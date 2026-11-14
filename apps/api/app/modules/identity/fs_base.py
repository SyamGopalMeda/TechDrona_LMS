"""Shared helpers for the access-module Firestore repositories (identity, sessions, rbac, orgs)."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, TypeVar

from app.core.firestore.repository import FirestoreRepository
from app.core.firestore.store import Doc, Filter, Order, ScopedTransaction
from app.core.time import utcnow
from app.modules.identity.fs_codec import doc_obj, obj_doc, with_defaults

M = TypeVar("M")

_STORE_MANAGED = ("created_at", "schema_version", "updated_at", "expire_at")


def write_changes(data: dict[str, Any], *, keep_created: bool = False) -> dict[str, Any]:
    """A full document minus the fields the store stamps itself (for ``update``)."""
    skip = _STORE_MANAGED[1:] if keep_created else _STORE_MANAGED
    return {k: v for k, v in data.items() if k not in skip}


class AccessRepo(FirestoreRepository):
    """Small helpers on top of ``ScopedStore``; subclasses add the module's queries."""

    async def _all(
        self,
        collection: str,
        *,
        filters: Sequence[Filter] = (),
        order_by: Sequence[Order] = (),
        user_id: Any = None,
    ) -> list[Doc]:
        """Every matching document (pages of 200 under the hood)."""
        out: list[Doc] = []
        cursor: str | None = None
        while True:
            page = await self.store.query(
                collection, user_id=user_id, filters=filters, order_by=order_by, limit=200, cursor=cursor
            )
            out += page.items
            if not page.next_cursor:
                return out
            cursor = page.next_cursor

    async def _objs(self, model: type[M], collection: str, **kw: Any) -> list[M]:
        return [doc_obj(model, d.data) for d in await self._all(collection, **kw)]

    async def _get_obj(self, model: type[M], collection: str, doc_id: str) -> M | None:
        d = await self.store.get(collection, doc_id)
        return doc_obj(model, d.data) if d else None

    @staticmethod
    def new_doc(obj: Any) -> dict[str, Any]:
        """Document for an INSERT of ``obj`` (server defaults applied, as Postgres would)."""
        return with_defaults(type(obj), obj_doc(obj), utcnow())

    @staticmethod
    async def _tx_upsert(
        tx: ScopedTransaction, collection: str, doc_id: str, obj: Any, current: Doc | None
    ) -> Doc:
        """Insert or overwrite ``obj`` (``current`` = what this transaction read for ``doc_id``)."""
        if current is None:
            return await tx.create(collection, AccessRepo.new_doc(obj), doc_id=doc_id)
        return await tx.update_read(collection, current, write_changes(obj_doc(obj)))

    async def _upsert(self, collection: str, doc_id: str, obj: Any) -> Any:
        """Save ``obj`` (insert or full overwrite) and return it as stored (a new transient object)."""

        async def fn(tx: ScopedTransaction) -> Doc:
            cur = await tx.get(collection, doc_id)
            return await self._tx_upsert(tx, collection, doc_id, obj, cur)

        d = await self.store.run_transaction(fn)
        return doc_obj(type(obj), d.data)
