"""Notification service: in-app rows + direct email/SMS delivery through adapters.

Security messages carrying secrets (OTP codes, verification/reset links) are sent with
``send_email``/``send_sms`` only: their content is never stored in ``notifications.data``.
Delivery happens inline (best effort) until the ``worker-notifications`` consumer exists.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from typing import Any

import structlog
from sqlalchemy import update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ids import uuid7
from app.modules.notifications.adapters import OutboundEmail, OutboundSms, get_email_adapter, get_sms_adapter
from app.modules.notifications.models import Notification

log = structlog.get_logger("app.notifications")

CATEGORIES = frozenset({"security", "transactional", "learning", "marketing", "system"})


async def send_email(
    to: str, subject: str, text: str, *, template_key: str, category: str = "security"
) -> bool:
    try:
        await get_email_adapter().send(OutboundEmail(to, subject, text, category, template_key))
        return True
    except Exception as e:  # delivery is best effort; never fail the business transaction
        log.warning("email_delivery_failed", template=template_key, error=type(e).__name__)
        return False


async def send_sms(to: str, text: str, *, template_key: str) -> bool:
    try:
        await get_sms_adapter().send(OutboundSms(to, text, template_key))
        return True
    except Exception as e:
        log.warning("sms_delivery_failed", template=template_key, error=type(e).__name__)
        return False


async def notify(
    session: AsyncSession,
    user_id: uuid.UUID,
    template_key: str,
    *,
    category: str,
    data: dict[str, Any] | None = None,
    channels: Iterable[str] = ("in_app",),
    organization_id: uuid.UUID | None = None,
    priority: str = "normal",
    dedupe_key: str | None = None,
    is_minor: bool = False,
    email_to: str | None = None,
    email_subject: str | None = None,
    email_text: str | None = None,
) -> uuid.UUID | None:
    """Create an inbox/delivery row and deliver email if requested. Marketing is suppressed
    for minors. Returns the notification id (None when suppressed or deduplicated)."""
    if category not in CATEGORIES:
        raise ValueError(f"unknown category {category!r}")
    chans = list(dict.fromkeys(channels))
    if category == "marketing" and is_minor:
        return None
    nid = uuid7()
    row = (
        await session.execute(
            pg_insert(Notification)
            .values(
                id=nid,
                user_id=user_id,
                organization_id=organization_id,
                template_key=template_key,
                template_version=1,
                category=category,
                channels=chans,
                data=data or {},
                priority=priority,
                status="queued",
                dedupe_key=dedupe_key,
            )
            .on_conflict_do_nothing()
            .returning(Notification.id)
        )
    ).scalar_one_or_none()
    if row is None:
        return None
    delivery: dict[str, Any] = {}
    if "in_app" in chans:
        delivery["in_app"] = {"status": "delivered"}
    if "email" in chans and email_to:
        ok = await send_email(
            email_to,
            email_subject or template_key,
            email_text or "",
            template_key=template_key,
            category=category,
        )
        delivery["email"] = {"status": "sent" if ok else "failed"}
    statuses = {v["status"] for v in delivery.values()}
    status = (
        "sent"
        if statuses <= {"delivered", "sent"}
        else ("failed" if statuses == {"failed"} else "partially_sent")
    )
    await session.execute(
        update(Notification).where(Notification.id == nid).values(delivery=delivery, status=status)
    )
    return nid
