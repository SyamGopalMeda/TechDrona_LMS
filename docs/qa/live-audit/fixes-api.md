# Live role audit: API fixes (2026-11-14)

- **Sources:** `staff-portals.md` (F1, F3, section 2 exceptions), `admin.md` (9, 11, 14), `student-and-access.md` (F-12, F-15), and the earlier `docs/firebase/agents/role-api-audit.md`.
- **Scope:** `apps/api` and its tests only. `apps/lms-spa` and `apps/web` are untouched. `functions-lms/app` was re-synced with `functions-lms/tools/build.py`. The build again reported "functions-lms/venv missing"; that is expected here.
- **Not deployed.** Each fix still has to be checked on the live site after the deploy (see "Live checks" at the end).

## Summary

| # | Finding | Result |
|---|---|---|
| F1 | Evaluator gets 403 on `batches/{id}` and `/members`, and an empty `?mine=true` | **Fixed** (code, no data change) |
| F3 | Content manager holds ticket permissions but has no ticket screen | **Decision: keep the permissions.** Admins handle content tickets. Documented in code. |
| admin 9 | QA accounts counted in the dashboard headline numbers | **Fixed** for "Signed in now". "New registrations" and "Learners" already left them out. |
| admin 11 | Hourly "Razorpay 0 orders" reconciliation rows with no gateway connected | **Fixed:** the scheduled run is skipped |
| admin 14 / student F-12 | A new sign-in silently evicts the oldest session | **API improved.** The 401 now carries a clear `detail` (`reason` was already sent). An **SPA change is still needed** to show it. Caps are unchanged. |
| student F-15 | Trainer gets 200 on `mentor/students`; content manager gets 200 on `admin/certificates` | **Review only:** both are intended by the role matrix (details below) |

## F1: Evaluator batch read

**Cause:** `GET /batches/{id}` and `GET /batches/{id}/members` required `org.member.read` at batch scope. `?mine=true` also filtered grants by that permission. The matrix (`catalogue.py`, `org.member.read` = `- - B - P`) does not give it to the Evaluator.

**Fix** (`apps/api/app/modules/orgs/router.py`):

- New `BATCH_READ_PERMISSIONS = ("org.member.read", "progress.read")`. A route allows the read when the caller holds **either** permission **at that batch**.
  - The Evaluator holds `progress.read` at batch scope (`S B B - P`).
  - Reading learners' progress in a batch already reveals who the learners are, so this adds no new kind of data.
- `GET /batches/{id}` and `GET /batches/{id}/members` use a new dependency, `_require_batch_read`:
  - An unknown batch still returns 404 (TI-02).
  - Denial is still `403 permission_denied` with `permission: org.member.read`.
  - The guard still advertises `td_permission = org.member.read` to the route listings.
- `GET /batches` and `?mine=true` count a batch grant when it gives batch read. An Evaluator therefore sees exactly its own batch. A grant on a batch that was deleted is now skipped; before, it raised an error.
- **Unchanged:**
  - Plan, schedule, classes and attendance (`orgs/classes.py`) still need `org.member.read`, so they stay Trainer and Admin only.
  - Every write keeps its own permission.
  - The content manager holds neither permission and is still refused.

**Why not change the catalogue cell to `- B B - P`?** The deployed role permissions live in the Firestore `role_permissions` collection. Nothing in the deploy path re-syncs that collection from `catalogue.py`: `rbac_seed.sync` targets Postgres, and `functions-lms/tools/seed_emulator.py` targets the emulator. A catalogue edit would pass the tests, which read the catalogue, but would do nothing on live until someone ran a manual data operation. The code rule works as soon as it is deployed.

- If the owner prefers the matrix route later:
  1. Set `org.member.read` to `- B B - P`.
  2. Write the evaluator × `org.member.read` row to live `role_permissions`.
  3. Remove `BATCH_READ_PERMISSIONS`.
- Note that this route would also open classes and attendance to evaluators.

**SPA follow-up (not done here):** `useTrainerBatches` (`apps/lms-spa/src/features/trainer/lib/batches.ts`) can call `batches?mine=true` once instead of N calls to `batches/{id}`. The F1 comments that work around evaluators ("evaluators can't look batch names up") can go. F7 ("My batch" panel for the evaluator) is now possible.

## F3: Content manager support permissions

**What "escalate to content" does** (`support/router.py` `POST /support/tickets/{id}/escalate`):

- It sets `escalated_to = "content"` and the status `pending_internal`.
- It adds an internal message.
- It emits `support.ticket_escalated`. **No handler consumes that event**, so no one is notified.

**Who can see the ticket:**

| Viewer | What they see |
|---|---|
| Admin | Every category, including content tickets and content escalations, in the Admin Support queue (`ROLE_CATEGORIES["super_admin"] = None`) |
| Content manager | Through the API only: the content, assessment and certificate lane, plus "content" escalations. There is no Studio screen for tickets. |

**Decision:** keep the permissions and use the rule "**Admins handle content tickets**" in the Admin Support queue.

- **No data leak:** the content manager's queue, tickets and messages are lane-scoped (`staff_scope.sees`, verified in the earlier audit).
- **Possible future use:** removing the permissions would break a Studio "Content tickets" view, which `staff-portals.md` F3 proposes as an alternative.
- A comment at `ROLE_ESCALATION` in `support/service.py` records this.
- **Known gap, unchanged:** D5 in `role-api-audit.md`. A content manager can attach support notes to any user. That item is still open for an owner decision.

## Admin 9: Synthetic accounts in the dashboard counts

`GET /admin/dashboard` (`admin/accounts.py`):

- `new_7d` and `new_30d` ("New registrations"), `learners` and `minors` **already** passed `is_synthetic=False`, on Postgres and on Firestore.
- `sessions.active` ("Signed in now") counted every active session.
- **Fix:** active sessions whose user is `is_synthetic` are no longer counted. The rule is the same on both stores (`ipub.list_users(is_synthetic=True)`, then the sessions are filtered).
- `users.total`, `active` and the other status totals still count every account. They are account totals, not activity numbers.

> **Live caveat:** the audit says the QA accounts are *not* marked synthetic ("New registrations 4"). With the new filter, live numbers drop only if the `qa-*@qa.techdrona.test` users have `is_synthetic = true` in Firestore `users`. If "New registrations" still shows 4 after the deploy, those 4 are either real accounts or QA accounts without the flag. Set the flag on the QA users; that is a data step, not a code change.

## Admin 11: Reconciliation noise

`commerce/tasks.py` `reconciliation()` (the hourly beat job; on Firebase it is `lmsJobCommerceReconciliation`):

- It now checks `gateway_status()` first.
- While no real gateway is connected, it logs `commerce.reconciliation_skipped` and returns `{"skipped": "gateway_not_integrated", ...}`. It writes **no** run row.
- "Not connected" means the fake provider is in use, or there is no real Razorpay key. This is the same answer `/public/integrations` gives as `payments` and the finance pages give as "not integrated yet".
- An Admin's manual "Run reconciliation" (`POST`, `reconciliation.run`) is unchanged.
- The 30 old rows are not deleted. They are harmless history.

## Admin 14 / student F-12: Sessions evicted by a new sign-in

**Behaviour:** the caps are unchanged (staff 3, students 2). With `TD_SIMPLE_AUTH`, the oldest session without an attempt is revoked with `end_reason = session_cap_evicted` (`sessions/login.py`).

**What the signed-out browser receives** on its next API call (`sessions/resolver.py`):

- **Already sent before this change:** `401` `code: session_revoked`, `reason: session_cap_evicted`. `reason` is the end reason after the user-safe filter.
- **Added now:** a specific `detail`.

  | `reason` | `detail` |
  |---|---|
  | `session_cap_evicted` | "You were signed out because your account signed in on another device and only a limited number of devices can stay signed in at once." |
  | `replaced_same_device` | Specific message |
  | `user_revoked_other` | Specific message |
  | `password_changed` | Specific message |
  | Any other reason | The generic "You have been signed out" |

- The reason code stays `session_cap_evicted`, not `superseded`:
  - The SPA already knows that code (`DevicesAndSessions.tsx` `END_REASONS`).
  - The Postgres tests assert it.
  - It is already on the user-safe list.

**Why the user still sees nothing specific:** in the SPA, `lib/api/client.ts` handles any 401 `session_revoked` by redirecting to `/login?next=…&reason=session_revoked`. That drops `problem.reason`. The login page (`app/(public)/login/page.tsx` `REASONS`) then shows "You were signed out. Please log in again."

**What the SPA needs** (not done here):

1. In the 401 branch of `client.ts`, when `problem.reason` is present, pass it on, e.g. `reason=session_cap_evicted`, or a second parameter `why=<problem.reason>`.
2. Add a `REASONS` entry on the login page: `session_cap_evicted: "You were signed out because your account signed in on another device."` Alternatively, show the problem `detail` that the API now sends.

**QA note:** this also explains the harness sign-outs (admin run 9fbdd251, student run 5f3a1867). Run QA builds that share an account one at a time.

## F-15: Review only (no change)

**Trainer → `GET /mentor/students` 200**

- Route: `placement/mentoring.py`. It lists the active students of batches where the caller holds `mentor.notes.read`.
- The trainer holds that permission at batch scope (`S - B - P`). `docs/single-company/ws4.md` §83 keeps it on purpose: trainers read their own batch's learners' notes but cannot write them.
- **Intended per the matrix.** Scope is limited to the trainer's own batches. With no mentor bookings it returns only their roster.
- This is the same open owner question as D3 in `role-api-audit.md`. If "/mentor is admin-only" is the rule, set that cell to `-` and re-seed the live `role_permissions`.

**Content manager → `GET /admin/certificates` 200**

- Every `/admin/certificates/*` route needs `certificate.issue_manual` at platform scope (`learning/cert_admin.py`). The matrix gives it to the content manager (`- - - P P`, also in `docs/role-permission-matrix.md`).
- **Intended per the matrix.** The content manager issues and revokes certificates.
- The same permission also lets the content manager:
  - see certificate holders' email addresses;
  - approve or cancel the certificate email outbox;
  - change the `auto_send` setting.
- No Studio screen uses these routes. If certificate administration should be Admin-only, that is a matrix change (the content manager cell set to `-`, plus a live re-seed), not a bug.

**Also seen (`staff-portals.md` section 2):** `admin/approvals` returns 200 with an empty list for non-admins. The handler filters to the caller's own requests. No leak, no change.

## Tests

The Firestore emulator ran at 127.0.0.1:18080, with `TD_TEST_NO_PG=1` and no parallelism. It was started for this run and then stopped.

**New tests:**

| Test | What it checks |
|---|---|
| `tests/parity/test_live_audit_api.py::test_evaluator_reads_own_batch_and_roster_only` | The real RBAC checker over the catalogue. An evaluator at batch A gets 200 on `batches/A` and `/members` (roster = the A student), `?mine=true` and `/batches` list only A. It gets **403** on batch B and its members, and 404 on an unknown batch. Writes, `/sessions` and `/attendance` on A stay 403. The trainer still reads. The content manager still gets 403, and its `?mine=true` is empty. |
| `tests/parity/test_live_audit_api.py::test_scheduled_reconciliation_skips_without_gateway` | No gateway: no run and no row. Gateway connected: one run (`system:beat`). |
| `tests/admin/fs/test_admin_access_http.py::test_dashboard_headline_counts_leave_out_synthetic_accounts` | A signed-in synthetic QA user is not counted in `sessions.active`, `new_7d`, `new_30d` or `learners`. It is still counted in `users.total`. |
| `tests/identity/fs/test_session_revoked_reason.py` (2 tests) | With simple auth, three sign-ins as a student mean the first browser gets `401 session_revoked`, `reason=session_cap_evicted`, with a detail naming the other device; the newer sessions keep working. A revocation with a reason that is not user-safe still returns `security_action` and the generic detail. |

**Results:**

| Run | Result |
|---|---|
| New files (`test_live_audit_api.py`, `test_session_revoked_reason.py`) | 4 passed |
| `test_admin_access_http.py` (incl. the new test), `test_rbac_audit.py`, `test_http_identity.py`, `test_jobs_parity.py` | 24 passed |
| `tests/identity/fs/test_fs_rbac_orgs.py`, `test_http_sessions_rbac.py` | 12 passed |
| `tests/identity/fs/test_http_orgs.py` | 3 passed |

`ruff check` and `ruff format --check` are clean on every changed file.

## Files changed

- `apps/api/app/modules/orgs/router.py`: `BATCH_READ_PERMISSIONS`, `can_read_batch`, `_require_batch_read`; the batch read routes and `list_batches` use them.
- `apps/api/app/modules/admin/accounts.py`: "Signed in now" leaves out synthetic accounts.
- `apps/api/app/modules/commerce/tasks.py`: the scheduled reconciliation is skipped while no gateway is connected.
- `apps/api/app/modules/sessions/resolver.py`: `_REVOKED_DETAIL`, a specific `detail` on `401 session_revoked`.
- `apps/api/app/modules/support/service.py`: comment recording the F3 decision.
- Tests:
  - `apps/api/tests/parity/test_live_audit_api.py` (new)
  - `apps/api/tests/identity/fs/test_session_revoked_reason.py` (new)
  - `apps/api/tests/admin/fs/test_admin_access_http.py` (one test added)
- `functions-lms/app/**`: re-copied by `build.py`.

## Live checks after the deploy

1. As qa-evaluator:
   - `GET batches/01a1ca9b-…` and `/members` return 200.
   - `batches?mine=true` lists "Generative AI".
   - `/evaluator/integrity` makes no 403 call, and its Batch filter lists the batch.
   - A batch the evaluator is not granted returns 403.
2. As qa-content: `batches/{id}` still returns 403.
3. `/finance/reconciliation`: no new "Razorpay 0 orders" row appears after the next full hour.
4. Admin dashboard "Signed in now":
   - It drops by the number of signed-in QA sessions **if** the QA users are flagged `is_synthetic`.
   - Check the flag in Firestore `users` if it does not drop.
5. Sign in as a QA student in 3 browser contexts, one after another, then call `GET me` from the first context. Expect `401 session_revoked`, with `reason: session_cap_evicted` and the new detail. Run this alone, not while other builds use that account.
