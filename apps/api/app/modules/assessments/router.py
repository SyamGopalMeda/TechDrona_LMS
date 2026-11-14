"""Assessments API (api-specification §14 ASM-01..16, 21 and §15 ATT-01..13).

Attempt routes return 4xx problems *without* raising out of the request transaction
(``_commit_problem``), so that writes made while deciding them — lazy auto-submit at the
deadline, ``rebind_refused`` / ``reattach_same_device`` events — are committed.

ASM-18 invalidate, ASM-19/20 integrity review and ASM-22 report live in ``integrity.py`` /
``report.py``. §15.2 per-endpoint rate limits: ``ratelimit.py``. Not implemented: ASM-17
regrade, ASM-23 leaderboard.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy import literal, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.access import check_access
from app.core.audit import audit
from app.core.auth import require_active_principal, require_step_up
from app.core.errors import ProblemError, problem_response
from app.core.firestore.sqlstore import StorePrincipalDbSession as PrincipalDbSession
from app.core.idempotency import HEADER as IDEM_HEADER
from app.core.idempotency import IdemResult, idempotent
from app.core.pagination import MAX_LIMIT, decode_cursor, page_meta
from app.core.principal import Principal
from app.core.request_context import get_request_id
from app.core.routing import authenticated_router
from app.core.time import to_rfc3339, utcnow
from app.modules.ai.service import require_app_enabled
from app.modules.assessments import attempts as svc
from app.modules.assessments import datastore as adb
from app.modules.assessments import evaluation, exam, integrity, report, studio
from app.modules.assessments import privacy as _privacy  # noqa: F401  (registers the erasure provider)
from app.modules.assessments import ratelimit as rl
from app.modules.assessments.models import Test, TestAssignment, TestAttempt
from app.modules.assessments.schemas import (
    AiGradeIn,
    AssignmentCreate,
    AssignmentPatch,
    AttemptStart,
    AutosaveIn,
    IntegrityDecisionIn,
    InvalidateIn,
    ItemGradeIn,
    OverrideCreate,
    RebindIn,
    RebindOverrideIn,
    ReleaseIn,
    SectionsPut,
    SubmitIn,
    TestCreate,
    TestSettings,
)
from app.modules.placement.policies import can_in_org, require, scope_for
from app.modules.placement.rls import bind_principal
from app.modules.sessions.service import register_active_attempt_lookup

register_active_attempt_lookup(svc.sessions_holding_attempts)

dflt = authenticated_router(tags=["assessments"], dependencies=[Depends(bind_principal)])
neutral = authenticated_router(tags=["assessments"], idle="neutral", dependencies=[Depends(bind_principal)])
l3r = authenticated_router(
    tags=["assessments"], route_tag="l3_readonly", dependencies=[Depends(bind_principal)]
)


def _nopg(session: Any) -> Any:
    """The request session, or ``None`` without Postgres (``db.NO_POSTGRES`` is falsy): core
    ``idempotent`` then keeps no Postgres savepoint (it checks ``session is not None``)."""
    return session or None


def _client_ip(request: Request) -> str | None:
    ip = getattr(request.state, "client_ip", None)
    return str(ip) if ip else None


async def _commit_problem(fn: Callable[[], Awaitable[Any]]) -> Any:
    try:
        return await fn()
    except ProblemError as e:
        if e.status >= 500:
            raise
        return problem_response(e)


def _as_result(e: ProblemError) -> IdemResult:
    return IdemResult(body=e.to_body(get_request_id()), status=e.status, headers=e.headers or None)


async def _owned_live(
    session: AsyncSession,
    principal: Principal,
    attempt_id: uuid.UUID,
    *,
    read_only_summary: bool = False,
) -> tuple[TestAttempt, Test, bool]:
    """Load own attempt (locked), apply lazy expiry, then enforce the session binding."""
    att, test = await svc.load_owned(session, principal, attempt_id, lock=True)
    await svc.expire_if_due(session, att, test)
    reattached = await svc.ensure_bound(session, principal, att, test, read_only_summary=read_only_summary)
    return att, test, reattached


# =========================================================================== attempts (ATT)


@dflt.post("/attempts", status_code=201, dependencies=[Depends(rl.limit("att01_start"))])
async def att_01_start(
    request: Request,
    body: AttemptStart,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
) -> JSONResponse:
    async def op() -> IdemResult:
        key = request.headers.get(IDEM_HEADER, "")
        att, test = await svc.start(session, principal, body, idempotency_key=key, ip=_client_ip(request))
        return IdemResult(
            body=await svc.state_payload(session, principal, att, test), status=201, resource_id=att.id
        )

    return await idempotent(request, _nopg(session), user_id=principal.user_id, operation=op, required=True)


@dflt.get("/attempts/{attempt_id}/state", dependencies=[Depends(rl.limit("att02_state"))])
async def att_02_state(
    attempt_id: uuid.UUID,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
) -> Any:
    async def fn() -> Any:
        att, test, reattached = await _owned_live(session, principal, attempt_id, read_only_summary=True)
        return await svc.state_payload(session, principal, att, test, reattached=reattached)

    return await _commit_problem(fn)


@dflt.post("/attempts/{attempt_id}/resume", dependencies=[Depends(rl.limit("att03_resume"))])
async def att_03_resume(
    request: Request,
    attempt_id: uuid.UUID,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
) -> Any:
    async def fn() -> Any:
        att, test, reattached = await _owned_live(session, principal, attempt_id)
        if att.status == "in_progress" and not reattached:
            await svc.add_event(session, att, "resume", principal=principal, ip=_client_ip(request))
            await svc.hold_session(session, principal.session_id, att, test)
        return await svc.state_payload(session, principal, att, test, reattached=reattached)

    return await _commit_problem(fn)


@dflt.post("/attempts/{attempt_id}/rebind/otp")
async def att_04_rebind_otp(
    attempt_id: uuid.UUID,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
) -> Any:
    async def fn() -> Any:
        att, test = await svc.load_owned(session, principal, attempt_id, lock=True)
        if await svc.expire_if_due(session, att, test):
            raise ProblemError(
                "attempt_closed", attempt_status=att.status, deadline_at=svc.iso(att.deadline_at)
            )
        return await svc.send_rebind_otp(session, principal, att, test)

    return await _commit_problem(fn)


@dflt.post("/attempts/{attempt_id}/rebind", dependencies=[Depends(rl.limit("att05_rebind"))])
async def att_05_rebind(
    request: Request,
    attempt_id: uuid.UUID,
    body: RebindIn,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
) -> JSONResponse:
    async def op() -> IdemResult:
        try:
            if not body.confirm:
                raise ProblemError(
                    "validation_failed",
                    errors=[{"field": "confirm", "code": "required", "message": "confirm the device switch"}],
                )
            att, test = await svc.load_owned(session, principal, attempt_id, lock=True)
            await svc.expire_if_due(session, att, test)
            return IdemResult(body=await svc.rebind(session, principal, att, test, otp_code=body.otp_code))
        except ProblemError as e:
            if e.status >= 500:
                raise
            return _as_result(e)  # stored + committed: keeps rebind_refused / auto-submit writes

    return await idempotent(request, _nopg(session), user_id=principal.user_id, operation=op, required=True)


@dflt.post("/attempts/{attempt_id}/autosave", dependencies=[Depends(rl.limit("att06_autosave"))])
async def att_06_autosave(
    attempt_id: uuid.UUID,
    body: AutosaveIn,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
) -> Any:
    async def fn() -> Any:
        att, test, _ = await _owned_live(session, principal, attempt_id)
        return await svc.autosave(session, principal, att, test, body)

    return await _commit_problem(fn)


@neutral.get("/attempts/{attempt_id}/time", dependencies=[Depends(rl.limit("att07_time"))])
async def att_07_time(
    attempt_id: uuid.UUID,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
) -> Any:
    async def fn() -> Any:
        att, test, _ = await _owned_live(session, principal, attempt_id)
        secs = await svc.advance_sections(session, att, test, utcnow())
        sec = next((s for s in secs if s.test_section_id == att.current_section_id), None)
        return svc.time_payload(att, sec)

    return await _commit_problem(fn)


@dflt.post("/attempts/{attempt_id}/sections/{section_id}/enter")
async def att_08_enter_section(
    attempt_id: uuid.UUID,
    section_id: uuid.UUID,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
) -> Any:
    async def fn() -> Any:
        att, test, _ = await _owned_live(session, principal, attempt_id)
        if att.status != "in_progress":
            raise ProblemError(
                "attempt_closed", attempt_status=att.status, deadline_at=svc.iso(att.deadline_at)
            )
        await svc.enter_section(session, principal, att, test, section_id)
        return await svc.state_payload(session, principal, att, test)

    return await _commit_problem(fn)


@dflt.post("/attempts/{attempt_id}/sections/{section_id}/submit")
async def att_09_submit_section(
    attempt_id: uuid.UUID,
    section_id: uuid.UUID,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
) -> Any:
    async def fn() -> Any:
        att, test, _ = await _owned_live(session, principal, attempt_id)
        if att.status != "in_progress":
            raise ProblemError(
                "attempt_closed", attempt_status=att.status, deadline_at=svc.iso(att.deadline_at)
            )
        await svc.submit_section(session, principal, att, test, section_id)
        return await svc.state_payload(session, principal, att, test)

    return await _commit_problem(fn)


@dflt.post("/attempts/{attempt_id}/submit", dependencies=[Depends(rl.limit("att10_submit"))])
async def att_10_submit(
    request: Request,
    attempt_id: uuid.UUID,
    body: SubmitIn,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
) -> JSONResponse:
    async def op() -> IdemResult:
        try:
            att, test, _ = await _owned_live(session, principal, attempt_id)
            return IdemResult(
                body=await svc.submit(
                    session, principal, att, test, body.final_items, body.confirm_unanswered
                )
            )
        except ProblemError as e:
            if e.status >= 500:
                raise
            return _as_result(e)

    return await idempotent(request, _nopg(session), user_id=principal.user_id, operation=op, required=True)


async def _attempt_reader(
    request: Request, session: AsyncSession, principal: Principal, attempt_id: uuid.UUID
) -> tuple[TestAttempt, Test, bool]:
    """Owner, or staff holding ``test.results.read`` at the attempt's batch/org (ATT-11/12)."""
    att = await svc.load_attempt(session, attempt_id)
    test = await adb.get(session, Test, att.test_id)
    if test is None:  # pragma: no cover
        raise ProblemError("not_found")
    if att.user_id == principal.user_id:
        await svc.expire_if_due(session, att, test)
        return att, test, False
    if await studio.attempt_scope_allows(
        request, principal, "test.results.read", batch_id=att.batch_id, org_id=att.organization_id
    ):
        return att, test, True
    raise ProblemError("not_found")


@l3r.get("/attempts/{attempt_id}/result")
async def att_11_result(
    request: Request,
    attempt_id: uuid.UUID,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
) -> Any:
    async def fn() -> Any:
        att, test, staff = await _attempt_reader(request, session, principal, attempt_id)
        return await svc.result_payload(session, att, test, staff=staff, principal=principal)

    return await _commit_problem(fn)


@l3r.get("/attempts/{attempt_id}/review")
async def att_12_review(
    request: Request,
    attempt_id: uuid.UUID,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
) -> Any:
    async def fn() -> Any:
        att, test, staff = await _attempt_reader(request, session, principal, attempt_id)
        keys = staff and await can_in_org(
            request, session, principal, "question.answer_key.read", att.organization_id
        )
        return await svc.review_payload(session, att, test, staff=staff, staff_keys=keys, principal=principal)

    return await _commit_problem(fn)


@l3r.get("/me/attempts")
async def att_13_my_attempts(
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
    test_id: uuid.UUID | None = None,
    limit: int = Query(default=MAX_LIMIT, ge=1, le=MAX_LIMIT),
    cursor: str | None = None,
) -> dict[str, Any]:
    """Own attempts, newest first, cursor-paginated on (started_at, id) (BE-21, §1.10)."""
    q = (
        select(TestAttempt, Test.title)
        .join(Test, Test.id == TestAttempt.test_id)
        .where(TestAttempt.user_id == principal.user_id)
        .order_by(TestAttempt.started_at.desc(), TestAttempt.id.desc())
        .limit(limit + 1)
    )
    if test_id is not None:
        q = q.where(TestAttempt.test_id == test_id)
    if cursor:
        pos = decode_cursor(cursor)
        try:
            at, last = datetime.fromisoformat(str(pos["s"])), uuid.UUID(str(pos["i"]))
        except (KeyError, ValueError) as e:
            raise ProblemError("invalid_cursor") from e
        q = q.where(tuple_(TestAttempt.started_at, TestAttempt.id) < tuple_(literal(at), literal(last)))
    rows = (await adb.execute(session, q)).all()
    more = len(rows) > limit
    rows = rows[:limit]
    nxt = {"s": rows[-1][0].started_at.isoformat(), "i": str(rows[-1][0].id)} if more and rows else None
    return {
        "items": [
            {
                "attempt_id": str(a.id),
                "test_id": str(a.test_id),
                "test_title": title,
                "attempt_no": a.attempt_no,
                "status": a.status,
                "started_at": svc.iso(a.started_at),
                "deadline_at": svc.iso(a.deadline_at),
                "submitted_at": svc.iso(a.submitted_at),
                "submit_reason": a.submit_reason,
            }
            for a, title in rows
        ],
        "page": page_meta(nxt, limit),
        "server_now": to_rfc3339(utcnow()),
    }


# =========================================================================== student test views


@l3r.get("/me/tests")
async def asm_01_my_tests(
    session: PrincipalDbSession, principal: Principal = Depends(require_active_principal)
) -> dict[str, Any]:
    now = utcnow()
    entries: dict[uuid.UUID, dict[str, Any]] = {}
    rows = (
        await adb.execute(
            session,
            select(TestAssignment, Test)
            .join(Test, Test.id == TestAssignment.test_id)
            .where(Test.status == "published"),
        )
    ).all()
    # ``a`` is eligible iff ``svc.eligible_assignments(t.id)`` (every assignment of the test, kept
    # when eligible) lists it, and that filter only looks at ``a`` itself: the same predicate per
    # row, with batch membership looked up once per batch (was: the test's assignments re-read
    # and every batch re-checked for EACH row).
    member: dict[uuid.UUID, bool] = {}
    for a, t in rows:
        if a.batch_id is not None:
            if a.batch_id not in member:
                member[a.batch_id] = await svc._member_of_batch(session, principal.user_id, a.batch_id)
            eligible = member[a.batch_id]
        else:
            eligible = a.organization_id is not None and a.organization_id in principal.org_ids
        if not eligible:
            continue
        entries.setdefault(t.id, {"test": t, "assignment": a})
    for t in (
        await adb.execute(session, select(Test).where(Test.status == "published", Test.is_free.is_(True)))
    ).scalars():
        entries.setdefault(t.id, {"test": t, "assignment": None})
    attempts_rows = (
        await adb.execute(session, select(TestAttempt).where(TestAttempt.user_id == principal.user_id))
    ).scalars()
    by_test: dict[uuid.UUID, list[TestAttempt]] = {}
    for at in attempts_rows:
        by_test.setdefault(at.test_id, []).append(at)
    for tid in by_test:
        if tid not in entries:
            t2 = await adb.get(session, Test, tid)
            if t2 is not None:
                entries[tid] = {"test": t2, "assignment": None}
    overrides = await svc.overrides_for_many(
        session, principal.user_id, [(tid, e["assignment"]) for tid, e in entries.items()]
    )
    items = []
    for tid, e in entries.items():
        t, a = e["test"], e["assignment"]
        _, extra_attempts, window_ext = overrides[tid]
        frm, until = svc.window_of(t, a)
        mine = by_test.get(tid, [])
        allowed = (a.attempts_allowed if a and a.attempts_allowed else None) or t.attempts_allowed
        left = None if allowed is None else max(0, allowed + extra_attempts - len(mine))
        if any(x.status == "in_progress" for x in mine):
            status = "in_progress"
        elif frm is not None and now < frm:
            status = "scheduled"
        elif until is not None and now >= until + timedelta(seconds=window_ext):
            status = "closed"
        elif left == 0:
            status = "completed"
        else:
            status = "available"
        items.append(
            {
                "test_id": str(tid),
                "title": t.title,
                "test_kind": t.test_kind,
                "duration_seconds": t.duration_seconds,
                "test_assignment_id": str(a.id) if a else None,
                "available_from": svc.iso(frm),
                "available_until": svc.iso(until),
                "attempts_used": len(mine),
                "attempts_left": left,
                "status": status,
                "in_progress_attempt_id": next((str(x.id) for x in mine if x.status == "in_progress"), None),
            }
        )
    items.sort(key=lambda i: (i["status"] != "in_progress", i["available_until"] or "9999"))
    return {"items": items, "server_now": to_rfc3339(now)}


@dflt.get("/tests/{test_id}")
async def asm_02_test_detail(
    test_id: uuid.UUID, session: PrincipalDbSession, principal: Principal = Depends(require_active_principal)
) -> dict[str, Any]:
    t = await adb.get(session, Test, test_id)
    if t is None or t.status != "published":
        raise ProblemError("not_found")
    assignments = await svc.eligible_assignments(session, principal, t.id)
    via = "assignment" if assignments else None
    if via is None:
        decision = await check_access(session, principal, "test", t.id, is_free=t.is_free)
        if not decision.allowed:
            raise ProblemError(
                "entitlement_required", resource_type="test", resource_id=str(t.id), reason=decision.reason
            )
        via = decision.reason
    a = assignments[0] if assignments else None
    _, extra_attempts, window_ext = await svc.overrides_for(session, t.id, principal.user_id, a)
    used = len(
        (
            await adb.execute(
                session,
                select(TestAttempt.id).where(
                    TestAttempt.test_id == t.id, TestAttempt.user_id == principal.user_id
                ),
            )
        ).all()
    )
    allowed = (a.attempts_allowed if a and a.attempts_allowed else None) or t.attempts_allowed
    frm, until = svc.window_of(t, a)
    secs = await studio.sections_of(session, t.id)
    return {
        "id": str(t.id),
        "title": t.title,
        "test_kind": t.test_kind,
        "version": t.version,
        "duration_seconds": t.duration_seconds,
        "grace_seconds": t.grace_seconds,
        "navigation_mode": t.navigation_mode,
        "pass_percentage": str(t.pass_percentage) if t.pass_percentage is not None else None,
        "marking": "Per question as shown; negative marks apply to wrong answers only, unanswered = 0.",
        "sections": studio.sections_out(secs, with_rules=False),
        "integrity_notice": {
            "settings": t.integrity_settings,
            "text": "Focus changes and paste events are logged as advisory signals only; they never "
            "change your score automatically.",
        },
        "protocol": exam.protocol_of(t).public(),
        "window": {
            "available_from": svc.iso(frm),
            "available_until": svc.iso(until),
            "window_extension_seconds": window_ext,
        },
        "attempts_allowed": allowed,
        "attempts_left": None if allowed is None else max(0, allowed + extra_attempts - used),
        "eligibility": {"eligible": True, "via": via, "test_assignment_id": str(a.id) if a else None},
        "server_now": to_rfc3339(utcnow()),
    }


# =========================================================================== studio (ASM-03..09)


@dflt.get("/studio/tests")
async def asm_03_list_tests(
    request: Request,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
    status: str | None = Query(default=None, pattern="^(draft|published|closed|archived)$"),
    limit: int = Query(default=MAX_LIMIT, ge=1, le=MAX_LIMIT),
    cursor: str | None = None,
) -> dict[str, Any]:
    q = select(Test).order_by(Test.created_at.desc(), Test.id.desc()).limit(limit + 1)
    if status:
        q = q.where(Test.status == status)
    if cursor:
        pos = decode_cursor(cursor)
        try:
            at, last = datetime.fromisoformat(str(pos["c"])), uuid.UUID(str(pos["i"]))
        except (KeyError, ValueError) as e:
            raise ProblemError("invalid_cursor") from e
        q = q.where(tuple_(Test.created_at, Test.id) < tuple_(literal(at), literal(last)))
    rows = list((await adb.execute(session, q)).scalars())
    more = len(rows) > limit
    rows = rows[:limit]
    nxt = {"c": rows[-1].created_at.isoformat(), "i": str(rows[-1].id)} if more and rows else None
    items = []
    cache: dict[uuid.UUID | None, bool] = {}
    for t in rows:
        if t.organization_id not in cache:
            cache[t.organization_id] = await can_in_org(
                request, session, principal, "test.create", t.organization_id
            )
        # ADM-49: batch-scoped trainers list only the tests they created.
        if cache[t.organization_id] and await studio.can_test(request, session, principal, "test.create", t):
            items.append(studio.test_out(t))
        elif await studio.can_read_test(request, session, principal, t):
            items.append(studio.test_out(t))  # evaluators: read-only, for the grading screens
    if not cache or not any(cache.values()):
        # Distinguish "no tests yet" from "not allowed at all".
        allowed_any = (
            await can_in_org(request, session, principal, "test.create", None)
            or any(
                [await can_in_org(request, session, principal, "test.create", o) for o in principal.org_ids]
            )
            or await studio.reads_results_anywhere(request, principal)
        )
        if not allowed_any:
            raise ProblemError("permission_denied", permission="test.create")
    # BE-21: cursor over the scanned rows; a page may hold fewer items than ``limit`` after the
    # per-org permission filter, ``page.has_more`` still tells whether to continue.
    return {"items": items, "page": page_meta(nxt, limit)}


@dflt.post("/studio/tests", status_code=201)
async def asm_04_create_test(
    request: Request,
    body: TestCreate,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
) -> JSONResponse:
    scope, org = await scope_for(session, batch_id=body.batch_id, organization_id=body.organization_id)
    await require(request, principal, "test.create", scope)
    await require_app_enabled(session, app_key="assessments")

    async def op() -> IdemResult:
        t = await studio.create_test(session, principal, body, org)
        await audit(session, principal, "test.created", "test", t.id, organization_id=org)
        return IdemResult(body=studio.test_out(t), status=201, resource_id=t.id)

    return await idempotent(request, _nopg(session), user_id=principal.user_id, operation=op, required=False)


async def _editable_test(
    request: Request, session: AsyncSession, principal: Principal, test_id: uuid.UUID
) -> Test:
    t = await studio.get_test(session, test_id)
    await studio.require_test_perm(request, session, principal, "test.edit", t)
    return t


@dflt.get("/studio/tests/{test_id}")
async def asm_05_get_test(
    request: Request,
    test_id: uuid.UUID,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
) -> dict[str, Any]:
    t = await studio.get_test(session, test_id)
    if not await studio.can_read_test(request, session, principal, t):
        raise ProblemError("permission_denied", permission="test.edit")
    return {
        **studio.test_out(t),
        "sections": studio.sections_out(await studio.sections_of(session, t.id), with_rules=True),
    }


@dflt.patch("/studio/tests/{test_id}")
async def asm_06_patch_test(
    request: Request,
    test_id: uuid.UUID,
    body: TestSettings,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
) -> dict[str, Any]:
    t = await _editable_test(request, session, principal, test_id)
    before = studio.test_out(t)
    await studio.patch_test(session, t, body)
    await audit(
        session,
        principal,
        "test.settings_changed",
        "test",
        t.id,
        organization_id=t.organization_id,
        before=before,
        after=studio.test_out(t),
    )
    return studio.test_out(t)


@dflt.put("/studio/tests/{test_id}/sections")
async def asm_07_put_sections(
    request: Request,
    test_id: uuid.UUID,
    body: SectionsPut,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
) -> dict[str, Any]:
    t = await _editable_test(request, session, principal, test_id)
    await studio.put_sections(session, t, body)
    await audit(session, principal, "test.sections_replaced", "test", t.id, organization_id=t.organization_id)
    return {
        **studio.test_out(t),
        "sections": studio.sections_out(await studio.sections_of(session, t.id), with_rules=True),
    }


@dflt.post("/studio/tests/{test_id}/validate")
async def asm_08_validate(
    request: Request,
    test_id: uuid.UUID,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
) -> dict[str, Any]:
    t = await _editable_test(request, session, principal, test_id)
    return await studio.validate(session, t)


@dflt.post("/studio/tests/{test_id}/publish")
async def asm_09_publish(
    request: Request,
    test_id: uuid.UUID,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
) -> JSONResponse:
    t = await _editable_test(request, session, principal, test_id)
    await require_app_enabled(session, app_key="assessments")

    async def op() -> IdemResult:
        await studio.publish(session, t)
        await audit(
            session,
            principal,
            "test.published",
            "test",
            t.id,
            organization_id=t.organization_id,
            after={"version": t.version},
        )
        return IdemResult(body=studio.test_out(t))

    return await idempotent(request, _nopg(session), user_id=principal.user_id, operation=op, required=False)


@dflt.post("/studio/tests/{test_id}/archive")
async def asm_09b_archive(
    request: Request,
    test_id: uuid.UUID,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
) -> JSONResponse:
    """Retire a test: whoever may edit it (``test.edit``) archives it; open assignment windows
    close now; existing attempts and results stay readable."""
    t = await _editable_test(request, session, principal, test_id)

    async def op() -> IdemResult:
        closed = await studio.archive(session, t)
        await audit(
            session,
            principal,
            "test.archived",
            "test",
            t.id,
            organization_id=t.organization_id,
            after={"closed_assignments": closed},
        )
        return IdemResult(body={**studio.test_out(t), "closed_assignments": closed})

    return await idempotent(request, _nopg(session), user_id=principal.user_id, operation=op, required=False)


# =========================================================================== assignments, overrides, results


@dflt.post("/tests/{test_id}/assignments", status_code=201)
async def asm_10_assign(
    request: Request,
    test_id: uuid.UUID,
    body: AssignmentCreate,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
) -> JSONResponse:
    t = await studio.get_test(session, test_id)

    async def op() -> IdemResult:
        a = await studio.create_assignment(request, session, principal, t, body)
        return IdemResult(body=studio.assignment_out(a), status=201, resource_id=a.id)

    return await idempotent(request, _nopg(session), user_id=principal.user_id, operation=op, required=False)


@dflt.get("/tests/{test_id}/assignments")
async def asm_11_assignments(
    request: Request,
    test_id: uuid.UUID,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
) -> dict[str, Any]:
    t = await studio.get_test(session, test_id)
    return {"items": await studio.list_assignments(request, session, principal, t)}


@dflt.patch("/test-assignments/{assignment_id}")
async def asm_12_patch_assignment(
    request: Request,
    assignment_id: uuid.UUID,
    body: AssignmentPatch,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
) -> dict[str, Any]:
    a = await studio.get_assignment(session, assignment_id)
    await studio.require_assignment_perm(request, principal, "test.assign", a)
    return await studio.patch_assignment(session, principal, a, body)


@dflt.post("/tests/{test_id}/overrides", status_code=201)
async def asm_13_override(
    request: Request,
    test_id: uuid.UUID,
    body: OverrideCreate,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
) -> JSONResponse:
    t = await studio.get_test(session, test_id)

    async def op() -> IdemResult:
        o = await studio.create_override(request, session, principal, t, body)
        return IdemResult(body=studio.override_out(o), status=201, resource_id=o.id)

    return await idempotent(request, _nopg(session), user_id=principal.user_id, operation=op, required=False)


@dflt.get("/tests/{test_id}/overrides")
async def asm_14_overrides(
    request: Request,
    test_id: uuid.UUID,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
) -> dict[str, Any]:
    t = await studio.get_test(session, test_id)
    return {"items": await studio.list_overrides(request, session, principal, t)}


@dflt.get("/tests/{test_id}/attempts")
async def asm_15_attempts(
    request: Request,
    test_id: uuid.UUID,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
) -> dict[str, Any]:
    t = await studio.get_test(session, test_id)
    return {"items": await studio.list_attempts(request, session, principal, t)}


@dflt.post("/tests/{test_id}/results/release")
async def asm_16_release(
    request: Request,
    test_id: uuid.UUID,
    body: ReleaseIn,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
) -> JSONResponse:
    t = await studio.get_test(session, test_id)

    async def op() -> IdemResult:
        return IdemResult(
            body=await studio.release_results(request, session, principal, t, body.test_assignment_id)
        )

    return await idempotent(request, _nopg(session), user_id=principal.user_id, operation=op, required=False)


@dflt.post("/attempts/{attempt_id}/rebind-override", status_code=201)
async def asm_21_rebind_override(
    request: Request,
    attempt_id: uuid.UUID,
    body: RebindOverrideIn,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
) -> JSONResponse:
    att = await svc.load_attempt(session, attempt_id)
    if not await studio.attempt_scope_allows(
        request, principal, "test.override.grant", batch_id=att.batch_id, org_id=att.organization_id
    ):
        raise ProblemError("not_found" if att.user_id != principal.user_id else "permission_denied")

    async def op() -> IdemResult:
        if att.status != "in_progress":
            raise ProblemError(
                "attempt_closed", attempt_status=att.status, deadline_at=svc.iso(att.deadline_at)
            )
        await svc.add_event(
            session,
            att,
            "override_applied",
            principal=principal,
            payload={"kind": "rebind", "reason": body.reason, "granted_by": str(principal.user_id)},
        )
        await audit(
            session,
            principal,
            "attempt.rebind_override_granted",
            "test_attempt",
            att.id,
            organization_id=att.organization_id,
            subject_user_id=att.user_id,
            reason=body.reason,
        )
        return IdemResult(body={"attempt_id": str(att.id), "granted": True}, status=201)

    return await idempotent(request, _nopg(session), user_id=principal.user_id, operation=op, required=False)


# =========================================================================== integrity + report


@dflt.get("/integrity/flags")
async def asm_19_integrity_flags(
    request: Request,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
    test_id: uuid.UUID | None = None,
    batch_id: uuid.UUID | None = None,
    status: str | None = Query(default=None, pattern="^(open|decided)$"),
    cursor: str | None = Query(default=None, max_length=2000),
    limit: int = Query(default=25, ge=1, le=100),
) -> dict[str, Any]:
    return await integrity.list_flags(
        request,
        session,
        principal,
        test_id=test_id,
        batch_id=batch_id,
        status=status,
        cursor=cursor,
        limit=limit,
    )


@dflt.post("/attempts/{attempt_id}/integrity-decision", status_code=201)
async def asm_20_integrity_decision(
    request: Request,
    attempt_id: uuid.UUID,
    body: IntegrityDecisionIn,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
) -> JSONResponse:
    async def op() -> IdemResult:
        out, status = await integrity.decide(request, session, principal, attempt_id, body.outcome, body.note)
        return IdemResult(body=out, status=status, resource_id=attempt_id)

    return await idempotent(request, _nopg(session), user_id=principal.user_id, operation=op, required=False)


@dflt.post("/attempts/{attempt_id}/invalidate")
async def asm_18_invalidate(
    request: Request,
    attempt_id: uuid.UUID,
    body: InvalidateIn,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
) -> JSONResponse:
    async def op() -> IdemResult:
        att = await integrity.load_for_staff(request, session, principal, attempt_id, "attempt.invalidate")
        await require_step_up("staff")(principal)
        await integrity.invalidate(session, principal, att, body.reason, source="manual")
        return IdemResult(
            body={"attempt_id": str(att.id), "status": att.status, "integrity_status": att.integrity_status},
            resource_id=att.id,
        )

    return await idempotent(request, _nopg(session), user_id=principal.user_id, operation=op, required=False)


@dflt.get("/tests/{test_id}/report")
async def asm_22_report(
    request: Request,
    test_id: uuid.UUID,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
    batch_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    t = await studio.get_test(session, test_id)
    return await report.build_report(request, session, principal, t, batch_id=batch_id)


# =========================================================================== evaluation (exam build)


@dflt.get("/tests/{test_id}/evaluation")
async def asm_24_evaluation(
    request: Request,
    test_id: uuid.UUID,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
) -> dict[str, Any]:
    t = await studio.get_test(session, test_id)
    return await evaluation.evaluation_list(request, session, principal, t)


@dflt.get("/attempts/{attempt_id}/evaluation")
async def asm_25_attempt_evaluation(
    request: Request,
    attempt_id: uuid.UUID,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
) -> dict[str, Any]:
    return await evaluation.attempt_review(request, session, principal, attempt_id)


@dflt.post("/tests/{test_id}/evaluation/ai-grade")
async def asm_26_ai_grade(
    request: Request,
    test_id: uuid.UUID,
    body: AiGradeIn,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
) -> JSONResponse:
    t = await studio.get_test(session, test_id)

    async def op() -> IdemResult:
        return IdemResult(
            body=await evaluation.run_ai_grading(
                request, session, principal, t, attempt_id=body.attempt_id, redo=body.redo
            )
        )

    return await idempotent(request, _nopg(session), user_id=principal.user_id, operation=op, required=False)


@dflt.post("/attempts/{attempt_id}/items/{question_version_id}/grade")
async def asm_27_grade_item(
    request: Request,
    attempt_id: uuid.UUID,
    question_version_id: uuid.UUID,
    body: ItemGradeIn,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
) -> JSONResponse:
    async def op() -> IdemResult:
        return IdemResult(
            body=await evaluation.finalize_item(
                request, session, principal, attempt_id, question_version_id, body.marks, body.feedback
            )
        )

    return await idempotent(request, _nopg(session), user_id=principal.user_id, operation=op, required=False)


router = APIRouter()
for _r in (dflt, neutral, l3r):
    router.include_router(_r)
