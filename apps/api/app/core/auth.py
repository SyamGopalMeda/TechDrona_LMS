"""Authentication / authorization dependencies with pluggable back-ends.

Extension points (registered by owning modules at import time of their ``router.py``):

* ``register_session_resolver(resolver)`` — sessions module. Implements steps 2-10 of
  api-specification §1.4 and returns a ``Principal``. Until registered every authenticated
  route answers ``401 unauthenticated`` (fail closed).
* ``register_permission_checker(checker)`` — rbac module. Until registered every
  ``require_permission`` answers ``403 permission_denied`` (deny by default).

Dependencies used by routes:

* ``require_active_principal`` — mounted by ``app.core.routing.authenticated_router``.
* ``require_permission("perm.key", scope=resolver)``
* ``require_step_up(window_s)`` or ``require_step_up("privileged"|"staff"|"student")``.
"""

from __future__ import annotations

import inspect
import re
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import timedelta
from typing import Literal, Protocol, runtime_checkable

from fastapi import Depends, Request

from app.core.errors import ProblemError
from app.core.principal import Principal
from app.core.routing import RouteContext, route_context, scope_allows
from app.core.time import within

PERMISSION_KEY_RE = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*){1,2}$")


# --------------------------------------------------------------------------- session resolver


@runtime_checkable
class SessionResolver(Protocol):
    async def resolve(self, request: Request, session_token: str, ctx: RouteContext) -> Principal:
        """Validate the session for this request and return the principal, or raise
        ``ProblemError`` (``unauthenticated``, ``session_expired``, ``session_revoked``,
        ``login_incomplete``, ``account_restricted``, ``mfa_enrolment_required``,
        ``consent_required`` ...)."""
        ...


_session_resolver: SessionResolver | None = None


def register_session_resolver(resolver: SessionResolver | None) -> None:
    global _session_resolver
    if resolver is not None and not isinstance(resolver, SessionResolver):
        raise TypeError("resolver must implement SessionResolver.resolve")
    _session_resolver = resolver


def get_session_resolver() -> SessionResolver | None:
    return _session_resolver


async def require_active_principal(request: Request) -> Principal:
    """Single enforcement point for authenticated routes (ADR-0002)."""
    cached = getattr(request.state, "principal", None)
    if isinstance(cached, Principal):
        return cached
    ctx = route_context(request)
    token = getattr(request.state, "session_token", None)
    if not token:
        raise ProblemError("unauthenticated")
    resolver = _session_resolver
    if resolver is None:
        raise ProblemError("unauthenticated")
    principal = await resolver.resolve(request, token, ctx)
    if not isinstance(principal, Principal):  # pragma: no cover - defensive
        raise ProblemError("unauthenticated")
    # Defence in depth: the scope gate even if a resolver forgot it.
    if not scope_allows(principal.scope, ctx.route_tag):
        raise ProblemError(
            "account_restricted",
            level=principal.restriction_level,
            status_url="/app/account-status",
        )
    request.state.principal = principal
    return principal


# --------------------------------------------------------------------------- permissions


@dataclass(frozen=True, slots=True)
class ScopeRef:
    """A resource's position for permission checks. ``scope_type='platform'`` = global."""

    scope_type: Literal["platform", "organization", "batch", "course"]
    scope_id: uuid.UUID | None = None


PLATFORM_SCOPE = ScopeRef("platform")

ScopeResolver = Callable[[Request], "ScopeRef | Awaitable[ScopeRef]"]


@runtime_checkable
class PermissionChecker(Protocol):
    async def has_permission(
        self, principal: Principal, permission: str, scope: ScopeRef, request: Request
    ) -> bool:
        """True if the principal holds ``permission`` at any scope in ``scope``'s chain."""
        ...


_permission_checker: PermissionChecker | None = None


def register_permission_checker(checker: PermissionChecker | None) -> None:
    global _permission_checker
    if checker is not None and not isinstance(checker, PermissionChecker):
        raise TypeError("checker must implement PermissionChecker.has_permission")
    _permission_checker = checker


def get_permission_checker() -> PermissionChecker | None:
    return _permission_checker


async def check_permission(
    principal: Principal,
    permission: str,
    scope: ScopeRef | None = None,
    request: Request | None = None,
    *,
    cross_tenant_raises: bool = False,
) -> bool:
    """Service-level permission test through the registered checker (the same one
    ``require_permission`` uses). Returns ``False`` when no checker is registered (fail
    closed). A cross-tenant probe (``ProblemError('not_found')`` from the checker) answers
    ``False`` unless ``cross_tenant_raises`` — then the 404 propagates (TI-02)."""
    if not PERMISSION_KEY_RE.match(permission):
        raise ValueError(f"invalid permission key {permission!r}")
    checker = _permission_checker
    if checker is None:
        return False
    try:
        return bool(
            await checker.has_permission(
                principal,
                permission,
                scope or PLATFORM_SCOPE,
                request,  # type: ignore[arg-type]  # checkers must tolerate a missing request
            )
        )
    except ProblemError as e:
        if e.code == "not_found" and not cross_tenant_raises:
            return False
        raise


def scope_from_path(param: str, scope_type: Literal["organization", "batch", "course"]) -> ScopeResolver:
    """Scope resolver taking the id from a path parameter (e.g. ``org_id``)."""

    def _resolve(request: Request) -> ScopeRef:
        raw = request.path_params.get(param)
        try:
            return ScopeRef(scope_type, uuid.UUID(str(raw)))
        except (ValueError, TypeError) as e:
            raise ProblemError("not_found") from e

    return _resolve


def require_permission(
    permission: str, scope: ScopeResolver | ScopeRef | None = None
) -> Callable[..., Awaitable[Principal]]:
    """Endpoint dependency: ``Depends(require_permission("audit.read"))``."""
    if not PERMISSION_KEY_RE.match(permission):
        raise ValueError(f"invalid permission key {permission!r}")

    async def _dep(request: Request, principal: Principal = Depends(require_active_principal)) -> Principal:
        if scope is None:
            ref: ScopeRef = PLATFORM_SCOPE
        elif isinstance(scope, ScopeRef):
            ref = scope
        else:
            res = scope(request)
            ref = await res if inspect.isawaitable(res) else res
        checker = _permission_checker
        if checker is None or not await checker.has_permission(principal, permission, ref, request):
            raise ProblemError("permission_denied", permission=permission)
        granted = getattr(request.state, "permissions_used", None)
        if granted is None:
            granted = []
            request.state.permissions_used = granted
        granted.append(permission)
        return principal

    _dep.__name__ = f"require_permission_{permission.replace('.', '_')}"
    _dep.td_permission = permission  # type: ignore[attr-defined]
    return _dep


# --------------------------------------------------------------------------- step-up

STEP_UP_WINDOWS: dict[str, int] = {"privileged": 300, "staff": 600, "student": 900}  # api-spec §1.6


def require_step_up(window: int | str = "privileged") -> Callable[..., Awaitable[Principal]]:
    """Endpoint dependency enforcing step-up freshness (``auth_sessions.last_step_up_at``).

    ``window`` is seconds or a class name (``privileged``=P5, ``staff``=S10, ``student``=U15).
    Runtime policy keys ``auth.step_up_window.*`` may later override these defaults.
    """
    seconds = STEP_UP_WINDOWS[window] if isinstance(window, str) else int(window)
    if seconds <= 0:
        raise ValueError("step-up window must be positive")

    async def _dep(principal: Principal = Depends(require_active_principal)) -> Principal:
        if not within(principal.last_step_up_at, timedelta(seconds=seconds)):
            methods = ["totp"]  # SEC-11: no WebAuthn passkeys yet
            if principal.tier == "student":
                methods += ["sms_otp", "email_otp"]
            raise ProblemError(
                "step_up_required",
                detail="This action needs a fresh confirmation with your authenticator app.",
                step_up={
                    "max_age_seconds": seconds,
                    "allowed_methods": methods,
                    "options_url": "/api/v1/auth/step-up/options",
                },
            )
        return principal

    _dep.__name__ = f"require_step_up_{seconds}"
    return _dep


def require_feature(feature: str) -> Callable[..., Awaitable[Principal]]:
    """Deny when the principal carries a feature lock (e.g. ``video_locked``)."""

    async def _dep(principal: Principal = Depends(require_active_principal)) -> Principal:
        if f"{feature}_locked" in principal.restrictions:
            raise ProblemError("account_restricted", level=principal.restriction_level)
        return principal

    return _dep


__all__ = [
    "PLATFORM_SCOPE",
    "PermissionChecker",
    "ScopeRef",
    "SessionResolver",
    "check_permission",
    "get_permission_checker",
    "register_permission_checker",
    "register_session_resolver",
    "require_active_principal",
    "require_feature",
    "require_permission",
    "require_step_up",
    "scope_from_path",
]
