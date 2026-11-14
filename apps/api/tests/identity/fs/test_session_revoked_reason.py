"""Live audit 2026-11-14 (#14 / student F-12): a sign-in past the concurrent-session cap ends the
oldest session. The signed-out browser's next request must say why: 401 ``session_revoked`` with
``reason = session_cap_evicted`` and a detail naming the other sign-in. Firestore, no Postgres,
``TD_SIMPLE_AUTH`` on (as live). The caps themselves are unchanged."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest

from tests.identity.fs.conftest import fs_user


@pytest.fixture
def simple(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Requested before ``http`` (which resets the settings cache)."""
    monkeypatch.setenv("TD_SIMPLE_AUTH", "true")
    yield


async def test_evicted_session_gets_superseded_reason(simple: None, http: Any) -> None:
    u = await fs_user("cap@x.in")
    first, second, third = http, http.fork(), http.fork()
    for b in (first, second, third):  # student cap: 2 sessions at once
        r = await b.login(u.email, u.password)
        assert r.status_code == 200 and r.json()["result"] == "authenticated", r.text

    r = await first.get("/me")
    assert r.status_code == 401, r.text
    body = r.json()
    assert body["code"] == "session_revoked" and body["reason"] == "session_cap_evicted", body
    assert "signed in on another device" in body["detail"], body

    for b in (second, third):  # the newer sessions are untouched
        assert (await b.get("/me")).status_code == 200


async def test_other_revocations_keep_generic_detail(simple: None, http: Any) -> None:
    u = await fs_user("out@x.in")
    r = await http.login(u.email, u.password)
    assert r.status_code == 200, r.text
    from app.modules.sessions.repo_firestore import system_repo

    # a revocation whose reason is not user-safe (e.g. the risk engine)
    await system_repo().end_sessions(
        u.id, status="revoked", reason="risk_engine", where=lambda o: o.status == "active"
    )
    r = await http.get("/me")
    assert r.status_code == 401 and r.json()["reason"] == "security_action", r.text
    assert r.json()["detail"] == "You have been signed out"
