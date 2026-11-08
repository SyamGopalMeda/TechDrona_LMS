# WS4: Learning delivery (learning, paths, engage, catalog, mentoring, notifications, media)

| | |
|---|---|
| Status | Done. |
| Date | 2026-11-07 |
| Plan | `REMOVAL-PLAN.md` §1.2 (delivery modules), §3, §4.2, §5 step 7, §6 WS4, and the owner decisions in §8 (D2, D3, D9, D10) |
| Dev DB | Not touched. Tests ran only on the scratch databases `techdrona_ws4`, `techdrona_ws4a`, `techdrona_ws4p` and `techdrona_ws4e`. |

## 1. What changed

### Learning: structured assignments and the legacy routes
- **SEC-02 and `evaluator_ids`.** A new function, `structured_api._ensure_grade`, decides who may grade. It returns the set of allocations the caller may grade, or "all":
  - **All allocations** when the caller holds `assignment.grade` on the assignment's own scope (its batch or course; company-wide assignments use platform scope).
  - **Otherwise, only these allocations:**
    - allocations to a batch where the caller holds `assignment.grade`;
    - allocations whose `evaluator_ids` list the caller, provided the caller holds `assignment.grade` on some grant.
  - **If neither applies:** 403 `permission_denied`.
  - **Where the set is enforced:**
    - filtered: the evaluation list, the allocation list, the AI-grading run, and the regrade queue;
    - checked per object: review, finalize, single-submission AI grading, extensions, and regrade resolve.

  There is no longer an "any allocated batch" fallback.
- **Who can be named in `evaluator_ids`:** a user with a live grant whose role holds `assignment.grade`, or an active company staff member. Anyone else gets 422 `not_evaluator`. Being named grants nothing on its own; the grading-time check still applies.
- **The staff list** `GET /assignments` also shows assignments where the caller is a named evaluator.
- **D3 (release):** `POST /assignments/{id}/release-grades` needs `assignment.grade` on the assignment's own scope. An evaluator at batch scope can therefore release results for that batch's assignments. A company-wide assignment can only be released by someone with a platform grant. A named evaluator from another batch cannot release, because release affects every batch.
- **SEC-03:** a single helper, `structured.active_batch_ids`, which keeps only memberships with `status='active'`. It is used by:
  - `_my_batch_ids`, which serves the learner's assignment list and workspace;
  - `learner_list_fields`;
  - `coding_access_grant`;
  - batch enrolment (`POST /enrolments`).
- **SEC-09:** start, autosave, submit and the tutor refuse an archived assignment with 409. The workspace, the result and the tutor history stay readable.
- **SEC-11:** legacy `POST /assignment-submissions/{id}/grade` refuses structured submissions and drafts with 409.
- **SEC-12:**
  - An extension for oneself is refused with 403 `conflict_of_interest`.
  - An extension for a user the allocation does not target is refused with 422 `not_allocated`.
- **SEC-05, SEC-17 and D10** (using WS3's API):
  - The tutor calls `ai.tutor_reply(..., item_id=...)`. That call enforces the per-user rate limit, the per-activity cap (the assignment's `ai_help_limit`, else the platform default of 20) and the server-side history. `enforce_tutor_rate` is not called a second time.
  - Client `history` is ignored.
  - The tutor response and the workspace's `ai_help` block now report the effective limit.
- **Org pickers:**
  - `AssignmentIn.organization_id` was removed. A structured assignment with no batch and no course is now company-wide: it is stamped `COMPANY_ORG_ID` and needs platform scope.
  - `GET /enrolments` and `GET /progress` lost `organization_id`:
    - with `batch_id`, the scope is that batch;
    - without it, the scope is platform and the list covers every batch's enrolments.
  - Organization grants were removed from the staff assignment list.
  - Every `require_app_enabled` and `ai_enabled` call no longer passes `org_id`.

### Catalog
- `org_only` was removed from `Visibility`, and `CourseIn.organization_id` was removed.
- `POST /studio/courses`:
  - a caller with `course.create` at platform scope (Content manager) creates a platform course;
  - a batch trainer (ADM-41) gets a company course, stamped `COMPANY_ORG_ID`.
- Company courses are enrollable by the company's batch learners and staff (`learning.service.course_enrollable`) and never appear in the public catalogue.

### Paths (fork; see its report below)
- **SEC-01:** a batch allocation (create, progress, revoke) needs `path.allocate` on that exact batch. Allocations to named users need a platform grant, or every learner must be an active student of a batch where the caller holds `path.allocate`.
- **Org helpers removed:** `_batch_org`, `can_in_org`, `require_in_org` and `org_members` are gone, and new rows are stamped `COMPANY_ORG_ID`.
- **Authoring:** a platform grant, or any batch grant that holds `path.manage`.
- **D9:** a step's `embeddable` flag is true only for these https URLs, with no userinfo and no port:
  - `www.youtube-nocookie.com/embed/<id>`
  - `player.vimeo.com/video/<n>`
  - `docs.google.com/{document|spreadsheets|presentation|forms}/d/[e/]<id>/{preview|embed|pub|pubhtml|viewform}`
  - `drive.google.com/file/d/<id>/preview`

  Any other URL is saved unchanged and shown as a plain link. No column was added.
- The article audience `org` was removed.

### Engage (fork)
- An activity is a batch activity or a platform activity. The whole-organization target and `organization_id` are gone. Managing a batch activity needs `engage.activity.manage` on that batch.
- **SEC-06:**
  - questions stop being answerable once results are published, or once the question has been revealed;
  - a new column `closed_positions` makes "hide" unable to reopen a question;
  - `publish` on a run that is still live returns 409.
- **SEC-07:** the invite limit is 5 per hour and the launch limit 10 per hour, both keyed by activity and user. Invites go only to active batch members.
- **§2.4:** participant labels use the nickname (`display_name`), otherwise `Participant #n`. The full name is never shown.

### Mentoring (D2: the minimal mapping)
- **Admin (`super_admin`, P) performs every mentor duty:** slots, bookings, feedback, no-show handling, resume reviews and notes.
  - Admin slots are platform slots (`organization_id` NULL), open to every learner, including public learners with no batch.
  - An Admin acting as mentor is "assigned" only to the learners who booked them. Notes, the console detail and the readiness view stay limited to those learners. This is the same rule as the former platform mentor.
  - Every Admin sees the shared resume-review queue.
- **Trainer** keeps `mentor.notes.read` at batch scope: they can read the notes of their own batch's learners, but cannot write them.
- **No batch-scoped mentor role remains.** If a role ever gets `mentor.slot.manage` at batch scope, its slots will be stamped `COMPANY_ORG_ID`.
- `SlotsIn.organization_id` (the org picker) was removed, and so was `_slot_orgs`. `assigned_batches` no longer reads organization grants.

### Notifications and media
- `consumers.finance_admin_ids` now returns live Admins (`rbac.catalogue.admin_roles()`), so finance alerts go to Admin.
- Batch announcements already filtered on `status='active'`.
- Media needed no change.

## 2. Migrations (step 7)

| Revision | Depends on | Effect |
|---|---|---|
| `catalog_0003` | `catalog_0002` | `org_only` courses become `private`. The visibility CHECK becomes `ck_courses_visibility` (`public`, `unlisted`, `private`). |
| `paths_0002` | `paths_0001` | Articles with audience `org` move to `batches` with every non-archived batch of that organization; if there is none, they become `draft`. New CHECK `ck_pa_audience` (`batches`, `people`). |
| `engage_0002` | `engage_0001` | Adds `engage_runs.closed_positions`, backfilled from `revealed_positions`. Closes the live runs of org-wide activities, then soft-deletes those activities. Adds `ck_ea_no_org_wide`. |

How the migrations run:
- None of them lists `orgs_0002` in `depends_on`.
- Each data step lifts FORCE RLS and restores it in the same transaction.
- Every `downgrade()` restores the schema only, as the docstrings say.
- `learning_0004` and `notifications_0002` were not needed: neither module had an org-only value or CHECK.
- The remaps were checked on fresh databases only, not on legacy-shaped data.

## 3. Endpoint changes that web phase 2 must follow

| Endpoint | Change |
|---|---|
| `POST /assignments` | `organization_id` is gone (400 `extra_forbidden`). Omit both `batch_id` and `course_id` for a company-wide structured assignment; only Admin or another platform grant may do this. |
| `GET /enrolments`, `GET /progress` | `organization_id` was removed. Use `batch_id`; leave it out for company-wide (platform staff only). |
| `POST /assignment-submissions/{id}/grade` | 409 for structured submissions. Use review and finalize. |
| `POST /assignment-allocations/{id}/extensions` | 403 `conflict_of_interest` for oneself; 422 `not_allocated` for a learner the allocation does not target. |
| `evaluator_ids` (allocate and patch) | Must be evaluators, trainers or company staff; otherwise 422 `not_evaluator`. A named evaluator can now grade that allocation. |
| Evaluation, allocations and regrade queue | For batch graders, filtered to the allocations they may grade. Review and finalize of other submissions return 403. |
| `POST /me/assignments/{id}/tutor` | Stop sending `history`; it is ignored. `limit` is the effective limit, never null. 429 means `rate_limited` or `ai_quota_exceeded`. |
| **New:** `GET /me/assignments/{id}/tutor/history?item_id=` | Returns `{data:[{role, content, created_at}]}`, the learner's own turns. |
| Start, autosave, submit and tutor on archived assignments | 409. |
| `POST /studio/courses` | `organization_id` is gone, and so is visibility `org_only` (400). The course's `organization_id` is set by the server. |
| `POST /mentor/slots` | `organization_id` is gone (400). Admin slots have `organization_id: null`. |
| Paths | `organization_id` was removed from `POST /paths`, `/paths/ai-generate`, `/path-articles` and from the `GET /paths`, `/path-articles` and `/paths/link-options` queries. `GET /paths/context` returns `{can_author, can_allocate_any_learner, batches:[{id,name,code}]}`. `GET /paths/org-members` became `GET /paths/batch-members?batch_id=&q=`, returning `{user_id, full_name, email}`. `PublishIn.audience` is `batches` or `people`. Steps carry `embeddable`; use an iframe only when it is true (SEC-08 sandbox in WS6). |
| Engage | `organization_id` and the "Whole organization" option are gone. "No batch" means a platform activity (Admin or Content manager only). Handle 409 on publish while live, and 429 on launch and invite. |

## 4. Test results (real runs)

Command, from `apps/api`:

```
TD_TEST_DB_NAME=techdrona_ws4 TD_TEST_RESET_DB=1 .venv/Scripts/python -m pytest tests/learning tests/paths tests/engage tests/catalog tests/mentoring tests/notifications tests/media tests/authz -q
```

**Before (baseline):** 117 passed, 18 failed.

**After:** see §4.1. The other checks:
- `ruff check .` passes.
- `ruff format --check` passes on the owned paths.
- `mypy app` passes: no issues in 259 files.

**New regression tests:**
- `tests/learning/test_single_company_sec.py`:
  - SEC-02 (the former probe), with real asserts;
  - `evaluator_ids`;
  - the evaluator grades and releases but gets 403 on authoring;
  - SEC-03 (the former probe): the workspace returns 404 and the coding grant 403 after the learner is removed;
  - SEC-09, SEC-11 and SEC-12;
  - org input rejected.
- `tests/paths/test_paths.py::test_sec01_other_batch_trainer_cannot_touch_batch_allocation` (the former SEC-01 probe), the removed-member test and the D9 unit test.
- In `tests/engage`: SEC-06, SEC-07, nicknames, and the org field rejected.

**Converted tests** (from removed roles to Admin or Trainer):
- the catalog permission test, now about company courses;
- the learning enrolment and progress test, now cross-batch;
- the mentoring suite, with Admin as mentor;
- notifications: Admin finance alerts, and trainer announcements.

### 4.1 Final run
The command was the one above plus `tests/rbac/test_w2a_adm41.py`, on a fresh `techdrona_ws4` (`TD_TEST_RESET_DB=1`).

- **Result:** 151 passed, 1 failed in 4 min 22 s.
  - **The failure:** `tests/paths/test_paths.py::test_ai_generate_draft_and_errors`. The test's fake `generate_path` still required `org_id`, which WS4 no longer passes.
  - **Fix:** the fake's signature was updated. A re-run of `tests/paths` gave **10 passed**.
- **`tests/authz` on its own** (fresh `techdrona_ws4a`): every matrix test passes. The one failure in that run was `test_object_level`, which inserted an `org_only` course. It is fixed (see §5), and the final run above includes it.
- **`tests/learning/test_structured_assignments.py`** was re-run after a SEC-17 assertion was added: **7 passed**.

## 5. Edits outside WS4's folders (requested by the coordinator), and open items

- **`tests/authz/matrix.py`** (WS1): `SCOPE_QUERY` and `fill_query` now send `batch_id` (batch A) instead of `organization_id`. This fixes the 403-instead-of-404 failure that WS2 reported on `GET /enrolments` and `GET /progress`.
- **`tests/authz/test_object_level.py:90`** (WS1): `visibility="org_only"` became `"private"`.
- **`tests/rbac/test_w2a_adm41.py`** (WS1): converted to company courses, without `organization_id` or `org_only`. 3 passed.
- **`tests/_review_scratch/test_sec_paths_probe.py` and `test_probe_structured_sec.py`:** now superseded by the regression tests above. Deleting them was blocked by the tool permission policy, and they now fail because they assert the old, vulnerable behaviour. WS1, which owns `_review_scratch`, should delete them.
- **`tests/ai/test_app_gating.py::test_paths_create_publish_allocate_progress`** (WS3): still sends `organization_id` and uses `coordinator_a`.
- **`tests/placement/world.py`** (WS5): still builds org B. The engage, learning and mentoring suites no longer rely on its `coordinator_a`.
