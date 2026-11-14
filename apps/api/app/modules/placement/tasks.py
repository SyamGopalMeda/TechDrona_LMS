"""Placement background jobs: ``placement.media_scan_sweep`` (beat, every 2 minutes) pulls the
malware-scan result of question images still ``pending`` (SEC-04: viewers never write scan state;
without this sweep a platform image stayed unserved until its author called ``/complete``). A
clean result is accepted only after the presigned-upload window has closed (SEC-18)."""

from __future__ import annotations

from celery import shared_task
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_sessionmaker, system_context
from app.core.jobs import register_periodic, run_async
from app.core.time import utcnow


async def sweep_pending_question_media(session: AsyncSession, *, limit: int = 200) -> int:
    """Resolve pending question images (oldest first). Caller supplies a system context.
    Returns the number of rows that changed."""
    from app.core.firestore.backend import uses_firestore
    from app.modules.placement.models import QuestionMedia
    from app.modules.placement.qbank_router import refresh_scan

    if uses_firestore("placement"):
        from app.modules.placement.repo_firestore import system_repo

        r = system_repo()
        changed = 0
        for fm in await r.pending_media(limit):
            if await refresh_scan(fm):
                fm.updated_at = utcnow()
                await r.save_media(fm)
                changed += 1
        return changed
    rows = list(
        (
            await session.execute(
                select(QuestionMedia)
                .where(QuestionMedia.scan_status == "pending")
                .order_by(QuestionMedia.created_at, QuestionMedia.id)
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
        ).scalars()
    )
    done = 0
    for m in rows:
        if await refresh_scan(m):
            m.updated_at = utcnow()
            done += 1
    await session.flush()
    return done


async def media_scan_sweep() -> int:
    from app.core.firestore.backend import uses_firestore

    if uses_firestore("placement"):
        return await sweep_pending_question_media(None)  # type: ignore[arg-type]
    async with get_sessionmaker()() as session, session.begin():
        await system_context(session, "placement.media_scan_sweep")
        return await sweep_pending_question_media(session)


@shared_task(name="placement.media_scan_sweep", ignore_result=True)
def media_scan_sweep_task() -> int:
    return run_async(media_scan_sweep())


register_periodic("placement.media_scan_sweep", "placement.media_scan_sweep", 120.0)
