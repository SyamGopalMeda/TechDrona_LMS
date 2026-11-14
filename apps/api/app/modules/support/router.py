"""Support desk API (api-specification §22, SUP-01..15; the public corporate enquiry form
lives in ``enquiries.py``).

Students (any signed-in user, including restricted ones: route tag ``account_status``) open
tickets and talk to support; staff triage through ``/support/queue`` within their lane
(``ticket.*`` permissions; Admin sees every category). Internal notes are never
shown to the requester. The user lookup (SUP-11) is limited and masked (no evidence, no full
IPs, no passwords — SoD-03) and every lookup is audited with a reason code. Device resets and
session kills reuse SES-12 / SES-10 (sessions module).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, literal, or_, select, tuple_

from app.core.audit import audit
from app.core.auth import (
    PLATFORM_SCOPE,
    check_permission,
    require_active_principal,
    require_permission,
)
from app.core.db import PrincipalDbSession, system_context
from app.core.errors import ProblemError
from app.core.idempotency import IdemResult, idempotent
from app.core.ids import uuid7
from app.core.outbox import emit_event
from app.core.pagination import DEFAULT_LIMIT, MAX_LIMIT, decode_cursor, page_meta
from app.core.principal import Principal
from app.core.routing import authenticated_router
from app.core.time import to_rfc3339, within
from app.modules.identity import clock
from app.modules.identity.contacts import mask_email, mask_phone
from app.modules.identity.public import User
from app.modules.support import service as sv
from app.modules.support.models import SupportTicket, SupportTicketMessage, SupportUserNote

AS = {"x-td-route-tag": "account_status"}
NEUTRAL = {"x-td-idle": "neutral"}
REASON_CODES = ("ticket", "unblock_request", "case", "incident", "user_request", "legal")
TICKETS_PER_DAY = 10
MESSAGES_PER_HOUR = 30

r = authenticated_router(tags=["support"], route_tag="default", idle="extends")

Category = Literal[
    "account_access",
    "device_reset",
    "billing",
    "refund",
    "content",
    "assessment",
    "technical",
    "grievance",
    "privacy_request",
    "certificate",
    "appeal",
    "other",
]
Status = Literal["open", "pending_user", "pending_internal", "resolved", "closed"]
Priority = Literal["low", "normal", "high", "urgent"]
Limit = Annotated[int, Query(ge=1, le=MAX_LIMIT)]


def _vf(field: str, code: str, message: str) -> ProblemError:
    return ProblemError("validation_failed", 422, errors=[{"field": field, "code": code, "message": message}])


class ContextIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    route: str | None = Field(default=None, max_length=300)
    browser: str | None = Field(default=None, max_length=100)
    os: str | None = Field(default=None, max_length=100)
    request_id: str | None = Field(default=None, max_length=64)


class AttachmentIn(BaseModel):
    """A file uploaded first with MED-02 ``purpose=support_attachment`` (BE-17)."""

    model_config = ConfigDict(extra="forbid")
    s3_key: str = Field(min_length=10, max_length=400)
    filename: str = Field(min_length=1, max_length=200)
    content_type: str = Field(min_length=3, max_length=120)
    size_bytes: int = Field(gt=0, le=10 * 1024 * 1024)


MAX_ATTACHMENTS = 5


def _attachments(items: list[AttachmentIn], principal: Principal) -> list[dict[str, Any]]:
    """Only the requester's own MED-02 support uploads can be attached."""
    from app.modules.media.router import ALLOWED_TYPES, SUPPORT_ATTACHMENT_PREFIX

    prefix = f"{SUPPORT_ATTACHMENT_PREFIX}{principal.user_id}/"
    out = []
    for i, a in enumerate(items):
        if not a.s3_key.startswith(prefix) or ".." in a.s3_key:
            raise _vf(
                f"attachments.{i}.s3_key", "invalid", "Upload the file with POST /media/uploads/file first"
            )
        if a.content_type not in ALLOWED_TYPES["support_attachment"]:
            raise _vf(f"attachments.{i}.content_type", "file_type", "This file type is not allowed")
        out.append(a.model_dump())
    return out


class TicketIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    category: Category
    subject: str = Field(min_length=3, max_length=200)
    body: str = Field(min_length=10, max_length=5000)
    attachments: list[AttachmentIn] = Field(default_factory=list, max_length=MAX_ATTACHMENTS)
    related_order_id: uuid.UUID | None = None
    related_unblock_request_id: uuid.UUID | None = None
    # Appeal of an invalidated attempt (FR-ASM-012 via an ``assessment``/``appeal`` ticket; the
    # web prefills it from ``/app/support/new?topic=assessment&attempt_id=``). Stored in the
    # ticket context; there is no column for it (weblearn request 4).
    related_attempt_id: uuid.UUID | None = None
    context: ContextIn | None = None


class MessageIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    body: str = Field(min_length=1, max_length=5000)
    visibility: Literal["public", "internal"] = "public"
    attachments: list[AttachmentIn] = Field(default_factory=list, max_length=MAX_ATTACHMENTS)


class ReopenIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str | None = Field(default=None, max_length=1000)


class CsatIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    score: int = Field(ge=1, le=5)
    comment: str | None = Field(default=None, max_length=2000)


class TicketPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    assign_to_me: bool | None = None
    assigned_to: uuid.UUID | None = None
    status: Status | None = None
    priority: Priority | None = None
    related_case_id: uuid.UUID | None = None
    related_unblock_request_id: uuid.UUID | None = None


class EscalateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    to: Literal["finance", "security", "content"]
    note: str = Field(min_length=3, max_length=2000)


class MergeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    into_ticket_id: uuid.UUID


class SupportActionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason_code: str = "ticket"
    ticket_id: uuid.UUID | None = None


class NoteIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    body: str = Field(min_length=3, max_length=4000)
    ticket_id: uuid.UUID | None = None


# --------------------------------------------------------------------------- helpers


async def _unblock_owner(
    session: Any, principal: Principal, request_id: uuid.UUID
) -> tuple[uuid.UUID, uuid.UUID]:
    """(owner user id, security case id) of an unblock request. Security tables are read
    under a system context, then the caller's RLS context is restored."""
    from app.modules.security import public as security

    async with system_context(session, "support.link_unblock"):
        ur = await security.get_unblock_request(session, request_id)
    if ur is None:
        raise ProblemError("not_found")
    return ur.user_id, ur.case_id


async def _visible(session: Any, principal: Principal, t: SupportTicket) -> tuple[bool, sv.StaffScope | None]:
    """(is_requester, staff scope if the caller may act as an agent on this ticket)."""
    sc = await sv.staff_scope(session, principal)
    agent = sc if sc.sees(t) else None
    if t.requester_id != principal.user_id and agent is None:
        raise ProblemError("not_found")
    return t.requester_id == principal.user_id, agent


async def _ticket_view(session: Any, t: SupportTicket, *, internal: bool, staff: bool) -> dict[str, Any]:
    counts = await sv.message_counts(session, [t.id], internal=internal)
    req = (await sv.requester_info(session, {t.requester_id})).get(t.requester_id) if staff else None
    return sv.ticket_out(t, message_count=counts.get(t.id, 0), requester=req)


_FAR_DUE = datetime(9999, 1, 1, tzinfo=UTC)


def _queue_cursor(cursor: str | None) -> tuple[datetime, uuid.UUID] | None:
    if not cursor:
        return None
    pos = decode_cursor(cursor)
    try:
        return datetime.fromisoformat(str(pos["due"])), uuid.UUID(str(pos["id"]))
    except (KeyError, ValueError) as e:
        raise ProblemError("invalid_cursor") from e


def _cursor(cursor: str | None) -> uuid.UUID | None:
    if not cursor:
        return None
    try:
        return uuid.UUID(str(decode_cursor(cursor)["id"]))
    except (KeyError, ValueError) as e:
        raise ProblemError("invalid_cursor") from e


# --------------------------------------------------------------------------- SUP-01 create


@r.post("/support/tickets", status_code=201, openapi_extra=AS)
async def create_ticket(
    body: TicketIn,
    request: Request,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
) -> JSONResponse:
    async def op() -> IdemResult:
        since = clock.now() - timedelta(days=1)
        if sv.on_firestore():
            recent = await (await sv.fs_repo(session)).count_tickets_since(principal.user_id, since)
        else:
            recent = (
                await session.execute(
                    select(func.count()).where(
                        SupportTicket.requester_id == principal.user_id, SupportTicket.created_at > since
                    )
                )
            ).scalar_one()
        if recent >= TICKETS_PER_DAY:
            raise ProblemError("rate_limited", headers={"Retry-After": "86400"})
        if body.related_order_id is not None:
            from app.modules.commerce import public as commerce

            order = await commerce.get_order(session, body.related_order_id)
            if order is None or order.user_id != principal.user_id:
                raise _vf("related_order_id", "not_found", "Order not found")
        case_id: uuid.UUID | None = None
        if body.related_unblock_request_id is not None:
            owner, case_id = await _unblock_owner(session, principal, body.related_unblock_request_id)
            if owner != principal.user_id:
                raise _vf("related_unblock_request_id", "not_found", "Unblock request not found")
        if body.related_attempt_id is not None:
            from app.modules.assessments import public as assessments

            attempt = await assessments.get_attempt(session, body.related_attempt_id)
            if attempt is None or attempt.user_id != principal.user_id:
                raise _vf("related_attempt_id", "not_found", "Test attempt not found")
        files = _attachments(body.attachments, principal)
        now = clock.now()
        grievance = body.category == "grievance"
        priority = await sv.derive_priority(session, principal.user_id, body.category)
        first_due, res_due = sv.sla_due(priority, grievance, now)
        t = sv.new_ticket(
            id=uuid7(),
            requester_id=principal.user_id,
            organization_id=None,
            category=body.category,
            subject=body.subject.strip(),
            body=body.body.strip(),
            status="open",
            priority=priority,
            is_grievance=grievance,
            related_order_id=body.related_order_id,
            related_case_id=case_id,
            related_unblock_request_id=body.related_unblock_request_id,
            context={
                **(body.context.model_dump(exclude_none=True) if body.context else {}),
                **({"attachments": files} if files else {}),
                **({"attempt_id": str(body.related_attempt_id)} if body.related_attempt_id else {}),
            },
            first_response_due_at=first_due,
            resolution_due_at=res_due,
            last_message_at=now,
            created_at=now,
            updated_at=now,
        )
        await sv.insert_ticket(session, t)
        await audit(
            session,
            principal,
            "support.ticket.created",
            "support_ticket",
            t.id,
            organization_id=t.organization_id,
            subject_user_id=principal.user_id,
            after={"category": t.category, "priority": t.priority, "is_grievance": grievance},
        )
        await emit_event(
            session,
            "support.ticket_created",
            {"ticket_id": str(t.id), "category": t.category, "priority": t.priority},
            aggregate_type="support_ticket",
            aggregate_id=t.id,
        )
        return IdemResult(status=201, body=sv.ticket_out(t), resource_id=t.id)

    return await idempotent(request, session, user_id=principal.user_id, operation=op, required=False)


# --------------------------------------------------------------------------- SUP-02 own list


@r.get("/me/support/tickets", openapi_extra={**AS, **NEUTRAL})
async def my_tickets(
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
    status: Status | None = None,
    cursor: str | None = None,
    limit: Limit = DEFAULT_LIMIT,
) -> dict[str, Any]:
    if sv.on_firestore():
        rows, nxt = await (await sv.fs_repo(session)).tickets_of(
            principal.user_id, status=status, cursor=cursor, limit=limit
        )
        counts = await sv.message_counts(session, [t.id for t in rows], internal=False)
        return {
            "data": [sv.ticket_out(t, message_count=counts.get(t.id, 0)) for t in rows],
            "page": {"next_cursor": nxt, "has_more": nxt is not None, "limit": limit},
        }
    q = select(SupportTicket).where(SupportTicket.requester_id == principal.user_id)
    if status:
        q = q.where(SupportTicket.status == status)
    after = _cursor(cursor)
    if after:
        q = q.where(SupportTicket.id < after)
    rows = list((await session.execute(q.order_by(SupportTicket.id.desc()).limit(limit + 1))).scalars())
    more = len(rows) > limit
    rows = rows[:limit]
    counts = await sv.message_counts(session, [t.id for t in rows], internal=False)
    return {
        "data": [sv.ticket_out(t, message_count=counts.get(t.id, 0)) for t in rows],
        "page": page_meta({"id": str(rows[-1].id)} if more and rows else None, limit),
    }


# --------------------------------------------------------------------------- SUP-03 thread


@r.get("/support/tickets/{ticket_id}", openapi_extra={**AS, **NEUTRAL})
async def get_ticket(
    ticket_id: uuid.UUID,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
) -> dict[str, Any]:
    t = await sv.load_ticket(session, ticket_id)
    _is_owner, agent = await _visible(session, principal, t)
    # Internal notes are platform-lane only.
    internal = agent is not None and agent.sees_internal(t)
    msgs: Any
    if sv.on_firestore():
        msgs = await (await sv.fs_repo(session)).thread(None, t, internal=internal)
    else:
        q = select(SupportTicketMessage).where(SupportTicketMessage.support_ticket_id == t.id)
        if not internal:
            q = q.where(SupportTicketMessage.visibility == "public")
        msgs = (
            await session.execute(q.order_by(SupportTicketMessage.created_at, SupportTicketMessage.id))
        ).scalars()
    if agent is not None and t.requester_id != principal.user_id:
        await audit(
            session,
            principal,
            "support.ticket.viewed",
            "support_ticket",
            t.id,
            organization_id=t.organization_id,
            subject_user_id=t.requester_id,
        )
    staff = agent is not None and t.requester_id != principal.user_id
    return {
        **(await _ticket_view(session, t, internal=internal, staff=staff)),
        "messages": [sv.message_out(m) for m in msgs],
        "viewer": "agent" if staff else "requester",
    }


# --------------------------------------------------------------------------- SUP-04 reply / note


@r.post("/support/tickets/{ticket_id}/messages", status_code=201, openapi_extra=AS)
async def post_message(
    ticket_id: uuid.UUID,
    body: MessageIn,
    request: Request,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
) -> JSONResponse:
    async def op() -> IdemResult:
        t = await sv.load_ticket(session, ticket_id, for_update=True)
        is_owner, agent = await _visible(session, principal, t)
        as_agent = agent is not None and agent.can_respond_on(t) and not is_owner
        if body.visibility == "internal" and not (as_agent and agent is not None and agent.sees_internal(t)):
            raise ProblemError("permission_denied", permission="ticket.respond")
        if not is_owner and not as_agent:
            raise ProblemError("permission_denied", permission="ticket.respond")
        if t.status == "closed" or t.merged_into_id is not None:
            raise ProblemError("invalid_state_transition", current_state=t.status, allowed=["reopen"])
        hour_ago = clock.now() - timedelta(hours=1)
        if sv.on_firestore():
            recent = await (await sv.fs_repo(session)).count_messages_by_author_since(
                principal.user_id, hour_ago
            )
        else:
            recent = (
                await session.execute(
                    select(func.count()).where(
                        SupportTicketMessage.author_id == principal.user_id,
                        SupportTicketMessage.created_at > hour_ago,
                    )
                )
            ).scalar_one()
        if recent >= MESSAGES_PER_HOUR:
            raise ProblemError("rate_limited", headers={"Retry-After": "3600"})
        m = await sv.add_message(
            session,
            t,
            author_id=principal.user_id,
            author_kind="agent" if as_agent else "requester",
            body=body.body.strip(),
            visibility=body.visibility,
            attachments=_attachments(body.attachments, principal),
        )
        if as_agent and body.visibility == "public":
            if t.first_responded_at is None:
                t.first_responded_at = m.created_at
            if t.status in ("open", "pending_internal"):
                t.status = "pending_user"
        elif not as_agent:
            if t.status == "pending_user":
                t.status = "open"
            elif t.status == "resolved":
                t.status = "open"
                t.resolved_at = None
        await sv.save(session, t)
        if as_agent:
            await audit(
                session,
                principal,
                "support.ticket.note_added" if body.visibility == "internal" else "support.ticket.replied",
                "support_ticket",
                t.id,
                organization_id=t.organization_id,
                subject_user_id=t.requester_id,
            )
        return IdemResult(status=201, body=sv.message_out(m), resource_id=m.id)

    return await idempotent(request, session, user_id=principal.user_id, operation=op, required=False)


# --------------------------------------------------------------------------- attachments (BE-17)


@r.get(
    "/support/tickets/{ticket_id}/attachments/{ref}/{index}",
    openapi_extra={**AS, **NEUTRAL},
)
async def attachment_download(
    ticket_id: uuid.UUID,
    ref: str,
    index: int,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
) -> dict[str, Any]:
    """Short-lived download URL for an attachment. ``ref`` is ``ticket`` (files sent with
    SUP-01) or a message id (SUP-04). Same visibility as the thread: the requester and agents
    who see the ticket; internal-note files only for platform-lane agents."""
    from app.core.time import to_rfc3339
    from app.modules.media.storage import presign_get, storage_settings

    t = await sv.load_ticket(session, ticket_id)
    _is_owner, agent = await _visible(session, principal, t)
    files: list[Any]
    if ref == "ticket":
        files = list((t.context or {}).get("attachments") or [])
    else:
        try:
            mid = uuid.UUID(ref)
        except ValueError as e:
            raise ProblemError("not_found") from e
        m: Any
        if sv.on_firestore():
            m = await (await sv.fs_repo(session)).get_message(None, t, mid)
        else:
            m = (
                await session.execute(
                    select(SupportTicketMessage).where(
                        SupportTicketMessage.id == mid, SupportTicketMessage.support_ticket_id == t.id
                    )
                )
            ).scalar_one_or_none()
        if m is None or m.redacted_at is not None:
            raise ProblemError("not_found")
        if m.visibility != "public" and not (agent is not None and agent.sees_internal(t)):
            raise ProblemError("not_found")
        files = list(m.attachments or [])
    if not 0 <= index < len(files) or not isinstance(files[index], dict):
        raise ProblemError("not_found")
    f = files[index]
    key = str(f["s3_key"])
    url, exp = presign_get(
        storage_settings().S3_BUCKET_UPLOADS, key, filename=str(f.get("filename") or "file")
    )
    if agent is not None and t.requester_id != principal.user_id:
        await audit(
            session,
            principal,
            "support.attachment.downloaded",
            "support_ticket",
            t.id,
            organization_id=t.organization_id,
            subject_user_id=t.requester_id,
            after={"ref": ref, "index": index},
        )
    return {"url": url, "expires_at": to_rfc3339(exp), "filename": f.get("filename")}


# --------------------------------------------------------------------------- SUP-05 / SUP-06


async def _own(session: Any, principal: Principal, ticket_id: uuid.UUID) -> SupportTicket:
    t = await sv.load_ticket(session, ticket_id, for_update=True)
    if t.requester_id != principal.user_id:
        raise ProblemError("not_found")
    return t


@r.post("/support/tickets/{ticket_id}/reopen", openapi_extra=AS)
async def reopen(
    ticket_id: uuid.UUID,
    body: ReopenIn,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
) -> dict[str, Any]:
    t = await _own(session, principal, ticket_id)
    if t.status != "resolved":
        raise ProblemError("invalid_state_transition", current_state=t.status, allowed=["resolved"])
    t.status = "open"
    t.resolved_at = None
    await sv.add_message(
        session,
        t,
        author_id=principal.user_id,
        author_kind="requester",
        body=f"Reopened: {body.reason.strip()}" if body.reason and body.reason.strip() else "Reopened.",
    )
    await sv.save(session, t)
    await audit(
        session,
        principal,
        "support.ticket.reopened",
        "support_ticket",
        t.id,
        organization_id=t.organization_id,
    )
    return await _ticket_view(session, t, internal=False, staff=False)


@r.post("/support/tickets/{ticket_id}/csat", openapi_extra=AS)
async def csat(
    ticket_id: uuid.UUID,
    body: CsatIn,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
) -> dict[str, Any]:
    t = await _own(session, principal, ticket_id)
    if t.status not in ("resolved", "closed"):
        raise ProblemError("invalid_state_transition", current_state=t.status, allowed=["resolved", "closed"])
    if t.csat_score is not None:
        raise ProblemError("invalid_state_transition", current_state="rated", allowed=[])
    t.csat_score = body.score
    t.csat_comment = body.comment
    t.csat_at = clock.now()
    await sv.save(session, t)
    return await _ticket_view(session, t, internal=False, staff=False)


# --------------------------------------------------------------------------- SUP-07 queue


@r.get("/support/queue", openapi_extra=NEUTRAL)
async def queue(
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
    status: Status | None = None,
    priority: Priority | None = None,
    category: Category | None = None,
    assigned: Literal["me", "unassigned", "any"] = "any",
    q: Annotated[str | None, Query(max_length=100)] = None,
    cursor: str | None = None,
    limit: Limit = DEFAULT_LIMIT,
) -> dict[str, Any]:
    sc = await sv.staff_scope(session, principal)
    if not sc.any:
        raise ProblemError("permission_denied", permission="ticket.read")
    if sv.on_firestore():
        return await _queue_firestore(
            session, principal, sc, status, priority, category, assigned, q, cursor, limit
        )
    conds: list[Any] = []
    if not sc.all_categories:
        lane: list[Any] = []
        if sc.categories:
            lane.append(SupportTicket.category.in_(sc.categories))
        if sc.escalations:
            lane.append(SupportTicket.escalated_to.in_(sc.escalations))
        conds.append(or_(*lane))
    base = list(conds)
    if status:
        conds.append(SupportTicket.status == status)
    else:
        conds.append(SupportTicket.status.in_(sv.OPEN_STATUSES))
    if priority:
        conds.append(SupportTicket.priority == priority)
    if category:
        conds.append(SupportTicket.category == category)
    if assigned == "me":
        conds.append(SupportTicket.assigned_to == principal.user_id)
    elif assigned == "unassigned":
        conds.append(SupportTicket.assigned_to.is_(None))
    if q:
        like = f"%{q.strip()}%"
        conds.append(or_(SupportTicket.subject.ilike(like), SupportTicket.ticket_number.ilike(like)))
    # SLA order across pages (ADM-38): soonest resolution deadline first, keyset on (due, id).
    due = func.coalesce(SupportTicket.resolution_due_at, _FAR_DUE)
    qry = select(SupportTicket).where(*conds)
    pos = _queue_cursor(cursor)
    if pos is not None:
        qry = qry.where(tuple_(due, SupportTicket.id) > tuple_(literal(pos[0]), literal(pos[1])))
    rows = list((await session.execute(qry.order_by(due, SupportTicket.id).limit(limit + 1))).scalars())
    more = len(rows) > limit
    rows = rows[:limit]
    full = await sv.message_counts(session, [t.id for t in rows if sc.sees_internal(t)], internal=True)
    public = await sv.message_counts(session, [t.id for t in rows if not sc.sees_internal(t)], internal=False)
    counts = {**public, **full}
    req = await sv.requester_info(session, {t.requester_id for t in rows})
    open_rows = (
        await session.execute(
            select(
                SupportTicket.status,
                SupportTicket.assigned_to,
                SupportTicket.first_response_due_at,
                SupportTicket.first_responded_at,
                SupportTicket.resolution_due_at,
            ).where(*base, SupportTicket.status.in_(sv.OPEN_STATUSES))
        )
    ).all()
    now = clock.now()
    summary = {s: 0 for s in sv.OPEN_STATUSES}
    breached = unassigned = 0
    for st, assignee, frd, fr, rd in open_rows:
        summary[st] += 1
        unassigned += assignee is None
        breached += bool((rd and now > rd) or (frd and fr is None and now > frd))
    return {
        "data": [
            sv.ticket_out(t, message_count=counts.get(t.id, 0), requester=req.get(t.requester_id))
            for t in rows
        ],
        "page": page_meta(
            {"due": (rows[-1].resolution_due_at or _FAR_DUE).isoformat(), "id": str(rows[-1].id)}
            if more and rows
            else None,
            limit,
        ),
        "counts": {**summary, "breached": breached, "unassigned": unassigned},
    }


async def _queue_firestore(
    session: Any,
    principal: Principal,
    sc: sv.StaffScope,
    status: str | None,
    priority: str | None,
    category: str | None,
    assigned: str,
    q: str | None,
    cursor: str | None,
    limit: int,
) -> dict[str, Any]:
    """SUP-07 on Firestore: the status filter runs in the store; the lane (category OR
    escalation), the other filters, the search and the SLA keyset order run in memory over the
    company's open queue. Same response and cursor shape as Postgres."""
    repo = await sv.fs_repo(session)
    open_rows = [t for t in await repo.lane_tickets(sv.OPEN_STATUSES) if sc.sees(t)]
    rows = open_rows if not status else [t for t in await repo.lane_tickets([status]) if sc.sees(t)]
    needle = q.strip().lower() if q else None

    def keep(t: Any) -> bool:
        if priority and t.priority != priority:
            return False
        if category and t.category != category:
            return False
        if assigned == "me" and t.assigned_to != principal.user_id:
            return False
        if assigned == "unassigned" and t.assigned_to is not None:
            return False
        return not needle or needle in t.subject.lower() or needle in t.ticket_number.lower()

    def key(t: Any) -> tuple[datetime, str]:
        return (t.resolution_due_at or _FAR_DUE, str(t.id))

    rows = sorted((t for t in rows if keep(t)), key=key)
    pos = _queue_cursor(cursor)
    if pos is not None:
        rows = [t for t in rows if key(t) > (pos[0], str(pos[1]))]
    more = len(rows) > limit
    rows = rows[:limit]
    full = await sv.message_counts(session, [t.id for t in rows if sc.sees_internal(t)], internal=True)
    public = await sv.message_counts(session, [t.id for t in rows if not sc.sees_internal(t)], internal=False)
    counts = {**public, **full}
    req = await sv.requester_info(session, {t.requester_id for t in rows})
    now = clock.now()
    summary = {s: 0 for s in sv.OPEN_STATUSES}
    breached = unassigned = 0
    for t in open_rows:
        summary[t.status] += 1
        unassigned += t.assigned_to is None
        rd, frd = t.resolution_due_at, t.first_response_due_at
        breached += bool((rd and now > rd) or (frd and t.first_responded_at is None and now > frd))
    return {
        "data": [
            sv.ticket_out(t, message_count=counts.get(t.id, 0), requester=req.get(t.requester_id))
            for t in rows
        ],
        "page": page_meta(
            {"due": (rows[-1].resolution_due_at or _FAR_DUE).isoformat(), "id": str(rows[-1].id)}
            if more and rows
            else None,
            limit,
        ),
        "counts": {**summary, "breached": breached, "unassigned": unassigned},
    }


# --------------------------------------------------------------------------- SUP-08 triage


@r.patch("/support/tickets/{ticket_id}")
async def patch_ticket(
    ticket_id: uuid.UUID,
    body: TicketPatch,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_permission("ticket.assign")),
) -> dict[str, Any]:
    t = await sv.load_ticket(session, ticket_id, for_update=True)
    sc = await sv.staff_scope(session, principal)
    if not sc.sees(t):
        raise ProblemError("not_found")
    fields = body.model_dump(exclude_unset=True)
    before = {k: getattr(t, k) for k in ("status", "priority", "assigned_to")}
    if fields.get("assign_to_me"):
        t.assigned_to = principal.user_id
    elif "assigned_to" in fields:
        target = body.assigned_to
        if target is not None and not await sv.user_has_platform_permission(
            session, target, "ticket.respond"
        ):
            raise _vf("assigned_to", "not_an_agent", "The assignee cannot respond to tickets")
        t.assigned_to = target
    if body.priority and body.priority != t.priority:
        t.priority = body.priority
        first_due, res_due = sv.sla_due(t.priority, t.is_grievance, t.created_at)
        t.first_response_due_at, t.resolution_due_at = first_due, res_due
    if body.status and body.status != t.status:
        if t.status == "closed":
            raise ProblemError("invalid_state_transition", current_state="closed", allowed=[])
        t.status = body.status
        now = clock.now()
        if body.status == "resolved":
            t.resolved_at = now
        elif body.status == "closed":
            t.closed_at = now
            t.resolved_at = t.resolved_at or now
        else:
            t.resolved_at = None
        await sv.add_message(
            session,
            t,
            author_id=principal.user_id,
            author_kind="system",
            body=f"Status changed to {body.status.replace('_', ' ')}.",
        )
    if "related_case_id" in fields:
        t.related_case_id = body.related_case_id
    if "related_unblock_request_id" in fields:
        if body.related_unblock_request_id is not None:
            owner, case_id = await _unblock_owner(session, principal, body.related_unblock_request_id)
            if owner != t.requester_id:
                raise _vf("related_unblock_request_id", "other_user", "That request belongs to another user")
            if "related_case_id" not in fields:
                t.related_case_id = case_id
        t.related_unblock_request_id = body.related_unblock_request_id
    await sv.save(session, t)
    await audit(
        session,
        principal,
        "support.ticket.updated",
        "support_ticket",
        t.id,
        organization_id=t.organization_id,
        subject_user_id=t.requester_id,
        before={k: str(v) if v else None for k, v in before.items()},
        after={k: str(getattr(t, k)) if getattr(t, k) else None for k in before},
    )
    return await _ticket_view(session, t, internal=sc.sees_internal(t), staff=True)


# --------------------------------------------------------------------------- SUP-09 / SUP-10


@r.post("/support/tickets/{ticket_id}/escalate")
async def escalate(
    ticket_id: uuid.UUID,
    body: EscalateIn,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_permission("ticket.escalate")),
) -> dict[str, Any]:
    t = await sv.load_ticket(session, ticket_id, for_update=True)
    sc = await sv.staff_scope(session, principal)
    if not sc.sees(t):
        raise ProblemError("not_found")
    if t.status == "closed":
        raise ProblemError("invalid_state_transition", current_state="closed", allowed=[])
    t.escalated_to = body.to
    t.status = "pending_internal"
    await sv.add_message(
        session,
        t,
        author_id=principal.user_id,
        author_kind="agent",
        visibility="internal",
        body=f"Escalated to {body.to}: {body.note.strip()}",
    )
    await sv.save(session, t)
    await audit(
        session,
        principal,
        "support.ticket.escalated",
        "support_ticket",
        t.id,
        organization_id=t.organization_id,
        subject_user_id=t.requester_id,
        after={"to": body.to},
    )
    await emit_event(
        session,
        "support.ticket_escalated",
        {"ticket_id": str(t.id), "to": body.to, "related_case_id": str(t.related_case_id or "") or None},
        aggregate_type="support_ticket",
        aggregate_id=t.id,
    )
    return await _ticket_view(session, t, internal=sc.sees_internal(t), staff=True)


@r.post("/support/tickets/{ticket_id}/merge")
async def merge(
    ticket_id: uuid.UUID,
    body: MergeIn,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_permission("ticket.assign")),
) -> dict[str, Any]:
    if body.into_ticket_id == ticket_id:
        raise _vf("into_ticket_id", "same_ticket", "Cannot merge a ticket into itself")
    src = await sv.load_ticket(session, ticket_id, for_update=True)
    dst = await sv.load_ticket(session, body.into_ticket_id, for_update=True)
    sc = await sv.staff_scope(session, principal)
    if not (sc.sees(src) and sc.sees(dst)):
        raise ProblemError("not_found")
    if src.requester_id != dst.requester_id:
        raise _vf("into_ticket_id", "different_requester", "Only tickets from the same person can be merged")
    if src.merged_into_id is not None or dst.merged_into_id is not None or dst.status == "closed":
        raise ProblemError("invalid_state_transition", current_state="merged_or_closed", allowed=[])
    now = clock.now()
    src.merged_into_id = dst.id
    src.status = "closed"
    src.closed_at = now
    src.resolved_at = src.resolved_at or now
    await sv.add_message(
        session, src, author_id=None, author_kind="system", body=f"Merged into {dst.ticket_number}."
    )
    await sv.add_message(
        session,
        dst,
        author_id=None,
        author_kind="system",
        body=f"{src.ticket_number} was merged into this ticket.",
    )
    await sv.save(session, src, dst)
    await audit(
        session,
        principal,
        "support.ticket.merged",
        "support_ticket",
        src.id,
        organization_id=src.organization_id,
        subject_user_id=src.requester_id,
        after={"into": str(dst.id)},
    )
    return await _ticket_view(session, dst, internal=sc.sees_internal(dst), staff=True)


# --------------------------------------------------------------------------- SUP-11 user lookup


LEVEL_TEXT = {
    1: "Extra verification is needed when signing in on a new device.",
    2: "Some features are limited while we review recent sign-in activity.",
    3: "Access is paused while the security team reviews the account.",
    4: "The account is suspended pending a security review.",
}


def _reason(code: str | None) -> str:
    if not code or code not in REASON_CODES:
        raise ProblemError("reason_code_required", allowed_reason_codes=list(REASON_CODES))
    return code


async def _ticket_ref(session: Any, ticket_id: uuid.UUID | None, user_id: uuid.UUID) -> None:
    if ticket_id is None:
        return
    t: Any
    if sv.on_firestore():
        t = await (await sv.fs_repo(session)).get_ticket(None, ticket_id)
    else:
        t = await session.get(SupportTicket, ticket_id)
    if t is None or t.requester_id != user_id:
        raise _vf("ticket_id", "not_found", "Ticket not found for this user")


async def _target(session: Any, user_id: uuid.UUID) -> User:
    from app.modules.identity import public as identity

    u = await identity.get_user(session, user_id)
    if u is None or u.status == "deleted":
        raise ProblemError("not_found")
    return u


@r.get("/support/users/{user_id}", openapi_extra=NEUTRAL)
async def user_lookup(
    user_id: uuid.UUID,
    session: PrincipalDbSession,
    reason_code: str | None = None,
    ticket_id: uuid.UUID | None = None,
    principal: Principal = Depends(require_permission("user.read")),
) -> dict[str, Any]:
    code = _reason(reason_code)
    u = await _target(session, user_id)
    await _ticket_ref(session, ticket_id, user_id)
    from app.modules.commerce import public as commerce
    from app.modules.entitlements import public as entitlements
    from app.modules.identity import public as identity
    from app.modules.security import public as security
    from app.modules.sessions import public as sessions
    from app.modules.sessions.ua import mask_ip

    prof = await identity.get_profile(session, u.id)
    now = clock.now()
    # active restriction with the highest level, then the latest start (security orders it)
    active = await security.user_restrictions(session, u.id, active_only=True)
    restr = active[0] if active else None
    devices = [
        (d.trust_status,) for d in await sessions.list_user_devices(session, user_id=u.id, not_removed=True)
    ]
    # ORDER BY last_seen_at DESC (Postgres puts NULLs first) LIMIT 20
    sess = sorted(
        await sessions.list_sessions(session, user_id=u.id, status="active"),
        key=lambda s: (s.last_seen_at is None, s.last_seen_at or now),
        reverse=True,
    )[:20]
    ents = sorted(
        await entitlements.user_entitlements(session, u.id), key=lambda e: e.starts_at, reverse=True
    )[:20]
    orders = await commerce.recent_orders(session, u.id, 10)
    notes, tickets = await _notes_and_tickets(session, u.id)
    mfa = sum(1 for f in await identity.active_factors(session, u.id) if f.factor_type != "recovery_codes")
    level = restr.level if restr else (u.restriction_level or 0)
    # Visibility tier: minors' names are reduced to the first name for every staff viewer.
    name = (prof.display_name or prof.full_name) if prof else None
    if name and u.is_minor:
        name = name.split()[0]
    await audit(
        session,
        principal,
        "support.user_lookup",
        "user",
        u.id,
        subject_user_id=u.id,
        reason_code=code,
        after={"ticket_id": str(ticket_id) if ticket_id else None},
    )

    def ts(v: Any) -> str | None:
        return to_rfc3339(v) if v else None

    return {
        "user_id": str(u.id),
        "display_name": name,
        "email_masked": mask_email(u.email),
        "phone_masked": mask_phone(u.phone_e164),
        "status": u.status,
        "privacy_tier": u.privacy_tier,
        "is_minor": u.is_minor,
        "email_verified": u.email_verified_at is not None,
        "phone_verified": u.phone_verified_at is not None,
        "created_at": ts(u.created_at),
        "last_login_at": ts(u.last_login_at),
        "mfa_enrolled": bool(mfa),
        "restriction": {
            "level": level,
            "reason_text": LEVEL_TEXT.get(level, ""),
            "since": ts(restr.starts_at) if restr else None,
        }
        if level
        else None,
        "devices": {"trusted_count": sum(1 for (s,) in devices if s == "trusted"), "total": len(devices)},
        "active_sessions": [
            {
                "session_id": str(s.id),
                "device_label": f"{s.ua_family or 'Browser'} on {s.os_family or 'unknown OS'}",
                "approx_region": s.geo_region,
                "ip_masked": mask_ip(str(s.ip_last)) if s.ip_last else None,
                "last_active_at": ts(s.last_seen_at),
            }
            for s in sess
            if s.absolute_expires_at > now
        ],
        "entitlements": [
            {
                "entitlement_id": str(e.id),
                "kind": "course"
                if e.course_id
                else (f"feature:{e.feature_key}" if e.feature_key else "product"),
                "status": e.status,
                "ends_at": ts(e.ends_at),
            }
            for e in ents
        ],
        "recent_orders": [
            {
                "order_number": o.order_number,
                "status": o.status,
                "total_paise": o.total_paise,
                "created_at": ts(o.created_at),
            }
            for o in orders
        ],
        "notes": [_note_out(n) for n in notes],
        "tickets": [
            {
                "ticket_id": str(t.id),
                "ticket_number": t.ticket_number,
                "subject": t.subject,
                "status": t.status,
                "created_at": ts(t.created_at),
            }
            for t in tickets
        ],
    }


async def _notes_and_tickets(session: Any, user_id: uuid.UUID) -> tuple[list[Any], list[Any]]:
    """The 50 newest notes and 20 newest tickets of a user (SUP-11), either store."""
    if sv.on_firestore():
        repo = await sv.fs_repo(session)
        tickets, _ = await repo.tickets_of(user_id, limit=20, order=("created_at", "desc"))
        return await repo.notes_for(user_id, 50), tickets
    notes = (
        (
            await session.execute(
                select(SupportUserNote)
                .where(SupportUserNote.user_id == user_id)
                .order_by(SupportUserNote.created_at.desc())
                .limit(50)
            )
        )
        .scalars()
        .all()
    )
    tickets = (
        (
            await session.execute(
                select(SupportTicket)
                .where(SupportTicket.requester_id == user_id)
                .order_by(SupportTicket.created_at.desc())
                .limit(20)
            )
        )
        .scalars()
        .all()
    )
    return list(notes), list(tickets)


def _note_out(n: Any) -> dict[str, Any]:
    return {
        "note_id": str(n.id),
        "body": n.body,
        "author_id": str(n.author_id),
        "ticket_id": str(n.support_ticket_id) if n.support_ticket_id else None,
        "created_at": to_rfc3339(n.created_at),
    }


async def _tokens_last_day(session: Any, model: Any, user_id: uuid.UUID, **filters: Any) -> int:
    """Links issued to a user in the last 24 h (identity token tables; system context)."""
    from app.modules.identity import public as identity

    since = clock.now() - timedelta(days=1)
    if model == "verification":
        rows: Any = await identity.verification_tokens_of(session, user_id, created_after=since, **filters)
    else:
        rows = await identity.reset_tokens_of(session, user_id, created_after=since)
    return len(rows)


@r.post("/support/users/{user_id}/resend-verification", status_code=202)
async def resend_verification(
    user_id: uuid.UUID,
    body: SupportActionIn,
    request: Request,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_permission("user.read")),
) -> JSONResponse:
    code = _reason(body.reason_code)

    async def op() -> IdemResult:
        u = await _target(session, user_id)
        await _ticket_ref(session, body.ticket_id, user_id)
        if not u.email or u.email_verified_at is not None:
            raise ProblemError("invalid_state_transition", current_state="verified", allowed=[])
        from app.modules.identity.router import send_verification_email

        async with system_context(session, "support.resend_verification"):
            if await _tokens_last_day(session, "verification", u.id, purpose="email_verify") >= 5:
                raise ProblemError("rate_limited", headers={"Retry-After": "86400"})
            await send_verification_email(session, u, None)
            await session.flush()
        await audit(
            session,
            principal,
            "support.verification_resent",
            "user",
            u.id,
            subject_user_id=u.id,
            reason_code=code,
        )
        return IdemResult(status=202, body={"status": "sent", "sent_to": mask_email(u.email)})

    return await idempotent(request, session, user_id=principal.user_id, operation=op, required=False)


@r.post("/support/users/{user_id}/password-reset-email", status_code=202)
async def password_reset_email(
    user_id: uuid.UUID,
    body: SupportActionIn,
    request: Request,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_permission("user.read")),
) -> JSONResponse:
    code = _reason(body.reason_code)
    window = 300 if principal.tier == "privileged" else 600
    if not within(principal.last_step_up_at, timedelta(seconds=window), now=clock.now()):
        from app.modules.identity.router import step_up_problem

        p = step_up_problem(principal, window)
        if p:
            raise p

    async def op() -> IdemResult:
        u = await _target(session, user_id)
        await _ticket_ref(session, body.ticket_id, user_id)
        if not u.email:
            raise _vf("user_id", "no_email", "The account has no email address")
        from app.modules.identity.router import issue_password_reset

        async with system_context(session, "support.password_reset"):
            if await _tokens_last_day(session, "reset", u.id) >= 3:
                raise ProblemError("rate_limited", headers={"Retry-After": "86400"})
            sent = await issue_password_reset(session, u, ip=None, actor=principal)
            await session.flush()
        if not sent:
            raise ProblemError("rate_limited", headers={"Retry-After": "3600"})
        await audit(
            session,
            principal,
            "support.password_reset_sent",
            "user",
            u.id,
            subject_user_id=u.id,
            reason_code=code,
        )
        return IdemResult(status=202, body={"status": "sent", "sent_to": mask_email(u.email)})

    return await idempotent(request, session, user_id=principal.user_id, operation=op, required=False)


@r.post("/support/users/{user_id}/notes", status_code=201)
async def add_note(
    user_id: uuid.UUID,
    body: NoteIn,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_permission("ticket.respond")),
) -> dict[str, Any]:
    await _target(session, user_id)
    await _ticket_ref(session, body.ticket_id, user_id)
    fields: dict[str, Any] = {
        "id": uuid7(),
        "user_id": user_id,
        "author_id": principal.user_id,
        "support_ticket_id": body.ticket_id,
        "body": body.body.strip(),
        "created_at": clock.now(),
    }
    n: Any
    if sv.on_firestore():
        from app.modules.support.repo_firestore import NoteRow

        n = await (await sv.fs_repo(session)).add_note(NoteRow(**fields))
    else:
        n = SupportUserNote(**fields)
        session.add(n)
        await session.flush()
    await audit(session, principal, "support.user_note_added", "user", user_id, subject_user_id=user_id)
    return _note_out(n)


# --------------------------------------------------------------------------- SUP-15 macros

MACROS = [
    {
        "macro_id": "device-limit",
        "title": "Device limit reached",
        "category": "device_reset",
        "body": "You can keep a limited number of trusted devices. Open Settings → Devices, remove "
        "one you no "
        "longer use, then sign in again on the new device. If you can't reach an old device, reply here "
        "and we'll reset it for you.",
    },
    {
        "macro_id": "verify-email",
        "title": "Verification email",
        "category": "account_access",
        "body": "We've sent a fresh verification link to your email. It expires in 24 hours — "
        "please also check "
        "your spam folder.",
    },
    {
        "macro_id": "password-reset",
        "title": "Password reset link",
        "category": "account_access",
        "body": "We've sent you a password-reset link. Support can never see or set your password. The link "
        "works once and expires soon.",
    },
    {
        "macro_id": "refund-timeline",
        "title": "Refund timeline",
        "category": "refund",
        "body": "Approved refunds reach the original payment method within 5-7 working days. We'll "
        "update this "
        "ticket when the bank confirms.",
    },
    {
        "macro_id": "account-review",
        "title": "Account under review",
        "category": "account_access",
        "body": "Your account is being reviewed by our security team. You can follow the review from Account "
        "status. Support cannot change the outcome, but we'll keep this ticket updated.",
    },
    {
        "macro_id": "resolved",
        "title": "Marking as resolved",
        "category": "other",
        "body": "I'm marking this ticket as resolved. If anything is still not working, reply "
        "within 7 days and "
        "it will reopen automatically.",
    },
]


@r.get("/support/macros", openapi_extra=NEUTRAL)
async def macros(principal: Principal = Depends(require_active_principal)) -> dict[str, Any]:
    allowed = await check_permission(principal, "ticket.respond", PLATFORM_SCOPE)
    if not allowed:
        raise ProblemError("permission_denied", permission="ticket.respond")
    return {"data": MACROS}


router = APIRouter()
router.include_router(r)

# D8: public corporate enquiry form + the Admin enquiry queue (no main.py change needed).
from app.modules.support.enquiries import router as _enquiries_router  # noqa: E402

router.include_router(_enquiries_router)


# DB-01: register this module's erasure provider with admin privacy (import-time registration).
from app.modules.support import privacy as _privacy  # noqa: E402

_privacy.register()
