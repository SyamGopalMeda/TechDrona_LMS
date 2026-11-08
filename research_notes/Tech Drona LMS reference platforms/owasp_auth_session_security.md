# Authentication, Session Management, API Security & Risk-Based Auth — Standards Notes for Tech Drona LMS

Researched 2026-11-03. Target stack: FastAPI, PostgreSQL, Redis, Next.js/React.
Versions in scope: NIST SP 800-63-4 / 63B-4 (final, 31 Jul 2025); OWASP ASVS 5.0.0 (May 2025); OWASP API Security Top 10 2023; OWASP Cheat Sheet Series (live pages, fetched Nov 2026); PostgreSQL 18 (current stable; 19 at RC1 on 15 Oct 2026).
Wording used below: **[NORMATIVE]** = SHALL/MUST in NIST, or an ASVS requirement at a stated level. **[REC]** = SHOULD in NIST, or OWASP cheat-sheet guidance and vendor practice.

---

## 1. Status and versions of the governing standards

### Takeaway
NIST SP 800-63-4, including 63B-4, is final as of 31 July 2025 and replaces Rev 3. OWASP ASVS 5.0.0, released May 2025, renumbers its chapters: Authentication is now V6, Session Management is V7 and Authorization is V8. Older 4.0 IDs such as V2 and V3 should no longer be cited.

### Cited Findings
- SP 800-63-4 final has a CSRC document-history entry dated 07/31/25. It has four volumes: base, 63A-4 (proofing), 63B-4 (authentication) and 63C-4 (federation), and it supersedes Rev 3 — [NIST CSRC SP 800-63-4 final](https://csrc.nist.gov/pubs/sp/800/63/4/final); [63B-4 final](https://csrc.nist.gov/pubs/sp/800/63/B/4/final). One blog reports the release as 1 Aug, which is most likely a time-zone difference — [search summary/sakimura.org](https://www.sakimura.org/en/page/6/?p=3072)
- ASVS 5.0.0 was released May 2025. V6 covers Authentication and V7 covers Session Management — [arc42 quality: OWASP ASVS](https://quality.arc42.org/standards/owasp-asvs); chapter text from [OWASP ASVS GitHub V6](https://raw.githubusercontent.com/OWASP/ASVS/master/5.0/en/0x15-V6-Authentication.md), [V7](https://raw.githubusercontent.com/OWASP/ASVS/master/5.0/en/0x16-V7-Session-Management.md)
- V7 subsections: 7.1 Documentation, 7.2 Fundamental session security, 7.3 Timeout, 7.4 Termination, 7.5 Defenses against session abuse, 7.6 Federated re-authentication — [ASVS V7](https://raw.githubusercontent.com/OWASP/ASVS/master/5.0/en/0x16-V7-Session-Management.md)
- The current OWASP Cheat Sheet index is mapped to ASVS 5.0.x — [OWASP Cheat Sheet IndexASVS](https://cheatsheetseries.owasp.org/IndexASVS.html)

### Inferences
- Target ASVS 5.0 **Level 2** as the baseline for Tech Drona. It covers MFA (6.3.3), timeouts (7.3.x) and session listing and revocation (7.5.2). Apply L3 items selectively to admin and finance consoles.
- Use NIST AAL2 for learner and instructor accounts that hold PII or payments. Use AAL2 with phishing-resistant authentication (or AAL3-like) for platform admins.

### Gaps
- I did not fetch the ASVS 5.0 **V8 Authorization** chapter, so its requirement IDs (object-level and function-level access control) are not listed here. The file is at `https://github.com/OWASP/ASVS/tree/master/5.0/en` (0x17-V8-Authorization.md).

---

## 2. Passwords, hashing, brute force, lockout vs throttling

### Takeaway
Require a minimum of 15 characters for password-only accounts and 8 when MFA is enforced. Accept at least 64 characters, impose no composition rules and no periodic rotation, and screen passwords against a blocklist and breach corpus. Hash with Argon2id at m=19 MiB, t=2, p=1 or stronger. Cap consecutive failures at 100 or fewer per NIST. OWASP prefers exponential back-off per account to hard lockout.

### Cited Findings
**NIST 63B-4 (Sec. 3.1.1) [NORMATIVE]** — [SP 800-63B-4](https://pages.nist.gov/800-63-4/sp800-63b.html)
- Single-factor passwords: minimum length **15** (SHALL).
- Passwords used only as part of MFA: minimum length **8** (SHALL).
- Maximum length: verifiers SHOULD allow at least **64** characters.
- Composition rules: SHALL NOT be imposed.
- Periodic change: SHALL NOT be required. A change SHALL be forced on evidence of compromise.
- Blocklist: SHALL compare against commonly used, expected or compromised values, matching the whole password. Users SHALL be told why a password was rejected.
- Password hints and KBA prompts: SHALL NOT be used.
- Password managers and autofill: SHALL be allowed. Paste SHOULD be allowed.
- Storage: SHALL be salted and hashed with a salt of at least **32 bits**.
- Rate limiting (Sec. 3.2.2): consecutive failed attempts per authenticator SHALL be limited to **≤100**, after which the authenticator is disabled. Lower limits MAY be set.
- Informative usability guidance: allow at least 10 attempts, show how many remain, and say how long to wait — [SP 800-63B-4](https://pages.nist.gov/800-63-4/sp800-63b.html)

**ASVS 5.0 V6**, all IDs — [ASVS V6](https://raw.githubusercontent.com/OWASP/ASVS/master/5.0/en/0x15-V6-Authentication.md)

| ID | Requirement | Level |
|---|---|---|
| 6.2.1 | Minimum 8 characters (15 strongly recommended) | L1 |
| 6.2.3 | Changing a password requires the current and new password | L1 |
| 6.2.4 | Check against the top 3000 common passwords | L1 |
| 6.2.5 | No composition rules | L1 |
| 6.2.7 | Allow paste and password managers | L1 |
| 6.2.9 | Allow at least 64 characters | L2 |
| 6.2.10 | No periodic rotation | L2 |
| 6.2.11 / 6.1.2 | Block and document context-specific words (product or org names, e.g. "techdrona") | L2 |
| 6.2.12 | Check against breached-password sets | L2 |
| 6.1.1 / 6.3.1 | Document and implement anti-credential-stuffing and brute-force controls that do not allow malicious lockout | L1 |
| 6.3.2 | Remove default accounts (root, admin, sa) | L1 |
| 6.3.8 | No user enumeration: identical errors, status codes and timing, including registration and reset | L3 |

**OWASP Authentication Cheat Sheet [REC]** — [OWASP Authentication CS](https://cheatsheetseries.owasp.org/cheatsheets/Authentication_Cheat_Sheet.html)
- Allow at least 64 characters, never truncate silently, impose no composition rules, and check against Pwned Passwords or a self-hosted copy.
- Use a generic message, e.g. "Login failed; Invalid user ID or password", with consistent status codes and timing.
- Lockout: the cheat sheet gives **no fixed threshold**. It suggests exponential delay that starts around 1 s and doubles, with at most 2–3 escalations before permanent lockout.
- Count failures **per account, not per IP**.
- Keep the forgot-password flow available to locked users so lockout cannot be used for DoS.
- Use CAPTCHA only as defense in depth, ideally after a few failures.
- Log all authentication failures and lockouts, and monitor them in real time.

**OWASP Password Storage Cheat Sheet [REC]** — [OWASP Password Storage CS](https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html)

| Algorithm | When to use | Parameters |
|---|---|---|
| Argon2id | Default | Minimum m=19456 KiB (19 MiB), t=2, p=1. Equivalent alternatives: m=46 MiB/t=1; 12 MiB/t=3; 9 MiB/t=4; 7 MiB/t=5 (all p=1) |
| scrypt | If Argon2id is unavailable | N=2^17, r=8, p=1 (or the listed equivalents) |
| bcrypt | Legacy only | Cost ≥10. Input limit is **72 bytes**, so enforce a max length. Plain pre-hashing is dangerous; if needed use `bcrypt(base64(hmac-sha384(pw, pepper)))` |
| PBKDF2 | FIPS requirement | PBKDF2-HMAC-SHA256 600,000 iterations; PBKDF2-HMAC-SHA512 220,000 (live page value) |
- Pepper: shared across hashes, stored in a vault or HSM rather than the database, and defense in depth only.
- Store hashes in PHC string format so the algorithm and parameters travel with each hash.
- Rehash to current parameters on the next successful login.

**OWASP Credential Stuffing Prevention CS [REC]** — [OWASP Credential Stuffing CS](https://cheatsheetseries.owasp.org/cheatsheets/Credential_Stuffing_Prevention_Cheat_Sheet.html)
- MFA is the primary control (the cheat sheet cites Microsoft's 99.9% figure).
- Layered controls:
  - CAPTCHA only on suspicious logins.
  - IP intelligence (residential vs hosting, proxy/VPN), with graduated and temporary blocks over short and long windows.
  - Device fingerprinting and connection fingerprinting (JA3, HTTP/2).
  - Non-email usernames.
  - Multi-step login.
  - Degradation such as proof-of-work and delays.
  - Per-defense metrics.
- Notifications: do **not** notify on simple wrong-password attempts. **Do** notify when the password was correct but MFA failed. Show the last login's time and location, and let users view and terminate sessions.

### Inferences
- Policy for Tech Drona: minimum 15 characters, or 8 once the user has MFA enrolled. Max 128 characters, which is above the NIST/ASVS floor of 64 and also bounds Argon2 DoS. No composition rules. Check the k-anonymity HIBP range API plus a local top-N list plus context words ("techdrona", "drona", course names).
- Throttling design in Redis:
  - Per-account counter with exponential back-off (1 s, 2 s, 4 s, … capped at roughly 15 min).
  - Hard disable at ≤100 consecutive failures to meet NIST, with unlock through reset or MFA.
  - Separate per-IP and per-ASN sliding windows to catch password spray.
  - A global failed-login rate alarm.
- Argon2id hashing is CPU and memory heavy. Run it in a threadpool (`run_in_threadpool`) and rate-limit **before** hashing so the login endpoint cannot be used for DoS (OWASP API4).

### Gaps
- OWASP gives no single numeric lockout threshold or observation window. 100 is NIST's ceiling, not a recommended value.

---

## 3. Session management: server-side sessions, cookies, timeouts, fixation

### Takeaway
Use opaque, CSPRNG-generated session IDs of at least 128 bits (ASVS 7.2.3), kept server-side in Redis. Send them in a `__Host-` cookie with `Secure; HttpOnly; SameSite=Lax|Strict; Path=/` and no Domain. Rotate the ID on login and on privilege change. Enforce both idle and absolute timeouts on the server. NIST AAL2 sets an absolute limit of 24 h or less and an idle limit of 1 h or less. AAL3 sets 12 h or less and 15 min or less.

### Cited Findings
**NIST 63B-4 Sec. 5 [NORMATIVE]** — [SP 800-63B-4](https://pages.nist.gov/800-63-4/sp800-63b.html)

Session secrets (SHALL):
- generated from an approved RBG;
- at least **64 bits** long;
- erased on logout;
- sent only over an authenticated protected channel;
- rejected after timeout;
- never available to intermediaries.

Other session rules:
- A session SHALL NOT be treated as a higher AAL than the authentication event that created it.
- A session SHALL NOT fall back from HTTPS to HTTP.
- POST and PUT requests SHALL carry a session-bound CSRF value that the RP verifies.
- Secrets SHOULD NOT be stored in HTML5 localStorage.
- Bearer session secrets SHOULD NOT persist across app restarts or reboots.

Cookies:

| Attribute | Strength | Rule |
|---|---|---|
| Secure | SHALL | Sent over HTTPS only |
| Scope | SHALL | Minimum practical host and path |
| HttpOnly | SHOULD | |
| Expiry | SHOULD / SHALL NOT | SHOULD expire near session end, but SHALL NOT be relied on to enforce the timeout |
| Prefix and path | SHOULD | `__Host-` with `Path=/` |
| SameSite | SHOULD | `Lax` or `Strict` |
| Content | SHOULD / SHALL NOT | SHOULD be opaque; SHALL NOT contain cleartext PII |

- "Remember my browser" cookies SHALL NOT replace authentication. The one exception is AAL2 reauthentication after the inactivity timeout but within the overall timeout.
- Reauthentication (Sec. 2 and 5.2), with the session terminated when either timer expires:

| AAL | Overall (absolute) timeout | Inactivity timeout |
|---|---|---|
| AAL1 | SHOULD ≤ 30 days | MAY be applied |
| AAL2 | SHOULD ≤ 24 h | SHOULD ≤ 1 h |
| AAL3 | **SHALL** ≤ 12 h | SHOULD ≤ 15 min |

**ASVS 5.0 V7** — [ASVS V7](https://raw.githubusercontent.com/OWASP/ASVS/master/5.0/en/0x16-V7-Session-Management.md)

| ID | Requirement | Level |
|---|---|---|
| 7.1.1 | Document idle and absolute timeouts and justify any deviation from NIST 63B | L2 |
| 7.1.2 | Document the concurrent-session limit and what happens at the limit | L2 |
| 7.2.1 | Verify tokens at a trusted backend | L1 |
| 7.2.2 | Use dynamic tokens, not static API keys, for sessions | L1 |
| 7.2.3 | Reference tokens: CSPRNG, **≥128 bits** entropy | L1 |
| 7.2.4 | Issue a new token on authentication or reauthentication and kill the old one | L1 |
| 7.3.1 | Enforce the inactivity timeout | L2 |
| 7.3.2 | Enforce the absolute lifetime | L2 |
| 7.4.1 | Logout and expiry block further use. Self-contained tokens need revocation (deny list, per-user cutoff time, or key rotation) | L1 |
| 7.4.2 | Kill all sessions when an account is disabled or deleted | L1 |
| 7.4.3 | Offer to kill other sessions after a factor change or reset | L2 |
| 7.4.4 | Visible logout on every page | L2 |
| 7.4.5 | Admins can kill sessions for one or all users | L2 |
| 7.5.1 | Full reauthentication before changing email, phone, MFA or recovery settings | L2 |
| 7.5.2 | Users can list and terminate sessions (after reauthentication) | L2 |
| 7.5.3 | Step-up before highly sensitive transactions | L3 |
| 7.6.2 | No silent session creation via SSO without user action | L2 |

**OWASP Session Management CS [REC]** — [OWASP Session Mgmt CS](https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html)
- Entropy: at least 64 bits. Custom IDs: at least 128 bits from a CSPRNG.
- Use `__Host-` (Secure, no Domain, Path=/). Use `__Secure-` only when subdomain sharing is needed.
- Set SameSite explicitly: Strict preferred, or Lax. Never set None without Secure.
- Idle timeout: **2–5 min** for high-value apps, **15–30 min** for low-risk apps. Absolute: **4–8 h** for office-day usage.
- Regenerate the ID on any privilege change (login, password change, role elevation) and destroy the old one.
- Use strict mode: reject server-unknown IDs and alert. Accept IDs from cookies only, never from the URL.
- Logout must invalidate the session server-side. Also send `Clear-Site-Data: "cache","cookies","storage"`, and use `Cache-Control: no-store` on session data.
- Never put session IDs, JWTs or refresh tokens in localStorage or sessionStorage. Use HttpOnly cookies or the **Backend-for-Frontend (BFF)** pattern.
- Detection: alert on many distinct IDs from one IP, and on IP-geo or User-Agent changes mid-session. IP and UA binding can be bypassed or broken by NAT.
- Log a **salted hash** of the session ID, never the raw ID.
- Reauthenticate after password or email change, a new device or IP, and account recovery.

### Inferences
Recommended Tech Drona defaults. These are my design choices, mapped to the standards above.

| Account type | Idle timeout | Absolute timeout | "Remember me" |
|---|---|---|---|
| Learners (AAL2-ish) | 60 min | 24 h | Up to 30 days for low-risk read-only course viewing. NIST treats this as AAL1, so require reauthentication for payments and profile changes |
| Instructors and org admins | 30 min | 12 h | Not allowed |
| Platform super-admins | 15 min | 8–12 h | Not allowed. Phishing-resistant MFA required |

- Next.js on `app.techdrona.in` with the API on the same site: use a BFF/same-origin proxy so the browser only ever holds the `__Host-sid` cookie, and keep tokens server-side.
- Session store in Redis:
  - Key = SHA-256(session_id). Value holds user_id, tenant_id, aal, created_at, last_seen, auth_time and device info.
  - Use the Redis TTL as the idle timer and enforce absolute expiry in the record.
  - Keep a per-user set of session keys to support "logout everywhere" (ASVS 7.4.x / 7.5.2).

### Gaps
- None material.

---

## 4. JWT access/refresh tokens vs server-side sessions; rotation and reuse detection

### Takeaway
JWTs need explicit revocation machinery (ASVS 7.4.1), and the browser should not store them. For a first-party web LMS, opaque server-side sessions, or a BFF holding tokens, are simpler and meet ASVS directly. If JWTs are used (mobile app or public API):
- keep access tokens short-lived;
- pin algorithms and validate exp, nbf, iss and aud;
- revoke by `jti`;
- rotate refresh tokens with family-wide revocation on reuse.

### Cited Findings
**OWASP JWT Cheat Sheet [REC]** — [OWASP JWT CS](https://cheatsheetseries.owasp.org/cheatsheets/JSON_Web_Token_Cheat_Sheet.html)
- Reject `alg:none`.
- Hardcode the accepted algorithms (e.g. `algorithms=["ES256"]`) and never mix MAC and public-key algorithms in one validation path, to prevent key confusion.
- HMAC secrets come from a CSPRNG, at least as long as the hash (256 bits for HS256), with at least 160 bits of entropy, and are never reused across audiences or issuers.
- Always validate `exp`, `nbf`, `iss` and `aud`, and keep lifetimes short.
- Revocation: key the denylist on **`jti` + `iss`** and hold each entry until `exp`. Do **not** key it on the raw token or its hash, because JWT malleability can bypass that.
- Alternatives to a denylist: Token Status Lists, a session-bound nonce, or sender-constrained tokens (**DPoP** or mTLS).
- JWS claims are readable by anyone holding the token, so keep PII out. Use nested JWS-in-JWE if claims must be confidential.

**Auth0 refresh token rotation [vendor practice]** — [Auth0 Refresh Token Rotation](https://auth0.com/docs/secure/tokens/refresh-tokens/refresh-token-rotation)
- Each refresh returns a new refresh token, and the one presented is invalidated immediately.
- Tokens descended from the same original form a **token family**. Presenting an already-used refresh token invalidates the whole family, so the user must reauthenticate.
- Reuse events are logged (`ferrt`).

**ASVS 7.4.1 / 7.2.4** require revocation for self-contained tokens and new tokens on reauthentication — [ASVS V7](https://raw.githubusercontent.com/OWASP/ASVS/master/5.0/en/0x16-V7-Session-Management.md)

### Inferences
- If JWTs are used:
  - Access token TTL 5–15 min, ES256 or EdDSA, with `kid`-based key rotation.
  - Refresh token: opaque (not a JWT), 256-bit random, stored hashed in PostgreSQL or Redis with `family_id`, `parent_id`, `used_at`, `revoked_at` and `expires_at`.
  - Allow a small reuse grace window (a few seconds) to absorb concurrent-tab races.
  - Revoke the family on reuse.
  - Add a per-user `tokens_valid_after` timestamp for "logout everywhere" and for password reset.
- Step-up: record `auth_time` and `amr`/`acr` in the session. For sensitive routes (payment, payout settings, email or MFA change, grade overrides, bulk export), require `now - auth_time < 5–15 min` and the MFA factor; otherwise force reauthentication (ASVS 7.5.1 / 7.5.3).

### Gaps
- I did not fetch the IETF OAuth 2.0 Security BCP (RFC 9700, Jan 2025). Its requirement that public-client refresh tokens be sender-constrained or rotated should be confirmed at https://www.rfc-editor.org/rfc/rfc9700.
- I did not retrieve Auth0's default refresh-token lifetimes or reuse-interval values. The cheat sheet's sidejacking fingerprint-cookie guidance no longer appears on the current JWT cheat sheet.

---

## 5. CSRF, forgot password, MFA

### Takeaway
For cookie-authenticated APIs, layer three controls:
- Fetch Metadata (`Sec-Fetch-Site`) checks;
- a session-bound, HMAC-signed double-submit token or a custom header with a strict CORS allowlist;
- SameSite=Lax/Strict, as defense in depth only.

Reset tokens must be single-use, CSPRNG-generated and short-lived. A reset must not bypass MFA and must not auto-login. Prefer passkeys/WebAuthn, then TOTP. SMS is "restricted" under NIST, and email is not an acceptable authenticator at ASVS L3.

### Cited Findings
**CSRF** — [OWASP CSRF CS](https://cheatsheetseries.owasp.org/cheatsheets/Cross-Site_Request_Forgery_Prevention_Cheat_Sheet.html)
- Never change state via GET.
- Signed double-submit token: HMAC-SHA-256 over the session ID plus a random value, compared in constant time. Read it from a header or body field, not from the cookie alone. Naive double-submit is discouraged.
- Fetch Metadata: reject `Sec-Fetch-Site: cross-site` on POST, PUT, PATCH and DELETE. Fall back to Origin/Referer when the header is missing, rejecting `Origin: null`. Add `Vary: Sec-Fetch-Site, Origin`.
- Custom header such as `X-CSRF-Token` plus a strict CORS allowlist without wildcard subdomains. Reject `text/plain`, form-urlencoded and multipart bodies on JSON APIs.
- Use `__Host-` on CSRF cookies.
- Login CSRF: put a pre-session token on the login form, then issue a new session ID after login.
- NIST also requires a session-bound CSRF value on POST and PUT — [SP 800-63B-4](https://pages.nist.gov/800-63-4/sp800-63b.html)

**Forgot password** — [OWASP Forgot Password CS](https://cheatsheetseries.owasp.org/cheatsheets/Forgot_Password_Cheat_Sheet.html)
- Return the same message and the same timing whether or not the account exists.
- Tokens: CSPRNG, tied to one user, single-use, stored hashed, with an expiry. The cheat sheet sets no exact TTL.
- Never build the reset URL from the Host header. Set `Referrer-Policy: no-referrer` on the reset page.
- Rate-limit reset requests per account.
- No account changes and no lockout before the token is proven.
- No automatic login after reset. Notify the user, and offer or force termination of all sessions.
- Security questions must not be the sole reset method.
- Related ASVS requirements — [ASVS V6](https://raw.githubusercontent.com/OWASP/ASVS/master/5.0/en/0x15-V6-Authentication.md):
  - 6.4.3 (L2): reset must not bypass MFA.
  - 6.4.2 (L1): no hints or KBA.
  - 6.4.4 (L2): replacing a lost factor needs proofing at enrollment level.
  - 6.4.6 (L3): admins cannot set user passwords.
- NIST recovery-code validity: 10 min for text/voice delivery, 24 h for email. Saved recovery codes need at least 64 bits — [SP 800-63B-4](https://pages.nist.gov/800-63-4/sp800-63b.html)

**MFA** — [OWASP MFA CS](https://cheatsheetseries.owasp.org/cheatsheets/Multifactor_Authentication_Cheat_Sheet.html), [ASVS V6](https://raw.githubusercontent.com/OWASP/ASVS/master/5.0/en/0x15-V6-Authentication.md), [SP 800-63B-4](https://pages.nist.gov/800-63-4/sp800-63b.html)
- Where MFA applies:
  - Require it at login on **every path** (API and mobile included).
  - Require it to change the password or email, disable MFA, or elevate to admin.
  - Changing factors requires reauthentication with an existing factor plus an out-of-band notification.
- Factor strength and rules:
  - Prefer FIDO2/WebAuthn and validate the UV flag on the server.
  - TOTP is the default fallback (30 s step).
  - SMS is weak (SIM swap). Email is weakest.
  - Issue single-use recovery codes at enrollment.
- ASVS 6.3.3: MFA is required from L2. L3 requires a phishing-resistant hardware factor.
- ASVS OTP rules:
  - 6.5.5: TOTP lifetime ≤30 s; out-of-band lifetime ≤10 min.
  - 6.5.1: single use.
  - 6.5.4: at least 20 bits (6 digits).
  - 6.5.2: hash low-entropy lookup secrets.
  - 6.6.1: SMS allowed only with a validated number, alongside stronger options, and never at L3.
  - 6.6.4: rate-limit push notifications against push-bombing.
  - 6.3.6: email is not allowed as a factor at L3.
- NIST:
  - PSTN/SMS is the only **"restricted"** authenticator. The CSP SHALL offer an unrestricted alternative, give users risk notice and keep a migration plan. Verifiers SHOULD check SIM-swap and number-porting signals.
  - Email SHALL NOT be used for out-of-band authentication.
  - Out-of-band SHALL complete within **10 min**, and an OTP is accepted **once**.
  - At AAL2 the verifier SHALL **offer** at least one phishing-resistant option.
  - Syncable passkeys are allowed at AAL2 but SHALL NOT be used at AAL3.

### Inferences
- In India, SMS OTP is culturally expected, and phone-number-first login is common in Indian edtech. Treat SMS as a NIST "restricted" factor:
  - Offer TOTP and passkeys as well.
  - Check number-porting or SIM-change signals where the telecom or aggregator API provides them.
  - Rate-limit OTP sends per number, IP and device to curb SMS pumping, which is a cost risk under OWASP API4 and API6.
  - Never use email magic links as the second factor for admins.
- Recommended token TTLs: reset links 15–30 min, single-use and stored hashed. Email verification codes up to 24 h, matching NIST's email recovery-code value. SMS OTPs 5–10 min.

### Gaps
- No OWASP source gives an exact reset-token TTL or length. The 15–30 min above is my recommendation.

---

## 6. OWASP API Security Top 10 2023 (FastAPI mapping)

### Takeaway
Object-level authorization (API1) and property-level authorization (API3) are the critical risks for a multi-tenant LMS: course, enrollment, submission, grade and certificate IDs. API4 and API6 cover OTP and SMS cost abuse and scraping of paid content.

### Cited Findings
All ten items — [OWASP API Security Top 10 2023](https://api-security.owasp.org/editions/2023/en/0x11-t10)
1. API1 Broken Object Level Authorization: check, on every request, that the caller may access *that* object ID.
2. API2 Broken Authentication.
3. API3 Broken Object Property Level Authorization: excessive data exposure and mass assignment.
4. API4 Unrestricted Resource Consumption: bandwidth, CPU and **paid third-party services** (SMS, email).
5. API5 Broken Function Level Authorization: admin vs user functions.
6. API6 Unrestricted Access to Sensitive Business Flows: automation abuse.
7. API7 SSRF.
8. API8 Security Misconfiguration.
9. API9 Improper Inventory Management: old versions, debug endpoints.
10. API10 Unsafe Consumption of third-party APIs.

### Inferences
| Risk | FastAPI mitigation |
|---|---|
| API1 | Every repository query is scoped by `tenant_id` plus ownership or enrollment, enforced centrally (dependency plus PostgreSQL RLS, section 9). Use UUIDv7 or random IDs so IDs are not enumerable, but do not rely on that for security |
| API3 | Separate Pydantic input and output models. Use `extra="forbid"` on input and never accept `role`, `tenant_id` or `is_admin` from the client. Use explicit response models |
| API5 | Role checks via route dependencies with deny by default, and admin routers under a separate prefix with their own dependency |
| API4 / API6 | Redis rate limits per user, IP and route. Caps on page size and upload size, request timeouts, and quotas on OTP sends and video-URL signing |
| API9 | Disable `/docs` and `/openapi.json` in production or put them behind auth, and keep an inventory of versions |
| API7 / API10 | Validate and allowlist outbound URLs (e.g. webhook targets, LTI/SCORM imports), and validate third-party responses |

### Gaps
- I did not fetch the per-item mitigation pages; the one-line descriptions are from the index page.

---

## 7. Risk-based / adaptive authentication

### Takeaway
The major IdPs combine IP reputation, travel velocity, unfamiliarity of device, ASN and location, anonymizers, spray patterns and leaked credentials into low, medium or high risk. They respond in steps: allow, then MFA, then block, with a secure password reset for high user risk. A home-grown version for Tech Drona can copy these signals.

### Cited Findings
**Microsoft Entra ID Protection** (page updated 21 Oct 2026) — [Microsoft Learn: risk detections](https://learn.microsoft.com/en-us/entra/id-protection/concept-identity-protection-risks)

Sign-in risk detections, real-time unless noted:
- Anonymous IP address (Tor or anonymous VPN).
- Atypical travel: two distant sign-ins, judged against the time needed to travel between them.
- Impossible travel (offline, via Defender for Cloud Apps).
- Unfamiliar sign-in properties: IP, ASN, location, device, browser, subnet. There is a learning period of **at least 5 days** for new users, and users re-enter learning after long inactivity.
- Malicious IP: high invalid-credential failure rates.
- Password spray: fires only when the sprayed password **validated successfully**.
- Verified threat actor IP.
- Anomalous token: unusual lifetime or replay location, covering session and refresh tokens.
- Suspicious MFA approval: requester and approver device proximity.
- New country (offline).

User risk detections:
- Leaked credentials: always **high**. Remediated by a secure password reset.
- Attacker-in-the-Middle: high. May need a password reset and session revocation.
- Suspicious credential addition: a new auth method registered under suspicious conditions.
- User reported suspicious activity: user denied an MFA prompt and reported it.

**Okta ThreatInsight** — [Okta Help: About ThreatInsight](https://help.okta.com/en-us/content/topics/security/threat-insight/about-threatinsight.htm)
- Evaluates sign-in requests **before authentication** against IP reputation aggregated across all Okta orgs. Targets credential stuffing, brute force and password spray.
- Modes: Log, or Log + Block (recommended).
- **Blocked requests are not counted as failed sign-ins, which avoids lockouts.**
- Trusted proxy IPs must be configured correctly or detection degrades.

**OWASP MFA / Credential Stuffing CS** — [MFA CS](https://cheatsheetseries.owasp.org/cheatsheets/Multifactor_Authentication_Cheat_Sheet.html), [Credential Stuffing CS](https://cheatsheetseries.owasp.org/cheatsheets/Credential_Stuffing_Prevention_Cheat_Sheet.html)
- Risk triggers: new device or location, IP reputation, proxy or VPN, unusual time, behavioral signals, known compromised credentials.
- Responses: an extra factor, reauthentication, or deny plus alert.
- Risk signals are **not** a substitute for an authentication factor, and fallbacks must not be weaker than the primary MFA.

### Inferences
Proposed graduated policy for Tech Drona. This is my design, not a sourced standard.

| Risk | Example signals | Response |
|---|---|---|
| Low | Known device or cookie, usual ASN or city | Allow, with MFA per policy |
| Medium | New device, new city or ASN, VPN, velocity over N accounts per IP | Step-up MFA (TOTP or passkey preferred over SMS), plus a notification email |
| High | Tor or known-bad IP, impossible travel (km/h above a threshold), breached password match, correct password + failed MFA, spray pattern | Block or require a secure reset, revoke sessions, alert security |

- Copy Okta's behavior: blocked pre-auth requests do not increment the user's lockout counter, so attackers cannot weaponize lockout.
- Use a per-user learning period of 5 days or more before "unfamiliar properties" is enforced, as Entra does.
- India note: carrier-grade NAT and mobile IP churn are common, so weight ASN and device over raw IP, and do not hard-bind sessions to IP.

### Gaps
- I did not fetch Auth0 Adaptive MFA (NewDevice, ImpossibleTravel, UntrustedIP confidence scoring) or Google's account-security risk documentation, so their exact signal names and thresholds are not cited here.
- I did not retrieve Entra's documented policy recommendations (e.g. MFA at medium+ sign-in risk, password change at high user risk); verify at learn.microsoft.com "risk-based access policies".

---

## 8. Logging, audit trails, webhooks, idempotency and replay protection

### Takeaway
Log authentication and authorization events in structured form, but never passwords, tokens, raw session IDs, keys or connection strings. Verify webhooks by HMAC over the raw body plus a timestamp tolerance (Stripe's is 5 min), and dedupe by event ID because delivery is at-least-once and unordered.

### Cited Findings
**OWASP Logging CS** — [OWASP Logging CS](https://cheatsheetseries.owasp.org/cheatsheets/Logging_Cheat_Sheet.html)

Never log directly (remove, mask, hash or encrypt instead):
- source code;
- **session IDs** (hash them if needed);
- **access tokens**;
- passwords;
- DB connection strings;
- encryption keys and secrets;
- bank and card data;
- sensitive PII (health data, government IDs, data about vulnerable people);
- data above the log system's classification;
- commercially sensitive data;
- data without consent.

Names, phones and emails need special handling or pseudonymization.

Always log:
- auth successes and failures;
- authorization failures;
- session failures;
- input and output validation failures;
- privilege and admin changes;
- use of break-glass accounts;
- sensitive data access;
- data import and export;
- key use and rotation;
- uploads;
- consent opt-ins;
- business-logic abuse.

Integrity:
- tamper detection;
- copy logs to read-only media quickly;
- monitor and restrict log access;
- detect when logging stops;
- use structured JSON;
- strip CR/LF from logged values;
- cap the length of user-supplied fields.

**Stripe webhooks** — [Stripe Webhooks docs](https://docs.stripe.com/webhooks)
- Signing: HMAC-SHA256 over `"{t}.{raw_body}"` in the `Stripe-Signature` header (`t=…,v1=…`).
- Verification:
  - Ignore any scheme other than `v1` (prevents downgrade).
  - Compare in constant time.
  - Use the **raw body**; framework re-serialization breaks verification.
- Replay: the default tolerance is **5 minutes**. A tolerance of 0 disables the recency check. Keep server clocks on NTP.
- Delivery behavior:
  - Duplicates happen, so record processed **event IDs**.
  - Ordering is not guaranteed, and `created` must not be used for ordering or dedupe.
  - Retries continue for up to 3 days in live mode.
- Handler: return 2xx quickly and process asynchronously through a queue. Exempt the route from CSRF.
- Secret rotation: up to 24 h overlap.

### Inferences
- Audit log design (PostgreSQL):
  - Store audit records in an `audit_events` table separate from operational logs.
  - The app DB role gets INSERT only; REVOKE UPDATE, DELETE and TRUNCATE. A trigger rejects UPDATE and DELETE, and the table is partitioned by month.
  - Each row stores `prev_hash` and `hash = SHA-256(prev_hash || canonical_json(row))`, chained per tenant or globally.
  - Periodically anchor the latest hash to external WORM storage (e.g. S3 Object Lock) so truncation can be detected. This implements OWASP's "tamper detection / read-only media" guidance.
- Idempotency:
  - A `processed_events(provider, event_id)` table with a unique constraint, inserted in the same transaction as the side effect.
  - An `Idempotency-Key` header for client POSTs (payments, enrollments), cached in Redis with a 24 h TTL holding the response.
- Indian payment gateways (Razorpay, PayU, Cashfree) use the same HMAC-signed webhook pattern. Apply identical controls: raw body, constant-time compare, event-ID dedupe.

### Gaps
- I found no authoritative standard (OWASP or NIST) that prescribes hash chaining specifically; it is common practice inferred from OWASP's tamper-detection requirement.
- I did not fetch Razorpay's own webhook signature docs.

---

## 9. Python/FastAPI libraries and multi-tenant isolation in PostgreSQL

### Takeaway
Do not use passlib in new code. It is unmaintained and breaks on newer Python and bcrypt; use pwdlib with Argon2 (or argon2-cffi directly), as FastAPI Users v13 does. For tenant isolation, PostgreSQL RLS is a strong second layer, but owners and BYPASSRLS roles skip it, so the app must connect as a non-owner role and tables need FORCE RLS.

### Cited Findings
**Python libraries**
- passlib has been unmaintained for years, and the pwdlib author states it will not work from Python 3.13 unless updated — [fastapi-users issue #1325](https://github.com/fastapi-users/fastapi-users/issues/1325); [Introducing pwdlib](https://polar.sh/frankie567/posts/introducing-pwdlib-a-modern-password-hash-helper-for-python)
- pwdlib supports Argon2 and bcrypt: `pip install 'pwdlib[argon2]'`, then `PasswordHash.recommended()` — [pwdlib intro](https://polar.sh/frankie567/posts/introducing-pwdlib-a-modern-password-hash-helper-for-python)
- FastAPI Users 13.0.0 switched from passlib to pwdlib, with Argon2 as the default. Existing bcrypt hashes still verify and are upgraded to Argon2 at login — [fastapi-users releases](https://github.com/fastapi-users/fastapi-users/releases/latest)
- A reported passlib + bcrypt≥4.0 breakage was attributed by the bcrypt maintainers to deployment rather than an API change. The exact failure is unverified — [pyca/bcrypt #414](https://github.com/pyca/bcrypt/issues/414)

**PostgreSQL 18 RLS** — [PostgreSQL docs: Row Security Policies](https://www.postgresql.org/docs/current/ddl-rowsecurity.html)
- `ENABLE ROW LEVEL SECURITY` with no policy means **default deny**.
- Superusers and `BYPASSRLS` roles always bypass RLS. Table owners bypass it unless `FORCE ROW LEVEL SECURITY` is set.
- `USING` filters visible or targeted rows. `WITH CHECK` validates new or updated rows and defaults to the USING expression.
- Permissive policies combine with OR. `AS RESTRICTIVE` policies combine with AND.
- Unique, PK and FK checks bypass RLS. This is a covert channel for existence probing.
- Policies with sub-SELECTs on other tables can race under READ COMMITTED.
- `TRUNCATE` and `REFERENCES` are not subject to RLS.
- `row_security=off` raises an error rather than bypassing, which is useful for backups.

### Inferences
**Libraries**

| Need | Library |
|---|---|
| Password hashing | `pwdlib[argon2]` or `argon2-cffi` (`PasswordHasher(time_cost=2, memory_cost=19456, parallelism=1)` minimum; tune up to about 250–500 ms per hash), with `check_needs_rehash()` on login |
| OAuth/OIDC (Google login, SSO) | `authlib` |
| TOTP | `pyotp`: `valid_window=1`, store the last-used timestep to enforce single use (ASVS 6.5.1) |
| Passkeys | `webauthn` (py_webauthn, Duo Labs) |
| JWT | PyJWT with an explicit `algorithms=[...]` list and required `exp`/`iss`/`aud`, or `joserfc`/`authlib.jose` |
| Rate limiting | Redis-backed (e.g. `fastapi-limiter`/`slowapi` or a custom Lua sliding window) |

These library choices are general ecosystem knowledge; only the passlib and pwdlib statements are sourced above.

Known pitfalls:
- Synchronous Argon2 inside an async route blocks the event loop.
- `python-jose` maintenance concerns (not verified in this session).
- Trusting `X-Forwarded-For` without trusted-proxy config.
- Comparing secrets with `==` instead of `hmac.compare_digest`.

**Multi-tenant pattern** (shared schema, `tenant_id` on every row)
- Layer 1, application: a repository and dependency layer always filters by tenant, with BOLA checks per object.
- Layer 2, database:
  - RLS policy `USING (tenant_id = current_setting('app.tenant_id')::uuid)` with a matching `WITH CHECK`, and `FORCE ROW LEVEL SECURITY`.
  - The app connects as a non-owner, non-BYPASSRLS role. Migrations run as the owner.
  - `SET LOCAL app.tenant_id` happens per transaction. This is critical with pgBouncer transaction pooling: use SET LOCAL, never session-level SET, which would leak across pooled connections.
- Add a restrictive policy as a backstop.
- Composite FKs `(tenant_id, id)` prevent cross-tenant references.
- Consider schema-per-tenant or DB-per-tenant only for large B2B institutional customers with contractual isolation needs.

### Gaps
- The PostgreSQL page did not document the `current_setting()`-based tenant pattern; the pattern above is common practice, not quoted from the docs.
- I did not verify the current release versions or maintenance status of authlib, pyotp, py_webauthn, PyJWT or python-jose in this session.

---

## 10. REST Security Cheat Sheet

### Takeaway
Not fetched in this session. See the gap below.

### Cited Findings
- (none fetched)

### Inferences
- Commonly applicable REST controls are already covered above: HTTPS only, authentication on every endpoint, method allowlisting, strict content-type validation, CORS allowlist, rate limiting, and no sensitive data in URLs.

### Gaps
- The OWASP REST Security Cheat Sheet (https://cheatsheetseries.owasp.org/cheatsheets/REST_Security_Cheat_Sheet.html) was not retrieved. Its specific items (security headers, HTTP 405/406/415 handling, API keys) should be verified by the report writer or a follow-up researcher.
