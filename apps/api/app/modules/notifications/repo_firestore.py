"""Firestore repository for notifications (``TD_STORE_NOTIFICATIONS=firestore``).

The Postgres paths in ``service.py`` / ``router.py`` / ``erasure.py`` dispatch here when the
switch is on; the HTTP contract is unchanged. Rows come back as ``NotificationRow`` with the same
attribute names and Python types as the ORM model.

Authorization (replacing RLS ``O``):

* Inbox routes use ``ScopedStore(principal)``: every method takes the owner's ``user_id`` and the
  store refuses other users' documents (``None`` / ``not_found``, no existence oracle).
* Writes for any user (``notify`` from consumers, jobs, fan-out, staff flows), the announcement
  cap and erasure use named system jobs. ``service.notify`` first applies the Postgres ``O``
  predicate to the caller's transaction context (``app.user_id`` = owner or
  ``app.is_platform``), so a write Postgres would refuse is refused here too.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.core.firestore.errors import UniqueViolationError
from app.core.firestore.repository import FirestoreRepository, platform_only
from app.core.firestore.store import Page, ScopedStore, ScopedTransaction
from app.modules.notifications.store_specs import DEDUPE, NOTIFICATIONS, dedupe_id

# ``@platform_only`` permission for the system-job methods: no role holds it, so only a named
# system job passes (the Postgres ``app.is_platform`` system-context branch).
SYSTEM_ONLY = "notification.system"
_PAGE = 100


def _uuid(v: Any) -> uuid.UUID | None:
    return uuid.UUID(str(v)) if v else None


@dataclass
class NotificationRow:
    id: uuid.UUID
    user_id: uuid.UUID
    organization_id: uuid.UUID | None
    template_key: str
    template_version: int
    category: str
    channels: list[str]
    data: dict[str, Any]
    priority: str
    status: str
    delivery: dict[str, Any] = field(default_factory=dict)
    dedupe_key: str | None = None
    read_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @classmethod
    def of(cls, d: dict[str, Any]) -> NotificationRow:
        return cls(
            id=uuid.UUID(d["id"]),
            user_id=uuid.UUID(d["user_id"]),
            organization_id=_uuid(d.get("organization_id")),
            template_key=d["template_key"],
            template_version=int(d.get("template_version") or 1),
            category=d["category"],
            channels=list(d.get("channels") or []),
            data=dict(d.get("data") or {}),
            priority=d.get("priority") or "normal",
            status=d.get("status") or "queued",
            delivery=dict(d.get("delivery") or {}),
            dedupe_key=d.get("dedupe_key"),
            read_at=d.get("read_at"),
            created_at=d.get("created_at"),
            updated_at=d.get("updated_at"),
        )


class NotificationRepo(FirestoreRepository):
    # ------------------------------------------------------------------ owner inbox

    async def inbox(self, user_id: uuid.UUID, *, unread_only: bool, cursor: str | None, limit: int) -> Page:
        filters: list[Any] = [("channels", "array-contains", "in_app")]
        if unread_only:
            filters.append(("read_at", "==", None))
        return await self.store.query(
            NOTIFICATIONS,
            user_id=user_id,
            filters=filters,
            order_by=(("id", "desc"),),
            limit=limit,
            cursor=cursor,
        )

    async def unread_count(self, user_id: uuid.UUID) -> int:
        return await self.store.count(
            NOTIFICATIONS,
            user_id=user_id,
            filters=(("channels", "array-contains", "in_app"), ("read_at", "==", None)),
        )

    async def mark_read(
        self, user_id: uuid.UUID, notification_id: uuid.UUID, now: datetime
    ) -> datetime | None:
        """``read_at`` (set now if unread); ``None`` when absent or not the caller's."""

        async def fn(tx: ScopedTransaction) -> datetime | None:
            d = await tx.get(NOTIFICATIONS, str(notification_id))
            if d is None or d.get("user_id") != str(user_id):
                return None
            if d.get("read_at") is not None:
                read_at: datetime = d["read_at"]
                return read_at
            await tx.update(NOTIFICATIONS, d.id, {"read_at": now})
            return now

        return await self.store.run_transaction(fn)

    async def mark_all_read(self, user_id: uuid.UUID, now: datetime) -> int:
        """Every unread row of the owner (all channels, as the Postgres ``UPDATE``).

        One short transaction per row: idempotent, and a concurrent single ``mark_read`` cannot
        be double counted (the row is re-read inside its transaction)."""
        n = 0
        while True:
            page = await self.store.query(
                NOTIFICATIONS,
                user_id=user_id,
                filters=(("read_at", "==", None),),
                order_by=(("id", "asc"),),
                limit=_PAGE,
            )
            if not page.items:
                return n
            for d in page.items:
                n += await self._mark_one(d.id, now)

    async def _mark_one(self, doc_id: str, now: datetime) -> int:
        async def fn(tx: ScopedTransaction) -> int:
            cur = await tx.get(NOTIFICATIONS, doc_id)
            if cur is None or cur.get("read_at") is not None:
                return 0
            await tx.update(NOTIFICATIONS, doc_id, {"read_at": now})
            return 1

        return await self.store.run_transaction(fn)

    async def list_for_user(self, user_id: uuid.UUID) -> list[NotificationRow]:
        out: list[NotificationRow] = []
        cursor: str | None = None
        while True:
            page = await self.store.query(
                NOTIFICATIONS, user_id=user_id, order_by=(("id", "asc"),), limit=_PAGE, cursor=cursor
            )
            out += [NotificationRow.of(d.data) for d in page.items]
            if not page.next_cursor:
                return out
            cursor = page.next_cursor

    # ------------------------------------------------------------------ system writes

    async def create(self, user_id: uuid.UUID, doc: dict[str, Any]) -> bool:
        """Insert ``doc`` (owned by ``user_id``); False when ``(user_id, dedupe_key)`` exists.

        The dedupe document is read and created in the same transaction as the row, so two
        concurrent deliveries of one event write exactly one notification."""
        key = doc.get("dedupe_key")
        nid = doc["id"]

        async def fn(tx: ScopedTransaction) -> bool:
            if key:
                did = dedupe_id(user_id, key)
                if await tx.get(DEDUPE, did) is not None:
                    return False
                await tx.create(DEDUPE, {"user_id": user_id, "notification_id": nid}, doc_id=did)
            await tx.create(NOTIFICATIONS, {**doc, "user_id": user_id}, doc_id=nid)
            return True

        try:
            return await self.store.run_transaction(fn)
        except UniqueViolationError:
            return False

    async def set_delivery(
        self, user_id: uuid.UUID, notification_id: str, delivery: dict[str, Any], status: str
    ) -> None:
        await self.store.update(NOTIFICATIONS, notification_id, {"delivery": delivery, "status": status})

    @platform_only(SYSTEM_ONLY)
    async def distinct_dedupe_keys_since(self, template_key: str, batch_id: str, since: datetime) -> int:
        """Announcement cap: distinct ``dedupe_key`` of a template for one batch since ``since``."""
        keys: set[str] = set()
        cursor: str | None = None
        while True:
            page = await self.store.query(
                NOTIFICATIONS,
                filters=(
                    ("template_key", "==", template_key),
                    ("data.batch_id", "==", batch_id),
                    ("created_at", ">", since),
                ),
                order_by=(("created_at", "asc"),),
                limit=_PAGE,
                cursor=cursor,
            )
            keys |= {d["dedupe_key"] for d in page.items if d.get("dedupe_key")}
            if not page.next_cursor:
                return len(keys)
            cursor = page.next_cursor

    async def erase_user(self, user_id: uuid.UUID) -> int:
        """Delete the user's notifications and their dedupe guards (DB-01). Idempotent."""
        n = 0
        for coll in (NOTIFICATIONS, DEDUPE):
            while True:
                page = await self.store.query(coll, user_id=user_id, order_by=(), limit=_PAGE)
                if not page.items:
                    break
                for d in page.items:
                    await self.store.delete(coll, d.id)
                n += len(page.items) if coll == NOTIFICATIONS else 0
        return n


def user_repo(principal: Any) -> NotificationRepo:
    return NotificationRepo(ScopedStore(principal))


def system_repo(job: str) -> NotificationRepo:
    return NotificationRepo(ScopedStore.system(job))
