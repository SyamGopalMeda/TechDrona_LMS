# 00 — Requirements traceability / master feature inventory (area `inventory`)

> **Removed 2026-11-14** ([cleanup/feature-removal-plan.md](../cleanup/feature-removal-plan.md)): mentoring (slots, bookings, sessions, feedback, mentor notes, résumé reviews, the `/mentor` console; the Résumé builder stays), company paths (the `companies` entity stays), corporate enquiries, `GET /catalog/search`, the public SPA pages Hosting redirects to the website, and the `/app/diagnostic`, `/admin/question-review`, `/admin/notifications`, `/app/bookmarks`, `/app/analytics` and `/security/policies` pages. Mentions below of those features are historical.

Auditor: inventory agent · Phase A (audit only) · 2026-11-03 · Brief: `docs/audit/AUDIT-BRIEF.md`

## 0. Method (what was actually run)

All checks are static and read-only. Nothing in the repo was changed except this file. I did not run pytest, vitest or the browser.

| Step | Command / tool | Result |
|---|---|---|
| OpenAPI drift | `python -m app.scripts.export_openapi --out <scratchpad>/openapi_live.json` (from `apps/api`), then a set diff of (method, path) against the committed `apps/api/openapi.json` | 403 paths / 449 operations; **0 drift** (`only committed [] / only live []`) |
| Web copy of the spec | `cmp apps/web/openapi/openapi.json apps/api/openapi.json`; count of `"/api/v1/…"` keys in `apps/web/src/lib/api-types/schema.d.ts` | identical; 403 = 403 |
| Frontend→API wiring | Node + TypeScript compiler-API walk of every non-test `.ts/.tsx` under `apps/web/src` (5,936 string/template literals). Each literal used as a path in `api.get/post/put/patch/delete`, `apiRequest`, `useApi`, `useResource`, `useCursorList`, `useVersioned`, `usePaged`, `serverApiGet`, `serverLoad`, `send(method, path)`, `judgePost`, `startSignedDownload`, `fetch`, or `path`/`*_URL` variables was normalised (`${x}`→`{}`) and matched segment by segment against openapi (path and method). I checked the `${base}/x` call sites by hand: `DecisionPanel.tsx:247-279`, `Governance.tsx:434-437`, `GuardianConsent.tsx:68,94`, `UnblockStatus.tsx:260` | 398 API call sites. **0 calls to a path that does not exist and 0 wrong-method calls.** The only flagged item, `StepUpDialog.tsx:46 [TOTP]`, was a false positive: a `method: "totp"` body field. This agrees with the repo's own `src/features/__contract__/api-paths.test.ts` |
| Request-body shapes | `node node_modules/typescript/bin/tsc --noEmit --incremental false -p tsconfig.json` (apps/web) | exit 0. Request bodies are typed from the Pydantic `Body<>`/`Schema<>` types |
| Response shapes | Not mechanically checkable: most routes return `dict[str, Any]`, so the generated types are open objects (`apps/web/src/lib/api-types/index.ts:6-9`). I spot-checked them by reading the code; see INV-06 | partial |
| Backend endpoints with no UI caller | (openapi ops) − (ops matched by the call-site extraction) | 111 ops have no web caller. After removing false positives: see the "UI caller" column in §5 |
| Test coverage per endpoint | Regex search of every openapi path, allowing params like `{x}`, `{a.b}`, `${x}`, `{r.json()['id']}`, in `apps/api/tests/**/*.py` (excluding `_audit_scratch`) and `apps/web/e2e/*.ts`, plus a weaker suffix match for `f"{base}/suffix"` | 32 ops with no reference found. The heuristic gives some false negatives: for example, reference-solutions **is** tested via `f"{base}/reference-solutions"` in `coding/test_authoring_gaps.py:136`. "none found" therefore means *probably* untested |
| Sitemap → pages | Screen IDs extracted from `docs/sitemap.md` (§2–§11 plus §13 implemented additions), diffed against `find apps/web/src/app -name page.tsx` with route groups stripped | 163 pages. **Every sitemap route has a page, and no page is missing from the sitemap.** **34 pages render `<NotImplemented>`** |
| Nav / href links | Every leading-`/` literal in `href`, `Link`, `router.push/replace`, `redirect` and `lib/nav/portals.ts`, matched against the page routes (dynamic segments allowed) | **0 dead in-app hrefs.** The dead links come from **API-supplied URLs** instead (INV-09, INV-10) |
| Spec ↔ code | 486 endpoint rows parsed from `docs/api-specification.md` and diffed against openapi | 58 spec rows have no route (all marked Planned, except the stub cases below). 58 rows marked "Planned" in the spec are actually implemented. 30 openapi ops are not in the spec |
| Roles | `docs/role-permission-matrix.md` §3/§9 vs `apps/api/app/modules/rbac/catalogue.py` `ROLES` and `lib/nav/portals.ts` | all 9 roles exist, each with a portal. Matrix cell drift is left to the authz/rbac area |

Classification legend: **Impl+tested**; **Impl-untested**; **UI-only** (no backend); **Backend-only** (no UI where a UI is required); **Disconnected** (the UI calls a missing path or method, or expects a shape it does not get); **Not built**; **Fake-adapter-only**; **Partial** (some sub-requirements built).

## 1. Functional requirements (PRD v0.3 §4) → code

Columns: `Feature/Req ID | Requirement source | Code location (API op IDs → web page / component) | Audit method | Result`. "Tests" are listed when the static search found them; *IDs* refer to `docs/api-specification.md` rows; S = static call-site/route extraction, T = test-reference search, R = code read.

| Feature/Req ID | Requirement source | Code location | Audit method | Result |
|---|---|---|---|---|
| FR-IDN-001 | PRD §4.1 signup | AUTH-01 → `/signup` SignupForm; tests identity/test_signup_and_verification.py, e2e identity/auth-pages | S,T | Impl+tested. The "or passkey" part is Not built (AUTH-07/08, ME-10/11 have no route) |
| FR-IDN-002 | §4.1 age gate | AUTH-01 + AUTH-25..27 → `/signup`, `/guardian-consent/[token]` GuardianConsent; e2e auth-pages "under-18 guardian notice" | S,T | Impl+tested. `minor_consent_pending.guardian_flow_url=/app/guardian-consent` is a dead URL (INV-10) |
| FR-IDN-003 | §4.1 email + mobile verification | AUTH-02..05 → `/verify/email/[token]`, `/verify/mobile` Verification | S,T | Email: Impl+tested. **Mobile OTP send/verify and email resend: Impl-untested** (INV-16) |
| FR-IDN-004 | §4.1 password policy | identity/passwords.py + data/common_passwords.txt; test_login_and_passwords.py | R,T | Impl+tested. Breached-password check TO-02 is noted as Planned in security/engine.py:944 |
| FR-IDN-005 | §4.1 login | AUTH-06 → `/login` LoginForm; tests + e2e | S,T | Partial: password login Impl+tested; **passkey login Not built** (AUTH-07/08) |
| FR-IDN-006 | §4.1 MFA | ME-07..09,12,13, AUTH-11 → `/app/settings/security`, `/login/mfa` | S,T | Partial: TOTP and recovery codes Impl+tested; **passkey Not built** (admin/accounts.py:12 "Passkeys are not implemented yet"); SMS OTP login (AUTH-09/10) Not built |
| FR-IDN-007 | §4.1 forgot password | AUTH-16/17 → `/forgot-password`, `/reset-password/[token]` | S,T | Impl+tested |
| FR-IDN-008 | §4.1 change email/mobile (P0) | ME-03/04 not in openapi | S | **Not built** (INV-18) |
| FR-IDN-009 | §4.1 throttling | sessions/login.py; identity/test_login_and_passwords.py | R,T | Impl+tested |
| FR-IDN-010 | §4.1 profile | ME-01/02 → `/app/settings/profile` ProfileSettings | S,T | Impl+tested |
| FR-IDN-011 | §4.1 Google sign-in (P1) | AUTH-23/24 not in openapi | S | Not built |
| FR-IDN-012 | §4.1 invite account linking | ORG-18/19 (`GET/POST /invitations/{token}`) → `/invite/[token]` = **NotImplemented** | S,T | **Backend-only.** Core B2B join path is dead (INV-01) |
| FR-IDN-013 | §4.1 identity confirmation (P1) | none (ADM-06 legal-name Planned) | S | Not built |
| FR-SES-001 | §4.2 opaque sessions | sessions/service.py, BFF cookies; core/test_route_guard_and_auth.py, security SCN19 | R,T | Impl+tested |
| FR-SES-002/003 | §4.2 device token, new-device OTP | AUTH-12/13 → `/login/verify-device` | S,T | Impl+tested |
| FR-SES-004/005 | §4.2 3 devices, 2 replacements/30 d | sessions/test_sessions_and_devices.py; `/app/settings/devices` | T | Impl+tested |
| FR-SES-006 | §4.2 2 sessions, soft prompt | AUTH-14 → `/login/session-choice`; e2e | S,T | Impl+tested |
| FR-SES-007 | §4.2 1 stream | MED-04..06 → player use-playback-session; media/test_media.py | S,T | Impl+tested. **Fake-adapter by default** (`VDOCIPHER_MODE=stub|fake`, media/providers.py:200); a real VdoCipherProvider exists |
| FR-SES-008 | §4.2 devices & sessions page | SES-01..06 → DevicesAndSessions | S,T | Impl+tested. SES-08 login-history is backend-only |
| FR-SES-009 | §4.2 kill all sessions | identity/sessions services; tests | T | Impl+tested |
| FR-SES-010 | §4.2 remember device | AUTH-28 via BFF proxy.ts | S,T | Impl+tested |
| FR-SES-011 | §4.2 one session per attempt | ATT rebind/resume; assessments test_rebind_rules, test_crash_resume… | T | Impl+tested |
| FR-SES-012 | §4.2 limit signals | security/signals.py; test_scn_sessions.py | T | Impl+tested |
| FR-SEC-001 | §4.3 versioned risk scoring | SEC-24..30 → `/security/rules` RuleVersions; test_rules_unit, test_controls_reports | S,T | Impl+tested. Rollback and shadow-report are Impl-untested |
| FR-SEC-003 | §4.3 plain-language reason | `/account/restricted` RestrictedStatus; test_scn_unblock | S,T | Impl+tested. The **L3 landing page `/app/account-status` is a placeholder** (INV-02) |
| FR-SEC-004 | §4.3 unblock request / appeal | UNB-01..09,19,20 → `/unblock-request`, `/account/restricted`; e2e identity "restricted → request a review" | S,T | Partial: create, appeal and withdraw Impl+tested; **attachments are a stub** (UNB-03 always 503, INV-12); STU-026 placeholder (INV-02) |
| FR-SEC-005 | §4.3 human review + second approver | SEC-08..12 → CaseDetail, DecisionPanel; e2e security-console | S,T | Impl+tested |
| FR-SEC-006 | §4.3 support lifts L1/L2 only | SUP-005 `/desk/unblock-requests`: lift/forward **not wired** (SupportDesk.tsx:701-715) | R | **Disconnected / Backend-only** (INV-06) |
| FR-SEC-007 | §4.3 minors deterministic only | SCN09h, SCN06 tests | T | Impl+tested |
| FR-SEC-008 | §4.3 wrongful-restriction remedy | SCN20 tests | T | Impl+tested (API only) |
| FR-SEC-009 | §4.3 account-integrity centre | `/app/settings/devices` (devices/sessions only); SES-07 device-policy and SES-08 login-history have no UI caller; `/app/account-status` placeholder | S | **Partial / Backend-only** (INV-02, INV-19) |
| FR-SEC-010 | §4.3 HC-01/02 auto L3 | SCN09e/f/i tests | T | Impl+tested |
| FR-ORG-001 | §4.4 create org | ORG-01..04 → `/admin/organizations` Organizations | S,T | Impl+tested |
| FR-ORG-002 | §4.4 org settings | ORG-06 `PATCH /orgs/{id}/settings`, `PATCH /orgs/{id}` → no UI caller | S,T | **Backend-only** (INV-14) |
| FR-ORG-003 | §4.4 batches | ORG-20..24 → `/college/batches` Batches | S,T | Impl+tested. Batch PATCH/archive have no UI |
| FR-ORG-004 | §4.4 batch membership | ORG-26/27 (`POST/DELETE /batches/{id}/members`) → **no UI caller** | S,T | **Backend-only** (INV-05) |
| FR-ORG-010/011 | §4.4 bulk import + invite | ORG-11..17 → `/college/students/import` RosterImport; e2e staff-portals | S,T | Impl+tested (import cancel untested) |
| FR-ORG-012 | §4.4 invite acceptance (PUB-016) | ORG-18/19 → `/invite/[token]` **NotImplemented** | S | **Backend-only** (INV-01) |
| FR-ORG-013 | §4.4 seats | ENT-08..10 → `/college/seats` Seats; entitlements/test_access_and_seats | S,T | Impl+tested |
| FR-ORG-014 | §4.4 assign tests | ASM-10..12 → `/college/tests`, trainer AssignTest; e2e | S,T | Impl+tested. ASM-12 `PATCH /test-assignments/{id}` has no UI and no test |
| FR-ORG-015 | §4.4 coordinator reports + export | ANL-05..08, ANL-13..15 → CoordinatorDashboard, `/college/reports` Exports | S,T | Impl+tested. Export approve/reject (dual) has no UI |
| FR-ORG-016 | §4.4 shortlist (P1) | ORG-30 not in openapi; `/college/shortlists` placeholder | S | Not built |
| FR-ORG-017 | §4.4 coordinator staff grants (P1) | RBAC-04 exists (used by admin Governance); `/college/staff` placeholder | S | Backend-only |
| FR-ORG-018 | §4.4 graduation/removal | `DELETE /orgs/{id}/members/{uid}` → no UI caller | S,T | Backend-only |
| FR-ORG-019 | §4.4 placement drives (P2) | none | S | Not built |
| FR-RBAC-001..004 | §4.5 | rbac/catalogue.py, RBAC-01..08 → `/admin/roles` Governance; authz/test_authz_matrix.py | S,T | Impl+tested. RBAC approval reject is untested and has no UI (admin approvals queue is used instead) |
| FR-CAT-001/002 | §4.6 course structure, versioning | CAT-06..14 → `/studio/courses/[id]` Courses; LRN-07 migrate-version (untested) | S,T | Impl+tested. Outline PUT (CAT-12) and lesson PATCH have no UI |
| FR-CAT-003/004 | §4.6 metadata + workflow | CAT-07/09/10/11 → Courses | S,T | Impl+tested |
| FR-CAT-005 | §4.6 free preview | catalog + learning access; e2e learning-commerce | T | Impl+tested |
| FR-CAT-006 | §4.6 resources | CAT-21/22 (studio/resources) no UI; CAT-02 `GET /catalog/free-resources` has no UI caller → `/free-resources` placeholder | S,T | **Backend-only** (INV-13) |
| FR-CAT-007 | §4.6 media upload | MED-01 `POST /media/uploads/video` has no UI caller; `/studio/media` placeholder | S,T | **Backend-only** (INV-03) |
| FR-CAT-008 | §4.6 catalog search | CAT-01, catalog/search → `/courses`; catalog/test_catalog.py, e2e | S,T | Impl+tested |
| FR-CAT-009 | §4.6 trainer org-private courses | `/trainer/courses` reuses studio CourseList | S | Impl (scope tests in authz) |
| FR-MED-001/002 | §4.6 DRM playback, watermark | media/providers.py VdoCipherProvider + FakeVideoProvider; player VideoPlayer | R,T | Impl+tested. **Fake adapter in dev** |
| FR-LRN-001..003 | §4.7 enrolment, progress | LRN-01..06 → `/app/learning`, `/app/courses/[slug]`, `/app/learn/...`; learning/test_learning.py; e2e | S,T | Impl+tested. `POST /me/lessons/{key}/completion` is referenced only in tests via an f-string |
| FR-LRN-004/005 | §4.7 assignments + grading | LRN-08..19 → `/app/assignments`, trainer Grading | S,T | Impl+tested. LRN-15 PATCH assignment has no UI |
| FR-LRN-006 | §4.7 certificates | LRN-11..13 → `/app/certificates`, `/verify/[id]` | S,T | Impl+tested |
| FR-LRN-007 | §4.7 certificate revocation | LRN-20/21 → no UI caller | S,T | **Backend-only** (INV-19) |
| FR-LRN-008 | §4.7 Add to LinkedIn (P1) | no "linkedin" anywhere in apps/web/src | S | Not built |
| FR-LRN-009 | §4.7 bookmarks/notes (P1) | LRN-25..27 not in openapi; `/app/bookmarks` placeholder | S | Not built |
| FR-PLC-001 | §4.8 subjects/taxonomy | PLC-01 → practice; PLC-02/03 studio/topics no UI; `/studio/taxonomy` placeholder | S,T | Partial (student read Impl+tested; authoring Backend-only, INV-13) |
| FR-PLC-002..004 | §4.8 question bank + lifecycle | PLC-04..11 → `/studio/questions`, `/studio/review`; placement tests | S,T | Impl+tested |
| FR-PLC-005 | §4.8 practice mode | PLC-18..24 → `/app/practice/...`; e2e student-learning | S,T | Impl+tested |
| FR-PLC-006 | §4.8 mastery | PLC-25 → SubjectTopics, ProgressDashboard | S,T | Impl+tested |
| FR-PLC-007 | §4.8 company paths | PLC-16/17 + company-paths PUT have no UI (`/studio/companies` placeholder); `/app/companies` shows "Not available yet" (CompaniesIndex.tsx:7); `/app/companies/[slug]` → `GET /me/company-paths/{slug}` | S,T | **Partial / Backend-only** (INV-13) |
| FR-PLC-008/009 | §4.8 technical/HR interview prep (P1) | `/app/interview-prep` placeholder; no API | S | Not built |
| FR-PLC-010 | §4.8 mock interviews | PLC-36..46 → `/app/mentoring`, `/mentor/*`; mentoring tests | S,T | Impl+tested |
| FR-PLC-011 | §4.8 recommendations | PLC-26/27 → practice shared | S,T | Impl+tested |
| FR-PLC-012 | §4.8 skill analytics STU-010/011 | ANL-03/04 → `/app/progress` (built); `/app/analytics` placeholder | S,T | Partial |
| FR-PLC-013 | §4.8 diagnostic (P0) | `/app/diagnostic` placeholder; only a test `type` value in assessments/schemas.py | S | **Not built** (INV-18) |
| FR-PLC-014 | §4.8 goal picker (P0) | PLC-28/29 not in openapi; `/app/onboarding` placeholder | S | **Not built** (INV-18) |
| FR-PLC-015 | §4.8 resume builder | PLC-47..52 → `/app/resume` Resume; PLC-49 export Planned, GET pdf exists | S,T | Partial (builder Impl+tested; templates/PDF render per spec Planned) |
| FR-PLC-016 | §4.8 learning path (P1) | PLC-30/31 not in openapi; `/app/path` placeholder | S | Not built |
| FR-PLC-017 | §4.8 question reporting | PLC-33..35 → PracticeSession, `/studio/reports/errors` | S,T | Impl+tested |
| FR-PLC-018 | §4.8 bulk question import (P1) | PLC-12..14 not in openapi; `/studio/questions/import` placeholder | S | Not built |
| FR-ASM-001..003 | §4.9 test definition, types, schedule | ASM-01..09 → `/studio/tests`, `/trainer/tests/[id]/edit` | S,T | Impl+tested |
| FR-ASM-004..006 | §4.9 server timer, autosave, resume | ATT-01..13 → `/app/attempts/...` AttemptRunner; e2e "timed test: start, autosave, refresh-resume, offline sync" | S,T | Impl+tested. Section enter/submit are referenced in tests |
| FR-ASM-007 | §4.9 overrides | ASM-13/14 → TestOps | S,T | Impl+tested |
| FR-ASM-008/009 | §4.9 review visibility, results | ATT-11/12, ASM-15 → ResultsView | S,T | Impl+tested |
| FR-ASM-010 | §4.9 integrity events | ATT autosave events; test_integrity_events_are_advisory… | T | Impl+tested |
| FR-ASM-011 | §4.9 regrade (AC-ASM-06) | ASM-17 not in openapi (assessments/router.py:8) | S | **Not built** |
| FR-ASM-012 | §4.9 invalidation | ASM-18/20 → trainer Integrity; the student **appeal link is dead** | S,T | Impl+tested + Issue (INV-09) |
| FR-ASM-013 | §4.9 accommodation (P1) | no "accommodation" in apps/api | S | Not built |
| FR-ASM-014 | §4.9 palette | AttemptRunner/RunnerParts | R | Impl (unit assessment.test.tsx) |
| FR-ASM-015 | §4.9 leaderboard (P1) | ASM-23 not in openapi | S | Not built |
| FR-COD-001..006 | §4.10 problems, languages, editor, run/submit, limits, history | COD-01..08, 13..19 → `/app/coding/...`, `/studio/coding/...`; coding tests; e2e | S,T | Impl+tested. **Judge: FakeJudgeAdapter in dev** (coding/__init__.py:23); Judge0 adapter exists |
| FR-COD-007 | §4.10 coding in tests | AttemptRunner + coding | R | Impl (no dedicated test found) |
| FR-COD-008 | §4.10 similarity (P1) | COD-21/22 not in openapi | S | Not built |
| FR-COD-009 | §4.10 snapshot replay (P2) | none | S | Not built |
| FR-COD-010 | §4.10 judge outage | coding/test_judge.py | T | Impl+tested. `stream_url` points to a missing SSE route (INV-10) |
| FR-COM-001/002 | §4.11 products, INR/GST | COM-01..03, COM-20..23 → catalog/pricing (read); **`/finance/products` placeholder** | S,T | Partial: storefront Impl+tested; finance authoring Backend-only (INV-04) |
| FR-COM-003/004 | §4.11 checkout, order status | COM-04..08 → `/app/checkout/*`, `/app/orders/[id]`; e2e "checkout a paid plan"; `orders/{id}/confirm`/`cancel` | S,T | Impl+tested. **Razorpay FakePaymentProvider in dev** (gateway.py:350) |
| FR-COM-005 | §4.11 subscriptions / UPI AutoPay | COM-09/10 (`/commerce/subscriptions*`) have **no UI caller**; recurring plans are sold through `commerce/orders` (PricingPlans.tsx:73 → Checkout.tsx:137) | S,R | **Backend-only** (INV-15) |
| FR-COM-006 | §4.11 plan change | COM-13/14 → ChangePlanDialog, Billing | S,T | Impl+tested |
| FR-COM-007 | §4.11 coupons | COM-24..27 → **`/finance/coupons` placeholder**; quote applies coupons | S,T | **Backend-only** for management (INV-04). COM-27 PATCH untested |
| FR-COM-008 | §4.11 refunds | COM-18/19, finance/refunds decision → Billing, Finance | S,T | Impl+tested. Finance-initiated refund (POST /finance/refunds) has no UI |
| FR-COM-009 | §4.11 GST invoices | COM-15/16, finance invoices/credit-notes/gst-exports → Billing, FinanceDocuments | S,T | Impl+tested. Credit-note path is referenced via f-string |
| FR-COM-010 | §4.11 contracts | COM-38..43 → `/finance/contracts`; `/college/contract` | S,T | Impl+tested |
| FR-COM-011 | §4.11 sponsored warning | Checkout.tsx `included_in_subscription` etc. | R | Impl |
| FR-COM-012 | §4.11 chargeback | commerce/test_coupons_refunds_subscriptions.py (dispute) | T | Impl+tested (API) |
| FR-COM-013 | §4.11 reconciliation | COM-44/45 → `/finance/reconciliation` | S,T | Impl+tested |
| FR-COM-014 | §4.11 no card data | n/a | — | Not assessed (security area) |
| FR-ENT-001/003 | §4.12 access check | ENT-01/02, core/access; entitlements/test_decision_cache.py | T | Impl+tested |
| FR-ENT-002 | §4.12 "what I have access to" | ENT-03 → `/app/access` AccessList | S,T | Impl+tested |
| FR-ENT-004 | §4.12 audit | audit tests | T | Impl+tested |
| FR-ENT-005 | §4.12 manual grants | ENT-06/07 → **no UI caller** | S,T | **Backend-only** (INV-19) |
| FR-ANL-001/002 | §4.13 events, heartbeats | ANL-01/02 → lib/analytics/transport.ts; analytics tests | S,T | Impl+tested (beacon untested) |
| FR-ANL-003 | §4.13 daily aggregates | analytics/jobs.py, tasks.py (beat registered) | R,T | Impl+tested (jobs.py:4 docstring says beat wiring is "Planned", but tasks.py registers it: doc drift) |
| FR-ANL-004 | §4.13 reports | ANL-05..10 → coordinator/trainer; **platform (ANL-10) and course (ANL-09) reports have no UI caller**; ANL-11 commerce Not built | S,T | Partial |
| FR-ANL-005 | §4.13 minors | analytics consent gating tests | T | Impl+tested |
| FR-NTF-001 | §4.14 channels | email: SMTP adapter (Mailpit in dev); **SMS: ConsoleSmsAdapter only** (notifications/adapters.py:109,148-153); in-app: NTF-01..03 **no UI** | R,S | **Partial: SMS Fake-adapter-only; in-app Backend-only** (INV-07) |
| FR-NTF-002 | §4.14 transactional events | notifications/test_notifications.py | T | Impl+tested (email) |
| FR-NTF-003 | §4.14 preferences (P0) | NTF-04/05 not in openapi (notifications/router.py:3) | S | **Not built** (INV-18) |
| FR-NTF-004 | §4.14 batch announcements | NTF-06 → no UI caller | S,T | Backend-only (INV-19) |
| FR-NTF-005 | §4.14 templates | NTF-07..09 not in openapi; `/admin/notifications` placeholder | S | Not built |
| FR-SUP-001..006 | §4.15 tickets, context, SLA, workspace, lookup, actions | SUP-01..15 → `/app/support/*`, `/desk/*` | S,T | Impl+tested, **except** the unblock lift/forward actions (INV-06) |
| FR-SUP-007 | §4.15 support device reset | SES-12 → SupportDesk | S,T | Impl+tested |
| FR-SUP-008 | §4.15 CSAT | SUP-06 → StudentSupport | S,T | Impl+tested |
| FR-PRV-001 | §4.16 itemised consent | AUTH-01, ME-05/06 → signup, PrivacySettings | S,T | Impl+tested |
| FR-PRV-002 | §4.16 export + deletion (P0) | PRV-01..05 (`/me/privacy-requests*`) → **no UI caller**; `/app/settings/privacy` shows consents only | S,T | **Backend-only** (INV-08) |
| FR-PRV-003 | §4.16 guardian consent | AUTH-25..27 → GuardianConsent | S,T | Impl+tested |
| FR-ADM-001 | §4.16 audit log | AUD-01..03 → `/admin/audit` | S,T | Impl+tested. Org audit (AUD-04) and export (AUD-05) Not built |
| FR-ADM-002 | §4.16 policy settings | ADM-07..09 → `/admin/policies`, `/security/policies` | S,T | Impl+tested |
| FR-ADM-003 | §4.16 feature flags | ADM-10/11 → Governance | S,T | Impl+tested |
| FR-ADM-004 | §4.16 approvals queue | ADM-12..16 → `/admin/approvals` | S,T | Impl+tested |
| FR-ADM-005 | §4.16 break-glass | ADM-17..19 → `/admin/break-glass` | S,T | Impl+tested (passkey step-up replaced by TOTP, admin/accounts.py:12) |
| NFR-* | PRD §5 | — | — | Not assessed in this area (perf/sec/a11y areas) |

## 2. Section H reports (source-requirements-excerpt §H) → code

The backend catalogue is `apps/api/app/modules/security/reports.py:36-57` (`REPORTS` and `_RUNNERS` at :558). The UI is `/security/reports` (ReportsIndex) and `/security/reports/[report_key]` (ReportView + ExportRequest), with the catalogue in `apps/web/src/features/security-admin/lib/catalogue.ts:12-24`. API test: `apps/api/tests/security/test_controls_reports.py:257-316` asserts the catalogue = H1–H12 + ENG, `reason_code` gating, role denials, and export approval routing.

| Feature/Req ID | Requirement source | Code location | Audit method | Result |
|---|---|---|---|---|
| H1 Top suspicious accounts | §H item 1 | `top-suspicious-accounts` → `_h1`; ReportView | S,T (200 smoke) | Impl+tested |
| H2 Multiple-account/device associations | §H 2 | `account-device-associations` → `_h2` | S,T | Impl+tested |
| H3 Concurrent login events | §H 3 | `concurrent-login-events` | S,T | Impl+tested |
| H4 Repeated IP/device associations | §H 4 | `repeated-network-device-associations` | S,T | Impl+tested |
| H5 Blocked accounts | §H 5 | `blocked-accounts` (+ export test, reason-code test) | S,T | Impl+tested |
| H6 Pending unblock requests | §H 6 | `pending-unblock-requests` | S,T | Impl+tested |
| H7 Average review time | §H 7 | `average-review-time` (super_admin aggregate allowed) | S,T | Impl+tested |
| H8 False-positive rate | §H 8 | `false-positive-rate` (+ export test) | S,T | Impl+tested |
| H9 Repeat incidents | §H 9 | `repeat-incidents` | S,T | Impl+tested |
| H10 Active-session counts | §H 10 | `active-session-counts` | S,T | Impl+tested |
| H11 Daily/weekly/monthly learning activity | §H 11 | `learning-activity` | S,T | Impl+tested |
| H12 Device and login history | §H 12 | `device-login-history` → `_h12`; UI catalogue entry | S,T | **Impl-untested**: not in the test loop at test_controls_reports.py:267-279, and `device-login-history` appears in no test or e2e (INV-17) |
| H-export | "exportable only by authorised users" | SEC-32 POST export → ExportRequest; **SEC-47 `GET /security/reports/exports/{id}` (download) has no UI caller**; the UI says "You will be notified when the file is ready" (Reports.tsx:150), but in-app notifications have no UI | S,R | **Backend-only for retrieval** (INV-11) |
| H-dashboard | PRD §8.5 SEC-001 tiles H1–H12 | SEC-40 `GET /security/dashboard` has no UI caller; SecurityDashboard.tsx:17 only reads `security/cases` counts and lists report links | S,R | Partial (INV-11) |

## 3. Phase 8 account-sharing scenarios → tests

| Feature/Req ID | Requirement source | Code location (test) | Audit method | Result |
|---|---|---|---|---|
| SCN-01 laptop → phone | Phase 8 #1 | security/test_scn_sessions.py `test_scn01_laptop_then_phone_daily_overlap_scores_l0` | T | Impl+tested |
| SCN-02 several tabs | #2 | `test_scn02_many_tabs_one_session…` + e2e multi-tab.integration.spec.ts "SCN-02" | T | Impl+tested |
| SCN-03 same college Wi-Fi | #3 | `test_scn03_campus_wifi_many_students_no_lockout_no_signals` | T | Impl+tested |
| SCN-04 Wi-Fi → mobile data | #4 | `test_scn04_network_change_keeps_session…` | T | Impl+tested |
| SCN-05 concurrent unrelated devices | #5 | `test_scn05a_*`, `test_scn05a2_*` | T | Impl+tested |
| SCN-06 many accounts one device | #6 | `test_scn06_shared_pc_lab_pc_minor_and_restricted_device_reuse` | T | Impl+tested. Lab-device enrolment (SES-13..16) Not built |
| SCN-07 impossible travel | #7 | `test_scn07_geo_inconsistent…`, `test_scn07_first_login_outside_india…` | T | Impl+tested |
| SCN-08 VPN | #8 | `test_scn08_vpn_student_capped_and_tor_adds_takeover_only` | T | Impl+tested |
| SCN-09 HC auto-restrict | #9 | `test_scn09c..i` (7 tests) | T | Impl+tested |
| SCN-10 legit unblock request | #10 | `test_scn10_*` (2) + e2e reverify.integration.spec.ts "SCN-10" + identity e2e | T | Impl+tested (attachments stub, INV-12) |
| SCN-11 approve + revoke sessions | #11 | `test_scn11_*` (3) + e2e security-console | T | Impl+tested |
| SCN-12 reject with reason | #12 | `test_scn12_*` (3) | T | Impl+tested |
| SCN-13 blocked user direct API | #13 | `test_scn13_*` (2) + e2e restricted-direct-api.integration.spec.ts | T | Impl+tested |
| SCN-14 duplicate webhook | #14 | `test_scn14_same_webhook_delivered_repeatedly_is_processed_once` | T | Impl+tested |
| SCN-15 idle tab hours | #15 | `test_scn15_idle_session_expires_and_background_poll_does_not_extend` | T | Impl+tested |
| SCN-16 browser crash in timed test | #16 | assessments `test_crash_resume_same_device_reattaches_without_rebind`, `test_scn16b_relogin…`; e2e student-learning "refresh-resume" | T | Impl+tested |
| SCN-17 multi-tab time manipulation | #17 | `test_scn17_time_manipulation_is_integrity_only` | T | Impl+tested |
| SCN-18 cross-institution access | #18 | `test_scn18_cross_org_access_404_and_ab09_alert`; authz/test_object_level.py | T | Impl+tested |
| SCN-19 session-id tamper / revoked reuse | #19 | `test_scn19_*` (3) | T | Impl+tested |
| SCN-20 false-positive dispute | #20 | `test_scn20_*` (2) | T | Impl+tested |

I verified that these tests exist, not that they pass. Pass/fail belongs to the security and backend-QA areas.

## 4. Roles (role-permission-matrix §9) → code

| Feature/Req ID | Requirement source | Code location | Audit method | Result |
|---|---|---|---|---|
| student | RPM §9 | `ROLES["student"]` catalogue.py:47; portal `/app` (48 pages, 9 placeholders) | R,S | Impl. Placeholders: account-status, analytics, bookmarks, college, diagnostic, interview-prep, notifications, onboarding, path (+ public ones) |
| college_coordinator | §9 | catalogue.py:48; `/college` (13 pages; shortlists, staff, students/[user_id] placeholders) | R,S | Impl, partial UI |
| trainer | §9 | catalogue.py:51; `/trainer` (13 pages, 0 placeholders) | R,S | Impl |
| content_manager | §9 | catalogue.py:52; `/studio` (15 pages; companies, media, questions/import, taxonomy placeholders) | R,S | Impl, partial UI |
| placement_mentor | §9 | catalogue.py:53; `/mentor` (6 pages) | R,S | Impl |
| support_agent | §9 | catalogue.py:54; `/desk` (4 pages) | R,S | Impl (unblock triage actions missing, INV-06) |
| security_reviewer | §9 | catalogue.py:55; `/security` (11 pages) | R,S | Impl |
| finance_admin | §9 | catalogue.py:56; `/finance` (9 pages; coupons, products, subscriptions placeholders) | R,S | Impl, partial UI (INV-04) |
| super_admin | §9 | catalogue.py:57; `/admin` (13 pages; notifications placeholder) | R,S | Impl |
| Permission matrix §3 | RPM §3 | catalogue.py `_ROWS` (125 perms) vs doc §3 (78 parsed rows; doc groups several keys) | R | Left to the authz area. A quick diff showed notation-level differences only (for example `enrolment.read` FIN doc `P` vs code `R`, and `question.answer_key.read` STU doc `p` vs code `-`) |

## 5. API endpoints (openapi.json, 449 operations + 58 spec-only) → UI caller → tests

"UI caller" = web source files (basename) whose call sites resolve to this operation (static extraction, §0). "Tests" = first matching API test files (+N more) and e2e specs. "none found" means no static reference, so probably untested (see the false-negative caveat in §0). The classification follows the legend in §0. Paths are relative to `/api/v1`.

| Spec ID | Operation | UI caller | Tests | Result |
|---|---|---|---|---|
| ADM-12 | `GET /admin/approvals` | ApprovalsQueue | admin/test_accounts.py, admin/test_admin.py (+4) | Implemented+tested |
| ADM-13 | `GET /admin/approvals/{approval_id}` | — | admin/test_accounts.py, admin/test_admin.py (+3) | Backend-only (tested) |
| ADM-14 | `POST /admin/approvals/{approval_id}/approve` | ApprovalsQueue | admin/test_accounts.py, admin/test_admin.py (+4) | Implemented+tested |
| ADM-16 | `POST /admin/approvals/{approval_id}/cancel` | ApprovalsQueue | admin/test_admin.py, commerce/test_documents_plan_change.py | Implemented+tested |
| ADM-15 | `POST /admin/approvals/{approval_id}/reject` | ApprovalsQueue | admin/test_admin.py, commerce/test_documents_plan_change.py | Implemented+tested |
| ADM-19 | `GET /admin/break-glass` | Governance | admin/test_accounts.py | Implemented+tested |
| ADM-17 | `POST /admin/break-glass` | Governance | admin/test_accounts.py | Implemented+tested |
| ADM-18 | `POST /admin/break-glass/{session_id}/end` | Governance | admin/test_accounts.py | Implemented+tested |
| — | `POST /admin/break-glass/{session_id}/review` | Governance | admin/test_accounts.py | Implemented+tested |
| ADM-01 | `GET /admin/dashboard` | Governance | admin/test_accounts.py | Implemented+tested |
| ADM-10 | `GET /admin/feature-flags` | Governance | admin/test_admin.py | Implemented+tested |
| ADM-11 | `PATCH /admin/feature-flags/{flag_key}` | Governance | admin/test_admin.py | Implemented+tested |
| ADM-07 | `GET /admin/policy-settings` | PolicySettings | admin/test_admin.py, security/test_controls_reports.py | Implemented+tested |
| ADM-08 | `GET /admin/policy-settings/{setting_key}` | — | admin/test_admin.py, security/test_controls_reports.py | Backend-only (tested) |
| ADM-09 | `POST /admin/policy-settings/{setting_key}/changes` | PolicySettings | admin/test_admin.py, security/test_controls_reports.py | Implemented+tested |
| PRV-07 | `GET /admin/privacy-requests` | Governance | admin/test_admin.py | Implemented+tested |
| PRV-08 | `GET /admin/privacy-requests/{request_id}` | Governance | admin/test_admin.py | Implemented+tested |
| PRV-10 | `POST /admin/privacy-requests/{request_id}/complete` | Governance | admin/test_admin.py, security/test_seed_and_guard.py | Implemented+tested |
| PRV-11 | `POST /admin/privacy-requests/{request_id}/reject` | Governance | admin/test_admin.py | Implemented+tested |
| PRV-09 | `POST /admin/privacy-requests/{request_id}/verify-identity` | Governance | **none found** | Implemented-untested |
| PRV-13 | `GET /admin/retention-policies` | — | admin/test_admin.py | Backend-only (tested) |
| ADM-02 | `GET /admin/users` | Users | admin/test_accounts.py | Implemented+tested |
| ADM-03 | `GET /admin/users/{user_id}` | Users | admin/test_accounts.py | Implemented+tested |
| ADM-04 | `POST /admin/users/{user_id}/deactivate` | Users | admin/test_accounts.py | Implemented+tested |
| ADM-05 | `POST /admin/users/{user_id}/mfa-reset` | Users | admin/test_accounts.py | Implemented+tested |
| — | `POST /admin/users/{user_id}/reactivate` | Users | admin/test_accounts.py | Implemented+tested |
| ANL-03 | `GET /analytics/config` | transport | analytics/test_ingest.py | Implemented+tested |
| ANL-01 | `POST /analytics/events` | transport | analytics/test_ingest.py | Implemented+tested |
| ANL-02 | `POST /analytics/events/beacon` | proxy, transport | **none found** | Implemented-untested |
| ANL-12 | `GET /analytics/ingest-health` | — | analytics/test_pipeline.py, authz/matrix.py | Implemented+tested (no UI needed) |
| ANL-06 | `GET /analytics/reports/batches/{batch_id}` | Batches | analytics/test_pipeline.py | Implemented+tested |
| ANL-09 | `GET /analytics/reports/courses/{course_id}` | — | **none found** | Backend-only, untested |
| ANL-07 | `GET /analytics/reports/orgs/{org_id}` | CoordinatorDashboard | analytics/test_pipeline.py | Implemented+tested |
| ANL-08 | `GET /analytics/reports/orgs/{org_id}/students/{user_id}` | — | analytics/test_pipeline.py | Backend-only (tested) |
| ANL-10 | `GET /analytics/reports/platform` | — | analytics/test_pipeline.py | Backend-only (tested) |
| — | `GET /assignment-submissions/{submission_id}` | Grading | authz/matrix.py, learning/test_learning.py (+1) | Implemented+tested |
| LRN-17 | `POST /assignment-submissions/{submission_id}/grade` | Grading | authz/matrix.py, learning/test_learning.py | Implemented+tested |
| LRN-19 | `POST /assignment-submissions/{submission_id}/grade-override` | Grading | learning/test_learning.py | Implemented+tested |
| — | `GET /assignments` | Grading | assessments/test_attempts.py, authz/matrix.py (+3) | Implemented+tested |
| LRN-14 | `POST /assignments` | Grading | assessments/test_attempts.py, authz/matrix.py (+3) | Implemented+tested |
| LRN-15 | `PATCH /assignments/{assignment_id}` | — | learning/test_learning.py | Backend-only (tested) |
| LRN-18 | `POST /assignments/{assignment_id}/release-grades` | Grading | learning/test_learning.py | Implemented+tested |
| LRN-16 | `GET /assignments/{assignment_id}/submissions` | Grading | learning/test_learning.py | Implemented+tested |
| ATT-01 | `POST /attempts` | api | assessments/test_attempts.py, assessments/test_integrity_and_report.py (+2) ; e2e: multi-tab.integration.spec.ts, restricted-direct-api.integration.spec.ts | Implemented+tested |
| ATT-06 | `POST /attempts/{attempt_id}/autosave` | api | assessments/test_attempts.py | Implemented+tested |
| ASM-20 | `POST /attempts/{attempt_id}/integrity-decision` | Integrity | assessments/test_integrity_and_report.py, authz/matrix.py | Implemented+tested |
| ASM-18 | `POST /attempts/{attempt_id}/invalidate` | — | assessments/test_integrity_and_report.py, authz/matrix.py | Backend-only (tested) |
| ATT-05 | `POST /attempts/{attempt_id}/rebind` | api | assessments/test_attempts.py | Implemented+tested |
| ASM-21 | `POST /attempts/{attempt_id}/rebind-override` | TestOps | assessments/test_attempts.py, authz/matrix.py | Implemented+tested |
| ATT-04 | `POST /attempts/{attempt_id}/rebind/otp` | api | assessments/test_attempts.py | Implemented+tested |
| ATT-11 | `GET /attempts/{attempt_id}/result` | api | assessments/test_attempts.py | Implemented+tested |
| ATT-03 | `POST /attempts/{attempt_id}/resume` | api | assessments/test_attempts.py | Implemented+tested |
| ATT-12 | `GET /attempts/{attempt_id}/review` | api | assessments/test_attempts.py, authz/matrix.py | Implemented+tested |
| ATT-08 | `POST /attempts/{attempt_id}/sections/{section_id}/enter` | api | assessments/test_attempts.py | Implemented+tested |
| ATT-09 | `POST /attempts/{attempt_id}/sections/{section_id}/submit` | api | assessments/test_attempts.py, assessments/test_integrity_and_report.py (+1) | Implemented+tested |
| ATT-02 | `GET /attempts/{attempt_id}/state` | api | assessments/test_attempts.py | Implemented+tested |
| ATT-10 | `POST /attempts/{attempt_id}/submit` | api | assessments/test_attempts.py, assessments/test_integrity_and_report.py (+1) ; e2e: restricted-direct-api.integration.spec.ts | Implemented+tested |
| ATT-07 | `GET /attempts/{attempt_id}/time` | api | assessments/test_attempts.py | Implemented+tested |
| AUD-03 | `GET /audit/chain-status` | Governance | audit/test_audit_api.py | Implemented+tested |
| AUD-01 | `GET /audit/events` | Governance | audit/test_audit_api.py | Implemented+tested |
| AUD-02 | `GET /audit/events/{seq}` | Governance | audit/test_audit_api.py | Implemented+tested |
| AUTH-12 | `POST /auth/device-verification/send` | DeviceVerificationForm | catalog/factory.py, identity/test_seeds_and_audit.py (+3) | Implemented+tested |
| AUTH-13 | `POST /auth/device-verification/verify` | DeviceVerificationForm | catalog/factory.py, identity/test_seeds_and_audit.py (+3) | Implemented+tested |
| AUTH-25 | `GET /auth/guardian-consent/{token}` | GuardianConsent | identity/test_signup_and_verification.py | Implemented+tested |
| AUTH-27 | `POST /auth/guardian-consent/{token}/decision` | GuardianConsent | identity/test_signup_and_verification.py | Implemented+tested |
| AUTH-26 | `POST /auth/guardian-consent/{token}/verify-contact` | GuardianConsent | identity/test_signup_and_verification.py | Implemented+tested |
| AUTH-06 | `POST /auth/login` | LoginForm | identity/factory.py ; e2e: smoke.spec.ts | Implemented+tested |
| AUTH-15 | `POST /auth/logout` | SignOutButton | identity/test_login_and_passwords.py, identity/test_seeds_and_audit.py (+3) | Implemented+tested |
| AUTH-11 | `POST /auth/mfa/verify` | MfaForm | identity/factory.py, identity/test_login_and_passwords.py (+2) | Implemented+tested |
| AUTH-18 | `POST /auth/password/change` | SecuritySettings | identity/test_login_and_passwords.py, identity/test_seeds_and_audit.py | Implemented+tested |
| AUTH-16 | `POST /auth/password/forgot` | PasswordRecovery | identity/test_email_links.py, identity/test_login_and_passwords.py (+1) | Implemented+tested |
| AUTH-17 | `POST /auth/password/reset` | PasswordRecovery | identity/test_login_and_passwords.py, security/test_security_regression.py | Implemented+tested |
| AUTH-28 | `POST /auth/remember/refresh` | bff/proxy | sessions/test_sessions_and_devices.py | Implemented+tested |
| AUTH-22 | `POST /auth/reverify/complete` | ReverifyPanel | security/test_scn_unblock.py, security/test_seed_and_guard.py | Implemented+tested |
| AUTH-21 | `POST /auth/reverify/start` | ReverifyPanel | security/test_scn_unblock.py | Implemented+tested |
| AUTH-14 | `POST /auth/session-choice` | SessionChoice | sessions/test_sessions_and_devices.py | Implemented+tested |
| AUTH-01 | `POST /auth/signup` | SignupForm | identity/test_email_links.py, identity/test_signup_and_verification.py | Implemented+tested |
| AUTH-20 | `POST /auth/step-up` | StepUpDialog | identity/factory.py, identity/test_login_and_passwords.py (+3) | Implemented+tested |
| AUTH-19 | `POST /auth/step-up/options` | — | identity/test_login_and_passwords.py, orgs/test_orgs.py (+1) | Backend-only (tested) |
| AUTH-02 | `POST /auth/verify/email` | Verification | identity/test_signup_and_verification.py | Implemented+tested |
| AUTH-03 | `POST /auth/verify/email/resend` | ProfileSettings, Verification | **none found** | Implemented-untested |
| AUTH-05 | `POST /auth/verify/mobile` | Verification | **none found** | Implemented-untested |
| AUTH-04 | `POST /auth/verify/mobile/send-otp` | Verification | **none found** | Implemented-untested |
| ORG-22 | `GET /batches/{batch_id}` | Batches, batches | analytics/test_pipeline.py, notifications/test_notifications.py (+1) | Implemented+tested |
| ORG-23 | `PATCH /batches/{batch_id}` | — | analytics/test_pipeline.py, notifications/test_notifications.py (+1) | Backend-only (tested) |
| NTF-06 | `POST /batches/{batch_id}/announcements` | — | notifications/test_notifications.py | Backend-only (tested) |
| ORG-24 | `POST /batches/{batch_id}/archive` | — | orgs/test_orgs.py | Backend-only (tested) |
| ORG-25 | `GET /batches/{batch_id}/members` | Batches, TestOps, batches | orgs/test_orgs.py | Implemented+tested |
| ORG-26 | `POST /batches/{batch_id}/members` | — | orgs/test_orgs.py | Backend-only (tested) |
| ORG-27 | `DELETE /batches/{batch_id}/members/{user_id}` | — | orgs/test_orgs.py | Backend-only (tested) |
| CAT-01 | `GET /catalog/courses` | page | catalog/test_catalog.py, catalog/test_seed.py | Implemented+tested |
| CAT-02 | `GET /catalog/courses/{slug}` | server, use-course | catalog/test_catalog.py, catalog/test_seed.py | Implemented+tested |
| CAT-06 | `GET /catalog/free-resources` | — | catalog/test_catalog.py | Backend-only (tested) |
| CAT-07 | `GET /catalog/search` | page | catalog/test_catalog.py | Implemented+tested |
| LRN-20 | `POST /certificates` | — | authz/matrix.py, learning/test_learning.py | Backend-only (tested) |
| LRN-13 | `GET /certificates/verify/{public_code}` | page | learning/test_learning.py | Implemented+tested |
| LRN-21 | `POST /certificates/{certificate_id}/revoke` | — | authz/matrix.py, learning/test_learning.py | Backend-only (tested) |
| COD-01 | `GET /coding/languages` | api | coding/test_flow.py, coding/test_studio.py | Implemented+tested |
| COD-02 | `GET /coding/problems` | api | coding/test_authoring_gaps.py, coding/test_flow.py (+4) | Implemented+tested |
| COD-05 | `GET /coding/problems/{problem_id}/drafts/{language_key}` | api | coding/test_authoring_gaps.py | Implemented+tested |
| COD-04 | `PUT /coding/problems/{problem_id}/drafts/{language_key}` | api | coding/test_authoring_gaps.py | Implemented+tested |
| COD-06 | `POST /coding/problems/{problem_id}/run` | api | coding/test_flow.py, coding/test_judge.py ; e2e: restricted-direct-api.integration.spec.ts | Implemented+tested |
| COD-07 | `POST /coding/problems/{problem_id}/submit` | api | coding/test_flow.py, coding/test_judge.py (+1) ; e2e: restricted-direct-api.integration.spec.ts | Implemented+tested |
| COD-03 | `GET /coding/problems/{slug}` | api | coding/test_authoring_gaps.py, coding/test_flow.py (+4) | Implemented+tested |
| COD-08 | `GET /coding/submissions/{submission_id}` | api | coding/test_flow.py, coding/test_judge.py | Implemented+tested |
| COM-03 | `POST /commerce/checkout/quote` | Checkout | commerce/factory.py, commerce/test_checkout_webhooks.py (+2) | Implemented+tested |
| COM-04 | `POST /commerce/orders` | Checkout | commerce/factory.py, commerce/test_checkout_webhooks.py (+1) | Implemented+tested |
| COM-05 | `GET /commerce/orders/{order_id}` | OrderStatus | commerce/test_checkout_webhooks.py, commerce/test_coupons_refunds_subscriptions.py | Implemented+tested |
| COM-07 | `POST /commerce/orders/{order_id}/cancel` | PaymentStep | commerce/test_checkout_webhooks.py, commerce/test_coupons_refunds_subscriptions.py (+1) | Implemented+tested |
| COM-06 | `POST /commerce/orders/{order_id}/confirm` | PaymentStep | commerce/test_checkout_webhooks.py, commerce/test_coupons_refunds_subscriptions.py (+1) | Implemented+tested |
| COM-01 | `GET /commerce/products` | Billing, CourseDetail, page | commerce/test_checkout_webhooks.py, commerce/test_coupons_refunds_subscriptions.py | Implemented+tested |
| COM-02 | `GET /commerce/products/{sku}` | — | commerce/test_checkout_webhooks.py | Backend-only (tested) |
| COM-09 | `POST /commerce/subscriptions` | — | commerce/test_coupons_refunds_subscriptions.py, commerce/test_documents_plan_change.py | Backend-only (tested) |
| COM-10 | `POST /commerce/subscriptions/{subscription_id}/confirm` | — | commerce/test_checkout_webhooks.py, commerce/test_coupons_refunds_subscriptions.py (+1) | Backend-only (tested) |
| LRN-22 | `GET /enrolments` | — | authz/matrix.py, learning/test_learning.py (+2) | Backend-only (tested) |
| LRN-23 | `POST /enrolments` | — | authz/matrix.py, learning/test_learning.py (+2) | Backend-only (tested) |
| ENT-01 | `POST /entitlements/check` | — | commerce/test_checkout_webhooks.py, commerce/test_coupons_refunds_subscriptions.py (+1) | Implemented+tested (no UI needed) |
| ENT-02 | `POST /entitlements/check-batch` | — | entitlements/test_access_and_seats.py | Implemented+tested (no UI needed) |
| ENT-06 | `POST /entitlements/grants` | — | authz/matrix.py, entitlements/test_access_and_seats.py | Backend-only (tested) |
| ENT-05 | `GET /entitlements/{entitlement_id}/events` | — | entitlements/test_access_and_seats.py | Backend-only (tested) |
| ENT-07 | `POST /entitlements/{entitlement_id}/revoke` | — | authz/matrix.py, entitlements/test_access_and_seats.py (+1) | Backend-only (tested) |
| — | `GET /exports` | Exports | analytics/test_exports.py, security/test_controls_reports.py | Implemented+tested |
| ANL-13 | `POST /exports` | Exports | analytics/test_exports.py, security/test_controls_reports.py | Implemented+tested |
| ANL-14 | `GET /exports/{export_job_id}` | — | analytics/test_exports.py, security/test_controls_reports.py | Backend-only (tested) |
| — | `POST /exports/{export_job_id}/approve` | — | analytics/test_exports.py, commerce/test_documents_plan_change.py (+1) | Backend-only (tested) |
| ANL-15 | `GET /exports/{export_job_id}/download` | Exports | analytics/test_exports.py, commerce/test_documents_plan_change.py | Implemented+tested |
| — | `POST /exports/{export_job_id}/reject` | — | analytics/test_exports.py, commerce/test_documents_plan_change.py | Backend-only (tested) |
| COM-48 | `POST /finance/approval-requests/{approval_request_id}/approve` | — | commerce/test_coupons_refunds_subscriptions.py, entitlements/test_access_and_seats.py (+3) | Backend-only (tested) |
| COM-49 | `POST /finance/approval-requests/{approval_request_id}/reject` | — | **none found** | Backend-only, untested |
| COM-38 | `GET /finance/contracts` | Finance | commerce/test_documents_plan_change.py, entitlements/test_access_and_seats.py | Implemented+tested |
| COM-39 | `POST /finance/contracts` | Finance | commerce/test_documents_plan_change.py, entitlements/test_access_and_seats.py | Implemented+tested |
| COM-40 | `PATCH /finance/contracts/{contract_id}` | — | commerce/test_documents_plan_change.py, entitlements/test_access_and_seats.py | Backend-only (tested) |
| — | `GET /finance/contracts/{contract_id}/invoices` | FinanceDocuments | commerce/test_documents_plan_change.py, entitlements/test_access_and_seats.py | Implemented+tested |
| COM-42 | `POST /finance/contracts/{contract_id}/invoices` | FinanceDocuments | commerce/test_documents_plan_change.py, entitlements/test_access_and_seats.py | Implemented+tested |
| COM-41 | `POST /finance/contracts/{contract_id}/terminate` | Finance | entitlements/test_access_and_seats.py | Implemented+tested |
| COM-25 | `GET /finance/coupons` | — | commerce/test_coupons_refunds_subscriptions.py | Backend-only (tested) |
| COM-26 | `POST /finance/coupons` | — | commerce/test_coupons_refunds_subscriptions.py | Backend-only (tested) |
| COM-27 | `PATCH /finance/coupons/{coupon_id}` | — | **none found** | Backend-only, untested |
| — | `GET /finance/gst-exports` | FinanceDocuments | commerce/test_documents_plan_change.py | Implemented+tested |
| COM-37 | `POST /finance/gst-exports` | FinanceDocuments | commerce/test_documents_plan_change.py | Implemented+tested |
| — | `GET /finance/gst-exports/{gst_export_id}` | — | commerce/test_documents_plan_change.py | Backend-only (tested) |
| — | `GET /finance/gst-exports/{gst_export_id}/download` | FinanceDocuments | commerce/test_documents_plan_change.py | Implemented+tested |
| COM-35 | `GET /finance/invoices` | Finance | commerce/test_documents_plan_change.py, entitlements/test_access_and_seats.py | Implemented+tested |
| COM-36 | `POST /finance/invoices/{invoice_id}/credit-notes` | Finance | commerce/test_documents_plan_change.py | Implemented+tested |
| — | `GET /finance/invoices/{invoice_id}/pdf` | FinanceDocuments | commerce/test_documents_plan_change.py | Implemented+tested |
| COM-28 | `GET /finance/orders` | Finance | commerce/test_coupons_refunds_subscriptions.py, entitlements/test_access_and_seats.py | Implemented+tested |
| COM-29 | `GET /finance/orders/{order_id}` | Finance | commerce/test_coupons_refunds_subscriptions.py | Implemented+tested |
| COM-24 | `POST /finance/plans/{plan_id}/prices` | — | commerce/test_coupons_refunds_subscriptions.py | Backend-only (tested) |
| COM-20 | `GET /finance/products` | — | commerce/test_coupons_refunds_subscriptions.py | Backend-only (tested) |
| COM-21 | `POST /finance/products` | — | commerce/test_coupons_refunds_subscriptions.py | Backend-only (tested) |
| COM-22 | `PATCH /finance/products/{product_id}` | — | commerce/test_coupons_refunds_subscriptions.py | Backend-only (tested) |
| COM-23 | `POST /finance/products/{product_id}/plans` | — | commerce/test_coupons_refunds_subscriptions.py | Backend-only (tested) |
| COM-45 | `GET /finance/reconciliation` | Finance | commerce/test_coupons_refunds_subscriptions.py, entitlements/test_access_and_seats.py | Implemented+tested |
| COM-46 | `POST /finance/reconciliation/runs` | Finance | commerce/test_coupons_refunds_subscriptions.py | Implemented+tested |
| COM-30 | `GET /finance/refunds` | Finance | commerce/test_coupons_refunds_subscriptions.py | Implemented+tested |
| COM-32 | `POST /finance/refunds` | — | commerce/test_coupons_refunds_subscriptions.py | Backend-only (tested) |
| COM-31 | `POST /finance/refunds/{refund_id}/decision` | Finance | commerce/test_coupons_refunds_subscriptions.py | Implemented+tested |
| COM-47 | `GET /finance/reports/revenue` | — | commerce/test_coupons_refunds_subscriptions.py | Backend-only (tested) |
| COM-33 | `GET /finance/subscriptions` | — | commerce/test_documents_plan_change.py | Backend-only (tested) |
| COM-34 | `POST /finance/subscriptions/{subscription_id}/cancel` | — | commerce/test_checkout_webhooks.py, commerce/test_coupons_refunds_subscriptions.py (+1) | Backend-only (tested) |
| SYS-01 | `GET /health/live` | — | core/test_errors_request_id.py, core/test_health.py | Implemented+tested (no UI needed) |
| SYS-02 | `GET /health/ready` | — | core/test_health.py | Implemented+tested (no UI needed) |
| ASM-19 | `GET /integrity/flags` | Integrity | assessments/test_integrity_and_report.py | Implemented+tested |
| ORG-18 | `GET /invitations/{token}` | — | orgs/test_orgs.py | Backend-only (tested) |
| ORG-19 | `POST /invitations/{token}/accept` | — | orgs/test_orgs.py | Backend-only (tested) |
| ME-01 | `GET /me` | ApprovalsQueue, ProfileSettings, UnblockRequestForm | admin/test_accounts.py, admin/test_admin.py (+30) ; e2e: multi-tab.integration.spec.ts, reverify.integration.spec.ts | Implemented+tested |
| ANL-05 | `GET /me/analytics/learning-time` | metrics | analytics/test_pipeline.py | Implemented+tested |
| ANL-04 | `GET /me/analytics/summary` | metrics | analytics/test_ingest.py, analytics/test_pipeline.py | Implemented+tested |
| LRN-08 | `GET /me/assignments` | Assignments | learning/test_learning.py | Implemented+tested |
| LRN-09 | `GET /me/assignments/{assignment_id}` | Assignments | learning/test_learning.py | Implemented+tested |
| LRN-10 | `POST /me/assignments/{assignment_id}/submissions` | Assignments | learning/test_learning.py | Implemented+tested |
| ATT-13 | `GET /me/attempts` | api | **none found** | Implemented-untested |
| LRN-11 | `GET /me/certificates` | Certificates | learning/test_learning.py | Implemented+tested |
| LRN-12 | `GET /me/certificates/{certificate_id}/pdf` | Certificates | learning/test_learning.py | Implemented+tested |
| COD-10 | `GET /me/coding/submissions` | api | coding/test_flow.py | Implemented+tested |
| PLC-32 | `GET /me/company-paths/{slug}` | api | placement/test_placement.py | Implemented+tested |
| ME-05 | `GET /me/consents` | PrivacySettings | identity/test_signup_and_verification.py, sessions/test_restrictions_and_hooks.py | Implemented+tested |
| ME-06 | `POST /me/consents` | PrivacySettings | identity/test_signup_and_verification.py, sessions/test_restrictions_and_hooks.py | Implemented+tested |
| LRN-04 | `GET /me/courses/{course_id}` | use-course | learning/test_learning.py | Implemented+tested |
| LRN-05 | `GET /me/courses/{course_id}/lessons/{lesson_id}` | LessonView | learning/test_learning.py | Implemented+tested |
| LRN-07 | `POST /me/courses/{course_id}/migrate-version` | CourseOverview | **none found** | Implemented-untested |
| LRN-01 | `GET /me/dashboard` | StudentDashboard | security/test_scn02_tabs.py | Implemented+tested |
| SES-07 | `GET /me/device-policy` | — | sessions/test_sessions_and_devices.py | Backend-only (tested) |
| SES-04 | `GET /me/devices` | DevicesAndSessions, UnblockRequestForm | identity/test_seeds_and_audit.py, security/test_scn02_tabs.py (+1) | Implemented+tested |
| SES-06 | `DELETE /me/devices/{user_device_id}` | DevicesAndSessions | sessions/test_sessions_and_devices.py | Implemented+tested |
| SES-05 | `PATCH /me/devices/{user_device_id}` | DevicesAndSessions | sessions/test_sessions_and_devices.py | Implemented+tested |
| LRN-02 | `GET /me/enrolments` | MyCourses | learning/test_learning.py, media/test_media.py (+1) | Implemented+tested |
| LRN-03 | `POST /me/enrolments` | CourseAccess | learning/test_learning.py, media/test_media.py (+1) | Implemented+tested |
| ENT-03 | `GET /me/entitlements` | AccessList | commerce/test_checkout_webhooks.py, entitlements/test_access_and_seats.py | Implemented+tested |
| RBAC-06 | `GET /me/grants` | grants | rbac/test_rbac.py | Implemented+tested |
| COM-15 | `GET /me/invoices` | Billing | commerce/test_documents_plan_change.py | Implemented+tested |
| COM-16 | `GET /me/invoices/{invoice_id}/pdf` | Billing | commerce/test_documents_plan_change.py | Implemented+tested |
| LRN-06 | `POST /me/lessons/{lesson_key}/completion` | LessonView | learning/test_learning.py | Implemented+tested |
| SES-08 | `GET /me/login-history` | — | sessions/test_sessions_and_devices.py | Backend-only (tested) |
| PLC-25 | `GET /me/mastery` | api | placement/test_placement.py | Implemented+tested |
| PLC-40 | `GET /me/mentoring/bookings` | Mentoring | mentoring/test_mentoring.py | Implemented+tested |
| ME-07 | `GET /me/mfa/factors` | SecuritySettings | identity/test_login_and_passwords.py | Implemented+tested |
| ME-12 | `DELETE /me/mfa/factors/{factor_id}` | SecuritySettings | identity/test_login_and_passwords.py | Implemented+tested |
| ME-13 | `POST /me/mfa/recovery-codes` | SecuritySettings | identity/test_login_and_passwords.py | Implemented+tested |
| ME-08 | `POST /me/mfa/totp` | SecuritySettings | identity/test_login_and_passwords.py | Implemented+tested |
| ME-09 | `POST /me/mfa/totp/{factor_id}/confirm` | SecuritySettings | identity/test_login_and_passwords.py | Implemented+tested |
| NTF-01 | `GET /me/notifications` | — | admin/test_accounts.py, notifications/test_notifications.py (+1) | Backend-only (tested) |
| NTF-03 | `POST /me/notifications/read-all` | — | notifications/test_notifications.py | Backend-only (tested) |
| NTF-02 | `POST /me/notifications/{notification_id}/read` | — | notifications/test_notifications.py | Backend-only (tested) |
| COM-08 | `GET /me/orders` | Billing | commerce/test_coupons_refunds_subscriptions.py | Implemented+tested |
| COM-17 | `GET /me/orders/{order_id}/refund-eligibility` | Billing | commerce/test_coupons_refunds_subscriptions.py | Implemented+tested |
| ORG-28 | `GET /me/orgs` | — | orgs/test_orgs.py, security/test_scn_sessions.py (+1) | Backend-only (tested) |
| ORG-29 | `PATCH /me/orgs/{org_id}` | — | orgs/test_orgs.py | Backend-only (tested) |
| PLC-24 | `GET /me/practice/review` | api | placement/test_placement.py | Implemented+tested |
| PRV-01 | `GET /me/privacy-requests` | — | admin/test_admin.py, security/test_seed_and_guard.py | Backend-only (tested) |
| PRV-02 | `POST /me/privacy-requests` | — | admin/test_admin.py, security/test_seed_and_guard.py | Backend-only (tested) |
| PRV-03 | `GET /me/privacy-requests/{request_id}` | — | admin/test_admin.py | Backend-only (tested) |
| PRV-05 | `GET /me/privacy-requests/{request_id}/export` | — | admin/test_admin.py | Backend-only (tested) |
| PRV-04 | `POST /me/privacy-requests/{request_id}/withdraw` | — | admin/test_admin.py | Backend-only (tested) |
| ME-02 | `PATCH /me/profile` | ProfileSettings | identity/test_signup_and_verification.py, security/test_scn_sessions.py (+3) | Implemented+tested |
| PLC-26 | `GET /me/recommendations` | api | placement/test_placement.py | Implemented+tested |
| PLC-27 | `POST /me/recommendations/{recommendation_id}/dismiss` | api | placement/test_placement.py | Implemented+tested |
| COM-19 | `GET /me/refund-requests` | Billing | commerce/test_coupons_refunds_subscriptions.py | Implemented+tested |
| COM-18 | `POST /me/refund-requests` | Billing | commerce/test_coupons_refunds_subscriptions.py | Implemented+tested |
| PLC-47 | `GET /me/resumes` | Resume | mentoring/test_mentoring.py, mentoring/test_resumes.py | Implemented+tested |
| — | `POST /me/resumes` | Resume | mentoring/test_mentoring.py, mentoring/test_resumes.py | Implemented+tested |
| PLC-48 | `PUT /me/resumes/{resume_id}` | Resume | mentoring/test_resumes.py | Implemented+tested |
| — | `GET /me/resumes/{resume_id}/pdf` | Resume | mentoring/test_resumes.py | Implemented+tested |
| — | `POST /me/resumes/{resume_id}/pdf-upload` | Resume | mentoring/test_resumes.py | Implemented+tested |
| — | `POST /me/resumes/{resume_id}/pdf-upload/complete` | Resume | mentoring/test_resumes.py | Implemented+tested |
| PLC-50 | `POST /me/resumes/{resume_id}/review-requests` | Resume | mentoring/test_resumes.py | Implemented+tested |
| SEC-02 | `GET /me/security/cases/{case_ref}` | — | **none found** | Backend-only, untested |
| SEC-46 | `POST /me/security/events/{event_ref}/disown` | SecuritySettings | security/test_controls_reports.py | Implemented+tested |
| SEC-01 | `GET /me/security/status` | RestrictedStatus, UnblockRequestForm | security/test_scn_sessions.py, security/test_seed_and_guard.py ; e2e: reverify.integration.spec.ts | Implemented+tested |
| SES-01 | `GET /me/sessions` | DevicesAndSessions | authz/test_authz_matrix.py, security/test_scn02_tabs.py (+2) ; e2e: multi-tab.integration.spec.ts | Implemented+tested |
| SES-03 | `POST /me/sessions/revoke-others` | DevicesAndSessions | sessions/test_sessions_and_devices.py | Implemented+tested |
| SES-02 | `DELETE /me/sessions/{session_id}` | DevicesAndSessions | sessions/test_sessions_and_devices.py | Implemented+tested |
| COM-11 | `GET /me/subscriptions` | Billing | commerce/test_checkout_webhooks.py, commerce/test_coupons_refunds_subscriptions.py (+1) | Implemented+tested |
| COM-12 | `POST /me/subscriptions/{subscription_id}/cancel` | Billing | commerce/test_checkout_webhooks.py, commerce/test_coupons_refunds_subscriptions.py (+1) | Implemented+tested |
| COM-14 | `POST /me/subscriptions/{subscription_id}/change-plan` | ChangePlanDialog | commerce/test_documents_plan_change.py | Implemented+tested |
| COM-13 | `POST /me/subscriptions/{subscription_id}/resume` | Billing | commerce/test_documents_plan_change.py | Implemented+tested |
| SUP-02 | `GET /me/support/tickets` | StudentSupport | support/test_support.py | Implemented+tested |
| ASM-01 | `GET /me/tests` | TestsList, api | assessments/test_attempts.py | Implemented+tested |
| MED-03 | `GET /media/assets/{lesson_asset_id}/status` | — | catalog/test_catalog.py, media/test_media.py | Backend-only (tested) |
| MED-07 | `POST /media/downloads` | LessonView | media/test_media.py | Implemented+tested |
| MED-05 | `POST /media/playback-sessions/{playback_session_id}/heartbeat` | use-playback-session | media/test_media.py, security/test_scn02_tabs.py | Implemented+tested |
| MED-06 | `POST /media/playback-sessions/{playback_session_id}/stop` | use-playback-session | media/test_media.py, security/test_scn02_tabs.py | Implemented+tested |
| MED-04 | `POST /media/playback-tokens` | use-playback-session | media/test_media.py, security/test_scn02_tabs.py (+1) | Implemented+tested |
| MED-02 | `POST /media/uploads/file` | Assignments | learning/test_learning.py, media/test_media.py | Implemented+tested |
| MED-01 | `POST /media/uploads/video` | — | catalog/test_catalog.py, media/test_media.py | Backend-only (tested) |
| PLC-44 | `POST /mentor/bookings/{booking_id}/feedback` | Mentor | mentoring/test_mentoring.py | Implemented+tested |
| PLC-45 | `POST /mentor/bookings/{booking_id}/no-show` | Mentor | mentoring/test_mentoring.py | Implemented+tested |
| PLC-51 | `GET /mentor/resume-reviews` | Mentor, ResumeReviews | mentoring/test_resumes.py | Implemented+tested |
| PLC-52 | `POST /mentor/resume-reviews/{review_id}/feedback` | ResumeReviews | mentoring/test_resumes.py | Implemented+tested |
| PLC-43 | `GET /mentor/sessions` | Mentor | mentoring/test_mentoring.py | Implemented+tested |
| — | `GET /mentor/sessions/{booking_id}` | Mentor | mentoring/test_mentoring.py | Implemented+tested |
| — | `PATCH /mentor/sessions/{booking_id}` | Mentor | mentoring/test_mentoring.py | Implemented+tested |
| — | `GET /mentor/slots` | Slots | mentoring/test_mentoring.py | Implemented+tested |
| PLC-41 | `POST /mentor/slots` | Slots | mentoring/test_mentoring.py | Implemented+tested |
| PLC-42 | `DELETE /mentor/slots/{slot_id}` | Slots | mentoring/test_mentoring.py | Implemented+tested |
| — | `GET /mentor/students` | Mentor | mentoring/test_mentoring.py, placement/test_stage10_endpoints.py | Implemented+tested |
| PLC-46 | `GET /mentor/students/{user_id}` | Mentor | mentoring/test_mentoring.py, placement/test_stage10_endpoints.py | Implemented+tested |
| — | `GET /mentor/students/{user_id}/notes` | — | mentoring/test_mentoring.py | Backend-only (tested) |
| — | `POST /mentor/students/{user_id}/notes` | shared | mentoring/test_mentoring.py | Implemented+tested |
| PLC-37 | `POST /mentoring/bookings` | Mentoring | mentoring/test_mentoring.py | Implemented+tested |
| PLC-39 | `POST /mentoring/bookings/{booking_id}/cancel` | Mentoring | mentoring/test_mentoring.py | Implemented+tested |
| PLC-38 | `POST /mentoring/bookings/{booking_id}/reschedule` | Mentoring | mentoring/test_mentoring.py | Implemented+tested |
| PLC-36 | `GET /mentoring/slots` | Mentoring | mentoring/test_mentoring.py | Implemented+tested |
| ORG-01 | `GET /orgs` | Organizations | analytics/conftest.py, analytics/test_pipeline.py (+10) | Implemented+tested |
| ORG-02 | `POST /orgs` | Organizations | analytics/conftest.py, analytics/test_pipeline.py (+10) | Implemented+tested |
| ORG-03 | `GET /orgs/{org_id}` | Organizations | analytics/test_pipeline.py, authz/matrix.py (+8) | Implemented+tested |
| ORG-04 | `PATCH /orgs/{org_id}` | — | analytics/test_pipeline.py, authz/matrix.py (+8) | Backend-only (tested) |
| ORG-20 | `GET /orgs/{org_id}/batches` | Batches, Reports, RosterImport… | analytics/test_pipeline.py, orgs/test_orgs.py | Implemented+tested |
| ORG-21 | `POST /orgs/{org_id}/batches` | Batches, Organizations | analytics/test_pipeline.py, orgs/test_orgs.py | Implemented+tested |
| COM-43 | `GET /orgs/{org_id}/contract` | CoordinatorDashboard, Seats | entitlements/test_access_and_seats.py | Implemented+tested |
| ORG-10 | `POST /orgs/{org_id}/imports` | Organizations, RosterImport | orgs/test_orgs.py | Implemented+tested |
| ORG-11 | `GET /orgs/{org_id}/imports/{job_id}` | RosterImport | orgs/test_orgs.py | Implemented+tested |
| ORG-13 | `POST /orgs/{org_id}/imports/{job_id}/cancel` | RosterImport | **none found** | Implemented-untested |
| ORG-12 | `POST /orgs/{org_id}/imports/{job_id}/commit` | RosterImport | orgs/test_orgs.py | Implemented+tested |
| ORG-14 | `GET /orgs/{org_id}/invitations` | Students | orgs/test_orgs.py | Implemented+tested |
| ORG-15 | `POST /orgs/{org_id}/invitations` | Organizations, Students | orgs/test_orgs.py | Implemented+tested |
| ORG-16 | `POST /orgs/{org_id}/invitations/{invitation_id}/resend` | Students | orgs/test_orgs.py | Implemented+tested |
| ORG-17 | `POST /orgs/{org_id}/invitations/{invitation_id}/revoke` | Students | orgs/test_orgs.py | Implemented+tested |
| COM-44 | `GET /orgs/{org_id}/invoices` | Seats | commerce/test_documents_plan_change.py, entitlements/test_access_and_seats.py | Implemented+tested |
| — | `GET /orgs/{org_id}/invoices/{invoice_id}/pdf` | — | commerce/test_documents_plan_change.py | Backend-only (tested) |
| ORG-07 | `GET /orgs/{org_id}/members` | Seats, Students | orgs/test_orgs.py, security/test_scn_sessions.py | Implemented+tested |
| ORG-09 | `DELETE /orgs/{org_id}/members/{user_id}` | — | orgs/test_orgs.py, security/test_scn_sessions.py | Backend-only (tested) |
| ORG-08 | `GET /orgs/{org_id}/members/{user_id}` | — | orgs/test_orgs.py, security/test_scn_sessions.py | Backend-only (tested) |
| PRV-12 | `GET /orgs/{org_id}/privacy-requests` | — | **none found** | Backend-only, untested |
| — | `POST /orgs/{org_id}/reactivate` | Organizations | authz/test_authz_matrix.py, orgs/test_lifecycle.py | Implemented+tested |
| ENT-08 | `GET /orgs/{org_id}/seats` | CoordinatorDashboard, Seats | entitlements/test_access_and_seats.py | Implemented+tested |
| ENT-09 | `POST /orgs/{org_id}/seats/assignments` | Seats | entitlements/test_access_and_seats.py | Implemented+tested |
| ENT-10 | `POST /orgs/{org_id}/seats/revocations` | Seats | entitlements/test_access_and_seats.py | Implemented+tested |
| SEC-41 | `GET /orgs/{org_id}/security-summary` | CoordinatorDashboard, Organizations | security/test_controls_reports.py | Implemented+tested |
| ORG-06 | `PATCH /orgs/{org_id}/settings` | — | orgs/test_orgs.py | Backend-only (tested) |
| ORG-05 | `POST /orgs/{org_id}/suspend` | Organizations | authz/test_authz_matrix.py, orgs/test_lifecycle.py | Implemented+tested |
| SEC-36 | `GET /orgs/{org_id}/trusted-networks` | TrustedNetworks | authz/matrix.py, security/test_controls_reports.py | Implemented+tested |
| SEC-35 | `POST /orgs/{org_id}/trusted-networks` | Organizations, TrustedNetworks | authz/matrix.py, security/test_controls_reports.py | Implemented+tested |
| PLC-01 | `GET /placement/subjects` | api | placement/test_placement.py | Implemented+tested |
| PLC-19 | `POST /practice/sessions` | api | placement/test_placement.py | Implemented+tested |
| PLC-20 | `GET /practice/sessions/{session_id}` | api | placement/test_placement.py | Implemented+tested |
| PLC-21 | `POST /practice/sessions/{session_id}/answers` | api | placement/test_placement.py ; e2e: restricted-direct-api.integration.spec.ts | Implemented+tested |
| PLC-23 | `POST /practice/sessions/{session_id}/complete` | api | admin/test_admin.py, placement/test_placement.py (+1) | Implemented+tested |
| PLC-22 | `POST /practice/sessions/{session_id}/questions/{question_version_id}/reveal` | api | placement/test_placement.py | Implemented+tested |
| LRN-24 | `GET /progress` | — | authz/matrix.py, learning/test_learning.py | Backend-only (tested) |
| PLC-33 | `POST /questions/{question_id}/reports` | api | analytics/test_pipeline.py, placement/test_question_reports.py | Implemented+tested |
| RBAC-07 | `POST /rbac/approval-requests/{approval_request_id}/approve` | — | commerce/test_coupons_refunds_subscriptions.py, entitlements/test_access_and_seats.py (+3) | Backend-only (tested) |
| RBAC-08 | `POST /rbac/approval-requests/{approval_request_id}/reject` | — | **none found** | Backend-only, untested |
| RBAC-03 | `GET /rbac/grants` | Governance | authz/matrix.py, identity/test_seeds_and_audit.py (+1) | Implemented+tested |
| RBAC-04 | `POST /rbac/grants` | Governance | authz/matrix.py, identity/test_seeds_and_audit.py (+1) | Implemented+tested |
| RBAC-05 | `POST /rbac/grants/{grant_id}/revoke` | Governance | authz/matrix.py, entitlements/test_access_and_seats.py (+2) | Implemented+tested |
| RBAC-02 | `GET /rbac/permissions` | — | authz/matrix.py, rbac/test_rbac.py | Backend-only (tested) |
| RBAC-01 | `GET /rbac/roles` | — | rbac/test_rbac.py | Backend-only (tested) |
| SEC-03 | `GET /security/cases` | CaseQueue, SecurityDashboard | authz/matrix.py, security/test_case_pending_approval.py (+2) ; e2e: a11y.integration.spec.ts, security-console.integration.spec.ts | Implemented+tested |
| SEC-12 | `POST /security/cases` | — | authz/matrix.py, security/test_case_pending_approval.py (+2) ; e2e: a11y.integration.spec.ts, security-console.integration.spec.ts | Backend-only (tested) |
| SEC-04 | `GET /security/cases/{case_id}` | CaseDetail | security/test_case_pending_approval.py, security/test_scn_unblock.py ; e2e: a11y.integration.spec.ts, security-console.integration.spec.ts | Implemented+tested |
| SEC-10 | `POST /security/cases/{case_id}/approval-requests/{approval_request_id}/approve` | DecisionPanel | commerce/test_coupons_refunds_subscriptions.py, entitlements/test_access_and_seats.py (+3) | Implemented+tested |
| SEC-11 | `POST /security/cases/{case_id}/approval-requests/{approval_request_id}/send-back` | DecisionPanel | security/test_scn_unblock.py | Implemented+tested |
| SEC-11a | `POST /security/cases/{case_id}/approval-requests/{approval_request_id}/withdraw` | DecisionPanel | security/test_case_pending_approval.py, security/test_scn_unblock.py | Implemented+tested |
| SEC-06 | `POST /security/cases/{case_id}/assign` | CaseDetail | **none found** | Implemented-untested |
| SEC-05 | `POST /security/cases/{case_id}/claim` | CaseDetail, CaseQueue | security/test_scn_unblock.py | Implemented+tested |
| SEC-09 | `POST /security/cases/{case_id}/decisions` | DecisionPanel | security/test_scn_unblock.py | Implemented+tested |
| SEC-07 | `GET /security/cases/{case_id}/explanation` | EvidenceTabs | security/test_scn_unblock.py | Implemented+tested |
| SEC-08 | `POST /security/cases/{case_id}/notes` | EvidenceTabs | security/test_scn_unblock.py | Implemented+tested |
| SEC-40 | `GET /security/dashboard` | — | authz/matrix.py | Backend-only (tested) |
| SEC-42 | `POST /security/engine/kill-switch` | EngineControls | security/test_controls_reports.py | Implemented+tested |
| SEC-43 | `GET /security/engine/state` | EngineControls, PolicySettings | security/test_controls_reports.py | Implemented+tested |
| SEC-17 | `GET /security/evaluations` | — | authz/matrix.py | Backend-only (tested) |
| SEC-18 | `GET /security/evaluations/{evaluation_id}` | — | **none found** | Backend-only, untested |
| SEC-37 | `GET /security/incidents` | — | authz/matrix.py, security/test_controls_reports.py | Backend-only (tested) |
| SEC-38 | `POST /security/incidents` | — | authz/matrix.py, security/test_controls_reports.py | Backend-only (tested) |
| SEC-39 | `PATCH /security/incidents/{incident_id}` | — | security/test_controls_reports.py | Backend-only (tested) |
| SEC-16 | `POST /security/pii-reveals` | EvidenceTabs | authz/matrix.py | Implemented+tested |
| SEC-30 | `GET /security/reports` | Reports | authz/matrix.py, security/test_controls_reports.py (+1) | Implemented+tested |
| SEC-47 | `GET /security/reports/exports/{export_job_id}` | — | security/test_controls_reports.py | Backend-only (tested) |
| SEC-31 | `GET /security/reports/{report_key}` | Reports | security/test_controls_reports.py, security/test_scn_unblock.py | Implemented+tested |
| SEC-32 | `POST /security/reports/{report_key}/exports` | Reports | analytics/test_exports.py, security/test_controls_reports.py | Implemented+tested |
| SEC-19 | `GET /security/restrictions` | Restrictions | authz/matrix.py, security/test_controls_reports.py | Implemented+tested |
| SEC-20 | `POST /security/restrictions` | CaseDetail, Restrictions | authz/matrix.py, security/test_controls_reports.py | Implemented+tested |
| SEC-44 | `POST /security/restrictions/bulk-lift-requests` | Restrictions | security/test_controls_reports.py | Implemented+tested |
| SEC-45 | `GET /security/restrictions/bulk-lift-requests/{bulk_lift_id}` | — | security/test_controls_reports.py | Backend-only (tested) |
| SEC-21 | `POST /security/restrictions/{restriction_id}/lift` | Restrictions | security/test_controls_reports.py | Implemented+tested |
| UNB-10 | `GET /security/review/unblock-requests` | EvidenceTabs, UnblockReviewQueue | security/test_scn_unblock.py | Implemented+tested |
| UNB-11 | `GET /security/review/unblock-requests/{request_id}` | EvidenceTabs | security/test_scn_unblock.py | Implemented+tested |
| UNB-16 | `GET /security/review/unblock-requests/{request_id}/attachments/{attachment_id}` | — | **none found** | Stub: always 404 (api_review.py:942) |
| UNB-12 | `POST /security/review/unblock-requests/{request_id}/claim` | UnblockReviewQueue | security/test_scn_unblock.py | Implemented+tested |
| UNB-14 | `POST /security/review/unblock-requests/{request_id}/escalate` | EvidenceTabs | authz/matrix.py | Implemented+tested |
| UNB-13 | `POST /security/review/unblock-requests/{request_id}/request-info` | EvidenceTabs | **none found** | Implemented-untested |
| UNB-15 | `POST /security/review/unblock-requests/{request_id}/send-back` | — | security/test_scn_unblock.py | Backend-only (tested) |
| SEC-23 | `GET /security/rule-versions` | RuleVersions | security/test_controls_reports.py | Implemented+tested |
| SEC-24 | `POST /security/rule-versions` | RuleVersions | security/test_controls_reports.py | Implemented+tested |
| SEC-28 | `POST /security/rule-versions/{version_id}/activation-requests` | RuleVersions | security/test_controls_reports.py | Implemented+tested |
| SEC-29 | `POST /security/rule-versions/{version_id}/rollback-requests` | RuleVersions | **none found** | Implemented-untested |
| SEC-27 | `GET /security/rule-versions/{version_id}/shadow-report` | RuleVersions | **none found** | Implemented-untested |
| SEC-25 | `POST /security/rule-versions/{version_id}/simulate` | RuleVersions | security/test_controls_reports.py | Implemented+tested |
| SEC-26 | `POST /security/rule-versions/{version_id}/start-shadow` | RuleVersions | security/test_controls_reports.py | Implemented+tested |
| SEC-22 | `GET /security/rules` | RuleVersions | security/test_controls_reports.py | Implemented+tested |
| SEC-33 | `GET /security/trusted-networks` | — | authz/matrix.py, security/test_controls_reports.py | Backend-only (tested) |
| SEC-34 | `POST /security/trusted-networks/{network_id}/decision` | — | security/test_controls_reports.py | Backend-only (tested) |
| UNB-05 | `GET /security/unblock-requests` | — | security/test_scn_unblock.py, security/test_seed_and_guard.py ; e2e: a11y.integration.spec.ts, security-console.integration.spec.ts | Backend-only (tested) |
| UNB-01 | `POST /security/unblock-requests` | UnblockRequestForm | security/test_scn_unblock.py, security/test_seed_and_guard.py ; e2e: a11y.integration.spec.ts, security-console.integration.spec.ts | Implemented+tested |
| UNB-20 | `GET /security/unblock-requests/by-reference/{reference}` | UnblockStatus | security/test_scn_unblock.py | Implemented+tested |
| UNB-19 | `GET /security/unblock-requests/form` | UnblockStatus | security/test_scn_unblock.py | Implemented+tested |
| UNB-06 | `GET /security/unblock-requests/{request_id}` | UnblockStatus | security/test_scn_unblock.py | Implemented+tested |
| UNB-02 | `PATCH /security/unblock-requests/{request_id}` | — | security/test_scn_unblock.py | Backend-only (tested) |
| UNB-09 | `POST /security/unblock-requests/{request_id}/appeal` | UnblockStatus | security/test_scn_unblock.py | Implemented+tested |
| UNB-03 | `POST /security/unblock-requests/{request_id}/attachments` | — | **none found** | Stub: always 503 service_unavailable (api_student.py:317) |
| UNB-07 | `POST /security/unblock-requests/{request_id}/responses` | UnblockStatus | **none found** | Implemented-untested |
| UNB-04 | `POST /security/unblock-requests/{request_id}/submit` | — (UI creates with `submit:true` via UNB-02) | **none found** | Backend-only, untested |
| UNB-08 | `POST /security/unblock-requests/{request_id}/withdraw` | UnblockStatus | security/test_scn_unblock.py | Implemented+tested |
| SEC-14 | `GET /security/users/{user_id}/concurrency` | EvidenceTabs | **none found** | Implemented-untested |
| SEC-15 | `GET /security/users/{user_id}/device-graph` | EvidenceTabs | **none found** | Implemented-untested |
| SEC-13 | `GET /security/users/{user_id}/timeline` | EvidenceTabs | security/test_scn_unblock.py | Implemented+tested |
| — | `GET /studio/coding/problems` | Coding | coding/test_authoring_gaps.py, coding/test_stage10_endpoints.py (+1) | Implemented+tested |
| COD-13 | `POST /studio/coding/problems` | Coding | coding/test_authoring_gaps.py, coding/test_stage10_endpoints.py (+1) | Implemented+tested |
| COD-23 | `GET /studio/coding/problems/{problem_id}` | Coding | coding/test_authoring_gaps.py, coding/test_stage10_endpoints.py (+1) | Implemented+tested |
| COD-14 | `PATCH /studio/coding/problems/{problem_id}` | Coding | coding/test_authoring_gaps.py, coding/test_stage10_endpoints.py (+1) | Implemented+tested |
| COD-19 | `POST /studio/coding/problems/{problem_id}/publish` | Coding | catalog/test_catalog.py, coding/test_studio.py | Implemented+tested |
| — | `GET /studio/coding/problems/{problem_id}/reference-solutions` | Coding | **none found** | Implemented-untested |
| — | `PUT /studio/coding/problems/{problem_id}/reference-solutions/{language_key}` | — | **none found** | Backend-only, untested |
| COD-16 | `GET /studio/coding/problems/{problem_id}/test-cases` | Coding | coding/test_authoring_gaps.py, coding/test_studio.py | Implemented+tested |
| COD-15 | `POST /studio/coding/problems/{problem_id}/test-cases` | Coding | coding/test_authoring_gaps.py, coding/test_studio.py | Implemented+tested |
| COD-18 | `POST /studio/coding/problems/{problem_id}/validate` | Coding | coding/test_authoring_gaps.py | Implemented+tested |
| — | `GET /studio/coding/problems/{problem_id}/validation` | Coding | **none found** | Implemented-untested |
| — | `GET /studio/coding/test-cases/content-downloads/{token}` | Coding | **none found** | Implemented-untested |
| COD-17 | `GET /studio/coding/test-cases/{test_case_id}/content` | Coding | coding/test_authoring_gaps.py | Implemented+tested |
| PLC-16 | `GET /studio/companies` | — | placement/test_placement.py | Backend-only (tested) |
| PLC-17 | `POST /studio/companies` | — | placement/test_placement.py | Backend-only (tested) |
| PLC-18 | `PUT /studio/company-paths/{company_path_id}` | — | placement/test_placement.py | Backend-only (tested) |
| CAT-08 | `GET /studio/courses` | Courses, Questions, StudioDashboard | catalog/test_catalog.py, learning/test_learning.py (+1) | Implemented+tested |
| CAT-09 | `POST /studio/courses` | Courses | catalog/test_catalog.py, learning/test_learning.py (+1) | Implemented+tested |
| CAT-10 | `GET /studio/courses/{course_id}` | Courses | catalog/test_catalog.py, learning/test_learning.py (+1) | Implemented+tested |
| CAT-18 | `POST /studio/courses/{course_id}/archive` | Courses | catalog/test_catalog.py | Implemented+tested |
| CAT-11 | `PATCH /studio/courses/{course_id}/draft` | Courses | catalog/test_catalog.py, learning/test_learning.py (+1) | Implemented+tested |
| CAT-13 | `POST /studio/courses/{course_id}/draft/lessons` | Courses | catalog/test_catalog.py, learning/test_learning.py (+1) | Implemented+tested |
| CAT-12 | `PUT /studio/courses/{course_id}/draft/outline` | — | catalog/test_catalog.py | Backend-only (tested) |
| CAT-17 | `POST /studio/courses/{course_id}/publish` | Courses | catalog/test_catalog.py, learning/test_learning.py | Implemented+tested |
| CAT-16 | `POST /studio/courses/{course_id}/submit-review` | Courses | catalog/test_catalog.py, learning/test_learning.py | Implemented+tested |
| CAT-19 | `GET /studio/courses/{course_id}/versions` | Courses | catalog/test_catalog.py | Implemented+tested |
| CAT-14 | `PATCH /studio/lessons/{lesson_id}` | — | catalog/test_catalog.py | Backend-only (tested) |
| CAT-20 | `GET /studio/lessons/{lesson_id}/preview` | — | catalog/test_catalog.py | Backend-only (tested) |
| CAT-15 | `PUT /studio/lessons/{lesson_id}/topics` | — | **none found** | Backend-only, untested |
| PLC-34 | `GET /studio/question-reports` | QuestionReports, StudioDashboard | placement/test_question_reports.py | Implemented+tested |
| PLC-35 | `POST /studio/question-reports/{report_id}/resolve` | QuestionReports | placement/test_question_reports.py | Implemented+tested |
| PLC-04 | `GET /studio/questions` | Questions, StudioDashboard | placement/test_placement.py | Implemented+tested |
| PLC-05 | `POST /studio/questions` | Questions | placement/test_placement.py | Implemented+tested |
| PLC-06 | `GET /studio/questions/{question_id}` | Questions | placement/test_placement.py | Implemented+tested |
| PLC-10 | `POST /studio/questions/{question_id}/publish` | Questions | assessments/test_attempts.py, placement/test_placement.py | Implemented+tested |
| PLC-11 | `POST /studio/questions/{question_id}/retire` | Questions | placement/test_placement.py | Implemented+tested |
| PLC-09 | `POST /studio/questions/{question_id}/review` | Questions | assessments/test_attempts.py, placement/test_placement.py | Implemented+tested |
| PLC-08 | `POST /studio/questions/{question_id}/submit-review` | Questions | placement/test_placement.py | Implemented+tested |
| PLC-07 | `POST /studio/questions/{question_id}/versions` | Questions | placement/test_placement.py | Implemented+tested |
| CAT-21 | `POST /studio/resources` | — | catalog/test_catalog.py, media/test_media.py | Backend-only (tested) |
| CAT-22 | `PATCH /studio/resources/{resource_id}` | — | catalog/test_catalog.py | Backend-only (tested) |
| ASM-03 | `GET /studio/tests` | Integrity, Tests, TestsList | assessments/test_attempts.py, seeds/test_dev_fixtures.py | Implemented+tested |
| ASM-04 | `POST /studio/tests` | Tests | assessments/test_attempts.py, seeds/test_dev_fixtures.py | Implemented+tested |
| ASM-05 | `GET /studio/tests/{test_id}` | Tests | assessments/test_attempts.py | Implemented+tested |
| ASM-06 | `PATCH /studio/tests/{test_id}` | Tests | assessments/test_attempts.py | Implemented+tested |
| ASM-09 | `POST /studio/tests/{test_id}/publish` | Tests | assessments/test_attempts.py, catalog/test_catalog.py (+3) | Implemented+tested |
| ASM-07 | `PUT /studio/tests/{test_id}/sections` | Tests | assessments/test_attempts.py | Implemented+tested |
| ASM-08 | `POST /studio/tests/{test_id}/validate` | Tests | assessments/test_attempts.py, coding/test_authoring_gaps.py | Implemented+tested |
| PLC-02 | `POST /studio/topics` | — | placement/test_placement.py | Backend-only (tested) |
| PLC-03 | `PATCH /studio/topics/{topic_id}` | — | placement/test_placement.py | Backend-only (tested) |
| SUP-15 | `GET /support/macros` | SupportDesk | authz/matrix.py, support/test_support.py | Implemented+tested |
| SUP-07 | `GET /support/queue` | SupportDesk | authz/matrix.py, support/test_support.py | Implemented+tested |
| SUP-01 | `POST /support/tickets` | StudentSupport | authz/matrix.py, support/test_support.py | Implemented+tested |
| SUP-03 | `GET /support/tickets/{ticket_id}` | StudentSupport, SupportDesk | authz/matrix.py, support/test_support.py | Implemented+tested |
| SUP-08 | `PATCH /support/tickets/{ticket_id}` | SupportDesk | authz/matrix.py, support/test_support.py | Implemented+tested |
| SUP-06 | `POST /support/tickets/{ticket_id}/csat` | StudentSupport | support/test_support.py | Implemented+tested |
| SUP-09 | `POST /support/tickets/{ticket_id}/escalate` | SupportDesk | authz/matrix.py, support/test_support.py | Implemented+tested |
| SUP-10 | `POST /support/tickets/{ticket_id}/merge` | SupportDesk | authz/matrix.py, support/test_support.py | Implemented+tested |
| SUP-04 | `POST /support/tickets/{ticket_id}/messages` | StudentSupport, SupportDesk | support/test_support.py | Implemented+tested |
| SUP-05 | `POST /support/tickets/{ticket_id}/reopen` | StudentSupport | support/test_support.py | Implemented+tested |
| UNB-17 | `GET /support/unblock-requests` | SupportDesk | authz/matrix.py | Implemented+tested |
| UNB-18 | `POST /support/unblock-requests/{request_id}/forward` | — | **none found** | Backend-only, untested |
| SUP-11 | `GET /support/users/{user_id}` | SupportDesk | support/test_support.py | Implemented+tested |
| SUP-14 | `POST /support/users/{user_id}/notes` | SupportDesk | security/test_scn_unblock.py, support/test_support.py | Implemented+tested |
| SUP-13 | `POST /support/users/{user_id}/password-reset-email` | SupportDesk | support/test_support.py | Implemented+tested |
| SUP-12 | `POST /support/users/{user_id}/resend-verification` | SupportDesk | support/test_support.py | Implemented+tested |
| ASM-12 | `PATCH /test-assignments/{assignment_id}` | — | **none found** | Backend-only, untested |
| ASM-02 | `GET /tests/{test_id}` | api | analytics/test_pipeline.py, assessments/test_attempts.py (+1) ; e2e: a11y.integration.spec.ts, multi-tab.integration.spec.ts | Implemented+tested |
| ASM-11 | `GET /tests/{test_id}/assignments` | AssignTest, TestOps | assessments/test_attempts.py, entitlements/test_access_and_seats.py (+2) | Implemented+tested |
| ASM-10 | `POST /tests/{test_id}/assignments` | AssignTest | assessments/test_attempts.py, entitlements/test_access_and_seats.py (+2) | Implemented+tested |
| ASM-15 | `GET /tests/{test_id}/attempts` | TestOps | assessments/test_attempts.py ; e2e: multi-tab.integration.spec.ts, student-learning.integration.spec.ts | Implemented+tested |
| ASM-14 | `GET /tests/{test_id}/overrides` | TestOps | assessments/test_attempts.py | Implemented+tested |
| ASM-13 | `POST /tests/{test_id}/overrides` | TestOps | assessments/test_attempts.py | Implemented+tested |
| ASM-22 | `GET /tests/{test_id}/report` | TestOps | assessments/test_integrity_and_report.py | Implemented+tested |
| ASM-16 | `POST /tests/{test_id}/results/release` | TestOps | assessments/test_attempts.py | Implemented+tested |
| SES-11 | `GET /users/{user_id}/devices` | SupportDesk | identity/test_seeds_and_audit.py, sessions/test_sessions_and_devices.py | Implemented+tested |
| SES-12 | `POST /users/{user_id}/devices/{user_device_id}/reset` | SupportDesk | security/test_security_regression.py, sessions/test_sessions_and_devices.py | Implemented+tested |
| ENT-04 | `GET /users/{user_id}/entitlements` | — | entitlements/test_access_and_seats.py | Backend-only (tested) |
| SES-09 | `GET /users/{user_id}/sessions` | SupportDesk | admin/test_accounts.py, sessions/test_sessions_and_devices.py | Implemented+tested |
| SES-10 | `POST /users/{user_id}/sessions/revoke` | CaseDetail, SupportDesk, Users | sessions/test_sessions_and_devices.py | Implemented+tested |
| — | `POST /webhooks/{provider}` | — | commerce/factory.py, commerce/test_checkout_webhooks.py ; e2e: smoke.spec.ts | Implemented+tested (no UI needed) |
| AUTH-07 | `POST /auth/passkey/login-options` | — | — | Not built (spec: Planned) |
| AUTH-08 | `POST /auth/passkey/login` | — | — | Not built (spec: Planned) |
| AUTH-09 | `POST /auth/otp-login/send` | — | — | Not built (spec: Planned) |
| AUTH-10 | `POST /auth/otp-login/verify` | — | — | Not built (spec: Planned) |
| AUTH-23 | `GET /auth/oidc/google/start` | — | — | Not built (spec: Planned) |
| AUTH-24 | `GET /auth/oidc/google/callback` | — | — | Not built (spec: Planned) |
| ME-03 | `POST /me/contact-changes` | — | — | Not built (spec: Planned) |
| ME-04 | `POST /me/contact-changes/{change_id}/verify` | — | — | Not built (spec: Planned) |
| ME-10 | `POST /me/mfa/passkeys/options` | — | — | Not built (spec: Planned) |
| ME-11 | `POST /me/mfa/passkeys` | — | — | Not built (spec: Planned) |
| SES-13 | `POST /orgs/{org_id}/lab-devices/enrolment-links` | — | — | Not built (spec: Planned) |
| SES-14 | `POST /lab-devices/enrol` | — | — | Not built (spec: Planned) |
| SES-15 | `GET /orgs/{org_id}/lab-devices` | — | — | Not built (spec: Planned) |
| SES-16 | `DELETE /orgs/{org_id}/lab-devices/{device_id}` | — | — | Not built (spec: Planned) |
| ORG-30 | `POST /orgs/{org_id}/shortlists` | — | — | Not built (spec: Planned) |
| CAT-03 | `GET /catalog/companies` | — | — | Not built (spec: Planned) |
| CAT-04 | `GET /catalog/companies/{slug}` | — | — | Not built (spec: Planned) |
| CAT-05 | `GET /catalog/subjects/{subject_slug}/topics/{topic_slug}` | — | — | Not built (spec: Planned) |
| LRN-25 | `GET /me/bookmarks` | — | — | Not built (spec: Planned) |
| LRN-26 | `POST /me/bookmarks` | — | — | Not built (spec: Planned) |
| LRN-27 | `DELETE /me/bookmarks/{bookmark_id}` | — | — | Not built (spec: Planned) |
| PLC-12 | `POST /studio/question-imports` | — | — | Not built (spec: Planned) |
| PLC-13 | `GET /studio/question-imports/{job_id}` | — | — | Not built (spec: Planned) |
| PLC-14 | `POST /studio/question-imports/{job_id}/commit` | — | — | Not built (spec: Planned) |
| PLC-15 | `GET /studio/questions/{question_id}/stats` | — | — | Not built (spec: Planned) |
| PLC-28 | `GET /me/goals` | — | — | Not built (spec: Planned) |
| PLC-29 | `PUT /me/goals` | — | — | Not built (spec: Planned) |
| PLC-30 | `GET /me/learning-path` | — | — | Not built (spec: Planned) |
| PLC-31 | `PATCH /me/learning-path` | — | — | Not built (spec: Planned) |
| PLC-49 | `POST /me/resumes/{resume_id}/export` | — | — | Not built (spec: Planned) |
| ASM-17 | `POST /attempts/{attempt_id}/regrade` | — | — | Not built (spec: Planned) |
| ASM-23 | `GET /tests/{test_id}/leaderboard` | — | — | Not built (spec: Planned) |
| COD-09 | `GET /coding/submissions/{submission_id}/stream` | — | — | Not built (spec: Planned) |
| COD-11 | `GET /coding/submissions/{submission_id}/diff/{other_submission_id}` | — | — | Not built (spec: Planned) |
| COD-12 | `GET /coding/problems/{problem_id}/editorial` | — | — | Not built (spec: Planned) |
| COD-20 | `GET /coding/submissions/{submission_id}/source` | — | — | Not built (spec: Planned) |
| COD-21 | `POST /tests/{test_id}/similarity-runs` | — | — | Not built (spec: Planned) |
| COD-22 | `GET /similarity-runs/{run_id}` | — | — | Not built (spec: Planned) |
| WH-03 | `POST /webhooks/ses` | — | — | Not built (spec: Planned) |
| WH-04 | `POST /webhooks/sms-dlr` | — | — | Not built (spec: Planned) |
| ANL-11 | `GET /analytics/reports/commerce` | — | — | Not built (spec: Planned) |
| NTF-04 | `GET /me/notification-preferences` | — | — | Not built (spec: Planned) |
| NTF-05 | `PUT /me/notification-preferences` | — | — | Not built (spec: Planned) |
| NTF-07 | `GET /admin/notification-templates` | — | — | Not built (spec: Planned) |
| NTF-08 | `POST /admin/notification-templates/{template_key}/versions` | — | — | Not built (spec: Planned) |
| NTF-09 | `POST /admin/notification-templates/{template_key}/versions/{version}/activate` | — | — | Not built (spec: Planned) |
| NTF-10 | `GET /me/events` | — | — | Not built (spec: Planned) |
| SUP-16 | `POST /public/contact` | — | — | Not built (spec: Planned) |
| SUP-17 | `POST /public/college-enquiries` | — | — | Not built (spec: Planned) |
| PRV-06 | `POST /privacy/representative-requests` | — | — | Not built (spec: Planned) |
| PRV-14 | `PATCH /admin/retention-policies/{policy_id}` | — | — | Not built (spec: Planned) |
| PRV-15 | `GET /admin/erasure-ledger/status` | — | — | Not built (spec: Planned) |
| AUD-04 | `GET /orgs/{org_id}/audit/events` | — | — | Not built (spec: Planned) |
| AUD-05 | `POST /audit/exports` | — | — | Not built (spec: Planned) |
| ADM-06 | `POST /admin/users/{user_id}/legal-name` | — | — | Not built (spec: Planned) |
| SYS-03 | `GET /public/status` | — | — | Not built (spec: Planned) |
| SYS-04 | `GET /public/legal/{document_key}` | — | — | Not built (spec: Planned) |
| SYS-05 | `GET /public/policy-numbers` | — | — | Not built (spec: Planned) |

## 6. Pages (apps/web/src/app, 163 routes) vs sitemap

"Screen" = the sitemap/PRD screen ID (`§13` = implemented addition listed in sitemap §13). "Tests" = `e2e` if a Playwright spec `goto`s the route; `unit(feature)` = the feature folder has a `*.test.tsx` (component-level, not route-level). Result: **Built** = renders a feature component; **Placeholder** = `<NotImplemented>`.

| Screen | Route | Feature / component | Tests | Result |
|---|---|---|---|---|
| PUB-001 | `/` | catalog/CourseGrid | e2e + unit(catalog) | Built |

> Historical audit. College/multi-organization items are superseded by the single-company conversion, see `docs/single-company/REMOVAL-PLAN.md`.
| PUB-021 | `/account/restricted` | unblock/RestrictedStatus | e2e + unit(unblock) | Built |
| PUB-010 | `/colleges` | — |  | **Placeholder (NotImplemented)** |
| PUB-006 | `/companies` | — |  | **Placeholder (NotImplemented)** |
| PUB-007 | `/companies/[slug]` | — |  | **Placeholder (NotImplemented)** |
| PUB-002 | `/courses` | catalog/CatalogFilters | e2e + unit(catalog) | Built |
| PUB-003 | `/courses/[slug]` | catalog/ServerErrorState |  + unit(catalog) | Built |
| PUB-013 | `/forgot-password` | auth/AuthCard |  + unit(auth) | Built |
| PUB-009 | `/free-resources` | — |  | **Placeholder (NotImplemented)** |
| PUB-015 | `/guardian-consent/[token]` | auth/AuthCard |  + unit(auth) | Built |
| PUB-019 | `/help` | — |  | **Placeholder (NotImplemented)** |
| PUB-019 | `/help/[article]` | — |  | **Placeholder (NotImplemented)** |
| PUB-016 | `/invite/[token]` | — |  | **Placeholder (NotImplemented)** |
| PUB-018 | `/legal/device-policy` | — |  | **Placeholder (NotImplemented)** |
| PUB-018 | `/legal/privacy` | — |  | **Placeholder (NotImplemented)** |
| PUB-018 | `/legal/refund-policy` | — |  | **Placeholder (NotImplemented)** |
| PUB-018 | `/legal/terms` | — |  | **Placeholder (NotImplemented)** |
| PUB-012 | `/login` | auth/AuthCard | e2e + unit(auth) | Built |
| §13 | `/login/mfa` | auth/AuthCard |  + unit(auth) | Built |
| §13 | `/login/session-choice` | auth/AuthCard | e2e + unit(auth) | Built |
| §13 | `/login/verify-device` | auth/AuthCard |  + unit(auth) | Built |
| PUB-004 | `/placement` | — |  | **Placeholder (NotImplemented)** |
| §13 | `/placement/[subject]/[topic]` | — |  | **Placeholder (NotImplemented)** |
| PUB-008 | `/pricing` | catalog/ServerErrorState | e2e + unit(catalog) | Built |
| PUB-013 | `/reset-password/[token]` | auth/AuthCard |  + unit(auth) | Built |
| PUB-011 | `/signup` | auth/AuthCard | e2e + unit(auth) | Built |
| PUB-020 | `/status` | — |  | **Placeholder (NotImplemented)** |
| §13 | `/unblock-request` | unblock/UnblockRequestForm | e2e + unit(unblock) | Built |
| PUB-017 | `/verify/[certificate_id]` | catalog/ServerErrorState |  + unit(catalog) | Built |
| PUB-014 | `/verify/email/[token]` | auth/AuthCard |  + unit(auth) | Built |
| PUB-014 | `/verify/mobile` | auth/AuthCard |  + unit(auth) | Built |
| ADM-001 | `/admin` | admin/AdminDashboard |  + unit(admin) | Built |
| ADM-010 | `/admin/approvals` | admin/ApprovalsQueue |  + unit(admin) | Built |
| ADM-008 | `/admin/audit` | admin/AuditLog |  + unit(admin) | Built |
| ADM-012 | `/admin/break-glass` | admin/BreakGlass |  + unit(admin) | Built |
| ADM-007 | `/admin/feature-flags` | admin/FeatureFlags |  + unit(admin) | Built |
| ADM-011 | `/admin/notifications` | — |  | **Placeholder (NotImplemented)** |
| ADM-002 | `/admin/organizations` | admin/Organizations |  + unit(admin) | Built |
| ADM-003 | `/admin/organizations/[org_id]` | admin/OrganizationDetail |  + unit(admin) | Built |
| ADM-006 | `/admin/policies` | admin/PolicySettings |  + unit(admin) | Built |
| ADM-009 | `/admin/privacy-requests` | admin/PrivacyRequests |  + unit(admin) | Built |
| ADM-005 | `/admin/roles` | admin/RoleGrants |  + unit(admin) | Built |
| ADM-004 | `/admin/users` | admin/UserSearch |  + unit(admin) | Built |
| §13 | `/admin/users/[user_id]` | admin/UserDetail |  + unit(admin) | Built |
| STU-001 | `/app` | dashboard/StudentDashboard | e2e + unit(dashboard) | Built |
| STU-019 | `/app/access` | commerce/AccessList |  + unit(commerce) | Built |
| STU-026 | `/app/account-status` | — |  | **Placeholder (NotImplemented)** |
| STU-011 | `/app/analytics` | — |  | **Placeholder (NotImplemented)** |
| STU-007 | `/app/assignments` | learning/AssignmentsList |  + unit(learning) | Built |
| STU-008 | `/app/assignments/[id]` | learning/AssignmentDetail |  + unit(learning) | Built |
| TST-002 | `/app/attempts/[attempt_id]` | assessment/AttemptRunner |  + unit(assessment) | Built |
| TST-004 | `/app/attempts/[attempt_id]/resume` | assessment/AttemptRunner |  + unit(assessment) | Built |
| TST-005 | `/app/attempts/[attempt_id]/submitted` | assessment/SubmittedView |  + unit(assessment) | Built |
| STU-018 | `/app/billing` | commerce/Billing | e2e + unit(commerce) | Built |
| STU-028 | `/app/bookmarks` | — |  | **Placeholder (NotImplemented)** |
| STU-012 | `/app/certificates` | learning/Certificates |  + unit(learning) | Built |
| STU-016 | `/app/checkout/[order_id]` | commerce/OrderStatus |  + unit(commerce) | Built |
| §13 | `/app/checkout/new` | commerce/Checkout |  + unit(commerce) | Built |
| COD-001 | `/app/coding` | coding/ProblemList | e2e + unit(coding) | Built |
| COD-002 | `/app/coding/[slug]` | coding/CodingWorkspace |  + unit(coding) | Built |
| COD-003 | `/app/coding/[slug]/submissions` | coding/SubmissionHistory |  + unit(coding) | Built |
| STU-027 | `/app/college` | — |  | **Placeholder (NotImplemented)** |
| §13 | `/app/companies` | practice/CompaniesIndex |  + unit(practice) | Built |
| PRC-005 | `/app/companies/[slug]` | practice/CompanyPathView |  + unit(practice) | Built |
| §13 | `/app/courses` | — |  | Built |
| STU-005 | `/app/courses/[slug]` | learning/CourseOverview |  + unit(learning) | Built |
| STU-003 | `/app/diagnostic` | — |  | **Placeholder (NotImplemented)** |
| STU-015 | `/app/interview-prep` | — |  | **Placeholder (NotImplemented)** |
| PLY-001 | `/app/learn/[course_slug]/[lesson_id]` | learning/LessonView |  + unit(learning) | Built |
| STU-004 | `/app/learning` | learning/MyCourses | e2e + unit(learning) | Built |
| STU-013 | `/app/mentoring` | mentor/StudentMentoring |  + unit(mentor) | Built |
| STU-024 | `/app/notifications` | — |  | **Placeholder (NotImplemented)** |
| STU-002 | `/app/onboarding` | — |  | **Placeholder (NotImplemented)** |
| STU-017 | `/app/orders/[order_id]` | commerce/OrderStatus |  + unit(commerce) | Built |
| STU-006 | `/app/path` | — |  | **Placeholder (NotImplemented)** |
| PRC-001 | `/app/practice` | practice/PracticeHub | e2e + unit(practice) | Built |
| PRC-002 | `/app/practice/[subject]` | practice/SubjectTopics |  + unit(practice) | Built |
| PRC-004 | `/app/practice/review` | practice/PracticeReview |  + unit(practice) | Built |
| PRC-003 | `/app/practice/sessions/[session_id]` | practice/PracticeSession |  + unit(practice) | Built |
| §13 | `/app/progress` | progress/ProgressDashboard |  + unit(progress) | Built |
| STU-014 | `/app/resume` | mentor/StudentResume |  + unit(mentor) | Built |
| STU-022 | `/app/settings/devices` | account/DevicesAndSessions | e2e + unit(account) | Built |
| STU-023 | `/app/settings/privacy` | account/PrivacySettings |  + unit(account) | Built |
| STU-020 | `/app/settings/profile` | account/ProfileSettings |  + unit(account) | Built |
| STU-021 | `/app/settings/security` | account/SecuritySettings |  + unit(account) | Built |
| §13 | `/app/settings/security/not-me/[event_ref]` | account/DisownEvent |  + unit(account) | Built |
| STU-025 | `/app/support` | support/MyTickets |  + unit(support) | Built |
| STU-025 | `/app/support/[ticket_id]` | support/MyTicket |  + unit(support) | Built |
| STU-025 | `/app/support/new` | support/NewTicketForm |  + unit(support) | Built |
| STU-009 | `/app/tests` | assessment/TestsList |  + unit(assessment) | Built |
| TST-001 | `/app/tests/[test_id]` | assessment/TestInstructions |  + unit(assessment) | Built |
| STU-010 | `/app/tests/[test_id]/results/[attempt_id]` | assessment/ResultsView |  + unit(assessment) | Built |
| COL-001 | `/college` | college/CollegeScreen | e2e + unit(college) | Built |
| COL-004 | `/college/batches` | college/CollegeScreen |  + unit(college) | Built |
| COL-005 | `/college/batches/[batch_id]` | college/CollegeBatch |  + unit(college) | Built |
| COL-011 | `/college/contract` | college/CollegeScreen |  + unit(college) | Built |
| §13 | `/college/networks` | college/CollegeScreen |  + unit(college) | Built |
| COL-008 | `/college/reports` | college/CollegeScreen |  + unit(college) | Built |
| COL-006 | `/college/seats` | college/CollegeScreen |  + unit(college) | Built |
| COL-010 | `/college/shortlists` | — |  | **Placeholder (NotImplemented)** |
| COL-012 | `/college/staff` | — |  | **Placeholder (NotImplemented)** |
| COL-002 | `/college/students` | college/CollegeScreen |  + unit(college) | Built |
| COL-009 | `/college/students/[user_id]` | — |  | **Placeholder (NotImplemented)** |
| COL-003 | `/college/students/import` | college/CollegeScreen | e2e + unit(college) | Built |
| COL-007 | `/college/tests` | college/CollegeScreen |  + unit(college) | Built |
| SUP-001 | `/desk` | support/TicketQueue |  + unit(support) | Built |
| SUP-002 | `/desk/tickets/[ticket_id]` | support/TicketDetail |  + unit(support) | Built |
| SUP-005 | `/desk/unblock-requests` | support/SupportUnblockTriage |  + unit(support) | Built |
| SUP-003 | `/desk/users/[user_id]` | support/UserLookup |  + unit(support) | Built |
| FIN-001 | `/finance` | finance/FinanceHome |  + unit(finance) | Built |
| FIN-008 | `/finance/contracts` | finance/Contracts |  + unit(finance) | Built |
| FIN-003 | `/finance/coupons` | — |  | **Placeholder (NotImplemented)** |
| FIN-007 | `/finance/invoices` | finance/Invoices |  + unit(finance) | Built |
| FIN-004 | `/finance/orders` | finance/Orders |  + unit(finance) | Built |
| FIN-002 | `/finance/products` | — |  | **Placeholder (NotImplemented)** |
| FIN-009 | `/finance/reconciliation` | finance/Reconciliation |  + unit(finance) | Built |
| FIN-005 | `/finance/refunds` | finance/Refunds |  + unit(finance) | Built |
| FIN-006 | `/finance/subscriptions` | — |  | **Placeholder (NotImplemented)** |
| MEN-001 | `/mentor` | mentor/MentorSessions |  + unit(mentor) | Built |
| MEN-005 | `/mentor/resume-reviews` | mentor/MentorResumeReviews |  + unit(mentor) | Built |
| MEN-003 | `/mentor/sessions/[session_id]` | mentor/MentorSessionDetail |  + unit(mentor) | Built |
| MEN-002 | `/mentor/slots` | mentor/MentorSlots |  + unit(mentor) | Built |
| §13 | `/mentor/students` | mentor/MentorStudents |  + unit(mentor) | Built |
| MEN-004 | `/mentor/students/[user_id]` | mentor/MentorStudent |  + unit(mentor) | Built |
| SEC-001 | `/security` | security-admin/SecurityDashboard |  + unit(security-admin) | Built |
| §13 | `/security/approvals` | admin/ApprovalsQueue |  + unit(admin) | Built |
| SEC-002 | `/security/cases` | security-admin/CaseQueue |  + unit(security-admin) | Built |
| SEC-003 | `/security/cases/[case_id]` | security-admin/CaseDetail |  + unit(security-admin) | Built |
| §13 | `/security/policies` | admin/PolicySettings |  + unit(admin) | Built |
| §13 | `/security/reports` | security-admin/ReportsIndex |  + unit(security-admin) | Built |
| §13 | `/security/reports/[report_key]` | security-admin/ReportView |  + unit(security-admin) | Built |
| SEC-005 | `/security/restrictions` | security-admin/Restrictions |  + unit(security-admin) | Built |
| SEC-006 | `/security/rules` | security-admin/RuleVersions |  + unit(security-admin) | Built |
| SEC-004 | `/security/unblock-requests` | security-admin/UnblockReviewQueue | e2e + unit(security-admin) | Built |
| SEC-007 | `/security/users/[user_id]/timeline` | security-admin/UserTimelinePage |  + unit(security-admin) | Built |
| CMS-001 | `/studio` | studio/StudioDashboard |  + unit(studio) | Built |
| §13 | `/studio/coding` | studio/CodingProblemList |  + unit(studio) | Built |
| CMS-010 | `/studio/coding/[problem_id]` | studio/CodingProblemEditor |  + unit(studio) | Built |
| CMS-009 | `/studio/companies` | — |  | **Placeholder (NotImplemented)** |
| CMS-002 | `/studio/courses` | studio/CourseList |  + unit(studio) | Built |
| CMS-003 | `/studio/courses/[course_id]` | studio/CourseEditor |  + unit(studio) | Built |
| CMS-012 | `/studio/media` | — |  | **Placeholder (NotImplemented)** |
| CMS-004 | `/studio/questions` | studio/QuestionBank |  + unit(studio) | Built |
| CMS-005 | `/studio/questions/[question_id]` | studio/QuestionEditor |  + unit(studio) | Built |
| CMS-006 | `/studio/questions/import` | — |  | **Placeholder (NotImplemented)** |
| CMS-013 | `/studio/reports/errors` | studio/QuestionReportQueue |  + unit(studio) | Built |
| CMS-007 | `/studio/review` | studio/ReviewQueue |  + unit(studio) | Built |
| CMS-008 | `/studio/taxonomy` | — |  | **Placeholder (NotImplemented)** |
| CMS-011 | `/studio/tests` | studio/TestBlueprints |  + unit(studio) | Built |
| §13 | `/studio/tests/[test_id]` | studio/TestBuilder |  + unit(studio) | Built |
| TRN-001 | `/trainer` | trainer/TrainerDashboard |  + unit(trainer) | Built |
| TRN-012 | `/trainer/assignments` | trainer/TrainerAssignments |  + unit(trainer) | Built |
| TRN-002 | `/trainer/batches/[batch_id]` | college/BatchDetail |  + unit(college) | Built |
| TRN-003 | `/trainer/courses` | studio/CourseList |  + unit(studio) | Built |
| TRN-004 | `/trainer/courses/[course_id]/edit` | studio/CourseEditor |  + unit(studio) | Built |
| TRN-008 | `/trainer/grading` | trainer/GradingQueue |  + unit(trainer) | Built |
| TRN-009 | `/trainer/grading/[submission_id]` | trainer/GradeSubmission |  + unit(trainer) | Built |
| TRN-010 | `/trainer/integrity` | trainer/IntegrityReview |  + unit(trainer) | Built |
| TRN-005 | `/trainer/tests` | trainer/TrainerTests | e2e + unit(trainer) | Built |
| §13 | `/trainer/tests/[test_id]/attempts` | trainer/AttemptLog |  + unit(trainer) | Built |
| TRN-006 | `/trainer/tests/[test_id]/edit` | studio/TestBuilder |  + unit(studio) | Built |
| TRN-007 | `/trainer/tests/[test_id]/overrides` | trainer/TestOverrides |  + unit(trainer) | Built |
| TRN-011 | `/trainer/tests/[test_id]/report` | trainer/TestReportView |  + unit(trainer) | Built |

## 7. Issues

### INV-01: College invite acceptance page is a placeholder, so invited students cannot join
- Severity: Critical (core B2B workflow J2 is dead at the last step)
- Status: Confirmed
- Component: `apps/web/src/app/(public)/invite/[token]/page.tsx` (renders `<NotImplemented>`); backend ORG-18 `GET /api/v1/invitations/{token}` and ORG-19 `POST /api/v1/invitations/{token}/accept` are implemented and tested (orgs tests). The invite email links to this page: `apps/api/app/modules/identity/links.py:21` `"invite": "/invite/{token}"`
- Requirement: FR-ORG-011/012, FR-IDN-012, PRD §7 J2, sitemap PUB-016
- Repro: coordinator commits a roster (e2e `staff-portals.integration.spec.ts` "coordinator imports a CSV roster … → invitations"), then opens the invite link from Mailpit → "Not yet implemented".
- Expected / Actual: the invitee sees the org, creates or links an account and accepts. Actual: a placeholder with no action. `invitations/{token}` is called nowhere in `apps/web/src` (static extraction).
- Evidence: `grep -rln NotImplemented apps/web/src/app` lists `app/(public)/invite/[token]/page.tsx`; §5 rows ORG-18/ORG-19 = "Backend-only (tested)".
- Root cause: PUB-016 screen never built.
- Recommended fix: build `features/orgs` (or `features/auth`) `InviteAccept`: GET the invitation, show the data-sharing notice, then signup/login and POST accept with an Idempotency-Key. Add an e2e step to the staff-portals spec.
- Suggested owner paths: `apps/web/src/app/(public)/invite/[token]/page.tsx`, `apps/web/src/features/auth/components/*`, `apps/web/e2e/staff-portals.integration.spec.ts`

### INV-02: L3-restricted students land on a placeholder "Account status" page
- Severity: High
- Status: Confirmed
- Component: `apps/web/src/features/auth/lib/login-flow.ts:22` (`if (r && r.level >= 3) return safeNextPath(res.redirect, "/app/account-status")`); `apps/web/src/app/app/account-status/page.tsx` = `<NotImplemented screen="STU-026">`; student nav `apps/web/src/lib/nav/portals.ts:57`; backend `status_url="/app/account-status"` in `apps/api/app/core/auth.py:85`, `modules/sessions/resolver.py:203`, `modules/coding/service.py:145`
- Requirement: FR-SEC-003/004/009, sitemap STU-026, account-unblock-workflow
- Repro: sign in as an L3-restricted adult student (SCN-09 seed) → redirected to `/app/account-status` → "Not yet implemented". The L4 path (`/account/restricted`) is built.
- Expected / Actual: restriction reason, case reference, unblock-request/appeal status. Actual: placeholder with no link to `/unblock-request`.
- Evidence: code lines above.
- Root cause: STU-026 not built. PUB-021 (`RestrictedStatus`) and `/unblock-request` contain the needed pieces.
- Recommended fix: render `RestrictedStatus`/`UnblockRequestForm` (`features/unblock`) on `/app/account-status`, reading `me/security/status`.
- Suggested owner paths: `apps/web/src/app/app/account-status/page.tsx`, `apps/web/src/features/unblock/components/*`

### INV-03: Content studio cannot upload video/media; lessons cannot get assets from the UI
- Severity: High
- Status: Confirmed (static)
- Component: `apps/web/src/app/studio/media/page.tsx` (NotImplemented, CMS-012). MED-01 `POST /api/v1/media/uploads/video` has no web caller; `GET /media/assets/{id}/status` has no caller. `features/studio/components/Courses.tsx:141-299` creates `video` lessons via `draft/lessons` but offers no upload. `PATCH /studio/lessons/{id}`, `PUT /studio/courses/{id}/draft/outline` and `PUT /studio/lessons/{id}/topics` (CAT-15, untested) have no caller either.
- Requirement: FR-CAT-007, FR-CAT-001, PRD §6.10 CMS-012
- Repro: studio → course → add a video lesson → there is no way to attach a video.
- Expected / Actual: upload to VdoCipher, then status. Actual: backend only.
- Evidence: §5 rows MED-01 and CAT-12 "Backend-only (tested)", CAT-15 "Backend-only, untested".
- Recommended fix: media upload panel in the lesson editor (MED-01 ticket → provider upload → poll MED-02), lesson PATCH and topics.
- Suggested owner paths: `apps/web/src/features/studio/components/Courses.tsx`, `apps/web/src/app/studio/media/page.tsx`

### INV-04: Finance products/plans/prices, coupons and subscriptions consoles are placeholders
- Severity: High
- Status: Confirmed
- Component: `apps/web/src/app/finance/{products,coupons,subscriptions}/page.tsx` (NotImplemented; nav `portals.ts:141` and siblings). Backend COM-20..23 (products/plans), `POST /finance/plans/{id}/prices`, COM-24..27 (coupons; COM-27 PATCH untested), `GET /finance/subscriptions`, `POST /finance/subscriptions/{id}/cancel`, `GET /finance/reports/revenue` (COM-47): no web caller.
- Requirement: FR-COM-001/002/005/007, PRD §6.12 FIN-001/002/003/006
- Expected / Actual: finance_admin manages the catalogue, prices (dual approval for decreases above 20%) and coupons. Actual: possible only by direct API calls or seeds.
- Evidence: §5 table rows; `grep -rln NotImplemented apps/web/src/app/finance`.
- Recommended fix: build FIN-002/003/006 screens on the existing endpoints, and add the revenue tiles (COM-47) to `FinanceHome`.
- Suggested owner paths: `apps/web/src/features/finance/components/*`, `apps/web/src/app/finance/*`

### INV-05: Coordinator cannot add or remove students in a batch
- Severity: High
- Status: Confirmed (static)
- Component: `apps/web/src/features/college/components/Batches.tsx` calls only `GET batches/{id}`, `GET batches/{id}/members`, `GET/POST orgs/{id}/batches` and `GET analytics/reports/batches/{id}`. ORG-26 `POST /batches/{id}/members`, ORG-27 `DELETE …/members/{uid}`, `PATCH /batches/{id}` and `POST /batches/{id}/archive` have no caller. Member removal from the org (`DELETE /orgs/{id}/members/{uid}`) has no caller either.
- Requirement: FR-ORG-003/004/018, PRD §6.8 COL-005
- Expected / Actual: move/add/remove students and archive the batch. Actual: read-only.
- Recommended fix: add member management and archive actions to the batch detail.
- Suggested owner paths: `apps/web/src/features/college/components/Batches.tsx`

### INV-06: Support unblock triage cannot lift L1/L2 or forward, because the list API omits ids (shape mismatch)
- Severity: High
- Status: Confirmed
- Component: `apps/api/app/modules/security/api_review.py:945-966` (`support_list` returns only `reference,state,level,route`); `apps/web/src/features/support/components/SupportDesk.tsx:699-716` ("Lift and forward are not available yet: the api list does not include the request or restriction ids"). UNB-18 `POST /support/unblock-requests/{id}/forward` has no caller and no test.
- Requirement: FR-SEC-006, FR-SUP-006, PRD §6.11 SUP-005, role matrix §7 (support lifts L1/L2)
- Expected / Actual: support lifts L1/L2 and forwards L3/L4. Actual: read-only table.
- Evidence: code above.
- Root cause: the API response shape lacks `request_id`/`restriction_id`/`case_ref`.
- Recommended fix: return `request_id`, `case_ref`, `restriction_id` (no evidence fields) in `support_list`; wire Lift (SEC-21) and Forward (UNB-18); add an API test for forward.
- Suggested owner paths: `apps/api/app/modules/security/api_review.py`, `apps/web/src/features/support/components/SupportDesk.tsx`, `apps/api/tests/security/test_scn_unblock.py`

### INV-07: In-app notifications have no UI at all
- Severity: High
- Status: Confirmed (static)
- Component: NTF-01..03 (`GET /me/notifications`, `…/read`, `…/read-all`) have no caller (`grep -r "me/notifications" apps/web/src` returns nothing). `/app/notifications` is NotImplemented (STU-024). There is no bell or inbox in the shell. Several UIs promise a notification: `features/security-admin/components/Reports.tsx:150` ("You will be notified when the file is ready"), and security notices with `disown_url` (`security/signals.py:606`).
- Requirement: FR-NTF-001 (in-app channel), FR-NTF-002, PRD STU-024
- Expected / Actual: an inbox with unread count. Actual: notifications are written but unreadable in the UI.
- Recommended fix: an inbox page plus a shell badge on NTF-01..03.
- Suggested owner paths: `apps/web/src/app/app/notifications/page.tsx`, `apps/web/src/components/shell/*`

### INV-08: DPDP self-service data export / account deletion has no UI
- Severity: High (legal P0 requirement)
- Status: Confirmed (static)
- Component: PRV-01..05 (`/me/privacy-requests*`) have no caller. `apps/web/src/features/account/components/PrivacySettings.tsx` calls only `me/consents`. The org view `GET /orgs/{id}/privacy-requests` (PRV-12) has no caller and no test.
- Requirement: FR-PRV-002, privacy-and-data-retention.md, STU-023
- Expected / Actual: the student requests an export or deletion (14-day cooling-off) and downloads the export. Actual: backend only (admin side `/admin/privacy-requests` exists).
- Recommended fix: add an export/deletion section to `/app/settings/privacy`.
- Suggested owner paths: `apps/web/src/features/account/components/PrivacySettings.tsx`

### INV-09: Dead link: "appeal" on an invalidated attempt points to a non-existent route
- Severity: Medium
- Status: Confirmed
- Component: `apps/api/app/modules/assessments/attempts.py:1410` `out["appeal_url"] = f"/app/attempts/{attempt.id}/appeal"`; rendered as a `<Link href={r.appeal_url}>` in `apps/web/src/features/assessment/components/ResultsView.tsx:149-150`. No `app/app/attempts/[attempt_id]/appeal/page.tsx` exists (pages list in §6). Compare `integrity.py:388`, which uses the existing `/app/support/new?topic=assessment&attempt_id=…`.
- Requirement: FR-ASM-012 (student can appeal an invalidation)
- Expected / Actual: the appeal form opens. Actual: 404 (not-found page).
- Recommended fix: change `attempts.py:1410` to the support-ticket URL used in `integrity.py:388` (or build the page).
- Suggested owner paths: `apps/api/app/modules/assessments/attempts.py`

### INV-10: Other API-supplied URLs that point to routes that do not exist
- Severity: Medium
- Status: Confirmed (URLs) / Suspected (UX impact of `mfa_enrolment_required`)
- Component:
  - `apps/api/app/modules/sessions/resolver.py:212` `enrol_url="/app/settings/security/mfa"`: no such page (only `/app/settings/security`). The web client has no handler for `mfa_enrolment_required` (`grep` in `apps/web/src/lib/api/client.ts` finds none), so a staff user without MFA probably gets a generic error on every portal call.
  - `resolver.py:216` `guardian_flow_url="/app/guardian-consent"`: no such page.
  - `apps/api/app/modules/coding/service.py:627` `stream_url=/api/v1/coding/submissions/{id}/stream`: COD-09 is not routed (spec Planned). The web declares it in `features/coding/lib/types.ts:115` but polls instead.
  - `security/signals.py:606` `disown_url=/api/v1/me/security/events/{ref}/disown`: an API POST endpoint used as a link in notification data. The page for humans is `/app/settings/security/not-me/[event_ref]`.
- Requirement: implementation-conventions (problem `*_url` fields must be navigable)
- Recommended fix: point the URLs at the existing pages (`/app/settings/security`, `/app/settings/privacy` or a guardian-pending page, `/app/settings/security/not-me/{ref}`), drop `stream_url` until COD-09 exists, and add a client handler for `mfa_enrolment_required`.
- Suggested owner paths: `apps/api/app/modules/sessions/resolver.py`, `apps/api/app/modules/coding/service.py`, `apps/api/app/modules/security/signals.py`, `apps/web/src/lib/api/client.ts`

### INV-11: Section H exports cannot be retrieved from the UI; the SEC-001 dashboard ignores SEC-40
- Severity: High (exports) / Medium (dashboard)
- Status: Confirmed (static)
- Component: `features/security-admin/components/Reports.tsx:105-150` requests SEC-32 exports, but SEC-47 `GET /security/reports/exports/{id}` (download) has no caller anywhere in `apps/web/src`. The user is told they "will be notified", and notifications have no UI (INV-07). `SecurityDashboard.tsx:17` reads only `security/cases` counts; SEC-40 `GET /security/dashboard` (queue health, restrictions, appeals, rule performance, CGNAT watch) has no caller.
- Requirement: source-requirements §H ("exportable only by authorised users"), PRD §8.5 SEC-001 tiles
- Expected / Actual: approved export → download link; dashboard tiles H1–H12/ENG. Actual: an export job that cannot be downloaded; a dashboard with case counts and links only.
- Recommended fix: an export status/download list on `/security/reports` (SEC-47) and dashboard tiles from SEC-40.
- Suggested owner paths: `apps/web/src/features/security-admin/components/Reports.tsx`, `SecurityDashboard.tsx`

### INV-12: Unblock-request attachments are a stub, but the spec marks them "Implemented"
- Severity: Medium
- Status: Confirmed
- Component: `apps/api/app/modules/security/api_student.py:309-317` (UNB-03 always raises `service_unavailable` "File uploads need the S3 presign adapter (Planned)"); `api_review.py:942` (UNB-16 always `not_found`). `docs/api-specification.md` lists UNB-03 as **Implemented**. The UI does not offer attachments (`UnblockRequestForm.tsx:34`).
- Requirement: account-unblock-workflow §3 supporting documents; FR-SEC-004
- Recommended fix: implement it with the S3 presign used by `media/uploads/file`, or mark UNB-03/16 as Planned in the spec.
- Suggested owner paths: `apps/api/app/modules/security/api_student.py`, `api_review.py`, `docs/api-specification.md`

### INV-13: Taxonomy, company paths, resources and free resources: backend exists, UI is placeholder or missing
- Severity: Medium
- Status: Confirmed (static)
- Component: `/studio/taxonomy`, `/studio/companies`, `/free-resources`, `/companies`, `/companies/[slug]`, `/placement`, `/placement/[subject]/[topic]` are NotImplemented. PLC-02/03 (studio/topics), PLC-16/17 (studio/companies), `PUT /studio/company-paths/{id}`, CAT-21/22 (studio/resources) and CAT-02 `GET /catalog/free-resources` have no caller. `/app/companies` shows "Not available yet" (`features/practice/components/CompaniesIndex.tsx:7-16`): there is no student company list API. CAT-03..05 public company/topic APIs are Not built.
- Requirement: FR-PLC-001/007, FR-CAT-006, PUB-004..007, PUB-009
- Recommended fix: build CMS-008/009 on the existing endpoints and PUB-009 on CAT-02. Company hubs need CAT-03/04 first.
- Suggested owner paths: `apps/web/src/features/studio/components/*`, `apps/web/src/app/(public)/free-resources/page.tsx`

### INV-14: Coordinator staff grants, student profile, org settings and the trusted-network approval loop have no UI
- Severity: Medium
- Status: Confirmed (static)
- Component: `/college/staff` (COL-012) and `/college/students/[user_id]` (COL-009) are NotImplemented, although `GET /orgs/{id}/members/{uid}` and `POST /rbac/grants` exist. `PATCH /orgs/{id}/settings` (ORG-06) and `PATCH /orgs/{id}` have no caller, so FR-ORG-002 (MFA-for-students, allowed domains) is not configurable in the UI. Coordinators can register trusted networks (`/college/networks`), but SEC-33/34 (`GET /security/trusted-networks`, `POST …/{id}/decision`) have no caller, so a reviewer cannot approve them in the UI.
- Requirement: FR-ORG-002/017, COL-009/012, security trusted-network flow
- Recommended fix: add those screens; add a trusted-networks tab in `/security`.
- Suggested owner paths: `apps/web/src/features/college/components/*`, `apps/web/src/features/security-admin/components/*`, `apps/web/src/features/admin/components/Organizations.tsx`

### INV-15: Subscription (UPI AutoPay) flow is unreachable; recurring plans go through the one-time order flow
- Severity: Medium
- Status: Suspected (business semantics need confirmation by the commerce area)
- Component: COM-09/10 `POST /commerce/subscriptions`, `…/{id}/confirm` have no caller. `features/catalog/components/PricingPlans.tsx:70-73` sends recurring (`/month`, `/year`) plan prices to `/app/checkout/new?price_id=…`, which posts `commerce/orders` (`features/commerce/components/Checkout.tsx:137`). `commerce/service.py:795` (the subscription path) requires `price.is_recurring`; the order path has no such guard (`grep is_recurring` finds only :795).
- Requirement: FR-COM-005, AC-COM-03 (recurring cap ₹15,000), AC-COM-05 (one-click cancel)
- Expected / Actual: a recurring plan creates a mandate/subscription. Actual: a one-time order (no renewal, no mandate cap check).
- Recommended fix: route recurring prices to COM-09 in checkout, and/or reject recurring prices in `commerce/orders`.
- Suggested owner paths: `apps/web/src/features/commerce/components/Checkout.tsx`, `apps/api/app/modules/commerce/service.py`

### INV-16: Endpoints with no automated test reference (static)
- Severity: Medium
- Status: Suspected (static search; some may be exercised indirectly)
- Component: no test reference was found for: AUTH-03 email resend, **AUTH-04/05 mobile OTP send/verify** (OTP limits in FR-IDN-003 unverified), ANL-02 beacon, ANL-09 course report, ATT-13 `GET /me/attempts`, LRN-07 migrate-version, ORG-13 import cancel, PRV-09 verify-identity, PRV-12 org privacy requests, RBAC-08 and COM-49 approval reject, COM-27 coupon PATCH, SEC-02 `/me/security/cases/{ref}`, SEC-06 case assign, SEC-18 evaluation detail, SEC-27 shadow report, SEC-29 rollback request, SEC-14/15 concurrency and device-graph, UNB-04 submit (draft path), UNB-07 responses, UNB-13 request-info, UNB-18 forward, ASM-12 test-assignment PATCH, CAT-15 lesson topics, studio coding validation and content-downloads. Full list: §5 rows marked "none found".
- Recommended fix: add pytest cases. Priority: AUTH-04/05 (rate limits), UNB-07/13 (reviewer ↔ student info loop), SEC-29 (rollback is dual-control).
- Suggested owner paths: `apps/api/tests/identity/`, `apps/api/tests/security/`

### INV-17: H12 "Device and login history" report has no test; only H5/H8 exports are tested
- Severity: Medium
- Status: Confirmed
- Component: `apps/api/tests/security/test_controls_reports.py:267-279` loops over every key except `device-login-history` and `blocked-accounts` (H5 is tested separately). `device-login-history` appears in no test or e2e. Export tests exist only for `blocked-accounts` and `false-positive-rate`.
- Requirement: source-requirements §H item 12
- Recommended fix: add H12 (needs a `user_id` filter) to the test loop and add per-user export approval for H12.
- Suggested owner paths: `apps/api/tests/security/test_controls_reports.py`

### INV-18: P0 requirements not built (no route, no UI)
- Severity: Medium (each is a planned gap rather than a broken feature, but all are P0 in PRD v0.3)
- Status: Confirmed
- Component / Requirement:
  - FR-IDN-008 contact change (ME-03/04 not in openapi)
  - FR-IDN-005/006 passkey login and registration (AUTH-07/08, ME-10/11)
  - FR-NTF-003 notification preferences (NTF-04/05; `notifications/router.py:3`)
  - FR-PLC-013 diagnostic (`/app/diagnostic` placeholder)
  - FR-PLC-014 goal picker (PLC-28/29; `/app/onboarding` placeholder)
  - AC-ASM-06 / FR-ASM-011 regrade (ASM-17; `assessments/router.py:8`)
  - PUB-018/019/020 legal, help and status pages are placeholders (SYS-03..05, SUP-16/17 Planned); legal pages are referenced from signup consents (`/legal/terms`, `/legal/privacy`)
  - FR-NTF-001 SMS: only `ConsoleSmsAdapter` exists (`notifications/adapters.py:109,148-153`; any other `SMS_PROVIDER` → `UnavailableAdapter`), so SMS OTPs are **Fake-adapter-only**
- Recommended fix: track these in the backlog. The legal pages are the cheapest and matter most for compliance (consent links point at placeholders).
- Suggested owner paths: per item

### INV-19: Backend-only staff actions (no UI) for certificates, manual entitlements, announcements, incidents and exports approval
- Severity: Low
- Status: Confirmed (static)
- Component: LRN-20/21 (manual issue/revoke certificate), ENT-06/07 + `GET /users/{id}/entitlements` (manual grant/revoke, support view), NTF-06 batch announcements, SEC-37..39 incidents, `POST /exports/{id}/approve|reject`, ANL-10 platform report, `GET /security/unblock-requests` (student list), `GET /me/device-policy` and `GET /me/login-history` (published policy numbers and login history for FR-SEC-009), `GET /me/orgs` and `PATCH /me/orgs/{id}` (STU-027 college sharing; `/app/college` placeholder). None has a web caller.
- Requirement: FR-LRN-007, FR-ENT-005, FR-NTF-004, FR-SEC-009, STU-027
- Recommended fix: add UIs where the PRD lists a screen (STU-022 policy numbers and login history, STU-027, trainer announcements).
- Suggested owner paths: respective features

### INV-20: 34 placeholder pages, 11 of them linked from portal navigation
- Severity: Low
- Status: Confirmed
- Component: the full list is in §6 ("Placeholder"). Linked from nav in `apps/web/src/lib/nav/portals.ts`: `/app/account-status` (:57), `/app/analytics` (:51), `/college/shortlists`, `/college/staff` (:89), `/studio/companies`, `/studio/media` (:119), `/studio/taxonomy`, `/finance/coupons` (:141), `/finance/products`, `/finance/subscriptions`, `/admin/notifications` (:181).
- Expected / Actual: nav shows working screens or hides unbuilt ones. Actual: an honest "Not yet implemented" (not dead links: every href resolves).
- Recommended fix: hide nav entries for unbuilt screens behind a flag, or build them (see INV-01..14).

### INV-21: Documentation drift between docs and code
- Severity: Low
- Status: Confirmed
- Component:
  - `docs/api-specification.md`: 58 rows marked "Planned" are implemented (for example ORG-05, PLC-33..52, ASM-18..22, SUP-01..15, ADM-01..05, ADM-17..19, COM-13/14/16/37/42, ANL-13..15, COD-04/05/17/18).
  - 30 openapi operations are not in the spec (for example `POST /admin/users/{id}/reactivate`, `POST /orgs/{id}/reactivate`, `GET /exports`, `POST /exports/{id}/approve|reject`, `GET /finance/gst-exports*`, `GET /mentor/slots`, `GET /mentor/students`, mentor notes, the resume PDF upload trio, studio coding list/reference-solutions/validation/content-downloads, `GET /assignments`, `GET /assignment-submissions/{id}`).
  - UNB-03 "Implemented" but a stub (INV-12).
  - `docs/sitemap.md:311` says `/mentor/students` has no backend endpoint, but `GET /mentor/students` exists and is used.
  - `apps/api/app/modules/analytics/jobs.py:4` says beat wiring is Planned, but `analytics/tasks.py` registers it.
  - Stale comments in `apps/web/src/features/auth/components/LoginForm.tsx:67` and `features/account/components/SecuritySettings.tsx:339`: the API now returns `web_path("forgot_password")` = `/forgot-password` (`identity/router.py:538`, `security/api_student.py:248`, `sessions/resolver.py:188`).
- Recommended fix: re-sync the status column in the spec from openapi (scriptable: see §0) and add the 30 undocumented operations.
- Suggested owner paths: `docs/api-specification.md`, `docs/sitemap.md`

## 8. Summary

- **Wiring:** no frontend→API mismatches. 398 static call sites, 0 calls to missing paths, 0 wrong methods; tsc is clean; the committed openapi.json equals the live app (0 drift). Every sitemap route exists and every in-app href resolves.
- **Main gaps:** (a) 34 placeholder pages, several sitting on implemented backends (invite acceptance, account status, finance catalogue/coupons, studio media/taxonomy/companies, notifications); (b) about 90 backend operations with no UI caller; (c) dead links in **API-supplied** URLs; (d) one response-shape gap (support unblock triage).
- **Counts:** Critical 1 (INV-01) · High 8 (INV-02, 03, 04, 05, 06, 07, 08, 11) · Medium 9 (INV-09, 10, 12, 13, 14, 15, 16, 17, 18) · Low 3 (INV-19, 20, 21). **Total 21.**
- **Endpoint classification (449 ops):** Impl+tested 320 · Backend-only (tested) 91 · Impl-untested about 18 · Backend-only untested about 12 · infra/no-UI 6 · stubs 2 (UNB-03, UNB-16) · plus 58 spec endpoints Not built.
- **Not tested / limits:** test **existence** only (I did not run pytest, vitest or Playwright). Response-body shapes are checked by reading only, because most routes are `dict[str, Any]`. The test-reference search is regex-based and has false negatives for `f"{base}/…"` patterns. Role×permission cell parity, NFRs and adapter behaviour belong to other areas.
