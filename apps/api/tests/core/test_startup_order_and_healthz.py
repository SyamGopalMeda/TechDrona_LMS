"""Startup gate runs after module discovery; /healthz liveness alias."""

from __future__ import annotations

import pytest

import app.main as main_mod
from app.core import startup_checks
from app.core.config import Settings
from app.core.startup_checks import UnsafeConfigurationError
from tests.core.test_logging_and_startup import _prod

FAKE_NAME = "probe (registered by a module at import time)"


def test_fake_adapter_registered_during_discovery_blocks_production(monkeypatch) -> None:
    real_discover = main_mod.discover_routers

    def discover_and_register(router_set: str):
        # Simulates a module whose router import registers a fake adapter.
        startup_checks.register_fake_adapter(FAKE_NAME, lambda s: True)
        return real_discover(router_set)

    monkeypatch.setattr(main_mod, "discover_routers", discover_and_register)
    try:
        with pytest.raises(UnsafeConfigurationError) as exc:
            main_mod.create_app(_prod())
        assert FAKE_NAME in str(exc.value)
    finally:
        startup_checks._fake_checks.pop(FAKE_NAME, None)


def test_non_production_starts_with_fakes() -> None:
    app = main_mod.create_app(Settings(_env_file=None, APP_ENV="test"))  # type: ignore[call-arg]
    from app.core.routing import iter_api_routes

    assert "/healthz" in {path for _r, path in iter_api_routes(app)}


async def test_healthz_is_public_liveness(client) -> None:
    r = await client.get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}
    assert r.headers["cache-control"] == "no-store"
    assert r.headers.get("x-request-id")
