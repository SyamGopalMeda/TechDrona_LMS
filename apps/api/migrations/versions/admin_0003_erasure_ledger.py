"""admin: erasure_ledger (CCP-P1; privacy-and-data-retention §7 backups; audit DB-01)

Revision ID: admin_0003
Revises: admin_0002
Create Date: 2026-11-03

One append-only row per executed erasure run: ``subject_hash`` (SHA-256 of the user id, never
the id itself), the modules whose erasure provider ran (``scope``) and the modules still
pending. A backup restore re-applies every ledger entry before data is used. RLS: platform
only; ``td_app`` may only SELECT and INSERT (no UPDATE/DELETE/TRUNCATE).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "admin_0003"
down_revision: str | Sequence[str] | None = "admin_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE erasure_ledger (
          id                 uuid PRIMARY KEY,
          privacy_request_id uuid        NULL REFERENCES privacy_requests(id),
          subject_hash       bytea       NOT NULL CHECK (octet_length(subject_hash) = 32),
          erased_at          timestamptz NOT NULL DEFAULT now(),
          scope              jsonb       NOT NULL DEFAULT '{}'::jsonb,
          pending_modules    text[]      NOT NULL DEFAULT '{}'
        );
        CREATE INDEX ix_erasure_ledger_subject ON erasure_ledger (subject_hash);
        CREATE INDEX ix_erasure_ledger_request ON erasure_ledger (privacy_request_id);
        COMMENT ON TABLE erasure_ledger IS 'Owner: admin | RLS: platform only | append-only | Retention: R-AUDIT (>= oldest backup) | PII: P0 (hash only)';
        ALTER TABLE erasure_ledger ENABLE ROW LEVEL SECURITY;
        ALTER TABLE erasure_ledger FORCE ROW LEVEL SECURITY;
        CREATE POLICY p_platform ON erasure_ledger FOR ALL TO td_app, td_readonly
          USING (app.is_platform()) WITH CHECK (app.is_platform());
        REVOKE UPDATE, DELETE, TRUNCATE ON erasure_ledger FROM td_app;
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS erasure_ledger CASCADE")
