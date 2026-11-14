"""Media background jobs: ``media.scan_sweep`` (beat, every 2 minutes) is the malware-scan
consumer - it pulls GuardDuty Malware Protection results (object tags) for S3 lesson assets
still ``pending`` and marks them ``available`` (clean) or ``failed`` (infected)."""

from __future__ import annotations

from celery import shared_task

from app.core.db import job_session
from app.core.jobs import register_periodic, run_async


async def scan_sweep() -> int:
    from app.modules.media.service import sweep_pending_scans

    async with job_session("media.scan_sweep") as session:  # NO_POSTGRES on the Firebase stack
        return await sweep_pending_scans(session)


@shared_task(name="media.scan_sweep", ignore_result=True)
def scan_sweep_task() -> int:
    return run_async(scan_sweep())


register_periodic("media.scan_sweep", "media.scan_sweep", 120.0)
