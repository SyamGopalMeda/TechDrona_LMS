"""Extension points other modules register at import time (no cross-module table reads).

* ``register_org_resolver(fn)``      — learning/entitlements: which organization's enrolment or
  entitlement an event belongs to (§4.2 "rolls up to the org of the enrolment"). Default
  (``_default_org``): own attempt's org, else the course enrolment's org, else a verified
  ``batch_id`` membership, else the single active student org membership; otherwise ``None``.
* ``register_lesson_meta_lookup(fn)`` — catalog: ``est_reading_minutes`` per lesson and
  ``duration_s`` per lesson asset (M5 caps §3.1, video coverage §3.9).
* ``register_engagement_toucher(fn)`` — sessions: ``touch_engaged(session_id)`` (CPR-ANL-01).
  Defaults to ``app.modules.sessions.resolver.touch_engaged`` when importable.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.principal import Principal


@dataclass(frozen=True)
class EntityRef:
    course_id: uuid.UUID | None = None
    lesson_id: uuid.UUID | None = None
    batch_id: uuid.UUID | None = None
    test_attempt_id: uuid.UUID | None = None


OrgResolver = Callable[[AsyncSession, Principal, EntityRef], Awaitable[uuid.UUID | None]]


@dataclass(frozen=True)
class LessonMeta:
    est_reading_minutes: float | None = None


@dataclass(frozen=True)
class AssetMeta:
    duration_s: float | None = None


class LessonMetaLookup:
    """Protocol-like base: subclass and register; defaults know nothing."""

    async def lessons(self, session: AsyncSession, ids: set[uuid.UUID]) -> dict[uuid.UUID, LessonMeta]:
        return {}

    async def assets(self, session: AsyncSession, ids: set[uuid.UUID]) -> dict[uuid.UUID, AssetMeta]:
        return {}


Toucher = Callable[[uuid.UUID], Awaitable[None]]

_org_resolver: OrgResolver | None = None
_lesson_meta: LessonMetaLookup = LessonMetaLookup()
_toucher: Toucher | None = None


def register_org_resolver(fn: OrgResolver | None) -> None:
    global _org_resolver
    _org_resolver = fn


def register_lesson_meta_lookup(lookup: LessonMetaLookup | None) -> None:
    global _lesson_meta
    _lesson_meta = lookup or LessonMetaLookup()


def lesson_meta_lookup() -> LessonMetaLookup:
    return _lesson_meta


def register_engagement_toucher(fn: Toucher | None) -> None:
    global _toucher
    _toucher = fn


async def _default_org(session: AsyncSession, principal: Principal, ref: EntityRef) -> uuid.UUID | None:
    """Server-side attribution (§4.2, BE-02). Never trusts a client-supplied org; a client
    ``batch_id`` is only a hint that must match an active membership. Order:

    1. the learner's own test attempt -> the attempt's organization;
    2. the learner's enrolment in the course (course_id, or the lesson's course) -> the
       enrolment's organization (``NULL`` for a D2C enrolment, which stays D2C);
    3. an active membership in ``batch_id`` -> that batch's organization
       (``orgs.service.batch_org_for_member``);
    4. exactly one active student organization membership -> that organization
       (``orgs.service.active_student_org_ids``);
    5. otherwise ``None`` (D2C / ambiguous).

    Reads other modules only through their public service functions (no raw SQL on
    ``org_memberships`` / ``batch_members`` / ``enrolments``).
    """
    from app.core.errors import ProblemError
    from app.modules.assessments.models import TestAttempt
    from app.modules.learning import service as learning_service
    from app.modules.orgs import service as orgs_service

    u = principal.user_id
    if ref.test_attempt_id is not None:
        org = (
            await session.execute(
                select(TestAttempt.organization_id).where(
                    TestAttempt.id == ref.test_attempt_id, TestAttempt.user_id == u
                )
            )
        ).scalar_one_or_none()
        if org is not None:
            return org
    course = ref.course_id
    if course is None and ref.lesson_id is not None:
        try:
            _lesson, _version, course_row = await learning_service.student_lesson(session, ref.lesson_id)
            course = course_row.id
        except ProblemError:
            course = None
    if course is not None:
        enrolment = await learning_service.get_enrolment(session, u, course)
        if enrolment is not None:
            return enrolment.organization_id
    if ref.batch_id is not None:
        org = await orgs_service.batch_org_for_member(session, ref.batch_id, u)
        if org is not None:
            return org
    orgs = await orgs_service.active_student_org_ids(session, u)
    return orgs[0] if len(orgs) == 1 else None


async def resolve_org(session: AsyncSession, principal: Principal, ref: EntityRef) -> uuid.UUID | None:
    fn = _org_resolver or _default_org
    return await fn(session, principal, ref)


async def touch_engaged(session_id: uuid.UUID) -> None:
    fn = _toucher
    if fn is None:
        from app.modules.sessions.resolver import touch_engaged as sessions_touch

        fn = sessions_touch
    await fn(session_id)
