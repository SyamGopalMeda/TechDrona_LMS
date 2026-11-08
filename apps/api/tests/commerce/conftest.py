"""Commerce/entitlement fixtures: FakePaymentProvider installed as ``razorpay``, fake auth,
API helper, and clean extension-point registries per test."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest

from app.modules.commerce.gateway import FakePaymentProvider, set_gateway
from tests.commerce.factory import Api


@pytest.fixture
def fake_gw() -> Iterator[FakePaymentProvider]:
    fake = FakePaymentProvider()
    set_gateway("razorpay", fake)
    yield fake
    set_gateway("razorpay", None)


@pytest.fixture(autouse=True)
def _clean_registries() -> Iterator[None]:
    from app.modules.entitlements import service as ent

    prev = dict(ent._parent_resolvers)
    prev_usage = ent.usage_provider()
    yield
    ent._parent_resolvers.clear()
    ent._parent_resolvers.update(prev)
    ent.register_usage_provider(prev_usage)


@pytest.fixture
def api(client: Any, auth: Any, db: Any, app: Any) -> Api:
    import app.modules.entitlements.router  # noqa: F401  (registers the access checker)

    return Api(client, auth)
