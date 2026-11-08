"""Judge worker (``worker-judge`` service ONLY — ADR-0005). Never import from API routes.

Flow per submission: claim (guarded ``queued → running``) → load problem/language/cases →
decrypt hidden cases in memory → ``run_jobs`` on the adapter (batch + polling, 30 s budget)
→ check outputs locally → aggregate verdict/score → write ``submission_results`` (hidden:
verdict/time/memory only) → update ``code_submissions`` → outbox ``submission.judged``.

Failure handling: provider unavailable → back to ``queued`` with ``notice='judge_degraded'``
(``judge_error`` after 15 min); poll budget exhausted → one automatic retry, then
``judge_timeout``; stale ``running`` rows (> 5 min) are re-queued.

Run: ``python -m app.modules.coding.worker [--once] [--batch N] [--interval S]``.
"""

from __future__ import annotations

import argparse
import asyncio
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import timedelta
from decimal import Decimal

import structlog
from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.db import get_sessionmaker, system_context
from app.core.ids import uuid7
from app.core.outbox import emit_event
from app.core.time import utcnow
from app.modules.coding import blobstore, crypto
from app.modules.coding.judge_gateway import (
    JudgeAdapter,
    JudgeJob,
    JudgeLimits,
    JudgeRunResult,
    JudgeTimeout,
    JudgeUnavailable,
    get_judge_adapter,
    run_jobs,
)
from app.modules.coding.judge_gateway.checker import ScoredCase, aggregate, case_verdict
from app.modules.coding.models import (
    CodeSubmission,
    CodingProblem,
    CodingTestCase,
    JudgeLanguage,
    SubmissionResult,
)

log = structlog.get_logger("app.coding.worker")

POLL_BUDGET_S = 30.0
OUTAGE_MAX = timedelta(minutes=15)
STALE_RUNNING = timedelta(minutes=5)
STDOUT_EXCERPT_BYTES = 4096
COMPILE_OUTPUT_BYTES = 16 * 1024
JOB = "coding.judge"


@dataclass
class _Case:
    ordinal: int
    test_case_id: uuid.UUID | None
    is_hidden: bool
    weight: Decimal
    stdin: str
    expected: str | None  # None = custom input (no checker)


@dataclass
class JudgeWork:
    submission_id: uuid.UUID
    user_id: uuid.UUID
    organization_id: uuid.UUID | None
    problem_id: uuid.UUID
    mode: str
    queued_at_age: timedelta
    retry_count: int
    checker_type: str
    checker_config: dict[str, object] | None
    scoring_mode: str
    jobs: list[JudgeJob] = field(default_factory=list)
    cases: list[_Case] = field(default_factory=list)


def _trim(s: str | None, limit: int) -> str | None:
    if s is None:
        return None
    return s.encode("utf-8")[:limit].decode("utf-8", errors="ignore")


async def claim(session: AsyncSession, submission_id: uuid.UUID) -> bool:
    await system_context(session, JOB)
    res = await session.execute(
        update(CodeSubmission)
        .where(CodeSubmission.id == submission_id, CodeSubmission.status == "queued")
        .values(status="running", started_at=utcnow())
        .returning(CodeSubmission.id)
    )
    return res.scalar_one_or_none() is not None


async def load_work(session: AsyncSession, submission_id: uuid.UUID) -> JudgeWork:
    """Build jobs; decrypts hidden cases (worker memory only)."""
    await system_context(session, JOB)
    sub = (
        await session.execute(
            select(CodeSubmission)
            .where(CodeSubmission.id == submission_id)
            .execution_options(populate_existing=True)
        )
    ).scalar_one()
    problem = (
        await session.execute(select(CodingProblem).where(CodingProblem.id == sub.coding_problem_id))
    ).scalar_one()
    lang = (
        await session.execute(select(JudgeLanguage).where(JudgeLanguage.language_key == sub.language_key))
    ).scalar_one()
    q = select(CodingTestCase).where(
        CodingTestCase.coding_problem_id == problem.id, CodingTestCase.problem_version == sub.problem_version
    )
    if sub.mode == "run":
        q = q.where(CodingTestCase.is_sample.is_(True))  # Run NEVER touches hidden cases
    rows = list((await session.execute(q.order_by(CodingTestCase.ordinal))).scalars())
    limits = JudgeLimits.for_problem(
        time_limit_ms=problem.time_limit_ms,
        wall_limit_ms=problem.wall_limit_ms,
        memory_limit_kb=problem.memory_limit_kb,
        time_multiplier=float(lang.time_multiplier),
        memory_extra_kb=lang.memory_extra_kb,
        max_processes=lang.max_processes,
    )
    work = JudgeWork(
        submission_id=sub.id,
        user_id=sub.user_id,
        organization_id=sub.organization_id,
        problem_id=problem.id,
        mode=sub.mode,
        queued_at_age=utcnow() - sub.queued_at,
        retry_count=sub.retry_count,
        checker_type=problem.checker_type,
        checker_config=problem.checker_config,
        scoring_mode=problem.scoring_mode,
    )
    for c in rows:
        if c.is_sample:
            stdin, expected = c.sample_input or "", c.sample_output or ""
        else:
            assert c.wrapped_data_key and c.input_s3_key and c.expected_s3_key
            stdin, expected = crypto.open_case(
                problem.id,
                c.wrapped_data_key,
                await blobstore.get_blob(session, c.input_s3_key),
                await blobstore.get_blob(session, c.expected_s3_key),
            )
        work.cases.append(_Case(c.ordinal, c.id, c.is_hidden, c.weight, stdin, expected))
    if sub.mode == "run" and sub.custom_input is not None:
        nxt = max((c.ordinal for c in work.cases), default=0) + 1
        work.cases.append(_Case(nxt, None, False, Decimal(0), sub.custom_input, None))
    work.jobs = [
        JudgeJob(
            ordinal=c.ordinal,
            source_code=sub.source_code,
            language_key=lang.language_key,
            provider_language_id=lang.provider_language_id,
            stdin=c.stdin,
            limits=limits,
            expected_output=c.expected,
        )
        for c in work.cases
    ]
    return work


async def record(session: AsyncSession, work: JudgeWork, results: Sequence[JudgeRunResult]) -> str:
    await system_context(session, JOB)
    compile_output = next((r.compile_output for r in results if r.status == "CE"), None)
    verdicts: list[str] = []
    for case, res in zip(work.cases, results, strict=True):
        v = (
            "CE"
            if compile_output is not None
            else case_verdict(res, case.expected, work.checker_type, work.checker_config)
        )
        verdicts.append(v)
    graded = [
        ScoredCase(c.ordinal, c.weight, v)
        for c, v in zip(work.cases, verdicts, strict=True)
        if c.expected is not None
    ]
    if graded:
        agg = aggregate(graded, work.scoring_mode)
        verdict, score, max_score = agg.verdict, agg.score, agg.max_score
        passed, total, awarded = agg.passed, agg.total, agg.awarded
    else:  # custom-input-only run
        verdict = verdicts[0] if verdicts else "IE"
        score, max_score, passed, total, awarded = Decimal(0), Decimal(0), 0, 0, {}
    for case, res, v in zip(work.cases, results, verdicts, strict=True):
        session.add(
            SubmissionResult(
                id=uuid7(),
                code_submission_id=work.submission_id,
                user_id=work.user_id,
                organization_id=work.organization_id,
                test_case_id=case.test_case_id,
                ordinal=case.ordinal,
                is_hidden=case.is_hidden,
                verdict=v,
                time_ms=res.time_ms,
                memory_kb=res.memory_kb,
                exit_code=res.exit_code
                if res.exit_code is None or -32768 <= res.exit_code <= 32767
                else None,
                # Hidden cases: never store stdout (ck_sr_hidden_output).
                stdout_excerpt=None if case.is_hidden else _trim(res.stdout, STDOUT_EXCERPT_BYTES),
                judge_token=res.token,
                weight_awarded=awarded.get(case.ordinal, Decimal(0)),
            )
        )
    times = [r.time_ms for r in results if r.time_ms is not None]
    mems = [r.memory_kb for r in results if r.memory_kb is not None]
    await session.execute(
        update(CodeSubmission)
        .where(CodeSubmission.id == work.submission_id)
        .values(
            status="completed",
            verdict=verdict,
            score=score if work.mode == "submit" else None,
            max_score=max_score if work.mode == "submit" else None,
            passed_cases=passed,
            total_cases=total,
            max_time_ms=max(times) if times else None,
            max_memory_kb=max(mems) if mems else None,
            compile_output=_trim(compile_output, COMPILE_OUTPUT_BYTES),
            notice=None,
            completed_at=utcnow(),
        )
    )
    await emit_event(
        session,
        "submission.judged",
        {
            "submission_id": str(work.submission_id),
            "user_id": str(work.user_id),
            "problem_id": str(work.problem_id),
            "mode": work.mode,
            "verdict": verdict,
            "score": str(score) if work.mode == "submit" else None,
        },
        aggregate_type="code_submission",
        aggregate_id=work.submission_id,
        organization_id=work.organization_id,
    )
    await session.flush()
    return verdict


async def _release(session: AsyncSession, work: JudgeWork, *, timed_out: bool) -> str:
    await system_context(session, JOB)
    if timed_out:
        if work.retry_count < 1:
            values: dict[str, object] = {
                "status": "queued",
                "retry_count": work.retry_count + 1,
                "started_at": None,
            }
            outcome = "requeued_after_timeout"
        else:
            values = {"status": "judge_timeout", "verdict": "IE", "completed_at": utcnow()}
            outcome = "judge_timeout"
    elif work.queued_at_age > OUTAGE_MAX:
        values = {
            "status": "judge_error",
            "verdict": "IE",
            "notice": "judge_degraded",
            "completed_at": utcnow(),
        }
        outcome = "judge_error"
    else:
        values = {"status": "queued", "notice": "judge_degraded", "started_at": None}
        outcome = "requeued_judge_degraded"
    await session.execute(
        update(CodeSubmission).where(CodeSubmission.id == work.submission_id).values(**values)
    )
    await session.flush()
    return outcome


async def execute(
    adapter: JudgeAdapter, work: JudgeWork, budget_s: float = POLL_BUDGET_S
) -> list[JudgeRunResult]:
    return await run_jobs(adapter, work.jobs, budget_s=budget_s)


async def judge_submission(
    session: AsyncSession,
    submission_id: uuid.UUID,
    adapter: JudgeAdapter | None = None,
    *,
    budget_s: float = POLL_BUDGET_S,
) -> str:
    """Single-session variant (tests, tooling). Returns the verdict or an outcome string."""
    adapter = adapter or get_judge_adapter()
    if not await claim(session, submission_id):
        return "not_claimed"
    work = await load_work(session, submission_id)
    try:
        results = await execute(adapter, work, budget_s)
    except JudgeTimeout:
        return await _release(session, work, timed_out=True)
    except JudgeUnavailable:
        return await _release(session, work, timed_out=False)
    return await record(session, work, results)


async def judge_by_id(
    submission_id: uuid.UUID,
    adapter: JudgeAdapter | None = None,
    factory: async_sessionmaker[AsyncSession] | None = None,
) -> str:
    """Production path: short transactions around the (slow) provider calls."""
    adapter = adapter or get_judge_adapter()
    factory = factory or get_sessionmaker()
    async with factory() as s, s.begin():
        if not await claim(s, submission_id):
            return "not_claimed"
        work = await load_work(s, submission_id)
    try:
        results = await execute(adapter, work)
    except (JudgeTimeout, JudgeUnavailable) as e:
        async with factory() as s, s.begin():
            return await _release(s, work, timed_out=isinstance(e, JudgeTimeout))
    async with factory() as s, s.begin():
        return await record(s, work, results)


_PICK_SQL = text(
    """
    SELECT id FROM code_submissions
     WHERE status = 'queued'
     ORDER BY CASE queue_name WHEN 'judge_assessment' THEN 0 WHEN 'judge_submit' THEN 1 ELSE 2 END, queued_at
     LIMIT :n
     FOR UPDATE SKIP LOCKED
    """
)


async def pending_ids(session: AsyncSession, limit: int) -> list[uuid.UUID]:
    await system_context(session, JOB)
    await session.execute(
        update(CodeSubmission)
        .where(CodeSubmission.status == "running", CodeSubmission.started_at < utcnow() - STALE_RUNNING)
        .values(status="queued", started_at=None)
    )
    return [r[0] for r in (await session.execute(_PICK_SQL, {"n": limit})).all()]


async def process_pending(
    adapter: JudgeAdapter | None = None,
    *,
    limit: int = 16,
    factory: async_sessionmaker[AsyncSession] | None = None,
) -> dict[uuid.UUID, str]:
    adapter = adapter or get_judge_adapter()
    factory = factory or get_sessionmaker()
    async with factory() as s, s.begin():
        ids = await pending_ids(s, limit)
    out: dict[uuid.UUID, str] = {}
    for sid in ids:
        try:
            out[sid] = await judge_by_id(sid, adapter, factory)
        except Exception as e:  # keep the loop alive; the row stays running → re-queued when stale
            log.error("coding.judge_failed", submission_id=str(sid), error=type(e).__name__)
            out[sid] = "error"
    return out


async def _main(once: bool, batch: int, interval: float) -> None:
    import app.modules.coding  # noqa: F401  (registers the production safety check)
    from app.core.config import get_settings
    from app.core.startup_checks import run_startup_checks

    run_startup_checks(get_settings())
    crypto.get_testcase_keyring()  # fail fast on a bad key in production
    adapter = get_judge_adapter()
    log.info("coding.worker_started", provider=adapter.provider)
    while True:
        done = await process_pending(adapter, limit=batch)
        if once:
            return
        if not done:
            await asyncio.sleep(interval)


def main() -> None:
    ap = argparse.ArgumentParser(description="Tech Drona judge worker (worker-judge only)")
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--batch", type=int, default=16)
    ap.add_argument("--interval", type=float, default=1.0)
    a = ap.parse_args()
    asyncio.run(_main(a.once, a.batch, a.interval))


if __name__ == "__main__":  # pragma: no cover
    main()
