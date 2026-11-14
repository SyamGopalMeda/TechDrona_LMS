"""catalog_demo seed: dev/demo only, refuses production, idempotent, published + browsable."""

from __future__ import annotations

import pytest

from app.seeds import catalog_demo, dev_users
from tests.catalog.factory import sync_catalog


# The production guard below is a pure-Python check (no store), so only this one runs on both.
@pytest.mark.usefixtures("catalog_backend")
async def test_catalog_demo_seed_idempotent_and_public(browser, db) -> None:
    await dev_users.seed(db)
    made = await catalog_demo.seed(db)
    assert made == ["demo-dsa-free", "demo-aptitude-paid"]
    assert await catalog_demo.seed(db) == []
    await sync_catalog(db)  # the seed CLI copies to Firestore after seeding (TD_STORE_CATALOG)
    r = await browser.get("/catalog/courses/demo-dsa-free")
    assert r.status_code == 200 and r.json()["price_type"] == "free"


def test_catalog_demo_refuses_production(monkeypatch) -> None:
    from app.core.config import reset_settings_cache

    monkeypatch.setenv("APP_ENV", "production")
    reset_settings_cache()
    try:
        with pytest.raises(catalog_demo.ProductionRefused):
            catalog_demo.guard()
    finally:
        monkeypatch.setenv("APP_ENV", "test")
        reset_settings_cache()
