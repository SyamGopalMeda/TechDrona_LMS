"""Assessments persistence switch (``TD_STORE_ASSESSMENTS=postgres|firestore``, default ``postgres``).

Every assessments statement goes through here instead of ``session.execute`` / ``add`` / ``get`` /
``flush`` / ``refresh`` / ``delete`` / ``begin_nested``. On ``postgres`` each call reaches the
session unchanged (byte-for-byte the previous behaviour); on ``firestore`` statements over
assessments tables run on the shared SQL-on-Firestore engine (``store_specs.STORE``) and commit with
the request. Statements over other modules' tables must go through those modules' public APIs.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from app.core.firestore.sqlstore import Savepoint
from app.modules.assessments.store_specs import STORE


def on_firestore() -> bool:
    return STORE.on_firestore()


async def execute(session: Any, stmt: Any, params: Any = None) -> Any:
    return await STORE.execute(session, stmt, params)


def add(session: Any, obj: Any) -> None:
    STORE.add(session, obj)


def add_all(session: Any, objs: Any) -> None:
    for o in objs:
        STORE.add(session, o)


async def flush(session: Any) -> None:
    await STORE.flush(session)


async def refresh(session: Any, obj: Any, attribute_names: Any = None) -> None:
    if not on_firestore() and attribute_names is not None:
        await session.refresh(obj, attribute_names)
        return
    await STORE.refresh(session, obj)


async def get(session: Any, model: type[Any], ident: Any, **kw: Any) -> Any:
    if on_firestore() and getattr(model, "__tablename__", None) not in STORE.spec.TABLES:
        return await _foreign_get(session, model, ident)
    if on_firestore() and isinstance(ident, tuple):
        # Composite primary key (attempt_sections, attempt_item_grades): the engine's ``get``
        # compares only the first key column, so select on every column instead.
        from sqlalchemy import select

        cols = list(model.__table__.primary_key.columns)
        q = select(model).where(*[c == v for c, v in zip(cols, ident, strict=True)])
        if kw.get("with_for_update"):
            q = q.with_for_update()
        return (await STORE.execute(session, q)).scalar_one_or_none()
    return await STORE.get(session, model, ident, with_for_update=bool(kw.get("with_for_update")))


async def _foreign_get(session: Any, model: type[Any], ident: Any) -> Any:
    """``session.get`` of another module's row: that module's public API (no Postgres)."""
    table = getattr(model, "__tablename__", "")
    name = f"{model.__name__} ({table})"
    if table in {"questions", "question_versions", "companies", "topics"}:
        from app.modules.placement import public as placement_public

        fn = {
            "Question": placement_public.get_question,
            "QuestionVersion": placement_public.get_version,
            "Company": placement_public.get_company,
            "Topic": placement_public.get_topic,
        }[model.__name__]
        return await fn(session, ident)
    if table == "auth_sessions":
        from app.modules.sessions import public as sessions_public

        return await sessions_public.get_session(session, ident)
    if table == "code_submissions":
        # system view: every caller checks attempt and user ownership itself (as the Postgres
        # path does after ``session.get``); coding's request-scoped view needs its own session
        from app.modules.coding import repo_firestore as coding_repo

        return await (await coding_repo.repo(None)).get_submission(ident)
    if table == "users":
        from app.modules.identity import public as identity_public

        return await identity_public.get_user(session, ident)
    raise LookupError(f"assessments: no public lookup for {name}")


async def delete(session: Any, obj: Any) -> None:
    await STORE.delete(session, obj)


async def begin_nested(session: Any) -> Savepoint:
    return await STORE.begin_nested(session)


@asynccontextmanager
async def nested(session: Any) -> AsyncIterator[Savepoint]:
    """``async with session.begin_nested():`` replacement (rolls the unit of work back too)."""
    sp = await STORE.begin_nested(session)
    async with sp:
        yield sp


async def commit(session: Any) -> None:
    """Commit the unit of work now (jobs that commit in the middle; tests)."""
    from app.core.firestore.sqlstore import commit_all

    await commit_all(session)


def written_as_system(session: Any, obj: Any) -> None:
    """The row was changed inside ``system_context`` (Postgres: the UPDATE ran under platform
    RLS). The engine checks writes at commit with the scope the row was *read* with, so record
    that this change was made with platform scope."""
    if not on_firestore():
        return
    from app.core.firestore.sqlstore import Scope

    e = STORE.uow(session).entry_of(obj)
    if e is not None:
        e.scope = Scope.platform()
