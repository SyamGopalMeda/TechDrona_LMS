# Tech Drona LMS: Product Requirements (PRD v0.3)

> **Single-company note (2026-11-06).** Tech Drona now runs as a single company ([ADR-0015](architecture-decisions/ADR-0015-single-company.md)); the college/B2B features described in this document (college portal and coordinators, institution contracts and seats, invitations and roster import, per-organization settings, trusted networks and lab devices, the "For colleges" page) are removed. Roles are Admin (`super_admin`), Trainer, Evaluator, Content manager and Student; finance, support, security and mentor duties belong to Admin. Batches are Tech Drona cohorts managed by Admin at `/admin/batches`; businesses use the corporate enquiry form at `/enquiries`. Where this document conflicts, ADR-0015 and [`single-company/REMOVAL-PLAN.md`](single-company/REMOVAL-PLAN.md) §8 win.

| Field | Value |
|---|---|
| Owner | Research & Product Analyst |
| Status | **Planned** (blueprint stage; nothing in this document is Implemented, Tested or Deployed) |
| Binding contracts | `docs/blueprint-brief.md` v0.4 (roles, modules, entities, decisions) |
| Revision | v0.2 (2026-11-03): wave-2 consistency pass (contract-reconciliation §7). v0.3 (2026-11-03): security review pass applied by the Integration Lead (CPR-PRD-01..11, `contract-reconciliation.md` §9): webhook AC (no age rejection), remember-device re-issue, session-cap replace/refuse rules, AC-SES-04/05, compensation formula, minor safeguard incl. takeover signals, separated-network evidence, FR-SEC-010 HC rules, L2 re-verification, dashboard H1–H12 + ENG, hard-disable response, device-policy text |
| Research basis | `research/reference-platform-analysis.md` (cited as **RPA §n**). Evidence labels are kept: **[Verified]** primary source, **[Reported]** secondary/claims, **[Rec]** recommendation |
| Companion docs | `docs/feature-comparison.md`, `docs/role-permission-matrix.md` (this author); `docs/account-security-and-risk-engine.md`, `docs/account-unblock-workflow.md`, `docs/privacy-and-data-retention.md` (Security Specialist); `docs/analytics-event-schema.md` (Analytics Engineer); `docs/system-architecture.md`, `docs/database-schema.md` (System Architect) |
| Date | 2026-11-03 |

**Status rule.** Every requirement, rule, screen, dashboard and acceptance criterion below is **Planned**. Where a table has a Status column it reads "Planned"; where it does not, the item is Planned by this rule.

**Priority scale.** **P0** = launch blocker (Phase 0 + MVP, RPA §8 "Implementation priorities"); **P1** = v1, within 6 months of launch; **P2** = later (Phase 2–3). "v1" in this document means P0 + P1.

---

## 1. Executive summary

Tech Drona is a placement-preparation LMS for Indian engineering and degree students, sold both directly to individuals (D2C) and to colleges through institution contracts (B2B). It combines four workloads that no single reference platform covers end to end (RPA §2): a structured LMS (courses, batches, assignments, certificates), a placement-practice engine (aptitude, programming, DSA, CS fundamentals, company paths, interview prep), a rigorous timed-assessment engine with a sandboxed coding judge, and an Indian-compliant commerce stack with a single central entitlement system.

The market's information architecture is settled (Quant/Logical/Verbal → programming → DSA → CS core → company hubs → interview; RPA §1 [Verified]), so Tech Drona adopts it. It differentiates on **verifiable trust** (RPA conclusion): published device and session numbers, honest pricing and one refund rule applied everywhere, a readiness engine with disclosed methods, a TPO (college coordinator) console, dispute-ready assessment integrity with human review, and instantly verifiable certificates.

v1 delivers: self-signup and college-invite onboarding with a DOB age gate and minor routing; server-side sessions with a published 3-device / 2-session / 1-stream policy; course authoring and a DRM course player; placement practice with explained question banks; sectional company-pattern mocks with a server-authoritative timer and 5–10 s autosave; a Run/Submit coding workspace on Judge0 Cloud with hidden tests; Razorpay one-time payments, subscriptions (≤ ₹15,000 per debit) and coupons; institution contracts with seat pools; and dashboards for students, trainers, coordinators, admins and security reviewers.

Success metrics for the first 12 months (targets, **Planned**):

| Metric | Target | Data source |
|---|---|---|
| Diagnostic-to-paid conversion (D2C) | ≥ 4% within 30 days of diagnostic | `orders`, `test_attempts` |
| Weekly active learners / entitled learners | ≥ 45% | `daily_learning_aggregates`, `entitlements` |
| Test attempts lost due to crash/disconnect (answers not recovered) | < 0.1% of attempts | `attempt_events`, `attempt_responses` |
| Refund requests decided within SLA (5 business days) | ≥ 98% | `refunds` |
| False-positive restrictions overturned on appeal | tracked; target < 5% of L3/L4 actions | `case_decisions` |
| Support first response (P1 tickets) | ≤ 4 business hours, ≥ 95% | `support_tickets` |
| College coordinator weekly active rate | ≥ 70% of contracted colleges | `analytics_events` |

---

## 2. Product vision and differentiation

**Vision.** "Every student walks into a placement drive knowing exactly how ready they are, and every college knows it too, on a platform whose rules are published and fair."

| # | Differentiator | What we build | Why (evidence) |
|---|---|---|---|
| D1 | Placement-readiness engine | Skill-tagged mastery per topic, cohort percentiles, company-pattern readiness, weak-area next-practice recommendations, disclosed computation method | Incumbents show no public evidence of readiness analytics; Coursera admin metrics focus on consumption (RPA §7.1 [Rec], [Verified] Mass.gov guide) |
| D2 | TPO / coordinator console | Roster import, seat pool, batch progress, readiness distribution, mock-based shortlisting, exports | FACE Prep (2,000+ colleges claimed) runs on a white-label LMS (RPA §7.2 [Reported]) |
| D3 | Honest commerce | Real list prices (no inflated anchors), refund rule that includes discounted purchases, identical wording in marketing and Terms, one-click cancel, pre-renewal reminder | PrepInsta excludes discounted purchases from refunds [Verified]; Coursera Terms contradict its money-back claim [Verified]; dark-pattern rules from 1 Jan 2027 [Reported] (RPA §4, §7.3) |
| D4 | Transparent account-integrity centre | Published numbers (3 devices, 2 sessions, 1 stream, 2 replacements/30 days), self-service device list, explanation of every enforcement action, in-app appeal with stated response time | No Indian peer publishes a device limit (RPA §3 [Verified]) |
| D5 | Assessment resilience and dispute-ready integrity | Server deadline, autosave + IndexedDB mirror, immutable attempt steps, disconnects as events not penalties, advisory integrity flags with human review, provisional leaderboards | Moodle 60 s autosave is a trade-off [Verified]; HackerRank flags are 85% precise by its own statement [Verified] (RPA §5, §6) |
| D6 | Verified outcomes and credentials | Instant `/verify/{id}` certificate pages, content-completeness indicator per course, outcome claims with cohort and sample size | Coursera share links reportedly take 24–48 h [Reported]; complaints of "under construction" courses (RPA §4, §7.6) |

**Non-goals for differentiation.** Webcam/AI proctoring, browser fingerprinting and behavioural risk scoring of minors are explicitly not differentiators (RPA §3, §8).

---

## 3. Personas

Every persona maps to one canonical role key from the brief §3. Scope is the role-grant scope.

| ID | Persona | Role key / scope | Context | Goals | Pain points we solve | Auth tier (brief §1) |
|---|---|---|---|---|---|---|
| PER-01 | **Ananya, individual student** (21, final-year B.Tech, Tier-2 city, mid-range Android + shared family laptop, Jio 4G behind CGNAT) | `student` (own data) | Pays herself; price-sensitive; targets TCS/Infosys/Accenture drives in 3 months | Know weak areas fast; company-pattern mocks; affordable plan; certificate for LinkedIn | Fake "80% off" anchors, refund denial, buffering video (RPA §4) | 60 min / 24 h; MFA optional; remember device ≤ 30 days on trusted device |
| PER-02 | **Rahul, college-enrolled student** (20, pre-final year, college-sponsored seat) | `student` + `org_memberships` + `batch_members` | Access via coordinator invite; hostel Wi-Fi (one NAT IP for 800 students) | Complete assigned tests; see rank in batch; convert to own plan after graduation without losing history | Being flagged because the hostel shares one IP; losing history when seat ends | Same as PER-01; college may require MFA |
| PER-02m | **Meera, under-18 student** (17, first-year diploma/degree) | `student` with `is_minor=true` | Either guardian-consented D2C or college-sponsored | Same learning goals | Must not be profiled; parent must consent (DPDP s.9) | Same; no behavioural risk scoring, no marketing personalisation |
| PER-03 | **Dr. Suresh, college coordinator / TPO** | `college_coordinator` @ `organization:{id}` | Runs placements for 1,200 students across 6 departments; reports to principal weekly | Bulk onboard, assign mocks before drives, see readiness distribution, shortlist for company drives, export reports | No purpose-built TPO console on incumbents (RPA §7.2) | Staff: 30 min / 12 h, MFA mandatory |
| PER-04 | **Kavya, trainer** | `trainer` @ `batch:{id}` and/or `course:{id}` | Teaches aptitude and DSA to 4 batches; part-time | Build and schedule tests, grade assignments, give extra time to a student whose power failed, review integrity flags fairly | Reopening a whole test for one student; opaque plagiarism flags | Staff tier, MFA mandatory |
| PER-05 | **Arjun, content manager** | `content_manager` @ `platform` (or `course:{id}`) | In-house content team of 5 | Author/version question bank with explanations, peer review, publish company paths, track completeness | Duplicate questions, unreviewed answer keys | Staff tier, MFA mandatory |
| PER-06 | **Priya, placement mentor** | `placement_mentor` @ `batch:{id}` (or platform for D2C mentoring) | Ex-recruiter; conducts mock interviews | Manage slots, run interviews, record rubric feedback, review resumes | No-show handling, unstructured feedback (RPA §4 "Mentoring") | Staff tier, MFA mandatory |
| PER-07 | **Imran, support agent** | `support_agent` @ `platform` | Handles 150 tickets/day in English/Hindi | Resolve login/device/payment issues quickly; triage unblock requests | Cannot see why a user is blocked; must not see more than needed | Staff tier, MFA mandatory, step-up for session kills |
| PER-08 | **Neha, security reviewer** | `security_reviewer` @ `platform` | Reviews account-sharing and takeover cases | Explainable evidence, decide cases, handle appeals, tune rules safely | CGNAT false positives (RPA §3) | 15 min / 8 h, mandatory TOTP/passkey |
| PER-09 | **Vikram, finance admin** | `finance_admin` @ `platform` | Owns pricing, refunds, GST invoices, college billing | Reconcile Razorpay settlements, process refunds within SLA, issue B2B invoices with GSTIN | Webhook delays (UPI AutoPay 24–36 h, RPA §4 [Verified]) | 15 min / 8 h, mandatory TOTP/passkey |
| PER-10 | **Sanjay, super admin** | `super_admin` @ `platform` | CTO/ops lead | Onboard orgs, grant roles, set policy, approve sensitive actions, break-glass | Every action must be audited | 15 min / 8 h, passkey preferred |

**Individual vs college-enrolled student: differences that drive requirements**

| Aspect | Individual (PER-01) | College-enrolled (PER-02) |
|---|---|---|
| Account creation | Self-signup (FR-IDN-001) | Invite link / bulk import (FR-ORG-010); may also pre-exist as individual and be linked |
| Access source | Free tier, purchase, subscription, coupon | `institution_contracts` seat entitlement; may stack personal purchases |
| Who sees their data | Only themselves and platform staff with permission | Plus own college's coordinators/trainers/mentors, scoped to contract content and batch (BR-ENT-14, role-permission-matrix §6) |
| Payments | Razorpay checkout | None for sponsored content; optional personal upgrades |
| End of access | Expiry / cancellation / refund | Contract end, removal from org, graduation → conversion offer preserving history (FR-ORG-018) |
| Assigned work | Self-paced | Batch-assigned tests, assignments, drives with deadlines |
| Minors | Guardian consent required | College acts as data fiduciary, Tech Drona as processor (brief §1) |

---

## 4. Functional requirements

Format: `FR-<AREA>-NNN`. Areas: IDN identity, SES sessions/devices, SEC security & unblock, ORG orgs/colleges/batches, RBAC, CAT catalog & authoring, MED media, LRN learning, PLC placement prep, ASM assessments, COD coding, COM commerce, ENT entitlements, ANL analytics, NTF notifications, SUP support, PRV privacy, ADM admin/audit. Module column = brief §2 package.

### 4.1 Identity (`identity`)

| ID | Requirement | Pri | Status |
|---|---|---|---|
| FR-IDN-001 | Self-signup with email **or** Indian mobile number + password (or passkey). Fields: full name, email, mobile (+91, 10 digits), date of birth, password, consent checkboxes (itemised, FR-PRV-001). | P0 | Planned |
| FR-IDN-002 | **Age gate:** DOB collected at signup. If age < 18 on signup date, account is created in `pending_guardian_consent` state; only the guardian-consent screen and free public content are reachable until a guardian completes verifiable consent (`guardian_consents`), unless the student joins via a college invite where the college is data fiduciary (brief §1, RPA §8 "Minors"). | P0 | Planned |
| FR-IDN-003 | Email verification by single-use link (valid 24 h) and mobile verification by 6-digit OTP (valid 10 min, max 5 sends/number/hour, max 10/day). Unverified accounts may browse free content but cannot purchase or start a timed test. | P0 | Planned |
| FR-IDN-004 | Password policy per brief: min 15 chars without MFA, 8 with MFA, max ≥ 64 (accept 128), no composition rules, breached-password blocklist incl. context words ("techdrona", "drona"), paste allowed. Argon2id m=19456 KiB t=2 p=1. | P0 | Planned |
| FR-IDN-005 | Login by email or mobile + password; passkey login (WebAuthn); identical error message, status and timing for unknown user vs wrong password (ASVS 6.3.8). | P0 | Planned |
| FR-IDN-006 | MFA: passkey, TOTP, SMS OTP (restricted, rate-limited). Mandatory for all staff roles; mandatory TOTP/passkey (no SMS) for `finance_admin`, `security_reviewer`, `super_admin`. Optional for students; 10 single-use recovery codes. Email is never a second factor for staff. | P0 | Planned |
| FR-IDN-007 | Forgot password: single-use reset link (valid 30 min, stored hashed, no auto-login), or mobile OTP; success revokes all sessions (FR-SES-009). | P0 | Planned |
| FR-IDN-008 | Change email/mobile/MFA requires full re-authentication within the last 5 min and notifies the old contact channel. | P0 | Planned |
| FR-IDN-009 | Progressive per-account throttling: 1 s delay doubling to a 15 min cap; hard disable at `login.hard_disable_after_failures` consecutive failures (default 50, max 100; brief v0.2 §1) (unlocked by reset or MFA); separate per-IP/per-ASN windows down-weighted for CGNAT; pre-auth blocks do not count to lockout (RPA §8 baseline). A hard-disabled account receives the same `invalid_credentials` response as any failed login; the verified contact gets an out-of-band message with a reset link (v0.3, CPR-PRD-09). | P0 | Planned |
| FR-IDN-010 | Profile: name, photo (optional), college name (free text for individuals), graduation year, branch, target role, target companies, preferred language (English v1; Hindi UI P2). | P0 | Planned |
| FR-IDN-011 | "Sign in with Google" for students (OIDC), mapped to the same `users` row by verified email; disabled for staff roles. | P1 | Planned |
| FR-IDN-012 | Account linking: a college invite sent to an email that already has an individual account links the existing account to the org (no duplicate user); student sees a consent screen explaining what the college will see (BR-ENT-14). | P0 | Planned |
| FR-IDN-013 | Identity confirmation before a certificate-bearing final assessment: verified mobile + verified email + name confirmation (legal name lock after first certificate; changes go through support with document check). | P1 | Planned |

### 4.2 Sessions and devices (`sessions`)

Policy values are brief §1 defaults, editable in `policy_settings` by `super_admin` only (second-person approval, role-permission-matrix §5).

| ID | Requirement | Pri | Status |
|---|---|---|---|
| FR-SES-001 | Opaque server-side sessions, `__Host-td_session` cookie, only SHA-256 hash stored; rotate on login and privilege change; idle/absolute timeouts per role tier (brief §1). | P0 | Planned |
| FR-SES-002 | First-party device token (random ID in `__Host-` cookie / app keystore) identifies a device; `user_devices` records trust status (`pending_verification`, `trusted`, `revoked`). | P0 | Planned |
| FR-SES-003 | **New device ⇒ OTP verification** (email or SMS) before it becomes trusted. Until verified the session is limited to free content and account settings. | P0 | Planned |
| FR-SES-004 | Max **3 trusted devices** per student. Signing in on a 4th device shows "You have 3 registered devices. Remove one to continue" with the device list (last used date, browser/OS label, approximate state); removal counts as a replacement. | P0 | Planned |
| FR-SES-005 | Max **2 replacements per rolling 30 days** self-service. The 3rd replacement is refused with a link to support (support can perform it within quota rules, FR-SUP-007). Counter is shown on the devices page ("1 of 2 replacements used; resets on 14 Nov"). | P0 | Planned |
| FR-SES-006 | Max **2 concurrent active sessions**. A 3rd sign-in shows a soft prompt "You're signed in on 2 other devices — sign out the oldest and continue here?"; on confirm the oldest session is revoked. Unsaved work protection: an active test attempt session is never auto-revoked; the prompt names it and offers "cancel". A previous session on the same browser profile is replaced (`replaced_same_device`), not counted; if every other session holds an active attempt the sign-in is refused (`session_cap_reached`) (v0.3). | P0 | Planned |
| FR-SES-007 | Max **1 concurrent video playback stream**, enforced at VdoCipher OTP/token issuance (`playback_sessions`). Second stream shows interstitial PLY-005 with "Stop playback on other device and play here". | P0 | Planned |
| FR-SES-008 | Devices & sessions page (STU-022): list sessions (device label, approx. location, started, last active, current marker), revoke any session, revoke all others, remove device, rename device (ASVS 7.5.2). | P0 | Planned |
| FR-SES-009 | Kill all sessions on password reset, account disable, L4 restriction, and on user request. | P0 | Planned |
| FR-SES-010 | "Remember this device" (students only, trusted devices only): silent re-issue of a new (AAL1) session only on a top-level user navigation on a trusted device, within a fixed 30-day ceiling from the last full authentication; background requests never re-issue a session (v0.3, CPR-PRD-02); re-authentication required for payment, profile/contact change, device management and test start if auth older than 24 h. | P1 | Planned |
| FR-SES-011 | During an active timed-test attempt only **1 session** may submit answers for that attempt; the attempt is bound to one session (`test_attempts.bound_session_id`). A second session opening the attempt gets `409 attempt_bound_elsewhere` and a read-only "This test is open on another device" screen with "Continue here?"; rebinding needs explicit confirmation, OTP only when the restriction level is ≥ L2 (`assessment.rebind_requires_otp_at_level`), max **2 rebinds** per attempt, and proctored drives need a trainer override; each rebind logs `attempt_events.rebind` (brief v0.2 §1 Device policy, PO-08). See Contract change proposal CCP-01. | P0 | Planned |
| FR-SES-012 | All device/session limit events emit security signals (`security_signals`) for adults; for minors only deterministic cap events are logged (no behavioural scoring, brief §1). | P0 | Planned |

### 4.3 Account security, restrictions and unblock (`security`) — summary

The Security Specialist owns the detailed design (`docs/account-security-and-risk-engine.md`, `docs/account-unblock-workflow.md`). Product-level requirements:

| ID | Requirement | Pri | Status |
|---|---|---|---|
| FR-SEC-001 | Rule-based, versioned risk scoring (`risk_rules`, `risk_rule_versions`, `risk_evaluations`) over server-side signals; primary evidence is behavioural overlap (≥ 2 device tokens with overlapping playback/test sessions from physically separated networks (two fixed-line networks at the same time) over multiple days; OTP verification of a device does not discount such use), never IP or fingerprint alone (RPA §3 [Rec]). | P1 | Planned |
| FR-SEC-002a | Graduated restriction levels (`account_restrictions`), deterministic part: **L1** notice + soft prompt; **L2** re-verification by SMS OTP/passkey/TOTP of every device in the evidence (email OTP not accepted) and revocation of sessions above the cap, produced by deterministic caps and rules (v0.3, CPR-PRD-07). Exact thresholds: Security doc. | P0 | Planned |
| FR-SEC-002b | Graduated restriction levels, scored part: **L3** temporary restriction of premium content/playback and new test starts (account settings, billing, support, certificates verification remain available; `restricted` session scope) for a stated period; **L4** account suspension pending human review (`status_only` session scope; applied by a human only). Exact thresholds and durations: Security doc. | P1 | Planned |
| FR-SEC-003 | Every restriction shows the student a plain-language reason, the signal categories involved (e.g. "simultaneous video playback on 3 devices from 2 networks on 4 days"), the level, its end time, and the action available (verify, appeal). No restriction is applied silently. | P0 | Planned |
| FR-SEC-004 | Unblock request / appeal in-app (STU-026) and from the blocked-login interstitial (PUB-021); there is no unauthenticated unblock endpoint: an L4 user signs in to a `status_only` session limited to `account_status` routes (PO-07), and a hard-disabled account first recovers its credentials through password reset; stated response time: L3 ≤ 2 business days, L4 ≤ 3 business days. | P0 | Planned |
| FR-SEC-005 | Human review mandatory before L4; L4 lift on cases marked high-risk needs a second `security_reviewer` (or `super_admin`) approval (brief §1). | P1 | Planned |
| FR-SEC-006 | `support_agent` may lift L1/L2 only; never L3/L4 (role-permission-matrix §7). | P0 | Planned |
| FR-SEC-007 | Minors: no behavioural risk scoring; only deterministic caps (FR-SES-004..007, -011) can produce L1/L2 outcomes; L3/L4 for minors only via human case (e.g. credential resale evidence) with guardian/college notification. | P0 | Planned |
| FR-SEC-008 | Wrongful restriction remedy: if a restriction is overturned (also when an `uphold` is later overturned), credit = ceil(restricted days, including any L4 period of the same case) to every time-bound entitlement active during the restriction; institution-contract seats only up to the contract end (remainder recorded and handled by support) (BR-ENT-12; PO-10 to confirm). | P1 | Planned |
| FR-SEC-009 | Account-integrity centre (part of STU-022/STU-026): published policy numbers, device list, replacement quota, restriction history, appeal status. The published device-policy text (PO-02) states: "Verifying a device with a code does not exempt simultaneous use from two different home or college networks" (v0.3, CPR-PRD-11). | P0 | Planned |
| FR-SEC-010 | Configured high-confidence rules (HC-01, HC-02) may apply a temporary L3 automatically for adults; each rule runs ≥ 14 days in shadow, needs dual approval, can be switched off instantly (kill switch) and is returned to shadow automatically on a false-positive spike. Never L4, never minors (v0.3, CPR-PRD-06; RE §5.6). | P1 | Planned |

### 4.4 Organizations, colleges and batches (`orgs`)

> **Removed (single-company, ADR-0015).** College organizations, contracts, seats, invitations, roster import and coordinators are removed. Only batches remain (Tech Drona cohorts, managed by Admin at `/admin/batches`; members are existing accounts added one by one). Requirements below about colleges are retained for history only.

| ID | Requirement | Pri | Status |
|---|---|---|---|
| FR-ORG-001 | `super_admin` creates an organization (college): legal name, display name, short code, address, GSTIN (optional), primary contact, logo, data-fiduciary role (college as fiduciary; Tech Drona as processor), DPA reference, status (`onboarding`, `active`, `suspended`, `ended`). | P0 | Planned |
| FR-ORG-002 | Org-level settings: require MFA for students (on/off), allowed email domains for invite acceptance (optional), default batch visibility, student data visible to trainers (on by default within batch). | P1 | Planned |
| FR-ORG-003 | Coordinator creates batches: name, department, graduation year, start/end dates, linked courses/tests, assigned trainers/mentors (`batches`). | P0 | Planned |
| FR-ORG-004 | Batch membership management: add/remove students, move student between batches (history retained per batch). | P0 | Planned |
| FR-ORG-010 | **Bulk import** via CSV/XLSX template (columns: full_name, email, mobile, roll_number, department, graduation_year, batch_code, date_of_birth optional). Max 5,000 rows per file. Validation preview shows per-row errors (invalid email/mobile, duplicate in file, already member, seat pool exhausted) before commit. Commit is idempotent (re-upload of same file does not duplicate). | P0 | Planned |
| FR-ORG-011 | Bulk invite: commit sends invite emails (and SMS if mobile present) with single-use link valid 14 days; resend allowed max 3 times; coordinator sees invite status (`sent`, `opened`, `accepted`, `expired`, `bounced`). | P0 | Planned |
| FR-ORG-012 | Invite acceptance (PUB-016): new user sets password and verifies mobile; existing user signs in and links (FR-IDN-012); minors through college invite skip guardian-consent flow only if org is configured as data fiduciary and has confirmed it holds parental consent (checkbox + DPA clause). | P0 | Planned |
| FR-ORG-013 | Seat assignment from contract seat pool on acceptance (or at import, configurable): creates an `entitlements` row with source `institution_contract` (BR-ENT-15..18). | P0 | Planned |
| FR-ORG-014 | Coordinator assigns tests/mocks/drives to batches with window (open/close), attempt limit, and result release mode; assignment notifies students. | P0 | Planned |
| FR-ORG-015 | Coordinator reports (COL-008): batch progress, test results, readiness distribution, time-on-task summary, seat utilisation; export CSV/XLSX (async, link valid 24 h, audited, PII export requires step-up). | P0 | Planned |
| FR-ORG-016 | Shortlist builder: filter batch students by mock score/percentile, topic mastery, attendance, and export as a shortlist for a company drive. | P1 | Planned |
| FR-ORG-017 | Coordinator can grant `trainer` / `placement_mentor` at `batch:{id}` scope only within own org, only to users with a staff `org_memberships` row; audited (role-permission-matrix §3). | P1 | Planned |
| FR-ORG-018 | Graduation / removal: student retains account, history, certificates; sponsored entitlements end per BR-ENT-17; student receives a conversion offer to an individual plan; college loses visibility of activity after removal date (historical reports keep aggregated/pseudonymised data per DPA). | P0 | Planned |
| FR-ORG-019 | Placement drives: coordinator records a company drive (company, date, eligibility criteria: CGPA min, backlogs max, branches, graduation year), links a mock, and generates eligible list. See CCP-03. | P2 | Planned |

### 4.5 RBAC (`rbac`) — summary

| ID | Requirement | Pri | Status |
|---|---|---|---|
| FR-RBAC-001 | Allow-only permissions, deny by default, granted via `role_grants` (user, role, scope). Scopes: `platform`, `organization:{id}`, `batch:{id}`, `course:{id}` (brief §3). Full matrix: `docs/role-permission-matrix.md`. | P0 | Planned |
| FR-RBAC-002 | A user may hold multiple grants (e.g. trainer in two batches + student elsewhere); UI shows a portal switcher listing only portals for which the user has a grant. | P0 | Planned |
| FR-RBAC-003 | Every endpoint declares permission + scope; the blocked/restricted check is enforced centrally by `require_active_principal` (brief §5). | P0 | Planned |
| FR-RBAC-004 | Grants have optional `expires_at`; expired grants are inert; grants/revocations audited. | P0 | Planned |

### 4.6 Catalog and course authoring (`catalog`, `media`)

| ID | Requirement | Pri | Status |
|---|---|---|---|
| FR-CAT-001 | Course structure: `courses` → `course_versions` → `course_modules` → `lessons` → `lesson_assets`; lesson types: video, article (rich text + code blocks + LaTeX), PDF/resource, embedded practice set, quiz (assessment), coding problem, assignment, live-session link. | P0 | Planned |
| FR-CAT-002 | Versioning: authors edit a draft version; publishing creates an immutable published version. Enrolled students stay on their version unless the change is marked "minor" (typo/asset fix), which auto-migrates progress; "major" versions prompt opt-in migration. | P1 | Planned |
| FR-CAT-003 | Course metadata: title, slug, summary, outcomes, prerequisites, level, language, duration estimate, tags (topics), thumbnail, trailer (free preview lesson flag per lesson), certificate eligibility rule, **completeness indicator** (% of planned lessons published, with public roadmap dates) (D6). | P0 | Planned |
| FR-CAT-004 | Workflow states: `draft` → `in_review` → `published` → `archived`; publish requires `course.publish`; author ≠ publisher for platform catalog (separation of duties, role-permission-matrix §7). | P0 | Planned |
| FR-CAT-005 | Free preview: lessons flagged `is_free_preview` are viewable by any signed-in user (video) or public (articles), for SEO and conversion. | P0 | Planned |
| FR-CAT-006 | Resources (`resources`): PDFs, cheat sheets, interview question PDFs; access level `public`, `signed_in`, `entitled`; downloads served via short-lived signed CloudFront URLs (≤ 5 min), watermarked PDF with user email for `entitled` resources (P1). | P0 | Planned |
| FR-CAT-007 | Media upload to VdoCipher via `media` module; no videos in Postgres; upload status (`uploading`, `processing`, `ready`, `failed`). | P0 | Planned |
| FR-CAT-008 | Catalog browse & search: filter by category (aptitude, programming, DSA, CS fundamentals, company, interview), level, price type (free/paid/included in plan), language; full-text search on title/summary/tags. | P0 | Planned |
| FR-CAT-009 | Trainers with `course.edit` at `course:{id}` scope can author org-private courses visible only to their org's batches. | P1 | Planned |
| FR-MED-001 | Video playback through VdoCipher with Widevine/FairPlay DRM and dynamic watermark showing user name + masked mobile (e.g. `Ananya • 98xxxxxx21`), randomly repositioned; iframe embed not used where it prevents user-ID watermark (RPA §3). | P0 | Planned |
| FR-MED-002 | Playback speed 0.75–2×, quality auto/manual, captions (English) where available, resume from last position, keyboard controls. | P0 | Planned |

### 4.7 Learning, progress, assignments and certificates (`learning`)

| ID | Requirement | Pri | Status |
|---|---|---|---|
| FR-LRN-001 | Enrolment created when an entitlement covering a course is first used or when a batch is assigned the course (`enrolments`); enrolment never grants access by itself — access is always checked against `entitlements` (§4.12). | P0 | Planned |
| FR-LRN-002 | Lesson progress (`lesson_progress`): video completion = ≥ 90% of duration watched (unique seconds); article = scrolled to end + ≥ 30% of estimated read time on visible tab; quiz = submitted; assignment = submitted. | P0 | Planned |
| FR-LRN-003 | Course progress % = completed required lessons / required lessons; "Continue where you left off" on dashboard. | P0 | Planned |
| FR-LRN-004 | Assignments: trainer creates assignment (instructions, attachments, due date, late policy: accept with penalty % per day up to N days, or reject), max file size 20 MB, allowed types (pdf, zip, docx, txt, code files), or code submission linked to a coding problem. | P1 | Planned |
| FR-LRN-005 | Grading: rubric (criteria × levels) or points; inline comments; return for resubmission; grade release per assignment; grade changes after release require reason and are audited. | P1 | Planned |
| FR-LRN-006 | Certificates: issued automatically when course completion rule is met (e.g. 100% required lessons + final test ≥ 60%); unique ID (non-guessable, 12-char base32), PDF + public `/verify/{certificate_id}` page live instantly showing name, course, issue date, identity-verified flag, status (valid/revoked) (RPA §6 [Rec]). | P1 | Planned |
| FR-LRN-007 | Certificate revocation (e.g. confirmed integrity violation, refund) by `certificate.revoke` holder with reason; verify page shows "revoked on DATE" without stating the reason. | P1 | Planned |
| FR-LRN-008 | "Add to LinkedIn" button with pre-filled certification fields. | P1 | Planned |
| FR-LRN-009 | Bookmarks and notes on lessons and questions. | P1 | Planned |

### 4.8 Placement preparation (`placement`)

Taxonomy uses `topics` (subject → topic → subtopic) mirroring the market IA (RPA §1 [Verified] IndiaBix/GfG).

| ID | Requirement | Pri | Status |
|---|---|---|---|
| FR-PLC-001 | Subjects (v1 seed): **Quantitative Aptitude** (number system, percentages, profit & loss, time & work, time-speed-distance, ratios, averages, P&C, probability, mensuration, data interpretation…), **Logical Reasoning** (series, coding-decoding, blood relations, direction sense, seating arrangement, syllogisms, puzzles, data sufficiency…), **Verbal Ability** (reading comprehension, sentence correction, para-jumbles, vocabulary, fill-in-the-blanks, error spotting), **Programming** (C, C++, Java, Python fundamentals, output prediction, OOP), **DSA** (arrays, strings, linked lists, stacks/queues, trees, graphs, DP, greedy, sorting/searching, hashing), **CS Fundamentals** (OS, DBMS/SQL, Computer Networks, OOP concepts, basic system design for freshers), **Interview** (technical, HR). | P0 | Planned |
| FR-PLC-002 | Question bank (`questions`, `question_versions`, `question_options`, `question_tags`): types single-choice MCQ, multi-select, numeric answer (tolerance), fill-in-blank (exact/regex), true/false, output prediction, passage-based group (RC/DI with child questions), coding (link to `coding_problems`). | P0 | Planned |
| FR-PLC-003 | Every question carries: difficulty (1–5), topic/subtopic tags, company tags, expected time (seconds), **mandatory step-by-step explanation** (rich text/LaTeX/image) and optional video explanation, source attribution, "pattern-aligned practice" labelling (never "actual questions", RPA §6). | P0 | Planned |
| FR-PLC-004 | Question lifecycle: `draft` → `in_review` → `published` → `retired`; reviewer ≠ author; published versions immutable; edits create a new version; attempts reference the version answered. | P0 | Planned |
| FR-PLC-005 | Practice mode (untimed): student picks subject/topic/difficulty; gets sets of 10 questions; immediate correctness + explanation after each answer; retry incorrect; adaptive next set (P1). | P0 | Planned |
| FR-PLC-006 | Topic mastery score per student per subtopic (0–100), computed from correct/incorrect, difficulty and recency (method disclosed on the analytics page; details owned by Analytics Engineer). | P1 | Planned |
| FR-PLC-007 | **Company paths** (`companies`, `company_paths`): per company (e.g. TCS NQT, Infosys, Wipro, Accenture, Cognizant, Capgemini, HCL, Tech Mahindra, Deloitte, Amazon/Microsoft SDE-intern track): exam pattern (sections, question counts, time, negative marking), syllabus mapped to topics, ordered practice sets, sectional and full mocks, interview experiences (curated), HR question set. Free public hub page + entitled content. | P0 | Planned |
| FR-PLC-008 | Technical interview prep: curated question sets by role (SDE, analyst, testing, support) with model answers, follow-up probes; self-rated readiness checklist. | P1 | Planned |
| FR-PLC-009 | HR interview prep: common HR questions with frameworks (STAR), sample answers, record-yourself practice (local only, not uploaded in v1). | P1 | Planned |
| FR-PLC-010 | Mock interviews with mentors: mentor publishes slots (30/45/60 min), student books (entitlement: premium placement package), video link (external meeting URL in v1), rubric feedback (communication, problem solving, technical depth, confidence, each 1–5 + comments) visible to student within 48 h; no-show by mentor ⇒ automatic credit back of the session and apology notification; student no-show after 10 min ⇒ session consumed unless rescheduled ≥ 12 h before. See CCP-02. | P1 | Planned |
| FR-PLC-011 | **Personalised recommendations**: "Next best practice" list (max 5 items) based on lowest-mastery subtopics weighted by target company syllabus and days to target drive date; each item shows "why recommended". For minors: computed only from assessment/practice results for learning delivery; no engagement-based or commercial recommendations (BR-MIN-02). | P1 | Planned |
| FR-PLC-012 | **Skill analytics** (STU-010): accuracy and average time per subject/topic, mastery heatmap, percentile in batch (college) and in platform cohort (same graduation year), trend over 8 weeks, strongest/weakest 3 topics, company readiness score (% of company syllabus with mastery ≥ 60). | P1 | Planned |
| FR-PLC-013 | Diagnostic test: 30-minute free test (Quant 10, Logical 10, Verbal 10 questions) used at onboarding; result seeds the personalised path. | P0 | Planned |
| FR-PLC-014 | Goal picker (onboarding): target companies (max 5), target role, expected drive date, current year; editable later. | P0 | Planned |
| FR-PLC-015 | **Resume and career prep**: resume builder with 2 ATS-friendly templates (sections: education, skills, projects, internships, achievements, certifications auto-filled from Tech Drona certificates), PDF export, resume checklist score; mentor resume review request (premium) with comments. | P1 | Planned |
| FR-PLC-016 | Learning path: ordered sequence of courses/practice sets/mocks generated from goal + diagnostic; student can reorder or skip. | P1 | Planned |
| FR-PLC-017 | Question reporting: student can report an error in a question (wrong key, typo, unclear); creates content review ticket for content managers; reporter notified on resolution. | P0 | Planned |
| FR-PLC-018 | Bulk question import (CSV/XLSX/QTI-like JSON) with preview and validation; imported questions enter `draft`. | P1 | Planned |

### 4.9 Assessments (`assessments`)

| ID | Requirement | Pri | Status |
|---|---|---|---|
| FR-ASM-001 | Test definition (`tests`, `test_sections`, `test_section_rules`): sections with own time limit (sectional timing) or a single overall timer; per-section rules draw N questions by topic/difficulty/tag from the bank (random draw) or fixed questions; shuffle questions/options; marking: +marks, negative marks, partial credit for multi-select; section navigation: free or sequential (no return). | P0 | Planned |
| FR-ASM-002 | Test types: practice quiz (in course), sectional mock, full company-pattern mock, diagnostic, batch assessment/drive test, final certificate test. | P0 | Planned |
| FR-ASM-003 | Schedule & availability: open/close window, duration, max attempts, attempt grading (highest, latest, first, average), eligible audience (entitlement / batch assignment). | P0 | Planned |
| FR-ASM-004 | **Server-authoritative timer**: `started_at` and `deadline_at` stored server-side; client clock displays server-derived remaining time, re-synced every 60 s and on reconnect; a server job auto-submits at deadline + configured grace (default 0 s for drives, 30 s for practice mocks). | P0 | Planned |
| FR-ASM-005 | **Autosave**: answers saved on change with 5 s debounce (max 10 s after the first unsynced change; server returns `max_interval_ms: 10000`), idempotent by (attempt, question, version); mirrored in IndexedDB; save indicator ("Saved 3 s ago" / "Offline — answers stored on this device"); on reconnect pending answers flush in order. | P0 | Planned |
| FR-ASM-006 | **Resume**: if the browser closes or crashes, reopening the test within the window resumes the same attempt with answers and remaining time (time keeps running server-side; disconnects are logged as `attempt_events`, not penalties). | P0 | Planned |
| FR-ASM-007 | Per-user and per-batch **overrides** (`test.override.grant`): extra time (minutes), extra attempt, extended close date; reason required; audited. | P0 | Planned |
| FR-ASM-008 | **Review visibility matrix** (4 phases adopted from Moodle, RPA §5 [Verified]): during attempt / immediately after / after close / after results release; per phase toggles: score, correct/incorrect, correct answer, explanation, section analytics, rank. | P0 | Planned |
| FR-ASM-009 | Results: score, section scores, accuracy, time per question, attempted/skipped, rank and percentile (provisional until integrity pass completes, D5), comparison with topper and batch average, question-by-question review per review matrix. | P0 | Planned |
| FR-ASM-010 | Integrity events (advisory): full-screen exit, tab hidden/visible, window blur, paste (logged not blocked), device switch, IP/network change (adults only), multiple session attempt. Shown to trainers as "review recommended" with evidence; never auto-penalise. Settings lock once the first attempt starts. | P0 | Planned |
| FR-ASM-011 | Immutable attempt steps (`attempt_responses` append-only with sequence numbers) enable regrade after answer-key correction; regrade recomputes results and notifies affected students. | P0 | Planned |
| FR-ASM-012 | Attempt invalidation by trainer/coordinator with `attempt.invalidate` only after human review; student notified with reason and appeal link. | P1 | Planned |
| FR-ASM-013 | Accessibility in tests: per-student accommodation profile (extra time %, high contrast, screen reader-compatible question rendering, no time-pressure warnings) applied automatically as overrides. | P1 | Planned |
| FR-ASM-014 | Question palette with states: not visited, not answered, answered, marked for review, answered & marked (matches Indian exam-UI conventions). | P0 | Planned |
| FR-ASM-015 | Leaderboard per test (opt-in display name or anonymised "Student #1234"); provisional until post-test similarity pass completes. | P1 | Planned |

### 4.10 Coding practice (`coding`)

| ID | Requirement | Pri | Status |
|---|---|---|---|
| FR-COD-001 | Problem model (`coding_problems`): statement (Markdown + LaTeX), constraints, input/output format, sample cases (visible), hidden test cases (`coding_test_cases` hidden flag, stored encrypted/private, never sent to the browser), per-case weight, time limit (default 2 s CPU, 5 s wall per case), memory limit (default 256 MB), allowed languages, starter code per language, editorial (unlock after solve or after N attempts), difficulty, topic/company tags. | P0 | Planned |
| FR-COD-002 | Languages v1: C (GCC), C++17, Java 17, Python 3.11; P1 adds JavaScript (Node), Go; P2 adds C#, Kotlin (RPA §4 "6–8 languages"). | P0 | Planned |
| FR-COD-003 | Editor workspace: Monaco-based editor, language switcher, font size, light/dark, custom stdin, reset to starter code, keyboard shortcuts (Ctrl+Enter run, Ctrl+Shift+Enter submit); code autosaved per problem per language every 5 s. | P0 | Planned |
| FR-COD-004 | **Run** executes sample + custom input only; **Submit** executes all hidden cases via `judge-gateway` → Judge0 Cloud; per-case verdicts AC/WA/TLE/MLE/RE/CE shown for samples, hidden cases shown as "Case 7: Wrong Answer" without input/expected output; score = Σ weights of passed cases. | P0 | Planned |
| FR-COD-005 | Rate limits: Run max 10/min, Submit max 5/min per user per problem, max 1 in-flight submit per user (policy keys `coding.run_per_minute`, `coding.submit_per_minute`, `coding.max_inflight_submits`); per-user judge queue; assessment submissions are never shed; during a test, submissions are prioritised over practice traffic. | P0 | Planned |
| FR-COD-006 | Submission history (`code_submissions`, `submission_results`): code, language, verdict, score, runtime, memory, timestamp; diff between submissions. | P0 | Planned |
| FR-COD-007 | Coding questions inside tests (FR-ASM-001) share the same workspace with the test's server timer; last submission (or best, configurable) counts. | P0 | Planned |
| FR-COD-008 | Similarity check (MOSS/JPlag-style) within a test cohort after close; pairs above threshold create advisory integrity flags with side-by-side diff for trainer review. | P1 | Planned |
| FR-COD-009 | Code snapshot replay for reviewers (keystroke-level snapshots every 10 s during tests) — adults only; minors: final submissions only. | P2 | Planned |
| FR-COD-010 | Judge outage handling: if `judge-gateway` reports provider unavailable, Submit queues (max 15 min) with visible status "Queued — results will appear here"; tests extend deadline automatically by outage duration for affected attempts (logged override). | P0 | Planned |

### 4.11 Commerce (`commerce`)

| ID | Requirement | Pri | Status |
|---|---|---|---|
| FR-COM-001 | **Product types** (`products`): `free_resource` (no price; public or signed-in), `free_course` (no price; enrolment requires sign-in), `course` (one-time purchase, validity N days or a fixed end date), `bundle` (set of courses/paths), `subscription_plan` (all-access tier; `plans` + `prices` with interval monthly/quarterly/annual), `placement_package` (premium: company paths + N mentor interviews + resume review + priority support, fixed validity), `mock_pack` (N full mocks), `institution_seat` (B2B only, never sold online); reserved: `extra_learner_seat` (paid buddy seat, Phase 3). This list is exactly the `products.product_kind` CHECK in `database-schema.md` §11 (brief v0.3). | P0 | Planned |
| FR-COM-002 | Prices in INR, GST-inclusive display for D2C (18% GST shown as a breakdown at checkout; the final price never changes after the product page). List price = selling price: no anchor/strike-through unless a real time-bound sale with start/end dates where the pre-sale price was actually charged for ≥ 30 days (CCPA dark-pattern guidance, RPA §4 [Reported]). | P0 | Planned |
| FR-COM-003 | Checkout: create `orders` + `order_items` server-side, then a Razorpay order, then Razorpay Checkout (UPI, cards, netbanking, wallets). Payment is confirmed only via a verified webhook (HMAC over raw body, constant-time compare, dedupe by event ID in `payment_webhook_events`; Razorpay signs no timestamp so events are never rejected by age; for timestamp-signed providers (Cashfree) a payload older than 5 min is not trusted; any stale or out-of-order event is applied only from a server-side re-fetch of the entity, ADR-0006) or verified signature + server-side fetch. Idempotency-Key on order creation. | P0 | Planned |
| FR-COM-004 | Order status page (STU-017): `created` → `pending_payment` → `paid` / `failed` / `expired` (30 min); later states `cancelled`, `refunded`, `partially_refunded` (statuses = `orders.status` CHECK). A paid order triggers the entitlement grant within 60 s p95. If the webhook is delayed the page polls and shows "Payment received by bank, confirming…" for up to 15 min, then "We will email you when confirmed" + support link. | P0 | Planned |
| FR-COM-005 | **Subscriptions** via Razorpay Subscriptions / UPI AutoPay. Every recurring debit ≤ ₹15,000 (plan configuration rejects higher recurring amounts). Pre-debit notification ≥ 24 h before each debit; reminder email 7 days before an annual renewal; **one-click cancel** (STU-018) effective at period end with immediate confirmation. Cashfree fallback adapter (P1). | P0 | Planned |
| FR-COM-006 | Plan change: upgrade immediately with prorated charge (remaining days × daily price difference); downgrade at next renewal. | P1 | Planned |
| FR-COM-007 | **Coupons** (`coupons`, `coupon_redemptions`): percent / flat / 100%-free-access; applicable products; validity window; global and per-user redemption caps; min order value; new-users-only flag; org-restricted (college code). Max 1 coupon per order. A coupon > 50% off or with > 1,000 redemptions requires second finance approval. | P0 | Planned |
| FR-COM-008 | **Refunds** (`refunds`): one rule used identically in Terms, product page and checkout (D3): full refund within **7 days of purchase if < 20% of the content is consumed and no certificate is issued, including discounted purchases** (RPA §4 [Rec]). Subscriptions: first payment only under the same rule; renewals not refundable but cancellable. Placement packages: refundable minus consumed mentor sessions at their listed unit price. Mock packs: refundable if no mock started. Student requests in-app; finance decides within 5 business days; refund to original method via Razorpay. | P0 | Planned |
| FR-COM-009 | **GST invoices** (`invoices`): auto-generated for every paid order with a sequential number per financial year, SAC code, GST breakup (CGST+SGST or IGST by state of supply), buyer GSTIN when provided (B2B); credit notes for refunds; retained 72 months (brief §1). | P0 | Planned |
| FR-COM-010 | **Institution contracts** (`institution_contracts`): org, products/plans covered, seat count, start/end dates, price per seat, PO number, billing schedule (upfront / milestones), grace days after end (default 7), seat reassignment allowance (default 10% of seats), data-sharing scope, status (`draft`, `active`, `expired`, `terminated`). B2B invoices issued by finance against the contract. | P0 | Planned |
| FR-COM-011 | College-sponsored students may still buy personal products; checkout warns when the product is already covered by their college seat (BR-ENT-06). | P0 | Planned |
| FR-COM-012 | Chargeback/dispute webhook moves the related entitlement to `suspended` (BR-ENT-11) and opens a finance task. | P1 | Planned |
| FR-COM-013 | Reconciliation (FIN-009): daily comparison of `payments` against the Razorpay settlement report; mismatches listed for manual action. | P1 | Planned |
| FR-COM-014 | Never store card data; keep only gateway token, last 4 digits and issuer (RPA §4 [Verified] RBI). | P0 | Planned |

### 4.12 Entitlements (`entitlements`): the central access system

All content and feature access is decided by **one** access check, `can_access(user, resource, action, at=now)`, evaluated by the `entitlements` module and nowhere else. Courses, lessons, practice sets, tests, coding problems, company paths, mentor sessions and resources each declare an **access requirement** (`public`, `signed_in`, `free_enrolment`, or a list of product/plan IDs that unlock it). Orders, subscriptions, contracts, coupons and admin actions create, extend, suspend or revoke `entitlements` rows. They never grant access directly.

**Entitlement row (product view).** user; product/plan/feature scope; `source_type` (`free_enrolment`, `purchase`, `subscription`, `placement_package`, `coupon_grant`, `institution_contract`, `admin_grant`, `trial`); `source_id` (order/subscription/contract/coupon/grant); `organization_id` (institution grants); `starts_at`; `ends_at` (null only for free enrolments); `grace_ends_at`; `status` (`active`, `grace`, `suspended`, `expired`, `revoked`); quotas (`mentor_sessions_remaining`, `mocks_remaining`, `resume_reviews_remaining`); `revoke_reason`. Every change is also appended to the `entitlement_events` history table. Final column list is the System Architect's (`database-schema.md` §11; see CCP-05).

| ID | Requirement | Pri | Status |
|---|---|---|---|
| FR-ENT-001 | Single access-check service used by the API, BFF route guards and VdoCipher token issuance. The result includes `allowed`, `reason_code` (`ENTITLED`, `NO_ENTITLEMENT`, `EXPIRED`, `IN_GRACE`, `SUSPENDED_PAYMENT`, `ACCOUNT_RESTRICTED`, `MINOR_CONSENT_PENDING`, `NOT_VERIFIED`), the winning entitlement ID and an upsell hint. | P0 | Planned |
| FR-ENT-002 | "What I have access to" page (STU-019): each entitlement with source, start/end dates, remaining quotas and renewal status. | P0 | Planned |
| FR-ENT-003 | Access check p95 ≤ 20 ms (cached per user, invalidated on any entitlement change event). | P0 | Planned |
| FR-ENT-004 | Every create/extend/suspend/revoke writes `audit_log` with actor and source. | P0 | Planned |
| FR-ENT-005 | Manual/comp grants (`entitlement.grant.manual`) require a reason, max validity 365 days, and appear in finance reports. | P1 | Planned |

**Entitlement business rules (all Planned)**

| Rule | Statement |
|---|---|
| BR-ENT-01 **Union** | Access is allowed if **any** entitlement in status `active` or `grace` covers the resource at the requested time. Entitlements never subtract from each other. |
| BR-ENT-02 **Precedence for attribution** | When several entitlements cover the same resource, the "winning" one (used for analytics attribution, quota consumption and data visibility) is chosen in this order: (1) `institution_contract`, if the resource is in contract scope and the student is an active org member; (2) `placement_package`; (3) `subscription`; (4) `purchase` / `coupon_grant`; (5) `admin_grant` / `trial`; (6) `free_enrolment`. Ties go to the one ending latest. |
| BR-ENT-03 **Quota consumption** | Consumable quotas (mentor sessions, mock packs) are drawn from the entitlement ending soonest, so the student never loses quota to expiry unnecessarily. |
| BR-ENT-04 **Restriction overrides access** | An L3/L4 account restriction denies premium access regardless of entitlements (`ACCOUNT_RESTRICTED`). Entitlement dates are not changed by the restriction itself (see BR-ENT-12). Free resources, billing, support, the devices page, certificate verification and data export stay available. |
| BR-ENT-05 **Duplicate purchase prevention** | Checkout blocks buying a product the user already holds with an `active` entitlement whose `ends_at` ≥ the new product's would-be `ends_at`, showing "Already included in your <source> until <date>". |
| BR-ENT-06 **Overlap with college seat** | If a product is covered by an active college seat, checkout warns "Included via <College> until <contract end>". Purchase is allowed (the student may want access beyond the contract); the purchased entitlement starts immediately (no deferred start in v1). |
| BR-ENT-07 **Subscription + course purchase** | Holding a subscription does not block a one-time course purchase; checkout shows the overlap and the purchase validity. Cancelling the subscription never affects purchased entitlements. |
| BR-ENT-08 **Expiry** | Entitlements expire at `ends_at` (stored UTC, displayed IST). A timed attempt started before expiry continues until its own deadline. Progress, attempts, notes and certificates are never deleted on expiry; content becomes locked with a renewal CTA. |
| BR-ENT-09 **Subscription grace** | On a failed renewal debit the entitlement moves to `grace` for **5 days** (covers the 24–36 h UPI AutoPay webhook delay, RPA §4 [Verified]) with access retained and gateway retries. Grace length is policy key `commerce.subscription_grace_days` (default 5, bounds 3–7). No success by the end of grace → `expired`. Success during grace restores `active` with the original period boundary. |
| BR-ENT-10 **Refund revocation** | An approved refund revokes the linked entitlement immediately (`revoked`, reason `refund`). Partial refunds of a bundle revoke only the refunded items. Certificates issued under a refunded entitlement are revoked (the standard rule already excludes certificate-issued purchases, so this applies only to goodwill refunds, which need a second finance approver). |
| BR-ENT-11 **Chargeback** | A dispute suspends the entitlement (`suspended`, `SUSPENDED_PAYMENT`). Dispute won → `active`, dates unchanged. Dispute lost → `revoked`. |
| BR-ENT-12 **Wrongful-restriction compensation** | If an L3/L4 restriction is overturned on appeal (including an `uphold` later overturned), every time-bound entitlement that was `active` during the restriction is extended automatically by ceil(restricted days, including any L4 period of the same case), with an audit entry. Institution-contract seats are extended only up to the contract end; the remainder is recorded (`conditions.uncredited_days`) and handled by support (PO-10 to confirm). |
| BR-ENT-13 **Trials** | One trial per user per plan family (user + verified mobile). A trial converts only on explicit payment (no card-on-file auto-conversion in v1). |
| BR-ENT-14 **College data visibility** | Coordinators, trainers and mentors of the student's org see activity, progress, attempts and analytics on resources in the contract scope or assigned to the student's batch, from membership start to membership end. Activity on personally purchased content outside the contract scope is not visible to the college unless the student opts in ("Share all my prep progress with my college"). |
| BR-ENT-15 **Seat assignment** | A contract has `seat_count`. A seat is consumed when an `institution_contract` entitlement is created for a member. Import/invite fails with "Seat pool exhausted (1,200/1,200)" when no seat is free; the coordinator may queue invites as `waitlisted`. |
| BR-ENT-16 **Seat release and reassignment** | Removing a student from the org (or revoking the seat) ends the contract entitlement at removal time. The seat returns to the pool **freely** if the student had < 5% contract-content consumption **and** < 14 days since seat assignment. Otherwise it is a "used seat" and returns to the pool only while the contract's reassignment allowance (default 10% of `seat_count`) is not exhausted. Coordinators see "Reassignments used: 34 of 120". |
| BR-ENT-17 **Contract end** | At contract `end_date`, contract entitlements move to `grace` for the contract's `grace_days` (default 7), then `expired`. Students keep history and certificates and receive a conversion offer (FR-ORG-018). Renewal before expiry extends entitlements in place without re-invites. |
| BR-ENT-18 **Contract termination** | Early termination (finance + super admin dual control) expires entitlements at the termination date + 7 days; no further grace. |
| BR-ENT-19 **Org suspension** | Org status `suspended` (e.g. invoice unpaid > 60 days) suspends contract entitlements; the students' personal entitlements are unaffected. |
| BR-ENT-20 **Free tiers** | `free_resource` needs no entitlement row. `free_course` creates a `free_enrolment` entitlement with no end date on first enrolment, so progress and certificates work uniformly. |
| BR-ENT-21 **Minors** | Paid D2C entitlements for a minor can be created only after guardian consent is `verified`; checkout for a minor shows the guardian as payer contact. |
| BR-MIN-01 **Minor monitoring** | For `is_minor=true`: only deterministic caps and security-necessary logs; no sharing-family signals or evaluations (takeover handled by deterministic rules only, no score), no fingerprinting, no IP/ASN-based scoring, no code keystroke replay (brief §1). |
| BR-MIN-02 **Minor personalisation** | Recommendations for minors use only assessment/practice results for learning delivery; no engagement-based nudges, no commercial recommendations, no marketing messages. |
| BR-EVD-01 **Learning evidence** | No completion, certificate or grade may depend on time thresholds alone; each requires server-verifiable evidence (video coverage + quiz, accepted submissions, attempt scores). Browser time is forgeable (analytics CP-12; brief v0.2 §1). |

### 4.13 Analytics and time tracking (`analytics`): summary

The detailed event schema and time-on-task model are owned by the Analytics Engineer (`docs/analytics-event-schema.md`).

| ID | Requirement | Pri | Status |
|---|---|---|---|
| FR-ANL-001 | xAPI-shaped events (actor, verb, object, context, result) into monthly-partitioned `analytics_events`. Client events batched (max 100 per request, analytics doc §5.2; flush every 15 s and on `visibilitychange`). | P0 | Planned |
| FR-ANL-002 | Time-on-task from **visible-tab heartbeats** (`activity_heartbeats`, every 15 s while the tab is visible and there was input or playback in the last 60 s), sessionized into `engagement_intervals`. Method disclosed to students and colleges (RPA §4 [Rec]). | P0 | Planned |
| FR-ANL-003 | Daily aggregates (`daily_learning_aggregates`) per user × day × course/topic: active minutes, lessons completed, questions attempted/correct, tests taken. Dashboards read aggregates, not raw events. | P0 | Planned |
| FR-ANL-004 | Reports: student (self), batch/org (coordinator), course/test (trainer), platform (super admin), commerce (finance). Dashboard aggregates ≤ 15 min behind; daily exports at 02:00 IST. | P0 | Planned |
| FR-ANL-005 | Minors: analytics used only for learning delivery and college reporting; never for marketing segments. No third-party marketing pixels on authenticated pages or for minors anywhere. | P0 | Planned |

### 4.14 Notifications (`notifications`)

| ID | Requirement | Pri | Status |
|---|---|---|---|
| FR-NTF-001 | Channels: email (SES), SMS (MSG91 or similar; DLT-registered transactional templates only), in-app (bell + `/app/notifications`); push in P2 (mobile app). | P0 | Planned |
| FR-NTF-002 | Always-on transactional events: verification/OTP, new-device sign-in, password/MFA/contact changes, restriction applied/lifted, appeal decision, order paid/failed, invoice, refund decision, subscription pre-debit (≥ 24 h), renewal reminder (7 days), entitlement expiring (7 days and 1 day), invite, test assigned, test reminders (24 h and 1 h before close), results released, assignment graded, mentor booking/reschedule/no-show, ticket updates. | P0 | Planned |
| FR-NTF-003 | Preferences per category (learning reminders, product updates, marketing). Marketing opt-in defaults to **off** and is never sent to minors. | P0 | Planned |
| FR-NTF-004 | Batch announcements by trainers/coordinators (in-app + email), max 3 per batch per day. | P1 | Planned |
| FR-NTF-005 | Versioned templates; delivery status (sent, delivered, bounced) tracked in `notifications`. | P1 | Planned |

### 4.15 Support (`support`)

| ID | Requirement | Pri | Status |
|---|---|---|---|
| FR-SUP-001 | Tickets from the help centre, in-app, or the blocked-login interstitial. Categories: login/account, device limit, payment/refund, content error, test issue, certificate, college access, appeal (routes to security), privacy request, other. | P0 | Planned |
| FR-SUP-002 | Context auto-attached (disclosed to the user): user ID, browser/OS, current route, last error `request_id`. Never passwords or OTPs. | P0 | Planned |
| FR-SUP-003 | SLAs by priority: P1 (cannot access paid content, or test in progress) first response ≤ 4 business hours; P2 ≤ 1 business day; P3 ≤ 2 business days. Grievances: acknowledgement ≤ 48 h, resolution ≤ 1 month (RPA §8 Q6). | P0 | Planned |
| FR-SUP-004 | Agent workspace: queue filters, assignment, internal notes, macros, merge duplicates, escalation to finance/security/content. | P0 | Planned |
| FR-SUP-005 | User lookup (SUP-003): account and verification status, restriction level + student-facing reason, device list with masked IPs, active sessions, entitlements, recent orders (read-only). | P0 | Planned |
| FR-SUP-006 | Support actions: resend verification, revoke sessions (step-up), lift L1/L2, trigger password-reset email (never set a password, ASVS 6.4.6), annotate account. | P0 | Planned |
| FR-SUP-007 | Device reset by support: 1 extra replacement per rolling 30 days beyond the self-service quota, with reason. Further resets need a `security_reviewer`. | P0 | Planned |
| FR-SUP-008 | CSAT survey after ticket closure (1–5 + comment). | P1 | Planned |

### 4.16 Privacy, audit and admin (`identity`, `audit`, `admin`)

| ID | Requirement | Pri | Status |
|---|---|---|---|
| FR-PRV-001 | Itemised consent notice at signup (account & learning delivery; security monitoring for account protection; learning analytics; college data sharing when in an org; marketing), stored in `consents` with notice version. Withdrawal as easy as giving (DPDP Rule 3). Details: `docs/privacy-and-data-retention.md`. | P0 | Planned |
| FR-PRV-002 | Self-service data export (JSON + CSV zip, delivered ≤ 72 h) and account deletion request (14-day cooling-off). Legally retained records are kept: invoices 72 months, security logs ≥ 1 year. | P0 | Planned |
| FR-PRV-003 | Guardian consent flow: guardian email/mobile verification + declaration; a consent token is stored, not ID documents (RPA §8). | P0 | Planned |
| FR-ADM-001 | Append-only, hash-chained `audit_log` for all privileged actions: role grants, device resets, session kills, restrictions, grade overrides, refunds, coupons, exports, policy changes, entitlement changes. | P0 | Planned |
| FR-ADM-002 | Policy settings (`policy_settings`): device/session/stream caps, replacement quota, OTP limits, refund window/threshold, subscription grace days. Changes need second-person approval and apply to new events only. | P0 | Planned |
| FR-ADM-003 | Feature flags (`feature_flags`) per platform, org or percentage rollout. | P1 | Planned |
| FR-ADM-004 | Approvals queue (ADM-010): pending dual-control actions with requester, payload diff, 72 h expiry; approver ≠ requester. | P0 | Planned |
| FR-ADM-005 | Break-glass access: time-boxed (≤ 2 h) elevation with mandatory reason, passkey step-up, and an alert to all super admins and security reviewers. | P1 | Planned |

---

## 5. Non-functional requirements

All targets are **Planned** and measured in production from day one through the observability stack (NFR-OBS).

| ID | Category | Requirement (measurable) |
|---|---|---|
| NFR-PERF-01 | API latency | Read endpoints p95 ≤ 300 ms, p99 ≤ 800 ms; write endpoints p95 ≤ 500 ms (excluding payment-gateway and judge round-trips), measured at the load balancer. |
| NFR-PERF-02 | Test engine | Answer autosave p95 ≤ 250 ms; attempt start p95 ≤ 1.5 s; auto-submit fires ≤ 10 s after deadline + grace. |
| NFR-PERF-03 | Web vitals | Mid-range Android (4 GB RAM) on 4G (≈ 9 Mbps, 170 ms RTT): LCP ≤ 2.5 s, INP ≤ 200 ms, CLS ≤ 0.1 at p75 for public pages, dashboards and test runner. Test-runner route JS ≤ 200 KB gzipped. |
| NFR-PERF-04 | Video | Time to first frame ≤ 3 s p75 on 4G; rebuffer ratio ≤ 1%. |
| NFR-PERF-05 | Coding judge | Run p95 ≤ 6 s; Submit (≤ 20 hidden cases) p95 ≤ 15 s under normal load; a queued state is shown beyond 15 s. |
| NFR-PERF-06 | Entitlement check | p95 ≤ 20 ms (FR-ENT-003). |
| NFR-AVL-01 | Availability | Core platform (auth, learning, practice, commerce) 99.9% monthly (≤ 43.8 min downtime). Assessment service 99.95% during drive windows scheduled ≥ 72 h ahead. Planned maintenance only 01:00–05:00 IST with 48 h notice and never during scheduled drives. |
| NFR-AVL-02 | Recovery | RPO ≤ 5 min (RDS PITR). RTO ≤ 30 min for a single-AZ failure (Multi-AZ); ≤ 4 h for full restore from backups. |
| NFR-AVL-03 | Degradation | A judge, video or payment-provider outage must not affect login, MCQ tests or course reading; status banner within 5 min of detection. |
| NFR-SCL-01 | Users | Year-1 sizing: 100,000 registered users, 50 colleges, 10,000 daily active, 3,000 concurrent sessions at peak. Must scale horizontally to 10× without redesign. |
| NFR-SCL-02 | Drives | 2,000 concurrent test-takers in one drive starting within the same 5 min window; 20,000 autosave writes/min sustained. |
| NFR-SCL-03 | Judge | 10,000 submissions/day steady; burst 60,000/day in drive peaks (RPA §8: 2,000 students × 3 problems × ~10 submissions). |
| NFR-SCL-04 | Analytics data | ≤ 50 M raw event rows/month in year 1; raw retention per `docs/analytics-event-schema.md`, then aggregate-only. |
| NFR-ACC-01 | Accessibility | **WCAG 2.2 AA** in all portals: full keyboard operation including test runner and code editor; focus not obscured (2.4.11); target size ≥ 24×24 px (2.5.8); no drag-only interactions (2.5.7); consistent help (3.2.6); redundant entry avoided (3.3.7); accessible authentication with paste allowed and passkeys (3.3.8); contrast ≥ 4.5:1 text and 3:1 UI; captions on video lessons; accessible maths rendering; timer announced via ARIA live region only at 10/5/1 min. Verified by axe-core in CI (0 serious/critical) plus a manual NVDA + TalkBack audit per release. |
| NFR-ACC-02 | Devices | Latest 2 versions of Chrome, Edge, Firefox, Safari; Android 10+, iOS 16+; min viewport 360 px; coding workspace needs ≥ 768 px (notice shown on smaller screens). |
| NFR-SEC-01 | Standard | OWASP ASVS 5.0 Level 2 platform-wide; Level 3 controls on finance, security and super-admin consoles (RPA §8). |
| NFR-SEC-02 | Testing | Zero open critical/high findings at release; external penetration test before launch and annually; dependency scanning on every build. |
| NFR-SEC-03 | Tenant isolation | Zero cross-tenant exposure; an automated isolation suite (RLS + API) passes on every build (role-permission-matrix §4). |
| NFR-SEC-04 | Judge | Student code never runs on app servers; judge has no network and no route to DB/Redis (brief §1). |
| NFR-PRV-01 | Privacy | DPDP Act 2023 + Rules 2025 from launch: itemised consent; grievance response ≤ 90 days (target ≤ 30); breach report to the Board ≤ 72 h; CERT-In ≤ 6 h; logs ≥ 1 year in India. |
| NFR-PRV-02 | Residency | All personal data and logs in AWS ap-south-1; sub-processors listed publicly. |
| NFR-OBS-01 | Tracing/logging | Every request carries `request_id` (returned in problem+json); structured JSON logs; OpenTelemetry traces across BFF → API → workers → judge-gateway; RED metrics per endpoint. |
| NFR-OBS-02 | Alerting | Alerts on SLO burn (2% of monthly budget in 1 h), webhook processing lag > 5 min, judge queue wait > 60 s, autosave error rate > 0.5% over 5 min, login failures > 3× baseline. |
| NFR-OBS-03 | Business monitoring | Dashboards for orders/min, payment success rate, entitlement grant lag, active attempts, restriction actions/day. |
| NFR-I18N-01 | Locale | English UI in v1 with all strings externalised for Hindi (P2); dates in IST; INR with Indian digit grouping (₹1,23,456). |
| NFR-MNT-01 | Maintainability | Each module exposes a `privacy_provider` (export/delete) and owns its tables; no cross-module table writes (RPA §6). |

---

## 6. Screen inventory

**Standard states** (every authenticated screen implements all five unless stated): **L** loading (skeleton, no layout shift); **E** empty (explanation + primary next action); **X** error (problem+json `title` + `request_id` + retry; never a stack trace); **B** blocked (account under L3/L4 restriction → restriction banner and redirect of premium routes to STU-026; L4 → session ends, PUB-021); **R** restricted (no entitlement → paywall card with the access options from FR-ENT-001 `upsell hint`; no permission → 403 "You don't have access to this page" without revealing whether the object exists). **O** offline (connectivity lost) applies where noted. Additional key states are listed per screen. All screens: **Planned**.

Route prefixes: public `/`, student `/app`, trainer `/trainer`, college coordinator `/college`, placement mentor `/mentor`, content manager `/studio`, support `/desk`, finance `/finance`, security `/security`, super admin `/admin`. Roles column uses brief §3 keys (`coord` = `college_coordinator`, `mentor` = `placement_mentor`, `cm` = `content_manager`, `support` = `support_agent`, `sec` = `security_reviewer`, `finance` = `finance_admin`, `sa` = `super_admin`).

### 6.1 Public site

| ID | Route | Roles | Purpose | Key states |
|---|---|---|---|---|
| PUB-001 | `/` | anyone | Home: value proposition, published device/refund policy highlights, free diagnostic CTA, company hubs, college CTA | L, X |
| PUB-002 | `/courses` | anyone | Catalog with filters (category, level, price type) and search | L, E (no results → clear filters), X |
| PUB-003 | `/courses/[slug]` | anyone | Course detail: outcomes, syllabus, completeness indicator, free preview lessons, price/plan options, refund rule text | L, X, 404, "Already owned" (signed-in), "Included via college" |
| PUB-004 | `/placement` | anyone | Placement hub: subjects (Quant, Logical, Verbal, Programming, DSA, CS fundamentals, Interview) | L, X |
| PUB-005 | `/placement/[subject]/[topic]` | anyone | Indexable topic page with concept notes + 10 free sample questions with explanations | L, E, X, sign-in gate after free sample |
| PUB-006 | `/companies` | anyone | Company hub list | L, E, X |
| PUB-007 | `/companies/[slug]` | anyone | Company hub: exam pattern, syllabus, interview experiences, free sample mock CTA, path pricing | L, X, 404 |
| PUB-008 | `/pricing` | anyone | Plans, packages, subscription terms, GST-inclusive prices, refund rule, cancel-anytime statement | L, X |
| PUB-009 | `/free-resources` | anyone | Free PDFs, cheat sheets, free courses | L, E, X, sign-in gate for `signed_in` resources |
| PUB-010 | `/enquiries` | anyone | Corporate/bulk enquiry form: name, company, email, phone, message, consent (rate-limited; stored server-side, visible to Admin in the support queue) | X, form validation, submitted, rate-limited |
| PUB-011 | `/signup` | anyone | Self-signup with DOB, itemised consents | validation, OTP sent, OTP rate-limited, under-18 → guardian step, existing account |
| PUB-012 | `/login` | anyone | Password / passkey / Google login; MFA challenge | throttled (back-off timer), MFA required, new device OTP, device limit reached (→ device chooser), session limit prompt, blocked (→ PUB-021) |
| PUB-013 | `/forgot-password`, `/reset-password/[token]` | anyone | Recovery | generic "If an account exists…" message, token expired/used |
| PUB-014 | `/verify/email/[token]`, `/verify/mobile` | signed-in or token holder | Contact verification | expired, already verified, OTP rate-limited |
| PUB-015 | `/guardian-consent/[token]` | guardian | Guardian reviews notice, verifies own contact, consents or declines | expired, declined, already consented |
| PUB-016 | — | — | Removed (college invitations) | — |
| PUB-017 | `/verify/[certificate_id]` | anyone | Public certificate verification | valid, revoked (date only), not found |
| PUB-018 | `/legal/terms`, `/legal/privacy`, `/legal/refund-policy`, `/legal/device-policy` | anyone | Published policies with version and effective date | — |
| PUB-019 | `/help`, `/help/[article]` | anyone | FAQ, contact, grievance officer details | L, E (search), X |
| PUB-020 | `/status` | anyone | Service status (judge, video, payments) | operational, degraded, outage |
| PUB-021 | `/account/restricted` | user with L4 restriction signed in with a `status_only` session (no full session); hard-disabled accounts are sent to password reset first | Explains restriction, offers identity verification + appeal/unblock request form, shows case reference | request status per the 8 unblock states (brief v0.2 §1): draft, submitted, under review, additional information requested, with senior reviewer (`escalated`), approved, rejected, closed |

### 6.2 Student portal (`student`)

| ID | Route | Purpose | Key states (+ standard) |
|---|---|---|---|
| STU-001 | `/app` | Student dashboard (§8.1) | first-run (no diagnostic yet), college banner, expiring entitlement banner, restriction banner |
| STU-002 | `/app/onboarding` | Goal picker: target companies, role, drive date, year | skipped, saved |
| STU-003 | `/app/diagnostic` | Free diagnostic test launcher (runs in TST-002) | already taken (show result), in progress (resume) |
| STU-004 | `/app/learning` | My courses with progress and validity | E (no enrolments → catalog CTA), expired items (locked badge) |
| STU-005 | `/app/courses/[slug]` | Enrolled course overview: modules, progress, next lesson, certificate status | R (expired → renew), version-migration prompt |
| STU-006 | `/app/path` | Personalised learning path + recommendations with "why" | E (no diagnostic), minor mode (no commercial items) |
| STU-007 | `/app/assignments` | Assignments list (due, submitted, graded) | E, overdue, late-penalty notice |
| STU-008 | `/app/assignments/[id]` | Assignment detail + submission upload | upload progress, file too large/type rejected, submitted, returned for resubmission, graded |
| STU-009 | `/app/tests` | Available, scheduled, completed tests (batch-assigned + purchased) | E, upcoming (countdown), window closed, attempts exhausted |
| STU-010 | `/app/tests/[test_id]/results/[attempt_id]` | Results and review per review matrix | results pending release, provisional rank, regraded notice, invalidated (with appeal link) |
| STU-011 | `/app/analytics` | Skill analytics (FR-PLC-012) | insufficient data (< 20 questions), method disclosure panel |
| STU-012 | `/app/certificates` | Certificates list, download, share, LinkedIn | E, revoked |
| STU-013 | `/app/mentoring` | Book/reschedule mock interviews; feedback history | R (no package), no slots available, booking quota 0, mentor no-show credit |
| STU-014 | `/app/resume` | Resume builder, checklist score, request review | E, saving, export PDF, review pending/returned |
| STU-015 | `/app/interview-prep` | Technical and HR interview sets | R, E |
| STU-016 | `/app/checkout/[order_id]` | Order summary, GST breakup, coupon, Razorpay | coupon invalid/expired/cap reached, already owned (BR-ENT-05), included via college (BR-ENT-06), minor without guardian consent, payment cancelled |
| STU-017 | `/app/orders/[order_id]` | Payment status | pending/confirming, paid (access granted), failed (retry), expired |
| STU-018 | `/app/billing` | Subscriptions (cancel/resume/change), orders, invoices (PDF), refund requests | in grace (update payment), cancellation scheduled, refund eligible/ineligible with reason |
| STU-019 | `/app/access` | "What I have access to" (FR-ENT-002) | E, grace, suspended (payment dispute), expiring soon |
| STU-020 | `/app/settings/profile` | Profile, college details, legal name | name locked after certificate |
| STU-021 | `/app/settings/security` | Password, MFA, passkeys, recovery codes | re-auth required, MFA enrolment, recovery codes shown once |
| STU-022 | `/app/settings/devices` | Account-integrity centre: published limits, devices, sessions, replacement quota | quota exhausted (→ support), current device pending verification |
| STU-023 | `/app/settings/privacy` | Consents, college sharing opt-in, data export, deletion | export in progress/ready, deletion cooling-off (cancel) |
| STU-024 | `/app/notifications` | Notification centre + preferences | E |
| STU-025 | `/app/support`, `/app/support/new`, `/app/support/[ticket_id]` | Tickets | E, awaiting reply, resolved, reopened |
| STU-026 | `/app/account-status` | Restriction explanation, history, unblock request/appeal | none (all clear), L1–L3 active with end time, unblock request in one of the 8 states (draft, submitted, under review, additional information requested, with senior reviewer (`escalated`), approved, rejected, closed) |
| STU-027 | — | Removed (college students) | — |
| STU-028 | `/app/bookmarks` | Bookmarked lessons/questions and notes | E |

### 6.3 Course player (`student`; trainers/content managers in preview mode)

| ID | Route | Purpose | Key states (+ standard) |
|---|---|---|---|
| PLY-001 | `/app/learn/[course_slug]/[lesson_id]` (video) | DRM video with watermark, notes, transcript, resources, next/prev, progress | DRM unsupported browser (instructions), token denied (stream limit → PLY-005), media processing, O |
| PLY-002 | same (article/PDF) | Reading lesson | O (cached text readable), PDF download link expired |
| PLY-003 | same (in-lesson quiz/practice) | Embedded practice set | submitted, retry |
| PLY-004 | `/app/learn/[course_slug]/[lesson_id]?preview=1` | Author/trainer preview of draft | "Preview — not visible to students" banner |
| PLY-005 | (modal in player) | Stream limit interstitial: "Playing on <device> — stop it and play here?" | taken over, other device stopped |

### 6.4 Practice (`student`)

| ID | Route | Purpose | Key states (+ standard) |
|---|---|---|---|
| PRC-001 | `/app/practice` | Practice hub by subject with mastery badges | first-time (no mastery yet) |
| PRC-002 | `/app/practice/[subject]` | Topics/subtopics with mastery %, question counts, difficulty filter | R (premium topics), E |
| PRC-003 | `/app/practice/sessions/[session_id]` | Untimed question set with instant feedback + explanation, report error, bookmark | answered correct/incorrect, explanation, set complete summary, O (answers queued) |
| PRC-004 | `/app/practice/review` | Incorrect and bookmarked questions for re-practice | E |
| PRC-005 | `/app/companies/[slug]` | Enrolled company path: pattern, ordered sets, mocks, readiness score | R, readiness insufficient data |

### 6.5 Timed test (`student`)

| ID | Route | Purpose | Key states (+ standard) |
|---|---|---|---|
| TST-001 | `/app/tests/[test_id]` | Instructions, pattern, marking, integrity notice, system check (browser, connectivity, full-screen), consent for integrity events | not yet open (countdown), closed, attempts exhausted, not verified (verify first), R |
| TST-002 | `/app/attempts/[attempt_id]` | Attempt runner: section tabs, server-synced timer, question palette (5 states), autosave indicator, mark for review, calculator (where allowed) | saving, saved, offline (answers stored locally), reconnecting, time warning 10/5/1 min, section locked (sequential), open on another device (read-only, FR-SES-011), auto-submitted |
| TST-003 | (modal) | Section submit / final submit confirmation with unanswered count | — |
| TST-004 | `/app/attempts/[attempt_id]/resume` | Resume after crash/disconnect with remaining time | pending local answers flushed, conflict resolved (server wins for timing, latest-sequence wins for answers) |
| TST-005 | `/app/attempts/[attempt_id]/submitted` | Submission confirmation, result release info | results immediate / on date / after review |

### 6.6 Coding (`student`)

| ID | Route | Purpose | Key states (+ standard) |
|---|---|---|---|
| COD-001 | `/app/coding` | Problem list with filters (topic, difficulty, company, status) | E, R (premium) |
| COD-002 | `/app/coding/[slug]` | Workspace: statement, editor, custom input, Run, Submit, results panel | running, queued (judge busy/outage), CE with compiler output, per-case verdicts, rate-limited, small screen notice, autosaved |
| COD-003 | `/app/coding/[slug]/submissions` | Submission history, diff | E |
| COD-004 | (embedded in TST-002) | Coding question inside a timed test | same as COD-002 + test timer |

### 6.7 Trainer portal (`trainer`, scoped to batch/course)

| ID | Route | Purpose | Key states (+ standard) |
|---|---|---|---|
| TRN-001 | `/trainer` | Trainer dashboard (§8.2) | no batches assigned (E) |
| TRN-002 | `/trainer/batches/[batch_id]` | Batch roster, progress, upcoming tests, at-risk students | E |
| TRN-003 | `/trainer/courses` | Assigned/org-private courses | E |
| TRN-004 | `/trainer/courses/[course_id]/edit` | Course builder (modules, lessons, assets), versions, submit for review | draft saved, in review, published (read-only), media processing |
| TRN-005 | `/trainer/tests` | Tests owned/assigned | E |
| TRN-006 | `/trainer/tests/[test_id]/edit` | Test builder: sections, timing, draw rules, marking, review matrix, schedule, audience | validation (insufficient questions for draw rule), locked after first attempt (settings read-only) |
| TRN-007 | `/trainer/tests/[test_id]/overrides` | Per-student/batch extra time, extra attempt, extension | reason required, audited |
| TRN-008 | `/trainer/grading` | Grading queue (assignments, descriptive answers) | E, overdue grading |
| TRN-009 | `/trainer/grading/[submission_id]` | Rubric grading, comments, return/resubmit | released, grade change after release (reason) |
| TRN-010 | `/trainer/integrity` | Advisory integrity flags: events timeline, similarity pairs, "review recommended" | E, decided (no action / invalidate / refer to security) |
| TRN-011 | `/trainer/tests/[test_id]/report` | Test analytics: score distribution, item analysis (difficulty, discrimination), section times | results provisional |
| TRN-012 | `/trainer/assignments` | Create/manage assignments | E |

### 6.8 Evaluator portal (`evaluator`, scoped to batch or platform)

The college coordinator portal (COL-001…COL-012) is removed. Batches (formerly COL-004/005) move to the Admin console (ADM-013/014). The Evaluator portal reuses the trainer grading screens with authoring hidden:

| ID | Route | Purpose | Key states (+ standard) |
|---|---|---|---|
| EVL-001 | `/evaluator` | Grading queue across granted batches; assignment evaluation (TRN-008/009 screens), test evaluation, integrity review (TRN-010), publish results | E, own attempt/submission excluded (conflict of interest) |

### 6.9 Placement mentor section (Admin portal, `super_admin`)

| ID | Route | Purpose | Key states (+ standard) |
|---|---|---|---|
| MEN-001 | `/mentor` | Upcoming sessions, pending feedback, resume reviews | E |
| MEN-002 | `/mentor/slots` | Availability calendar, slot creation (30/45/60 min) | overlap conflict, booked slot (cannot delete; cancel → student credit) |
| MEN-003 | `/mentor/sessions/[session_id]` | Session detail, student readiness snapshot, rubric feedback form | feedback due (≤ 48 h), no-show marking |
| MEN-004 | `/mentor/students/[user_id]` | Readiness notes and feedback history (assigned students only) | E |
| MEN-005 | `/mentor/resume-reviews` | Resume review queue with inline comments | E |

### 6.10 Content manager studio (`content_manager`)

| ID | Route | Purpose | Key states (+ standard) |
|---|---|---|---|
| CMS-001 | `/studio` | Content dashboard: completeness per course/path, review backlog, reported errors | E |
| CMS-002 | `/studio/courses` | Platform courses list | E |
| CMS-003 | `/studio/courses/[course_id]` | Course builder + version history + publish | in review, published, archived |
| CMS-004 | `/studio/questions` | Question bank search (topic, difficulty, tag, company, status, author) | E |
| CMS-005 | `/studio/questions/[question_id]` | Question editor: stem, options, key, explanation (mandatory), tags, versions, usage stats | missing explanation (cannot submit), published (edit creates version) |
| CMS-006 | `/studio/questions/import` | Bulk import with validation preview | row errors, duplicates detected (similar stem) |
| CMS-007 | `/studio/review` | Review queue (questions, courses, coding problems); author ≠ reviewer | E, changes requested |
| CMS-008 | `/studio/taxonomy` | Subject → topic → subtopic tree | move with dependent-count warning |
| CMS-009 | `/studio/companies` | Companies and company paths (pattern, syllabus mapping, ordered content) | E |
| CMS-010 | `/studio/coding/[problem_id]` | Coding problem editor, test cases (hidden/visible), reference solution validation run | reference solution fails a case (cannot publish) |
| CMS-011 | `/studio/tests` | Template mocks for catalog products | E |
| CMS-012 | `/studio/media` | Uploads and processing status | failed upload |
| CMS-013 | `/studio/reports/errors` | Student-reported question errors | E |

### 6.11 Support desk (Admin portal, `super_admin`)

| ID | Route | Purpose | Key states (+ standard) |
|---|---|---|---|
| SUP-001 | `/desk` | Ticket queue (SLA timers, priority, category) | E, SLA breach highlighted |
| SUP-002 | `/desk/tickets/[ticket_id]` | Conversation, internal notes, macros, escalate | awaiting user, escalated |
| SUP-003 | `/desk/users/[user_id]` | User lookup (FR-SUP-005) | restricted L3/L4 (lift disabled with tooltip "Security reviewer only"), minor badge |
| SUP-004 | (drawer on SUP-003) | Device reset / session revoke with reason, step-up | support quota exhausted (→ escalate) |
| SUP-005 | `/desk/unblock-requests` | Triage L1/L2 unblock requests; forward L3/L4 to security | E |

### 6.12 Finance console (Admin portal, `super_admin`)

| ID | Route | Purpose | Key states (+ standard) |
|---|---|---|---|
| FIN-001 | `/finance` | Revenue dashboard: GMV, net revenue, refunds, MRR, failed payments, AR from contracts | — |
| FIN-002 | `/finance/products` | Products, plans, prices (≤ ₹15,000 recurring check) | price change scheduled, validation error |
| FIN-003 | `/finance/coupons` | Coupons create/edit/disable, redemption stats | pending second approval |
| FIN-004 | `/finance/orders` | Orders and payments search | E |
| FIN-005 | `/finance/refunds` | Refund queue with eligibility evaluation (consumption %, certificate, days) | eligible, ineligible (override → second approver), processing, failed at gateway |
| FIN-006 | `/finance/subscriptions` | Subscriptions, grace, cancellations | E |
| FIN-007 | `/finance/invoices` | Invoices, credit notes, GST exports | E |
| FIN-008 | — | Removed (institution contracts) | — |
| FIN-009 | `/finance/reconciliation` | Payments vs settlements mismatches | E (all matched) |

### 6.13 Security console (Admin portal, `super_admin`)

| ID | Route | Purpose | Key states (+ standard) |
|---|---|---|---|
| SEC-001 | `/security` | Account-security dashboard (§8.5) | — |
| SEC-002 | `/security/cases` | Case queue (priority, age, level, SLA) | E |
| SEC-003 | `/security/cases/[case_id]` | Evidence (signals, overlaps timeline, rule version, explanation), notes, decision | minor (behavioural evidence absent by design), second approval required, decided |
| SEC-004 | `/security/unblock-requests` | Appeals/unblock requests (L3/L4 and escalations) | E |
| SEC-005 | `/security/restrictions` | Active restrictions list, expiry, manual apply/lift | lift pending second approval |
| SEC-006 | `/security/rules` | Risk rules & versions; propose, simulate on last 30 days, submit for approval | simulation running, pending approval, published |
| SEC-007 | `/security/users/[user_id]/timeline` | IP/device/session history (access logged with reason code) | reason prompt before view, minor (limited data) |

### 6.14 Admin console (`super_admin`, shown as "Admin")

| ID | Route | Purpose | Key states (+ standard) |
|---|---|---|---|
| ADM-001 | `/admin` | Platform admin dashboard (§8.4) | — |
| ADM-002 | — | Removed (organizations) | — |
| ADM-003 | `/admin/ai` | AI and app settings (platform-wide; replaces per-org AI settings) | AI off, cap reached |
| ADM-013 | `/admin/batches` | Batch list, create batch | E, duplicate code |
| ADM-014 | `/admin/batches/[batch_id]` | Batch detail: members add/remove (existing accounts), assign trainer/evaluator | E, archived (read-only) |
| ADM-015 | `/admin/college-data` | College Data Portal (college outreach: colleges, contacts, calls, targets, enrollments), embedded from `/college-portal/` (docs/college-data-portal.md) | portal unavailable (502), access unverifiable (503) |
| ADM-004 | `/admin/users` | User search (no evidence data; links to security for that) | E |
| ADM-005 | `/admin/roles` | Role grants (create/expire), grant history | pending second approval (super_admin grants) |
| ADM-006 | `/admin/policies` | Policy settings (device/session/refund/grace) | pending approval, scheduled effective date |
| ADM-007 | `/admin/feature-flags` | Feature flags | — |
| ADM-008 | `/admin/audit` | Audit log viewer with hash-chain verification status | chain verified / break detected (alert) |
| ADM-009 | `/admin/privacy-requests` | Export/deletion/grievance queue with DPDP timers | overdue |
| ADM-010 | `/admin/approvals` | Dual-control approvals queue | E, expired |
| ADM-011 | `/admin/notifications` | Notification templates | draft, active |
| ADM-012 | `/admin/break-glass` | Request/activate break-glass session | active (countdown), expired |

---

## 7. User journeys

Each step references screens (§6) and requirements (§4). All **Planned**.

### J1. Individual student: self-signup → purchase → learn → mock test

1. Ananya finds `/companies/tcs-nqt` (PUB-007) from search, reads the pattern and solves 10 free questions on PUB-005.
2. She clicks "Take free diagnostic", lands on PUB-011, enters name, email, mobile, DOB (age 21 → adult path), password (15+ chars), and ticks the itemised consents (FR-IDN-001, FR-PRV-001). Mobile OTP verifies her (FR-IDN-003). Her laptop becomes trusted device 1 (FR-SES-002).
3. Onboarding goal picker (STU-002): TCS, Infosys, Accenture; drive date in 90 days.
4. Diagnostic (STU-003 → TST-001 → TST-002, 30 min). Result shows Quant 7/10, Logical 4/10, Verbal 8/10; path (STU-006) recommends Logical: seating arrangement, blood relations.
5. On `/pricing` (PUB-008) she compares the annual all-access subscription and the TCS company path. Prices are GST-inclusive with no anchor; the refund rule is printed under the button.
6. Checkout (STU-016): applies a 20% coupon (FR-COM-007), pays via UPI. Order page (STU-017) shows "confirming" for 8 s, then "Access granted" when the verified webhook creates a `purchase` entitlement (FR-COM-003/004, FR-ENT-001). Invoice emailed (FR-COM-009).
7. Learns in the course player (PLY-001). Video carries her watermark. When her brother starts a video on the family laptop under her login while she watches on her phone, PLY-005 appears on his screen (FR-SES-007).
8. Practises (PRC-003) seating arrangement with explanations; mastery rises from 35 to 62 (FR-PLC-006).
9. Takes a TCS full mock (TST-002). Hostel power fails at minute 41; she reopens on her phone (trusted device 2) — TST-004 resumes with 49 min left and all answers (FR-ASM-005/006). Rebind logged (`attempt_events.rebind`), not penalised.
10. Results (STU-010): section scores, provisional percentile, explanations per review matrix. Analytics (STU-011) updates company readiness to 58%.

### J2. College onboarding → batch → bulk invite → reporting

> **Removed (single-company, ADR-0015).** This journey no longer applies. Replacement: Admin creates a batch (ADM-013), adds existing accounts one by one (ADM-014), assigns a trainer and an evaluator; the trainer assigns a test; the evaluator grades and publishes results.

1. Sales closes a contract. Finance creates the institution contract (FIN-008): 1,200 seats, 12 months, grace 7 days, reassignment allowance 10% (FR-COM-010).
2. Super admin creates the org (ADM-002), links the contract, and grants Dr. Suresh `college_coordinator` at `organization:{id}` (ADM-005). He receives an invite, sets a password and enrols TOTP (mandatory).
3. Coordinator creates 6 batches (COL-004) for 2027 graduates by department (FR-ORG-003).
4. Bulk import (COL-003): uploads a 1,180-row XLSX. Preview shows 14 errors (9 invalid mobiles, 5 duplicates). He fixes 9, drops 5, commits 1,175 rows; invites go out (FR-ORG-010/011). Seats: 1,175/1,200 reserved on acceptance.
5. 37 students already had individual accounts; their invites link the existing accounts after a college data-sharing notice (FR-IDN-012). Three under-18 students join under the college-as-fiduciary configuration (FR-ORG-012).
6. Coordinator grants Kavya `trainer` at `batch:{CSE-A}` (COL-012, FR-ORG-017) and assigns the "Accenture pattern mock" to all batches with a 3-day window (COL-007).
7. After the window, COL-001 shows the readiness distribution and completion (78%); COL-008 exports a results file (step-up MFA, audited). COL-010 shortlists students with percentile ≥ 70 for the Accenture drive.
8. Mid-year, 22 students leave. Coordinator revokes their seats (COL-006); 15 return to the pool freely, 7 count against the reassignment allowance (BR-ENT-16).
9. At contract end, entitlements move to grace for 7 days, then expire; students receive conversion offers (BR-ENT-17).

### J3. Trainer authoring and grading

1. Kavya opens TRN-006 and builds "DSA Weekly Test 3": Section A MCQ (15 questions drawn from arrays/strings, difficulty 2–4, 20 min), Section B coding (2 problems, 40 min). Review matrix: scores immediately, answers + explanations after close.
2. Validation warns that the draw rule needs ≥ 45 eligible questions to vary between students (only 38 available); she widens to difficulty 2–5.
3. She schedules it for batch CSE-A (Sat 10:00–Mon 22:00, 1 attempt). Once the first attempt starts, settings lock (FR-ASM-010).
4. A student reports a power cut; Kavya grants +15 min via TRN-007 with a reason (FR-ASM-007).
5. After close, the similarity pass flags 2 coding pairs (FR-COD-008). In TRN-010 she compares diffs and the events timeline, marks one pair "no action" (common template code) and refers the other to review; leaderboard stays provisional until decided (FR-ASM-015).
6. She grades the weekly assignment in TRN-009 with the rubric and releases grades; one later change requires a reason and is audited (FR-LRN-005).
7. A content error is reported on question Q-4471 (wrong key). The content manager fixes it, creating version 3; regrade runs automatically and 31 students get updated scores (FR-ASM-011).

### J4. Blocked student → unblock

1. Rahul's account shows overlapping video playback from 3 device tokens on 2 distinct networks on 4 separate days (FR-SEC-001). The rule engine raises L2: other sessions above the cap revoked and the devices involved must re-verify (SMS OTP/passkey/TOTP) (FR-SEC-002a). He sees the reason on next login (FR-SEC-003).
2. Overlap continues; a security reviewer reviews case evidence (SEC-003) and applies L3 for 7 days: premium playback and new test starts restricted. Rahul sees STU-026 with the reason category, end date and "Request review".
3. Rahul explains that his roommate used his laptop; he removes the device (STU-022) and submits an unblock request with a declaration (FR-SEC-004).
4. Support triage (SUP-005) sees L3 and forwards to security; support cannot lift it (FR-SEC-006).
5. Security reviewer decides within 2 business days: lift with a warning; case decision recorded in `case_decisions`. Because the evidence was valid, no compensation applies (BR-ENT-12 applies only to overturned restrictions).
6. Alternative branch: the evidence proves to be the hostel NAT (a false positive). The restriction is overturned; entitlements are extended by 3 days automatically, and the rule version is flagged for tuning (SEC-006).
7. Alternative branch, L4 on a high-risk case (credential resale): a lift requires a second reviewer's approval (FR-SEC-005, ADM-010).
8. His college coordinator sees only "Account restricted — contact support" on COL-009, never the evidence (role-permission-matrix §8).

### J5. Admin review (platform governance)

1. Monday review on ADM-001: payment success 96.4%, webhook lag p95 40 s, 3 orgs with contracts ending in 30 days, audit chain verified.
2. Security reviewer proposes rule v7 (lower weight for shared-ASN overlap). A 30-day simulation (SEC-006) shows L3 actions dropping from 41 to 29 with no missed confirmed cases. Super admin approves in ADM-010 (requester ≠ approver).
3. Finance requests a goodwill refund beyond the rule (certificate issued). A second finance approver approves in FIN-005; the certificate is revoked (BR-ENT-10).
4. Super admin raises the replacement quota from 2 to 3 per 30 days for the exam season; the change waits for a second super admin approval and takes effect at 00:00 IST the next day (FR-ADM-002).
5. ADM-009 shows a deletion request on day 20 of the 30-day target; it is processed, retaining invoices and security logs as stated in the notice.

### J6. College-enrolled student → graduation → conversion

> **Removed (single-company, ADR-0015).** This journey no longer applies (no college-funded access).

1. Rahul's batch ends; the coordinator removes the batch from the org (FR-ORG-018).
2. Rahul keeps his account, attempts, analytics and certificates; contract entitlements end and seats are released per BR-ENT-16.
3. STU-027 shows "Your college access ended on 31 May. Continue with your progress" with individual plans; buying one restores access with history intact. The college no longer sees new activity.

---

## 8. Dashboard designs

Data sources use brief §4 entities. "Agg" = `daily_learning_aggregates`. Freshness: ≤ 15 min unless stated. All **Planned**.

### 8.1 Student dashboard (STU-001)

| Widget | Content / metric | Data source | Notes |
|---|---|---|---|
| Continue learning | Last lesson per course, progress %, resume button | `lesson_progress`, `enrolments` | Max 3 cards |
| Today's plan | 3–5 recommended items with "why" | recommendations (FR-PLC-011) from mastery + goals | Minors: assessment-based only |
| Upcoming | Assigned tests/assignments with due dates, mentor sessions | `tests` (batch assignment), `assignments`, mentor bookings (CCP-02) | Sorted by due date |
| Readiness ring | Company readiness % for each target company (max 3) | mastery per subtopic × `company_paths` syllabus | Method link |
| Skill snapshot | Accuracy by subject (Quant/Logical/Verbal/Programming/DSA/CS) last 30 days | Agg (questions attempted/correct) | Bar per subject |
| Weekly activity | Active minutes per day (7 days), streak | Agg (active minutes from `engagement_intervals`) | Visible-tab measurement disclosed |
| Recent results | Last 3 test attempts with score, percentile (provisional flag) | `attempt_results` | — |
| Access & billing | Active entitlements expiring ≤ 14 days, subscription status | `entitlements`, `subscriptions` | Grace banner |
| Account status | "All clear" or active restriction with action | `account_restrictions` | Links to STU-026 |
| College card | College name, batch, coordinator contact | `org_memberships`, `batch_members` | College students only |

### 8.2 Trainer dashboard (TRN-001)

| Widget | Content / metric | Data source |
|---|---|---|
| My batches | Per batch: students, avg course progress, active last 7 days % | `batch_members`, Agg |
| Grading queue | Pending submissions count, oldest age, overdue count | `assignment_submissions` |
| Upcoming / live tests | Tests in window: started/submitted/not started counts | `tests`, `test_attempts` |
| At-risk students | Students with < 20% progress and no activity in 7 days, or ≥ 2 tests below 40% | Agg, `attempt_results` |
| Integrity review | Open advisory flags by test | `attempt_events`, similarity results |
| Topic weakness | Batch lowest-accuracy 5 subtopics | Agg by topic |
| Content reports | Error reports on own content | support/content tickets |

### 8.3 College coordinator dashboard (COL-001)

> **Removed (single-company, ADR-0015).** The coordinator dashboard is removed; batch-level views live in the trainer dashboard and the Admin batches pages.

| Widget | Content / metric | Data source |
|---|---|---|
| Seat pool | Seats total / assigned / free / waitlisted; reassignment allowance used | `institution_contracts`, `entitlements` (source = contract) |
| Onboarding funnel | Invited → opened → accepted → first activity, per batch | invitations (CCP-04), `org_memberships`, Agg |
| Engagement | Weekly active % per batch; median active minutes/student/week | Agg |
| Readiness distribution | Histogram of company readiness % per target company; counts in bands 0–40/40–60/60–80/80–100 | mastery aggregates |
| Assessment results | Last 5 assigned tests: participation %, mean, median, top 10% cutoff | `attempt_results` |
| Topic gaps | Org-wide lowest-accuracy subtopics | Agg by topic |
| Upcoming | Scheduled tests/drives, contract end date | `tests`, `institution_contracts` |
| Restricted accounts | Count of own students with an active restriction (status only) | `account_restrictions` (count, no evidence) |
| Export shortcuts | Last exports and their expiry | export jobs |

Freshness: daily snapshot at 02:00 IST plus live counts for seats and test participation (consistent with B2B portal practice of daily metrics, RPA §1 [Verified] Coursera admin guide).

### 8.4 Platform admin dashboard (ADM-001)

| Widget | Content / metric | Data source |
|---|---|---|
| Users | Registered, verified, DAU/WAU/MAU, minors share | `users`, Agg |
| Revenue snapshot | Today/MTD GMV, net of refunds, MRR, payment success rate | `orders`, `payments`, `refunds`, `subscriptions` |
| Orgs | Active orgs, seats sold vs used, contracts ending ≤ 30 days | `organizations`, `institution_contracts` |
| Platform health | API p95, error rate, autosave error rate, judge queue wait, webhook lag | observability metrics (NFR-OBS) |
| Content | Published courses/questions, completeness %, open error reports | `courses`, `questions` |
| Security summary | Restrictions by level (7 days), open cases, appeals overdue | `account_restrictions`, `security_cases` (counts only) |
| Governance | Pending approvals, privacy requests by due date, audit chain status | approvals, privacy requests, `audit_log` |

### 8.5 Account-security dashboard (SEC-001, `security_reviewer`)

Widgets are numbered by the Section H report they summarise (RE §10; v0.3, CPR-PRD-08).

| Id | Widget | Content / metric | Data source |
|---|---|---|---|
| H1 | Suspicious-activity queue | Open cases by level, median age, SLA breaches, top suspicious accounts | `security_cases`, `risk_evaluations` |
| H2 | Device–account graph | Devices shared across accounts, accounts per device | `user_devices`, `devices` |
| H3 | Concurrent-use events | Overlapping sessions/streams (incl. stream-limit takeovers, device-limit hits, replacements per day) | `security_signals`, `playback_sessions`, `session_network_observations` |
| H4 | Network-cluster associations (incl. CGNAT/shared-network watch) | Top shared ASNs/IP prefixes behind overlaps (to prevent false positives) | `security_signals` (adults only), `session_network_observations` |
| H5 | Blocked/restricted | Active L1–L4 counts, new in 24 h/7 days, auto vs manual vs HC | `account_restrictions` |
| H6 | Pending unblock requests | Submitted, awaiting info, escalated | `unblock_requests` |
| H7 | Review time | Median/p90 time to first response and decision | `unblock_requests`, `case_decisions` |
| H8 | False-positive rate | Overturn rate (30 days), per rule version and per HC rule | `case_decisions`, `risk_rule_versions` |
| H9 | Repeat incidents | Users with repeat cases | `security_cases` |
| H10 | Active sessions | Active-session counts | `auth_sessions` |
| H11 | Activity context | Daily/weekly/monthly learning activity | analytics aggregates (adults with consent) |
| H12 | User security timeline | Device and login history (failed logins, throttled, hard-disabled accounts, OTP sends vs cap) | `login_attempts`, `auth_sessions`, notifications |
| ENG | Engine health | `risk.mode`, HC switch, per-rule status, circuit-breaker state, pending kill-switch ratifications | `risk_rule_versions`, `policy_settings`, `approval_requests` |

**Section H reports (H1–H12).** Report ids follow the verbatim order of `docs/source-requirements-excerpt.md` Section H (brief v0.3); report keys are those of `api-specification.md` SEC-30. Every report is permission-controlled, every view is audited, and exports go through `report.export.request` + `report.export.approve` (approver ≠ requester).

| Id | Report (verbatim) | Report key |
|---|---|---|
| H1 | Top suspicious accounts | `top-suspicious-accounts` |
| H2 | Multiple-account/device associations | `account-device-associations` |
| H3 | Concurrent login events | `concurrent-login-events` |
| H4 | Repeated IP/device associations | `repeated-network-device-associations` |
| H5 | Blocked accounts | `blocked-accounts` |
| H6 | Pending unblock requests | `pending-unblock-requests` |
| H7 | Average review time | `average-review-time` |
| H8 | False-positive rate | `false-positive-rate` |
| H9 | Repeat incidents | `repeat-incidents` |
| H10 | Active-session counts | `active-session-counts` |
| H11 | Daily/weekly/monthly learning activity | `learning-activity` |
| H12 | Device and login history | `device-login-history` |

---

## 9. Acceptance criteria (major features)

Format Given/When/Then. Full test design is owned by the QA Lead (`docs/testing-and-acceptance-criteria.md`). All **Planned**.

| ID | Feature | Criteria |
|---|---|---|
| AC-IDN-01 | Age gate | **Given** a visitor enters a DOB making them 17 **When** they submit signup **Then** the account is created as `pending_guardian_consent`, a guardian-consent request is sent, and paid checkout and timed tests return `MINOR_CONSENT_PENDING` until consent is verified. |
| AC-IDN-02 | Uniform login errors | **Given** an unknown email and a known email with a wrong password **When** each logs in **Then** both get the same message, status code, and response time within ±50 ms (p95 over 100 tries). |
| AC-SES-01 | Device limit | **Given** a student with 3 trusted devices **When** they sign in on a 4th **Then** they see the device chooser; removing one counts 1 replacement; with 2 replacements already used in 30 days the removal is refused with a support link. |
| AC-SES-02 | Session limit | **Given** 2 active sessions **When** a 3rd sign-in completes **Then** the prompt names the oldest session; on confirm it is revoked within 5 s; if the oldest session has an active test attempt, it is not auto-selected. A session on the same browser profile is replaced, not counted. If every other session holds an active test attempt, the sign-in is refused (`session_cap_reached`) instead of evicting. |
| AC-SES-04 | Attempt idle hold | **Given** a timed test in progress **When** the student does not interact for longer than the idle timeout **Then** the session stays valid until the attempt deadline + grace + 5 min. |
| AC-SES-05 | Same-device re-attach | **Given** the browser crashes and the student signs in again on the same browser profile **Then** the attempt resumes without using a rebind. |
| AC-SES-03 | Stream limit | **Given** a video playing on device A **When** device B requests playback **Then** B receives `409 playback_conflict` and no playback token is issued to B until the user confirms takeover, after which A's stream stops within 30 s. |
| AC-ASM-01 | Autosave & resume | **Given** a student answered 25 questions **When** the browser crashes and they reopen within the window **Then** all 25 answers are restored and remaining time equals server `deadline_at − now` (±2 s). |
| AC-ASM-02 | Offline answers | **Given** connectivity drops for 3 min **When** the student answers 4 questions **Then** the UI shows "Offline — stored on this device" and all 4 sync in order within 10 s of reconnection. |
| AC-ASM-03 | Server deadline | **Given** an attempt whose deadline passed while the student is offline **When** the deadline + grace elapses **Then** the server auto-submits with the last synced answers within 10 s, and later-arriving answers timestamped after the deadline are rejected and logged. |
| AC-ASM-04 | Overrides | **Given** a trainer grants +15 min to one student **Then** only that attempt's `deadline_at` changes, the action is in `audit_log` with the reason, and other students are unaffected. |
| AC-ASM-05 | Settings lock | **Given** one attempt has started **When** a trainer edits timing or draw rules **Then** the save is rejected with code `TEST_LOCKED`. |
| AC-ASM-06 | Regrade | **Given** a question key is corrected **When** the new version is published **Then** affected attempts are regraded within 15 min and each affected student is notified. |
| AC-COD-01 | Hidden tests | **Given** a problem with 12 hidden cases **When** the student submits **Then** no hidden input/expected output is present in any API response or browser bundle; per-case verdicts and the weighted score are shown. |
| AC-COD-02 | Judge outage | **Given** the judge provider is down **When** a test-taker submits **Then** the submission shows "Queued", and the attempt deadline is extended by the outage duration with an audited override. |
| AC-COM-01 | Webhook idempotency | **Given** Razorpay delivers the same `payment.captured` event 3 times **Then** exactly one payment, one entitlement and one invoice exist. |
| AC-COM-02 | Unverified webhook | **Given** a webhook with an invalid HMAC **Then** it is rejected (`400`, no state change) and logged (AB-12). **Given** a valid webhook that is a duplicate or arrives late (any age) **Then** it is acknowledged `2xx` and any state change is applied only from a server-side re-fetch of the entity, never twice. |
| AC-COM-03 | Recurring cap | **Given** finance configures a plan with a ₹15,001 recurring price **Then** saving fails with a validation error. |
| AC-COM-04 | Refund rule | **Given** a discounted purchase 5 days old with 12% consumption and no certificate **When** the student requests a refund **Then** it is shown as eligible; the same request at 25% consumption is ineligible with the reason shown. |
| AC-COM-05 | One-click cancel | **Given** an active subscription **When** the student clicks Cancel and confirms once **Then** auto-renew stops, access continues to period end, and a confirmation email is sent within 5 min. |
| AC-ENT-01 | Union/precedence | **Given** a college seat and a personal purchase covering course C **When** the student opens C **Then** access is allowed with the contract entitlement as winner; after the contract expires, access continues through the purchase. |
| AC-ENT-02 | Grace | **Given** a failed renewal **Then** the entitlement is `grace` for 5 days with access; a success on day 3 returns it to `active`; no success by day 5 → `expired`. |
| AC-ENT-03 | Seat reassignment | **Given** a student assigned 20 days ago with 12% consumption **When** the seat is revoked **Then** reassignments used increases by 1; for a student assigned 3 days ago with 1% consumption it does not. |
| AC-ENT-04 | Restriction compensation | **Given** an L3 restriction of 4 days (or 3.2 days, rounded up to 4; an L4 period of the same case counts too) is overturned **Then** each active time-bound entitlement's `ends_at` moves 4 days later (contract seats only up to the contract end) and an audit entry exists. |
| AC-ORG-01 | Bulk import | **Given** a 1,000-row file with 10 invalid rows **When** validated **Then** the preview lists the 10 rows with reasons and commit creates exactly 990 invites; uploading the same file again creates 0 new invites. |
| AC-ORG-02 | Tenant isolation | **Given** coordinator X of org A **When** they request any student, batch, report or export ID belonging to org B **Then** the API returns 404 and the attempt is logged; RLS returns 0 rows for org B even with a forged query. |
| AC-SEC-01 | Explanation | **Given** any restriction is applied **Then** the student sees the level, plain-language reason category, end time and available actions on STU-026 within 1 min. |
| AC-SEC-02 | Support limits | **Given** a support agent views an L3/L4 restriction **Then** the lift control is disabled and the API rejects a lift with 403. |
| AC-SEC-03 | Dual approval | **Given** an L4 high-risk case **When** reviewer A records a lift **Then** the restriction stays until a different reviewer or super admin approves. |
| AC-SEC-04 | Minor safeguard | **Given** a minor account **Then** no `risk_evaluations` rows of any family are ever created for it, and only deterministic-cap signals and deterministic takeover signals (`family = takeover`, 0 points) are stored. |
| AC-LRN-01 | Certificate verify | **Given** a certificate is issued **Then** `/verify/{id}` returns it as valid within 60 s; after revocation it shows "revoked on <date>" with no reason. |
| AC-ACC-01 | Accessible test runner | **Given** a keyboard-only screen-reader user **When** they complete a 20-question test **Then** every control is reachable, question state is announced, and the timer announces only at 10/5/1 min. |

---

## 10. Out of scope for v1

| Item | Reason / when |
|---|---|
| Native Android/iOS apps (FLAG_SECURE, offline downloads) | P2; v1 is a responsive web app/PWA |
| Webcam, screenshot or AI proctoring; Safe Exam Browser | Cost, bias and DPDP risk (RPA §5, §7.5); Phase 3 only with consent and stated retention |
| Browser fingerprinting / paid device intelligence | Phase 2+ adults only, if data shows cookie-clearing evasion (RPA §3) |
| ML-based risk scoring | Brief §1: rule-based v1 |
| Behavioural risk scoring or profiling of minors | Brief §1 / DPDP s.9(3) |
| Live classes hosted on-platform (WebRTC) | v1 links to external meeting tools |
| Discussion forums / peer Q&A | Intermediary Rules exposure (RPA §8 Q7); P2 after legal review |
| LTI 1.3, xAPI LRS export, SCORM import | Phase 2–3 (RPA §8) |
| Hindi and regional UI | P2 (strings externalised in v1) |
| Paid "buddy / extra learner" seat | Phase 3 (RPA §3) |
| Self-hosted judge | Phase 2 (brief §1) |
| Job board / recruiter marketplace, placement outcome verification service | P2; outcome claims in v1 limited to cohort data with sample size |
| Multi-currency, international payments | INR only |
| Gamification beyond streaks (badges, coins) | P2 |
| Keystroke code replay | P2 (FR-COD-009), adults only |
| College-branded white-label domains | P2 |

---

## 11. Open product decisions

| ID | Decision needed | Options | Recommended default | Owner / by |
|---|---|---|---|---|
| OPD-01 | Refund consumption threshold and window | 7 days/20%; 14 days/10%; 7 days/no consumption check | 7 days, < 20% consumed, no certificate, includes discounted purchases | Product owner + counsel (RPA §8 Q10), before pricing page |
| OPD-02 | Subscription plan lineup and prices | Monthly + annual; quarterly; multi-year one-time | Monthly + annual subscription + 12-month placement package; no multi-year anchors | Product owner + finance |
| OPD-03 | Whether a free diagnostic needs signup | Guest diagnostic; signup-gated | Signup-gated (needed for results and consent) | Product owner |
| OPD-04 | Minors via D2C at launch | Allow with guardian consent; college-only for minors | College-only at launch, D2C minors from P1 after counsel sign-off (RPA §8 Q1–2) | Counsel |
| OPD-05 | Seat reassignment thresholds | 5%/14 days and 10% allowance (BR-ENT-16) vs contract-negotiated | Defaults as BR-ENT-16, overridable per contract | Sales + finance |
| OPD-06 | Default data-sharing scope with colleges | Contract-scope only (BR-ENT-14); all prep activity | Contract scope only + student opt-in | Product owner + counsel |
| OPD-07 | Coding languages at launch | 4 (C, C++, Java, Python) vs 6 | 4 at P0; JS + Go in P1 | Product owner |
| OPD-08 | Mentor sessions: external meeting links vs integrated video | Google Meet/Zoom links; integrated | External links in v1 | Product owner |
| OPD-09 | Leaderboards: display names default | Opt-in display name; anonymised by default | Anonymised by default | Product owner |
| OPD-10 | Certificates for free courses | Yes (lead magnet); no | Yes, with "free course" label; identity check only for paid certification tests | Product owner |
| OPD-11 | Student-initiated device replacement quota at peak season | Static 2/30 days; seasonal 3/30 days | Static 2 with support +1 (FR-SUP-007) | Product owner + security |
| OPD-12 | Placement drives (FR-ORG-019) in v1 or P2 | P1 vs P2 | P2; shortlists (FR-ORG-016) in P1 cover the need | Product owner |
| OPD-13 | Public outcome claims format | Cohort stats with sample size; none at launch | None at launch; publish after first full placement season | Marketing + product |

---

## 12. Contract change proposals

Reconciled by the Integration Lead in `contract-reconciliation.md` §2.1; outcomes are in the last column and are reflected in brief v0.2 and `database-schema.md`.

| ID | Proposal | Rationale | Affects | Reconciliation outcome |
|---|---|---|---|---|
| CCP-01 | Add to brief §1 device policy: **max 1 active session per timed-test attempt** (other sessions read-only, "Move test here" with OTP). | Research recommends "1 session during any assessment" (RPA §3 [Rec]); brief lists 2 concurrent sessions without an assessment rule. | `sessions`, `assessments`, `policy_settings` | → Accepted-modified in brief v0.2 (merged with SEC CCP-S3: bound session, confirm to rebind, OTP only at ≥ L2, max 2 rebinds, proctored = trainer override; PO-08). OTP on every move rejected |
| CCP-02 | Add entities for mentoring: `mentor_slots`, `mentor_bookings`, `interview_feedback` (rubric scores, comments). | FR-PLC-010 mock interviews with SLA/no-show handling (RPA §4 "Mentoring") have no canonical tables. Owning module: `placement`. | `placement`, entitlements quota | → Accepted in brief v0.2 (owner `placement`; PO-12) |
| CCP-03 | Add placement-drive entities: `placement_drives`, `drive_eligibility_rules`, `drive_shortlists`. | RPA §2/§7.1 identify companies, drives, eligibility and shortlists as placement-specific entities; brief has `companies`/`company_paths` only. P1–P2. | `placement`, `orgs` | → Deferred-to-owner (OPD-12 / PO-11); default P2, table names reserved, no DDL |
| CCP-04 | Add `org_invitations` (token hash, email, mobile, batch, status, expires_at, resend_count) and `bulk_import_jobs` (file, row results, idempotency hash). | FR-ORG-010/011 bulk invite with status tracking and idempotent re-upload. | `orgs` | → Accepted in brief v0.2 (invite token stored as SHA-256) |
| CCP-05 | Specify `entitlements` columns: `source_type`, `source_id`, `organization_id`, `starts_at`, `ends_at`, `grace_ends_at`, `status`, quota columns, `revocation_reason`; and an `entitlement_events` history table. | BR-ENT-01..21 need explicit source, status and grace semantics and an auditable history beyond `audit_log`. | `entitlements` | → Accepted-modified (typed source FK columns, PRD `source_type` vocabulary, `grace` status, column `revoke_reason`, `entitlement_events` added) |
| CCP-06 | Add `resumes` (structured JSON, template, version) and `resume_reviews`. | FR-PLC-015. | `placement` | → Accepted in brief v0.2 (owner `placement`) |
| CCP-07 | Add `support_ticket_messages` and `privacy_requests` (export/deletion/grievance with DPDP due dates). | FR-SUP-004, FR-PRV-002, ADM-009; brief has only `support_tickets`. | `support`, `identity`/`admin` | → Accepted in brief v0.2 (`privacy_requests` owned by `admin` privacy sub-package) |
| CCP-08 | Add `approval_requests` (requester, action type, payload hash, approver, status, expires_at). | Dual-control actions (FR-ADM-004, role-permission-matrix §5) need a shared mechanism; not in the brief. | `admin`, `audit` | → Accepted in brief v0.2 (owner `admin`; approver ≠ requester; 72 h expiry) |
| CCP-09 | Add `test_assignments` (test ↔ batch/user, window, attempt limit, release mode) and `attempt_overrides`. | FR-ORG-014, FR-ASM-007; overrides must be distinct, auditable records. | `assessments` | → Accepted in brief v0.2 (`release_mode` on `test_assignments`) |
| CCP-10 | Add `recommendations` / `topic_mastery` (user × subtopic) as derived tables (originally proposed as `mastery_scores`). | FR-PLC-006/011/012 readiness engine (D1). Ownership: `placement` reads `analytics` aggregates. | `placement`, `analytics` | → Accepted-modified (`recommendations` in `placement`; mastery is analytics-owned `topic_mastery`; `mastery_scores` not created) |
| CCP-11 | Add `export_jobs` (requester, scope, filter, file key, expires_at, PII flag). | FR-ORG-015 audited, expiring exports. | `analytics` | → Accepted in brief v0.2 (owner `analytics`; security exports reference `approval_requests`) |
| CCP-12 | Add `users.is_minor` (derived from DOB, frozen on 18th birthday recalculation job) and `users.date_of_birth` in `user_profiles`. | BR-MIN-01/02 and FR-IDN-002 need a single queryable flag. | `identity` | → Accepted-modified (merged with SEC CCP-S6: `is_minor` defaults to true until `age_verified_at`; `privacy_tier` generated) |
| CCP-13 | Clarify a 15 min / 8 h tier for `security_reviewer` in the role table of the security doc (brief §1 already includes it) and note `support_agent` step-up for session kills. | Consistency between research (RPA §5 table omits security_reviewer) and brief. | Security docs | → Accepted in brief v0.2 §1 (tier mapping and step-up windows) |
