#!/bin/sh
# Tech Drona LMS — create local S3 buckets (names from .env.example S3_BUCKET_*; prefix local-).
# LOCAL ONLY. Idempotent. Runs in the `s3-init` one-shot container (amazon/aws-cli).
set -eu
EP="${S3_ENDPOINT:-http://s3:8333}"
for b in local-td-uploads local-td-content local-td-certificates local-td-exports \
         local-td-judge-private local-td-audit-anchor; do
  if aws --endpoint-url "$EP" s3api head-bucket --bucket "$b" >/dev/null 2>&1; then
    echo "s3-init: bucket $b exists"
  else
    aws --endpoint-url "$EP" s3api create-bucket --bucket "$b" >/dev/null
    echo "s3-init: created $b"
  fi
done
# Versioning on every bucket (prod parity, deployment-and-operations §4.3). Object Lock
# compliance mode for td-audit-anchor is enforced in AWS only (infra/terraform); the local
# emulator does not provide WORM guarantees.
for b in local-td-uploads local-td-content local-td-certificates local-td-exports \
         local-td-judge-private local-td-audit-anchor; do
  aws --endpoint-url "$EP" s3api put-bucket-versioning --bucket "$b" \
    --versioning-configuration Status=Enabled >/dev/null 2>&1 || echo "s3-init: versioning not supported for $b (ok locally)"
done
echo "s3-init: done"
