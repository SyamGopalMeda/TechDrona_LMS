"""rbac: single-company roles (Admin, Trainer, Evaluator, Content manager, Student)

Revision ID: rbac_0004
Revises: rbac_0003
Create Date: 2026-11-06

docs/single-company/REMOVAL-PLAN.md §4, §5 step 2 and owner decisions §8 D2/D3:

1. ``roles.role_key`` CHECK: adds ``evaluator``. Removed role keys (``college_coordinator``,
   ``finance_admin``, ``support_agent``, ``security_reviewer``, ``placement_mentor``) stay
   allowed **only** so that historic rows still referenced by revoked grants remain valid; the
   catalogue never creates them and they hold no permissions and no allowed scope.
2. Live trainer grants at ``organization`` scope become ``batch`` grants on every
   non-archived batch of that organization (same grantee, granter and expiry).
3. Live grants of removed roles are revoked (reason ``college_removal`` for the coordinator,
   ``role_consolidation`` for the four roles folded into Admin). Nobody is promoted to Admin
   automatically: an Admin grant stays a Dual-control decision.
4. Every other live ``organization``-scope grant is revoked (``college_removal``); a new CHECK
   forbids live organization-scope grants from now on.
5. Users whose grants changed lose their sessions (``privilege_change``), as an API grant
   change would do.
6. ``app.seeds.rbac_seed.sync`` loads the new catalogue (adds ``evaluator``, renames
   ``super_admin`` to "Admin", re-homes the folded permissions to Admin, drops every
   role_permissions row not in the matrix); permissions removed from the catalogue are
   deleted; removed role rows are deleted when no grant references them, otherwise kept as
   historic rows with no permissions.
7. Pending approvals of ``org.suspend`` / ``commerce.contract.terminate`` expire; pending
   approvals whose approver was a removed role now need an Admin (``super_admin``).

Data migrations run as the table owner; FORCE RLS is lifted for the statements and restored
in the same transaction.

Downgrade restores the schema (CHECKs) only, **not** data: revoked grants, deleted
permissions and expired approvals come back only from
``backups/techdrona-dev-before-college-removal-20261106.dump``.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
from sqlalchemy import Connection, text

revision: str = "rbac_0004"
down_revision: str | Sequence[str] | None = "rbac_0003"
branch_labels: str | Sequence[str] | None = None
# Not orgs_0002 on purpose: a cross-branch dependent would make Alembic drop orgs_0002 from
# alembic_version, and the later merge step orgs_0003 would then fail (KeyError in update_to_step).
depends_on: str | Sequence[str] | None = ("orgs_0001", "sessions_0001")

ACTIVE_ROLES = ("student", "evaluator", "trainer", "content_manager", "super_admin")
REMOVED_ROLES = {
    "college_coordinator": "college_removal",
    "finance_admin": "role_consolidation",
    "support_agent": "role_consolidation",
    "security_reviewer": "role_consolidation",
    "placement_mentor": "role_consolidation",
}
OLD_ROLES = (
    "student",
    "college_coordinator",
    "trainer",
    "content_manager",
    "placement_mentor",
    "support_agent",
    "security_reviewer",
    "finance_admin",
    "super_admin",
)
FORCED = ("role_grants", "approval_requests", "auth_sessions", "users", "batches")


def _q(keys: Sequence[str]) -> str:
    return ",".join(f"'{k}'" for k in keys)


def _lift_force(conn: Connection, tables: Sequence[str]) -> list[str]:
    """Lift FORCE RLS (owner-run data migration) on the tables that have it; returns them."""
    forced = list(
        conn.execute(
            text(
                "SELECT relname FROM pg_class WHERE relname = ANY (:t) AND relkind IN ('r','p') "
                "AND relforcerowsecurity AND relnamespace = 'public'::regnamespace"
            ),
            {"t": list(tables)},
        ).scalars()
    )
    for t in forced:
        op.execute(f"ALTER TABLE {t} NO FORCE ROW LEVEL SECURITY")
    return forced


def _restore_force(tables: Sequence[str]) -> None:
    for t in tables:
        op.execute(f"ALTER TABLE {t} FORCE ROW LEVEL SECURITY")


def upgrade() -> None:
    from app.modules.rbac.catalogue import PERMISSIONS
    from app.seeds.rbac_seed import sync

    conn = op.get_bind()
    # 1. role_key CHECK
    op.execute("ALTER TABLE roles DROP CONSTRAINT IF EXISTS roles_role_key_check")
    op.execute(
        "ALTER TABLE roles ADD CONSTRAINT roles_role_key_check "
        f"CHECK (role_key IN ({_q(ACTIVE_ROLES + tuple(REMOVED_ROLES))}))"
    )

    forced = _lift_force(conn, FORCED)
    op.execute("CREATE TEMP TABLE _rbac4_changed (user_id uuid PRIMARY KEY) ON COMMIT DROP")

    # 2. trainer organization grants -> batch grants on that organization's live batches
    op.execute(
        """
        INSERT INTO role_grants (id, user_id, role_id, scope_type, scope_id, organization_id,
                                 granted_by, granted_at, expires_at, reason)
        SELECT gen_random_uuid(), g.user_id, g.role_id, 'batch', b.id, b.organization_id,
               g.granted_by, now(), g.expires_at,
               'single_company: converted from organization scope (grant ' || g.id || ')'
          FROM role_grants g
          JOIN roles r ON r.id = g.role_id AND r.role_key = 'trainer'
          JOIN batches b ON b.organization_id = g.scope_id AND b.status <> 'archived'
         WHERE g.scope_type = 'organization' AND g.revoked_at IS NULL
           AND (g.expires_at IS NULL OR g.expires_at > now())
           AND NOT EXISTS (SELECT 1 FROM role_grants x
                            WHERE x.user_id = g.user_id AND x.role_id = g.role_id
                              AND x.scope_type = 'batch' AND x.scope_id = b.id
                              AND x.revoked_at IS NULL)
        """
    )

    # 3. removed roles
    for role, reason in REMOVED_ROLES.items():
        op.execute(
            f"""
            WITH revoked AS (
              UPDATE role_grants g
                 SET revoked_at = now(),
                     reason = left(coalesce(g.reason || ' | ', '') || 'revoked: {reason}', 500)
                FROM roles r
               WHERE r.id = g.role_id AND r.role_key = '{role}' AND g.revoked_at IS NULL
              RETURNING g.user_id)
            INSERT INTO _rbac4_changed SELECT DISTINCT user_id FROM revoked ON CONFLICT DO NOTHING
            """
        )

    # 4. any other live organization-scope grant
    op.execute(
        """
        WITH revoked AS (
          UPDATE role_grants g
             SET revoked_at = now(),
                 reason = left(coalesce(g.reason || ' | ', '') || 'revoked: college_removal', 500)
           WHERE g.scope_type = 'organization' AND g.revoked_at IS NULL
          RETURNING g.user_id)
        INSERT INTO _rbac4_changed SELECT DISTINCT user_id FROM revoked ON CONFLICT DO NOTHING
        """
    )
    op.execute(
        "ALTER TABLE role_grants ADD CONSTRAINT ck_rg_no_live_org_scope "
        "CHECK (scope_type <> 'organization' OR revoked_at IS NOT NULL)"
    )

    # 5. session rotation for every user whose grants changed
    op.execute(
        """
        UPDATE auth_sessions s
           SET status = 'revoked', end_reason = 'privilege_change', ended_at = now()
         WHERE s.user_id IN (SELECT user_id FROM _rbac4_changed)
           AND s.status NOT IN ('expired','revoked','blocked');
        UPDATE users u SET sessions_valid_after = now()
         WHERE u.id IN (SELECT user_id FROM _rbac4_changed);
        """
    )

    # 6. catalogue
    sync(conn)
    conn.execute(
        text("DELETE FROM permissions WHERE NOT (permission_key = ANY (:keep))"),
        {"keep": sorted(PERMISSIONS)},
    )
    removed = _q(tuple(REMOVED_ROLES))
    op.execute(
        f"DELETE FROM role_permissions rp USING roles r WHERE rp.role_id = r.id AND r.role_key IN ({removed})"
    )
    op.execute(
        f"DELETE FROM roles r WHERE r.role_key IN ({removed}) "
        "AND NOT EXISTS (SELECT 1 FROM role_grants g WHERE g.role_id = r.id)"
    )
    op.execute(
        f"UPDATE roles SET allowed_scope_types = '{{}}', "
        "name = CASE WHEN name LIKE '%(removed)' THEN name ELSE name || ' (removed)' END "
        f"WHERE role_key IN ({removed})"
    )

    # 7. approvals
    op.execute(
        "UPDATE approval_requests SET status = 'expired' "
        "WHERE status = 'pending' AND action_type IN ('org.suspend','commerce.contract.terminate')"
    )
    conds = " OR ".join(f"required_approver_role LIKE '%{r}%'" for r in REMOVED_ROLES)
    op.execute(
        f"UPDATE approval_requests SET required_approver_role = 'super_admin' "
        f"WHERE status = 'pending' AND ({conds})"
    )

    _restore_force(forced)


def downgrade() -> None:
    op.execute("ALTER TABLE role_grants DROP CONSTRAINT IF EXISTS ck_rg_no_live_org_scope")
    op.execute(
        "DELETE FROM role_permissions rp USING roles r WHERE rp.role_id = r.id AND r.role_key = 'evaluator'"
    )
    op.execute(
        "DELETE FROM roles r WHERE r.role_key = 'evaluator' "
        "AND NOT EXISTS (SELECT 1 FROM role_grants g WHERE g.role_id = r.id)"
    )
    op.execute("ALTER TABLE roles DROP CONSTRAINT IF EXISTS roles_role_key_check")
    op.execute(
        "ALTER TABLE roles ADD CONSTRAINT roles_role_key_check "
        f"CHECK (role_key IN ({_q(OLD_ROLES)})) NOT VALID"
    )
