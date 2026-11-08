# Fixes: secadmin (security, audit, admin, rbac)

Agent key `secadmin`. Owned paths: `apps/api/app/modules/{security,audit,admin,rbac}/**`, their new migrations, `apps/api/tests/{security,audit,admin,rbac,authz}/**`. Test DBs: `techdrona_fix_secadmin`, `_2`, `_3`.

The audit probes reproduced every finding below before the fixes (`tests/_audit_scratch/admin/security`: 7 passed, `superadmin`: 8 passed, on `techdrona_fix_secadmin`). Those probes assert the old buggy behaviour, so the ADM-01/02/03/04/09/13/14/19/20 probes now fail by design.

Probe caveat (ADM-10): the original probe counted rows in `audit_log`. Request-path audits only land in `audit_outbox`, and `audit_log` gets them after sealing, so that count is always 0. The regression test spies on `audit()` instead. The bug was still real: the code audited per-user views only.

## Results

| ID(s) | Severity | Fix summary | Files | Regression test | Result |
|---|---|---|---|---|---|
| ADM-01 | High | An export of a per-user report (H1, H2, H3, H5, H6, H9, H12) now always routes to a second `security_reviewer`, and the `include_per_user_rows` flag can no longer skip approval. Aggregate exports drop identifying columns (`user_id`, `case_ref`, `assignee`, `reference`, `device_id`, session ids). `contains_pii` is set from the columns actually written. ENG exports as metric/value rows instead of an empty file. Export filters are checked up front, so H12 without `user_id` returns 422 before any approval is created. | security/api_engine.py, security/reports.py | tests/security/test_reports_phase_b.py::test_adm01_per_user_export_always_needs_second_reviewer, ::test_adm01_aggregate_export_has_no_identifying_columns | Fixed+tested |
| ADM-02 | High | H8 counts one row per L3/L4 decision. The old DISTINCT over non-unique columns is gone, and each decision adds to a dimension once. Only levels 3 and 4 are counted. | security/reports.py | ::test_adm02_h8_counts_every_decision (3 decisions, 2 FP, 0.667) | Fixed+tested |
| ADM-03 | Medium | H9 counts distinct L3+ cases with a confirmed decision. The interval is measured between the first confirmations of different cases. A `latest_outcome` column is added. | security/reports.py | ::test_adm03_h9_counts_incidents_not_decisions | Fixed+tested |
| ADM-04 | High | H11 is built on the analytics public function `analytics.feeds.get_learning_activity`, not on raw tables. It returns active learners plus engaged and learning minutes per day, week or month, for the platform or one org. Org buckets below `analytics.k_min.cohort` are suppressed. | security/reports.py | ::test_adm04_h11_learning_activity_from_analytics (seeds k learners, plus a small org that is suppressed) | Fixed+tested |
| ADM-05 / INV-11 (backend) | High | New `GET /security/reports/exports` lists the caller's own exports. Each entry has its status (including expired), `row_count`, `contains_pii` and a `download_path` once it can be downloaded. Downloads stay single-principal and audited. The response now has `Content-Disposition: attachment` and `Cache-Control: no-store`. When an approval executes, the requester gets an in-app and email notice (`security.export.ready`). A rejection sends `security.export.rejected`; cancelling your own request sends nothing. | security/api_engine.py, security/controls.py | ::test_adm01_per_user_export_always_needs_second_reviewer, ::test_adm05_rejected_export_notifies_requester | Fixed+tested (the "My exports" UI panel is a web request) |
| ADM-06 (backend) | Medium | Filters now work: `to` (an inclusive IST date) on every report. H1: level, family, org, rule, sla_state, assignee. H3: user_id and rule, window at most 14 days. H5: level, family, org, source. H6: level, state. H7: level, reviewer. H10: tier, client_type. H11: granularity, org. H12 now returns 422 when `user_id` is missing, instead of an empty list. The catalogue lists each report's filters, and responses echo `filters_applied`. | security/reports.py | ::test_adm06_report_filters_are_applied, ::test_h7_review_time_with_k_rows_and_suppression, ::test_inv17_h12_view_and_export | Fixed+tested (filter bar in the UI: web request) |
| ADM-08 | Medium | Partly fixed. H8 adds the alert "a rule contributes more than 3 FP cases in a week" and labels each alert. H10 adds the student sessions-per-user distribution and the count of users at the session cap, both with k-floors. Still missing: the H2 graph (it points to SEC-15), H3 engaged-bucket overlap, the H8 L2 re-verification pass rate and org dimension, and the H10 time series. | security/reports.py | ::test_adm08_h8_weekly_rule_fp_alert, ::test_h10_active_sessions_with_k_rows | Partly fixed; the rest deferred (content scope, no data source for the H10 history) |
| ADM-09 | Low | `from`/`to` keep any offset they carry. A naive date-time or a bare date is read as IST. | security/reports.py | ::test_adm09_from_filter_keeps_offset_and_bare_dates_are_ist | Fixed+tested |
| ADM-10 | Medium | Every H1–H12 and ENG view writes `security.report_viewed`, with the report key, whether it is per-user, and the filters. Per-user views still require a reason code. | security/api_engine.py | ::test_adm10_every_report_view_is_audited, ::test_inv17_h12_view_and_export | Fixed+tested |
| INV-17 | Medium | H12 view and export are tested: 422 without a user, a reason code required, super_admin denied, per-user approval by a second reviewer, and CSV download. | — | ::test_inv17_h12_view_and_export | Fixed+tested |
| H7/H10 k-floor | — | The tests seed `k_min` rows (default 10) so the unsuppressed numbers are checked: median, p90 and SLA % for H7, and active sessions for H10. A k-1 group must come back suppressed. Suppressed H7 and H10 cells now hide the count too (`requests` / `active_sessions` are null). | security/reports.py | ::test_h7_review_time_with_k_rows_and_suppression, ::test_h10_active_sessions_with_k_rows | Fixed+tested |
| ADM-13 | High | `rbac.grant.privileged` and `rbac.revoke.privileged` are registered in the admin approvals registry and share one executor with RBAC-07. They are visible and decidable in `/admin/approvals`. The approver must be a super_admin, not the requester and not the grantee. | rbac/router.py | tests/admin/test_audit_phase_b_fixes.py::test_adm13_* | Fixed+tested |
| ADM-25 (admin side) | Critical | No admin change was needed. The registry (`admin.approvals.register(ApprovalHandler(...))`) already supports per-type approver roles, `check` and `on_reject`. Commerce must register its handlers (see Requests). | — | — | Request to commerce |
| ADM-19 | Low | A grantee approving a grant or revoke on their own account gets `sod_violation`, on both the RBAC-07 and the admin path. | rbac/router.py | test_adm19_* | Fixed+tested |
| ADM-20 | Low | Self-grants are blocked at every scope (`sod_violation`), not only at platform scope. | rbac/router.py | test_adm20_* | Fixed+tested |
| ADM-23 | Low | New `expire_if_due` and `expired_body` helpers save the `expired` status and return 409, instead of raising, which rolled the change back. Used by admin decide, admin cancel and rbac decide. | admin/approvals.py, admin/router.py, rbac/router.py | test_adm23_* | Fixed+tested (commerce copy: Request) |
| ADM-14 | High | Audit list and detail are filtered by role. super_admin sees everything, security_reviewer sees security events, finance_admin sees commerce events, and anyone else sees nothing. Detail outside the allowed set returns 404. Roles other than super_admin and security_reviewer see IPs cut to /24 (IPv4) or /48 (IPv6). | audit/router.py | tests/audit/test_audit_role_filter.py (2 tests) | Fixed+tested |
| ADM-22 (backend) | Low | The dashboard's "Pending approvals" count includes only requests the viewer can decide, excluding their own. | admin/accounts.py | test_adm22_* | Fixed+tested (label and role-list items: web) |
| ADM-17 (backend) | Medium | `flag_enabled` treats a 0 % rollout as off for everyone. Org and user allowlists can already be edited through the PATCH, and a test now covers it. | admin/router.py | test_adm17_* | Fixed+tested (wiring the flags into their consumers: Request) |
| DB-01 | High | New erasure-provider registry `admin.privacy.register_erasure_provider`. The analytics `erase_user` is registered. New `erasure_ledger` table (migration `admin_0003`, append-only, platform-only RLS) stores a SHA-256 subject hash per run. A request is marked `completed` only when every required module's provider has run; otherwise it stays `in_progress` and lists the modules still pending. | admin/privacy.py, admin/models.py, admin/router.py, migrations/versions/admin_0003_erasure_ledger.py | test_db01_* | Fixed+tested (identity, learning, assessments, coding, placement, support and notifications must register providers: Request) |
| ADM-21 / SEC-11 | Low | Not changed. Passkeys are not built, so making break-glass passkey-only would disable it. TOTP stays, as documented in accounts.py. | — | — | Deferred: depends on passkeys (identity) |
| ADM-27 / INV-06 | High | `GET /support/unblock-requests` now returns `request_id`, `case_ref`, `submitted_at` and the active restrictions (id, level, family, `liftable_by_support`), with no evidence fields. Forward (UNB-18) refuses requests that are not open (409) and audits the reason. Support can lift L1/L2 through SEC-21 (the reason is audited); L3/L4 return `decision_required`. | security/api_review.py, security/restrictions.py | tests/security/test_unblock_support_attachments.py::test_support_list_ids_forward_and_lift_l1l2_only | Fixed+tested (support desk buttons: web) |
| INV-12 (UNB-03/16) | Medium | Real presigned S3 POST through the public `media.storage` helpers. At most 2 files per request, each PDF/PNG/JPG up to 5 MB, stored in `unblock_requests.attachments`. Idempotent and audited. The reviewer view returns a 5-minute inline URL, only once the scan is clean, and needs a reason code. | security/unblock.py, api_student.py, api_review.py | ::test_unblock_attachments_upload_and_reviewer_view | Fixed+tested |
| INV-16 (UNB-04/07/13/18) | Medium | New tests cover draft submit, the request-info → student response loop, and forward. | — | ::test_request_info_and_student_response_loop, plus the two tests above | Tested |
| DB-05 | Medium | New migration `security_0002`. On account_restrictions, security_cases, unblock_requests, security_user_state and security_notices it replaces `p_o` with `p_o_read` (SELECT for the owner or platform) and `p_o_write` (writes for platform only). DELETE and TRUNCATE on account_restrictions and security_cases are revoked from td_app. The two request-path writers (the signals sink guard and `restriction_state`) now use `as_system`. | migrations/versions/security_0002_rls_owner_readonly.py, security/signals.py, security/restrictions.py | ::test_db05_learner_cannot_write_own_enforcement_rows | Fixed+tested |
| E2E-01 | High | Follows account-unblock-workflow §4.2/§6.3a. When a lift decision finds no contact verified at least 7 days before the restriction, the request goes to `escalated` (`manual_verification_required`). New `POST /security/restrictions/{id}/manual-verification` (P5 step-up, idempotent; a different reviewer from the decider or approver; refused with 409 while the student can still re-verify by code) runs the shared restore-access procedure. The student's status shows `await_manual_verification` instead of `reverify`. | security/cases.py, unblock.py, api_review.py, api_student.py | tests/security/test_unblock_manual_verification.py (2 tests; contact verified 1 h before, no back-dating) | Fixed+tested |
| E2E-09 | Low | TO-04/TO-08 signal evidence records `expected_ua_family`/`os_family`, and `observed_*` when the resolver passes them. | security/signals.py | ::test_to08_evidence_has_expected_and_observed_ua | Fixed on the security side; resolver change requested |
| DB-02 (security tables) | High | Cannot be done inside security: these tables are append-only or no-delete for td_app. | — | — | Deferred: Request to core/DB |

## Requests

1. **Commerce (ADM-25, ADM-23), `apps/api/app/modules/commerce/`**
   - Register one handler per commerce approval type at import time with `apr.register(apr.ApprovalHandler(action_type, "approval.decide", roles, execute, on_reject=...))`.
     - `roles` is `frozenset({"finance_admin"})` for `commerce.refund`, `commerce.coupon.activate` and `commerce.price.create`, and `frozenset({"super_admin"})` for `commerce.contract.terminate` (check against role matrix §5).
     - `execute(session, principal, req)` calls the existing commerce execute logic for `req.payload` (the same code as `POST /finance/approval-requests/{id}/approve`).
     - `on_reject` moves the target back, for example a `requested` refund to `rejected`.
   - These requests then appear in and can be decided from `/admin/approvals`, which the finance UI already uses.
   - In `commerce/router.py` around lines 1150-1152, replace `req.status = "expired"; raise ...` with `if await apr.expire_if_due(session, req): return <409 invalid_state_transition expired>`.
2. **Erasure providers (DB-01), owners of identity, learning, assessments, coding, placement, support and notifications:**
   - Call `app.modules.admin.privacy.register_erasure_provider("<module>", fn)` at import, where `fn(session, user_id)` is idempotent and returns a summary dict.
   - Identity must tombstone email, phone, name and DOB.
   - Analytics may register its own provider to replace the built-in one.
3. **Flag consumers (ADM-17):** read the flags through `app.modules.admin.router.flag_enabled`.
   - `platform.maintenance_mode`: core middleware.
   - `payments.cashfree_enabled`: commerce.
   - `risk.fingerprint_collection`: sessions and identity.
4. **Web (ADM-05/06/07/INV-11), `apps/web/src/features/security-admin/components/Reports.tsx`:**
   - Add a "My exports" panel that calls `GET security/reports/exports` and downloads from `download_path`.
   - Add a filter bar driven by the catalogue's `filters` list, including `to`, and `user_id` for H3 and H12. H12 now returns a 422 `user_id` error when the user is missing.
   - Render the H11 `granularity` and `scope`, the H10 `student_sessions_per_user` and `students_at_session_cap`, and the labelled H8 `alerts`.
   - The export dialog no longer needs the `include_per_user_rows` checkbox: per-user reports always go to approval.
5. **OpenAPI:** regenerate `apps/api/openapi.json` with `python -m app.scripts.export_openapi`. The new routes are `GET /security/reports/exports` and the fork C routes listed below. Then refresh the web API types.
6. **Orgs (ADM-30), `apps/api/app/modules/orgs/router.py:418,476`:** null the roster `restricted` field when `org.notify_coordinator_on_restriction` forbids it or the caller lacks `security.status.read`, following the `security-summary` logic in `security/api_engine.py` `org_summary`.
7. **Orgs (ADM-16), `orgs/lifecycle.py:155-157`:** set the approver roles to `{"super_admin","finance_admin"}`.
8. **Sessions (E2E-09), `sessions/resolver.py` ~line 160 and the `SecurityEvents` Protocol in `hooks.py`:**
   - Pass `observed={"ua_family": ..., "os_family": ...}` to `sink.replay_blocked`.
   - Add the expected and observed UA/OS fields to the `session.replay_blocked` audit row.
9. **Core/DB (DB-02):**
   - Add a `maint.purge_expired_rows` SECURITY DEFINER function, executable only by `td_maintenance`, plus a maintenance job. It should purge:
     - `security_signals` and `risk_evaluations` older than 180 days, unless held by an open case;
     - closed cases with their notes, decisions, restrictions and requests 1 year after closure (3 years if disputed).
   - Add an S3 lifecycle rule for `uploads/unblock_request/*`.
10. **Media (INV-12):**
    - The GuardDuty `apply_scan_result` consumer must update `unblock_requests.attachments[*].scan_status` for keys under `uploads/unblock_request/`.
    - EXIF stripping is not implemented.
    - The 5/h attachment rate limit is not enforced.

## Test commands and results

All from `apps/api`.

- Probes before the fix: `TD_TEST_DB_NAME=techdrona_fix_secadmin TD_TEST_RESET_DB=1 .venv/Scripts/python -m pytest tests/_audit_scratch/admin/security tests/_audit_scratch/admin/superadmin -q -s`: 15 passed (bugs reproduced).
- `TD_TEST_DB_NAME=techdrona_fix_secadmin .venv/Scripts/python -m pytest tests/security/test_reports_phase_b.py -q`: 13 passed.
- `TD_TEST_DB_NAME=techdrona_fix_secadmin .venv/Scripts/python -m pytest tests/security tests/authz tests/analytics/test_exports.py -q`: 113 passed, 1 failed. The failure is `test_scn_sessions.py::test_scn09c` (`security_user_state` StaleDataError), which came from fork C's in-progress DB-05 RLS migration. Fork C fixed it; see the final run below.
- Fork B: `TD_TEST_DB_NAME=techdrona_fix_secadmin_2 .venv/Scripts/python -m pytest tests/admin tests/rbac tests/audit tests/authz tests/security/test_controls_reports.py tests/security/test_case_pending_approval.py tests/orgs -q`: 108 passed.
- `ruff check app/modules/security app/modules/admin app/modules/rbac app/modules/audit tests/security tests/admin tests/audit`: passed. `ruff format --check`: clean.
- `mypy app/modules/security/reports.py app/modules/security/api_engine.py app/modules/security/controls.py`: no issues. `mypy app/modules/admin app/modules/rbac app/modules/audit`: 1 error, in `app/modules/analytics/hooks.py:109`, which we did not touch.
- Fork C final (`techdrona_fix_secadmin_3`): `pytest tests/security tests/sessions`: 109 passed, 0 failed. This includes scn09c, fixed by moving the request-path writers to `as_system`. The new unblock test files: 7 passed. `ruff` and `mypy` on security: clean.
