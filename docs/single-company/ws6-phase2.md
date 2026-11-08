# WS6 phase 2: web re-pointing after the backend workstreams

| | |
|---|---|
| Status | Done in code. `npm run build` could not finish on this machine (see §4). |
| Date | 2026-11-07 |
| Inputs | [ws6-phase1.md](ws6-phase1.md) §6, ws1–ws5, [REMOVAL-PLAN.md](REMOVAL-PLAN.md) §8 |
| Scope | `apps/web` only. In `apps/api` the only action was running the OpenAPI export script. No commits were made. |

## 1. OpenAPI and types

- I ran `cd apps/api; .venv/Scripts/python -m app.scripts.export_openapi`. It wrote **451 paths**, down from 482.
- I copied the result to `apps/web/openapi/openapi.json` and ran `npm run gen:api`, which regenerated `src/lib/api-types/schema.d.ts`.
- After regeneration, `tsc` showed 3 errors:
  - `FlagPatch.org_allowlist`
  - `CouponIn.organization_id`
  - the `org_only` course visibility

  The contract test showed 1 failure: `POST admin/break-glass`, which now returns 405. All four are fixed.

## 2. Changes, following phase-1 §6

1. **Batches.** Every call now uses a literal path: `batches`, `batches/{id}`, `/archive`, `/members`, `/members/{uid}`, `analytics/reports/batches/{id}`, `admin/users`, `rbac/grants` and `rbac/grants/{id}/revoke`. All of them are checked against the OpenAPI and covered by the contract test. `BATCH_API` is deleted.
   - Adding a member upserts the org membership on the server (`ensure_org_membership`), so this works for a user with no existing membership.
   - `BatchReport.organization_id` was dropped.
2. **AI admin.** The calls are now `admin/ai-settings`, `admin/apps` and `admin/ai-usage?month=`.
   - `COMPANY_ORG_ID` and `AI_ADMIN_CONFIGURED` are deleted, and `NEXT_PUBLIC_COMPANY_ORG_ID` is removed from `.env.example`.
   - The settings form now needs every cap; the API no longer accepts "unlimited". It also has the 4 new SEC-05 rate limits, using the API's bounds.
   - The `organization_id` fields were removed from the AI types. `AITutorReply.limit` is now `number`.
3. **Enquiries.** The form posts to the literal path `public/enquiries`.
   - The body type is `Schema<"EnquiryIn">`.
   - The client limits now match the API: name 2–100, company 2–150, message 10–4000.
   - Success is 202. The API has no CAPTCHA field, only the `website` honeypot and rate limits.
4. **App toggles.** `useEnabledApps()` takes no argument. Both `me/enabled-apps` hooks are now platform-wide.
5. **Org pickers and `organization_id` senders.** These are removed from:
   - paths (list, articles, AI generate, link options, the editor)
   - engage (the "no batch" option means platform-wide and is offered to platform staff only)
   - the assignment manager (owner is a batch, or company-wide for platform staff)
   - studio `Courses` and `TrainerCourses`
   - the `QuestionBankPicker` filter
   - the restriction bulk-lift selector and the coupon form
   - feature flags (`org_allowlist`) and `PolicySettings` (`org_overridable`)
   - the dashboard `organizations` tile
   - `Me.organizations`, `Users.organizations`, `Ticket.organization_id` and the `orgs/{id}/members` evaluator picker. The picker now uses batch members, plus `rbac/grants` for Admin.

   **Kept on purpose:** question create and media upload still send the bank's own `organization_id`. WS5 accepts null or the company org, and without it a question an Admin adds to a company bank would become a platform question.
6. **Paths.** `paths/org-members` became `paths/batch-members?batch_id=&q=`, with batch-first member search (`BatchMemberSearch.tsx`).
   - The audience is now `batches` or `people`.
   - The player uses an iframe only when the server's `step.embeddable` is true **and** the client allow-list agrees.
   - The editor strips `embeddable` before saving, because the save body rejects extra fields.
7. **Tutor.** `AITutorPanel` no longer sends history. It loads `GET me/assignments/{id}/tutor/history?item_id=` and shows the wait time on a 429 `rate_limited`.
8. **Tests.** Test assignments already sent `batch_id` only. The old "Everyone" label for legacy rows without a batch now reads "No batch (older assignment)".
9. **Evaluator portal.**
   - `useTrainerBatches` now includes evaluator batch grants. Platform staff get `GET batches`.
   - Messages were added for `not_evaluator`, `conflict_of_interest` and `not_allocated`.
   - Structured assignments are left out of the legacy grading queue, because SEC-11 now returns 409 for them.
10. **Admin enquiry queue (new).** New component `features/support/components/Enquiries.tsx`, and new pages `/desk/enquiries` (SUP-006) and `/desk/enquiries/[enquiry_id]` (SUP-007).
    - The list has a status filter and a count of new enquiries.
    - The detail page has "Assign to me" (which moves a new enquiry to in progress), close, spam, reopen and a staff note.
    - It is in the Admin nav under Support, and in `docs/sitemap.md`.
11. **Trusted networks and lab devices.** Removed the "Lab device" column, the shading for lab devices in the graph, and the `lab` field on device nodes.
    - Added the `shared_computer_details` info template and the `shared_computer` unblock reason, matching the WS5 rename.
12. **Break-glass.** The activate button and dialog are removed, because the API now returns 405. History, end and review stay.

**Line endings.** About 200 web source files had CRLF line endings in the working tree. I converted them to LF, as `.gitattributes` requires with `eol=lf`. The two `openapi.json` files were converted too.

## 3. Not wired, or needs the backend

- **`me/grants` does not list `/evaluator`.** `apps/api/app/modules/sessions/login.py` `PORTALS` still maps `evaluator` to `/trainer`, so `me/grants` never returns `/evaluator`.
  - As a stopgap, `staff-portal/access.ts` lets a live grant of one of a portal's roles open that portal.
  - WS1 should map `evaluator` to `/evaluator`. Until then, evaluators can also reach the `/trainer` shell; the API still blocks authoring.
- **Admin's evaluator picker shows only a short id** for grant holders who are not batch members, because grants carry no names.
- **E2E is not run.** `E2E_EVALUATOR_*` still needs WS1's seeded `evaluator@` account and the CI secret.
- **Docs not done:** the full rewrite of the PRD, API spec, schema and ERD (phase-1 §6.10).

## 4. Results (apps/web, real runs)

**Machine condition.** During this run, drive C: had **0 MB free**. That capped Windows virtual memory: about 1.9 GB of commit was free. I pointed TEMP and TMP at `apps/web/node_modules/.tmp` for every command, and **deleted nothing**. Please free space on C:, then re-run `npm run build`.

| Check | Result |
|---|---|
| `npx tsc --noEmit` | Pass, 0 errors |
| `npx eslint . --max-warnings=0` | Pass, 0 problems |
| `npx vitest run` (default workers) | Did not finish. The worker crashed with `JavaScript heap out of memory` / `Channel closed`, which is system memory exhaustion, not a test failure. |
| `npx vitest run --maxWorkers=2` | **81 files, 723 of 723 passed** in 139 s. No global timeout was changed. |
| Contract test (`__contract__/api-paths.test.ts`) | Pass. It ran in the full run, and also with `--maxWorkers=1` alongside the support, admin, batches, security-admin, finance and unblock tests: 103 of 103 passed. |
| `npm run build` | **Incomplete, two attempts.** Both printed "✓ Compiled successfully". Attempt 1 then died in a build worker with `Zone Allocation failed - process out of memory` (exit 134). Attempt 2 got through "Linting and checking validity of types" and "Collecting page data", then crashed at "Generating static pages (0/123)" (exit 0xC0000409). Both crashes were caused by memory, not by the code. |
| Playwright | Not run. It needs the live stack and the seeded evaluator account. |
