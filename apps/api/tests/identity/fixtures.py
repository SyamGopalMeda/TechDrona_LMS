"""Pytest fixtures shared by the Stage 4 test packages (imported by each package conftest)."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest

from app.modules.notifications.adapters import (
    ConsoleSmsAdapter,
    MemoryEmailAdapter,
    get_email_adapter,
    get_sms_adapter,
    set_email_adapter,
    set_sms_adapter,
)
from tests.identity.factory import Browser


@pytest.fixture(autouse=True)
def real_auth(app: Any) -> Iterator[None]:
    """Use the real SessionResolver and PermissionChecker (the ``auth`` fixture of other
    packages swaps in fakes and may restore ``None``)."""
    from app.core import auth as core_auth
    from app.modules.rbac.service import RbacPermissionChecker
    from app.modules.sessions.resolver import SessionsResolver

    prev_r, prev_c = core_auth.get_session_resolver(), core_auth._permission_checker
    core_auth.register_session_resolver(SessionsResolver())
    core_auth.register_permission_checker(RbacPermissionChecker())
    yield
    core_auth.register_session_resolver(prev_r)
    core_auth.register_permission_checker(prev_c)


@pytest.fixture
def mail() -> Iterator[MemoryEmailAdapter]:
    prev = get_email_adapter()
    fake = MemoryEmailAdapter()
    set_email_adapter(fake)
    yield fake
    set_email_adapter(prev)


@pytest.fixture
def sms() -> Iterator[ConsoleSmsAdapter]:
    prev = get_sms_adapter()
    fake = ConsoleSmsAdapter()
    set_sms_adapter(fake)
    yield fake
    set_sms_adapter(prev)


@pytest.fixture
def browser(client: Any, db: Any, mail: MemoryEmailAdapter, sms: ConsoleSmsAdapter) -> Iterator[Browser]:
    """A BFF-hop browser. Rate-limit counters are isolated in memory for the test (no shared
    Redis state between tests or parallel runs); ``browser.rate_limits`` exposes them."""
    from app.core import ratelimit
    from app.modules.identity import router as identity_router

    prev = ratelimit.set_backend(ratelimit.MemoryBackend())
    prev_floor = identity_router.SIGNUP_MIN_SECONDS
    identity_router.SIGNUP_MIN_SECONDS = 0.0  # SEC-05 timing floor: exercised by its own test
    try:
        yield Browser(client)
    finally:
        ratelimit.set_backend(prev)
        identity_router.SIGNUP_MIN_SECONDS = prev_floor


def last_code(mail: MemoryEmailAdapter) -> str:
    import re

    m = re.search(r"\b(\d{6})\b", mail.sent[-1].text)
    assert m, mail.sent[-1].text
    return m.group(1)


def last_link_token(mail: MemoryEmailAdapter, marker: str | None = None) -> str:
    """Token from the last email's web link (``/verify/email/<t>``, ``/reset-password/<t>``,
    ``/guardian-consent/<t>``, ``/invite/<t>``) or after an explicit ``marker``."""
    import re
    from urllib.parse import unquote

    text = mail.sent[-1].text
    if marker is not None:
        start = text.index(marker) + len(marker)
        return text[start:].split()[0]
    m = re.search(r"/(?:verify/email|reset-password|guardian-consent|invite)/([^\s/?#]+)", text)
    assert m, text
    return unquote(m.group(1))
