"""ADM-06: an Admin creates an account (starting password) and optionally grants a role in the
same step. Non-privileged roles are granted at once; Admin goes to dual control."""

from __future__ import annotations

from sqlalchemy import select

from app.modules.identity.models import User
from app.modules.rbac.models import ApprovalRequest
from tests.identity.factory import GOOD_PASSWORD, Browser
from tests.security.helpers import adult, idem, staff, staff_browser


def _body(email: str, **kw: object) -> dict[str, object]:
    return {
        "full_name": "New Person",
        "email": email,
        "password": GOOD_PASSWORD,
        "reason": "New hire onboarding",
        "confirm_adult": True,
        **kw,
    }


async def test_admin_creates_user_with_role_and_user_can_sign_in(client, db) -> None:
    sa = await staff(db, "super_admin")
    bsa = await staff_browser(client, sa, ip="198.18.6.1")

    r = await bsa.post(
        "/admin/users", _body("New.Person@Example.com", role_key="content_manager"), headers=idem()
    )
    assert r.status_code == 201, r.text
    out = r.json()
    assert out["status"] == "active" and out["role"]["status"] == "granted"
    u = (await db.execute(select(User).where(User.email == "new.person@example.com"))).scalar_one()
    assert u.account_origin == "staff_created" and u.email_verified_at is not None and not u.is_minor
    detail = (await bsa.get(f"/admin/users/{u.id}")).json()
    assert [g["role"] for g in detail["grants"]] == ["content_manager"]

    dup = await bsa.post("/admin/users", _body("new.person@example.com"), headers=idem())
    assert dup.status_code == 422 and dup.json()["errors"][0]["field"] == "email"

    plain = await bsa.post("/admin/users", _body("plain@example.com"), headers=idem())
    assert plain.status_code == 201 and plain.json()["role"] is None
    nb = Browser(client)
    assert (await nb.login("plain@example.com")).status_code == 200


async def test_admin_role_needs_second_admin_and_others_cannot_create(client, db) -> None:
    sa = await staff(db, "super_admin")
    bsa = await staff_browser(client, sa, ip="198.18.6.2")
    r = await bsa.post("/admin/users", _body("boss@example.com", role_key="super_admin"), headers=idem())
    assert r.status_code == 201, r.text
    assert r.json()["role"]["status"] == "approval_pending"
    req = await db.get(ApprovalRequest, __import__("uuid").UUID(r.json()["role"]["approval_request_id"]))
    assert req is not None and req.action_type == "rbac.grant.privileged"

    trainer_scope = await bsa.post("/admin/users", _body("t@example.com", role_key="trainer"), headers=idem())
    assert trainer_scope.status_code == 422  # trainer needs a batch or course

    cm = await staff(db, "content_manager")
    bcm = await staff_browser(client, cm, ip="198.18.6.3")
    assert (await bcm.post("/admin/users", _body("x@example.com"), headers=idem())).status_code == 403
    student = await adult(db)
    sb = Browser(client)
    await sb.login(student.email)
    assert (await sb.post("/admin/users", _body("y@example.com"), headers=idem())).status_code == 403
