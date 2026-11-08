"""Single-company batches (REMOVAL-PLAN §3): Admin manages batches and adds any account;
trainers manage their own batch; memberships follow batch membership; the college surfaces
(``/orgs``, ``/invitations``, ``/me/orgs``) are gone. Also the orgs public helpers (BE-02)."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select, update

from app.core.company import COMPANY_ORG_ID
from app.core.db import system_context
from app.modules.orgs.models import Batch, BatchMember, OrgMembership
from app.modules.orgs.service import LearnerOrgContext, get_learner_org_context
from tests.identity.factory import add_member, company_org, grant, make_batch, make_user, staff_login


async def _admin(db, browser):
    a = await make_user(db, with_totp=True)
    await grant(db, a.id, "super_admin")
    await staff_login(browser, a)
    return a


async def _membership(db, user_id: uuid.UUID) -> OrgMembership | None:
    await system_context(db, "t")
    return (
        await db.execute(
            select(OrgMembership)
            .where(OrgMembership.organization_id == COMPANY_ORG_ID, OrgMembership.user_id == user_id)
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/orgs"),
        ("POST", "/orgs"),
        ("GET", f"/orgs/{COMPANY_ORG_ID}"),
        ("GET", f"/orgs/{COMPANY_ORG_ID}/members"),
        ("GET", f"/orgs/{COMPANY_ORG_ID}/batches"),
        ("POST", f"/orgs/{COMPANY_ORG_ID}/imports"),
        ("POST", f"/orgs/{COMPANY_ORG_ID}/invitations"),
        ("POST", f"/orgs/{COMPANY_ORG_ID}/suspend"),
        ("GET", "/invitations/abcdefghijklmnopqrstuvwxyz"),
        ("POST", "/invitations/abcdefghijklmnopqrstuvwxyz/accept"),
        ("GET", "/me/orgs"),
    ],
)
async def test_college_org_routes_are_gone(browser, db, method, path) -> None:
    await _admin(db, browser)
    r = await browser.request(method, path, json={} if method != "GET" else None)
    assert r.status_code in (404, 405), (method, path, r.status_code)


async def test_admin_creates_batches_in_the_company_org(browser, db) -> None:
    await _admin(db, browser)
    r = await browser.post("/batches", {"name": "CSE 2027", "code": "WS1-CSE27"})
    assert r.status_code == 201, r.text
    assert r.json()["organization_id"] == str(COMPANY_ORG_ID)
    dup = await browser.post("/batches", {"name": "dup", "code": "WS1-CSE27"})
    assert dup.status_code == 409
    # an organization id in the body is not accepted
    bad = await browser.post("/batches", {"name": "x", "code": "WS1-X", "organization_id": str(uuid.uuid4())})
    assert bad.status_code in (400, 422)
    codes = {b["code"] for b in (await browser.get("/batches")).json()["data"]}
    assert "WS1-CSE27" in codes


async def test_non_admins_cannot_create_or_list_all_batches(browser, db) -> None:
    owner = await make_user(db)
    mine = await make_batch(db, company_org(), owner.id)
    other = await make_batch(db, company_org(), owner.id)
    trainer = await make_user(db, with_totp=True)
    await grant(db, trainer.id, "trainer", "batch", mine)
    tb = browser.fork()
    await staff_login(tb, trainer)
    assert (await tb.post("/batches", {"name": "x", "code": "WS1-T1"})).status_code == 403
    assert [b["id"] for b in (await tb.get("/batches")).json()["data"]] == [str(mine)]
    # a sibling batch is outside the trainer's grant (same org: 403, not 404)
    r = await tb.get(f"/batches/{other}/members")
    assert r.status_code == 403 and r.json()["code"] == "permission_denied"
    student = await make_user(db)
    sb = browser.fork(ua="Mozilla/5.0 (X11; Linux x86_64; rv:131.0) Gecko/20100101 Firefox/131.0")
    await sb.login(student.email)
    assert (await sb.get("/batches")).status_code == 403
    assert (await sb.post("/batches", {"name": "x", "code": "WS1-S1"})).status_code == 403


async def test_admin_adds_any_account_and_membership_follows_batches(browser, db) -> None:
    """A public learner with no organization joins a batch (by id or e-mail): the company
    membership is created; leaving the last batch sets it to ``left``; re-adding reactivates."""
    admin = await _admin(db, browser)
    a = await make_batch(db, company_org(), admin.id)
    b = await make_batch(db, company_org(), admin.id)
    s1, s2 = await make_user(db), await make_user(db)
    assert await _membership(db, s1.id) is None
    r = await browser.post(f"/batches/{a}/members", {"user_ids": [str(s1.id)], "emails": [s2.email.upper()]})
    assert r.status_code == 200 and r.json()["added"] == 2, r.text
    m = await _membership(db, s1.id)
    assert m is not None and (m.member_type, m.status, m.source) == ("student", "active", "staff")
    # unknown or unusable accounts are refused as a whole
    gone = await make_user(db, status="deactivated")
    for body in (
        {"user_ids": [str(uuid.uuid4())]},
        {"emails": ["nobody-ws1@example.com"]},
        {"user_ids": [str(gone.id)]},
    ):
        r = await browser.post(f"/batches/{a}/members", body)
        assert r.status_code == 422 and r.json()["errors"][0]["code"] == "unknown_account", body
    assert (await browser.post(f"/batches/{a}/members", {"user_ids": []})).status_code in (400, 422)
    # in two batches: leaving one keeps the membership
    assert (await browser.post(f"/batches/{b}/members", {"user_ids": [str(s1.id)]})).json()["added"] == 1
    assert (await browser.delete(f"/batches/{a}/members/{s1.id}")).status_code == 200
    m = await _membership(db, s1.id)
    assert m is not None and m.status == "active"
    # leaving the last batch ends it
    assert (await browser.delete(f"/batches/{b}/members/{s1.id}")).status_code == 200
    m = await _membership(db, s1.id)
    assert m is not None and m.status == "left" and m.left_at is not None
    # re-adding reactivates the same row
    assert (await browser.post(f"/batches/{b}/members", {"user_ids": [str(s1.id)]})).json()["added"] == 1
    m2 = await _membership(db, s1.id)
    assert m2 is not None and m2.id == m.id and m2.status == "active" and m2.left_at is None
    # trainer members become staff members; staff is never downgraded
    t = await make_user(db)
    assert (
        await browser.post(f"/batches/{a}/members", {"user_ids": [str(t.id)], "member_role": "trainer"})
    ).json()["added"] == 1
    assert (await browser.post(f"/batches/{b}/members", {"user_ids": [str(t.id)]})).json()["added"] == 1
    mt = await _membership(db, t.id)
    assert mt is not None and mt.member_type == "staff"


async def test_trainer_manages_own_batch_members(browser, db) -> None:
    owner = await make_user(db)
    mine = await make_batch(db, company_org(), owner.id)
    other = await make_batch(db, company_org(), owner.id)
    trainer = await make_user(db, with_totp=True)
    await grant(db, trainer.id, "trainer", "batch", mine)
    await staff_login(browser, trainer)
    s = await make_user(db, full_name="Asha Learner")
    r = await browser.post(f"/batches/{mine}/members", {"emails": [s.email]})
    assert r.status_code == 200 and r.json()["added"] == 1, r.text
    roster = (await browser.get(f"/batches/{mine}/members")).json()["data"]
    assert [(m["user_id"], m["full_name"]) for m in roster] == [(str(s.id), "Asha Learner")]
    r = await browser.post(f"/batches/{other}/members", {"user_ids": [str(s.id)]})
    assert r.status_code == 403
    # moving out of a batch the trainer does not manage is hidden (404)
    r = await browser.post(
        f"/batches/{mine}/members", {"user_ids": [str(s.id)], "move_from_batch_id": str(other)}
    )
    assert r.status_code == 404


async def test_batch_lifecycle_state_checks(browser, db) -> None:
    """BE-18: archive is a one-way transition; archived batches are read-only."""
    admin = await _admin(db, browser)
    s = await make_user(db)
    batch = await make_batch(db, company_org(), admin.id)
    other = await make_batch(db, company_org(), admin.id)
    assert (await browser.post(f"/batches/{batch}/members", {"user_ids": [str(s.id)]})).json()["added"] == 1
    r = await browser.post(f"/batches/{batch}/archive")
    assert r.status_code == 200 and r.json()["status"] == "archived"
    again = await browser.post(f"/batches/{batch}/archive")
    assert again.status_code == 409 and again.json()["code"] == "invalid_state_transition"
    add = await browser.post(f"/batches/{batch}/members", {"user_ids": [str(s.id)]})
    assert add.status_code == 409
    assert (await browser.patch(f"/batches/{batch}", {"status": "active"})).status_code == 409
    assert (await browser.patch(f"/batches/{batch}", {"name": "Renamed"})).status_code == 409
    move_out = await browser.post(
        f"/batches/{other}/members", {"user_ids": [str(s.id)], "move_from_batch_id": str(batch)}
    )
    assert move_out.status_code == 409
    assert (await browser.delete(f"/batches/{batch}/members/{s.id}")).status_code == 409
    await system_context(db, "t")
    b = (await db.execute(select(Batch).where(Batch.id == batch))).scalar_one()
    assert b.status == "archived" and b.name == "CSE 2027"


async def test_batch_member_moves_and_patch(browser, db) -> None:
    """INV-05 backend: add, move, remove members, PATCH and no-op handling (now by Admin)."""
    await _admin(db, browser)
    s1, s2 = await make_user(db), await make_user(db)
    a = (await browser.post("/batches", {"name": "A", "code": "WS1-A1"})).json()["id"]
    b = (await browser.post("/batches", {"name": "B", "code": "WS1-B1"})).json()["id"]
    r = await browser.post(f"/batches/{a}/members", {"user_ids": [str(s1.id), str(s2.id)]})
    assert r.status_code == 200 and r.json()["added"] == 2
    assert (await browser.post(f"/batches/{a}/members", {"user_ids": [str(s1.id)]})).json()["added"] == 0
    r = await browser.post(f"/batches/{b}/members", {"user_ids": [str(s1.id)], "move_from_batch_id": a})
    assert r.status_code == 200 and r.json()["added"] == 1
    same = await browser.post(f"/batches/{a}/members", {"user_ids": [str(s2.id)], "move_from_batch_id": a})
    assert same.status_code == 422
    in_a = {m["user_id"] for m in (await browser.get(f"/batches/{a}/members")).json()["data"]}
    in_b = {m["user_id"] for m in (await browser.get(f"/batches/{b}/members")).json()["data"]}
    assert in_a == {str(s2.id)} and in_b == {str(s1.id)}
    m = await _membership(db, s1.id)
    assert m is not None and m.status == "active"  # moved, still in a batch
    assert (await browser.delete(f"/batches/{a}/members/{s2.id}")).status_code == 200
    assert (await browser.delete(f"/batches/{a}/members/{s2.id}")).status_code == 404
    r = await browser.patch(f"/batches/{b}", {"name": "B renamed", "starts_on": "2026-12-01"})
    assert r.status_code == 200 and r.json()["name"] == "B renamed"
    assert (await browser.patch(f"/batches/{b}", {"ends_on": "2026-01-01"})).status_code == 422
    assert (await browser.patch(f"/batches/{b}", {"status": "completed"})).json()["status"] == "completed"


async def test_get_learner_org_context(db) -> None:
    """BE-02: orgs public function resolving a learner's organization/batch (compat shim)."""
    org = company_org()
    creator = await make_user(db)
    b1 = await make_batch(db, org, creator.id)
    b2 = await make_batch(db, org, creator.id)
    s = await make_user(db)
    await system_context(db, "t")
    assert await get_learner_org_context(db, s.id) is None  # public learner: no organization
    await add_member(db, org, s.id, "student", b1)
    assert await get_learner_org_context(db, s.id) == LearnerOrgContext(org, b1)
    assert await get_learner_org_context(db, s.id, batch_id=b2) == LearnerOrgContext(org, b1)
    await system_context(db, "t")
    db.add(
        BatchMember(id=uuid.uuid4(), batch_id=b2, organization_id=org, user_id=s.id, member_role="student")
    )
    await db.flush()
    assert await get_learner_org_context(db, s.id) == LearnerOrgContext(org, None)  # two batches
    assert await get_learner_org_context(db, s.id, batch_id=b2) == LearnerOrgContext(org, b2)
    await db.execute(update(Batch).where(Batch.id == b2).values(status="archived"))
    assert await get_learner_org_context(db, s.id) == LearnerOrgContext(org, b1)
    assert await get_learner_org_context(db, s.id, batch_id=b2) == LearnerOrgContext(org, b1)


async def test_be02_public_org_helpers(db) -> None:
    from app.modules.orgs.service import active_student_org_ids, batch_org_for_member

    org = company_org()
    u = await make_user(db)
    owner = await make_user(db)
    batch = await make_batch(db, org, owner.id)
    await add_member(db, org, u.id, "student", batch_id=batch)
    await system_context(db, "t")
    assert await active_student_org_ids(db, u.id) == [COMPANY_ORG_ID]
    assert await batch_org_for_member(db, batch, u.id) == COMPANY_ORG_ID
    assert await batch_org_for_member(db, batch, owner.id) is None
    assert await batch_org_for_member(db, uuid.uuid4(), u.id) is None
