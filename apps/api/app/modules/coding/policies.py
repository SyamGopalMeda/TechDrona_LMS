"""Permission helpers for coding routes whose scope depends on a loaded row.

``require_permission`` resolves its scope from the request only; studio routes need the
problem's organization, so they call the registered checker through ``check_permission``.
(Request to Foundation: a public ``app.core.auth.check_permission(...)`` helper.)
"""

from __future__ import annotations

import uuid

from fastapi import Request

from app.core import auth as core_auth
from app.core.auth import PLATFORM_SCOPE, ScopeRef
from app.core.errors import ProblemError
from app.core.principal import Principal


def scope_for(organization_id: uuid.UUID | None) -> ScopeRef:
    return ScopeRef("organization", organization_id) if organization_id else PLATFORM_SCOPE


async def has_permission(request: Request, principal: Principal, permission: str, scope: ScopeRef) -> bool:
    return await core_auth.check_permission(principal, permission, scope, request, cross_tenant_raises=True)


async def check_permission(request: Request, principal: Principal, permission: str, scope: ScopeRef) -> None:
    if not await has_permission(request, principal, permission, scope):
        raise ProblemError("permission_denied", permission=permission)
    used = getattr(request.state, "permissions_used", None)
    if used is None:
        request.state.permissions_used = used = []
    used.append(permission)
