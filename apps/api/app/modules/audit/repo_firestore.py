"""Firestore audit store (``TD_STORE_AUDIT=firestore``; MIGRATION-PLAN §3.5).

* ``enqueue(tx, actor, action, ...)`` -- the Firestore twin of ``app.core.audit.audit()``: writes
  ``audit_outbox/{uuid7}`` inside the caller's Firestore transaction (an audit record exists iff
  the business write committed). Same record fields, same validation.
* ``AuditFsRepo`` -- the read API (list / get / whole-chain read) and the sealer step.

Sealing on Firestore: a lease ``locks/audit_sealer`` replaces ``pg_try_advisory_xact_lock``
(single writer). One transaction per batch reads ``audit_meta/head`` and the outbox batch, writes
``audit_log/{seq:012d}`` rows chained with the unchanged ``chain.compute_row_hash``, deletes the
outbox documents and moves the head -- so ``seq`` is gap-free and nothing is sealed twice.

Immutability: Firestore has no trigger or per-collection grant, so the repository exposes no
update/delete of ``audit_log`` (the specs are append-only and the store refuses updates); the hash
chain (``verify_chain``) detects any out-of-band edit.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from app.core.audit import ACTION_RE, AuditActor, _jsonable, _s
from app.core.firestore.repository import FirestoreRepository, platform_only
from app.core.firestore.store import ScopedStore, ScopedTransaction
from app.core.ids import uuid7
from app.core.principal import Principal
from app.core.request_context import get_request_id
from app.core.time import utcnow
from app.modules.audit.chain import GENESIS_HASH, ChainVerification, compute_row_hash, verify_rows
from app.modules.audit.store_specs import (
    HEAD,
    LOG,
    META,
    OUTBOX,
    READ_PERM,
    RECORD_FIELDS,
    UUID_FIELDS,
    dump_json,
    load_json,
    log_doc,
    log_id,
)

SEALER_JOB = "audit.sealer"
SEALER_LEASE = "audit_sealer"
SEALER_LEASE_TTL = timedelta(seconds=60)
# 2 writes per row (log create + outbox delete) + the head, under the store's 400-write cap.
MAX_SEAL_BATCH = 199
_SCAN_PAGE = 100


# --------------------------------------------------------------------------- writers


def build_record(
    actor: Principal | AuditActor,
    action: str,
    target_type: str,
    target_id: uuid.UUID | None = None,
    *,
    organization_id: uuid.UUID | None = None,
    subject_user_id: uuid.UUID | None = None,
    reason_code: str | None = None,
    reason: str | None = None,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    ip: str | None = None,
    request_id: str | None = None,
) -> dict[str, Any]:
    """The ``audit_outbox.record`` payload, field for field as ``app.core.audit.audit()``."""
    if not ACTION_RE.match(action):
        raise ValueError(f"invalid audit action {action!r}")
    a = AuditActor.from_principal(actor) if isinstance(actor, Principal) else actor
    return {
        "actor_type": a.actor_type,
        "actor_user_id": _s(a.user_id),
        "actor_session_id": _s(a.session_id),
        "actor_roles": list(a.roles) or ([f"system:{a.system_job}"] if a.system_job else []),
        "action": action,
        "target_type": target_type,
        "target_id": _s(target_id),
        "organization_id": _s(organization_id),
        "subject_user_id": _s(subject_user_id),
        "reason_code": reason_code,
        "reason": reason,
        "before_state": _jsonable(before),
        "after_state": _jsonable(after),
        "request_id": request_id or get_request_id(),
        "ip": ip,
    }


def outbox_doc(audit_id: uuid.UUID, record: dict[str, Any], occurred_at: datetime) -> dict[str, Any]:
    return {
        "id": str(audit_id),
        "occurred_at": occurred_at,
        "record_json": json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=False),
        "created_at": occurred_at,
        "schema_version": 1,
    }


async def enqueue(
    tx: ScopedTransaction, actor: Principal | AuditActor, action: str, target_type: str, *args: Any, **kw: Any
) -> uuid.UUID:
    """Record a privileged action inside a Firestore transaction (pure: retry-safe).

    The outbox is system-only, so the document is written with the transaction's raw create (the
    equivalent of ``td_app``'s INSERT-only grant on ``audit_outbox``): any principal's business
    transaction can append a record, nobody but the sealer can read or delete one."""
    record = build_record(actor, action, target_type, *args, **kw)
    audit_id = uuid7()
    tx.raw_create(OUTBOX, str(audit_id), outbox_doc(audit_id, record, utcnow()))
    return audit_id


async def enqueue_now(
    actor: Principal | AuditActor, action: str, target_type: str, *args: Any, **kw: Any
) -> uuid.UUID:
    """Outside a transaction (a write that is itself a single document): own one-write transaction."""
    store = ScopedStore.system("audit.writer")

    async def fn(tx: ScopedTransaction) -> uuid.UUID:
        return await enqueue(tx, actor, action, target_type, *args, **kw)

    return await store.run_transaction(fn)


# --------------------------------------------------------------------------- rows


def _uuid(v: Any) -> uuid.UUID | None:
    return None if v is None else uuid.UUID(str(v))


@dataclass
class AuditRow:
    """Same attribute names and Python types as the ``AuditLog`` ORM row (shared serializers)."""

    seq: int
    occurred_at: datetime
    id: uuid.UUID
    actor_type: str
    actor_user_id: uuid.UUID | None
    actor_session_id: uuid.UUID | None
    actor_roles: list[str]
    action: str
    target_type: str
    target_id: uuid.UUID | None
    organization_id: uuid.UUID | None
    subject_user_id: uuid.UUID | None
    reason_code: str | None
    reason: str | None
    before_state: Any
    after_state: Any
    request_id: str | None
    ip: str | None
    prev_hash: bytes
    row_hash: bytes

    @classmethod
    def of(cls, d: Mapping[str, Any]) -> AuditRow:
        return cls(
            seq=int(d["seq"]),
            occurred_at=d["occurred_at"],
            id=uuid.UUID(d["id"]),
            actor_type=d["actor_type"],
            actor_user_id=_uuid(d.get("actor_user_id")),
            actor_session_id=_uuid(d.get("actor_session_id")),
            actor_roles=list(d.get("actor_roles") or []),
            action=d["action"],
            target_type=d["target_type"],
            target_id=_uuid(d.get("target_id")),
            organization_id=_uuid(d.get("organization_id")),
            subject_user_id=_uuid(d.get("subject_user_id")),
            reason_code=d.get("reason_code"),
            reason=d.get("reason"),
            before_state=load_json(d.get("before_state_json")),
            after_state=load_json(d.get("after_state_json")),
            request_id=d.get("request_id"),
            ip=d.get("ip"),
            prev_hash=bytes.fromhex(d["prev_hash"]),
            row_hash=bytes.fromhex(d["row_hash"]),
        )

    def chain_dict(self) -> dict[str, Any]:
        """The dict ``chain.verify_rows`` hashes (``occurred_at`` as stored, microsecond exact)."""
        return {k: getattr(self, k) for k in self.__dataclass_fields__}


def sealed_row(
    seq: int, prev: bytes, audit_id: Any, occurred_at: datetime, record: Mapping[str, Any]
) -> dict[str, Any]:
    """Outbox record -> chained ``audit_log`` row dict (identical to ``sealer.seal_pending``)."""
    row: dict[str, Any] = {f: record.get(f) for f in RECORD_FIELDS}
    row["actor_roles"] = list(row["actor_roles"] or [])
    for f in UUID_FIELDS:
        if f != "id" and row[f] is not None:
            row[f] = uuid.UUID(str(row[f]))
    row.update(seq=seq, occurred_at=occurred_at, id=uuid.UUID(str(audit_id)))
    row_hash = compute_row_hash(prev, row)
    row.update(prev_hash=prev, row_hash=row_hash)
    return row


# --------------------------------------------------------------------------- repository

RowFilter = Callable[[AuditRow], bool]


class AuditFsRepo(FirestoreRepository):
    """Read side for ``ScopedStore(principal)`` (the store re-checks ``audit.read``); chain and
    sealer methods for named system jobs."""

    @platform_only(READ_PERM)
    async def list_events(
        self,
        *,
        equals: Mapping[str, Any],
        before_seq: int | None,
        limit: int,
        keep: RowFilter | None = None,
    ) -> tuple[list[AuditRow], bool]:
        """Newest first (``seq desc``), ``limit`` rows + whether more exist.

        Equality filters run in Firestore (composite ``(field, seq desc)`` indexes); ``keep``
        (time window, event family) is applied in memory while paging, so the result equals the
        Postgres ``WHERE ... ORDER BY seq DESC LIMIT n+1``."""
        filters: list[Any] = [(k, "==", str(v)) for k, v in equals.items() if v is not None]
        if before_seq is not None:
            filters.append(("seq", "<", int(before_seq)))
        out: list[AuditRow] = []
        cursor: str | None = None
        while len(out) <= limit:
            page = await self.store.query(
                LOG, filters=filters, order_by=(("seq", "desc"),), limit=_SCAN_PAGE, cursor=cursor
            )
            for d in page.items:
                row = AuditRow.of(d.data)
                if keep is None or keep(row):
                    out.append(row)
                    if len(out) > limit:
                        break
            if not page.next_cursor:
                break
            cursor = page.next_cursor
        return out[:limit], len(out) > limit

    @platform_only(READ_PERM)
    async def get_event(self, seq: int) -> AuditRow | None:
        if seq < 0:
            return None
        d = await self.store.get(LOG, log_id(seq))
        return AuditRow.of(d.data) if d else None

    @platform_only(READ_PERM)
    async def chain_rows(self, from_seq: int = 1) -> list[dict[str, Any]]:
        """Every row from ``from_seq`` in ``seq`` order (a full read: O(log size) reads)."""
        out: list[dict[str, Any]] = []
        cursor: str | None = None
        while True:
            page = await self.store.query(
                LOG,
                filters=(("seq", ">=", from_seq),),
                order_by=(("seq", "asc"),),
                limit=_SCAN_PAGE,
                cursor=cursor,
            )
            out += [AuditRow.of(d.data).chain_dict() for d in page.items]
            if not page.next_cursor:
                return out
            cursor = page.next_cursor

    @platform_only(READ_PERM)
    async def verify_chain(self, from_seq: int = 1) -> ChainVerification:
        expected_prev = GENESIS_HASH
        if from_seq > 1:
            prev = await self.store.get(LOG, log_id(from_seq - 1))
            if prev is None:
                return ChainVerification(False, 0, None, None, from_seq - 1, "anchor row missing")
            expected_prev = bytes.fromhex(prev["row_hash"])
        rows = await self.chain_rows(from_seq)
        return verify_rows(rows, expected_prev_hash=expected_prev, expected_first_seq=from_seq)

    # ------------------------------------------------------------------ sealer (system job)

    @platform_only("audit.seal")
    async def head(self) -> tuple[int, bytes]:
        d = await self.store.get(META, HEAD)
        if d is None:
            return 0, GENESIS_HASH
        return int(d["seq"]), bytes.fromhex(d["row_hash"])

    @platform_only("audit.seal")
    async def pending_ids(self, batch: int) -> list[str]:
        """Oldest outbox documents first: ``(occurred_at, id)`` as the Postgres sealer."""
        page = await self.store.query(
            OUTBOX, order_by=(("occurred_at", "asc"),), limit=max(1, min(batch, MAX_SEAL_BATCH))
        )
        return [d.id for d in page.items]

    @platform_only("audit.seal")
    async def append(
        self,
        records: list[tuple[Any, datetime, Mapping[str, Any]]] | None = None,
        *,
        outbox_ids: list[str] | None = None,
        pg_batch_ids: list[str] | None = None,
    ) -> int:
        """One chain transaction. Appends ``records`` (``(id, occurred_at, record)`` from the
        Postgres outbox) and/or the Firestore outbox documents ``outbox_ids`` (deleted in the same
        commit). ``pg_batch_ids``: ids of the Postgres batch, remembered on the head so a batch
        whose Postgres delete failed after this commit is skipped, not sealed twice."""
        records = records or []
        outbox_ids = outbox_ids or []
        if len(records) + 2 * len(outbox_ids) + 1 > 400:
            raise ValueError("audit seal batch too large for one transaction")

        async def fn(tx: ScopedTransaction) -> int:
            head = await tx.get(META, HEAD)
            pending = await tx.get_many(OUTBOX, outbox_ids) if outbox_ids else {}
            seq = int(head["seq"]) if head else 0
            prev = bytes.fromhex(head["row_hash"]) if head else GENESIS_HASH
            already = set((head.get("last_pg_ids") if head else None) or [])
            items: list[tuple[Any, datetime, Mapping[str, Any]]] = [
                r for r in records if str(r[0]) not in already
            ]
            for oid in outbox_ids:  # caller's order: (occurred_at, id)
                d = pending.get(oid)
                if d is not None:
                    items.append((d["id"], d["occurred_at"], json.loads(d["record_json"])))
            for audit_id, occurred_at, record in items:
                seq += 1
                row = sealed_row(seq, prev, audit_id, occurred_at, record)
                await tx.create(LOG, log_doc(row), doc_id=log_id(seq))
                prev = row["row_hash"]
            for oid, d in pending.items():
                await tx.delete_read(OUTBOX, oid, d.data)
            if items or pg_batch_ids is not None:
                new_head: dict[str, Any] = {"seq": seq, "row_hash": prev.hex()}
                new_head["last_pg_ids"] = list(pg_batch_ids) if pg_batch_ids is not None else list(already)
                await tx.put(META, HEAD, new_head)
            return len(items)

        return await self.store.run_transaction(fn)

    @platform_only("audit.seal")
    async def seal_pending(self, batch: int = MAX_SEAL_BATCH) -> int:
        """Drain one batch of the Firestore outbox into the Firestore chain (single writer)."""
        if not await self.pending_ids(1):  # nothing to seal: skip the lease (2 writes) entirely
            return 0
        holder = str(uuid7())
        if not await self.store.claim_lease(SEALER_LEASE, holder, SEALER_LEASE_TTL):
            return 0
        try:
            ids = await self.pending_ids(batch)
            return await self.append(outbox_ids=ids) if ids else 0
        finally:
            await self.store.release_lease(SEALER_LEASE, holder)

    @platform_only("audit.seal")
    async def pending_outbox(self, batch: int) -> list[tuple[str, datetime, dict[str, Any]]]:
        """Oldest Firestore outbox records (for sealing into the Postgres chain)."""
        ids = await self.pending_ids(batch)
        docs = await self.store.get_many(OUTBOX, ids)
        return [(i, docs[i]["occurred_at"], json.loads(docs[i]["record_json"])) for i in ids if i in docs]

    @platform_only("audit.seal")
    async def delete_outbox(self, ids: list[str]) -> int:
        """Remove Firestore outbox documents already sealed into the Postgres chain."""

        async def fn(tx: ScopedTransaction) -> int:
            docs = await tx.get_many(OUTBOX, ids)
            for oid, d in docs.items():
                await tx.delete_read(OUTBOX, oid, d.data)
            return len(docs)

        return await self.store.run_transaction(fn) if ids else 0


def sealer_repo() -> AuditFsRepo:
    return AuditFsRepo(ScopedStore.system(SEALER_JOB))


def reader_repo(principal: Principal) -> AuditFsRepo:
    return AuditFsRepo(ScopedStore(principal))


def chain_repo() -> AuditFsRepo:
    """Whole-chain verification (route already checked ``audit.read``): a named system read,
    as the Postgres ``verify_chain`` reads every row regardless of the caller's row filter."""
    return AuditFsRepo(ScopedStore.system("audit.verify"))


__all__ = [
    "AuditFsRepo",
    "AuditRow",
    "build_record",
    "chain_repo",
    "dump_json",
    "enqueue",
    "enqueue_now",
    "reader_repo",
    "sealer_repo",
]
