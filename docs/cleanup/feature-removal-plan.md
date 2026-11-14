# Feature removal plan (Firebase stack)

Date: 2026-11-14. Analysis only: no code was changed.

**Scope.** This plan covers:
- `apps/lms-spa`;
- the Firestore paths of `apps/api`;
- `functions-lms`.

`functions-lms/app` is rebuilt from `apps/api/app` by `functions-lms/tools/build.py`, so it is never edited by hand.

`apps/web` and the Postgres code paths are out of scope. The VM still runs them, and they are removed after the VM is retired (see the memory note "cleanup sequence"). Where a change touches them, this plan only says so.

**Sources:**
- the live audit (`docs/qa/live-audit/admin.md` §3, `student-and-access.md`, `fixes-nav.md`);
- CodeGraph and grep dependency tracing;
- a dry run of `sync-from-web.mjs` into a scratch folder;
- read-only Firestore REST counts on `billing-f4fe3`.

Paths are relative to the repo root. "Both nav copies" means `apps/lms-spa/spa-overrides/lib/nav/X` **and** `apps/lms-spa/src/lib/nav/X`, which are identical today. After Batch 0 (below), only `src/` exists.

---

## 1. Summary

| # | Feature | Decision | Reason | Size of removal |
|---|---|---|---|---|
| 1 | **Mentoring**: slots, bookings ("Mock interviews"), sessions, feedback, mentor notes, mentee console, résumé *reviews* | **REMOVE** (keep the Résumé builder) | No mentor role exists (`placement_mentor` was folded into Admin). The Admin is not a mentor. The student upsell is a dead end that leads to Billing with no plans. Zero live documents; no `lms_mentor_*` collection exists. | Large. SPA: 7 pages and about 5 components. API: about 3,000 lines across `mentoring/*` and `placement/mentoring.py`. 3 RBAC keys, 3 indexes, about 10 test files. |
| 2 | **Company paths**: student `/app/companies*`, Studio Companies page, `me/company-paths`, `studio/company-paths` | **REMOVE** (keep the `companies` entity) | The student index is a "coming soon" stub. Nothing links to the detail page. No company path data. Placement prep is done through batches. | Medium. 3 SPA pages (plus 2 public ones counted in #4). Edits in `placement/*`, `assessments/studio.py` and `wiring.py`. 2 collections and 3 indexes. |
| 3 | **Corporate enquiries**: `/desk/enquiries*`, `(public)/enquiries`, `POST public/enquiries` | **REMOVE** | Hosting already redirects `/enquiries` to the website contact page. 0 enquiry documents. The open `POST public/enquiries` emails every Admin, which is needless attack surface. | Medium. 3 SPA pages and 5 components. `support/enquiries.py` (372 lines) plus edits in the support repo and specs. 1 index and 1 field override. |
| 4 | **Public SPA pages made dead by Hosting redirects**: `(public)/courses*`, `pricing`, `placement*`, `companies*`, `free-resources`, `status` | **REMOVE** | `firebase.json` (target `lms`) redirects every one of these URLs to the website before the SPA loads. The old landing `(public)/page.tsx` is the only in-app way to reach them. | Medium. 9 pages, about 10 components, the `GET catalog/search` endpoint. |
| 5 | Old landing page `(public)/page.tsx` | **REPLACE** with a redirect route (`/` → `/modules` or `/login`) | A full page load of `/` is already redirected by `src/spa/session.ts`. Only `read/[id]` reaches the page through client-side routing. | Small. |
| 6 | Free diagnostic page `/app/diagnostic` | **REMOVE the page.** Keep the `diagnostic` test kind | It is just `me/tests` filtered to `test_kind=diagnostic`, and Tests already lists those tests. It has no API of its own. | Small. 1 page, `DiagnosticLauncher` and 1 test. |
| 7 | `/admin/question-review` | **REMOVE** | The same `ReviewQueue` component as Studio "Review queue", which Admins can open. | Small. 1 page. |
| 8 | `/admin/notifications` (ADM-011) | **REMOVE** | A placeholder: "Templates can't be edited here yet". No API, no links. Audit item M10 recommends deleting it. | Small. 1 page. |
| 9 | `/app/bookmarks` | **REMOVE** | A placeholder ("not available yet"). No API, no links. | Small. 1 page. |
| 10 | `/app/analytics` | **REMOVE** | Only redirects to `/app/progress`. No links. | Small. 1 page. |
| 11 | `/security/policies` | **REMOVE** | The same `PolicySettings` component as `/admin/policies`, filtered to 8 namespaces. Nothing links to it, and `/admin/policies` shows all namespaces. | Small. 1 page. |
| 12 | Feature flag `risk.fingerprint_collection` | **REMOVE** (one data doc, owner approval) | No code reads it. It was seeded only. | Tiny. 1 Firestore doc, 1 test key. |
| 13 | Learning paths + articles (Trainer "Learning paths" and "Articles"; student `/app/path/my`, `/read/[id]`) | **KEEP** (the owner may switch it off with the `paths` app toggle) | A complete, batch-scoped trainer feature on Firestore: allocation to a batch, pacing, progress. It is visible in the Trainer nav, has 0 data, and fits batch training. See risk R9 for a findability bug. | n/a. A full removal would be large: 8 pages, `paths/*` (3,600 lines), a shared test harness and an env-var startup trap. |
| 14 | AI engine (`modules/ai`: adapters, grading, tutor, AI drafts) | **KEEP-HIDDEN.** Trim the admin page to "Apps" | It has a real Anthropic adapter, and 5 working features call it. The live provider is `fake`. The "Authorized apps" toggles and `require_app_enabled` live in this module and gate 7 other modules. | UI trim only: the AI settings and Usage tabs in `AIAdmin.tsx`. |
| 15 | Online gateway (Razorpay): 8 `/finance/*` pages, student Billing, My access, orders, checkout, subscriptions, coupons, invoices, Cashfree skeleton | **KEEP-HIDDEN** | Rule: the owner may connect it, and entitlements and paid lessons depend on it. The Cashfree code is already off twice (by setting and by flag). | Small UX fixes only (§3.15). |
| 16 | Commerce and entitlement jobs (`commerce.*`, `entitlements.expiry`) | **KEEP** | Reconciliation already skips when no gateway is connected (`commerce/tasks.py:92-101`). Three jobs are already idle-gated in `core/scheduler.py` `GATES`. | None. |
| 17 | Risk rules, Reports, Unblock reviews (L3–L4), Restrictions, Cases, Incidents, Security overview | **KEEP-HIDDEN** (rules, reports, unblock reviews) / **KEEP** | Safety and security tools. They hold live data (50 risk rules, 26 signals, 19 user states). The Security overview links to them. | None. |
| 18 | `/security/approvals` | **KEEP** | The engine kill-switch ratification banner links to it (`EngineControls.tsx:52`). | None. |
| 19 | Break-glass, Feature flags | **KEEP** (hidden; linked from Settings › System status) | Emergency and ops tools, and the audit trail. | None. |
| 20 | `/modules`, `/continue`, `/sso/website`, `modules/hub` | **KEEP** | The core sign-in landing flow. `GET public/integrations` drives the `requires: "payments"` nav gating. | None. |
| 21 | Student Notifications page | **KEEP-HIDDEN in the nav** | It is the only target of the header bell (`NotificationBell.tsx:17`). | None. |
| 22 | Profile & settings `/app/settings/profile` | **KEEP** | The shared account page for every role (`ACCOUNT_SETTINGS_HREF`). | None. |
| 23 | `/app/onboarding` | **KEEP-HIDDEN** | A working "Get started" page with no links. Cheap to keep. Delete it with `GetStarted` if the owner prefers. | (optional, 1 page) |
| 24 | `/app/account-status`, `/app/guardian-consent` | **KEEP** | API redirect targets (`status_url`, `guardian_flow_url`). | None. |
| 25 | Demo seeds (`app/seeds/*_demo.py`) and fake adapters | **KEEP**, trimmed with features 1–3 | CLI-only and restricted to `APP_ENV` local/dev/test. Fake adapters are config-switched behind the production startup gate. | Trim the enquiry, company-path and mentoring helpers. |
| 26 | `showcase` Hosting target (`apps/web/out/showcase`) | Out of scope (note only) | Built from `apps/web`. Retire it with the VM cleanup. | None. |
| 27 | `sync-from-web.mjs` | **RETIRE** (Batch 0) | See §5. | Small. |

**Totals if every REMOVE is done:**
- SPA pages: 207 → **179**. That is −28: mentoring 7, company paths 3, dead public pages 9, enquiries 3, diagnostic, question review, admin notifications, bookmarks, analytics and security policies 1 each.
- Firestore collections whose code is removed: **none of them holds data**.

---

## 2. Live Firestore check (read-only, 2026-11-14)

`billing-f4fe3` has 64 root collections, 56 of them `lms_*`. `listCollectionIds` returns only collections that have documents. So **no** `lms_mentor_*`, `lms_interview_feedback*`, `lms_resume*`, `lms_learning_path*`, `lms_path_*`, `lms_company_path*` or `lms_corporate_enquiries` collection exists live.

These live documents would become orphaned. Dropping them needs owner approval, and leaving them is harmless:

| Collection | Doc | Orphaned by |
|---|---|---|
| `lms_support_counters` | `corporate_enquiry` (1 of 2 docs) | #3 Enquiries |
| `lms_feature_flags` | `risk.fingerprint_collection` (1 of 4) | #12 |
| `lms_permissions` | `mentor.slot.manage` (c900102a…), `mentor.feedback.write` (a7f951f1…), `mentor.notes.read` (a5d20d83…) | #1 Mentoring |
| `lms_role_permissions` | 4 docs for the 3 mentor keys (`mentor.notes.read` ×2, the others ×1) | #1 Mentoring |
| `lms_permissions` / `lms_role_permissions` | `notification.template.manage` (1 + 1) | optional, #8 (key unused; keep is fine) |

**Collections whose code goes but which hold 0 documents** (nothing to drop):
- `lms_mentor_slots`, `lms_mentor_slot_times`, `lms_mentor_slot_live`, `lms_mentor_bookings`, `lms_mentor_booking_idem`;
- `lms_interview_feedback`, `lms_interview_feedback_by_booking`, `lms_mentor_notes`;
- `lms_resume_reviews`, `lms_resume_review_open`;
- `lms_company_paths`, `lms_company_path_steps`;
- `lms_corporate_enquiries`.

**Composite indexes to delete in production** once the root `firestore.indexes.json` is updated (`firebase deploy --only firestore:indexes` lists them; delete on prompt, or leave them, which is harmless):
- `lms_mentor_slots` ×2 and `lms_mentor_bookings` ×1;
- `lms_company_paths` ×1 and `lms_company_path_steps` ×2;
- `lms_corporate_enquiries` ×1 plus the field override on `message`.

Other notes:
- `lms_reconciliation_runs` (47 docs) are from before the "skip reconciliation without a gateway" fix. Not orphaned; they can be purged at will.
- No `lms_permissions` docs exist for `path.*`/`company_path.*` removal, because both are kept.

---

## 3. Per-feature checklists

Conventions:
- **SPA** paths are under `apps/lms-spa/src/`.
- **API** paths are under `apps/api/`.
- Line numbers are from 2026-11-14. Re-check them before editing.
- Routers are auto-discovered (`app/main.py:35`), and models and store specs load by `pkgutil`. So deleting a module file needs no registration edit, except where a step says so.
- `src/spa/routes.gen.tsx`, `scripts/routes-report.json` and `PAGE_COUNT` are generated by `scripts/gen-routes.mjs`. Never hand-edit them. Update the assertion in `src/spa/spa.test.tsx:35` (now 207) once, in the integration batch.

### 3.1 Mentoring → REMOVE (keep the Résumé builder)

**Key fact:** the Résumé builder lives inside the mentoring module on both sides.
- SPA: `app/app/resume/page.tsx` imports `features/mentor/student/Resume.tsx`.
- API: `/me/resumes*` are in `modules/mentoring/router.py:136-175`.

So **keep the package `app/modules/mentoring` and the store module name `"mentoring"` as the résumé home**, and strip everything else out of it. Renaming the package would touch:
- `core/firestore/backend.py:45` `MODULES`, which rejects unknown `TD_STORE_*` keys at startup;
- `TD_STORE_MENTORING` in `functions-lms/.env.billing-f4fe3:64`, `.env.example:64` and `tools/emulate.ps1:32`;
- `admin/privacy.py:295` `REQUIRED_ERASURE_MODULES`.

Get that wrong and the API fails to start, or erasure never completes. Do not rename now.

**SPA, delete:**
- `app/mentor/` (`layout.tsx`, `error.tsx`, and pages `page.tsx`, `resume-reviews/`, `sessions/[session_id]/`, `slots/`, `students/`, `students/[user_id]/`): 6 pages.
- `app/app/mentoring/page.tsx`: 1 page.
- `features/mentor/components/{Mentor,ResumeReviews,Slots,shared}.tsx` and `mentor.test.tsx`.
- `features/mentor/student/Mentoring.tsx`.
- `spa-overrides/features/mentor/student/Mentoring.tsx`. All of `spa-overrides` goes in Batch 0 anyway.

**SPA, keep and edit (résumé):**
- Move `features/mentor/student/Resume.tsx` and the parts of `features/mentor/lib/{api,types}.ts` it needs to `features/resume/`.
  - Keep from the lib: `send`, `isCode`, and the types `Certification`, `PdfUpload`, `Resume`, `ResumeContent`, `ResumeList`, `TemplateKey`.
  - Drop `ReviewPanel`/`REVIEW_LABEL` (lines 260-323) and the "Mentor review" card (366-373).
- `features/mentor/student/student.test.tsx`: drop `describe("StudentMentoring")` and keep `describe("StudentResume")`.
- `app/app/resume/page.tsx:3` (import path) and `:11` (description "ask a mentor to review it").
- `app/app/interview-prep/page.tsx:11`: the description mentions mock interviews.

**SPA, links:**
- `features/dashboard/components/StudentDashboard.tsx:188`: the "Mock interviews" quick action.
- `features/dashboard/components/LearnerHubs.tsx:200`: the Interview prep card. At `:201` remove "ask for a review". The grid at `sm:grid-cols-3` may need to become 2 columns.

**SPA, nav (integration batch):** both copies of `portals.ts`:
- `:18` the `"mentor"` `PortalKey`;
- `:86` and `:95` comments;
- `:123-127` the four Mentoring items;
- `:193` `/app/mentoring`;
- `:234-241` the `mentor` portal entry.

Also:
- `icons.ts:13-16` and `:59`;
- `portals.test.ts:48-50`, `:97`, `:116` and `:124`.

**SPA, cosmetic (optional):**
- `app/robots.ts:11`;
- `lib/firebase/analytics.ts:15,63`;
- `features/auth/components/shared.tsx:17`;
- `features/public/content/legal.ts:237`.

Leave `Display.tsx:129`, `batches/lib/delivery.ts:13` and the `AccessList` quota rendering alone.

**API:**
- `app/modules/placement/mentoring.py`: delete it (the mentor console `GET /mentor/students*`). It is the only module that imports the mentoring service.
- `placement/router.py`: the import at `:28` and the `mentor` entry in the router tuple at `:580`.
- `mentoring/router.py`: delete the student mentoring routes (`:68-133`), the `/me/resumes/{id}/review-requests` route (`:177-190`) and the mentor router (`:197-332`). Keep `/me/resumes*` and the erasure provider registration (`:335-343`, trimmed).
- `mentoring/service.py`:
  - delete the permission constants (`:54-56`), scopes, quota and booking JSON (`:110-327`), slots, bookings, sessions, feedback and notes (`:457-1367`), and the review queue (`:1673-1794`);
  - keep the résumé code (`:1370-1667`), with the quota and review hooks removed from `resume_json` and `request_review`;
  - drop `entitlements.require_package`/`consume` and the `quota` field from `GET /me/resumes`.
- `mentoring/service_fs.py`: delete `:47-638` and `:711-805`. Trim `erase_user` (`:808`) to résumés.
- `mentoring/repo_firestore.py`: delete the booking, slot, feedback and note methods.
- `mentoring/schemas.py:36-118`: delete.
- `mentoring/models.py`: `MentorSlot`, `MentorBooking`, `InterviewFeedback` and `MentorNote` are Postgres models (out of scope). Leave them; the VM still imports them.
- `mentoring/public.py`: delete. It only served `placement/mentoring.py`.
- `mentoring/privacy.py`: keep it, résumé-only.
- `mentoring/store_specs.py`: drop the collections `mentor_slots`, `mentor_slot_times`, `mentor_slot_live`, `mentor_bookings`, `mentor_booking_idem`, `interview_feedback`, `interview_feedback_by_booking`, `mentor_notes`, `resume_reviews` and `resume_review_open`, with their `register_mapping` entries (`~:134-175`, `~:186-196`).
  - Keep `resumes` and `resume_versions`.
  - **Pitfall:** `:76` registers `RESUMES` with `read_permission=PERM_FEEDBACK` (`mentor.feedback.write`). Set it to `None` (owner-only).
- `mentoring/firestore.indexes.fragment.json`: remove `lms_mentor_slots` ×2 and `lms_mentor_bookings`. Keep `lms_resumes`.
- Root `firestore.indexes.json:1373-1414` (integration batch). Keep `:1415-1428` `lms_resumes`.
- RBAC `rbac/catalogue.py` (integration batch):
  - remove `:265-267` (`mentor.slot.manage`, `mentor.feedback.write`, `mentor.notes.read`);
  - remove `:119` (`_MODULE_PREFIX "mentor"`);
  - add the 3 keys to `REMOVED_PERMISSIONS` (`:152`);
  - keep `placement_mentor` in `REMOVED_ROLES` (`:44`, `:85`).
- **Cut from `placement`, optional and done by the same agent:** `placement/practice.py:1058-1114` `practised_company_readiness` has no caller after this. It also goes with §3.2.
- **No change** in:
  - `wiring.py`, outbox handlers, notification templates or consumers (the `mentoring.*` events have no consumer);
  - `register_periodic` or `schedules.json`;
  - retention defaults.
- **Leave dormant:** `entitlements` `QUOTA_FEATURES` (`mentor_sessions`, `resume_reviews`), `commerce/service.py:1247-1260` (refund deduction; 0 without bookings) and `seeds/commerce_demo.py:60-66`.

**Tests (`apps/api/tests`):**
- Delete:
  - `mentoring/test_mentoring.py`, `test_mentor_readiness.py`, `test_fs_registers.py` and `test_mentoring_firestore_matrix.py` (or trim it to the résumé suite);
  - `parity/test_mentoring_parity.py`;
  - `placement/test_stage10_endpoints.py`.
- Trim:
  - `mentoring/test_fs_repo.py`: drop `:99-235`; keep the résumé versions and `erase_user` tests;
  - `mentoring/test_resumes.py`: drop `test_review_request_queue_and_feedback` (`:103`);
  - `mentoring/fs/test_mentoring_http.py`: drop `:100` (slots); trim `test_resumes_and_review`;
  - `rbac/test_rbac.py:136`;
  - optionally `authz/matrix.py:61`.
- Keep: `learning/test_privacy_erasure.py`, `admin/test_w2a_flags_erasure.py:48-51` (the provider still exists) and `platform/test_rows.py:71`.

**Docs:**
- `docs/api-specification.md` §13.1;
- `docs/role-permission-matrix.md`;
- `docs/database-schema.md`, `docs/database-erd.md`;
- `docs/product-requirements.md` (STU-013, MEN-001..005);
- `docs/sitemap.md`;
- `docs/firebase/agents/data-learning.md`, `docs/firebase/MIGRATION-PLAN.md`;
- `docs/privacy-and-data-retention.md`;
- `docs/implementation-status.md`;
- `docs/audit/00-feature-inventory.md`;
- `docs/qa/live-audit/fixes-nav.md`.

QA specs: `qa/live-e2e/tests/audit-admin.spec.ts:22,46`, `audit-staff.spec.ts:22`, `audit-student.spec.ts:17,29`, `audit-responsive.spec.ts:16-17`.

**VM:** the VM's `apps/web` shows `/mentor/*` and `/app/mentoring` *visibly*. If the VM image is ever rebuilt from this repo, those pages would 404 against the API. The VM is not rebuilt during cleanup, so this is acceptable. Do not add a Postgres migration.

### 3.2 Company paths → REMOVE (keep the `companies` entity and `company_path.manage`)

**SPA, delete:**
- Pages: `app/app/companies/page.tsx`, `app/app/companies/[slug]/page.tsx`, `app/studio/companies/page.tsx` (3). The 2 public `companies` pages are in §3.4.
- Components and libs:
  - `features/practice/components/CompaniesIndex.tsx`, `CompanyPathView.tsx`;
  - `features/practice/lib/api.ts:61` (`companyPath`);
  - `features/practice/lib/types.ts:89` (`company_step`) and `:191-215`;
  - `features/studio/components/Companies.tsx`.
- Tests: `features/studio/components/studio-authoring.test.tsx` (import `:5`, block `~:536-600`).
- Links: `LearnerHubs.tsx:202` (the Interview prep "Company paths" card).
- Nav (integration batch): `portals.ts:195` and `:254`; `icons.ts:61` and `:88`; optionally `staff-portal.test.tsx:269`.
- Leave dormant: the `company_path` item types in `FinanceCatalog.tsx:66`, `catalog/lib/types.ts:107`, `trainer/lib/types.ts:18` and `studio/lib/types.ts:221`.

**API:**
- `placement/router.py`: remove `PUT studio/company-paths/{id}` (`:440-458`) and `GET me/company-paths/{slug}` (`:572-576`). Keep `GET`/`POST studio/companies`.
- `placement/practice.py`:
  - remove `company_step` mode (`:94-125`, `:136-145`, `:208`);
  - remove `my_company_path` (`:986-1030`);
  - remove `practised_company_readiness` and `_fs_…` (`:1058-1114`).
- `placement/schemas.py:185-187`: `PracticeStart.mode`/`company_path_step_id`. Also `CompanyPathPut` (`~:160-180`).
- `placement/bank.py:1425-1600`: path_steps, path_out, `paths` in `list_companies`, put_company_path, `_fs_put_company_path`.
- `placement/repo_firestore.py:586-640`: paths, get_path, path_steps, path_ids_with_test, get_step, put_path. Also `PATH_PERM` at `:100`.
- `placement/store_specs.py:65-66, 87-88, 180-181`: the `company_paths` and `company_path_steps` collections and their mappings.
- `placement/firestore.indexes.fragment.json`: `lms_company_paths` (1) and `lms_company_path_steps` (2). Root `firestore.indexes.json` goes in the integration batch.
- **Entitlement hook, `wiring.py:90-97`:** `test_parents` returns only the course parents.
  - Delete `company_paths_with_test` and `get_company_path` in `placement/public.py:138-145`, `:154-159`, `:288`, `:292` and the doc row at `:19`.
  - This also removes one Firestore query from every test access check.
- `assessments/studio.py:79, 178-181, 198, 207, 245`: reject a non-null `company_path_id`, or drop the reference check.
- `assessments/datastore.py:72-76`: the `"CompanyPath"` resolver.
- Leave dormant: the `company_path` field in `assessments/schemas.py:102`, the entitlement resource type (`entitlements/service.py:59,74`, `entitlements/router.py:46`, `core/access.py:35`), the commerce item_type and the analytics entity check. They are needed only to avoid schema churn.
- Postgres models `placement/models.py:51-80`: leave them.
- Seeds: `app/seeds/placement_demo.py:266-330` (the demo company path). Leave `commerce_demo.py:59`.
- RBAC: **keep** `company_path.manage`. It is the write permission for `companies` (`placement/store_specs.py:85-86`).

**Tests:**
- `placement/test_placement.py:412-451`;
- `placement/test_audit_fixes.py:125-184`;
- `placement/fs/test_placement_firestore.py:24, 249-269, 390`;
- `placement/fs/test_practice_firestore.py:21, 159-179`;
- `placement/fs/test_placement_http_firestore.py:135-152`;
- `assessments/fs/test_public_api_firestore.py:48-57, 109-110, 133`;
- `analytics/test_audit_fixes.py:242`;
- the comment in `assessments/fs/test_assessments_http_firestore.py:143`.

**Docs:** `docs/firebase/agents/data-content.md`, `data-assess.md`, `docs/sitemap.md`, `docs/product-requirements.md`. QA: `audit-admin.spec.ts:33`, `audit-responsive.spec.ts:16,18`, `audit-staff.spec.ts:14`, `audit-student.spec.ts:17`.

### 3.3 Corporate enquiries → REMOVE

**Before deleting:** confirm in the separate website repo that nothing posts to `/api/v1/public/enquiries`. The `functions-lms/lms_edge/public.py` bridge covers only admissions and course status, so nothing in this repo does.

**SPA:**
- Delete pages: `app/desk/enquiries/page.tsx`, `app/desk/enquiries/[enquiry_id]/page.tsx`, `app/(public)/enquiries/page.tsx` (3).
- Delete components and tests:
  - `features/support/components/Enquiries.tsx`, `enquiries.test.tsx`;
  - `features/public/components/EnquiryForm.tsx`, `enquiry.test.tsx`;
  - `features/public/lib/enquiries.ts`.
- Edit:
  - `features/support/lib/types.ts:6-10`: drop `"corporate_enquiry"` from `DESK_CATEGORIES`. The API rejects it with a 422 today, which is an existing bug.
  - `features/support/components/support.test.tsx:115-116`.
  - `features/public/lib/seo.ts:9`.
  - `features/public/public-pages.test.ts:25`.
  - `app/(public)/page.tsx:124`. The page is replaced anyway (§3.5).
- Nav (integration batch): `portals.ts:144-145`, `icons.ts:31`, `portals.test.ts:97`; check `PortalShell.test.tsx`.

**API:**
- Delete `app/modules/support/enquiries.py`. That removes:
  - the routes `POST public/enquiries`, `GET support/enquiries` and `GET`/`PATCH support/enquiries/{id}`;
  - the rate limits;
  - the template key `support.corporate_enquiry_received`.
- `support/router.py`: docstring `:1-2`; `:1321-1324` (the import and `include_router`).
- `support/repo_firestore.py`:
  - docstring `:3-12`;
  - imports `:37-38`;
  - `EnquiryRow` `:175-208`;
  - methods `:472-522`.
- `support/store_specs.py`:
  - docstring `:10-14`;
  - `ENQUIRIES` `:27` and `ENQUIRY_SEQ` `:30`;
  - `register_collection` `:35`;
  - `ENQUIRY_FIELDS`/`enquiry_doc` `:112-130`;
  - mapping `:149-151`;
  - the counters mapping `:152-162`: keep only `support_ticket` in the `UNION ALL`.
- `support/models.py:81-99` `CorporateEnquiry` is Postgres. Leave it.
- `app/seeds/company_demo.py`: `:23`, `:67`, `:86`, `_enquiry()` `~:498-520`, `made["enquiries"]` `~:535`.
- Root `firestore.indexes.json` (integration batch): composite `lms_corporate_enquiries` `~:395-408` and the field override `~:2463-2467`. Support has no fragment file.
- No RBAC keys (it reuses `user.read`/`ticket.assign`), no outbox, privacy, retention or schedule entries.

**Tests:**
- Delete `support/test_enquiries.py`.
- `support/helpers.py:12, 63-75`.
- `support/test_firestore_store.py:89`, the enquiry half of `:105-131`, and `:205`.
- `seeds/test_dev_fixtures.py:373, 430`.

**Keep:** the `/enquiries` Hosting redirect (`firebase.json` and `functions-lms/tools/sync_hosting.py:78`).

**Docs:** `docs/api-specification.md`, `sitemap.md`, `privacy-and-data-retention.md`, `database-schema.md`, `database-erd.md`, `single-company/ws5.md`, `implementation-status.md`, `README.md`. QA: `audit-admin.spec.ts:25,42`, `audit-staff.spec.ts:20`, `audit-student.spec.ts:27`, `audit-responsive.spec.ts:17`.

**Data:** `lms_support_counters/corporate_enquiry` (needs owner approval).

### 3.4 Public pages made dead by Hosting redirects → REMOVE

**Pages** (9):
- `app/(public)/courses/page.tsx`, `courses/[slug]/page.tsx`;
- `pricing/page.tsx`;
- `placement/page.tsx`, `placement/[subject]/[topic]/page.tsx`;
- `companies/page.tsx`, `companies/[slug]/page.tsx`;
- `free-resources/page.tsx`;
- `status/page.tsx`.

**Components that become dead:**
- `features/catalog/components/CourseDetail.tsx`, `CatalogFilters.tsx`;
- `PricingPlans.tsx` (tests `catalog.test.tsx:108`, `markdown-verify.test.tsx:4`);
- `features/public/components/{CompanyHubs,PlacementHub,FreeResources,ServiceStatus}.tsx` (tests `public.test.tsx:175-260`);
- `loadCourseDetail` in `features/catalog/lib/server.ts`;
- `CourseGrid`/`CourseCard` in `CatalogParts.tsx`. Keep `ServerErrorState`, which `verify/[certificate_id]` uses.
- `ReadyDto`/`FreeResourceDto` in `features/public/lib/types.ts`;
- `PUBLIC_SITEMAP_PATHS` in `seo.ts`;
- `public-pages.test.ts:24-38`.

**Check before deleting:** `CourseAccess.tsx:39-44` builds `/courses/<slug>` only for signed-out users. In-app, `CourseOverview` always passes `signedIn`, so the path is never used. Keep the component.

**API:**
- Remove `GET catalog/search` (`catalog/router.py:126`, `cat_07`) and its tests.
- **Keep:**
  - `GET catalog/free-resources` (optional; studio resources still publish there);
  - `GET health/ready` (infra probe);
  - `catalog/courses`, `catalog/courses/{slug}`, `placement/subjects`, `commerce/products` (used by live pages).

QA: `audit-responsive.spec.ts:22`. Hosting redirects stay as they are.

### 3.5 Old landing page `(public)/page.tsx` → REPLACE

Replace the page with a component that redirects to `/modules` (signed in) or `/login`, reusing the `homeRedirect` logic in `src/spa/session.ts:82`. Or change `app/read/[id]/page.tsx:21` from `<Link href="/">` to a plain `<a>` and delete the page. With the replacement option, the page count is unchanged.

### 3.6 Free diagnostic page → REMOVE

- Delete `app/app/diagnostic/page.tsx`.
- Remove `DiagnosticLauncher` (`LearnerHubs.tsx:174-192`) and its test (`hubs.test.tsx:43-~58`, import `:4`). Keep `DiagnosticStep`.
- `StudentDashboard.tsx:187`: point the "Free diagnostic" quick action at `/app/tests`.
- Nav (integration batch): `portals.ts:191`, `icons.ts:57`.
- QA: `audit-responsive.spec.ts:16`, `audit-student.spec.ts:16`.
- No API change. Keep the `diagnostic` `TestKind`.

### 3.7–3.11 Small page removals (no API changes)

| Page | Delete | Also edit |
|---|---|---|
| `/admin/question-review` | `app/admin/question-review/page.tsx` | nav `portals.ts:119-120`, `portals.test.ts:97`; QA `audit-admin.spec.ts:21`, `audit-responsive.spec.ts:17`. Optional: in `/studio/review`, pass `mode="admin"` when `studioAccess()` is `"admin"`, so Admin-only users don't get question links that bounce. Keep the `mode="admin"` branch of `ReviewQueue` for that. |
| `/admin/notifications` | `app/admin/notifications/page.tsx` | the `portals.ts:7-8` comment; QA `audit-admin.spec.ts:29`; `docs/sitemap.md:266`; `fixes-nav.md:29` (it said "not deleted": record the new decision). Keep the RBAC key (it has a live doc; harmless). |
| `/app/bookmarks` | `app/app/bookmarks/page.tsx` | QA `audit-student.spec.ts:20` |
| `/app/analytics` | `app/app/analytics/page.tsx` | QA `audit-student.spec.ts:20`; `portals.test.ts:29` can stay |
| `/security/policies` | `app/security/policies/page.tsx` | the `portals.ts:98-99` comment; QA `audit-admin.spec.ts:29`. Keep `PolicySettings`'s namespace-filter prop (other callers) |

### 3.12 Flag `risk.fingerprint_collection` → REMOVE

- Delete the data doc in `lms_feature_flags` (owner approval).
- Change the key used in `tests/admin/test_w2a_flags_erasure.py:14`.
- Leave the Postgres seed in `migrations/versions/admin_0001_admin.py:86`.
- Do not confuse it with the policy key `risk.fingerprint.enabled`, which stays.

### 3.13 Learning paths → KEEP (no removal)

Decision record:
- It is a working, batch-scoped trainer feature (`paths/service.py`: `require_allocate_batch`, pacing, progress).
- It runs on Firestore with `TD_STORE_PATHS=firestore` and is gated by the `paths` app toggle.
- If the owner does not want it, switch it off with Admin › AI & apps › Authorized apps › Learning paths. No code is needed.

A future full removal has two traps:
- `core/firestore/backend.py:48` `MODULES` together with `TD_STORE_PATHS` in the env files: remove the env var first, otherwise the API fails at startup.
- `tests/paths/fs/http_harness.py` is shared by analytics, catalog, entitlements and learning tests. It must be moved, not deleted.

### 3.14 AI → KEEP-HIDDEN; trim the admin page (audit M8)

- `features/ai/admin/AIAdmin.tsx:58-64`: drop the "AI settings" and "Usage" tabs, or show them only when `ai_simulated === false` (a provider is configured). In the Authorized apps section, hide the `category === "ai"` toggles under the same condition.
- Rename the nav label to "Apps" (integration batch, `portals.ts:157`).
- Tests: `features/ai/ai.test.tsx:283+` and `portals.test.ts:48`.
- Keep `ai/router.py` (`/admin/ai-settings`, `/admin/ai-usage`), the adapters, `/admin/apps`, `/me/enabled-apps` and `useNavApps`.
- **Owner decision, not cleanup:** set `AI_PROVIDER=disabled` instead of `fake` and change the default grading engine from `pure_ai`. The affected lines are `learning/structured.py:588, 905` and `AllocateDialog.tsx:149, 254`. Today, a trainer choosing the default engine gets fake AI marks.

### 3.15 Online gateway → KEEP-HIDDEN, UX fixes only (optional, in the integration batch)

- `portals.ts:197-198`: change `/app/billing` and `/app/access` from `hidden: true` to `requires: "payments"`, so they appear when Razorpay is connected. My access also lists admissions-granted entitlements, so the owner may prefer to keep `/app/access` listed.
- `StudentDashboard.tsx:196-201`: show the "Access & billing" card only when `payments` is connected, or link it to `/app/access` only.
- No change to `/finance/*`, the commerce API, jobs, RBAC (`payment.*` is used by Admissions) or Cashfree.

---

## 4. Dependency risks

| ID | Risk | Mitigation |
|---|---|---|
| R1 | **The sync script undoes SPA deletions.** `npm run sync` wipes `src/` (except `src/spa`) and recopies `apps/web/src`. Every page deleted only in the SPA returns. | Batch 0 retires sync before any deletion (§5). |
| R2 | **API startup.** `core/firestore/backend.py` `MODULES` rejects unknown `TD_STORE_*` keys, and the deployed env sets `TD_STORE_MENTORING` and `TD_STORE_PATHS`. | Keep the `mentoring` module name (résumé home) and keep paths. Do not touch `MODULES` or the env files in this cleanup. |
| R3 | **Privacy erasure.** `admin/privacy.py:295` requires a `mentoring` erasure provider. | Keep `mentoring/privacy.py`, résumé-only. |
| R4 | **Résumé builder** lives in the mentoring module (SPA and API). Its read permission is `mentor.feedback.write`. | Move the SPA files to `features/resume/`, trim the API in place, and set `RESUMES` `read_permission=None`. Keep the `test_resumes*` suites green. |
| R5 | **Entitlement access path.** `wiring.py` `test_parents` calls `placement.company_paths_with_test` on every test access check. | Cut the edge in `wiring.py` in the same commit that deletes the function. Run the entitlements and assessments tests. |
| R6 | **Contract test.** `src/features/__contract__/api-paths.test.ts` fails if the SPA still calls a removed endpoint. | Feature batches delete SPA callers and API routes together. The integration batch regenerates OpenAPI (`apps/api/app/scripts/export_openapi.py` → `apps/api/openapi.json`) and `src/lib/api-types/schema.d.ts`. After Batch 0, the contract test reads the API spec directly. |
| R7 | **Deploy order.** If the API is deployed before the SPA, old SPA bundles in open tabs call removed routes. Those pages are hidden, so the impact is tiny. | Deploy the SPA (Hosting) first, then the functions (`functions-lms/tools/build.py`, then deploy), then indexes. |
| R8 | **The VM** still runs `apps/web` and `apps/api` on Postgres. Its Mentoring and enquiry pages are *visible* there. | Do not redeploy the VM from the cleaned repo. Postgres models and migrations stay (`mentoring_0001` is a `depends_on` of `orgs_0003`). |
| R9 | **Paths findability bug** (not a removal). The student "My paths" item is `hidden`, and the student dashboard has no link. A student allocated a path can only reach it from `/app/path`. | Unhide `/app/path/my` and rely on the `paths` `appKey`, or add a dashboard card when allocations exist. Owner decision. |
| R10 | **Shared hot files** (nav, `LearnerHubs`, `StudentDashboard`, the root index file, the RBAC catalogue, OpenAPI, QA specs, docs) are touched by several features. | Each hot file has one owner per batch (§6). |
| R11 | **Stale live RBAC docs** (`mentor.*` in `lms_permissions`/`lms_role_permissions`). | Harmless once the routes are gone. `REMOVED_PERMISSIONS` stops the reseed. Deleting the docs needs owner approval. |
| R12 | **Old composite indexes** stay in production until deleted. | Harmless. Delete them on the `firestore:indexes` deploy prompt, with owner approval. |

---

## 5. sync-from-web handling → retire sync; `apps/lms-spa/src` becomes the source of truth

**What the script does** (`apps/lms-spa/scripts/sync-from-web.mjs`, run by `npm run sync`):
1. It deletes everything in `src/` except `src/spa/`.
2. It copies `apps/web/src/**`, minus `EXCLUDE` (middleware, `app/api`, `app/college-portal`, `lib/bff`, `lib/college-portal`, `route.ts`).
3. It wraps async server components.
4. It overlays `spa-overrides/**`, which is 75 files today.
5. It copies `apps/web/public` and `apps/web/openapi`.

**Dry run (2026-11-14, into a scratch folder).** The sync output matches the current `src/` except for two files, which were edited directly in `src/` and **would be lost**:
- `features/commerce/components/OrderStatus.tsx`: pause polling while the tab is hidden;
- `features/commerce/components/commerce.test.tsx`.

So sync still works, but it has already started to drift: work is landing in `src/` that sync silently reverts.

**Why sync should be retired rather than given an exclusion list:**
- **`apps/web` is frozen.** It is the VM's frontend, out of scope, and deleted after the VM is retired. Mirroring removals into `apps/web` would change the VM's UI and break the scope rule.
- **Most removals edit shared files.** For example, `LearnerHubs.tsx` loses three cards and `StudentDashboard.tsx` loses quick actions. `EXCLUDE` only drops whole paths, so each edited web file would need a new full-copy override. That would roughly double the 75-file override set and the same-content duplication.
- **Every recent SPA change is already override-plus-src duplication** (`fixes-nav.md`: "every changed file under `src/` is also in `spa-overrides/`"). That doubles the edit surface for every agent and is the source of the drift above.

**Batch 0 steps** (one agent, before anything else):
1. Run the dry run again; it must show only the 2 commerce files. Keep `src/` as is (src wins).
2. `apps/lms-spa/package.json`:
   - Remove the `sync` script, or replace it with one that exits non-zero with the message "retired: edit src directly (docs/cleanup/feature-removal-plan.md §5)".
   - Keep `gen:routes` and `prebuild`, which run `gen-routes.mjs`, `gen-static.mjs` and `copy-monaco.mjs`.
3. Delete `apps/lms-spa/scripts/sync-from-web.mjs` and `scripts/sync-report.json`. Then delete `apps/lms-spa/spa-overrides/` after a `diff -rq spa-overrides src` that shows every override is identical to its `src` copy (true today).
4. **OpenAPI source.** `apps/lms-spa/openapi/` was copied from `apps/web/openapi`. Make the contract test read `apps/api/openapi.json` (the API's own export), or add an `npm run openapi` step that copies it from `apps/api`. Either way, `apps/web/openapi` is no longer in the chain. Check `src/features/__contract__/api-paths.test.ts` and `vite.config.ts`/`tsconfig.json` aliases for the path.
5. **Public assets.** `apps/web/public` was copied to `apps/lms-spa/public`. The copies are already in place; from now on only `apps/lms-spa/public` is edited. `copy-monaco.mjs` is unchanged.
6. **Keep** `src/spa/async.tsx` (`asyncComponent`). The already-wrapped ex-server components still use it, so leave the wrappers alone.
7. Update `package.json` `description`, `docs/firebase/agents/spa.md` and the `fixes-nav.md` convention note: "edit `src/` only; `spa-overrides` is gone".
8. Run `npm run typecheck`, `npm test` and `npm run build`. Expect no diff in `dist` routes.

**Fallback,** if the owner wants to keep sync until the VM is retired: add every deleted path from §3 to `EXCLUDE` (whole files and folders), and put the edited shared files in `spa-overrides` as full copies. This is workable, but every agent has to edit two trees, so it is not recommended.

---

## 6. Batches

Rules:
- Each batch ends green (`apps/api`: `pytest`; `apps/lms-spa`: `npm run typecheck && npm test`).
- Within a batch, agents own disjoint files. **Hot files** belong only to the integration agent: both nav copies (gone after Batch 0), `spa.test.tsx`, `routes.gen.tsx`, root `firestore.indexes.json`, `rbac/catalogue.py`, OpenAPI files, `schema.d.ts`, `qa/live-e2e/**` and `docs/**`.
- Feature agents leave those alone and list the lines they need changed in their hand-off.
- The feature agents' intermediate state may fail `portals.test.ts`/`PAGE_COUNT` until the integration agent runs. Merge Batch 1 as one change.

### Batch 0: retire sync (1 agent, serial, small)
§5 steps 1–8. Owns `apps/lms-spa/package.json`, `scripts/sync-from-web.mjs`, `spa-overrides/**`, the contract-test spec path, and `docs/firebase/agents/spa.md`.

### Batch 1: feature removals (3 agents in parallel)

| Agent | Features | Owns (exclusive) |
|---|---|---|
| **A: Placement & mentoring** | §3.1 mentoring, §3.2 company paths | SPA: `app/mentor/**`, `app/app/mentoring`, `app/app/companies/**`, `app/studio/companies`, `app/app/resume/page.tsx`, `app/app/interview-prep/page.tsx`, `features/mentor/**` → `features/resume/**`, `features/practice/{components/CompaniesIndex,components/CompanyPathView,lib/api,lib/types}.ts(x)`, `features/studio/components/Companies.tsx`, `studio-authoring.test.tsx`. API: `modules/mentoring/**`, `modules/placement/**` (incl. `firestore.indexes.fragment.json`), `modules/assessments/{studio,datastore}.py`, `app/wiring.py`, `seeds/placement_demo.py`. Tests: `tests/mentoring/**`, `tests/placement/**`, `tests/parity/test_mentoring_parity.py`, `tests/assessments/fs/test_public_api_firestore.py`, `tests/analytics/test_audit_fixes.py`, `tests/rbac/test_rbac.py`, `tests/authz/matrix.py`. |
| **B: Public & support** | §3.3 enquiries, §3.4 dead public pages, §3.5 landing replacement | SPA: `app/(public)/{page.tsx,enquiries,courses,pricing,placement,companies,free-resources,status}`, `app/read/[id]/page.tsx`, `app/desk/enquiries/**`, `features/public/**`, `features/catalog/**`, `features/support/**`, `src/spa/session.ts` (only if reusing `homeRedirect`). API: `modules/support/**`, `modules/catalog/router.py` (`catalog/search`), `seeds/company_demo.py`. Tests: `tests/support/**`, `tests/catalog/**`, `tests/seeds/test_dev_fixtures.py`. |
| **C: Student & admin pages, AI page** | §3.6 diagnostic, §3.7–3.11 small pages, §3.12 flag test, §3.14 AI page trim, §3.15 dashboard card | SPA: `app/app/{diagnostic,bookmarks,analytics}`, `app/admin/{question-review,notifications}`, `app/security/policies`, `features/dashboard/**` (**incl. `LearnerHubs.tsx` and `StudentDashboard.tsx`: removes the Mock interviews, Company paths and Free diagnostic cards and actions for agents A and B**), `features/ai/**`, `features/studio/components/Questions.tsx` (optional admin mode). API tests: `tests/admin/test_w2a_flags_erasure.py`. |

Hand-offs between agents in Batch 1:
- Agent C edits `LearnerHubs.tsx`/`StudentDashboard.tsx` for all features. Agents A and B do not touch `features/dashboard/**`.
- Agent A deletes `placement/mentoring.py` and `practised_company_readiness` in the same change, so no dangling imports remain.

### Batch 2: integration (1 agent, after Batch 1 is merged)
- **Nav:** `src/lib/nav/portals.ts`, `icons.ts`, `portals.test.ts`, `components/shell/PortalShell.test.tsx`, `nav-shell.test.tsx`, `features/staff-portal/staff-portal.test.tsx`, `features/hub/last-page*`. Covers:
  - removing the mentor portal key and items;
  - removing the company, diagnostic, enquiries and question-review items;
  - the AI → "Apps" label;
  - optionally `requires: "payments"` for Billing and My access.
- Run `node scripts/gen-routes.mjs`. Set `src/spa/spa.test.tsx:35` to the new `find src/app -name page.tsx | wc -l`; expect **179** and fix the comment.
- Root `firestore.indexes.json`: remove `lms_mentor_slots` ×2, `lms_mentor_bookings`, `lms_company_paths`, `lms_company_path_steps` ×2, `lms_corporate_enquiries` and its `message` override. It must match the module fragments.
- `rbac/catalogue.py`: remove the 3 `mentor.*` rows and `_MODULE_PREFIX "mentor"`, and add them to `REMOVED_PERMISSIONS`.
- Regenerate `apps/api/openapi.json` and `src/lib/api-types/schema.d.ts`. Run the contract test.
- Rebuild `functions-lms` (`python functions-lms/tools/build.py`). `schedules.json` should not change; no removed feature had a periodic job. `tests/platform/test_schedules.py` confirms it.
- QA specs in `qa/live-e2e/tests/audit-{admin,staff,student,responsive}.spec.ts`, and the docs listed in §3.

### Batch 3: deploy and data (owner-gated)
1. Deploy the SPA, then the functions, then the indexes (R7).
2. Re-run the live audits (`audit-admin`, `audit-staff`, `audit-student`) on Cloud Build.
3. With owner approval, delete the orphaned docs and indexes listed in §2.

Batches 0 and 2 are single-agent and short. Batch 1 is where three agents work in parallel. A fourth agent can join Batch 1 by splitting Agent A into A1 (mentoring) and A2 (company paths). If you do, A2 owns `placement/practice.py` and `public.py`, `wiring.py` and `assessments/*`; A1 owns `placement/mentoring.py` and `placement/router.py:28,580` only. The `router.py` edits are in disjoint hunks but in one file, so merge A1 before A2.
