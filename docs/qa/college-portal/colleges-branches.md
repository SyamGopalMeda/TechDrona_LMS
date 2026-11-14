# College portal cleanup: colleges, branches, geography, exams, live data

Date: 2026-11-14. Scope: `apps/college-data/portal/public/js/views/{college,college-form,branch,geo,exams,live}.js` and the
source descriptions in `server/live.js`. Display only: no column, row or stored value was dropped or renamed in the
database, and every field stays editable in the forms.

Fill rates come from `server/schema.sql` and the non-personal seed files only (170 master colleges; 128 active rows carry
research fields; 808 branches; 256 exam rows). Contact files and `.db` files were not opened.

## Shared vocabulary (used in every view I own)

| Old term(s) | New term | Why |
|---|---|---|
| "IT branch", "IT target", "Not IT", "Counts toward IT target" | **Target branch** / "Not a target branch" (tooltip lists the groups) | `is_relevant` also covers electronics (`circuit`), so "IT" was wrong |
| Category `IT core` / `IT allied` / `Circuit` / `Core` | Computer science / CS-related (AI, data, IoT…) / Electronics / electrical / Other engineering | Plain names; the codes stay in the DB |
| Intake, Intake / yr, Intake / year | **Seats / year** | 741 of 808 values are counselling seats (EAPCET 2026-27) |
| Strength, Strength (4 yrs) | **Students, all 4 years (est.)** | It is seats × 4, not a head count |
| 4-1 cohort, Completing 4-1 | **Final-year students** | Same number, plain words |
| Eligible, Eligible (est.), Eligible students | **Likely prospects (est.)** | final-years × branch relevance (1 / 0.6 / 0.15); tooltip explains |
| College phone / College email | **Office phone / Office email** | They are office lines, not the TPO |
| Ownership | **Type of institution** (values reworded, e.g. "Pvt autonomous" → "Private college (autonomous)") | Plain words |
| Affiliation | **Affiliated university** | Plain words |
| NAAC / NIRF / tier (one line of long research text) | **NAAC grade** (grade only) + **NIRF ranking (2025)** ("Not ranked" when not in the lists) | The research strings run to 150 characters; full text is on hover and under More details |
| Exam status `No Current Exams Found` / `Unverified` / `In Progress` / `Completed` | No exams announced / Not confirmed / In progress / Finished | Stored values unchanged |
| Exam evidence `Unverified (calendar-planned)` etc. | Academic calendar (planned) / Official notice / University timetable / Sources disagree / Not confirmed | Stored values unchanged |
| EAPCET / ECET | B.Tech counselling (EAPCET 2026) / Lateral-entry counselling (ECET 2026) | Code names kept in brackets |

## College page (`college.js`)

| Item | Fill / source | Decision | New label / why |
|---|---|---|---|
| Header `#<sno>` | 170/170, master list serial | Hide from header | Internal id; now "Master list no." under More details |
| Header P1/P2/P3/Hold badge | research import | Rename | "Priority P1" / "Priority: on hold", with tooltip |
| Header Targeted badge | colleges.targeted | Keep | — |
| Header Operating status | 170/170 | Keep | — |
| Header data_status ("Partly verified") | computed | Move | Provenance; now "Checked against sources" under More details |
| KPI "IT branches covered" | computed | Rename | "Target branches with an ambassador" |
| Other KPIs (lead, ambassadors, confirmed, contacts, exams) | computed | Keep | — |
| Next-step "No contact numbers yet" (printed the office phone) | — | Reword | Points to College information instead of repeating the number |
| Official name | 170/170 | More details | Same as the page title |
| Also known as | aliases ~153/170 | More details (only when set) | Search aid |
| District / City / town | 169/170 | More details | Already in the header and breadcrumb; still verifiable there |
| Phone / Email / Website | ~116 / ~105 / ~105 of 170 | Keep (default) | "Office phone", "Office email", "Website" |
| Address | 128/170 (else town) | Keep (default) | Needed for visits |
| Ownership | 128/128 active | Keep (default) | "Type of institution", values reworded |
| Affiliation | 0/170 from seed (only via "Use official value") | More details, only when set | "Affiliated university"; never shows an empty "Missing" row |
| Autonomy | 128/128 | More details | Mostly duplicates "Type of institution" ("Pvt autonomous") |
| NAAC | 42/128 real values (86 are "—") | Keep (default) | "NAAC grade", grade only; full text on hover + More details |
| NIRF | 126/128, mostly "Not in 2025 Engg top 300" | Keep (default) | "NIRF ranking (2025)": "Not ranked" or "Engineering 201-300" |
| Tier | 128/128 | More details | "Research tier" with tooltip (Tier 1 = strongest) |
| Operating status + evidence link | 170/170 | Keep (default) | — |
| Status evidence (op_status_note) | 170/170 | More details | "Why this status" |
| Admitted students 2025-26 / 2026-27 | 170/170 | More details | "Admitting new students" |
| Total intake / year | 93/170 | Keep when set | "Seats per year (all branches)"; long source text trimmed to its link |
| Map location (geo_precision) | 170/170 | More details | "Map pin": Exact / Approximate (town centre) / … |
| geo_source, contact_source, lat/lng, is_demo | provenance | Not shown (unchanged) | — |
| Notes | research text ("Tier basis: … EAPCET: … NBA: …") | More details | "Research notes" |
| Last updated | audit | More details | — |
| Research plan block | research import | Keep, rename | "Research priority", "Recommended to target", "Expected enrollments", "One lead shared with a nearby college" (was "0.5") |
| Branches tab: card figures (4) | — | 3 figures | Seats / year, Final-year students, Likely prospects (est.). "Students, all 4 years" (= seats × 4) moved to the drawer |
| Branches tab: card "Intake source: … · 2026-27" | 808/808, 741 the same EAPCET API URL | Remove from card | Shown once in the branch drawer as "Seats from" |
| Branches table columns | — | 8 → 6 | Dropped "Strength" (duplicate of seats × 4) and "Source" (same URL on 92% of rows) |
| Branch sort "Most students" | — | Rename | "Most seats" (now sorts by seats, same order) |
| Filter "IT branches only" | — | Rename | "Target branches only" |
| Exams tab: "Evidence: …" + "Confidence: …" badges | 256/256 | Merge | One badge, e.g. "Official notice · high confidence" (raw values on hover) |
| Exams tab: status badge | 256/256 | Rename | Readable status words (table above) |
| Exams tab: Mid / Lab / Notice date rows | 166 / 148 / 180 of 256 | Show only when set | No more rows of "—" |
| Exams tab: "Checked on" | 256/256, all 2026-11-03 | Keep, renamed | "Last checked", moved after Source |
| Exams tab: multi-URL source | some rows hold 2 URLs | Fix | Each URL gets its own link (was one broken link) |
| Contacts tab wording (hard-coded) | calls | Rename | Matches `forms.js`: "participation confirmed" / "Confirmed participation" → "College agreed"; "not working / invalid" → "not working or wrong number"; "Not called yet" → "Not tried yet" |
| Change history field names | audit | Rename | intake_per_year → "seats / year", eligible_estimate → "likely prospects", is_relevant → "target branch", sno → "master list no.", etc. |

## College edit form (`college-form.js`)

| Item | Decision | New label / why |
|---|---|---|
| "S.No 12 (fixed) · id c12" | Rename | "Master list no. 12 (fixed)"; internal id hidden |
| Duplicate warning "· #sno" | Remove | Internal id |
| College phone / email | Rename | Office phone / Office email (+ hint to add TPO numbers under Contacts & calls) |
| Ownership / Affiliation / Autonomy / Tier | Rename | Type of institution / Affiliated university / Autonomous? / Research tier (Tier 1 = strongest) |
| NAAC grade | Keep + help | "The grade first, e.g. A+" |
| Admitted students 2025-26? / 2026-27? | Rename | "Admitting new students in …?" |
| Evidence for the status / Evidence link | Rename | Why this status / Link to the evidence |
| Targeted by Tech Drona | Rename | "… (in the outreach plan)" |
| Verification list labels | Rename | Match the view labels |
| Every field | Kept editable | Behaviour and payloads unchanged |

## Branch drawer (`branch.js`)

| Item | Decision | New label / why |
|---|---|---|
| Category badge | Rename | Plain group names |
| "Counts toward IT target" / "Not an IT branch" | Rename | "Target branch" / "Not a target branch" (tooltip) |
| Four figures | Keep, reorder, rename | Seats / year, Final-year students, Likely prospects (est.), Students, all 4 years (est.); each has a how-it-is-worked-out tooltip |
| "Intake source: <url> · 2026-27" | Rename | "Seats from: <link> (2026-27)"; "unspecified" year hidden |
| progressCell "N enrolled · no target" | Rename | "N confirmed · no target" (only confirmed enrollments count) |
| Follow-up issue "Data" | Rename | "Data check" |
| Research notes | Keep | — |

## District / town pages (`geo.js`)

| Item | Decision | New label / why |
|---|---|---|
| KPI "IT branches uncovered" | Rename | "Target branches without ambassador" |
| KPI "Eligible students" | Rename | "Likely prospects (est.)" |
| KPI "In exams / soon" | Rename | "Exams now or in 14 days" |
| Other KPIs, target block, cities, alerts, map | Keep | — |
| Colleges list | Not mine | `collegeList` lives in dashboard.js (agent 1) |

## Exams page (`exams.js`)

| Item | Decision | New label / why |
|---|---|---|
| Status badge / select options | Rename (display only) | Table above; stored values unchanged |
| "Pending verification" | Rename | "Dates not confirmed" |
| Evidence select | Rename options | Plain labels; the field is "Kind of source" |
| Confidence | Keep, rename field | "How sure are we?" |
| Exam body | Rename | "Exams set by" (+ help: university, or the college if autonomous) |
| End-sem starts / ends | Rename | "End-semester exams start / end" |
| Mid exam window / Lab / practical window | Rename | "Mid exams" / "Labs / practicals" |
| Notice date / Checked on | Rename | "Notice published on" / "Last checked on" |
| Timeline header "lane" | Rename | "Year" |
| State cards, outreach panel, list columns | Keep | Already plain |

## Official data (`live.js`, `server/live.js`)

| Item | Decision | New label / why |
|---|---|---|
| Presence badges "EAPCET 2026" / "ECET 2026" | Rename | "B.Tech counselling (EAPCET 2026)" / "Lateral-entry counselling (ECET 2026)" |
| "Matched by research code (X)" / "Matched by name — check" | Rename | "Linked by college code (X)" / "Linked by name — please check" |
| "Counselling code", "Name in the source" | Rename | "Counselling college code", "Name in this list" |
| Phone / Admission officer / Email | Rename | Office phone / Admissions officer (mobile) / Office email |
| "Feed entry date" | Hide | The feed's own bookkeeping date; says nothing about the college |
| Seats table "Left over", "Course" | Rename | "Still empty", "Programme" |
| Diff "Ours (research)" / "Official (live)" | Rename | "Our record" / "Official list" |
| Sources table "Last successful", "Items" | Rename | "Last good copy", "Records" |
| Coverage KPIs "Linked to EAPCET 2026" … | Rename | "In B.Tech counselling (EAPCET)" … |
| Source descriptions "convener seats, seats left over" (server) | Rename | "counselling (convener-quota) seats, seats still empty" |
| Change summaries ("left over 50 → 40") | Keep | Asserted by `live.test.js` |

## Tests

- `node --test server/live.test.js server/proxy.test.js`: 19/19 pass. (`node --test server/` fails to start on Windows
  because Node treats the folder as a module path; pass the files.)
- No server test asserts on these UI labels. All six view modules import cleanly in Node with DOM stubs. The new display
  helpers were checked against real seed strings: `naacGrade("A+; 3.49; …(College site)")` gives "A+", and
  `nirfText("Not in 2025 Engg top 300")` gives "Not ranked".
- No browser run (low RAM). Check the college page's More details toggle and the branch card's 3-figure row on the live
  site.
