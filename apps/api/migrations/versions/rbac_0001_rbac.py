"""rbac: roles, permissions, role_permissions, role_grants, approval_requests

Revision ID: rbac_0001
Revises:
Create Date: 2026-11-03

database-schema §6 (rbac) and §13 (``approval_requests``: owned by admin in the schema doc;
created here because RBAC-04/05 dual control needs it now — the admin module adopts it).
RLS: roles/permissions/role_permissions/approval_requests NONE (reference data / platform
queue; td_app cannot write the reference tables), role_grants custom.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

from app.core.migration_helpers import add_updated_at_trigger

revision: str = "rbac_0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = ("rbac",)
depends_on: str | Sequence[str] | None = ("core_base", "identity_0001", "orgs_0001")

TABLES = ("roles", "permissions", "role_permissions", "role_grants", "approval_requests")


def upgrade() -> None:
    op.execute(
        r"""
        CREATE TABLE roles (
          id            uuid PRIMARY KEY,
          role_key      text        NOT NULL UNIQUE CHECK (role_key IN ('student','college_coordinator','trainer','content_manager',
                           'placement_mentor','support_agent','security_reviewer','finance_admin','super_admin')),
          name          text        NOT NULL,
          session_tier  text        NOT NULL CHECK (session_tier IN ('student','staff','privileged')),
          mfa_required  boolean     NOT NULL,
          allowed_scope_types text[] NOT NULL,
          is_system     boolean     NOT NULL DEFAULT true,
          created_at    timestamptz NOT NULL DEFAULT now(),
          updated_at    timestamptz NOT NULL DEFAULT now()
        );
        COMMENT ON TABLE roles IS 'Owner: rbac | RLS: NONE | Retention: R-CONTENT | PII: P0';

        CREATE TABLE permissions (
          id              uuid PRIMARY KEY,
          permission_key  text        NOT NULL UNIQUE CHECK (permission_key ~ '^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*){1,2}$'),
          module          text        NOT NULL,
          description     text        NOT NULL,
          is_sensitive    boolean     NOT NULL DEFAULT false,
          created_at      timestamptz NOT NULL DEFAULT now()
        );
        COMMENT ON TABLE permissions IS 'Owner: rbac | RLS: NONE | Retention: R-CONTENT | PII: P0';

        CREATE TABLE role_permissions (
          role_id        uuid NOT NULL REFERENCES roles(id) ON DELETE CASCADE,
          permission_id  uuid NOT NULL REFERENCES permissions(id) ON DELETE CASCADE,
          created_at     timestamptz NOT NULL DEFAULT now(),
          PRIMARY KEY (role_id, permission_id)
        );
        COMMENT ON TABLE role_permissions IS 'Owner: rbac | RLS: NONE | Retention: R-CONTENT | PII: P0';

        CREATE TABLE role_grants (
          id               uuid PRIMARY KEY,
          user_id          uuid        NOT NULL REFERENCES users(id),
          role_id          uuid        NOT NULL REFERENCES roles(id),
          scope_type       text        NOT NULL CHECK (scope_type IN ('platform','organization','batch','course')),
          scope_id         uuid        NULL,
          organization_id  uuid        NULL REFERENCES organizations(id),
          granted_by       uuid        NOT NULL REFERENCES users(id),
          granted_at       timestamptz NOT NULL DEFAULT now(),
          expires_at       timestamptz NULL,
          revoked_at       timestamptz NULL,
          revoked_by       uuid        NULL REFERENCES users(id),
          reason           text        NULL,
          CONSTRAINT ck_rg_scope CHECK ((scope_type = 'platform') = (scope_id IS NULL)),
          CONSTRAINT ck_rg_self CHECK (granted_by <> user_id OR scope_type <> 'platform')
        );
        CREATE UNIQUE INDEX ux_rg_live ON role_grants (user_id, role_id, scope_type,
          coalesce(scope_id, '00000000-0000-0000-0000-000000000000'::uuid)) WHERE revoked_at IS NULL;
        CREATE INDEX ix_rg_user ON role_grants (user_id) WHERE revoked_at IS NULL;
        CREATE INDEX ix_rg_scope ON role_grants (scope_type, scope_id) WHERE revoked_at IS NULL;
        COMMENT ON TABLE role_grants IS 'Owner: rbac | RLS: custom (own, org, platform) | Retention: R-AUDIT | PII: P1';

        CREATE TABLE approval_requests (
          id                 uuid PRIMARY KEY,
          action_type        text        NOT NULL,
          organization_id    uuid        NULL REFERENCES organizations(id),
          target_type        text        NOT NULL,
          target_id          uuid        NULL,
          payload            jsonb       NOT NULL,
          payload_hash       bytea       NOT NULL CHECK (octet_length(payload_hash) = 32),
          requested_by       uuid        NOT NULL REFERENCES users(id),
          request_reason     text        NOT NULL,
          required_approver_role text    NOT NULL,
          status             text        NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','approved','rejected','expired','cancelled','executed')),
          decided_by         uuid        NULL REFERENCES users(id),
          decided_at         timestamptz NULL,
          decision_note      text        NULL,
          expires_at         timestamptz NOT NULL,
          executed_at        timestamptz NULL,
          created_at         timestamptz NOT NULL DEFAULT now(),
          updated_at         timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT ck_apr_distinct CHECK (decided_by IS NULL OR decided_by <> requested_by),
          CONSTRAINT ck_apr_decided CHECK ((status IN ('approved','rejected','executed')) = (decided_by IS NOT NULL))
        );
        CREATE INDEX ix_apr_pending ON approval_requests (action_type, expires_at) WHERE status = 'pending';
        CREATE UNIQUE INDEX ux_apr_case_decision_pending ON approval_requests (target_id)
          WHERE action_type = 'security.case.decision' AND status = 'pending';
        COMMENT ON TABLE approval_requests IS 'Owner: admin (created by rbac) | RLS: NONE | Retention: R-AUDIT | PII: P1';
        """
    )
    op.execute("GRANT SELECT ON roles, permissions, role_permissions TO td_app, td_readonly")
    op.execute("REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON roles, permissions, role_permissions FROM td_app")
    op.execute("GRANT SELECT, INSERT, UPDATE ON role_grants, approval_requests TO td_app")
    op.execute("REVOKE DELETE, TRUNCATE ON role_grants, approval_requests FROM td_app")
    op.execute("GRANT SELECT ON role_grants, approval_requests TO td_readonly")
    add_updated_at_trigger("roles")
    add_updated_at_trigger("approval_requests")
    op.execute("ALTER TABLE role_grants ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE role_grants FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY p_rg ON role_grants FOR ALL TO td_app, td_readonly "
        "USING (user_id = app.user_id() OR organization_id = ANY (app.org_ids()) OR app.is_platform()) "
        "WITH CHECK (organization_id = ANY (app.org_ids()) OR app.is_platform())"
    )


def downgrade() -> None:
    for t in reversed(TABLES):
        op.execute(f"DROP TABLE IF EXISTS {t} CASCADE")
