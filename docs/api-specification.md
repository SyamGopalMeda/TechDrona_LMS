# Tech Drona LMS — API Specification (v0.3)

> **Single-company note (2026-11-06).** Tech Drona now runs as a single company ([ADR-0015](architecture-decisions/ADR-0015-single-company.md)); the college/B2B features described in this document (college portal and coordinators, institution contracts and seats, invitations and roster import, per-organization settings, trusted networks and lab devices, the "For colleges" page) are removed. Roles are Admin (`super_admin`), Trainer, Evaluator, Content manager and Student; finance, support, security and mentor duties belong to Admin. Batches are Tech Drona cohorts managed by Admin at `/admin/batches`; businesses use the corporate enquiry form at `/enquiries`. The `/orgs/**`, invitation, contract and seat endpoints are removed; batches move to `GET/POST /batches`; AI/app settings become platform settings (`/admin/ai-settings`, `/admin/apps`); a public `POST /public/enquiries` endpoint is added. The regenerated `apps/web/openapi/openapi.json` is authoritative for paths. Where this document conflicts, ADR-0015 and [`single-company/REMOVAL-PLAN.md`](single-company/REMOVAL-PLAN.md) §8 win.

| Field | Value |
|---|---|
| Owner | Backend Lead (wave 2) |
| Date | 2026-11-03 |
| Status | **Partially Implemented** (Stage 10, 2026-11-03). Each catalogue row now carries a **Status** column: **Implemented** = the route exists in `apps/api` (verified against the generated OpenAPI, `TD_ROUTER_SET=all`), **Implemented (added)** = route added during implementation and back-filled here, **Planned** = not built. Nothing is marked Deployed. Test evidence per module is tracked in `docs/implementation-status.md`. Summary and gaps: §28. |
| Binding contracts | `docs/blueprint-brief.md` **v0.3** (v0.4 in progress; §1 decisions, §2 modules, §3 roles, §5 API conventions), `docs/contract-reconciliation.md` §7, and the applied change requests in `docs/integration-pass-requests.md` (IPR-API-*) and `docs/consistency-pass-requests.md` (CPR-API-*). Where any other document disagrees, these win. |
| Inputs | `database-schema.md` (column names, enums, CHECKs), `system-architecture.md` (§5 request lifecycle, §6 auth, §8 assessments, §9 coding, §11 commerce, §12 media), `role-permission-matrix.md` (permission keys and scopes), `product-requirements.md` (FR IDs, screen IDs), `account-security-and-risk-engine.md`, `account-unblock-workflow.md`, `analytics-event-schema.md` §5 (ingest contract), `privacy-and-data-retention.md`, `source-requirements-excerpt.md` (Section H) |
| OpenAPI | **The OpenAPI 3.1 document will be generated from the FastAPI code** (`/api/v1/openapi.json`, served only to staff in non-production; exported to `packages/api-client` for the Next.js BFF). The generated document **must match this specification**. A CI contract test diffs the generated OpenAPI against the route catalogue in §4–§24 (method, path, permission, route tag, idempotency flag, error codes) and fails on any undocumented route or any route missing from the code. Changes to the API are made here first, then in code. |

## Changelog

### v0.3.1 — 2026-11-03 (audit fix wave 3, documentation sync)

Back-fills the API changes made by the Phase B audit fixes (`docs/audit/fixes/*.md`), each checked against `apps/api` code. Changed entries are marked **(audit fix)** in their rows.

- **Conventions and errors:** §1.1 now says unknown fields → `400 validation_failed` (matches §1.13/§2.1 and `app.core.errors`, BE-33). §1.6: `passkey` is no longer advertised (TOTP only until WebAuthn exists; students also `sms_otp`/`email_otp`; password only as a student's last resort; break-glass uses TOTP). §2.1 `mfa_enrolment_required` widened to students of orgs with `require_mfa_students`, default `enrol_url` `/app/settings/security/mfa`. §2.1 `503 maintenance` is now enforced (exemptions `/admin/`, `/auth/`, `/webhooks/`; 30 s flag cache; fails open); §28.4 item 3 resolved.
- **New routes:** CAT-21b `GET /studio/resources`; PLC-02b `GET /studio/topics`; LRN-16b `GET /assignment-submissions/{id}/files/{file_index}`; ASM-03b `GET /studio/assignable-tests`; SUP-04b `GET /support/tickets/{id}/attachments/{ref}/{index}`; SEC-48 `GET /security/reports/exports`; SEC-49 `POST /security/restrictions/{id}/manual-verification`; COD-24 `GET /studio/coding/problems/published`.
- **Changed routes/fields:** CAT-08 (ADM-41 batch trainers see their batch orgs' private courses); lesson types `pdf`/`practice_set` and studio lesson `topics`; PLC-04 `q`/`version_status`/`retired_reason`; PLC-09/10 SoD for editors; LRN-02/11 `cursor`/`limit`; rubric schema (LRN-14/15/17), `raw_score`/`late_penalty_pct`; ASM-03 and ATT-13 signed cursors (`page`); ASM-04 `batch_id`; ASM-07 `RuleIn.coding_problem_id` and `question_types: ["coding"]`; ATT-12 `your_submission`; COD-03/04/05/06 `attempt_id` (COD-04/05 now Implemented), COD-08 batch readers; COM-04/05 `resumed`/`checkout`; COM-09 `billing`; COM-25 `status` filter and `approval_request_id`; COM-26 `202` envelope; COM-32 reason `price_adjustment`; ORG-06/07/14/15/19 (`member_type`, cursors, invite domains, `email_domain_not_allowed`); MED-02 purpose `support_attachment`; SUP-01/04 `attachments`, `related_attempt_id`, `Category` enum (SUP-01..15 status corrected to Implemented); SEC-31/32/47 (ADM-01/05/06/10); ANL-06/07 report fields.
- §25 and §28 counts were **not** recomputed for these additions.

### v0.3 — 2026-11-03 (Stage 10 integration, documentation sync)

- **Status column** added to every route catalogue (§4–§24), derived from the FastAPI routes (`create_app()` OpenAPI dump, 361 operations + `/healthz`). Result: **353 of 470** spec'd endpoints Implemented (incl. WH-01/02 via the shared provider route), **117 Planned**; **10 routes added** during implementation and back-filled as new catalogue rows (§28.2).
- **New catalogue rows (10):** COD-23 studio problem detail; COM-47 revenue report; COM-48/49 finance approval approve/reject; RBAC-07/08 RBAC approval approve/reject (interim until ADM-14/15 decide `rbac.*` actions); SEC-47 security export download; UNB-19 unblock form metadata; UNB-20 unblock status by `APL-` reference; SYS-06 `/healthz` (root, outside `/api/v1`).
- **Webhooks (§18):** implemented as a single route `POST /api/v1/webhooks/{provider}` accepting `razorpay` and `cashfree` (anything else → `404 not_found`); WH-03 (`ses`) and WH-04 (`sms-dlr`) are Planned. A hidden `GET /webhooks/{provider}/health` exists (not in OpenAPI).
- **Errors (§2):** added `405 method_not_allowed` and `500 internal_error` (framework-level, emitted by `app.core.errors`). Request-schema failures are returned as **`400 validation_failed`** (FastAPI `RequestValidationError` is mapped to 400, not 422). `503 maintenance` is defined in the code catalogue but **no maintenance-mode gate is wired yet** (§28.4).
- **Field rename:** `attempt_closed` problem details carry **`attempt_status`** (not `status`, which is the RFC 9457 HTTP status member) plus `deadline_at` (§2.3, §15).
- **Event name:** the assessments module emits **`attempt.scored`** on the outbox (not `attempt.graded`); analytics stores it as `assessment.attempt_scored` (`analytics-event-schema.md` §2.4).
- **Counts (§25)** updated to 480 catalogued endpoints (470 + 10 new IDs). New §28 Implementation status.

### v0.2.1 — 2026-11-03 (Security Specialist, final cleanup)

- **I-26 resolved:** export approval split by report family. `security.export.per_user` (H1–H9, H12, per-user device/login history) is approved by a **second `security_reviewer`** holding `report.export.approve`; `export.bulk_pii` (H10/H11 aggregates, finance, college reports, bulk PII > 10,000 rows) by `super_admin`; approver ≠ requester in both (§1.7, SEC-32, ANL-13, role matrix v0.4).

### v0.2 — 2026-11-03 (Backend Lead, consistency pass)

Applied all 20 integration-pass requests (IPR-API-01..20) and all 16 security consistency-pass requests (CPR-API-01..16). Where the two request files differ, the security decision (no age-based webhook rejection) is used and the difference is recorded in §27.

- **Principal gate and sessions (§1.2, §1.4):** `pending_session_choice` added to the session states and to `login_continuation` (IPR-API-10, CPR-API-01, CPR-API-12). Gate steps follow RE §1.4/§1.6/§7.2: Redis-then-Postgres lookup, `idle_hold_until`, cookie replay revokes **this session only** (TO-04/TO-08) plus a takeover evaluation. New mandatory **idle effect** per route (`x-td-idle`: `extends` / `engaged_only` / `neutral`) (CPR-API-02). Scope is derived per request; L3-deferral scope rule (CPR-API-03). Canonical route tags are the §1.4 set, declared in any module.
- **CSRF (§1.2, §1.3):** `td_csrf` is minted and checked by the BFF only, keyed with `TD_CSRF_KEY` (IPR-API-15).
- **Transport (§1.1):** BFF-only error tunnel `POST /api/v1/_errors` (IPR-API-17).
- **Errors (§2):** added `503 maintenance` (IPR-API-16), `401 remember_invalid` (CPR-API-08), `409 session_too_short_for_attempt` (CPR-API-10), `400 webhook_signature_invalid`; `second_approval_required` now carries `approval_request_id`; L2 `device_verification_required` wording (CPR-API-10). Confirmed: `409 playback_conflict`, `401 step_up_required`, `403 mfa_enrolment_required`, `202 approval_pending`; `pending_session_choice` is a session status, not an error code.
- **Identity (§4):** new AUTH-28 `POST /auth/remember/refresh` (BFF-only) (CPR-API-08); session-cap flow with same-device replacement and attempt-holding sessions never evicted (CPR-API-12); hard-disable behaviour (CPR-API-15).
- **Security (§6, §7):** pending second approvals of case decisions are `approval_requests` (`security.case.decision`): SEC-09 `202` returns `approval_request_id` and no `decision_id`; SEC-10/SEC-11 re-pathed to the approval request; new SEC-11a withdraw (CPR-API-04). New SEC-42 kill switch, SEC-43 engine state, SEC-44/45 bulk false-positive lift, SEC-46 "This wasn't me" (CPR-API-05, CPR-API-09). Report ids H1–H12 + `ENG` follow RE §10 (CPR-API-07). Permission keys: `report.export.request` / `report.export.approve`, `security.network.verify`, `security.incident.read` / `security.incident.manage`, `policy.propose` (IPR-API-01..08). UNB-01 CAPTCHA removed (CPR-API-13).
- **Attempts (§15):** autosave max interval 10 s (IPR-API-11); `session_too_short_for_attempt` and `idle_hold_until` on start; same-device re-attach without a rebind (CPR-API-11).
- **Commerce and webhooks (§17, §18):** `product_kind` vocabulary (IPR-API-12) and order statuses (IPR-API-13); goodwill and high-value refunds always use `approval_requests` (IPR-API-14). Webhooks: canonical path `/api/v1/webhooks/{provider}`; HMAC + event-id dedupe + provider re-fetch for every state-changing event; **no age-based rejection**; signature failures are `AB-12` (CPR-API-06, IPR-API-20).
- **Analytics (§20):** ANL-01 max 100 events, no permission key (ownership) (IPR-API-09); ingest limits referenced from `analytics-event-schema.md` §5.2 (CPR-API-16); ANL-13 uses `report.export.request` (IPR-API-02). `ORG-30` and `COM-37` also moved off the retired `report.export`.
- **Admin (§24):** ADM-09 uses `policy.propose`; approvals require `report.export.approve` / `policy.edit` / `approval.decide` by action type (IPR-API-04, -08); AUD-05 uses `report.export.request` (IPR-API-03).
- **Mapping and issues (§25–§27):** counts updated (AUTH 28, SEC 47, total 470); `FR-SEC-002` split into `-002a`/`-002b` (IPR-API-18); every §27 issue now has a status and pointer (IPR-API-19, CPR-API-14); new issues I-26, I-27.

### v0.1 — 2026-11-03 (Backend Lead)

Initial specification (wave 2).

---

## Contents

1. Conventions (transport, auth, CSRF, principal gate, permissions, step-up, dual control, idempotency, pagination, rate limits, versioning, errors, formats)
2. Error catalogue (`code` values)
3. How to read an endpoint entry
4. Identity and authentication (`identity`) — AUTH, ME
5. Sessions and devices (`sessions`) — SES
6. Account security administration (`security`) — SEC
7. Unblock requests (`security`) — UNB
8. Organizations, batches, memberships, invitations, imports (`orgs`) — ORG
9. RBAC (`rbac`) — RBAC
10. Catalog and authoring (`catalog`) — CAT
11. Media (`media`, playback sessions owned by `sessions`) — MED
12. Learning, progress, assignments, certificates (`learning`) — LRN
13. Placement preparation (`placement`) — PLC
14. Assessments: tests, assignments, overrides, results (`assessments`) — ASM
15. Assessment attempts (`assessments`) — ATT
16. Coding (`coding`) — COD
17. Commerce (`commerce`) — COM
18. Payment and provider webhooks — WH (incl. Razorpay webhook specification)
19. Entitlements (`entitlements`) — ENT
20. Analytics ingest, reports and exports (`analytics`) — ANL
21. Notifications (`notifications`) — NTF
22. Support (`support`) — SUP
23. Privacy and data-principal rights (`admin` privacy sub-package) — PRV
24. Audit (`audit`) and platform administration (`admin`) — AUD, ADM, SYS
25. Endpoint counts
26. Endpoint → FR → screen mapping
27. Issues for Integration Lead
28. Implementation status (Stage 10)

---

## 1. Conventions

### 1.1 Base path, transport, media types

| Item | Rule |
|---|---|
| Base path | `/api/v1` on the **same origin** as the web app (`https://app.techdrona.in/api/v1/...`). The browser calls the Next.js BFF route handler at that path; the BFF forwards to the FastAPI `api` service (and the ALB routes `/api/v1/webhooks/*` directly to the `api-webhooks` service). |
| BFF-only routes | `POST /api/v1/_errors`: browser error-event tunnel to the self-hosted GlitchTip (ADR-0014). Implemented in the Next.js BFF, **not a FastAPI route** (not in the OpenAPI document); no cookies are forwarded to GlitchTip; 60/min per IP; payload scrubbed of PII before forwarding. `POST /api/v1/auth/remember/refresh` (AUTH-28) is a FastAPI route but is called only by the BFF. |
| Format | JSON, UTF-8, `snake_case` field names, `Content-Type: application/json`. Errors use `application/problem+json` (§1.13). Uploads never go through the API body: the API issues S3 presigned POSTs or VdoCipher upload credentials. |
| Request body | Pydantic v2 models with `extra="forbid"` (unknown fields, like every other schema failure, → `400 validation_failed` with `errors[]`; §1.13, §2.1. `422 validation_failed` is reserved for well-formed but semantically invalid input that a module rejects explicitly). `organization_id` in a body is never trusted for authorization; it must match the path or the principal's grant (role matrix TI-11). |
| Body size | 256 KiB default; 64 KiB for code source (`COD-06/07`) and analytics batches (`ANL-01/02`); larger payloads → `413 payload_too_large`. |
| Responses | Single resources are returned as the object. Lists return `{"data": [...], "page": {...}}` (§1.10). Every response carries `X-Request-Id` (also echoed in problem bodies as `request_id`). Authenticated responses carry `Cache-Control: no-store`. |
| Methods | `GET` never changes state. `POST` creates or performs an action; `PATCH` partially updates (JSON Merge Patch semantics); `PUT` replaces a whole sub-document (draft outline, preferences); `DELETE` removes or revokes. |
| Timestamps | RFC 3339 UTC with `Z` and millisecond precision (`2026-11-03T10:15:02.123Z`). Dates shown to users in IST are formatted by the client. Daily rollups use the Asia/Kolkata calendar day (`date` fields are IST dates, `YYYY-MM-DD`). |
| Money | Integer **paise** (`amount_paise`), currency `INR`. Never floats. GST components are explicit (`cgst_paise`, `sgst_paise`, `igst_paise`). |
| IDs | UUIDv7 strings for internal ids. Human references keep their formats: `SEC-YYMM-XXXXXX` (case), `APL-YYMM-XXXXXX` (unblock request), `PRV-YYMM-XXXXXX` (privacy request), `TD-O-YYYY-NNNNNNNN` (order), `TD-T-YYYY-NNNNNN` (ticket), certificate `public_code` (`^[A-Z0-9]{10,16}$`). |
| Enums | Exactly the `CHECK` vocabularies of `database-schema.md`; new values are additive and announced (§1.12). |

### 1.2 Authentication through the Next.js BFF

The browser never holds a bearer token (brief §1 Frontend).

| Credential | Where | Rule |
|---|---|---|
| `__Host-td_session` | Cookie set by the BFF on login | 256-bit random, base64url; `Secure; HttpOnly; SameSite=Lax; Path=/`; no `Domain`. The server stores only `SHA-256(token)` (`auth_sessions.token_hash`). Rotated on login, MFA completion, privilege change, password change and unblock re-verification. Never accepted from a URL or a header sent by the browser. |
| `__Host-td_device` | Cookie | 128-bit random browser-profile id; stored only as `HMAC-SHA256(k_device_v{key_version}, id)` (`devices.device_key_hash`, `devices.key_version`; re-hashed in place on lookup with an old version, RE §1.5). Issued on the first visit to an authenticated surface. A session presented with a different device cookie than it was created with (TO-04), or with a `ua_family`/`os_family` drift (TO-08), is revoked — **this session only** (`device_mismatch`, status `blocked`) — and a takeover evaluation runs → `401 session_revoked` (RE §4.3, §6.2). All sessions are revoked only on HC-T3. |
| `__Host-td_remember` | Cookie | Remember-device credential (students, trusted devices only). Stored as `user_devices.remember_token_hash`; rotated on every use; `remember_until` fixed at the last full authentication and never slides. Used only by AUTH-28 (RE §1.4 rule 5). |
| `td_csrf` | Cookie (not HttpOnly) | Signed double-submit token: `HMAC(TD_CSRF_KEY, session_id_hash ‖ nonce)`, **minted and validated by the BFF (`web`)**; the `api` service does not issue or check `td_csrf` and never holds the key (ADR-0010 v0.3). |
| BFF → API | Internal headers | `Authorization: Service <bff token>` (rotated via Secrets Manager), `X-TD-Session`, `X-TD-Device`, `X-TD-Client-IP`, `X-Request-Id`, `traceparent`. The API trusts `X-TD-Client-IP` only when the service token is valid (`ServiceAuthMiddleware`). These headers are **not** part of the browser-facing contract and are stripped if sent by a browser. |
| Mobile apps (later) | — | Opaque rotating refresh token + short-lived access token (architecture §6.1). Out of scope for v1; not specified here. |

**Session states.** `auth_sessions.status` ∈ `pending_mfa`, `pending_device_otp`, `pending_session_choice`, `active`, `expired`, `revoked`, `blocked`; `auth_sessions.scope` ∈ `full`, `restricted` (L3), `status_only` (L4) — a record only: enforcement derives scope per request from the restriction state (§1.4). A `pending_*` session may call only routes tagged `login_continuation` (§1.4). `pending_session_choice` is held for at most 5 min while the session-cap chooser is shown (AUTH-06, AUTH-14). Postgres is the session source of truth; the Redis `cache` cluster is a read-through copy.

**Timeouts** (server-authoritative; `idle_expires_at`, `absolute_expires_at`): `student` 60 min / 24 h, `staff` 30 min / 12 h, `privileged` 15 min / 8 h; registered college lab devices 30 min idle, no remember-device. `__Host-td_session` carries `Max-Age` = seconds until `absolute_expires_at` (lab devices: browser-session cookie). Only engaged activity extends the idle timer: every authenticated route declares an idle effect (`x-td-idle`: `extends`, `engaged_only`, `neutral`; §1.4); keepalives, polling and prefetches never extend it. An in-progress timed attempt holds the session until `idle_hold_until = deadline_at + grace + 5 min`. Absolute timeouts are never extended. **Remember device** (students, trusted devices): a new AAL1 session is re-issued silently only on a top-level user navigation, through AUTH-28, within a fixed 30-day ceiling from the last full authentication that never slides; background requests never re-issue a session (RE §1.4).

**Public (unauthenticated) routes** are explicitly tagged `public`: signup, verification links, login and recovery, invitation preview, guardian consent, catalog/SEO reads, product listing, certificate verification, public contact/grievance form, status, webhooks (HMAC instead of a session), health.

### 1.3 CSRF and Fetch Metadata

| Route class | Requirement |
|---|---|
| Every state-changing request (`POST`, `PUT`, `PATCH`, `DELETE`) except the two below | Header `X-CSRF-Token` equal to the `td_csrf` cookie **and** valid HMAC for the current session (or for the pre-session nonce on public auth forms); **and** `Sec-Fetch-Site` ∈ {`same-origin`, `none`} when present. Failure → `403 csrf_failed`. Checked by the BFF (which holds `TD_CSRF_KEY`); the `api` service accepts state-changing browser traffic only through the BFF hop (service token, §1.2) and does not re-validate `td_csrf` (ADR-0010 v0.3). |
| `POST /api/v1/analytics/events/beacon` (ANL-02) | `navigator.sendBeacon` cannot set headers: the signed CSRF token travels in the body field `csrf` and is validated by the BFF, and `Sec-Fetch-Site: same-origin` is **required** (absent → reject). |
| `POST /api/v1/webhooks/*` (WH) | No cookie, no CSRF: provider HMAC signature over the raw body (§18). Not routable through the BFF. |
| `GET` | No CSRF (GET never changes state). |

### 1.4 `require_active_principal` and route tags

One FastAPI dependency, `require_active_principal`, is mounted on **every authenticated router** (`core.routing.authenticated_router()`); it is never opted into per route. It performs, in order (security doc §7.2, architecture §6.3):

1. Read `__Host-td_session` (via BFF header). Missing → `401 unauthenticated`.
2. Load `sess:{sha256(token)}` from the Redis `cache` (read-through copy); on a miss, look up `auth_sessions` in Postgres (source of truth). Unknown in **both** Redis and Postgres → `401 unauthenticated` (counted as AB-07).
3. Idle or absolute expiry passed → session ended (`idle_timeout` / `absolute_timeout`) → `401 session_expired`. Idle expiry is **not** enforced while `now < auth_sessions.idle_hold_until` (in-progress timed attempt); absolute expiry always is.
4. Device cookie hash ≠ session device (TO-04) or `ua_family`/`os_family` drift (TO-08) → revoke **this session only** (`device_mismatch`, status `blocked`), takeover evaluation → `401 session_revoked`.
5. `users.sessions_valid_after > session.created_at`, session `revoked`/`blocked`, or user `deactivated`/`deleted` → `401 session_revoked`.
6. Session `pending_mfa` / `pending_device_otp` / `pending_session_choice` and route not tagged `login_continuation` → `401 login_incomplete` (body names the pending step).
7. **Scope gate** by route tag (table below), with scope derived for this request from the current restriction state (`restr:{uid}`). Denied → `403 account_restricted` with `case_ref`, `level`, `until`.
8. Staff/privileged tier without an enrolled MFA factor and route not tagged `mfa_enrolment` → `403 mfa_enrolment_required`.
9. Required consent missing (e.g. new notice version of `terms`/`privacy_notice`) and route not tagged `consent` or `account_status` → `403 consent_required`.
10. Slide the idle timer only for routes with `x-td-idle: extends`; `engaged_only` routes slide it through `sessions.touch_engaged()` when the server credits engagement; `neutral` never. Write `last_seen_at` at most every 60 s.
11. Return `Principal(user_id, session_id, device_id, org_ids, tier, scope, aal, amr, auth_time, last_step_up_at, restriction_level, is_minor, privacy_tier)`.

**Route tags** (declared in the router as `openapi_extra={"x-td-route-tag": ...}`, in any module; a CI test enumerates `app.routes` and fails if any authenticated route lacks the dependency, a tag or an idle effect). The canonical tag set is exactly `public`, `login_continuation`, `account_status`, `l3_readonly`, `mfa_enrolment`, `consent`, `default` (RE §7.2; the architecture doc's `restriction_class` naming is retired):

| Tag | Callable by session scope | Used for |
|---|---|---|
| `public` | No session required | §1.2 list |
| `login_continuation` | `pending_mfa`, `pending_device_otp`, `pending_session_choice`, and `full`/`restricted`/`status_only` | MFA verify, device OTP, session-cap choice, logout |
| `account_status` | `full`, `restricted`, `status_only` | `GET /me`; own devices and sessions (list, revoke, remove); own security status, cases and unblock requests; privacy and consent; billing view, invoices, subscription cancel, refund requests; support tickets; notifications inbox; logout; unblock re-verification |
| `l3_readonly` | `full`, `restricted` | Read-only dashboard, enrolments, progress, certificate list, own results (L3 keeps read-only progress; brief §5) |
| `mfa_enrolment` | any non-pending scope | MFA factor enrolment for staff who have no factor yet |
| `consent` | any non-pending scope | Consent read/grant |
| `default` (untagged in tables: `—`) | `full` only | Everything else, including playback, attempts, practice, coding, checkout, staff consoles |

`status_only` (L4) sessions additionally cannot call `l3_readonly` routes. Contact changes (ME-03/04) are tagged `default`, so they are blocked in `restricted` and `status_only` scope (unblock doc §8). Data export (DSAR, PRV) is `account_status`; the certificate list is `l3_readonly`.

**Scope is derived per request** (`auth_sessions.scope` is a record only). During an L3 deferral (`deferred_until`, §15.1) the attempt-bound session keeps `full` scope for that attempt's `ATT-*` routes only, until submit or `deferred_until`; all other sessions of the user are revoked immediately (`risk_L3`) (RE §7.2, §7.4; AMB-20, AMB-21).

**Idle effect** (`openapi_extra={"x-td-idle": ...}`, **required on every authenticated route**; CI-checked together with the route tag; RE §1.4):

| `x-td-idle` | Effect | Routes |
|---|---|---|
| `extends` | Slides `idle_expires_at` | State-changing user actions (default for every non-GET route not listed below); `GET` page-data requests marked by the BFF with `X-TD-Activity: navigation` (set only from `Sec-Fetch-Mode: navigate` or an App Router client navigation; never for `Sec-Purpose: prefetch`) |
| `engaged_only` | Slides idle only when the server credits engagement in this request, via `sessions.touch_engaged(session_id)` | `ANL-01`/`ANL-02` ingest (batch credited > 0 active seconds); playback heartbeat `MED-05` with `state = playing` and the position advanced; `ATT-06` autosave with at least one changed response |
| `neutral` | Never slides idle | Keepalives, notification polling and SSE (`NTF-*` polling), `SEC-01` polling, session-status checks, prefetches, background refreshes, idempotent replays |

`X-TD-Activity` is accepted only on the BFF→API hop (service token) and is stripped by the BFF from browser requests; a client cannot extend idle by setting a header.

**Entitlement gating is separate.** Content routes call `entitlements.check` (§19); at restriction level ≥ L3 it returns `ACCOUNT_RESTRICTED` for every resource class except `account_status`. Security never revokes entitlements; it gates them.

### 1.5 Authorization: permission + scope, ownership, tenant isolation

- Every endpoint declares **one permission key** (from `role-permission-matrix.md` §2) and a **scope resolver**, or `S` (ownership: `resource.user_id == principal.user_id`), or `public`. Allow-only, deny by default. A principal passes if it holds a non-expired, non-revoked `role_grants` row whose role includes the permission at any scope in the resource's scope chain (`platform` ⊃ `organization:{id}` ⊃ `batch:{id}`; `course:{id}` separate axis).
- Scope notation in this document: `@P` platform, `@O` organization (from path or resource), `@B` batch, `@C` course, `S` self/ownership, `S|perm@X` "owner, or holder of perm at X".
- **Cross-tenant ids return `404 not_found`, never `403`** (TI-02), and the attempt is recorded as a security signal. `403 permission_denied` is returned only when the object is visible to the principal but the action is not allowed.
- Uniqueness conflicts never reveal another tenant's data (TI-05): invites to an existing email return the same `201` as a new invite.
- Postgres RLS (`FORCE`) is the tenant boundary underneath; it is not used as object authorization.
- Every staff read of another user's personal data is audited (`audit_log`, permission used, `reason_code` where required).

### 1.6 Step-up MFA

Freshness is `now − auth_sessions.last_step_up_at` (step-up via passkey or TOTP; SMS/email OTP accepted **only for students**, never for staff or privileged tiers).

> **Implementation (audit fix, SEC-09/SEC-11):** WebAuthn passkeys are not built, so `passkey` is **not advertised**: `allowed_methods` is `["totp"]` for staff and `["totp", "sms_otp", "email_otp"]` for students in the `step_up_required` problem. AUTH-19 returns the methods actually usable by the account (`totp` only with a confirmed factor; students `email_otp` when they have an email and `sms_otp` with a verified mobile). `password` is offered only to a student account with no other usable method. Break-glass (ADM accounts), admin and org-lifecycle step-ups use **TOTP** until passkeys exist. Exception: the remember-device re-auth on SES self-service device sign-out (`sessions/router.py`) still advertises `["password", "totp"]`.

| Window | Applies to | Column in tables |
|---|---|---|
| **5 min** | Privileged actions regardless of the actor's tier: refund decisions, role grants/revokes, policy changes, case decisions and L3/L4 restriction apply/lift, rule activation, MFA reset, bulk/per-user exports, price/coupon/contract/entitlement-grant changes, break-glass (passkey only by design; **TOTP until passkeys are built**, SEC-11), approvals | `P5` |
| **10 min** | Other staff sensitive actions (`Up` keys in the role matrix): session kills and device resets by support, attempt invalidation, released-grade change, certificate revocation, PII report export by coordinators/trainers, org suspension request | `S10` |
| **15 min** | Student self-service: email/phone change, MFA factor changes, recovery codes | `U15` |

Window values are policy keys `auth.step_up_window.privileged|staff|student`. When freshness is missing the API returns:

```http
HTTP/1.1 401 Unauthorized
Content-Type: application/problem+json
X-Request-Id: 01JC9V6R3W0ZK8M5N2Q4T7Y1AB

{
  "type": "https://techdrona.in/problems/step-up-required",
  "title": "Please confirm it's you",
  "status": 401,
  "code": "step_up_required",
  "detail": "This action needs a fresh confirmation.",
  "request_id": "01JC9V6R3W0ZK8M5N2Q4T7Y1AB",
  "step_up": {
    "max_age_seconds": 300,
    "allowed_methods": ["totp"],
    "options_url": "/api/v1/auth/step-up/options"
  }
}
```

The session itself stays valid (this 401 never clears cookies). The client runs `AUTH-19` → `AUTH-20` and retries the original request **with the same `Idempotency-Key`**.

### 1.7 Dual control (second-person approval)

Actions marked **Dual** (role matrix §5) do not execute immediately. The endpoint validates the request, writes an `approval_requests` row (`payload_hash` over the minimised payload, `expires_at = created_at + 72 h`) and returns:

```http
HTTP/1.1 202 Accepted
{
  "status": "approval_pending",
  "approval_request_id": "0193a1c2-7d4e-7b10-9a55-2f6e1d0c9b31",
  "action_type": "policy.change",
  "required_approver_role": "super_admin",
  "expires_at": "2026-11-06T10:15:00.000Z"
}
```

An approver holding the approval permission for that action type (never the requester; `ck_apr_distinct`) approves with `ADM-14` (step-up `P5`); the system executes the stored payload exactly (hash re-verified) and marks the request `executed`. Changing the payload requires a new request. Approval permission by `action_type` (role matrix §2.7, §5):

| `action_type` | Approver permission | Decided through |
|---|---|---|
| `security.export.per_user` (security/monitoring exports: H1–H9, H12, per-user device/login history, per-user H11 rows from a case) | `report.export.approve` held by a **different `security_reviewer`** (≠ requester; `super_admin` cannot approve: no security-evidence access outside break-glass) | ADM-14/ADM-15 |
| `export.bulk_pii` (all other exports needing approval: H10/H11 aggregates, finance/commerce, college/coordinator and trainer reports, bulk PII > 10,000 rows) | `report.export.approve` (`super_admin`, ≠ requester) | ADM-14/ADM-15 |
| `policy.change` | `policy.edit` (`super_admin`, ≠ proposer) | ADM-14/ADM-15 |
| `security.case.decision` | `security.restriction.lift_l3l4` (second `security_reviewer`) or `approval.decide` (`super_admin`); ≠ requester, ≠ person who applied the restriction | **SEC-10/SEC-11** (not ADM-14) |
| `security.restriction.bulk_lift` | `approval.decide` (a different `security_reviewer` or `super_admin`) | ADM-14/ADM-15 |
| `risk.kill_switch.ratify` | `approval.decide` (a different `security_reviewer` or `super_admin`; ≠ the person who flipped the switch) | ADM-14/ADM-15 |
| every other Dual action (`risk.ruleset.activate`, refunds, contracts, MFA reset, …) | `approval.decide` for that action type | ADM-14/ADM-15 |

Security case decisions that need a second approver are stored as `approval_requests` (`security.case.decision`) and decided through SEC-10/SEC-11, not ADM-14.

### 1.8 Idempotency-Key

| Rule | Detail |
|---|---|
| Header | `Idempotency-Key: <8–128 printable ASCII>`; UUIDv4/UUIDv7 recommended (`idempotency_keys.idem_key` CHECK). |
| **Required** on | Every `POST` that creates a **money**, **attempt** or **submission** record, and **unblock-request** creation/submission. In this document: orders, order confirmation, subscriptions, refunds (request and decision), credit notes, price creation, contracts and contract invoices, manual entitlement grants/revokes, seat assignment, attempt start/rebind/submit, code run/submit, assignment submissions, practice sessions, mentor bookings and résumé-review requests (consume paid quota), unblock create/submit/respond/appeal, case decisions and their approvals, kill switch, bulk lifts, privacy requests, security exports. Column `Idem` = **Req**. Missing → `400 idempotency_key_required`. |
| **Accepted** (optional) | Any other `POST`. Column `Idem` = `opt`. |
| **Exempt** | `POST /analytics/events` and `/analytics/events/beacon`: idempotent per event (`event_id` UUIDv7, `ON CONFLICT DO NOTHING`); the header is ignored. Autosave (`ATT-06`) is idempotent by `(attempt_id, question_version_id, client_seq)`; the header is ignored. Webhooks dedupe on the provider event id. |
| Scope and storage | `(user_id, route_key, idem_key)` in `idempotency_keys` with `request_hash = SHA-256(canonical JSON body ‖ path params)`. TTL 24 h; **7 days** for money routes (COM, ENT grants, refunds). Redis lock `idem:{...}` serialises concurrent duplicates. |
| Replay, same body | Returns the stored status and body with header `Idempotency-Replayed: true`. |
| Same key, different body | `409 idempotency_key_reuse`. |
| Original still running | `409 idempotency_in_progress` with `Retry-After: 1`. |
| Failed original | 5xx results are **not** stored (the client may retry with the same key); 4xx results are stored and replayed. |
| Step-up / dual | A `401 step_up_required` is not stored; the retry with the same key proceeds. A `202 approval_pending` **is** stored; replay returns the same approval request. |

### 1.9 Optimistic concurrency

Mutable administrative resources (tests in draft, policy settings, cases, unblock requests, contracts, coupons, course drafts) return `ETag: "v<version>"`. State transitions on cases and unblock requests (`SEC-05..11`, `UNB-12..15`) **require** `If-Match`; missing → `428 precondition_required`; stale → `412 version_conflict`. Elsewhere `If-Match` is optional.

### 1.10 Pagination, filtering, sorting

- Cursor pagination only: `?cursor=<opaque>&limit=<1..100>` (default 25). The cursor is a base64url, HMAC-signed encoding of the sort key + id; tampered or expired (24 h) cursors → `400 invalid_cursor`.
- Response: `{"data": [...], "page": {"next_cursor": "eyJrIjoi...", "has_more": true, "limit": 25}}`. No total counts on large tables; queue endpoints may add `"counts": {...}` computed from indexed aggregates.
- Filters are explicit query parameters documented per endpoint; sort is `?sort=<field>` or `?sort=-<field>` from an allowlist per endpoint.

### 1.11 Rate limiting

Redis token buckets (cache cluster), keyed by user, session, IP (BFF-forwarded client IP), ASN, destination (OTP) or provider quota, as stated per endpoint. Registered campus ranges (`org_trusted_networks`) and known CGNAT ASNs get ×10 on per-IP limits (security §3.2). Responses carry the IETF `RateLimit` structured headers:

```http
RateLimit-Policy: "user";q=60;w=60, "session";q=30;w=60
RateLimit: "session";r=12;t=34
```

On breach: `429 rate_limited` (or the more specific code listed per endpoint) with `Retry-After: <seconds>`. Login throttling uses `429 throttled` with identical message and timing for unknown and known identifiers (FR-IDN-005). Pre-auth blocks never increment an account's failure counter.

Default limits when an endpoint does not state one: authenticated `GET` 120/min/user; authenticated writes 60/min/user; public `GET` 300/min/IP; public `POST` 20/min/IP.

Analytics ingest limits (`ANL-01`/`ANL-02`: per-session/user/IP rates, batch size, heartbeat cadence, page-instance limits) have a **single source**: `analytics-event-schema.md` §5.2. The values repeated in §20 are informative; if they differ, §5.2 wins (the threat model no longer states its own values).

### 1.12 Versioning and deprecation

- Major version in the path (`/api/v1`). Within v1 only additive changes: new endpoints, new optional request fields, new response fields, new enum values (clients must tolerate unknown enum values and unknown fields).
- Breaking changes require `/api/v2` for the affected resources, with ≥ 6 months overlap. Deprecated endpoints send `Deprecation` and `Sunset` headers and a `Link: <...>; rel="deprecation"`.
- Analytics event payloads are versioned separately (`schema_version`, `measurement_version: tm-1.0`); risk rules by `ruleset_version`; tests by `test_version`; coding problems by `problem_version`; review policy and scoring by `scoring_version`.

### 1.13 Problem details (RFC 9457)

Every error is `application/problem+json` with at least `type`, `title`, `status`, `detail`, `code`, `request_id`. Extension members are listed per code. Validation errors add `errors: [{"field": "explanation", "code": "too_short", "message": "..."}]`. Stack traces, SQL and internal ids of other tenants are never returned. `title` and `detail` are safe to show to the user.

```json
{
  "type": "https://techdrona.in/problems/account-restricted",
  "title": "Account access paused",
  "status": 403,
  "code": "account_restricted",
  "detail": "Learning access is paused until 2026-11-04T10:15:00+05:30.",
  "request_id": "01JC9V8Z0M7T3X4Q6B2N5R8KDE",
  "case_ref": "SEC-2611-7KQ4MZ",
  "level": 3,
  "until": "2026-11-04T04:45:00.000Z",
  "status_url": "/app/account-status"
}
```

---

## 2. Error catalogue (`code` values)

`type` is `https://techdrona.in/problems/<code with - instead of _>`. Codes are stable; titles may be localised.

### 2.1 Generic and authentication

| HTTP | `code` | When | Extension members |
|---|---|---|---|
| 400 | `validation_failed` | Body/query fails schema (also 422 for semantically invalid but well-formed input; see below) | `errors[]` |
| 422 | `validation_failed` | Well-formed but semantically invalid (e.g. window end before start) | `errors[]` |

> **Implementation note (v0.3):** schema failures detected by FastAPI (`RequestValidationError`) are always returned as `400 validation_failed` with `errors[]`; `422` is used only where a module raises it explicitly for semantic checks.
| 400 | `invalid_cursor` | Bad or expired pagination cursor | — |
| 400 | `idempotency_key_required` | Required header missing | — |
| 409 | `idempotency_key_reuse` | Same key, different request hash | — |
| 409 | `idempotency_in_progress` | Original request still running | `Retry-After` |
| 401 | `unauthenticated` | No or unknown session | — |
| 401 | `session_expired` | Idle/absolute timeout | `reason` (`idle_timeout`/`absolute_timeout`) |
| 401 | `session_revoked` | Revoked (logout elsewhere, cap eviction, device mismatch, security action, password change) | `reason` (an `auth_sessions.end_reason`, user-safe subset) |
| 401 | `login_incomplete` | Pending session calls a non-continuation route | `next_step` (`mfa`, `device_verification`, `session_choice`) |
| 401 | `step_up_required` | Step-up freshness missing (§1.6) | `step_up{max_age_seconds, allowed_methods, options_url}` |
| 401 | `invalid_credentials` | Wrong identifier or password (identical for unknown users and for hard-disabled accounts, including timing) | — |
| 401 | `remember_invalid` | AUTH-28: remember token unknown, expired (`now ≥ remember_until`), superseded (→ TO-10), device not trusted, restriction ≥ L3, or T-protect lock | — |
| 403 | `csrf_failed` | CSRF/Fetch-Metadata check failed | — |
| 403 | `permission_denied` | Visible object, action not allowed | `permission` (key) |
| 403 | `mfa_enrolment_required` | Staff tier without a confirmed MFA factor, **and** (audit fix, FR-ORG-002) an active student of an active organization with `require_mfa_students` on who has no confirmed factor. Every non-exempt route returns it; MFA enrolment, login continuation and public routes stay open. Students of such orgs who already have a factor are asked for it at login | `enrol_url` (default `/app/settings/security/mfa`, used for staff and students) |
| 403 | `consent_required` | Required consent/notice version missing | `purposes[]`, `notice_version` |
| 403 | `contact_not_verified` | Action needs verified email/mobile (purchase, timed test) | `missing` (`email`/`mobile`) |
| 403 | `minor_consent_pending` | Under-18 without verified guardian consent | `guardian_flow_url` |
| 403 | `reason_code_required` | Evidence/PII view without `reason_code` | `allowed_reason_codes[]` |
| 403 | `sod_violation` | Separation of duties (author = publisher, requester = approver, role exclusivity, own case) | `rule` (e.g. `SoD-10`) |
| 403 | `conflict_of_interest` | Reviewer applied the restriction, shares a device, same org, prior contact | — |
| 404 | `not_found` | Unknown **or cross-tenant** id | — |
| 409 | `invalid_state_transition` | Action not allowed in current state | `current_state`, `allowed[]` |
| 412 | `version_conflict` | `If-Match` stale | `current_etag` |
| 428 | `precondition_required` | `If-Match` required but missing | — |
| 413 | `payload_too_large` | Body over limit | `max_bytes` |
| 415 | `unsupported_media_type` | Wrong content type / file type | `allowed[]` |
| 429 | `rate_limited` | Generic limit | `Retry-After` |
| 429 | `throttled` | Login/OTP back-off (identical for unknown users) | `Retry-After` |
| 202 | *(not an error)* `approval_pending` | Dual control (§1.7) | — |
| 503 | `service_unavailable` | Dependency down (judge, gateway, VdoCipher) and no queueing possible | `Retry-After` |
| 503 | `maintenance` | Feature flag `platform.maintenance_mode` is on: every non-`GET`/`HEAD`/`OPTIONS` request returns `503 maintenance` with `Retry-After: 300`, **except** paths under `/api/v1/admin/` (incl. break-glass), `/api/v1/auth/` and `/api/v1/webhooks/` (webhooks are **not** refused) and anything outside `/api/v1` (`/healthz`). **(audit fix, ADM-17; `app.core.middleware.MaintenanceMiddleware`)** The flag is read through `admin.flags.cached_flag_enabled` (own short DB transaction, cached 30 s per process; a flag PATCH clears the local cache at once, other processes within 30 s). A flag-read failure **fails open** (writes allowed, logged) | `Retry-After` |
| 405 | `method_not_allowed` | **(v0.3)** HTTP method not supported on an existing path (framework 405 mapped to the catalogue) | — (`Allow` header kept) |
| 500 | `internal_error` | **(v0.3)** Unhandled exception or any un-catalogued 5xx; framework detail is never echoed; logged with `request_id` | — |

### 2.2 Security, sessions and devices

| HTTP | `code` | When | Extension members |
|---|---|---|---|
| 403 | `account_restricted` | Session scope `restricted`/`status_only` calls a non-allowed route; entitlement denied by L3/L4 | `case_ref`, `level`, `until`, `status_url` |
| 403 | `account_protect_locked` | T-protect lock (takeover): recovery required | `recovery_url` |
| 403 | `device_verification_required` | L2: this device (including a previously verified device that appears in the L2 evidence) must re-verify by SMS OTP, passkey or TOTP before playback/attempt start; email OTP not accepted | `verify_url` |
| 409 | `session_too_short_for_attempt` | Attempt start (ATT-01) when `absolute_expires_at < deadline_at + grace + 5 min` | `reauth_url`, `required_until` |
| 409 | `session_cap_reached` | Login/activation at `sessions.student.max_concurrent` with `prompt_choose` (the new session is `pending_session_choice` for ≤ 5 min), or every other session holds an active attempt (no eviction) | `sessions[]` (id, device label, approximate state, last active, `has_active_attempt`), `max_concurrent` |
| 409 | `device_cap_reached` | New device would exceed `devices.student.max_trusted` | `devices[]`, `max_trusted`, `replacements_used`, `replacements_max`, `next_replacement_at` |
| 409 | `device_replacement_quota_exhausted` | Self-service replacements used up in rolling 30 days | `next_replacement_at`, `support_url` |
| 409 | `playback_conflict` | Stream cap: another playback session is active (brief §5) | `other_device_label`, `other_playback_session_id`, `takeover_allowed` |
| 410 | `playback_revoked` | Heartbeat on an ended/revoked playback session | `end_reason` |
| 400 | `otp_invalid` / `otp_expired` | Wrong / expired code | `attempts_remaining` |
| 429 | `otp_attempts_exceeded` | > `otp.max_verify_attempts` | — |
| 429 | `otp_send_limited` | Per-number hourly/daily cap or per-IP send cap | `Retry-After` |
| 409 | `decision_required` | Attempt to lift L3/L4 outside a case decision | `case_ref` |
| 409 | `second_approval_required` | Decision proposed as an `approval_requests` row (`security.case.decision`); waits for a distinct approver (no `case_decisions` row exists yet) | `approval_request_id` |
| 409 | `explanation_not_viewed` | Case decision before the reviewer opened explanation and timeline (unblock §7 guard rail) | — |
| 409 | `unblock_request_open` | One open request per case | `reference` |
| 429 | `unblock_rate_limited` | > 3 submissions per 30 days, or 5 form loads/min | `Retry-After` |
| 422 | `dlp_rejected` | Explanation contains password/OTP-like content | `hint` |
| 409 | `appeal_window_closed` / `appeal_already_used` | Second-level appeal not allowed | — |
| 409 | `shadow_period_incomplete` | Rule version activation before 14 days of shadow | `shadow_started_at`, `eligible_at` |
| 403 | `k_anonymity_floor` | Report cell/cohort below `analytics.k_min.*` (whole response suppressed) | `k_min` |

### 2.3 Assessments, coding, media

| HTTP | `code` | When | Extension members |
|---|---|---|---|
| 409 | `attempt_bound_elsewhere` | Attempt is bound to another session | `bound_device_label`, `bound_since`, `rebind_allowed`, `rebinds_remaining`, `otp_required`, `trainer_override_required` |
| 409 | `rebind_limit_reached` | `rebind_count` ≥ `assessment.max_rebinds_per_attempt` | — |
| 409 | `active_attempt_exists` | One in-progress attempt per test per user | `attempt_id` |
| 409 | `attempt_limit_reached` | `attempts_allowed` (+ overrides) exhausted | — |
| 409 | `test_not_open` / `test_window_closed` | Outside the availability window | `available_from` / `available_until` |
| 409 | `attempt_closed` | Write after `deadline_at + grace_seconds`, or attempt not `in_progress` | `deadline_at`, **`attempt_status`** (renamed from `status` in v0.3 — `status` is the RFC 9457 HTTP status member) |
| 409 | `section_locked` | Write to a section whose deadline passed or that was submitted (sequential/section-locked) | `section_id` |
| 409 | `test_settings_locked` | Edit after `settings_locked_at` | `locked_at` |
| 409 | `results_not_released` | Result/review before the release phase | `release_mode`, `release_at` |
| 409 | `judge_queue_full` | `run` shed under saturation (assessment submits are never shed) | `Retry-After` |
| 422 | `language_not_allowed` | Language not in `allowed_languages` | `allowed[]` |
| 409 | `submission_in_flight` | One in-flight `submit` per user | `submission_id` |
| 403 | `entitlement_required` | Access check denied (no/expired entitlement) | `reason_code` (FR-ENT-001), `purchase_options[]` |

### 2.4 Commerce and entitlements

| HTTP | `code` | When | Extension members |
|---|---|---|---|
| 409 | `already_owned` | BR-ENT-05 duplicate purchase | `source_type`, `ends_at` |
| 422 | `coupon_invalid` / `coupon_expired` / `coupon_cap_reached` / `coupon_not_applicable` | Coupon checks | — |
| 409 | `order_expired` | Order past `expires_at` (30 min) | — |
| 400 | `payment_signature_invalid` | Checkout callback HMAC fails | — |
| 400 | `webhook_signature_invalid` | Webhook HMAC over the raw body fails (§18; recorded as `AB-12`). Webhooks are never rejected for age | — |
| 409 | `refund_not_eligible` | Rule fails and no goodwill path requested | `reasons[]` (`window_passed`, `consumption_exceeded`, `certificate_issued`) |
| 422 | `recurring_amount_exceeds_mandate_limit` | Recurring price > ₹15,000 | `max_paise: 1500000` |
| 409 | `seat_pool_exhausted` | No free contract seat | `used`, `total`, `waitlist_allowed` |
| 409 | `reassignment_allowance_exhausted` | BR-ENT-16 | `used`, `allowance` |

---

## 3. How to read an endpoint entry

Each module section starts with a **catalogue table** listing every endpoint:

| Column | Meaning |
|---|---|
| ID | Stable endpoint id used in the mapping table (§26) and in the OpenAPI `operationId` suffix (`AUTH-06` → `auth_06_login`) |
| Method, Path | Path relative to `/api/v1` |
| Permission @ scope | Key from the role matrix; `S` ownership; `public`; `any` = any active principal |
| Step-up | `P5`, `S10`, `U15` or `—` (§1.6); `+Dual` when dual control applies (§1.7) |
| Idem | `Req`, `opt`, `exempt`, `—` (GET) (§1.8) |
| Tag | Route tag (§1.4): `PUB`, `LC` (login_continuation), `AS` (account_status), `L3R` (l3_readonly), `MFA` (mfa_enrolment), `CON` (consent), `—` (default: full scope only) |
| Rate limit | Per-endpoint limit when different from the default (§1.11) |

Endpoints that need more than the table carries get a **detail entry** with request/response JSON, errors and server-side enforcement notes. Full detail is given for security, unblock, assessment attempts, coding, commerce, webhooks and entitlements; other modules give representative schemas.

---

## 4. Identity and authentication (`identity`)

### 4.1 Catalogue — authentication (AUTH)

| ID | Method | Path | Summary | Permission @ scope | Step-up | Idem | Tag | Rate limit | Status |
|---|---|---|---|---|---|---|---|---|---|
| AUTH-01 | POST | `/auth/signup` | Self-signup (email or mobile + password or passkey), DOB age gate, itemised consents | public | — | opt | PUB | 5/h per IP+device; 3/day per contact | **Implemented** |
| AUTH-02 | POST | `/auth/verify/email` | Consume email verification link token | public | — | — | PUB | 20/h per IP | **Implemented** |
| AUTH-03 | POST | `/auth/verify/email/resend` | Resend verification email | any | — | opt | AS | 3/h per user | **Implemented** |
| AUTH-04 | POST | `/auth/verify/mobile/send-otp` | Send mobile verification OTP | any | — | opt | AS | `otp.sms.max_per_number_per_hour` 3, `per_day` 10 | **Implemented** |
| AUTH-05 | POST | `/auth/verify/mobile` | Verify mobile OTP | any | — | opt | AS | `otp.max_verify_attempts` 5 per OTP | **Implemented** |
| AUTH-06 | POST | `/auth/login` | Password login (email or mobile) | public | — | opt | PUB | per-IP 30/10 min (×10 campus/CGNAT), per-ASN, per-account back-off 1 s doubling to 900 s | **Implemented** |
| AUTH-07 | POST | `/auth/passkey/login-options` | WebAuthn assertion options for passkey login | public | — | — | PUB | 30/min per IP | Planned |
| AUTH-08 | POST | `/auth/passkey/login` | Passkey login | public | — | opt | PUB | as AUTH-06 | Planned |
| AUTH-09 | POST | `/auth/otp-login/send` | Send login OTP (students only; refused for staff tiers with the generic response) | public | — | opt | PUB | OTP send caps | Planned |
| AUTH-10 | POST | `/auth/otp-login/verify` | Verify login OTP | public | — | opt | PUB | 5 attempts per OTP | Planned |
| AUTH-11 | POST | `/auth/mfa/verify` | Complete a `pending_mfa` session (passkey, TOTP, recovery code; SMS OTP for students only) | any (pending) | — | opt | LC | 5 failures / 10 min | **Implemented** |
| AUTH-12 | POST | `/auth/device-verification/send` | Send new-device OTP to a verified channel | any (pending) | — | opt | LC | OTP send caps | **Implemented** |
| AUTH-13 | POST | `/auth/device-verification/verify` | Verify new-device OTP (or passkey/TOTP); trust device subject to caps | any (pending) | — | opt | LC | 5 attempts per OTP | **Implemented** |
| AUTH-14 | POST | `/auth/session-choice` | Resolve `session_cap_reached` (session in `pending_session_choice`, ≤ 5 min) by ending a chosen session or cancelling | any (pending) | — | opt | LC | 10/min | **Implemented** |
| AUTH-15 | POST | `/auth/logout` | End current session; `Clear-Site-Data` (device cookie re-set) | any | — | — | LC | — | **Implemented** |
| AUTH-16 | POST | `/auth/password/forgot` | Request reset link or mobile OTP (always the generic response) | public | — | opt | PUB | 5/h per IP; 3/h per identifier | **Implemented** |
| AUTH-17 | POST | `/auth/password/reset` | Reset with link token or OTP; revokes all sessions | public | — | opt | PUB | 10/h per IP | **Implemented** |
| AUTH-18 | POST | `/auth/password/change` | Change password (current password required; other sessions revoked by default) | any | — | opt | — | 5/h per user | **Implemented** |
| AUTH-19 | POST | `/auth/step-up/options` | Step-up challenge (WebAuthn options, allowed methods; students may request OTP) | any | — | — | AS | 10/min | **Implemented** |
| AUTH-20 | POST | `/auth/step-up` | Verify step-up; sets `auth_sessions.last_step_up_at` | any | — | opt | AS | 5 failures / 10 min | **Implemented** |
| AUTH-21 | POST | `/auth/reverify/start` | Unblock re-verification: OTP to a contact verified before the restriction | S | — | opt | AS | OTP send caps | **Implemented** |
| AUTH-22 | POST | `/auth/reverify/complete` | Finish re-verification (OTP, MFA, optional password reset, device review); revoke all sessions; end restriction | S | — | Req | AS | 5 attempts | **Implemented** |
| AUTH-23 | GET | `/auth/oidc/google/start` | Start "Sign in with Google" (students only, P1) | public | — | — | PUB | 30/min per IP | Planned |
| AUTH-24 | GET | `/auth/oidc/google/callback` | OIDC callback (state + PKCE + nonce) | public | — | — | PUB | — | Planned |
| AUTH-25 | GET | `/auth/guardian-consent/{token}` | Guardian views the notice and child details | public (token) | — | — | PUB | 20/h per IP | **Implemented** |
| AUTH-26 | POST | `/auth/guardian-consent/{token}/verify-contact` | OTP to the guardian's own contact | public (token) | — | opt | PUB | OTP send caps | **Implemented** |
| AUTH-27 | POST | `/auth/guardian-consent/{token}/decision` | Guardian consents or declines | public (token) | — | Req | PUB | 5/h | **Implemented** |
| AUTH-28 | POST | `/auth/remember/refresh` | Remember-device re-issue. Called **only by the BFF** on a top-level user navigation (`Sec-Fetch-Mode: navigate`, `Sec-Fetch-User: ?1`) when the session has expired and `__Host-td_remember` is present; issues a new session (`created_via = remember_device`, AAL1, rotated remember token) | public (BFF-internal; service token required) | — | opt | PUB | 10/min per device | **Implemented** |

### 4.2 Catalogue — self-service profile, consent and MFA (ME)

| ID | Method | Path | Summary | Permission @ scope | Step-up | Idem | Tag | Rate limit | Status |
|---|---|---|---|---|---|---|---|---|---|
| ME-01 | GET | `/me` | Current principal: user, profile, session (tier, scope, expiries), restriction summary, portals | `user.profile.read_self` S | — | — | AS | — | **Implemented** |
| ME-02 | PATCH | `/me/profile` | Update profile (name until legal-name lock, college text, graduation year, branch, target role/companies) | `user.profile.update_self` S | — | — | — | 30/h | **Implemented** |
| ME-03 | POST | `/me/contact-changes` | Start email/mobile change: OTP to new contact, notice to old contact | `user.profile.update_self` S | U15 | opt | — | OTP caps | Planned |
| ME-04 | POST | `/me/contact-changes/{change_id}/verify` | Verify new contact; revoke other sessions | `user.profile.update_self` S | U15 | opt | — | 5 attempts | Planned |
| ME-05 | GET | `/me/consents` | Current consent state per canonical purpose + notice versions | S | — | — | CON | — | **Implemented** |
| ME-06 | POST | `/me/consents` | Grant or withdraw a purpose (append-only `consents`) | S | — | opt | CON | 30/h | **Implemented** |
| ME-07 | GET | `/me/mfa/factors` | List factors (no secrets) | S | — | — | MFA | — | **Implemented** |
| ME-08 | POST | `/me/mfa/totp` | Begin TOTP enrolment (returns `otpauth://` URI once) | S | U15 for students; none for a staff member's first factor | opt | MFA | 5/h | **Implemented** |
| ME-09 | POST | `/me/mfa/totp/{factor_id}/confirm` | Confirm TOTP with a code | S | — | opt | MFA | 5 attempts | **Implemented** |
| ME-10 | POST | `/me/mfa/passkeys/options` | WebAuthn registration options | S | as ME-08 | — | MFA | 10/h | Planned |
| ME-11 | POST | `/me/mfa/passkeys` | Register passkey | S | as ME-08 | opt | MFA | 10/h | Planned |
| ME-12 | DELETE | `/me/mfa/factors/{factor_id}` | Remove a factor (staff cannot remove their last factor) | S | U15 / S10 / P5 by tier | — | — | 5/h | **Implemented** |
| ME-13 | POST | `/me/mfa/recovery-codes` | Generate 10 single-use recovery codes (shown once) | S | U15 / S10 / P5 by tier | opt | MFA | 3/day | **Implemented** |

### 4.3 Detail entries (identity)

#### AUTH-01 · POST `/auth/signup`

Request:

```json
{
  "full_name": "Ananya Reddy",
  "email": "ananya.reddy@example.com",
  "mobile": "+919876543221",
  "date_of_birth": "2006-04-12",
  "password": "correct-horse-battery-staple-17",
  "consents": [
    {"purpose": "terms", "notice_version": "2026-11-01", "granted": true},
    {"purpose": "privacy_notice", "notice_version": "2026-11-01", "granted": true},
    {"purpose": "core_service", "notice_version": "2026-11-01", "granted": true},
    {"purpose": "security_monitoring", "notice_version": "2026-11-01", "granted": true},
    {"purpose": "analytics_personalisation", "notice_version": "2026-11-01", "granted": false},
    {"purpose": "marketing_email", "notice_version": "2026-11-01", "granted": false}
  ],
  "invite_token": null
}
```

Response `201`:

```json
{
  "user_id": "0193a0f1-2b3c-7d4e-8f50-61a2b3c4d5e6",
  "status": "pending_verification",
  "is_minor": false,
  "next_steps": ["verify_email", "verify_mobile"],
  "session": {"status": "active", "scope": "full", "tier": "student", "idle_expires_at": "2026-11-03T11:15:00.000Z"}
}
```

Errors: `validation_failed` (`password_too_short` < 15 characters without MFA, `password_breached`, `password_too_long` > 128, `invalid_mobile`, `invalid_date_of_birth`), `throttled`, `consent_required` (missing `terms`, `privacy_notice` or `core_service`). An already-registered email or mobile returns the **same `201` shape** with `next_steps: ["check_email"]` and an out-of-band "you already have an account" message (no account enumeration).

Server-side enforcement: age computed from DOB on the signup date; age < 18 → `users.status = pending_guardian_consent`, `is_minor = true`, `next_steps: ["guardian_consent"]`; minors cannot grant `security_monitoring`, `analytics_personalisation`, `device_fingerprint`, `marketing_*` or `analytics_product` (stored as not granted). Unverified age is treated as minor (`is_minor` defaults to true until `age_verified_at`; self-declared DOB records `age_verification_method = self_declared`). `security_monitoring` is required before an adult buys a paid plan (PO-03), not at signup. Argon2id m=19456 KiB, t=2, p=1; breached-password blocklist incl. "techdrona", "drona". Issues `__Host-td_device` if absent. Unverified accounts may browse free content but cannot purchase or start a timed test (`403 contact_not_verified`).

#### AUTH-06 · POST `/auth/login`

Request: `{"identifier": "ananya.reddy@example.com", "password": "correct-horse-battery-staple-17", "remember_device": true}`

The session cookie is set in every non-error outcome; a pending session can call only `LC` routes.

| Outcome | HTTP | Body |
|---|---|---|
| Authenticated | 200 | `{"result": "authenticated", "session": {"id": "...", "tier": "student", "scope": "full", "idle_expires_at": "...", "absolute_expires_at": "..."}, "redirect": "/app"}` |
| Restricted (L3) / status-only (L4) | 200 | `{"result": "authenticated", "session": {"scope": "restricted", ...}, "restriction": {"level": 3, "case_ref": "SEC-2611-7KQ4MZ", "until": "..."}, "redirect": "/app/account-status"}` |
| MFA required (staff always; students with MFA; takeover step-up) | 200 | `{"result": "mfa_required", "methods": ["passkey", "totp", "recovery_code"]}` (`sms_otp` listed only for students) |
| New device | 200 | `{"result": "device_verification_required", "channels": [{"channel": "sms", "destination_masked": "+91 98xxxxxx21"}, {"channel": "email", "destination_masked": "a****@example.com"}], "alternatives": ["passkey", "totp"]}` |
| Session cap (`prompt_choose`) | 409 | `session_cap_reached` (example below) |
| Device cap (after OTP) | 409 | `device_cap_reached` (returned by AUTH-13) |
| Takeover protective lock | 403 | `account_protect_locked` with `recovery_url` |
| Wrong credentials / unknown user / hard-disabled | 401 | `invalid_credentials` (identical body and timing; see hard-disable below) |
| Throttled | 429 | `throttled` + `Retry-After` |

```json
{
  "type": "https://techdrona.in/problems/session-cap-reached",
  "title": "You're signed in on 2 devices",
  "status": 409,
  "code": "session_cap_reached",
  "detail": "Sign out of one device to continue here.",
  "request_id": "01JC9W1F7H5A2C9D3E6G8J0KLM",
  "max_concurrent": 2,
  "sessions": [
    {"session_id": "0193a2b1-0c3d-7e4f-8a90-b1c2d3e4f5a1", "device_label": "Chrome on Windows", "approx_region": "Telangana", "last_active_at": "2026-11-03T09:58:11.000Z", "has_active_attempt": false},
    {"session_id": "0193a2b1-0c3d-7e4f-8a90-b1c2d3e4f5b7", "device_label": "Android phone", "approx_region": "Telangana", "last_active_at": "2026-11-03T10:12:40.000Z", "has_active_attempt": true}
  ],
  "choice_url": "/api/v1/auth/session-choice"
}
```

Enforcement order (security doc §7.1): pre-auth IP/ASN windows and per-account back-off (pre-auth blocks never count toward `login.hard_disable_after_failures`, default 50) → Argon2id verify in a threadpool → resolve or issue the device cookie → restriction check (L4 → `status_only`, L3 → `restricted`, takeover lock → recovery) → TO-* rules (step-up when needed; minors get deterministic rules only, no score) → new device ⇒ OTP; trusted-device cap and replacement quota → concurrent-session cap under `pg_advisory_xact_lock` → rotate token, write `auth_sessions`, `login_attempts` and `audit_log`. `session_tier` = most privileged active grant.

Session cap (RE §6.3, §7.1; resolves I-08):
1. **Before** the cap check, other active sessions of this user on the same `device_id` (same `__Host-td_device`) end with `end_reason = replaced_same_device`; they do not count toward the cap. If one of them holds an in-progress attempt, the attempt is re-attached to the new session (no rebind consumed, no OTP; `attempt_events.reattach_same_device`).
2. At the cap with `sessions.student.at_limit_behavior = prompt_choose`: the new session moves to `pending_session_choice` (≤ 5 min, then `expired`) and the response is `409 session_cap_reached`; the chooser pre-selects the oldest session **without** an active attempt. `evict_oldest` (non-interactive clients) evicts only sessions without an active attempt. `deny` refuses.
3. Sessions holding an in-progress attempt are **never** evicted automatically (listed with `has_active_attempt: true`). If every other session holds an active attempt → `409 session_cap_reached` with no eviction option for those sessions.

Hard disable (`login.hard_disable_after_failures`, RE §3.2; FR-IDN-009; resolves I-21): the response stays `401 invalid_credentials`, identical to an unknown user including timing; an out-of-band email/SMS to the verified contact explains the pause and links to password reset; a successful password reset or MFA login clears the counter.

#### AUTH-13 · POST `/auth/device-verification/verify`

Request: `{"code": "482913"}`, or `{"method": "passkey", "assertion": {...}}`, optionally with `"remove_user_device_id": "0193..."` to free a slot during a pending login (no `full`-scope route is needed). Success `200` → the login pipeline continues with the session cap check. If trusted devices are at `devices.student.max_trusted` (default 3; lab devices excluded): `409 device_cap_reached` with the device list. Replacement quota exhausted → `409 device_replacement_quota_exhausted` with `next_replacement_at`. Errors: `otp_invalid`, `otp_expired`, `otp_attempts_exceeded`.

#### AUTH-14 · POST `/auth/session-choice`

Request `{"end_session_id": "0193a2b1-0c3d-7e4f-8a90-b1c2d3e4f5a1"}` or `{"cancel": true}`. Callable only by a session in `pending_session_choice`. Response `200` as AUTH-06 "authenticated" (the session moves to `active`). The ended session gets `end_reason = session_cap_evicted` and an SSE "You were signed out because…" event (NTF-10). Ending a session that holds an active attempt requires `"confirm_attempt_session": true` (an explicit user choice; never automatic). Errors: `not_found`, `invalid_state_transition` (no pending choice, or the 5-minute choice window expired → `401 session_expired` on the next call).

#### AUTH-28 · POST `/auth/remember/refresh`

BFF-internal (service token required; a browser cannot call it directly). The BFF calls it only when a top-level user navigation (`Sec-Fetch-Mode: navigate` and `Sec-Fetch-User: ?1`, or a click on the signed-out overlay) arrives with an expired or missing session and a `__Host-td_remember` cookie; never for XHR, heartbeats, beacons or prefetches. Request (BFF → API): `{"remember_token": "<cookie value>"}` plus the forwarded device cookie.

Response `200 {"result": "authenticated", "session": {"id": "...", "tier": "student", "scope": "full", "aal": 1, "created_via": "remember_device", "auth_time": "<original full authentication>", "idle_expires_at": "...", "absolute_expires_at": "..."}}`; the BFF sets the new `__Host-td_session` and the rotated `__Host-td_remember`. `auth_time` is copied from the original full authentication, so actions that need authentication within 24 h (payments, contact changes, device management, attempt start) still require a full login.

Preconditions (all must hold; RE §1.4 rule 5): student tier, not a lab device; `__Host-td_remember` matches `user_devices.remember_token_hash`; `now < remember_until` (fixed at the last full authentication, never slides); device still `trusted` with the same `device_key_hash`; restriction < L3; no T-protect lock; `remember_issued_at > users.sessions_valid_after`. Errors: `401 remember_invalid` (any precondition fails; a superseded remember token also revokes the remember credential and records TO-10).

#### AUTH-19 / AUTH-20 · Step-up

`AUTH-19` request `{"purpose": "refund.decide"}` → `200 {"allowed_methods": ["passkey", "totp"], "webauthn": {"challenge": "q8rT...", "rpId": "app.techdrona.in", "allowCredentials": [{"type": "public-key", "id": "AbC..."}], "userVerification": "required", "timeout": 60000}}`. Students may receive `["passkey", "totp", "sms_otp", "email_otp"]` and request an OTP with `{"purpose": "contact_change", "send_otp_via": "sms"}`.

`AUTH-20` request `{"method": "totp", "code": "731905"}` or `{"method": "passkey", "assertion": {...}}` → `200 {"last_step_up_at": "2026-11-03T10:15:02.123Z", "valid_for_seconds": {"privileged_action": 300, "staff_action": 600, "student_action": 900}}`. TOTP codes are single-use per 30 s step (`mfa_factors.totp_last_used_step`). Purpose `breakglass.activate` accepts passkey only. Errors: `otp_invalid`, `otp_attempts_exceeded`, `validation_failed` (`method_not_allowed_for_tier`).

#### AUTH-21 / AUTH-22 · Unblock re-verification (unblock doc §6)

Callable from a `restricted`/`status_only` session after a case decision put the restriction in `lift_pending`, or when an L3 reached `ends_at` (auto-expiry).

`AUTH-21` request `{"channel": "sms"}` → `200 {"sent_to": "+91 98xxxxxx21", "expires_in_seconds": 300}`. Only contacts verified **before** the restriction started are eligible; contacts changed within the 7 days before the restriction are refused (`409 invalid_state_transition`; `detail` says a senior reviewer will verify manually).

`AUTH-22` request:

```json
{
  "otp_code": "582014",
  "mfa": {"method": "totp", "code": "104882"},
  "new_password": null,
  "devices": [
    {"user_device_id": "0193a2c4-11aa-7bcd-9e01-23456789abd1", "keep": true},
    {"user_device_id": "0193a2c4-11aa-7bcd-9e01-23456789abd4", "keep": false}
  ]
}
```

Response `200 {"result": "reverified", "restriction_ended": true, "sessions_revoked": 3, "next": "login"}` with cookies cleared (all sessions revoked, `end_reason = unblock_reset`; remember-device tokens invalidated). Unconfirmed devices are removed without consuming replacement quota; lab devices untouched. Errors: `otp_invalid`, `validation_failed` (`password_reset_required` when the family is takeover or the decision requires it), `invalid_state_transition` (no lift pending). Entitlements were gated, not revoked, so access returns at the next full login. If the decision outcome is `lift_false_positive` and `unblock.false_positive_extension = true`, commerce extends time-bound entitlements by the restricted days (`entitlement_events.event_type = fp_extension`).

#### ME-01 · GET `/me` (representative)

```json
{
  "user": {"id": "0193a0f1-2b3c-7d4e-8f50-61a2b3c4d5e6", "email": "ananya.reddy@example.com", "email_verified": true, "mobile_masked": "+91 98xxxxxx21", "mobile_verified": true, "status": "active", "is_minor": false, "privacy_tier": "adult", "locale": "en-IN"},
  "profile": {"full_name": "Ananya Reddy", "graduation_year": 2027, "branch": "CSE", "legal_name_locked": false},
  "session": {"id": "0193a2b1-0c3d-7e4f-8a90-b1c2d3e4f5b7", "tier": "student", "scope": "full", "aal": 1, "idle_expires_at": "2026-11-03T11:15:02.000Z", "absolute_expires_at": "2026-11-04T10:15:02.000Z", "remember_device": true, "last_step_up_at": null},
  "restriction": {"level": 0},
  "portals": ["student"],
  "organizations": [{"id": "0192f7aa-5b6c-7d8e-9f01-a2b3c4d5e6f7", "display_name": "Vasavi College of Engineering", "membership": "student"}]
}
```

For an L3 user `restriction` is `{"level": 3, "scope": "learning_access", "case_ref": "SEC-2611-7KQ4MZ", "until": "2026-11-04T04:45:00.000Z", "explanation_keys": ["sh01.overlap_two_devices"]}`. It never contains evidence, scores, rule parameters or thresholds.

#### ME-06 · POST `/me/consents`

Request `{"purpose": "analytics_personalisation", "action": "granted", "notice_version": "2026-11-01"}` → `201 {"purpose": "analytics_personalisation", "state": "granted", "effective_at": "2026-11-03T10:15:02.123Z"}`. Withdrawing `security_monitoring` switches the account to deterministic-only mode (PO-03) and emits `consent.changed`; analytics deletes the security feed rows within 24 h. Minors attempting B, C, E, F or H → `403 permission_denied` (`detail`: not available for under-18 accounts). `assessment_integrity` takes `context_ref` (test id). Withdrawal is always possible, including from `restricted`/`status_only` sessions.

---

## 5. Sessions and devices (`sessions`)

### 5.1 Catalogue (SES)

| ID | Method | Path | Summary | Permission @ scope | Step-up | Idem | Tag | Rate limit | Status |
|---|---|---|---|---|---|---|---|---|---|
| SES-01 | GET | `/me/sessions` | Own sessions (M1 tier: device label, approx. state, own IP for current/recent, started, last active, logout time, duration, status, termination reason) | `session.read` S | — | — | AS | — | **Implemented** |
| SES-02 | DELETE | `/me/sessions/{session_id}` | Revoke one own session (`user_revoked_other`) | `session.revoke` S | — | — | AS | 20/h | **Implemented** |
| SES-03 | POST | `/me/sessions/revoke-others` | Revoke all other own sessions | `session.revoke` S | — | opt | AS | 10/h | **Implemented** |
| SES-04 | GET | `/me/devices` | Own devices with trust status, "probably this computer" grouping, replacement quota | `device.reset` S | — | — | AS | — | **Implemented** |
| SES-05 | PATCH | `/me/devices/{user_device_id}` | Rename device (`user_label`) | `device.reset` S | — | — | AS | 20/h | **Implemented** |
| SES-06 | DELETE | `/me/devices/{user_device_id}` | Remove a trusted device (revokes its sessions; counts as a replacement only if a new device is added within 30 d) | `device.reset` S | re-auth when a remember-device session's `auth_time` > 24 h | — | AS | 10/h | **Implemented** |
| SES-07 | GET | `/me/device-policy` | Effective published limits for this user (devices, sessions, streams, replacements, rebinds) | S | — | — | AS | — | **Implemented** |
| SES-08 | GET | `/me/login-history` | Own login attempts and ended sessions (90 days) | `session.read` S | — | — | AS | — | **Implemented** |
| SES-09 | GET | `/users/{user_id}/sessions` | Another user's sessions (M2: IP masked /24 or /48, approx. state) | `session.read` @P | — | — | — | 60/h; audited; `reason_code` required | **Implemented** |
| SES-10 | POST | `/users/{user_id}/sessions/revoke` | Admin kill of one or all sessions (`admin_kill`) | `session.revoke` @P | S10 (support) / P5 (privileged tier) | opt | — | 20/h | **Implemented** |
| SES-11 | GET | `/users/{user_id}/devices` | Another user's devices + replacement quota (M2) | `session.read` @P | — | — | — | audited; `reason_code` required | **Implemented** |
| SES-12 | POST | `/users/{user_id}/devices/{user_device_id}/reset` | Support device reset within quota (+1 per 30 d); beyond quota for security reviewers | `device.reset` @P / `device.reset.beyond_quota` @P | S10 / P5 | opt | — | 20/h | **Implemented** |
| SES-13 | POST | `/orgs/{org_id}/lab-devices/enrolment-links` | Create a one-time lab-enrolment link (coordinator) | `org.settings.update` @O | S10 | opt | — | 20/day | Planned |
| SES-14 | POST | `/lab-devices/enrol` | Called on the lab PC with the link token; marks this device `shared_organization_id` | `org.settings.update` @O | — | opt | — | 100/day per org | Planned |
| SES-15 | GET | `/orgs/{org_id}/lab-devices` | List registered lab devices | `org.settings.update` @O | — | — | — | — | Planned |
| SES-16 | DELETE | `/orgs/{org_id}/lab-devices/{device_id}` | Deregister a lab device | `org.settings.update` @O | S10 | — | — | — | Planned |

### 5.2 Detail entries (sessions)

#### SES-01 · GET `/me/sessions`

```json
{
  "data": [
    {"session_id": "0193a2b1-0c3d-7e4f-8a90-b1c2d3e4f5b7", "is_current": true, "status": "active", "device_label": "Chrome 130 on Windows", "device_class": "desktop", "approx_region": "Telangana", "ip": "49.36.112.18", "auth_method": "password+otp_sms", "login_at": "2026-11-03T08:01:10.000Z", "last_active_at": "2026-11-03T10:14:55.000Z", "logout_at": null, "duration_seconds": null, "end_reason": null},
    {"session_id": "0193a1ff-7a2b-7c3d-8e4f-5a6b7c8d9e0f", "is_current": false, "status": "revoked", "device_label": "Android phone", "approx_region": "Telangana", "ip": "106.208.0.0/24", "login_at": "2026-11-02T14:00:00.000Z", "last_active_at": "2026-11-02T15:20:00.000Z", "logout_at": "2026-11-02T15:21:03.000Z", "duration_seconds": 4863, "end_reason": "user_logout"}
  ],
  "page": {"next_cursor": null, "has_more": false, "limit": 25}
}
```

Covers every Section A field (source requirements) for the owner's view. The full IP is shown only for the current and the last 7 days of own sessions; older rows are /24 (IPv4) or /48 (IPv6).

#### SES-04 · GET `/me/devices`

```json
{
  "data": [
    {"user_device_id": "0193a2c4-11aa-7bcd-9e01-23456789abd1", "label": "Chrome on Windows", "user_label": "My laptop", "client_type": "web", "device_class": "desktop", "trust_status": "trusted", "counts_toward_cap": true, "first_seen_at": "2026-08-02T05:11:00.000Z", "last_used_at": "2026-11-03T10:12:40.000Z", "approx_region": "Telangana", "is_current": true, "group_hint": "probably_this_computer:g1"},
    {"user_device_id": "0193a2c4-11aa-7bcd-9e01-23456789abd2", "label": "Edge on Windows", "trust_status": "trusted", "counts_toward_cap": true, "group_hint": "probably_this_computer:g1", "is_current": false},
    {"user_device_id": "0193a2c4-11aa-7bcd-9e01-23456789abd9", "label": "Lab PC (Vasavi College)", "trust_status": "trusted", "counts_toward_cap": false, "is_current": false}
  ],
  "limits": {"max_trusted": 3, "trusted_counted": 2, "replacements_used_30d": 1, "replacements_max_30d": 2, "next_replacement_at": "2026-11-14T00:00:00.000Z", "inactivity_expiry_days": 90},
  "page": {"next_cursor": null, "has_more": false, "limit": 25}
}
```

Region is state-level only (never city). The ids returned are `user_devices` ids, never `device_key_hash` values.

#### SES-10 · POST `/users/{user_id}/sessions/revoke`

Request `{"session_id": null, "all": true, "reason_code": "ticket", "reason": "Ticket TD-T-2026-000481: user reports a lost phone"}`. Response `200 {"revoked": 2}`. Support agents need step-up within 10 min (brief §1; PRD CCP-13); audited (`admin_kill`). Errors: `step_up_required`, `reason_code_required`, `not_found`.

#### SES-12 · POST `/users/{user_id}/devices/{user_device_id}/reset`

Request `{"reason_code": "ticket", "reason": "Laptop replaced; self-service quota exhausted", "ticket_id": "0193a3d0-4e5f-7a6b-8c9d-0e1f2a3b4c5d"}`. Response `200 {"removed": true, "support_resets_used_30d": 1, "support_resets_max_30d": 1}`. A second support reset within 30 days → `409 device_replacement_quota_exhausted` (`detail`: needs a security reviewer); a `security_reviewer` uses the same endpoint under `device.reset.beyond_quota`. Support never sees full IPs or evidence (SoD-03).

---

## 6. Account security administration (`security`)

All `/security/*` staff routes are platform-scoped. Every per-user view of signals, timelines, graphs or evaluations requires `reason_code` ∈ {`case_review`, `appeal`, `takeover_investigation`, `qa_sample`} plus a `case_ref` or `ticket_id` (M3 tier), and writes an `audit_log` row (`security.view.*`). Full IPs are never in list responses: they are revealed one at a time through `SEC-16` (audited `pii.reveal`). Minors never appear in sharing views (no data exists); takeover views show their deterministic events only. Coordinators see aggregates only (`SEC-41`); finance never (SoD-01).

### 6.1 Catalogue (SEC)

| ID | Method | Path | Summary | Permission @ scope | Step-up | Idem | Tag | Rate limit | Status |
|---|---|---|---|---|---|---|---|---|---|
| SEC-01 | GET | `/me/security/status` | Own restriction level, scope, end time, student-facing reasons (explanation keys), open case refs, published policy numbers | `security.status.read` S, `security.reason.read` S | — | — | AS | — | **Implemented** |
| SEC-02 | GET | `/me/security/cases/{case_ref}` | Own case (student projection: level, status, student-visible notes, decision summary, appeal window) | `security.reason.read` S | — | — | AS | — | **Implemented** |
| SEC-03 | GET | `/security/cases` | Case queue (dashboard H1): filter by level, family, status, org, rule, SLA state, assignee, high-risk, repeat | `security.case.read` @P | — | — | — | — | **Implemented** |
| SEC-04 | GET | `/security/cases/{case_id}` | Case header, restriction, recommended level, high-risk reasons, SLA timers, history | `security.case.read` @P | — | — | — | `reason_code` required | **Implemented** |
| SEC-05 | POST | `/security/cases/{case_id}/claim` | Claim (conflict-of-interest check) | `security.case.assign` @P | — | opt | — | If-Match | **Implemented** |
| SEC-06 | POST | `/security/cases/{case_id}/assign` | Assign to a reviewer | `security.case.assign` @P | — | opt | — | If-Match | **Implemented** |
| SEC-07 | GET | `/security/cases/{case_id}/explanation` | Score breakdown by category, contributing signals (rule, version, points, decayed points, evidence summary), student-facing explanation preview; marks "explanation viewed" | `security.evidence.read` @P | — | — | — | `reason_code` required | **Implemented** |
| SEC-08 | POST | `/security/cases/{case_id}/notes` | Add internal or student-visible note (≤ 4,000 chars, ≤ 2 attachments) | `security.case.note` @P | — | opt | — | 60/h | **Implemented** |
| SEC-09 | POST | `/security/cases/{case_id}/decisions` | Record decision (`lift_false_positive`, `lift_with_warning`, `lift_conditions`, `uphold`, `convert_L4`, `reduce_level`) | `security.case.decide` @P (+ `security.restriction.lift_l3l4` / `apply_l3l4` when the outcome changes L3/L4) | **P5** | **Req** | — | If-Match; 30/h | **Implemented** |
| SEC-10 | POST | `/security/cases/{case_id}/approval-requests/{approval_request_id}/approve` | Second-person approval of a proposed decision (`approval_requests`, `security.case.decision`); inserts the final `case_decisions` row | `security.restriction.lift_l3l4` @P (second reviewer) or `approval.decide` @P (super_admin) | **P5** | Req | — | If-Match | **Implemented** |
| SEC-11 | POST | `/security/cases/{case_id}/approval-requests/{approval_request_id}/send-back` | Second reviewer returns the proposal with a note (approval `rejected`; unblock request → `under_review`) | as SEC-10 | P5 | opt | — | If-Match | **Implemented** |
| SEC-11a | POST | `/security/cases/{case_id}/approval-requests/{approval_request_id}/withdraw` | Requester withdraws a pending proposal (approval `cancelled`) | `security.case.decide` @P (requester only) | — | opt | — | If-Match | **Implemented** |
| SEC-12 | POST | `/security/cases` | Open a case manually (support escalation, integrity referral, manual) | `security.case.note` @P | — | opt | — | 30/h | **Implemented** |
| SEC-13 | GET | `/security/users/{user_id}/timeline` | User security timeline: logins, sessions (device label, /24 net, state), caps, signals, evaluations, restrictions, OTP outcomes, case events (report H12) | `security.evidence.read` @P | — | — | — | `reason_code` required | **Implemented** |
| SEC-14 | GET | `/security/users/{user_id}/concurrency` | Engaged 5-min buckets per device for selected IST days with overlaps (H3), via `analytics.feeds.get_engaged_buckets` | `security.evidence.read` @P | — | — | — | `reason_code`; max 14 days per call | **Implemented** |
| SEC-15 | GET | `/security/users/{user_id}/device-graph` | Device ↔ account graph, 1–2 hops, 30/90 days; linked accounts masked until opened (H2) | `security.evidence.read` @P | — | — | — | `reason_code` | **Implemented** |
| SEC-16 | POST | `/security/pii-reveals` | Reveal one full IP / raw value behind a masked evidence reference | `security.evidence.read` @P | S10 | opt | — | 30/h; `reason_code` + case/ticket required | **Implemented** |
| SEC-17 | GET | `/security/evaluations` | Risk evaluations for a user (`?user_id=&family=&from=&to=`) | `security.evidence.read` @P | — | — | — | `reason_code` | **Implemented** |
| SEC-18 | GET | `/security/evaluations/{evaluation_id}` | One evaluation record (security doc §9 shape) | `security.evidence.read` @P | — | — | — | `reason_code` | **Implemented** |
| SEC-19 | GET | `/security/restrictions` | Active/ended restrictions (H5); filters level, org, age, source | `security.status.read` @P | — | — | — | — | **Implemented** |
| SEC-20 | POST | `/security/restrictions` | Apply restriction manually (L1/L2 by support or reviewer; L3/L4 by reviewer through a case) | `security.restriction.apply_l1l2` @P / `security.restriction.apply_l3l4` @P | — / **P5** | Req | — | 30/h | **Implemented** |
| SEC-21 | POST | `/security/restrictions/{restriction_id}/lift` | Lift L1/L2 (support or reviewer). L3/L4 → `409 decision_required` | `security.restriction.lift_l1l2` @P | — | opt | — | 30/h | **Implemented** |
| SEC-22 | GET | `/security/rules` | Rule catalogue (key, family, category, description, explanation key, active version) | `security.rule.read` @P | — | — | — | — | **Implemented** |
| SEC-23 | GET | `/security/rule-versions` | Rule and ruleset versions (`?family=&status=`) | `security.rule.read` @P | — | — | — | — | **Implemented** |
| SEC-24 | POST | `/security/rule-versions` | Create draft version (semver, `definition` JSON) | `security.rule.propose` @P | — | opt | — | 20/day | **Implemented** |
| SEC-25 | POST | `/security/rule-versions/{version_id}/simulate` | Simulate on the last 30 days (async job) | `security.rule.simulate` @P | — | opt | — | 5/day | **Implemented** |
| SEC-26 | POST | `/security/rule-versions/{version_id}/start-shadow` | Move draft → `shadow` (records `shadow_started_at`) | `security.rule.propose` @P | — | opt | — | — | **Implemented** |
| SEC-27 | GET | `/security/rule-versions/{version_id}/shadow-report` | Level-distribution diff, newly flagged users (counts + masked ids), FP history vs active | `security.rule.read` @P | — | — | — | — | **Implemented** |
| SEC-28 | POST | `/security/rule-versions/{version_id}/activation-requests` | Request activation after ≥ 14 days shadow → dual approval by `super_admin` | `security.rule.publish` @P | **P5 +Dual** | Req | — | — | **Implemented** |
| SEC-29 | POST | `/security/rule-versions/{version_id}/rollback-requests` | Request re-activation of the previous version | `security.rule.publish` @P | **P5 +Dual** | Req | — | — | **Implemented** |
| SEC-30 | GET | `/security/reports` | Report catalogue H1–H12 + `ENG` (engine health) per RE §10, with access and export rules | `security.case.read` @P | — | — | — | — | **Implemented** |
| SEC-31 | GET | `/security/reports/{report_key}` | Run a Section H report (aggregate or per-user rows). **(audit fix)** Every view (H1–H12, `ENG`) is audited as `security.report_viewed` (ADM-10); filters are applied and echoed as `filters_applied` (ADM-06; the catalogue SEC-30 lists each report's filters; `to` = inclusive IST date; a naive date-time or bare date is IST, ADM-09); H12 without `user_id` → `422` | `security.case.read` @P (per-user rows also `security.evidence.read`) | — | — | — | 30/min; `reason_code` for per-user rows | **Implemented** |
| SEC-32 | POST | `/security/reports/{report_key}/exports` | Export CSV (watermarked); per-user rows need approval by a second `security_reviewer` holding `report.export.approve` (approver ≠ requester; §1.7 `security.export.per_user`); the job waits in `awaiting_approval`. **(audit fix, ADM-01)** A per-user report (H1, H2, H3, H5, H6, H9, H12) **always** goes to a second `security_reviewer` (`include_per_user_rows` no longer skips approval); aggregate exports drop identifying columns; `contains_pii` reflects the columns written; filters are validated before any approval is created | `report.export.request` @P | **P5** (+Dual for per-user rows) | Req | — | 10/day | **Implemented** |
| SEC-33 | GET | `/security/trusted-networks` | Proposed/verified trusted college networks queue | `security.network.verify` @P | — | — | — | — | **Implemented** |
| SEC-34 | POST | `/security/trusted-networks/{network_id}/decision` | Verify or reject (verifier ≠ proposer; max /16 IPv4; consumer mobile ASNs refused) | `security.network.verify` @P | S10 | opt | — | — | **Implemented** |
| SEC-35 | POST | `/orgs/{org_id}/trusted-networks` | Coordinator proposes CIDR/ASN with evidence (WHOIS / IT letter upload) | `org.settings.update` @O | S10 | opt | — | 20/day | **Implemented** |
| SEC-36 | GET | `/orgs/{org_id}/trusted-networks` | Coordinator views own org's networks and status | `org.settings.update` @O | — | — | — | — | **Implemented** |
| SEC-37 | GET | `/security/incidents` | Breach/incident register with CERT-In 6 h and DPB clocks | `security.incident.read` @P (security_reviewer, super_admin) | — | — | — | — | **Implemented** |
| SEC-38 | POST | `/security/incidents` | Open an incident (`INC-YYMM-XXXXXX`) | `security.incident.manage` @P | S10 | opt | — | — | **Implemented** |
| SEC-39 | PATCH | `/security/incidents/{incident_id}` | Update status, timeline, notification timestamps | `security.incident.manage` @P | S10 | — | — | If-Match | **Implemented** |
| SEC-40 | GET | `/security/dashboard` | SEC-001 widgets: queue health, restrictions, appeals, rule performance, device-policy events, login security, CGNAT watch | `security.case.read` @P | — | — | — | — | **Implemented** |
| SEC-41 | GET | `/orgs/{org_id}/security-summary` | Coordinator aggregate tile: restricted-student count, open cases count, trusted-network status (no per-student signals) | `security.status.read` @O | — | — | — | k-floor `analytics.k_min.cohort` | **Implemented** |
| SEC-42 | POST | `/security/engine/kill-switch` | Emergency move toward safety: `risk.mode` → `shadow`, all HC rules off, or one rule → `shadow`; takes effect ≤ 60 s; creates a `risk.kill_switch.ratify` approval request (ratify within 24 h; unratified → page, **no auto-revert**). Only moves toward shadow/off (else `409 invalid_state_transition`); moving toward enforcement is a Dual policy change | `security.engine.kill_switch` @P (single approver + post-hoc ratification; named exception to Dual) | **P5** | **Req** | — | 10/day | **Implemented** |
| SEC-43 | GET | `/security/engine/state` | `risk.mode`, `risk.hc.auto_restrict_enabled`, per-rule status (incl. `status_change_reason`), circuit-breaker state, pending ratifications | `security.rule.read` @P | — | — | — | — | **Implemented** |
| SEC-44 | POST | `/security/restrictions/bulk-lift-requests` | Bulk false-positive lift of engine-applied L3s by selector; `dry_run` returns counts; execution is Dual (`security.restriction.bulk_lift`) | `security.restriction.bulk_lift` @P | **P5** (+Dual when `dry_run = false`) | **Req** | — | 10/day | **Implemented** |
| SEC-45 | GET | `/security/restrictions/bulk-lift-requests/{bulk_lift_id}` | Status and per-case progress of a bulk lift | `security.restriction.bulk_lift` @P | — | — | — | — | **Implemented** |
| SEC-46 | POST | `/me/security/events/{event_ref}/disown` | "This wasn't me" on a cookie-replay or new-sign-in notice → HC-T3: all sessions revoked, forced password reset; returns the recovery URL | S | — | opt | AS | 5/h | **Implemented** |
| SEC-47 | GET | `/security/reports/exports/{export_job_id}` | Download an approved, completed security report export (CSV; requester only; expiry enforced; audited `export.download`). **(audit fix, ADM-05)** Response has `Content-Disposition: attachment` and `Cache-Control: no-store` | `report.export.request` (own job) | — | — | — (idle `neutral`) | — | **Implemented (added)** |
| SEC-48 | GET | `/security/reports/exports` | **(audit fix, ADM-05/INV-11, added)** The caller's own security report exports, newest first (`?limit=` 1..200, default 50; no cursor). Each entry: `export_job_id`, `report_key`, `report_id`, `status` (incl. `expired`), `contains_pii`, `row_count`, `approval_request_id`, `created_at`, `completed_at`, `download_expires_at`, `download_path` (`/security/reports/exports/{id}` once downloadable, else `null`). Response `{data}`. The requester is notified on approval execution (`security.export.ready`) and on rejection (`security.export.rejected`) | `report.export.request` (own jobs) | — | — | — (idle `neutral`) | — | **Implemented (added)** |
| SEC-49 | POST | `/security/restrictions/{restriction_id}/manual-verification` | **(audit fix, E2E-01, added)** Senior manual verification (unblock workflow §6.3a) when a lift decision finds no contact verified ≥ 7 days before the restriction (the request is `escalated`, reason `manual_verification_required`; the student's status shows `await_manual_verification`). Runs the shared restore-access procedure. Reviewer must differ from the decider/approver; `409` while the student can still re-verify by code | `security.case.decide` @P | **P5** | Req | — | — | **Implemented (added)** |

### 6.2 Detail entries (security)

#### SEC-01 · GET `/me/security/status`

```json
{
  "level": 3,
  "family": "sharing",
  "scope": "learning_access",
  "starts_at": "2026-11-03T04:45:00.000Z",
  "until": "2026-11-04T04:45:00.000Z",
  "deferred_until": null,
  "case_ref": "SEC-2611-7KQ4MZ",
  "reasons": [
    {"explanation_key": "sh01.overlap_two_devices", "text": "Video and tests were used at the same time on 2 devices on 4 different days."},
    {"explanation_key": "sh02.two_states", "text": "Those devices were in 2 different states at the same time."}
  ],
  "categories": ["concurrency", "device", "network"],
  "available_actions": ["request_review", "manage_devices", "contact_support"],
  "unblock_request": {"reference": null, "state": null},
  "policy": {"max_trusted_devices": 3, "max_concurrent_sessions": 2, "max_concurrent_streams": 1, "max_replacements_per_30d": 2},
  "history": [{"level": 1, "starts_at": "2026-10-21T08:00:00.000Z", "ended_at": "2026-10-25T02:00:00.000Z", "end_reason": "expired_reverified"}]
}
```

Never includes scores, rule weights, thresholds, raw signals, other users or full IPs (unblock doc §8: explanations name the behaviour, not the thresholds). Minors receive only deterministic-cap and takeover information.

#### SEC-03 · GET `/security/cases` (H1)

Query: `?status=open,under_review,escalated&level=3,4&family=sharing&sla_state=breaching&assignee=me&high_risk=true&org_id=&rule=SH-01&sort=sla_decision_due&cursor=&limit=50`.

```json
{
  "data": [
    {
      "case_id": "0193a4e5-6f70-7a81-9b2c-3d4e5f607182",
      "case_ref": "SEC-2611-7KQ4MZ",
      "family": "sharing",
      "level": 3,
      "recommended_level": 4,
      "priority": "high",
      "status": "under_review",
      "score": 82.4,
      "top_explanation_keys": ["sh01.overlap_two_devices", "sh09.hosting_asn", "sh11.shared_device_many_accounts"],
      "age_hours": 19,
      "sla_first_response_due": "2026-11-04T04:45:00.000Z",
      "sla_decision_due": "2026-11-06T04:45:00.000Z",
      "sla_state": "on_track",
      "assignee": {"user_id": "0192...", "display_name": "R. Iyer"},
      "organization_name": "Vasavi College of Engineering",
      "is_high_risk": true,
      "repeat_count": 1,
      "unblock_request": {"reference": "APL-2611-3HX9RB", "state": "under_review"}
    }
  ],
  "counts": {"open": 14, "under_review": 9, "escalated": 2, "sla_breaching": 1},
  "page": {"next_cursor": "eyJrIjoi...", "has_more": true, "limit": 50}
}
```

The list shows the student by internal id and organization name only; the name is shown on `SEC-04` after a `reason_code`.

#### SEC-09 · POST `/security/cases/{case_id}/decisions`

Headers: `Idempotency-Key`, `If-Match: "v7"`, `X-CSRF-Token`.

Request:

```json
{
  "unblock_request_id": "0193a5f6-0718-7293-a4b5-c6d7e8f90a1b",
  "outcome": "lift_false_positive",
  "resulting_level": 0,
  "rationale": "Both devices belong to the student (laptop + phone); overlaps were lecture video on laptop with notes on phone; second state explained by a hostel move documented in the request.",
  "student_summary": "We reviewed your request and found the activity was yours. Your access is restored once you finish the verification steps.",
  "conditions": {
    "user_exception": {"setting_key": "devices.student.max_trusted", "value": 4, "expires_at": "2027-02-01T00:00:00.000Z"}
  },
  "extension_days": 2,
  "false_positive_rule_keys": ["SH-01", "SH-02"]
}
```

Response `201` (single approver) or `202` (second approval required):

```json
{
  "decision_id": "0193a6a7-b8c9-7dda-8eeb-fc0d1e2f3a4b",
  "case_ref": "SEC-2611-7KQ4MZ",
  "outcome": "lift_false_positive",
  "requires_second_approval": false,
  "restriction": {"restriction_id": "0193a3...", "state": "lift_pending"},
  "unblock_request": {"reference": "APL-2611-3HX9RB", "state": "approved"},
  "next": "student_reverification"
}
```

When a second approver is needed **no `case_decisions` row is written**: the decision is stored as an `approval_requests` row (`action_type = security.case.decision`, `target_id = case_id`, full decision as `payload`, `payload_hash`, `expires_at = created_at + 72 h`; at most one pending per case, `ux_apr_case_decision_pending`), the unblock request and the case move to `escalated`, and the response is `202` (UNB §5.1):

```json
{
  "requires_second_approval": true,
  "approval_request_id": "0193a6a7-0000-7aaa-8bbb-ccccdddd0001",
  "expires_at": "2026-11-06T10:15:02.000Z",
  "unblock_request": {"state": "escalated"},
  "approval": {"required_role": "security_reviewer|super_admin", "excludes": ["requested_by", "applied_by"]}
}
```

There is no `decision_id` in this response; it is returned by SEC-10 when the decision is approved.

Errors: `step_up_required`, `idempotency_key_required`, `precondition_required`/`version_conflict`, `explanation_not_viewed` (the reviewer has not opened `SEC-07` and `SEC-13` for this case), `conflict_of_interest` (reviewer applied the restriction, is the subject, shares a registered device, same org or prior support contact), `invalid_state_transition` (case already decided/closed), `validation_failed` (`student_summary` < 50 characters, `user_exception` beyond bounds or > 180 days, `extension_days` without a lift outcome, `convert_L4` without rationale), `permission_denied` (support agent; L3/L4 outcome without `security.restriction.*_l3l4`).

Server-side enforcement:
- `requires_second_approval` is **computed**, never accepted from the client: true when the restriction is L4 and `security_cases.is_high_risk`; or the outcome overrides a `recommend_L4` with `lift_false_positive` while the score ≥ 90; or the conditions loosen a 🔒/cap setting beyond 2× its default or for > 90 days; or recovery changes a verified contact; or the reviewer had prior contact with the student; or the subject holds a staff role (L4 application on staff needs two reviewers).
- `convert_L4` is human-only; the engine can only recommend L4 (`ck_ar_l4_human`). Applying L4 revokes all sessions; the user can sign in only to a `status_only` session.
- Lift outcomes put the restriction into `lift_pending`; the restriction is ended only by `AUTH-22` (re-verification) and the unblock procedure (unblock doc §6). Signals behind a `lift_false_positive` get `suppressed_by_decision_id` and the rule's FP counter (H8) increments.
- `case_decisions` are append-only and hold **final** decisions only; `ck_cd_second` (`approved_by <> decided_by`), `ck_cd_approval_link` (`requires_second_approval` ⇒ `approval_request_id`) and the service rule (approver ≠ person who applied the restriction) all apply.
- Writes `audit_log` (`case.decide`, `reason_code = case_review`), outbox `restriction.lifted` (when ended), notifications per unblock doc §4.2.

#### SEC-10 · POST `/security/cases/{case_id}/approval-requests/{approval_request_id}/approve`

Request `{"note": "Agree: owner verified both devices; hostel move documented."}` → `200 {"decision_id": "...", "approval_request_id": "...", "decided_by": "0192...", "approved_by": "0192...", "approved_at": "...", "unblock_request": {"state": "approved"}, "restriction": {"state": "lift_pending"}}`. In one transaction: the stored payload hash is re-verified, the approval request moves to `approved` → `executed`, and the `case_decisions` row is inserted with `decided_by` = requester, `approved_by` = approver, `approval_request_id`; the restriction then follows the outcome (lift → `lift_pending`; `uphold` → request `rejected`). Errors: `sod_violation` (approver = requester or applied the restriction), `conflict_of_interest`, `invalid_state_transition` (approval request `expired`, `cancelled` or already decided), `step_up_required`, `not_found` (approval request not for this case).

#### SEC-11 / SEC-11a · send back, withdraw

`SEC-11` request `{"note": "Please confirm the second location with the student first."}` → `200 {"approval_request_id": "...", "status": "rejected", "unblock_request": {"state": "under_review"}}`; no decision row exists. `SEC-11a` (requester only) → `200 {"approval_request_id": "...", "status": "cancelled"}`; the case stays `escalated` until a new proposal or decision. Errors on both: `invalid_state_transition` (approval request `expired`, `cancelled` or already decided), `sod_violation` (SEC-11 by the requester), `permission_denied` (SEC-11a by anyone other than the requester), `step_up_required` (SEC-11). A pending proposal not decided within 72 h becomes `expired`; the case stays `escalated`, an SLA-breach alert fires and the requester must re-propose.

#### SEC-13 · GET `/security/users/{user_id}/timeline` (H12 device and login history)

Query: `?reason_code=case_review&case_ref=SEC-2611-7KQ4MZ&from=2026-10-04&to=2026-11-03&types=login,session,cap,signal,evaluation,restriction,otp,case`.

```json
{
  "subject": {"user_id": "0193a0f1-...", "is_minor": false, "privacy_tier": "adult", "restriction_level": 3},
  "events": [
    {"at": "2026-11-02T14:05:00.000Z", "type": "signal", "rule": "SH-01", "rule_version": "1.0.0", "category": "C", "base_points": 15, "decayed_points": 14.1, "evidence": {"device_a": "dev_7f2c", "device_b": "dev_c21a", "overlap_buckets": 7, "net_a": "AS55836:/16", "net_b": "AS24560:/16", "region_a": "TG", "region_b": "MH"}},
    {"at": "2026-11-02T13:58:41.000Z", "type": "session", "session_id": "0193...", "device_label": "Chrome on Windows", "net": "49.36.112.0/24", "asn": 55836, "network_type": "mobile", "region": "TG", "status": "active", "auth_method": "password"},
    {"at": "2026-11-02T13:58:40.000Z", "type": "login", "outcome": "success", "method": "password", "mfa_method": null, "device_label": "Chrome on Windows", "net": "49.36.112.0/24", "evidence_ref": "la_0193a7..."},
    {"at": "2026-11-01T09:12:00.000Z", "type": "otp", "purpose": "new_device_otp", "outcome": "abandoned"},
    {"at": "2026-11-03T04:45:00.000Z", "type": "restriction", "level": 3, "source": "engine", "evaluation_id": "0193..."}
  ],
  "page": {"next_cursor": null, "has_more": false, "limit": 200}
}
```

IP fields are /24 (IPv4) or /48 (IPv6); `evidence_ref` values can be passed to `SEC-16` to reveal the full value. Without `reason_code` → `403 reason_code_required`.

#### SEC-16 · POST `/security/pii-reveals`

Request `{"evidence_ref": "la_0193a7c2", "field": "ip", "reason_code": "case_review", "case_ref": "SEC-2611-7KQ4MZ"}` → `200 {"field": "ip", "value": "49.36.112.18", "asn": 55836, "network_type": "mobile", "revealed_at": "...", "audit_id": "0193..."}`. Audited as `pii.reveal`; included in the reviewer-lift-rate QA sample.

#### SEC-20 · POST `/security/restrictions`

Request:

```json
{
  "user_id": "0193a0f1-2b3c-7d4e-8f50-61a2b3c4d5e6",
  "level": 4,
  "family": "sharing",
  "case_id": "0193a4e5-6f70-7a81-9b2c-3d4e5f607182",
  "rationale": "Reseller pattern: hosting ASN, 5 device tokens in 24 h, devices shared with 8 accounts; prior confirmed L3 on 2026-09-14.",
  "ends_at": null
}
```

Response `201 {"restriction_id": "...", "level": 4, "scope": "status_only", "starts_at": "...", "deferred_until": null, "sessions_revoked": 2}`. Rules: L1/L2 need no case; L3/L4 require `case_id`; L4 requires `rationale` and a human actor (`source = reviewer`); L4 on a staff account requires a second reviewer (returns `202` with an approval on the case); for minors, sharing-family restrictions are refused (`422 validation_failed`, `minor_sharing_not_permitted`) — minors' L3/L4 only via a human case with guardian/college notification under the `takeover` family or a documented resale case (FR-SEC-007). A sharing L3 is **deferred** while the user has an in-progress attempt (max 3 h, `deferred_until`); takeover restrictions are immediate. Errors: `step_up_required`, `permission_denied` (support for L3/L4), `invalid_state_transition` (an active restriction of the same family exists; one active per family).

#### SEC-28 · POST `/security/rule-versions/{version_id}/activation-requests`

Request `{"reason": "Lower SH-01 base points for owner-verified overlaps; FP rate 12% in October.", "effective_from": "2026-11-20T20:30:00.000Z"}` → `202 approval_pending` (§1.7, `action_type = risk.ruleset.activate`, `required_approver_role = super_admin`). Preconditions: status `shadow`; `now − shadow_started_at ≥ 14 days` else `409 shadow_period_incomplete`; shadow report present; proposer ≠ approver (`ck_rrv_approval`). On approval the version becomes `active`, the previous one `retired`; restrictions already in force are not changed retroactively and are queued for re-review if the new version would not have produced them.

#### SEC-31 · GET `/security/reports/{report_key}` — Section H reports

The twelve report ids follow the verbatim Section H list of the source requirements, and the security doc §10 now uses the **same** numbering (RE §10; resolves I-15). Engine health is `ENG`.

| Report | `report_key` | Content | Source | Per-user rows? | RE §10 view |
|---|---|---|---|---|---|
| H1 Top suspicious accounts | `top-suspicious-accounts` | Open cases by priority then SLA; HC rule (if any), top explanation keys, repeat flag; second tab: adults with the highest current score without an open case | `security_cases`, latest `risk_evaluations` | yes | H1 Suspicious-activity queue |
| H2 Multiple-account/device associations | `account-device-associations` | Devices used by ≥ N accounts in 7/30 days, lab flag, linked restricted accounts (masked); per-user graph = SEC-15 | `user_devices`, `devices`, `security_signals` | yes (masked ids) | H2 Device–account graph |
| H3 Concurrent login events | `concurrent-login-events` | Days/users with overlapping engaged sessions on ≥ 2 devices with separation class (S0–S3); session-cap hits; stream conflicts; per-user = SEC-14 | engaged-bucket feed (adults with consent), `session_network_observations`, `playback_sessions`, `security_signals` (`cap.*`) | yes | H3 Concurrent-use events |
| H4 Repeated IP/device associations | `repeated-network-device-associations` | Network clusters (`ASN:/16`, /24 prefixes) shared by many accounts, with trusted-network, CGNAT and AB-04/AB-05 flags; never used as identity | `login_attempts`, `session_network_observations`, `org_trusted_networks` | aggregate by default; per-user with `security.evidence.read` | H4 Network-cluster associations |
| H5 Blocked accounts | `blocked-accounts` | Active L3/L4 and T-protect: since, ends_at, deferred_until, source (engine / HC rule / reviewer), case, org | `account_restrictions` | yes | H5 Blocked and restricted accounts |
| H6 Pending unblock requests | `pending-unblock-requests` | State, SLA countdown, pending second approval (`approval_requests`), assignee | `unblock_requests`, `approval_requests` | yes | H6 Pending unblock requests |
| H7 Average review time | `average-review-time` | Median/p90 submission → first response and → decision, by level and week; SLA compliance % | `unblock_requests`, `case_decisions` | no | H7 Average review time |
| H8 False-positive rate | `false-positive-rate` | Per ruleset version, rule and **HC rule**: share of L3/L4 decisions concluded `lift_false_positive`; L2 re-verification pass rate; bulk lifts; circuit-breaker state; alerts (> 10% over 30 d; > 3 FP cases/week per rule; HC breaker trip) | `case_decisions`, `risk_evaluations` | no | H8 False-positive rate |
| H9 Repeat incidents | `repeat-incidents` | Users with ≥ 2 confirmed L3+ within 180 days; interval; outcome | `case_decisions`, `security_cases` | yes | H9 Repeat incidents |
| H10 Active-session counts | `active-session-counts` | Active sessions now and by hour/day, by tier, client type, org; users at cap; lab vs personal | `auth_sessions` (aggregates) | no | H10 Active sessions |
| H11 Daily/weekly/monthly learning activity | `learning-activity` | DAU/WAU/MAU (M5 > 0), learning time totals, by org/tier; per-user daily activity only inside a case review, adults with `security_monitoring` consent | `daily_learning_aggregates`, `weekly_learning_aggregates`, `analytics.feeds.get_activity_summary` | aggregate; per-user only adults with consent | H11 Activity context |
| H12 Device and login history | `device-login-history` | Per-user chronological logins, sessions, network changes and devices (same as SEC-13, export-oriented) | `auth_sessions`, `session_network_observations`, `login_attempts`, `user_devices` | yes | H12 User security timeline |
| ENG Engine health | `engine-health` | Level distribution over time, `risk.mode` and kill-switch state, HC shadow matches vs enforced, shadow vs active diff, signal volumes, AB-*/IN-* counters, OTP delivery failure by provider, pending trusted-network verifications (live state: SEC-43) | aggregates | no | ENG Policy and engine health |

Response (aggregate example, H7):

```json
{
  "report_key": "average-review-time",
  "generated_at": "2026-11-03T10:15:02.123Z",
  "period": {"from": "2026-10-01", "to": "2026-10-31", "timezone": "Asia/Kolkata"},
  "rows": [
    {"week": "2026-W40", "level": 3, "requests": 21, "first_response_median_h": 6.5, "first_response_p90_h": 19.0, "decision_median_h": 30.2, "decision_p90_h": 61.0, "sla_compliance_pct": 95.2},
    {"week": "2026-W40", "level": 4, "requests": 3, "suppressed": true}
  ],
  "k_min": 10
}
```

Cells with fewer than `analytics.k_min.cohort` (10) subjects are returned as `{"suppressed": true}`. Per-user rows require `security.evidence.read` and a `reason_code`; super_admin sees aggregates only (M3 only in break-glass).

#### SEC-32 · POST `/security/reports/{report_key}/exports`

Request `{"filters": {"from": "2026-10-01", "to": "2026-10-31", "level": [3, 4]}, "include_per_user_rows": true, "reason_code": "qa_sample", "reason": "Monthly integrity report"}`. Response `202`:

```json
{
  "export_job_id": "0193a8b9-cadb-7cec-8dfe-0f1a2b3c4d5e",
  "status": "awaiting_approval",
  "approval_request_id": "0193a8b9-0000-7111-8222-333344445555",
  "contains_pii": true
}
```

Aggregate-only exports go straight to `running`. Per-user exports wait in `awaiting_approval` until approved by a **second `security_reviewer`** holding `report.export.approve` (approver ≠ requester; `action_type = security.export.per_user`, §1.7; I-26). Exports of H10 and aggregate H11 are not security evidence: when they need approval (bulk > 10,000 rows) they use `action_type = export.bulk_pii` and a `super_admin` approver. Files are CSV, watermarked with requester and time, stored encrypted, download link valid 24 h, single principal, audited (`export.*`). Download via `ANL-14`.

#### SEC-41 · GET `/orgs/{org_id}/security-summary`

```json
{"organization_id": "0192f7aa-...", "restricted_students": {"L3": 2, "L4": 0}, "open_cases": 2, "trusted_networks": {"verified": 3, "proposed": 1, "expiring_within_30d": 0}, "notify_policy": "L4_status_only"}
```

Counts below the cohort floor are shown as `"<10"`. No student names, reasons, evidence or levels per student here; COL-009 shows a per-student status badge only (status + level, `security.status.read` @O), following `org.notify_coordinator_on_restriction` (default `L4_status_only`: only L4 status is shown; never signals) (resolves I-23).

#### SEC-42 · POST `/security/engine/kill-switch`

Request `{"target": "risk_mode" | "hc_all" | "rule", "rule_key": "HC-01", "reason": "FP surge on HC-01 after campus Wi-Fi change"}` (`rule_key` only with `target = rule`). Response `200`:

```json
{
  "applied": {"target": "hc_all", "risk.hc.auto_restrict_enabled": false, "effective_within_seconds": 60},
  "ratification": {"approval_request_id": "0193b9c0-...", "action_type": "risk.kill_switch.ratify", "due_at": "2026-11-04T10:15:02.000Z"}
}
```

Effects: `risk_mode` → `risk.mode = shadow`; `hc_all` → `risk.hc.auto_restrict_enabled = false`; `rule` → that rule version `active → shadow` (`status_change_reason = kill_switch`). Restrictions already in force are not changed (use SEC-44). A ratification request is created; the ratifier (`approval.decide`, ≠ the person who flipped the switch) decides via ADM-14/15. If not ratified within 24 h the security lead and super_admins are paged; the switch is **not** reverted. Errors: `409 invalid_state_transition` (target already in that state, or the request would move toward enforcement — that is a Dual `policy.change` via ADM-09), `step_up_required`, `permission_denied`. Audited (`risk.kill_switch`). (RE §5.7)

#### SEC-44 · POST `/security/restrictions/bulk-lift-requests`

Request:

```json
{
  "selector": {"ruleset_version": "2.1.0", "rule_key": "HC-01", "organization_id": null, "applied_from": "2026-11-01T00:00:00.000Z", "applied_to": "2026-11-03T00:00:00.000Z", "network_cidr": null, "asn": null},
  "dry_run": true,
  "reason": "HC-01 false-positive surge on 2026-11-02",
  "extension_credit": true
}
```

`dry_run: true` → `200 {"matched": 214, "excluded_by_reason": {"l4": 3, "high_risk": 5, "takeover": 2, "human_applied": 11}, "sample": [≤ 50 masked rows]}`. `dry_run: false` → `202 approval_pending` (`action_type = security.restriction.bulk_lift`; approver via `approval.decide`, ≠ requester); on approval one `lift_false_positive` decision is written per case, restrictions end without re-verification, FP counters (H8) increment and, with `extension_credit`, the restricted days are credited (UNB §6 step 8). Only engine-applied L3s match; L4, high-risk, takeover and human-applied restrictions are always excluded. More than 5,000 matches → `422 validation_failed` (`selector_too_broad`). Progress via SEC-45. (RE §5.8)

#### SEC-46 · POST `/me/security/events/{event_ref}/disown`

"This wasn't me" from a cookie-replay or new-sign-in notice (UNB §1.6a). Request `{"confirm": true}` → `200 {"result": "protected", "sessions_revoked": 3, "must_change_password": true, "recovery_url": "/auth/recover?t=..."}`. Triggers HC-T3: all sessions revoked (including the current one; cookies cleared), forced password reset, T-protect lock until recovery. Errors: `not_found` (unknown or not the caller's event), `invalid_state_transition` (event already disowned).

---

## 7. Unblock requests (`security`)

States (brief §1, PO-01): `draft`, `submitted`, `under_review`, `info_requested` (student label "Additional information requested"), `escalated` ("With senior reviewer"), `approved`, `rejected`, `closed` with `closure_reason` ∈ `completed`, `rejected_final`, `withdrawn`, `no_response`, `moot`. Only the authenticated account holder (any scope, typically `restricted` or `status_only`) can create or view their own requests; an L4 user signs in to a `status_only` session to appeal (PO-07). The reference `APL-YYMM-XXXXXX` is never an authenticator.

### 7.1 Catalogue (UNB)

| ID | Method | Path | Summary | Permission @ scope | Step-up | Idem | Tag | Rate limit | Status |
|---|---|---|---|---|---|---|---|---|---|
| UNB-01 | POST | `/security/unblock-requests` | Create a request for an own open case (`submit: false` → draft, `true` → submitted) | `security.unblock.triage` S (create own) | — | **Req** | AS | 1 open per case; 3 submissions / 30 d; 5 form loads/min (no CAPTCHA; WCAG 2.2 SC 3.3.8) | **Implemented** |
| UNB-02 | PATCH | `/security/unblock-requests/{request_id}` | Autosave a draft (drafts deleted after 7 days idle) | S | — | — | AS | 30/min | **Implemented** |
| UNB-03 | POST | `/security/unblock-requests/{request_id}/attachments` | Presigned upload for ≤ 2 files, ≤ 5 MB, PDF/PNG/JPG (AV-scanned, EXIF stripped) | S | — | opt | AS | 5/h | **Implemented** |
| UNB-04 | POST | `/security/unblock-requests/{request_id}/submit` | Submit a draft | S | — | **Req** | AS | as UNB-01 | **Implemented** |
| UNB-05 | GET | `/security/unblock-requests` | Own requests | S | — | — | AS | — | **Implemented** |
| UNB-06 | GET | `/security/unblock-requests/{request_id}` | Own request with student-visible timeline and notes | S | — | — | AS | — | **Implemented** |
| UNB-07 | POST | `/security/unblock-requests/{request_id}/responses` | Answer an info request (same validation as the form) → `under_review` | S | — | **Req** | AS | 10/day | **Implemented** |
| UNB-08 | POST | `/security/unblock-requests/{request_id}/withdraw` | Withdraw → `closed` (`withdrawn`) | S | — | opt | AS | — | **Implemented** |
| UNB-09 | POST | `/security/unblock-requests/{request_id}/appeal` | One second-level appeal within 14 days of rejection → `escalated` | S | — | **Req** | AS | 1 per request | **Implemented** |
| UNB-10 | GET | `/security/review/unblock-requests` | Reviewer queue (H6): state, SLA, second-approval flag, assignee, level | `security.unblock.triage` @P | — | — | — | — | **Implemented** |
| UNB-11 | GET | `/security/review/unblock-requests/{request_id}` | Full request incl. form answers, device recognitions, attachment list | `security.unblock.triage` @P | — | — | — | `reason_code` | **Implemented** |
| UNB-12 | POST | `/security/review/unblock-requests/{request_id}/claim` | Claim → `under_review` (conflict check; first-response SLA met) | `security.unblock.triage` @P | — | opt | — | If-Match | **Implemented** |
| UNB-13 | POST | `/security/review/unblock-requests/{request_id}/request-info` | Templated question (+ free text) → `info_requested`; SLA clock pauses; reminders 72 h and 6 d; auto-close at 7 d | `security.unblock.triage` @P | — | opt | — | If-Match | **Implemented** |
| UNB-14 | POST | `/security/review/unblock-requests/{request_id}/escalate` | → `escalated` (reviewer choice; system also escalates on SLA breach) | `security.unblock.triage` @P | — | opt | — | If-Match | **Implemented** |
| UNB-15 | POST | `/security/review/unblock-requests/{request_id}/send-back` | `escalated` → `under_review` with note (second reviewer) | `security.case.decide` @P | P5 | opt | — | If-Match | **Implemented** |
| UNB-16 | GET | `/security/review/unblock-requests/{request_id}/attachments/{attachment_id}` | Sandboxed viewer URL (download disabled by default; 5 min) | `security.evidence.read` @P | — | — | — | audited; `reason_code` | **Implemented** |
| UNB-17 | GET | `/support/unblock-requests` | Support triage list (L1/L2 handled by support; L3/L4 forwarded) | `security.unblock.triage` @P (support) | — | — | — | — | **Implemented** |
| UNB-18 | POST | `/support/unblock-requests/{request_id}/forward` | Forward an L3/L4 or escalated item to the security queue with a note | `security.unblock.triage` @P (support) | — | opt | — | — | **Implemented** |
| UNB-19 | GET | `/security/unblock-requests/form` | Unblock form metadata (reason codes, attachment limits, eligibility) for the caller | any (AS) | — | — | AS | — | **Implemented (added)** |
| UNB-20 | GET | `/security/unblock-requests/by-reference/{reference}` | Status by `APL-` reference; only the owner's own requests resolve — malformed/unknown/others' → same `404` | any (AS) | — | — | AS | — | **Implemented (added)** |

Decisions (approve/reject) are recorded on the case with `SEC-09` (`unblock_request_id` set); `uphold` moves the request to `rejected`, lift outcomes to `approved` (or `escalated` when a second approval is required: the proposal is an `approval_requests` row decided with `SEC-10`/`SEC-11`, or withdrawn with `SEC-11a`).

### 7.2 Detail entries (unblock)

#### UNB-01 · POST `/security/unblock-requests`

Headers: `Idempotency-Key: 6f1c3e5a-9b7d-4e2f-8a10-c3d5e7f9a1b2`, `X-CSRF-Token`.

Request:

```json
{
  "case_ref": "SEC-2611-7KQ4MZ",
  "submit": true,
  "what_happened": ["all_devices_mine", "travelling_or_vpn"],
  "explanation": "I use my laptop for lectures and my phone for notes at the same time. I moved from my hostel in Hyderabad to my home in Pune on 30 October, so the locations changed.",
  "recognised_user_device_ids": ["0193a2c4-11aa-7bcd-9e01-23456789abd1", "0193a2c4-11aa-7bcd-9e01-23456789abd2"],
  "none_recognised": false,
  "lab_location_text": null,
  "attachment_ids": [],
  "preferred_contact": "email",
  "declaration": true,
  "guardian_assisted": false
}
```

`what_happened` codes: `all_devices_mine`, `family_member_used`, `shared_with_friend`, `account_may_be_hacked`, `college_lab_or_shared_computer`, `travelling_or_vpn`, `other`.

Response `201`:

```json
{
  "request_id": "0193a5f6-0718-7293-a4b5-c6d7e8f90a1b",
  "reference": "APL-2611-3HX9RB",
  "case_ref": "SEC-2611-7KQ4MZ",
  "state": "submitted",
  "state_label": "Submitted",
  "submitted_at": "2026-11-03T10:15:02.123Z",
  "devices_revoked": [{"user_device_id": "0193a2c4-11aa-7bcd-9e01-23456789abd7", "label": "Chrome on Android"}],
  "sla": {"first_response_due": "2026-11-04T10:15:02.000Z", "decision_due": "2026-11-06T10:15:02.000Z"},
  "acknowledgement_sent_via": ["in_app", "email"]
}
```

Errors: `idempotency_key_required`, `not_found` (case is not the caller's or not open — no existence disclosure), `unblock_request_open` (one open request per case; `reference` of the open one), `unblock_rate_limited`, `validation_failed` (`explanation` outside 30–2,000 characters, no device chosen and `none_recognised` false, `preferred_contact` not a verified channel, missing `declaration`), `dlp_rejected` (password/OTP/card-like content; inline hint "Please don't include passwords or codes"), `payload_too_large`.

Server-side enforcement: text stripped of HTML, CR/LF normalised, DLP-masked before storage; never asks for passwords, OTPs, recovery codes, payment details, Aadhaar or PAN; unrecognised devices (all devices not in `recognised_user_device_ids`) are revoked immediately on submit; `submit: false` stores a draft and does not revoke; one open request per case enforced by `ux_ur_open_per_case`; `(user_id, idempotency_key)` unique; acknowledgement with the `APL-` reference via in-app + chosen channel; audited (`unblock.created`, `unblock.submitted`). Guardian-assisted requests exist only for deterministic or takeover issues of minors.

#### UNB-06 · GET `/security/unblock-requests/{request_id}`

```json
{
  "reference": "APL-2611-3HX9RB",
  "case_ref": "SEC-2611-7KQ4MZ",
  "state": "info_requested",
  "state_label": "Additional information requested",
  "submitted_at": "2026-11-03T10:15:02.123Z",
  "timeline": [
    {"at": "2026-11-03T10:15:02.123Z", "state": "submitted"},
    {"at": "2026-11-03T14:02:00.000Z", "state": "under_review"},
    {"at": "2026-11-03T15:40:00.000Z", "state": "info_requested", "question_template": "confirm_second_location", "message": "Please tell us which city you were in on 30–31 October."}
  ],
  "info_requested_due": "2026-11-10T15:40:00.000Z",
  "decision": null,
  "appeal": {"allowed": false, "deadline": null},
  "grievance_route": "/help/grievance"
}
```

After a decision: `"decision": {"outcome": "uphold", "summary": "...", "decided_at": "...", "appeal_deadline": "2026-11-20T...Z"}`; `appeal.allowed` true until the deadline if not used. Internal notes, reviewer identity, scores and evidence are never included.

#### UNB-09 · POST `/security/unblock-requests/{request_id}/appeal`

Request `{"explanation": "I have attached my hostel exit letter showing the move date.", "attachment_ids": ["0193a9..."]}` → `200 {"state": "escalated", "state_label": "With senior reviewer", "is_second_level_appeal": true}`. A different reviewer is required. Errors: `appeal_window_closed` (> 14 days after rejection), `appeal_already_used`, `invalid_state_transition` (not `rejected`).

#### UNB-13 · POST `/security/review/unblock-requests/{request_id}/request-info`

Headers `If-Match`. Request `{"template_key": "confirm_second_location", "message": "Please tell us which city you were in on 30–31 October."}` → `200 {"state": "info_requested", "info_requested_due": "...", "sla_paused": true}`. The template list is fixed (`GET /security/review/info-templates` is part of UNB-10's `meta` block). Errors: `invalid_state_transition`, `version_conflict`.

#### Transitions enforced by the API

| From → To | Endpoint | Actor guard |
|---|---|---|
| — → `draft` / `submitted` | UNB-01 | Owner; case open; limits |
| `draft` → `submitted` | UNB-04 | Owner |
| `submitted` → `under_review` | UNB-12 (or auto-assign job) | Reviewer without conflict; not the applier |
| `under_review` → `info_requested` | UNB-13 | Assigned reviewer |
| `info_requested` → `under_review` | UNB-07 | Owner |
| `info_requested` → `closed` (`no_response`) | system (7 days) | — |
| `under_review` → `approved` / `rejected` | SEC-09 | Assigned reviewer; not high-risk for approval |
| `under_review` → `escalated` | UNB-14, SEC-09 (second approval), SLA job | Reviewer / system |
| `escalated` → `approved` / `rejected` | SEC-10 (approves the pending `approval_requests` proposal) / SEC-09 by second reviewer | Distinct reviewer or super_admin (≠ requester, ≠ applier) |
| `escalated` → `under_review` | UNB-15 / SEC-11 (approval `rejected`) | Second reviewer |
| `escalated` (stays) | SEC-11a withdraw (approval `cancelled`); 72 h lapse (approval `expired`, SLA alert) | Requester / system |
| `rejected` → `escalated` | UNB-09 | Owner, once, ≤ 14 days |
| `rejected` → `closed` (`rejected_final`) | system | 14 days without appeal, or appeal decided |
| `approved` → `closed` (`completed`) | AUTH-22 completion | system |
| `submitted`/`under_review`/`info_requested` → `closed` (`withdrawn`/`moot`) | UNB-08 / system on natural expiry + re-verification | Owner / system |

Any other transition → `409 invalid_state_transition`.

---

## 8. Organizations, batches, memberships, invitations, imports (`orgs`)

Cross-org ids return `404` (TI-02). Coordinators act only inside their own organization (`@O`); trainers inside batches they hold (`@B`).

### 8.1 Catalogue (ORG)

| ID | Method | Path | Summary | Permission @ scope | Step-up | Idem | Tag | Status |
|---|---|---|---|---|---|---|---|---|
| ORG-01 | GET | `/orgs` | List organizations (super_admin: all; others: own) | `org.read` @P / @O | — | — | — | **Implemented** |
| ORG-02 | POST | `/orgs` | Create organization (legal/display name, short code, address, GSTIN, contact, fiduciary role, DPA ref) | `org.create` @P | P5 | opt | — | **Implemented** |
| ORG-03 | GET | `/orgs/{org_id}` | Org profile, status, settings, contract link | `org.read` @O | — | — | — | **Implemented** |
| ORG-04 | PATCH | `/orgs/{org_id}` | Update profile | `org.update` @O | — | — | — | **Implemented** |
| ORG-05 | POST | `/orgs/{org_id}/suspend` | Suspend (contract entitlements suspended, BR-ENT-19) | `org.suspend` @P | P5 +Dual | Req | — | Planned |
| ORG-06 | PATCH | `/orgs/{org_id}/settings` | Require MFA for students, allowed invite domains, default batch visibility, trainer visibility. **(audit fix, FR-ORG-002)** `allowed_invite_domains` is normalised (lowercase, `@` and spaces stripped, duplicates removed); a value that is not a domain → `422`. An empty list means no restriction. `require_mfa_students` is enforced at sign-in (§2.1 `mfa_enrolment_required`) | `org.settings.update` @O | S10 | — | — | **Implemented** |
| ORG-07 | GET | `/orgs/{org_id}/members` | Roster (filters: batch, department, year, status, invite status). **(audit fix)** `?member_type=student\|staff`; `?batch_id=` is checked at batch scope (BE-29); cursor-paginated `cursor`/`limit` (≤ 100) with `page` (ADM-33). `restricted` is `null` unless the caller holds `security.status.read` and the org's `notify_coordinator_on_restriction` policy allows it (ADM-30) | `org.member.read` @O/@B | — | — | — | **Implemented** |
| ORG-08 | GET | `/orgs/{org_id}/members/{user_id}` | Scoped student profile (BR-ENT-14; restriction badge = status + level only) | `org.member.read` @O | — | — | — | **Implemented** |
| ORG-09 | DELETE | `/orgs/{org_id}/members/{user_id}` | Remove member / graduate (ends sponsored access per BR-ENT-16/17; conversion offer) | `org.member.remove` @O | S10 | — | — | **Implemented** |
| ORG-10 | POST | `/orgs/{org_id}/imports` | Create import job from an uploaded CSV/XLSX (≤ 5,000 rows); idempotent by file SHA-256 | `org.member.import` @O | — | Req | — | **Implemented** |
| ORG-11 | GET | `/orgs/{org_id}/imports/{job_id}` | Validation preview with per-row errors | `org.member.import` @O | — | — | — | **Implemented** |
| ORG-12 | POST | `/orgs/{org_id}/imports/{job_id}/commit` | Commit: create/link users, memberships, invitations, seats (or waitlist) | `org.member.import` @O | S10 (PII bulk) | Req | — | **Implemented** |
| ORG-13 | POST | `/orgs/{org_id}/imports/{job_id}/cancel` | Cancel before commit | `org.member.import` @O | — | opt | — | **Implemented** |
| ORG-14 | GET | `/orgs/{org_id}/invitations` | Invitation status list (`sent`, `opened`, `accepted`, `expired`, `bounced`, `revoked`). **(audit fix, ADM-33)** Cursor-paginated `cursor`/`limit` (≤ 100), `page` | `org.member.read` @O | — | — | — | **Implemented** |
| ORG-15 | POST | `/orgs/{org_id}/invitations` | Invite one student or staff member. **(audit fix)** An email outside the org's `allowed_invite_domains` → `422 validation_failed` with `errors[{field: "email", code: "email_domain_not_allowed"}]` (exact, case-insensitive domain match; mobile-only invites are not checked). The CSV import preview (ORG-10/11) marks such rows `error_code: "email_domain_not_allowed"` | `user.invite` @O | — | opt | — | **Implemented** |
| ORG-16 | POST | `/orgs/{org_id}/invitations/{invitation_id}/resend` | Resend (≤ 3) | `user.invite` @O | — | opt | — | **Implemented** |
| ORG-17 | POST | `/orgs/{org_id}/invitations/{invitation_id}/revoke` | Revoke invitation | `user.invite` @O | — | opt | — | **Implemented** |
| ORG-18 | GET | `/invitations/{token}` | Invite preview (org name, data-sharing notice, account exists hint only after sign-in) | public (token) | — | — | PUB | **Implemented** |
| ORG-19 | POST | `/invitations/{token}/accept` | Accept: new user sets password + verifies mobile, or signed-in user links (FR-IDN-012); seat assignment. **(audit fix)** An email outside `allowed_invite_domains` → `403 permission_denied` (`permission: invitation.accept`) on both the new-account and the signed-in path | public (token) / S | — | Req | PUB | **Implemented** |
| ORG-20 | GET | `/orgs/{org_id}/batches` | Batches | `org.read` @O | — | — | — | **Implemented** |
| ORG-21 | POST | `/orgs/{org_id}/batches` | Create batch (name, department, graduation year, dates, linked courses/tests) | `batch.create` @O | — | opt | — | **Implemented** |
| ORG-22 | GET | `/batches/{batch_id}` | Batch detail | `org.member.read` @B | — | — | — | **Implemented** |
| ORG-23 | PATCH | `/batches/{batch_id}` | Update batch | `batch.update` @O | — | — | — | **Implemented** |
| ORG-24 | POST | `/batches/{batch_id}/archive` | Archive batch | `batch.archive` @O | — | opt | — | **Implemented** |
| ORG-25 | GET | `/batches/{batch_id}/members` | Batch members | `org.member.read` @B | — | — | — | **Implemented** |
| ORG-26 | POST | `/batches/{batch_id}/members` | Add or move members (history retained) | `batch.member.manage` @O / @B (both batches) | — | opt | — | **Implemented** |
| ORG-27 | DELETE | `/batches/{batch_id}/members/{user_id}` | Remove from batch | `batch.member.manage` @O | — | — | — | **Implemented** |
| ORG-28 | GET | `/me/orgs` | My college, batches, coordinator contact, seat validity (STU-027) | S | — | — | L3R | **Implemented** |
| ORG-29 | PATCH | `/me/orgs/{org_id}` | Opt in/out "share all my prep progress with my college" (BR-ENT-14) | S | — | — | CON | **Implemented** |
| ORG-30 | POST | `/orgs/{org_id}/shortlists` | Build shortlist (filters: score/percentile, mastery, attendance) and export (P1) | `analytics.read` @O + `report.export.request` @O | S10 | opt | — | Planned |

#### ORG-10 / ORG-11 / ORG-12 · Bulk import (representative)

`ORG-10` request (after the client uploads the file through `MED-02` with purpose `roster_import`): `{"file_upload_id": "0193aa...", "batch_id": "0193ab...", "assign_seats": "on_acceptance"}` → `201 {"job_id": "0193ac...", "status": "validating"}`. Re-posting the same file returns the **same job** (`UNIQUE (organization_id, file_sha256)`; `200`, header `Idempotency-Replayed: true`).

`ORG-11` response:

```json
{
  "job_id": "0193ac10-1121-7232-8343-945a6b7c8d9e",
  "status": "preview_ready",
  "total_rows": 1180,
  "valid_rows": 1162,
  "error_rows": 18,
  "seat_pool": {"total": 1200, "used": 1050, "free": 150, "would_waitlist": 1012},
  "row_results": [
    {"row": 14, "status": "error", "error_code": "invalid_mobile"},
    {"row": 77, "status": "error", "error_code": "duplicate_in_file"},
    {"row": 102, "status": "ok", "action": "link_existing_account_on_acceptance"}
  ],
  "page": {"next_cursor": "eyJ...", "has_more": true, "limit": 100}
}
```

`row_results` never say that an email belongs to an account in another organization (TI-05); existing accounts are linked only when the invitee accepts. `ORG-12` request `{"waitlist_when_pool_exhausted": true}` → `202 {"status": "committing"}`; errors `seat_pool_exhausted` (when waitlisting declined), `invalid_state_transition`.

---

## 9. RBAC (`rbac`)

### 9.1 Catalogue (RBAC)

| ID | Method | Path | Summary | Permission @ scope | Step-up | Idem | Tag | Status |
|---|---|---|---|---|---|---|---|---|
| RBAC-01 | GET | `/rbac/roles` | Roles with tier, MFA requirement, allowed scope types | `rbac.grant.read` @O/@P | — | — | — | **Implemented** |
| RBAC-02 | GET | `/rbac/permissions` | Permission catalogue (key, module, sensitivity) | `rbac.grant.read` @P | — | — | — | **Implemented** |
| RBAC-03 | GET | `/rbac/grants` | Grants in scope (`?user_id=&role=&scope_type=&scope_id=`) | `rbac.grant.read` @O/@P | — | — | — | **Implemented** |
| RBAC-04 | POST | `/rbac/grants` | Grant a role at a scope (optional `expires_at`, reason) | `rbac.grant.manage` @P, or `rbac.grant.org_staff` @O for trainer/mentor at own `batch:{id}` | P5 (+Dual for `super_admin`, `security_reviewer`, `finance_admin`) | Req | — | **Implemented** |
| RBAC-05 | POST | `/rbac/grants/{grant_id}/revoke` | Revoke grant (forces re-login of the grantee) | as RBAC-04 | P5 (+Dual for privileged roles) | opt | — | **Implemented** |
| RBAC-06 | GET | `/me/grants` | Own grants → portal switcher | S | — | — | AS | **Implemented** |
| RBAC-07 | POST | `/rbac/approval-requests/{approval_request_id}/approve` | Approve a privileged grant/revoke (interim until ADM-14/15 cover `rbac.*` actions); approver ≠ requester and holds the required role | `approval.decide` @P | P5 | — | — | **Implemented (added)** |
| RBAC-08 | POST | `/rbac/approval-requests/{approval_request_id}/reject` | Reject a privileged grant/revoke request | `approval.decide` @P | P5 | — | — | **Implemented (added)** |

`RBAC-04` request `{"user_id": "0193...", "role_key": "trainer", "scope_type": "batch", "scope_id": "0193ab...", "expires_at": "2027-05-31T18:29:59.000Z", "reason": "CSE 2027 placement batch faculty"}` → `201 {"grant_id": "...", "session_effect": "grantee_sessions_rotated"}` or `202 approval_pending` for privileged roles. Errors: `sod_violation` (`SoD-10`: `finance_admin` with `security_reviewer`, or super_admin with either in production), `validation_failed` (scope type not allowed for the role; coordinator granting outside own org or to a user without a staff `org_memberships` row), `permission_denied`. A grant change forces re-login of the grantee because `session_tier` is fixed at login.

---

## 10. Catalog and authoring (`catalog`)

Public reads are cacheable (`Cache-Control: public, max-age=300`) and never include draft content, answer keys or entitled-only bodies. Authoring routes live under `/studio/*` and are used by content managers (platform) and trainers/coordinators (org-private, `O-private`).

### 10.1 Catalogue (CAT)

> **Removed 2026-11-14:** CAT-07 `GET /catalog/search` (its only caller, the public catalogue page, was removed; Hosting redirects `/courses` to the website).

| ID | Method | Path | Summary | Permission @ scope | Step-up | Idem | Tag | Status |
|---|---|---|---|---|---|---|---|---|
| CAT-01 | GET | `/catalog/courses` | Catalog with filters (category, level, price type, language) | public | — | — | PUB | **Implemented** |
| CAT-02 | GET | `/catalog/courses/{slug}` | Course detail: outcomes, syllabus, completeness indicator, free-preview lessons, access options, refund rule text; signed-in adds "already owned" / "included via college" | public | — | — | PUB | **Implemented** |
| CAT-03 | GET | `/catalog/companies` | Company hubs | public | — | — | PUB | Planned |
| CAT-04 | GET | `/catalog/companies/{slug}` | Company hub: pattern, syllabus, interview experiences, sample mock CTA, path pricing | public | — | — | PUB | Planned |
| CAT-05 | GET | `/catalog/subjects/{subject_slug}/topics/{topic_slug}` | Indexable topic page with concept notes and 10 free sample questions **with explanations** | public | — | — | PUB | Planned |
| CAT-06 | GET | `/catalog/free-resources` | Free PDFs, cheat sheets, free courses | public | — | — | PUB | **Implemented** |
| CAT-08 | GET | `/studio/courses` | Courses in scope (platform or org-private). `?status=draft\|published\|archived`, cursor. **(audit fix, ADM-41)** A batch-scoped trainer gets the courses of their course-scoped grants **plus the organization-owned (O-private) courses of their batches' organizations** (mirrors `rbac.service.ORG_PRIVATE_VIA_BATCH`); never platform courses or other orgs. A batch-scoped studio user with no such course gets an empty list, not `403` | `course.create`/`course.edit`/`course.preview` @P/@C/@O/@B | — | — | — | **Implemented** |
| CAT-09 | POST | `/studio/courses` | Create course + draft version | `course.create` @P / @O (O-private) | — | opt | — | **Implemented** |
| CAT-10 | GET | `/studio/courses/{course_id}` | Course with draft and published versions | `course.edit` @C | — | — | — | **Implemented** |
| CAT-11 | PATCH | `/studio/courses/{course_id}/draft` | Update draft metadata (title, slug, summary, outcomes, level, tags, certificate rule, completeness plan) | `course.edit` @C | — | — | — | **Implemented** |
| CAT-12 | PUT | `/studio/courses/{course_id}/draft/outline` | Replace module/lesson ordering (lessons keep `lesson_key`) | `course.edit` @C | — | — | — | **Implemented** |
| CAT-13 | POST | `/studio/courses/{course_id}/draft/lessons` | Add lesson (video, article, pdf, practice set, quiz, coding, assignment, live link) | `course.edit` @C | — | opt | — | **Implemented** |
| CAT-14 | PATCH | `/studio/lessons/{lesson_id}` | Edit draft lesson (content, assets, free-preview flag, est. reading minutes) | `course.edit` @C | — | — | — | **Implemented** |
| CAT-15 | PUT | `/studio/lessons/{lesson_id}/topics` | Set `lesson_topics` (one primary) | `course.edit` @C | — | — | — | **Implemented** |
| CAT-16 | POST | `/studio/courses/{course_id}/submit-review` | Draft → `in_review` | `course.edit` @C | — | opt | — | **Implemented** |
| CAT-17 | POST | `/studio/courses/{course_id}/publish` | Publish immutable version (`change_type`: `minor` auto-migrates progress, `major` prompts opt-in); author ≠ publisher for platform catalog | `course.publish` @P / @O (O-private, reviewed) | — | Req | — | **Implemented** |
| CAT-18 | POST | `/studio/courses/{course_id}/archive` | Archive | `course.archive` @P/@O | — | opt | — | **Implemented** |
| CAT-19 | GET | `/studio/courses/{course_id}/versions` | Version history | `course.edit` @C | — | — | — | **Implemented** |
| CAT-20 | GET | `/studio/lessons/{lesson_id}/preview` | Player preview of draft ("Preview — not visible to students") | `course.preview` @C/@O/@P | — | — | — | **Implemented** |
| CAT-21 | POST | `/studio/resources` | Create downloadable resource (`public`, `signed_in`, `entitled`) | `resource.manage` @C/@P | — | opt | — | **Implemented** |
| CAT-21b | GET | `/studio/resources` | **(audit fix, added)** Read side of CAT-21/22: resources of a course, lesson or company hub, newest first. `?course_id=\|lesson_id=\|company_id=&cursor=&limit=` (at least one target, else `422 validation_failed` on `course_id`; a `lesson_id` outside the given `course_id` → `422`). Response `{data, page}` (operation `cat_21b_list_resources`) | `resource.manage` @C, or @P for company-only resources | — | — | — | **Implemented (added)** |
| CAT-22 | PATCH | `/studio/resources/{resource_id}` | Update resource | `resource.manage` @C/@P | — | — | — | **Implemented** |

**Lesson types (audit fix, `catalog_0002`):** `lesson_type` is `video`, `article`, `pdf`, `practice_set`, `quiz`, `coding`, `assignment` or `live_link` (see `database-schema.md` §7 for the exact CHECK). `pdf` needs no reference: the file is a `lesson_assets` row uploaded with MED-02 `lesson_file` (`asset_type=pdf`) and completes on LRN-06 scroll evidence like an article. `practice_set` needs a `test_id`, like `quiz`. **Studio lesson output** (CAT-10/11/12 full version, CAT-13, CAT-14, CAT-20) now includes `topics: [{topic_id, is_primary}]`, primary first; learner payloads (LRN-05) do not carry the key.

Catalog and learning list endpoints return `400 validation_failed` for a `limit` outside 1..100 (it used to be clamped silently; BE-34).

`CAT-17` errors: `sod_violation` (`SoD-04` author = publisher), `validation_failed` (lessons with media still `processing`, missing required explanation in embedded questions), `invalid_state_transition` (not `in_review`). Publishing emits `course.published`; progress is keyed by `lessons.lesson_key`, so republishing does not reset progress.

---

## 11. Media (`media`; playback sessions owned by `sessions`)

### 11.1 Catalogue (MED)

| ID | Method | Path | Summary | Permission @ scope | Step-up | Idem | Tag | Rate limit | Status |
|---|---|---|---|---|---|---|---|---|---|
| MED-01 | POST | `/media/uploads/video` | VdoCipher upload credentials for a lesson asset (direct upload; metadata only stored) | `media.upload` @C/@P | — | opt | — | 60/h | **Implemented** |
| MED-02 | POST | `/media/uploads/file` | S3 presigned POST (content-type and size conditions; malware scan before `available`) for a declared `purpose` | `media.upload` @C/@P, or purpose-specific (`roster_import`: `org.member.import` @O; `assignment_submission`, `support_attachment`, `unblock_attachment`: S). **Implemented purposes (code):** `lesson_file`, `resource_file`, `assignment_submission`, `support_attachment`. `support_attachment` **(audit fix, BE-17)**: ownership (S), ≤ 10 MB, `application/pdf`, `image/png`, `image/jpeg`, `image/webp`, `text/plain`, key `uploads/support_attachment/{user_id}/…`; attached through SUP-01/SUP-04 `attachments`. Unblock attachments use UNB-03, not MED-02 | — | opt | varies | 30/h | **Implemented** |
| MED-03 | GET | `/media/assets/{lesson_asset_id}/status` | Upload/processing status (`uploading`, `processing`, `ready`, `failed`) | `media.upload` @C/@P | — | — | — | — | **Implemented** |
| MED-04 | POST | `/media/playback-tokens` | Issue VdoCipher OTP + playback session (stream cap enforced) | S + entitlement | — | opt | — | 30/h per user | **Implemented** |
| MED-05 | POST | `/media/playback-sessions/{playback_session_id}/heartbeat` | 30 s heartbeat (position, buffering); `410` when revoked | S | — | exempt | — | 4/min per playback session | **Implemented** |
| MED-06 | POST | `/media/playback-sessions/{playback_session_id}/stop` | Stop playback (`stopped`) | S | — | — | — | — | **Implemented** |
| MED-07 | POST | `/media/downloads` | Short-lived CloudFront signed URL (≤ 5 min) for a resource or lesson file; watermarked PDF for `entitled` resources (P1) | S + entitlement (or public/signed_in) | — | opt | — | 60/h | **Implemented** |

#### MED-04 · POST `/media/playback-tokens`

Request:

```json
{"lesson_asset_id": "0193b0c1-d2e3-7f40-8152-63748596a7b8", "tab_id": "6c1e9d3a-2f47-4b8e-9a51-0d2c7e8f4b13", "take_over_playback_session_id": null}
```

Response `201`:

```json
{
  "playback_session_id": "0193b0c2-0000-7111-8222-3333aaaabbbb",
  "provider": "vdocipher",
  "otp": "20160313versASE323...",
  "playback_info": "eyJ2aWRlb0lkIjoi...",
  "otp_expires_at": "2026-11-03T10:20:02.000Z",
  "heartbeat_interval_seconds": 30,
  "stale_after_seconds": 90,
  "resume_position_seconds": 412,
  "watermark": {"text": "Ananya • 98xxxxxx21 • k7Q2", "moving": true}
}
```

Conflict (stream cap reached, brief §5):

```json
{
  "type": "https://techdrona.in/problems/playback-conflict",
  "title": "Playing on another device",
  "status": 409,
  "code": "playback_conflict",
  "detail": "This account is already playing a video on Chrome on Android. Play here instead?",
  "request_id": "01JC9X0A1B2C3D4E5F6G7H8J9K",
  "other_device_label": "Chrome on Android",
  "other_playback_session_id": "0193b0aa-1111-7222-8333-444455556666",
  "takeover_allowed": true
}
```

The client retries with `take_over_playback_session_id` set; the other session ends with `end_reason = taken_over` and its next heartbeat gets `410 playback_revoked`. Within the **same auth session** (multiple tabs) a second tab takes over silently (no 409).

Order of checks (security doc §7.3): `require_active_principal` (L3/L4 scope never reaches here) → `entitlements.check(lesson)` (free-preview lessons allowed for any signed-in user) → restriction < L3 → L2 owner verification of this device (`403 device_verification_required`) → stream cap under `pg_advisory_xact_lock(hashtext('play:'||user_id))`: count `playback_sessions` with `status='active' AND last_heartbeat_at > now() − 90 s` ≥ `playback.max_concurrent_streams` (default 1) → `409 playback_conflict` unless `playback.takeover_behavior = prompt_takeover` and a takeover id is supplied → per-user token rate limit (30/hour) → insert `playback_sessions` → VdoCipher OTP with `ttl = playback.otp_ttl_seconds` (300) and annotate watermark. The OTP is never logged; only `provider_otp_ref_hash` is stored. Stream-cap hits write `security_signals` `cap.stream` (deterministic; for adults also an SH-03 input). Errors: `entitlement_required`, `device_verification_required`, `playback_conflict`, `rate_limited`, `service_unavailable` (VdoCipher down).

#### MED-05 · POST `/media/playback-sessions/{id}/heartbeat`

Request `{"position_seconds": 431, "buffering": false, "playing": true}` → `200 {"state": "active", "server_time": "..."}`. Revoked (takeover, restriction, session revoked) → `410 playback_revoked` with `end_reason` (`taken_over`, `revoked`, `stale`); the player stops. Heartbeats update `last_heartbeat_at` only; learning time and video coverage come from analytics events (`ANL-01`), not from this endpoint. Idle effect `engaged_only` (§1.4): a heartbeat slides the idle timer (via `sessions.touch_engaged`) only when `playing: true` and the position advanced; paused or buffering heartbeats are neutral.

---

## 12. Learning, progress, assignments, certificates (`learning`)

Completion, certificates and grades depend on server-verifiable evidence (coverage + quiz, accepted submissions, attempt scores), never on time thresholds alone (brief §1 learning-evidence rule).

### 12.1 Catalogue (LRN)

| ID | Method | Path | Summary | Permission @ scope | Step-up | Idem | Tag | Status |
|---|---|---|---|---|---|---|---|---|
| LRN-01 | GET | `/me/dashboard` | Student dashboard (continue learning, assigned work, tests, expiring entitlements, banners) | S | — | — | L3R | **Implemented** |
| LRN-02 | GET | `/me/enrolments` | My courses with progress and validity. **(audit fix, BE-34)** `?cursor=&limit=` (1..100, default 100) with a real `page` envelope (signed offset cursor) | `enrolment.read` S | — | — | L3R | **Implemented** |
| LRN-03 | POST | `/me/enrolments` | Enrol in a free course or a course covered by an entitlement (first use) | S + entitlement | — | opt | — | **Implemented** |
| LRN-04 | GET | `/me/courses/{course_id}` | Enrolled course overview: modules, progress, next lesson, certificate status, version-migration prompt | `progress.read` S | — | — | L3R | **Implemented** |
| LRN-05 | GET | `/me/courses/{course_id}/lessons/{lesson_id}` | Lesson payload (article body, asset refs, resources) after entitlement check | S + entitlement | — | — | — | **Implemented** |
| LRN-06 | POST | `/me/lessons/{lesson_key}/completion` | Record server-checkable completion evidence for article/PDF lessons (scrolled-to-end marker); video completion derives from `video_watch_coverage` ≥ 90% | S + entitlement | — | opt | — | **Implemented** |
| LRN-07 | POST | `/me/courses/{course_id}/migrate-version` | Opt in to a major course version | S | — | opt | — | **Implemented** |
| LRN-08 | GET | `/me/assignments` | Assignments (due, submitted, graded) | S | — | — | L3R | **Implemented** |
| LRN-09 | GET | `/me/assignments/{assignment_id}` | Assignment detail, own submissions, grade (when released) | S | — | — | L3R | **Implemented** |
| LRN-10 | POST | `/me/assignments/{assignment_id}/submissions` | Submit (file refs ≤ 20 MB, allowed types, or code submission id); late policy applied | S + entitlement | — | **Req** | — | **Implemented** |
| LRN-11 | GET | `/me/certificates` | Certificates (issued, revoked). **(audit fix, BE-34)** `?cursor=&limit=` (1..100, default 100), `page` envelope | S | — | — | L3R | **Implemented** |
| LRN-12 | GET | `/me/certificates/{certificate_id}/pdf` | Signed URL to PDF (5 min) | S | — | — | L3R | **Implemented** |
| LRN-13 | GET | `/certificates/verify/{public_code}` | Public verification: name, course, issue date, identity-verified flag, status (`valid` / `revoked on DATE`, no reason) | public | — | — | PUB | **Implemented** |
| LRN-14 | POST | `/assignments` | Create assignment (instructions, attachments, due date, late policy, rubric) | `assignment.manage` @B/@C | — | opt | — | **Implemented** |
| LRN-15 | PATCH | `/assignments/{assignment_id}` | Edit assignment | `assignment.manage` @B/@C | — | — | — | **Implemented** |
| LRN-16 | GET | `/assignments/{assignment_id}/submissions` | Grading queue | `assignment.grade` @B/@C | — | — | — | **Implemented** |
| LRN-16b | GET | `/assignment-submissions/{submission_id}/files/{file_index}` | **(audit fix, ADM-47, added)** Short-lived (≤ 5 min) presigned GET for one attached file of a submission, from the uploads bucket: `{url, expires_at, filename}`. Allowed for the submission's owner or staff with `assignment.grade` on the assignment scope; anyone else (and an out-of-range index) → `404 not_found`. Operation `lrn_16b_submission_file`, tag L3R | owner (S) or `assignment.grade` @B/@C | — | — | L3R | **Implemented (added)** |
| LRN-17 | POST | `/assignment-submissions/{submission_id}/grade` | Grade (rubric/points, inline comments, return for resubmission). Rubric scoring and late penalty: see below | `assignment.grade` @B/@C | — | opt | — | **Implemented** |
| LRN-18 | POST | `/assignments/{assignment_id}/release-grades` | Release grades | `assignment.grade` @B/@C | — | opt | — | **Implemented** |
| LRN-19 | POST | `/assignment-submissions/{submission_id}/grade-override` | Change a released grade (reason required, audited) | `grade.override_released` @B/@C | S10 | opt | — | **Implemented** |
| LRN-20 | POST | `/certificates` | Issue a certificate outside the automatic rule | `certificate.issue_manual` @P | — | Req | — | **Implemented** |
| LRN-21 | POST | `/certificates/{certificate_id}/revoke` | Revoke with reason (verify page shows date only) | `certificate.revoke` @P | S10 / P5 by tier | opt | — | **Implemented** |
| LRN-22 | GET | `/enrolments` | Enrolments in scope (`?batch_id=&course_id=`) | `enrolment.read` @O/@B | — | — | — | **Implemented** |
| LRN-23 | POST | `/enrolments` | Manage enrolments (assign course to batch) | `enrolment.manage` @O/@B | — | opt | — | **Implemented** |
| LRN-24 | GET | `/progress` | Learners' progress in scope (BR-ENT-14 visibility) | `progress.read` @O/@B | — | — | — | **Implemented** |
| LRN-25 | GET | `/me/bookmarks` | Bookmarks and notes | S | — | — | — | Planned |
| LRN-26 | POST | `/me/bookmarks` | Add bookmark/note on lesson or question | S | — | opt | — | Planned |
| LRN-27 | DELETE | `/me/bookmarks/{bookmark_id}` | Remove bookmark | S | — | — | — | Planned |

`LRN-13` response: `{"public_code": "K7Q2M9XH4TPA", "status": "valid", "name_on_certificate": "Ananya Reddy", "course_title": "Data Structures for Placements", "issued_at": "2026-10-28", "identity_verified": true, "issuer": "Tech Drona"}`; revoked → `{"status": "revoked", "revoked_on": "2026-11-02"}` (no reason). Not found → `404 not_found`. Rate limit 60/min per IP; no enumeration hints.

**Rubric schema (LRN-14/15/17; audit fix, FR-LRN-005).** `assignments.rubric` is `null` or:

```json
{"criteria": [
  {"key": "correctness", "label": "Correctness", "max_points": 6, "description": "optional", "levels": [{"label": "Full", "points": 6}, {"label": "Partial", "points": 3}]},
  {"key": "style", "label": "Code style", "max_points": 4}
]}
```

- `criteria`: 1–30 items. `key` matches `^[A-Za-z0-9_.-]{1,64}$` and is unique; `label` 1–200 chars; `max_points` > 0 and ≤ 10000; `description` ≤ 1000 chars (optional); `levels` (optional, ≤ 10) `{label (1–100), points (0..10000)}`. Unknown members are rejected.
- LRN-14/15 checks: duplicate key → `422` `rubric.criteria.{i}.key` `duplicate`; a level above its criterion's `max_points` → `too_high`; the sum of `max_points` above the assignment's `max_score` → `422` `rubric` `exceeds_max_score`.
- LRN-17 body: `{action: "grade"|"return", score?, rubric_scores?: {criterion_key: points}, feedback_md?, returned_reason?}`. When the assignment has a rubric in this shape, `rubric_scores` must score **every** criterion (`required`), unknown keys are rejected (`unknown`), and each score is 0..`max_points` (`too_high`). `score` may be omitted and defaults to the rubric total; if both are sent they must match (±0.01) or `422` `score` `rubric_mismatch`. Rubrics stored earlier in another shape are not checked.
- **Late penalty (BE-08, `learning_0002`):** grading a submission made after `due_at` stores the grader's `raw_score` and the final `score = raw_score × (1 − late_penalty_pct/100)` (2 dp), and records the applied `late_penalty_pct` (null when on time). Submission views (staff and learner) return `score`, `raw_score` and `late_penalty_pct`; a grade override (LRN-19) sets the final score explicitly and clears the penalty.

---

## 13. Placement preparation (`placement`)

Practice delivery DTOs never contain `is_correct`, `answer_key` or explanations until the student has answered that question (practice shows feedback immediately after each answer, FR-PLC-005). Mastery and recommendations for minors use only assessment and practice results (BR-MIN-02); personalised recommendations require `analytics_personalisation` consent (item C, default off, PO-04); basic progress is always shown under `core_service`.

### 13.1 Catalogue (PLC)

> **Removed 2026-11-14** ([feature-removal-plan.md](cleanup/feature-removal-plan.md) §3.1–3.2): company paths (PLC-18 `PUT /studio/company-paths/{id}`, PLC-32 `GET /me/company-paths/{slug}`), mentoring (PLC-36..46: `/mentoring/*`, `/me/mentoring/bookings`, `/mentor/*`) and résumé reviews (PLC-50..52). The résumé builder (`/me/resumes*`, PLC-47..49) and `GET`/`POST /studio/companies` stay.

| ID | Method | Path | Summary | Permission @ scope | Step-up | Idem | Tag | Status |
|---|---|---|---|---|---|---|---|---|
| PLC-01 | GET | `/placement/subjects` | Taxonomy tree (subject → topic → subtopic) with question counts | public | — | — | PUB | **Implemented** |
| PLC-02 | POST | `/studio/topics` | Create topic node | `taxonomy.manage` @P | — | opt | — | **Implemented** |
| PLC-02b | GET | `/studio/topics` | **(audit fix, added)** Studio taxonomy tree **including deactivated nodes** (PLC-01 stays active-only), so managers can find and reactivate them via PLC-03. Response `{items: [...tree]}` | `taxonomy.manage` @P | — | — | — | **Implemented (added)** |
| PLC-03 | PATCH | `/studio/topics/{topic_id}` | Rename/move node (dependent-count warning) | `taxonomy.manage` @P | — | — | — | **Implemented** |
| PLC-04 | GET | `/studio/questions` | Question bank search (`topic_id`, `difficulty` 1–5, `tag`, `company_id`, `status` `draft\|active\|retired`, `author`; `limit` 1–200 default 50, `offset`). **(audit fix)** `q` (2–200 chars): case-insensitive match on the latest version's stem text (HTML stripped, LIKE wildcards escaped); `version_status` (`draft\|in_review\|awaiting_review\|approved\|published\|retired`) filters on the latest version. Each item carries `retired_reason` and `latest_version.reviewed` | `question.create` @P/@C/@O | — | — | — | **Implemented** |
| PLC-05 | POST | `/studio/questions` | Create question (draft version) | `question.create` @P/@C/@O | — | opt | — | **Implemented** |
| PLC-06 | GET | `/studio/questions/{question_id}` | Question with versions; keys/explanations only for author, reviewer or `question.answer_key.read`. **(audit fix)** Returns `retired_reason` and each version's `review_comment` | `question.edit` @P/@C/@O | — | — | — | **Implemented** |
| PLC-07 | POST | `/studio/questions/{question_id}/versions` | Edit → new draft version (published versions immutable) | `question.edit` | — | opt | — | **Implemented** |
| PLC-08 | POST | `/studio/questions/{question_id}/submit-review` | Draft → `in_review` (explanation mandatory) | `question.edit` | — | opt | — | **Implemented** |
| PLC-09 | POST | `/studio/questions/{question_id}/review` | Approve or request changes (reviewer ≠ author **and ≠ any editor of the version**, `403 sod_violation`; ADM-46). The review comment is persisted and audited (ADM-55) | `question.review` @P | — | opt | — | **Implemented** |
| PLC-10 | POST | `/studio/questions/{question_id}/publish` | Publish version (the author and every editor of the version are refused, `403 sod_violation`; ADM-48) | `question.publish` @P | — | opt | — | **Implemented** |
| PLC-11 | POST | `/studio/questions/{question_id}/retire` | Retire version | `question.retire` @P | — | opt | — | **Implemented** |
| PLC-12 | POST | `/studio/question-imports` | Bulk import (CSV/XLSX/JSON) → validation job; imported questions enter `draft` | `question.import` @P | — | Req | — | Planned |
| PLC-13 | GET | `/studio/question-imports/{job_id}` | Preview (row errors, similar-stem duplicates) | `question.import` @P | — | — | — | Planned |
| PLC-14 | POST | `/studio/question-imports/{job_id}/commit` | Commit import | `question.import` @P | — | Req | — | Planned |
| PLC-15 | GET | `/studio/questions/{question_id}/stats` | Item statistics (p-value n ≥ 30, point-biserial n ≥ 50, review flags; k ≥ 10, no learner identities) | `question.edit` @P / `analytics.read` @C | — | — | — | Planned |
| PLC-16 | GET | `/studio/companies` | Companies and company paths | `company_path.manage` @P | — | — | — | **Implemented** |
| PLC-17 | POST | `/studio/companies` | Create company | `company_path.manage` @P | — | opt | — | **Implemented** |
| PLC-19 | POST | `/practice/sessions` | Start a practice set (subject/topic/difficulty or path step; 10 questions; adaptive next set P1) | S + entitlement | — | **Req** | — | **Implemented** |
| PLC-20 | GET | `/practice/sessions/{session_id}` | Session state (served questions without keys; answered ones with feedback) | S | — | — | — | **Implemented** |
| PLC-21 | POST | `/practice/sessions/{session_id}/answers` | Answer one question → immediate correctness + explanation | S + entitlement | — | **Req** | — | **Implemented** |
| PLC-22 | POST | `/practice/sessions/{session_id}/questions/{question_version_id}/reveal` | Reveal hint or solution (recorded; lowers mastery weight) | S | — | opt | — | **Implemented** |
| PLC-23 | POST | `/practice/sessions/{session_id}/complete` | Complete set → summary | S | — | opt | — | **Implemented** |
| PLC-24 | GET | `/me/practice/review` | Incorrect and bookmarked questions for re-practice | S | — | — | — | **Implemented** |
| PLC-25 | GET | `/me/mastery` | Topic mastery bands + weighted accuracy + n (`mastery-1.0`), company readiness | S | — | — | L3R | **Implemented** |
| PLC-26 | GET | `/me/recommendations` | "Next best practice" (≤ 5) with "why recommended" | S (consent C for personalised items) | — | — | — | **Implemented** |
| PLC-27 | POST | `/me/recommendations/{recommendation_id}/dismiss` | Dismiss | S | — | opt | — | **Implemented** |
| PLC-28 | GET | `/me/goals` | Goal picker values | S | — | — | — | Planned |
| PLC-29 | PUT | `/me/goals` | Target companies (≤ 5), role, drive date, year | S | — | — | — | Planned |
| PLC-30 | GET | `/me/learning-path` | Generated path (courses, sets, mocks) | S | — | — | — | Planned |
| PLC-31 | PATCH | `/me/learning-path` | Reorder/skip steps | S | — | — | — | Planned |
| PLC-33 | POST | `/questions/{question_id}/reports` | Report an error in a question (creates content review ticket) | S | — | opt | — | Planned |
| PLC-34 | GET | `/studio/question-reports` | Reported-error queue | `question.edit` @P | — | — | — | Planned |
| PLC-35 | POST | `/studio/question-reports/{report_id}/resolve` | Resolve (reporter notified) | `question.edit` @P | — | opt | — | Planned |
| PLC-47 | GET | `/me/resumes` | Résumés | S | — | — | — | Planned |
| PLC-48 | PUT | `/me/resumes/{resume_id}` | Save résumé (sections; certificates auto-filled) | S | — | — | — | Planned |
| PLC-49 | POST | `/me/resumes/{resume_id}/export` | Render PDF (async; signed URL) | S | — | opt | — | Planned |

#### PLC-21 · POST `/practice/sessions/{session_id}/answers` (representative)

Request `{"question_version_id": "0193c1d2-...", "response": {"option_ids": ["0193c1d3-..."]}, "time_spent_ms": 48210, "client_attempt_no": 1}` → `200`:

```json
{
  "is_correct": false,
  "correct_option_ids": ["0193c1d4-..."],
  "explanation_html": "<p>Let the cost price be 100…</p>",
  "attempt_no": 1,
  "mastery_delta": {"topic_id": "0193b9...", "band_before": "developing", "band_after": "developing"},
  "next_question_version_id": "0193c1e0-..."
}
```

Server-side: scoring is server-side; `practice_responses` rows with `attempt_no`, `served_at`, hint/solution flags; restriction ≥ L3 blocks practice answer saves (security doc §7.6). The practice answer event is emitted by the server via the outbox (clients cannot send it to `ANL-01`, `server_only_event`).

---

## 14. Assessments: tests, assignments, overrides, results (`assessments`)

### 14.1 Catalogue (ASM)

| ID | Method | Path | Summary | Permission @ scope | Step-up | Idem | Tag | Status |
|---|---|---|---|---|---|---|---|---|
| ASM-01 | GET | `/me/tests` | Available, scheduled, completed tests (batch-assigned + purchased + free) with windows and attempts left | `test.results.read` S | — | — | L3R | **Implemented** |
| ASM-02 | GET | `/tests/{test_id}` | Instructions, pattern, sections, marking, integrity notice, window, attempts left, eligibility (no questions) | S + entitlement or assignment | — | — | — | **Implemented** |
| ASM-03 | GET | `/studio/tests` | Tests owned/assigned in scope (`?status=`). **(audit fix, BE-21)** Signed cursor: `?cursor=&limit=` (1..100, default 100), response `{items, page}` (§1.10 `page`; `invalid_cursor` → 400). A page may hold fewer than `limit` items after the per-scope filter; follow `page.has_more`. Batch-scoped trainers see only tests owned by their batch (`batch_id`) or, for legacy tests without one, tests they created (ADM-49) | `test.create` @P/@O/@B/@C | — | — | — | **Implemented** |
| ASM-03b | GET | `/studio/assignable-tests` | **(audit fix, ADM-36, added)** Published tests a college can assign: its own published tests plus platform tests. `?organization_id=` (required), `cursor`, `limit` (1..100); response `{items, page}` | `test.assign` @O (or a batch of that org) | — | — | — | **Implemented (added)** |
| ASM-04 | POST | `/studio/tests` | Create test (kind, duration, grace, navigation mode, attempts, grading method, shuffle, review policy, integrity settings, pass %). **(audit fix, ADM-49, `assessments_0003`)** Optional `batch_id`: the owning batch (owner org = the batch's org); stored as `tests.batch_id` and returned by every test view. Every trainer of that batch may edit a batch-owned test; trainers of other batches may not | `test.create` | — | opt | — | **Implemented** |
| ASM-05 | GET | `/studio/tests/{test_id}` | Test definition | `test.edit` | — | — | — | **Implemented** |
| ASM-06 | PATCH | `/studio/tests/{test_id}` | Edit settings (refused after `settings_locked_at`) | `test.edit` | — | — | — | **Implemented** |
| ASM-07 | PUT | `/studio/tests/{test_id}/sections` | Replace sections and draw rules (fixed / random by topic, difficulty, tags, company). **(audit fix)** `RuleIn`: a `fixed` rule needs exactly one of `question_id` or `coding_problem_id` (resolved to the published bank `coding` question wrapping that problem; none → `422`) and `draw_count` 1; a `random` rule may set `question_types` including `"coding"` (draws published coding questions of the topic subtree; omitted = objective types only) | `test.edit` | — | — | — | **Implemented** |
| ASM-08 | POST | `/studio/tests/{test_id}/validate` | Check draw feasibility (enough published questions per rule) | `test.edit` | — | opt | — | **Implemented** |
| ASM-09 | POST | `/studio/tests/{test_id}/publish` | Publish (bumps `version`) | `test.edit` | — | opt | — | **Implemented** |
| ASM-10 | POST | `/tests/{test_id}/assignments` | Assign to batch/course/org with window, attempts, release mode (`immediate`, `after_window`, `scheduled`, `manual`) | `test.assign` @O/@B | — | opt | — | **Implemented** |
| ASM-11 | GET | `/tests/{test_id}/assignments` | Assignments of a test | `test.assign` @O/@B | — | — | — | **Implemented** |
| ASM-12 | PATCH | `/test-assignments/{assignment_id}` | Change window/release (window conflict warning) | `test.assign` @O/@B | — | — | — | **Implemented** |
| ASM-13 | POST | `/tests/{test_id}/overrides` | Extra time, extra attempt, window extension for a user or batch (reason; audited) | `test.override.grant` @O/@B (support: outage only, with ticket ref) | — | opt | — | **Implemented** |
| ASM-14 | GET | `/tests/{test_id}/overrides` | Overrides | `test.override.grant` | — | — | — | **Implemented** |
| ASM-15 | GET | `/tests/{test_id}/attempts` | Attempts and results in scope (status, score, integrity status, rebinds) | `test.results.read` @O/@B | — | — | — | **Implemented** |
| ASM-16 | POST | `/tests/{test_id}/results/release` | Release results (manual mode) | `test.results.release` @O/@B | — | opt | — | **Implemented** |
| ASM-17 | POST | `/attempts/{attempt_id}/regrade` | Regrade after key correction (new `scoring_version`; students notified) | `attempt.regrade` @B/@P | — | opt | — | Planned |
| ASM-18 | POST | `/attempts/{attempt_id}/invalidate` | Invalidate after human review (reason; student notified with appeal link) | `attempt.invalidate` @O/@B | S10 | opt | — | Planned |
| ASM-19 | GET | `/integrity/flags` | Advisory integrity events and similarity pairs ("review recommended"; no IP) | `integrity.flag.read` @O/@B | — | — | — | Planned |
| ASM-20 | POST | `/attempts/{attempt_id}/integrity-decision` | Record review outcome (`no_action`, `refer_security`, `invalidate`) | `integrity.flag.decide` @B | — | opt | — | Planned |
| ASM-21 | POST | `/attempts/{attempt_id}/rebind-override` | Trainer override that allows a rebind on a proctored drive or beyond the rebind limit | `test.override.grant` @O/@B | — | opt | — | **Implemented** |
| ASM-22 | GET | `/tests/{test_id}/report` | Score distribution, item analysis (difficulty, discrimination; k ≥ 10), section times, submit vs auto-submit | `test.results.read` @O/@B, content managers item stats only | — | — | — | Planned |
| ASM-23 | GET | `/tests/{test_id}/leaderboard` | Opt-in leaderboard (display name or "Student #1234"); provisional until similarity pass (P1) | S + entitlement | — | — | — | Planned |

`ASM-06/07` after the first attempt → `409 test_settings_locked` (SoD-08). `ASM-13` request `{"user_id": "0193...", "extra_time_seconds": 900, "extra_attempts": 0, "window_extension_seconds": 0, "reason": "accessibility"}` → `201`. Accessibility profiles (FR-ASM-013) are applied automatically as overrides at attempt start.

---

## 15. Assessment attempts (`assessments`)

### 15.1 Rules common to all attempt endpoints

- **Server-authoritative timer.** On start: `started_at = now()`, `deadline_at = min(started_at + duration + override_extra, window_end + override_window_ext)`; section deadlines in `attempt_sections.deadline_at`. Every attempt response includes `server_now`, `deadline_at` and the current section deadline; client clocks are never trusted. Writes after `deadline_at + grace_seconds` (default 30 s; 0 s for drives) → `409 attempt_closed`. Auto-submit by the `critical` sweeper (Redis ZSET every 5 s + DB safety sweep every 60 s), `submit_reason = deadline`.
- **Session binding.** The attempt is bound to `bound_session_id` / `bound_device_id`. Any attempt endpoint called from another session **on a different device** returns `409 attempt_bound_elsewhere` (except `ATT-02`, which returns the read-only summary in the same problem body). A new session on the **same `device_id`** (re-login after a crash on the same browser profile) re-attaches the attempt instead: `200` with `"reattached": true`, `rebind_count` unchanged, no OTP even at ≥ L2, `attempt_events.reattach_same_device` (RE §7.4; AMB-08). Multiple tabs of the same session share the binding.
- **Session hold.** While an attempt is in progress its bound session has `idle_hold_until = deadline_at + grace + 5 min` (set on start and on re-attach/rebind); idle expiry is not enforced before then (§1.4 step 3). Sessions holding an in-progress attempt are never auto-evicted by the session cap (AUTH-06).
- **Answer keys never leave the server before the review policy allows it.** Delivery DTOs (`QuestionDelivery`) have no key fields; a contract test asserts no delivery schema contains `is_correct`, `answer_key`, `explanation`, `correct_option_ids` or hidden test data. Review endpoints compute the current phase (`during`, `after_submit`, `after_close`, `release_at`) server-side and include key fields only when that phase allows.
- **Restrictions.** Start and rebind require restriction < L3 and L2 owner verification of the device. A sharing L3 that becomes due mid-attempt is deferred until the attempt ends or its deadline passes (max 3 h); a takeover revocation is immediate, autosaved answers are kept, the deadline job closes the attempt and records `attempt_events.session_revoked_security` so a trainer can grant an override.
- **Integrity events** (`focus_lost`, `focus_gained`, `fullscreen_exit`, `paste`, `disconnect`, `reconnect`) are advisory and ride along with autosave; collected only with `assessment_integrity` consent for that test (G); never auto-penalised.
- Entitlement expiry during an attempt does not stop it (BR-ENT-08).

### 15.2 Catalogue (ATT)

| ID | Method | Path | Summary | Permission @ scope | Step-up | Idem | Tag | Rate limit | Status |
|---|---|---|---|---|---|---|---|---|---|
| ATT-01 | POST | `/attempts` | Start an attempt (layout frozen, deadline set, bound to this session) | S + entitlement or active assignment | — | **Req** | — | 10/min per user | **Implemented** |
| ATT-02 | GET | `/attempts/{attempt_id}/state` | Resume state: frozen layout (no keys), saved responses with `client_seq`, deadlines, `server_now`; other session → `409` with read-only summary | S | — | — | — | 30/min | **Implemented** |
| ATT-03 | POST | `/attempts/{attempt_id}/resume` | Resume in the bound session after crash/reconnect (logs `resume`), or re-attach from a new session on the same device (`reattached: true`, no rebind consumed) | S | — | opt | — | 10/min | **Implemented** |
| ATT-04 | POST | `/attempts/{attempt_id}/rebind/otp` | Send rebind OTP (only when required: restriction level ≥ `assessment.rebind_requires_otp_at_level`, default L2) | S | — | opt | — | OTP caps | **Implemented** |
| ATT-05 | POST | `/attempts/{attempt_id}/rebind` | Move the attempt to this session after explicit confirmation (≤ 2 rebinds; proctored drives need trainer override) | S | — | **Req** | — | 5/h | **Implemented** |
| ATT-06 | POST | `/attempts/{attempt_id}/autosave` | Upsert ≤ 50 answers (newer `client_seq` wins) + integrity events | S | — | exempt (per `client_seq`) | — | 30/min per attempt (burst 10) | **Implemented** |
| ATT-07 | GET | `/attempts/{attempt_id}/time` | Timer sync (`server_now`, deadlines) — client re-syncs every 60 s and on reconnect | S | — | — | — | 4/min | **Implemented** |
| ATT-08 | POST | `/attempts/{attempt_id}/sections/{section_id}/enter` | Enter a section (sequential / section-locked; sets section deadline) | S | — | opt | — | — | **Implemented** |
| ATT-09 | POST | `/attempts/{attempt_id}/sections/{section_id}/submit` | Submit a section (locks it) | S | — | opt | — | — | **Implemented** |
| ATT-10 | POST | `/attempts/{attempt_id}/submit` | Final submit (with final flush) → scoring queued | S | — | **Req** | — | 5/min | **Implemented** |
| ATT-11 | GET | `/attempts/{attempt_id}/result` | Result per review policy (score, sections, accuracy, time per question, rank/percentile with `provisional` flag) | `test.results.read` S \| @O/@B | — | — | L3R | — | **Implemented** |
| ATT-12 | GET | `/attempts/{attempt_id}/review` | Question-by-question review; keys/explanations only when the phase allows. **(audit fix, BE-23)** Coding items carry `your_submission`: the scored submission (pinned, else newest judged) with the learner's own `source_code`; verdict, score and per-case results only when correctness is visible; hidden cases stay verdict-only | `test.results.read` S \| @O/@B (`question.answer_key.read` for staff outside student rules) | — | — | L3R | — | **Implemented** |
| ATT-13 | GET | `/me/attempts` | Own attempts (`?test_id=`), newest first. **(audit fix, BE-21)** Signed cursor on `(started_at, id)`: `?cursor=&limit=` (1..100, default 100), response `{items, page}` | S | — | — | L3R | — | **Implemented** |

### 15.3 Detail entries (attempts)

#### ATT-01 · POST `/attempts`

Headers: `Idempotency-Key: 0193c2a0-5b6c-7d8e-9f01-2a3b4c5d6e7f`.

Request:

```json
{"test_id": "0193c100-aaaa-7bbb-8ccc-ddddeeeeffff", "test_assignment_id": "0193c101-1111-7222-8333-444455556666", "integrity_consent": true, "client_info": {"fullscreen_supported": true, "tz_offset_min": 330}}
```

Response `201`:

```json
{
  "attempt_id": "0193c2a1-0000-7111-8222-333344445555",
  "attempt_no": 1,
  "status": "in_progress",
  "test": {"id": "0193c100-aaaa-7bbb-8ccc-ddddeeeeffff", "version": 3, "title": "TCS NQT Full Mock 4", "navigation_mode": "section_locked", "grace_seconds": 0},
  "server_now": "2026-11-03T10:15:02.123Z",
  "started_at": "2026-11-03T10:15:02.100Z",
  "deadline_at": "2026-11-03T11:45:02.100Z",
  "sections": [
    {"section_id": "0193c110-...", "title": "Numerical Ability", "position": 1, "status": "active", "deadline_at": "2026-11-03T10:55:02.100Z",
     "questions": [
       {"question_version_id": "0193c201-...", "type": "mcq_single", "stem_html": "<p>A shopkeeper marks an article 25% above cost…</p>", "options": [{"option_id": "0193c202-...", "html": "12%"}, {"option_id": "0193c203-...", "html": "15%"}, {"option_id": "0193c204-...", "html": "20%"}, {"option_id": "0193c205-...", "html": "25%"}], "marks": 1, "negative_marks": 0.25}
     ]},
    {"section_id": "0193c111-...", "title": "Reasoning Ability", "position": 2, "status": "not_started", "duration_seconds": 1500}
  ],
  "binding": {"bound_session_id": "current", "rebinds_remaining": 2},
  "autosave": {"debounce_ms": 5000, "max_interval_ms": 10000, "max_items": 50}
}
```

Errors: `idempotency_key_required`, `entitlement_required`, `contact_not_verified` (timed tests need verified contacts), `account_restricted` (via principal gate), `device_verification_required` (L2), `test_not_open`, `test_window_closed`, `attempt_limit_reached`, `active_attempt_exists` (with `attempt_id` to resume), `consent_required` (`assessment_integrity` when the test collects integrity events and `integrity_consent` is false and the test makes it mandatory), `minor_consent_pending`, `session_too_short_for_attempt` (`absolute_expires_at < deadline_at + grace + 5 min`; the student re-authenticates for a fresh absolute window — no rebind is involved because the attempt has not started).

Server-side enforcement: entitlement or active assignment (`entitlements.check`, §19), `attempts_allowed` + overrides, one in-progress attempt per test per user (`ux_att_one_open`), selection seed and frozen `layout` (question versions + option order), `settings_locked_at` set on the first attempt of a test, `bound_session_id`/`bound_device_id` set, `auth_sessions.idle_hold_until = deadline_at + grace + 5 min` on the bound session, `ZADD attempt_deadlines`, `attempt_events.start`, outbox for analytics. Questions are returned stripped of keys; for `section_locked` only the active section's questions are returned.

#### ATT-02 · GET `/attempts/{attempt_id}/state` from another session

```json
{
  "type": "https://techdrona.in/problems/attempt-bound-elsewhere",
  "title": "This test is open on another device",
  "status": 409,
  "code": "attempt_bound_elsewhere",
  "detail": "This test is open on Chrome on Windows. Continue here?",
  "request_id": "01JC9Y2B3C4D5E6F7G8H9J0K1L",
  "bound_device_label": "Chrome on Windows",
  "bound_since": "2026-11-03T10:15:02.100Z",
  "rebind_allowed": true,
  "rebinds_remaining": 2,
  "otp_required": false,
  "trainer_override_required": false,
  "read_only": {"answered_count": 14, "deadline_at": "2026-11-03T11:45:02.100Z", "server_now": "2026-11-03T10:31:44.020Z"}
}
```

From the bound session, `200` with the resume payload (same shape as ATT-01 plus `responses: [{question_version_id, response, client_seq, flagged, saved_at}]`). From another session on the **same `device_id`** (`ATT-02` or `ATT-03`), `200` with the resume payload plus `"reattached": true`: the binding moves to the new session, `rebind_count` is unchanged, no OTP is needed, `attempt_events.reattach_same_device` is written and `idle_hold_until` is set on the new session. A `409` from a session on a different device writes `security_signals` `cap.attempt_bind`; abandoning the rebind feeds SH-08 for adults.

#### ATT-05 · POST `/attempts/{attempt_id}/rebind`

Request `{"confirm": true, "otp_code": null}` → `200` resume payload; the previous session gets an SSE event and further writes from it return `409 attempt_bound_elsewhere`. `rebind_count` increments only when `bound_device_id` changes (a same-device re-attach never counts); `attempt_events.rebind` (and `rebind_requested` / `rebind_refused`) recorded and visible to the trainer.

Errors: `rebind_limit_reached` (`rebind_count ≥ assessment.max_rebinds_per_attempt`, default 2, unless an `ASM-21` override exists), `validation_failed` (`otp_required` — restriction level ≥ L2), `otp_invalid`, `permission_denied` with `trainer_override_required: true` (proctored drives, `assessment.single_device_binding` locked), `attempt_closed`, `account_restricted`.

#### ATT-06 · POST `/attempts/{attempt_id}/autosave`

Request:

```json
{
  "items": [
    {"question_version_id": "0193c201-...", "response": {"option_ids": ["0193c204-..."]}, "client_seq": 41, "time_spent_ms": 52340, "flagged": false},
    {"question_version_id": "0193c206-...", "response": {"value": "12.5"}, "client_seq": 42, "time_spent_ms": 18800, "flagged": true}
  ],
  "events": [
    {"type": "focus_lost", "client_at": "2026-11-03T10:22:10.400Z", "client_seq": 43},
    {"type": "focus_gained", "client_at": "2026-11-03T10:22:31.900Z", "client_seq": 44}
  ],
  "current_section_id": "0193c110-..."
}
```

Response `200`:

```json
{"acked_seq": 44, "server_now": "2026-11-03T10:22:33.010Z", "deadline_at": "2026-11-03T11:45:02.100Z", "section_deadline_at": "2026-11-03T10:55:02.100Z", "status": "in_progress"}
```

Server-side: `INSERT … ON CONFLICT (attempt_id, question_version_id) DO UPDATE … WHERE attempt_responses.client_seq < EXCLUDED.client_seq` (out-of-order and replay safe); question must belong to the frozen layout and to an open section (`409 section_locked`); `attempt_events.answer_saved`; response bodies validated per question type (option ids must belong to the version); `is_correct`/`marks_awarded` are never set here. Late writes after deadline + grace → `409 attempt_closed` with `status` (`auto_submitted`), so the client stops and shows the submitted screen. A `sendBeacon` fallback is not used for autosave (it needs the CSRF header); the client keeps IndexedDB and flushes on reconnect.

#### ATT-10 · POST `/attempts/{attempt_id}/submit`

Request `{"final_items": [ ... as autosave ... ], "confirm_unanswered": 3}` → `200 {"status": "submitted", "submitted_at": "...", "submit_reason": "user", "result_release": {"mode": "after_window", "release_at": "2026-11-05T12:30:00.000Z"}, "redirect": "/app/attempts/0193c2a1-.../submitted"}`. Guarded `UPDATE … WHERE status = 'in_progress'`; a replay or a race with the sweeper returns the current terminal state (`200`, `submit_reason` may be `deadline`). Scoring (`score_attempt`, idempotent by `(attempt_id, scoring_version)`) runs on the `critical` queue; outbox `attempt.submitted`.

#### ATT-11 · GET `/attempts/{attempt_id}/result`

```json
{
  "attempt_id": "0193c2a1-0000-7111-8222-333344445555",
  "status": "graded",
  "phase": "after_submit",
  "visible": {"score": true, "correctness": false, "answer_key": false, "explanation": false, "section_analytics": true, "rank": false},
  "score": 61.75, "max_score": 90, "percentage": 68.61,
  "correct_count": 66, "incorrect_count": 17, "unanswered_count": 7,
  "time_taken_seconds": 5310,
  "section_scores": [{"section_id": "0193c110-...", "title": "Numerical Ability", "score": 21.5, "max": 30, "time_s": 2380}],
  "rank": null, "percentile": null, "rank_provisional": true,
  "integrity_status": "none",
  "released_at": "2026-11-03T11:45:10.000Z"
}
```

Before release → `409 results_not_released` with `release_mode` and `release_at`. Fields not allowed in the current phase are omitted (not `null`-ed with a value hint). Percentile shown only when the reference cohort ≥ `analytics.k_min.percentile_reference` (20); otherwise `"percentile": null, "percentile_note": "insufficient_cohort"`. Invalidated attempts return `status: invalidated` with an appeal link.

#### ATT-12 · GET `/attempts/{attempt_id}/review`

Per question: `{"question_version_id", "stem_html", "options", "your_response", "is_correct"?, "correct_option_ids"?, "explanation_html"?, "marks_awarded"?, "time_spent_ms"}` where the `?` fields appear only when `review_policy[phase]` allows. Coding questions show own source and per-case verdicts; hidden cases never show input/expected output.

---

## 16. Coding (`coding`)

### 16.1 Rules common to coding endpoints

- **Hidden test cases are never returned** to the browser or to any staff role without `coding_test_case.hidden.read` (and then only through the audited `COD-17`). Results for hidden cases contain only `ordinal`, `verdict`, `time_ms`, `memory_kb` — never stdin, stdout, expected output, diff or checker messages (`ck_sr_hidden_output`). Sample/custom runs may return stdout excerpts ≤ 4 KiB.
- Student code never runs on app servers: the API enqueues; `worker-judge` (judge-gateway) talks to Judge0 Cloud (phase 1) or the isolated self-hosted judge (phase 2). The browser never talks to the judge. *(Implementation, COM-09: `worker-judge` is the DB poller `python -m app.modules.coding.worker`; the Celery `judge_*` queues are used only when `TD_CODING_SEND_TASKS=1`.)*
- Limits: source ≤ 64 KiB (`413 payload_too_large`), custom input ≤ 64 KiB; per-problem CPU/wall/memory limits from `coding_problems` × `judge_languages` multipliers.
- Rate limits (FR-COD-005): **Run ≤ 10/min**, **Submit ≤ 5/min** per user per problem; plus 1 in-flight `submit` per user and a global token bucket sized to the provider quota. Under saturation `run` is shed first (`409 judge_queue_full` + `Retry-After`); submissions inside an active attempt are never shed (queue `judge_assessment`).
- Restriction ≥ L3 blocks run and submit (security doc §7.6). Code is never written to security logs.

### 16.2 Catalogue (COD)

| ID | Method | Path | Summary | Permission @ scope | Step-up | Idem | Tag | Rate limit | Status |
|---|---|---|---|---|---|---|---|---|---|
| COD-01 | GET | `/coding/languages` | Enabled languages (key, display name, version, starter template) | any | — | — | — | — | **Implemented** |
| COD-02 | GET | `/coding/problems` | Problem list (topic, difficulty, company, status solved/attempted) | S (entitlement shown per item) | — | — | — | — | **Implemented** |
| COD-03 | GET | `/coding/problems/{slug}` | Statement, constraints, formats, **sample cases only**, limits, allowed languages, starter code. **(audit fix)** `{slug}` may also be the problem id (test items deliver `coding_problem_id`); optional `?attempt_id=`: see the in-attempt access rule below | S + entitlement, or S + in-progress attempt containing the problem | — | — | — | — | **Implemented** |
| COD-04 | PUT | `/coding/problems/{problem_id}/drafts/{language_key}` | Autosave editor code (every 5 s; owner-only, ≤ 64 KiB). Optional `?attempt_id=` (in-attempt access). Entitlement checked as for run/submit (`403 entitlement_required`, BE-20) | S + entitlement or in-progress attempt | — | — | — | 20/min | **Implemented** |
| COD-05 | GET | `/coding/problems/{problem_id}/drafts/{language_key}` | Load autosaved code (`404` when none). Optional `?attempt_id=`. Entitlement as for run/submit (BE-20) | S + entitlement or in-progress attempt | — | — | — | — | **Implemented** |
| COD-06 | POST | `/coding/problems/{problem_id}/run` | Run on samples + optional custom input. **(audit fix)** Body `attempt_id` (optional) for an in-test run: access through the attempt instead of an entitlement. The 202 body no longer carries `stream_url` | S + entitlement / in-progress attempt | — | **Req** | — | 10/min per user per problem | **Implemented** |
| COD-07 | POST | `/coding/problems/{problem_id}/submit` | Submit against all cases (practice, or inside an attempt with `attempt_id`) | S + entitlement / bound attempt | — | **Req** | — | 5/min per user per problem; 1 in flight | **Implemented** |
| COD-08 | GET | `/coding/submissions/{submission_id}` | Poll status and verdicts (hidden cases verdict-only). **(audit fix)** A batch-scoped reader is allowed only with `submission.code.read` on a batch whose active member made the submission and whose org matches the submission's org; otherwise `404` | S \| `submission.code.read` @B/@P | — | — | — | 60/min | **Implemented** |
| COD-09 | GET | `/coding/submissions/{submission_id}/stream` | Server-Sent Events for status changes (alternative to polling) | S | — | — | — | 5 concurrent streams per user | Planned |
| COD-10 | GET | `/me/coding/submissions` | Own submission history (`?problem_id=`) | S | — | — | — | — | **Implemented** |
| COD-11 | GET | `/coding/submissions/{submission_id}/diff/{other_submission_id}` | Diff of two own submissions | S | — | — | — | — | Planned |
| COD-12 | GET | `/coding/problems/{problem_id}/editorial` | Editorial (unlocked after solve or after N attempts) | S + entitlement | — | — | — | — | Planned |
| COD-13 | POST | `/studio/coding/problems` | Create problem (draft) | `coding_problem.manage` @P/@C | — | opt | — | — | **Implemented** |
| COD-14 | PATCH | `/studio/coding/problems/{problem_id}` | Edit statement, limits, languages, checker, scoring mode (bumps `version_no` when cases/limits change) | `coding_problem.manage` | — | — | — | — | **Implemented** |
| COD-15 | POST | `/studio/coding/problems/{problem_id}/test-cases` | Add a sample case (inline) or a hidden case (upload refs → envelope-encrypted in S3) | `coding_problem.manage` (samples) / `coding_test_case.hidden.read` (hidden) | — | opt | — | — | **Implemented** |
| COD-16 | GET | `/studio/coding/problems/{problem_id}/test-cases` | Case list: samples with content; hidden cases metadata only (ordinal, weight, size, sha256) | `coding_problem.manage` | — | — | — | — | **Implemented** |
| COD-17 | GET | `/studio/coding/test-cases/{test_case_id}/content` | Hidden case content (decrypted server-side; 5-min signed URL) | `coding_test_case.hidden.read` @P/@C (own problems) | S10 | — | — | 30/h; audited with reason | Planned — Planned — hidden cases stay in DB until S3/KMS (backlog A12) |
| COD-18 | POST | `/studio/coding/problems/{problem_id}/validate` | Run reference solution(s) on all cases; must pass before publish | `coding_problem.manage` | — | opt | — | 10/h | Planned |
| COD-19 | POST | `/studio/coding/problems/{problem_id}/publish` | Publish (reviewer ≠ author for platform) | `coding_problem.manage` @P (+ review) | — | opt | — | — | **Implemented** |
| COD-20 | GET | `/coding/submissions/{submission_id}/source` | Another user's submitted code | `submission.code.read` @B (own batches) / @P (reported issues, case-linked) | — | — | — | audited | Planned |
| COD-21 | POST | `/tests/{test_id}/similarity-runs` | Run cohort similarity check after close (MOSS/JPlag-style) | `similarity.run` @B/@P | — | opt | — | 5/day per test | Planned |
| COD-22 | GET | `/similarity-runs/{run_id}` | Similarity pairs above threshold with side-by-side diff refs (advisory flags) | `similarity.run` @B/@P | — | — | — | — | Planned |
| COD-23 | GET | `/studio/coding/problems/{problem_id}` | Studio problem detail (author view; hidden-case metadata only, never content) | `coding_problem.manage` @P/@O | — | — | — | — | **Implemented (added)** |
| COD-24 | GET | `/studio/coding/problems/published` | **(audit fix wave 3)** Read-only list of **published** coding problems for test builders (the ASM-07 coding-problem picker), so callers who can author tests but do not manage coding problems can add fixed coding items. Query `q` (title/slug search), `cursor`, `limit`. Response `{data: [{problem_id, slug, title, difficulty, version_no, organization_id}], page}`; metadata only (no statement, test cases or solutions). Platform-bank problems plus organization problems where the caller can author tests; 403 `permission_denied` (`test.create`) when the caller can author tests nowhere | authenticated; callers who can author tests (`test.create` at platform, organization or batch scope) | — | — | — | — | see note |

**COD-24 note:** shipped in fix wave 3 (operation `cod_24_studio_published_problems`); it is registered before `/studio/coding/problems/{problem_id}` so `published` is never parsed as an id.

**In-attempt access (COD-03/04/05/06/07; audit fix).** With `attempt_id` (query on COD-03/04/05, body on COD-06/07), access comes from the learner's own attempt instead of an entitlement: the attempt must be in progress and bound to this session, the problem must be part of the attempt, and its section must be open; otherwise `403`/`404` as for a missing entitlement. Without a registered attempt validator access is refused.

### 16.3 Detail entries (coding)

#### COD-07 · POST `/coding/problems/{problem_id}/submit`

Headers: `Idempotency-Key: 0193d0a0-1b2c-7d3e-8f4a-5b6c7d8e9f00`.

Request:

```json
{
  "language_key": "cpp17",
  "source_code": "#include <bits/stdc++.h>\nusing namespace std;\nint main(){int n;cin>>n;vector<long long>a(n);for(auto&x:a)cin>>x;/* … */}\n",
  "attempt_id": null,
  "practice_session_id": null
}
```

Response `202`:

```json
{
  "submission_id": "0193d0a1-2222-7333-8444-555566667777",
  "status": "queued",
  "mode": "submit",
  "queue": "judge_submit",
  "queue_position": 3,
  "problem_version": 2,
  "poll_url": "/api/v1/coding/submissions/0193d0a1-2222-7333-8444-555566667777",
  "stream_url": "/api/v1/coding/submissions/0193d0a1-2222-7333-8444-555566667777/stream"
}
```

Errors: `idempotency_key_required`, `entitlement_required`, `language_not_allowed`, `payload_too_large`, `rate_limited`, `submission_in_flight`, `attempt_bound_elsewhere` / `attempt_closed` (when `attempt_id` is set: the attempt must be in progress, bound to this session and contain this problem), `account_restricted`.

Server-side enforcement: `code_submissions` row (`mode = submit`, `idempotency_key`, `problem_version`, `judge_provider`, `queue_name`) inside the request transaction; enqueue `judge_assessment` (attempt) or `judge_submit`; the judge worker decrypts hidden cases with the KMS-wrapped data key (only its task role can), sends batches with network disabled and limits applied, polls with backoff (30 s budget, then `judge_timeout` + one automatic retry), writes `submission_results` and verdict/score, outbox `submission.judged`. Judge outage: submissions stay `queued` (max 15 min) and the response/poll shows `"status": "queued", "notice": "judge_degraded"`; for attempts the deadline is extended automatically by the outage duration (logged override, FR-COD-010). Score = Σ weights of passed cases (`weighted_cases`) or all-or-nothing. In tests, the last (or best, per test config) submission counts.

#### COD-08 · GET `/coding/submissions/{submission_id}`

```json
{
  "submission_id": "0193d0a1-2222-7333-8444-555566667777",
  "problem_id": "0193cf00-...",
  "language_key": "cpp17",
  "mode": "submit",
  "status": "completed",
  "verdict": "PARTIAL",
  "score": 70.0,
  "passed_cases": 7,
  "total_cases": 10,
  "max_time_ms": 412,
  "max_memory_kb": 18240,
  "compile_output": null,
  "cases": [
    {"ordinal": 1, "is_sample": true, "verdict": "AC", "time_ms": 3, "memory_kb": 3410, "stdout_excerpt": "6\n", "expected_output": "6\n", "input": "3\n1 2 3\n"},
    {"ordinal": 7, "is_sample": false, "verdict": "WA", "time_ms": 120, "memory_kb": 9100},
    {"ordinal": 9, "is_sample": false, "verdict": "TLE", "time_ms": 2000, "memory_kb": 18240}
  ],
  "queued_at": "2026-11-03T10:15:02.200Z",
  "completed_at": "2026-11-03T10:15:05.910Z"
}
```

Hidden cases (`is_sample: false`) carry only `ordinal`, `verdict`, `time_ms`, `memory_kb` — the response model for hidden cases has no other fields (contract test). Compile errors return `verdict: "CE"` with `compile_output` (≤ 16 KiB). Staff viewers with `submission.code.read` see the same shape plus `source_code`.

#### COD-06 · POST `/coding/problems/{problem_id}/run`

Request `{"language_key": "python3", "source_code": "n=int(input())\nprint(sum(map(int,input().split())))\n", "custom_input": "3\n1 2 3\n"}` → `202` as COD-07 with `"mode": "run"`, queue `judge_run`. Runs execute samples + the custom input only; never hidden cases. Practice run records are purged after 90 days.

#### COD-17 · GET `/studio/coding/test-cases/{test_case_id}/content`

Query `?reason=fixing+reported+issue+CMS-013-482`. Response `200 {"input_url": "https://files.techdrona.in/…&Expires=…", "expected_url": "…", "expires_at": "…", "sha256": {"input": "…", "expected": "…"}}`. Trainers only for problems they own (`course:{id}`/O-private); audited (`coding.testcase.read_hidden`, reason). Never cached.

---

## 17. Commerce (`commerce`)

### 17.1 Rules common to commerce endpoints

- Prices are INR paise, GST-inclusive for D2C display; the order splits taxable value and CGST+SGST (intra-state) or IGST (inter-state) by `place_of_supply`. The final price shown at checkout equals the product-page price (no drip pricing).
- **Payment is confirmed only** by a verified webhook (§18) or by the verified checkout signature **plus** a server-side fetch of the order/payment from Razorpay (`COM-06`). The browser callback alone never grants access. Both paths call the same idempotent `fulfil_order`; first arrival wins.
- Recurring prices and subscription mandates are capped at ₹15,000 (1,500,000 paise) per debit (`ck_price_mandate`, `ck_sub…mandate_max_amount_paise`).
- Card data is never stored or logged; only gateway ids, method, last4/network/issuer and masked VPA.
- Purchase requires verified contacts (`403 contact_not_verified`); minors need verified guardian consent and checkout shows the guardian as payer contact (`403 minor_consent_pending`, BR-ENT-21); adults need `security_monitoring` consent for paid plans (PO-03, `403 consent_required`).
- Money routes keep idempotency records for 7 days.
- **Vocabularies** (schema v0.3; resolves I-12, I-13). `products.product_kind` ∈ `free_resource`, `free_course`, `course`, `bundle`, `subscription_plan`, `placement_package`, `mock_pack`, `institution_seat`, `extra_learner_seat`. `orders.status` ∈ `created`, `pending_payment`, `paid`, `failed`, `expired`, `cancelled`, `refunded`, `partially_refunded`.
- **Refund dual control** (resolves I-22): a goodwill refund always creates an `approval_requests` row (stored in `refunds.approval_request_id`; DB CHECK `ck_refund_goodwill_dual`), and so does any refund above `commerce.refund.dual_approval_above_paise` (default 2,500,000 paise = ₹25,000); the approver is a second `finance_admin` (≠ requester).

### 17.2 Catalogue (COM)

| ID | Method | Path | Summary | Permission @ scope | Step-up | Idem | Tag | Rate limit | Status |
|---|---|---|---|---|---|---|---|---|---|
| COM-01 | GET | `/commerce/products` | Active products with plans, prices (GST breakup), refund rule text, what each unlocks | public | — | — | PUB | — | **Implemented** |
| COM-02 | GET | `/commerce/products/{sku}` | Product detail | public | — | — | PUB | — | **Implemented** |
| COM-03 | POST | `/commerce/checkout/quote` | Price preview: GST split, coupon validation, BR-ENT-05/06/07 overlap warnings | S | — | — | — | 30/min | **Implemented** |
| COM-04 | POST | `/commerce/orders` | Create order (+ Razorpay order); reserve coupon. **(audit fix, FE-27)** A matching unexpired pending order (same user, price, coupon, state and total) is resumed instead of duplicated: response carries its `checkout` and `resumed: true` | S | — | **Req** | — | 10/min; 30/day | **Implemented** |
| COM-05 | GET | `/commerce/orders/{order_id}` | Order status (polling page STU-017). **(audit fix)** Returns `checkout` for an unexpired pending order (FE-26) and `refunded_paise` | `order.read` S | — | — | AS | 20/min | **Implemented** |
| COM-06 | POST | `/commerce/orders/{order_id}/confirm` | Checkout callback: verify `razorpay_signature`, fetch payment server-side, fulfil | S | — | **Req** | — | 10/min | **Implemented** |
| COM-07 | POST | `/commerce/orders/{order_id}/cancel` | Cancel an unpaid order (releases coupon reservation) | S | — | opt | — | — | **Implemented** |
| COM-08 | GET | `/me/orders` | Own orders | `order.read` S | — | — | AS | — | **Implemented** |
| COM-09 | POST | `/commerce/subscriptions` | Create Razorpay subscription for a recurring price (mandate ≤ ₹15,000). **(audit fix, COM-10, `commerce_0003`)** Body `{price_id, billing?: {name?, state_code? (2 digits), gstin?}}`; `billing` is stored on the subscription and sets IGST vs CGST+SGST and the place of supply on every debit invoice | S | — | **Req** | — | 5/day | **Implemented** |
| COM-10 | POST | `/commerce/subscriptions/{subscription_id}/confirm` | Verify subscription checkout signature + server fetch | S | — | **Req** | — | 10/min | **Implemented** |
| COM-11 | GET | `/me/subscriptions` | Own subscriptions (status, next charge, pre-debit notice, grace) | S | — | — | AS | — | **Implemented** |
| COM-12 | POST | `/me/subscriptions/{subscription_id}/cancel` | One-click cancel at period end, immediate confirmation | `subscription.admin_cancel` S (own cancel) | — | **Req** | AS | 5/day | **Implemented** |
| COM-13 | POST | `/me/subscriptions/{subscription_id}/resume` | Undo a scheduled cancellation before period end | S | — | opt | AS | — | Planned |
| COM-14 | POST | `/me/subscriptions/{subscription_id}/change-plan` | Upgrade now (prorated) / downgrade at renewal (P1) | S | — | **Req** | — | 5/day | Planned |
| COM-15 | GET | `/me/invoices` | Own invoices and credit notes | `invoice.read` S | — | — | AS | — | **Implemented** |
| COM-16 | GET | `/me/invoices/{invoice_id}/pdf` | Signed URL (5 min) | `invoice.read` S | — | — | AS | — | Planned |
| COM-17 | GET | `/me/orders/{order_id}/refund-eligibility` | Evaluate the published refund rule (days, consumption %, certificate) | S | — | — | AS | — | **Implemented** |
| COM-18 | POST | `/me/refund-requests` | Request refund for an own order | `refund.decide` S (request own) | — | **Req** | AS | 3/day | **Implemented** |
| COM-19 | GET | `/me/refund-requests` | Own refund requests | S | — | — | AS | — | **Implemented** |
| COM-20 | GET | `/finance/products` | Products incl. drafts, plans, price history | `product.manage` @P | — | — | — | — | **Implemented** |
| COM-21 | POST | `/finance/products` | Create product + `product_items` (what it unlocks) | `product.manage` @P | P5 | opt | — | — | **Implemented** |
| COM-22 | PATCH | `/finance/products/{product_id}` | Edit / retire product | `product.manage` @P | P5 | — | — | — | **Implemented** |
| COM-23 | POST | `/finance/products/{product_id}/plans` | Create plan (one-time with access days, or recurring interval) | `price.manage` @P | P5 | opt | — | — | **Implemented** |
| COM-24 | POST | `/finance/plans/{plan_id}/prices` | Create price with validity window (no overlapping active windows) | `price.manage` @P | P5 (+Dual if > 20% decrease or the plan has active subscriptions) | **Req** | — | — | **Implemented** |
| COM-25 | GET | `/finance/coupons` | Coupons with redemption stats. **(audit fix)** `?status=active\|paused\|expired` (server-side), keyset `cursor`/`limit` (1..500, default 100), `page`; each coupon carries `approval_request_id` of its pending `commerce.coupon.activate` approval, or `null` (also on COM-27 responses) | `coupon.manage` @P | — | — | — | — | **Implemented** |
| COM-26 | POST | `/finance/coupons` | Create coupon. `201` with the coupon, or **`202`** when Dual applies: the coupon is created `paused` and the response is the coupon object (own `status: "paused"`, `approval_request_id`) plus the approval envelope fields `approval_status`, `action_type` (`commerce.coupon.activate`), `required_approver_role` and `expires_at` | `coupon.manage` @P | P5 (+Dual if > 50% off or > 1,000 redemptions) | opt | — | — | **Implemented** |
| COM-27 | PATCH | `/finance/coupons/{coupon_id}` | Pause/resume/edit window (loosening re-checks the Dual thresholds) | `coupon.manage` @P | P5 | — | — | — | **Implemented** |
| COM-28 | GET | `/finance/orders` | Orders and payments search | `order.read` @P (`payment.read` for payment rows) | — | — | — | — | **Implemented** |
| COM-29 | GET | `/finance/orders/{order_id}` | Order with items, payments (masked), webhook event summary, entitlements, invoice | `order.read` @P | — | — | — | — | **Implemented** |
| COM-30 | GET | `/finance/refunds` | Refund queue with rule evaluation | `refund.decide` @P | — | — | — | — | **Implemented** |
| COM-31 | POST | `/finance/refunds/{refund_id}/decision` | Approve/reject; processes via Razorpay | `refund.decide` @P (`refund.goodwill` outside rule) | **P5** (+Dual: goodwill, or > ₹25,000) | **Req** | — | — | **Implemented** |
| COM-32 | POST | `/finance/refunds` | Finance-initiated refund. `reason_code`: `duplicate_payment`, `service_failure`, `content_issue`, `goodwill`, **`price_adjustment`** (audit fix, COM-01, `commerce_0003`) or `other`. `price_adjustment` and `duplicate_payment` are money corrections that keep access; every other reason revokes the order's access at approval unless `order_item_ids` narrows it | `refund.decide` @P | **P5** (+Dual as COM-31) | **Req** | — | — | **Implemented** |
| COM-33 | GET | `/finance/subscriptions` | Subscriptions, grace, cancellations | `order.read` @P | — | — | — | — | **Implemented** |
| COM-34 | POST | `/finance/subscriptions/{subscription_id}/cancel` | Cancel on a user's behalf (ticket ref) | `subscription.admin_cancel` @P | P5 (finance) / S10 (support) | **Req** | — | — | **Implemented** |
| COM-35 | GET | `/finance/invoices` | Invoices and credit notes | `invoice.read` @P | — | — | — | — | **Implemented** |
| COM-36 | POST | `/finance/invoices/{invoice_id}/credit-notes` | Issue credit note (gap-free `TDCN` series) | `invoice.credit_note` @P | P5 | **Req** | — | — | **Implemented** |
| COM-37 | POST | `/finance/gst-exports` | GST register export (async → `ANL-13/14`) | `invoice.read` @P + `report.export.request` @P | P5 | opt | — | 10/day | Planned |
| COM-38 | GET | `/finance/contracts` | Institution contracts | `contract.manage` @P | — | — | — | — | **Implemented** |
| COM-39 | POST | `/finance/contracts` | Create contract (org, product, seats, dates, price per seat, PO, billing schedule, grace days, reassignment allowance, DPA version) | `contract.manage` @P | P5 | **Req** | — | — | **Implemented** |
| COM-40 | PATCH | `/finance/contracts/{contract_id}` | Renew/extend/amend seats (renewal extends entitlements in place) | `contract.manage` @P | P5 | — | — | If-Match | **Implemented** |
| COM-41 | POST | `/finance/contracts/{contract_id}/terminate` | Early termination (entitlements expire at termination + 7 days) | `contract.terminate` @P | P5 +Dual (finance + super_admin) | **Req** | — | — | **Implemented** |
| COM-42 | POST | `/finance/contracts/{contract_id}/invoices` | Issue B2B invoice against the contract (offline PO order) | `contract.manage` @P | P5 | **Req** | — | — | Planned |
| COM-43 | GET | `/orgs/{org_id}/contract` | Coordinator: contract terms, seats, validity (read-only) | `contract.read` @O | — | — | — | — | **Implemented** |
| COM-44 | GET | `/orgs/{org_id}/invoices` | Coordinator: contract invoices | `invoice.read` @O | — | — | — | — | **Implemented** |
| COM-45 | GET | `/finance/reconciliation` | Payments vs settlement mismatches | `reconciliation.run` @P | — | — | — | — | **Implemented** |
| COM-46 | POST | `/finance/reconciliation/runs` | Run settlement reconciliation for a date range | `reconciliation.run` @P | — | opt | — | 5/day | **Implemented** |
| COM-47 | GET | `/finance/reports/revenue` | Revenue report for `range_from`..`range_to` (default trailing window to now) | `order.read` @P | — | — | — | — | **Implemented (added)** |
| COM-48 | POST | `/finance/approval-requests/{approval_request_id}/approve` | Approve a commerce `approval_requests` row (goodwill/high-value refund, contract changes); approver ≠ requester | `approval.decide` @P | P5 | — | — | — | **Implemented (added)** |
| COM-49 | POST | `/finance/approval-requests/{approval_request_id}/reject` | Reject a commerce approval request (note required) | `approval.decide` @P | P5 | — | — | — | **Implemented (added)** |

### 17.3 Detail entries (commerce)

#### COM-03 · POST `/commerce/checkout/quote`

Request `{"price_id": "0193e001-...", "coupon_code": "NQT25", "billing": {"state_code": "36", "gstin": null}}` → `200`:

```json
{
  "price_id": "0193e001-aaaa-7bbb-8ccc-000000000001",
  "product": {"sku": "PP-TCS-NQT-180", "name": "TCS NQT Placement Package (180 days)", "product_kind": "placement_package"},
  "list_amount_paise": 349900,
  "discount_paise": 87475,
  "taxable_paise": 222394,
  "cgst_paise": 20015,
  "sgst_paise": 20016,
  "igst_paise": 0,
  "total_paise": 262425,
  "coupon": {"code": "NQT25", "status": "applicable", "percent_off": 25},
  "warnings": [{"code": "included_via_college", "message": "Included via Vasavi College of Engineering until 2027-05-31", "ends_at": "2027-05-31T18:29:59.000Z"}],
  "blocking": [],
  "refund_rule": "Full refund within 7 days of purchase if less than 20% of the content is used and no certificate is issued.",
  "access_ends_at": "2027-05-02T10:15:00.000Z"
}
```

`blocking` contains `already_owned` (BR-ENT-05) when an active entitlement already covers the product until at least the new `ends_at`. Coupon problems are reported in `coupon.status` (`invalid`, `expired`, `cap_reached`, `not_applicable`, `min_order_not_met`, `new_users_only`) rather than as errors.

#### COM-04 · POST `/commerce/orders`

Headers: `Idempotency-Key: 9a7e2c10-3b4d-4f5a-8b6c-7d8e9f0a1b2c`.

Request `{"price_id": "0193e001-aaaa-7bbb-8ccc-000000000001", "coupon_code": "NQT25", "billing": {"name": "Ananya Reddy", "state_code": "36", "gstin": null}, "quote_total_paise": 262425}`

Response `201`:

```json
{
  "order_id": "0193e100-1111-7222-8333-444455556666",
  "order_number": "TD-O-2026-00001234",
  "status": "pending_payment",
  "total_paise": 262425,
  "currency": "INR",
  "expires_at": "2026-11-03T10:45:02.000Z",
  "gateway": "razorpay",
  "checkout": {"key_id": "rzp_live_XXXXXXXXXXXX", "gateway_order_id": "order_PJ7x2Yq9ZkL3aB", "amount": 262425, "currency": "INR", "name": "Tech Drona", "prefill": {"email": "ananya.reddy@example.com", "contact": "+919876543221"}, "notes": {"order_number": "TD-O-2026-00001234"}}
}
```

Errors: `idempotency_key_required`, `idempotency_key_reuse`, `already_owned`, `coupon_invalid`/`coupon_expired`/`coupon_cap_reached`/`coupon_not_applicable`, `validation_failed` (`quote_mismatch` when the server total ≠ `quote_total_paise` — the client must re-quote), `contact_not_verified`, `minor_consent_pending`, `consent_required` (`security_monitoring` for adult paid plans), `service_unavailable` (gateway down: order not created).

Server-side: totals recomputed server-side from `prices` (client amounts are never trusted); `orders` + `order_items` + `coupon_redemptions` (`reserved`, `reserved_until = expires_at`) in one transaction; Razorpay order created with `receipt = order_number`; `orders.gateway_order_id` stored; order expires after 30 min (reconciliation job fetches pending orders > 15 min).

#### COM-06 · POST `/commerce/orders/{order_id}/confirm`

Request `{"razorpay_order_id": "order_PJ7x2Yq9ZkL3aB", "razorpay_payment_id": "pay_PJ7y8Ab1Cd2Ef3", "razorpay_signature": "9ef4dffbfd84f1318f6739a3ce19f9d85851857ae648f114332d8401e0949a3d"}`

Response `200`:

```json
{
  "order_id": "0193e100-1111-7222-8333-444455556666",
  "status": "paid",
  "paid_at": "2026-11-03T10:17:40.000Z",
  "entitlements": [{"entitlement_id": "0193e1a0-...", "source_type": "placement_package", "starts_at": "2026-11-03T10:17:40.000Z", "ends_at": "2027-05-02T10:17:40.000Z", "mentor_sessions_remaining": 2, "resume_reviews_remaining": 1}],
  "invoice": {"invoice_number": "TD/2627/000123", "pdf_ready": false}
}
```

If the gateway reports the payment as authorized but not yet captured, `200 {"status": "pending_payment", "message": "Payment received by bank, confirming…"}` and the page polls `COM-05` (up to 15 min, then "We will email you when confirmed"). Errors: `payment_signature_invalid` (HMAC-SHA256(`order_id|payment_id`, key secret) mismatch; recorded as `security_signals` `abuse.checkout_signature_invalid`), `order_expired` (payment captured after expiry is still fulfilled through the webhook path or refunded per finance rule), `not_found`.

Server-side: constant-time HMAC compare; `GET /payments/{id}` from Razorpay to confirm `captured` and the amount/order match; then `fulfil_order` (idempotent: `UPDATE orders SET status='paid' WHERE id=$1 AND status IN ('created','pending_payment')`; entitlements `UNIQUE (order_item_id)`; coupon `reserved → consumed`; invoice number from `invoice_sequences` in the same transaction; outbox `order.paid`, `entitlement.granted`; `ent:{user_id}` version bump). A paid order grants access within 60 s p95.

#### COM-18 · POST `/me/refund-requests`

Request `{"order_id": "0193e100-...", "reason_code": "within_policy_window", "note": "Bought the wrong package."}` → `201 {"refund_id": "...", "status": "requested", "eligibility": {"eligible": true, "days_since_purchase": 2, "consumption_pct": 6.5, "certificate_issued": false}, "decision_due": "2026-11-10"}`. Ineligible requests are still accepted (`eligible: false`, reasons) and routed to finance, who may only approve them as goodwill (Dual). Placement packages: refundable amount = paid − consumed mentor sessions at unit price; mock packs: refundable only if no mock started; subscription renewals are not refundable (cancel instead). Errors: `invalid_state_transition` (order not paid / already refunded), `idempotency_key_required`.

#### COM-31 · POST `/finance/refunds/{refund_id}/decision`

Request `{"decision": "approve", "amount_paise": 262425, "goodwill": false, "note": "Within 7 days; 6.5% consumed."}` → `200 {"status": "processing", "gateway_refund_id": null}` or `202 approval_pending` (goodwill or outside rule: **always**; amount above `commerce.refund.dual_approval_above_paise`, default 2,500,000 paise = ₹25,000: always). The Dual cases create an `approval_requests` row whose id is stored in `refunds.approval_request_id` (`ck_refund_goodwill_dual`: a goodwill refund cannot reach `approved` without it); the approver is a second `finance_admin` (≠ requester) via ADM-14. Approval revokes the linked entitlement immediately (`revoked`, `revoke_reason = refund`; partial bundle refunds revoke only refunded items), creates a credit note, and submits the Razorpay refund; `refund.processed` webhook marks `processed`. Errors: `step_up_required`, `sod_violation` (approver = requester for goodwill; `ck_refund_approver`), `refund_not_eligible` (rule fails and `goodwill: false`), `invalid_state_transition`.

#### COM-12 · POST `/me/subscriptions/{subscription_id}/cancel`

Request `{"reason": "too_expensive", "feedback": null}` → `200 {"status": "active", "cancel_at_period_end": true, "access_until": "2026-12-01T18:29:59.000Z", "confirmation_sent": true}`. One click, no retention dark patterns (no forced survey, no extra screens). Calls Razorpay `cancel(cancel_at_cycle_end=1)`. Allowed from `restricted` and `status_only` sessions (billing view/cancel is `account_status`). Purchased entitlements are unaffected (BR-ENT-07).

---

## 18. Payment and provider webhooks

### 18.1 Catalogue (WH)

| ID | Method | Path | Summary | Auth | Idem | Tag | Status |
|---|---|---|---|---|---|---|---|
| WH-01 | POST | `/webhooks/razorpay` | Razorpay events (payments, orders, refunds, subscriptions, disputes) | HMAC-SHA256 `X-Razorpay-Signature` over raw body | dedupe on `X-Razorpay-Event-Id` | PUB | **Implemented** — Implemented as `POST /webhooks/{provider}` (provider ∈ razorpay, cashfree; others 404) |
| WH-02 | POST | `/webhooks/cashfree` | Cashfree fallback adapter (feature flag `payments.cashfree_enabled`, off by default; P1) | Cashfree signature (`x-webhook-signature` over timestamp + raw body) | dedupe on event id | PUB | **Implemented** — Implemented via the shared `/webhooks/{provider}` route; adapter is a fake until credentials |
| WH-03 | POST | `/webhooks/ses` | Email delivery/bounce/complaint via SNS (notification status, invite `bounced`) | SNS message signature + topic ARN allowlist | dedupe on `MessageId` | PUB | Planned |
| WH-04 | POST | `/webhooks/sms-dlr` | SMS delivery reports from the SMS provider | Provider HMAC/shared secret header + IP allowlist | dedupe on provider message id | PUB | Planned |

Paths are relative to the base path: the canonical webhook path is **`/api/v1/webhooks/{provider}`** (e.g. `https://app.techdrona.in/api/v1/webhooks/razorpay`; resolves I-24). All webhook routes are served by the separate `api-webhooks` ECS service (CloudFront behaviour and ALB rule `/api/v1/webhooks/*`, ordered before the generic `/api/*` → `web` rule), never through the BFF, with no session, no CSRF and a 256 KiB body cap. WAF rate rule: 600/min per source IP.

**Common webhook rules (all providers; TM §2.4, ADR-0006 v0.3):** (1) signature over the raw body (provider HMAC / SNS signature) — failure → `400 webhook_signature_invalid` + `AB-12`; (2) permanent dedupe on the provider event id — duplicates → `2xx` `duplicate`, no effect; (3) every event that can change order, payment, refund, subscription or entitlement state is applied **only from a server-side re-fetch** of the entity from the provider API, never from the payload. **No event is rejected for age.** Razorpay does not sign a timestamp; Cashfree payloads older than `WEBHOOK_TOLERANCE_SECONDS` (`commerce.webhook.tolerance_seconds`, 300) are not trusted, i.e. accepted and applied from the re-fetch like any stale or out-of-order event. In maintenance mode (`platform.maintenance_mode`) webhooks return `503 maintenance` so providers retry.

### 18.2 Razorpay webhook specification (WH-01)

**Request:** `POST /api/v1/webhooks/razorpay`, headers `X-Razorpay-Signature`, `X-Razorpay-Event-Id`, `Content-Type: application/json`; body = Razorpay event JSON (`entity: "event"`, `event`, `payload`, `created_at` epoch seconds, `account_id`).

**Processing steps:**

1. **Read the raw body bytes** before any JSON parsing.
2. **Verify signature:** `expected = hex(HMAC-SHA256(webhook_secret, raw_body))`; constant-time compare with `X-Razorpay-Signature`. Two secrets are accepted during rotation (`current`, `previous`, from Secrets Manager). Failure → `400` problem `webhook_signature_invalid`, metric, `security_signals` (`family = abuse`, `rule_key = AB-12`, `source = system`); the body is **not** stored beyond a hash.
3. **Validate envelope:** `account_id` equals our merchant account; `event` is in the handled list (unknown types are stored with status `ignored` and acknowledged).
4. **Dedupe:** `INSERT INTO payment_webhook_events (gateway, event_id, event_type, signature_valid, payload, payload_sha256, gateway_created_at, …) ON CONFLICT (gateway, event_id) DO NOTHING RETURNING id`. No row returned ⇒ duplicate ⇒ respond `200 {"status": "duplicate"}` and stop. The same event delivered any number of times produces one state change (Phase-8 scenario 14). If `X-Razorpay-Event-Id` is missing, the dedupe key falls back to `sha256(raw_body)`.
5. **Re-fetch, never trust the payload:** Razorpay does not sign a timestamp, so replay protection is the permanent dedupe in step 4 plus the re-fetch rule. For **every** event that can change order, payment, refund, subscription or entitlement state, the worker re-fetches the entity (`payment`, `order`, `refund`, `subscription`) from the provider API and applies the fetched state (never the payload state). Events older than `commerce.webhook.tolerance_seconds` (default **300 s**) are flagged `is_stale = true` for monitoring only. **No event is rejected for age.** Legitimate late retries are therefore processed correctly; a replayed old payload cannot push a stale state.
6. **Respond `200 {"status": "accepted"}` immediately** (target p99 < 300 ms), then enqueue `commerce.process_webhook_event(event_row_id)` on the `critical` queue. If the database is unavailable the handler returns `503` so that Razorpay retries.
7. **Worker:** `SELECT … FOR UPDATE` on the event row (skip if `processed`); re-fetch the entity (step 5; `refetched_at`, `refetch_status = ok`, or `not_required` for events that change no state). If the re-fetch fails (provider API down), retry with backoff **without any state change** (`refetch_status = failed`). Lock the order/subscription row; apply the state machine below to the fetched state, ignoring transitions that would move backwards (e.g. `payment.failed` after `captured`); upsert `payments` by `(gateway, gateway_payment_id)`; call `fulfil_order` / entitlement handlers; mark the event `processed` (or `ignored` with reason). Errors retry with exponential backoff (max 8), then `failed` + alert; finance sees failed events in `COM-29`.
8. **Audit:** state changes write `audit_outbox` (`actor_type = gateway`) and outbox domain events (`order.paid`, `payment.failed`, `refund.processed`, `entitlement.granted|extended|entered_grace|suspended|restored|revoked`).

**Responses:** `200` (accepted — at any age —, duplicate, ignored), `400` (signature invalid or malformed JSON), `413` (body too large), `503` (temporarily unable to persist). Webhooks are exempt from the maintenance gate (§2.1). There is no age-based `4xx`. Webhook responses never include internal ids.

### 18.3 Event → state transitions (Razorpay)

| Razorpay event | Preconditions / lookup | `orders` | `payments` | `subscriptions` | Entitlements (`entitlement_events`) | Other effects |
|---|---|---|---|---|---|---|
| `payment.authorized` | payment by `gateway_payment_id`; order by `gateway_order_id` | `created` → `pending_payment` | upsert `authorized` | — | — | Capture is automatic (auto-capture enabled); if not captured within 5 days the gateway refunds |
| `payment.captured` | amount = order total; currency INR | `pending_payment`/`created` → `paid` (`paid_at`) via `fulfil_order` | `captured` | — | `granted` per order item (`starts_at = now`, `ends_at = now + access_duration_days`; quotas from `product_items.quantity`) | Coupon `reserved → consumed`; invoice `TD/yyyy/nnnnnn`; notification "order paid"; if the order had expired: still fulfilled (money was taken) and flagged for review |
| `order.paid` | same order | as `payment.captured` (idempotent; whichever arrives first fulfils) | upsert from payload | — | as above (no duplicate: `UNIQUE (order_item_id)`) | — |
| `payment.failed` | — | unchanged (`pending_payment`; the user may retry until `expires_at`) | `failed` (`error_code`, `error_description`) unless already `captured` (then ignored) | if linked to a subscription charge: see `subscription.pending` | — | Notification "payment failed — retry" |
| `refund.created` | refund by `gateway_refund_id` or our `refunds.id` in notes | — | — | — | — | `refunds.status` → `processing` |
| `refund.processed` | — | full: `refunded`; partial: `partially_refunded` | `refunded` / `partially_refunded` | — | Full: `revoked` (`refund`) if not already revoked at approval; partial: refunded items only | Credit note issued (if not yet); notification "refund processed" |
| `refund.failed` | — | unchanged | unchanged | — | Entitlement was revoked at approval: stays revoked; finance alerted | `refunds.status = failed`; finance task |
| `subscription.authenticated` | subscription by `gateway_subscription_id` | — | — | `created` → `authenticated` | — | Mandate registered |
| `subscription.activated` | — | — | — | → `active`; `current_period_start/end`, `next_charge_at` | `granted` (one rolling entitlement per subscription, `ux_ent_sub`), `ends_at = current_period_end` | — |
| `subscription.charged` | payment in payload | — | upsert `captured` (`subscription_id`) | `active`; period advanced; `paid_count + 1` | `extended` (`ends_at = new current_period_end`); if in `grace` → `restored` (original period boundary kept) | Invoice for the charge; pre-debit notification for the next cycle is scheduled ≥ 24 h before `next_charge_at` |
| `subscription.pending` | debit failed; gateway retrying | — | — | → `pending` | `entered_grace`: `status = grace`, `grace_ends_at = current_period_end + commerce.subscription_grace_days` (default **5 days**, BR-ENT-09) | Notification "update payment method" |
| `subscription.halted` | retries exhausted | — | — | → `halted` | stays `grace` until `grace_ends_at`, then `expired` (nightly job) | Notification |
| `subscription.paused` / `subscription.resumed` | — | — | — | → `paused` / `active` | paused: no extension (access until `ends_at`); resumed: no change until next charge | — |
| `subscription.cancelled` | — | — | — | → `cancelled` (`cancelled_at`) | no extension; access until `ends_at`; then `expired` | — |
| `subscription.completed` | all cycles paid | — | — | → `completed` | no extension; `expired` after `ends_at` | — |
| `payment.dispute.created` | payment → order | unchanged | unchanged | — | `suspended` (`SUSPENDED_PAYMENT`, BR-ENT-11) | Finance task; audited |
| `payment.dispute.won` | — | unchanged | unchanged | — | `restored` → `active` (dates unchanged) | — |
| `payment.dispute.lost` | — | `refunded` (chargeback) | `refunded` | — | `revoked` (`chargeback`) | Credit note; certificates under that entitlement revoked per BR-ENT-10 |
| `payment.dispute.closed` | — | — | — | — | none beyond won/lost | — |
| any other | — | — | — | — | — | Stored as `ignored` |

Ordering: the worker always compares against the current row state; e.g. `subscription.charged` for an older period than `current_period_end` is ignored, `payment.failed` after `captured` is ignored, `refund.processed` before `refund.created` is applied (creating the missing intermediate state).

---

## 19. Entitlements (`entitlements`)

### 19.1 Access-check contract

Single access check `can_access(user, resource, action, at=now)` owned by `entitlements` and used by the API, the BFF route guards and media token issuance (FR-ENT-001). Evaluation order:

1. `require_active_principal` already applied (scope gate).
2. Restriction ≥ L3 (or feature lock) → `allowed=false, reason_code=ACCOUNT_RESTRICTED` for every resource class except `account_status` (entitlements are gated, never revoked).
3. Minor without verified guardian consent → `MINOR_CONSENT_PENDING` (paid D2C content); unverified contacts for purchase/timed tests → `NOT_VERIFIED`.
4. Free/preview (`public`, `signed_in`, `free_enrolment`) → `ENTITLED` (free courses create a `free_enrolment` entitlement on first enrolment).
5. Staff preview at the resource's scope (`course.preview`, `test.edit`, …) → `ENTITLED` with `via: staff_preview`.
6. Products covering the resource (`product_items`) ∩ user entitlements in status `active` or `grace` with `starts_at ≤ at < ends_at` (or open-ended) → union (BR-ENT-01); contract entitlements require active org membership. Winner chosen by BR-ENT-02 precedence (contract > placement package > subscription > purchase/coupon > admin/trial > free; ties: latest end).
7. Assigned tests: active `test_assignments` for the user's batch → `ENTITLED` with `via: assignment`.
8. Otherwise `NO_ENTITLEMENT`, `EXPIRED`, `SUSPENDED_PAYMENT` (chargeback) with an upsell hint.

`IN_GRACE` is returned with `allowed=true`. Decisions are cached per `(user, resource)` for 60 s keyed by the entitlement-set version (`ent:{user_id}:v{n}`), invalidated on every `entitlement.*` event; p95 ≤ 20 ms.

### 19.2 Catalogue (ENT)

| ID | Method | Path | Summary | Permission @ scope | Step-up | Idem | Tag | Rate limit | Status |
|---|---|---|---|---|---|---|---|---|---|
| ENT-01 | POST | `/entitlements/check` | Check one resource for the current user | S | — | — | — | 300/min | **Implemented** |
| ENT-02 | POST | `/entitlements/check-batch` | Check ≤ 50 resources (catalog pages, BFF route guards) | S | — | — | — | 60/min | **Implemented** |
| ENT-03 | GET | `/me/entitlements` | "What I have access to": source, dates, grace, quotas, renewal status | `entitlement.read` S | — | — | AS | — | **Implemented** |
| ENT-04 | GET | `/users/{user_id}/entitlements` | Entitlements of a user in scope (coordinator: contract entitlements only) | `entitlement.read` @P/@O | — | — | — | audited | **Implemented** |
| ENT-05 | GET | `/entitlements/{entitlement_id}/events` | Append-only history (grant, extend, grace, suspend, restore, revoke, quota use/credit, FP extension) | `entitlement.read` S \| @P | — | — | AS | — | **Implemented** |
| ENT-06 | POST | `/entitlements/grants` | Manual/comp grant (`admin_grant` or `trial`) to ≤ 500 users, ≤ 365 days, reason required | `entitlement.grant_manual` @P | **P5** (+Dual if > 90 days or > 50 users) | **Req** | — | 20/day | **Implemented** |
| ENT-07 | POST | `/entitlements/{entitlement_id}/revoke` | Revoke outside refund/contract flows (`admin`, `fraud`) | `entitlement.revoke` @P | **P5** | **Req** | — | — | **Implemented** |
| ENT-08 | GET | `/orgs/{org_id}/seats` | Seat pool: used/free/waitlisted, reassignments used/allowance | `seat.assign` @O / `contract.read` @O | — | — | — | — | **Implemented** |
| ENT-09 | POST | `/orgs/{org_id}/seats/assignments` | Assign seats to members (creates `institution_contract` entitlements under a contract row lock) | `seat.assign` @O | — | **Req** | — | — | **Implemented** |
| ENT-10 | POST | `/orgs/{org_id}/seats/revocations` | Revoke seats (free return vs used-seat reassignment allowance, BR-ENT-16) | `seat.revoke` @O | S10 | **Req** | — | — | **Implemented** |

### 19.3 Detail entries (entitlements)

#### ENT-01 · POST `/entitlements/check`

Request `{"resource": {"kind": "lesson", "id": "0193b0aa-..."}, "action": "view"}` (kinds: `course`, `lesson`, `lesson_asset`, `resource`, `test`, `practice_topic`, `company_path`, `coding_problem`, `mentor_session`, `feature`).

Allowed:

```json
{"allowed": true, "reason_code": "ENTITLED", "via": "entitlement", "entitlement_id": "0193e1a0-...", "source_type": "institution_contract", "status": "active", "ends_at": "2027-05-31T18:29:59.000Z", "cache_ttl_seconds": 60}
```

Denied (the HTTP status is still `200`; content routes translate a denial to `403 entitlement_required` or `403 account_restricted`):

```json
{"allowed": false, "reason_code": "NO_ENTITLEMENT", "upsell": {"purchase_options": [{"sku": "PP-TCS-NQT-180", "price_id": "0193e001-...", "total_paise": 349900}], "included_in_plans": ["ALL-ACCESS-Y"]}}
```

`reason_code` ∈ `ENTITLED`, `NO_ENTITLEMENT`, `EXPIRED`, `IN_GRACE`, `SUSPENDED_PAYMENT`, `ACCOUNT_RESTRICTED`, `MINOR_CONSENT_PENDING`, `NOT_VERIFIED`. For `ACCOUNT_RESTRICTED` the body adds `case_ref` and `status_url` and never an upsell.

#### ENT-03 · GET `/me/entitlements`

```json
{
  "data": [
    {"entitlement_id": "0193e1a0-...", "title": "TCS NQT Placement Package", "source_type": "placement_package", "source_ref": "TD-O-2026-00001234", "status": "active", "starts_at": "2026-11-03T10:17:40.000Z", "ends_at": "2027-05-02T10:17:40.000Z", "grace_ends_at": null, "quotas": {"mentor_sessions_remaining": 2, "mocks_remaining": null, "resume_reviews_remaining": 1}, "renewal": null},
    {"entitlement_id": "0193d9f0-...", "title": "All-access (college seat)", "source_type": "institution_contract", "organization_name": "Vasavi College of Engineering", "status": "active", "ends_at": "2027-05-31T18:29:59.000Z", "renewal": {"type": "contract", "grace_days": 7}},
    {"entitlement_id": "0193c0b1-...", "title": "All-access monthly", "source_type": "subscription", "status": "grace", "ends_at": "2026-11-01T18:29:59.000Z", "grace_ends_at": "2026-11-06T18:29:59.000Z", "renewal": {"type": "subscription", "next_charge_at": null, "action": "update_payment_method"}}
  ],
  "restriction_gate": {"active": false},
  "page": {"next_cursor": null, "has_more": false, "limit": 25}
}
```

When an L3/L4 restriction is active, `restriction_gate` is `{"active": true, "case_ref": "SEC-2611-7KQ4MZ"}` and entitlement dates are unchanged (BR-ENT-04).

#### ENT-06 · POST `/entitlements/grants`

Request:

```json
{"user_ids": ["0193a0f1-2b3c-7d4e-8f50-61a2b3c4d5e6"], "target": {"product_id": "0193e000-..."}, "source_type": "admin_grant", "starts_at": "2026-11-03T00:00:00.000Z", "ends_at": "2026-12-03T00:00:00.000Z", "reason": "Compensation for judge outage on 2026-10-30 (INC-2610-4F2K9P)"}
```

Response `201 {"granted": 1, "entitlement_ids": ["0193f..."]}` or `202 approval_pending` (> 90 days or > 50 users; approver `super_admin`). Errors: `validation_failed` (> 365 days; missing reason), `sod_violation` (`security_reviewer` may not grant entitlements, SoD-01; the automatic false-positive extension is a system action), `step_up_required`. Every grant writes `audit_log` and `entitlement_events.granted` and appears in finance reports.

#### ENT-09 · POST `/orgs/{org_id}/seats/assignments`

Request `{"contract_id": "0193d900-...", "user_ids": ["0193...", "0193..."], "waitlist_when_full": true}` → `200 {"assigned": 1, "waitlisted": 1, "pool": {"total": 1200, "used": 1200, "free": 0}}`. Seat count enforced with `SELECT … FOR UPDATE` on the contract row; `UNIQUE (institution_contract_id, user_id)` for live seats. Errors: `seat_pool_exhausted` (when `waitlist_when_full` is false), `not_found` (user not an active member of this org — no cross-tenant disclosure).

---

## 20. Analytics ingest, reports and exports (`analytics`)

### 20.1 Catalogue (ANL)

| ID | Method | Path | Summary | Permission @ scope | Step-up | Idem | Tag | Rate limit | Status |
|---|---|---|---|---|---|---|---|---|---|
| ANL-01 | POST | `/analytics/events` | Batch ingest (primary; `fetch` with `keepalive`); max 100 events per request | S (self only; identity from session)¹ | — | **exempt** (per `event_id`) | — | per `analytics-event-schema.md` §5.2 (informative: 30/min per session, burst 10; 60/min per user; 600/min per IP) | **Implemented** |
| ANL-02 | POST | `/analytics/events/beacon` | `sendBeacon` fallback; CSRF token in body + `Sec-Fetch-Site: same-origin` | S | — | **exempt** | — | as ANL-01 | **Implemented** |
| ANL-03 | GET | `/analytics/config` | Active `tm-*` parameters, permitted purposes for this user (consent + tier), sampling flags | S | — | — | — | 10/min | **Implemented** |
| ANL-04 | GET | `/me/analytics/summary` | Student self analytics (learning time M5 today/week, streak, accuracy and median time by topic, mastery, tests, coding) with "How we measure" (`tm-1.0`) | `analytics.read` S | — | — | L3R | — | **Implemented** |
| ANL-05 | GET | `/me/analytics/learning-time` | Daily/weekly learning time series (`?from=&to=&grain=day|week`) | `analytics.read` S | — | — | L3R | — | **Implemented** |
| ANL-06 | GET | `/analytics/reports/batches/{batch_id}` | Trainer/coordinator batch report (progress distribution, lesson funnel, item analysis, learners needing attention, weekly learning time) | `analytics.read` @B/@O | — | — | — | — | **Implemented** |
| ANL-07 | GET | `/analytics/reports/orgs/{org_id}` | Coordinator dashboard (seat utilisation, weekly active learners, completion, readiness by category, test participation) | `analytics.read` @O | — | — | — | — | **Implemented** |
| ANL-08 | GET | `/analytics/reports/orgs/{org_id}/students/{user_id}` | Per-student drill-down in scope (BR-ENT-14, DPA-governed) | `analytics.read` @O/@B | — | — | — | audited | **Implemented** |
| ANL-09 | GET | `/analytics/reports/courses/{course_id}` | Content usage (completion, median M5, drop-off curve k ≥ 10) | `analytics.read` @C | — | — | — | — | **Implemented** |
| ANL-10 | GET | `/analytics/reports/platform` | DAU/WAU/MAU, learning time totals, content performance, cohort benchmarks | `analytics.read.platform` @P | — | — | — | — | **Implemented** |
| ANL-11 | GET | `/analytics/reports/commerce` | GMV, net revenue, refunds, MRR, failed payments, AR from contracts | `analytics.read` @P (finance) | — | — | — | — | Planned |
| ANL-12 | GET | `/analytics/ingest-health` | Events/s, rejection rate by code, duplicates, late %, skew, `seq_gap` %, builder lag | `analytics.read.platform` @P | — | — | — | — | **Implemented** |
| ANL-13 | POST | `/exports` | Request an export job for a report key and scope (CSV/XLSX) | `report.export.request` @scope (security_reviewer, finance_admin @P; college_coordinator @O; trainer @B). Own-data export is a privacy rights request (PRV), not this endpoint | S10 (PII); P5 (bulk > 10,000 rows or privileged requester) +Dual (bulk PII > 10,000 rows, approved via `report.export.approve` by a `super_admin`; security/monitoring report keys H1–H9, H12 and per-user device/login history by a second `security_reviewer`, §1.7) | opt | — | 10/day per user | Planned |
| ANL-14 | GET | `/exports/{export_job_id}` | Export status (`requested`, `awaiting_approval`, `running`, `ready`, `expired`, `failed`, `rejected`) | requester | — | — | AS | — | Planned |
| ANL-15 | GET | `/exports/{export_job_id}/download` | 302 to a signed URL valid ≤ 24 h, only for the requesting principal's session; audited `export.download` | requester | — | — | AS | 5 per job | Planned |

**ANL-06/ANL-07 report fields (audit fix, webstaff 11 / w2a).** Every cell is a k-floored value (`analytics.k_min.cohort`, default 10; a suppressed cell is the string `"<10"`). **ANL-06** adds `progress_distribution: {enrolments, suppressed, buckets: [{bucket, min_pct, max_pct, enrolments}]}` with buckets `not_started`, `1-25`, `26-50`, `51-75`, `76-99`, `completed`, and `lesson_funnel: [{course_id, course_title, enrolments, suppressed, steps: [{lesson_key, title, is_required, started, completed}]}]` for at most 5 courses (most-enrolled first; lessons of the current version in outline order). **ANL-07** adds `course_completion_rate: {enrolments, completed, rate}` and `test_participation: {period: {from, to}, learners_total, learners_attempted, share_attempted, attempts_finished}` (30-day IST window, attempts under the org), and each `placement_readiness_by_category` entry now has a `name` (root topic name, or `Uncategorised`). Learner activity is attributed to an org server-side (own attempt's org → enrolment org → verified batch membership → single active student org; client `batch_id` never trusted, BE-02).

¹ ANL-01/ANL-02 have **no permission key**: authenticated ownership only (role matrix §2.7 note; there is no `analytics.event.ingest` key). Idle effect `engaged_only` (§1.4).

### 20.2 Detail entries (analytics)

#### ANL-01 · POST `/analytics/events`

Request (wire envelope, analytics doc §1.4; `additionalProperties: false`; the client cannot send `user_id`, `organization_id`, `auth_session_id`, `device_id` or `privacy_tier`):

```json
{
  "sent_at": "2026-11-03T10:15:01.900+05:30",
  "client": {"app_version": "web-2026.11.1", "platform": "web", "tz_offset_min": 330, "measurement_version": "tm-1.0"},
  "events": [
    {
      "event_id": "0193f0a0-1b2c-7d3e-8f4a-5b6c7d8e9f01",
      "event_type": "page.heartbeat",
      "schema_version": 1,
      "occurred_at": "2026-11-03T10:15:00.012+05:30",
      "mono_ms": 812345,
      "tab_id": "6c1e9d3a-2f47-4b8e-9a51-0d2c7e8f4b13",
      "page_instance_id": "f2b8c0de-3a41-4e7b-8c9d-1a2b3c4d5e6f",
      "seq": 57,
      "route": "/app/learn/[courseSlug]/[lessonId]",
      "surface": "lesson_video",
      "entity": {"course_id": "0193b000-...", "lesson_id": "0193b0a0-...", "lesson_asset_id": "0193b0aa-..."},
      "payload": {"visible": true, "focused": true, "input_recent": false, "media_playing": true, "interval_ms": 15000}
    }
  ]
}
```

Response `200` (never fails the whole batch for per-event problems):

```json
{
  "accepted": 41, "duplicate": 2, "rejected": 1,
  "results": [
    {"event_id": "0193f0a0-1b2c-7d3e-8f4a-5b6c7d8e9f01", "status": "accepted"},
    {"event_id": "0193f0a0-1b2c-7d3e-8f4a-5b6c7d8e9f02", "status": "duplicate"},
    {"event_id": "0193f0a0-1b2c-7d3e-8f4a-5b6c7d8e9f03", "status": "rejected", "code": "event_too_old"}
  ],
  "server_time": "2026-11-03T04:45:02.123Z",
  "config_version": "tm-1.0"
}
```

Per-event rejection codes: `unknown_event_type`, `unsupported_schema_version`, `server_only_event` (assessment, coding-submission, practice-answer and completion events are emitted only by the server via the outbox), `purpose_not_permitted` (consent/tier), `event_too_old` (> 72 h late), `event_in_future`, `invalid_payload`, `payload_too_large` (> 4 KiB event; > 24 payload props), `entity_not_entitled`, `rate_capped` (engaged heartbeats closer than 10 s per page instance; still 200), `uuid_time_mismatch` (UUIDv7 time not within ±5 min of `occurred_at`).

Batch-level errors: `413 payload_too_large` (> 64 KiB), `422 validation_failed` (> 100 events per request, schema violation), `429 rate_limited`, `401`/`403` from the principal gate (L3/L4 sessions cannot ingest learning events, `account_restricted`; keepalive-only clients get `403` and stop).

Server-side: identity from the session only; `effective_at = min(occurred_at + skew_ms, received_at)`; `event_ts` derived from the UUIDv7; insert `ON CONFLICT (event_id, event_ts) DO NOTHING`; union per user (≤ 1 active second per wall-clock second); daily plausibility flag; entitlement check on entity refs; after crediting, if the batch is credited > 0 active seconds for the requesting session the handler calls `sessions.touch_engaged(session_id)` — keepalive-only batches never do (`x-td-idle: engaged_only`). Minors: `privacy_tier = minor` snapshot; product (P-purpose) events dropped; no security feed rows.

#### ANL-02 · POST `/analytics/events/beacon`

Same body as ANL-01 plus `"csrf": "<signed token>"`; `Content-Type: text/plain` or `application/json` (sendBeacon); `Sec-Fetch-Site: same-origin` required; response `204` (the beacon cannot read a body). All other rules identical.

#### ANL-13 · POST `/exports`

Request `{"report_key": "coordinator.batch_progress", "scope": {"type": "batch", "id": "0193ab..."}, "filters": {"from": "2026-10-01", "to": "2026-10-31"}, "format": "csv", "contains_pii": true, "reason": "Placement cell monthly review"}` → `202 {"export_job_id": "0193f1...", "status": "running"}` or `{"status": "awaiting_approval", "approval_request_id": "..."}` for bulk PII (> 10,000 rows, approver a `super_admin` holding `report.export.approve`, ≠ requester). Files are watermarked (requester + time), scoped to the requester's session, expire after 24 h; k-floors apply to aggregate exports; pseudonymous exports use `subject_key = HMAC-SHA256(k_analytics_vN, user_id)`. Security per-user exports use `SEC-32`.

---

## 21. Notifications (`notifications`)

### 21.1 Catalogue (NTF)

| ID | Method | Path | Summary | Permission @ scope | Step-up | Idem | Tag | Rate limit | Status |
|---|---|---|---|---|---|---|---|---|---|
| NTF-01 | GET | `/me/notifications` | In-app inbox | S | — | — | AS | — | **Implemented** |
| NTF-02 | POST | `/me/notifications/{notification_id}/read` | Mark read | S | — | — | AS | — | **Implemented** |
| NTF-03 | POST | `/me/notifications/read-all` | Mark all read | S | — | — | AS | — | **Implemented** |
| NTF-04 | GET | `/me/notification-preferences` | Preferences per category (learning reminders, product updates, marketing) | S | — | — | AS | — | Planned |
| NTF-05 | PUT | `/me/notification-preferences` | Update preferences (marketing default off; never for minors; transactional/security always on) | S | — | — | AS | 20/h | Planned |
| NTF-06 | POST | `/batches/{batch_id}/announcements` | Batch announcement (in-app + email; ≤ 3 per batch per day) | `notification.batch_announce` @B/@O | — | opt | — | 3/day per batch | **Implemented** |
| NTF-07 | GET | `/admin/notification-templates` | Templates with versions | `notification.template.manage` @P | — | — | — | — | Planned |
| NTF-08 | POST | `/admin/notification-templates/{template_key}/versions` | Create template version (DLT template id for SMS) | `notification.template.manage` @P | — | opt | — | — | Planned |
| NTF-09 | POST | `/admin/notification-templates/{template_key}/versions/{version}/activate` | Activate version | `notification.template.manage` @P | P5 | opt | — | — | Planned |
| NTF-10 | GET | `/me/events` | Server-Sent Events stream: signed-out notice, playback revoked, attempt rebound, submission judged, order paid, new notification | S | — | — | AS | 2 concurrent streams per session | Planned |

`NTF-10` event example: `event: session.revoked` / `data: {"reason_text": "you signed in on another device", "end_reason": "session_cap_evicted"}`. The stream is closed by the server when the session ends.

---

## 22. Support (`support`)

### 22.1 Catalogue (SUP)

> **Removed 2026-11-14:** corporate enquiries (`POST /public/enquiries`, `GET /support/enquiries`, `GET`/`PATCH /support/enquiries/{id}`; the `corporate_enquiry` category). Enquiries go to the website contact page.

| ID | Method | Path | Summary | Permission @ scope | Step-up | Idem | Tag | Rate limit | Status |
|---|---|---|---|---|---|---|---|---|---|
| SUP-01 | POST | `/support/tickets` | Create ticket (category, subject, body, attachments; context auto-attached and disclosed: browser/OS, route, last `request_id`). Body `{category, subject (3–200), body (10–5000), attachments?, organization_id?, related_order_id?, related_unblock_request_id?, related_attempt_id?, context?}`; unknown fields rejected. **(audit fix)** `attachments`: ≤ 5 `{s3_key, filename, content_type, size_bytes ≤ 10 MB}` uploaded first with MED-02 `support_attachment` (only the requester's own keys). `related_attempt_id`: must be the requester's own `test_attempts` row, else `422` on `related_attempt_id`; stored in the ticket context and returned as `related_attempt_id` by every ticket view (appeal prefill) | `ticket.read` S (own) | — | opt | AS | 10/day | **Implemented** |
| SUP-02 | GET | `/me/support/tickets` | Own tickets | S | — | — | AS | — | **Implemented** |
| SUP-03 | GET | `/support/tickets/{ticket_id}` | Ticket thread (owner: public messages; agents: + internal notes) | S \| `ticket.read` @P/@O | — | — | AS | — | **Implemented** |
| SUP-04 | POST | `/support/tickets/{ticket_id}/messages` | Reply (owner) or respond/internal note (agent). Body `{body, visibility: public\|internal, attachments?}` (≤ 5, as SUP-01). A coordinator (college lane) cannot post internal notes | S \| `ticket.respond` @P/@O | — | opt | AS | 30/h | **Implemented** |
| SUP-04b | GET | `/support/tickets/{ticket_id}/attachments/{ref}/{index}` | **(audit fix, BE-17, added)** Short-lived presigned download URL for an attachment: `ref` = `ticket` (files sent with SUP-01) or a message id (SUP-04); `index` = position in that list. Response `{url, expires_at, filename}`. Same visibility as the thread: the requester and agents who can see the ticket; internal-note files only for platform-lane agents; otherwise `404`. Staff downloads are audited (`support.attachment.downloaded`) | S \| agents who can read the ticket | — | — | AS | — | **Implemented (added)** |
| SUP-05 | POST | `/support/tickets/{ticket_id}/reopen` | Reopen a resolved ticket | S | — | opt | AS | — | **Implemented** |
| SUP-06 | POST | `/support/tickets/{ticket_id}/csat` | CSAT 1–5 + comment (P1) | S | — | opt | AS | 1 per ticket | **Implemented** |
| SUP-07 | GET | `/support/queue` | Agent queue (SLA timers, priority, category; grievance clocks) | `ticket.read` @P (content managers: content tickets; finance: billing; security: security tickets; coordinators: own org's college-access tickets) | — | — | — | — | **Implemented** |
| SUP-08 | PATCH | `/support/tickets/{ticket_id}` | Assign, status, priority | `ticket.assign` @P | — | — | — | — | **Implemented** |
| SUP-09 | POST | `/support/tickets/{ticket_id}/escalate` | Route to finance/security/content (security escalation can open a case via SEC-12) | `ticket.escalate` @P | — | opt | — | — | **Implemented** |
| SUP-10 | POST | `/support/tickets/{ticket_id}/merge` | Merge duplicates | `ticket.assign` @P | — | opt | — | — | **Implemented** |
| SUP-11 | GET | `/support/users/{user_id}` | User lookup (FR-SUP-005): account and verification status, restriction level + student-facing reason, devices with masked IPs, active sessions, entitlements, recent orders (read-only) | `user.read` @P | — | — | — | `reason_code` (ticket) required; audited | **Implemented** |
| SUP-12 | POST | `/support/users/{user_id}/resend-verification` | Resend email/mobile verification | `user.read` @P | — | opt | — | 5/day per user | **Implemented** |
| SUP-13 | POST | `/support/users/{user_id}/password-reset-email` | Trigger password-reset email (never sets a password) | `user.read` @P | S10 | opt | — | 3/day per user | **Implemented** |
| SUP-14 | POST | `/support/users/{user_id}/notes` | Annotate account (internal) | `ticket.respond` @P | — | opt | — | — | **Implemented** |
| SUP-15 | GET | `/support/macros` | Macros | `ticket.respond` @P | — | — | — | — | **Implemented** |
| SUP-16 | POST | `/public/contact` | Unauthenticated help/grievance form (CAPTCHA; grievance acknowledgement ≤ 48 h) | public | — | opt | PUB | 5/h per IP | Planned |
| SUP-17 | POST | `/public/college-enquiries` | College enquiry form (PUB-010) | public | — | opt | PUB | 5/h per IP | Planned |

**Ticket categories (`Category`, audit fix, `support_0002`):** `account_access`, `device_reset`, `billing`, `refund`, `content`, `assessment`, `technical`, `grievance`, `privacy_request`, `certificate`, `college_access`, `appeal`, `other`. **Lanes (BE-16):** a coordinator sees only their own org's `college_access` tickets, never internal notes; everything else is the platform lane. Responses list attachments as `filename`, `content_type` and `size_bytes` only. **Queue (SUP-07, ADM-38):** ordered by `(resolution_due_at, id)` with a keyset cursor. **Priority (BE-32):** an `assessment` ticket from a learner with a running attempt is raised to `high`.

**Status note (2026-11-03):** SUP-01..15 exist in `apps/api/app/modules/support/router.py` and are marked Implemented above; the §25/§28 counts were not recomputed for this change.

Support actions that change security state use the security/session endpoints (`SES-10`, `SES-12`, `SEC-20/21` for L1/L2, `UNB-17/18`); support can never lift L3/L4, see evidence or full IPs (SoD-03).

---

## 23. Privacy and data-principal rights (`admin` privacy sub-package)

### 23.1 Catalogue (PRV)

| ID | Method | Path | Summary | Permission @ scope | Step-up | Idem | Tag | Rate limit | Status |
|---|---|---|---|---|---|---|---|---|---|
| PRV-01 | GET | `/me/privacy-requests` | Own rights requests with DPDP timers | S | — | — | AS | — | **Implemented** |
| PRV-02 | POST | `/me/privacy-requests` | Create request: `access_export`, `correction`, `erasure` (14-day cooling-off), `grievance`, `nomination`, `consent_withdrawal_help` | `privacy.request.process` S (request) | U15 for `erasure` | **Req** | AS | 3/day | **Implemented** |
| PRV-03 | GET | `/me/privacy-requests/{request_id}` | Request status and response | S | — | — | AS | — | **Implemented** |
| PRV-04 | POST | `/me/privacy-requests/{request_id}/withdraw` | Withdraw (e.g. cancel deletion during cooling-off) | S | — | opt | AS | — | **Implemented** |
| PRV-05 | GET | `/me/privacy-requests/{request_id}/export` | Download own data export (JSON + CSV zip, ≤ 72 h after request; link 24 h) | S | — | — | AS | 5 per request | **Implemented** |
| PRV-06 | POST | `/privacy/representative-requests` | Guardian or nominee request without the principal's session (OTP to the representative's contact; manual verification) | public (OTP) | — | Req | PUB | 3/day per contact | Planned |
| PRV-07 | GET | `/admin/privacy-requests` | Rights queue with timers (overdue highlighted) | `privacy.request.process` @P | — | — | — | — | **Implemented** |
| PRV-08 | GET | `/admin/privacy-requests/{request_id}` | Request detail | `privacy.request.process` @P | — | — | — | audited | **Implemented** |
| PRV-09 | POST | `/admin/privacy-requests/{request_id}/verify-identity` | Record identity verification (`session`, `otp`, `guardian_otp`, `manual`) | `privacy.request.process` @P | P5 | opt | — | — | **Implemented** |
| PRV-10 | POST | `/admin/privacy-requests/{request_id}/complete` | Complete (export generated, correction applied, erasure executed → `erasure_ledger`) | `privacy.request.process` @P | P5 | **Req** | — | — | **Implemented** |
| PRV-11 | POST | `/admin/privacy-requests/{request_id}/reject` | Reject with reason (legal retention, unverifiable) | `privacy.request.process` @P | P5 | opt | — | — | **Implemented** |
| PRV-12 | GET | `/orgs/{org_id}/privacy-requests` | Requests routed to the college as data fiduciary | `privacy.request.process` @O | — | — | — | — | **Implemented** |
| PRV-13 | GET | `/admin/retention-policies` | Retention registry | `audit.read` @P | — | — | — | — | **Implemented** |
| PRV-14 | PATCH | `/admin/retention-policies/{policy_id}` | Change a retention rule | `policy.edit` @P | P5 +Dual | Req | — | — | Planned |
| PRV-15 | GET | `/admin/erasure-ledger/status` | Ledger counts and last post-restore re-application check (no subject identifiers) | `audit.read` @P | — | — | — | — | Planned |

`PRV-02` request `{"request_type": "erasure", "details": "Please delete my account.", "confirm": true}` → `201 {"request_ref": "PRV-2611-8M3QZT", "status": "cooling_off", "cooling_off_until": "2026-11-17T10:15:02.000Z", "due_at": "2026-12-03T10:15:02.000Z", "retained_by_law": ["invoices (72 months)", "security logs (≥ 1 year)"]}`. Erasure revokes all sessions at completion (`account_deleted`); legally retained records are kept and listed.

---

## 24. Audit (`audit`), platform administration (`admin`) and system

### 24.1 Catalogue (AUD)

| ID | Method | Path | Summary | Permission @ scope | Step-up | Idem | Tag | Status |
|---|---|---|---|---|---|---|---|---|
| AUD-01 | GET | `/audit/events` | Query the audit log (actor, action, target, subject, org, time range, `reason_code`); results filtered by role (security events for `security_reviewer`, commerce events for `finance_admin`, all for `super_admin`) | `audit.read` @P | — | — | — | **Implemented** |
| AUD-02 | GET | `/audit/events/{seq}` | One entry with before/after diff and hash fields | `audit.read` @P | — | — | — | **Implemented** |
| AUD-03 | GET | `/audit/chain-status` | Hash-chain verification status and last S3 Object Lock anchor | `audit.read` @P | — | — | — | **Implemented** |
| AUD-04 | GET | `/orgs/{org_id}/audit/events` | Own org's admin actions (grants, imports, exports, seat changes) | `audit.read.org` @O | — | — | — | Planned |
| AUD-05 | POST | `/audit/exports` | Export audit range (async → ANL-14/15) | `audit.read` @P + `report.export.request` @P | P5 | opt | — | Planned |

`AUD-01` query: `?action=security.restriction.lift&subject_user_id=0193...&from=2026-10-01T00:00:00Z&to=2026-11-03T00:00:00Z&cursor=`. Row example: `{"seq": 1048577, "occurred_at": "...", "actor_type": "user", "actor_user_id": "0192...", "actor_roles": ["security_reviewer"], "action": "case.decide", "target_type": "security_case", "target_id": "0193a4e5-...", "subject_user_id": "0193a0f1-...", "reason_code": "case_review", "request_id": "01JC9...", "row_hash": "b1946ac9…", "prev_hash": "a3f2…"}`. The audit API itself is audited (`audit.query`). No endpoint can modify or delete audit rows.

### 24.2 Catalogue (ADM)

| ID | Method | Path | Summary | Permission @ scope | Step-up | Idem | Tag | Status |
|---|---|---|---|---|---|---|---|---|
| ADM-01 | GET | `/admin/dashboard` | Platform admin dashboard (ADM-001 widgets, aggregates only) | `analytics.read.platform` @P | — | — | — | Planned |
| ADM-02 | GET | `/admin/users` | User search (no evidence data) | `user.read` @P | — | — | — | Planned |
| ADM-03 | GET | `/admin/users/{user_id}` | User account view (status, tier, grants, restriction level, minor flag) | `user.read` @P | — | — | — | Planned |
| ADM-04 | POST | `/admin/users/{user_id}/deactivate` | Deactivate account (revokes all sessions) | `user.deactivate` @P | P5 | Req | — | Planned |
| ADM-05 | POST | `/admin/users/{user_id}/mfa-reset` | Remove MFA factors after identity verification | `user.mfa.reset` @P | P5 +Dual (security_reviewer approves support requests) | Req | — | Planned |
| ADM-06 | POST | `/admin/users/{user_id}/legal-name` | Change locked legal name after document check | `user.legal_name.change` @P | S10 | opt | — | Planned |
| ADM-07 | GET | `/admin/policy-settings` | All keys: effective platform values, bounds, flags (`org_overridable`, `plan_overridable`, `locked`), pending changes | `policy.edit` @P or `policy.propose` @P (read also `security.rule.read` @P) | — | — | — | **Implemented** |
| ADM-08 | GET | `/admin/policy-settings/{setting_key}` | One key across scopes (platform/plan/org/user exceptions) with version history | `policy.edit` @P or `policy.propose` @P (own namespaces) | — | — | — | **Implemented** |
| ADM-09 | POST | `/admin/policy-settings/{setting_key}/changes` | Propose a change at a scope (bounds-checked; applies to new events only; effective within 60 s after execution) | `policy.propose` @P, namespace-limited: security_reviewer for `risk.*`, `sessions.*`, `devices.*`, `playback.*`, `login.*`, `otp.*`, `unblock.*`, `assessment.*`; finance_admin for `commerce.*`; super_admin any. Execution needs approval by a different `super_admin` with `policy.edit` | P5 +Dual | Req | — | **Implemented** |
| ADM-10 | GET | `/admin/feature-flags` | Feature flags | `feature_flag.manage` @P | — | — | — | **Implemented** |
| ADM-11 | PATCH | `/admin/feature-flags/{flag_key}` | Toggle / rollout % / allowlists | `feature_flag.manage` @P | P5 | — | — | **Implemented** |
| ADM-12 | GET | `/admin/approvals` | Dual-control queue (requester, payload diff, expiry) filtered to action types the caller may approve | approval permission per action type (§1.7): `report.export.approve` (exports), `policy.edit` (policy changes), `approval.decide` (others) @P | — | — | — | **Implemented** |
| ADM-13 | GET | `/admin/approvals/{approval_id}` | Approval detail with payload and hash | as ADM-12 for that action type (or requester) | — | — | — | **Implemented** |
| ADM-14 | POST | `/admin/approvals/{approval_id}/approve` | Approve and execute the stored payload. Not used for `security.case.decision` (SEC-10) | as ADM-12 for that action type @P (never own request) | P5 | Req | — | **Implemented** |
| ADM-15 | POST | `/admin/approvals/{approval_id}/reject` | Reject with note. Not used for `security.case.decision` (SEC-11) | as ADM-12 for that action type @P | P5 | opt | — | **Implemented** |
| ADM-16 | POST | `/admin/approvals/{approval_id}/cancel` | Requester cancels a pending request | requester | — | opt | — | **Implemented** |
| ADM-17 | POST | `/admin/break-glass` | Activate time-boxed elevation (≤ 2 h) with reason; alerts all super admins and security reviewers | `breakglass.activate` @P | P5 (passkey only) | Req | — | Planned |
| ADM-18 | POST | `/admin/break-glass/{session_id}/end` | End break-glass early | `breakglass.activate` @P | — | opt | — | Planned |
| ADM-19 | GET | `/admin/break-glass` | Break-glass history and post-hoc review status (review within 2 business days by another super admin) | `breakglass.activate` @P | — | — | — | Planned |

#### ADM-09 · POST `/admin/policy-settings/{setting_key}/changes`

Request:

```json
{"scope_type": "organization", "scope_id": "0192f7aa-5b6c-7d8e-9f01-a2b3c4d5e6f7", "value": 1, "effective_from": "2026-11-10T00:00:00.000Z", "change_reason": "College requests single concurrent session during placement season"}
```

Response `202 approval_pending` (`action_type = policy.change`, approver a different `super_admin` holding `policy.edit`). A proposal outside the proposer's namespaces → `403 permission_denied` (`permission: policy.propose`). `risk.owner_verified_overlap_multiplier` is retired (RE §3.2); new security namespaces include `risk.hc.*`, `risk.separation.*`, `risk.owner_verification.*`, `security.keys.*`, `assessment.idle_hold_extra_minutes`. Moving `risk.mode` toward enforcement or turning HC rules on always goes through this Dual path; the reverse emergency direction is SEC-42. Errors: `validation_failed` (`out_of_bounds` with `min_value`/`max_value`; `not_overridable_at_scope`; `locked_key` for 🔒 keys below platform; `org_override_may_only_tighten` for `sessions.student.idle_minutes` and similar), `step_up_required`. User-scope rows (security exceptions) are created only by case decisions (`SEC-09` `conditions.user_exception`), never through this endpoint (`422 validation_failed`, `user_scope_requires_case_decision`).

### 24.3 Catalogue (SYS)

| ID | Method | Path | Summary | Permission @ scope | Tag | Status |
|---|---|---|---|---|---|---|
| SYS-01 | GET | `/health/live` | Liveness (internal ALB only) | public (internal) | PUB | **Implemented** |
| SYS-02 | GET | `/health/ready` | Readiness: DB, Redis cache/queue, migrations head (internal only) | public (internal) | PUB | **Implemented** |
| SYS-03 | GET | `/public/status` | Service status (judge, video, payments): operational / degraded / outage | public | PUB | Planned |
| SYS-04 | GET | `/public/legal/{document_key}` | Published policies (terms, privacy, refund, device policy) with version and effective date | public | PUB | Planned |
| SYS-05 | GET | `/public/policy-numbers` | Published platform limits (devices, sessions, streams, replacements, refund window) for marketing and legal pages | public | PUB | Planned |
| SYS-06 | GET | `/healthz` (root, **outside** `/api/v1`; not in OpenAPI) | Liveness alias for docker/ECS/ALB health checks | public (internal) | PUB | **Implemented (added)** |

---

## 25. Endpoint counts

| Module | Prefix | Endpoints | Implemented | Added (v0.3) | Planned |
|---|---|---|---|---|---|
| Identity: authentication | AUTH | 28 | 22 | 0 | 6 |
| Identity: self-service profile, consent, MFA | ME | 13 | 9 | 0 | 4 |
| Sessions and devices | SES | 16 | 12 | 0 | 4 |
| Security administration | SEC | 48 (SEC-01..47 + SEC-11a) | 47 | 1 | 0 |
| Unblock requests | UNB | 20 | 18 | 2 | 0 |
| Organizations, batches, invitations, imports | ORG | 30 | 28 | 0 | 2 |
| RBAC | RBAC | 8 | 6 | 2 | 0 |
| Catalog and authoring | CAT | 22 | 19 | 0 | 3 |
| Media and playback | MED | 7 | 7 | 0 | 0 |
| Learning, progress, assignments, certificates | LRN | 27 | 24 | 0 | 3 |
| Placement | PLC | 52 | 24 | 0 | 28 |
| Assessments (tests, assignments, overrides, results) | ASM | 23 | 17 | 0 | 6 |
| Assessment attempts | ATT | 13 | 13 | 0 | 0 |
| Coding | COD | 23 | 12 | 1 | 10 |
| Commerce | COM | 49 | 41 | 3 | 5 |
| Webhooks | WH | 4 | 2 | 0 | 2 |
| Entitlements | ENT | 10 | 10 | 0 | 0 |
| Analytics and exports | ANL | 15 | 11 | 0 | 4 |
| Notifications | NTF | 10 | 4 | 0 | 6 |
| Support | SUP | 17 | 0 | 0 | 17 |
| Privacy | PRV | 15 | 12 | 0 | 3 |
| Audit | AUD | 5 | 3 | 0 | 2 |
| Platform administration | ADM | 19 | 10 | 0 | 9 |
| System | SYS | 6 | 2 | 1 | 3 |
| **Total** | | **480** | **353** | **10** | **117** |

The BFF-only `POST /api/v1/_errors` tunnel (§1.1) is not a FastAPI route and is not counted.

---

## 26. Endpoint → FR → screen mapping (best effort)

| Endpoints | FR IDs | Screens |
|---|---|---|
| AUTH-01, AUTH-02..05 | FR-IDN-001, -002, -003, -004; FR-PRV-001 | PUB-011, PUB-014 |
| AUTH-06..10 | FR-IDN-005, -009; FR-SES-001 | PUB-012 |
| AUTH-11, ME-07..13 | FR-IDN-006 | PUB-012, STU-021 |
| AUTH-12, AUTH-13 | FR-SES-002, -003, -004, -005 | PUB-012, STU-022 |
| AUTH-14 | FR-SES-006 | PUB-012 |
| AUTH-15 | FR-SES-001, -009 | all portals |
| AUTH-16, AUTH-17, AUTH-18 | FR-IDN-007, FR-SES-009 | PUB-013, STU-021 |
| AUTH-19, AUTH-20 | FR-IDN-008, FR-RBAC-003 (step-up), FR-ADM-005 | all staff consoles (step-up modal) |
| AUTH-21, AUTH-22 | FR-SEC-004, FR-SEC-008 | STU-026, PUB-021 |
| AUTH-23, AUTH-24 | FR-IDN-011 | PUB-012 |
| AUTH-25..27 | FR-IDN-002, FR-PRV-003 | PUB-015 |
| AUTH-28 | FR-SES-010 (remember-device re-issue) | — (BFF, no screen) |
| ME-01, ME-02 | FR-IDN-010, FR-IDN-013 | STU-001, STU-020 |
| ME-03, ME-04 | FR-IDN-008 | STU-020, STU-021 |
| ME-05, ME-06 | FR-PRV-001 | STU-023 |
| SES-01..08 | FR-SES-004, -005, -008, -010; FR-SEC-009 | STU-022 |
| SES-09..12 | FR-SUP-005, -006, -007; FR-SES-009 | SUP-003, SUP-004 |
| SES-13..16 | FR-SES-004 (lab exclusion); security §5.5 | COL-001 (settings), COL-012 |
| SEC-01, SEC-02 | FR-SEC-002a (L1–L2, P0), FR-SEC-002b (L3–L4, P1), FR-SEC-003, -009 | STU-026, STU-001 (banner), PUB-021 |
| SEC-03..12 (incl. SEC-11a) | FR-SEC-001, FR-SEC-002b, FR-SEC-005, -006 | SEC-002, SEC-003 |
| SEC-13..18 | FR-SEC-001, FR-SEC-003 | SEC-003, SEC-007 |
| SEC-19..21 | FR-SEC-002a (L1–L2), FR-SEC-002b (L3–L4), FR-SEC-006, -007 | SEC-005, SUP-003 |
| SEC-22..29 | FR-SEC-001 | SEC-006, ADM-010 |
| SEC-30..32, SEC-40 | Section H (source); FR-ANL-004 | SEC-001 |
| SEC-33..36 | security §5.5 | SEC-001, COL-001 |
| SEC-37..39 | FR-ADM-001 (incident register; privacy doc) | SEC-001 |
| SEC-41 | FR-SEC-007 (coordinator status only) | COL-001, COL-009 |
| SEC-42, SEC-43 | FR-SEC-010 (HC rules, kill switch); RE §5.7 | SEC-001, SEC-006 |
| SEC-44, SEC-45 | FR-SEC-002b, FR-SEC-008; RE §5.8 | SEC-005 |
| SEC-46 | FR-SEC-009; UNB §1.6a | STU-022 (security notice) |
| UNB-01..09 | FR-SEC-004, -008; FR-SUP-001 (appeal route) | STU-026, PUB-021 |
| UNB-10..16 | FR-SEC-004, -005 | SEC-004, SEC-003 |
| UNB-17, UNB-18 | FR-SEC-006 | SUP-005 |
| ORG-01..06 | FR-ORG-001, -002; BR-ENT-19 | ADM-002, ADM-003 |
| ORG-07..09 | FR-ORG-004, -018 | COL-002, COL-009 |
| ORG-10..17 | FR-ORG-010, -011 | COL-003, COL-002 |
| ORG-18, ORG-19 | FR-ORG-012, FR-IDN-012, FR-ORG-013 | PUB-016 |
| ORG-20..27 | FR-ORG-003, -004 | COL-004, COL-005, TRN-002 |
| ORG-28, ORG-29 | BR-ENT-14, FR-ORG-018 | STU-027, STU-023 |
| ORG-30 | FR-ORG-016 | COL-010 |
| RBAC-01..06 | FR-RBAC-001..004, FR-ORG-017 | ADM-005, COL-012, portal switcher |
| CAT-01..07 | FR-CAT-003, -005, -008; FR-PLC-007 | PUB-001..009 |
| CAT-08..22 | FR-CAT-001, -002, -004, -006, -009 | CMS-002, CMS-003, TRN-003, TRN-004, PLY-004 |
| MED-01..03 | FR-CAT-007 | CMS-012, TRN-004 |
| MED-04..06 | FR-SES-007, FR-MED-001, -002 | PLY-001, PLY-005 |
| MED-07 | FR-CAT-006 | PLY-002, PUB-009 |
| LRN-01..07 | FR-LRN-001, -002, -003; FR-CAT-002 | STU-001, STU-004, STU-005, PLY-001..003 |
| LRN-08..10, LRN-14..19 | FR-LRN-004, -005 | STU-007, STU-008, TRN-008, TRN-009, TRN-012 |
| LRN-11..13, LRN-20, LRN-21 | FR-LRN-006, -007, -008 | STU-012, PUB-017 |
| LRN-22..24 | FR-LRN-001, -003; BR-ENT-14 | COL-005, TRN-002 |
| LRN-25..27 | FR-LRN-009 | STU-028 |
| PLC-01..18 | FR-PLC-001..004, -007, -018 | CMS-004..009, CMS-013, PUB-004, PUB-005 |
| PLC-19..24 | FR-PLC-005, -008, -009 | PRC-001..004, STU-015 |
| PLC-25..32 | FR-PLC-006, -011, -012, -014, -016, -013 | STU-002, STU-006, STU-011, PRC-005 |
| PLC-33..35 | FR-PLC-017 | PRC-003, CMS-013 |
| PLC-36..46 | FR-PLC-010 | STU-013, MEN-001..004 |
| PLC-47..52 | FR-PLC-015 | STU-014, MEN-005 |
| ASM-01, ASM-02 | FR-ASM-002, -003 | STU-009, TST-001, STU-003 |
| ASM-03..09 | FR-ASM-001, -002, -003, -008, -010 | TRN-005, TRN-006, CMS-011 |
| ASM-10..14 | FR-ORG-014, FR-ASM-007, -013 | COL-007, TRN-007 |
| ASM-15..22 | FR-ASM-009, -010, -011, -012; FR-COD-008 | TRN-010, TRN-011, COL-007 |
| ASM-23 | FR-ASM-015 | STU-010 |
| ATT-01 | FR-ASM-003, -004; FR-SES-011 | TST-001, TST-002 |
| ATT-02..05 | FR-ASM-006; FR-SES-011 | TST-002, TST-004 |
| ATT-06..09 | FR-ASM-004, -005, -014 | TST-002, TST-003 |
| ATT-10 | FR-ASM-004 | TST-003, TST-005 |
| ATT-11..13 | FR-ASM-008, -009 | STU-010, TST-005 |
| COD-01..12 | FR-COD-001..007, -010 | COD-001..004 |
| COD-13..19 | FR-COD-001, -002 | CMS-010 |
| COD-20..22 | FR-COD-006, -008 | TRN-010 |
| COM-01..08 | FR-COM-001..004, -011, -014; BR-ENT-05, -06 | PUB-003, PUB-008, STU-016, STU-017 |
| COM-09..14 | FR-COM-005, -006 | STU-016, STU-018 |
| COM-15..19 | FR-COM-008, -009 | STU-018 |
| COM-20..27 | FR-COM-001, -002, -005, -007 | FIN-002, FIN-003 |
| COM-28..37 | FR-COM-008, -009, -012 | FIN-004..007 |
| COM-38..44 | FR-COM-010; BR-ENT-15..18 | FIN-008, COL-011 |
| COM-45, COM-46 | FR-COM-013 | FIN-009 |
| WH-01, WH-02 | FR-COM-003, -004, -005, -012; BR-ENT-09, -10, -11 | STU-017 (indirect) |
| WH-03, WH-04 | FR-NTF-005, FR-ORG-011 | COL-003 (invite status) |
| ENT-01..05 | FR-ENT-001..004; BR-ENT-01..04, -08 | STU-019, all content screens (state R) |
| ENT-06, ENT-07 | FR-ENT-005; BR-ENT-12 | FIN-004 (grants), ADM-010 |
| ENT-08..10 | FR-ORG-013; BR-ENT-15, -16 | COL-006 |
| ANL-01..03 | FR-ANL-001, -002, -005 | all student screens (SDK) |
| ANL-04, ANL-05 | FR-ANL-003, -004; FR-PLC-012 | STU-001, STU-011 |
| ANL-06..12 | FR-ANL-004; FR-ORG-015 | TRN-001, TRN-002, COL-001, COL-008, ADM-001, FIN-001 |
| ANL-13..15 | FR-ORG-015; Section H "exportable only by authorised users" | COL-008, FIN-007 |
| NTF-01..05, NTF-10 | FR-NTF-001, -002, -003 | STU-024 |
| NTF-06 | FR-NTF-004 | TRN-002, COL-005 |
| NTF-07..09 | FR-NTF-005 | ADM-011 |
| SUP-01..06, SUP-16 | FR-SUP-001, -002, -003, -008 | STU-025, PUB-019 |
| SUP-07..15 | FR-SUP-004, -005, -006 | SUP-001..004 |
| SUP-17 | — (marketing) | PUB-010 |
| PRV-01..06 | FR-PRV-002, -003 | STU-023 |
| PRV-07..15 | FR-PRV-002; FR-ADM-001 | ADM-009 |
| AUD-01..05 | FR-ADM-001 | ADM-008 |
| ADM-01..06 | FR-ADM-001; FR-SUP-006 | ADM-001, ADM-004 |
| ADM-07..09 | FR-ADM-002 | ADM-006 |
| ADM-10, ADM-11 | FR-ADM-003 | ADM-007 |
| ADM-12..16 | FR-ADM-004 | ADM-010 |
| ADM-17..19 | FR-ADM-005 | ADM-012 |
| SYS-03..05 | — (public policy and status) | PUB-018, PUB-020, PUB-001 |

---

## 27. Issues for Integration Lead

Inconsistencies found while writing this specification. v0.1 followed brief v0.2 and `contract-reconciliation.md`; v0.2 follows brief v0.3, `contract-reconciliation.md` §7 and the applied change requests (IPR-API-*, CPR-API-*); where they are silent it follows `database-schema.md`, then the domain owner's document. No other file was edited.

**Status summary (v0.2):** I-01..I-25 are all **Resolved**; the Status column points to the decision and the section of this spec that now reflects it. New issues found in this pass: I-26 (Resolved in v0.2.1), I-27 (Resolved by interpretation, confirm).

| # | Issue | Where | What this spec assumes | Proposed resolution | Status |
|---|---|---|---|---|---|
| I-01 | **Permission key format.** `database-schema.md` `permissions.permission_key` CHECK requires three segments (`module.resource.action`) and the architecture doc uses `assessments.test.publish`, `coding.testcase.read_hidden`; the role matrix (the stated source of keys) uses mostly two-segment keys (`test.create`, `refund.decide`, `policy.edit`) | schema §6, architecture §6.4, §9.3, role matrix §2 | Role-matrix keys verbatim | Either relax the CHECK to `^[a-z_]+(\.[a-z_]+){1,3}$` or rename the role-matrix keys to three segments; the OpenAPI generator must use one list | **Resolved** (contract-reconciliation §7): role-matrix keys v0.2 (two-segment keys allowed); this spec uses them verbatim |
| I-02 | **Policy-setting permission name.** Security doc §3.1 says `security.policy.write` (super_admin; reviewer can propose); role matrix has `policy.edit` only and no "propose" key | security §3.1, role matrix §2.7 | `policy.edit` for ADM-09; security reviewers propose via a new key | Add `policy.propose` (security_reviewer for `risk.*`, `sessions.*`, `devices.*`, `playback.*`, `login.*`, `otp.*`, `unblock.*` keys) to the role matrix | **Resolved** (contract-reconciliation §7; CPR-RPM-01, IPR-API-08): `policy.propose` adopted — ADM-07..09 |
| I-03 | **Missing permission keys** for endpoints the brief requires: security incidents, trusted-network verification, export approval, analytics ingest | role matrix §2; reconciliation F-RPM-5 | SEC-37..39 use `security.case.read/decide`; SEC-34 uses `security.case.decide`; exports use `report.export` + `approval.decide`; ingest uses ownership | Add `security.incident.manage`, `security.network.verify`, `report.export.request`, `report.export.approve` (F-RPM-5) and document `analytics.event.ingest` (analytics §5.1) or drop it in favour of ownership | **Resolved** (contract-reconciliation §7; IPR-API-01..07, -09): `security.incident.read/manage` (SEC-37..39), `security.network.verify` (SEC-33/34), `report.export.request/approve` (SEC-32, ANL-13, AUD-05, ORG-30, COM-37), ingest by ownership (ANL-01 footnote) |
| I-04 | **Stream-cap error code.** Brief §5 = `409 playback_conflict`; architecture §12 = `409 stream_limit_reached`; the Backend Lead task brief mentioned `stream_cap_reached` | brief §5, architecture §12 | `playback_conflict` (brief wins) | Architecture §12 follow-up edit | **Resolved** (contract-reconciliation §7): `409 playback_conflict` (MED-04) |
| I-05 | **Playback endpoint path.** Security §7.3 `POST /media/playback-tokens`; architecture §12 `POST /media/playback` and `/media/playback/{id}/heartbeat` | security §7.3, architecture §12 | `/media/playback-tokens`, `/media/playback-sessions/{id}/heartbeat` | Architecture follow-up | **Resolved** (contract-reconciliation §7): `/media/playback-tokens`, `/media/playback-sessions/{id}/heartbeat` |
| I-06 | **Assessment binding mechanism.** Architecture §6.2 still describes a Redis "take over" lock and event `session_takeover`; brief v0.2 and schema use `bound_session_id`, `rebind_count`, events `rebind_requested`/`rebind`/`rebind_refused` (no `session_takeover` in the `attempt_events` CHECK, but architecture §8.5 lists it as an integrity event) | architecture §6.2, §8.5; schema §9 | Brief/schema model; integrity events limited to the schema CHECK list | Architecture follow-up (add to F-ARCH list) | **Resolved** (contract-reconciliation §7): binding model + `reattach_same_device` (§15.1) |
| I-07 | **Restriction route tag naming.** Brief §5 / security §7.2: routes tagged `account_status`; architecture §6.3: `restriction_class` with `appeal` / `self_service_minimal`, and CI rule "only in security, identity, support modules" — but the brief's allowlist also includes billing (commerce), notifications, privacy (admin) and devices (sessions) | brief §5, architecture §6.3 | Tag `account_status` (+ `l3_readonly`, `login_continuation`, `mfa_enrolment`, `consent`) declared in any module; CI checks the tag map | Architecture follow-up: rename and drop the module restriction | **Resolved** (contract-reconciliation §7; RE §7.2, CPR-API-01..03): canonical tag set in §1.4, any module, plus `x-td-idle` |
| I-08 | **Missing pending-login status.** `auth_sessions.status` has `pending_mfa`, `pending_device_otp` but nothing for the session-cap choice (`prompt_choose`) | schema §4 | The pending session keeps its last pending status; the cap choice is held server-side for 5 min keyed by the session | Add `pending_session_choice` to the `auth_sessions.status` CHECK | **Resolved** (contract-reconciliation §7; CPR-API-12, IPR-API-10): `pending_session_choice` — §1.2, §1.4, AUTH-06, AUTH-14 |
| I-09 | **Step-up window in the role matrix** still says "≤ 10 min" for all `Up` actions (F-RPM-2 not yet applied); architecture §6.1 still uses `mfa_at` (F-ARCH-3) | role matrix §2, §5; architecture §6.1 | Brief 5/10/15 min via `last_step_up_at` | Apply F-RPM-2 and F-ARCH-3 | **Resolved** (contract-reconciliation §7): 5/10/15 min via `last_step_up_at` (§1.6) |
| I-10 | **Step-up response status.** The task brief specifies `401 step_up_required`; architecture §6.3 uses `403 mfa_required` for missing MFA | architecture §6.3 | `401 step_up_required` (freshness) and `403 mfa_enrolment_required` (no factor enrolled) as distinct codes | Confirm in brief §5 error list | **Resolved** (contract-reconciliation §7): `401 step_up_required` and `403 mfa_enrolment_required` are distinct (§2.1) |
| I-11 | **Subscription grace period.** PRD BR-ENT-09: 5 days; architecture §11.3: 3 days *(policy)* | PRD §4.12, architecture §11.3 | 5 days via new policy key `commerce.subscription_grace_days` | Architecture follow-up; register the key in `policy_settings` namespaces | **Resolved** (contract-reconciliation §7): 5 days, `commerce.subscription_grace_days` (§18.3) |
| I-12 | **Product types vocabulary.** PRD FR-COM-001 types (`free_resource`, `free_course`, `course`, `bundle`, `subscription_plan`, `placement_package`, `mock_pack`, `institution_seat`) differ from `products.product_kind` CHECK (`all_access`, `course`, `test_series`, `company_pack`, `mentor_pack`, `cohort`, `seat_licence`, `extra_learner_seat`) | PRD §4.11, schema §11 | Schema values in responses | Reconcile (add a mapping table or align the CHECK), as was done for entitlement `source_type` (§3.21) | **Resolved** (contract-reconciliation §7; IPR-API-12): PRD vocabulary adopted in schema v0.3 — §17.1 |
| I-13 | **Order status vocabulary.** PRD FR-COM-004: `created → pending → paid/failed/expired`; schema: `pending_payment`, plus `cancelled`, `refunded`, `partially_refunded` | PRD §4.11, schema §11 | Schema values | PRD follow-up | **Resolved** (contract-reconciliation §7; IPR-API-13): order statuses confirmed — §17.1 |
| I-14 | **Webhook staleness.** PRD FR-COM-003 "5 min tolerance" implies rejection; architecture §11.2 processes stale events and flags them | PRD, architecture | Stale events are processed only from a server-side re-fetch of the entity (§18.2 step 5), never from the stale payload | Record in ADR-0006 | **Resolved** (contract-reconciliation §7, ADR-0006 v0.3; CPR-API-06, IPR-API-20): re-fetch for every state-changing event, no age rejection — §18 |
| I-15 | **Section H numbering.** Security doc §10 numbers its views H1–H10 in a different order from the verbatim Section H list (12 items); "Active-session counts" and "Daily/weekly/monthly learning activity" have no view in the security doc; "Repeated IP/device associations" maps only to the PRD CGNAT widget | source excerpt, security §10, PRD §8.5 | Report ids H1–H12 follow the verbatim list; mapping column in SEC-31 | Security Specialist to renumber §10 or adopt the mapping | **Resolved** (contract-reconciliation §7; RE §10, CPR-API-07): RE §10 renumbered H1–H12 + ENG — SEC-31 |
| I-16 | **Analytics batch size.** PRD FR-ANL-001: max 50 events per request; analytics doc §1.4/§5.2: max 100 | PRD, analytics §5.2 | 100 (analytics owns ingest) | PRD follow-up | **Resolved** (contract-reconciliation §7; IPR-API-09): 100 events per request — ANL-01 |
| I-17 | **Autosave interval.** PRD FR-ASM-005: 5 s debounce, max 10 s; architecture §8.5: max 15 s | PRD, architecture | Server accepts any cadence; `ATT-01` returns `max_interval_ms: 15000` | Pick one value (PO or Architect) | **Resolved** (contract-reconciliation §7; IPR-API-11): max 10 s, debounce 5 s — ATT-01 |
| I-18 | **Coding rate limits.** PRD FR-COD-005: Run 10/min, Submit 5/min per problem; architecture §9.4: run ≤ 6/min, submit ≤ 20 per 10 min, 1 in-flight submit | PRD, architecture | PRD values + 1 in-flight submit | Architecture follow-up | **Resolved** (contract-reconciliation §7): PRD values + 1 in-flight submit |
| I-19 | **Device cookie.** Architecture §6.1 still says 256-bit `device_token_hash` = SHA-256; brief/schema: 128-bit, HMAC `device_key_hash` | architecture §6.1 | Brief/schema | Add to F-ARCH list | **Resolved** (contract-reconciliation §7): 128-bit cookie, `HMAC-SHA256(k_device_v{n})` with `key_version` — §1.2 |
| I-20 | **Unblock entry without a session.** PRD FR-SEC-004 / PUB-021 say the appeal is possible "without needing a full session"; v0.2 (PO-07) gives L4 users a `status_only` session | PRD, brief §1 | No unauthenticated unblock endpoint; PUB-021 uses a `status_only` session | PRD follow-up (F-PRD-9 area); confirm PO-07 | **Resolved** (contract-reconciliation §7): no unauthenticated unblock endpoint; `status_only` session (PO-07) |
| I-21 | **Hard-disable message.** NIST/FR-IDN-005 require identical responses for unknown vs wrong password; security §3.2 says hard-disable is "unlocked by password reset or MFA" but no user-facing state is defined | security §3.2, PRD FR-IDN-009 | `401 invalid_credentials` + out-of-band email to the owner | Security Specialist to confirm | **Resolved** (Security Specialist; CPR-API-15): `401 invalid_credentials` + out-of-band notice; reset/MFA login clears the counter — AUTH-06 |
| I-22 | **Refund approver CHECK.** `ck_refund_approver` allows `approved_by = requested_by` for `within_policy_window`; the role matrix requires a second finance approver for goodwill and > ₹25,000 refunds, which the CHECK does not express | schema §11, role matrix §5 | Service rule + `approval_requests` for the Dual cases | Schema comment or CHECK extension | **Resolved** (contract-reconciliation §7; IPR-API-14): `refunds.approval_request_id` + `ck_refund_goodwill_dual` — §17.1, COM-31 |
| I-23 | **Coordinator restriction visibility.** Role matrix M0 lets coordinators see restriction status/level of their students; security §6.1 / policy `org.notify_coordinator_on_restriction` defaults to `L4_status_only` | role matrix §8, security §3.2 | COL-009 badge respects the org policy key (default: only L4 shown) | Product Analyst to align the matrix with the policy default | **Resolved** (contract-reconciliation §7; CPR-RPM-06): follows `org.notify_coordinator_on_restriction` (default `L4_status_only`) — SEC-41 |
| I-24 | **Webhook path.** Architecture §11.2 routes `/webhooks/razorpay` (no `/api/v1` prefix) | architecture §11.2 | `/api/v1/webhooks/razorpay` (all routes under the base path) | DevOps ALB rule to match | **Resolved** (contract-reconciliation §7; IPR-API-20): `/api/v1/webhooks/{provider}` canonical — §18.1 |
| I-25 | **Lab-device enrolment** relies on `devices.shared_scope` in the security doc; schema uses `shared_organization_id` (F-SEC-3 pending) | security §5.5 | Schema column | Apply F-SEC-3 | **Resolved** (Security Specialist; CPR-API-14, IPR-SEC-03): `devices.shared_organization_id` already used — SES-14 |

### New issues (v0.2)

| # | Issue | Where | What this spec assumes | Proposed resolution | Status |
|---|---|---|---|---|---|
| I-26 | **Approver of per-user security report exports.** RE §10 "Reports" still says per-user exports need "an approval from a second security_reviewer"; IPR-API-01 and role matrix v0.2 §5 say a `super_admin` holding `report.export.approve` | RE §10, role matrix §5 | `super_admin` with `report.export.approve` (approver ≠ requester) — SEC-32, §1.7 | Security Specialist to align RE §10 wording with the role matrix | **Resolved** (final cleanup, v0.2.1): security/monitoring exports (H1–H9, H12, per-user device/login history; `security.export.per_user`) are approved by a second `security_reviewer` holding `report.export.approve`, because `super_admin` cannot view security evidence outside break-glass (role matrix §3 notes, `security.evidence.read` = BG); all other exports needing approval (`export.bulk_pii`: H10/H11 aggregates, finance, college reports, bulk PII) by `super_admin`; approver ≠ requester in both. See §1.7, SEC-32, role matrix v0.4 §2.7/§3/§5, RE §10 |
| I-27 | **Cashfree staleness wording.** IPR-API-20 says Cashfree payloads older than `WEBHOOK_TOLERANCE_SECONDS` "are not trusted"; CPR-API-06 / TM §2.4 say no event is rejected for age | integration-pass-requests, consistency-pass-requests, ADR-0006 v0.3 | "Not trusted" = accepted (`2xx`) and applied only from the provider re-fetch; never rejected for age (§18.1 common rules) | ADR-0006 owner to confirm the wording | **Resolved by interpretation** (confirm in ADR-0006) |

---

## 28. Implementation status (Stage 10, 2026-11-03)

**Method.** `create_app()` with `TD_ROUTER_SET=all` was built and its OpenAPI document dumped (361 operations; `/healthz` and `/webhooks/{provider}/health` are `include_in_schema=False`). Every catalogue row in §4–§24 was matched on method + path (path parameters normalised). Per-row results are in each catalogue's **Status** column; per-module totals in §25. Test evidence per module lives in `docs/implementation-status.md`. No endpoint is marked **Deployed**.

### 28.1 Summary

| | Count |
|---|---|
| Catalogued endpoints | 480 (470 from v0.2 + 10 added) |
| Implemented (spec'd before implementation) | 353 (incl. WH-01/02 through the shared provider route) |
| Implemented (added during implementation, §28.2) | 10 |
| Planned (no route in `apps/api`) | 117 |
| Implemented routes **not** in this spec | 0 after back-fill |

Fully implemented families: MED, ATT, ENT, SEC (+SEC-47), UNB (+UNB-19/20), RBAC (+RBAC-07/08). Not started: **SUP** (support desk API, 17). Largely planned: PLC mentoring/resume/mock-interview/company-path authoring (PLC-12..15, PLC-28..52), coding drafts/editorial/similarity (COD-04/05/09/11/12/17/18/20/21/22), NTF preferences and templates, ADM user administration and break-glass (ADM-01..06, ADM-17..19), the generic export pipeline (ANL-13..15, AUD-05, COM-37), passkeys/OTP login/Google OIDC (AUTH-07..10, AUTH-23/24, ME-10/11), contact change (ME-03/04), lab devices (SES-13..16), SYS-03..05 public status/legal/policy numbers.

### 28.2 Routes added during implementation (back-filled)

| ID | Method | Path | Module | Notes |
|---|---|---|---|---|
| COD-23 | GET | `/studio/coding/problems/{problem_id}` | coding | Studio detail; `coding_problem.manage` at the problem's scope |
| COM-47 | GET | `/finance/reports/revenue` | commerce | `order.read` @P; `range_from` / `range_to` query |
| COM-48 / COM-49 | POST | `/finance/approval-requests/{approval_request_id}/approve` · `/reject` | commerce | `approval.decide` @P + P5; commerce-local until ADM-14/15 take over |
| RBAC-07 / RBAC-08 | POST | `/rbac/approval-requests/{approval_request_id}/approve` · `/reject` | rbac | `approval.decide` @P + P5; interim — fold into ADM-14/15 |
| SEC-47 | GET | `/security/reports/exports/{export_job_id}` | security | CSV download for the requester of a completed export; stands in for ANL-15 for security reports |
| UNB-19 | GET | `/security/unblock-requests/form` | security | Form metadata |
| UNB-20 | GET | `/security/unblock-requests/by-reference/{reference}` | security | Owner-only; uniform `404` |
| SYS-06 | GET | `/healthz` | core | Root liveness alias (outside `/api/v1`) |

Not catalogued (operational, hidden): `GET /api/v1/webhooks/{provider}/health`.

### 28.3 Endpoints the web app calls that the API does not provide (backlog C)

| Called by `apps/web` | Nearest spec row | Status |
|---|---|---|
| `GET /assignments` (trainer list) | none — LRN-14 is `POST /assignments` only; students use `GET /me/assignments` | **Gap** — add a trainer list (`assignment.manage` @B/@C) or switch the page to an existing route |
| `GET /studio/coding/problems` (list) | none — only `POST` (COD-13) and detail (COD-23) were catalogued | **Exists in code (2026-11-03 re-check):** `studio_list_problems` (`?status=&q=&cursor=&limit=`, `coding_problem.manage`; response `{data, meta}`) — not yet given a catalogue ID |

### 28.4 Behavioural deviations recorded

1. **`attempt_closed`** carries `attempt_status` (not `status`) and `deadline_at` (§2.3).
2. **Validation status:** FastAPI schema failures are always `400 validation_failed` (§2.1 note).
3. ~~**`maintenance`** gate not wired~~ — **resolved (audit fix wave 3):** `MaintenanceMiddleware` refuses writes while `platform.maintenance_mode` is on, with the `/admin/`, `/auth/` and `/webhooks/` exemptions and 30 s cache described in §2.1. Deviation from the original §2.1 text: webhooks are accepted, not refused.
4. **Webhooks:** one route `/webhooks/{provider}` (razorpay, cashfree); other providers → `404 not_found` before signature checks; SES/SMS-DLR receivers (WH-03/04) not built. Webhook events are processed inline in the request (backlog A7: move to the Celery `critical` queue).
5. **Domain event name:** `attempt.scored` (assessments outbox) — analytics consumes it via its own outbox cursor (`app/modules/analytics/consumer.py`, `ATTEMPT_DONE_TYPES`) and stores it as `assessment.attempt_scored`; switching to `app.core.outbox.register_handler` is backlog A3.
6. **Hidden coding test cases** are stored encrypted in Postgres until S3/KMS credentials exist; COD-17 (signed-URL content) is Planned.
7. **Provider adapters are fakes** until credentials are supplied (Razorpay/Cashfree, VdoCipher, Judge0, SES/SMTP, SMS, S3/KMS) — routes are Implemented, integrations are not; see `docs/implementation-status.md`.
