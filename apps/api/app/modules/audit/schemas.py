from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, field_serializer

from app.core.time import to_rfc3339


class AuditEventOut(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)

    seq: int
    occurred_at: datetime
    id: uuid.UUID
    actor_type: str
    actor_user_id: uuid.UUID | None
    actor_session_id: uuid.UUID | None
    actor_roles: list[str]
    action: str
    target_type: str
    target_id: uuid.UUID | None
    organization_id: uuid.UUID | None
    subject_user_id: uuid.UUID | None
    reason_code: str | None
    reason: str | None
    request_id: str | None
    prev_hash: str
    row_hash: str

    @field_serializer("occurred_at")
    def _ts(self, v: datetime) -> str:
        return to_rfc3339(v)

    @classmethod
    def from_row(cls, row: Any) -> AuditEventOut:
        data = {f: getattr(row, f) for f in cls.model_fields if f not in ("prev_hash", "row_hash")}
        data["actor_roles"] = list(data["actor_roles"] or [])
        return cls(**data, prev_hash=bytes(row.prev_hash).hex(), row_hash=bytes(row.row_hash).hex())


class AuditEventDetailOut(AuditEventOut):
    before_state: Any | None = None
    after_state: Any | None = None
    ip: str | None = None

    @classmethod
    def from_row(cls, row: Any) -> AuditEventDetailOut:
        base = AuditEventOut.from_row(row).model_dump()
        return cls(
            **base,
            before_state=row.before_state,
            after_state=row.after_state,
            ip=str(row.ip) if row.ip is not None else None,
        )


class PageMeta(BaseModel):
    next_cursor: str | None
    has_more: bool
    limit: int


class AuditEventList(BaseModel):
    data: list[AuditEventOut]
    page: PageMeta


class ChainStatusOut(BaseModel):
    verified: bool
    checked_rows: int
    last_seq: int | None
    last_row_hash: str | None
    first_bad_seq: int | None
    reason: str | None
    last_anchor: dict[str, Any] | None = None  # S3 Object Lock anchoring: Planned
