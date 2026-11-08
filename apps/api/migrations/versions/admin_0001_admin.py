"""admin: policy_settings, feature_flags, privacy_requests, retention_policies

Revision ID: admin_0001
Revises:
Create Date: 2026-11-03

database-schema §13 / §13.1. ``approval_requests`` stays in the rbac branch (rbac_0001); the
admin module owns its API (ADM-12..16). ``privacy_requests.export_job_id`` has no FK until the
analytics ``export_jobs`` table exists.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

from app.core.migration_helpers import add_updated_at_trigger, enable_rls

revision: str = "admin_0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = ("admin",)
depends_on: str | Sequence[str] | None = (
    "core_base",
    "identity_0001",
    "orgs_0001",
    "rbac_0001",
    "security_0001",
)

TABLES = ("policy_settings", "feature_flags", "privacy_requests", "retention_policies")


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE policy_settings (
          id               uuid PRIMARY KEY,
          setting_key      text        NOT NULL,
          scope_type       text        NOT NULL CHECK (scope_type IN ('platform','plan','organization','user')),
          scope_id         uuid        NULL,
          value            jsonb       NOT NULL,
          value_schema     text        NOT NULL,
          min_value        jsonb       NULL,
          max_value        jsonb       NULL,
          org_overridable  boolean     NOT NULL DEFAULT false,
          plan_overridable boolean     NOT NULL DEFAULT false,
          locked           boolean     NOT NULL DEFAULT false,
          version          int         NOT NULL CHECK (version >= 1),
          is_active        boolean     NOT NULL DEFAULT true,
          effective_from   timestamptz NOT NULL DEFAULT now(),
          expires_at       timestamptz NULL,
          case_decision_id uuid        NULL REFERENCES case_decisions(id),
          change_reason    text        NOT NULL,
          changed_by       uuid        NOT NULL REFERENCES users(id),
          approved_by      uuid        NULL REFERENCES users(id),
          approval_request_id uuid     NULL REFERENCES approval_requests(id),
          created_at       timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT ck_ps_scope CHECK ((scope_type = 'platform') = (scope_id IS NULL)),
          CONSTRAINT ck_ps_user_exception CHECK (scope_type <> 'user'
              OR (expires_at IS NOT NULL AND case_decision_id IS NOT NULL AND expires_at <= effective_from + interval '180 days')),
          CONSTRAINT ck_ps_approval CHECK (approved_by IS NULL OR approved_by <> changed_by),
          UNIQUE (setting_key, scope_type, scope_id, version)
        );
        CREATE UNIQUE INDEX ux_ps_active ON policy_settings (setting_key, scope_type,
          coalesce(scope_id, '00000000-0000-0000-0000-000000000000'::uuid)) WHERE is_active;
        CREATE INDEX ix_ps_user_exceptions ON policy_settings (scope_id, expires_at) WHERE scope_type = 'user' AND is_active;
        COMMENT ON TABLE policy_settings IS 'Owner: admin | RLS: NONE (platform config) | versioned | Retention: R-CONTENT | PII: P0/P1';

        CREATE TABLE feature_flags (
          id               uuid PRIMARY KEY,
          flag_key         text        NOT NULL UNIQUE,
          description      text        NOT NULL,
          is_enabled       boolean     NOT NULL DEFAULT false,
          rollout_percent  smallint    NOT NULL DEFAULT 0 CHECK (rollout_percent BETWEEN 0 AND 100),
          org_allowlist    uuid[]      NOT NULL DEFAULT '{}',
          user_allowlist   uuid[]      NOT NULL DEFAULT '{}',
          updated_by       uuid        NULL REFERENCES users(id),
          created_at       timestamptz NOT NULL DEFAULT now(),
          updated_at       timestamptz NOT NULL DEFAULT now()
        );
        COMMENT ON TABLE feature_flags IS 'Owner: admin | RLS: NONE | Retention: R-CONTENT | PII: P0';
        INSERT INTO feature_flags (id, flag_key, description) VALUES
          (gen_random_uuid(), 'platform.maintenance_mode', 'Refuse writes platform-wide (503 maintenance)'),
          (gen_random_uuid(), 'payments.cashfree_enabled', 'Enable the Cashfree payment gateway'),
          (gen_random_uuid(), 'risk.fingerprint_collection', 'Collect the coarse device fingerprint (Phase 2, adults only)');

        CREATE TABLE privacy_requests (
          id                   uuid PRIMARY KEY,
          request_ref          text        NOT NULL UNIQUE CHECK (request_ref ~ '^PRV-[0-9]{4}-[0-9A-HJKMNP-TV-Z]{6}$'),
          user_id              uuid        NULL REFERENCES users(id),
          requested_by         uuid        NULL REFERENCES users(id),
          requester_relationship text      NOT NULL DEFAULT 'self' CHECK (requester_relationship IN ('self','guardian','nominee','college')),
          organization_id      uuid        NULL REFERENCES organizations(id),
          request_type         text        NOT NULL CHECK (request_type IN ('access_export','correction','erasure','grievance',
                                   'nomination','consent_withdrawal_help')),
          status               text        NOT NULL DEFAULT 'received' CHECK (status IN ('received','identity_verification','in_progress',
                                   'awaiting_requester','cooling_off','completed','rejected','withdrawn')),
          details              text        NULL CHECK (details IS NULL OR char_length(details) <= 4000),
          identity_verification_method text NULL CHECK (identity_verification_method IN ('session','otp','guardian_otp','manual')),
          identity_verified_at timestamptz NULL,
          received_at          timestamptz NOT NULL DEFAULT now(),
          due_at               timestamptz NOT NULL,
          cooling_off_until    timestamptz NULL,
          completed_at         timestamptz NULL,
          response_summary     text        NULL,
          export_job_id        uuid        NULL,
          export_payload       jsonb       NULL,
          assigned_to          uuid        NULL REFERENCES users(id),
          legal_hold           boolean     NOT NULL DEFAULT false,
          idempotency_key      text        NULL,
          created_at           timestamptz NOT NULL DEFAULT now(),
          updated_at           timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX ix_prq_queue ON privacy_requests (status, due_at) WHERE status NOT IN ('completed','rejected','withdrawn');
        CREATE INDEX ix_prq_user ON privacy_requests (user_id, received_at DESC);
        COMMENT ON TABLE privacy_requests IS 'Owner: admin (privacy) | RLS: O + platform | Retention: R-PRIV | PII: P2/P3';

        CREATE TABLE retention_policies (
          id                 uuid PRIMARY KEY,
          data_category      text        NOT NULL,
          table_name         text        NOT NULL,
          retention_class    text        NOT NULL,
          retention_interval interval    NULL,
          basis              text        NOT NULL,
          deletion_method    text        NOT NULL CHECK (deletion_method IN ('partition_drop','row_delete','anonymise','pseudonymise','s3_lifecycle')),
          legal_hold_aware   boolean     NOT NULL DEFAULT true,
          job_name           text        NOT NULL,
          owner_module       text        NOT NULL,
          is_active          boolean     NOT NULL DEFAULT true,
          updated_by         uuid        NULL REFERENCES users(id),
          created_at         timestamptz NOT NULL DEFAULT now(),
          updated_at         timestamptz NOT NULL DEFAULT now(),
          UNIQUE (table_name, data_category)
        );
        COMMENT ON TABLE retention_policies IS 'Owner: admin (privacy) | RLS: NONE | Retention: R-CONTENT | PII: P0';
        INSERT INTO retention_policies (id, data_category, table_name, retention_class, retention_interval, basis,
                                        deletion_method, job_name, owner_module) VALUES
          (gen_random_uuid(), 'D7', 'login_attempts', 'R-SEC', interval '395 days', 'CERT-In logs >= 1 year', 'partition_drop', 'purge_auth_logs', 'sessions'),
          (gen_random_uuid(), 'D7', 'session_network_observations', 'R-SEC', interval '395 days', 'CERT-In logs >= 1 year', 'partition_drop', 'purge_auth_logs', 'sessions'),
          (gen_random_uuid(), 'D8', 'security_signals', 'R-RISK', interval '180 days', 'Risk evidence (RE §4.5)', 'partition_drop', 'purge_risk', 'security'),
          (gen_random_uuid(), 'D8', 'risk_evaluations', 'R-RISK', interval '180 days', 'Risk evidence (RE §9)', 'partition_drop', 'purge_risk', 'security'),
          (gen_random_uuid(), 'D9', 'unblock_requests', 'R-RISK', interval '365 days', 'Case closure + 1 year (UNB §9)', 'row_delete', 'purge_cases', 'security');
        """
    )
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON {', '.join(TABLES)} TO td_app")
    op.execute(f"GRANT SELECT ON {', '.join(TABLES)} TO td_readonly")
    op.execute("REVOKE DELETE, TRUNCATE ON policy_settings FROM td_app")
    for t in ("feature_flags", "privacy_requests", "retention_policies"):
        add_updated_at_trigger(t)
    enable_rls("privacy_requests", "O")


def downgrade() -> None:
    for t in reversed(TABLES):
        op.execute(f"DROP TABLE IF EXISTS {t} CASCADE")
