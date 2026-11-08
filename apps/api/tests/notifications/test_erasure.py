"""DB-01: the notifications erasure provider deletes the learner's inbox rows (idempotent)."""

from __future__ import annotations

from sqlalchemy import func, select

from app.core.db import system_context
from app.modules.notifications.erasure import erase_user
from app.modules.notifications.models import Notification
from app.modules.notifications.service import notify
from tests.identity.factory import make_user


async def test_db01_notifications_erasure_deletes_user_rows_only(db) -> None:
    u = await make_user(db)
    other = await make_user(db)
    await system_context(db, "test.erasure")
    for uid in (u.id, u.id, other.id):
        await notify(db, uid, "learning.reminder", category="learning", data={"x": 1})

    assert await erase_user(db, u.id) == {"notifications_deleted": 2}
    assert await erase_user(db, u.id) == {"notifications_deleted": 0}
    left = (await db.execute(select(func.count()).where(Notification.user_id == other.id))).scalar_one()
    assert left == 1
