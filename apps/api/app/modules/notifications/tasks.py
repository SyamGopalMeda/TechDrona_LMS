"""Notifications periodic jobs (discovered by ``app.worker.discover_task_modules``).

* ``notifications.renewal_reminders`` (daily): 7-day annual renewal reminder (COM-17,
  FR-COM-005). Idempotent per subscription period through the notification ``dedupe_key``.
"""

from __future__ import annotations

import structlog
from celery import shared_task

from app.core.db import get_sessionmaker, system_context
from app.core.jobs import register_periodic, run_async
from app.core.time import utcnow

log = structlog.get_logger("app.notifications.tasks")

RENEWAL_TASK = "notifications.renewal_reminders"


async def renewal_reminders() -> int:
    from app.modules.notifications.consumers import send_renewal_reminders

    async with get_sessionmaker()() as session, session.begin():
        await system_context(session, "notifications.renewal_reminders")
        n = await send_renewal_reminders(session, utcnow())
    if n:
        log.info("renewal_reminders_sent", count=n)
    return n


@shared_task(name=RENEWAL_TASK, ignore_result=True)
def renewal_reminders_task() -> int:
    return run_async(renewal_reminders())


register_periodic(RENEWAL_TASK, RENEWAL_TASK, 86_400.0, options={"queue": "default", "expires": 3_600})
