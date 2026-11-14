# College Data portal: clean-up of Home, Targets, Planner and Team

Date: 2026-11-14. Scope: `apps/college-data/portal/public/js/views/{dashboard,targets,plan,people}.js`, `public/js/app.js`
(top bar and sidebar), `public/js/map/map.js` (the shared map's "closed" control text) and `public/css/views-dashboard.css`
(new rules added; existing rules unchanged). No server, schema or data changes.

Why: the owner said Home showed "so many irrelevant columns" and asked to remove them or give them proper names.

## How each item was judged

Each item was traced to its source, using only the schema and the non-personal seed files:

- **Seed data** (170 colleges, branches, exams, geo status: 113 operational, 49 possibly closed, 1 closed, 7 pending)
  fills the college, branch, exam and map items.
- **People, enrollments, follow-ups, person targets and min/max targets** have no seed. They are empty until the team
  types them in. On day one, every card built on them showed 0.
- **Recruitment "needed" numbers** (63 college leads, 296 ambassadors) come from the research planner model
  (`/api/plan`, table `college_plan`). They are model estimates, not records.

Rules applied:

- **Keep:** the item is an essential: target against paid enrollments, the pace needed, the colleges to act on, or the
  follow-ups due.
- **Hide when 0:** the item depends on data the team has not created yet.
- **Remove:** the item duplicates another, or it is a technical detail.

## Decisions

### Top bar and sidebar (`app.js`)

| Item | Source | Decision | New label / why |
|---|---|---|---|
| "Checked 5 h ago" chip | `views/live.js` `liveChip()`: the age of the background re-check of the official EAPCET/ECET/JNTUK lists | **Removed** from the top bar | This is a technical background detail. The background refresh still runs on every visit, and its status stays on More › Official sources. |
| "Target" dropdown (district selector, tablet/phone short label) | `renderScopeControl()` | **Renamed** | The short label read "Target", which looks like the enrollment target. It now shows a count: "3 districts" or "All districts". The tooltip reads "Districts shown on every page: … (the target districts). Click to change." |
| Sidebar links | `NAV` | **Kept**, tooltips and aria labels added | In the collapsed, icon-only sidebar each link now has `aria-label` and a tooltip. Tooltips explain Team ("college leads and ambassadors"), Targets & performance, Reports and Official sources. The phone tab bar links also got `aria-label`. |

### Home (`views/dashboard.js` `renderState`)

| Item | Source | Decision | New label / why |
|---|---|---|---|
| Header "Outreach programme" + "Guntur · Krishna · West Godavari · Change" | `scopePill()` | **Removed** (duplicate) | The same selector is in the top bar on every page. The header now says what Home is for: "Paid enrollments against the target, and what needs doing next." |
| Target 400 | `/api/target-dashboard` `program.target` (targets table, state scope) | **Kept** | The sub-line is now "by <deadline>", replacing "target districts". Tooltip added. |
| Confirmed 0 "paid enrollments" | `T.confirmed` (enrollments, stage confirmed) | **Renamed** | "Paid enrollments". The sub-line is "N% of target", taken from the old Achieved tile. |
| Remaining 400 | `T.remaining` | **Renamed** | "Still needed" ("Above target by" once exceeded). |
| Achieved 0% | `T.pct` | **Removed** (duplicate) | Folded into the Paid enrollments tile. |
| Needed per week 58 (now 0/wk, 48 days left) | `T.required_weekly`, `T.current_weekly`, `T.days_left` | **Renamed** | "Needed each week". The sub-line is "current pace 0 a week · 48 days left incl. today". A tooltip explains that current pace covers the last 14 days. |
| College leads 0 of 63 | `/api/plan` `totals_research` vs people | **Removed from Home** | This is a research-model estimate, not an essential. It is still shown in Reports › Recruitment structure and in the Target planner. Home no longer calls `/api/plan`. |
| Ambassadors 0 of 296 | as above | **Removed from Home** | As above. |
| Needs attention: 89 targeted colleges with no lead | `/api/colleges` rows: targeted + operational + no `college_lead` | **Kept, renamed** | "Colleges without a college lead", "of N colleges we are targeting". A tooltip defines a college lead: the student who runs Tech Drona outreach at one college. These leads are students, not college staff; staff phone contacts are separate (Contacts). |
| 0 unassigned team members | `/api/people?assignment=unassigned,invalid_link` | **Hidden while 0**, renamed | "Ambassadors without a lead". It shows only when above 0, because it stays 0 until people exist. |
| 0 people behind target | `/api/performance?level=person` status `behind` | **Hidden while 0**, renamed | "Team members behind their target". It shows only when above 0, because it needs person targets. |
| 0 overdue follow-ups | `summary.followups_overdue` | **Kept** (essential) | Moved first. Tooltip: "Planned calls or visits whose due date has passed". |
| "All alerts (11)" | `/api/attention` | **Renamed** | "Show every issue, college by college (11)". |
| Map "127 colleges" | `/api/colleges` row count (all statuses) | **Renamed** | The count now matches the pins: "94 colleges in the selected districts · 33 more may have shut down (hidden by default)", with a tooltip that explains the flag. |
| Map control "33 possibly closed hidden" | `map.js` closed control (`op_status` possibly_closed or closed, from geo seed) | **Renamed** | "33 may have shut down (hidden)" or "Showing 33 colleges that may have shut down". The short form is "33 hidden" or "33 shown". |
| Top colleges to call / "priority 87" | `/api/calls/queue` | **Renamed** | "Colleges to call next". "priority 87/100" has a tooltip listing what the score is made of. The link reads "Open the call list". |
| Next 14 days | follow-ups + exams | **Kept** (essential) | The sub-line is now "Follow-ups due and exams coming up". |

### Reports (same file, `renderAnalytics`) and the shared vocabulary

| Item | Decision | New label / why |
|---|---|---|
| Headline and "Road to 400" tiles: Confirmed / Remaining / Exceeded by / Achieved | **Renamed** | "Paid enrollments", "Still needed", "Above target by" and "% of target". These now match Home and Targets. The pipeline stage is still called "confirmed", because that is the stage name in the forms. |

### Targets & performance (`views/targets.js`)

| Item | Source | Decision | New label / why |
|---|---|---|---|
| Status cards (Exceeded, Met, On track, Behind, Too early, No target), always 6 | `/api/performance` row statuses | **Show only the statuses that occur** | Six "0" cards was noise. The cards still add up to the row count, and the Status filter still lists every status. Sub-lines are now plain: "slower than the pace needed" instead of "pace < 80% of expected"; "target set under 7 days ago, not judged yet". |
| Column "Min · Target · Max" | targets `target_min`/`target_max` (empty unless typed) | **Renamed** | "Target". Min and max still show underneath when they are set. |
| Column "Actual" | `actual_own` / team / combined | **Renamed** | "Paid enrollments". |
| Column "Remaining" | `remaining` | **Renamed** | "Still needed", which now shows "+N over" when the target is exceeded. |
| Column "Exceeded by" | `exceeded_by` | **Removed** (duplicate) | Folded into "Still needed". |
| Column "%" | `pct` | **Renamed** | "% of target". |
| Column "Target vs actual" (bar) | same numbers as % | **Removed** (duplicate) | The programme summary bar stays. |
| Lead note "judged three ways, never merged (F5)…" | — | **Rewritten** | A plain explanation of Own, Team and Total, with the internal "F5" code removed. |
| Section "Targets vs confirmed enrollments", sorts "% achieved", "Most enrolled", Places column "Confirmed" | — | **Renamed** | "Targets vs paid enrollments", "% of target, low to high", "Most paid enrollments", "Paid enrollments". |

### Target planner (`views/plan.js`)

| Item | Decision | New label / why |
|---|---|---|
| Header eyebrow "Scope: Guntur · …" | **Removed** (duplicate) | The district selector is in the top bar. |
| Tile "Confirmed so far" | **Renamed** | "Paid so far". |
| District table, 15 columns | **Cut to 11** | These columns were removed: "Share of 400 (min/avg/max)", because the chart above already shows it; "Amb. leads", "Standby" and "District Leads", because they are model internals that stay in "What it takes" and in the assumptions. Renamed: "Open colleges", "IT students", "Planned paid (min/avg/max)", "College leads needed", "Ambassadors needed", "Ambassadors recruited" and "Paid so far", each with a tooltip. |
| College table, 17 columns | **Cut to 11** | Moved into the expanded row, where they were already listed: "3rd yr", "2nd yr", "Avg", "Max", "400 here?" (research rating) and "Lead offer" (a cryptic "(a)" code). Renamed: "Final-year IT students", "Reachable students", "Planned paid" (minimum scenario, explained in a tooltip), "College lead" and "Paid so far". Priority and # columns got tooltips. |
| "400 here?" in the expanded row | **Renamed** | "Research rating (can this college alone reach the goal?)". |

### Team (`views/people.js`)

| Item | Decision | New label / why |
|---|---|---|
| Page sub-line | **Rewritten** | Defines the roles in plain words: a college lead is a student who runs outreach at one college; ambassadors bring in enrollments. |
| Segment "Unassigned" | **Renamed** | "Without a lead", matching the Home card. |
| Column "Lead" | **Renamed** | "Reports to". |
| Column "Target vs actual (programme)" | **Renamed** | "Paid enrollments vs target". Lead rows show "team N · total N", the same words as Targets. |
| Filters "Lead" and "Assignment" (Assigned / No lead / Invalid lead link) | **Renamed** | "Reports to" and "Link to a lead" (Has a lead / No lead / Lead link broken). |

## Behaviour kept

- No API, data or schema changes. Every removed tile or column is still available elsewhere (Reports, the planner's
  expanded rows, or the Status filter).
- Home makes one request fewer (`/api/plan`).
- The official-source refresh still runs.
- Deep links are unchanged: `#/people?seg=unassigned`, `#/targets?level=person&status=behind` and
  `#/colleges?team=no_lead&targeted=1`.

## Tests

- `node --check` passes on every changed file.
- `node --test server/live.test.js server/proxy.test.js` passes 19 of 19.
- No test asserted the changed labels: the Node tests and the LMS Playwright audits (`qa/live-e2e`) only check routes
  and API.
- Not run locally: the browser UI, because the laptop is low on RAM. Check it on the deployed Cloud Run build.

## Follow-up: shared vocabulary from the other agents (same day)

- **Colleges list** (in `dashboard.js`):
  - The calling-status filter is now built from `forms.CALL_STATUS`: "No answer yet", "Spoke to them", "College agreed" and so on, so it matches the badges.
  - "IT branch" became "target branch" in the coverage filter, the list cell and the CSV header, because relevant branches include electronics.
  - The list number (`#sno`) and the verification badge are no longer in the default list rows. Verification is still a filter and a CSV column.
  - P-levels read "Priority P1", "Priority P2" and "On hold".
- **"Eligible students"** became "Likely prospects (est.)" in the sort, the Reports KPI, the facts list, the funnel and the CSV. The target split method is now "By likely prospects".
- **Planner:**
  - "IT branches" got the tooltip "Research count: computer branches only".
  - In the branch table, "Final yr (2023-24)" and "Latest intake" became "Final-year students" and "Seats / year (latest)".
  - "4-1 exams end" became "Final-year exams end".
