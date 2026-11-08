#!/usr/bin/env bash
# Tech Drona LMS — install extensions + base grants in techdrona and techdrona_test.
# LOCAL / CI ONLY. Runs from docker-entrypoint-initdb.d after 01-init.sql.
set -euo pipefail

for db in "${POSTGRES_DB:-techdrona}" techdrona_test; do
  echo "td-init: preparing database ${db}"
  psql -v ON_ERROR_STOP=1 --username "${POSTGRES_USER}" --dbname "${db}" <<'SQL'
CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS citext;
CREATE EXTENSION IF NOT EXISTS btree_gist;
CREATE EXTENSION IF NOT EXISTS pg_stat_statements;
CREATE SCHEMA IF NOT EXISTS partman;
CREATE EXTENSION IF NOT EXISTS pg_partman SCHEMA partman;

-- td_owner owns all application DDL (migrations). PG15+ removed CREATE on public from PUBLIC.
GRANT USAGE, CREATE ON SCHEMA public TO td_owner;
GRANT ALL ON SCHEMA partman TO td_owner;
GRANT ALL ON ALL TABLES IN SCHEMA partman TO td_owner;
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA partman TO td_owner;
GRANT EXECUTE ON ALL PROCEDURES IN SCHEMA partman TO td_owner;
SQL
done
echo "td-init: done"
