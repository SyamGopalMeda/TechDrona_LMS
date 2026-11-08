# ADR-0006: Payments — Razorpay primary, Cashfree fallback adapter, entitlement-centric access

* **Status:** Accepted (Brief §1) — implementation **Planned**
* **Related:** `system-architecture.md §11`, `database-schema.md §11`
* **Revision:** v0.4 (2026-11-03, Integration Lead): staleness rule aligned with the Security Specialist (re-fetch every state-changing event; no age-based rejection for any provider) — `contract-reconciliation.md` §9

## Context

Indian D2C buyers pay by UPI, cards, netbanking; subscriptions need UPI AutoPay / e-mandates. RBI e-mandate rules allow silent debits up to ₹15,000 with AFA at registration and a pre-debit notice ≥ 24 h ahead (research §4 [Reported, news]). Razorpay UPI AutoPay debit webhooks can arrive 24–36 h after the charge (research §4 [Verified]). Merchants must not store card data. GST invoices (72-month retention) are required. Competitors' refund practices are a top complaint (research §1, §7).

## Decision

* `PaymentGateway` abstraction with `RazorpayGateway` (primary) and `CashfreeGateway` (fallback, feature-flagged off).
* Server-created orders (`orders`, `order_items` price snapshots in integer paise, CGST/SGST vs IGST by place of supply); browser receives only checkout parameters.
* Webhooks: canonical path `/api/v1/webhooks/{provider}` (CloudFront/ALB rule `/api/v1/webhooks/*` → dedicated `api-webhooks` service, never through the BFF; v0.3); HMAC-SHA256 over the raw body with constant-time compare; dedupe on `(gateway, event_id)` via `INSERT … ON CONFLICT DO NOTHING`; respond 200 fast; process asynchronously on the `critical` queue with row locks and a state machine that ignores stale transitions.
* **Staleness (v0.4, security review pass — supersedes v0.3; `security-threat-model.md` §2.4, CPR-BRF-06/CPR-ARC-06):** no event from any provider is rejected for age; replay is neutralised by event-id dedupe. **Every** event that can change order, payment, refund, subscription or entitlement state is applied **only from a server-side re-fetch** of the entity from the provider API, never from the event payload, and backward state transitions are ignored (`payment_webhook_events.refetched_at`, `refetch_status`). Events older than `commerce.webhook.tolerance_seconds` (5 min; `WEBHOOK_TOLERANCE_SECONDS`) are flagged `is_stale` for monitoring only. If the re-fetch fails, the worker retries with backoff and makes no state change (`refetch_status = failed`). An invalid signature is rejected with `400` and recorded as security signal `AB-12`. *(v0.3 said Cashfree payloads older than 5 min are "not trusted"; under the v0.4 rule the outcome is the same — no payload state is trusted — but no event is rejected.)*
* `fulfil_order()` is idempotent and called by both the checkout callback (signature-verified) and the webhook; entitlements are unique per `order_item_id`.
* `entitlements` are the single source of access truth with explicit source FKs (order item, subscription, institution contract, manual/trial/coupon). Subscription renewals extend `ends_at`; a failed renewal debit moves the entitlement to `grace` for **5 days** (policy key `commerce.subscription_grace_days`, default 5, bounds 3–7; PRD BR-ENT-09; v0.3 — supersedes the earlier 3-day value).
* Recurring prices and mandates are capped at ₹15,000 by CHECK constraints.
* Store only gateway ids, method, last4/network/issuer, masked VPA.
* Reconciliation job polls the gateway for pending orders; daily settlement reconciliation.
* Gap-free invoice numbering per series and financial year via `invoice_sequences` in the fulfilment transaction; credit notes for refunds.
* Refund rules identical on marketing pages and Terms, including discounted purchases (research §7 [Rec]).

## Alternatives considered

| Option | Why not |
|---|---|
| Stripe India | Recurring/UPI AutoPay support and onboarding constraints for Indian merchants; Razorpay is the market default. |
| Gateway-hosted subscriptions as access truth | Access would depend on webhook timing; no unified model for B2B seats and manual grants. |
| Synchronous webhook processing | Gateway retries on slow responses; risk of duplicate work and timeouts. |

## Consequences

* (+) Exactly-once effects from at-least-once delivery; clear audit trail from payment to access.
* (+) B2B seats, coupons, trials and D2C purchases share one access check.
* (−) Two code paths (callback + webhook) must stay convergent — covered by contract tests.
* (−) Gateway fallback adapter must be exercised periodically (staging drills) or it will rot.
* (−) RBI framework sourced from news must be checked against the primary circular before go-live (research §8 open Q13).
