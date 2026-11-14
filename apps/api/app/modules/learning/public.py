"""Public, store-neutral API of ``learning`` for other modules (``TD_STORE_LEARNING``).

Other modules must not import ``learning.models`` or run SQL on learning tables; they call these
functions instead (the Postgres branches are the queries those modules ran, moved here verbatim).

Callers today (to be switched by their owners; see docs/firebase/agents/data-learning.md):

* admin ``courses_overview``  -> :func:`courses_overview_stats`
* paths ``_check_link`` / ``link_options`` / ``_assignment_done`` -> :func:`assignment_in_org`,
  :func:`assignment_link_options`, :func:`assignment_grades_released_at`, :func:`graded_submissions`
* analytics ``reports`` -> :func:`enrolments_of_users`, :func:`lesson_progress_counts`;
  ``hooks`` -> :func:`get_enrolment`, :func:`student_lesson`
* commerce refunds -> :func:`certificates_for_refund` + :func:`revoke_certificate`
  (``revoke_certificate`` / ``revoke_certificates_for_entitlement`` /
  ``revoke_certificates_for_courses`` keep their signatures)
* admissions -> :func:`lock_enrolment`, :func:`create_enrolment`, :func:`withdraw_enrolment`
* ``wiring.py`` -> :func:`max_progress_by_course`, :func:`has_certificate_for_courses`,
  the ``register_*`` hooks and :func:`coding_access_grant`
* media -> :func:`check_lesson_access`, :func:`get_enrolment`, :func:`get_progress`,
  :func:`record_video_heartbeat`, ``STUDENT_VISIBLE``
* mentoring -> :func:`certificates_of_user`
"""

from __future__ import annotations

import uuid
from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import and_, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.firestore.store import chunks
from app.modules.learning import fs_store as fss
from app.modules.learning.models import (
    Assignment,
    AssignmentSubmission,
    Certificate,
    Enrolment,
    LessonProgress,
)

# Re-exported service functions (they dispatch on the store themselves).
from app.modules.learning.service import (
    STUDENT_VISIBLE,
    check_lesson_access,
    create_enrolment,
    get_enrolment,
    get_progress,
    lock_enrolment,
    record_video_heartbeat,
    register_final_test_lookup,
    register_video_coverage_lookup,
    revoke_certificate,
    revoke_certificates_for_courses,
    revoke_certificates_for_entitlement,
    student_lesson,
)

__all__ = [
    "STUDENT_VISIBLE",
    "CoursesOverviewStats",
    "assignment_grades_released_at",
    "assignment_in_org",
    "assignment_link_options",
    "certificates_for_refund",
    "certificates_of_user",
    "check_lesson_access",
    "coding_access_grant",
    "courses_overview_stats",
    "create_enrolment",
    "enrolments_of_users",
    "get_enrolment",
    "get_progress",
    "graded_submissions",
    "has_certificate_for_courses",
    "lesson_progress_counts",
    "lock_enrolment",
    "max_progress_by_course",
    "record_video_heartbeat",
    "register_final_test_lookup",
    "register_video_coverage_lookup",
    "revoke_certificate",
    "revoke_certificates_for_courses",
    "revoke_certificates_for_entitlement",
    "student_lesson",
    "withdraw_enrolment",
]


async def coding_access_grant(*args: Any, **kwargs: Any) -> Any:
    """``learning.structured.coding_access_grant`` (registered with coding by ``wiring.py``)."""
    from app.modules.learning.structured import coding_access_grant as fn

    return await fn(*args, **kwargs)


# =========================================================================== admin overview


@dataclass
class CoursesOverviewStats:
    """Counts behind ``GET /admin/courses/overview``."""

    # course_id -> (active, completed, completed without a certificate row)
    per_course: dict[uuid.UUID, tuple[int, int, int]] = field(default_factory=dict)
    # course_id -> valid (not revoked) certificates
    certificates: dict[uuid.UUID, int] = field(default_factory=dict)
    # (course_id, batch_id, active enrolments) for enrolments pointing at a batch
    batch_links: list[tuple[uuid.UUID, uuid.UUID | None, int]] = field(default_factory=list)
    learners: int = 0  # distinct users with an active or completed enrolment
    issued_valid: int = 0
    revoked: int = 0
    issued_30d: int = 0
    ready_total: int = 0


async def courses_overview_stats(session: AsyncSession, now: datetime) -> CoursesOverviewStats:
    if fss.fs():
        return await _overview_fs(now)
    out = CoursesOverviewStats()
    with_cert = Enrolment.__table__.outerjoin(Certificate, Certificate.enrolment_id == Enrolment.id)
    ready_cond = and_(Enrolment.status == "completed", Certificate.id.is_(None))
    out.per_course = {
        cid: (int(a), int(c), int(rd))
        for cid, a, c, rd in (
            await session.execute(
                select(
                    Enrolment.course_id,
                    func.count().filter(Enrolment.status == "active"),
                    func.count().filter(Enrolment.status == "completed"),
                    func.count().filter(ready_cond),
                )
                .select_from(with_cert)
                .group_by(Enrolment.course_id)
            )
        ).all()
    }
    out.certificates = {
        cid: int(n)
        for cid, n in (
            await session.execute(
                select(Certificate.course_id, func.count())
                .where(Certificate.revoked_at.is_(None))
                .group_by(Certificate.course_id)
            )
        ).all()
    }
    out.batch_links = [
        (cid, bid, int(n))
        for cid, bid, n in (
            await session.execute(
                select(
                    Enrolment.course_id, Enrolment.batch_id, func.count().filter(Enrolment.status == "active")
                )
                .where(Enrolment.batch_id.is_not(None))
                .group_by(Enrolment.course_id, Enrolment.batch_id)
            )
        ).all()
    ]
    out.learners = int(
        (
            await session.execute(
                select(func.count(func.distinct(Enrolment.user_id))).where(
                    Enrolment.status.in_(("active", "completed"))
                )
            )
        ).scalar_one()
    )
    row = (
        await session.execute(
            select(
                func.count().filter(Certificate.revoked_at.is_(None)),
                func.count().filter(Certificate.revoked_at.is_not(None)),
                func.count().filter(Certificate.issued_at > now - timedelta(days=30)),
            ).select_from(Certificate)
        )
    ).one()
    out.issued_valid, out.revoked, out.issued_30d = int(row[0]), int(row[1]), int(row[2])
    out.ready_total = int(
        (await session.execute(select(func.count()).select_from(with_cert).where(ready_cond))).scalar_one()
    )
    return out


async def _overview_fs(now: datetime) -> CoursesOverviewStats:
    out = CoursesOverviewStats()
    enrolments = await fss.find(None, Enrolment)
    certs = await fss.find(None, Certificate)
    certified = {c.enrolment_id for c in certs}
    per: dict[uuid.UUID, list[int]] = defaultdict(lambda: [0, 0, 0])
    links: dict[tuple[uuid.UUID, uuid.UUID], int] = {}
    learners: set[uuid.UUID] = set()
    for e in enrolments:
        p = per[e.course_id]
        p[0] += e.status == "active"
        p[1] += e.status == "completed"
        ready = e.status == "completed" and e.id not in certified
        p[2] += ready
        out.ready_total += ready
        if e.batch_id is not None:
            links[(e.course_id, e.batch_id)] = links.get((e.course_id, e.batch_id), 0) + (
                e.status == "active"
            )
        if e.status in ("active", "completed"):
            learners.add(e.user_id)
    out.per_course = {k: (v[0], v[1], v[2]) for k, v in per.items()}
    out.batch_links = [(c, b, n) for (c, b), n in links.items()]
    out.learners = len(learners)
    valid = Counter(c.course_id for c in certs if c.revoked_at is None)
    out.certificates = dict(valid)
    out.issued_valid = sum(valid.values())
    out.revoked = sum(1 for c in certs if c.revoked_at is not None)
    out.issued_30d = sum(1 for c in certs if c.issued_at > now - timedelta(days=30))
    return out


# =========================================================================== paths


async def assignment_in_org(session: AsyncSession, assignment_id: uuid.UUID, org_id: uuid.UUID) -> bool:
    if fss.fs():
        a = await fss.get(None, Assignment, assignment_id)
        return a is not None and a.organization_id == org_id
    return (
        await session.execute(
            select(Assignment.id).where(Assignment.id == assignment_id, Assignment.organization_id == org_id)
        )
    ).scalar_one_or_none() is not None


async def assignment_link_options(
    session: AsyncSession, org_id: uuid.UUID, q: str | None, limit: int = 25
) -> list[tuple[uuid.UUID, str, Decimal]]:
    """(id, title, max_score) of the org's assignments whose title contains ``q`` (ILIKE),
    newest first."""
    if fss.fs():
        needle = (q or "").lower()
        rows = await fss.find(
            None,
            Assignment,
            filters=(("organization_id", "==", org_id),),
            order_by=(("created_at", "desc"),),
            where=lambda a: needle in (a.title or "").lower(),
            limit=limit,
        )
        return [(a.id, a.title, a.max_score) for a in rows]
    like = "%" + (q or "").replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
    res = await session.execute(
        select(Assignment.id, Assignment.title, Assignment.max_score)
        .where(Assignment.organization_id == org_id, Assignment.title.ilike(like))
        .order_by(Assignment.created_at.desc())
        .limit(limit)
    )
    return [(i, t, m) for i, t, m in res.all()]


async def assignment_grades_released_at(session: AsyncSession, assignment_id: uuid.UUID) -> datetime | None:
    if fss.fs():
        a = await fss.get(None, Assignment, assignment_id)
        return a.grades_released_at if a else None
    return (
        await session.execute(select(Assignment.grades_released_at).where(Assignment.id == assignment_id))
    ).scalar_one_or_none()


async def graded_submissions(
    session: AsyncSession, assignment_id: uuid.UUID, user_id: uuid.UUID | None = None
) -> list[tuple[uuid.UUID, uuid.UUID]]:
    """(user_id, submission_id) of graded submissions of an assignment (optionally one user)."""
    if fss.fs():
        filters: list[Any] = [("assignment_id", "==", assignment_id), ("status", "==", "graded")]
        if user_id is not None:
            filters.append(("user_id", "==", user_id))
        return [(s.user_id, s.id) for s in await fss.find(None, AssignmentSubmission, filters=filters)]
    q = select(AssignmentSubmission.user_id, AssignmentSubmission.id).where(
        AssignmentSubmission.assignment_id == assignment_id, AssignmentSubmission.status == "graded"
    )
    if user_id is not None:
        q = q.where(AssignmentSubmission.user_id == user_id)
    return [(u, s) for u, s in (await session.execute(q)).all()]


# =========================================================================== analytics


async def enrolments_of_users(
    session: AsyncSession, users: list[uuid.UUID]
) -> list[tuple[uuid.UUID, uuid.UUID, uuid.UUID, float, bool]]:
    """(enrolment_id, user_id, course_id, progress_pct, completed) for ``users``; withdrawn
    enrolments excluded."""
    if not users:
        return []
    if fss.fs():
        out = []
        for chunk in chunks(users):
            for e in await fss.find(None, Enrolment, filters=(("user_id", "in", chunk),)):
                if e.status != "withdrawn":
                    out.append(
                        (
                            e.id,
                            e.user_id,
                            e.course_id,
                            float(e.progress_pct or 0),
                            e.status == "completed" or e.completed_at is not None,
                        )
                    )
        return out
    rows = (
        await session.execute(
            text(
                "SELECT id, user_id, course_id, progress_pct, "
                "(status = 'completed' OR completed_at IS NOT NULL) FROM enrolments "
                "WHERE user_id = ANY(:us) AND status <> 'withdrawn'"
            ),
            {"us": users},
        )
    ).all()
    return [(r[0], r[1], r[2], float(r[3] or 0), bool(r[4])) for r in rows]


async def lesson_progress_counts(
    session: AsyncSession, enrolment_ids: list[uuid.UUID]
) -> dict[uuid.UUID, tuple[int, int]]:
    """lesson_key -> (opened, completed) over ``enrolment_ids``."""
    if not enrolment_ids:
        return {}
    if fss.fs():
        acc: dict[uuid.UUID, list[int]] = defaultdict(lambda: [0, 0])
        for chunk in chunks(enrolment_ids):
            for lp in await fss.find(None, LessonProgress, filters=(("enrolment_id", "in", chunk),)):
                a = acc[lp.lesson_key]
                a[0] += lp.first_opened_at is not None or lp.status != "not_started"
                a[1] += lp.status == "completed"
        return {k: (v[0], v[1]) for k, v in acc.items()}
    rows = (
        await session.execute(
            text(
                "SELECT lesson_key, count(*) FILTER (WHERE first_opened_at IS NOT NULL "
                "OR status <> 'not_started'), count(*) FILTER (WHERE status = 'completed') "
                "FROM lesson_progress WHERE enrolment_id = ANY(:es) GROUP BY lesson_key"
            ),
            {"es": enrolment_ids},
        )
    ).all()
    return {r[0]: (int(r[1]), int(r[2])) for r in rows}


# =========================================================================== commerce


async def certificates_for_refund(
    session: AsyncSession,
    user_id: uuid.UUID,
    *,
    course_ids: Iterable[uuid.UUID] = (),
    issued_since: datetime | None = None,
) -> list[Certificate]:
    """Valid certificates of ``user_id`` for any of ``course_ids`` or issued at/after
    ``issued_since`` (row-locked on Postgres, as the refund path did)."""
    courses = set(course_ids)
    if not courses and issued_since is None:
        return []
    if fss.fs():
        return await fss.find(
            session,
            Certificate,
            filters=(("user_id", "==", user_id),),
            where=lambda c: (
                c.revoked_at is None
                and (c.course_id in courses or (issued_since is not None and c.issued_at >= issued_since))
            ),
        )
    conds: list[Any] = []
    if courses:
        conds.append(Certificate.course_id.in_(courses))
    if issued_since is not None:
        conds.append(Certificate.issued_at >= issued_since)
    q = select(Certificate).where(
        Certificate.user_id == user_id, Certificate.revoked_at.is_(None), or_(*conds)
    )
    return list((await session.execute(q.with_for_update())).scalars())


# =========================================================================== admissions


async def withdraw_enrolment(
    session: AsyncSession, enrolment_id: uuid.UUID, entitlement_id: uuid.UUID | None
) -> bool:
    """Withdraw an active enrolment granted under ``entitlement_id`` (admissions ``revoke_access``)."""
    enr = await fss.get(session, Enrolment, enrolment_id)
    if enr is None or enr.status != "active" or enr.entitlement_id != entitlement_id:
        return False
    enr.status = "withdrawn"
    await fss.flush(session)
    return True


# =========================================================================== wiring (usage provider)


async def max_progress_by_course(
    session: AsyncSession, user_id: uuid.UUID, course_ids: Iterable[uuid.UUID]
) -> dict[uuid.UUID, Decimal]:
    courses = list(course_ids)
    if not courses:
        return {}
    if fss.fs():
        out: dict[uuid.UUID, Decimal] = {}
        for e in await fss.find(None, Enrolment, filters=(("user_id", "==", user_id),)):
            if e.course_id in courses:
                out[e.course_id] = max(out.get(e.course_id, e.progress_pct), e.progress_pct)
        return out
    rows = (
        await session.execute(
            text(
                "SELECT course_id, max(progress_pct) FROM enrolments "
                "WHERE user_id = :u AND course_id = ANY(:c) GROUP BY course_id"
            ),
            {"u": user_id, "c": courses},
        )
    ).all()
    return {r[0]: Decimal(r[1]) for r in rows}


async def has_certificate_for_courses(
    session: AsyncSession, user_id: uuid.UUID, course_ids: Iterable[uuid.UUID]
) -> bool:
    """Any certificate row (revoked included, as the usage provider counted) for these courses."""
    courses = list(course_ids)
    if not courses:
        return False
    if fss.fs():
        return any(
            c.course_id in courses
            for c in await fss.find(None, Certificate, filters=(("user_id", "==", user_id),))
        )
    row = (
        await session.execute(
            text("SELECT 1 FROM certificates WHERE user_id = :u AND course_id = ANY(:c) LIMIT 1"),
            {"u": user_id, "c": courses},
        )
    ).first()
    return row is not None


# =========================================================================== mentoring


async def certificates_of_user(session: AsyncSession, user_id: uuid.UUID) -> list[Certificate]:
    """Valid certificates of a user, newest first (résumé auto-fill)."""
    if fss.fs():
        rows = await fss.find(
            None, Certificate, filters=(("user_id", "==", user_id),), where=lambda c: c.revoked_at is None
        )
        return sorted(rows, key=lambda c: c.issued_at, reverse=True)
    return list(
        (
            await session.execute(
                select(Certificate)
                .where(Certificate.user_id == user_id, Certificate.revoked_at.is_(None))
                .order_by(Certificate.issued_at.desc())
            )
        ).scalars()
    )
