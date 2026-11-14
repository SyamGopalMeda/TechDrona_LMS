"""Store-neutral read API of assessments for other modules.

Round 3: one code path for both stores. Each function runs the same SQLAlchemy statement the caller
ran before, through ``assessments.datastore`` (Postgres session unchanged on ``postgres``; the
SQL-on-Firestore engine on ``firestore``). When the caller has no usable session (another module's
Firestore route passes ``db.NO_POSTGRES``), a ``MemoryTx`` carrying the request principal's RLS
context (``placement.rls``) is used, so RLS is applied exactly as on Postgres.

| Function | Replaces (caller) |
|---|---|
| ``attempt_lifetime`` | ``SELECT user_id, started_at, ... FROM test_attempts`` (analytics/service.py) |
| ``attempt_org_of_user`` | ``select(TestAttempt.organization_id)`` (analytics/hooks.py, coding) |
| ``get_attempt`` | ``session.get(TestAttempt)`` (support/router.py) |
| ``has_attempt_in_progress`` | the ``in_progress`` lookup in support/service.py ``derive_priority`` |
| ``attempt_bound_session_ids`` | the ``bound_session_id`` foreign key (core Firestore retention) |
| ``count_attempts`` / ``count_attempted_tests`` | ``test_attempts`` counts in wiring.py |
| ``best_result`` | ``final_test_lookup`` in wiring.py |
| ``test_linkable`` / ``search_tests`` | ``Test`` lookups in paths/service.py |
| ``attempt_scored_facts`` | the attempt/result/test join in paths ``on_attempt_scored`` |
| ``fixed_versions_in_live_tests`` | placement practice hold-back |
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator, Iterable
from contextlib import asynccontextmanager
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.assessments import datastore as adb
from app.modules.assessments.models import AttemptResult, Test, TestAttempt, TestSection, TestSectionRule


@asynccontextmanager
async def _sess(session: Any, *, system: bool = False) -> AsyncGenerator[Any]:
    """The session the statements run on.

    * Postgres store: the caller's session (``system``: inside ``system_context``), unchanged.
    * Firestore store, caller passed the engine's ``MemoryTx``: that one (same unit of work).
    * Firestore store, any other caller session (``db.NO_POSTGRES``, ``None``, another module's
      session object): a private read-only ``MemoryTx`` carrying the caller's RLS scope (from the
      session's GUCs when it can answer them, else the request principal; platform for
      ``system``). Nothing is ever sent to Postgres."""
    from app.modules.placement.rls import memory_gucs

    if not adb.on_firestore() or memory_gucs(session) is not None:
        if system and session:
            from app.core.db import system_context

            async with system_context(session, "assessments.public"):
                yield session
            return
        yield session
        return
    from app.core.db import set_rls_context
    from app.core.firestore.sqlstore import MemoryTx
    from app.modules.placement.repo_firestore import visibility

    vis = await visibility(session)
    tx = MemoryTx()
    await set_rls_context(
        tx,  # type: ignore[arg-type]
        user_id=vis.user_id or None,
        org_ids=vis.org_ids,
        is_platform=vis.is_platform or system,
    )
    try:
        yield tx
    finally:
        await tx.rollback()


async def get_attempt(session: AsyncSession, attempt_id: uuid.UUID) -> TestAttempt | None:
    async with _sess(session) as s:
        return await adb.get(s, TestAttempt, attempt_id)


async def attempt_lifetime(
    session: AsyncSession, attempt_id: uuid.UUID
) -> tuple[uuid.UUID, datetime, datetime | None, datetime | None] | None:
    """``(user_id, started_at, submitted_at, deadline_at)`` of an attempt, or ``None``."""
    async with _sess(session) as s:
        row = (
            await adb.execute(
                s,
                select(
                    TestAttempt.user_id,
                    TestAttempt.started_at,
                    TestAttempt.submitted_at,
                    TestAttempt.deadline_at,
                ).where(TestAttempt.id == attempt_id),
            )
        ).first()
    return (row[0], row[1], row[2], row[3]) if row else None


async def attempt_org_of_user(
    session: AsyncSession, attempt_id: uuid.UUID, user_id: uuid.UUID
) -> uuid.UUID | None:
    async with _sess(session) as s:
        return (
            await adb.execute(
                s,
                select(TestAttempt.organization_id).where(
                    TestAttempt.id == attempt_id, TestAttempt.user_id == user_id
                ),
            )
        ).scalar_one_or_none()


async def attempt_bound_session_ids(session: Any, session_ids: Iterable[uuid.UUID]) -> set[uuid.UUID]:
    """Which of ``session_ids`` a test attempt references as ``bound_session_id`` (the
    ``test_attempts.bound_session_id REFERENCES auth_sessions(id)`` foreign key, no ON DELETE:
    Postgres refuses to delete such a session). Platform scope (retention job)."""
    ids = list(dict.fromkeys(session_ids))
    out: set[uuid.UUID] = set()
    async with _sess(session, system=True) as s:
        for i in range(0, len(ids), 30):
            rows = await adb.execute(
                s,
                select(TestAttempt.bound_session_id).where(TestAttempt.bound_session_id.in_(ids[i : i + 30])),
            )
            out.update(v for v in rows.scalars() if v is not None)
    return out


async def has_attempt_in_progress(session: AsyncSession, user_id: uuid.UUID) -> bool:
    async with _sess(session) as s:
        running = (
            await adb.execute(
                s,
                select(TestAttempt.id)
                .where(TestAttempt.user_id == user_id, TestAttempt.status == "in_progress")
                .limit(1),
            )
        ).scalar_one_or_none()
    return running is not None


async def count_attempts(session: AsyncSession, user_id: uuid.UUID, test_ids: Iterable[uuid.UUID]) -> int:
    tests = list(test_ids)
    if not tests:
        return 0
    async with _sess(session) as s:
        n = (
            await adb.execute(
                s,
                select(func.count())
                .select_from(TestAttempt)
                .where(TestAttempt.user_id == user_id, TestAttempt.test_id.in_(tests)),
            )
        ).scalar_one()
    return int(n or 0)


async def count_attempted_tests(
    session: AsyncSession, user_id: uuid.UUID, test_ids: Iterable[uuid.UUID]
) -> int:
    tests = list(test_ids)
    if not tests:
        return 0
    async with _sess(session) as s:
        rows = (
            await adb.execute(
                s,
                select(TestAttempt.test_id).where(
                    TestAttempt.user_id == user_id, TestAttempt.test_id.in_(tests)
                ),
            )
        ).all()
    return len({r[0] for r in rows})  # count(DISTINCT test_id)


async def best_result(
    session: AsyncSession, user_id: uuid.UUID, test_id: uuid.UUID
) -> tuple[uuid.UUID, float] | None:
    """Best graded attempt: highest percentage, then earliest ``graded_at``."""
    async with _sess(session) as s:
        row = (
            await adb.execute(
                s,
                select(AttemptResult.attempt_id, AttemptResult.percentage)
                .where(AttemptResult.user_id == user_id, AttemptResult.test_id == test_id)
                .order_by(AttemptResult.percentage.desc(), AttemptResult.graded_at)
                .limit(1),
            )
        ).first()
    return (row[0], float(row[1])) if row else None


async def test_linkable(session: AsyncSession, test_id: uuid.UUID, org_id: uuid.UUID) -> bool:
    """The test exists in ``org_id`` or is global (paths step link check)."""
    async with _sess(session) as s:
        found = (
            await adb.execute(
                s,
                select(Test.id).where(
                    Test.id == test_id, or_(Test.organization_id == org_id, Test.organization_id.is_(None))
                ),
            )
        ).scalar_one_or_none()
    return found is not None


async def search_tests(
    session: AsyncSession, org_id: uuid.UUID, q: str | None, limit: int = 25
) -> list[tuple[uuid.UUID, str, int | None]]:
    """``(id, title, duration_seconds)`` of draft/published tests of ``org_id`` or global whose
    title contains ``q`` (case-insensitive), newest first."""
    like = "%" + (q or "").replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
    async with _sess(session) as s:
        res = await adb.execute(
            s,
            select(Test.id, Test.title, Test.duration_seconds)
            .where(
                or_(Test.organization_id == org_id, Test.organization_id.is_(None)),
                Test.status.in_(("published", "draft")),
                Test.title.ilike(like),
            )
            .order_by(Test.created_at.desc())
            .limit(limit),
        )
        return [(r[0], r[1], r[2]) for r in res.all()]


async def attempt_scored_facts(
    session: AsyncSession, attempt_id: uuid.UUID
) -> tuple[uuid.UUID, uuid.UUID, str, bool | None, Decimal | None] | None:
    """``(user_id, test_id, integrity_status, result.passed, test.pass_percentage)`` for an attempt
    that has a result (inner joins, as before), else ``None``."""
    async with _sess(session) as s:
        row = (
            await adb.execute(
                s,
                select(
                    TestAttempt.user_id,
                    TestAttempt.test_id,
                    TestAttempt.integrity_status,
                    AttemptResult.passed,
                    Test.pass_percentage,
                )
                .join(AttemptResult, AttemptResult.attempt_id == TestAttempt.id)
                .join(Test, Test.id == TestAttempt.test_id)
                .where(TestAttempt.id == attempt_id),
            )
        ).first()
    return (row[0], row[1], row[2], row[3], row[4]) if row else None


async def fixed_versions_in_live_tests(
    session: AsyncSession, pool: list[uuid.UUID], question_of: dict[uuid.UUID, uuid.UUID] | None = None
) -> set[uuid.UUID]:
    """Question versions of ``pool`` that a published graded test (any kind but ``practice_set``)
    uses as a fixed question, by version or by question (``placement.practice`` hold-back), in a
    system context. ``question_of`` maps version -> question (the question branch)."""
    if not pool:
        return set()
    async with _sess(session, system=True) as s:
        rows = (
            await adb.execute(
                s,
                select(TestSectionRule.question_version_id, TestSectionRule.question_id)
                .join(TestSection, TestSection.id == TestSectionRule.test_section_id)
                .join(Test, Test.id == TestSection.test_id)
                .where(
                    Test.status == "published",
                    Test.test_kind != "practice_set",
                    TestSectionRule.rule_type == "fixed",
                ),
            )
        ).all()
    fixed_v = {r[0] for r in rows if r[0] is not None}
    fixed_q = {r[1] for r in rows if r[1] is not None}
    qmap = question_of or {}
    return {v for v in pool if v in fixed_v or qmap.get(v) in fixed_q}
