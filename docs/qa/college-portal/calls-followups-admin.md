# College Data Portal cleanup: calls, follow-ups, forms and admin

Date: 2026-11-14. Scope: `apps/college-data/portal/public/js/views/{calls,followups,forms,admin}.js` and `server/calls.js`.

What did not change:

- No schema, stored value, API key or query parameter changed. Only the wording people see, and whether an item is shown, changed.
- Every stored key (outcome, call status, contact status, follow-up `issue`, settings keys) is the same, so old rows, links and filters keep working.
- Exports in `forms.js` keep the same names and shapes (`OUTCOMES`, `CALL_STATUS`, `CONTACT_STATUS`, `CONTACT_ROLE_LABEL`, `logCall`, `addContact`, ...). `OUTCOMES[*]` gained an optional `hint` field.

Decisions: **keep** (useful and clear), **rename** (plain, consistent wording), **hide** (noise, duplicate, unused or developer-only; the data is kept).

## Call queue (`#/calls`)

| Item | Decision | New label / why |
|---|---|---|
| Filter `all` "All" | rename | **All colleges** |
| Filter `pending` "To call / call-back" | rename | **To call**: covers not called, no answer and call-back due |
| Filter `high` "High potential" | rename | **High priority**: it is the priority tier, not the "student potential" part |
| Filter `working` "Working numbers" | rename | **Has a working number**: it filters colleges, not numbers |
| Filter `interested` "Interested" | rename | **Spoke to them**: it matches *contacted or interested*, so "Interested" was wrong |
| Filter `confirmed` "Confirmed" | rename | **College agreed**: participation confirmed or students enrolled |
| Filter `invalid` "Bad numbers" | rename | **Has a bad number** |
| KPI Calls today / Call-backs due | keep | |
| KPI "Not called yet" | rename | **Colleges not called yet**, sub "operating colleges only" (the server counts operational colleges only) |
| KPI Working numbers, sub "untested · bad" | rename sub | "N not tried yet · N not working" |
| Column College (+ call status, open/closed, exam badges) | keep | |
| Column "Best number" | rename | **Number to call** |
| Column Last call | keep | |
| Column "Next call" | rename | **Call back on**: it is the call-back follow-up date |
| Column Priority + "Why?" pop-over | keep | Footnote "Internal only: it orders this list" became "It only decides the order of this list". |
| Priority parts (server `calls.js`) | rename | Student potential → **Students**; Contact reliability → **Phone number**; Outreach window → **Exam timing**; College standing → **College rank (tier / NAAC)**; Engagement so far → **Response so far**. Detail texts reworded ("untested" → "not tried yet", "outreach window open" → "a good time to reach students"). The keys (`potential`, `contact`, `exams`, `standing`, `engagement`) did not change. |
| Row actions Log call / Add contact | keep | |
| Empty-state texts | rename | Use the new chip names |

## Shared calling labels (`forms.js`, used by the call queue, college page and colleges list)

| Item (stored key) | Decision | New label / why |
|---|---|---|
| Call status `not_called` "Not called" | rename | **Not called yet** |
| `attempted_no_answer` "Tried, no answer" | rename | **No answer yet** |
| `follow_up_due` | keep | Call-back due |
| `contacted` "Contacted" | rename | **Spoke to them**: "contacted" also reads as "we tried" |
| `interested` | keep | Interested |
| `participation_confirmed` "Participation confirmed" | rename | **College agreed** |
| `enrolled` | keep | Students enrolled |
| Outcome `connected_callback` "Call back later" | rename | **Asked to call back** |
| `connected_info_only` "Took information" | rename | **Took details only** |
| `busy` "Busy" | rename | **Line busy** |
| `wrong_number` "Wrong number" | rename | **Wrong person**: someone answered who is not with this college |
| `invalid_number` "Invalid number" | rename | **Number does not exist** |
| `disconnected` "Disconnected" | rename | **Number out of service** |
| Other outcomes | keep | Each outcome button now has a tooltip saying when to pick it (`hint`) |
| Contact status `untested` "Not called yet" | rename | **Not tried yet** (it is about the number, not the college) |
| `invalid` "Invalid number" | rename | **Wrong number** (set by "wrong person" or "number does not exist") |
| `working` / `non_working` | keep | Working / Not working |
| Contact roles TPO / placement, HOD, Office | rename | **Placement officer (TPO)**, **Head of department**, **College office** |
| Unused `ISSUE_OPTS` list (its labels disagreed with Follow-ups) | hide (removed dead code) | Follow-up reasons have one list: `followups.js` `ISSUES` |

## Log call dialog and contact form (`forms.js`)

| Item | Decision | New label / why |
|---|---|---|
| Who did you call? / What happened? / Notes | keep | |
| "Another / unlisted number" | rename | **A number not listed here** |
| Section "Next call" + chip "None" | rename | **Call back on** + chip **No call-back**; the help now says the call-back is assigned to you |
| "The college confirmed participation" | rename | **The college agreed to take part (only after speaking to someone)** |
| Contact "Where is the number from?" | rename | **Is it verified?** |
| Contact "Source link" | rename | **Where it was found (link)**, with help text |
| Contact "Branch (for a HOD)" | rename | **Branch (for a head of department)** |
| Contact "Number status" help | rename | Explains that a status set by hand stays until changed |

## Follow-ups (`#/followups`)

| Item | Decision | New label / why |
|---|---|---|
| Tabs Overdue / Today / Next 14 days / All open / Done | keep | |
| KPIs | keep | |
| Column Due / Done on, What, About | keep | About sub-label "Person" became **Team member** |
| Column "Issue" | rename | **Reason**. Call-backs created by Log call are stored as `other` with the title "Call back …". They used to show "Other"; they now show **Call-back**. |
| Reason values | rename | Ambassador gap → **No ambassador**; Low outreach → **Few students reached**; Low conversion → **Few enrolling**; Exams → **Exam timing**; Data check → **Fix data**; Other → **General**; Target too high: kept |
| Filter "Issue" | rename | **Reason**, with a new **Call-back** option so the filter matches the badge (view-only; "General" excludes call-backs) |
| Column / filter / field "Owner" | rename | **Assigned to** ("Everyone" → "Anyone", "No owner" → "Not assigned") |
| Column "Last contact" | rename + hide on Done tab | **Last spoke to them**. On the Done tab it equals "Done on", so it is a duplicate there. |
| Form field "Last contacted on" | rename | **Last spoke to them on** (optional) |
| Action "Snooze" (row, bulk, dialog) | rename | **Reschedule**. The note text "Snoozed to" became "Moved to". |
| Mark-done field "Outcome" | rename | **What happened?** |
| "Targeted colleges with nothing scheduled" | keep | |
| DEMO badge | keep | Needed while demo data exists (testing phase) |

## Data quality (`#/data`)

| Item | Decision | New label / why |
|---|---|---|
| Tab "Verification queue" | rename | **To verify** |
| Tab "Gaps & checks" | rename | **Missing or doubtful** |
| Tab "Export" | rename | **Download** |
| KPI "Fully verified" | rename | **Colleges fully verified** |
| KPI "Verified numbers" | rename | **Verified student figures**: these are branch seat and student figures, not phone numbers |
| KPI "Status to confirm" | rename | **Still open? To confirm** |
| Segment "College contacts" / "Needs checking" | rename | **Contact numbers** / **Not verified yet** |
| College queue column "Overall" / "Details" | rename | **Status** / **Details checked**; chip text "unverified" became "not verified" |
| Contact queue column "Status" / "Source" | rename | **Verified?** / **Found at**; the role shows the plain role name; "Not recorded (before v4)" became "Not recorded" |
| Old-server message "needs the v4 update (verified fields per college)" | rename | Plain wording, no version jargon |
| Reliability bars, map locations, still-operating review, missing details | keep | |
| Download: CSVs, full backup, demo-data card | keep | |
| Download: "Research data" card | hide | It had no action, only "ask an admin to re-import on the server" |

## Audit log (`#/audit`)

| Item | Decision | New label / why |
|---|---|---|
| Columns When / Who / What / Record / Changed | keep | |
| Filter "Person" | rename | **Changed by** |
| Filter "Record id" | hide unless set | Ids like `c6` mean nothing to staff. The box shows only when a link opened the log for one record; "Clear filters" removes it. |
| Change details "Show raw data" | hide outside dev | Shown only with `?dev=1` (the same switch as the style guide) |
| Field names in "Changed" and the diff | rename | Added plain labels for the calling and enrollment fields that showed as raw keys, e.g. `confirms_participation` → "College agreed to take part", `followup_id` → "Call-back", `next_action_at` → "Call back on", `called_at` → "Called on", `caller` → "Called by", `outcome` → "What happened", `status_source`, `op_2025_26`, `is_demo`, `students_reached`, the stage dates, the branch figures |

## Settings (`#/settings`)

| Item | Decision | New label / why |
|---|---|---|
| Programme target, deadline, start, target districts | keep | |
| "You & access": your-name box, sign-in status, session end, Sign out, saved team passcode | hide in LMS proxy mode | The LMS signs people in and its name goes into the audit log. In proxy mode the section is **Your account**: signed in as, access, "through Tech Drona LMS". Standalone is unchanged. |
| Read-only warning | rename | "You have view-only access …"; in the LMS it adds "ask an LMS super admin for edit access" |
| Courses & prices | keep | |
| "Organisation name" | hide | Nothing in the portal displays `org_name`. The stored value is kept and still accepted by the API. |
| "Default deadline for other targets" | rename | **Fallback deadline**: used only when a target has no deadline of its own |
| "Minimum conversion (%)" | rename | **Low-conversion alert (%)**; fixed the "enrolll" typo in its help |
| `unreachable_after_attempts` (was not shown) | keep, now shown | **Unanswered calls before a number is "Not working"** (0–50, default 6). It decides when calls mark a number not working, so callers need to see it. It already existed in the server allow-list. |
| Branch relevance | keep | The help now says it also orders the call queue |
| Appearance (theme) | keep | Per device |

## Branch terms (to match the colleges and branches views, `branch.js`)

| Item | Decision | New label / why |
|---|---|---|
| Branch category options (`forms.js`) and Settings → Branch relevance names (`admin.js`) | rename | **Computer science** / **CS-related (AI, data, IoT…)** / **Electronics / electrical** / **Other engineering** / Other, the same text as `branch.js` `CATEGORY_LABEL`. It is copied, not imported, because `branch.js` imports `forms.js`. |
| Branch form "Intake per year (seats)" / "Intake basis" / "Intake source" / "Intake year" | rename | **Seats / year** / **Seats basis** / **Seats source** / **Seats year** |
| Branch form "Relevant for IT courses?" and "(not IT-relevant)" in branch pickers | rename | **Target branch?** / "(not a target branch)" |
| Audit labels `is_relevant`, `intake_*` | rename | **Target branch**, **Seats / year**, **Seats basis / source / year** |

## Tests

- `node --test "server/*.test.js"` (proxy and live-source tests; Node 24 does not accept a bare `server/` folder): 19/19 pass. They run on a temporary copy of the local database.
- No test asserted any label changed here. `selftest.js` checks priority keys and scores, not labels.
- `node --check` passes on every changed file.
- No browser, emulator or LMS run (low RAM).
