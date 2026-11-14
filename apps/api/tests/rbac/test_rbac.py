"""RBAC: seeded catalogue == role matrix (single-company roles), permission checker scope
resolution (parametrised from the seed), grants API with step-up, dual control between two
different admins, re-login on grant change."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.core.auth import PLATFORM_SCOPE, ScopeRef
from app.core.db import system_context
from app.core.ids import uuid7
from app.core.principal import Principal, RoleGrant
from app.modules.rbac.catalogue import (
    GRANTING_CELLS,
    PERMISSIONS,
    REMOVED_PERMISSIONS,
    REMOVED_ROLES,
    ROLE_ORDER,
    ROLES,
    admin_roles,
    cell_scope,
    role_permission_pairs,
    successor_role,
)
from app.modules.rbac.models import ApprovalRequest, Permission, Role, RolePermission
from app.modules.rbac.service import RbacPermissionChecker
from tests.identity.factory import company_org, grant, make_batch, make_user, staff_login, step_up


async def test_seed_matches_role_matrix(db) -> None:
    await system_context(db, "t")
    roles = (await db.execute(select(Role))).scalars().all()
    assert {r.role_key for r in roles} == set(ROLE_ORDER) and len(roles) == 5
    assert not {r.role_key for r in roles} & set(REMOVED_ROLES)
    tiers = {r.role_key: (r.session_tier, r.mfa_required) for r in roles}
    assert tiers["student"] == ("student", False)
    assert tiers["evaluator"] == ("staff", True) and tiers["trainer"] == ("staff", True)
    assert {k for k, (t, _) in tiers.items() if t == "privileged"} == {"super_admin"}
    names = {r.role_key: r.name for r in roles}
    assert names["super_admin"] == "Admin" and names["evaluator"] == "Evaluator"
    scopes = {r.role_key: set(r.allowed_scope_types) for r in roles}
    assert all("organization" not in s for s in scopes.values())
    assert scopes["evaluator"] == {"batch", "platform"} and scopes["trainer"] == {"batch", "course"}
    perms = set((await db.execute(select(Permission.permission_key))).scalars())
    assert perms == set(PERMISSIONS) and not perms & REMOVED_PERMISSIONS
    pairs = set(
        (
            await db.execute(
                select(Role.role_key, Permission.permission_key)
                .join(RolePermission, RolePermission.role_id == Role.id)
                .join(Permission, Permission.id == RolePermission.permission_id)
            )
        ).all()
    )
    assert pairs == set(role_permission_pairs())


def test_catalogue_helpers_for_other_modules() -> None:
    assert admin_roles() == frozenset({"super_admin"})
    for old in REMOVED_ROLES:
        assert successor_role(old) == "super_admin"
    assert successor_role("trainer") == "trainer" and successor_role("nope") is None


async def _principal_for(db, role: str, cell: str) -> tuple[Principal, ScopeRef, ScopeRef]:
    """Principal holding ``role`` at the scope implied by ``cell``; returns (principal,
    matching target, a target outside the grant)."""
    scope = cell_scope(role, cell)
    if scope == "platform":
        return (
            Principal(uuid7(), uuid7(), grants=(RoleGrant(role, "platform"),)),
            PLATFORM_SCOPE,
            PLATFORM_SCOPE,
        )
    if scope == "batch":
        org = company_org()
        u = await make_user(db)
        b = await make_batch(db, org, u.id)
        b2 = await make_batch(db, org, u.id)
        return (
            Principal(uuid7(), uuid7(), org_ids=(org,), grants=(RoleGrant(role, "batch", b),)),
            ScopeRef("batch", b),
            ScopeRef("batch", b2),
        )
    course = uuid7()
    return (
        Principal(uuid7(), uuid7(), grants=(RoleGrant(role, "course", course),)),
        ScopeRef("course", course),
        ScopeRef("course", uuid7()),
    )


@pytest.mark.parametrize("role", ROLE_ORDER)
async def test_permission_matrix_per_role(db, role) -> None:
    """Every matrix cell for this role: granting cells allow at their scope; '-' and 'S'
    cells deny (deny by default)."""
    checker = RbacPermissionChecker()
    cache: dict[str, tuple[Principal, ScopeRef, ScopeRef]] = {}
    for key, p in PERMISSIONS.items():
        cell = p.cells[role]
        scope_kind = cell_scope(role, cell) if cell in GRANTING_CELLS else ROLES[role].default_scope
        if scope_kind not in cache:
            cache[scope_kind] = await _principal_for(db, role, cell if cell in GRANTING_CELLS else "-")
        principal, target, _ = cache[scope_kind]
        allowed = await checker.has_permission(principal, key, target, None)  # type: ignore[arg-type]
        assert allowed == (cell in GRANTING_CELLS), f"{role} {key} cell={cell}"


@pytest.mark.parametrize(
    ("role", "perm", "expected"),
    [
        # Evaluator (REMOVAL-PLAN §4.2, D3): grades and releases, never authors
        ("evaluator", "assignment.grade", True),
        ("evaluator", "test.results.release", True),
        ("evaluator", "integrity.flag.decide", True),
        ("evaluator", "question.answer_key.read", True),
        ("evaluator", "assignment.manage", False),
        ("evaluator", "test.create", False),
        ("evaluator", "test.assign", False),
        ("evaluator", "question.create", False),
        ("evaluator", "course.edit", False),
        ("evaluator", "path.manage", False),
        ("evaluator", "engage.activity.manage", False),
        ("evaluator", "media.upload", False),
        ("evaluator", "grade.override_released", False),
        ("evaluator", "attempt.invalidate", False),
        ("evaluator", "batch.member.manage", False),
        ("evaluator", "enrolment.manage", False),
        # Admin carries the folded roles' duties (D2) and the coordinator's (D3)
        ("super_admin", "security.case.decide", True),
        ("super_admin", "refund.decide", True),
        ("super_admin", "session.revoke", True),
        ("super_admin", "mentor.slot.manage", True),
        ("super_admin", "test.assign", True),
        ("super_admin", "test.results.release", True),
        ("super_admin", "test.override.grant", True),
        ("super_admin", "path.allocate", True),
        ("super_admin", "batch.create", True),
        ("super_admin", "rbac.grant.manage", True),
        ("trainer", "test.assign", True),
        ("trainer", "batch.create", False),
        ("content_manager", "test.results.release", False),
        ("student", "user.read", False),
    ],
)
async def test_permission_spot_checks(db, role, perm, expected) -> None:
    cell = PERMISSIONS[perm].cells[role]
    principal, target, _ = await _principal_for(db, role, cell if cell in GRANTING_CELLS else "P")
    assert await RbacPermissionChecker().has_permission(principal, perm, target, None) is expected  # type: ignore[arg-type]


async def test_scope_chain_batch_grants_and_cross_tenant_404(db) -> None:
    from app.core.errors import ProblemError

    org = company_org()
    u = await make_user(db)
    batch = await make_batch(db, org, u.id)
    sibling = await make_batch(db, org, u.id)
    checker = RbacPermissionChecker()
    trainer = Principal(uuid7(), uuid7(), org_ids=(org,), grants=(RoleGrant("trainer", "batch", batch),))
    evaluator = Principal(uuid7(), uuid7(), org_ids=(org,), grants=(RoleGrant("evaluator", "batch", batch),))
    # a batch grant covers that batch only — never a sibling batch (cross-batch)
    assert await checker.has_permission(trainer, "test.assign", ScopeRef("batch", batch), None)  # type: ignore[arg-type]
    assert not await checker.has_permission(trainer, "test.assign", ScopeRef("batch", sibling), None)  # type: ignore[arg-type]
    assert await checker.has_permission(evaluator, "assignment.grade", ScopeRef("batch", batch), None)  # type: ignore[arg-type]
    assert not await checker.has_permission(evaluator, "assignment.grade", ScopeRef("batch", sibling), None)  # type: ignore[arg-type]
    # and never reaches the (internal) organization level
    assert not await checker.has_permission(trainer, "test.assign", ScopeRef("organization", org), None)  # type: ignore[arg-type]
    # single company: nonexistent organizations/batches are 404, not 403
    for target in (
        ScopeRef("organization", uuid7()),
        ScopeRef("batch", uuid7()),
    ):
        with pytest.raises(ProblemError) as ei:
            await checker.has_permission(trainer, "org.member.read", target, None)  # type: ignore[arg-type]
        assert ei.value.code == "not_found"
    # a principal outside the company (public learner holding a stray batch grant) gets 404 on
    # company batches: the batch is invisible to them, not merely forbidden
    outsider = Principal(uuid7(), uuid7(), org_ids=(), grants=(RoleGrant("trainer", "batch", sibling),))
    with pytest.raises(ProblemError) as ei:
        await checker.has_permission(outsider, "org.member.read", ScopeRef("batch", batch), None)  # type: ignore[arg-type]
    assert ei.value.code == "not_found"
    # Admin (platform) reaches every batch
    sa = Principal(uuid7(), uuid7(), grants=(RoleGrant("super_admin", "platform"),), is_platform=True)
    assert await checker.has_permission(sa, "batch.member.manage", ScopeRef("batch", sibling), None)  # type: ignore[arg-type]


async def test_admin_grants_evaluator_at_batch(browser, db) -> None:
    org = company_org()
    admin = await make_user(db, with_totp=True)
    await grant(db, admin.id, "super_admin")
    grader = await make_user(db)
    batch = await make_batch(db, org, admin.id)
    await staff_login(browser, admin)
    body = {
        "user_id": str(grader.id),
        "role_key": "evaluator",
        "scope_type": "batch",
        "scope_id": str(batch),
        "reason": "CSE 2027 grading",
    }
    r = await browser.post("/rbac/grants", body)
    assert r.status_code == 400 and r.json()["code"] == "idempotency_key_required"
    r = await browser.post("/rbac/grants", body, headers={"Idempotency-Key": "grant-eval-0001"})
    assert r.status_code == 201, r.text
    assert r.json()["session_effect"] == "grantee_sessions_rotated"
    replay = await browser.post("/rbac/grants", body, headers={"Idempotency-Key": "grant-eval-0001"})
    assert replay.status_code == 201 and replay.headers["idempotency-replayed"] == "true"
    listed = (await browser.get("/rbac/grants", params={"user_id": str(grader.id)})).json()["data"]
    assert [(g["role_key"], g["scope_type"], g["organization_id"]) for g in listed] == [
        ("evaluator", "batch", str(org))
    ]
    # organization is no longer a grant scope (schema) — nor for roles that used to allow it
    r = await browser.post(
        "/rbac/grants",
        {**body, "role_key": "trainer", "scope_type": "organization", "scope_id": str(org)},
        headers={"Idempotency-Key": "grant-eval-0002"},
    )
    assert r.status_code in (400, 422) and r.json()["code"] == "validation_failed", r.text
    # trainers cannot be granted at platform scope; evaluators can (every cohort)
    r = await browser.post(
        "/rbac/grants",
        {**body, "role_key": "trainer", "scope_type": "platform", "scope_id": None},
        headers={"Idempotency-Key": "grant-eval-0003"},
    )
    assert r.status_code == 422 and r.json()["errors"][0]["code"] == "scope_not_allowed"
    # removed roles are unknown
    for i, old in enumerate(sorted(REMOVED_ROLES)):
        r = await browser.post(
            "/rbac/grants",
            {**body, "role_key": old, "scope_type": "platform", "scope_id": None},
            headers={"Idempotency-Key": f"grant-old-000{i}"},
        )
        assert r.status_code == 422 and r.json()["errors"][0]["code"] == "unknown_role", old


async def test_only_admin_grants_roles(browser, db) -> None:
    """The coordinator's "org staff" grant path is gone: a trainer cannot grant anything,
    not even an evaluator on their own batch."""
    org = company_org()
    trainer = await make_user(db, with_totp=True)
    batch = await make_batch(db, org, trainer.id)
    await grant(db, trainer.id, "trainer", "batch", batch)
    grader = await make_user(db)
    await staff_login(browser, trainer)
    r = await browser.post(
        "/rbac/grants",
        {
            "user_id": str(grader.id),
            "role_key": "evaluator",
            "scope_type": "batch",
            "scope_id": str(batch),
            "reason": "helper",
        },
        headers={"Idempotency-Key": "trainer-grant-0001"},
    )
    assert r.status_code == 403 and r.json()["code"] == "permission_denied"
    assert (await browser.get("/rbac/grants")).status_code == 403
    assert (await browser.get("/rbac/roles")).status_code == 403


async def test_admin_grant_needs_a_second_admin(browser, db) -> None:
    sa1 = await make_user(db, with_totp=True)
    sa2 = await make_user(db, with_totp=True)
    await grant(db, sa1.id, "super_admin")
    await grant(db, sa2.id, "super_admin")
    target = await make_user(db)
    await staff_login(browser, sa1)
    body = {
        "user_id": str(target.id),
        "role_key": "super_admin",
        "scope_type": "platform",
        "reason": "new hire",
    }
    r = await browser.post("/rbac/grants", body, headers={"Idempotency-Key": "dual-grant-0001"})
    assert r.status_code == 202 and r.json()["status"] == "approval_pending", r.text
    assert r.json()["required_approver_role"] == "super_admin"
    apr = r.json()["approval_request_id"]
    # maker != checker: the requesting admin cannot approve their own request
    r = await browser.post(f"/rbac/approval-requests/{apr}/approve", {})
    assert r.status_code == 403 and r.json()["code"] == "sod_violation"
    b2 = browser.fork(ua="Mozilla/5.0 (X11; Linux x86_64; rv:131.0) Gecko/20100101 Firefox/131.0")
    await staff_login(b2, sa2)
    r = await b2.post(f"/rbac/approval-requests/{apr}/approve", {"note": "ok"})
    assert r.status_code == 200 and r.json()["status"] == "executed", r.text
    await system_context(db, "t")
    req = await db.get(ApprovalRequest, uuid.UUID(apr))
    assert req is not None and req.decided_by == sa2.id and req.status == "executed"


async def test_grant_requires_fresh_step_up(browser, db, monkeypatch) -> None:
    from datetime import timedelta

    from app.modules.identity import clock

    sa = await make_user(db, with_totp=True)
    await grant(db, sa.id, "super_admin")
    target = await make_user(db)
    await staff_login(browser, sa)
    base = clock.utcnow()
    monkeypatch.setattr(clock, "now", lambda: base + timedelta(minutes=6))
    await browser.post("/auth/step-up/options", {})  # an engaged request keeps the 15-min idle alive
    body = {
        "user_id": str(target.id),
        "role_key": "content_manager",
        "scope_type": "platform",
        "reason": "studio",
    }
    r = await browser.post("/rbac/grants", body, headers={"Idempotency-Key": "stepup-grant-1"})
    assert r.status_code == 401 and r.json()["step_up"]["max_age_seconds"] == 300
    await step_up(browser, sa)
    r = await browser.post("/rbac/grants", body, headers={"Idempotency-Key": "stepup-grant-1"})
    assert r.status_code == 201, r.text


async def test_grant_and_revoke_force_grantee_relogin(browser, db) -> None:
    sa = await make_user(db, with_totp=True)
    await grant(db, sa.id, "super_admin")
    target = await make_user(db, with_totp=True)
    tb = browser.fork(ua="Mozilla/5.0 (X11; Linux x86_64; rv:131.0) Gecko/20100101 Firefox/131.0")
    await staff_login(tb, target)
    assert (await tb.get("/me")).json()["session"]["tier"] == "student"
    await staff_login(browser, sa)
    r = await browser.post(
        "/rbac/grants",
        {"user_id": str(target.id), "role_key": "evaluator", "scope_type": "platform", "reason": "graders"},
        headers={"Idempotency-Key": "relogin-grant-1"},
    )
    gid = r.json()["grant_id"]
    r = await tb.get("/me")
    assert r.status_code == 401 and r.json()["code"] == "session_revoked"
    await staff_login(tb, target)
    assert (await tb.get("/me")).json()["session"]["tier"] == "staff"
    assert (await tb.get("/me/grants")).json()["portals"] == ["/evaluator"]
    r = await browser.post(f"/rbac/grants/{gid}/revoke", {"reason": "left team"})
    assert r.status_code == 200 and r.json()["revoked"] is True
    assert (await tb.get("/me")).status_code == 401


async def test_rbac_reads_permission_checks(browser, db) -> None:
    student = await make_user(db)
    await browser.login(student.email)
    assert (await browser.get("/rbac/permissions")).status_code == 403
    assert (await browser.get("/rbac/roles")).status_code == 403
    assert (await browser.get("/me/grants")).json() == {"data": [], "portals": ["/app"]}


async def test_evaluator_portal_and_landing(browser, db) -> None:
    """WS6: an evaluator lands on (and is offered) the /evaluator portal; a user holding both
    trainer and evaluator grants lands on /trainer (more privileged) but is offered both."""
    org = company_org()
    owner = await make_user(db)
    batch = await make_batch(db, org, owner.id)
    ev = await make_user(db, with_totp=True)
    await grant(db, ev.id, "evaluator", "batch", batch)
    r = await staff_login(browser, ev)
    assert r.json()["redirect"] == "/evaluator", r.text
    assert (await browser.get("/me/grants")).json()["portals"] == ["/evaluator"]

    both = await make_user(db, with_totp=True)
    await grant(db, both.id, "evaluator", "batch", batch)
    await grant(db, both.id, "trainer", "batch", batch)
    b2 = browser.fork(ua="Mozilla/5.0 (X11; Linux x86_64; rv:131.0) Gecko/20100101 Firefox/131.0")
    r = await staff_login(b2, both)
    assert r.json()["redirect"] == "/trainer", r.text
    assert (await b2.get("/me/grants")).json()["portals"] == ["/evaluator", "/trainer"]


async def test_sole_admin_rule(db) -> None:
    """Owner decision 2026-11-11: with exactly one active Admin, that Admin may decide their own
    dual-control requests; a second active Admin restores the normal SoD-05 rule."""
    from app.modules.rbac.service import is_sole_admin

    await system_context(db, "test")
    existing = await is_sole_admin(db, uuid7())  # never true for a stranger
    assert existing is False
    a = await make_user(db)
    await grant(db, a.id, "super_admin")
    others = (
        await db.execute(
            select(Role.role_key).where(Role.role_key == "super_admin")  # sanity: role exists
        )
    ).scalar_one()
    assert others == "super_admin"
    sole_a = await is_sole_admin(db, a.id)
    b = await make_user(db)
    await grant(db, b.id, "super_admin")
    assert await is_sole_admin(db, a.id) is False and await is_sole_admin(db, b.id) is False
    # A is sole only if no other active Admin existed in this database before the test
    if sole_a is False:
        pytest.skip("another active Admin exists in this test database")


async def test_self_decision_needs_the_sole_admin_flag(db) -> None:
    """rbac_0006: ck_apr_distinct refuses decided_by = requested_by unless the row is flagged
    sole_admin_decision (set only after rbac.service.is_sole_admin)."""
    from sqlalchemy import text
    from sqlalchemy.exc import IntegrityError

    await system_context(db, "test")
    u = await make_user(db)
    sql = (
        "INSERT INTO approval_requests (id, action_type, target_type, payload, payload_hash, requested_by, "
        "request_reason, required_approver_role, status, decided_by, decided_at, expires_at, sole_admin_decision) "
        "VALUES (:id, 'policy.change', 'policy', '{}'::jsonb, decode(repeat('00', 32), 'hex'), :u, 'test', "
        "'super_admin', 'approved', :u, now(), now() + interval '1 day', :sole)"
    )
    await db.execute(text(sql), {"id": uuid7(), "u": u.id, "sole": True})
    with pytest.raises(IntegrityError):
        async with db.begin_nested():
            await db.execute(text(sql), {"id": uuid7(), "u": u.id, "sole": False})
