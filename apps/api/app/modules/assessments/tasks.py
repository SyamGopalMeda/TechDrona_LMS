"""Background jobs for assessments.

``sweep_expired_attempts`` is the DB safety sweeper (system-architecture §8.4): it auto-submits
(``submit_reason = deadline``) and scores every in-progress attempt whose ``deadline_at + grace``
has passed. It is idempotent and concurrency-safe (``FOR UPDATE SKIP LOCKED`` + status guard),
so it can run alongside the lazy expiry done by the attempt endpoints.

Run: ``python -m app.modules.assessments.tasks [--once] [--interval 5]``, or Celery task
``assessments.deadline_sweeper`` scheduled by beat every 5 s on the ``critical`` queue
(registered here at import). The Redis ZSET fast path remains Planned.
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timedelta

from celery import shared_task
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_sessionmaker, system_context
from app.core.jobs import register_periodic, run_async
from app.core.time import utcnow
from app.modules.assessments.attempts import advance_sections, finalize
from app.modules.assessments.models import AttemptSection, Test, TestAttempt

JOB = "assessments.deadline_sweeper"


async def sweep_expired_attempts(
    session: AsyncSession, *, now: datetime | None = None, limit: int = 200
) -> int:
    """Close overdue attempts in the caller's transaction (sets the system RLS context)."""
    await system_context(session, JOB)
    now = now or utcnow()
    grace = func.make_interval(0, 0, 0, 0, 0, 0, Test.grace_seconds)
    rows = (
        await session.execute(
            select(TestAttempt, Test)
            .join(Test, Test.id == TestAttempt.test_id)
            .where(
                TestAttempt.status == "in_progress",
                TestAttempt.deadline_at.is_not(None),
                TestAttempt.deadline_at + grace < now,
            )
            .order_by(TestAttempt.deadline_at)
            .limit(limit)
            .with_for_update(of=TestAttempt, skip_locked=True)
        )
    ).all()
    n = 0
    for attempt, test in rows:
        if attempt.status != "in_progress":
            continue
        await finalize(session, attempt, test, "deadline")
        n += 1
    # BE-10: sequential tests whose active section timed out (the last one -> auto-submit).
    sec_rows = (
        await session.execute(
            select(TestAttempt, Test)
            .join(Test, Test.id == TestAttempt.test_id)
            .where(
                TestAttempt.status == "in_progress",
                Test.navigation_mode != "free",
                select(AttemptSection.attempt_id)
                .where(
                    AttemptSection.attempt_id == TestAttempt.id,
                    AttemptSection.status == "active",
                    AttemptSection.deadline_at.is_not(None),
                    AttemptSection.deadline_at + grace < now,
                )
                .exists(),
            )
            .limit(limit)
            .with_for_update(of=TestAttempt, skip_locked=True)
        )
    ).all()
    for attempt, test in sec_rows:
        if attempt.status != "in_progress":
            continue
        await advance_sections(session, attempt, test, now)
        if attempt.status != "in_progress":
            n += 1
    return n


async def run_once(limit: int = 200) -> int:
    async with get_sessionmaker()() as session, session.begin():
        await session.execute(text("SELECT 1"))
        return await sweep_expired_attempts(session, limit=limit)


@shared_task(name=JOB, ignore_result=True)
def deadline_sweeper_task() -> int:
    return run_async(run_once())


register_periodic(JOB, JOB, 5.0, options={"queue": "critical", "expires": 10})


async def _loop(interval: float) -> None:  # pragma: no cover - process entry point
    while True:
        await run_once()
        await asyncio.sleep(interval)


def main() -> None:  # pragma: no cover - process entry point
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--once", action="store_true")
    p.add_argument("--interval", type=float, default=float(timedelta(seconds=5).total_seconds()))
    args = p.parse_args()
    if args.once:
        print(asyncio.run(run_once()))
    else:
        asyncio.run(_loop(args.interval))


if __name__ == "__main__":  # pragma: no cover
    main()
