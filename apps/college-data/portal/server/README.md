# Tech Drona portal — server

Zero-dependency Node 24 server (`node:http` + `node:sqlite`). API reference and business rules: `../CONTRACT.md` (section "v4" for the
current rules R1–R15).

## Run
```
cd portal
node server/server.js                      # http://localhost:4173, this computer only (binds 127.0.0.1)
PORT=4211 DB_PATH=/path/copy.db TODAY=2026-11-07 node server/server.js   # a copy, another port, a fixed date
```
Environment:

| Variable | Meaning |
|---|---|
| `PORT` | default 4173 |
| `HOST` | default `127.0.0.1`. Any non-loopback value (e.g. `0.0.0.0` for the LAN) refuses to start unless `PORTAL_PASSCODE` (or `PORTAL_PROXY_SECRET`) is set. |
| `PORTAL_PASSCODE` | turns on sign-in: every `/api` call (except `/api/health`, `/api/session`) needs the session cookie from `POST /api/session` (12 h) or the legacy `X-Passcode` header. Without it the portal behaves as before (no login). |
| `PORTAL_VIEWER_PASSCODE` | optional read-only sign-in (writes → 403). |
| `PORTAL_PROXY_SECRET` | proxy mode for the Tech Drona LMS (min 32 chars): every request needs header `x-td-proxy-secret` (except `GET/HEAD /api/health`), identity/role come from `x-td-proxy-user` / `x-td-proxy-role`, Host/Origin checks are left to the proxy, framing allowed for the same origin. Also allows a non-loopback `HOST`. See ../README.md. |
| `PORTAL_ALLOWED_HOSTS` | optional comma list of Host names; other Host headers → 403 (DNS rebinding guard). |
| `PORTAL_CSP=off` | disables the Content-Security-Policy header on HTML (debugging only). |
| `DB_PATH` | default `data/techdrona.db`. |
| `TODAY` | fixed `YYYY-MM-DD` for tests; otherwise today's date in Asia/Kolkata. |

Five wrong passcodes from one IP within 10 minutes lock that IP out for the rest of the window (429).

## Files
- `server.js` — routes, validation (`ENT` definitions + `preparePerson` / `prepareTarget` / `prepareEnrollment`), auth, idempotency.
- `rollup.js` — rollups, `judge()` (remaining / exceeded_by / pct / status), periods, `performance()`, assignment status.
- `calls.js` — calling system, funnel, target dashboard.
- `db.js` — open + idempotent migrations (v4: targets rebuilt once with min/max/period; new columns; people phones normalised).
- `schema.sql` — table definitions for new databases.
- `seed.js` — reference data (keeps every admin edit). `import_research.js` — research planner import (matches by research id).
- `selftest.js` — `node server/selftest.js`: copies the live DB to a temp dir, never touches it; ~390 checks incl. v4 scenarios.

## Migration notes (v4)
Opening a pre-v4 database migrates it in place, once, inside a transaction: the `targets` table is copied to a new definition
(same ids, every row becomes period `programme`), columns are added (`colleges.verified_fields`, `colleges.research_id`,
`contacts.verified_by/verified_on`), people phones are normalised to `+91XXXXXXXXXX` where possible (audited as actor `system`),
and `settings.program_start` is added (2026-11-03). Back up `data/techdrona.db` first and restart the running server after updating
the code (an old server process must not keep running against a migrated file).
