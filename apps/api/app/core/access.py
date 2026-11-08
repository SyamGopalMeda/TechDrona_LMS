"""Content access (entitlement) checks with a pluggable back-end.

Extension point:

* ``register_access_checker(checker)`` — entitlements module. Until registered every
  ``check_access`` call for non-free content answers ``deny`` (fail closed).

Consumers (catalog, learning, media, placement, assessments, coding) call
``check_access`` / ``require_access`` server-side before serving any gated resource.
They must never trust a client-supplied access flag.

Resource types (stable keys): ``course``, ``lesson``, ``resource``, ``test``,
``question_set``, ``coding_problem``, ``company_path``, ``product``.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, Protocol, runtime_checkable

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ProblemError
from app.core.principal import Principal

ResourceType = Literal[
    "course",
    "lesson",
    "resource",
    "test",
    "question_set",
    "coding_problem",
    "company_path",
    "product",
]


@dataclass(frozen=True, slots=True)
class AccessDecision:
    allowed: bool
    reason: str  # e.g. "free", "entitlement", "staff", "no_entitlement", "expired", "restricted"
    entitlement_ids: tuple[uuid.UUID, ...] = field(default_factory=tuple)
    expires_at: datetime | None = None


@runtime_checkable
class AccessChecker(Protocol):
    async def check(
        self,
        session: AsyncSession,
        principal: Principal,
        resource_type: ResourceType,
        resource_id: uuid.UUID,
        *,
        is_free: bool = False,
    ) -> AccessDecision: ...


_access_checker: AccessChecker | None = None


def register_access_checker(checker: AccessChecker | None) -> None:
    global _access_checker
    if checker is not None and not isinstance(checker, AccessChecker):
        raise TypeError("checker must implement AccessChecker.check")
    _access_checker = checker


def get_access_checker() -> AccessChecker | None:
    return _access_checker


async def check_access(
    session: AsyncSession,
    principal: Principal,
    resource_type: ResourceType,
    resource_id: uuid.UUID,
    *,
    is_free: bool = False,
) -> AccessDecision:
    """Return the access decision. Free content is allowed without a checker; everything
    else fails closed until the entitlements module registers its checker."""
    checker = _access_checker
    if checker is None:
        if is_free:
            return AccessDecision(True, "free")
        return AccessDecision(False, "no_entitlement")
    return await checker.check(session, principal, resource_type, resource_id, is_free=is_free)


async def require_access(
    session: AsyncSession,
    principal: Principal,
    resource_type: ResourceType,
    resource_id: uuid.UUID,
    *,
    is_free: bool = False,
) -> AccessDecision:
    """Like ``check_access`` but raises ``403 entitlement_required`` when denied."""
    decision = await check_access(session, principal, resource_type, resource_id, is_free=is_free)
    if not decision.allowed:
        raise ProblemError(
            "entitlement_required",
            resource_type=resource_type,
            resource_id=str(resource_id),
            reason=decision.reason,
        )
    return decision
