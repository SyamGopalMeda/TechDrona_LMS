"""Store-neutral rbac API for other modules (``TD_STORE_RBAC`` = postgres | firestore).

Replaces direct SQL on ``roles``, ``permissions``, ``role_permissions``, ``role_grants`` and
``approval_requests`` in admin, analytics, commerce, learning, notifications, security,
support and the seeds. Approvals: read with ``find_approvals`` / ``get_approval``; to decide or
execute one, mutate the returned object and call ``save_approval`` (Firestore: only a still
``pending`` request can be decided, which keeps the single-execution rule).
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Iterable
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.firestore.backend import uses_firestore
from app.core.time import utcnow
from app.modules.rbac.models import ApprovalRequest, Permission, Role, RoleGrant, RolePermission


def _fs() -> bool:
    return uses_firestore("rbac")


def _repo() -> Any:
    from app.modules.rbac.repo_firestore import system_repo

    return system_repo()


# --------------------------------------------------------------------------- roles / grants


async def roles(session: AsyncSession) -> list[Role]:
    """Every role, by ``role_key``."""
    if _fs():
        return await _repo().roles()
    return list((await session.execute(select(Role).order_by(Role.role_key))).scalars().all())


async def role_by_key(session: AsyncSession, role_key: str) -> Role | None:
    if _fs():
        return await _repo().role_by_key(role_key)
    return (await session.execute(select(Role).where(Role.role_key == role_key))).scalar_one_or_none()


async def live_grants(
    session: AsyncSession,
    *,
    user_ids: Iterable[uuid.UUID] | None = None,
    role_keys: Iterable[str] | None = None,
    exclude_role_keys: Iterable[str] | None = None,
    scope_type: str | None = None,
    include_expired: bool = False,
    now: datetime | None = None,
) -> list[tuple[RoleGrant, str]]:
    """Unrevoked grants (and unexpired unless ``include_expired``) as ``(grant, role_key)``."""
    now = now or utcnow()
    uids = set(user_ids) if user_ids is not None else None
    keys = set(role_keys) if role_keys is not None else None
    excl = set(exclude_role_keys or ())
    if _fs():
        from app.modules.rbac.store_specs import GRANTS

        f: list[Any] = [("revoked_at", "==", None)]
        if scope_type:
            f.append(("scope_type", "==", scope_type))
        repo = _repo()
        if uids is not None and len(uids) <= 30:
            docs = []
            for u in uids:
                docs += await repo._all(GRANTS, user_id=u, filters=tuple(f))
        else:
            docs = await repo._all(GRANTS, filters=tuple(f))
        rows = [repo._grant(d) for d in docs]
    else:
        q = (
            select(RoleGrant, Role.role_key)
            .join(Role, Role.id == RoleGrant.role_id)
            .where(RoleGrant.revoked_at.is_(None))
        )
        if uids is not None:
            q = q.where(RoleGrant.user_id.in_(uids))
        if keys is not None:
            q = q.where(Role.role_key.in_(keys))
        if scope_type:
            q = q.where(RoleGrant.scope_type == scope_type)
        if not include_expired:
            q = q.where(or_(RoleGrant.expires_at.is_(None), RoleGrant.expires_at > now))
        rows = [(g, k) for g, k in (await session.execute(q)).all()]
    return [
        (g, k)
        for g, k in rows
        if (uids is None or g.user_id in uids)
        and (keys is None or k in keys)
        and k not in excl
        and (include_expired or g.expires_at is None or g.expires_at > now)
    ]


async def user_ids_with_role(
    session: AsyncSession, role_keys: Iterable[str], *, scope_type: str | None = None
) -> set[uuid.UUID]:
    return {g.user_id for g, _k in await live_grants(session, role_keys=role_keys, scope_type=scope_type)}


async def staff_user_ids(session: AsyncSession) -> set[uuid.UUID]:
    """Users holding any unrevoked non-student grant (expired included, as admin counts did)."""
    return {
        g.user_id
        for g, _k in await live_grants(session, exclude_role_keys=("student",), include_expired=True)
    }


async def user_ids_with_permission(
    session: AsyncSession, permission_key: str, user_ids: Iterable[uuid.UUID]
) -> set[uuid.UUID]:
    """Which of ``user_ids`` hold a live grant whose role carries ``permission_key`` (any scope)."""
    from app.modules.rbac.service import role_permission_map

    perms = await role_permission_map(session)
    roles_with = {r for r, ps in perms.items() if permission_key in ps}
    return {g.user_id for g, _k in await live_grants(session, user_ids=user_ids, role_keys=roles_with)}


async def get_grant(session: AsyncSession, grant_id: uuid.UUID) -> RoleGrant | None:
    if _fs():
        got = await _repo().get_grant(grant_id)
        return got[0] if got else None
    return await session.get(RoleGrant, grant_id)


async def add_grant(session: AsyncSession, grant: RoleGrant, role_key: str) -> RoleGrant:
    """Insert a prepared grant without the service checks (seeds only; routes use
    ``rbac.service.create_grant``)."""
    if _fs():
        return await _repo().create_grant(grant, role_key)
    session.add(grant)
    await session.flush()
    return grant


async def role_permission_pairs(session: AsyncSession) -> list[tuple[str, str]]:
    """``(role_key, permission_key)`` for every role_permissions row."""
    if _fs():
        from app.modules.identity.textsort import text_key
        from app.modules.rbac.service import role_permission_map

        pairs = [(r, p) for r, ps in (await role_permission_map(session)).items() for p in ps]
        return sorted(pairs, key=lambda t: (text_key(t[0]), text_key(t[1])))
    q = (
        select(Role.role_key, Permission.permission_key)
        .join(RolePermission, RolePermission.role_id == Role.id)
        .join(Permission, Permission.id == RolePermission.permission_id)
        .order_by(Role.role_key, Permission.permission_key)
    )
    return [(r, p) for r, p in (await session.execute(q)).all()]


# --------------------------------------------------------------------------- approvals


async def get_approval(
    session: AsyncSession, approval_id: uuid.UUID, *, for_update: bool = False
) -> ApprovalRequest | None:
    """One approval. ``for_update``: Postgres row lock (Firestore: ``save_approval`` re-checks
    that the request is still pending, inside its transaction)."""
    if _fs():
        return await _repo().get_approval(approval_id)
    q = select(ApprovalRequest).where(ApprovalRequest.id == approval_id)
    if for_update:
        q = q.with_for_update()
    return (await session.execute(q)).scalar_one_or_none()


async def find_approvals(
    session: AsyncSession,
    *,
    action_type: str | None = None,
    action_types: Iterable[str] | None = None,
    status: str | Iterable[str] | None = None,
    target_type: str | None = None,
    target_id: uuid.UUID | None = None,
    target_ids: Iterable[uuid.UUID] | None = None,
    requested_by: uuid.UUID | None = None,
    exclude_requested_by: uuid.UUID | None = None,
    request_reason: str | None = None,
    expires_after: datetime | None = None,
    expires_until: datetime | None = None,
    created_until: datetime | None = None,
    order: str = "created_desc",
) -> list[ApprovalRequest]:
    """Approvals matching every filter. ``order``: ``created_desc`` (default) or ``expires_asc``."""
    statuses = {status} if isinstance(status, str) else (set(status) if status is not None else None)
    types = set(action_types) if action_types is not None else None
    tids = set(target_ids) if target_ids is not None else None
    if _fs():
        from app.modules.rbac.store_specs import APPROVALS

        f: list[Any] = []
        if action_type:
            f.append(("action_type", "==", action_type))
        if statuses is not None and len(statuses) == 1:
            f.append(("status", "==", next(iter(statuses))))
        if target_id is not None:
            f.append(("target_id", "==", str(target_id)))
        rows: list[ApprovalRequest] = await _repo()._objs(ApprovalRequest, APPROVALS, filters=tuple(f))
    else:
        q = select(ApprovalRequest)
        if action_type:
            q = q.where(ApprovalRequest.action_type == action_type)
        if statuses is not None:
            q = q.where(ApprovalRequest.status.in_(statuses))
        if target_id is not None:
            q = q.where(ApprovalRequest.target_id == target_id)
        if tids is not None:
            q = q.where(ApprovalRequest.target_id.in_(tids))
        if types is not None:
            q = q.where(ApprovalRequest.action_type.in_(types))
        rows = list((await session.execute(q)).scalars().all())
    rows = [
        r
        for r in rows
        if (statuses is None or r.status in statuses)
        and (types is None or r.action_type in types)
        and (target_type is None or r.target_type == target_type)
        and (tids is None or r.target_id in tids)
        and (requested_by is None or r.requested_by == requested_by)
        and (exclude_requested_by is None or r.requested_by != exclude_requested_by)
        and (request_reason is None or r.request_reason == request_reason)
        and (expires_after is None or r.expires_at > expires_after)
        and (expires_until is None or r.expires_at <= expires_until)
        and (created_until is None or r.created_at <= created_until)
    ]
    if order == "expires_asc":
        return sorted(rows, key=lambda r: (r.expires_at, str(r.id)))
    return sorted(rows, key=lambda r: (r.created_at, str(r.id)), reverse=True)


async def save_approval(session: AsyncSession, req: ApprovalRequest) -> ApprovalRequest:
    """Persist a decision / execution made on ``req``. Firestore: refused
    (``invalid_state_transition``) unless the stored request is still ``pending`` — except
    for ``executed_at`` stamping of an already approved request."""
    if _fs():
        stored = await _repo().get_approval(req.id)
        if stored is not None and stored.status != "pending":
            return await _repo().save_approval(req)
        changes = {
            k: getattr(req, k)
            for k in (
                "status",
                "decided_by",
                "decided_at",
                "decision_note",
                "executed_at",
                "sole_admin_decision",
            )
        }
        return await _repo().decide_approval(req.id, **changes)
    await session.flush()
    return req


async def get_approvals(
    session: AsyncSession, approval_ids: Iterable[uuid.UUID]
) -> dict[uuid.UUID, ApprovalRequest]:
    """Batched lookup by id (e.g. the approvals joined to export jobs)."""
    ids = list(dict.fromkeys(approval_ids))
    if not ids:
        return {}
    if _fs():
        from app.modules.identity.fs_codec import doc_obj
        from app.modules.rbac.store_specs import APPROVALS

        docs = await _repo().store.get_many(APPROVALS, [str(i) for i in ids])
        return {uuid.UUID(k): doc_obj(ApprovalRequest, d.data) for k, d in docs.items()}
    rows = (await session.execute(select(ApprovalRequest).where(ApprovalRequest.id.in_(ids)))).scalars().all()
    return {r.id: r for r in rows}


# --------------------------------------------------------------------------- decisions (single execution)


@asynccontextmanager
async def decision(
    session: AsyncSession,
    req: ApprovalRequest,
    *,
    status: str,
    decided_by: uuid.UUID | None,
    note: str | None = None,
    sole_admin: bool = False,
    decided_at: datetime | None = None,
) -> AsyncIterator[ApprovalRequest]:
    """Claim the ``pending -> status`` transition of ``req`` for the block that executes it.

    Postgres: sets the fields on the locked row; an exception rolls everything back.
    Firestore: the claim is one transaction that only the first caller wins (others get
    409 ``invalid_state_transition``). If the block raises, the claim is **undone** (back to
    ``pending``, decision fields cleared), the state a Postgres rollback leaves; then the error
    propagates. ``req`` is updated in place; mark it executed with ``mark_executed``."""
    from app.modules.identity import clock, fs_uow

    req.status = status
    req.decided_by = decided_by
    # a cancellation keeps decided_at NULL (admin.approvals.cancel)
    req.decided_at = decided_at or (None if status == "cancelled" else clock.now())
    req.decision_note = note
    req.sole_admin_decision = sole_admin
    if not _fs():
        await session.flush()
        yield req
        return
    fs_uow.discard(req)
    from app.modules.identity.fs_journal import journal

    # One undo journal for the claim and every Firestore write of the action (grants, sessions,
    # users, factors, ... written through the access repositories, plus any module that joins
    # with ``JournalingStore`` / ``on_rollback``). If the block raises, every touched document is
    # restored to its before-image -- the approval back to ``pending`` included -- as the single
    # Postgres transaction would roll back. Audit rows are buffered to the request commit point
    # (core.audit) and dropped with the failed request.
    async with journal():
        await _repo().decide_approval(
            req.id,
            status=status,
            decided_by=decided_by,
            decided_at=req.decided_at,
            decision_note=note,
            sole_admin_decision=sole_admin,
        )
        yield req


async def mark_executed(session: AsyncSession, req: ApprovalRequest) -> ApprovalRequest:
    """``approved -> executed`` (call inside the ``decision`` block, after the action ran)."""
    from app.modules.identity import clock

    req.status = "executed"
    req.executed_at = clock.now()
    if _fs():
        return await _repo().save_approval(req)
    await session.flush()
    return req


async def expire_if_due(session: AsyncSession, req: ApprovalRequest) -> bool:
    """Persist ``pending -> expired`` for a past-due request now (ADM-23: the caller then
    answers 409 without raising, so the change stays on either store)."""
    from app.modules.identity import clock, fs_uow

    if req.status != "pending" or req.expires_at > clock.now():
        return False
    req.status = "expired"
    if _fs():
        fs_uow.discard(req)
        from app.core.errors import ProblemError

        try:
            await _repo().decide_approval(req.id, status="expired")
        except ProblemError:
            pass  # decided meanwhile
    else:
        await session.flush()
    return True


# --------------------------------------------------------------------------- re-exports for other modules


async def revoke_grant(
    session: AsyncSession, actor: Any, grant_id: uuid.UUID, revoked_by: uuid.UUID, reason: str | None
) -> RoleGrant:
    """Revoke one grant with the full service semantics (audit, grantee sessions rotated);
    ``not_found`` / ``invalid_state_transition`` as RBAC-06. Used by break-glass (data-ops)."""
    from app.modules.rbac.service import revoke_grant as _revoke

    return await _revoke(session, actor, grant_id, revoked_by, reason)


async def role_permission_map(session: AsyncSession) -> dict[str, frozenset[str]]:
    """role_key -> permission keys (cached 60 s), either store."""
    from app.modules.rbac.service import role_permission_map as _rpm

    return await _rpm(session)


async def batch_org(session: AsyncSession, batch_id: uuid.UUID) -> uuid.UUID | None:
    """Owning organization of a batch (``None`` if unknown), either store."""
    from app.modules.rbac.service import batch_org as _bo

    return await _bo(session, batch_id)
