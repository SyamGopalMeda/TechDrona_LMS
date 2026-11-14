"""Firestore repository of the security module (``TD_STORE_SECURITY=firestore``) -- slice 1:
restrictions, the per-user security state and case lookups (data-ops agent).

This slice serves the hot path: ``restrictions.restriction_state`` runs on **every authenticated
request** (the sessions resolver hook), plus apply/end of restrictions and the admin/support/
privacy read helpers of ``security.public``. Rows come back as the ``store_specs`` row classes
(same attribute names and Python types as the ORM rows), so ``restriction_out`` and callers are
shared.

Invariants:
* one active restriction per (user, family) -- ``restriction_heads/{user}:{family}`` is read and
  written in the same transaction as the rows (Postgres ``ux_ar_active_family``);
* rows are owner read-only (DB-05): every method runs as a named system job, as Postgres did
  (``as_system(session, "security.*")``); the routes keep their permission checks.
"""

from __future__ import annotations

import uuid
from typing import Any

from app.core.firestore.ids import compose_id
from app.core.firestore.repository import FirestoreRepository, platform_only
from app.core.firestore.store import Doc, ScopedStore, ScopedTransaction
from app.modules.admin.fs_rows import FsRow, save_row
from app.modules.security.store_specs import (
    RESTRICTION_HEADS,
    CaseRow,
    RestrictionRow,
    UnblockRow,
    UserStateRow,
)

RESTRICTIONS = "account_restrictions"
STATE = "security_user_state"
CASES = "security_cases"
UNBLOCK = "unblock_requests"
_PAGE = 100
SYS = "security.case.read"  # @platform_only key: system jobs pass; principals would need it


async def _all(store: ScopedStore, coll: str, **kw: Any) -> list[Doc]:
    out: list[Doc] = []
    cursor: str | None = None
    while True:
        page = await store.query(coll, limit=_PAGE, cursor=cursor, **kw)
        out += page.items
        if not page.next_cursor:
            return out
        cursor = page.next_cursor


def head_id(user_id: Any, family: str) -> str:
    return compose_id(str(user_id), family)


class _AttachmentOps(FirestoreRepository):
    """INV-12 helpers mixed into SecurityRepo (unblock requests are low volume: a scan of the
    collection is bounded by the number of appeals, not by traffic)."""

    store: ScopedStore

    async def _unblock_docs(self) -> list[Doc]:
        return await self.store.scan(UNBLOCK)  # document-id order = request id order

    @platform_only(SYS)
    async def set_attachment_scan(self, s3_key: str, result: str) -> int:
        matched = 0
        for d in await self._unblock_docs():
            row = UnblockRow.of(d)
            atts = list(row.attachments or [])
            if not any(isinstance(a, dict) and a.get("s3_key") == s3_key for a in atts):
                continue
            matched += 1
            new = [
                {**a, "scan_status": result}
                if isinstance(a, dict) and a.get("s3_key") == s3_key and a.get("scan_status") == "pending"
                else a
                for a in atts
            ]
            if new != atts:
                row.attachments = new

                async def fn(tx: ScopedTransaction, row: Any = row) -> Doc | None:
                    return await save_row(tx, UNBLOCK, row)

                await self.store.run_transaction(fn)
        return matched

    @platform_only(SYS)
    async def pending_attachment_keys(self, limit: int) -> list[str]:
        out: list[str] = []
        for d in await self._unblock_docs():  # scan() is in document-id (= request id) order
            for a in UnblockRow.of(d).attachments or []:
                if isinstance(a, dict) and a.get("scan_status") == "pending" and a.get("s3_key") is not None:
                    out.append(a["s3_key"])
                    if len(out) >= limit:
                        return out
        return out


class SecurityRepo(_AttachmentOps):
    # ------------------------------------------------------------------ restrictions

    async def active_restrictions(self, user_id: uuid.UUID) -> list[Any]:
        docs = await _all(
            self.store, RESTRICTIONS, user_id=user_id, filters=(("ended_at", "==", None),), order_by=()
        )
        return [RestrictionRow.of(d) for d in docs]

    async def active_for(self, user_id: uuid.UUID, family: str) -> Any | None:
        head = await self.store.get(RESTRICTION_HEADS, head_id(user_id, family))
        if head is None or not head.get("active_id"):
            return None
        d = await self.store.get(RESTRICTIONS, head["active_id"])
        return RestrictionRow.of(d) if d is not None and d.get("ended_at") is None else None

    async def restrictions_for_user(self, user_id: uuid.UUID, *, active_only: bool = False) -> list[Any]:
        f: Any = (("ended_at", "==", None),) if active_only else ()
        docs = await _all(self.store, RESTRICTIONS, user_id=user_id, filters=f, order_by=())
        return [RestrictionRow.of(d) for d in docs]

    async def insert_restriction(self, user_id: uuid.UUID, row: FsRow) -> tuple[Any | None, Any]:
        """End the user's active row of the same family (``superseded``) and insert ``row`` as
        the active one, atomically. Returns (previous row or None, saved row)."""
        if row.user_id != user_id:
            raise ValueError("restriction user mismatch")
        hid = head_id(row.user_id, row.family)

        async def fn(tx: ScopedTransaction) -> tuple[Any | None, Any]:
            head = await tx.get(RESTRICTION_HEADS, hid)
            prev_doc = (
                await tx.get(RESTRICTIONS, head["active_id"]) if head and head.get("active_id") else None
            )
            prev = None
            if prev_doc is not None and prev_doc.get("ended_at") is None:
                prev = RestrictionRow.of(prev_doc)
                prev.ended_at = row.starts_at
                prev.end_reason = "superseded"
                prev.ended_by = row.applied_by
                await save_row(tx, RESTRICTIONS, prev, current=prev_doc)
            created = await tx.create(RESTRICTIONS, row.doc(), doc_id=str(row.id))
            await tx.put(RESTRICTION_HEADS, hid, {"active_id": str(row.id)})
            return prev, RestrictionRow.of(created)

        return await self.store.run_transaction(fn)

    async def save_restriction(self, user_id: uuid.UUID, row: Any) -> Any:
        """Persist attribute changes (optimistic lock). Ending the row frees its family head."""
        if row.user_id != user_id:
            raise ValueError("restriction user mismatch")
        hid = head_id(row.user_id, row.family)

        async def fn(tx: ScopedTransaction) -> Doc | None:
            head = await tx.get(RESTRICTION_HEADS, hid) if row.ended_at is not None else None
            saved = await save_row(tx, RESTRICTIONS, row)
            if head is not None and head.get("active_id") == str(row.id):
                await tx.put(RESTRICTION_HEADS, hid, {"active_id": None})
            return saved

        d = await self.store.run_transaction(fn)
        if d is not None:
            row.mark_saved(d.data)
        return row

    @platform_only(SYS)
    async def level_counts(self) -> dict[int, set[uuid.UUID]]:
        """Active restrictions: level -> distinct user ids (admin dashboard)."""
        out: dict[int, set[uuid.UUID]] = {}
        for d in await _all(self.store, RESTRICTIONS, filters=(("ended_at", "==", None),), order_by=()):
            out.setdefault(int(d["level"]), set()).add(uuid.UUID(d["user_id"]))
        return out

    # ------------------------------------------------------------------ user state

    async def get_state(self, user_id: uuid.UUID) -> Any | None:
        d = await self.store.get(STATE, str(user_id))
        return UserStateRow.of(d) if d else None

    async def ensure_state(self, user_id: uuid.UUID) -> Any:
        """``get_state`` that creates the zero row (Postgres ``get_state`` inserts it)."""
        from decimal import Decimal

        async def fn(tx: ScopedTransaction) -> Doc:
            cur = await tx.get(STATE, str(user_id))
            if cur is not None:
                return cur
            row = UserStateRow(
                user_id=user_id,
                sharing_score=Decimal("0.00"),
                takeover_score=Decimal("0.00"),
                sharing_level=0,
            )
            return await tx.create(STATE, row.doc(), doc_id=str(user_id))

        return UserStateRow.of(await self.store.run_transaction(fn))

    async def save_state(self, user_id: uuid.UUID, row: Any) -> Any:
        if row.user_id != user_id:
            raise ValueError("state user mismatch")

        async def fn(tx: ScopedTransaction) -> Doc | None:
            cur = await tx.get(STATE, str(user_id))
            return await save_row(tx, STATE, _with_id(row), current=cur)  # type: ignore[arg-type]

        d = await self.store.run_transaction(fn)
        if d is not None:
            row.mark_saved(d.data)
        return row

    # ------------------------------------------------------------------ cases / unblock (reads)

    @platform_only(SYS)
    async def case_ref(self, case_id: uuid.UUID) -> str | None:
        d = await self.store.get(CASES, str(case_id))
        return d.get("case_ref") if d else None

    @platform_only(SYS)
    async def open_case_count(self) -> int:
        return await self.store.count(CASES, filters=(("status", "not-in", ["decided", "closed"]),))

    async def unblock_requests_for_user(self, user_id: uuid.UUID) -> list[Any]:
        docs = await _all(self.store, UNBLOCK, user_id=user_id, order_by=())
        return [UnblockRow.of(d) for d in docs]

    @platform_only(SYS)
    async def get_unblock(self, request_id: uuid.UUID) -> Any | None:
        d = await self.store.get(UNBLOCK, str(request_id))
        return UnblockRow.of(d) if d else None

    @platform_only(SYS)
    async def get_case(self, case_id: uuid.UUID) -> Any | None:
        d = await self.store.get(CASES, str(case_id))
        return CaseRow.of(d) if d else None


class StatusReads(SecurityRepo):
    """Reads of the learner status page (SEC-01) -- system job, keyed by the caller's user id."""

    async def evaluation(self, user_id: uuid.UUID, evaluation_id: uuid.UUID) -> Any | None:
        from app.modules.security.store_specs import RiskEvaluationRow

        docs = await _all(
            self.store,
            "risk_evaluations",
            user_id=user_id,
            filters=(("id", "==", str(evaluation_id)),),
            order_by=(),
        )
        return RiskEvaluationRow.of(docs[0]) if docs else None

    async def latest_open_unblock(self, user_id: uuid.UUID) -> Any | None:
        docs = await _all(self.store, UNBLOCK, user_id=user_id, order_by=(("created_at", "desc"),))
        rows = [UnblockRow.of(d) for d in docs]
        live = [r for r in rows if r.state != "closed"]
        return live[0] if live else None

    async def ended_history(self, user_id: uuid.UUID, limit: int = 10) -> list[Any]:
        rows = [r for r in await self.restrictions_for_user(user_id) if r.ended_at is not None]
        rows.sort(key=lambda r: r.ended_at, reverse=True)
        return rows[:limit]


class _with_id:
    def __init__(self, row: Any) -> None:
        self._row = row

    def __getattr__(self, name: str) -> Any:
        if name == "id":
            return self._row.user_id
        return getattr(self._row, name)


def system_repo(job: str = "security.restrictions") -> SecurityRepo:
    # Writes join an open undo journal (detector scope, request journal): restriction rows, heads
    # and user state are restored automatically when the enclosing work fails.
    from app.modules.identity.fs_journal import JournalingStore

    return SecurityRepo(JournalingStore.system(job))


class IncidentRepo(FirestoreRepository):
    """Breach / incident register (SEC-40..42). ScopedStore(principal): the store re-checks
    security.incident.read (reads) and the shared write permission (writes)."""

    @platform_only("security.incident.read")
    async def list_incidents(self) -> list[Any]:
        from app.modules.security.store_specs import IncidentRow

        docs = await _all(self.store, "security_incidents", order_by=(("detected_at", "desc"),))
        return [IncidentRow.of(d) for d in docs]

    @platform_only("security.incident.read")
    async def get_incident(self, incident_id: uuid.UUID) -> Any | None:
        from app.modules.security.store_specs import IncidentRow

        d = await self.store.get("security_incidents", str(incident_id))
        return IncidentRow.of(d) if d else None

    @platform_only("security.incident.read")
    async def create_incident(self, row: Any) -> Any:
        from app.modules.security.store_specs import IncidentRow

        async def fn(tx: ScopedTransaction) -> Doc:
            await tx.reserve_unique(
                "incident_ref", row.incident_ref, owner=("security_incidents", str(row.id))
            )
            return await tx.create("security_incidents", row.doc(), doc_id=str(row.id))

        return IncidentRow.of(await self.store.run_transaction(fn))

    @platform_only("security.incident.read")
    async def save_incident(self, row: Any) -> Any:
        async def fn(tx: ScopedTransaction) -> Doc | None:
            return await save_row(tx, "security_incidents", row)

        d = await self.store.run_transaction(fn)
        if d is not None:
            row.mark_saved(d.data)
        return row


def incident_repo(principal: Any) -> IncidentRepo:
    return IncidentRepo(ScopedStore(principal))


class FindRepo(FirestoreRepository):
    """Generic single-collection reads for the security port (system job; the routes keep their
    permission checks). Equality / in / is None filters run in Firestore; ordering and
    limits are applied in memory so results equal the ORDER BY ... LIMIT of the SQL."""

    @platform_only(SYS)
    async def find(
        self,
        coll: str,
        row_cls: Any,
        *,
        filters: Any = (),
        order: tuple[str, bool] | None = None,
        limit: int | None = None,
    ) -> list[Any]:
        docs = await _all(self.store, coll, filters=filters, order_by=())
        rows = [row_cls.of(d) for d in docs]
        if order is not None:
            from app.core.firestore.collation import order_key

            key, desc = order
            # id order for ties, then the column: text in the VM collation, Postgres NULL placement
            rows.sort(key=lambda r: str(r.id))
            rows.sort(key=lambda r: order_key(getattr(r, key), desc=desc), reverse=desc)
        return rows[:limit] if limit is not None else rows


def find_repo(job: str = "security.read") -> FindRepo:
    return FindRepo(ScopedStore.system(job))
