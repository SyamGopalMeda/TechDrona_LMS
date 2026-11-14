"""Parity: buy a paid course over HTTP on the Firebase stack (no Postgres), then learn on it.

VM expectations (``tests/commerce``, ``tests/integration``): finance product 201, plan 201,
price 201 ``created``; COM-03 quote 200; COM-04 order 201; the gateway webhook 200 ``accepted``;
then ENT-01 allows the course and its paid lessons open (LRN-05 ``entitlement``).
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest

from tests.parity.harness import World, publish_paid_course


@pytest.fixture
def fake_gw() -> Iterator[Any]:
    from app.modules.commerce.gateway import FakePaymentProvider, set_gateway

    fake = FakePaymentProvider()
    set_gateway("razorpay", fake)
    yield fake
    set_gateway("razorpay", None)


async def make_course_product(w: World, course_id: str) -> str:
    """Finance (admin) creates a product for the course, a one-time plan and its price."""
    _, fh = await w.staff("finance")
    r = await w.call(
        "POST",
        "/finance/products",
        fh,
        expect=201,
        json={
            "sku": f"PC-{course_id[-8:].upper()}",
            "name": "Paid parity course",
            "product_kind": "course",
            "status": "active",
            "items": [{"item_type": "course", "ref_id": course_id}],
        },
    )
    pid = r.json()["product_id"]
    r = await w.call(
        "POST",
        f"/finance/products/{pid}/plans",
        fh,
        expect=201,
        json={
            "code": f"PC-{course_id[-8:].upper()}-180",
            "billing_type": "one_time",
            "access_duration_days": 180,
        },
    )
    plan = r.json()["plan_id"]
    r = await w.call(
        "POST", f"/finance/plans/{plan}/prices", fh, expect=201, idem=True, json={"amount_paise": 349900}
    )
    return str(r.json()["price_id"])


async def test_buy_paid_course_then_open_lessons(web: World, fake_gw: Any) -> None:
    w = web
    course = await publish_paid_course(w)
    price_id = await make_course_product(w, course.id)
    _student, sh = await w.learner("buyer")
    await w.consent(sh)

    await w.call("GET", "/commerce/products", {})
    q = await w.call(
        "POST", "/commerce/checkout/quote", sh, json={"price_id": price_id, "billing": {"state_code": "36"}}
    )
    r = await w.call(
        "POST",
        "/commerce/orders",
        sh,
        expect=201,
        idem=True,
        json={
            "price_id": price_id,
            "billing": {"state_code": "36"},
            "quote_total_paise": q.json()["total_paise"],
        },
    )
    order = r.json()
    gp = fake_gw.pay(order["checkout"]["gateway_order_id"])
    raw, h = fake_gw.webhook("payment.captured", {"payment": {"id": gp.id, "order_id": gp.order_id}})
    r = await w.client.post("/api/v1/webhooks/razorpay", content=raw, headers=h)
    assert r.status_code == 200 and r.json()["status"] == "accepted", r.text
    r = await w.call("GET", f"/commerce/orders/{order['order_id']}", sh)
    assert r.json()["status"] == "paid", r.text
    await w.call("GET", "/me/orders", sh)

    r = await w.call(
        "POST", "/entitlements/check", sh, json={"resource": {"kind": "course", "id": course.id}}
    )
    assert r.json()["allowed"] is True, r.text
    await w.call("GET", "/me/entitlements", sh)
    await w.call("POST", "/me/enrolments", sh, expect=201, json={"course_id": course.id})
    lessons = await course.outline(w, sh)
    r = await w.call("GET", f"/me/courses/{course.id}/lessons/{lessons['Paid']['id']}", sh)
    assert r.json()["access"]["reason"] == "entitlement"
    await w.relay()  # outbox consumers, as the Firebase worker runs them
