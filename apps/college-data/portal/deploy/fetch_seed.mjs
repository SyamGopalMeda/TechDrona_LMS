// Cloud Run only: download the one-time seed database gs://$LITESTREAM_BUCKET/seed/techdrona.db to <target>, with the
// service account token from the metadata server (no gcloud in the image). Used by entrypoint.sh when no replica exists.
// Fails (exit 1) when the seed is missing: the portal must never start with an empty database by accident.
import fs from 'node:fs';

const [target] = process.argv.slice(2);
const bucket = process.env.LITESTREAM_BUCKET;
const object = process.env.SEED_OBJECT || 'seed/techdrona.db';
if (!target || !bucket) { console.error('usage: LITESTREAM_BUCKET=<bucket> node fetch_seed.mjs <target.db>'); process.exit(2); }
const tok = await fetch('http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token', { headers: { 'Metadata-Flavor': 'Google' } });
if (!tok.ok) { console.error(`metadata token: HTTP ${tok.status}`); process.exit(1); }
const { access_token: token } = await tok.json();
const r = await fetch(`https://storage.googleapis.com/storage/v1/b/${encodeURIComponent(bucket)}/o/${encodeURIComponent(object)}?alt=media`, { headers: { Authorization: `Bearer ${token}` } });
if (!r.ok) { console.error(`seed gs://${bucket}/${object}: HTTP ${r.status}`); process.exit(1); }
const buf = Buffer.from(await r.arrayBuffer());
fs.writeFileSync(`${target}.tmp`, buf);
fs.renameSync(`${target}.tmp`, target);
console.log(`seed restored: ${buf.length} bytes -> ${target}`);
