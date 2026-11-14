"""Analytics Celery tasks + beat schedule (Stage 10 backlog A-3).

Every job in ``analytics.jobs._JOBS`` runs through task ``analytics.run_job(name)``. Domain
events arrive through the core outbox relay (``consumer.on_outbox_event``, registered by
``app.wiring``); ``outbox_consumer`` stays as a 10-minute reconciler (see ``consumer.py``).

Report exports (ANL-13..15): ``analytics.export_generate(job_id)`` builds one job (enqueued by
``exports.dispatch``) and ``analytics.exports_sweep`` (60 s) expires files after 24 h, closes
jobs whose approval lapsed and generates ``running`` jobs nobody picked up.
"""

from __future__ import annotations

import uuid
from typing import Any

from celery import shared_task
from celery.schedules import crontab

from app.core.jobs import register_periodic, run_async

RUN_JOB = "analytics.run_job"

# IST = UTC+05:30: 03:30 IST = 22:00 UTC, 04:30 IST = 23:00 UTC, 03:00 IST = 21:30 UTC.
SCHEDULE: dict[str, Any] = {
    "interval_builder": 60.0,
    "video_coverage": 60.0,
    "daily_aggregator": 900.0,
    "outbox_consumer": 600.0,
    "rollups": crontab(minute=0, hour=22),
    "security_feed": crontab(minute=0, hour=23),
    "retention_purge": crontab(minute=30, hour=21),
}


@shared_task(name=RUN_JOB, ignore_result=True)
def run_job_task(name: str) -> dict[str, Any]:
    from app.modules.analytics.jobs import run_job

    return run_async(run_job(name))


EXPORT_GENERATE = "analytics.export_generate"
EXPORT_SWEEP = "analytics.exports_sweep"


async def run_export(job_id: uuid.UUID) -> str:
    """Task body: generate one export job in its own transaction (system context)."""
    from app.core.db import system_context
    from app.core.firestore.sqlstore import store_session
    from app.modules.analytics.exports import generate

    async with store_session() as session:
        await system_context(session, "analytics.export_generate")
        return await generate(session, job_id)


async def run_exports_sweep() -> dict[str, int]:
    from app.core.db import system_context
    from app.core.firestore.sqlstore import store_session
    from app.modules.analytics.exports import sweep

    async with store_session() as session:
        await system_context(session, "analytics.exports_sweep")
        return await sweep(session)


@shared_task(name=EXPORT_GENERATE, ignore_result=True)
def export_generate_task(job_id: str) -> str:
    return run_async(run_export(uuid.UUID(job_id)))


@shared_task(name=EXPORT_SWEEP, ignore_result=True)
def exports_sweep_task() -> dict[str, int]:
    return run_async(run_exports_sweep())


def register_beat() -> None:
    for name, schedule in SCHEDULE.items():
        expires = schedule * 2 if isinstance(schedule, float) else 3600
        register_periodic(f"analytics.{name}", RUN_JOB, schedule, args=(name,), options={"expires": expires})
    register_periodic(EXPORT_SWEEP, EXPORT_SWEEP, 60.0, options={"expires": 120})


register_beat()
