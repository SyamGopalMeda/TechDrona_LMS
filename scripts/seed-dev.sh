#!/usr/bin/env bash
# Load DEV/DEMO data into the local database (Linux/macOS/WSL/Git Bash).
#   scripts/seed-dev.sh              # rbac sync + all demo seeds, in dependency order
#   scripts/seed-dev.sh --migrate    # alembic upgrade heads first
#   scripts/seed-dev.sh --only catalog_demo,coding_demo
# Order: rbac_seed (reference data, idempotent) -> dev_users -> catalog_demo -> placement_demo
#        -> coding_demo -> commerce_demo -> security_demo -> e2e_demo -> company_demo. Idempotent.
# Refuses when APP_ENV (environment or root .env) is prod/production. Runs on the HOST with
# apps/api/.venv: the td-api image deliberately ships no demo seeds (G-21).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
API="$ROOT/apps/api"
MIGRATE=0
ONLY=""
for arg in "$@"; do
  case "$arg" in
    --migrate) MIGRATE=1 ;;
    --only=*) ONLY="${arg#*=}" ;;
    -h|--help) sed -n '2,9p' "$0"; exit 0 ;;
    *) echo "unknown argument: $arg" >&2; exit 2 ;;
  esac
done

app_env="${APP_ENV:-}"
if [ -z "$app_env" ] && [ -f "$ROOT/.env" ]; then
  app_env="$(grep -E '^[[:space:]]*APP_ENV[[:space:]]*=' "$ROOT/.env" | tail -n1 | cut -d= -f2- | tr -d '[:space:]"' || true)"
fi
case "${app_env,,}" in
  prod|production) echo "REFUSED: APP_ENV=$app_env — demo seeds never run against production." >&2; exit 3 ;;
esac

if [ -x "$API/.venv/bin/python" ]; then PY="$API/.venv/bin/python"
elif [ -x "$API/.venv/Scripts/python.exe" ]; then PY="$API/.venv/Scripts/python.exe"
else echo "apps/api/.venv not found — run: make install-api" >&2; exit 1; fi

cd "$API"
if [ "$MIGRATE" = 1 ]; then
  echo "==> alembic upgrade heads"
  "$PY" -m alembic upgrade heads
fi

RUNNER='import runpy, sys; from app.core.models_registry import import_all_models; import_all_models(); m = sys.argv[1]; sys.argv = [m]; runpy.run_module(m, run_name="__main__", alter_sys=True)'

SEEDS=(rbac_seed dev_users catalog_demo placement_demo coding_demo commerce_demo security_demo e2e_demo company_demo)
if [ -n "$ONLY" ]; then IFS=',' read -r -a SEEDS <<<"$ONLY"; fi

for s in "${SEEDS[@]}"; do
  echo "==> python -m app.seeds.$s"
  # Preload every module's models so cross-module FKs resolve (a seed may import only its own).
  if ! "$PY" -c "$RUNNER" "app.seeds.$s"; then
    echo "seed $s FAILED (earlier seeds were committed; fix and re-run — seeds are idempotent)" >&2
    exit 1
  fi
done
echo "All seeds completed: ${SEEDS[*]}"
