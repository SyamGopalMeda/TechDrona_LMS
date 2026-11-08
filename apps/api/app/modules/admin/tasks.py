"""Admin background jobs: ``admin.break_glass_expiry`` (beat, 60 s) ends elevations past their
``expires_at``, revokes the elevated grant and alerts super admins / security reviewers."""

from __future__ import annotations

from celery import shared_task

from app.core.db import get_sessionmaker, system_context
from app.core.jobs import register_periodic, run_async


async def break_glass_expiry() -> int:
    from app.modules.admin.accounts import expire_break_glass

    async with get_sessionmaker()() as session, session.begin():
        await system_context(session, "admin.break_glass_expiry")
        return await expire_break_glass(session)


@shared_task(name="admin.break_glass_expiry", ignore_result=True)
def break_glass_expiry_task() -> int:
    return run_async(break_glass_expiry())


register_periodic("admin.break_glass_expiry", "admin.break_glass_expiry", 60.0, options={"queue": "critical"})
