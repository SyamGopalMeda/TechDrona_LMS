# Tech Drona Outreach Portal

Tracks engineering colleges across Andhra Pradesh: branches, ambassadors, targets, enrollments, follow-ups and exam
windows. It needs **Node 24** and nothing else. There are no npm dependencies and no build step. The data lives in
one SQLite file, `data/techdrona.db`. The shared build spec is `CONTRACT.md`.

## Run

```bash
cd portal
node server/seed.js        # first time: create the DB and load reference data (safe to re-run)
node server/import_research.js --dry-run   # target planner: diff the research CSVs (research_notes/... colleges 2) against the DB
node server/import_research.js             # load them into college_plan / college_plan_branches (idempotent; adds ANR CET once)
node server/server.js      # http://localhost:4173   (or: npm start)
```

Environment variables:

| Var | Default | Meaning |
|---|---|---|
| `PORT` | `4173` | HTTP port |
| `HOST` | *(unset: loopback, 127.0.0.1 and ::1)* | Bind address. A non-loopback value (e.g. `0.0.0.0`) is refused unless `PORTAL_PASSCODE` (or `PORTAL_PROXY_SECRET`) is set |
| `DB_PATH` | `data/techdrona.db` | SQLite file (created with an empty schema if missing) |
| `PORTAL_PASSCODE` | *(unset)* | Editor passcode. When set, reads **and** writes need a sign-in (session cookie, or header `X-Passcode`) |
| `PORTAL_VIEWER_PASSCODE` | *(unset)* | Optional view-only passcode |
| `PORTAL_PROXY_SECRET` | *(unset)* | Proxy mode for the Tech Drona LMS (at least 32 characters); see "Running inside the Tech Drona LMS" |
| `TRUST_PROXY` | *(unset)* | `1` = trust `X-Forwarded-For/Proto/Host` from a reverse proxy in front of the server |
| `LIVE_DISABLED` | *(unset)* | `1` = never fetch the official live sources |
| `TODAY` | *(system date)* | `YYYY-MM-DD` override for testing pace and exam state |

### Set a passcode
```bash
PORTAL_PASSCODE='choose-something' node server/server.js           # bash
$env:PORTAL_PASSCODE='choose-something'; node server/server.js     # PowerShell
```
With a passcode set, the portal shows a sign-in screen (your name + the passcode) and every read and write needs that
sign-in; `/api/health` stays open. Without a passcode the portal is open to whoever can reach it (loopback only by default),
and changes only need a name (`X-User`).

## Seed and reseed

`node server/seed.js` loads these files from `data/seed/`:

- `master_colleges.json` (required)
- `geo_a.json` and `geo_b.json` (optional: location, contacts, operating status)
- `branches.json` (optional: branches and intake)
- `exams.json`
- `contacts.json` and/or `contacts_*.json` (optional: college phone/email contacts from the research team; format in
  CONTRACT.md "Contacts import". Rows with no valid phone or email are skipped and listed in the output)

It is **idempotent**, so run it again whenever any seed file changes. Each run:

- upserts districts (the 26 fixed ids, plus any new district id found in the geo files), cities, colleges (`c<sno>`),
  branches (keyed by college + code) and exams (keyed by college + semester);
- **keeps manual edits**: for any row last changed by someone other than `seed`, it leaves alone the fields that
  person edited (it reads them from the audit log);
- re-derives the branch estimates (`strength = intake×4`, `final_year = intake_2023_24 ?? intake`,
  `eligible = final_year × relevance_factor[category]`) unless a value is marked `verified`;
- **never touches** people, enrollments, targets, activities, follow-ups, calls, courses or the audit log (contacts only
  from the contacts files, keeping user edits; contact status is never imported).

A college with no geo data gets its town from the master `town` text and is pinned at its district HQ, with
`geo_precision='district'` and approximate coordinates.

### Demo data (QA only)
```bash
node server/seed.js --demo        # writes is_demo=1 people/enrollments/activities/follow-ups/targets + a course for 6 colleges
node server/seed.js --clear-demo  # removes every is_demo=1 row
```
While any demo row exists, the UI shows a red **DEMO DATA** banner (`/api/meta` → `demo: true`).

## Back up the database
The DB runs in WAL mode. Make backups while the server is stopped, or use SQLite's online backup:
```bash
# server stopped: copy the file (plus -wal/-shm if present)
cp data/techdrona.db backups/techdrona-$(date +%F).db
# server running (Node 24 has node:sqlite built in):
node -e "const {DatabaseSync}=require('node:sqlite');new DatabaseSync('data/techdrona.db').exec(\"VACUUM INTO 'backups/techdrona-backup.db'\")"
```
To restore, stop the server and replace `data/techdrona.db` (and delete any stale `-wal`/`-shm` files).

## Self-test
```bash
node server/selftest.js   # npm run selftest
```
The self-test copies the live DB to a temp directory and sets `TODAY=2026-11-03`. It then seeds the copy, adds demo
data, exercises every endpoint and prints a PASS/FAIL list. It never modifies `data/techdrona.db`.

## API overview
All responses are JSON. Errors come back as `{error}`, and validation errors as `400 {error, fields:{field: message}}`.
Writes need the header `X-User: <URL-encoded name>`, or the server returns `401`. Every create, update and delete
writes an `audit_log` row with before/after JSON.

Scopes look like `state`, `district:<id>`, `city:<district>--<slug>`, `college:c<sno>`, `branch:<id>` or `person:<id>`.

| Method & path | Purpose |
|---|---|
| `GET /api/meta` | districts, cities, courses, settings, counts, `demo` flag |
| `GET /api/summary?scope=` | full rollup: counts, strength/eligible with basis, people, target/enrolled/remaining/pct, pace, diagnosis, follow-ups, exam states, by-course |
| `GET /api/colleges?district=&city=&q=&op_status=&targeted=&exam_state=&amb=gap\|ok&progress=behind\|on_track\|no_target&branch_code=` | college rows for lists and map pins |
| `GET /api/colleges/:id` | college, rollup, branches (each with rollup + people), people, exams, follow-ups, recent activity/enrollments, last 20 audit rows |
| `GET /api/branches/:id` | branch, rollup, people, follow-ups, activities, enrollments |
| `GET /api/people?role=&college=&district=&q=&status=` / `GET /api/people/:id` | people with targets, progress and team totals |
| `GET /api/search?q=` | districts, towns, colleges, branches and people |
| `GET /api/leaderboard?level=district\|city\|college\|branch\|person&scope=&limit=` | ranked progress |
| `GET /api/attention?scope=` | what needs action: behind pace, ambassador gaps, overdue follow-ups, no lead, exams soon |
| `GET /api/followups?status=&due=overdue\|today\|week\|fortnight&scope=&owner=` | follow-ups (`fortnight` = due within 14 days) |
| `GET /api/branches?college=&relevant=&intake_basis=&category=&district=&q=` | branch list with college name |
| `GET /api/targets/unreconciled` | explicit targets whose children's targets don't add up to them |
| `GET /api/exams?district=&state=` | exam state, next exam and `outreach_from` per college |
| `GET /api/timeseries?scope=&days=60` | daily enrolled/reached, plus cumulative totals |
| `GET /api/quality` | missing-data counts and basis counts |
| `GET /api/audit?entity=&entity_id=&actor=&action=&from=&to=&limit=&offset=` | audit trail, newest first, pageable |
| `POST/PATCH/DELETE /api/{colleges,branches,people,courses,targets,enrollments,activities,followups,exams}[/:id]` | writes (`PATCH people` accepts `branch_ids[]`; `POST targets` upserts) |
| `GET/PATCH /api/settings` | settings (`{key: value, ...}`) |
| `PATCH /api/districts/:id` | toggle `targeted` |
| `POST /api/targets/allocate` | split a total across the next level (largest remainder, so the sum always equals the total). `dry_run` defaults to true |
| `GET/POST/PATCH/DELETE /api/contacts[/:id]` | college contacts; phones normalised to `+91` + 10 digits; a duplicate phone/email in one college → `409` with `existing_id` |
| `GET/POST /api/calls`, `PATCH` (notes) / `DELETE /api/calls/:id` | call log; logging a call updates the contact status, closes earlier call-backs, creates a follow-up when `next_action_at` is set, and can record college participation |
| `GET /api/calls/queue?filter=&sort=&district=&q=` | prioritised calling queue with call status, best contact, last outcome, next action and the priority "why" breakdown |
| `GET /api/funnel?scope=` | students per funnel stage (lead → interested → registered → applied → confirmed, + dropped) |
| `GET /api/target-dashboard?scope=` | target, confirmed, remaining, required vs current pace, projected completion, funnel, contacts, calls, call-backs, top people |

### Calling system and enrollment funnel
- **Only confirmed enrollments count** toward targets, pace, revenue and leaderboards. Each enrollment row is one
  student record at one stage; moving the stage updates the same row, so nothing is counted twice. Rows that existed
  before the funnel are `confirmed`.
- **Contact status** comes from calls: someone answered → working; wrong / invalid number → invalid; disconnected or
  `unreachable_after_attempts` (setting, default 6) unanswered attempts in a row → not working.
- **College call status** is derived: not called → tried, no answer → call-back due → contacted → interested →
  participation confirmed → students enrolled.
- **Priority** (0–100, calling queue only): student potential 40 + contact reliability 20 + outreach window 15 +
  tier/NAAC 10 + engagement 15. The formula and the meaning of each part are in CONTRACT.md.
- **Projection** = today + remaining ÷ (confirmed in the last 14 days ÷ 14). With no confirmed enrollment in the last
  14 days there is no projection, and the dashboard says why.
- The UI: `#/calls` (queue + Log call), the **Contacts & calls** tab on each college, the **Road to {target}** block on
  the overview, a stage on every enrollment, and Calling status / Contacts filters on the college list.

### Rollup rules, in brief
- A scope's **target** is its own explicit target. Without one, it is the sum of its children's targets
  (state → district → city → college → branch). Each rollup also returns `target_source`, `children_target_sum`
  and `reconciled`.
- `remaining = max(target − enrolled, 0)`. **Pace** runs from when the target was set to its deadline: the scope's
  own deadline, else its parent's, else `state_target_deadline`. A scope is on track if it has
  `enrolled ≥ 0.8 × expected_now`.
- When a scope is behind pace, the **diagnosis** is the first of these that applies: `ambassador_gap`, `low_outreach`,
  `low_conversion`, `unrealistic_target`, `behind_pace`.
- **Exam state** is `in_exams`, `exams_soon` (within 14 days), `clear` or `unknown`. It comes from the end-sem dates
  plus any date ranges in `mid_window` text. Exam date fields may hold free text such as "before 2026-12-09 (inferred)".
  Only strict `YYYY-MM-DD` values create a window, and free text counts as an unknown window.
- The **state target** is stored as `scope_type='state'`, `scope_id='ap'`.

### Caching
The server caches rollups in memory. A write through the API clears the cache immediately. Changes from any other
process (re-running `seed.js`, the sqlite3 CLI) are detected on the next request through `PRAGMA data_version`, so you
don't need to restart the server after a reseed.

## Running inside the Tech Drona LMS

The portal is part of the Tech Drona LMS stack: it runs as its own container (`Dockerfile`: `node:24-slim`, non-root,
port 4173, database in the `/data` volume) on the LMS's internal network, and the LMS (Next.js) serves it at
**`/college-portal/`**. LMS admins open it from the admin dashboard (`/admin/college-data`), where the page
`/college-portal/index.html` is shown in a same-origin iframe.

```
browser ──> LMS (Next.js)  /admin/college-data  (iframe: /college-portal/index.html)
              └─ /college-portal/<path> ──proxy (admin session checked, prefix stripped)──> http://college-portal:4173/<path>
                                                                                            └─ node server/server.js ─ SQLite /data/techdrona.db
```

**Proxy mode** is on when `PORTAL_PROXY_SECRET` is set (at least 32 characters; the server refuses to start with a shorter one):

- Every request must carry `x-td-proxy-secret: <secret>` (compared in constant time), otherwise
  `401 {code: 'proxy_required'}`. Only `GET/HEAD /api/health` is open, for container health checks.
- Sign-in comes from the LMS (single sign-on): the proxy sends `x-td-proxy-user` (URL-encoded name) and
  `x-td-proxy-role` (`editor` or `viewer`; anything else is `viewer`). No passcode screen is shown and every change is
  written to the audit log under the LMS user's name. `GET /api/session` answers `{authenticated: true, sso: true, ...}`;
  `POST /api/session` answers `409 {code: 'sso'}`. When the LMS session ends, the page sends the top window to the LMS login.
- The Host allow-list and the same-origin check on writes are skipped for verified proxy requests (the LMS checks the
  origin itself; Host is the internal name such as `college-portal:4173`). The JSON content-type check stays.
- Framing is allowed for the same origin only (`X-Frame-Options: SAMEORIGIN`, CSP `frame-ancestors 'self'`).
  Standalone keeps `DENY` / `'none'`.
- The frontend uses page-relative URLs (`api/...` against `document.baseURI`), so the same files work at `/` and
  under `/college-portal/` (the page must be loaded with the trailing slash or as `/college-portal/index.html`).

| Var (container) | Value | Meaning |
|---|---|---|
| `PORTAL_PROXY_SECRET` | shared with the LMS | Turns on proxy mode (see above) |
| `TRUST_PROXY` | `1` | Trust `X-Forwarded-*` from the LMS proxy (client address for logs/lockout, https for cookies) |
| `DB_PATH` | `/data/techdrona.db` | The database in the volume (copy a migrated `data/techdrona.db` there before first start) |
| `HOST` / `PORT` | `0.0.0.0` / `4173` | Internal network only; never publish the port on the host |

Analytics comes from the LMS's own Firebase project in the parent page. The old standalone deployment (Firebase Hosting +
Cloud Run + Litestream, Firebase project `techdrona-colleges-data`) is **retired**; its deploy files were removed.

**Standalone** use is unchanged: `npm start` serves the portal at `http://localhost:4173` with its own passcode sign-in
(optional) and `data/techdrona.db`.

Tests: `npm run selftest` (standalone, every endpoint), `npm run test:live` (official-source parsers, no network),
`npm run test:proxy` (proxy mode). All run on a temporary copy of the database.

## Official-source data (server/live.js): fetched automatically when someone opens the site

The research (3–9 Nov 2026) was a one-time snapshot. The server now re-reads the **same official sources** on its own:

| Source | What it gives | Re-checked |
|---|---|---|
| AP EAPCET counselling list (api.cap.apcfss.in, JSON) | colleges in counselling, branches, seats, seats left over, fees, office phone/email/website, affiliation | every 6 h |
| AP ECET counselling list (same API) | lateral-entry colleges, branches, seats | every 6 h |
| JNTUK affiliated colleges (jntuk.edu.in/examinations) | affiliated colleges per district + autonomous list, college code, courses | every 24 h |
| JNTUK notifications (jntuk.edu.in/notifications) | circulars sorted into exams, results, academic calendar, holidays, admissions, other | every 30 min |
| College websites | up / down | every 24 h |

- **When:** the app calls `GET /api/live?refresh=1` when it opens. Every source older than its re-check time is fetched
  in the background, and the page updates when the fetch finishes. A source is never fetched more often than that, so
  sources are not hammered.
- **Where it is stored:** the tables `live_sources`, `live_snapshots`, `live_announcements`, `live_web` and
  `live_changes` live in the same SQLite database. They are backed up with the database.
- **If a source is down or changes its page layout:** the last good copy is kept and shown as
  "Source unreachable — showing last successful copy from <time>". A source that failed is retried after 15 minutes.
- **Our records are never overwritten.** Each college page shows "Official live data": its listing in each source, its
  branches and seats, and any differences from our record. Each difference has a "Use official value" button for
  editors. A college that is missing from every list is flagged and never closed automatically.
- **Matching colleges:** colleges are matched to source rows by the EAPCET codes found during research. Otherwise they
  are matched by name only when the match is unambiguous (district, town and website checks; pharmacy and women's
  colleges are kept apart). If the match is unclear, the college is left unlinked rather than guessed.
- **Still manual (no live feed exists):**
  - placements and actual student strength, which come from yearly NIRF and AICTE PDFs (both sites block automated
    requests);
  - TPO contacts;
  - per-college exam dates, which sit inside timetable PDFs;
  - college-specific holidays and announcements.
- Tests: `npm run test:live` (no network; fixtures copied from the real pages).
