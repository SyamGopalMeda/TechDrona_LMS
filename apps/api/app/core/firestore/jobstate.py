"""Raw Firestore access for the Firebase dispatcher (``app.core.scheduler`` / ``app.core.jobhints``).

Kept inside the store layer (MIGRATION-PLAN §1.4: no raw Firestore outside ``app/core/firestore``).
System-job access only: the scheduler's hint document and ``limit(1)`` existence checks on the
collections the gated jobs read themselves.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from google.cloud.firestore import DELETE_FIELD, SERVER_TIMESTAMP, FieldFilter

from app.core.firestore.collections import physical_name

HINTS = "scheduler_state"
HINT_DOC = "hints"


def hint_ref(client: Any) -> Any:
    return client.collection(physical_name(HINTS)).document(HINT_DOC)


def hint_payload(collections: Iterable[str]) -> dict[str, Any]:
    """``w.<collection> = SERVER_TIMESTAMP`` (merged into the hint document)."""
    return {"w": dict.fromkeys(sorted(collections), SERVER_TIMESTAMP)}


def delete_marker() -> Any:
    return DELETE_FIELD


async def read_hints(client: Any) -> tuple[dict[str, Any], Any]:
    """``(document data, server read time)`` of the hint document (one billed read)."""
    snap = await hint_ref(client).get()
    return (snap.to_dict() or {}) if snap.exists else {}, getattr(snap, "read_time", None)


async def merge_hints(client: Any, data: dict[str, Any]) -> None:
    await hint_ref(client).set(data, merge=True)


async def exists(client: Any, collection: str, filters: Iterable[tuple[str, str, Any]] = ()) -> bool:
    """Does any document match? One billed read (``select([])``, ``limit(1)``)."""
    q: Any = client.collection(physical_name(collection))
    for f, op, v in filters:
        q = q.where(filter=FieldFilter(f, op, v))
    async for _ in q.select([]).limit(1).stream():
        return True
    return False


async def outbox_has_work(client: Any, max_attempts: int) -> bool:
    """The relay's own eligibility (``core_store._eligible_ids``): any pending event, or a dead
    letter below the current ``max_attempts`` (re-picked when that setting is raised)."""
    coll = client.collection(physical_name("outbox_events"))
    async for _ in coll.order_by("pending_at").select([]).limit(1).stream():
        return True
    async for snap in coll.order_by("dead_at").select(["attempts", "dispatched_at"]).stream():
        d = snap.to_dict() or {}
        if d.get("dispatched_at") is None and int(d.get("attempts") or 0) < max_attempts:
            return True
    return False
