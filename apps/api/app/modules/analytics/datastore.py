"""Persistence switch of ``export_jobs`` (``TD_STORE_ANALYTICS``): every statement of
``exports.py`` goes through here. Postgres: the session, unchanged. Firestore: the shared
SQL-on-Firestore engine (``store_specs.EXPORT_STORE``) interprets the same statements."""

from __future__ import annotations

from typing import Any

from app.modules.analytics.store_specs import EXPORT_STORE


async def execute(session: Any, stmt: Any, params: Any = None) -> Any:
    return await EXPORT_STORE.execute(session, stmt, params)


def add(session: Any, obj: Any) -> None:
    EXPORT_STORE.add(session, obj)


async def flush(session: Any) -> None:
    await EXPORT_STORE.flush(session)


async def refresh(session: Any, obj: Any) -> None:
    await EXPORT_STORE.refresh(session, obj)


async def get(session: Any, model: type[Any], ident: Any) -> Any:
    return await EXPORT_STORE.get(session, model, ident)


async def begin_nested(session: Any) -> Any:
    return await EXPORT_STORE.begin_nested(session)
