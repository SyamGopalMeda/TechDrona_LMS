"""Support desk domain logic: SLA clocks, visibility scopes, ticket/message serialisation."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import PLATFORM_SCOPE
from app.core.errors import ProblemError
from app.core.ids import uuid7
from app.core.principal import Principal
from app.core.time import to_rfc3339
from app.modules.identity import clock
from app.modules.identity.contacts import mask_email
from app.modules.identity.models import User, UserProfile
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
        from app.modules.assessments.models import TestAttempt

        running = (
            await session.execute(
                select(TestAttempt.id)
                .where(TestAttempt.user_id == user_id, TestAttempt.status == "in_progress")
                .limit(1)
            )
        ).scalar_one_or_none()
        if running is not None:
            priority = "high"
    return priority


async def next_ticket_number(session: AsyncSession) -> str:
    n = (await session.execute(text("SELECT nextval('support_ticket_number_seq')"))).scalar_one()
    return f"TD-T-{clock.now().year}-{int(n):06d}"


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
    q = select(SupportTicket).where(SupportTicket.id == ticket_id)
    if for_update:
        q = q.with_for_update()
    t = (await session.execute(q)).scalar_one_or_none()
    if t is None:
        raise ProblemError("not_found")
    return t


async def add_message(
    session: AsyncSession,
    t: SupportTicket,
    *,
    author_id: uuid.UUID | None,
    author_kind: str,
    body: str,
    visibility: str = "public",
    attachments: list[dict[str, Any]] | None = None,
) -> SupportTicketMessage:
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
    rows = (
        await session.execute(
            select(User.id, User.email, UserProfile.full_name, UserProfile.display_name)
            .outerjoin(UserProfile, UserProfile.user_id == User.id)
            .where(User.id.in_(ids))
        )
    ).all()
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
