"""analytics: export_jobs (ANL-13..15 audited, expiring report exports)

Revision ID: analytics_0002
Revises: analytics_0001
Create Date: 2026-11-03

database-schema §12 ``export_jobs`` with its custom RLS (requester, own org, or platform).
Deviations (owner = analytics, documented in app/modules/analytics/README.md):

* ``download_count`` (ANL-15: at most 5 downloads per job), ``watermark`` (the text stamped
  into the file), ``failure_code`` (``failed`` jobs), ``format``, ``reason``, ``completed_at``.
* Status adds nothing; approval ``cancelled``/``expired`` maps to ``rejected``.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

from app.core.migration_helpers import add_updated_at_trigger

revision: str = "analytics_0002"
down_revision: str | Sequence[str] | None = "analytics_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = ("rbac_0001",)


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE export_jobs (
          id                   uuid PRIMARY KEY,
          requested_by         uuid        NOT NULL REFERENCES users(id),
          organization_id      uuid        NULL REFERENCES organizations(id),
          report_key           text        NOT NULL,
          scope_type           text        NOT NULL CHECK (scope_type IN ('platform','organization','batch','course','self')),
          scope_id             uuid        NULL,
          filters              jsonb       NOT NULL DEFAULT '{}',
          format               text        NOT NULL DEFAULT 'csv' CHECK (format IN ('csv')),
          contains_pii         boolean     NOT NULL,
          row_count            int         NULL,
          status               text        NOT NULL DEFAULT 'requested' CHECK (status IN ('requested','awaiting_approval',
                                   'running','ready','expired','failed','rejected')),
          approval_request_id  uuid        NULL REFERENCES approval_requests(id),
          reason_code          text        NULL,
          reason               text        NULL,
          file_s3_key          text        NULL,
          file_sha256          bytea       NULL CHECK (file_sha256 IS NULL OR octet_length(file_sha256) = 32),
          watermark            text        NULL,
          failure_code         text        NULL,
          expires_at           timestamptz NULL,
          downloaded_at        timestamptz NULL,
          download_count       int         NOT NULL DEFAULT 0 CHECK (download_count BETWEEN 0 AND 5),
          completed_at         timestamptz NULL,
          created_at           timestamptz NOT NULL DEFAULT now(),
          updated_at           timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT ck_ej_ready CHECK (status <> 'ready' OR (file_s3_key IS NOT NULL AND expires_at IS NOT NULL))
        )
        """
    )
    op.execute("CREATE INDEX ix_ej_requester ON export_jobs (requested_by, created_at DESC)")
    op.execute(
        "CREATE INDEX ix_ej_status ON export_jobs (status, updated_at) WHERE status IN ('running','ready')"
    )
    op.execute("ALTER TABLE export_jobs ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE export_jobs FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY p_ej ON export_jobs FOR ALL TO td_app, td_readonly "
        "USING (requested_by = app.user_id() "
        "       OR (organization_id IS NOT NULL AND organization_id = ANY (app.org_ids())) "
        "       OR app.is_platform()) "
        "WITH CHECK (requested_by = app.user_id() "
        "       OR (organization_id IS NOT NULL AND organization_id = ANY (app.org_ids())) "
        "       OR app.is_platform())"
    )
    add_updated_at_trigger("export_jobs")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS export_jobs")
