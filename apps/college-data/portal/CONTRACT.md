# Tech Drona Outreach Portal — shared build contract

Every agent works from this file. **Only edit files you own** (see the ownership table). If you need a change in
another agent's file or in this contract, say so in your final report; don't make the change yourself.

## Stack (fixed)
- Node 24, **zero npm runtime dependencies**. Server: `node:http` plus `node:sqlite` (`DatabaseSync`). There is no build step.
- Frontend: vanilla ES modules, served statically from `portal/public/`. Third-party libraries are vendored into
  `public/vendor/` so the portal works offline: only Leaflet 1.9.4 (owned by the map agent). Charts are hand-written SVG.
- Start: `cd portal && node server/server.js` → http://localhost:4173. Seed: `node server/seed.js` (idempotent).
- DB file: `portal/data/techdrona.db`.

## Data principles (non-negotiable)
- No fabricated data. People, enrollments, targets, follow-ups and courses start **empty**. Only the team creates them.
  There is no demo or mock data in the app. (If needed, a `seed-demo` flag exists only for local QA, writes rows with
  `is_demo=1`, and the UI shows a red "DEMO DATA" banner whenever any such row exists.)
- Every numeric fact about a college or branch carries a **basis**: `verified` | `estimated` | `pending`. The UI always
  shows it (`ui.provenance(basis)`). Unknown values are `null` and render as "—, pending" and never as 0.
- Every write goes to `audit_log` (actor, timestamp, entity, before/after JSON).

## Folder layout and ownership
| Path | Owner |
|---|---|
| `CONTRACT.md`, `public/js/api.js`, `public/js/ui/h.js` | orchestrator |
| `server/**`, `package.json`, `README.md` | Backend agent |
| `data/seed/branches.json` | Data agent: Branches |
| `data/seed/geo_a.json` (S.No 1–61) | Data agent: Geo A |
| `data/seed/geo_b.json` (S.No 62–170) | Data agent: Geo B |
| `data/seed/master_colleges.json`, `data/seed/exams.json` | orchestrator (already exists) |
| `public/index.html`, `public/css/tokens.css`, `public/css/base.css`, `public/css/components.css`, `public/css/shell.css`, `public/js/app.js`, `public/js/state.js`, `public/js/ui/components.js`, `public/assets/**` | UI shell agent |
| `public/js/map/**`, `public/css/map.css`, `public/vendor/leaflet/**`, `public/data/ap_districts.geojson` | Map agent |
| `public/js/views/dashboard.js`, `public/js/views/geo.js`, `public/js/ui/charts.js`, `public/css/views-dashboard.css` | Dashboard agent |
| `public/js/views/college.js`, `public/js/views/branch.js`, `public/js/views/people.js`, `public/js/views/forms.js`, `public/css/views-college.css` | College & Team agent |
| `public/js/views/followups.js`, `public/js/views/exams.js`, `public/js/views/targets.js`, `public/js/views/admin.js`, `public/css/views-ops.css` | Ops agent |
| `server/calls.js`, `public/js/views/calls.js`, `public/css/views-calls.css` | Calling system (v2); also touched additively: server.js, rollup.js, db.js, seed.js, schema.sql, selftest.js, forms.js, college.js, branch.js, dashboard.js, app.js, index.html |

## Database schema (Backend agent implements it in `server/schema.sql`; other agents rely on these names)
```
settings(key TEXT PK, value TEXT)            -- JSON values. Keys: state_target_deadline, relevance_factors,
                                             --   interest_rate, min_conversion, org_name, unreachable_after_attempts,
                                             --   target_district_groups, program_target, program_deadline (v3, see below)
districts(id TEXT PK, name, old_district, hq_lat, hq_lng, targeted INT DEFAULT 0)
cities(id TEXT PK, district_id, name, lat, lng)
colleges(id TEXT PK, sno INT UNIQUE, name, short_name, aliases JSON, district_id, city_id, address,
  lat REAL, lng REAL, geo_precision TEXT CHECK(exact|town|district|pending), geo_source,
  website, phone, email, contact_source,
  ownership, autonomous, affiliation, naac, nirf, tier,
  op_status TEXT CHECK(operational|possibly_closed|closed|pending), op_status_note, op_status_source,
  op_2025_26 TEXT, op_2026_27 TEXT,          -- 'yes'|'no'|'unknown' each, plus evidence in op_status_note
  targeted INT DEFAULT 0, notes, is_demo INT DEFAULT 0, updated_at, updated_by)
branches(id INTEGER PK, college_id, code, name,
  category TEXT CHECK(it_core|it_allied|circuit|core|other),
  is_relevant INT,                           -- 1 for it_core, it_allied and circuit by default; editable
  intake_per_year INT, intake_basis, intake_source, intake_year,
  strength_total INT, strength_basis,        -- estimated = intake*4 when unknown
  final_year INT, final_year_basis,          -- students who complete 4-1 (2023 batch), estimate = intake
  eligible_estimate INT, eligible_basis,     -- final_year * relevance_factor[category]
  notes, is_demo INT DEFAULT 0, updated_at, updated_by)
courses(id INTEGER PK, name, price_inr INT, active INT DEFAULT 1, notes)
people(id INTEGER PK, college_id, role TEXT CHECK(college_lead|ambassador_lead|ambassador),
  full_name, phone, email, reports_to INT NULL REFERENCES people(id),
  status TEXT CHECK(active|onboarding|inactive) DEFAULT 'active', joined_on, notes, is_demo, updated_at, updated_by)
person_branches(person_id, branch_id, PRIMARY KEY(person_id, branch_id))   -- a lead may cover several branches
targets(id INTEGER PK, scope_type TEXT CHECK(state|district|city|college|branch|person), scope_id TEXT,
  course_id INT NULL, target INT, deadline TEXT, notes, updated_at, updated_by,
  UNIQUE(scope_type, scope_id, course_id))   -- course_id NULL = all courses
enrollments(id INTEGER PK, college_id, branch_id NULL, course_id NULL, person_id NULL,  -- credited ambassador
  student_name NULL, student_contact NULL, enrolled_on TEXT, amount_inr INT NULL, notes, is_demo, created_at, created_by)
activities(id INTEGER PK, college_id, branch_id NULL, person_id NULL, on_date TEXT,
  type TEXT CHECK(visit|call|session|whatsapp|followup|other), students_reached INT DEFAULT 0, notes, is_demo, created_at, created_by)
followups(id INTEGER PK, scope_type TEXT CHECK(college|branch|person), scope_id TEXT, owner_person_id NULL, owner_name,
  due_date TEXT, status TEXT CHECK(open|done) DEFAULT 'open',
  issue TEXT CHECK(ambassador_gap|low_outreach|low_conversion|unrealistic_target|exams|data|other),
  title, notes, last_contact TEXT, created_at, created_by, done_at)
exams(id INTEGER PK, college_id, semester TEXT CHECK('3-1'|'4-1'), exam_body, status, endsem_start, endsem_end,
  mid_window, lab_window, evidence, confidence, source_url, notice_date, verified_on, notes, updated_at, updated_by)
audit_log(id INTEGER PK, at TEXT, actor, action TEXT CHECK(create|update|delete), entity, entity_id, before JSON, after JSON)
```
**District ids (fixed; the GeoJSON `properties.id`, geo seed `district_id` and DB must all use these):**
srikakulam, vizianagaram, parvathipuram-manyam, alluri-sitharama-raju, visakhapatnam, anakapalli, kakinada,
east-godavari, konaseema, eluru, west-godavari, ntr, krishna, palnadu, guntur, bapatla, prakasam, nellore, kurnool,
nandyal, anantapur, sri-sathya-sai, kadapa, annamayya, tirupati, chittoor.
If a district created after 2022 exists as of Nov 2026 (verify), add a slug in the same style and report it.
Display names: "Dr. B.R. Ambedkar Konaseema", "Sri Potti Sriramulu Nellore", "YSR Kadapa", "NTR", etc.

IDs: districts and cities use slugs (`ntr`, `guntur/tenali` → city id `guntur--tenali`). College ids are `c<sno>`, e.g. `c9`.

## Rollup semantics (computed in `server/rollup.js`; the UI never recomputes them)
- `enrolled` = count of **confirmed** enrollments (`stage = 'confirmed'`) in scope; leads, interested, registered, applied and
  dropped records never count (see "Enrollment funnel" below). Revenue, pace, leaderboards and timeseries use confirmed only. `reached` = sum of activities.students_reached.
- `target` for a scope = an explicit `targets` row (course_id NULL) if present, else the sum of the children's effective targets
  (state → districts → cities → colleges → branches). Return `target_source: 'explicit'|'sum_of_children'|'none'`, plus
  `children_target_sum` and `reconciled: bool` (explicit == sum, or no children have targets).
- A person's target comes only from an explicit `targets` row (scope person). A lead's team view also returns
  `team_target`, the sum of its reports' targets.
- `remaining = max(target - enrolled, 0)`. `pct = target ? enrolled/target : null`.
- Pace: `deadline` = the scope's target deadline, else the parent's, else settings.state_target_deadline.
  `expected_now = target * elapsed/total` (from the target's updated_at to the deadline).
  `on_track = enrolled >= 0.8*expected_now`.
- Diagnosis (when not on track), in this order:
  1. `ambassador_gap`: any relevant branch has 0 active ambassadors.
  2. `low_outreach`: reached < 3*target*elapsed_frac.
  3. `low_conversion`: enrolled/reached < settings.min_conversion (default 0.05).
  4. `unrealistic_target`: target > 0.5 * eligible_estimate.
  5. otherwise `behind_pace`.
- Exam state per college, using today's date: `in_exams` if today falls in any end-sem window or a parsed mid window for 3-1 or 4-1;
  `exams_soon` if an exam starts within 14 days; `clear`; or `unknown` if both semesters are Unverified / No Current Exams Found.
  Also return `next_exam {semester, kind, start, end}` and `outreach_from`, the day after the last known 4-1 end-sem
  (4-1 completion matters most for targeting).

## REST API (JSON; writes need header `X-User: <name>`; optional env PORTAL_PASSCODE → header `X-Passcode`)
```
GET  /api/meta                         {districts[], cities[], courses[], settings{}, counts{}, demo:bool}
     (districts= scope filter, /api/program, /api/plan: see "District scope, program target and target planner (v3)")
GET  /api/summary?scope=state|district:<id>|city:<id>|college:<id>|branch:<id>
     -> {scope, label, colleges, targeted_colleges, operational_colleges, cities, districts, branches,
         branches_relevant, branches_with_ambassadors, branches_needing_ambassadors,
         strength:{value,basis}, relevant_students:{value,basis}, final_year:{value,basis}, eligible:{value,basis},
         college_leads, colleges_with_lead, ambassador_leads, ambassadors,
         target, target_source, reconciled, children_target_sum, enrolled, reached, remaining, pct, deadline,
         on_track, diagnosis, followups_open, followups_overdue,
         exams:{in_exams, exams_soon, clear, unknown}, by_course:[{course_id,name,price_inr,target,enrolled,revenue_inr}]}
GET  /api/colleges?district=&city=&q=&op_status=&targeted=&exam_state=&amb=(gap|ok)&progress=(behind|on_track|no_target)&branch_code=
     &diagnosis=(ambassador_gap|low_outreach|low_conversion|unrealistic_target|behind_pace)[,…]   (unknown value -> 400)
     -> [{id,sno,name,short_name,district_id,city_id,lat,lng,geo_precision,op_status,targeted,tier,autonomous,
          branches,strength:{value,basis},eligible:{value,basis},college_lead,ambassador_leads,ambassadors,
          branches_needing_ambassadors,target,enrolled,remaining,pct,on_track,diagnosis,exam_state,next_exam,
          followups_open,next_followup}]
GET  /api/colleges/:id                 {college, rollup(=summary), branches:[{...branch, rollup, people[]}], people[],
                                        exams[], followups[], recent_activities[], recent_enrollments[], audit[] (last 20)}
GET  /api/branches/:id                 {branch, rollup, people[], followups[], activities[], enrollments[]}
GET  /api/people?role=&college=&district=&q=&status=   -> [{...person, college_name, branches[], reports_to_name,
                                        reports[], target, reached, enrolled, remaining, pct, on_track, next_followup}]
GET  /api/people/:id                   {person, college, branches[], reports[], rollup, activities[], enrollments[], followups[]}
GET  /api/search?q=&limit=20           [{type:'district'|'city'|'college'|'branch'|'person', id, label, sub, href}]
                                        Matching (also used by q= on colleges/branches/people lists) ignores case, accents and
                                        punctuation ("K.L."="kl", "vignans"="Vignan's", "aids"="AI-DS"); several words match when
                                        each starts a word anywhere in the record ("engineering guntur", "cse vignan"). Colleges match
                                        on name, short name, aliases and exact sno/id (no longer substring of sno); /api/colleges?q=
                                        also matches town and district names, /api/search does so for multi-word queries; old
                                        district names find the new district (sub "District · formerly part of …"). Phone digits match
                                        only for digit queries of 4+ digits.
GET  /api/leaderboard?level=district|city|college|branch|person&scope=...&limit=  -> rows with target/enrolled/pct
GET  /api/attention?scope=             [{type,id,label,href,reasons[],diagnosis,severity}]  (behind pace, ambassador gaps,
                                        overdue follow-ups, no lead appointed, exams soon). Reasons are display sentences
                                        ("9 Nov 2026", en-IN numbers). While NO active college lead exists anywhere, the per-college
                                        "No college lead appointed" reasons are replaced by ONE item {type:'group', id:'no_college_leads',
                                        label, href:'#/people', reasons[1], severity:'low', count}; likewise while no active
                                        ambassador exists: {type:'group', id:'no_ambassadors', diagnosis:'ambassador_gap', count,
                                        branches}. Per-college reasons return once the first lead / ambassador is added.
GET  /api/followups?status=(open|done)&due=(overdue|today|week|fortnight)&scope=&owner=   (fortnight = open, due within 14 days)
GET  /api/branches?college=&relevant=(1|0)&intake_basis=&category=&district=&q=   [{...branch, college_name, college_short_name,
                                        district_id, active_ambassadors, href}]
GET  /api/targets/unreconciled?course= [{scope_type, scope_id, label, href, target, children_target_sum, difference, course_id}]
                                        (explicit targets whose children's targets don't sum to them)
GET  /api/exams?district=&state=       [{college_id,name,district_id,exam_state,next_exam,outreach_from,rows:[exam]}]
GET  /api/timeseries?scope=&days=60    [{date, enrolled, reached}]
GET  /api/quality                      {missing:[{field,count,college_ids[]}], basis_counts:{verified,estimated,pending}}
GET  /api/audit?entity=&entity_id=&actor=&action=&from=&to=&limit=100&offset=0   newest first; from/to are inclusive
                                        YYYY-MM-DD dates; offset pages through older entries (limit max 1000)
POST|PATCH|DELETE /api/{colleges|branches|people|courses|targets|enrollments|activities|followups|exams|settings}[/:id]
     PATCH people accepts branch_ids[]; POST targets upserts on (scope_type,scope_id,course_id).
     The state target is stored with scope_type 'state' and scope_id 'ap' (scope_id may be omitted for state; any value is
     normalised to 'ap'). Summary scope 'state' reads it.
     exams.endsem_start/endsem_end/notice_date/verified_on accept free text (e.g. "before 2026-12-09 (inferred)"); only strict
     YYYY-MM-DD values create exam windows, so free text counts as an unknown window.
POST /api/targets/allocate {parent_type:'state'|'district'|'city'|'college'|'branch', parent_id, course_id|null, total,
     method:'eligible'|'strength'|'equal', only_targeted:true, deadline, dry_run:true}
     -> {rows:[{scope_type, scope_id, label, basis_value, proposed}], sum, total}  (largest-remainder rounding, so sum == total;
     child level: state→district→city→college→relevant branches→ambassadors (branch→people with role ambassador)). With dry_run:false it writes
     targets and returns the same rows. One audit entry per written row.
     Validation errors -> 400 {error, fields{}}; returns the saved row. fields maps each bad field to a short message for
     inline display; error repeats them in one sentence ("Please fix 2 fields — Full name: required; Phone: …") for toasts.
     A blank (null or "") value for a required column: on create the default is used when one exists (branch category ->
     other, activity on_date -> today, students_reached -> 0), otherwise and on PATCH -> 400 fields{col:'Required'} (never 500).
     404 errors name the record ("Follow-up 12 not found"). Duplicate branch code -> 409 {error, fields:{code}}.
     Re-saving identical values (PATCH, POST targets, PATCH districts) is a no-op: no audit row, updated_at unchanged.
     DELETE refuses (409, with a plain-language hint) when it would silently cascade or blank linked records: a course with
     enrollments or course targets (mark it inactive), a branch with enrollments/activities, a person with credited
     enrollments/activities (set status inactive), a college with branches/people/enrollments/activities/exam rows, or any
     college/branch/person that still has targets. Deleting a person clears reports_to on their reports (audited).
```

## Calling system, enrollment funnel and target dashboard (v2, additive)
Code: `server/calls.js` (status, priority, queue, dashboard), routes in `server/server.js`, view `public/js/views/calls.js`,
shared modals in `forms.js` (`addContact, editContact, logCall, editEnrollment`), CSS `public/css/views-calls.css`.

**Schema** (`schema.sql` + `db.js` COLUMN_MIGRATIONS; both run on every start/seed, so an existing DB upgrades in place):
```
contacts(id PK, college_id FK, branch_id NULL, name NULL, role CHECK(tpo|principal|hod|office|admissions|dean|other),
  phone ('+91'+10 digits, normalised), email (lower-case), source_url, basis CHECK(verified|pending), notes,
  status CHECK(untested|working|non_working|invalid) DEFAULT untested, status_source (calls|manual|NULL), is_demo, created_*, updated_*,
  CHECK(phone or email); UNIQUE(college_id, phone), UNIQUE(college_id, email))
calls(id PK, contact_id NULL FK, college_id FK, branch_id NULL, called_at (ISO date or date-time), caller (= X-User),
  outcome CHECK(connected_interested|connected_callback|connected_not_interested|connected_info_only|no_answer|busy|
  switched_off|not_reachable|wrong_number|invalid_number|disconnected), notes, next_action_at DATE NULL,
  followup_id NULL FK followups, confirms_participation INT, is_demo, created_*)
enrollments + stage CHECK(lead|interested|registered|applied|confirmed|dropped) NOT NULL DEFAULT 'confirmed',
  interested_on, registered_on, applied_on, confirmed_on, dropped_on (first date each stage was reached; lead date = enrolled_on),
  student_contact_norm, updated_at, updated_by
colleges + participation_confirmed_on DATE NULL, participation_note
settings + unreachable_after_attempts (default 6; 0 = never)
```
Every row that existed before v2 is `stage='confirmed'` (that is what every enrollment meant), so no existing number changes.

**Phones**: `normPhone` (db.js) strips punctuation, `+91`/`0091`/trunk `0`, and ignores text after `ext`/`x`/`,`/`;`/`/`.
Valid = 10 digits not starting with 0 (mobiles and STD landlines). Anything else is a 400 field error.

**Contact status** (stored, recomputed from calls): a connected_* call → `working`; wrong_number/invalid_number → `invalid`;
disconnected → `non_working`; `unreachable_after_attempts` unanswered attempts in a row (no_answer/busy/switched_off/
not_reachable, none connected since) → `non_working`. Fewer unanswered attempts change nothing (stays untested/working).
A user may set the status by hand (`status_source='manual'`); deleting a call recomputes unless it was set by hand.

**Logging a call** (`POST /api/calls`, one transaction, everything audited): inserts the call; closes (done) earlier open
call-backs created by calls to the same contact (or the college, when no contact); if `next_action_at` is set, creates a
college follow-up `Call back <who> (<outcome>)` owned by the caller and links it (`followup_id`); applies the contact status
rule; if `confirms_participation` (connected calls only) and the college has no `participation_confirmed_on`, sets it to the
call date (a college update in the audit log). Calls are not edited except `notes`; delete and re-log instead.

**College call status** (derived, never typed), first match wins:
`enrolled` (≥1 confirmed enrollment) → `participation_confirmed` (colleges.participation_confirmed_on set) → `interested`
(last connected call = connected_interested) → `follow_up_due` (an open call-back due today or earlier) → `contacted` (any
connected call) → `attempted_no_answer` (calls, none connected) → `not_called`.

**Enrollment funnel**: lead → interested → registered → applied → confirmed (+ dropped/refunded). One row per student record;
moving a stage PATCHes the same row (never a copy), so stage counts never double count. A second record with the same
normalised mobile (or email) and course → 409 `{fields:{student_contact}, existing_id}`. Only `confirmed` counts toward targets.

**Internal priority (0–100)** — shown only in the calling queue (and `/api/colleges?priority=` as a filter), never as a
highlight in the college list. Real fields only; the "why" breakdown is returned with every queue row:
| Part | Points | Rule |
|---|---|---|
| Student potential | 0–40 | `40 × min(1, eligible ÷ 1000)`; eligible = the college's relevance-weighted final-year estimate (**estimated** from intake unless verified); unknown → 0 and "pending" |
| Contact reliability | 0–20 | working + verified 20 · working 15 · untested verified 10 · untested pending 6 · none / only bad numbers 0 |
| Outreach window | 0–15 | exam_state clear 15 · unknown 8 · exams_soon 5 · in_exams 0 |
| College standing | 0–10 | max(tier: Tier 1 10 / Tier 2 7 / Tier 3 4, first NAAC grade in the text: A++ 10 … C 2); NAAC text from listings is flagged unverified |
| Engagement so far | 0–15 | enrolled / participation confirmed / interested 15 · call-back due 12 · asked to call back 10 · took info 6 · not called 5 · no answer 3 · not interested 0 |
Tier: high ≥ 60, medium 40–59, low < 40. Only operational colleges are queued; `include_closed=1` adds possibly-closed, pending and closed ones.

**Target dashboard** (`GET /api/target-dashboard?scope=`): target / target_source / deadline from the rollup; `confirmed`,
`remaining = max(target − confirmed, 0)`, `pct`; `days_left` = days to the deadline **including today**; `required_daily =
remaining ÷ days_left`, `required_weekly = remaining ÷ (days_left ÷ 7)`; `confirmed_last_14d` (by confirmed_on), `current_daily
= that ÷ 14`, `current_weekly`; `projection.date = today + ceil(remaining ÷ current_daily)` with `status`
on_or_before_deadline | after_deadline | achieved | no_target | no_recent_pace (date null + plain `explanation` when there is
no target or no confirmed enrollment in the last 14 days). Plus `funnel`, `contacts{total,working,non_working,invalid,untested,
colleges_with_working,colleges_without_contact}`, `calls{today,last_7d,total,colleges_called}`, `pending_calls{callbacks_due,
callbacks_scheduled,never_called}` (never_called = operational colleges with no logged call, the default queue's population), `colleges_by_call_status`, `followups_due` (open, due ≤ today), `people[]` (top 10 leads /
ambassadors by confirmed, with target and in-pipeline count).

**API** (writes need X-User like every other write; errors use the usual `{error, fields}`, 409s add `existing_id`):
```
GET  /api/contacts?college=&district=&status=&role=&basis=&q=   rows + college_label, calls_total, last_call, unanswered_streak
GET  /api/contacts/:id                 {contact, calls[]}
POST|PATCH|DELETE /api/contacts[/:id]  duplicate phone/email in the same college -> 409 {fields:{phone|email}, existing_id};
                                       DELETE refuses (409) when calls exist ("mark it non-working or invalid instead")
GET  /api/calls?college=&contact=&caller=&outcome=&from=&to=&limit=   newest first, with contact/college names, follow-up state
GET  /api/calls/:id ; POST /api/calls ; PATCH /api/calls/:id (notes only) ; DELETE /api/calls/:id
GET  /api/calls/queue?filter=all|working|high|pending|invalid|interested|confirmed&sort=priority|next_action|last_call|name
     &district=&city=&q=&targeted=1&include_closed=1&call_status=&limit=
     -> {filter, sort, total, counts{per filter}, rows:[{college_id, name, short_name, district_name, city_name, op_status,
        exam_state, call_status, contact_counts, best_contact, last_call, next_action, calls_total, calls_today, calls_7d,
        enrolled_confirmed, participation_confirmed_on, priority{score, tier, parts[{key,label,points,max,detail,basis?,estimated?}]}}]}
     filters: working = has a working number; high = priority tier high; pending = not called / no answer / call-back due;
     invalid = has a non-working or invalid number; interested = contacted or interested; confirmed = participation
     confirmed or enrolled
GET  /api/funnel?scope=                {stages:[{stage,label,count,counts_toward_target}], total, active, confirmed, dropped, note}
GET  /api/target-dashboard?scope=      see above
GET  /api/colleges also accepts call_status=<status>[,…], contact=working|non_working|untested|none[,…], priority=high|medium|low
     (unknown value -> 400) and its rows gain call_status + contact_counts (priority is not returned in list rows).
GET  /api/colleges/:id gains contacts[], calls[] (last 100), call_info, funnel. /api/summary gains funnel{stage counts}.
GET  /api/enrollments?stage= ; POST/PATCH /api/enrollments accept stage and the stage dates.
```

**Contacts import** (`node server/seed.js` also reads `data/seed/contacts.json` and every `data/seed/contacts_*.json`, if present;
never invented here). Each file is an array of rows:
`{college_id: "c94" | 94 (S.No) , role, name, phone, email, source_url, basis: "verified"|"pending", notes, website?, branch_code?}`
— other fields (`college_name`, `confidence`, …) are ignored, `college_sno` works too. Rules: unknown college or no valid
phone/email → skipped and logged; a field listing several numbers ("0866-2469679 / +91 7013293572") becomes one contact per
valid number (email and the text "as listed" stay on the first); a later row with a number/email already imported in the
same run is a duplicate (first kept); matched to existing contacts by (college, phone) then (college, email); a contact last
edited by a user keeps the fields that user changed (audit-based, like colleges); status is never imported; `website` fills
the college's website only when it has none. Re-running is a no-op.

## District scope, program target and target planner (v3, additive)
Code: `server/server.js` (routes, `programOut`, `patchProgram`, `planOut`), `server/rollup.js` (`withDistricts`), `server/calls.js`
(`targetDashboard(ctx, sc, program)`), importer `server/import_research.js`. Every endpoint behaves exactly as before when the new
`districts` param is absent.

**District model.** The DB uses present-day districts. The program's three target districts are the OLD undivided ones, stored in
`settings.target_district_groups` = `{"Guntur":["guntur","palnadu","bapatla"],"Krishna":["krishna","ntr"],"West Godavari":["west-godavari","eluru"]}`
→ default selection = these 7 ids. Note: `polavaram` (formed 2025 from Eluru/ASR; 2 colleges, both out of research scope) and
`east-godavari` (research college c154, targeted, formerly West Godavari) are NOT in the default groups.

**Schema (schema.sql, CREATE TABLE IF NOT EXISTS — created on every start/seed):**
```
settings + target_district_groups (JSON object group -> [district ids]), program_target (int), program_deadline ('YYYY-MM-DD')
  -- inserted once with defaults; program_target/program_deadline start from the explicit state target row (targets state:ap,
  -- all courses) when it exists. Not writable through /api/settings (unknown setting -> 400); use PATCH /api/program.
college_plan(college_id FK colleges, research_version, research_id ('c36'|'new-ANRG'), in_plan INT, status_final, targeted INT
  (research decision, NOT colleges.targeted), hold_reason, priority_score, rank, p_level, target_min/avg/max, ambassadors,
  college_leads REAL (0.5 = shared lead), payload JSON (research half of PlanCollege), raw JSON (the CSV row), source_file,
  imported_at, imported_by, PRIMARY KEY(college_id, research_version))
college_plan_branches(id PK, college_id FK, research_version, seq, name, is_it, intake_latest, intake_latest_year,
  intake_latest_basis, intake_2023_24, basis CHECK(verified|estimated|unavailable), confidence, source, notes, counted INT,
  final_decision, UNIQUE(college_id, research_version, seq))
```
Plan tables are read-only for the API; only the importer writes them.

**Research import** — `node server/import_research.js [--dry-run] [--csv-dir <dir>] [--db <file>]` (DB_PATH works too; default
csv dir `../research_notes/Krishna Guntur West Godavari colleges 2`). Reads `master_colleges_v2.csv` (130 rows) +
`master_branches_v2.csv` (682 rows) with an RFC-4180 parser. Idempotent: a version's rows are replaced as a whole; an
unchanged CSV prints `0 insert, 0 update, 130 unchanged` and writes nothing. `--dry-run` prints the diff only. Counts (v2):
122 in plan (84 targeted, 38 not targeted with status_final + hold_reason) + 8 excluded (`in_plan=0`: 5 duplicate_merged,
3 out_of_scope; status_final/duplicate_of kept, no numbers); 672 branch rows (656 counted). Targeted totals: min 377 / avg 655 /
max 1,143, 299 ambassadors, 64 college leads. It never changes existing colleges/branches/contacts. The one research college
missing from the DB and verified active — ANR CET Gudivada (`new-ANRG`) — is inserted once as `c<max sno + 1>` (c171 on the
current data): op_status operational, op_2025_26/op_2026_27 yes, targeted 1, district krishna, city krishna--gudivada (town-centre
location, geo_precision 'town'), aliases include `new-ANRG`, notes cite the evidence; plus its 4 branches (intake verified from the
AICTE LoA, strength pending) and its 3 official contacts; all audited as actor `import_research`. Its plan row is not targeted,
hold_reason "No final-year batch until 2028-29 …".
Provenance rules: a value is kept only with a basis; `{value:null, basis:'unavailable'}` otherwise. fy_pool/it_fy/it_3rd/it_2nd
take the CSV basis columns (fy_pool_basis, it_fy_pool_basis, T_S_basis); total_students/total_intake are `verified` (official
source URL) or `unavailable`; branch intake_2023_24 uses final_year_basis; branch intake_latest is `estimated` when the research
says derived/estimated/DB/CAP÷0.8/undated, else `verified` with a source URL. `source` = first URL in the research's cited fields,
`note`/`definition` = the research's method text (some verified figures cite a named document without a URL).

**API**
```
districts=<id>[,<id>…] | all     accepted by GET /api/summary, /api/colleges, /api/calls/queue, /api/target-dashboard, /api/funnel,
                                  /api/leaderboard, /api/attention, /api/followups, /api/exams, /api/timeseries, /api/people,
                                  /api/branches, /api/contacts, /api/calls, /api/plan.
     Keeps colleges whose district_id is in the list (and branches/people/contacts/calls/follow-ups/enrollments of those colleges).
     `all` (alone or in the list) = no filter; blank = absent. Unknown id -> 400 {fields:{districts}}. Combines with the
     existing district=/city=/scope= filters (intersection). Rollups (summary, funnel, timeseries, leaderboard, attention,
     target-dashboard) are computed for the filtered set: enrolled/confirmed/reached/funnel/contacts/calls count only selected
     districts; a sum_of_children state target sums only the selected districts (an explicit state target stays explicit);
     leaderboard level=district lists only selected districts. summary gains `districts_filter` ([ids] | null) and a label
     like "Guntur, NTR" or "7 selected districts"; calls/queue gains `districts_filter`.
GET  /api/target-dashboard?scope=state&districts=…   when districts is present (ids or all) the response gains
     program:{target, deadline, target_source:'state_target'|'settings', selected_districts[], all_districts, is_default_selection,
     confirmed, remaining, pct}; for scope=state, target/deadline/remaining/required_* use the program target
     (target_source:'program') and confirmed counts only the selection. Without districts= nothing changes (no program key).
GET  /api/program  -> {target, deadline, target_source:'state_target'|'settings', state_target_id, target_district_groups,
     target_district_ids[7], default_district_ids[7], note, districts:[{id, name, old_district, group|null, is_target, targeted,
     colleges_total, colleges_operational, colleges_targeted, plan_colleges, plan_targeted}]}   (target = the explicit state
     target row when present, else settings.program_target)
PATCH /api/program {target?, deadline?, target_district_groups?}  (X-User required) -> the GET shape. target: whole number 1..10,00,000;
     deadline: YYYY-MM-DD; groups: object of name (1-60 chars, ≤12 groups) -> non-empty list of known district ids, a district in at
     most one group; unknown keys -> 400. Writes settings (one audit row per changed key) AND upserts the state target row
     (audited as a target update, so its updated_at = pace start moves). Same values = no-op, no audit. A state target written via
     POST /api/targets or PATCH /api/targets/:id also updates settings.program_target/program_deadline.
GET  /api/plan[?districts=…][&version=]  -> {generated_at, research_version:'v2 2026-11-07', imported:bool, source_report, source_files[],
     program:{target, deadline, target_source}, districts_filter, defaults:{…research model assumptions, see below…},
     colleges:[PlanCollege] (in_plan rows; targeted first, by research rank), excluded:[{college_id, name, district_id, status_final,
     final_decision, duplicate_of, hold_reason, …}], colleges_without_research:[{college_id, name, district_id, op_status,
     portal_targeted}] (DB colleges in the selection — or the 7 default ids when unfiltered — with no research row),
     totals_research:{colleges, targeted, min, avg, max, ambassadors, college_leads} (targeted rows in the filter),
     totals_actual:{college_leads, ambassador_leads, ambassadors, active_ambassadors, confirmed, calls, leads_by_stage{}}}
     When nothing is imported: imported:false, colleges:[], message.
     PlanCollege = {college_id, name, short_name, district_id, district_name, target_group (old-district group | null), city, city_id,
       website, op_status, portal_targeted (colleges.targeted), lat, lng, geo_precision,
       research_id, research_name, research_district_id, old_district_group, research_city, cluster, status_final, final_decision,
       status_detail, status_evidence, status_evidence_url, duplicate_of, in_plan, targeted (bool, research), hold_reason|null,
       ownership, affiliation, autonomous, it_branches[], it_branch_count, all_branches[],
       total_students:{value,basis,year,source}, total_intake:{value,basis,year,source}, fy_pool:{value,basis,source,definition},
       it_fy:{value,basis,source,note} (= F), it_3rd:{value,basis,note} (= T), it_2nd:{value,basis,note} (= S), fill_risk_flag,
       conflict_resolution, strength_confidence, access_x, type (a|b|c|d), priority_score, score_parts{pool,contact,digital,exam,
       fill_quality,tier_naac}, rank, p_level (P1|P2|P3|Hold), research_target:{min,avg,max}, buffered_min, standby, rag_400,
       mou:{min,avg,max}, ambassadors_research, college_leads_research (1 | 0.5 | 0), lead_assignment, lead_offer, placement_tier,
       verify_flag, exam_4_1_end (YYYY-MM-DD | null), exam_4_1_note, exam_4_1_source, exam_3_1_end, exam_3_1_note,
       contact:{name, role, phone, email, source, verified(bool)}, social{instagram, linkedin, facebook_or_youtube},
       student_communities, outreach_opportunities, notes, db_discrepancies, change_note_v2,
       actual:{college_leads, ambassador_leads, ambassadors (not inactive), active_ambassadors (status active), leads_by_stage:{lead,
         interested, registered, applied, confirmed, dropped}, confirmed, calls, last_call_at, people:[{id, full_name, role, status,
         reports_to}]}   (live, from people / enrollments / calls; hierarchy = reports_to: ambassador -> ambassador_lead | college_lead),
       branches:[{name, is_it, intake_2023_24, intake_latest, intake_latest_year, intake_latest_basis, basis, source, confidence,
         counted, final_decision, notes}]}
     basis ∈ verified | estimated | unavailable everywhere in /api/plan (unavailable ⇔ value null). Not-targeted rows keep their
     numbers as researched (0/null) and always carry hold_reason.
     defaults (reproduce the research exactly): formula text; year_groups {final_year, third_year, second_year: true};
     rates {final_year [0.0075,0.0125,0.02], third_year [0.00375,0.00625,0.01], second_year [0.0015,0.0025,0.005]};
     year_weight {final_year 1, third_year 0.5, second_year 0.5}; type_multiplier {a [0.8,1,1.2], b [1,1,1], c [0.8,0.9,1], d [0.9,1,1.1]};
     access_x {tpo_contact 1, other_contact 0.8, no_contact 0.6}; min_floor {value 2, access_x_at_least 0.8}; buffer_on_min 1.2;
     paid_per_active_ambassador 5; active_share 0.5; paid_per_recruited_ambassador 2.5; min_ambassadors_per_college 3;
     standby_ratio 0.25; per_ambassador_targets {3, 5, 15}; college_lead {own_lead_min_ambassadors 4, max_ambassadors_per_lead 7,
     ambassador_leads_when_over_capacity 2, shared_lead_pair_size 2, district_coordinator_per_college_leads 6, rule}; mou_coverage
     [0.3,0.5,0.8]; rag_400; priority_levels; program_target.
```


## v4 — team rules, targets & performance, verification, auth (API/data; backend owns this section)
Code: `server/server.js`, `server/rollup.js` (`performance`, `periodOf`, `perfStatus`, `subtreeOf`, `assignmentOf`), `server/db.js` (migrations),
`server/selftest.js` (scenario tests). **Everything below is additive: every v1–v3 endpoint and response field keeps working.**
Where v4 adds an envelope or new semantics it is opt-in (query param / new endpoint) unless it is a validation rule (rules apply to every write).

### v4 business rules (server-enforced; UI explains)
- **R1 roles**: `college_lead` (max ONE not-inactive per college), `ambassador_lead`, `ambassador`. "Active" below = status `active` or `onboarding`.
- **R2 reports_to**: ambassador → an active `college_lead` or `ambassador_lead` of the SAME college; ambassador_lead → the active `college_lead`
  of the same college; college_lead → null. `null` (unassigned) is always allowed for ambassadors / ambassador leads. Self, cycles,
  other-college, inactive or wrong-role managers → **400** `fields.reports_to`. Making someone `college_lead` silently clears an *inherited*
  reports_to; sending a non-null reports_to with role college_lead is a 400.
- **R1 one lead**: a 2nd active college_lead at a college → **409** `{code:'lead_exists', existing_id, existing_name, fields:{role}}` → UI offers
  "Replace lead" (`POST /api/people/:id/replace-lead`).
- **R3 assignment_status** (people rows, computed): ambassador / ambassador_lead → `assigned` | `unassigned` (reports_to null) |
  `invalid_link` (manager missing, inactive, other college, or not a valid manager role); `assignment_issue`: null | `no_lead` | `lead_missing` |
  `lead_inactive` | `lead_other_college` | `lead_wrong_role`. college_lead → `assignment_status: null`.
- **R4 move**: changing `college_id` (PATCH or `POST /api/people/:id/move`) clears reports_to (unless a valid new one for the new college is sent),
  removes person_branches of the old college (unless `branch_ids` for the new college are sent), and unassigns the person's direct reports.
- **R5 side effects**: any PATCH that makes a person's direct reports' links invalid (deactivate, move, role change) sets those reports'
  `reports_to = null` in the same transaction (one audit row each). PATCH/move/replace-lead responses carry
  `side_effects:{unassigned:[ids], removed_branches:[branch ids], reassigned:[ids], cleared_reports_to:bool}`.
- **R6 duplicates** (v4.1: people phones are mobile-only, see "v4.1 fixes"): people `phone` is stored normalised `+91XXXXXXXXXX` (same rule as contacts: 10-digit mobile or STD landline; anything else
  → 400 "Enter a 10-digit Indian number"); `email` lower-cased. Another active person with the same phone or email anywhere →
  **409** `{code:'duplicate_person', existing_id, existing_name, existing_college_id, college, fields:{phone|email}}`. Same (case/space-insensitive)
  name at the same college → **409** `{code:'possible_duplicate_name', existing_id, existing_name}` unless the body has `allow_same_name:true`.
  Reactivating a person re-checks duplicates.
- **Idempotency** (all POST/PATCH/PUT/DELETE): optional header `Idempotency-Key: <≤100 chars, e.g. a UUID per form open>`. The same key from the
  same actor for the same method+path within 10 minutes returns the FIRST response (status + body) again with header `Idempotent-Replay: true`;
  the same key on a different method/path → 409 `{code:'idempotency_key_reused'}`. **Superseded by v4.1: 2xx only, body in the fingerprint, reuse → 422.**
- **R7 validation (every write)**: text is trimmed and whitespace-only counts as blank (required → 400 `Required`); dates must be real calendar
  dates (`2026-02-31` → 400); booleans accept only true/false/1/0/"true"/"false"/"yes"/"no"; link/source fields (`website`, `source_url`,
  `*_source`, `geo_source`, `intake_source`) reject any scheme other than http/https (`javascript:`, `data:`… → 400); college `phone` must
  contain valid Indian numbers (several allowed, separated by `/ , ;`), college `email` valid; `joined_on` not in the future; `limit` params are
  clamped to 1..max (negative = default); bad %-encoding in a path → 400; body > 1 MB → 413. Constraint errors return plain messages (no table names).
- **R8 enrollment credit**: `person_id` must belong to the enrollment's `college_id` (400 `fields.person_id`). Stage dates cannot be after today
  (IST) and cannot be before `enrolled_on`. `student_contact` must be a valid Indian mobile or an email (400 otherwise). A record WITHOUT contact
  whose student_name + college + enrolled_on match an existing one → 409 `{code:'possible_duplicate', existing_id}` unless `force:true`.
- **R9 achievement** = enrollments with `stage='confirmed'` and `COALESCE(confirmed_on, enrolled_on) <= today` (server date, Asia/Kolkata, or env
  TODAY). Applies to every rollup (`enrolled`), the leaderboard, plan, target dashboard and `/api/performance`. Person **own** = credited to them;
  **team** = all non-inactive people below them (recursive, cycle-safe); **combined** = own + team (always returned separately).
- **R10 targets**: each row has `target` (required, ≥0), optional `target_min` (≤ target) and `target_max` (≥ target), and a period:
  `programme` (default; all existing rows) | `month` (period_start = 1st of month) | `week` (period_start = ISO Monday).
  `remaining = max(target − actual, 0)`, `exceeded_by = max(actual − target, 0)`, `pct = round(actual/target×100, 1)` (null when target is 0 or null).
  **Performance `status`**: `no_target` | `zero_target` | `exceeded` | `met` | `too_early` (< 7 days into the period, or period not started) |
  `behind` (actual < 0.8 × expected) | `on_track`. (Elapsed days count today, = period.days_elapsed: 1 on the first day. "Too early" while days_elapsed < 7, or < a quarter of a shorter period: < 2 for a week.) `expected = target × days_elapsed / days_total` (days_elapsed inclusive of today), counted from the PERIOD START
  (programme start = `settings.program_start`, default 2026-11-03) — never from when the target was saved. Badges: `below_min`, `above_max` (bool).
  Programme-period actuals have no lower date bound (everything confirmed up to today counts toward the programme).
  A rolled-up target (`target_source:'sum_of_children'`) is compared only with the actual of the children that HAVE a target
  (`actual_against_target`, `covers:{with_target,total}`).
- **R11 programme target protected**: `POST/PUT /api/targets` on scope `state` (programme period) needs `confirm_programme:true`, else 409
  `{code:'programme_target_protected'}`; the normal path is `PATCH /api/program`. `/api/targets/unreconciled` never lists the state target and
  only lists a target when EVERY child has a target.
- **R12 data provenance**: X-User / session names `seed`, `import`, `import_research`, `system`, `demo` (any case) are reserved → 400.
  The research importer matches by `colleges.research_id` / `college_plan.research_id` before name/website (never inserts a duplicate
  college after an admin rename). `seed.js` never overwrites a row last edited by a person. College `sno` is read-only after create.
- **R13 verification**: `colleges.verified_fields` JSON `{field:{source, verified_on, verified_by, note?}}`. A college field changed through the API
  WITHOUT a source becomes unverified (its entry is removed); with a source (`sources:{field:'https://…'}` in the same PATCH) it is stamped
  verified. Contacts: `basis:'verified'` stamps `verified_by` + `verified_on` (cleared when basis goes back to pending). Branch numbers typed
  without a basis become `estimated` (verified only when the request also sets the basis to verified or gives an http(s) `intake_source`).
- **R14 security**: see "Auth" below. **R15 deletes**: college / branch / person deletes are refused (409) while follow-ups point at them
  (and colleges while research plan rows exist); deleting a person unassigns their reports (audited).

### v4 schema changes (migrations in `server/db.js`, safe on the live DB: ADD COLUMN / copy-rebuild, no data loss)
```
targets          + target_min INT NULL, target_max INT NULL, period TEXT NOT NULL DEFAULT 'programme' CHECK (programme|month|week),
                   period_start TEXT NULL ('YYYY-MM-01' | Monday date | NULL for programme). Unique per
                   (scope_type, scope_id, IFNULL(course_id,0), period, IFNULL(period_start,'')). Table rebuilt once (rows copied as programme).
colleges         + verified_fields TEXT (JSON object), research_id TEXT (importer key, e.g. 'new-ANRG'; backfilled from college_plan)
contacts         + verified_by TEXT, verified_on TEXT
people           phone normalised to +91XXXXXXXXXX where possible (unparseable legacy values kept as typed); email lower-cased
                 + designation TEXT NULL (≤120), responsibility TEXT NULL (≤500): trimmed; blank = null; accepted on POST/PATCH /api/people,
                   returned on every people row (list + detail), audited like every field
settings         + program_start ('2026-11-03') — editable via PATCH /api/program {start}
```

### v4 API (exact; frontend codes against this)
```
GET    /api/session            200 always (also signed out): {required, auth_required (same value), authenticated, role:'editor'|'viewer'|null, user, expires_at, viewer_enabled}
POST   /api/session {name, passcode?}   -> {role, user, expires_at} + cookie td_session (HttpOnly; SameSite=Strict; Path=/; 12 h)
                                400 name missing/reserved · 401 {code:'bad_passcode'} · 429 {code:'locked', retry_after_s} (5 failures / IP / 10 min)
                                Without PORTAL_PASSCODE the passcode is ignored and role = editor (the session just remembers the name).
DELETE /api/session            -> {ok:true}, clears the cookie
GET    /api/health             {ok, today, version:'v4', auth_required}  (never needs auth)
  Auth: with env PORTAL_PASSCODE set, EVERY other /api call needs the session cookie (or the legacy X-Passcode header) → else
  401 {code:'auth_required'}. Env PORTAL_VIEWER_PASSCODE → role viewer: GETs only, writes → 403 {code:'read_only'}. Writes: actor =
  session user, else X-User (missing → 401 {code:'user_required'}). Without PORTAL_PASSCODE nothing changes (no login needed).
  Server binds 127.0.0.1 unless HOST is set; a non-loopback HOST refuses to start without PORTAL_PASSCODE. Optional PORTAL_ALLOWED_HOSTS
  (comma list) → other Host headers get 403 (v4.1: the allow-list is always on, see "v4.1 fixes"). HTML responses carry CSP (self + Google Fonts + OSM/Carto tiles; NO inline scripts except by sha256 hash computed from the served file,
  PORTAL_CSP=off disables), all responses X-Content-Type-Options nosniff, X-Frame-Options DENY, Referrer-Policy strict-origin-when-cross-origin (OSM tiles need a Referer; only the origin is sent cross-site).
  500s say only "Internal server error".

GET  /api/people  + college_id (alias college) · role · status · reports_to=<id>|none · assignment=assigned|unassigned|invalid_link[,…]
                  (assignment filter excludes inactive people unless status= is given) · district · districts · branch · q
                  · sort=name|college|role|status|joined_on|actual|pct|assignment (prefix '-' = descending)
                  · page, page_size (default 50, max 200).  WITHOUT page/page_size → the v1 plain array (unchanged);
                  WITH either → {items, total, page, page_size, counts:{assigned, unassigned, invalid_link, college_lead, ambassador_lead, ambassador}}
     every item adds: college{id,name,short_name,district_id}|null, lead{id,name,role,status}|null (= the reports_to person),
       assignment_status, assignment_issue, phone_norm, links{tel, whatsapp, mailto}, team_size (non-inactive people below),
       actual_own, actual_team, actual_combined, target_summary{min,target,max,remaining,exceeded_by,pct,status} (programme, own)
POST /api/people                    R1–R7 enforced; returns the person row (+ assignment fields)
PATCH /api/people/:id               R1–R7; returns the person row PLUS {person:<row>, side_effects:{unassigned[], removed_branches[], cleared_reports_to}}
POST /api/people/:id/move {college_id, reports_to?, branch_ids?}   -> {person, side_effects}   (R4)
POST /api/people/:id/replace-lead {new_lead_id, old_lead_becomes:'ambassador_lead'|'inactive', move_reports?:true}
     :id = the current college_lead; new_lead_id = a non-inactive person of the same college (any role). In one transaction: old lead →
     ambassador_lead reporting to the new lead (or inactive); new lead → college_lead, active, reports_to null; old lead's direct reports →
     the new lead (unless move_reports:false and the old lead stays as ambassador_lead).
     -> {old_lead, new_lead, side_effects:{reassigned[], unassigned[]}}
POST /api/people/bulk-assign {person_ids:[…], reports_to:<id>|null}  all-or-nothing R2 check -> {updated:[ids], unchanged:[ids]}
     Deactivate = PATCH {status:'inactive'} (reports become unassigned, R5).

GET  /api/colleges + team=no_lead|has_lead|no_ambassadors|has_team|has_unassigned · verified=verified|partly|unverified · sort=sno|name|district|
       ambassadors|unassigned|enrolled|pct|target (prefix '-' desc) · page, page_size (envelope {items,total,page,page_size} only when given)
     every row adds: lead{id,name,phone}|null, ambassador_count (non-inactive ambassadors + ambassador leads), unassigned_count
       (non-inactive ambassadors/ambassador leads whose assignment_status ≠ assigned), data_status 'verified'|'partly'|'unverified'
GET  /api/colleges/:id  college adds verified_fields{}, field_status{name,district_id,city_id,phone,email,website,ownership,affiliation,op_status:
       'verified'|'unverified'|'missing'}, data_status; people[] rows carry the v4 people fields
POST /api/colleges {name, district_id, city_id | city_name, sno?, short_name?, …}  sno defaults to max+1, id = 'c'+sno;
       same normalised name in the same district → 409 {code:'duplicate_college', existing_id}
PATCH /api/colleges/:id  name, short_name, aliases, district_id, city_id|city_name, ownership, website, phone, email, affiliation, op_status, … ;
       optional sources:{<field>: '<http(s) url or note>'} → verified_fields; sno → 400 (read-only)
POST /api/colleges/:id/verify {fields:[…], source, note?, verified_on? (YYYY-MM-DD, not future; default today), verified?:true}  stamps (or with
       verified:false clears) verified_fields -> college row (+ verified_fields, field_status, data_status). Audit rows carry the college name.
PATCH /api/contacts/:id {basis:'verified', verified_on?}  stamps verified_by (actor) + verified_on (given date, not future, else today);
       basis 'pending' clears both. Contact rows return verified_by / verified_on.
DELETE /api/colleges/:id  409 while branches/people/enrollments/activities/exams/contacts/calls/follow-ups/plan rows exist (unchanged + R15)

GET  /api/targets?scope=&period=  rows add min, max (aliases of target_min/target_max), period, period_start, period_key
POST|PUT /api/targets {scope_type, scope_id, period?:'programme'|'month:YYYY-MM'|'week:YYYY-MM-DD' (or period:'month'+period_start),
       min?, target, max?, deadline?, notes?, course_id?, confirm_programme?}  upsert on (scope, course, period); 0≤min≤target≤max;
       person targets: no course_id, person not inactive; returns the row (+ min/max/period_key)
GET  /api/performance?level=person|college|district|state & period=programme|month:YYYY-MM|week:YYYY-MM-DD (week = a Monday)
       & districts= & district= & college_id= & role= & include_inactive=1 & only_with_target=1 & sort=pct|-pct|actual|name|remaining
     -> {level, period:{key,type,start,end,label,days_total,days_elapsed,today}, rows:[…], totals:{…},
         programme:{target,deadline,start,actual,remaining,exceeded_by,pct,status}}
     row: {id, name, href, level, role?, person_status?, college:{id,name}|null, district:{id,name}|null, min, target, max, target_source,
           actual (the number compared with target), actual_own, actual_team, actual_combined, actual_against_target, remaining, exceeded_by,
           pct, status, expected, below_min, above_max, covers:{with_target,total} (always on college/district/state rows; null on person rows),
           team:{size,target,actual,remaining,exceeded_by,pct,status}|null, combined:{target,actual,remaining,exceeded_by,pct,status}|null,
           not_credited (college rows: confirmed with no person)}
       person rows compare OWN actual with OWN target; team/combined are separate blocks (team target = Σ targets of team members).
     totals: {rows, with_target, target, actual (Σ row.actual), actual_against_target, remaining, exceeded_by, pct, by_status{status:n}}
GET  /api/audit/actors        [{actor, n, last_at}]
GET  /api/search              towns match only at a word start; person sub adds the lead name and the last 4 phone digits
districts= works on every list/rollup endpoint: colleges, people, branches, contacts, calls, calls/queue, followups, exams, enrollments,
       activities, summary, leaderboard, attention, timeseries, funnel, target-dashboard, performance, plan, quality.
Rollup changes (v4): summary/person rollups add `actual_against_target`, `covers`, `exceeded_by`, `pace_status` (= performance status) and
       pace now starts at settings.program_start; `on_track` is null while `pace_status` is `too_early`. personRollup `team_target` /
       `team_enrolled` now cover the whole non-inactive subtree (was: direct reports) and add `own`, `team`, `combined` blocks.
       target-dashboard projection status `zero_target` for an explicit target of 0 (was 'achieved').
```

## v4.1 fixes (backend; supersedes the v4 lines it names)
Code: `server/server.js`, `server/rollup.js` (`judge`, `teamBlocks`, `programmeDistricts`, `stateRowApplies`), `server/calls.js` (`targetDashboard`),
`server/db.js` (`canonicalScopeId`, `migrateCanonicalV41`). Tests: `server/selftest.js` steps "v4.1 …".
```
STATUS 'partial_target' (new judge status, everywhere a status/pace_status appears)
  A target that does not cover the whole population it is compared with is SHOWN but never JUDGED:
  {target (the sum that exists), actual, covers:{with_target, total, complete}, status:'partial_target', pct:null, remaining:null,
   exceeded_by:null, expected:null}. Only complete coverage gives pct / remaining / exceeded_by / met / behind / on_track / exceeded.
  Rolled-up geo/college targets (target_source 'sum_of_children'): complete = EVERY child has a target (0 counts as a target) and each of
  those children is itself complete. summary adds target_complete (bool|null) and covers.complete; pct/remaining/exceeded_by null when partial.
  A single explicit 0 on one college no longer makes its town/district "zero_target, exceeded by N" (F3): the town/district is partial_target.
  An explicit row is never partial (its covers, when returned, is informational only).
  /api/performance totals: target/actual_against_target/remaining/pct add only judged rows; totals.partial_target = count; by_status includes it.
  progress bucket (colleges ?progress=) adds 'partial_target'. target-dashboard: projection.status 'partial_target', target_status
  'no_target'|'partial_target'|'judged', covers.

TEAM / COMBINED (person rows of /api/performance, personRollup own/team/combined)   (F2, F5, D5)
  own      = own target vs own credited actual (unchanged).
  team     = {size, target: Σ members' targets (null if none), actual: Σ ALL non-inactive members' actual, actual_with_target,
              covers:{with_target, total:size, complete}, …judge}  → judged only when every member has a target, else partial_target.
  combined = {target: own + team target, actual: own + team actual, covers:{with_target (own counts 1), total: size+1, complete}, …judge}
              → judged only when the person AND every member have a target. (A lead with own target 10 and no team targets: combined partial.)
  personRollup legacy team_target / team_enrolled unchanged.

PROGRAMME TARGET SCOPE (D2)
  The programme target (state row, e.g. 400) covers the programme districts = settings.target_district_groups (all districts if none).
  It applies to a state scope only when districts= is absent, 'all', or includes ALL programme districts. Otherwise the state target is
  the roll-up of the selected districts' own targets (or null), and responses carry target_reason
  "The programme target covers the 7 target districts (…); this selection does not include all of them."
  - target-dashboard: program {target:null when not applicable, programme_target (always the 400), applies, target_reason, target_districts,…};
    top level target (selected-district roll-up or null), target_status, covers, target_reason; remaining/pct null when target null/partial.
  - performance: programme {target:null when not applicable, programme_target, target_reason, target_districts, …}; level=state row target
    = selected districts' roll-up (or null) + target_reason.   - summary scope=state&districts=…: target_reason.

PLAN TOTALS (D1)  /api/plan totals_actual = every college in scope (districts= or whole state), INCLUDING colleges outside the research plan:
  {colleges, college_leads, ambassador_leads, ambassadors, active_ambassadors, confirmed, calls, leads_by_stage,
   in_plan:{same keys} (plan colleges listed in colleges[]), outside_plan:{same keys}}. No-research message no longer shows a command.

PEOPLE COUNTS (F4, D9)  GET /api/people?page… counts leave out inactive people unless status= is given; counts.inactive = how many were
  left out. To make a role segment list match its count, send status=active,onboarding with the role filter.

PHONE RULE (F6, one rule; FE mirrors)  normalise: strip everything but digits and '+'; text after ext / x<digit> / , ; / is ignored;
  '+' must be +91; drop 0091 / 91 (12 digits) / trunk 0 (11 digits); result must be 10 digits not starting with 0 → '+91XXXXXXXXXX'.
  people.phone:   MOBILE only  /^\+91[6-9]\d{9}$/   else 400 fields.phone "Enter a 10-digit Indian mobile number, e.g. 98765 43210".
  contacts.phone / college phone:  mobile OR STD landline (any normalised 10-digit number).  student_contact: mobile or email (unchanged).
  (Limitation: a landline whose STD code starts 6-9, e.g. 0863…, normalises like a mobile and is accepted.)

IDEMPOTENCY (F1, SEC-07; replaces the v4 bullet)  Only 2xx results are remembered (10 min, max 5000 keys). Fingerprint = method + path +
  actor + SHA-256 of the JSON body. Same key + same request → first 2xx result again + header Idempotent-Replay: true. Same key + ANY other
  request (body, path, method or actor) → 422 {code:'idempotency_key_reused', error:'Idempotency-Key reused with a different request'}.
  A 4xx is never replayed: after an error the same key may be resent with a corrected body (it runs for real). FE: new key per attempt.

CSRF (SEC-01)  Every POST/PATCH/PUT/DELETE under /api (POST /api/session included):
  - a non-empty body MUST have Content-Type: application/json (charset allowed); any other Content-Type → 415 {code:'json_required'}.
    An empty body without Content-Type is allowed.
  - Origin (when sent) must equal this request's Host (scheme ignored), Origin 'null' refused; Sec-Fetch-Site (when sent) must be
    same-origin or none → else 403 {code:'cross_origin'}.
HOST ALLOW-LIST (F9, SEC-04; replaces the opt-in v4 line)  Always on: Host must be localhost, an IP literal (127.0.0.1, [::1], LAN IPs),
  the HOST env value, or listed in PORTAL_ALLOWED_HOSTS / ALLOWED_HOSTS (comma list, names only; any port) → else 403 {code:'bad_host'}.
DISTRICTS (F8)  Every GET validates districts= and district= when present (also endpoints that do not filter by them): unknown → 400
  fields.districts / fields.district. colleges?op_status= is validated (400 on unknown values).
SCOPE IDS (SEC-03)  follow-ups and targets store canonical scope ids: person/branch "0010" → "10"; college " C9 " → "c9"; district/city
  lower-case. Non-numeric person/branch ids → 400 Unknown <type>. Start-up migration canonicalises existing rows (audited, actor 'system').
  /api/quality integrity adds followups_noncanonical_scope (0 when healthy).
PROTOTYPE NAMES (SEC-05/06)  /api/constructor, /api/__proto__, … → 404; settings keys are an allow-list (own keys only): __proto__,
  hasOwnProperty, … → 400 "Unknown setting". Junk rows with such keys are deleted at start-up and never read.
LIMITS (SEC-08..13)  enrollments.amount_inr and courses.price_inr 0..10,000,000. PATCH /api/program: start must be ≤ deadline (either one
  changing) → 400. Actor names (X-User and session) are NFKC-normalised with invisible characters removed; the reserved check ignores case,
  spaces and punctuation (seed, "ｓｅｅｄ", "S E E D", "seed.", "Import-Research" → 400) and a name needs a letter. full_name: text made of
  invisible characters only is blank (400 Required), a name with no letter → 400, a non-string (true) → 400 "Must be text" (all text fields
  refuse booleans). POST /api/session name must be a string ≤ 80 chars. Cookie gets `Secure` when the request is https (TLS socket or
  X-Forwarded-Proto: https). Sessions capped at 500 (oldest evicted). Start-up warns when a passcode is shorter than 6 characters.
  isLoopback accepts 127.x only as an IP literal.
MESSAGES (D3)  In "Please fix … — Field: message" the first letter of a message is lower-cased only for our own label words (Required,
  Must, Unknown, …), never for a name ("Person: QA Amb Sita Devi belongs to another college …").
```

## Frontend contract
- `public/js/api.js` (orchestrator): `api.get(path, params)`, `api.post/patch/del(path, body)`, `api.user`/`setUser()`.
  It throws `ApiError {status, message, fields}`.
- `public/js/ui/h.js` (orchestrator): `h(tag, attrs, ...children)`, `fmt.num/inr/pct/date/days`, `daysUntil(date)`,
  `debounce`, `qs`.
- `public/js/ui/components.js` (UI shell agent). These signatures are FIXED; each returns an HTMLElement unless noted:
  `provenance(basis)`, `valueWithBasis({value,basis}, fmtFn)`, `badge(text, tone)` with tone
  `neutral|good|warn|bad|info|brand`, `statusBadge(kind, value)` with kind `exam_state|op_status|on_track|followup|person_status|diagnosis`,
  `progress({target, done, size})`, `statCard({label, value, sub, basis, tone, icon, onClick})`,
  `table({columns:[{key,label,render?,align?,sortable?}], rows, onRowClick?, empty?})`, `tabs({tabs:[{id,label,count?,render}], active, onChange})`,
  `modal({title, body, actions:[{label,tone,onClick}]})` → `{close}`, `drawer({title, body, onClose})` → `{close}`,
  `form({fields:[{name,label,type:'text'|'number'|'date'|'select'|'multiselect'|'textarea'|'tel'|'email',options?,required?,value?,help?}], submitLabel, onSubmit(values) -> Promise})`,
  `toast(msg, tone)` (void), `emptyState({title,text,action?})`, `section({title, actions?, body})`, `kv(pairs:[[label, node|string]])`,
  `icon(name)` with names `map, dashboard, college, branch, people, lead, ambassador, target, followup, exam, data, audit, settings, search, filter, plus, edit, trash, phone, mail, link, warn, check, clock, chevron`.
- `public/js/state.js` (UI shell agent): `state.filters` (district, city, op_status, branch_code, amb, progress, exam_state, followup)
  plus `subscribe(fn)`, `setFilter(k,v)`.
- Views export `async function render(el, params, ctx)` and an optional `destroy()`. `ctx = {api, ui, h, fmt, state, navigate(href), map, refresh()}`.
- Router (hash, in app.js):
  | Route | Module.export | Layout |
  |---|---|---|
  | `#/` | dashboard.renderState | explore (map + panel) |
  | `#/d/:district` | geo.renderDistrict | explore |
  | `#/d/:district/:city` | geo.renderCity | explore |
  | `#/college/:id` (`?tab=branches&branch=ID`) | college.render | explore on desktop; full on mobile |
  | `#/colleges` | dashboard.renderCollegeList | full |
  | `#/analytics` | dashboard.renderAnalytics | full |
  | `#/people`, `#/person/:id` | people.renderList / people.renderPerson | full |
  | `#/followups` | followups.render | full |
  | `#/calls` (`?filter=`) | calls.render | full |
  | `#/exams` | exams.render | full |
  | `#/targets` | targets.render | full |
  | `#/data` | admin.renderData | full |
  | `#/audit` | admin.renderAudit | full |
  | `#/settings` | admin.renderSettings | full |
  Branch detail opens as a drawer: `branch.openBranch(branchId, ctx)`.
  Shared forms (`forms.js`) export `editCollege, editBranch, addBranch, addPerson, editPerson, recordEnrollment, logActivity, addFollowup, setTarget(scope_type, scope_id)`. Each opens a modal, saves, then calls `ctx.refresh()`.
- Map (map agent), `public/js/map/map.js`: `createMap(el, {onSelectDistrict(id), onSelectCity(districtId, cityId), onSelectCollege(id)})` →
  `{setColleges(rows /* /api/colleges rows */), focusState(), focusDistrict(id), focusCity(districtId, cityId), focusCollege(id),
  highlight(id|null), invalidateSize(), destroy()}`. Water-drop SVG pins are coloured by progress (no target = neutral,
  behind = bad, on track = good) and get a ring when `exam_state==='in_exams'`. District polygons are shaded by targeted / not
  targeted, and clustered at state zoom. Pins at town or district precision are drawn hollow, with an "approx. location" tooltip.
- Explore layout: the map is on the left at 55% and the panel on the right (desktop ≥1100px). Tablet stacks the map (45vh) over the panel.
  On mobile the map toggles full-screen and the panel is a bottom sheet. The shell owns the layout. Views render only into the panel `el`
  and call `ctx.map.focus*()`.
- CSS: design tokens are custom properties in `tokens.css`: `--td-brand`, `--td-brand-2`, `--td-accent`, `--td-bg`, `--td-surface`,
  `--td-surface-2`, `--td-text`, `--td-muted`, `--td-border`, `--td-good`, `--td-warn`, `--td-bad`, `--td-info`, `--td-radius`,
  `--td-shadow`, `--td-font`, `--td-font-display`, and spacing `--sp-1..8`. Light and dark themes. Component classes are prefixed `td-`.
  View CSS is scoped under `.v-dashboard`, `.v-college`, `.v-ops` etc. Use only tokens, never raw colours.
- Provenance tokens: `--td-verified`, `--td-estimated`, `--td-pending` (each with a `-soft` variant), plus `--td-on-accent` and `--td-demo-*`.
- Logo: the official Tech Drona logo (single colour, navy #032269) lives in `public/assets/brand/`. Each piece comes as `-navy` for light
  surfaces and `-white` for dark ones:
  - `mark-*`: the mark alone, for the nav rail and mobile.
  - `wordmark-*` / `wordmark-tagline-*`: the wordmark, with or without the tagline.
  - `logo-full-*`: the original lockup, about 80 KB, kept for print and large uses.
  - `logo-mark-*`: the mark cropped from the full file.

  The favicon is `assets/favicon.svg` (white mark on navy) plus `apple-touch-icon.png`. The palette is navy with a saffron accent, and
  brand colours live in tokens only.
- Shared UI additions: `ui.pageHeader({title, sub, actions})` for every page title, `ui.chip` for filter pills, `ui.spinner` for loading.
  `modal()` accepts `onClose`, and form fields accept `password`/`url` types.
- Labels use plain language for non-technical users. Numbers use Indian grouping (`fmt.num`). Accessibility: keyboard focus,
  ARIA on tabs/modals/drawers, 44px touch targets on mobile.
