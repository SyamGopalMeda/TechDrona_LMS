"""Route classes, route-tag allow-list and the authenticated-router factory.

Every route declares (api-specification §1.4):

* ``x-td-route-tag`` — one of ``ROUTE_TAGS``. ``public`` routes need no session.
* ``x-td-idle`` (authenticated routes) — one of ``IDLE_EFFECTS``.

Use the factories, never a bare ``APIRouter``::

    from app.core.routing import authenticated_router, public_router

    router = authenticated_router(prefix="/audit", tags=["audit"])          # tag "default", idle "extends"
    me = authenticated_router(prefix="/me", route_tag="account_status")
    @router.get("/events", openapi_extra={"x-td-idle": "neutral"})       # per-route override
    ...
    pub = public_router(prefix="/catalog")

``authenticated_router`` mounts ``require_active_principal`` as a router dependency so it
can't be forgotten. ``find_route_guard_violations(app)`` is the CI check (tests/core).
"""

from __future__ import annotations

from collections.abc import Callable, Coroutine, Iterable
from dataclasses import dataclass
from typing import Any

from fastapi import APIRouter, Depends, FastAPI, Request, Response
from fastapi.dependencies.models import Dependant
from fastapi.routing import APIRoute

ROUTE_TAG_KEY = "x-td-route-tag"
IDLE_KEY = "x-td-idle"

ROUTE_TAGS = frozenset(
    {"public", "login_continuation", "account_status", "l3_readonly", "mfa_enrolment", "consent", "default"}
)
IDLE_EFFECTS = frozenset({"extends", "engaged_only", "neutral"})
PENDING_ALLOWED_TAGS = frozenset({"login_continuation"})

# Which session scopes may call which tag (api-specification §1.4 table).
_SCOPE_TAGS: dict[str, frozenset[str]] = {
    "full": ROUTE_TAGS,
    "restricted": frozenset(
        {"login_continuation", "account_status", "l3_readonly", "mfa_enrolment", "consent", "public"}
    ),
    "status_only": frozenset({"login_continuation", "account_status", "mfa_enrolment", "consent", "public"}),
}


def scope_allows(scope: str, route_tag: str) -> bool:
    return route_tag in _SCOPE_TAGS.get(scope, frozenset())


@dataclass(frozen=True, slots=True)
class RouteContext:
    route_tag: str
    idle_effect: str
    path: str
    method: str


def _make_route_class(default_tag: str, default_idle: str | None) -> type[APIRoute]:
    if default_tag not in ROUTE_TAGS:
        raise ValueError(f"unknown route tag {default_tag!r}; allowed: {sorted(ROUTE_TAGS)}")
    if default_idle is not None and default_idle not in IDLE_EFFECTS:
        raise ValueError(f"unknown idle effect {default_idle!r}; allowed: {sorted(IDLE_EFFECTS)}")

    class TDRoute(APIRoute):
        td_default_tag = default_tag
        td_default_idle = default_idle

        def __init__(self, path: str, endpoint: Callable[..., Any], **kwargs: Any) -> None:
            extra = dict(kwargs.get("openapi_extra") or {})
            extra.setdefault(ROUTE_TAG_KEY, default_tag)
            if default_idle is not None and extra[ROUTE_TAG_KEY] != "public":
                extra.setdefault(IDLE_KEY, default_idle)
            kwargs["openapi_extra"] = extra
            super().__init__(path, endpoint, **kwargs)
            if extra[ROUTE_TAG_KEY] not in ROUTE_TAGS:
                raise ValueError(f"{path}: unknown {ROUTE_TAG_KEY} {extra[ROUTE_TAG_KEY]!r}")
            if IDLE_KEY in extra and extra[IDLE_KEY] not in IDLE_EFFECTS:
                raise ValueError(f"{path}: unknown {IDLE_KEY} {extra[IDLE_KEY]!r}")

        def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
            handler = super().get_route_handler()
            route = self

            async def td_handler(request: Request) -> Response:
                request.scope["td_route"] = route
                return await handler(request)

            return td_handler

    TDRoute.__name__ = f"TDRoute_{default_tag}"
    return TDRoute


def route_context(request: Request) -> RouteContext:
    route = request.scope.get("td_route") or request.scope.get("route")
    extra: dict[str, Any] = getattr(route, "openapi_extra", None) or {}
    return RouteContext(
        route_tag=str(extra.get(ROUTE_TAG_KEY, "default")),
        idle_effect=str(extra.get(IDLE_KEY, "neutral")),
        path=getattr(route, "path", request.url.path),
        method=request.method,
    )


def authenticated_router(
    *,
    route_tag: str = "default",
    idle: str = "extends",
    dependencies: Iterable[Any] = (),
    **kwargs: Any,
) -> APIRouter:
    """Router whose every route requires an active principal (cannot be opted out)."""
    from app.core.auth import require_active_principal

    if route_tag == "public":
        raise ValueError("authenticated_router cannot use the 'public' tag; use public_router()")
    deps = [Depends(require_active_principal), *dependencies]
    return APIRouter(dependencies=deps, route_class=_make_route_class(route_tag, idle), **kwargs)


def public_router(**kwargs: Any) -> APIRouter:
    """Router for unauthenticated routes (signup, login, catalog reads, webhooks, health)."""
    return APIRouter(route_class=_make_route_class("public", None), **kwargs)


# --------------------------------------------------------------------------- CI guard


def _dependant_calls(dep: Dependant) -> Iterable[Callable[..., Any]]:
    stack = [dep]
    while stack:
        d = stack.pop()
        if d.call is not None:
            yield d.call
        stack.extend(d.dependencies)


def iter_api_routes(app: FastAPI) -> Iterable[tuple[APIRoute, str]]:
    """Yield ``(route, full_path)`` for every API route, including routes of included
    routers (FastAPI >= 0.16x wraps them in ``_IncludedRouter``; older versions copy them)."""
    try:
        from fastapi.routing import iter_route_contexts
    except ImportError:  # pragma: no cover - older FastAPI
        for r in app.routes:
            if isinstance(r, APIRoute):
                yield r, r.path
        return
    for rc in iter_route_contexts(app.routes):
        original = rc.original_route
        if isinstance(original, APIRoute):
            yield original, rc.path or original.path


def find_route_guard_violations(app: FastAPI) -> list[str]:
    """Every non-public route must depend on ``require_active_principal`` and declare a
    valid route tag and idle effect. Public routes must be explicitly tagged ``public``.

    The dependency must be part of the route's own dependant (router-level dependencies of
    an ``APIRouter`` are merged there), because that is what runs for the request."""
    from app.core.auth import require_active_principal

    problems: list[str] = []
    for route, path in iter_api_routes(app):
        name = f"{sorted(route.methods or [])} {path}"
        extra = route.openapi_extra or {}
        tag = extra.get(ROUTE_TAG_KEY)
        if tag is None:
            problems.append(f"{name}: missing {ROUTE_TAG_KEY}")
            continue
        if tag not in ROUTE_TAGS:
            problems.append(f"{name}: unknown route tag {tag!r}")
            continue
        if tag == "public":
            continue
        if require_active_principal not in set(_dependant_calls(route.dependant)):
            problems.append(f"{name}: authenticated route lacks require_active_principal")
        idle = extra.get(IDLE_KEY)
        if idle not in IDLE_EFFECTS:
            problems.append(f"{name}: missing/invalid {IDLE_KEY} ({idle!r})")
    return problems
