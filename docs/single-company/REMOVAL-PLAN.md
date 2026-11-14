# Single-company LMS: plan for removing college and multi-organisation features

| | |
|---|---|
| Status | Plan, not started. Nothing in this plan has been applied yet. |
| Date | 2026-11-06 |
| Owner decision | The LMS serves Tech Drona only. Learners are public B2C students who pay through Razorpay. Every college and multi-organisation feature is **removed completely, not hidden**. |
| Dev DB backup | `backups/techdrona-dev-before-college-removal-20261106.dump` (moved out of the repo on 2026-11-14 to `../_backups/techdrona-lms/`, next to the repo folder) |
| Line numbers | Taken from the working tree on 2026-11-06. Re-check them before editing; they drift. |

Paths are relative to the repo root. `api/` means `apps/api/app/`, `mig/` means `apps/api/migrations/versions/`, `web/` means `apps/web/src/` and `tests/` means `apps/api/tests/` unless stated otherwise.

---

## 0. Summary

- **Recommendation: option B, a single invisible company organization.** Keep one `organizations` row with `org_type='internal'` and a fixed id, `COMPANY_ORG_ID`. It owns:
  - batches and batch members,
  - structured assignments, paths and engage activities,
  - trainer-authored tests and question banks.

  Users never see it, pick it or manage it. Everything with a college purpose is deleted: the `/college/**` portal, the `college_coordinator` role, contracts and seats, B2B invoices, invitations and roster import, per-org settings, org reports, lab devices, trusted networks and the `/orgs/**` API. Settings that were per-organisation become platform settings.
- **Why not option A (drop organizations entirely):** about 110 `organization_id` columns across 29 migration files, the RLS families `T`, `TN` and `U`, `app.org_ids()`, `Principal.org_ids` and every scope check would need rewriting. That is weeks of change in security-critical code for no visible benefit.
- **Batches stay** as the company's cohorts. `batches.organization_id` is always `COMPANY_ORG_ID`. Admins manage batches from new `/admin/batches` pages; today only the college portal can.
- **Roles:**
  - `college_coordinator` is removed.
  - A new `evaluator` role is added; it does not exist today.
  - `super_admin` is shown as "Admin".
  - Trainer, Content manager and Student stay.
  - `finance_admin`, `support_agent`, `security_reviewer` and `placement_mentor` stay for now, pending the owner's decision (§7).
- **Execution:** six workstreams. WS1 (RBAC, orgs and identity foundation) lands first. WS2 to WS5 (backend modules) then run in parallel, and WS6 (web, OpenAPI and docs) runs alongside and closes last. Each workstream owns its files and adds its own forward migrations on its own Alembic branch.

---

## 1. Inventory

### 1.1 How organizations are wired today

- **RLS families**, in `api/core/migration_helpers.py:23-40`:
  - `T` = `organization_id = ANY(app.org_ids()) OR app.is_platform()`
  - `TN` = `T`, plus `NULL` meaning a platform row
  - `U` = the user's own rows, plus org rows
  - `O` = the user's own rows only
- **Session settings:** `api/core/db.py:105-160` sets `app.org_ids` and `app.is_platform` for each request.
- **Where `Principal.org_ids` comes from** (`api/core/principal.py:31`): org memberships plus `organization_id` on role grants (`api/modules/sessions/resolver.py:57-95`).
- **Scope chain:** `platform ⊃ organization ⊃ batch`, with `course` as a separate axis (`api/modules/rbac/service.py:4-7,154-205`). `ScopeRef("organization", …)` is used throughout the modules.
- **Users' visibility of each other:** `app.user_visible_in_orgs()` (`mig/orgs_0001_orgs.py:176-186`). The `p_users` and `p_o` policies (`mig/identity_0002_org_visibility.py`) let a caller read any user who shares an organization with them.
- **B2C students today have no organization**, so `org_ids` is empty and they see only their own rows. A student becomes an org member only through an invitation or roster import (`api/modules/orgs/router.py:1020-1088`). Adding someone to a batch requires an existing org membership (`orgs/router.py:1392-1405`, error `not_org_member`).
- **Footprint:**
  - About 110 `organization_id` columns across 29 migration files.
  - About 1,300 `organization_id`/`org_id` references in `api/**`.
  - `app.org_ids()` is used directly in 7 migrations, and through `enable_rls()` in nearly every module.

### 1.2 Backend: what to delete, convert or simplify

Each item is tagged:
- **DEL**: delete; it exists only for colleges.
- **CONV**: convert a per-org setting into a platform setting.
- **SIMP**: collapse an org picker or loop to `COMPANY_ORG_ID`, or to platform.
- **KEEP**: plumbing that stays as it is.

#### orgs (`api/modules/orgs/`)
- **DEL** `lifecycle.py`, the whole file: `/orgs/{id}/suspend` and `/reactivate`, and the `org.suspend` Dual approval.
- **DEL** `csv_import.py`, the whole file: roster CSV import.
- **DEL** these `router.py` routes:
  - `:341` GET `/orgs`
  - `:358` POST `/orgs`
  - `:395` GET and `:402` PATCH `/orgs/{id}`
  - `:420` PATCH `/orgs/{id}/settings`
  - `:444` and `:523` members, `:564` remove member
  - `:639-848` imports
  - `:863-990` invitations
  - `:1005-1238` the public `/invitations/{token}` and `/accept`
  - `:1503` GET `/me/orgs`
  - `:1544` PATCH `/me/orgs/{id}`, the college data-sharing consent
  - The helpers that go with them: `:94-113` `_restriction_visibility`, which reads `org.notify_coordinator_on_restriction`; `:146`, which defaults `org_type="college"`; and `:1015`, the college notice text.
- **KEEP and move** the batch routes `:1240-1500` to `/batches` (list and create) and `/batches/{id}/**`, with no `org_id` in the path. `create_batch` stamps `COMPANY_ORG_ID`.
  - `add_batch_members` must stop rejecting users who are not org members (`:1392-1405`). It should create or reactivate the user's `org_memberships` row in the company org (`member_type='student'`, `source='staff'`).
- **`service.py`:**
  - **SIMP** `get_learner_org_context` `:27-97`. It always returns `COMPANY_ORG_ID`; the batch rule stays.
  - **SIMP** `active_student_org_ids` `:100`.
  - **DEL** `invite_domains` and `invite_domain_allowed` `:132-146`.
  - **CONV** `org_requires_mfa` `:148` into the platform policy key `auth.require_mfa_students`.
- **`models.py`:**
  - **DEL** `BulkImportJob` and `OrgInvitation`.
  - **SIMP** `Organization`: drop `gstin`, `billing_*`, `state_code`, `contact_*`, `data_role` and `settings`.

#### rbac (`api/modules/rbac/`)
- **`catalogue.py`:**
  - **DEL** role `college_coordinator` (`:23`, `:48-50`).
  - **DEL** permissions:
    - `org.create`, `org.update`, `org.suspend`, `org.settings.update`, `org.member.import`, `org.member.remove` (`:171-178`)
    - `rbac.grant.org_staff` (`:184`)
    - `contract.manage`, `contract.terminate`, `contract.read` (`:244-246`)
    - `seat.assign`, `seat.revoke` (`:251-252`)
    - `audit.read.org` (`:266`)
  - **KEEP** `org.read` and `org.member.read` only if a view of company members is wanted. Otherwise delete them too.
  - **DEL** the `"organization"` scope from every role's `allowed_scope_types` (`:46-56`). The student role currently defaults to `organization` and holds no granting cells, so it becomes `("platform",)`.
  - The 9-column matrix (`STU CRD TRN …`) loses the CRD column and gains EVL (§4).
- **`service.py`:**
  - **SIMP** `_scope_chain` `:154-178` and `_org_private_batch_links` `:187-205`. The organization step is now always the company org.
  - **SIMP** `resolve_grant_scope` `:282-318`: reject `scope_type='organization'`.
- **`router.py`:** **DEL** the coordinator "org staff" grant path (it uses `rbac.grant.org_staff`).

#### identity, sessions, core
- **identity:**
  - **DEL** `router.py:1481-1524`, the `organizations` list in `/me`.
  - **DEL** the consent purpose `college_data_sharing` (`service.py:37`, `schemas.py:17`).
  - **CONV** `policy.py:5,48-91`: drop `organization` from the precedence. It becomes user > plan > platform.
- **sessions:**
  - **DEL** `login.py:37,333`, the `college_coordinator` → `/college` portal mapping.
  - **DEL** shared lab devices:
    - `models.py:27-29` (`Device.shared_organization_id` and `shared_registered_*`)
    - `login.py:284`
    - `service.py:139,264-266,287`
  - **CONV** `resolver.py:220-224,310-313` to the platform MFA key.
  - **KEEP** `org_ids_for` (`resolver.py:57-95`).
- **core:** **KEEP** `principal.py`, `db.py` and `migration_helpers.py` unchanged. **ADD** `api/core/company.py` exporting `COMPANY_ORG_ID`, the fixed UUID inserted by the migration.
- **seeds:**
  - `seeds/dev_users.py:1-230` is a demo college plus a coordinator. Rewrite it as the company org, an admin, a trainer, an evaluator, a content manager and students.
  - `seeds/e2e_demo.py:15,63-68,255-262` uses `demo-college`. Change it to the company org.
  - `seeds/e2e_env.py:81` creates the COORDINATOR account. Replace it with an EVALUATOR account.

#### commerce and entitlements (the B2B part)
- **commerce `router.py`:** **DEL**
  - `:96` `_own_org`
  - `:1047` GET `/finance/contracts`
  - `:1067` POST `/contracts`
  - `:1082` PATCH `/contracts/{id}`
  - `:1102` POST `/contracts/{id}/terminate`
  - `:1135` GET `/orgs/{id}/contract`
  - `:1160` GET `/orgs/{id}/invoices`
  - `:1464` GET `/orgs/{id}/invoices/{id}/pdf`
  - `:1490` and `:1512` `/contracts/{id}/invoices`
- **commerce `admin.py`:** **DEL** `:25`, `:44`, `:344-549` (`contract_json`, `create_contract`, `amend_contract`, `terminate_contract`, and the approval executor branch). **SIMP** `:124`.
- **commerce, other files:**
  - **DEL** `billing.py:256-400` `issue_contract_invoice`, the B2B offline-PO GST invoice.
  - **DEL** `billing_approvals.py:69`.
  - **DEL** `policy.py:36-40,53` (the `CONTRACT_*` and `SEAT_*` constants).
  - **DEL** `schemas.py:116` (`institution_seat`), `:162` (`CouponIn.organization_id`), `:190`, `:207`, `:240`.
  - **DEL** `pricing.py:143-158` (college-only coupon codes) and `:328` (`included_via_college`).
  - **SIMP** `documents.py:174,256,301,397` to remove the B2B branch.
  - **DEL** `models.py:343` `Invoice.contract_id` and `:349` `InstitutionContract`.
  - **KEEP** B2C `billing.gstin` on orders (`router.py:198,320`). This is a GST invoice to a buyer who supplies a GSTIN; see owner decision D1.
- **entitlements:**
  - **DEL** `router.py:97-110` and `:385-460` (`/orgs/{id}/seats`, `/seats/assignments`, `/seats/revocations`).
  - **DEL** `router.py:215-243`, the coordinator `org_id` branch of `GET /users/{id}/entitlements`.
  - **DEL** in `service.py`:
    - `:45` (`institution_contract` precedence)
    - `:744` `_active_contract_orgs`
    - `:818-835`
    - `:887-1300` (seats, waitlist, contract sync and termination, `on_member_removed`)
    - `:1358-1364`
  - **SIMP** `service.py:248-293` (the `institution_contract_id` parameter of `grant()`).
  - **DEL** `models.py:32` and `:68` (`SeatWaitlist`), and `cache.py:51`.
- **`api/wiring.py:388-390`:** remove the COM-04 `orgs.member_removed` → seat release hook.

#### admin and AI (per-org settings)
- **`admin/policy.py`:**
  - **CONV** the org override layer: `_K(..., org=True)` `:37,47-73,133`, `_user_orgs` `:235`, `resolve` `:253-285`, `check_scope` `:333-346`, `org_overridable` `:387,417`.
  - **DEL** key `org.notify_coordinator_on_restriction` `:128-134`.
- **`admin/flags.py`:** **CONV** `:30-91` to drop `org_allowlist`.
- **`admin/router.py`:**
  - **CONV** `:66`, `:246`, `:256`, `:295`.
  - **DEL** `:692` `/orgs/{id}/privacy-requests`.
- **`admin/accounts.py`:** **SIMP** `:133-151,209-213` (org tiles on the dashboard) and `:336,362-367` (org list on user detail).
- **`admin/models.py`:** **CONV** `:30` `org_overridable` and `:53` `org_allowlist` (drop the columns).
- **AI:**
  - **CONV** `ai/models.py:22` `AIOrgSettings` (`ai_org_settings`) and `:38` `OrgAppSetting` (`org_app_settings`) into platform singletons.
  - **CONV** routes `ai/router.py:130,139,180,189,234` from `/admin/orgs/{id}/ai-settings|apps|ai-usage` to `/admin/ai-settings`, `/admin/apps` and `/admin/ai-usage`.
  - **SIMP** `ai/router.py:257-265` `/me/enabled-apps`.
  - **CONV** `ai/store.py:54-172` and `ai/service.py:136-154,250,479-493`, the `_gate`, `ai_enabled` and `require_app_enabled` functions that take `org_id`.
  - **Edit** the copy in `ai/service.py:69,144-152` and `ai/prompts.py:152,290`.
- **`require_app_enabled` / `ai_enabled` callers**, which become platform toggles:
  - `learning/structured_api.py:371,708`
  - `learning/router.py:924`
  - `engage/service.py:322,702,1000`
  - `paths/service.py:350,568,913,1327,1362`
  - `placement/qbank_router.py:123,358,445`
  - `assessments/router.py:608,700`

#### Delivery modules: org pickers collapse to the company org
- **catalog:**
  - **DEL** visibility `org_only` (`schemas.py:16`, and the CHECK in `mig/catalog_0001_catalog.py:63`).
  - **SIMP** `router.py:274,335-338,414-415`.
  - **SIMP** `learning/service.py:112-127`, the rule that hides another college's course.
- **learning:**
  - **SIMP** `structured.py:83-90,524,907` and `router.py:1378,1601`.
  - **KEEP** `models.py:196` (NOT NULL `organization_id`, which is now the company org).
  - Note: `allocation.evaluator_ids` (`models.py:204`, `structured_api.py:390-406,503-506`) is stored but never used for authorization. See §4 and SEC-02.
- **paths:**
  - **SIMP** `service.py:95-133` (`_batch_org`, `can_in_org`, `require_in_org`, `staff_context` org picker).
  - **DEL or SIMP** `router.py:227` GET `/paths/org-members`. Replace it with a batch-members picker.
  - **DEL** the article audience `"org"` (`service.py:1820`).
- **engage:** **SIMP** `service.py:5-16,97,149` (members of the org become members of the company), and remove the "Whole organization" target.
- **assessments:**
  - **SIMP** `studio.py:200-206,536-599,649,667,737-812,892,932`.
  - **SIMP** `router.py:550`.
  - **DEL** `router.py:568` `/studio/assignable-tests?organization_id` (COL-007, college assigns tests).
  - **SIMP** `integrity.py:102-117`.
  - **KEEP** `tests.batch_id`.
- **placement:**
  - **SIMP** `policies.py:36-80`, `router.py:119`, `qbank_router.py:64,91-105,122,354-358,444-452,531,584`, `banks.py:47,121-130,270`, `reports.py:146-192,228`.
- **coding:** **SIMP** `policies.py:20`, `router.py:432,461-471` and `service.py:610-640` (multi-org submission attribution).
- **mentoring:** **SIMP** `service.py:136,697`.

#### analytics, support, notifications, security, audit
- **analytics:**
  - **DEL** in `router.py`: `:130` `OrgReader`, `:148` `/reports/orgs/{id}` and `:155` `/reports/orgs/{id}/students/{uid}`.
  - **DEL** in `reports.py`: `:149-178` (`org=` drill-down), `:242`, `:256`, `:483`, `:542`, `:566`, `:574`.
  - **DEL** in `exports.py`: `:72-73` (`coordinator.org_overview`, `coordinator.org_learners`). **Rename** `:71` `coordinator.batch_progress` to `batch.progress`.
  - **SIMP** `exports.py:157,176,487-492`, `router.py:205,243` (the `"organization"` export scope), `feeds.py:132-168` and `jobs.py:448-449,604` (org rollups with `entity_kind='organization'`).
- **support:**
  - **DEL** in `service.py`: `:35`, `:71`, `:114-122`, `:144`, `:179-182` (the `college_access` category and the coordinator lane).
  - **DEL** in `router.py`: `:64`, `:257`, `:609-612`, `:1238-1240`.
- **notifications:** **KEEP** `router.py:126` `/batches/{id}/announcements`, held by trainer and admin.
- **security:**
  - **DEL** `api_engine.py:524-617`, the org trusted networks (`org_trusted_networks`, `models.py:244`).
  - **DEL** `api_engine.py:640-690` (org security summary, `/orgs/{id}/security-summary`) and `:670` (coordinator notification).
  - **DEL** `signals.py:347-386,933,1063` (lab-org signals).
  - **Rename** the unblock reason `college_lab_or_shared_computer` to `shared_computer` (`unblock.py:53,70`).
  - **Decide** on `admin/policy.py:102` `risk.trusted_network_multiplier`; see D5.
- **audit:** **KEEP** `router.py:135,156`, the generic organization filter. Remove `"org_trusted_network"` from `:53` after the table is dropped.

### 1.3 Database objects

| Object | Created in | Action |
|---|---|---|
| `org_invitations`, `bulk_import_jobs` | `mig/orgs_0001_orgs.py:131-160` | DROP |
| `organizations` college columns (`gstin`, `billing_*`, `state_code`, `contact_*`, `data_role`, `settings`), and `org_type` values other than `internal` | `orgs_0001:38-58` | DROP the columns, tighten the CHECK, and add a unique index so only one live org can exist |
| `institution_contracts` | `mig/commerce_0001_commerce.py:393` (RLS `:35,:464`) | DROP |
| `invoices.contract_id` | `commerce_0002_documents_plan_change.py:34` | DROP |
| `products.product_kind 'institution_seat'`, `coupons.organization_id` | `commerce_0001` | Archive the products, tighten the CHECK, DROP the column |
| `entitlements.institution_contract_id`, `source_type 'institution_contract'` | `entitlements_0001_entitlements.py:36-60` | End the entitlements, DROP the column, tighten the CHECK |
| `seat_waitlist` | `entitlements_0001:107` | DROP |
| `ai_org_settings`, `org_app_settings` | `ai_0001_ai.py:47,71` | Migrate to `ai_settings` (singleton) and `app_settings` (keyed by `app_key`), then DROP |
| `policy_settings.org_overridable`, rows with `scope_type='organization'` | `admin_0001_admin.py:46` | Delete the rows, DROP the column, tighten the CHECK |
| `feature_flags.org_allowlist` | `admin_0001:76` | DROP |
| `privacy_requests.requester_relationship 'college'` | `admin_0001:93` | Remap existing rows to `self`, tighten the CHECK |
| `devices.shared_organization_id`, `shared_registered_by`, `shared_registered_at` | `sessions_0001_sessions.py:41` | DROP |
| `org_trusted_networks` | `security_0001_security.py:308-327` | DROP (pending D5) |
| `consents` purpose `college_data_sharing`, `consents.organization_id` | `identity_0001:205`, `identity_0002` | Keep historic rows (legal evidence), tighten the purpose CHECK for new rows with `NOT VALID` or a trigger. The column stays, nullable and unused. |
| `user_profiles.college_name_text` | `identity_0001:81` | Pending D6. The recommendation is to keep it as an optional "Institution" field on the learner profile. |
| `roles.role_key` CHECK | `rbac_0001_rbac.py:34` | Replace the CHECK: drop `college_coordinator`, add `evaluator` |
| `role_grants` held by `college_coordinator`, and grants with `scope_type='organization'` | `rbac_0001` | Revoke coordinator grants with reason `college_removal`, convert org-scope staff grants to `platform`, then delete the role row once no grants reference it |
| `support_tickets.category 'college_access'` | `support_0002_categories.py:28` | Remap to `other`/`account`, tighten the CHECK |
| `courses.visibility 'org_only'` | `catalog_0001:63` | Remap to `private`, tighten the CHECK |
| Analytics rollups with `entity_kind='organization'`, org-scoped export jobs | `analytics_0001`, `analytics_0002` | DELETE the rows, tighten the CHECKs |
| `app.user_visible_in_orgs()` | `orgs_0001:176` | Replace it so that only staff memberships expose users (§2.4) |

### 1.4 Web (`apps/web`)

**Delete:**
- **Routes:**
  - `src/app/college/**`: 27 pages plus the layout (dashboard, batches, contract, seats, engage, networks, paths, reports, shortlists, staff, students, import, support, tests).
  - `src/app/admin/organizations/**` (`page.tsx`, `[org_id]/page.tsx`, `[org_id]/ai/page.tsx`).
  - `src/app/(public)/invite/[token]/page.tsx`.
  - `src/app/(public)/colleges/page.tsx`, the "For colleges" page. It is the only "register your institution" entry and points at a support ticket.
  - `src/app/app/college/page.tsx`.
  - `src/app/finance/contracts/page.tsx`.
- **Features and components:**
  - `src/features/college/**`, but move these out first (see below): `components/Batches.tsx`, `components/BatchManage.tsx`, the batch types in `lib/types.ts`, and `lib/roster.ts#readText`.
  - `src/features/invite/**`.
  - `src/features/admin/components/Organizations.tsx`. Move its `Org` type out first, or drop it.
  - `src/features/ai/admin/OrgAIAdmin.tsx`.
  - `src/features/engage/components/CollegeEngage.tsx`.
  - `src/features/privacy/components/CollegeSharing.tsx`.
  - `src/features/trainer/shared/grants.ts:24-31` (`coordinatorOrgId`).
- **E2E:**
  - Delete `e2e/_audit/staff.audit.ts`.
  - In `e2e/staff-portals.integration.spec.ts`, delete `:10` and `:32-63`.
  - In `e2e/a11y.integration.spec.ts`, delete `:16` and `:169-182`.
  - In `e2e/staff-portal-gate.integration.spec.ts`, remove `/college` from `:21`.
  - In `e2e/public-pages.spec.ts`, delete `:54-57`.
  - Remove `E2E_COORDINATOR_*` from `apps/web/.env.e2e.local:17-19` and `.github/workflows/ci.yml:297-299`.

**Move** to `src/features/batches/`: `Batches.tsx`, `BatchManage.tsx` and the batch types. Add `src/app/admin/batches/page.tsx` and `src/app/admin/batches/[batch_id]/page.tsx`, plus an admin nav item. Repoint `BatchDetail.studentHref` from `/college/students/{id}` to `/admin/users/{id}`, or to the trainer learner view.

**Edit:**
- **Nav:** `src/lib/nav/portals.ts:16,65,94-113,174,197`, plus the `appKey` gating (`:29-30` etc.) when the app toggles become platform-wide. Tests in `portals.test.ts` and `staff-portal.test.tsx:73-75`.
- **Robots and README:** `src/app/robots.ts:11`, `README.md:53`.
- **Public pages and copy:**
  - `src/components/shell/PublicShell.tsx:11,24`
  - `src/features/public/lib/seo.ts:9`
  - `src/features/public/content/help.ts:205-228`
  - `src/features/public/content/legal.ts:42,120,132,163,282,284`
  - `src/features/public/lib/types.ts:14,23-24`
  - signup `invite_token` in `src/app/(public)/signup/page.tsx:11,15` and `src/features/auth/components/SignupForm.tsx:32,123`
  - `src/features/catalog/components/CourseAccess.tsx:104`
  - `src/features/learning/components/States.tsx:90`
  - `src/app/app/settings/security/mfa/page.tsx:20`
  - `src/features/trainer/components/TrainerDashboard.tsx:49`
- **Privacy and account:**
  - `src/features/account/components/PrivacySettings.tsx:11,15,89`
  - `src/features/auth/lib/consents.ts:16,53`
  - `src/features/privacy/lib/types.ts`
  - `src/features/account/lib/types.ts:48`
  - `src/features/unblock/**` (the lab reason)
- **Commerce:** `src/features/commerce/components/AccessList.tsx:13,54`, `Checkout.tsx:33`, `lib/types.ts:19,177-178,222`.
- **Support:** `src/features/support/components/SupportDesk.tsx` (college lane), `lib/types.ts:23,48-49`.
- **Finance:**
  - `src/features/finance/components/Finance.tsx:9,20,660-800`
  - `FinanceDocuments.tsx:153-270`
  - `FinanceCatalog.tsx:64,437-626`
  - `lib/types.ts`
- **Admin:**
  - `src/features/admin/components/Users.tsx:49,187-195`
  - `Governance.tsx:60,180-240,336,379-383`
  - `ApprovalsQueue.tsx:56`
  - `PolicySettings.tsx:193,288`
- **AI:**
  - `src/features/ai/index.ts:5`
  - `types.ts:18-75`
  - `hooks/useEnabledApps.ts:24,36`
  - `components/AIErrorState.tsx:25-30`
  - `nav.test.tsx`
  - `ai.test.tsx`
- **Org pickers:**
  - engage: `lib/scope.tsx`, `ActivityBuilder.tsx:193-228,302-313`, `lib/builder.ts`
  - paths: `lib/base.ts:5-8`, `PathList.tsx`, `Articles.tsx`, `lib/types.ts:15,88-89`
  - assignment manager: `AssignmentManagerList.tsx:18-78`, `AllocateDialog.tsx:18-48`
  - trainer: `TestsList.tsx:16-41`, `TestOps.tsx:624`, `AssignTest.tsx:224`, `TrainerCourses.tsx:9-36`
  - studio: `Courses.tsx:23-48`, `Tests.tsx:110`
  - question bank: `QuestionBankPicker.tsx`, `lib/media.ts`, `QuestionEditorDialog.tsx:209`
  - `src/app/trainer/courses/page.tsx:14`
- **Security console:**
  - `src/features/security-admin/lib/catalogue.ts:90,113,167-177`
  - `TrustedNetworks.tsx`, and the `/security/networks` nav item at `portals.ts:182`
  - `Restrictions.tsx:190-239`
  - `CaseQueue.tsx:91,110`
  - `ReportExtras.tsx:72-75`
- **OpenAPI:** `apps/web/openapi/openapi.json` has 41 org, invitation, contract and seat paths, and `src/lib/api-types/schema.d.ts` has about 360 matching lines. Regenerate both from the backend:
  - `python -m app.scripts.export_openapi`
  - `npm run gen:api`

  Never hand-edit them. The contract test `src/features/__contract__/api-paths.test.ts:81` catches dangling calls.

### 1.5 Tests

**Backend tests to delete** (paths relative to `apps/api/tests`):
- `orgs/test_audit_fixes.py`, `orgs/test_lifecycle.py`, and the invitation and import parts of `orgs/test_orgs.py`. Keep the batch tests and move them to `orgs/test_batches.py`.
- `entitlements/test_access_and_seats.py:219,304`
- `commerce/test_documents_plan_change.py:212,488`
- `commerce/test_audit_fixes.py:443,480`
- `analytics/test_exports.py:105`
- `analytics/test_audit_fixes.py:150,163`
- `analytics/test_w2a_reports.py:95`, which needs rework to use an admin
- `support/test_audit_fixes.py:47`
- `identity/test_phase_b_identity.py:252` and `orgs/test_w2b_fixes.py:93`; convert both to the platform MFA key
- `coding/test_audit_fixes.py:51,66`
- `engage/test_engage.py:152,344,629`
- `paths/test_paths.py:479,584`
- `rbac/test_rbac.py:161`
- `admin/test_audit_phase_b_fixes.py:83`
- `placement/test_stage10_endpoints.py:57`
- `security/test_scn_sharing.py:274`
- `security/test_controls_reports.py:367`
- `authz/test_object_level.py:110` and `security/test_scn_sessions.py:383`. These cross-org isolation tests become cross-batch and cross-user tests.
- `_review_scratch/*`, once each probe is turned into a real regression test in its owning workstream

**Backend tests to update:**
- `ai/test_router.py`, `ai/test_app_gating.py`, `ai/test_service.py:104,257,323`, `ai/conftest.py`
- `admin/test_admin.py:78`, `admin/test_audit_phase_b_fixes.py:156`
- `authz/matrix.py`, `authz/test_authz_matrix.py` (CRD column becomes EVL)
- `rbac/test_w2a_adm41.py`
- `catalog/test_catalog.py`
- assessments, placement, learning, mentoring
- factories: `commerce/factory.py`, `identity/factory.py`
- `commerce/test_coupons_refunds_subscriptions.py:383`
- `analytics/conftest.py`
- `security/helpers.py` and the unblock tests
- `support/test_support.py`
- `notifications/test_notifications.py:58`, which should use a trainer instead of a coordinator
- `core/test_stage10_wiring.py`

### 1.6 Docs, environment and CI

- **Docs** with college content (count of mentions):

  | Doc | Mentions |
  |---|---|
  | `product-requirements.md` | 99 |
  | `api-specification.md` | 49 |
  | `audit/00-feature-inventory.md` | 44 |
  | `database-schema.md` | 41 |
  | `implementation-roadmap.md` | 31 |
  | `testing-and-acceptance-criteria.md` | 29 |
  | `account-security-and-risk-engine.md` | 25 |
  | `sitemap.md` | 21 |
  | `role-permission-matrix.md` | 19 |
  | `privacy-and-data-retention.md` | 15 |
  | `contract-reconciliation.md` | 15 |
  | `analytics-event-schema.md` | 13 |
  | `wireframes.md` | 12 |
  | `system-architecture.md` | 11 |
  | `blueprint-brief.md` | 11 |
  | `database-erd.md` | 8 |
  | `deployment-and-operations.md` | 8 |
  | `design-system.md` | 8 |
  | `account-unblock-workflow.md` | 7 |
  | `wiseman-reference/build/{engage,paths,ai,assign,qbank}.md` | a few each |
  | `architecture-decisions/ADR-0003-postgres-rls-tenancy.md` | 2 |

  Leave `docs/audit/**` and the QA reports alone; they are historical. Add a "superseded by single-company" banner where they are linked.
- **New ADR:** `docs/architecture-decisions/ADR-0004-single-company.md`.
- **Environment:**
  - Add `COMPANY_DISPLAY_NAME`; it is optional, since `SELLER_*` already names the seller.
  - Remove `E2E_COORDINATOR_*` and add `E2E_EVALUATOR_*`.
  - Edit `.env.example:88` (drop `/invite/{token}`) and `:430` (change "org admins may pick" to "admins").
- **CI:** `.github/workflows/ci.yml:297-299`.

---

## 2. Design decision: what happens to `organization`

### 2.1 Options

| | A. Drop organizations entirely | B. One invisible company org (recommended) | B′. Platform only (`organization_id` NULL everywhere) |
|---|---|---|---|
| Schema | Drop about 110 columns. Rewrite the `T`, `TN` and `U` predicates and every policy. Drop `app.org_ids()`. | Data migration only: re-home rows to `COMPANY_ORG_ID`. Drop the college-only tables and columns (§1.3). | NOT NULL columns (batches, paths, engage, structured assignments, …) would need to become nullable, and their predicates change. |
| RLS model | Must be redesigned. Trainers and batch students would need a new mechanism, such as batch-based predicates, to see shared rows. | Unchanged and already tested. Staff and batch students get `org_ids=[COMPANY]`. | `TN` write checks require `is_platform()`, so trainers, who are not platform, could no longer write their tests, banks or paths. That breaks batch trainers. |
| Code | Every module, plus `Principal`, the resolver and `rbac._scope_chain`, plus about 1,300 references | Delete college code paths. Org pickers become constants. About 30 helper functions simplified. | Medium, but it alters security semantics. |
| Risk | Very high. Security regressions are likely and test churn is huge. | Low to medium. Most of the risk is in data migration and permission remapping. | Medium to high. |
| Effort | Weeks | Days (6 parallel workstreams) | About a week |
| Honours "remove completely" | Yes | Yes for every surface users can see and every college code path. The organization survives only as an internal tenancy key, like a schema constant. | Yes |

### 2.2 Recommendation: option B

- **`COMPANY_ORG_ID` is a fixed UUID** in `api/core/company.py`. The migration `orgs_0002` inserts the row: name "Tech Drona", slug `techdrona`, `org_type='internal'`.
- **Only one organization can exist.** Enforce this in the database:
  - `CHECK (org_type = 'internal')`
  - `CREATE UNIQUE INDEX ux_organizations_singleton ON organizations ((true))`

  No API can create, suspend or edit organizations; `/orgs/**` is deleted.
- **Which `organization_id` a row gets:**
  - Rows whose column is nullable (`TN` family) keep their current meaning. `NULL` means platform content, authored by content managers. A non-NULL value means it was created inside a batch or org context, which is now always the company org.
  - Rows whose column is NOT NULL always get `COMPANY_ORG_ID`.
  - Nothing exposes the value. API DTOs may still carry `organization_id` for a while, but no endpoint accepts it as input except where it is ignored. WS6 then removes it from the web types.
- **Scope types:** drop `organization` as a grant scope. The scopes that remain are `platform`, `batch` and `course`.
  - Existing org-scope staff grants (other than coordinator grants) become `platform`, which means company-wide.
  - `rbac._scope_chain` can still add `("organization", COMPANY)` internally, so that batch grants cover org-owned content. That keeps the trainer's org-private course and test logic.
- **Org memberships stay as an internal fact:**
  - Batch students are `org_memberships(student)` of the company. The batch add endpoint creates the membership.
  - Staff with batch grants get the company org through `grant.organization_id`.
  - Public students who are not in a batch stay org-less and see only their own rows.

### 2.3 Settings that move from per-org to platform

| Today (per org) | Target (platform) | Owner |
|---|---|---|
| `ai_org_settings` (enabled, model, monthly token/call caps, per-activity cap) | `ai_settings` singleton row (`id smallint PK CHECK (id=1)`). The caps get **non-NULL defaults** (SEC-05). | WS3 |
| `org_app_settings` (assignments, engage, paths, assessments, question_banks, ai_grading, ai_tutor, ai_generation) | `app_settings(app_key PK, enabled)`, or policy keys `app.<key>.enabled`. `/me/enabled-apps` returns the platform set. | WS3 |
| `policy_settings` with scope `organization`, and `org_overridable` | Removed. Precedence is user > plan > platform. | WS3 |
| `feature_flags.org_allowlist` | Removed. The user allowlist and percentage rollout stay. | WS3 |
| `organizations.settings.require_mfa_students` | Policy key `auth.require_mfa_students` (default `false`) | WS1 |
| `organizations.settings` invite domains, `org.notify_coordinator_on_restriction` | Removed | WS1, WS3 |

### 2.4 RLS hardening that becomes necessary with one org

With colleges, a student's org peers were the few hundred students of one college. With one company org, every batch student shares the org with every other batch student. Today `p_users` and `p_o` let any member read any other member's `users` and `user_profiles` row at the database level, so the database layer would no longer isolate student PII between students. Only app-level checks would.

**Fix (WS1, `identity_0005`):** replace `app.user_visible_in_orgs(target)` so that it returns true only when one of these holds:
- (a) the caller has an active **staff** membership in a shared org, or
- (b) the target is a **staff** member of a shared org, so that students can still see trainer names.

Students then cannot read other students at the database level.

Engage leaderboards use nicknames; WS4 must verify this. Mentoring and support must also keep working: staff are covered by (a) and (b), and platform staff bypass RLS through `is_platform`.

---

## 3. Batches and cohorts

- **Batches stay** as Tech Drona's cohorts. `batches.organization_id` stays NOT NULL and holds `COMPANY_ORG_ID`. The constraint `uq_batches_org_code` effectively becomes "batch codes are globally unique". `batch_members.organization_id` behaves the same way.
- **Managed by:** Admin (`super_admin`, which already holds `batch.create`, `batch.update`, `batch.archive` and `batch.member.manage` at P). Until now only the coordinator (O) could do this in practice, through `/college/batches`. Trainers keep `batch.member.manage` at B for their own batches.
- **API:**
  - `GET` and `POST /batches` replace `/orgs/{org_id}/batches`.
  - `GET` and `PATCH /batches/{id}`, `/archive`, `/members` and `/members/{uid}` stay.
  - Adding a member accepts any active user, by user id or email lookup, and upserts the company org membership.
  - When the last active batch membership ends, the org membership is set to `left`. This removes the student's `org_ids`.
- **Columns:** keep `academic_year` and `graduation_year` as optional fields, labelled "Intake" and "Graduation year" in the UI. Dropping them is optional and not planned.
- **Batch features that stay:**
  - batch-scoped trainer, evaluator and mentor grants
  - `tests.batch_id`
  - batch announcements
  - batch analytics reports (`/analytics/reports/batches/{id}`)
  - path, assignment and engage allocations to batches
- **SEC-03 is fixed in the same pass:** check `status='active'` on batch membership.

---

## 4. Roles

### 4.1 From current roles to target roles

| Current role (key) | Target | Notes |
|---|---|---|
| `super_admin` | **Admin**. The key stays `super_admin` and the display name becomes "Admin". | Renaming the key would touch hundreds of references for no benefit. Admin takes over the coordinator's operational duties: batches, member moves, `test.assign` at platform scope, user invites, privacy requests. It remains privileged and needs MFA. |
| `trainer` | **Trainer** | Allowed scopes become `batch` and `course` (`organization` is dropped). Keeps authoring at course scope and grading at batch scope. |
| *(new)* `evaluator` | **Evaluator** | See §4.2. |
| `content_manager` | **Content manager** | Unchanged (platform and course). |
| `student` | **Student** | Allowed scopes become `platform` only. The role holds no permissions; the tier defaults to student. |
| `college_coordinator` | **Removed** | Grants are revoked by the migration. Its duties go to Admin or Trainer, as listed above. |
| `finance_admin` | Keep (D2) | Needed for Razorpay refunds, reconciliation, B2C GST invoices and coupons. It could be folded into Admin, but SoD-10 and Dual approvals need at least two privileged people. |
| `support_agent` | Keep (D2) | B2C helpdesk, MFA resets, session revocation. |
| `security_reviewer` | Keep (D2) | Risk engine cases, unblock appeals, L3/L4 restrictions, exam integrity. Could be folded into Admin if the risk engine is staffed by Admin. |
| `placement_mentor` | Keep (D2) | Only if the mentoring and placement product stays. It is B2C and not college-specific. |

**Permissions to re-home** (they were held only through the coordinator's O cells):
- Admin (P) already holds most of them.
- Add `test.assign`, `test.results.release` and `test.override.grant` at P for `super_admin`. Today these are coordinator (O) or trainer (B) only. Owner confirmation needed (D3).
- `engage.activity.manage`, `path.manage` and `path.allocate` are held by Trainer (B), Content manager (P) and Admin (P). `super_admin` lacks `path.*` today; add it.

### 4.2 Evaluator role (new)

There is no evaluator role today. `evaluator_ids` on structured-assignment allocations (`learning/models.py:204`) is stored but never used for authorization.

| Field | Value |
|---|---|
| Key, name | `evaluator`, "Evaluator" |
| Session tier | `staff`. MFA required. |
| Allowed scopes | `batch` (default) and `platform` (an evaluator for every cohort) |
| Grants (B, or P when granted at platform) | `assignment.grade`, `test.results.read`, `attempt.regrade`, `integrity.flag.read`, `integrity.flag.decide`, `submission.code.read`, `similarity.run`, `question.answer_key.read` (needed to grade), `user.read`, `progress.read` |
| Explicitly not granted | No authoring or publishing: no `course.*`, `question.*`, `coding_problem.*`, `test.create`, `test.edit`, `test.assign`, `assignment.manage`, `path.*`, `engage.*`, `media.upload`. No `grade.override_released` (it stays with Trainer). No `attempt.invalidate`. No `test.results.release` (D3). No `enrolment.manage` or `batch.*`. |
| Conflict of interest | Never grade one's own attempt or submission (SEC-10, SEC-12). |
| Structured assignments | When an allocation lists `evaluator_ids`, grading on that allocation requires the caller to be in that list, **or** to hold `assignment.grade` on the allocation's batch. This is part of the SEC-02 fix. |
| Migration | `rbac_0004` replaces the `roles.role_key` CHECK and calls `rbac_seed.sync()`. |
| Matrix | Add an EVL column to `catalogue.py` and to `docs/role-permission-matrix.md`. |

---

## 5. Migration strategy

**Rules:**
- Applied migrations are never edited. Every change is a new revision on its module's branch.
- Every new migration is idempotent and works both on the backed-up dev DB and on a fresh DB.
- `rbac_0002` imports the **live** catalogue, so a fresh DB never creates `college_coordinator`. The role-permission inserts in `engage_0001` and `paths_0001` are `INSERT … SELECT` and become no-ops when the role is missing.
- Every new revision has a `downgrade()` that restores the schema (columns, CHECKs and tables) but **not** the data. Its docstring says to restore the data from the dump.

**Order** (cross-branch `depends_on` enforces it):

1. **`orgs_0002_company_org`** (WS1)
   - Insert the company org.
   - Drop `org_invitations` and `bulk_import_jobs`.
   - Keep the organizations columns for now; step 9 drops them.
2. **`rbac_0004_single_company`** (WS1; depends on `orgs_0002`)
   - Replace the `role_key` CHECK and sync the catalogue, which adds `evaluator`.
   - Set `revoked_at=now()` with reason `college_removal` on every `college_coordinator` grant.
   - Convert remaining `scope_type='organization'` grants: trainer grants become `platform`, and their `organization_id` becomes `COMPANY_ORG_ID`.
   - Delete the removed permissions and their `role_permissions` rows.
   - Delete the `college_coordinator` role row only when no `role_grants` row references it (FK); otherwise keep it as a historic row with no permissions.
   - Expire pending approvals of type `org.suspend` and `commerce.contract.terminate`.
3. **`identity_0005_single_company`** (WS1)
   - Replace `app.user_visible_in_orgs` (§2.4).
   - Restrict the `college_data_sharing` purpose for new rows.
   - Set `college_name_text` according to D6.
4. **`sessions_0003_drop_lab_devices`** (WS1): drop the `shared_*` columns on `devices`.
5. **`commerce_0004_drop_b2b`** and **`entitlements_0003_drop_seats`** (WS2)
   - End live `institution_contract` entitlements (`ends_at=now()`, reason `college_removal`), then drop the column and the CHECK value.
   - Drop `seat_waitlist`, `institution_contracts` and `invoices.contract_id`.
   - Archive products of kind `institution_seat` and tighten the CHECK.
   - Drop `coupons.organization_id`, deactivating those coupons first.
   - Existing contract invoices are legal GST records. **Do not delete them.** Export them to the archive store before dropping `contract_id` (D1).
6. **`admin_0004_platform_policy`** and **`ai_0002_platform_settings`** (WS3)
   - Create `ai_settings` and `app_settings`. Seed them from the company org's rows if present, otherwise from defaults with non-NULL caps.
   - Drop `ai_org_settings` and `org_app_settings`.
   - Delete org-scoped policy rows, drop `org_overridable` and `org_allowlist`, remap `requester_relationship='college'`, and tighten the CHECKs.
7. **`catalog_0003`, `learning_0004`, `paths_0002`, `engage_0002`, `notifications_0002`** (WS4): remap `org_only` to `private` and tighten the CHECKs. No schema change for org columns.
8. **`analytics_0003`, `support_0004`, `security_0003`, `placement_0006`, `assessments_0005`, `coding_0004`** (WS5)
   - Delete org rollups and org export jobs.
   - Remap `college_access` tickets.
   - Drop `org_trusted_networks` (D5).
   - Placement, assessments and coding only need data re-homing (step 9).
9. **`orgs_0003_rehome_and_lock`** (WS1, last; `depends_on` every migration above)
   - For each table that has an `organization_id` column (from `information_schema`, excluding `organizations`), set `organization_id = COMPANY_ORG_ID` where it is non-NULL and not already the company org.
   - Resolve unique conflicts first: `org_memberships(org, user)` keeps the most recent row; `batches(org, code)` gets a suffix `-<oldslug>`.
   - Delete the other organizations.
   - Drop the college columns on `organizations`.
   - Add the CHECK on `org_type` and the singleton index.
   - Run inside `system_context` semantics: a migration role with RLS bypass.

**Dev data** (D7): the recommendation is to purge the demo college rather than re-home it.
1. Restore the backup.
2. Run the migrations; re-homing makes them safe either way.
3. Run `python -m app.seeds.dev_users` again with the rewritten single-company seed.

**Verification** (WS1 owns this, run after all workstreams merge):
- Running `alembic upgrade heads` on a fresh DB and on the restored dump gives the same schema. Compare with `pg_dump --schema-only`, ignoring the dropped columns.
- `SELECT count(*) FROM organizations` returns 1.
- No row in `role_grants` has `scope_type='organization'` and `revoked_at IS NULL`.

---

## 6. Workstreams

**Ownership rules:**
- A workstream edits only the files it owns.
- A cross-workstream need is handled one of two ways: the owner adds a temporary compatibility shim, or the requester files a one-line request to the owner.
- Every workstream runs `ruff`, `mypy` and `pytest` for its own test folders, plus `tests/authz`, before handing off.

**Dependency graph:**

```
WS1 (foundation) ──► WS2, WS3, WS4, WS5 in parallel ──► WS1 closes with orgs_0003 and verification
WS6 (web)        ──  starts the pure deletions at once; does the API-dependent edits after WS1–WS5; regenerates OpenAPI last
```

### WS1: Foundation (RBAC, orgs, identity, sessions, core, seeds). Goes first.

- **Owns:**
  - `api/modules/{rbac,orgs,identity,sessions}/**`
  - `api/core/**`
  - `api/seeds/{dev_users,e2e_demo,e2e_env,rbac_seed}.py`
  - `api/main.py`
  - migrations `rbac_*`, `orgs_*`, `identity_*`, `sessions_*`
  - `tests/{rbac,orgs,identity,sessions,authz,seeds,core,_review_scratch}/**`
- **Scope:**
  - §1.2 orgs, rbac, identity, sessions; `api/core/company.py`
  - batch routes moved to `/batches`
  - Evaluator role and the catalogue matrix
  - RLS hardening (§2.4)
  - Platform MFA key: WS1 adds it to `admin/policy.py` through WS3, or registers it via the identity policy registry
  - Migrations 1–4 and 9
- **Compatibility shims for the others:** keep `orgs.service.get_learner_org_context` and `batch_org_for_member` with the same signatures, now returning the company org. Export `COMPANY_ORG_ID`.
- **Security fixes:** none of SEC-01 to SEC-19 is in its files. WS1 does own the §2.4 RLS hardening, which is new.
- **Acceptance:**
  - The `college_coordinator` string appears nowhere in `apps/api/app`.
  - `/orgs` and `/invitations` return 404.
  - `authz` matrix tests pass with the EVL column.
  - At the DB level, a student in a batch cannot select another student's `users` row.
  - Seeds run on an empty DB.

### WS2: Commerce and entitlements (B2B removal)

- **Owns:**
  - `api/modules/{commerce,entitlements}/**`
  - `api/wiring.py`
  - `api/seeds/commerce_demo.py`
  - migrations `commerce_*`, `entitlements_*`
  - `tests/{commerce,entitlements}/**`
- **Scope:** §1.2 commerce and entitlements; migration 5. Keep the B2C GST path. Remove `DEMO-COLLEGE-SEAT` from `commerce_demo.py:15,89-91`.
- **Security fixes:** none in its files.
- **Acceptance:**
  - No `contract`, `seat`, `institution_` or `included_via_college` symbols remain in `apps/api/app`.
  - A B2C checkout through the Razorpay fake creates an order, an invoice and an entitlement.
  - The B2C invoice PDF still splits CGST/SGST/IGST.

### WS3: Admin and AI (per-org settings become platform settings)

- **Owns:**
  - `api/modules/{admin,ai}/**`
  - migrations `admin_*`, `ai_*`
  - `tests/{admin,ai}/**`
- **Scope:**
  - §1.2 admin and AI; §2.3; migration 6.
  - Keep a **compatibility signature** `require_app_enabled(session, org_id=None, app=...)` and `ai_enabled(session, org_id=None)`, ignoring `org_id`, so that WS4 and WS5 callers keep working. WS4 and WS5 then drop the argument. WS3 removes the parameter in a final small commit after they merge.
- **Security fixes:**
  - **SEC-05:** a per-user rate limit on the tutor (10/min, 200/day) and on generate; non-NULL default caps. The rate-limit call sites in `learning/structured_api.py:1319-1360` and `learning/router.py:863,890` belong to WS4. WS3 provides `ai.service.enforce_tutor_rate(principal)` and WS4 calls it.
  - **SEC-14 (reshaped):** the org caps race becomes a platform caps race. Fix it with a global advisory lock or a reserved usage row.
  - **SEC-15:** move the provider call out of the transaction (reserve, call, record).
  - **SEC-17:** the prompt `tagged()` escape becomes case-insensitive, and tutor history is kept on the server. This requires a WS4 change at `structured_api.py:1306-1309`; WS3 provides the API.
  - **SEC-19 (reshaped):** the platform `question_banks` toggle. WS3 provides the helper; WS5 calls it in `_bank_for` and `resolve`.
- **Acceptance:**
  - `/admin/orgs/*` returns 404. `/admin/ai-settings`, `/admin/apps` and `/admin/ai-usage` work.
  - Policy precedence tests show user > plan > platform.
  - The tutor returns 429 after the limit.

### WS4: Learning delivery (learning, paths, engage, catalog, mentoring, notifications, media)

- **Owns:**
  - `api/modules/{learning,paths,engage,catalog,mentoring,notifications,media}/**`
  - their migrations
  - `tests/{learning,paths,engage,catalog,mentoring,notifications,media}/**`
- **Scope:**
  - Collapse the org pickers to `COMPANY_ORG_ID`.
  - Delete `org_only`, the `org` article audience, `/paths/org-members` (replace it with batch members), and the "whole organization" targets in engage, paths and assignments.
  - Wire `evaluator_ids` into grading authorization.
  - Migration 7.
- **Security fixes:**
  - **SEC-01** (path allocation): no org fallback when `a.batch_id` is set.
  - **SEC-02** (cross-batch grading): return the set of gradable batches and filter by it; honour `evaluator_ids`.
  - **SEC-03** (`status='active'`): learning part. The coding grant reads `learning.structured.coding_access_grant`, which WS4 owns.
  - **SEC-06** and **SEC-07** (engage).
  - **SEC-08:** web, so it goes to WS6.
  - **SEC-09**, **SEC-11** and **SEC-12** (structured assignments).
  - Call WS3's rate limit for SEC-05, and adopt WS3's tutor-history API for SEC-17.
- **Acceptance:**
  - No `organization_id` query parameter or body field is accepted anywhere in these modules.
  - The probe tests from `_review_scratch` for SEC-01, SEC-02 and SEC-03 are turned into regression tests and pass.
  - An evaluator can grade but gets 403 on `assignment.manage` and on authoring endpoints.

### WS5: Assessment, practice and operations (assessments, placement, coding, analytics, support, security, audit)

- **Owns:**
  - `api/modules/{assessments,placement,coding,analytics,support,security,audit}/**`
  - `api/seeds/{placement_demo,coding_demo,security_demo,catalog_demo}.py`
  - their migrations
  - `tests/{assessments,placement,coding,analytics,support,security,audit}/**`
- **Scope:**
  - Delete `/studio/assignable-tests` (college), `/analytics/reports/orgs/**`, the coordinator exports, the `college_access` lane, trusted networks, the org security summary and lab-device signals.
  - Rename the unblock reason to `shared_computer`.
  - Collapse the org helpers in placement, coding and assessments.
  - Migration 8.
- **Security fixes:**
  - **SEC-04** (`qbank_router.py:582-593`): make the GET read-only, and add `question_media` to the sweep.
  - **SEC-10** (self-grading, `assessments/evaluation.py`, `integrity.py`).
  - **SEC-13** (connectivity event cap).
  - **SEC-16:** reduced but not moot, because company-bank versus platform-draft separation remains. Accept only published platform questions.
  - **SEC-18** (pin the scanned ETag).
  - **SEC-19:** call WS3's toggle helper in `_bank_for` and `resolve`.
- **Acceptance:**
  - No coordinator or college strings remain.
  - Analytics batch reports work for Admin, Trainer and Evaluator.
  - The SEC-04 probe (`_review_scratch/test_sec_aq_probe.py`) becomes a passing regression test.

### WS6: Web, OpenAPI, docs, E2E and CI

- **Owns:**
  - `apps/web/**`
  - `docs/**` (except this plan)
  - `README.md`, `.env.example`, `.github/workflows/ci.yml`
- **Scope:**
  - §1.4, §1.6.
  - Phase 1, which can start at once: delete the college portal, invite, colleges and organizations pages; move the batches UI to `features/batches` and add `/admin/batches`; fix the copy and the nav.
  - Phase 2, after WS1–WS5 merge: repoint the API calls (`/batches`, `/admin/ai-settings`, `/admin/apps`); remove the org pickers; add the Evaluator portal entry, which reuses the trainer grading screens with authoring hidden; regenerate OpenAPI and `schema.d.ts`; update docs, the ADR and the role matrix.
- **Security fixes:** **SEC-08** (Paths iframe sandbox in `features/paths/components/Learner.tsx:219-224`).
- **Acceptance:**
  - `rg -i "college|coordinator|institution" apps/web/src` returns only intended copy (placement "campus" wording), or nothing.
  - `npm run typecheck`, `lint`, `test` and the contract test pass.
  - Playwright suites pass with the EVALUATOR account.
  - The `/college` and `/invite/x` routes return 404.

### Where each security finding lands

| Finding | Workstream | Effect of the removal |
|---|---|---|
| SEC-01 | WS4 | Still applies. The org fallback becomes a company-wide fallback, which is worse because the org is bigger. |
| SEC-02 | WS4 | Still applies. Add `evaluator_ids`. |
| SEC-03 | WS4 | Still applies. |
| SEC-04 | WS5 | Still applies. |
| SEC-05 | WS3 + WS4 | Still applies. The caps become platform caps. |
| SEC-06, SEC-07 | WS4 | Still apply. SEC-07: "org members" becomes batch members. |
| SEC-08 | WS6 | Still applies. |
| SEC-09, SEC-11, SEC-12 | WS4 | Still apply. |
| SEC-10, SEC-13 | WS5 | Still apply. |
| SEC-14 | WS3 | Reshaped: the org cap race becomes a global cap race. |
| SEC-15, SEC-17 | WS3 (+ WS4 call sites) | Still apply. |
| SEC-16 | WS5 | Reduced: there are no foreign colleges, but the separation between the trainer bank and platform drafts remains. |
| SEC-18 | WS5 | Still applies. |
| SEC-19 | WS3 + WS5 | Reshaped: the per-org toggle becomes a platform toggle. |

No finding becomes fully moot: they are all intra-org or platform issues. The removal mainly **raises** the severity of SEC-01, SEC-02 and the user-visibility issue (§2.4), because all learners now share one organization.

---

## 7. Risks and decisions for the owner

### Risks

- **R1. PII exposure between students.** Every batch student shares one organization, so RLS on `users` and `user_profiles` no longer separates students from each other. Mitigation: §2.4 (WS1) must ship together with re-homing (`orgs_0003`).
- **R2. Permission gaps after the coordinator is removed.** Duties only the coordinator did (batch creation, test assignment at org level, member moves) must be reachable by Admin or Trainer. Mitigation: the authz matrix test, and an E2E "admin creates a batch, adds students, the trainer assigns a test, the evaluator grades it" flow (WS6).
- **R3. Migration ordering across branches.** `orgs_0003` must run last. Mitigation: explicit `depends_on`, and running both the fresh-DB path and the dump-restore path in CI.
- **R4. Removing the `require_app_enabled` / `ai_enabled` `org_id` parameter breaks callers in other workstreams.** Mitigation: the WS3 compatibility signature and its final cleanup commit.
- **R5. Historic GST invoices to colleges are legal records** (kept for 8 years). Do not drop them; export them before dropping `contract_id`.
- **R6. Dual control with a small staff.** `DUAL_ROLES` and Dual approvals (refund goodwill, rule publish, role grants) need two distinct privileged people. Confirm the company has them, or plan a policy change.
- **R7. Docs drift.** `role-permission-matrix.md` is the stated source of the catalogue, so update both in the same change (WS1 does the code, WS6 the doc, and WS1 reviews).

### Decisions needed from the owner

- **D1. GST invoicing to businesses.** Should B2C buyers still be able to enter a GSTIN for a B2B tax invoice (recommended, since India's GST rules call for it), while contract and offline-PO invoicing goes? And how should existing contract invoices be archived?
- **D2. Staff roles beyond the core five.** Keep Finance admin, Support agent, Security reviewer and Placement mentor as separate roles (recommended for SoD), or fold some into Admin?
- **D3. Evaluator scope.** May evaluators **release** results (`test.results.release`), or only grade? Should Admin get `test.assign`, `test.results.release` and `test.override.grant` at platform scope?
- **D4. Batch roster bulk add.** CSV roster import and invitations are being removed. Is a "bulk add existing accounts to a batch by email list" feature needed later?
- **D5. Trusted networks and shared computers.** Delete `org_trusted_networks` and the lab-device feature entirely (recommended), or keep trusted networks as **company office** networks for the risk engine (`risk.trusted_network_multiplier`)?
- **D6. `user_profiles.college_name_text`.** Public learners are often students themselves. Keep it as an optional "Institution / college" field on the learner profile (recommended, as it is useful for placement) or drop it?
- **D7. Existing demo data.** Purge the demo college and re-seed (recommended), or re-home it into the company org?
- **D8. Marketing.** Remove the "For colleges" page and all B2B copy (planned). Should there be a contact form for corporate or bulk enquiries in its place, or nothing?

---

## 8. Owner decisions (recorded by the coordinator, 2026-11-06) — these OVERRIDE the recommendations above

| # | Decision |
|---|---|
| D1 | Keep optional buyer GSTIN for B2C tax invoices (CGST/SGST/IGST stays). Contract/offline-PO invoicing is removed. Existing contract invoices are legal records: export them (JSON + PDFs if present) to `backups/archived-contract-invoices/` and keep the invoice rows; only drop `contract_id` after export. (coordinator default) |
| D2 | **Fold Finance admin, Support agent, Security reviewer and Placement mentor INTO Admin** (owner choice). Target roles = Admin (`super_admin`, shown as "Admin"), Trainer, Evaluator, Content manager, Student. All their permissions move to `super_admin`; the four roles are removed like `college_coordinator` (grants revoked with reason `role_consolidation`, role rows deleted when unreferenced). Dual control / SoD rules become "two DIFFERENT admins" (maker ≠ checker); keep the rules, change role sets. Mentoring features stay; mentor duties are performed by Admin (or Trainer where a mentor booking is batch-scoped — WS4 decides minimal mapping and documents it). |
| D3 | **Evaluators may grade AND publish results** (owner choice): grant `test.results.release` and the assignment grade-release action to `evaluator`. Admin also gets `test.assign`, `test.results.release`, `test.override.grant` at platform scope. Evaluators still have no authoring rights and may never grade their own attempt/submission. |
| D4 | No bulk roster add now; Admin adds existing accounts to a batch one by one (+ search). Note as future idea. (default) |
| D5 | Delete trusted networks and lab/shared-device features entirely. (default) |
| D6 | Keep `college_name_text` as an optional learner profile field labelled "Institution (optional)". (default) |
| D7 | Purge demo college data and re-seed single-company demo data. (default) |
| D8 | Replace the public "For colleges" page with a **corporate enquiry form** (owner choice): public page `/enquiries` (name, company, email, phone, message, consent; CAPTCHA/rate-limited; no account needed) → stored server-side (support module: ticket category `corporate_enquiry` or a small `enquiries` table) and visible to Admin in the support queue; notification email to the admin mailbox via existing notifications. Backend = WS5 (support), web = WS6. |
| D9 | **Allow embeds** in learning paths from YouTube (`www.youtube-nocookie.com` embeds only), Vimeo (`player.vimeo.com`) and Google Docs/Drive viewers (`docs.google.com`, `drive.google.com` preview URLs) via CSP `frame-src` + a strict iframe `sandbox` (SEC-08); everything else keeps "open in new tab". Server-side URL allow-list check when saving a step (WS4), CSP + iframe (WS6). |
| D10 | AI tutor default limit: 20 messages per learner per assignment/activity (platform setting, Admin-editable), plus SEC-05 rate limits. (coordinator default) |
