"""Mentoring tests reuse the placement two-tenant world (real RBAC checker, FakeAuth)."""

from __future__ import annotations

from typing import Any

import pytest

from tests.placement.conftest import rbac, world  # noqa: F401


@pytest.fixture
def audits(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, Any]]:
    """Spy on ``audit()`` in the mentoring service (td_app cannot read audit_outbox)."""
    from app.modules.mentoring import service

    seen: list[tuple[str, Any]] = []
    real = service.audit

    async def spy(session: Any, actor: Any, action: str, *a: Any, **kw: Any) -> Any:
        seen.append((action, kw.get("subject_user_id")))
        return await real(session, actor, action, *a, **kw)

    monkeypatch.setattr(service, "audit", spy)
    return seen
