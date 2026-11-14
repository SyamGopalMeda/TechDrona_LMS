#!/usr/bin/env bash
# Submit a live audit run to Cloud Build and fetch the small result files (not the screenshots).
#   bash qa/live-e2e/run.sh [spec] [--projects=a,b] [--roles=a,b] [--workers=N] [--shots]
# Prints the run dir: qa/live-e2e/runs/<build-id>/ with results.json, exit_code, findings/.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
SPEC=""; PROJECTS="desktop"; ROLES=""; WORKERS="2"; SHOTS=0
for a in "$@"; do case "$a" in
  --projects=*) PROJECTS="${a#*=}";; --roles=*) ROLES="${a#*=}";; --workers=*) WORKERS="${a#*=}";; --shots) SHOTS=1;;
  *) SPEC="$a";; esac; done
ID=$(gcloud builds submit "$HERE" --project billing-f4fe3 --config "$HERE/cloudbuild.yaml" --async --format='value(id)' \
  --substitutions="^~^_SPEC=$SPEC~_PROJECTS=$PROJECTS~_ROLES=$ROLES~_WORKERS=$WORKERS")  # ^~^: values may hold commas
echo "build $ID submitted" >&2
# Light polling (gcloud is a Python process: keep calls rare on the low-RAM laptop; survive a failed poll).
while :; do sleep 45; S=$(gcloud builds describe "$ID" --project billing-f4fe3 --format='value(status)' 2>/dev/null || echo WORKING); case "$S" in QUEUED|WORKING|"") ;; *) break;; esac; done
echo "build $ID: $S" >&2
OUT="$HERE/runs/$ID"; mkdir -p "$OUT"
gcloud storage cp "gs://td-qa-reports-f4fe3/runs/$ID/results.json" "gs://td-qa-reports-f4fe3/runs/$ID/exit_code" "$OUT/" --quiet 2>/dev/null || true
gcloud storage cp -r "gs://td-qa-reports-f4fe3/runs/$ID/findings" "$OUT/" --quiet 2>/dev/null || true
[ "$SHOTS" = 1 ] && gcloud storage cp -r "gs://td-qa-reports-f4fe3/runs/$ID/artifacts" "$OUT/" --quiet 2>/dev/null || true
echo "$OUT"
