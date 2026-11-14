"""Celery -> Cloud Tasks shim and beat -> scheduled functions."""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from celery import Celery
from celery.schedules import crontab

from app.core import cloudtasks, jobs

SCHEDULES = Path(__file__).resolve().parents[4] / "functions-lms" / "schedules.json"


@pytest.mark.parametrize(
    ("schedule", "cron", "repeat"),
    [
        (5.0, "* * * * *", 5.0),
        (2.0, "* * * * *", 2.0),
        (60.0, "* * * * *", None),
        (120.0, "*/2 * * * *", None),
        (300.0, "*/5 * * * *", None),
        (900.0, "*/15 * * * *", None),
        (3600.0, "0 * * * *", None),
        (86_400.0, "0 0 * * *", None),
        (timedelta(minutes=10), "*/10 * * * *", None),
        (crontab(hour=21, minute=30), "30 21 * * *", None),
        (crontab(minute=0, hour=23, day_of_week=0), "0 23 * * 0", None),
        (crontab(minute="*/5"), "*/5 * * * *", None),
    ],
)
def test_cron_for(schedule: Any, cron: str, repeat: float | None) -> None:
    assert cloudtasks.cron_for(schedule) == (cron, repeat)


def test_cron_for_refuses_inexact_intervals() -> None:
    with pytest.raises(ValueError):
        cloudtasks.cron_for(7 * 60.0)


def test_function_names() -> None:
    assert cloudtasks.function_name_for_job("commerce.order_expiry") == "lmsJobCommerceOrderExpiry"
    assert cloudtasks.function_name_for_job("core.outbox_relay") == "lmsJobCoreOutboxRelay"


def test_schedules_json_matches_the_beat_registry() -> None:
    """Every Celery beat entry has a scheduled function with the same cadence (regenerate with
    functions-lms/tools/gen_schedules.py)."""
    import app.worker  # noqa: F401 - registers the beat entries

    manifest = cloudtasks.schedule_manifest()
    assert json.loads(SCHEDULES.read_text(encoding="utf-8")) == manifest
    names = [e["function"] for e in manifest]
    assert len(names) == len(set(names))
    # Firebase-only backstop for the judge (no VM beat entry: worker-judge polls there).
    sweep = next(e for e in manifest if e["job"] == "coding.process_pending")
    assert sweep == {
        "job": "coding.process_pending",
        "task": "coding.process_pending",
        "function": "lmsJobCodingProcessPending",
        "cron": "* * * * *",
        "repeat_seconds": None,
        "queue": "default",
    }
    from app.core.jobs import periodic_jobs

    assert "coding.process_pending" not in {j.name for j in periodic_jobs()}  # VM beat unchanged
    assert all(len(n) <= 63 for n in names)


@pytest.fixture
def capp() -> Any:
    app = Celery("t", broker="memory://", set_as_current=False)
    app.conf.task_ignore_result = True
    calls: list[tuple[Any, ...]] = []

    @app.task(name="platformtest.add")
    def add(a: int, b: int, scale: int = 1) -> int:
        calls.append((a, b, scale))
        return (a + b) * scale

    @app.task(name="platformtest.fail")
    def fail() -> None:
        raise RuntimeError("boom")

    app.calls = calls  # type: ignore[attr-defined]
    return app


def test_install_routes_every_send_to_cloud_tasks(capp: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    sent: list[tuple[str, str, dict[str, Any], float | None]] = []
    monkeypatch.setattr(
        cloudtasks,
        "enqueue_impl",
        lambda fn, loc, data, delay: sent.append((fn, loc, data, delay)) or "task-1",
    )
    cloudtasks.install(capp)
    r = capp.send_task("commerce.process_webhook_event", args=["razorpay", "id-1"], queue="critical")
    assert r.id == "task-1" and r.function == "lmsTasksCritical"
    capp.tasks["platformtest.add"].apply_async(args=[1, 2], kwargs={"scale": 3}, countdown=2)
    capp.tasks["platformtest.add"].delay(4, 5)
    capp.send_task("x.y", args=[], queue="maintenance")
    capp.send_task("x.z", queue="judge_submit")  # unknown queue -> default
    assert [s[0] for s in sent] == [
        "lmsTasksCritical",
        "lmsTasks",
        "lmsTasks",
        "lmsTasksMaintenance",
        "lmsTasks",
    ]
    assert sent[1][2] == {"task": "platformtest.add", "args": [1, 2], "kwargs": {"scale": 3}}
    assert sent[1][3] == 2 and sent[0][1] == "asia-south1"
    assert capp.calls == []  # nothing ran locally


def test_run_task_executes_the_registered_body(capp: Any) -> None:
    assert cloudtasks.run_task(capp, "platformtest.add", [2, 3], {"scale": 2}) == 10
    with pytest.raises(RuntimeError):
        cloudtasks.run_task(capp, "platformtest.fail")
    with pytest.raises(LookupError):
        cloudtasks.run_task(capp, "nope")


def test_run_periodic_once_and_sub_minute_repeat(capp: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    jobs.register_periodic("platformtest.hourly", "platformtest.add", 3600.0, args=(1, 1))
    jobs.register_periodic("platformtest.fast", "platformtest.add", 0.2, args=(0, 0))
    jobs.register_periodic("platformtest.failing", "platformtest.fail", 60.0)
    try:
        assert cloudtasks.run_periodic(capp, "platformtest.hourly") == 1
        runs = cloudtasks.run_periodic(capp, "platformtest.fast", budget_s=1.0)
        assert 4 <= runs <= 6
        assert cloudtasks.run_periodic(capp, "platformtest.failing") == 1  # logged, not raised
    finally:
        for n in ("platformtest.hourly", "platformtest.fast", "platformtest.failing"):
            jobs.unregister_periodic(n)
