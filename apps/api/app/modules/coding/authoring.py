"""Coding authoring gaps: editor drafts (COD-04/05), reference solutions + validation (COD-18,
publish gate for COD-19) and audited hidden-case content (COD-17).

Hidden-case decryption on the API side is limited to two paths, both permission-gated:

* COD-18 validate — decrypts in memory to run the author's reference solutions through the judge
  gateway (synchronously, short budget); only verdict/time/memory per case is returned or stored.
* COD-17 content — decrypts ONLY when a single-use, user-bound, 5-minute download token is
  redeemed by the same user (``coding_test_case.hidden.read`` re-checked); issuance is audited
  (``coding.testcase.read_hidden`` with the reason).

Rate limits are counted from this module's own tables (no core rate-limit helper exists):
drafts 20/min (window counter on the row), validate 10/h (``coding_problem_validations``),
hidden content 30/h (``coding_testcase_content_tokens`` requests).
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ProblemError
from app.core.ids import uuid7
from app.core.principal import Principal
from app.core.security import generate_token, hash_token
from app.core.time import to_rfc3339, utcnow
from app.modules.coding import blobstore, crypto
from app.modules.coding.judge_gateway import (
    JudgeConfigurationError,
    JudgeJob,
    JudgeLimits,
    JudgeRunResult,
    JudgeTimeout,
    JudgeUnavailable,
    get_judge_adapter,
    run_jobs,
)
from app.modules.coding.judge_gateway.checker import case_verdict
from app.modules.coding.models import (
    CodingDraft,
    CodingProblem,
    CodingProblemValidation,
    CodingReferenceSolution,
    CodingTestCase,
    CodingTestCaseContentToken,
)
from app.modules.coding.schemas import MAX_SOURCE_BYTES
from app.modules.coding.service import _fs, _repo, language_or_422, list_cases

DRAFTS_PER_MINUTE = 20
VALIDATIONS_PER_HOUR = 10
HIDDEN_READS_PER_HOUR = 30
CONTENT_TOKEN_TTL = timedelta(minutes=5)
VALIDATE_BUDGET_S = 20.0
DOWNLOAD_PATH = "/api/v1/studio/coding/test-cases/content-downloads/"


def _size_or_413(source_code: str) -> int:
    n = len(source_code.encode("utf-8"))
    if n > MAX_SOURCE_BYTES:
        raise ProblemError(
            "payload_too_large", detail="Source code is limited to 64 KiB.", limit_bytes=MAX_SOURCE_BYTES
        )
    return n


# --------------------------------------------------------------------------- drafts (COD-04/05)


def draft_out(d: CodingDraft) -> dict[str, Any]:
    return {
        "problem_id": str(d.coding_problem_id),
        "language_key": d.language_key,
        "source_code": d.source_code,
        "size_bytes": len(d.source_code.encode("utf-8")),
        "updated_at": to_rfc3339(d.updated_at),
    }


async def get_draft(
    session: AsyncSession, principal: Principal, problem_id: uuid.UUID, language_key: str
) -> CodingDraft:
    if _fs():
        fd = await (await _repo(session)).get_draft(principal.user_id, problem_id, language_key)
        if fd is None:
            raise ProblemError("not_found")
        return fd
    row = (
        await session.execute(
            select(CodingDraft).where(
                CodingDraft.user_id == principal.user_id,
                CodingDraft.coding_problem_id == problem_id,
                CodingDraft.language_key == language_key,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise ProblemError("not_found")
    return row


async def save_draft(
    session: AsyncSession, principal: Principal, problem: CodingProblem, language_key: str, source_code: str
) -> CodingDraft:
    _size_or_413(source_code)
    await language_or_422(session, problem, language_key)
    now = utcnow()
    window_start = now - timedelta(seconds=60)
    if _fs():
        return await (await _repo(session)).save_draft(
            principal.user_id,
            CodingDraft(
                id=uuid7(),
                user_id=principal.user_id,
                coding_problem_id=problem.id,
                language_key=language_key,
                source_code=source_code,
                window_started_at=now,
                window_count=1,
                created_at=now,
                updated_at=now,
            ),
            window_start=window_start,
            per_minute=DRAFTS_PER_MINUTE,
            limited=_drafts_limited,
        )
    stmt = (
        pg_insert(CodingDraft)
        .values(
            id=uuid7(),
            user_id=principal.user_id,
            coding_problem_id=problem.id,
            language_key=language_key,
            source_code=source_code,
            window_started_at=now,
            window_count=1,
        )
        .on_conflict_do_nothing(constraint="ux_cd_user_problem_lang")
        .returning(CodingDraft.id)
    )
    if (await session.execute(stmt)).scalar_one_or_none() is None:
        existing = (
            await session.execute(
                select(CodingDraft)
                .where(
                    CodingDraft.user_id == principal.user_id,
                    CodingDraft.coding_problem_id == problem.id,
                    CodingDraft.language_key == language_key,
                )
                .with_for_update()
            )
        ).scalar_one()
        if existing.window_started_at > window_start:
            if existing.window_count >= DRAFTS_PER_MINUTE:
                raise _drafts_limited()
            existing.window_count += 1
        else:
            existing.window_started_at = now
            existing.window_count = 1
        existing.source_code = source_code
        existing.updated_at = now
        await session.flush()
    return await get_draft(session, principal, problem.id, language_key)


def _drafts_limited() -> ProblemError:
    return ProblemError(
        "rate_limited",
        detail=f"At most {DRAFTS_PER_MINUTE} draft saves per minute.",
        headers={"Retry-After": "60"},
        retry_after=60,
    )


# --------------------------------------------------------------------------- reference solutions


def reference_out(r: CodingReferenceSolution, *, include_source: bool = True) -> dict[str, Any]:
    out: dict[str, Any] = {
        "language_key": r.language_key,
        "size_bytes": len(r.source_code.encode("utf-8")),
        "updated_at": to_rfc3339(r.updated_at),
    }
    if include_source:
        out["source_code"] = r.source_code
    return out


async def list_reference_solutions(
    session: AsyncSession, problem: CodingProblem
) -> list[CodingReferenceSolution]:
    if _fs():
        return await (await _repo(session)).ref_solutions(problem.id)
    rows = await session.execute(
        select(CodingReferenceSolution)
        .where(CodingReferenceSolution.coding_problem_id == problem.id)
        .order_by(CodingReferenceSolution.language_key)
    )
    return list(rows.scalars())


async def put_reference_solution(
    session: AsyncSession, principal: Principal, problem: CodingProblem, language_key: str, source_code: str
) -> CodingReferenceSolution:
    if problem.status == "retired":
        raise ProblemError("invalid_state_transition", detail="Retired problems cannot change.")
    _size_or_413(source_code)
    await language_or_422(session, problem, language_key)
    now = utcnow()
    if _fs():
        return await (await _repo(session)).put_ref_solution(
            CodingReferenceSolution(
                id=uuid7(),
                coding_problem_id=problem.id,
                organization_id=problem.organization_id,
                language_key=language_key,
                source_code=source_code,
                updated_by=principal.user_id,
                created_at=now,
                updated_at=now,
            )
        )
    await session.execute(
        pg_insert(CodingReferenceSolution)
        .values(
            id=uuid7(),
            coding_problem_id=problem.id,
            organization_id=problem.organization_id,
            language_key=language_key,
            source_code=source_code,
            updated_by=principal.user_id,
        )
        .on_conflict_do_update(
            constraint="ux_crs_problem_lang",
            set_={"source_code": source_code, "updated_by": principal.user_id, "updated_at": now},
        )
    )
    row = (
        await session.execute(
            select(CodingReferenceSolution)
            .where(
                CodingReferenceSolution.coding_problem_id == problem.id,
                CodingReferenceSolution.language_key == language_key,
            )
            .execution_options(populate_existing=True)
        )
    ).scalar_one()
    return row


# --------------------------------------------------------------------------- validation (COD-18)


def fingerprint(problem: CodingProblem, cases: list[CodingTestCase]) -> bytes:
    """Identity of what a validation proved: version, limits, checker, scoring and the exact case
    set (ids, weights, content hashes). Any change makes earlier validations stale."""

    def _h(s: str | None) -> str | None:
        return hashlib.sha256(s.encode("utf-8")).hexdigest() if s is not None else None

    doc = {
        "version_no": problem.version_no,
        "limits": [problem.time_limit_ms, problem.wall_limit_ms, problem.memory_limit_kb],
        "checker": [problem.checker_type, problem.checker_config],
        "scoring_mode": problem.scoring_mode,
        "cases": [
            [
                str(c.id),
                c.ordinal,
                c.is_sample,
                str(c.weight),
                c.input_sha256.hex() if c.input_sha256 else _h(c.sample_input),
                c.expected_sha256.hex() if c.expected_sha256 else _h(c.sample_output),
            ]
            for c in sorted(cases, key=lambda c: c.ordinal)
        ],
    }
    return hashlib.sha256(json.dumps(doc, sort_keys=True, default=str).encode("utf-8")).digest()


def validation_out(v: CodingProblemValidation, current_fp: bytes) -> dict[str, Any]:
    return {
        "validation_id": str(v.id),
        "problem_id": str(v.coding_problem_id),
        "problem_version": v.problem_version,
        "status": v.status,
        "is_current": v.fingerprint == current_fp,
        "validated_at": to_rfc3339(v.created_at),
        "requested_by": str(v.requested_by),
        "detail": v.detail,
        "solutions": v.results,
    }


async def latest_validation(session: AsyncSession, problem_id: uuid.UUID) -> CodingProblemValidation | None:
    if _fs():
        return await (await _repo(session)).latest_validation(problem_id)
    return (
        await session.execute(
            select(CodingProblemValidation)
            .where(CodingProblemValidation.coding_problem_id == problem_id)
            .order_by(CodingProblemValidation.created_at.desc(), CodingProblemValidation.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def current_fingerprint(session: AsyncSession, problem: CodingProblem) -> bytes:
    return fingerprint(problem, await list_cases(session, problem))


async def has_passing_validation(session: AsyncSession, problem: CodingProblem) -> bool:
    v = await latest_validation(session, problem.id)
    return (
        v is not None
        and v.status == "passed"
        and v.fingerprint == await current_fingerprint(session, problem)
    )


@dataclass
class _PlainCase:
    ordinal: int
    is_sample: bool
    stdin: str
    expected: str


async def _plain_cases(
    session: AsyncSession, problem: CodingProblem, cases: list[CodingTestCase]
) -> list[_PlainCase]:
    out: list[_PlainCase] = []
    for c in cases:
        if c.is_sample:
            out.append(_PlainCase(c.ordinal, True, c.sample_input or "", c.sample_output or ""))
            continue
        assert c.wrapped_data_key and c.input_s3_key and c.expected_s3_key
        stdin, expected = crypto.open_case(
            problem.id,
            c.wrapped_data_key,
            await blobstore.get_blob(session, c.input_s3_key),
            await blobstore.get_blob(session, c.expected_s3_key),
        )
        out.append(_PlainCase(c.ordinal, False, stdin, expected))
    return out


def _case_row(case: _PlainCase, verdict: str, res: JudgeRunResult) -> dict[str, Any]:
    # Same field set for samples and hidden cases: nothing beyond verdict/time/memory.
    return {
        "ordinal": case.ordinal,
        "is_sample": case.is_sample,
        "verdict": verdict,
        "time_ms": res.time_ms,
        "memory_kb": res.memory_kb,
    }


async def validate_problem(
    session: AsyncSession,
    principal: Principal,
    problem: CodingProblem,
    solutions: list[tuple[str, str]] | None,
) -> CodingProblemValidation:
    if problem.status == "retired":
        raise ProblemError("invalid_state_transition", detail="Retired problems cannot be validated.")
    if _fs():
        recent = await (await _repo(session)).validations_since(
            principal.user_id, utcnow() - timedelta(hours=1)
        )
    else:
        recent = (
            await session.execute(
                select(func.count()).where(
                    CodingProblemValidation.requested_by == principal.user_id,
                    CodingProblemValidation.created_at > utcnow() - timedelta(hours=1),
                )
            )
        ).scalar_one()
    if int(recent) >= VALIDATIONS_PER_HOUR:
        raise ProblemError(
            "rate_limited",
            detail=f"At most {VALIDATIONS_PER_HOUR} validations per hour.",
            headers={"Retry-After": "600"},
            retry_after=600,
        )
    for lang_key, src in solutions or []:
        await put_reference_solution(session, principal, problem, lang_key, src)
    refs = await list_reference_solutions(session, problem)
    if not refs:
        raise ProblemError(
            "invalid_state_transition",
            detail="Add a reference solution before validating.",
            reason="no_reference_solution",
        )
    cases = await list_cases(session, problem)
    if not cases:
        raise ProblemError(
            "invalid_state_transition", detail="Add test cases before validating.", reason="no_test_cases"
        )
    fp = fingerprint(problem, cases)
    plain = await _plain_cases(session, problem, cases)
    status, detail = "passed", None
    results: list[dict[str, Any]] = []
    try:
        adapter = get_judge_adapter()
    except JudgeConfigurationError:
        adapter = None
        status, detail = "error", "The judge is not configured."
    if adapter is not None:
        for ref in refs:
            lang = await language_or_422(session, problem, ref.language_key)
            limits = JudgeLimits.for_problem(
                time_limit_ms=problem.time_limit_ms,
                wall_limit_ms=problem.wall_limit_ms,
                memory_limit_kb=problem.memory_limit_kb,
                time_multiplier=float(lang.time_multiplier),
                memory_extra_kb=lang.memory_extra_kb,
                max_processes=lang.max_processes,
            )
            jobs = [
                JudgeJob(
                    ordinal=c.ordinal,
                    source_code=ref.source_code,
                    language_key=lang.language_key,
                    provider_language_id=lang.provider_language_id,
                    stdin=c.stdin,
                    limits=limits,
                    expected_output=c.expected,
                )
                for c in plain
            ]
            try:
                runs = await run_jobs(adapter, jobs, budget_s=VALIDATE_BUDGET_S)
            except (JudgeTimeout, JudgeUnavailable) as e:
                status = "error"
                detail = (
                    "The judge timed out." if isinstance(e, JudgeTimeout) else "The judge is unavailable."
                )
                results.append(
                    {
                        "language_key": ref.language_key,
                        "verdict": "IE",
                        "passed_cases": 0,
                        "total_cases": len(plain),
                        "cases": [],
                    }
                )
                continue
            compile_error = any(r.status == "CE" for r in runs)
            rows = []
            for c, r in zip(plain, runs, strict=True):
                v = (
                    "CE"
                    if compile_error
                    else case_verdict(r, c.expected, problem.checker_type, problem.checker_config)
                )
                rows.append(_case_row(c, v, r))
            passed = sum(1 for x in rows if x["verdict"] == "AC")
            overall = (
                "AC" if passed == len(rows) else next(x["verdict"] for x in rows if x["verdict"] != "AC")
            )
            if overall != "AC" and status == "passed":
                status = "failed"
            results.append(
                {
                    "language_key": ref.language_key,
                    "verdict": overall,
                    "passed_cases": passed,
                    "total_cases": len(rows),
                    "cases": rows,
                }
            )
    del plain  # plaintext never leaves this function
    rec = CodingProblemValidation(
        id=uuid7(),
        coding_problem_id=problem.id,
        organization_id=problem.organization_id,
        problem_version=problem.version_no,
        fingerprint=fp,
        status=status,
        results=results,
        detail=detail,
        requested_by=principal.user_id,
        created_at=utcnow(),
    )
    if _fs():
        return await (await _repo(session)).create_validation(rec)
    session.add(rec)
    await session.flush()
    return rec


# --------------------------------------------------------------------------- hidden content (COD-17)


async def hidden_reads_last_hour(session: AsyncSession, user_id: uuid.UUID) -> int:
    if _fs():
        return await (await _repo(session)).token_requests_since(user_id, utcnow() - timedelta(hours=1))
    n = (
        await session.execute(
            select(func.count(func.distinct(CodingTestCaseContentToken.request_id))).where(
                CodingTestCaseContentToken.user_id == user_id,
                CodingTestCaseContentToken.created_at > utcnow() - timedelta(hours=1),
            )
        )
    ).scalar_one()
    return int(n)


async def issue_content_tokens(
    session: AsyncSession, principal: Principal, case: CodingTestCase, reason: str
) -> dict[str, Any]:
    if await hidden_reads_last_hour(session, principal.user_id) >= HIDDEN_READS_PER_HOUR:
        raise ProblemError(
            "rate_limited",
            detail=f"At most {HIDDEN_READS_PER_HOUR} hidden test-case reads per hour.",
            headers={"Retry-After": "600"},
            retry_after=600,
        )
    request_id = uuid7()
    now = utcnow()
    expires = now + CONTENT_TOKEN_TTL
    urls: dict[str, str] = {}
    fs_rows: list[CodingTestCaseContentToken] = []
    for part in ("input", "expected"):
        token = generate_token(32)
        (fs_rows.append if _fs() else session.add)(
            CodingTestCaseContentToken(
                id=uuid7(),
                token_hash=hash_token(token),
                request_id=request_id,
                user_id=principal.user_id,
                test_case_id=case.id,
                coding_problem_id=case.coding_problem_id,
                organization_id=case.organization_id,
                part=part,
                reason=reason,
                expires_at=expires,
                created_at=now,
            )
        )
        urls[part] = DOWNLOAD_PATH + token
    if _fs():
        await (await _repo(session)).add_tokens(principal.user_id, fs_rows)
    else:
        await session.flush()
    return {
        "test_case_id": str(case.id),
        "ordinal": case.ordinal,
        "input_url": urls["input"],
        "expected_url": urls["expected"],
        "expires_at": to_rfc3339(expires),
        "sha256": {
            "input": case.input_sha256.hex() if case.input_sha256 else None,
            "expected": case.expected_sha256.hex() if case.expected_sha256 else None,
        },
        "request_id": str(request_id),
    }


async def redeem_content_token(
    session: AsyncSession, principal: Principal, token: str
) -> tuple[CodingTestCaseContentToken, CodingTestCase]:
    """Atomically mark the token used (single use, unexpired, same user) — else 404."""
    if not token or len(token) > 128:
        raise ProblemError("not_found")
    if _fs():
        frepo = await _repo(session)
        frow = await frepo.redeem_token(principal.user_id, hash_token(token), utcnow())
        if frow is None:
            raise ProblemError("not_found")
        fcase = await frepo.get_case(frow.test_case_id)
        if fcase is None or not fcase.is_hidden:
            raise ProblemError("not_found")
        return frow, fcase
    row = (
        await session.execute(
            update(CodingTestCaseContentToken)
            .where(
                CodingTestCaseContentToken.token_hash == hash_token(token),
                CodingTestCaseContentToken.user_id == principal.user_id,
                CodingTestCaseContentToken.used_at.is_(None),
                CodingTestCaseContentToken.expires_at > utcnow(),
            )
            .values(used_at=utcnow())
            .returning(CodingTestCaseContentToken)
        )
    ).scalar_one_or_none()
    if row is None:
        raise ProblemError("not_found")
    case = await session.get(CodingTestCase, row.test_case_id)
    if case is None or not case.is_hidden:
        raise ProblemError("not_found")
    return row, case


async def decrypt_part(session: AsyncSession, case: CodingTestCase, part: str) -> str:
    assert case.wrapped_data_key and case.input_s3_key and case.expected_s3_key
    stdin, expected = crypto.open_case(
        case.coding_problem_id,
        case.wrapped_data_key,
        await blobstore.get_blob(session, case.input_s3_key),
        await blobstore.get_blob(session, case.expected_s3_key),
    )
    return stdin if part == "input" else expected
