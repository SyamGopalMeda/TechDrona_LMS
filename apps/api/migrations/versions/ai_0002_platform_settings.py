"""ai: per-org AI settings become platform settings; usage reservations; server-side tutor history

Revision ID: ai_0002
Revises: ai_0001
Create Date: 2026-11-07

Single-company conversion (docs/single-company/REMOVAL-PLAN.md §2.3, §5 step 6, WS3).

* ``ai_settings`` — singleton (``id = 1``). Every cap is NOT NULL with a safe default (SEC-05):
  monthly calls/tokens, the per-activity tutor cap (owner decision D10: 20 per learner per
  activity) and the per-user tutor/generate rate limits. Seeded from the company org's
  ``ai_org_settings`` row when one exists (NULL caps fall back to the defaults).
* ``app_settings`` — platform app toggles (absent row = enabled). Seeded from the company
  org's ``org_app_settings`` rows.
* ``ai_org_settings`` and ``org_app_settings`` are dropped.
* ``ai_usage`` gains the ``reserved`` outcome (SEC-14/15: reserve in a short transaction, call
  the provider with no AI lock held, then finalise the row). ``td_app`` may update only the
  finalisation columns, and a trigger allows that only while the row is still ``reserved``.
* ``ai_tutor_turns`` — server-side tutor history (SEC-17), own rows or platform, FORCE RLS.

Downgrade restores the schema only (the per-org tables come back empty, reserved rows are
marked ``provider_error``); restore data from the pre-migration dump.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

from app.core.migration_helpers import add_updated_at_trigger

revision: str = "ai_0002"
down_revision: str | Sequence[str] | None = "ai_0001"
branch_labels: str | Sequence[str] | None = None
# Never orgs_0002 here (Alembic 1.20 merge pitfall, docs/single-company/ws1.md §2).
depends_on: str | Sequence[str] | None = ("orgs_0001",)

COMPANY_ORG_ID = "01930000-0000-7000-8000-00000000c001"
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
DEFAULTS = {
    "monthly_token_cap": 50_000_000,
    "monthly_call_cap": 50_000,
    "per_activity_default_cap": 20,
    "tutor_per_minute": 10,
    "tutor_per_day": 200,
    "generate_per_hour": 30,
    "generate_per_day": 100,
}


def upgrade() -> None:
    keys = ",".join(f"'{k}'" for k in APP_KEYS)
    d = DEFAULTS
    op.execute(
        f"""
        CREATE TABLE ai_settings (
          id                       smallint    PRIMARY KEY DEFAULT 1 CHECK (id = 1),
          enabled                  boolean     NOT NULL DEFAULT true,
          model                    text        NULL CHECK (model IS NULL OR length(model) BETWEEN 1 AND 100),
          monthly_token_cap        bigint      NOT NULL DEFAULT {d["monthly_token_cap"]} CHECK (monthly_token_cap >= 0),
          monthly_call_cap         int         NOT NULL DEFAULT {d["monthly_call_cap"]} CHECK (monthly_call_cap >= 0),
          per_activity_default_cap int         NOT NULL DEFAULT {d["per_activity_default_cap"]}
                                               CHECK (per_activity_default_cap >= 0),
          tutor_per_minute         int         NOT NULL DEFAULT {d["tutor_per_minute"]} CHECK (tutor_per_minute BETWEEN 1 AND 1000),
          tutor_per_day            int         NOT NULL DEFAULT {d["tutor_per_day"]} CHECK (tutor_per_day BETWEEN 1 AND 100000),
          generate_per_hour        int         NOT NULL DEFAULT {d["generate_per_hour"]} CHECK (generate_per_hour BETWEEN 1 AND 10000),
          generate_per_day         int         NOT NULL DEFAULT {d["generate_per_day"]} CHECK (generate_per_day BETWEEN 1 AND 100000),
          updated_by               uuid        NULL REFERENCES users(id),
          created_at               timestamptz NOT NULL DEFAULT now(),
          updated_at               timestamptz NOT NULL DEFAULT now()
        );
        COMMENT ON TABLE ai_settings IS 'Owner: ai | RLS: platform only (services read via system context) | singleton | no secrets';
        CREATE POLICY p_ai_settings ON ai_settings FOR ALL TO td_app, td_readonly
          USING (app.is_platform()) WITH CHECK (app.is_platform());
        GRANT SELECT, INSERT, UPDATE ON ai_settings TO td_app;
        GRANT SELECT ON ai_settings TO td_readonly;
        REVOKE DELETE, TRUNCATE ON ai_settings FROM td_app;

        INSERT INTO ai_settings (id, enabled, model, monthly_token_cap, monthly_call_cap,
                                 per_activity_default_cap, updated_by)
        SELECT 1, s.enabled, s.model,
               coalesce(s.monthly_token_cap, {d["monthly_token_cap"]}),
               coalesce(s.monthly_call_cap, {d["monthly_call_cap"]}),
               coalesce(s.per_activity_default_cap, {d["per_activity_default_cap"]}),
               s.updated_by
          FROM ai_org_settings s
         WHERE s.organization_id = '{COMPANY_ORG_ID}'
        ON CONFLICT (id) DO NOTHING;
        INSERT INTO ai_settings (id) VALUES (1) ON CONFLICT (id) DO NOTHING;

        CREATE TABLE app_settings (
          app_key    text        PRIMARY KEY CHECK (app_key IN ({keys})),
          enabled    boolean     NOT NULL,
          updated_by uuid        NULL REFERENCES users(id),
          updated_at timestamptz NOT NULL DEFAULT now()
        );
        COMMENT ON TABLE app_settings IS 'Owner: ai | RLS: platform only (services read via system context) | absent row = enabled';
        CREATE POLICY p_app_settings ON app_settings FOR ALL TO td_app, td_readonly
          USING (app.is_platform()) WITH CHECK (app.is_platform());
        GRANT SELECT, INSERT, UPDATE ON app_settings TO td_app;
        GRANT SELECT ON app_settings TO td_readonly;
        REVOKE DELETE, TRUNCATE ON app_settings FROM td_app;

        INSERT INTO app_settings (app_key, enabled, updated_by)
        SELECT app_key, enabled, updated_by FROM org_app_settings
         WHERE organization_id = '{COMPANY_ORG_ID}'
        ON CONFLICT (app_key) DO NOTHING;

        DROP TABLE ai_org_settings;
        DROP TABLE org_app_settings;

        -- RLS is forced only after the owner has seeded the rows above.
        ALTER TABLE ai_settings ENABLE ROW LEVEL SECURITY;
        ALTER TABLE ai_settings FORCE ROW LEVEL SECURITY;
        ALTER TABLE app_settings ENABLE ROW LEVEL SECURITY;
        ALTER TABLE app_settings FORCE ROW LEVEL SECURITY;
        """
    )
    add_updated_at_trigger("ai_settings")
    add_updated_at_trigger("app_settings")

    # ai_usage: reservations (SEC-14 / SEC-15)
    op.execute(
        """
        ALTER TABLE ai_usage DROP CONSTRAINT IF EXISTS ai_usage_outcome_check;
        ALTER TABLE ai_usage ADD CONSTRAINT ai_usage_outcome_check
          CHECK (outcome IN ('ok','invalid_output','provider_error','reserved'));
        CREATE INDEX IF NOT EXISTS ix_ai_usage_time ON ai_usage (created_at);
        GRANT UPDATE (outcome, model, tokens_in, tokens_out, cost_estimate) ON ai_usage TO td_app;

        CREATE OR REPLACE FUNCTION ai_usage_finalize_guard() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
          IF (NEW.outcome, NEW.model, NEW.tokens_in, NEW.tokens_out, NEW.cost_estimate)
             IS DISTINCT FROM (OLD.outcome, OLD.model, OLD.tokens_in, OLD.tokens_out, OLD.cost_estimate) THEN
            IF OLD.outcome <> 'reserved' OR NEW.outcome = 'reserved' THEN
              RAISE EXCEPTION 'ai_usage is append-only: only a reserved row can be finalised once'
                USING ERRCODE = 'check_violation';
            END IF;
          END IF;
          IF (NEW.id, NEW.organization_id, NEW.feature, NEW.context_type, NEW.context_id, NEW.provider, NEW.created_at)
             IS DISTINCT FROM (OLD.id, OLD.organization_id, OLD.feature, OLD.context_type, OLD.context_id, OLD.provider, OLD.created_at) THEN
            RAISE EXCEPTION 'ai_usage identity columns are immutable' USING ERRCODE = 'check_violation';
          END IF;
          RETURN NEW;
        END $$;
        CREATE TRIGGER trg_ai_usage_finalize_guard BEFORE UPDATE ON ai_usage
          FOR EACH ROW EXECUTE FUNCTION ai_usage_finalize_guard();
        CREATE INDEX IF NOT EXISTS ix_ai_usage_reserved ON ai_usage (created_at) WHERE outcome = 'reserved';
        """
    )

    # server-side tutor history (SEC-17)
    op.execute(
        """
        CREATE TABLE ai_tutor_turns (
          seq          bigint      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
          user_id      uuid        NOT NULL REFERENCES users(id),
          context_type text        NOT NULL CHECK (context_type IN ('assignment','path_step','practice')),
          context_id   uuid        NOT NULL,
          item_id      uuid        NULL,
          role         text        NOT NULL CHECK (role IN ('learner','tutor')),
          content      text        NOT NULL CHECK (char_length(content) BETWEEN 1 AND 8000),
          created_at   timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX ix_ai_tutor_turns_ctx ON ai_tutor_turns (user_id, context_type, context_id, item_id, seq);
        COMMENT ON TABLE ai_tutor_turns IS 'Owner: ai | RLS: own rows or platform | learner/tutor chat text, deleted on erasure | PII: P2';
        ALTER TABLE ai_tutor_turns ENABLE ROW LEVEL SECURITY;
        ALTER TABLE ai_tutor_turns FORCE ROW LEVEL SECURITY;
        CREATE POLICY p_ai_tutor_turns ON ai_tutor_turns FOR ALL TO td_app, td_readonly
          USING (user_id = app.user_id() OR app.is_platform())
          WITH CHECK (user_id = app.user_id() OR app.is_platform());
        GRANT SELECT, INSERT, DELETE ON ai_tutor_turns TO td_app;
        GRANT SELECT ON ai_tutor_turns TO td_readonly;
        REVOKE UPDATE, TRUNCATE ON ai_tutor_turns FROM td_app;
        """
    )


def downgrade() -> None:
    """Schema only; restore data from the dump taken before the single-company migration."""
    keys = ",".join(f"'{k}'" for k in APP_KEYS)
    op.execute("DROP TABLE IF EXISTS ai_tutor_turns")
    op.execute("DROP TRIGGER IF EXISTS trg_ai_usage_finalize_guard ON ai_usage")
    op.execute("DROP FUNCTION IF EXISTS ai_usage_finalize_guard()")
    op.execute("DROP INDEX IF EXISTS ix_ai_usage_reserved")
    op.execute("DROP INDEX IF EXISTS ix_ai_usage_time")
    op.execute("UPDATE ai_usage SET outcome = 'provider_error' WHERE outcome = 'reserved'")
    op.execute("REVOKE UPDATE (outcome, model, tokens_in, tokens_out, cost_estimate) ON ai_usage FROM td_app")
    op.execute("ALTER TABLE ai_usage DROP CONSTRAINT IF EXISTS ai_usage_outcome_check")
    op.execute(
        "ALTER TABLE ai_usage ADD CONSTRAINT ai_usage_outcome_check "
        "CHECK (outcome IN ('ok','invalid_output','provider_error'))"
    )
    op.execute(
        f"""
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
        ALTER TABLE ai_org_settings ENABLE ROW LEVEL SECURITY;
        ALTER TABLE ai_org_settings FORCE ROW LEVEL SECURITY;
        CREATE POLICY p_ai_settings_read ON ai_org_settings FOR SELECT TO td_app, td_readonly
          USING (organization_id = ANY (app.org_ids()) OR app.is_platform());
        CREATE POLICY p_ai_settings_write ON ai_org_settings FOR ALL TO td_app
          USING (app.is_platform()) WITH CHECK (app.is_platform());
        REVOKE DELETE, TRUNCATE ON ai_org_settings FROM td_app;
        CREATE TABLE org_app_settings (
          organization_id uuid        NOT NULL REFERENCES organizations(id),
          app_key         text        NOT NULL CHECK (app_key IN ({keys})),
          enabled         boolean     NOT NULL,
          updated_by      uuid        NULL REFERENCES users(id),
          updated_at      timestamptz NOT NULL DEFAULT now(),
          PRIMARY KEY (organization_id, app_key)
        );
        ALTER TABLE org_app_settings ENABLE ROW LEVEL SECURITY;
        ALTER TABLE org_app_settings FORCE ROW LEVEL SECURITY;
        CREATE POLICY p_app_settings_read ON org_app_settings FOR SELECT TO td_app, td_readonly
          USING (organization_id = ANY (app.org_ids()) OR app.is_platform());
        CREATE POLICY p_app_settings_write ON org_app_settings FOR ALL TO td_app
          USING (app.is_platform()) WITH CHECK (app.is_platform());
        REVOKE DELETE, TRUNCATE ON org_app_settings FROM td_app;
        """
    )
    add_updated_at_trigger("ai_org_settings")
    add_updated_at_trigger("org_app_settings")
    op.execute("DROP TABLE IF EXISTS app_settings")
    op.execute("DROP TABLE IF EXISTS ai_settings")
