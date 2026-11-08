"""admin: break_glass_sessions (ADM-17..19)

Revision ID: admin_0002
Revises: admin_0001
Create Date: 2026-11-03

A time-boxed elevation (≤ 2 h) with a mandatory reason. The elevation itself is an expiring
``role_grants`` row (``security_reviewer`` at platform scope) referenced by
``role_grant_id``; the expiry job revokes it at ``expires_at``. ``role_grants`` forbids
self-granted platform roles (``ck_rg_self``), so the grant's ``granted_by`` is a synthetic,
deactivated system account created here (it can never sign in); the human actor is recorded
in ``break_glass_sessions.user_id`` and the audit log. Post-hoc review by another
super admin within 2 business days. RLS: platform only.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

from app.core.migration_helpers import add_updated_at_trigger

revision: str = "admin_0002"
down_revision: str | Sequence[str] | None = "admin_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = ("rbac_0001",)


SYSTEM_USER_ID = "00000000-0000-7000-8000-0000000bb6a5"


def upgrade() -> None:
    # users has FORCE RLS with app-role policies only; the owner seeds this one row inside the
    # migration transaction with FORCE briefly lifted (restored before commit).
    op.execute("ALTER TABLE users NO FORCE ROW LEVEL SECURITY")
    op.execute(
        f"""
        INSERT INTO users (id, email, status, is_minor, is_synthetic, account_origin)
        VALUES ('{SYSTEM_USER_ID}', 'break-glass@system.techdrona.invalid', 'deactivated', true, true,
                'staff_created')
        ON CONFLICT (id) DO NOTHING
        """
    )
    op.execute("ALTER TABLE users FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE TABLE break_glass_sessions (
          id             uuid PRIMARY KEY,
          user_id        uuid        NOT NULL REFERENCES users(id),
          reason         text        NOT NULL CHECK (char_length(reason) BETWEEN 20 AND 2000),
          elevated_role  text        NOT NULL DEFAULT 'security_reviewer',
          role_grant_id  uuid        NULL REFERENCES role_grants(id),
          status         text        NOT NULL DEFAULT 'active' CHECK (status IN ('active','ended','expired')),
          started_at     timestamptz NOT NULL DEFAULT now(),
          expires_at     timestamptz NOT NULL,
          ended_at       timestamptz NULL,
          end_reason     text        NULL CHECK (end_reason IN ('ended_early','expired')),
          ended_by       uuid        NULL REFERENCES users(id),
          review_due_at  timestamptz NULL,
          reviewed_by    uuid        NULL REFERENCES users(id),
          reviewed_at    timestamptz NULL,
          review_note    text        NULL,
          created_at     timestamptz NOT NULL DEFAULT now(),
          updated_at     timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT ck_bg_window CHECK (expires_at > started_at AND expires_at <= started_at + interval '2 hours'),
          CONSTRAINT ck_bg_ended CHECK ((status = 'active') = (ended_at IS NULL)),
          CONSTRAINT ck_bg_reviewer CHECK (reviewed_by IS NULL OR reviewed_by <> user_id)
        );
        CREATE UNIQUE INDEX ux_bg_active ON break_glass_sessions (user_id) WHERE status = 'active';
        CREATE INDEX ix_bg_expiry ON break_glass_sessions (expires_at) WHERE status = 'active';
        COMMENT ON TABLE break_glass_sessions IS 'Owner: admin | RLS: platform only | Retention: R-AUDIT | PII: P1';
        ALTER TABLE break_glass_sessions ENABLE ROW LEVEL SECURITY;
        ALTER TABLE break_glass_sessions FORCE ROW LEVEL SECURITY;
        CREATE POLICY p_platform ON break_glass_sessions FOR ALL TO td_app, td_readonly
          USING (app.is_platform()) WITH CHECK (app.is_platform());
        REVOKE DELETE, TRUNCATE ON break_glass_sessions FROM td_app;
        """
    )
    add_updated_at_trigger("break_glass_sessions")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS break_glass_sessions CASCADE")
