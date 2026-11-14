"""Reads/writes of other modules' tables that assessments makes, for the Firestore store.

On ``TD_STORE_ASSESSMENTS=postgres`` the callers keep their original SQL (this module is not
used). On ``firestore`` the request "session" is a ``MemoryTx`` (no Postgres), so these go through
the owning modules' public APIs instead of joining their tables.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from app.core.principal import Principal


async def member_of_batch(session: Any, user_id: uuid.UUID, batch_id: uuid.UUID) -> bool:
    from app.modules.orgs import public as orgs_public

    return await orgs_public.is_batch_member(session, batch_id, user_id)


async def device_owner_verified(session: Any, principal: Principal) -> bool:
    from app.modules.sessions import public as sessions_public

    rows = await sessions_public.list_user_devices(
        session, user_id=principal.user_id, device_id=principal.device_id, not_removed=True
    )
    return any(r.owner_verified_at is not None for r in rows)


async def auth_session(session: Any, session_id: uuid.UUID | None) -> Any:
    if session_id is None:
        return None
    from app.modules.sessions import public as sessions_public

    return await sessions_public.get_session(session, session_id)


async def hold_auth_session(session: Any, session_id: uuid.UUID, until: datetime) -> None:
    from app.modules.sessions import public as sessions_public

    await sessions_public.update_session(session, session_id, idle_hold_until=until)


async def lock(key: str) -> None:
    """``pg_advisory_xact_lock`` replacement: a lease held until the request ends."""
    from app.core.request_locks import acquire

    await acquire(key)


async def version_settings(session: Any, qv_ids: list[uuid.UUID]) -> dict[uuid.UUID, dict[str, Any]]:
    from app.modules.placement import bank

    return {k: dict(b.version.settings or {}) for k, b in (await bank.load_bundles(session, qv_ids)).items()}


async def version_topics(session: Any, qv_ids: list[uuid.UUID]) -> dict[uuid.UUID, Any]:
    """version id -> the ``QuestionVersion`` (difficulty, ...) for reports."""
    from app.modules.placement import bank

    return {k: b.version for k, b in (await bank.load_bundles(session, qv_ids)).items()}
