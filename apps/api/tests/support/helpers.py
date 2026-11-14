"""Backend-neutral direct data access for support tests (Postgres or the Firestore emulator,
following ``TD_STORE_SUPPORT``). Callers hold a system context on Postgres."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import func, select, update

from app.modules.support import service as sv
from app.modules.support.models import CorporateEnquiry, SupportTicket, SupportTicketMessage


def _fs() -> Any:
    from app.core.db import RlsScope
    from app.modules.support.repo_firestore import repo

    return repo(RlsScope("", True), "test.support")


def _id(v: Any) -> uuid.UUID:
    return v if isinstance(v, uuid.UUID) else uuid.UUID(str(v))


async def ticket(db: Any, tid: Any) -> Any:
    if sv.on_firestore():
        return await _fs().get_ticket(None, _id(tid))
    q = select(SupportTicket).where(SupportTicket.id == _id(tid)).execution_options(populate_existing=True)
    return (await db.execute(q)).scalar_one_or_none()


async def patch_ticket(db: Any, tid: Any, **values: Any) -> None:
    if sv.on_firestore():
        await _fs().patch_ticket(_id(tid), values)
        return
    await db.execute(update(SupportTicket).where(SupportTicket.id == _id(tid)).values(**values))


async def patch_messages(db: Any, tid: Any, **values: Any) -> None:
    if sv.on_firestore():
        await _fs().patch_messages(_id(tid), values)
        return
    await db.execute(
        update(SupportTicketMessage)
        .where(SupportTicketMessage.support_ticket_id == _id(tid))
        .values(**values)
    )


async def thread(db: Any, tid: Any) -> list[Any]:
    if sv.on_firestore():
        t = await _fs().get_ticket(None, _id(tid))
        return await _fs().thread(None, t, internal=True)
    q = (
        select(SupportTicketMessage)
        .where(SupportTicketMessage.support_ticket_id == _id(tid))
        .execution_options(populate_existing=True)
    )
    return list((await db.execute(q)).scalars())


async def enquiry_count(db: Any) -> int:
    if sv.on_firestore():
        return int(await _fs().count_enquiries())
    return int((await db.execute(select(func.count()).select_from(CorporateEnquiry))).scalar_one())


async def latest_enquiry(db: Any) -> Any:
    if sv.on_firestore():
        rows, _ = await _fs().enquiries(None, None, 1)
        return rows[0] if rows else None
    q = select(CorporateEnquiry).order_by(CorporateEnquiry.created_at.desc()).limit(1)
    return (await db.execute(q)).scalar_one_or_none()
