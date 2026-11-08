# Wave-2 fixes: w2b (catalog, learning, media, placement, mentoring, support, orgs)

Agent key `w2b`. The scope is the wave-1 §Requests aimed at these modules (webstaff 8, 9, 13, 14, 15, 17; weblearn 4 and 5; secadmin 6, 7 and 10; assess 1–4; commerce 6). Placement/mentoring and orgs ran in two forks.

Wave 1 had already fixed several of them (fix agent `learn`, `docs/audit/fixes/learn.md`), and they were re-checked, not changed:

- ADM-38 (webstaff 15): the queue is ordered in SQL by `(resolution_due_at, id)`, with an index (`support_0002`).
- ADM-30 (secadmin 6) and ADM-16 (secadmin 7).
- INV-12 media consumer (secadmin 10).
- DB-01 erasure providers.
- BE-07/BE-08 and the coverage clip (assess 1–4).
- COM-12 (commerce 6).
- MEN-004 readiness (webstaff 14, ADM-35): `tests/mentoring/test_mentor_readiness.py` passes.

| ID(s) | Severity | Fix summary | Files | Regression test | Result |
|---|---|---|---|---|---|
| webstaff 8a: lesson types `pdf` and `practice_set` (FR-CAT-001, CAT-13) | Medium | Both are defined in the PRD and the API spec, but they were missing from `LessonType` and the DB CHECK.<br>**`pdf`:** needs no reference. The file is a `lesson_assets` row (MED-02 `lesson_file`, `asset_type=pdf`). It completes through LRN-06 scroll evidence, like an article.<br>**`practice_set`:** needs `test_id`, like `quiz`.<br>The new migration `catalog_0002` replaces `lessons_lesson_type_check` and `ck_lesson_ref`. | catalog/schemas.py, catalog/service.py (`check_lesson_refs`), learning/service.py (`record_article_completion`), migrations/versions/catalog_0002_lesson_types.py | tests/catalog/test_w2b_fixes.py::test_pdf_and_practice_set_lesson_types; tests/learning/test_w2b_fixes.py::test_pdf_lesson_completes_on_scroll_evidence | Fixed+tested |
| webstaff 8b: `topics` in the studio lesson output | Low | `lesson_out(..., topics=)` adds `topics: [{topic_id, is_primary}]`, primary first.<br>It is used by CAT-10/11/12 `version_out(full=True)`, CAT-13, CAT-14 and CAT-20.<br>Learner payloads (LRN-05) do not load topics and do not get the key. | catalog/service.py (`lesson_topics_map`), catalog/router.py | test_studio_lesson_output_includes_topics | Fixed+tested |
| webstaff 8c: resources list | Low | New `GET /studio/resources?course_id=\|lesson_id=\|company_id=&cursor=&limit=` (operation `cat_21b_list_resources`).<br>Permission: `resource.manage` @C, or @P for company-only resources, the same as CAT-21.<br>Newest first, keyset cursor. With no target it returns 422.<br>The spec has no list ID; this is the read side of CAT-21/22 (see Requests). | catalog/router.py | test_studio_resources_list, test_studio_resources_list_needs_resource_manage | Fixed+tested |
| webstaff 13: rubric schema (FR-LRN-005) | Medium | **Schema:** `assignments.rubric` = `{criteria: [{key, label, max_points, description?, levels?: [{label, points}]}]}`, with 1–30 criteria.<br>**Checked on LRN-14/15:** keys are unique, a level is at most `max_points`, and the sum of `max_points` is at most `max_score`.<br>**LRN-17 `rubric_scores` `{key: points}`:** every criterion is required, unknown keys are rejected, and each score is 0..`max_points`. `score` defaults to the rubric total and must match it if both are sent (`rubric_mismatch`).<br>Rubrics stored earlier in another shape are not checked. | learning/router.py | tests/learning/test_w2b_fixes.py::test_rubric_schema_on_create_and_patch, ::test_rubric_scores_validated_and_totalled | Fixed+tested |
| weblearn 4: appeal prefill (topic + `attempt_id`) | Low | The web "topic" is the ticket `category` (`assessment`/`appeal`), which SUP-01 already accepted.<br>New optional `related_attempt_id` on SUP-01. It must be the requester's own `test_attempts` row, otherwise 422 `related_attempt_id`. It is stored in `context.attempt_id` (no new column) and returned as `related_attempt_id` by every ticket view.<br>Before this fix it was rejected, because `TicketIn` forbids extra fields. | support/router.py, support/service.py (`ticket_out`) | tests/support/test_w2b_fixes.py::test_ticket_links_own_attempt_only | Fixed+tested |
| webstaff 9a: studio topic list with inactive topics | Low | New `GET /studio/topics` (`taxonomy.manage` @P). It returns the full tree, inactive nodes included. Public PLC-01 stays active-only. | placement/router.py, placement/bank.py (`subject_tree(include_inactive=)`) | tests/placement/test_w2b_fixes.py::test_studio_topic_list_includes_inactive_for_staff_only | Fixed+tested |
| webstaff 9b: `retired_reason` | Low | The column already exists (`placement_0004`). It is now returned by PLC-06 detail and by each PLC-04 item. Topics have no reason column; the schema defines none. | placement/bank.py | ::test_retired_reason_exposed | Fixed+tested |
| webstaff 9c: PLC-04 `q` | Low | `q` (2–200 characters) does a case-insensitive match on the latest version's stem text. HTML is stripped and LIKE wildcards are escaped. | placement/router.py, placement/bank.py | ::test_question_search_by_stem_text | Fixed+tested |
| webstaff 14: MEN-004 readiness | — | Already real since wave 1 (`practised_company_readiness`). | — | tests/mentoring/test_mentor_readiness.py | Already fixed |
| webstaff 17a: `allowed_invite_domains` (FR-ORG-002) | Medium | **Settings (ORG-06):** domains are normalised (lowercase, `@` and spaces stripped, duplicates removed). A value that is not a domain gets 422.<br>**Invite create (ORG-15):** 422 `email_domain_not_allowed`.<br>**CSV import preview:** such a row is marked as an error.<br>**Accept (ORG-19):** 403 on both the new-account and the signed-in path.<br>Matching is exact and ignores case. An empty list means no restriction. | orgs/service.py (`invite_domains`, `invite_domain_allowed`), orgs/router.py | tests/orgs/test_w2b_fixes.py (4 tests) | Fixed+tested |
| webstaff 17b: `require_mfa_students` | Medium | Orgs side: the public helper `org_requires_mfa(session, user_id)` returns True for an active student of an active org that has the setting on. Enforcing it at login belongs to identity/sessions. | orgs/service.py | ::test_org_requires_mfa_helper | Orgs side fixed+tested; enforcement is a request (R1) |
| webstaff 17c: ORG-07 `member_type` filter | Low | `?member_type=student\|staff`. | orgs/router.py | ::test_members_member_type_filter | Fixed+tested |
| weblearn 5 (my modules): PLC-28/29 goals, bookmarks, CAT-03/04 company hubs, CAT-05 public sample questions, SUP-16 contact form | — | These are spec-**Planned** features, not defects. CAT-03/04 need a company-hub data model, and SUP-16 needs a CAPTCHA provider, which is not chosen. | — | — | Deferred: new feature work or needs a product decision (see below) |

## Needs product decision (not implemented)

- **SUP-16 public contact form:** the CAPTCHA provider and the anti-abuse policy.
- **CAT-03/04 company hubs:** the content model (pattern, syllabus, interview experiences, path pricing) has no table beyond the soft `resources.company_id`.
- **Org invite domains:** whether mobile-only invites (no email) are allowed when a domain list is set. Today they are not checked.
- **Org MFA for students:** whether existing students get a grace period, and whether SMS OTP counts as their second factor.
- **Rubric totals:** we chose sum of `max_points` ≤ `max_score`, and a rubric-graded score equal to the rubric total. If product wants weighted rubrics (total scaled to `max_score`), this changes.
- **PDF lessons:** whether publishing should require a scanned, ready PDF asset, as video requires a ready video (CAT-17 does not say).

## Requests

- **R1, identity/sessions (MFA, FR-ORG-002):**
  - On a student login, call `app.modules.orgs.service.org_requires_mfa(session, user.id)`.
  - If it returns True and a factor is enrolled, return `{"result": "mfa_required"}` (methods include `sms_otp`), even on a trusted device.
  - If no factor is enrolled, return 403 `mfa_enrolment_required` with `enrol_url`, and allow only the enrolment routes, as for staff.
  - The api-spec §2.1 row for `mfa_enrolment_required` says "Staff tier" and needs widening.
- **R2, docs (api-specification):**
  - Add `GET /studio/resources` (e.g. CAT-21b, `resource.manage` @C/@P) and `GET /studio/topics` (e.g. PLC-03a, `taxonomy.manage` @P, includes inactive).
  - Add `q` to PLC-04, `member_type` to ORG-07, and `related_attempt_id` to SUP-01.
  - Document the rubric schema under LRN-14/17.
  - Update database-schema §7 `lessons` CHECKs for `pdf`/`practice_set` (catalog_0002).
- **R3, coordinator:** regenerate `apps/api/openapi.json`, `apps/web/openapi/openapi.json` and the web types. The new and changed items are:
  - the two routes above;
  - `LessonType`;
  - lesson `topics`;
  - `Rubric`, and `rubric_scores` as `{string: number}`;
  - SUP-01 `related_attempt_id` and its output field;
  - PLC-04 `q` and `retired_reason`;
  - ORG-07 `member_type`, and the `email_domain_not_allowed` error.
- **R4, web:**
  - **Studio:**
    - Offer the `pdf` and `practice_set` lesson types (practice set: pick a `practice_set` test).
    - Load lesson resources from `GET studio/resources?lesson_id=`.
    - Show and edit lesson `topics`.
    - Use `GET studio/topics` on the taxonomy page, use `q` in `Questions.tsx`, and show `retired_reason`.
  - **Trainer:**
    - Create rubrics in the documented shape.
    - Grading can omit `score` when sending `rubric_scores`.
  - **Support:**
    - `NewTicketForm` should map `?topic=` to `category` and send `related_attempt_id` from `?attempt_id=`.
  - **College:**
    - Use `member_type` on the roster.
    - Show `email_domain_not_allowed` on invite and import errors.

## Test commands and results (from `apps/api`)

**Reproduction (before the fixes):**
- `TD_TEST_DB_NAME=techdrona_fix_w2b TD_TEST_RESET_DB=1 .venv/Scripts/python -m pytest -q -p no:cacheprovider tests/catalog/test_w2b_fixes.py` → 4 failed. The unknown lesson types gave 422, there was no `topics` key, and `GET /studio/resources` gave 405.
- Placement fork, `tests/placement/test_w2b_fixes.py` on `techdrona_fix_w2b_p` → 3 failed. Readiness passed.
- The learning rubric, support and orgs tests were written against the code. These bugs were confirmed by reading the code, not by running the tests on the old code:
  - any dict was accepted as a rubric;
  - `TicketIn` rejects extra fields, so an attempt link was refused;
  - nothing read the two orgs settings.

**After the fixes:**
- `TD_TEST_DB_NAME=techdrona_fix_w2b_2 TD_TEST_RESET_DB=1 ... tests/catalog/test_w2b_fixes.py tests/learning/test_w2b_fixes.py tests/support/test_w2b_fixes.py` → 8 passed. This is a fresh DB, so `catalog_0002` was applied.
- **Full owned run:** `TD_TEST_DB_NAME=techdrona_fix_w2b_2 .venv/Scripts/python -m pytest -q -p no:cacheprovider tests/catalog tests/learning tests/media tests/placement tests/mentoring tests/support tests/orgs tests/authz tests/integration` → **163 passed** in 275 s.
- After `ruff format`: the catalog and learning w2b tests → 7 passed.
- Forks:
  - `tests/placement tests/mentoring tests/authz` on `techdrona_fix_w2b_p` → 63 passed.
  - `tests/orgs` on `techdrona_fix_w2b_o` → 26 passed.
- `ruff check` on the 7 modules, their test folders and `catalog_0002` → All checks passed.
- `ruff format --check` → 53 files already formatted.
- `mypy` on the 7 modules → Success: no issues found in 47 source files.
- **Test DBs used:** `techdrona_fix_w2b`, `techdrona_fix_w2b_2`, `techdrona_fix_w2b_p`, `techdrona_fix_w2b_o`.
