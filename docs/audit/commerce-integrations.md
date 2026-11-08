# Audit: Commerce, entitlements, external integrations, background jobs, ops config (COM-)

Phase A (audit only). Auditor: commerce agent, 2026-11-03.
Probes: `apps/api/tests/_audit_scratch/commerce/` (`test_probe_money.py`, `test_probe_ops.py`).
Run them from `apps/api` with: `TD_TEST_DB_NAME=techdrona_audit_commerce TD_TEST_RESET_DB=1 .venv/Scripts/python -m pytest tests/_audit_scratch/commerce -q -s`.
Result: 14 passed. Each probe asserts the behaviour as it is today, so a passing probe documents a finding.
The existing suites `tests/commerce` and `tests/entitlements` also ran on the same DB: 45 passed.
Ops-config checks (compose, Dockerfiles, `.env.example`, CI) were done by a read-only sub-agent. Its key claims were re-checked as noted.

## Coverage inventory

| Feature/Req ID | Requirement source | Code location | Audit method | Result |
|---|---|---|---|---|
| FR-COM-002 GST-inclusive quote: split, intra/inter-state, half-up rounding | PRD FR-COM-002, ADR-0012 | `commerce/pricing.py:66-80,337-405` | probe + existing test | Verified OK, with a Low issue (COM-19) |
| FR-COM-007 coupons: caps, per-user, min order, new-users-only, college code, free access | PRD FR-COM-007 | `pricing.py:134-201`, `service.py:286-336` | existing tests (pass) + read | Verified OK |
| FR-COM-003/004 order → provider order → verify → fulfil, 30 min expiry | PRD, API spec §18 | `service.py:149-261,519-594` | existing tests + probe | Verified OK. A late capture on a cancelled order is honoured (probe) |
| Webhook HMAC (raw body, constant time, current+previous secret), dedupe, re-fetch, out-of-order/stale | ADR-0006 v0.4 | `gateway.py:302-344`, `webhooks.py`, `router.py:1215-1255` | probe + existing tests | Verified OK. Retry/queue weaknesses in COM-13 |
| Amount/currency mismatch on capture | ADR-0006 | `service.py:494-503` | read | Verified OK (audited, no fulfilment) |
| Duplicate grants | ADR-0006 | `entitlements/service.py:232-308`, unique indexes `ux_ent_*` | read + existing tests | Verified OK |
| FR-COM-008 refund rule (7 days, < 20 %, certificate, mock, placement deduction) | PRD FR-COM-008 | `service.py:1055-1129` | probe | Issue (COM-01, COM-11) |
| BR-ENT-10 refund revocation; credit notes | PRD BR-ENT-10, FR-COM-009 | `service.py:1207-1327` | probe | Issue (COM-01, COM-02, COM-03, COM-12) |
| BR-ENT-11 chargeback suspend/restore/revoke | PRD BR-ENT-11, FR-COM-012 | `service.py:1333-1379` | probe | Issue (COM-05). One-time purchases are OK |
| FR-COM-005 subscriptions, ₹15,000 mandate cap, 5-day grace, cancel | PRD FR-COM-005, BR-ENT-09 | `service.py:786-1038`, `billing.py:64-223` | existing tests + read | Partly OK. Issues COM-10, COM-16, COM-17 |
| FR-COM-006 plan change proration | PRD FR-COM-006 | `billing.py:105-223` | existing test + read | Maths OK. Issue COM-16 |
| FR-COM-009 invoice numbering (gap-free per series+FY, ≤ 16 chars), PDF | PRD FR-COM-009 | `service.py:600-678`, `documents.py` | probe (FY) + existing tests | Verified OK, apart from COM-10 |
| BR-ENT-15/16 seats, waitlist, reassignment | PRD BR-ENT-15/16 | `entitlements/service.py:931-1096` | existing tests + probe | Issue (COM-04) |
| BR-ENT-17/18 contract end/termination | PRD | `entitlements/service.py:1099-1171` | probe | Issue (COM-20, Low) |
| FR-ENT-001 checker covers each resource type; parent resolution; free; restricted | PRD FR-ENT-001, `core/access.py` | `entitlements/service.py:600-824`, `wiring.py:48-122,377-380` | read + existing test | Verified OK (lesson/resource→course, test→path/course, coding_problem→topic/course) |
| FR-ENT-003 60 s decision cache, invalidation | PRD FR-ENT-003 | `entitlements/cache.py` | read + existing tests | OK, with one race (COM-21, Suspected) |
| Razorpay / Cashfree adapters | ADR-0006 | `gateway.py:152-344` | read | Mostly OK. COM-22 Suspected; Cashfree is a stub (flag off) |
| VdoCipher adapter | ADR-0007 | `media/providers.py:95-152` | read | OK by reading (not run against the vendor) |
| Judge0 adapter | ADR-0005 | `coding/judge_gateway/judge0.py` | read | OK by reading. Queue wiring issue in COM-09 |
| SES / MSG91 adapters | PRD notifications | `notifications/adapters.py:121-154` | probe | **Not built** (COM-06) |
| Production refuses fakes and dev keys | brief, startup_checks | `core/startup_checks.py`, `worker.py` | probe | Issue (COM-07, COM-08) |
| Celery beat registration and queue consumers | ADR-0008 | `worker.py`, `core/jobs.py`, `docker-compose.yml` | probe (dump of the beat schedule) | Issue (COM-09, COM-14, COM-15) |
| Outbox handlers registered | ADR-0011 | `wiring.py`, `entitlements/service.py:184` | probe (dump of the handler list) | OK for the handlers that exist. Commerce events have no consumers (COM-17) |
| `.env.example` completeness, Dockerfiles, CI | brief | repo root, `.github/workflows` | sub-agent + spot-check | Issue (COM-18, COM-23, COM-24) |

## Findings

### COM-01: A partial refund of a placement package keeps the entitlement and the remaining quotas
- Severity: Critical
- Status: Confirmed
- Component: `apps/api/app/modules/commerce/service.py:1226-1236` (`execute_refund`, `full = r.amount_paise >= order.total_paise`) and `:1303-1316` (`apply_refund_state`)
- Requirement: PRD FR-COM-008 ("Placement packages: refundable minus consumed mentor sessions"); BR-ENT-10 ("An approved refund revokes the linked entitlement")
- Repro: `test_probe_money.py::test_placement_package_partial_refund_keeps_entitlement`
  1. Buy a ₹10,000 placement package that includes 4 mentor sessions at ₹1,000 each.
  2. Consume 1 session.
  3. Request the refund. Finance approves it, the provider settles it, and the `refund.processed` webhook arrives.
- Expected: ₹9,000 is refunded and the entitlement is revoked.
- Actual: ₹9,000 is refunded, the order becomes `partially_refunded`, and the entitlement stays **active** with 3 mentor sessions left. Any rule-based refund with a deduction leaves access in place.
- Evidence:
  ```
  eligibility {... 'eligible': True, 'refundable_paise': 900000 ...}
  decision 200 processing 900000
  after refund: order partially_refunded entitlement active mentor_left 3
  ```
- Root cause: "full" is decided by `amount >= order.total`. The placement deduction makes the amount smaller, so the code treats the refund as partial and revokes nothing.
- Recommended fix: decide revocation by refund intent, not by amount. When a refund request comes from the rule (eligibility) or covers every item, revoke all of the order's entitlements. Keep partial, unrevoked refunds only for an explicit finance "price adjustment" reason code.
- Suggested owner paths: `apps/api/app/modules/commerce/service.py`, `apps/api/app/modules/commerce/schemas.py`

### COM-02: A refund submitted during a provider outage is never retried; the customer loses access and no money is sent
- Severity: High
- Status: Confirmed
- Component: `service.py:1246-1252` (comment: "stays approved; retried by job"); `commerce/tasks.py` has no refund retry job
- Requirement: FR-COM-008 ("refund to original method via Razorpay"); ADR-0006
- Repro: `test_probe_money.py::test_refund_submit_outage_is_never_retried`. Set `fake_gw.unavailable = True` while finance approves.
- Expected: the refund is submitted later by a job.
- Actual: the refund stays `approved` with no `gateway_refund_id`. The entitlement is already revoked and the credit note is already issued. No task, beat entry or reconciliation step picks up `approved` refunds.
- Evidence: `approve during outage: 200 refund approved gw id None ent revoked`, `commerce task symbols mentioning refund: []`. The beat dump (`test_probe_ops.py::test_beat_schedule_and_queues`) has no refund job.
- Root cause: the promised retry job was never written.
- Recommended fix: add a beat job, `commerce.refund_submit_retry`, on the `critical` queue. It should submit `approved` refunds that have no `gateway_refund_id` (idempotent through `notes.refund_id`) and alert after N attempts.
- Suggested owner paths: `apps/api/app/modules/commerce/tasks.py`, `apps/api/app/modules/commerce/service.py`

### COM-03: A failed provider refund leaves access revoked and the credit note issued, with no compensation
- Severity: High
- Status: Confirmed
- Component: `service.py:1321-1323` (`gr.status == "failed"` only sets the status and writes an audit row)
- Requirement: BR-ENT-10; FR-COM-009 (a credit note should reflect an actual refund)
- Repro: `test_probe_money.py::test_gateway_refund_failure_leaves_access_revoked`
- Expected: the entitlement is restored (or a finance task is opened), and the credit note is cancelled or a follow-up is flagged.
- Actual: `refund failed entitlement revoked order paid credit_notes 1`. The customer has paid, has no access, no money comes back, and a GST credit note exists for a refund that never happened.
- Root cause: entitlements are revoked and the credit note is issued at approval time (`execute_refund`). The failure path never undoes either.
- Recommended fix: issue the credit note only on `processed` (it is already deduplicated there). On `failed`, restore the entitlements revoked with `source_ref=refund.id` and emit a finance alert event.
- Suggested owner paths: `apps/api/app/modules/commerce/service.py`

### COM-04: Removing a student from the org does not end the seat entitlement or release the seat
- Severity: High
- Status: Confirmed
- Component: `apps/api/app/modules/orgs/router.py:482-517` emits `orgs.member_removed`. No handler is registered for it (handler list in the `test_beat_schedule_and_queues` output). Seat counting is in `entitlements/service.py:853-862`.
- Requirement: PRD BR-ENT-16 ("Removing a student from the org (or revoking the seat) ends the contract entitlement at removal time"); FR-ORG-018
- Repro: `test_probe_money.py::test_member_removal_keeps_seat_and_blocks_waitlist`. One seat, two students: one is assigned, one is waitlisted. Then remove the assigned student's membership.
- Expected: the seat entitlement is revoked under the free-return/reassignment rules, and the waitlisted student is promoted.
- Actual: `pool after removal {'total': 1, 'used': 1, 'free': 0, 'waitlisted': 1 ...} removed student's seat entitlement: active`. The seat leaks and the waitlist stalls. The checker denies the removed user (`inactive_membership`), so this is not an access leak.
- Root cause: nothing consumes `orgs.member_removed`.
- Recommended fix: register an outbox handler in `wiring.py` that calls `revoke_seats` (system actor, `accept_seat_loss=True` or the documented default) for every live seat of that user in that org, then `promote_waitlist`.
- Suggested owner paths: `apps/api/app/wiring.py`, `apps/api/app/modules/entitlements/service.py`

### COM-05: Disputes on subscription debits never suspend or revoke access
- Severity: High
- Status: Confirmed
- Component: `service.py:1345-1356` (`apply_dispute` only finds entitlements joined through `OrderItem.order_id`; a subscription entitlement has `subscription_id`, not `order_item_id`)
- Requirement: BR-ENT-11, FR-COM-012
- Repro: `test_probe_money.py::test_subscription_charge_dispute_and_interstate_invoice`
- Evidence: `subscription entitlement after dispute open: active`, `... after chargeback lost: active`
- Recommended fix: when `pay.subscription_id` (or the order's `subscription_id`) is set, also act on `Entitlement.subscription_id == ...`.
- Suggested owner paths: `apps/api/app/modules/commerce/service.py`

### COM-06: SES email and MSG91 SMS adapters are not implemented, so production cannot send OTPs or emails
- Severity: High
- Status: Confirmed
- Component: `apps/api/app/modules/notifications/adapters.py:121-154` (`UnavailableAdapter`)
- Requirement: PRD notifications/OTP; deployment-and-operations.md (SES, MSG91)
- Repro: `test_probe_ops.py::test_ses_and_msg91_adapters_not_implemented`
- Evidence: `send -> email:ses adapter is not implemented yet (Planned)`, `send -> sms:msg91 adapter is not implemented yet (Planned)`. The production gate does not flag this (COM-07).
- Recommended fix: implement SES (boto3 `send_email`, configuration set) and MSG91 (DLT template ids) adapters. Until then, add `ses`/`msg91` to the production refusal list.
- Suggested owner paths: `apps/api/app/modules/notifications/adapters.py`, `apps/api/app/core/startup_checks.py`

### COM-07: The production startup gate accepts empty Razorpay credentials, the placeholder seller GSTIN/address, in-memory email and unimplemented adapters
- Severity: High
- Status: Confirmed
- Component: `apps/api/app/core/startup_checks.py:19-64`; `notifications/adapters.py:173`; `commerce/policy.py:76-84`
- Requirement: brief ("production startup refuses fakes & dev keys")
- Repro: `test_probe_ops.py::test_production_gate_gaps`
- Evidence:
  - `ses/msg91 + empty razorpay + placeholder GSTIN -> []`
  - `EMAIL_PROVIDER=memory -> []`
- The `memory` email adapter is selectable (`adapters.py:139`), but the fake check covers only `fake`/`console`. Invoices in production would carry the "DEV PLACEHOLDER — not a valid tax document" banner. `TD_COMMERCE_WEBHOOK_MODE=inline` is also accepted (see COM-13).
- Recommended fix: add these production checks:
  - `RAZORPAY_KEY_ID`, `RAZORPAY_KEY_SECRET` and `RAZORPAY_WEBHOOK_SECRET` are non-empty and the key id does not start with `rzp_test_`
  - `SELLER_GSTIN != PLACEHOLDER_GSTIN`, and no `PLACEHOLDER` in `SELLER_LEGAL_NAME`/`SELLER_ADDRESS`
  - `EMAIL_PROVIDER` is not `memory`
  - providers that are not implemented are refused
- Suggested owner paths: `apps/api/app/core/startup_checks.py`, `apps/api/app/modules/commerce/gateway.py`, `apps/api/app/modules/commerce/documents.py`, `apps/api/app/modules/notifications/adapters.py`

### COM-08: Celery workers and beat never run the production safety gate
- Severity: High
- Status: Confirmed
- Component: `apps/api/app/worker.py:109-133` (`create_celery` never calls `run_startup_checks`; only `main.create_app` and `coding/worker.py:386` do)
- Repro: `test_probe_ops.py::test_celery_worker_skips_startup_checks`. It sets `APP_ENV=production` and `PAYMENTS_PRIMARY_PROVIDER=fake`.
- Evidence:
  - `celery app created in APP_ENV=production with fake payments: techdrona`
  - `api -> UnsafeConfigurationError refusing to start in production: ...`
- Impact: the worker processes webhooks (queue mode), order expiry, reconciliation and refunds-related jobs, and could do so with the in-memory fake gateway in production.
- Recommended fix: call `run_startup_checks(get_settings())` in `create_celery()` after `wire_all()`.
- Suggested owner paths: `apps/api/app/worker.py`

### COM-09: Nothing consumes the `judge_*` Celery queues; beat pushes to `judge_assessment` every 10 s
- Severity: High
- Status: Confirmed (beat dump + compose)
- Component: `coding/tasks.py:78` (beat on `judge_assessment`); `docker-compose.yml:268` (`worker` queues: `critical,default,notifications,analytics,reports`); `docker-compose.yml:334` (`worker-judge` runs `python -m app.modules.coding.worker`, a DB poller and not a Celery worker)
- Requirement: ADR-0008 (`judge_*` queues); `docs/deployment-and-operations.md:152`
- Evidence (probe):
  - `BEAT coding.process_pending ... every=10.0 queue=judge_assessment`
  - `beat queues with no consumer: ['judge_assessment']`
- Impact: messages pile up in `redis-queue`, which is configured `noeviction` (`compose:109`, per the sub-agent) and will eventually fill. The submit paths also `send_task` to `judge_submit`/`judge_run` (`coding/service.py:577`). Whether judging itself works depends on the DB poller; that belongs to the coding area.
- Recommended fix: either run a Celery worker with `-Q judge_assessment,judge_submit,judge_run`, or remove the beat entry and the `send_task` calls if the DB poller is the design.
- Suggested owner paths: `docker-compose.yml`, `apps/api/app/modules/coding/tasks.py`, `apps/api/app/modules/coding/service.py`

### COM-10: Subscription debit invoices are always intra-state (CGST+SGST, seller place of supply)
- Severity: Medium
- Status: Confirmed
- Component: `service.py:944` (`split_inclusive(..., intra_state=True)`), `:959` (`place_of_supply = SELLER_STATE_CODE`). `create_subscription` takes no billing state.
- Requirement: FR-COM-009 ("CGST+SGST or IGST by state of supply")
- Evidence: `sub invoice 36 3806 3806 0` (CGST 3806, SGST 3806, IGST 0). Every out-of-state subscriber gets a wrong tax split.
- Recommended fix: capture `billing.state_code` (and GSTIN) at subscription creation, store it on `subscriptions`, and use it for each debit invoice.
- Suggested owner paths: `apps/api/app/modules/commerce/service.py`, `schemas.py`, `models.py` (+ migration)

### COM-11: Refund amounts are not limited to the remaining refundable amount (only the provider stops over-refunds)
- Severity: Medium
- Status: Confirmed (with the fake provider)
- Component: `service.py:1170-1175` (bound is `order.total_paise`, not total minus already refunded); `router.py:761-767` (finance override up to the order total, ignoring the placement deduction in `refundable_paise`)
- Repro: `test_probe_money.py::test_second_refund_can_exceed_order_total`. Refund ₹600 (processed), then refund ₹1,000 on a ₹1,000 order.
- Evidence: `r2 201 {"amount_paise":100000 ...}`, `refund rows total 160000`. A credit note is also issued for each refund.
- Recommended fix: limit the amount to `order.total - sum(approved/processing/processed)`. For rule-based requests, also limit it to `refundable_paise`.
- Suggested owner paths: `apps/api/app/modules/commerce/service.py`, `router.py`

### COM-12: Certificates are not revoked when a refund revokes the entitlement
- Severity: Medium
- Status: Confirmed (code reading + handler list)
- Component: there is no outbox handler for `refund.approved`/`refund.processed` or for `entitlement.revoked` with reason `refund` that calls `learning.service.revoke_certificate`. The registered handlers are listed in the probe output.
- Requirement: BR-ENT-10 ("Certificates issued under a refunded entitlement are revoked"); PRD scenario line 689
- Recommended fix: add a handler in `wiring.py` that, on `refund.approved` (goodwill), revokes certificates for the order's courses.
- Suggested owner paths: `apps/api/app/wiring.py`, `apps/api/app/modules/learning/service.py`

### COM-13: Webhook processing is inline by default, the retry gives up after about 8 minutes, and reconciliation covers only payments
- Severity: Medium
- Status: Confirmed (code reading)
- Component:
  - `core/config.py:110` (`TD_COMMERCE_WEBHOOK_MODE="inline"` default; not in `.env.example`; not enforced in production)
  - `webhooks.py:161-169` + `commerce/tasks.py:127-129` (60 s sweep, `WEBHOOK_MAX_ATTEMPTS=8`, then `status=failed` permanently)
  - `admin.py:546-600` (`run_reconciliation` only re-checks orders/payments)
- Requirement: ADR-0006 ("respond 200 fast; process asynchronously on the critical queue … retries with backoff")
- Impact: a provider API outage longer than about 8 minutes permanently drops refund, subscription (`charged`/`halted`) and dispute events. Nothing alerts on `failed` rows and nothing re-drives them.
- Recommended fix:
  - require `queue` mode in production
  - use exponential backoff based on `received_at`/`attempts` instead of a fixed count
  - extend reconciliation to refunds in `processing` and to active subscriptions
  - emit an alert event for `failed` webhook rows
- Suggested owner paths: `apps/api/app/modules/commerce/webhooks.py`, `tasks.py`, `admin.py`, `apps/api/app/core/startup_checks.py`

### COM-14: There is no beat leader lock, despite the docs
- Severity: Medium
- Status: Confirmed (sub-agent grep + spot-check: `TD_SCHEDULER_LEADER_LOCK_TTL_SECONDS` is in `.env.example:165`; no "leader" or lock code exists in `apps/api/app`)
- Requirement: ADR-0008 ("single replica with a Redis leader lock"); `deployment-and-operations.md:156`
- Impact: two schedulers during a rolling deploy double-fire every periodic job, including the 2 s audit seal and 5 s outbox relay. The jobs are idempotent, but load doubles.
- Recommended fix: implement the lock (for example a `redbeat`-style lock, or a Redis `SET NX PX` guard in a custom Beat scheduler), or correct the docs.
- Suggested owner paths: `apps/api/app/worker.py`, `docs/deployment-and-operations.md`

### COM-15: The `maintenance` queue has a worker but no producers; maintenance jobs run as `td_app` on `default`
- Severity: Medium
- Status: Confirmed (beat dump: queues used are `critical`, `default`, `judge_assessment` only)
- Component: `docker-compose.yml:283-294` (worker-maintenance `-Q maintenance`); `analytics/tasks.py`, `security/tasks.py` (default queue); `DATABASE_MAINTENANCE_URL` is not a Settings field
- Requirement: ADR-0008, `deployment-and-operations.md:65,151` (partition premake/drop, retention purge, `hmac_key_retire` on worker-maintenance)
- Recommended fix: route retention/partition jobs to `maintenance` with the maintenance DB role, or update the docs and drop the idle worker.
- Suggested owner paths: `apps/api/app/modules/*/tasks.py`, `apps/api/app/core/config.py`, `docker-compose.yml`

### COM-16: An upgrade can leave the provider and the DB out of sync, and the mandate ceiling is raised only in the DB
- Severity: Medium
- Status: Suspected (code reading; the Razorpay behaviour has not been verified)
- Component: `billing.py:173-187`
- Detail:
  - `update_subscription_plan` is called first, then `add_subscription_addon`. If the add-on call fails (`GatewayUnavailable`, or a 4xx surfacing as `ProblemError`), the DB transaction rolls back but the provider plan has already changed.
  - `mandate_max_amount_paise` is raised locally (`:187`). A UPI AutoPay mandate's maximum amount is fixed when the customer authorises it, so a larger next debit (new price plus proration) may be declined by the bank.
- Recommended fix: add the add-on first (or compensate on failure). Keep the mandate maximum set at creation, and reject upgrades whose next debit exceeds the authorised maximum (or require re-authorisation).
- Suggested owner paths: `apps/api/app/modules/commerce/billing.py`

### COM-17: Commerce events have no consumers: no invoice email, no renewal reminder, no cancel confirmation (`confirmation_sent: True` is hard-coded)
- Severity: Medium
- Status: Confirmed (handler list in probe output; `grep "order.paid|invoice.issued|refund.approved"` found no consumers; no reminder code)
- Component: `service.py:1037` (`"confirmation_sent": True` with no send); the events `order.paid`, `invoice.issued`, `subscription.*` and `refund.*` are emitted but unhandled
- Requirement:
  - FR-COM-005: one-click cancel with immediate confirmation; reminder 7 days before an annual renewal
  - PRD scenario line 646: "Invoice emailed"
- Recommended fix: add notification handlers for these events, and only report `confirmation_sent` after a successful enqueue.
- Suggested owner paths: `apps/api/app/wiring.py`, `apps/api/app/modules/notifications/*`, `apps/api/app/modules/commerce/service.py`

### COM-18: `.env.example` is out of sync with the code (names only)
- Severity: Medium (missing names); Low (unused names)
- Status: Confirmed (spot-checked: `grep -c TD_COMMERCE_WEBHOOK_MODE .env.example` → 0; no `SELLER_ADDRESS` or `COMMERCE_DOCUMENT_STORE` lines)
- Missing from `.env.example`:
  - `TD_COMMERCE_WEBHOOK_MODE`, `SELLER_ADDRESS`, `COMMERCE_DOCUMENT_STORE`
  - web: `TD_CSP_UPLOAD_ORIGINS`, `API_INTERNAL_URL`, `NEXT_PUBLIC_APP_VERSION`, `NEXT_PUBLIC_NOTICE_VERSION`
- In `.env.example` but never read (sub-agent list):
  - Celery/DB: `CELERY_VISIBILITY_TIMEOUT_SECONDS`, `DB_SSLMODE`, `DB_SSLROOTCERT`
  - CDN: `CLOUDFRONT_*`
  - Judge: `JUDGE_CALLBACK_HMAC_SECRET`, `JUDGE_DAILY_QUOTA`, `JUDGE_MTLS_*`
  - SMS: `MSG91_*`, `SMS_DAILY_SPEND_CAP_INR`
  - Email: `SES_CONFIGURATION_SET_*`, `EMAIL_RECIPIENT_ALLOWLIST`
  - Observability: `OTEL_SERVICE_NAME`, `SENTRY_ENVIRONMENT`
  - Other: `S3_BUCKET_JUDGE_PRIVATE`, `TD_FP_*`, `TD_WEBAUTHN_*`, `MINIO_ROOT_*` (MinIO was replaced by SeaweedFS), `TD_SCHEDULER_LEADER_LOCK_TTL_SECONDS`, `DATABASE_MAINTENANCE_URL`
- Default ports in `.env.example` and compose are 5432/6379/6380. The 15432/16379/16380 values come only from the developer's untracked `.env`.
- Suggested owner paths: `.env.example`, `apps/api/app/core/config.py`

### COM-19: For an odd tax amount, CGST and SGST differ by 1 paisa
- Severity: Low
- Status: Confirmed
- Component: `pricing.py:70-72` (`c = tax // 2; sgst = tax - c`)
- Evidence: `split 262425 -> GstLine(taxable_paise=222394, cgst_paise=20015, sgst_paise=20016 ...)`. The existing test asserts this.
- Note: CGST and SGST are normally equal. Recommended: compute taxable value from the inclusive price so that the two halves round equally, or absorb the paisa into the taxable value. Confirm with the CA.
- Suggested owner paths: `apps/api/app/modules/commerce/pricing.py`

### COM-20: Contract termination can extend access beyond the contract end
- Severity: Low
- Status: Confirmed
- Component: `entitlements/service.py:1155-1158` (`ends_at = max(termination + 7 days, ...)`, applied even when the original `ends_at` is earlier)
- Evidence: `ends_at before termination 2026-11-05 18:29:59+00:00 after 2026-11-10 15:33:29`
- Requirement: BR-ENT-18
- Recommended fix: `ends_at = min(current ends_at, termination + 7 days)`.

### COM-21: The decision cache can pin a stale allow for up to one relay interval after a revoke
- Severity: Low
- Status: Suspected (code reading)
- Component: `entitlements/cache.py`; `record_event` bumps `ent:ver` inside the uncommitted transaction.
- Detail: a concurrent reader can read the new version together with the old DB state and cache an allow under the new version. The post-commit outbox bump (relay every 5 s) clears it. If the relay is down, the stale allow lasts until the 60 s TTL.
- Recommended fix: bump the version only after commit (`after_commit` hook) as well as from the outbox.

### COM-22: Razorpay orders do not set `payment_capture`; payments that are only authorised are never captured
- Severity: Low
- Status: Suspected (depends on the account's auto-capture setting)
- Component: `gateway.py:225-229`; `service.py:505-506,546-548` (an authorised payment only shows "confirming…")
- Recommended fix: confirm that auto-capture is enabled on the account and document it, or capture explicitly on `payment.authorized`.

### COM-23: Build and CI reproducibility risks
- Severity: Medium
- Status: Suspected (sub-agent reading; not executed)
- Detail:
  - `apps/api/Dockerfile:33-35` installs from `pyproject` version ranges without a lockfile, and base images are not pinned by digest.
  - `ci.yml:289` executes `scripts/seed-dev.sh` directly. On this Windows checkout (`core.fileMode=false`) the exec bit will likely be lost.
  - `compose up --wait` with the one-shot `s3-init` service may fail on some Compose versions.
- Suggested owner paths: `apps/api/Dockerfile`, `.github/workflows/ci.yml`

### COM-24: Documentation and naming drift
- Severity: Low
- Status: Confirmed
- Detail:
  - `webhooks.py:10-12` still says the critical-queue wiring is "pending"; it exists (`tasks.py`).
  - `FakePaymentProvider.name = "razorpay"`, so fake payments are stored as `gateway='razorpay'` and cannot be told apart in the DB.
  - `api-webhooks` has no host port, so it cannot be reached locally.
  - `deploy.yml:147-149,186-188` is a deliberate `exit 1` skeleton.

## Verified OK (highlights)
- Quote maths matches the spec example: ₹3,499 with 25 % off gives taxable 222394 + CGST 20015 + SGST 20016 = 262425. Inter-state goes to IGST. The server recomputes every quote, and a quote total mismatch is rejected.
- Webhooks:
  - HMAC is constant-time over the raw body.
  - The previous secret is accepted during rotation.
  - An empty secret always fails (probe `test_webhook_hmac_rotation_and_empty_secret`).
  - Invalid signatures get 400 and an AB-12 signal.
  - Events are deduplicated permanently on `(gateway, event_id)`.
  - Stale events are flagged, not rejected.
  - State comes only from the provider re-fetch, and status changes only move forward.
- Fulfilment is idempotent (row lock, status guard, `ux_ent_order_item`). A subscription-charge race is protected by `ux_orders_idem`. Invoice numbering is gap-free per series and FY through `invoice_sequences` upsert, ≤ 16 chars, and the FY boundary is correct (probe).
- Every beat entry's task is registered in the worker (`beat tasks not registered in worker: []`). The outbox handlers for `entitlement.*` (cache bump) and analytics are registered.
- The access checker covers all 8 resource types with parent resolution. Free content bypasses restrictions. L3+/locks deny access. Staff preview goes through RBAC. Contract seats require an active membership and an active org (BR-ENT-19).
- The FakePaymentProvider, FakeVideoProvider, Fake judge, console SMS, fake/console email, local KMS and memory document store are all refused by the API in production. The exceptions are covered in COM-07 and COM-08.

## Summary
Counts (24 findings): Critical 1, High 8, Medium 10, Low 5.

| Severity | IDs |
|---|---|
| Critical | COM-01 |
| High | COM-02 to COM-09 |
| Medium | COM-10 to COM-18, COM-23 |
| Low | COM-19 to COM-22, COM-24 |

Not tested, and why:
- No real calls were made to Razorpay, Cashfree, VdoCipher, Judge0, SES or MSG91 (brief rule). Adapter correctness was judged by reading the code only.
- Celery was not run against a broker. Queue analysis comes from the beat dump and compose.
- PDF visual layout was not inspected (the existing text-extraction test passes).
- The GuardDuty malware-scan consumer is "Planned" (`media/providers.py:252-258`), so production uploads may never become `clean`. This is cross-area (media) and was not verified.
- The cache race (COM-21) was not reproduced; it needs concurrent transactions.
