"""Support tests: real resolver/permission checker, captured email/SMS, Browser."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest

from tests.identity.fixtures import browser, mail, real_auth, sms  # noqa: F401


@pytest.fixture(autouse=True)
def security_hooks(app: Any) -> Iterator[None]:
    from app.modules.admin.policy import identity_resolver
    from app.modules.identity.policy import register_policy_resolver
    from app.modules.security.router import install_hooks

    install_hooks()
    register_policy_resolver(identity_resolver)
    yield


@pytest.fixture
def audited(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Spy on ``audit()`` calls made by the support router (td_app cannot read audit_outbox)."""
    from app.modules.support import router as sr

    calls: list[str] = []
    real = sr.audit

    async def spy(session: Any, actor: Any, action: str, *a: Any, **kw: Any) -> Any:
        calls.append(action)
        return await real(session, actor, action, *a, **kw)

    monkeypatch.setattr(sr, "audit", spy)
    return calls
