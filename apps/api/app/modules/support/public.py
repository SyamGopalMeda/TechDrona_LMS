"""Support public API for other modules (store-neutral: ``TD_STORE_SUPPORT``).

The only cross-module read of support tables is the admin dashboard's ticket counts.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.support.service import dashboard_counts, on_firestore


async def detach_security_refs(
    session: AsyncSession, case_ids: Iterable[uuid.UUID], request_ids: Iterable[uuid.UUID]
) -> int:
    """Security retention (``maint.purge_closed_cases``): tickets outlive purged security cases,
    so their ``related_case_id`` / ``related_unblock_request_id`` are set to NULL. Returns the
    number of tickets changed. Postgres: two UPDATEs; Firestore: the tickets collection."""
    cases, reqs = set(case_ids), set(request_ids)
    if not cases and not reqs:
        return 0
    if on_firestore():
        from app.core.firestore.store import ScopedStore
        from app.modules.support import store_specs  # noqa: F401  (registers the collections)

        st = ScopedStore.system("support.retention")
        n = 0
        for field, ids in (("related_case_id", cases), ("related_unblock_request_id", reqs)):
            vals = [str(x) for x in ids]
            for i in range(0, len(vals), 30):
                page = await st.query(
                    "support_tickets", filters=[(field, "in", vals[i : i + 30])], order_by=(), limit=500
                )
                for d in page.items:
                    await st.update("support_tickets", d.id, {field: None})
                    n += 1
        return n
    from sqlalchemy import update

    from app.modules.support.models import SupportTicket

    a = await session.execute(
        update(SupportTicket).where(SupportTicket.related_case_id.in_(cases)).values(related_case_id=None)
    )
    b = await session.execute(
        update(SupportTicket)
        .where(SupportTicket.related_unblock_request_id.in_(reqs))
        .values(related_unblock_request_id=None)
    )
    return int(getattr(a, "rowcount", 0) or 0) + int(getattr(b, "rowcount", 0) or 0)


__all__ = ["dashboard_counts", "detach_security_refs"]
