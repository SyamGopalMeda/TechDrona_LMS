-- =============================================================================
-- Tech Drona LMS — local docker-compose Postgres init (LOCAL / CI ONLY)
-- Runs once, on first start of an empty data volume, as the bootstrap
-- superuser `techdrona` (docker-entrypoint-initdb.d). To re-run:
--   scripts/reset-db.ps1  (drops the volume)
--
-- Creates:
--   * database techdrona_test (integration tests, TEST_DATABASE_URL)
--   * login roles td_owner, td_app, td_readonly, td_audit_sealer, td_maintenance
--     with the LOCAL placeholder passwords from .env.example, so that RLS behaves
--     as in prod (tests must run as td_app, never as a superuser).
--   * extensions in both databases (superuser-only ones must exist before the
--     Foundation `core_base` migration, which should use IF NOT EXISTS).
--
-- NOT created here (owned by Alembic `core_base`, ADR-0009): schemas other than
-- partman, grants on tables, helper functions, RLS policies. Role *attributes*
-- beyond LOGIN/NOINHERIT are also left to the migration.
-- These passwords are local placeholders — never reuse outside docker-compose.
-- =============================================================================

DO $$
DECLARE
  r record;
BEGIN
  FOR r IN SELECT * FROM (VALUES
      ('td_owner',        'local_owner_pw_REPLACE'),
      ('td_app',          'local_app_pw_REPLACE'),
      ('td_readonly',     'local_ro_pw_REPLACE'),
      ('td_audit_sealer', 'local_sealer_pw_REPLACE'),
      ('td_maintenance',  'local_maint_pw_REPLACE')
    ) AS t(rolname, pw)
  LOOP
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r.rolname) THEN
      EXECUTE format('CREATE ROLE %I LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS PASSWORD %L',
                     r.rolname, r.pw);
    END IF;
  END LOOP;
END
$$;

-- td_owner runs migrations (DDL) and may create the non-login roles a migration needs.
ALTER ROLE td_owner CREATEROLE;

CREATE DATABASE techdrona_test OWNER techdrona;

GRANT CONNECT, CREATE, TEMPORARY ON DATABASE techdrona      TO td_owner;
GRANT CONNECT, CREATE, TEMPORARY ON DATABASE techdrona_test TO td_owner;
GRANT CONNECT ON DATABASE techdrona      TO td_app, td_readonly, td_audit_sealer, td_maintenance;
GRANT CONNECT ON DATABASE techdrona_test TO td_app, td_readonly, td_audit_sealer, td_maintenance;
