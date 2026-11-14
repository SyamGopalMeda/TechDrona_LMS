# Live audit: Teacher, Evaluator and Content Studio portals

- Site: https://techdrona-lms-app.web.app. Live only, run on Cloud Build. Navigation and reading only: no form was submitted.
- Date: 2026-11-14
- Spec: `qa/live-e2e/tests/audit-staff.spec.ts`
- Runs:
  - `qa/live-e2e/runs/80305aad-d35a-4680-b889-389921a7c088/`: desktop and tablet, with screenshots.
  - `qa/live-e2e/runs/6e734a80-979a-4f95-8018-39d4f8cf5970/`: desktop only. This run is the clean source for the cross-portal results (see the note on run 1 below).
- Accounts:
  - qa-trainer: `trainer` at batch "Generative AI", which is planned and has no students yet.
  - qa-evaluator: `evaluator` at the same batch.
  - qa-content: `content_manager` at platform scope.
- Coverage limit: the batch has no tests, assignments, submissions or attempts. Test, attempt, review and integrity detail routes that need an ID could not be opened live. For those routes I probed the API (GET only) and read the code.

> **Run 1 note:** in run 1 the trainer and evaluator sessions were signed out partway through. Desktop and tablet ran in parallel with the same session cookies, and every later page went to `/login` with `401 GET me/grants`. Run 2 used one context per account and lost no sessions. The cause is the test harness, not a product bug. Specs should not reuse one role's storageState in parallel projects.

## 1. Per-role navigation and page status

Status "OK" means the page loaded with no 4xx/5xx API call and no console error, and was not blank or stuck loading.

### Teacher (`/trainer`): qa-trainer

| Item (where) | URL | Purpose | Status |
|---|---|---|---|
| Dashboard (sidebar) | `/trainer` | Batches, waiting-to-grade and flag tiles, quick actions, live tests, tests list | OK |
| Teach > Courses | `/trainer/courses` | Author or teach company courses | OK (empty) |
| Teach > Learning paths | `/trainer/paths` | Guided paths, AI draft | OK (empty) |
| Teach > Articles | `/trainer/paths/articles` | Path articles | OK (empty) |
| Teach > Engage | `/trainer/engage` | Live polls, quizzes, word clouds | OK (empty) |
| Quick action "Start a live activity" | `/trainer/engage/new` (and `?type=poll`) | Activity builder | OK. The batch picker lists "Generative AI". |
| Assess > Grading | `/trainer/grading` | Grading queue | OK (empty) |
| Assess > Assignments | `/trainer/assignments` (tabs: Sections & questions, Single submission) | Assignment builder | OK, both tabs |
| Assess > Tests | `/trainer/tests` | Tests list, "New test" | OK (empty) |
| Assess > Integrity flags | `/trainer/integrity` | Advisory flags | OK, `GET integrity/flags` returns 200 |
| Batch link / "My batches" tile / "Message students" | `/trainer/batches/{id}` (tabs: Overview, Classes & attendance, Plan) | Batch roster, progress, announcements, classes | OK, all tabs |
| Account menu | Settings to `/app/settings/profile`; Tech Drona website; Sign out | | OK. Settings stays in the Trainer shell. |
| `/app/account-status` (not in menu) | | | OK, in the Trainer shell |
| Portal switcher / Modules switcher | | | Hidden (one portal, one module). Correct. |
| Find a page (Ctrl K) | | | Focuses the search box. Lists only Trainer pages, nothing from Admin, Finance or Student. |

API (GET) for the trainer: `batches/{id}` 200, `batches/{id}/members` 200, `studio/tests` 200 (0 items), `assignments?scope=mine` 200 (0 items), `integrity/flags` 200, `paths` 200.

### Evaluator (`/evaluator`): qa-evaluator

| Item | URL | Purpose | Status |
|---|---|---|---|
| Grading (home) | `/evaluator` | Grading queue | OK (empty) |
| Tests | `/evaluator/tests` | Tests with "Evaluate" and "Report" links | OK (empty), but the empty-state text is wrong (F5) |
| Integrity flags | `/evaluator/integrity` | Advisory flags | **Silent 403** on `GET batches/01a1ca9b-ea02-731b-9da3-9f7d03e3ffa1`. The Batch filter is empty (F1). |
| Account menu | Settings, website, Sign out | | OK. Settings and account status stay in the Evaluator shell. |
| Switchers | | | Hidden. Correct. |
| Find a page | | | Evaluator pages only |
| `/trainer/batches/{id}` (deep link) | | | Redirects to `/evaluator`. The evaluator has no page for its own batch. |

API (GET) for the evaluator: `batches` 403, `batches?mine=true` 200 with an empty list, `batches/{id}` **403**, `batches/{id}/members` **403**, `studio/tests` 200, `assignments?scope=mine` 200, `integrity/flags` 200.

### Content Studio (`/studio`): qa-content

| Item | URL | Purpose | Status |
|---|---|---|---|
| Dashboard | `/studio` | Review, draft and report counts; quick actions | OK |
| Review > Review queue | `/studio/review` | Questions and courses waiting for review | OK (once 21 s to settle on tablet in run 1) |
| Review > Reported errors | `/studio/reports/errors` (tabs: Open, Resolved) | Learner error reports | OK, both tabs |
| Content > Courses | `/studio/courses` | Course authoring | OK (empty) |
| Content > Media | `/studio/media` | Media per course | OK (empty) |
| Content > Taxonomy | `/studio/taxonomy` | Subjects and topics | OK (empty) |
| Content > Companies | `/studio/companies` | Company prep paths | OK (empty) |
| Questions & tests > All questions | `/studio/questions` | Question search | OK |
| Quick action "Write a question" | `/studio/questions/new` | Question editor | OK |
| `/studio/questions/import` (link on the questions page) | | Points to Question banks for bulk import | OK |
| Questions & tests > Question banks | `/studio/question-banks` | Banks, AI generation, bulk import | OK (empty) |
| Questions & tests > Coding problems | `/studio/coding` | Coding problems | OK (once 11 s to settle on tablet in run 1) |
| Questions & tests > Template mocks | `/studio/tests` | Test templates for trainers | OK (empty) |
| Account menu, switchers, Find a page | | | OK. Studio pages only. |

## 2. Cross-portal access (run 2, desktop)

Each role opened `/admin`, `/finance`, `/desk`, `/security`, `/mentor`, `/studio`, `/trainer`, `/evaluator` and `/app`, plus 2 deep pages under each:

| Role | Result |
|---|---|
| trainer | All 24 foreign URLs redirect to `/trainer` (Trainer dashboard). No foreign content and no foreign API calls. |
| evaluator | All 24 redirect to `/evaluator`. |
| content | All 24 redirect to `/studio`. |

Staff API probes (GET) gave the expected result:
- These return 403 for all three roles: `admin/users`, `admin/feature-flags`, `admin/privacy-requests`, `admin/ai-settings`, `admin/apps`, `security/cases`, `mentoring/slots`.
- `support/queue` returns 403 for trainer and evaluator.

Exceptions:
- `admin/approvals` returns **200** for every staff role. The handler filters the list to approvals the caller requested or can approve (`apps/api/app/modules/admin/router.py:328-347`), so the result is an empty list for these roles. No data leaks. It is noted only because a route under `admin/` is reachable by non-admins.
- `support/queue` returns **200** for the content manager. This is deliberate in the permission matrix, but no screen uses it (see F3).

## 3. Findings

**F1 (Medium): Evaluator: batch metadata and roster return 403, so the Integrity page makes a silent 403 and other screens lose batch and student names**
- Role: evaluator
- URL: `/evaluator/integrity`. Also affects `/evaluator` (grading queue), `/evaluator/tests/{id}/report` and `/evaluator/grading/*` when data exists.
- Evidence:
  - Live, both runs and both viewports: `403 GET v1/batches/01a1ca9b-…` and a console error "Failed to load resource: 403". The Batch filter shows only "All batches".
  - API probes: `batches/{id}/members` returns 403, and `batches?mine=true` returns `{"data": []}`.
- Effect:
  - The Integrity Batch filter can never be used.
  - The test report "Assigned to" column shows "—".
  - Grading-queue student names fall back to "Student" when `learner_name` is missing.
  - The code already works around this with comments ("evaluators can't look batch names up").
- Source:
  - `apps/api/app/modules/rbac/catalogue.py:214`: `org.member.read` matrix is `- - B - P`, so the evaluator column has no access.
  - `apps/api/app/modules/orgs/router.py:207-213` (`get_batch` requires `org.member.read`) and `:264-268` (members).
  - `apps/api/app/modules/orgs/router.py:163-172`: `mine=true` also filters by `org.member.read`, so an evaluator gets an empty list.
  - Client: `apps/lms-spa/src/features/trainer/lib/batches.ts:34` (per-ID `GET batches/{id}`) and `:81` (members, error swallowed).
  - Callers: `features/trainer/components/Integrity.tsx:70`, `TestOps.tsx:633`, `Grading.tsx:82` and `:1027`.
- Fix: give the evaluator a batch-scoped read of batch name and roster. Either:
  - set the `org.member.read` matrix to `- B B - P`, or
  - add a narrow `batch.read` permission (name, code, dates) and make `GET batches?mine=true` include batches from any batch grant.

  Then have `useTrainerBatches` call `batches?mine=true` once instead of N per-ID calls.

**F2 (Medium, not verifiable live): attempt result, review and evaluation routes for batch staff**
- Roles: trainer, evaluator
- URLs: `/trainer/tests/{id}/attempts|evaluation|report|overrides`, `/evaluator/tests/{id}/evaluation|report`
- Evidence: the QA batch has 0 tests and 0 attempts (`studio/tests` returns 200 with 0 items). No detail page or attempt API could be opened.
- Code reading:
  - `GET attempts/{id}/result|review` call `_attempt_reader`, which checks `test.results.read` at `ScopeRef("batch", att.batch_id)` (`apps/api/app/modules/assessments/router.py:296-312`, `studio.py:579-607`). The matrix grants B to both evaluator and trainer, so these should return 200 for an attempt carrying the batch_id.
  - The suspected 403/404 would happen when `att.batch_id` is NULL ("No batch (older assignment)"). The check then falls back to organization scope, which batch staff do not hold, and the API returns **404**, not 403.
- Fix:
  - Seed one published test assigned to "Generative AI" with one QA-student attempt, then rerun this spec. It already derives the deep routes from `studio/tests` and `tests/{id}/attempts`.
  - Make sure attempts always carry `batch_id`.

**F3 (Medium): Content manager can read and answer support tickets, but no screen offers it**
- Role: content
- Evidence:
  - `GET support/queue` returns 200 for qa-content.
  - `/desk` redirects to `/studio`, and the Studio nav has no ticket item.
- Source:
  - `apps/api/app/modules/rbac/catalogue.py:301-302`: `ticket.read` and `ticket.respond` are `S - - P P`.
  - `apps/api/app/modules/support/service.py:66-70`: `ROLE_CATEGORIES` gives the content manager the content, assessment and certificate categories, and `ROLE_ESCALATION` routes "content" escalations to them.
- Effect: tickets escalated to "content" have no UI owner.
- Fix: either remove these permissions from the content manager column (Admin handles support since D2), or add a "Content tickets" item to the Studio Review section that reuses the `/desk` queue filtered to those categories.

**F4 (Low): Staff account-status page links to student-only pages**
- Roles: all three
- URL: `/app/account-status`, rendered inside the staff shell
- Evidence (screenshot `runs/6e734a80…/shots/eval-account-status.png`):
  - "Go to my dashboard" goes to `/app`. It only works because the gate then redirects to the staff home.
  - "Contact support" goes to `/app/support/new`, which redirects staff to their home. The link is dead for them.
  - "Check a review request" goes to `/unblock-request#status` (a student flow).
- Source: `apps/lms-spa/src/features/unblock/components/AccountStatus.tsx:118-124` and `features/unblock/components/RestrictedStatus.tsx:246`
- Fix: build these links from the current shell's home, and hide the support and review-request links for staff accounts.

**F5 (Low): Evaluator Tests empty state uses authoring wording**
- Role: evaluator
- URL: `/evaluator/tests`
- Evidence: "No tests yet. Tests you create or that are shared with your batches appear here." Evaluators cannot create tests.
- Source: `apps/lms-spa/src/features/trainer/components/TestsList.tsx:191`
- Fix: when `evaluateOnly` is set, use "Tests assigned to your batches appear here when students submit attempts."

**F6 (Low): "Find a page" misses common words and account pages**
- Roles: all three
- Evidence:
  - Trainer query "grade" finds nothing, although "Grading" exists. The match is a plain substring and "grade" is not a substring of "grading".
  - "settings" finds nothing for every role, although Settings is in the account menu.
  - Content query "test" matches "All questions", "Question banks" and "Coding problems" only because of the section name "Questions & tests".
- Source: `apps/lms-spa/src/components/shell/PortalNav.tsx:119`
- Fix: add keywords or synonyms to `NavItem` (for example grade, mark, settings, profile), match on word stems, and add the account links (Settings, Account status) to the search index.

**F7 (Low): Evaluator portal has no page for its own batch**
- Role: evaluator
- URL: `/trainer/batches/{id}` redirects to `/evaluator`
- Evidence: the evaluator has a batch grant but no page showing batch name, dates or students. The grading screens are the only context.
- Fix (product decision): once F1 is fixed, add a read-only "My batch" panel (name, dates, student count) to `/evaluator`.

**F8 (Low, UI, tablet 810x1080): small touch targets**
- `/trainer`: batch name link "Generative AI" is 96x19.
- `/trainer/engage/new`: radio and checkbox inputs `#…-instant`, `#…-scheduled`, `#…-members` are 16x16.
- `/studio/questions/new`: checkboxes `input.h-5.w-5` are 20x20.
- Fix: give these inputs a 24 px or larger hit area (padding on the label, or `min-h-touch` on the row).

**F9 (Info): duplicate sign-out and website entries in the shell**
- The sidebar footer and the account menu both show "Tech Drona website" and "Sign out" (all three portals). This is harmless but adds noise.
- Fix: keep them in the account menu only on desktop, and keep the sidebar copies for the mobile drawer.

**F10 (Info): harness caveat**
- See the Run 1 note at the top. Running several device projects in parallel with one role's storageState signs that account out partway through the run.
- Fix (qa): run cross-portal checks on a single project, or sign in once per project in `global-setup.ts`.

### Checked and not a problem
- Every sidebar item, dashboard tile, quick action and in-page tab opened without errors for its own role (desktop and tablet).
- Role gate: every foreign portal URL redirects to the role's own home. Nothing from another portal appeared.
- Account menu "Settings" (`/app/settings/profile`) keeps the staff shell and does not drop staff into the Student portal.
- Portal and module switchers are correctly hidden for these single-portal accounts.
- Internal screen IDs used as eyebrows (`TRN-010`, `TRN-005`, `CMS-013`…) do not appear on the live pages.
- The large blank area in full-page screenshots of `/trainer` is a screenshot artifact. `Reveal` sections fade in on scroll through an IntersectionObserver, so they are empty in full-page captures.

## 4. Irrelevant / misplaced items

| Item | Where now | Problem | Where it belongs |
|---|---|---|---|
| Course authoring ("Courses", "New course") | Teacher > Teach > Courses **and** Studio > Content > Courses | Two authoring screens with different rules: trainer courses are company-only and skip the review queue. Teachers of a planned batch see "Create a course draft" as their first job. | Keep authoring in Studio. In the Teacher portal show "Course materials" read-only, with an "Add lesson to my batch course" action. Otherwise label it "My company courses" to make the difference explicit. |
| Learning paths + Articles authoring, with "Generate with AI" | Teacher > Teach | Content authoring inside the Teacher portal, duplicating the Studio's role. `path.manage` is also granted to the content manager, who has no Studio nav item for paths. | Either add "Learning paths" to Studio > Content (the content manager holds `path.manage`) and keep trainer access to *allocating* paths, or keep both and accept the duplication. |
| Assignments builder (sections & bank questions) | Teacher > Assess | Fits the teacher. Bank questions are authored in Studio. | Keep. Link to Studio question banks for question authoring. |
| Integrity flags "Invalidate the attempt" outcome | Evaluator > Integrity flags (decision dialog) | `attempt.invalidate` is trainer-only (`- - B - -`), but the evaluator sees the same three outcomes, so choosing Invalidate would fail with `permission_denied` (`apps/api/app/modules/assessments/integrity.py:593-599`). | Hide the "Invalidate" outcome when `evaluateOnly` / in `/evaluator` (`apps/lms-spa/src/features/trainer/components/Integrity.tsx:34-57`, rendered at `:359`). |
| Support ticket permissions for the content manager | API only | No UI (F3) | Admin > Support, or a Studio "Content tickets" view |
| `admin/approvals` reachable by non-admins | API only | Returns only the caller's own requests (empty) | Fine. Consider moving it to `/me/approvals` for clarity. |
| Account-status links to Support, Privacy and Review request | `/app/account-status` in staff shells | Student-only flows (F4) | Hide for staff |
| No student-facing or admin-only items | All three sidebars, Find a page | None found | — |
