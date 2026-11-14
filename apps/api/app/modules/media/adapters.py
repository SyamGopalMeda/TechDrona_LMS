"""Reads and writes of other modules' tables that media needs (identity, sessions, security).

Identity, sessions and security (INV-12 unblock-request attachment scans) are reached through
their ``public.py``; media touches no foreign table itself.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession


async def watermark_contact(session: AsyncSession, user_id: uuid.UUID) -> tuple[Any, Any, Any]:
    """``(email, phone_e164, full_name)`` of a user (``None``s when missing), via identity."""
    from app.modules.identity import public as identity

    c = (await identity.user_cards(session, [user_id])).get(user_id)
    return (c.email, c.phone_e164, c.full_name) if c else (None, None, None)


async def device_families(session: AsyncSession, device_id: uuid.UUID) -> tuple[Any, Any] | None:
    """``(ua_family, os_family)`` of a device, ``None`` when unknown, via sessions."""
    from app.modules.sessions import public as sessions

    d = await sessions.get_device(session, device_id)
    return (d.ua_family, d.os_family) if d else None


# --------------------------------------------------------------------------- security (INV-12)


async def set_unblock_attachment_scan(session: AsyncSession, s3_key: str, result: str) -> int:
    """Set ``scan_status`` of the pending unblock-request attachment under ``s3_key`` (security)."""
    from app.modules.security import public as security

    return await security.set_unblock_attachment_scan(session, s3_key, result)


async def pending_unblock_attachment_keys(session: AsyncSession, limit: int) -> list[str]:
    from app.modules.security import public as security

    return list(await security.pending_unblock_attachment_keys(session, limit))
