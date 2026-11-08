# Tech Drona LMS — Testing and Acceptance Criteria

> **Single-company note (2026-11-06).** Tech Drona now runs as a single company ([ADR-0015](architecture-decisions/ADR-0015-single-company.md)); the college/B2B features described in this document (college portal and coordinators, institution contracts and seats, invitations and roster import, per-organization settings, trusted networks and lab devices, the "For colleges" page) are removed. Roles are Admin (`super_admin`), Trainer, Evaluator, Content manager and Student; finance, support, security and mentor duties belong to Admin. Batches are Tech Drona cohorts managed by Admin at `/admin/batches`; businesses use the corporate enquiry form at `/enquiries`. Acceptance tests for college/coordinator flows are retired; cross-org isolation tests become batch/student isolation tests; E2E uses an `E2E_EVALUATOR_*` account instead of `E2E_COORDINATOR_*`. Where this document conflicts, ADR-0015 and [`single-company/REMOVAL-PLAN.md`](single-company/REMOVAL-PLAN.md) §8 win.

Owner: QA & Security Testing Lead (wave 2). Status of every item in this document: **Planned** (brief §7).
Version: v0.2 (2026-11-03). Contracts: `docs/blueprint-brief.md` v0.3 and `docs/contract-reconciliation.md` win over every other document. Where a wave-1 document still disagrees, this plan tests the brief/schema value and lists the conflict in §5 or §13.

## Changelog

### v0.2.1 — 2026-11-03 (Security Specialist, final cleanup)

- AMB-22, AMB-23, AMB-24 **Resolved** by RE v0.4 (§4.2.1/§5.1, §3.2/§5.7, §5.7); KS-07, CB-03, CB-06, SCN-01 variant 1-B updated and their `xfail` markers removed; I-13 closed.
- Section H export approval split (API I-26): RPT-01 and RPT-03 updated, RPT-05 added (security/monitoring exports approved by a second `security_reviewer`; other exports by `super_admin`; `super_admin` cannot approve security exports).

### v0.2 — 2026-11-03 (QA Lead, consistency pass)

- Applied all 21 security change requests CPR-TST-01..21 (`consistency-pass-requests.md` §5) and all 8 integration requests IPR-QA-01..08 (`integration-pass-requests.md` §2).
- Re-verified the 20 owner scenarios against `account-security-and-risk-engine.md` (RE) v0.3: separation classes S0–S3 replace the owner-verified ×0.25 multiplier (SCN-01, 05, 08); HC-01/HC-02 auto-L3 and HC-T1..T3 (SCN-09); SH-13 OTP-relay detection (SCN-05); AB-/IN- rule IDs replace undefined detections (SCN-04, 06, 13, 14, 17, 18, 19); stolen-cookie replay revokes only the replayed session unless HC-T3 confirms (SCN-09, 19); idle semantics `x-td-idle` and `idle_hold_until` (SCN-15); same-device crash re-attach without rebind (SCN-16); webhook re-fetch, no age-based rejection (SCN-14); Section H ids H1–H12 + ENG.
- §4.1 and §4.22 re-keyed to the RE §11 owner numbering; regression ids RX-nn replaced by RE ids R-1..R-9 (RX-06 is now RE row 9d inside SCN-09).
- §5: AMB-01..21 all **Resolved** with pointers; new open items AMB-22..24 found during re-verification.
- New §2.16 tests: kill switch with 24 h ratification, HC circuit breaker, bulk false-positive lift with Dual, HMAC key versioning/rotation, `approval_requests` lifecycle, separation classes and SH-13, accepted under-detection of the mobile-only sharer, abuse/integrity registry boundaries, 395-day log retention, Section H report access.
- §6 re-keyed to the canonical 12-stage order of `implementation-roadmap.md` §2; §13 issues closed.

### v0.1 — 2026-11-03

Initial plan.

Inputs read: `source-requirements-excerpt.md` (Phase-8 list, verbatim, authoritative numbering), `account-security-and-risk-engine.md` (RE), `account-unblock-workflow.md` (UNB), `security-threat-model.md` (TM), `analytics-event-schema.md` (AN), `product-requirements.md` (PRD), `role-permission-matrix.md` (RPM), `system-architecture.md` (ARCH), `database-schema.md` (SCHEMA), `privacy-and-data-retention.md` (PRIV).

Identifier conventions used here:

| Prefix | Meaning |
|---|---|
| `TS-*` | Test suite (§2) |
| `SCN-01` … `SCN-20` | The product owner's Phase-8 scenarios, **numbered exactly as the owner numbered them** (§4) |
| `RE-n` | Row *n* of `account-security-and-risk-engine.md` §11, which uses the owner numbering (rows 1–20 with sub-rows 5a–5c, 6a–6c, 9a–9f; mapped in §4.1) |
| `R-n` | Regression scenarios R-1..R-9 of RE §11 that the owner list does not cover (§4.22); same ids as RE |
| `AMB-nn` | Ambiguity or inconsistency found in the security design (§5), with its resolution status |
| `KS-`, `CB-`, `BL-`, `HK-`, `AR-`, `SEP-`, `SH13-`, `UD-`, `ABR-`, `RET-`, `RPT-` | Engine-control and new-mechanism test cases (§2.16) |
| `G-nn` | CI / release gate (§10) |
| `AC-*` | PRD acceptance criteria (PRD §9), reused verbatim by ID |

---

## 1. Principles

1. **The server is the system under test.** Every rule is proven at the API and database layers. A UI check is supplementary, never the only evidence (§8 Definition of Done).
2. **Deny by default is tested by enumeration, not by example.** Authorisation, route guards, RLS and restriction gates are tested by generated suites that cover *every* route and *every* tenant table (TS-AUTHZ, TS-RLS, G-05).
3. **Time is injected.** All tests run against the kernel `core.clock` with a controllable clock. No test sleeps for real time. Decay, SLAs, retention, idle timeouts and deadlines are tested by moving the clock.
4. **Determinism.** Risk-engine and time-tracking scenarios are executable fixtures with golden values (RE §11, AN §8). A change to a rule version, a `tm-*` version or a policy default must change a golden file in the same PR, and that PR needs the Security Specialist (risk) or Analytics Engineer (time) as reviewer.
5. **Minors are a first-class test dimension.** Every security, analytics and privacy suite runs its fixtures twice: adult with `security_monitoring` consent, and minor (including the unverified-age default). The minor run must produce *no* sharing-family data (brief §1).
6. **Independent verification.** QA re-runs acceptance on a fresh environment built from the release artefact. The implementing developer cannot be the sole verifier of a feature (§8).
7. **No real personal data in any non-production environment** (§9).

---

## 2. Test strategy and pyramid

### 2.1 Pyramid and ownership

| Level | Suite | Tooling | Runs where | Trigger | Target share / budget |
|---|---|---|---|---|---|
| Unit | TS-UNIT | pytest, Hypothesis (property tests), Vitest for TS | CI runner, no network | Every PR | ~65 % of tests; full run < 4 min |
| Integration | TS-INT | pytest + Testcontainers (Postgres 16, Redis `cache` + Redis `queue`), Alembic `upgrade head` applied, app connected as `td_app` | CI runner | Every PR | ~20 %; < 12 min with sharding |
| API contract | TS-CON | Schemathesis (OpenAPI-driven fuzz + examples), `oasdiff` breaking-change check, generated `packages/api-client` diff | CI runner | Every PR (smoke), nightly (full) | All routes |
| Authorisation matrix | TS-AUTHZ | pytest generator over route registry × roles × scopes × restriction states (§2.5) | CI (integration env) | Every PR | 100 % of authenticated routes |
| RLS | TS-RLS | pytest against migrated DB as `td_app` (§2.6) | CI | Every PR and every migration | 100 % of tenant tables |
| Security regression | TS-SEC | pytest, ZAP (DAST), Semgrep, custom attack scripts (§2.7) | CI + staging | PR (fast set), nightly, weekly DAST | ASVS L2 selection, API Top 10 |
| Session | TS-SESS | pytest integration + Playwright | CI | Every PR | TM §6 "session tests" |
| Risk engine | TS-RISK | Deterministic fixture harness (§2.11, §2.16) | CI | Every PR | SCN + R-1..R-9 fixtures + §2.16 cases |
| Unblock workflow | TS-UNB | pytest integration + Playwright | CI | Every PR touching `security`, `notifications` | State machine 100 % transitions |
| Judge sandbox | TS-JUDGE | Escape corpus runner (§2.8) | Judge staging account | Weekly + every judge image change | Corpus 100 % blocked |
| Payments | TS-PAY | pytest + Razorpay **test mode** + webhook replay harness (§2.9) | CI (replay), staging (live test mode) | PR touching `commerce`/`entitlements`; nightly live | All lifecycle states |
| Time tracking | TS-TIME | Simulation harness + Playwright browser lifecycle (§2.10) | CI | Every PR touching `analytics`, `sessions`, web SDK | AN §3.13 golden examples + properties |
| Data quality | TS-DQ | pytest over pipeline outputs (AN §8) | CI nightly | Nightly | AN §8 items 1–6 |
| End-to-end | TS-E2E | Playwright (Chromium, Firefox, WebKit; Android/iOS emulation at 360 px) | Ephemeral preview env | PR smoke (≤ 10 min), nightly full | Journeys J1–J6 + SCN E2E steps |
| Performance | TS-PERF | k6 (+ xk6-browser for web vitals), Lighthouse CI | Dedicated perf env sized like prod | Weekly, before every release, before every drive season | NFR targets (§2.12) |
| Accessibility | TS-A11Y | axe-core in Playwright, Lighthouse a11y, manual NVDA/TalkBack/VoiceOver | CI + manual | PR (axe), per release (manual) | WCAG 2.2 AA (§2.13) |
| Backup / DR | TS-DR | Runbooks + scripted verification | Isolated restore account | Monthly restore, quarterly failover | NFR-AVL-02 (§2.14) |
| Privacy | TS-PRIV | pytest + time-travel fixtures | CI + nightly | Every PR touching personal data | §2.15 |
| Migrations | TS-MIG | Alembic checks (§10 G-04) | CI | Every PR with a migration | All revisions |

### 2.2 Unit tests (TS-UNIT)

- Pure domain logic only: risk scoring formula (RE §5.1), level gates and hysteresis (RE §5.3), policy resolution precedence and bounds (RE §3.1), unblock state-machine guards (UNB §4.2), entitlement precedence/union (PRD AC-ENT-01), refund eligibility (AC-COM-04), interval crediting and union/attribution (AN §3.3–§3.5), clock-skew correction (AN §1.3), mastery update (AN §6.2), case reference generator (UNB §2: alphabet, length, no I/L/O/U), password policy and Argon2 parameters, problem+json builders.
- Property-based (Hypothesis) where an invariant exists: `Σ attributed = |⋃ A_u| ≤ wall-clock`; `M5 ≤ M2 ≤ M1`; score ∈ [0, 100]; network subtotal ≤ `risk.network_points_cap`; no sequence of signals moves `level_after` to 4 (mirrors SCHEMA `ck_re_no_auto_l4`); policy overrides outside bounds always rejected.
- No database, Redis or network. Clock injected.

### 2.3 Integration tests (TS-INT)

- Testcontainers: `postgres:16` with the production extensions (`pg_partman`, `pgcrypto`), two Redis containers configured like the brief (`cache` with eviction allowed, `queue` with `noeviction`), MinIO for S3, Mailpit for email, an SMS stub, a VdoCipher stub, a Judge0 stub and a Razorpay stub (recorded test-mode payloads).
- Every session starts from an empty database and runs `alembic upgrade head` as `td_owner`; tests connect as `td_app` (non-owner, no BYPASSRLS) so RLS is always live (ARCH §6.5). A guard test fails the session if `td_app` owns any table or has BYPASSRLS.
- Transactions: each test runs in its own transaction or schema clone; Celery runs eager for unit-of-work tests and with a real worker for outbox/beat tests.
- Outbox: tests assert that every state change that the brief lists (`session.ended`, `account.restricted`, `restriction.lifted`, `consent.changed`, `age_tier.changed`, `entitlement.granted/revoked`, `attempt.submitted`) writes exactly one `outbox_events` row in the same transaction as the change.
- Audit: tests assert `audit_log` rows (actor, `reason_code`, before/after) and that UPDATE/DELETE on `audit_log` fail for every app role, including the role used by super_admin actions (TM §2.2 R).

### 2.4 API contract tests (TS-CON)

- The OpenAPI document generated by FastAPI is the contract; it is snapshotted per PR and diffed with `oasdiff`. Breaking changes on `/api/v1` fail G-08 unless the PR carries the `api-breaking-approved` label from the Backend Lead.
- `packages/api-client` must regenerate with no diff (ARCH §20).
- Schemathesis runs every operation with: valid examples; negative fuzzing (`extra` fields must be rejected — Pydantic `extra="forbid"`, TM §2.2 T); oversize bodies (413); `limit` > 100 (422); missing `Idempotency-Key` on money/attempt/submission/unblock POSTs (422 or 400 per spec); every error must be RFC 9457 problem+json with `type`, `title`, `status`, `detail`, `code`, `request_id`, and no stack trace.
- Conformance: every route declares permission + scope, a route tag (`x-td-route-tag`: `public`, `login_continuation`, `account_status`, `l3_readonly`, `mfa_enrolment`, `consent`, `default`; RE §7.2) and an idle effect (`x-td-idle`: `extends`, `engaged_only`, `neutral`; RE §1.4) in its OpenAPI extension (input to TS-AUTHZ and G-05). `/docs` and `/openapi.json` return 404 in the production profile (TM §2.2 I).
- Canonical error codes asserted (IPR-QA-07): stream cap `409 playback_conflict`; step-up needed `401 step_up_required`; staff without a factor `403 mfa_enrolment_required`; maintenance mode (`platform.maintenance_mode`) `503 maintenance` with `Retry-After`; restriction `403 account_restricted`; L2 device `403 device_verification_required`; session cap with only attempt-holding sessions `409 session_cap_reached`; short session `409 session_too_short_for_attempt`; invalid webhook signature `400 webhook_signature_invalid`; hard-disabled account `401 invalid_credentials` (identical body and timing to an unknown user, CPR-API-15).

### 2.5 Authorisation matrix tests (TS-AUTHZ)

**Source of truth.** `apps/api/app/core/authz/permissions.yaml`, generated from `role-permission-matrix.md` §2, §3 and §5 (role matrix v0.2 §10; permission → role → scope letter, sensitivity, step-up, dual), plus the route registry (route → permission, scope resolver, route tag, idle effect). §13 I-04 resolved.

**Generation.** For each authenticated route the generator builds the cartesian product:

| Dimension | Values |
|---|---|
| Role | the 9 canonical roles + a user with no grants + a multi-role user (e.g. trainer + mentor) |
| Scope relation of target object | own object (self), same batch, sibling batch same org, same org, **other org**, platform catalog, org-private course of own org, org-private course of other org |
| Restriction state (derived per request, RE §7.2) | L0, L2 (device in the L2 evidence, not yet re-verified), L3 `restricted`, L3 deferral (attempt-bound session: `full` for that attempt's routes only), L4 `status_only`, T-protect (only `login_continuation` + recovery), pending statuses (`pending_mfa`, `pending_device_otp`, `pending_session_choice`) |
| Session tier freshness | step-up fresh (inside 5/10/15 min window), stale |
| Grant state | active, expired (`expires_at` past), revoked, changed since login (must force re-login, brief §1) |

**Expected outcome** is computed from the matrix, not hand-written: `2xx` if allowed; `401` for no/expired/revoked session; `403 account_restricted` (with `case_ref`) when the restriction gate denies (brief §5); `403` with step-up code when freshness is stale; **`404` when the object belongs to another org** for org-scoped principals (RPM TI-02); `403` for platform principals lacking the permission (BFLA).

**Additional generated checks.** SoD-01..SoD-11 (e.g. granting `finance_admin` to a `security_reviewer` is rejected; author ≠ publisher; requester ≠ approver); every Dual action in RPM §5 creates an `approval_requests` row and does not take effect until a distinct approver approves within 72 h (lifecycle in §2.16 AR-*); break-glass (`BG`) permissions work only inside an active break-glass session and are flagged for review. Named cases (IPR-QA-02): `report.export.approve` approver ≠ requester; `policy.propose` (security_reviewer) accepted only for the `risk.*`, `sessions.*`, `devices.*`, `playback.*`, `assessment.*`, `login.*`, `otp.*`, `unblock.*` namespaces and refused elsewhere, while `policy.edit` stays super_admin + Dual; `security.incident.*` and `security.network.verify` succeed only for `security_reviewer` (super_admin can read incidents but every write is 403); `security.engine.kill_switch` and `security.restriction.bulk_lift` per §2.16.

**Size.** Roughly 400 routes × 11 principals × 8 relations ≈ 35k cases before pruning; the generator prunes impossible combinations and runs in parallel shards (target < 8 min). A route with no generated cases fails the suite.

### 2.6 RLS tests (TS-RLS)

For every table whose SCHEMA RLS family is `T`, `TN`, `U` or `O`:

1. `relrowsecurity` and `relforcerowsecurity` are true; at least one policy exists for SELECT, INSERT, UPDATE, DELETE (or ALL) with a matching `WITH CHECK`.
2. As `td_app` with `app.org_ids = A`: SELECT of org-B rows returns 0; INSERT with `organization_id = B` fails; UPDATE moving a row from A to B fails; DELETE of B rows affects 0 rows.
3. **Fail closed:** with no tenant context set, SELECT returns 0 rows (not all rows).
4. `app.is_platform = 'on'` is only set for principals with a platform grant and for named system jobs; a test enumerates code paths that set it (static check) and runs each as a non-platform user.
5. Partitioned tables: a newly created partition (pg_partman pre-make) inherits the policy; test creates next month's partition and repeats checks 1–3.
6. Context leakage: 200 concurrent requests alternating tenants over a pooled connection; no response contains another tenant's row (transaction-local `set_config(..., true)`, ARCH §6.5).
7. Existence probing: uniqueness/FK violations across tenants surface as generic 409/422 without the conflicting value (TM §2.2 I, RPM TI-05); importing an email that exists in another org returns "invite sent".
8. Views and functions: every view is `security_invoker`; any `SECURITY DEFINER` function is on an allowlist reviewed by the Security Specialist.

### 2.7 Security regression (TS-SEC)

#### 2.7.1 OWASP ASVS 5.0 Level 2 selection (Level 3 on finance, security and super-admin consoles, NFR-SEC-01)

The full checklist with evidence links is tracked per requirement as a pre-launch gate (TM §6). The automated selection below runs continuously.

| ASVS chapter | Automated checks (suite) |
|---|---|
| V1 Encoding & sanitisation | Output encoding of user text (unblock explanation, ticket messages, display names) in React and in emails; no `dangerouslySetInnerHTML` (Semgrep); maths rendering sanitised (TS-SEC, TS-E2E) |
| V2 Validation & business logic | Pydantic `extra="forbid"` on all inputs; `role`, `organization_id`, `score`, `price` never accepted (TS-CON); coupon/OTP/playback/unblock business-flow limits (RE §3.2, TM §4.1) (TS-SEC nightly) |
| V3 Web frontend | CSP, HSTS preload values, `X-Content-Type-Options`, `Referrer-Policy: no-referrer` on reset pages, `Clear-Site-Data` on logout with device cookie re-set (RE §8), `Cache-Control: no-store` on authenticated responses |
| V4 API & web service | CORS exact-origin allowlist (no wildcard, `Origin: null` rejected); CSRF signed double-submit + Fetch Metadata; beacon route accepts body token only with `Sec-Fetch-Site: same-origin` (brief §5) |
| V5 File handling | Unblock attachments: ≤2 files, ≤5 MB, PDF/PNG/JPG by magic bytes, AV scan, EXIF stripped, private S3 SSE-KMS (UNB §3); presigned uploads ≤25 MB; signed URL TTL 5 min / 1 min paid PDFs |
| V6 Authentication | NIST password rules (15/8 chars, ≥64 max, no composition rules, blocklist incl. "techdrona"); Argon2id parameters; uniform login errors and timing ±50 ms (AC-IDN-02); progressive back-off and hard disable at 50; pre-auth blocks not counted; MFA required for staff/privileged, SMS/email refused for staff; TOTP single-use timestep; recovery codes hashed; reset does not bypass MFA |
| V7 Session management | §2.7.3 session tests |
| V8 Authorisation | TS-AUTHZ, TS-RLS, `require_active_principal` route check (G-05) |
| V9/V10 Tokens, OAuth | Only if mobile JWT ships: ES256 pinned, refresh family revocation on reuse (TM §4.2) |
| V11 Cryptography | Session token 256-bit CSPRNG, SHA-256 at rest; device key HMAC-SHA-256 (32 bytes) with `key_version`; identifier HMAC with `key_version` (rotation tests §2.16 HK-*); KMS envelope for hidden tests; constant-time compare for webhook HMAC and tokens (Semgrep custom rule `==` on secrets) |
| V12 Secure communication | TLS ≥1.2 (testssl.sh weekly on staging/prod endpoints) |
| V13 Configuration | Debug off, docs endpoints off, IaC scans (Checkov/tfsec), S3 Block Public Access, IMDSv2 hop limit 1 |
| V14 Data protection | No raw IP in `risk_evaluations.evidence`; masked IPs in support views; PII never in logs (log scanner over test-run logs: no passwords, OTPs, session tokens, full card data, Aadhaar/PAN patterns) |
| V15 Secure coding & architecture | import-linter module boundaries; one writer per table manifest; SBOM per release |
| V16 Logging & errors | `request_id` in every problem+json; security events logged (validation failures, authz denials); audit hash chain verifies end-to-end (TS-INT) |

L3 additions for privileged consoles: passkey/TOTP only, 15 min / 8 h timeouts, step-up 5 min before refund, role grant, policy change, case decision and bulk export; new-device privileged login alerts the security lead; dual control for Dual actions; break-glass alerting.

#### 2.7.2 OWASP API Security Top 10 (2023)

| Risk | Test focus | Suite |
|---|---|---|
| API1 BOLA | ID swaps on attempts, submissions, certificates, invoices, cases, unblock requests, rosters, exports; cross-org returns 404 | TS-AUTHZ, SCN-18 |
| API2 Broken authentication | Login/OTP/reset limits (TM §4.1), reset token single-use 30 min, no auto-login after reset, session fixation, SCN-19 | TS-SESS, TS-SEC |
| API3 BOPLA | Mass assignment; response models never expose hidden tests, answer keys, other users' emails (leaderboards), evidence fields to support | TS-CON, TS-JUDGE |
| API4 Resource consumption | Page limit, body size, request timeout 15 s, Argon2 semaphore, OTP quotas, judge queue caps, export quotas | TS-SEC nightly |
| API5 BFLA | Admin/finance/security routers under separate prefixes deny every non-granted role | TS-AUTHZ |
| API6 Sensitive business flows | Coupon brute force (10/h, 20 failures/day), trial farming, SMS pumping (3/h, 10/day per number, +91 only), playback token minting (30/h), question scraping (≤50/request, 2,000/day) | TS-SEC nightly |
| API7 SSRF | No user-supplied URL fetch exists in v1 (Semgrep rule bans outbound HTTP with user-controlled URL) | TS-SEC |
| API8 Misconfiguration | Headers, CORS, S3, debug, staging behind SSO + IP allowlist | TS-SEC, DAST |
| API9 Inventory | Router-registry inventory equals deployed OpenAPI; no `/api/v0`; staging not public | G-08 |
| API10 Unsafe consumption | Third-party response schema validation (Judge0, Razorpay, VdoCipher, HIBP, IP-intel), 5 s timeouts, circuit breakers; payments fail closed, HIBP fails open with log | TS-INT (fault injection) |

#### 2.7.3 Session and CSRF tests (TS-SESS)

Cookie attributes (`__Host-` prefix, Secure, HttpOnly, SameSite=Lax, Path=/); session cookie `Max-Age` = seconds to `absolute_expires_at` (lab devices: no `Max-Age`), so it survives a browser restart (RE §1.4 rule 6); token rotation on login and privilege change; idle and absolute timeouts per tier (student 60 min/24 h, staff 30 min/12 h, privileged 15 min/8 h, lab device 30 min, remember-device ≤30 days trusted only); idle effect per route (`x-td-idle`): `extends` slides idle, `engaged_only` slides only via `sessions.touch_engaged` when the batch credits > 0 active s / playback advanced / an answer changed, `neutral` never; a browser-sent `X-TD-Activity` header is stripped by the BFF and has no effect; `idle_hold_until = deadline_at + grace + 5 min` while an attempt is held; remember-device re-issue only on a top-level navigation with a valid rotated `__Host-td_remember` and `now < remember_until` (fixed, never slides), never from XHR/beacon/prefetch, never at ≥ L3 or T-protect; a superseded remember token → TO-10 (remember credential and presenting session revoked); revoke one, revoke all via `sessions_valid_after`; device mismatch (TO-04) and UA/OS-family drift (TO-08) revoke **only** the presented session; Redis miss → Postgres lookup, unknown in both → 401 (AB-07 counter); same-`device_id` login ends the older session as `replaced_same_device` before the cap check; at the cap the pending session has `status = pending_session_choice`, the chooser pre-selects the oldest session without an active attempt, and the pending session expires after 5 min (IPR-QA-05); non-interactive clients evict only non-attempt sessions, else `409 session_cap_reached`; grant change forces re-login; scope derived per request (`restricted`/`status_only`; `auth_sessions.scope` is a record only); logout clears site data but keeps the device cookie; CSRF: cross-site POST, missing token, `Origin: null` rejected.

### 2.8 Judge sandbox escape tests (TS-JUDGE)

**Phase 1 (Judge0 Cloud behind `judge-gateway`).** Scope is our gateway: hidden test confidentiality (AC-COD-01: no hidden input/expected output in any API response, browser bundle, log line or error), verdict recomputation (a stub judge returning "Accepted" with wrong output must be graded wrong), per-user queue limits (2 in flight, 30 per 10 min), probe detection (≥20 submits/problem/hour flagged), callback HMAC + nonce, outage behaviour (AC-COD-02: queued + audited deadline extension).

**Phase 2 (self-hosted, separate VPC/account).** Corpus per supported language, each expected to end in a resource-limit verdict or a clean failure with **no** host impact:

| Category | Probes | Expected |
|---|---|---|
| Process | fork bomb, thread bomb, `kill -9 -1`, ptrace, setuid binaries | ≤64 processes; no effect outside the box |
| CPU / wall | infinite loop, `sleep(60)`, busy-wait with signals ignored | CPU 5 s, wall 10 s verdicts |
| Memory | allocation bomb, mmap tricks, compile-time template bomb | 512 MB limit, compile timeout |
| Output / files | 1 GB stdout, stderr flood, file write > 1 MB, fill `/tmp` | Output ≤64 KB, file ≤1 MB |
| Network | DNS lookup, TCP to internet, to `169.254.169.254`, to RDS/Redis endpoints, raw sockets | All fail; egress-deny alert fires |
| Filesystem | read `/proc/self/environ`, `/proc/1/*`, `/sys`, host mounts, other submissions' dirs, hidden-test files, symlink and path traversal | Nothing sensitive readable; no secrets in env |
| Privilege | known Judge0/isolate CVE reproductions (incl. the Tanto Security class), cgroup escape, `--privileged` misconfig detection | Blocked; image scan clean; container runs non-root, read-only root FS, no `--share-net` |
| Side channels | stdin echo on hidden cases, exit-code encoding, timing encoding | Hidden-case feedback is verdict/time/memory only; probe-rate flag raised |

Infrastructure assertions on every judge image change: no credentials on judge hosts, IMDS blocked from sandboxes, Falco/auditd rules fire on the corpus, patch SLA 72 h tracked. Penetration test covers the judge before launch (TM §6).

### 2.9 Payment lifecycle tests (TS-PAY)

**Live test mode (staging, nightly).** Razorpay test mode with test cards and test UPI handles: order → checkout → `payment.authorized` → `payment.captured` → `order.paid` → entitlement grant → GST invoice (gap-free `invoice_sequences`); failure; partial and full refunds (`refund.processed`) with entitlement effect per refund rule (AC-COM-04); subscriptions (`subscription.authenticated/activated/charged/pending/halted/cancelled`) with grace 5 days (AC-ENT-02); one-click cancel (AC-COM-05); recurring price > ₹15,000 rejected at configuration (AC-COM-03). Cashfree fallback adapter runs the same contract suite.

**Replay harness (CI, every commerce PR).** Recorded test-mode payloads (stored with PII removed) are replayed against `api-webhooks`:

| Case | Expected |
|---|---|
| Same event 3× sequentially | One payment, one entitlement, one invoice (AC-COM-01); duplicates answered 2xx; `payment_webhook_events` unique `(gateway, event_id)` holds |
| Same event 3× concurrently (parallel requests) | Same as above; no deadlock; side effect and dedupe row in one transaction |
| Two different events for the same payment (`payment.captured`, `order.paid`) | Domain-level idempotency on payment/order: still one entitlement |
| Out of order (`captured` before `authorized`; `refunded` before `captured`) | Monotonic state machine: illegal backwards transition rejected and logged; forward-only state reached |
| Invalid HMAC, tampered body, wrong secret, missing header | `400 webhook_signature_invalid`, no state change, payload not processed (only its hash kept); `security_signals` `rule_key = AB-12`, `family = abuse`, source-level (`user_id` NULL); ops alert when > 10/min per provider (RE §4.5) |
| Amount or currency mismatch vs `orders` | No entitlement; finance alert |
| Unknown order id | Stored, `ignored`, reconciliation picks it up |
| Old event (retry after hours) | No request is rejected for age (AMB-10 resolved, TM §2.4). Same `event_id` 6 h later → 2xx `duplicate`, no effect. A different valid event for the same payment hours later → 2xx, entity re-fetched from the provider, no second grant (`refetch_status = ok`). Razorpay event older than 5 min → processed via re-fetch, not rejected (IPR-QA-06). Cashfree payload older than `WEBHOOK_TOLERANCE_SECONDS` (300) → payload not trusted; state applied only from the re-fetch (ADR-0006 v0.3) |
| Provider API down during re-fetch | Event stored, re-fetch retried with back-off; no state change until a re-fetch succeeds; DLQ after max retries; lag alert per NFR-OBS-02 |
| Subscription grace | `subscription.halted`/payment failure → entitlement kept for 5 days (`commerce.subscription_grace_days`), revoked on day 6 if unpaid (IPR-QA-06) |
| Goodwill refund | Cannot reach `approved` without a non-null `refunds.approval_request_id` whose request is `approved` by a second finance approver (IPR-QA-06) |
| Secret rotation with 24 h overlap | Both secrets accepted during overlap, only new after |
| Client "success" redirect without webhook | Pending state only; entitlement only after verified webhook or server-to-server status fetch (TM §2.4 E) |
| Webhook flood 100 rps to `/api/v1/webhooks/{provider}` | 2xx in < 1 s after enqueue; DLQ on processing failure; NFR-OBS-02 lag alert > 5 min |

Daily reconciliation job is tested against a fake settlement report with one missing and one extra payment.

### 2.10 Time-tracking simulation tests (TS-TIME)

**Harness.** A deterministic generator produces heartbeat/event streams per page instance (tab), device and session from a scenario script, with the injected clock and a configurable client clock offset. Streams go through the real ingest API (`POST /analytics/events`, `/beacon`), the interval builder (AN §3.4) and the daily aggregation, and outputs are compared with golden values.

| Area | Cases | Expected (source) |
|---|---|---|
| Golden examples | AN §3.13 Examples 1–6 as fixtures | Exact M1–M5, coverage, attribution, `multi_device_overlap_s` values in AN §3.13 |
| Multi-tab | 2–7 visible/hidden tabs, video in one tab, practice in another, same window vs two windows | Union ≤ 1 s per wall-clock second; hidden tab earns no M2; hidden playback flagged; Σ attributed = M2 |
| Idle | No input for `T_idle(surface)`; keepalives every `K` for hours | Credit stops at last input + `T_idle`; keepalives (`x-td-idle = neutral`) earn 0 and do not extend the auth session; an ingest batch extends idle only when it credits > 0 active seconds (`touch_engaged`) (SCN-15) |
| Crash | No terminal event; last flush lost | Interval closed at `t_n + G` with `timeout_grace`; under-count only (Example 3) |
| Late events | 48 h late; 73 h late | 48 h accepted and dirty-day recompute changes D-2; 73 h rejected `event_too_old` (AN §8.4) |
| Duplicates | Same batch retried 10× | Identical row counts; `duplicate` statuses (AN §8.2) |
| Out of order | Shuffled `seq` | Builder orders by `(page_instance_id, seq)`; gaps flagged `seq_gap`, never filled |
| Clock skew | Client clock ±3 h, ±10 min, jump mid-page, device sleep | `effective_at` within 1 s of server time (AN §8.3); `large_skew` and `clock_jump` flags; UUIDv7 time mismatch rejected |
| Day boundary | Interval across IST midnight | Split per `Asia/Kolkata` day; UTC storage |
| Freeze and backfill | Late event after D+4 | No recompute without explicit audited backfill |
| Version mixing | Aggregates under `tm-1.0` and `tm-1.1` | Comparison refused / banner shown |
| Manipulation | SCN-17 cases | §4.18 |
| Minors | Same fixtures with `privacy_tier = minor` | No P-purpose events stored, no `security_activity_feed_daily` rows, no `multi_device_overlap_s` (AN §8.6) |

**Browser-level (Playwright).** Real lifecycle signals: `page.bringToFront`, CDP `Emulation.setFocusEmulationEnabled`, `Emulation.setIdleOverride`, `context.setOffline`, killing a browser context without `pagehide` (crash), bfcache back/forward, SPA route change, `sendBeacon` fallback with CSRF body token. Android webview and iOS behaviour are checked manually per release (AN §9.7).

### 2.11 Risk-engine simulation harness (TS-RISK)

- Fixture format: personas (age tier, consent, `is_synthetic`, devices with trust state, `owner_verified_at` and `verification_method` (SMS OTP / passkey / TOTP = owner-verified for 30 days; email OTP = trusted only), network clusters with ASN, `network_type` and state, `session_network_observations` timelines, lab/trusted-network registrations) + a timeline of logins, engaged 5-minute buckets (supplied through a fake `analytics.feeds.get_engaged_buckets`), playback takeovers, OTP outcomes, verifications, attempts.
- Precondition: the launch default is `risk.mode = shadow` and `risk.hc.auto_restrict_enabled = false` (RE §3.2). Every fixture states both values explicitly. The harness runs the real `security` module with `risk.mode = enforce` and again with `shadow`, and asserts `security_signals` (incl. `multipliers.separation_class` and `counted`), `risk_evaluations` (score ±0.5, level, gates incl. `separated_days` and `hc_rule`, action, `explanation_keys`), `account_restrictions`, `security_cases` (`opened_reason` `engine_L3` / `engine_hc_L3` / `engine_recommend_L4`), sessions ended and `end_reason`, notifications, outbox events, and audit rows.
- Golden expectations are parameterised by the active ruleset version (`sharing-1.0.0`) and reproduce RE §5.1 worked examples A (≈ 15 → L0; email-only phone ≈ 45 → L2, re-weighted to ≈ 15 after SMS verification), B (≈ 71 → L3; 2-day variant ≈ 55 → L2) and C (≈ 15–25 → L0/L1). A rule change regenerates goldens and the PR diff is reviewed as part of the ≥14-day shadow report (RE §5.4).
- The same fixture runs for a minor and must produce **no** sharing signals and **no `risk_evaluations` row of any family** (SCHEMA `ck_sig_minor`, `ck_re_no_minor`; AC-SEC-04; AMB-12 resolved). Deterministic takeover actions for minors appear only as `security_signals` (`family = takeover`, `base_points = 0`, `is_minor_at_time = true`). Synthetic accounts (`users.is_synthetic = true`) produce no SH score, no HC match and no dashboard rows; caps still apply.

### 2.12 Performance (TS-PERF, k6)

| ID | Scenario | Load | Pass criteria (source) |
|---|---|---|---|
| P1 | Placement drive | 2,000 test-takers start within 5 min; autosave 20,000 writes/min sustained 30 min; shared deadline auto-submit | Attempt start p95 ≤ 1.5 s; autosave p95 ≤ 250 ms; auto-submit ≤ 10 s after deadline + grace; error rate < 0.1 % (NFR-PERF-02, NFR-SCL-02) |
| P2 | Steady mixed traffic | 3,000 concurrent sessions (NFR-SCL-01), ~1,000 req/s through BFF (ARCH §19.1, 5,000 concurrent users) | Read p95 ≤ 300 ms, p99 ≤ 800 ms; write p95 ≤ 500 ms (NFR-PERF-01) |
| P3 | College login storm | 50 colleges × 40 students behind one NAT IP each, 10 min | No IP lockout for registered ranges; Argon2 semaphore holds; login p95 ≤ 1 s; risk login evaluation p95 < 30 ms (RE §5.2) |
| P4 | Analytics ingest | 500 events/s peak ×2 for 1 h | 0 data loss; builder lag < 2 min (AN §7.4) |
| P5 | Judge burst | ~8 submissions/s for 1 h (60k/day profile, NFR-SCL-03) against stub + quota-limited real staging | Run p95 ≤ 6 s, submit p95 ≤ 15 s, queued state shown beyond 15 s (NFR-PERF-05) |
| P6 | Webhook flood | 100 rps for 10 min while P2 runs | Ack < 1 s; user traffic unaffected (separate `api-webhooks` service) |
| P7 | Entitlement check | Micro-benchmark under P2 | p95 ≤ 20 ms (NFR-PERF-06) |
| P8 | Playback tokens | ~170 req/s OTP issuance + heartbeats | p95 ≤ 300 ms; stream-cap correctness under concurrency (no double token for 1-stream cap) |
| P9 | Soak | P2 at 60 % for 8 h | No memory growth > 10 %, no connection leak, RDS connections < budget |
| P10 | Scale-out | Step to 10× P2 on scaled infrastructure | Horizontal scaling without code change (NFR-SCL-01) |
| P11 | Degradation | Judge, VdoCipher or Razorpay stub down during P2 | Login, MCQ tests, reading unaffected; status banner ≤ 5 min (NFR-AVL-03) |
| P12 | Web vitals | Lighthouse CI + xk6-browser, mid-range Android profile, 4G (≈9 Mbps, 170 ms RTT) | LCP ≤ 2.5 s, INP ≤ 200 ms, CLS ≤ 0.1 at p75; test-runner JS ≤ 200 KB gz (NFR-PERF-03) |

Concurrency correctness checks run inside P1/P8: no attempt bound to two sessions, no duplicate submission rows, no second concurrent stream.

### 2.13 Accessibility (TS-A11Y)

- axe-core runs on every screen in the PRD §6 inventory reached by the E2E suite, in light and dark themes, at 360 px and desktop; gate: 0 serious/critical (NFR-ACC-01).
- Scripted keyboard checks: test runner and code editor fully operable; no keyboard trap (editor has a documented escape key); focus not obscured (2.4.11); target size ≥ 24×24 px (2.5.8); no drag-only interaction (2.5.7); consistent help (3.2.6); redundant entry (3.3.7); accessible authentication — paste allowed in password/OTP fields, passkeys supported (3.3.8); no CAPTCHA anywhere in the unblock flow (AMB-19 resolved: rate limits only); the AB-02 source challenge is non-puzzle.
- Timer announced via ARIA live region only at 10/5/1 min (AC-ACC-01).
- Contrast ≥ 4.5:1 text / 3:1 UI via design-token unit tests.
- Manual per release: NVDA + Chrome, TalkBack + Chrome Android, VoiceOver iOS on journeys J1, J4 (blocked student → unblock), a 20-question test and a coding problem. Captions on all video lessons (content QA checklist).

### 2.14 Backup, restore and recovery drills (TS-DR)

| Drill | Frequency | Pass criteria |
|---|---|---|
| RDS point-in-time restore to an isolated account | Monthly | Canary rows written every minute show RPO ≤ 5 min; full restore ≤ 4 h (NFR-AVL-02) |
| Erasure re-application after restore | Monthly (same drill) | `erasure_ledger` applied **before** the restored DB serves traffic; erased fixture users absent (brief §1, PRIV §7) |
| Audit chain continuity | Monthly | Hash chain verifies across the restore point; S3 Object Lock anchors match |
| Multi-AZ failover (RDS, both Redis clusters) | Quarterly in staging | RTO ≤ 30 min; attempt deadlines still enforced by the DB safety sweeper when Redis `queue` loses entries (ARCH §8.4); Redis `cache` outage → logins and session checks continue via Postgres (circuit breaker, p95 +5 ms), revoked sessions stay revoked via `sessions_valid_after` (RE §1.6; AMB-09 resolved) |
| Celery DLQ replay and webhook reconciliation after 2 h provider outage | Quarterly | No lost or duplicated entitlements |
| Secrets rotation (webhook secret, Judge0 key, HMAC keys incl. `fp_epoch_rotate`) | Quarterly | No downtime; old secret rejected after overlap. `k_device`/`k_login` are versioned, not overlapped: see §2.16 HK-* (old versions stay usable for lookup) |
| Incident tabletop (CERT-In 6 h, DPB 72 h) | Pre-launch, then 6-monthly | Report drafted within the clocks (TM §6) |

### 2.15 Privacy tests (TS-PRIV)

| Area | Test | Expected |
|---|---|---|
| Unverified age | Create user with no DOB | `is_minor = true`, `privacy_tier = minor`; CHECK `is_minor OR age_verified_at IS NOT NULL` holds |
| Minors and sharing signals | Run every TS-RISK fixture as a minor (17-year-old with guardian consent; unverified age) | 0 `security_signals` with `family='sharing'` (DB CHECK `ck_sig_minor` + app test); **0 `risk_evaluations` of any family** (`ck_re_no_minor`); no HC-01/HC-02 match; 0 `security_activity_feed_daily` rows; no `multi_device_overlap_s`; no fingerprint; only `cap.*`, AB-/IN- throttles (no points) and deterministic takeover outcomes. A minor's TO-04 writes one `security_signals` row (`family = takeover`, `base_points = 0`, `is_minor_at_time = true`) plus the `auth_sessions` end record (CPR-TST-09) |
| Synthetic accounts | Synthetic-monitoring user and org (`is_synthetic = true`) active alongside real fixtures | Excluded from analytics aggregates, risk scoring and HC rules, invoices/GST sequences and k-anonymity counts; only the synthetic-monitoring provisioning job can set the flag (any other writer → rejected) (IPR-QA-03) |
| Minors in UI | Minor hits caps repeatedly | Only cap dialogs and T-protect copy, never L1–L3 sharing copy (UNB §1) |
| Turning 18 | Birthday job flips tier; adult consent given 3 days later | Scoring and feed start only from the adult consent date; no back-fill of prior data |
| Consent withdrawal | Adult withdraws `security_monitoring` | Feed rows deleted within 24 h; no new rows; account runs deterministic-only (PO-03) |
| Consent defaults | New adult | `analytics_personalisation` off (PO-04); `analytics_product` off |
| P-purpose drop | Minor client sends product events | Server rejects `purpose_not_permitted` |
| Retention jobs | Time-travel fixtures aged past each limit, then run `purge_raw_analytics`, `purge_security_signals`, `purge_auth_logs`, `expire_devices`, `purge_closed_cases`, `account_erasure`, `pseudonymise_aggregates`, `consent_proof_expiry` | Rows/partitions deleted per brief values (heartbeats 35 d, events 90 d, intervals 13 months, signals/evaluations 180 d unless on an open or held case, auth logs 395 days (§2.16 RET-*), attachments 90 d after closure); held rows skipped; run summary written to `audit_log` |
| Erasure | DSAR erasure after cooling-off | Every module's `privacy_provider.delete()` called (contract test enumerates modules, NFR-MNT-01); legal-hold categories tombstoned; ledger row written |
| Export / pseudonymisation | BI export and coordinator reports | `subject_key` only; k-floors: cohort 10, item 10, cross-org display 50, percentile reference 20 |
| Monitoring access | Reviewer opens per-user timeline without reason code | Refused; with reason: audited; IP reveal audited; >30 timelines/day alert |
| Logs | Scan all test-run logs | No passwords, OTPs, tokens, raw UA in session table, Aadhaar/PAN-like strings |
| Residency | IaC check | All data stores and log sinks in `ap-south-1` |

### 2.16 Engine controls and new security mechanisms (TS-RISK, TS-SEC, TS-PRIV)

Sources: RE v0.3 §1.5, §4.2.1, §4.5, §5.6–§5.8, §10; UNB §5.1, §6.2; PRIV §7. All run with the injected clock. Every case runs in the integration suite; the ones marked E2E also run in Playwright.

**Kill switch (RE §3.1, §5.7).**

| ID | Case | Expected |
|---|---|---|
| KS-01 | A `security_reviewer` holding `security.engine.kill_switch` calls `POST /security/engine/kill-switch` (`target = mode`, reason, step-up P5) while `risk.mode = enforce` | `risk.mode = shadow` within 60 s (policy cache TTL); later evaluations are written with `mode = shadow`; no new L1–L3 action; restrictions already in force stay in force; `audit_log` row with reason |
| KS-02 | Same call | An `approval_requests` row `action_type = risk.kill_switch.ratify`, `status = pending` is created automatically. Ratification by the same person → refused (`sod_violation`); by a different holder of `approval.decide` → `approved` |
| KS-03 | No ratification within 24 h | At 24 h the security lead and all super_admins are paged; `risk.mode` is **still `shadow`** at 24 h + 1 min and at 72 h (no automatic revert) |
| KS-04 | `target = hc`; `target = rule:HC-01` | `risk.hc.auto_restrict_enabled = false`, or HC-01 status `shadow` only (HC-02 untouched); HC conditions still evaluated and written `mode = shadow`; ratification request as KS-02 |
| KS-05 | Attempt to move back to `enforce` / HC on through the kill-switch endpoint, or with one approver | Refused; only `policy.edit` / `security.rule.publish` with Dual (`approval_requests`, distinct approver) succeeds |
| KS-06 | Caller without the permission (support_agent, finance_admin, coordinator); holder without fresh step-up | 403; `401 step_up_required` |
| KS-07 | Kill switch engaged, then an adult logs in with a breached password (HC-T1) | T-protect still applies: takeover rules, deterministic caps and AB-*/IN-* controls are not covered by the kill switch or `risk.mode` (RE §3.2, §5.7; AMB-23 resolved). Same result with `risk.mode = shadow` and `off` |

**HC circuit breaker (RE §5.7; defaults `max_fp_rate` 0.05, `min_decisions` 20, `max_daily_restrictions` 50).**

| ID | Case | Expected |
|---|---|---|
| CB-01 | Last 20 decided HC-01-applied restrictions contain 3 `lift_false_positive` (RE row 9f) | 15 % > 5 % → HC-01 moves to `shadow`: new `risk_rule_versions` status change by the system actor with `status_change_reason = circuit_breaker`; security-lead alert; ENG banner; H8 shows the breaker open |
| CB-02 | Boundaries: 1 of 20 (5 %, not "exceeds"); 2 of 20 (10 %) | 1/20 → stays `active`; 2/20 → trips |
| CB-03 | 51 HC-01 L3s in a rolling 24 h (`max_daily_restrictions` = 50) | The 51st is **not** applied: the limit is checked before applying (atomic per-rule counter, also under 2 concurrent workers); the breaker trips; the 51st evaluation is written `mode = shadow` with `gates.breaker = tripped_daily_limit` and continues on the scored path; exactly 50 HC-01 L3s exist (RE §5.7 (b); AMB-24 resolved) |
| CB-04 | HC-01 trips while HC-02 is healthy | HC-02 stays `active` (breaker is per rule) |
| CB-05 | After a trip | The rule never re-activates on its own (assert after 30 days of clean data); re-activation only by Dual approval |
| CB-06 | Fewer than `min_decisions` decided: 1 FP of 3; 2 FP of 3; 2 decided + 5 undecided with 1 FP | Absolute threshold `max_fp_rate × min_decisions` = 1: 1 FP of 3 → stays `active`; 2 FP of 3 → trips; undecided restrictions are not counted (RE §5.7 (a); AMB-24 resolved) |

**Bulk false-positive lift (RE §5.8; UNB §6.2).**

| ID | Case | Expected |
|---|---|---|
| BL-01 | Dry run with a selector (`ruleset_version`, `rule_key` incl. HC-01, `organization_id`, `applied_between`, `network_cidr`/`asn`) | Matching count, first 50 cases masked, list of exclusions; no state change |
| BL-02 | Selector matching 5,001 restrictions | `422` (max 5,000 per request) |
| BL-03 | Selector also matches an L4, a reviewer-applied L3, a takeover lock, an `is_high_risk` case and a case with a pending unblock decision | All five excluded automatically and listed as exclusions |
| BL-04 | Execute | Needs step-up P5 and Dual: `approval_requests` `action_type = security.restriction.bulk_lift` with selector, snapshot of matched restriction ids and `payload_hash`. Requester approving → `sod_violation`; no approval in 72 h → `expired`, nothing lifted |
| BL-05 | Approved (RE row R-8: 300 students in one org) | Per restriction, in its own transaction: `case_decisions` (`lift_false_positive`, `decided_by` = requester, `approved_by` = approver, `approval_request_id`); restriction ended `case_decision` **without** re-verification; contributing signals suppressed; FP extension credit; open unblock request → `moot`; student notified (UNB §1.6b "We made a mistake…"); H8 counters incremented; operator reminded to shadow the rule. One failing restriction does not roll back the others |
| BL-06 | A restriction matching the selector is applied after the snapshot; the stored payload is altered | Late restriction is not lifted (snapshot only); hash mismatch → execution refused |
| BL-07 | Caller without `security.restriction.bulk_lift` | 403 |

**HMAC key versioning and rotation (RE §1.5; PRIV §7 `hmac_key_retire`).**

| ID | Case | Expected |
|---|---|---|
| HK-01 | `k_device` rotated v1 → v2; a browser presents a device cookie hashed under v1 | Lookup misses v2, hits v1; the row is re-hashed in place (`device_key_hash`, `key_version = 2`) in the same transaction; the device is **not** treated as new (no OTP); the next request hits v2 first |
| HK-02 | Three rotations (v1 → v4) and a cookie from v1 | At most 2 extra versions are tried; v1 outside the lookup window → treated as a new device. A version destroyed 400 days after retirement is never tried |
| HK-03 | `k_login` rotated; failures for one email under v1 and v2 | Search by identifier computes one hash per live version and returns both rows; `login_attempts` rows are never re-hashed |
| HK-04 | Planned rotation by one approver; emergency rotation after compromise | Planned: refused without Dual (🔒 `security.keys.*.current_version`). Emergency: single approver + `approval_requests` 24 h ratification (as KS-02/03); old-version lookups stay enabled and every old-version hit raises an alert for 30 days |
| HK-05 | Monthly `hmac_key_retire` job (queue `maintenance`); IaC check of secret access | `k_device` versions destroyed 400 days after retirement, `k_login` 395 days after; destruction audited; `td/k_device/v{n}` and `td/k_login/v{n}` readable only by the `api` and `worker-*` task roles |

**`approval_requests` lifecycle (UNB §5.1; applies to `security.case.decision`, `risk.kill_switch.ratify`, `security.restriction.bulk_lift`, `report.export.approve`, policy changes, goodwill refunds).**

| ID | Case | Expected |
|---|---|---|
| AR-01 | R1 submits a decision that needs a second approver | `202` with `approval_request_id`; row `status = pending`, `expires_at = created_at + 72 h`, `payload_hash`; **no `case_decisions` row**; case and unblock request `escalated`. A second pending `security.case.decision` for the same case → 409 (partial unique index) |
| AR-02 | R2 approves | `approved` → `executed`; in the same transaction `case_decisions` is inserted (`decided_by` = R1, `approved_by` = R2, `approved_at`, `approval_request_id`); restriction → `lift_pending` |
| AR-03 | R1 approves own request; the reviewer who applied the restriction approves; an approver sharing a registered device with the student approves | Each refused (`sod_violation` / conflict) |
| AR-04 | R2 sends back with a note | `rejected` with `decision_note`; unblock request returns to `under_review`; no decision row |
| AR-05 | Nobody acts for 72 h | `expired`; case stays `escalated`; SLA-breach alert; R1 must re-propose |
| AR-06 | R1 withdraws; someone else tries to withdraw | `cancelled`; non-requester refused |
| AR-07 | Payload edited after creation | Execution refused (hash re-verified); a changed decision must be a new proposal |
| AR-08 | `case_decisions` CHECKs | Every stored row satisfies `approved_by <> decided_by` and `requires_second_approval ⇒ approved_by IS NOT NULL` |

**Separation classes, owner verification and SH-13 (RE §4.2.1, §4.2).**

| ID | Case | Expected |
|---|---|---|
| SEP-01 | S0: Chrome + Edge, same cluster, OS family and device_class; variant with matching `fp_hash` | SH-01 × 0.1; × 0 with fingerprint (R-1) |
| SEP-02 | S1: both on the same fixed-line /24 (or /56); both on mobile with the same ASN and `geo_region`; one leg on a verified trusted network | × 0.1 |
| SEP-03 | S2: laptop broadband + phone on Jio; both devices owner-verified vs phone email-OTP only; then the phone completes SMS OTP | 0.1 vs 0.3; after verification earlier S2 overlaps re-weighted to 0.1 at scoring time (worked example A: ≈ 45 → ≈ 15, L2 clears) |
| SEP-04 | S3: two broadband legs, different ASNs or non-overlapping /16s, neither trusted; both owner-verified | × 1.0, never re-weighted; a policy change of `risk.separation.multiplier.S3` ≠ 1.0 → rejected (🔒) |
| SEP-05 | Wi-Fi → mobile mid-day: device B overlaps device A on a distant broadband cluster in the morning (S3), switches to mobile data in the afternoon (S2); reverse order on another day | `session_network_observations` row on each cluster change (≤ 1 per 60 s); each bucket mapped to the covering observation; **one** SH-01 occurrence per pair per day with the most separated class (S3) in both orders |
| SEP-06 | Owner verification by SMS OTP / passkey / TOTP / email OTP; age 29 vs 31 days | First three owner-verified for 30 days; email OTP → `trusted`, not owner-verified; at 31 days not owner-verified (`owner_verified_at`, `verification_method` stored) |
| SH13-01 | Device B completes a new-device or L2 verification on a broadband cluster while device A had an engaged bucket or authenticated request within ±15 min on a different broadband cluster | SH-13 (10 points, cap 20/7 d), one occurrence per verified device; B keeps the unverified S2 multiplier (0.3) for 30 days |
| SH13-02 | Negatives: A on mobile; A's last activity 16 min before; same cluster; minor | No SH-13 |
| SH13-03 | R-9: owner verifies an office laptop at work while a family member streams at home | SH-13 (+ S3 overlap if they overlap) ≈ 25–45 → at most L1/L2; no L3 unless the §5.3 gates are later met |

**Accepted under-detection (RE §4.2.1, row 5c; TM §7 R1; AMB-18).**

| ID | Case | Expected |
|---|---|---|
| UD-01 | Worked example C: owner relays the SMS OTP; the sharer uses only Jio mobile data; overlaps on 4 days in 10 | All overlaps S2 × 0.1 (relayed device owner-verified); no SH-13 (mobile leg); score ≈ 15–25 → **L0/L1 is the expected, accepted outcome** (asserted as a pass, not xfail); no L2, no L3, no HC-01 match; only the deterministic caps (2 sessions, 1 stream) act. A rule change that alters this must update the golden in the same PR with Security Specialist review (G-17) |

**Abuse and integrity registry boundaries (RE §4.5).** For each rule, a fixture just below and at the threshold; below → no signal; at → `security_signals` with `rule_key` = the ID and `family` `abuse`/`integrity`, the stated action, and alert routing. None restricts an account.

| ID | Rule | Below / at threshold | Action asserted |
|---|---|---|---|
| ABR-01 | AB-01 | 9 / 10 logins in 1 h; 20 / 21 in 24 h | Adults TO-11 +20 → T-step-up; minors no points; > 20/24 h → `429 rate_limited` 1 h |
| ABR-02 | AB-02 | OTP sends to 4 / 5 numbers from one /24 in 1 h | Non-puzzle challenge, then sends refused 24 h; ops alert at > 2× baseline spend |
| ABR-03 | AB-03 | 9 / 10 failed OTP verifications in 1 h | OTP disabled 1 h; 3 occurrences/24 h → passkey/TOTP-only step-up; adults +20 |
| ABR-04 | AB-04 / AB-05 | 49 / 50 failures across 20 accounts; 99 / 100 accounts sprayed (× 10 for campus and CGNAT) | Source flagged; failures not counted toward account lockout; feeds TO-05 |
| ABR-05 | AB-06 | 999 / 1,000 requests in 10 min | Session `429` for 15 min; 3 days in 14 → case `opened_reason = manual`, priority low; no restriction |
| ABR-06 | AB-07 | 19 / 20 unknown tokens per /24 in 10 min | /24 throttled 15 min on authenticated routes; security lead at ≥ 100 |
| ABR-07 | AB-08 | 29 / 30 `403 account_restricted` in 10 min | Signal only (info); restriction unchanged |
| ABR-08 | AB-09 | 19 / 20 404s per minute; 4 / 5 cross-tenant hits per hour | Security-lead alert; no automatic action |
| ABR-09 | AB-10 / AB-11 | Device of an L3 account logs into another account within 7 days; lab device of org X used by a non-member 2 / 3 times in 7 days | AB-10: evidence on the restricted case (case on the other account only if it is ≥ L2); AB-11: session allowed, coordinator review request at 3 |
| ABR-10 | AB-12 | One invalid signature | `400 webhook_signature_invalid`; ops alert at > 10/min |
| ABR-11 | IN-01 / IN-02 / IN-03 | Day 16 h / > 16 h credited; 49 / 50 forgery rejections per session per hour; 19 / 20 submits per problem per hour | IN-01 no score (day excluded by analytics); IN-02 ingest for that session ignored 1 h; IN-03 submissions throttled 1 h |

**Log retention (PRIV §7; CPR-DEP-02).**

| ID | Case | Expected |
|---|---|---|
| RET-01 | `login_attempts` monthly partition whose newest row is 394 days old; another at 396 days | `purge_auth_logs` keeps the first, drops the second (whole partition) |
| RET-02 | Same for `session_network_observations`; ended `auth_sessions` rows at 394 / 396 days | Same rule; ended sessions deleted row-wise at > 395 days; active sessions never deleted |

**Section H reports (RE §10; ids H1–H12 + ENG, identical in the API spec and PRD).**

| ID | Case | Expected |
|---|---|---|
| RPT-01 | Each of H1–H12 and ENG opened by every role | Only `security_reviewer` (platform scope) sees signal and per-user views; `super_admin` sees aggregate views only (H7, H8, H10, aggregate H11, ENG; per-user evidence only in break-glass); `support_agent` sees restriction and case status only; `college_coordinator` sees only the org aggregate tile; all others 403 |
| RPT-02 | Per-user views (H2, H3, H12, per-user H11) without / with a reason code (`case_review`, `appeal`, `takeover_investigation`, `qa_sample`) | Refused / allowed with an `audit_log` row |
| RPT-03 | CSV export with per-user rows of a security/monitoring report (H1–H9, H12, per-user device/login history) | Step-up P5; job `awaiting_approval` with `action_type = security.export.per_user`; approved only by a **second `security_reviewer`** holding `report.export.approve` (≠ requester → else `sod_violation`); watermark with requester and time; audited. Aggregate-only exports need step-up only |
| RPT-05 | Approver routing (API §1.7 I-26; role matrix v0.4 §5) | `super_admin` approving a `security.export.per_user` request → 403 `permission_denied`; `security_reviewer` approving an `export.bulk_pii` request (H10/H11 aggregates, finance GST export, coordinator report > 10,000 rows) → 403; `super_admin` approving `export.bulk_pii` (≠ requester) → approved; requester approving own request in either type → `sod_violation` |
| RPT-04 | Content checks | H1 shows the HC rule column; H3 shows separation class per overlap and only adults with consent; H5 shows source engine / HC rule / reviewer and `deferred_until`; H8 is per ruleset, per rule and per HC rule with breaker state and bulk lifts; H10 aggregate only; H11 applies k-floors to org views; ENG shows `risk.mode`, kill-switch state and HC shadow vs enforced; minors never appear in sharing views |

---

## 3. Environments and test doubles

| Environment | Purpose | Data | External providers |
|---|---|---|---|
| Local (`infra/docker`) | Developer runs | Seed `dev` profile | Stubs (SMS, VdoCipher, Judge0, Razorpay replay), Mailpit, MinIO |
| CI ephemeral | TS-UNIT … TS-TIME | Per-test fixtures | Stubs only; no internet egress from test containers |
| Preview (per PR) | TS-E2E smoke, TS-A11Y | Seed `demo` profile | Stubs |
| Staging | Nightly E2E, DAST, live provider test modes | Seed `demo` profile, synthetic only | Razorpay/Cashfree **test mode**, VdoCipher test account, Judge0 test plan, SMS provider sandbox restricted to an allowlist of team test numbers |
| Perf | TS-PERF | Generated synthetic volume (≈ year-1 size) | Stubs with recorded latency profiles + capped real judge |
| Judge staging account | TS-JUDGE Phase 2 | None | — |
| Restore account | TS-DR | Restored prod snapshot, access restricted to DR operators | None |

Test-only hooks (clock control, fixture loaders) are compiled out of the production image; G-21 fails if any test hook route or env flag is reachable in the production profile.

---

## 4. Phase-8 account-sharing control scenarios (owner list)

Severity mapping (RE §11): L0 = none, L1 = info, L2 = low, L3 = medium, L4 recommended or T-protect = high. Scores use the v1 defaults (`sharing-1.0.0`, half-life 7 days, SH-01 separation multipliers S0 0/0.1, S1 0.1, S2 0.1 both owner-verified / 0.3 otherwise, S3 1.0) and are approximate after decay. Every expected value below was re-verified against RE v0.3 (§4.2.1, §4.3, §4.5, §5.1, §5.6, §11).

### 4.1 Mapping to the risk-engine document

| Owner # | Owner scenario (verbatim) | RE §11 row(s) | Other design source |
|---|---|---|---|
| 1 | One student logs in on a laptop and continues using the same account on a phone. | 1 | RE §2 cases 3–4, §4.2.1, §5.1 example A |
| 2 | One student has several browser tabs open on the same laptop. | 2 | RE §2 case 1; AN §3.5 |
| 3 | Two students access the site from the same college Wi-Fi. | 3 | RE §2 case 7, §5.5 |
| 4 | One student changes from Wi-Fi to mobile data. | 4 | RE §1.2 network observations, §4.3 TO-08; brief §1 "never bound to IP" |
| 5 | One account is active concurrently from two unrelated devices. | 5a, 5b, 5c | RE §4.2.1, §5.1 examples B and C |
| 6 | Several different accounts repeatedly use the same browser/device. | 6a, 6b, 6c | RE §2 case 5; §4.5 AB-10, AB-11; UNB §8 |
| 7 | One account is accessed from geographically inconsistent locations within an implausibly short time. | 7 | RE §4.2 SH-10, §4.3 TO-09 |
| 8 | A legitimate student uses a VPN. | 8 | RE §4.2 SH-09, §4.2.1 S2, §4.3 TO-07 |
| 9 | A suspicious account is automatically restricted by a configured high-confidence rule. | 9a–9f | RE §5.3, §5.6, §5.7, §6.1–6.2, §7.4 |
| 10 | A student submits an unblock request with a legitimate explanation. | 10 | UNB §3, §4 |
| 11 | An administrator approves the request and revokes suspicious sessions. | 11 | UNB §5, §5.1, §6 |
| 12 | An administrator rejects a request and provides a reason. | 12 | UNB §4.2, §4.3 |
| 13 | A blocked user tries to access private content through a direct API request. | 13 | RE §7.2, §7.5, AB-08; brief §5 |
| 14 | The same payment webhook is delivered repeatedly. | 14 | TM §2.4; ADR-0006 v0.3; AC-COM-01; AB-12 |
| 15 | An inactive tab remains open for several hours. | 15 | RE §1.4; AN §3.13 Example 2 |
| 16 | A browser crashes during a timed assessment. | 16 | RE §1.4, §6.3, §7.4; AN Examples 3–4; AC-ASM-01 |
| 17 | A student opens multiple tabs and attempts to manipulate time tracking. | 17 | AN §5.2, §5.5; RE §4.5 IN-01, IN-02 |
| 18 | An administrator accesses another institution's records without permission. | 18 | RPM §4 TI-01..11; RE §4.5 AB-09 |
| 19 | A user attempts to change a session identifier or reuse a revoked session. | 19 | RE §1.6, §4.3 TO-04/TO-08, §5.6 HC-T3, §6.2, AB-07 |
| 20 | A student disputes a false-positive account-sharing decision. | 20 | UNB §4–§6; RE §5.7, §10 H8 |

RE §11 regression rows R-1..R-9 are retained in §4.22 under the same ids (former RX-01..RX-05 = R-1..R-5; former RX-06 credential stuffing is now RE row 9d inside SCN-09; former RX-07 = R-6; R-7..R-9 are new).

Common fixtures used below: `org-A` (college, registered trusted network `198.51.100.0/24`, 2 registered lab PCs), `org-B` (college, nothing registered), adult students with `security_monitoring` consent unless stated, minors as stated, two `security_reviewer`s (R1, R2), one `support_agent`, one `super_admin`.

### 4.2 SCN-01 — Laptop, then phone

| Field | Specification |
|---|---|
| Preconditions / fixtures | Adult student "Aarav" (org none, D2C), laptop device D1 trusted and owner-verified by SMS OTP 10 days ago on home broadband, no phone device yet, verified phone and email; policy defaults (`risk.mode` stated per run) |
| Steps | 1. Log in on D1 (Chrome), watch a lesson for 20 min, close the lid without logging out. 2. 40 min later, log in on a phone (D2, new `__Host-td_device`) on Jio mobile data. 3. Complete the new-device OTP by SMS. 4. Continue the same lesson and a practice set on D2 for 30 min. 5. Variant 1-B: daily ≥ 15 min engaged overlap of D1 (broadband) and D2 (Jio) for 30 days (owner's "continues using" with overlap). 6. Variant 1-C: as 1-B but D2's new-device OTP went by **email** |
| Expected result | Step 2 → `device_otp_required`; after SMS OTP, D2 becomes `trusted` (2 of 3) and owner-verified (`verification_method = sms_otp`), session issued; D1 session remains active (2 sessions = cap, no prompt). Learning progress continues on D2 (keyed by `lesson_key`). Variant 1-B: allowed (2 sessions, 1 stream; if D2 plays video, `409 playback_conflict` → "Play here instead?"); overlap class S2 × 0.1. Variant 1-C: S2 × 0.3 until D2 is owner-verified |
| Security rule tested | New-device verification (brief §1, RE §6.3); session cap 2; device cap 3; no SH-01 without engaged overlap (RE §2 "engaged" definition); owner verification (RE §4.2.1: SMS/passkey/TOTP yes, email no); separation class S2 multiplier and re-weighting |
| Events recorded | `login_attempts` (`device_otp_required`, then `success`); `devices` + `user_devices` (D2 `pending_otp` → `trusted`, `owner_verified_at`); `auth_sessions` row for D2; `session_network_observations`; `audit_log` login; analytics heartbeats (union, not summed). Variants: SH-01 signal daily with `separation_class = S2` |
| Risk score / severity | 0 / none. Variant 1-B: 1.5/day; ≈ 8 after 7 days; steady ≈ 15 → L0 (RE §5.1 example A; RE row 1). Variant 1-C: 4.5/day; ≈ 24 after 7 days (L0), L1 from about day 8, steady ≈ 45 → L2 "Confirm it's you" by SMS OTP; after D2 is owner-verified the S2 overlaps re-weight to 0.1 → ≈ 15 and L2 clears (< 35). Owner verification stays fresh through SMS-OTP/passkey/TOTP sign-ins or the pre-expiry "Keep this device verified" prompt (RE §4.2.1); day-31+ with verification deliberately lapsed: overlaps score × 0.3 only until the next owner verification, which re-weights them to 0.1 (AMB-22 resolved) |
| User-facing response | One-time OTP prompt on D2. Devices page lists both devices |
| Admin notification | None |
| Auto-restriction appropriate? | **No** |
| Recovery / appeal | Variant 1-C: pass the L2 SMS OTP |
| Automation | Integration (TS-RISK fixture) + E2E (Playwright: two browser contexts with distinct device cookies, mobile emulation for D2) |
| Ambiguity | AMB-01 resolved (RE §4.2.1); AMB-22 resolved (RE §4.2.1 refresh and pre-expiry prompt; §5.1 example A) |

### 4.3 SCN-02 — Several tabs on the same laptop

| Field | Specification |
|---|---|
| Preconditions / fixtures | Adult student on trusted D1, one session; a mock test assigned |
| Steps | 1. Open 3 tabs: video lesson (tab A), practice (tab B), dashboard (tab C). 2. Play video in A, then start video in tab C on another lesson. 3. Start a mock attempt in tab B, then open the same attempt in tab C. 4. Boundary runs with 5 and 7 tabs open. |
| Expected result | One session, one device, no security signal. Step 2: stream moves to tab C silently within the same session; tab A shows "Playing in another tab". Step 3: both tabs work on the attempt (bound to the session); BroadcastChannel shows "already open in another tab"; answers are idempotent by `client_seq`. Analytics: M2 = union of tabs, never a sum |
| Security rule tested | RE §2 case 1; stream cap applies per session (takeover within session); attempt binding is per session (brief §1); AN §3.5 union |
| Events recorded | Heartbeats per `tab_id`/page instance; `playback_sessions` (previous ended `taken_over`); `attempt_events` `answer_saved`; no `security_signals`, no `cap.*` |
| Risk score / severity | 0 / none |
| User-facing response | "Playing in another tab" overlay; "This test is already open in another tab" banner |
| Admin notification | None |
| Auto-restriction appropriate? | **No** |
| Recovery / appeal | n/a |
| Automation | Unit (attribution), integration (ingest union), E2E (Playwright multi-page in one context) |
| Ambiguity | AMB-11 resolved: `analytics-event-schema.md` §5.2 is the single source. Boundary runs: 5 tabs → nothing flagged; 7 tabs → "more than 6 active page instances" flag (adults with consent), credit unaffected (union), no sharing signal |

### 4.4 SCN-03 — Two students on the same college Wi-Fi

| Field | Specification |
|---|---|
| Preconditions / fixtures | Students S1 and S2 of org-A, each with their own trusted device; both egress from `198.51.100.10` (registered trusted range). Scale variant: 40 students of org-A within 10 min; unregistered variant: 40 students of org-B from `203.0.113.10` |
| Steps | 1. S1 and S2 log in and learn concurrently for 1 h. 2. Run the 40-student storm, including 15 mistyped passwords. 3. Repeat for org-B (unregistered range) |
| Expected result | All logins succeed; no IP lockout (per-IP failure limit ×10 for registered campus ranges = 300/10 min); no sharing signals on any account because IP is never an identity; network multipliers 0 for the trusted range. Org-B: logins still succeed (15 failures < 30/10 min); no signals; coordinator of org-B is prompted to register the range |
| Security rule tested | RE §2 case 7; `login.ip_failed_limit_per_10min` and campus relaxation; `risk.trusted_network_multiplier` = 0; SH-02/SH-09/SH-10 × 0 for trusted ranges (RE §5.5); "never bind sessions to IP" |
| Events recorded | `login_attempts` only (with `pre_auth_blocked = false`); `auth_sessions` per student |
| Risk score / severity | 0 / none |
| User-facing response | Normal |
| Admin notification | None; H4 lists org-B's cluster as a registration candidate; org-B coordinator sees a "register your campus network" prompt |
| Auto-restriction appropriate? | **No** |
| Recovery / appeal | n/a |
| Automation | Integration (rate-limit + risk fixture), performance (P3) |

### 4.5 SCN-04 — Wi-Fi to mobile data

| Field | Specification |
|---|---|
| Preconditions / fixtures | Adult student on phone D2 (trusted), home broadband (ACT, Telangana); then Jio mobile (CGNAT ASN, IP geolocating to Maharashtra); mid-video and mid-attempt variants |
| Steps | 1. Watch a video on Wi-Fi. 2. Switch to mobile data mid-stream; IP changes 3 times in 10 min. 3. Variant: same during a timed attempt with 30 s of no connectivity during the switch. 4. Variant: the same session cookies (session + device) then arrive with a different `ua_family` (Chrome → Firefox); and with only a Chrome major-version change |
| Expected result | Same session continues, no re-login, no OTP; playback heartbeats continue; attempt autosaves queue in IndexedDB and sync in order on reconnect (AC-ASM-02); no sharing or takeover signal; SH-10 not computed because mobile ASNs are excluded and it is the same session. Step 4: different UA family → TO-08 (that session only revoked, `device_mismatch`, adults +60 → T-step-up, owner notice UNB §1.6a); major-version change → nothing (RE §4.3) |
| Security rule tested | Brief §1 "sessions are never bound to IP"; SH-10 mobile-ASN exclusion; network cap; TO-08 client drift |
| Events recorded | `auth_sessions.last_seen_at` / `ip_last` updated; `session_network_observations` row per cluster change (≤ 1 per 60 s); `attempt_events` `disconnect` / `reconnect` (events, not penalties); step 4: TO-08 signal, `auth_sessions` ended `device_mismatch` |
| Risk score / severity | 0 / none |
| User-facing response | Attempt: "Offline — stored on this device" then synced |
| Admin notification | None |
| Auto-restriction appropriate? | **No** |
| Recovery / appeal | n/a |
| Automation | Integration (session + risk), E2E (Playwright `context.setOffline`, proxy-switched egress IP) |
| Ambiguity | AMB-04 resolved: the UA-change case is TO-08 (RE §4.3); a network-only change raises nothing |

### 4.6 SCN-05 — Concurrent use from two unrelated devices

| Field | Specification |
|---|---|
| Preconditions / fixtures | Adult account, `risk.mode = enforce`, `risk.hc.auto_restrict_enabled` false unless stated. Owner laptop D1 in Hyderabad (Airtel broadband, TG); sharer laptop D3 in Pune (ACT Fibernet broadband, MH), made trusted **and owner-verified** by an SMS OTP the owner relayed on day −10 while D1 was active (RE §5.1 example B); no trusted networks; 6 device tokens in 30 days. Variant 5c: D3 is a phone on Jio mobile data only (example C) |
| Steps | 5a (RE row 5a): S3 overlaps (≥ 3 engaged buckets) on days −9, −6, −3 and 0; stream ping-pong 3× within 60 min on day −1; L2 reached on day −3, its re-verification passed by relay, new overlap on day 0. 5a-2: same with overlaps only on days −3 and 0. 5b (RE row 5b): D3 requests playback while D1 streams; confirm takeover; a third device logs in while 2 sessions are active. 5c (RE row 5c): example B timeline with D3 on mobile data only. 5d: 5a with `risk.hc.auto_restrict_enabled = true` and HC-01 `active` |
| Expected result | Deterministic first: stream cap → `409 playback_conflict`, takeover ends the other stream within 30 s (AC-SES-03); third login → session chooser (AC-SES-02). A single isolated S3 overlap day with no other signal ≈ SH-01 15 + SH-02 6 = 21 → L0; two consecutive days ≈ 40 → L1. 5a: SH-13 (10) on day −10; after day −9 ≈ 30–38 → L1; day −3 ≈ 55 → L2 "Confirm it's you" by SMS OTP/passkey/TOTP on **every device in the L2 evidence**, even though both are owner-verified (email OTP refused); day 0 ≈ 71 with gates met (categories C, D, N; concurrency on 5 days in 14; separated-use evidence on 5 days; L2 passed then a new C signal) → **L3 although every device is owner-verified** (see SCN-09). 5a-2: ≈ 55 → L2 only; HC-01 not met (needs 3 days). 5c: all overlaps S2 × 0.1, no SH-13, ≈ 15–25 → L0/L1: **expected under-detection, accepted outcome** (residual R1; §2.16 UD-01). 5d: HC-01 applies L3 on day 0 regardless of score (case `engine_hc_L3`) |
| Security rule tested | Session cap, stream cap; SH-01 (S3 × 1.0 never discounted), SH-02, SH-03, SH-05, SH-13; L2/L3 gates incl. `risk.L3.min_separated_days` (RE §5.3); network cap 20; HC-01 (5d) |
| Events recorded | `security_signals` (`cap.stream`, `cap.session`, SH-01 with `separation_class = S3`, SH-02, SH-03, SH-05, SH-13; evidence with /16 prefixes, network types and state codes only); `risk_evaluations` per level change (trigger `heartbeat_batch`, `verification`, `playback`, `nightly`; `gates.separated_days`); `playback_sessions` `taken_over`; `auth_sessions` `session_cap_evicted` / `risk_L3`; L3 `account_restrictions` + `security_cases` |
| Risk score / severity | Isolated day 21 / none. 5a: day −10 ≈ 10–18 / none; day −9 ≈ 30–38 / info (L1); day −3 ≈ 55 / low (L2); day 0 ≈ 71 / medium (L3). 5a-2: ≈ 55 / low. 5b: 0 / info. 5c: ≈ 15–25 / none–info |
| User-facing response | Conflict dialog; chooser; L1 banner "New activity on your account" (UNB §1.1); L2 interstitial (UNB §1.2); L3 restricted screen (UNB §1.3) |
| Admin notification | None at L1/L2 (queue counter only); L3 → case in H1 (medium), SLA 24 h |
| Auto-restriction appropriate? | L1/L2 automatic: yes (non-punitive). L3 only once the multi-day, multi-category, separated-use gates are met (or HC-01 in 5d). Never on day 0 of the first overlap. 5c: no |
| Recovery / appeal | Owner OTP clears L2 when the re-verifications pass and score < 35; L3: unblock request, or auto-lift at 24 h after re-verification + device review (SCN-10/11/20) |
| Automation | TS-RISK fixture (multi-day, injected clock; goldens = RE §5.1 examples B and C), integration (caps), E2E (two contexts for conflict dialogs) |
| Ambiguity | AMB-01 and AMB-18 resolved (RE §4.2.1, §5.3; rows 5a, 5c) |

### 4.7 SCN-06 — Several accounts on the same browser/device

| Field | Specification |
|---|---|
| Preconditions / fixtures | (a) Unregistered family/café PC D9 used by 6 adult accounts in 7 days (RE 6b); (b) registered org-A lab PC used by 35 org-A students in a week (RE 6a); (c) D9 also used by a minor; (d) reseller variant: one hosting-ASN device used by 8 accounts with 5 new tokens in 24 h (RE 6c); (e) a restricted (L3) account's device logs into a brand-new account within 7 days; (f) the org-A lab PC is used by a student of org-B 3 times in 7 days |
| Steps | Log each account in and out sequentially on the same device cookie; run the nightly batch |
| Expected result | (a) SH-11 (4 pts, cap 8 per 7 days) on each adult account; device node flagged in H2 (device–account graph); no access change. (b) No SH-11; lab devices excluded from personal device caps; sessions on lab PCs forced to 30 min idle, browser-session cookie, no remember-device; "Shared computer: sign out when done" banner. (c) Minor gets no SH-11. (d) Reseller pattern (SH-09 + SH-11 + SH-06, network capped) → L3 if gates met + **L4-recommended** case, High priority (RE 6c). (e) New account cannot reuse the restricted account's verified contacts; **AB-10** on the new account: evidence attached to the restricted account's case; a case on the new account only if it is itself ≥ L2 (UNB §8). (f) **AB-11**: sessions allowed (lab rules apply); at the 3rd use in 7 days the coordinator is asked to review the lab registration |
| Security rule tested | RE §2 case 5; SH-11; lab exception (RE §5.5); minors rule (RE §4.4); reseller gate (RE §5.3 L4); AB-10, AB-11 (RE §4.5) |
| Events recorded | `user_devices` per account on one `devices` row; SH-11 signals; nightly `risk_evaluations`; (d) case `engine_recommend_L4`; (e) AB-10 signal (`family = abuse`); (f) AB-11 signal |
| Risk score / severity | (a) ≈ 4 each (max 8) / none; (b) 0; (c) n/a; (d) ≈ 80–95 / high; (e), (f) no score |
| User-facing response | (a) none; (b) lab banner; (d) L3 screen |
| Admin notification | (a) H2 graph flag only; (d) H1 High priority; (e) case queue; (f) security reviewer, status only to the coordinator |
| Auto-restriction appropriate? | (a)(b)(c) **No**. (d) L3 yes (gated); L4 human only |
| Recovery / appeal | (d) unblock request; dual approval to lift if L4 applied |
| Automation | TS-RISK fixtures; integration for lab enrolment link; E2E for lab banner |
| Ambiguity | AMB-04 resolved: (e) = AB-10, (f) = AB-11 |

### 4.8 SCN-07 — Geographically inconsistent locations

| Field | Specification |
|---|---|
| Preconditions / fixtures | Adult account; session 1 from broadband in Telangana; session 2 from broadband in Delhi (centroids > 1,000 km) 40 min later; variant with mobile ASN (Jio IP geolocating to 3 states); variant with overlap (both active); variant: first successful login from outside India in 180 days |
| Steps | Create the two sessions; run evaluation |
| Expected result | Non-overlapping: SH-10 (4 pts, cap 8) → L0, no user impact. Mobile ASN: SH-10 not raised. Overlapping: SH-01 (S3) + SH-02 path as in SCN-05. Network evidence alone never exceeds 20 points, so it can reach at most L1. Outside-India login: TO-09 (15 takeover points) + "Was this you?" notice only. No takeover "impossible travel" rule exists (by design) |
| Security rule tested | SH-10, SH-02, `risk.network_points_cap` (🔒 < L2), TO-09 |
| Events recorded | SH-10 signal (state codes only, no raw IP); evaluation row if score changes by ≥5 |
| Risk score / severity | ≤8 / none |
| User-facing response | None (new-device OTP if the device is new) |
| Admin notification | None; visible in the H12 user security timeline (H3 for overlaps) |
| Auto-restriction appropriate? | **No** — state-level IP geolocation is unreliable in India (brief; RE §4.2) |
| Recovery / appeal | n/a |
| Automation | TS-RISK fixture; property test that network-only fixtures never exceed L1 |
| Ambiguity | AMB-17 resolved (RE §4.3 TO-09): no takeover impossible-travel rule, by design (India geo-IP unreliability); domestic geo jumps raise SH-10 only (adults, broadband), ≤ 8 → L0 |

### 4.9 SCN-08 — Legitimate student on a VPN

| Field | Specification |
|---|---|
| Preconditions / fixtures | Adult account; IP-intel marks egress `network_type = vpn_proxy` (corporate VPN), then iCloud Private Relay; Tor variant; variant: laptop on the VPN while the owner-verified phone is on home Wi-Fi, overlapping daily |
| Steps | Log in daily for 10 days through the VPN; learn normally |
| Expected result | Login and learning unaffected. SH-09 4 per day, capped at 8 per 7 days, counted inside the network cap → L0. Overlap variant: a VPN leg makes the pair S2 (× 0.1 when both devices are owner-verified), never S3. Tor variant: TO-07 (15) + SH-09 → below T-step-up (40) unless combined with other TO signals. Per-IP limits on a shared VPN egress may throttle *pre-auth* only, which does not count toward the account lockout |
| Security rule tested | SH-09; §4.2.1 S2 for `vpn_proxy` legs; TO-07; network cap; pre-auth blocks not counted (RE §7.1) |
| Events recorded | SH-09 signals; SH-01 with `separation_class = S2` in the overlap variant; `login_attempts.pre_auth_blocked` if throttled |
| Risk score / severity | ≤ 10 / none (RE row 8) |
| User-facing response | None |
| Admin notification | None |
| Auto-restriction appropriate? | **No** |
| Recovery / appeal | If combined with other evidence and restricted, the unblock form option "I was travelling / using VPN" applies; a reviewer can grant a time-bound exception (ignore SH-02/SH-09) |
| Automation | TS-RISK fixture; integration (rate limits) |

### 4.10 SCN-09 — Automatic restriction by a configured high-confidence rule

| Field | Specification |
|---|---|
| Preconditions / fixtures | Launch default is `risk.mode = shadow` and `risk.hc.auto_restrict_enabled = false`; each fixture sets them explicitly. (a) Scored sharing path: SCN-05 5a timeline at day 0 (gates met), `risk.mode = enforce`, active ruleset that completed ≥ 14 days of shadow and dual approval. (b) Same as (a) or (e) but an in-progress mock attempt on the evaluated session (RE 9c). (c) Takeover: HC-T1 (breached password, TO-02); HC-T2 (RE 9d: 2,000 failures across 600 accounts from one ASN, then one account's correct password followed by 2 failed OTPs); HC-T3 (TO-04 replay followed by a second replay within 24 h). (d) Negative: ruleset in `shadow`; a draft rule version with no second approver. (e) **HC-01**: S3 overlaps of ≥ 2 devices on 3 days within 14, an L2 re-verification issued ≥ 24 h before the last qualifying day with a qualifying day after it, no lab device, no exception, no FP lift in 30 days, not synthetic; `risk.hc.auto_restrict_enabled = true`; HC-01 version `active` (RE 9a). (f) Same facts with the switch false, or HC-01 version `shadow` (RE 9b). (g) Circuit breaker: 3 `lift_false_positive` among the last 20 decided HC-01 restrictions (RE 9f). (h) Minor with the HC-01 facts (RE 9e). (i) HC-02: ≥ 3 device tokens on ≥ 3 fixed-line clusters in the same 30 min on 2 days within 7 |
| Steps | Feed heartbeats and network observations; run the 5-min batch and the nightly batch; for (c) log in with a breached password / run the stuffing script / replay the cookie twice |
| Expected result | (a) `account_restrictions` level 3, scope `learning_access`, source `engine`, `ends_at = now + 24 h` (72 h for a repeat); **all other sessions revoked** (`risk_L3`); current session's derived scope `restricted`: only `account_status` and `l3_readonly` routes (RE §7.2); case opened (`opened_reason = engine_L3`, priority medium, SLA 24 h/72 h); restriction cache invalidated < 1 s; playback, attempt start, practice, code submit, downloads, certificate issuance blocked. (b) Restriction row written immediately with `deferred_until = min(deadline + grace, now + 3 h)`; **all other sessions revoked immediately** (`risk_L3`); new logins get `restricted`; the attempt session keeps `full` only for that attempt's routes and `restricted` for everything else; restricted at submit or `deferred_until`, whichever is first. (c) HC-T1/HC-T2/HC-T3 → T-protect: all sessions revoked (`takeover_protect`), `must_change_password`, remember-device disabled, email + SMS; self-service recovery. A single replay alone is **not** T-protect (SCN-19). AB-04 flags the stuffing source; its failures do not count toward lockout. (d) Shadow: evaluation rows with `mode = shadow`, no action; unapproved version cannot be activated (SCHEMA `ck_rrv_approval`). (e) L3 regardless of score; `risk_evaluations` `action = restrict_L3`, `gates.hc_rule = 'HC-01'` with params and qualifying days; case `opened_reason = engine_hc_L3`; outbox `account.restricted`; otherwise as (a). (f) Evaluation `mode = shadow` with `gates.hc_rule = 'HC-01'`, no action; ENG counts the shadow match. (g) HC-01 → `shadow` with `status_change_reason = circuit_breaker`, security-lead alert (§2.16 CB-*). (h) Nothing: no SH signal, no HC match, no evaluation row; caps only. (i) HC-02 L3, case priority `high`, `recommended_level` **not** set to 4. In no case does the engine set level 4 (`ck_re_no_auto_l4`) |
| Security rule tested | RE §5.3 L3 gates; §5.6 HC-01, HC-02, HC-T1..T3; §5.7 circuit breaker; §6.1; §7.4 deferral; §6.2 T-protect; §5.4 versioning; brief "L4 human only" |
| Events recorded | `risk_evaluations` (`action = restrict_L3` or `protect_lock`, `gates.hc_rule`), `account_restrictions` (`deferred_until` in b), `security_cases`, `auth_sessions` ended, outbox `account.restricted`, `audit_log`, notifications; (g) `risk_rule_versions` status change |
| Risk score / severity | (a) ≈ 71 / medium; (e), (i) medium (score not required; (i) case priority high); (c) T-protect / high; (f) — |
| User-facing response | (a), (e) UNB §1.3 full-screen state with case reference and "Request a review"; API clients get problem+json `account_restricted` with `case_ref` and `level` (UNB §1.7). (b) Attempt continues, then L3 screen. (c) UNB §1.5 |
| Admin notification | (a), (e) Case in H1 (medium; HC rule column); coordinator status only if `org.notify_coordinator_on_restriction` allows (default: L4 only). (c) ENG spike for (HC-T2); no case unless recovery fails twice or contacts changed within 7 days. (g) Security lead alert; H8 and ENG |
| Auto-restriction appropriate? | **Yes** for (a) and (e) — temporary, gated or configured high-confidence, reversible; **yes** for (c) — protective, self-service. **No** for (f), (h). **Never** for L4 |
| Recovery / appeal | (a), (e) Auto-lift at `ends_at` only after OTP + device review; or SCN-10 → SCN-11/12; (c) OTP + password reset; (g) re-activation by Dual approval |
| Automation | TS-RISK (a, b, d–i), integration + E2E (restricted screen, API 403), TS-SESS (c) |
| Ambiguity | AMB-03 resolved (no PO decision needed: HC-01/HC-02 and HC-T1..T3, RE §5.6); AMB-20 and AMB-21 resolved (RE §7.2, §7.4); AMB-23 and AMB-24 resolved (RE §3.2, §5.7) |

### 4.11 SCN-10 — Unblock request with a legitimate explanation

| Field | Specification |
|---|---|
| Preconditions / fixtures | Student under L3 from SCN-09(a); in a `restricted` session; devices D1 (own), D3 (unrecognised) |
| Steps | 1. Click "Request a review". 2. Choose "A family member used my account", write a 200-char explanation, mark D1 recognised, leave D3 unticked, upload one PDF, choose SMS, accept declaration. 3. Submit with an `Idempotency-Key`. 4. Re-submit with the same key. 5. Try a second request on the same case. 6. Try explanation text containing "OTP 482913". 7. Submit 3 more requests over 30 days on new cases |
| Expected result | 201 with `APL-YYMM-XXXXXX` linked to the `SEC-` case; state `submitted`, then `under_review` on assignment (skipping conflicted reviewers); D3 sessions revoked and trust cleared on submit; acknowledgement in-app + SMS; SLA timers set (L3: first response 24 h, decision 72 h). Step 4 → same response, no duplicate. Step 5 → 409 (one open request per case, 🔒). Step 6 → inline rejection "Please don't include passwords or codes" and server DLP masks before storage. Step 7 → 4th request in 30 days refused (429). Rate limits only, no CAPTCHA: 1 open request per case, 3 per 30 days, 5 form loads per minute (6th load → 429). Contact changes are blocked while restricted |
| Security rule tested | UNB §3 validation, DLP, limits, Idempotency-Key; §4.2 transitions; §8 bypass prevention |
| Events recorded | `unblock_requests`, `audit_log` (created, state change, devices removed, sessions revoked), notification rows, outbox |
| Risk score / severity | Unchanged (score is not modified by filing) |
| User-facing response | "We've received your request {APL}", then "A reviewer is looking at your case" |
| Admin notification | H6 pending unblock requests counter; assignee notified |
| Auto-restriction appropriate? | n/a (no new restriction) |
| Recovery / appeal | Proceeds to SCN-11 or SCN-12; if L3 expires first and the student re-verifies, the request closes as `moot` |
| Automation | Integration (TS-UNB), E2E (form, upload, a11y), unit (DLP patterns, reference generator) |
| Ambiguity | AMB-19 resolved (UNB §3: no CAPTCHA) |

### 4.12 SCN-11 — Administrator approves and revokes suspicious sessions

| Field | Specification |
|---|---|
| Preconditions / fixtures | SCN-10 request `under_review` with R1; case not high-risk; variant: L4 high-risk case (repeat incident); variant: R1 is the person who applied the restriction |
| Steps | 1. R1 claims (step-up within 5 min, reason code `case_review`). 2. R1 tries to decide before opening explanation and timeline → refused. 3. R1 opens panels, kills D3's remaining session (`session.revoke`, reason required), records `lift_false_positive` or `lift_with_warning` with ≥50-char student summary. 4. Student completes re-verification (OTP to a contact that existed before the restriction; MFA if enrolled), device review. 5. Student logs in fresh. Variant: high-risk L4 → R1's decision is stored as a proposal; R1 tries to approve it; R2 approves. Variant 2: R2 sends it back. Variant 3: nobody acts for 72 h |
| Expected result | Restriction `lift_pending` (still enforced) until step 4; then **all** sessions revoked (`unblock_reset`, `sessions_valid_after = now`, restricted session included, remember-device tokens invalidated); restriction ended (`case_decision`); Redis restriction cache invalidated; fresh session only after full authentication; entitlements accessible immediately with no commerce change; FP outcome adds extension credit when PO-10 is on; trainer notified about interrupted attempts; request → `approved` → `closed` (`completed`). Variant: R1's decision → `202` with `approval_request_id`, **no `case_decisions` row**, request and case `escalated`; R1 approving own request → `sod_violation`; R2 approves via the approval-request path → `case_decisions` inserted (`decided_by = R1`, `approved_by = R2`, `approval_request_id`) and only then `lift_pending`. Variant 2: approval `rejected`, request back to `under_review`. Variant 3: approval `expired`, case stays `escalated`, SLA alert (§2.16 AR-*) |
| Security rule tested | UNB §5 second-person rules, §6 procedure, §7 guard rails; RPM SoD-06; brief step-up 5 min |
| Events recorded | `case_decisions`, `approval_requests` (variant), `auth_sessions` ended (`admin_kill`, `unblock_reset`), `account_restrictions.ended_*`, outbox `restriction.lifted`, `audit_log` for each step incl. PII reveal |
| Risk score / severity | FP: contributing signals suppressed, score recomputed; warning: score decays normally, repeat window starts |
| User-facing response | "Your review was approved — finish these steps to get back in", then "Access restored"; revoked devices see UNB §1.6 |
| Admin notification | Coordinator status only (if policy); H7 review time recorded |
| Auto-restriction appropriate? | n/a |
| Recovery / appeal | Complete; repeat incidents within 180 days apply SH-M1 |
| Automation | Integration (TS-UNB, TS-AUTHZ for decide permission and support-agent refusal AC-SEC-02), E2E (reviewer console + student flow) |
| Ambiguity | AMB-13 resolved (UNB §5.1: proposals live in `approval_requests`) |

### 4.13 SCN-12 — Administrator rejects with a reason

| Field | Specification |
|---|---|
| Preconditions / fixtures | Request `under_review` with R1 |
| Steps | 1. R1 records `uphold` with a 30-char summary → refused. 2. With a ≥50-char student summary → accepted. 3. Student appeals within 14 days. 4. R1 tries to take the appeal. 5. R2 decides. 6. Student tries a second appeal. 7. Separate run: no appeal for 14 days |
| Expected result | Step 1 rejected (SCHEMA `student_summary` ≥ 50; `ck_cd_reject_summary`). Step 2: state `rejected`; student told reasons, how to appeal (14 days) and the DPDP grievance route; restriction remains. Step 3: `rejected → escalated`, student label "With senior reviewer". Step 4 refused (different reviewer required). Step 6 refused (one second-level appeal). Step 7: `closed` with `rejected_final` |
| Security rule tested | UNB §4.2; SoD; DPDP grievance obligations |
| Events recorded | `case_decisions` (`uphold`), `case_notes` (student-visible), state changes, `audit_log`, notifications |
| Risk score / severity | Unchanged; counts as a confirmed decision for SH-M1 only if the outcome is confirmed (not FP) |
| User-facing response | Decision message with reasons in plain language (no thresholds or weights, UNB §8) |
| Admin notification | Senior pool on appeal; SLA 24 h / 72 h after escalation |
| Auto-restriction appropriate? | n/a |
| Recovery / appeal | One second-level appeal. Rejection refuses an early lift only: at `ends_at` the L3 auto-expires after re-verification and the rejected request closes as `moot` (assert with the clock moved past `ends_at`) |
| Automation | Integration (TS-UNB), unit (state guards), E2E (student view) |
| Ambiguity | AMB-16 resolved (UNB §4.3) |

### 4.14 SCN-13 — Blocked user calls private content APIs directly

| Field | Specification |
|---|---|
| Preconditions / fixtures | User A under L3 with `restricted` session; user B under L4 with `status_only` session; user C whose other sessions were revoked by L3; a VdoCipher OTP and a signed S3 URL issued to A 2 minutes before the restriction |
| Steps | Using curl (no UI) with each session cookie and CSRF token: `POST /media/playback-tokens`, `POST /attempts`, `POST /attempts/{id}/autosave`, `POST /coding/submissions`, practice answer save, lesson resource download, certificate issue, placement-drive registration (P2), `POST /analytics/events`; also allowed routes: tag `account_status` (`GET /me`, own devices and sessions, cases, unblock requests and re-verification, privacy and consent requests incl. data export (DSAR), billing view/invoices/cancel/refund request, support, notifications inbox, logout) and, for L3 only, tag `l3_readonly` (dashboard, enrolments, progress, certificate list, own results). Send ≥ 30 denied calls within 10 min as A. Repeat with C's revoked token. Call `entitlements.check` directly in an integration test. Generate the full route list via TS-AUTHZ with restriction states L3/L4 |
| Expected result | Every `default`-tagged route → **403 problem+json `code=account_restricted`** with `case_ref`, `level` and `until`, no content in the body; `account_status` routes → 2xx for A and B; `l3_readonly` routes → 2xx for A, 403 for B (L4 `status_only`); C's revoked token → 401. Scope is derived per request from the restriction cache, so an L3 applied mid-session takes effect on the next request. A's 30th denial within 10 min → AB-08 signal (info), no escalation of the restriction. `entitlements.check` returns `allowed=false, reason=account_restricted` for any resource class except `account_status` (defence in depth). Already-issued playback: next heartbeat → 410, overrun ≤ 90 s; signed URL expires within its 5 min/1 min TTL. Clearing cookies or a new browser does not help (restriction bound to `user_id`). The CI route check (G-05) proves no route lacks the dependency |
| Security rule tested | `require_active_principal` (RE §7.2 step 7; brief §5); RE §7.3–7.6; UNB §8 |
| Events recorded | Request log with `request_id`; AB-08 `security_signals` row (`family = abuse`) at ≥ 30 denials in 10 min |
| Risk score / severity | Unchanged / info |
| User-facing response | UNB §1.7 payload; UI shows the restricted screen |
| Admin notification | None (AB-08 visible in the case timeline and the ENG counter) |
| Auto-restriction appropriate? | n/a — already restricted; probing must not escalate automatically |
| Recovery / appeal | SCN-10 |
| Automation | TS-AUTHZ (generated), integration, G-05 static check; E2E only for the screen |
| Ambiguity | AMB-04, AMB-15, AMB-20 resolved (RE §4.5, §7.2) |

### 4.15 SCN-14 — The same payment webhook is delivered repeatedly

| Field | Specification |
|---|---|
| Preconditions / fixtures | Order for a course plan; valid signed Razorpay `payment.captured` payload (recorded in test mode) |
| Steps | POST to `/api/v1/webhooks/razorpay`: deliver the identical request 3× sequentially; 3× concurrently; then the same `event_id` with a modified body and a recomputed bad signature; then a different event for the same payment (`order.paid`); then the original delivered again 6 h later; then a different valid event for the same payment 6 h later; then a delivery while the provider API is down |
| Expected result | Exactly one `payments` row, one entitlement, one invoice (AC-COM-01); every valid duplicate gets 2xx so the provider stops retrying; tampered body → `400 webhook_signature_invalid`, no state change, AB-12; `order.paid` causes no second grant; the entity is re-fetched from the provider and amount/currency re-checked against `orders`. No request is rejected for age: the 6 h-late identical delivery → 2xx `duplicate`, no effect; the 6 h-late different event → 2xx, re-fetch, no second grant (`refetch_status = ok`). Provider API down during re-fetch → retries, no state change until it succeeds |
| Security rule tested | HMAC over raw body, constant-time compare; dedupe `UNIQUE (gateway, event_id)` in the same transaction as the side effect; server-side re-fetch for stale/out-of-order events (ADR-0006 v0.3); monotonic state (TM §2.4; abuse case A8); AB-12 |
| Events recorded | `payment_webhook_events` (one row per unique event, `status`, `attempts`, `is_stale`, `refetch_status`); duplicate counter metric; `security_signals` `rule_key = AB-12` for the tampered body; `entitlement_events` once; outbox `entitlement.granted` once |
| Risk score / severity | Not a user-risk event; duplicates = info; invalid signatures = medium (high if > 10/min) |
| User-facing response | Student sees one purchase and one invoice |
| Admin notification | Finance/ops alert on webhook lag > 5 min (NFR-OBS-02); ops on-call when AB-12 > 10/min per provider; none for normal duplicates |
| Auto-restriction appropriate? | **No** (provider traffic, not user behaviour) |
| Recovery / appeal | Daily reconciliation fixes missed events; finance can re-drive from the DLQ |
| Automation | Integration (replay harness, TS-PAY), concurrency test with parallel requests; nightly live test mode |
| Ambiguity | AMB-10 resolved (TM §2.4; ADR-0006 v0.3) |

### 4.16 SCN-15 — An inactive tab stays open for hours

| Field | Specification |
|---|---|
| Preconditions / fixtures | Adult student, trusted laptop, remember-device on and off variants; staff (trainer) and privileged (finance) variants; lab-device variant |
| Steps | AN Example 2: open text lesson 14:00, input until 14:12, leave tab visible and focused until 18:00. Variant: paused video tab. Variant: tab hidden (minimised). Variant R: remember-device on; at 18:00 (i) a background XHR/heartbeat, (ii) a top-level navigation (`Sec-Fetch-Mode: navigate`, `Sec-Fetch-User: ?1`), (iii) the same navigation after `remember_until`, (iv) a superseded remember token. Variant A: timed 120-min attempt started at 14:00, no input for 70 min. Variant S: attempt start when `absolute_expires_at < deadline_at + grace + 5 min`. Variant H: browser sends `X-TD-Activity: navigation` itself |
| Expected result | M2 = M5 = 15 min (credit until 14:15 via `T_idle(lesson_text)` = 180 s); keepalives (`x-td-idle = neutral`) every 5 min earn 0 and **do not** extend the auth session; engaged ingest extends idle only via `touch_engaged`; session idle-expires 60 min after the last engaged activity (≈ 15:12–15:15) with `end_reason = idle_timeout`; the next background request gets `401 session_expired` (`reason = idle_timeout`) and the client stops; M1 ≈ 75 min labelled "Time signed in (approx.)". Staff: 30 min idle; privileged: 15 min; lab PC: 30 min. No security signal. R: (i) 401, **no** remember-device re-issue; (ii) new session `created_via = remember_device`, `aal = 1`, `auth_time` copied, remember token rotated; (iii) full login required (`remember_until` fixed, never slides); (iv) TO-10: remember credential and presenting session revoked. A: session stays valid until `deadline + grace + 5 min` (`idle_hold_until`) despite no input. S: `409 session_too_short_for_attempt` with `reauth_url`. H: header stripped by the BFF; idle not extended |
| Security rule tested | Brief §1 "idle timer is extended only by engaged activity; analytics keepalives never extend it"; RE §1.4 rules 1–6; AN §3.2–3.3; RE §8; TO-10 |
| Events recorded | Heartbeats (keepalive kind), `engagement_intervals` closed by `page.idle_change`, `auth_sessions` ended `idle_timeout`, outbox `session.ended` |
| Risk score / severity | 0 / none |
| User-facing response | On return: signed-out message and login; progress preserved |
| Admin notification | None |
| Auto-restriction appropriate? | **No** |
| Recovery / appeal | Log in again (new-device OTP not needed on a trusted device) |
| Automation | TS-TIME (simulation with injected clock), TS-SESS (timeouts per tier), E2E (Playwright `setIdleOverride`, clock control) |
| Ambiguity | AMB-05, AMB-06, AMB-07 resolved (RE §1.4) |

### 4.17 SCN-16 — Browser crash during a timed assessment

| Field | Specification |
|---|---|
| Preconditions / fixtures | Adult student, 60-min mock, 25 questions answered and synced, 2 more answered but unsynced in IndexedDB; variants: (A) reopen same browser, session cookie survives; (B) reopen same device but session cookie lost → new login; (C) device dead, continue on phone; (D) never return; (E) student at L2 |
| Steps | Kill the browser process at minute 20 (no `pagehide`); reopen at minute 35 |
| Expected result | (A) Session cookie survives the crash (`Max-Age` to absolute expiry) and `idle_hold_until` keeps it valid; resume on the same session; all 27 answers present (IndexedDB entries merged by `client_seq`); remaining time = server `deadline_at − now` ± 2 s (AC-ASM-01); `attempt_events` `disconnect`, `resume`; analytics interval closed by `timeout_grace`; M4 counts wall time, `assessment_active_s` excludes the gap; no penalty. (B) Re-login on the same device ends the old session as `replaced_same_device` (not an eviction, not SH-04) and **re-attaches** the attempt automatically: `bound_session_id` updated, `attempt_events` `reattach_same_device`, `rebind_count` unchanged, no prompt, no OTP even at ≥ L2, `idle_hold_until` set on the new session. (C) Phone (different `device_id`) → `409 attempt_bound_elsewhere` → "Continue here?" → rebind (1 of 2); if the student abandons the rebind → SH-08 (10 pts). (D) Auto-submit within 10 s after deadline + grace with last synced answers; later answers rejected `409 attempt_closed` and logged (AC-ASM-03). (E) Student at L2: same-device re-attach still needs no OTP; a rebind to another device needs OTP. Third rebind to another device refused (max 2); proctored drive requires a trainer override. (F) R-2 interplay: when a third login hits the session cap, attempt-holding sessions are never auto-evicted; if every other session holds an attempt → `409 session_cap_reached` |
| Security rule tested | Server-authoritative timer (ARCH §8.4); session cookie lifetime (RE §1.4 rule 6); same-device re-attach and other-device rebind (RE §6.3, §7.4, PO-08); SH-08; AN §3.8 |
| Events recorded | `attempt_events` (`disconnect`, `resume`, `reattach_same_device`, `rebind_requested`, `rebind`, `rebind_refused`, `auto_submit`); `auth_sessions` ended `replaced_same_device` (B); `cap.attempt_bind` signal (C); outbox `attempt.submitted` |
| Risk score / severity | 0 normally; 10 / none if the rebind is abandoned |
| User-facing response | (B) none (silent re-attach); (C) "This test is open on {device}. Continue here?"; restored answers; timer from server |
| Admin notification | Trainer sees rebind/disconnect in the attempt log and may grant an audited override |
| Auto-restriction appropriate? | **No** — disconnects are events, not penalties |
| Recovery / appeal | Rebind; trainer override for lost time |
| Automation | Integration (attempt state machine), E2E (Playwright kill context; IndexedDB persistence), TS-TIME (Example 3/4), TS-PERF P1 |
| Ambiguity | AMB-08 resolved (RE §1.4, §6.3, §7.4) |

### 4.18 SCN-17 — Multiple tabs used to manipulate time tracking

| Field | Specification |
|---|---|
| Preconditions / fixtures | Adult student and minor variants; scripted client (not the SDK) with a valid session and CSRF token |
| Steps | 1. Five visible tabs with simulated input (mouse jiggler). 2. Replay 100 heartbeats with `active_ms = 60000` each in one second. 3. Set the client clock +3 h and −2 days; forge `occurred_at` in the future. 4. Put another user's `user_id`/`session_id` in the payload. 5. Credit time to a lesson the user is not entitled to. 6. Send heartbeats every 2 s. 7. Inflate video coverage by seeking and sending `rate = 4.0`. 8. Run 20 h/day for 3 days. 9. Change the client clock during a timed attempt. 10. Try to complete a lesson or earn a certificate on time alone |
| Expected result | 1. Union: ≤ 1 active second per wall-clock second per user. 2. Per-sample cap `C_max` 20 s and credit ≤ Δ server time → no extra time. 3. `effective_at` corrected; future → `event_in_future`; beyond 72 h → `event_too_old`; UUIDv7 mismatch → `uuid_time_mismatch`; flags `large_skew`/`clock_jump`. 4. Identity from session only; payload identity ignored. 5. `entity_not_entitled`. 6. Engaged heartbeats < 10 s apart per page instance dropped as `rate_capped` (still 200); > 30 requests/min per session or > 60/min per user → 429 (AN §5.2). 7. Schema rejects rate > 2.0; coverage only from played ranges; `implausible_clamped`. 8. M2 > 16 h → day `implausible`, excluded from percentiles and leaderboards. 9. Assessment time unchanged (server timestamps). 10. Impossible: completion/certificates need server-verifiable evidence (BR-EVD-01) |
| Security rule tested | AN §5.2 limits, §5.5 rules 1–8; TM §2.7 T; brief learning-evidence rule; IN-01, IN-02 (RE §4.5) |
| Events recorded | `analytics_ingest_rejections` by code; ingest flags; IN-01 `security_signals` (`family = integrity`) for the implausible day (step 8); IN-02 at ≥ 50 forgery rejections (`uuid_time_mismatch`, `event_in_future`, identity mismatch) in 1 h for the session (steps 3–4 repeated) → ingest for that session ignored 1 h; per-event results in the 200 response |
| Risk score / severity | IN-01 and IN-02 never score; **no sharing signal**; plausibility = low |
| User-facing response | None (silent per-event rejection); students see only credited time with "How we measure" |
| Admin notification | Ingest-health dashboard (AN §7.4); no individual alert |
| Auto-restriction appropriate? | **No** |
| Recovery / appeal | n/a; a student disputing time goes to support |
| Automation | TS-TIME (scripted client), unit (crediting), integration (ingest), E2E (multi-tab real browser for step 1) |
| Ambiguity | AMB-04 resolved (IN-01 is not a sharing input); AMB-11 resolved (AN §5.2 is the single source) |

### 4.19 SCN-18 — Administrator accesses another institution's records

| Field | Specification |
|---|---|
| Preconditions / fixtures | Coordinator X of org-A; trainer T of batch A1; mentor M of batch A1; org-B with students, batches, results, invoices, tickets, exports, certificates; platform staff: finance F, support S |
| Steps | 1. X requests org-B student, batch, report, export, invoice and certificate IDs via path params, query filters and bulk endpoints. 2. X forges `organization_id = B` in a request body. 3. X invites an email that exists in org-B. 4. T requests a sibling batch A2 in the same org. 5. A forged SQL path (integration test) sets `app.org_ids = A` and selects org-B rows. 6. X sends 25 such requests in one minute. 7. F reads a security case; S reads signal evidence. 8. Super admin reads org-B records without break-glass where the matrix says BG |
| Expected result | 1. **404** (not 403) for every cross-org object, logged (AC-ORG-02, TI-02); list endpoints never include org-B rows; exports and signed URLs are bound to the requester's session and scope. 2. Body `organization_id` ignored for authorisation; mismatch → 422/404 (TI-11). 3. "Invite sent" with no existence disclosure (TI-05). 4. 404 unless granted on A2. 5. RLS returns 0 rows. 6. AB-09 at ≥ 20 404s/min per user on ID routes, or ≥ 5 requests in 1 h resolving to another tenant's object → security-lead alert; no automatic action. 7. 403 (SoD-01, SoD-03). 8. Denied outside break-glass; break-glass access flagged for review |
| Security rule tested | RPM TI-01..TI-11, SoD-01/03/07; API1/API5; RLS FORCE |
| Events recorded | Request log + `audit_log` (denied access with permission attempted); `security_signals` `rule_key = AB-09`, `family = abuse` |
| Risk score / severity | Single attempt: medium; burst: high |
| User-facing response | Generic not-found |
| Admin notification | Security lead alert on the threshold; monthly access review |
| Auto-restriction appropriate? | **No** automatic restriction of staff; a `security_reviewer` may kill sessions (step-up) and open an incident |
| Recovery / appeal | Incident process; grant review |
| Automation | TS-AUTHZ (generated), TS-RLS, integration for the alert (both AB-09 thresholds, boundary 19/20 and 4/5), E2E smoke for coordinator UI |
| Ambiguity | AMB-04 resolved (AB-09) |

### 4.20 SCN-19 — Changing a session identifier or reusing a revoked session

| Field | Specification |
|---|---|
| Preconditions / fixtures | Adult student with active session S1 on D1; minor variant |
| Steps | 1. Change one character of the `__Host-td_session` value. 2. Log out, then replay the old token. 3. Revoke S1 from another device ("sign out other devices"), then replay. 4. Session fixation: plant a token before login. 5. Send the token in a URL parameter or `Authorization` header from a browser. 6. Replay S1's cookie from a different browser without/with a different `__Host-td_device`; adult also has active session S2 on D2. 6b. A second replay within 24 h (or the owner clicks "This wasn't me"). 6c (TO-08 variant). Copy both S1's session and device cookies into a different browser family and replay. 7. Revoke all (password change) while the Redis user-session set is missing a key, and with `sess:{hash}` evicted from Redis; replay. 8. 1,000 random tokens from one IP /24 within 10 min |
| Expected result | 1, 2, 3 → 401 (a token unknown to both Redis and Postgres is rejected in strict mode and counted by AB-07; a revoked token stays revoked). 4 → a new token is issued at login (rotation); the planted value never authenticates. 5 → ignored (cookie only for browsers). 6 → TO-04: **only S1** revoked (`device_mismatch`, status `blocked`), `401 session_revoked`; S2 stays active; adults get a takeover evaluation (+60 → T-step-up: MFA/SMS OTP on the next login and the next sensitive action on S2); owner notice UNB §1.6a with "This wasn't me". 6b → HC-T3 → T-protect: all sessions revoked (`takeover_protect`), `must_change_password`, remember-device disabled. 6c → TO-08, same outcome as step 6. 7 → Redis miss falls back to Postgres; 401 through the `sessions_valid_after` cutoff. 8 → all 401; from the 20th unknown token in 10 min AB-07 throttles the /24 on authenticated routes for 15 min; security lead alerted at ≥ 100. Minor: TO-04/TO-08 revoke applies deterministically, no score; **no `risk_evaluations` row**; one `security_signals` row (`family = takeover`, `base_points = 0`, `is_minor_at_time = true`) plus the session end record; HC-T3 still applies to minors |
| Security rule tested | RE §1.6 (Postgres source of truth); RE §7.2 steps 2–6; RE §8 revocation semantics; ASVS session rotation; TO-04, TO-08; HC-T3; AB-07 |
| Events recorded | `auth_sessions` ended (`user_logout`, `user_revoked_other`, `device_mismatch`, `password_changed`, `takeover_protect`); `security_signals` TO-04 / TO-08 / AB-07; takeover `risk_evaluations` (adults only; `action = step_up`, then `protect_lock` on HC-T3) |
| Risk score / severity | TO-04 / TO-08: T 60 / high (single-session revoke + T-step-up); HC-T3: T-protect / high |
| User-facing response | Owner: "We signed out a session that looked unusual. If this wasn't you, secure your account" (UNB §1.6a); revoked device: UNB §1.6; HC-T3: UNB §1.5 |
| Admin notification | Takeover queue only on HC-T3 (case only if recovery fails twice or contacts changed within 7 days); AB-07 alert at ≥ 100 |
| Auto-restriction appropriate? | **Yes**, limited to revoking the replayed session (all sessions only on HC-T3) |
| Recovery / appeal | Owner signs in again on the affected device with MFA/OTP (T-step-up); after HC-T3, OTP + password reset |
| Automation | TS-SESS integration, E2E (cookie tampering via Playwright `context.addCookies`; second browser engine for 6c) |
| Ambiguity | AMB-02, AMB-09, AMB-12 resolved (RE §1.6, §4.3, §4.4, §6.2) |

### 4.21 SCN-20 — Student disputes a false-positive sharing decision

| Field | Specification |
|---|---|
| Preconditions / fixtures | Adult student restricted L3 for 4 days by overlap evidence that was actually a laptop + college lab PC not yet registered; active subscription and an active time-bound college entitlement; an interrupted mock attempt. Variant: case had `recommend_L4` and score ≥ 90 |
| Steps | 1. Student files an unblock request ("I was using a college lab / shared computer") and requests an evidence pack. 2. Coordinator attests lab usage via case note. 3. R1 decides `lift_false_positive` and grants a per-user exception or approves the network registration. 4. Variant: R1's FP override of `recommend_L4` goes to R2. 5. Student completes re-verification |
| Expected result | Evidence pack generated by a security reviewer only, limited to data relevant to the decision (RPM §8). Coordinator attestation is evidence only (cannot lift). Lift per SCN-11. Signals that drove the decision get `suppressed_by_decision_id`; score recomputed without them; H8 FP counter increments for each contributing rule and, if the L3 was HC-applied, for that HC rule (circuit-breaker input, §2.16 CB-*); extension credit = `ceil(restricted days, incl. any L4 period of the case)` = 4 days added to **every** time-bound entitlement active during the restriction (subscription and college entitlement), with a college-contract seat capped at the contract end and the remainder recorded in `conditions.uncredited_days` (variant: contract ends in 2 days → 2 credited, 2 uncredited), with audit (PO-10; AC-ENT-04); trainer notified about the interrupted attempt (security never edits scores); exception is time-bound (≤ 180 days) and visible to the student. Variant: second approval required (UNB §5 rule 2). FP rate alert when L3 FP > 10 % over 30 days or a rule contributes to > 3 FP cases per week |
| Security rule tested | UNB §5–§6 (step 8 credit rule); RE §5.5 exceptions; RE §5.7 breaker input; RE §10 H8; DPDP s.8(3) accuracy |
| Events recorded | `case_decisions` (`lift_false_positive`, `extension_days`), signal suppression, `entitlement_events` (`security_false_positive_credit`), `policy_settings` user exception, `org_trusted_networks` update, `audit_log` |
| Risk score / severity | Recomputed (expected L0); severity of the original case recorded as false positive |
| User-facing response | Approval message, then "Access restored" with what to watch for; exception shown on devices page |
| Admin notification | H8 dashboard; security lead alert on FP thresholds |
| Auto-restriction appropriate? | n/a (this tests the correction path) |
| Recovery / appeal | Complete; if rejected instead, SCN-12 second-level appeal and DPDP grievance |
| Automation | TS-UNB integration, TS-RISK (suppression and recompute), TS-PAY/entitlements (extension), E2E (student + reviewer) |
| Ambiguity | AMB-13 resolved; AMB-14 resolved, pending PO-10 confirmation |

### 4.22 Retained regression scenarios from RE §11 (not in the owner list)

Ids are identical to RE §11 rows R-1..R-9. Former RX-06 (credential stuffing) is now RE row 9d and is tested as SCN-09 (c).

| ID | Former id | Scenario | Key expectation | Suite |
|---|---|---|---|---|
| R-1 | RX-01 | Chrome + Edge on one laptop, same Wi-Fi, both active | 2 devices counted; S0 × 0.1 (× 0 with matching fingerprint); ≈ 15 steady → L0; "probably this computer" grouping | TS-RISK |
| R-2 | RX-02 | Third login while 2 sessions active; one holds an attempt | Pending session `pending_session_choice` (expires after 5 min); chooser pre-selects the oldest non-attempt session; non-interactive client evicts it (`session_cap_evicted`); if both hold attempts → `409 session_cap_reached`, no eviction; AC-SES-02 | TS-SESS, E2E |
| R-3 | RX-03 | Fourth trusted device | After OTP, "Remove a device to continue"; AC-SES-01 | TS-SESS, E2E |
| R-4 | RX-04 | Third replacement in 30 days | Blocked until date; support grants +1 with logged reason | TS-SESS |
| R-5 | RX-05 | Daily incognito, single person, no overlap | SH-06 + SH-05 ≈ 16–24 → at most L1; L3 gate fails (no C, no separated use) | TS-RISK |
| R-6 | RX-07 | 17-year-old overlapping 2 devices for a week, hitting the stream cap | Only deterministic caps; no SH, no score, no L3, **no evaluation rows** | TS-RISK, TS-PRIV |
| R-7 | new | Student lifted with `lift_with_warning` in Sept re-offends in Nov | × 1.25 repeat (SH-M1); L3 for 72 h; L4 recommended (≥ 90); reviewer applies L4; lift needs second approval (`approval_requests`) | TS-RISK, TS-UNB |
| R-8 | new | Bad rule version restricts 300 students in one org overnight | Kill switch to shadow (single approver, ratified ≤ 24 h); bulk lift by selector with Dual; 300 `case_decisions` `lift_false_positive`; credits; notifications (§2.16 KS-*, BL-*) | TS-RISK, TS-UNB |
| R-9 | new | Owner verifies a new office laptop at work while a family member streams at home | SH-13 (10) + S3 overlap if they overlap; ≈ 25–45 → L1/L2 at most unless repeated on ≥ 3 days (§2.16 SH13-03) | TS-RISK |

---

## 5. Ambiguities and inconsistencies in the security design

An **Open** item blocks the final golden value of the listed tests; those tests assert the brief/schema behaviour where one exists, and are marked `xfail(strict=True, reason=AMB-nn)` where none exists. A **Resolved** item has its expected values written into §4 / §2.16 and its xfail markers removed.

Status (v0.2): AMB-01..21 **Resolved** by RE / UNB / TM v0.3 (consistency pass CPR-TST-01..17); AMB-22..24 found while re-verifying against RE v0.3 and **Resolved** by RE v0.4 (final cleanup).

| ID | Issue | Where | Affects | Proposed resolution (for the Security Specialist) | Status |
|---|---|---|---|---|---|
| AMB-01 | "Owner-verified" (×0.25 multiplier, L3 "unverified device" gate) is not distinguished from "trusted after new-device OTP". Because every new device must pass OTP before trust (brief §1), every trusted device may count as owner-verified, which would make the RE §5.1 sharer timeline unreachable and RE-#13 impossible | RE §2 case 4, §4.2 SH-01, §5.3, §6.1 L2 | SCN-01, 05, 09 | Define owner verification precisely (e.g. OTP to the **registered phone** or passkey/TOTP within 30 days, distinct from email OTP) and whether a new-device OTP counts | **Resolved** — RE §4.2.1 (owner-verified = SMS OTP to the registered mobile, passkey or TOTP within 30 days; email OTP = trusted only; SH-01 weight by separation class), §5.1 examples A–C; CPR-TST-01. Tests: SCN-01, 05; §2.16 SEP-* |
| AMB-02 | TO-04 response conflict: §6.2 lists TO-04 as a T-protect trigger (revoke **all** sessions, `must_change`), while §11 #18 says revoke only the token and step up at next login | RE §6.2 vs §11 | SCN-19 | Choose one; schema allows `device_mismatch` either way | **Resolved** — RE §4.3, §6.2, §8: only the replayed session is revoked (+60 → T-step-up); all sessions only on HC-T3; CPR-TST-02. Tests: SCN-19 steps 6, 6b, 6c |
| AMB-03 | The owner's scenario 9 assumes "a configured high-confidence rule" restricts automatically. The design has no single-rule L3; only a gated score (sharing) or single-rule protective locks (takeover) | RE §5.3, §6 | SCN-09 | Confirm with the product owner that "high-confidence rule" = gated L3 + T-protect; or add a policy-controlled single-rule path with the same shadow/dual-approval guard | **Resolved** (no PO decision needed) — RE §5.6 HC-01/HC-02 (auto-L3, shadow-first, master switch, circuit breaker) and HC-T1..T3; CPR-TST-03. Tests: SCN-09 (c), (e)–(i) |
| AMB-04 | Several detections are mentioned without a rule key, threshold or family: unknown session IDs "counted" (§7.2 step 2); cross-tenant 404s "logged as a security signal" (RPM TI-02); restricted-route probing; `analytics.plausibility_violation` as an adult "risk input" (no SH rule consumes it); new network + UA change on the same session (TM A2); restricted account's device opening a new account; cross-org login on a lab device. `security_signals.family = 'abuse'` exists but has no registry | RE, RPM, TM, AN, UNB §8 | SCN-04, 06, 13, 17, 18, 19 | Publish an `abuse.*` / `integrity.*` rule-key registry with thresholds, whether they score, and alert routing | **Resolved** — RE §4.5 registry AB-01..AB-12, IN-01..IN-03; TO-08 for UA drift; CPR-TST-04. Tests: SCN-04, 06, 13, 14, 17, 18, 19; §2.16 ABR-* |
| AMB-05 | Idle extension: brief says only engaged activity extends the idle timer, but RE §7.2 step 8 and ARCH §6.3 `touch()` slide it on every authenticated request (including keepalive ingest). No mechanism is specified to classify a request as engaged | Brief §1 vs RE §7.2, ARCH §6.3 | SCN-15 | Route tag `extends_idle` + payload check for ingest (engaged samples only) | **Resolved** — RE §1.4 `x-td-idle` (`extends` / `engaged_only` via `touch_engaged` / `neutral`); CPR-TST-05. Tests: SCN-15; §2.7.3 |
| AMB-06 | Remember-device "refresh up to 30 days" is unspecified: if an idle 401 triggers a silent re-issue on a trusted device, an idle tab survives for 30 days | Brief §1, RE §3.2 | SCN-15 | Refresh only on an explicit user navigation, never from background requests | **Resolved** — RE §1.4 rule 5: re-issue only on a top-level navigation with a valid rotated remember token, `remember_until` fixed; CPR-TST-05. Tests: SCN-15 variant R |
| AMB-07 | A long timed attempt with no input beyond the idle timeout (e.g. reading a long passage, or a staff-tier proctor) would expire the session mid-attempt; no rule treats an in-progress attempt as engaged | Brief §1, ARCH §8.4 | SCN-15, 16 | Attempt runner heartbeat counts as engaged while an attempt is in progress | **Resolved** — RE §1.4 rule 4 `idle_hold_until`; `409 session_too_short_for_attempt`; CPR-TST-05. Tests: SCN-15 variants A, S |
| AMB-08 | Crash recovery on the **same device**: if the session cookie is lost (cookie persistence/Max-Age for `__Host-td_session` is unspecified), the re-login creates a new session and the student must "rebind", consuming 1 of 2 rebinds and needing OTP at ≥ L2. Also, `evict_oldest` for non-interactive clients conflicts with AC-SES-02 when the oldest session holds the attempt | RE §6.3, §3.2; PRD AC-SES-02 | SCN-16 | Same `device_id` re-login rebinds automatically without consuming quota; exclude attempt-bound sessions from evict-oldest | **Resolved** — RE §1.4 rule 6, §6.3, §7.4: same-device re-attach without rebind or OTP; attempt-holding sessions never evicted; CPR-TST-06. Tests: SCN-16 (A), (B), (E), (F); R-2 |
| AMB-09 | Session lookup on Redis miss: RE §7.2 "miss ⇒ 401 (strict mode)" vs ARCH §6.3 "Redis → Postgres". The cluster holding sessions is not named; the `cache` cluster allows eviction | RE §7.2, ARCH §6.3, brief §1 | SCN-19, TS-DR | Sessions in `queue` (noeviction) or DB fallback; specify failover behaviour | **Resolved** — RE §1.6: Postgres source of truth, Redis read-through, unknown in both → 401; CPR-TST-07. Tests: SCN-19 step 7; TS-DR |
| AMB-10 | Webhook "timestamp older than 5 min → reject" (AC-COM-02, TM §4.2) vs provider retries that legitimately arrive hours later; Razorpay's signature carries no timestamp header (needs verification). `payment_webhook_events.is_stale` suggests stale events are processed, not rejected | PRD AC-COM-02, TM §2.4, SCHEMA | SCN-14 | Dedupe on `event_id`; process stale events through the monotonic state machine; reject only when a signed timestamp exists and is outside tolerance | **Resolved** — TM §2.4, ADR-0006 v0.3: no age-based rejection; dedupe + server re-fetch; CPR-TST-08, IPR-QA-06. Tests: SCN-14; §2.9 |
| AMB-11 | Ingest limits differ: TM says 1 heartbeat per tab per 15 s, max 4 `tab_id`s per session, 120 events/min per session; AN says ≥ 10 s apart per page instance, > 6 active page instances flagged, 30 requests/min sustained, 60/min per user | TM §2.7, §4.1 vs AN §5.2 | SCN-02, 17 | One table of values in the API spec | **Resolved** — `analytics-event-schema.md` §5.2 is the single source; TM states no values; CPR-TST-17. Tests: SCN-02, 17 |
| AMB-12 | Minors and `risk_evaluations`: AC-SEC-04 says no rows ever; RE §4.4 allows deterministic takeover rules for minors; F-PRD-7 restricts the PRD wording to sharing. Whether a minor's TO-04 writes a `family = 'takeover'` evaluation row is undefined, and no DB CHECK enforces either reading | PRD AC-SEC-04, RE §4.4, SCHEMA | SCN-19, TS-PRIV | State: no evaluation rows of any family for minors; deterministic actions logged as `security_signals` (`takeover`, no score) | **Resolved** — RE §4.4: no `risk_evaluations` of any family for minors (`ck_re_no_minor`); deterministic actions as `security_signals`; CPR-TST-09. Tests: SCN-19 minor; TS-PRIV |
| AMB-13 | `case_decisions` is append-only with `ck_cd_needs` requiring `approved_by` at insert, so a pending high-risk lift (state `escalated`) cannot be stored as a decision row before approval | SCHEMA, UNB §5 | SCN-11, 20 | Store the proposal in `approval_requests` and insert the decision only on approval, or relax the CHECK | **Resolved** — UNB §5.1: proposals in `approval_requests` (`security.case.decision`), `case_decisions` only on approval; CPR-TST-10. Tests: SCN-11; §2.16 AR-* |
| AMB-14 | False-positive compensation scope: AC-ENT-04 moves **every** active time-bound entitlement's `ends_at`; UNB §6 step 8 extends the **subscription**. Behaviour for L4 days, college-contract entitlements and the `uphold` → later-FP path is not stated | PRD AC-ENT-04, UNB §6 | SCN-20 | Pick one rule; include contract entitlements or not | **Resolved** (PO-10 to confirm) — UNB §6 step 8: ceil(restricted days incl. L4) to every time-bound entitlement; contract seats capped, remainder in `conditions.uncredited_days`; CPR-TST-11. Tests: SCN-20 |
| AMB-15 | Restricted-route vocabulary: brief uses route tag `account_status`; ARCH §6.3 uses `restriction_class ∈ {appeal, self_service_minimal}` and limits it to the `security`, `identity`, `support` modules (but billing view/cancel is in `commerce` and privacy requests in `admin`); RPM §1.4 L3 allowlist adds "data export, certificate list" and still says L4 → 403 (F-RPM-1 pending) | Brief §5, ARCH §6.3, RPM §1 | SCN-13, G-05 | Adopt the brief tag set; list allowed modules explicitly | **Resolved** — RE §7.2 canonical tags (`account_status` incl. DSAR export; `l3_readonly` incl. certificate list); CPR-TST-12. Tests: SCN-13; G-05 |
| AMB-16 | Meaning of `rejected` for an L3 that auto-expires anyway: does rejection prevent the auto-lift at `ends_at`? | UNB §4.2, §6 | SCN-12 | Clarify: rejection only refuses an *early* lift; auto-expiry still applies | **Resolved** — UNB §4.3: rejection refuses an early lift only; request closes `moot` at auto-expiry; CPR-TST-13. Tests: SCN-12 |
| AMB-17 | No takeover-family "impossible travel" rule; SH-10 is sharing-only, so it does nothing for minors or for takeover protection | RE §4.2–4.3 | SCN-07 | Confirm intent (India geo-IP unreliability) and document | **Resolved** — RE §4.3: no takeover impossible-travel rule by design; TO-09 for first login outside India; CPR-TST-14. Tests: SCN-07 |
| AMB-18 | An owner who forwards OTPs to a sharer makes the sharer's device "owner-verified" (×0.25), so detection depends on SH-02/D-signals. Accepted as residual risk R1, but no test expectation was written | TM §7 R1 | SCN-05 | Record the expected under-detection as an accepted test outcome | **Resolved** — RE §4.2.1, row 5c: S3 and SH-13 catch fixed-line relays; mobile-only sharer is an accepted under-detection; CPR-TST-15. Tests: SCN-05 5a/5c; §2.16 UD-01 |
| AMB-19 | CAPTCHA after the 2nd unblock request per day may conflict with WCAG 2.2 3.3.8 (accessible authentication) unless a non-cognitive alternative exists | UNB §8, NFR-ACC-01 | SCN-10, TS-A11Y | Use a non-puzzle challenge or rate limit only | **Resolved** — UNB §3: no CAPTCHA; rate limits only; CPR-TST-16. Tests: SCN-10; TS-A11Y |
| AMB-20 | Session `scope` is said to be set per session (brief §1) and at login (RE §7.1), but an L3 that lands mid-session must change the current session's scope; whether scope is stored and updated or derived per request from `restr:{uid}` is not stated | Brief §1, RE §7.1–7.2 | SCN-09, 13 | Derive per request; store only for audit | **Resolved** — RE §1.2, §7.2: scope derived per request; `auth_sessions.scope` is a record only; CPR-TST-12. Tests: SCN-09, 13 |
| AMB-21 | L3 deferral during an in-progress attempt (max 3 h): it is not stated whether the *other* sessions (the suspected sharer) are revoked immediately or also deferred | RE §7.4 | SCN-09 | Revoke non-attempt sessions immediately; defer only the attempt session | **Resolved** — RE §7.4: other sessions revoked immediately; the attempt session keeps only that attempt's routes until submit or `deferred_until`; CPR-TST-12. Tests: SCN-09 (b) |
| AMB-22 | Owner-verification expiry vs steady state: RE §5.1 example A says one person with laptop + phone stays at ≈ 15 → L0 "forever", but `risk.owner_verification.max_age_days = 30` (§3.2, §4.2.1) makes both devices non-owner-verified 30 days after their last SMS/passkey/TOTP verification, so S2 overlaps move to × 0.3 (steady ≈ 45 → L2 prompt roughly monthly) unless some routine login re-verifies them | RE §3.2, §4.2.1, §5.1 example A | SCN-01 variant 1-B (day > 30), R-1 | State whether ordinary logins with SMS OTP/passkey refresh `owner_verified_at`, or whether a monthly L2 prompt is intended; update example A | **Resolved** (RE v0.4 §3.2, §4.2.1, §5.1): any SMS-OTP/passkey/TOTP challenge on the device refreshes `owner_verified_at`; password-only users get a "Keep this device verified" prompt within `risk.owner_verification.refresh_prompt_days` (5) of expiry; a lapsed device scores × 0.3 only while lapsed. Example A restated. `xfail` removed |
| AMB-23 | Scope of `risk.mode`: §3.2 says `shadow` "records evaluations without actions" and is the launch default, while §5.6/§5.7 say HC-T1..T3 are active from launch and takeover rules are not covered by the kill switch. Whether `risk.mode = shadow` also suppresses takeover actions (T-step-up, T-protect, replay revoke) is not stated explicitly | RE §3.2, §5.6, §5.7 | SCN-09 (c), SCN-19, KS-07 | State that `risk.mode` governs the sharing family only (takeover and deterministic caps always enforce) | **Resolved** (RE v0.4 §3.2, §5.7): `risk.mode` (`shadow`/`off`) and the kill switch cover sharing enforcement only; takeover protections, deterministic caps and AB-*/IN-* always enforce. Tests unchanged (KS-07 extended to `off`) |
| AMB-24 | HC circuit-breaker edge cases: (a) behaviour when fewer than `min_decisions` HC-applied restrictions have been decided (e.g. 2 FP of 3 in the first pilot weeks); (b) whether the restriction that exceeds `max_daily_restrictions` (the 51st) is itself applied | RE §3.2, §5.7 | §2.16 CB-03, CB-06 | (a) evaluate over all decided when fewer than `min_decisions`, or only once `min_decisions` is reached; (b) trip before applying the excess restriction | **Resolved** (RE v0.4 §5.7 edge cases): (a) FP test from the first decision with the absolute threshold `max_fp_rate × min_decisions` (2nd FP trips); (b) checked before applying, the 51st is not applied. CB-03, CB-06 updated, `xfail` removed |

---

## 6. Acceptance criteria per implementation stage

Stages follow the canonical 12-stage order in `implementation-roadmap.md` §2 (brief v0.3 §7). The "Former QA stage" column shows where each criterion sat in v0.1 of this document; the substance is unchanged. Every stage exit also needs the Definition of Done (§8) for the features delivered in that stage.

| # | Stage (roadmap §2) | Former QA stage | Exit (acceptance) criteria |
|---|---|---|---|
| 1 | Discovery | 1 | Research basis recorded with [Verified]/[Reported]/[Rec]; the owner's verbatim lists captured (`source-requirements-excerpt.md`); open legal questions logged |
| 2 | Product design | 2 + 3 | Every FR has an ID, priority and at least one testable acceptance criterion; the 20 Phase-8 scenarios mapped (§4.1); NFRs measurable; PO decisions PO-01..13 recorded with defaults. Brief/contract reconciliation complete; ADRs accepted; every ambiguity in §5 has an owner and a decision date; API spec frozen for v1 routes with permission + scope + route tag + idle effect per route |
| 3 | Technical foundation | 4 + 5 | Monorepo, CI pipeline with G-01..G-22 wired (initially with empty suites where code does not exist yet, failing on missing suites); Testcontainers harness; seed tooling with the production guard (§9); IaC baseline passes Checkov/tfsec. All 121 tables migrated from empty; TS-RLS green for every tenant table; ownership manifest complete; partitions and retention registry rows exist; downgrade/upgrade round-trip passes |
| 4 | Identity & permissions | 6 | TS-SESS, TS-AUTHZ (all routes existing so far, generated from `permissions.yaml`), AC-IDN-01/02, AC-SES-01..03, AC-ORG-01/02 pass; `require_active_principal` route check green; MFA for staff; minors default; HMAC key versioning (§2.16 HK-*) |
| 5 | Core LMS | 8 | Entitlement gating on every content route; playback cap and DRM token flow (SCN-02, 05 conflict cases); progress keyed by `lesson_key` survives republish; AC-LRN-01; no completion on time alone (BR-EVD-01) |
| 6 | Placement prep (incl. timed MCQ assessments) | 9 (MCQ/assessment part) | AC-ASM-01..06; SCN-16 all variants; autosave interval ≤ 10 s with 5 s debounce; P1 at target in the perf environment |
| 7 | Account security & monitoring | 7 | All SCN fixtures that exercise the engine (SCN-01..09, 19, 20) and R-1..R-9 green in shadow and enforce modes; §2.16 KS-, CB-, BL-, AR-, SEP-, SH13-, UD-, ABR-, RPT- cases green; Open AMB items affecting them closed or explicitly xfail-accepted by the Security Specialist; TS-UNB full transition coverage; AC-SEC-01..04 pass; Section H views H1–H12 + ENG access-controlled and audited; exports need step-up + second approval |
| 8 | Commerce & college management | 10 + college parts of 11 | AC-COM-01..05, AC-ENT-01..04; SCN-14; TS-PAY live test mode nightly green 7 consecutive days; reconciliation job verified; GST invoice numbering gap-free; coordinator reports with k-floors enforced; coordinator security view is the aggregate status tile only |
| 9 | Coding assessments | 9 (coding part) | AC-COD-01/02; TS-JUDGE phase-1 set; P5 at target in the perf environment |
| 10 | Integration & hardening | 11 remainder + hardening part of 12 | AN §3.13 golden examples; AN §8 data-quality tests; SCN-15, 17; TS-PRIV complete incl. retention jobs (RET-*) and erasure; support cannot lift L3/L4 (AC-SEC-02). Zero open critical/high findings (NFR-SEC-02); external pen test with retest; ASVS L2 checklist evidenced (L3 on privileged consoles); TS-PERF all P-scenarios pass; TS-A11Y manual audit pass; TS-DR restore drill within the last 30 days; incident tabletop done |
| 11 | Pilot | UAT part of 12 | UAT sign-off by product owner and one pilot college; QA independent verification report; HC-01/HC-02 shadow report (≥ 14 days, blind reviewer sample, estimated FP ≤ 5 %) produced before any dual-approved switch to enforce (RE §5.6) |
| 12 | Production | release part of 12 | Production smoke and synthetic monitoring (synthetic accounts only, `is_synthetic = true`) green for 72 h before announcing; G-20 release gate passed |

---

## 7. Acceptance criteria per major module

PRD AC-* IDs are reused verbatim; additions are QA's. All Planned.

| Module | Acceptance criteria (must all pass) | Primary suites |
|---|---|---|
| `identity` | AC-IDN-01, AC-IDN-02; NIST password policy; Argon2id parameters; back-off + hard disable at 50 (`login.hard_disable_after_failures`); MFA mandatory for staff/privileged with passkey or TOTP only; step-up windows 5/10/15 min enforced server-side; contact changes blocked in restricted/status-only scope; unverified age ⇒ minor; consent purposes stored per brief list | TS-UNIT, TS-INT, TS-SESS, TS-SEC |
| `sessions` | AC-SES-01..03; timeouts per tier and lab device; revoke one/all; device cookie HMAC only; `scope` behaviour; playback heartbeats and 410 on revoke; attempt binding, same-device re-attach and rebind rules; `x-td-idle` effects; `pending_session_choice`; R-1..R-4 | TS-SESS, TS-RISK, TS-E2E |
| `security` | SCN-01..13, 19, 20; R-5..R-9; §2.16 (kill switch, circuit breaker, bulk lift, HMAC keys, `approval_requests`, separation classes, SH-13, under-detection, AB-/IN- registry, Section H); AC-SEC-01..04; engine never sets L4; rule versions need shadow ≥ 14 days + dual approval; HC rules shadow-first behind `risk.hc.auto_restrict_enabled`; network cap; minors produce no sharing data and no evaluation rows; reviewer guard rails; reason codes on per-user views; IP reveal audited; FP alerting | TS-RISK, TS-UNB, TS-AUTHZ, TS-PRIV |
| `orgs` | AC-ORG-01, AC-ORG-02; invitations with no existence disclosure; bulk import idempotent; lab enrolment and trusted-network proposal/verification flow | TS-INT, TS-AUTHZ, TS-RLS |
| `rbac` | Allow-only; scope containment (RPM §1.2); SoD-01..11; Dual actions via `approval_requests` (72 h expiry, approver ≠ requester); grant change forces re-login | TS-AUTHZ |
| `catalog` / `media` | Versioned courses; org-private content isolation; signed URL TTLs; VdoCipher OTP 300 s with server-specified watermark; 30 tokens/h; entitlement check before OTP | TS-INT, TS-AUTHZ, TS-E2E |
| `learning` | Progress by `lesson_key`; completion needs evidence (coverage ≥ 0.9 + quiz etc.); AC-LRN-01 certificate verify; certificate issuance blocked at ≥ L3 | TS-INT, TS-E2E |
| `placement` | Question versioning; pagination caps and scrape alerting (≤ 50 per request, 2,000/day); mastery model `mastery-1.0` unit tests; recommendations deterministic | TS-UNIT, TS-INT, TS-SEC |
| `assessments` | AC-ASM-01..06; server-authoritative deadline; autosave idempotent by `client_seq`, max interval 10 s (`max_interval_ms: 10000`), debounce 5 s (IPR-QA-04); writes after deadline + grace → 409 `attempt_closed`; settings lock `TEST_LOCKED`; audited overrides; SCN-16 | TS-INT, TS-E2E, TS-PERF P1 |
| `coding` | AC-COD-01/02; verdict recomputation; queue limits; hidden test encryption; TS-JUDGE | TS-JUDGE, TS-INT, TS-PERF P5 |
| `commerce` | AC-COM-01..05; SCN-14; webhook HMAC, dedupe, re-fetch (no age rejection), monotonic states; grace 5 days; goodwill refund needs `approval_request_id`; no card data stored; coupon limits; refunds by rule and Dual for goodwill/> ₹25,000 | TS-PAY, TS-AUTHZ |
| `entitlements` | AC-ENT-01..04; p95 ≤ 20 ms; gating not revocation by `security`; `entitlement_events` history; FP credit | TS-INT, TS-PERF P7 |
| `analytics` | AN §3.13 golden values; AN §8 1–6; invariants `M5 ≤ M2 ≤ M1`; per-event idempotency; minors purpose filter; security feed only for adults with consent; k-floors; `subject_key` exports | TS-TIME, TS-DQ, TS-PRIV |
| `notifications` | Every message in UNB §1 rendered from templates with variables; channel = verified only; SMS quotas; delivery-failure metrics (ENG: OTP delivery failure rate by provider) | TS-INT, TS-E2E |
| `audit` | Append-only enforced at DB level for all roles; hash chain verifies; hourly anchoring to Object Lock | TS-INT, TS-DR |
| `support` | Tickets scoped; support sees M0 + M2 only with ticket/reason; cannot lift L3/L4 (AC-SEC-02), cannot set passwords, +1 replacement grant with reason | TS-AUTHZ, TS-INT |
| `admin` (incl. privacy) | `policy_settings` bounds and 🔒 keys; changes take effect ≤ 60 s; dual approval for locked keys; feature flags audited; privacy requests, retention jobs, erasure ledger | TS-INT, TS-PRIV, TS-AUTHZ |
| Web (Next.js BFF) | Browser never holds bearer tokens; CSRF; Fetch Metadata; web vitals budgets; WCAG 2.2 AA | TS-E2E, TS-A11Y, TS-PERF P12 |

---

## 8. Definition of Done

A feature is **not done because a UI exists.** "Done" means all of the following, verified by someone other than the implementer:

1. **Backend enforcement.** Every rule is enforced in the API/service layer (and the database where the design says so: RLS, CHECKs, unique keys). The route declares permission + scope + restriction tag; `require_active_principal` applies; entitlement checks run where content is served. Hiding a button is never the control.
2. **Persistence and contracts.** Data is stored in the owning module's tables via Alembic migrations (single head, reversible or expand/contract-labelled); domain events go through the outbox; audit rows are written for sensitive actions; retention registry rows exist for new personal-data tables.
3. **Tests.** Unit tests for logic; integration tests against real Postgres with RLS; generated TS-AUTHZ cases exist for every new route; contract (OpenAPI) updated; E2E for the user journey; minors variant where personal data or security is involved; negative and abuse cases; coverage gates met (G-02).
4. **Non-functional.** Performance budget checked if on a hot path; axe clean; logs carry `request_id` and no PII; metrics and alerts added for new failure modes.
5. **Documentation.** API spec, the relevant blueprint doc and runbook updated; status vocabulary moved from Planned to Implemented/Tested (brief §7); student-facing copy reviewed.
6. **Security review.** Threat model delta noted; Semgrep/SCA/secret scans green; Security Specialist review for anything in `security`, `sessions`, `identity`, `commerce` webhooks, `coding` judge or RLS policies.
7. **QA independent verification.** QA executes the acceptance criteria on a fresh preview/staging environment built from the PR artefact and records evidence (test run IDs, screenshots where useful). A failed criterion reopens the item.
8. **Product acceptance.** Product Analyst accepts against the PRD AC; for security-sensitive UX, the Security Specialist accepts copy and flows.

Stage DoD = all features in the stage done + stage exit criteria (§6). Release DoD = §6 stage 12.

---

## 9. Test data and seed policy

1. **Synthetic only.** No production personal data is copied into any non-production environment. Production snapshots are restored only into the isolated DR account for drills and are destroyed after verification.
2. **Labelling.** Seed scripts live in `tools/seed/` and are named `seed_dev_*.py` / `seed_demo_*.py`. Every seeded user and organization carries `users.is_synthetic = true` / `organizations.is_synthetic = true` (schema v0.3; §13 I-06 resolved). In production only the synthetic-monitoring provisioning job may set the flag; TS-PRIV asserts that analytics aggregates, risk scoring, invoices and k-counts exclude synthetic rows (IPR-QA-03). display names end with "(Demo)", emails use `@example.test`, and every page served from a seeded environment shows a "Demo data" banner.
3. **Production guard.** Seed scripts refuse to run when `APP_ENV = production` or when the database contains any non-synthetic user (G-21). The production image does not contain seed modules.
4. **Determinism.** Faker (`en_IN`) with a fixed seed; UUIDv7 from the injected clock; the same command always yields the same dataset.
5. **Identifiers.** Phone numbers come from a non-dialable block reserved by the team and are routed only to the SMS stub; staging SMS sandbox sends only to an allowlist of team test numbers. IPs use documentation ranges (`192.0.2.0/24`, `198.51.100.0/24`, `203.0.113.0/24`, `2001:db8::/32`) and `100.64.0.0/10` for CGNAT simulations; ASNs use the private range 64512–65534 with a fake IP-intel table. Payment data uses Razorpay/Cashfree test cards and handles only.
6. **Personas (minimum set).**

| Persona | Purpose |
|---|---|
| Adult D2C student with `security_monitoring` consent, 2 trusted devices (one SMS-OTP owner-verified, one email-OTP only) | Baseline for SCN-01, 02, 04, 05 |
| Owner + sharer pair on two fixed-line ISPs in two states (relayed OTP); same pair with the sharer on mobile data only | SCN-05 5a/5c, SCN-09 (e), UD-01 |
| Adult student who withdrew `security_monitoring` | Deterministic-only mode |
| 17-year-old with verified guardian consent | Minors rules (R-6, SCN-09 (h), TS-PRIV) |
| Student with no DOB (unverified age) | Default-minor treatment |
| Student turning 18 tomorrow | Age-tier transition |
| College students of org-A (registered trusted network + 2 lab PCs) and org-B (unregistered), 40 each, behind one NAT IP per college | SCN-03, 06, 18; P3 |
| Jio/Airtel CGNAT mobile user; corporate VPN user; Tor user | SCN-04, 07, 08 |
| Family PC shared by 6 accounts; reseller cluster (hosting ASN, 8 accounts, churned devices) | SCN-06 |
| L3-restricted user with an open case; L4 high-risk repeat user; takeover victim; user with an FP-overturned case | SCN-09..13, 20 |
| Staff: coordinator A and B, trainer A1, content manager, mentor, support, two security reviewers, two finance admins, two super admins (one break-glass) | TS-AUTHZ, dual control |
| Commerce: active subscription, subscription in grace, refunded order, college contract with seats | TS-PAY, AC-ENT-* |

7. **Volume data** for TS-PERF is generated by a separate script at year-1 scale (100k users, 50 colleges, 50M raw events/month) and is never loaded outside the perf environment.
8. **Fixture hygiene.** Recorded third-party payloads are scrubbed of personal data before commit; G-14 secret scanning covers fixtures.

---

## 10. CI gates

| Gate | Check | Blocks |
|---|---|---|
| G-01 | Lint and types: ruff, mypy (strict for `core`, `security`, `sessions`, `entitlements`, `commerce`), eslint, `tsc --noEmit` | PR |
| G-02 | Coverage: backend line ≥ 85 % and branch ≥ 80 % overall; **branch ≥ 95 %** for `core/authz`, `security`, `sessions`, `entitlements`, `commerce/webhooks`, `assessments` timer/autosave, `analytics` crediting; diff coverage ≥ 90 %; frontend line ≥ 75 %; no module drops > 0.5 % | PR |
| G-03 | Required suites green: TS-UNIT, TS-INT, TS-AUTHZ, TS-RLS, TS-SESS, TS-RISK, TS-UNB, TS-TIME (golden), TS-CON smoke, TS-PAY replay, TS-E2E smoke, axe | PR |
| G-04 | Migration check: single Alembic head; `upgrade head` from empty; `downgrade -1`/`upgrade` round-trip; upgrade from the last release's schema with seed data; destructive operations only with an expand/contract label; every tenant table has RLS ENABLE + FORCE + policy; `td_app` is not owner and has no BYPASSRLS; ownership manifest lists every table exactly once; partition pre-creation present; retention registry row for each personal-data table | PR with migrations |
| G-05 | **Route guard check**: enumerate all routers; every authenticated route has `require_active_principal`, a permission + scope declaration and a restriction tag mapping; only allowlisted routes carry the `account_status` tag (list reviewed by CODEOWNERS = Security Specialist); public (unauthenticated) routes match an explicit allowlist; admin routers under their own prefix | PR |
| G-06 | OpenAPI: `oasdiff` breaking-change check; generated TS client has no diff; `/docs` disabled in prod profile | PR |
| G-07 | Module boundaries: import-linter contracts; one writer per table | PR |
| G-08 | API inventory equals router registry; no undeclared versions | PR |
| G-09 | SAST: Semgrep (Python, TS + custom rules: missing `require_active_principal`, `==` on secrets, raw SQL without tenant scope, `extra="allow"`, user-controlled outbound URL, `dangerouslySetInnerHTML`); block on high | PR |
| G-10 | Dependency/SCA: pip-audit, OSV-Scanner/npm audit; block critical/high with a fix available; licence allowlist; CycloneDX SBOM on release | PR + daily |
| G-11 | Container image scan (Trivy): block critical; base images pinned by digest | PR + daily |
| G-12 | IaC: Checkov/tfsec; block high | PR |
| G-13 | Secret scanning: gitleaks pre-commit + CI; block any finding (allowlist only for documented test keys) | Every commit |
| G-14 | Fixture/PII scan: recorded payloads and seed files contain no real PII patterns | PR |
| G-15 | Log hygiene: test-run logs scanned for tokens, passwords, OTPs, raw IP in risk evidence | PR |
| G-16 | Web budgets: test-runner JS ≤ 200 KB gz; Lighthouse CI budgets | PR touching `apps/web` |
| G-17 | Golden-file guard: changes to risk or time goldens require CODEOWNERS approval (Security Specialist / Analytics Engineer) | PR |
| G-18 | Nightly: TS-E2E full, TS-CON full fuzz, TS-SEC rate-limit set, TS-PAY live test mode, TS-DQ, k6 smoke | Next-day merge freeze if red > 24 h |
| G-19 | Weekly: DAST (ZAP baseline + authenticated per role), TS-JUDGE corpus, testssl | Release |
| G-20 | Pre-release: TS-PERF full, manual a11y audit, ASVS checklist, pen-test findings closed, restore drill ≤ 30 days old, zero open critical/high, QA independent verification report | Release |
| G-21 | Production-safety: seed scripts and test hooks absent from the production image; seed guard test passes | PR + release |
| G-22 | Policy defaults: `policy_settings` defaults in code equal the documented defaults (RE §3.2, brief §1); 🔒 keys locked | PR |

---

## 11. Traceability matrix (FR area → test suites)

| FR / NFR area (PRD) | Unit | Int | Contract | AuthZ | RLS | Session | Risk | Unblock | Judge | Pay | Time/DQ | E2E | Perf | A11y | DR | Privacy | Phase-8 SCN |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| FR-IDN (identity) | ✓ | ✓ | ✓ | ✓ | | ✓ | | | | | | ✓ | P3 | ✓ | | ✓ | 19 |
| FR-SES (sessions/devices) | ✓ | ✓ | ✓ | ✓ | | ✓ | ✓ | | | | | ✓ | P8 | | ✓ | | 1, 2, 4, 5, 15, 16, 19 |
| FR-SEC (security/unblock) | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | | | | ✓ | | ✓ | | ✓ | 3, 5–13, 20 |
| FR-ORG (orgs/batches) | ✓ | ✓ | ✓ | ✓ | ✓ | | | | | | | ✓ | | ✓ | | ✓ | 3, 6, 18 |
| FR-RBAC | ✓ | ✓ | | ✓ | ✓ | | | | | | | | | | | | 18 |
| FR-CAT, FR-MED (catalog/media) | ✓ | ✓ | ✓ | ✓ | ✓ | | | | | | | ✓ | P8 | ✓ | | | 2, 13 |
| FR-LRN (learning) | ✓ | ✓ | ✓ | ✓ | ✓ | | | | | | ✓ | ✓ | | ✓ | | | 13, 17 |
| FR-PLC (placement) | ✓ | ✓ | ✓ | ✓ | ✓ | | | | | | | ✓ | | ✓ | | | — |
| FR-ASM (assessments) | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | | | | ✓ | ✓ | P1 | ✓ | ✓ | | 16, 17 |
| FR-COD (coding) | ✓ | ✓ | ✓ | ✓ | ✓ | | | | ✓ | | | ✓ | P5 | ✓ | | | 13 |
| FR-COM (commerce) | ✓ | ✓ | ✓ | ✓ | ✓ | | | | | ✓ | | ✓ | P6 | ✓ | ✓ | | 14 |
| FR-ENT (entitlements) | ✓ | ✓ | ✓ | ✓ | ✓ | | | ✓ | | ✓ | | ✓ | P7 | | | | 13, 14, 20 |
| FR-ANL (analytics/time) | ✓ | ✓ | ✓ | ✓ | ✓ | | | | | | ✓ | ✓ | P4 | | | ✓ | 2, 15, 17 |
| FR-NTF (notifications) | ✓ | ✓ | | | | | | ✓ | | | | ✓ | | ✓ | | ✓ | 9–12 |
| FR-SUP (support) | ✓ | ✓ | ✓ | ✓ | ✓ | | | ✓ | | | | ✓ | | ✓ | | | 11, 18 |
| FR-PRV (privacy) | ✓ | ✓ | ✓ | ✓ | ✓ | | ✓ | | | | ✓ | ✓ | | ✓ | ✓ | ✓ | R-6 |
| FR-ADM (admin/policy) | ✓ | ✓ | ✓ | ✓ | | | ✓ | | | | | ✓ | | ✓ | | | 9 |
| NFR-PERF / SCL / AVL | | | | | | | | | | | | | ✓ | | ✓ | | 3, 16 |
| NFR-SEC (incl. tenant isolation) | | ✓ | ✓ | ✓ | ✓ | ✓ | | | ✓ | ✓ | | | | | | | 13, 18, 19 |
| NFR-ACC | | | | | | | | | | | | ✓ | | ✓ | | | 10 |
| NFR-PRV | | ✓ | | | | | | | | | ✓ | | | | ✓ | ✓ | — |
| NFR-OBS / MNT | ✓ | ✓ | | | | | | | | | | | ✓ | | | ✓ | 14 |

Row-level traceability (each FR-* ID → test case IDs) is generated from test markers (`@pytest.mark.fr("FR-SES-011")`, Playwright tags) into a report published per build; an FR with no linked test fails the stage-exit review (§6), not the PR.

---

## 12. Defect handling and reporting

- Severity: **S1** security/tenant-isolation/payment-integrity/data-loss; **S2** feature broken with no workaround; **S3** workaround exists; **S4** cosmetic. S1 blocks release unconditionally; S2 blocks unless the product owner signs an exception with a fix date.
- Every escaped S1/S2 defect adds a regression test at the lowest level that would have caught it.
- Flaky tests are quarantined for ≤ 7 days with an owner; quarantined security suites still block release.
- QA publishes per release: suite pass rates, coverage, open defects by severity, Phase-8 scenario status (20/20 required), AMB status, performance results vs NFRs, a11y audit summary, DR drill date.

---

## 13. Issues for Integration Lead

"Needed by" uses the roadmap stage numbers (§6).

| # | Issue | Owner suggested | Needed by | Status (v0.2) |
|---|---|---|---|---|
| I-01 | No document defined the 12-stage implementation order | Integration Lead / TPM | Roadmap | **Resolved** (contract-reconciliation §7) — `implementation-roadmap.md` §2; §6 re-keyed (IPR-QA-01) |
| I-02 | RE §11 used its own numbering, giving two "scenario 13"s | Security Specialist | Next security doc pass | **Resolved** — RE v0.3 §11 uses the owner numbering and R-1..R-9; §4.1/§4.22 re-keyed (CPR-TST-18) |
| I-03 | 21 ambiguities in §5 (AMB-01..21) blocked final golden values | Security Specialist; Backend Lead; Product owner | Before Stage 7 exit | **Resolved** — all 21 resolved by RE/UNB/TM v0.3 (CPR-TST-21). Follow-up items AMB-22..24 (I-13) resolved by RE v0.4 |
| I-04 | TS-AUTHZ needs a machine-readable permission matrix and route registry | Product Analyst + Backend Lead | Stage 4 | **Resolved** (contract-reconciliation §7) — `apps/api/app/core/authz/permissions.yaml` generated from role matrix §2/§3/§5 (IPR-QA-02) |
| I-05 | `security_signals.family = 'abuse' / 'integrity'` had no rule-key registry | Security Specialist | Stage 7 | **Resolved** — RE §4.5 AB-01..12, IN-01..03 (CPR-TST-21) |
| I-06 | Schema had no synthetic-data marker | System Architect | Stage 3 | **Resolved** (contract-reconciliation §7) — `users.is_synthetic`, `organizations.is_synthetic` (schema v0.3; IPR-QA-03) |
| I-07 | Route names differed between documents; API spec missing | Backend Lead | API spec freeze (Stage 2) | **Resolved** (contract-reconciliation §7) — `api-specification.md`; route tags per RE §7.2 |
| I-08 | PRIV §7 `purge_raw_analytics` said 90 days for heartbeats | Security Specialist | Stage 10 | **Resolved** — PRIV §7 shows 35 days (CPR-TST-21) |
| I-09 | `attempt_events.event_type` CHECK lacked `session_takeover` / `device_switch` | System Architect / Product Analyst | Stage 6 | **Resolved** (contract-reconciliation §7); tests use the schema values incl. `reattach_same_device` |
| I-10 | Test infrastructure needs budget/accounts (payment, VdoCipher, Judge0, SMS sandbox, perf env, DR account, pen-test vendor) | DevOps / TPM | Stage 3 | **Resolved** (contract-reconciliation §7) |
| I-11 | AC-SES-02 conflicted with `evict_oldest` for non-interactive clients | Product Analyst + Security Specialist | Stage 4 | **Resolved** — RE §6.3: attempt-holding sessions never evicted; `409 session_cap_reached` (CPR-TST-06) |
| I-12 | RPM step-up window and L4 → 403 wording | Product Analyst | Stage 4 | **Resolved** (contract-reconciliation §7) — brief values (5/10/15 min; L4 → `status_only`) |
| I-13 | AMB-22 (owner-verification expiry vs example A), AMB-23 (`risk.mode` scope over takeover actions), AMB-24 (circuit-breaker edge cases) | Security Specialist | Stage 7 | **Resolved** (RE v0.4; §5 AMB-22..24) |
