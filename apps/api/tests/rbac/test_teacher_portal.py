"""Owner request 2026-11-12, "Be a Teacher": an Admin makes themselves the trainer of a batch
through the normal batch-staff path (``POST /rbac/grants``), with no dual control and no second
sign-in, and their Teacher portal then lists only the batches they teach."""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import func, select

from app.core.db import system_context
from app.core.ids import uuid7
from app.modules.learning.models import Assignment
from app.modules.rbac.models import ApprovalRequest, Role, RoleGrant
from tests.identity.factory import company_org, grant, make_batch, make_user, staff_login


async def _assignment(db, org, batch, created_by, title: str):
    await system_context(db, "test.factory")
    aid = uuid7()
    db.add(
        Assignment(
            id=aid,
            organization_id=org,
            batch_id=batch,
            title=title,
            instructions_md="Do it.",
            submission_type="text",
            max_score=Decimal(10),
            allowed_file_types=["pdf"],
            created_by=created_by,
        )
    )
    await db.flush()
    return aid


async def test_admin_self_assigns_as_batch_trainer_and_teacher_views_are_scoped(browser, db) -> None:
    org = company_org()
    sa = await make_user(db, with_totp=True)
    await grant(db, sa.id, "super_admin")
    taught = await make_batch(db, org, sa.id)
    other = await make_batch(db, org, sa.id)
    a_taught = await _assignment(db, org, taught, sa.id, "Taught batch worksheet")
    a_other = await _assignment(db, org, other, sa.id, "Other batch worksheet")
    await staff_login(browser, sa)

    # Before: the Teacher portal list is empty; the Admin view still has every batch.
    mine = await browser.get("/batches", params={"mine": "true"})
    assert mine.status_code == 200 and mine.json() == {"data": []}, mine.text
    assert (await browser.get("/me/grants")).json()["portals"] == ["/admin"]

    r = await browser.post(
        "/rbac/grants",
        {
            "user_id": str(sa.id),
            "role_key": "trainer",
            "scope_type": "batch",
            "scope_id": str(taught),
            "reason": "I teach this batch",
        },
        headers={"Idempotency-Key": "self-trainer-0001"},
    )
    assert r.status_code == 201, r.text  # immediate: trainer is not a dual-control role
    gid = r.json()["grant_id"]

    await system_context(db, "test.check")
    pending = (
        await db.execute(
            select(func.count()).select_from(ApprovalRequest).where(ApprovalRequest.requested_by == sa.id)
        )
    ).scalar_one()
    assert pending == 0
    rows = (
        await db.execute(
            select(RoleGrant.scope_type, RoleGrant.scope_id, RoleGrant.granted_by)
            .join(Role, Role.id == RoleGrant.role_id)
            .where(RoleGrant.user_id == sa.id, Role.role_key == "trainer", RoleGrant.revoked_at.is_(None))
        )
    ).all()
    assert [(st, sid, by) for st, sid, by in rows] == [("batch", taught, sa.id)]

    # Same session keeps working (no re-login) and now offers the Teacher portal.
    me = await browser.get("/me")
    assert me.status_code == 200 and me.json()["session"]["tier"] == "privileged", me.text
    assert (await browser.get("/me/grants")).json()["portals"] == ["/admin", "/trainer"]

    # Teacher portal lists: only the batch they teach, and only its work.
    mine = (await browser.get("/batches", params={"mine": "true"})).json()["data"]
    assert [b["id"] for b in mine] == [str(taught)]
    everything = {b["id"] for b in (await browser.get("/batches")).json()["data"]}
    assert {str(taught), str(other)} <= everything  # the Admin view is unchanged
    teaching = await browser.get("/assignments", params={"scope": "mine", "teaching": "true"})
    assert teaching.status_code == 200, teaching.text
    ids = {x["assignment_id"] for x in teaching.json()["data"]}
    assert str(a_taught) in ids and str(a_other) not in ids

    # Grading lists are teacher work: Admin holds no assignment.grade/manage (catalogue "SA" = "-"),
    # so outside the batch they teach an Admin's grading list stays empty, with or without teaching=true.
    def ids_of(r):
        assert r.status_code == 200, r.text
        return {x["assignment_id"] for x in r.json()["data"]}

    assert str(a_taught) in ids_of(await browser.get("/assignments", params={"batch_id": str(taught)}))
    assert str(a_other) not in ids_of(await browser.get("/assignments", params={"batch_id": str(other)}))

    # Unassigning works the same way and also keeps the session.
    r = await browser.post(f"/rbac/grants/{gid}/revoke", {"reason": "handing over the batch"})
    assert r.status_code == 200 and r.json()["revoked"] is True, r.text
    assert (await browser.get("/me")).status_code == 200
    assert (await browser.get("/batches", params={"mine": "true"})).json() == {"data": []}
    assert (await browser.get("/me/grants")).json()["portals"] == ["/admin"]


async def test_regular_trainer_assignment_still_rotates_grantee_sessions(browser, db) -> None:
    """Assigning someone else is unchanged: their sessions end so the new tier applies."""
    org = company_org()
    sa = await make_user(db, with_totp=True)
    await grant(db, sa.id, "super_admin")
    batch = await make_batch(db, org, sa.id)
    t = await make_user(db, with_totp=True)
    tb = browser.fork(ua="Mozilla/5.0 (X11; Linux x86_64; rv:131.0) Gecko/20100101 Firefox/131.0")
    await staff_login(tb, t)
    await staff_login(browser, sa)
    r = await browser.post(
        "/rbac/grants",
        {
            "user_id": str(t.id),
            "role_key": "trainer",
            "scope_type": "batch",
            "scope_id": str(batch),
            "reason": "new trainer",
        },
        headers={"Idempotency-Key": "other-trainer-0001"},
    )
    assert r.status_code == 201, r.text
    assert (await tb.get("/me")).status_code == 401
    await staff_login(tb, t)
    assert [b["id"] for b in (await tb.get("/batches", params={"mine": "true"})).json()["data"]] == [
        str(batch)
    ]
    # a trainer never reaches Admin features
    assert (await tb.get("/rbac/grants")).status_code == 403
    assert (await tb.get("/admin/dashboard")).status_code == 403
