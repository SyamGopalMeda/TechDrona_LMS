# Admin › Payments › Admissions: control audit (2026-11-14)

Scope: `apps/lms-spa/src/features/admissions/*` (the SPA source of truth) for the four pages
`/finance/admissions` (+ `#course-status`), `/finance/admissions/verify`,
`/finance/admissions/registrations` (+ detail) and `/finance/admissions/plans` (`?edit=<slug>`).
Each control was checked against `apps/api/app/modules/admissions/admin.py` / `service.py` /
`courses.py`: request/response shape, error handling, visible feedback, state refresh.
Static review plus unit tests (vitest); no live run in this pass.

Status: **OK** = works as intended · **fixed** = changed in this pass · **issue** = open (see notes).

## Fee plans: `/finance/admissions/plans`

### Why "Edit" seemed not to work (root cause)

1. The page order was: global *Payment details* form → plan form → plans table. The plan form
   opened **above** the table, after the tall Payment details card.
2. The scroll-into-view effect was keyed on a boolean `formOpen` (`form !== null`). Opening
   `?edit=<slug>` (the link from Courses › "Set the fee" and the site-catalogue card) already
   opened the form, so `formOpen` was `true` before the admin ever clicked anything. Pressing
   **Edit** on a table row then only replaced the form state: `formOpen` stayed `true`, the effect
   didn't run again, nothing scrolled. The form changed off-screen (and when it was the same
   plan, it didn't change at all), so the click looked dead.
3. Save errors (for example `pay_to_missing` when activating) were shown by an `InlineProblem`
   at the **top** of the page, also off-screen, so a failed save looked like nothing happened too.

The fix doesn't patch the scroll. The plan form is now a modal dialog (native `<dialog>`, focus
moves into it), so Edit always responds visibly, wherever the row is.

### Controls

| Control | Status | Change |
|---|---|---|
| Page layout (order) | fixed | Course list first, then a separate "Default payment details (used when a course has none)" card. The plan form is a dialog. |
| Course list source | fixed | One row per **website course** (website catalogue via `loadCourseTitles` → `loadSiteCatalog`), including courses with no plan, plus plans for slugs not in the catalogue (marked "not in the website catalogue"). |
| Row: fee / instalments / LMS link / pays-to | fixed | Shows fee, "Yes · n (access from ₹…)" / "No (full fee)", "Batch: name (code)" / "LMS course (no batch)" / "Not linked" (warning), and whether the course uses its own UPI/bank or the defaults. Plan `problems[]` from the api are listed. |
| Row: Plan Active/Inactive badge | fixed | "Plan active" / "Plan inactive" / "No fee plan". |
| Row: registration status badge | fixed | From `GET /admin/courses/status`, showing the **effective** status (what students see). When a course is set to Open but the plan is inactive, the row says that students see it as Closed. If the status call fails (no `price.manage`), a note replaces the badges. |
| Row: Edit / Set up fee plan | fixed | Opens the plan dialog with the plan's values (or a new plan with the catalogue slug and title filled in). |
| Row: Activate | fixed (new) | `PUT /admin/admissions/plans` with the plan as it is and `active: true`. Toast says the next step is opening registration. An error (for example `pay_to_missing`) is shown next to the row. The list and statuses reload. |
| Row: Deactivate | fixed (new) | Asks first (explains that an open course then reads Closed), then saves with `active: false`. An error shows in the confirm dialog. |
| Row: Open registration / Registration status | fixed (new) | Link to `/finance/admissions#course-status` (that section scrolls itself into view). |
| Row: Registrations | fixed (new) | Link to `/finance/admissions/registrations?course=<slug>`. |
| "Add plan for another course" (header) | fixed | Was "Add fee plan" (inline form). Now opens the dialog with an editable slug, for a course the catalogue doesn't list. |
| `?edit=<slug>` deep link | fixed | Read through `useSearchParams`, handled once per value after plans load. Opens that course's plan, or "Set up fee plan" when it has none. |
| Dialog › Course & batch | fixed | Website course is **read-only** when the course is known. Course title. LMS batch select. LMS course id, with help that names the batch's course id and says to leave it empty. Client UUID check. "Not linked" warning. |
| Dialog › Fee | fixed | Fee (₹1 to ₹10,00,000, checked on the client). Allow instalments shows the schedule (label / amount / due, add up to 6, remove), the minimum first payment and the access threshold. The schedule total must equal the fee (same rule as `rules.clean_terms`). |
| Dialog › Where students pay | OK → fixed copy | Course UPI / payee / bank / instructions, with "leave empty to use the default payment details" and the current default shown. UPI format is checked. |
| Dialog › Status | fixed copy | "Fee plan active" with an explanation of how it relates to Courses › Open, and the `active` api error (`pay_to_missing`) shown under it. |
| Dialog › validation messages | fixed | Client and api 422 `errors[].field` are mapped to their fields (`fee_paise`→Fee, `schedule.N.amount_paise`→instalment N, …). Other problems show in the dialog, never at the top of the page. |
| Dialog › Save fee plan | fixed | On success: toast (it also says whether the plan is still inactive), dialog closes, list and statuses reload. A 202 approval_pending shows an info toast (before, it showed "saved"). |
| Dialog › Cancel / Esc / × | OK | Closes without a request (blocked while saving). |
| Full-fee plan → enabling instalments | fixed | `planToForm` copied `min_first = access_min = fee` and the `[Full fee]` schedule from a full-fee plan. Ticking "Allow instalments" then started with "minimum first payment = the whole fee". These fields now start empty for full-fee plans. |
| Default payment details › fields + QR preview | OK | Same fields as `AdmissionPayIn`. QR preview from the UPI ID. |
| Default payment details › Save | fixed | Errors (`invalid_mobile`, `invalid_upi`, `pay_to_required`) now show next to their field in the card (they used to be at the page top). Saving a plan no longer resets unsaved edits in this card (it used to be re-seeded on every plans reload). Approval_pending is handled. |

## Admissions overview: `/finance/admissions`

| Control | Status | Change |
|---|---|---|
| "Verify payments (n)" header button | OK | |
| KPI tiles (Waiting → verify, Registered → registrations) | OK | |
| Registrations by course table | fixed | The course name now links to `registrations?course=<slug>`, using the website title when there is one. |
| Recent activity "Open" links | OK | |
| Courses (`#course-status`) scroll on hash | OK | |
| Course status switch (Open / Coming soon / Closed) | OK | `PUT /admin/courses/{slug}/status`. Optimistic, rolls back on error. Toast. 202 → info toast and rollback. |
| `409 no_fee_plan` path | OK | Inline alert + "Set the fee" → `plans?edit=<slug>` (opens the plan dialog). |
| Course list completeness | fixed | Website courses the api doesn't know yet (no status row, plan or batch) were missing. They are now listed as Coming soon, so they can be opened (→ 409 → Set the fee). |
| Open-but-plan-inactive course | fixed | The switch showed "Open" while students saw Closed (`effective_status`). The row now warns about it and links to the plan. A fee that's set but on an inactive plan is also pointed out. The row title falls back to the api `title` before the slug. |
| "Open the fee plan" link | fixed | Was a plain `<a>` (full page reload). Now an SPA `Link`. |

## Verify payments: `/finance/admissions/verify`

| Control | Status | Change |
|---|---|---|
| Show filter (open / pending / needs_info / verified / rejected / reversed) | OK | `status` matches the api `ClaimStatus` literal. |
| Pagination (next / previous) | OK | Cursor list. |
| Receipt thumbnail → full size dialog | OK | `/proof/file` blob, revoked on unmount. |
| Receipt "Open receipt (PDF)" | fixed | A failure was stored in state but never shown (silent no-op, and the blank tab closed). It now shows "Couldn't open the receipt. Try again." and the button says "Retry receipt (PDF)". |
| Verify & add to batch (dialog) | OK | Body matches `AdmissionVerifyEnrolIn`. Checkbox and amount validated. Batch defaults to the plan's batch. Login details dialog, then the letter step (auto setting). |
| Approve / Approve part payment | OK | `AdmissionVerifyIn` (`checked` required). Toast + "Just decided" + reload. Warning toast on `warning`. |
| Reject (reason + release locks) | OK | `AdmissionRejectIn`. |
| Ask the student to correct it | OK | `needs-info`. |
| Reverse (verified filter) | OK | `AdmissionReasonIn`. Toast. |
| Allow reference again (rejected / reversed) | fixed | Gave no feedback. It now shows a success toast. The list reloads as before. |
| Just decided › Login details / Admission letter | OK | |
| Letter step (LetterStepDialog) | OK | Issue / correct / download / auto-open setting. Covered by `admission-letter.test.tsx`. |

## Registrations: `/finance/admissions/registrations` (+ detail)

| Control | Status | Change |
|---|---|---|
| Status filter, Search (Enter / button) | OK | `status`, `q` match the api. |
| `?course=<slug>` + "Show all courses" | OK | Sent as `course_slug`. |
| Pagination | OK | |
| Row checkbox / "Select enrolled without a letter" / Clear | fixed | The selection survived a filter or search change, so rows no longer visible could still go into the bulk letters. It is now cleared when the filter, search or course changes. |
| Preview & issue letters (bulk) | OK | Max 50. Reloads on done. |
| Send / Resend login email | OK | Confirm, then the login details dialog, then reload. |
| Issue / Open letter (row) | OK | Reloads on change. |
| Detail › Record a payment | fixed | "Received on" defaulted to the **UTC** date (yesterday before 05:30 IST). It now uses the local date. |
| Detail › Enrol now / Change status / Edit contact / Adjust fee | OK | Bodies match `AdmissionStatusIn`, `AdmissionContactIn`, `AdmissionFeeIn`. Errors inline in the dialog. Toast + reload. |
| Detail › payment row actions | OK | Same `ClaimActions` as the queue. Reloads the registration. |
| Detail › View resume | OK | Error shown in the page's inline problem. |
| Detail › Admission letter, LMS access, Send login email | OK | |

## API issues found (not changed here; the API is audited separately)

1. **Deactivating a plan silently closes an open course.** `courses.effective()` turns a course
   set to "open" into "closed" for students when its plan is inactive (or has no fee). Saving
   the plan with `active: false` gives no hint of this, and the `save_plan` response doesn't
   carry the course's status. The SPA now warns (confirm dialog + row note). The api could add
   the course's `status` / `effective_status` to the `save_plan` response.
2. **Permission mismatch.** `GET /admin/admissions/plans` needs `payment.read`, but
   `GET /admin/courses/status` needs `price.manage`. A payment-only admin sees the Fee plans
   list without registration status (the SPA now degrades gracefully). Consider `READ` for the
   status list.
3. **No partial update for plans.** Activate/Deactivate has to `PUT` the whole plan
   (`AdmissionPlanIn`), so a concurrent edit by someone else is overwritten (last write wins,
   no `updated_at` / ETag check). A `PATCH /admin/admissions/plans/{slug}` with `{active}`, or
   an `If-Match`, would be safer.
4. **`save_plan` side effects before validation.** For a new slug, `courses.ensure_row` runs
   before the `pay_to_missing` check. It is harmless only if the request transaction rolls back
   on the 422. Worth confirming that `ProblemError` rolls back `PrincipalDbSession`.
