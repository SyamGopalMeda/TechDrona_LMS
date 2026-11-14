"""Firestore repository for privacy requests, the erasure ledger, retention policies and
break-glass sessions (``TD_STORE_ADMIN=firestore``; docs/firebase/agents/data-ops.md).

Rows come back as ``PrivacyRow`` / ``BreakGlassRow`` / ``RetentionRow`` with the ORM attribute
names, so ``privacy.request_out`` / ``accounts.bg_out`` and the route code are shared. Routes
mutate the row and call ``save`` (optimistic lock on ``updated_at``: a concurrent change answers
409 ``conflict`` where Postgres would wait on ``FOR UPDATE``).

Authorization: learner routes use ``ScopedStore(principal)`` (owned family: only their own
requests); staff routes use ``ScopedStore(principal)`` too, so the store re-checks
``privacy.request.process`` / ``breakglass.activate``. System jobs (dashboard counts, erasure
ledger, break-glass expiry) use named jobs, as Postgres used system context.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Any

from app.core.errors import ProblemError
from app.core.firestore.errors import UniqueViolationError
from app.core.firestore.repository import FirestoreRepository, platform_only
from app.core.firestore.store import Doc, ScopedStore, ScopedTransaction
from app.core.principal import Principal
from app.modules.admin.fs_rows import save_row
from app.modules.admin.store_specs import (
    BREAK_GLASS,
    BREAK_GLASS_PERM,
    ERASURE_LEDGER,
    PRIVACY,
    PRIVACY_PERM,
    PRIVACY_REF_NS,
    RETENTION,
    BreakGlassRow,
    ErasureLedgerRow,
    PrivacyRow,
    RetentionRow,
)

_PAGE = 100


async def _all(store: ScopedStore, coll: str, **kw: Any) -> list[Doc]:
    out: list[Doc] = []
    cursor: str | None = None
    while True:
        page = await store.query(coll, limit=_PAGE, cursor=cursor, **kw)
        out += page.items
        if not page.next_cursor:
            return out
        cursor = page.next_cursor


class PrivacyRepo(FirestoreRepository):
    # ------------------------------------------------------------------ learner (owned)

    async def list_for_user(self, user_id: uuid.UUID) -> list[PrivacyRow]:
        docs = await _all(self.store, PRIVACY, user_id=user_id, order_by=(("received_at", "desc"),))
        return [PrivacyRow.of(d) for d in docs]

    async def count_received_since(self, user_id: uuid.UUID, since: datetime) -> int:
        return await self.store.count(PRIVACY, user_id=user_id, filters=(("received_at", ">", since),))

    async def get_request(self, user_id: uuid.UUID | None, request_id: uuid.UUID) -> PrivacyRow | None:
        """``user_id``: the learner reading their own request (another user's is ``None``);
        ``None``: staff (the store requires ``privacy.request.process``)."""
        d = await self.store.get(PRIVACY, str(request_id))
        if d is None:
            return None
        row: PrivacyRow = PrivacyRow.of(d)
        if user_id is not None and row.user_id != user_id:
            return None
        return row

    async def create(self, user_id: uuid.UUID, row: PrivacyRow) -> PrivacyRow:
        if row.user_id != user_id:
            raise ProblemError("not_found")

        async def fn(tx: ScopedTransaction) -> Doc:
            await tx.reserve_unique(PRIVACY_REF_NS, str(row.request_ref), owner=(PRIVACY, str(row.id)))
            return await tx.create(PRIVACY, row.doc(), doc_id=str(row.id))

        try:
            d = await self.store.run_transaction(fn)
        except UniqueViolationError as e:
            raise ProblemError("conflict") from e
        saved: PrivacyRow = PrivacyRow.of(d)
        return saved

    async def save(self, user_id: uuid.UUID | None, row: PrivacyRow) -> PrivacyRow:
        """Persist the attribute changes made on ``row`` (owner or staff, checked by the store)."""
        if user_id is not None and row.user_id != user_id:
            raise ProblemError("not_found")

        async def fn(tx: ScopedTransaction) -> Doc | None:
            return await save_row(tx, PRIVACY, row)

        d = await self.store.run_transaction(fn)
        if d is not None:
            row.mark_saved(d.data)
        return row

    # ------------------------------------------------------------------ staff

    @platform_only(PRIVACY_PERM)
    async def queue(self, open_states: tuple[str, ...], now: datetime) -> list[PrivacyRow]:
        """Open requests or completed in the last 30 days, by ``due_at`` (the PRV queue)."""
        seen: dict[str, Doc] = {}
        for d in await _all(self.store, PRIVACY, filters=(("status", "in", list(open_states)),), order_by=()):
            seen[d.id] = d
        recent = await _all(
            self.store,
            PRIVACY,
            filters=(("completed_at", ">", now - timedelta(days=30)),),
            order_by=(("completed_at", "asc"),),
        )
        for d in recent:
            seen[d.id] = d
        rows: list[PrivacyRow] = [PrivacyRow.of(d) for d in seen.values()]
        rows.sort(key=lambda r: (r.due_at, str(r.id)))
        return rows

    @platform_only(PRIVACY_PERM)
    async def open_counts(self, open_states: tuple[str, ...], now: datetime) -> tuple[int, int]:
        """(open, overdue) for the admin dashboard."""
        f: Any = ("status", "in", list(open_states))
        return (
            await self.store.count(PRIVACY, filters=(f,)),
            await self.store.count(PRIVACY, filters=(f, ("due_at", "<=", now))),
        )

    @platform_only(PRIVACY_PERM)
    async def append_ledger(self, row: ErasureLedgerRow) -> None:
        await self.store.create(ERASURE_LEDGER, row.doc(), doc_id=str(row.id))

    @platform_only(PRIVACY_PERM)
    async def ledger(self) -> list[ErasureLedgerRow]:
        docs = await _all(self.store, ERASURE_LEDGER, order_by=(("erased_at", "asc"),))
        return [ErasureLedgerRow.of(d) for d in docs]

    # ------------------------------------------------------------------ retention (read-only)

    @platform_only("audit.read")
    async def retention_policies(self) -> list[RetentionRow]:
        from app.core.firestore.collation import order_key

        # ORDER BY table_name with the database collation (Firestore would order raw bytes);
        # rows of one table keep document-id order
        docs = await _all(self.store, RETENTION, order_by=())
        return sorted((RetentionRow.of(d) for d in docs), key=lambda r: order_key(r.table_name))

    @platform_only("audit.read")
    async def ensure_retention_defaults(self) -> int:
        """Insert every migration-seeded policy row (``retention_defaults``) whose
        ``(table_name, data_category)`` has no document yet -- the migrations' ``INSERT ... ON
        CONFLICT DO NOTHING``. Existing documents are never changed. Only a system job can write
        (``retention_policies`` has no write permission). Returns the number of rows created."""
        from app.core.time import utcnow
        from app.modules.admin.retention_defaults import DEFAULT_POLICIES

        have = {
            (d.get("table_name"), d.get("data_category"))
            for d in await _all(self.store, RETENTION, order_by=())
        }
        created = 0
        for p in DEFAULT_POLICIES:
            if (p.table_name, p.data_category) in have:
                continue
            now = utcnow()
            row = RetentionRow(
                id=p.doc_id,
                data_category=p.data_category,
                table_name=p.table_name,
                retention_class=p.retention_class,
                retention_interval=p.retention_interval,
                basis=p.basis,
                deletion_method=p.deletion_method,
                legal_hold_aware=True,
                job_name=p.job_name,
                owner_module=p.owner_module,
                is_active=True,
                updated_by=None,
                created_at=now,
                updated_at=now,
            )
            try:
                await self.store.create(RETENTION, row.doc(), doc_id=str(p.doc_id))
            except UniqueViolationError:  # a concurrent seed created it
                continue
            created += 1
        return created


class BreakGlassRepo(FirestoreRepository):
    @platform_only(BREAK_GLASS_PERM)
    async def list_sessions(self, status: str | None, limit: int = 200) -> list[BreakGlassRow]:
        page = await self.store.query(
            BREAK_GLASS,
            filters=(("status", "==", status),) if status else (),
            order_by=(("started_at", "desc"),),
            limit=min(limit, 100),
        )
        docs = list(page.items)
        while page.next_cursor and len(docs) < limit:
            page = await self.store.query(
                BREAK_GLASS,
                filters=(("status", "==", status),) if status else (),
                order_by=(("started_at", "desc"),),
                limit=min(limit - len(docs), 100),
                cursor=page.next_cursor,
            )
            docs += page.items
        return [BreakGlassRow.of(d) for d in docs[:limit]]

    @platform_only(BREAK_GLASS_PERM)
    async def active_for(self, holder_id: uuid.UUID) -> BreakGlassRow | None:
        page = await self.store.query(
            BREAK_GLASS,
            filters=(("user_id", "==", str(holder_id)), ("status", "==", "active")),
            order_by=(),
            limit=2,
        )
        if len(page.items) > 1:  # Postgres scalar_one_or_none() raises on two rows as well
            raise RuntimeError("more than one active break-glass session")
        return BreakGlassRow.of(page.items[0]) if page.items else None

    @platform_only(BREAK_GLASS_PERM)
    async def get(self, session_id: uuid.UUID) -> BreakGlassRow | None:
        d = await self.store.get(BREAK_GLASS, str(session_id))
        return BreakGlassRow.of(d) if d else None

    @platform_only(BREAK_GLASS_PERM)
    async def save(self, row: BreakGlassRow) -> BreakGlassRow:
        async def fn(tx: ScopedTransaction) -> Doc | None:
            return await save_row(tx, BREAK_GLASS, row)

        d = await self.store.run_transaction(fn)
        if d is not None:
            row.mark_saved(d.data)
        return row

    @platform_only(BREAK_GLASS_PERM)
    async def due_for_expiry(self, now: datetime) -> list[BreakGlassRow]:
        docs = await _all(self.store, BREAK_GLASS, filters=(("status", "==", "active"),), order_by=())
        return [r for r in (BreakGlassRow.of(d) for d in docs) if r.expires_at <= now]

    @platform_only(BREAK_GLASS_PERM)
    async def count_active(self) -> int:
        return await self.store.count(BREAK_GLASS, filters=(("status", "==", "active"),))


def privacy_repo(principal: Principal | None, job: str = "admin.privacy") -> PrivacyRepo:
    return PrivacyRepo(ScopedStore(principal) if principal is not None else ScopedStore.system(job))


def break_glass_repo(principal: Principal | None, job: str = "admin.break_glass") -> BreakGlassRepo:
    return BreakGlassRepo(ScopedStore(principal) if principal is not None else ScopedStore.system(job))
