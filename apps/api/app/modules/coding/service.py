"""Coding service: authoring, submission intake, views, assessments interface.

Nothing here executes code or decrypts hidden cases. Judging happens in ``worker.py``.

Queueing (ADR-0008 / architecture §9.4): Postgres is the durable queue — a submission is
``status='queued'`` with ``queue_name`` in (``judge_assessment`` > ``judge_submit`` >
``judge_run``). The judge worker claims rows with ``FOR UPDATE SKIP LOCKED``. Only when
``TD_CODING_SEND_TASKS=1`` (a ``judge_*`` Celery consumer is deployed) does ``tasks.py`` also push
a wake-up task; the DB row remains the source of truth either way (COM-09).

Assessments interface (for the assessments module; no assessments code is touched here)::

    from app.modules.coding.service import judge_for_attempt, get_attempt_judgement

    handle = await judge_for_attempt(
        session,                     # the assessments request transaction (student RLS context)
        user_id=..., organization_id=..., attempt_id=..., problem_id=...,
        language_key="python3", source_code="...", idempotency_key="<client key>",
    )  # -> AttemptSubmissionHandle(submission_id, status, queue, problem_version)
    j = await get_attempt_judgement(session, handle.submission_id)
    # -> AttemptJudgement(status, verdict, score, max_score, passed_cases, total_cases) | None

The caller MUST have validated the attempt (in progress, bound to this session, contains the
problem) — that is assessments' domain. Entitlement and per-minute limits are not applied to
attempt submissions (they are never shed, queue ``judge_assessment``). The assessments module
may also ``register_attempt_validator`` so COD-07 with ``attempt_id`` works; until then such
requests fail closed with ``409 attempt_closed``.
"""

from __future__ import annotations

import hashlib
import re
import uuid
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import and_, func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.access import require_access
from app.core.company import COMPANY_ORG_ID
from app.core.db import system_context
from app.core.errors import ProblemError
from app.core.firestore.backend import uses_firestore
from app.core.ids import uuid7
from app.core.principal import Principal
from app.core.time import to_rfc3339, utcnow
from app.modules.coding import blobstore, crypto
from app.modules.coding.judge_gateway import provider_name
from app.modules.coding.models import (
    CodeSubmission,
    CodingProblem,
    CodingTestCase,
    JudgeLanguage,
    SubmissionResult,
)
from app.modules.coding.schemas import (
    MAX_SOURCE_BYTES,
    HiddenCaseMetaOut,
    HiddenCaseResultOut,
    ProblemCreateIn,
    ProblemPatchIn,
    SampleCaseMetaOut,
    SampleCaseResultOut,
    SubmissionOut,
    TestCaseIn,
)

# Policy defaults (PRD FR-COD-005; runtime policy keys coding.* may override later).
RUN_PER_MINUTE = 10
SUBMIT_PER_MINUTE = 5
MAX_INFLIGHT_SUBMITS = 1
INFLIGHT_STALE_MINUTES = 15
RUN_QUEUE_MAX = 200
STDOUT_EXCERPT_BYTES = 4096
RESTRICTION_BLOCK_LEVEL = 3

QUEUE_FOR_MODE = {"run": "judge_run", "submit": "judge_submit"}


def _fs() -> bool:
    """``TD_STORE_CODING=firestore``: dispatch to ``repo_firestore`` (same results)."""
    return uses_firestore("coding")


async def _repo(session: AsyncSession | None) -> Any:
    from app.modules.coding import repo_firestore

    return await repo_firestore.repo(session)


VERSIONED_FIELDS = frozenset(
    {"time_limit_ms", "wall_limit_ms", "memory_limit_kb", "checker_type", "checker_config", "scoring_mode"}
)


# --------------------------------------------------------------------------- helpers


def problem_out(p: CodingProblem, *, staff: bool = False) -> dict[str, Any]:
    out: dict[str, Any] = {
        "problem_id": str(p.id),
        "slug": p.slug,
        "title": p.title,
        "version_no": p.version_no,
        "statement_md": p.statement_md,
        "input_format_md": p.input_format_md,
        "output_format_md": p.output_format_md,
        "constraints_md": p.constraints_md,
        "difficulty": p.difficulty,
        "limits": {
            "time_limit_ms": p.time_limit_ms,
            "wall_limit_ms": p.wall_limit_ms,
            "memory_limit_kb": p.memory_limit_kb,
        },
        "allowed_languages": list(p.allowed_languages),
        "scoring_mode": p.scoring_mode,
        "is_free": p.is_free,
    }
    if staff:
        out.update(
            {
                "status": p.status,
                "organization_id": str(p.organization_id) if p.organization_id else None,
                "checker_type": p.checker_type,
                "checker_config": p.checker_config,
                "created_by": str(p.created_by),
            }
        )
    return out


def _excerpt(s: str | None, limit: int = STDOUT_EXCERPT_BYTES) -> str | None:
    if s is None:
        return None
    b = s.encode("utf-8")
    if len(b) <= limit:
        return s
    return b[:limit].decode("utf-8", errors="ignore")


def ensure_source_size(source_code: str, custom_input: str | None = None) -> None:
    if len(source_code.encode("utf-8")) > MAX_SOURCE_BYTES:
        raise ProblemError(
            "payload_too_large", detail="Source code is limited to 64 KiB.", limit_bytes=MAX_SOURCE_BYTES
        )
    if custom_input is not None and len(custom_input.encode("utf-8")) > MAX_SOURCE_BYTES:
        raise ProblemError(
            "payload_too_large", detail="Custom input is limited to 64 KiB.", limit_bytes=MAX_SOURCE_BYTES
        )


def ensure_not_restricted(principal: Principal) -> None:
    """Restriction >= L3 blocks run and submit (security doc §7.6)."""
    if principal.restriction_level >= RESTRICTION_BLOCK_LEVEL or "coding_locked" in principal.restrictions:
        raise ProblemError(
            "account_restricted", level=principal.restriction_level, status_url="/app/account-status"
        )


# --------------------------------------------------------------------------- plagiarism hook

_C_COMMENTS = re.compile(r"//[^\n]*|/\*.*?\*/", re.S)
_PY_COMMENTS = re.compile(r"#[^\n]*")
_WS = re.compile(r"\s+")


def normalize_source(language_key: str, source: str) -> str:
    """Comment/whitespace-insensitive form used for exact-copy detection. The cohort
    similarity job (MOSS/JPlag-style, COD-21/22) is Planned and will consume these hashes."""
    s = source.replace("\r\n", "\n")
    s = _PY_COMMENTS.sub("", s) if language_key.startswith("python") else _C_COMMENTS.sub("", s)
    return _WS.sub(" ", s).strip()


def normalized_hash(language_key: str, source: str) -> bytes:
    return hashlib.sha256(normalize_source(language_key, source).encode("utf-8")).digest()


async def similarity_candidates(session: AsyncSession, submission: CodeSubmission) -> list[uuid.UUID]:
    """Placeholder for the similarity job: other users' submit-mode submissions on the same
    problem with an identical normalized hash (caller provides a system/staff context)."""
    if submission.normalized_sha256 is None:
        return []
    if _fs():
        from app.modules.coding.fsmap import to_doc_value

        h = to_doc_value(CodeSubmission.__table__.c.normalized_sha256, submission.normalized_sha256)
        subs = await (await _repo(session)).all_submissions(
            (
                ("coding_problem_id", "==", str(submission.coding_problem_id)),
                ("mode", "==", "submit"),
                ("normalized_sha256", "==", h),
            )
        )
        return [s.id for s in subs if s.user_id != submission.user_id]
    rows = await session.execute(
        select(CodeSubmission.id).where(
            CodeSubmission.coding_problem_id == submission.coding_problem_id,
            CodeSubmission.mode == "submit",
            CodeSubmission.normalized_sha256 == submission.normalized_sha256,
            CodeSubmission.user_id != submission.user_id,
        )
    )
    return list(rows.scalars())


# --------------------------------------------------------------------------- languages


async def enabled_languages(session: AsyncSession) -> list[JudgeLanguage]:
    if _fs():
        langs = await (await _repo(session)).languages()
        from app.core.firestore.collation import sort_key

        return sorted((x for x in langs if x.is_enabled), key=lambda x: sort_key(x.language_key))
    rows = await session.execute(
        select(JudgeLanguage).where(JudgeLanguage.is_enabled.is_(True)).order_by(JudgeLanguage.language_key)
    )
    return list(rows.scalars())


async def _language(session: AsyncSession, key: str) -> JudgeLanguage | None:
    if _fs():
        return next((x for x in await (await _repo(session)).languages() if x.language_key == key), None)
    return (
        await session.execute(select(JudgeLanguage).where(JudgeLanguage.language_key == key))
    ).scalar_one_or_none()


async def language_or_422(session: AsyncSession, problem: CodingProblem, key: str) -> JudgeLanguage:
    lang = await _language(session, key)
    if lang is None or not lang.is_enabled or key not in problem.allowed_languages:
        raise ProblemError("language_not_allowed", language_key=key, allowed=list(problem.allowed_languages))
    return lang


# --------------------------------------------------------------------------- problems (student)


async def get_problem(session: AsyncSession, problem_id: uuid.UUID) -> CodingProblem:
    if _fs():
        fp = await (await _repo(session)).get_problem(problem_id)
        if fp is None:
            raise ProblemError("not_found")
        return fp
    p = await session.get(CodingProblem, problem_id)
    if p is None:
        raise ProblemError("not_found")
    return p


async def published_problem(session: AsyncSession, problem_id: uuid.UUID) -> CodingProblem:
    p = await get_problem(session, problem_id)
    if p.status != "published":
        raise ProblemError("not_found")
    return p


async def published_by_slug(session: AsyncSession, slug: str) -> CodingProblem:
    if _fs():
        found = [
            p for p in await (await _repo(session)).problems_by_slug(slug.lower()) if p.status == "published"
        ]
    else:
        rows = await session.execute(
            select(CodingProblem).where(
                CodingProblem.slug == slug.lower(), CodingProblem.status == "published"
            )
        )
        found = list(rows.scalars())
    if not found:
        raise ProblemError("not_found")
    # Org-specific copy wins over the global one with the same slug.
    found.sort(key=lambda p: p.organization_id is None)
    return found[0]


async def sample_cases(session: AsyncSession, problem: CodingProblem) -> list[CodingTestCase]:
    if _fs():
        return [c for c in await list_cases(session, problem) if c.is_sample]
    rows = await session.execute(
        select(CodingTestCase)
        .where(
            CodingTestCase.coding_problem_id == problem.id,
            CodingTestCase.problem_version == problem.version_no,
            CodingTestCase.is_sample.is_(True),
        )
        .order_by(CodingTestCase.ordinal)
    )
    return list(rows.scalars())


async def require_problem_access(
    session: AsyncSession,
    principal: Principal,
    problem: CodingProblem,
    *,
    attempt_id: uuid.UUID | None = None,
) -> None:
    """Entitlement gate for a problem. With ``attempt_id`` the problem is reached through a
    test: the learner's in-progress, session-bound attempt must contain it (assessments
    validator; fails closed when not wired) and no standalone entitlement is needed."""
    if attempt_id is not None:
        validator = _attempt_validator
        if validator is None:
            raise ProblemError("attempt_closed", detail="This attempt is not accepting coding submissions.")
        await validator(session, principal, attempt_id, problem.id)
        return
    for grant in _access_grants:  # e.g. learning: the problem is in the learner's open assignment
        if await grant(session, principal, problem.id):
            return
    await require_access(session, principal, "coding_problem", problem.id, is_free=problem.is_free)


async def problem_by_slug_or_id(session: AsyncSession, ref: str) -> CodingProblem:
    """COD-03 path value: a slug, or the problem id (test items deliver ``coding_problem_id``)."""
    try:
        pid = uuid.UUID(ref)
    except ValueError:
        return await published_by_slug(session, ref)
    return await published_problem(session, pid)


# --------------------------------------------------------------------------- authoring (studio)


async def create_problem(session: AsyncSession, principal: Principal, body: ProblemCreateIn) -> CodingProblem:
    if _fs():
        await _check_languages_exist(session, body.allowed_languages)
        return await (await _repo(session)).create_problem(_new_problem(principal, body))
    dup = await session.execute(
        select(CodingProblem.id).where(
            CodingProblem.slug == body.slug,
            CodingProblem.organization_id.is_(None)
            if body.organization_id is None
            else CodingProblem.organization_id == body.organization_id,
        )
    )
    if dup.first() is not None:
        raise ProblemError(
            "validation_failed",
            errors=[{"field": "slug", "code": "duplicate", "message": "A problem with this slug exists."}],
        )
    await _check_languages_exist(session, body.allowed_languages)
    p = CodingProblem(
        id=uuid7(),
        organization_id=body.organization_id,
        slug=body.slug,
        title=body.title,
        version_no=1,
        statement_md=body.statement_md,
        input_format_md=body.input_format_md,
        output_format_md=body.output_format_md,
        constraints_md=body.constraints_md,
        difficulty=body.difficulty,
        time_limit_ms=body.time_limit_ms,
        wall_limit_ms=body.wall_limit_ms or 5000,
        memory_limit_kb=body.memory_limit_kb,
        allowed_languages=list(dict.fromkeys(body.allowed_languages)),
        checker_type=body.checker_type,
        checker_config=body.checker_config,
        scoring_mode=body.scoring_mode,
        status="draft",
        is_free=body.is_free,
        created_by=principal.user_id,
    )
    session.add(p)
    await session.flush()
    return p


def _new_problem(principal: Principal, body: ProblemCreateIn) -> CodingProblem:
    """The row ``create_problem`` inserts (Firestore path; same values as the Postgres path)."""
    return CodingProblem(
        id=uuid7(),
        organization_id=body.organization_id,
        slug=body.slug,
        title=body.title,
        version_no=1,
        statement_md=body.statement_md,
        input_format_md=body.input_format_md,
        output_format_md=body.output_format_md,
        constraints_md=body.constraints_md,
        difficulty=body.difficulty,
        time_limit_ms=body.time_limit_ms,
        wall_limit_ms=body.wall_limit_ms or 5000,
        memory_limit_kb=body.memory_limit_kb,
        allowed_languages=list(dict.fromkeys(body.allowed_languages)),
        checker_type=body.checker_type,
        checker_config=body.checker_config,
        scoring_mode=body.scoring_mode,
        status="draft",
        is_free=body.is_free,
        created_by=principal.user_id,
    )


async def _check_languages_exist(session: AsyncSession, keys: Sequence[str]) -> None:
    if _fs():
        known = {x.language_key for x in await (await _repo(session)).languages()}
    else:
        known = set((await session.execute(select(JudgeLanguage.language_key))).scalars())
    unknown = sorted(set(keys) - known)
    if unknown:
        raise ProblemError(
            "validation_failed",
            errors=[
                {"field": "allowed_languages", "code": "unknown", "message": f"Unknown: {', '.join(unknown)}"}
            ],
        )


def _copy_case(c: CodingTestCase, new: int) -> CodingTestCase:
    return CodingTestCase(
        id=uuid7(),
        coding_problem_id=c.coding_problem_id,
        organization_id=c.organization_id,
        problem_version=new,
        ordinal=c.ordinal,
        is_sample=c.is_sample,
        is_hidden=c.is_hidden,
        weight=c.weight,
        sample_input=c.sample_input,
        sample_output=c.sample_output,
        input_s3_key=c.input_s3_key,
        expected_s3_key=c.expected_s3_key,
        wrapped_data_key=c.wrapped_data_key,
        input_sha256=c.input_sha256,
        expected_sha256=c.expected_sha256,
        size_bytes=c.size_bytes,
    )


async def _fs_bump_copies(session: AsyncSession, p: CodingProblem) -> list[CodingTestCase]:
    """Firestore ``_bump_version``: the copies of the current version's cases (written with the
    problem by ``repo.save_problem``) and ``p.version_no`` advanced in memory."""
    old = p.version_no
    copies = [_copy_case(c, old + 1) for c in await (await _repo(session)).cases(p.id, old)]
    p.version_no = old + 1
    return copies


async def _bump_version(session: AsyncSession, p: CodingProblem) -> None:
    """New immutable version: copy the current version's cases (ciphertext refs are shared;
    AAD is bound to the problem id, not the version)."""
    old = p.version_no
    new = old + 1
    rows = await session.execute(
        select(CodingTestCase).where(
            CodingTestCase.coding_problem_id == p.id, CodingTestCase.problem_version == old
        )
    )
    for c in rows.scalars():
        session.add(
            CodingTestCase(
                id=uuid7(),
                coding_problem_id=p.id,
                organization_id=c.organization_id,
                problem_version=new,
                ordinal=c.ordinal,
                is_sample=c.is_sample,
                is_hidden=c.is_hidden,
                weight=c.weight,
                sample_input=c.sample_input,
                sample_output=c.sample_output,
                input_s3_key=c.input_s3_key,
                expected_s3_key=c.expected_s3_key,
                wrapped_data_key=c.wrapped_data_key,
                input_sha256=c.input_sha256,
                expected_sha256=c.expected_sha256,
                size_bytes=c.size_bytes,
            )
        )
    p.version_no = new
    await session.flush()


async def patch_problem(session: AsyncSession, p: CodingProblem, body: ProblemPatchIn) -> list[str]:
    changes = body.model_dump(exclude_unset=True)
    if "allowed_languages" in changes and changes["allowed_languages"] is not None:
        await _check_languages_exist(session, changes["allowed_languages"])
        changes["allowed_languages"] = list(dict.fromkeys(changes["allowed_languages"]))
    for k in (
        "title",
        "statement_md",
        "difficulty",
        "time_limit_ms",
        "wall_limit_ms",
        "memory_limit_kb",
        "allowed_languages",
        "checker_type",
        "scoring_mode",
        "is_free",
    ):
        if k in changes and changes[k] is None:
            raise ProblemError(
                "validation_failed", errors=[{"field": k, "code": "required", "message": "Cannot be null."}]
            )
    tl = changes.get("time_limit_ms", p.time_limit_ms)
    wl = changes.get("wall_limit_ms", p.wall_limit_ms)
    if wl < tl:
        raise ProblemError(
            "validation_failed",
            errors=[{"field": "wall_limit_ms", "code": "too_small", "message": "Must be >= time_limit_ms."}],
        )
    changed = [k for k, v in changes.items() if getattr(p, k) != v]
    if _fs():
        expect = p.version_no
        copies: list[CodingTestCase] = []
        if p.status != "draft" and VERSIONED_FIELDS.intersection(changed):
            copies = await _fs_bump_copies(session, p)
        for k in changed:
            setattr(p, k, changes[k])
        fields = [*changed, "version_no"] if p.version_no != expect else list(changed)
        if fields:
            await (await _repo(session)).save_problem(p, fields, expect_version=expect, new_cases=copies)
        return changed
    if p.status != "draft" and VERSIONED_FIELDS.intersection(changed):
        await _bump_version(session, p)
    for k in changed:
        setattr(p, k, changes[k])
    await session.flush()
    return changed


async def add_test_case(session: AsyncSession, p: CodingProblem, body: TestCaseIn) -> CodingTestCase:
    if p.status not in ("draft", "in_review", "published"):
        raise ProblemError("invalid_state_transition", detail="Retired problems cannot change.")
    if _fs():
        return await _fs_add_test_case(session, p, body)
    if p.status != "draft":
        await _bump_version(session, p)
    max_ord = (
        await session.execute(
            select(func.coalesce(func.max(CodingTestCase.ordinal), 0)).where(
                CodingTestCase.coding_problem_id == p.id, CodingTestCase.problem_version == p.version_no
            )
        )
    ).scalar_one()
    case = CodingTestCase(
        id=uuid7(),
        coding_problem_id=p.id,
        organization_id=p.organization_id,
        problem_version=p.version_no,
        ordinal=int(max_ord) + 1,
        is_sample=body.kind == "sample",
        is_hidden=body.kind == "hidden",
        weight=body.weight,
    )
    if body.kind == "sample":
        case.sample_input = body.input
        case.sample_output = body.expected_output
        case.size_bytes = len(body.input.encode()) + len(body.expected_output.encode())
    else:
        sealed = crypto.seal_case(p.id, body.input, body.expected_output)
        case.input_s3_key = await blobstore.put_blob(
            session, problem_id=p.id, organization_id=p.organization_id, ciphertext=sealed.input_blob
        )
        case.expected_s3_key = await blobstore.put_blob(
            session, problem_id=p.id, organization_id=p.organization_id, ciphertext=sealed.expected_blob
        )
        case.wrapped_data_key = sealed.wrapped_data_key
        case.input_sha256 = sealed.input_sha256
        case.expected_sha256 = sealed.expected_sha256
        case.size_bytes = sealed.size_bytes
    session.add(case)
    await session.flush()
    return case


async def _fs_add_test_case(session: AsyncSession, p: CodingProblem, body: TestCaseIn) -> CodingTestCase:
    """Firestore ``add_test_case``: same row values; the version bump (problem + copied cases)
    and the new case commit in one transaction (``repo.save_problem``)."""
    expect = p.version_no
    copies = await _fs_bump_copies(session, p) if p.status != "draft" else []
    current = copies if p.version_no != expect else await (await _repo(session)).cases(p.id, p.version_no)
    case = CodingTestCase(
        id=uuid7(),
        coding_problem_id=p.id,
        organization_id=p.organization_id,
        problem_version=p.version_no,
        ordinal=max((c.ordinal for c in current), default=0) + 1,
        is_sample=body.kind == "sample",
        is_hidden=body.kind == "hidden",
        weight=body.weight,
    )
    if body.kind == "sample":
        case.sample_input = body.input
        case.sample_output = body.expected_output
        case.size_bytes = len(body.input.encode()) + len(body.expected_output.encode())
    else:
        sealed = crypto.seal_case(p.id, body.input, body.expected_output)
        case.input_s3_key = await blobstore.put_blob(
            session, problem_id=p.id, organization_id=p.organization_id, ciphertext=sealed.input_blob
        )
        case.expected_s3_key = await blobstore.put_blob(
            session, problem_id=p.id, organization_id=p.organization_id, ciphertext=sealed.expected_blob
        )
        case.wrapped_data_key = sealed.wrapped_data_key
        case.input_sha256 = sealed.input_sha256
        case.expected_sha256 = sealed.expected_sha256
        case.size_bytes = sealed.size_bytes
    await (await _repo(session)).save_problem(
        p, ["version_no"] if p.version_no != expect else [], expect_version=expect, new_cases=[*copies, case]
    )
    return case


async def list_cases(session: AsyncSession, p: CodingProblem) -> list[CodingTestCase]:
    if _fs():
        return await (await _repo(session)).cases(p.id, p.version_no)
    rows = await session.execute(
        select(CodingTestCase)
        .where(CodingTestCase.coding_problem_id == p.id, CodingTestCase.problem_version == p.version_no)
        .order_by(CodingTestCase.ordinal)
    )
    return list(rows.scalars())


def case_meta_out(c: CodingTestCase) -> SampleCaseMetaOut | HiddenCaseMetaOut:
    if c.is_sample:
        return SampleCaseMetaOut(
            test_case_id=c.id,
            ordinal=c.ordinal,
            weight=float(c.weight),
            input=c.sample_input or "",
            expected_output=c.sample_output or "",
        )
    return HiddenCaseMetaOut(
        test_case_id=c.id,
        ordinal=c.ordinal,
        weight=float(c.weight),
        size_bytes=c.size_bytes,
        input_sha256=c.input_sha256.hex() if c.input_sha256 else None,
        expected_sha256=c.expected_sha256.hex() if c.expected_sha256 else None,
    )


async def publish_problem(session: AsyncSession, principal: Principal, p: CodingProblem) -> None:
    if p.status == "published":
        raise ProblemError("invalid_state_transition", detail="Already published.")
    if p.status == "retired":
        raise ProblemError("invalid_state_transition", detail="Retired problems cannot be published.")
    cases = await list_cases(session, p)
    if not any(c.is_sample for c in cases) or not any(c.is_hidden for c in cases):
        raise ProblemError(
            "invalid_state_transition",
            detail="Add at least one sample and one hidden test case before publishing.",
        )
    if p.organization_id is None and p.created_by == principal.user_id:
        raise ProblemError(
            "sod_violation", detail="Platform problems must be published by a reviewer, not the author."
        )
    from app.modules.coding.authoring import has_passing_validation  # cycle: authoring imports service

    if not await has_passing_validation(session, p):
        raise ProblemError(
            "invalid_state_transition",
            detail="Validate the reference solution against every test case of this version first.",
            reason="validation_required",
        )
    p.status = "published"
    p.published_by = principal.user_id
    p.published_at = utcnow()
    if _fs():
        await (await _repo(session)).save_problem(
            p, ["status", "published_by", "published_at"], expect_version=p.version_no
        )
        return
    await session.flush()


# --------------------------------------------------------------------------- submissions


AttemptValidator = Callable[[AsyncSession, Principal, uuid.UUID, uuid.UUID], Awaitable[None]]
_attempt_validator: AttemptValidator | None = None


AccessGrant = Callable[[AsyncSession, Principal, uuid.UUID], Awaitable[bool]]
_access_grants: list[AccessGrant] = []


def register_access_grant(fn: AccessGrant) -> None:
    """Other modules: ``fn(session, principal, problem_id) -> bool`` grants practice access to a
    problem through their own context (learning: a started structured assignment the learner is
    allocated that contains the problem) instead of a standalone entitlement. Grants only ever
    widen access; restriction, size, language and rate limits still apply. Idempotent."""
    if fn not in _access_grants:
        _access_grants.append(fn)


def register_attempt_validator(fn: AttemptValidator | None) -> None:
    """Assessments module: ``fn(session, principal, attempt_id, problem_id)`` raises
    ``ProblemError`` (``attempt_closed``/``attempt_bound_elsewhere``) unless the attempt is in
    progress, bound to this session and contains the problem."""
    global _attempt_validator
    _attempt_validator = fn


async def _lock_user(session: AsyncSession, user_id: uuid.UUID) -> None:
    if _fs():
        # pg_advisory_xact_lock -> a request lock held until the request ends (core.request_locks)
        from app.core import request_locks

        await request_locks.acquire(f"coding_submit:{user_id}")
        return
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:k, 0))"), {"k": f"coding.submit:{user_id}"}
    )


async def _recent_count(session: AsyncSession, user_id: uuid.UUID, problem_id: uuid.UUID, mode: str) -> int:
    if _fs():
        subs = await (await _repo(session)).submissions_of(
            user_id,
            (
                ("coding_problem_id", "==", str(problem_id)),
                ("mode", "==", mode),
                ("queued_at", ">", utcnow() - timedelta(seconds=60)),
            ),
        )
        return sum(1 for s in subs if s.attempt_id is None)
    q = select(func.count()).where(
        CodeSubmission.user_id == user_id,
        CodeSubmission.coding_problem_id == problem_id,
        CodeSubmission.mode == mode,
        CodeSubmission.attempt_id.is_(None),
        CodeSubmission.queued_at > func.now() - text("interval '60 seconds'"),
    )
    return int((await session.execute(q)).scalar_one())


async def _inflight_count(session: AsyncSession, user_id: uuid.UUID) -> int:
    if _fs():
        subs = await (await _repo(session)).submissions_of(
            user_id,
            (
                ("mode", "==", "submit"),
                ("queued_at", ">", utcnow() - timedelta(minutes=INFLIGHT_STALE_MINUTES)),
            ),
        )
        return sum(1 for s in subs if s.attempt_id is None and s.status in ("queued", "running"))
    q = select(func.count()).where(
        CodeSubmission.user_id == user_id,
        CodeSubmission.mode == "submit",
        CodeSubmission.attempt_id.is_(None),
        CodeSubmission.status.in_(("queued", "running")),
        CodeSubmission.queued_at > func.now() - text(f"interval '{INFLIGHT_STALE_MINUTES} minutes'"),
    )
    return int((await session.execute(q)).scalar_one())


async def _global_pending(session: AsyncSession, principal: Principal, queue: str) -> int:
    """Queue depth across all users (system context for the count, then restore)."""
    if _fs():
        return await (await _repo(session)).count_submissions(
            (("queue_name", "==", queue), ("status", "==", "queued"))
        )
    async with system_context(session, "coding.queue_depth"):
        q = select(func.count()).where(CodeSubmission.queue_name == queue, CodeSubmission.status == "queued")
        return int((await session.execute(q)).scalar_one())


async def precheck_practice(
    session: AsyncSession,
    principal: Principal,
    problem: CodingProblem,
    *,
    mode: str,
    language_key: str,
    source_code: str,
    custom_input: str | None = None,
    attempt_id: uuid.UUID | None = None,
) -> JudgeLanguage:
    """All checks for a practice run/submit that must NOT be stored as an idempotent result
    (restriction, size, entitlement, language, rate limits, in-flight, shedding). A run with
    ``attempt_id`` is gated by the attempt instead of a standalone entitlement."""
    ensure_not_restricted(principal)
    ensure_source_size(source_code, custom_input)
    await require_problem_access(session, principal, problem, attempt_id=attempt_id)
    lang = await language_or_422(session, problem, language_key)
    await _lock_user(session, principal.user_id)
    limit = RUN_PER_MINUTE if mode == "run" else SUBMIT_PER_MINUTE
    if await _recent_count(session, principal.user_id, problem.id, mode) >= limit:
        raise ProblemError(
            "rate_limited",
            detail=f"At most {limit} {mode}s per minute on a problem.",
            headers={"Retry-After": "60"},
            retry_after=60,
        )
    if mode == "submit" and await _inflight_count(session, principal.user_id) >= MAX_INFLIGHT_SUBMITS:
        raise ProblemError("submission_in_flight", headers={"Retry-After": "2"})
    if mode == "run" and await _global_pending(session, principal, "judge_run") >= RUN_QUEUE_MAX:
        raise ProblemError("judge_queue_full", headers={"Retry-After": "10"}, retry_after=10)
    return lang


async def submission_org(
    session: AsyncSession,
    principal: Principal,
    problem: CodingProblem,
    *,
    attempt_id: uuid.UUID | None = None,
) -> uuid.UUID | None:
    """Organization a submission is attributed to (BE-11; COD-08 staff read, batch reports).

    Single company: an in-test submission takes the attempt's organization; an org-private
    problem its organization; a learner who is a member of the company (batch student) the
    company org; a public learner ``None``.
    """
    if attempt_id is not None:
        if uses_firestore("assessments"):
            from app.modules.assessments import public as assessments_public

            org = await assessments_public.attempt_org_of_user(session, attempt_id, principal.user_id)
            if org is not None:
                return org
        else:
            from app.modules.assessments import public as assessments_public

            org = await assessments_public.attempt_org_of_user(session, attempt_id, principal.user_id)
            if org is not None:
                return org
    if problem.organization_id is not None:
        return problem.organization_id
    return COMPANY_ORG_ID if COMPANY_ORG_ID in principal.org_ids else None


async def verify_submission_owner(
    session: AsyncSession,
    submission_id: uuid.UUID,
    user_id: uuid.UUID,
    problem_id: uuid.UUID | None = None,
) -> bool:
    """Public check for other modules (learning LRN-10 code assignments, BE-07): ``True`` only when
    the submission exists, belongs to ``user_id``, is a graded-mode ``submit`` (not a scratch
    ``run``) and, when given, is for ``problem_id``. Reads in the caller's RLS context."""
    if _fs():
        sub = await (await _repo(session)).get_submission(submission_id)
        return (
            sub is not None
            and sub.user_id == user_id
            and sub.mode == "submit"
            and (problem_id is None or sub.coding_problem_id == problem_id)
        )
    q = select(CodeSubmission.id).where(
        CodeSubmission.id == submission_id,
        CodeSubmission.user_id == user_id,
        CodeSubmission.mode == "submit",
    )
    if problem_id is not None:
        q = q.where(CodeSubmission.coding_problem_id == problem_id)
    return (await session.execute(q)).first() is not None


async def create_submission(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    organization_id: uuid.UUID | None,
    problem: CodingProblem,
    language_key: str,
    mode: str,
    source_code: str,
    idempotency_key: str,
    custom_input: str | None = None,
    attempt_id: uuid.UUID | None = None,
    practice_session_id: uuid.UUID | None = None,
) -> CodeSubmission:
    queue = "judge_assessment" if attempt_id is not None else QUEUE_FOR_MODE[mode]
    sub = CodeSubmission(
        id=uuid7(),
        user_id=user_id,
        organization_id=organization_id,
        coding_problem_id=problem.id,
        problem_version=problem.version_no,
        language_key=language_key,
        mode=mode,
        attempt_id=attempt_id,
        practice_session_id=practice_session_id,
        source_code=source_code,
        custom_input=custom_input if mode == "run" else None,
        status="queued",
        judge_provider=provider_name(),
        queue_name=queue,
        idempotency_key=f"{mode}:{idempotency_key}"[:200],
        normalized_sha256=normalized_hash(language_key, source_code) if mode == "submit" else None,
    )
    if _fs():
        sub = await (await _repo(session)).add_submission(user_id, sub)
    else:
        session.add(sub)
        await session.flush()
    from app.modules.coding.tasks import notify_enqueued

    notify_enqueued(sub.id, queue)
    return sub


async def queue_position(session: AsyncSession, principal: Principal, sub: CodeSubmission) -> int:
    if _fs():
        n = await (await _repo(session)).count_submissions(
            (
                ("queue_name", "==", sub.queue_name),
                ("status", "==", "queued"),
                ("queued_at", "<=", sub.queued_at),
            )
        )
        return n - (1 if sub.status == "queued" else 0) + 1  # ``id != sub.id``
    async with system_context(session, "coding.queue_position"):
        q = select(func.count()).where(
            CodeSubmission.queue_name == sub.queue_name,
            CodeSubmission.status == "queued",
            CodeSubmission.queued_at <= sub.queued_at,
            CodeSubmission.id != sub.id,
        )
        return int((await session.execute(q)).scalar_one()) + 1


def accepted_body(sub: CodeSubmission, position: int | None) -> dict[str, Any]:
    return {
        "submission_id": str(sub.id),
        "status": sub.status,
        "mode": sub.mode,
        "queue": sub.queue_name,
        "queue_position": position,
        "problem_version": sub.problem_version,
        "poll_url": f"/api/v1/coding/submissions/{sub.id}",
    }


async def submission_view(
    session: AsyncSession, sub: CodeSubmission, *, include_source: bool = False
) -> SubmissionOut:
    joined: Sequence[Any]
    if _fs():
        repo = await _repo(session)
        results = await repo.results_of(sub)
        samples = {
            c.id: c
            for c in await repo.get_cases([r.test_case_id for r in results if r.test_case_id is not None])
            if c.is_sample
        }
        joined = [
            (
                r,
                samples[r.test_case_id].sample_input if r.test_case_id in samples else None,
                samples[r.test_case_id].sample_output if r.test_case_id in samples else None,
            )
            for r in results
        ]
    else:
        rows = await session.execute(
            select(SubmissionResult, CodingTestCase.sample_input, CodingTestCase.sample_output)
            .outerjoin(
                CodingTestCase,
                and_(CodingTestCase.id == SubmissionResult.test_case_id, CodingTestCase.is_sample.is_(True)),
            )
            .where(SubmissionResult.code_submission_id == sub.id)
            .order_by(SubmissionResult.ordinal)
        )
        joined = rows.all()
    cases: list[SampleCaseResultOut | HiddenCaseResultOut] = []
    for r, s_in, s_out in joined:
        if r.is_hidden:
            cases.append(
                HiddenCaseResultOut(
                    ordinal=r.ordinal, verdict=r.verdict, time_ms=r.time_ms, memory_kb=r.memory_kb
                )
            )
            continue
        is_custom = r.test_case_id is None
        cases.append(
            SampleCaseResultOut(
                ordinal=r.ordinal,
                is_custom=is_custom,
                verdict=r.verdict,
                time_ms=r.time_ms,
                memory_kb=r.memory_kb,
                stdout_excerpt=r.stdout_excerpt,
                expected_output=None if is_custom else s_out,
                input=_excerpt(sub.custom_input) if is_custom else s_in,
            )
        )
    notice = sub.notice
    return SubmissionOut(
        submission_id=sub.id,
        problem_id=sub.coding_problem_id,
        problem_version=sub.problem_version,
        language_key=sub.language_key,
        mode=sub.mode,
        status=sub.status,
        notice=notice,
        verdict=sub.verdict,
        score=float(sub.score) if sub.score is not None else None,
        max_score=float(sub.max_score) if sub.max_score is not None else None,
        passed_cases=sub.passed_cases,
        total_cases=sub.total_cases,
        max_time_ms=sub.max_time_ms,
        max_memory_kb=sub.max_memory_kb,
        compile_output=sub.compile_output,
        cases=cases,
        queued_at=to_rfc3339(sub.queued_at),
        completed_at=to_rfc3339(sub.completed_at) if sub.completed_at else None,
        source_code=sub.source_code if include_source else None,
    )


def history_item(sub: CodeSubmission) -> dict[str, Any]:
    return {
        "submission_id": str(sub.id),
        "problem_id": str(sub.coding_problem_id),
        "problem_version": sub.problem_version,
        "language_key": sub.language_key,
        "mode": sub.mode,
        "status": sub.status,
        "verdict": sub.verdict,
        "score": float(sub.score) if sub.score is not None else None,
        "max_score": float(sub.max_score) if sub.max_score is not None else None,
        "passed_cases": sub.passed_cases,
        "total_cases": sub.total_cases,
        "attempt_id": str(sub.attempt_id) if sub.attempt_id else None,
        "queued_at": to_rfc3339(sub.queued_at),
        "completed_at": to_rfc3339(sub.completed_at) if sub.completed_at else None,
    }


# --------------------------------------------------------------------------- assessments interface


@dataclass(frozen=True, slots=True)
class AttemptSubmissionHandle:
    submission_id: uuid.UUID
    status: str
    queue: str
    problem_version: int


@dataclass(frozen=True, slots=True)
class AttemptJudgement:
    status: str  # queued | running | completed | judge_error | judge_timeout | rejected
    verdict: str | None
    score: Decimal | None
    max_score: Decimal | None
    passed_cases: int | None
    total_cases: int | None


async def judge_for_attempt(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    organization_id: uuid.UUID | None,
    attempt_id: uuid.UUID,
    problem_id: uuid.UUID,
    language_key: str,
    source_code: str,
    idempotency_key: str,
) -> AttemptSubmissionHandle:
    """Queue a coding answer inside an assessment attempt (queue ``judge_assessment``).

    Idempotent on ``(user_id, idempotency_key)``: a repeat returns the existing submission.
    Raises ``ProblemError`` (``not_found``, ``language_not_allowed``, ``payload_too_large``).
    Problems must be ``published`` (or ``in_review`` for staff previews — not supported here).
    """
    ensure_source_size(source_code)
    stored_key = f"submit:{idempotency_key}"[:200]
    if _fs():
        existing = await (await _repo(session)).submission_by_idempotency(user_id, stored_key)
    else:
        existing = (
            await session.execute(
                select(CodeSubmission).where(
                    CodeSubmission.user_id == user_id, CodeSubmission.idempotency_key == stored_key
                )
            )
        ).scalar_one_or_none()
    if existing is not None:
        return AttemptSubmissionHandle(
            existing.id, existing.status, existing.queue_name, existing.problem_version
        )
    problem = await published_problem(session, problem_id)
    await language_or_422(session, problem, language_key)
    sub = await create_submission(
        session,
        user_id=user_id,
        organization_id=organization_id,
        problem=problem,
        language_key=language_key,
        mode="submit",
        source_code=source_code,
        idempotency_key=idempotency_key,
        attempt_id=attempt_id,
    )
    return AttemptSubmissionHandle(sub.id, sub.status, sub.queue_name, sub.problem_version)


async def get_attempt_judgement(session: AsyncSession, submission_id: uuid.UUID) -> AttemptJudgement | None:
    sub = (
        await (await _repo(session)).get_submission(submission_id)
        if _fs()
        else await session.get(CodeSubmission, submission_id)
    )
    if sub is None:
        return None
    return AttemptJudgement(
        sub.status, sub.verdict, sub.score, sub.max_score, sub.passed_cases, sub.total_cases
    )


async def mark_rejected(session: AsyncSession, submission_id: uuid.UUID) -> None:
    if _fs():
        await (await _repo(session)).update_submission(
            submission_id, {"status": "rejected", "completed_at": utcnow()}, if_status="queued"
        )
        return
    await session.execute(
        update(CodeSubmission)
        .where(CodeSubmission.id == submission_id, CodeSubmission.status == "queued")
        .values(status="rejected", completed_at=func.now())
    )


# --------------------------------------------------------------------------- key rotation


async def rotate_wrapped_keys(session: AsyncSession, *, batch: int = 500) -> int:
    """Re-wrap hidden-case data keys under the active ``TD_K_TESTCASE_KEY`` version.

    Worker-side maintenance job (needs unwrap capability). Ciphertext blobs are untouched.
    Returns the number of rows re-wrapped."""
    if _fs():
        from app.modules.coding.repo_firestore import system_repo

        fring = crypto.get_testcase_keyring()
        frepo = system_repo("coding.key_rotation")
        todo: dict[uuid.UUID, bytes] = {}
        for fc in await frepo.hidden_cases():
            if fc.wrapped_data_key is None or crypto.key_version(fc.wrapped_data_key) == fring.active_version:
                continue
            todo[fc.id] = crypto.rewrap(fc.wrapped_data_key, fc.coding_problem_id, fring)
            if len(todo) >= batch:
                break
        await frepo.set_wrapped_keys(todo)
        return len(todo)
    await system_context(session, "coding.key_rotation")
    ring = crypto.get_testcase_keyring()
    rows = await session.execute(
        select(CodingTestCase)
        .where(
            CodingTestCase.is_hidden.is_(True),
            func.substring(CodingTestCase.wrapped_data_key, 2, 2) != ring.active_version.to_bytes(2, "big"),
        )
        .limit(batch)
    )
    n = 0
    for c in rows.scalars():
        if c.wrapped_data_key is None or crypto.key_version(c.wrapped_data_key) == ring.active_version:
            continue
        c.wrapped_data_key = crypto.rewrap(c.wrapped_data_key, c.coding_problem_id, ring)
        n += 1
    await session.flush()
    return n


# --------------------------------------------------------------------------- studio list (Stage 10)


async def studio_list_problems(
    session: AsyncSession,
    *,
    status: str | None,
    q: str | None,
    after: uuid.UUID | None,
    limit: int,
    allowed: Callable[[uuid.UUID | None], Awaitable[bool]],
) -> tuple[list[CodingProblem], bool]:
    """Problems visible under the caller's RLS context (platform + own orgs), newest first,
    keeping only those whose scope passes ``allowed(organization_id)``. Returns (rows, more)."""
    if _fs():
        found = await (await _repo(session)).problems(status=status)
        if q:  # ILIKE '%q%' on title or slug
            ql = q.lower()
            found = [p for p in found if ql in p.title.lower() or ql in p.slug.lower()]
        found.sort(key=lambda p: p.id, reverse=True)
        fverdicts: dict[uuid.UUID | None, bool] = {}
        fpicked: list[CodingProblem] = []
        for p in found:
            if after is not None and not p.id < after:
                continue
            if p.organization_id not in fverdicts:
                try:
                    fverdicts[p.organization_id] = await allowed(p.organization_id)
                except ProblemError:
                    fverdicts[p.organization_id] = False
            if fverdicts[p.organization_id]:
                fpicked.append(p)
                if len(fpicked) > limit:
                    break
        return fpicked[:limit], len(fpicked) > limit
    stmt = select(CodingProblem)
    if status is not None:
        stmt = stmt.where(CodingProblem.status == status)
    if q:
        like = "%" + q.replace("\\", "\\\\").replace("%", r"\%").replace("_", r"\_") + "%"
        stmt = stmt.where(CodingProblem.title.ilike(like) | CodingProblem.slug.ilike(like))
    verdicts: dict[uuid.UUID | None, bool] = {}
    picked: list[CodingProblem] = []
    chunk = (limit + 1) * 2
    for _ in range(20):
        page = stmt if after is None else stmt.where(CodingProblem.id < after)
        rows = list((await session.execute(page.order_by(CodingProblem.id.desc()).limit(chunk))).scalars())
        for p in rows:
            if p.organization_id not in verdicts:
                try:
                    verdicts[p.organization_id] = await allowed(p.organization_id)
                except ProblemError:
                    verdicts[p.organization_id] = False
            if verdicts[p.organization_id]:
                picked.append(p)
                if len(picked) > limit:
                    break
        if len(picked) > limit or len(rows) < chunk:
            break
        after = rows[-1].id
    return picked[:limit], len(picked) > limit


async def test_case_counts(
    session: AsyncSession, problem_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, tuple[int, int]]:
    """(sample, hidden) case counts per problem for its current version (metadata only)."""
    if not problem_ids:
        return {}
    if _fs():
        repo = await _repo(session)
        out: dict[uuid.UUID, tuple[int, int]] = {}
        for p in await repo.get_problems(problem_ids):
            cs = await repo.cases(p.id, p.version_no)
            if cs:
                out[p.id] = (sum(1 for c in cs if c.is_sample), sum(1 for c in cs if c.is_hidden))
        return out
    rows = await session.execute(
        select(
            CodingTestCase.coding_problem_id,
            func.count().filter(CodingTestCase.is_sample.is_(True)),
            func.count().filter(CodingTestCase.is_hidden.is_(True)),
        )
        .join(
            CodingProblem,
            and_(
                CodingProblem.id == CodingTestCase.coding_problem_id,
                CodingProblem.version_no == CodingTestCase.problem_version,
            ),
        )
        .where(CodingTestCase.coding_problem_id.in_(list(problem_ids)))
        .group_by(CodingTestCase.coding_problem_id)
    )
    return {r[0]: (int(r[1]), int(r[2])) for r in rows.all()}


def studio_compat_fields(p: CodingProblem, counts: tuple[int, int] | None) -> dict[str, Any]:
    """Flat fields the web studio reads (``time_limit_ms``, ``memory_limit_mb``, ``languages``)
    plus case counts — hidden-case content is never included."""
    samples, hidden = counts or (0, 0)
    return {
        "time_limit_ms": p.time_limit_ms,
        "memory_limit_mb": p.memory_limit_kb // 1024,
        "languages": list(p.allowed_languages),
        "test_cases": {"sample": samples, "hidden": hidden},
        "updated_at": to_rfc3339(p.updated_at),
        "published_at": to_rfc3339(p.published_at) if p.published_at else None,
    }


def studio_summary_out(p: CodingProblem, counts: tuple[int, int]) -> dict[str, Any]:
    return {
        "problem_id": str(p.id),
        "slug": p.slug,
        "title": p.title,
        "status": p.status,
        "difficulty": p.difficulty,
        "version_no": p.version_no,
        "is_free": p.is_free,
        "scoring_mode": p.scoring_mode,
        "organization_id": str(p.organization_id) if p.organization_id else None,
        **studio_compat_fields(p, counts),
    }
