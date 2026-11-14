"""TD_ACCOUNT_PROTECTION_OFF (testing phase): no takeover lock or step-up, an existing protect-lock
ends at the next sign-in; ignored in production."""

from __future__ import annotations

from app.core.config import get_settings
from app.core.db import system_context
from app.modules.identity.models import User
from app.modules.security import engine
from app.modules.security import restrictions as rx
from tests.identity.factory import Browser
from tests.security.helpers import adult


async def test_existing_lock_ends_and_engine_is_quiet(client, db, monkeypatch) -> None:
    u = await adult(db)
    await system_context(db, "test.protect")
    await engine.protect_lock(db, await db.get(User, u.id), "TO-score")
    await db.commit()
    r = await Browser(client).login(u.email)
    assert r.status_code == 403 and r.json()["code"] == "account_protect_locked"

    monkeypatch.setattr(get_settings(), "TD_ACCOUNT_PROTECTION_OFF", True)
    r = await Browser(client).login(u.email)
    assert r.status_code == 200, r.text
    db.expire_all()
    state = await rx.restriction_state(db, u.id)
    assert not state.takeover_lock and not state.step_up_required
    assert (await db.get(User, u.id)).must_change_password is False
    assert await engine.evaluate_takeover(db, u.id, trigger="login") is None
