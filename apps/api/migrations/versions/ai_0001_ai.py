"""ai: org AI settings, per-org app enablement, ai_usage ledger (WISEMAN-FEATURES build)

Revision ID: ai_0001
Revises:
Create Date: 2026-11-06

* ``ai_org_settings`` — one row per organization (absent row = defaults: AI enabled, platform
  default model, no caps). RLS: org members read their org's row; platform writes.
* ``org_app_settings`` — per-org app enablement. Absent row = enabled, so existing
  organizations keep working. RLS as above.
* ``ai_usage`` — append-only metering ledger (tokens, cost estimate; never prompt/response
  text). RLS: own rows or platform. ``td_app`` may INSERT/SELECT and only UPDATE ``user_id``
  (privacy erasure pseudonymises it); no DELETE/TRUNCATE.

Provider API keys are never stored in the database.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

from app.core.migration_helpers import add_updated_at_trigger

revision: str = "ai_0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = ("ai",)
depends_on: str | Sequence[str] | None = ("core_base", "orgs_0001", "identity_0001")

APP_KEYS = (
    "assignments",
    "assessments",
    "question_banks",
    "engage",
    "paths",
    "ai_tutor",
    "ai_grading",
    "ai_generation",
)


def upgrade() -> None:
    keys = ",".join(f"'{k}'" for k in APP_KEYS)
    op.execute(
        """
        CREATE TABLE ai_org_settings (
          organization_id          uuid        PRIMARY KEY REFERENCES organizations(id),
          enabled                  boolean     NOT NULL DEFAULT true,
          model                    text        NULL CHECK (model IS NULL OR length(model) BETWEEN 1 AND 100),
          monthly_token_cap        bigint      NULL CHECK (monthly_token_cap IS NULL OR monthly_token_cap >= 0),
          monthly_call_cap         int         NULL CHECK (monthly_call_cap IS NULL OR monthly_call_cap >= 0),
          per_activity_default_cap int         NULL CHECK (per_activity_default_cap IS NULL OR per_activity_default_cap >= 0),
          updated_by               uuid        NULL REFERENCES users(id),
          created_at               timestamptz NOT NULL DEFAULT now(),
          updated_at               timestamptz NOT NULL DEFAULT now()
        );
        COMMENT ON TABLE ai_org_settings IS 'Owner: ai | RLS: org members read, platform write | no secrets';
        ALTER TABLE ai_org_settings ENABLE ROW LEVEL SECURITY;
        ALTER TABLE ai_org_settings FORCE ROW LEVEL SECURITY;
        CREATE POLICY p_ai_settings_read ON ai_org_settings FOR SELECT TO td_app, td_readonly
          USING (organization_id = ANY (app.org_ids()) OR app.is_platform());
        CREATE POLICY p_ai_settings_write ON ai_org_settings FOR ALL TO td_app
          USING (app.is_platform()) WITH CHECK (app.is_platform());
        REVOKE DELETE, TRUNCATE ON ai_org_settings FROM td_app;
        """
    )
    add_updated_at_trigger("ai_org_settings")
    op.execute(
        f"""
        CREATE TABLE org_app_settings (
          organization_id uuid        NOT NULL REFERENCES organizations(id),
          app_key         text        NOT NULL CHECK (app_key IN ({keys})),
          enabled         boolean     NOT NULL,
          updated_by      uuid        NULL REFERENCES users(id),
          updated_at      timestamptz NOT NULL DEFAULT now(),
          PRIMARY KEY (organization_id, app_key)
        );
        COMMENT ON TABLE org_app_settings IS 'Owner: ai | RLS: org members read, platform write | absent row = enabled';
        ALTER TABLE org_app_settings ENABLE ROW LEVEL SECURITY;
        ALTER TABLE org_app_settings FORCE ROW LEVEL SECURITY;
        CREATE POLICY p_app_settings_read ON org_app_settings FOR SELECT TO td_app, td_readonly
          USING (organization_id = ANY (app.org_ids()) OR app.is_platform());
        CREATE POLICY p_app_settings_write ON org_app_settings FOR ALL TO td_app
          USING (app.is_platform()) WITH CHECK (app.is_platform());
        REVOKE DELETE, TRUNCATE ON org_app_settings FROM td_app;
        """
    )
    add_updated_at_trigger("org_app_settings")
    op.execute(
        """
        CREATE TABLE ai_usage (
          id              uuid          PRIMARY KEY,
          organization_id uuid          NULL REFERENCES organizations(id),
          user_id         uuid          NULL REFERENCES users(id),
          feature         text          NOT NULL CHECK (feature IN ('question_generation','grading','tutor','path_generation')),
          context_type    text          NULL,
          context_id      uuid          NULL,
          provider        text          NOT NULL,
          model           text          NOT NULL,
          tokens_in       int           NOT NULL DEFAULT 0 CHECK (tokens_in >= 0),
          tokens_out      int           NOT NULL DEFAULT 0 CHECK (tokens_out >= 0),
          cost_estimate   numeric(12,6) NOT NULL DEFAULT 0 CHECK (cost_estimate >= 0),
          outcome         text          NOT NULL DEFAULT 'ok' CHECK (outcome IN ('ok','invalid_output','provider_error')),
          created_at      timestamptz   NOT NULL DEFAULT now()
        );
        CREATE INDEX ix_ai_usage_org_time ON ai_usage (organization_id, created_at);
        CREATE INDEX ix_ai_usage_ctx ON ai_usage (user_id, context_type, context_id) WHERE feature = 'tutor';
        COMMENT ON TABLE ai_usage IS 'Owner: ai | RLS: own rows or platform | append-only metering, no prompt text | PII: P1 (user_id)';
        ALTER TABLE ai_usage ENABLE ROW LEVEL SECURITY;
        ALTER TABLE ai_usage FORCE ROW LEVEL SECURITY;
        CREATE POLICY p_ai_usage ON ai_usage FOR ALL TO td_app, td_readonly
          USING (user_id = app.user_id() OR app.is_platform())
          WITH CHECK (user_id = app.user_id() OR app.is_platform());
        REVOKE UPDATE, DELETE, TRUNCATE ON ai_usage FROM td_app;
        GRANT UPDATE (user_id) ON ai_usage TO td_app;
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS ai_usage")
    op.execute("DROP TABLE IF EXISTS org_app_settings")
    op.execute("DROP TABLE IF EXISTS ai_org_settings")
