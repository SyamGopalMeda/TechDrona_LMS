# Audit — Backend APIs & business logic (learner-facing modules)

Area key: `backend` · Issue prefix: `BE-` · Phase A (audit only, no source edits) · 2026-11-03

Scope: catalog, learning (progress/completion/certificates/assignments), media (playback/downloads), assessments, coding, analytics (time-on-task tm-1.0), notifications, placement (practice, company paths, question bank), mentoring, support, orgs (colleges/batches).
Auth/sessions/rbac/security engine, commerce/entitlements and admin are out of scope (other agents).

## Baseline

`apps/api`: `TD_TEST_DB_NAME=techdrona_audit_backend_baseline TD_TEST_RESET_DB=1 .venv/Scripts/python -m pytest -q --ignore=tests/_audit_scratch -p no:cacheprovider`
→ **559 passed in 997.73s (0:16:37)**, 0 failed / 0 errors.

## Probes (all in `apps/api/tests/_audit_scratch/backend/`)

| Dir | DB (`TD_TEST_DB_NAME`) | Result |
|---|---|---|
| `learning/test_learning_probes.py` (catalog/learning/media) | `techdrona_audit_backend` | 9 probes: 5 pass, 4 fail (= findings BE-05..BE-08) |
| `assessments_coding/` | `techdrona_audit_backend_ac` | 15 probes: 8 pass, 7 fail (= findings) |
| `analytics/test_probe_analytics.py` (analytics + notifications) | `techdrona_audit_backend_an` | 12 probes, assertions written to print evidence; all ran |
| `pmso/` (placement/mentoring/support/orgs) | `techdrona_audit_backend_pm` | 12 probes, print evidence lines; all ran |

Run e.g. `TD_TEST_DB_NAME=techdrona_audit_backend [TD_TEST_RESET_DB=1] .venv/Scripts/python -m pytest -q -s -p no:cacheprovider tests/_audit_scratch/backend/learning`.
Probes use the real resolver/permission checker (`browser` fixture) or `auth`/`make_principal`, and swap `app.core.access` checkers (allow / deny / switchable) to exercise entitlement gating.

## Feature / coverage inventory

| Feature/Req ID | Requirement source | Code location | Audit method | Result |
|---|---|---|---|---|
| CAT-01/02/07 public catalogue, private/draft hidden, cursor | api-spec §CAT, §1.10 | catalog/router.py:71-190 | probe `test_probe_catalog_public` (private slug 404, not in search; bad cursor 400 `invalid_cursor`) | Verified OK (limit silently clamped — BE-34) |
| LRN-03 self-enrol (free / entitlement, fail closed) | LRN-03, FR-LRN-001 | learning/service.py:181 | existing tests + probes | Verified OK |
| LRN-05 lesson payload entitlement gate | LRN-05 "S + entitlement" | learning/router.py:250, service.py:104 | probes: org-private course → 404 (RLS); paid → 403 `entitlement_required` | Issue BE-05 (private-visibility free course) |
| Free-preview of org-private paid course (outsider) | LRN-05, MED-04 | service.py:109 | probe → 404/404 | Verified OK (RLS) |
| LRN-06 article completion evidence (open + scrolled + 30% read time) | BR-EVD-01 | service.py:369 | existing tests | Verified OK |
| Video completion from server-timed heartbeats | MED-05, BR-EVD-01 | service.py:301-366, media/service.py:330 | existing tests + probe | OK for MED-05 path; analytics coverage feed forgeable (BE-01); credits after revoke (BE-19) |
| Course completion / progress recompute | FR-LRN | service.py:488 | code + probe | Issue BE-06 (minor version auto-migration) |
| Certificates: rule issue, public verify minimal fields, revoke (step-up) | LRN-11..13, 20/21 | service.py:522-679, router.py:623-700 | existing tests + code review | Verified OK |
| LRN-10 assignment submission (window, attempts, file key prefix) | LRN-10 | router.py:518-620 | probe | Issue BE-07 (code_submission_id unverified) |
| LRN-17/18 grading, late penalty | LRN-17, assignment schema `late_penalty_pct` | router.py:922-1000 | probe | Issue BE-08 |
| LRN-22/24 staff enrolment/progress scoping | LRN-24, BR-ENT-14 | router.py:1121-1306 | existing cross-tenant test (404) | Verified OK |
| MED-04 playback token: entitlement, stream cap, 30/h, watermark | MED-04 | media/service.py:185 | existing tests + probes | Verified OK |
| MED-07 downloads (entitled resources, scan clean) | MED-07 | media/router.py:319 | code review | Verified OK |
| Server-side scoring only (no client score fields) | api-spec §15.1 | assessments/schemas.py (extra=forbid); attempts.py:964 | probe (400 on `is_correct`/`score`) | Verified OK |
| Deadline + grace, auto-submit on access/sweeper | §15.1 | attempts.py:619-660, 915 | code + existing tests | Verified OK (section-locked gap BE-10) |
| Autosave idempotency (client_seq) | ATT-06 | attempts.py:759-909 | code + existing tests | Verified OK |
| Attempt limits / one open attempt | ATT-01 | attempts.py:392-417 + unique indexes | code + migration | OK (race → BE-22 Suspected) |
| Random draw feasibility | ASM-08/09 | studio.py:360-392 vs attempts.py:297 | probe | Issue BE-03 |
| Answer keys hidden until review policy allows | §15.1, FR-ASM-008 | attempts.py:1350-1492 | 2 probes | Issue BE-04 |
| Test / coding entitlement gating | ATT-01, COD | attempts.py:381; coding/service.py:245,531 | probes | Verified OK (drafts: BE-20) |
| Hidden coding test cases never returned | §15.3 | coding/worker.py:125,225; service.py:631-686 | probe (secret strings absent in 4 responses) | Verified OK |
| Student code never executed in-process | ADR-0005 | coding/judge_gateway, worker.py | grep (no subprocess/exec/eval); fake judge refused in production | Verified OK |
| 404 (not 403) for other users' attempts/submissions | §1.13 | attempts.py:144; coding/router.py:256 | probes | Verified OK |
| Rate limits on attempt endpoints | §15.2 | assessments/router.py:1-9 | code | Not built (BE-09) |
| Coding submission org attribution | COD-08 | coding/router.py:159 | probe | Issue BE-11 |
| Analytics ingest identity from session only; batch limits; server-only events | analytics-event-schema §1.1, §5.2 | analytics/service.py | probe | Verified OK |
| Duplicate / out-of-order ingest idempotent | §3.7 | service.py, timemodel.py | probe | Verified OK |
| Interval union across tabs; 5 metrics M1..M5 | §3.5, §3.11 | timemodel.py | probe, hand-computed (900,900,0,0,900) | Verified OK |
| Clock skew / future events | §1.3 | service.py `_effective` | probe | Verified OK |
| Video coverage clamp | §3.9, §5.5(6) | service.py:478 | probe | Issue BE-01 |
| M5 evidence rule | §3.11, §5.5(7) | timemodel.py:509,563 | probe | Issue BE-12 |
| Org attribution for coordinator/trainer reports | §4.2, §7.2-7.3 | analytics/hooks.py:82 | probe + code | Issue BE-02 |
| Entity entitlement at ingest | §5.3, §5.5(5) | service.py:204-225 | probe | Issue BE-13 |
| Retention purge | §4.4 | jobs.py:1085 | probe | Issue BE-24 |
| Report scoping / k-floor / exports authz | §7.3, ANL-13..15 | analytics/router.py, reports.py, exports.py | probe + existing tests | Verified OK (filters: BE-25) |
| NTF-01..03 inbox ownership | api-spec §21 | notifications/router.py | probe (other user's id → 404; read-all own only) | Verified OK |
| NTF-04/05 preferences | api-spec §21 | — | probe → 404 | Not built (BE-26) |
| PLC-19 practice start entitlement (question_set / company_path) | PLC-19 | placement/practice.py:69-91 | probe | Verified OK |
| PLC-20/21 no keys in delivery, server scoring, idempotent answer | PLC-21 | practice.py:221-296, bank.py:718 | probe | Verified OK |
| PLC-21/22 entitlement re-checked on answer/reveal | PLC-21 | practice.py:221,298 | probe | Issue BE-14 |
| PLC-32 company paths (published only) | PLC-32 | practice.py:81, 640 | probe | Issue BE-27 |
| Mentoring slots/booking/cancel/reschedule (no double booking, own bookings only, cross-college 404) | FR-PLC-010, PLC-36..45 | mentoring/service.py:469-935 + partial unique indexes | code + existing tests | Verified OK (true concurrency not testable) |
| Support tickets: requester sees public msgs only, other student 404, state transitions | SUP-01..06 | support/router.py:190-460 | probe | Verified OK |
| SUP-07 coordinator queue scope | SUP-07 | support/service.py:60-130 | probe | Issue BE-16 |
| Support attachments / categories | FR-SUP-001 | support/router.py:53-90 | probe | Not built (BE-17) |
| Org isolation between colleges (coordinator) | §8 TI-02 | orgs/router.py | probe (6 GETs, PATCH, move → 404) | Verified OK |
| Batch lifecycle | ORG-23/24/26 | orgs/router.py:131,1119-1240 | probe | Issue BE-18 |
| ORG-07 roster batch scope + pagination | ORG-07 | orgs/router.py:385-440 | probe | Issue BE-29 |
| ORG-10/11 CSV import validation | ORG-10/11 | orgs/csv_import.py | probe | Verified OK (formula injection: BE-30) |
| problem+json shape | §1.13 | core/errors.py | probes across modules | Verified OK (status inconsistency BE-33) |

---

## Issues

### BE-01: Video coverage forgeable via client `sample_interval_ms`; forged coverage auto-completes video lessons
- Severity: High
- Status: Confirmed
- Component: `apps/api/app/modules/analytics/service.py:478` (`clamp_played_ranges(pairs, hb.sample_interval_ms / 1000.0, rate)`), `analytics/timemodel.py:653`, `analytics/jobs.py:917` `run_video_coverage`, `app/wiring.py:213-226` `video_coverage_lookup`, `modules/learning/service.py:343-358`; endpoint POST `/api/v1/analytics/events`
- Requirement: analytics-event-schema §3.9 (`Σ(to−from) ≤ credit_wall_s × rate × 1.1 + 1`), §5.5(6)/(8); BR-EVD-01 (completion never from forgeable/time-only signals)
- Repro: `tests/_audit_scratch/backend/analytics/test_probe_analytics.py` P1/P1b — 3 engaged heartbeats 10 s apart with `sample_interval_ms=330000`, `rate=2.0`, `played_ranges [[727i,727(i+1)]]`, `lesson_id` = enrolled video lesson, `lesson_asset_id` = random UUID; run `run_video_coverage`; send one MED-05 heartbeat with a 5 s advance.
- Expected / Actual: ≈70 s coverage for 30 s wall time; lesson stays in progress / Actual 2181 s coverage, 600 s lesson marked **completed**.
- Evidence: `P1 covered_s after 30 s of wall clock: 2181.0`; `P1b lesson progress: completed 2181 100.00`
- Root cause: clamp budget uses client-claimed `sample_interval_ms` (≤330 s) instead of server-credited Δt; `lesson_asset_id`/`lesson_id` never cross-validated; learning takes `max(own watched_seconds, analytics covered_s)` without clipping to duration.
- Recommended fix: compute clamp from server Δ`effective_at` to previous sample of same page instance (cap C_max); reject assets not belonging to `lesson_id`; clip `covered_s` to asset duration in `video_coverage_lookup`.
- Suggested owner paths: `apps/api/app/modules/analytics/service.py`, `analytics/timemodel.py`, `analytics/jobs.py`, `apps/api/app/wiring.py`

### BE-02: Client activity never attributed to the learner's college → coordinator/trainer time reports empty
- Severity: High
- Status: Confirmed (backend); web side by code read
- Component: `apps/api/app/modules/analytics/hooks.py:82` `_default_org` (org only from `entity.batch_id`); `register_org_resolver` never called; web `useActivityTracker` (`apps/web/src/features/learning/components/LessonView.tsx:269`, `StudentDashboard.tsx:21`) never sends `batch_id`; reports read `entity_kind='organization'` (`reports.py` `_org_m5`, `student_metrics`)
- Requirement: analytics-event-schema §4.2 (activity rolls up to the org of the enrolment), §7.2/§7.3 (coordinator/trainer weekly M5, active learners)
- Repro: P3 — batch member ingests a web-shaped heartbeat (course + lesson) and one with `batch_id`.
- Expected / Actual: org = learner's college / `activity_heartbeats.organization_id` NULL → ANL-06/07/08 and coordinator exports show 0.
- Evidence: `P3 org web_like: None with batch_id: 01a1a20e-...`
- Root cause: no org resolver registered; default depends on a client field the web never sends.
- Recommended fix: register an org resolver in `wiring.py` mapping (user, course/lesson) → enrolment org/batch; don't rely on client `batch_id`.
- Suggested owner paths: `apps/api/app/wiring.py`, `apps/api/app/modules/analytics/hooks.py`

### BE-03: Test publishable with overlapping draw rules that can never be satisfied — every start then fails
- Severity: High
- Status: Confirmed
- Component: `apps/api/app/modules/assessments/studio.py:360-392` (`validate`/`publish`), `attempts.py:297-306` (`build_layout`); ATT-01 POST /attempts
- Requirement: ASM-08/09 (publish rejects infeasible draw rules)
- Repro: `assessments_coding/test_probe_assessments.py::test_probe_overlapping_rules_publish_ok_but_start_fails` — topic with 4 questions; section with `fixed(q0)` + `random(topic, draw_count=4)`; publish, assign, start.
- Expected / Actual: publish 409 / publish OK, every start 409.
- Evidence: `START 409 {"code":"invalid_state_transition","detail":"This test cannot be started right now (question pool exhausted). Please contact support."}`
- Root cause: `validate()` checks each rule's pool independently; `build_layout()` excludes already-used questions.
- Recommended fix: simulate the draw in `validate()` with a shared used-set across sections/rules (fixed first); mark the short rule `ok:false`.
- Suggested owner paths: `apps/api/app/modules/assessments/studio.py`

### BE-04: Answer keys released to finished students while other students can still start the same test
- Severity: High (exam integrity / answer-key leak)
- Status: Confirmed
- Component: `apps/api/app/modules/assessments/attempts.py:1350-1363` (`phase_of`), 1441-1492 (`review_payload`); ATT-11/12
- Requirement: api-spec §15.1 "Answer keys never leave the server before the review policy allows it"; FR-ASM-007 (window extensions), FR-ASM-008
- Repro: `test_probe_answer_keys_leak_while_other_batch_window_open` (same test assigned to batch A closed and batch A2 open); `test_probe_answer_keys_leak_vs_window_extension_override` (classmate with +24 h override).
- Expected / Actual: after-close phase only when nobody can still start/continue / keys returned while another student's start returns 201.
- Evidence: `REVIEW phase after_close keys present: ['correct_answer','correct_option_ids','explanation_html','is_correct']` / `OTHER BATCH START 201`; `phase after_close keys: [...] | extended student start: 201`
- Root cause: `phase_of` uses only the viewer's own assignment end (or test end), ignoring other assignments and overrides.
- Recommended fix: compute a per-test effective close = max(assignment ends + max extension, running attempts' deadlines); use it for the after-close phase (or a release timestamp).
- Suggested owner paths: `apps/api/app/modules/assessments/attempts.py`

### BE-05: Lessons of a `private`-visibility free platform course are readable by any signed-in user
- Severity: Medium
- Status: Confirmed
- Component: `apps/api/app/modules/learning/router.py:250-296` (LRN-05), `learning/service.py:85-111` (`student_lesson`, `check_lesson_access`), 208-230 (`enrolment_for_lesson`)
- Requirement: LRN-05 "lesson payload after entitlement check"; course visibility (`private`/`org_only` not enrollable, database-schema courses.visibility)
- Repro: `learning/test_learning_probes.py::test_probe_private_visibility_platform_free_course` — platform course `is_free=True, visibility="private"`; signed-in student calls LRN-03 then LRN-05.
- Expected / Actual: 404 for both / enrol 404 but lesson **200 with full `article_body`**.
- Evidence: `ENROL private 404 ...` / `LESSON private 200 {"id":"01a1a214-...","lesson_key":"...","title":"Article","lesson_type":"article",...}`
- Root cause: `student_lesson` filters only on version status / deleted; `check_lesson_access` asks the entitlement checker with `is_free=course.is_free`, which allows free courses; when `course_enrollable` is false `enrolment_for_lesson` returns None and the handler still serves content (only checks `version.status`). Org-private courses are saved only by RLS (outsider → 404, verified), not by this code.
- Recommended fix: in `lesson_payload` (and media `student_asset` callers) require `course_enrollable(course, principal)` or an existing active enrolment/entitlement unless the lesson is a free preview of a public/unlisted course.
- Suggested owner paths: `apps/api/app/modules/learning/service.py`, `apps/api/app/modules/learning/router.py`, `apps/api/app/modules/media/service.py`

### BE-06: Minor-version auto-migration does not recompute progress / completion
- Severity: Medium
- Status: Confirmed
- Component: `apps/api/app/modules/learning/service.py:716-731` (`on_course_published`) vs `migrate_version` 685-713
- Requirement: FR-CAT-002 ("minor ... auto-migrates progress")
- Repro: `test_probe_minor_version_publish_does_not_recompute` — learner completes both required lessons (enrolment completed, cert issued); publish minor v2 that adds a third required lesson; call the publish hook; GET LRN-04.
- Expected / Actual: enrolment re-opened (`active`, 66.67%) as LRN-07 `migrate_version` does / stays `completed`, 100%, while the new lesson is `not_started`.
- Evidence: `AFTER MINOR on_v2: True completed 100.0 ['completed', 'completed', 'not_started']`
- Root cause: hook does a bulk `UPDATE enrolments SET course_version_id` with no recompute / reopen.
- Recommended fix: after the bulk update, recompute affected enrolments (or reuse `migrate_version` per enrolment, batched/job).
- Suggested owner paths: `apps/api/app/modules/learning/service.py`

### BE-07: Code-type assignment accepts any `code_submission_id` (not verified to exist or belong to the learner)
- Severity: Medium
- Status: Confirmed
- Component: `apps/api/app/modules/learning/router.py:511-516` (`SubmissionIn`), 599-616 (`_validate_payload`), 518 (LRN-10)
- Requirement: LRN-10; ownership/IDOR rules (§1.13)
- Repro: `test_probe_code_assignment_accepts_foreign_code_submission` — POST `/me/assignments/{id}/submissions` `{"code_submission_id": <random uuid>}`.
- Expected / Actual: 404/422 / 201, submission stored (column has no FK) and the assignment lesson is marked complete.
- Evidence: `CODE SUBMIT random code_submission_id 201 {"assignment_id":"01a1a214-...","code_submission_id":"435365c9-...",...}`
- Root cause: only non-null is checked. A learner can also cite another learner's submission id (grader would then review someone else's code).
- Recommended fix: verify `code_submissions.id` exists, `user_id == principal`, and (if set) problem matches the assignment.
- Suggested owner paths: `apps/api/app/modules/learning/router.py`

### BE-08: Assignment `late_penalty_pct` is stored but never applied
- Severity: Medium
- Status: Confirmed
- Component: `apps/api/app/modules/learning/router.py:922-972` (LRN-17 `grade`), `_submission_out`
- Requirement: assignment contract (`late_penalty_pct`, LRN-14), late window semantics
- Repro: `test_probe_late_penalty_not_applied` — assignment max 10, `late_penalty_pct=50`; learner submits late (status `late`); trainer grades 10; releases.
- Expected / Actual: learner score 5 (or penalty shown) / 10.0 everywhere.
- Evidence: `LATE SUBMIT 201 late` / `GRADE late w/ 50% penalty: 200 10.0 release 200 learner view 200 10.0`
- Root cause: no code reads `late_penalty_pct` after creation.
- Recommended fix: apply penalty on grade for `late` submissions (store raw + final score), or document it as advisory and show it in the grading UI.
- Suggested owner paths: `apps/api/app/modules/learning/router.py`, learning models/migration if a raw score column is added

### BE-09: Spec rate limits on assessment attempt endpoints not built
- Severity: Medium
- Status: Confirmed (code self-documents)
- Component: `apps/api/app/modules/assessments/router.py:1-9` ("Not implemented: ... per-endpoint rate limits (§15.2 column)"); no limiter in `core/middleware.py`/`main.py`
- Requirement: api-spec §15.2 (ATT-01 10/min, ATT-02 30/min, ATT-05 5/h, ATT-06 30/min/attempt, ATT-07 4/min, ATT-10 5/min)
- Expected / Actual: 429 `rate_limited` / unlimited.
- Recommended fix: reuse `commerce/ratelimit.hit` (move to core) per route.
- Suggested owner paths: `apps/api/app/modules/assessments/router.py`, `apps/api/app/core/`

### BE-10: Section-locked attempt stays `in_progress` after every section timed out
- Severity: Medium
- Status: Confirmed
- Component: `apps/api/app/modules/assessments/attempts.py:638-660` (`advance_sections`), 625-635 (`expire_if_due`)
- Requirement: §15.1 server timer and auto-submit
- Repro: `test_probe_section_timeouts_before_test_deadline` — two 60 s sections, 3600 s test, `section_locked`; push both section deadlines into the past; GET /time.
- Expected / Actual: auto-submit / stays `in_progress`, nothing writable, unscored and blocking a new attempt until test deadline.
- Evidence: `TIME 200 in_progress sections ['timed_out', 'timed_out'] attempt in_progress`
- Root cause: last section timeout with no next section never calls `finalize`.
- Recommended fix: in `advance_sections`, `finalize(..., "deadline")` when no section remains.
- Suggested owner paths: `apps/api/app/modules/assessments/attempts.py`

### BE-11: Coding submissions get `organization_id = NULL` when learner has 0 or >1 orgs
- Severity: Medium
- Status: Confirmed
- Component: `apps/api/app/modules/coding/router.py:159-160` (`_org_of`), used at :190, :241
- Requirement: COD-08 staff read @org; org-scoped reporting
- Repro: `test_probe_submission_org_attribution_multi_org` (learner in two orgs).
- Evidence: `multi-org submission organization_id: None`
- Expected / Actual: relevant org (attempt's org for in-attempt; problem org for org-private) / NULL → invisible to both colleges, missing from org reports.
- Recommended fix: derive org from the attempt (in-test) or the problem/assignment context.
- Suggested owner paths: `apps/api/app/modules/coding/router.py`

### BE-12: Unverified client `test_attempt_id` turns evidence-free time into M5 meaningful-learning time
- Severity: Medium
- Status: Confirmed
- Component: `apps/api/app/modules/analytics/timemodel.py:509` (priority 0 when `test_attempt_id`), :563 (whole piece counts as evidence); `service.py:204` (no ownership/in-progress check)
- Requirement: analytics-event-schema §3.11 E(s) ("in-progress attempt" is a server fact), §5.5(7)
- Repro: P2 — two users, 10 min on `lesson_text` with no scroll/signals; spoof adds `entity.test_attempt_id` = random UUID.
- Evidence: `P2 (m1,m2,m3,m4,m5) control: (600, 600, 0, 0, 0) spoof: (600, 600, 0, 0, 600)`
- Recommended fix: at ingest accept `test_attempt_id` only if it is the principal's own in-progress attempt (else `entity_not_entitled`), or derive attempts from server `assessment.attempt_started` events.
- Suggested owner paths: `apps/api/app/modules/analytics/service.py`, `analytics/jobs.py` (`load_day_inputs`)

### BE-13: Analytics entity entitlement check skips `lesson_id` when `course_id` present and never checks asset/attempt/test/question/company_path
- Severity: Medium
- Status: Confirmed
- Component: `apps/api/app/modules/analytics/service.py:204-225` (`_entitled`)
- Requirement: analytics-event-schema §5.3 step 3, §5.5(5)
- Repro: P4 — checker allowing only `course` still accepts course + denied lesson; deny-all checker accepts entity with `lesson_asset_id`, `test_attempt_id`, `question_id`, `test_id`, `company_path_id` (0 checks made).
- Evidence: `P4a course(allowed)+lesson(denied): {... 'status': 'accepted'} checks: ['course']`; `P4b deny-all ... 'status': 'accepted'} checks: []`
- Recommended fix: check `lesson_id` (and that it belongs to `course_id`), `lesson_asset_id` via lesson, `test_id`, `company_path_id`, attempt ownership. Enables BE-01/BE-12.
- Suggested owner paths: `apps/api/app/modules/analytics/service.py`

### BE-14: Practice answer and solution reveal still served after entitlement is lost
- Severity: Medium
- Status: Confirmed
- Component: `apps/api/app/modules/placement/practice.py:221` (`answer`), :298 (`reveal`); `placement/router.py:401-430`
- Requirement: api-spec §13.1 PLC-21/22 "S + entitlement"
- Repro: `pmso/test_pm_probes.py::test_practice_answer_after_entitlement_lost` — start while allowed, switch checker to deny, answer + reveal.
- Expected / Actual: 403 `entitlement_required` / both 200 with `correct_option_ids`, `explanation_html`.
- Evidence: `ANSWER_AFTER_REVOKE 200 [... 'correct_option_ids','explanation_html','is_correct' ...]`; `REVEAL_AFTER_REVOKE 200 [...]`
- Root cause: `require_access` only in `start()`; sessions never expire.
- Recommended fix: re-check access (question_set root topic or company_path via step) in `answer`/`reveal`.
- Suggested owner paths: `apps/api/app/modules/placement/practice.py`

### BE-15: Practice session counters lose updates; concurrent duplicate answers may 500
- Severity: Medium
- Status: Suspected (shared-connection fixture cannot reproduce true concurrency)
- Component: `placement/practice.py:60-64` (`session.get` without lock), :271-273 (`ps.answered_count += 1` absolute write); UNIQUE(practice_session_id, question_version_id) in placement_0001:231; `core/errors.py:292` maps integrity errors to 500. Also `my_company_path` (practice.py:664) raises 403 for the whole page if one path is unentitled.
- Requirement: PLC-21 (correct counts, idempotent answers), PLC-32
- Repro idea: two parallel answers with different Idempotency-Keys.
- Recommended fix: `SELECT … FOR UPDATE` on the practice session or SQL increments; catch unique violation and return existing feedback; filter unentitled paths in `my_company_path`.
- Suggested owner paths: `apps/api/app/modules/placement/practice.py`

### BE-16: College coordinators see support agents' internal notes and non-college-access tickets
- Severity: Medium
- Status: Confirmed
- Component: `apps/api/app/modules/support/service.py:60-62` (`ORG_VISIBLE_CATEGORIES`), :125-129; `support/router.py:308` (`internal = agent is not None`)
- Requirement: api-spec §22 SUP-07 (coordinator: own org's college-access tickets); FR-SUP-001
- Repro: `pmso/test_so_probes.py::test_support_coordinator_sees_internal_notes`.
- Evidence: `COORD_VIEW 200 agent [('internal', 'INTERNAL: suspect ac')]`; `COORD_QUEUE 200 {"data":[{... "category":"technical" ...`; `COORD_INTERNAL_POST 201`; cross-org still `COORD_CROSS_ORG 404`.
- Root cause: any `ticket.read` @org holder is treated as a full agent; `can_respond` is global.
- Recommended fix: add `college_access` category and restrict coordinators to it; hide platform-staff internal notes from org-scoped viewers; per-org `can_respond`.
- Suggested owner paths: `apps/api/app/modules/support/service.py`, `support/router.py`

### BE-17: Support ticket attachments and required categories not built
- Severity: Medium
- Status: Confirmed
- Component: `apps/api/app/modules/support/router.py:53-90` (`TicketIn`, extra=forbid, no attachments)
- Requirement: SUP-01 attachments; FR-SUP-001 categories (certificate, college access, appeal)
- Evidence: `SUPPORT_ATTACHMENTS 400 validation_failed`
- Recommended fix: attachments via MED-02 upload flow; align categories with FR-SUP-001.
- Suggested owner paths: `support/router.py`, `support/service.py`, new migration

### BE-18: Batch lifecycle has no state checks (archive repeatable, add to archived, un-archive via PATCH)
- Severity: Medium
- Status: Confirmed
- Component: `apps/api/app/modules/orgs/router.py:1119-1128` (archive), :1158 (add members), :131/:1092 (PATCH status)
- Requirement: ORG-24 archive; `invalid_state_transition`
- Repro: `pmso/test_so_probes.py::test_orgs_coordinator_scoping` (archive section).
- Evidence: `ARCHIVE 200 archived`, `ARCHIVE_AGAIN 200 archived`, `ADD_TO_ARCHIVED 200 {'added': 1}`, `UNARCHIVE_VIA_PATCH 200 active`
- Recommended fix: 409 `invalid_state_transition` for these on archived batches; audit only real transitions.
- Suggested owner paths: `apps/api/app/modules/orgs/router.py`

### BE-19: Playback heartbeats keep crediting video progress after entitlement is withdrawn
- Severity: Low
- Status: Confirmed
- Component: `apps/api/app/modules/media/service.py:316-361` (`heartbeat` — access checked only at token issue, MED-04)
- Requirement: MED-04/05 "S + entitlement"; BR-ENT (revocation effect)
- Repro: `learning/test_learning_probes.py::test_probe_video_heartbeat_after_entitlement_revoked` — token issued while allowed, checker switched to deny, heartbeat after 30 s at position 60.
- Expected / Actual: heartbeat 410 `playback_revoked` (or no credit) / 200 and progress credited, while LRN-05 already returns 403.
- Evidence: `HEARTBEAT after revoke 200 {"state":"active",...}` / `LESSON after revoke 403 entitlement_required` / `OVERVIEW after revoke [0.0, 10.0]`
- Recommended fix: re-check `check_lesson_access` in heartbeat (cached, e.g. every N heartbeats) and end the session on denial. VdoCipher OTP TTL bounds the actual stream.
- Suggested owner paths: `apps/api/app/modules/media/service.py`

### BE-20: Coding drafts saved/read for problems the learner isn't entitled to
- Severity: Low
- Status: Confirmed
- Component: `apps/api/app/modules/coding/router.py:512-524` (COD-04 PUT / COD-05 GET drafts)
- Evidence: `DRAFT unentitled 200 {"problem_id":"01a1a205-...","language_key":"python3","size_bytes":8,...}`
- Recommended fix: call `service.require_problem_access` in COD-04/05.
- Suggested owner paths: `apps/api/app/modules/coding/router.py`

### BE-21: `/me/attempts` (and `/studio/tests`) unpaginated with silent caps
- Severity: Low
- Status: Confirmed
- Component: `apps/api/app/modules/assessments/router.py:325-357` (`.limit(200)`), :500 (`.limit(500)`)
- Requirement: §1.10 cursor pagination
- Evidence: `{'items': [], 'server_now': ...}` — no `page` meta; `?limit=` ignored.
- Recommended fix: `core.pagination` cursor on (started_at, id), limit ≤ 100.
- Suggested owner paths: `apps/api/app/modules/assessments/router.py`

### BE-22: Concurrent attempt starts likely return 500 instead of 409
- Severity: Low
- Status: Suspected
- Component: `assessments/attempts.py:392-458`; unique indexes `migrations/versions/assessments_0001_assessments.py:190,194`; `core/errors.py:291-292`
- Expected / Actual: loser gets 409 `active_attempt_exists` / likely 500 `internal_error` (data stays consistent).
- Recommended fix: catch unique violation → `active_attempt_exists`, or advisory lock on (user, test).
- Suggested owner paths: `apps/api/app/modules/assessments/attempts.py`

### BE-23: Review page lacks own source and per-case verdicts for coding questions
- Severity: Low
- Status: Confirmed (code review)
- Component: `assessments/attempts.py:1466-1490` (coding `your_response` is only `{"submission_id"}`)
- Requirement: ATT-12 detail
- Recommended fix: attach `coding.service.submission_view(sub, include_source=True)` (hidden cases already verdict-only).
- Suggested owner paths: `apps/api/app/modules/assessments/attempts.py`

### BE-24: Heartbeat retention purge keys on client-derived `event_ts`
- Severity: Low
- Status: Confirmed
- Component: `apps/api/app/modules/analytics/jobs.py:1085` (`_PURGE` on `event_ts` = client UUIDv7 time)
- Requirement: analytics-event-schema §4.4 (35-day retention)
- Evidence: `P6 effective_at: 2026-11-03 15:37 event_ts: 2026-09-24 15:37`; `P6 purge: 1 remaining rows for user: 0`
- Recommended fix: purge on `received_at`/`effective_at`, or reject |event_ts − effective_at| > L_late.
- Suggested owner paths: `analytics/jobs.py`, `analytics/service.py`

### BE-25: Analytics export `filters` (from/to) accepted but ignored
- Severity: Low
- Status: Suspected (code read)
- Component: `apps/api/app/modules/analytics/exports.py:444-475` (`_build` never reads `job.filters`)
- Requirement: ANL-13 example `filters: {from, to}`
- Recommended fix: apply filters or 422 on unsupported ones.
- Suggested owner paths: `analytics/exports.py`, `analytics/reports.py`

### BE-26: Notification preferences (NTF-04/05) not built
- Severity: Low
- Status: Confirmed
- Component: `apps/api/app/modules/notifications/router.py` (no route)
- Evidence: `P9 preferences: 404` (GET `/api/v1/me/notification-preferences`)
- Recommended fix: implement NTF-04/05 (marketing off by default; never for minors — suppression already exists in `notify()`).
- Suggested owner paths: `notifications/router.py`, `notifications/service.py`

### BE-27: Steps of a draft (unpublished) company path can be practised
- Severity: Low
- Status: Confirmed
- Component: `apps/api/app/modules/placement/practice.py:81-83`
- Evidence: `PUT_DRAFT 200 draft`, `STUDENT_GET_DRAFT_PATH 404`, `PRACTICE_DRAFT_STEP 201`
- Recommended fix: join `CompanyPath`, require `status == 'published'` → else 404.
- Suggested owner paths: `placement/practice.py`

### BE-28: Answers after "reveal solution" count as correct in the set summary
- Severity: Low
- Status: Confirmed
- Component: `placement/practice.py:271-273`, `complete()` :314
- Requirement: PLC-22 ("lowers mastery weight")
- Evidence: `REVEAL_THEN_ANSWER True True summary 1 1.0` (mastery correctly excludes it)
- Recommended fix: exclude `solution_viewed` responses from `correct_count`/accuracy or report separately.
- Suggested owner paths: `placement/practice.py`

### BE-29: ORG-07 roster ignores batch scope and is not paginated
- Severity: Low
- Status: Confirmed (trainer 403); Suspected (1000-row cap)
- Component: `apps/api/app/modules/orgs/router.py:385-440` (org-level permission only; `.limit(1000)`, `has_more: False`); invitations :712-731 same
- Requirement: ORG-07 `org.member.read @O/@B`; §1.10
- Evidence: `TRAINER_ORG_MEMBERS 403 permission_denied` (trainer with own `batch_id`)
- Recommended fix: accept batch scope when `batch_id` is given; cursor pagination ≤ 100.
- Suggested owner paths: `orgs/router.py`

### BE-30: CSV import formula-injection neutralisation incomplete
- Severity: Low
- Status: Confirmed
- Component: `apps/api/app/modules/orgs/csv_import.py:53-58` (strips only leading `=`/`@`)
- Evidence: `CSV_NAMES ['+SUM(1+1)*cmd', '-2+3', 'HYPERLINK("http://e")', 'Ok Name']`; also `roll_number` duplicates only checked within the file.
- Recommended fix: neutralise leading `+ - = @ \t \r` on export (prefix `'`); check roll numbers against existing `org_memberships.external_ref`.
- Suggested owner paths: `orgs/csv_import.py`

### BE-31: Spec/status drift (mentoring, support, ORG-27 scope)
- Severity: Low
- Status: Confirmed
- Component: `docs/api-specification.md` §13.1 PLC-36..52 and §22 SUP-01..15 marked "Planned" but implemented; `placement/router.py:1-7` docstring says mentoring not implemented; ORG-27 spec says org scope but `rbac/catalogue.py:180` gives `batch.member.manage` to trainers @batch.
- Evidence: `TRAINER_REMOVE_BATCH_MEMBER 200 {"removed":true}`
- Recommended fix: update spec status columns/docstring; decide ORG-27 scope.
- Suggested owner paths: `docs/api-specification.md`, `apps/api/app/modules/rbac/catalogue.py`, `placement/router.py`

### BE-32: Support SLAs computed in calendar hours; P1 never derived
- Severity: Low
- Status: Confirmed (code review)
- Component: `apps/api/app/modules/support/service.py:41-47`
- Requirement: FR-SUP-003 (business hours; P1 = cannot access paid content / test in progress)
- Recommended fix: business-hours calendar; auto-raise priority from ticket context.
- Suggested owner paths: `support/service.py`

### BE-33: `validation_failed` returned as 400 in some modules and 422 in others
- Severity: Low
- Status: Confirmed
- Component: `core/errors.py:192` (400, catalogue §2.1) vs module helpers defaulting to 422: `support/router.py:70`, `orgs/router.py:70`, `learning/service.py:78` (`vf(..., status=422)`), catalog `vf`.
- Requirement: api-spec §1.13 / §2.1
- Evidence: `SUPPORT_VF_NOT_MEMBER 422` vs `SUPPORT_VF_PYDANTIC 400`; `BATCH_VF 422` vs `BATCH_VF_PYD 400`; `IMPORT_BADHDR 422`; placement `PRACTICE_HUGE_COUNT 400`; learning LRN-06 missing evidence → 422 (existing test asserts 422); bad UUID path → 400.
- Recommended fix: one status for `validation_failed` (catalogue 400) or document 422 for business-rule validation.
- Suggested owner paths: `support/router.py`, `orgs/router.py`, `learning/service.py`, `catalog/service.py`

### BE-34: Pagination inconsistencies in catalog/learning lists
- Severity: Low
- Status: Confirmed
- Component: `catalog/router.py:66-68` (`_limit` silently clamps; other modules reject `limit>100` with 400); `learning/router.py:141-146` (LRN-02) and :623-635 (LRN-11) return all rows with a fixed `page` meta.
- Requirement: api-spec §1.10
- Evidence: `CATALOG limit=1000 200 {'next_cursor': None, 'has_more': False, 'limit': 100}`; `MY ENROLMENTS page {'next_cursor': None, 'has_more': False, 'limit': 100}` (query `limit=5` ignored)
- Recommended fix: consistent `limit` validation (Query le=100) and cursor support on learner lists.
- Suggested owner paths: `catalog/router.py`, `learning/router.py`

---

## Summary

| Severity | Count | IDs |
|---|---|---|
| Critical | 0 | — |
| High | 4 | BE-01, BE-02, BE-03, BE-04 |
| Medium | 14 | BE-05 … BE-18 |
| Low | 16 | BE-19 … BE-34 |

Confirmed 30, Suspected 4 (BE-15, BE-22, BE-25, part of BE-29).

Strong points verified: server-side scoring only (client score fields rejected), hidden coding test cases never returned, no in-process code execution (judge adapter path only, fake judge refused in production), cross-college isolation in orgs/support/mentoring/learning (404), playback stream cap + token rate limit, certificate public verify minimal fields, analytics interval union across tabs and duplicate/out-of-order idempotency.

Not tested / why:
- True concurrency (double booking, concurrent starts, practice counters): the `db` fixture shares one rolled-back connection; races assessed by code + index review only.
- Real Judge0 end-to-end and VdoCipher/S3 providers: no external calls allowed; fake adapters only.
- Real entitlements checker with real products (question_set/company_path): probes used allow/deny stand-ins (the real checker's `is_free` → allow behaviour was read in `entitlements/service.py:742,815`).
- Redis deadline sweeper timing, partition-drop jobs, web SDK idle/multi-tab behaviour (client-side).
