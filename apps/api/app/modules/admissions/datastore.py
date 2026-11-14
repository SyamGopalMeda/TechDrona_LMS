"""Admissions persistence switch (``TD_STORE_ADMISSIONS=postgres|firestore``, default ``postgres``).

Every admissions statement goes through here instead of ``session.execute`` / ``add`` /
``flush`` / ``refresh`` / ``get`` / ``begin_nested``. On ``postgres`` each call reaches the
session unchanged; on ``firestore`` statements over admissions tables run on the shared
SQL-on-Firestore engine (``app/core/firestore/sqlstore.py``; tables and rules in
``store_specs.SPEC``) and other modules' tables (users, batches, enrolments, entitlements) stay
on their own store.
"""

from __future__ import annotations

from typing import Any

from app.core.firestore.sqlstore import Savepoint
from app.modules.admissions.store_specs import STORE


def on_firestore() -> bool:
    return STORE.on_firestore()


async def execute(session: Any, stmt: Any, params: Any = None) -> Any:
    return await STORE.execute(session, stmt, params)


def add(session: Any, obj: Any) -> None:
    STORE.add(session, obj)


async def flush(session: Any) -> None:
    await STORE.flush(session)


async def refresh(session: Any, obj: Any) -> None:
    await STORE.refresh(session, obj)


async def get(session: Any, model: type[Any], ident: Any, *, with_for_update: bool = False) -> Any:
    return await STORE.get(session, model, ident, with_for_update=with_for_update)


async def begin_nested(session: Any) -> Savepoint:
    return await STORE.begin_nested(session)


async def constraints_immediate(session: Any) -> None:
    """Run the deferred checks now (the ledger trigger), before an external side effect.
    Postgres: ``SET CONSTRAINTS ALL IMMEDIATE`` (unchanged). Firestore: every pending unit of work
    is checked exactly as its commit would check it (``sqlstore.precheck_all``)."""
    from sqlalchemy import text

    await flush(session)
    if on_firestore():
        from app.core.firestore.sqlstore import precheck_all

        await precheck_all(session)
        return
    await session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))


async def before_side_effect(session: Any) -> None:
    """An external side effect follows (file store put, email): check pending writes first."""
    if on_firestore():
        from app.core.firestore.sqlstore import precheck_all

        await flush(session)
        await precheck_all(session)
