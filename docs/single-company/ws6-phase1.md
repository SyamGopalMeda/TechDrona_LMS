# WS6 phase 1: web, docs, E2E and CI (single-company conversion)

Scope: [REMOVAL-PLAN.md](REMOVAL-PLAN.md) §1.4, §1.6, §6 WS6 and the §8 owner decisions. This phase covers only the work that does not depend on backend changes. `apps/api` was not touched, and no commits were made.

## 1. Deletions (apps/web)

**Routes**
- `src/app/college/**` (27 pages and the layout)
- `src/app/admin/organizations/**`
- `src/app/(public)/invite/**`, `src/app/(public)/colleges/**`
- `src/app/app/college/**`
- `src/app/finance/contracts/**`, `src/app/security/networks/**` (D5)

**Features and components**
- `src/features/college/**` (all components, lib and tests)
- `src/features/invite/**`
- `features/admin/components/Organizations.tsx`, along with its `OrganizationDetail` test
- `features/ai/admin/OrgAIAdmin.tsx`, which was renamed and converted (see §2)
- `features/privacy/components/CollegeSharing.tsx`
- `features/engage/components/CollegeEngage.tsx`
- `features/security-admin/components/TrustedNetworks.tsx`
- `features/trainer/shared/grants.ts#coordinatorOrgId`
- The coordinator-only `assignableForOrg` mode of `TestsList`

**Removed UI and copy**
- Finance: contracts, contract invoices, the `institution_seat` product kind and the coupon org field. The optional buyer GSTIN stays (D1).
- Signup: `invite_token` and the `college_data_sharing` consent.
- Unblock: the lab / shared-computer reason (D5).
- Support: the college lane. `corporate_enquiry` is added to the desk category filter.
- Security console: the lab template, org filters and the networks link.
- Admin: Organizations cards. Role pickers now show only Admin, Trainer, Evaluator, Content manager and Student, with scopes `platform`, `batch` and `course`.
- Engage scope `orgId`, the `/college` branch of the paths base, and the "For colleges" links.
- Public help and legal text.
- "Coordinator", "college" and "organization" wording in the trainer, AI and assessment copy.

**E2E**
- Deleted `e2e/_audit/staff.audit.ts`.
- College portal specs were replaced by an `/evaluator` smoke test and a11y checks that use `E2E_EVALUATOR_*`.
- The gate spec now covers `/evaluator`.
- `public-pages.spec.ts` checks that `/college`, `/invite/x` and `/colleges` return 404 and that the `/enquiries` form renders.

## 2. New and moved pages

| Route | What it is |
|---|---|
| `/enquiries` (public) | Corporate enquiry form (D8). Fields: name, company, email, optional phone, message and a required consent box. It has client validation, an error summary with focus, a honeypot field, an idempotency key and 429 handling. It posts to `ENQUIRIES_ENDPOINT` (`src/features/public/lib/enquiries.ts`). The header, footer and home page link to it. |
| `/admin/batches` | Batch list with create (name, code, intake, graduation year, dates). |
| `/admin/batches/[batch_id]` | Batch detail: edit and archive, add a student (search existing accounts, one at a time, D4), move or remove members, assign or revoke a Trainer or Evaluator (an RBAC grant at batch scope), and the batch report. Student names link to `/admin/users/{id}`. |
| `/admin/ai` | AI settings, authorized apps and usage for the whole platform. Replaces `/admin/organizations/[id]/ai`. |
| `/evaluator`, `/evaluator/grading/[submission_id]`, `/evaluator/grading/assignments/[id]`, `/evaluator/tests`, `/evaluator/tests/[test_id]/evaluation`, `/evaluator/tests/[test_id]/report`, `/evaluator/integrity` | Evaluator portal. It reuses the trainer grading screens with authoring hidden: no "New test", Assign, Edit, Overrides or "Edit assignment". Grading and publishing results stay (D3). Links stay inside `/evaluator`, using `features/trainer/shared/portal-base.ts`. |

The batches UI now lives in `src/features/batches/` (`components/Batches.tsx`, `components/BatchManage.tsx`, `lib/types.ts`, `lib/api.ts`, `batches.test.tsx`). The trainer batch page and the trainer, assessment and learning imports now point there. `readText` moved to `src/lib/files/readText.ts`.

## 3. Navigation and role gates (D2)

- `src/lib/nav/portals.ts`:
  - The `college` portal is removed and an `evaluator` portal is added (`/evaluator`, role `evaluator`).
  - `ADMIN_NAV` holds the admin items (now including Batches and AI & apps) plus the sections Finance, Support, Account security and Mentoring.
  - The `finance`, `support`, `security` and `mentor` portals keep their URLs and layouts. They now have `roles: ["super_admin"]`, `parent: "admin"` and share `ADMIN_NAV`. The Admin portal title is now "Admin".
  - Removed nav items: Contracts, Trusted networks, Organizations, and the learner's "My college".
- `PortalNav` renders section headings and highlights the most specific matching item. Portal roots match only exactly.
- `PortalSwitcher` and `reachablePortals` (shown on the 403 page) hide the admin sub-sections.
- `canEnterPortal`: `/admin` still opens every staff portal, including `/evaluator`.

## 4. Security: CSP and embeds (D9, SEC-08)

- `src/lib/security/csp.ts`:
  - `frame-src` is set to `EMBED_FRAME_ORIGINS`: `https://www.youtube-nocookie.com`, `https://player.vimeo.com`, `https://docs.google.com` and `https://drive.google.com`.
  - `'self'` is left out on purpose, so SEC-08 stays closed.
- `src/features/paths/lib/embed.ts`:
  - A pure allow-list check that accepts only HTTPS youtube-nocookie `/embed/`, Vimeo `/video/`, and Docs or Drive preview/embed URLs.
  - A test keeps it in sync with the CSP.
- `src/features/paths/components/Learner.tsx`:
  - Only allow-listed URLs are embedded, using `sandbox="allow-scripts allow-same-origin allow-presentation allow-popups"`, a strict-origin referrer policy, a limited `allow` attribute and lazy loading.
  - Every other URL gets an "Open in a new tab" link.
- The server-side check when a step is saved belongs to WS4.

## 5. Docs, env and CI

- New ADR: `docs/architecture-decisions/ADR-0015-single-company.md`. ADR-0004 was already taken. ADR-0003 is marked as amended by it.
- Fully updated: `docs/sitemap.md` (including the evaluator routes as built) and `docs/wireframes.md`.
- Focused edits:
  - `product-requirements.md`: PUB-010 is now `/enquiries`, college, contract and org screens are removed, an Evaluator portal section is added, ADM-003 is now `/admin/ai`, and ADM-013/014 cover batches.
  - Also edited: `design-system.md`, `account-unblock-workflow.md`, `deployment-and-operations.md`, the root `README.md` and `apps/web/README.md`.
- Single-company banners were added to `api-specification`, `database-schema`, `database-erd`, `implementation-roadmap`, `implementation-status`, `testing-and-acceptance-criteria`, `account-security-and-risk-engine`, `privacy-and-data-retention`, `contract-reconciliation`, `analytics-event-schema`, `system-architecture`, `blueprint-brief` and `wiseman-reference/build/{engage,paths,ai,assign}.md`. `docs/audit/00-feature-inventory.md` got a historical banner.
- `role-permission-matrix.md` was not touched; it belongs to WS1.
- `.env.example`:
  - Dropped the `/invite/{token}` mention.
  - Changed "org admins" to "admins".
  - Added `COMPANY_DISPLAY_NAME` (optional).
  - Added `NEXT_PUBLIC_COMPANY_ORG_ID`, which is needed in phase 1 only (see §6).
- `.github/workflows/ci.yml` and `apps/web/.env.e2e.local`: `E2E_COORDINATOR_*` is now `E2E_EVALUATOR_*`.

## 6. What phase 2 must re-point (exact list)

1. **`src/features/batches/lib/api.ts` `BATCH_API`.**
   - `list` and `create` are already `batches` (the new WS1/WS4 routes). Confirm the `batches/{id}`, `/archive`, `/members`, `/members/{uid}` and `analytics/reports/batches/{id}` paths, the `rbac/grants` paths, and the `admin/users?q=` search.
   - Then switch the calls back to literal paths so `src/features/__contract__/api-paths.test.ts` covers them. The helpers are invisible to the contract test today.
   - Check that adding a member works for a user without an org membership (the api should upsert it).
2. **`src/features/ai/admin/endpoints.ts`.**
   - Set `AI_ADMIN_BASE = "admin"`. This makes the calls `admin/ai-settings`, `admin/apps` and `admin/ai-usage?month=` (WS3).
   - Delete `COMPANY_ORG_ID` and `AI_ADMIN_CONFIGURED`, and remove `NEXT_PUBLIC_COMPANY_ORG_ID` from `.env.example`.
   - Update the `AI_ADMIN_BASE` keys in `features/ai/ai.test.tsx`.
3. **`src/features/public/lib/enquiries.ts` `ENQUIRIES_ENDPOINT`.** Use a literal `public/enquiries` (WS5) after the OpenAPI is regenerated, and confirm the body field names and the CAPTCHA token field if WS5 adds one.
4. **App toggles.** `features/ai/hooks/useEnabledApps.ts` sends `org_id` to `me/enabled-apps`, and `useNavApps.ts` is described as "per-organization". Make both platform-wide.
5. **Org pickers and `organization_id` senders still in the UI:**
   - `features/trainer/components/TrainerCourses.tsx` (`organizationId`; the picker never shows with one org)
   - `features/paths/components/PathList.tsx`, `Articles.tsx` and `features/paths/lib/types.ts`
   - `features/engage/lib/builder.ts`
   - `features/security-admin/components/Restrictions.tsx` (bulk lift, `organization_id: null`)
   - `features/finance/components/FinanceCatalog.tsx` (coupon `organization_id: null`)
   - `features/admin/components/Governance.tsx` (flag `org_allowlist`, kept for existing values)
   - Org pickers in studio, question bank and assignment manager, listed in REMOVAL-PLAN §1.4: `Courses.tsx`, `Tests.tsx`, `QuestionBankPicker.tsx`, `AssignmentManagerList.tsx`, `AllocateDialog.tsx`, `TestsList`/`TestOps`/`AssignTest`
   - Types only: `account/lib/types.ts` (`Me.organizations`), `admin/Users.tsx` (`organizations`), `commerce/lib/types.ts` (entitlement `organization_id`), `batches/lib/types.ts` (`organization_id`)
6. **Evaluator portal dependencies on the backend:**
   - `GET me/grants` must return `/evaluator` in `portals` for the `evaluator` role (WS1, `sessions/login.py` PORTALS).
   - `assignments?scope=mine` must include the evaluator's batches (WS4).
   - The evaluator tests list calls `studio/tests`. It needs read access for evaluators, or a grading-scoped list endpoint (WS5).
   - `rbac/grants` with `role_key: "evaluator"` and `scope_type: "batch"` must be accepted (WS1).
7. **"Everyone" scope.** The test assignment label (`AssignTest.tsx`, `TestOps.tsx`), shown when there is no `batch_id`, should be confirmed against WS5's company-wide assignment semantics.
8. **OpenAPI regeneration.** Run `python -m app.scripts.export_openapi`, then `npm run gen:api` to regenerate `openapi/openapi.json` and `src/lib/api-types/schema.d.ts`. That removes the 41 org, invitation, contract and seat paths. Never hand-edit them.
9. **E2E evaluator account.** `E2E_EVALUATOR_TOTP_SECRET` in `.env.e2e.local` and the CI secret still hold the old coordinator value, and need WS1's seeded `evaluator@` account.
10. **Docs.**
    - Rewrite the full PRD, API spec, schema and ERD text after the OpenAPI is regenerated.
    - Update the role-permission matrix (WS1 does the code; WS6 reviews).
    - Re-check the README demo-accounts line against WS1's seed.

## 7. Results

All commands were run in `apps/web` on 2026-11-07.

| Check | Result |
|---|---|
| `npx tsc --noEmit` | Pass, 0 errors. No errors come from backend changes, because phase 1 does not depend on any. |
| `npx eslint . --max-warnings=0` | Pass, 0 problems. |
| `npm run build` | Pass. Built routes include `/enquiries`, `/admin/batches`, `/admin/batches/[batch_id]`, `/admin/ai` and the seven `/evaluator/**` routes. There are no `/college`, `/invite` or `/colleges` routes, so those paths return 404. |
| `npx vitest run --testTimeout=30000` | 712 of 715 tests passed. The 3 failures were timing-sensitive tests (`progress.test.tsx` and the AttemptRunner timer tests), which ran while `next build` was running at the same time. All 20 tests in those three files pass when run on their own. |
| `npx vitest run` (default 5 s timeout) | Not green on this machine. 25 tests failed in a full parallel run, all because they hit the 5 s per-test timeout in typing-heavy dialog tests across many features. Each failed file passes when run alone (for example, admin, batches and public: 82 of 82). The new `batches` and `enquiry` tests now set `testTimeout: 20000`. Recommendation: set a global `testTimeout` in `vitest.config.ts`, which is outside this workstream's change scope. |
| Contract test (`api-paths.test.ts`) | Passes. New phase-2 endpoints are reached through constants, so the contract test does not check them yet (see §6 items 1–3). |
| `rg -i "college\|coordinator\|institution" apps/web/src` | Remaining hits are intentional: mentor résumé "Institution" fields, the legal text "institution (optional)" (D6), comments noting the removal, and tests that assert the routes are gone. |
| Playwright | Not run. It needs the live stack and the seeded `evaluator@` account from WS1. |
