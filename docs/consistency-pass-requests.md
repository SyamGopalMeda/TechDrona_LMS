# Consistency-Pass Requests — Security Review Pass (v0.3)

| | |
|---|---|
| Owner | Security & Account Monitoring Specialist (author of the requests; each target file keeps its own owner) |
| Source decisions | `account-security-and-risk-engine.md` (RE) v0.3, `account-unblock-workflow.md` (UNB) v0.3, `security-threat-model.md` (TM) v0.3, `privacy-and-data-retention.md` (PRIV) v0.3 |
| Inputs resolved | `testing-and-acceptance-criteria.md` §5 AMB-01..21 and §13; `api-specification.md` §27 (security items); `deployment-and-operations.md` §20 (security items) |
| Status | Every request is **Proposed**. The owner of each target file applies it (or rejects it with a reason) in the next consistency pass |

## Changelog

### v0.1 — 2026-11-03 (Security Specialist)

Initial list: 107 change requests across 10 target files, produced by the security review pass.

---

## How to use this file

- Each request has an id `CPR-<target>-nn`, the exact location, the exact change, and the source decision. "Replace A with B" means a literal text change; DDL is given where a table changes.
- Where a request says **Resolved: no change**, the target's open issue is closed by a decision in a security document and only the issue entry needs to be marked resolved.
- Summary of the ten must-fix decisions, for orientation:

| # | Decision | Source |
|---|---|---|
| 1 | SH-01 is weighted by **network separation class** S0–S3, not by OTP verification; S3 (two distinct fixed-line networks at once) is always ×1.0; new SH-13 "verification at a distance"; L3 gate needs separated-use evidence | RE §4.2.1, §5.1, §5.3 |
| 2 | High-confidence rules **HC-01/HC-02** (sharing → auto-L3, adults only) and **HC-T1..T3** (takeover → T-protect); shadow first, 🔒 master switch `risk.hc.auto_restrict_enabled` (default false), circuit breaker | RE §5.6, §5.7 |
| 3 | Cookie replay (TO-04/TO-08/TO-10): revoke **the replayed session only** + takeover evaluation (T-step-up); revoke all only on HC-T3 | RE §4.3, §6.2 |
| 4 | Idle effect per route (`extends` / `engaged_only` / `neutral`); attempt idle hold; remember-device re-issue only on a top-level user navigation, fixed 30-day ceiling | RE §1.4 |
| 5 | Same-device re-login re-attaches an attempt without consuming a rebind; attempt-holding sessions never evicted | RE §6.3, §7.4 |
| 6 | Webhooks: HMAC + dedupe + provider re-fetch for every state-changing event; no age-based rejection | TM §2.4 |
| 7 | Pending second approvals live in `approval_requests` (`security.case.decision`); `case_decisions` written only when final | UNB §5.1 |
| 8 | Rule registry: SH-*, TO-*, HC-*, AB-01..12, IN-01..03, `cap.*` | RE §4 |
| 9 | Canonical route tags = API spec §1.4 set; scope derived per request | RE §7.2 |
| 10 | Kill switch (single approver to shadow + 24 h ratification), bulk FP lift (Dual), HMAC key versioning, security logs purged at **395 days** | RE §1.5, §5.7, §5.8; PRIV §7.1 |

---

## 1. `docs/blueprint-brief.md` (Integration Lead)

| ID | Location | Change | Source |
|---|---|---|---|
| CPR-BRF-01 | §1 Risk engine | Replace "The engine may apply L1–L3 automatically (L3 only behind multi-day, multi-category gates)" with "The engine may apply L1–L3 automatically: L3 only behind multi-day, multi-category, separated-use gates, **or** through a configured high-confidence rule (HC-01/HC-02, adults only) that has completed ≥ 14 days of shadow and dual approval and is enabled by the 🔒 switch `risk.hc.auto_restrict_enabled` (default false); an automatic circuit breaker returns an HC rule to shadow on a false-positive spike" | RE §5.6, §5.7 |
| CPR-BRF-02 | §1 Risk engine, append | "Owner (OTP/passkey) verification never discounts overlapping use on two distinct fixed-line networks at the same time (separation class S3). Emergency move of `risk.mode` to `shadow` (or HC rules off) needs one `security_reviewer`/`super_admin` plus ratification by a second person within 24 h; any move toward enforcement is dual-approved. Engine-applied L3s can be lifted in bulk (Dual)." | RE §4.2.1, §5.7, §5.8 |
| CPR-BRF-03 | §1 Timeouts | Replace `(with "remember device" refresh up to 30 days only on trusted devices)` with `(with "remember device": silent re-issue only on a top-level user navigation on a trusted device, within a fixed 30-day ceiling from the last full authentication that never slides; the re-issued session is AAL1)`. Replace the sentence "The idle timer is extended only by engaged activity (input or media playing); analytics keepalives never extend it." with "The idle timer is extended only by engaged activity: every authenticated route declares an idle effect (`extends`, `engaged_only`, `neutral`); keepalives, polling and prefetches never extend it; an in-progress timed attempt holds the session until `deadline_at + grace + 5 min`; absolute timeouts are never extended." | RE §1.4 |
| CPR-BRF-04 | §1 Device policy, after "max 2 rebinds per attempt" | Insert "; re-login on the same device (same `__Host-td_device`) re-attaches the attempt without consuming a rebind or needing OTP; sessions holding an in-progress attempt are never auto-evicted by the session cap" | RE §6.3, §7.4 |
| CPR-BRF-05 | §1 Sessions, append | "Session cookie `Max-Age` = time to absolute expiry (registered lab devices: browser-session cookie). `k_device` and `k_login` HMAC keys are versioned (`key_version`) so they can be rotated without breaking lookups. Postgres is the session source of truth; Redis `cache` is a read-through copy." | RE §1.4–§1.6 |
| CPR-BRF-06 | §1 Payments | Replace "Webhooks verified (HMAC) and idempotent." with "Webhooks verified (HMAC over the raw body) and idempotent (event-id dedupe); no age-based rejection — every state-changing event is applied from a server-side re-fetch of the entity from the provider." | TM §2.4 |
| CPR-BRF-07 | §1 Privacy | Replace "Logs min 1 year" with "Logs min 1 year (security and operational logs purged at 13 months = 395 days)" | PRIV §7.1 |
| CPR-BRF-08 | §1 Minors, after "never an accumulated score" | Insert "; no `risk_evaluations` rows of any family are written for minors; deterministic takeover actions are recorded as `security_signals`" | RE §4.4 |
| CPR-BRF-09 | §4 Sessions/devices | Add `session_network_observations` to the canonical table list | RE §1.2 |
| CPR-BRF-10 | §5, restricted-route sentence | Replace "may call only routes tagged `account_status` (me, devices/sessions, …; L3 also read-only dashboard/progress)" with "may call only routes tagged `account_status` (…) and, for L3, `l3_readonly`. The canonical tag set is `public`, `login_continuation`, `account_status`, `l3_readonly`, `mfa_enrolment`, `consent`, `default` (`api-specification.md` §1.4); tags may be declared in any module. Session scope is derived per request from the restriction state." Add "`409 session_too_short_for_attempt`" to the standard codes sentence | RE §7.2 |
| CPR-BRF-11 | §3 Roles, dual-control sentence | Append "Pending second-person case decisions are `approval_requests` rows (`security.case.decision`); `case_decisions` stores final decisions only." | UNB §5.1 |
| CPR-BRF-12 | §8 Changelog | Add a v0.3 entry listing CPR-BRF-01..11 | — |

## 2. `docs/database-schema.md` (System Architect)

| ID | Location | Change | Source |
|---|---|---|---|
| CPR-SCH-01 | §4 `devices`; §4 `login_attempts` | `devices`: add `key_version smallint NOT NULL DEFAULT 1 CHECK (key_version >= 1)` and change the `device_key_hash` comment to `-- HMAC-SHA256(k_device_v{key_version}, raw id); re-hashed in place on lookup with an old version`. `login_attempts`: add `key_version smallint NOT NULL DEFAULT 1 CHECK (key_version >= 1)`; comment on `identifier_hash`: `-- HMAC(k_login_v{key_version}, normalised email/phone); never re-hashed` | RE §1.5; DEP I-04 |
| CPR-SCH-02 | §4 `user_devices` | Add `remember_token_hash bytea NULL CHECK (remember_token_hash IS NULL OR octet_length(remember_token_hash) = 32)`, `remember_issued_at timestamptz NULL`; add `CONSTRAINT ck_ud_remember CHECK ((remember_token_hash IS NULL) = (remember_until IS NULL))`; `CREATE UNIQUE INDEX ux_ud_remember ON user_devices (remember_token_hash) WHERE remember_token_hash IS NOT NULL;`. Comment on `owner_verified_at`: `-- set only by sms_otp (registered mobile), passkey, totp or support; email_otp sets trusted_at only`. Comment on `remember_until`: `-- fixed at last full authentication; never slides` | RE §1.4, §4.2.1 |
| CPR-SCH-03 | §4 `auth_sessions` | `status` CHECK: add `'pending_session_choice'`. `created_via` CHECK: add `'remember_device'`. `end_reason` CHECK: add `'replaced_same_device'`. Add column `idle_hold_until timestamptz NULL` (`-- deadline_at + grace + 5 min while bound to an in-progress attempt`). Comment on `scope`: `-- record only; enforcement derives scope per request from restr:{uid}` | RE §1.2, §1.4, §6.3 |
| CPR-SCH-04 | §4, new table after `auth_sessions` | `CREATE TABLE session_network_observations ( id uuid NOT NULL, first_seen_at timestamptz NOT NULL DEFAULT now(), last_seen_at timestamptz NOT NULL DEFAULT now(), auth_session_id uuid NOT NULL, user_id uuid NOT NULL, net_cluster text NOT NULL, asn integer NULL, network_type text NULL CHECK (network_type IN ('mobile','broadband','hosting','vpn_proxy','tor','education','unknown')), geo_region text NULL, PRIMARY KEY (id, first_seen_at) ) PARTITION BY RANGE (first_seen_at); CREATE INDEX ix_sno_session ON session_network_observations (auth_session_id, first_seen_at); CREATE INDEX ix_sno_user_time ON session_network_observations (user_id, first_seen_at DESC);` Header: `-- Owner sessions. Written on network-cluster change, ≤ 1 per 60 s per session. RLS: O | Retention: R-SEC | PII: P3`. Add to §1.3 partition list and §14 summary | RE §1.2 |
| CPR-SCH-05 | §5 `case_decisions`; §13 `approval_requests` | `case_decisions`: add `approval_request_id uuid NULL REFERENCES approval_requests(id)` and `CONSTRAINT ck_cd_approval_link CHECK (NOT requires_second_approval OR approval_request_id IS NOT NULL)`; table comment: `-- Final decisions only; a decision awaiting a second approver lives in approval_requests (action_type security.case.decision) and is inserted here on approval (UNB §5.1)`. `approval_requests.action_type` comment: add `'security.case.decision'`, `'security.restriction.bulk_lift'`, `'risk.kill_switch.ratify'`. Add `CREATE UNIQUE INDEX ux_apr_case_decision_pending ON approval_requests (target_id) WHERE action_type = 'security.case.decision' AND status = 'pending';` | UNB §5.1; RE §5.7, §5.8; AMB-13 |
| CPR-SCH-06 | §9 `attempt_events`, `test_attempts` | `attempt_events.event_type` CHECK: add `'reattach_same_device'`. `test_attempts.rebind_count` comment: `-- incremented only when bound_device_id changes; same-device re-attach does not count` | RE §7.4; AMB-08 |
| CPR-SCH-07 | §5 `security_cases.opened_reason` | Add `'engine_hc_L3'` to the CHECK | RE §5.6 |
| CPR-SCH-08 | §5 `risk_evaluations` | Add `is_minor_at_time boolean NOT NULL DEFAULT false` and `CONSTRAINT ck_re_no_minor CHECK (NOT is_minor_at_time)`. `trigger` CHECK: add `'verification'`. Comment on `gates`: `-- incl. hc_rule, separated_days, l2_reached` | RE §4.4, §5.2, §9; AMB-12 |
| CPR-SCH-09 | §5 `security_signals` | Comment on `rule_key`: replace the example `'abuse.webhook_signature_invalid'` with `'AB-12'`; document the key families `SH-*`, `TO-*`, `HC-*`, `AB-*`, `IN-*`, `cap.*`. `multipliers` example: `{"separation_class":"S3","separation":1.0,"trusted_network":1.0,"counted":true}` | RE §4.1, §4.5 |
| CPR-SCH-10 | §5 `risk_rule_versions` | Add `status_changed_at timestamptz NULL`, `status_changed_by uuid NULL REFERENCES users(id)` (`-- NULL = system`), `status_change_reason text NULL CHECK (status_change_reason IN ('activation','rollback','retire','circuit_breaker','kill_switch'))`. Document the allowed transition `active → shadow` (circuit breaker / kill switch) | RE §5.7 |
| CPR-SCH-11 | §1.4 retention classes | R-SEC: replace "1 year minimum (180 days hot), purge at 13 months" with "1 year minimum (180 days hot); purge at **395 days** (`auth_sessions` ended rows, `login_attempts`, `session_network_observations`, operational logs)". R-AUDIT: replace "8 years for privileged/financial audit; aligns with R-FIN" with "Security-administration and access actions 3 years; financial actions 8 years (aligns with R-FIN); Object-Lock hash anchors 8 years" | PRIV §2 D5, D17, §7.1 |
| CPR-SCH-12 | §13 `policy_settings` key-namespace comment | Add `risk.hc.*`, `risk.separation.*`, `risk.owner_verification.*`, `security.keys.*`, `assessment.idle_hold_extra_minutes`; note that `risk.owner_verified_overlap_multiplier` is retired | RE §3.2 |
| CPR-SCH-13 | §11 `payment_webhook_events` | Add `refetched_at timestamptz NULL`, `refetch_status text NULL CHECK (refetch_status IN ('ok','failed','not_required'))`; comment on `is_stale`: `-- monitoring flag only (> 5 min old); stale events are processed via re-fetch, never rejected` | TM §2.4; AMB-10 |
| CPR-SCH-14 | §3 `users` | Endorse `is_synthetic boolean NOT NULL DEFAULT false` (testing I-06, deployment I-15); the risk engine excludes synthetic accounts from SH and HC rules | RE §4.4 |
| CPR-SCH-15 | §15/§16 | Record CPR-SCH-01..14 as v0.3 security follow-ups | — |

## 3. `docs/database-erd.md` (System Architect)

| ID | Location | Change | Source |
|---|---|---|---|
| CPR-ERD-01 | Sessions/devices diagram | Add entity `session_network_observations` with `auth_sessions ||--o{ session_network_observations` (soft ref, partitioned) | CPR-SCH-04 |
| CPR-ERD-02 | Security / platform diagram | Add `approval_requests ||--o{ case_decisions : "approval_request_id"`; annotate `case_decisions` "final decisions only" | CPR-SCH-05 |
| CPR-ERD-03 | Attribute lists | Add `devices.key_version`, `login_attempts.key_version`, `user_devices.remember_token_hash/remember_issued_at`, `auth_sessions.idle_hold_until`, `risk_evaluations.is_minor_at_time`, `risk_rule_versions.status_changed_*` | CPR-SCH-01..10 |
| CPR-ERD-04 | Enum notes | `auth_sessions.status` + `pending_session_choice`; `end_reason` + `replaced_same_device`; `created_via` + `remember_device`; `security_cases.opened_reason` + `engine_hc_L3`; `attempt_events` + `reattach_same_device` | CPR-SCH-03, -06, -07 |

## 4. `docs/api-specification.md` (Backend Lead)

| ID | Location | Change | Source |
|---|---|---|---|
| CPR-API-01 | §1.4 steps | Step 2: "Unknown in **both** Redis and Postgres → `401 unauthenticated` (counted as AB-07)". Step 3: idle expiry is not enforced while `now < idle_hold_until`. Step 4: "Device cookie hash ≠ session device (TO-04) or `ua_family`/`os_family` drift (TO-08) → revoke **this session only** (`device_mismatch`, status `blocked`), takeover evaluation → `401 session_revoked`". Step 6: add `pending_session_choice` to the pending statuses. Step 10: "Slide the idle timer only for routes with `x-td-idle: extends`; `engaged_only` routes slide it through `sessions.touch_engaged()` when the server credits engagement; `neutral` never" | RE §1.4, §1.6, §7.2 |
| CPR-API-02 | §1.4, new sub-table after route tags | Add "**Idle effect** (`openapi_extra={"x-td-idle": ...}`, required on every authenticated route; CI-checked)": `extends` (state-changing user actions; GETs marked by the BFF with `X-TD-Activity: navigation`), `engaged_only` (`ANL` ingest, playback heartbeat with `state = playing`, `ATT-05` autosave with a changed response), `neutral` (keepalives, notification polling/SSE, `SEC-01` polling, prefetch). `X-TD-Activity` is accepted only from the BFF hop and stripped from browser requests | RE §1.4 |
| CPR-API-03 | §1.4 after the tag table | Add "Scope is derived per request (`auth_sessions.scope` is a record only). During an L3 deferral the attempt-bound session keeps `full` scope for that attempt's `ATT-*` routes only; all other sessions are revoked immediately" | RE §7.2, §7.4; AMB-20, AMB-21 |
| CPR-API-04 | §6.1 SEC-09/10/11, §6.2 detail entries, §1.7 last sentence, §7 transition table | SEC-09 `202` body: `{"requires_second_approval": true, "approval_request_id": "...", "expires_at": "...", "unblock_request": {"state": "escalated"}}` — **no `decision_id`** (no `case_decisions` row exists yet). SEC-10 path → `POST /security/cases/{case_id}/approval-requests/{approval_request_id}/approve` (inserts `case_decisions` with `approved_by`, `approval_request_id`; returns `decision_id`). SEC-11 path → `POST /security/cases/{case_id}/approval-requests/{approval_request_id}/send-back` (approval status `rejected`; request → `under_review`). New SEC-11a `POST /security/cases/{case_id}/approval-requests/{approval_request_id}/withdraw` (requester only; status `cancelled`). Errors on SEC-10/11: `invalid_state_transition` when the approval request is `expired`, `cancelled` or already decided. §2.2 `second_approval_required` extension: `approval_request_id` (replaces `decision_id`). §1.7: replace the last sentence with "Security case decisions that need a second approver are stored as `approval_requests` (`security.case.decision`) and decided through SEC-10/SEC-11, not ADM-14" | UNB §5.1; AMB-13 |
| CPR-API-05 | §6.1, new endpoints | SEC-42 `POST /security/engine/kill-switch` — body `{target: "risk_mode" \| "hc_all" \| "rule", rule_key?: "HC-01", reason}`; permission `security.engine.kill_switch` @P; step-up P5; Idem Req; creates the `risk.kill_switch.ratify` approval request; only moves toward shadow/off-for-HC (else `409 invalid_state_transition`). SEC-43 `GET /security/engine/state` — `risk.mode`, HC switch, per-rule status, circuit-breaker state, pending ratifications; `security.rule.read` @P. SEC-44 `POST /security/restrictions/bulk-lift-requests` — body `{selector: {ruleset_version?, rule_key?, organization_id?, applied_from?, applied_to?, network_cidr?, asn?}, dry_run: bool, reason, extension_credit: bool}`; permission `security.restriction.bulk_lift` @P; P5 + Dual when `dry_run = false`; Idem Req; `dry_run` returns `{matched, excluded_by_reason{}, sample[≤50 masked]}`; > 5,000 matches → `422 validation_failed` (`selector_too_broad`). SEC-45 `GET /security/restrictions/bulk-lift-requests/{id}` — status and per-case progress | RE §5.7, §5.8; DEP I-01, I-02 |
| CPR-API-06 | §18.2 steps 2 and 5; §18 responses | Step 2: `rule_key = abuse.webhook_signature_invalid` → `rule_key = AB-12`. Step 5: replace "If `now − created_at > tolerance` … re-fetches" with "For **every** event that can change order, payment, refund, subscription or entitlement state, the worker re-fetches the entity from the provider API and applies the fetched state (never the payload state). Events older than `commerce.webhook.tolerance_seconds` are flagged `is_stale` for monitoring only. No event is rejected for age." Worker: if the re-fetch fails, retry with backoff without any state change (`refetch_status = failed`) | TM §2.4; AMB-10; API I-14 |
| CPR-API-07 | §6.1 SEC-30/31; SEC-13 summary | Report keys follow RE §10: H1 suspicious-activity queue, H2 device–account graph, H3 concurrent-use events, H4 network-cluster associations, H5 blocked/restricted, H6 pending unblock requests, H7 review time, H8 false-positive rate (incl. per HC rule), H9 repeat incidents, H10 active sessions, H11 activity context, H12 user security timeline, ENG engine health. SEC-13 → "(report H12)"; SEC-15 → "(H2)"; SEC-14 → "(H3)" | RE §10; API I-15 |
| CPR-API-08 | §4.1 AUTH, new endpoint | AUTH-xx `POST /auth/remember/refresh` — called **only by the BFF** on a top-level user navigation (`Sec-Fetch-Mode: navigate`, `Sec-Fetch-User: ?1`) when the session has expired and `__Host-td_remember` is present; tag `public` (BFF-internal); issues a new session (`created_via = remember_device`, AAL1, rotated remember token). Errors `401 remember_invalid` (unknown, expired, superseded → TO-10, device not trusted, restriction ≥ L3, T-protect) | RE §1.4 rule 5 |
| CPR-API-09 | §6.1, new endpoint | SEC-46 `POST /me/security/events/{event_ref}/disown` ("This wasn't me" on a replay or new-sign-in notice); permission S; tag `account_status`; triggers HC-T3 (revoke all sessions, forced reset) and returns the recovery URL | RE §5.6; UNB §1.6a |
| CPR-API-10 | §2.2 error catalogue | Add `409 session_too_short_for_attempt` (`reauth_url`, `required_until`): attempt start when `absolute_expires_at < deadline_at + grace + 5 min`. `device_verification_required` description: "L2: this device (including a previously verified device that appears in the L2 evidence) must re-verify by SMS OTP, passkey or TOTP; email OTP not accepted" | RE §1.4, §6.1 |
| CPR-API-11 | §15 ATT start / resume / rebind detail entries | Start: add error `session_too_short_for_attempt`; set `idle_hold_until` on success. Resume from another session on the **same `device_id`** → `200` with `{"reattached": true}`, `rebind_count` unchanged, event `reattach_same_device`; `409 attempt_bound_elsewhere` only when the device differs | RE §7.4; AMB-08 |
| CPR-API-12 | §4/§5 login and session-cap (`session_cap_reached`) | Before the cap check, active sessions on the same `device_id` end as `replaced_same_device`. The chooser pre-selects the oldest session without an active attempt; non-interactive clients evict only sessions without an active attempt; if every other session holds an active attempt → `409 session_cap_reached` (no eviction). Pending status is `pending_session_choice` (resolves API I-08) | RE §6.3, §7.1 |
| CPR-API-13 | §7.1 UNB-01 rate-limit column | Remove "CAPTCHA after 2nd/day" (no CAPTCHA; WCAG 2.2 SC 3.3.8) | UNB §3; AMB-19 |
| CPR-API-14 | §27 issue table | Mark resolved: I-02 (adopt `policy.propose`, CPR-RPM-01), I-07 (tags, RE §7.2), I-08 (CPR-API-12), I-14 (CPR-API-06), I-15 (CPR-API-07), I-21 (CPR-API-15), I-23 (CPR-RPM-06), I-25 (already `shared_organization_id`) | — |
| CPR-API-15 | §4 AUTH login detail (hard disable) | Hard-disabled account (`login.hard_disable_after_failures`): response stays `401 invalid_credentials` (identical to unknown user, including timing); an out-of-band email/SMS to the verified contact explains the pause and links to password reset; a successful reset or MFA login clears the counter (resolves API I-21) | RE §3.2; FR-IDN-009 |
| CPR-API-16 | §1.11 / ingest rows | Ingest limits: reference `analytics-event-schema.md` §5.2 as the single source (TM no longer states its own values) | TM §2.7; AMB-11 |

## 5. `docs/testing-and-acceptance-criteria.md` (QA Lead)

| ID | Location | Change | Source |
|---|---|---|---|
| CPR-TST-01 | §5 AMB-01; SCN-01, SCN-05 | Resolved. Owner-verified = SMS OTP to the registered mobile, passkey or TOTP within 30 days (email OTP = trusted only). SH-01 multiplier by separation class: S0 0/0.1, S1 0.1, S2 0.1 (both verified) / 0.3, S3 1.0 (never discounted). Golden values: RE §5.1 worked examples A (≈ 15 → L0; email-only phone ≈ 45 → L2 → re-weighted ≈ 15), B (≈ 71 → L3; 2-day variant ≈ 55 → L2), C (≈ 15–25 → L0/L1) | RE §4.2.1, §5.1 |
| CPR-TST-02 | §5 AMB-02; SCN-19 step 6, "Auto-restriction" row | Resolved. Expected: only S1 revoked (`device_mismatch`, status `blocked`), other sessions stay active, adults get a takeover evaluation (+60 → T-step-up on the next login/sensitive action), owner notice UNB §1.6a. Add step 6b: second replay within 24 h (or "This wasn't me") → HC-T3 → all sessions revoked, `must_change_password`. Replace "(and per AMB-02, possibly all sessions)" with "(all sessions only on HC-T3)". Add TO-08 variant: same cookies replayed in a different browser family → same as step 6 | RE §4.3, §6.2 |
| CPR-TST-03 | §5 AMB-03; SCN-09 | Resolved (no PO decision needed): scenario 9 is satisfied by HC-01/HC-02 (and HC-T1..T3 for takeover). Add fixtures: (e) HC-01 met with `risk.hc.auto_restrict_enabled = true` and HC-01 version `active` → L3 regardless of score, case `opened_reason = engine_hc_L3`, evaluation `gates.hc_rule = 'HC-01'`; (f) HC-01 met but switch false or version `shadow` → `mode = shadow` evaluation only; (g) circuit breaker: 3 `lift_false_positive` among the last 20 HC-01 decisions → HC-01 status `shadow`, `status_change_reason = circuit_breaker`, alert; (h) minor with HC-01 facts → nothing. Precondition note: `risk.mode` default is `shadow` at launch | RE §5.6, §5.7 |
| CPR-TST-04 | §5 AMB-04; SCN-13, SCN-14, SCN-17, SCN-18, SCN-19; §13 I-05 | Resolved by RE §4.5. Replace `abuse.webhook_signature_invalid` with `AB-12` (SCN-14). SCN-13 events: AB-08 at ≥ 30 `account_restricted` in 10 min (info, no escalation). SCN-17: IN-01 (plausibility, no score), IN-02 (forgery bursts). SCN-18: AB-09 (≥ 20 404s/min or ≥ 5 cross-tenant hits/h → security-lead alert). SCN-19 step 8: AB-07 (≥ 20 unknown tokens per /24 in 10 min → throttle 15 min) | RE §4.5 |
| CPR-TST-05 | §5 AMB-05, -06, -07; SCN-15 | Resolved. Expected: keepalives (`neutral`) never extend idle; engaged ingest extends only via `touch_engaged`; idle expiry 60 min after the last engaged activity; background request after expiry → 401 and no remember-device re-issue; re-issue only on a top-level navigation with a valid rotated `__Host-td_remember` and `now < remember_until` (fixed); new test case: timed attempt with no input for 70 min → session still valid until `deadline + grace + 5 min`; attempt start with insufficient absolute time → `409 session_too_short_for_attempt` | RE §1.4 |
| CPR-TST-06 | §5 AMB-08; SCN-16 (B); §13 I-11 | Resolved. (B): re-login on the same device ends the old session as `replaced_same_device`, re-attaches the attempt (`attempt_events` `reattach_same_device`), `rebind_count` unchanged, no OTP even at ≥ L2. (A): cookie survives the crash (`Max-Age` to absolute expiry). R-2: attempt-holding sessions never auto-evicted; all others hold attempts → `409 session_cap_reached` | RE §6.3, §7.4 |
| CPR-TST-07 | §5 AMB-09 | Resolved: Postgres is the source of truth; Redis miss → DB lookup; unknown in both → 401. TS-DR: Redis outage → logins and session checks continue via Postgres | RE §1.6 |
| CPR-TST-08 | §5 AMB-10; SCN-14 | Resolved. Expected for the 6 h-late delivery: same `event_id` → 2xx `duplicate`, no effect; a different valid event for the same payment hours later → 2xx, re-fetch, no second grant (`refetch_status = ok`). No request is rejected for age. Invalid signature → `400 webhook_signature_invalid` + AB-12. Provider API down during re-fetch → retries, no state change | TM §2.4 |
| CPR-TST-09 | §5 AMB-12; TS-PRIV | Resolved: no `risk_evaluations` rows of **any** family for minors (`ck_re_no_minor`); a minor's TO-04 writes `security_signals` (`family = takeover`, `base_points = 0`, `is_minor_at_time = true`) plus the session end record | RE §4.4 |
| CPR-TST-10 | §5 AMB-13; SCN-11 variant, SCN-20 variant | Resolved. Expected: R1's high-risk decision → `202` with `approval_request_id`; **no** `case_decisions` row; request and case `escalated`. R2 approves via the approval-request path → `case_decisions` inserted (`decided_by = R1`, `approved_by = R2`, `approval_request_id`). Add cases: R1 approving own request → `sod_violation`; send-back → approval `rejected`, request `under_review`; 72 h lapse → `expired`, case stays `escalated`, SLA alert | UNB §5.1 |
| CPR-TST-11 | §5 AMB-14; SCN-20 | Resolved (PO-10 to confirm): credit = ceil(restricted days incl. any L4 period of the case) to every time-bound entitlement active during the restriction; contract seats capped at the contract end, remainder in `conditions.uncredited_days` | UNB §6 step 8 |
| CPR-TST-12 | §5 AMB-15, -20, -21; SCN-09 (b), SCN-13 | Resolved. Tags: `account_status`, `l3_readonly`, `login_continuation`, `mfa_enrolment`, `consent`, `default`; data export (DSAR) is `account_status`, certificate list `l3_readonly`. Scope derived per request. Deferral: other sessions revoked immediately (`risk_L3`); attempt session keeps only that attempt's routes until submit or `deferred_until` | RE §7.2, §7.4 |
| CPR-TST-13 | §5 AMB-16; SCN-12 | Resolved: rejection refuses an early lift only; at `ends_at` the L3 auto-expires after re-verification and the rejected request closes as `moot` | UNB §4.3 |
| CPR-TST-14 | §5 AMB-17; SCN-07 | Resolved: no takeover "impossible travel" rule (by design); only TO-09 (first login from outside India, 15 points, notice). Expected for domestic geo jumps: SH-10 only (sharing, adults, broadband), ≤ 8 → L0 | RE §4.3 |
| CPR-TST-15 | §5 AMB-18; SCN-05 | Resolved: add variant 5c (sharer on mobile data only, OTP relayed) with the **expected under-detection** L0/L1 as an accepted outcome; add variant 5a (relay on fixed-line) expecting L3 | RE §11 rows 5a, 5c |
| CPR-TST-16 | §5 AMB-19; SCN-10 step 7 | Resolved: remove "CAPTCHA after 2nd per day"; expected = rate limits only (1 open per case, 3 per 30 days, 5 form loads/min) | UNB §3 |
| CPR-TST-17 | §5 AMB-11 | Resolved: ingest limits from `analytics-event-schema.md` §5.2 only; TM no longer states values | TM §2.7 |
| CPR-TST-18 | §4.1 mapping; §4.22; §13 I-02 | RE §11 now uses the owner numbering (rows 1–20 with sub-rows 5a–5c, 6a–6c, 9a–9f) and regression rows R-1..R-9. Update the "RE §11 scenario(s)" column accordingly and rename RX-01..RX-07 to R-1..R-7 (RX-06 credential stuffing is now RE row 9d) | RE §11 |
| CPR-TST-19 | §7 TS-RISK / TS-SEC / TS-PRIV, new cases | Add: kill switch (single approver → shadow within 60 s; ratification request created; not ratified in 24 h → page; no auto-revert; enforce → requires Dual); bulk lift (dry run counts; > 5,000 → 422; Dual; per-case decisions; no re-verification; excludes L4/high-risk/takeover); HMAC key rotation (old-version device lookup re-hashes; login search across versions); SH-13 detection; separation-class classification incl. Wi-Fi → mobile change mid-day; retention: `login_attempts` partition dropped only when its newest row is > 395 days old | RE §1.5, §4.2.1, §5.7, §5.8; PRIV §7 |
| CPR-TST-20 | Section H report tests | Use report ids H1–H12 + ENG per RE §10 | RE §10 |
| CPR-TST-21 | §13 I-03, I-05, I-08 | Mark I-03 (security AMBs), I-05 (registry) resolved; I-08 already resolved (PRIV §7 shows 35 days) | — |

## 6. `docs/deployment-and-operations.md` (DevOps)

| ID | Location | Change | Source |
|---|---|---|---|
| CPR-DEP-01 | §20 I-01; runbooks | Resolved as proposed, with two details: the emergency switch is SEC-42 (`security.engine.kill_switch`, P5) and creates a `risk.kill_switch.ratify` approval request; an unratified switch pages the security lead and super_admins after 24 h but is **not** reverted. Add runbook "False-positive surge": (1) kill switch to shadow or HC off, (2) bulk lift dry run, (3) Dual approval, (4) rule rollback request, (5) H8 review | RE §5.7, §5.8 |
| CPR-DEP-02 | §20 I-12; §15.4 retention jobs; log-group config | Resolved: **395 days**. S3 lifecycle for operational and security logs: Standard 180 d → Glacier IR → expire at 395 d. CloudWatch Logs retention: 400 days (nearest supported value ≥ 395). `login_attempts`, `session_network_observations` partitions dropped when the newest row is > 395 days; ended `auth_sessions` rows deleted at 395 days | PRIV §7, §7.1 |
| CPR-DEP-03 | §20 I-04; secrets inventory | Resolved: secrets `td/k_device/v{n}`, `td/k_login/v{n}` (KMS-generated, 32 bytes), readable by `api` and `worker-*` roles only; current versions in policy keys `security.keys.k_device.current_version`, `security.keys.k_login.current_version`; retired device keys kept 400 days, login keys 395 days; monthly `hmac_key_retire` job on the `maintenance` queue | RE §1.5; PRIV §7 |
| CPR-DEP-04 | §20 I-05 | Resolved: 8 years compliance-mode Object Lock for `td-audit-anchor` confirmed (anchors hold hashes only) | PRIV D17; TM §2.2 |
| CPR-DEP-05 | §20 I-06 | Resolved: Sentry SaaS allowed (EU region preferred) with `send_default_pii = false`, no IPs/cookies/headers/bodies, user = `subject_key`, email/phone scrubbing; listed as a processor in PRIV §10; self-host in ap-south-1 if counsel (P-8) objects | PRIV §10 |
| CPR-DEP-06 | §20 I-07 | Resolved: all personal-data backups ≤ 35 days in v1 | PRIV §7 |
| CPR-DEP-07 | §20 I-08 | Approved: job `sync_trusted_networks_to_waf` (owner `security`, runs on `worker-default`) on verification and daily; also a WAF challenge IP set fed from AB-04/AB-05 flagged sources (24 h TTL) | RE §4.5, §5.5 |
| CPR-DEP-08 | §20 I-15 | Endorsed: synthetic accounts excluded from SH/HC rules and security dashboards | RE §4.4 |
| CPR-DEP-09 | Alerting section | Add alert routes: AB-02 SMS spend and AB-12 signature bursts → ops on-call; AB-04 (> 500 failures/10 min), AB-07 (≥ 100/10 min), AB-09 → security lead; HC circuit breaker trip and unratified kill switch → security lead + super_admins | RE §4.5, §5.7 |
| CPR-DEP-10 | Redis section | Sessions use the `cache` cluster as a read-through copy (eviction harmless); circuit breaker falls back to Postgres for session and restriction reads; the `queue` cluster is not used for sessions | RE §1.6 |
| CPR-DEP-11 | `.env.example` / config tables | Remove any webhook "max age" setting used for rejection; keep `commerce.webhook.tolerance_seconds` as a monitoring threshold only | TM §2.4 |

## 7. `docs/role-permission-matrix.md` (Product Analyst)

| ID | Location | Change | Source |
|---|---|---|---|
| CPR-RPM-01 | §2.7 catalogue; §3 matrix | Add `policy.propose` — "Propose a `policy_settings` change in the `risk.*`, `sessions.*`, `devices.*`, `playback.*`, `assessment.*`, `login.*`, `otp.*`, `unblock.*` namespaces" — Sens; granted to `security_reviewer` (P). `policy.edit` stays super_admin (Up, Dual) | RE §3.1; API I-02 |
| CPR-RPM-02 | §2.2; §3 | Add `security.engine.kill_switch` — "Emergency move of `risk.mode` to shadow or HC rules off" — Up (P5), Sens, **single approver + post-hoc ratification within 24 h** (document as a named exception to Dual); `security_reviewer` P, `super_admin` P | RE §5.7 |
| CPR-RPM-03 | §2.2; §3; §5 | Add `security.restriction.bulk_lift` — "Bulk false-positive lift of engine-applied L3s" — Up (P5), Sens, **Dual**; `security_reviewer` P (requester); approver via `approval.decide` | RE §5.8 |
| CPR-RPM-04 | §2.7 `approval.decide` notes; §5 | List action types: `security.case.decision`, `security.restriction.bulk_lift`, `risk.kill_switch.ratify` (approver: a different `security_reviewer` or `super_admin`; never the requester or the person who applied the restriction) | UNB §5.1; RE §5.7, §5.8 |
| CPR-RPM-05 | §1.4 L3/L4 allowlist | Replace the allowlist wording with the tag model: `restricted` (L3) → routes tagged `account_status` + `l3_readonly`; `status_only` (L4) → `account_status` only (not 403 for everything; F-RPM-1). "Data export" (DSAR) = `account_status`; "certificate list" = `l3_readonly` | RE §7.2; AMB-15 |
| CPR-RPM-06 | §8 visibility M0 | Coordinator visibility of a student's restriction follows `org.notify_coordinator_on_restriction` (default `L4_status_only`: only L4 status shown); never signals | RE §3.2; API I-23 |
| CPR-RPM-07 | §2.2 | Endorse API I-03: add `security.incident.manage` (SEC-38/39) and `security.network.verify` (SEC-34) for `security_reviewer` | API I-03 |
| CPR-RPM-08 | §7 Separation of duties | Add SoD rule: the approver of a `security.case.decision` or bulk lift must differ from the requester and from the person who applied the restriction; a kill-switch ratifier must differ from the person who flipped it | UNB §5.1; RE §5.7 |

## 8. `docs/product-requirements.md` (Product Analyst)

| ID | Location | Change | Source |
|---|---|---|---|
| CPR-PRD-01 | §AC AC-COM-02 | Replace with: "**Given** a webhook with an invalid HMAC **Then** it is rejected (`400`, no state change) and logged (AB-12). **Given** a valid webhook that is a duplicate or arrives late (any age) **Then** it is acknowledged `2xx` and any state change is applied only from a server-side re-fetch of the entity, never twice." | TM §2.4; AMB-10 |
| CPR-PRD-02 | FR-SES-010 | Replace "idle extension up to 30 days for viewing" with "silent re-issue of a new (AAL1) session only on a top-level user navigation on a trusted device, within a fixed 30-day ceiling from the last full authentication; background requests never re-issue a session" | RE §1.4; AMB-06 |
| CPR-PRD-03 | AC-SES-02 | Append: "A session on the same browser profile is replaced, not counted. If every other session holds an active test attempt, the sign-in is refused (`session_cap_reached`) instead of evicting." | RE §6.3 |
| CPR-PRD-04 | FR-SEC-008, BR-ENT-12, AC-ENT-04 | Restate the remedy: credit = ceil(restricted days, including any L4 period of the same case) to every time-bound entitlement active during the restriction; institution-contract seats only up to the contract end (remainder recorded and handled by support); applies also when an `uphold` is later overturned (PO-10 to confirm) | UNB §6 step 8; AMB-14 |
| CPR-PRD-05 | AC-SEC-04 | Replace "only deterministic-cap signals are stored" with "only deterministic-cap signals and deterministic takeover signals (`family = takeover`, 0 points) are stored; no `risk_evaluations` rows of any family" | RE §4.4 |
| CPR-PRD-06 | FR-SEC-001; new FR-SEC-010 | FR-SEC-001: replace "from distinct networks" with "from physically separated networks (two fixed-line networks at the same time); OTP verification of a device does not discount such use". New **FR-SEC-010** (P1): "Configured high-confidence rules (HC-01, HC-02) may apply a temporary L3 automatically for adults; each rule runs ≥ 14 days in shadow, needs dual approval, can be switched off instantly (kill switch) and is returned to shadow automatically on a false-positive spike. Never L4, never minors." | RE §4.2.1, §5.6 |
| CPR-PRD-07 | FR-SEC-002a; §6 Rahul journey step 1 | L2 = "re-verification by SMS OTP/passkey/TOTP of every device in the evidence (email OTP not accepted) and revocation of sessions above the cap" (not "forced logout of other sessions"). Journey step 1: "other sessions above the cap revoked and the devices involved must re-verify" | RE §6.1 |
| CPR-PRD-08 | §8.5 security dashboard (SEC-001) | Number the widgets/reports H1–H12 + ENG as in RE §10 (H4 = network-cluster associations incl. CGNAT watch; H10 active sessions; H11 activity context) | RE §10; API I-15 |
| CPR-PRD-09 | FR-IDN-009 | Append: "A hard-disabled account receives the same `invalid_credentials` response as any failed login; the verified contact gets an out-of-band message with a reset link" | API I-21 |
| CPR-PRD-10 | FR-SES (new AC) | Add AC-SES-04: "**Given** a timed test in progress **When** the student does not interact for longer than the idle timeout **Then** the session stays valid until the attempt deadline + grace + 5 min." and AC-SES-05: "**Given** the browser crashes and the student signs in again on the same browser profile **Then** the attempt resumes without using a rebind." | RE §1.4, §7.4 |
| CPR-PRD-11 | NFR / Terms note (PO-02) | Add to the published device-policy text: "Verifying a device with a code does not exempt simultaneous use from two different home or college networks" | RE §4.2.1 |

## 9. `docs/system-architecture.md` (System Architect) — additional target

| ID | Location | Change | Source |
|---|---|---|---|
| CPR-ARC-01 | §6.3 `require_active_principal` code and the `restriction_class` paragraph (≈ lines 323–345) | Replace `restriction_class` (`appeal`, `self_service_minimal`) with `x-td-route-tag` using the canonical tags; drop "declared inside `security`, `identity`, `support` modules only"; CI checks the tag and `x-td-idle` on every authenticated route | RE §7.2; API I-07; AMB-15 |
| CPR-ARC-02 | §6.3 `touch()` | `touch()` slides idle only for `x-td-idle: extends`; add `sessions.touch_engaged(session_id)` called by analytics ingest and the playback heartbeat; honour `idle_hold_until` | RE §1.4; AMB-05 |
| CPR-ARC-03 | §6 concurrency row (≈ line 312) | "confirming revokes the **oldest**" → "pre-selects the oldest session without an active attempt; same-browser-profile sessions are replaced first (`replaced_same_device`); never evicts an attempt-holding session" | RE §6.3 |
| CPR-ARC-04 | §6.2, §8.5 | Remove the Redis "take over" lock / `session_takeover`; use `bound_session_id`/`bound_device_id`, events `rebind_requested`, `rebind`, `rebind_refused`, `reattach_same_device` (API I-06) | RE §7.4 |
| CPR-ARC-05 | §6.1 device token | 128-bit `__Host-td_device`, stored as `HMAC-SHA256(k_device_v{n})` with `key_version` (API I-19) | RE §1.5 |
| CPR-ARC-06 | §11.2 webhooks | Every state-changing event re-fetched from the provider; no age rejection; `is_stale` monitoring only | TM §2.4 |

## 10. `docs/analytics-event-schema.md` (Analytics Engineer) — additional target

| ID | Location | Change | Source |
|---|---|---|---|
| CPR-ANL-01 | §5 ingest handler | After crediting a batch, if credited active seconds > 0 for the requesting session, call `sessions.touch_engaged(session_id)`; keepalive-only batches never call it | RE §1.4 |
| CPR-ANL-02 | Outbox/feeds table row `analytics.plausibility_violation` (≈ line 305) | State that security records it as integrity signal **IN-01** (implausible day) or **IN-02** (ingest forgery bursts), which are **not** inputs to any sharing score for any user; keep "security-necessary log" wording | RE §4.5; AMB-04 |
| CPR-ANL-03 | §5.2 | Mark §5.2 as the single authoritative source of ingest rate, cadence and page-instance limits (TM and API reference it) | AMB-11 |

---

## Count of change requests by target file

| Target file | Requests |
|---|---|
| blueprint-brief | 12 |
| database-schema | 15 |
| database-erd | 4 |
| api-specification | 16 |
| testing-and-acceptance-criteria | 21 |
| deployment-and-operations | 11 |
| role-permission-matrix | 8 |
| product-requirements | 11 |
| system-architecture (additional) | 6 |
| analytics-event-schema (additional) | 3 |
| **Total** | **107** |
