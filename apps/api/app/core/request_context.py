"""Per-request context (request id, caller principal / RLS view) shared by logging, errors,
audit and Firestore repositories."""

from __future__ import annotations

import re
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any

_request_id: ContextVar[str | None] = ContextVar("td_request_id", default=None)

# Accept an upstream (BFF) id only if it is a short, safe token.
REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9._\-]{8,128}$")


def get_request_id() -> str | None:
    return _request_id.get()


def set_request_id(value: str | None) -> object:
    return _request_id.set(value)


def reset_request_id(token: object) -> None:
    _request_id.reset(token)  # type: ignore[arg-type]


# --------------------------------------------------------------------------- caller context (R12)
#
# ``RequestContextMiddleware`` publishes the request's ASGI ``state`` dict here for the whole
# request. ``require_active_principal`` stores the resolved principal in that same dict
# (``request.state.principal``), so code that has no Postgres session -- and therefore no RLS
# GUCs -- can still act with the caller's view, e.g. a module calling catalog on Firestore:
#
#     from app.core.request_context import current_principal, current_rls_context
#     p = current_principal()            # Principal | None (None: anonymous / not resolved yet)
#     ctx = current_rls_context()        # the values tenant_context() would bind as GUCs
#
# The dict is shared by reference, so the principal is visible even when it was resolved after
# the middleware ran or in a copied context (threadpool dependencies). Outside a request
# (jobs, tests) both return the anonymous answer unless ``bind_request_state`` is used.

_request_state: ContextVar[dict[str, Any] | None] = ContextVar("td_request_state", default=None)


@dataclass(frozen=True, slots=True)
class RlsContext:
    """Mirror of ``app.core.db.tenant_context`` (``app.user_id``, ``app.org_ids``, ...)."""

    user_id: str | None = None
    org_ids: tuple[Any, ...] = ()
    is_platform: bool = False
    actor: str | None = None
    roles: tuple[str, ...] = ()
    privacy_tier: str = ""

    @property
    def anonymous(self) -> bool:
        return self.user_id is None and not self.is_platform


ANONYMOUS = RlsContext()


def bind_request_state(state: dict[str, Any] | None) -> object:
    return _request_state.set(state)


def reset_request_state(token: object) -> None:
    _request_state.reset(token)  # type: ignore[arg-type]


def current_principal() -> Any:
    """The authenticated ``Principal`` of the current request, else ``None``."""
    from app.core.principal import Principal

    state = _request_state.get()
    p = state.get("principal") if state else None
    return p if isinstance(p, Principal) else None


def current_rls_context() -> RlsContext:
    """The caller's RLS context (anonymous when no principal was resolved)."""
    p = current_principal()
    if p is None:
        return ANONYMOUS
    return RlsContext(
        user_id=str(p.user_id),
        org_ids=tuple(p.org_ids),
        is_platform=bool(p.is_platform),
        actor=f"user:{p.user_id}",
        roles=tuple(p.role_keys),
        privacy_tier=p.privacy_tier or "",
    )
