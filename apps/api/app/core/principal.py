"""The authenticated principal returned by ``require_active_principal``.

Built by the sessions module's ``SessionResolver`` (api-specification §1.4 step 11).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

SessionTier = Literal["student", "staff", "privileged"]
SessionScope = Literal["full", "restricted", "status_only"]
ScopeType = Literal["platform", "organization", "batch", "course"]


@dataclass(frozen=True, slots=True)
class RoleGrant:
    role: str
    scope_type: ScopeType
    scope_id: uuid.UUID | None = None


@dataclass(frozen=True, slots=True)
class Principal:
    user_id: uuid.UUID
    session_id: uuid.UUID
    tier: SessionTier = "student"
    scope: SessionScope = "full"
    device_id: uuid.UUID | None = None
    org_ids: tuple[uuid.UUID, ...] = ()
    grants: tuple[RoleGrant, ...] = ()
    is_platform: bool = False  # holds a platform-scoped staff grant -> app.is_platform = on
    aal: int = 1
    amr: tuple[str, ...] = ()
    mfa_level: Literal["none", "totp", "passkey"] = "none"
    auth_time: datetime | None = None
    last_step_up_at: datetime | None = None
    restriction_level: int = 0
    restrictions: frozenset[str] = field(default_factory=frozenset)  # feature locks
    is_minor: bool = True  # unverified age => minor treatment (brief §1)
    privacy_tier: str | None = None

    @property
    def role_keys(self) -> tuple[str, ...]:
        return tuple(sorted({g.role for g in self.grants}))

    def has_role(
        self, role: str, scope_type: ScopeType | None = None, scope_id: uuid.UUID | None = None
    ) -> bool:
        return any(
            g.role == role
            and (scope_type is None or g.scope_type == scope_type)
            and (scope_id is None or g.scope_id == scope_id)
            for g in self.grants
        )
