"""Notifications public API for other modules (store-neutral: ``TD_STORE_NOTIFICATIONS``).

Other modules never touch ``notifications`` / ``notification_dedupe`` directly; they call these.
``notify`` writes the in-app row (Postgres, or Firestore with the dedupe document in the same
transaction) and sends email/SMS after commit; ``erase_user`` is the DPDP erasure hook.
"""

from __future__ import annotations

from typing import Any

from app.modules.notifications.adapters import (
    EmailAttachment,
    OutboundEmail,
    email_integrated,
    get_email_adapter,
    sms_integrated,
)
from app.modules.notifications.consumers import register_commerce_consumers
from app.modules.notifications.erasure import erase_user
from app.modules.notifications.service import notify, send_email, send_sms


def created_documents(user_id: Any, notification_id: Any, dedupe_key: str | None) -> list[tuple[str, str]]:
    """``(collection, document id)`` of the Firestore documents one ``notify`` created: the inbox
    row and, with a ``dedupe_key``, its dedupe marker. For a caller's undo journal (security
    ``detector_scope``), so no other module needs this module's collection names."""
    from app.modules.notifications.store_specs import DEDUPE, NOTIFICATIONS, dedupe_id

    out = [(NOTIFICATIONS, str(notification_id))]
    if dedupe_key:
        out.insert(0, (DEDUPE, dedupe_id(user_id, dedupe_key)))
    return out


async def delete_notification(
    session: Any, user_id: Any, notification_id: Any, dedupe_key: str | None = None
) -> None:
    """Undo one ``notify`` (inbox row + dedupe marker), on either store."""
    from app.core.firestore.backend import uses_firestore

    if uses_firestore("notifications"):
        from app.core.firestore.store import ScopedStore, ScopedTransaction

        refs = created_documents(user_id, notification_id, dedupe_key)

        async def body(tx: ScopedTransaction) -> None:
            for coll, did in refs:
                tx.raw_delete(coll, did)

        await ScopedStore.system("notifications.undo").run_transaction(body)
        return
    from sqlalchemy import delete

    from app.modules.notifications.models import Notification

    await session.execute(delete(Notification).where(Notification.id == notification_id))


__all__ = [
    "EmailAttachment",
    "OutboundEmail",
    "created_documents",
    "delete_notification",
    "email_integrated",
    "erase_user",
    "get_email_adapter",
    "notify",
    "register_commerce_consumers",
    "send_email",
    "send_sms",
    "sms_integrated",
]
