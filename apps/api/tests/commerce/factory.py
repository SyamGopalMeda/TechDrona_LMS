"""Shared helpers for commerce/entitlements tests: catalogue rows, buyers, principals,
the FakePaymentProvider and HTTP helpers. Everything is rolled back after each test."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import system_context
from app.core.ids import uuid7
from app.core.principal import Principal, RoleGrant
from app.core.time import utcnow
from app.modules.commerce.gateway import FakePaymentProvider
from app.modules.commerce.models import Coupon, Plan, Price, Product, ProductItem
from app.modules.identity.models import Consent
from tests.conftest import SERVICE_TOKEN
from tests.identity.factory import add_member, make_user


@dataclass
class Catalog:
    product: Product
    plan: Plan
    price: Price


async def make_product(
    db: AsyncSession,
    *,
    kind: str = "course",
    amount_paise: int = 349900,
    days: int = 180,
    items: list[dict[str, Any]] | None = None,
    recurring: bool = False,
    gateway_plan: str | None = None,
    creator: uuid.UUID | None = None,
) -> Catalog:
    await system_context(db, "test.factory")
    if creator is None:
        creator = (await make_user(db)).id
        await system_context(db, "test.factory")
    pid = uuid7()
    p = Product(
        id=pid,
        sku=f"T-{pid.hex[-10:]}",
        name=f"Test {kind}",
        product_kind=kind,
        refund_policy_key="standard",
        status="active",
        gst_rate=Decimal("18.00"),
    )
    db.add(p)
    await db.flush()
    for it in items if items is not None else [{"item_type": "course", "course_id": uuid7()}]:
        db.add(ProductItem(id=uuid7(), product_id=pid, **it))
    plan = Plan(
        id=uuid7(),
        product_id=pid,
        code=f"PL-{pid.hex[-10:]}",
        billing_type="recurring" if recurring else "one_time",
        interval_unit="month" if recurring else None,
        interval_count=1 if recurring else None,
        access_duration_days=None if recurring else days,
        gateway_plan_ids={"razorpay": gateway_plan or "plan_FAKE"} if recurring else {},
        status="active",
    )
    db.add(plan)
    await db.flush()
    price = Price(
        id=uuid7(),
        plan_id=plan.id,
        amount_paise=amount_paise,
        is_recurring=recurring,
        valid_from=utcnow() - timedelta(days=1),
        created_by=creator,
    )
    db.add(price)
    await db.flush()
    return Catalog(p, plan, price)


async def make_coupon(db: AsyncSession, creator: uuid.UUID, **kw: Any) -> Coupon:
    await system_context(db, "test.factory")
    c = Coupon(
        id=uuid7(),
        code=kw.pop("code", f"C{uuid7().hex[-8:].upper()}"),
        discount_type=kw.pop("discount_type", "percent"),
        percent_off=kw.pop("percent_off", Decimal("25")),
        valid_from=kw.pop("valid_from", utcnow() - timedelta(days=1)),
        created_by=creator,
        **kw,
    )
    db.add(c)
    await db.flush()
    return c


async def make_buyer(db: AsyncSession, *, consent: bool = True, minor: bool = False) -> uuid.UUID:
    u = await make_user(db, minor=minor)
    if consent:
        await system_context(db, "test.factory")
        db.add(
            Consent(
                id=uuid7(),
                user_id=u.id,
                purpose="security_monitoring",
                action="granted",
                notice_version="2026-11-01",
                channel="web",
            )
        )
        await db.flush()
    return u.id


def principal(
    user_id: uuid.UUID,
    *,
    roles: tuple[str, ...] = (),
    org_roles: tuple[tuple[str, uuid.UUID], ...] = (),
    org_ids: tuple[uuid.UUID, ...] = (),
    platform: bool = False,
    stepped_up: bool = True,
    **kw: Any,
) -> Principal:
    grants = tuple(RoleGrant(r, "platform") for r in roles) + tuple(
        RoleGrant(r, "organization", o) for r, o in org_roles
    )
    return Principal(
        user_id=user_id,
        session_id=uuid7(),
        tier="privileged" if platform else "student",
        org_ids=org_ids,
        grants=grants,
        is_platform=platform,
        is_minor=kw.pop("is_minor", False),
        last_step_up_at=utcnow() if stepped_up else None,
        **kw,
    )


class Api:
    """Thin client wrapper: ``api.as_(principal).post(path, json, idem=True)``."""

    def __init__(self, client: Any, auth: Any) -> None:
        self.client = client
        self.auth = auth
        self.headers: dict[str, str] = {}

    def as_(self, p: Principal, *perms: str) -> Api:
        a = Api(self.client, self.auth)
        a.headers = self.auth.login(p)
        for perm in perms:
            self.auth.grant(p, perm)
        return a

    async def get(self, path: str, **kw: Any) -> Any:
        return await self.client.get(f"/api/v1{path}", headers=self.headers, **kw)

    async def post(
        self, path: str, json: Any = None, *, idem: bool | str = False, headers: dict[str, str] | None = None
    ) -> Any:
        h = dict(self.headers)
        if idem:
            h["Idempotency-Key"] = idem if isinstance(idem, str) else f"k-{uuid7().hex}"
        h.update(headers or {})
        return await self.client.post(f"/api/v1{path}", json=json if json is not None else {}, headers=h)

    async def patch(self, path: str, json: Any, headers: dict[str, str] | None = None) -> Any:
        return await self.client.patch(
            f"/api/v1{path}", json=json, headers={**self.headers, **(headers or {})}
        )


async def deliver(client: Any, raw: bytes, headers: dict[str, str]) -> Any:
    return await client.post("/api/v1/webhooks/razorpay", content=raw, headers=headers)


async def buy(api: Api, cat: Catalog, *, coupon: str | None = None, state: str = "36") -> dict[str, Any]:
    q = await api.post(
        "/commerce/checkout/quote",
        {"price_id": str(cat.price.id), "coupon_code": coupon, "billing": {"state_code": state}},
    )
    assert q.status_code == 200, q.text
    r = await api.post(
        "/commerce/orders",
        {
            "price_id": str(cat.price.id),
            "coupon_code": coupon,
            "billing": {"state_code": state},
            "quote_total_paise": q.json()["total_paise"],
        },
        idem=True,
    )
    assert r.status_code == 201, r.text
    return dict(r.json())


async def pay_via_webhook(
    client: Any, fake: FakePaymentProvider, order: dict[str, Any], event_id: str | None = None
) -> str:
    gp = fake.pay(order["checkout"]["gateway_order_id"])
    raw, h = fake.webhook(
        "payment.captured", {"payment": {"id": gp.id, "order_id": gp.order_id}}, event_id=event_id
    )
    r = await deliver(client, raw, h)
    assert r.status_code == 200 and r.json()["status"] == "accepted", r.text
    return gp.id


async def rows(db: AsyncSession, model: Any, *where: Any) -> list[Any]:
    await system_context(db, "test.inspect")
    return list(
        (await db.execute(select(model).where(*where).execution_options(populate_existing=True))).scalars()
    )


def past(days: float) -> datetime:
    return utcnow() - timedelta(days=days)


__all__ = ["SERVICE_TOKEN", "add_member", "make_user"]
