"""Outbox relay (handlers, idempotent retry, dead letter), periodic registry, Celery app."""

from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import jobs
from app.core.ids import uuid7
from app.core.models import OutboxEvent
from app.core.outbox import OutboxMessage, emit_event, register_handler, relay_pending, unregister_handler


async def _quiesce(db: AsyncSession) -> None:
    """Mark any pre-existing pending rows dispatched (rolled back with the test)."""
    await db.execute(
        update(OutboxEvent).where(OutboxEvent.dispatched_at.is_(None)).values(dispatched_at=func.now())
    )


@pytest.fixture
def handler_registry() -> Any:
    registered: list[tuple[str, Any]] = []

    def _reg(event_type: str, fn: Any) -> None:
        register_handler(event_type, fn)
        registered.append((event_type, fn))

    yield _reg
    for et, fn in registered:
        unregister_handler(et, fn)


async def test_handler_invoked_once(db: AsyncSession, handler_registry) -> None:
    await _quiesce(db)
    calls: list[OutboxMessage] = []

    async def h(session: AsyncSession, msg: OutboxMessage) -> None:
        calls.append(msg)

    handler_registry("probe.relay_once", h)
    handler_registry("probe.relay_once", h)  # duplicate registration is a no-op
    agg = uuid7()
    eid = await emit_event(db, "probe.relay_once", {"n": 1}, aggregate_type="probe", aggregate_id=agg)

    r1 = await relay_pending(db)
    r2 = await relay_pending(db)
    assert (r1.dispatched, r1.failed) == (1, 0)
    assert (r2.dispatched, r2.failed) == (0, 0)
    assert len(calls) == 1
    assert calls[0].id == eid and calls[0].payload == {"n": 1} and calls[0].aggregate_id == agg
    assert calls[0].attempt == 1
    row = (await db.execute(select(OutboxEvent).where(OutboxEvent.id == eid))).scalar_one()
    assert row.dispatched_at is not None and row.attempts == 1 and row.last_error is None


async def test_failed_handler_rolls_back_and_retries_idempotently(db: AsyncSession, handler_registry) -> None:
    await _quiesce(db)
    attempts: list[int] = []

    async def flaky(session: AsyncSession, msg: OutboxMessage) -> None:
        attempts.append(msg.attempt)
        # DB side effect inside the handler's savepoint
        await emit_event(
            session, "probe.side_effect", {"src": str(msg.id)}, aggregate_type="probe", aggregate_id=msg.id
        )
        if msg.attempt == 1:
            raise RuntimeError("transient")

    handler_registry("probe.relay_flaky", flaky)
    eid = await emit_event(db, "probe.relay_flaky", {}, aggregate_type="probe", aggregate_id=uuid7())

    async def side_effects() -> int:
        return int(
            (
                await db.execute(
                    select(func.count())
                    .select_from(OutboxEvent)
                    .where(OutboxEvent.event_type == "probe.side_effect", OutboxEvent.aggregate_id == eid)
                )
            ).scalar_one()
        )

    r1 = await relay_pending(db)
    assert (r1.dispatched, r1.failed) == (0, 1)
    row = (await db.execute(select(OutboxEvent).where(OutboxEvent.id == eid))).scalar_one()
    assert row.dispatched_at is None and row.attempts == 1 and "transient" in (row.last_error or "")
    assert await side_effects() == 0  # rolled back with the savepoint

    r2 = await relay_pending(db)
    assert r2.dispatched >= 1 and r2.failed == 0
    assert await side_effects() == 1
    await relay_pending(db)  # side-effect event has no handler -> marked dispatched, no re-run
    await relay_pending(db)
    assert attempts == [1, 2]
    assert await side_effects() == 1


async def test_dead_letter_after_max_attempts(db: AsyncSession, handler_registry) -> None:
    await _quiesce(db)
    calls = 0

    async def broken(session: AsyncSession, msg: OutboxMessage) -> None:
        nonlocal calls
        calls += 1
        raise ValueError("permanent")

    handler_registry("probe.relay_broken", broken)
    eid = await emit_event(db, "probe.relay_broken", {}, aggregate_type="probe", aggregate_id=uuid7())
    for _ in range(4):
        await relay_pending(db, max_attempts=2)
    assert calls == 2
    row = (await db.execute(select(OutboxEvent).where(OutboxEvent.id == eid))).scalar_one()
    assert row.dispatched_at is None and row.attempts == 2


async def test_event_without_handler_is_marked_dispatched(db: AsyncSession) -> None:
    await _quiesce(db)
    eid = await emit_event(db, "probe.nobody_listens", {}, aggregate_type="probe", aggregate_id=uuid7())
    r = await relay_pending(db)
    assert r.skipped_no_handler == 1
    row = (await db.execute(select(OutboxEvent).where(OutboxEvent.id == eid))).scalar_one()
    assert row.dispatched_at is not None


def test_register_handler_rejects_bad_event_type() -> None:
    async def h(session: Any, msg: Any) -> None: ...

    with pytest.raises(ValueError):
        register_handler("NotDotted", h)


def test_periodic_registry_builds_beat_schedule() -> None:
    from celery.schedules import crontab

    class FakeTask:
        name = "probe.task_obj"

    try:
        jobs.register_periodic("probe.every_minute", "probe.task", 60.0, options={"queue": "default"})
        jobs.register_periodic("probe.nightly", FakeTask(), crontab(hour=2, minute=0), kwargs={"x": 1})
        jobs.register_periodic("probe.td", "probe.task", timedelta(minutes=5), args=(1,))
        sched = jobs.beat_schedule()
        assert sched["probe.every_minute"] == {
            "task": "probe.task",
            "schedule": 60.0,
            "options": {"queue": "default"},
        }
        assert sched["probe.nightly"]["task"] == "probe.task_obj" and sched["probe.nightly"]["kwargs"] == {
            "x": 1
        }
        assert sched["probe.td"]["args"] == (1,)
        with pytest.raises(ValueError):
            jobs.register_periodic("probe.bad", "probe.task", 0)
        with pytest.raises(TypeError):
            jobs.register_periodic("probe.bad", object(), 10)
    finally:
        for n in ("probe.every_minute", "probe.nightly", "probe.td"):
            jobs.unregister_periodic(n)


def test_celery_app_config_and_core_jobs() -> None:
    from app import worker
    from app.core.config import get_settings

    capp = worker.celery_app
    assert capp.conf.broker_url == get_settings().REDIS_QUEUE_URL
    assert capp.conf.task_ignore_result is True
    assert worker.OUTBOX_RELAY_TASK in capp.tasks and worker.AUDIT_SEAL_TASK in capp.tasks
    sched = capp.conf.beat_schedule
    assert sched["core.outbox_relay"]["task"] == worker.OUTBOX_RELAY_TASK
    assert sched["core.audit_seal"]["task"] == worker.AUDIT_SEAL_TASK


def test_outbox_relay_task_end_to_end(committed_engine_sync_urls: str) -> None:
    """Runs the real Celery task body (own engine, committed transaction)."""
    from app import worker

    seen: list[str] = []
    event_type = "probe.relay_task"

    async def h(session: AsyncSession, msg: OutboxMessage) -> None:
        seen.append(str(msg.id))

    async def _emit() -> str:
        from app.core.db import make_engine

        eng = make_engine(committed_engine_sync_urls)
        try:
            async with eng.begin() as conn:
                s = AsyncSession(bind=conn)
                eid = await emit_event(s, event_type, {}, aggregate_type="probe", aggregate_id=uuid7())
                await s.flush()
                return str(eid)
        finally:
            await eng.dispose()

    async def _cleanup(eid: str) -> Any:
        from sqlalchemy import delete

        from app.core.db import make_engine

        eng = make_engine(committed_engine_sync_urls)
        try:
            async with eng.begin() as conn:
                row = (
                    await conn.execute(select(OutboxEvent.dispatched_at).where(OutboxEvent.id == eid))
                ).scalar_one()
                await conn.execute(delete(OutboxEvent).where(OutboxEvent.id == eid))
                return row
        finally:
            await eng.dispose()

    register_handler(event_type, h)
    try:
        eid = asyncio.run(_emit())
        out = worker.outbox_relay.apply().get()
        assert out["dispatched"] >= 1
        out2 = worker.outbox_relay.apply().get()
        assert eid not in seen[1:] and seen.count(eid) == 1, out2
        assert asyncio.run(_cleanup(eid)) is not None
    finally:
        unregister_handler(event_type, h)


@pytest.fixture
def committed_engine_sync_urls() -> str:
    from app.core.config import get_settings

    return get_settings().DATABASE_URL
