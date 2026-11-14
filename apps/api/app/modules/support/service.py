"""Support desk domain logic: SLA clocks, visibility scopes, ticket/message serialisation.

Storage: Postgres, or Firestore with ``TD_STORE_SUPPORT=firestore`` (``repo_firestore``). The
functions below are backend-neutral: tickets are ORM rows or ``TicketRow`` (same attributes);
callers mutate them and then ``save`` (a flush on Postgres, one optimistic transaction on
Firestore)."""

from __future__ import annotations

import functools
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import PLATFORM_SCOPE
from app.core.errors import ProblemError
from app.core.firestore.backend import uses_firestore
from app.core.ids import uuid7
from app.core.principal import Principal
from app.core.time import to_rfc3339
from app.modules.identity import clock
from app.modules.identity.contacts import mask_email
from app.modules.rbac import service as rs
from app.modules.support.models import SupportTicket, SupportTicketMessage

CATEGORIES = (
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
)
STATUSES = ("open", "pending_user", "pending_internal", "resolved", "closed")
PRIORITIES = ("low", "normal", "high", "urgent")
OPEN_STATUSES = ("open", "pending_user", "pending_internal")
ESCALATION_TARGETS = ("finance", "security", "content")

# Service levels (hours) per priority: first response / resolution. Grievances follow the
# DPDP / consumer-protection clock: acknowledgement 48 h, resolution 30 days.
FIRST_RESPONSE_H = {"urgent": 1, "high": 4, "normal": 24, "low": 48}
RESOLUTION_H = {"urgent": 8, "high": 24, "normal": 72, "low": 120}
GRIEVANCE_FIRST_H = 48
GRIEVANCE_RESOLUTION_H = 30 * 24
DEFAULT_PRIORITY = {"account_access": "high", "device_reset": "high", "appeal": "high", "refund": "normal"}
# FR-SUP-003 P1 ("cannot access paid content, or test in progress") maps to ``high`` (first
# response 4 h). Access-loss categories are already ``high`` by default; an ``assessment``
# ticket is raised to ``high`` when the requester has a test attempt in progress
# (``derive_priority``). Business-hours clocks are not applied: no business calendar
# (working days, hours, holidays, timezone) is defined in the docs, so SLAs stay in
# calendar hours (documented in docs/audit/fixes/learn.md, BE-32).
AUTO_CLOSE_AFTER = timedelta(days=7)

# Platform staff see tickets in their lane (API §22 SUP-07). Single company (owner decision D2):
# the former support/finance/security roles are folded into Admin (``super_admin``), which sees
# every category; content managers keep their content lane. There is no organization lane.
ROLE_CATEGORIES: dict[str, frozenset[str] | None] = {
    "super_admin": None,
    "content_manager": frozenset({"content", "assessment", "certificate"}),
}
ROLE_ESCALATION = {"content_manager": "content"}
# Live audit 2026-11-14 (F3): no Studio screen lists tickets, so content-lane tickets and tickets
# escalated to "content" are worked by Admin in the Admin Support queue (Admin sees every
# category). The content manager keeps its lane permissions (API only) for when a Studio
# "Content tickets" view is built; the lane exposes nothing outside content/assessment/certificate.


def sla_due(priority: str, is_grievance: bool, start: datetime) -> tuple[datetime, datetime]:
    if is_grievance:
        return start + timedelta(hours=GRIEVANCE_FIRST_H), start + timedelta(hours=GRIEVANCE_RESOLUTION_H)
    return start + timedelta(hours=FIRST_RESPONSE_H[priority]), start + timedelta(
        hours=RESOLUTION_H[priority]
    )


async def derive_priority(session: AsyncSession, user_id: uuid.UUID, category: str) -> str:
    """Initial priority from the ticket context (FR-SUP-003): P1 (= ``high``) when the requester
    cannot reach paid content (access categories) or has a test attempt in progress."""
    priority = DEFAULT_PRIORITY.get(category, "normal")
    if category == "assessment" and priority != "high":
        from app.modules.assessments import public as assessments

        if await assessments.has_attempt_in_progress(session, user_id):
            priority = "high"
    return priority


def ticket_number(n: int) -> str:
    return f"TD-T-{clock.now().year}-{int(n):06d}"


async def next_ticket_number(session: AsyncSession) -> str:
    n = (await session.execute(text("SELECT nextval('support_ticket_number_seq')"))).scalar_one()
    return ticket_number(int(n))


on_firestore = functools.partial(uses_firestore, "support")


async def fs_repo(session: AsyncSession, job: str = "support.desk") -> Any:
    """The Firestore repository bound to the caller's RLS scope (``app.user_id``/``is_platform``)."""
    from app.core.db import rls_scope
    from app.modules.support.repo_firestore import repo

    return repo(await rls_scope(session), job)


def new_ticket(**kw: Any) -> Any:
    """An unsaved ticket (ORM row, or ``TicketRow`` on Firestore); ``insert_ticket`` numbers it."""
    if on_firestore():
        from app.modules.support.repo_firestore import TicketRow

        return TicketRow(ticket_number="", **kw)
    return SupportTicket(**kw)


async def insert_ticket(session: AsyncSession, t: Any) -> Any:
    """Insert with the next gap-free ticket number (the number commits with the row)."""
    if on_firestore():
        return await (await fs_repo(session)).insert_ticket(t.requester_id, t, ticket_number)
    t.ticket_number = await next_ticket_number(session)
    session.add(t)
    await session.flush()
    return t


async def save(session: AsyncSession, *tickets: Any) -> None:
    """Persist changes made to loaded tickets (and their queued messages)."""
    if on_firestore():
        await (await fs_repo(session)).save(None, tickets)
        return
    await session.flush()


# --------------------------------------------------------------------------- staff scope


@dataclass
class StaffScope:
    """What a staff principal may see / do on tickets: the platform lane only (``ticket.*`` @P,
    by role category / escalation). Internal notes are visible to every viewer in the lane."""

    all_categories: bool = False
    categories: set[str] = field(default_factory=set)
    escalations: set[str] = field(default_factory=set)
    platform_can_respond: bool = False
    can_assign: bool = False
    can_escalate: bool = False

    @property
    def any(self) -> bool:
        return self.all_categories or bool(self.categories or self.escalations)

    @property
    def can_respond(self) -> bool:
        return self.platform_can_respond

    def platform_sees(self, t: SupportTicket) -> bool:
        if self.all_categories or t.category in self.categories:
            return True
        return bool(t.escalated_to and t.escalated_to in self.escalations)

    def sees(self, t: SupportTicket) -> bool:
        return self.platform_sees(t)

    def sees_internal(self, t: SupportTicket) -> bool:
        """Internal notes are platform-staff only."""
        return self.platform_sees(t)

    def can_respond_on(self, t: SupportTicket) -> bool:
        return self.platform_sees(t) and self.platform_can_respond


async def staff_scope(session: AsyncSession, principal: Principal) -> StaffScope:
    sc = StaffScope()
    if await rs.check_permission(session, principal, "ticket.read", PLATFORM_SCOPE):
        for g in principal.grants:
            if g.scope_type != "platform" or g.role not in ROLE_CATEGORIES:
                continue
            cats = ROLE_CATEGORIES[g.role]
            if cats is None:
                sc.all_categories = True
            else:
                sc.categories |= cats
            if g.role in ROLE_ESCALATION:
                sc.escalations.add(ROLE_ESCALATION[g.role])
        sc.platform_can_respond = await rs.check_permission(
            session, principal, "ticket.respond", PLATFORM_SCOPE
        )
        sc.can_assign = await rs.check_permission(session, principal, "ticket.assign", PLATFORM_SCOPE)
        sc.can_escalate = await rs.check_permission(session, principal, "ticket.escalate", PLATFORM_SCOPE)
    return sc


async def user_has_platform_permission(session: AsyncSession, user_id: uuid.UUID, permission: str) -> bool:
    perms = await rs.role_permission_map(session)
    return any(
        g.scope_type == "platform" and permission in perms.get(g.role, frozenset())
        for g in await rs.active_grants(session, user_id)
    )


# --------------------------------------------------------------------------- loading


async def load_ticket(
    session: AsyncSession, ticket_id: uuid.UUID, *, for_update: bool = False
) -> SupportTicket:
    if on_firestore():
        row = await (await fs_repo(session)).get_ticket(None, ticket_id)
        if row is None:
            raise ProblemError("not_found")
        return row  # type: ignore[no-any-return,unused-ignore]
    q = select(SupportTicket).where(SupportTicket.id == ticket_id)
    if for_update:
        q = q.with_for_update()
    t = (await session.execute(q)).scalar_one_or_none()
    if t is None:
        raise ProblemError("not_found")
    return t


async def add_message(
    session: AsyncSession,
    t: Any,
    *,
    author_id: uuid.UUID | None,
    author_kind: str,
    body: str,
    visibility: str = "public",
    attachments: list[dict[str, Any]] | None = None,
) -> SupportTicketMessage:
    if on_firestore():
        from app.modules.support.repo_firestore import new_message

        fm = new_message(
            t,
            author_id=author_id,
            author_kind=author_kind,
            visibility=visibility,
            body=body,
            attachments=list(attachments or []),
            created_at=clock.now(),
        )
        t._new_messages.append(fm)
        t.last_message_at = fm.created_at
        return fm  # type: ignore[return-value]
    m = SupportTicketMessage(
        id=uuid7(),
        support_ticket_id=t.id,
        organization_id=t.organization_id,
        author_id=author_id,
        author_kind=author_kind,
        visibility=visibility,
        body=body,
        attachments=list(attachments or []),
        created_at=clock.now(),
    )
    session.add(m)
    t.last_message_at = m.created_at
    await session.flush()
    return m


async def message_counts(
    session: AsyncSession, ids: list[uuid.UUID], *, internal: bool
) -> dict[uuid.UUID, int]:
    if not ids:
        return {}
    if on_firestore():
        counts: dict[uuid.UUID, int] = await (await fs_repo(session)).message_counts(
            None, ids, internal=internal
        )
        return counts
    q = select(SupportTicketMessage.support_ticket_id, func.count()).where(
        SupportTicketMessage.support_ticket_id.in_(ids)
    )
    if not internal:
        q = q.where(SupportTicketMessage.visibility == "public")
    rows = (await session.execute(q.group_by(SupportTicketMessage.support_ticket_id))).all()
    return {r[0]: int(r[1]) for r in rows}


async def requester_info(session: AsyncSession, ids: set[uuid.UUID]) -> dict[uuid.UUID, dict[str, Any]]:
    if not ids:
        return {}
    from app.modules.identity import public as identity

    rows = list((await identity.user_cards(session, ids)).values())
    return {
        r.id: {
            "user_id": str(r.id),
            "display_name": r.display_name or (r.full_name.split()[0] if r.full_name else None),
            "email_masked": mask_email(r.email),
        }
        for r in rows
    }


# --------------------------------------------------------------------------- serialisation


def _ts(v: datetime | None) -> str | None:
    return to_rfc3339(v) if v else None


def _sid(v: uuid.UUID | None) -> str | None:
    return str(v) if v else None


def _breached(due: datetime | None, done: datetime | None, open_: bool, now: datetime) -> bool:
    if due is None:
        return False
    if done is not None:
        return done > due
    return open_ and now > due


def ticket_out(
    t: SupportTicket, *, message_count: int = 0, requester: dict[str, Any] | None = None
) -> dict[str, Any]:
    now = clock.now()
    open_ = t.status in OPEN_STATUSES
    out: dict[str, Any] = {
        "ticket_id": str(t.id),
        "ticket_number": t.ticket_number,
        "requester_id": str(t.requester_id),
        "category": t.category,
        "subject": t.subject,
        "body": t.body,
        "status": t.status,
        "priority": t.priority,
        "assigned_to": _sid(t.assigned_to),
        "is_grievance": t.is_grievance,
        "escalated_to": t.escalated_to,
        "merged_into_id": _sid(t.merged_into_id),
        "related_order_id": _sid(t.related_order_id),
        "related_case_id": _sid(t.related_case_id),
        "related_unblock_request_id": _sid(t.related_unblock_request_id),
        "related_attempt_id": (t.context or {}).get("attempt_id"),
        "first_response_due_at": _ts(t.first_response_due_at),
        "resolution_due_at": _ts(t.resolution_due_at),
        "first_responded_at": _ts(t.first_responded_at),
        "resolved_at": _ts(t.resolved_at),
        "closed_at": _ts(t.closed_at),
        "created_at": _ts(t.created_at),
        "updated_at": _ts(t.updated_at),
        "sla": {
            "first_response_breached": _breached(t.first_response_due_at, t.first_responded_at, open_, now),
            "resolution_breached": _breached(t.resolution_due_at, t.resolved_at, open_, now),
        },
        "csat_score": t.csat_score,
        "message_count": message_count,
        "attachments": [
            {
                "filename": a.get("filename"),
                "content_type": a.get("content_type"),
                "size_bytes": a.get("size_bytes"),
            }
            for a in ((t.context or {}).get("attachments") or [])
            if isinstance(a, dict)
        ],
    }
    if requester is not None:
        out["requester"] = requester
    return out


def message_out(m: SupportTicketMessage) -> dict[str, Any]:
    return {
        "message_id": str(m.id),
        "author_kind": m.author_kind,
        "author_id": _sid(m.author_id),
        "visibility": m.visibility,
        "body": "[redacted]" if m.redacted_at else m.body,
        "attachments": []
        if m.redacted_at
        else [
            {
                "filename": a.get("filename"),
                "content_type": a.get("content_type"),
                "size_bytes": a.get("size_bytes"),
            }
            for a in (m.attachments or [])
            if isinstance(a, dict)
        ],
        "created_at": _ts(m.created_at),
    }


# --------------------------------------------------------------------------- background job


async def auto_close_resolved(session: AsyncSession) -> int:
    """Resolved tickets with no reopen within ``AUTO_CLOSE_AFTER`` become ``closed``."""
    from app.core.audit import AuditActor, audit

    cutoff = clock.now() - AUTO_CLOSE_AFTER
    if on_firestore():
        return await _auto_close_firestore(session, cutoff)
    rows = (
        (
            await session.execute(
                select(SupportTicket)
                .where(SupportTicket.status == "resolved", SupportTicket.resolved_at <= cutoff)
                .with_for_update(skip_locked=True)
                .limit(500)
            )
        )
        .scalars()
        .all()
    )
    for t in rows:
        t.status = "closed"
        t.closed_at = clock.now()
        await add_message(
            session, t, author_id=None, author_kind="system", body="Ticket closed automatically after 7 days."
        )
        await audit(
            session,
            AuditActor.system("support.auto_close"),
            "support.ticket.auto_closed",
            "support_ticket",
            t.id,
            organization_id=t.organization_id,
            subject_user_id=t.requester_id,
        )
    return len(rows)


async def _auto_close_firestore(session: AsyncSession, cutoff: datetime) -> int:
    """Firestore ``auto_close``: a ticket changed concurrently is skipped (``SKIP LOCKED``) and
    picked up by the next hourly run."""
    from app.core.audit import AuditActor, audit

    repo = await fs_repo(session, "support.auto_close")
    closed = 0
    for t in await repo.resolved_before(cutoff, 500):
        t.status = "closed"
        t.closed_at = clock.now()
        await add_message(
            session, t, author_id=None, author_kind="system", body="Ticket closed automatically after 7 days."
        )
        try:
            await repo.save(None, [t])
        except ProblemError as e:
            if e.code != "conflict":
                raise
            continue
        closed += 1
        await audit(
            session,
            AuditActor.system("support.auto_close"),
            "support.ticket.auto_closed",
            "support_ticket",
            t.id,
            organization_id=t.organization_id,
            subject_user_id=t.requester_id,
        )
    return closed


async def dashboard_counts(session: AsyncSession, now: datetime) -> dict[str, int]:
    """Open / SLA-breached / unassigned ticket counts (admin dashboard; caller is platform)."""
    if on_firestore():
        rows = await (await fs_repo(session, "support.dashboard")).open_tickets(OPEN_STATUSES)
        return {
            "open": len(rows),
            "breached": sum(
                1
                for t in rows
                if (t.resolution_due_at is not None and t.resolution_due_at < now)
                or (
                    t.first_responded_at is None
                    and t.first_response_due_at is not None
                    and t.first_response_due_at < now
                )
            ),
            "unassigned": sum(1 for t in rows if t.assigned_to is None),
        }
    from sqlalchemy import or_

    async def n(*conds: Any) -> int:
        q = select(func.count()).select_from(SupportTicket).where(*conds)
        return int((await session.execute(q)).scalar_one())

    is_open = SupportTicket.status.in_(OPEN_STATUSES)
    return {
        "open": await n(is_open),
        "breached": await n(
            is_open,
            or_(
                SupportTicket.resolution_due_at < now,
                (SupportTicket.first_responded_at.is_(None)) & (SupportTicket.first_response_due_at < now),
            ),
        ),
        "unassigned": await n(is_open, SupportTicket.assigned_to.is_(None)),
    }
