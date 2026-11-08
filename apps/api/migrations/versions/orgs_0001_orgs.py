"""orgs: organizations, memberships, batches, batch members, roster imports, invitations

Revision ID: orgs_0001
Revises:
Create Date: 2026-11-03

database-schema §6. RLS: organizations custom on id (members + platform); every other table
family T (organization_id = ANY(app.org_ids()) OR platform). Also creates
``app.user_visible_in_orgs(uuid)`` (SECURITY INVOKER: the caller's own RLS on
org_memberships applies) used by the users/user_profiles policies (identity_0002).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

from app.core.migration_helpers import add_updated_at_trigger, enable_rls

revision: str = "orgs_0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = ("orgs",)
depends_on: str | Sequence[str] | None = ("core_base", "identity_0001")

TABLES = (
    "organizations",
    "org_memberships",
    "batches",
    "batch_members",
    "bulk_import_jobs",
    "org_invitations",
)


def upgrade() -> None:
    op.execute(
        r"""
        CREATE TABLE organizations (
          id                 uuid PRIMARY KEY,
          name               text        NOT NULL CHECK (char_length(name) BETWEEN 2 AND 200),
          slug               citext      NOT NULL UNIQUE CHECK (slug ~ '^[a-z0-9][a-z0-9-]{1,62}$'),
          org_type           text        NOT NULL CHECK (org_type IN ('college','university','company','training_partner','internal')),
          status             text        NOT NULL DEFAULT 'active' CHECK (status IN ('prospect','active','suspended','archived')),
          data_role          text        NOT NULL DEFAULT 'tech_drona_processor'
                             CHECK (data_role IN ('tech_drona_processor','independent_fiduciaries')),
          gstin              text        NULL CHECK (gstin ~ '^[0-9]{2}[A-Z0-9]{13}$'),
          billing_name       text        NULL,
          billing_address    jsonb       NULL,
          state_code         char(2)     NULL,
          contact_name       text        NULL,
          contact_email      citext      NULL,
          contact_phone_e164 text        NULL,
          settings           jsonb       NOT NULL DEFAULT '{}',
          is_synthetic       boolean     NOT NULL DEFAULT false,
          created_at         timestamptz NOT NULL DEFAULT now(),
          updated_at         timestamptz NOT NULL DEFAULT now(),
          deleted_at         timestamptz NULL
        );
        COMMENT ON TABLE organizations IS 'Owner: orgs | RLS: custom (id in org_ids or platform) | Retention: R-ORG | PII: P2/P0';

        CREATE TABLE org_memberships (
          id               uuid PRIMARY KEY,
          organization_id  uuid        NOT NULL REFERENCES organizations(id),
          user_id          uuid        NOT NULL REFERENCES users(id),
          member_type      text        NOT NULL CHECK (member_type IN ('student','staff')),
          external_ref     text        NULL,
          status           text        NOT NULL DEFAULT 'active' CHECK (status IN ('invited','active','graduated','left','removed')),
          joined_at        timestamptz NULL,
          left_at          timestamptz NULL,
          invited_by       uuid        NULL REFERENCES users(id),
          source           text        NOT NULL DEFAULT 'roster_import' CHECK (source IN ('roster_import','invite','self_join_code','staff')),
          created_at       timestamptz NOT NULL DEFAULT now(),
          updated_at       timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT uq_org_memberships_org_user UNIQUE (organization_id, user_id)
        );
        CREATE UNIQUE INDEX ux_om_external_ref ON org_memberships (organization_id, external_ref) WHERE external_ref IS NOT NULL;
        CREATE INDEX ix_om_user ON org_memberships (user_id) WHERE status = 'active';
        COMMENT ON TABLE org_memberships IS 'Owner: orgs | RLS: T | Retention: R-ORG | PII: P2';

        CREATE TABLE batches (
          id                 uuid PRIMARY KEY,
          organization_id    uuid        NOT NULL REFERENCES organizations(id),
          name               text        NOT NULL CHECK (char_length(name) BETWEEN 1 AND 200),
          code               text        NOT NULL CHECK (char_length(code) BETWEEN 1 AND 64),
          academic_year      text        NULL,
          graduation_year    smallint    NULL,
          starts_on          date        NULL,
          ends_on            date        NULL,
          status             text        NOT NULL DEFAULT 'active' CHECK (status IN ('planned','active','completed','archived')),
          created_by         uuid        NOT NULL REFERENCES users(id),
          created_at         timestamptz NOT NULL DEFAULT now(),
          updated_at         timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT uq_batches_org_code UNIQUE (organization_id, code),
          CONSTRAINT ck_batch_dates CHECK (ends_on IS NULL OR starts_on IS NULL OR ends_on >= starts_on)
        );
        CREATE INDEX ix_batches_org ON batches (organization_id);
        COMMENT ON TABLE batches IS 'Owner: orgs | RLS: T | Retention: R-ORG | PII: P0';

        CREATE TABLE batch_members (
          id               uuid PRIMARY KEY,
          batch_id         uuid        NOT NULL REFERENCES batches(id),
          organization_id  uuid        NOT NULL REFERENCES organizations(id),
          user_id          uuid        NOT NULL REFERENCES users(id),
          member_role      text        NOT NULL CHECK (member_role IN ('student','trainer','mentor')),
          status           text        NOT NULL DEFAULT 'active' CHECK (status IN ('active','removed','completed')),
          added_by         uuid        NULL REFERENCES users(id),
          added_at         timestamptz NOT NULL DEFAULT now(),
          removed_at       timestamptz NULL,
          updated_at       timestamptz NOT NULL DEFAULT now()
        );
        CREATE UNIQUE INDEX ux_bm_live ON batch_members (batch_id, user_id, member_role) WHERE status = 'active';
        CREATE INDEX ix_bm_user ON batch_members (user_id) WHERE status = 'active';
        COMMENT ON TABLE batch_members IS 'Owner: orgs | RLS: T | Retention: R-ORG | PII: P1';

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
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {', '.join(TABLES)} TO td_app")
    op.execute(f"GRANT SELECT ON {', '.join(TABLES)} TO td_readonly")
    for t in TABLES:
        add_updated_at_trigger(t)

    op.execute("ALTER TABLE organizations ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE organizations FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY p_org ON organizations FOR ALL TO td_app, td_readonly "
        "USING (id = ANY (app.org_ids()) OR app.is_platform()) WITH CHECK (app.is_platform() OR id = ANY (app.org_ids()))"
    )
    for t in TABLES[1:]:
        enable_rls(t, "T")

    op.execute(
        """
        CREATE OR REPLACE FUNCTION app.user_visible_in_orgs(target uuid) RETURNS boolean
        LANGUAGE sql STABLE SECURITY INVOKER AS
        $$ SELECT EXISTS (SELECT 1 FROM org_memberships m
                          WHERE m.user_id = target AND m.organization_id = ANY (app.org_ids())
                            AND m.status <> 'removed') $$;
        GRANT EXECUTE ON FUNCTION app.user_visible_in_orgs(uuid) TO td_app, td_readonly;
        """
    )


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS app.user_visible_in_orgs(uuid)")
    for t in reversed(TABLES):
        op.execute(f"DROP TABLE IF EXISTS {t} CASCADE")
