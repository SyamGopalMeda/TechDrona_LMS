"""Guided learning paths: authoring, versions, articles, allocations, learner progress.

Authorization (backend-enforced; the web only mirrors it):

Single company (REMOVAL-PLAN §6 WS4): every path, article and allocation belongs to
``COMPANY_ORG_ID``; no organization is ever read from a request.

* ``path.manage`` — author paths and articles: a platform grant, or a batch-scoped trainer grant
  holding it (paths are company content).
* ``path.allocate`` (SEC-01) — a batch allocation (create, progress, revoke) needs the permission
  on THAT batch (platform grants cover every batch); there is no company-wide fallback. An
  individual-learner allocation needs a platform grant, or every learner must be an active
  student of a batch where the caller holds ``path.allocate`` (same rule to view / revoke it).
* Learners see an allocation only when it targets them (chosen learner, or active student of
  the allocated batch); anything else is 404.

Completion rules (never trusted from the client):

* reading / video / article steps: the learner must have opened the step (server timestamp) and
  a minimum dwell time must have passed (``min_dwell_seconds``: 10 % of the step's estimated
  time, clamped to 30 s … 5 min). Analytics has no per-path-step engagement feed, so the dwell
  check uses the server-recorded open time.
* assignment steps: only from learning outbox events — the learner's submission is graded AND
  the assignment's grades are released (state re-read from the database, payload not trusted).
* assessment steps: only from the assessments ``attempt.scored`` event — the attempt result is
  passed (or graded with no pass mark) and the attempt was not invalidated.
* strict flow: a step completed after its planned due date earns half its credits
  (``STRICT_LATE_FACTOR``); lenient flow always earns full credits.
* sequential: a step is locked until every earlier step (depth-first order) is completed.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from urllib.parse import urlsplit

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import auth as core_auth
from app.core.audit import audit
from app.core.auth import ScopeRef
from app.core.company import COMPANY_ORG_ID
from app.core.errors import ProblemError
from app.core.ids import uuid7
from app.core.principal import Principal
from app.core.time import to_rfc3339, utcnow
from app.modules.ai.service import require_app_enabled
from app.modules.paths import adapters, schedule
from app.modules.paths import store as st
from app.modules.paths.articles import sanitize_markdown, table_of_contents
from app.modules.paths.models import (
    LearningPath,
    LearningPathStep,
    LearningPathVersion,
    LearningPathVersionStep,
    PathAllocation,
    PathArticle,
    PathStepProgress,
)
from app.modules.rbac.catalogue import ADMIN_ROLE

LEAF_TYPES = ("reading", "video", "article", "assignment", "assessment")
STEP_TYPES = (*LEAF_TYPES, "super_step")
SELF_COMPLETE = ("reading", "video", "article")
LINK_FIELD = {
    "article": "article_id",
    "assignment": "assignment_id",
    "assessment": "test_id",
}
MAX_STEPS = 200
STRICT_LATE_FACTOR = Decimal("0.5")
DWELL_MIN_S, DWELL_MAX_S, DWELL_SHARE = 30, 300, Decimal("0.1")


def vf(field: str, code: str, message: str) -> ProblemError:
    return ProblemError("validation_failed", errors=[{"field": field, "code": code, "message": message}])


def _iso(d: date | datetime | None) -> str | None:
    if d is None:
        return None
    return to_rfc3339(d) if isinstance(d, datetime) else d.isoformat()


def _num(d: Decimal | None) -> float:
    return float(d or 0)


# --------------------------------------------------------------------------- embeds (D9)

_DOCS_KINDS = frozenset({"document", "spreadsheets", "presentation", "forms"})
_DOCS_ENDINGS = frozenset({"preview", "embed", "pub", "pubhtml", "viewform"})
_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,200}$")


def embeddable(url: str | None) -> bool:
    """Owner decision D9: a reading/video step URL may be shown in the learner's iframe only
    when it is one of these exact embed/preview forms (checked on every save and read):

    * ``https://www.youtube-nocookie.com/embed/<id>``
    * ``https://player.vimeo.com/video/<numeric id>``
    * ``https://docs.google.com/{document|spreadsheets|presentation|forms}/d/[e/]<id>/
      {preview|embed|pub|pubhtml|viewform}``
    * ``https://drive.google.com/file/d/<id>/preview``

    Anything else is kept as a plain link ("open in new tab"). No credentials, no port."""
    if not url:
        return False
    try:
        u = urlsplit(url)
        port = u.port
    except ValueError:
        return False
    if u.scheme != "https" or u.username or u.password or port not in (None, 443):
        return False
    host = (u.hostname or "").lower()
    parts = [x for x in u.path.split("/") if x]
    if host == "www.youtube-nocookie.com":
        return len(parts) == 2 and parts[0] == "embed" and bool(_ID_RE.match(parts[1]))
    if host == "player.vimeo.com":
        return len(parts) == 2 and parts[0] == "video" and parts[1].isdigit()
    if host == "drive.google.com":
        return (
            len(parts) == 4
            and parts[:2] == ["file", "d"]
            and bool(_ID_RE.match(parts[2]))
            and (parts[3] == "preview")
        )
    if host == "docs.google.com":
        if parts[:1] and parts[0] not in _DOCS_KINDS:
            return False
        rest = parts[1:]
        if rest[:2] == ["d", "e"]:
            rest = ["d", *rest[2:]]
        return len(rest) == 3 and rest[0] == "d" and bool(_ID_RE.match(rest[1])) and rest[2] in _DOCS_ENDINGS
    return False


# --------------------------------------------------------------------------- permissions


async def _has(request: Request | None, principal: Principal, perm: str, scope: ScopeRef) -> bool:
    return await core_auth.check_permission(principal, perm, scope, request)


COMPANY_SCOPE = ScopeRef("organization", COMPANY_ORG_ID)


async def _batch_exists(session: AsyncSession, batch_id: uuid.UUID) -> bool:
    return await adapters.batch_exists(session, batch_id)


async def has_company_scope(request: Request | None, principal: Principal, perm: str) -> bool:
    """``perm`` held company-wide (a platform grant; the company org is the only tenant)."""
    return await _has(request, principal, perm, COMPANY_SCOPE)


async def can_author(request: Request | None, principal: Principal, perm: str = "path.manage") -> bool:
    """Path / article authoring: company-wide grant, or a batch-scoped grant (trainer) holding
    ``perm``. Paths and articles are company content; batch trainers author them."""
    if await has_company_scope(request, principal, perm):
        return True
    for g in principal.grants:
        if g.scope_type == "batch" and g.scope_id is not None:
            if await _has(request, principal, perm, ScopeRef("batch", g.scope_id)):
                return True
    return False


async def require_author(request: Request | None, principal: Principal, perm: str = "path.manage") -> None:
    if not await can_author(request, principal, perm):
        raise ProblemError("permission_denied", permission=perm)
    _mark_used(request, perm)


def _mark_used(request: Request | None, perm: str) -> None:
    if request is not None:
        used = getattr(request.state, "permissions_used", None)
        if used is None:
            request.state.permissions_used = used = []
        used.append(perm)


async def allocatable_batches(request: Request | None, principal: Principal) -> set[uuid.UUID]:
    """Batches where the caller holds ``path.allocate`` through a batch-scoped grant."""
    out: set[uuid.UUID] = set()
    for g in principal.grants:
        if g.scope_type == "batch" and g.scope_id is not None and g.scope_id not in out:
            if await _has(request, principal, "path.allocate", ScopeRef("batch", g.scope_id)):
                out.add(g.scope_id)
    return out


async def _active_batch_students(
    session: AsyncSession, batch_ids: set[uuid.UUID], user_ids: list[uuid.UUID]
) -> set[uuid.UUID]:
    """Of ``user_ids``, the active student members of any of ``batch_ids``."""
    return await adapters.active_batch_students(session, batch_ids, user_ids)


async def can_allocate_users(
    request: Request | None, session: AsyncSession, principal: Principal, user_ids: list[uuid.UUID]
) -> bool:
    """Individual-learner allocation (SEC-01): a company-wide ``path.allocate`` grant, or every
    learner is an active student of a batch where the caller holds ``path.allocate``."""
    if await has_company_scope(request, principal, "path.allocate"):
        return True
    if not user_ids:
        return False
    mine = await allocatable_batches(request, principal)
    return set(user_ids) <= await _active_batch_students(session, mine, user_ids)


async def require_allocate_batch(request: Request | None, principal: Principal, batch_id: uuid.UUID) -> None:
    """``path.allocate`` on exactly this batch (platform grants cover it). No company fallback."""
    if not await core_auth.check_permission(principal, "path.allocate", ScopeRef("batch", batch_id), request):
        raise ProblemError("permission_denied", permission="path.allocate")
    _mark_used(request, "path.allocate")


async def require_audience_scope(
    request: Request | None,
    session: AsyncSession,
    principal: Principal,
    batch_ids: list[uuid.UUID],
    user_ids: list[uuid.UUID],
) -> None:
    """An article's audience (or a path's live allocations) reaches only learners the caller
    manages: ``path.manage`` on every batch (platform grants cover all) and, for people,
    ``can_allocate_users``. A company-wide grant passes. RBAC audit 2026-11-13: a batch-A
    trainer could publish into, unpublish, rewrite or delete content of batch B."""
    if await has_company_scope(request, principal, "path.manage"):
        return
    for b in dict.fromkeys(batch_ids):
        if not await core_auth.check_permission(principal, "path.manage", ScopeRef("batch", b), request):
            raise ProblemError("permission_denied", permission="path.manage")
    if user_ids and not await can_allocate_users(request, session, principal, list(user_ids)):
        raise ProblemError("permission_denied", permission="path.allocate")


async def staff_context(request: Request, session: AsyncSession, principal: Principal) -> dict[str, Any]:
    """What the caller may do in paths, and the batches they may allocate to."""
    company_alloc = await has_company_scope(request, principal, "path.allocate")
    mine = set() if company_alloc else await allocatable_batches(request, principal)
    rows = await adapters.active_batches(session, None if company_alloc else mine)
    return {
        "can_author": await can_author(request, principal, "path.manage"),
        "can_allocate_any_learner": company_alloc,
        "batches": [{"id": str(b["id"]), "name": b["name"], "code": b["code"]} for b in rows],
    }


# --------------------------------------------------------------------------- serialisation


@dataclass
class StepNode:
    row: Any
    children: list[StepNode]


def _tree(rows: list[Any]) -> list[StepNode]:
    tops = sorted((r for r in rows if r.parent_key is None), key=lambda r: r.position)
    kids: dict[uuid.UUID, list[Any]] = {}
    for r in rows:
        if r.parent_key is not None:
            kids.setdefault(r.parent_key, []).append(r)
    return [
        StepNode(t, [StepNode(c, []) for c in sorted(kids.get(t.step_key, []), key=lambda r: r.position)])
        for t in tops
    ]


def _leaves(tree: list[StepNode]) -> list[Any]:
    out: list[Any] = []
    for n in tree:
        if n.row.step_type == "super_step":
            out += [c.row for c in n.children]
        else:
            out.append(n.row)
    return out


def _totals(rows: list[Any]) -> tuple[Decimal, int, int]:
    leaves = _leaves(_tree(rows))
    return (
        sum((Decimal(r.est_hours) for r in leaves), Decimal("0")),
        sum(r.credits for r in leaves),
        len(leaves),
    )


def _step_out(n: StepNode) -> dict[str, Any]:
    r = n.row
    children = [_step_out(c) for c in n.children]
    hours = sum((c["est_hours"] for c in children), 0.0) if r.step_type == "super_step" else _num(r.est_hours)
    credits = sum(c["credits"] for c in children) if r.step_type == "super_step" else r.credits
    return {
        "step_key": str(r.step_key),
        "step_type": r.step_type,
        "title": r.title,
        "description_md": r.description_md,
        "est_hours": round(hours, 2),
        "credits": credits,
        "url": r.url,
        "embeddable": embeddable(r.url),
        "lesson_id": str(r.lesson_id) if r.lesson_id else None,
        "assignment_id": str(r.assignment_id) if r.assignment_id else None,
        "test_id": str(r.test_id) if r.test_id else None,
        "article_id": str(r.article_id) if r.article_id else None,
        "children": children,
    }


async def _draft_rows(session: AsyncSession, path_id: uuid.UUID) -> list[LearningPathStep]:
    return await st.draft_rows(session, path_id)


async def _version_rows(session: AsyncSession, version_id: uuid.UUID) -> list[LearningPathVersionStep]:
    return await st.version_rows(session, version_id)


def _summary(p: LearningPath, rows: list[Any]) -> dict[str, Any]:
    hours, credits, n = _totals(rows)
    return {
        "id": str(p.id),
        "organization_id": str(p.organization_id),
        "title": p.title,
        "description_md": p.description_md,
        "level": p.level,
        "status": p.status,
        "has_unpublished_changes": p.has_unpublished_changes,
        "version_no": p.version_no,
        "step_count": n,
        "total_credits": credits,
        "total_hours": _num(hours),
        "source": p.source,
        "updated_at": _iso(p.updated_at),
    }


async def path_detail(session: AsyncSession, p: LearningPath) -> dict[str, Any]:
    rows = await _draft_rows(session, p.id)
    out = _summary(p, rows)
    out["steps"] = [_step_out(n) for n in _tree(rows)]
    allocs = await st.allocations_for_path(session, p.id)
    out["allocations"] = [await allocation_out(session, a) for a in allocs]
    return out


# --------------------------------------------------------------------------- paths


async def get_path(session: AsyncSession, path_id: uuid.UUID) -> LearningPath:
    p = await st.get_path(session, path_id)
    if p is None:
        raise ProblemError("not_found")
    return p


async def managed_path(
    request: Request,
    session: AsyncSession,
    principal: Principal,
    path_id: uuid.UUID,
    perm: str = "path.manage",
) -> LearningPath:
    p = await get_path(session, path_id)
    await require_author(request, principal, perm)
    return p


async def list_paths(
    request: Request,
    session: AsyncSession,
    principal: Principal,
    *,
    q: str | None,
    status: str | None,
) -> dict[str, Any]:
    if not await can_author(request, principal, "path.manage"):
        return {"data": []}
    rows = await st.list_paths(session, status, q)
    return {"data": [_summary(p, await _draft_rows(session, p.id)) for p in rows]}


async def create_path(
    request: Request,
    session: AsyncSession,
    principal: Principal,
    *,
    title: str,
    description_md: str,
    level: str,
    source: str = "manual",
) -> LearningPath:
    organization_id = COMPANY_ORG_ID
    await require_author(request, principal, "path.manage")
    await require_app_enabled(session, app_key="paths")
    p = LearningPath(
        id=uuid7(),
        organization_id=organization_id,
        title=title.strip(),
        description_md=description_md,
        level=level,
        source=source,
        status="draft",
        version_no=0,
        has_unpublished_changes=True,
        created_by=principal.user_id,
    )
    await st.insert_path(session, p)
    await audit(
        session,
        principal,
        "path.create",
        "learning_path",
        p.id,
        organization_id=organization_id,
        after={"title": p.title, "source": source},
    )
    return p


async def update_path(
    session: AsyncSession, principal: Principal, p: LearningPath, changes: dict[str, Any]
) -> None:
    if p.status == "archived":
        raise ProblemError("invalid_state_transition", detail="This path is archived.")
    for k in ("title", "description_md", "level"):
        if changes.get(k) is not None:
            setattr(p, k, changes[k].strip() if k == "title" else changes[k])
    p.has_unpublished_changes = True
    p.updated_at = utcnow()
    await st.save_path(session, p)
    await audit(
        session,
        principal,
        "path.update",
        "learning_path",
        p.id,
        organization_id=p.organization_id,
        after={k: v for k, v in changes.items() if v is not None and k != "description_md"},
    )


async def archive_path(
    session: AsyncSession, principal: Principal, p: LearningPath, request: Request | None = None
) -> None:
    # Archiving revokes every live allocation of the path: allowed only if the caller could
    # revoke each one directly (DELETE /path-allocations/{id}, SEC-01) -- RBAC audit 2026-11-13.
    for a in await st.allocations_for_path(session, p.id):
        if a.status == "active":
            await managed_allocation(request, session, principal, a.id)
    p.status = "archived"
    await st.save_path(session, p)
    await st.revoke_active_for_path(session, p.id)
    await audit(session, principal, "path.archive", "learning_path", p.id, organization_id=p.organization_id)


async def _check_link(session: AsyncSession, org_id: uuid.UUID, field: str, value: uuid.UUID) -> None:
    from app.modules.catalog import api as catalog_api

    ok: Any
    if field == "assignment_id":
        ok = await adapters.assignment_in_org(session, value, org_id) or None
    elif field == "test_id":
        ok = await adapters.test_in_org(session, value, org_id) or None
    elif field == "article_id":
        ok = await st.article_in_org(session, value, org_id) or None
    else:
        ok = (await catalog_api.get_lessons(session, [value])).get(value)
    if ok is None:
        raise vf(field, "not_found", "The linked item does not exist in this organization")


async def replace_steps(
    session: AsyncSession, principal: Principal, p: LearningPath, steps: list[dict[str, Any]]
) -> None:
    """Full replace of the draft step tree (add / delete / reorder in one call)."""
    if p.status == "archived":
        raise ProblemError("invalid_state_transition", detail="This path is archived.")
    seen: set[uuid.UUID] = set()
    count = 0
    for i, s in enumerate(steps):
        count += 1
        kids = s.get("children") or []
        if kids and s["step_type"] != "super_step":
            raise vf(f"steps[{i}].children", "not_allowed", "Only a super-step can hold steps")
        for j, c in enumerate(kids):
            count += 1
            if c["step_type"] == "super_step" or c.get("children"):
                raise vf(f"steps[{i}].children[{j}].step_type", "not_allowed", "Super-steps cannot be nested")
    if count > MAX_STEPS:
        raise vf("steps", "too_many", f"A path can have at most {MAX_STEPS} steps")
    new_rows: list[LearningPathStep] = []
    for i, s in enumerate(steps):
        key = s.get("step_key") or uuid7()
        if key in seen:
            raise vf(f"steps[{i}].step_key", "duplicate", "Duplicate step")
        seen.add(key)
        new_rows.append(await _add_step(session, p, s, key, None, i, f"steps[{i}]"))
        for j, c in enumerate(s.get("children") or []):
            ckey = c.get("step_key") or uuid7()
            if ckey in seen:
                raise vf(f"steps[{i}].children[{j}].step_key", "duplicate", "Duplicate step")
            seen.add(ckey)
            new_rows.append(await _add_step(session, p, c, ckey, key, j, f"steps[{i}].children[{j}]"))
    p.has_unpublished_changes = True
    p.updated_at = utcnow()
    await st.replace_draft(session, p, new_rows)
    await audit(
        session,
        principal,
        "path.steps_save",
        "learning_path",
        p.id,
        organization_id=p.organization_id,
        after={"steps": count},
    )


async def _add_step(
    session: AsyncSession,
    p: LearningPath,
    s: dict[str, Any],
    key: uuid.UUID,
    parent: uuid.UUID | None,
    pos: int,
    field: str,
) -> LearningPathStep:
    t = s["step_type"]
    if t not in STEP_TYPES:
        raise vf(f"{field}.step_type", "invalid", "Unknown step type")
    links: dict[str, Any] = {
        "url": None,
        "lesson_id": None,
        "assignment_id": None,
        "test_id": None,
        "article_id": None,
    }
    if t in ("reading", "video"):
        url = (s.get("url") or "").strip() or None
        if url and not url.lower().startswith("https://"):
            raise vf(f"{field}.url", "insecure", "Use an https:// link")
        links["url"] = url
        links["lesson_id"] = s.get("lesson_id")
    elif t in LINK_FIELD:
        links[LINK_FIELD[t]] = s.get(LINK_FIELD[t])
    for name in ("lesson_id", "assignment_id", "test_id", "article_id"):
        if links[name] is not None:
            await _check_link(session, p.organization_id, name, links[name])
    return LearningPathStep(
        id=uuid7(),
        path_id=p.id,
        organization_id=p.organization_id,
        step_key=key,
        parent_key=parent,
        position=pos,
        step_type=t,
        title=s["title"].strip(),
        description_md=s.get("description_md") or "",
        est_hours=Decimal("0") if t == "super_step" else Decimal(str(s.get("est_hours") or 0)),
        credits=0 if t == "super_step" else int(s.get("credits") or 0),
        **links,
    )


def _publish_errors(rows: list[LearningPathStep]) -> list[dict[str, str]]:
    errors: list[dict[str, str]] = []
    tree = _tree(rows)
    if not _leaves(tree):
        errors.append({"field": "steps", "code": "empty", "message": "Add at least one step"})
    for n in tree:
        if n.row.step_type == "super_step" and not n.children:
            errors.append(
                {
                    "field": f"steps.{n.row.step_key}",
                    "code": "empty_super_step",
                    "message": f"Super-step “{n.row.title}” has no steps",
                }
            )
    for r in _leaves(tree):
        f = f"steps.{r.step_key}"
        if r.step_type in ("reading", "video") and not (r.url or r.lesson_id):
            errors.append(
                {"field": f, "code": "link_required", "message": f"“{r.title}” needs a link or lesson"}
            )
        elif r.step_type in LINK_FIELD and getattr(r, LINK_FIELD[r.step_type]) is None:
            errors.append(
                {"field": f, "code": "link_required", "message": f"Attach the {r.step_type} for “{r.title}”"}
            )
    return errors


async def publish_path(session: AsyncSession, principal: Principal, p: LearningPath) -> LearningPathVersion:
    await require_app_enabled(session, app_key="paths")
    if p.status == "archived":
        raise ProblemError("invalid_state_transition", detail="This path is archived.")
    rows = await _draft_rows(session, p.id)
    errors = _publish_errors(rows)
    if errors:
        raise ProblemError("validation_failed", errors=errors)
    hours, credits, _ = _totals(rows)
    v = LearningPathVersion(
        id=uuid7(),
        path_id=p.id,
        organization_id=p.organization_id,
        version_no=p.version_no + 1,
        title=p.title,
        description_md=p.description_md,
        level=p.level,
        total_hours=hours,
        total_credits=credits,
        published_by=principal.user_id,
    )
    vrows = [
        LearningPathVersionStep(
            id=uuid7(),
            path_version_id=v.id,
            organization_id=p.organization_id,
            step_key=r.step_key,
            parent_key=r.parent_key,
            position=r.position,
            step_type=r.step_type,
            title=r.title,
            description_md=r.description_md,
            est_hours=r.est_hours,
            credits=r.credits,
            url=r.url,
            lesson_id=r.lesson_id,
            assignment_id=r.assignment_id,
            test_id=r.test_id,
            article_id=r.article_id,
        )
        for r in rows
    ]
    p.version_no = v.version_no
    p.current_version_id = v.id
    p.status = "published"
    p.has_unpublished_changes = False
    await st.publish(session, p, v, vrows)
    await audit(
        session,
        principal,
        "path.publish",
        "learning_path",
        p.id,
        organization_id=p.organization_id,
        after={"version_no": v.version_no, "total_credits": credits, "total_hours": str(hours)},
    )
    return v


# --------------------------------------------------------------------------- AI draft


async def ai_generate(
    request: Request, session: AsyncSession, principal: Principal, body: dict[str, Any]
) -> LearningPath:
    from app.modules.ai import service as ai

    org = COMPANY_ORG_ID
    await require_author(request, principal, "path.manage")
    spec = ai.PathGenSpec(
        title=body["topic"],
        level=body["level"],
        style=body["style"],
        target_hours=body["target_hours"],
        approx_steps=body["approx_steps"],
        guidelines=body.get("guidelines"),
    )
    try:
        draft = await ai.generate_path(session, user_id=principal.user_id, spec=spec)
    except ai.AIError as e:
        status = {"ai_disabled": 403, "ai_quota_exceeded": 429}.get(e.code, 503)
        raise ProblemError(e.code, status, "AI is not available", str(e) or None) from e
    p = await create_path(
        request,
        session,
        principal,
        title=str(draft.get("title") or body["topic"])[:200],
        description_md=str(draft.get("description") or "")[:5000],
        level=body["level"],
        source="ai",
    )
    steps: list[dict[str, Any]] = []
    for raw in list(draft.get("steps") or [])[:60]:
        t = str(raw.get("step_type") or "reading").lower().replace("-", "_")
        t = {"doc": "reading", "docs": "reading", "exam": "assessment", "quiz": "assessment"}.get(t, t)
        if t not in LEAF_TYPES:
            t = "reading"
        if body["style"] == "textbook":
            t = "article"
        title = str(raw.get("title") or "Step")[:300]
        desc = str(raw.get("description_md") or "")
        step: dict[str, Any] = {
            "step_type": t,
            "title": title,
            "description_md": desc[:5000],
            "est_hours": min(Decimal(str(raw.get("est_hours") or 0)), Decimal(1000)),
            "credits": max(0, min(int(raw.get("credits") or 0), 10000)),
        }
        url = raw.get("url")
        if t in ("reading", "video") and isinstance(url, str) and url.lower().startswith("https://"):
            step["url"] = url[:2048]
        if t == "article":
            art = await _new_article(
                session,
                principal,
                org,
                title=title[:200],
                subtitle="",
                level=body["level"],
                est_minutes=int(Decimal(step["est_hours"]) * 60),
                body_md=f"# {title}\n\n{desc}",
            )
            step["article_id"] = art.id
        steps.append(step)
    await replace_steps(session, principal, p, steps)
    await audit(
        session,
        principal,
        "path.ai_generate",
        "learning_path",
        p.id,
        organization_id=org,
        after={"style": body["style"], "steps": len(steps)},
    )
    return p


# --------------------------------------------------------------------------- link pickers


async def link_options(
    request: Request, session: AsyncSession, principal: Principal, kind: str, q: str | None
) -> dict[str, Any]:
    from app.modules.catalog import api as catalog_api

    org_id = COMPANY_ORG_ID
    await require_author(request, principal, "path.manage")
    like = adapters.like_pattern(q)
    out: list[dict[str, Any]] = []
    if kind == "assignment":
        rows = await adapters.assignment_options(session, org_id, q)
        out = [{"id": str(i), "title": t, "meta": f"{_num(m):g} marks"} for i, t, m in rows]
    elif kind == "test":
        rows = await adapters.test_options(session, org_id, q)
        out = [{"id": str(i), "title": t, "meta": f"{(d or 0) // 60} min"} for i, t, d in rows]
    elif kind == "article":
        rows = await st.article_options(session, org_id, q)
        out = [{"id": str(i), "title": t, "meta": s} for i, t, s in rows]
    elif kind == "lesson":
        found = await catalog_api.search_published_lessons(session, org_id, like, limit=25)
        out = [{"id": str(i), "title": t, "meta": f"{c} · {lt}"} for i, t, lt, c in found]
    else:
        raise vf("kind", "invalid", "Unknown kind")
    return {"data": out}


async def _names(session: AsyncSession, user_ids: list[uuid.UUID]) -> dict[uuid.UUID, tuple[str, str]]:
    """Display name + email for staff views (after the caller's permission check)."""
    return await adapters.user_names(session, user_ids)


def shows_learner_email(principal: Principal) -> bool:
    """Learner emails are Admin-only here (QA 2026-11, F9): trainers and content managers
    allocate and follow paths by name; an email is beyond what they need."""
    return principal.has_role(ADMIN_ROLE, "platform")


async def batch_members(
    request: Request, session: AsyncSession, principal: Principal, batch_id: uuid.UUID, q: str | None
) -> dict[str, Any]:
    """Allocate picker: active student members of one batch. Needs ``path.allocate`` on that
    batch (platform grants cover every batch). Replaces the removed ``/paths/org-members``."""
    if not await _batch_exists(session, batch_id):
        raise ProblemError("not_found")
    await require_allocate_batch(request, principal, batch_id)
    email = shows_learner_email(principal)
    rows = await adapters.batch_people(session, batch_id, q, search_email=email)
    return {
        "data": [
            {"user_id": str(r[0]), "full_name": r[2] or "", "email": r[1] if email else None} for r in rows
        ]
    }


# --------------------------------------------------------------------------- allocations


async def _plan_for(
    p: LearningPath, session: AsyncSession, start: date, pace: dict[str, Any]
) -> dict[str, Any]:
    if p.current_version_id is None:
        rows: list[Any] = await _draft_rows(session, p.id)
        total = _totals(rows)[0]
    else:
        v = await st.get_version(session, p.current_version_id)
        assert v is not None
        total = Decimal(v.total_hours)
    return schedule.plan(start, total, pace)


def _plan_out(pl: dict[str, Any]) -> dict[str, Any]:
    return {
        "per_day": {d: float(h) for d, h in pl["per_day"].items()},
        "weekly_hours": float(pl["weekly_hours"]),
        "total_hours": float(pl["total_hours"]),
        "finish_date": pl["finish_date"].isoformat(),
        "days": pl["days"],
    }


async def allocation_preview(session: AsyncSession, p: LearningPath, body: dict[str, Any]) -> dict[str, Any]:
    start = body.get("start_date") or utcnow().date()
    return _plan_out(await _plan_for(p, session, start, body["pace"]))


async def _batch_students(session: AsyncSession, batch_id: uuid.UUID) -> list[uuid.UUID]:
    return await adapters.batch_students(session, batch_id)


async def allocation_learners(session: AsyncSession, a: PathAllocation) -> list[uuid.UUID]:
    if a.target_type == "batch" and a.batch_id:
        return await _batch_students(session, a.batch_id)
    return list(a.user_ids)


async def allocation_out(session: AsyncSession, a: PathAllocation) -> dict[str, Any]:
    batch_name = None
    if a.batch_id:
        batch_name = await adapters.batch_name(session, a.batch_id)
    ver = await st.get_version(session, a.path_version_id)
    assert ver is not None
    vno = ver.version_no
    return {
        "id": str(a.id),
        "path_id": str(a.path_id),
        "path_version_id": str(a.path_version_id),
        "version_no": vno,
        "target_type": a.target_type,
        "batch_id": str(a.batch_id) if a.batch_id else None,
        "batch_name": batch_name,
        "user_ids": [str(u) for u in a.user_ids],
        "flow": a.flow,
        "sequential": a.sequential,
        "start_date": a.start_date.isoformat(),
        "pace": a.pace,
        "weekly_hours": _num(a.weekly_hours),
        "total_hours": _num(a.total_hours),
        "finish_date": a.finish_date.isoformat(),
        "status": a.status,
        "learner_count": len(await allocation_learners(session, a)),
        "created_at": _iso(a.created_at),
    }


async def create_allocation(
    request: Request, session: AsyncSession, principal: Principal, p: LearningPath, body: dict[str, Any]
) -> PathAllocation:
    await require_app_enabled(session, app_key="paths")
    if p.status == "archived" or p.current_version_id is None:
        raise ProblemError("invalid_state_transition", detail="Publish the path before allocating it.")
    user_ids: list[uuid.UUID] = []
    batch_id = None
    if body["target_type"] == "batch":
        batch_id = body.get("batch_id")
        if batch_id is None:
            raise vf("batch_id", "required", "Choose a batch")
        if not await _batch_exists(session, batch_id):
            raise vf("batch_id", "not_found", "Choose an existing batch")
        await require_allocate_batch(request, principal, batch_id)
    else:
        user_ids = list(dict.fromkeys(body.get("user_ids") or []))
        if not user_ids:
            raise vf("user_ids", "required", "Choose at least one learner")
        if len(user_ids) > 500:
            raise vf("user_ids", "too_many", "At most 500 learners per allocation")
        # SEC-01: company-wide path.allocate, or every learner is an active student of a batch
        # where the caller holds path.allocate.
        if not await can_allocate_users(request, session, principal, user_ids):
            raise ProblemError("permission_denied", permission="path.allocate")
        _mark_used(request, "path.allocate")
        members = await adapters.active_company_members(session, user_ids)
        if set(user_ids) - members:
            raise vf("user_ids", "not_member", "Every learner must be an active batch learner")
    start = body.get("start_date") or utcnow().date()
    pl = await _plan_for(p, session, start, body["pace"])
    a = PathAllocation(
        id=uuid7(),
        organization_id=p.organization_id,
        path_id=p.id,
        path_version_id=p.current_version_id,
        target_type=body["target_type"],
        batch_id=batch_id,
        user_ids=user_ids,
        flow=body["flow"],
        sequential=bool(body["sequential"]),
        start_date=start,
        pace={"mode": body["pace"].get("mode", "every_day"), "per_day": _plan_out(pl)["per_day"]},
        weekly_hours=pl["weekly_hours"],
        total_hours=pl["total_hours"],
        finish_date=pl["finish_date"],
        status="active",
        created_by=principal.user_id,
    )
    await st.insert_allocation(session, a)
    await audit(
        session,
        principal,
        "path.allocate",
        "path_allocation",
        a.id,
        organization_id=p.organization_id,
        after={
            "path_id": str(p.id),
            "target_type": a.target_type,
            "batch_id": str(batch_id) if batch_id else None,
            "learners": len(user_ids),
            "flow": a.flow,
            "sequential": a.sequential,
            "finish_date": a.finish_date.isoformat(),
        },
    )
    return a


async def managed_allocation(
    request: Request, session: AsyncSession, principal: Principal, allocation_id: uuid.UUID
) -> PathAllocation:
    a = await st.get_allocation(session, allocation_id)
    if a is None:
        raise ProblemError("not_found")
    if a.batch_id is not None:
        # SEC-01: a batch allocation is managed only with path.allocate on THAT batch (platform
        # grants cover it). No company-wide fallback for batch-scoped trainers of other batches.
        await require_allocate_batch(request, principal, a.batch_id)
        return a
    if not await can_allocate_users(request, session, principal, list(a.user_ids)):
        raise ProblemError("permission_denied", permission="path.allocate")
    _mark_used(request, "path.allocate")
    return a


async def revoke_allocation(session: AsyncSession, principal: Principal, a: PathAllocation) -> None:
    if a.status == "revoked":
        return
    a.status = "revoked"
    a.revoked_at = utcnow()
    await st.save_allocation(session, a)
    await audit(
        session,
        principal,
        "path.allocation_revoke",
        "path_allocation",
        a.id,
        organization_id=a.organization_id,
    )


async def allocation_progress(
    session: AsyncSession, a: PathAllocation, *, show_email: bool = False
) -> dict[str, Any]:
    rows = await _version_rows(session, a.path_version_id)
    leaves = _leaves(_tree(rows))
    learners = await allocation_learners(session, a)
    prog = await st.allocation_progress_rows(session, a.id)
    by_user: dict[uuid.UUID, list[PathStepProgress]] = {}
    for r in prog:
        by_user.setdefault(r.user_id, []).append(r)
    names = await _names(session, learners)
    leaf_keys = {r.step_key for r in leaves}
    total_credits = sum(r.credits for r in leaves)
    today = utcnow().date()
    dues = _due_map(a, leaves)
    out = []
    for uid in learners:
        mine = [r for r in by_user.get(uid, []) if r.step_key in leaf_keys]
        done = {r.step_key for r in mine if r.status == "completed"}
        behind = any(d is not None and d < today and k not in done for k, d in dues.items())
        last = max((r.updated_at for r in mine), default=None)
        out.append(
            {
                "user_id": str(uid),
                "full_name": names.get(uid, ("", ""))[0],
                "email": names.get(uid, ("", ""))[1] if show_email else None,
                "completed_steps": len(done),
                "total_steps": len(leaves),
                "credits_earned": sum(r.credits_awarded for r in mine),
                "total_credits": total_credits,
                "pct": round(100 * len(done) / len(leaves), 1) if leaves else 0.0,
                "last_activity_at": _iso(last),
                "behind": behind,
            }
        )
    p = await get_path(session, a.path_id)
    return {
        "allocation": await allocation_out(session, a),
        "path": {"id": str(p.id), "title": p.title},
        "steps": [
            {"step_key": str(r.step_key), "title": r.title, "step_type": r.step_type, "credits": r.credits}
            for r in leaves
        ],
        "learners": out,
    }


# --------------------------------------------------------------------------- learner


def _per_day(a: PathAllocation) -> dict[str, Decimal]:
    raw = (a.pace or {}).get("per_day") or {}
    return {d: Decimal(str(raw.get(d, 0))) for d in schedule.DAYS}


def _due_map(a: PathAllocation, leaves: list[Any]) -> dict[uuid.UUID, date | None]:
    """Planned due date per leaf step (strict flow only)."""
    if a.flow != "strict" or not leaves:
        return {r.step_key: None for r in leaves}
    cum: list[Decimal] = []
    acc = Decimal("0")
    for r in leaves:
        acc += Decimal(r.est_hours)
        cum.append(acc)
    try:
        dates = schedule.due_dates(a.start_date, cum, _per_day(a))
    except ProblemError:
        return {r.step_key: None for r in leaves}
    return {r.step_key: d for r, d in zip(leaves, dates, strict=True)}


def min_dwell_seconds(step: Any) -> int:
    if step.step_type not in SELF_COMPLETE:
        return 0
    s = int(Decimal(step.est_hours) * 3600 * DWELL_SHARE)
    return max(DWELL_MIN_S, min(DWELL_MAX_S, s))


def _award(a: PathAllocation, step: Any, due: date | None, at: datetime) -> int:
    if a.flow == "strict" and due is not None and at.date() > due:
        return int(Decimal(step.credits) * STRICT_LATE_FACTOR)
    return int(step.credits)


@dataclass
class Player:
    alloc: PathAllocation
    version: LearningPathVersion
    rows: list[LearningPathVersionStep]
    progress: dict[uuid.UUID, PathStepProgress]

    def __post_init__(self) -> None:
        self.tree = _tree(self.rows)
        self.leaves = _leaves(self.tree)
        self.dues = _due_map(self.alloc, self.leaves)

    def locked(self, step_key: uuid.UUID) -> bool:
        if not self.alloc.sequential:
            return False
        for r in self.leaves:
            if r.step_key == step_key:
                return False
            pr = self.progress.get(r.step_key)
            if pr is None or pr.status != "completed":
                return True
        return False

    def leaf(self, step_key: uuid.UUID) -> LearningPathVersionStep | None:
        return next((r for r in self.rows if r.step_key == step_key), None)

    def _leaf_out(self, r: Any, number: str, depth: int) -> dict[str, Any]:
        pr = self.progress.get(r.step_key)
        if pr is not None and pr.status == "completed":
            state = "completed"
        elif self.locked(r.step_key):
            state = "locked"
        elif pr is not None:
            state = "in_progress"
        else:
            state = "available"
        d = self.dues.get(r.step_key)
        return {
            "step_key": str(r.step_key),
            "parent_key": str(r.parent_key) if r.parent_key else None,
            "number": number,
            "depth": depth,
            "step_type": r.step_type,
            "title": r.title,
            "description_md": r.description_md,
            "est_hours": _num(r.est_hours),
            "credits": r.credits,
            "url": r.url,
            "embeddable": embeddable(r.url),
            "lesson_id": str(r.lesson_id) if r.lesson_id else None,
            "assignment_id": str(r.assignment_id) if r.assignment_id else None,
            "test_id": str(r.test_id) if r.test_id else None,
            "article_id": str(r.article_id) if r.article_id else None,
            "state": state,
            "credits_awarded": pr.credits_awarded if pr else 0,
            "due_date": d.isoformat() if d else None,
            "opened_at": _iso(pr.opened_at) if pr else None,
            "completed_at": _iso(pr.completed_at) if pr else None,
            "min_dwell_seconds": min_dwell_seconds(r),
        }

    def steps(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for i, n in enumerate(self.tree, 1):
            if n.row.step_type != "super_step":
                out.append(self._leaf_out(n.row, str(i), 0))
                continue
            kids = [self._leaf_out(c.row, f"{i}.{j}", 1) for j, c in enumerate(n.children, 1)]
            states = {k["state"] for k in kids}
            if kids and states == {"completed"}:
                st = "completed"
            elif states & {"in_progress", "completed"}:
                st = "in_progress"
            elif kids and kids[0]["state"] == "locked":
                st = "locked"
            else:
                st = "available"
            r = n.row
            out.append(
                {
                    **self._leaf_out(r, str(i), 0),
                    "state": st,
                    "est_hours": round(sum(k["est_hours"] for k in kids), 2),
                    "credits": sum(k["credits"] for k in kids),
                    "credits_awarded": sum(k["credits_awarded"] for k in kids),
                    "due_date": None,
                    "opened_at": None,
                    "completed_at": None,
                }
            )
            out += kids
        return out

    def totals(self) -> tuple[int, int, float, int]:
        done = [r for r in self.leaves if (p := self.progress.get(r.step_key)) and p.status == "completed"]
        earned = sum(p.credits_awarded for r in self.leaves if (p := self.progress.get(r.step_key)))
        total = sum(r.credits for r in self.leaves)
        pct = round(100 * len(done) / len(self.leaves), 1) if self.leaves else 0.0
        return earned, total, pct, len(done)


async def _player(session: AsyncSession, a: PathAllocation, user_id: uuid.UUID) -> Player:
    v = await st.get_version(session, a.path_version_id)
    assert v is not None
    rows = await _version_rows(session, v.id)
    prog = {r.step_key: r for r in await st.user_progress(session, a.id, user_id)}
    return Player(a, v, rows, prog)


async def my_allocation(
    session: AsyncSession, principal: Principal, allocation_id: uuid.UUID
) -> PathAllocation:
    found = await st.user_allocations(session, principal.user_id, allocation_id=allocation_id)
    if not found:
        raise ProblemError("not_found")
    return found[0]


async def my_paths(session: AsyncSession, principal: Principal) -> dict[str, Any]:
    allocs = await st.user_allocations(session, principal.user_id)
    out = []
    for a in allocs:
        pl = await _player(session, a, principal.user_id)
        earned, total, pct, done = pl.totals()
        out.append(
            {
                "allocation_id": str(a.id),
                "path_id": str(a.path_id),
                "title": pl.version.title,
                "description_md": pl.version.description_md,
                "flow": a.flow,
                "sequential": a.sequential,
                "step_count": len(pl.leaves),
                "completed_count": done,
                "total_credits": total,
                "credits_earned": earned,
                "pct": pct,
                "total_hours": _num(pl.version.total_hours),
                "start_date": a.start_date.isoformat(),
                "finish_date": a.finish_date.isoformat(),
                "started": bool(pl.progress),
            }
        )
    return {"data": out}


def _player_out(pl: Player) -> dict[str, Any]:
    earned, total, pct, _ = pl.totals()
    a = pl.alloc
    return {
        "allocation_id": str(a.id),
        "path_id": str(a.path_id),
        "title": pl.version.title,
        "description_md": pl.version.description_md,
        "flow": a.flow,
        "sequential": a.sequential,
        "start_date": a.start_date.isoformat(),
        "finish_date": a.finish_date.isoformat(),
        "credits_earned": earned,
        "total_credits": total,
        "pct": pct,
        "steps": pl.steps(),
    }


async def player_view(
    session: AsyncSession, principal: Principal, allocation_id: uuid.UUID
) -> dict[str, Any]:
    a = await my_allocation(session, principal, allocation_id)
    return _player_out(await _player(session, a, principal.user_id))


def _step_view(pl: Player, step_key: uuid.UUID) -> dict[str, Any]:
    return next(s for s in pl.steps() if s["step_key"] == str(step_key))


async def open_step(
    session: AsyncSession, principal: Principal, allocation_id: uuid.UUID, step_key: uuid.UUID
) -> dict[str, Any]:
    a = await my_allocation(session, principal, allocation_id)
    await require_app_enabled(session, app_key="paths")
    pl = await _player(session, a, principal.user_id)
    step = pl.leaf(step_key)
    if step is None:
        raise ProblemError("not_found")
    if step.step_type != "super_step":
        if pl.locked(step_key):
            raise ProblemError(
                "step_locked",
                409,
                "Finish the earlier steps first",
                "This path is sequential: complete the previous steps to unlock this one.",
            )
        await st.open_progress(
            session,
            {
                "id": uuid7(),
                "allocation_id": a.id,
                "organization_id": a.organization_id,
                "user_id": principal.user_id,
                "step_key": step_key,
                "status": "in_progress",
                "opened_at": utcnow(),
                "source": "learner",
            },
        )
        pl = await _player(session, a, principal.user_id)
    return _step_view(pl, step_key)


async def complete_step(
    session: AsyncSession, principal: Principal, allocation_id: uuid.UUID, step_key: uuid.UUID
) -> dict[str, Any]:
    a = await my_allocation(session, principal, allocation_id)
    await require_app_enabled(session, app_key="paths")
    pl = await _player(session, a, principal.user_id)
    step = pl.leaf(step_key)
    if step is None:
        raise ProblemError("not_found")
    if step.step_type not in SELF_COMPLETE:
        raise ProblemError(
            "completion_by_evaluation",
            409,
            "Completed by evaluation",
            "This step completes when your work is evaluated "
            "(assignment graded and released, or test passed).",
        )
    if pl.locked(step_key):
        raise ProblemError("step_locked", 409, "Finish the earlier steps first")
    pr = pl.progress.get(step_key)
    if pr is None or pr.opened_at is None:
        raise ProblemError("invalid_state_transition", detail="Open the step before marking it complete.")
    if pr.status != "completed":
        now = utcnow()
        elapsed = (now - pr.opened_at).total_seconds()
        need = min_dwell_seconds(step)
        if elapsed < need:
            wait = int(need - elapsed) + 1
            raise ProblemError(
                "too_early",
                409,
                "A little more time on this step",
                "Spend a bit more time on this step before marking it complete.",
                headers={"Retry-After": str(wait)},
                retry_after_seconds=wait,
            )
        pr.status = "completed"
        pr.completed_at = now
        pr.source = "learner"
        pr.credits_awarded = _award(a, step, pl.dues.get(step_key), now)
        pr.evidence = {"kind": "learner_mark", "dwell_seconds": int(elapsed)}
        await st.save_progress(session, pr)
        await st.flush(session)
    pl = await _player(session, a, principal.user_id)
    earned, _, pct, _ = pl.totals()
    return {"step": _step_view(pl, step_key), "credits_earned": earned, "pct": pct}


# --------------------------------------------------------------------------- event-driven completion


async def complete_from_evidence(
    session: AsyncSession, user_id: uuid.UUID, *, field: str, ref_id: uuid.UUID, evidence: dict[str, Any]
) -> int:
    """Complete every active allocation step of ``user_id`` that links ``ref_id`` (``field`` =
    ``assignment_id`` | ``test_id``). Runs in the outbox relay (system context). Idempotent."""
    allocs = await st.user_allocations(session, user_id, linking=(field, ref_id))
    n = 0
    now = utcnow()
    for a in allocs:
        pl = await _player(session, a, user_id)
        for step in pl.leaves:
            if getattr(step, field) != ref_id:
                continue
            pr = pl.progress.get(step.step_key)
            if pr is not None and pr.status == "completed":
                continue
            credits = _award(a, step, pl.dues.get(step.step_key), now)
            if pr is None:
                await st.add_progress(
                    session,
                    PathStepProgress(
                        id=uuid7(),
                        allocation_id=a.id,
                        organization_id=a.organization_id,
                        user_id=user_id,
                        step_key=step.step_key,
                        status="completed",
                        completed_at=now,
                        credits_awarded=credits,
                        source="event",
                        evidence=evidence,
                    ),
                )
            else:
                pr.status = "completed"
                pr.completed_at = now
                pr.credits_awarded = credits
                pr.source = "event"
                pr.evidence = evidence
                await st.save_progress(session, pr)
            n += 1
    await st.flush(session)
    return n


async def _assignment_done(
    session: AsyncSession, assignment_id: uuid.UUID, user_id: uuid.UUID | None
) -> None:
    if not await adapters.assignment_released(session, assignment_id):
        return
    for uid, sid in await adapters.graded_submissions(session, assignment_id, user_id):
        await complete_from_evidence(
            session,
            uid,
            field="assignment_id",
            ref_id=assignment_id,
            evidence={"kind": "assignment_graded", "submission_id": str(sid)},
        )


def _uuid(v: Any) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(v)) if v else None
    except ValueError:
        return None


async def on_submission_graded(session: AsyncSession, msg: Any) -> None:
    """learning ``submission_graded``: completes once the grade is also released."""
    aid, uid = _uuid(msg.payload.get("assignment_id")), _uuid(msg.payload.get("user_id"))
    if aid and uid:
        await _assignment_done(session, aid, uid)


async def on_grades_released(session: AsyncSession, msg: Any) -> None:
    aid = _uuid(msg.payload.get("assignment_id"))
    if aid:
        await _assignment_done(session, aid, None)


async def on_attempt_scored(session: AsyncSession, msg: Any) -> None:
    """assessments ``attempt.scored``: completes when the result is a pass (or graded without a
    pass mark) and the attempt is not invalidated. State is re-read from the database."""
    att_id = _uuid(msg.payload.get("attempt_id"))
    if att_id is None:
        return
    row = await adapters.attempt_outcome(session, att_id)
    if row is None:
        return
    user_id, test_id, integrity, passed, pass_pct = row
    if integrity == "invalidated":
        return
    if passed is True or (passed is None and pass_pct is None):
        await complete_from_evidence(
            session,
            user_id,
            field="test_id",
            ref_id=test_id,
            evidence={"kind": "assessment_passed", "attempt_id": str(att_id)},
        )


def register_outbox_handlers() -> None:
    from app.core.outbox import register_handler

    register_handler("learning.submission_graded", on_submission_graded)
    register_handler("learning.grades_released", on_grades_released)
    register_handler("attempt.scored", on_attempt_scored)


# --------------------------------------------------------------------------- articles


def article_out(a: PathArticle, *, body: bool) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id": str(a.id),
        "organization_id": str(a.organization_id),
        "title": a.title,
        "subtitle": a.subtitle,
        "level": a.level,
        "est_minutes": a.est_minutes,
        "status": a.status,
        "audience": a.audience,
        "batch_ids": [str(b) for b in a.batch_ids],
        "user_ids": [str(u) for u in a.user_ids],
        "updated_at": _iso(a.updated_at),
    }
    if body:
        out["body_md"] = a.body_md
        out["toc"] = a.toc
    return out


async def _new_article(
    session: AsyncSession,
    principal: Principal,
    org_id: uuid.UUID,
    *,
    title: str,
    subtitle: str,
    level: str,
    est_minutes: int,
    body_md: str,
) -> PathArticle:
    clean = sanitize_markdown(body_md)
    a = PathArticle(
        id=uuid7(),
        organization_id=org_id,
        title=title.strip(),
        subtitle=subtitle,
        level=level,
        est_minutes=max(0, min(est_minutes, 6000)),
        body_md=clean,
        toc=table_of_contents(clean),
        status="draft",
        created_by=principal.user_id,
    )
    await st.insert_article(session, a)
    await audit(
        session,
        principal,
        "path_article.create",
        "path_article",
        a.id,
        organization_id=org_id,
        after={"title": a.title},
    )
    return a


async def create_article(
    request: Request, session: AsyncSession, principal: Principal, body: dict[str, Any]
) -> PathArticle:
    await require_author(request, principal, "path.manage")
    return await _new_article(
        session,
        principal,
        COMPANY_ORG_ID,
        title=body["title"],
        subtitle=body.get("subtitle") or "",
        level=body.get("level") or "beginner",
        est_minutes=body.get("est_minutes") or 0,
        body_md=body["body_md"],
    )


async def get_article(session: AsyncSession, article_id: uuid.UUID) -> PathArticle:
    a = await st.get_article(session, article_id)
    if a is None:
        raise ProblemError("not_found")
    return a


async def managed_article(
    request: Request,
    session: AsyncSession,
    principal: Principal,
    article_id: uuid.UUID,
    *,
    change: bool = False,
) -> PathArticle:
    """``change``: the caller is about to edit, re-target, unpublish or delete the article, so
    its current audience must be within the caller's scope (``require_audience_scope``)."""
    a = await get_article(session, article_id)
    await require_author(request, principal, "path.manage")
    if change and a.status == "published":
        await require_audience_scope(
            request, session, principal, list(a.batch_ids or []), list(a.user_ids or [])
        )
    return a


async def list_articles(
    request: Request,
    session: AsyncSession,
    principal: Principal,
    q: str | None,
) -> dict[str, Any]:
    if not await can_author(request, principal, "path.manage"):
        return {"data": []}
    rows = await st.list_articles(session, q)
    return {"data": [article_out(a, body=False) for a in rows]}


async def update_article(
    session: AsyncSession, principal: Principal, a: PathArticle, changes: dict[str, Any]
) -> None:
    for k in ("title", "subtitle", "level", "est_minutes"):
        if changes.get(k) is not None:
            setattr(a, k, changes[k])
    if changes.get("body_md") is not None:
        a.body_md = sanitize_markdown(changes["body_md"])
        a.toc = table_of_contents(a.body_md)
    a.updated_at = utcnow()
    await st.save_article(session, a)
    await audit(
        session,
        principal,
        "path_article.update",
        "path_article",
        a.id,
        organization_id=a.organization_id,
        after={k: v for k, v in changes.items() if v is not None and k != "body_md"},
    )


async def publish_article(
    request: Request, session: AsyncSession, principal: Principal, a: PathArticle, body: dict[str, Any]
) -> None:
    audience = body["audience"]
    batch_ids: list[uuid.UUID] = list(dict.fromkeys(body.get("batch_ids") or []))
    user_ids: list[uuid.UUID] = list(dict.fromkeys(body.get("user_ids") or []))
    if audience == "batches":
        if not batch_ids:
            raise vf("batch_ids", "required", "Choose at least one batch")
        found = await adapters.existing_batch_ids(session, batch_ids)
        if set(batch_ids) - found:
            raise vf("batch_ids", "not_found", "Choose existing batches")
        user_ids = []
    elif audience == "people":
        if not user_ids:
            raise vf("user_ids", "required", "Choose at least one person")
        found = await adapters.active_company_members(session, user_ids)
        if set(user_ids) - found:
            raise vf("user_ids", "not_member", "Choose active batch learners or staff")
        batch_ids = []
    else:
        raise vf("audience", "invalid", "Choose batches or people")
    await require_audience_scope(request, session, principal, batch_ids, user_ids)
    a.status = "published"
    a.audience = audience
    a.batch_ids = batch_ids
    a.user_ids = user_ids
    a.published_at = a.published_at or utcnow()
    await st.save_article(session, a)
    await audit(
        session,
        principal,
        "path_article.publish",
        "path_article",
        a.id,
        organization_id=a.organization_id,
        after={"audience": audience, "batches": len(batch_ids), "people": len(user_ids)},
    )


async def unpublish_article(session: AsyncSession, principal: Principal, a: PathArticle) -> None:
    a.status = "draft"
    a.audience = None
    a.batch_ids = []
    a.user_ids = []
    await st.save_article(session, a)
    await audit(
        session, principal, "path_article.unpublish", "path_article", a.id, organization_id=a.organization_id
    )


async def delete_article(session: AsyncSession, principal: Principal, a: PathArticle) -> None:
    used = await st.draft_steps_using_article(session, a.id)
    if used:
        raise ProblemError(
            "invalid_state_transition", detail="Remove this article from its path steps first."
        )
    a.deleted_at = utcnow()
    a.status = "draft"
    a.audience = None
    await st.save_article(session, a)
    await audit(
        session, principal, "path_article.delete", "path_article", a.id, organization_id=a.organization_id
    )


async def _on_allocated_path(session: AsyncSession, user_id: uuid.UUID, article_id: uuid.UUID) -> bool:
    return bool(await st.user_allocations(session, user_id, linking=("article_id", article_id), limit=1))


async def read_article(
    request: Request, session: AsyncSession, principal: Principal, article_id: uuid.UUID
) -> dict[str, Any]:
    """Reader view. Allowed: path authors; learners on an active allocation whose path includes
    the article (published or not); otherwise the publish audience — active members of the
    chosen batches, or the chosen people. Everyone else gets 404 (existence is not disclosed)."""
    a = await get_article(session, article_id)
    can_edit = await can_author(request, principal, "path.manage")
    allowed = can_edit or await _on_allocated_path(session, principal.user_id, a.id)
    if not allowed and a.status == "published":
        if a.audience == "people":
            allowed = principal.user_id in a.user_ids
        elif a.audience == "batches" and a.batch_ids:
            allowed = await adapters.active_member_of_batches(session, principal.user_id, a.batch_ids)
    if not allowed:
        raise ProblemError("not_found")
    return {
        "id": str(a.id),
        "title": a.title,
        "subtitle": a.subtitle,
        "level": a.level,
        "est_minutes": a.est_minutes,
        "body_md": a.body_md,
        "toc": a.toc,
        "status": a.status,
        "audience": a.audience,
        "can_edit": can_edit,
    }
