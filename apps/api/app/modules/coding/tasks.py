"""Queue integration for the judge worker.

The durable queue is the ``code_submissions`` table (``status='queued'``, ``queue_name``).
``queue_name`` (``judge_assessment`` > ``judge_submit`` > ``judge_run``) is a *priority label on
the row*, not a Celery queue that something must consume.

* ``python -m app.modules.coding.worker`` (the ``worker-judge`` service, the only process with the
  sandbox credentials) polls the table (``FOR UPDATE SKIP LOCKED``), highest priority first,
  every ``--interval`` seconds. That poller is the judging path (COM-09).
* No Celery beat entry is registered and no wake-up task is published by default: nothing in the
  deployed compose consumes ``judge_*`` Celery queues, and the ``redis-queue`` broker is
  ``noeviction``, so unconsumed messages would accumulate until the broker fills.
* Opt-in only: a deployment that ALSO runs ``celery -A app.worker worker -Q
  judge_assessment,judge_submit,judge_run`` inside ``worker-judge`` may set
  ``TD_CODING_SEND_TASKS=1`` to get low-latency wake-ups (``notify_enqueued``) — the tasks
  below are registered in every Celery app for that case; the DB row stays the source of truth.
"""

from __future__ import annotations

import importlib
import os
import uuid
from typing import Any

import structlog

log = structlog.get_logger("app.coding.tasks")

TASK_NAME = "coding.judge_submission"


WAKEUPS_ENV = "TD_CODING_SEND_TASKS"


def wakeups_enabled() -> bool:
    """Celery wake-ups only when the deployment declares a ``judge_*`` consumer (COM-09)."""
    return os.environ.get(WAKEUPS_ENV) == "1"


def _celery_app() -> Any | None:
    import sys

    if not wakeups_enabled():
        return None
    # Prefer an already-built worker app; importing ``app.worker`` builds a Celery app (and
    # connects to the broker), which only happens when wake-ups were explicitly enabled.
    mod = sys.modules.get("app.worker")
    if mod is None:
        try:
            mod = importlib.import_module("app.worker")
        except ModuleNotFoundError:  # pragma: no cover
            return None
    return getattr(mod, "celery_app", None)


def notify_enqueued(submission_id: uuid.UUID, queue: str) -> None:
    """Best-effort wake-up; never raises (the DB row is the source of truth).

    Note: sent before commit; the worker treats a missing/uncommitted row as "retry later"."""
    app = _celery_app()
    if app is None:
        return
    try:
        app.send_task(TASK_NAME, args=[str(submission_id)], queue=queue, countdown=1)
    except Exception as e:  # broker down: polling worker still picks it up
        log.warning("coding.enqueue_failed", submission_id=str(submission_id), error=type(e).__name__)


SWEEP_TASK = "coding.process_pending"


def register_celery_tasks(celery_app: Any) -> None:
    @celery_app.task(name=TASK_NAME, acks_late=True, max_retries=3)
    def judge_submission_task(submission_id: str) -> str:
        from app.core.jobs import run_async
        from app.modules.coding.worker import judge_by_id

        return run_async(judge_by_id(uuid.UUID(submission_id)))

    @celery_app.task(name=SWEEP_TASK, ignore_result=True)
    def process_pending_task(limit: int = 16) -> int:
        """Safety sweep for rows whose wake-up was lost (broker down, sent before commit)."""
        from app.core.jobs import run_async
        from app.modules.coding.worker import process_pending

        return len(run_async(process_pending(limit=limit)))


# No beat entry for ``SWEEP_TASK`` (COM-09): the ``worker-judge`` DB poller already sweeps every
# ``--interval`` seconds, and a beat entry on ``judge_assessment`` had no consumer. Routing it to a
# consumed queue (``default``) would run judging in a worker without sandbox credentials.
