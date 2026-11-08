"""orgs_0004: RLS family ``U`` (user-owned rows that carry an ``organization_id``). With one
company organization every batch student is an org member, so the organization branch of ``U``
must be for company STAFF only: a student reads only their own rows (never a batch-mate's),
staff by membership or by a live grant read org rows, and a revoked grant stops counting."""

from __future__ import annotations

import uuid

from sqlalchemy import text, update
from sqlalchemy.exc import DBAPIError

from app.core.db import system_context, tenant_context
from app.core.ids import uuid7
from app.core.principal import Principal, RoleGrant
from tests.identity.factory import add_member, company_org, grant, make_batch, make_user


async def _recommendation(db, user_id: uuid.UUID, org: uuid.UUID | None) -> uuid.UUID:
    await system_context(db, "t")
    rid = uuid7()
    await db.execute(
        text(
            "INSERT INTO recommendations (id, user_id, organization_id, rule_key, reason, target_type, "
            "target_id, expires_at) VALUES (:i, :u, :o, 'weak_topic', 'r', 'topic', :t, now() + interval '1 day')"
        ),
        {"i": rid, "u": user_id, "o": org, "t": uuid7()},
    )
    return rid


async def _sees(db, principal: Principal, rid: uuid.UUID) -> bool:
    await tenant_context(db, principal)
    assert (await db.execute(text("select current_user"))).scalar() == "td_app"
    n = (await db.execute(text("select count(*) from recommendations where id = :i"), {"i": rid})).scalar()
    await system_context(db, "t")
    return bool(n)


async def test_every_u_policy_requires_staff_for_the_org_branch(db) -> None:
    await system_context(db, "t")
    rows = (
        await db.execute(text("select tablename, qual, with_check from pg_policies where policyname = 'p_u'"))
    ).all()
    assert rows, "expected family-U policies"
    for table, qual, check in rows:
        assert "caller_is_org_staff()" in qual, table
        assert "caller_is_org_staff()" in check, table


async def test_student_cannot_read_batch_mates_org_rows(db) -> None:
    org = company_org()
    owner = await make_user(db)
    batch = await make_batch(db, org, owner.id)
    s1, s2 = await make_user(db), await make_user(db)
    await add_member(db, org, s1.id, "student", batch)
    await add_member(db, org, s2.id, "student", batch)
    member_staff = await make_user(db)
    await add_member(db, org, member_staff.id, "staff")
    trainer = await make_user(db)
    await grant(db, trainer.id, "trainer", "batch", batch)

    own = await _recommendation(db, s1.id, org)
    mate = await _recommendation(db, s2.id, org)

    p1 = Principal(s1.id, uuid7(), org_ids=(org,))
    assert await _sees(db, p1, own) is True
    assert await _sees(db, p1, mate) is False  # same org, same batch: still invisible

    pt = Principal(trainer.id, uuid7(), org_ids=(org,), grants=(RoleGrant("trainer", "batch", batch),))
    assert await _sees(db, pt, mate) is True  # staff by live grant
    pm = Principal(member_staff.id, uuid7(), org_ids=(org,))
    assert await _sees(db, pm, mate) is True  # staff by membership

    # WITH CHECK: a student cannot write a row for a batch-mate either.
    await tenant_context(db, p1)
    try:
        async with db.begin_nested():
            await db.execute(
                text(
                    "INSERT INTO recommendations (id, user_id, organization_id, rule_key, reason, "
                    "target_type, target_id, expires_at) VALUES (:i, :u, :o, 'weak_topic', 'r', 'topic', "
                    ":t, now() + interval '1 day')"
                ),
                {"i": uuid7(), "u": s2.id, "o": org, "t": uuid7()},
            )
        raise AssertionError("insert for another student must be refused by RLS")
    except DBAPIError as e:
        assert "row-level security" in str(e), e
    await system_context(db, "t")


async def test_revoked_grant_loses_org_branch(db) -> None:
    from app.modules.rbac.models import RoleGrant as RG

    org = company_org()
    owner = await make_user(db)
    batch = await make_batch(db, org, owner.id)
    s = await make_user(db)
    await add_member(db, org, s.id, "student", batch)
    ex = await make_user(db)
    gid = await grant(db, ex.id, "trainer", "batch", batch)
    rid = await _recommendation(db, s.id, org)
    view = Principal(ex.id, uuid7(), org_ids=(org,))
    assert await _sees(db, view, rid) is True
    await db.execute(update(RG).where(RG.id == gid).values(revoked_at=text("now()")))
    assert await _sees(db, view, rid) is False
