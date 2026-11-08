"""ADM-41 (w2a): matrix ``course.create/edit`` trainer = "C / O-private". A batch-scoped trainer
creates and edits org-private courses of their batch's organization; never platform courses,
never another organization's courses, and no other permission is widened."""

from __future__ import annotations

from app.core.auth import PLATFORM_SCOPE, ScopeRef
from app.core.ids import uuid7
from app.core.principal import Principal, RoleGrant
from app.modules.rbac.service import RbacPermissionChecker
from tests.identity.factory import (
    add_member,
    company_org,
    grant,
    make_batch,
    make_user,
    staff_login,
)


async def test_batch_trainer_scope_covers_org_private_course_permissions_only(db) -> None:
    # single company: the only "other organization" a principal can name is one that does not
    # exist (orgs_0003 allows exactly one live org)
    org, other = company_org(), uuid7()
    u = await make_user(db)
    b = await make_batch(db, org, u.id)
    p = Principal(uuid7(), uuid7(), org_ids=(org,), grants=(RoleGrant("trainer", "batch", b),))
    chk = RbacPermissionChecker()
    assert await chk.has_permission(p, "course.create", ScopeRef("organization", org), None)  # type: ignore[arg-type]
    assert await chk.has_permission(p, "course.edit", ScopeRef("organization", org), None)  # type: ignore[arg-type]
    assert not await chk.has_permission(p, "course.create", PLATFORM_SCOPE, None)  # type: ignore[arg-type]
    # Not widened: other permissions keep their own cells (trainer course.preview is C only).
    assert not await chk.has_permission(p, "course.preview", ScopeRef("organization", org), None)  # type: ignore[arg-type]
    assert not await chk.has_permission(p, "batch.create", ScopeRef("organization", org), None)  # type: ignore[arg-type]
    # Any other organization id: cross-tenant -> 404 (TI-02), never a grant.
    from app.core.errors import ProblemError

    try:
        allowed = await chk.has_permission(p, "course.create", ScopeRef("organization", other), None)  # type: ignore[arg-type]
    except ProblemError as e:
        assert e.code == "not_found"
    else:
        assert allowed is False


async def test_batch_trainer_creates_and_edits_org_private_course(browser, db) -> None:
    org = company_org()
    trainer = await make_user(db, with_totp=True)
    await add_member(db, org, trainer.id, "staff")
    batch = await make_batch(db, org, trainer.id)
    await grant(db, trainer.id, "trainer", "batch", batch)
    tr = browser.fork()
    await staff_login(tr, trainer)

    # Single company (WS4): no organization_id input; a batch trainer's course is a company course.
    body = {"title": "Batch DSA", "slug": f"batch-dsa-{uuid7().hex[:6]}", "visibility": "private"}
    r = await tr.post("/studio/courses", body)
    assert r.status_code == 201, r.text
    cid = r.json()["id"]
    assert r.json()["organization_id"] == str(org)

    r = await tr.get(f"/studio/courses/{cid}")
    assert r.status_code == 200, r.text
    r = await tr.patch(f"/studio/courses/{cid}/draft", {"summary": "Arrays, strings and graphs"})
    assert r.status_code == 200, r.text

    # organization_id is not accepted any more.
    r = await tr.post("/studio/courses", {**body, "slug": body["slug"] + "-o", "organization_id": str(org)})
    assert r.status_code == 400, r.text


async def test_studio_courses_lists_batch_org_private_courses(browser, db) -> None:
    """ADM-41 listing (w3be): CAT-08 ``GET /studio/courses`` shows a batch trainer the org-private
    courses of the company (including ones other staff created), never platform courses.
    (Single company: there is no other organization whose courses could leak.)"""
    org = company_org()
    trainer = await make_user(db, with_totp=True)
    await add_member(db, org, trainer.id, "staff")
    batch = await make_batch(db, org, trainer.id)
    await grant(db, trainer.id, "trainer", "batch", batch)
    tr = browser.fork()
    await staff_login(tr, trainer)
    tag = uuid7().hex[:6]
    r = await tr.post(
        "/studio/courses",
        {"title": "Own", "slug": f"own-{tag}", "visibility": "private"},
    )
    assert r.status_code == 201, r.text
    own = r.json()["id"]

    from sqlalchemy import text

    from app.core.db import system_context

    ids = {}
    async with system_context(db, "test"):
        for name, owner in (("peer", org), ("platform", None)):
            cid = uuid7()
            await db.execute(
                text(
                    "INSERT INTO courses (id, slug, title, organization_id, visibility, status, created_by) "
                    "VALUES (:i, :s, :t, :o, :v, 'draft', :u)"
                ),
                {
                    "i": cid,
                    "s": f"{name}-{tag}",
                    "t": name,
                    "o": owner,
                    "v": "private",
                    "u": trainer.id,
                },
            )
            ids[name] = str(cid)
        await db.flush()

    r = await tr.get("/studio/courses", params={"limit": 100})
    assert r.status_code == 200, r.text
    listed = {c["id"] for c in r.json()["data"]}
    assert own in listed and ids["peer"] in listed
    assert ids["platform"] not in listed
