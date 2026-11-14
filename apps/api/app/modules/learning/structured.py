"""Structured assignments: sections -> items, batch allocations with schedules, per-item
learner responses, deterministic / AI-suggested / human grading (WISEMAN-FEATURES "assign").

This module is the service layer; HTTP lives in ``structured_api``. It never executes learner
code (coding items cite the learner's own judged ``code_submissions`` through the coding
module's public functions) and only reaches AI through ``app.modules.ai.service``. AI marks are
stored as *pending suggestions*; a staff ``finalize`` is always required before a learner sees
a mark.

Grading engines (chosen per section on each allocation):

* ``pure_objective`` — choice / numeric / fill-blank items and coding items are scored by rules
  (answer key, judge score); written and file answers wait for a human.
* ``pure_ai`` — rules for objective items, AI suggestions for everything else (code included).
* ``ai_human`` — like ``pure_ai``; the evaluation list flags every AI-suggested item for review.
* ``adaptive`` — rules wherever they apply (objective + judged code), AI for the rest; AI
  suggestions with confidence < 0.6 are flagged for review.
* ``pure_manual`` — no automatic marks except 0 for unanswered items.

Store: ``TD_STORE_LEARNING=firestore`` routes every learning-table read/write through
``fs_store`` / ``fs_assign`` (the Postgres statements below are unchanged). The SQL filter
builders (``allocated_to_*_filter`` / ``evaluator_filter``) have Firestore twins in
``fs_assign`` that return assignment-id sets.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import and_, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import ScopeRef
from app.core.errors import ProblemError
from app.core.ids import uuid7
from app.core.time import to_rfc3339, utcnow
from app.modules.learning import fs_assign as fsa
from app.modules.learning import fs_store as fss
from app.modules.learning.models import (
    Assignment,
    AssignmentAllocation,
    AssignmentItem,
    AssignmentItemResponse,
    AssignmentRegradeRequest,
    AssignmentSection,
    AssignmentSubmission,
)

ENGINES = ("pure_ai", "ai_human", "pure_objective", "adaptive", "pure_manual")
AI_ENGINES = frozenset({"pure_ai", "ai_human", "adaptive"})
RULE_ENGINES = frozenset({"pure_objective", "pure_ai", "ai_human", "adaptive"})
OBJECTIVE_TYPES = frozenset({"mcq_single", "mcq_multi", "numeric", "fill_blank"})
INLINE_TYPES = ("essay", "short_text", "file", "coding")
UNGRADED_BANK_TYPES = frozenset({"poll", "survey", "word_cloud"})
LOW_CONFIDENCE = 0.6
MAX_TEXT = {"essay": 50_000, "short_text": 2_000}
MAX_FILES = 5
TWO = Decimal("0.01")


def _vf(field: str, code: str, msg: str) -> ProblemError:
    return ProblemError("validation_failed", 422, errors=[{"field": field, "code": code, "message": msg}])


def locked_error() -> ProblemError:
    return ProblemError(
        "assignment_locked",
        409,
        "Assignment locked",
        detail="Learners have started this assignment; its questions and marks can no longer change.",
    )


def iso(dt: datetime | None) -> str | None:
    return to_rfc3339(dt) if dt is not None else None


def f(v: Decimal | None) -> float | None:
    return float(v) if v is not None else None


# --------------------------------------------------------------------------- scope / visibility


def scope_of(batch_id: uuid.UUID | None, course_id: uuid.UUID | None, org_id: uuid.UUID | None) -> ScopeRef:
    """RBAC scope of an assignment: owning batch, else course, else (structured, company-wide)
    the company organization. Nothing grants at organization scope any more, so a company-wide
    assignment is covered by platform grants only (batch staff reach it via allocations)."""
    if batch_id is not None:
        return ScopeRef("batch", batch_id)
    if course_id is not None:
        return ScopeRef("course", course_id)
    if org_id is not None:
        return ScopeRef("organization", org_id)
    return ScopeRef("platform", None)


def _learner_target(user_id: uuid.UUID, batches: set[uuid.UUID]) -> Any:
    A = AssignmentAllocation
    target = A.user_ids.contains([user_id])
    return or_(A.batch_id.in_(batches), target) if batches else target


def allocated_to_learner_filter(user_id: uuid.UUID, batches: set[uuid.UUID], now: datetime) -> Any:
    """Assignments allocated to the learner (batch or explicit list) that are visible now, or
    that the learner already handed in (results stay reachable after "Visible until")."""
    A = AssignmentAllocation
    handed_in = exists(
        select(AssignmentSubmission.id).where(
            AssignmentSubmission.assignment_id == A.assignment_id,
            AssignmentSubmission.user_id == user_id,
            AssignmentSubmission.status != "draft",
        )
    )
    visible = and_(
        A.status == "active",
        or_(A.visible_from.is_(None), A.visible_from <= now),
        or_(A.visible_until.is_(None), A.visible_until >= now),
    )
    return Assignment.id.in_(
        select(A.assignment_id).where(_learner_target(user_id, batches), or_(visible, handed_in))
    )


def allocated_to_batches_filter(batches: set[uuid.UUID]) -> Any:
    return Assignment.id.in_(
        select(AssignmentAllocation.assignment_id).where(AssignmentAllocation.batch_id.in_(batches))
    )


def evaluator_filter(user_id: uuid.UUID) -> Any:
    """Assignments with an allocation that names ``user_id`` in ``evaluator_ids``."""
    return Assignment.id.in_(
        select(AssignmentAllocation.assignment_id).where(
            AssignmentAllocation.evaluator_ids.contains([user_id])
        )
    )


async def is_named_evaluator(session: AsyncSession, assignment_id: uuid.UUID, user_id: uuid.UUID) -> bool:
    if fss.fs():
        return any(user_id in al.evaluator_ids for al in await fsa.allocations_of(session, assignment_id))
    row = await session.execute(
        select(AssignmentAllocation.id)
        .where(
            AssignmentAllocation.assignment_id == assignment_id,
            AssignmentAllocation.evaluator_ids.contains([user_id]),
        )
        .limit(1)
    )
    return row.first() is not None


async def allocation_batches(session: AsyncSession, assignment_id: uuid.UUID) -> list[uuid.UUID]:
    if fss.fs():
        return [
            al.batch_id for al in await fsa.allocations_of(session, assignment_id) if al.batch_id is not None
        ]
    rows = await session.execute(
        select(AssignmentAllocation.batch_id).where(
            AssignmentAllocation.assignment_id == assignment_id, AssignmentAllocation.batch_id.is_not(None)
        )
    )
    return [r for r in rows.scalars() if r is not None]


async def structure_counts(
    session: AsyncSession, assignment_ids: list[uuid.UUID]
) -> dict[uuid.UUID, tuple[int, int]]:
    if fss.fs():
        out: dict[uuid.UUID, tuple[int, int]] = {}
        for aid in assignment_ids:
            n_secs = await fss.count(AssignmentSection, (("assignment_id", "==", aid),))
            n_items = await fss.count(AssignmentItem, (("assignment_id", "==", aid),))
            out[aid] = (n_secs, n_items)
        return out
    secs = dict(
        (
            await session.execute(
                select(AssignmentSection.assignment_id, func.count())
                .where(AssignmentSection.assignment_id.in_(assignment_ids))
                .group_by(AssignmentSection.assignment_id)
            )
        ).all()
    )
    items = dict(
        (
            await session.execute(
                select(AssignmentItem.assignment_id, func.count())
                .where(AssignmentItem.assignment_id.in_(assignment_ids))
                .group_by(AssignmentItem.assignment_id)
            )
        ).all()
    )
    return {aid: (int(secs.get(aid, 0)), int(items.get(aid, 0))) for aid in assignment_ids}


async def unfinalized_count(session: AsyncSession, assignment_id: uuid.UUID) -> int:
    if fss.fs():
        return await fss.count(
            AssignmentSubmission,
            (("assignment_id", "==", assignment_id), ("status", "in", ["submitted", "late"])),
        )
    return int(
        (
            await session.execute(
                select(func.count()).where(
                    AssignmentSubmission.assignment_id == assignment_id,
                    AssignmentSubmission.status.in_(("submitted", "late")),
                )
            )
        ).scalar_one()
    )


async def is_locked(session: AsyncSession, assignment_id: uuid.UUID) -> bool:
    if fss.fs():
        return await fss.count(AssignmentSubmission, (("assignment_id", "==", assignment_id),)) > 0
    return (
        await session.execute(
            select(AssignmentSubmission.id)
            .where(AssignmentSubmission.assignment_id == assignment_id)
            .limit(1)
        )
    ).first() is not None


async def check_patch(session: AsyncSession, a: Assignment, data: dict[str, Any]) -> None:
    """LRN-15 additions: ``max_score`` / AI-help settings are for structured assignments;
    ``max_score`` is frozen once a learner has started."""
    keys = {"max_score", "ai_help_enabled", "ai_help_limit"} & set(data)
    if not keys:
        return
    if a.submission_type != "structured":
        k = sorted(keys)[0]
        raise _vf(k, "structured_only", "Only structured assignments have this setting")
    if data.get("max_score") is not None and Decimal(data["max_score"]) != a.max_score:
        if await is_locked(session, a.id):
            raise locked_error()


# --------------------------------------------------------------------------- structure


async def load_structure(
    session: AsyncSession, assignment_id: uuid.UUID
) -> list[tuple[AssignmentSection, list[AssignmentItem]]]:
    if fss.fs():
        fs_secs = await fsa.sections_of(session, assignment_id)
        fs_by: dict[uuid.UUID, list[AssignmentItem]] = defaultdict(list)
        for fit in await fsa.items_of(session, assignment_id):
            fs_by[fit.section_id].append(fit)
        return [(s, fs_by.get(s.id, [])) for s in fs_secs]
    secs = list(
        (
            await session.execute(
                select(AssignmentSection)
                .where(AssignmentSection.assignment_id == assignment_id)
                .order_by(AssignmentSection.position)
            )
        ).scalars()
    )
    items = (
        await session.execute(
            select(AssignmentItem)
            .where(AssignmentItem.assignment_id == assignment_id)
            .order_by(AssignmentItem.position)
        )
    ).scalars()
    by_sec: dict[uuid.UUID, list[AssignmentItem]] = defaultdict(list)
    for it in items:
        by_sec[it.section_id].append(it)
    return [(s, by_sec.get(s.id, [])) for s in secs]


def marks_check(
    a: Assignment, structure: list[tuple[AssignmentSection, list[AssignmentItem]]]
) -> dict[str, Any]:
    """Item marks must add up to each section's max (when set) and to the assignment total."""
    issues: list[dict[str, str]] = []
    total = Decimal(0)
    n_items = 0
    for i, (s, items) in enumerate(structure):
        st = sum((it.marks for it in items), Decimal(0))
        total += st
        n_items += len(items)
        if s.max_score is not None and st != s.max_score:
            issues.append(
                {
                    "field": f"sections.{i}.max_score",
                    "code": "section_marks_mismatch",
                    "message": f"{s.title}: items add up to {st:g}, section is out of {s.max_score:g}",
                }
            )
        for j, it in enumerate(items):
            if it.marks <= 0:
                issues.append(
                    {
                        "field": f"sections.{i}.items.{j}.marks",
                        "code": "zero_marks",
                        "message": f"{s.title} question {j + 1} has no marks",
                    }
                )
    if n_items == 0:
        issues.append({"field": "sections", "code": "empty", "message": "Add at least one question"})
    if total != a.max_score:
        issues.append(
            {
                "field": "marks",
                "code": "marks_mismatch",
                "message": f"Question marks add up to {total:g}; the total is {a.max_score:g}",
            }
        )
    return {"allocated": float(total), "total": float(a.max_score), "ok": not issues, "issues": issues}


@dataclass(frozen=True, slots=True)
class ItemSpec:
    source: str
    marks: Decimal
    question_id: uuid.UUID | None = None
    question_version_id: uuid.UUID | None = None
    item_type: str | None = None
    prompt_md: str | None = None
    coding_problem_id: uuid.UUID | None = None
    rubric: dict[str, Any] | None = None
    reference_answer_md: str | None = None


@dataclass(frozen=True, slots=True)
class SectionSpec:
    title: str
    max_score: Decimal | None
    items: list[ItemSpec]


def _bank_item_type(question_type: str) -> str:
    if question_type in OBJECTIVE_TYPES or question_type == "coding":
        return question_type
    return "essay" if question_type == "essay" else "short_text"


async def _resolve_bank_item(
    session: AsyncSession, spec: ItemSpec, field: str
) -> tuple[uuid.UUID, uuid.UUID, str, uuid.UUID | None]:
    """(question_id, pinned published version id, item_type, coding_problem_id) through the
    placement bank (RLS hides other organizations' private questions -> not_found). Reads go
    through ``placement.bank`` (``get_question`` / ``versions_of``), which follow its own store."""
    from app.modules.placement import public as bank

    assert spec.question_id is not None
    from app.modules.placement import public as placement_public

    q = await placement_public.get_question(session, spec.question_id)
    if q is None or q.deleted_at is not None:  # as placement.bank.get_question: not_found
        raise _vf(f"{field}.question_id", "not_found", "Unknown question")
    versions = {v.id: v for v in await bank.versions_of(session, q.id)}
    if spec.question_version_id is not None:
        qv = versions.get(spec.question_version_id)
        if qv is None or qv.question_id != q.id:
            raise _vf(f"{field}.question_version_id", "invalid", "Version does not belong to the question")
    else:
        qv = versions.get(q.current_version_id) if q.current_version_id else None
        if qv is None or q.status != "active":
            raise _vf(f"{field}.question_id", "not_published", "Publish the question before using it")
    if qv.status not in ("published", "retired") or qv.published_at is None:
        raise _vf(f"{field}.question_version_id", "not_published", "Only published versions can be used")
    if q.question_type in UNGRADED_BANK_TYPES:
        raise _vf(
            f"{field}.question_id", "unsupported_type", "Polls and surveys cannot be graded in an assignment"
        )
    item_type = _bank_item_type(q.question_type)
    if item_type == "coding" and qv.coding_problem_id is None:
        raise _vf(f"{field}.question_id", "invalid", "This coding question has no coding problem")
    return q.id, qv.id, item_type, qv.coding_problem_id


async def put_structure(session: AsyncSession, a: Assignment, sections: list[SectionSpec]) -> None:
    if await is_locked(session, a.id):
        raise locked_error()
    Resolved = tuple[ItemSpec, uuid.UUID | None, uuid.UUID | None, str, uuid.UUID | None]
    resolved: list[list[Resolved]] = []
    for i, sec in enumerate(sections):
        row: list[Resolved] = []
        for j, it in enumerate(sec.items):
            field = f"sections.{i}.items.{j}"
            if it.source == "bank":
                bank_ref = await _resolve_bank_item(session, it, field)
                row.append((it, bank_ref[0], bank_ref[1], bank_ref[2], bank_ref[3]))
            else:
                itype = it.item_type or "essay"
                pid = it.coding_problem_id
                if itype == "coding":
                    if pid is None:
                        raise _vf(f"{field}.coding_problem_id", "required", "Pick a coding problem")
                    from app.modules.coding.public import published_problem

                    try:
                        await published_problem(session, pid)
                    except ProblemError as e:
                        raise _vf(f"{field}.coding_problem_id", "not_found", "Unknown coding problem") from e
                elif pid is not None:
                    raise _vf(f"{field}.coding_problem_id", "invalid", "Only coding items take a problem")
                row.append((it, None, None, itype, pid))
        resolved.append(row)
    for s, old_items in await load_structure(session, a.id):
        if fss.fs():  # Postgres: ON DELETE CASCADE removes the items
            for old in old_items:
                await fss.delete(session, old)
        await fss.delete(session, s)
    await fss.flush(session)
    for i, sec in enumerate(sections):
        s = AssignmentSection(
            id=uuid7(),
            assignment_id=a.id,
            organization_id=a.organization_id,
            position=i + 1,
            title=sec.title,
            max_score=sec.max_score,
        )
        fss.add(session, s)
        await fss.flush(session)
        for j, (it, qid, qvid, itype, pid) in enumerate(resolved[i]):
            fss.add(
                session,
                AssignmentItem(
                    id=uuid7(),
                    section_id=s.id,
                    assignment_id=a.id,
                    organization_id=a.organization_id,
                    position=j + 1,
                    source=it.source,
                    item_type=itype,
                    question_id=qid,
                    question_version_id=qvid,
                    coding_problem_id=pid,
                    prompt_md=it.prompt_md if it.source == "inline" else None,
                    marks=it.marks,
                    rubric=it.rubric,
                    reference_answer_md=it.reference_answer_md,
                ),
            )
    a.updated_at = utcnow()
    await fss.flush(session)
    if fss.fs():
        await fsa.touch(a)


async def clone_structure(session: AsyncSession, src: Assignment, dst: Assignment) -> None:
    for s, items in await load_structure(session, src.id):
        ns = AssignmentSection(
            id=uuid7(),
            assignment_id=dst.id,
            organization_id=dst.organization_id,
            position=s.position,
            title=s.title,
            max_score=s.max_score,
        )
        fss.add(session, ns)
        await fss.flush(session)
        for it in items:
            fss.add(
                session,
                AssignmentItem(
                    id=uuid7(),
                    section_id=ns.id,
                    assignment_id=dst.id,
                    organization_id=dst.organization_id,
                    position=it.position,
                    source=it.source,
                    item_type=it.item_type,
                    question_id=it.question_id,
                    question_version_id=it.question_version_id,
                    coding_problem_id=it.coding_problem_id,
                    prompt_md=it.prompt_md,
                    marks=it.marks,
                    rubric=it.rubric,
                    reference_answer_md=it.reference_answer_md,
                ),
            )
    await fss.flush(session)


async def bundles_for(session: AsyncSession, items: list[AssignmentItem]) -> dict[uuid.UUID, Any]:
    from app.modules.placement import public as bank

    ids = [it.question_version_id for it in items if it.question_version_id is not None]
    return await bank.load_bundles(session, ids)


def item_content(it: AssignmentItem, bundles: dict[uuid.UUID, Any], *, staff: bool) -> dict[str, Any]:
    """Learner-safe item payload (no keys); ``staff`` adds the key, rubric and reference answer."""
    from app.modules.placement import public as bank

    out: dict[str, Any] = {
        "id": str(it.id),
        "position": it.position,
        "item_type": it.item_type,
        "marks": float(it.marks),
        "prompt_md": it.prompt_md,
        "stem_html": None,
        "options": [],
        "coding_problem_id": str(it.coding_problem_id) if it.coding_problem_id else None,
        "settings": None,
    }
    b = bundles.get(it.question_version_id) if it.question_version_id else None
    if b is not None:
        d = bank.delivery(b, marks=it.marks)
        out["stem_html"] = d.get("stem_html")
        out["options"] = d.get("options", [])
        out["settings"] = d.get("settings") or _settings(b) or None
    if staff:
        out.update(
            {
                "source": it.source,
                "question_id": str(it.question_id) if it.question_id else None,
                "question_version_id": str(it.question_version_id) if it.question_version_id else None,
                "rubric": it.rubric,
                "reference_answer_md": it.reference_answer_md,
                "key": bank.key_payload(b) if b is not None else None,
            }
        )
    return out


def question_text(it: AssignmentItem, bundles: dict[uuid.UUID, Any]) -> str:
    """Plain question text for AI calls (the stem only — never options' keys)."""
    import re

    b = bundles.get(it.question_version_id) if it.question_version_id else None
    if b is not None:
        from app.modules.placement import public as bank

        html = bank.delivery(b).get("stem_html") or ""
        return re.sub(r"<[^>]+>", " ", html).strip()
    return it.prompt_md or ""


# --------------------------------------------------------------------------- allocations


def allocation_out(al: AssignmentAllocation, batch_name: str | None = None) -> dict[str, Any]:
    return {
        "id": str(al.id),
        "assignment_id": str(al.assignment_id),
        "batch_id": str(al.batch_id) if al.batch_id else None,
        "batch_name": batch_name,
        "user_ids": [str(u) for u in al.user_ids],
        "visible_from": iso(al.visible_from),
        "visible_until": iso(al.visible_until),
        "start_at": iso(al.start_at),
        "due_at": iso(al.due_at),
        "section_engines": dict(al.section_engines),
        "evaluator_ids": [str(u) for u in al.evaluator_ids],
        "extensions": dict(al.extensions),
        "status": al.status,
        "created_at": iso(al.created_at),
    }


def check_schedule(
    visible_from: datetime | None, visible_until: datetime | None, start_at: datetime | None, due_at: datetime
) -> None:
    if visible_from and visible_until and visible_until <= visible_from:
        raise _vf("visible_until", "before_visible_from", "Visible until must be after Visible from")
    if start_at and start_at >= due_at:
        raise _vf("start_at", "after_due", "Can start at must be before Must submit by")
    if visible_from and start_at and start_at < visible_from:
        raise _vf("start_at", "before_visible", "Learners cannot start before the assignment is visible")
    if visible_from and due_at <= visible_from:
        raise _vf("due_at", "before_visible", "Must submit by must be after Visible from")
    if visible_until and due_at > visible_until:
        raise _vf("visible_until", "before_due", "Keep the assignment visible until the submission deadline")


def check_engines(engines: dict[str, str], section_ids: list[uuid.UUID]) -> dict[str, str]:
    known = {str(s) for s in section_ids}
    for k, v in engines.items():
        if k not in known:
            raise _vf(f"section_engines.{k}", "unknown", "Not a section of this assignment")
        if v not in ENGINES:
            raise _vf(f"section_engines.{k}", "invalid", "Unknown grading engine")
    return {s: engines.get(s, "pure_ai") for s in sorted(known)}


async def active_batch_ids(session: AsyncSession, user_id: uuid.UUID) -> set[uuid.UUID]:
    """Batches the user is an ACTIVE member of (SEC-03: removed / transferred members are
    excluded). The single helper for every learner-side batch lookup in this module.
    ``batch_members`` is an orgs table: isolated here until orgs exposes a store-neutral
    lookup (see the data-learning report)."""
    from app.modules.orgs import public as orgs_public

    rows = await orgs_public.batch_members(session, user_ids=[user_id], active_only=False)
    return {m.batch_id for m in rows if m.status == "active"}


async def graders(session: AsyncSession, user_ids: list[uuid.UUID]) -> set[uuid.UUID]:
    """Users that may be listed as an allocation's ``evaluator_ids``: a live grant of a role
    holding ``assignment.grade`` (any scope), or an active company *staff* membership. Listing
    alone never grants anything: at grading time the caller must still hold
    ``assignment.grade`` somewhere (``structured_api._ensure_grade``). System context."""
    from app.modules.orgs import public as orgs_public
    from app.modules.rbac import public as rbac_public

    if not user_ids:
        return set()
    staff = {
        m.user_id for m in await orgs_public.org_memberships(session, user_ids=user_ids, member_type="staff")
    }
    # live grant (unrevoked, unexpired) of a role holding assignment.grade: rbac's public API
    return staff | await rbac_public.user_ids_with_permission(session, "assignment.grade", user_ids)


def targets_learner(al: AssignmentAllocation, user_id: uuid.UUID, batches: set[uuid.UUID]) -> bool:
    return (al.batch_id is not None and al.batch_id in batches) or user_id in al.user_ids


async def org_members(
    session: AsyncSession,
    org_id: uuid.UUID,
    user_ids: list[uuid.UUID],
    batch_ids: set[uuid.UUID] | None = None,
) -> set[uuid.UUID]:
    """Of ``user_ids``, the active members of ``org_id``. With ``batch_ids`` (a batch-scoped
    caller), only active members of one of those batches of the org count (SEC: a trainer may
    allocate only to learners of the batches they manage)."""
    from app.modules.orgs import public as orgs_public

    if not user_ids:
        return set()
    if batch_ids is not None:
        if not batch_ids:
            return set()
        rows = await orgs_public.batch_members(
            session, batch_ids=batch_ids, user_ids=user_ids, organization_id=org_id
        )
        return {m.user_id for m in rows}
    return {
        m.user_id
        for m in await orgs_public.org_memberships(session, user_ids=user_ids, organization_id=org_id)
    }


def effective_due(al: AssignmentAllocation, user_id: uuid.UUID) -> datetime:
    ext = al.extensions.get(str(user_id))
    if ext:
        until = datetime.fromisoformat(str(ext).replace("Z", "+00:00"))
        return max(al.due_at, until)
    return al.due_at


async def learner_allocation(
    session: AsyncSession,
    user_id: uuid.UUID,
    batches: set[uuid.UUID],
    a: Assignment,
    sub: AssignmentSubmission | None = None,
) -> AssignmentAllocation | None:
    if sub is not None and sub.allocation_id is not None:
        al = await fss.get(session, AssignmentAllocation, sub.allocation_id)
        if al is not None:
            return al
    if fss.fs():
        cands = [
            x
            for x in await fsa.allocations_of(session, a.id)
            if x.status == "active" and targets_learner(x, user_id, batches)
        ]
        cands.sort(key=lambda x: (x.created_at, str(x.id)))
        return cands[0] if cands else None
    return (
        await session.execute(
            select(AssignmentAllocation)
            .where(
                AssignmentAllocation.assignment_id == a.id,
                AssignmentAllocation.status == "active",
                _learner_target(user_id, batches),
            )
            .order_by(AssignmentAllocation.created_at, AssignmentAllocation.id)
            .limit(1)
        )
    ).scalar_one_or_none()


def schedule_out(al: AssignmentAllocation | None, user_id: uuid.UUID, now: datetime) -> dict[str, Any]:
    if al is None:
        return {
            "visible_from": None,
            "visible_until": None,
            "start_at": None,
            "due_at": None,
            "can_start": False,
            "can_submit": False,
            "seconds_left": None,
        }
    due = effective_due(al, user_id)
    started = al.start_at is None or now >= al.start_at
    open_ = al.status == "active" and now <= due
    return {
        "visible_from": iso(al.visible_from),
        "visible_until": iso(al.visible_until),
        "start_at": iso(al.start_at),
        "due_at": iso(due),
        "can_start": started and open_,
        "can_submit": started and open_,
        "seconds_left": max(0, int((due - now).total_seconds())) if open_ else 0,
        "extended": due != al.due_at,
    }


async def learner_list_fields(
    session: AsyncSession, principal: Any, a: Assignment, last: AssignmentSubmission | None, now: datetime
) -> dict[str, Any]:
    batches = await active_batch_ids(session, principal.user_id)
    al = await learner_allocation(session, principal.user_id, batches, a, last)
    sched = schedule_out(al, principal.user_id, now)
    return {
        "due_at": sched["due_at"],
        "available_from": sched["start_at"],
        "window": "on_time" if sched["can_submit"] else "closed",
        "schedule": sched,
        "my_status": (last.status if last else "not_submitted"),
    }


# --------------------------------------------------------------------------- responses


def _settings(bundle: Any) -> dict[str, Any]:
    """Per-version presentation/answer settings of a bank question (placement), or {}."""
    if bundle is None:
        return {}
    return dict(getattr(bundle.version, "settings", None) or {})


def normalise_response(
    it: AssignmentItem, bundle: Any, response: Any, user_id: uuid.UUID, allowed_file_types: list[str]
) -> dict[str, Any] | None:
    """Validate a learner's autosaved answer for one item; ``None`` = cleared."""
    if response is None:
        return None
    if not isinstance(response, dict):
        raise _vf("response", "invalid", "must be an object")
    t = it.item_type
    if t in OBJECTIVE_TYPES:
        from app.modules.placement import public as grading

        if bundle is None:
            raise ProblemError("not_found")
        try:
            return grading.normalise_response(t, response, bundle.option_ids, _settings(bundle))
        except ProblemError as e:  # placement uses 400; this module's field errors are 422
            raise ProblemError("validation_failed", 422, errors=e.ext.get("errors", [])) from e
    if t in MAX_TEXT:
        text = response.get("text")
        if text is None or (isinstance(text, str) and not text.strip()):
            return None
        if not isinstance(text, str):
            raise _vf("response.text", "invalid", "must be text")
        if len(text) > MAX_TEXT[t]:
            raise _vf("response.text", "too_long", f"At most {MAX_TEXT[t]} characters")
        # Bank essays carry the author's word limit (placement ``settings.max_words``).
        max_words = _settings(bundle).get("max_words")
        if max_words and len(text.split()) > int(max_words):
            raise _vf("response.text", "too_many_words", f"At most {int(max_words)} words")
        return {"text": text}
    if t == "file":
        keys = response.get("file_s3_keys")
        if not isinstance(keys, list):
            raise _vf("response.file_s3_keys", "invalid", "must be a list")
        if len(keys) > MAX_FILES:
            raise _vf("response.file_s3_keys", "too_many", f"At most {MAX_FILES} files")
        prefix = f"uploads/assignment_submission/{user_id}/"
        allowed = {x.lower().lstrip(".") for x in allowed_file_types}
        for i, k in enumerate(keys):
            if not isinstance(k, str) or not k.startswith(prefix) or ".." in k:
                raise _vf(f"response.file_s3_keys.{i}", "invalid", "Upload the file first")
            name = k.rsplit("/", 1)[-1]
            ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
            if allowed and ext not in allowed:
                raise _vf(f"response.file_s3_keys.{i}", "file_type", "This file type is not allowed")
        return {"file_s3_keys": list(keys)} if keys else None
    if t == "coding":
        src = response.get("source_code")
        lang = response.get("language_key")
        sid = response.get("submission_id")
        if not src and not sid:
            return None
        if not isinstance(lang, str) or not lang or len(lang) > 40:
            raise _vf("response.language_key", "required", "Pick a language")
        if not isinstance(src, str) or len(src) > 100_000:
            raise _vf("response.source_code", "invalid", "Source must be text up to 100 KB")
        out: dict[str, Any] = {"language_key": lang, "source_code": src}
        if sid is not None:
            try:
                out["submission_id"] = str(uuid.UUID(str(sid)))
            except ValueError as e:
                raise _vf("response.submission_id", "invalid", "Not a submission id") from e
        return out
    raise _vf("response", "invalid", "Unsupported item")


async def verify_code_submission(
    session: AsyncSession, it: AssignmentItem, resp: dict[str, Any] | None, user_id: uuid.UUID
) -> None:
    if resp is None or "submission_id" not in resp:
        return
    from app.modules.coding.public import verify_submission_owner

    if not await verify_submission_owner(
        session, uuid.UUID(resp["submission_id"]), user_id, it.coding_problem_id
    ):
        raise _vf("response.submission_id", "not_found", "Run the tests first, then save that run")


async def responses_of(
    session: AsyncSession, submission_id: uuid.UUID
) -> dict[uuid.UUID, AssignmentItemResponse]:
    if fss.fs():
        return {r.item_id: r for r in await fsa.responses_of(session, [submission_id])}
    rows = (
        await session.execute(
            select(AssignmentItemResponse).where(AssignmentItemResponse.submission_id == submission_id)
        )
    ).scalars()
    return {r.item_id: r for r in rows}


async def upsert_response(
    session: AsyncSession, sub: AssignmentSubmission, it: AssignmentItem, resp: dict[str, Any] | None
) -> AssignmentItemResponse:
    if fss.fs():
        return await _upsert_response_fs(session, sub, it, resp)
    row = (
        await session.execute(
            select(AssignmentItemResponse)
            .where(AssignmentItemResponse.submission_id == sub.id, AssignmentItemResponse.item_id == it.id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    now = utcnow()
    if row is None:
        row = AssignmentItemResponse(
            id=uuid7(),
            submission_id=sub.id,
            item_id=it.id,
            user_id=sub.user_id,
            organization_id=sub.organization_id,
        )
        fss.add(session, row)
    row.response = resp
    row.saved_at = now
    await fss.flush(session)
    return row


async def _upsert_response_fs(
    session: AsyncSession, sub: AssignmentSubmission, it: AssignmentItem, resp: dict[str, Any] | None
) -> AssignmentItemResponse:
    """Firestore autosave, as Postgres: the first save inserts the (submission, item) row (a
    concurrent first save of the same item gets 409 ``conflict`` from ``item_response_keys``,
    like the unique-index violation); later saves set the answer in one transaction on the
    fresh row (``FOR UPDATE``: they serialise, the last one wins, nothing else is overwritten)."""
    now = utcnow()
    row = await fsa.response_for(session, sub.id, it.id)
    if row is None:
        row = AssignmentItemResponse(
            id=uuid7(),
            submission_id=sub.id,
            item_id=it.id,
            user_id=sub.user_id,
            organization_id=sub.organization_id,
            response=resp,
            saved_at=now,
        )
        fss.add(session, row)
        # create-only: ``item_response_keys`` rejects a concurrent first save of the same item
        # with the same 409 Postgres gives (both INSERT; the unique index fails the second)
        await fss.flush(session)
        return row
    rid = row.id

    def step(rows: dict[uuid.UUID, AssignmentItemResponse]) -> None:
        cur = rows.get(rid)
        if cur is None:
            raise ProblemError("not_found")
        cur.response = resp
        cur.saved_at = now

    _, rows = await fss.locked(session, AssignmentItemResponse, [rid], step)
    return fss.copy_into(row, rows[rid])


# --------------------------------------------------------------------------- scoring


def engine_for(al: AssignmentAllocation | None, section_id: uuid.UUID) -> str:
    if al is None:
        return "pure_manual"
    return str(al.section_engines.get(str(section_id), "pure_ai"))


def uses_ai(engine: str, it: AssignmentItem, judged: bool) -> bool:
    """Whether the engine asks AI for this item (objective items are always scored by rules;
    file answers are never sent to AI; adaptive prefers the judge for coding)."""
    if engine not in AI_ENGINES or it.item_type in OBJECTIVE_TYPES or it.item_type == "file":
        return False
    return not (engine == "adaptive" and it.item_type == "coding" and judged)


async def judge_of(session: AsyncSession, resp: dict[str, Any] | None) -> Any:
    if not resp or "submission_id" not in resp:
        return None
    from app.modules.coding.public import get_attempt_judgement

    return await get_attempt_judgement(session, uuid.UUID(resp["submission_id"]))


def judged_marks(it: AssignmentItem, j: Any) -> Decimal | None:
    if j is None or j.status != "completed" or j.score is None or not j.max_score:
        return None
    ratio = min(Decimal(1), max(Decimal(0), Decimal(j.score) / Decimal(j.max_score)))
    return (it.marks * ratio).quantize(TWO)


async def rule_marks(
    session: AsyncSession, it: AssignmentItem, bundle: Any, row: AssignmentItemResponse | None, engine: str
) -> Decimal | None:
    """Deterministic marks for an item, or None when a human / AI must decide."""
    resp = row.response if row is not None else None
    if resp is None:
        return Decimal(0)  # unanswered
    if engine == "pure_manual":
        return None
    if it.item_type in OBJECTIVE_TYPES and bundle is not None:
        from app.modules.placement import public as grading

        ok = grading.is_correct(it.item_type, resp, bundle.correct_option_ids, bundle.version.answer_key)
        return it.marks if ok else Decimal(0)
    if it.item_type == "coding" and engine in ("pure_objective", "adaptive"):
        return judged_marks(it, await judge_of(session, resp))
    return None


async def refresh_auto_marks(
    session: AsyncSession, sub: AssignmentSubmission, al: AssignmentAllocation | None
) -> int:
    """(Re)compute deterministic marks for every item of a handed-in submission; creates empty
    response rows for unanswered items so the evaluation view has one row per item."""
    a = await fss.get(session, Assignment, sub.assignment_id)
    assert a is not None
    structure = await load_structure(session, a.id)
    items = [it for _s, its in structure for it in its]
    bundles = await bundles_for(session, items)
    rows = await responses_of(session, sub.id)
    n = 0
    for s, its in structure:
        engine = engine_for(al, s.id)
        for it in its:
            row = rows.get(it.id)
            if row is None:
                row = AssignmentItemResponse(
                    id=uuid7(),
                    submission_id=sub.id,
                    item_id=it.id,
                    user_id=sub.user_id,
                    organization_id=sub.organization_id,
                )
                fss.add(session, row)
            bundle = bundles.get(it.question_version_id) if it.question_version_id else None
            marks = await rule_marks(session, it, bundle, row, engine)
            if marks != row.auto_marks:
                row.auto_marks = marks
                n += 1
    await fss.flush(session)
    return n


def suggested_marks(row: AssignmentItemResponse | None, ai_item: bool) -> Decimal | None:
    if row is None:
        return Decimal(0)
    if row.response is None:
        return Decimal(0)
    if ai_item and row.ai_status in ("pending", "accepted") and row.ai_marks is not None:
        return row.ai_marks
    return row.auto_marks


async def queue_ai(
    session: AsyncSession, subs: list[AssignmentSubmission], allocs: dict[uuid.UUID, AssignmentAllocation]
) -> tuple[int, int]:
    """Refresh rule marks and mark AI-engine items ``queued``; returns (queued, auto_scored)."""
    queued = auto = 0
    for sub in subs:
        al = allocs.get(sub.allocation_id) if sub.allocation_id else None
        auto += await refresh_auto_marks(session, sub, al)
        structure = await load_structure(session, sub.assignment_id)
        rows = await responses_of(session, sub.id)
        for s, its in structure:
            engine = engine_for(al, s.id)
            for it in its:
                row = rows.get(it.id)
                if row is None or row.response is None or row.final_marks is not None:
                    continue
                judged = it.item_type == "coding" and row.auto_marks is not None
                if not uses_ai(engine, it, judged) or row.ai_status in ("queued", "accepted"):
                    continue
                row.ai_status = "queued"
                row.ai_error = None
                queued += 1
    await fss.flush(session)
    return queued, auto


AI_EVENT = "learning.ai_grading_requested"


async def run_queued_ai(
    session: AsyncSession, submission_ids: list[uuid.UUID], requested_by: uuid.UUID
) -> int:
    """Outbox handler body: ask ``ai.grade_response`` for every queued item of the given
    submissions. Results are stored as pending suggestions (never final)."""
    from app.modules.ai import public as ai

    done = 0
    rows: list[Any]
    held: list[tuple[str, str]] = []
    if fss.fs():
        # The Postgres row lock held during the AI calls is a per-response lease: a concurrent
        # handler skips responses another one is grading, and the "still queued" check is made
        # on the row re-read after the lease is taken (each item is sent to AI once).
        queued = []
        for r in await fsa.responses_of(session, submission_ids):
            if r.ai_status != "queued":
                continue
            holder = await fss.lease(f"ai.{r.id}")
            if holder is None:
                continue
            held.append((f"ai.{r.id}", holder))
            _, fresh = await fss.locked(session, AssignmentItemResponse, [r.id], lambda rows: None)
            cur = fresh.get(r.id)
            if cur is not None and cur.ai_status == "queued":
                queued.append(fss.copy_into(r, cur))
        fs_items = await fss.get_many(session, AssignmentItem, {r.item_id for r in queued})
        fs_subs = await fss.get_many(session, AssignmentSubmission, {r.submission_id for r in queued})
        rows = [
            (r, fs_items[r.item_id], fs_subs[r.submission_id])
            for r in queued
            if r.item_id in fs_items and r.submission_id in fs_subs
        ]
    else:
        rows = list(
            (
                await session.execute(
                    select(AssignmentItemResponse, AssignmentItem, AssignmentSubmission)
                    .join(AssignmentItem, AssignmentItem.id == AssignmentItemResponse.item_id)
                    .join(
                        AssignmentSubmission, AssignmentSubmission.id == AssignmentItemResponse.submission_id
                    )
                    .where(
                        AssignmentItemResponse.submission_id.in_(submission_ids),
                        AssignmentItemResponse.ai_status == "queued",
                    )
                    .with_for_update(of=AssignmentItemResponse)
                )
            ).all()
        )
    bundles = await bundles_for(session, [it for _r, it, _s in rows])
    for row, it, _sub in rows:
        resp = row.response or {}
        text = resp.get("text") or resp.get("source_code") or ""
        if not text.strip():
            row.ai_status = "none"
            continue
        try:
            sug = await ai.grade_response(
                session,
                user_id=requested_by,
                purpose="assignment",
                question_md=question_text(it, bundles),
                response_text=text,
                max_marks=it.marks,
                rubric=(it.rubric or {}).get("criteria") if isinstance(it.rubric, dict) else None,
                reference_answer_md=it.reference_answer_md,
            )
        except ai.AIError as e:
            row.ai_status = "failed"
            row.ai_error = e.code
            continue
        row.ai_marks = min(it.marks, max(Decimal(0), Decimal(sug.marks))).quantize(TWO)
        row.ai_feedback_md = sug.feedback_md
        row.ai_confidence = float(sug.confidence)
        row.ai_criteria = list(sug.criteria)
        row.ai_status = "pending"
        row.ai_error = None
        done += 1
    try:
        await fss.flush(session)
    finally:
        for key, holder in held:
            await fss.release(key, holder)
    return done


async def on_ai_grading_requested(session: AsyncSession, msg: Any) -> None:
    ids = [uuid.UUID(x) for x in msg.payload.get("submission_ids", [])]
    by = msg.payload.get("requested_by")
    if ids and by:
        await run_queued_ai(session, ids, uuid.UUID(by))


# --------------------------------------------------------------------------- views


def response_view(
    it: AssignmentItem, row: AssignmentItemResponse | None, engine: str, judge: Any
) -> dict[str, Any]:
    resp = row.response if row is not None else None
    code = None
    if it.item_type == "coding" and resp:
        code = {
            "language_key": resp.get("language_key"),
            "source_code": resp.get("source_code"),
            "submission_id": resp.get("submission_id"),
            "judge": (
                {
                    "status": judge.status,
                    "verdict": judge.verdict,
                    "score": f(judge.score),
                    "max_score": f(judge.max_score),
                    "passed_cases": judge.passed_cases,
                    "total_cases": judge.total_cases,
                }
                if judge is not None
                else None
            ),
        }
    ai_item = uses_ai(engine, it, row is not None and row.auto_marks is not None and it.item_type == "coding")
    ai = None
    if row is not None and row.ai_status != "none":
        ai = {
            "status": row.ai_status,
            "marks": f(row.ai_marks),
            "feedback_md": row.ai_feedback_md,
            "confidence": row.ai_confidence,
            "criteria": row.ai_criteria,
            "error": row.ai_error,
        }
    sug = suggested_marks(row, ai_item)
    source: str | None = row.grade_source if row is not None else None
    return {
        "response": resp,
        "code": code,
        "auto_marks": f(row.auto_marks) if row is not None else None,
        "ai": ai,
        "suggested_marks": f(sug),
        "suggested_source": (
            "ai"
            if ai_item
            and row is not None
            and row.ai_status in ("pending", "accepted")
            and row.ai_marks is not None
            else ("auto" if sug is not None else None)
        ),
        "final_marks": f(row.final_marks) if row is not None else None,
        "final_feedback_md": row.final_feedback_md if row is not None else None,
        "source": source,
        "needs_review": bool(
            row is not None
            and row.final_marks is None
            and ai_item
            and row.ai_status == "pending"
            and (engine == "ai_human" or (engine == "adaptive" and (row.ai_confidence or 0) < LOW_CONFIDENCE))
        ),
    }


def regrade_out(r: AssignmentRegradeRequest, learner_name: str | None = None) -> dict[str, Any]:
    return {
        "id": str(r.id),
        "submission_id": str(r.submission_id),
        "assignment_id": str(r.assignment_id),
        "user_id": str(r.user_id),
        "learner_name": learner_name,
        "item_id": str(r.item_id) if r.item_id else None,
        "reason": r.reason,
        "status": r.status,
        "resolution_note": r.resolution_note,
        "resolved_at": iso(r.resolved_at),
        "created_at": iso(r.created_at),
    }


async def learner_names(session: AsyncSession, user_ids: set[uuid.UUID]) -> dict[uuid.UUID, str | None]:
    """Display names from ``user_profiles`` (identity table; isolated here until identity
    exposes a store-neutral lookup — see the data-learning report)."""
    from app.modules.identity import public as identity_public

    if not user_ids:
        return {}
    profs = await identity_public.get_profiles(session, user_ids)
    return {uid: p.display_name or p.full_name for uid, p in profs.items()}


# --------------------------------------------------------------------------- coding access


async def coding_access_grant(session: AsyncSession, principal: Any, problem_id: uuid.UUID) -> bool:
    """Coding-module access grant (``coding.register_access_grant``, wired in ``app.wiring``):
    a learner may run / submit a coding problem without a standalone entitlement while they
    are working on (started, not yet handed in) a structured assignment that contains it,
    under an active allocation that still targets them (active batch membership, SEC-03) and
    whose window is open now."""
    if fss.fs():
        return await _coding_access_grant_fs(session, principal, problem_id)
    rows = (
        await session.execute(
            select(AssignmentAllocation)
            .join(AssignmentSubmission, AssignmentSubmission.allocation_id == AssignmentAllocation.id)
            .join(Assignment, Assignment.id == AssignmentSubmission.assignment_id)
            .where(
                AssignmentSubmission.user_id == principal.user_id,
                AssignmentSubmission.status == "draft",
                Assignment.submission_type == "structured",
                Assignment.status == "active",
                AssignmentAllocation.status == "active",
                exists(
                    select(AssignmentItem.id).where(
                        AssignmentItem.assignment_id == Assignment.id,
                        AssignmentItem.coding_problem_id == problem_id,
                    )
                ),
            )
        )
    ).scalars()
    allocs = list(rows)
    if not allocs:
        return False
    batches = await active_batch_ids(session, principal.user_id)
    now = utcnow()
    for al in allocs:
        targeted = targets_learner(al, principal.user_id, batches)
        started = al.start_at is None or now >= al.start_at
        if targeted and started and now <= effective_due(al, principal.user_id):
            return True
    return False


async def _coding_access_grant_fs(session: AsyncSession, principal: Any, problem_id: uuid.UUID) -> bool:
    drafts = await fss.find(
        session,
        AssignmentSubmission,
        filters=(("user_id", "==", principal.user_id), ("status", "==", "draft")),
        where=lambda s: s.allocation_id is not None,
    )
    if not drafts:
        return False
    assignments = await fss.get_many(session, Assignment, {s.assignment_id for s in drafts})
    allocs = await fss.get_many(session, AssignmentAllocation, {s.allocation_id for s in drafts})
    with_problem = {
        it.assignment_id
        for it in await fss.find(session, AssignmentItem, filters=(("coding_problem_id", "==", problem_id),))
    }
    cands = []
    for s in drafts:
        a = assignments.get(s.assignment_id)
        al = allocs.get(s.allocation_id) if s.allocation_id else None
        if (
            a is not None
            and al is not None
            and a.submission_type == "structured"
            and a.status == "active"
            and al.status == "active"
            and a.id in with_problem
        ):
            cands.append(al)
    if not cands:
        return False
    batches = await active_batch_ids(session, principal.user_id)
    now = utcnow()
    for al in cands:
        targeted = targets_learner(al, principal.user_id, batches)
        started = al.start_at is None or now >= al.start_at
        if targeted and started and now <= effective_due(al, principal.user_id):
            return True
    return False
