#!/usr/bin/env bash
# Create the LMS Cloud Storage buckets in a NO-COST region (cost-media agent; see
# docs/firebase/agents/cost-media.md §4). NOT RUN BY THE MIGRATION AGENTS: the owner runs it once,
# before the first deploy, after approving the region.
#
#   BUCKET_PREFIX=td-lms bash functions-lms/deploy/create-buckets.sh [--dry-run]
#
# Why us-central1: Cloud Storage's always-free usage (5 GB-months Standard storage, 5,000 Class A
# and 50,000 Class B operations, 100 GB egress per month) applies ONLY to buckets in us-central1,
# us-east1 or us-west1. The same buckets in asia-south1 bill every GB stored and every GB
# downloaded from the first byte. What changes for users: an upload/download from India takes one
# longer round trip (~200-250 ms more) to start; videos are not served from these buckets
# (VdoCipher streams them), only PDFs, images, captions, submissions, certificates and exports.
# Data residency: the objects (learner submissions, admission proofs, invoices) are then stored in
# the USA; the owner decides (cost-media.md §4.3).
#
# The app needs no code change: it addresses buckets by name through the S3 API
# (S3_ENDPOINT_URL=https://storage.googleapis.com). Put the four names below into
# functions-lms/.env.<project> (S3_BUCKET_UPLOADS/CONTENT/CERTIFICATES/EXPORTS).
#
# Existing buckets in another region cannot be moved: create these, copy the objects
# (`gcloud storage rsync -r gs://OLD gs://NEW`), switch the env names, deploy, verify a download,
# then delete the old buckets.
#
# No lifecycle (auto-delete) rule is set: the exports bucket also holds invoices/receipts
# (commerce documents), so nothing in it is disposable. GCS soft delete stays at its default
# (deleted objects recoverable for 7 days; they count as stored bytes meanwhile).
set -euo pipefail

PROJECT="${PROJECT:-billing-f4fe3}"
LOCATION="${LOCATION:-us-central1}"   # us-central1 | us-east1 | us-west1 for the free tier
PREFIX="${BUCKET_PREFIX:?set BUCKET_PREFIX, e.g. td-lms (bucket names are global)}"
DRY="${1:-}"
CORS="$(cd "$(dirname "$0")" && pwd)/gcs-cors.json"

case "$LOCATION" in
  us-central1|us-east1|us-west1) ;;
  *) echo "warning: $LOCATION is outside the Cloud Storage free tier (us-central1/us-east1/us-west1)" ;;
esac
if grep -q "REPLACE" "$CORS"; then
  echo "edit $CORS first: set the LMS site origin(s)"; exit 1
fi

run() { if [ "$DRY" = "--dry-run" ]; then echo "dry run: $*"; else "$@"; fi; }

for kind in uploads content certificates exports; do
  b="gs://$PREFIX-$kind"
  if gcloud storage buckets describe "$b" --project "$PROJECT" >/dev/null 2>&1; then
    echo "exists, left unchanged: $b"; continue
  fi
  run gcloud storage buckets create "$b" --project "$PROJECT" --location "$LOCATION" \
    --default-storage-class STANDARD --uniform-bucket-level-access --public-access-prevention
  run gcloud storage buckets update "$b" --cors-file="$CORS"
done

echo "== env values"
echo "S3_BUCKET_UPLOADS=$PREFIX-uploads"
echo "S3_BUCKET_CONTENT=$PREFIX-content"
echo "S3_BUCKET_CERTIFICATES=$PREFIX-certificates"
echo "S3_BUCKET_EXPORTS=$PREFIX-exports"
