"""Fixtures for placement/assessments tests: FakeAuth sessions + the real RBAC checker,
a two-tenant world, an allow-all entitlement checker and an email capture."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest

from app.core.access import AccessDecision, get_access_checker, register_access_checker
from tests.placement.world import World, build_world


@pytest.fixture
def rbac(auth: Any) -> Iterator[Any]:
    from app.core import auth as core_auth
    from app.modules.rbac.service import RbacPermissionChecker

    prev = core_auth._permission_checker
    core_auth.register_permission_checker(RbacPermissionChecker())
    yield auth
    core_auth.register_permission_checker(prev)


@pytest.fixture
async def world(db: Any, rbac: Any, client: Any) -> World:
    return await build_world(db, rbac)


class AllowAll:
    def __init__(self) -> None:
        self.calls: list[tuple[str, Any]] = []

    async def check(
        self, session: Any, principal: Any, resource_type: Any, resource_id: Any, *, is_free: bool = False
    ) -> AccessDecision:
        self.calls.append((resource_type, resource_id))
        return AccessDecision(True, "entitlement")


@pytest.fixture
def allow_access() -> Iterator[AllowAll]:
    prev = get_access_checker()
    checker = AllowAll()
    register_access_checker(checker)
    yield checker
    register_access_checker(prev)


@pytest.fixture
def no_access() -> Iterator[None]:
    prev = get_access_checker()
    register_access_checker(None)
    yield
    register_access_checker(prev)


@pytest.fixture
def mail() -> Iterator[Any]:
    from app.modules.notifications.adapters import MemoryEmailAdapter, get_email_adapter, set_email_adapter

    prev = get_email_adapter()
    fake = MemoryEmailAdapter()
    set_email_adapter(fake)
    yield fake
    set_email_adapter(prev)
