"""Firestore repository of the rbac module (``TD_STORE_RBAC=firestore``).

``service.py`` dispatches here when the switch is on. Grants carry a denormalised ``role_key``
so ``active_grants`` (every request, via ``build_principal``) is one equality query.

Atomicity: ``ux_rg_live`` -> ``role_grants_live`` document created with the grant and deleted
with the revoke; ``ux_apr_case_decision_pending`` -> ``approvals_case_pending``; approval
decisions are a transaction that requires ``status == 'pending'`` (single execution, as the
Postgres ``FOR UPDATE`` + status check). Maker != checker stays in the router.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from app.core.errors import ProblemError
from app.core.firestore.errors import UniqueViolationError
from app.core.firestore.repository import platform_only
from app.core.firestore.store import Doc, ScopedTransaction
from app.core.time import utcnow
from app.modules.identity.fs_base import AccessRepo, write_changes
from app.modules.identity.fs_codec import doc_obj, obj_doc
from app.modules.rbac.models import ApprovalRequest, Permission, Role, RoleGrant
from app.modules.rbac.store_specs import (
    APPROVALS,
    CASE_ACTION,
    CASE_PENDING,
    GRANTS,
    GRANTS_LIVE,
    PERMISSIONS,
    ROLE_PERMS,
    ROLES,
    live_grant_id,
)

PERM = "rbac.grant.read"
JOB = "rbac.store"


class RbacRepo(AccessRepo):
    # ------------------------------------------------------------------ catalogue

    @platform_only(PERM)
    async def roles(self) -> list[Role]:
        from app.modules.identity.textsort import text_key

        return sorted(await self._objs(Role, ROLES), key=lambda r: text_key(r.role_key))

    @platform_only(PERM)
    async def role_by_key(self, role_key: str) -> Role | None:
        rows = await self._objs(Role, ROLES, filters=(("role_key", "==", role_key),))
        return rows[0] if rows else None

    @platform_only(PERM)
    async def role_permission_map(self) -> dict[str, frozenset[str]]:
        roles = {str(r.id): r.role_key for r in await self._objs(Role, ROLES)}
        perms = {str(p.id): p.permission_key for p in await self._objs(Permission, PERMISSIONS)}
        out: dict[str, set[str]] = {}
        for d in await self._all(ROLE_PERMS):
            rk, pk = roles.get(d["role_id"]), perms.get(d["permission_id"])
            if rk and pk:
                out.setdefault(rk, set()).add(pk)
        return {k: frozenset(v) for k, v in out.items()}

    # ------------------------------------------------------------------ grants

    @staticmethod
    def _grant(d: Doc) -> tuple[RoleGrant, str]:
        return doc_obj(RoleGrant, d.data), d["role_key"]

    @platform_only(PERM)
    async def grants_for(self, user_id: uuid.UUID) -> list[tuple[RoleGrant, str]]:
        return [self._grant(d) for d in await self._all(GRANTS, user_id=user_id)]

    @platform_only(PERM)
    async def active_grants(self, user_id: uuid.UUID, now: datetime) -> list[tuple[RoleGrant, str]]:
        rows = await self._all(GRANTS, user_id=user_id, filters=(("revoked_at", "==", None),))
        out = [self._grant(d) for d in rows]
        return [(g, k) for g, k in out if g.expires_at is None or g.expires_at > now]

    @platform_only(PERM)
    async def get_grant(self, grant_id: uuid.UUID) -> tuple[RoleGrant, str] | None:
        d = await self.store.get(GRANTS, str(grant_id))
        return self._grant(d) if d else None

    @platform_only(PERM)
    async def live_grant_holders(self, role_key: str, scope_type: str) -> list[uuid.UUID]:
        now = utcnow()
        rows = await self._all(
            GRANTS,
            filters=(
                ("role_key", "==", role_key),
                ("scope_type", "==", scope_type),
                ("revoked_at", "==", None),
            ),
        )
        return sorted(
            {uuid.UUID(d["user_id"]) for d in rows if d.get("expires_at") is None or d["expires_at"] > now},
            key=str,
        )

    @platform_only(PERM)
    async def query_grants(
        self,
        *,
        user_id: uuid.UUID | None,
        role_key: str | None,
        scope_type: str | None,
        scope_id: uuid.UUID | None,
        org_ids: tuple[uuid.UUID, ...] | None,
        limit: int = 500,
    ) -> list[tuple[RoleGrant, str]]:
        """``grants_in_scope``: live grants, newest ``granted_at`` first, at most ``limit``."""
        filters: list[Any] = [("revoked_at", "==", None)]
        if role_key:
            filters.append(("role_key", "==", role_key))
        if scope_type:
            filters.append(("scope_type", "==", scope_type))
        if scope_id:
            filters.append(("scope_id", "==", str(scope_id)))
        rows = [
            self._grant(d) for d in await self._all(GRANTS, user_id=user_id or None, filters=tuple(filters))
        ]
        if org_ids is not None:
            allowed = set(org_ids)
            rows = [(g, k) for g, k in rows if g.organization_id is not None and g.organization_id in allowed]
        rows.sort(key=lambda t: (t[0].granted_at, str(t[0].id)), reverse=True)
        return rows[:limit]

    @platform_only(PERM)
    async def create_grant(self, grant: RoleGrant, role_key: str) -> RoleGrant:
        """Insert a grant; ``invalid_state_transition`` when the same live grant exists."""
        lid = live_grant_id(grant.user_id, grant.role_id, grant.scope_type, grant.scope_id)

        async def fn(tx: ScopedTransaction) -> Doc:
            ref = await tx.get(GRANTS_LIVE, lid)
            if ref is not None:
                cur = await tx.get(GRANTS, ref["grant_id"])
                if cur is not None and cur.get("revoked_at") is None:
                    raise ProblemError(
                        "invalid_state_transition", current_state="granted", allowed=["revoke"]
                    )
            d = await tx.create(GRANTS, {**self.new_doc(grant), "role_key": role_key}, doc_id=str(grant.id))
            await tx.put(GRANTS_LIVE, lid, {"grant_id": str(grant.id)})
            return d

        return doc_obj(RoleGrant, (await self.store.run_transaction(fn)).data)

    @platform_only(PERM)
    async def revoke_grant(self, grant_id: uuid.UUID, revoked_by: uuid.UUID, now: datetime) -> RoleGrant:
        """Set ``revoked_at`` once (``not_found`` / ``invalid_state_transition`` as Postgres)."""

        async def fn(tx: ScopedTransaction) -> Doc:
            cur = await tx.get(GRANTS, str(grant_id))
            if cur is None:
                raise ProblemError("not_found")
            if cur.get("revoked_at") is not None:
                raise ProblemError("invalid_state_transition", current_state="revoked", allowed=[])
            g = doc_obj(RoleGrant, cur.data)
            lid = live_grant_id(g.user_id, g.role_id, g.scope_type, g.scope_id)
            ref = await tx.get(GRANTS_LIVE, lid)
            d = await tx.update_read(GRANTS, cur, {"revoked_at": now, "revoked_by": revoked_by})
            if ref is not None and ref["grant_id"] == str(grant_id):
                await tx.delete_read(GRANTS_LIVE, lid, ref.data)
            return d

        return doc_obj(RoleGrant, (await self.store.run_transaction(fn)).data)

    @platform_only(PERM)
    async def save_grant(self, grant: RoleGrant) -> RoleGrant:
        """Overwrite a grant (keeps ``role_key``); a revoked grant frees its live slot."""
        lid = live_grant_id(grant.user_id, grant.role_id, grant.scope_type, grant.scope_id)

        async def fn(tx: ScopedTransaction) -> Doc:
            cur = await tx.get(GRANTS, str(grant.id))
            ref = await tx.get(GRANTS_LIVE, lid)
            if cur is None:
                raise ProblemError("not_found")
            d = await tx.update_read(GRANTS, cur, write_changes(obj_doc(grant)))
            if grant.revoked_at is not None and ref is not None and ref["grant_id"] == str(grant.id):
                await tx.delete_read(GRANTS_LIVE, lid, ref.data)
            return d

        return doc_obj(RoleGrant, (await self.store.run_transaction(fn)).data)

    # ------------------------------------------------------------------ approvals

    @platform_only(PERM)
    async def add_approval(self, req: ApprovalRequest) -> ApprovalRequest:
        async def fn(tx: ScopedTransaction) -> Doc:
            case = req.action_type == CASE_ACTION and req.status == "pending" and req.target_id is not None
            if case:
                ref = await tx.get(CASE_PENDING, str(req.target_id))
                if ref is not None:
                    cur = await tx.get(APPROVALS, ref["approval_id"])
                    if cur is not None and cur.get("status") == "pending":
                        raise UniqueViolationError(CASE_PENDING, str(req.target_id))
            d = await tx.create(APPROVALS, self.new_doc(req), doc_id=str(req.id))
            if case:
                await tx.put(CASE_PENDING, str(req.target_id), {"approval_id": str(req.id)})
            return d

        return doc_obj(ApprovalRequest, (await self.store.run_transaction(fn)).data)

    @platform_only(PERM)
    async def get_approval(self, approval_id: uuid.UUID) -> ApprovalRequest | None:
        return await self._get_obj(ApprovalRequest, APPROVALS, str(approval_id))

    @platform_only(PERM)
    async def approvals(self, *, status: str | None = None) -> list[ApprovalRequest]:
        f = (("status", "==", status),) if status else ()
        rows = await self._objs(ApprovalRequest, APPROVALS, filters=f)
        return sorted(rows, key=lambda r: (r.created_at, str(r.id)), reverse=True)

    @platform_only(PERM)
    async def restore_pending(
        self, approval_id: uuid.UUID, claimed_by: uuid.UUID, claimed_status: str
    ) -> bool:
        """Undo a decision claim (compensation when the action executed after the claim fails):
        back to ``pending`` with the decision fields cleared, i.e. the state a Postgres rollback
        leaves. Only the claimer's own, still un-executed claim is undone."""

        async def fn(tx: ScopedTransaction) -> bool:
            cur = await tx.get(APPROVALS, str(approval_id))
            if cur is None or cur.get("status") != claimed_status or cur.get("decided_by") != str(claimed_by):
                return False
            ref = None
            if cur.get("action_type") == CASE_ACTION and cur.get("target_id"):
                ref = await tx.get(CASE_PENDING, cur["target_id"])
            await tx.update_read(
                APPROVALS,
                cur,
                {
                    "status": "pending",
                    "decided_by": None,
                    "decided_at": None,
                    "decision_note": None,
                    "sole_admin_decision": False,
                    "executed_at": None,
                },
            )
            if ref is None and cur.get("action_type") == CASE_ACTION and cur.get("target_id"):
                await tx.put(CASE_PENDING, cur["target_id"], {"approval_id": str(approval_id)})
            return True

        return await self.store.run_transaction(fn)

    @platform_only(PERM)
    async def decide_approval(self, approval_id: uuid.UUID, **changes: Any) -> ApprovalRequest:
        """Apply a decision to a **pending** request (single execution under concurrency)."""

        async def fn(tx: ScopedTransaction) -> Doc:
            cur = await tx.get(APPROVALS, str(approval_id))
            if cur is None:
                raise ProblemError("not_found")
            if cur.get("status") != "pending":
                raise ProblemError("invalid_state_transition", current_state=cur.get("status"), allowed=[])
            ref = None
            if cur.get("action_type") == CASE_ACTION and cur.get("target_id"):
                ref = await tx.get(CASE_PENDING, cur["target_id"])
            req = doc_obj(ApprovalRequest, cur.data)
            for k, v in changes.items():
                setattr(req, k, v)
            d = await tx.update_read(APPROVALS, cur, write_changes(obj_doc(req)))
            if ref is not None and ref["approval_id"] == str(approval_id) and req.status != "pending":
                await tx.delete_read(CASE_PENDING, ref.id, ref.data)
            return d

        return doc_obj(ApprovalRequest, (await self.store.run_transaction(fn)).data)

    @platform_only(PERM)
    async def save_approval(self, req: ApprovalRequest) -> ApprovalRequest:
        return await self._upsert(APPROVALS, str(req.id), req)

    @platform_only(PERM)
    async def expire_stale_approvals(self, now: datetime) -> int:
        n = 0
        for req in await self.approvals(status="pending"):
            if req.expires_at <= now:
                try:
                    await self.decide_approval(req.id, status="expired")
                    n += 1
                except ProblemError:
                    pass  # decided meanwhile
        return n


def system_repo(job: str = JOB) -> RbacRepo:
    from app.modules.identity.fs_journal import JournalingStore

    return RbacRepo(JournalingStore.system(job))
