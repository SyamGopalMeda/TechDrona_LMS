"""HTTP through the real FastAPI app on a stack **without Postgres** (Firebase emulator only).

``runtime.postgres_enabled()`` is False and commerce, admissions, core (idempotency/outbox) and
audit are on Firestore, as on the final Firebase stack. The commerce / admissions routes then
get a ``MemoryTx`` from ``sqlstore.store_db`` (RLS context in memory, units of work committed at
the end of the request, outbox events committed in the same Firestore transaction). Only the
authenticated principal is injected (identity is another module). No dependency override for
the database: this is the production request path.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import timedelta
from typing import Any

import httpx
import pytest
from sqlalchemy import select

from app.core.ids import uuid7
from app.core.principal import Principal
from app.core.time import utcnow
from app.modules.commerce import datastore as ds
from app.modules.commerce.models import Order
from tests.commerce.firestore.conftest import FakeSession
from tests.commerce.firestore.factory import catalogue, paid_order


class Http:
    def __init__(self, client: httpx.AsyncClient, state: dict[str, Any]) -> None:
        self.c = client
        self.state = state

    def as_user(self, user_id: uuid.UUID | None) -> Http:
        self.state["user"] = user_id
        return self


@pytest.fixture
async def http(fs: Any, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Http]:
    from app.core import auth as core_auth
    from app.core import runtime
    from app.core.firestore.backend import reset_store_backends
    from app.main import create_app

    monkeypatch.setenv("TD_ROUTER_SET", "all")
    for m in ("ADMISSIONS", "CORE", "AUDIT", "ORGS", "ENTITLEMENTS", "IDENTITY", "LEARNING"):
        monkeypatch.setenv(f"TD_STORE_{m}", "firestore")
    reset_store_backends()
    monkeypatch.setattr(runtime, "postgres_enabled", lambda: False)
    state: dict[str, Any] = {"user": None}

    def principal() -> Principal:
        uid = state["user"]
        if uid is None:
            from app.core.errors import ProblemError

            raise ProblemError("unauthenticated")
        return Principal(user_id=uid, session_id=uuid7(), tier="student", is_minor=False)

    app = create_app()
    app.dependency_overrides[core_auth.require_active_principal] = principal
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        yield Http(c, state)


async def test_public_catalogue_reads_firestore(http: Http, session: Any) -> None:
    cat = await catalogue(session, amount=118_000)
    r = await http.c.get("/api/v1/commerce/products")
    assert r.status_code == 200, r.text
    assert [p["sku"] for p in r.json()["data"]] == [cat["product"].sku]
    one = await http.c.get(f"/api/v1/commerce/products/{cat['product'].sku}")
    assert one.status_code == 200 and one.json()["sku"] == cat["product"].sku
    missing = await http.c.get("/api/v1/commerce/products/NOPE-123")
    assert missing.status_code == 404 and missing.json()["code"] == "not_found"


async def test_my_orders_lists_only_the_callers_orders(http: Http, session: Any) -> None:
    cat = await catalogue(session)
    me, other = uuid7(), uuid7()
    mine = await paid_order(session, me, cat)
    await paid_order(session, other, cat)
    r = await http.as_user(me).c.get("/api/v1/me/orders")
    assert r.status_code == 200, r.text
    assert [o["order_id"] for o in r.json()["data"]] == [str(mine.id)]
    detail = await http.c.get(f"/api/v1/commerce/orders/{mine.id}")
    assert detail.status_code == 200, detail.text
    assert detail.json()["items"][0]["total_paise"] == 118_000
    # someone else's order answers like a missing one (RLS, no existence oracle)
    theirs = (
        await ds.execute(FakeSession().as_platform(), select(Order).where(Order.user_id == other))
    ).scalar_one()
    assert (await http.c.get(f"/api/v1/commerce/orders/{theirs.id}")).status_code == 404


async def test_cancel_pending_order_commits_at_end_of_request(http: Http, session: Any) -> None:
    await catalogue(session)
    me = uuid7()
    now = utcnow()
    o = Order(
        id=uuid7(),
        order_number=await ds.next_order_number(session, now),
        user_id=me,
        status="pending_payment",
        subtotal_paise=100_000,
        discount_paise=0,
        tax_paise=18_000,
        total_paise=118_000,
        gateway="razorpay",
        gateway_order_id="order_http1",
        idempotency_key="k-http",
        expires_at=now + timedelta(minutes=30),
    )
    ds.add(session, o)
    await session.commit()
    key = uuid.uuid4().hex
    r = await http.as_user(me).c.post(
        f"/api/v1/commerce/orders/{o.id}/cancel", headers={"Idempotency-Key": key}
    )
    assert r.status_code in (200, 201), r.text
    assert r.json()["status"] == "cancelled"
    fresh = (
        await ds.execute(FakeSession().as_platform(), select(Order).where(Order.id == o.id))
    ).scalar_one()
    assert fresh.status == "cancelled"  # committed by the end of the request
    again = await http.c.post(f"/api/v1/commerce/orders/{o.id}/cancel", headers={"Idempotency-Key": key})
    assert again.status_code == r.status_code and again.json() == r.json()  # idempotent replay


async def test_webhook_without_postgres_stores_the_event_once(
    http: Http, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``provider_webhook`` opens no Postgres session on this stack (``store_session``)."""
    from app.core.config import get_settings
    from app.modules.commerce import tasks
    from app.modules.commerce.gateway import FakePaymentProvider, set_gateway
    from app.modules.commerce.models import PaymentWebhookEvent

    gw = FakePaymentProvider()
    set_gateway("razorpay", gw)
    queued: list[Any] = []
    monkeypatch.setattr(tasks, "enqueue_webhook_event", lambda p, rid: queued.append(rid))
    from app.modules.commerce import router as commerce_router

    real = get_settings()

    class _Queue:
        TD_COMMERCE_WEBHOOK_MODE = "queue"

        def __getattr__(self, name: str) -> Any:
            return getattr(real, name)

    monkeypatch.setattr(commerce_router, "get_settings", lambda: _Queue())
    try:
        body = b'{"event":"payment.captured","payload":{},"created_at":1}'
        headers = {"x-razorpay-event-id": "evt_http_1", **gw_signature(gw, body)}
        first = await http.c.post("/api/v1/webhooks/razorpay", content=body, headers=headers)
        second = await http.c.post("/api/v1/webhooks/razorpay", content=body, headers=headers)
    finally:
        set_gateway("razorpay", None)
    assert first.status_code == 200, first.text
    assert first.json()["status"] == "accepted" and second.json()["status"] == "duplicate"
    rows = (await ds.execute(FakeSession().as_platform(), select(PaymentWebhookEvent))).scalars().all()
    assert len(rows) == 1 and len(queued) == 1


def gw_signature(gw: Any, body: bytes) -> dict[str, str]:
    from app.modules.commerce.gateway import hmac_hex

    return {"x-razorpay-signature": hmac_hex(gw.WEBHOOK_SECRET, body)}


async def test_admissions_public_course_status_and_plan_without_postgres(http: Http) -> None:
    from app.modules.admissions import datastore as ads
    from app.modules.admissions.models import AdmissionFeePlan, CourseStatus

    s = FakeSession().as_platform()
    ads.add(s, CourseStatus(course_slug="data-101", status="open"))
    ads.add(
        s,
        AdmissionFeePlan(
            id=uuid7(),
            course_slug="data-101",
            title="Data 101",
            fee_paise=250_000,
            min_first_paise=50_000,
            access_min_paise=100_000,
            active=True,
        ),
    )
    await s.commit()
    r = await http.c.get("/api/v1/public/courses/status")
    assert r.status_code == 200, r.text
    assert r.json()["data"]["data-101"] == "open"
    p = await http.c.get("/api/v1/public/admissions/plans/data-101")
    assert p.status_code == 200, p.text
    assert p.json()["fee_paise"] == 250_000 and p.json()["course_status"] == "open"
    assert (await http.c.get("/api/v1/public/admissions/plans/nope-1")).status_code == 404
