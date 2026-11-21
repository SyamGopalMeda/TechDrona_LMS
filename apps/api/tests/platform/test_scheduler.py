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
        due = {e.job for e in scheduler.due_entries(at, entries, window=1)}
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

    entries = scheduler.entries()
    by_job = {e.job: e for e in entries}
    days = scheduler.BACKSTOP_EVERY_DAYS
    step = scheduler.TICK_MINUTES
    ticks = [WEEK_START + timedelta(minutes=m) for m in range(step, days * 1440 + 1, step)]  # one cycle
    for job, gate in scheduler.GATES.items():
        e = by_job[job]
        due = [at for at in ticks if e in scheduler.due_entries(at, entries)]
        backstops = [at for at in due if scheduler.is_backstop(job, e.cron, at)]
        per_cycle = days // (gate.backstop_days or days)
        assert len(backstops) == per_cycle, (job, backstops)  # full runs while idle, on ticks it is due
        if gate.quiet is not None or gate.idle is scheduler._always_idle:
            assert gate.watch, job  # woken only by writes: it must watch something
        for c in gate.watch:
            get_spec(c)  # a registered logical collection (the store hook sees exactly these names)


def test_ticks_run_every_entry_at_its_cadence_or_once_per_tick() -> None:
    """Ticks every TICK_MINUTES (2 h): an entry due several times in the window runs once; daily and
    weekly entries run in the tick right after their time, exactly as often as before."""
    import app.worker  # noqa: F401

    step = scheduler.TICK_MINUTES
    assert step == 120 and 1440 % step == 0
    entries = scheduler.entries()
    counts = {e.job: 0 for e in entries}
    first: dict[str, datetime] = {}
    for m in range(step, 7 * 1440 + 1, step):
        at = WEEK_START + timedelta(minutes=m)
        for e in scheduler.due_entries(at, entries):
            counts[e.job] += 1
            first.setdefault(e.job, at)
    per_week = 7 * 1440 // step
    assert counts["core.outbox_relay"] == counts["commerce.order_expiry"] == per_week
    assert counts["analytics.daily_aggregator"] == counts["commerce.reconciliation"] == per_week
    assert counts["security.decay_recompute"] == counts["notifications.renewal_reminders"] == 7
    assert counts["security.purge_closed_cases"] == 1
    assert first["security.decay_recompute"] == WEEK_START + timedelta(hours=22)  # 20:30 -> 22:00 tick
    assert first["notifications.renewal_reminders"] == WEEK_START + timedelta(days=1)  # 00:00 -> that tick


def test_the_scheduled_function_fires_at_the_tick_interval() -> None:
    main = (Path(__file__).resolve().parents[4] / "functions-lms" / "main.py").read_text(encoding="utf-8")
    hours = scheduler.TICK_MINUTES // 60
    cron = "0 * * * *" if hours == 1 else f"0 */{hours} * * *"
    assert f'schedule="{cron}"' in main


def test_idle_day_cost_only_the_hint_and_the_ungated_daily_jobs() -> None:
    """The owner's target (2026-11-19): < 50 billed operations a day while nobody uses the LMS. Every
    entry that runs more than once a day is gated (an idle tick reads only the hint document)."""
    import app.worker  # noqa: F401

    ungated = sorted(
        e.job for e in scheduler.entries() if e.job not in scheduler.GATES and not scheduler._at_most_daily(e.cron)
    )
    assert ungated == []


def test_backstop_of_a_daily_job_falls_on_its_cycle_day() -> None:
    e = scheduler.Entry("security.decay_recompute", "t", "30 20 * * *", None, "default")
    day, _hour = scheduler.backstop_slot(e.job)
    n = scheduler.BACKSTOP_EVERY_DAYS
    hits = [d for d in range(n) if scheduler.is_backstop(e.job, e.cron, WEEK_START + timedelta(days=d, hours=21))]
    assert len(hits) == 1 and (WEEK_START + timedelta(days=hits[0])).toordinal() % n == day
    weekly = scheduler.Entry("analytics.retention_purge", "t", "30 21 * * *", None, "default")
    assert scheduler.GATES[weekly.job].backstop_days == 7
    assert sum(
        scheduler.is_backstop(weekly.job, weekly.cron, WEEK_START + timedelta(days=d, hours=22)) for d in range(28)
    ) == 4  # retention sweeps: weekly while idle (21:30 -> the 22:00 tick)


def test_quiet_window_keeps_yesterday_jobs_running_after_activity() -> None:
    """``analytics.security_feed`` processes yesterday: activity today must still be built tomorrow."""
    from app.core.firestore import jobstate

    gate = scheduler.GATES["analytics.security_feed"]
    e = scheduler.Entry("analytics.security_feed", "t", "0 23 * * *", None, "default")
    now = datetime(2026, 11, 20, 23, 0, tzinfo=UTC)
    merged: list[dict[str, Any]] = []

    async def merge(_client: Any, data: dict[str, Any]) -> None:
        merged.append(data)

    import pytest as _pt

    mp = _pt.MonkeyPatch()
    mp.setattr(jobstate, "merge_hints", merge)
    mp.setattr(scheduler, "_client", lambda: None)
    try:
        st = scheduler.HintState(now, {"analytics_batches": now - timedelta(hours=12)}, {})
        jobs.run_async(scheduler._finish(st, [(e, True, {"built": 0})]))
        assert merged == []  # activity 12 h ago: no idle verdict, it runs again tomorrow
        st = scheduler.HintState(now, {"analytics_batches": now - timedelta(days=3)}, {})
        jobs.run_async(scheduler._finish(st, [(e, True, {"built": 0})]))
        assert merged and e.job in merged[-1]["idle"]  # quiet for 3 days: idle
    finally:
        mp.undo()
    assert gate.quiet == timedelta(days=2)


def _fake_exists(found: set[str]) -> Callable[..., Any]:
    seen: list[tuple[str, tuple[Any, ...]]] = []

    async def exists(_client: Any, collection: str, filters: tuple[Any, ...]) -> bool:
        seen.append((collection, filters))
        return collection in found

    exists.seen = seen  # type: ignore[attr-defined]
    return exists


@pytest.mark.parametrize(
    ("job", "busy_collection"),
    [
        ("security.decay_recompute", "security_signals"),
        ("security.decay_recompute", "account_restrictions"),
        ("security.decay_recompute", "verification_tokens"),
        ("security.sla_breach_alerts", "security_cases"),
        ("security.sla_breach_alerts", "unblock_requests"),
        ("security.sla_breach_alerts", "approval_requests"),
        ("support.auto_close", "support_tickets"),
        ("media.scan_sweep", "lesson_assets"),
        ("security.purge_counters", "security_counters"),
    ],
)
def test_new_gates_are_idle_only_when_nothing_can_become_due(
    monkeypatch: pytest.MonkeyPatch, job: str, busy_collection: str
) -> None:
    gate = scheduler.GATES[job]
    monkeypatch.setattr(scheduler, "_exists", _fake_exists(set()))
    assert jobs.run_async(gate.idle(None, None)) is True
    monkeypatch.setattr(scheduler, "_exists", _fake_exists({busy_collection}))
    assert jobs.run_async(gate.idle(None, None)) is False


def test_entitlement_gate_books_the_next_expiry_instead_of_polling(monkeypatch: pytest.MonkeyPatch) -> None:
    gate = scheduler.GATES["entitlements.expiry"]
    ends: dict[str, datetime | None] = {"active": None, "grace": None}

    async def earliest(_client: Any, _coll: str, status: str, _field: str) -> datetime | None:
        return ends[status]

    booked: list[tuple[str, datetime]] = []
    ok = [True]

    async def kick_at(job: str, when: datetime, **_: Any) -> bool:
        booked.append((job, when))
        return ok[0]

    monkeypatch.setattr(scheduler, "_earliest", earliest)
    monkeypatch.setattr(jobhints, "kick_at", kick_at)
    assert jobs.run_async(gate.idle(None, None)) is True and booked == []  # nothing can expire
    soon = datetime.now(UTC) + timedelta(days=3)
    ends["active"], ends["grace"] = soon + timedelta(days=1), soon
    assert jobs.run_async(gate.idle(None, None)) is True
    assert booked[-1] == ("entitlements.expiry", soon + timedelta(seconds=1))  # the earliest one
    ends["active"], ends["grace"] = datetime.now(UTC) + timedelta(days=200), None
    assert jobs.run_async(gate.idle(None, None)) is True  # far away: a re-check within 30 days
    assert booked[-1][1] < datetime.now(UTC) + timedelta(days=26)
    ok[0] = False
    assert jobs.run_async(gate.idle(None, None)) is False  # cannot book -> keep the hourly runs


def test_result_gates_and_gateway_fingerprint() -> None:
    g = scheduler.GATES
    assert jobs.run_async(g["analytics.outbox_consumer"].idle(None, {"applied": 0, "skipped": 0, "seen": 0}))
    assert not jobs.run_async(g["analytics.outbox_consumer"].idle(None, {"seen": 2}))
    assert jobs.run_async(g["analytics.daily_aggregator"].idle(None, {"user_days": 0}))
    rec = g["commerce.reconciliation"]
    assert jobs.run_async(rec.idle(None, {"skipped": "gateway_not_integrated", "provider": "fake"}))
    assert not jobs.run_async(rec.idle(None, {"orders": 3}))
    assert rec.fingerprint is not None and ":" in rec.fingerprint()


def test_daily_gated_job_is_skipped_until_a_watched_write_or_its_backstop() -> None:
    e = scheduler.Entry("security.decay_recompute", "t", "30 20 * * *", None, "default")
    gate = scheduler.GATES[e.job]
    at = next(
        WEEK_START + timedelta(days=d, hours=21)
        for d in range(28)
        if not scheduler.is_backstop(e.job, e.cron, WEEK_START + timedelta(days=d, hours=21))
    )
    since = at - timedelta(days=1)
    st = scheduler.HintState(at, {}, {e.job: {"at": since, "fp": gate.fingerprint() if gate.fingerprint else None}})
    assert scheduler.should_skip(e, gate, st, at)
    st.written["auth_sessions"] = at - timedelta(hours=3)  # someone signed in since the verdict
    assert not scheduler.should_skip(e, gate, st, at)


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
    r = scheduler.tick(capp, datetime(2026, 11, 15, 21, 30, 42, tzinfo=UTC), window=1)
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
    r = scheduler.tick(capp, datetime(2026, 11, 15, 21, 31, tzinfo=UTC), window=1)
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
    r = scheduler.tick(capp, datetime(2026, 11, 15, 1, 0, tzinfo=UTC), inline_budget_s=45.0, window=1)
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
    r = scheduler.tick(capp, datetime(2026, 11, 15, 1, 0, tzinfo=UTC), window=1)
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
    t0 = datetime(2026, 11, 15, 3, 7, tzinfo=UTC)  # never a backstop minute (those are hour starts)

    r = scheduler.tick(capp, t0, window=1)  # no verdict yet: runs, then records "idle" (nothing pending)
    assert r.ran == ["x.gated"]
    assert "x.gated" in _hint_doc()["idle"]
    r = scheduler.tick(capp, t0 + timedelta(minutes=1), window=1)
    assert r.skipped == ["x.gated"] and r.ran == []

    _write("d1", {"status": "done"})  # any write to a watched collection wakes the job
    hint = _hint_doc()
    assert TEST_COLL in hint["w"]
    r = scheduler.tick(capp, t0 + timedelta(minutes=2), window=1)
    assert r.ran == ["x.gated"]  # ran; still nothing pending -> idle again, but the write is recent
    _write("d2", {"status": "pending"})  # the same process within 30 s: no second hint write
    assert _hint_doc()["w"][TEST_COLL] == hint["w"][TEST_COLL]
    r = scheduler.tick(capp, t0 + timedelta(minutes=3), window=1)
    assert r.ran == ["x.gated"]  # the earlier hint is still within the margin -> runs, finds work
    assert "x.gated" not in _hint_doc().get("idle", {})  # busy: no idle verdict
    r = scheduler.tick(capp, t0 + timedelta(minutes=4), window=1)
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
    day, hour = scheduler.backstop_slot("x.gated")
    step = scheduler.TICK_MINUTES
    start = WEEK_START + timedelta(minutes=step)
    ticks = [start + timedelta(minutes=m) for m in range(0, (scheduler.BACKSTOP_EVERY_DAYS + 1) * 1440, step)]
    ran = [at for at in ticks if scheduler.tick(capp, at).ran]
    assert ran[0] == start and len(ran) == 2  # first verdict, then only the periodic full sweep
    covered = scheduler.window_minutes(ran[1])  # the tick whose window holds the slot hour's start
    assert any(m.toordinal() % scheduler.BACKSTOP_EVERY_DAYS == day and (m.hour, m.minute) == (hour, 0) for m in covered)


def test_hint_state_fingerprint_invalidates_the_idle_verdict() -> None:
    gate = scheduler.Gate(("c",), scheduler._none_of("c"), fingerprint=lambda: "v2")
    e = scheduler.Entry("x.j", "t", "* * * * *", None, "default")
    since = datetime(2026, 11, 15, 3, 0, tzinfo=UTC)
    at = datetime(2026, 11, 15, 3, 5, tzinfo=UTC)
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


def test_judge_gate_is_idle_while_the_judge_is_disabled(
    event_mode: list[dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.core.firestore.store import ScopedStore
    from app.modules.coding import judge_gateway

    enabled = [True]
    monkeypatch.setattr(judge_gateway, "judge_enabled", lambda: enabled[0])

    async def run() -> list[Any]:
        client = ScopedStore.system("schedtest").client
        coll = client.collection(physical_name("code_submissions"))
        out: list[Any] = [await scheduler._judge_idle(client, {})]
        await coll.document("s").set({"status": "queued"})
        out.append(await scheduler._judge_idle(client, {}))  # enabled + queued: work
        enabled[0] = False
        out += [await scheduler._judge_idle(client, {}), scheduler._judge_fp()]  # nothing can judge it
        enabled[0] = True
        out.append(scheduler._judge_fp())  # re-enabling invalidates the idle verdict
        return out

    assert jobs.run_async(run()) == [True, False, True, "judge_enabled=False", "judge_enabled=True"]


def test_restriction_gate_ignores_lifted_restrictions(event_mode: list[dict[str, Any]]) -> None:
    from app.core.firestore.store import ScopedStore

    gate = scheduler.GATES["security.restriction_expiry"]

    async def run() -> list[bool]:
        client = ScopedStore.system("schedtest").client
        coll = client.collection(physical_name("account_restrictions"))
        await coll.document("lifted").set(
            {"level": 3, "family": "sharing", "ended_at": datetime.now(UTC) - timedelta(days=1)}
        )
        out = [await gate.idle(client, None)]  # a lifted L3 row is no work
        await coll.document("live").set({"level": 3, "family": "sharing", "ended_at": None})
        out.append(await gate.idle(client, None))
        return out

    assert jobs.run_async(run()) == [True, False]


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


def test_earliest_expiry_query_on_the_emulator(event_mode: list[dict[str, Any]]) -> None:
    from app.core.firestore.collections import physical_name
    from app.core.firestore.store import ScopedStore

    client = ScopedStore.system("schedtest").client
    t1 = datetime(2027, 1, 5, tzinfo=UTC)
    t2 = datetime(2027, 3, 1, tzinfo=UTC)

    async def body() -> tuple[Any, Any, Any]:
        coll = client.collection(physical_name("entitlements"))
        await coll.document("a").set({"status": "active", "ends_at": t2})
        await coll.document("b").set({"status": "active", "ends_at": t1})
        await coll.document("c").set({"status": "active", "ends_at": None})  # lifetime access
        await coll.document("d").set({"status": "expired", "ends_at": datetime(2026, 1, 1, tzinfo=UTC)})
        return (
            await scheduler._earliest(client, "entitlements", "active", "ends_at"),
            await scheduler._earliest(client, "entitlements", "grace", "grace_ends_at"),
            await scheduler._exists(client, "security_cases", (("status", "!=", "closed"),)),
        )

    active, grace, cases = jobs.run_async(body())
    assert active == t1 and grace is None and cases is False


# --------------------------------------------------------------------------- idle cost (emulator)


def _count_billed_ops(monkeypatch: pytest.MonkeyPatch) -> dict[str, int]:
    """Count billed Firestore operations at the GAPIC level, as Firestore bills them (same rules as
    functions-lms/tools/firestore_cost_probe.py): a query bills one read per document returned and
    one read when it returns nothing; every write / delete in a commit bills one."""
    from google.cloud.firestore_v1.services.firestore.async_client import FirestoreAsyncClient as C

    n = {"reads": 0, "writes": 0, "deletes": 0}

    class Stream:
        def __init__(self, inner: Any, kind: str) -> None:
            self.inner, self.kind, self.docs, self.it, self.done = inner, kind, 0, None, False

        def __aiter__(self) -> Any:
            return self

        async def __anext__(self) -> Any:
            if self.it is None:
                self.it = self.inner.__aiter__()
            try:
                resp = await self.it.__anext__()
            except StopAsyncIteration:
                if not self.done and self.kind == "query" and self.docs == 0:
                    n["reads"] += 1
                self.done = True
                raise
            pb = getattr(resp, "_pb", resp)
            if self.kind == "query" and pb.HasField("document"):
                self.docs += 1
                n["reads"] += 1
            elif self.kind == "get" and (pb.HasField("found") or pb.WhichOneof("result") == "missing"):
                n["reads"] += 1
            return resp

    rq, agg, bg, gd, cm = C.run_query, C.run_aggregation_query, C.batch_get_documents, C.get_document, C.commit

    async def run_query(self: Any, *a: Any, **kw: Any) -> Any:
        return Stream(await rq(self, *a, **kw), "query")

    async def run_aggregation_query(self: Any, *a: Any, **kw: Any) -> Any:
        n["reads"] += 1
        return await agg(self, *a, **kw)

    async def batch_get_documents(self: Any, *a: Any, **kw: Any) -> Any:
        return Stream(await bg(self, *a, **kw), "get")

    async def get_document(self: Any, *a: Any, **kw: Any) -> Any:
        n["reads"] += 1
        return await gd(self, *a, **kw)

    async def commit(self: Any, *a: Any, **kw: Any) -> Any:
        req = kw.get("request") if kw.get("request") is not None else (a[0] if a else None)
        writes = (req.get("writes") if isinstance(req, dict) else getattr(req, "writes", None)) or kw.get("writes") or []
        for w in writes:
            if getattr(w, "_pb", None) is not None:
                op = w._pb.WhichOneof("operation")
            elif isinstance(w, dict):
                op = "delete" if w.get("delete") else "update"
            else:
                op = "delete" if getattr(w, "delete", "") else "update"
            n["deletes" if op == "delete" else "writes"] += 1
        return await cm(self, *a, **kw)

    for name, fn in {
        "run_query": run_query,
        "run_aggregation_query": run_aggregation_query,
        "batch_get_documents": batch_get_documents,
        "get_document": get_document,
        "commit": commit,
    }.items():
        monkeypatch.setattr(C, name, fn)
    return n


def test_an_idle_week_costs_under_50_billed_operations_a_day(
    event_mode: list[dict[str, Any]], settings_env: pytest.MonkeyPatch, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Owner target (2026-11-19): while nobody uses the LMS, Firestore bills < 50 operations a day.
    Every real beat entry, hourly ticks (TICK_MINUTES), an empty project; day 1 also makes the first
    idle verdicts, so days 2-7 are the steady state (the weekly full sweeps fall on those days).
    Runs one backstop cycle (BACKSTOP_EVERY_DAYS) so weekly retention sweeps and every gated job's
    full run are included; days 1-2 make the first verdicts, the rest is the idle average."""
    import app.worker as worker
    from app.core.firestore.backend import MODULES
    from app.core.config import reset_settings_cache

    for m in MODULES:
        settings_env.setenv(f"TD_STORE_{m.upper()}", "firestore")
    reset_settings_cache()
    jobhints.reset_for_tests()
    # A simulated week runs in seconds of real time, while hints carry real server timestamps: the
    # clock-slack margin and the 30 s hint rate limit would make every tick look "just written".
    monkeypatch.setattr(jobhints, "SKIP_MARGIN", timedelta(0))
    monkeypatch.setattr(jobhints, "HINT_REFRESH_S", 0.0)
    n = _count_billed_ops(monkeypatch)
    capp = worker.celery_app
    per_day: list[dict[str, int]] = []
    busy: list[str] = []
    for day in range(scheduler.BACKSTOP_EVERY_DAYS):
        before = dict(n)
        for m in range(scheduler.TICK_MINUTES, 1441, scheduler.TICK_MINUTES):
            at = WEEK_START + timedelta(days=day, minutes=m)
            b = dict(n)
            res = scheduler.tick(capp, at)
            while event_mode:  # what the task queues would run (maintenance hand-offs, kicks)
                item = event_mode.pop(0)
                if item.get("periodic"):
                    cloudtasks.run_periodic(capp, item["periodic"], loop=False)
                else:
                    cloudtasks.run_task(capp, item["task"], item.get("args"), item.get("kwargs"))
            cost = sum(n[k] - b[k] for k in n)
            if day > 1 and cost > 1:
                busy.append(f"{at:%a %d %H:%M} {cost} ran={res.ran} handed={res.handed_off}")
        per_day.append({k: n[k] - before[k] for k in n})
    print("ticks costing more than the hint read (days 3+):", *busy, sep="\n  ")  # noqa: T201
    print("billed operations per idle day (days 1-2 = first verdicts):", per_day)  # noqa: T201
    steady = [sum(d.values()) for d in per_day[2:]]
    avg = sum(steady) / len(steady)
    print("idle days: average", round(avg, 1), "max", max(steady), "min", min(steady))  # noqa: T201
    assert avg < 50, per_day


def test_decay_recompute_is_idle_while_protection_is_off_and_not_enforcing(monkeypatch: pytest.MonkeyPatch) -> None:
    gate = scheduler.GATES["security.decay_recompute"]
    monkeypatch.setattr(scheduler, "_exists", _fake_exists({"security_signals"}))  # signals exist
    skipped = {"derived_signals": 0, "evaluations": 0, "skipped": "protection_off_not_enforcing"}
    assert jobs.run_async(gate.idle(None, skipped)) is True
    assert jobs.run_async(gate.idle(None, {"derived_signals": 1, "evaluations": 3})) is False
    assert "policy_settings" in gate.watch and gate.fingerprint is not None
    assert gate.fingerprint().startswith("protection_off=")


def test_decay_recompute_job_skips_without_reading_sessions(monkeypatch: pytest.MonkeyPatch) -> None:
    from types import SimpleNamespace

    from app.modules.security import engine
    from app.modules.security import tasks as sec_tasks

    mode = ["shadow"]

    async def risk_mode(_session: Any) -> str:
        return mode[0]

    async def no_sessions(*_a: Any, **_k: Any) -> list[Any]:
        raise AssertionError("must not read sessions while skipped")

    monkeypatch.setattr(engine, "risk_mode", risk_mode)
    monkeypatch.setattr(sec_tasks.sessions_public, "list_sessions", no_sessions)
    monkeypatch.setattr("app.core.config.get_settings", lambda: SimpleNamespace(account_protection_off=True))
    out = jobs.run_async(sec_tasks.decay_recompute(None))  # type: ignore[arg-type]
    assert out["skipped"] == "protection_off_not_enforcing"
    mode[0] = "enforce"
    with pytest.raises(AssertionError, match="must not read sessions"):
        jobs.run_async(sec_tasks.decay_recompute(None))  # type: ignore[arg-type]
