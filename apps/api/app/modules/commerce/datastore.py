"""Commerce persistence switch (``TD_STORE_COMMERCE=postgres|firestore``, default ``postgres``).

Every commerce statement goes through here instead of ``session.execute`` / ``add`` / ``flush`` /
``refresh`` / ``begin_nested``. On ``postgres`` each call reaches the session unchanged; on
``firestore`` statements over commerce tables run on the shared SQL-on-Firestore engine
(``app/core/firestore/sqlstore.py``; tables and rules in ``store_specs.SPEC``). Other modules
use ``app/modules/commerce/public.py``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select, text

from app.core.firestore.sqlstore import Savepoint, commit_all
from app.modules.commerce.store_specs import ORDER_SEQ, STORE

UOW_KEY = STORE.uow_key


def on_firestore() -> bool:
    return STORE.on_firestore()


def is_commerce_obj(obj: Any) -> bool:
    return STORE.owns(obj)


def uow(session: Any) -> Any:
    return STORE.uow(session)


async def scope(session: Any) -> Any:
    return await STORE.scope(session)


async def execute(session: Any, stmt: Any, params: Any = None) -> Any:
    return await STORE.execute(session, stmt, params)


def add(session: Any, obj: Any) -> None:
    STORE.add(session, obj)


async def flush(session: Any) -> None:
    await STORE.flush(session)


async def refresh(session: Any, obj: Any) -> None:
    await STORE.refresh(session, obj)


async def get(session: Any, model: type[Any], ident: Any) -> Any:
    return await STORE.get(session, model, ident)


async def begin_nested(session: Any) -> Savepoint:
    return await STORE.begin_nested(session)


async def commit_unit_of_work(session: Any) -> None:
    """Commit every SQL-on-Firestore unit of work of ``session`` (what ``before_commit`` does)."""
    await commit_all(session)


# --------------------------------------------------------------------------- sequences


async def next_order_number(session: Any, now: datetime) -> str:
    if on_firestore():
        n = await STORE.next_counter(session, ORDER_SEQ)
    else:
        n = (await session.execute(text("SELECT nextval('commerce_order_number_seq')"))).scalar_one()
    return f"TD-O-{now.year}-{int(n):08d}"


_SEQ_SQL = text(
    "INSERT INTO invoice_sequences (series, fiscal_year, next_value) VALUES (:s, :fy, 2) "
    "ON CONFLICT (series, fiscal_year) "
    "DO UPDATE SET next_value = invoice_sequences.next_value + 1 "
    "RETURNING next_value - 1"
)


async def allocate_invoice_value(session: Any, series: str, fy: str) -> int:
    """Gap-free next value per (series, fiscal year); committed with the invoice."""
    if not on_firestore():
        return int((await session.execute(_SEQ_SQL, {"s": series, "fy": fy})).scalar_one())
    from app.modules.commerce.models import InvoiceSequence

    seq = (
        await execute(
            session,
            select(InvoiceSequence)
            .where(InvoiceSequence.series == series, InvoiceSequence.fiscal_year == fy)
            .with_for_update(),
        )
    ).scalar_one_or_none()
    if seq is None:
        add(session, InvoiceSequence(series=series, fiscal_year=fy, next_value=2))
        return 1
    n = int(seq.next_value)
    seq.next_value = n + 1
    return n


async def before_side_effect(session: Any) -> None:
    """Call right before an external side effect (payment provider call that changes state,
    file store put, email). On Firestore every pending commerce/admissions write is checked as
    its commit would check it (versions, uniqueness, CHECKs), so a transaction that cannot
    commit never reaches the provider. On Postgres a no-op: the row locks already held give the
    same guarantee there."""
    if on_firestore():
        from app.core.firestore.sqlstore import precheck_all

        await precheck_all(session)


def _join_access_journal() -> None:
    from app.core.firestore.sqlstore import register_journal
    from app.modules.identity import fs_journal

    register_journal(fs_journal.current, fs_journal.on_rollback)


_join_access_journal()


def journaled_executor(job: str) -> Any:
    """Approval executors of commerce (billing approvals): all-or-nothing with the decision's
    undo journal on Firestore (``sqlstore.journaled_executor``)."""
    from app.core.firestore.sqlstore import journaled_executor as _je

    return _je(STORE, job)
