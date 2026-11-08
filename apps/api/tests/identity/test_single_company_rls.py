"""REMOVAL-PLAN §2.4 (identity_0005): with one company organization every batch student shares
the org with every other batch student. At the database level a student must not read another
student's ``users`` / ``user_profiles`` row; students still see staff of their organization, and
staff (by membership or by a live grant in the org) see the members."""

from __future__ import annotations

from sqlalchemy import text

from app.core.db import system_context, tenant_context
from app.core.ids import uuid7
from app.core.principal import Principal, RoleGrant
from tests.identity.factory import add_member, company_org, grant, make_batch, make_user


async def _visible(db, principal: Principal, target) -> tuple[int, int]:
    await tenant_context(db, principal)
    assert (await db.execute(text("select current_user"))).scalar() == "td_app"
    users = (await db.execute(text("select count(*) from users where id = :u"), {"u": target})).scalar()
    profiles = (
        await db.execute(text("select count(*) from user_profiles where user_id = :u"), {"u": target})
    ).scalar()
    await system_context(db, "t")
    return int(users or 0), int(profiles or 0)


async def test_students_cannot_read_other_students(db) -> None:
    org = company_org()
    owner = await make_user(db)
    batch = await make_batch(db, org, owner.id)
    s1, s2 = await make_user(db), await make_user(db)
    await add_member(db, org, s1.id, "student", batch)
    await add_member(db, org, s2.id, "student", batch)
    # staff by membership (no grant) and staff by grant only (no membership)
    member_staff = await make_user(db)
    await add_member(db, org, member_staff.id, "staff")
    trainer = await make_user(db)
    await grant(db, trainer.id, "trainer", "batch", batch)
    outsider = await make_user(db)  # public learner, no organization

    p1 = Principal(s1.id, uuid7(), org_ids=(org,))
    assert await _visible(db, p1, s1.id) == (1, 1)  # own row
    assert await _visible(db, p1, s2.id) == (0, 0)  # same batch, still invisible
    assert await _visible(db, p1, outsider.id) == (0, 0)
    assert await _visible(db, p1, member_staff.id) == (1, 1)  # (b) staff by membership
    assert await _visible(db, p1, trainer.id) == (1, 1)  # (b) staff by live grant

    pt = Principal(trainer.id, uuid7(), org_ids=(org,), grants=(RoleGrant("trainer", "batch", batch),))
    assert await _visible(db, pt, s1.id) == (1, 1)  # (a) caller is staff of the org
    assert await _visible(db, pt, outsider.id) == (0, 0)  # never org-less public learners

    pm = Principal(member_staff.id, uuid7(), org_ids=(org,))
    assert await _visible(db, pm, s2.id) == (1, 1)


async def test_revoked_grant_no_longer_counts_as_staff(db) -> None:
    from sqlalchemy import update

    from app.modules.rbac.models import RoleGrant as RG

    org = company_org()
    owner = await make_user(db)
    batch = await make_batch(db, org, owner.id)
    s = await make_user(db)
    await add_member(db, org, s.id, "student", batch)
    ex = await make_user(db)
    gid = await grant(db, ex.id, "trainer", "batch", batch)
    student_view = Principal(s.id, uuid7(), org_ids=(org,))
    assert await _visible(db, student_view, ex.id) == (1, 1)
    await db.execute(update(RG).where(RG.id == gid).values(revoked_at=text("now()")))
    assert await _visible(db, student_view, ex.id) == (0, 0)
    ex_view = Principal(ex.id, uuid7(), org_ids=(org,))
    assert await _visible(db, ex_view, s.id) == (0, 0)


async def test_college_data_sharing_consent_rejected_for_new_rows(db) -> None:
    from sqlalchemy.exc import DBAPIError

    u = await make_user(db)
    await system_context(db, "t")
    try:
        async with db.begin_nested():
            await db.execute(
                text(
                    "INSERT INTO consents (id, user_id, purpose, action, notice_version, channel) "
                    "VALUES (:i, :u, 'college_data_sharing', 'granted', 'v1', 'web')"
                ),
                {"i": uuid7(), "u": u.id},
            )
        raise AssertionError("college_data_sharing must be rejected")
    except DBAPIError as e:
        assert "consents_purpose_check" in str(e)
