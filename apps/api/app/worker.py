"""Celery application (workers + beat).

    celery -A app.worker worker -Q critical,default -c 4 --loglevel=INFO
    celery -A app.worker beat --loglevel=INFO

* Broker: ``REDIS_QUEUE_URL`` (noeviction cluster). Results are disabled
  (``task_ignore_result``): tasks persist their outcome in Postgres.
* Task discovery: every ``app.modules.<name>.tasks`` module is imported (use
  ``celery.shared_task``); periodic entries come from ``app.core.jobs.register_periodic``.
* Core tasks: ``td.core.outbox_relay`` (outbox_events -> handlers registered with
  ``app.core.outbox.register_handler``) and ``td.core.audit_seal`` (audit_outbox ->
  audit_log, role ``td_audit_sealer``; disable with ``TD_AUDIT_SEALER_BEAT_ENABLED=false``
  where the dedicated audit-sealer service runs).
* Safety: ``create_celery`` runs the same production startup gate as the API (COM-08), so a
  worker or beat refuses to start with fake adapters or placeholder keys in production.
* Beat takes a Redis leader lock before scheduling (COM-14); workers touch a liveness file for
  the container healthcheck (E2E-06). See ``app.core.celery_ops``.
"""

from __future__ import annotations

from typing import Any

import structlog
from celery import Celery, shared_task

from app.core import maintenance
from app.core.celery_ops import install_beat_leader_lock, install_worker_health
from app.core.config import get_settings
from app.core.db import make_engine
from app.core.jobs import beat_schedule, register_periodic, run_async
from app.core.logging import configure_logging
from app.core.models_registry import _optional_import, import_all_models, module_names
from app.core.outbox import RelayResult, relay_pending
from app.core.startup_checks import run_startup_checks

log = structlog.get_logger("app.worker")

OUTBOX_RELAY_TASK = "td.core.outbox_relay"
AUDIT_SEAL_TASK = "td.core.audit_seal"


async def _relay_once() -> RelayResult:
    from sqlalchemy.ext.asyncio import AsyncSession

    engine = make_engine(get_settings().DATABASE_URL)
    try:
        async with engine.connect() as conn, conn.begin():
            session = AsyncSession(bind=conn, expire_on_commit=False)
            try:
                return await relay_pending(session)
            finally:
                await session.close()
    finally:
        await engine.dispose()


@shared_task(name=OUTBOX_RELAY_TASK, ignore_result=True)
def outbox_relay() -> dict[str, int]:
    r = run_async(_relay_once())
    if r.dispatched or r.failed:
        log.info("outbox_relayed", dispatched=r.dispatched, failed=r.failed, no_handler=r.skipped_no_handler)
    return {"dispatched": r.dispatched, "failed": r.failed, "no_handler": r.skipped_no_handler}


async def _seal_once() -> int:
    from app.modules.audit.sealer import seal_once

    engine = make_engine(get_settings().sealer_url)
    try:
        return await seal_once(engine)
    finally:
        await engine.dispose()


@shared_task(name=AUDIT_SEAL_TASK, ignore_result=True)
def audit_seal() -> int:
    n = run_async(_seal_once())
    if n:
        log.info("audit_sealed", rows=n)
    return n


def discover_task_modules(capp: Celery | None = None) -> list[str]:
    """Import ``app.modules.<name>.tasks`` for every module (registers shared tasks, outbox
    handlers and periodic jobs). A module may also expose ``register_celery_tasks(celery_app)``
    which is called with the worker's app."""
    found = []
    for name in module_names():
        mod = _optional_import(f"app.modules.{name}.tasks")
        if mod is None:
            continue
        found.append(mod.__name__)
        hook = getattr(mod, "register_celery_tasks", None)
        if capp is not None and callable(hook):
            hook(capp)
    return found


def register_core_jobs() -> None:
    s = get_settings()
    interval = s.TD_OUTBOX_RELAY_INTERVAL_SECONDS
    register_periodic(
        "core.outbox_relay",
        OUTBOX_RELAY_TASK,
        interval,
        options={"queue": "critical", "expires": interval * 2},
    )
    if s.TD_AUDIT_SEALER_BEAT_ENABLED:
        si = s.TD_AUDIT_SEALER_INTERVAL_SECONDS
        register_periodic(
            "core.audit_seal", AUDIT_SEAL_TASK, si, options={"queue": "critical", "expires": max(si * 2, 5.0)}
        )
    maintenance.register_jobs()  # DB-02/DB-04: partitions + retention on the maintenance queue


def create_celery() -> Celery:
    s = get_settings()
    configure_logging(s.LOG_LEVEL, s.LOG_FORMAT, s.TD_SERVICE_NAME)
    capp = Celery("techdrona", broker=s.REDIS_QUEUE_URL, set_as_current=True)
    capp.conf.update(
        result_backend=None,
        task_ignore_result=True,
        task_default_queue="default",
        task_serializer="json",
        accept_content=["json"],
        task_acks_late=True,
        task_reject_on_worker_lost=True,
        worker_prefetch_multiplier=1,
        broker_connection_retry_on_startup=True,
        timezone="UTC",
        enable_utc=True,
    )
    import_all_models()
    discover_task_modules(capp)
    from app.wiring import wire_all

    wire_all()  # outbox handlers + cross-module hooks the relay and jobs rely on
    run_startup_checks(s)  # COM-08: after discovery, so module-registered fakes are checked
    register_core_jobs()
    capp.conf.beat_schedule = beat_schedule()
    install_worker_health(capp)
    install_beat_leader_lock()
    return capp


celery_app: Any = create_celery()
app = celery_app  # ``celery -A app.worker`` looks for ``app``/``celery``
