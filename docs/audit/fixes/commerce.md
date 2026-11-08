# Fixes: commerce + entitlements (agent key `commerce`)

Owned paths: `apps/api/app/modules/commerce/**`, `apps/api/app/modules/entitlements/**`, new migration `commerce_0003`, `apps/api/tests/{commerce,entitlements}/**`.
Regression tests: `apps/api/tests/commerce/test_audit_fixes.py` (20 tests). Two existing tests were updated where the fix changes intended behaviour; see the notes after the table.

## Refund state machine (COM-01/02/03, E2E-03)

Decision: access is revoked when the refund is approved, and stays revoked while the provider refund is retried. It is restored only if the provider confirms the refund failed. BR-ENT-10 says "an approved refund revokes", and revoking at approval stops the customer using the content while the refund is in flight.

| From → to | Trigger | Effects |
|---|---|---|
| `requested` → `approved` | Finance decision or Dual approval | Order row is locked. The amount must be ≤ `total − refunds already approved/processing/processed` (rule-based student refunds are also capped at `refundable_paise`). The amount is reserved in `orders.refunded_paise`, which has a DB CHECK of ≤ total. All of the order's entitlements are revoked (order items, coupon grant, subscription), together with the certificates issued under them. Exceptions: reason `price_adjustment` or `duplicate_payment`, or a request that names specific `order_item_ids`. Then the refund is submitted to the provider. |
| `approved` (no gateway id) → `processing` | Submit succeeds, either immediately or via the `commerce.refund_submit_retry` beat job (2 min, `critical` queue, exponential backoff) | Re-submission is idempotent: a provider refund that already has `notes.refund_id` is adopted rather than created again. After 5 failed attempts the job emits `commerce.refund_submit_stuck` and writes an audit row. |
| `processing` → `processed` | `refund.processed` webhook, hourly reconciliation, or the dev fake auto-settling | Order and payment become `refunded` / `partially_refunded`. The GST credit note is issued **only here**. Emits `refund.processed`. |
| `processing` → `failed` | `refund.failed` webhook or reconciliation | The reservation is released. The entitlements this refund revoked are reinstated (`restored` event, `entitlements.reinstate`). Emits `commerce.refund_failed` and writes an audit row. No credit note is issued. |

## Results

| ID(s) | Severity | Fix summary | Files | Regression test | Result |
|---|---|---|---|---|---|
| COM-01 | Critical | Revocation is decided by refund intent, not by the amount. A placement package refunded net of consumed sessions now revokes the entitlement and its quotas. Added the finance-only reason `price_adjustment` (migration). | service.py, schemas.py, commerce_0003 | `test_com01_placement_refund_with_consumed_sessions_revokes_access`, `test_com01_price_adjustment_keeps_access` | Fixed+tested |
| COM-02 | High | Submit and retry job (`submit_refund`, `retry_refund_submissions`, beat `commerce.refund_submit_retry`) with backoff, an alert, and idempotent adoption of a provider refund that already exists. Added `fetch_payment_refunds` to the gateways (Razorpay adapter is unverified). | service.py, tasks.py, gateway.py, policy.py, commerce_0003 | `test_com02_refund_submitted_during_outage_is_retried`, `test_com02_resubmit_adopts_refund_the_provider_already_has` | Fixed+tested |
| COM-03 | High | Credit note is issued only once the refund is `processed`. On `failed`, entitlements are reinstated, the reservation is released and an alert event is emitted. | service.py, entitlements/service.py | `test_com03_provider_refund_failure_reinstates_access_without_credit_note` | Fixed+tested |
| E2E-03 | Medium | The dev fake gateway singleton (`auto_settle_refunds=True`) returns refunds already settled, and they go through the same `apply_refund_state` path as the webhook. Hourly reconciliation now also settles `processing` refunds, which covers missed webhooks in production. Order JSON now exposes `refunded_paise`. | gateway.py, service.py, admin.py | `test_e2e03_dev_fake_gateway_completes_refunds`, `test_com13_reconciliation_settles_processing_refunds` | Fixed+tested |
| COM-11, ADM-24 | Critical | `check_refund_amount` runs at request time, at decision time (order row locked) and inside `execute_refund`. `orders.refunded_paise` has `ck_order_refunded` (`0 ≤ refunded ≤ total`). | service.py, router.py, models.py, commerce_0003 | `test_com11_adm24_cumulative_refunds_cannot_exceed_paid` | Fixed+tested |
| COM-12 | Medium | When a refund revokes access, certificates for the product's courses are revoked through `learning.service.revoke_certificate` (audited, emits `learning.certificate_revoked`). For `all_courses` products this covers certificates issued during the entitlement. Courses still covered by another live entitlement are skipped. | service.py | none (needs learning enrolment/certificate fixtures; logic exercised only by code path) | Fixed, not covered by a dedicated test |
| COM-04 | High | `orgs.member_removed` outbox handler (`entitlements.on_member_removed`, registered by `entitlements.router`). It ends the seat using the BR-ENT-16 return rules (a seat is lost only once the allowance is exhausted, because removal cannot be refused), promotes the waitlist, and cancels the user's waitlist entries. | entitlements/service.py, entitlements/router.py | `test_com04_member_removal_ends_seat_and_promotes_waitlist` | Fixed+tested |
| COM-05 | High | Disputes also suspend, restore or revoke the subscription entitlement, found through `payment.subscription_id` or `order.subscription_id`. A lost chargeback sets `order.refunded_paise = total`. | service.py | `test_com05_subscription_dispute_suspends_then_revokes` | Fixed+tested |
| COM-10 | Medium | `POST /commerce/subscriptions` accepts `billing{name,state_code,gstin}`, which is stored on `subscriptions` (migration). Every debit invoice uses IGST or CGST+SGST and the place of supply based on the buyer's state. | service.py, router.py, schemas.py, models.py, commerce_0003 | `test_com05_subscription_dispute_suspends_then_revokes` (asserts IGST, place of supply 29) | Fixed+tested |
| COM-13 | Medium | Webhook retries use exponential backoff (`next_attempt_at`) for 72 h after receipt, replacing the fixed 8 attempts. A row becomes `failed` only after that and then emits `commerce.webhook_failed`. Reconciliation now also settles `processing` refunds, re-submits refunds that never reached the provider, and re-syncs live subscriptions. The stale docstring is corrected. Requiring queue mode in production needs core (see Requests). | webhooks.py, admin.py, policy.py, commerce_0003 | `test_com13_webhook_retry_horizon_then_failed_alert`, `test_com13_reconciliation_settles_processing_refunds`, updated `test_refetch_failure_makes_no_state_change_and_is_retried` | Fixed+tested (production gate: Request) |
| COM-16 | Medium | Plan change now adds the add-on **before** the plan update and deletes it again if the update fails (`delete_subscription_addon`; Razorpay adapter unverified). `mandate_max_amount_paise` is no longer raised in the DB only. | billing.py, gateway.py | none (existing plan-change tests pass) | Partly fixed. Deferred: rejecting or re-authorising upgrades above the authorised mandate maximum. Razorpay's UPI mandate max-amount semantics need provider confirmation, and enforcing the current value would block every upgrade. |
| COM-17 | Medium | Cancelling a subscription now writes a real in-app confirmation through `notifications.notify`, and `confirmation_sent` reflects whether that succeeded (it was hard-coded `True`). Also emits `subscription.cancel_requested`. | service.py | covered by existing cancel tests | Partly fixed. Email consumers: Request |
| COM-20 | Low | Termination end date is `min(current ends_at, termination + 7 d)`. | entitlements/service.py | `test_com20_termination_never_extends_access` | Fixed+tested |
| COM-21 / 60 s grant cache after revoke | Low | `cache.bump_after_commit` (SQLAlchemy `after_commit`) bumps the version again as soon as the revoking transaction commits, so it no longer waits for the outbox relay. | entitlements/cache.py, entitlements/service.py | `test_com21_revoke_bumps_cache_version_after_commit` | Fixed+tested (hook body; the concurrency race was not reproduced) |
| COM-22 | Low | Razorpay create order sends `payment_capture: 1`. | gateway.py | none (provider call) | Fixed, not verified against Razorpay |
| COM-24 (commerce part) | Low | Webhook docstring drift fixed. | webhooks.py | none | Fixed. Deferred: `FakePaymentProvider.name="razorpay"`. The DB CHECKs limit `gateway` to razorpay/cashfree/offline_po, production refuses the fake, and renaming would need a cross-table migration. |
| COM-19 | Low | No change. The API spec example (api-specification.md:1844) specifies CGST 20015 / SGST 20016. | none | none | Deferred: the spec wins, and a change needs CA confirmation |
| ADM-25 (commerce side) | Critical | `commerce.refund`, `coupon.activate`, `price.create`, `contract.terminate` and `entitlements.grant.bulk` are registered as admin `ApprovalHandler`s that delegate to `admin.execute_approval`. Rejecting or cancelling a refund approval rejects the refund. These requests now appear in `/admin/approvals` for the eligible second approver and can be decided there. | billing_approvals.py | `test_adm25_commerce_approval_visible_and_decidable_in_admin_queue` | Fixed+tested (web "Decide" button: Request) |
| ADM-26 | High | Setting `max_redemptions: null` (unlimited) on a capped coupon counts as loosening and needs Dual approval. | router.py | `test_adm26_coupon_patch_to_unlimited_needs_dual` | Fixed+tested |
| ADM-23 (commerce part) | Low | An expired commerce approval is persisted as `expired` and the route returns 409 without raising. | router.py | `test_adm23_expired_commerce_approval_is_persisted` | Fixed+tested |
| ADM-32 (API part) | Medium | Keyset cursors (`cursor`, `page.next_cursor`/`has_more`) on `/finance/orders`, `refunds`, `subscriptions`, `invoices` (plus a server-side `invoice_type` filter), `coupons`, `contracts` and `/me/orders`. Refund eligibility is now computed per page instead of for every refund. | router.py | covered by existing list tests | Fixed (web paging: Request) |
| DB-07 | Medium | `commerce_0003` adds `>=0` CHECKs on 7 columns, `ck_oi_total` and `ck_order_refunded`. Each is added NOT VALID and then validated when no existing row violates it. | commerce_0003 | `test_db07_money_checks` | Fixed+tested |
| FE-26 / FE-27 (backend) | Medium | `GET /commerce/orders/{id}` returns `checkout` for unexpired pending orders. Order creation resumes a matching pending order (same user, price, coupon, state and total), returning `resumed: true`, so a reload does not create a duplicate order or coupon reservation. | service.py, router.py | `test_fe26_fe27_pending_order_resumes_and_reload_does_not_duplicate` | Fixed+tested (redirect: Request) |
| INV-15 | Medium | The backend already rejects recurring prices on quote and order (`pricing.build_quote`, `not_one_time`). | none | `test_inv15_recurring_price_cannot_be_bought_as_one_time_order` | Not reproduced on the backend. The web routing is wrong: Request |
| E2E-04 | Medium | `consent_required` for a missing `security_monitoring` consent now has an accurate title and detail ("Turn on account protection to buy a paid plan" / "Paid plans need 'Account protection and single-user licence checks'…"), plus `purposes`, `reason` and a `grant` action (`POST /me/consents`, which also needs `notice_version`). | service.py | `test_e2e04_missing_monitoring_consent_has_accurate_error` | Fixed+tested (inline toggle in the web: Request) |

Not in my paths (for reference): COM-06, 07, 08, 09, 14, 15, 18 and 23 belong to core, worker, compose, notifications or CI owners.

Updated existing tests:
- `test_coupons_refunds_subscriptions.py::test_refund_within_rule_revokes_and_issues_credit_note`: the credit note is now expected after `processed`, not at approval (COM-03).
- `test_checkout_webhooks.py::test_refetch_failure_makes_no_state_change_and_is_retried`: the retry now honours `next_attempt_at` (COM-13).

The audit probes in `tests/_audit_scratch/commerce/test_probe_money.py` that asserted the buggy behaviour now fail as expected: the COM-01, 02, 03, 05/10, 11 and 20 probes. The ops probes for ADM-24 and ADM-26 now pass.

## Requests

1. **core** (`app/core/startup_checks.py`): when `APP_ENV=production`, refuse `TD_COMMERCE_WEBHOOK_MODE != "queue"` (COM-13). Also: `.env.example` should gain `TD_COMMERCE_WEBHOOK_MODE` (COM-18).
2. **web** (`features/commerce/components/Checkout.tsx`):
   - FE-27: after `POST commerce/orders`, `router.replace('/app/checkout/{order_id}')`. Treat `resumed: true` as success.
   - E2E-04: on `consent_required` with `purposes` containing `security_monitoring`, show the API `title`/`detail` once and offer an inline "Turn on and continue". That button should `POST /me/consents {purpose:'security_monitoring', action:'granted', notice_version}` and then retry the order without asking for billing details again.
   - INV-15: route recurring prices (`is_recurring`) to `POST /commerce/subscriptions` (now accepts `billing`) plus Razorpay subscription checkout and `/confirm`.
3. **web** (`OrderStatus.tsx`, FE-26): use `checkout` from `GET /commerce/orders/{id}` to show "Complete payment".
4. **web** (`features/finance/*`, `ApprovalsQueue.tsx`):
   - ADM-25: commerce approvals now appear in `/admin/approvals`. Show Decide for them (don't hide it on "Awaiting second approver" for a different viewer) and add labels for `commerce.refund`, `commerce.coupon.activate`, `commerce.price.create`, `commerce.contract.terminate` and `entitlements.grant.bulk`.
   - ADM-32: follow `page.next_cursor` and use `invoice_type` server-side.
   - New refund reason `price_adjustment` (keeps access) in the finance refund form.
5. **notifications / wiring** (COM-17):
   - Consumers for `invoice.issued` / `order.paid` (invoice email), `subscription.cancel_requested` (email confirmation) and the 7-day annual renewal reminder.
   - Alert routing for `commerce.refund_failed`, `commerce.refund_submit_stuck` and `commerce.webhook_failed`.
6. **learning** (optional, COM-12): a public "revoke certificates for user+courses" helper would avoid commerce querying `learning.models.Certificate` directly. Commerce currently calls the existing `learning.service.revoke_certificate`.

## Commands and results (run from `apps/api`)

```
TD_TEST_DB_NAME=techdrona_fix_commerce TD_TEST_RESET_DB=1 .venv/Scripts/python -m pytest tests/commerce tests/entitlements -q
  -> 65 passed
TD_TEST_DB_NAME=techdrona_fix_commerce_2 TD_TEST_RESET_DB=1 .venv/Scripts/python -m pytest tests/admin tests/orgs tests/rbac -q
  -> 60 passed
TD_TEST_DB_NAME=techdrona_fix_commerce_2 TD_TEST_RESET_DB=1 .venv/Scripts/python -m pytest tests/authz tests/integration -q
  -> 27 passed
.venv/Scripts/python -m ruff check app/modules/commerce app/modules/entitlements tests/commerce tests/entitlements migrations/versions/commerce_0003_money_integrity.py
  -> All checks passed
.venv/Scripts/python -m ruff format --check (same paths) -> already formatted
.venv/Scripts/python -m mypy app/modules/commerce app/modules/entitlements -> Success: no issues found
Audit probes tests/_audit_scratch/commerce + admin/ops (3): 11 passed, 6 failed — the 6 failures are the bug-asserting probes listed above.
```
