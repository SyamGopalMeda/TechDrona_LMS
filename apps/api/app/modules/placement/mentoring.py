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
from sqlalchemy import select

from app.core import auth as core_auth
from app.core.auth import ScopeRef, require_active_principal
from app.core.db import PrincipalDbSession
from app.core.errors import ProblemError
from app.core.pagination import DEFAULT_LIMIT, MAX_LIMIT, decode_cursor, page_meta
from app.core.principal import Principal
from app.core.routing import authenticated_router
from app.modules.placement.rls import bind_principal

PERM = "mentor.notes.read"

mentor = authenticated_router(
    prefix="/mentor", tags=["placement-mentor"], route_tag="default", dependencies=[Depends(bind_principal)]
)


async def _may(request: Request, principal: Principal, scope: ScopeRef) -> bool:
    return await core_auth.check_permission(principal, PERM, scope, request)


async def _assigned_batches(request: Request, session: Any, principal: Principal) -> dict[uuid.UUID, str]:
    """batch_id -> batch name for every batch whose students the caller may see."""
    from app.modules.orgs import public as orgs_public
    from app.modules.placement.rls import system_scope

    batch_ids = {g.scope_id for g in principal.grants if g.scope_type == "batch" and g.scope_id}
    org_ids = {g.scope_id for g in principal.grants if g.scope_type == "organization" and g.scope_id}
    if not batch_ids and not org_ids:
        return {}
    # id in batches OR organization in orgs, active, ordered by id (orgs public API, system scope)
    async with system_scope(session, "placement.mentor_scope"):
        found = (
            {b.id: b for b in await orgs_public.list_batches(session, status="active", ids=batch_ids)}
            if batch_ids
            else {}
        )
        if org_ids:
            found.update(
                {
                    b.id: b
                    for b in await orgs_public.list_batches(
                        session, status="active", organization_ids=org_ids
                    )
                }
            )
    out: dict[uuid.UUID, str] = {}
    for b in sorted(found.values(), key=lambda b: str(b.id)):
        if await _may(request, principal, ScopeRef("batch", b.id)):
            out[b.id] = b.name
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
    from app.modules.placement.rls import system_scope

    async with system_scope(session, "placement.mentor_students"):
        rows = await _students_rows_public(session, list(batches), user_id)
    return _students_out(rows, batches)


async def _students_rows_public(
    session: Any, batch_ids: list[uuid.UUID], user_id: uuid.UUID | None
) -> list[tuple[uuid.UUID, str | None, uuid.UUID]]:
    from app.modules.identity import public as identity_public
    from app.modules.orgs import public as orgs_public

    # bm.status = 'active' (removed_at is not part of the original filter)
    members = [
        m
        for m in await orgs_public.batch_members(
            session, batch_ids=batch_ids, member_role="student", active_only=False
        )
        if m.status == "active"
    ]
    if user_id is not None:
        members = [m for m in members if m.user_id == user_id]
    uids = {m.user_id for m in members}
    users = await identity_public.get_users(session, uids)
    profiles = await identity_public.get_profiles(session, uids)
    out = []
    for m in members:
        u = users.get(m.user_id)
        if u is None or u.deleted_at is not None:
            continue
        pr = profiles.get(m.user_id)
        out.append((m.user_id, (pr.display_name or pr.full_name) if pr else None, m.batch_id))
    return sorted(out, key=lambda r: (str(r[0]), str(r[2])))


def _students_out(rows: list[Any], batches: dict[uuid.UUID, str]) -> dict[uuid.UUID, dict[str, Any]]:
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
    from app.modules.placement.bank import _fs as bank_fs
    from app.modules.placement.models import Topic
    from app.modules.placement.practice import practised_company_readiness
    from app.modules.placement.rls import system_scope

    async with system_scope(session, "placement.mentor_readiness"):
        readiness = await practised_company_readiness(session, user_id)
        views = await get_topic_mastery(session, user_id)
        if bank_fs():
            from app.modules.placement.public import topic_names

            names = await topic_names(session, [v.topic_id for v in views])
        else:
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
