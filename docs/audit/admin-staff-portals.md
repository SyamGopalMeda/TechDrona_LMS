# Audit: Admin panel and staff portals (area `admin`, prefix `ADM-`)

Phase A (audit only). Auditor: admin-area agent, 2026-11-03. Scope: `/admin` (super admin), `/security` (security console, reports H1–H12, kill switch, exports, approvals), `/desk` (support), `/finance`, `/studio` (content), `/trainer`, `/college` (coordinator), `/mentor`, and the backend routers they call.

Method: CodeGraph and code tracing (web page → `api.*` call → BFF pass-through `apps/web/src/app/api/v1/[...path]/route.ts` → FastAPI route, permission dependency, scoping, audit). Route existence was checked against `apps/api/openapi.json`; every path the security console calls exists with the matching method. Pytest probes were run on dedicated databases only. Each probe asserts the observed (buggy) behaviour, so a pass means the finding reproduced:

| Probe dir (`apps/api/tests/_audit_scratch/admin/…`) | DB (`TD_TEST_DB_NAME`) | Result |
|---|---|---|
| `security/test_adm_security_reports_probe.py` | `techdrona_audit_admin` | 7 passed |
| `superadmin/test_superadmin_probes.py` | `techdrona_audit_admin_super` | 8 passed |
| `studio/test_studio_trainer_probes.py` | `techdrona_audit_admin_studio` | 5 passed |
| `ops/test_ops_refund_overpay.py`, `test_ops_coupon_dual_bypass.py` (fail on purpose, showing the bug), `test_ops_commerce_approvals_queue.py` | `techdrona_audit_admin_ops` | bugs reproduced |

Run command (from `apps/api`): `TD_TEST_DB_NAME=<db> TD_TEST_RESET_DB=1 .venv/Scripts/python -m pytest tests/_audit_scratch/admin/<dir> -q -s`

## 1. Coverage inventory

| Feature/Req ID | Requirement source | Code location | Audit method | Result |
|---|---|---|---|---|
| SEC-001 dashboard (queue counts, engine state, report links) | sitemap §SEC-001 | features/security-admin/components/SecurityDashboard.tsx, EngineControls.tsx | code trace | Verified OK |
| SEC-002/003 case queue, detail, claim/assign, notes, explanation, timeline, concurrency, device graph | sitemap SEC-002/003 | CaseQueue.tsx, CaseDetail.tsx, EvidenceTabs.tsx → security/cases/* | code trace, openapi | Verified OK; "Previous incidents" card is a placeholder (part of ADM-11) |
| Case decision dual control (SoD-06) | account-unblock-workflow, RE §5 | security/cases.py:285-360, 628-660 (requester ≠ approver, applier ≠ approver, conflict check, payload hash) | code read + existing tests/security/test_case_pending_approval.py | Verified OK |
| SEC-004 unblock review queue (claim, request-info, escalate, send-back) | sitemap SEC-004 | UnblockReviewQueue.tsx, EvidenceTabs.tsx → security/review/unblock-requests/* | code trace | Verified OK |
| SEC-005 restrictions: manual apply/lift, bulk false-positive lift | RE §5.8 | Restrictions.tsx → security/restrictions*, bulk-lift-requests | code trace + existing tests | Verified OK. There is no UI for the bulk-lift status GET (Low, folded into ADM-11) |
| SEC-006 rule versions, simulate, shadow, activation/rollback | RE §5.4 | RuleVersions.tsx → security/rule-versions/* | code trace | Verified OK |
| Kill switch + 24 h ratification | RE §5.7 | api_engine.py:241 (perm `security.engine.kill_switch`, P5 step-up, idempotent); controls.py:693 handler `risk.kill_switch.ratify` | code trace | Verified OK |
| Security approvals queue | RE §10 | app/security/approvals/page.tsx → ApprovalsQueue (admin/approvals) | code trace | Issue: no payload shown (ADM-15) |
| H1 Top suspicious accounts | src-req §H; RE §10 | security/reports.py `_h1` | code read | Issue: filters ignored, second tab not rendered (ADM-06, ADM-07) |
| H2 Multiple-account/device associations | RE §10 | `_h2` | code read | Partial: platform list only (ADM-08) |
| H3 Concurrent login events | RE §10 | `_h3` | code read | Partial: no user or date-range filter (ADM-06, ADM-08) |
| H4 Repeated IP/device associations | RE §10 | `_h4` | code read | Partial: k-floor applied; `flagged_sources` not rendered (ADM-07) |
| H5 Blocked accounts | RE §10 | `_h5` | probe | Rows correct; per-user export bypasses second approver (ADM-01) |
| H6 Pending unblock requests | RE §10 | `_h6` | code read | Verified OK; counts not rendered (ADM-07) |
| H7 Average review time | RE §10 | `_h7` | code read | Verified OK (median, p90, SLA %, k-floor); the "reviewer" filter is missing (ADM-06) |
| H8 False-positive rate | RE §10 | `_h8` | **probe** | **Issue: wrong numbers (ADM-02)** |
| H9 Repeat incidents | RE §10 | `_h9` | **probe** | **Issue: counts decisions, not incidents (ADM-03)** |
| H10 Active-session counts | RE §10 | `_h10` | code read + probe | Partial (ADM-08); view not audited (ADM-10) |
| H11 Learning activity | RE §10 | `_h11` | probe | **Not built (ADM-04)** |
| H12 Device and login history | RE §10 | `_h12` | probe | Report page always empty (ADM-06); timeline on the case page works |
| ENG engine health | RE §10 | `_eng` | code read | Data is in `extra`, not rendered on the report page (ADM-07) |
| Report access control | RE §10 | api_engine.py:321-352 | existing test + code | Verified OK: per-user needs `security.evidence.read` + reason code + audit; super_admin aggregate only; support 403 |
| Report exports (P5, approval, watermark, download) | RE §10, API I-26 | api_engine.py:355-453, controls.py:717-735 | probe | Issues ADM-01, ADM-05 |
| Trusted-network verification queue, incidents | API SEC trusted-networks/incidents | api_engine.py:456-705 | grep of web | No security-console UI (ADM-11) |
| Super admin panel (ADM-001..012) | sitemap, matrix §5 | features/admin/*, modules/admin, rbac, audit, orgs | code + 8 probes | See ADM-13..23. Requester self-approval is refused on every path; MFA reset, break-glass and policy SoD OK; the audit log is append-only and hash-chained |
| Portal guards (8 staff portals) | matrix §1.6 | components/shell/PortalShell.tsx, middleware.ts | code + probe | Issue Low (ADM-12). The backend returns 403 for users with no grants |
| Finance FIN-001..009 | sitemap FIN-* | features/finance/*, commerce/router.py | code + probes | ADM-24..28, 31, 32, 37, 39, 40 |
| Support desk SUP-001..005 | sitemap SUP-* | features/support/SupportDesk.tsx, support/router.py, security/api_review.py | code | Ticket and user lookup OK: masking, reason codes, audit, 30-day device-reset quota server-side, no evidence shown, no answer keys. Unblock triage dead (ADM-27); ADM-38 |
| Mentor MEN-001..005 | sitemap MEN-* | features/mentor/*, mentoring/service.py, placement/mentoring.py | code | Verified OK: mentor_id == caller, assignment-scoped, note reads audited. Readiness missing (ADM-35) |
| College coordinator COL-001..013 | sitemap COL-* | features/college/*, orgs/router.py, entitlements, analytics | code + existing BOLA test (`tests/authz/test_object_level.py`, 1 passed) | Cross-tenant GETs OK. Issues ADM-29, 30, 33..36 |
| Studio CMS-001..013 | sitemap CMS-* | features/studio/*, catalog, placement, coding, assessments | code + probes | ADM-41, 44..46, 48, 50..52, 54, 55, 57. Coding hidden cases and answer keys are protected (Verified OK) |
| Trainer TRN-001..012 | PRD §6.7 | features/trainer/*, assessments/studio.py, learning/router.py | code + probes | ADM-41..43, 47, 49, 53, 56 |
| Mock / hard-coded data in production paths | brief | all staff features and app dirs | grep (mock, sample, dummy, TODO, lorem, FIXME, hard-coded arrays) | Verified OK. Unbuilt screens use the honest `NotImplemented` component. Hard-coded role list noted in ADM-22 |

## 2. Issues

### Security console and Section H reports

### ADM-01: A per-user security report can be exported without the second security reviewer
- Severity: High
- Status: Confirmed
- Component:
  - apps/api/app/modules/security/api_engine.py:364 sets `per_user = REPORTS[k]["per_user"] and body.include_per_user_rows`. Line 401 then renders immediately when that is false.
  - security/reports.py:574 `render_export` writes the full `rows`. It never strips per-user columns.
  - Endpoint: `POST /security/reports/{report_key}/exports`.
- Requirement: RE §10 "an export of a security/monitoring report with per-user rows (H1–H9, H12…) is approved by a second `security_reviewer`"; source-req §H "exportable only by authorised users".
- Repro: `test_aggregate_export_of_per_user_report_bypasses_second_approver`. Export H5 (blocked-accounts) with `include_per_user_rows=false`, then download it.
- Expected: either an aggregate-only CSV (counts by level/source, no user ids), or the request routes to approval.
- Actual: the export completes at once, with no approval and `contains_pii=false`, and the CSV has a `user_id` column.
- Evidence: `EXPORT 202 {'status': 'completed', 'approval_request_id': None, 'contains_pii': False}`; `CSV 200 header: case_ref,deferred_until,ends_at,family,level,organization_id,scope,since,source,user_id | contains subject user_id: True`
- Root cause: the client-chosen flag decides whether approval is needed. Reports have no aggregate projection.
- Recommended fix (minimal): for `REPORTS[k]["per_user"]` keys, either always require approval, or render an aggregate projection when `include_per_user_rows` is false (drop `user_id`, `case_ref` and `assignee`; group counts). Set `contains_pii` from the actual columns.
- Suggested owner paths: apps/api/app/modules/security/api_engine.py, apps/api/app/modules/security/reports.py

### ADM-02: H8 false-positive rate undercounts because identical decisions are collapsed
- Severity: High
- Status: Confirmed
- Component: security/reports.py:375-420 `_h8`. The select of `(outcome, ruleset_version, hc_rule, rule_keys)` is followed by `.distinct()` (line 389), with no case or decision id.
- Requirement: RE §10 H8 "share of L3 and L4 decisions concluded `lift_false_positive`… Alert when L3 FP rate > 10 %".
- Repro: `test_h8_false_positive_rate_collapses_identical_decisions`. Three engine L3 cases on ruleset `sharing-audit-1`, rule SH-01: two decided `lift_false_positive`, one `uphold`.
- Expected: decisions=3, false_positives=2, fp_rate=0.667.
- Actual: decisions=2, false_positives=1, fp_rate=0.5.
- Evidence: `H8_ROWS [{'dimension': 'ruleset', 'key': 'sharing-audit-1', 'decisions': 2, 'false_positives': 1, 'fp_rate': 0.5}]`
- Root cause: DISTINCT over non-unique columns merges different decisions. In production every engine decision on the same ruleset has the same tuple, so the counts are capped at about one per outcome and rule-key set. The FP rate and the >10 % alert are meaningless.
- Recommended fix: select `CaseDecision.id` (or distinct on `(CaseDecision.id, AccountRestriction.id)`), or drop `.distinct()` and join to the restriction that the decision acted on. Also filter `level IN (3,4)`. Add a numeric regression test.
- Suggested owner paths: apps/api/app/modules/security/reports.py, apps/api/tests/security/test_controls_reports.py

### ADM-03: H9 repeat incidents counts decisions, not incidents
- Severity: Medium
- Status: Confirmed
- Component: security/reports.py:425-455 `_h9` uses `func.count()` over `case_decisions` joined to cases, `HAVING count >= 2`.
- Requirement: RE §10 H9 "Users with ≥ 2 confirmed L3+ within 180 days; time between incidents; outcome".
- Repro: `test_h9_repeat_incidents_counts_decisions_not_incidents`. One user has one L3 case with two confirmed decisions (`uphold`, then `convert_L4`).
- Expected: the user is not listed, because there is one incident.
- Actual: the user is listed with `confirmed_incidents: 2`.
- Evidence: `H9_ROWS [{'user_id': '01a1a210-…', 'confirmed_incidents': 2, 'first': '2026-10-31…', 'last': '2026-11-02…', 'interval_days': 2.0}]`
- Root cause: counts rows, not `DISTINCT SecurityCase.id`. The "outcome" column is also missing.
- Recommended fix: `func.count(func.distinct(SecurityCase.id))`, take the interval from the per-case first confirmation, and add the latest outcome.
- Suggested owner paths: apps/api/app/modules/security/reports.py

### ADM-04: H11 "Daily/weekly/monthly learning activity" is not built
- Severity: High
- Status: Confirmed
- Component: security/reports.py:477-484 `_h11` returns `[]` with `available: False`.
- Requirement: source-req §H item 11 (verbatim); RE §10 H11 (DAU/WAU/MAU and engaged minutes by platform and org, with k-floors).
- Repro: `test_h11_learning_activity_not_built`
- Evidence: `H11 {'rows': [], 'available': False, 'note': 'Learning-activity aggregates are provided by the analytics module (not yet available).'}`. The web page shows "No rows for this period".
- Recommended fix: implement it from `daily_learning_aggregates` / `weekly_learning_aggregates` (or `analytics.feeds.get_activity_summary`), with day/week/month buckets and k-floor suppression for org views.
- Suggested owner paths: apps/api/app/modules/security/reports.py, apps/api/app/modules/analytics/

### ADM-05: Completed security exports cannot be downloaded or listed from the UI, and no one is notified
- Severity: High
- Status: Confirmed (code and grep)
- Component:
  - apps/web/src/features/security-admin/components/Reports.tsx:150 says "You will be notified when the file is ready", but nothing calls `GET /security/reports/exports/{export_job_id}`; grep of apps/web/src finds no caller.
  - There is no list-my-exports endpoint.
  - controls.py `_execute_export` (≈line 660-680) renders the file but sends no notification.
  - The job id is shown only once, in a transient status line.
- Requirement: RE §10 "CSV exports… watermarked… audited"; source-req §H "exportable only by authorised users".
- Expected / Actual: after approval or completion the requester can download the CSV. Actually the export workflow dead-ends in the UI; the file is reachable only by a hand-crafted API call within 24 h.
- Recommended fix: add `GET /security/reports/exports?mine=1` (or reuse the analytics `exports` list) and a "My exports" panel with a download button. Notify the requester when approval executes.
- Suggested owner paths: apps/api/app/modules/security/api_engine.py, controls.py, apps/web/src/features/security-admin/components/Reports.tsx

### ADM-06: Report filters are ignored, and the H12 report page can never show data
- Severity: Medium
- Status: Confirmed
- Component:
  - security/reports.py `run_report` (line 74) reads only `from`. The period always ends "now".
  - `_h1` ignores level, family, org, rule, SLA and assignee.
  - `_h3` has no user filter and no ≤ 14-day range.
  - `_h5` has no level, org or source filter.
  - `_h7` has no reviewer filter.
  - `_h10` has no tier, org or period filter.
  - `_h12` needs `user_id`, but the web ReportView (Reports.tsx:58, 119) sends only `from` and `reason_code`.
- Requirement: RE §10 table "Filters" column.
- Repro: `test_h12_report_requires_user_filter_web_never_sends`. Evidence: `H12 [] user_id filter required`.
- Recommended fix: implement the documented filters in the runners. Add a filter bar per report, including user id for H12/H3 and a "to" date.
- Suggested owner paths: apps/api/app/modules/security/reports.py, apps/web/src/features/security-admin/components/Reports.tsx

### ADM-07: Report page renders only `rows`, so ENG, H8 alerts and other secondary data are invisible
- Severity: Medium
- Status: Confirmed (code)
- Component: Reports.tsx:62-90 builds the table from `res.data.rows` only. Data the runners return outside `rows` is never shown:
  - ENG `_eng` returns `rows: []` with everything in extra fields, so its page always says "No rows".
  - H1 `highest_scores_without_case` (the doc's second tab).
  - H6 `counts`.
  - H8 `circuit_breakers` and `alerts`.
  - H4 `flagged_sources`.
- Requirement: RE §10 (H1 second tab, H8 alert and breaker state, ENG view).
- Recommended fix: per-report renderers for these extra fields, or have the runners return them as additional row sets.
- Suggested owner paths: apps/web/src/features/security-admin/components/Reports.tsx

### ADM-08: H2, H3, H8 and H10 implement only part of the RE §10 content
- Severity: Medium
- Status: Confirmed (code)
- Component: security/reports.py
  - `_h2`: platform list only. The per-user device↔account graph lives at `security/users/{id}/device-graph`, which is fine, but the H2 page has none of it.
  - `_h3`: a list of signals, max 500. No engaged-bucket overlap from `analytics.feeds.get_engaged_buckets`.
  - `_h8`: no L2 re-verification pass rate, no bulk-lift counts, no "rule contributes > 3 FP cases in a week" alert, no org dimension.
  - `_h10`: "now" only. No over-time series, no sessions-per-user distribution, no "users at session cap".
- Requirement: RE §10 table "Content" column.
- Recommended fix: complete the aggregates listed in RE §10, or record the reduced scope in docs/implementation-status.md.
- Suggested owner paths: apps/api/app/modules/security/reports.py

### ADM-09: The report `from` filter drops the timezone offset
- Severity: Low
- Status: Confirmed
- Component: security/reports.py:77, `datetime.fromisoformat(frm).replace(tzinfo=now.tzinfo)`.
- Repro: `test_from_filter_ignores_ist_offset`. Evidence: `PERIOD {'from': '2026-10-01T00:00:00.000Z', …}` for input `2026-10-01T00:00:00+05:30`; expected `2026-09-30T18:30Z`. A bare date (what the web sends) is read as UTC midnight, not IST, although the response says `timezone: Asia/Kolkata`.
- Recommended fix: if the value is naive, attach IST; if it has an offset, use `astimezone(UTC)`.
- Suggested owner paths: apps/api/app/modules/security/reports.py

### ADM-10: Opening aggregate Section H reports is not audited
- Severity: Medium
- Status: Confirmed
- Component: api_engine.py:342-351 audits `security.report_viewed` only when `per_user` is true.
- Requirement: source-req §H "All reports must be permission-controlled, auditable and exportable only by authorised users". (RE §10 requires audit only for per-user views, so the docs conflict; the owner's verbatim text is wider.)
- Repro: `test_aggregate_h10_view_is_not_audited`. Evidence: `H10 200 audit rows before/after 0 0`.
- Recommended fix: audit every report view, without a reason code for aggregate views, or record a decision in an ADR.
- Suggested owner paths: apps/api/app/modules/security/api_engine.py

### ADM-11: Security console has no UI for trusted-network verification, incidents or bulk-lift status
- Severity: Medium
- Status: Confirmed (grep)
- Component:
  - No web caller of `GET /security/trusted-networks` or `POST /security/trusted-networks/{id}/decision` (perm `security.network.verify`). Only the college side (TrustedNetworks.tsx) proposes networks, so coordinator proposals can never be verified from the UI.
  - No caller of `/security/incidents` (GET/POST/PATCH) or `GET /security/restrictions/bulk-lift-requests/{id}`.
  - EvidenceTabs.tsx:485-487 shows "Previous incidents: Not available yet".
- Requirement: API spec trusted-network and incident endpoints; RE §4 / org trusted networks (H4 "prompt coordinator registration").
- Recommended fix: add `/security/networks` and `/security/incidents` screens, and a bulk-lift status panel in Restrictions.tsx.
- Suggested owner paths: apps/web/src/app/security/*, apps/web/src/features/security-admin/components/

### Cross-cutting

### ADM-12: Staff portals are not restricted by role in the web (UX only)
- Severity: Low
- Status: Confirmed (code). The backend is fine (probe).
- Component: apps/web/src/components/shell/PortalShell.tsx:16-18 and middleware.ts only check that a session cookie exists. `PortalDef.roles` (lib/nav/portals.ts) is unused, there is no portal switcher, and the `portals` field of `/me/grants` is ignored.
- Requirement: role-permission-matrix §1.6 and lines 418-419 (portal landing per role).
- Evidence: `test_sup_plain_user_cannot_call_admin_apis`: every admin/audit/rbac GET returns 403 for a user with no grants. A student can still load the /admin, /studio and /trainer shells and nav, and sees error states.
- Recommended fix: fetch `me/grants` server-side in PortalShell and redirect when the portal is not in `portals`; add a switcher.
- Suggested owner paths: apps/web/src/components/shell/PortalShell.tsx, apps/web/src/middleware.ts

### Super admin (/admin)

### ADM-13: Privileged role grant or revoke requests cannot be approved from the admin UI
- Severity: High
- Status: Confirmed
- Component:
  - rbac/router.py:240 and :307 create `rbac.grant.privileged` / `rbac.revoke.privileged`, but no `ApprovalHandler` is registered for them.
  - admin/approvals.py:97-106 `can_approve` is False and :133 decide returns 404.
  - The web never calls RBAC-07.
  - ApprovalsQueue.tsx:41 uses the label key `rbac.grant`, which matches nothing.
- Requirement: matrix §5 (granting SA/SEC/FIN is Dual, approved by another super_admin); FR-ADM-004.
- Repro: `test_sup_privileged_grant_invisible_and_undecidable_in_admin_queue`
- Evidence: `requester sees: True | approver sees: False`; `ADM-14 approve: 404 not_found`; `RBAC-07 approve: 200 executed` (API only).
- Expected / Actual: the second super admin approves from /admin/approvals. Actually the request stays pending until it expires at 72 h.
- Recommended fix: register handlers for both `rbac.*` types, reusing the `_decide` execute logic (approver super_admin, approver ≠ grantee). Fix the label key.
- Suggested owner paths: apps/api/app/modules/rbac/router.py, apps/web/src/features/admin/components/ApprovalsQueue.tsx

### ADM-14: Audit log is not filtered by role, so finance_admin reads security events with full IP
- Severity: High
- Status: Confirmed
- Component: apps/api/app/modules/audit/router.py:35-90 `list_events` and :93-99 `get_event` require only `audit.read`, with no role filter.
- Requirement: API AUD-01 (api-specification.md:2226) "filtered by role (security events for security_reviewer, commerce events for finance_admin)"; matrix §3; SoD-01 (finance cannot read security evidence or IP history).
- Repro: `test_sup_finance_admin_reads_security_audit_events`
- Evidence: `finance rows: [('security.probe.m01a1a206da87', 'security_case')]`, `detail ip present: True`.
- Recommended fix: map roles to allowed action and target families in both the list and the detail endpoint, returning 404 outside the allowed set.
- Suggested owner paths: apps/api/app/modules/audit/router.py

### ADM-15: Approvers decide without seeing the payload (admin and security approval queues)
- Severity: Medium
- Status: Confirmed
- Component: ApprovalsQueue.tsx:76 loads only `GET admin/approvals`; admin/approvals.py:65-84 `approval_out` omits the payload; `GET admin/approvals/{id}` is never called. This also affects /security/approvals (export, bulk lift, kill-switch ratify).
- Requirement: FR-ADM-004 ("payload diff").
- Repro: `test_sup_approval_list_has_no_payload`. The list keys are `action_type, approval_request_id, created_at, decided_at, decided_by, decision_note, expires_at, request_reason, requested_by, required_approver_role, status, target_id, target_type`, with no payload.
- Recommended fix: fetch the detail on expand or approve, and render the payload or diff.
- Suggested owner paths: apps/web/src/features/admin/components/ApprovalsQueue.tsx

### ADM-16: finance_admin cannot approve org suspension
- Severity: Medium
- Status: Confirmed
- Component: apps/api/app/modules/orgs/lifecycle.py:155-157 registers approver roles `{"super_admin"}` only.
- Requirement: matrix §5 "Suspend organization — approver finance_admin or second super_admin".
- Repro: `test_sup_org_suspend_finance_admin_cannot_approve`. Evidence: `finance sees: False | approve: 403 permission_denied`.
- Recommended fix: set the approver roles to `{"super_admin","finance_admin"}`.
- Suggested owner paths: apps/api/app/modules/orgs/lifecycle.py

### ADM-17: Feature flags have no effect, and allowlists cannot be edited
- Severity: Medium
- Status: Confirmed (code and grep)
- Component:
  - admin/router.py:292 defines `flag_enabled()`, but nothing calls it.
  - The seeded keys `platform.maintenance_mode`, `payments.cashfree_enabled` and `risk.fingerprint_collection` are not read anywhere in apps/api/app.
  - Governance.tsx:179 PATCHes only `is_enabled` and `rollout_percent`; the org and user allowlists cannot be edited.
  - At a 0 % rollout the flag returns True for anonymous users and False for signed-in users (lines 302-303).
- Requirement: FR-ADM-003.
- Recommended fix: wire the flag consumers, add allowlist editing, and fix the 0 % branch.
- Suggested owner paths: apps/api/app/modules/admin/router.py, apps/web/src/features/admin/components/Governance.tsx

### ADM-18: ADM-011 notification templates page is not built
- Severity: Medium
- Status: Confirmed
- Component: apps/web/src/app/admin/notifications/page.tsx renders `<NotImplemented screen="ADM-011">` but is linked in the nav.
- Requirement: sitemap ADM-011.
- Recommended fix: build the page, or remove it from the nav and mark it Planned.
- Suggested owner paths: apps/web/src/app/admin/notifications/, lib/nav/portals.ts

### ADM-19: The grantee can approve their own privileged grant
- Severity: Low (open in non-production only)
- Status: Confirmed
- Component: rbac/router.py:351-354 checks only requester ≠ approver.
- Repro: `test_sup_grantee_can_approve_own_privileged_grant`. Evidence: `grantee self-approve: 200 {'status': 'executed', …}`. In production `check_sod` (rbac/service.py:296-300) blocks the super_admin + SEC/FIN combination.
- Recommended fix: reject with `sod_violation` when `payload.user_id == principal.user_id`.
- Suggested owner paths: apps/api/app/modules/rbac/router.py

### ADM-20: A coordinator can grant themselves trainer at their own batch
- Severity: Low
- Status: Confirmed (behaviour). Whether it breaches policy is Suspected: the docs are silent.
- Component: rbac/router.py:231 blocks self-grants only at platform scope.
- Repro: `test_sup_coordinator_self_grants_trainer` → `201 {… 'session_effect': 'grantee_sessions_rotated'}`.
- Recommended fix: block all self-grants, or route them to approval.
- Suggested owner paths: apps/api/app/modules/rbac/router.py

### ADM-21: Break-glass step-up accepts TOTP, but the docs require passkey only
- Severity: Low
- Status: Confirmed (code)
- Component: admin/accounts.py:12-13 documents the deviation; :53-62 `p5` accepts any fresh step-up.
- Requirement: matrix §5 "Activate break-glass: passkey only"; FR-ADM-005.
- Recommended fix: once passkeys ship, enforce the passkey method; until then, record the deviation in implementation-status.
- Suggested owner paths: apps/api/app/modules/admin/accounts.py

### ADM-22: Small admin console drift
- Severity: Low
- Status: Confirmed
- Component:
  - Governance.tsx:16 hard-codes `ROLES` instead of calling `GET rbac/roles`.
  - Governance.tsx:113 has the Revoke dialog reuse the Grant form's `reason` state.
  - accounts.py:173-180: the dashboard "Pending approvals" count includes types the viewer cannot decide.
  - ApprovalsQueue.tsx:34-47 has stale label keys.
- Recommended fix: use the API role list, give the Revoke dialog its own state, count only actionable approvals, and align the labels.
- Suggested owner paths: apps/web/src/features/admin/components/Governance.tsx, ApprovalsQueue.tsx, apps/api/app/modules/admin/accounts.py

### ADM-23: An expired privileged-grant decision may lose its "expired" status
- Severity: Low
- Status: Suspected (not reproduced)
- Component: rbac/router.py:348-350 sets `req.status="expired"` and then raises `ProblemError`, so a rollback may discard the change. The same pattern is in admin/approvals.py:123-125 and commerce/router.py:1150-1152. The job `expire_stale_approvals` eventually covers this.
- Recommended fix: commit before raising, or return a 409 without raising.
- Suggested owner paths: apps/api/app/modules/rbac/router.py, admin/approvals.py, commerce/router.py

### Finance (/finance)

### ADM-24: A refund decision can refund more than was paid
- Severity: Critical
- Status: Confirmed
- Component:
  - apps/api/app/modules/commerce/router.py:752-757 `_decide_refund` (`POST /finance/refunds/{id}/decision`).
  - service.py:1170-1175 `create_refund_request`.
  - service.py:1207-1248 `execute_refund` has no cap.
- Requirement: FR-COM-008; refund ≤ refundable (`refund_eligibility.refundable_paise`, service.py:1120).
- Repro: `ops/test_ops_refund_overpay.py`. Buy ₹3,499, refund 100000 paise (settled), then approve a second refund of `amount_paise=349900`.
- Expected / Actual: 422. Actually 200 `processing`.
- Evidence: `ELIG after first {… 'refundable_paise': 249900}`; `DECIDE2 200 processing 349900`; `ORDER_TOTAL 349900 REFUNDED_SUM 449900 CREDIT_NOTES_SUM 449900`.
- Root cause: the only check is `amount_paise > o.total_paise`, which ignores prior refunds. The UI check (Finance.tsx:196) is client-side only.
- Recommended fix: cap at `elig["refundable_paise"]`; for goodwill refunds, cap at `total - already_refunded`. Add a defensive assert in `execute_refund` and `issue_credit_note`.
- Suggested owner paths: apps/api/app/modules/commerce/router.py, service.py

### ADM-25: Commerce dual-control requests cannot be decided from any UI
- Severity: Critical (core finance workflow dead in the UI)
- Status: Confirmed
- Component:
  - Affected requests: refunds over ₹25k or goodwill, coupon activation, price create, contract termination.
  - Finance.tsx:45 uses ApprovalsQueue (`admin/approvals`), but commerce types are not registered in the admin registry; billing_approvals.py:56-67 registers only `commerce.gst_export`.
  - The working `POST /finance/approval-requests/{id}/approve` (commerce/router.py:1190) has no web caller.
  - Finance.tsx:155-161 hides Decide on "Awaiting second approver".
- Requirement: sitemap ⇄ markers on FIN-002/003/005/008; matrix `approval.decide`.
- Repro: `ops/test_ops_commerce_approvals_queue.py`
- Evidence: `CREATE 202 paused`; `LIST 200 visible_to_second_finance_admin= False`; `ADMIN_APPROVE 404 not_found`; `FIN_APPROVE 200 executed`.
- Recommended fix: register `ApprovalHandler`s for the commerce types, delegating to the commerce execute logic, or point the finance UI at `/finance/approval-requests/*` with a list endpoint. This is the same root cause as ADM-13: two approval mechanisms.
- Suggested owner paths: apps/api/app/modules/commerce/billing_approvals.py, apps/web/src/features/finance/components/Finance.tsx, ApprovalsQueue.tsx

### ADM-26: Coupon PATCH `max_redemptions: null` makes a coupon unlimited without dual approval
- Severity: High
- Status: Confirmed
- Component: commerce/router.py:624-657. The loosening check `(c.max_redemptions or 0) < (upd["max_redemptions"] or 0)` treats None as 0.
- Requirement: COM-26 / FIN-003 "⇄ (> 50 % or > 1,000 redemptions)"; `coupon_needs_dual` treats None as needing Dual.
- Repro: `ops/test_ops_coupon_dual_bypass.py`. Evidence: `CREATE 201 active 100`, then `PATCH 200 active None`.
- Recommended fix: treat None as loosening, or reject null in `CouponPatchIn`.
- Suggested owner paths: apps/api/app/modules/commerce/router.py, schemas.py

### ADM-28: Finance screens FIN-002 products, FIN-003 coupons and FIN-006 subscriptions are not built
- Severity: High
- Status: Confirmed
- Component: apps/web/src/app/finance/{products,coupons,subscriptions}/page.tsx render `NotImplemented`. The backend exists (commerce/router.py:439-653, 861-904).
- Requirement: sitemap.md:224-228.
- Note: coupon create returns 202 with `status:"paused"`, not `approval_pending`, so `api/client.ts:184` will treat it as ok. Handle this when building the screen.
- Suggested owner paths: apps/web/src/app/finance/*, apps/web/src/features/finance/components/

### ADM-31: FIN-001 "Revenue dashboard" shows no revenue
- Severity: Medium
- Status: Confirmed
- Component: Finance.tsx:22-47 says "no aggregate endpoint is specified", but `GET /finance/reports/revenue` exists (commerce/router.py:1120).
- Recommended fix: render gross, GST, refunds and net.
- Suggested owner paths: apps/web/src/features/finance/components/Finance.tsx

### ADM-32: Finance lists cannot page past the first page
- Severity: Medium
- Status: Confirmed (code)
- Component: commerce/router.py:65-66 `_list` → `page_meta(None, limit)` always returns `has_more: False`. Orders show 50, invoices 100, contracts and subscriptions 200. Refunds are unbounded, with an N+1 eligibility query per row. The invoice type filter (Finance.tsx:231-233) is client-side.
- Recommended fix: keyset cursors and server-side filters.
- Suggested owner paths: apps/api/app/modules/commerce/router.py, Finance.tsx

### ADM-37: Order detail is a raw JSON dump
- Severity: Low
- Status: Confirmed
- Component: Finance.tsx:93-97 (`JsonBlock`). Masking is correct.
- Recommended fix: a structured view.

### ADM-39: Contract creation takes raw org and product UUIDs
- Severity: Low
- Status: Confirmed
- Component: Finance.tsx:463-464.
- Recommended fix: org and product pickers.

### ADM-40: Reconciliation "To" date is excluded
- Severity: Low
- Status: Confirmed (code)
- Component: Finance.tsx:312, 350. `range_to` is sent as 00:00 IST of the selected day.
- Recommended fix: send the next day, or relabel the field.

### Support desk (/desk)

### ADM-27: Support unblock triage is read-only: support cannot lift L1/L2 or forward L3/L4
- Severity: High
- Status: Confirmed (code)
- Component:
  - SupportDesk.tsx:703-718 says "Lift and forward are not available yet".
  - security/api_review.py:945-966 `support_list` returns only `reference/state/level/route`, with no `request_id`.
  - `POST /support/unblock-requests/{id}/forward` (:969) exists but cannot be reached.
- Requirement: sitemap SUP-005; account-unblock-workflow.md:267; `security.restriction.lift_l1l2` = SUP P.
- Recommended fix: add `request_id` and a restriction id to `support_list`, then add Forward and Lift actions.
- Suggested owner paths: apps/api/app/modules/security/api_review.py, apps/web/src/features/support/components/SupportDesk.tsx

### ADM-38: Ticket queue sorts by due date only within each page
- Severity: Low
- Status: Confirmed (code)
- Component: support/router.py `queue` pages by id, then sorts in memory.
- Recommended fix: order the SQL by `(resolution_due_at, id)`.

### College coordinator (/college) and mentor (/mentor)

### ADM-29: COL-009 student profile, COL-010 shortlists and COL-012 staff are not built
- Severity: High
- Status: Confirmed
- Component: apps/web/src/app/college/{students/[user_id],shortlists,staff}/page.tsx render `NotImplemented`. The backend exists (`/analytics/reports/orgs/{org}/students/{user}`, `/orgs/{org}/members/{user}`, rbac org-staff grants).
- Requirement: sitemap.md:171, 177, 179.
- Suggested owner paths: apps/web/src/app/college/*, apps/web/src/features/college/components/

### ADM-30: The roster shows restriction status whatever the org's visibility policy
- Severity: Medium
- Status: Confirmed (code; the policy=`none` case was not run)
- Component: orgs/router.py:418 and :476 (`"restricted": level >= 4`), shown at Students.tsx. The roster is gated by `org.member.read`, not `security.status.read`. `security-summary` (api_engine.py:597-603) does honour the policy.
- Requirement: api-specification.md:992 / I-23; matrix line 399 (`org.notify_coordinator_on_restriction`).
- Recommended fix: look up the policy and null the field when it is forbidden or when the caller lacks `security.status.read`.
- Suggested owner paths: apps/api/app/modules/orgs/router.py

### ADM-33: Coordinator roster is silently truncated at 1,000 members
- Severity: Medium
- Status: Confirmed (code)
- Component: orgs/router.py:408-427 (`limit(1000)`, `has_more: False`). The invitations list (≈line 730) is the same.
- Recommended fix: cursor pagination.
- Suggested owner paths: apps/api/app/modules/orgs/router.py, Students.tsx

### ADM-34: College UI links to unbuilt pages and lacks batch-member management
- Severity: Medium
- Status: Confirmed
- Component: Students.tsx (≈62) and screens.tsx:44 link to the unbuilt `/college/students/{id}`. BatchDetail (Batches.tsx:137-200) has no add, move or remove member, archive or edit actions, although `POST/DELETE /batches/{id}/members` and `PATCH` exist (orgs/router.py:1092-1270).
- Requirement: COL-005; `batch.member.manage` = O.
- Suggested owner paths: apps/web/src/features/college/components/Batches.tsx, Students.tsx

### ADM-35: Coordinator dashboard and mentor readiness are partly "not available yet"
- Severity: Medium
- Status: Confirmed
- Component:
  - CoordinatorDashboard.tsx: assessment results, onboarding funnel, and readiness category names are not available.
  - Batches.tsx: "Course progress is not available yet".
  - Mentor.tsx:388 / placement/mentoring.py:257 return `readiness: []`.
- Requirement: COL-001, MEN-004 (wireframes).
- Suggested owner paths: features/college/components/CoordinatorDashboard.tsx, analytics/reports.py, placement/mentoring.py

### ADM-36: Coordinators probably cannot list platform tests and drives to assign
- Severity: Medium
- Status: Suspected
- Component: assessments/router.py:493-519 `GET /studio/tests` needs `test.create` in the owning org; for platform tests that means platform scope (policies.py:54-55). College tests (screens.tsx:17) reuse that list.
- Requirement: COL-007.
- Recommended fix: an "assignable tests" list (published, own org plus platform) gated by `test.assign`.
- Suggested owner paths: apps/api/app/modules/assessments/router.py, features/college/components/screens.tsx

### Content studio (/studio) and trainer (/trainer)

### ADM-41: Batch-scoped trainers get 403 on /trainer/courses and cannot create org-private courses
- Severity: High
- Status: Confirmed
- Component: catalog/router.py:260-270 `studio_courses` ignores batch grants. The same applies to placement/router.py:106-115 `_bank_orgs`. Courses.tsx:39 sends no `organization_id` on create.
- Requirement: PRD §6.7 TRN-003; matrix `course.create/edit` trainer = C / O-private.
- Repro: `test_trainer_batch_scope_studio_lists`, `test_trainer_create_test_and_course_bodies`
- Evidence: `TRAINER_COURSES 403 …permission_denied`, `TRAINER_QUESTIONS 403`, `CREATE_COURSE web body 403`
- Recommended fix: map batch grants to the batch's org for listing and creating (consistent with `can_in_org`, see ADM-49), and send `organization_id` with visibility `org_only`.
- Suggested owner paths: apps/api/app/modules/catalog/router.py, placement/router.py, apps/web/src/features/studio/components/Courses.tsx

### ADM-42: Per-student override (TRN-007) always fails for batch-scoped trainers
- Severity: High
- Status: Confirmed
- Component: TestOps.tsx:82 sends only `{user_id}`; assessments/studio.py:639-643 then falls back to org or platform scope. The schema forbids sending user and batch together.
- Requirement: FR-ASM-007, ASM-13, PRD J3 step 4.
- Repro: `test_trainer_per_student_override_and_cross_batch_edit`
- Evidence: `OVERRIDE per-student(web body) 403`, `whole-batch 201 | user+batch 400`
- Recommended fix: send `test_assignment_id` together with `user_id`, or accept `batch_id + user_id` scoped to the batch with a membership check.
- Suggested owner paths: features/trainer/components/TestOps.tsx, assessments/schemas.py, assessments/studio.py

### ADM-43: Trainers cannot create a test from the portal
- Severity: High
- Status: Confirmed
- Component: TestsList.tsx and TrainerDashboard.tsx:132 have no "New test" action. The shared create (Tests.tsx:47) omits `batch_id`.
- Requirement: PRD J3 step 1; matrix `test.create` B/C.
- Evidence: `CREATE_TEST web body 403 | +organization_id 403 | +batch_id 201`
- Recommended fix: add "New test" with a batch picker that sends `batch_id`.
- Suggested owner paths: features/trainer/components/TestsList.tsx, features/studio/components/Tests.tsx

### ADM-44: Content managers can read every learner's attempt results platform-wide
- Severity: High
- Status: Confirmed
- Component: assessments/studio.py:736-756 `list_attempts` (ASM-15) has no content-manager carve-out. The report endpoint (report.py:90) correctly limits content managers to item stats.
- Requirement: matrix §3 `test.results.read` CM = "P (item stats only)".
- Repro: `test_content_manager_reads_per_learner_attempts`
- Evidence: `CM_REPORT 200 item_stats_only`; `CM_ATTEMPTS 200 [{'user_id': '01a1…', 'status': 'graded', 'percentage': '0.00', …}] student_is_visible True`
- Recommended fix: reuse the `item_only` logic and deny per-learner rows to content managers.
- Suggested owner paths: apps/api/app/modules/assessments/studio.py

### ADM-45: Course builder cannot author lesson content, media, order, resources or preview
- Severity: High
- Status: Confirmed (code and grep)
- Component: Courses.tsx:141-307 calls only CAT-11 and CAT-13. There are no web callers of `studio/lessons/*` (CAT-14/15/20), `draft/outline` (CAT-12), `studio/resources` (CAT-21/22) or `media/uploads/*` (MED-01..03). The lesson kinds omit pdf and practice_set. Courses can still be submitted and published with title-only lessons.
- Requirement: PRD §6.7 TRN-004; sitemap CMS-003.
- Suggested owner paths: apps/web/src/features/studio/components/Courses.tsx (plus a new lesson editor)

### ADM-46: A reviewer can rewrite an author's draft and then approve it
- Severity: High
- Status: Confirmed
- Component: placement/bank.py:431-433 (an edit keeps `authored_by` and clears `reviewed_by`); bank.py:476 (SoD compares only `authored_by`, and is skipped for org-private questions).
- Requirement: matrix `question.review` (reviewer ≠ author); PLC-09.
- Repro: `test_question_sod_gaps` (b)
- Evidence: `SOD_B edit 200 submit 200 self-approve 200 publish 200 | … stem <p>Completely rewritten by reviewer</p>`
- Recommended fix: track editors per version and refuse review by any editor; apply SoD to org-private questions too.
- Suggested owner paths: apps/api/app/modules/placement/bank.py (plus a migration)

### ADM-47: Trainers cannot see file or code submissions, and there is no rubric grading
- Severity: High
- Status: Confirmed (code)
- Component: Grading.tsx:329-335 says "Viewing attachments here is not available yet"; `code_submission_id` is ignored. There is no staff download route for assignment submissions (media/router.py:314-327 accepts only `resource_id` and `lesson_asset_id`). There is no rubric UI, although LRN-17 accepts `rubric_scores`.
- Requirement: PRD TRN-009, J3 step 6, FR-LRN-005.
- Suggested owner paths: apps/api/app/modules/media/router.py or learning/router.py, features/trainer/components/Grading.tsx

### ADM-48: An author can publish their own question after approval
- Severity: Medium
- Status: Confirmed
- Component: bank.py:487-491 (`publish` checks only `reviewed_by`); Questions.tsx:430.
- Requirement: matrix §3 `question.publish` = "P (≠ author)".
- Evidence: `SOD_A submit 200 approve 200 publish-by-author 200`
- Suggested owner paths: placement/bank.py, features/studio/components/Questions.tsx

### ADM-49: A trainer of one batch can edit and publish any test in the org
- Severity: Medium
- Status: Confirmed
- Component: placement/policies.py:58-67 `can_in_org` (any batch grant counts as the whole org); assessments/studio.py:404-409; tests store no owning batch.
- Requirement: matrix `test.edit` trainer = B / C; SoD-08.
- Evidence: `CROSS_BATCH get 200 patch 200 Renamed by other batch trainer`
- Recommended fix: store the owning batch or `created_by` on tests and restrict batch-scoped trainers to their own.
- Suggested owner paths: assessments/studio.py, placement/policies.py, assessments models/migration

### ADM-50: Studio taxonomy, companies, media and question import are stubs
- Severity: Medium
- Status: Confirmed
- Component: app/studio/{taxonomy,companies,media,questions/import}/page.tsx render `NotImplemented` but are linked in the nav (portals.ts:116-119). The APIs PLC-02/03, PLC-16..18 and MED-01..03 exist; import (PLC-12..14) is Planned. implementation-status.md:71 claims the studio is wired.
- Suggested owner paths: apps/web/src/app/studio/*, features/studio/components/

### ADM-51: Authors must type raw UUIDs for topics and lesson references
- Severity: Medium
- Status: Confirmed (code)
- Component: Questions.tsx:410-411 (topic id is required); Tests.tsx:368; Courses.tsx:144-150.
- Recommended fix: pickers backed by PLC-01 and the test and problem lists.

### ADM-52: Test builder is incomplete
- Severity: Medium
- Status: Confirmed (code)
- Component: Tests.tsx:122-421.
  - There is no question picker for fixed rules.
  - There are no controls for the review policy, integrity settings, grace, schedule, window or coding sections.
  - A new test's default rule has an empty topic id, so Save returns 422, shown as a generic toast.
- Requirement: PRD TRN-006; FR-ASM-001/008.

### ADM-53: Trainer dashboard and batch page are missing PRD widgets
- Severity: Medium
- Status: Confirmed (code)
- Component: TrainerDashboard.tsx:38-129 and Batches.tsx:226 ("Course progress is not available yet"). Missing: progress, grading backlog, live tests, at-risk students, topic weakness.
- Requirement: PRD §8.2, TRN-002.

### ADM-54: Review queue and dashboard only look at the newest 200 questions
- Severity: Medium
- Status: Confirmed (code)
- Component: Questions.tsx:471, 479 and StudioDashboard.tsx:18, 25. PLC-04 has no version-status filter, so older in-review items never appear, and approved items still show a "Review" button.
- Suggested owner paths: placement/router.py, bank.py `search_questions`, Questions.tsx

### ADM-55: Review comments and retire reasons are silently discarded
- Severity: Low
- Status: Confirmed (code)
- Component: Questions.tsx:487 sends `comment`; placement/router.py:270-286 and bank.py:469-484 ignore it. `RetireIn.reason` is ignored too (router.py:307-323).

### ADM-56: Trainer course editor shows Publish and Archive, and Release stays enabled
- Severity: Low
- Status: Confirmed (code)
- Component: app/trainer/courses/[course_id]/edit/page.tsx:18 (no `canPublish={false}`); Courses.tsx:315-322; TestOps.tsx:651 keeps "Release results" enabled after results are released. The backend correctly returns 403.

### ADM-57: Audit gaps on content and grading mutations
- Severity: Low
- Status: Confirmed (code)
- Component:
  - catalog/router.py: `add_lesson` (440-462), `put_outline` (423-437), `patch_lesson` (473-496) and `put_topics` (499-511) are not audited. `patch_draft` is audited only partially.
  - learning/router.py: `grade` (923-973) and `release_grades` (976-1000) write no audit row.
  - Sensitive publish and archive actions carry no reason.
- Requirement: matrix §2 "Sens = audited with reason".

### ADM-58: Docs drift (studio and trainer)
- Severity: Low
- Status: Confirmed
- Component:
  - api-specification.md marks PLC-33/34/35 and ASM-19/20/22 as Planned, but they are implemented.
  - stage10-integration-backlog.md:24, 57 lists `GET /assignments` and the studio coding list as missing, but they exist.
  - implementation-status.md:68/71 overstates the studio and trainer status.

## 3. Summary

The IDs are not contiguous by severity, because they are grouped by portal.

| Severity | Count | IDs |
|---|---|---|
| Critical | 2 | ADM-24, 25 |
| High | 17 | ADM-01, 02, 04, 05, 13, 14, 26, 27, 28, 29, 41, 42, 43, 44, 45, 46, 47 |
| Medium | 24 | ADM-03, 06, 07, 08, 10, 11, 15, 16, 17, 18, 30, 31, 32, 33, 34, 35, 36, 48, 49, 50, 51, 52, 53, 54 |
| Low | 15 | ADM-09, 12, 19, 20, 21, 22, 23, 37, 38, 39, 40, 55, 56, 57, 58 |
| **Total** | **58** | |

**Verified OK:**
- Security case decision SoD.
- Kill switch: step-up plus ratification by a different approver.
- Report access: evidence permission, reason code, audit for per-user views, super_admin aggregate only.
- The export approver must be a second security_reviewer.
- Requester self-approval is refused on all admin paths.
- The audit log is append-only and hash-chained.
- Support desk masking and quotas.
- Mentor scoping.
- Coordinator cross-tenant GETs.
- Answer keys and hidden coding cases are protected.
- No mock or lorem data is rendered.

**Not tested, and why:**
- The browser and running stack were not driven (reserved for the E2E agent), so loading, empty and error states were reviewed in code only.
- H7 and H10 numbers were code-reviewed, not seeded. The k_min default is 10, so seeding ≥ 10 unblock requests per week and level was out of time budget.
- Production-mode `check_sod` was not run.
- Passkeys are not implemented.
- Real payment gateway behaviour on over-refund is unknown.
- Cross-tenant mutation probes with complete bodies were not written (the existing BOLA test sends `{}`).
- The ADM-30 policy=`none` case and the ADM-36 coordinator listing were not run.
