"""Media erasure provider (core request 7; privacy §6 erasure, §7 ``account_erasure``).

Deletes the user-owned objects in the private uploads bucket through
``app.modules.media.storage``: support-ticket attachments and assignment-submission files
(``uploads/<purpose>/<user_id>/...``). The rows that referenced them are minimised by the
support and learning providers. Security-case attachments (``uploads/unblock_request/``) are
*not* deleted here: D8 cases are a legal hold and age out through ``security.purge_closed_cases``
(90 days after closure). The avatar object is deleted by the identity provider, which owns
``user_profiles.avatar_s3_key``.

Idempotent and tolerant of missing objects; a storage outage raises (503) so the erasure
transaction rolls back and can be re-run. Registered when the media router is imported.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.media import storage

USER_UPLOAD_PURPOSES = ("support_attachment", "assignment_submission")


def user_prefixes(user_id: uuid.UUID) -> list[str]:
    return [f"uploads/{p}/{user_id}/" for p in USER_UPLOAD_PURPOSES]


async def erase_user(session: AsyncSession, user_id: uuid.UUID) -> dict[str, Any]:
    del session  # objects only; playback_sessions age out with their 180-day retention (D11)
    bucket = storage.storage_settings().S3_BUCKET_UPLOADS
    deleted = {p: await storage.delete_prefix(bucket, p) for p in user_prefixes(user_id)}
    return {"objects_deleted": sum(deleted.values()), "by_prefix": deleted}


def register() -> None:
    from app.modules.admin.privacy import register_erasure_provider

    register_erasure_provider("media", erase_user)
