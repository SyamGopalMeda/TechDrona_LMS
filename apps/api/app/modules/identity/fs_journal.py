"""Undo journal for Firestore writes: the "one Postgres transaction" guarantee for multi-step
actions that cannot run in a single Firestore transaction (dual-control execution).

``async with journal() as j:`` opens a scope. Every document written through a
``JournalingStore`` inside it (the access modules' repositories use one) records its
**before-image** (``None`` when the write created the document) once per document. If the block
raises, ``rollback()`` restores every touched document to its before-image in reverse order
(deleting documents that did not exist), then the error propagates. On success the journal is
simply dropped. Other modules can join the same scope: build their store with
``JournalingStore.system(job)``, or register a custom compensation with ``on_rollback(cb)``.

Before-images of documents written inside a transaction come from that transaction's reads
where the write used them (``update_read`` / ``delete_read`` / ``update`` / ``delete``); a
blind ``put`` reads the document just before (outside the transaction). Entries are only kept
for transaction attempts that committed.
"""

from __future__ import annotations

import contextvars
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

from app.core.firestore.store import Doc, ScopedStore

Undo = Callable[[], Awaitable[Any]]


@dataclass
class Journal:
    images: dict[tuple[str, str], dict[str, Any] | None] = field(default_factory=dict)
    order: list[tuple[str, str] | Undo] = field(default_factory=list)

    def record(self, collection: str, doc_id: str, before: dict[str, Any] | None) -> None:
        key = (collection, doc_id)
        if key not in self.images:  # the first image is the pre-scope state
            self.images[key] = dict(before) if before is not None else None
            self.order.append(key)

    async def rollback(self) -> int:
        store = ScopedStore.system("access.journal.rollback")
        n = 0
        for entry in reversed(self.order):
            if callable(entry):
                await entry()
                n += 1
                continue
            coll, doc_id = entry
            before = self.images[entry]

            async def fn(tx: Any, coll: str = coll, doc_id: str = doc_id, before: Any = before) -> None:
                if before is None:
                    tx.raw_delete(coll, doc_id)
                else:
                    tx.raw_set(coll, doc_id, before)

            await store.run_transaction(fn)
            n += 1
        self.images.clear()
        self.order.clear()
        return n


_current: contextvars.ContextVar[Journal | None] = contextvars.ContextVar("td_access_journal", default=None)


def current() -> Journal | None:
    return _current.get()


def on_rollback(cb: Undo) -> None:
    """Register a compensation for a write that does not go through a ``JournalingStore``."""
    j = _current.get()
    if j is not None:
        j.order.append(cb)


@asynccontextmanager
async def journal() -> AsyncIterator[Journal]:
    outer = _current.get()
    if outer is not None:  # nested: the outer scope decides
        yield outer
        return
    j = Journal()
    token = _current.set(j)
    reset = False
    try:
        yield j
    except BaseException:
        _current.reset(token)
        reset = True
        await j.rollback()
        raise
    finally:
        if not reset:
            _current.reset(token)


class _JournalTx:
    """Proxy of a ``ScopedTransaction`` that records before-images (per attempt)."""

    def __init__(
        self, tx: Any, seen: list[tuple[str, str, dict[str, Any] | None]], store: ScopedStore
    ) -> None:
        self._tx = tx
        self._seen = seen
        self._store = store

    def __getattr__(self, name: str) -> Any:
        return getattr(self._tx, name)

    async def create(self, collection: str, data: dict[str, Any], *, doc_id: str | None = None) -> Doc:
        d: Doc = await self._tx.create(collection, data, doc_id=doc_id)
        self._seen.append((collection, d.id, None))
        return d

    async def update(self, collection: str, doc_id: str, changes: dict[str, Any]) -> Doc:
        before = await self._tx.raw_get(collection, doc_id)
        d: Doc = await self._tx.update(collection, doc_id, changes)
        self._seen.append((collection, doc_id, before))
        return d

    async def update_read(self, collection: str, current: Doc, changes: dict[str, Any]) -> Doc:
        d: Doc = await self._tx.update_read(collection, current, changes)
        self._seen.append((collection, current.id, current.data))
        return d

    async def put(self, collection: str, doc_id: str, data: dict[str, Any]) -> Doc:
        snap = await self._store.ref(collection, doc_id).get()  # outside the transaction
        before = (snap.to_dict() or {}) if snap.exists else None
        d: Doc = await self._tx.put(collection, doc_id, data)
        self._seen.append((collection, doc_id, before))
        return d

    async def delete(self, collection: str, doc_id: str) -> None:
        before = await self._tx.raw_get(collection, doc_id)
        await self._tx.delete(collection, doc_id)
        self._seen.append((collection, doc_id, before))

    async def delete_read(self, collection: str, doc_id: str, current: dict[str, Any]) -> None:
        await self._tx.delete_read(collection, doc_id, current)
        self._seen.append((collection, doc_id, current))


class JournalingStore(ScopedStore):
    """``ScopedStore`` whose writes join the current ``journal()`` scope (no-op outside one)."""

    async def run_transaction(self, fn: Callable[[Any], Awaitable[Any]], *, max_attempts: int = 10) -> Any:
        j = _current.get()
        if j is None:
            return await super().run_transaction(fn, max_attempts=max_attempts)
        seen: list[tuple[str, str, dict[str, Any] | None]] = []

        async def wrapped(tx: Any) -> Any:
            seen.clear()  # a retried attempt starts over
            return await fn(_JournalTx(tx, seen, self))

        result = await super().run_transaction(wrapped, max_attempts=max_attempts)
        for coll, doc_id, before in seen:
            j.record(coll, doc_id, before)
        return result

    async def create(self, collection: str, data: dict[str, Any], *, doc_id: str | None = None) -> Doc:
        d = await super().create(collection, data, doc_id=doc_id)
        j = _current.get()
        if j is not None:
            j.record(collection, d.id, None)
        return d


async def request_journal() -> AsyncIterator[None]:
    """Router dependency (``dependencies=[Depends(request_journal, scope="function")]``): the
    whole request is one undo scope, so a route that writes several Firestore documents (e.g.
    deactivate: user status + sessions; break-glass: grant + sessions) leaves none of them
    behind when it fails, like its single Postgres transaction. Audit rows are buffered to the
    request commit point by ``core.audit`` and dropped on failure."""
    async with journal():
        yield


async def capture(collection: str, doc_id: str) -> None:
    """Record the current state of a document a store outside the access modules is about to
    write (before-image; ``None`` if it does not exist yet), so the open journal restores it on
    failure. No-op outside a journal scope."""
    j = _current.get()
    if j is None or (collection, doc_id) in j.images:
        return
    store = ScopedStore.system("access.journal.capture")
    snap = await store.ref(collection, doc_id).get()
    j.record(collection, doc_id, (snap.to_dict() or {}) if snap.exists else None)


def child() -> Any:
    """A nested undo scope: ``async with fs_journal.child():`` joins the current journal when
    one is open (its writes roll back with the outer scope), else opens its own. Public
    replacement for reading the private ``_current`` (kept working for existing callers)."""
    return journal()


@asynccontextmanager
async def savepoint() -> AsyncIterator[Journal]:
    """A nested undo scope with its own outcome, like a SQL savepoint: if the block raises, the
    writes made inside it are restored **at once** (even when the caller then catches the error
    and the outer scope goes on to succeed); on success its entries join the outer journal, so a
    later failure of the outer scope still undoes them. Without an outer scope it behaves like
    ``journal()``."""
    outer = _current.get()
    j = Journal()
    token = _current.set(j)
    try:
        yield j
    except BaseException:
        _current.reset(token)
        await j.rollback()
        raise
    _current.reset(token)
    if outer is not None:
        for entry in j.order:
            if callable(entry):
                outer.order.append(entry)
            else:
                outer.record(entry[0], entry[1], j.images[entry])
