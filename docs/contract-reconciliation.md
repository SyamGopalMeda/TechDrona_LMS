# Tech Drona LMS — Contract Reconciliation (wave 1 → wave 2)

> **Single-company note (2026-11-06).** Tech Drona now runs as a single company ([ADR-0015](architecture-decisions/ADR-0015-single-company.md)); the college/B2B features described in this document (college portal and coordinators, institution contracts and seats, invitations and roster import, per-organization settings, trusted networks and lab devices, the "For colleges" page) are removed. Roles are Admin (`super_admin`), Trainer, Evaluator, Content manager and Student; finance, support, security and mentor duties belong to Admin. Batches are Tech Drona cohorts managed by Admin at `/admin/batches`; businesses use the corporate enquiry form at `/enquiries`. Historical record; the college/B2B decisions below are superseded. Where this document conflicts, ADR-0015 and [`single-company/REMOVAL-PLAN.md`](single-company/REMOVAL-PLAN.md) §8 win.

| Field | Value |
|---|---|
| Owner | Integration Lead |
| Date | 2026-11-03 |
| Status | **Planned** (blueprint stage, documentation only) |
| Result | `docs/blueprint-brief.md` **v0.2**; `docs/database-schema.md` and `docs/database-erd.md` updated to match. **Wave-2 pass (§7):** brief **v0.3**, schema/ERD v0.3, role matrix v0.2, PRD v0.2, architecture v0.3, ADR-0014; requests for frozen files in `docs/integration-pass-requests.md` |
| Inputs | `blueprint-brief.md` v0.1; `source-requirements-excerpt.md`; `product-requirements.md` §12 (CCP-01..13) and OPD-01..13; `system-architecture.md` §23 (CCP-1..13); `account-security-and-risk-engine.md` §12 (data model) and §13 (CCP-S1..S7); `account-unblock-workflow.md` §10 (CCP-U1..U3); `privacy-and-data-retention.md` §12 (CCP-P1); `security-threat-model.md` §8; `analytics-event-schema.md` §10 (DM-1..12) and §11 (CP-1..12); `database-schema.md` §15; `role-permission-matrix.md` |

Wave-2 authors (API spec, QA, DevOps, roadmap) work from brief v0.2 and `database-schema.md`. Where a wave-1 document still disagrees with them, **brief v0.2 and the schema win** until the follow-up edits in §6 are applied.

---

## 1. Decision rules applied

1. **Domain owner wins inside their domain** unless the proposal breaks another contract: Security Specialist for sessions/devices/risk/unblock/privacy semantics; Analytics Engineer for analytics tables, measurement and ingest; System Architect for physical schema conventions (types, partitioning, RLS families, naming style); Product Analyst for business vocabulary and screens.
2. **Stricter privacy wins** when two owners disagree on retention or disclosure thresholds and neither gives a functional need for the looser value.
3. **One writer per table.** When two authors proposed overlapping tables, one name and one owning module were chosen; the other is recorded as merged.
4. **Additive over subtractive.** Additions to the product owner's verbatim lists (e.g. the `Escalated` unblock state) are accepted only when nothing required is removed, and are flagged for product-owner confirmation (§5).
5. **Business policy is not decided here.** Items that change pricing, customer-facing policy or a decision the product owner approved on 2026-11-03 are listed in §5 with the default the documents now assume.

Decision values: **Accepted**, **Accepted-modified** (accepted with a stated change), **Rejected**, **Deferred-to-owner** (product owner or counsel must decide; default stated).

---

## 2. Proposal register (every proposal from every document)

### 2.1 Product requirements (`product-requirements.md` §12)

| Source + ID | Summary | Decision | Rationale | Affected files |
|---|---|---|---|---|
| PRD CCP-01 | Max 1 active session per timed-test attempt; others read-only; "Move test here" with OTP | **Accepted-modified** | Merged with SEC CCP-S3. Security owns enforcement: the attempt is bound to one session (`test_attempts.bound_session_id`); rebind needs explicit confirmation, OTP only when restriction level ≥ L2 (`assessment.rebind_requires_otp_at_level`), max 2 rebinds per attempt, proctored drives need a trainer override. OTP on every move (PRD) was rejected as hostile to the crash/power-cut case (Phase-8 scenario 16) | brief §1; schema `test_attempts`, `attempt_events`, `policy_settings`; PRD FR-SES-011 (follow-up) |
| PRD CCP-02 | `mentor_slots`, `mentor_bookings`, `interview_feedback` | **Accepted** | FR-PLC-010 (P1) has no home. Owner `placement`. External meeting URL column per OPD-08 default | brief §4; schema §8 |
| PRD CCP-03 | `placement_drives`, `drive_eligibility_rules`, `drive_shortlists` | **Deferred-to-owner** | Tied to OPD-12 (drives P1 vs P2). Default **P2**: names reserved in brief §4 and schema §16, no DDL in the baseline | brief §4 (reserved); schema §16 |
| PRD CCP-04 | `org_invitations`, `bulk_import_jobs` | **Accepted** | FR-ORG-010/011 idempotent import and invite status tracking. Invite token stored as SHA-256 (brief hashing rule) | brief §4; schema §6 |
| PRD CCP-05 | Entitlement columns (`source_type`, `source_id`, `grace_ends_at`, `status` incl. grace, quotas, revocation reason) + `entitlement_events` | **Accepted-modified** | Kept the architect's typed source FK columns (one per source) instead of a polymorphic `source_id`; adopted the PRD `source_type` vocabulary and `grace` status; quotas as explicit columns; column name stays `revoke_reason` (schema naming). `entitlement_events` added as append-only history | schema §11; PRD "Entitlement row" (follow-up) |
| PRD CCP-06 | `resumes`, `resume_reviews` | **Accepted** | FR-PLC-015 (P1). Owner `placement` | brief §4; schema §8 |
| PRD CCP-07 | `support_ticket_messages`, `privacy_requests` | **Accepted** | Replaces `support_tickets.messages` JSONB. `privacy_requests` merged with SEC CCP-S2 / ARCH CCP-13 (one table, owner `admin` privacy sub-package) | brief §2, §4; schema §13 |
| PRD CCP-08 | `approval_requests` (dual control) | **Accepted** | Required by FR-ADM-004, role matrix §5, risk-rule activation, policy changes. Owner `admin`; CHECK approver ≠ requester; 72 h expiry | brief §4; schema §13 |
| PRD CCP-09 | `test_assignments`, `attempt_overrides` | **Accepted** | Same tables as ARCH CCP-3; `release_mode` column added to `test_assignments` | schema §9 |
| PRD CCP-10 | `recommendations` / `mastery_scores` | **Accepted-modified** | `recommendations` (placement, ARCH CCP-4). Mastery is one table **`topic_mastery`** owned by `analytics` (AN CP-11); `mastery_scores` and the architect's `user_topic_mastery` are not created | schema §8, §12; PRD (follow-up); system-architecture §4.2 (follow-up) |
| PRD CCP-11 | `export_jobs` (audited, expiring exports) | **Accepted** | FR-ORG-015, Section H "exportable only by authorised users". Owner `analytics`; security exports reference an `approval_requests` row | brief §4; schema §12 |
| PRD CCP-12 | `users.is_minor` (derived) + DOB in `user_profiles` | **Accepted-modified** | Merged with SEC CCP-S6. `is_minor` defaults to **true** until an age determination exists (`age_verified_at`); a CHECK forbids adult status without it; `privacy_tier` generated from it | brief §1 Minors; schema §3 |
| PRD CCP-13 | Clarify 15 min / 8 h tier for `security_reviewer`; `support_agent` step-up for session kills | **Accepted** | All documents already agree; recorded explicitly in brief §1 with the tier mapping and step-up windows | brief §1 |

### 2.2 System architecture (`system-architecture.md` §23)

| Source + ID | Summary | Decision | Rationale | Affected files |
|---|---|---|---|---|
| ARCH CCP-1 | `outbox_events`, `idempotency_keys` (core) | **Accepted** | Same need as AN CP-8 / DM-7. Single outbox for all server-emitted domain events | brief §2, §4, §5; schema §2.3 |
| ARCH CCP-2 | `audit_outbox` (sealer pattern) | **Accepted** | Single ordered writer for the hash chain (ADR-0011) | brief §4; schema §13 |
| ARCH CCP-3 | `test_assignments`, `attempt_overrides`, `attempt_sections` | **Accepted** | Merged with PRD CCP-09 | brief §4; schema §9 |
| ARCH CCP-4 | `practice_sessions`, `practice_responses`, `user_topic_mastery`, `recommendations`, `company_path_steps` | **Accepted-modified** | All accepted except `user_topic_mastery`, which becomes analytics-owned `topic_mastery` (AN CP-11, one writer). `practice_responses` gains AN DM-5 columns | brief §4; schema §8, §12 |
| ARCH CCP-5 | `product_items`, `invoice_sequences` | **Accepted** | Access check mapping; gap-free GST numbering | brief §4; schema §11 |
| ARCH CCP-6 | `judge_languages` | **Accepted** | Per-language limits and provider ids | brief §4; schema §10 |
| ARCH CCP-7 | `policy_settings`, `feature_flags` owned by `admin` | **Accepted** | One owner per table; `security` is the main consumer via `core.policy` | brief §2, §4 |
| ARCH CCP-8 | `playback_sessions` owned by `sessions` | **Accepted** | All concurrency caps in one module | brief §2 |
| ARCH CCP-9 | Second Redis cluster (`queue`, `noeviction`) | **Accepted** | Broker data must never be evicted | brief §1 Cache/queue |
| ARCH CCP-10 | `api-webhooks` as a separate ECS service from the same image | **Accepted** | Isolation without a second codebase; still a modular monolith | brief §1 Architecture |
| ARCH CCP-11 | `lessons.lesson_key` stable across versions; progress keyed by it | **Accepted** | Republishing must not reset progress | brief §4 common rules; schema §7 |
| ARCH CCP-12 | Hash-only storage for device tokens, verification/reset tokens, login identifiers | **Accepted-modified** | Security §1.1 specifies a **keyed HMAC-SHA-256** for the device cookie (`devices.device_key_hash`) and login identifiers (`login_attempts.identifier_hash`); SHA-256 stays for session, verification, reset and invite tokens | brief §1 Sessions; schema §3, §4, §6 |
| ARCH CCP-13 | `privacy_requests` (left to Security) | **Accepted** | Merged with PRD CCP-07 and SEC CCP-S2 | schema §13 |

### 2.3 Security (`account-security-and-risk-engine.md` §12–13, `account-unblock-workflow.md` §10, `privacy-and-data-retention.md` §12, `security-threat-model.md` §8)

| Source + ID | Summary | Decision | Rationale | Affected files |
|---|---|---|---|---|
| SEC CCP-S1 | `org_trusted_networks` | **Accepted** | CGNAT and campus-NAT exceptions (§5.5). Owner `security`; coordinator proposes, reviewer verifies | brief §4; schema §5 |
| SEC CCP-S2 | `privacy_requests`, `security_incidents`, `retention_policies` | **Accepted** | DPDP rights queue, CERT-In 6 h / DPB clocks, deletion-job registry. Owners: `privacy_requests`, `retention_policies` → `admin` (privacy sub-package); `security_incidents` → `security` | brief §2, §4; schema §5, §13 |
| SEC CCP-S3 | 1 session may hold an in-progress attempt; rebind with confirmation, OTP at ≥ L2 | **Accepted** | See PRD CCP-01 | brief §1 Device policy |
| SEC CCP-S4 | Minors: "security-necessary" includes deterministic takeover controls, no accumulated scores | **Accepted** | Clarification; no conflict with DPDP s.9(3) reading in privacy doc | brief §1 Minors |
| SEC CCP-S5 | L4 is applied by a human only; engine only recommends | **Accepted** | Matches research and threat model | brief §1 Risk engine |
| SEC CCP-S6 | `users.is_minor` + `age_verified_at`; unverified age ⇒ minor treatment | **Accepted** | See PRD CCP-12 | brief §1; schema §3 |
| SEC CCP-S7 | Each browser profile counts as a device (Terms); college lab devices do not count toward personal caps | **Accepted** (customer-facing wording **Deferred-to-owner**, PO-02) | Technically required (the device cookie identifies a browser profile). Terms wording needs product-owner sign-off | brief §1 Device policy; schema `devices.shared_organization_id`, `user_devices.counts_toward_cap` |
| SEC-DM-01 | `users`: `is_minor`, `age_verified_at`, `account_status` enum, `sessions_valid_after`, `must_change_password` | **Accepted-modified** | `account_status` rejected as a second status enum (identity already has a lifecycle `status`; restrictions live in `account_restrictions`). Replaced by cached `users.restriction_level` (0–4, written only by `security`). Other columns accepted | schema §3 |
| SEC-DM-02 | `auth_sessions`: all §1.2 fields; index (user_id, ended), unique token hash | **Accepted-modified** | All §1.2 fields adopted with security names (`amr`, `last_step_up_at`, `ip_first/ip_last`, `net_cluster_*`, `ua_hash` instead of raw UA, `created_via`, …). Two naming exceptions: `session_tier` (used by `roles` and the architecture doc) instead of `role_tier`; `ended_at/end_reason/ended_by` instead of `revoked_*`, because the source requirement asks for *logout time* and *termination reason* for every ended session (expiry included). Status vocabulary adds `blocked` (source requirement Section A) | brief §1; schema §4; security doc §1.2, §8 (follow-up) |
| SEC-DM-03 | `devices`: `device_key_hash`, `client_type`, UA/OS/class, `fp_hash`, `fp_epoch`, `shared_scope`, `shared_registered_by`, `label_hint` | **Accepted-modified** | `shared_scope` text replaced by typed `shared_organization_id` FK (RLS-friendly, no string parsing). `first_seen_ip` removed from `devices` (table has no RLS; IP stays in sessions/login rows) | schema §4 |
| SEC-DM-04 | `user_devices`: `trust_status` (pending_otp/trusted/removed/expired), `owner_verified_at`, `counts_toward_cap`, … | **Accepted** | Replaces architect enum (`pending_verification`, `blocked`) | schema §4 |
| SEC-DM-05 | `login_attempts`: `identifier_hash` (HMAC), `network_type`, `failure_reason`, `pre_auth_blocked`, `mfa_method`; monthly partitions | **Accepted** | `geo_country`/`geo_region` added for consistency with sessions (no city) | schema §4 |
| SEC-DM-06 | `playback_sessions`: `end_reason` (stopped/stale/taken_over/revoked), `provider_otp_ref_hash` | **Accepted** | Replaces architect `end_reason` list | schema §4 |
| SEC-DM-07 | `security_signals`: family, rule_key, rule_version, category C/D/N, base_points, multipliers, evidence, source, `is_minor_at_time` CHECK | **Accepted** | Architect's `abuse`/`integrity` families retained for non-sharing system signals (webhook signature failures, plausibility) | schema §5 |
| SEC-DM-08 | `risk_rules`, `risk_rule_versions` (ruleset rows, semver, shadow report, approver ≠ proposer) | **Accepted** | Answers schema §15 "first-class ruleset?" — yes, as `risk_rule_versions` rows with `rule_id NULL` | schema §5 |
| SEC-DM-09 | `risk_evaluations`: §9 record, monthly partitions, append-only | **Accepted** | Action vocabulary from security §9 replaces the architect's; `feed_version` added (AN §6.5) | schema §5 |
| SEC-DM-10 | `account_restrictions`: scope, deferred_until, source, decision link, one active per user per family | **Accepted** | Replaces architect `restriction_type/feature_key`; L4 lift second approval enforced through `case_decisions` | schema §5 |
| SEC-DM-11 | `security_cases`: `case_ref` (`SEC-YYMM-XXXXXX`), `is_high_risk`, SLA columns | **Accepted** | Replaces `case_number 'SC-…'`. Answers schema §15: second approval is triggered by `is_high_risk` + unblock doc §5 rules, not by level alone | schema §5 |
| SEC-DM-12 | `unblock_requests`: unblock doc §3 fields + state, `reference` (`APL-…`), `requires_second_approval`, `escalated_at` | **Accepted** | States per CCP-U1 | schema §5 |
| SEC-DM-13 | `case_notes`: visibility internal/student, body ≤ 4,000, attachments | **Accepted** | | schema §5 |
| SEC-DM-14 | `case_decisions`: outcome vocabulary, `approved_by ≠ decided_by` | **Accepted** | Architect's `convert_to_paid_seat` **rejected** as a decision outcome: the buddy seat is a commerce product (security §5.5), not a case remedy | schema §5 |
| SEC-DM-15 | `policy_settings`: scope platform/plan/organization/user, min/max, locked, expires_at, approved_by | **Accepted** | Replaces the architect's platform/organization-only design | schema §13 |
| SEC-DM-16 | `activity_heartbeats` must carry device, session, 5-min bucket, kind, engaged flag for SH-01 | **Accepted-modified** | Columns exist in the analytics design (`device_id`, `auth_session_id`, `effective_at`, `kind`, `state_bits`, `surface`). **Security does not read the table directly** (AN §6.5): analytics exposes `analytics.feeds.get_engaged_buckets(user_id, from, to)` returning `(device_id, auth_session_id, bucket_5min, activity_kind)` for adults with `security_monitoring` consent only. Used by SH-01/02 and dashboard H3 | brief §2 module rules; analytics doc §6.5, security doc §1.2 (follow-up) |
| SEC-DM-17 | `test_attempts`: `bound_session_id`, `bound_device_id`, `rebind_count` | **Accepted** | Replaces `auth_session_id`/`device_id` on attempts | schema §9 |
| SEC-DM-18 | `audit_log` accepts `security.*`, `case.*`, `policy.*`, `pii.reveal`, `export.*` with `reason_code` | **Accepted** | `reason_code` column added (free-text `reason` kept) | schema §13 |
| SEC-DM-19 | `user_security_exceptions` (or fold into `policy_settings` scope=user) | **Accepted-modified** | Folded into `policy_settings` (`scope_type='user'`, `expires_at` ≤ 180 days, `case_decision_id` required). No separate table | schema §13 |
| UNB CCP-U1 | Add `Escalated` to the canonical unblock states (student label "With senior reviewer") | **Accepted** (product-owner confirmation PO-01) | Needed for second-person approval and appeals; all seven verbatim states remain | brief §1 Unblock states; schema `unblock_requests.state` |
| UNB CCP-U2 | `case_decisions.approved_by/approved_at`, CHECK `approved_by <> decided_by` | **Accepted** | | schema §5 |
| UNB CCP-U3 | `auth_sessions.scope` (`full`/`restricted`/`status_only`) | **Accepted** | Lets `require_active_principal` gate L3/L4 sessions without a separate session type | brief §5; schema §4 |
| PRIV CCP-P1 | `erasure_ledger` so restores re-apply deletions | **Accepted** | Owner `admin` (privacy). Stores `subject_hash`, not the user id, so the ledger itself is not personal data after erasure | brief §4; schema §13 |
| THREAT §8 | None; note `audit_log` (brief) beats research `audit_events` | **Accepted** (no change) | Brief name kept | — |

### 2.4 Analytics (`analytics-event-schema.md` §10–11)

| Source + ID | Summary | Decision | Rationale | Affected files |
|---|---|---|---|---|
| AN CP-1 / DM-1 | Raw tables partitioned by `event_ts` derived from UUIDv7 `event_id`; PK `(event_id, event_ts)`; narrow typed heartbeat columns | **Accepted** | Makes per-event idempotency work across partitions. Replaces the architect's `occurred_at` partition key | brief §1 Analytics storage; schema §1.3, §12 |
| AN CP-2 / DM-11 | Add `video_watch_coverage`, `weekly_learning_aggregates`, `cohort_learning_aggregates`, `route_daily_aggregates`, `topic_mastery`, `question_item_stats`, `security_activity_feed_daily`, `analytics_dirty_days`, `analytics_ingest_rejections` | **Accepted-modified** | All accepted. `weekly_learning_aggregates` is a **table**, not a materialized view, because Postgres RLS does not apply to MVs | brief §4; schema §12 |
| AN CP-3 / DM-5 | `practice_responses` in placement, with attempt_no, served_at, hint/solution flags | **Accepted** | Same table as ARCH CCP-4; columns added | schema §8 |
| AN CP-4 | Exempt `POST /analytics/events` (and `/beacon`) from `Idempotency-Key` | **Accepted** | Idempotency is per event (`event_id`, `ON CONFLICT DO NOTHING`) | brief §5 |
| AN CP-5 | Beacon CSRF variant: body-borne signed token + `Sec-Fetch-Site: same-origin` | **Accepted** | `sendBeacon` cannot set headers; only for the beacon route | brief §5 |
| AN CP-6 | Ingest touches the session idle timer only for engaged samples (`input_recent` or `media_playing`); keepalives never extend it | **Accepted** | Prevents an idle tab defeating idle timeouts (Phase-8 scenario 15) | brief §1 Timeouts |
| AN CP-7 | `session.ended`, `account.restricted`, `consent.changed`, age-tier changes published as domain events | **Accepted** | Via `outbox_events` | brief §2 |
| AN CP-8 / DM-7 | Transactional outbox `outbox_events` | **Accepted** | Same as ARCH CCP-1 | schema §2.3 |
| AN CP-9 | Analytics day boundary = Asia/Kolkata; storage UTC | **Accepted** | Already used by security (IST day for overlaps) | brief §4 common rules |
| AN CP-10 / DM-9 | Consent purposes `analytics_learning`, `analytics_product`, `security_monitoring`; `users.privacy_tier` | **Accepted-modified** | Unified with the privacy doc's itemised consent screen (items A–G). Canonical purposes: `core_service` (A, includes basic learning-progress analytics — the analytics doc's "notice-only" L-purpose), `security_monitoring` (B), `analytics_personalisation` (C, replaces the name `analytics_learning`), `analytics_product` (product/route analytics; adults, opt-in; added to the consent screen as item H — follow-up), `college_data_sharing` (D), `device_fingerprint` (E), `marketing_email`/`marketing_sms` (F), `assessment_integrity` (G, per test), plus `terms`, `privacy_notice`. `privacy_tier` is a generated column on `users` | brief §1 Privacy; schema `consents`, `users` |
| AN CP-11 | `topic_mastery` owned by analytics; placement reads via service | **Accepted** | Resolves the three-way mastery overlap | schema §12 |
| AN CP-12 | Business rule: no completion, certificate or grade may depend on time thresholds alone | **Accepted** | Browser time is forgeable | brief §1 (new row); PRD BR list (follow-up) |
| AN DM-2 | `engagement_intervals` monthly by `started_at`, partial index on open intervals, `measurement_version` | **Accepted** | Retention 13 months (analytics) replaces the architect's 24 months | schema §1.3, §12 |
| AN DM-3 | `daily_learning_aggregates` grain user × IST date × (`entity_kind`, `entity_id`) + `measurement_version`, `is_frozen`, `privacy_tier` | **Accepted** | Replaces the architect's `dim_key` design | schema §12 |
| AN DM-4 | `lesson_topics` (lesson, topic, is_primary); `questions.primary_topic_id`; category = root of `topics`; `lessons.est_reading_minutes`; `lesson_assets` duration | **Accepted-modified** | `lesson_topics` replaces the `lessons.topic_ids uuid[]` array (one truth). Category = root `subject` node (no new enum). Duration column keeps the existing name `lesson_assets.duration_seconds` | schema §7 |
| AN DM-6 | `test_attempts` server `started_at`, `deadline_at`, `submitted_at`, `submit_reason`; section entry in `attempt_events` | **Accepted** (already satisfied) | Existing columns and `section_enter` event | — |
| AN DM-8 | `policy_settings` keys `analytics.tm.*`, `analytics.retention.*`, `analytics.k_min.*` | **Accepted** | Key namespaces only | schema §13 (comment) |
| AN DM-10 | RLS on all analytics tables with `organization_id`; D2C rows NULL | **Accepted** | Family `U` (user + tenant) | schema §12, §14 |
| AN DM-12 | Analytics `privacy_provider` registered in the retention registry | **Accepted** | `retention_policies` rows per analytics table | schema §13 |

### 2.5 Schema §15 pending items (from `database-schema.md`)

| Item | Resolution |
|---|---|
| `risk_evaluations.score/level/action` | Score 0–100 `numeric(5,2)`; levels 0–4; thresholds in `policy_settings` (`risk.threshold.*`); action vocabulary from security §9 |
| First-class ruleset table? | No separate table: ruleset rows in `risk_rule_versions` with `rule_id IS NULL` |
| `scoring_mode` | Replaced by `mode` (`off`/`shadow`/`enforce`). Minors: no sharing evaluations at all (CHECK on signals; service rule), so no `deterministic_only` mode is stored |
| Rule DSL / approval | `definition` JSONB (`params`, `points`, `caps`, `multipliers`, `thresholds`); approver ≠ proposer CHECK |
| Signal catalogue / minor rule | SH-01..12, SH-M1, TO-01..07, `cap.*`; CHECK `family <> 'sharing' OR NOT is_minor_at_time` |
| L4 lift trigger | `security_cases.is_high_risk` + unblock doc §5 rules → `unblock_requests.requires_second_approval`; DB CHECK `approved_by <> decided_by` |
| Case statuses / SLA | Security statuses; SLA from `unblock.sla.*` policy keys; columns `sla_first_response_due`, `sla_decision_due` |
| Evidence handling | Max 2 files ≤ 5 MB, PDF/PNG/JPG, AV-scanned, never Aadhaar/PAN; S3 keys in `attachments` JSONB; deleted 90 days after closure |
| `convert_to_paid_seat` | Dropped (see SEC-DM-14) |
| Geo granularity | Country + state only (`geo_country`, `geo_region`); no city; offline ASN/IP-type DB |
| Fingerprint columns | Added (`fp_hash`, `fp_epoch`), feature off by default, adults only, Phase 2 |
| Step-up windows | `auth_sessions.last_step_up_at`; windows in brief §1 (5 / 10 / 15 min) |
| Retention | Privacy doc is authoritative; classes in schema §1.4 updated |
| `privacy_requests` | Defined (owner `admin`, privacy sub-package) |
| Analytics envelope | Analytics stored envelope adopted (`event_type`, `event_ts`, `effective_at`, `skew_ms`, `privacy_tier`, `ingest_flags`, `payload`); xAPI columns dropped |
| Client time clamping | Replaced by `effective_at = min(occurred_at + skew_ms, received_at)`, late window 72 h |
| Heartbeat inputs | Analytics `page.heartbeat` columns adopted |
| Interval method version | `measurement_version` text (`tm-1.0`) |
| Org/batch pre-aggregates | Yes: `cohort_learning_aggregates`, `weekly_learning_aggregates` |
| Raw retention | `analytics_events` 90 days, `activity_heartbeats` 35 days (see §3.1) |
| Percentile tables | `attempt_results.percentile` stays; cohort distributions in `cohort_learning_aggregates`; item statistics in `question_item_stats` |

---

## 3. Conflict resolutions

| # | Conflict | Positions | Resolution | Why |
|---|---|---|---|---|
| 3.1 | **Analytics raw retention** | Analytics: events 120 d, heartbeats 35 d. Architect: both 90 d. Privacy doc D10 and `purge_raw_analytics`: raw 90 d | **`activity_heartbeats` 35 days; `analytics_events` 90 days**; `engagement_intervals` 13 months; identifiable aggregates 24 months | Heartbeats: analytics' value is the strictest and justified (72 h late window + 30-day recompute). Events: the privacy doc (authoritative for retention) caps raw analytics at 90 d and the analytics doc gives no functional need beyond 90 d (aggregates freeze at D+4; intervals keep 13 months for recompute). Legal Q4 ("traffic data") may still change these values |
| 3.2 | **Session timeouts for `security_reviewer`** | Brief, PRD, threat model, architecture: 15 min / 8 h. Research table omitted the role | **15 min / 8 h + mandatory MFA**, tier `privileged` = `finance_admin`, `security_reviewer`, `super_admin`. Tier = most privileged active grant at login; a grant change forces re-login. Lab devices: 30 min idle, no remember-device | No real disagreement; made explicit |
| 3.3 | **Step-up freshness window** | Role matrix ≤ 10 min; threat model ≤ 5 min privileged / ≤ 15 min student; architecture 5–15 min | **5 min** for privileged actions (refund, role grant, policy change, case decision, bulk export); **10 min** for other staff sensitive actions; **15 min** for student contact/MFA changes. Policy keys `auth.step_up_window.*` | Security domain values; role matrix to align |
| 3.4 | **Privileged MFA factor** | Brief: TOTP/passkey. Threat model §2 A10: passkeys mandatory for privileged | Brief kept (**passkey or TOTP; passkey preferred; SMS/email never for staff or privileged**); break-glass passkey only. Moving to passkey-only is PO-05 | Brief §1 was approved by the product owner; tightening it is their call |
| 3.5 | **`Escalated` unblock state** | Source list has 7 states; unblock doc adds `Escalated` | **8 states**: `draft`, `submitted`, `under_review`, `info_requested`, `escalated`, `approved`, `rejected`, `closed` (+ `closure_reason`). Student label "With senior reviewer" | Required for dual approval and the one second-level appeal; nothing removed. PO-01 confirms |
| 3.6 | **Attempt–session binding** | PRD: 1 session per attempt, OTP on every move. Security: bind to session, confirm to rebind, OTP at ≥ L2, max 2 rebinds, proctored = trainer override | **Security model**. Second session gets `409 attempt_bound_elsewhere`, read-only view, "Continue here?" | Crash recovery (scenario 16) without OTP friction for normal students; still blocks concurrent attempt sharing |
| 3.7 | **Minor flag, DOB, unverified age** | PRD: `is_minor` derived from DOB. Security/privacy: unverified age ⇒ minor. Architect: `is_minor DEFAULT false` | `user_profiles.date_of_birth`; `users.is_minor DEFAULT true`; `users.age_verified_at` + `age_verification_method` (`self_declared`, `roster`, `digilocker`, `guardian_attested`); CHECK `is_minor OR age_verified_at IS NOT NULL`; `privacy_tier` generated (`minor`/`adult`); birthday job flips `is_minor`; scoring starts only from adult consent date | Default-safe: a missing DOB can never produce adult processing |
| 3.8 | **Account status** | Security: `users.account_status` (active/restricted/suspended/deleted). Architect: lifecycle `status` | Keep lifecycle `status`; add cached `users.restriction_level` (0–4) maintained only by `security` from `account_restrictions` | One source of truth per concept |
| 3.9 | **Mastery table** | Architect `user_topic_mastery` (placement), analytics `topic_mastery` (analytics), PRD `mastery_scores` | **`topic_mastery`**, owner `analytics`, Elo-style columns from analytics §6.2 plus raw counts | One writer; mastery is derived data |
| 3.10 | **Security access to heartbeats** | Security §1.2/§12: read `activity_heartbeats` 5-min buckets. Analytics §6.5: security never queries raw analytics tables | Analytics service interface `get_engaged_buckets` (5-min, device/session/kind only) + `get_activity_summary` (daily feed). Both require adult + `security_monitoring` consent; raw window limited by heartbeat retention (35 d) | Keeps table ownership; signals keep their own evidence for 180 d |
| 3.11 | **Consent purposes** | Architect codes (`learning_analytics`, …), analytics codes (`analytics_learning` notice-only, `analytics_product`, `security_monitoring` opt-in), privacy items A–G (B required for adult paid plans) | Canonical code list in brief §1 Privacy (see AN CP-10). `security_monitoring` = item B: **required for adult paid plans; withdrawal ⇒ deterministic-only mode** (pending counsel Q3, PO-03). Personalisation (C) default **off** (PO-04) | Privacy doc owns consent design; analytics codes kept where they did not collide |
| 3.12 | **Small-cell (k) thresholds** | Analytics k ≥ 5 cohort, ≥ 20 cross-org; privacy k ≥ 10; role matrix k ≥ 50 cross-org for coordinators, ≥ 10 item analytics | `analytics.k_min.cohort` = **10**, `analytics.k_min.item` = **10**, `analytics.k_min.cross_org_display` = **50** (coordinator/student-facing benchmarks), `analytics.k_min.percentile_reference` = **20** (minimum reference cohort for computing a percentile) | Stricter privacy wins for disclosure; 20 kept as a statistical floor, not a disclosure rule |
| 3.13 | **Pseudonymous export key** | Analytics `pseudo_user`; privacy `subject_key` | **`subject_key = HMAC-SHA256(k_analytics_vN, user_id)`** | Privacy doc owns pseudonymisation |
| 3.14 | **Device identifier hashing** | Architect SHA-256 `device_token_hash`; security HMAC `device_key_hash` | **HMAC-SHA-256 `device_key_hash`** (32 bytes) | Security domain; keyed hash resists offline linking |
| 3.15 | **Idempotency for analytics ingest** | Brief §5: Idempotency-Key on POSTs creating attempt/submission records; analytics: per-event | Analytics ingest routes exempt; per-event `event_id` UUIDv7 + `ON CONFLICT DO NOTHING`; `uuid_time_mismatch` rejection keeps `event_ts` honest | AN CP-4 |
| 3.16 | **Outbox tables** | Architect `outbox_events` + `audit_outbox`; analytics asked for `outbox_events` | Both tables; `outbox_events` for domain events (analytics consumes `source=server` events from it), `audit_outbox` only for the audit sealer. Neither is used for the other's purpose | ARCH CCP-1/2, AN CP-8 |
| 3.17 | **New tables from all authors** | 46 new table names proposed across PRD, architecture, security, privacy and analytics (14 already in the v0.1 schema as architect CCP tables, several proposed by more than one author) | 26 new tables added to the schema; 1 renamed (`user_topic_mastery` → `topic_mastery`); 1 folded (`user_security_exceptions` → `policy_settings`); 1 merged (`mastery_scores` → `topic_mastery`); 3 reserved (placement drives, P2) | See §4 |
| 3.18 | **Hard-disable after failed logins** | PRD FR-IDN-009: 100; security policy: 50 (bounds 10–100) | **50** default, policy-bounded ≤ 100 (NIST ceiling) | Security owns the knob |
| 3.19 | **L4 login behaviour** | Role matrix §1: L4 → 403. Security: L4 may sign in to a `status_only` session | **`status_only` session** (case, appeal, privacy requests, billing view/cancel, support, logout) | Needed so suspended students can appeal (Section E). PO-07 (corrected from PO-06 in the wave-2 pass, §7) |
| 3.20 | **Geo granularity in UI** | PRD FR-SES-004 and role matrix M1/M2: "approximate city"; security §1.3: no city | **State/region only** everywhere (device list, support view, risk records) | City-level IP geo is unreliable in India and is excluded by the security design |
| 3.21 | **Entitlement vocabulary** | PRD: `free_enrolment`, `purchase`, `subscription`, `placement_package`, `coupon_grant`, `institution_contract`, `admin_grant`, `trial`; status incl. `grace`. Architect: `order_item`, `manual_grant`, `coupon_free`, no `grace` | PRD vocabulary adopted in `entitlements.source_type` with the architect's typed source FKs and CHECKs; status adds `grace` | Business vocabulary belongs to the PRD; physical modelling to the architect |

---

## 4. Table inventory delta

**Before:** `database-schema.md` defined **96** tables (82 brief + 14 architect CCP). **After:** **121** tables.

| Change | Tables |
|---|---|
| Added (26) | `org_trusted_networks`, `security_incidents` (security); `privacy_requests`, `retention_policies`, `erasure_ledger`, `approval_requests` (admin); `org_invitations`, `bulk_import_jobs` (orgs); `lesson_topics` (catalog); `mentor_slots`, `mentor_bookings`, `interview_feedback`, `resumes`, `resume_reviews` (placement); `entitlement_events` (entitlements); `video_watch_coverage`, `weekly_learning_aggregates`, `cohort_learning_aggregates`, `route_daily_aggregates`, `topic_mastery`, `question_item_stats`, `security_activity_feed_daily`, `analytics_dirty_days`, `analytics_ingest_rejections`, `export_jobs` (analytics); `support_ticket_messages` (support) |
| Renamed / merged (1 removed) | `user_topic_mastery` → `topic_mastery` (analytics) |
| Folded (no table) | `user_security_exceptions` → `policy_settings` (`scope_type='user'`); `mastery_scores` → `topic_mastery` |
| Reserved, no DDL (Deferred-to-owner) | `placement_drives`, `drive_eligibility_rules`, `drive_shortlists` |
| Rewritten in place (columns changed) | `users`, `consents`, `devices`, `user_devices`, `auth_sessions`, `login_attempts`, `playback_sessions`, all 9 security tables, `lessons`, `practice_responses`, `test_assignments`, `test_attempts`, `attempt_events`, `entitlements`, `analytics_events`, `activity_heartbeats`, `engagement_intervals`, `daily_learning_aggregates`, `audit_log`, `policy_settings`, `support_tickets` |

---

## 5. Needs product-owner decision

The documents (brief v0.2, schema) currently assume the default shown. The PRD's own OPD-01..OPD-13 (refund thresholds, plan lineup, minors via D2C, etc.) remain open in `product-requirements.md` §11 and are not repeated here, except where they interact with a contract.

| ID | Decision needed | Default assumed now | Raised by | Deadline |
|---|---|---|---|---|
| PO-01 | Add `Escalated` ("With senior reviewer") to the verbatim unblock status list | Included (8 states) | UNB CCP-U1 | Before API spec freeze |
| PO-02 | Publish in the Terms that **each browser profile counts as a device** and that registered college lab PCs do not count toward personal device caps | Yes | SEC CCP-S7 | Before Terms drafting |
| PO-03 | Consent item B (`security_monitoring`, account-sharing detection) **required for adult paid plans**; on withdrawal the account runs in deterministic-only mode (alternative: end the licence with a pro-rata refund) | Required; withdrawal ⇒ deterministic-only | Privacy §3.2, counsel Q3 | With counsel, before launch |
| PO-04 | Default of consent item C (personalised recommendations / readiness scores) | **Off**, asked at onboarding; basic progress always shown under A | Privacy §3.2 vs analytics/PRD readiness features | Before onboarding UX |
| PO-05 | Privileged roles: passkey-only (threat model) vs passkey **or** TOTP (approved brief) | Passkey or TOTP, passkey preferred; SMS/email never for staff | Threat model A10 | Before identity build |
| PO-06 | MFA mandatory for **all staff** tiers (coordinator, trainer, content, mentor, support), not only privileged | Yes (PRD personas, architecture and role matrix already assume it) | PRD PER-03, arch §6 | Before identity build |
| PO-07 | L4-suspended users can sign in to a status-only portal (appeal, billing, privacy) rather than being fully locked out | Yes | Security §6.1, §7.1 | Before API spec freeze |
| PO-08 | Assessment rebind policy: max 2 rebinds per attempt, OTP only at ≥ L2, proctored drives need trainer override | As stated | PRD CCP-01 vs SEC CCP-S3 | Before assessment build |
| PO-09 | Unblock SLAs: L3 first response 24 h / decision 72 h; L4 48 h / 120 h; 30-day hard ceiling; 7-day coverage | As stated | Unblock §4.3 | Before support staffing plan |
| PO-10 | False-positive compensation: extend the subscription by the number of restricted days (`unblock.false_positive_extension`) | On | Security §3.2 | Before commerce build |
| PO-11 | Placement drives (PRD CCP-03 / OPD-12) in P1 or P2 | P2; table names reserved | PRD | Roadmap |
| PO-12 | Mentoring and résumé review (PRD CCP-02/06) in P1 with external meeting links (OPD-08) | P1, external links | PRD | Roadmap |
| PO-13 | Analytics raw retention: events 90 d / heartbeats 35 d (shorter than the analytics author's 120 d) | 90 d / 35 d | §3.1 | With counsel Q4 |

---

## 6. Required follow-up edits (not applied; wave 2 or a later pass)

Each row is a small inconsistency between a wave-1 document and brief v0.2 / the schema. Owners apply them; until then brief v0.2 and the schema win.

### 6.1 `docs/product-requirements.md` (Product Analyst)

| # | Section | Change |
|---|---|---|
| F-PRD-1 | FR-SES-011 | Replace "Move test here (requires OTP, logs `attempt_events.device_switch`)" with the binding rules: confirm to rebind, OTP only at ≥ L2, max 2 rebinds, proctored drives need trainer override; event `attempt_events.rebind` |
| F-PRD-2 | FR-IDN-009 | "hard disable at 100 consecutive failures" → "hard disable at `login.hard_disable_after_failures` (default 50, max 100)" |
| F-PRD-3 | FR-SES-004 | "approximate city" → "approximate state" |
| F-PRD-4 | "Entitlement row (product view)" | `revocation_reason` → `revoke_reason`; quotas named `mentor_sessions_remaining`, `mocks_remaining`, `resume_reviews_remaining`; note `entitlement_events` history table |
| F-PRD-5 | §12 CCP-10 | `mastery_scores` → `topic_mastery` (analytics-owned) |
| F-PRD-6 | Business rules (new BR) | Add AN CP-12: no completion, certificate or grade depends on time thresholds alone |
| F-PRD-7 | BR-MIN-01 | "no `risk_evaluations`" → "no sharing-family signals or evaluations; takeover handled by deterministic rules only (no score)" |
| F-PRD-8 | §12 table | Mark CCP-01..13 with the decisions in this document; CCP-03 deferred (OPD-12) |
| F-PRD-9 | PUB-021 / STU unblock screens | Use the 8 unblock states including `Escalated` ("With senior reviewer") |

### 6.2 `docs/role-permission-matrix.md` (Product Analyst)

| # | Section | Change |
|---|---|---|
| F-RPM-1 | §1 principle 4 | "L4 → 403" → "L4 → `status_only` session limited to `account_status` routes; L3 → `restricted` scope" (security §7.2) |
| F-RPM-2 | §2 and §5 step-up definition | "≤ 10 min" → 5 min for privileged actions, 10 min for other staff sensitive actions, 15 min for student contact/MFA changes (brief §1) |
| F-RPM-3 | §8 tiers M1, M2 | "approximate city" → "approximate state"; M3 "device token hashes" → "device key hashes (HMAC)" |
| F-RPM-4 | TI-03, SoD-09 | Reference the `analytics.k_min.*` keys (cross-org display 50, item 10, cohort 10) |
| F-RPM-5 | §2.7 | Add permissions for `export_jobs` (`report.export.request`, `report.export.approve`) and `approval.decide` per action type; `privacy.request.*` acts on `privacy_requests`. **Applied in the wave-2 pass (§7, W2-REC-01):** request = security_reviewer @P, finance_admin @P, college_coordinator @O, trainer @B; approve = super_admin, approver ≠ requester |

### 6.3 `docs/system-architecture.md` (System Architect)

| # | Section | Change |
|---|---|---|
| F-ARCH-1 | §4.2 module table | Placement: drop `user_topic_mastery`, add `mentor_slots`, `mentor_bookings`, `interview_feedback`, `resumes`, `resume_reviews`. Analytics: add the AN CP-2 tables, `topic_mastery`, `export_jobs`. Security: add `org_trusted_networks`, `security_incidents`. Orgs: `org_invitations`, `bulk_import_jobs`. Admin: `approval_requests`, `privacy_requests`, `retention_policies`, `erasure_ledger`. Support: `support_ticket_messages`. Entitlements: `entitlement_events`. Catalog: `lesson_topics` |
| F-ARCH-2 | §~line 782 (analytics storage) | Raw retention "default 90 days" → events 90 d, heartbeats 35 d; partition key `event_ts` (AN CP-1) |
| F-ARCH-3 | §6 sessions table (Timeouts / MFA) | `mfa_at` → `last_step_up_at`; lab devices 30 min idle; step-up windows 5/10/15 min; idle timer extended only by engaged activity (AN CP-6) |
| F-ARCH-4 | §23 | Mark CCP-1..13 with decisions from this document |
| F-ARCH-5 | Events table in §4.2 | Add `session.ended`, `account.restricted`, `consent.changed`, `age_tier.changed` (AN CP-7) |
| F-ARCH-6 | ADR-0004 | Record 90 d / 35 d raw retention and the `event_ts` partition key |

### 6.4 `docs/account-security-and-risk-engine.md` (Security Specialist)

| # | Section | Change |
|---|---|---|
| F-SEC-1 | §1.2 | `role_tier` → `session_tier`; `revoked_at/revoked_reason/revoked_by` → `ended_at/end_reason/ended_by`; add `scope`, `status` incl. `blocked` |
| F-SEC-2 | §1.2 "Engagement heartbeats" and §10 H3 | Replace direct reads of `activity_heartbeats` with `analytics.feeds.get_engaged_buckets(...)` (adult + `security_monitoring` consent) |
| F-SEC-3 | §12 | Mark `users.account_status` as replaced by `users.restriction_level`; `devices.shared_scope` → `shared_organization_id`; `user_security_exceptions` folded into `policy_settings` (scope `user`) |
| F-SEC-4 | §8 reason codes | Note they are stored in `auth_sessions.end_reason` together with `idle_timeout`/`absolute_timeout` |

### 6.5 `docs/account-unblock-workflow.md` (Security Specialist)

| # | Section | Change |
|---|---|---|
| F-UNB-1 | §10 CCP-U1 | Remove "the master list already includes it" (the source list does not); reference PO-01 |
| F-UNB-2 | §4.1 | Add machine codes for states (`draft` … `closed`) and `closure_reason` values (`completed`, `rejected_final`, `withdrawn`, `no_response`, `moot`) |

### 6.6 `docs/privacy-and-data-retention.md` (Security Specialist)

| # | Section | Change |
|---|---|---|
| F-PRIV-1 | §3.2 consent screen | Add item H "Product analytics (`analytics_product`)", adults only, off by default; map items A–H to the canonical purpose codes in brief §1 |
| F-PRIV-2 | §2 D10 and §7 `purge_raw_analytics` | Heartbeats 35 days; events 90 days; `engagement_intervals` 13 months |
| F-PRIV-3 | §2 D1 | "Life of account + 30 days grace" vs schema R-ACCT "+ 90 days": confirm one value (schema assumes privacy doc: **30 days**; schema §1.4 updated) |
| F-PRIV-4 | §8 | k-floor: keep 10 for cohort cells; add item 10, cross-org display 50 (`analytics.k_min.*`) |

### 6.7 `docs/security-threat-model.md` (Security Specialist)

| # | Section | Change |
|---|---|---|
| F-THR-1 | §2 admin takeover row and §5 A10 | "Passkeys mandatory for privileged tiers" → "passkey preferred, TOTP allowed; SMS/email never" until PO-05 is decided |
| F-THR-2 | §4 controls table, step-up row | Add the 10 min staff tier (brief §1) |

### 6.8 `docs/analytics-event-schema.md` (Analytics Engineer)

| # | Section | Change |
|---|---|---|
| F-AN-1 | §4.4 | `analytics_events` 120 days → 90 days |
| F-AN-2 | §4.5 | `pseudo_user` → `subject_key`; k-floor 5 → `analytics.k_min.cohort` = 10; cross-org display 50 |
| F-AN-3 | §6.3, §7.2 video drop-off | k ≥ 5 → `analytics.k_min.cohort` (10); percentile reference minimum 20 unchanged |
| F-AN-4 | §6.5 | Add the second interface `get_engaged_buckets` used by SH-01/SH-02 and dashboard H3 |
| F-AN-5 | §10 DM-9 / §11 CP-10 | Purpose codes: `analytics_learning` → `core_service` (basic progress) and `analytics_personalisation` (item C) |
| F-AN-6 | §4.2 `weekly_learning_aggregates` | "may be a materialized view" → table (RLS) |

**Follow-up edit count: 38** (PRD 9, role matrix 5, architecture 6, security engine 4, unblock 2, privacy 4, threat model 2, analytics 6).

---

## 7. Wave-2 consistency pass (2026-11-03, Integration Lead)

**Inputs:** `api-specification.md` §27 (I-01..I-25), `testing-and-acceptance-criteria.md` §13 (I-01..I-12), `deployment-and-operations.md` §20 (I-01..I-16), `implementation-roadmap.md` §12 (I-1..I-11), and this document's open items (F-RPM-5, the §3.19 citation). Security-design questions (kill-switch approval, bulk lift, HMAC key versioning, log retention 395/365 days, the AMB list, hard-disable messaging) are being settled in a separate security pass and are marked **Security**.

**Outputs:** `blueprint-brief.md` **v0.3**; `database-schema.md` and `database-erd.md` v0.3 (still 121 tables); `role-permission-matrix.md` v0.2; `product-requirements.md` v0.2; `system-architecture.md` v0.3; ADR-0006, ADR-0009, ADR-0010 and ADR-0011 amended; new **ADR-0014** (error tracking). Files outside this pass's edit set get mechanical change requests in **`docs/integration-pass-requests.md`** (62 requests, ids `IPR-*`).

**Decision rule added:** (6) A wave-2 issue is settled in the brief and the schema first. Wave-1 documents in the edit set are corrected in place. Frozen documents get an `IPR-*` request, and until it is applied the brief and the schema win.

### 7.1 Canonical decisions

| ID | Decision | Applied in |
|---|---|---|
| W2-D01 | **Permission-key format.** The role matrix is the only source of keys. The schema CHECK is relaxed to accept 2–3 lowercase segments, `^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*){1,2}$`, so the existing keys `security.restriction.apply_l1l2` and `test.assign` stay valid. `permissions.module` holds the owning module. Renames: `report.export` → `report.export.request`; `security.policy.write` → `policy.edit` + `policy.propose`; `assessments.test.publish` → `test.results.release`; `coding.testcase.read_hidden` → `coding_test_case.hidden.read`; for incidents and trusted networks, `security.case.*` → `security.incident.read` / `security.incident.manage` / `security.network.verify`; `analytics.event.ingest` → none (ownership). Machine-readable copy: `apps/api/app/core/authz/permissions.yaml` | schema §6; role matrix §1, §10; brief §3; arch §6.4, §9 |
| W2-D02 | **New keys:** `policy.propose`, `security.incident.read`, `security.incident.manage`, `security.network.verify`, `report.export.request`, `report.export.approve` (role × scope rows in the role matrix §3) | role matrix §2, §3, §5 |
| W2-D03 | Stream-cap error **`409 playback_conflict`**. Paths `POST /api/v1/media/playback-tokens` and `/media/playback-sessions/{id}/heartbeat` | brief §1, §5; arch §12, §21 |
| W2-D04 | Attempt binding uses the brief/schema model (`bound_session_id`, `rebind_*` events). `session_takeover` and `device_switch` are retired | brief §1; arch §6.2, §8.5; PRD journey |
| W2-D05 | Route tag `account_status` (+ `l3_readonly`, `login_continuation`, `mfa_enrolment`, `consent`), declarable in any module. `restriction_class` is retired | brief §5; arch §6.3 |
| W2-D06 | `auth_sessions.status` adds **`pending_session_choice`** | schema §4; ERD; brief §1; arch §6.2 |
| W2-D07 | `401 step_up_required` (freshness, `last_step_up_at`) and `403 mfa_enrolment_required` (no factor) | brief §5; arch §6.3 |
| W2-D08 | Subscription grace **5 days** (PRD default; the architecture's 3 days was not justified beyond the 24–36 h AutoPay delay, which 5 days also covers). Policy key `commerce.subscription_grace_days` (default 5, bounds 3–7) | brief §1; schema §13 comment; arch §11.3; ADR-0006; PRD BR-ENT-09 |
| W2-D09 | `products.product_kind` uses the PRD vocabulary (`free_resource`, `free_course`, `course`, `bundle`, `subscription_plan`, `placement_package`, `mock_pack`, `institution_seat`) + reserved `extra_learner_seat`. Mapping: all_access→subscription_plan, test_series→mock_pack, company_pack→placement_package (or bundle), mentor_pack→placement_package, cohort→course (`course_kind='cohort'`), seat_licence→institution_seat. This follows the §3.21 rule (business vocabulary from the PRD, physical model from the architect) | schema §11; ERD; PRD FR-COM-001; arch §11.1 |
| W2-D10 | Order statuses follow the schema: `created`, `pending_payment`, `paid`, `failed`, `expired`, `cancelled`, `refunded`, `partially_refunded` | PRD FR-COM-004; arch §11.1 |
| W2-D11 | Webhook staleness: no age-based rejection for Razorpay; payloads from timestamp-signed providers (Cashfree) older than 5 min are not trusted; stale or out-of-order events are applied only from a server-side re-fetch | ADR-0006; PRD FR-COM-003; arch §11.2 |
| W2-D12 | **Section H report ids H1–H12** follow the verbatim order of `source-requirements-excerpt.md` (report keys per API SEC-30) | brief §7; PRD §8.5 |
| W2-D13 | Analytics batch max **100** events per request (the Analytics Engineer owns ingest) | brief §5; PRD FR-ANL-001 |
| W2-D14 | Autosave 5 s debounce, max **10 s** (PRD value; research recommends 5–10 s; capacity bound 200 writes/s at 2,000 takers) | brief §1; arch §1, §8.5, §19; PRD FR-ASM-005 |
| W2-D15 | Coding limits: Run 10/min, Submit 5/min per user per problem, 1 in-flight submit; `coding.*` policy keys | arch §9; PRD FR-COD-005; schema §13 comment |
| W2-D16 | Device cookie: 128-bit, keyed HMAC `device_key_hash` | arch §6.1 |
| W2-D17 | No unauthenticated unblock endpoint; L4 users appeal via a `status_only` session (PO-07) | PRD FR-SEC-004, PUB-021 |
| W2-D18 | Refunds: `approval_request_id` + CHECK `ck_refund_goodwill_dual`; the > ₹25,000 Dual rule is a service rule (`commerce.refund.dual_approval_above_paise`) | schema §11, §13; ERD |
| W2-D19 | Coordinator M0 visibility follows the org policy `org.notify_coordinator_on_restriction` (default `L4_status_only`) | role matrix §8 |
| W2-D20 | Webhook path **`/api/v1/webhooks/{provider}`** (brief §5 base path), with a CloudFront/ALB rule straight to `api-webhooks` that bypasses the BFF | brief §1, §5; arch §3, §11.2; ADR-0006, ADR-0010 |
| W2-D21 | **CSRF key ownership:** the BFF (`web`) issues and validates `td_csrf`; `TD_CSRF_KEY` lives only in `web` (one choke point, ADR-0010) | brief §1; arch §6.1; ADR-0010 |
| W2-D22 | **Error tracking data residency:** self-hosted GlitchTip (Sentry-SDK compatible) in ap-south-1; no Sentry SaaS; scrubbed events; 90-day retention | **ADR-0014**; brief §1; arch §3, §21 |
| W2-D23 | **12-stage order** is canonical in `implementation-roadmap.md` §2 (list in §7.4) | brief §7 |
| W2-D24 | Migrations path **`apps/api/migrations`** everywhere (ADR-0009) | brief §1; arch §6.5 |
| W2-D25 | **Partition-drop DDL:** new login role **`td_maintenance`** that may only `EXECUTE` the `td_owner`-owned `SECURITY DEFINER` functions `maint.run_partition_maintenance()` and `maint.drop_expired_partitions(parent)`, which are bounded by `retention_policies` | schema §1.2; ADR-0009, ADR-0011; arch §6.5, §14, §21 |
| W2-D26 | Audit sealer runs as the dedicated 1-task ECS service `audit-sealer` (`td_audit_sealer`) | brief §1; schema §1.2; arch §3; ADR-0011 |
| W2-D27 | `td-audit-anchor` Object Lock compliance retention of 8 years = R-AUDIT (anchors hold hashes only) | ADR-0011 |
| W2-D28 | Partition premake at 01:00 IST; purges and drops at the privacy §7 times | arch §14 |
| W2-D29 | `users.is_synthetic` and `organizations.is_synthetic` (default false), excluded from analytics, risk, invoices and k-counts. In production only the synthetic-monitoring job may set them | schema §3, §6; ERD |
| W2-D30 | Feature flag `platform.maintenance_mode`: writes return `503 maintenance`, GETs and health stay up, webhooks return 503 | brief §5; arch §5.1; schema `feature_flags` comment |
| W2-D31 | Exports: request = security_reviewer @P, finance_admin @P, college_coordinator @own org, trainer @own batch. Approve = super_admin, approver ≠ requester (security per-user exports; any personal-data export > 10,000 rows) | role matrix §2.7, §3, §5; brief §3 |

### 7.2 Issue log

Status values: **Resolved** (decided and applied here, or decided with an `IPR-*` request for a frozen file), **Security** (left to the Security Specialist's concurrent pass), **No change** (confirmed as is).

#### `api-specification.md` §27 (25)

| Issue | Topic | Status | Resolution |
|---|---|---|---|
| API I-01 | Permission-key format | Resolved | W2-D01 (CHECK relaxed; renamed keys listed in role matrix §10) |
| API I-02 | Policy-setting permission | Resolved | W2-D02 `policy.propose`; `security.policy.write` → `policy.edit`; IPR-API-08, IPR-SEC-01 |
| API I-03 | Missing keys (incidents, networks, export approval, ingest) | Resolved | W2-D01/D02/D31; IPR-API-01..07, IPR-API-09, IPR-AN-01 |
| API I-04 | Stream-cap code | Resolved | W2-D03 `playback_conflict`; arch §12 |
| API I-05 | Playback paths | Resolved | W2-D03; arch §12; IPR-SEC-06 |
| API I-06 | Assessment binding / `session_takeover` | Resolved | W2-D04; arch §6.2, §8.5 |
| API I-07 | Route tag naming | Resolved | W2-D05; arch §6.3 |
| API I-08 | Pending status for session-cap choice | Resolved | W2-D06; schema §4; IPR-API-10 |
| API I-09 | Step-up window (F-RPM-2, F-ARCH-3) | Resolved | Role matrix already at 5/10/15; arch §6.1 `last_step_up_at` |
| API I-10 | Step-up response status | Resolved | W2-D07; brief §5 |
| API I-11 | Subscription grace 5 vs 3 days | Resolved | W2-D08 (5 days) |
| API I-12 | Product types | Resolved | W2-D09; IPR-API-12 |
| API I-13 | Order statuses | Resolved | W2-D10; PRD FR-COM-004 |
| API I-14 | Webhook staleness | Resolved | W2-D11; ADR-0006; IPR-API-20, IPR-ENV-03 |
| API I-15 | Section H numbering | Resolved | W2-D12; PRD §8.5; IPR-SEC-02, IPR-SRC-02 |
| API I-16 | Analytics batch size | Resolved | W2-D13; PRD FR-ANL-001 |
| API I-17 | Autosave interval | Resolved | W2-D14 (10 s); IPR-API-11, IPR-QA-04, IPR-ROAD-02 |
| API I-18 | Coding rate limits | Resolved | W2-D15; arch §9 |
| API I-19 | Device cookie in architecture | Resolved | W2-D16; arch §6.1 |
| API I-20 | Unblock entry without a session | Resolved | W2-D17; PRD FR-SEC-004, PUB-021 |
| API I-21 | Hard-disable message | Security | Security-design ambiguity; the API's interim assumption stands |
| API I-22 | Refund approver CHECK | Resolved | W2-D18; IPR-API-14 |
| API I-23 | Coordinator restriction visibility | Resolved | W2-D19; role matrix §8 |
| API I-24 | Webhook path | Resolved | W2-D20 (`/api/v1/webhooks/*`); arch §11.2; IPR-DEP-01 |
| API I-25 | `devices.shared_scope` | Security | Existing F-SEC-3; IPR-SEC-03 |

#### `testing-and-acceptance-criteria.md` §13 (12)

| Issue | Topic | Status | Resolution |
|---|---|---|---|
| QA I-01 | 12-stage order not defined | Resolved | W2-D23; list in §7.4; IPR-QA-01 (re-key §6), IPR-SRC-01 |
| QA I-02 | RE §11 scenario numbering | Security | — |
| QA I-03 | AMB-01..21 | Security | AMB-03/14 also go to the product owner |
| QA I-04 | Machine-readable permission matrix | Resolved | `apps/api/app/core/authz/permissions.yaml` (role matrix §10); IPR-QA-02, IPR-ROAD-05 |
| QA I-05 | `abuse`/`integrity` rule-key registry | Security | — |
| QA I-06 | Synthetic-data marker | Resolved | W2-D29; IPR-QA-03 |
| QA I-07 | API spec missing; route names differ | Resolved | API spec exists; arch aligned to its routes (autosave `POST /attempts/{id}/autosave`, `account_status`) |
| QA I-08 | PRIV heartbeat retention | Security | Existing F-PRIV-2 |
| QA I-09 | `attempt_events` lacks `session_takeover`/`device_switch` | Resolved | W2-D04 (schema values canonical) |
| QA I-10 | Test infrastructure accounts/budget | Resolved | IPR-ROAD-06 (external dependencies) |
| QA I-11 | AC-SES-02 vs `evict_oldest` (AMB-08) | Security | — |
| QA I-12 | RPM step-up and L4 rules | Resolved | Already applied in the role matrix (F-RPM-1/2); verified |

#### `deployment-and-operations.md` §20 (16)

| Issue | Topic | Status | Resolution |
|---|---|---|---|
| DEP I-01 | Kill-switch approval | Security | — |
| DEP I-02 | Bulk lift | Security | — |
| DEP I-03 | Where the audit sealer runs | Resolved | W2-D26; IPR-DEP-04 |
| DEP I-04 | HMAC key versioning | Security | — |
| DEP I-05 | Object Lock retention | Resolved | W2-D27 (8 years confirmed) |
| DEP I-06 | Sentry data residency | Resolved | W2-D22 / **ADR-0014**; IPR-DEP-03, IPR-ENV-04, IPR-SEC-05 |
| DEP I-07 | Backup retention vs erasure | Resolved | Accepted: personal-data backups ≤ 35 days in v1; IPR-DEP-07 |
| DEP I-08 | WAF sync of trusted networks | Resolved | Accepted (owner `security`, verified networks only; Security may veto); IPR-DEP-08 |
| DEP I-09 | Pilot DR level | Resolved | Daily cross-region copy from pilot day 1 (cost flagged to PO); IPR-DEP-06 |
| DEP I-10 | Partition drops need DDL | Resolved | W2-D25 `td_maintenance`; IPR-DEP-05, IPR-ENV-02 |
| DEP I-11 | Job schedule mismatch | Resolved | W2-D28; arch §14 |
| DEP I-12 | Log retention 395/365 | Security | — |
| DEP I-13 | Webhook path | Resolved | W2-D20; the API spec's `/api/v1/webhooks/*` is canonical, so the DevOps proposal to serve webhooks outside `/api/v1` is rejected; IPR-DEP-01, IPR-SEC-04 |
| DEP I-14 | CSRF key sharing | Resolved | W2-D21 (BFF only); ADR-0010; IPR-DEP-02, IPR-ENV-01, IPR-API-15 |
| DEP I-15 | Synthetic monitoring accounts | Resolved | W2-D29; IPR-DEP-09 |
| DEP I-16 | Maintenance-mode flag | Resolved | W2-D30; IPR-API-16, IPR-DEP-10 |

#### `implementation-roadmap.md` §12 (11)

| Issue | Topic | Status | Resolution |
|---|---|---|---|
| ROAD I-1 | Migrations directory | Resolved | W2-D24; IPR-ROAD-01 (`migrations/**` shorthand rows) |
| ROAD I-2 | Wave-2 docs missing | Resolved | They exist; IPR-ROAD-04 |
| ROAD I-3 | 38 follow-up edits | Resolved (partly) | PRD 9/9, role matrix 5/5 and architecture 6/6 verified applied (§7.3). Security (12) and analytics (6) follow-ups stay with their owners |
| ROAD I-4 | PO-06 vs PO-07 in §3.19 | Resolved | §3.19 corrected to PO-07 |
| ROAD I-5 | Arch §4.2 table out of date | Resolved | F-ARCH-1 verified in arch v0.3; the ownership manifest is still generated from the schema |
| ROAD I-6 | Brief §6 rows for UX and code paths | Resolved | Brief v0.3 §6 (UX row; code paths → roadmap §3.2) |
| ROAD I-7 | FR-SEC-002 mixes P0/P1; F-PRD-1 | Resolved | PRD split into FR-SEC-002a (P0) / FR-SEC-002b (P1); IPR-API-18, IPR-ROAD-03 |
| ROAD I-8 | `reports/` duplicate | Resolved | `research/` canonical; IPR-README-01 |
| ROAD I-9 | Certificates MVP vs P1 | No change | PRD FR-LRN-006 P1 and the feature comparison already agree; RD-03 stands |
| ROAD I-10 | Durations not validated | No change | Re-baseline at the Stage 3 exit, as the roadmap proposes |
| ROAD I-11 | Agent roles and lane splits | No change | PO confirms at RD-02 |

#### This document (2)

| Item | Status | Resolution |
|---|---|---|
| W2-REC-01 F-RPM-5 (skipped in wave 1) | Resolved | Role × permission rows added: `report.export.request` (security_reviewer @P, finance_admin @P, college_coordinator @O, trainer @B); `report.export.approve` (super_admin; approver ≠ requester). `report.export` retired (W2-D31) |
| W2-REC-02 §3.19 cited PO-06 | Resolved | Corrected to PO-07 |

### 7.3 Status of §6 follow-up edits

| Group | Status after this pass |
|---|---|
| F-PRD-1..9 | Applied (verified in PRD v0.2) |
| F-RPM-1..5 | Applied (F-RPM-5 in this pass; 1–4 verified) |
| F-ARCH-1..6 | Applied (verified in arch v0.3 and ADR-0004) |
| F-SEC-1..4, F-UNB-1..2, F-PRIV-1..4, F-THR-1..2 | Open: Security Specialist (concurrent pass) |
| F-AN-1..6 | Open: Analytics Engineer (+ IPR-AN-01/02) |

### 7.4 Canonical 12-stage order (from `implementation-roadmap.md` §2)

| # | Stage | Weeks (planned) |
|---|---|---|
| 1 | Discovery | done 2026-11-03 |
| 2 | Product design | W1–W3 |
| 3 | Technical foundation | W2–W5 |
| 4 | Identity & permissions | W6–W11 |
| 5 | Core LMS | W12–W17 (Stream A) |
| 6 | Placement prep (incl. timed MCQ assessments) | W18–W23 (Stream A) |
| 7 | Account security & monitoring | W12–W16 (Stream B) |
| 8 | Commerce & college management | W17–W23 (Stream B) |
| 9 | Coding assessments | W24–W28 |
| 10 | Integration & hardening | W29–W32 |
| 11 | Pilot | W33–W40 |
| 12 | Production | W41–W46 |

`source-requirements-excerpt.md` should cite this list (IPR-SRC-01), and the testing doc §6 should be re-keyed to it (IPR-QA-01).

### 7.5 Counts

| Source | Issues | Resolved | No change | Security |
|---|---|---|---|---|
| API spec §27 | 25 | 23 | 0 | 2 |
| Testing §13 | 12 | 7 | 0 | 5 |
| Deployment §20 | 16 | 12 | 0 | 4 |
| Roadmap §12 | 11 | 8 | 3 | 0 |
| Reconciliation (F-RPM-5, §3.19) | 2 | 2 | 0 | 0 |
| **Total** | **66** | **52** | **3** | **11** |

Canonical decisions: 31 (W2-D01..D31). New ADR: 1 (ADR-0014). Requests for frozen files: **62** in `docs/integration-pass-requests.md`. Schema: 0 tables added (121), 1 DB role added (`td_maintenance`), 3 columns added (`users.is_synthetic`, `organizations.is_synthetic`, `refunds.approval_request_id`), 3 CHECKs changed (`auth_sessions.status`, `permissions.permission_key`, `products.product_kind`), 1 CHECK and 1 FK added (`ck_refund_goodwill_dual`, `fk_refund_approval`).

---

## 8. Summary counts (wave 1)

| Decision | Count |
|---|---|
| Accepted | 61 |
| Accepted-modified | 14 |
| Rejected | 0 as whole proposals; three sub-items rejected inside modified decisions (`users.account_status` enum, `case_decisions.convert_to_paid_seat`, OTP on every attempt move) |
| Deferred-to-owner | 1 (PRD CCP-03); plus the customer-facing wording of SEC CCP-S7 (PO-02) |
| **Total register rows** | **76** (PRD 13, architecture 13, security CCP-S 7 + SEC-DM 19, unblock 3, privacy 1, threat model 1, analytics 19 rows covering CP-1..12 and DM-1..12, where a DM that restates a CP shares its row) |

Schema §15 pending items: 21, all resolved (§2.5). Product-owner decisions: 13 (§5). Follow-up edits: 38 (§6). Wave-2 consistency pass: 66 issues logged, 52 resolved, 3 no change, 11 routed to Security (§7.5); 62 requests in `docs/integration-pass-requests.md`.

---

## 9. Request application log (security review pass, 2026-11-03, Integration Lead)

Applies `docs/consistency-pass-requests.md` (Security Specialist, 107 requests, ids `CPR-*`) and `docs/integration-pass-requests.md` (62 requests, ids `IPR-*`). This pass edited only `blueprint-brief.md` (→ **v0.4**), `database-schema.md` / `database-erd.md` (→ v0.4), `role-permission-matrix.md` (→ v0.3), `product-requirements.md` (→ v0.3), `system-architecture.md` (→ v0.4), `analytics-event-schema.md` (→ v0.4), `feature-comparison.md` (no requests) and `architecture-decisions/ADR-0002`, `ADR-0006`, `ADR-0013`. Files owned by other agents in this pass (API spec, testing, deployment, roadmap, README, `.env.example`) and files outside the edit set (security documents, source excerpt) were not touched; their requests are **Skipped (out of scope — owner applies)** and remain open for those owners.

### 9.1 Conflict resolutions

| # | Conflict | Resolution |
|---|---|---|
| C-1 | Webhook staleness: CPR-BRF-06 / CPR-ARC-06 / CPR-SCH-13 (TM §2.4: no age-based rejection for any provider; re-fetch every state-changing event) vs brief v0.3, ADR-0006 v0.3 and IPR-API-20 / IPR-ENV-03 ("Cashfree payloads older than `WEBHOOK_TOLERANCE_SECONDS` are not trusted") | Security domain → **Security Specialist wins**. Brief v0.4 §1, architecture §11.2 and ADR-0006 v0.4 now say: no event rejected for age; every state-changing event applied from a provider re-fetch; `is_stale` is monitoring only. The Backend Lead (IPR-API-20) and DevOps (IPR-ENV-03, CPR-DEP-11) should word their text to the v0.4 rule. |
| C-2 | CPR-BRF-12 asks for a "v0.3 changelog entry"; v0.3 was already used by the wave-2 pass | Entry written as **v0.4**; brief bumped to v0.4 (marker ✦). |
| C-3 | `analytics-event-schema.md` §5.5 rule 4 said plausibility violations are an adult "risk input"; CPR-ANL-02 says IN-01/IN-02 are not inputs to any sharing score | Security wins; §2.7 and §5.5 rewritten. |
| C-4 | CPR-RPM-01 / CPR-RPM-07 ask to add keys (`policy.propose`, `security.incident.manage`, `security.network.verify`) that already exist since role matrix v0.2 | No conflict: keys kept; `policy.propose` description gains the namespace list (incl. `assessment.*`); RPM-07 confirmed. |
| C-5 | CPR-SCH-03 asks to add `pending_session_choice` to `auth_sessions.status` | Already present since schema v0.3; other CPR-SCH-03 items applied. |

Additional consistency edits made while applying (no request id): ADR-0013 autosave ceiling 15 s → 10 s (brief v0.3, API I-17) plus attempt binding/re-attach/idle hold; ADR-0002 session rules aligned with brief v0.4; PRD FR-SES-006 aligned with AC-SES-02; role matrix §3 row now lists `question.retire` (catalogue key that had no matrix cell; found by the check in §9.4).

### 9.2 `consistency-pass-requests.md` (107)

| Request | Result |
|---|---|
| CPR-BRF-01 | Applied |
| CPR-BRF-02 | Applied |
| CPR-BRF-03 | Applied |
| CPR-BRF-04 | Applied |
| CPR-BRF-05 | Applied |
| CPR-BRF-06 | Applied (C-1) |
| CPR-BRF-07 | Applied |
| CPR-BRF-08 | Applied |
| CPR-BRF-09 | Applied |
| CPR-BRF-10 | Applied |
| CPR-BRF-11 | Applied |
| CPR-BRF-12 | Applied (as the v0.4 changelog entry; C-2) |
| CPR-SCH-01 | Applied |
| CPR-SCH-02 | Applied |
| CPR-SCH-03 | Applied (`pending_session_choice` already present; C-5) |
| CPR-SCH-04 | Applied |
| CPR-SCH-05 | Applied |
| CPR-SCH-06 | Applied |
| CPR-SCH-07 | Applied |
| CPR-SCH-08 | Applied |
| CPR-SCH-09 | Applied |
| CPR-SCH-10 | Applied |
| CPR-SCH-11 | Applied |
| CPR-SCH-12 | Applied |
| CPR-SCH-13 | Applied (C-1) |
| CPR-SCH-14 | Applied |
| CPR-SCH-15 | Applied (schema §16.1) |
| CPR-ERD-01 | Applied |
| CPR-ERD-02 | Applied |
| CPR-ERD-03 | Applied |
| CPR-ERD-04 | Applied |
| CPR-API-01 | Skipped — out of scope (`api-specification.md`, Backend Lead, concurrently edited) |
| CPR-API-02 | Skipped — out of scope (`api-specification.md`, Backend Lead, concurrently edited) |
| CPR-API-03 | Skipped — out of scope (`api-specification.md`, Backend Lead, concurrently edited) |
| CPR-API-04 | Skipped — out of scope (`api-specification.md`, Backend Lead, concurrently edited) |
| CPR-API-05 | Skipped — out of scope (`api-specification.md`, Backend Lead, concurrently edited) |
| CPR-API-06 | Skipped — out of scope (`api-specification.md`, Backend Lead, concurrently edited) |
| CPR-API-07 | Skipped — out of scope (`api-specification.md`, Backend Lead, concurrently edited) |
| CPR-API-08 | Skipped — out of scope (`api-specification.md`, Backend Lead, concurrently edited) |
| CPR-API-09 | Skipped — out of scope (`api-specification.md`, Backend Lead, concurrently edited) |
| CPR-API-10 | Skipped — out of scope (`api-specification.md`, Backend Lead, concurrently edited) |
| CPR-API-11 | Skipped — out of scope (`api-specification.md`, Backend Lead, concurrently edited) |
| CPR-API-12 | Skipped — out of scope (`api-specification.md`, Backend Lead, concurrently edited) |
| CPR-API-13 | Skipped — out of scope (`api-specification.md`, Backend Lead, concurrently edited) |
| CPR-API-14 | Skipped — out of scope (`api-specification.md`, Backend Lead, concurrently edited) |
| CPR-API-15 | Skipped — out of scope (`api-specification.md`, Backend Lead, concurrently edited) |
| CPR-API-16 | Skipped — out of scope (`api-specification.md`, Backend Lead, concurrently edited) |
| CPR-TST-01 | Skipped — out of scope (`testing-and-acceptance-criteria.md`, QA Lead, concurrently edited) |
| CPR-TST-02 | Skipped — out of scope (`testing-and-acceptance-criteria.md`, QA Lead, concurrently edited) |
| CPR-TST-03 | Skipped — out of scope (`testing-and-acceptance-criteria.md`, QA Lead, concurrently edited) |
| CPR-TST-04 | Skipped — out of scope (`testing-and-acceptance-criteria.md`, QA Lead, concurrently edited) |
| CPR-TST-05 | Skipped — out of scope (`testing-and-acceptance-criteria.md`, QA Lead, concurrently edited) |
| CPR-TST-06 | Skipped — out of scope (`testing-and-acceptance-criteria.md`, QA Lead, concurrently edited) |
| CPR-TST-07 | Skipped — out of scope (`testing-and-acceptance-criteria.md`, QA Lead, concurrently edited) |
| CPR-TST-08 | Skipped — out of scope (`testing-and-acceptance-criteria.md`, QA Lead, concurrently edited) |
| CPR-TST-09 | Skipped — out of scope (`testing-and-acceptance-criteria.md`, QA Lead, concurrently edited) |
| CPR-TST-10 | Skipped — out of scope (`testing-and-acceptance-criteria.md`, QA Lead, concurrently edited) |
| CPR-TST-11 | Skipped — out of scope (`testing-and-acceptance-criteria.md`, QA Lead, concurrently edited) |
| CPR-TST-12 | Skipped — out of scope (`testing-and-acceptance-criteria.md`, QA Lead, concurrently edited) |
| CPR-TST-13 | Skipped — out of scope (`testing-and-acceptance-criteria.md`, QA Lead, concurrently edited) |
| CPR-TST-14 | Skipped — out of scope (`testing-and-acceptance-criteria.md`, QA Lead, concurrently edited) |
| CPR-TST-15 | Skipped — out of scope (`testing-and-acceptance-criteria.md`, QA Lead, concurrently edited) |
| CPR-TST-16 | Skipped — out of scope (`testing-and-acceptance-criteria.md`, QA Lead, concurrently edited) |
| CPR-TST-17 | Skipped — out of scope (`testing-and-acceptance-criteria.md`, QA Lead, concurrently edited) |
| CPR-TST-18 | Skipped — out of scope (`testing-and-acceptance-criteria.md`, QA Lead, concurrently edited) |
| CPR-TST-19 | Skipped — out of scope (`testing-and-acceptance-criteria.md`, QA Lead, concurrently edited) |
| CPR-TST-20 | Skipped — out of scope (`testing-and-acceptance-criteria.md`, QA Lead, concurrently edited) |
| CPR-TST-21 | Skipped — out of scope (`testing-and-acceptance-criteria.md`, QA Lead, concurrently edited) |
| CPR-DEP-01 | Skipped — out of scope (`deployment-and-operations.md` / `.env.example`, DevOps, concurrently edited) |
| CPR-DEP-02 | Skipped — out of scope (`deployment-and-operations.md` / `.env.example`, DevOps, concurrently edited) |
| CPR-DEP-03 | Skipped — out of scope (`deployment-and-operations.md` / `.env.example`, DevOps, concurrently edited) |
| CPR-DEP-04 | Skipped — out of scope (`deployment-and-operations.md` / `.env.example`, DevOps, concurrently edited) |
| CPR-DEP-05 | Skipped — out of scope (`deployment-and-operations.md` / `.env.example`, DevOps, concurrently edited) |
| CPR-DEP-06 | Skipped — out of scope (`deployment-and-operations.md` / `.env.example`, DevOps, concurrently edited) |
| CPR-DEP-07 | Skipped — out of scope (`deployment-and-operations.md` / `.env.example`, DevOps, concurrently edited) |
| CPR-DEP-08 | Skipped — out of scope (`deployment-and-operations.md` / `.env.example`, DevOps, concurrently edited) |
| CPR-DEP-09 | Skipped — out of scope (`deployment-and-operations.md` / `.env.example`, DevOps, concurrently edited) |
| CPR-DEP-10 | Skipped — out of scope (`deployment-and-operations.md` / `.env.example`, DevOps, concurrently edited) |
| CPR-DEP-11 | Skipped — out of scope (`deployment-and-operations.md` / `.env.example`, DevOps, concurrently edited) |
| CPR-RPM-01 | Applied (key existed; description and namespaces updated; C-4) |
| CPR-RPM-02 | Applied |
| CPR-RPM-03 | Applied |
| CPR-RPM-04 | Applied |
| CPR-RPM-05 | Applied |
| CPR-RPM-06 | Applied (already the v0.2 rule; "never signals" added) |
| CPR-RPM-07 | Applied (keys already present since v0.2; confirmed; C-4) |
| CPR-RPM-08 | Applied |
| CPR-PRD-01 | Applied |
| CPR-PRD-02 | Applied |
| CPR-PRD-03 | Applied |
| CPR-PRD-04 | Applied |
| CPR-PRD-05 | Applied |
| CPR-PRD-06 | Applied |
| CPR-PRD-07 | Applied |
| CPR-PRD-08 | Applied |
| CPR-PRD-09 | Applied |
| CPR-PRD-10 | Applied |
| CPR-PRD-11 | Applied (as part of FR-SEC-009, the published policy text; PO-02) |
| CPR-ARC-01 | Applied (`restriction_class` was already retired in v0.3; `x-td-route-tag`, canonical tags and `x-td-idle` CI check added) |
| CPR-ARC-02 | Applied |
| CPR-ARC-03 | Applied |
| CPR-ARC-04 | Applied |
| CPR-ARC-05 | Applied |
| CPR-ARC-06 | Applied (C-1) |
| CPR-ANL-01 | Applied |
| CPR-ANL-02 | Applied (C-3) |
| CPR-ANL-03 | Applied |

### 9.3 `integration-pass-requests.md` (62)

| Request | Result |
|---|---|
| IPR-API-01 | Skipped — out of scope (`api-specification.md`, Backend Lead) |
| IPR-API-02 | Skipped — out of scope (`api-specification.md`, Backend Lead) |
| IPR-API-03 | Skipped — out of scope (`api-specification.md`, Backend Lead) |
| IPR-API-04 | Skipped — out of scope (`api-specification.md`, Backend Lead) |
| IPR-API-05 | Skipped — out of scope (`api-specification.md`, Backend Lead) |
| IPR-API-06 | Skipped — out of scope (`api-specification.md`, Backend Lead) |
| IPR-API-07 | Skipped — out of scope (`api-specification.md`, Backend Lead) |
| IPR-API-08 | Skipped — out of scope (`api-specification.md`, Backend Lead) |
| IPR-API-09 | Skipped — out of scope (`api-specification.md`, Backend Lead) |
| IPR-API-10 | Skipped — out of scope (`api-specification.md`, Backend Lead) |
| IPR-API-11 | Skipped — out of scope (`api-specification.md`, Backend Lead) |
| IPR-API-12 | Skipped — out of scope (`api-specification.md`, Backend Lead) |
| IPR-API-13 | Skipped — out of scope (`api-specification.md`, Backend Lead) |
| IPR-API-14 | Skipped — out of scope (`api-specification.md`, Backend Lead) |
| IPR-API-15 | Skipped — out of scope (`api-specification.md`, Backend Lead) |
| IPR-API-16 | Skipped — out of scope (`api-specification.md`, Backend Lead) |
| IPR-API-17 | Skipped — out of scope (`api-specification.md`, Backend Lead) |
| IPR-API-18 | Skipped — out of scope (`api-specification.md`, Backend Lead) |
| IPR-API-19 | Skipped — out of scope (`api-specification.md`, Backend Lead) |
| IPR-API-20 | Skipped — out of scope (`api-specification.md`, Backend Lead) — see C-1 for the staleness wording |
| IPR-QA-01 | Skipped — out of scope (`testing-and-acceptance-criteria.md`, QA Lead) |
| IPR-QA-02 | Skipped — out of scope (`testing-and-acceptance-criteria.md`, QA Lead) |
| IPR-QA-03 | Skipped — out of scope (`testing-and-acceptance-criteria.md`, QA Lead) |
| IPR-QA-04 | Skipped — out of scope (`testing-and-acceptance-criteria.md`, QA Lead) |
| IPR-QA-05 | Skipped — out of scope (`testing-and-acceptance-criteria.md`, QA Lead) |
| IPR-QA-06 | Skipped — out of scope (`testing-and-acceptance-criteria.md`, QA Lead) |
| IPR-QA-07 | Skipped — out of scope (`testing-and-acceptance-criteria.md`, QA Lead) |
| IPR-QA-08 | Skipped — out of scope (`testing-and-acceptance-criteria.md`, QA Lead) |
| IPR-DEP-01 | Skipped — out of scope (`deployment-and-operations.md`, DevOps) |
| IPR-DEP-02 | Skipped — out of scope (`deployment-and-operations.md`, DevOps) |
| IPR-DEP-03 | Skipped — out of scope (`deployment-and-operations.md`, DevOps) |
| IPR-DEP-04 | Skipped — out of scope (`deployment-and-operations.md`, DevOps) |
| IPR-DEP-05 | Skipped — out of scope (`deployment-and-operations.md`, DevOps) |
| IPR-DEP-06 | Skipped — out of scope (`deployment-and-operations.md`, DevOps) |
| IPR-DEP-07 | Skipped — out of scope (`deployment-and-operations.md`, DevOps) |
| IPR-DEP-08 | Skipped — out of scope (`deployment-and-operations.md`, DevOps) |
| IPR-DEP-09 | Skipped — out of scope (`deployment-and-operations.md`, DevOps) |
| IPR-DEP-10 | Skipped — out of scope (`deployment-and-operations.md`, DevOps) |
| IPR-DEP-11 | Skipped — out of scope (`deployment-and-operations.md`, DevOps) |
| IPR-ROAD-01 | Skipped — out of scope (`implementation-roadmap.md`, concurrently edited) |
| IPR-ROAD-02 | Skipped — out of scope (`implementation-roadmap.md`, concurrently edited) |
| IPR-ROAD-03 | Skipped — out of scope (`implementation-roadmap.md`, concurrently edited) |
| IPR-ROAD-04 | Skipped — out of scope (`implementation-roadmap.md`, concurrently edited) |
| IPR-ROAD-05 | Skipped — out of scope (`implementation-roadmap.md`, concurrently edited) |
| IPR-ROAD-06 | Skipped — out of scope (`implementation-roadmap.md`, concurrently edited) |
| IPR-ROAD-07 | Skipped — out of scope (`implementation-roadmap.md`, concurrently edited) |
| IPR-README-01 | Skipped — out of scope (`README.md`, concurrently edited) |
| IPR-README-02 | Skipped — out of scope (`README.md`, concurrently edited) |
| IPR-ENV-01 | Skipped — out of scope (`.env.example`, DevOps) |
| IPR-ENV-02 | Skipped — out of scope (`.env.example`, DevOps) |
| IPR-ENV-03 | Skipped — out of scope (`.env.example`, DevOps) — see C-1 |
| IPR-ENV-04 | Skipped — out of scope (`.env.example`, DevOps) |
| IPR-SRC-01 | Skipped — out of scope (`source-requirements-excerpt.md` not in this pass's edit set) |
| IPR-SRC-02 | Skipped — out of scope (`source-requirements-excerpt.md` not in this pass's edit set) |
| IPR-SEC-01 | Skipped — out of scope (Security Specialist documents) |
| IPR-SEC-02 | Skipped — out of scope (Security Specialist documents) |
| IPR-SEC-03 | Skipped — out of scope (Security Specialist documents) |
| IPR-SEC-04 | Skipped — out of scope (Security Specialist documents) |
| IPR-SEC-05 | Skipped — out of scope (Security Specialist documents) |
| IPR-SEC-06 | Skipped — out of scope (Security Specialist documents) |
| IPR-AN-01 | Applied |
| IPR-AN-02 | Applied |

### 9.4 Counts and checks

| Target file | Applied | Skipped |
|---|---|---|
| blueprint-brief | 12 | 0 |
| database-schema | 15 | 0 |
| database-erd | 4 | 0 |
| role-permission-matrix | 8 | 0 |
| product-requirements | 11 | 0 |
| system-architecture | 6 | 0 |
| analytics-event-schema | 5 (CPR-ANL 3 + IPR-AN 2) | 0 |
| feature-comparison, ADRs | 0 requests (ADR-0002/0006/0013 updated for consistency, C-1) | 0 |
| Other owners' files (API 36, testing 29, deployment 22, roadmap 7, README 2, `.env.example` 4, source excerpt 2, security docs 6) | 0 | 108 |
| **Total (169)** | **61** | **108** |

Scripted checks after applying (Python over the Markdown sources):

- Brief v0.4 §4 lists **122** tables (excluding the three reserved P2 names); every one has a `CREATE TABLE` in `database-schema.md` (122 `CREATE TABLE` statements, none extra) and appears as an entity or relationship in `database-erd.md`. **Pass.**
- Role matrix: **125** catalogue keys (§2), all matching the key-format regex; every key used in the §3 matrix (wildcard and slash forms expanded) and in the §10 canonical-key column is in the catalogue; every catalogue key now has a §3 row (after adding `question.retire`). **Pass.**

---

## 10. Final cleanup log (2026-11-03, Security & Account Monitoring Specialist)

Docs-only, targeted edits; each edited file has a changelog line.

| # | Item | Resolution | Files |
|---|---|---|---|
| FC-01 | IPR-SEC-01 (`security.policy.write`) | Already applied in RE v0.3 §3.1 (`policy.edit` / `policy.propose`); confirmed | `account-security-and-risk-engine.md` |
| FC-02 | IPR-SEC-02 (H1–H12 views, H4 key) | Views already H1–H12 incl. H10/H11; report keys for every view (H4 `repeated-network-device-associations`) added to RE §10 | `account-security-and-risk-engine.md` |
| FC-03 | IPR-SEC-03 (`shared_organization_id`) | Already applied (RE §5.5, §12); confirmed | `account-security-and-risk-engine.md` |
| FC-04 | IPR-SEC-04 (webhook path) | `POST /api/v1/webhooks/{provider}` in threat model §4.1 and RE AB-12 | `security-threat-model.md`, `account-security-and-risk-engine.md` |
| FC-05 | IPR-SEC-05 (Sentry) | Sentry SaaS removed from privacy §10 processors; GlitchTip self-hosted in ap-south-1 (ADR-0014) added as D19 (90 days, scrubbed) and job `purge_error_events` | `privacy-and-data-retention.md` |
| FC-06 | IPR-SEC-06 (playback paths, `409 playback_conflict`) | Already applied (RE §6.3, §7.3); confirmed | `account-security-and-risk-engine.md` |
| FC-07 | API I-26 (export approver) | `report.export.approve` split by report family: security/monitoring exports (H1–H9, H12, per-user device/login history; `security.export.per_user`) approved by a second `security_reviewer`; all other exports needing approval (`export.bulk_pii`: H10/H11 aggregates, finance, college reports) by `super_admin`; approver ≠ requester. `super_admin` dashboard access limited to aggregate views (per-user evidence only in break-glass) | role matrix v0.4 §2.7/§3/§5; API §1.7, SEC-32, ANL-13, I-26 (Resolved); RE §10; privacy §9; testing RPT-01/03/05; brief §3 + v0.4 changelog |
| FC-08 | AMB-22 (owner-verification expiry vs example A) | `owner_verified_at` refreshed by any SMS-OTP/passkey/TOTP challenge on the device; pre-expiry "Keep this device verified" prompt (`risk.owner_verification.refresh_prompt_days` = 5); a lapsed device scores × 0.3 only while lapsed; example A restated | RE §3.2, §4.2.1, §5.1; testing SCN-01, §5 |
| FC-09 | AMB-23 (`risk.mode` scope) | `risk.mode` and the kill switch govern sharing enforcement only; takeover protections, deterministic caps and AB-*/IN-* always enforce | RE §3.2, §5.7; testing KS-07, §5 |
| FC-10 | AMB-24 (circuit-breaker edges) | (a) FP test from the first decision with absolute threshold `max_fp_rate × min_decisions` (2nd FP trips); (b) daily limit checked before applying, the 51st is not applied (shadow evaluation, scored path continues) | RE §5.7; testing CB-03, CB-06, §5, I-13 (Resolved) |
| FC-11 | §6 follow-ups F-SEC/F-UNB/F-PRIV/F-THR (12) and F-AN (6) | Verified as applied in the current documents; §7.3 "Open" rows superseded; roadmap §12 I-3 → Resolved | `implementation-roadmap.md` |
| FC-12 | Stale-term sweep | `stream_cap_reached`, `stream_limit_reached`, `user_topic_mastery`, `apps/api/alembic`, `sentry.io`, unprefixed `/webhooks/{provider}`, retired `report.export`, `security.policy.write`: remaining hits are historical (changelogs, issue logs, reconciliation tables, rename tables) or explanatory (`sentry.io` "not allowlisted"); API WH-01..04 paths are relative to the stated `/api/v1` base. No further edits needed | — |

**Open after this pass:** none in the security lane. Product-owner and counsel items (PO-*, P-*) are unchanged.
