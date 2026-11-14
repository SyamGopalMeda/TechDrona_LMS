"""Partition maintenance and retention purge jobs (DB-02, DB-04; privacy §7; schema §1.2-§1.4).

Both jobs run on the Celery ``maintenance`` queue (compose/ECS ``worker-maintenance``) and log
in as ``td_maintenance`` through ``DATABASE_MAINTENANCE_URL``. That role has no table
privileges: it may only EXECUTE the ``maint.*`` SECURITY DEFINER functions created by
migration ``core_base_0002``. When the URL is not configured the jobs skip with a warning —
they never fall back to the application role.

* ``td.core.maint_partitions`` (daily): ``maint.run_partition_maintenance(3)`` premakes the
  current and next 3 monthly partitions of the 10 partitioned parents, hardened like their
  DEFAULT partitions, moving any DEFAULT rows of those months.
* ``td.core.maint_retention`` (daily): ``maint.run_retention()`` drops expired monthly
  partitions and deletes expired rows per ``retention_policies``.

Each SQL entry point writes its own ``audit_outbox`` summary (privacy §7: every run is audited).

Firebase (``lmsScheduler`` hands both entries to ``lmsTasksMaintenance``; agent retention-fs):

* ``maint_retention`` also runs ``app.core.retention_fs.run_retention`` -- the same 12 predicates,
  intervals and audit summary over the collections of modules on Firestore. With no Postgres at
  all (``postgres_enabled()`` False) the SQL call is skipped with an info log, not a warning.
* ``maint_partitions`` is a logged no-op without Postgres: Firestore has no partitions (a
  collection grows without premade children), so there is nothing to premake or harden.

On the VM no module is on Firestore and Postgres is enabled: both jobs run exactly as before.
"""

from __future__ import annotations

from typing import Any

import structlog
from celery import shared_task
from celery.schedules import crontab
from sqlalchemy import text

from app.core.config import get_settings
from app.core.db import make_engine
from app.core.jobs import register_periodic, run_async

log = structlog.get_logger("app.maintenance")

PARTITIONS_TASK = "td.core.maint_partitions"
RETENTION_TASK = "td.core.maint_retention"
MONTHS_AHEAD = 3


async def _call(sql: str, params: dict[str, Any]) -> list[dict[str, Any]] | None:
    url = get_settings().DATABASE_MAINTENANCE_URL
    if not url:
        log.warning("maintenance_skipped", reason="DATABASE_MAINTENANCE_URL not configured")
        return None
    engine = make_engine(url)
    try:
        async with engine.begin() as conn:
            rows = (await conn.execute(text(sql), params)).mappings().all()
            return [dict(r) for r in rows]
    finally:
        await engine.dispose()


async def call_maintenance(sql: str, params: dict[str, Any]) -> list[dict[str, Any]] | None:
    """Run one ``maint.*`` statement as ``td_maintenance`` in its own transaction (module
    retention jobs, e.g. ``security.purge_closed_cases``). ``None`` when not configured."""
    return await _call(sql, params)


def _no_postgres() -> bool:
    from app.core.runtime import postgres_enabled

    return not postgres_enabled()


async def run_partition_maintenance(months_ahead: int = MONTHS_AHEAD) -> list[dict[str, Any]] | None:
    if _no_postgres():
        # Firestore has no partitions: nothing to premake, harden or move. Not a failure.
        log.info("partitions_noop", reason="no Postgres: Firestore collections have no partitions")
        return []
    rows = await _call("SELECT * FROM maint.run_partition_maintenance(:m)", {"m": months_ahead})
    if rows is not None:
        changed = [r for r in rows if r["action"] != "exists"]
        log.info("partitions_maintained", checked=len(rows), changed=len(changed))
    return rows


async def run_retention(batch: int = 5000, max_batches: int = 200) -> list[dict[str, Any]] | None:
    from app.core import retention_fs

    if not retention_fs.firestore_targets():  # the VM: unchanged
        return await _run_retention_sql(batch, max_batches)
    rows: list[dict[str, Any]] | None = None
    if _no_postgres():
        log.info("retention_sql_skipped", reason="no Postgres: retention runs on Firestore")
    else:  # hybrid stack: the Postgres tables keep their SQL purge
        rows = await _run_retention_sql(batch, max_batches)
    fs_rows = await retention_fs.run_retention(batch, max_batches)
    return [*(rows or []), *fs_rows]


async def _run_retention_sql(batch: int, max_batches: int) -> list[dict[str, Any]] | None:
    rows = await _call("SELECT * FROM maint.run_retention(:b, :mb)", {"b": batch, "mb": max_batches})
    if rows is not None:
        log.info(
            "retention_purged",
            rows=sum(int(r["rows_deleted"]) for r in rows),
            partitions=sum(int(r["partitions_dropped"]) for r in rows),
        )
    return rows


@shared_task(name=PARTITIONS_TASK, ignore_result=True)
def maint_partitions() -> int:
    rows = run_async(run_partition_maintenance())
    return 0 if rows is None else len(rows)


@shared_task(name=RETENTION_TASK, ignore_result=True)
def maint_retention() -> int:
    rows = run_async(run_retention())
    return 0 if rows is None else sum(int(r["rows_deleted"]) for r in rows)


def register_jobs() -> None:
    """Beat entries (UTC; 21:30/22:30 UTC = 03:00/04:00 IST, privacy §7) on ``maintenance``."""
    opts = {"queue": "maintenance", "expires": 3 * 3600}
    register_periodic("core.maint_partitions", PARTITIONS_TASK, crontab(hour=21, minute=30), options=opts)
    register_periodic("core.maint_retention", RETENTION_TASK, crontab(hour=22, minute=30), options=opts)
