"""Engage service: activities, runs, participants, responses and live result aggregation.

Authorization model
-------------------
Single company (docs/single-company/REMOVAL-PLAN.md): an activity is either a **batch** activity
(``batch_id`` set; ``organization_id`` = the batch's organization, i.e. the company) or a
**platform** activity (both NULL). There is no organization-wide target and no organization
picker; legacy organization-wide rows were soft-deleted by ``engage_0002``.

* Managing an activity (``engage.activity.manage``): platform activities need the permission at
  platform scope; batch activities at the batch scope of the activity's batch (a platform grant
  covers every batch through the scope chain). A trainer of another batch has no access.
* Joining a run: ``members`` = active members of the activity's batch (platform activities:
  platform staff only); ``public`` = any authenticated Tech Drona user holding the link/code.
  Managers of the activity may always join (preview). There is no unauthenticated path.
* Participant-side reads of activities/runs happen inside ``system_context`` blocks (a public run's
  participant may not share the activity's organization, which TN RLS would hide) after the
  explicit checks above; participant and response rows are written under the caller's own RLS
  context (policy U: ``user_id = app.user_id()``).

Display names (§2.4): participants are labelled by their profile *nickname* (``display_name``)
only, never by full name or e-mail; without a nickname the label is ``Participant #<seq>``.

Answer secrecy: the run's question snapshot carries ``is_correct``; :func:`_public_question`
strips it, and correct option ids are only added for questions that were revealed to the room or
after results are published.

Anonymity: anonymous runs store no display name; every output labels participants
``Anonymous #<seq>`` and never includes user ids.
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from collections import defaultdict
from datetime import datetime
from typing import Any

from fastapi import Request
from sqlalchemy import delete, func, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import ratelimit
from app.core.audit import audit
from app.core.auth import PLATFORM_SCOPE, ScopeRef
from app.core.db import system_context
from app.core.errors import ProblemError
from app.core.ids import uuid7
from app.core.outbox import emit_event
from app.core.principal import Principal
from app.core.ratelimit import MIN, Rule
from app.core.time import to_rfc3339, utcnow
from app.modules.ai.service import require_app_enabled
from app.modules.engage.models import (
    EngageActivity,
    EngageParticipant,
    EngageQuestion,
    EngageResponse,
    EngageRun,
)
from app.modules.engage.schemas import (
    CHOICE_KINDS,
    KINDS_BY_TYPE,
    ActivityIn,
    AnswerIn,
    ControlIn,
    LaunchIn,
)
from app.modules.engage.words import is_blocked, normalise_terms
from app.modules.placement.policies import batch_org, can_in_org, has_permission

PERM = "engage.activity.manage"
JOIN_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
JOIN_CODE_LEN = 8
LIVE_STATUSES = ("scheduled", "open")
ANSWER_RULES = (Rule(10, 10), Rule(120, MIN))
JOIN_RULES = (Rule(30, MIN),)
# SEC-07: keyed by activity + manager (not by run), so relaunching does not reset the budget.
INVITE_RULES = (Rule(5, 3600),)
LAUNCH_RULES = (Rule(10, 3600),)
INVITE_CAP = 500
TEXT_SAMPLE = 200
WORD_TOP = 100
LEADERBOARD_TOP = 20


def _problem(code: str, status: int, title: str, detail: str | None = None, **ext: Any) -> ProblemError:
    return ProblemError(code, status=status, title=title, detail=detail or title, **ext)


def _invalid(errors: list[dict[str, Any]]) -> ProblemError:
    return ProblemError("validation_failed", errors=errors)


# =========================================================================== authorization


async def can_manage(
    request: Request, session: AsyncSession, principal: Principal, a: EngageActivity
) -> bool:
    if a.batch_id is not None:
        return await has_permission(request, principal, PERM, ScopeRef("batch", a.batch_id))
    # Platform activity — or a legacy organization-wide row (soft-deleted by engage_0002): only a
    # platform-scope holder (Admin / content manager) may manage it.
    return await has_permission(request, principal, PERM, PLATFORM_SCOPE)


async def require_manage(
    request: Request, session: AsyncSession, principal: Principal, a: EngageActivity
) -> None:
    if not await can_manage(request, session, principal, a):
        raise ProblemError("permission_denied", permission=PERM)


async def _create_scope(
    request: Request, session: AsyncSession, principal: Principal, body: ActivityIn
) -> uuid.UUID | None:
    """Authorize creating (or moving) an activity to the body's batch (or the platform); returns
    the owning organization (the batch's — the company — or None = platform)."""
    if body.batch_id is not None:
        org = await batch_org(session, body.batch_id)
        if org is None:
            raise ProblemError("not_found")
        if not await has_permission(request, principal, PERM, ScopeRef("batch", body.batch_id)):
            raise ProblemError("permission_denied", permission=PERM)
        return org
    if not await has_permission(request, principal, PERM, PLATFORM_SCOPE):
        raise ProblemError("permission_denied", permission=PERM)
    return None


async def _is_member(session: AsyncSession, principal: Principal, a: EngageActivity) -> bool:
    if a.batch_id is not None:
        row = (
            await session.execute(
                text(
                    "SELECT 1 FROM batch_members WHERE batch_id = :b AND user_id = :u AND status = 'active' "
                    "AND removed_at IS NULL LIMIT 1"
                ),
                {"b": a.batch_id, "u": principal.user_id},
            )
        ).first()
        return row is not None
    if a.organization_id is not None:
        return False  # legacy organization-wide activity: no member audience any more
    return principal.is_platform


async def _may_join(
    request: Request, session: AsyncSession, principal: Principal, a: EngageActivity, run: EngageRun
) -> bool:
    if run.settings.get("audience") == "public":
        return True
    async with system_context(session, "engage.membership"):
        member = await _is_member(session, principal, a)
    return member or await can_manage(request, session, principal, a)


# =========================================================================== activities


def validate_activity(body: ActivityIn) -> ActivityIn:
    errors: list[dict[str, Any]] = []
    if body.activity_type == "quiz":
        body.winner_rule = body.winner_rule or "fastest_first"
    else:
        body.winner_rule = None
    if body.run_mode == "scheduled" and body.opens_at and body.closes_at and body.closes_at <= body.opens_at:
        errors.append({"field": "closes_at", "code": "invalid", "message": "must be after opens_at"})
    allowed = KINDS_BY_TYPE[body.activity_type]
    for i, q in enumerate(body.questions):
        f = f"questions[{i}]"
        if q.kind not in allowed:
            msg = f"not allowed in a {body.activity_type}"
            errors.append({"field": f"{f}.kind", "code": "invalid", "message": msg})
            continue
        if q.kind in CHOICE_KINDS:
            if len(q.options) < 2:
                errors.append({"field": f"{f}.options", "code": "too_short", "message": "at least 2 options"})
            n_correct = sum(1 for o in q.options if o.is_correct)
            if body.activity_type == "quiz":
                if n_correct == 0:
                    errors.append({"field": f"{f}.options", "code": "required", "message": "tick the answer"})
                elif q.kind == "single_choice" and n_correct > 1:
                    errors.append({"field": f"{f}.options", "code": "invalid", "message": "one correct only"})
            elif n_correct:
                # polls and surveys have no right answer
                for o in q.options:
                    o.is_correct = False
        elif q.options:
            errors.append({"field": f"{f}.options", "code": "invalid", "message": "this kind has no options"})
        if q.kind == "word" and q.max_words is None:
            q.max_words = 1
    if errors:
        raise _invalid(errors)
    return body


def _question_rows(a: EngageActivity, body: ActivityIn) -> list[EngageQuestion]:
    out = []
    for i, q in enumerate(body.questions):
        out.append(
            EngageQuestion(
                id=uuid7(),
                activity_id=a.id,
                organization_id=a.organization_id,
                position=i,
                kind=q.kind,
                prompt=q.prompt.strip(),
                options=[
                    {"id": str(o.id or uuid7()), "text": o.text.strip(), "is_correct": bool(o.is_correct)}
                    for o in q.options
                ],
                max_words=q.max_words if q.kind == "word" else None,
                source_question_id=q.source_question_id,
                source_version_id=q.source_version_id,
            )
        )
    return out


def _apply_settings(a: EngageActivity, body: ActivityIn, org: uuid.UUID | None) -> None:
    a.organization_id = org
    a.batch_id = body.batch_id
    a.activity_type = body.activity_type
    a.title = body.title.strip()
    a.description = (body.description or "").strip() or None
    a.run_mode = body.run_mode
    a.audience = body.audience
    a.identity_mode = body.identity_mode
    a.results_mode = body.results_mode
    a.pacing = body.pacing
    a.winner_rule = body.winner_rule
    a.participant_limit = body.participant_limit
    a.opens_at = body.opens_at if body.run_mode == "scheduled" else None
    a.closes_at = body.closes_at if body.run_mode == "scheduled" else None


def settings_of(a: EngageActivity) -> dict[str, Any]:
    return {
        "run_mode": a.run_mode,
        "audience": a.audience,
        "identity_mode": a.identity_mode,
        "results_mode": a.results_mode,
        "pacing": a.pacing,
        "winner_rule": a.winner_rule,
        "participant_limit": a.participant_limit,
    }


def question_out(q: EngageQuestion) -> dict[str, Any]:
    return {
        "id": str(q.id),
        "position": q.position,
        "kind": q.kind,
        "prompt": q.prompt,
        "options": [dict(o) for o in q.options],
        "max_words": q.max_words,
        "source_question_id": str(q.source_question_id) if q.source_question_id else None,
    }


def activity_out(
    a: EngageActivity,
    questions: list[EngageQuestion] | None = None,
    *,
    question_count: int | None = None,
    latest_run: EngageRun | None = None,
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id": str(a.id),
        "activity_type": a.activity_type,
        "title": a.title,
        "description": a.description,
        "organization_id": str(a.organization_id) if a.organization_id else None,
        "batch_id": str(a.batch_id) if a.batch_id else None,
        "owner_id": str(a.owner_id),
        **settings_of(a),
        "opens_at": to_rfc3339(a.opens_at) if a.opens_at else None,
        "closes_at": to_rfc3339(a.closes_at) if a.closes_at else None,
        "created_at": to_rfc3339(a.created_at) if a.created_at else None,
        "updated_at": to_rfc3339(a.updated_at) if a.updated_at else None,
    }
    if questions is not None:
        out["questions"] = [question_out(q) for q in questions]
        out["question_count"] = len(questions)
    elif question_count is not None:
        out["question_count"] = question_count
    if latest_run is not None or questions is None:
        out["latest_run"] = run_summary(latest_run) if latest_run else None
    return out


async def get_activity(session: AsyncSession, activity_id: uuid.UUID) -> EngageActivity:
    a = await session.get(EngageActivity, activity_id)
    if a is None or a.deleted_at is not None:
        raise ProblemError("not_found")
    return a


async def questions_of(session: AsyncSession, activity_id: uuid.UUID) -> list[EngageQuestion]:
    return list(
        (
            await session.execute(
                select(EngageQuestion)
                .where(EngageQuestion.activity_id == activity_id)
                .order_by(EngageQuestion.position)
            )
        ).scalars()
    )


async def create_activity(
    request: Request, session: AsyncSession, principal: Principal, body: ActivityIn
) -> dict[str, Any]:
    validate_activity(body)
    org = await _create_scope(request, session, principal, body)
    await require_app_enabled(session, app_key="engage")
    a = EngageActivity(id=uuid7(), owner_id=principal.user_id)
    _apply_settings(a, body, org)
    session.add(a)
    await session.flush()
    qs = _question_rows(a, body)
    session.add_all(qs)
    await session.flush()
    await session.refresh(a)
    await audit(
        session,
        principal,
        "engage.activity_created",
        "engage_activity",
        a.id,
        organization_id=org,
        after={"type": a.activity_type, "questions": len(qs)},
    )
    return activity_out(a, qs)


async def update_activity(
    request: Request, session: AsyncSession, principal: Principal, activity_id: uuid.UUID, body: ActivityIn
) -> dict[str, Any]:
    a = await get_activity(session, activity_id)
    await require_manage(request, session, principal, a)
    validate_activity(body)
    if body.activity_type != a.activity_type:
        raise _invalid([{"field": "activity_type", "code": "immutable", "message": "type cannot change"}])
    if body.batch_id != a.batch_id or (a.batch_id is None and a.organization_id is not None):
        org = await _create_scope(request, session, principal, body)
    else:
        org = a.organization_id
    _apply_settings(a, body, org)
    await session.execute(delete(EngageQuestion).where(EngageQuestion.activity_id == a.id))
    await session.flush()
    qs = _question_rows(a, body)
    session.add_all(qs)
    await session.flush()
    await session.refresh(a)
    await audit(
        session,
        principal,
        "engage.activity_updated",
        "engage_activity",
        a.id,
        organization_id=a.organization_id,
        after={"questions": len(qs)},
    )
    return activity_out(a, qs)


async def activity_detail(
    request: Request, session: AsyncSession, principal: Principal, activity_id: uuid.UUID
) -> dict[str, Any]:
    a = await get_activity(session, activity_id)
    await require_manage(request, session, principal, a)
    out = activity_out(a, await questions_of(session, a.id))
    runs = await _runs_of(session, a.id)
    for r in runs:
        await refresh_status(session, r)
    out["runs"] = [run_summary(r) for r in runs]
    return out


async def list_activities(
    request: Request,
    session: AsyncSession,
    principal: Principal,
    *,
    q: str | None,
    activity_type: str | None,
    limit: int = 200,
) -> dict[str, Any]:
    stmt = select(EngageActivity).where(EngageActivity.deleted_at.is_(None))
    if activity_type:
        stmt = stmt.where(EngageActivity.activity_type == activity_type)
    if q:
        stmt = stmt.where(EngageActivity.title.ilike(f"%{_like(q)}%", escape="\\"))
    rows = list(
        (await session.execute(stmt.order_by(EngageActivity.created_at.desc()).limit(limit))).scalars()
    )
    cache: dict[tuple[Any, ...], bool] = {}
    visible: list[EngageActivity] = []
    for a in rows:
        key = (a.organization_id, a.batch_id, a.owner_id == principal.user_id)
        if key not in cache:
            cache[key] = await can_manage(request, session, principal, a)
        if cache[key]:
            visible.append(a)
    ids = [a.id for a in visible]
    counts: dict[uuid.UUID, int] = {}
    latest: dict[uuid.UUID, EngageRun] = {}
    if ids:
        counts = {
            aid: int(n)
            for aid, n in (
                await session.execute(
                    select(EngageQuestion.activity_id, func.count())
                    .where(EngageQuestion.activity_id.in_(ids))
                    .group_by(EngageQuestion.activity_id)
                )
            ).all()
        }
        for r in (
            await session.execute(
                select(EngageRun)
                .where(EngageRun.activity_id.in_(ids))
                .order_by(EngageRun.activity_id, EngageRun.run_no.desc())
                .distinct(EngageRun.activity_id)
            )
        ).scalars():
            latest[r.activity_id] = r
    return {
        "data": [
            activity_out(a, question_count=counts.get(a.id, 0), latest_run=latest.get(a.id)) for a in visible
        ],
        "counts": {"total": len(visible)},
    }


def _like(v: str) -> str:
    return v.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


async def duplicate_activity(
    request: Request, session: AsyncSession, principal: Principal, activity_id: uuid.UUID
) -> dict[str, Any]:
    src = await get_activity(session, activity_id)
    await require_manage(request, session, principal, src)
    a = EngageActivity(
        id=uuid7(),
        organization_id=src.organization_id,
        batch_id=src.batch_id,
        owner_id=principal.user_id,
        activity_type=src.activity_type,
        title=(src.title[: 200 - len(" (copy)")] + " (copy)"),
        description=src.description,
        run_mode=src.run_mode,
        audience=src.audience,
        identity_mode=src.identity_mode,
        results_mode=src.results_mode,
        pacing=src.pacing,
        winner_rule=src.winner_rule,
        participant_limit=src.participant_limit,
        opens_at=src.opens_at,
        closes_at=src.closes_at,
    )
    session.add(a)
    await session.flush()
    qs = [
        EngageQuestion(
            id=uuid7(),
            activity_id=a.id,
            organization_id=a.organization_id,
            position=q.position,
            kind=q.kind,
            prompt=q.prompt,
            options=[{**o, "id": str(uuid7())} for o in q.options],
            max_words=q.max_words,
            source_question_id=q.source_question_id,
            source_version_id=q.source_version_id,
        )
        for q in await questions_of(session, src.id)
    ]
    session.add_all(qs)
    await session.flush()
    await session.refresh(a)
    await audit(
        session,
        principal,
        "engage.activity_duplicated",
        "engage_activity",
        a.id,
        organization_id=a.organization_id,
        after={"source": str(src.id)},
    )
    return activity_out(a, qs)


async def delete_activity(
    request: Request, session: AsyncSession, principal: Principal, activity_id: uuid.UUID
) -> None:
    a = await get_activity(session, activity_id)
    await require_manage(request, session, principal, a)
    now = utcnow()
    a.deleted_at = now
    await session.execute(
        update(EngageRun)
        .where(EngageRun.activity_id == a.id, EngageRun.status.in_(LIVE_STATUSES))
        .values(status="closed", closed_at=now, state_version=EngageRun.state_version + 1)
        .execution_options(synchronize_session=False)
    )
    await session.flush()
    await audit(
        session,
        principal,
        "engage.activity_deleted",
        "engage_activity",
        a.id,
        organization_id=a.organization_id,
    )


# --------------------------------------------------------------------------- question bank import


async def bank_import(
    request: Request, session: AsyncSession, principal: Principal, question_ids: list[uuid.UUID]
) -> dict[str, Any]:
    """Convert placement questions (MCQ) into engage question drafts through the placement bank's
    public functions. Nothing is persisted: the builder appends the drafts and saves the activity.
    Correct flags are copied only when the caller may read that question's answer key (author /
    reviewer, or ``question.answer_key.read`` in its organization), the same rule as the bank."""
    from app.modules.placement import bank
    from app.modules.placement.richtext import html_of

    out: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    for qid in dict.fromkeys(question_ids):
        try:
            q = await bank.get_question(session, qid)
        except ProblemError:
            skipped.append({"question_id": str(qid), "reason": "not_found"})
            continue
        if q.question_type not in ("mcq_single", "mcq_multi") or q.current_version_id is None:
            reason = "unsupported_type" if q.current_version_id else "no_version"
            skipped.append({"question_id": str(qid), "reason": reason})
            continue
        if not await _may_read_question(request, session, principal, q):
            skipped.append({"question_id": str(qid), "reason": "forbidden"})
            continue
        bundles = await bank.load_bundles(session, [q.current_version_id])
        b = bundles.get(q.current_version_id)
        if b is None:
            skipped.append({"question_id": str(qid), "reason": "no_version"})
            continue
        keys = await _keys_visible(request, session, principal, q)
        out.append(
            {
                "kind": "single_choice" if q.question_type == "mcq_single" else "multi_choice",
                "prompt": _plain(html_of(b.version.stem) or "")[:2000] or "Question",
                "options": [
                    {
                        "text": _plain(html_of(o.body) or o.label)[:500] or o.label,
                        "is_correct": bool(o.is_correct and keys),
                    }
                    for o in b.options
                ][:10],
                "max_words": None,
                "source_question_id": str(q.id),
                "source_version_id": str(b.version.id),
                "key_copied": keys,
            }
        )
    return {"data": out, "skipped": skipped}


async def _may_read_question(request: Request, session: AsyncSession, principal: Principal, q: Any) -> bool:
    if q.organization_id is None and q.status == "active":
        return True  # the shared platform bank (answer keys still follow the bank rule)
    for p in ("question.edit", "question.answer_key.read", "test.create"):
        if await can_in_org(request, session, principal, p, q.organization_id):
            return True
    return q.created_by == principal.user_id


async def _keys_visible(request: Request, session: AsyncSession, principal: Principal, q: Any) -> bool:
    from app.modules.placement import bank

    versions = await bank.versions_of(session, q.id)
    if any(principal.user_id in (v.authored_by, v.reviewed_by) for v in versions):
        return True
    return await can_in_org(request, session, principal, "question.answer_key.read", q.organization_id)


def _plain(html: str) -> str:
    import html as html_mod
    import re

    return re.sub(r"\s+", " ", html_mod.unescape(re.sub(r"<[^>]+>", " ", html))).strip()


# =========================================================================== runs


def _join_code() -> str:
    return "".join(secrets.choice(JOIN_ALPHABET) for _ in range(JOIN_CODE_LEN))


def _snapshot(q: EngageQuestion) -> dict[str, Any]:
    return {
        "id": str(q.id),
        "position": q.position,
        "kind": q.kind,
        "prompt": q.prompt,
        "options": [
            {"id": o["id"], "text": o["text"], "is_correct": bool(o.get("is_correct"))} for o in q.options
        ],
        "max_words": q.max_words,
    }


def run_summary(r: EngageRun) -> dict[str, Any]:
    return {
        "id": str(r.id),
        "activity_id": str(r.activity_id),
        "run_no": r.run_no,
        "join_code": r.join_code,
        "join_path": join_path(r.join_code),
        "status": r.status,
        "current_position": r.current_position,
        "revealed_positions": sorted(r.revealed_positions or []),
        "results_published": r.results_published,
        "question_count": len(r.questions or []),
        "settings": dict(r.settings or {}),
        "opens_at": to_rfc3339(r.opens_at) if r.opens_at else None,
        "closes_at": to_rfc3339(r.closes_at) if r.closes_at else None,
        "opened_at": to_rfc3339(r.opened_at) if r.opened_at else None,
        "closed_at": to_rfc3339(r.closed_at) if r.closed_at else None,
        "finalised_at": to_rfc3339(r.finalised_at) if r.finalised_at else None,
        "created_at": to_rfc3339(r.created_at) if r.created_at else None,
    }


def join_path(code: str) -> str:
    return f"/app/engage/join/{code}"


async def _runs_of(session: AsyncSession, activity_id: uuid.UUID) -> list[EngageRun]:
    return list(
        (
            await session.execute(
                select(EngageRun)
                .where(EngageRun.activity_id == activity_id)
                .order_by(EngageRun.run_no.desc())
            )
        ).scalars()
    )


async def refresh_status(session: AsyncSession, r: EngageRun, now: datetime | None = None) -> bool:
    """Apply a scheduled run's timer (opens/closes). Caller holds a context that may update the
    row. Returns True when the status changed."""
    now = now or utcnow()
    changed = False
    if (
        r.status == "scheduled"
        and r.settings.get("run_mode") == "scheduled"
        and r.opens_at
        and r.opens_at <= now
    ):
        r.status = "open"
        r.opened_at = r.opens_at
        changed = True
    if r.status in LIVE_STATUSES and r.closes_at and r.closes_at <= now:
        r.status = "closed"
        r.closed_at = r.closes_at
        changed = True
    if changed:
        r.state_version += 1
        await session.flush()
    return changed


async def launch_run(
    request: Request, session: AsyncSession, principal: Principal, activity_id: uuid.UUID, body: LaunchIn
) -> dict[str, Any]:
    """Launch (first run) or rerun: a new run with a fresh join code; any live run of the activity
    is closed first."""
    a = (
        await session.execute(
            select(EngageActivity).where(EngageActivity.id == activity_id).with_for_update()
        )
    ).scalar_one_or_none()
    if a is None or a.deleted_at is not None:
        raise ProblemError("not_found")
    await require_manage(request, session, principal, a)
    # SEC-07: relaunching mints a new run id, so launches are budgeted per activity + manager.
    await ratelimit.hit(f"engage:launch:{a.id}:{principal.user_id}", LAUNCH_RULES, scope="engage.launch")
    await require_app_enabled(session, app_key="engage")
    qs = await questions_of(session, a.id)
    if not qs:
        raise _invalid([{"field": "questions", "code": "required", "message": "add at least one question"}])
    opens_at = body.opens_at or a.opens_at
    closes_at = body.closes_at or a.closes_at
    if a.run_mode == "scheduled":
        if opens_at is None or closes_at is None:
            raise _invalid([{"field": "opens_at", "code": "required", "message": "needs a window"}])
        if closes_at <= opens_at or closes_at <= utcnow():
            raise _invalid([{"field": "closes_at", "code": "invalid", "message": "future, after opens_at"}])
    else:
        opens_at = None
        closes_at = body.closes_at
    now = utcnow()
    await session.execute(
        update(EngageRun)
        .where(EngageRun.activity_id == a.id, EngageRun.status.in_(LIVE_STATUSES))
        .values(status="closed", closed_at=now, state_version=EngageRun.state_version + 1)
        .execution_options(synchronize_session=False)
    )
    run_no = (
        int(
            (
                await session.execute(
                    select(func.coalesce(func.max(EngageRun.run_no), 0)).where(EngageRun.activity_id == a.id)
                )
            ).scalar_one()
        )
        + 1
    )
    run_id = uuid7()
    for _ in range(5):
        code = _join_code()
        rid = (
            await session.execute(
                pg_insert(EngageRun)
                .values(
                    id=run_id,
                    activity_id=a.id,
                    organization_id=a.organization_id,
                    run_no=run_no,
                    join_code=code,
                    status="scheduled",
                    settings=settings_of(a),
                    questions=[_snapshot(q) for q in qs],
                    opens_at=opens_at,
                    closes_at=closes_at,
                    created_by=principal.user_id,
                )
                .on_conflict_do_nothing(index_elements=["join_code"])
                .returning(EngageRun.id)
            )
        ).scalar_one_or_none()
        if rid is not None:
            break
    else:  # pragma: no cover - 31^8 codes
        raise ProblemError("conflict")
    r = await session.get(EngageRun, run_id)
    assert r is not None
    await refresh_status(session, r)
    await audit(
        session,
        principal,
        "engage.run_launched",
        "engage_run",
        r.id,
        organization_id=a.organization_id,
        after={"activity_id": str(a.id), "run_no": run_no},
    )
    return run_summary(r)


async def _manager_run(
    request: Request, session: AsyncSession, principal: Principal, run_id: uuid.UUID, *, lock: bool = False
) -> tuple[EngageRun, EngageActivity]:
    stmt = select(EngageRun).where(EngageRun.id == run_id)
    if lock:
        stmt = stmt.with_for_update()
    r = (await session.execute(stmt)).scalar_one_or_none()
    if r is None:
        raise ProblemError("not_found")
    a = await session.get(EngageActivity, r.activity_id)
    if a is None:
        raise ProblemError("not_found")
    await require_manage(request, session, principal, a)
    await refresh_status(session, r)
    return r, a


async def control_run(
    request: Request, session: AsyncSession, principal: Principal, run_id: uuid.UUID, body: ControlIn
) -> dict[str, Any]:
    r, a = await _manager_run(request, session, principal, run_id, lock=True)
    now = utcnow()
    n = len(r.questions)
    act = body.action

    def bad(allowed: list[str]) -> ProblemError:
        return ProblemError("invalid_state_transition", current_state=r.status, allowed=allowed)

    if act == "start":
        if r.status != "scheduled":
            raise bad(["scheduled"])
        r.status, r.opened_at = "open", now
    elif act == "close":
        if r.status not in LIVE_STATUSES:
            raise bad(list(LIVE_STATUSES))
        r.status, r.closed_at = "closed", now
    elif act == "finalise":
        if r.status == "finalised":
            raise bad(["scheduled", "open", "closed"])
        r.status = "finalised"
        r.closed_at = r.closed_at or now
        r.finalised_at = now
        r.results_published = True
    elif act == "goto":
        if r.status == "finalised":
            raise bad(["scheduled", "open", "closed"])
        if body.position is None or body.position >= n:
            raise _invalid([{"field": "position", "code": "invalid", "message": f"0..{n - 1}"}])
        r.current_position = body.position
    elif act in ("reveal", "hide"):
        targets = (
            set(range(n))
            if r.settings.get("pacing") == "all_at_once" and body.position is None
            else {r.current_position if body.position is None else body.position}
        )
        if any(p >= n for p in targets):
            raise _invalid([{"field": "position", "code": "invalid", "message": f"0..{n - 1}"}])
        cur = set(r.revealed_positions or [])
        r.revealed_positions = sorted(cur | targets if act == "reveal" else cur - targets)
        if act == "reveal":
            # SEC-06: once the answer was shown, the question stays closed even after "hide".
            r.closed_positions = sorted(set(r.closed_positions or []) | targets)
    elif act in ("publish", "unpublish"):
        if act == "publish" and r.status in LIVE_STATUSES:
            # SEC-06: publishing shows every answer key, so only a closed run may publish.
            raise bad(["closed", "finalised"])
        r.results_published = act == "publish"
    r.state_version += 1
    await session.flush()
    await audit(
        session,
        principal,
        f"engage.run_{act}",
        "engage_run",
        r.id,
        organization_id=a.organization_id,
        after={"position": body.position, "status": r.status},
    )
    if act == "finalise":
        await emit_event(
            session,
            "engage.run_finalised",
            {"run_id": str(r.id), "activity_id": str(a.id), "activity_type": a.activity_type},
            aggregate_type="engage_run",
            aggregate_id=r.id,
            organization_id=a.organization_id,
        )
    return run_summary(r)


async def invite(
    request: Request, session: AsyncSession, principal: Principal, run_id: uuid.UUID
) -> dict[str, Any]:
    """Notify the activity's active batch members about the run: in-app notification plus email
    through the notifications module. Platform activities have no member list (share the link)."""
    from app.core.config import get_settings
    from app.modules.notifications.service import notify

    r, a = await _manager_run(request, session, principal, run_id)
    if r.status not in LIVE_STATUSES:
        raise ProblemError("invalid_state_transition", current_state=r.status, allowed=list(LIVE_STATUSES))
    if a.batch_id is None:
        msg = "platform activities have no member list; share the link"
        raise _invalid([{"field": "run_id", "code": "no_audience", "message": msg}])
    # SEC-07: the budget belongs to the activity + manager, so a relaunch cannot reset it.
    await ratelimit.hit(f"engage:invite:{a.id}:{principal.user_id}", INVITE_RULES, scope="engage.invite")
    sql = (
        "SELECT DISTINCT u.id, u.email FROM batch_members m JOIN users u ON u.id = m.user_id "
        "WHERE m.batch_id = :s AND m.status = 'active' AND m.removed_at IS NULL AND u.id <> :me "
        "LIMIT :cap"
    )
    scope_id: Any = a.batch_id
    link = get_settings().TD_PUBLIC_BASE_URL.rstrip("/") + join_path(r.join_code)
    sent = 0
    async with system_context(session, "engage.invite"):
        rows = (
            await session.execute(text(sql), {"s": scope_id, "me": principal.user_id, "cap": INVITE_CAP})
        ).all()
        for uid, email in rows:
            nid = await notify(
                session,
                uid,
                "engage.invite",
                category="learning",
                data={
                    "run_id": str(r.id),
                    "title": a.title,
                    "join_code": r.join_code,
                    "url": join_path(r.join_code),
                },
                channels=("in_app", "email") if email else ("in_app",),
                organization_id=a.organization_id,
                dedupe_key=f"engage_invite:{r.id}:{uid}",
                email_to=email,
                email_subject=f"Join the live activity: {a.title}",
                email_text=(
                    f'You are invited to join "{a.title}" on Tech Drona.\n\n'
                    f"Join: {link}\nCode: {r.join_code}\n"
                ),
            )
            sent += 1 if nid else 0
        await session.flush()
    await audit(
        session,
        principal,
        "engage.run_invited",
        "engage_run",
        r.id,
        organization_id=a.organization_id,
        after={"recipients": sent},
    )
    return {"sent": sent, "recipients": len(rows), "join_path": join_path(r.join_code)}


# =========================================================================== participants


async def _run_by_code(
    session: AsyncSession, code: str, *, lock: bool = False
) -> tuple[EngageRun, EngageActivity]:
    code = (code or "").strip().upper()
    if len(code) != JOIN_CODE_LEN or any(c not in JOIN_ALPHABET for c in code):
        raise ProblemError("not_found")
    stmt = select(EngageRun).where(EngageRun.join_code == code)
    if lock:
        stmt = stmt.with_for_update()
    r = (await session.execute(stmt)).scalar_one_or_none()
    if r is None:
        raise ProblemError("not_found")
    a = await session.get(EngageActivity, r.activity_id)
    if a is None or a.deleted_at is not None:
        raise ProblemError("not_found")
    return r, a


async def _participant(
    session: AsyncSession, run_id: uuid.UUID, user_id: uuid.UUID
) -> EngageParticipant | None:
    return (
        await session.execute(
            select(EngageParticipant).where(
                EngageParticipant.run_id == run_id, EngageParticipant.user_id == user_id
            )
        )
    ).scalar_one_or_none()


def _label(p: EngageParticipant | None, anonymous: bool, seq: int | None = None) -> str:
    s = p.seq if p is not None else (seq or 0)
    if anonymous or p is None or not p.display_name:
        return f"{'Anonymous' if anonymous else 'Participant'} #{s}"
    return p.display_name


async def join_preview(
    request: Request, session: AsyncSession, principal: Principal, code: str
) -> dict[str, Any]:
    await ratelimit.hit(f"engage:join:{principal.user_id}", JOIN_RULES, scope="engage.join")
    async with system_context(session, "engage.join"):
        r, a = await _run_by_code(session, code)
        await refresh_status(session, r)
        joined = (await _participant(session, r.id, principal.user_id)) is not None
    may = await _may_join(request, session, principal, a, r)
    return {
        "run_id": str(r.id),
        "title": a.title,
        "description": a.description,
        "activity_type": a.activity_type,
        "status": r.status,
        "audience": r.settings.get("audience"),
        "identity_mode": r.settings.get("identity_mode"),
        "eligible": may,
        "joined": joined,
    }


async def join(request: Request, session: AsyncSession, principal: Principal, code: str) -> dict[str, Any]:
    await ratelimit.hit(f"engage:join:{principal.user_id}", JOIN_RULES, scope="engage.join")
    async with system_context(session, "engage.join"):
        r, a = await _run_by_code(session, code, lock=True)
        await refresh_status(session, r)
    if not await _may_join(request, session, principal, a, r):
        raise ProblemError("permission_denied", detail="This activity is open to members of its batch only.")
    await require_app_enabled(session, app_key="engage")
    name: str | None = None
    seq = 0
    async with system_context(session, "engage.join"):
        existing = await _participant(session, r.id, principal.user_id)
        if existing is None:
            if r.status not in LIVE_STATUSES:
                raise ProblemError(
                    "invalid_state_transition",
                    detail="This activity is no longer accepting participants.",
                    current_state=r.status,
                    allowed=list(LIVE_STATUSES),
                )
            count = int(
                (
                    await session.execute(select(func.count()).where(EngageParticipant.run_id == r.id))
                ).scalar_one()
            )
            limit = r.settings.get("participant_limit")
            if limit is not None and count >= int(limit):
                raise _problem("participant_limit_reached", 409, "This activity is full", limit=int(limit))
            if r.settings.get("identity_mode") != "anonymous":
                name = (
                    await session.execute(
                        # §2.4: the nickname only, never a learner's full name or e-mail.
                        text("SELECT display_name FROM user_profiles WHERE user_id = :u"),
                        {"u": principal.user_id},
                    )
                ).scalar_one_or_none()
            seq = count + 1
    if existing is None:
        # Written under the participant's own RLS context (policy U: user_id = app.user_id()).
        await session.execute(
            pg_insert(EngageParticipant)
            .values(
                id=uuid7(),
                run_id=r.id,
                organization_id=r.organization_id,
                user_id=principal.user_id,
                display_name=(name or None) and str(name)[:200],
                seq=seq,
            )
            .on_conflict_do_nothing(index_elements=["run_id", "user_id"])
        )
        await session.flush()
    return {"run_id": str(r.id), "status": r.status, "joined": True}


def _public_question(q: dict[str, Any]) -> dict[str, Any]:
    """A snapshot question without any correctness data."""
    return {
        "id": q["id"],
        "position": q["position"],
        "kind": q["kind"],
        "prompt": q["prompt"],
        "options": [{"id": o["id"], "text": o["text"]} for o in q.get("options", [])],
        "max_words": q.get("max_words"),
    }


def _visible_positions(r: EngageRun) -> list[int]:
    n = len(r.questions)
    if r.status == "scheduled":
        return []
    if r.status == "open" and r.settings.get("pacing") == "one_by_one":
        return [r.current_position] if r.current_position < n else []
    return list(range(n))


def _answerable(r: EngageRun, position: int) -> bool:
    """SEC-06: never answerable once results are published or the answer was ever revealed."""
    return (
        r.status == "open"
        and not r.results_published
        and position in _visible_positions(r)
        and position not in (r.revealed_positions or [])
        and position not in (r.closed_positions or [])
    )


async def answer(
    request: Request, session: AsyncSession, principal: Principal, run_id: uuid.UUID, body: AnswerIn
) -> dict[str, Any]:
    await ratelimit.hit(f"engage:answer:{principal.user_id}", ANSWER_RULES, scope="engage.answer")
    async with system_context(session, "engage.answer"):
        r = await session.get(EngageRun, run_id)
        if r is None:
            raise ProblemError("not_found")
        await refresh_status(session, r)
        p = await _participant(session, r.id, principal.user_id)
    if p is None:
        raise _problem("not_joined", 403, "Join the activity first")
    q = next((x for x in r.questions if x["id"] == str(body.question_id)), None)
    if q is None:
        raise ProblemError("not_found")
    if not _answerable(r, int(q["position"])):
        raise _problem("question_not_open", 409, "This question isn't accepting answers right now")
    ans, terms, filtered, correct = _build_answer(r, q, body)
    rid = (
        await session.execute(
            pg_insert(EngageResponse)
            .values(
                id=uuid7(),
                run_id=r.id,
                participant_id=p.id,
                organization_id=r.organization_id,
                user_id=principal.user_id,
                question_id=body.question_id,
                answer=ans,
                terms=terms,
                filtered=filtered,
                is_correct=correct,
            )
            .on_conflict_do_nothing(index_elements=["participant_id", "question_id"])
            .returning(EngageResponse.id, EngageResponse.answered_at)
        )
    ).first()
    if rid is None:
        raise _problem("already_answered", 409, "You already answered this question")
    return {"question_id": str(body.question_id), "accepted": True, "answered_at": to_rfc3339(rid[1])}


def _build_answer(
    r: EngageRun, q: dict[str, Any], body: AnswerIn
) -> tuple[dict[str, Any], list[str], bool, bool | None]:
    kind = q["kind"]

    def err(field: str, msg: str) -> ProblemError:
        return _invalid([{"field": field, "code": "invalid", "message": msg}])

    if kind in CHOICE_KINDS:
        ids = [str(i) for i in dict.fromkeys(body.option_ids or [])]
        valid = {o["id"] for o in q["options"]}
        if not ids or any(i not in valid for i in ids):
            raise err("option_ids", "choose from the question's options")
        if kind == "single_choice" and len(ids) != 1:
            raise err("option_ids", "choose exactly one option")
        correct: bool | None = None
        if r.settings.get("winner_rule") is not None:  # quiz
            correct = set(ids) == {o["id"] for o in q["options"] if o.get("is_correct")}
        return {"option_ids": ids}, [], False, correct
    if kind == "word":
        raw = (body.text or "").strip()
        terms = normalise_terms(raw, q.get("max_words")) if raw else []
        if not terms:
            raise err("text", "enter a word")
        filtered = any(is_blocked(t) for t in terms)
        return {"text": raw[:200]}, terms, filtered, None
    if kind == "text":
        raw = (body.text or "").strip()
        if not raw:
            raise err("text", "enter an answer")
        return {"text": raw[:500]}, [], is_blocked(raw), None
    if kind == "rating":
        if body.rating is None:
            raise err("rating", "choose 1-5")
        return {"rating": int(body.rating)}, [], False, None
    raise err("question_id", "unsupported question")


# =========================================================================== aggregation


async def _counts(session: AsyncSession, run_id: uuid.UUID) -> tuple[int, int, int]:
    row = (
        await session.execute(
            text(
                "SELECT (SELECT count(*) FROM engage_participants WHERE run_id = :r), "
                "(SELECT count(DISTINCT participant_id) FROM engage_responses WHERE run_id = :r), "
                "(SELECT count(*) FROM engage_responses WHERE run_id = :r)"
            ),
            {"r": run_id},
        )
    ).one()
    return int(row[0]), int(row[1]), int(row[2])


def version_of(r: EngageRun, counts: tuple[int, int, int], extra: str = "") -> str:
    raw = f"{r.id}:{r.state_version}:{r.status}:{counts[0]}:{counts[1]}:{counts[2]}:{extra}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


async def _aggregate(session: AsyncSession, r: EngageRun) -> dict[str, Any]:
    """Per-question counts for one run (caller holds a system context)."""
    rid = {"r": r.id}
    answered = {
        str(q): int(n)
        for q, n in (
            await session.execute(
                text("SELECT question_id, count(*) FROM engage_responses WHERE run_id = :r GROUP BY 1"), rid
            )
        ).all()
    }
    choice: dict[str, dict[str, int]] = defaultdict(dict)
    for q, opt, n in (
        await session.execute(
            text(
                "SELECT question_id, o, count(*) FROM engage_responses, "
                "jsonb_array_elements_text(coalesce(answer->'option_ids', '[]'::jsonb)) AS o "
                "WHERE run_id = :r GROUP BY 1, 2"
            ),
            rid,
        )
    ).all():
        choice[str(q)][str(opt)] = int(n)
    words: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for q, term, n in (
        await session.execute(
            text(
                "SELECT question_id, t, count(*) AS n FROM engage_responses, unnest(terms) AS t "
                "WHERE run_id = :r AND NOT filtered GROUP BY 1, 2 ORDER BY 1, n DESC, t"
            ),
            rid,
        )
    ).all():
        if len(words[str(q)]) < WORD_TOP:
            words[str(q)].append({"term": term, "count": int(n)})
    ratings: dict[str, dict[str, int]] = defaultdict(dict)
    for q, val, n in (
        await session.execute(
            text(
                "SELECT question_id, (answer->>'rating')::int, count(*) FROM engage_responses "
                "WHERE run_id = :r AND answer ? 'rating' GROUP BY 1, 2"
            ),
            rid,
        )
    ).all():
        ratings[str(q)][str(val)] = int(n)
    return {"answered": answered, "choice": choice, "words": words, "ratings": ratings}


def _question_result(
    q: dict[str, Any], agg: dict[str, Any], *, with_dist: bool, with_correct: bool
) -> dict[str, Any]:
    qid = q["id"]
    total = agg["answered"].get(qid, 0)
    out = _public_question(q)
    out["answered"] = total
    if q["kind"] in CHOICE_KINDS:
        counts = agg["choice"].get(qid, {})
        for o_out, o in zip(out["options"], q["options"], strict=True):
            if with_dist:
                c = counts.get(o["id"], 0)
                o_out["count"] = c
                o_out["pct"] = round(100 * c / total) if total else 0
            if with_correct:
                o_out["correct"] = bool(o.get("is_correct"))
    elif q["kind"] == "word" and with_dist:
        out["words"] = agg["words"].get(qid, [])
    elif q["kind"] == "rating" and with_dist:
        dist = {str(i): agg["ratings"].get(qid, {}).get(str(i), 0) for i in range(1, 6)}
        n = sum(dist.values())
        out["ratings"] = dist
        out["average"] = round(sum(int(k) * v for k, v in dist.items()) / n, 2) if n else None
    return out


async def _leaderboard(
    session: AsyncSession, r: EngageRun, participants: dict[uuid.UUID, EngageParticipant]
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]], dict[uuid.UUID, dict[str, Any]]]:
    """Quiz scoring. Returns (ranked rows, per-question winners, per-participant row).

    * ``fastest_first``: each question's winner is the earliest correct answer (server clock,
      ties broken by response id = insertion order); ranking by wins, then correct answers, then
      total answer time of correct answers.
    * ``all_correct``: ranking by correct answers, then total time.
    """
    anon = r.settings.get("identity_mode") == "anonymous"
    rule = r.settings.get("winner_rule")
    started = r.opened_at or r.created_at
    rows = (
        await session.execute(
            select(EngageResponse.participant_id, EngageResponse.question_id, EngageResponse.answered_at)
            .where(EngageResponse.run_id == r.id, EngageResponse.is_correct.is_(True))
            .order_by(EngageResponse.question_id, EngageResponse.answered_at, EngageResponse.id)
        )
    ).all()
    score: dict[uuid.UUID, dict[str, Any]] = {}
    winners: dict[str, dict[str, Any]] = {}
    by_q: dict[str, list[uuid.UUID]] = defaultdict(list)
    for pid, qid, at in rows:
        s = score.setdefault(pid, {"wins": 0, "correct": 0, "time_ms": 0})
        s["correct"] += 1
        s["time_ms"] += max(0, int((at - started).total_seconds() * 1000)) if started else 0
        by_q[str(qid)].append(pid)
    for q_key, pids in by_q.items():
        first = pids[0]
        if rule == "fastest_first":
            score[first]["wins"] += 1
        winners[q_key] = {
            "fastest": _label(participants.get(first), anon),
            "also_correct": [_label(participants.get(p), anon) for p in pids[1:6]],
            "also_correct_count": max(0, len(pids) - 1),
        }
    if rule == "fastest_first":
        order = sorted(score.items(), key=lambda kv: (-kv[1]["wins"], -kv[1]["correct"], kv[1]["time_ms"]))
    else:
        order = sorted(score.items(), key=lambda kv: (-kv[1]["correct"], kv[1]["time_ms"]))
    ranked: list[dict[str, Any]] = []
    mine: dict[uuid.UUID, dict[str, Any]] = {}
    for i, (pid, s) in enumerate(order, start=1):
        row = {"rank": i, "label": _label(participants.get(pid), anon), **s}
        mine[pid] = row
        if i <= LEADERBOARD_TOP:
            ranked.append(row)
    return ranked, winners, mine


async def _participants_map(session: AsyncSession, run_id: uuid.UUID) -> dict[uuid.UUID, EngageParticipant]:
    return {
        p.id: p
        for p in (
            await session.execute(select(EngageParticipant).where(EngageParticipant.run_id == run_id))
        ).scalars()
    }


async def _texts(
    session: AsyncSession, r: EngageRun, participants: dict[uuid.UUID, EngageParticipant]
) -> dict[str, list[dict[str, Any]]]:
    anon = r.settings.get("identity_mode") == "anonymous"
    out: dict[str, list[dict[str, Any]]] = defaultdict(list)
    text_q = {q["id"] for q in r.questions if q["kind"] == "text"}
    if not text_q:
        return out
    rows = (
        await session.execute(
            select(
                EngageResponse.question_id,
                EngageResponse.participant_id,
                EngageResponse.answer,
                EngageResponse.filtered,
            )
            .where(EngageResponse.run_id == r.id)
            .order_by(EngageResponse.answered_at.desc())
        )
    ).all()
    for qid, pid, ans, filtered in rows:
        k = str(qid)
        if k in text_q and len(out[k]) < TEXT_SAMPLE:
            out[k].append(
                {
                    "label": _label(participants.get(pid), anon),
                    "text": None if filtered else ans.get("text"),
                    "filtered": filtered,
                }
            )
    return out


async def presenter_state(
    request: Request, session: AsyncSession, principal: Principal, run_id: uuid.UUID, since: str | None
) -> tuple[dict[str, Any], str]:
    r, a = await _manager_run(request, session, principal, run_id)
    async with system_context(session, "engage.presenter"):
        counts = await _counts(session, r.id)
        version = version_of(r, counts)
        if since and since == version:
            return {"unchanged": True, "version": version}, version
        agg = await _aggregate(session, r)
        participants = await _participants_map(session, r.id)
        is_quiz = r.settings.get("winner_rule") is not None
        ranked, winners, _ = await _leaderboard(session, r, participants) if is_quiz else ([], {}, {})
        texts = await _texts(session, r, participants)
    anon = r.settings.get("identity_mode") == "anonymous"
    questions = []
    for q in r.questions:
        qr = _question_result(q, agg, with_dist=True, with_correct=True)
        qr["revealed"] = q["position"] in (r.revealed_positions or [])
        if is_quiz:
            qr["winner"] = winners.get(q["id"])
        if q["kind"] == "text":
            qr["texts"] = texts.get(q["id"], [])
        questions.append(qr)
    recent = sorted(participants.values(), key=lambda p: p.seq)
    return (
        {
            "version": version,
            "run": run_summary(r),
            "activity": {
                "id": str(a.id),
                "title": a.title,
                "description": a.description,
                "activity_type": a.activity_type,
            },
            "joined": counts[0],
            "voted": counts[1],
            "total_votes": counts[2],
            "participants": [{"label": _label(p, anon), "seq": p.seq} for p in recent[-50:]],
            "questions": questions,
            "leaderboard": ranked,
        },
        version,
    )


async def participant_state(
    request: Request, session: AsyncSession, principal: Principal, run_id: uuid.UUID, since: str | None
) -> tuple[dict[str, Any], str]:
    async with system_context(session, "engage.live"):
        r = await session.get(EngageRun, run_id)
        if r is None:
            raise ProblemError("not_found")
        a = await session.get(EngageActivity, r.activity_id)
        if a is None:
            raise ProblemError("not_found")
        await refresh_status(session, r)
        p = await _participant(session, r.id, principal.user_id)
        if p is None:
            raise _problem("not_joined", 403, "Join the activity first")
        mine_rows = (
            await session.execute(
                select(
                    EngageResponse.question_id,
                    EngageResponse.answer,
                    EngageResponse.is_correct,
                    EngageResponse.answered_at,
                ).where(EngageResponse.participant_id == p.id)
            )
        ).all()
        counts = await _counts(session, r.id)
        version = version_of(r, counts, f"{p.id}:{len(mine_rows)}")
        if since and since == version:
            return {"unchanged": True, "version": version}, version
        live = r.settings.get("results_mode") == "live"
        visible = _visible_positions(r)
        revealed = set(r.revealed_positions or [])
        needs_agg = live or r.results_published or bool(revealed)
        empty: dict[str, Any] = {"answered": {}, "choice": {}, "words": {}, "ratings": {}}
        agg = await _aggregate(session, r) if needs_agg else empty
        is_quiz = r.settings.get("winner_rule") is not None
        show_board = is_quiz and r.results_published
        if show_board:
            participants = await _participants_map(session, r.id)
            ranked, _w, by_p = await _leaderboard(session, r, participants)
        else:
            ranked, by_p = [], {}
    mine = {str(q): (ans, ok, at) for q, ans, ok, at in mine_rows}
    anon = r.settings.get("identity_mode") == "anonymous"
    questions = []
    for q in r.questions:
        pos = int(q["position"])
        if pos not in visible:
            continue
        shown = pos in revealed or r.results_published
        live_kind = live and q["kind"] in ("single_choice", "multi_choice", "rating")
        qr = _question_result(q, agg, with_dist=shown or live_kind, with_correct=shown and is_quiz)
        qr["revealed"] = pos in revealed
        qr["answerable"] = _answerable(r, pos) and q["id"] not in mine
        m = mine.get(q["id"])
        qr["my_answer"] = m[0] if m else None
        if m and shown and is_quiz:
            qr["my_correct"] = m[1]
        questions.append(qr)
    return (
        {
            "version": version,
            "run": {
                "id": str(r.id),
                "status": r.status,
                "pacing": r.settings.get("pacing"),
                "results_mode": r.settings.get("results_mode"),
                "identity_mode": r.settings.get("identity_mode"),
                "current_position": r.current_position,
                "question_count": len(r.questions),
                "results_published": r.results_published,
                "closes_at": to_rfc3339(r.closes_at) if r.closes_at else None,
            },
            "activity": {"title": a.title, "description": a.description, "activity_type": a.activity_type},
            "me": {"label": _label(p, anon), "answered": len(mine_rows)},
            "joined": counts[0],
            "questions": questions,
            "leaderboard": ranked if show_board else [],
            "my_rank": by_p.get(p.id) if show_board else None,
        },
        version,
    )


async def my_runs(session: AsyncSession, principal: Principal) -> dict[str, Any]:
    """Runs the caller joined (newest first) for the learner Engage page."""
    rows = (
        await session.execute(
            select(EngageParticipant.run_id, EngageParticipant.joined_at)
            .where(EngageParticipant.user_id == principal.user_id)
            .order_by(EngageParticipant.joined_at.desc())
            .limit(50)
        )
    ).all()
    out = []
    async with system_context(session, "engage.my_runs"):
        for run_id, joined_at in rows:
            r = await session.get(EngageRun, run_id)
            a = await session.get(EngageActivity, r.activity_id) if r else None
            if r is None or a is None or a.deleted_at is not None:
                continue
            out.append(
                {
                    "run_id": str(r.id),
                    "title": a.title,
                    "activity_type": a.activity_type,
                    "status": r.status,
                    "results_published": r.results_published,
                    "joined_at": to_rfc3339(joined_at),
                }
            )
    return {"data": out}
