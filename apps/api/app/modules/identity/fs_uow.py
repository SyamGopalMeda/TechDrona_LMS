"""Request unit of work for the access modules on Firestore (identity, sessions, rbac, orgs).

Postgres routes load ORM rows, mutate attributes and rely on the request transaction's commit.
On Firestore the repositories hand out transient objects, so this module reproduces the same
"mutate, then commit at the end of the request" contract without rewriting every route:

* While a unit of work is open (the ``unit_of_work`` router dependency, or ``async with
  open_uow():`` in jobs), every object built by ``fs_codec.doc_obj`` is **tracked** with a
  snapshot of its document.
* ``add(session, obj)`` replaces ``session.add(obj)``: on Firestore the object is queued as an
  insert; on Postgres it is added to the session as before.
* At the end of a **successful** request (or ``await flush(session)``) every tracked object whose
  document differs from its snapshot is written: only the **changed fields**, merged into the
  current stored document through the module's saver (so uniqueness lookups and the
  "ended session stays ended" rule still apply). New objects are inserted. An exception
  discards everything not yet flushed, like a Postgres rollback.

Writes the repositories already performed atomically (OTP checks, token claims, grants, ...)
are not repeated: their objects carry a snapshot taken after the write.
"""

from __future__ import annotations

import contextvars
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

from app.core.firestore.backend import uses_firestore
from app.modules.identity import fs_codec

Saver = Callable[[Any], Awaitable[Any]]
Loader = Callable[[Any], Awaitable[Any]]


@dataclass(frozen=True)
class SaverSpec:
    module: str
    load: Loader  # obj -> current stored object (or None)
    save: Saver  # full object -> persisted
    insert: Saver  # new object -> persisted


_SAVERS: dict[type, SaverSpec] = {}


def register_saver(model: type, spec: SaverSpec) -> None:
    _SAVERS[model] = spec


def _spec(model: type) -> SaverSpec | None:
    if not _SAVERS:
        _load_savers()
    return _SAVERS.get(model)


def _load_savers() -> None:
    import importlib

    for m in ("identity", "sessions", "rbac", "orgs"):
        importlib.import_module(f"app.modules.{m}.uow_savers")


def on_firestore(obj_or_model: Any) -> bool:
    model = obj_or_model if isinstance(obj_or_model, type) else type(obj_or_model)
    spec = _spec(model)
    return spec is not None and uses_firestore(spec.module)


@dataclass
class UnitOfWork:
    tracked: dict[int, tuple[Any, dict[str, Any] | None]] = field(default_factory=dict)
    suspended: int = 0

    def track(self, obj: Any) -> None:
        if self.suspended or _spec(type(obj)) is None:
            return
        from app.core.firestore.store import in_transaction

        if in_transaction():
            # built inside a repository transaction: an internal working copy that the
            # repository writes itself; tracking it would write a stale copy back later
            return
        self.tracked[id(obj)] = (obj, fs_codec.obj_doc(obj))

    def add(self, obj: Any) -> None:
        self.tracked[id(obj)] = (obj, None)

    def clean(self, obj: Any) -> None:
        if id(obj) in self.tracked:
            self.tracked[id(obj)] = (obj, fs_codec.obj_doc(obj))

    async def flush(self) -> int:
        n = 0
        # flush until stable (savers may load objects; those are untracked)
        self.suspended += 1
        try:
            for key, (obj, snap) in list(self.tracked.items()):
                spec = _spec(type(obj))
                if spec is None or not uses_firestore(spec.module):
                    continue
                doc = fs_codec.obj_doc(obj)
                if snap is None:
                    await spec.insert(obj)
                    n += 1
                else:
                    changed = {k for k, v in doc.items() if snap.get(k) != v}
                    if not changed:
                        continue
                    current = await spec.load(obj)
                    if current is None:
                        await spec.insert(obj)
                    else:
                        for k in changed:
                            setattr(current, k, getattr(obj, k))
                        await spec.save(current)
                    n += 1
                self.tracked[key] = (obj, fs_codec.obj_doc(obj))
        finally:
            self.suspended -= 1
        return n


_current: contextvars.ContextVar[UnitOfWork | None] = contextvars.ContextVar("td_access_uow", default=None)


def current() -> UnitOfWork | None:
    return _current.get()


def _on_load(obj: Any) -> None:
    uow = _current.get()
    if uow is not None:
        uow.track(obj)


fs_codec.set_load_hook(_on_load)


@asynccontextmanager
async def open_uow() -> AsyncIterator[UnitOfWork]:
    """Open a unit of work; flushed when the block exits normally, discarded on error."""
    outer = _current.get()
    if outer is not None:  # nested: join the outer unit of work
        yield outer
        return
    uow = UnitOfWork()
    token = _current.set(uow)
    try:
        yield uow
        await uow.flush()
    finally:
        _current.reset(token)


async def unit_of_work() -> AsyncIterator[None]:
    """Router dependency (``dependencies=[Depends(unit_of_work, scope="function")]``)."""
    async with open_uow():
        yield


def add(session: Any, obj: Any) -> None:
    """``session.add(obj)`` for an access-module row on either store."""
    if on_firestore(obj):
        uow = _current.get()
        if uow is None:
            raise RuntimeError("fs_uow.add outside a unit of work: use 'async with open_uow()'")
        uow.add(obj)
        return
    session.add(obj)


async def flush(session: Any, *objs: Any) -> None:
    """``session.flush()``: writes pending Firestore changes (all, or only ``objs``) and flushes
    the Postgres session when there is one."""
    uow = _current.get()
    if uow is not None:
        if objs:
            sub = UnitOfWork(tracked={id(o): uow.tracked[id(o)] for o in objs if id(o) in uow.tracked})
            await sub.flush()
            for o in objs:
                if id(o) in sub.tracked:
                    uow.tracked[id(o)] = sub.tracked[id(o)]
        else:
            await uow.flush()
    if session:
        await session.flush()


def discard(obj: Any) -> None:
    """Forget an object (e.g. one deleted through a repository call)."""
    uow = _current.get()
    if uow is not None:
        uow.tracked.pop(id(obj), None)
