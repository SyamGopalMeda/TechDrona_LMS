"""Sessions and devices (database-schema §4)."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    SmallInteger,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, INET, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

_TS = DateTime(timezone=True)


class Device(Base):
    __tablename__ = "devices"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    device_key_hash: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    key_version: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="1")
    client_type: Mapped[str] = mapped_column(Text, nullable=False)
    ua_family: Mapped[str | None] = mapped_column(Text)
    os_family: Mapped[str | None] = mapped_column(Text)
    device_class: Mapped[str | None] = mapped_column(Text)
    label_hint: Mapped[str | None] = mapped_column(Text)
    first_seen_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())
    last_seen_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())
    created_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())


class UserDevice(Base):
    __tablename__ = "user_devices"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    device_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("devices.id"), nullable=False)
    trust_status: Mapped[str] = mapped_column(Text, nullable=False, server_default="pending_otp")
    trusted_at: Mapped[datetime | None] = mapped_column(_TS)
    owner_verified_at: Mapped[datetime | None] = mapped_column(_TS)
    verification_method: Mapped[str | None] = mapped_column(Text)
    counts_toward_cap: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    remember_until: Mapped[datetime | None] = mapped_column(_TS)
    remember_token_hash: Mapped[bytes | None] = mapped_column(LargeBinary)
    remember_issued_at: Mapped[datetime | None] = mapped_column(_TS)
    user_label: Mapped[str | None] = mapped_column(Text)
    last_used_at: Mapped[datetime | None] = mapped_column(_TS)
    removed_at: Mapped[datetime | None] = mapped_column(_TS)
    removed_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    removed_reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())


class AuthSession(Base):
    __tablename__ = "auth_sessions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    token_hash: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    device_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    user_device_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    client_type: Mapped[str] = mapped_column(Text, nullable=False)
    session_tier: Mapped[str] = mapped_column(Text, nullable=False)
    scope: Mapped[str] = mapped_column(Text, nullable=False, server_default="full")
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="active")
    aal: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="1")
    amr: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, server_default="{}")
    created_via: Mapped[str] = mapped_column(Text, nullable=False)
    auth_time: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())
    last_step_up_at: Mapped[datetime | None] = mapped_column(_TS)
    remember_device: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    restriction_level_at_issue: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="0")
    created_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())
    last_seen_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())
    idle_expires_at: Mapped[datetime] = mapped_column(_TS, nullable=False)
    absolute_expires_at: Mapped[datetime] = mapped_column(_TS, nullable=False)
    idle_hold_until: Mapped[datetime | None] = mapped_column(_TS)
    ip_first: Mapped[str | None] = mapped_column(INET)
    ip_last: Mapped[str | None] = mapped_column(INET)
    net_cluster_first: Mapped[str | None] = mapped_column(Text)
    net_cluster_last: Mapped[str | None] = mapped_column(Text)
    asn: Mapped[int | None] = mapped_column(Integer)
    network_type: Mapped[str | None] = mapped_column(Text)
    geo_country: Mapped[str | None] = mapped_column(Text)
    geo_region: Mapped[str | None] = mapped_column(Text)
    ua_family: Mapped[str | None] = mapped_column(Text)
    ua_major: Mapped[str | None] = mapped_column(Text)
    os_family: Mapped[str | None] = mapped_column(Text)
    device_class: Mapped[str | None] = mapped_column(Text)
    ua_hash: Mapped[bytes | None] = mapped_column(LargeBinary)
    app_version: Mapped[str | None] = mapped_column(Text)
    risk_evaluation_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    ended_at: Mapped[datetime | None] = mapped_column(_TS)
    end_reason: Mapped[str | None] = mapped_column(Text)
    ended_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    updated_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())


class LoginAttempt(Base):
    __tablename__ = "login_attempts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    attempted_at: Mapped[datetime] = mapped_column(_TS, primary_key=True, server_default=func.now())
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    identifier_hash: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    key_version: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="1")
    method: Mapped[str] = mapped_column(Text, nullable=False)
    mfa_method: Mapped[str | None] = mapped_column(Text)
    outcome: Mapped[str] = mapped_column(Text, nullable=False)
    failure_reason: Mapped[str | None] = mapped_column(Text)
    pre_auth_blocked: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    ip: Mapped[str | None] = mapped_column(INET)
    asn: Mapped[int | None] = mapped_column(Integer)
    network_type: Mapped[str | None] = mapped_column(Text)
    geo_country: Mapped[str | None] = mapped_column(Text)
    geo_region: Mapped[str | None] = mapped_column(Text)
    ua_hash: Mapped[bytes | None] = mapped_column(LargeBinary)
    device_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    auth_session_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    risk_evaluation_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))


class SessionNetworkObservation(Base):
    __tablename__ = "session_network_observations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    first_seen_at: Mapped[datetime] = mapped_column(_TS, primary_key=True, server_default=func.now())
    last_seen_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())
    auth_session_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    net_cluster: Mapped[str] = mapped_column(Text, nullable=False)
    asn: Mapped[int | None] = mapped_column(Integer)
    network_type: Mapped[str | None] = mapped_column(Text)
    geo_region: Mapped[str | None] = mapped_column(Text)
