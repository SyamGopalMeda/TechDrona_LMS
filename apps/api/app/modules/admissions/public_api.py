"""Admissions public API for other modules (store-neutral: ``TD_STORE_ADMISSIONS``).

(``admissions/public.py`` is already taken by the public website routes, so the cross-module API
lives here.) Today no other module reads admissions tables; anything that needs admissions data
must use these functions, never SQL on ``course_status`` / ``admission_*``.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import as_system
from app.modules.admissions import datastore as ads
from app.modules.admissions.models import AdmissionRegistration, CourseStatus


async def course_statuses(session: AsyncSession) -> dict[str, str]:
    """``{course_slug: open | coming_soon | closed}`` (platform-only table; read as a system job)."""
    async with as_system(session, "admissions.public_api"):
        rows = (await ads.execute(session, select(CourseStatus.course_slug, CourseStatus.status))).all()
    return {slug: st for slug, st in rows}


async def registrations_for_user(session: AsyncSession, user_id: uuid.UUID) -> list[dict[str, Any]]:
    """The admissions registrations linked to a user account (status, course, balance)."""
    from app.modules.admissions.service import registration_out

    async with as_system(session, "admissions.public_api"):
        regs = (
            await ads.execute(
                session,
                select(AdmissionRegistration)
                .where(AdmissionRegistration.user_id == user_id)
                .order_by(AdmissionRegistration.created_at.desc()),
            )
        ).scalars()
        return [registration_out(r) for r in regs]


__all__ = ["course_statuses", "registrations_for_user"]
