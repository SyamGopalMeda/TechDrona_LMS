"""Coding API (api-specification §16). Implemented: COD-01..08, 10, 13..19 (+ studio problem
detail, reference solutions, latest validation). Planned: COD-09 SSE, COD-11 diff,
COD-12 editorial, COD-20..22 code review / similarity.

The API never executes student code: run/submit insert a queued ``code_submissions`` row; the
judge worker (``worker.py``) does the rest. Hidden cases are decrypted on the API side only by
the permission-gated COD-18 validation and COD-17 token redemption (``authoring.py``).
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import Depends, Path, Query, Request
from fastapi.responses import JSONResponse, Response
from sqlalchemy import select

from app.core.access import check_access
from app.core.audit import audit
from app.core.auth import ScopeRef, require_active_principal, require_step_up
from app.core.config import get_settings
from app.core.errors import ProblemError
from app.core.firestore.backend import uses_firestore

# Postgres stack: the request session unchanged. No Postgres: the SQL engine's ``MemoryTx`` with the
# principal's RLS context, so modules on the engine (assessments: the attempt validator) can use it.
from app.core.firestore.sqlstore import StorePrincipalDbSession as PrincipalDbSession
from app.core.idempotency import HEADER as IDEM_HEADER
from app.core.idempotency import IdemResult, idempotent, route_key
from app.core.models import IdempotencyKey
from app.core.pagination import DEFAULT_LIMIT, MAX_LIMIT, decode_cursor, page_meta
from app.core.principal import Principal
from app.core.routing import authenticated_router
from app.modules.coding import authoring, service
from app.modules.coding import privacy as _privacy  # noqa: F401  (registers the erasure provider)
from app.modules.coding.models import CodeSubmission, CodingProblem, CodingTestCase
from app.modules.coding.policies import check_permission, has_permission, scope_for
from app.modules.coding.rls import bind_principal
from app.modules.coding.schemas import (
    DraftIn,
    ProblemCreateIn,
    ProblemPatchIn,
    ReferenceSolutionIn,
    RunIn,
    SubmitIn,
    TestCaseIn,
    ValidateIn,
)

router = authenticated_router(tags=["coding"], dependencies=[Depends(bind_principal)])

Limit = Annotated[int, Query(ge=1, le=MAX_LIMIT)]


# --------------------------------------------------------------------------- catalogue


def _fs() -> bool:
    return uses_firestore("coding")


async def _repo(session: Any) -> Any:
    from app.modules.coding import repo_firestore

    return await repo_firestore.repo(session)


def _nopg(session: Any) -> Any:
    """The request session, or ``None`` without Postgres (``db.NO_POSTGRES`` is falsy): core
    ``idempotent`` then keeps no Postgres savepoint (it checks ``session is not None``)."""
    return session or None


@router.get("/coding/languages", openapi_extra={"x-td-idle": "neutral"})
async def list_languages(session: PrincipalDbSession) -> dict[str, Any]:
    langs = await service.enabled_languages(session)
    return {
        "data": [
            {
                "language_key": lang.language_key,
                "display_name": lang.display_name,
                "version": lang.version_label,
                "starter_template": lang.starter_template,
            }
            for lang in langs
        ],
        # FakeJudgeAdapter never runs code (every run is "Wrong answer" unless a FAKE_VERDICT
        # marker is present): screens must say the code runner is not integrated yet.
        "judge": {"simulated": get_settings().JUDGE_PROVIDER.lower() == "fake"},
    }


@router.get("/coding/problems")
async def list_problems(
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
    difficulty: Annotated[int | None, Query(ge=1, le=5)] = None,
    cursor: str | None = None,
    limit: Limit = DEFAULT_LIMIT,
) -> dict[str, Any]:
    after: uuid.UUID | None = None
    if cursor:
        try:
            after = uuid.UUID(str(decode_cursor(cursor)["id"]))
        except (KeyError, ValueError) as e:
            raise ProblemError("invalid_cursor") from e
    pairs: Any
    if _fs():
        repo = await _repo(session)
        found = sorted(
            (
                p
                for p in await repo.problems(status="published")
                if (difficulty is None or p.difficulty == difficulty) and (after is None or p.id > after)
            ),
            key=lambda p: p.id,
        )
        rows = found[: limit + 1]
        more = len(rows) > limit
        rows = rows[:limit]
        ids = {p.id for p in rows}
        pairs = [
            (s.coding_problem_id, s.verdict)
            for s in await repo.submissions_of(principal.user_id, (("mode", "==", "submit"),))
            if s.coding_problem_id in ids
        ]
    else:
        q = select(CodingProblem).where(CodingProblem.status == "published")
        if difficulty is not None:
            q = q.where(CodingProblem.difficulty == difficulty)
        if after is not None:
            q = q.where(CodingProblem.id > after)
        rows = list((await session.execute(q.order_by(CodingProblem.id).limit(limit + 1))).scalars())
        more = len(rows) > limit
        rows = rows[:limit]
        status_rows = await session.execute(
            select(CodeSubmission.coding_problem_id, CodeSubmission.verdict).where(
                CodeSubmission.user_id == principal.user_id,
                CodeSubmission.mode == "submit",
                CodeSubmission.coding_problem_id.in_([p.id for p in rows]),
            )
        )
        pairs = status_rows.all()
    mine: dict[uuid.UUID, str] = {}
    for pid, verdict in pairs:
        if verdict == "AC":
            mine[pid] = "solved"
        else:
            mine.setdefault(pid, "attempted")
    data = []
    for p in rows:
        decision = await check_access(session, principal, "coding_problem", p.id, is_free=p.is_free)
        data.append(
            {
                "problem_id": str(p.id),
                "slug": p.slug,
                "title": p.title,
                "difficulty": p.difficulty,
                "is_free": p.is_free,
                "entitled": decision.allowed,
                "status": mine.get(p.id, "not_started"),
            }
        )
    return {"data": data, "meta": page_meta({"id": str(rows[-1].id)} if more and rows else None, limit)}


@router.get("/coding/problems/{slug}")
async def get_problem(
    slug: str,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
    attempt_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    """COD-03. ``slug`` may also be the problem id (test items deliver ``coding_problem_id``).
    With ``attempt_id`` the learner's in-progress attempt containing the problem grants access
    without a standalone entitlement."""
    p = await service.problem_by_slug_or_id(session, slug)
    await service.require_problem_access(session, principal, p, attempt_id=attempt_id)
    out = service.problem_out(p)
    out["samples"] = [
        {"ordinal": c.ordinal, "input": c.sample_input, "expected_output": c.sample_output}
        for c in await service.sample_cases(session, p)
    ]
    langs = {lang.language_key: lang for lang in await service.enabled_languages(session)}
    out["languages"] = [
        {
            "language_key": k,
            "display_name": langs[k].display_name,
            "starter_template": langs[k].starter_template,
        }
        for k in p.allowed_languages
        if k in langs
    ]
    return out


# --------------------------------------------------------------------------- run / submit


async def _idem_exists(request: Request, session: Any, principal: Principal) -> bool:
    key = request.headers.get(IDEM_HEADER)
    if not key:
        raise ProblemError("idempotency_key_required")
    if uses_firestore("core"):  # the idempotency record lives where core.idempotent keeps it
        from app.core.firestore.core_store import IDEM_JOB, IDEMPOTENCY, idem_doc_id
        from app.core.firestore.store import ScopedStore

        doc_id = idem_doc_id(principal.user_id, route_key(request), key)
        return await ScopedStore.system(IDEM_JOB).get(IDEMPOTENCY, doc_id) is not None
    row = await session.execute(
        select(IdempotencyKey.id).where(
            IdempotencyKey.user_id == principal.user_id,
            IdempotencyKey.route_key == route_key(request),
            IdempotencyKey.idem_key == key,
        )
    )
    return row.first() is not None


@router.post(
    "/coding/problems/{problem_id}/run", status_code=202, openapi_extra={"x-td-idle": "engaged_only"}
)
async def run_code(
    problem_id: uuid.UUID,
    body: RunIn,
    request: Request,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
) -> JSONResponse:
    replay = await _idem_exists(request, session, principal)
    problem = await service.published_problem(session, problem_id)
    if not replay:
        await service.precheck_practice(
            session,
            principal,
            problem,
            mode="run",
            language_key=body.language_key,
            source_code=body.source_code,
            custom_input=body.custom_input,
            attempt_id=body.attempt_id,
        )

    async def op() -> IdemResult:
        sub = await service.create_submission(
            session,
            user_id=principal.user_id,
            organization_id=await service.submission_org(
                session, principal, problem, attempt_id=body.attempt_id
            ),
            problem=problem,
            language_key=body.language_key,
            mode="run",
            source_code=body.source_code,
            custom_input=body.custom_input,
            idempotency_key=request.headers[IDEM_HEADER],
        )
        pos = await service.queue_position(session, principal, sub)
        return IdemResult(body=service.accepted_body(sub, pos), status=202, resource_id=sub.id)

    return await idempotent(request, _nopg(session), user_id=principal.user_id, operation=op)


@router.post(
    "/coding/problems/{problem_id}/submit", status_code=202, openapi_extra={"x-td-idle": "engaged_only"}
)
async def submit_code(
    problem_id: uuid.UUID,
    body: SubmitIn,
    request: Request,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
) -> JSONResponse:
    replay = await _idem_exists(request, session, principal)
    problem = await service.published_problem(session, problem_id)
    if not replay:
        if body.attempt_id is not None:
            service.ensure_not_restricted(principal)
            service.ensure_source_size(body.source_code)
            validator = service._attempt_validator
            if validator is None:  # assessments module not wired yet: fail closed
                raise ProblemError(
                    "attempt_closed", detail="This attempt is not accepting coding submissions."
                )
            await validator(session, principal, body.attempt_id, problem.id)
            await service.language_or_422(session, problem, body.language_key)
        else:
            await service.precheck_practice(
                session,
                principal,
                problem,
                mode="submit",
                language_key=body.language_key,
                source_code=body.source_code,
            )

    async def op() -> IdemResult:
        sub = await service.create_submission(
            session,
            user_id=principal.user_id,
            organization_id=await service.submission_org(
                session, principal, problem, attempt_id=body.attempt_id
            ),
            problem=problem,
            language_key=body.language_key,
            mode="submit",
            source_code=body.source_code,
            idempotency_key=request.headers[IDEM_HEADER],
            attempt_id=body.attempt_id,
            practice_session_id=body.practice_session_id,
        )
        pos = await service.queue_position(session, principal, sub)
        return IdemResult(body=service.accepted_body(sub, pos), status=202, resource_id=sub.id)

    return await idempotent(request, _nopg(session), user_id=principal.user_id, operation=op)


@router.get("/coding/submissions/{submission_id}", openapi_extra={"x-td-idle": "neutral"})
async def get_submission(
    submission_id: uuid.UUID,
    request: Request,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
) -> dict[str, Any]:
    sub = (
        await (await _repo(session)).get_submission(submission_id)
        if _fs()
        else await session.get(CodeSubmission, submission_id)
    )
    if sub is None:
        raise ProblemError("not_found")
    staff_view = False
    if sub.user_id != principal.user_id:
        if not await has_permission(
            request, principal, "submission.code.read", scope_for(sub.organization_id)
        ) and not await _batch_reader(request, session, principal, sub):
            raise ProblemError("not_found")
        staff_view = True
        await audit(
            session,
            principal,
            "coding.submission.read",
            "code_submission",
            sub.id,
            organization_id=sub.organization_id,
            subject_user_id=sub.user_id,
        )
    view = await service.submission_view(session, sub, include_source=staff_view)
    return view.model_dump(mode="json")


async def _batch_reader(request: Request, session: Any, principal: Principal, sub: CodeSubmission) -> bool:
    """Batch-scoped ``submission.code.read`` (trainer, matrix cell B): only for a submission of
    an org-attributed learner who is an active member of a batch the caller holds it on."""
    if sub.organization_id is None:
        return False
    if _fs():
        return await _fs_batch_reader(request, session, principal, sub)
    from app.modules.orgs import public as orgs

    for g in principal.grants:
        if g.scope_type != "batch" or g.scope_id is None:
            continue
        b = await orgs.get_batch(session, g.scope_id)
        if b is None or b.organization_id != sub.organization_id:
            continue
        if not await orgs.batch_members(session, batch_ids=[g.scope_id], user_ids=[sub.user_id]):
            continue
        try:
            if await has_permission(
                request, principal, "submission.code.read", ScopeRef("batch", g.scope_id)
            ):
                return True
        except ProblemError:
            continue
    return False


async def _fs_batch_reader(request: Request, session: Any, principal: Principal, sub: CodeSubmission) -> bool:
    """``_batch_reader`` through ``orgs.public`` (same rule: an ``active`` member row of the grant's
    batch, the batch belonging to the submission's organization)."""
    from app.modules.orgs import public as orgs_public

    for g in principal.grants:
        if g.scope_type != "batch" or g.scope_id is None:
            continue
        members = await orgs_public.batch_members(
            session, batch_ids=[g.scope_id], user_ids=[sub.user_id], active_only=False
        )
        if not any(m.status == "active" for m in members):
            continue
        batch = await orgs_public.get_batch(session, g.scope_id)
        if batch is None or batch.organization_id != sub.organization_id:
            continue
        try:
            if await has_permission(
                request, principal, "submission.code.read", ScopeRef("batch", g.scope_id)
            ):
                return True
        except ProblemError:
            continue
    return False


@router.get("/me/coding/submissions", openapi_extra={"x-td-idle": "neutral"})
async def my_submissions(
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
    problem_id: uuid.UUID | None = None,
    mode: Annotated[str | None, Query(pattern="^(run|submit)$")] = None,
    cursor: str | None = None,
    limit: Limit = DEFAULT_LIMIT,
) -> dict[str, Any]:
    if _fs():
        before: uuid.UUID | None = None
        if cursor:
            try:
                before = uuid.UUID(str(decode_cursor(cursor)["id"]))
            except (KeyError, ValueError) as e:
                raise ProblemError("invalid_cursor") from e
        flt: list[Any] = []
        if problem_id:
            flt.append(("coding_problem_id", "==", str(problem_id)))
        if mode:
            flt.append(("mode", "==", mode))
        subs = sorted(
            (
                s
                for s in await (await _repo(session)).submissions_of(principal.user_id, flt)
                if before is None or s.id < before
            ),
            key=lambda s: s.id,
            reverse=True,
        )
        frows = subs[: limit + 1]
        fmore = len(frows) > limit
        frows = frows[:limit]
        return {
            "data": [service.history_item(s) for s in frows],
            "meta": page_meta({"id": str(frows[-1].id)} if fmore and frows else None, limit),
        }
    q = select(CodeSubmission).where(CodeSubmission.user_id == principal.user_id)
    if problem_id:
        q = q.where(CodeSubmission.coding_problem_id == problem_id)
    if mode:
        q = q.where(CodeSubmission.mode == mode)
    if cursor:
        try:
            q = q.where(CodeSubmission.id < uuid.UUID(str(decode_cursor(cursor)["id"])))
        except (KeyError, ValueError) as e:
            raise ProblemError("invalid_cursor") from e
    rows = list((await session.execute(q.order_by(CodeSubmission.id.desc()).limit(limit + 1))).scalars())
    more = len(rows) > limit
    rows = rows[:limit]
    return {
        "data": [service.history_item(s) for s in rows],
        "meta": page_meta({"id": str(rows[-1].id)} if more and rows else None, limit),
    }


# --------------------------------------------------------------------------- studio


async def _studio_problem(
    request: Request, session: Any, principal: Principal, problem_id: uuid.UUID
) -> CodingProblem:
    p = (
        await (await _repo(session)).get_problem(problem_id)
        if _fs()
        else await session.get(CodingProblem, problem_id)
    )
    if p is None:
        raise ProblemError("not_found")
    await check_permission(request, principal, "coding_problem.manage", scope_for(p.organization_id))
    return p


@router.post("/studio/coding/problems", status_code=201)
async def create_problem(
    body: ProblemCreateIn,
    request: Request,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
) -> dict[str, Any]:
    await check_permission(request, principal, "coding_problem.manage", scope_for(body.organization_id))
    p = await service.create_problem(session, principal, body)
    await audit(
        session,
        principal,
        "coding.problem.created",
        "coding_problem",
        p.id,
        organization_id=p.organization_id,
        after={"slug": p.slug, "version_no": p.version_no},
    )
    return service.problem_out(p, staff=True)


@router.get("/studio/coding/problems", openapi_extra={"x-td-idle": "neutral"})
async def studio_list_problems(
    request: Request,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
    status: Annotated[str | None, Query(pattern="^(draft|in_review|published|retired)$")] = None,
    q: Annotated[str | None, Query(min_length=1, max_length=100)] = None,
    cursor: str | None = None,
    limit: Limit = DEFAULT_LIMIT,
) -> dict[str, Any]:
    """Studio problem list (used by the web studio; not in the spec table). Rows visible under
    RLS (platform + own org) filtered to scopes where the caller holds
    ``coding_problem.manage``. Newest first."""
    rows, more = await service.studio_list_problems(
        session,
        status=status,
        q=q,
        after=_cursor_id(cursor),
        limit=limit,
        allowed=lambda org: has_permission(request, principal, "coding_problem.manage", scope_for(org)),
    )
    if not rows and not await _manages_anything(request, principal, session):
        raise ProblemError("permission_denied", permission="coding_problem.manage")
    counts = await service.test_case_counts(session, [p.id for p in rows])
    data = [service.studio_summary_out(p, counts.get(p.id, (0, 0))) for p in rows]
    return {"data": data, "meta": page_meta({"id": str(rows[-1].id)} if more and rows else None, limit)}


def _cursor_id(cursor: str | None) -> uuid.UUID | None:
    if not cursor:
        return None
    try:
        return uuid.UUID(str(decode_cursor(cursor)["id"]))
    except (KeyError, ValueError) as e:
        raise ProblemError("invalid_cursor") from e


async def _manages_anything(request: Request, principal: Principal, session: Any) -> bool:
    """403 vs empty list: the caller must hold ``coding_problem.manage`` at platform scope or in
    one of their organizations."""
    from app.core.auth import PLATFORM_SCOPE, ScopeRef

    scopes = [PLATFORM_SCOPE, *(ScopeRef("organization", o) for o in principal.org_ids)]
    for s in scopes:
        try:
            if await has_permission(request, principal, "coding_problem.manage", s):
                return True
        except ProblemError:
            continue
    return False


@router.get(
    "/studio/coding/problems/published",
    operation_id="cod_24_studio_published_problems",
    openapi_extra={"x-td-idle": "neutral"},
)
async def studio_published_problems(
    request: Request,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
    q: Annotated[str | None, Query(min_length=1, max_length=100)] = None,
    cursor: str | None = None,
    limit: Limit = DEFAULT_LIMIT,
) -> dict[str, Any]:
    """Read-only picker of published coding problems for test builders (w3be; web test builder
    coding sections). Open to callers who can author tests (``test.create``) at platform scope,
    in one of their organizations, or through a batch grant (trainers). Lists the published
    problems visible under RLS (platform bank + the caller's organizations); organization
    problems only where the caller can author tests for that organization. Metadata only:
    no statements, test cases or solutions. Newest first."""
    from app.modules.placement.policies import can_in_org

    can: dict[uuid.UUID | None, bool] = {}

    async def allowed(org: uuid.UUID | None) -> bool:
        if org not in can:
            can[org] = await can_in_org(request, session, principal, "test.create", org)
        return can[org]

    author_anywhere = False
    for org in (None, *principal.org_ids):
        try:
            if await allowed(org):
                author_anywhere = True
                break
        except ProblemError:
            continue
    if not author_anywhere:
        raise ProblemError("permission_denied", permission="test.create")

    async def visible(org: uuid.UUID | None) -> bool:
        return org is None or await allowed(org)

    rows, more = await service.studio_list_problems(
        session, status="published", q=q, after=_cursor_id(cursor), limit=limit, allowed=visible
    )
    data = [
        {
            "problem_id": str(p.id),
            "slug": p.slug,
            "title": p.title,
            "difficulty": p.difficulty,
            "version_no": p.version_no,
            "organization_id": str(p.organization_id) if p.organization_id else None,
        }
        for p in rows
    ]
    return {"data": data, "page": page_meta({"id": str(rows[-1].id)} if more and rows else None, limit)}


@router.get("/studio/coding/problems/{problem_id}")
async def studio_get_problem(
    problem_id: uuid.UUID,
    request: Request,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
) -> dict[str, Any]:
    p = await _studio_problem(request, session, principal, problem_id)
    out = service.problem_out(p, staff=True)
    out.update(service.studio_compat_fields(p, (await service.test_case_counts(session, [p.id])).get(p.id)))
    return out


@router.patch("/studio/coding/problems/{problem_id}")
async def patch_problem(
    problem_id: uuid.UUID,
    body: ProblemPatchIn,
    request: Request,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
) -> dict[str, Any]:
    p = await _studio_problem(request, session, principal, problem_id)
    before = p.version_no
    changed = await service.patch_problem(session, p, body)
    if changed:
        await audit(
            session,
            principal,
            "coding.problem.updated",
            "coding_problem",
            p.id,
            organization_id=p.organization_id,
            before={"version_no": before},
            after={"fields": sorted(changed), "version_no": p.version_no},
        )
    return service.problem_out(p, staff=True)


@router.post("/studio/coding/problems/{problem_id}/test-cases", status_code=201)
async def add_test_case(
    problem_id: uuid.UUID,
    body: TestCaseIn,
    request: Request,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
) -> dict[str, Any]:
    p = await _studio_problem(request, session, principal, problem_id)
    if body.kind == "hidden":
        await check_permission(
            request, principal, "coding_test_case.hidden.read", scope_for(p.organization_id)
        )
    case = await service.add_test_case(session, p, body)
    await audit(
        session,
        principal,
        "coding.testcase.created",
        "coding_test_case",
        case.id,
        organization_id=p.organization_id,
        after={
            "problem_id": str(p.id),
            "kind": body.kind,
            "ordinal": case.ordinal,
            "problem_version": case.problem_version,
        },
    )
    out = service.case_meta_out(case).model_dump(mode="json")
    out["problem_version"] = case.problem_version
    return out


@router.get("/studio/coding/problems/{problem_id}/test-cases")
async def list_test_cases(
    problem_id: uuid.UUID,
    request: Request,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
) -> dict[str, Any]:
    p = await _studio_problem(request, session, principal, problem_id)
    cases = await service.list_cases(session, p)
    return {
        "problem_version": p.version_no,
        "data": [service.case_meta_out(c).model_dump(mode="json") for c in cases],
    }


@router.post("/studio/coding/problems/{problem_id}/publish")
async def publish_problem(
    problem_id: uuid.UUID,
    request: Request,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
) -> dict[str, Any]:
    p = await _studio_problem(request, session, principal, problem_id)
    await service.publish_problem(session, principal, p)
    await audit(
        session,
        principal,
        "coding.problem.published",
        "coding_problem",
        p.id,
        organization_id=p.organization_id,
        after={"version_no": p.version_no},
    )
    return service.problem_out(p, staff=True)


# --------------------------------------------------------------------------- drafts (COD-04/05)

LanguagePath = Annotated[str, Path(min_length=1, max_length=32, pattern=r"^[a-z][a-z0-9_]{0,31}$")]


@router.put(
    "/coding/problems/{problem_id}/drafts/{language_key}", openapi_extra={"x-td-idle": "engaged_only"}
)
async def save_draft(
    problem_id: uuid.UUID,
    language_key: LanguagePath,
    body: DraftIn,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
    attempt_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    """COD-04: owner-only autosave (≤ 64 KiB, 20/min). Entitlement as for run/submit (BE-20);
    ``attempt_id`` = reached through the learner's in-progress attempt."""
    problem = await service.published_problem(session, problem_id)
    await service.require_problem_access(session, principal, problem, attempt_id=attempt_id)
    d = await authoring.save_draft(session, principal, problem, language_key, body.source_code)
    return authoring.draft_out(d)


@router.get("/coding/problems/{problem_id}/drafts/{language_key}", openapi_extra={"x-td-idle": "neutral"})
async def get_draft(
    problem_id: uuid.UUID,
    language_key: LanguagePath,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
    attempt_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    """COD-05: the caller's own draft (404 when none). Entitlement as for run/submit (BE-20)."""
    problem = await service.published_problem(session, problem_id)
    await service.require_problem_access(session, principal, problem, attempt_id=attempt_id)
    return authoring.draft_out(await authoring.get_draft(session, principal, problem_id, language_key))


# --------------------------------------------------------------------------- validate (COD-18)


@router.get("/studio/coding/problems/{problem_id}/reference-solutions")
async def list_reference_solutions(
    problem_id: uuid.UUID,
    request: Request,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
) -> dict[str, Any]:
    p = await _studio_problem(request, session, principal, problem_id)
    rows = await authoring.list_reference_solutions(session, p)
    return {"data": [authoring.reference_out(r) for r in rows]}


@router.put("/studio/coding/problems/{problem_id}/reference-solutions/{language_key}")
async def put_reference_solution(
    problem_id: uuid.UUID,
    language_key: LanguagePath,
    body: ReferenceSolutionIn,
    request: Request,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
) -> dict[str, Any]:
    p = await _studio_problem(request, session, principal, problem_id)
    r = await authoring.put_reference_solution(session, principal, p, language_key, body.source_code)
    await audit(
        session,
        principal,
        "coding.reference_solution.saved",
        "coding_problem",
        p.id,
        organization_id=p.organization_id,
        after={"language_key": language_key, "size_bytes": len(body.source_code.encode("utf-8"))},
    )
    return authoring.reference_out(r, include_source=False)


@router.post("/studio/coding/problems/{problem_id}/validate")
async def validate_problem(
    problem_id: uuid.UUID,
    request: Request,
    session: PrincipalDbSession,
    body: ValidateIn | None = None,
    principal: Principal = Depends(require_active_principal),
) -> JSONResponse:
    """COD-18: run the reference solution(s) on every case of the current version (samples and
    hidden) through the judge gateway. Results carry verdict/time/memory per case only."""
    p = await _studio_problem(request, session, principal, problem_id)
    sols = [(s.language_key, s.source_code) for s in (body.reference_solutions or [])] if body else None

    async def op() -> IdemResult:
        v = await authoring.validate_problem(session, principal, p, sols)
        await audit(
            session,
            principal,
            "coding.problem.validated",
            "coding_problem",
            p.id,
            organization_id=p.organization_id,
            after={"version_no": p.version_no, "status": v.status, "validation_id": str(v.id)},
        )
        return IdemResult(body=authoring.validation_out(v, v.fingerprint), status=200, resource_id=v.id)

    return await idempotent(request, _nopg(session), user_id=principal.user_id, operation=op, required=False)


@router.get("/studio/coding/problems/{problem_id}/validation")
async def latest_validation(
    problem_id: uuid.UUID,
    request: Request,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
) -> dict[str, Any]:
    p = await _studio_problem(request, session, principal, problem_id)
    v = await authoring.latest_validation(session, p.id)
    if v is None:
        raise ProblemError("not_found")
    return authoring.validation_out(v, await authoring.current_fingerprint(session, p))


# --------------------------------------------------------------------------- hidden content (COD-17)

NO_STORE = {"Cache-Control": "no-store", "Pragma": "no-cache"}


@router.get("/studio/coding/test-cases/{test_case_id}/content")
async def hidden_case_content(
    test_case_id: uuid.UUID,
    request: Request,
    session: PrincipalDbSession,
    reason: Annotated[str | None, Query(max_length=500)] = None,
    principal: Principal = Depends(require_active_principal),
) -> JSONResponse:
    """COD-17: short-lived (5 min), single-use, user-bound download links for one hidden case.
    Requires ``coding_test_case.hidden.read`` on the problem's scope, a fresh staff step-up
    (S10) and a reason (>= 10 chars); 30 requests/hour; audited ``coding.testcase.read_hidden``."""
    if _fs():
        frepo = await _repo(session)
        case = await frepo.get_case(test_case_id)
        if case is None:
            raise ProblemError("not_found")
        p = await frepo.get_problem(case.coding_problem_id)
    else:
        case = await session.get(CodingTestCase, test_case_id)
        if case is None:
            raise ProblemError("not_found")
        p = await session.get(CodingProblem, case.coding_problem_id)
    if p is None:
        raise ProblemError("not_found")
    await check_permission(request, principal, "coding_test_case.hidden.read", scope_for(p.organization_id))
    text_reason = (reason or "").strip()
    if len(text_reason) < 10:
        raise ProblemError(
            "validation_failed",
            errors=[
                {"field": "reason", "code": "too_short", "message": "Give a reason (at least 10 characters)."}
            ],
        )
    if not case.is_hidden:
        raise ProblemError(
            "validation_failed",
            errors=[
                {"field": "test_case_id", "code": "not_hidden", "message": "Sample cases are listed inline."}
            ],
        )
    await require_step_up("staff")(principal)
    out = await authoring.issue_content_tokens(session, principal, case, text_reason)
    await audit(
        session,
        principal,
        "coding.testcase.read_hidden",
        "coding_test_case",
        case.id,
        organization_id=case.organization_id,
        reason=text_reason,
        after={"problem_id": str(p.id), "ordinal": case.ordinal, "request_id": out["request_id"]},
    )
    return JSONResponse(out, headers=NO_STORE)


@router.get("/studio/coding/test-cases/content-downloads/{token}")
async def hidden_case_download(
    token: Annotated[str, Path(min_length=16, max_length=128)],
    request: Request,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
) -> Response:
    """Redeem a COD-17 token: same user, unexpired, single use; permission re-checked."""
    row, case = await authoring.redeem_content_token(session, principal, token)
    try:
        await check_permission(
            request, principal, "coding_test_case.hidden.read", scope_for(case.organization_id)
        )
    except ProblemError as e:
        raise ProblemError("not_found") from e
    content = await authoring.decrypt_part(session, case, row.part)
    await audit(
        session,
        principal,
        "coding.testcase.hidden_downloaded",
        "coding_test_case",
        case.id,
        organization_id=case.organization_id,
        after={"part": row.part, "request_id": str(row.request_id)},
    )
    return Response(
        content=content.encode("utf-8"),
        media_type="text/plain; charset=utf-8",
        headers={
            **NO_STORE,
            "Content-Disposition": f'attachment; filename="case-{case.ordinal}-{row.part}.txt"',
            "X-Content-Type-Options": "nosniff",
        },
    )
