# Audit — Authentication, Authorization & Security (area `security`, prefix `SEC-`)

Phase A (audit only). Auditor: security audit agent, 2026-11-03.
Scope: `apps/api/app/core/{auth,security,crypto,principal,routing,middleware,logging,startup_checks,db}.py`,
`app/modules/{identity,sessions,rbac,security,audit,admin(approvals/break-glass)}`, web BFF
(`apps/web/src/lib/bff/*`, `src/app/api/v1/[...path]/route.ts`, `src/middleware.ts`, `src/lib/security/csp.ts`,
`features/auth/lib/{validation,login-flow}.ts`), `infra/terraform/envs/prod/main.tf`, repo secrets.

Test database: `TD_TEST_DB_NAME=techdrona_audit_security` (reset once with `TD_TEST_RESET_DB=1`).
Probes: `apps/api/tests/_audit_scratch/security/` (`test_route_dump.py`, `test_sec_probes.py`,
`web/bff.audit.test.ts` + `web/vitest.audit.config.mjs`).

Baseline: the existing suites pass against the audit DB —
`pytest tests/identity tests/sessions tests/security tests/rbac tests/authz tests/core` → **253 passed** (11 min);
`pytest tests/audit` → **24 passed**; `vitest run src/lib/bff src/middleware.test.ts src/lib/security src/features/auth` → **58 passed**.

## Feature / coverage inventory

| Feature/Req ID | Requirement source | Code location | Audit method | Result |
|---|---|---|---|---|
| Route guard: every non-public route depends on `require_active_principal` | ADR-0002, api-spec §1.4 | `core/routing.py:110-185` | Route dump of all 451 routes + `find_route_guard_violations` (0 violations); 24 public routes reviewed | Verified OK |
| Permission per route | role-permission-matrix | `core/auth.py:175`, per-module checks | Route dump: 160+ mutating routes have no route-level `require_permission` and rely on in-handler `check_permission`/ownership; security/rbac/admin ones read and checked | Verified OK for security/rbac/admin/sessions/identity (other modules: owned by module auditors) |
| Signup (AUTH-01) | api-spec AUTH-01 | `identity/router.py:188-356` | Probe | Issue (SEC-02, SEC-05) |
| Email verification (AUTH-02/03) | api-spec | `identity/router.py:363-405` | Existing tests + probe | Verified OK (token 256-bit, hashed, single use); per-IP limit missing (SEC-02) |
| Login, back-off, hard-disable (AUTH-06) | api-spec AUTH-06, RE §7.1 | `identity/router.py:456-578`, `sessions/service.py` | Existing tests (backoff, hard-disable at 50, identical invalid_credentials for unknown/known) | Verified OK; per-IP window keyed on spoofable IP (SEC-01) |
| Password hashing | brief §1 | `core/security.py:291-321` | Code read | Verified OK (Argon2id m=19456 KiB, t=2, p=1, 16-byte salt, dummy hash for unknown users, rehash on login) |
| Token entropy / storage | ADR-0002 | `core/security.py:325-350` | Code read + DB scan probe | Verified OK (session/reset/link tokens 256-bit CSPRNG; only SHA-256 stored; OTP 6-digit `secrets.randbelow`) |
| Constant-time compares | — | `core/security.py:352`, `middleware.py:285`, `bff/csrf.ts:32` | Code read | Verified OK (service token, HMAC, CSRF use constant-time; OTP compares SHA-256 digests of row-bound code — not exploitable) |
| Password reset (AUTH-16/17) | api-spec, threat model "Reset link" | `identity/router.py:840-955` | Existing tests | Verified OK (single use, 30 min TTL, revokes all sessions, clears hard-lock, `no-referrer` page); per-IP limits missing (SEC-02) |
| Password change (AUTH-18) | api-spec AUTH-18 (5/h per user) | `identity/router.py:957-995` | Probe | Issue (SEC-03) |
| Device verification OTP (AUTH-12/13) | RE §7.1 | `identity/router.py:653-757` | Existing tests (5 attempts/OTP, send caps) | Verified OK; token not rotated on activation (SEC-08) |
| MFA / TOTP enrolment, recovery codes, factor removal | api-spec ME-07..10 | `identity/router.py:1520-1705`, `identity/totp.py` | Code read + existing tests | Verified OK (AES-GCM encrypted secret, ±1 step, replay guard, step-up for changes, staff cannot remove last factor, other sessions revoked) |
| MFA login verify (AUTH-11) | 5 failures/10 min | `identity/router.py:595-650` | Existing tests | Verified OK (token rotated after MFA) |
| Step-up (AUTH-19/20), windows P5/S10/U15 | api-spec §1.6 | `identity/router.py:999-1120`, inline `step_up_problem`/`require_fresh_step_up` | Probe + existing tests | Issue (SEC-09: students may use password) ; staff TOTP-only Verified OK |
| Staff MFA requirement | api-spec §1.4 step 8 | `sessions/resolver.py:207-213` | Existing test `test_staff_must_enrol_mfa_then_can_work` | Verified OK |
| Session expiry (idle/absolute per tier), revocation, logout, logout-everywhere | api-spec §1.2 | `sessions/resolver.py`, `sessions/router.py` | Existing tests (idle/absolute, staff/privileged timeouts, logout reuse rejected, revoke-others) | Verified OK |
| Stolen-cookie replay / UA drift | RE TO-04/TO-08 | `sessions/resolver.py:147-167` | Existing tests | Verified OK |
| Concurrent session cap 2 | policy `sessions.student.max_concurrent` | `sessions/login.py:215-263` | Existing test `test_session_cap_chooser_and_evicted_session_rejected` | Verified OK |
| Trusted device cap 3, swaps 2/30 d | policy `devices.student.*` | `sessions/login.py:88-154` | Existing test `test_device_cap_and_replacement_quota` | Verified OK |
| Stream cap 1 | policy `playback.max_concurrent_streams` | `media/service.py` | Existing media test (`-k concurren/stream/cap`) passes | Verified OK (detail owned by media auditor) |
| Remember device (AUTH-28) | api-spec §1.2, RE §1.4 | `identity/router.py` AUTH-28, `bff/proxy.ts:115` | Code search | Issue (SEC-07, not wired) |
| Account enumeration | api-spec AUTH-01/06/16 | — | Probes | Login/forgot OK; signup Issue (SEC-05) |
| Rate limits on public auth endpoints | api-spec AUTH table | — | Probe | Issue (SEC-02) |
| OTP relay (SH-13) | RE §4.2 | `security/signals.py`, `catalogue.py` | Existing scenario test `test_scn05a_relayed_otp_sharer_l1_l2_then_l3` | Verified OK |
| Risk scoring: thresholds 25/45/70/90, half-life 7 d, network cap 20, L3 gates | RE §5.1-5.3 | `security/rules.py` | Code read vs RE §5 + `test_rules_unit.py` (passes) | Verified OK |
| Never L4 automatically | RE §5.3 | `rules.py:next_level`, `engine.py:604,783`, `cases.py:474` | Code read + `test_scn09i_..._never_l4` | Verified OK (L4 only via human `convert_L4` with `security.restriction.apply_l3l4`) |
| Never restrict on shared IP alone | RE §5.2 | `rules.py` network cap (20 < L2 45) | `test_network_signals_alone_never_exceed_l1` | Verified OK |
| Explanations stored / human review | RE §5.4, UNB | `engine.py` evaluations, `cases.py:propose_decision` (explanation+timeline must be viewed) | Code read + scenario tests | Verified OK |
| Minors deterministic only | RE §4.4 | `engine.py:132-151, 562, 867, 973` | Code read + `test_scn09h_minor_with_hc_facts_gets_nothing` | Verified OK |
| Kill switch (only toward shadow/off, 24 h ratification) | role matrix §5, RE §5.7 | `security/controls.py:96-160` | Code read | Verified OK |
| Unblock workflow ownership (IDOR) | UNB | `security/api_student.py:214-421` | Code read (all lookups filtered by `principal.user_id`, 404 otherwise) | Verified OK |
| IDOR: sessions/devices | — | `sessions/router.py` | Probe (user B on A's session/device → 404/404/404, A unaffected) | Verified OK |
| RLS enforced for td_app | ADR / database-schema | migrations | Probe as td_app with tenant context of org A: org B, its users and others' sessions invisible; insert into org B blocked; existing `test_rls.py` lint | Verified OK (26 tables without RLS are catalogue/global or security-internal; see note) |
| Privilege escalation via role grant | role matrix §5, SoD-05/10 | `rbac/router.py:212-301`, `rbac/service.py:291-360` | Code read + `tests/rbac` | Verified OK (dual roles → approval; self-grant blocked at platform; grantee sessions rotated) |
| Second-person approval can't be self-approved | SoD-05/12 | `admin/approvals.py:140`, `rbac/router.py:351`, `security/cases.py:633,784` | Code read + `test_case_pending_approval.py` | Verified OK |
| Audit hash chain / tamper evidence | ADR (audit) | `modules/audit/chain.py`, `sealer.py` | `tests/audit` (24 pass) + probe: td_app UPDATE/DELETE/TRUNCATE on `audit_log`, UPDATE `audit_outbox` → all `ProgrammingError` | Verified OK |
| Logs/DB never hold passwords/OTPs/tokens | threat model, logging.py | `core/logging.py`, `notifications/adapters.py` | Probe: full flow (login, device OTP, step-up OTP, forgot/reset) with JSON logging captured + scan of audit_log/outbox/notifications/login_attempts/verification_tokens/auth_sessions | Verified OK (none found) |
| BFF CSRF double-submit + Fetch Metadata | ADR-0010, api-spec §1.3 | `bff/proxy.ts:132-180`, `bff/csrf.ts` | Existing proxy tests + probe (cross-site 403, missing header 403, token bound to other session 403, valid 200, form POST 415) | Verified OK |
| Cookie flags | api-spec §1.2 | `bff/cookies.ts`, `proxy.ts:246-270`, `sessions/service.py:535` | Code read | Verified OK (`__Host-`, Secure in prod, HttpOnly, SameSite=Lax; csrf SameSite=Strict non-HttpOnly) |
| CSP nonce | threat model "XSS" | `middleware.ts`, `csp.ts` | Code read + csp tests | Verified OK (nonce + strict-dynamic, no unsafe-inline scripts, frame-ancestors none); HSTS not set by the app (expected at edge) |
| Open redirect (`next`) | threat model | `features/auth/lib/validation.ts:53` | Vitest probe | Issue (SEC-04) |
| SSRF in BFF fetch | — | `proxy.ts:221` | Code read (fixed internal base URL, path traversal/encoded separators rejected, `redirect: manual`) | Verified OK |
| Client IP derivation | api-spec §1.2 | `bff/headers.ts:216` | Vitest probe | Issue (SEC-01) |
| Frontend-only permission checks | ADR-0002 | `middleware.ts` (UX gate only) | Code read | Verified OK (api enforces every route) |
| Secrets committed | — | repo | No commits exist; `.env`, `apps/web/.env.e2e.local` git-ignored; pattern scan (AWS/Razorpay/private keys/GitHub/Google) → only placeholders in `.env.example`/docs | Verified OK |
| Production startup refuses fakes/default keys | startup_checks | `core/startup_checks.py` | Probe | Issue (SEC-06) |
| Passkey/WebAuthn, break-glass passkey-only | api-spec AUTH-07/08, AUTH-20 | — | Code search | Not built (SEC-11) |

## Issues

### SEC-01: Client IP is taken from client-controlled `X-Forwarded-For` when `TD_TRUSTED_PROXY_HOPS=0` (the default, and the value production ends up with)
- Severity: High
- Status: Confirmed
- Component: `apps/web/src/lib/bff/headers.ts:216-237` (`resolveClientIp`), `apps/web/src/lib/bff/config.ts:67`; consumed by `apps/api/app/core/middleware.py:296` (`X-TD-Client-IP` trusted from the BFF); `infra/terraform/envs/prod/main.tf:24-38` (web service sets no `TD_TRUSTED_PROXY_HOPS`)
- Requirement: api-spec §1.2 / AUTH-06 per-IP 30/10 min login window; RE §4 network signals; README "left-most entries are client-controlled and never trusted"
- Repro: `vitest run --config apps/api/tests/_audit_scratch/security/web/vitest.audit.config.mjs` (test "client IP with TD_TRUSTED_PROXY_HOPS=0 …")
- Expected / Actual: with no trusted proxy the BFF should use the socket peer (or nothing), never a browser header. Actual: `resolveClientIp(XFF="6.6.6.6", hops=0)` returns `6.6.6.6`; with hops=0 the right-most XFF entry is used, which is entirely client-supplied when nothing appends to it. Behind CloudFront→ALB with the default 0, every user instead gets the CloudFront edge IP.
- Evidence: `AUDIT resolveClientIp(XFF=6.6.6.6, hops=0) -> 6.6.6.6`
- Root cause: `idx = chain.length - 1 - trustedProxyHops` treats the last XFF entry as trustworthy even when there is no trusted hop; prod env does not set the hop count.
- Impact: per-IP login throttle (`ss.ip_failures_exceeded`), the unknown-session-token throttle (`resolver.py:131`) and network-based risk signals/clusters can be bypassed or poisoned per request; in prod default, all users share edge IPs (mass throttling, meaningless SH-02/09/10 evidence).
- Recommended fix: when `trustedProxyHops === 0` ignore XFF and return null (or the runtime peer address); require `TD_TRUSTED_PROXY_HOPS`≥1 + `CloudFront-Viewer-Address` in prod; set it in terraform.
- Suggested owner paths: `apps/web/src/lib/bff/headers.ts`, `apps/web/src/lib/bff/proxy.test.ts`, `infra/terraform/envs/*/main.tf`

### SEC-02: Spec'd rate limits on public auth endpoints are not implemented (signup, verify-email, forgot, reset) — enables email bombing and spam signups
- Severity: High
- Status: Confirmed
- Component: `apps/api/app/modules/identity/router.py:188` (signup), `:363` (verify/email), `:899` (password/forgot), `:910` (password/reset)
- Requirement: api-spec AUTH table: AUTH-01 "5/h per IP+device; 3/day per contact", AUTH-02 "20/h per IP", AUTH-16 "5/h per IP; 3/h per identifier", AUTH-17 "10/h per IP"
- Repro: `pytest tests/_audit_scratch/security/test_sec_probes.py -k rate_limits -s`
- Expected / Actual: 429 after the limits. Actual: 7 signups from one IP all 201; 5 signups for an existing contact all 201 and 5 "You already have an account" emails sent to the owner; 7 forgot → 202; 12 reset → 400 (never 429); 22 verify-email → 400 (never 429).
- Evidence: `AUDIT 7 signups same IP -> [201, 201, 201, 201, 201, 201, 201]; 5 signups same existing contact -> [201, 201, 201, 201, 201] (emails sent to owner: 5)` / `AUDIT 7 forgot same IP -> [202]; 12 reset same IP -> [400]; 22 verify-email same IP -> [400]`
- Root cause: only per-user caps exist (forgot 3/h per user, resend 3/h, OTP send caps); no per-IP/per-contact limiter on these routes.
- Recommended fix: reuse the Redis limiter in `app/modules/commerce/ratelimit.py` (`limit(...)` dependency) or a DB window like `ss.ip_failures_exceeded`; key by client IP (after SEC-01) and by contact HMAC; cap "already registered" mails per contact/day.
- Suggested owner paths: `apps/api/app/modules/identity/router.py`, a shared limiter in `apps/api/app/core/`

### SEC-03: Password change accepts unlimited wrong current-password guesses (session holder can brute-force the password)
- Severity: Medium
- Status: Confirmed
- Component: `apps/api/app/modules/identity/router.py:957-970` (`POST /auth/password/change`)
- Requirement: api-spec AUTH-18 rate limit "5/h per user"
- Repro: `pytest ... -k password_change_no_attempt_limit -s`
- Expected / Actual: 429 after 5 failures/h (and failures recorded). Actual: 25 wrong guesses all `401 invalid_credentials`, no `login_attempts` row, no counter; the 26th (correct) succeeds with 200.
- Evidence: `AUDIT password/change 25 wrong guesses -> statuses [401]` / `AUDIT password/change correct after 25 wrong -> 200`
- Root cause: `check_password` failure returns immediately without counting.
- Recommended fix: record `mfa_failed`-style attempts (or a dedicated outcome) and refuse after 5/h; consider requiring step-up instead of current password.
- Suggested owner paths: `apps/api/app/modules/identity/router.py`

### SEC-04: Open redirect after login via tab-smuggled `next` (`/%09/evil.example`)
- Severity: Medium
- Status: Confirmed (validator + URL resolution in Node; Next 15.5.28 `router.push` treats a cross-origin URL as `mpaNavigation`, `navigate-reducer.js:44`)
- Component: `apps/web/src/features/auth/lib/validation.ts:53-59` (`safeNextPath`), used by `app/(public)/login/page.tsx:18`, `features/auth/lib/login-flow.ts:22-23`, `LoginForm.tsx:53`, `MfaForm.tsx:54`
- Requirement: security-threat-model (open redirect), safe `next` handling
- Repro: vitest probe "safeNextPath rejects tab-smuggled…"; manual: `/login?next=/%09/evil.example` then sign in.
- Expected / Actual: fallback `/app`. Actual: `safeNextPath("/\t/evil.example")` returns the value unchanged; the WHATWG URL parser strips the tab → `//evil.example` → `http://evil.example/`.
- Evidence: `AUDIT safeNextPath("/\t/evil.example") -> "/\t/evil.example" -> http://evil.example/`
- Root cause: only `\r\n` rejected; tabs/other C0 controls and backslash variants after the first char are not.
- Recommended fix: reject any control char/whitespace (`/[\u0000-\u001F\u007F\s\\]/`), then confirm `new URL(next, origin).origin === origin` and return the normalised pathname+search.
- Suggested owner paths: `apps/web/src/features/auth/lib/validation.ts` (+ its test)

### SEC-05: Signup reveals whether an email/mobile is already registered (body, cookies and timing)
- Severity: Medium
- Status: Confirmed
- Component: `apps/api/app/modules/identity/router.py:221-243` vs `:340-356` (signup handler starts at :188)
- Requirement: api-spec AUTH-01 / code comment "No enumeration: same 201 shape"
- Repro: `pytest ... -k signup_enumeration -s`
- Expected / Actual: indistinguishable responses. Actual: new → `next_steps=['verify_email']`, `session` object, `Set-Cookie` session+device, ~1.68 s (Argon2 hash); existing → `next_steps=['check_email']`, `session: null`, no cookies, ~0.02 s.
- Evidence: `AUDIT signup new: 201 next=['verify_email'] session=True cookies=['__Host-td_session', '__Host-td_device'] t=1.683s` / `AUDIT signup existing: 201 next=['check_email'] session=False cookies=[] t=0.023s`
- Root cause: the duplicate branch returns a different, cheaper body; the new-account branch logs the user in immediately.
- Recommended fix: return the same body for both (no session on signup — user logs in after verifying, or issue a pending session in both cases), and burn one Argon2 hash in the duplicate branch.
- Suggested owner paths: `apps/api/app/modules/identity/router.py`, `apps/web/src/features/auth/components/SignupForm*`

### SEC-06: Production startup gate accepts non-hex placeholder HMAC keys (`TD_K_DEVICE_KEY_V1`, `TD_K_LOGIN_KEY_V1`)
- Severity: Medium
- Status: Confirmed
- Component: `apps/api/app/core/startup_checks.py:376-379`, `apps/api/app/core/security.py:371-376`
- Requirement: startup_checks doc "refuse … local keys … in production"; message says "keys must be 256-bit hex in production"
- Repro: `pytest ... -k prod_gate_accepts_placeholder -s` (sets a 42-char non-hex key shaped like `.env.example`, `Settings(APP_ENV="production")`)
- Expected / Actual: a problem reported. Actual: `HMAC problems: []` — the check is `len(key_bytes) < 32`, and a non-hex placeholder is used as UTF-8 bytes (≥ 32 chars passes). `.env.example` placeholders are 39–40 chars. (The TOTP AEAD ring is checked correctly via `weak_versions`.)
- Evidence: `AUDIT prod gate HMAC problems with placeholder keys: []`
- Recommended fix: track hex-ness in `HmacKeyring` (like `AeadKeyring.weak_versions`) and refuse non-hex or `REPLACE` keys in production.
- Suggested owner paths: `apps/api/app/core/security.py`, `apps/api/app/core/startup_checks.py`, `tests/core/test_logging_and_startup.py`

### SEC-07: Remember-device is not wired end-to-end — BFF never calls AUTH-28, so the `td_remember` cookie is issued but never used
- Severity: Medium
- Status: Confirmed (static: no caller)
- Component: `apps/web/src/lib/bff/proxy.ts:115` (blocks browser calls to `auth/remember/refresh`, correct) — but nothing in `apps/web/src` calls it (grep for `remember/refresh` finds only `lib/api-types/schema.d.ts`); `middleware.ts` has no refresh-on-navigation path
- Requirement: api-spec §1.2 (lines 109, 116) "re-issued silently only on a top-level user navigation, through AUTH-28"; `docs/implementation-status.md` claims "remember-device refresh" implemented
- Expected / Actual: on a top-level navigation with an expired/absent session and a valid `td_remember`, the BFF calls AUTH-28 with the service token. Actual: never called; "Remember this device" on the login form has no effect after the session ends.
- Recommended fix: in the page middleware (or a BFF helper), on navigation with no/expired session and a remember cookie, call AUTH-28 server-side and set the returned cookies.
- Suggested owner paths: `apps/web/src/middleware.ts`, `apps/web/src/lib/bff/`

### SEC-08: Session token is not rotated when a pending login becomes active after device OTP / session choice
- Severity: Low
- Status: Confirmed
- Component: `apps/api/app/modules/identity/router.py:694-757` (`device_verification_verify`), `:759-822` (`session_choice`), `sessions/login.py:265-291` (`advance` activates without `rotate_token`)
- Requirement: api-spec AUTH-06 enforcement order ends with "rotate token, write auth_sessions…"
- Repro: `pytest ... -k token_not_rotated -s`
- Expected / Actual: new token when the session goes `pending_device_otp → active`. Actual: same token (MFA path does rotate, `router.py:627`).
- Evidence: `AUDIT session token rotated pending->active after device OTP: False`
- Recommended fix: call `ss.rotate_token` in `advance()` right before `activate_session` and return the new cookie.
- Suggested owner paths: `apps/api/app/modules/sessions/login.py`

### SEC-09: Students can satisfy step-up with their password (spec allows passkey/TOTP/SMS OTP/email OTP only)
- Severity: Low (needs product/security decision; code and its tests intentionally allow it)
- Status: Confirmed
- Component: `apps/api/app/modules/identity/router.py:1000-1011` (`_step_up_methods` adds `password`), `:119-133`
- Requirement: api-spec §1.6 and AUTH-19 example ("Students may receive [passkey, totp, sms_otp, email_otp]")
- Repro: `pytest ... -k step_up_password -s`
- Evidence: `AUDIT student step-up with password -> 200 {"last_step_up_at":"…","valid_for_seconds":…}`
- Recommended fix: either remove `password` from student step-up or update api-spec §1.6 to document it.
- Suggested owner paths: `apps/api/app/modules/identity/router.py`, `docs/api-specification.md`

### SEC-10: Production terraform composition omits security-critical env/secrets (HMAC/AEAD keys, cookie flag, proxy hops)
- Severity: Low (skeleton "not applied anywhere yet"; api would fail closed)
- Status: Confirmed (static)
- Component: `infra/terraform/envs/prod/main.tf:24-70`
- Expected / Actual: api gets `TD_K_DEVICE_KEY_V*`, `TD_K_LOGIN_KEY_V*`, `TD_K_TOTP_KEY_V*`, `TD_COOKIE_SECURE=true`; web gets `TD_TRUSTED_PROXY_HOPS`. Actual: none set → `run_startup_checks` raises (keyring not loaded / cookie flag), and web defaults to hops=0 (SEC-01).
- Suggested owner paths: `infra/terraform/envs/{dev,staging,prod}/main.tf`, `infra/terraform/modules/secrets`

### SEC-11: Passkey/WebAuthn not built; break-glass and privileged step-up accept TOTP although spec says break-glass is passkey-only
- Severity: Low (documented gap in implementation-status)
- Status: Confirmed (static)
- Component: `apps/api/app/modules/admin/accounts.py:54-60`, `identity/router.py` (no WebAuthn routes); `step_up` problems advertise `"passkey"` that cannot be used
- Requirement: api-spec AUTH-07/08, AUTH-20 ("Purpose breakglass.activate accepts passkey only")
- Recommended fix: build WebAuthn or stop advertising `passkey` in `allowed_methods`; document the TOTP exception for break-glass.
- Suggested owner paths: `apps/api/app/modules/identity/`, `apps/api/app/modules/admin/accounts.py`

## Notes (no finding)
- 26 tables have no RLS (`case_decisions`, `case_notes`, `security_incidents`, `security_bulk_lifts`, `security_report_exports`, `devices`, catalogue/policy tables…). All security ones are only reached through `security.*`-permissioned handlers; RLS would be defence in depth only.
- `role_grants` RLS (`p_rg`) lets any member of an org (incl. students) read/write that org's grant rows at the DB layer; writes are gated in `rbac/router.py`. Consider narrowing to staff roles.
- Many authenticated routes switch to `system_context` (RLS off) mid-request (e.g. `identity/router.py:396,421,1030,1071`); each was keyed by `principal.user_id` in the reviewed code.
- HSTS is not emitted by the app (expected at CloudFront).
- Recovery codes have ~51 bits of entropy and are stored as unsalted SHA-256 (fine online; weak if the DB leaks).

## Summary
- Counts: Critical 0 · High 2 (SEC-01, SEC-02) · Medium 5 (SEC-03..07) · Low 4 (SEC-08..11).
- Existing suites (identity, sessions, security, rbac, authz, core, audit: 277 tests; web BFF/auth: 58) all pass on the audit DB.
- Not tested / limits: no live-stack (browser) runs — the open-redirect browser step is inferred from Next's router code; passkeys do not exist; per-ASN login throttling and the GlitchTip `_errors` tunnel were not exercised (the tunnel is not implemented: `proxy.ts:120`); IDOR in non-security modules (assessments, commerce, learning, media…) is left to those module auditors — the route dump (`test_route_dump.py`) lists 160+ mutating routes with handler-level checks only.
