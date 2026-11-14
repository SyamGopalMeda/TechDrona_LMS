"""Extension hooks for modules that ship later.

* ``register_restriction_lookup(fn)`` — security module: ``await fn(session, user_id) ->
  RestrictionState``. Default: ``users.restriction_level`` (the security-maintained cache
  column), no case reference, no feature locks.
* ``register_consent_requirement(fn)`` — admin/privacy: ``await fn(session, user_id) ->
  (missing_purposes, notice_version) | None``. Default: ``terms``, ``privacy_notice`` and
  ``core_service`` must be currently granted (any notice version).
* ``register_security_events(sink)`` — security module: login attempts, replay revocations,
  device trust, restricted-route denials and unknown tokens feed the risk engine.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol

from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True, slots=True)
class RestrictionState:
    level: int = 0
    case_ref: str | None = None
    until: datetime | None = None
    restrictions: frozenset[str] = field(default_factory=frozenset)  # feature locks, e.g. video_locked
    takeover_lock: bool = False
    step_up_required: bool = False  # T-step-up (RE §6.2): next login needs MFA or SMS OTP


RestrictionLookup = Callable[[AsyncSession, uuid.UUID], Awaitable[RestrictionState]]
ConsentRequirement = Callable[[AsyncSession, uuid.UUID], Awaitable[tuple[list[str], str] | None]]

_restriction_lookup: RestrictionLookup | None = None
_consent_requirement: ConsentRequirement | None = None


class SecurityEvents(Protocol):
    """Security module sink for session/login events (signal ingestion, RE §5.2). Every method
    runs inside the caller's transaction and must not raise for ordinary input."""

    async def login_attempt(self, session: AsyncSession, attempt: Any) -> None: ...

    async def replay_blocked(
        self, session: AsyncSession, auth_session: Any, rule: str, observed: dict[str, Any] | None = None
    ) -> None:
        """``observed``: the request's ``ua_family`` / ``os_family`` (E2E-09 evidence)."""
        ...

    async def device_trusted(self, session: AsyncSession, user_device: Any, method: str | None) -> None: ...

    async def restricted_denial(self, session: AsyncSession, user_id: uuid.UUID, path: str) -> None: ...

    async def unknown_token(self, session: AsyncSession, ip: str | None) -> bool:
        """Count an unknown session token (AB-07); True when the source is throttled."""
        ...


_security_events: SecurityEvents | None = None


def register_security_events(sink: SecurityEvents | None) -> None:
    global _security_events
    _security_events = sink


def security_events() -> SecurityEvents | None:
    return _security_events


REQUIRED_PURPOSES = ("terms", "privacy_notice", "core_service")


def register_restriction_lookup(fn: RestrictionLookup | None) -> None:
    global _restriction_lookup
    _restriction_lookup = fn


def register_consent_requirement(fn: ConsentRequirement | None) -> None:
    global _consent_requirement
    _consent_requirement = fn


async def lookup_restriction(
    session: AsyncSession, user_id: uuid.UUID, cached_level: int
) -> RestrictionState:
    if _restriction_lookup is not None:
        return await _restriction_lookup(session, user_id)
    return RestrictionState(level=cached_level)


async def missing_consents(session: AsyncSession, user_id: uuid.UUID) -> tuple[list[str], str] | None:
    if _consent_requirement is not None:
        return await _consent_requirement(session, user_id)
    from app.modules.identity.service import current_consents

    state = await current_consents(session, user_id, REQUIRED_PURPOSES)  # only these rows are read
    missing = [p for p in REQUIRED_PURPOSES if state.get(p, {}).get("state") != "granted"]
    return (missing, "current") if missing else None


def derive_scope(level: int) -> str:
    return "status_only" if level >= 4 else ("restricted" if level == 3 else "full")
