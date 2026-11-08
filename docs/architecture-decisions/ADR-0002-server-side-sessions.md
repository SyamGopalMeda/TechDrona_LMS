# ADR-0002: Server-side opaque sessions behind a same-origin Next.js BFF

* **Status:** Accepted (Brief §1) — implementation **Planned**
* **Related:** ADR-0010 (BFF), `system-architecture.md §6`, `database-schema.md §4`
* **Revision:** v0.4 (2026-11-03, Integration Lead): security review pass (CPR-BRF-03..05, CPR-ARC-02/03/05) — per-route idle effect, attempt idle hold, remember-device re-issue, same-device replacement, single-session replay revoke, versioned HMAC keys — `contract-reconciliation.md` §9

## Context

The platform must enforce idle/absolute timeouts per role tier, list and kill sessions (ASVS 7.4/7.5), cap concurrent sessions (2) and revoke access instantly when an account is restricted. OWASP and NIST advise against bearer JWTs in browser storage (research §6 [Verified]). Indian college NAT/CGNAT makes IP binding unreliable (research §3 [Verified]).

## Decision

* Session token: 256-bit CSPRNG, base64url, in cookie `__Host-td_session` (Secure, HttpOnly, SameSite=Lax, Path=/, no Domain). Only `sha256(token)` is stored (`auth_sessions.token_hash`) and used as the Redis cache key. Never bound to IP.
* Postgres `auth_sessions` is the source of truth; Redis is a read-through cache (TTL ≤ idle remaining). Revocation updates the row and deletes cache keys.
* Timeouts by `session_tier` (Brief §1): student 60 min / 24 h, staff 30 min / 12 h, privileged 15 min / 8 h + MFA. Sliding idle updated in Redis per request, persisted at most once a minute. *(v0.4, Brief v0.4 §1)* Only routes declared `x-td-idle: extends` slide the idle timer; `engaged_only` routes slide it through `sessions.touch_engaged()` when engagement is credited; `neutral` routes never do. A session bound to an in-progress attempt is not idle-expired before `idle_hold_until` (= `deadline_at + grace + 5 min`); absolute timeouts are never extended. Remember-device (trusted student devices): a new AAL1 session (`created_via = remember_device`) is silently re-issued only on a top-level user navigation, within a fixed 30-day ceiling from the last full authentication (`user_devices.remember_until`, never slides; rotated `__Host-td_remember` token stored as `remember_token_hash`). Session cookie `Max-Age` = time to absolute expiry (lab devices: browser-session cookie).
* Token rotation on login, MFA, privilege change; all sessions revoked on password change/reset. *(v0.4)* A replayed session cookie (device mismatch, UA drift) revokes **that session only** plus a takeover evaluation; all sessions are revoked only on HC-T3.
* CSRF: HMAC-signed double-submit token + Fetch Metadata (`Sec-Fetch-Site`) checks; no state change on GET.
* Concurrency cap enforced at session creation under an advisory lock. *(v0.4)* Sessions on the same device are replaced first (`replaced_same_device`); the chooser pre-selects the oldest session without an active attempt; attempt-holding sessions are never evicted (`409 session_cap_reached` if all others hold one).
* Device and login-identifier HMAC keys are versioned (`devices.key_version`, `login_attempts.key_version`) so `k_device`/`k_login` can rotate without breaking lookups (v0.4).
* A single dependency `require_active_principal` validates session, account status, restrictions, MFA tier and consent on every authenticated router.

## Alternatives considered

| Option | Why not |
|---|---|
| Stateless JWT access + refresh in browser | Revocation needs a denylist anyway; XSS exposure; timeouts hard to enforce precisely. |
| Redis-only sessions | Loss of Redis = mass logout; no durable audit of sessions for disputes/appeals. |
| Third-party IdP (Cognito/Auth0) | Data residency/cost; custom device/stream/restriction rules still needed in-app; adds a hop to every check. |

## Consequences

* (+) Instant revocation, accurate session lists, simple browser security model.
* (+) Device/session caps and restrictions are deterministic and explainable (minor-safe).
* (−) Every request needs a session lookup (Redis hit ~sub-ms; DB fallback).
* (−) Mobile apps later need a separate token flow (opaque rotating refresh tokens, short-lived access tokens — research §8).
