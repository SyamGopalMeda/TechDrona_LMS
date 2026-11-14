"""Firestore collections of the notifications module (MIGRATION-PLAN P2; ``TD_STORE_NOTIFICATIONS``).

* ``notifications/{id}`` — one document per row (``id`` = the uuid7 string, so ordering by
  ``id`` is ordering by creation, as the Postgres inbox orders by ``id DESC``). Family
  ``owned`` (Postgres RLS ``O``: the owner, or platform/system context). TTL ``expire_at`` =
  ``created_at`` + 365 days (privacy D13 / ``R-NOTIF``: the Postgres ``purge_notifications``
  retention rule, 1 year).
* ``notification_dedupe/{sha256(user_id, dedupe_key)}`` — ``{user_id, notification_id}``: the
  Postgres partial unique index ``ux_notif_dedupe (user_id, dedupe_key)``. Created in the same
  transaction as the notification; same TTL and erasure as the notification it guards.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from app.core.firestore.backfill import Row, TableMapping, register_mapping
from app.core.firestore.collections import CollectionSpec, register_collection
from app.core.firestore.ids import hashed_id

NOTIFICATIONS = "notifications"
DEDUPE = "notification_dedupe"
RETENTION = timedelta(days=365)

# RLS O: the owner reads and writes their rows; nobody else except a named system job
# (the Postgres ``app.is_platform`` branch, used by fan-out, consumers, jobs and erasure).
register_collection(CollectionSpec(NOTIFICATIONS, "owned", ttl=RETENTION))
register_collection(CollectionSpec(DEDUPE, "owned", ttl=RETENTION))


def dedupe_id(user_id: Any, dedupe_key: str) -> str:
    return hashed_id("notif_dedupe", f"{user_id}\0{dedupe_key}", normalize=False)


def _opt(v: Any) -> str | None:
    return str(v) if v is not None else None


def notification_doc(r: Row) -> dict[str, Any]:
    return {
        "id": str(r["id"]),
        "user_id": str(r["user_id"]),
        "organization_id": _opt(r["organization_id"]),
        "template_key": r["template_key"],
        "template_version": int(r["template_version"]),
        "category": r["category"],
        "channels": list(r["channels"] or []),
        "data": dict(r["data"] or {}),
        "priority": r["priority"],
        "status": r["status"],
        "delivery": dict(r["delivery"] or {}),
        "dedupe_key": r["dedupe_key"],
        "read_at": r["read_at"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "expire_at": r["created_at"] + RETENTION,
    }


def dedupe_doc(r: Row) -> dict[str, Any]:
    return {
        "user_id": str(r["user_id"]),
        "notification_id": str(r["id"]),
        "created_at": r["created_at"],
        "expire_at": r["created_at"] + RETENTION,
    }


register_mapping(
    TableMapping("notifications", "notifications", NOTIFICATIONS, lambda r: str(r["id"]), notification_doc)
)
register_mapping(
    TableMapping(
        "notifications",
        "notifications",
        DEDUPE,
        lambda r: dedupe_id(r["user_id"], r["dedupe_key"]),
        dedupe_doc,
        where="dedupe_key IS NOT NULL",
    )
)
