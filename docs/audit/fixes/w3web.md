# w3web: wave-3 web fixes

Agent key `w3web`. Owned paths: all of `apps/web/**`. Scope: every §Requests item aimed at the web in `core`, `w2b`, `webstaff`, `weblearn`, `secadmin`, `assess`, `learn` and `commerce`, plus the w2a web requests the coordinator added mid-run. Work was split into the lead (shell, nav, client, CSP) and forks B (studio, trainer, college, support), C (learner, commerce), D (finance, admin, security-admin), E (coupons, analytics) and F (test builder, coding).

The API contract was regenerated at the start, again after w2a finished, and again at the end (no change): `apps/api/openapi.json` (408 paths) → `apps/web/openapi/openapi.json` → `npm run gen:api`.

| ID(s) | Severity | Fix summary | Files | Regression test | Result |
|---|---|---|---|---|---|
| SEC-04 (core) | High | `lib/nav/portals.safeNextPath` now delegates to the hardened `features/auth/lib/validation.safeNextPath`. | lib/nav/portals.ts | lib/nav/portals.test.ts | Fixed+tested |
| commerce/core (nav) | Low | Removed the duplicate `/app/analytics` entry (the route still redirects to `/app/progress`). | portals.ts | portals.test.ts (no duplicate hrefs) | Fixed+tested |
| commerce/core, weblearn 1 (deep link) | Medium | PortalShell builds `next=` from the middleware's `x-td-request-path`, kept only when it is a safe path inside the portal (`signInNext`). | components/shell/PortalShell.tsx, portals.ts | portals.test.ts | Fixed+tested |
| ADM-12 (core) | Medium | `StaffPortalGate` (`/me/grants`) and `PortalSwitcher` already exist. | — | staff-portal.test.tsx | Already done |
| INV-10 (core) | Medium | The client handles 403 `mfa_enrolment_required` by navigating to `enrol_url` (same-origin check, default `/app/settings/security/mfa`, also used by staff). It does not navigate when already on that page. | lib/api/client.ts | client.test.ts (2 tests) | Fixed+tested |
| FE-09 (core) | Low | `retryAfterSeconds` already falls back to the body field and the `Retry-After` header. | — | features/auth/lib/errors.test.ts | Verified |
| SEC-09, E2E-12 (core) | High | StepUpDialog asks AUTH-19 for the account's real methods. TOTP; email/SMS OTP (AUTH-19 `{send_otp_via}` then AUTH-20 `{method, code}`, resend); password only when the API lists it. `reason: code_already_used` says "wait for the next code". Plain messages for `otp_invalid/expired/attempts_exceeded/send_limited`. | components/shell/StepUpDialog.tsx | components/shell/StepUpDialog.test.tsx (4) | Fixed+tested |
| core (README) | Low | `TD_TRUSTED_PROXY_HOPS=0` documented as "client IP unknown". | apps/web/README.md | — | Fixed |
| webstaff 1, weblearn 1 (nav) | Low | `/admin/notifications` (ADM-011) and `/college/shortlists` (COL-010) hidden. Added `/security/networks`, `/security/incidents`, learner `/app/path`, `/app/college`, `/app/notifications`, and college `/college/support`. | portals.ts | portals.test.ts | Fixed+tested |
| webstaff 3 | Low | New `apiRequestRaw` (same CSRF, step-up, auth and problem handling; returns the raw Response). The security-admin CSV download uses it. `mockApi` gained a `raw` body. | client.ts, features/security-admin/lib/download.ts, features/auth/test/mock-api.tsx | client.test.ts; security-console.test.tsx (3 tests moved to mockApi) | Fixed+tested |
| webstaff 7 | High | CSP `connect-src`/`form-action` now allow the content bucket (`S3_BUCKET_CONTENT`, AWS virtual-hosted) and the VdoCipher upload origin (`TD_CSP_VDOCIPHER_UPLOAD_ORIGINS`, default `https://vdo-ap-southeast.s3-accelerate.amazonaws.com`, unverified). Only exact https origins; wildcards are dropped. Nonce CSP unchanged. | lib/security/csp.ts | csp.test.ts (2 new) | Fixed+tested |
| webstaff 16 | Low | Real HTTP 403 via `forbidden()`/`authInterrupts` not done. It is experimental in Next 15.5, and `forbidden.tsx` cannot receive the reachable-portal list. The gate still renders PortalForbidden (200). | — | — | Deferred: optional, experimental API |
| w2b R4 studio (lesson types, resources, topics, taxonomy, `q`, `retired_reason`) | Medium | Fork B. Added the `pdf`/`practice_set` types (practice-set test picker); resources from `GET studio/resources?lesson_id=`; topics editor; taxonomy uses `GET studio/topics`; question `q` search; `retired_reason` shown. | features/studio/** | studio-authoring.test, Questions tests | Fixed+tested |
| w2b R4 trainer rubric | Medium | Rubric editor sends `{criteria:[{key,label,max_points}]}`; grading sends `rubric_scores` without `score`. | features/trainer/components/Grading.tsx | trainer-fixes tests | Fixed+tested |
| w2b R4 / weblearn 4 support | Medium | `NewTicketForm`: `?topic=` → `category`; `?attempt_id=` → `related_attempt_id`. | features/support/**, app/app/support/new | support.test (2) | Fixed+tested |
| w2b R4 college | Medium | Roster `member_type` filter; `email_domain_not_allowed` message on invite and import. | features/college/** | college-manage (4) | Fixed+tested |
| learn R5 support/desk | Medium | New categories; MED-02 `support_attachment` uploads and attachment downloads; college lane `/college/support` (`college_access` only). | features/support/**, app/college/support/** | support tests | Fixed+tested |
| learn R5 batches, grading | Low | Archived-batch 409 message; `raw_score`/`late_penalty_pct` shown. Studio review (`awaiting_review`, `review_comment`, `sod_violation`) and `/files/{i}` download were already done. | BatchManage.tsx, Grading.tsx | trainer/college tests | Fixed+tested |
| assess 6 staff (ADM-36, ADM-43, `/studio/tests` paging) | Low | ADM-36/43 were already done. `useApiAll` follows `next_cursor` for the test pickers. | trainer/shared/use-api.ts | paging test | Fixed+tested |
| w2b R4 player (`pdf`, `practice_set`) | Medium | Fork C. PDF lessons open through MED-07 and complete once opened; practice-set lessons launch their test. | features/learning/components/LessonView.tsx, lib/types.ts | lesson-types.test.tsx | Fixed+tested |
| learn R5 (LRN-02/11 paging) | Medium | `useAllPages` follows `next_cursor` in My courses and Certificates. No learner screen asks for `limit` > 100. | features/learning/** | lesson-types.test.tsx | Fixed+tested |
| assess 6 (ATT-07 4/min) | Medium | Time-up polling went from 3 s ×40 to 15 s ×20 and respects `Retry-After` on 429. The other assess 6 learner items were already done. | features/assessment/components/AttemptRunner.tsx | runner-learning.test.tsx | Fixed+tested |
| commerce 2/3 (FE-27, E2E-04, INV-15, FE-26) | — | Already done (checkout resume, consent "Turn on and continue", subscriptions, "Complete payment"). | — | checkout-resume.test.tsx | Already done |
| ADM-25, `price_adjustment` (commerce 4) | — | Already done. | — | admin.test.tsx | Already done |
| ADM-32, webstaff 6, w2a R4 coupons | Medium | Forks D and E. Coupons filter `status` on the server, show the pending `approval_request_id` on list rows, and read the 202 envelope (`required_approver_role`, `expires_at`). | features/finance/components/FinanceCatalog.tsx | finance-catalog.test.tsx | Fixed+tested |
| ADM-05/06/07, INV-11 (secadmin 4) | Medium | My exports downloads from `download_path` and hides expired jobs; 422 `user_id` errors appear on the filter they name; H10 per-user sessions and session cap, H11 granularity and scope, H8 labelled alerts. The filter bar and the removed checkbox were already done. | features/security-admin/components/{MyExports,Reports,ReportExtras}.tsx | security-console.test.tsx | Fixed+tested |
| webstaff 11, w2a R4 analytics | Medium | Fork E. Batch `progress_distribution` and `lesson_funnel`; org `course_completion_rate` and `test_participation`; readiness `name`. k-floor cells are suppressed. | features/trainer/shared/report-sections.tsx (new), Insights.tsx, college/components/{Batches,CoordinatorDashboard}.tsx | trainer-fixes, college.test | Fixed+tested |
| webstaff 10, ADM-49, w2a R4 test builder | Medium | Fork F. Coding problem picker (fixed `coding_problem_id`), random `question_types:["coding"]`, 422 on the rule, "Batch-owned" badge. | features/studio/components/Tests.tsx | test-builder-coding.test.tsx (3) | Fixed+tested |
| weblearn 3, w2a R4 coding `attempt_id` | Medium | COD-03/04/05 and run send `attempt_id`; COD-03 by id; `slugForId` removed. | features/coding/** | coding-signals.test.tsx | Fixed+tested |

## Requests

1. **infra / root (`.env.example`, `infra/`):**
   - Document `TD_CSP_VDOCIPHER_UPLOAD_ORIGINS` (web) next to `TD_CSP_UPLOAD_ORIGINS`.
   - Make sure the web task has `S3_BUCKET_CONTENT` and `AWS_REGION`.
   - Bucket CORS on the uploads and content buckets must allow the web origin for POST (webstaff 7).
   - Confirm the real VdoCipher `uploadLink` origin for our account region.
2. **product (fork C decision):** PDF lessons complete once the learner opens the PDF. Tracking reading to the end would need an in-page viewer and a CSP `frame-src` entry for the content bucket. Decide whether that is wanted.
3. **coding API (fork F note):** the coding-problem picker in the test builder needs `coding_problem.manage`. A batch trainer without it can only add random coding draws. Consider a read-only published-problem list for test authors.
4. **docs:** `api-specification.md` §2.1 should list the `enrol_url` default, which the web also uses for staff.

## Commands and results (from `apps/web`, final run)

- `.venv/Scripts/python -m app.scripts.export_openapi` (in apps/api): 408 paths; identical to `apps/web/openapi/openapi.json` after the final regen. `npm run gen:api`: OK.
- `npm run lint`: clean (0 warnings).
- `npm run typecheck`: clean.
- `npx vitest run`: **66 files, 628/628 passed**.
- `npm run build`: compiled successfully; all routes built.
- Playwright: not run (the coordinator runs it next).
