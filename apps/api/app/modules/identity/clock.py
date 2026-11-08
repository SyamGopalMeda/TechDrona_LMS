"""Single clock for identity/sessions/rbac/orgs logic (tests monkeypatch ``clock.now``).
Always call as ``clock.now()``."""

from __future__ import annotations

from datetime import datetime

from app.core.time import utcnow


def now() -> datetime:
    return utcnow()
