"""admin: per-org policy layer removed (single company)

Revision ID: admin_0004
Revises: admin_0003
Create Date: 2026-11-07

Single-company conversion (docs/single-company/REMOVAL-PLAN.md §2.3, §5 step 6, WS3).

* ``policy_settings``: organization-scoped rows (and every row of the removed key
  ``org.notify_coordinator_on_restriction``) are deleted, ``org_overridable`` is dropped and the
  scope CHECK becomes ``platform | plan | user``. Precedence is user > plan > platform.
* ``feature_flags.org_allowlist`` is dropped (the user allowlist and the rollout stay).
* ``privacy_requests.requester_relationship = 'college'`` is remapped to ``'self'`` (the request
  is about the learner's own data) and the CHECK no longer allows ``college``.
* ``break_glass_sessions.elevated_role`` defaults to ``super_admin``: the ``security_reviewer``
  role is gone (owner decision D2) and break-glass activation is retired.

Data steps run as the table owner; FORCE RLS is lifted only on tables that have it and restored
in the same transaction. Downgrade restores the schema only (columns come back with their
defaults); restore data from the pre-migration dump.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
from sqlalchemy import text
from sqlalchemy.engine import Connection

revision: str = "admin_0004"
down_revision: str | Sequence[str] | None = "admin_0003"
branch_labels: str | Sequence[str] | None = None
# Never orgs_0002 here (Alembic 1.20 merge pitfall, docs/single-company/ws1.md §2).
depends_on: str | Sequence[str] | None = ("orgs_0001",)

DATA_TABLES = ("policy_settings", "privacy_requests")


def _lift_force(conn: Connection, tables: Sequence[str]) -> list[str]:
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


def _drop_scope_check(conn: Connection) -> None:
    """Drop the inline (auto-named) CHECK on policy_settings.scope_type, whatever its name."""
    names = conn.execute(
        text(
            "SELECT conname FROM pg_constraint WHERE conrelid = 'public.policy_settings'::regclass "
            "AND contype = 'c' AND pg_get_constraintdef(oid) LIKE '%scope_type%' "
            "AND pg_get_constraintdef(oid) LIKE '%organization%'"
        )
    ).scalars()
    for n in list(names):
        op.execute(f'ALTER TABLE policy_settings DROP CONSTRAINT "{n}"')


def upgrade() -> None:
    conn = op.get_bind()
    forced = _lift_force(conn, DATA_TABLES)
    op.execute(
        """
        DELETE FROM policy_settings
         WHERE scope_type = 'organization' OR setting_key = 'org.notify_coordinator_on_restriction';
        UPDATE privacy_requests SET requester_relationship = 'self' WHERE requester_relationship = 'college';
        """
    )
    _restore_force(forced)
    _drop_scope_check(conn)
    op.execute(
        """
        ALTER TABLE policy_settings DROP CONSTRAINT IF EXISTS ck_ps_scope_type;
        ALTER TABLE policy_settings ADD CONSTRAINT ck_ps_scope_type
          CHECK (scope_type IN ('platform','plan','user'));
        ALTER TABLE policy_settings DROP COLUMN IF EXISTS org_overridable;
        ALTER TABLE feature_flags DROP COLUMN IF EXISTS org_allowlist;
        ALTER TABLE privacy_requests DROP CONSTRAINT IF EXISTS privacy_requests_requester_relationship_check;
        ALTER TABLE privacy_requests DROP CONSTRAINT IF EXISTS ck_prq_relationship;
        ALTER TABLE privacy_requests ADD CONSTRAINT ck_prq_relationship
          CHECK (requester_relationship IN ('self','guardian','nominee'));
        ALTER TABLE break_glass_sessions ALTER COLUMN elevated_role SET DEFAULT 'super_admin';
        """
    )


def downgrade() -> None:
    """Schema only; restore data from the dump taken before the single-company migration."""
    op.execute(
        """
        ALTER TABLE break_glass_sessions ALTER COLUMN elevated_role SET DEFAULT 'security_reviewer';
        ALTER TABLE privacy_requests DROP CONSTRAINT IF EXISTS ck_prq_relationship;
        ALTER TABLE privacy_requests ADD CONSTRAINT privacy_requests_requester_relationship_check
          CHECK (requester_relationship IN ('self','guardian','nominee','college'));
        ALTER TABLE feature_flags ADD COLUMN IF NOT EXISTS org_allowlist uuid[] NOT NULL DEFAULT '{}';
        ALTER TABLE policy_settings ADD COLUMN IF NOT EXISTS org_overridable boolean NOT NULL DEFAULT false;
        ALTER TABLE policy_settings DROP CONSTRAINT IF EXISTS ck_ps_scope_type;
        ALTER TABLE policy_settings ADD CONSTRAINT policy_settings_scope_type_check
          CHECK (scope_type IN ('platform','plan','organization','user'));
        """
    )
