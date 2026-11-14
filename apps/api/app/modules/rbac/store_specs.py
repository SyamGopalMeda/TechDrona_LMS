"""Firestore collections of the rbac module (``TD_STORE_RBAC=firestore``).

* ``roles/{id}``, ``permissions/{id}``: the seeded catalogue (rbac_0002+), read whole and cached
* ``role_permissions/{role_id:permission_id}``
* ``role_grants/{id}``: the row plus a denormalised ``role_key`` (replaces the join to ``roles``)
* ``role_grants_live/{user_id:role_id:scope_type:scope_id|-}`` ``{grant_id}``: the partial unique
  index ``ux_rg_live`` (``revoked_at IS NULL``), same transaction as the grant / revoke
* ``approval_requests/{id}``
* ``approvals_case_pending/{target_id}`` ``{approval_id}``: ``ux_apr_case_decision_pending``
  (one pending ``security.case.decision`` per case)
"""

from __future__ import annotations

from typing import Any

from app.core.firestore.backfill import Row, TableMapping, register_mapping
from app.core.firestore.collections import CollectionSpec, register_collection
from app.core.firestore.ids import compose_id
from app.modules.identity.fs_codec import row_doc
from app.modules.rbac.models import ApprovalRequest, Permission, Role, RoleGrant, RolePermission

ROLES = "roles"
PERMISSIONS = "permissions"
ROLE_PERMS = "role_permissions"
GRANTS = "role_grants"
GRANTS_LIVE = "role_grants_live"
APPROVALS = "approval_requests"
CASE_PENDING = "approvals_case_pending"
CASE_ACTION = "security.case.decision"

register_collection(CollectionSpec(ROLES, "shared", write_permission=None))
register_collection(CollectionSpec(PERMISSIONS, "shared", write_permission=None))
register_collection(CollectionSpec(ROLE_PERMS, "shared", write_permission=None))
register_collection(
    CollectionSpec(GRANTS, "owned", read_permission="rbac.grant.read", write_permission="rbac.grant.manage")
)
register_collection(CollectionSpec(GRANTS_LIVE, "system"))
register_collection(
    CollectionSpec(APPROVALS, "shared", read_permission="approval.decide", write_permission="approval.decide")
)
register_collection(CollectionSpec(CASE_PENDING, "system"))


def live_grant_id(user_id: object, role_id: object, scope_type: str, scope_id: object | None) -> str:
    return compose_id(str(user_id), str(role_id), scope_type, str(scope_id) if scope_id else "-")


def grant_doc(r: Row) -> dict[str, Any]:
    return {**row_doc(RoleGrant, r), "role_key": r["role_key"]}


_GRANTS_SQL = "(SELECT g.*, r.role_key FROM role_grants g JOIN roles r ON r.id = g.role_id) AS rg"

register_mapping(TableMapping("rbac", "roles", ROLES, lambda r: str(r["id"]), lambda r: row_doc(Role, r)))
register_mapping(
    TableMapping("rbac", "permissions", PERMISSIONS, lambda r: str(r["id"]), lambda r: row_doc(Permission, r))
)
register_mapping(
    TableMapping(
        "rbac",
        "role_permissions",
        ROLE_PERMS,
        lambda r: compose_id(str(r["role_id"]), str(r["permission_id"])),
        lambda r: row_doc(RolePermission, r),
        order_by="role_id, permission_id",
    )
)
register_mapping(TableMapping("rbac", _GRANTS_SQL, GRANTS, lambda r: str(r["id"]), grant_doc))
register_mapping(
    TableMapping(
        "rbac",
        "role_grants",
        GRANTS_LIVE,
        lambda r: live_grant_id(r["user_id"], r["role_id"], r["scope_type"], r["scope_id"]),
        lambda r: {"grant_id": str(r["id"])},
        where="revoked_at IS NULL",
    )
)
register_mapping(
    TableMapping(
        "rbac", "approval_requests", APPROVALS, lambda r: str(r["id"]), lambda r: row_doc(ApprovalRequest, r)
    )
)
register_mapping(
    TableMapping(
        "rbac",
        "approval_requests",
        CASE_PENDING,
        lambda r: str(r["target_id"]),
        lambda r: {"approval_id": str(r["id"])},
        where=f"action_type = '{CASE_ACTION}' AND status = 'pending' AND target_id IS NOT NULL",
    )
)
