"""Support tables (database-schema §14; migration support_0001)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, SmallInteger, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

_TS = DateTime(timezone=True)
_U = UUID(as_uuid=True)


class SupportTicket(Base):
    __tablename__ = "support_tickets"

    id: Mapped[uuid.UUID] = mapped_column(_U, primary_key=True)
    ticket_number: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    requester_id: Mapped[uuid.UUID] = mapped_column(_U, ForeignKey("users.id"), nullable=False)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(_U)
    category: Mapped[str] = mapped_column(Text, nullable=False)
    subject: Mapped[str] = mapped_column(Text, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="open")
    priority: Mapped[str] = mapped_column(Text, nullable=False, server_default="normal")
    assigned_to: Mapped[uuid.UUID | None] = mapped_column(_U)
    related_order_id: Mapped[uuid.UUID | None] = mapped_column(_U)
    related_case_id: Mapped[uuid.UUID | None] = mapped_column(_U)
    related_unblock_request_id: Mapped[uuid.UUID | None] = mapped_column(_U)
    privacy_request_id: Mapped[uuid.UUID | None] = mapped_column(_U)
    is_grievance: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    escalated_to: Mapped[str | None] = mapped_column(Text)
    merged_into_id: Mapped[uuid.UUID | None] = mapped_column(_U)
    context: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    first_response_due_at: Mapped[datetime | None] = mapped_column(_TS)
    resolution_due_at: Mapped[datetime | None] = mapped_column(_TS)
    first_responded_at: Mapped[datetime | None] = mapped_column(_TS)
    resolved_at: Mapped[datetime | None] = mapped_column(_TS)
    closed_at: Mapped[datetime | None] = mapped_column(_TS)
    last_message_at: Mapped[datetime | None] = mapped_column(_TS)
    csat_score: Mapped[int | None] = mapped_column(SmallInteger)
    csat_comment: Mapped[str | None] = mapped_column(Text)
    csat_at: Mapped[datetime | None] = mapped_column(_TS)
    created_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())


class SupportTicketMessage(Base):
    __tablename__ = "support_ticket_messages"

    id: Mapped[uuid.UUID] = mapped_column(_U, primary_key=True)
    support_ticket_id: Mapped[uuid.UUID] = mapped_column(
        _U, ForeignKey("support_tickets.id", ondelete="CASCADE"), nullable=False
    )
    organization_id: Mapped[uuid.UUID | None] = mapped_column(_U)
    author_id: Mapped[uuid.UUID | None] = mapped_column(_U)
    author_kind: Mapped[str] = mapped_column(Text, nullable=False)
    visibility: Mapped[str] = mapped_column(Text, nullable=False, server_default="public")
    body: Mapped[str] = mapped_column(Text, nullable=False)
    attachments: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, server_default="[]")
    redacted_at: Mapped[datetime | None] = mapped_column(_TS)
    created_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())


class SupportUserNote(Base):
    __tablename__ = "support_user_notes"

    id: Mapped[uuid.UUID] = mapped_column(_U, primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(_U, ForeignKey("users.id"), nullable=False)
    author_id: Mapped[uuid.UUID] = mapped_column(_U, nullable=False)
    support_ticket_id: Mapped[uuid.UUID | None] = mapped_column(_U)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())


class CorporateEnquiry(Base):
    """Public corporate enquiry form (owner decision D8; migration support_0004). Platform-only RLS."""

    __tablename__ = "corporate_enquiries"

    id: Mapped[uuid.UUID] = mapped_column(_U, primary_key=True)
    reference: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    company: Mapped[str] = mapped_column(Text, nullable=False)
    email: Mapped[str] = mapped_column(Text, nullable=False)
    phone: Mapped[str | None] = mapped_column(Text)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    consent_at: Mapped[datetime] = mapped_column(_TS, nullable=False)
    notice_version: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="new")
    assigned_to: Mapped[uuid.UUID | None] = mapped_column(_U, ForeignKey("users.id"))
    staff_note: Mapped[str | None] = mapped_column(Text)
    closed_at: Mapped[datetime | None] = mapped_column(_TS)
    created_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())
