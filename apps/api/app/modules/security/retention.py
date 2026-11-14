"""``purge_closed_cases`` (privacy-and-data-retention D8 and §7; migration ``support_0003``).

Weekly on the Celery ``maintenance`` queue, as ``td_maintenance`` (``DATABASE_MAINTENANCE_URL``;
the role may only EXECUTE the ``maint.*`` functions):

1. attachments of cases closed more than 90 days ago (not on legal hold): the objects are deleted
   from the private uploads bucket through ``app.modules.media.storage`` and only then the
   attachment lists are emptied (``maint.clear_closed_case_attachments``), so a failed delete
   leaves the keys in place for the next run;
2. case data (case, notes, decisions, unblock requests, case-linked restrictions) 1 year after
   closure, 3 years if disputed (``maint.purge_closed_cases``).

Every step is idempotent and writes its own ``audit_outbox`` summary. Without a maintenance URL
the job skips with a warning (it never falls back to the application role).
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from collections.abc import Awaitable, Callable
from typing import Any

import structlog

from app.core.maintenance import call_maintenance
from app.modules.media import storage

log = structlog.get_logger("app.security.retention")

PURGE_CLOSED_CASES_TASK = "td.security.purge_closed_cases"
ATTACHMENT_BATCH = 500
CASE_BATCH = 500
MAX_ROUNDS = 50

Runner = Callable[[str, dict[str, Any]], Awaitable[list[dict[str, Any]] | None]]


async def purge_case_attachments(
    run: Runner = call_maintenance, *, batch: int = ATTACHMENT_BATCH
) -> int | None:
    """Delete closed-case attachment objects, then clear their references. Returns the number
    of objects deleted (``None`` when maintenance is not configured)."""
    bucket = storage.storage_settings().S3_BUCKET_UPLOADS
    total = 0
    for _ in range(MAX_ROUNDS):
        rows = await run("SELECT * FROM maint.closed_case_attachments(:n)", {"n": batch})
        if rows is None:
            return None
        if not rows:
            break
        ids: dict[str, set[uuid.UUID]] = defaultdict(set)
        keys: list[str] = []
        for r in rows:
            ids[str(r["source"])].add(r["row_id"])
            if r["s3_key"]:
                keys.append(str(r["s3_key"]))
        # Objects first: a failure raises before any reference is dropped.
        total += await storage.delete_objects(bucket, keys)
        for source, row_ids in sorted(ids.items()):
            await run(
                "SELECT maint.clear_closed_case_attachments(:s, CAST(:ids AS uuid[])) AS n",
                {"s": source, "ids": sorted(row_ids, key=str)},
            )
        if len({(r["source"], r["row_id"]) for r in rows}) < batch:
            break
    return total


async def purge_case_rows(
    run: Runner = call_maintenance, *, batch: int = CASE_BATCH
) -> dict[str, int] | None:
    out: dict[str, int] = defaultdict(int)
    for _ in range(MAX_ROUNDS):
        rows = await run("SELECT * FROM maint.purge_closed_cases(:b)", {"b": batch})
        if rows is None:
            return None
        for r in rows:
            out[str(r["table_name"])] += int(r["rows_deleted"])
        cases = next((int(r["rows_deleted"]) for r in rows if r["table_name"] == "security_cases"), 0)
        if cases < batch:
            break
    return dict(out)


def default_runner() -> Runner:
    """``maint.*`` on Postgres (``td_maintenance``), or the same functions over the Firestore
    security store when ``TD_STORE_SECURITY=firestore`` (``repo_fs_controls.maintenance_runner``)."""
    from app.core.firestore.backend import uses_firestore

    if uses_firestore("security"):
        from app.modules.security.repo_fs_controls import maintenance_runner

        return maintenance_runner
    return call_maintenance


async def purge_closed_cases(run: Runner | None = None) -> dict[str, Any] | None:
    run = run or default_runner()
    objects = await purge_case_attachments(run)
    if objects is None:
        return None
    rows = await purge_case_rows(run)
    result: dict[str, Any] = {"attachment_objects_deleted": objects, "rows_deleted": rows or {}}
    log.info("security_closed_cases_purged", **result)
    return result
