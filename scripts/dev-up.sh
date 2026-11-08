#!/usr/bin/env bash
# Start the Tech Drona LMS local data services and wait until healthy (Linux/macOS/WSL/Git Bash).
#   scripts/dev-up.sh            # data services
#   scripts/dev-up.sh --with-app # + api/web/worker containers (compose profile `app`)
#   scripts/dev-up.sh --build    # rebuild images
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

WITH_APP=0
BUILD=0
TIMEOUT=180
for arg in "$@"; do
  case "$arg" in
    --with-app) WITH_APP=1 ;;
    --build) BUILD=1 ;;
    --timeout=*) TIMEOUT="${arg#*=}" ;;
    -h|--help) sed -n '2,4p' "$0"; exit 0 ;;
    *) echo "unknown argument: $arg" >&2; exit 2 ;;
  esac
done

command -v docker >/dev/null || { echo "docker not found on PATH" >&2; exit 1; }
docker info >/dev/null 2>&1 || { echo "Docker daemon not reachable" >&2; exit 1; }

if [ ! -f .env ]; then
  cp .env.example .env
  echo "Created .env from .env.example (local placeholders only)."
fi

envval() { # envval NAME DEFAULT
  local v
  v="$(grep -E "^[[:space:]]*$1[[:space:]]*=" .env 2>/dev/null | tail -n1 | cut -d= -f2- | tr -d '[:space:]' || true)"
  echo "${v:-$2}"
}

PG_PORT="$(envval TD_PG_HOST_PORT 5432)"
RC_PORT="$(envval TD_REDIS_CACHE_HOST_PORT 6379)"
RQ_PORT="$(envval TD_REDIS_QUEUE_HOST_PORT 6380)"
SMTP_PORT="$(envval TD_SMTP_HOST_PORT 1025)"
UI_PORT="$(envval TD_MAILPIT_UI_HOST_PORT 8025)"
S3_PORT="$(envval TD_S3_HOST_PORT 9000)"

OURS="$(docker compose ps --format '{{.Ports}}' 2>/dev/null || true)"
for p in "$PG_PORT" "$RC_PORT" "$RQ_PORT" "$SMTP_PORT" "$UI_PORT" "$S3_PORT"; do
  if ! grep -q ":$p->" <<<"$OURS"; then
    if (command -v ss >/dev/null && ss -ltn "( sport = :$p )" | grep -q LISTEN) \
       || (command -v lsof >/dev/null && lsof -iTCP:"$p" -sTCP:LISTEN >/dev/null 2>&1); then
      echo "WARNING: host port $p already in use; override it in .env (docs/local-development.md)" >&2
    fi
  fi
done

ARGS=(compose)
[ "$WITH_APP" = 1 ] && ARGS+=(--profile app)
ARGS+=(up -d --wait --wait-timeout "$TIMEOUT")
[ "$BUILD" = 1 ] && ARGS+=(--build)

echo "docker ${ARGS[*]}"
if ! docker "${ARGS[@]}"; then
  docker compose ps -a
  echo "docker compose up failed; inspect with: docker compose logs <service>" >&2
  exit 1
fi

docker compose ps --format 'table {{.Service}}\t{{.Status}}\t{{.Ports}}'
echo
echo "Postgres : localhost:$PG_PORT (techdrona + techdrona_test; superuser techdrona/techdrona_dev)"
echo "Redis    : localhost:$RC_PORT (cache), localhost:$RQ_PORT (queue)"
echo "Mailpit  : smtp localhost:$SMTP_PORT, UI http://localhost:$UI_PORT"
echo "S3       : http://localhost:$S3_PORT (buckets local-td-*)"
