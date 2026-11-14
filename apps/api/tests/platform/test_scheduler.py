"""The single Firebase dispatcher (``app.core.scheduler``) and the event kicks / work hints
(``app.core.jobhints``) that replaced the per-entry scheduled functions and the sub-minute loops."""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from celery import Celery

from app.core import cloudtasks, jobhints, jobs, scheduler
from app.core.firestore.collections import (
    CollectionSpec,
    physical_name,
    register_collection,
    unregister_collection,
)

SCHEDULES = Path(__file__).resolve().parents[4] / "functions-lms" / "schedules.json"
WEEK_START = datetime(2026, 11, 15, tzinfo=UTC)  # a Sunday, 00:00 UTC


def _rec(out: list[Any], shape: Callable[..., Any]) -> Callable[..., str]:
    """A fake ``cloudtasks.enqueue_impl`` that records ``shape(*args)`` (nothing is sent)."""

    def enqueue(*args: Any) -> str:
        out.append(shape(*args))
        return "t"

    return enqueue


# --------------------------------------------------------------------------- cadence


def _oracle(job: Any) -> Any:
    """Is ``job`` due at minute ``at`` -- computed from the beat schedule itself, not from the cron
    string the dispatcher uses (Celery crontab fields: day_of_week 0 = Sunday)."""
    sched = job.schedule
    seconds = cloudtasks._interval_seconds(sched)
    if seconds is not None:
        if seconds < 60:  # sub-minute: the dispatcher's every-minute backstop (+ event kicks)
            return lambda at: True
        return lambda at: int(at.timestamp()) % int(seconds) == 0
    return lambda at: (
        at.minute in sched.minute
        and at.hour in sched.hour
        and at.day in sched.day_of_month
        and at.month in sched.month_of_year
        and (at.weekday() + 1) % 7 in sched.day_of_week
    )


def test_due_selection_equals_the_old_cadence_for_every_entry_over_a_week() -> None:
    import app.worker  # noqa: F401 - registers every beat entry

    entries = scheduler.entries()
    assert [e.job for e in entries] == [e["job"] for e in json.loads(SCHEDULES.read_text(encoding="utf-8"))]
    by_name = {j.name: j for j in cloudtasks.firebase_jobs()}
    oracles = {e.job: _oracle(by_name[e.job]) for e in entries}
    counts = dict.fromkeys(oracles, 0)
    for m in range(7 * 1440):
        at = WEEK_START + timedelta(minutes=m)
        due = {e.job for e in scheduler.due_entries(at, entries)}
        expected = {name for name, f in oracles.items() if f(at)}
        assert due == expected, at
        for name in due:
            counts[name] += 1
    # spot checks of the per-week totals
    assert counts["core.outbox_relay"] == 7 * 1440
    assert counts["commerce.order_expiry"] == 7 * 288
    assert counts["analytics.daily_aggregator"] == 7 * 96
    assert counts["commerce.reconciliation"] == 7 * 24
    assert counts["notifications.renewal_reminders"] == 7
    assert counts["security.purge_closed_cases"] == 1


@pytest.mark.parametrize(
    ("cron", "at", "due"),
    [
        ("*/15 * * * *", "2026-11-15T10:45", True),
        ("*/15 * * * *", "2026-11-15T10:46", False),
        ("30 21 * * *", "2026-11-15T21:30", True),
        ("0 23 * * 0", "2026-11-15T23:00", True),  # Sunday
        ("0 23 * * 0", "2026-11-16T23:00", False),
        ("0 23 * * 7", "2026-11-15T23:00", True),
        ("0 0 1 * 1", "2026-11-16T00:00", True),  # dom OR dow (Vixie)
        ("0 0 1-5/2 * *", "2026-11-03T00:00", True),
        ("0 0 1-5/2 * *", "2026-11-04T00:00", False),
    ],
)
def test_cron_matches(cron: str, at: str, due: bool) -> None:
    assert scheduler.cron_matches(cron, datetime.fromisoformat(at).replace(tzinfo=UTC)) is due


def test_gates_are_well_formed() -> None:
    import app.worker  # noqa: F401
    from app.core.firestore import core_store  # noqa: F401 - registers outbox_events
    from app.core.firestore.collections import get_spec
    from app.core.models_registry import _optional_import, module_names

    for name in module_names():
        _optional_import(f"app.modules.{name}.store_specs")

    by_job = {e.job: e for e in scheduler.entries()}
    for job, gate in scheduler.GATES.items():
        e = by_job[job]
        step = scheduler._step_minutes(e.cron)
        assert step is not None, job  # only every-N-minutes entries are gated
        m = scheduler.backstop_minute(job, e.cron)
        assert 0 <= m < 60 and m % step == 0, job
        hour = [WEEK_START + timedelta(minutes=i) for i in range(60)]
        backstops = [at for at in hour if scheduler.is_backstop(job, e.cron, at)]
        assert len(backstops) == 1 and scheduler.cron_matches(e.cron, backstops[0])  # full run hourly
        for c in gate.watch:
            get_spec(c)  # a registered logical collection (the store hook sees exactly these names)


# --------------------------------------------------------------------------- tick (no hints)


@pytest.fixture
def capp() -> Celery:
    app = Celery("t", broker="memory://", set_as_current=False)
    app.conf.task_ignore_result = True
    calls: list[str] = []

    @app.task(name="schedtest.ok", shared=False)
    def ok(tag: str = "") -> dict[str, int]:
        calls.append(tag)
        return {"n": 0}

    @app.task(name="schedtest.fail", shared=False)
    def fail() -> None:
        raise RuntimeError("boom")

    @app.task(name="schedtest.slow", shared=False)
    def slow() -> None:
        time.sleep(0.05)

    app.calls = calls
    return app


def _entries(*items: tuple[str, str, str, str]) -> list[scheduler.Entry]:
    return [
        scheduler.Entry(job, task, cron, None, queue, (job,) if task == "schedtest.ok" else ())
        for job, task, cron, queue in items
    ]


def test_tick_runs_due_entries_inline_and_hands_off_maintenance(
    capp: Celery, monkeypatch: pytest.MonkeyPatch, settings_env: pytest.MonkeyPatch
) -> None:
    sent: list[dict[str, Any]] = []
    monkeypatch.setattr(
        cloudtasks, "enqueue_impl", _rec(sent, lambda fn, loc, data, delay: {"fn": fn, **data})
    )
    monkeypatch.setattr(
        scheduler,
        "entries",
        lambda: _entries(
            ("a.every", "schedtest.ok", "* * * * *", "default"),
            ("b.five", "schedtest.ok", "*/5 * * * *", "critical"),
            ("c.fail", "schedtest.fail", "* * * * *", "default"),
            ("d.maint", "schedtest.ok", "30 21 * * *", "maintenance"),
        ),
    )
    r = scheduler.tick(capp, datetime(2026, 11, 15, 21, 30, 42, tzinfo=UTC))
    assert r.at == datetime(2026, 11, 15, 21, 30, tzinfo=UTC)
    assert r.ran == ["b.five", "a.every"]  # critical queue first
    assert r.failed == ["c.fail"] and r.handed_off == ["d.maint"] and r.skipped == []
    assert capp.calls == ["b.five", "a.every"]
    assert sent == [
        {
            "fn": "lmsTasksMaintenance",
            "task": "schedtest.ok",
            "args": ["d.maint"],
            "kwargs": {},
            "periodic": "d.maint",
            "periodic_loop": False,
        }
    ]
    r = scheduler.tick(capp, datetime(2026, 11, 15, 21, 31, tzinfo=UTC))
    assert r.ran == ["a.every"] and r.handed_off == []


def test_tick_hands_off_what_exceeds_the_inline_budget(
    capp: Celery, monkeypatch: pytest.MonkeyPatch, settings_env: pytest.MonkeyPatch
) -> None:
    sent: list[str] = []
    monkeypatch.setattr(cloudtasks, "enqueue_impl", _rec(sent, lambda fn, loc, data, delay: fn))
    monkeypatch.setattr(
        scheduler,
        "entries",
        lambda: _entries(
            ("a.slow", "schedtest.slow", "* * * * *", "default"),
            ("b.next", "schedtest.ok", "* * * * *", "critical"),
            ("c.next", "schedtest.ok", "* * * * *", "default"),
        ),
    )
    clock = iter([0.0, 0.0, 0.0, 100.0])  # tick start, then one reading before each entry
    monkeypatch.setattr(scheduler.time, "monotonic", lambda: next(clock))
    r = scheduler.tick(capp, datetime(2026, 11, 15, 1, 0, tzinfo=UTC), inline_budget_s=45.0)
    assert r.ran == ["b.next", "a.slow"] and r.handed_off == ["c.next"]  # never skipped
    assert sent == ["lmsTasks"]


def test_hybrid_stack_keeps_the_sub_minute_loops(
    capp: Celery, monkeypatch: pytest.MonkeyPatch, settings_env: pytest.MonkeyPatch
) -> None:
    """Not event mode (here: Celery backend / Postgres present): a sub-minute entry is handed to its
    queue function every minute with ``periodic_loop`` -> loops 50 s there, as before."""
    sent: list[dict[str, Any]] = []
    monkeypatch.setattr(
        cloudtasks, "enqueue_impl", _rec(sent, lambda fn, loc, data, delay: {"fn": fn, **data})
    )
    monkeypatch.setattr(
        scheduler,
        "entries",
        lambda: [scheduler.Entry("x.fast", "schedtest.ok", "* * * * *", 5.0, "critical")],
    )
    assert not scheduler.event_mode()
    r = scheduler.tick(capp, datetime(2026, 11, 15, 1, 0, tzinfo=UTC))
    assert (
        r.handed_off == ["x.fast"]
        and sent[0]["periodic_loop"] is True
        and sent[0]["fn"] == "lmsTasksCritical"
    )


def test_run_handed_off_logs_periodic_failures_but_raises_plain_tasks(capp: Celery) -> None:
    jobs.register_periodic("schedtest.failing", "schedtest.fail", 60.0)
    try:
        cloudtasks.run_handed_off(
            capp, {"task": "schedtest.fail", "periodic": "schedtest.failing"}
        )  # no raise
        with pytest.raises(RuntimeError):
            cloudtasks.run_handed_off(capp, {"task": "schedtest.fail"})
        cloudtasks.run_handed_off(capp, {"task": "schedtest.ok", "args": ["plain"]})
        assert capp.calls == ["plain"]
    finally:
        jobs.unregister_periodic("schedtest.failing")


def test_exact_eta_uses_schedule_time(monkeypatch: pytest.MonkeyPatch) -> None:
    got: list[Any] = []
    monkeypatch.setattr(cloudtasks, "enqueue_impl", _rec(got, lambda fn, loc, data, delay: delay))
    eta = datetime.now(UTC) + timedelta(seconds=7.5)
    cloudtasks.send_task("x.y", eta=eta, queue="critical")
    assert 6.5 < got[0] < 7.6 and got[0] != int(got[0])


# --------------------------------------------------------------------------- event mode (emulator)


TEST_COLL = "schedtest_items"


@pytest.fixture
def event_mode(firestore_emulator: str, settings_env: pytest.MonkeyPatch) -> Iterator[list[dict[str, Any]]]:
    """Firebase final stack on the emulator: Cloud Tasks backend, no Postgres. Yields the list
    of enqueued Cloud Tasks (nothing is sent)."""
    from tests.firestore.conftest import TEST_PROJECT, clear_emulator

    clear_emulator(firestore_emulator)
    for k, v in {
        "TD_TASKS_BACKEND": "cloudtasks",
        "DATABASE_URL": "",
        "FIRESTORE_EMULATOR_HOST": firestore_emulator,
        "FIREBASE_PROJECT_ID": TEST_PROJECT,
        "APP_ENV": "test",
    }.items():
        settings_env.setenv(k, v)
    from app.core.config import reset_settings_cache

    reset_settings_cache()
    sent: list[dict[str, Any]] = []
    settings_env.setattr(
        cloudtasks,
        "enqueue_impl",
        _rec(sent, lambda fn, loc, data, delay: {"fn": fn, "delay": delay, **data}),
    )
    register_collection(CollectionSpec(TEST_COLL, "system"))
    jobhints.reset_for_tests()
    scheduler._watched.cache_clear()
    try:
        yield sent
    finally:
        jobhints.reset_for_tests()
        scheduler._watched.cache_clear()
        unregister_collection(TEST_COLL)


def _write(doc_id: str, data: dict[str, Any]) -> None:
    from app.core.firestore.store import ScopedStore

    async def body(tx: Any) -> None:
        tx.raw_set(TEST_COLL, doc_id, data)

    jobs.run_async(ScopedStore.system("schedtest").run_transaction(body))


def _hint_doc() -> dict[str, Any]:
    from app.core.firestore.store import ScopedStore

    async def get() -> dict[str, Any]:
        snap = await jobhints.hint_ref(ScopedStore.system("schedtest").client).get()
        return snap.to_dict() or {}

    return jobs.run_async(get())


def test_event_mode_switch(event_mode: list[dict[str, Any]]) -> None:
    assert scheduler.event_mode() and jobhints.active()


def test_gated_job_is_skipped_while_idle_and_woken_by_a_write(
    event_mode: list[dict[str, Any]], capp: Celery, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(
        scheduler.GATES,
        "x.gated",
        scheduler.Gate((TEST_COLL,), scheduler._none_of(TEST_COLL, ("status", "==", "pending"))),
    )
    scheduler._watched.cache_clear()
    monkeypatch.setattr(
        scheduler,
        "entries",
        lambda: [scheduler.Entry("x.gated", "schedtest.ok", "* * * * *", None, "default", ("x",))],
    )
    backstop = scheduler.backstop_minute("x.gated", "* * * * *")
    minute = (backstop + 7) % 60
    t0 = datetime(2026, 11, 15, 3, minute, tzinfo=UTC)

    r = scheduler.tick(capp, t0)  # no verdict yet: runs, then records "idle" (nothing pending)
    assert r.ran == ["x.gated"]
    assert "x.gated" in _hint_doc()["idle"]
    r = scheduler.tick(capp, t0 + timedelta(minutes=1))
    assert r.skipped == ["x.gated"] and r.ran == []

    _write("d1", {"status": "done"})  # any write to a watched collection wakes the job
    hint = _hint_doc()
    assert TEST_COLL in hint["w"]
    r = scheduler.tick(capp, t0 + timedelta(minutes=2))
    assert r.ran == ["x.gated"]  # ran; still nothing pending -> idle again, but the write is recent
    _write("d2", {"status": "pending"})  # the same process within 30 s: no second hint write
    assert _hint_doc()["w"][TEST_COLL] == hint["w"][TEST_COLL]
    r = scheduler.tick(capp, t0 + timedelta(minutes=3))
    assert r.ran == ["x.gated"]  # the earlier hint is still within the margin -> runs, finds work
    assert "x.gated" not in _hint_doc().get("idle", {})  # busy: no idle verdict
    r = scheduler.tick(capp, t0 + timedelta(minutes=4))
    assert r.ran == ["x.gated"]


def test_backstop_runs_an_idle_job_even_without_any_hint(
    event_mode: list[dict[str, Any]], capp: Celery, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(
        scheduler.GATES, "x.gated", scheduler.Gate((TEST_COLL,), scheduler._none_of(TEST_COLL))
    )
    scheduler._watched.cache_clear()
    monkeypatch.setattr(
        scheduler,
        "entries",
        lambda: [scheduler.Entry("x.gated", "schedtest.ok", "* * * * *", None, "default", ("x",))],
    )
    b = scheduler.backstop_minute("x.gated", "* * * * *")
    start = datetime(2026, 11, 15, 3, (b + 1) % 60, tzinfo=UTC)
    ran = [m for m in range(61) if scheduler.tick(capp, start + timedelta(minutes=m)).ran]
    assert ran == [0, 59]  # first verdict, then only the hourly full sweep (a missed hint: <= 60 min)


def test_hint_state_fingerprint_invalidates_the_idle_verdict() -> None:
    gate = scheduler.Gate(("c",), scheduler._none_of("c"), fingerprint=lambda: "v2")
    e = scheduler.Entry("x.j", "t", "* * * * *", None, "default")
    since = datetime(2026, 11, 15, 3, 0, tzinfo=UTC)
    at = datetime(2026, 11, 15, 3, (scheduler.backstop_minute("x.j", e.cron) + 5) % 60, tzinfo=UTC)
    st = scheduler.HintState(since, {}, {"x.j": {"at": since, "fp": "v2"}})
    assert scheduler.should_skip(e, gate, st, at)
    st.idle["x.j"]["fp"] = "v1"
    assert not scheduler.should_skip(e, gate, st, at)
    st.idle["x.j"]["fp"] = "v2"
    st.written["c"] = since - timedelta(seconds=60)  # inside SKIP_MARGIN: may predate S -> run
    assert not scheduler.should_skip(e, gate, st, at)
    st.written["c"] = since - timedelta(seconds=120)
    assert scheduler.should_skip(e, gate, st, at)


def test_outbox_create_kicks_the_relay_at_the_next_interval_boundary(
    event_mode: list[dict[str, Any]],
) -> None:
    from app.core.firestore.core_store import emit_event_tx
    from app.core.firestore.store import ScopedStore

    async def emit(tx: Any) -> None:
        emit_event_tx(
            tx, "schedtest.thing_happened", {}, aggregate_type="t", aggregate_id=__import__("uuid").uuid4()
        )

    async def two() -> float:
        store = ScopedStore.system("schedtest")
        await store.run_transaction(emit)
        committed = time.time()
        await store.run_transaction(emit)  # usually the same 1 s window: deduped in-process
        return committed

    committed = jobs.run_async(two())
    relay = [s for s in event_mode if s["task"] == "td.core.outbox_relay"]
    assert 1 <= len(relay) <= 2 and relay[0]["fn"] == "lmsTasksCritical"
    run_at = committed + relay[0]["delay"]
    assert run_at > committed - 0.5  # strictly after the commit (delay measured at enqueue time)
    assert relay[0]["delay"] <= 1.0  # coalescing window 1 s (the old loop: 5 s + a ~10 s gap/minute)
    # the store hook also wrote the work hint in the same commit
    assert "outbox_events" in _hint_doc()["w"]


def test_audit_outbox_create_kicks_the_sealer_within_a_second(event_mode: list[dict[str, Any]]) -> None:
    from app.core.firestore.store import ScopedStore

    async def body(tx: Any) -> None:
        tx.raw_create("audit_outbox", "a1", {"record_json": "{}", "occurred_at": datetime.now(UTC)})

    import app.modules.audit.store_specs  # noqa: F401 - registers audit_outbox

    jobs.run_async(ScopedStore.system("schedtest").run_transaction(body))
    seal = [s for s in event_mode if s["task"] == "td.core.audit_seal"]
    assert len(seal) == 1 and 0 < seal[0]["delay"] <= 1.0


def test_deadline_write_schedules_the_sweeper_at_the_deadline(event_mode: list[dict[str, Any]]) -> None:
    import app.modules.assessments.store_specs  # noqa: F401
    from app.core.firestore.store import ScopedStore

    deadline = datetime.now(UTC).replace(microsecond=0) + timedelta(minutes=30)

    async def body(tx: Any) -> None:
        tx.raw_set("test_attempts", "att1", {"status": "in_progress", "deadline_at": deadline})
        tx.raw_set("attempt_sections", "sec1", {"status": "not_started", "deadline_at": None})

    async def twice() -> None:
        store = ScopedStore.system("schedtest")
        await store.run_transaction(body)
        await store.run_transaction(body)  # e.g. an answer save re-writes the row: no new task

    jobs.run_async(twice())
    sweeps = [s for s in event_mode if s["task"] == "assessments.deadline_sweeper"]
    assert len(sweeps) == 1 and sweeps[0]["fn"] == "lmsTasksCritical"
    assert abs(sweeps[0]["delay"] - (deadline + timedelta(seconds=1) - datetime.now(UTC)).total_seconds()) < 3


def test_sweeper_schedules_the_next_deadline_plus_grace(
    event_mode: list[dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    from types import SimpleNamespace as NS

    from app.modules.assessments import tasks as atasks

    got: list[datetime] = []

    async def fake_kick_at(job: str, when: datetime, **_kw: Any) -> bool:
        got.append(when)
        return True

    monkeypatch.setattr(jobhints, "kick_at", fake_kick_at)
    now = datetime(2026, 11, 15, 10, 0, tzinfo=UTC)
    t = NS(grace_seconds=30)
    a1 = NS(id=1, test_id="t", status="in_progress", deadline_at=now + timedelta(minutes=5))
    a2 = NS(id=2, test_id="t", status="submitted", deadline_at=now + timedelta(minutes=1))
    sec = NS(attempt_id=1, status="active", deadline_at=now + timedelta(minutes=2))
    asyncio.run(atasks._schedule_next([a1, a2], [sec], {"t": t}, now))  # type: ignore[list-item, dict-item]
    assert got == [now + timedelta(minutes=2, seconds=31)]


def test_relay_gate_sees_pending_events_and_revivable_dead_letters(event_mode: list[dict[str, Any]]) -> None:
    from app.core.firestore.store import ScopedStore

    async def run() -> list[bool]:
        client = ScopedStore.system("schedtest").client
        coll = client.collection(physical_name("outbox_events"))
        out = [await scheduler._relay_idle(client, None)]
        await coll.document("dead").set({"dead_at": datetime.now(UTC), "attempts": 10, "dispatched_at": None})
        out.append(await scheduler._relay_idle(client, None))  # dead at the current max (10): idle
        await coll.document("dead").update({"attempts": 3})
        out.append(await scheduler._relay_idle(client, None))  # below max: the relay must run
        await coll.document("dead").delete()
        await coll.document("p").set({"pending_at": datetime.now(UTC), "attempts": 0})
        out.append(await scheduler._relay_idle(client, None))
        return out

    assert jobs.run_async(run()) == [True, True, False, False]


def test_audit_seal_with_nothing_pending_takes_no_lease(event_mode: list[dict[str, Any]]) -> None:
    from app.core.firestore.collections import LOCKS
    from app.core.firestore.store import ScopedStore
    from app.modules.audit.repo_firestore import sealer_repo

    async def run() -> tuple[int, int]:
        n = await sealer_repo().seal_pending(10)
        locks = [
            s async for s in ScopedStore.system("schedtest").client.collection(physical_name(LOCKS)).stream()
        ]
        return n, len(locks)

    assert jobs.run_async(run()) == (0, 0)


def test_nothing_is_hinted_or_kicked_outside_event_mode(
    firestore_emulator: str, settings_env: pytest.MonkeyPatch
) -> None:
    from tests.firestore.conftest import TEST_PROJECT, clear_emulator

    clear_emulator(firestore_emulator)
    settings_env.setenv("FIRESTORE_EMULATOR_HOST", firestore_emulator)
    settings_env.setenv("FIREBASE_PROJECT_ID", TEST_PROJECT)
    settings_env.setenv("TD_TASKS_BACKEND", "celery")
    from app.core.config import reset_settings_cache

    reset_settings_cache()
    jobhints.reset_for_tests()
    sent: list[Any] = []
    settings_env.setattr(cloudtasks, "enqueue_impl", _rec(sent, lambda *a: a))
    register_collection(CollectionSpec(TEST_COLL, "system"))
    try:
        assert not jobhints.active()
        from app.core.firestore.core_store import emit_event_tx
        from app.core.firestore.store import ScopedStore

        async def emit(tx: Any) -> None:
            emit_event_tx(
                tx,
                "schedtest.thing_happened",
                {},
                aggregate_type="t",
                aggregate_id=__import__("uuid").uuid4(),
            )

        jobs.run_async(ScopedStore.system("schedtest").run_transaction(emit))
        assert sent == [] and _hint_doc() == {}
    finally:
        jobhints.reset_for_tests()
        unregister_collection(TEST_COLL)


def test_kick_coalesces_per_window_and_never_runs_before_the_commit(event_mode: list[dict[str, Any]]) -> None:
    assert jobhints.next_boundary(100.0, 1.0) == 101.0 and jobhints.next_boundary(100.4, 1.0) == 101.0

    async def kicks() -> list[bool]:
        t = time.time()
        base = float(int(t)) + 0.1  # a fixed window
        return [
            await jobhints.kick(jobhints.RELAY_JOB, now=base),
            await jobhints.kick(jobhints.RELAY_JOB, now=base + 0.5),  # same window: covered
            await jobhints.kick(jobhints.RELAY_JOB, now=base + 1.0),  # next window: new task
        ]

    assert jobs.run_async(kicks()) == [True, False, True]
    assert len(event_mode) == 2


def test_failed_kick_is_logged_not_raised(
    event_mode: list[dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(*_a: Any) -> str:
        raise RuntimeError("cloud tasks down")

    monkeypatch.setattr(cloudtasks, "enqueue_impl", boom)
    assert jobs.run_async(jobhints.kick(jobhints.SEAL_JOB)) is False  # the hint + minute backstop cover it
