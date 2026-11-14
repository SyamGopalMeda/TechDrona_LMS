"""RBAC service: grant lookup, permission checker with scope resolution, grant lifecycle,
dual-control approval requests.

Scope chain (role matrix §1.2): ``platform`` ⊃ ``organization:{id}`` ⊃ ``batch:{id}``;
``course:{id}`` is a separate axis (``platform`` and the owning organization — resolved
through ``register_course_org_lookup`` by the catalog module — also cover it).

Single-company LMS (REMOVAL-PLAN §2.2, §4): grants are made at ``platform``, ``batch`` or
``course`` scope only. ``organization`` survives purely as an *internal* step of the chain —
the company org (``app.core.company.COMPANY_ORG_ID``) owning batches and org-private content —
so that ``ScopeRef("organization", COMPANY_ORG_ID)`` targets used by other modules resolve and
batch grants still cover org-owned content where the rules below allow it.
Cross-tenant targets (organization/batch outside the principal's orgs, without a platform
grant) raise ``404 not_found`` (TI-02) and are recorded in the audit log.
"""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import structlog
from fastapi import Request
from sqlalchemy import and_, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import AuditActor, audit
from app.core.auth import ScopeRef
from app.core.errors import ProblemError
from app.core.firestore.backend import uses_firestore
from app.core.ids import uuid7
from app.core.principal import Principal
from app.core.time import utcnow
from app.modules.rbac.catalogue import (
    DUAL_ROLES,
    EXCLUSIVE_ROLE_PAIRS,
    GRANT_SCOPE_TYPES,
    ROLES,
    TIER_RANK,
)
from app.modules.rbac.models import ApprovalRequest, Permission, Role, RoleGrant, RolePermission

log = structlog.get_logger("app.rbac")

APPROVAL_TTL = timedelta(hours=72)


def _fs() -> bool:
    """``TD_STORE_RBAC=firestore``: rbac tables live in Firestore (repo_firestore)."""
    return uses_firestore("rbac")


def _repo() -> Any:
    from app.modules.rbac.repo_firestore import system_repo

    return system_repo()


@dataclass(frozen=True, slots=True)
class GrantInfo:
    id: uuid.UUID
    role: str
    scope_type: str
    scope_id: uuid.UUID | None
    organization_id: uuid.UUID | None
    expires_at: datetime | None


# --------------------------------------------------------------------------- role permissions cache

_ROLE_PERMS: dict[str, frozenset[str]] | None = None
_ROLE_PERMS_AT = 0.0
_CACHE_TTL_S = 60.0


async def role_permission_map(session: AsyncSession) -> dict[str, frozenset[str]]:
    global _ROLE_PERMS, _ROLE_PERMS_AT
    if _ROLE_PERMS is not None and time.monotonic() - _ROLE_PERMS_AT < _CACHE_TTL_S:
        return _ROLE_PERMS
    if _fs():
        _ROLE_PERMS = await _repo().role_permission_map()
        _ROLE_PERMS_AT = time.monotonic()
        return _ROLE_PERMS
    rows = (
        await session.execute(
            select(Role.role_key, Permission.permission_key)
            .join(RolePermission, RolePermission.role_id == Role.id)
            .join(Permission, Permission.id == RolePermission.permission_id)
        )
    ).all()
    out: dict[str, set[str]] = {}
    for role_key, perm in rows:
        out.setdefault(role_key, set()).add(perm)
    _ROLE_PERMS = {k: frozenset(v) for k, v in out.items()}
    _ROLE_PERMS_AT = time.monotonic()
    return _ROLE_PERMS


def reset_role_permission_cache() -> None:
    global _ROLE_PERMS
    _ROLE_PERMS = None


# --------------------------------------------------------------------------- grants


async def active_grants(session: AsyncSession, user_id: uuid.UUID) -> list[GrantInfo]:
    now = utcnow()
    if _fs():
        return [
            GrantInfo(g.id, role_key, g.scope_type, g.scope_id, g.organization_id, g.expires_at)
            for g, role_key in await _repo().active_grants(user_id, now)
        ]
    rows = (
        await session.execute(
            select(RoleGrant, Role.role_key)
            .join(Role, Role.id == RoleGrant.role_id)
            .where(
                RoleGrant.user_id == user_id,
                RoleGrant.revoked_at.is_(None),
                or_(RoleGrant.expires_at.is_(None), RoleGrant.expires_at > now),
            )
        )
    ).all()
    return [
        GrantInfo(g.id, role_key, g.scope_type, g.scope_id, g.organization_id, g.expires_at)
        for g, role_key in rows
    ]


async def is_sole_admin(session: AsyncSession, user_id: uuid.UUID) -> bool:
    """True when ``user_id`` is the ONLY active user holding an active platform Admin grant.

    Owner decision 2026-11-11: the platform runs with a single Admin, so dual-control requests
    (SoD-05: requester != approver) would otherwise stay pending forever. A sole Admin may
    decide their own request (callers audit it as ``sole_admin``); as soon as a second active
    Admin exists, the normal second-person rule applies again. Read under a system context so
    RLS can never hide another Admin (which would wrongly allow self-approval).
    """
    from app.modules.identity import public as identity_public
    from app.modules.identity.pgctx import sys_scope
    from app.modules.rbac import public as rbac_public

    async with sys_scope(session, "rbac.sole_admin_check"):
        holders = sorted(
            {
                g.user_id
                for g, _k in await rbac_public.live_grants(
                    session, role_keys=["super_admin"], scope_type="platform"
                )
            },
            key=str,
        )
        users = await identity_public.get_users(session, holders)
    active = [u for u in holders if u in users and users[u].status == "active"]
    # compare as text: asyncpg returns its own UUID type, the principal carries uuid.UUID
    return [str(r) for r in active] == [str(user_id)]


def tier_for(grants: list[GrantInfo]) -> str:
    """Most privileged active grant (brief §1); no staff grant -> student."""
    best = "student"
    for g in grants:
        t = ROLES[g.role].session_tier if g.role in ROLES else "student"
        if TIER_RANK[t] > TIER_RANK[best]:
            best = t
    return best


def has_platform_staff_grant(grants: list[GrantInfo]) -> bool:
    return any(g.scope_type == "platform" and g.role != "student" for g in grants)


# --------------------------------------------------------------------------- scope helpers

CourseOrgLookup = Callable[[AsyncSession, uuid.UUID], Awaitable[uuid.UUID | None]]
_course_org_lookup: CourseOrgLookup | None = None


def register_course_org_lookup(fn: CourseOrgLookup | None) -> None:
    """Catalog module hook: owning organization of an org-private course (None = platform)."""
    global _course_org_lookup
    _course_org_lookup = fn


async def batch_org(session: AsyncSession, batch_id: uuid.UUID) -> uuid.UUID | None:
    from app.modules.orgs import public as orgs_public

    b = await orgs_public.get_batch(session, batch_id)
    return b.organization_id if b is not None else None


async def org_exists(session: AsyncSession, org_id: uuid.UUID) -> bool:
    from app.modules.orgs import public as orgs_public

    o = await orgs_public.get_org(session, org_id)
    return o is not None and o.deleted_at is None


async def _scope_chain(
    session: AsyncSession, scope: ScopeRef
) -> tuple[set[tuple[str, uuid.UUID | None]], uuid.UUID | None]:
    """Return (set of (scope_type, scope_id) that cover the target, target organization)."""
    chain: set[tuple[str, uuid.UUID | None]] = {("platform", None)}
    org: uuid.UUID | None = None
    if scope.scope_type == "organization" and scope.scope_id:
        org = scope.scope_id if await org_exists(session, scope.scope_id) else None
        if org is None:
            raise ProblemError("not_found")
        chain.add(("organization", org))
    elif scope.scope_type == "batch" and scope.scope_id:
        org = await batch_org(session, scope.scope_id)
        if org is None:
            raise ProblemError("not_found")
        chain |= {("organization", org), ("batch", scope.scope_id)}
    elif scope.scope_type == "course" and scope.scope_id:
        chain.add(("course", scope.scope_id))
        if _course_org_lookup is not None:
            org = await _course_org_lookup(session, scope.scope_id)
            if org is not None:
                chain.add(("organization", org))
    return chain, org


# ADM-41 (matrix row ``course.create/edit``: trainer = "C / O-private"): a trainer may author
# org-private courses of the organization they train in. Trainer grants are batch-scoped, and a
# batch never contains a course (matrix §2 containment), so for these permissions only, a batch
# grant covers an organization-owned target (the org itself, or an org-private course) when the
# batch belongs to that organization. Platform catalog authoring is never covered.
ORG_PRIVATE_VIA_BATCH: frozenset[str] = frozenset({"course.create", "course.edit"})


async def _org_private_batch_links(
    session: AsyncSession,
    principal: Principal,
    permission: str,
    scope: ScopeRef,
    target_org: uuid.UUID | None,
) -> set[tuple[str, uuid.UUID | None]]:
    if permission not in ORG_PRIVATE_VIA_BATCH or target_org is None:
        return set()
    if scope.scope_type not in ("organization", "course"):
        return set()
    out: set[tuple[str, uuid.UUID | None]] = set()
    for g in principal.grants:
        if g.scope_type == "batch" and g.scope_id is not None:
            if await batch_org(session, g.scope_id) == target_org:
                out.add(("batch", g.scope_id))
    return out


class RbacPermissionChecker:
    """``app.core.auth.PermissionChecker`` backed by role_grants/role_permissions."""

    async def has_permission(
        self, principal: Principal, permission: str, scope: ScopeRef, request: Request
    ) -> bool:
        from app.modules.sessions.service import system_session

        async with system_session("rbac.check") as session:
            perms = await role_permission_map(session)
            chain, target_org = await _scope_chain(session, scope)
            chain |= await _org_private_batch_links(session, principal, permission, scope, target_org)
            platform_holder = any(g.scope_type == "platform" for g in principal.grants)
            if target_org is not None and target_org not in principal.org_ids and not platform_holder:
                # TI-02: existence is not disclosed; record the probe.
                await audit(
                    session,
                    principal,
                    "rbac.cross_tenant_denied",
                    "organization",
                    target_org,
                    after={"permission": permission, "scope_type": scope.scope_type},
                )
                deny_404 = True
            else:
                deny_404 = False
        if deny_404:
            log.warning("cross_tenant_denied", permission=permission, scope_type=scope.scope_type)
            raise ProblemError("not_found")
        for g in principal.grants:
            if permission in perms.get(g.role, frozenset()) and (g.scope_type, g.scope_id) in chain:
                return True
        return False


def principal_can(
    principal: Principal,
    perms: dict[str, frozenset[str]],
    permission: str,
    chain: set[tuple[str, uuid.UUID | None]],
) -> bool:
    return any(
        permission in perms.get(g.role, frozenset()) and (g.scope_type, g.scope_id) in chain
        for g in principal.grants
    )


async def check_permission(
    session: AsyncSession, principal: Principal, permission: str, scope: ScopeRef
) -> bool:
    """In-transaction permission test (no TI-02 raise) for service-level decisions."""
    perms = await role_permission_map(session)
    chain, org = await _scope_chain(session, scope)
    chain |= await _org_private_batch_links(session, principal, permission, scope, org)
    return principal_can(principal, perms, permission, chain)


# --------------------------------------------------------------------------- grant lifecycle


def payload_hash(payload: dict[str, Any]) -> bytes:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).digest()


async def _role(session: AsyncSession, role_key: str) -> Role:
    if _fs():
        role = await _repo().role_by_key(role_key)
    else:
        role = (await session.execute(select(Role).where(Role.role_key == role_key))).scalar_one_or_none()
    if role is None:
        raise ProblemError(
            "validation_failed",
            422,
            errors=[{"field": "role_key", "code": "unknown_role", "message": "Unknown role"}],
        )
    return role


async def resolve_grant_scope(
    session: AsyncSession, role: Role, scope_type: str, scope_id: uuid.UUID | None
) -> uuid.UUID | None:
    """Validate scope against the role and return the owning organization_id.

    ``organization`` is never a grant scope any more (single-company)."""
    if scope_type not in GRANT_SCOPE_TYPES or scope_type not in role.allowed_scope_types:
        raise ProblemError(
            "validation_failed",
            422,
            errors=[
                {
                    "field": "scope_type",
                    "code": "scope_not_allowed",
                    "message": f"{role.role_key} cannot be granted at {scope_type}",
                }
            ],
        )
    if (scope_type == "platform") != (scope_id is None):
        raise ProblemError(
            "validation_failed",
            422,
            errors=[{"field": "scope_id", "code": "invalid", "message": "scope_id mismatch"}],
        )
    if scope_type == "batch":
        assert scope_id is not None
        org = await batch_org(session, scope_id)
        if org is None:
            raise ProblemError("not_found")
        return org
    if scope_type == "course" and scope_id is not None and _course_org_lookup is not None:
        return await _course_org_lookup(session, scope_id)
    return None


async def check_sod(session: AsyncSession, user_id: uuid.UUID, role_key: str) -> None:
    """SoD-10 exclusive role pairs. Single-company (D2): Finance admin and Security reviewer
    were folded into Admin, so no pair is left today; dual control is "two different admins"
    (maker != checker, enforced per approval). Kept so a future pair is enforced here."""
    held = {g.role for g in await active_grants(session, user_id)}
    for a, b in EXCLUSIVE_ROLE_PAIRS:
        if (role_key == a and b in held) or (role_key == b and a in held):
            raise ProblemError("sod_violation", rule="SoD-10")


async def create_grant(
    session: AsyncSession,
    actor: Principal | AuditActor,
    *,
    user_id: uuid.UUID,
    role_key: str,
    scope_type: str,
    scope_id: uuid.UUID | None,
    expires_at: datetime | None,
    reason: str | None,
    granted_by: uuid.UUID,
) -> uuid.UUID:
    role = await _role(session, role_key)
    org_id = await resolve_grant_scope(session, role, scope_type, scope_id)
    await check_sod(session, user_id, role_key)
    if _fs():
        gid = uuid7()
        await _repo().create_grant(
            RoleGrant(
                id=gid,
                user_id=user_id,
                role_id=role.id,
                scope_type=scope_type,
                scope_id=scope_id,
                organization_id=org_id,
                granted_by=granted_by,
                expires_at=expires_at,
                reason=reason,
            ),
            role_key,
        )
        await audit(
            session,
            actor,
            "rbac.grant.created",
            "role_grant",
            gid,
            organization_id=org_id,
            subject_user_id=user_id,
            reason=reason,
            after={
                "role": role_key,
                "scope_type": scope_type,
                "scope_id": scope_id,
                "expires_at": expires_at,
            },
        )
        await _rotate_grantee_sessions(session, user_id, actor, role_key=role_key)
        return gid
    existing = (
        await session.execute(
            select(RoleGrant.id).where(
                RoleGrant.user_id == user_id,
                RoleGrant.role_id == role.id,
                RoleGrant.scope_type == scope_type,
                RoleGrant.scope_id.is_not_distinct_from(scope_id),
                RoleGrant.revoked_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise ProblemError("invalid_state_transition", current_state="granted", allowed=["revoke"])
    gid = uuid7()
    session.add(
        RoleGrant(
            id=gid,
            user_id=user_id,
            role_id=role.id,
            scope_type=scope_type,
            scope_id=scope_id,
            organization_id=org_id,
            granted_by=granted_by,
            expires_at=expires_at,
            reason=reason,
        )
    )
    await session.flush()
    await audit(
        session,
        actor,
        "rbac.grant.created",
        "role_grant",
        gid,
        organization_id=org_id,
        subject_user_id=user_id,
        reason=reason,
        after={"role": role_key, "scope_type": scope_type, "scope_id": scope_id, "expires_at": expires_at},
    )
    await _rotate_grantee_sessions(session, user_id, actor, role_key=role_key)
    return gid


async def revoke_grant(
    session: AsyncSession,
    actor: Principal | AuditActor,
    grant_id: uuid.UUID,
    revoked_by: uuid.UUID,
    reason: str | None,
) -> RoleGrant:
    if _fs():
        found = await _repo().get_grant(grant_id)
        fs_grant = await _repo().revoke_grant(grant_id, revoked_by, utcnow())
        await audit(
            session,
            actor,
            "rbac.grant.revoked",
            "role_grant",
            fs_grant.id,
            organization_id=fs_grant.organization_id,
            subject_user_id=fs_grant.user_id,
            reason=reason,
        )
        await _rotate_grantee_sessions(session, fs_grant.user_id, actor, role_key=found[1] if found else None)
        return fs_grant
    grant = (await session.execute(select(RoleGrant).where(RoleGrant.id == grant_id))).scalar_one_or_none()
    if grant is None:
        raise ProblemError("not_found")
    if grant.revoked_at is not None:
        raise ProblemError("invalid_state_transition", current_state="revoked", allowed=[])
    grant.revoked_at = utcnow()
    grant.revoked_by = revoked_by
    await session.flush()
    await audit(
        session,
        actor,
        "rbac.grant.revoked",
        "role_grant",
        grant.id,
        organization_id=grant.organization_id,
        subject_user_id=grant.user_id,
        reason=reason,
    )
    role = await session.get(Role, grant.role_id)
    await _rotate_grantee_sessions(
        session, grant.user_id, actor, role_key=role.role_key if role is not None else None
    )
    return grant


async def _rotate_grantee_sessions(
    session: AsyncSession,
    user_id: uuid.UUID,
    actor: Principal | AuditActor,
    *,
    role_key: str | None = None,
) -> None:
    """A grant change forces re-login (session_tier is fixed at login). The grantee's sessions
    are not visible to an org-scoped granter under RLS, so this runs as a named system job and
    then restores the caller's tenant context."""
    from app.modules.sessions.service import revoke_all_sessions

    by = actor.user_id if isinstance(actor, Principal) else None
    # An Admin changing their own NON-Admin grant (granting: only "trainer of a batch" is
    # possible, see rbac.router ``_self_grant_allowed``; or revoking their own trainer grant)
    # keeps the session they are using: it is already at the top ("privileged") tier, so a
    # re-login could not change it, and permissions come from the live grants on every request.
    # Their other sessions still end. This is what lets the Admin open their Teacher portal
    # without signing in again. Changes to an Admin grant itself always end every session.
    keep = (
        actor.session_id
        if isinstance(actor, Principal)
        and actor.user_id == user_id
        and actor.tier == "privileged"
        and role_key is not None
        and not is_dual_role(role_key)
        else None
    )
    from app.modules.identity.pgctx import sys_scope

    async with sys_scope(session, "rbac.session_rotation"):
        await revoke_all_sessions(session, user_id, "privilege_change", ended_by=by, except_session_id=keep)
        if session:
            await session.flush()


async def create_approval_request(
    session: AsyncSession,
    principal: Principal,
    *,
    action_type: str,
    target_type: str,
    target_id: uuid.UUID | None,
    payload: dict[str, Any],
    reason: str,
    required_approver_role: str,
    organization_id: uuid.UUID | None = None,
) -> ApprovalRequest:
    req = ApprovalRequest(
        id=uuid7(),
        action_type=action_type,
        organization_id=organization_id,
        target_type=target_type,
        target_id=target_id,
        payload=json.loads(json.dumps(payload, default=str)),
        payload_hash=payload_hash(payload),
        requested_by=principal.user_id,
        request_reason=reason,
        required_approver_role=required_approver_role,
        status="pending",
        expires_at=utcnow() + APPROVAL_TTL,
    )
    if _fs():
        req = await _repo().add_approval(req)
    else:
        session.add(req)
        await session.flush()
    await audit(
        session,
        principal,
        "approval.requested",
        "approval_request",
        req.id,
        organization_id=organization_id,
        reason=reason,
        after={"action_type": action_type, "target_type": target_type, "target_id": target_id},
    )
    return req


def is_dual_role(role_key: str) -> bool:
    return role_key in DUAL_ROLES


async def grants_in_scope(
    session: AsyncSession,
    *,
    user_id: uuid.UUID | None,
    role_key: str | None,
    scope_type: str | None,
    scope_id: uuid.UUID | None,
    org_ids: tuple[uuid.UUID, ...] | None,
) -> list[tuple[RoleGrant, str]]:
    if _fs():
        return await _repo().query_grants(
            user_id=user_id, role_key=role_key, scope_type=scope_type, scope_id=scope_id, org_ids=org_ids
        )
    q = (
        select(RoleGrant, Role.role_key)
        .join(Role, Role.id == RoleGrant.role_id)
        .where(RoleGrant.revoked_at.is_(None))
    )
    if user_id:
        q = q.where(RoleGrant.user_id == user_id)
    if role_key:
        q = q.where(Role.role_key == role_key)
    if scope_type:
        q = q.where(RoleGrant.scope_type == scope_type)
    if scope_id:
        q = q.where(RoleGrant.scope_id == scope_id)
    if org_ids is not None:
        q = q.where(and_(RoleGrant.organization_id.is_not(None), RoleGrant.organization_id.in_(org_ids)))
    rows = (await session.execute(q.order_by(RoleGrant.granted_at.desc()).limit(500))).all()
    return [(g, rk) for g, rk in rows]


async def expire_stale_approvals(session: AsyncSession) -> int:
    if _fs():
        return await _repo().expire_stale_approvals(utcnow())
    r = await session.execute(
        update(ApprovalRequest)
        .where(ApprovalRequest.status == "pending", ApprovalRequest.expires_at <= utcnow())
        .values(status="expired")
    )
    return int(getattr(r, "rowcount", 0) or 0)
