"""Issued documents (letters + the extra certificate types), their wording overrides and the
document settings (migration ``learning_0006``).

Course completion certificates of LMS enrolments stay in ``certificates`` (one per enrolment,
progress rule, ``public_code``); ``issued_documents`` holds everything else the company issues:
offer / admission letters, recommendation letters, and internship / appreciation / participation
certificates and completion certificates for programmes run outside an LMS enrolment. Both are
verifiable on the same public page and emailed through the same ``certificate_outbox``.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, LargeBinary, SmallInteger, Text, func
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

_TS = DateTime(timezone=True)
_UUID = UUID(as_uuid=True)


class IssuedDocument(Base):
    __tablename__ = "issued_documents"

    id: Mapped[uuid.UUID] = mapped_column(_UUID, primary_key=True)
    doc_type: Mapped[str] = mapped_column(Text, nullable=False)
    ref_no: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    recipient_name: Mapped[str] = mapped_column(Text, nullable=False)
    recipient_email: Mapped[str] = mapped_column(Text, nullable=False)
    # college, reg_no (printed / used in placeholders)
    recipient: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    user_id: Mapped[uuid.UUID | None] = mapped_column(_UUID, ForeignKey("users.id"))
    organization_id: Mapped[uuid.UUID | None] = mapped_column(_UUID, ForeignKey("organizations.id"))
    enrolment_id: Mapped[uuid.UUID | None] = mapped_column(_UUID, ForeignKey("enrolments.id"))
    batch_id: Mapped[uuid.UUID | None] = mapped_column(_UUID, ForeignKey("batches.id"))
    course_id: Mapped[uuid.UUID | None] = mapped_column(_UUID)  # catalog may live in Firestore: no FK
    certificate_id: Mapped[uuid.UUID | None] = mapped_column(_UUID, ForeignKey("certificates.id"))
    fields: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    # frozen at issue: paragraphs, sections, subject, letterhead + signatory snapshot
    content: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    issue_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="valid")
    origin: Mapped[str] = mapped_column(Text, nullable=False, server_default="manual")
    replaces_id: Mapped[uuid.UUID | None] = mapped_column(_UUID, ForeignKey("issued_documents.id"))
    superseded_by_id: Mapped[uuid.UUID | None] = mapped_column(_UUID, ForeignKey("issued_documents.id"))
    superseded_at: Mapped[datetime | None] = mapped_column(_TS)
    revoked_at: Mapped[datetime | None] = mapped_column(_TS)
    revoked_by: Mapped[uuid.UUID | None] = mapped_column(_UUID, ForeignKey("users.id"))
    revoke_reason: Mapped[str | None] = mapped_column(Text)
    revoke_reason_public: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    template_version: Mapped[str] = mapped_column(Text, nullable=False)
    pdf_s3_key: Mapped[str | None] = mapped_column(Text)
    content_hash: Mapped[bytes | None] = mapped_column(LargeBinary)
    file_hashes: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, server_default="{}")
    issued_by: Mapped[uuid.UUID | None] = mapped_column(_UUID, ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())


class DocumentTemplate(Base):
    """Wording overrides: ``kind='document'`` (paragraphs / letter sections per document type) or
    ``kind='email'`` (subject / body per email key). Absent row = the ``docdefs`` default."""

    __tablename__ = "document_templates"

    kind: Mapped[str] = mapped_column(Text, primary_key=True)
    template_key: Mapped[str] = mapped_column(Text, primary_key=True)
    content: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(_UUID, ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())


class DocumentSettings(Base):
    """Singleton (``id = 1``): letterhead, signatory, image keys (S3), automation switches."""

    __tablename__ = "document_settings"

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    data: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    updated_by: Mapped[uuid.UUID | None] = mapped_column(_UUID, ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())
