"""Engage tests reuse the placement two-tenant world (real RBAC checker, FakeAuth) and an
in-memory rate-limit backend."""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from tests.placement.conftest import rbac, world  # noqa: F401


@pytest.fixture(autouse=True)
def memory_ratelimit() -> Iterator[None]:
    from app.core.ratelimit import MemoryBackend, set_backend

    prev = set_backend(MemoryBackend())
    yield
    set_backend(prev)
