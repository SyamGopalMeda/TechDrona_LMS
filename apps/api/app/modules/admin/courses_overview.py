"""ADM-016 courses overview: one card per catalog course for the admin panel (and the course /
certificate tiles on the admin dashboard).

Read-only aggregates under the same permission as the ADM-01 dashboard
(``analytics.read.platform``), on the caller's RLS session. No per-learner rows are returned.

* Courses come from the catalog (Postgres or Firestore, ``TD_STORE_CATALOG``); soft-deleted ones
  are skipped.
* A course's batches are the batches its enrolments point to (``enrolments.batch_id``) plus the
  batches linked to it by their delivery plan (``batches.course_id``, orgs_0005).
* ``certificates_ready`` = completed enrolments with no certificate row yet (a revoked
  certificate still counts as handled: it was issued and then withdrawn on purpose).
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any

from fastapi import Depends
from sqlalchemy import select

from app.core.auth import require_permission
from app.core.db import PrincipalDbSession
from app.core.firestore.backend import uses_firestore
from app.core.principal import Principal
from app.core.routing import authenticated_router
from app.core.time import to_rfc3339
from app.modules.catalog import api as catalog_api
from app.modules.catalog.api import Course
from app.modules.identity import clock
from app.modules.learning import public as learning_public
from app.modules.orgs import public as orgs_public
from app.modules.orgs.public import Batch

r = authenticated_router(tags=["admin"], route_tag="default", idle="extends")
NEUTRAL = {"x-td-idle": "neutral"}

# Safety cap: the company catalog is small; the page shows every course in one go.
MAX_COURSES = 500


def _d(v: date | None) -> str | None:
    return v.isoformat() if v else None


async def _courses(session: Any) -> list[Course]:
    if uses_firestore("catalog"):
        from app.modules.catalog.repo_firestore import reader

        rows, _drafts, _more = await (await reader(session)).studio_list(
            platform=True, orgs=set(), course_ids=set(), status=None, after_id=None, limit=MAX_COURSES
        )
        return list(rows)
    return list(
        (
            await session.execute(
                select(Course)
                .where(Course.deleted_at.is_(None))
                .order_by(Course.id.desc())
                .limit(MAX_COURSES)
            )
        ).scalars()
    )


@r.get("/admin/courses/overview", openapi_extra=NEUTRAL)
async def courses_overview(
    session: PrincipalDbSession, principal: Principal = Depends(require_permission("analytics.read.platform"))
) -> dict[str, Any]:
    now = clock.now()
    courses = await _courses(session)
    versions = await catalog_api.get_versions(
        session, [c.current_version_id for c in courses if c.current_version_id is not None]
    )

    # Store-neutral: enrolment / certificate counts from learning.public (the same GROUP BYs on
    # Postgres, its Firestore repository otherwise), batches from orgs.public.
    stats = await learning_public.courses_overview_stats(session, now)
    per_course = stats.per_course
    certs = stats.certificates
    links = stats.batch_links
    batch_ids = {b for _, b, _ in links if b is not None}
    batches: dict[uuid.UUID, Batch] = await orgs_public.get_batches(session, batch_ids) if batch_ids else {}
    by_course: dict[uuid.UUID, list[dict[str, Any]]] = {}
    for cid, bid, active in links:
        b = batches.get(bid) if bid is not None else None
        if b is None:  # not visible to this session
            continue
        by_course.setdefault(cid, []).append(
            {
                "batch_id": str(b.id),
                "name": b.name,
                "code": b.code,
                "status": b.status,
                "starts_on": _d(b.starts_on),
                "ends_on": _d(b.ends_on),
                "enrolled": int(active),
            }
        )
    # orgs_0005: batches linked to a course by their plan (``batches.course_id``) show up even
    # before anyone is enrolled through them.
    for b in await orgs_public.list_batches(session, exclude_status="archived", has_course=True, order="id"):
        assert b.course_id is not None
        listed = by_course.setdefault(b.course_id, [])
        if not any(x["batch_id"] == str(b.id) for x in listed):
            listed.append(
                {
                    "batch_id": str(b.id),
                    "name": b.name,
                    "code": b.code,
                    "status": b.status,
                    "starts_on": _d(b.starts_on),
                    "ends_on": _d(b.ends_on),
                    "enrolled": 0,
                }
            )

    out: list[dict[str, Any]] = []
    for c in courses:
        active, completed, ready = per_course.get(c.id, (0, 0, 0))
        v = versions.get(c.current_version_id) if c.current_version_id else None
        bl = sorted(by_course.get(c.id, []), key=lambda x: (x["starts_on"] or "9999-12-31", x["name"]))
        out.append(
            {
                "course_id": str(c.id),
                "title": c.title,
                "slug": c.slug,
                "status": c.status,
                "visibility": c.visibility,
                "course_kind": c.course_kind,
                "is_free": bool(c.is_free),
                "published_at": to_rfc3339(v.published_at) if v is not None and v.published_at else None,
                "updated_at": to_rfc3339(c.updated_at) if c.updated_at else None,
                "enrolled": active,
                "completed": completed,
                "certificates_issued": certs.get(c.id, 0),
                "certificates_ready": ready,
                "batch_count": len(bl),
                "batches": bl,
            }
        )
    out.sort(key=lambda x: (x["title"].lower(), x["course_id"]))

    learners = stats.learners
    return {
        "generated_at": to_rfc3339(now),
        "totals": {
            "courses": len(out),
            "courses_published": sum(1 for x in out if x["status"] == "published"),
            "courses_draft": sum(1 for x in out if x["status"] == "draft"),
            "learners": learners,
            "enrolled": sum(x["enrolled"] for x in out),
            "completed": sum(x["completed"] for x in out),
        },
        "certificates": {
            "issued_valid": stats.issued_valid,
            "revoked": stats.revoked,
            "issued_30d": stats.issued_30d,
            "ready": stats.ready_total,
        },
        "courses": out,
    }
