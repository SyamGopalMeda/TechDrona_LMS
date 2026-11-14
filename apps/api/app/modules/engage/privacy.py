"""DB-01: engage erasure provider. Registered when the engage router is imported.

* ``engage_participants``: display name cleared (the row stays so counts/rankings of past runs
  remain consistent; it is labelled ``Participant #<seq>`` afterwards).
* ``engage_responses``: free-text and word answers replaced by ``{"erased": true}`` and their
  terms emptied; choice/rating answers carry no personal content and stay for the aggregates.

Idempotent. Caller supplies a system context."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.engage.models import EngageParticipant


def _n(result: Any) -> int:
    return int(getattr(result, "rowcount", 0) or 0)


async def erase_user(session: AsyncSession, user_id: uuid.UUID) -> dict[str, Any]:
    from app.core.firestore.backend import uses_firestore

    if uses_firestore("engage"):
        from app.modules.engage import service_fs

        return await service_fs.erase_user(user_id)
    names = await session.execute(
        update(EngageParticipant)
        .where(EngageParticipant.user_id == user_id, EngageParticipant.display_name.is_not(None))
        .values(display_name=None)
        .execution_options(synchronize_session=False)
    )
    texts = await session.execute(
        text(
            "UPDATE engage_responses SET answer = '{\"erased\": true}'::jsonb, terms = '{}' "
            "WHERE user_id = :u AND answer ? 'text'"
        ),
        {"u": user_id},
    )
    await session.flush()
    return {"participant_names_cleared": _n(names), "text_answers_erased": _n(texts)}


def register() -> None:
    from app.modules.admin.public import register_erasure_provider

    register_erasure_provider("engage", erase_user)
