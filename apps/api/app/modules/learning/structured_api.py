"""HTTP endpoints for structured assignments (WISEMAN-FEATURES "assign"; service in
``structured``). Included by ``learning.router``.

Staff (RBAC on the assignment's scope — owning batch / course, or platform for company-wide
structured assignments). Grading is narrower than the assignment (SEC-02): a caller without
``assignment.grade`` on the assignment's own scope may grade only the allocations
(a) to a batch where they hold ``assignment.grade``, or (b) that list them in
``evaluator_ids`` while they hold ``assignment.grade`` somewhere (an evaluator / trainer).
Everything they read or change is filtered to those allocations.

* ``assignment.manage``: structure (sections/items), clone, allocations.
* ``assignment.grade``: evaluation list, AI grading runs, review, finalize, extensions,
  regrade queue. Publishing reuses LRN-18 ``release-grades``.

Learner (own rows, RLS family U): workspace start / autosave / submit, AI tutor, results,
regrade ("Request modification") requests. Schedule windows are enforced here, server-side.

Store: with ``TD_STORE_LEARNING=firestore`` the learning rows go through ``fs_store`` /
``fs_assign`` (Firestore branches below; Postgres statements unchanged). Learner reads that
relied on RLS (own rows) filter on ``user_id`` explicitly there.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.core.audit import audit
from app.core.auth import ScopeRef, require_active_principal
from app.core.db import PrincipalDbSession, system_context
from app.core.errors import ProblemError, register_unique_conflict
from app.core.idempotency import IdemResult, idempotent
from app.core.ids import uuid7
from app.core.outbox import emit_event, register_handler
from app.core.principal import Principal
from app.core.routing import authenticated_router
from app.core.time import utcnow
from app.modules.ai.public import require_app_enabled
from app.modules.catalog import public as catalog
from app.modules.learning import fs_assign as fsa
from app.modules.learning import fs_store as fss
from app.modules.learning import router as base
from app.modules.learning import structured as st
from app.modules.learning.models import (
    Assignment,
    AssignmentAllocation,
    AssignmentItem,
    AssignmentItemResponse,
    AssignmentRegradeRequest,
    AssignmentSubmission,
)

me = authenticated_router(prefix="/me", tags=["learning"])
me_ro = authenticated_router(prefix="/me", tags=["learning"], route_tag="l3_readonly")
staff = authenticated_router(tags=["learning"])

AI_STATUS = {"ai_disabled": 403, "ai_quota_exceeded": 429, "ai_unavailable": 503}
AI_TITLES = {
    "ai_disabled": "AI help is turned off",
    "ai_quota_exceeded": "AI limit reached",
    "ai_unavailable": "AI is unavailable",
}


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


def ai_problem(code: str, detail: str | None = None) -> ProblemError:
    return ProblemError(code, AI_STATUS.get(code, 503), AI_TITLES.get(code, "AI error"), detail=detail)


# --------------------------------------------------------------------------- permission helpers


# ``None`` = every allocation of the assignment; otherwise the allocation ids the caller grades.
Gradable = frozenset[uuid.UUID] | None


async def _ensure(
    request: Request, session: Any, principal: Principal, assignment_id: uuid.UUID, perm: str
) -> Assignment:
    """``perm`` on the assignment's own scope (managing, and full grading)."""
    scope, _row = await base._assignment_scope(session, principal, assignment_id)
    await catalog.ensure_permission(request, session, principal, perm, scope)
    async with system_context(session, "learning.assignment_scope"):
        a = await fss.get(session, Assignment, assignment_id)
    if a is None:
        raise ProblemError("not_found")
    return a


async def _holds_grade_somewhere(session: Any, principal: Principal) -> bool:
    from app.modules.rbac.public import role_permission_map

    async with system_context(session, "learning.assignment_scope"):
        perms = await role_permission_map(session)
    return any("assignment.grade" in perms.get(g.role, frozenset()) for g in principal.grants)


async def _ensure_grade(
    request: Request, session: Any, principal: Principal, assignment_id: uuid.UUID
) -> tuple[Assignment, Gradable]:
    """SEC-02 + evaluator_ids: the assignment and the set of allocations the caller may grade
    (``None`` = all, when ``assignment.grade`` is held on the assignment's own scope)."""
    scope, _row = await base._assignment_scope(session, principal, assignment_id)
    async with system_context(session, "learning.assignment_scope"):
        a = await fss.get(session, Assignment, assignment_id)
        allocs = await _allocs(session, assignment_id) if a is not None else {}
    if a is None:
        raise ProblemError("not_found")
    # The assignment's own scope covers every allocation only when it is not a batch: a batch-A
    # grant does NOT cover an allocation of this assignment to batch B (allocate() allows that
    # for someone holding both) -- such allocations need the grant on their own batch
    # (RBAC audit 2026-11-13).
    own_batch: uuid.UUID | None = None
    if await base._may(request, principal, "assignment.grade", scope):
        own = (None, scope.scope_id)
        if scope.scope_type != "batch" or all(al.batch_id in own for al in allocs.values()):
            return a, None
        own_batch = scope.scope_id
    grader = None
    ok: set[uuid.UUID] = set()
    batch_ok: dict[uuid.UUID, bool] = {}
    for al in allocs.values():
        if own_batch is not None and al.batch_id in (None, own_batch):
            ok.add(al.id)
            continue
        if al.batch_id is not None:
            if al.batch_id not in batch_ok:
                batch_ok[al.batch_id] = await base._may(
                    request, principal, "assignment.grade", ScopeRef("batch", al.batch_id)
                )
            if batch_ok[al.batch_id]:
                ok.add(al.id)
                continue
        if principal.user_id in al.evaluator_ids:
            if grader is None:
                grader = await _holds_grade_somewhere(session, principal)
            if grader:
                ok.add(al.id)
    if own_batch is not None and len(ok) == len(allocs):
        return a, None
    if not ok:
        raise ProblemError("permission_denied", permission="assignment.grade")
    return a, frozenset(ok)


async def gradable_allocations(
    request: Request, session: Any, principal: Principal, assignment_id: uuid.UUID
) -> Gradable:
    """For the legacy staff routes in ``learning.router``: the allocations of a structured
    assignment the caller may grade (``None`` = all)."""
    return (await _ensure_grade(request, session, principal, assignment_id))[1]


def _in_gradable(gradable: Gradable, allocation_id: uuid.UUID | None) -> bool:
    return gradable is None or (allocation_id is not None and allocation_id in gradable)


def _require_structured(a: Assignment) -> None:
    if a.submission_type != "structured":
        raise ProblemError("not_found", detail="Not a structured assignment.")


async def _sub_for_staff(
    request: Request, session: Any, principal: Principal, submission_id: uuid.UUID
) -> tuple[AssignmentSubmission, Assignment]:
    row: Any
    if fss.fs():
        found = await fss.get(session, AssignmentSubmission, submission_id)
        row = (found.assignment_id,) if found is not None else None
    else:
        row = await fss.system_row(
            session,
            principal,
            select(AssignmentSubmission.assignment_id).where(AssignmentSubmission.id == submission_id),
        )
    if row is None:
        raise ProblemError("not_found")
    a, gradable = await _ensure_grade(request, session, principal, row[0])
    _require_structured(a)
    async with system_context(session, "learning.assignment_scope"):
        sub = await fss.get(session, AssignmentSubmission, submission_id)
    if sub is None:
        raise ProblemError("not_found")
    if not _in_gradable(gradable, sub.allocation_id):
        raise ProblemError("permission_denied", permission="assignment.grade")
    return sub, a


async def _allocs(session: Any, assignment_id: uuid.UUID) -> dict[uuid.UUID, AssignmentAllocation]:
    if fss.fs():
        return {al.id: al for al in await fsa.allocations_of(session, assignment_id)}
    rows = (
        await session.execute(
            select(AssignmentAllocation).where(AssignmentAllocation.assignment_id == assignment_id)
        )
    ).scalars()
    return {al.id: al for al in rows}


# =========================================================================== staff: structure


class ItemIn(Strict):
    source: Literal["bank", "inline"]
    marks: Decimal = Field(ge=0, le=10000)
    question_id: uuid.UUID | None = None
    question_version_id: uuid.UUID | None = None
    item_type: Literal["essay", "short_text", "file", "coding"] | None = None
    prompt_md: str | None = Field(default=None, min_length=1, max_length=50_000)
    coding_problem_id: uuid.UUID | None = None
    rubric: base.Rubric | None = None
    reference_answer_md: str | None = Field(default=None, max_length=50_000)


class SectionIn(Strict):
    title: str = Field(min_length=1, max_length=200)
    max_score: Decimal | None = Field(default=None, gt=0, le=10000)
    items: list[ItemIn] = Field(default_factory=list, max_length=200)


class StructureIn(Strict):
    sections: list[SectionIn] = Field(max_length=20)


def _specs(body: StructureIn) -> list[st.SectionSpec]:
    out = []
    n = 0
    for i, sec in enumerate(body.sections):
        items = []
        for j, it in enumerate(sec.items):
            n += 1
            f = f"sections.{i}.items.{j}"
            if it.source == "bank":
                if it.question_id is None:
                    raise st._vf(f"{f}.question_id", "required", "Pick a question from a bank")
                if it.prompt_md or it.item_type:
                    raise st._vf(
                        f"{f}.source", "invalid", "Bank items take only question_id / version / marks"
                    )
            elif not it.prompt_md:
                raise st._vf(f"{f}.prompt_md", "required", "Write the question")
            rubric = None
            if it.rubric is not None:
                rubric = base._check_rubric(it.rubric, it.marks if it.marks > 0 else Decimal("10000"))
            items.append(
                st.ItemSpec(
                    source=it.source,
                    marks=it.marks,
                    question_id=it.question_id,
                    question_version_id=it.question_version_id,
                    item_type=it.item_type,
                    prompt_md=it.prompt_md,
                    coding_problem_id=it.coding_problem_id,
                    rubric=rubric,
                    reference_answer_md=it.reference_answer_md,
                )
            )
        out.append(st.SectionSpec(title=sec.title, max_score=sec.max_score, items=items))
    if n > 200:
        raise st._vf("sections", "too_many", "At most 200 questions per assignment")
    return out


async def _structure_out(session: Any, a: Assignment) -> dict[str, Any]:
    structure = await st.load_structure(session, a.id)
    items = [it for _s, its in structure for it in its]
    bundles = await st.bundles_for(session, items)
    allocs = list((await _allocs(session, a.id)).values())
    names: dict[uuid.UUID, str] = {}
    bids = [al.batch_id for al in allocs if al.batch_id]
    if bids:
        from app.modules.orgs import public as orgs_public

        names = await orgs_public.batch_names(session, bids)
    return {
        "assignment": base._assignment_out(a, utcnow()),
        "locked": await st.is_locked(session, a.id),
        "sections": [
            {
                "id": str(s.id),
                "title": s.title,
                "position": s.position,
                "max_score": st.f(s.max_score),
                "marks_total": float(sum((it.marks for it in its), Decimal(0))),
                "items": [st.item_content(it, bundles, staff=True) for it in its],
            }
            for s, its in structure
        ],
        "marks": st.marks_check(a, structure),
        "allocations": [
            st.allocation_out(al, names.get(al.batch_id) if al.batch_id else None)
            for al in sorted(allocs, key=lambda x: x.created_at)
        ],
    }


@staff.get(
    "/assignments/{assignment_id}/structure",
    operation_id="lrn_30_assignment_structure",
    openapi_extra={"x-td-idle": "neutral"},
)
async def get_structure(
    request: Request,
    assignment_id: uuid.UUID,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
) -> dict[str, Any]:
    a = await _ensure(request, session, principal, assignment_id, "assignment.manage")
    _require_structured(a)
    return await _structure_out(session, a)


@staff.put("/assignments/{assignment_id}/structure", operation_id="lrn_31_put_assignment_structure")
async def put_structure(
    request: Request,
    assignment_id: uuid.UUID,
    body: StructureIn,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
) -> dict[str, Any]:
    a = await _ensure(request, session, principal, assignment_id, "assignment.manage")
    _require_structured(a)
    await st.put_structure(session, a, _specs(body))
    out = await _structure_out(session, a)
    await audit(
        session,
        principal,
        "assignment.structure_update",
        "assignment",
        a.id,
        organization_id=a.organization_id,
        after={
            "sections": len(out["sections"]),
            "items": sum(len(s["items"]) for s in out["sections"]),
            "marks": out["marks"]["allocated"],
        },
    )
    return out


@staff.post("/assignments/{assignment_id}/clone", status_code=201, operation_id="lrn_32_clone_assignment")
async def clone_assignment(
    request: Request,
    assignment_id: uuid.UUID,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
) -> Any:
    src = await _ensure(request, session, principal, assignment_id, "assignment.manage")

    async def op() -> IdemResult:
        a = Assignment(
            id=uuid7(),
            organization_id=src.organization_id,
            course_id=src.course_id,
            batch_id=src.batch_id,
            lesson_id=None,
            title=f"{src.title} (copy)"[:200],
            instructions_md=src.instructions_md,
            submission_type=src.submission_type,
            max_score=src.max_score,
            rubric=src.rubric,
            allowed_file_types=list(src.allowed_file_types),
            available_from=src.available_from,
            due_at=src.due_at,
            late_until=src.late_until,
            late_penalty_pct=src.late_penalty_pct,
            max_attempts=src.max_attempts,
            ai_help_enabled=src.ai_help_enabled,
            ai_help_limit=src.ai_help_limit,
            created_by=principal.user_id,
        )
        fss.add(session, a)
        await fss.flush(session)
        await st.clone_structure(session, src, a)
        await audit(
            session,
            principal,
            "assignment.clone",
            "assignment",
            a.id,
            organization_id=a.organization_id,
            after={"source_assignment_id": src.id},
        )
        return IdemResult(base._assignment_out(a, utcnow()), 201, a.id)

    return await idempotent(request, session, user_id=principal.user_id, operation=op, required=False)


# =========================================================================== staff: allocations


Engine = Literal["pure_ai", "ai_human", "pure_objective", "adaptive", "pure_manual"]


class AllocationIn(Strict):
    batch_id: uuid.UUID | None = None
    user_ids: list[uuid.UUID] = Field(default_factory=list, max_length=500)
    visible_from: datetime | None = None
    visible_until: datetime | None = None
    start_at: datetime | None = None
    due_at: datetime
    section_engines: dict[str, Engine] = Field(default_factory=dict)
    evaluator_ids: list[uuid.UUID] = Field(default_factory=list, max_length=50)


class AllocationPatch(Strict):
    visible_from: datetime | None = None
    visible_until: datetime | None = None
    start_at: datetime | None = None
    due_at: datetime | None = None
    section_engines: dict[str, Engine] | None = None
    evaluator_ids: list[uuid.UUID] | None = Field(default=None, max_length=50)
    status: Literal["revoked"] | None = None


async def _managed_batches(request: Request, principal: Principal) -> set[uuid.UUID]:
    """Batches where the caller holds ``assignment.manage`` through a batch-scoped grant."""
    out: set[uuid.UUID] = set()
    for g in principal.grants:
        if g.scope_type == "batch" and g.scope_id is not None and g.scope_id not in out:
            if await base._may(request, principal, "assignment.manage", ScopeRef("batch", g.scope_id)):
                out.add(g.scope_id)
    return out


async def _check_people(
    request: Request, session: Any, principal: Principal, org: uuid.UUID, ids: list[uuid.UUID], field: str
) -> None:
    """Individual learners must be active members of a batch where the caller holds
    ``assignment.manage`` (a company-wide grant keeps the whole org). Unknown and out-of-scope
    ids get the same error, so the response never tells whether an id exists."""
    if not ids:
        return
    company = await base._may(request, principal, "assignment.manage", ScopeRef("organization", org))
    if company:
        found = await st.org_members(session, org, ids)
    else:
        batches = await _managed_batches(request, principal)
        async with system_context(session, "learning.allocation_people"):
            found = await st.org_members(session, org, ids, batch_ids=batches)
    for i, u in enumerate(ids):
        if u not in found:
            raise st._vf(f"{field}.{i}", "not_member", "Not an active learner or staff member of a batch")


async def _check_evaluators(session: Any, principal: Principal, ids: list[uuid.UUID]) -> None:
    """evaluator_ids must be graders (a live grant of a role holding ``assignment.grade``)."""
    async with system_context(session, "learning.evaluators"):
        found = await st.graders(session, ids)
    for i, u in enumerate(ids):
        if u not in found:
            raise st._vf(f"evaluator_ids.{i}", "not_evaluator", "Not an evaluator or trainer")


@staff.post(
    "/assignments/{assignment_id}/allocations", status_code=201, operation_id="lrn_33_allocate_assignment"
)
async def allocate(
    request: Request,
    assignment_id: uuid.UUID,
    body: AllocationIn,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
) -> Any:
    from app.modules.orgs import public as orgs_public

    a = await _ensure(request, session, principal, assignment_id, "assignment.manage")
    _require_structured(a)
    if a.organization_id is None:
        raise st._vf("assignment_id", "no_organization", "Only organization assignments can be allocated")
    await require_app_enabled(session, app_key="assignments")
    if (body.batch_id is None) == (not body.user_ids):
        raise st._vf("batch_id", "required", "Choose a batch or a list of learners (one of them)")
    batch_name = None
    if body.batch_id is not None:
        await catalog.ensure_permission(
            request, session, principal, "assignment.manage", ScopeRef("batch", body.batch_id)
        )
        batch = await orgs_public.get_batch(session, body.batch_id)
        if batch is None or batch.organization_id != a.organization_id:
            raise ProblemError("not_found")
        batch_name = batch.name
    structure = await st.load_structure(session, a.id)
    mc = st.marks_check(a, structure)
    if not mc["ok"]:
        raise ProblemError("validation_failed", 422, errors=mc["issues"])
    engines = st.check_engines(dict(body.section_engines), [s.id for s, _ in structure])
    st.check_schedule(body.visible_from, body.visible_until, body.start_at, body.due_at)
    users = list(dict.fromkeys(body.user_ids))
    evaluators = list(dict.fromkeys(body.evaluator_ids))
    await _check_people(request, session, principal, a.organization_id, users, "user_ids")
    await _check_evaluators(session, principal, evaluators)

    async def op() -> IdemResult:
        al = AssignmentAllocation(
            id=uuid7(),
            assignment_id=a.id,
            organization_id=a.organization_id,
            batch_id=body.batch_id,
            user_ids=users,
            visible_from=body.visible_from,
            visible_until=body.visible_until,
            start_at=body.start_at,
            due_at=body.due_at,
            section_engines=engines,
            evaluator_ids=evaluators,
            extensions={},
            created_by=principal.user_id,
        )
        fss.add(session, al)
        await fss.flush(session)
        await fss.refresh(session, al)
        await audit(
            session,
            principal,
            "assignment.allocate",
            "assignment_allocation",
            al.id,
            organization_id=a.organization_id,
            after={
                "assignment_id": a.id,
                "batch_id": body.batch_id,
                "learners": len(users),
                "due_at": body.due_at,
                "section_engines": engines,
                "evaluators": len(evaluators),
            },
        )
        await emit_event(
            session,
            "learning.assignment_allocated",
            {
                "assignment_id": str(a.id),
                "allocation_id": str(al.id),
                "batch_id": str(body.batch_id) if body.batch_id else None,
                "user_ids": [str(u) for u in users],
            },
            aggregate_type="assignment",
            aggregate_id=a.id,
            organization_id=a.organization_id,
        )
        return IdemResult(st.allocation_out(al, batch_name), 201, al.id)

    return await idempotent(request, session, user_id=principal.user_id, operation=op, required=False)


@staff.get(
    "/assignments/{assignment_id}/allocations",
    operation_id="lrn_34_list_allocations",
    openapi_extra={"x-td-idle": "neutral"},
)
async def list_allocations(
    request: Request,
    assignment_id: uuid.UUID,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
) -> dict[str, Any]:
    a, gradable = await _ensure_grade(request, session, principal, assignment_id)
    out = (await _structure_out(session, a))["allocations"]
    return {"data": [al for al in out if _in_gradable(gradable, uuid.UUID(al["id"]))]}


async def _alloc_for_staff(
    request: Request, session: Any, principal: Principal, allocation_id: uuid.UUID, perm: str
) -> tuple[AssignmentAllocation, Assignment]:
    row: Any
    if fss.fs():
        found = await fss.get(session, AssignmentAllocation, allocation_id)
        row = (found.assignment_id,) if found is not None else None
    else:
        row = await fss.system_row(
            session,
            principal,
            select(AssignmentAllocation.assignment_id).where(AssignmentAllocation.id == allocation_id),
        )
    if row is None:
        raise ProblemError("not_found")
    gradable: Gradable = None
    if perm == "assignment.grade":
        a, gradable = await _ensure_grade(request, session, principal, row[0])
    else:
        a = await _ensure(request, session, principal, row[0], perm)
    async with system_context(session, "learning.assignment_scope"):
        al = await fss.get(session, AssignmentAllocation, allocation_id)
    if al is None:
        raise ProblemError("not_found")
    if not _in_gradable(gradable, al.id):
        raise ProblemError("permission_denied", permission=perm)
    if perm == "assignment.manage" and al.batch_id is not None:
        # managing the assignment is not enough: the allocation's own batch must be in scope too
        # (an assignment of batch A can be allocated to batch B by someone holding both).
        await catalog.ensure_permission(request, session, principal, perm, ScopeRef("batch", al.batch_id))
    return al, a


@staff.patch("/assignment-allocations/{allocation_id}", operation_id="lrn_35_patch_allocation")
async def patch_allocation(
    request: Request,
    allocation_id: uuid.UUID,
    body: AllocationPatch,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
) -> dict[str, Any]:
    al, a = await _alloc_for_staff(request, session, principal, allocation_id, "assignment.manage")
    data = body.model_dump(exclude_unset=True)
    before = st.allocation_out(al)
    for k in ("visible_from", "visible_until", "start_at"):
        if k in data:
            setattr(al, k, data[k])
    if data.get("due_at") is not None:
        al.due_at = data["due_at"]
    st.check_schedule(al.visible_from, al.visible_until, al.start_at, al.due_at)
    if data.get("section_engines") is not None:
        structure = await st.load_structure(session, a.id)
        al.section_engines = st.check_engines(
            {**al.section_engines, **data["section_engines"]}, [s.id for s, _ in structure]
        )
    if data.get("evaluator_ids") is not None:
        ev = list(dict.fromkeys(data["evaluator_ids"]))
        await _check_evaluators(session, principal, ev)
        al.evaluator_ids = ev
    if data.get("status") == "revoked":
        al.status = "revoked"
    await fss.flush(session)
    after = st.allocation_out(al)
    await audit(
        session,
        principal,
        "assignment.allocation_update",
        "assignment_allocation",
        al.id,
        organization_id=al.organization_id,
        before={k: before[k] for k in data},
        after={k: after[k] for k in data},
    )
    return after


class ExtensionIn(Strict):
    user_id: uuid.UUID
    until: datetime
    reason: str = Field(min_length=5, max_length=2000)


@staff.post("/assignment-allocations/{allocation_id}/extensions", operation_id="lrn_36_grant_extension")
async def grant_extension(
    request: Request,
    allocation_id: uuid.UUID,
    body: ExtensionIn,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
) -> dict[str, Any]:
    """Late submission for one learner ("evaluators can grant late submission per learner")."""
    al, _a = await _alloc_for_staff(request, session, principal, allocation_id, "assignment.grade")
    if body.user_id == principal.user_id:
        # SEC-12: never extend one's own deadline.
        raise ProblemError("conflict_of_interest", detail="You cannot extend your own deadline.")
    if body.until <= al.due_at or body.until <= utcnow():
        raise st._vf("until", "too_early", "The extension must end after the deadline and in the future")
    async with system_context(session, "learning.assignment_scope"):
        targeted = st.targets_learner(al, body.user_id, await st.active_batch_ids(session, body.user_id))
    if not targeted:
        raise st._vf("user_id", "not_allocated", "This learner is not in this allocation")
    ext = dict(al.extensions)
    before = ext.get(str(body.user_id))
    ext[str(body.user_id)] = st.iso(body.until)
    al.extensions = ext
    await fss.flush(session)
    await audit(
        session,
        principal,
        "assignment.extension_grant",
        "assignment_allocation",
        al.id,
        organization_id=al.organization_id,
        subject_user_id=body.user_id,
        reason=body.reason,
        before={"until": before},
        after={"until": ext[str(body.user_id)]},
    )
    return st.allocation_out(al)


# =========================================================================== staff: evaluation


@staff.get(
    "/assignments/{assignment_id}/evaluation",
    operation_id="lrn_37_assignment_evaluation",
    openapi_extra={"x-td-idle": "neutral"},
)
async def evaluation(
    request: Request,
    assignment_id: uuid.UUID,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
) -> dict[str, Any]:
    a, gradable = await _ensure_grade(request, session, principal, assignment_id)
    _require_structured(a)
    async with system_context(session, "learning.assignment_evaluation"):
        return await _evaluation(session, a, gradable)


async def _evaluation(session: Any, a: Assignment, gradable: Gradable = None) -> dict[str, Any]:
    structure = await st.load_structure(session, a.id)
    item_section = {it.id: (s, it) for s, its in structure for it in its}
    allocs = await _allocs(session, a.id)
    sub_rows: Any
    if fss.fs():
        # ORDER BY submitted_at (ascending, NULLs last), ties by id
        sub_rows = sorted(
            (s for s in await fsa.submissions_of(session, a.id) if s.status != "draft"),
            key=lambda s: (fsa.nulls_last(s.submitted_at), str(s.id)),
        )
    else:
        sub_rows = (
            await session.execute(
                select(AssignmentSubmission)
                .where(AssignmentSubmission.assignment_id == a.id, AssignmentSubmission.status != "draft")
                .order_by(AssignmentSubmission.submitted_at)
            )
        ).scalars()
    subs = [s for s in sub_rows if _in_gradable(gradable, s.allocation_id)]
    responses: dict[uuid.UUID, list[AssignmentItemResponse]] = {s.id: [] for s in subs}
    if subs:
        resp_rows: Any
        if fss.fs():
            resp_rows = await fsa.responses_of(session, [s.id for s in subs])
        else:
            resp_rows = (
                await session.execute(
                    select(AssignmentItemResponse).where(
                        AssignmentItemResponse.submission_id.in_([s.id for s in subs])
                    )
                )
            ).scalars()
        for r in resp_rows:
            responses[r.submission_id].append(r)
    if fss.fs():
        open_regrades = {
            r.submission_id for r in await fsa.regrades_of(session, assignment_id=a.id) if r.status == "open"
        }
    else:
        open_regrades = set(
            (
                await session.execute(
                    select(AssignmentRegradeRequest.submission_id).where(
                        AssignmentRegradeRequest.assignment_id == a.id,
                        AssignmentRegradeRequest.status == "open",
                    )
                )
            ).scalars()
        )
    names = await st.learner_names(session, {s.user_id for s in subs})
    sec_sum: dict[uuid.UUID, Decimal] = {s.id: Decimal(0) for s, _ in structure}
    finalized_n = 0
    rows = []
    for sub in subs:
        al = allocs.get(sub.allocation_id) if sub.allocation_id else None
        finalized = sub.status == "graded"
        fin_marks = Decimal(0)
        ai_pending = ai_queued = needs_review = 0
        for r in responses[sub.id]:
            if r.item_id not in item_section:
                continue
            s, it = item_section[r.item_id]
            if r.final_marks is not None:
                fin_marks += r.final_marks
                if finalized:
                    sec_sum[s.id] += r.final_marks
            if r.ai_status == "pending" and r.final_marks is None:
                ai_pending += 1
            if r.ai_status == "queued":
                ai_queued += 1
            if st.response_view(it, r, st.engine_for(al, s.id), None)["needs_review"]:
                needs_review += 1
        finalized_n += 1 if finalized else 0
        late = sub.status == "late" or bool(
            al is not None and sub.submitted_at is not None and sub.submitted_at > al.due_at
        )
        flags = []
        if late:
            flags.append("late")
        if al is not None and str(sub.user_id) in al.extensions:
            flags.append("extension")
        if sub.id in open_regrades:
            flags.append("regrade_requested")
        if sub.ai_help_used:
            flags.append("ai_help_used")
        rows.append(
            {
                "submission_id": str(sub.id),
                "user_id": str(sub.user_id),
                "learner_name": names.get(sub.user_id),
                "learner_email": None,
                "status": sub.status,
                "submitted_at": st.iso(sub.submitted_at),
                "late": late,
                "finalized": finalized,
                "finalized_marks": float(fin_marks),
                "score": st.f(sub.score),
                "max_score": float(a.max_score),
                "ai_pending": ai_pending,
                "ai_queued": ai_queued,
                "needs_review": needs_review,
                "ai_help_used": sub.ai_help_used,
                "regrade_open": sub.id in open_regrades,
                "flags": flags,
            }
        )
    return {
        "assignment": base._assignment_out(a, utcnow()),
        "submission_count": len(subs),
        "max_score": float(a.max_score),
        "published": a.grades_released_at is not None,
        "sections": [
            {
                "id": str(s.id),
                "title": s.title,
                "max_marks": float(sum((it.marks for it in its), Decimal(0))),
                "avg_marks": float((sec_sum[s.id] / finalized_n).quantize(st.TWO)) if finalized_n else None,
            }
            for s, its in structure
        ],
        "rows": rows,
    }


class AIRunIn(Strict):
    submission_ids: list[uuid.UUID] | None = Field(default=None, max_length=500)


async def _run_ai(
    session: Any, principal: Principal, a: Assignment, subs: list[AssignmentSubmission]
) -> dict[str, Any]:
    from app.modules.ai import public as ai

    allocs = await _allocs(session, a.id)
    used = {
        e
        for sub in subs
        if sub.allocation_id in allocs
        for e in allocs[sub.allocation_id].section_engines.values()
    }
    if used & st.AI_ENGINES:
        try:
            enabled = await ai.ai_enabled(session, app_key="ai_grading")
        except ai.AIError as e:
            raise ai_problem(e.code) from e
        if not enabled:
            raise ai_problem("ai_disabled", "AI grading is turned off.")
    async with system_context(session, "learning.ai_grading_queue"):
        queued, auto = await st.queue_ai(session, subs, allocs)
    if queued:
        await emit_event(
            session,
            st.AI_EVENT,
            {
                "assignment_id": str(a.id),
                "submission_ids": [str(s.id) for s in subs],
                "requested_by": str(principal.user_id),
            },
            aggregate_type="assignment",
            aggregate_id=a.id,
            organization_id=a.organization_id,
        )
    await audit(
        session,
        principal,
        "assignment.ai_grading_run",
        "assignment",
        a.id,
        organization_id=a.organization_id,
        after={"submissions": len(subs), "queued_items": queued, "auto_scored_items": auto},
    )
    return {"queued_items": queued, "auto_scored_items": auto, "submissions": len(subs)}


@staff.post("/assignments/{assignment_id}/ai-grading", status_code=202, operation_id="lrn_38_run_ai_grading")
async def run_ai_grading(
    request: Request,
    assignment_id: uuid.UUID,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
    body: AIRunIn | None = None,
) -> dict[str, Any]:
    a, gradable = await _ensure_grade(request, session, principal, assignment_id)
    _require_structured(a)
    if fss.fs():
        wanted = set(body.submission_ids) if body is not None and body.submission_ids else None
        subs = [
            s
            for s in await fsa.submissions_of(session, a.id)
            if s.status in ("submitted", "late") and (wanted is None or s.id in wanted)
        ]
        subs.sort(key=lambda s: str(s.id))
        subs = [s for s in subs if s.user_id != principal.user_id and _in_gradable(gradable, s.allocation_id)]
        return await _run_ai(session, principal, a, subs)
    q = select(AssignmentSubmission).where(
        AssignmentSubmission.assignment_id == a.id, AssignmentSubmission.status.in_(("submitted", "late"))
    )
    if body is not None and body.submission_ids:
        q = q.where(AssignmentSubmission.id.in_(body.submission_ids))
    async with system_context(session, "learning.assignment_evaluation"):
        subs = list((await session.execute(q)).scalars())
    subs = [s for s in subs if s.user_id != principal.user_id and _in_gradable(gradable, s.allocation_id)]
    return await _run_ai(session, principal, a, subs)


@staff.post(
    "/assignment-submissions/{submission_id}/ai-grading",
    status_code=202,
    operation_id="lrn_39_run_ai_grading_one",
)
async def run_ai_grading_one(
    request: Request,
    submission_id: uuid.UUID,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
) -> dict[str, Any]:
    sub, a = await _sub_for_staff(request, session, principal, submission_id)
    if sub.status not in ("submitted", "late"):
        raise ProblemError("invalid_state_transition", detail="Only handed-in, unfinalized work is graded.")
    if sub.user_id == principal.user_id:
        raise ProblemError("conflict_of_interest", detail="You cannot grade your own submission.")
    return await _run_ai(session, principal, a, [sub])


async def _review(session: Any, sub: AssignmentSubmission, a: Assignment) -> dict[str, Any]:
    structure = await st.load_structure(session, a.id)
    items = [it for _s, its in structure for it in its]
    bundles = await st.bundles_for(session, items)
    rows = await st.responses_of(session, sub.id)
    al = await fss.get(session, AssignmentAllocation, sub.allocation_id) if sub.allocation_id else None
    names = await st.learner_names(session, {sub.user_id})
    sections = []
    final_total = Decimal(0)
    sug_total = Decimal(0)
    all_final = True
    for s, its in structure:
        engine = st.engine_for(al, s.id)
        out_items = []
        for it in its:
            row = rows.get(it.id)
            judge = (
                await st.judge_of(session, row.response if row else None)
                if it.item_type == "coding"
                else None
            )
            view = st.response_view(it, row, engine, judge)
            d = st.item_content(it, bundles, staff=True)
            d.update(view)
            out_items.append(d)
            if view["final_marks"] is None:
                all_final = False
            else:
                final_total += Decimal(str(view["final_marks"]))
            if view["suggested_marks"] is not None:
                sug_total += Decimal(str(view["suggested_marks"]))
        sections.append({"id": str(s.id), "title": s.title, "engine": engine, "items": out_items})
    return {
        "submission": base._submission_out(sub, show_grade=True),
        "learner": {"user_id": str(sub.user_id), "name": names.get(sub.user_id), "email": None},
        "allocation_id": str(al.id) if al else None,
        "sections": sections,
        "totals": {
            "final": float(final_total) if all_final and items else None,
            "suggested": float(sug_total),
            "max": float(a.max_score),
        },
    }


@staff.get(
    "/assignment-submissions/{submission_id}/review",
    operation_id="lrn_40_review_submission",
    openapi_extra={"x-td-idle": "neutral"},
)
async def review_submission(
    request: Request,
    submission_id: uuid.UUID,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
) -> dict[str, Any]:
    sub, a = await _sub_for_staff(request, session, principal, submission_id)
    async with system_context(session, "learning.assignment_review"):
        return await _review(session, sub, a)


class FinalItemIn(Strict):
    item_id: uuid.UUID
    marks: Decimal | None = Field(default=None, ge=0, le=10000)
    feedback_md: str | None = Field(default=None, max_length=20_000)
    override_reason: str | None = Field(default=None, max_length=2000)


class FinalizeIn(Strict):
    items: list[FinalItemIn] = Field(default_factory=list, max_length=200)
    feedback_md: str | None = Field(default=None, max_length=20_000)


@staff.post("/assignment-submissions/{submission_id}/finalize", operation_id="lrn_41_finalize_submission")
async def finalize(
    request: Request,
    submission_id: uuid.UUID,
    body: FinalizeIn,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
) -> Any:
    sub, a = await _sub_for_staff(request, session, principal, submission_id)

    async def op() -> IdemResult:
        if sub.user_id == principal.user_id:
            raise ProblemError("conflict_of_interest", detail="You cannot grade your own submission.")
        if sub.status == "draft":
            raise ProblemError("invalid_state_transition", detail="The learner has not handed this in yet.")
        if sub.status == "graded" and a.grades_released_at is not None:
            raise ProblemError(
                "invalid_state_transition",
                detail="Results are published; reopen through a modification request or use grade-override.",
            )
        async with system_context(session, "learning.assignment_finalize"):
            out = await _finalize(session, principal, sub, a, body)
        return IdemResult(out)

    return await idempotent(request, session, user_id=principal.user_id, operation=op, required=False)


async def _finalize(
    session: Any, principal: Principal, sub: AssignmentSubmission, a: Assignment, body: FinalizeIn
) -> dict[str, Any]:
    al = await fss.get(session, AssignmentAllocation, sub.allocation_id) if sub.allocation_id else None
    await st.refresh_auto_marks(session, sub, al)
    structure = await st.load_structure(session, a.id)
    rows = await st.responses_of(session, sub.id)
    given = {g.item_id: (i, g) for i, g in enumerate(body.items)}
    known = {it.id for _s, its in structure for it in its}
    for i, gi in enumerate(body.items):
        if gi.item_id not in known:
            raise st._vf(f"items.{i}.item_id", "unknown", "Not a question of this assignment")
    now = utcnow()
    total = Decimal(0)
    overrides: list[dict[str, Any]] = []
    for s, its in structure:
        engine = st.engine_for(al, s.id)
        for it in its:
            row = rows[it.id]
            judged = it.item_type == "coding" and row.auto_marks is not None
            ai_item = st.uses_ai(engine, it, judged)
            sug = st.suggested_marks(row, ai_item)
            sug_source = (
                "ai"
                if ai_item and row.ai_status in ("pending", "accepted") and row.ai_marks is not None
                else "auto"
            )
            pair = given.get(it.id)
            idx: int | None = pair[0] if pair else None
            g: FinalItemIn | None = pair[1] if pair else None
            field = f"items.{idx}" if idx is not None else "items"
            marks = g.marks if g is not None and g.marks is not None else sug
            if marks is None:
                raise st._vf(f"{field}.marks", "required", f"{s.title} question {it.position} needs marks")
            if marks > it.marks:
                raise st._vf(f"{field}.marks", "too_high", f"Out of {it.marks:g}")
            overridden = g is not None and g.marks is not None and sug is not None and g.marks != sug
            if overridden:
                assert g is not None
                if not g.override_reason or len(g.override_reason.strip()) < 5:
                    raise st._vf(
                        f"{field}.override_reason", "required", "Say why you changed the suggested marks"
                    )
                overrides.append(
                    {
                        "item_id": str(it.id),
                        "from": float(sug or 0),
                        "to": float(marks),
                        "reason": g.override_reason,
                    }
                )
            human = g is not None and g.marks is not None and (sug is None or overridden)
            row.final_marks = marks.quantize(st.TWO)
            row.grade_source = "human" if human else sug_source
            if g is not None and g.feedback_md is not None:
                row.final_feedback_md = g.feedback_md
            elif row.grade_source == "ai" and row.final_feedback_md is None:
                row.final_feedback_md = row.ai_feedback_md
            if ai_item and row.ai_status == "pending":
                row.ai_status = "accepted"
            row.graded_by = principal.user_id
            row.graded_at = now
            total += row.final_marks
    late = sub.status == "late" or bool(al is not None and sub.submitted_at and sub.submitted_at > al.due_at)
    pct = Decimal(a.late_penalty_pct or 0) if late else Decimal(0)
    sub.status = "graded"
    sub.raw_score = total
    sub.late_penalty_pct = pct if late else None
    sub.score = (total * (Decimal(100) - pct) / Decimal(100)).quantize(st.TWO)
    if body.feedback_md is not None:
        sub.feedback_md = body.feedback_md
    sub.graded_by = principal.user_id
    sub.graded_at = now
    await fss.flush(session)
    for o in overrides:
        await audit(
            session,
            principal,
            "assignment.item_override",
            "assignment_submission",
            sub.id,
            organization_id=a.organization_id,
            subject_user_id=sub.user_id,
            reason=o["reason"],
            before={"item_id": o["item_id"], "marks": o["from"]},
            after={"item_id": o["item_id"], "marks": o["to"]},
        )
    await audit(
        session,
        principal,
        "assignment.finalize",
        "assignment_submission",
        sub.id,
        organization_id=a.organization_id,
        subject_user_id=sub.user_id,
        after={"score": float(sub.score), "raw_score": float(total), "overrides": len(overrides)},
    )
    await emit_event(
        session,
        "learning.submission_graded",
        {
            "submission_id": str(sub.id),
            "assignment_id": str(a.id),
            "user_id": str(sub.user_id),
            "action": "grade",
        },
        aggregate_type="assignment",
        aggregate_id=a.id,
        organization_id=a.organization_id,
    )
    return await _review(session, sub, a)


# --------------------------------------------------------------------------- staff: regrades


@staff.get(
    "/assignments/{assignment_id}/regrade-requests",
    operation_id="lrn_42_regrade_queue",
    openapi_extra={"x-td-idle": "neutral"},
)
async def regrade_queue(
    request: Request,
    assignment_id: uuid.UUID,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
    status: Literal["open", "resolved", "rejected"] | None = None,
    mine: bool = False,
) -> dict[str, Any]:
    a, gradable = await _ensure_grade(request, session, principal, assignment_id)
    if fss.fs():
        return await _regrade_queue_fs(session, principal, a, gradable, status, mine)
    async with system_context(session, "learning.assignment_regrades"):
        q = select(AssignmentRegradeRequest).where(AssignmentRegradeRequest.assignment_id == a.id)
        if gradable is not None:
            q = q.where(
                AssignmentRegradeRequest.submission_id.in_(
                    select(AssignmentSubmission.id).where(AssignmentSubmission.allocation_id.in_(gradable))
                )
            )
        if status:
            q = q.where(AssignmentRegradeRequest.status == status)
        if mine:
            q = (
                q.join(
                    AssignmentSubmission, AssignmentSubmission.id == AssignmentRegradeRequest.submission_id
                )
                .join(AssignmentAllocation, AssignmentAllocation.id == AssignmentSubmission.allocation_id)
                .where(AssignmentAllocation.evaluator_ids.contains([principal.user_id]))
            )
        rows = list((await session.execute(q.order_by(AssignmentRegradeRequest.created_at))).scalars())
        names = await st.learner_names(session, {r.user_id for r in rows})
    return {"data": [st.regrade_out(r, names.get(r.user_id)) for r in rows]}


async def _regrade_queue_fs(
    session: Any, principal: Principal, a: Assignment, gradable: Gradable, status: str | None, mine: bool
) -> dict[str, Any]:
    rows = await fsa.regrades_of(session, assignment_id=a.id)
    if status:
        rows = [r for r in rows if r.status == status]
    if gradable is not None or mine:
        subs = await fss.get_many(session, AssignmentSubmission, {r.submission_id for r in rows})
        if gradable is not None:
            rows = [
                r for r in rows if r.submission_id in subs and subs[r.submission_id].allocation_id in gradable
            ]
        if mine:
            allocs = await _allocs(session, a.id)

            def evaluates(r: AssignmentRegradeRequest) -> bool:
                s = subs.get(r.submission_id)
                al = allocs.get(s.allocation_id) if s is not None and s.allocation_id else None
                return al is not None and principal.user_id in al.evaluator_ids

            rows = [r for r in rows if evaluates(r)]
    rows.sort(key=lambda r: (r.created_at, str(r.id)))
    async with system_context(session, "learning.assignment_regrades"):
        names = await st.learner_names(session, {r.user_id for r in rows})
    return {"data": [st.regrade_out(r, names.get(r.user_id)) for r in rows]}


class ResolveIn(Strict):
    action: Literal["resolve", "reject"]
    note: str = Field(min_length=5, max_length=2000)
    reopen: bool = False


@staff.post("/assignment-regrade-requests/{request_id}/resolve", operation_id="lrn_43_resolve_regrade")
async def resolve_regrade(
    request: Request,
    request_id: uuid.UUID,
    body: ResolveIn,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
) -> dict[str, Any]:
    row: Any
    if fss.fs():
        found = await fss.get(session, AssignmentRegradeRequest, request_id)
        row = (found.assignment_id,) if found is not None else None
    else:
        row = await fss.system_row(
            session,
            principal,
            select(AssignmentRegradeRequest.assignment_id).where(AssignmentRegradeRequest.id == request_id),
        )
    if row is None:
        raise ProblemError("not_found")
    a, gradable = await _ensure_grade(request, session, principal, row[0])
    async with system_context(session, "learning.assignment_regrades"):
        if fss.fs():
            rr = await _resolve_regrade_fs(session, principal, request_id, gradable, body)
            names = await st.learner_names(session, {rr.user_id})
        else:
            pg_rr = await session.get(AssignmentRegradeRequest, request_id, with_for_update=True)
            names = await _resolve_regrade_pg(session, principal, pg_rr, gradable, body)
            assert pg_rr is not None
            rr = pg_rr
    await audit(
        session,
        principal,
        "assignment.regrade_resolve",
        "assignment_regrade_request",
        rr.id,
        organization_id=a.organization_id,
        subject_user_id=rr.user_id,
        reason=body.note,
        after={"status": rr.status, "reopened": body.reopen},
    )
    await emit_event(
        session,
        "learning.regrade_resolved",
        {
            "request_id": str(rr.id),
            "submission_id": str(rr.submission_id),
            "assignment_id": str(a.id),
            "user_id": str(rr.user_id),
            "status": rr.status,
            "reopened": body.reopen,
        },
        aggregate_type="assignment",
        aggregate_id=a.id,
        organization_id=a.organization_id,
    )
    return st.regrade_out(rr, names.get(rr.user_id))


# =========================================================================== learner


async def _learner_ctx(
    session: Any, principal: Principal, assignment_id: uuid.UUID, *, for_results: bool = False
) -> tuple[Assignment, AssignmentSubmission | None, AssignmentAllocation | None]:
    a = await base._eligible_assignment(session, principal, assignment_id)
    if a.submission_type != "structured":
        raise ProblemError("not_found")
    if a.status != "active" and not for_results:
        # SEC-09: an archived assignment accepts no start / autosave / submit / tutor.
        raise ProblemError("invalid_state_transition", detail="This assignment is closed.")
    sub: AssignmentSubmission | None
    if fss.fs():
        mine = await fsa.submissions_of(session, a.id, user_id=principal.user_id)
        sub = max(mine, key=lambda s: (s.attempt_no, str(s.id))) if mine else None
    else:
        sub = (
            await session.execute(
                select(AssignmentSubmission)
                .where(
                    AssignmentSubmission.assignment_id == a.id,
                    AssignmentSubmission.user_id == principal.user_id,
                )
                .order_by(AssignmentSubmission.attempt_no.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
    batches = await base._my_batch_ids(session, principal.user_id)
    al = await st.learner_allocation(session, principal.user_id, batches, a, sub)
    return a, sub, al


async def _ai_help(session: Any, a: Assignment, sub: AssignmentSubmission | None) -> dict[str, Any]:
    """Effective tutor limit: the assignment's own ``ai_help_limit``, capped by the platform
    per-activity default (20, Admin-editable, D10) that ``ai.tutor_reply`` enforces."""
    from app.modules.ai import public as ai_store

    used = sub.ai_help_used if sub else 0
    cap = (await ai_store.system_settings(session)).per_activity_default_cap
    caps = [c for c in (a.ai_help_limit, cap) if c is not None]
    lim = min(caps) if caps else None
    return {
        "enabled": a.ai_help_enabled,
        "limit": lim,
        "used": used,
        "remaining": None if lim is None else max(0, lim - used),
    }


async def _workspace(
    session: Any,
    principal: Principal,
    a: Assignment,
    sub: AssignmentSubmission | None,
    al: AssignmentAllocation | None,
) -> dict[str, Any]:
    now = utcnow()
    structure = await st.load_structure(session, a.id)
    items = [it for _s, its in structure for it in its]
    bundles = await st.bundles_for(session, items) if sub is not None else {}
    rows = await st.responses_of(session, sub.id) if sub is not None else {}
    sections = []
    for s, its in structure:
        out_items = []
        if sub is not None:
            for it in its:
                d = st.item_content(it, bundles, staff=False)
                r = rows.get(it.id)
                d["response"] = r.response if r else None
                d["saved_at"] = st.iso(r.saved_at) if r else None
                out_items.append(d)
        sections.append(
            {
                "id": str(s.id),
                "title": s.title,
                "item_count": len(its),
                "marks": float(sum((it.marks for it in its), Decimal(0))),
                "items": out_items,
            }
        )
    return {
        "assignment": base._assignment_out(a, now),
        "schedule": st.schedule_out(al, principal.user_id, now),
        "submission": (
            {
                "id": str(sub.id),
                "status": sub.status,
                "submitted_at": st.iso(sub.submitted_at),
                "ai_help_used": sub.ai_help_used,
            }
            if sub is not None
            else None
        ),
        "ai_help": await _ai_help(session, a, sub),
        "sections": sections,
    }


def _require_open(al: AssignmentAllocation | None, user_id: uuid.UUID) -> None:
    if al is None or al.status != "active":
        raise ProblemError("invalid_state_transition", detail="This assignment is not open for you.")
    now = utcnow()
    if al.start_at is not None and now < al.start_at:
        raise ProblemError("invalid_state_transition", detail="You can start this assignment later.")
    if now > st.effective_due(al, user_id):
        raise ProblemError("invalid_state_transition", detail="The submission window has closed.")


async def _resolve_regrade_pg(
    session: Any, principal: Principal, rr: Any, gradable: Any, body: Any
) -> dict[uuid.UUID, str | None]:
    if rr is None:
        raise ProblemError("not_found")
    sub = await fss.get(session, AssignmentSubmission, rr.submission_id)
    if sub is None:
        raise ProblemError("not_found")
    if not _in_gradable(gradable, sub.allocation_id):
        raise ProblemError("permission_denied", permission="assignment.grade")
    if rr.status != "open":
        raise ProblemError("invalid_state_transition", detail="This request is already closed.")
    if sub.user_id == principal.user_id:
        raise ProblemError("conflict_of_interest", detail="You cannot review your own request.")
    if body.reopen and body.action != "resolve":
        raise st._vf("reopen", "invalid", "Only a resolved request reopens grading")
    rr.status = "resolved" if body.action == "resolve" else "rejected"
    rr.resolution_note = body.note
    rr.resolved_by = principal.user_id
    rr.resolved_at = utcnow()
    if body.reopen and sub.status == "graded":
        sub.status = "late" if sub.late_penalty_pct is not None else "submitted"
    await fss.flush(session)
    return await st.learner_names(session, {rr.user_id})


async def _resolve_regrade_fs(
    session: Any, principal: Principal, request_id: uuid.UUID, gradable: Any, body: Any
) -> AssignmentRegradeRequest:
    """Firestore: the request and its submission are re-read, checked and changed in ONE
    transaction (the Postgres ``FOR UPDATE`` on the request): two concurrent resolutions cannot
    both pass the ``status == 'open'`` check."""
    first = await fss.get(session, AssignmentRegradeRequest, request_id)
    if first is None:
        raise ProblemError("not_found")
    sub_id = first.submission_id
    now = utcnow()

    def step(rows: dict[type[Any], dict[Any, Any]]) -> None:
        rr = rows[AssignmentRegradeRequest].get(request_id)
        sub = rows[AssignmentSubmission].get(sub_id)
        if rr is None or sub is None:
            raise ProblemError("not_found")
        if not _in_gradable(gradable, sub.allocation_id):
            raise ProblemError("permission_denied", permission="assignment.grade")
        if rr.status != "open":
            raise ProblemError("invalid_state_transition", detail="This request is already closed.")
        if sub.user_id == principal.user_id:
            raise ProblemError("conflict_of_interest", detail="You cannot review your own request.")
        if body.reopen and body.action != "resolve":
            raise st._vf("reopen", "invalid", "Only a resolved request reopens grading")
        rr.status = "resolved" if body.action == "resolve" else "rejected"
        rr.resolution_note = body.note
        rr.resolved_by = principal.user_id
        rr.resolved_at = now
        if body.reopen and sub.status == "graded":
            sub.status = "late" if sub.late_penalty_pct is not None else "submitted"

    _, rows = await fss.locked_multi(
        session, [(AssignmentRegradeRequest, [request_id]), (AssignmentSubmission, [sub_id])], step
    )
    out: AssignmentRegradeRequest = rows[AssignmentRegradeRequest][request_id]
    return out


@me_ro.get("/assignments/{assignment_id}/workspace", operation_id="lrn_44_my_workspace")
async def my_workspace(
    assignment_id: uuid.UUID,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
) -> dict[str, Any]:
    a, sub, al = await _learner_ctx(session, principal, assignment_id, for_results=True)
    return await _workspace(session, principal, a, sub, al)


@me.post("/assignments/{assignment_id}/workspace/start", operation_id="lrn_45_start_workspace")
async def start_workspace(
    request: Request,
    assignment_id: uuid.UUID,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
) -> Any:
    async def op() -> IdemResult:
        a, sub, al = await _learner_ctx(session, principal, assignment_id)
        if sub is None:
            _require_open(al, principal.user_id)
            assert al is not None
            sub = AssignmentSubmission(
                id=uuid7(),
                assignment_id=a.id,
                user_id=principal.user_id,
                organization_id=a.organization_id,
                attempt_no=1,
                status="draft",
                allocation_id=al.id,
                file_s3_keys=[],
            )
            # (assignment, user, attempt) unique: Postgres constraint / Firestore submission_keys
            fss.add(session, sub)
            await fss.flush(session)
            await fss.refresh(session, sub)
        return IdemResult(await _workspace(session, principal, a, sub, al))

    return await idempotent(request, session, user_id=principal.user_id, operation=op, required=False)


class SaveIn(Strict):
    response: dict[str, Any] | None


async def _draft(
    session: Any, principal: Principal, assignment_id: uuid.UUID
) -> tuple[Assignment, AssignmentSubmission, AssignmentAllocation]:
    a, sub, al = await _learner_ctx(session, principal, assignment_id)
    if sub is None:
        raise ProblemError("invalid_state_transition", detail="Start the assignment first.")
    if sub.status != "draft":
        raise ProblemError("invalid_state_transition", detail="This assignment is already submitted.")
    _require_open(al, principal.user_id)
    assert al is not None
    return a, sub, al


@me.put("/assignments/{assignment_id}/workspace/items/{item_id}", operation_id="lrn_46_autosave_item")
async def autosave_item(
    assignment_id: uuid.UUID,
    item_id: uuid.UUID,
    body: SaveIn,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
) -> dict[str, Any]:
    a, sub, _al = await _draft(session, principal, assignment_id)
    it = await fss.get(session, AssignmentItem, item_id)
    if it is None or it.assignment_id != a.id:
        raise ProblemError("not_found")
    bundles = await st.bundles_for(session, [it])
    resp = st.normalise_response(
        it,
        bundles.get(it.question_version_id) if it.question_version_id else None,
        body.response,
        principal.user_id,
        list(a.allowed_file_types),
    )
    if it.item_type == "coding":
        await st.verify_code_submission(session, it, resp, principal.user_id)
    row = await st.upsert_response(session, sub, it, resp)
    return {"item_id": str(it.id), "saved_at": st.iso(row.saved_at), "response": row.response}


@me.post("/assignments/{assignment_id}/workspace/submit", operation_id="lrn_47_submit_workspace")
async def submit_workspace(
    request: Request,
    assignment_id: uuid.UUID,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
) -> Any:
    async def op() -> IdemResult:
        a, sub, al = await _draft(session, principal, assignment_id)
        now = utcnow()
        sub.status = "late" if now > al.due_at else "submitted"
        sub.submitted_at = now
        await fss.flush(session)
        async with system_context(session, "learning.assignment_submit"):
            await st.refresh_auto_marks(session, sub, al)
        await emit_event(
            session,
            "learning.assignment_submitted",
            {
                "submission_id": str(sub.id),
                "assignment_id": str(a.id),
                "user_id": str(principal.user_id),
                "late": sub.status == "late",
            },
            aggregate_type="assignment",
            aggregate_id=a.id,
            organization_id=a.organization_id,
        )
        return IdemResult(base._submission_out(sub, show_grade=False))

    return await idempotent(request, session, user_id=principal.user_id, operation=op, required=True)


class TutorTurn(Strict):
    role: Literal["learner", "tutor"]
    content: str = Field(max_length=8000)


class TutorIn(Strict):
    item_id: uuid.UUID
    mode: Literal["guide", "explain"]
    learner_input: str = Field(default="", max_length=20_000)
    # DEPRECATED, ignored (SEC-17): history is kept on the server; read it from
    # GET /me/assignments/{id}/tutor/history. Still accepted so old clients keep working.
    history: list[TutorTurn] = Field(default_factory=list, max_length=20)


@me.post("/assignments/{assignment_id}/tutor", operation_id="lrn_48_assignment_tutor")
async def tutor(
    assignment_id: uuid.UUID,
    body: TutorIn,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
) -> dict[str, Any]:
    """AI tutor on one item. Per-user rate limit (SEC-05, ``429 rate_limited``) and the
    per-activity cap (assignment ``ai_help_limit``, else the platform default of 20, D10) are
    enforced by ``ai.tutor_reply``; the conversation is stored server-side (SEC-17)."""
    from app.modules.ai import public as ai

    a, sub, _al = await _draft(session, principal, assignment_id)
    if not a.ai_help_enabled:
        raise ai_problem("ai_disabled", "AI help is turned off for this assignment.")
    it = await fss.get(session, AssignmentItem, body.item_id)
    if it is None or it.assignment_id != a.id:
        raise ProblemError("not_found")
    lim = a.ai_help_limit
    if lim is not None and sub.ai_help_used >= lim:
        raise ai_problem("ai_quota_exceeded", "You have used all AI help for this assignment.")
    bundles = await st.bundles_for(session, [it])
    try:
        res = await ai.tutor_reply(
            session,
            user_id=principal.user_id,
            context_type="assignment",
            context_id=a.id,
            item_id=it.id,
            mode=body.mode,
            question_md=st.question_text(it, bundles),
            learner_input=body.learner_input,
            per_learner_limit=lim,
        )
    except ai.AIError as e:
        raise ai_problem(e.code, str(e) or None) from e
    sub.ai_help_used = max(sub.ai_help_used + 1, int(res.get("used") or 0))
    await fss.flush(session)
    eff = res.get("limit", lim)
    return {
        "reply_md": res.get("reply_md", ""),
        "used": sub.ai_help_used,
        "limit": eff,
        "remaining": None if eff is None else max(0, int(eff) - sub.ai_help_used),
    }


@me_ro.get("/assignments/{assignment_id}/tutor/history", operation_id="lrn_48a_assignment_tutor_history")
async def tutor_history(
    assignment_id: uuid.UUID,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
    item_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    """The learner's own tutor conversation for this assignment (optionally one item), oldest
    first: ``{"data": [{"role": "learner"|"tutor", "content", "created_at"}]}`` (SEC-17)."""
    from app.modules.ai import public as ai

    a, _sub, _al = await _learner_ctx(session, principal, assignment_id, for_results=True)
    rows = await ai.tutor_history(
        session, user_id=principal.user_id, context_type="assignment", context_id=a.id, item_id=item_id
    )
    return {"data": rows}


@me_ro.get("/assignments/{assignment_id}/result", operation_id="lrn_49_my_result")
async def my_result(
    assignment_id: uuid.UUID,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
) -> dict[str, Any]:
    a, sub, _al = await _learner_ctx(session, principal, assignment_id, for_results=True)
    published = bool(sub is not None and a.grades_released_at is not None and sub.status == "graded")
    structure = await st.load_structure(session, a.id)
    items_out: list[dict[str, Any]] = []
    regrade = None
    if sub is not None and sub.status != "draft":
        bundles = await st.bundles_for(session, [it for _s, its in structure for it in its])
        rows = await st.responses_of(session, sub.id)
        for s, its in structure:
            for it in its:
                r = rows.get(it.id)
                d = st.item_content(it, bundles, staff=False)
                d.update(
                    {
                        "section_id": str(s.id),
                        "section_title": s.title,
                        "response": r.response if r else None,
                        "final_marks": st.f(r.final_marks) if published and r else None,
                        "feedback_md": r.final_feedback_md if published and r else None,
                    }
                )
                items_out.append(d)
        rr: AssignmentRegradeRequest | None
        if fss.fs():
            reqs = await fsa.regrades_of(session, submission_id=sub.id)
            rr = max(reqs, key=lambda r: (r.created_at, str(r.id))) if reqs else None
        else:
            rr = (
                await session.execute(
                    select(AssignmentRegradeRequest)
                    .where(AssignmentRegradeRequest.submission_id == sub.id)
                    .order_by(AssignmentRegradeRequest.created_at.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
        regrade = st.regrade_out(rr) if rr else None
    return {
        "assignment": base._assignment_out(a, utcnow()),
        "published": published,
        "submission": (
            {
                "id": str(sub.id),
                "status": sub.status,
                "submitted_at": st.iso(sub.submitted_at),
                "score": st.f(sub.score) if published else None,
                "max_score": float(a.max_score),
                "feedback_md": sub.feedback_md if published else None,
            }
            if sub is not None and sub.status != "draft"
            else None
        ),
        "items": items_out,
        "regrade": regrade,
    }


class RegradeIn(Strict):
    reason: str = Field(min_length=10, max_length=2000)
    item_id: uuid.UUID | None = None


@me.post(
    "/assignment-submissions/{submission_id}/regrade-requests",
    status_code=201,
    operation_id="lrn_50_request_regrade",
)
async def request_regrade(
    request: Request,
    submission_id: uuid.UUID,
    body: RegradeIn,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
) -> Any:
    async def op() -> IdemResult:
        sub = await fss.get(session, AssignmentSubmission, submission_id)
        if sub is None or sub.user_id != principal.user_id:
            raise ProblemError("not_found")
        a = await fss.get(session, Assignment, sub.assignment_id)
        if a is None or a.submission_type != "structured":
            raise ProblemError("not_found")
        if a.grades_released_at is None or sub.status != "graded":
            raise ProblemError(
                "invalid_state_transition", detail="You can ask for changes once results are out."
            )
        if body.item_id is not None:
            it = await fss.get(session, AssignmentItem, body.item_id)
            if it is None or it.assignment_id != a.id:
                raise st._vf("item_id", "unknown", "Not a question of this assignment")
        open_: Any
        if fss.fs():
            open_ = next(
                (r for r in await fsa.regrades_of(session, submission_id=sub.id) if r.status == "open"), None
            )
        else:
            open_ = (
                await session.execute(
                    select(AssignmentRegradeRequest.id).where(
                        AssignmentRegradeRequest.submission_id == sub.id,
                        AssignmentRegradeRequest.status == "open",
                    )
                )
            ).first()
        if open_ is not None:
            raise ProblemError("conflict", detail="You already have an open request for this submission.")
        rr = AssignmentRegradeRequest(
            id=uuid7(),
            submission_id=sub.id,
            assignment_id=a.id,
            user_id=principal.user_id,
            organization_id=sub.organization_id,
            item_id=body.item_id,
            reason=body.reason,
            status="open",
        )
        # one open request per submission: ux_arr_one_open / Firestore regrade_open key -> 409
        fss.add(session, rr)
        await fss.flush(session)
        await fss.refresh(session, rr)
        await audit(
            session,
            principal,
            "assignment.regrade_request",
            "assignment_regrade_request",
            rr.id,
            organization_id=a.organization_id,
            subject_user_id=principal.user_id,
            after={"submission_id": sub.id, "item_id": body.item_id},
        )
        await emit_event(
            session,
            "learning.regrade_requested",
            {
                "request_id": str(rr.id),
                "submission_id": str(sub.id),
                "assignment_id": str(a.id),
                "user_id": str(principal.user_id),
            },
            aggregate_type="assignment",
            aggregate_id=a.id,
            organization_id=a.organization_id,
        )
        return IdemResult(st.regrade_out(rr), 201, rr.id)

    return await idempotent(request, session, user_id=principal.user_id, operation=op, required=False)


# --------------------------------------------------------------------------- registration

register_handler(st.AI_EVENT, st.on_ai_grading_requested)
register_unique_conflict(
    "ux_arr_one_open", "conflict", "You already have an open request for this submission."
)

router = APIRouter()
for _r in (me, me_ro, staff):
    router.include_router(_r)
