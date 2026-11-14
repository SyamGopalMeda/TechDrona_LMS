#!/usr/bin/env bash
# Tech Drona LMS GCP demo — first-start Postgres init (runs once on an empty volume).
# Creates the application login roles with passwords from the container environment
# (TD_PG_*_PASSWORD, sourced from /opt/techdrona/server.env) and the extensions the
# core_base migration expects. No passwords are stored in this file.
set -euo pipefail

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
  -v owner_pw="$TD_PG_OWNER_PASSWORD" -v app_pw="$TD_PG_APP_PASSWORD" \
  -v ro_pw="$TD_PG_READONLY_PASSWORD" -v sealer_pw="$TD_PG_SEALER_PASSWORD" \
  -v maint_pw="$TD_PG_MAINT_PASSWORD" <<'SQL'
CREATE ROLE td_owner        LOGIN NOSUPERUSER NOCREATEDB CREATEROLE   NOBYPASSRLS PASSWORD :'owner_pw';
CREATE ROLE td_app          LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS PASSWORD :'app_pw';
CREATE ROLE td_readonly     LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS PASSWORD :'ro_pw';
CREATE ROLE td_audit_sealer LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS PASSWORD :'sealer_pw';
CREATE ROLE td_maintenance  LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS PASSWORD :'maint_pw';

GRANT CONNECT, CREATE, TEMPORARY ON DATABASE techdrona TO td_owner;
GRANT CONNECT ON DATABASE techdrona TO td_app, td_readonly, td_audit_sealer, td_maintenance;

CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS citext;
CREATE EXTENSION IF NOT EXISTS btree_gist;
CREATE EXTENSION IF NOT EXISTS pg_stat_statements;
CREATE SCHEMA IF NOT EXISTS partman;
CREATE EXTENSION IF NOT EXISTS pg_partman SCHEMA partman;

GRANT USAGE, CREATE ON SCHEMA public TO td_owner;
GRANT ALL ON SCHEMA partman TO td_owner;
GRANT ALL ON ALL TABLES IN SCHEMA partman TO td_owner;
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA partman TO td_owner;
GRANT EXECUTE ON ALL PROCEDURES IN SCHEMA partman TO td_owner;
SQL
echo "td-init: roles and extensions ready"
