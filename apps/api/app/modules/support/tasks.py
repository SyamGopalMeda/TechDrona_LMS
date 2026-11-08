"""Support background jobs: ``support.auto_close`` (beat, hourly) closes tickets resolved for
more than 7 days without a reply."""

from __future__ import annotations

from celery import shared_task

from app.core.db import get_sessionmaker, system_context
from app.core.jobs import register_periodic, run_async


async def auto_close() -> int:
    from app.modules.support.service import auto_close_resolved

    async with get_sessionmaker()() as session, session.begin():
        await system_context(session, "support.auto_close")
        return await auto_close_resolved(session)


@shared_task(name="support.auto_close", ignore_result=True)
def auto_close_task() -> int:
    return run_async(auto_close())


register_periodic("support.auto_close", "support.auto_close", 3600.0)
