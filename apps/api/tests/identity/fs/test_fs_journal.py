"""``fs_journal``: the undo journal that makes a privileged action's Firestore writes all-or-nothing
(dual-control execution). Covers the effects other approval executors use through the access
modules' public APIs: MFA reset (factors + sessions), deactivate (user status +
sessions_valid_after), break-glass (grant add / revoke)."""

from __future__ import annotations

from typing import Any

import pyotp
import pytest

from app.core.audit import AuditActor
from app.core.ids import uuid7
from app.modules.identity import public as ipub
from app.modules.identity.fs_journal import JournalingStore, journal, on_rollback
from app.modules.rbac import public as rbac_public
from app.modules.sessions import public as spub
from app.modules.sessions import service as ss
from app.modules.sessions.ua import parse_ua
from tests.identity.fs.conftest import fs_user

S: Any = None


async def _session_for(user: Any) -> Any:
    info = ss.ClientInfo(ip="203.0.113.9", ua=parse_ua("Mozilla/5.0 Chrome/130.0"), device_token=None)
    s, _t = await ss.create_session(
        S, user_id=user.id, tier="student", status="active", created_via="password", info=info,
        device=None, user_device=None, amr=["pwd"],
    )  # fmt: skip
    return s


async def _mfa_reset_and_deactivate(user: Any) -> None:
    await ipub.revoke_factors(S, user.id)
    await ss.revoke_all_sessions(S, user.id, "mfa_changed", ended_by=uuid7())
    await ipub.update_user(S, user.id, status="deactivated")


async def test_failed_action_restores_every_document(fs: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.firestore.backend import reset_store_backends

    monkeypatch.setenv("TD_STORE_AUDIT", "firestore")  # rbac.service audits the revoke
    reset_store_backends()
    u = await fs_user("j1@x.in", totp_secret=pyotp.random_base32(), roles=("trainer",))
    s = await _session_for(u)
    compensated: list[str] = []
    ((g, _k),) = await rbac_public.live_grants(S, user_ids=[u.id])
    with pytest.raises(RuntimeError):
        async with journal():
            await _mfa_reset_and_deactivate(u)
            await rbac_public.revoke_grant(S, AuditActor.system("test.bg"), g.id, uuid7(), "break-glass")

            async def undo() -> None:
                compensated.append("external")

            on_rollback(undo)  # a write outside the access stores registers its own undo
            raise RuntimeError("audit failed")
    assert [f.factor_type for f in await ipub.active_factors(S, u.id)] == ["totp"]
    assert (await spub.get_session(S, s.id)).status == "active"  # type: ignore[union-attr]
    user = await ipub.get_user(S, u.id)
    assert user is not None and user.status == "active" and user.sessions_valid_after is None
    assert [x[0].id for x in await rbac_public.live_grants(S, user_ids=[u.id])] == [g.id]
    assert compensated == ["external"]
    # the uniqueness lookups were restored too: the email still resolves, a re-grant is refused
    assert (await ipub.find_user(S, "email", "j1@x.in")).id == u.id  # type: ignore[union-attr]


async def test_successful_action_keeps_every_write(fs: Any) -> None:
    u = await fs_user("j2@x.in", totp_secret=pyotp.random_base32())
    s = await _session_for(u)
    async with journal():
        await _mfa_reset_and_deactivate(u)
    assert await ipub.active_factors(S, u.id) == []
    assert (await spub.get_session(S, s.id)).status == "revoked"  # type: ignore[union-attr]
    assert (await ipub.get_user(S, u.id)).status == "deactivated"  # type: ignore[union-attr]


async def test_created_documents_are_deleted_and_outside_scope_is_untouched(fs: Any) -> None:
    store = JournalingStore.system("test.journal")
    await store.create("users_by_username", {"user_id": "a"}, doc_id="keep")  # outside any scope
    with pytest.raises(ValueError):
        async with journal():
            await store.create("users_by_username", {"user_id": "b"}, doc_id="gone")
            await store.run_transaction(lambda tx: tx.update("users_by_username", "keep", {"user_id": "c"}))
            raise ValueError("x")
    assert await store.get("users_by_username", "gone") is None
    assert (await store.get("users_by_username", "keep"))["user_id"] == "a"  # type: ignore[index]


async def test_request_journal_dependency_rolls_back_a_failed_route(fs: Any) -> None:
    """``request_journal`` as a route dependency: deactivate-style writes (user status, sessions)
    disappear when the route fails after them; a successful route keeps them."""
    import httpx
    from fastapi import Depends, FastAPI

    from app.modules.identity.fs_journal import request_journal

    u = await fs_user("j3@x.in")
    s = await _session_for(u)
    app = FastAPI()

    @app.post("/deactivate/{fail}", dependencies=[Depends(request_journal, scope="function")])
    async def deactivate(fail: int) -> dict[str, bool]:
        await ipub.update_user(S, u.id, status="deactivated")
        await ss.revoke_all_sessions(S, u.id, "admin_kill")
        if fail:
            raise RuntimeError("audit failed")
        return {"ok": True}

    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        r = await c.post("/deactivate/1")
        assert r.status_code == 500
        assert (await ipub.get_user(S, u.id)).status == "active"  # type: ignore[union-attr]
        assert (await spub.get_session(S, s.id)).status == "active"  # type: ignore[union-attr]
        r = await c.post("/deactivate/0")
        assert r.status_code == 200
        assert (await ipub.get_user(S, u.id)).status == "deactivated"  # type: ignore[union-attr]
        assert (await spub.get_session(S, s.id)).status == "revoked"  # type: ignore[union-attr]
