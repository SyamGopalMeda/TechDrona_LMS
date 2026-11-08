"""core_base: extensions, roles, schemas, RLS context functions, kernel tables

Revision ID: core_base_0001
Revises:
Create Date: 2026-11-03

Role strategy (ADR-0003/0009, database-schema §1.2):
* Migrations run as the owner (``td_owner`` via DATABASE_MIGRATION_URL; in docker-compose the
  login roles td_owner/td_app/td_readonly/td_audit_sealer/td_maintenance are created by
  scripts/db-init). This migration creates any of those roles that are missing as NOLOGIN
  (needs CREATEROLE; skipped with a NOTICE otherwise — in AWS they are provisioned by infra).
* The app connects as ``td_app`` (not owner, NOBYPASSRLS) so FORCE RLS is meaningful.
* Default privileges: tables created later by the migration role grant DML to td_app and
  SELECT to td_readonly; append-only tables revoke UPDATE/DELETE explicitly.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

from app.core.migration_helpers import enable_rls

revision: str = "core_base_0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = ("core_base",)
depends_on: str | Sequence[str] | None = None

RUNTIME_ROLES = ("td_app", "td_readonly", "td_audit_sealer", "td_maintenance")


def upgrade() -> None:
    # Trusted extensions (CREATE privilege on the database is enough on PG13+).
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
    op.execute("CREATE EXTENSION IF NOT EXISTS citext")
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")

    roles = ", ".join(f"'{r}'" for r in RUNTIME_ROLES)
    op.execute(
        f"""
        DO $$
        DECLARE r text;
        BEGIN
          FOREACH r IN ARRAY ARRAY[{roles}] LOOP
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
              BEGIN
                EXECUTE format('CREATE ROLE %I NOLOGIN NOSUPERUSER NOBYPASSRLS', r);
              EXCEPTION WHEN insufficient_privilege THEN
                RAISE NOTICE 'core_base: cannot create role % (no CREATEROLE); provision it externally', r;
              END;
            END IF;
          END LOOP;
        END $$;
        """
    )

    op.execute("CREATE SCHEMA IF NOT EXISTS app")
    op.execute("CREATE SCHEMA IF NOT EXISTS maint")
    op.execute("REVOKE ALL ON SCHEMA maint FROM PUBLIC")
    op.execute("GRANT USAGE ON SCHEMA app TO td_app, td_readonly, td_audit_sealer")
    op.execute("GRANT USAGE ON SCHEMA public TO td_app, td_readonly, td_audit_sealer")

    # ---- RLS context functions (database-schema §2.1) + aliases used in conventions docs
    op.execute(
        """
        CREATE OR REPLACE FUNCTION app.user_id() RETURNS uuid LANGUAGE sql STABLE AS
        $$ SELECT nullif(current_setting('app.user_id', true), '')::uuid $$;

        CREATE OR REPLACE FUNCTION app.org_ids() RETURNS uuid[] LANGUAGE sql STABLE AS
        $$ SELECT coalesce(string_to_array(nullif(current_setting('app.org_ids', true), ''), ',')::uuid[], '{}') $$;

        CREATE OR REPLACE FUNCTION app.is_platform() RETURNS boolean LANGUAGE sql STABLE AS
        $$ SELECT coalesce(current_setting('app.is_platform', true), 'off') = 'on' $$;

        CREATE OR REPLACE FUNCTION app.actor() RETURNS text LANGUAGE sql STABLE AS
        $$ SELECT nullif(current_setting('app.actor', true), '') $$;

        CREATE OR REPLACE FUNCTION app.roles() RETURNS text[] LANGUAGE sql STABLE AS
        $$ SELECT coalesce(string_to_array(nullif(current_setting('app.roles', true), ''), ','), '{}') $$;

        CREATE OR REPLACE FUNCTION app.privacy_tier() RETURNS text LANGUAGE sql STABLE AS
        $$ SELECT nullif(current_setting('app.privacy_tier', true), '') $$;

        CREATE OR REPLACE FUNCTION app.has_role(role_key text) RETURNS boolean LANGUAGE sql STABLE AS
        $$ SELECT role_key = ANY (app.roles()) $$;

        CREATE OR REPLACE FUNCTION app.has_platform_role(role_key text) RETURNS boolean LANGUAGE sql STABLE AS
        $$ SELECT app.is_platform() AND role_key = ANY (app.roles()) $$;

        CREATE OR REPLACE FUNCTION app.current_user_id() RETURNS uuid LANGUAGE sql STABLE AS
        $$ SELECT app.user_id() $$;

        CREATE OR REPLACE FUNCTION app.current_org_ids() RETURNS uuid[] LANGUAGE sql STABLE AS
        $$ SELECT app.org_ids() $$;

        CREATE OR REPLACE FUNCTION app.set_updated_at() RETURNS trigger LANGUAGE plpgsql AS
        $$ BEGIN NEW.updated_at := now(); RETURN NEW; END $$;
        """
    )

    # ---- default privileges for tables created later by this (migration) role
    op.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO td_app"
    )
    op.execute("ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO td_readonly")
    op.execute("ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO td_app")

    # ---- kernel tables (database-schema §2.3)
    op.execute(
        """
        CREATE TABLE outbox_events (
          id              uuid PRIMARY KEY,
          event_type      text        NOT NULL,
          aggregate_type  text        NOT NULL,
          aggregate_id    uuid        NOT NULL,
          payload         jsonb       NOT NULL,
          organization_id uuid        NULL,
          occurred_at     timestamptz NOT NULL DEFAULT now(),
          dispatched_at   timestamptz NULL,
          attempts        int         NOT NULL DEFAULT 0,
          last_error      text        NULL
        );
        CREATE INDEX ix_outbox_pending ON outbox_events (occurred_at) WHERE dispatched_at IS NULL;
        COMMENT ON TABLE outbox_events IS 'Owner: core | RLS: NONE | Retention: dispatched rows 7 days | PII: P1 ids only';

        CREATE TABLE idempotency_keys (
          id              uuid PRIMARY KEY,
          user_id         uuid        NULL,   -- soft reference to users(id) (identity branch)
          route_key       text        NOT NULL,
          idem_key        text        NOT NULL,
          request_hash    bytea       NOT NULL,
          status          text        NOT NULL,
          response_status int         NULL,
          response_body   jsonb       NULL,
          resource_id     uuid        NULL,
          created_at      timestamptz NOT NULL DEFAULT now(),
          expires_at      timestamptz NOT NULL,
          CONSTRAINT ck_idempotency_keys_idem_key_len CHECK (char_length(idem_key) BETWEEN 8 AND 128),
          CONSTRAINT ck_idempotency_keys_request_hash_len CHECK (octet_length(request_hash) = 32),
          CONSTRAINT ck_idempotency_keys_status CHECK (status IN ('in_progress','completed','failed')),
          CONSTRAINT uq_idempotency_keys_user_route_key UNIQUE NULLS NOT DISTINCT (user_id, route_key, idem_key)
        );
        CREATE INDEX ix_idem_expires ON idempotency_keys (expires_at);
        COMMENT ON TABLE idempotency_keys IS 'Owner: core | RLS: O | Retention: 24h (money 7d) | PII: P1';
        """
    )
    # Default privileges only cover tables created after the ALTER above in the same role;
    # grant explicitly for robustness.
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON outbox_events, idempotency_keys TO td_app")
    op.execute("GRANT SELECT ON outbox_events, idempotency_keys TO td_readonly")
    enable_rls("idempotency_keys", "O")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS idempotency_keys")
    op.execute("DROP TABLE IF EXISTS outbox_events")
    op.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE SELECT, INSERT, UPDATE, DELETE ON TABLES FROM td_app"
    )
    op.execute("ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE SELECT ON TABLES FROM td_readonly")
    op.execute("ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE USAGE, SELECT ON SEQUENCES FROM td_app")
    op.execute("DROP SCHEMA IF EXISTS app CASCADE")
    op.execute("DROP SCHEMA IF EXISTS maint CASCADE")
    # Roles and extensions are cluster/database-level and intentionally left in place.
