#!/usr/bin/env bash
# DESTROY and recreate the LOCAL Postgres volume, re-run scripts/db-init/, then migrate.
#   scripts/reset-db.sh --force [--skip-migrations]
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

FORCE=0; SKIP_MIG=0
for a in "$@"; do
  case "$a" in
    --force) FORCE=1 ;;
    --skip-migrations) SKIP_MIG=1 ;;
    *) echo "unknown argument: $a" >&2; exit 2 ;;
  esac
done
if [ "$FORCE" != 1 ]; then
  read -r -p "Delete ALL local Postgres data (techdrona + techdrona_test)? type yes: " ans
  [ "$ans" = "yes" ] || { echo "Aborted."; exit 1; }
fi

docker compose stop postgres >/dev/null
docker compose rm -f postgres >/dev/null
docker volume rm techdrona_pgdata >/dev/null 2>&1 || true
docker compose up -d --wait postgres

[ "$SKIP_MIG" = 1 ] && exit 0
ALEMBIC="apps/api/.venv/bin/alembic"
[ -x "$ALEMBIC" ] || { echo "apps/api/.venv missing; skipping migrations"; exit 0; }

envval() { grep -E "^[[:space:]]*$1[[:space:]]*=" .env 2>/dev/null | tail -n1 | cut -d= -f2- || true; }
cd apps/api
../../"$ALEMBIC" upgrade heads
TEST_URL="$(cd "$ROOT" && envval TEST_DATABASE_MIGRATION_URL)"
if [ -z "$TEST_URL" ]; then
  MIG="$(cd "$ROOT" && envval DATABASE_MIGRATION_URL)"
  TEST_URL="${MIG%/techdrona}/techdrona_test"
fi
DATABASE_MIGRATION_URL="$TEST_URL" ../../"$ALEMBIC" upgrade heads
echo "Database reset complete."
