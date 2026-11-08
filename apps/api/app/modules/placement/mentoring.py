"""Mentor console reads (web MEN-004; api-spec PLC-46 + the assigned-students list).

Assignment rule (SoD-11): a mentor sees a student when the student is an active
``member_role='student'`` member of a batch where the mentor holds ``mentor.notes.read``
(batch grant, or an organization grant covering the batch), or when the student booked a
session with the mentor (``mentor_bookings``). ``next_session_at``, the interview feedback
history and the private mentor notes come from the mentoring module
(``app.modules.mentoring.service``); reading notes is audited.

Readiness: ``weak_topics`` comes from ``analytics.topic_mastery`` (band ``weak``); company
readiness is computed for the published company paths the student has practised (company-step
practice sets), with the PLC-32 formula. Target-company goals (PLC-28..31) are not built yet, so
companies the student never practised are not listed.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import Depends, Query, Request
from sqlalchemy import select, text

from app.core import auth as core_auth
from app.core.auth import ScopeRef, require_active_principal
from app.core.db import PrincipalDbSession, system_context
from app.core.errors import ProblemError
from app.core.pagination import DEFAULT_LIMIT, MAX_LIMIT, decode_cursor, page_meta
from app.core.principal import Principal
from app.core.routing import authenticated_router

PERM = "mentor.notes.read"

mentor = authenticated_router(prefix="/mentor", tags=["placement-mentor"], route_tag="default")


async def _may(request: Request, principal: Principal, scope: ScopeRef) -> bool:
    return await core_auth.check_permission(principal, PERM, scope, request)


async def _assigned_batches(request: Request, session: Any, principal: Principal) -> dict[uuid.UUID, str]:
    """batch_id -> batch name for every batch whose students the caller may see."""
    from app.modules.orgs.models import Batch

    batch_ids = {g.scope_id for g in principal.grants if g.scope_type == "batch" and g.scope_id}
    org_ids = {g.scope_id for g in principal.grants if g.scope_type == "organization" and g.scope_id}
    if not batch_ids and not org_ids:
        return {}
    conds = []
    if batch_ids:
        conds.append(Batch.id.in_(batch_ids))
    if org_ids:
        conds.append(Batch.organization_id.in_(org_ids))
    from sqlalchemy import or_

    async with system_context(session, "placement.mentor_scope"):
        rows = (
            await session.execute(
                select(Batch.id, Batch.name).where(or_(*conds), Batch.status == "active").order_by(Batch.id)
            )
        ).all()
    out: dict[uuid.UUID, str] = {}
    for bid, name in rows:
        if await _may(request, principal, ScopeRef("batch", bid)):
            out[bid] = name
    return out


async def _require_any_grant(request: Request, principal: Principal) -> None:
    scopes = [core_auth.PLATFORM_SCOPE] + [
        ScopeRef(g.scope_type, g.scope_id) for g in principal.grants if g.scope_type != "platform"
    ]
    for s in scopes:
        if await _may(request, principal, s):
            return
    raise ProblemError("permission_denied", permission=PERM)


async def _students(
    session: Any, principal: Principal, batches: dict[uuid.UUID, str], user_id: uuid.UUID | None = None
) -> dict[uuid.UUID, dict[str, Any]]:
    if not batches:
        return {}
    sql = (
        "SELECT bm.user_id, coalesce(up.display_name, up.full_name), bm.batch_id FROM batch_members bm "
        "JOIN users u ON u.id = bm.user_id LEFT JOIN user_profiles up ON up.user_id = bm.user_id "
        "WHERE bm.batch_id = ANY(:b) AND bm.member_role = 'student' AND bm.status = 'active' "
        "AND u.deleted_at IS NULL"
    )
    params: dict[str, Any] = {"b": list(batches)}
    if user_id is not None:
        sql += " AND bm.user_id = :u"
        params["u"] = user_id
    async with system_context(session, "placement.mentor_students"):
        rows = (await session.execute(text(sql + " ORDER BY bm.user_id, bm.batch_id"), params)).all()
    out: dict[uuid.UUID, dict[str, Any]] = {}
    for uid, name, bid in rows:
        s = out.setdefault(
            uid,
            {
                "user_id": str(uid),
                "full_name": name,
                "batch_id": str(bid),
                "batch_name": batches.get(bid),
                "batches": [],
                "target_companies": [],
                "next_session_at": None,
            },
        )
        s["batches"].append({"batch_id": str(bid), "name": batches.get(bid)})
    return out


async def _booked(
    session: Any, principal: Principal, user_id: uuid.UUID | None = None
) -> dict[uuid.UUID, dict[str, Any]]:
    """Booking-assigned students (SoD-11) not already covered by a batch."""
    from app.modules.mentoring import service as msvc

    ids = await msvc.booked_students(session, principal, user_id)
    nm = await msvc.names(session, principal, ids)
    return {
        uid: {
            "user_id": str(uid),
            "full_name": nm.get(uid),
            "batch_id": None,
            "batch_name": None,
            "batches": [],
            "target_companies": [],
            "next_session_at": None,
        }
        for uid in ids
    }


async def _with_next_sessions(
    session: Any, principal: Principal, students: dict[uuid.UUID, dict[str, Any]]
) -> None:
    from app.modules.mentoring import service as msvc

    nxt = await msvc.student_summaries(session, principal, list(students))
    for uid, row in students.items():
        at = nxt.get(uid)
        row["next_session_at"] = at.isoformat() if at else None


@mentor.get("/students", openapi_extra={"x-td-idle": "neutral"})
async def mentor_students(
    request: Request,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = DEFAULT_LIMIT,
) -> dict[str, Any]:
    """Students assigned to the caller (batch grants with ``mentor.notes.read``)."""
    await _require_any_grant(request, principal)
    batches = await _assigned_batches(request, session, principal)
    students = await _students(session, principal, batches)
    for uid, row in (await _booked(session, principal)).items():
        students.setdefault(uid, row)
    ids = sorted(students, key=str)
    if cursor:
        try:
            after = str(uuid.UUID(str(decode_cursor(cursor)["id"])))
        except (KeyError, ValueError) as e:
            raise ProblemError("invalid_cursor") from e
        ids = [i for i in ids if str(i) > after]
    page, more = ids[:limit], len(ids) > limit
    shown = {i: students[i] for i in page}
    await _with_next_sessions(session, principal, shown)
    return {
        "data": [students[i] for i in page],
        "page": page_meta({"id": str(page[-1])} if more and page else None, limit),
    }


@mentor.get("/students/{user_id}", openapi_extra={"x-td-idle": "neutral"})
async def mentor_student_detail(
    user_id: uuid.UUID,
    request: Request,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
) -> dict[str, Any]:
    """PLC-46 readiness summary for an assigned student. Unassigned students are ``404``
    (existence is not disclosed, SoD-11)."""
    await _require_any_grant(request, principal)
    batches = await _assigned_batches(request, session, principal)
    found = (await _students(session, principal, batches, user_id)).get(user_id)
    if found is None and user_id != principal.user_id:
        found = (await _booked(session, principal, user_id)).get(user_id)
    if found is None:
        raise ProblemError("not_found")
    from app.modules.analytics.mastery import get_topic_mastery
    from app.modules.placement.models import Topic
    from app.modules.placement.practice import practised_company_readiness

    async with system_context(session, "placement.mentor_readiness"):
        readiness = await practised_company_readiness(session, user_id)
        views = await get_topic_mastery(session, user_id)
        names = {
            t.id: t.name
            for t in (
                await session.execute(select(Topic).where(Topic.id.in_([v.topic_id for v in views])))
            ).scalars()
        }
    topics = [
        {
            "topic_id": str(v.topic_id),
            "name": names.get(v.topic_id),
            "mastery": v.mastery,
            "band": v.band,
            "attempts": v.attempts,
        }
        for v in views
    ]
    from app.modules.mentoring import service as msvc

    await _with_next_sessions(session, principal, {user_id: found})
    return {
        **found,
        "readiness": readiness,
        "topics": topics,
        "weak_topics": [t["name"] or t["topic_id"] for t in topics if t["band"] == "weak"],
        "feedback": await msvc.feedback_history(session, principal, user_id),
        "notes": await msvc.read_notes(session, principal, user_id),
    }
