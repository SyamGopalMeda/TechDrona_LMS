"""Permission helpers for service-level (body- or row-scoped) checks.

Route-level checks use ``Depends(require_permission(...))``; when the scope is only known after
reading the body or a row, routes call these helpers, which go through the same registered
``PermissionChecker`` (so RBAC, cross-tenant 404s and test fakes behave identically).
"""

from __future__ import annotations

import uuid

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import PLATFORM_SCOPE, ScopeRef, require_permission
from app.core.company import COMPANY_ORG_ID
from app.core.errors import ProblemError
from app.core.principal import Principal


async def require(request: Request, principal: Principal, permission: str, scope: ScopeRef) -> None:
    """Raise ``403 permission_denied`` (or ``404 not_found`` for a foreign tenant)."""
    await require_permission(permission, scope=scope)(request, principal)


async def has_permission(request: Request, principal: Principal, permission: str, scope: ScopeRef) -> bool:
    try:
        await require(request, principal, permission, scope)
    except ProblemError as e:
        if e.code in ("permission_denied", "not_found"):
            return False
        raise
    return True


async def batch_org(session: AsyncSession, batch_id: uuid.UUID) -> uuid.UUID | None:
    from app.modules.orgs.models import Batch

    return (
        await session.execute(select(Batch.organization_id).where(Batch.id == batch_id))
    ).scalar_one_or_none()


async def can_in_org(
    request: Request,
    session: AsyncSession,
    principal: Principal,
    permission: str,
    org_id: uuid.UUID | None,
) -> bool:
    """Holds ``permission`` for content owned by ``org_id`` (None = platform bank): at the
    platform/organization scope, or via a batch-scoped grant on a batch of that organization
    (trainers)."""
    if org_id is None:
        return await has_permission(request, principal, permission, PLATFORM_SCOPE)
    if await has_permission(request, principal, permission, ScopeRef("organization", org_id)):
        return True
    for g in principal.grants:
        if (
            g.scope_type == "batch"
            and g.scope_id is not None
            and await batch_org(session, g.scope_id) == org_id
        ):
            if await has_permission(request, principal, permission, ScopeRef("batch", g.scope_id)):
                return True
    return False


async def require_in_org(
    request: Request,
    session: AsyncSession,
    principal: Principal,
    permission: str,
    org_id: uuid.UUID | None,
) -> None:
    if not await can_in_org(request, session, principal, permission, org_id):
        raise ProblemError("permission_denied", permission=permission)


def company_owner(organization_id: uuid.UUID | None) -> uuid.UUID | None:
    """Single company: a body may still name the owner of new content, but only as ``null``
    (platform content) or the company organization (company bank). Any other id is unknown
    (404, no existence disclosure)."""
    if organization_id is not None and organization_id != COMPANY_ORG_ID:
        raise ProblemError("not_found")
    return organization_id


async def resolve_owner(
    request: Request,
    session: AsyncSession,
    principal: Principal,
    permission: str,
    organization_id: uuid.UUID | None,
) -> uuid.UUID | None:
    """Owner of new content (None = platform, else the company org) and the permission check.

    An explicit ``organization_id`` is honoured (it must be the company org). Without one, a
    holder of ``permission`` at platform scope creates platform content; everyone else (batch
    trainers) creates company-owned content, so web clients never need to send an org id."""
    org = company_owner(organization_id)
    if org is None and not await has_permission(request, principal, permission, PLATFORM_SCOPE):
        if await can_in_org(request, session, principal, permission, COMPANY_ORG_ID):
            return COMPANY_ORG_ID
    await require_in_org(request, session, principal, permission, org)
    return org


async def scope_for(
    session: AsyncSession, *, batch_id: uuid.UUID | None, organization_id: uuid.UUID | None
) -> tuple[ScopeRef, uuid.UUID | None]:
    """Scope + owning organization from an optional batch/organization pair in a body."""
    company_owner(organization_id)
    if batch_id is not None:
        org = await batch_org(session, batch_id)
        if org is None:
            raise ProblemError("not_found")
        if organization_id is not None and organization_id != org:
            raise ProblemError("not_found")
        return ScopeRef("batch", batch_id), org
    if organization_id is not None:
        return ScopeRef("organization", organization_id), organization_id
    return PLATFORM_SCOPE, None
