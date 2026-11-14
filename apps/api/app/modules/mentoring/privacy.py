"""DB-01: résumé erasure provider. ``mentoring`` is in admin's ``REQUIRED_ERASURE_MODULES``:
résumé content and PDFs are personal data. Registered when the module router is imported.

* ``resumes``: deleted (content and PDF keys; the S3 objects are left to the uploads-bucket
  lifecycle rule), with their version keys on Firestore.
* Postgres only: legacy ``resume_reviews`` rows are deleted first (they reference the résumé).

The mentoring sessions feature was removed (docs/cleanup/feature-removal-plan.md §3.1); its
Postgres tables stay for the VM and are no longer written by this code.

Idempotent. Caller supplies a system context."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.mentoring.models import Resume, ResumeReview


def _n(result: Any) -> int:
    return int(getattr(result, "rowcount", 0) or 0)


async def erase_user(session: AsyncSession, user_id: uuid.UUID) -> dict[str, Any]:
    from app.core.firestore.backend import uses_firestore

    if uses_firestore("mentoring"):
        from app.modules.mentoring import service_fs

        return await service_fs.erase_user(user_id)
    await session.execute(delete(ResumeReview).where(ResumeReview.user_id == user_id))
    resumes = await session.execute(delete(Resume).where(Resume.user_id == user_id))
    await session.flush()
    return {"resumes_deleted": _n(resumes)}


def register() -> None:
    from app.modules.admin.public import register_erasure_provider

    register_erasure_provider("mentoring", erase_user)
