"""Certificate + document email outbox (migrations ``learning_0005``, ``learning_0006``).

One row per certificate: the email to the learner with the certificate PDF attached. With the
feature flag ``certificates.auto_send`` off (default) the row waits as ``awaiting`` until an
admin approves it; approved / auto rows are ``pending`` and the sender moves them to ``sent``
or ``failed``. Admins may ``cancel`` any row that has not been sent.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, SmallInteger, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

_TS = DateTime(timezone=True)
_UUID = UUID(as_uuid=True)


class CertificateOutbox(Base):
    __tablename__ = "certificate_outbox"

    id: Mapped[uuid.UUID] = mapped_column(_UUID, primary_key=True)
    # Exactly one of certificate_id / document_id (learning_0006 generalised the outbox to issued
    # documents). One row per certificate; a document may be emailed more than once (resend).
    certificate_id: Mapped[uuid.UUID | None] = mapped_column(
        _UUID, ForeignKey("certificates.id", ondelete="CASCADE"), unique=True
    )
    document_id: Mapped[uuid.UUID | None] = mapped_column(
        _UUID, ForeignKey("issued_documents.id", ondelete="CASCADE")
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(_UUID, ForeignKey("users.id"))
    # documents only: the address (recipients may have no account), and the edited email text
    to_email: Mapped[str | None] = mapped_column(Text)
    subject: Mapped[str | None] = mapped_column(Text)
    body: Mapped[str | None] = mapped_column(Text)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(_UUID, ForeignKey("organizations.id"))
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="awaiting")
    origin: Mapped[str] = mapped_column(Text, nullable=False, server_default="rule")
    attempts: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="0")
    last_error: Mapped[str | None] = mapped_column(Text)
    provider_message_id: Mapped[str | None] = mapped_column(Text)
    approved_by: Mapped[uuid.UUID | None] = mapped_column(_UUID, ForeignKey("users.id"))
    approved_at: Mapped[datetime | None] = mapped_column(_TS)
    cancelled_by: Mapped[uuid.UUID | None] = mapped_column(_UUID, ForeignKey("users.id"))
    cancelled_at: Mapped[datetime | None] = mapped_column(_TS)
    sent_at: Mapped[datetime | None] = mapped_column(_TS)
    created_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())
