"""Payment gateway adapters (ADR-0006).

* ``PaymentGateway`` — the interface every provider implements. Commerce only applies state
  that it fetched through ``fetch_*`` (never webhook payload state).
* ``RazorpayGateway`` — primary provider over the Razorpay REST API (httpx, basic auth).
  Implemented against the public API documentation; **not verified against the provider**
  (no credentials in this environment).
* ``CashfreeGateway`` — fallback adapter (feature flag ``PAYMENTS_FALLBACK_PROVIDER_ENABLED``,
  off by default; P1): webhook signature verification is implemented, API calls are not.
* ``FakePaymentProvider`` — DEV/TEST ONLY in-memory simulation of the Razorpay protocol
  (orders, payments, refunds, subscriptions, disputes, signed webhooks). Selected with
  ``PAYMENTS_PRIMARY_PROVIDER=fake`` (refused at startup in production) or installed by tests
  through ``set_gateway``.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import itertools
import json
import secrets
import time
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx

from app.core.errors import ProblemError
from app.core.startup_checks import register_fake_adapter
from app.modules.commerce.policy import commerce_settings

register_fake_adapter(
    "payments (FakePaymentProvider: PAYMENTS_PRIMARY_PROVIDER=fake)",
    lambda s: s.PAYMENTS_PRIMARY_PROVIDER.lower() == "fake",
)


class GatewayUnavailable(Exception):
    """Provider API unreachable / 5xx: callers retry without any state change."""


@dataclass
class GwOrder:
    id: str
    amount_paise: int
    currency: str
    status: str  # created | attempted | paid
    receipt: str | None = None


@dataclass
class GwPayment:
    id: str
    amount_paise: int
    currency: str
    status: str  # created | authorized | captured | failed | refunded
    order_id: str | None = None
    subscription_id: str | None = None
    method: str | None = None
    card_last4: str | None = None
    card_network: str | None = None
    card_issuer: str | None = None
    vpa_masked: str | None = None
    bank_code: str | None = None
    error_code: str | None = None
    error_description: str | None = None
    amount_refunded_paise: int = 0
    fee_paise: int | None = None
    tax_paise: int | None = None
    created_at: int | None = None  # epoch seconds


@dataclass
class GwRefund:
    id: str
    payment_id: str
    amount_paise: int
    status: str  # pending | processed | failed
    notes: dict[str, Any] = field(default_factory=dict)


@dataclass
class GwSubscription:
    id: str
    plan_id: str
    status: str  # created|authenticated|active|pending|halted|paused|cancelled|completed|expired
    current_start: int | None = None
    current_end: int | None = None
    charge_at: int | None = None
    paid_count: int = 0
    total_count: int | None = None


@dataclass
class GwDispute:
    id: str
    payment_id: str
    amount_paise: int
    status: str  # open | under_review | won | lost | closed


class PaymentGateway(Protocol):
    name: str  # value stored in orders.gateway / payments.gateway

    @property
    def key_id(self) -> str: ...

    async def create_order(self, amount_paise: int, receipt: str, notes: dict[str, str]) -> GwOrder: ...
    async def fetch_order(self, order_id: str) -> GwOrder: ...
    async def fetch_order_payments(self, order_id: str) -> list[GwPayment]: ...
    async def fetch_payment(self, payment_id: str) -> GwPayment: ...
    async def create_refund(self, payment_id: str, amount_paise: int, notes: dict[str, str]) -> GwRefund: ...
    async def fetch_refund(self, refund_id: str) -> GwRefund: ...
    async def fetch_payment_refunds(self, payment_id: str) -> list[GwRefund]: ...
    async def create_subscription(
        self, gateway_plan_id: str, total_count: int, notes: dict[str, str]
    ) -> GwSubscription: ...
    async def fetch_subscription(self, subscription_id: str) -> GwSubscription: ...
    async def cancel_subscription(self, subscription_id: str, at_cycle_end: bool) -> GwSubscription: ...
    async def undo_scheduled_cancel(self, subscription_id: str) -> GwSubscription: ...
    async def update_subscription_plan(
        self, subscription_id: str, gateway_plan_id: str, *, at_cycle_end: bool
    ) -> GwSubscription: ...
    async def add_subscription_addon(self, subscription_id: str, amount_paise: int, name: str) -> str: ...
    async def delete_subscription_addon(self, addon_id: str) -> None: ...
    async def fetch_dispute(self, dispute_id: str) -> GwDispute: ...
    def verify_checkout_signature(self, order_id: str, payment_id: str, signature: str) -> bool: ...
    def verify_subscription_signature(
        self, payment_id: str, subscription_id: str, signature: str
    ) -> bool: ...
    def verify_webhook(self, raw_body: bytes, headers: dict[str, str]) -> bool: ...


def hmac_hex(secret: str, message: bytes) -> str:
    return hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()


def _ct_eq(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())


def _mask_vpa(vpa: str | None) -> str | None:
    if not vpa or "@" not in vpa:
        return None
    user, _, handle = vpa.partition("@")
    return f"{user[:2]}***@{handle}"


# --------------------------------------------------------------------------- Razorpay


class RazorpayGateway:
    """Razorpay REST adapter. Amounts are paise (Razorpay's native unit)."""

    name = "razorpay"

    def __init__(
        self,
        key_id: str,
        key_secret: str,
        webhook_secrets: tuple[str, ...],
        base_url: str = "https://api.razorpay.com/v1",
        timeout_s: float = 8.0,
    ) -> None:
        self._key_id = key_id
        self._secret = key_secret
        self._webhook_secrets = tuple(s for s in webhook_secrets if s)
        self._base = base_url.rstrip("/")
        self._timeout = timeout_s

    @property
    def key_id(self) -> str:
        return self._key_id

    async def _call(self, method: str, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=self._timeout, auth=(self._key_id, self._secret)) as c:
                resp = await c.request(method, f"{self._base}{path}", json=body)
        except httpx.HTTPError as e:
            raise GatewayUnavailable(str(e)) from e
        if resp.status_code >= 500 or resp.status_code == 429:
            raise GatewayUnavailable(f"razorpay {resp.status_code}")
        if resp.status_code >= 400:
            raise ProblemError("service_unavailable", detail="Payment provider rejected the request.")
        data: dict[str, Any] = resp.json()
        return data

    @staticmethod
    def _payment(d: dict[str, Any]) -> GwPayment:
        card = d.get("card") or {}
        return GwPayment(
            id=d["id"],
            amount_paise=int(d["amount"]),
            currency=d.get("currency", "INR"),
            status=d["status"],
            order_id=d.get("order_id"),
            subscription_id=d.get("subscription_id"),
            method=d.get("method"),
            card_last4=card.get("last4"),
            card_network=card.get("network"),
            card_issuer=card.get("issuer"),
            vpa_masked=_mask_vpa(d.get("vpa")),
            bank_code=d.get("bank"),
            error_code=d.get("error_code"),
            error_description=d.get("error_description"),
            amount_refunded_paise=int(d.get("amount_refunded") or 0),
            fee_paise=d.get("fee"),
            tax_paise=d.get("tax"),
            created_at=d.get("created_at"),
        )

    @staticmethod
    def _sub(d: dict[str, Any]) -> GwSubscription:
        return GwSubscription(
            id=d["id"],
            plan_id=d.get("plan_id", ""),
            status=d["status"],
            current_start=d.get("current_start"),
            current_end=d.get("current_end"),
            charge_at=d.get("charge_at"),
            paid_count=int(d.get("paid_count") or 0),
            total_count=d.get("total_count"),
        )

    async def create_order(self, amount_paise: int, receipt: str, notes: dict[str, str]) -> GwOrder:
        d = await self._call(
            "POST",
            "/orders",
            # COM-22: capture automatically on authorisation (Razorpay Orders API
            # ``payment_capture``); an authorised-only payment would otherwise never settle.
            {
                "amount": amount_paise,
                "currency": "INR",
                "receipt": receipt,
                "notes": notes,
                "payment_capture": 1,
            },
        )
        return GwOrder(d["id"], int(d["amount"]), d["currency"], d["status"], d.get("receipt"))

    async def fetch_order(self, order_id: str) -> GwOrder:
        d = await self._call("GET", f"/orders/{order_id}")
        return GwOrder(d["id"], int(d["amount"]), d["currency"], d["status"], d.get("receipt"))

    async def fetch_order_payments(self, order_id: str) -> list[GwPayment]:
        d = await self._call("GET", f"/orders/{order_id}/payments")
        return [self._payment(p) for p in d.get("items", [])]

    async def fetch_payment(self, payment_id: str) -> GwPayment:
        return self._payment(await self._call("GET", f"/payments/{payment_id}"))

    async def create_refund(self, payment_id: str, amount_paise: int, notes: dict[str, str]) -> GwRefund:
        d = await self._call(
            "POST", f"/payments/{payment_id}/refund", {"amount": amount_paise, "notes": notes}
        )
        return GwRefund(d["id"], d["payment_id"], int(d["amount"]), d["status"], d.get("notes") or {})

    async def fetch_refund(self, refund_id: str) -> GwRefund:
        d = await self._call("GET", f"/refunds/{refund_id}")
        return GwRefund(d["id"], d["payment_id"], int(d["amount"]), d["status"], d.get("notes") or {})

    async def fetch_payment_refunds(self, payment_id: str) -> list[GwRefund]:
        """COM-02 idempotent re-submit: refunds already created for a payment (``notes.refund_id``
        identifies ours). Razorpay ``GET /payments/{id}/refunds`` — not verified (no credentials)."""
        d = await self._call("GET", f"/payments/{payment_id}/refunds")
        return [
            GwRefund(x["id"], x["payment_id"], int(x["amount"]), x["status"], x.get("notes") or {})
            for x in d.get("items", [])
        ]

    async def create_subscription(
        self, gateway_plan_id: str, total_count: int, notes: dict[str, str]
    ) -> GwSubscription:
        d = await self._call(
            "POST",
            "/subscriptions",
            {"plan_id": gateway_plan_id, "total_count": total_count, "customer_notify": 1, "notes": notes},
        )
        return self._sub(d)

    async def fetch_subscription(self, subscription_id: str) -> GwSubscription:
        return self._sub(await self._call("GET", f"/subscriptions/{subscription_id}"))

    async def cancel_subscription(self, subscription_id: str, at_cycle_end: bool) -> GwSubscription:
        d = await self._call(
            "POST",
            f"/subscriptions/{subscription_id}/cancel",
            {"cancel_at_cycle_end": 1 if at_cycle_end else 0},
        )
        return self._sub(d)

    # COM-13/14 — implemented against the Razorpay Subscriptions API docs, NOT verified against
    # the provider (no credentials in this environment).
    async def undo_scheduled_cancel(self, subscription_id: str) -> GwSubscription:
        return self._sub(
            await self._call("POST", f"/subscriptions/{subscription_id}/cancel_scheduled_changes", {})
        )

    async def update_subscription_plan(
        self, subscription_id: str, gateway_plan_id: str, *, at_cycle_end: bool
    ) -> GwSubscription:
        d = await self._call(
            "PATCH",
            f"/subscriptions/{subscription_id}",
            {"plan_id": gateway_plan_id, "schedule_change_at": "cycle_end" if at_cycle_end else "now"},
        )
        return self._sub(d)

    async def add_subscription_addon(self, subscription_id: str, amount_paise: int, name: str) -> str:
        d = await self._call(
            "POST",
            f"/subscriptions/{subscription_id}/addons",
            {"item": {"name": name[:60], "amount": amount_paise, "currency": "INR"}, "quantity": 1},
        )
        return str(d.get("id", ""))

    async def delete_subscription_addon(self, addon_id: str) -> None:
        """COM-16 compensation (Razorpay ``DELETE /addons/{id}``; not verified)."""
        await self._call("DELETE", f"/addons/{addon_id}")

    async def fetch_dispute(self, dispute_id: str) -> GwDispute:
        d = await self._call("GET", f"/disputes/{dispute_id}")
        return GwDispute(d["id"], d["payment_id"], int(d["amount"]), d["status"])

    def verify_checkout_signature(self, order_id: str, payment_id: str, signature: str) -> bool:
        if not self._secret:
            return False
        return _ct_eq(hmac_hex(self._secret, f"{order_id}|{payment_id}".encode()), signature or "")

    def verify_subscription_signature(self, payment_id: str, subscription_id: str, signature: str) -> bool:
        if not self._secret:
            return False
        return _ct_eq(hmac_hex(self._secret, f"{payment_id}|{subscription_id}".encode()), signature or "")

    def verify_webhook(self, raw_body: bytes, headers: dict[str, str]) -> bool:
        sig = headers.get("x-razorpay-signature", "")
        if not sig:
            return False
        ok = False
        for secret in self._webhook_secrets:  # current + previous during rotation
            ok |= _ct_eq(hmac_hex(secret, raw_body), sig)
        return ok


# --------------------------------------------------------------------------- Cashfree


class CashfreeGateway(RazorpayGateway):
    """Fallback adapter skeleton (P1, flag off). Only webhook verification is implemented:
    ``x-webhook-signature = base64(HMAC-SHA256(secret, timestamp + raw_body))``."""

    name = "cashfree"

    def __init__(self, app_id: str, secret: str) -> None:
        super().__init__(app_id, secret, ())
        self._cf_secret = secret

    async def _call(self, method: str, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        raise GatewayUnavailable("cashfree adapter API calls are not implemented (P1)")

    def verify_webhook(self, raw_body: bytes, headers: dict[str, str]) -> bool:
        sig = headers.get("x-webhook-signature", "")
        ts = headers.get("x-webhook-timestamp", "")
        if not (sig and ts and self._cf_secret):
            return False
        mac = hmac.new(self._cf_secret.encode(), ts.encode() + raw_body, hashlib.sha256).digest()
        return _ct_eq(base64.b64encode(mac).decode(), sig)


# --------------------------------------------------------------------------- Fake (DEV/TEST ONLY)


class FakePaymentProvider:
    """DEV/TEST ONLY. In-memory Razorpay simulation; never used when ``APP_ENV=prod``
    (startup check). ``name`` is ``razorpay`` because it speaks the Razorpay protocol."""

    name = "razorpay"
    KEY_ID = "rzp_test_FAKE"
    KEY_SECRET = "fake_key_secret_for_tests_only"  # noqa: S105 - test-only constant
    WEBHOOK_SECRET = "fake_webhook_secret_for_tests_only"  # noqa: S105 - test-only constant

    def __init__(self, *, auto_settle_refunds: bool = False) -> None:
        # E2E-03: the dev singleton settles refunds at once (the real provider would send
        # ``refund.processed``); tests settle explicitly with ``refund_settle``.
        self.auto_settle_refunds = auto_settle_refunds
        self.orders: dict[str, GwOrder] = {}
        self.payments: dict[str, GwPayment] = {}
        self.refunds: dict[str, GwRefund] = {}
        self.subscriptions: dict[str, GwSubscription] = {}
        self.disputes: dict[str, GwDispute] = {}
        self.scheduled_cancels: set[str] = set()
        self.addons: list[tuple[str, int]] = []
        self.addon_ids: dict[str, tuple[str, int]] = {}
        self.fail_ops: set[str] = set()  # simulate a provider outage for specific calls only
        self.unavailable = False  # simulate provider API outage
        self.calls: list[str] = []
        self._seq = itertools.count(1)

    @property
    def key_id(self) -> str:
        return self.KEY_ID

    def _id(self, prefix: str) -> str:
        return f"{prefix}_FAKE{next(self._seq):08d}{secrets.token_hex(3)}"

    def _check(self, op: str) -> None:
        self.calls.append(op)
        if self.unavailable or op in self.fail_ops:
            raise GatewayUnavailable("fake provider marked unavailable")

    async def create_order(self, amount_paise: int, receipt: str, notes: dict[str, str]) -> GwOrder:
        self._check("create_order")
        o = GwOrder(self._id("order"), amount_paise, "INR", "created", receipt)
        self.orders[o.id] = o
        return o

    async def fetch_order(self, order_id: str) -> GwOrder:
        self._check("fetch_order")
        return self.orders[order_id]

    async def fetch_order_payments(self, order_id: str) -> list[GwPayment]:
        self._check("fetch_order_payments")
        return [p for p in self.payments.values() if p.order_id == order_id]

    async def fetch_payment(self, payment_id: str) -> GwPayment:
        self._check("fetch_payment")
        if payment_id not in self.payments:
            simulated = self._simulated_payment(payment_id)
            if simulated is not None:
                return simulated
        return self.payments[payment_id]

    async def create_refund(self, payment_id: str, amount_paise: int, notes: dict[str, str]) -> GwRefund:
        self._check("create_refund")
        status = "processed" if self.auto_settle_refunds else "pending"
        r = GwRefund(self._id("rfnd"), payment_id, amount_paise, status, dict(notes))
        self.refunds[r.id] = r
        return r

    async def fetch_refund(self, refund_id: str) -> GwRefund:
        self._check("fetch_refund")
        return self.refunds[refund_id]

    async def fetch_payment_refunds(self, payment_id: str) -> list[GwRefund]:
        self._check("fetch_payment_refunds")
        return [r for r in self.refunds.values() if r.payment_id == payment_id]

    async def create_subscription(
        self, gateway_plan_id: str, total_count: int, notes: dict[str, str]
    ) -> GwSubscription:
        self._check("create_subscription")
        s = GwSubscription(self._id("sub"), gateway_plan_id, "created", total_count=total_count)
        self.subscriptions[s.id] = s
        return s

    async def fetch_subscription(self, subscription_id: str) -> GwSubscription:
        self._check("fetch_subscription")
        return self.subscriptions[subscription_id]

    async def cancel_subscription(self, subscription_id: str, at_cycle_end: bool) -> GwSubscription:
        self._check("cancel_subscription")
        s = self.subscriptions[subscription_id]
        if not at_cycle_end:
            s.status = "cancelled"
        else:
            self.scheduled_cancels.add(subscription_id)
        return s

    async def undo_scheduled_cancel(self, subscription_id: str) -> GwSubscription:
        self._check("undo_scheduled_cancel")
        self.scheduled_cancels.discard(subscription_id)
        return self.subscriptions[subscription_id]

    async def update_subscription_plan(
        self, subscription_id: str, gateway_plan_id: str, *, at_cycle_end: bool
    ) -> GwSubscription:
        self._check("update_subscription_plan")
        s = self.subscriptions[subscription_id]
        if not at_cycle_end:
            s.plan_id = gateway_plan_id
        return s

    async def add_subscription_addon(self, subscription_id: str, amount_paise: int, name: str) -> str:
        self._check("add_subscription_addon")
        aid = self._id("ao")
        self.addons.append((subscription_id, amount_paise))
        self.addon_ids[aid] = (subscription_id, amount_paise)
        return aid

    async def delete_subscription_addon(self, addon_id: str) -> None:
        self._check("delete_subscription_addon")
        item = self.addon_ids.pop(addon_id, None)
        if item is not None and item in self.addons:
            self.addons.remove(item)

    async def fetch_dispute(self, dispute_id: str) -> GwDispute:
        self._check("fetch_dispute")
        return self.disputes[dispute_id]

    def verify_checkout_signature(self, order_id: str, payment_id: str, signature: str) -> bool:
        return _ct_eq(hmac_hex(self.KEY_SECRET, f"{order_id}|{payment_id}".encode()), signature or "")

    def verify_subscription_signature(self, payment_id: str, subscription_id: str, signature: str) -> bool:
        return _ct_eq(hmac_hex(self.KEY_SECRET, f"{payment_id}|{subscription_id}".encode()), signature or "")

    def verify_webhook(self, raw_body: bytes, headers: dict[str, str]) -> bool:
        return _ct_eq(hmac_hex(self.WEBHOOK_SECRET, raw_body), headers.get("x-razorpay-signature", ""))

    # ---- simulation helpers (tests / local demo)

    # Stateless "Simulate a successful payment" for the web test-mode dialog. The payment id
    # carries the gateway order id and amount, so ``fetch_payment`` can answer on any api
    # worker or replica (this provider is in-memory per process).
    SIMULATED_PREFIX = "pay_FAKESIM_"

    def test_checkout_payment(self, order_id: str, amount_paise: int) -> dict[str, str]:
        """``checkout.test_payment`` for COM-01: a payment id the learner may "complete" and its
        Razorpay-style checkout signature (HMAC of ``order_id|payment_id`` with the fake secret)."""
        payment_id = f"{self.SIMULATED_PREFIX}{amount_paise}_{order_id}"
        return {"payment_id": payment_id, "signature": self.checkout_signature(order_id, payment_id)}

    def _simulated_payment(self, payment_id: str) -> GwPayment | None:
        if not payment_id.startswith(self.SIMULATED_PREFIX):
            return None
        amount, sep, order_id = payment_id[len(self.SIMULATED_PREFIX) :].partition("_")
        if not sep or not amount.isdigit() or not order_id.startswith("order_"):
            return None
        p = GwPayment(
            id=payment_id,
            amount_paise=int(amount),
            currency="INR",
            status="captured",
            order_id=order_id,
            method="upi",
            vpa_masked="te***@okaxis",
            created_at=int(time.time()),
        )
        self.payments[p.id] = p
        o = self.orders.get(order_id)
        if o is not None:
            o.status = "paid"
        return p

    def checkout_signature(self, order_id: str, payment_id: str) -> str:
        return hmac_hex(self.KEY_SECRET, f"{order_id}|{payment_id}".encode())

    def subscription_signature(self, payment_id: str, subscription_id: str) -> str:
        return hmac_hex(self.KEY_SECRET, f"{payment_id}|{subscription_id}".encode())

    def pay(
        self, order_id: str, *, status: str = "captured", method: str = "upi", amount_paise: int | None = None
    ) -> GwPayment:
        o = self.orders[order_id]
        p = GwPayment(
            id=self._id("pay"),
            amount_paise=amount_paise if amount_paise is not None else o.amount_paise,
            currency="INR",
            status=status,
            order_id=order_id,
            method=method,
            vpa_masked="an***@okaxis" if method == "upi" else None,
            error_code="BAD_REQUEST_ERROR" if status == "failed" else None,
            error_description="Payment declined (simulated)" if status == "failed" else None,
            created_at=int(time.time()),
        )
        self.payments[p.id] = p
        if status == "captured":
            o.status = "paid"
        elif o.status == "created":
            o.status = "attempted"
        return p

    def refund_settle(self, refund_id: str, status: str = "processed") -> GwRefund:
        r = self.refunds[refund_id]
        r.status = status
        if status == "processed":
            p = self.payments[r.payment_id]
            p.amount_refunded_paise += r.amount_paise
            p.status = "refunded" if p.amount_refunded_paise >= p.amount_paise else p.status
        return r

    def subscription_charge(
        self, subscription_id: str, amount_paise: int, period_s: int = 30 * 86400
    ) -> GwPayment:
        s = self.subscriptions[subscription_id]
        now = int(time.time())
        start = s.current_end or now
        s.current_start, s.current_end = start, start + period_s
        s.charge_at = s.current_end
        s.paid_count += 1
        s.status = "active"
        p = GwPayment(
            id=self._id("pay"),
            amount_paise=amount_paise,
            currency="INR",
            status="captured",
            subscription_id=subscription_id,
            method="upi",
            created_at=now,
        )
        self.payments[p.id] = p
        return p

    def open_dispute(self, payment_id: str) -> GwDispute:
        p = self.payments[payment_id]
        d = GwDispute(self._id("disp"), payment_id, p.amount_paise, "open")
        self.disputes[d.id] = d
        return d

    def webhook(
        self,
        event: str,
        entities: dict[str, dict[str, Any]],
        *,
        event_id: str | None = None,
        created_at: int | None = None,
        secret: str | None = None,
    ) -> tuple[bytes, dict[str, str]]:
        """A signed Razorpay-style delivery: ``(raw_body, headers)``."""
        body = {
            "entity": "event",
            "account_id": "acc_FAKE",
            "event": event,
            "contains": list(entities),
            "payload": {k: {"entity": v} for k, v in entities.items()},
            "created_at": created_at if created_at is not None else int(time.time()),
        }
        raw = json.dumps(body, separators=(",", ":")).encode()
        headers = {
            "Content-Type": "application/json",
            "X-Razorpay-Signature": hmac_hex(secret or self.WEBHOOK_SECRET, raw),
            "X-Razorpay-Event-Id": event_id or self._id("evt"),
        }
        return raw, headers


# --------------------------------------------------------------------------- registry

_overrides: dict[str, PaymentGateway] = {}
_fake_singleton: FakePaymentProvider | None = None


def set_gateway(name: str, gateway: PaymentGateway | None) -> None:
    """Install (or clear with ``None``) a gateway for ``name`` — tests and local demos."""
    if gateway is None:
        _overrides.pop(name, None)
    else:
        _overrides[name] = gateway


def gateway_status() -> dict[str, Any]:
    """What the finance screens show about the online payment gateway. ``integrated`` is False
    while the DEV/DEMO fake provider is in use or no real Razorpay key is configured, so the UI
    can say "not integrated yet" instead of presenting simulated runs as real (owner rule)."""
    s = commerce_settings()
    if "razorpay" in _overrides:  # tests / local demos install their own gateway
        return {"provider": "razorpay", "integrated": True}
    fake = s.PAYMENTS_PRIMARY_PROVIDER.lower() == "fake"
    key = (s.RAZORPAY_KEY_ID or "").strip()
    return {
        "provider": "fake" if fake else "razorpay",
        "integrated": not fake and bool(key) and "REPLACE" not in key.upper(),
    }


def get_gateway(name: str = "razorpay") -> PaymentGateway:
    global _fake_singleton
    if name in _overrides:
        return _overrides[name]
    s = commerce_settings()
    if name == "razorpay":
        if s.PAYMENTS_PRIMARY_PROVIDER.lower() == "fake":
            if _fake_singleton is None:
                _fake_singleton = FakePaymentProvider(auto_settle_refunds=True)
            return _fake_singleton
        return RazorpayGateway(
            s.RAZORPAY_KEY_ID,
            s.RAZORPAY_KEY_SECRET,
            (s.RAZORPAY_WEBHOOK_SECRET, s.RAZORPAY_WEBHOOK_SECRET_PREVIOUS),
            s.RAZORPAY_API_BASE,
        )
    if name == "cashfree" and s.PAYMENTS_FALLBACK_PROVIDER_ENABLED:
        return CashfreeGateway(s.CASHFREE_APP_ID, s.CASHFREE_SECRET_KEY)
    raise ProblemError("not_found")
