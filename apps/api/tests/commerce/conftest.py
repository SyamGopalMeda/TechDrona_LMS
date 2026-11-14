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


# Store matrix (docs/firebase/agents/data-money.md). Opt-in while commerce is not flippable:
# ``TD_TEST_COMMERCE_MATRIX=1`` runs every test in this directory on Postgres **and** on the
# Firestore emulator (``TD_STORE_COMMERCE=firestore``, backfilled from the Postgres test DB).
import os  # noqa: E402
from collections.abc import AsyncIterator  # noqa: E402

from tests.firestore.conftest import firestore_emulator  # noqa: E402, F401
from tests.firestore.matrix import BACKENDS, activate_firestore  # noqa: E402

if os.environ.get("TD_TEST_COMMERCE_MATRIX") == "1":

    @pytest.fixture(autouse=True, params=BACKENDS)
    async def commerce_backend(
        request: pytest.FixtureRequest, db: Any, monkeypatch: pytest.MonkeyPatch
    ) -> AsyncIterator[str]:
        if request.param == "postgres":
            yield "postgres"
            return
        restore = await activate_firestore(request, db, monkeypatch, ("commerce",))
        try:
            yield "firestore"
        finally:
            await restore()
