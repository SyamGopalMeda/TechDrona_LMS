"""Access checker per resource type, BR-ENT precedence/expiry/grace, staff bypass,
restricted principals, role denials, the single-company B2B removal (entitlements_0003),
manual grants and the security false-positive extension."""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import update

from app.core.access import check_access, require_access
from app.core.db import system_context, tenant_context
from app.core.errors import ProblemError
from app.core.ids import uuid7
from app.core.time import utcnow
from app.modules.entitlements import service as ent
from app.modules.entitlements.models import Entitlement, EntitlementEvent
from tests.commerce.factory import (
    make_buyer,
    make_product,
    principal,
    rows,
)
from tests.identity.factory import company_org

SYS = ent.Actor.system("test")


async def _grant(db, uid, cat, source="admin_grant", *, days=30, start_days_ago=1, **kw):
    await system_context(db, "test")
    now = utcnow()
    e, _ = await ent.grant(
        db,
        SYS,
        user_id=uid,
        source_type=source,
        product_id=cat.product.id,
        starts_at=now - timedelta(days=start_days_ago),
        ends_at=now + timedelta(days=days) if days is not None else None,
        granted_by=kw.pop("granted_by", uid),
        **kw,
    )
    return e


async def test_access_checker_maps_each_resource_type(api, db) -> None:
    uid = await make_buyer(db)
    course, test, path, topic, lesson, problem = (uuid7() for _ in range(6))
    cat = await make_product(
        db,
        kind="bundle",
        items=[
            {"item_type": "course", "course_id": course},
            {"item_type": "test", "test_id": test},
            {"item_type": "company_path", "company_path_id": path},
            {"item_type": "topic_practice", "topic_id": topic},
        ],
    )
    await _grant(db, uid, cat)

    async def lesson_parent(s, i):
        return [("course", course)] if i == lesson else []

    async def problem_parent(s, i):
        return [("company_path", path)] if i == problem else []

    ent.register_resource_parent_resolver("lesson", lesson_parent)
    ent.register_resource_parent_resolver("coding_problem", problem_parent)
    p = principal(uid)
    await tenant_context(db, p)
    for kind, rid in [
        ("course", course),
        ("lesson", lesson),
        ("resource", None),
        ("test", test),
        ("question_set", topic),
        ("company_path", path),
        ("coding_problem", problem),
        ("product", cat.product.id),
    ]:
        if rid is None:
            continue
        d = await check_access(db, p, kind, rid)
        assert d.allowed and d.reason == "entitlement", (kind, d)
    for kind in (
        "course",
        "lesson",
        "resource",
        "test",
        "question_set",
        "coding_problem",
        "company_path",
        "product",
    ):
        d = await check_access(db, p, kind, uuid7())
        assert not d.allowed and d.reason == "no_entitlement", kind
    assert (await check_access(db, p, "course", uuid7(), is_free=True)).reason == "free"
    try:
        await require_access(db, p, "test", uuid7())
        raise AssertionError("expected entitlement_required")
    except ProblemError as e:
        assert e.code == "entitlement_required"
    # feature products (all-access) cover any course and its lessons
    other = await make_buyer(db)
    allx = await make_product(
        db, kind="subscription_plan", items=[{"item_type": "feature", "feature_key": "all_courses"}]
    )
    await _grant(db, other, allx)
    po = principal(other)
    await tenant_context(db, po)
    assert (await check_access(db, po, "lesson", lesson)).allowed
    assert not (await check_access(db, po, "test", test)).allowed
    # the HTTP check endpoint + upsell for an uncovered buyer
    a = api.as_(principal(await make_buyer(db)))
    r = await a.post("/entitlements/check", {"resource": {"kind": "course", "id": str(course)}})
    body = r.json()
    assert body["allowed"] is False and body["reason_code"] == "NO_ENTITLEMENT"
    assert body["upsell"]["purchase_options"][0]["sku"] == cat.product.sku
    r = await a.post(
        "/entitlements/check-batch",
        {
            "resources": [
                {"kind": "course", "id": str(course)},
                {"kind": "course", "id": str(course), "is_free": True},
            ]
        },
    )
    assert [x["allowed"] for x in r.json()["results"]] == [False, True]


async def test_precedence_expiry_grace_and_jobs(api, db) -> None:
    uid = await make_buyer(db)
    course = uuid7()
    cat = await make_product(db, items=[{"item_type": "course", "course_id": course}])
    trial = await _grant(db, uid, cat, "trial", days=60)
    admin = await _grant(db, uid, cat, "admin_grant", days=90)
    p = principal(uid)
    await tenant_context(db, p)
    ev = await ent.evaluate(db, p, "course", course)
    assert ev.winner.id == admin.id  # ties among admin/trial go to the latest end
    assert "institution_contract" not in ent.PRECEDENCE
    # expiry: past ends_at -> expired; grace window keeps access (IN_GRACE)
    await system_context(db, "test")
    now = utcnow()
    for e in (trial, admin):
        await db.execute(
            update(Entitlement)
            .where(Entitlement.id == e.id)
            .values(starts_at=now - timedelta(days=40), ends_at=now - timedelta(days=1))
        )
    await tenant_context(db, p)
    d = (await ent.evaluate(db, p, "course", course)).decision
    assert not d.allowed and d.reason == "expired"
    await system_context(db, "test")
    await db.execute(
        update(Entitlement).where(Entitlement.id == admin.id).values(grace_ends_at=now + timedelta(days=2))
    )
    await tenant_context(db, p)
    d = (await ent.evaluate(db, p, "course", course)).decision
    assert d.allowed and d.reason == "in_grace"
    await system_context(db, "test")
    out = await ent.expire_due(db)
    assert out["entered_grace"] >= 1 and out["expired"] >= 1
    st = {e.id: e.status for e in await rows(db, Entitlement, Entitlement.user_id == uid)}
    assert st[admin.id] == "grace" and st[trial.id] == "expired"
    out = await ent.expire_due(db, now + timedelta(days=3))
    assert (await rows(db, Entitlement, Entitlement.id == admin.id))[0].status == "expired"


async def test_staff_bypass_and_restriction(api, db) -> None:
    from tests.identity.factory import grant

    staff = await make_buyer(db)
    await grant(db, staff, "content_manager")
    p = principal(staff, roles=("content_manager",), platform=True)
    await tenant_context(db, p)
    d = await check_access(db, p, "course", uuid7())
    assert d.allowed and d.reason == "staff"
    # restricted (L3) student: denied even with an entitlement; free content stays available
    uid = await make_buyer(db)
    cat = await make_product(db)
    await _grant(db, uid, cat)
    pr = principal(uid, restriction_level=3)
    await tenant_context(db, pr)
    assert (await check_access(db, pr, "product", cat.product.id)).reason == "restricted"
    assert (await check_access(db, pr, "product", cat.product.id, is_free=True)).allowed
    pl = principal(uid, restrictions=frozenset({"premium_locked"}))
    assert (await check_access(db, pl, "product", cat.product.id)).reason == "restricted"


async def test_role_denials_and_no_org_scoped_reads(api, db, fake_gw) -> None:
    """Students have no finance access; ``GET /users/{id}/entitlements`` is platform staff only
    (the coordinator ``org_id`` branch is gone)."""
    student_id = await make_buyer(db)
    student = api.as_(principal(student_id, org_ids=(company_org(),)), "entitlement.read")
    for path in ("/finance/orders", "/finance/invoices", "/finance/reconciliation"):
        assert (await student.get(path)).status_code == 403, path
    other = await make_buyer(db)
    r = await student.get(f"/users/{other}/entitlements", params={"org_id": str(company_org())})
    assert r.status_code == 403 and r.json()["code"] == "permission_denied"


async def test_institution_entitlements_are_history_only_and_rows_are_own_only(db) -> None:
    """entitlements_0003: no live ``institution_contract`` entitlement can exist, and RLS family O
    hides a company member's entitlements from every other member."""
    from sqlalchemy import select, text
    from sqlalchemy.exc import IntegrityError

    a, b = await make_buyer(db), await make_buyer(db)
    cat = await make_product(db)
    await system_context(db, "test")
    org = company_org()
    with pytest.raises(IntegrityError):
        async with db.begin_nested():
            await db.execute(
                text(
                    "INSERT INTO entitlements (id, user_id, organization_id, product_id, source_type, status,"
                    " starts_at, ends_at) VALUES (:i, :u, :o, :p, 'institution_contract', 'active', now(),"
                    " now() + interval '30 days')"
                ),
                {"i": uuid7(), "u": a, "o": org, "p": cat.product.id},
            )
    await system_context(db, "test")
    cols = (
        await db.execute(
            text(
                "SELECT column_name FROM information_schema.columns WHERE table_name = 'entitlements'"
                " AND column_name = 'institution_contract_id'"
            )
        )
    ).all()
    assert cols == []
    assert (await db.execute(text("SELECT to_regclass('public.seat_waitlist')"))).scalar() is None
    e = await _grant(db, a, cat, organization_id=org)
    pb = principal(b, org_ids=(org,))
    await tenant_context(db, pb)
    assert (await db.execute(select(Entitlement.id).where(Entitlement.id == e.id))).first() is None
    assert (
        await db.execute(select(EntitlementEvent.id).where(EntitlementEvent.entitlement_id == e.id))
    ).first() is None
    pa = principal(a, org_ids=(org,))
    await tenant_context(db, pa)
    assert (await db.execute(select(Entitlement.id).where(Entitlement.id == e.id))).first() is not None


async def test_manual_grant_rules_and_history(api, db) -> None:
    target = await make_buyer(db)
    cat = await make_product(db)
    admin_id = await make_buyer(db)
    perms = ("entitlement.grant_manual", "entitlement.revoke", "entitlement.read")
    a = api.as_(principal(admin_id, roles=("super_admin",), platform=True), *perms)
    body = {
        "user_ids": [str(target)],
        "target": {"product_id": str(cat.product.id)},
        "source_type": "admin_grant",
        "ends_at": (utcnow() + timedelta(days=30)).isoformat(),
        "reason": "Compensation for judge outage INC-1",
    }
    r = await a.post("/entitlements/grants", {**body, "reason": "short"}, idem=True)
    assert r.status_code == 400
    r = await a.post(
        "/entitlements/grants", {**body, "ends_at": (utcnow() + timedelta(days=400)).isoformat()}, idem=True
    )
    assert r.status_code == 400
    r = await a.post(
        "/entitlements/grants", {**body, "ends_at": (utcnow() + timedelta(days=120)).isoformat()}, idem=True
    )
    assert r.status_code == 202 and r.json()["status"] == "approval_pending"
    r = await a.post("/entitlements/grants", body, idem=True)
    assert r.status_code == 201 and r.json()["granted"] == 1, r.text
    eid = r.json()["entitlement_ids"][0]
    nostep = api.as_(
        principal(await make_buyer(db), roles=("super_admin",), platform=True, stepped_up=False), *perms
    )
    assert (await nostep.post("/entitlements/grants", body, idem=True)).status_code == 401
    r = await a.post(
        f"/entitlements/{eid}/revoke", {"reason_code": "fraud", "note": "chargeback ring"}, idem=True
    )
    assert r.status_code == 200 and r.json()["status"] == "revoked"
    t = api.as_(principal(target))
    mine = (await t.get("/me/entitlements")).json()["data"]
    assert mine[0]["status"] == "revoked" and mine[0]["title"] == cat.product.name
    hist = (await t.get(f"/entitlements/{eid}/events")).json()["data"]
    assert [h["event_type"] for h in hist] == ["granted", "revoked"]
    assert (
        await api.as_(principal(await make_buyer(db))).get(f"/entitlements/{eid}/events")
    ).status_code == 404
    assert (await a.get(f"/users/{target}/entitlements")).json()["data"][0]["entitlement_id"] == eid


async def test_false_positive_extension_for_security(api, db) -> None:
    uid = await make_buyer(db)
    cat = await make_product(db)
    purchase = await _grant(db, uid, cat, "trial", days=10)
    old = purchase.ends_at
    out = await ent.extend_entitlements_for_restriction(
        db, uid, 3, "overturned SEC-2611-ABC", case_ref="SEC-2611-ABC"
    )
    assert out["extended"] == 1 and out["uncredited_days"] == {}
    p = (await rows(db, Entitlement, Entitlement.id == purchase.id))[0]
    assert p.ends_at - old == timedelta(days=3)
    evs = await rows(db, EntitlementEvent, EntitlementEvent.entitlement_id == purchase.id)
    assert evs[-1].event_type == "fp_extension" and evs[-1].actor_type == "system"
    assert evs[-1].delta["days"] == 3
