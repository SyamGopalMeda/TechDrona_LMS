"""Media: playback sessions (database-schema §4; migration ``media_0001``). Lesson assets are
catalog rows (``app.modules.catalog.models.LessonAsset``) whose status media maintains."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Integer, LargeBinary, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

_TS = DateTime(timezone=True)
_UUID = UUID(as_uuid=True)


class PlaybackSession(Base):
    __tablename__ = "playback_sessions"

    id: Mapped[uuid.UUID] = mapped_column(_UUID, primary_key=True)
    started_at: Mapped[datetime] = mapped_column(_TS, primary_key=True, server_default=func.now())
    user_id: Mapped[uuid.UUID] = mapped_column(_UUID, nullable=False)
    auth_session_id: Mapped[uuid.UUID] = mapped_column(_UUID, nullable=False)
    device_id: Mapped[uuid.UUID | None] = mapped_column(_UUID)
    tab_id: Mapped[uuid.UUID | None] = mapped_column(_UUID)
    lesson_asset_id: Mapped[uuid.UUID] = mapped_column(_UUID, nullable=False)
    provider: Mapped[str] = mapped_column(Text, nullable=False, server_default="vdocipher")
    provider_otp_ref_hash: Mapped[bytes | None] = mapped_column(LargeBinary)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="active")
    otp_expires_at: Mapped[datetime] = mapped_column(_TS, nullable=False)
    last_heartbeat_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())
    last_position_s: Mapped[int | None] = mapped_column(Integer)
    ended_at: Mapped[datetime | None] = mapped_column(_TS)
    end_reason: Mapped[str | None] = mapped_column(Text)
