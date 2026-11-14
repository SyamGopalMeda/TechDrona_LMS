#!/usr/bin/env bash
# Deploy the Tech Drona LMS to Firebase (Hosting target "lms" + functions codebase "lms").
# NOT RUN BY THE MIGRATION AGENTS. Read docs/firebase/agents/platform.md "Deploy steps" first:
# the owner approves, secrets exist, the site exists, the SPA is built with the Firebase env.
#
#   bash functions-lms/deploy/deploy.sh [--only-functions|--only-hosting] [--dry-run]
set -euo pipefail

PROJECT="${PROJECT:-billing-f4fe3}"
REGION="asia-south1"
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
FN="$ROOT/functions-lms"
WHAT="${1:-all}"
DRY="${2:-}"

cd "$ROOT"
[ -f "$FN/.env.$PROJECT" ] || { echo "missing $FN/.env.$PROJECT (copy .env.example, fill the REPLACE values)"; exit 1; }
if grep -q "REPLACE" "$FN/.env.$PROJECT"; then echo "fill every REPLACE value in $FN/.env.$PROJECT"; exit 1; fi

echo "== secrets present in Secret Manager"
while read -r name _; do
  case "$name" in ""|\#*) continue ;; esac
  gcloud secrets describe "$name" --project "$PROJECT" >/dev/null 2>&1 || { echo "missing secret $name"; exit 1; }
done < "$FN/secrets.txt"

echo "== build function source (copy apps/api/app, schedules.json, venv)"
python "$FN/tools/build.py"

if [ "$WHAT" != "--only-functions" ]; then
  echo "== SPA build + headers"
  (cd apps/lms-spa && npm ci && npm run build)
  python "$FN/tools/sync_hosting.py"
  [ -f apps/lms-spa/dist/index.html ] || { echo "apps/lms-spa/dist/index.html missing"; exit 1; }
fi

ONLY="functions:lms,hosting:lms"
[ "$WHAT" = "--only-functions" ] && ONLY="functions:lms"
[ "$WHAT" = "--only-hosting" ] && ONLY="hosting:lms"

if [ "$DRY" = "--dry-run" ] || [ "$WHAT" = "--dry-run" ]; then
  echo "dry run: firebase deploy --only $ONLY --project $PROJECT"
  exit 0
fi
firebase deploy --only "$ONLY" --project "$PROJECT"
echo "== smoke"
SITE_URL="$(grep '^TD_PUBLIC_BASE_URL=' "$FN/.env.$PROJECT" | cut -d= -f2-)"
curl -fsS "$SITE_URL/api/v1/health/live" && echo
curl -fsS -o /dev/null -w "csrf bootstrap: %{http_code}\n" "$SITE_URL/api/v1/_bff/csrf"
