"""w2a security fixes: the replay notice links to the web "not me" page (weblearn request), and
E2E-13 -- the unblock form offers only trusted devices; ``preferred_contact`` defaults to in-app."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select, update

from app.core.db import system_context
from app.modules.security import engine
from app.modules.security.models import UnblockRequest
from app.modules.security.signals import on_replay_blocked
from app.modules.sessions.models import AuthSession, UserDevice
from tests.security.helpers import adult, device_session, idem
from tests.security.test_scn_unblock import EXPL, restricted_student


async def test_replay_notice_disown_url_is_the_web_page(db, monkeypatch) -> None:
    sent: list[dict[str, Any]] = []

    async def _capture(session: Any, user_id: Any, template_key: str, **kw: Any) -> None:
        sent.append({"template": template_key, **(kw.get("data") or {})})

    monkeypatch.setattr(engine, "notify_user", _capture)
    u = await adult(db)
    _dev, sid = await device_session(db, u.id, ip="49.36.1.3", ua_family="Chrome", os_family="Windows")
    await system_context(db, "test.w2a")
    await on_replay_blocked(db, await db.get(AuthSession, sid), "TO-08", {"ua_family": "Firefox"})
    notice = next(n for n in sent if n["template"] == "security.session_replay")
    assert notice["disown_url"] == f"/app/settings/security/not-me/{notice['event_ref']}"


async def test_e2e13_form_lists_trusted_devices_and_contact_defaults_in_app(client, db, sms) -> None:
    u, b, case, _r, laptop_ud, other = await restricted_student(db, client)
    await system_context(db, "test.w2a")
    await db.execute(update(UserDevice).where(UserDevice.id == laptop_ud).values(trust_status="trusted"))
    await db.execute(
        update(UserDevice)
        .where(UserDevice.user_id == u.id, UserDevice.device_id == other[0])
        .values(trust_status="pending_otp")
    )
    await db.flush()
    form = await b.get("/security/unblock-requests/form", params={"case_ref": case.case_ref})
    assert form.status_code == 200, form.text
    assert [d["user_device_id"] for d in form.json()["devices"]] == [str(laptop_ud)]

    body = {
        "case_ref": case.case_ref,
        "submit": True,
        "what_happened": ["family_member_used"],
        "explanation": EXPL,
        "recognised_user_device_ids": [str(laptop_ud)],
        "declaration": True,
    }
    res = await b.post("/security/unblock-requests", body, headers=idem())
    assert res.status_code == 201, res.text
    await system_context(db, "test.w2a")
    db.expunge_all()
    ur = (await db.execute(select(UnblockRequest).where(UnblockRequest.user_id == u.id))).scalar_one()
    assert ur.preferred_contact == "in_app"
