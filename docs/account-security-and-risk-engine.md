# Account Security & Risk Engine — Tech Drona LMS

> **Single-company note (2026-11-06).** Tech Drona now runs as a single company ([ADR-0015](architecture-decisions/ADR-0015-single-company.md)); the college/B2B features described in this document (college portal and coordinators, institution contracts and seats, invitations and roster import, per-organization settings, trusted networks and lab devices, the "For colleges" page) are removed. Roles are Admin (`super_admin`), Trainer, Evaluator, Content manager and Student; finance, support, security and mentor duties belong to Admin. Batches are Tech Drona cohorts managed by Admin at `/admin/batches`; businesses use the corporate enquiry form at `/enquiries`. Trusted networks, lab/shared-device exemptions and coordinator notifications are removed; reviewer duties (two-person rules) are performed by two different Admins. Where this document conflicts, ADR-0015 and [`single-company/REMOVAL-PLAN.md`](single-company/REMOVAL-PLAN.md) §8 win.

| | |
|---|---|
| Owner | Security & Account Monitoring Specialist |
| Contract | `docs/blueprint-brief.md` v0.2 (binding); `docs/contract-reconciliation.md` |
| Research basis | `research/reference-platform-analysis.md` (cited as **RPA §n**), research notes `account_sharing_prevention.md` (**ASP**), `owasp_auth_session_security.md` (**OWASP-N**), `india_privacy_dpdp.md` (**DPDP-N**) |
| Status | Every item in this document is **Planned** |
| Companion docs | `account-unblock-workflow.md`, `security-threat-model.md`, `privacy-and-data-retention.md`; change requests for other owners: `consistency-pass-requests.md` |

Evidence labels follow the research: **[Verified]** = primary source, **[Reported]** = secondary or observed, **[Rec]** = our design choice. Unless a line is marked otherwise, the numbers in this document are **[Rec]** defaults held in `policy_settings`.

## Changelog

### v0.4 — 2026-11-03 (Security Specialist, final cleanup)

- **Owner-verification refresh** (AMB-22): `owner_verified_at` is refreshed by every SMS-OTP, passkey or TOTP challenge completed on the device; a pre-expiry "Keep this device verified" prompt (`risk.owner_verification.refresh_prompt_days`) prevents silent lapses; worked example A restated (§3.2, §4.2.1, §5.1).
- **`risk.mode` scope** (AMB-23): `shadow`/`off` and the kill switch govern the sharing family only; takeover protections, deterministic caps and AB-*/IN-* controls always enforce (§3.2, §5.7).
- **Circuit-breaker edge cases** (AMB-24): FP test with fewer than `min_decisions` decided, and the excess restriction is never applied (§5.7).
- **Export approval** (API I-26): security/monitoring exports approved by a second `security_reviewer`; other exports by `super_admin` (§10). Dashboard access for `super_admin` limited to aggregate views (§10).
- IPR-SEC-02: report keys listed per H view (§10); IPR-SEC-04: AB-12 path `/api/v1/webhooks/{provider}` (§4.5). IPR-SEC-01, -03, -06 confirmed already applied (§3.1, §5.5/§12, §6.3/§7.3).

### v0.3 — 2026-11-03 (Security Specialist, review pass)

Resolves the security-domain items raised in `testing-and-acceptance-criteria.md` §5 (AMB-01..21) and §13, `api-specification.md` §27 and `deployment-and-operations.md` §20. Changes needed in documents owned by others are listed in `consistency-pass-requests.md` (CPR-*).

- **Owner verification no longer cancels sharing evidence** (AMB-01, AMB-18). SH-01 weight now depends on the *network separation class* of the overlapping pair (§4.2.1), not on OTP verification alone. Physically separated use (two distinct fixed-line networks at the same time) is never discounted. New signal **SH-13** counts verifications completed on a distant network while the account is in use elsewhere (OTP relay). The L3 gate now requires separated-use evidence instead of "an unverified device". Worked examples and §11 recomputed.
- **High-confidence rules** HC-01, HC-02 (sharing, auto-L3) and HC-T1..T3 (takeover, protective) defined, with shadow-first activation, a per-rule enable switch and an automatic circuit breaker (§5.6; owner scenario 9, AMB-03).
- **Stolen-cookie replay** (TO-04/TO-08): the replayed session is revoked immediately and a takeover evaluation runs; all sessions are revoked only when a confirming takeover signal is present (§4.3, §6.2; AMB-02).
- **Idle timeout and remember-device** semantics defined (§1.4; AMB-05, AMB-06, AMB-07). Session store and Redis-miss behaviour defined (§1.6; AMB-09).
- **Crash recovery** on the same device re-attaches the attempt without consuming a rebind; attempt-bound sessions are never evicted (§6.3, §7.4; AMB-08).
- **Abuse and integrity rule registry** AB-01..AB-12 and IN-01..IN-03 with thresholds, scoring and alert routing (§4.5; AMB-04).
- **Canonical route tags** aligned with `api-specification.md` §1.4; session scope derived per request (§7.2; AMB-15, AMB-20). L3 deferral semantics (AMB-21).
- **Kill switch, circuit breaker and bulk false-positive lift** (§5.7, §5.8; deployment I-01, I-02). **HMAC key versioning** for `k_device` / `k_login` (§1.5; deployment I-04).
- Minors: no `risk_evaluations` rows of any family (§4.4; AMB-12). Takeover "impossible travel" explicitly not used (§4.3; AMB-17).
- Section H views renumbered to the verbatim owner list H1–H12 (§10; API I-15). §11 re-keyed to the owner's scenario numbering (testing I-02).
- Policy permissions renamed to `policy.edit` / `policy.propose` (API I-02).

### v0.2 — 2026-11-03

Reconciliation follow-ups F-SEC-1..4 applied (`contract-reconciliation.md` §6).

---

## 0. Design principles

1. **Deterministic caps first, scoring second.** The server-side caps on sessions, streams, devices and assessment binding are the primary control. They are unambiguous, explainable and lawful for every user, minors included. Behavioural scoring only adds evidence for adults. Concurrent sessions are the most reliable signal and IP is the least reliable (RPA §3, [Verified] Cloudflare: one IPv4 address "may represent hundreds or even thousands of users").
2. **Remedy before penalty.** The order is notice, then step-up OTP, then temporary restriction, then human-reviewed suspension. This mirrors the remedy-first patterns at Netflix, Disney+, Spotify and Adobe (RPA §3 [Verified]/[Reported]).
3. **Never act on IP or fingerprint alone.** Network signals can never push a score past L1, and fingerprints are capped at 10 points (brief §1, risk engine). The reason is DPDP s.8(3): personal data used in a decision affecting a person must be accurate (RPA §3 [Verified]). Network *context* is used only to classify how far apart two already-proven concurrent uses are (§4.2.1); it never creates evidence on its own.4. **Explainability.** Every evaluation stores its inputs, the rule version, the score and the action. Students see the reason in plain language, and reviewers see the evidence.
5. **Minors.** Under-18 accounts receive no behavioural scoring, no sharing profiling and no fingerprinting. Only deterministic caps and security-necessary logs apply (brief §1; DPDP s.9(3), RPA §8 [Verified]).
6. **Single enforcement chokepoint.** Every authenticated router goes through `require_active_principal` (brief §5). No route opts in on its own.
7. **Verification proves possession, not single-person use.** An OTP proves that someone could read the owner's inbox or phone at that moment; the owner can relay it to a sharer. Verification therefore clears L2 and resolves *ambiguous* overlaps, but never cancels evidence of physically separated simultaneous use (§4.2.1).

---

## 1. Session and device tracking

### 1.1 Identities involved

| Concept | Identifier | Where it lives | Lifetime |
|---|---|---|---|
| Auth session | `__Host-td_session` cookie: 256-bit CSPRNG value, base64url. The server stores only `SHA-256(token)` | Postgres `auth_sessions` (source of truth) plus Redis `cache` read-through `sess:{hash}` (§1.6) | Idle and absolute timeouts per tier (brief §1, §1.4). Cookie `Max-Age` = seconds until `absolute_expires_at`, so the cookie survives a browser crash or restart; registered lab devices get a browser-session cookie (no `Max-Age`) |
| Remember-device credential | `__Host-td_remember` cookie: 256-bit CSPRNG, rotated on every use | `user_devices.remember_token_hash` (SHA-256) + `remember_until` | Fixed `remember_until` ≤ 30 days from the last full authentication; never slides (§1.4) |
| Device | `__Host-td_device` cookie: 128-bit CSPRNG random ID, base64url. On mobile apps, an install ID held in Android Keystore or iOS Keychain | `devices.device_key_hash = HMAC-SHA256(k_device_v{n}, raw_id)` with `devices.key_version = n` (§1.5). The raw ID is never stored | Cookie Max-Age 400 days (the browser cap), refreshed on use |
| User–device trust | `user_devices` row: (user_id, device_id) | Postgres | Trust expires after 90 days of inactivity (`devices.trusted_inactivity_expiry_days`) |
| Tab | `tab_id`: a random UUID in `sessionStorage`, sent only on heartbeat and playback calls | Not persisted beyond `activity_heartbeats` | Life of the tab |
| Playback session | `playback_sessions` row, created when a VdoCipher OTP is issued | Postgres plus Redis `play:{user_id}` set | Ends on a stop event or after 90 s with no heartbeat |
| Optional fingerprint | `fp_hash = HMAC-SHA256(k_fp_epoch, canonical(coarse_attrs))` | `devices.fp_hash`, `fp_epoch` | Key rotated every 90 days, so hashes cannot be linked across epochs |

**Device cookie rules.** The cookie is `__Host-td_device=<id>; Secure; HttpOnly; SameSite=Lax; Path=/; Max-Age=34560000`. It is issued on the first visit to any authenticated surface, whether login or signup, and never on marketing pages. It carries no PII. Login is never blocked because the cookie is missing: the server issues a new one and treats the browser as a *new device*. The cookie identifies a browser profile, not a person, and the privacy notice says so.

**Optional fingerprint (Phase 2, adults only, off by default, `risk.fingerprint.enabled=false`).** The fingerprint is computed client-side from coarse, low-entropy attributes only:
- platform and OS family;
- screen-size bucket;
- timezone;
- primary language;
- `hardwareConcurrency` bucket;
- a WebGL vendor string truncated to the vendor name.

It uses no canvas or audio hashing and no font enumeration. Its **primary use is to reduce false positives**: it lets the engine recognise that two browser profiles are "probably the same physical machine" (case 2 in §2). Its secondary use is to re-link a device after the user clears cookies, which carries weight ≤5. It is never used for blocking, cross-site tracking or advertising. Evidence on fingerprint drift: changes occur "every few hours to days", with an average linkability of 54.48 days (FP-STALKER, RPA §3 [Verified academic]).

### 1.2 Fields captured per session (`auth_sessions`)

| Field | Type | Notes |
|---|---|---|
| `id` | uuid v7 | Internal ID. Never the token |
| `user_id`, `organization_id` (nullable) | uuid | `organization_id` = the active tenant context |
| `token_hash` | bytea(32) | SHA-256 of the session token. Unique |
| `device_id` → `devices.id`, `user_device_id` → `user_devices.id` | uuid | |
| `client_type` | enum `web`/`android`/`ios` | |
| `session_tier` | enum `student`/`staff`/`privileged` | Sets the timeouts: 60 min/24 h, 30 min/12 h, 15 min/8 h (name per brief v0.2 §1; originally proposed as `role_tier`) |
| `scope` | enum `full`/`restricted`/`status_only` | `restricted` for L3, `status_only` for L4 (§7.2, brief v0.2 §5). **Enforcement derives scope per request** from the restriction cache `restr:{uid}` (§7.2 step 7); this column is a record, written at creation and updated when a restriction is applied or lifted, for audit and reporting only (AMB-20) |
| `status` | enum `pending_mfa`/`pending_device_otp`/`pending_session_choice`/`active`/`expired`/`revoked`/`blocked` | `blocked` per source requirement Section A (`database-schema.md` §4). `pending_session_choice` = the user must pick a session to end at the concurrency cap (CPR-SCH-03) |
| `aal` | smallint 1–3 | Not higher than the creating authentication event (NIST, OWASP-3) |
| `amr` | text[] | e.g. `{pwd,otp_sms}`, `{passkey}` |
| `auth_time`, `last_step_up_at` | timestamptz | Used for step-up checks (windows 5 / 10 / 15 min per brief v0.2 §1, OWASP-4) |
| `created_at`, `last_seen_at` | timestamptz | `last_seen_at` is written at most once per 60 s |
| `idle_expires_at`, `absolute_expires_at` | timestamptz | Authoritative on the server, never cookie expiry |
| `remember_device` | bool | Only on trusted devices; max 30 days; AAL1-equivalent (brief §1) |
| `ip_first`, `ip_last` | inet | Full IP, kept for security logs (Rule 6 one-year minimum; purged at 13 months, privacy §7). UI and default views show /24 (IPv4) or /48 (IPv6) |
| `net_cluster_first`, `net_cluster_last` | text | `ASN:prefix`, e.g. `AS55836:49.36.0.0/16`, used for "same or different network" comparisons |
| `asn`, `network_type` | int, enum `mobile`/`broadband`/`hosting`/`vpn_proxy`/`tor`/`education`/`unknown` | From an offline ASN/IP-type database |
| `geo_country`, `geo_region` | char(2), text | Country and state only. **No city** at the risk layer (unreliable in India, RPA §3) |
| `ua_family`, `ua_major`, `os_family`, `device_class` | text | Parsed from the UA and client hints. The raw UA is stored only as `ua_hash` |
| `app_version` | text | Mobile apps only |
| `restriction_level_at_issue` | smallint | Snapshot taken at creation |
| `ended_at`, `end_reason`, `ended_by` | timestamptz, enum, uuid | Set for every ended session, expiry included (logout time and termination reason). See §8 |
| `created_via` | enum `password`/`otp_login`/`passkey`/`sso`/`recovery`/`unblock_reauth`/`remember_device` | `remember_device` = silent re-issue under §1.4 rules (AAL1; `auth_time` copied from the original full authentication) |
| `idle_hold_until` | timestamptz null | Set while the session holds an in-progress timed attempt: `deadline_at + grace + 5 min`. Idle expiry is not enforced before it (§1.4 rule 4) |

**Per-request telemetry** stays in operational logs, not in the session row: `request_id`, route template (not the full URL with query), status, latency, `session_id` (internal UUID, never the token), `ip`, `asn`. These are retained for 13 months (395 days; see the privacy doc §7).

**Network observations per session.** Because a session can move between networks (Wi-Fi to mobile data, owner scenario 4), `ip_first`/`ip_last` are not enough to know where a session was during a given 5-minute bucket. `require_active_principal` therefore writes a `session_network_observations` row (owner `sessions`; CPR-SCH-04) whenever the request's network cluster differs from the session's current one, at most once per 60 s per session: `auth_session_id`, `user_id`, `net_cluster`, `asn`, `network_type`, `geo_region`, `first_seen_at`, `last_seen_at`. The risk engine maps each engaged bucket to the observation covering it. Partitioned monthly; retention R-SEC (13 months).

**Engagement heartbeats** (owned by the Analytics Engineer) arrive in `activity_heartbeats`. The risk engine never queries that table directly: it calls `analytics.feeds.get_engaged_buckets(user_id, from, to)`, which returns `(device_id, auth_session_id, bucket_5min, activity_kind)` only for adults with an active `security_monitoring` consent (brief v0.2 §2; analytics §6.5). The raw window is limited by heartbeat retention (35 days); signals keep their own evidence.

### 1.3 Never logged or stored

| Item | Rule |
|---|---|
| Raw session tokens, CSRF secrets, device-cookie raw values, refresh tokens, VdoCipher OTPs | Never logged. Only HMAC or SHA-256 values are stored |
| Passwords, password hints, OTP codes, TOTP secrets, recovery codes (plaintext) | Never logged. Hashed where storage is required |
| Precise location (GPS, Wi-Fi BSSID), city-level geolocation in risk records | Never collected. Netflix states "we do not collect GPS data" (RPA §3 [Verified]) |
| Hardware identifiers: IMEI, MAC, serial number, Android ID, advertising IDs (GAID/IDFA) | Never collected |
| Canvas, audio or font fingerprints, keystroke dynamics, mouse movement biometrics, webcam or screen media | Never collected in v1 |
| Contact lists, installed-apps lists, browsing history outside Tech Drona | Never collected |
| Answer content, code content, payment card data in security logs | Never. Security logs reference IDs only. Card data is never stored at all (RBI) |
| Fingerprint attributes in the clear | Never. Only `fp_hash` per epoch |
| Any behavioural risk features for users with `is_minor = true` | Not computed and not stored (§4.4) |

### 1.4 Session lifetime: idle, absolute and remember-device (AMB-05, -06, -07)

The brief's rule is that the idle timer is extended only by engaged activity and never by analytics keepalives. It is implemented by classifying every authenticated route with an **idle effect**, declared next to the route tag (`openapi_extra={"x-td-idle": ...}`; a CI test fails if an authenticated route has none).

| `x-td-idle` | Meaning | Routes (examples) |
|---|---|---|
| `extends` | A user-initiated request. Slides `idle_expires_at` | Every state-changing route not listed below (answer save with a changed answer, code run/submit, notes, purchases, settings); `GET` page-data requests that the BFF marks as a user navigation (`X-TD-Activity: navigation`, set only by the BFF from `Sec-Fetch-Mode: navigate` or an App Router client navigation, never from prefetch: `Sec-Purpose: prefetch` is ignored) |
| `engaged_only` | Extends idle **only** when the server confirms engagement in this request | `POST /analytics/events` and `/analytics/events/beacon`: extends only if the batch is credited > 0 active seconds by the analytics crediting rules (AN §3); the ingest handler calls `sessions.touch_engaged(session_id)`. Playback heartbeat: extends only when `state = playing` and the position advanced. Attempt autosave: extends only when at least one response changed |
| `neutral` | Never extends idle | Keepalive heartbeats, notification polling and SSE, `GET /me/security/status` polling, session-status checks, background refreshes, prefetches, idempotent replays |

Rules:
1. **Server decides.** The client cannot extend idle by setting a header: `X-TD-Activity` is accepted only on the BFF→API hop (private network, mTLS/IAM) and is stripped from browser requests by the BFF.
2. **Absolute timeout is never extended** by activity. It is set at full authentication.
3. **Background requests after idle expiry** get `401 session_expired` (`reason = idle_timeout`); the client stops background traffic and shows the signed-out overlay. A background request never triggers a remember-device re-issue.
4. **Timed assessments keep the session alive.** When an attempt is started or re-attached on a session, `idle_hold_until = deadline_at + grace + 5 min`. Until then idle expiry is not enforced on that session, whatever the input pattern (a student reading a long passage). Before an attempt starts, if `absolute_expires_at < deadline_at + grace + 5 min` the start is refused with `409 session_too_short_for_attempt` (`reauth_url`); the student re-authenticates (a fresh session with a new absolute window, no rebind involved because the attempt has not started). Absolute timeouts are never extended.
5. **Remember-device refresh** (students, trusted devices only, never staff/privileged or lab devices). When a session on a remembered device has idle- or absolute-expired, a new session may be issued silently only if **all** hold:
   - the triggering request is a **top-level user navigation** (`Sec-Fetch-Mode: navigate` and `Sec-Fetch-User: ?1`, or a click on the signed-out overlay); never an XHR, heartbeat, beacon or prefetch;
   - `__Host-td_remember` matches `user_devices.remember_token_hash`, `now < remember_until`, and the device is still `trusted` with the same `device_key_hash`;
   - the user is not at restriction ≥ L3, not T-protect locked, and `remember_issued_at > users.sessions_valid_after`.
   The new session gets a new token, `created_via = remember_device`, `aal = 1`, `auth_time` copied from the original full authentication (so payments, contact changes, device management and attempt starts more than 24 h after that authentication require re-authentication, PRD FR-SES-010). The remember token is rotated on each use; presenting a superseded remember token revokes the remember credential and records **TO-10** (§4.3). `remember_until` is fixed at the last full authentication and **never slides**; after it passes, a full login is required.
6. **Session cookie lifetime.** `__Host-td_session` carries `Max-Age` = seconds until `absolute_expires_at` (lab devices: no `Max-Age`). A browser crash therefore does not normally lose the session (owner scenario 16, case A).

### 1.5 Keyed-hash key versioning (`k_device`, `k_login`) (deployment I-04)

| Key | Used for | Version column | Rotation | Lookup during rotation |
|---|---|---|---|---|
| `k_device_v{n}` | `devices.device_key_hash` | `devices.key_version smallint` | Planned every 24 months; immediately on suspected compromise | Compute with the current version; on a miss, retry with each version still in its lookup window (oldest first, max 2 extra versions). On a hit with an old version, **re-hash in place** (`device_key_hash`, `key_version` updated in the same transaction). Old versions stay usable for lookup for 400 days (the device-cookie Max-Age), then are destroyed |
| `k_login_v{n}` | `login_attempts.identifier_hash` (HMAC of the normalised email or phone) | `login_attempts.key_version smallint` | Planned every 24 months; immediately on suspected compromise | Rows are append-only and never re-hashed. Searches by identifier compute one hash per live version. Old versions are destroyed 395 days after retirement (when the last row they protect is purged) |
| `k_fp_epoch` | `devices.fp_hash` | `devices.fp_epoch` | Every 90 days (unchanged) | No cross-epoch lookup by design |
| `k_analytics_vN` | `subject_key` | in the key name | Yearly (privacy §8) | — |

Keys live in AWS Secrets Manager (`td/k_device/v{n}`, `td/k_login/v{n}`), are generated in KMS, are readable only by the `api` and `worker-*` task roles, and every version change is a 🔒 platform policy change (`security.keys.k_device.current_version`, `security.keys.k_login.current_version`) requiring dual approval, except an emergency rotation after compromise, which follows the kill-switch path in §5.7 (single approver + 24 h ratification). An emergency rotation leaves old-version lookups enabled (they are needed to avoid treating every browser as a new device) but raises an alert on each old-version hit for 30 days.

### 1.6 Session store and cache misses (AMB-09)

- **Postgres `auth_sessions` is the source of truth.** Redis `cache` holds a read-through copy `sess:{hash}` with TTL ≤ idle remaining. Eviction from `cache` is harmless.
- On a Redis miss, `require_active_principal` reads `auth_sessions` by `token_hash` (unique index) and re-populates the cache. Only when the token is unknown to **both** does the request get `401 unauthenticated` ("strict mode": an unknown ID never creates or adopts a session; counted by **AB-07**).
- **Revocation** is a DB update first, then `DEL sess:{hash}`; `users.sessions_valid_after` (also cached in `restr:{uid}`, DB fallback on miss) guarantees that a missed `DEL` cannot resurrect a session.
- **Redis unavailable:** a circuit breaker routes session and restriction reads to Postgres (p95 budget +5 ms). Rate limiting falls back to a coarse per-task in-memory limiter; login keeps working. The `queue` cluster (`noeviction`) is not used for sessions.

---

## 2. Distinguishing the seven usage cases

| # | Case | How the server sees it | Counted as | Treatment |
|---|---|---|---|---|
| 1 | **Multiple tabs**, same browser | Same `__Host-td_session` and `__Host-td_device`; different `tab_id` | 1 session, 1 device | No signal. Video: a second tab playing takes over the stream *within the same session* silently (the old tab gets a "playing in another tab" overlay). Assessment: the attempt is bound to the session, so both tabs work, and the client uses BroadcastChannel to show "already open in another tab" |
| 2 | **Multiple browsers on one device** (Chrome + Edge) | Different device cookies; same `net_cluster`; same OS. If the fingerprint is enabled, `fp_hash` usually matches | 2 sessions and **2 devices** (documented: "each browser counts as a device") | Caps apply as normal. Overlap between them is separation class **S0 same-machine** (§4.2.1): weight 0 when `fp_hash` matches, otherwise ×0.1 when net cluster, OS family and device_class all match. The "Your devices" UI groups them as "probably this computer" |
| 3 | **Multiple devices, sequential** (laptop by day, phone by night) | Distinct device IDs; no overlap of engaged heartbeats | Within the 3-device trust limit | No signal. A new device triggers a one-time OTP (brief §1) |
| 4 | **Multiple devices, simultaneous** (laptop playing video while the phone is open) | 2 live sessions; engaged heartbeats overlap | Within 2 concurrent sessions; 1 stream | Deterministic caps. Typical one-person patterns are both devices on the home network (class **S1 co-located**, ×0.1) or laptop on Wi-Fi and phone on mobile data (class **S2 indeterminate**, ×0.1 when both devices are owner-verified, ×0.3 otherwise). Steady daily use stays at L0 (§5.1). L3 is unreachable from S0–S2 overlaps alone (§5.3 gates require S3 evidence) |
| 5 | **Many accounts on one device** (family PC, college lab, cyber café, reseller) | One `devices` row with many `user_devices` rows | Per-account device counts as normal | If the device is registered as a **shared lab device** (§5.5), no signal. Otherwise SH-11 (low) on each account at ≥4 accounts in 7 days. Combined with a hosting ASN or rapid churn, it raises review priority (reseller pattern) |
| 6 | **One account, many people** (credential sharing) | Overlapping engaged activity on ≥2 device tokens, often on distinct networks, repeated over days; device churn; abandoned new-device OTPs | Multiple devices; cap hits | The strongest combined evidence (RPA §3 [Rec]; ASP §3). Scored by SH-01 to SH-08 and SH-13. Overlaps on two distinct fixed-line networks at the same time are class **S3 separated** (×1.0, never discounted by verification). L3 is gated on multi-day, multi-category, separated-use evidence (§5.3) or reached through high-confidence rule HC-01/HC-02 (§5.6). An owner who relays OTPs to the sharer still accumulates S3 and SH-13 evidence |
| 7 | **Shared networks** (college NAT, hostel Wi-Fi, Jio/Airtel CGNAT, VPN) | Many users per IP; IPs rotating; geolocation wrong | Not counted at all. IP is never an identity | Network signals capped at a total of 20 points. Coordinator-registered trusted ranges get weight 0. Per-IP login rate limits are relaxed ×10 for registered campus ranges and known CGNAT ASNs. Sessions are never bound to IP (OWASP Session CS, RPA §3 [Verified]) |

**"Engaged" activity**, used for overlap, means a 5-minute bucket that contains at least one of:
- a playback heartbeat;
- an attempt or practice answer save;
- a code run or submit;
- reading heartbeats with `visibilityState=visible` plus input within 60 s.

Idle open tabs do not count. Overlap requires at least **3 overlapping buckets (15 min) on the same calendar day (IST)** before it is recorded.

---

## 3. Configurable policies (`policy_settings`)

### 3.1 Resolution model

- **Precedence**, from strongest to weakest:
  1. user exception (time-bound, created only through a case decision);
  2. organization;
  3. plan;
  4. platform default.
- Every key has `min`/`max` bounds and flags (`org_overridable`, `plan_overridable`, `locked`). Overrides outside the bounds are rejected.
- Changes require `policy.edit` (super_admin, step-up P5, Dual via `approval_requests`); `security_reviewer` holds `policy.propose` for the `risk.*`, `sessions.*`, `devices.*`, `playback.*`, `assessment.*`, `login.*`, `otp.*` and `unblock.*` namespaces (API I-02; CPR-RPM-01). Changes are versioned (`version`, `effective_from`), audited, and take effect within 60 s, the Redis cache TTL.
- Keys marked 🔒 are **locked**: no override exists below the platform level, and changing the platform value needs dual approval. **Single exception:** the emergency kill switch (§5.7) may move `risk.mode` from `enforce` to `shadow`, or set `risk.hc.auto_restrict_enabled = false`, with one approver and mandatory ratification within 24 h. Moving *towards* enforcement always needs dual approval.

### 3.2 Knobs and defaults

| Key | Default | Bounds | Org | Plan | Notes |
|---|---|---|---|---|---|
| `sessions.student.max_concurrent` | 2 | 1–5 | ✓ | ✓ | Brief §1 |
| `sessions.student.at_limit_behavior` | `prompt_choose` | `prompt_choose`/`evict_oldest`/`deny` | ✓ | | `prompt_choose` lists the other sessions and lets the user pick which to end. A non-interactive client gets `evict_oldest` |
| `sessions.staff.max_concurrent` | 3 | 1–5 | | | |
| `sessions.student.idle_minutes` / `absolute_hours` | 60 / 24 | 15–60 / 4–24 | ✓ (tighten only) | | Brief §1 |
| `sessions.remember_device.max_days` | 30 | 0–30 | ✓ (tighten only) | ✓ | Trusted devices only; reauthentication for payments and profile changes |
| `devices.student.max_trusted` | 3 | 1–10 | ✓ | ✓ | Brief §1 |
| `devices.student.max_replacements_per_30d` | 2 | 0–10 | ✓ | ✓ | A replacement is removing a trusted device to add a new one. Rolling 30 days |
| `devices.new_device_verification` | `otp` | `otp`/`otp_plus_email_notice` | | | OTP goes to the registered phone or email, whichever is verified. Passkey or TOTP is accepted in place of OTP |
| `devices.trusted_inactivity_expiry_days` | 90 | 30–180 | ✓ | | An expired device frees its slot automatically and does **not** consume a replacement |
| `playback.max_concurrent_streams` | 1 | 1–3 | ✓ | ✓ | Brief §1 |
| `playback.heartbeat_seconds` / `stale_after_seconds` | 30 / 90 | 15–60 / 60–180 | | | |
| `playback.takeover_behavior` | `prompt_takeover` | `prompt_takeover`/`deny` | ✓ | | "Play here instead" ends the other stream |
| `playback.otp_ttl_seconds` | 300 | 60–900 | | | VdoCipher OTP validity for starting playback |
| `assessment.single_device_binding` | true | — 🔒 for proctored drives | ✓ | | The attempt is bound to one session |
| `assessment.max_rebinds_per_attempt` | 2 | 0–5 | ✓ | | Lets a student move to **another device** after a crash or power cut. A re-attach from the same `device_id` is not a rebind and never consumes this quota (§7.4) |
| `assessment.idle_hold_extra_minutes` | 5 | 0–15 | | | Added to `deadline_at + grace` for `idle_hold_until` (§1.4 rule 4) |
| `assessment.rebind_requires_otp_at_level` | `L2` | `L0`–`L3` | ✓ | | At or above this level, a rebind needs OTP |
| `risk.mode` | `shadow` at launch; `enforce` after the pilot shadow report is dual-approved | `off`/`shadow`/`enforce` 🔒 | | | Platform only. **Governs the sharing family only** (SH scoring, L1–L3 actions, HC-01/HC-02): `shadow` records sharing evaluations without actions; `off` stops sharing evaluations and needs dual approval. Emergency move to `shadow` per §5.7. Takeover protections (TO-*, HC-T1..T3, replay revoke, T-step-up, T-protect), deterministic caps (§6.3) and AB-*/IN-* controls **always enforce in every mode**, because they protect the user (AMB-23) |
| `risk.hc.auto_restrict_enabled` | **false** at launch | bool 🔒 | | | Master switch for HC-01/HC-02 auto-L3 (§5.6). Set true only after the HC rules complete ≥14 days of shadow with the circuit-breaker metrics below the limits, by dual approval |
| `risk.hc.circuit_breaker.max_fp_rate` / `min_decisions` | 0.05 / 20 | 0.01–0.2 / 10–100 | | | Per HC rule: if `lift_false_positive` decisions exceed this share of the last `min_decisions` decided HC-applied restrictions, that rule reverts to `shadow` automatically (§5.7) |
| `risk.hc.circuit_breaker.max_daily_restrictions` | 50 | 5–500 | | | Per HC rule: more auto-L3s than this in a rolling 24 h trips the breaker (spike protection) |
| `risk.window_days` | 30 | 14–60 | | | |
| `risk.decay_half_life_days` | 7 | 3–14 | | | |
| `risk.threshold.L1` / `L2` / `L3` / `L4_recommend` | 25 / 45 / 70 / 90 | ascending, 10–100 | | ✓ (raise only) | |
| `risk.L3.min_categories` | 2 | 2–3 | | | Concurrency, device and network categories |
| `risk.L3.min_distinct_days` | 3 | 2–7 | | | Days with concurrency evidence within 14 days |
| `risk.L3.min_separated_days` | 2 | 1–7 | | | Days within 14 with at least one S3 (separated) overlap or SH-13; replaces the former "at least one device not owner-verified" gate (§5.3) |
| `risk.L3.duration_hours` | `[24, 72]` | 12–168 | | | First restriction, then a repeat within `risk.repeat_window_days` |
| `risk.repeat_window_days` | 180 | 90–365 | | | |
| `risk.network_points_cap` | 20 | 0–25 🔒 (must stay < L2) | | | Enforces "never on IP alone" |
| `risk.fingerprint.enabled` | false | bool | | | Phase 2; adults only |
| `risk.fingerprint.points_cap` | 10 | 0–10 🔒 | | | |
| `risk.minors_scoring_enabled` | **false** | 🔒 | | | Counsel sign-off required (open question P-2) |
| `risk.separation.multiplier.S0` / `S1` / `S2_verified` / `S2_unverified` / `S3` | 0.1 / 0.1 / 0.1 / 0.3 / 1.0 | S0–S2: 0–0.5; S3: 🔒 1.0 | | | SH-01 weight by separation class (§4.2.1). S3 is locked at 1.0: verification can never discount separated use. Replaces the former `risk.owner_verified_overlap_multiplier` |
| `risk.owner_verification.max_age_days` | 30 | 7–90 | | | A device counts as owner-verified for this long after its last owner verification; refreshed by any SMS-OTP, passkey or TOTP challenge completed on that device (§4.2.1) |
| `risk.owner_verification.refresh_prompt_days` | 5 | 0–14 | | | Within this many days of expiry, the next sign-in or step-up on a device that had S2 overlaps in the last 7 days asks for SMS OTP, passkey or TOTP (not email OTP) as a "Keep this device verified" prompt; not a risk level (§4.2.1; AMB-22) |
| `risk.trusted_network_multiplier` | 0 | 0–0.5 | | | For coordinator-registered ranges (§5.5) |
| `risk.cgnat_asns` | Curated list (Jio, Airtel, Vi, BSNL mobile ASNs, …) | list of ints | | | ASNs treated as `mobile`/CGNAT for separation classes and IP-limit relaxation. Reviewed quarterly |
| `login.backoff_base_seconds` / `backoff_cap_seconds` | 1 / 900 | | | | Doubling. OWASP-2 |
| `login.hard_disable_after_failures` | 50 | 10–100 | | | NIST ceiling ≤100 [Verified]. Unlocked by password reset or MFA |
| `login.ip_failed_limit_per_10min` | 30 | 10–200 | | | ×10 for registered campus ranges and known CGNAT ASNs |
| `otp.ttl_seconds` | 300 | 120–600 | | | NIST out-of-band ≤10 min [Verified] |
| `otp.sms.max_per_number_per_hour` / `per_day` | 3 / 10 | | | | SMS-pumping control (API4/API6) |
| `otp.max_verify_attempts` | 5 | 3–10 | | | Per OTP |
| `unblock.max_open_requests` | 1 | — 🔒 | | | Per case |
| `unblock.max_requests_per_30d` | 3 | 1–5 | | | |
| `unblock.sla.first_response_hours` | L3: 24, L4: 48 | | | | |
| `unblock.sla.decision_hours` | L3: 72, L4: 120 | | | | |
| `unblock.false_positive_extension` | true | bool | | ✓ | Extends the subscription by the number of restricted days |
| `org.notify_coordinator_on_restriction` | `L4_status_only` | `none`/`L4_status_only`/`L3_and_L4_status_only` | ✓ | | Status only. **Signals are never shared** with coordinators |

---

## 4. Signal catalogue

### 4.1 Families

Two score families are kept apart because their remedies differ:
- **Sharing score (SH-*)** covers licence enforcement. It applies to adults only.
- **Takeover score (TO-*)** covers protecting the account holder. It applies to all users. For minors it works only as deterministic rules with no score (§4.4).
- **High-confidence rules (HC-*)** are not scores: they are explicit conditions that apply an action directly (§5.6).
- **Abuse (AB-*)** and **integrity (IN-*)** rules (§4.5) are deterministic detections that throttle, alert or open a review. They never add to the sharing score and never restrict an account on their own; AB-01 and AB-03 add takeover points for adults.
- **Cap events (`cap.*`)** record deterministic limit hits (§6.3).

Rule keys are stored in `security_signals.rule_key` and `risk_rules.key` exactly as written here (`SH-01`, `TO-04`, `HC-01`, `AB-07`, `IN-01`, `cap.stream`).

**Categories**, used by the L3 gate: `C` = concurrency, `D` = device, `N` = network.

### 4.2 Sharing signals (adults)

**Cap semantics.** Each signal has a 7-day cap expressed in *weighted* points (base points × multipliers). An occurrence counts only if the weighted points of the same signal already counted in the 7 days ending at that occurrence, plus this one, do not exceed the cap; otherwise it is recorded with `counted = false` in `multipliers` and contributes 0. Decay (§5.1) is applied after capping.

#### 4.2.1 Separation classes and owner verification

For every SH-01 overlap (a device pair with ≥3 overlapping engaged buckets on one IST day) the engine classifies the pair using the network observation that covers each device's buckets (§1.2). The **most separated** class seen on that day is used.

| Class | Condition | SH-01 multiplier | Rationale |
|---|---|---|---|
| **S0 same-machine** | `fp_hash` matches (×0), or same net cluster + same OS family + same device_class | 0 / 0.1 | Two browsers on one computer |
| **S1 co-located** | Same net cluster (same /24 IPv4 or /56 IPv6 on a fixed-line network; same ASN and same `geo_region` on mobile) or either leg on a verified trusted network of the user's org | 0.1 | One person, two screens on one network |
| **S2 indeterminate** | Different clusters, but at least one leg is `mobile`, a `risk.cgnat_asns` ASN, `vpn_proxy`, `hosting`, `tor` or `unknown` | 0.1 if **both** devices are owner-verified; 0.3 otherwise | Phone on mobile data while the laptop is on Wi-Fi is the commonest legitimate pattern, but the location of a CGNAT or VPN leg is unknown |
| **S3 separated** | Different clusters, **both** legs `broadband` or `education`, different ASNs or non-overlapping /16s, neither on a trusted network | **1.0, always** (🔒) | One person cannot be on two fixed-line networks in different places at the same time. Verification never discounts this |

**Owner-verified** (AMB-01) means: the device completed, within `risk.owner_verification.max_age_days` (30), a challenge using **SMS OTP to the registered mobile number, passkey or TOTP** (the new-device verification counts if it used one of these). Email OTP makes a device trusted but **not** owner-verified. `user_devices.owner_verified_at` and `verification_method` record it.

**Refresh and expiry (AMB-22).** `owner_verified_at` is refreshed whenever **any** SMS-OTP, passkey or TOTP challenge is completed on that device: login (passkey or OTP login), step-up (P5/S10), new-device verification or L2 re-verification. Passkey and OTP-login users therefore stay owner-verified without extra steps. For password-only users, within `risk.owner_verification.refresh_prompt_days` (5) of expiry, the next sign-in or step-up on a device that had S2 overlaps in the last 7 days asks for SMS OTP, passkey or TOTP instead of email OTP ("Keep this device verified"). If a device lapses anyway, its S2 overlaps score at the unverified multiplier only **while** it is lapsed: because the S2 multiplier is resolved at scoring time, the next owner verification re-weights them to 0.1.

**Re-weighting on verification.** The S2 multiplier is resolved at *scoring* time, using each device's verification state at the evaluation moment, so verifying both devices after an L2 prompt re-weights earlier S2 overlaps to 0.1 and clears L2. S3 overlaps are never re-weighted. A device verified in a way that triggered **SH-13** stays at the unverified S2 multiplier for 30 days.

**Why this closes the OTP-relay gap.** If an owner relays OTPs, the sharer's device becomes owner-verified, but (a) every simultaneous use from the sharer's home or college fixed-line network is S3 at full weight, (b) the relayed verification itself is SH-13 when it completes on a distant fixed-line network while the owner is active elsewhere, and (c) HC-01 (§5.6) needs no verification gate at all. A sharer who only ever uses mobile data remains hard to detect (S2); that is accepted residual risk R1 (threat model §7) and is tested as an expected under-detection (§11, row 5c).

Points are added per occurrence and capped per signal within a rolling 7-day window (cap semantics above).

| ID | Cat | Definition | Computation | Points (cap/7d) | Strength | Weakness and India caveats |
|---|---|---|---|---|---|---|
| SH-01 | C | **Overlapping engaged activity** on ≥2 distinct device tokens | Per day, ≥3 overlapping engaged 5-min buckets for a device pair. One occurrence per pair per day. Evidence stores `separation_class` | 15 (45). Multiplier by separation class (§4.2.1): S0 0/0.1, S1 0.1, S2 0.1 or 0.3, S3 1.0 | Server-side behavioural overlap, the strongest evidence (RPA §3 [Rec]) | One person with two screens. Mitigated by the separation classes and the L3 gates |
| SH-02 | N | Overlap (SH-01) **on distinct network clusters in different states** | Applies when the SH-01 pair's `geo_region` values differ and neither IP is in a trusted range | 6 (12) | Separates "two people in two cities" from "one person, two screens" | CGNAT egress can geolocate to the wrong state (RPA §3 [Reported]). Hence the low weight and the counting toward the network cap |
| SH-03 | C | **Stream ping-pong** | ≥3 "play here instead" takeovers between the same 2 devices within 60 min | 8 (24) | Hard evidence of two concurrent viewers fighting over the stream | A single user switching rooms. Hence the ≥3 threshold |
| SH-04 | C | **Session-cap evictions** | ≥3 sessions on *other* devices ended by the session-cap prompt within 24 h | 6 (12) | Server fact | Users who never log out. Low weight |
| SH-05 | D | **Distinct device tokens, 30 days** | Count of distinct `device_id`s that authenticated in 30 days: ≥6 gives 8 points; ≥10 gives 16 | 8 or 16 (16) | Simple and explainable | Cookie clearing and incognito inflate the count. The same-machine discount applies to the count |
| SH-06 | D | **Rapid device churn** | ≥4 new device tokens within 24 h | 8 (16) | Classic sharing or evasion pattern | Privacy-conscious users who clear cookies. Visible in the UI so they can self-correct |
| SH-07 | D | **New-device OTP abandoned or failed** | ≥2 new-device OTPs not completed (expired or failed) within 7 days | 8 (16) | The sharer cannot get the owner's OTP | SMS delivery failures in India. Excluded when the provider DLR shows "undelivered" |
| SH-08 | C | **Assessment conflict** | A second device tries to open an *in-progress* attempt that is bound to another session, and the student does not complete the rebind | 10 (20) | Directly protects assessment integrity (ASP §5 [Rec]) | A crash followed by a phone fallback. The rebind flow absorbs this |
| SH-09 | N | **Hosting, VPN or Tor network** | A session created from `network_type ∈ {hosting, vpn_proxy, tor}` | 4 per day (8) | Reseller indicator (RPA §3 [Reported]) | Corporate VPNs, iCloud Private Relay. Counted only toward the network cap |
| SH-10 | N | **Geo-velocity (state level)** | Consecutive sessions in different states whose centroids are >1,000 km apart within <2 h, excluding mobile ASNs | 4 (8) | Cheap | Weak in India: CGNAT and mobile egress (Microsoft needs learning and VPN suppression, RPA §3 [Reported]) |
| SH-11 | D | **Device shared across accounts** | The device is used by ≥4 accounts in 7 days and is not a registered lab device. Points go to each account | 4 (8) | Feeds the device-account graph and reseller detection | Family PC, cyber café. Low weight. Mostly a reviewer aid |
| SH-12 | D | **Fingerprint re-link** (Phase 2, opt-in) | A new device token whose `fp_hash` matches a previously revoked or removed device of this account | 5 (10) | Detects cookie clearing used to evade the device cap | Unstable (FP-STALKER). Capped at 10 🔒 |
| SH-13 | D | **Verification at a distance (OTP relay)** | A new-device verification or L2 owner verification is completed on device B whose network at completion is `broadband`/`education`, while another device A of the account had an engaged bucket or an authenticated request within ±15 min on a **different** `broadband`/`education` cluster (the S3 condition). One occurrence per verified device | 10 (20) | The owner's code was used somewhere the owner was not. Does not depend on the verification outcome being "owner" | A user who verifies a work laptop at the office while a family member streams at home on the same account. Explained in the L1/L2 copy; L3 still needs the §5.3 gates || SH-M1 | — | **Repeat modifier** | A confirmed (not false-positive) L3 or L4 decision within `risk.repeat_window_days` | Score ×1.25 | | Applies only after a human or confirmed decision |

**Network cap.** Points from SH-02, SH-09 and SH-10 together are capped at `risk.network_points_cap` = 20, which is below the L2 threshold. Network evidence alone can therefore reach at most L1.

### 4.3 Takeover signals (all users; scored for adults, rule-only for minors)

| ID | Definition | Computation | Points | Notes |
|---|---|---|---|---|
| TO-01 | Failed-login burst on the account | ≥10 failures in 15 min | 20 | Per-account back-off also applies deterministically |
| TO-02 | Breached-password match at login | The HIBP k-anonymity range check matches on a successful login | 40 | Always forces a password change. Microsoft rates leaked credentials as "always high" (OWASP-7 [Verified]) |
| TO-03 | Correct password, failed second factor or OTP | ≥2 occurrences in 1 h | 35 | OWASP: notify on this ([Verified]) |
| TO-04 | **Session or device mismatch (cookie replay)** | The session token is presented with a different `__Host-td_device` from the one it was issued to, or with none | 60. **That session only** is revoked immediately (`end_reason = device_mismatch`, `status = blocked`) | Cookie theft or replay indicator. Response in §6.2 |
| TO-05 | Spray or stuffing source | A success from an IP, /24 or ASN flagged by AB-04 (≥50 failures across ≥20 accounts in the past 1 h) | 30 | Okta-style pre-auth reputation (OWASP-7 [Verified]) |
| TO-06 | Sensitive change from a new device | An email, phone or MFA change within 24 h of a first-seen device | 25 | ASVS 7.5.1 already requires reauthentication |
| TO-07 | Tor exit node login | Tor network_type | 15 | |
| TO-08 | **Client drift within one session** | The same session (with the matching device cookie) presents a different `ua_family` or `os_family` from its issue values (a major-version change is ignored) | 60. That session only is revoked (`device_mismatch`) | Both cookies copied from one browser profile into another browser (infostealer cookie jar). Narrows residual risk R4 |
| TO-09 | **First login from outside India** | Successful login from `geo_country ≠ IN` when the account has no successful login from that country in 180 days | 15. "Was this you?" notice | Takeover protection only; never used for sharing. **No "impossible travel" rule is used for takeover**: state-level geo-IP in India is too unreliable (RPA §3), so only the country change is used (AMB-17) |
| TO-10 | **Remember-token reuse** | A superseded `__Host-td_remember` token is presented (§1.4 rule 5) | 60. The remember credential is revoked; the presenting session is revoked | Token theft indicator (rotation-reuse detection, OWASP JWT CS pattern) |
| TO-11 | Abuse-derived | AB-01 (rapid session creation) or AB-03 (OTP verify brute force) on this account | 20 each | §4.5 |

**Takeover thresholds:**
- **T-step-up ≥ 40**: the next login, and the next sensitive action on any remaining session, require MFA or SMS OTP to the registered mobile (passkey/TOTP where enrolled). Email "Was this you?" with a "Secure my account" link.
- **T-protect ≥ 70, or any confirming high-confidence takeover rule HC-T1..T3 (§5.6)**: protective lock. All sessions are revoked, a password reset and OTP are required, and a notification goes out.

A single TO-04, TO-08 or TO-10 (60 points) therefore revokes the replayed session and puts the account into T-step-up, but does **not** by itself revoke the owner's other sessions or force a password change (AMB-02). These are self-service recovery paths, not punitive restrictions.

### 4.4 Minors applicability

| Control | Adults | Minors (`users.is_minor = true` or no verified age) |
|---|---|---|
| Session, stream, device and replacement caps, assessment binding | ✓ | ✓ (deterministic) |
| New-device OTP | ✓ | ✓ |
| SH-* sharing signals and score | ✓ | ✗. Signals are **not computed**. No `risk_evaluations` row of type `sharing` is written |
| Fingerprint | Phase 2, opt-in | ✗ never |
| TO-* takeover protection | Score | Deterministic rules only: TO-01 back-off, TO-02 forced reset, TO-03 lock-after-N (3 in 1 h → protective lock), TO-04/TO-08/TO-10 revoke of that session, HC-T1..T3 protective lock. No score is accumulated. **No `risk_evaluations` row of any family is written for a minor** (AMB-12); each deterministic action is recorded as a `security_signals` row (`family = takeover`, `base_points = 0`, `is_minor_at_time = true`) plus the `auth_sessions` end record and `audit_log` |
| HC-01/HC-02 sharing auto-restriction | ✓ | ✗ never |
| AB-*, IN-* | ✓ | ✓ (deterministic throttles and alerts only; AB-01/AB-03 add no points for minors) |
| L3 sharing restriction | ✓ | ✗. Repeated cap hits produce only deterministic outcomes (e.g. replacement quota exhausted, so support is needed). A human case (PRD FR-SEC-007) remains possible for credential-resale evidence, with guardian or college notification |
| Shared-account handling | Risk engine | Support or the coordinator handles it through ordinary terms-of-use processes with the parent or college, never via profiling |

When a user turns 18, scoring starts **only from that date**. Historic data is never back-filled into features. Users with an unverified age default to minor treatment. Accounts flagged `users.is_synthetic = true` (monitoring accounts, deployment I-15) are excluded from SH scoring, HC rules and dashboards; caps still apply.

### 4.5 Abuse and integrity rule registry (AMB-04, testing I-05)

All rules below are in the `abuse-1.0.0` / `integrity-1.0.0` rulesets (`risk_rule_versions`, versioned and dual-approved like the others). Thresholds are rule-version parameters. "Source-level" rules write `security_signals` rows with `user_id = NULL` and the source (IP /24, ASN, device id) in `evidence`. None of them restricts an account; the strongest action is a throttle, a step-up or a case opened for human review.

| ID | Detection | Threshold (v1) | Scope | Scores? | Action | Alert routing |
|---|---|---|---|---|---|---|
| AB-01 | **Rapid session creation** on one account | ≥10 successful logins in 1 h, or ≥20 in 24 h | Account | Adults: TO-11 (+20 takeover points). Minors: none | T-step-up at the next login; logins beyond 20/24 h get `429 rate_limited` for 1 h | H-ENG counter; security lead if ≥50 accounts trip in 1 h |
| AB-02 | **OTP send abuse / SMS pumping** | Per number: hitting `otp.sms.max_per_number_per_hour` 3 times in 24 h. Per source: OTP sends to ≥5 distinct numbers from one IP /24 or device in 1 h | Account + source | No | Source: non-puzzle challenge (§ threat model A12), then sends refused 24 h. Number: SMS refused 24 h, email/passkey offered | Ops on-call when SMS spend > 2× 7-day hourly baseline |
| AB-03 | **OTP verify brute force** | ≥10 failed verifications in 1 h on one account (OTP disabled 1 h, threat model §4.1) | Account | Adults: TO-11 (+20) | OTP disabled 1 h; 3 occurrences in 24 h → T-step-up with passkey/TOTP only, or support | H-ENG counter |
| AB-04 | **Credential stuffing source** | ≥50 failures across ≥20 distinct accounts from one IP, /24 or ASN in 1 h (×10 for registered campus ranges and `risk.cgnat_asns`) | Source | No (feeds TO-05) | Source flagged 24 h: pre-auth challenge, login limits ×0.1, failures do not count toward account lockout | Security lead when > 500 failures/10 min platform-wide |
| AB-05 | **Password spray** | One ASN or /24 attempts ≥100 distinct accounts in 1 h with ≤2 attempts each | Source | No | ASN-level pre-auth challenge 1 h | As AB-04 |
| AB-06 | **Automation / scraping** | One session: ≥1,000 authenticated requests in 10 min, or ≥5 req/s sustained 60 s on content routes, or question-bank reads > 2,000/day (threat model API6) | Session | No | That session throttled (`429`, 15 min). ≥3 days in 14 → case opened (`opened_reason = manual`, priority low) for human review; never an automatic restriction | H-ENG; case queue |
| AB-07 | **Unknown or forged session tokens** | ≥20 tokens unknown to both Redis and Postgres presented from one IP /24 in 10 min | Source | No | IP /24 throttled on authenticated routes 15 min | Security lead at ≥100 in 10 min |
| AB-08 | **Restricted-route probing** | ≥30 `403 account_restricted` responses for one user in 10 min | Account | No | None beyond the 403s (probing must not escalate a restriction automatically, owner scenario 13) | Visible in the case timeline and H-ENG |
| AB-09 | **Cross-tenant ID probing** | ≥20 `404 not_found` on ID routes per user per minute, or ≥5 requests in 1 h that resolve to another tenant's object (detected by the scoped repository before the 404) | Account (staff or student) | No | None automatic. Staff: the security lead may kill sessions (step-up) and open an incident | Security lead immediately (role-permission-matrix TI-02; threat model A3) |
| AB-10 | **Restricted account's device used for another account** | A device used by an account under active L3/L4 authenticates into a different account within 7 days | Account (the other account) | No | Evidence attached to the restricted account's case; on the other account, a case is opened only if it is also at ≥ L2 | Case queue |
| AB-11 | **Cross-org login on a lab device** | A registered lab device of org X is used by an account with no membership in X | Account + device | No | Session allowed (lab rules apply); 3 in 7 days on one device → coordinator asked to review the lab device registration | Security reviewer (status only to the coordinator) |
| AB-12 | **Webhook signature invalid** | Any request to `/api/v1/webhooks/{provider}` failing HMAC verification | Source | No | `400 webhook_signature_invalid`, payload not processed (only its hash is kept) | Ops on-call when >10/min per provider |
| IN-01 | **Learning-time plausibility violation** (`analytics.plausibility_violation`) | Day flagged `implausible` by analytics (> 16 h credited, AN §5.5) | Account | **No** (not a sharing input; resolves AMB-04) | Excluded from analytics, leaderboards and percentiles by analytics | Ingest-health dashboard only |
| IN-02 | **Ingest identity or clock forgery** | ≥50 ingest rejections with codes `uuid_time_mismatch`, `event_in_future` or identity mismatch in 1 h for one session | Session | No | Ingest for that session ignored 1 h | Ingest-health dashboard |
| IN-03 | **Hidden-test probing** | ≥20 code submits per problem per hour by one user (threat model A6) | Account | No | Submissions throttled 1 h; trainer may refer to a case (`integrity_referral`) | Content/coding owner |

Every row writes `security_signals` with the ID as `rule_key` and `family` `abuse` (AB-*) or `integrity` (IN-*). Signals of these families are retained per R-RISK (180 days).

---

## 5. Risk scoring model v1

### 5.1 Formula

```
score_family(u, t) = min(100, M_repeat × Σ_i  p_i × m_i × 0.5^((t − t_i)/H))
```

- `p_i`: the signal's base points.
- `m_i`: product of the multipliers: separation class (SH-01, §4.2.1; resolved at scoring time for S2), trusted-network. The per-signal 7-day cap is applied to `p_i × m_i` (§4.2 cap semantics).
- `H`: `risk.decay_half_life_days` = 7. Only signals within `risk.window_days` = 30 count. Decay factor per day `r = 0.5^(1/7) ≈ 0.906`.
- Network subtotal: capped at 20 before summing.
- `M_repeat`: 1.25 if SH-M1 applies, otherwise 1.

**Worked example A: one person, laptop + phone, daily, indefinitely.** Laptop on home broadband, phone on Jio mobile data, ≥15 min of overlapping engaged use every day. Class S2.
- Both devices owner-verified (SMS OTP at new-device verification): 15 × 0.1 = 1.5 per day. Steady state over the 30-day window: 1.5 × Σ_{k=0..29} r^k = 1.5 × 10.06 ≈ **15 → L0** for as long as each device's owner verification stays fresh (≤ 30 days old). Passkey or SMS-OTP sign-ins refresh it automatically, and password-only users get the pre-expiry "Keep this device verified" prompt (§4.2.1), so in practice this is L0 indefinitely. If a device is allowed to lapse, it scores like the email-OTP case below until it is verified again, when the earlier overlaps re-weight to 0.1 (AMB-22). Both devices on home Wi-Fi (S1): ≈ 15 → L0 regardless of verification.
- Phone verified only by email OTP: 15 × 0.3 = 4.5 per day. After 7 days 4.5 × 5.30 ≈ 24 (L0); from about day 8, L1 banner; steady state 4.5 × 10.06 ≈ 45 → L2 "Confirm it's you" by SMS OTP. Once both devices are owner-verified, the S2 overlaps are re-weighted to 0.1 → ≈ 15 → L2 clears (< 35). **[Rec]**

**Worked example B: an owner who shares and relays OTPs.** The owner (Hyderabad, Airtel broadband) relays the new-device SMS OTP to a friend in Pune (ACT Fibernet broadband), so the friend's laptop is owner-verified. Timeline (day 0 = evaluation day): verification completed on the friend's laptop on day −10 while the owner was active at home (SH-13); S3 overlaps on days −9, −6, −3 and 0 with the two devices in different states (SH-01, SH-02); stream ping-pong on day −1 (SH-03); 6 device tokens in 30 days (SH-05).

| Signal | Occurrences counted after the 7-day cap | Decayed contribution |
|---|---|---|
| SH-01 (15 × S3 1.0; cap 45) | −9, −6, −3, 0 (each 7-day window holds ≤ 3) | 15 × (0.410 + 0.552 + 0.743 + 1) ≈ 40.6 |
| SH-02 (6; cap 12; network) | −9, −6, 0 (−3 exceeds the cap) | 6 × (0.410 + 0.552 + 1) ≈ 11.8 (network subtotal 11.8 ≤ 20) |
| SH-13 (10) | −10 | 10 × 0.372 ≈ 3.7 |
| SH-03 (8) | −1 | 8 × 0.906 ≈ 7.2 |
| SH-05 (8, state signal) | 0 | 8 |
| **Total** | | **≈ 71 → L3** |

Gates (§5.3): score ≥ 70; categories C, D, N; concurrency evidence on 5 distinct days within 14; separated-use evidence (S3 or SH-13) on 5 days; L2 was reached on day −3 (score ≈ 55), the L2 re-verification was passed (relayed again), and a new S3 overlap followed on day 0. → **L3 applies even though every device is owner-verified.** The same facts also satisfy HC-01 (§5.6): when `risk.hc.auto_restrict_enabled` is true, HC-01 would have applied L3 on day 0 regardless of the score.

With only 2 overlap days (−3, 0) and the same other signals: SH-01 26.1 + SH-02 10.5 + SH-13 3.7 + SH-03 7.2 + SH-05 8 ≈ 55 → **L2**; HC-01 not met (needs 3 days).

**Worked example C: sharer on mobile data only.** As B but the friend uses only Jio mobile data: all overlaps are S2; the friend's device is owner-verified through relay, so 1.5 per day; no SH-13 (mobile leg). Score stays ≈ 15–25 → L0/L1. Accepted under-detection (residual R1); only the deterministic caps (2 sessions, 1 stream) limit the sharing.

### 5.2 Evaluation triggers and windows

| Trigger | Mode | Rules evaluated |
|---|---|---|
| Login (pre-session) | Synchronous, p95 < 30 ms budget | TO-* and cap checks. The SH score is read from cache |
| Playback token request, attempt start, rebind | Synchronous | Caps, SH-03, SH-08. Cached score |
| Heartbeat ingestion (5-min micro-batch) | Asynchronous worker | SH-01, SH-02, SH-13; HC-01/HC-02 checked when a new S3 overlap is recorded |
| New-device or owner verification completed | Asynchronous (within 1 min) | SH-13 |
| Nightly 02:00 IST batch | Asynchronous | Full recompute of all SH and TO scores with decay, HC-01/HC-02 re-check, plus level de-escalation |
| Policy or rule version change | Shadow job | Recompute in `shadow` mode for comparison |

### 5.3 Level gates (sharing family)

| Level | Score | Additional gates (all required) | Hysteresis |
|---|---|---|---|
| L0 Normal | < 25 | — | — |
| L1 Notice | ≥ 25 | — | Clears when score < 15 |
| L2 Verify | ≥ 45 | ≥1 concurrency (C) signal in 7 days | Clears after the L2 re-verification of the devices in the evidence passes and score < 35 |
| L3 Temporary restriction | ≥ 70 | ≥`risk.L3.min_categories` (2) categories; concurrency evidence on ≥`risk.L3.min_distinct_days` (3) distinct days within 14; **separated-use evidence** (an S3 overlap or SH-13) on ≥`risk.L3.min_separated_days` (2) distinct days within 14; L2 was reached first and its re-verification was failed or abandoned, **or** a new C signal occurred after it was passed | Fixed duration; then re-verification |
| L3 via high-confidence rule | — (score not required) | HC-01 or HC-02 met, `risk.hc.auto_restrict_enabled = true`, the rule version is `active` and its circuit breaker is closed (§5.6, §5.7) | As L3 |
| L4 Suspension (**human applied**) | ≥ 90 recommended | Prior confirmed L3 within the repeat window **or** a reseller pattern (SH-09 + SH-11 + SH-06). A `security_reviewer` must decide. The system only opens an "L4 recommended" case | No automatic expiry |

The engine **never** auto-applies L4 or a permanent ban (brief §1). The former gate "at least one device not owner-verified" is removed: with OTP relay it made L3 unreachable for exactly the sharers it was meant to catch (AMB-01, AMB-18).

### 5.4 Versioning

- `risk_rules` holds the rule identity: key, family, category, description, student-facing explanation text key.
- `risk_rule_versions` holds the immutable parameter sets. Each version is a JSON document with `params`, `points`, `caps`, `multipliers` and `thresholds`, plus `semver`, `status ∈ {draft, shadow, active, retired}`, `effective_from`, `proposed_by` and `approved_by`. The approver must differ from the proposer.
- Exactly one *ruleset version* (`ruleset_version`, e.g. `sharing-1.0.0`) is active per family. Every `risk_evaluations` row stores the ruleset version and each contributing rule's version.
- **Release process:**
  1. Draft.
  2. **Shadow ≥14 days** on production data, compared against the active version.
  3. Report: level-distribution diff, the set of newly flagged users, and false-positive history.
  4. Dual approval.
  5. Activate.

  Rollback means reactivating the prior version. Restrictions already in force are not retroactively changed. They are re-reviewed when the new version would not have produced them.

### 5.5 Exceptions

| Exception | Who registers it | Effect | Guard rails |
|---|---|---|---|
| **Trusted college networks** (IPv4/IPv6 CIDRs, ASNs) | `college_coordinator` proposes for their organization; `security_reviewer` verifies (WHOIS or college IT letter) | SH-02, SH-09 and SH-10 × 0. Login IP limits ×10 | Max /16 IPv4 per entry; consumer mobile ASNs refused; review every 12 months; audit logged |
| **Shared lab devices** | Coordinator registers lab machines through a one-time "lab enrolment" link opened on each PC, which marks that device cookie `devices.shared_organization_id = {org id}` | SH-11 = 0. Lab devices **do not count** toward students' trusted-device caps (session caps still apply). Sessions on lab devices are forced to 30 min idle with no remember-device | Only usable by members of that org. A cross-org login on a lab device creates a signal for review |
| **Per-user exceptions** (travel, accessibility, a second device for a disability aid, a sibling sharing a laptop) | Created only by a `case_decisions` outcome | e.g. `devices.student.max_trusted = 4` for 90 days, or ignore SH-02 for 14 days | Time-bound (max 180 days); visible to the student |
| **Buddy or extra-learner seat** (commerce) | Purchase | Adds a second named user, which removes the incentive to share | Out of scope here; see the PRD |

### 5.6 High-confidence rules (owner scenario 9; AMB-03)

The owner's scenario 9 expects that "a suspicious account is automatically restricted by a configured high-confidence rule". High-confidence (HC) rules are explicit, individually configurable conditions whose evidence is strong enough to act without a score threshold. They are `risk_rules` rows (family `sharing` or `takeover`, key `HC-*`) with versioned parameters in `risk_rule_versions`, released through the same draft → shadow (≥ 14 days) → dual approval process (§5.4).

**Sharing HC rules (adults with `security_monitoring` consent only; never minors; action L3 only, never L4).**

| ID | Condition (all required; parameters are rule-version `params`) | Default params | Action |
|---|---|---|---|
| **HC-01** Separated concurrent use | (1) ≥ `min_devices` distinct device tokens of the account have engaged overlaps of ≥ 3 buckets in class **S3** (two distinct fixed-line, non-CGNAT, non-VPN, non-trusted network clusters) on ≥ `min_days` distinct IST days within `window_days`; (2) an L2 re-verification was issued on the account at least 24 h before the last qualifying day, and at least one qualifying day falls after it (remedy first); (3) none of the devices is a registered lab device or covered by an active per-user exception; (4) no `lift_false_positive` decision on the account in the last 30 days for sharing; (5) the account is not synthetic | `min_devices` 2, `min_days` 3, `window_days` 14 | L3 `ends_at = now + risk.L3.duration_hours[0]` (24 h; 72 h for a repeat). Case `opened_reason = engine_hc_L3` (CPR-SCH-07); the rule id is in the evaluation's `gates.hc_rule` |
| **HC-02** Three or more separated users | ≥ 3 distinct device tokens with S3 overlaps involving ≥ 3 distinct fixed-line clusters **in the same 30-minute period** on ≥ `min_days` distinct days within `window_days`; conditions (2)–(5) of HC-01 | `min_days` 2, `window_days` 7 | As HC-01; case priority `high`; `recommended_level = 4` is **not** set automatically (a reviewer decides) |

**Takeover HC rules (all users, protective and self-service, minors included as deterministic rules).**

| ID | Condition | Action |
|---|---|---|
| **HC-T1** Breached credential in use | TO-02: successful login with a password matching the breached-password corpus | T-protect for that account (forced reset; all sessions revoked) |
| **HC-T2** Confirmed stuffing success | TO-05 (success from an AB-04-flagged source) **and** TO-03 or AB-03 on the same account within 1 h | T-protect |
| **HC-T3** Replay confirmed | TO-04, TO-08 or TO-10, **plus** any of: a second TO-04/TO-08/TO-10 within 24 h; TO-06 within 24 h; TO-02 or TO-03 within 24 h; the owner answers "This wasn't me" to the notification | T-protect (revoke all sessions, `must_change_password`, remember-device disabled) |

**Configuration and safety.**
- `risk.hc.auto_restrict_enabled` (🔒, default **false**) is the master switch for HC-01/HC-02. While false, or while a rule version is in `shadow`, HC conditions are still evaluated and written to `risk_evaluations` (`mode = shadow`, `gates.hc_rule`), never acted on.
- Activation order at launch: HC-01 and HC-02 run in shadow for ≥ 14 days during the pilot; the shadow report must show, for every account the rule would have restricted, a reviewer's blind assessment (sample ≥ 30 or all, whichever is smaller) with an estimated FP rate ≤ 5 %; then dual approval sets the rule `active` and the master switch true.
- HC-T1..T3 are protective and self-service, so they are active from launch (security-necessary, brief §1 Minors), still with a dual-approved ruleset version.
- Every HC application writes a `risk_evaluations` row with `action = restrict_L3` (or `protect_lock`), `gates = {"hc_rule": "HC-01", "params": {...}, "qualifying_days": [...]}` and the evidence, so the student explanation and the reviewer view are identical to the scored path.
- The L3 sharing rules in §7.4 (deferral during an attempt) and §6.1 (case, SLA, auto-lift after re-verification) apply unchanged.

### 5.7 Kill switch and circuit breaker (deployment I-01)

| Control | Who | How | Ratification |
|---|---|---|---|
| **Emergency shadow** (`risk.mode` `enforce` → `shadow`) | One `security_reviewer` or `super_admin` holding `security.engine.kill_switch` | `POST /security/engine/kill-switch` with reason, step-up P5. Takes effect within 60 s (policy cache TTL). No new L1–L3 actions; evaluations continue in shadow. Existing restrictions stay in force (use the bulk lift, §5.8, if they were wrong) | A `approval_requests` row (`action_type = risk.kill_switch.ratify`) is created automatically; a second, different holder of `approval.decide` must ratify within 24 h. If not ratified, the security lead and super_admins are paged; the switch is **not** reverted automatically |
| **Emergency HC off** (`risk.hc.auto_restrict_enabled` → false, or one HC rule → `shadow`) | As above | Same endpoint with `target = hc` or `target = rule:HC-01` | As above |
| **Return to enforce / HC on** | `policy.edit` / `security.rule.publish` | Normal Dual (§3.1, §5.4) | — |
| **Automatic circuit breaker** (per HC rule) | System | Trips when `lift_false_positive` decisions exceed `risk.hc.circuit_breaker.max_fp_rate` of the last `min_decisions` HC-applied restrictions, or when more than `max_daily_restrictions` HC L3s would occur in 24 h (edge cases below). The rule moves to `shadow` (writes a new `risk_rule_versions` status change by system actor with reason `circuit_breaker`), alerts the security lead, and shows a banner on the engine-health view | Re-activation by normal dual approval |
| **Takeover rules** | — | Not covered by the kill switch or by `risk.mode` (protective; AMB-23). Deterministic caps and AB-*/IN-* controls are not covered either. A malfunction is handled by a normal rule rollback (SEC-29) | — |

**Circuit-breaker edge cases (AMB-24).**
- **(a) Fewer than `min_decisions` decided.** The FP test applies from the first decision, with an absolute threshold: the breaker trips when the number of `lift_false_positive` decisions among the last `min_decisions` decided HC-applied restrictions (or among all decided ones, if fewer) exceeds `max_fp_rate × min_decisions` (defaults: 0.05 × 20 = 1, so the **2nd** false positive trips it, e.g. 2 FP of 3 decided). Restrictions not yet decided are not counted. This is deliberately conservative during the pilot.
- **(b) The excess restriction.** The daily limit is checked **before** an HC L3 is applied, under a per-rule atomic counter, so at most `max_daily_restrictions` (50) HC L3s are applied in any rolling 24 h. The restriction that would exceed it (the 51st) is **not** applied: the breaker trips, the evaluation is written with `mode = shadow`, `gates.hc_rule` and `gates.breaker = "tripped_daily_limit"`, and the account continues on the scored path (it can still reach L3 through the §5.3 gates).

### 5.8 Bulk false-positive lift (deployment I-02)

When a rule version, a network event or a data bug produces many wrong L3s, reviewers do not decide each case one by one.

1. A `security_reviewer` with `security.restriction.bulk_lift` creates a bulk-lift request with a **selector**: any combination of `ruleset_version`, `rule_key` (incl. HC rules), `organization_id`, `applied_between`, `network_cidr` / `asn` (from the evaluation evidence). Only **engine-applied L3 restrictions** (`source = engine`, level 3, `family = sharing`) can be selected. L4, reviewer-applied restrictions, takeover locks, `is_high_risk` cases and cases with a pending unblock decision are excluded automatically.
2. A dry run returns the matching count, the first 50 cases (masked) and the exclusions. Maximum 5,000 restrictions per request.
3. Execution needs step-up P5 and **Dual**: an `approval_requests` row (`action_type = security.restriction.bulk_lift`, payload = selector + snapshot of matched restriction ids + `payload_hash`), approved by a different holder of `approval.decide` within 72 h.
4. On approval, a worker processes each restriction in its own transaction: writes a `case_decisions` row (`outcome = lift_false_positive`, `decided_by` = requester, `approved_by` = approver, `approval_request_id` = the bulk-lift request), ends the restriction (`end_reason = case_decision`) **without** the per-user re-verification step (the error was ours; sessions were already revoked at L3), suppresses the contributing signals, credits the false-positive extension (PO-10), closes any open unblock request as `moot`, and notifies the student ("We made a mistake…").
5. The rule's H8 counters are incremented; the operator is reminded to move the rule to shadow if it is still active.

---

## 6. Graduated responses

### 6.1 Sharing family

| Level | Default threshold | Automatic actions | Student experience (copy in unblock doc §1) | Admin notification | Expiry |
|---|---|---|---|---|---|
| L0 | < 25 | None | — | — | — |
| L1 Notice | ≥ 25 | In-app banner and email "New activity on your account". Device list highlighted | Informational. No access change | None (dashboard counter only) | Auto |
| L2 Verify | ≥ 45 + gate | On the next request from **every device that appears in the L2-driving evidence** (whether or not it was verified before) and from any non-owner-verified device: interstitial re-verification by SMS OTP to the registered mobile, passkey or TOTP (email OTP not accepted at L2). Until passed, that device gets `403 device_verification_required` for playback tokens and attempt starts. Other sessions above the cap are revoked (`risk_L2_overflow`). A re-verification completed on a distant fixed-line network while another device is active is recorded as SH-13 | "Confirm it's you" | None. Queue counter only | When the re-verifications pass and score < 35 |
| L3 Temporary restriction | ≥ 70 + gates, or HC-01/HC-02 (§5.6) | `account_restrictions` row (level 3, scope `learning_access`, `ends_at` = now + 24 h, or 72 h for a repeat). **All other sessions revoked** (immediately, even when L3 is deferred for an attempt, §7.4). Playback, attempt start, practice and code submit, downloads and certificate issuance are blocked. A `security_cases` row is opened (priority Medium). In-progress attempts are autosaved and follow §7.4 | Restricted screen with reasons, devices and an "Request review" CTA | Case into the security_reviewer queue. Coordinator status-only if policy allows | Auto-lift at `ends_at` **only after** re-verification (OTP + device confirmation). A reviewer can lift early or convert to L4 |
| L4 Suspended | Human applied (≥90 recommended) | All sessions revoked. Login permitted **only** into a limited "account status" surface (case, appeal, privacy requests, billing view/cancel). All entitlements gated, not deleted | Suspended screen with case reference and appeal | Reviewer decision recorded. Coordinator status-only if policy allows | Only via a case decision. Second-person approval for high-risk lifts (unblock doc §5) |

### 6.2 Takeover family (protective, self-service)

| Level | Threshold | Actions | Recovery |
|---|---|---|---|
| Replay response | TO-04, TO-08 or TO-10 (single occurrence) | Revoke **that session only** (`device_mismatch`, `blocked`), 401 to the presenter. Takeover evaluation (adults: +60 → T-step-up; minors: deterministic, no score). The owner's other sessions stay signed in. Owner notified in-app + email: "We signed out a session that looked unusual. If this wasn't you, secure your account" with a "This wasn't me" action (which triggers HC-T3) | Owner signs in again on the affected device (with MFA/OTP under T-step-up) |
| T-step-up | ≥ 40 | The next login, and the next sensitive action on any session, complete only after MFA or SMS OTP. Email: "Was this you?" | Pass MFA |
| T-protect | ≥ 70, or HC-T1, HC-T2, HC-T3 (§5.6) | Revoke all sessions. Mark the password `must_change`. Disable remember-device. Notify by email and SMS. Ingest becomes read-only until recovery | Self-service: OTP to the verified contact + password reset (+ MFA if enrolled). A case opens automatically only if recovery fails twice or the contact details changed within the previous 7 days |

### 6.3 Deterministic cap responses (all users)

| Cap | At the limit | Logged as |
|---|---|---|
| 2 concurrent sessions | First, any active session on the **same `device_id`** as the new login is ended as `replaced_same_device` (it is the same browser profile; not an eviction, not SH-04). If still at the cap: prompt "You're signed in on 2 devices. Sign out of one to continue." (session status `pending_session_choice`). The user chooses; the prompt pre-selects the oldest session that does **not** hold an in-progress attempt. A non-interactive client gets the oldest non-attempt session evicted; if every other session holds an in-progress attempt, the login is refused with `409 session_cap_reached` (`has_active_attempt = true`) instead of evicting (PRD AC-SES-02). Moodle evicts oldest by default and warns about lost work, so our prompt preserves choice (RPA §3 [Verified]) | `security_signals` type `cap.session` (SH-04 input for adults) |
| 1 stream | Token refused with `409 playback_conflict`. UI: "Playing on {device label}. Play here instead?" Confirming revokes the other playback session | `cap.stream` (SH-03 input) |
| 3 trusted devices | New device blocked after OTP until one is removed ("Remove a device") | `cap.device` |
| 2 replacements/30 d | "You've changed devices twice in 30 days. Next change available on {date}, or contact support." Support can grant +1 per 30 days with a logged reason | `cap.replacement` |
| Assessment binding | Same device (`device_id` equal to `bound_device_id`), new session (e.g. after a crash or a lost cookie): **automatic re-attach**, no prompt, no OTP, rebind quota untouched (§7.4). Second device: "This test is open on {device}. Continue here?" Rebind needs confirmation (and OTP at ≥L2). The max-rebinds limit applies. Proctored drives need a trainer override | `cap.attempt_bind` (SH-08 when abandoned); `attempt_events` `reattach_same_device` for re-attach |

---

## 7. Enforcement points

### 7.1 Login (`POST /api/v1/auth/login`, passkey, OTP login)

1. **Pre-auth:**
   - per-IP and per-ASN sliding windows (relaxed for CGNAT and registered ranges);
   - the per-account back-off gate;
   - stuffing-source reputation (TO-05).

   Pre-auth blocks **do not** increment the account's failure counter (the Okta pattern, OWASP-7 [Verified]).
2. Verify credentials. Argon2id runs in a threadpool, and rate limits are checked first.
3. Read or issue `__Host-td_device`, then resolve `devices` and `user_devices`.
4. Check `account_restrictions`:
   - L4 → a session with `scope=status_only`;
   - L3 → `scope=restricted`;
   - a T-protect lock → recovery flow.
5. Run the TO-* rules → step-up if needed.
6. If the device is new → OTP. If trusted devices are already at the cap → device-removal flow. Check the replacement quota.
7. End any active session on the same `device_id` (`replaced_same_device`), then check concurrent sessions → `prompt_choose` (`pending_session_choice`; §6.3 rules for attempt-holding sessions).
8. Issue a new session token (rotated per ASVS 7.2.4). Write the `auth_sessions` row. Write a `login_attempts` row (outcome) and an `audit_log` row.

### 7.2 `require_active_principal` (every authenticated request)

```text
1. token = cookie __Host-td_session (cookie only; never URL/header for browsers)
2. rec = Redis(cache) GET sess:{sha256(token)} → miss ⇒ Postgres auth_sessions by token_hash (re-populate)
   → unknown in both ⇒ 401 unauthenticated (strict mode; AB-07 counter)
3. now > rec.absolute_expires_at, or (now > rec.idle_expires_at and now > coalesce(rec.idle_hold_until, -∞))
   ⇒ end(reason=absolute_timeout|idle_timeout) ⇒ 401 session_expired (remember-device re-issue only per §1.4 rule 5)
4. device cookie hash ≠ rec.device_key_hash, or ua_family/os_family drift ⇒ TO-04 / TO-08
   ⇒ revoke THIS session (device_mismatch, status blocked) ⇒ takeover evaluation (async) ⇒ 401 session_revoked
5. user_state = Redis GET restr:{user_id} (version-stamped; invalidated on any restriction change; fallback DB)
6. user_state.sessions_valid_after > rec.created_at ⇒ revoke ⇒ 401 session_revoked
7. scope = derive(user_state, rec)            # per request; auth_sessions.scope is only a record (AMB-20)
   route.tag not allowed for scope ⇒ 403 problem+json code=account_restricted (case_ref, level, until)
8. if route.idle == extends: slide idle_expires_at   # engaged_only routes slide via sessions.touch_engaged()
   write last_seen_at at most every 60 s; record session_network_observations on cluster change
9. return Principal(user_id, org_ctx, roles, aal, auth_time, restriction_level, is_minor, device_id, session_id)
```

**Canonical route tags** (identical to `api-specification.md` §1.4; AMB-15, API I-07). Tags are declared on the route in any module (`openapi_extra={"x-td-route-tag": ...}`); there is no per-module allowlist.

| Tag | Callable with derived scope | Contents |
|---|---|---|
| `public` | no session | Public routes |
| `login_continuation` | pending statuses (`pending_mfa`, `pending_device_otp`, `pending_session_choice`) and `full`/`restricted`/`status_only` | MFA verify, device OTP, session-cap choice, logout |
| `account_status` | `full`, `restricted`, `status_only` | `GET /me`; own devices and sessions (list, revoke, remove); own security status, cases, unblock requests and unblock re-verification; privacy and consent requests incl. data export (DSAR); billing view, invoices, subscription cancel, refund requests; support tickets; notifications inbox; logout |
| `l3_readonly` | `full`, `restricted` | Read-only dashboard, enrolments, progress, certificate list, own results |
| `mfa_enrolment` | any non-pending scope | MFA factor enrolment for staff without a factor |
| `consent` | any non-pending scope | Consent read/grant |
| `default` | `full` only | Everything else, including playback, attempts, practice, coding, downloads, certificate issuance, checkout, contact changes and staff consoles |

**Scope derivation** (`derive`): restriction level ≥ 4 (or L4 pending lift) → `status_only`; level 3 in force → `restricted`, except that during an L3 **deferral** (§7.4) the session bound to the in-progress attempt keeps `full` for the attempt routes of that attempt only (`ATT-*` with that `attempt_id`) and `restricted` for everything else; T-protect → only `login_continuation` and the recovery routes; otherwise `full`.

A CI test enumerates all routers and fails if any authenticated route lacks the dependency, a route tag or an `x-td-idle` value.

### 7.3 Video playback token issuance (`POST /api/v1/media/playback-tokens`)

Order of checks:
1. principal;
2. entitlement (`entitlements` check, §7.5);
3. restriction (< L3);
4. L2 device owner verification;
5. stream cap: `count(play:{user_id} active, heartbeat < 90 s) ≥ max_concurrent_streams` → 409 with takeover option;
6. per-user token rate limit (30/hour).

The VdoCipher OTP is issued with a 300 s TTL and a watermark (name + masked phone + short session code). The `playback_sessions` row records user, session, device, lesson asset and start time. Heartbeats arrive every 30 s. A revoked playback session gets `410` on its next heartbeat, and the player stops. DRM licences already issued cannot be recalled, so the short TTL plus heartbeat refusal bounds the overrun to ≤90 s.

### 7.4 Test start, resume and rebind (`POST /attempts`, `POST /attempts/{id}/resume`)

- Check: entitlement, restriction < L3, L2 owner verification, one active attempt per test per user.
- The attempt is bound to `bound_session_id` and `bound_device_id`. A request from another session:
  - **same `device_id`** as `bound_device_id` (crash, restarted browser, lost cookie, re-login): the attempt is **re-attached** automatically to the new session: `bound_session_id` updated, `attempt_events` `reattach_same_device`, **`rebind_count` unchanged**, no OTP even at ≥ L2 (the device was already allowed to start the attempt), `idle_hold_until` set on the new session (AMB-08);
  - **different `device_id`**: `409 attempt_bound_elsewhere` and the rebind flow (confirmation; OTP at ≥ L2; counts toward `assessment.max_rebinds_per_attempt`; proctored → trainer override).
- Attempt start requires `absolute_expires_at ≥ deadline_at + grace + 5 min`, otherwise `409 session_too_short_for_attempt` (§1.4 rule 4).
- The server-authoritative deadline is unaffected by restrictions. If an L3 or T-protect happens mid-attempt, answers already autosaved are kept. The attempt is closed by the deadline job as normal, and an `attempt_events` row `session_revoked_security` is recorded so the trainer can grant an override (RPA §4 "disconnects as events, not penalties").
- **L3 deferral (AMB-21).** Revocation for **sharing** never interrupts the attempt-bound session. When L3 is decided while an attempt is in progress, the restriction row is written immediately with `deferred_until = min(attempt deadline + grace, now + 3 h)`; **all other sessions are revoked immediately** (`risk_L3`); new logins during the deferral get `restricted` scope; the attempt-bound session keeps `full` scope for that attempt's routes only (§7.2 scope derivation) and is restricted at `deferred_until` or at submission, whichever is first. **Takeover** revocations are immediate, attempt or not.

### 7.5 Entitlement check (`entitlements.check(user, resource)`)

The check returns `allowed=false, reason=account_restricted` when the restriction level is ≥ L3, for any resource class except `account_status`. Entitlements are never revoked by the security module. They are *gated*, so lifting a restriction restores access instantly with no commerce changes.

### 7.6 Other enforcement points

The rules for code submit, practice answer save, certificate issuance and downloads are identical to §7.5. Placement drive registration also blocks at L3+.

---

## 8. Session revocation semantics

| Aspect | Rule |
|---|---|
| Single revoke | `DEL sess:{hash}`; set `auth_sessions.ended_at/end_reason/ended_by`; remove from the `user_sessions:{uid}` set; end the playback sessions for that session; send a push event (SSE) to the client to show "You were signed out". **Effective immediately** at the next request |
| Revoke all | Increment `users.sessions_valid_after = now()` (in DB and Redis `restr:{uid}`), then iterate the set. The cutoff guarantees revocation even if set iteration misses a key |
| Reason codes (stored in `auth_sessions.end_reason`, together with the expiry reasons `idle_timeout` / `absolute_timeout`) | `user_logout`, `user_revoked_other`, `session_cap_evicted`, `replaced_same_device`, `idle_timeout`, `absolute_timeout`, `password_changed`, `mfa_changed`, `device_removed`, `device_mismatch`, `risk_L2_overflow`, `risk_L3`, `admin_L4`, `takeover_protect`, `admin_kill`, `unblock_reset`, `privilege_change`, `account_deleted` |
| Cookie replay (TO-04/TO-08/TO-10) | Revoke **only the presented session** (`device_mismatch`, status `blocked`); all sessions are revoked only on a confirming takeover rule (HC-T3) or T-protect score (§6.2; AMB-02) |
| Password reset or change, MFA change | Revoke all *other* sessions by default, with an option to keep the current one only on a change (not a reset). ASVS 7.4.3 |
| Account disable or delete | Revoke all (ASVS 7.4.2) |
| Admin kill | `support_agent` (step-up MFA) or `security_reviewer`. Reason required. Audited (ASVS 7.4.5) |
| Device removal | Revokes that device's sessions and clears trust. A removal counts as a replacement only when followed by a new device addition within 30 days |
| After unblock | **All** sessions revoked. New sessions only after full authentication with re-verification (unblock doc §6) |
| Remember-device tokens | `user_devices.remember_token_hash`, rotated on every use (§1.4 rule 5). Revoked with the device, on revoke-all, on any L3, L4 or T-protect, and on reuse of a superseded token (TO-10) |
| Clear-site data | Logout responses send `Clear-Site-Data: "cache","cookies","storage"`, except that the device cookie is re-set so the device keeps its identity. Cache-Control: no-store on authenticated responses |

---

## 9. Risk evaluation record (`risk_evaluations`)

One row is written per evaluation that changes the score by ≥5, changes the level, or is triggered synchronously at a decision point. Rows are append-only.

```json
{
  "id": "0192f3a4-...-v7",
  "user_id": "0192...",
  "organization_id": "0191... | null",
  "family": "sharing",
  "mode": "enforce",
  "ruleset_version": "sharing-1.0.0",
  "trigger": "heartbeat_batch",
  "evaluated_at": "2026-11-03T10:15:00Z",
  "window": {"from": "2026-10-04T10:15:00Z", "to": "2026-11-03T10:15:00Z", "half_life_days": 7},
  "signals": [
    {"signal_id": "0192...", "rule": "SH-01", "rule_version": "1.0.0", "category": "C",
     "occurred_at": "2026-11-02T14:05:00Z", "base_points": 15,
     "multipliers": {"separation_class": "S3", "separation": 1.0, "trusted_network": 1.0, "counted": true},
     "decayed_points": 13.6,
     "evidence": {"device_a": "dev_7f..", "device_b": "dev_c2..", "overlap_buckets": 7,
                  "net_a": "AS24560:/16", "net_type_a": "broadband", "net_b": "AS18209:/16", "net_type_b": "broadband",
                  "region_a": "TG", "region_b": "MH", "owner_verified": {"device_a": true, "device_b": true}}}
  ],
  "subtotals": {"C": 41.2, "D": 8.0, "N": 11.5, "network_capped": 11.5},
  "repeat_multiplier": 1.0,
  "score": 60.7,
  "previous_score": 48.3,
  "level_before": 2,
  "level_after": 2,
  "gates": {"min_categories": true, "distinct_days": 2, "distinct_days_required": 3,
            "separated_days": 2, "separated_days_required": 2, "l2_reached": true, "hc_rule": null},
  "action": "none",
  "restriction_id": null,
  "case_id": null,
  "explanation_keys": ["sh01.overlap_two_devices", "sh02.two_states"]
}
```

`action` takes one of these values:
- `none`
- `notice_L1`
- `require_otp_L2`
- `restrict_L3`
- `recommend_L4`
- `step_up`
- `protect_lock`
- `deescalate`

`evidence` holds only internal IDs, /16 or /24 network prefixes, network types, state codes and counts. It contains no raw IPs. Reviewers resolve full IPs on demand, and each reveal is audited. When an HC rule fires, `gates.hc_rule` holds its ID and `gates.hc` the qualifying days and parameters. Shadow-mode HC matches are written with `mode = shadow`. No row is ever written for a minor (§4.4).

---

## 10. Admin dashboards and reports (Section H)

**Access.** Only `security_reviewer` (platform scope, `security.evidence.read`) can see dashboards and per-user views that show signals. `super_admin` sees aggregate views only (H7, H8, H10, aggregate H11, ENG and the aggregate tabs of other views); per-user evidence only inside break-glass (role matrix §3). A `support_agent` sees restriction status and case status for a user, with no signal evidence. A `college_coordinator` sees an org-level aggregate tile only: count of restricted students, open cases and trusted-network status. Coordinators never see per-student signals or timelines. Every dashboard open of a per-user view requires a **reason code** (`case_review`, `appeal`, `takeover_investigation`, `qa_sample`) and writes an `audit_log` row (threat model A11, insider misuse). Minors never appear in sharing views because no data exists for them. Takeover views show minors' deterministic events.

Views are numbered to match the owner's verbatim Section H list (`source-requirements-excerpt.md`), so report ids are the same here, in `api-specification.md` (SEC-30/31) and in the PRD (API I-15). The engine-health view is `ENG`.

| # | Section H item (verbatim) | View | Content | Filters | Data source |
|---|---|---|---|---|---|
| H1 | Top suspicious accounts | **Suspicious-activity queue** | Open cases sorted by priority, then SLA breach time. Columns: case ref, level, score, HC rule (if any), top 3 explanation keys, age, SLA timer, assignee, org (name only), repeat flag. Second tab: adults with the highest current sharing or takeover score without an open case | Level, family, org, rule, SLA state, assignee | `security_cases` + latest `risk_evaluations` |
| H2 | Multiple-account/device associations | **Device–account graph** | Bipartite graph of the user's devices ↔ other accounts that used them (2 hops max). Nodes show device label, lab flag and the other accounts' level (masked until the reviewer opens that case). Platform list: devices used by ≥ 4 accounts in 7 days (SH-11, AB-10, AB-11) | Hop depth 1–2; 30/90 days | `user_devices`, `devices`, `security_signals` |
| H3 | Concurrent login events | **Concurrent-use events** | Gantt per device of engaged buckets for the selected days, overlaps highlighted with separation class (S0–S3), network type and state of each leg; list of session-cap hits and stream conflicts | User, date range (≤ 14 days per call) | `analytics.feeds.get_engaged_buckets(...)` (adults with `security_monitoring` consent only), `session_network_observations`, `playback_sessions`, `cap.*` signals |
| H4 | Repeated IP/device associations | **Network-cluster associations** | Network clusters (/24 or ASN, masked) used by many accounts: campus NAT candidates (prompt coordinator registration), CGNAT watch, hosting/VPN ASNs with many accounts, AB-04/AB-05 flagged sources | Network type, org, period | `login_attempts`, `session_network_observations` (aggregated), `org_trusted_networks` |
| H5 | Blocked accounts | **Blocked and restricted accounts** | Active L3, L4 and T-protect: since, ends_at, deferred_until, source (engine / HC rule / reviewer), case, org | Level, org, age, source | `account_restrictions` |
| H6 | Pending unblock requests | **Pending unblock requests** | State, SLA countdown, pending second approval (`approval_requests`), assignee | State, SLA | `unblock_requests`, `approval_requests` |
| H7 | Average review time | **Average review time** | Median and p90 for submission → first response and submission → decision, by level, by week; SLA compliance % | Period, reviewer | `unblock_requests`, `case_decisions` |
| H8 | False-positive rate | **False-positive rate** | Per ruleset version, per rule and **per HC rule**: share of L3 and L4 decisions concluded `lift_false_positive`, the L2 re-verification pass rate, bulk lifts, circuit-breaker state. **Alert** when the L3 FP rate is > 10 % over 30 days, any rule contributes to > 3 FP cases in a week, or an HC breaker trips | Ruleset version, rule, org | `case_decisions.outcome`, `risk_evaluations` |
| H9 | Repeat incidents | **Repeat incidents** | Users with ≥ 2 confirmed L3+ within 180 days; time between incidents; outcome | Period | `case_decisions` |
| H10 | Active-session counts | **Active sessions** | Active sessions now and over time by tier and client type; distribution of sessions per user; users at the session cap; aggregate only (no per-user rows unless opened from a case) | Tier, org, period | `auth_sessions` |
| H11 | Daily/weekly/monthly learning activity | **Activity context** | Aggregate daily/weekly/monthly active learners and engaged minutes (platform, org); per-user daily activity only inside a case review, adults with consent only | Period, org | `analytics.feeds.get_activity_summary(...)`, `daily_learning_aggregates` / `weekly_learning_aggregates` (k-floors apply to org views) |
| H12 | Device and login history | **User security timeline** | Chronological merge of logins, sessions (device label, /24 net, state, start, last active, logout, duration, end reason), network changes, caps hit, signals, evaluations (score sparkline), restrictions, OTP outcomes, case events and decisions | Time range; event type | `auth_sessions`, `session_network_observations`, `login_attempts`, `security_signals`, `risk_evaluations`, `account_restrictions`, `case_notes`, `case_decisions` |
| ENG | (engine health) | **Policy and engine health** | Level distribution (L0–L4) over time, `risk.mode` and kill-switch state, HC shadow matches vs enforced, shadow vs active diff, signal volumes, AB-*/IN-* counters, OTP delivery failure rate by provider, trusted-network registrations awaiting verification | — | Aggregates |

Report keys (`api-specification.md` SEC-31/SEC-32; IPR-SEC-02): H1 `top-suspicious-accounts`, H2 `account-device-associations`, H3 `concurrent-login-events`, H4 `repeated-network-device-associations`, H5 `blocked-accounts`, H6 `pending-unblock-requests`, H7 `average-review-time`, H8 `false-positive-rate`, H9 `repeat-incidents`, H10 `active-session-counts`, H11 `learning-activity`, H12 `device-login-history`, ENG `engine-health`.

**Reports.** These are CSV exports (`report.export.request`) and need step-up MFA (P5). Exports are watermarked with the requester and time, and audited. Approval (API I-26; role matrix v0.4 §5): an export of a **security/monitoring report** with per-user rows (H1–H9, H12, any per-user device/login history, per-user H11 rows from a case) is approved by a **second `security_reviewer`** holding `report.export.approve` (`action_type = security.export.per_user`; approver ≠ requester). `super_admin` never approves these, because it cannot view security evidence outside break-glass. All other exports that need approval (H10 and aggregate H11 when bulk, finance and college reports, any personal-data export > 10,000 rows) are approved by `super_admin` (`action_type = export.bulk_pii`; approver ≠ requester). Aggregate-only security exports need step-up only.
- **Monthly integrity report:** counts by level, FP rate, SLA compliance, appeals outcome, top rules, HC rule outcomes.
- **Per-org summary** for coordinators: aggregates only.
- **Rule-tuning report:** shadow comparisons.

---

## 11. Phase-8 test scenarios (owner numbering)

Rows 1–20 follow the owner's verbatim Phase-8 list (`source-requirements-excerpt.md`) and the SCN-01..20 ids of `testing-and-acceptance-criteria.md` §4. Rows R-1..R-9 are retained regression scenarios. Points use the v1 defaults and are approximate after decay (§5.1). Adults have `security_monitoring` consent unless stated.

| # | Scenario | Expected result | Rule(s) tested | Event(s) recorded | Score / severity | User-facing response | Admin notification | Auto-restriction appropriate? | Recovery / appeal |
|---|---|---|---|---|---|---|---|---|---|
| 1 | Laptop, then phone (home Wi-Fi + Jio). Variant: daily overlap, both devices SMS-OTP verified | Phone triggers a one-time new-device OTP (SMS → owner-verified), then normal. Variant: S2 overlaps × 0.1 | Case 3–4; new-device verification; §4.2.1 | `user_devices` trust; OTP success; SH-01 (S2) in the variant | 0; variant ≈ 15 steady → L0 | OTP prompt once | None | No | n/a |
| 2 | Several tabs on one laptop, video in one, practice in another | One session, one device. A second tab playing takes over the stream within the session silently | Case 1 | Heartbeats only | 0 / none | "Playing in another tab" overlay | None | No | n/a |
| 3 | Two students (and 40 in a lab) on the same college Wi-Fi within 10 min | All succeed; no IP lockout; no signals | Case 7; relaxed IP window; trusted network × 0 | `login_attempts` only | 0 / none | Normal | H4 shows the cluster as a registration candidate if unregistered | **No** | Coordinator prompted to register the range |
| 4 | Student switches from Wi-Fi to mobile data mid-session | Same session continues (never bound to IP); a `session_network_observations` row is added | Case 7; brief "never bound to IP" | Network observation | 0 / none | None | None | No | n/a |
| 5a | Two unrelated devices used at the same time from fixed-line networks in two states on 4 days in 10; OTPs relayed by the owner (worked example B) | L2 on day −3 (re-verification of both devices; passed by relay); L3 on day 0 (gates met) | SH-01 (S3), SH-02, SH-13, SH-03, SH-05; §5.3 gates; HC-01 if enabled | Signals, evaluations, L3 restriction 24 h, case | ≈ 71 / medium | L2 "Confirm it's you", then the L3 restricted screen | Case in H1 (medium), SLA 24 h | **Yes** (temporary, gated, reversible) | Unblock request; auto-lift at 24 h after re-verification + device review |
| 5b | Second device presses play while the first is streaming | 409 `playback_conflict`; "Play here instead?" ends the first stream | Stream cap 1; SH-03 only if ≥ 3 ping-pongs/h | `cap.stream` | 0 / info | Conflict dialog | None | No (deterministic only) | n/a |
| 5c | As 5a but the sharer uses only mobile data (worked example C) | Overlaps are S2; relayed verification → × 0.1; no SH-13. **Expected under-detection** (residual R1; AMB-18) | §4.2.1 S2 | SH-01 (S2) | ≈ 15–25 → L0/L1 | Possibly L1 banner | None | No | n/a |
| 6a | Registered lab PC used by 35 accounts in a week | No SH-11; lab devices excluded from personal device caps; 30-min idle; browser-session cookie | Case 5; lab device | Logins only | 0 / none | "Shared computer: sign out when done" | None | No | n/a |
| 6b | Unregistered PC used by 6 accounts in 7 days (cyber café) | SH-11 on each account (4 pts); H2 flag | Case 5; SH-11 | SH-11 signals | ≈ 4 each → L0 | None | H2 only | No | n/a |
| 6c | Hosting ASN, 5 new device tokens in 24 h, the same devices used by 8 other accounts | Network capped; device signals; reseller pattern → L3 if gates met, and an **L4 recommendation** case | SH-09, SH-06, SH-11, SH-05; L4 recommend | Evaluations; case high | ≈ 80–95 / L3 + recommend L4 | L3 screen | H1 high; reviewer decides L4 | L3 yes; **L4 human only** | Appeal; second approval to lift if L4 applied and high-risk |
| 7 | Logins geolocating to Hyderabad then Delhi within 1 h (broadband), and a Jio user whose IP geolocates to 3 states | Broadband pair: SH-10 (4); Jio excluded from SH-10; network cap. Login from outside India would add TO-09 (notice only) | SH-10; network cap; TO-09 | SH-10 signal | ≤ 8 → L0 | None (new device → OTP) | None | **No** (never on IP/geo alone) | n/a |
| 8 | Legitimate student on a VPN (and phone on home Wi-Fi) | SH-09 (4/day, cap 8, network cap). Overlaps with a VPN leg are S2 (× 0.1 verified). Tor login adds TO-07 (takeover) only | SH-09; §4.2.1 S2; TO-07 | SH-09 signal | ≤ 10 → L0 | None | None | **No** | n/a |
| 9a | HC-01 met (S3 overlaps on 3 days in 14, L2 issued ≥ 24 h earlier), `risk.hc.auto_restrict_enabled = true`, HC-01 version active | L3 applied by HC-01 regardless of score; all other sessions revoked; case `engine_hc_L3` | HC-01; §5.6 | Evaluation (`gates.hc_rule = HC-01`), restriction, case, outbox `account.restricted` | medium | L3 screen naming the behaviour | H1 (medium) | **Yes** (configured high-confidence rule; temporary, reversible) | As 5a |
| 9b | Same facts, HC-01 in shadow or master switch false | Evaluation `mode = shadow`, no action | §5.6 shadow | Shadow evaluation | — | None | ENG shows the shadow match | No (shadow) | n/a |
| 9c | Same facts while a timed attempt is in progress | Restriction written with `deferred_until`; other sessions revoked immediately; attempt session keeps attempt routes only; restricted at submit or `deferred_until` | §7.4 deferral | Restriction (deferred), `auth_sessions` ended `risk_L3` | medium | Attempt continues; then L3 screen | H1 | Yes (deferred) | As 5a |
| 9d | Credential stuffing: 2,000 failures across 600 accounts from one ASN; one account's correct password then failed OTP twice | AB-04 flags the source (no lockout counted); the target account hits HC-T2 → T-protect | AB-04, TO-05, TO-03, HC-T2 | `login_attempts`; signals; protective lock | high | "We've secured your account…" + email/SMS | ENG spike; no case unless recovery fails twice | **Yes** (protective, self-service) | OTP + password reset |
| 9e | Minor with the 9a timeline | Only deterministic caps fire; no SH, no HC, no evaluation rows | §4.4 | `cap.*` only | n/a | Cap dialogs only | None | **No** | Support process with parent/college |
| 9f | HC-01 produces 3 `lift_false_positive` decisions among its last 20 | Circuit breaker trips (3/20 = 15 % > 5 %): HC-01 → shadow; alert | §5.7 | Rule version status change (`circuit_breaker`) | — | None | Security lead alert; H8, ENG | n/a | Re-activation by dual approval |
| 10 | Student under L3 files an unblock request with a legitimate explanation | `APL-` reference, state `submitted` → `under_review`; unrecognised devices revoked on submit; SLA timers set | Unblock §3–§4 | `unblock_requests`, `audit_log` | unchanged | "We've received your request {APL}" | H6 counter | n/a | Proceeds to 11 or 12 |
| 11 | Reviewer approves and revokes suspicious sessions; variant high-risk L4 | Restriction `lift_pending`; reviewer kills the suspicious session (`admin_kill`); after re-verification all sessions revoked (`unblock_reset`); variant: proposal stored in `approval_requests`, `case_decisions` written only when a second reviewer approves | Unblock §5–§6 | `case_decisions`, `approval_requests` (variant), `auth_sessions` ended | FP: signals suppressed | "Finish these steps…", then "Access restored" | Coordinator status only (if policy) | n/a | Complete |
| 12 | Reviewer rejects with a reason | `uphold` with ≥ 50-char student summary; request `rejected`; one appeal in 14 days to a different reviewer; L3 still auto-expires at `ends_at` after re-verification (request then closes `moot`) | Unblock §4.2 | `case_decisions` (`uphold`), notes | unchanged | Decision with plain-language reasons | Senior pool on appeal | n/a | One appeal; DPDP grievance |
| 13 | L3/L4 user calls private content APIs directly; revoked token replayed | Every non-allowed route → `403 account_restricted` (no content); allowed tags work; revoked token → 401; ≥ 30 denials in 10 min → AB-08 (info only) | §7.2 tags; §7.5; AB-08 | Request log; AB-08 | unchanged / info | Restricted screen | None (ENG counter) | n/a (no escalation from probing) | 10 |
| 14 | Same payment webhook delivered repeatedly (incl. hours later) | Signature verified; dedupe on `(gateway, event_id)`; entity re-fetched from the provider; one payment, one entitlement; every valid duplicate gets 2xx; bad signature → 400 `webhook_signature_invalid` + AB-12 | Threat model §2.4 | `payment_webhook_events` (one row), AB-12 for invalid | not a user-risk event | One purchase | Ops alert on signature bursts | **No** | Daily reconciliation |
| 15 | Inactive tab open for hours (lesson tab, then idle) | Keepalives are `neutral`; session idle-expires 60 min after the last engaged activity (`idle_timeout`); next background request → 401 and the client stops; no remember-device re-issue from background requests | §1.4 | `auth_sessions` ended `idle_timeout`, outbox `session.ended` | 0 / none | Signed-out overlay on return | None | **No** | Log in again (silent re-issue only on a user navigation if remembered) |
| 16 | Browser crash during a timed test; reopen on same device (A: cookie kept, B: cookie lost), or (C) continue on the phone | A: same session resumes (cookie survives; idle hold). B: re-login ends the old same-device session (`replaced_same_device`) and **re-attaches** the attempt without consuming a rebind or OTP. C: rebind flow (1 of 2; OTP at ≥ L2); abandoned → SH-08 | §1.4, §7.4 | `attempt_events` `reattach_same_device` / `rebind`; `cap.attempt_bind` | 0 (10 if abandoned) | B: none; C: "This test is open on {device}. Continue here?" | Trainer sees events | **No** | Trainer override for lost time |
| 17 | Multiple tabs / scripted client inflating time | Analytics clamps credit; IN-01/IN-02 recorded; **no sharing signal** | IN-01, IN-02 | Ingest rejections, integrity signals | none | None | Ingest-health dashboard | **No** | Support |
| 18 | Coordinator of college A requests college B's records | 404 for every cross-org id; RLS returns 0 rows; ≥ 20 404s/min or ≥ 5 cross-tenant hits/h → AB-09 alert | AB-09; RLS | `audit_log`, AB-09 | medium (burst high) | Generic not-found | Security lead alert | **No** automatic restriction of staff | Incident process; grant review |
| 19 | Session id altered, revoked token reused, cookie replayed from another browser | Altered/revoked → 401 (DB fallback on Redis miss); replay with a different device cookie → TO-04: **that session** revoked, takeover evaluation +60 → T-step-up; other sessions stay; a second replay within 24 h or "This wasn't me" → HC-T3 → T-protect; 1,000 random tokens from one IP → AB-07 throttle | §7.2; TO-04; HC-T3; AB-07 | `auth_sessions` ended `device_mismatch`; TO-04 signal; evaluation (adults) | T 60 / high | Owner: "We signed out a session that looked unusual" | Takeover queue only on HC-T3 | **Yes**, limited to revoking the replayed session (all sessions only on HC-T3) | Owner signs in again with MFA/OTP |
| 20 | Student disputes a false-positive L3 (laptop + unregistered college lab PC) | `lift_false_positive`; contributing signals suppressed; extension credit; rule and HC FP counters (H8, circuit breaker) | Unblock §5–§6; §5.7 | `case_decisions`, suppression, `entitlement_events` | recomputed → L0 | "Access restored" | H8 | n/a | Complete |
| R-1 | Chrome + Edge on one laptop, same Wi-Fi, both active | 2 devices; S0 × 0.1 (× 0 with fingerprint); "probably this computer" | Case 2; S0 | SH-01 (S0) | ≈ 15 steady → L0 | Devices page grouping | None | No | n/a |
| R-2 | Third login while 2 sessions active; one holds an attempt | Chooser pre-selects the oldest non-attempt session; non-interactive client evicts it; if both hold attempts → `409 session_cap_reached` | Session cap | `cap.session`, `session_cap_evicted` | 0 / info | Chooser | None | No | n/a |
| R-3 | 4th trusted device | After OTP: "Remove a device to continue" | Device cap 3 | `cap.device` | 0 / info | Device-removal flow | None | No | Remove a device |
| R-4 | 3rd replacement within 30 days | Blocked until the date shown; support can grant +1 | Replacement quota | `cap.replacement` | 0 / low | "Next change available on {date}…" | Support ticket | No | Support grant |
| R-5 | Daily incognito, single person, no overlap | SH-06 + SH-05 → at most L1; L3 gate fails (no C, no separated use) | SH-06 | Signals | ≈ 16–24 → L0/L1 | L1 banner "Each browser profile counts as a device" | None | No | Remove stale devices |
| R-6 | 17-year-old overlapping 2 devices for a week, hitting the stream cap | Deterministic caps only; no SH, no score, no L3, no evaluation rows | §4.4 | `cap.*` | n/a | Cap dialogs | None | **No** | Support with parent/college |
| R-7 | Student lifted with `lift_with_warning` in Sept re-offends in Nov | × 1.25 repeat; L3 for 72 h; L4 recommended; reviewer applies L4; lift needs second approval | SH-M1 | Evaluations; case repeat (H9) | ≥ 90 / L3 → L4 | L3 then L4 screen | H1 high; H9 | L3 yes; L4 human | Appeal; dual approval |
| R-8 | Bad rule version restricts 300 students in one org overnight | Kill switch to shadow (single approver, ratified ≤ 24 h); bulk lift by selector with Dual; per-case `lift_false_positive` decisions; credits; notifications | §5.7, §5.8 | `approval_requests`, `case_decisions` × 300 | — | "We made a mistake…" | ENG, H8 | n/a | Complete |
| R-9 | Owner verifies a new office laptop on the office network while a family member streams at home on the same account | SH-13 (10) + S3 overlap if they overlap; L1/L2 at most unless repeated on ≥ 3 days | SH-13; §5.3 | Signals | ≈ 25–45 → L1/L2 | "Confirm it's you" explains both devices | None | No (unless gates later met) | Verify; buddy seat offered |

Severity mapping: L0 = none, L1 = info, L2 = low, L3 = medium, L4 recommended or T-protect = high.

---

## 12. Data model requirements for Architect

Table names follow brief §4. Columns are minimum requirements. Every table has the common columns (`id` uuid v7, `created_at`, `updated_at`), and `organization_id` wherever the table is tenant-scoped. All security tables are **platform-scoped** for RLS: access is by `security_reviewer` grant. An org's coordinator reads only the aggregate views.

| Table | Required columns |
|---|---|
| `users` (identity, owned elsewhere) | `is_minor` bool (derived and stored; age-gate outcome), `age_verified_at`, ~~`account_status` enum(`active`,`restricted`,`suspended`,`deleted`)~~ replaced by cached `restriction_level` smallint 0–4 (written only by `security`; lifecycle stays in `users.status`; reconciliation SEC-DM-01), `sessions_valid_after` timestamptz, `must_change_password` bool |
| `auth_sessions` | All fields in §1.2, incl. status `pending_session_choice`, `created_via = remember_device`, `idle_hold_until`, end reason `replaced_same_device` (CPR-SCH-03). Index (user_id, ended_at), unique(token_hash) |
| `session_network_observations` (new, owner `sessions`) | `auth_session_id`, `user_id`, `net_cluster`, `asn`, `network_type`, `geo_region`, `first_seen_at`, `last_seen_at`. Partitioned monthly on `first_seen_at`; retention R-SEC (CPR-SCH-04) |
| `devices` | `device_key_hash` bytea unique, `client_type`, `first_seen_at`, `last_seen_at`, `ua_family`, `os_family`, `device_class`, `fp_hash` bytea null, `fp_epoch` int null, `shared_organization_id` uuid null FK (lab devices; replaces the proposed `shared_scope` text, reconciliation SEC-DM-03), `shared_registered_by`, `label_hint`, `key_version` smallint (§1.5; CPR-SCH-01) |
| `user_devices` | `user_id`, `device_id`, `trust_status` enum(`pending_otp`,`trusted`,`removed`,`expired`), `trusted_at`, `owner_verified_at`, `verification_method`, `removed_at`, `removed_reason`, `user_label`, `last_used_at`, `counts_toward_cap` bool, `remember_token_hash` bytea null, `remember_until`, `remember_issued_at` (§1.4; CPR-SCH-02). Unique(user_id, device_id) |
| `login_attempts` | `user_id` null, `identifier_hash` (HMAC of the email or phone, to avoid storing unknown identifiers), `ip` inet, `asn`, `network_type`, `device_id` null, `outcome` enum, `failure_reason`, `pre_auth_blocked` bool, `mfa_method`, `key_version` smallint (§1.5). Partitioned monthly |
| `playback_sessions` | `user_id`, `auth_session_id`, `device_id`, `lesson_asset_id`, `started_at`, `last_heartbeat_at`, `ended_at`, `end_reason` enum(`stopped`,`stale`,`taken_over`,`revoked`), `provider_otp_ref_hash` |
| `security_signals` | `user_id`, `family`, `rule_key`, `rule_version`, `category`, `occurred_at`, `base_points`, `multipliers` jsonb, `evidence` jsonb (IDs, prefixes, counts only), `source` enum(`login`,`heartbeat_batch`,`playback`,`attempt`,`nightly`,`system`), `is_minor_at_time` bool (must be false for the `sharing` family, CHECK). `rule_key` values per §4 (SH-*, TO-*, HC-*, AB-*, IN-*, `cap.*`) |
| `risk_rules` | `key` unique, `family`, `category`, `description`, `explanation_key`, `active_version_id` |
| `risk_rule_versions` | `rule_id` null (null = ruleset), `ruleset_version`, `semver`, `definition` jsonb, `status` enum, `effective_from`, `proposed_by`, `approved_by` (CHECK approved_by ≠ proposed_by), `shadow_report` jsonb |
| `risk_evaluations` | The fields in §9, plus `is_minor_at_time` bool with CHECK `NOT is_minor_at_time` (no rows for minors, AMB-12; CPR-SCH-08). Partitioned monthly. Append-only |
| `account_restrictions` | `user_id`, `level` smallint, `family`, `scope` enum(`learning_access`,`status_only`,`protect_lock`), `starts_at`, `ends_at` null, `deferred_until` null, `source` enum(`engine`,`reviewer`), `evaluation_id`, `case_id`, `applied_by`, `ended_at`, `ended_by`, `end_reason`, `decision_id`. Partial unique index: one active restriction per user per family |
| `security_cases` | `case_ref` text unique (§ unblock doc 2), `user_id`, `organization_id` null, `family`, `level`, `priority`, `status`, `assignee_id`, `opened_reason`, `recommended_level`, `is_high_risk` bool, `repeat_count`, `opened_reason` value `engine_hc_L3` added (CPR-SCH-07), `sla_first_response_due`, `sla_decision_due`, `first_response_at`, `closed_at` |
| `unblock_requests` | Fields in unblock doc §3 plus `state`, `state_changed_at`, `submitted_at`, `info_requested_due`, `escalated_at`, `requires_second_approval` bool, `reference` text unique |
| `case_notes` | `case_id`, `author_id`, `visibility` enum(`internal`,`student`), `body` (max 4,000 chars), `attachments` jsonb (S3 keys) |
| `case_decisions` | `case_id`, `unblock_request_id` null, `outcome` enum(`lift_false_positive`,`lift_with_warning`,`lift_conditions`,`uphold`,`convert_L4`,`reduce_level`), `decided_by`, `approved_by` null (CHECK approved_by ≠ decided_by), `approved_at`, `approval_request_id` null FK `approval_requests` (CPR-SCH-05), `rationale`, `conditions` jsonb (e.g. a per-user exception), `extension_days`. Written **only when final**: a decision needing a second approver lives in `approval_requests` until approved (unblock doc §5.1) |
| `policy_settings` | `key`, `scope_type` enum(`platform`,`plan`,`organization`,`user`), `scope_id` null, `value` jsonb, `min`/`max` jsonb, `locked` bool, `version`, `effective_from`, `expires_at` null, `changed_by`, `approved_by`. Unique(key, scope_type, scope_id, version) |
| `activity_heartbeats` (Analytics) | Must include `device_id`, `session_id`, 5-min `bucket`, `kind`, `engaged` bool, so SH-01 can be computed without raw clickstream. Read by security only through `analytics.feeds.get_engaged_buckets` (reconciliation SEC-DM-16) |
| `test_attempts` (Assessments) | `bound_session_id`, `bound_device_id`, `rebind_count` (incremented only when the device changes); `attempt_events.event_type` value `reattach_same_device` (CPR-SCH-06) |
| `approval_requests` (admin) | `action_type` values `security.case.decision`, `security.restriction.bulk_lift`, `risk.kill_switch.ratify`; one pending `security.case.decision` per case (CPR-SCH-05) |
| `audit_log` | Must accept `action` values `security.*`, `case.*`, `policy.*`, `pii.reveal`, `export.*`, with `reason_code` |

**New tables proposed** (see Contract change proposals): `org_trusted_networks`, `user_security_exceptions` (folded into `policy_settings` with `scope_type='user'`, `expires_at` ≤ 180 days, `case_decision_id` required; no separate table), `privacy_requests`, `security_incidents`, `retention_policies`.

---

## 13. Contract change proposals

Reconciled in `contract-reconciliation.md` §2.3; outcomes in the last column.

| # | Proposal | Rationale | Reconciliation outcome |
|---|---|---|---|
| CCP-S1 | Add table **`org_trusted_networks`** (`organization_id`, `cidr` cidr null, `asn` int null, `status` enum(`proposed`,`verified`,`rejected`,`expired`), `proposed_by`, `verified_by`, `evidence_ref`, `expires_at`) | Needed for the CGNAT and college-NAT exceptions (§5.5). Not in the brief's canonical list | → Accepted in brief v0.2 (owner `security`) |
| CCP-S2 | Add **`privacy_requests`** (DPDP rights queue), **`security_incidents`** (CERT-In and DPB clocks) and **`retention_policies`** (registry driving deletion jobs) | Required by `privacy-and-data-retention.md`. The Moodle `tool_dataprivacy` pattern (RPA §6) | → Accepted in brief v0.2 (`privacy_requests`, `retention_policies` → `admin` privacy sub-package; `security_incidents` → `security`) |
| CCP-S3 | Add to brief §1, device policy: "**1 session may hold an in-progress assessment attempt**; rebinding requires confirmation (OTP at ≥L2)" | Research recommends 1 session during assessments (RPA §3); the brief is silent | → Accepted in brief v0.2 (merged with PRD CCP-01; max 2 rebinds, proctored = trainer override; PO-08) |
| CCP-S4 | Clarify brief §1, Minors: "security-necessary" includes **deterministic account-takeover controls** (throttling, breached-password reset, cookie-replay revoke) but no accumulated scores | Avoids ambiguity. Protecting a child's account is not behavioural monitoring (pending counsel question P-2) | → Accepted in brief v0.2 §1 Minors |
| CCP-S5 | Brief §1, Risk engine: state explicitly that **L4 is applied by a human only**. The engine may only *recommend* L4 | Aligns with research ("human review before suspension", RPA §3) | → Accepted in brief v0.2 §1 Risk engine |
| CCP-S6 | Add a **`users.is_minor` + `age_verified_at`** column contract and the rule "unverified age ⇒ minor treatment" | The engine must branch on it at every enforcement point | → Accepted in brief v0.2 (`is_minor` defaults to true; CHECK `is_minor OR age_verified_at IS NOT NULL`) |
| CCP-S7 | Browser-level device counting: document in the Terms that **each browser profile counts as a device**, and that lab devices registered by a college do not count toward personal caps | Avoids disputes in cases 2 and 5 | → Accepted in brief v0.2; customer-facing Terms wording Deferred-to-owner (PO-02) |

**Review-pass proposals (v0.3).** Each is broken down into exact edits per target file in `consistency-pass-requests.md`.

| # | Proposal | Rationale | Status |
|---|---|---|---|
| CCP-S8 | Brief §1 Risk engine: the engine may also apply L3 through **configured high-confidence rules** (HC-01/HC-02; shadow-first, per-rule switch, circuit breaker); network separation classes replace the owner-verified discount | Owner scenario 9; OTP relay (AMB-01/03/18) | Proposed (CPR-BRF-01, -02) |
| CCP-S9 | Brief §1 Sessions/Timeouts: idle-effect classes, attempt idle hold, remember-device refresh only on user navigation with a fixed 30-day ceiling | AMB-05/06/07 | Proposed (CPR-BRF-03) |
| CCP-S10 | Brief §1 Device policy: same-device re-login re-attaches an attempt without consuming a rebind | AMB-08 | Proposed (CPR-BRF-04) |
| CCP-S11 | Schema: `session_network_observations`, key versions, remember-token columns, `auth_sessions` enum additions, `case_decisions.approval_request_id`, `risk_evaluations.is_minor_at_time` | §1.2, §1.4, §1.5, §4.4; unblock §5.1 | Proposed (CPR-SCH-*) |
| CCP-S12 | Permissions `security.engine.kill_switch`, `security.restriction.bulk_lift`, `policy.propose` | §5.7, §5.8, §3.1 | Proposed (CPR-RPM-*) |
