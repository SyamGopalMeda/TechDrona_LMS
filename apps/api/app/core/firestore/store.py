"""``ScopedStore``: the only door to Firestore (MIGRATION-PLAN §1.4, §1.8, §3.3).

The Admin SDK bypasses ``firestore.rules``, so this layer replaces Postgres RLS:

* A store is built for a ``Principal`` (``ScopedStore(principal)``) or for a named system job
  (``ScopedStore.system("audit.sealer")``) — there is no anonymous/unscoped store.
* Every read and write goes through the collection's ``CollectionSpec`` family (``owned`` /
  ``shared`` / ``system``). Invisible documents answer ``None`` / ``NotFoundError`` (no
  existence oracle, as with RLS); visible-but-forbidden writes raise ``StoreAccessDeniedError``.
* ``owned`` queries must name the ``user_id`` they read; reading another user's (or everyone's)
  rows needs the spec's ``read_permission`` (checked through ``app.core.auth.check_permission``).

Helpers: transactions (``run_transaction``, retry-safe: external I/O is forbidden inside the
callback, use ``tx.after_commit``), uniqueness reservations, gap-free counters, leases,
signed pagination cursors, ``created_at``/``updated_at``/``schema_version``/``expire_at`` stamping.
"""

from __future__ import annotations

import asyncio
import contextvars
import random
import uuid
from collections.abc import Awaitable, Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Literal, TypeVar

from google.api_core import exceptions as gexc
from google.cloud.firestore import AsyncClient, AsyncTransaction, FieldFilter, async_transactional

from app.core.auth import check_permission
from app.core.errors import ProblemError
from app.core.firestore import client as client_mod
from app.core.firestore import request_memo
from app.core.firestore.codec import decode_position_value, encode_position_value, to_store
from app.core.firestore.collections import (
    COUNTERS,
    LOCKS,
    UNIQUE_PREFIX,
    CollectionSpec,
    get_spec,
    physical_name,
)
from app.core.firestore.errors import (
    ExternalIOInTransactionError,
    NotFoundError,
    StoreAccessDeniedError,
    TransactionContentionError,
    TransactionTooLargeError,
    UniqueViolationError,
)
from app.core.firestore.ids import hashed_id, validate_id
from app.core.ids import uuid7
from app.core.pagination import DEFAULT_LIMIT, MAX_LIMIT, decode_cursor, encode_cursor
from app.core.principal import Principal
from app.core.time import utcnow

T = TypeVar("T")
Direction = Literal["asc", "desc"]
Op = Literal["==", "!=", "<", "<=", ">", ">=", "in", "not-in", "array-contains", "array-contains-any"]

# The Python client spells the array operators with underscores.
_LIB_OPS = {"array-contains": "array_contains", "array-contains-any": "array_contains_any"}
# Firestore's documented commit limit is 500 writes; stay well below it (MIGRATION-PLAN §2).
MAX_TX_WRITES = 400
# Firestore's ``in`` / ``array-contains-any`` filters take at most 30 values.
IN_LIMIT = 30
_BACKOFF_BASE_S = 0.02
_BACKOFF_CAP_S = 1.0
DOC_ID_FIELD = "__name__"
_RESERVED_FIELDS = frozenset({"created_at", "schema_version"})

_in_transaction: contextvars.ContextVar[bool] = contextvars.ContextVar("td_fs_in_tx", default=False)


def chunks[V](vals: Sequence[V], n: int = IN_LIMIT) -> Iterable[list[V]]:
    """Consecutive slices of ``vals`` (new lists) of at most ``n`` items: ``in`` filter batches."""
    for i in range(0, len(vals), n):
        yield list(vals[i : i + n])


def in_transaction() -> bool:
    return _in_transaction.get()


def forbid_in_transaction(what: str) -> None:
    """Call at the top of every external side effect (HTTP to a gateway, email, SMS, Celery send).

    Firestore re-runs a transaction callback on contention, so a side effect inside it can happen
    twice. Queue it with ``ScopedTransaction.after_commit`` or the outbox instead."""
    if _in_transaction.get():
        raise ExternalIOInTransactionError(f"{what} inside a Firestore transaction callback")


@dataclass(frozen=True, slots=True)
class SystemActor:
    job: str

    def __post_init__(self) -> None:
        if not self.job or not self.job.replace(".", "").replace("_", "").replace("-", "").isalnum():
            raise ValueError("system job names are dotted identifiers, e.g. 'audit.sealer'")


Actor = Principal | SystemActor


@dataclass(frozen=True, slots=True)
class Doc:
    id: str
    data: dict[str, Any]

    def __getitem__(self, key: str) -> Any:
        return self.data[key]

    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)


@dataclass(frozen=True, slots=True)
class Page:
    items: list[Doc]
    next_cursor: str | None
    limit: int

    @property
    def has_more(self) -> bool:
        return self.next_cursor is not None

    def meta(self) -> dict[str, Any]:
        """Same shape as ``app.core.pagination.page_meta``."""
        return {"next_cursor": self.next_cursor, "has_more": self.has_more, "limit": self.limit}


Filter = tuple[str, Op, Any]
Order = tuple[str, Direction]


class ScopedStore:
    def __init__(self, actor: Actor, *, client: AsyncClient | None = None) -> None:
        if not isinstance(actor, (Principal, SystemActor)):
            raise TypeError("ScopedStore needs a Principal or a SystemActor")
        self.actor = actor
        self._client = client
        self._perm_cache: dict[str, bool] = {}

    @classmethod
    def system(cls, job: str, *, client: AsyncClient | None = None) -> ScopedStore:
        return cls(SystemActor(job), client=client)

    @property
    def client(self) -> AsyncClient:
        # Never cache the process client here: its gRPC channel is bound to one event loop and
        # ``run_async`` closes it after every job, so a long-lived store (module-level system
        # stores, cached repositories) must always ask for the current one.
        if self._client is None:
            return client_mod.get_client()
        return self._client

    @property
    def is_system(self) -> bool:
        return isinstance(self.actor, SystemActor)

    @property
    def principal(self) -> Principal | None:
        return self.actor if isinstance(self.actor, Principal) else None

    # ------------------------------------------------------------------ authorization

    async def has_permission(self, permission: str | None) -> bool:
        if self.is_system:
            return True
        if permission is None or self.principal is None:
            return False
        if permission not in self._perm_cache:
            self._perm_cache[permission] = await check_permission(self.principal, permission)
        return self._perm_cache[permission]

    def _is_owner(self, spec: CollectionSpec, data: dict[str, Any]) -> bool:
        p = self.principal
        return p is not None and data.get(spec.owner_field) == str(p.user_id)

    async def can_read(self, spec: CollectionSpec, data: dict[str, Any]) -> bool:
        if self.is_system:
            return True
        if spec.family == "system":
            return False
        if spec.family == "owned":
            return self._is_owner(spec, data) or await self.has_permission(spec.read_permission)
        return spec.read_permission is None or await self.has_permission(spec.read_permission)

    async def can_write(self, spec: CollectionSpec, data: dict[str, Any]) -> bool:
        """``data`` is the document as it will be (create) or as it is (update/delete)."""
        if self.is_system:
            return True
        if spec.family == "system":
            return False
        if spec.family == "owned" and spec.owner_writes and self._is_owner(spec, data):
            return True
        return await self.has_permission(spec.write_permission)

    async def _require_read_scope(self, spec: CollectionSpec, user_id: uuid.UUID | str | None) -> None:
        """Query-level check: owned collections are read per user unless the caller is staff."""
        if self.is_system:
            return
        if spec.family == "system":
            raise StoreAccessDeniedError(f"{spec.name} is system-only")
        if spec.family == "owned":
            own = (
                self.principal is not None
                and user_id is not None
                and str(user_id) == str(self.principal.user_id)
            )
            if not own and not await self.has_permission(spec.read_permission):
                raise StoreAccessDeniedError(
                    f"reading {spec.name} for other users needs {spec.read_permission}"
                )
        elif spec.read_permission is not None and not await self.has_permission(spec.read_permission):
            raise StoreAccessDeniedError(f"reading {spec.name} needs {spec.read_permission}")

    # ------------------------------------------------------------------ helpers

    def ref(self, collection: str, doc_id: str) -> Any:
        return self.client.collection(physical_name(collection)).document(validate_id(doc_id))

    def _stamp_new(self, spec: CollectionSpec, data: dict[str, Any], now: datetime) -> dict[str, Any]:
        out = to_store(data)
        # An explicit insert time (``created_at=clock.now()``, as ORM inserts do) is kept.
        if not isinstance(out.get("created_at"), datetime):
            out["created_at"] = now
        out["updated_at"] = now
        out["schema_version"] = spec.schema_version
        if spec.ttl is not None and "expire_at" not in out:
            out["expire_at"] = now + spec.ttl
        return out

    def _stamp_changes(self, spec: CollectionSpec, changes: dict[str, Any], now: datetime) -> dict[str, Any]:
        if spec.append_only:
            raise StoreAccessDeniedError(f"{spec.name} is append-only")
        bad = _RESERVED_FIELDS & set(changes)
        if bad:
            raise ValueError(f"fields {sorted(bad)} are managed by the store")
        out = to_store(changes)
        out["updated_at"] = now
        return out

    async def _check_create(self, spec: CollectionSpec, data: dict[str, Any]) -> None:
        if spec.family == "owned" and not data.get(spec.owner_field):
            raise ValueError(f"{spec.name} documents need {spec.owner_field}")
        if not await self.can_write(spec, data):
            raise StoreAccessDeniedError(f"cannot create in {spec.name}")

    async def _check_update(
        self, spec: CollectionSpec, current: dict[str, Any], changes: dict[str, Any]
    ) -> None:
        if not await self.can_read(spec, current):
            raise NotFoundError(spec.name)
        if not await self.can_write(spec, current):
            raise StoreAccessDeniedError(f"cannot modify {spec.name}")
        if spec.family == "owned" and spec.owner_field in changes:
            new_owner = to_store(changes[spec.owner_field])
            if new_owner != current.get(spec.owner_field) and not await self.has_permission(
                spec.write_permission
            ):
                raise StoreAccessDeniedError(f"cannot re-assign {spec.name} ownership")

    async def _check_delete(self, spec: CollectionSpec, current: dict[str, Any]) -> None:
        if not await self.can_read(spec, current):
            raise NotFoundError(spec.name)
        if spec.append_only and not self.is_system:
            raise StoreAccessDeniedError(f"{spec.name} is append-only")
        if not await self.can_write(spec, current):
            raise StoreAccessDeniedError(f"no delete right on {spec.name}")

    # ------------------------------------------------------------------ single-document CRUD

    async def get(self, collection: str, doc_id: str) -> Doc | None:
        spec = get_spec(collection)
        phys = physical_name(collection)
        memo = not _in_transaction.get()
        data = request_memo.get_doc(phys, doc_id) if memo else request_memo.MISSING
        if data is request_memo.MISSING:
            snap = await self.ref(collection, doc_id).get()
            data = (snap.to_dict() or {}) if snap.exists else None
            if memo:
                request_memo.put_doc(phys, doc_id, data)
        if data is None:
            return None
        return Doc(doc_id, data) if await self.can_read(spec, data) else None

    async def get_many(self, collection: str, doc_ids: Iterable[str]) -> dict[str, Doc]:
        """Batched lookup (the "two-step join" replacement); invisible/missing ids are omitted."""
        spec = get_spec(collection)
        phys = physical_name(collection)
        memo = not _in_transaction.get()
        ids = list(dict.fromkeys(doc_ids))
        found: dict[str, dict[str, Any] | None] = {}
        if memo:
            for d in ids:
                hit = request_memo.get_doc(phys, d)
                if hit is not request_memo.MISSING:
                    found[d] = hit
        todo = [d for d in ids if d not in found]
        fetched: list[str] = []
        for i in range(0, len(todo), 100):
            refs = [self.ref(collection, d) for d in todo[i : i + 100]]
            async for snap in self.client.get_all(refs):
                data = (snap.to_dict() or {}) if snap.exists else None
                found[snap.id] = data
                fetched.append(snap.id)
                if memo:
                    request_memo.put_doc(phys, snap.id, data)
        out: dict[str, Doc] = {}
        # Same order as before: the documents fetched now in server order, memoised ones first.
        for d in [*(i for i in ids if i not in fetched), *fetched]:
            data = found.get(d)
            if data is not None and await self.can_read(spec, data):
                out[d] = Doc(d, data)
        return out

    async def create(self, collection: str, data: dict[str, Any], *, doc_id: str | None = None) -> Doc:
        """Insert; a deterministic ``doc_id`` that already exists raises ``UniqueViolationError``."""
        spec = get_spec(collection)
        doc_id = doc_id or str(uuid7())
        stored = self._stamp_new(spec, data, utcnow())
        await self._check_create(spec, stored)
        request_memo.forget(physical_name(collection), doc_id)
        try:
            await self.ref(collection, doc_id).create(stored)
        except gexc.AlreadyExists as e:
            raise UniqueViolationError(collection, doc_id) from e
        await _hint_direct(self.client, collection, stored, created=True)
        return Doc(doc_id, stored)

    async def update(self, collection: str, doc_id: str, changes: dict[str, Any]) -> Doc:
        return await self.run_transaction(lambda tx: tx.update(collection, doc_id, changes))

    async def delete(self, collection: str, doc_id: str) -> None:
        await self.run_transaction(lambda tx: tx.delete(collection, doc_id))

    # ------------------------------------------------------------------ queries

    def _build_query(
        self,
        spec: CollectionSpec,
        user_id: uuid.UUID | str | None,
        filters: Sequence[Filter],
        order_by: Sequence[Order],
    ) -> Any:
        q: Any = self.client.collection(physical_name(spec.name))
        if spec.family == "owned" and user_id is not None:
            q = q.where(filter=FieldFilter(spec.owner_field, "==", str(user_id)))
        for f, op, v in filters:
            if f == DOC_ID_FIELD:
                raise ValueError("filter on document id with get()/get_many() instead")
            q = q.where(filter=FieldFilter(f, _LIB_OPS.get(op, op), to_store(v)))
        for f, d in order_by:
            q = q.order_by(f, direction="DESCENDING" if d == "desc" else "ASCENDING")
        return q

    async def query(
        self,
        collection: str,
        *,
        user_id: uuid.UUID | str | None = None,
        filters: Sequence[Filter] = (),
        order_by: Sequence[Order] = (("created_at", "desc"),),
        limit: int = DEFAULT_LIMIT,
        cursor: str | None = None,
    ) -> Page:
        """Keyset pagination with a signed cursor; the document id breaks ties (stable order).

        ``owned`` collections: pass the ``user_id`` being read. ``user_id=None`` (all users) or
        another user's id needs the spec's ``read_permission``."""
        spec = get_spec(collection)
        await self._require_read_scope(spec, user_id)
        limit = max(1, min(int(limit), MAX_LIMIT))
        tie: Direction = order_by[-1][1] if order_by else "asc"
        orders = [*order_by, (DOC_ID_FIELD, tie)]
        q = self._build_query(spec, user_id, filters, order_by).order_by(
            DOC_ID_FIELD, direction="DESCENDING" if tie == "desc" else "ASCENDING"
        )
        shape = {"c": collection, "o": [f"{f}:{d}" for f, d in orders]}
        if cursor:
            pos = decode_cursor(cursor)
            if pos.get("s") != shape or not isinstance(pos.get("v"), list) or len(pos["v"]) != len(orders):
                raise ProblemError("invalid_cursor")
            q = q.start_after([decode_position_value(v) for v in pos["v"]])
        phys = physical_name(collection)
        memo = not _in_transaction.get()
        qkey = repr((None if user_id is None else str(user_id), list(filters), orders, limit, cursor))
        rows = request_memo.get_query(phys, qkey) if memo else request_memo.MISSING
        if rows is request_memo.MISSING:
            rows = [(s.id, s.to_dict() or {}) async for s in q.limit(limit + 1).stream()]
            if memo:
                request_memo.put_query(phys, qkey, rows)
                for row_id, row in rows:
                    request_memo.put_doc(phys, row_id, row)
        docs: list[Doc] = []
        for row_id, data in rows[:limit]:
            if await self.can_read(spec, data):  # defence in depth: the query scope already applies
                docs.append(Doc(row_id, data))
        next_cursor = None
        if len(rows) > limit:
            last_id, last_data = rows[limit - 1]
            values = [
                encode_position_value(last_id if f == DOC_ID_FIELD else last_data.get(f)) for f, _ in orders
            ]
            next_cursor = encode_cursor({"s": shape, "v": values})
        return Page(docs, next_cursor, limit)

    async def count(
        self, collection: str, *, user_id: uuid.UUID | str | None = None, filters: Sequence[Filter] = ()
    ) -> int:
        """Aggregation ``count()`` (billed ~1 read per 1,000 index entries)."""
        spec = get_spec(collection)
        await self._require_read_scope(spec, user_id)
        result = await self._build_query(spec, user_id, filters, ()).count().get()
        return int(result[0][0].value) if result and result[0] else 0

    # ------------------------------------------------------------------ bulk (system jobs only)

    async def scan(self, collection: str) -> list[Doc]:
        """Every document of a collection in id order (backfill verification, small collections)."""
        if not self.is_system:
            raise StoreAccessDeniedError("scan() is for named system jobs")
        get_spec(collection)
        q = self.client.collection(physical_name(collection)).order_by(DOC_ID_FIELD)
        return [Doc(s.id, s.to_dict() or {}) async for s in q.stream()]

    async def import_documents(
        self, collection: str, docs: Sequence[tuple[str, dict[str, Any]]], *, chunk: int = MAX_TX_WRITES
    ) -> int:
        """Write documents verbatim (``set``, timestamps kept) in batches: backfill/reseed only.

        Not transactional across chunks; re-running is idempotent (same ids, same data)."""
        if not self.is_system:
            raise StoreAccessDeniedError("import_documents() is for named system jobs")
        get_spec(collection)
        n = 0
        request_memo.forget(physical_name(collection))
        for i in range(0, len(docs), chunk):
            batch = self.client.batch()
            for doc_id, data in docs[i : i + chunk]:
                batch.set(self.ref(collection, doc_id), to_store(data))
                n += 1
            await batch.commit()
        await _hint_direct(self.client, collection, None, created=True)
        return n

    async def delete_all(self, collection: str) -> int:
        """Delete every document of a collection (reseed / rollback of a backfill)."""
        if not self.is_system:
            raise StoreAccessDeniedError("delete_all() is for named system jobs")
        get_spec(collection)
        request_memo.forget(physical_name(collection))
        ids = [s.id async for s in self.client.collection(physical_name(collection)).select([]).stream()]
        for i in range(0, len(ids), MAX_TX_WRITES):
            batch = self.client.batch()
            for doc_id in ids[i : i + MAX_TX_WRITES]:
                batch.delete(self.ref(collection, doc_id))
            await batch.commit()
        await _hint_direct(self.client, collection, None, created=False)
        return len(ids)

    # ------------------------------------------------------------------ transactions

    async def run_transaction(
        self, fn: Callable[[ScopedTransaction], Awaitable[T]], *, max_attempts: int = 10
    ) -> T:
        """Run ``fn`` in a Firestore transaction (retried on contention — keep it pure).

        Reads must come before writes. External I/O inside ``fn`` raises
        ``ExternalIOInTransactionError`` (via ``forbid_in_transaction``); register it with
        ``tx.after_commit(cb)`` — callbacks run once, after a successful commit, in order."""
        if _in_transaction.get():
            raise RuntimeError("nested Firestore transactions are not supported; pass the tx along")
        holder: list[ScopedTransaction] = []

        @async_transactional
        async def _body(raw: AsyncTransaction) -> T:
            stx = ScopedTransaction(self, raw)
            holder[:] = [stx]
            token = _in_transaction.set(True)
            try:
                out = await fn(stx)
                if stx.notes is not None:  # scheduler work hint in the same commit
                    from app.core import jobhints

                    jobhints.before_commit(stx)
                return out
            finally:
                _in_transaction.reset(token)

        # Our own retry loop (one library attempt each) adds jittered exponential backoff: the
        # library retries ABORTED immediately, which livelocks hot documents (seen on the emulator
        # with 8 concurrent counter increments). Backoff sleeps happen outside the callback.
        attempt = 0
        while True:
            attempt += 1
            try:
                result = await _body(self.client.transaction(max_attempts=1))
                break
            except gexc.AlreadyExists as e:
                raise UniqueViolationError(*_split_conflict(e)) from e
            except (ValueError, gexc.GoogleAPICallError) as e:
                # Retryable: a commit ABORTED (the library wraps it in ValueError), or an ABORTED /
                # "Transaction lock timeout" raised raw by a read inside the callback (the emulator
                # does this under contention; production returns ABORTED the same way).
                if not _is_contention(e):
                    raise
                if attempt >= max_attempts:
                    raise TransactionContentionError(
                        f"transaction aborted {attempt} times (contention); retry later"
                    ) from e
                await asyncio.sleep(min(_BACKOFF_CAP_S, _BACKOFF_BASE_S * 2**attempt) * random.random())  # noqa: S311
        for cb in holder[0]._after_commit if holder else ():
            await cb()
        if holder and holder[0].notes is not None:
            from app.core import jobhints

            await jobhints.after_commit(holder[0])
        return result

    # ------------------------------------------------ leases (advisory-lock / SKIP LOCKED replacement)

    async def claim_lease(self, key: str, holder: str, ttl: timedelta) -> bool:
        """Claim ``locks/{key}`` for ``holder`` until now+ttl. True if claimed (or renewed)."""

        async def _claim(tx: ScopedTransaction) -> bool:
            snap = await tx.raw_get(LOCKS, key)
            now = utcnow()
            if (
                snap is not None
                and snap.get("holder") != holder
                and snap.get("expire_at")
                and snap["expire_at"] > now
            ):
                return False
            tx.raw_set(LOCKS, key, {"holder": holder, "expire_at": now + ttl, "updated_at": now})
            return True

        claimed = await self.run_transaction(_claim)
        if claimed:  # serialised from here on: re-read everything (request_memo docstring)
            request_memo.clear()
        return claimed

    async def release_lease(self, key: str, holder: str) -> bool:
        async def _release(tx: ScopedTransaction) -> bool:
            snap = await tx.raw_get(LOCKS, key)
            if snap is None or snap.get("holder") != holder:
                return False
            tx.raw_delete(LOCKS, key)
            return True

        return await self.run_transaction(_release)


def _hints_active() -> bool:
    from app.core import jobhints

    return jobhints.active()


async def _hint_direct(client: AsyncClient, collection: str, data: Any, *, created: bool) -> None:
    """Scheduler work hint + kicks for a write outside a transaction (event mode only)."""
    if not _hints_active():
        return
    from app.core import jobhints

    notes = jobhints.TxNotes()
    jobhints.note(notes, collection, data, created=created)
    await jobhints.after_direct_write(client, notes)


def _is_contention(e: BaseException) -> bool:
    if isinstance(e, gexc.Aborted) or isinstance(e.__cause__, gexc.Aborted):
        return True
    return isinstance(e, gexc.GoogleAPICallError) and "lock timeout" in str(e).lower()


def _split_conflict(e: gexc.AlreadyExists) -> tuple[str, str]:
    msg = str(e)
    marker = "/documents/"
    if marker in msg:
        path = msg.split(marker, 1)[1].split()[0].strip("'\".,")
        coll, _, doc_id = path.rpartition("/")
        return coll or "?", doc_id or "?"
    return "?", "?"


@dataclass
class ScopedTransaction:
    """Principal-scoped view of one Firestore transaction attempt."""

    store: ScopedStore
    raw: AsyncTransaction
    writes: int = 0
    _after_commit: list[Callable[[], Awaitable[Any]]] = field(default_factory=list)
    notes: Any = None  # app.core.jobhints.TxNotes (scheduler work hints, event mode only)

    def _staged(self, collection: str, doc_id: str, data: Any = None, *, created: bool = False) -> None:
        """Count one write and forget the document in the request read memo."""
        self._count()
        request_memo.forget(physical_name(collection), doc_id)
        if self.notes is not None or _hints_active():
            from app.core import jobhints

            if self.notes is None:
                self.notes = jobhints.TxNotes()
            jobhints.note(self.notes, collection, data, created=created)

    def _count(self, n: int = 1) -> None:
        self.writes += n
        if self.writes > MAX_TX_WRITES:
            raise TransactionTooLargeError(
                f"more than {MAX_TX_WRITES} writes in one transaction; chunk the job"
            )

    def after_commit(self, cb: Callable[[], Awaitable[Any]]) -> None:
        self._after_commit.append(cb)

    async def raw_get(self, collection: str, doc_id: str) -> dict[str, Any] | None:
        """Internal (store helpers only): unauthorised read of a store-internal document."""
        # AsyncTransaction.get(ref) awaits an async generator (google-cloud-firestore 2.34 bug),
        # so read through client.get_all bound to this transaction instead.
        ref = self.store.ref(collection, doc_id)
        snaps = [s async for s in self.store.client.get_all([ref], transaction=self.raw)]
        if not snaps or not snaps[0].exists:
            return None
        return snaps[0].to_dict() or {}

    def raw_set(self, collection: str, doc_id: str, data: dict[str, Any]) -> None:
        self._staged(collection, doc_id, data)
        self.raw.set(self.store.ref(collection, doc_id), to_store(data))

    def raw_create(self, collection: str, doc_id: str, data: dict[str, Any]) -> None:
        self._staged(collection, doc_id, data, created=True)
        self.raw.create(self.store.ref(collection, doc_id), to_store(data))

    def raw_delete(self, collection: str, doc_id: str) -> None:
        self._staged(collection, doc_id)
        self.raw.delete(self.store.ref(collection, doc_id))

    # ---------------------------------------------------------------- scoped reads/writes

    async def get(self, collection: str, doc_id: str) -> Doc | None:
        spec = get_spec(collection)
        data = await self.raw_get(collection, doc_id)
        if data is None or not await self.store.can_read(spec, data):
            return None
        return Doc(doc_id, data)

    async def create(self, collection: str, data: dict[str, Any], *, doc_id: str | None = None) -> Doc:
        """Transactional insert; an existing ``doc_id`` fails the commit with ``UniqueViolationError``."""
        spec = get_spec(collection)
        doc_id = doc_id or str(uuid7())
        stored = self.store._stamp_new(spec, data, utcnow())
        await self.store._check_create(spec, stored)
        self._staged(collection, doc_id, stored, created=True)
        self.raw.create(self.store.ref(collection, doc_id), stored)
        return Doc(doc_id, stored)

    async def update(self, collection: str, doc_id: str, changes: dict[str, Any]) -> Doc:
        spec = get_spec(collection)
        current = await self.raw_get(collection, doc_id)
        if current is None:
            raise NotFoundError(collection)
        await self.store._check_update(spec, current, changes)
        stamped = self.store._stamp_changes(spec, changes, utcnow())
        self._staged(collection, doc_id, {**current, **stamped})
        self.raw.update(self.store.ref(collection, doc_id), stamped)
        return Doc(doc_id, {**current, **stamped})

    async def update_read(self, collection: str, current: Doc, changes: dict[str, Any]) -> Doc:
        """``update`` of a document already read in this transaction (no second read), so several
        documents can be read first and then written (Firestore: all reads before writes)."""
        spec = get_spec(collection)
        await self.store._check_update(spec, current.data, changes)
        stamped = self.store._stamp_changes(spec, changes, utcnow())
        self._staged(collection, current.id, {**current.data, **stamped})
        self.raw.update(self.store.ref(collection, current.id), stamped)
        return Doc(current.id, {**current.data, **stamped})

    async def put(self, collection: str, doc_id: str, data: dict[str, Any]) -> Doc:
        """Blind upsert (no read, so it may follow other writes in the callback).

        For ``shared``/``system`` collections only: an ``owned`` document's current owner cannot
        be checked without a read, so use ``update`` there. ``created_at`` is kept when ``data``
        carries it (a document read earlier in the same transaction)."""
        spec = get_spec(collection)
        if spec.family == "owned":
            raise StoreAccessDeniedError(f"put() is not allowed on owned collection {spec.name}")
        if spec.append_only:
            raise StoreAccessDeniedError(f"{spec.name} is append-only")
        if not await self.store.can_write(spec, data):
            raise StoreAccessDeniedError(f"cannot write {spec.name}")
        now = utcnow()
        stored = to_store(data)
        stored.setdefault("created_at", now)
        stored["updated_at"] = now
        stored["schema_version"] = spec.schema_version
        self._staged(collection, doc_id, stored)
        self.raw.set(self.store.ref(collection, doc_id), stored)
        return Doc(doc_id, stored)

    async def delete(self, collection: str, doc_id: str) -> None:
        spec = get_spec(collection)
        current = await self.raw_get(collection, doc_id)
        if current is None:
            raise NotFoundError(collection)
        await self.store._check_delete(spec, current)
        self._staged(collection, doc_id)
        self.raw.delete(self.store.ref(collection, doc_id))

    async def delete_read(self, collection: str, doc_id: str, current: dict[str, Any]) -> None:
        """Delete a document read earlier in this callback (``current`` is what was read).

        No second read, so it may follow other writes (Firestore: all reads before writes)."""
        spec = get_spec(collection)
        await self.store._check_delete(spec, current)
        self._staged(collection, doc_id)
        self.raw.delete(self.store.ref(collection, doc_id))

    async def get_many(self, collection: str, doc_ids: Iterable[str]) -> dict[str, Doc]:
        """Transactional batched lookup (100 per round trip); invisible/missing ids are omitted."""
        spec = get_spec(collection)
        ids = list(dict.fromkeys(doc_ids))
        out: dict[str, Doc] = {}
        for i in range(0, len(ids), 100):
            refs = [self.store.ref(collection, d) for d in ids[i : i + 100]]
            async for snap in self.store.client.get_all(refs, transaction=self.raw):
                if snap.exists:
                    data = snap.to_dict() or {}
                    if await self.store.can_read(spec, data):
                        out[snap.id] = Doc(snap.id, data)
        return out

    async def query(self, collection: str, *, filters: Sequence[Filter] = ()) -> list[Doc]:
        """Transactional query (every match, unordered) on a ``shared``/``system`` collection.

        A read: call it before this callback's writes. Keep the result set small (it is read in
        one go and every matched document joins the transaction's read set)."""
        spec = get_spec(collection)
        if spec.family == "owned":
            raise StoreAccessDeniedError("transactional queries are for shared/system collections")
        await self.store._require_read_scope(spec, None)
        q = self.store._build_query(spec, None, filters, ())
        out: list[Doc] = []
        async for s in q.stream(transaction=self.raw):
            data = s.to_dict() or {}
            if await self.store.can_read(spec, data):
                out.append(Doc(s.id, data))
        return out

    # ---------------------------------------------------------------- uniqueness & sequences

    async def reserve_unique(
        self, namespace: str, value: str, *, owner: tuple[str, str], normalize: bool = True
    ) -> str:
        """Reserve ``uniq_{namespace}/{sha256(value)}`` for ``owner=(collection, doc_id)``.

        Raises ``UniqueViolationError`` if another owner holds it; re-reserving for the same owner
        is a no-op. Read-before-write: call it before this transaction's writes."""
        validate_id(namespace)
        coll, key = f"{UNIQUE_PREFIX}{namespace}", hashed_id(namespace, value, normalize=normalize)
        existing = await self.raw_get(coll, key)
        holder = {"collection": owner[0], "doc_id": owner[1]}
        if existing is not None:
            if {"collection": existing.get("collection"), "doc_id": existing.get("doc_id")} == holder:
                return key
            raise UniqueViolationError(coll, key)
        self.raw_create(coll, key, {**holder, "created_at": utcnow()})
        return key

    async def release_unique(
        self, namespace: str, value: str, *, owner: tuple[str, str], normalize: bool = True
    ) -> bool:
        coll, key = f"{UNIQUE_PREFIX}{namespace}", hashed_id(namespace, value, normalize=normalize)
        existing = await self.raw_get(coll, key)
        if existing is None or (existing.get("collection"), existing.get("doc_id")) != owner:
            return False
        self.raw_delete(coll, key)
        return True

    async def next_sequence(self, name: str, *, collection: str = COUNTERS) -> int:
        """Gap-free counter ``counters/{name}`` (first value 1): the number commits with the row.

        ``collection``: a module's own registered counter collection instead of the shared
        ``counters``, so the backfill can seed it from a Postgres sequence and verify it per module."""
        if collection != COUNTERS:
            get_spec(collection)
        current = await self.raw_get(collection, name)
        value = int((current or {}).get("value", 0)) + 1
        self.raw_set(collection, name, {"value": value, "updated_at": utcnow()})
        return value
