#!/bin/sh
# Cloud Run start: restore the newest Litestream replica (or, on the very first start, the seed DB), then run the
# server under Litestream (continuous replication to gs://$LITESTREAM_BUCKET/db).
set -eu
: "${LITESTREAM_BUCKET:?LITESTREAM_BUCKET is not set}"
: "${PORTAL_PROXY_SECRET:?PORTAL_PROXY_SECRET is not set (the portal must run in LMS proxy mode)}"
DB="${DB_PATH:-/data/techdrona.db}"
mkdir -p "$(dirname "$DB")"
litestream restore -config /etc/litestream.yml -if-replica-exists "$DB"
if [ ! -f "$DB" ]; then
  echo "No replica yet: downloading the seed gs://${LITESTREAM_BUCKET}/${SEED_OBJECT:-seed/techdrona.db}"
  node /app/fetch_seed.mjs "$DB"
fi
exec litestream replicate -config /etc/litestream.yml -exec "node /app/server/server.js"
