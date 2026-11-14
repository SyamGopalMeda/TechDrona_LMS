# Tech Drona LMS — Entity-Relationship Diagrams

> **Superseded (2026-11-14):** the LMS runs on Firebase (Vite React SPA + Cloud Functions + Firestore, project `billing-f4fe3`) — see `docs/firebase-migration-plan.md` and `docs/firebase/`. These PostgreSQL ERDs describe the legacy VM database, not the Firestore data model.

> **Single-company note (2026-11-06).** Tech Drona now runs as a single company ([ADR-0015](architecture-decisions/ADR-0015-single-company.md)); the college/B2B features described in this document (college portal and coordinators, institution contracts and seats, invitations and roster import, per-organization settings, trusted networks and lab devices, the "For colleges" page) are removed. Roles are Admin (`super_admin`), Trainer, Evaluator, Content manager and Student; finance, support, security and mentor duties belong to Admin. Batches are Tech Drona cohorts managed by Admin at `/admin/batches`; businesses use the corporate enquiry form at `/enquiries`. Where this document conflicts, ADR-0015 and [`single-company/REMOVAL-PLAN.md`](single-company/REMOVAL-PLAN.md) §8 win.

| Field | Value |
|---|---|
| Owner | System Architect |
| Status | **Partially implemented (v0.5)** — 123 tables migrated (113 contract tables + 10 implementation tables); 9 entities carry `_status "Planned - not yet migrated"` |
| Source of truth | `docs/database-schema.md` (columns, constraints, RLS, retention). Diagrams show keys and the most relevant columns only. |
| Revision | v0.2 (2026-11-03): aligned with Brief v0.2 and the reconciled schema (121 tables); see `docs/contract-reconciliation.md`. v0.3 (2026-11-03): wave-2 consistency pass (contract-reconciliation §7): `auth_sessions.status` adds `pending_session_choice`; `refunds.approval_request_id`; `users.is_synthetic`; `products.product_kind` uses the PRD vocabulary. v0.4 (2026-11-03): security review pass (CPR-ERD-01..04, `contract-reconciliation.md` §9): `session_network_observations` (122 tables); `approval_requests → case_decisions`; HMAC `key_version`; remember token; `idle_hold_until`; `is_minor_at_time` on evaluations; rule status-change columns; enum notes (`remember_device`, `replaced_same_device`, `engine_hc_L3`, `reattach_same_device`) v0.5 (2026-11-03, **Stage 10 schema sync**): diagrams aligned with the Alembic migrations — soft references (no FK yet) drawn dashed, implementation tables added (`coding_test_case_blobs`, `seat_waitlist`, `reconciliation_runs`, `security_user_state`, `security_notices`, `security_counters`, `security_report_exports`, `security_bulk_lifts`, `analytics_job_state`, `analytics_consumed_events`), key added columns shown, Planned entities marked; see §11 and `database-schema.md` §17. |

Legend: `PK` primary key, `FK` foreign key, `UK` unique. All tables are canonical in Brief v0.2 §4 (proposal origins are tagged in `database-schema.md`). Dashed relationships (`..`) are **soft references** (uuid without FK, used for partitioned tables) or polymorphic links.

---

## 0. Cross-domain overview

```mermaid
erDiagram
  users ||--o{ auth_sessions : "signs in via"
  users ||--o{ user_devices : "registers"
  devices ||--o{ user_devices : "trusted per user"
  users ||--o{ account_restrictions : "may have"
  users ||--o{ security_cases : "subject of"
  users ||--o{ org_memberships : "member of"
  organizations ||--o{ org_memberships : "has"
  organizations ||--o{ batches : "runs"
  batches ||--o{ batch_members : "contains"
  users ||--o{ role_grants : "holds"
  roles ||--o{ role_grants : "granted as"
  courses ||--o{ course_versions : "versioned as"
  users ||--o{ enrolments : "enrols"
  courses ||--o{ enrolments : "has"
  entitlements ||..o{ enrolments : "authorises (soft ref)"
  users ||--o{ entitlements : "owns"
  products ||--o{ entitlements : "grants"
  orders ||--o{ order_items : "contains"
  order_items ||--o| entitlements : "fulfils"
  subscriptions ||--o| entitlements : "renews"
  institution_contracts ||--o{ entitlements : "seats"
  topics ||--o{ questions : "classifies"
  questions ||--o{ question_versions : "versioned as"
  tests ||--o{ test_sections : "has"
  users ||--o{ test_attempts : "takes"
  tests ||--o{ test_attempts : "attempted as"
  question_versions ||--o{ attempt_responses : "answered in"
  coding_problems ||--o{ code_submissions : "receives"
  users ||--o{ code_submissions : "submits"
  users ||--o{ analytics_events : "emits"
  users ||--o{ notifications : "receives"
  users ||--o{ support_tickets : "raises"
  users ||--o{ unblock_requests : "submits"
  security_cases ||--o{ unblock_requests : "appealed via"
  users ||--o{ topic_mastery : "mastery"
  users ||--o{ privacy_requests : "exercises rights"
  organizations ||--o{ org_invitations : "invites"
  organizations ||--o{ org_trusted_networks : "registers"
  entitlements ||--o{ entitlement_events : "history"
  users ||--o{ mentor_bookings : "books"
  approval_requests ||..o{ policy_settings : "approves"
```

---

## 1. Identity and sessions

```mermaid
erDiagram
  users {
    uuid id PK
    citext email UK
    text phone_e164 UK
    text status
    boolean is_minor "default true until age verified"
    timestamptz age_verified_at
    text privacy_tier "generated: minor or adult"
    smallint restriction_level "cache, security-owned"
    boolean is_synthetic "v0.3"
    timestamptz sessions_valid_after
    timestamptz deleted_at
  }
  user_profiles {
    uuid user_id PK, FK
    text full_name
    date date_of_birth
    smallint graduation_year
  }
  user_credentials {
    uuid user_id PK, FK
    text password_hash "Argon2id PHC"
    int consecutive_failures
  }
  mfa_factors {
    uuid id PK
    uuid user_id FK
    text factor_type
    bytea webauthn_credential_id UK
    bigint totp_last_used_step
    timestamptz totp_confirmed_at "v0.5"
  }
  verification_tokens {
    uuid id PK
    uuid user_id FK
    text purpose
    bytea token_hash UK
    timestamptz expires_at
  }
  password_reset_tokens {
    uuid id PK
    uuid user_id FK
    bytea token_hash UK
  }
  consents {
    uuid id PK
    uuid user_id FK
    text purpose
    text action
    text notice_version
    uuid guardian_consent_id FK
  }
  guardian_consents {
    uuid id PK
    uuid child_user_id FK
    uuid guardian_user_id FK
    text verification_method
    text status
  }
  devices {
    uuid id PK
    bytea device_key_hash UK "HMAC-SHA256"
    smallint key_version "v0.4 HMAC key version"
    text client_type
    bytea fp_hash "phase 2, adults"
    uuid shared_organization_id FK "lab device"
  }
  user_devices {
    uuid id PK
    uuid user_id FK
    uuid device_id FK
    text trust_status "pending_otp, trusted, removed, expired"
    boolean counts_toward_cap
    timestamptz owner_verified_at "sms_otp, passkey, totp, support only"
    timestamptz remember_until "fixed, never slides"
    bytea remember_token_hash UK "v0.4 sha256"
    timestamptz remember_issued_at "v0.4"
    text removed_reason
  }
  auth_sessions {
    uuid id PK
    bytea token_hash UK "sha256 only"
    uuid user_id FK
    uuid device_id FK
    uuid user_device_id FK
    uuid organization_id FK
    text session_tier
    text scope "full, restricted, status_only (record only)"
    text status "pending_mfa, pending_device_otp, pending_session_choice, active, expired, revoked, blocked"
    text created_via "password ... unblock_reauth, remember_device (v0.4)"
    timestamptz last_step_up_at
    timestamptz idle_expires_at
    timestamptz absolute_expires_at
    timestamptz idle_hold_until "v0.4 attempt idle hold"
    timestamptz ended_at
    text end_reason "... replaced_same_device (v0.4)"
  }
  session_network_observations {
    uuid id PK
    timestamptz first_seen_at PK "partition key (v0.4)"
    timestamptz last_seen_at
    uuid auth_session_id "soft ref"
    uuid user_id "soft ref"
    text net_cluster
    int asn
    text network_type
  }
  login_attempts {
    uuid id PK
    timestamptz attempted_at PK "partition key"
    uuid user_id "soft ref"
    bytea identifier_hash "HMAC"
    smallint key_version "v0.4 HMAC key version"
    text network_type
    text outcome
    boolean pre_auth_blocked
  }
  playback_sessions {
    uuid id PK
    timestamptz started_at PK "partition key"
    uuid user_id "soft ref"
    uuid auth_session_id "soft ref"
    uuid lesson_asset_id "soft ref"
    uuid tab_id "v0.5 MED-04"
    text status
    timestamptz last_heartbeat_at
    text end_reason
  }

  users ||--|| user_profiles : "has"
  users ||--o| user_credentials : "has"
  users ||--o{ mfa_factors : "enrols"
  users ||--o{ verification_tokens : "receives"
  users ||--o{ password_reset_tokens : "requests"
  users ||--o{ consents : "records"
  users ||--o{ guardian_consents : "child of"
  guardian_consents ||--o{ consents : "evidences"
  users ||--o{ user_devices : "registers"
  devices ||--o{ user_devices : "linked"
  users ||--o{ auth_sessions : "opens"
  devices ||--o{ auth_sessions : "from"
  user_devices ||--o{ auth_sessions : "trusted device"
  users ||..o{ login_attempts : "soft ref"
  auth_sessions ||..o{ playback_sessions : "soft ref"
  auth_sessions ||..o{ session_network_observations : "soft ref (partitioned, v0.4)"
  users ||..o{ session_network_observations : "soft ref"
  organizations ||--o{ devices : "lab devices"
```

---

## 2. Security

```mermaid
erDiagram
  users {
    uuid id PK
  }
  security_signals {
    uuid id PK
    timestamptz occurred_at PK "partition key"
    uuid user_id "soft ref"
    text family "sharing, takeover, cap, abuse, integrity"
    text rule_key "SH-*, TO-*, HC-*, AB-*, IN-*, cap.*"
    text category "C, D, N"
    boolean is_minor_at_time "false for sharing"
  }
  risk_rules {
    uuid id PK
    text key UK
    text family
    text explanation_key
    uuid active_version_id FK
  }
  risk_rule_versions {
    uuid id PK
    uuid rule_id FK "NULL = ruleset version"
    text ruleset_version
    text semver
    text status
    uuid proposed_by FK
    uuid approved_by FK "not proposer"
    timestamptz status_changed_at "v0.4"
    uuid status_changed_by FK "v0.4, NULL = system"
    text status_change_reason "v0.4 incl. circuit_breaker, kill_switch"
  }
  risk_evaluations {
    uuid id PK
    timestamptz evaluated_at PK "partition key"
    uuid user_id "soft ref"
    text family
    text mode
    numeric score
    smallint level_after
    text action
    uuid restriction_id "soft ref"
    uuid case_id "soft ref"
    boolean is_minor_at_time "v0.4, always false (ck_re_no_minor)"
  }
  account_restrictions {
    uuid id PK
    uuid user_id FK
    smallint level
    text family
    text scope
    text source "engine or reviewer; L4 reviewer only"
    uuid evaluation_id "soft ref"
    uuid case_id FK
    uuid decision_id FK
  }
  security_cases {
    uuid id PK
    text case_ref UK "SEC-YYMM-XXXXXX"
    uuid user_id FK
    text status
    text opened_reason "engine_L3 ... engine_hc_L3 (v0.4)"
    boolean is_high_risk
    uuid assignee_id FK
  }
  unblock_requests {
    uuid id PK
    text reference UK "APL-YYMM-XXXXXX"
    uuid case_id FK
    uuid user_id FK
    uuid restriction_id FK
    text state "draft ... escalated ... closed"
    boolean requires_second_approval
  }
  case_notes {
    uuid id PK
    uuid case_id FK
    uuid author_id FK
    text visibility "internal or student"
  }
  case_decisions {
    uuid id PK "final decisions only (v0.4)"
    uuid case_id FK
    uuid unblock_request_id FK
    text outcome
    uuid decided_by FK
    uuid approved_by FK "not decider"
    uuid approval_request_id FK "v0.4 security.case.decision"
  }
  approval_requests {
    uuid id PK
    text action_type "incl. security.case.decision"
    uuid target_id "case id; one pending per case"
    text status
  }
  org_trusted_networks {
    uuid id PK
    uuid organization_id FK
    cidr cidr
    int asn
    text status
    uuid verified_by FK
  }
  security_incidents {
    uuid id PK
    text incident_ref UK
    text severity
    timestamptz certin_due_at
    timestamptz dpb_report_due_at
  }
  policy_settings {
    uuid id PK
    text setting_key
    text scope_type "platform, plan, organization, user"
    uuid scope_id
    int version
    uuid case_decision_id FK "user exceptions"
  }

  risk_rules ||--o{ risk_rule_versions : "versions"
  users ||..o{ security_signals : "soft ref"
  users ||..o{ risk_evaluations : "soft ref"
  security_signals ||..o{ risk_evaluations : "listed in signals JSON"
  users ||--o{ account_restrictions : "restricted"
  risk_evaluations ||..o{ account_restrictions : "caused"
  security_cases ||--o{ account_restrictions : "governs"
  users ||--o{ security_cases : "subject"
  security_cases ||--o{ unblock_requests : "appealed via"
  account_restrictions ||--o{ unblock_requests : "targets"
  security_cases ||--o{ case_notes : "has"
  security_cases ||--o{ case_decisions : "decided by"
  unblock_requests ||--o{ case_decisions : "answered by"
  case_decisions ||--o{ account_restrictions : "ends"
  case_decisions ||--o{ policy_settings : "grants user exception"
  approval_requests ||--o{ case_decisions : "approval_request_id (v0.4)"
  organizations ||--o{ org_trusted_networks : "registers"
  security_user_state {
    uuid user_id PK, FK
    numeric sharing_score
    numeric takeover_score
    smallint sharing_level
    timestamptz step_up_required_since "impl."
  }
  security_notices {
    uuid id PK
    text event_ref UK "ACC-YYYY-XXXXXX"
    uuid user_id FK
    text kind "replay, new_sign_in, new_country"
  }
  security_counters {
    text counter_key PK
    timestamptz bucket_start PK
    int count "impl. AB-* windows"
  }
  security_report_exports {
    uuid id PK
    uuid requested_by FK
    uuid approval_request_id FK
    text status "impl. SEC-32"
  }
  security_bulk_lifts {
    uuid id PK
    uuid requested_by FK
    uuid approval_request_id FK
    text status "impl. SEC-44/45"
  }
  users ||--o| security_user_state : "engine state (impl.)"
  users ||--o{ security_notices : "This wasn't me refs (impl.)"
  approval_requests ||--o{ security_report_exports : "approves (impl.)"
  approval_requests ||--o{ security_bulk_lifts : "approves (impl.)"
```

---

## 3. Organizations and RBAC

```mermaid
erDiagram
  organizations {
    uuid id PK
    citext slug UK
    text org_type
    text data_role
    text gstin
  }
  org_memberships {
    uuid id PK
    uuid organization_id FK
    uuid user_id FK
    text member_type
    text external_ref
  }
  batches {
    uuid id PK
    uuid organization_id FK
    text code
    smallint graduation_year
  }
  batch_members {
    uuid id PK
    uuid batch_id FK
    uuid organization_id FK
    uuid user_id FK
    text member_role
  }
  roles {
    uuid id PK
    text role_key UK
    text session_tier
    boolean mfa_required
  }
  permissions {
    uuid id PK
    text permission_key UK
    boolean is_sensitive
  }
  role_permissions {
    uuid role_id PK, FK
    uuid permission_id PK, FK
  }
  role_grants {
    uuid id PK
    uuid user_id FK
    uuid role_id FK
    text scope_type
    uuid scope_id "org, batch or course id"
    uuid organization_id FK
    timestamptz revoked_at
  }
  org_invitations {
    uuid id PK
    uuid organization_id FK
    uuid batch_id FK
    uuid bulk_import_job_id FK
    bytea token_hash UK "sha256"
    text status
    smallint resend_count
  }
  bulk_import_jobs {
    uuid id PK
    uuid organization_id FK
    bytea file_sha256 "UK with org (idempotent)"
    text status
  }
  users {
    uuid id PK
  }

  organizations ||--o{ org_memberships : "has"
  organizations ||--o{ org_invitations : "invites"
  organizations ||--o{ bulk_import_jobs : "imports"
  bulk_import_jobs ||--o{ org_invitations : "creates"
  batches ||--o{ org_invitations : "target batch"
  users ||--o{ org_invitations : "accepts"
  users ||--o{ org_memberships : "joins"
  organizations ||--o{ batches : "runs"
  batches ||--o{ batch_members : "contains"
  users ||--o{ batch_members : "member"
  roles ||--o{ role_permissions : "bundles"
  permissions ||--o{ role_permissions : "in"
  users ||--o{ role_grants : "holds"
  roles ||--o{ role_grants : "granted"
  organizations ||--o{ role_grants : "scoped to"
```

---

## 4. Catalog and learning

```mermaid
erDiagram
  courses {
    uuid id PK
    uuid organization_id FK "NULL = platform"
    citext slug
    text status
    uuid current_version_id FK
  }
  course_versions {
    uuid id PK
    uuid course_id FK
    int version_no
    text status
  }
  course_modules {
    uuid id PK
    uuid course_version_id FK
    uuid module_key "stable"
    int position
  }
  lessons {
    uuid id PK
    uuid course_module_id FK
    uuid lesson_key "stable across versions"
    text lesson_type
    uuid test_id FK
    uuid coding_problem_id FK
    uuid assignment_id FK
  }
  lesson_topics {
    uuid lesson_id PK, FK
    uuid topic_id PK, FK
    boolean is_primary
  }
  lesson_assets {
    uuid id PK
    uuid lesson_id FK
    int duration_seconds
    text provider
    text provider_asset_id UK "VdoCipher id"
    text s3_key
  }
  resources {
    uuid id PK
    uuid course_id FK
    uuid lesson_id FK
    uuid company_id FK
  }
  enrolments {
    uuid id PK
    uuid user_id FK
    uuid course_id FK
    uuid course_version_id FK
    uuid batch_id FK
    uuid entitlement_id FK
    text source
  }
  lesson_progress {
    uuid enrolment_id PK, FK
    uuid lesson_key PK
    text status
    int watched_seconds
  }
  assignments {
    uuid id PK
    uuid course_id FK
    uuid batch_id FK
    timestamptz due_at
  }
  assignment_submissions {
    uuid id PK
    uuid assignment_id FK
    uuid user_id FK
    uuid code_submission_id FK
    numeric score
  }
  certificates {
    uuid id PK
    text public_code UK
    uuid user_id FK
    uuid enrolment_id FK, UK
    uuid final_attempt_id FK
  }

  courses ||--o{ course_versions : "versions"
  course_versions ||--o{ course_modules : "has"
  course_modules ||--o{ lessons : "has"
  lessons ||--o{ lesson_assets : "has"
  lessons ||--o{ lesson_topics : "mapped to"
  topics ||..o{ lesson_topics : "covers (soft ref)"
  courses ||--o{ resources : "has"
  lessons ||--o{ resources : "has"
  courses ||--o{ enrolments : "has"
  course_versions ||--o{ enrolments : "pinned"
  enrolments ||--o{ lesson_progress : "tracks"
  lessons ||..o{ lesson_progress : "via lesson_key"
  assignments ||--o{ assignment_submissions : "receives"
  lessons }o..o| assignments : "references (soft ref)"
  enrolments ||--o| certificates : "earns"
```

---

## 5. Placement (taxonomy, question bank, practice)

```mermaid
erDiagram
  topics {
    uuid id PK
    uuid parent_id FK
    text kind "subject, topic, subtopic"
    text path UK
  }
  companies {
    uuid id PK
    citext slug UK
  }
  company_paths {
    uuid id PK
    uuid company_id FK
    text role_name
    int version_no
    jsonb pattern
  }
  company_path_steps {
    uuid id PK
    uuid company_path_id FK
    int position
    text step_type
    uuid test_id FK
    uuid topic_id FK
  }
  questions {
    uuid id PK
    uuid organization_id FK
    text question_type
    uuid primary_topic_id FK
    uuid current_version_id FK
  }
  question_versions {
    uuid id PK
    uuid question_id FK
    int version_no
    jsonb answer_key "server only"
    smallint difficulty
    uuid coding_problem_id FK
    text status
  }
  question_options {
    uuid id PK
    uuid question_version_id FK
    boolean is_correct "server only"
    smallint position
  }
  question_tags {
    uuid id PK
    uuid question_id FK
    text tag_type
    uuid topic_id FK
    uuid company_id FK
  }
  practice_sessions {
    uuid id PK
    uuid user_id FK
    text mode
    uuid topic_id FK
    jsonb served "v0.5 served questions + served_at"
  }
  practice_responses {
    uuid id PK
    uuid practice_session_id FK
    uuid question_version_id FK
    boolean is_correct
    smallint attempt_no
    boolean solution_viewed
  }
  topic_mastery {
    uuid user_id PK, FK
    uuid topic_id PK, FK
    numeric theta "owned by analytics"
    text band
  }
  mentor_slots {
    text _status "Planned - not yet migrated"
    uuid id PK
    uuid mentor_id FK
    timestamptz starts_at
    text session_kind
  }
  mentor_bookings {
    text _status "Planned - not yet migrated"
    uuid id PK
    uuid mentor_slot_id FK
    uuid user_id FK
    uuid entitlement_id FK "quota source"
    text status
  }
  interview_feedback {
    text _status "Planned - not yet migrated"
    uuid id PK
    uuid mentor_booking_id FK, UK
    jsonb scores
  }
  resumes {
    text _status "Planned - not yet migrated"
    uuid id PK
    uuid user_id FK
    int version_no
    boolean is_current
  }
  resume_reviews {
    text _status "Planned - not yet migrated"
    uuid id PK
    uuid resume_id FK
    uuid reviewer_id FK
    text status
  }
  recommendations {
    uuid id PK
    uuid user_id FK
    text rule_key
    text target_type
    uuid target_id "polymorphic"
  }

  topics ||--o{ topics : "parent of"
  companies ||--o{ company_paths : "has"
  company_paths ||--o{ company_path_steps : "ordered steps"
  topics ||--o{ questions : "primary topic"
  questions ||--o{ question_versions : "versions"
  question_versions ||--o{ question_options : "options"
  questions ||--o{ question_tags : "tagged"
  topics ||--o{ question_tags : "tag"
  companies ||--o{ question_tags : "tag"
  practice_sessions ||--o{ practice_responses : "answers"
  question_versions ||--o{ practice_responses : "answered"
  topics ||..o{ topic_mastery : "mastery per user (analytics-owned, soft ref)"
  mentor_slots ||--o{ mentor_bookings : "booked as"
  mentor_bookings ||--o| interview_feedback : "rated in"
  resumes ||--o{ resume_reviews : "reviewed in"
  topics ||--o{ practice_sessions : "scope"
```

---

## 6. Assessments

```mermaid
erDiagram
  tests {
    uuid id PK
    uuid organization_id FK
    text test_kind
    int version
    int duration_seconds
    jsonb review_policy
    timestamptz settings_locked_at
  }
  test_sections {
    uuid id PK
    uuid test_id FK
    smallint position
    int duration_seconds
  }
  test_section_rules {
    uuid id PK
    uuid test_section_id FK
    text rule_type "fixed or random"
    uuid question_id FK
    uuid question_version_id FK
    uuid topic_id FK
    smallint draw_count
  }
  test_assignments {
    uuid id PK
    uuid test_id FK
    uuid batch_id FK
    timestamptz available_from
    timestamptz available_until
    text release_mode
  }
  attempt_overrides {
    uuid id PK
    uuid test_id FK
    uuid user_id FK
    uuid batch_id FK
    int extra_time_seconds
  }
  test_attempts {
    uuid id PK
    uuid test_id FK
    uuid user_id FK
    uuid test_assignment_id FK
    smallint attempt_no
    text status
    jsonb layout "frozen selection"
    timestamptz deadline_at
    uuid bound_session_id FK "one session per attempt"
    uuid bound_device_id FK
    smallint rebind_count "same-device re-attach not counted"
  }
  attempt_sections {
    uuid attempt_id PK, FK
    uuid test_section_id PK, FK
    timestamptz deadline_at
  }
  attempt_responses {
    uuid id PK
    uuid attempt_id FK
    uuid question_version_id FK
    bigint client_seq
    jsonb response
  }
  attempt_events {
    uuid id PK
    timestamptz occurred_at PK "partition key"
    uuid attempt_id "soft ref"
    text event_type "... rebind, reattach_same_device (v0.4)"
  }
  attempt_results {
    uuid attempt_id PK, FK
    numeric score
    numeric percentile
    boolean rank_provisional
  }

  tests ||--o{ test_sections : "has"
  test_sections ||--o{ test_section_rules : "draws by"
  tests ||--o{ test_assignments : "assigned"
  tests ||--o{ attempt_overrides : "overrides"
  tests ||--o{ test_attempts : "attempted"
  test_assignments ||--o{ test_attempts : "context"
  test_attempts ||--o{ attempt_sections : "section timers"
  test_sections ||--o{ attempt_sections : "instantiated"
  test_attempts ||--o{ attempt_responses : "answers"
  test_attempts ||..o{ attempt_events : "soft ref"
  test_attempts ||--o| attempt_results : "scored as"
```

---

## 7. Coding

```mermaid
erDiagram
  judge_languages {
    uuid id PK
    text language_key UK
    int provider_language_id
  }
  coding_problems {
    uuid id PK
    uuid organization_id FK
    citext slug
    int version_no
    boolean is_free "v0.5"
    uuid primary_topic_id "soft ref"
    int time_limit_ms
    int memory_limit_kb
  }
  coding_test_cases {
    uuid id PK
    uuid coding_problem_id FK
    int problem_version
    boolean is_sample
    boolean is_hidden
    text input_s3_key "encrypted"
    bytea wrapped_data_key
  }
  code_submissions {
    uuid id PK
    uuid user_id FK
    uuid coding_problem_id FK
    text language_key FK
    text mode "run or submit"
    uuid attempt_id "soft ref"
    uuid practice_session_id "soft ref"
    text judge_provider "judge0_cloud, judge0_selfhosted, fake"
    bytea normalized_sha256 "v0.5 plagiarism hook"
    smallint retry_count "v0.5"
    text verdict
  }
  coding_test_case_blobs {
    uuid id PK
    uuid coding_problem_id FK
    uuid organization_id FK
    bytea ciphertext "AES-256-GCM; stand-in for S3 td-judge-private"
  }
  submission_results {
    uuid id PK
    uuid code_submission_id FK
    uuid test_case_id FK
    text verdict
    int time_ms
  }

  coding_problems ||--o{ coding_test_cases : "has"
  coding_problems ||--o{ coding_test_case_blobs : "hidden case ciphertext (impl.)"
  coding_test_cases ||..o| coding_test_case_blobs : "input/expected_s3_key = db:blob/uuid"
  coding_problems ||--o{ code_submissions : "receives"
  judge_languages ||--o{ code_submissions : "in"
  code_submissions ||--o{ submission_results : "per case"
  coding_test_cases ||--o{ submission_results : "evaluated"
  test_attempts ||..o{ code_submissions : "inside attempt (soft ref)"
  question_versions }o..o| coding_problems : "coding question (soft ref)"
```

---

## 8. Commerce and entitlements

```mermaid
erDiagram
  products {
    uuid id PK
    citext sku UK
    text product_kind "PRD vocabulary (v0.3)"
    numeric gst_rate
  }
  product_items {
    uuid id PK
    uuid product_id FK
    text item_type
    uuid course_id FK
    uuid test_id FK
    text feature_key
    bigint unit_price_paise "v0.5"
  }
  plans {
    uuid id PK
    uuid product_id FK
    text billing_type
    int access_duration_days
  }
  prices {
    uuid id PK
    uuid plan_id FK
    bigint amount_paise "recurring max 1500000"
    boolean is_recurring
  }
  coupons {
    uuid id PK
    citext code UK
    text discount_type
  }
  coupon_redemptions {
    uuid id PK
    uuid coupon_id FK
    uuid order_id FK
    uuid user_id FK
    text status
  }
  orders {
    uuid id PK
    text order_number UK
    uuid user_id FK
    uuid organization_id FK
    text gateway_order_id UK
    text status
    bigint total_paise
  }
  order_items {
    uuid id PK
    uuid order_id FK
    uuid product_id FK
    uuid price_id FK
  }
  payments {
    uuid id PK
    uuid order_id FK
    uuid subscription_id FK
    text gateway_payment_id UK
    text status
  }
  payment_webhook_events {
    uuid id PK
    text event_id UK "with gateway"
    text event_type
    text status
    boolean is_stale "monitoring only"
    text refetch_status "v0.4 ok, failed, not_required"
    uuid order_id FK
  }
  subscriptions {
    uuid id PK
    uuid user_id FK
    uuid plan_id FK
    text gateway_subscription_id UK
    bigint mandate_max_amount_paise
    timestamptz current_period_end
  }
  refunds {
    uuid id PK
    uuid payment_id FK
    uuid order_id FK
    bigint amount_paise
    text status
    uuid approval_request_id FK "Dual refunds (v0.3)"
  }
  invoices {
    uuid id PK
    text invoice_number UK
    text invoice_type
    uuid order_id FK
    uuid refund_id FK
    uuid original_invoice_id FK
  }
  invoice_sequences {
    text series PK
    text fiscal_year PK
    bigint next_value
  }
  institution_contracts {
    uuid id PK
    uuid organization_id FK
    uuid product_id FK
    int seat_count
    uuid order_id FK
    smallint grace_days "v0.5"
    int reassignment_allowance "v0.5"
    int reassignments_used "v0.5"
    int seats_burned "v0.5"
    int version "v0.5 ETag"
  }
  entitlements {
    uuid id PK
    uuid user_id FK
    uuid product_id FK
    text source_type "free_enrolment ... trial"
    uuid order_item_id FK, UK
    uuid subscription_id FK, UK
    uuid institution_contract_id FK
    uuid coupon_redemption_id FK
    uuid granted_by FK
    text status "active, grace, suspended, revoked, expired"
    timestamptz ends_at
    timestamptz grace_ends_at
    smallint mentor_sessions_remaining
  }
  entitlement_events {
    uuid id PK
    uuid entitlement_id FK
    text event_type
    timestamptz occurred_at
  }

  products ||--o{ product_items : "unlocks"
  products ||--o{ plans : "sold as"
  plans ||--o{ prices : "priced"
  coupons ||--o{ coupon_redemptions : "redeemed"
  orders ||--o{ coupon_redemptions : "applies"
  orders ||--o{ order_items : "lines"
  prices ||--o{ order_items : "priced at"
  orders ||--o{ payments : "paid by"
  subscriptions ||--o{ payments : "charges"
  orders ||..o{ payment_webhook_events : "about"
  payments ||--o{ refunds : "refunded by"
  orders ||--o{ invoices : "invoiced"
  refunds ||--o| invoices : "credit note"
  plans ||--o{ subscriptions : "subscribed"
  order_items ||--o| entitlements : "source order_item"
  subscriptions ||--o| entitlements : "source subscription"
  institution_contracts ||--o{ entitlements : "source contract seats"
  products ||--o{ entitlements : "grants"
  products ||--o{ institution_contracts : "licensed"
  coupon_redemptions ||--o| entitlements : "source coupon_grant"
  entitlements ||--o{ entitlement_events : "history"
  institution_contracts ||--o{ seat_waitlist : "waitlist (impl.)"
  users ||--o{ seat_waitlist : "waits"
  seat_waitlist |o--o| entitlements : "assigned seat"
  seat_waitlist {
    uuid id PK
    uuid institution_contract_id FK
    uuid organization_id FK
    uuid user_id FK
    text status "waiting, assigned, cancelled"
    uuid entitlement_id FK
  }
  reconciliation_runs {
    uuid id PK
    text gateway
    timestamptz range_from
    timestamptz range_to
    jsonb mismatches "impl., platform-only RLS"
  }
```

---

## 9. Analytics

```mermaid
erDiagram
  analytics_events {
    uuid event_id PK "client UUIDv7"
    timestamptz event_ts PK "partition key, from event_id"
    uuid user_id "soft ref"
    text event_type
    text purpose "learning or product"
    timestamptz effective_at
    text privacy_tier
  }
  activity_heartbeats {
    uuid event_id PK
    timestamptz event_ts PK "partition key"
    uuid user_id "soft ref"
    uuid device_id "soft ref"
    uuid auth_session_id "soft ref"
    text kind "engaged or keepalive"
    int active_ms
  }
  engagement_intervals {
    uuid id PK
    timestamptz started_at PK "partition key"
    uuid user_id "soft ref"
    int active_s
    boolean is_open
    text measurement_version
  }
  daily_learning_aggregates {
    uuid user_id PK
    date activity_date PK "IST"
    text entity_kind PK
    uuid entity_id PK
    int m5_learning_s
    boolean is_frozen
  }
  weekly_learning_aggregates {
    uuid user_id PK
    date iso_week_start PK
    text entity_kind PK
    uuid entity_id PK
  }
  cohort_learning_aggregates {
    uuid id PK
    uuid organization_id "NULL = platform"
    uuid batch_id
    date period_start
    boolean suppressed "k-rule"
  }
  route_daily_aggregates {
    text route PK
    date activity_date PK
  }
  video_watch_coverage {
    uuid user_id PK
    uuid lesson_asset_id PK
    numeric coverage_pct
  }
  topic_mastery {
    uuid user_id PK, FK
    uuid topic_id PK, FK
    numeric theta
  }
  question_item_stats {
    uuid question_version_id PK, FK
    numeric p_value
    boolean review_flag
  }
  security_activity_feed_daily {
    uuid user_id PK
    date activity_date PK
    int multi_device_overlap_s
    text feed_version
  }
  analytics_dirty_days {
    uuid user_id PK
    date activity_date PK
  }
  analytics_ingest_rejections {
    timestamptz hour_start PK
    text code PK
    text event_type PK
  }
  export_jobs {
    text _status "Planned - not yet migrated"
    uuid id PK
    uuid requested_by FK
    uuid approval_request_id FK
    boolean contains_pii
    timestamptz expires_at
  }

  activity_heartbeats ||..o{ engagement_intervals : "sessionized into"
  engagement_intervals ||..o{ daily_learning_aggregates : "rolled up"
  analytics_events ||..o{ daily_learning_aggregates : "rolled up"
  daily_learning_aggregates ||..o{ weekly_learning_aggregates : "rolled up"
  daily_learning_aggregates ||..o{ cohort_learning_aggregates : "rolled up (k-rule)"
  activity_heartbeats ||..o{ video_watch_coverage : "played ranges"
  analytics_events ||..o{ topic_mastery : "answer events"
  analytics_events ||..o{ question_item_stats : "first attempts"
  engagement_intervals ||..o{ security_activity_feed_daily : "adults with consent"
  analytics_dirty_days ||..o{ daily_learning_aggregates : "triggers recompute"
  analytics_job_state {
    text job PK
    timestamptz watermark "impl. builder watermark"
  }
  analytics_consumed_events {
    uuid outbox_event_id PK "impl. idempotent outbox consumption"
    text event_type
  }
  outbox_events ||..o| analytics_consumed_events : "consumed once"
```

---

## 10. Platform, approvals and privacy

```mermaid
erDiagram
  audit_outbox {
    uuid id PK
    jsonb record
  }
  audit_log {
    bigint seq PK
    timestamptz occurred_at PK "partition key"
    text action
    text reason_code
    uuid target_id
    bytea prev_hash
    bytea row_hash
  }
  outbox_events {
    uuid id PK
    text event_type
    timestamptz dispatched_at
  }
  idempotency_keys {
    uuid id PK
    uuid user_id FK
    text idem_key
  }
  approval_requests {
    uuid id PK
    text action_type
    bytea payload_hash
    uuid requested_by FK
    uuid decided_by FK "not requester"
    text status
    timestamptz expires_at
  }
  policy_settings {
    uuid id PK
    text setting_key
    text scope_type
    uuid approval_request_id FK
  }
  feature_flags {
    uuid id PK
    text flag_key UK
  }
  notifications {
    uuid id PK
    uuid user_id FK
    text template_key
    text status
  }
  support_tickets {
    text _status "Planned - not yet migrated"
    uuid id PK
    text ticket_number UK
    uuid requester_id FK
    uuid related_order_id FK
    uuid related_case_id FK
    uuid privacy_request_id FK
  }
  support_ticket_messages {
    text _status "Planned - not yet migrated"
    uuid id PK
    uuid support_ticket_id FK
    text visibility
  }
  privacy_requests {
    uuid id PK
    text request_ref UK
    uuid user_id FK
    text request_type
    timestamptz due_at
    uuid export_job_id FK
  }
  retention_policies {
    uuid id PK
    text table_name
    text retention_class
    text job_name
  }
  erasure_ledger {
    text _status "Planned - not yet migrated"
    uuid id PK
    bytea subject_hash "HMAC, never user id"
    uuid privacy_request_id FK
  }
  users {
    uuid id PK
  }

  audit_outbox ||..|| audit_log : "sealed into (hash chain)"
  approval_requests ||--o{ policy_settings : "approves"
  approval_requests ||--o{ export_jobs : "approves"
  approval_requests ||--o{ risk_rule_versions : "approves"
  users ||--o{ notifications : "receives"
  users ||--o{ support_tickets : "raises"
  support_tickets ||--o{ support_ticket_messages : "thread"
  privacy_requests ||--o| support_tickets : "tracked by"
  users ||--o{ privacy_requests : "exercises rights"
  privacy_requests ||--o{ erasure_ledger : "records erasure"
  privacy_requests ||..o| export_jobs : "access export (soft ref; export_jobs Planned)"
  users ||..o{ idempotency_keys : "uses (soft ref)"
```

---

## 11. Implementation status and changelog (v0.5, Stage 10 schema sync — 2026-11-03)

The Alembic migrations in `apps/api/migrations/versions/` are the source of truth; `database-schema.md` §17 is the full as-migrated reference (revision inventory, deviation register, soft references, RLS, partitioning).

| Item | As migrated |
|---|---|
| Migrated tables | 123 = 113 of the 122 contract tables + 10 implementation tables |
| Planned — not yet migrated | `mentor_slots`, `mentor_bookings`, `interview_feedback`, `resumes`, `resume_reviews`, `support_tickets`, `support_ticket_messages`, `export_jobs`, `erasure_ledger` (marked `_status "Planned - not yet migrated"` in the diagrams) |
| Implementation tables | §2 `security_user_state`, `security_notices`, `security_counters`, `security_report_exports`, `security_bulk_lifts`; §7 `coding_test_case_blobs`; §8 `seat_waitlist`, `reconciliation_runs`; §9 `analytics_job_state`, `analytics_consumed_events` |
| Soft references drawn dashed in v0.5 | `entitlements → enrolments`, `topics → lesson_topics`, `lessons → assignments`, `topics → topic_mastery`, `test_attempts → code_submissions`, `question_versions → coding_problems`, `privacy_requests → export_jobs`, `users → idempotency_keys`. Also soft but not drawn: `lessons.test_id` / `coding_problem_id`, `resources.company_id`, `courses.primary_topic_id`, `certificates.final_attempt_id`, `assignment_submissions.code_submission_id`, `test_assignments.course_id`, `product_items.course_id` / `test_id` / `company_path_id` / `topic_id`, `entitlements.course_id`, `question_item_stats.question_version_id` |
| FKs added by a later revision | `consents.organization_id` (identity_0002), `company_path_steps.test_id` (placement_0002); drawn solid |
| Partitioned tables | DEFAULT partition only; `pg_partman` monthly partitions Planned |

**Changelog**

- v0.5 (2026-11-03, Stage 10 schema sync): header status changed from Planned to Partially implemented; Planned entities marked; soft references redrawn dashed; implementation tables added to §2, §7, §8 and §9; key added columns shown (`mfa_factors.totp_confirmed_at`, `playback_sessions.tab_id`, `practice_sessions.served`, `coding_problems.is_free`, `code_submissions.judge_provider` incl. `fake`, `normalized_sha256`, `retry_count`, `institution_contracts` grace/reassignment/version, `product_items.unit_price_paise`).
