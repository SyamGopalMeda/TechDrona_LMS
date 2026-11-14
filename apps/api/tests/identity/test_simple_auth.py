"""TD_SIMPLE_AUTH (permanent owner decision 2026-11-12): plain email + password sign-in.

With the switch on: no MFA prompt or mandatory MFA enrolment, no new-device code, no step-up,
relaxed password policy, and an Admin's role grants apply at once. "Must change password on first
login" (``users.must_change_password``, set by an Admin) works in both modes: until the person
chooses a new password every route but a few answers 403 ``password_change_required``.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import pytest
from sqlalchemy import select

from app.core.config import reset_settings_cache
from app.core.db import system_context
from app.modules.identity.models import User
from app.modules.rbac.models import ApprovalRequest
from tests.identity.factory import Browser, grant, make_user


@pytest.fixture
def simple_auth(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("TD_SIMPLE_AUTH", "true")
    reset_settings_cache()
    yield
    monkeypatch.undo()
    reset_settings_cache()


def idem() -> dict[str, str]:
    return {"Idempotency-Key": uuid.uuid4().hex}


def _new_user(email: str, **kw: object) -> dict[str, object]:
    return {
        "full_name": "New Person",
        "email": email,
        "password": "simple1",  # relaxed policy in simple mode (min 6)
        "reason": "New hire onboarding",
        "confirm_adult": True,
        **kw,
    }


async def _admin(db, browser: Browser) -> object:
    """A super_admin WITHOUT any MFA factor, signed in with the password only."""
    sa = await make_user(db)
    await grant(db, sa.id, "super_admin")
    r = await browser.login(sa.email, sa.password)
    assert r.status_code == 200 and r.json()["result"] == "authenticated", r.text
    assert "must_change_password" not in r.json()
    return sa


async def test_simple_admin_signs_in_with_password_only(simple_auth, browser, db) -> None:
    sa = await _admin(db, browser)
    # no mfa_enrolment_required, no step-up on a P5 route
    assert (await browser.get("/admin/dashboard")).status_code == 200
    r = await browser.post("/admin/users", _new_user("plain.simple@example.com"), headers=idem())
    assert r.status_code == 201, r.text
    assert r.json()["must_change_password"] is False
    # a second, unknown device: no device verification code
    other = browser.fork()
    r = await other.login(sa.email, sa.password)
    assert r.status_code == 200 and r.json()["result"] == "authenticated", r.text
    assert (await other.get("/admin/dashboard")).status_code == 200
    # the web reads the mode
    pub = await browser.get("/public/integrations")
    assert pub.status_code == 200 and pub.json()["simple_auth"] is True


async def test_must_change_password_on_first_login(simple_auth, browser, client, db) -> None:
    await _admin(db, browser)
    r = await browser.post(
        "/admin/users",
        _new_user("first.login@example.com", role_key="content_manager", must_change_password=True),
        headers=idem(),
    )
    assert r.status_code == 201, r.text
    out = r.json()
    assert out["role"]["status"] == "granted" and out["must_change_password"] is True
    uid = uuid.UUID(out["user_id"])

    nb = Browser(client, ip="198.18.7.2")
    r = await nb.login("first.login@example.com", "simple1")
    assert r.status_code == 200, r.text
    assert r.json()["result"] == "authenticated" and r.json()["must_change_password"] is True
    me = await nb.get("/me")
    assert me.status_code == 200 and me.json()["user"]["must_change_password"] is True
    assert (await nb.get("/me/grants")).status_code == 200
    for path in ("/me/sessions", "/admin/dashboard"):
        denied = await nb.get(path)
        assert denied.status_code == 403 and denied.json()["code"] == "password_change_required", path
        assert denied.json()["change_url"] == "/change-password"

    r = await nb.post("/auth/password/change", {"current_password": "simple1", "new_password": "simple2"})
    assert r.status_code == 200, r.text
    assert (await nb.get("/me/sessions")).status_code == 200  # still signed in (rotated session)
    assert (await nb.get("/me")).json()["user"]["must_change_password"] is False
    await system_context(db, "test.simple_auth")
    db.expire_all()
    assert (await db.get(User, uid)).must_change_password is False


async def test_without_the_flag_the_assigned_password_just_works(simple_auth, browser, client, db) -> None:
    await _admin(db, browser)
    r = await browser.post("/admin/users", _new_user("keeps.password@example.com"), headers=idem())
    assert r.status_code == 201, r.text
    nb = Browser(client, ip="198.18.7.3")
    r = await nb.login("keeps.password@example.com", "simple1")
    assert r.status_code == 200 and r.json()["result"] == "authenticated"
    assert "must_change_password" not in r.json()
    assert (await nb.get("/me/sessions")).status_code == 200


async def test_admin_set_password_can_require_a_change(simple_auth, browser, client, db) -> None:
    await _admin(db, browser)
    u = await make_user(db)
    r = await browser.post(
        f"/admin/users/{u.id}/password",
        {"password": "reset1", "reason": "Forgot their password", "must_change_password": True},
        headers=idem(),
    )
    assert r.status_code == 200 and r.json()["must_change_password"] is True, r.text
    nb = Browser(client, ip="198.18.7.4")
    r = await nb.login(u.email, "reset1")
    assert r.json()["result"] == "authenticated" and r.json()["must_change_password"] is True
    assert (await nb.get("/me/sessions")).json()["code"] == "password_change_required"


async def test_admin_grants_any_role_at_once(simple_auth, browser, db) -> None:
    sa = await _admin(db, browser)
    other = await make_user(db)
    r = await browser.post(
        "/rbac/grants",
        {
            "user_id": str(other.id),
            "role_key": "super_admin",
            "scope_type": "platform",
            "reason": "New admin",
        },
        headers=idem(),
    )
    assert r.status_code == 201 and "grant_id" in r.json(), r.text
    r = await browser.post(
        "/admin/users", _new_user("boss.simple@example.com", role_key="super_admin"), headers=idem()
    )
    assert r.status_code == 201 and r.json()["role"]["status"] == "granted", r.text
    await system_context(db, "test.simple_auth")
    pending = (
        (await db.execute(select(ApprovalRequest).where(ApprovalRequest.requested_by == sa.id)))
        .scalars()
        .all()
    )
    assert pending == []
    # self-grant rules are unchanged
    r = await browser.post(
        "/rbac/grants",
        {"user_id": str(sa.id), "role_key": "content_manager", "scope_type": "platform", "reason": "Self"},
        headers=idem(),
    )
    assert r.status_code == 403 and r.json()["code"] == "sod_violation"


async def test_strict_mode_unchanged(browser, db) -> None:
    sa = await make_user(db)
    await grant(db, sa.id, "super_admin")
    r = await browser.login(sa.email, sa.password)
    assert r.status_code == 200 and r.json()["result"] == "authenticated"
    r = await browser.get("/admin/dashboard")
    assert r.status_code == 403 and r.json()["code"] == "mfa_enrolment_required"
    pub = await browser.get("/public/integrations")
    assert pub.json()["simple_auth"] is False
