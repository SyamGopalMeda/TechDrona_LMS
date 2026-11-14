"""Notifications erasure provider (DB-01). Inbox rows hold message data addressed to the
learner and have no legal-hold basis, so they are deleted. Idempotent."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.notifications.models import Notification


def _count(res: object) -> int:
    return int(getattr(res, "rowcount", 0) or 0)


async def erase_user(session: AsyncSession, user_id: uuid.UUID) -> dict[str, Any]:
    from app.core.firestore.backend import uses_firestore

    if uses_firestore("notifications"):
        from app.modules.notifications.repo_firestore import system_repo

        return {"notifications_deleted": await system_repo("notifications.erasure").erase_user(user_id)}
    n = _count(await session.execute(delete(Notification).where(Notification.user_id == user_id)))
    await session.flush()
    return {"notifications_deleted": n or 0}
