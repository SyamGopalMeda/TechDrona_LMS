# QA report — backend (Stage 10 final verification)

| Field | Value |
|---|---|
| Date | 2026-11-03 |
| Owner | QA & Security Testing (backend) |
| Scope | `apps/api/**`, root `.env.example` |
| Environment | Local Docker Compose (Postgres + Redis), Windows, Python 3.13, fresh DB `techdrona_test_qa` (`TD_TEST_RESET_DB=1`) for every full run |

## 1. Summary

| Check | Result |
|---|---|
| Full suite, run 1 (fresh DB) | **540 passed**, 0 failed, 0 skipped (14 min 35 s) |
| Full suite, run 2 (fresh DB) | **540 passed**, 0 failed, 0 skipped (9 min 34 s) |
| Flakiness across the 2 runs | none (every test passed in both runs, from the JUnit XML) |
| `ruff check .` / `ruff format --check .` | clean / 364 files formatted |
| `mypy` (package `app`) | `Success: no issues found in 211 source files` |
| Authorisation matrix (TS-AUTHZ) | 427 authenticated routes x 15 principals = **6,405 requests per run, 0 violations, 0 x 5xx** |
| Object-level cross-tenant probe | **312 probes**, 0 x 2xx, 0 x 5xx, 0 leaks |
| Owner scenarios SCN-01..20 | **20/20 covered and passing** (table in §4) |

The baseline before this work was 516 passed. The 24 new tests are 16 for the authz matrix, 1 object-level, 1 SCN-02, 5 security regression and 1 for the learning submission endpoint.

## 2. Authorisation matrix suite (`apps/api/tests/authz/`)

### 2.1 How it is generated

`tests/authz/matrix.py` builds the cases from two sources. Nothing is written by hand per route.

* **Route table.** `iter_api_routes(create_app())` gives every non-public route with its method, path, `x-td-route-tag` and the *static* permissions declared through `require_permission(...)` dependencies (`td_permission`).
* **Role catalogue.** `app.modules.rbac.catalogue.permissions_for_role` is generated from `role-permission-matrix.md` §2/§3/§5. It is the same source that seeds `role_permissions`.

**Principals (15).** Each one is a real `users` row with an `auth_sessions` row and an org membership. Each is resolved by the `FakeAuth` resolver and checked by the **real** `RbacPermissionChecker`, with step-up fresh and MFA set so that freshness never masks a permission decision.

* `anonymous`
* `no_grants`
* the 9 canonical roles at their default scope:
  * student @org A
  * college_coordinator @org A
  * trainer @batch A
  * content_manager @P
  * placement_mentor @batch A
  * support_agent @P
  * security_reviewer @P
  * finance_admin @P
  * super_admin @P
* `restricted_l3` (scope `restricted`)
* `status_only_l4` (scope `status_only`)
* `other_coordinator` @org B
* `other_trainer` @batch B

**Path binding.** `org_id` and `batch_id` are bound to org A and batch A. LRN-22 `/enrolments` and LRN-24 `/progress` get `?organization_id=<org A>`. Other ids are fresh UUIDs, and write requests carry `{}` and an `Idempotency-Key`.

**Expected outcomes, computed per (route, principal):**

| Rule | Assertion |
|---|---|
| Every principal | never `5xx` (an unhandled exception also counts as a failure) |
| `anonymous` | `401` on every non-public route |
| L3 / L4 | `403 account_restricted` exactly on the tags the scope forbids (`default`; plus `l3_readonly` for L4). Never on the allowed tags. |
| Static-permission routes (180) | **Holders** (the role holds the permission *and* the grant scope covers the target chain) are never refused with `permission_denied` for that permission. **Non-holders** get `403 permission_denied`, or `404 not_found` when they belong to another tenant (TI-02). |
| Other-tenant principals | never `2xx` on an org-A-scoped route. No `2xx` body contains an org-A identifier (org, batch, users). |
| In-handler routes (247) | student and no-grant principals never get `2xx` on a staff surface (`/admin`, `/finance`, `/studio`, `/security/*` console, `/mentor`, `/orgs/*`, `/tests/*`, `/assignments`, …) |
| Route coverage | `test_every_authenticated_route_has_generated_cases`: a route with no cases fails the suite |

### 2.2 Coverage numbers (identical in both runs)

| Metric | Value |
|---|---|
| Authenticated routes (method + path) | 427 |
| Routes with a static permission (exact matrix check) | 180 |
| Routes with in-handler checks (heuristic and tenant checks) | 247 |
| Requests per run | 6,405 (427 x 15) |
| Status classes | 2xx 810, 4xx 5,595, 5xx **0** |
| Violations | **0** |

The object-level probe is `tests/authz/test_object_level.py`. It creates real org-A objects: a batch, an assignment with a learner submission, an org-private question, an org-private published test with a running attempt, an org-private course and a learner `user_id`. Org-B coordinator, trainer and learner then call every route whose path parameters can all be bound to those objects. That is **312 probes**, with no `2xx`, no `5xx` and no org-A identifier echoed in an error body.

### 2.3 Intentional exceptions (`EXCEPTIONS` in `test_authz_matrix.py`)

| Route | Reason |
|---|---|
| `GET /admin/approvals` | Requester/approver-scoped list. Rows are filtered to requests the caller raised or may decide (`apr.can_approve`), so a learner gets `200` with an empty list and never sees other users' rows. |
| `POST /orgs/{org_id}/suspend`, `/reactivate` | `org.suspend` is platform-only (super_admin @P) and is checked at platform scope. Every org-scoped principal gets a uniform `403` for any org id, own or foreign, so there is no existence oracle. TI-02's 404 rule is about org-scoped permissions. |

Rules built into the generator (not exceptions):

* `login_continuation` routes may answer `401` to a fully signed-in session, because they need a pending login. They run last because they can end the session.
* A holder refused with a *different* permission named in the problem body is an extra in-handler check. Example: GST export download also needs `report.export.request`.

### 2.4 Authorisation bugs found

**No authorisation defect was found** by the matrix or the object-level probe. Two harness problems were found and fixed in the test code only:

* `GET /me` needs `request.state.auth_session_id`, which the real resolver sets. The test resolver now sets it too.
* LRN-22 and LRN-24 take their scope from a required query parameter, so the generator now supplies it.

## 3. Fixes and changes made

| # | Area | Change | Test |
|---|---|---|---|
| F1 | security, sessions | Hard-coded `/auth/forgot` (disown response) and `/auth/recover` (`account_protect_locked`) replaced by the real web route `web_path("forgot_password")` → `/forgot-password`. An absolute `recovery_link` (`WEB_BASE_URL` + path) was added. `recovery_url` stays relative because the web client only accepts paths starting with `/`. | full suite (security/sessions tests) |
| F2 | media | SigV4 helpers are now public API: `storage._signing_key` → `signing_key` and `_bucket_url` → `bucket_url`. The only external caller, `analytics/export_store.py`, was updated. | analytics export tests |
| F3 | learning | New **`GET /assignment-submissions/{submission_id}`** (`lrn_16a_get_submission`, `l3_readonly`, idle `neutral`). The owner gets their own submission, with grade fields only after release (as LRN-09). Staff need `assignment.grade` @B/@C on the assignment's scope (as LRN-16). Everyone else, including other tenants, gets `404`. `apps/api/openapi.json` was regenerated (+1 path). | `tests/learning/test_stage10_endpoints.py::test_get_submission_by_id_owner_staff_and_others` |
| F4 | `.env.example` | Added `WEB_BASE_URL`, `TD_EXPORT_STORE`, `TD_EXPORT_FAKE_DIR`, `TD_EXPORTS_SEND_TASKS` and `TD_CODING_SEND_TASKS`. These are all env vars read by the code that were missing from the example. | — |
| F5 | flaky test | `tests/commerce/test_documents_plan_change.py::test_rate_limits_quote_and_webhook_never_drops_valid_events` used `203.0.113.{random % 250}` as the webhook source IP. The patched per-IP rule is a **day** window kept in Redis, so a later run that reused one of the ~250 addresses got `429` on the first forged delivery instead of `400`. Redis held 8 such keys from earlier runs that day, about a 3 % chance per run and growing. It now uses a random `2001:db8::/32` address with 96 random bits. | same test; 12 repeated runs green |

## 4. Owner scenarios SCN-01..20

Each test id is a file in `apps/api/tests` followed by the test name. "P/P" means it passed in run 1 and in run 2.

| SCN | Scenario | Test ids | Result |
|---|---|---|---|
| 01 | Laptop, then phone | `security/test_scn_sharing::test_scn01_laptop_then_phone_daily_overlap_scores_l0` | P/P |
| 02 | Several tabs, same laptop | **new** `security/test_scn02_tabs::test_scn02_many_tabs_one_session_concurrent_requests_and_in_session_takeover`; `media/test_media::test_stream_cap_conflict_takeover_and_heartbeats`; `assessments/test_attempts::test_autosave_idempotent_and_order_safe`; `analytics/test_timemodel::test_example1_overlapping_windows_union_not_sum`, `::test_union_invariant_random_multi_tab` | P/P |
| 03 | Same college Wi-Fi | `security/test_scn_sessions::test_scn03_campus_wifi_many_students_no_lockout_no_signals` | P/P |
| 04 | Wi-Fi to mobile data | `security/test_scn_sessions::test_scn04_network_change_keeps_session_and_ua_family_change_is_to08` | P/P |
| 05 | Two unrelated devices concurrently | `security/test_scn_sharing::test_scn05a_relayed_otp_sharer_l1_l2_then_l3`, `::test_scn05a2_two_days_l2_only_and_5c_mobile_sharer_under_detected` | P/P |
| 06 | Many accounts, one device | `security/test_scn_sharing::test_scn06_shared_pc_lab_pc_minor_and_restricted_device_reuse` | P/P |
| 07 | Geo-inconsistent | `security/test_scn_sharing::test_scn07_geo_inconsistent_broadband_sh10_only_and_mobile_excluded`, `::test_scn07_first_login_outside_india_is_to09_notice_only` | P/P |
| 08 | VPN | `security/test_scn_sharing::test_scn08_vpn_student_capped_and_tor_adds_takeover_only`; `security/test_rules_unit::test_separation_classes` | P/P |
| 09 | High-confidence auto-restriction | `security/test_scn_sessions::test_scn09c_stuffing_source_then_failed_otp_is_hct2_protect_lock`; `security/test_scn_sharing::test_scn09c_deferral_keeps_attempt_session`, `::test_scn09d_…`, `::test_scn09e_…`, `::test_scn09f_…`, `::test_scn09h_…`, `::test_scn09i_…`, `::test_cb03_…`, `::test_cb06_…` | P/P |
| 10 | Unblock request | `security/test_scn_unblock::test_scn10_unblock_request_validation_limits_and_device_revocation`, `::test_scn10_rate_limits_three_per_30_days_and_form_loads` | P/P |
| 11 | Approve and revoke sessions | `security/test_scn_unblock::test_scn11_review_lift_reverify_and_fresh_login`, `::test_scn11_high_risk_l4_needs_distinct_second_approver`, `::test_scn11_send_back_withdraw_and_72h_expiry` | P/P |
| 12 | Reject with reason | `security/test_scn_unblock::test_scn12_reject_appeal_to_different_reviewer_and_final`, `::test_scn12_rejection_then_auto_expiry_reverify_closes_moot`, `::test_scn12_no_appeal_in_14_days_closes_rejected_final` | P/P |
| 13 | Blocked user, direct API | `security/test_scn_sessions::test_scn13_l3_and_l4_principals_get_403_on_every_non_allowed_route`, `::test_scn13_l3_entitlement_locks_and_cache_column`; `authz/test_authz_matrix::test_authz_matrix[restricted_l3]`, `[status_only_l4]` | P/P |
| 14 | Repeated payment webhook | `commerce/test_checkout_webhooks::test_scn14_same_webhook_delivered_repeatedly_is_processed_once` | P/P |
| 15 | Inactive tab for hours | `security/test_scn_sessions::test_scn15_idle_session_expires_and_background_poll_does_not_extend`; `analytics/test_timemodel::test_example2_tab_left_open_for_hours_no_credit_beyond_idle` | P/P |
| 16 | Browser crash during a test | `security/test_scn_sessions::test_scn16b_relogin_same_device_replaces_old_session`; `assessments/test_attempts::test_crash_resume_same_device_reattaches_without_rebind`; `analytics/test_timemodel::test_example3_crash_closes_at_last_sample_plus_grace` | P/P |
| 17 | Tabs used to manipulate time | `security/test_scn_sessions::test_scn17_time_manipulation_is_integrity_only`; `analytics/test_timemodel::test_union_invariant_random_multi_tab` (25 seeds) | P/P |
| 18 | Admin reads another institution | `security/test_scn_sessions::test_scn18_cross_org_access_404_and_ab09_alert`; `authz/test_authz_matrix[other_coordinator]`, `[other_trainer]`; `authz/test_object_level::test_org_b_principals_never_reach_org_a_objects` | P/P |
| 19 | Altered or revoked session id | `security/test_scn_sessions::test_scn19_altered_revoked_and_replayed_tokens`, `::test_scn19_drift_and_minor_replay_is_deterministic`, `::test_scn19_unknown_token_flood_ab07_throttles_source` | P/P |
| 20 | False-positive dispute | `security/test_scn_unblock::test_scn20_false_positive_exception_suppression_and_credit`, `::test_scn20_variant_fp_override_of_recommend_l4_needs_second_approval` | P/P |

### SCN-02 additions

The new test runs on a **committed** database, so the tabs' requests run genuinely concurrently, each on its own pooled connection. All tabs share one session cookie and one device cookie through the real resolver and login stack. It checks the following:

* 3 tabs load at once.
* Tab A starts playback and tab C starts playback. Tab C gets `201`, not `409`: the stream is taken over inside the session.
* Heartbeats are sent concurrently from A and from C (twice). A gets `410 playback_revoked end_reason=taken_over` and C gets `200`.
* Bursts of 5 and 7 tabs all return `200`.
* Afterwards there is exactly **1 active session**, **1 user device**, **0 `security_signals`** and **0 `media.stream_cap*` outbox events**, and tab A's playback row ended `taken_over`.

**Not covered in the backend:** the analytics "more than 6 page instances" flag for 7 tabs and the BroadcastChannel banner. The flag is analytics/web-side and the banner is web-only.

## 5. Security regression checks

The new file is `tests/security/test_security_regression.py`. The remaining checks are existing tests, which were re-run in both full runs.

| Check | Test | Result |
|---|---|---|
| No secrets in logs. Login, new-device email OTP, TOTP MFA, forgot/reset password, a wrong password and logout run while stdout/stderr (fd level) and every `logging` record at DEBUG are captured. The test asserts that no password, OTP, TOTP code, reset token, or session/device/pending-session cookie value appears. | `test_no_secrets_tokens_or_otps_in_logs_during_auth_flows` | P/P |
| Session token and reset token stored hashed only (`token_hash == sha256(token)`; the raw value appears in no column) | `test_session_and_reset_tokens_are_stored_hashed_only` (+ existing device-key HMAC test in sessions) | P/P |
| Cookie flags with the production setting: `__Host-` prefix, `Secure`, `HttpOnly`, `SameSite=Lax`, `Path=/`, no `Domain`; logout clears with `Max-Age=0` | `test_cookie_flags` | P/P |
| OTP send limit: `otp_send_limited` with `Retry-After` after 10 per hour per destination, and a refused send emails nothing. Wrong-code lockout is covered by `sessions/test_sessions_and_devices::test_otp_attempts_exceeded`. | `test_otp_send_and_verify_are_rate_limited` | P/P |
| Login rate limits: per-IP pre-auth window gives `429 throttled` with `Retry-After`; per-account back-off and hard stop are covered by `identity/test_login_and_passwords` | `test_login_rate_limit_per_source_ip` | P/P |
| Webhook invalid signature gives `400` and is logged | `commerce/test_checkout_webhooks::test_invalid_signature_is_400_and_logged` | P/P |
| Hidden test cases are never in responses | `coding/test_flow::test_submit_judges_all_cases_hidden_are_verdict_only`, `::test_other_users_submission_is_404_staff_sees_source_not_hidden` | P/P |
| Answer keys hidden before review | `assessments/test_attempts::test_delivery_schemas_have_no_key_fields`, `::test_start_returns_layout_without_keys_and_binds_session`, `::test_scoring_with_negative_marking_and_review_phases` | P/P |

## 6. Flakiness

* The 2 full runs on fresh DBs gave identical results: 540/540 both times, with no test whose result differed.
* The two reported flaky files (`tests/admin/test_accounts.py` and `tests/commerce/test_documents_plan_change.py`) were also run **12 more times in a loop: 12/12 green** (15 tests each time).
* **commerce:** root cause found and fixed (F5: a Redis day-window per-IP counter collided with a reused random IP).
* **admin `test_deactivate_and_reactivate…`:** **not reproduced** in 14 executions (12 loop runs + 2 full runs). Its login back-off, step-up window and TOTP step handling were reviewed and none is timing-dependent; for example, a deactivated-account login is recorded as `locked`, which does not feed the back-off. The most likely cause of the single reported failure is environmental: several agents shared the default `techdrona_test` database, and a parallel `TD_TEST_RESET_DB=1` drops it. **Recommendation:** always set `TD_TEST_DB_NAME` per agent or CI shard. This is now done for the QA runs.

## 7. Remaining risks and limitations

1. **The matrix uses the test session resolver** (with the real RBAC checker). Gates of the real resolver are covered by the sessions and security suites, not by the matrix. These are L2 device verification, pending login states, MFA enrolment and missing consents.
2. **In-handler permission checks (247 routes)** are checked only for:
   * no `5xx`
   * no learner `2xx` on staff surfaces
   * no cross-tenant `2xx` or leak
   * object-level binding for 9 object types

   The exact role-by-role outcome on these routes is not computed from the catalogue.
3. **Some §2.5 dimensions are not generated yet:**
   * multi-role principals
   * expired, revoked or changed-since-login grants
   * stale step-up per sensitivity class
   * sibling-batch and org-private-course relations
   * SoD and Dual-control named cases (some exist in the rbac, admin and security suites)
4. **Request bodies are `{}`,** so the matrix exercises the authorisation layer, not deep handler logic.
5. **Dev cookies:** `.env` / `.env.example` set `TD_COOKIE_SECURE=false`, but `__Host-` cookies require `Secure` in browsers. Production is protected because the startup check refuses `TD_COOKIE_SECURE=false`.
6. **The SCN-02 test commits rows** (one user, course and session) to the test DB. That is harmless with a fresh DB per run, but it is not rolled back.
7. **Not run here:** CI gates G-02 (coverage thresholds), G-09..G-13 (SAST/SCA/secret scanning) and the TS-RLS catalogue checks beyond `tests/core/test_rls.py`.
