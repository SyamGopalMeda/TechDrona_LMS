"""Everything the security Firestore path needs from ``identity`` and ``sessions``, through their
store-neutral ``public.py`` (data-access agent). One file, so the coupling is visible and the
security repository never touches identity/sessions tables itself.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from app.modules.identity import public as idp
from app.modules.sessions import public as sp


async def user_contact_verified(session: Any, user_id: uuid.UUID) -> bool:
    """True when the user has a verified phone (step-up may then not use e-mail OTP)."""
    user = await idp.get_user(session, user_id)
    return bool(user is not None and user.phone_e164 and user.phone_verified_at)


async def password_set_at(session: Any, user_id: uuid.UUID) -> datetime | None:
    cred = await idp.get_credential(session, user_id)
    return cred.password_set_at if cred is not None else None


async def set_must_change_password(session: Any, user_id: uuid.UUID, value: bool) -> None:
    await idp.update_user(session, user_id, must_change_password=value)


async def set_restriction_cache(session: Any, user_id: uuid.UUID, level: int) -> None:
    """``users.restriction_level`` cache + the scope of the user's active sessions."""
    await idp.update_user(session, user_id, restriction_level=int(level))
    scope = "status_only" if level >= 4 else ("restricted" if level == 3 else "full")
    for s in await sp.list_sessions(session, user_id=user_id, status="active"):
        if s.scope != scope:
            await sp.update_session(session, s.id, scope=scope)


async def stepped_up_sessions_since(session: Any, user_id: uuid.UUID, since: datetime, amr: list[str]) -> int:
    """Active sessions created at/after ``since`` whose AMR overlaps ``amr``."""
    rows = await sp.list_sessions(session, user_id=user_id, status="active")
    want = set(amr)
    return sum(1 for s in rows if s.created_at >= since and want & set(s.amr or []))


async def clear_remembered_devices(session: Any, user_id: uuid.UUID) -> None:
    await sp.clear_remember_tokens(session, user_id)


async def non_deleted_user_ids(session: Any, user_ids: list[uuid.UUID]) -> set[uuid.UUID]:
    users = await idp.get_users(session, user_ids)
    return {uid for uid, u in users.items() if u.status != "deleted"}
