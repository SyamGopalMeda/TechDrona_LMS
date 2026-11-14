"""Celery -> Cloud Tasks + scheduled functions (``TD_TASKS_BACKEND=cloudtasks``; Firebase runtime).

The Celery app is still built (``app.worker.create_celery``): it is the task *registry* (every
``shared_task`` and ``register_celery_tasks`` hook) and holds the beat schedule
(``app.core.jobs``). Only the transport changes:

* **Dispatch.** ``install(celery_app)`` replaces ``celery_app.send_task``. Celery's
  ``Task.apply_async`` / ``.delay`` end in ``app.send_task`` too, so every existing call site
  (``commerce.enqueue_webhook_event``, ``analytics.exports``, ``coding.notify_enqueued``) is
  covered without module changes. A send becomes a Cloud Tasks task on the task-queue function
  mapped to the Celery queue (``TD_CLOUD_TASKS_QUEUES``; unknown queues -> ``default``), payload
  ``{"task", "args", "kwargs"}``; ``countdown`` -> ``schedule_delay_seconds``. Enqueue goes
  through ``firebase_admin.functions.task_queue`` (OIDC to the function; Application Default
  Credentials of the function's service account).
* **Execution.** ``run_task(name, args, kwargs)`` runs the registered task body in-process
  (``Task.apply``, eager, exceptions propagate so Cloud Tasks retries) — called by the
  ``lmsTasks*`` functions (functions-lms/main.py).
* **Beat.** One scheduled function (``lmsScheduler``, every minute) runs every entry whose cron
  (``cron_for``: the same cadence) is due -- ``app.core.scheduler.tick``. Maintenance entries (and,
  on a hybrid stack with Postgres, the sub-minute entries) are handed to their task-queue function
  as ``{"task", "args", "kwargs", "periodic": job}``; ``run_periodic`` runs such a hand-off: a
  failure is logged, not retried, and a sub-minute entry repeats every ``interval`` seconds until
  ``budget_s`` is spent (``periodic_loop``), exactly like the old per-entry functions. In event
  mode the sub-minute entries are kicked by the writes that create their work
  (``app.core.jobhints``) instead of looping.

Default (``celery``): nothing here is used and the VM behaves exactly as before.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

import structlog

log = structlog.get_logger("app.cloudtasks")

_TASKS_APP_NAME = "td-lms-tasks"


@dataclass(frozen=True, slots=True)
class Enqueued:
    """Stand-in for Celery's ``AsyncResult`` (results are disabled everywhere anyway)."""

    id: str
    task: str
    function: str


def function_for_queue(queue: str | None) -> str:
    from app.core.runtime import cloud_task_queues

    queues = cloud_task_queues()
    return queues.get(queue or "default") or queues.get("default") or "lmsTasks"


def _admin_app() -> Any:
    import firebase_admin
    from firebase_admin import credentials

    from app.core.config import get_settings

    try:
        return firebase_admin.get_app(_TASKS_APP_NAME)
    except ValueError:
        project = (
            get_settings().FIREBASE_PROJECT_ID
            or os.environ.get("GOOGLE_CLOUD_PROJECT", "")
            or os.environ.get("GCLOUD_PROJECT", "")
        )
        return firebase_admin.initialize_app(
            credentials.ApplicationDefault(), {"projectId": project}, name=_TASKS_APP_NAME
        )


# Seam for tests: ``enqueue_impl(function_name, location, data, delay_seconds) -> task id``.
def _firebase_enqueue(function: str, location: str, data: dict[str, Any], delay: float | None) -> str:
    from firebase_admin import functions

    if not delay:
        opts = None
    elif delay == int(delay):
        opts = functions.TaskOptions(schedule_delay_seconds=int(delay))
    else:  # an exact ``eta`` (event kicks): never dispatch before it
        from app.core.time import utcnow

        opts = functions.TaskOptions(schedule_time=utcnow() + timedelta(seconds=delay))
    queue = functions.task_queue(f"locations/{location}/functions/{function}", app=_admin_app())
    return str(queue.enqueue(data, opts))


enqueue_impl = _firebase_enqueue


def send_task(
    name: str,
    args: Any = None,
    kwargs: Any = None,
    countdown: float | None = None,
    eta: Any = None,
    queue: str | None = None,
    **options: Any,
) -> Enqueued:
    from app.core.config import get_settings
    from app.core.firestore.store import forbid_in_transaction
    from app.core.time import utcnow

    forbid_in_transaction("Cloud Tasks enqueue")
    queue = queue or options.get("routing_key") or "default"
    delay = countdown
    if delay is None and eta is not None:
        delay = max(0.0, (eta - utcnow()).total_seconds())
    function = function_for_queue(queue)
    data: dict[str, Any] = {"task": name, "args": list(args or ()), "kwargs": dict(kwargs or {})}
    periodic = options.get("periodic")
    if periodic:  # a dispatcher hand-off (``run_periodic`` semantics on the task function)
        data["periodic"] = str(periodic)
        data["periodic_loop"] = bool(options.get("periodic_loop"))
    task_id = enqueue_impl(function, get_settings().TD_CLOUD_TASKS_LOCATION, data, delay)
    log.info("cloudtask_enqueued", task=name, function=function)
    return Enqueued(task_id, name, function)


def install(capp: Any) -> None:
    """Route every send of ``capp`` (incl. ``Task.apply_async``/``delay``) to Cloud Tasks."""

    def _send_task(name: str, args: Any = None, kwargs: Any = None, **options: Any) -> Enqueued:
        for k in (
            "task_id",
            "producer",
            "link",
            "link_error",
            "result_cls",
            "shadow",
            "task_type",
            "expires",
            "priority",
            "headers",
            "exchange",
            "retries",
            "chord",
            "group_id",
        ):
            options.pop(k, None)
        return send_task(name, args, kwargs, **options)

    capp.send_task = _send_task
    capp.conf.task_always_eager = False


def run_task(capp: Any, name: str, args: Any = None, kwargs: Any = None) -> Any:
    """Execute a registered task body now (Cloud Tasks handler). Raises on failure (-> retry)."""
    task = capp.tasks.get(name)
    if task is None:
        raise LookupError(f"unknown task {name!r}")
    res = task.apply(args=list(args or ()), kwargs=dict(kwargs or {}), throw=True)
    return res.result


# --------------------------------------------------------------------------- beat -> schedules


def _interval_seconds(schedule: Any) -> float | None:
    if isinstance(schedule, int | float):
        return float(schedule)
    if isinstance(schedule, timedelta):
        return schedule.total_seconds()
    run_every = getattr(schedule, "run_every", None)  # celery.schedules.schedule
    if isinstance(run_every, timedelta) and not hasattr(schedule, "_orig_minute"):
        return run_every.total_seconds()
    return None


def cron_for(schedule: Any) -> tuple[str, float | None]:
    """``(cron in UTC, sub-minute interval or None)`` for a beat schedule.

    crontab -> the same 5 fields. Intervals: < 60 s -> every minute + in-call repeat;
    whole minutes dividing an hour -> ``*/N``; whole hours dividing a day -> ``0 */N``;
    one day -> ``0 0 * * *``. Anything else raises (no silent cadence change)."""
    seconds = _interval_seconds(schedule)
    if seconds is None:
        fields = [
            getattr(schedule, f"_orig_{f}", None)
            for f in ("minute", "hour", "day_of_month", "month_of_year", "day_of_week")
        ]
        if any(f is None for f in fields):
            raise ValueError(f"unsupported schedule {schedule!r}")
        return " ".join(str(f).replace(" ", "") for f in fields), None
    if seconds < 60:
        return "* * * * *", seconds
    if seconds % 60 == 0:
        minutes = int(seconds // 60)
        if minutes == 1:
            return "* * * * *", None
        if minutes < 60 and 60 % minutes == 0:
            return f"*/{minutes} * * * *", None
        if minutes % 60 == 0:
            hours = minutes // 60
            if hours == 1:
                return "0 * * * *", None
            if hours < 24 and 24 % hours == 0:
                return f"0 */{hours} * * *", None
            if hours == 24:
                return "0 0 * * *", None
    raise ValueError(f"interval {seconds}s has no exact cron equivalent")


def function_name_for_job(job_name: str) -> str:
    """``commerce.order_expiry`` -> ``lmsJobCommerceOrderExpiry`` (Cloud Functions id rules)."""
    parts = [p for p in "".join(c if c.isalnum() else " " for c in job_name).split() if p]
    return "lmsJob" + "".join(p[:1].upper() + p[1:] for p in parts)


# Firebase-only scheduled jobs (no Celery beat entry on the VM, where a dedicated process does the
# work). ``coding.process_pending``: the VM's ``worker-judge`` polls ``code_submissions`` every few
# seconds; on Firebase each submission enqueues a Cloud Task (``TD_CODING_SEND_TASKS=1``) and this
# every-minute sweep is the backstop (coordinator decision 2026-11-12).
FIREBASE_ONLY_JOBS: tuple[tuple[str, str, float], ...] = (
    ("coding.process_pending", "coding.process_pending", 60.0),
)


def firebase_jobs() -> list[Any]:
    """Celery beat entries + the Firebase-only jobs (what the scheduled functions run)."""
    from app.core.jobs import PeriodicJob, periodic_jobs

    jobs = list(periodic_jobs())
    names = {j.name for j in jobs}
    jobs += [PeriodicJob(n, t, s) for n, t, s in FIREBASE_ONLY_JOBS if n not in names]
    return sorted(jobs, key=lambda j: j.name)


def schedule_manifest() -> list[dict[str, Any]]:
    """Every beat entry plus the Firebase-only jobs as ``{job, task, function, cron, repeat_seconds}``."""
    out = []
    for j in firebase_jobs():
        cron, repeat = cron_for(j.schedule)
        out.append(
            {
                "job": j.name,
                "task": j.task,
                "function": function_name_for_job(j.name),
                "cron": cron,
                "repeat_seconds": repeat,
                "queue": (j.options or {}).get("queue", "default"),
            }
        )
    return out


def run_handed_off(capp: Any, data: dict[str, Any]) -> None:
    """Task-queue handler body: a dispatcher hand-off (``periodic``) runs like the old scheduled
    function (logged, never retried); anything else is a plain task (raises -> Cloud Tasks retry)."""
    periodic = data.get("periodic")
    if periodic:
        run_periodic(capp, str(periodic), budget_s=50.0, loop=bool(data.get("periodic_loop")))
        return
    run_task(capp, str(data["task"]), data.get("args") or [], data.get("kwargs") or {})


def run_periodic(capp: Any, job_name: str, *, budget_s: float = 50.0, loop: bool = True) -> int:
    """Run one beat entry (repeating sub-minute entries within ``budget_s`` unless ``loop`` is
    False); returns runs made.

    A failing run is logged and the loop continues, like a beat tick whose task failed."""
    job = next((j for j in firebase_jobs() if j.name == job_name), None)
    if job is None:
        raise LookupError(f"unknown periodic job {job_name!r}")
    _cron, repeat = cron_for(job.schedule)
    if not loop:
        repeat = None
    started = time.monotonic()
    runs = 0
    while True:
        tick = time.monotonic()
        try:
            run_task(capp, job.task, job.args, job.kwargs)
        except Exception:  # logged with the traceback at ERROR (Cloud Logging error reporting)
            log.exception("periodic_job_failed", job=job_name)
        runs += 1
        if repeat is None:
            return runs
        next_at = tick + repeat
        if next_at - started > budget_s:
            return runs
        time.sleep(max(0.0, next_at - time.monotonic()))
