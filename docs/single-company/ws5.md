# WS5: Assessment, practice and operations

| | |
|---|---|
| Status | Done. Ready for WS6 phase 2 and for WS1's `orgs_0003` merge. |
| Date | 2026-11-07 |
| Plan | `REMOVAL-PLAN.md` §1.2 (assessments, placement, coding, analytics, support, security, audit), §5 step 8, §6 WS5, §8 (D2, D3, D5, D8) |
| Scope | `app/modules/{assessments,placement,coding,analytics,support,security,audit}/**`, the WS5 seeds, their migrations, `tests/{assessments,placement,coding,analytics,support,security,audit}/**` |
| Dev DB | Not touched. Runs used the scratch databases `techdrona_ws5`, `techdrona_ws5a` and `techdrona_ws5b`. |

## 1. What changed

### Assessments
- **Removed:** `GET /studio/assignable-tests?organization_id` (COL-007, college assigns tests).
- **Assigning a test:**
  - `AssignmentCreate.batch_id` is now required.
  - `organization_id` is no longer accepted (400 `validation_failed`). The "whole organization" target is gone.
  - Admin assigns at platform scope (D3); a Trainer assigns to their own batch.
- **Creating a test:** `TestCreate.organization_id` is accepted only as `null` (a platform test) or `COMPANY_ORG_ID`. Any other id returns 404. Batch trainers still send `batch_id`.
- **Evaluator read access** (for the grading screens in web phase 2), through the new `studio.can_read_test`:
  - `GET /studio/tests/{id}` is read-only for holders of `test.results.read` on any of: the test's owning batch, its organization, platform scope, or a batch the test is assigned to.
  - `GET /studio/tests` also lists those tests.
  - Writes still need `test.edit` or `test.create`.
- **App toggle:** the `require_app_enabled(..., app_key="assessments")` calls no longer pass `org_id`.
- **SEC-10:**
  - Grading an item (`POST /attempts/{id}/items/{qv}/grade`) on one's own attempt returns 403 `conflict_of_interest`.
  - The same applies to an integrity decision (`POST /attempts/{id}/integrity-decision`) and to invalidation (`POST /attempts/{id}/invalidate`).
  - Reading the evaluation screen is unchanged.
- **SEC-13:** connectivity events (`focus_gained`, `disconnect`, `reconnect`) have their own cap, `exam.MAX_CONNECTIVITY_EVENTS_PER_ATTEMPT = 300`. Events over the cap are ignored and counted in `ignored_events`. The cap of 500 recordable events is unchanged.

### Placement and question banks
- **Owner of new content** (new `placement.policies.resolve_owner` and `company_owner`):
  - Bodies may still send `organization_id`, but only `null` or the company org. Any other id returns 404.
  - When it is omitted, a caller who holds the permission at platform scope creates platform content. A batch trainer gets the company bank automatically, so the web can drop its org pickers.
  - This covers question create, company paths, bank create, import, generate and media upload. The `GET /studio/question-banks?organization_id=` filter is validated the same way.
- **SEC-04:** `GET /question-media/{id}` is strictly read-only. It serves the image only when the row is already `clean`/`ready`; otherwise it returns 404, never 500. It no longer asks the scanner.
  - New sweep job `placement.media_scan_sweep` (`app/modules/placement/tasks.py`, every 120 s, system context) resolves pending question images.
  - The `_review_scratch` probe is now `tests/placement/test_ws5_security.py::test_sec04_learner_get_pending_platform_media_is_404_not_500`.
- **SEC-18:** a `clean` scan result is accepted only after the presigned-POST window has closed (`created_at + MAX_PRESIGN_SECONDS + 30 s`). An `infected` result is accepted at once and is never undone.
  - `POST /studio/question-media/{id}/complete` and the sweep both apply this rule.
  - The media JSON gains `clean_not_before` while the image is pending.
  - This replaces ETag pinning, which would need an object-store HEAD call in the media module (WS4).
- **SEC-16:**
  - A company bank accepts a platform question only when it is `active` and has a `current_version_id`; otherwise the request gets 400 `validation_failed` (field code `not_found`).
  - In a company bank, platform rows always show their **published** version, never the newest draft.
- **SEC-19:** `require_app_enabled(session, app_key="question_banks")` now runs in `_bank_for`, which covers get, patch, delete, list questions, add, remove and import into a bank. It also runs in the bank list, resolve, create, import, generate and media upload.

### Coding
- `service.submission_org` is simplified. An in-test submission is attributed to the attempt's organization, an org-private problem to the problem's organization, and a company member to `COMPANY_ORG_ID`. A public learner gets `NULL`. The "most recently joined of several orgs" rule is gone.

### Support (sub-fork B)
- **Removed:**
  - the `college_access` category and the organization lane
  - the `organization_id` field on new tickets (sending it returns 400 `validation_failed`)
  - `organization_id` from ticket responses
- Admin (`super_admin`) handles every category (D2). Content managers keep content, assessment and certificate.
- **D8, the corporate enquiry backend:** see §3.

### Analytics (sub-fork B)
- **Removed:**
  - `OrgReader`
  - `/analytics/reports/orgs/{id}` and `/analytics/reports/orgs/{id}/students/{uid}` (both now 404)
  - the org drill-down in `reports.py`
  - the coordinator exports, the `organization` export scope, the org rollups (`entity_kind='organization'`) in the time model and the daily and weekly jobs, the org cohort cells, and the org filter on the feed
- **Renamed:** the export `coordinator.batch_progress` is now `batch.progress`.
- **Batch reports** (`GET /analytics/reports/batches/{id}`) work for:
  - Admin
  - a Trainer, with `analytics.read` on the batch
  - an Evaluator, with `progress.read` on the batch or at platform scope
- **Behaviour change:** batch reports now count all of a student's activity, not only the activity attributed to the organization.

### Security and audit (sub-fork A)
- **Removed endpoints (D5):**
  - `GET /security/trusted-networks`
  - `POST /security/trusted-networks/{id}/decision`
  - `GET` and `POST /orgs/{org_id}/trusted-networks`
  - `GET /orgs/{org_id}/security-summary`, along with the coordinator notification
  - the `organization_id` filter on reports H1, H5 and H11 and on the bulk-lift selector
- **Risk engine:** the trusted-network discounts, the lab-device signals and the AB-11 signal are gone.
  - AB-11 stays in the catalogue marked "Retired", so historic signals still render.
  - Nothing reads `Device.shared_organization_id` any more, so WS1 can delete the shim.
- **Renamed:** the unblock reason `college_lab_or_shared_computer` is now `shared_computer`, and the info template `lab_details` is now `shared_computer_details`. Device lists no longer return a `lab` field.
- **Approvals (D2):** every former reviewer, finance or support role reference now points to Admin. Dual control means maker ≠ checker, so the second approver is a different admin.
- **Audit:**
  - Only Admin reads the log, with full IPs.
  - The `org_trusted_network` and contract target types were removed.
  - The generic organization filter is kept.
- **Same-org conflict check:** removed. With one company it would have blocked every admin from reviewing batch students' cases.

## 2. Migrations

None of these lists `orgs_0002` (or any cross-branch revision) in `depends_on`.

| Revision | Revises | Effect |
|---|---|---|
| `security_0003_single_company` | `security_0002` | Drops `org_trusted_networks`. Remaps `unblock_requests.what_happened` from `college_lab_or_shared_computer` to `shared_computer`, lifting FORCE RLS only for that statement. Downgrade restores the table schema (CHECKs, indexes, trigger, RLS family T) and the reason value, but not the rows. |
| `support_0004_single_company` | `support_0003` | Remaps `college_access` tickets to `other`, keeping the old value in `context.legacy_category`, and tightens the CHECK. Ticket and message RLS becomes "own rows or platform staff", because the organization branch would let batch students read each other's tickets. Creates `corporate_enquiries` with FORCE RLS, platform only: the app may insert, select and update, but not delete. |
| `analytics_0003_single_company` | `analytics_0002` | Deletes org daily and weekly rows, org cohort cells and org export jobs. Renames `coordinator.batch_progress` jobs and tightens the CHECKs. On the 7 per-user analytics tables and on `export_jobs`, the organization branch of RLS now also requires the caller to be **staff** of that organization (new function `app.analytics_staff_org_ids()`), so batch students cannot read each other's rows. |
| `assessments_*`, `placement_*`, `coding_*` | none | No schema change is needed. Re-homing the data is WS1's `orgs_0003`. Existing `test_assignments` rows without a batch stay readable. |

## 3. Endpoints for web phase 2

**Corporate enquiries (D8):**
- **`POST /api/v1/public/enquiries`** (no sign-in; on the support router, so `main.py` is unchanged):
  - Body: `{name 2-100, company 2-150, email ≤254, phone? ≤20, message 10-4000, consent: true, website?}`. Unknown fields are rejected (400 `validation_failed`).
  - `website` is a honeypot. If it is filled, the response is the same 202 but nothing is stored.
  - Success is 202 `{"status":"received"}`.
  - Errors:
    - 400 `validation_failed`, with codes `consent_required`, `invalid_email` and `invalid_mobile`
    - 429 after 5 per hour or 20 per day from one IP, or 3 per day for one email address
  - No personal data appears in errors, logs or audit records.
  - Every Admin gets an in-app notification and an email that contains only the enquiry reference.
- **`GET /api/v1/support/enquiries?status=new|in_progress|closed|spam&cursor&limit`** (Admin; `user.read` at P):
  - Returns `{data:[{enquiry_id, reference, name, company, email, phone, status, assigned_to, created_at, updated_at, closed_at, message_preview}], page, counts:{new}}`.
- **`GET /api/v1/support/enquiries/{id}`:** the full record, adding `message`, `staff_note`, `consent_at` and `notice_version`. Every view is audited.
- **`PATCH /api/v1/support/enquiries/{id}`:** body `{status?, assign_to_me?, staff_note?}`. Also needs `ticket.assign`.

**Analytics:**
- `GET /api/v1/analytics/reports/batches/{id}`: Admin, Trainer or Evaluator, as in §1. The response no longer includes `organization_id`.
- Export report keys: `batch.progress`, `content.course_usage` and `platform.overview`. Scope types: `platform`, `batch` and `course`.

**Studio and grading** (the evaluator reuses the trainer screens):
- `GET /studio/tests` and `GET /studio/tests/{id}`: read-only for evaluators.
- Unchanged: `GET /tests/{id}/attempts`, `GET /attempts/{id}/evaluation`, `POST /attempts/{id}/items/{qv}/grade`, `POST /tests/{id}/results/release` (D3) and `GET /integrity/flags`.

**Request and response changes:**
- `POST /tests/{id}/assignments` requires `batch_id` and no longer accepts `organization_id`.
- Question and bank create bodies may omit `organization_id`; the server picks the owner.
- The question-media JSON gains `clean_not_before`.
- **Removed:** `/studio/assignable-tests`, `/analytics/reports/orgs/**`, the trusted-network routes and `/orgs/{id}/security-summary`. The unblock reason is renamed to `shared_computer`.

## 4. Test results (real runs)

Commands are run from `apps/api`. Every run started from a fresh database (`TD_TEST_RESET_DB=1`, `alembic upgrade heads`).

- **The full WS5 command:**

  ```
  TD_TEST_DB_NAME=techdrona_ws5 TD_TEST_RESET_DB=1 .venv/Scripts/python -m pytest tests/assessments tests/placement tests/coding tests/analytics tests/support tests/security tests/audit tests/authz -q
  ```

  - Run 1: **401 passed, 1 failed**. The failure was `support/test_w2b_fixes.py::test_ticket_links_own_attempt_only`. It passed when re-run alone, in `tests/support`, and in `tests/analytics tests/support`, so it is an order-dependent flake.
  - Run 2: **402 passed** in 8 min 13 s.
- **Sub-fork runs:**
  - `tests/security tests/audit` on `techdrona_ws5a`: 123 passed.
  - `tests/support tests/analytics tests/authz` on `techdrona_ws5b`: 116 passed.
- **Static checks:**
  - `ruff check .` passes.
  - `ruff format --check .` passes (512 files).
  - `mypy app` passes: no issues in 259 source files.
- **String check:** `rg -i "college|coordinator|finance_admin|support_agent|security_reviewer|placement_mentor|trusted_network"` over the 7 WS5 modules and the 4 WS5 seeds finds no matches.
- **New regression tests:**
  - `tests/placement/test_ws5_security.py`: SEC-04 (the former probe), SEC-16, SEC-18, SEC-19, and a foreign `organization_id` returning 404.
  - `tests/assessments/test_ws5_security.py`: SEC-10, SEC-13, and evaluator read-only access to studio tests.
  - `tests/support/test_enquiries.py`: D8 validation, the honeypot, rate limits, consent, Admin-only access and no PII in errors.
- **Converted tests:**
  - The coordinator persona in `tests/placement/world.py` became `admin` (`super_admin` at P) plus `evaluator_a` (batch A), and org A is `COMPANY_ORG_ID`.
  - The assignable-tests test became a "route is gone" check.
  - The coding attribution tests now use the company org.
  - The mentor persona became a batch trainer.

## 5. Left for other workstreams

- **WS1:**
  - Delete `tests/_review_scratch/test_sec_aq_probe.py`. Its SEC-04 probe asserts the old 307 on a pending image and is now `tests/placement/test_ws5_security.py`. Its cross-org bank probe creates a bank in org B, which now returns 404.
  - Delete the `Device.shared_organization_id` shim.
  - Consider granting the Evaluator `analytics.read` at batch scope; today evaluators read batch reports through `progress.read`.
  - Review RLS family `U`: any company-org member can read org-attributed rows in other modules. Analytics and support fixed this locally.
- **WS1 (`orgs_0003`):** `tests/placement/world.py` keeps a DEPRECATED second org ("B") only for the cross-tenant suites, including `tests/authz`. When `orgs_0003` lands, move B to a second company batch. The same applies to `tests/coding/test_authoring_gaps.py`, which uses `make_org`.
- **WS3:** delete `risk.trusted_network_multiplier` in `admin/policy.py`; nothing reads it now.
- **WS4:** `media.service.sweep_pending_scans` does not cover `question_media`. The placement module has its own sweep job instead.
- **WS6:**
  - Remove the trusted-networks page and the "Lab device" column in `EvidenceTabs.tsx`.
  - Use the template key `shared_computer_details`.
  - Remove `/studio/assignable-tests` from the API client.
  - Build the `/enquiries` page and the Admin enquiry queue.
