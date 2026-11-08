"""orgs: the single company organization; drop invitations and roster imports

Revision ID: orgs_0002
Revises: orgs_0001
Create Date: 2026-11-06

Single-company LMS (docs/single-company/REMOVAL-PLAN.md §2.2, §5 step 1):

* inserts the company organization ``COMPANY_ORG_ID`` (``app.core.company``): name
  "Tech Drona", slug ``techdrona``, ``org_type='internal'``. Idempotent; an older row that
  already uses the slug ``techdrona`` is renamed ``techdrona-legacy-<id prefix>`` first;
* drops ``org_invitations`` and ``bulk_import_jobs`` (college invitations / roster import).

The college columns of ``organizations``, the CHECK on ``org_type`` and the singleton index
come later, in ``orgs_0003_rehome_and_lock`` (after every module has re-homed its rows).

Data migrations run as the table owner; FORCE RLS applies to the owner and the policies only
name td_app/td_readonly, so the owner lifts FORCE for the duration of the statement and puts
it back in the same transaction.

Downgrade restores the dropped tables (schema, grants, RLS) but **not** their rows: restore
the data from ``backups/techdrona-dev-before-college-removal-20261106.dump``. The company row
is left in place (other tables may reference it).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

from app.core.company import COMPANY_ORG_ID, COMPANY_ORG_NAME, COMPANY_ORG_SLUG, COMPANY_ORG_TYPE
from app.core.migration_helpers import add_updated_at_trigger, enable_rls

revision: str = "orgs_0002"
down_revision: str | Sequence[str] | None = "orgs_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE organizations NO FORCE ROW LEVEL SECURITY")
    op.execute(
        f"""
        UPDATE organizations
           SET slug = left(slug::text, 40) || '-legacy-' || substr(id::text, 1, 8)
         WHERE slug = '{COMPANY_ORG_SLUG}' AND id <> '{COMPANY_ORG_ID}'::uuid;
        INSERT INTO organizations (id, name, slug, org_type, status, settings, is_synthetic)
        VALUES ('{COMPANY_ORG_ID}'::uuid, '{COMPANY_ORG_NAME}', '{COMPANY_ORG_SLUG}',
                '{COMPANY_ORG_TYPE}', 'active', '{{}}'::jsonb, false)
        ON CONFLICT (id) DO UPDATE
           SET name = EXCLUDED.name, slug = EXCLUDED.slug, org_type = EXCLUDED.org_type,
               status = 'active', deleted_at = NULL;
        """
    )
    op.execute("ALTER TABLE organizations FORCE ROW LEVEL SECURITY")
    op.execute("DROP TABLE IF EXISTS org_invitations")
    op.execute("DROP TABLE IF EXISTS bulk_import_jobs")


def downgrade() -> None:
    op.execute(
        r"""
        CREATE TABLE bulk_import_jobs (
          id                uuid PRIMARY KEY,
          organization_id   uuid        NOT NULL REFERENCES organizations(id),
          batch_id          uuid        NULL REFERENCES batches(id),
          uploaded_by       uuid        NOT NULL REFERENCES users(id),
          file_s3_key       text        NOT NULL,
          file_sha256       bytea       NOT NULL CHECK (octet_length(file_sha256) = 32),
          status            text        NOT NULL DEFAULT 'validating' CHECK (status IN ('validating','preview_ready','committing',
                                            'committed','failed','cancelled')),
          total_rows        int         NULL CHECK (total_rows BETWEEN 0 AND 5000),
          valid_rows        int         NULL,
          error_rows        int         NULL,
          row_results       jsonb       NOT NULL DEFAULT '[]',
          committed_at      timestamptz NULL,
          created_at        timestamptz NOT NULL DEFAULT now(),
          updated_at        timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT uq_bulk_import_jobs_org_sha UNIQUE (organization_id, file_sha256)
        );
        COMMENT ON TABLE bulk_import_jobs IS 'Owner: orgs | RLS: T | Retention: R-ORG | PII: P2';

        CREATE TABLE org_invitations (
          id                 uuid PRIMARY KEY,
          organization_id    uuid        NOT NULL REFERENCES organizations(id),
          batch_id           uuid        NULL REFERENCES batches(id),
          bulk_import_job_id uuid        NULL REFERENCES bulk_import_jobs(id),
          email              citext      NULL,
          phone_e164         text        NULL CHECK (phone_e164 IS NULL OR phone_e164 ~ '^\+[1-9][0-9]{7,14}$'),
          full_name          text        NULL,
          external_ref       text        NULL,
          member_type        text        NOT NULL DEFAULT 'student' CHECK (member_type IN ('student','staff')),
          token_hash         bytea       NOT NULL CHECK (octet_length(token_hash) = 32),
          status             text        NOT NULL DEFAULT 'sent' CHECK (status IN ('pending','sent','opened','accepted','expired','bounced','revoked')),
          resend_count       smallint    NOT NULL DEFAULT 0 CHECK (resend_count BETWEEN 0 AND 3),
          expires_at         timestamptz NOT NULL,
          accepted_at        timestamptz NULL,
          accepted_user_id   uuid        NULL REFERENCES users(id),
          invited_by         uuid        NOT NULL REFERENCES users(id),
          created_at         timestamptz NOT NULL DEFAULT now(),
          updated_at         timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT ck_oi_contact CHECK (email IS NOT NULL OR phone_e164 IS NOT NULL)
        );
        CREATE UNIQUE INDEX ux_oi_token ON org_invitations (token_hash);
        CREATE INDEX ix_oi_org_status ON org_invitations (organization_id, status);
        COMMENT ON TABLE org_invitations IS 'Owner: orgs | RLS: T | Retention: R-ORG | PII: P2';
        """
    )
    for t in ("bulk_import_jobs", "org_invitations"):
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {t} TO td_app")
        op.execute(f"GRANT SELECT ON {t} TO td_readonly")
        add_updated_at_trigger(t)
        enable_rls(t, "T")
