"""DB-01: support erasure provider (privacy D13: support tickets are kept 3 years as a legal
hold, so they are reduced to a minimal form instead of deleted). Registered when the support
router is imported.

* ``support_tickets`` requested by the user: subject/body replaced, context (route, browser,
  attachments) and CSAT comment cleared. Category, status, timestamps and SLA facts stay.
* ``support_ticket_messages`` written by the user (and every message of their tickets that
  carries attachments): marked ``redacted_at`` with the body replaced and attachments dropped
  (td_app has no DELETE on messages; the API already renders redacted messages as such).
* ``support_user_notes`` (staff notes about the user) are append-only (no UPDATE/DELETE for
  td_app) and are kept under the same 3-year support hold; reported as ``user_notes_retained``.

Idempotent. Caller supplies a system context."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time import utcnow
from app.modules.support.models import SupportTicket, SupportTicketMessage, SupportUserNote

ERASED_SUBJECT = "[erased]"
ERASED_BODY = "[erased]"


def _n(result: Any) -> int:
    return int(getattr(result, "rowcount", 0) or 0)


async def erase_user(session: AsyncSession, user_id: uuid.UUID) -> dict[str, Any]:
    own_tickets = select(SupportTicket.id).where(SupportTicket.requester_id == user_id)
    msgs = await session.execute(
        update(SupportTicketMessage)
        .where(
            SupportTicketMessage.redacted_at.is_(None),
            or_(
                SupportTicketMessage.author_id == user_id,
                (SupportTicketMessage.support_ticket_id.in_(own_tickets))
                & (func.jsonb_array_length(SupportTicketMessage.attachments) > 0),
            ),
        )
        .values(body=ERASED_BODY, attachments=[], redacted_at=utcnow())
        .execution_options(synchronize_session=False)
    )
    tickets = await session.execute(
        update(SupportTicket)
        .where(SupportTicket.requester_id == user_id, SupportTicket.subject != ERASED_SUBJECT)
        .values(subject=ERASED_SUBJECT, body=ERASED_BODY, context={}, csat_comment=None)
        .execution_options(synchronize_session=False)
    )
    notes = (
        await session.execute(select(func.count()).where(SupportUserNote.user_id == user_id))
    ).scalar_one()
    await session.flush()
    return {
        "tickets_minimised": _n(tickets),
        "messages_redacted": _n(msgs),
        "user_notes_retained": int(notes),
    }


def register() -> None:
    from app.modules.admin.privacy import register_erasure_provider

    register_erasure_provider("support", erase_user)
