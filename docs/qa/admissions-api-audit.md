# Admissions API audit (Firestore stack): 2026-11-14

Scope: `apps/api/app/modules/admissions/` (`admin.py`, `service.py`, `courses.py`, `public.py`, `onboarding.py`, `letters.py`, `store_specs.py`). These are the endpoints behind Admin › Payments › Admissions, checked against the live stack (`TD_STORE_ADMISSIONS=firestore`, no Postgres). Permissions: `payment.read`, `payment.verify`, `payment.reverse` and `price.manage` (Admin holds all of them).

## Live read-only check (billing-f4fe3, `(default)` DB)

| Collection | Docs |
|---|---|
| `lms_admission_fee_plans` | 1 |
| `lms_admission_pay_settings` | 1 (doc `1`; phone set, UPI ID empty) |
| `lms_course_status` | 1 |
| `lms_uniq_admissions_afp_course` | 1 |
| registrations / claims / events | 0 (collections not created yet) |

Owner's plan: slug `nextgen-career-accelerator-2026`, title "NextGen Career Accelerator 2026", `fee_paise` 500000, `active` false, `policy` full, `min_first`/`access_min` 500000, `batch_id` set, `course_id` null, `schedule` `[{"Full fee", 500000}]` (stored as canonical JSON). Its course status is `coming_soon`. It is stored as expected.

- `GET https://techdrona-lms-app.web.app/api/public/admissions/plans/nextgen-career-accelerator-2026` returns 200 with `active:false`, `course_status:"coming_soon"`, `registration_open:false` and `pay_configured:true`. This is by design: the plan is served while the course isn't open, so existing registrants can still pay. The website must gate on `registration_open`, not on a 200 response. The header is `Cache-Control: private, no-store`.
- `GET /api/public/admissions/plans/no-such-course` returns 404 `not_found`.
- `GET /api/public/courses/status` returns 200 with `Cache-Control: public, max-age=30, s-maxage=60` (60 s at the CDN). It lists 8 slugs, all `coming_soon`.

**Composite indexes:** none needed. The SQL-on-Firestore engine pushes down only `==` and `in` filters, with no `order_by`. Sorting, `ilike` and cursors run in memory, so single-field indexes are enough. There is no `gcloud firestore indexes composite create` to run.

## Endpoints

| Endpoint | Perm | Status | Fix / note |
|---|---|---|---|
| GET `/admin/admissions/plans` (list + `pay` + non-archived `batches`) | read | OK | The SPA's `?edit=<slug>` is served from this list; there is no get-by-slug route and none is needed |
| PUT `/admin/admissions/plans` (create / update / activate / deactivate) | price.manage | **Fixed** | (1) Saving an edited plan under a changed slug silently created a **second** plan. A new optional `fee_plan_id` field fixes this: when it is sent, a different slug returns 409 `slug_locked` and a missing plan returns 404. (2) `course_id` was not validated, so a typo only failed later at enrolment. It now returns 422 `unknown_course`. Fee 0 or below ₹1 returns 422 `invalid_plan`; a negative fee returns 400 (request validation); an instalment sum that doesn't equal the fee returns 422 `invalid_plan`; an unknown batch returns 422 `unknown_batch`; activating without pay-to details returns 422 `pay_to_missing`. A refused save stores nothing. **Follow-up fixes:** (3) The response now adds `course_status` (the switch) and `effective_status` (what students see), so the SPA can warn when deactivating makes an open course read closed. (4) The `pay_to_missing` check used to run after `courses.ensure_row` inserted a status row for a new slug. It now runs before any write, and a test confirms that no orphan course row or plan remains |
| POST `/admin/admissions/plans/{slug}/active` `{active: bool}` (**new**) | price.manage | Added | Switches a plan on or off without resending the whole plan, so there is no lost update. Activating checks the fee (422 `invalid_plan`) and the pay-to details (422 `pay_to_missing`). Unknown slug: 404. Missing or extra body field: 400. The response matches PUT |
| PUT `/admin/admissions/pay-settings` | price.manage | OK | Needs a phone or a UPI ID (422 `pay_to_required`) |
| GET `/admin/courses/status` | read (**was** price.manage) | Fixed | Now aligned with the plans list (`payment.read`). There is no personal data in it, and changing a status still needs `price.manage`. Rows carry `course_slug`, `title`, `status`, `effective_status`, `updated_at`, `fee_paise`, `plan_active` and `batch` |
| PUT `/admin/courses/{slug}/status` | price.manage | OK | `open` without an active plan with a fee returns 409 `no_fee_plan` |
| GET `/public/courses/status` | public | OK | CDN 60 s |
| GET `/public/admissions/plans/{slug}` | public | OK | Returns 404 only when there is no plan or the fee is 0 |
| GET `/admin/admissions/overview` | read | OK | Loads every event to pick the newest 20 (fine at this volume) |
| GET `/admin/admissions/claims` (queue, `status`, `registration_id`, cursor) | read | OK | |
| GET `/admin/admissions/registrations` (`status`, `course_slug`, `q`, cursor) | read | **Fixed** | `last_utr` / `last_paid_on` / `last_claim_status` showed the **oldest** claim on Firestore: the engine ignores Postgres `DISTINCT ON`, and the dict comprehension kept the last row. It now keeps the first row (the newest). `q` does a full scan in memory (fine at this volume) |
| GET `/admin/admissions/registrations/{id}` | read | OK | |
| PATCH `…/{id}/contact` | verify | OK | Invalid phone or email returns 422 |
| POST `…/{id}/payments` (record payment) | verify | OK | |
| POST `…/{id}/fee` | reverse | OK | A fee below the verified amount returns 422 `below_verified`; a fee of 0 (waiver) is allowed |
| POST `…/{id}/status` (rejected / cancelled / completed / reopen) | verify | OK | |
| POST `…/{id}/enrol` | verify | OK | When the student isn't eligible, or the plan isn't linked, the request is refused |
| POST `…/{id}/login-email` | verify | OK | Email isn't integrated, so it returns `reason: email_not_connected` and the temporary password once |
| POST `/claims/{id}/verify` / `needs-info` / `reject` / `reverse` / `release-locks` | verify / reverse | OK | |
| POST `/claims/{id}/verify-and-enrol` | verify | OK | No batch on the request or the plan returns 422 `batch_required`; an unknown batch returns 422 `unknown_batch`. Both roll the verification back |
| GET `/claims/{id}/proof`, `/proof/file`, `…/{id}/resume` | read | OK (not re-tested) | |
| GET `…/{id}/letter`, POST `/letters/drafts`, GET/PUT `/letter-settings` | read / verify | OK | Covered by `tests/admissions/firestore/test_letters.py` |

## State rules (unchanged, by design)

- **Activating a plan without a batch or course link** is allowed. "Verify & add to batch" asks for a batch (`batch_required`), and automatic enrolment after verifying returns `warning: "Payment saved, but enrolment didn't finish: …"`. The SPA already flags "Not linked".
- **Deactivating a plan while the course is open** leaves the switch at `open`, but `effective_status`, the public map and the public plan all read `closed`/`registration_open:false`, and new registrations get 409 `registration_closed`. Reactivating the plan reopens registration without touching the switch. Payments on existing registrations stay allowed.

## Tests

- New: `apps/api/tests/admissions/firestore/test_admin_http.py` (6 HTTP tests plus 1 permission test, Firestore emulator, no Postgres). It covers plan validation, create/edit/activate/deactivate, `slug_locked`, `no_fee_plan`, the public plan and status, the registrations list (filters, last payment, paging, search), detail, queue, overview, and every panel and queue action.
- `TD_TEST_NO_PG=1 pytest tests/admissions`: 33 passed, 21 skipped (Postgres-only).
- `ruff check` and `ruff format --check` are clean. `openapi.json` was regenerated (`fee_plan_id` and the `/active` route added).

## SPA alignment

- When editing a saved plan, send `fee_plan_id` (from the list) in the PUT body and make the slug field read-only. Handle 409 `slug_locked` and 404.
- Show `errors[0].message` for `unknown_course`.
- On the course status rows, show `effective_status` (for example: "Open, but reads Closed: fee plan inactive").
- Use `POST admin/admissions/plans/{slug}/active` with `{"active": true|false}` for the Activate/Deactivate toggle instead of a full PUT. Read `course_status` / `effective_status` from the PUT or POST response to warn when "open" now reads "closed".
