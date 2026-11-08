# Tech Drona LMS: Role and Permission Matrix (v0.5, single-company)

| Field | Value |
|---|---|
| Owner | Research & Product Analyst |
| Single-company edition | v0.5 (2026-11-06, WS1): §3 and §9 replaced for the single-company LMS (`docs/single-company/REMOVAL-PLAN.md`). Sections 2, 4–8 and 10 still describe the multi-organisation design in places; where they disagree, §3, §9 and `catalogue.py` win (WS6 rewrites the remaining prose). |
| Status | **Planned** (every permission, rule and matrix cell in this document is Planned) |
| Revision | v0.2 (2026-11-03): wave-2 consistency pass by the Integration Lead (`contract-reconciliation.md` §7): permission-key format (§1 principle 9, §10), new keys `policy.propose`, `security.incident.read`, `security.incident.manage`, `security.network.verify`, `report.export.request`, `report.export.approve` (F-RPM-5); `report.export` retired; coordinator restriction visibility follows the org policy (§8). v0.3 (2026-11-03): security review pass applied by the Integration Lead (CPR-RPM-01..08, `contract-reconciliation.md` §9): new keys `security.engine.kill_switch` (single approver + 24 h ratification) and `security.restriction.bulk_lift` (Dual); `approval.decide` security action types; route-tag model for L3/L4 (§1 principle 4); SoD-12; `policy.propose` namespaces incl. `assessment.*`. v0.4 (2026-11-03, final security cleanup; API I-26): `report.export.approve` split by report family: security/monitoring exports (H1–H9, H12, per-user device/login history) are approved by a **second `security_reviewer`**; all other exports needing approval (H10/H11 aggregates, finance, college reports, bulk PII) by `super_admin`; approver ≠ requester in both cases (§2.7, §3, §5). 2026-11-03 (audit fix wave 3): §2.4 implementation note for trainer `course.create/edit` "O-private" via the batch organization (ADM-41) |
| Binding contracts | `docs/blueprint-brief.md` v0.4 §3 (role keys, scopes), §4 (`roles`, `permissions`, `role_permissions`, `role_grants`), §5 (`require_active_principal`) |
| Related | `docs/product-requirements.md` (FR-RBAC, BR-ENT-14, CCP list); `docs/account-security-and-risk-engine.md` and `docs/account-unblock-workflow.md` (Security Specialist: restriction levels and case workflow detail) |
| Research basis | `research/reference-platform-analysis.md` (RPA) §5: allow-only permissions assigned at a scope, deny by default **[Rec]**, instead of Moodle's Allow/Prevent/Prohibit model, which needs dedicated "Check permissions" tooling **[Verified]** |

---

## 1. Model and principles

1. **Allow-only, deny by default.** A request succeeds only if the principal holds a grant (`role_grants`) of a role whose `role_permissions` include the permission, at a scope that contains the target object. There are no deny/prohibit overrides (RPA §5 [Rec]).
2. **Scopes** (brief §3): `platform` ⊃ `organization:{id}` ⊃ `batch:{id}`; `course:{id}` is a separate axis (a course may be platform catalog or org-private). Containment: a grant at `organization:{A}` covers every batch of A and every org-private course owned by A; it never covers platform catalog authoring.
3. **Ownership (`S` = self)** is not a role grant. A student acts on their own records (profile, devices, attempts, orders, tickets) through ownership checks (`resource.user_id == principal.id`). Ownership never extends to other users' data.
4. **Active principal first.** Every authenticated route runs `require_active_principal` (brief §5) before permission checks. Route-tag model (v0.3; security §7.2; brief v0.4 §5): `restricted` (L3) → routes tagged `account_status` + `l3_readonly`; `status_only` (L4) → routes tagged `account_status` only (it is **not** a 403 for everything, F-RPM-1; PO-07). `account_status` covers me, devices/sessions, case and appeal, privacy requests incl. **data export (DSAR)**, billing view/cancel, support, logout; `l3_readonly` covers read-only dashboard/progress and the **certificate list**. Scope is derived per request from the restriction state. Any other route returns 403 `account_restricted` with the case reference. A disabled account cannot sign in.
5. **Entitlements are not permissions.** Student content access is decided by the entitlement check (PRD §4.12). Permissions govern administrative and staff actions and data visibility.
6. **Staff are also users.** A person may hold grants in several roles; each request is evaluated per permission. The UI shows a portal switcher only for portals the user has grants for.
7. **Every grant is audited** (`audit_log`) with granter, scope, reason and optional `expires_at`.
8. **No impersonation in v1.** No role can "log in as" a user. Support uses read-only user lookup (SUP-003).
9. **Key format (v0.2).** Permission keys are lowercase dot-separated with **2 or 3 segments** (`resource.action` or `resource.sub.action`, e.g. `test.assign`, `security.case.decide`); regex `^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*){1,2}$`, enforced by the `permissions.permission_key` CHECK (`database-schema.md` §6). The owning module is a separate column, not a key prefix. This document is the only source of keys (§10).

---

## 2. Permission catalogue

Sensitivity: **Std** standard; **Sens** sensitive (audited with reason); **Up** requires MFA step-up (fresh authentication with a passkey/TOTP factor within **5 min** for privileged actions (refund, role grant, policy change, case decision, bulk export), **10 min** for other staff sensitive actions incl. support session kills, **15 min** for student email/phone/MFA changes; brief v0.2 §1; SMS/email not accepted for staff); **Dual** requires second-person approval via the approvals queue (PRD FR-ADM-004, CCP-08). All Planned.

### 2.1 Identity, sessions, devices

| Key | Description | Sensitivity |
|---|---|---|
| `user.profile.read_self` / `user.profile.update_self` | Own profile | Std (contact change: Up for self via re-auth, FR-IDN-008) |
| `user.read` | Read another user's profile and account status | Sens |
| `user.invite` | Invite/create staff or student accounts (within scope) | Sens |
| `user.deactivate` | Disable an account (kills all sessions) | Up, Sens |
| `user.mfa.reset` | Remove a user's MFA factors after identity verification | Up, Dual |
| `user.legal_name.change` | Change a locked legal name (after certificate issued) | Sens |
| `session.read` | List another user's sessions (device label, masked IP, times) | Sens |
| `session.revoke` | Revoke another user's sessions | Up, Sens |
| `device.reset` | Remove a trusted device of another user within the support quota (PRD FR-SUP-007) | Up, Sens |
| `device.reset.beyond_quota` | Device reset beyond the support quota | Up, Sens |

### 2.2 Security, restrictions and unblock (`security`)

| Key | Description | Sensitivity |
|---|---|---|
| `security.status.read` | See that an account is restricted and its level (no evidence) | Std |
| `security.reason.read` | See the student-facing reason text and history | Sens |
| `security.evidence.read` | See raw signals: full IP, ASN, device key hashes (HMAC), user agents, overlap timelines, risk evaluation inputs | Sens (reason code required on every view) |
| `security.case.read` / `security.case.note` | Read cases; add notes | Sens |
| `security.case.assign` | Assign cases | Std |
| `security.case.decide` | Decide case outcome (no action, warn, restrict, lift) | Sens |
| `security.restriction.apply_l1l2` | Apply L1/L2 manually | Sens |
| `security.restriction.apply_l3l4` | Apply L3/L4 manually | Up, Sens |
| `security.restriction.lift_l1l2` | Lift L1/L2 | Sens |
| `security.restriction.lift_l3l4` | Lift L3/L4 (high-risk L4 lift is Dual) | Up, Sens (+Dual for high-risk L4) |
| `security.unblock.triage` | Read and route unblock requests/appeals | Sens |
| `security.rule.read` / `security.rule.propose` / `security.rule.simulate` | Risk rules | Sens |
| `security.rule.publish` | Activate a new `risk_rule_versions` row | Up, Dual |
| `security.incident.read` | Read the breach/incident register (`security_incidents`) incl. CERT-In 6 h and DPB clocks | Sens |
| `security.incident.manage` | Open and update incidents (status, timeline, notification timestamps) | Up, Sens |
| `security.network.verify` | Read the trusted-network queue (`org_trusted_networks`) and verify/reject a coordinator's proposal (verifier ≠ proposer) | Sens |
| `security.engine.kill_switch` | Emergency move of `risk.mode` to shadow or HC rules off (SEC-42); only toward shadow/off, never toward enforcement | Up (P5), Sens; **single approver + post-hoc ratification within 24 h** (`risk.kill_switch.ratify` approval request) — a named exception to Dual (v0.3) |
| `security.restriction.bulk_lift` | Bulk false-positive lift of engine-applied L3s (SEC-44; dry run first; excludes L4, high-risk and takeover cases) | Up (P5), Sens, **Dual** (approver via `approval.decide`, action type `security.restriction.bulk_lift`) (v0.3) |

### 2.3 Organizations, batches, RBAC (`orgs`, `rbac`)

| Key | Description | Sensitivity |
|---|---|---|
| `org.create` / `org.update` / `org.suspend` | Organization lifecycle | Sens (`org.suspend`: Up) |
| `org.read` | Read org profile and settings | Std |
| `org.settings.update` | Org-level settings (require MFA, email domains) | Sens |
| `org.member.read` | Read org roster | Sens |
| `org.member.import` | Bulk import + invite (PRD FR-ORG-010) | Sens |
| `org.member.remove` | Remove a member (ends sponsored access) | Sens |
| `batch.create` / `batch.update` / `batch.archive` | Batch lifecycle | Std |
| `batch.member.manage` | Add/move/remove batch members | Std |
| `rbac.grant.read` | Read grants in scope | Std |
| `rbac.grant.org_staff` | Grant `trainer` / `placement_mentor` at `batch:{id}` within own org (PRD FR-ORG-017) | Up, Sens |
| `rbac.grant.manage` | Grant/revoke any role at any scope | Up, Sens; granting `super_admin`, `security_reviewer` or `finance_admin` is Dual |

### 2.4 Catalog, media, learning

| Key | Description | Sensitivity |
|---|---|---|
| `course.create` / `course.edit` | Create/edit drafts | Std |
| `course.publish` | Publish a version (author ≠ publisher for platform catalog) | Sens |
| `course.archive` | Archive course | Sens |
| `course.preview` | View drafts in player preview | Std |
| `resource.manage` | Manage downloadable resources | Std |
| `media.upload` | Upload to VdoCipher / S3 | Std |
| `enrolment.read` / `enrolment.manage` | Read/manage enrolments in scope | Std / Sens |
| `progress.read` | Read learners' progress in scope | Sens |
| `assignment.manage` | Create/edit assignments | Std |
| `assignment.grade` | Grade submissions | Std |
| `grade.override_released` | Change a released grade (reason required) | Up, Sens |
| `certificate.issue_manual` | Issue a certificate outside the automatic rule | Sens |
| `certificate.revoke` | Revoke a certificate | Up, Sens |

**Implementation note: trainer `course.create` / `course.edit` "O-private" (ADM-41; audit fix wave 3, 2026-11-03).** Trainer grants are batch-scoped, and a batch never contains a course (§3 containment), so the "O-private" cell in §3 is implemented as a narrow exception in `rbac.service` (`ORG_PRIVATE_VIA_BATCH`). For `course.create` and `course.edit` only, a trainer's batch grant covers an organization-owned target (the organization itself when creating, or an org-private course when editing) when the batch belongs to that organization. It never covers platform (catalogue) courses or another organization's courses, and no other permission is widened. CAT-08 `GET /studio/courses` mirrors the rule: for a batch-scoped trainer it lists the courses owned by their batches' organizations, plus any course-scoped grants.

### 2.5 Placement, assessments, coding

| Key | Description | Sensitivity |
|---|---|---|
| `taxonomy.manage` | Subject/topic tree | Sens |
| `question.create` / `question.edit` | Author questions (drafts) | Std |
| `question.review` | Approve/request changes (reviewer ≠ author) | Sens |
| `question.publish` / `question.retire` | Publish or retire versions | Sens |
| `question.answer_key.read` | See answer keys and explanations outside student review rules | Sens |
| `question.import` | Bulk import | Sens |
| `company_path.manage` | Companies and company paths | Std |
| `test.create` / `test.edit` | Build tests (locked after first attempt) | Std |
| `test.assign` | Assign tests to batches/users with windows | Std |
| `test.override.grant` | Extra time / attempt / extension for a user or batch | Sens |
| `test.results.read` | Read attempts and results in scope | Sens |
| `test.results.release` | Release results per review matrix | Std |
| `attempt.regrade` | Trigger regrade | Sens |
| `attempt.invalidate` | Invalidate an attempt after review | Up, Sens |
| `integrity.flag.read` | Read advisory integrity events of attempts (tab/blur/paste/full-screen/device switch, no IP) | Sens |
| `integrity.flag.decide` | Record review outcome (no action / refer / invalidate) | Sens |
| `coding_problem.manage` | Create/edit coding problems and visible cases | Std |
| `coding_test_case.hidden.read` | Read/edit hidden test cases | Sens |
| `submission.code.read` | Read submitted code of others | Sens |
| `similarity.run` | Run similarity checks | Std |
| `mentor.slot.manage` | Manage own slots | Std |
| `mentor.feedback.write` | Write interview/resume feedback | Std |
| `mentor.notes.read` | Read mentor feedback and readiness notes of assigned students | Sens |

### 2.6 Commerce and entitlements

| Key | Description | Sensitivity |
|---|---|---|
| `product.manage` / `price.manage` | Products, plans, prices | Up, Sens (price change Dual if > 20% decrease or any change to an active subscription price) |
| `coupon.manage` | Create/edit/disable coupons | Up, Sens; Dual if > 50% off or > 1,000 redemptions |
| `order.read` / `payment.read` | Orders and payments (masked instrument data only) | Sens |
| `refund.decide` | Approve/reject refunds within the published rule | Up, Sens |
| `refund.goodwill` | Approve a refund outside the rule | Up, Dual |
| `subscription.admin_cancel` | Cancel a subscription on a user's behalf | Up, Sens |
| `invoice.read` / `invoice.credit_note` | Invoices and credit notes | Sens / Up |
| `contract.manage` | Create/renew institution contracts | Up, Sens |
| `contract.terminate` | Terminate early | Up, Dual (finance + super admin) |
| `contract.read` | Read own org's contract | Std |
| `reconciliation.run` | Settlement reconciliation | Sens |
| `entitlement.read` | Read entitlements of users in scope | Sens |
| `entitlement.grant_manual` | Comp/admin grant (≤ 365 days) | Up, Sens; Dual if > 90 days or > 50 users |
| `entitlement.revoke` | Revoke an entitlement outside refund/contract flows | Up, Sens |
| `seat.assign` / `seat.revoke` | Assign/revoke contract seats in own org | Sens |

### 2.7 Analytics, notifications, support, privacy, platform

| Key | Description | Sensitivity |
|---|---|---|
| `analytics.read` | Dashboards/reports in scope (aggregates and per-learner within scope) | Sens |
| `analytics.read.platform` | Platform-wide aggregates | Sens |
| `report.export.request` | Request an audited, expiring export job (`export_jobs`) of a report in scope (replaces the retired `report.export`). Jobs needing approval wait in `awaiting_approval` | Up, Sens |
| `report.export.approve` | Approve an export job that requires approval; records an `approval_requests` row; approver ≠ requester (CHECK). Split by report family (v0.4): **security/monitoring exports** (Section H reports H1–H9 and H12, and any per-user device/login history or other per-user security evidence, incl. per-user H11 rows from a case review; `action_type = security.export.per_user`) are approved only by a **different `security_reviewer`**, because `super_admin` may not view security evidence outside break-glass; **all other exports** needing approval (H10/H11 aggregates, finance/commerce, college/coordinator and trainer reports, any personal-data export > 10,000 rows; `action_type = export.bulk_pii`) are approved only by `super_admin` | Up, Sens |
| `notification.batch_announce` | Announcements to batches in scope | Std |
| `notification.template.manage` | Templates | Sens |
| `ticket.read` / `ticket.respond` / `ticket.assign` | Support tickets | Sens / Std / Std |
| `ticket.escalate` | Route to finance/security/content | Std |
| `privacy.request.process` | Process export/deletion/grievance requests (rows in `privacy_requests`) | Up, Sens |
| `audit.read` | Read the audit log | Sens |
| `audit.read.org` | Read audit entries about own org's admin actions | Sens |
| `policy.propose` | Propose a `policy_settings` change at a scope (creates an `approval_requests` row); limited by namespace per grant (§3): `security_reviewer` in the `risk.*`, `sessions.*`, `devices.*`, `playback.*`, `assessment.*`, `login.*`, `otp.*`, `unblock.*` namespaces (v0.3, CPR-RPM-01); `finance_admin` in `commerce.*` | Up, Sens |
| `policy.edit` | Approve/execute a `policy_settings` change (device caps, refund window, grace); never one's own proposal. Replaces the security doc's `security.policy.write` | Up, Dual |
| `feature_flag.manage` | Feature flags | Up, Sens |
| `approval.decide` | Approve a dual-control request in `approval_requests` (never one's own); granted per action type. Security action types (v0.3): `security.case.decision`, `security.restriction.bulk_lift`, `risk.kill_switch.ratify` — approver is a different `security_reviewer` or `super_admin`, never the requester and never the person who applied the restriction (or flipped the kill switch) | Up, Sens |
| `breakglass.activate` | Time-boxed elevation (≤ 2 h) | Up (passkey), alerts all super admins + security reviewers |

Not permissions: analytics ingest (`POST /analytics/events`, `/beacon`) requires only an authenticated session and writes the principal's own events (ownership **S**); there is no `analytics.event.ingest` key. A student's export of their own data is a privacy rights request (ownership), not `report.export.request`.

---

## 3. Role × permission matrix (single-company edition, v0.5)

> **Generated from `apps/api/app/modules/rbac/catalogue.py`** (the machine-readable source; migration `rbac_0004` loads it). Edit the catalogue and this table together (`docs/single-company/REMOVAL-PLAN.md` §4, §8 D2/D3).

Cell legend: **P** platform scope; **B** batch scope; **C** course scope; **S** self only (ownership, never a role permission); **R** read-only variant; **—** never. Flags: **Up** step-up MFA, **Dual** second-person approval (a *different* Admin). Columns: STU `student`, EVL `evaluator`, TRN `trainer`, CM `content_manager`, SA `super_admin` (shown as "Admin").

Default grant scopes: `student` platform (holds no permissions; access is by ownership, memberships and entitlements), `evaluator` B (or P = every cohort), `trainer` B and/or C, `content_manager` P (or C for a single course), `super_admin` P. `organization` is **not** a grant scope any more: the single company org (`COMPANY_ORG_ID`) is an internal tenancy key.

Removed roles (live grants revoked by `rbac_0004`): `college_coordinator` (reason `college_removal`); `finance_admin`, `support_agent`, `security_reviewer`, `placement_mentor` (reason `role_consolidation`, owner decision D2 — every permission they held now belongs to Admin; break-glass-only and approver-only Admin cells became standing P cells). Removed permissions: `org.create`, `org.update`, `org.suspend`, `org.settings.update`, `org.member.import`, `org.member.remove`, `rbac.grant.org_staff`, `contract.manage`, `contract.terminate`, `contract.read`, `seat.assign`, `seat.revoke`, `audit.read.org`, `security.network.verify`. `org.read` / `org.member.read` now mean "company / batch roster read".

Evaluator (D3): grades and **releases** results (`assignment.grade` also covers assignment grade release; `test.results.release`), reads answer keys to grade, decides integrity flags; no authoring (`course.*`, `question.*`, `test.create/edit/assign`, `assignment.manage`, `path.*`, `engage.*`, `media.upload`), no `grade.override_released`, no `attempt.invalidate`, no batch/enrolment management, and never grades their own attempt or submission.

| Permission | Flags | STU | EVL | TRN | CM | SA |
|---|---|---|---|---|---|---|
| `user.profile.read_self` | — | S | S | S | S | S |
| `user.profile.update_self` | — | S | S | S | S | S |
| `user.read` | — | — | B | B | — | P |
| `user.invite` | — | — | — | — | — | P |
| `user.deactivate` | Up | S | — | — | — | P |
| `user.mfa.reset` | Up Dual | — | — | — | — | P |
| `user.legal_name.change` | — | — | — | — | — | P |
| `session.read` | — | S | — | — | — | P |
| `session.revoke` | Up | S | — | — | — | P |
| `device.reset` | Up | S | — | — | — | P |
| `device.reset.beyond_quota` | Up | — | — | — | — | P |
| `security.status.read` | — | S | — | B | — | P |
| `security.reason.read` | — | S | — | — | — | P |
| `security.evidence.read` | — | — | — | — | — | P |
| `security.case.read` | — | — | — | — | — | P |
| `security.case.note` | — | — | — | — | — | P |
| `security.case.assign` | — | — | — | — | — | P |
| `security.case.decide` | — | — | — | — | — | P |
| `security.restriction.apply_l1l2` | — | — | — | — | — | P |
| `security.restriction.apply_l3l4` | Up | — | — | — | — | P |
| `security.restriction.lift_l1l2` | — | — | — | — | — | P |
| `security.restriction.lift_l3l4` | Up | — | — | — | — | P |
| `security.unblock.triage` | — | S | — | — | — | P |
| `security.rule.read` | — | — | — | — | — | P |
| `security.rule.propose` | — | — | — | — | — | P |
| `security.rule.simulate` | — | — | — | — | — | P |
| `security.rule.publish` | Up Dual | — | — | — | — | P |
| `security.incident.read` | — | — | — | — | — | P |
| `security.incident.manage` | Up | — | — | — | — | P |
| `security.engine.kill_switch` | Up | — | — | — | — | P |
| `security.restriction.bulk_lift` | Up Dual | — | — | — | — | P |
| `org.read` | — | S | — | B | — | P |
| `org.member.read` | — | — | — | B | — | P |
| `batch.create` | — | — | — | — | — | P |
| `batch.update` | — | — | — | — | — | P |
| `batch.archive` | — | — | — | — | — | P |
| `batch.member.manage` | — | — | — | B | — | P |
| `rbac.grant.read` | — | — | — | — | — | P |
| `rbac.grant.manage` | Up | — | — | — | — | P |
| `course.create` | — | — | — | C | P | — |
| `course.edit` | — | — | — | C | P | — |
| `course.publish` | — | — | — | — | P | — |
| `course.archive` | — | — | — | — | P | P |
| `course.preview` | — | — | — | C | P | P |
| `resource.manage` | — | — | — | C | P | — |
| `media.upload` | — | — | — | C | P | — |
| `enrolment.read` | — | S | — | B | — | P |
| `enrolment.manage` | — | — | — | B | — | P |
| `progress.read` | — | S | B | B | — | P |
| `assignment.manage` | — | — | — | B | — | — |
| `assignment.grade` | — | — | B | B | — | — |
| `grade.override_released` | Up | — | — | B | — | — |
| `certificate.issue_manual` | — | — | — | — | P | P |
| `certificate.revoke` | Up | — | — | — | P | P |
| `taxonomy.manage` | — | — | — | — | P | — |
| `question.create` | — | — | — | C | P | — |
| `question.edit` | — | — | — | C | P | — |
| `question.review` | — | — | — | — | P | — |
| `question.publish` | — | — | — | — | P | — |
| `question.retire` | — | — | — | — | P | — |
| `question.answer_key.read` | — | — | B | B | P | — |
| `question.import` | — | — | — | — | P | — |
| `company_path.manage` | — | — | — | — | P | — |
| `test.create` | — | — | — | B | P | — |
| `test.edit` | — | — | — | B | P | — |
| `test.assign` | — | — | — | B | — | P |
| `test.override.grant` | — | — | — | B | — | P |
| `test.results.read` | — | S | B | B | P | P |
| `test.results.release` | — | — | B | B | — | P |
| `attempt.regrade` | — | — | B | B | P | — |
| `attempt.invalidate` | Up | — | — | B | — | — |
| `integrity.flag.read` | — | — | B | B | — | P |
| `integrity.flag.decide` | — | — | B | B | — | P |
| `coding_problem.manage` | — | — | — | C | P | — |
| `coding_test_case.hidden.read` | — | — | — | C | P | — |
| `submission.code.read` | — | S | B | B | P | P |
| `similarity.run` | — | — | B | B | — | P |
| `mentor.slot.manage` | — | — | — | — | — | P |
| `mentor.feedback.write` | — | — | — | — | — | P |
| `mentor.notes.read` | — | S | — | B | — | P |
| `product.manage` | Up | — | — | — | — | P |
| `price.manage` | Up | — | — | — | — | P |
| `coupon.manage` | Up | — | — | — | — | P |
| `order.read` | — | S | — | — | — | P |
| `payment.read` | — | S | — | — | — | P |
| `refund.decide` | Up | S | — | — | — | P |
| `refund.goodwill` | Up Dual | — | — | — | — | P |
| `subscription.admin_cancel` | Up | S | — | — | — | P |
| `invoice.read` | — | S | — | — | — | P |
| `invoice.credit_note` | Up | — | — | — | — | P |
| `reconciliation.run` | — | — | — | — | — | P |
| `entitlement.read` | — | S | — | — | — | P |
| `entitlement.grant_manual` | Up | — | — | — | — | P |
| `entitlement.revoke` | Up | — | — | — | — | P |
| `analytics.read` | — | S | — | B | C | P |
| `analytics.read.platform` | — | — | — | — | — | P |
| `report.export.request` | Up | — | — | B | — | P |
| `report.export.approve` | Up | — | — | — | — | P |
| `notification.batch_announce` | — | — | — | B | — | P |
| `notification.template.manage` | — | — | — | — | — | P |
| `ticket.read` | — | S | — | — | P | P |
| `ticket.respond` | — | S | — | — | P | P |
| `ticket.assign` | — | S | — | — | P | P |
| `ticket.escalate` | — | S | — | — | P | P |
| `privacy.request.process` | Up | S | — | — | — | P |
| `audit.read` | — | — | — | — | — | P |
| `policy.propose` | Up | — | — | — | — | P |
| `policy.edit` | Up Dual | — | — | — | — | P |
| `feature_flag.manage` | Up | — | — | — | — | P |
| `approval.decide` | Up | — | — | — | — | P |
| `breakglass.activate` | Up | — | — | — | — | P |
| `engage.activity.manage` | — | — | — | B | P | P |
| `path.manage` | — | — | — | B | P | P |
| `path.allocate` | — | — | — | B | P | P |

**Notes on the matrix**

- `O-private` = only courses/questions owned by the user's organization (PRD FR-CAT-009); org-private content never enters the platform catalog without `content_manager` review.
- `trainer` with only `course:{id}` scope (platform course faculty) sees enrolled learners of that course **only** in batches where they also hold a batch grant; course scope alone gives aggregate analytics without per-learner identity.
- Single-company (D2): `super_admin` ("Admin") is also the everyday operator for security, finance, support and mentoring. Dual-control actions still need a second, **different** Admin (maker ≠ checker); SoD-10 (finance vs security) no longer has two roles to separate.

---

## 4. Tenant-isolation rules

| ID | Rule |
|---|---|
| TI-01 | Every tenant-scoped table carries `organization_id`; Postgres RLS with `FORCE ROW LEVEL SECURITY` on these tables; the app connects as a non-owner role and sets `SET LOCAL app.tenant_id` / `app.user_id` per transaction (brief §1, RPA §8 [Verified] PostgreSQL docs). |
| TI-02 | Org-scoped principals (coordinators, org trainers, org mentors) can only resolve objects whose `organization_id` is in their grants. Cross-org object IDs return **404** (not 403), so existence is not disclosed, and the attempt is logged as a security signal. |
| TI-03 | A college coordinator never sees another organization's students, batches, results, contracts, invoices, tickets or aggregates, including benchmarks. Cross-org comparisons shown to coordinators use only platform-wide anonymised percentiles with k ≥ 50 students per bucket (`analytics.k_min.cross_org_display` = 50); cohort cells inside the org follow `analytics.k_min.cohort` = 10. |
| TI-04 | A student belonging to two orgs (rare: transfer) appears to each org only with data from that org's membership period and contract scope (PRD BR-ENT-14). |
| TI-05 | Uniqueness, primary-key and foreign-key checks bypass RLS (RPA §8 [Verified]); therefore uniqueness errors must not leak cross-tenant existence: invite/import of an email that exists elsewhere returns "invite sent" (linking happens on acceptance), never "user exists in org X". |
| TI-06 | Exports, file downloads and signed URLs embed the org scope; a signed URL is valid ≤ 5 min (files) / 24 h (exports) and only for the requesting principal's session. |
| TI-07 | Background jobs (Celery) run with an explicit tenant context per job; jobs spanning orgs (platform aggregates) run as a dedicated reporting role that writes only aggregated, de-identified outputs. |
| TI-08 | Search indexes and caches are keyed by tenant; cache keys include `organization_id` for any org-scoped response. |
| TI-09 | Platform-scoped staff (support, security, finance, super admin) bypass org scoping only through explicit platform grants; every cross-org read by staff is audited with the permission used. |
| TI-10 | An automated isolation test suite (API + RLS, two seeded orgs, every org-scoped endpoint) runs on every build; one failure blocks release (PRD NFR-SEC-03). |
| TI-11 | Request bodies use Pydantic `extra="forbid"`; `organization_id` in a request body is ignored for authorization and must match the path/grant (RPA §8 baseline). |

---

## 5. Sensitive actions: step-up MFA and second-person approval

Step-up = fresh authentication (`auth_sessions.last_step_up_at`) with passkey or TOTP within 5 min for privileged actions, 10 min for other staff sensitive actions, 15 min for student contact/MFA changes (brief v0.2 §1; SMS/email not accepted for staff; ASVS 7.5.3 per RPA §8). Dual = second-person approval in ADM-010; approver must hold `approval.decide` for that action type, must be a different person from the requester, and the request expires after 72 h. All Planned.

| Action | Step-up | Dual control | Approver role |
|---|---|---|---|
| Grant/revoke `super_admin`, `security_reviewer`, `finance_admin` | Yes | Yes | another `super_admin` |
| Grant other roles at platform scope | Yes | No | — |
| Coordinator grants batch-scoped trainer/mentor | Yes | No (audited, visible to SA) | — |
| Change `policy_settings` (device/session/stream caps, refund rule, grace days, OTP limits) | Yes | Yes | another `super_admin` |
| Publish a risk-rule version | Yes | Yes | `super_admin` (proposer is SEC) |
| Apply L3/L4 manually | Yes | No (human review is itself required before L4) | — |
| Lift L4 on a high-risk case | Yes | Yes | second `security_reviewer` or `super_admin` |
| Lift L3/L4 that the same reviewer applied | Yes | Yes | different `security_reviewer` |
| Case decision needing a second approver (`security.case.decision`; pending in `approval_requests`, `case_decisions` written only on approval) | Yes (5 min) | Yes | different `security_reviewer` or `super_admin` (≠ requester, ≠ applier) |
| Emergency kill switch: `risk.mode` → shadow or HC rules off (`security.engine.kill_switch`) | Yes (5 min) | **No — single approver + ratification within 24 h** (`risk.kill_switch.ratify`; unratified → page, not reverted); any move toward enforcement is Dual | ratifier: different `security_reviewer` or `super_admin` |
| Bulk false-positive lift of engine-applied L3s (`security.restriction.bulk_lift`) | Yes (5 min) | Yes | different `security_reviewer` or `super_admin` (≠ requester, ≠ applier) |
| Reset a user's MFA | Yes | Yes | `security_reviewer` (if requested by support) |
| Deactivate a user account | Yes | No | — |
| Device reset beyond quota | Yes | No | — |
| Revoke another user's sessions | Yes | No | — |
| Refund within published rule | Yes | No (single finance) | — |
| Goodwill refund outside rule | Yes | Yes | second `finance_admin` |
| Refund > ₹25,000 single order | Yes | Yes | second `finance_admin` |
| Coupon > 50% off or > 1,000 redemptions | Yes | Yes | second `finance_admin` or `super_admin` |
| Price decrease > 20% or change to an active subscription price | Yes | Yes | second `finance_admin` or `super_admin` |
| Manual entitlement grant > 90 days or > 50 users | Yes | Yes | `super_admin` |
| Terminate institution contract early | Yes | Yes | `finance_admin` + `super_admin` (both) |
| Suspend organization | Yes | Yes | `finance_admin` or second `super_admin` |
| PII report export (coordinator/trainer/finance), ≤ 10,000 rows | Yes | No | — |
| Security/monitoring report export with per-user rows (H1–H9, H12, per-user device/login history; `security.export.per_user`) | Yes | Yes | second `security_reviewer` (`report.export.approve`; ≠ requester) |
| Bulk export > 10,000 rows of personal data (non-security reports: H10/H11 aggregates, finance, college reports) | Yes | Yes | `super_admin` (`report.export.approve`; ≠ requester) |
| Policy change proposed by `security_reviewer` / `finance_admin` (`policy.propose`) | Yes | Yes | `super_admin` (`policy.edit`) |
| Change released grade / invalidate attempt / revoke certificate | Yes | No | — |
| Process deletion request | Yes | No | — |
| Activate break-glass | Yes (passkey only) | No (post-hoc review within 2 business days by another SA) | — |

---

## 6. Data visibility: learning and personal data

| Data | Student (self) | Coordinator (own org) | Trainer (batch) | Mentor (assigned) | Content manager | Support | Security | Finance | Super admin |
|---|---|---|---|---|---|---|---|---|---|
| Profile (name, email, mobile) | Full | Name, email, mobile, roll no. | Name, email | Name | — | Full (mobile masked except last 4) | Full | Name, email, billing address, GSTIN | Full |
| DOB / minor flag | Full | Minor flag only | Minor flag only | — | — | Minor flag | DOB + flag | — | Flag |
| Progress, attempts, results | Full | Contract scope + batch-assigned (BR-ENT-14) | Own batches' assigned content | Readiness summary | Item-level aggregates only | Read-only summary (troubleshooting) | Case-linked only | — | Aggregates |
| Time-on-task | Full | Aggregated per student (minutes/week) | Aggregated per student | — | Aggregated per content item | — | — | — | Aggregates |
| Submitted code | Full | — | Own batches | Assigned students (if shared) | Reported issues | — | Case-linked | — | — |
| Orders, payments, invoices | Full | Contract invoices only | — | — | — | Masked summary | — | Full (masked instrument) | Read |
| Mentor feedback | Full | Yes (sponsored sessions) | Yes | Own + assigned | — | — | — | — | — |
| Support tickets | Own | Own org's college-access tickets | — | — | Content tickets | Full | Security tickets | Billing tickets | Read |
| Personal purchases outside contract | Full | Only with student opt-in | Only with opt-in | — | — | Summary | — | Full | Read |

---

## 7. Separation of duties

| ID | Rule |
|---|---|
| SoD-01 | `finance_admin` cannot read security evidence, cases, signals or IP/device history; `security_reviewer` cannot issue refunds, change prices or grant entitlements (except automatic BR-ENT-12 compensation executed by the system). |
| SoD-02 | `college_coordinator` sees only their own org (TI-03), never other orgs, never security evidence or reasons for restriction (status and level only), never personal purchases outside contract scope without student opt-in. |
| SoD-03 | `support_agent` cannot lift L3/L4 restrictions, cannot apply L3/L4, cannot set or view passwords (ASVS 6.4.6, RPA §5), cannot reset MFA alone, cannot see full IPs or evidence, and has no device reset beyond quota. |
| SoD-04 | Question/course author ≠ reviewer/publisher for platform catalog content. |
| SoD-05 | Dual-control requester ≠ approver; the system enforces distinct `user_id`s, and an approver cannot approve requests they authored by delegation. |
| SoD-06 | The security reviewer who applied an L3/L4 restriction cannot alone lift it (§5). |
| SoD-07 | `super_admin` does not operate security cases, evidence or refunds outside break-glass; break-glass sessions are reviewed by another super admin. |
| SoD-08 | Trainers cannot modify test settings after the first attempt (lock) and cannot change released grades without a reason; integrity decisions to invalidate are visible to the coordinator. |
| SoD-09 | Content managers cannot see learner identities in item analytics (aggregates only, min 10 responses: `analytics.k_min.item` = 10). |
| SoD-10 | No role may hold both `finance_admin` and `security_reviewer` simultaneously; grant attempts are rejected. A `super_admin` may not also hold `security_reviewer` or `finance_admin` in production (except during a time-boxed break-glass). |
| SoD-11 | Placement mentors see only students assigned to them (by booking or batch grant); booking does not grant access to a student's attempts beyond the readiness summary. |
| SoD-12 | (v0.3) The approver of a `security.case.decision` or of a `security.restriction.bulk_lift` must differ from the requester **and** from the person who applied the restriction; a `risk.kill_switch.ratify` ratifier must differ from the person who flipped the kill switch (UNB §5.1; RE §5.7). |

---

## 8. Monitoring data visibility (IP, device and session history)

Monitoring data tiers (all Planned; retention per `docs/privacy-and-data-retention.md`):

| Tier | Content |
|---|---|
| **M0 — Status** | "Restricted / not restricted", level (L1–L4), end date |
| **M1 — Owner view** | Own devices: label (browser/OS), first/last seen, approximate state, own full IP for current and recent sessions, trust status; own login history (time, device, state, result); own restriction reasons |
| **M2 — Support view** | Device labels, first/last seen, approximate state, IP masked to /24 (IPv4) or /48 (IPv6), session start/last active, replacement quota, restriction level + student-facing reason |
| **M3 — Evidence** | Full IP, ASN and IP type, device key hashes (HMAC), user agents, overlap timelines, playback session overlaps, login attempts, risk evaluation inputs, rule version and score contributions |

| Viewer | Tier | Conditions |
|---|---|---|
| Student (self) | M0 + M1 | Always (ASVS 7.5.2 session list; PRD STU-022) |
| College coordinator | M0 only for own org students, **as allowed by org policy `org.notify_coordinator_on_restriction`** (default `L4_status_only`: only L4 status is shown; other values `none`, `L3_L4`, `all_levels`) | No reasons, no evidence, never signals; message "contact support" (confirmed by the Security Specialist, CPR-RPM-06) |
| Trainer | M0 for own batch students + attempt integrity events (tab/blur/paste/full-screen/device switch counts and times) | No IP, no ASN, no device history |
| Placement mentor, content manager | None | — |
| Support agent | M0 + M2 | Only while a ticket or unblock request references the user, or with a reason code; every view audited |
| Security reviewer | M0 + M2 + M3 | M3 requires a reason code (case ID or ticket ID) per view; views logged in `audit_log`; M3 for minors contains only deterministic-cap events (no behavioural data exists, BR-MIN-01) |
| Finance admin | None (M0 only when a payment dispute coincides with a restriction, via case reference from security) | SoD-01 |
| Super admin | M0 + aggregates; M3 only in break-glass | Break-glass views flagged for review |
| Guardian (minor accounts) | M0 + M1 for the minor's account on request | Through support with verified guardian identity |

Additional rules: evidence packs exported for an appeal are generated by security reviewers only, contain only data relevant to the decision, and are shared with the student on request (DPDP s.8(3) accuracy obligation, RPA §3). No monitoring data is ever shown to other students or used for marketing.

---

## 9. Role-to-portal mapping

| Role | Portals | Default landing |
|---|---|---|
| `student` | Public, `/app` (student, player, practice, tests, coding) | `/app` |
| `evaluator` | `/evaluator` (grading queues, results release; no authoring) | `/evaluator` |
| `trainer` | `/trainer` (+ player preview) | `/trainer` |
| `content_manager` | `/studio` (+ player preview) | `/studio` |
| `super_admin` ("Admin") | `/admin` plus the former `/finance`, `/desk`, `/security`, `/mentor` consoles | `/admin` |

Landing order when a user holds several roles: Admin, Content manager, Trainer, Evaluator (`apps/api/app/modules/sessions/login.py`).

Contract change proposals arising from this matrix (e.g. `approval_requests`, CCP-08) are listed in `docs/product-requirements.md` §12.

---

## 10. Machine-readable catalogue and key changes (v0.2)

- **Source and file.** §2 (keys), §3 (role × scope cells) and §5 (step-up/Dual) are the source for `apps/api/app/core/authz/permissions.yaml` (owner: Security lane; content changes approved by the Product Analyst). The Architect's seed data migration loads exactly that file into `permissions` / `role_permissions`. CI fails if a route declares a key missing from the file, if a key in the file is used by no route, or if the file and this document differ (QA issue I-04).
- **Key renames applied in the wave-2 pass** (old → canonical):

| Old key (where used) | Canonical key |
|---|---|
| `report.export` (role matrix v0.1, `api-specification.md` SEC-32, ANL-13, AUD-05) | `report.export.request` (+ `report.export.approve` where approval is required) |
| `security.policy.write` (`account-security-and-risk-engine.md` §3.1) | `policy.edit` (super_admin, execute/approve) and `policy.propose` (security_reviewer proposals) |
| `assessments.test.publish` (architecture §6.4 example) | `test.results.release` (no "test publish" permission exists; tests become available through `test.assign`) |
| `coding.testcase.read_hidden` (architecture §9) | `coding_test_case.hidden.read` |
| `security.case.read` / `security.case.decide` used for incidents (API SEC-37..39) | `security.incident.read` / `security.incident.manage` |
| `security.case.read` / `security.case.decide` used for trusted networks (API SEC-33, SEC-34) | `security.network.verify` |
| `analytics.event.ingest` (analytics doc §5.1) | none: ownership (authenticated session) |

