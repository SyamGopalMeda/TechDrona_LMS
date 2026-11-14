"""Dev/demo seeds as one chain (scripts/seed-dev.ps1 order): idempotent, refused in production,
and the E2E fixture invariants (qa-report-e2e B3a-B3f) hold after a single run."""

from __future__ import annotations

import importlib
import uuid
from typing import Any, cast

import pytest
from sqlalchemy import func, select

from app.core.db import system_context
from app.core.principal import Principal, RoleGrant, ScopeType
from app.modules.identity.models import User
from app.modules.security.models import (
    AccountRestriction,
    RiskEvaluation,
    SecurityCase,
    SecuritySignal,
    UnblockRequest,
)
from app.seeds import (
    catalog_demo,
    coding_demo,
    commerce_demo,
    company_demo,
    dev_users,
    e2e_demo,
    e2e_env,
    placement_demo,
    security_demo,
)

# Every demo seed (scripts/seed-dev.* order) plus the E2E env writer. rbac_seed is reference data
# (safe in every environment) and deliberately has no guard.
SEED_MODULES = (
    "dev_users",
    "catalog_demo",
    "placement_demo",
    "coding_demo",
    "commerce_demo",
    "security_demo",
    "e2e_demo",
    "company_demo",
    "e2e_env",
)


async def _run_all(db: Any) -> dict[str, Any]:
    out: dict[str, Any] = {"dev_users": await dev_users.seed(db)}
    out["catalog_demo"] = await catalog_demo.seed(db)
    out["placement_demo"] = await placement_demo.seed(db)
    out["coding_demo"] = await coding_demo.seed(db)
    out["commerce_demo"] = await commerce_demo.seed(db)
    out["security_demo"] = await security_demo.seed(db)
    out["e2e_demo"] = await e2e_demo.seed(db)
    out["company_demo"] = await company_demo.seed(db)
    await system_context(db, "test.seeds")
    return out


async def _user(db: Any, email: str) -> User:
    return (await db.execute(select(User).where(User.email == email))).scalar_one()


async def _active(db: Any, user_id: uuid.UUID) -> AccountRestriction:
    return (
        await db.execute(
            select(AccountRestriction).where(
                AccountRestriction.user_id == user_id, AccountRestriction.ended_at.is_(None)
            )
        )
    ).scalar_one()


@pytest.mark.parametrize("name", SEED_MODULES)
def test_every_seed_refuses_production(monkeypatch, name: str) -> None:
    from app.core.config import reset_settings_cache

    mod = importlib.import_module(f"app.seeds.{name}")
    monkeypatch.setenv("APP_ENV", "production")
    reset_settings_cache()
    try:
        with pytest.raises(mod.ProductionRefused):
            mod.guard()
    finally:
        monkeypatch.setenv("APP_ENV", "test")
        reset_settings_cache()


async def test_seed_chain_is_idempotent_and_fixtures_hold(db) -> None:
    first = await _run_all(db)
    assert set(first["security_demo"]) == {f.email for f in security_demo.FIXTURES}
    assert first["e2e_demo"] == {"consents": 1, "practice_grants": 1, "tests": 2, "approvals": 1}
    assert set(first["company_demo"].values()) == {1}
    assert first["coding_demo"] == [p["slug"] for p in coding_demo.PROBLEMS]
    second = await _run_all(db)
    assert second["dev_users"] == {}
    assert second["catalog_demo"] == [] and second["coding_demo"] == []
    assert second["placement_demo"] == {"questions_created": 0, "tests_created": 0}
    assert set(second["company_demo"].values()) == {0}
    assert second["security_demo"] == {}
    assert second["e2e_demo"] == {"consents": 0, "practice_grants": 0, "tests": 0, "approvals": 0}
    assert second["commerce_demo"] == {"products": 0, "coupons": 0}

    # B3e/B3f: the learner is clean and may practise.
    from app.modules.entitlements import service as ents
    from app.modules.placement.models import Topic

    student = await _user(db, "student@dev.techdrona.local")
    assert student.restriction_level == 0
    cases = select(func.count()).select_from(SecurityCase).where(SecurityCase.user_id == student.id)
    assert (await db.execute(cases)).scalar_one() == 0
    quant = (await db.execute(select(Topic.id).where(Topic.path == "quant"))).scalar_one()
    learner = Principal(user_id=student.id, session_id=uuid.uuid4(), is_minor=False)
    ev = await ents.evaluate(db, learner, "question_set", quant)
    assert ev.decision.allowed and ev.decision.reason == "entitlement"
    # paid checkout (COM-01) needs security_monitoring for adults (PO-03)
    from app.modules.identity.models import Consent

    purposes = set((await db.execute(select(Consent.purpose).where(Consent.user_id == student.id))).scalars())
    assert "security_monitoring" in purposes

    # Every fixture account stays synthetic after the signal writes.
    for f in security_demo.FIXTURES:
        assert (await _user(db, f.email)).is_synthetic is True

    # B3a/B3b: restricted student at L3, linked evaluation + signals, contact eligible, no request.
    from app.modules.security.unblock import contact_eligible, reverifiable

    rs = await _user(db, security_demo.RESTRICTED)
    r = await _active(db, rs.id)
    assert (r.level, r.source, r.lift_pending_at) == (3, "engine", None)
    assert r.evaluation_id is not None and r.rule_keys
    evaluation = (
        await db.execute(select(RiskEvaluation).where(RiskEvaluation.id == r.evaluation_id))
    ).scalar_one()
    assert (evaluation.mode, evaluation.action, evaluation.level_after) == ("enforce", "restrict_L3", 3)
    assert evaluation.case_id == r.case_id and evaluation.restriction_id == r.id
    assert {c["rule"] for c in evaluation.signals} >= {"SH-01", "SH-05"}
    sigs = select(func.count()).select_from(SecuritySignal).where(SecuritySignal.user_id == rs.id)
    assert (await db.execute(sigs)).scalar_one() >= 5
    assert contact_eligible(rs.email_verified_at, r.starts_at)
    reqs = select(func.count()).select_from(UnblockRequest).where(UnblockRequest.user_id == rs.id)
    assert (await db.execute(reqs)).scalar_one() == 0

    # SCN-10: the reverify fixture is lift-pending and eligible for AUTH-21.
    rv = await _user(db, security_demo.REVERIFY)
    pending = await reverifiable(db, rv.id)
    assert pending.lift_pending_at is not None and contact_eligible(rv.email_verified_at, pending.starts_at)

    # B3c: L4, high-risk, submitted request, dual control for reviewer A, B may approve.
    from app.modules.security.cases import conflict_reasons, second_approval_reasons

    sus = await _user(db, security_demo.SUSPENDED)
    case = (await db.execute(select(SecurityCase).where(SecurityCase.user_id == sus.id))).scalar_one()
    r4 = await _active(db, sus.id)
    assert (case.level, r4.level, case.is_high_risk) == (4, 4, True)
    assert "reseller_pattern" in case.high_risk_reasons
    ur = (await db.execute(select(UnblockRequest).where(UnblockRequest.case_id == case.id))).scalar_one()
    assert ur.state == "submitted" and ur.restriction_id == r4.id
    reviewer_a = await _user(db, "security@dev.techdrona.local")
    reviewer_b = await _user(db, "security2@dev.techdrona.local")
    assert r4.applied_by not in (reviewer_a.id, reviewer_b.id)
    for rev in (reviewer_a, reviewer_b):
        assert await conflict_reasons(db, rev.id, case, r4) == []
    reasons = await second_approval_reasons(db, reviewer_a.id, case, r4, {"outcome": "lift_false_positive"})
    assert "l4_high_risk" in reasons

    # E2E env file: ids resolve to these fixtures; secrets are the fixed dev constants.
    env = dict(await e2e_env.values(db))
    assert env["E2E_L4_CASE_ID"] == str(case.id)
    assert env["E2E_RESTRICTED_IDENTIFIER"] == security_demo.RESTRICTED
    assert env["E2E_REVIEWER_B_TOTP_SECRET"] == dev_users.DEV_TOTP_SECRETS["security2"]
    assert env["E2E_REVIEWER_A_IDENTIFIER"] != env["E2E_REVIEWER_B_IDENTIFIER"]
    # Staff consoles covered by the finance-admin-staff and studio-staff specs.
    for prefix, local in (("FINANCE", "finance"), ("CONTENT", "content"), ("ADMIN", "admin")):
        assert env[f"E2E_{prefix}_IDENTIFIER"] == f"{local}@{dev_users.DOMAIN}"
        assert env[f"E2E_{prefix}_TOTP_SECRET"] == dev_users.DEV_TOTP_SECRETS[local]
    from app.modules.assessments.models import Test

    t = (await db.execute(select(Test).where(Test.id == uuid.UUID(env["E2E_TEST_ID"])))).scalar_one()
    assert (t.slug, t.status, t.is_free, t.attempts_allowed) == (
        e2e_demo.E2E_TEST_SLUG,
        "published",
        True,
        100,
    )
    assert "\n" not in "".join(v for _, v in await e2e_env.values(db))


async def test_trainer_sees_a_test_in_scope(db, client, auth) -> None:
    """B3d through the real route + real RBAC checker (fake session resolver only)."""
    from app.core import auth as core_auth
    from app.modules.orgs.models import Organization
    from app.modules.rbac.service import RbacPermissionChecker, active_grants

    await _run_all(db)
    trainer = await _user(db, "trainer@dev.techdrona.local")
    org = (
        await db.execute(select(Organization.id).where(Organization.slug == dev_users.ORG_SLUG))
    ).scalar_one()
    grants = tuple(
        RoleGrant(g.role, cast(ScopeType, g.scope_type), g.scope_id)
        for g in await active_grants(db, trainer.id)
    )
    assert any(g.role == "trainer" and g.scope_type == "batch" for g in grants)
    p = Principal(
        user_id=trainer.id,
        session_id=uuid.uuid4(),
        tier="staff",
        grants=grants,
        org_ids=(org,),
        aal=2,
        mfa_level="totp",
        is_minor=False,
    )
    core_auth.register_permission_checker(RbacPermissionChecker())
    r = await client.get("/api/v1/studio/tests", headers=auth.login(p))
    assert r.status_code == 200, r.text
    slugs = {t["slug"] for t in r.json()["items"]}
    assert e2e_demo.TRAINER_TEST_SLUG in slugs


async def test_admin_sees_the_seeded_pending_approval_with_payload(db, client, auth) -> None:
    """Final verification: the e2e approvals spec needs a real pending dual-control request
    that admin@ (not the requester admin2@) can list and open with its payload."""
    from app.core import auth as core_auth
    from app.modules.rbac.service import RbacPermissionChecker, active_grants

    await _run_all(db)
    admin = await _user(db, "admin@dev.techdrona.local")
    grants = tuple(
        RoleGrant(g.role, cast(ScopeType, g.scope_type), g.scope_id)
        for g in await active_grants(db, admin.id)
    )
    p = Principal(
        user_id=admin.id,
        session_id=uuid.uuid4(),
        tier="staff",
        grants=grants,
        is_platform=True,
        aal=2,
        mfa_level="totp",
        is_minor=False,
    )
    core_auth.register_permission_checker(RbacPermissionChecker())
    r = await client.get("/api/v1/admin/approvals", headers=auth.login(p))
    assert r.status_code == 200, r.text
    mine = [a for a in r.json()["data"] if a["request_reason"] == e2e_demo.APPROVAL_REASON]
    assert len(mine) == 1 and mine[0]["action_type"] == "policy.change"
    assert mine[0]["requested_by"] != str(admin.id)
    d = await client.get(f"/api/v1/admin/approvals/{mine[0]['approval_request_id']}", headers=auth.login(p))
    assert d.status_code == 200, d.text
    assert d.json()["payload"]["setting_key"] == e2e_demo.APPROVAL_SETTING


async def test_dev_users_are_single_company(db) -> None:
    """WS1: the dev seed builds the company org's demo batch with the five target roles only;
    no college, no coordinator, no removed roles; batch staff get batch grants in the company."""
    from app.core.company import COMPANY_ORG_ID
    from app.modules.orgs.models import Batch, Organization, OrgMembership
    from app.modules.rbac.catalogue import REMOVED_ROLES, ROLES
    from app.modules.rbac.service import active_grants

    await dev_users.seed(db)
    await system_context(db, "t")
    live = list(
        (await db.execute(select(Organization.id).where(Organization.deleted_at.is_(None)))).scalars()
    )
    assert COMPANY_ORG_ID in live
    batch = (await db.execute(select(Batch).where(Batch.code == dev_users.BATCH_CODE))).scalar_one()
    assert batch.organization_id == COMPANY_ORG_ID
    held: set[str] = set()
    for local, _name, role, scope in dev_users.PEOPLE:
        u = await _user(db, f"{local}@{dev_users.DOMAIN}")
        grants = await active_grants(db, u.id)
        held |= {g.role for g in grants}
        if role:
            assert [(g.role, g.scope_type) for g in grants] == [(role, scope)]
            if scope == "batch":
                assert grants[0].scope_id == batch.id and grants[0].organization_id == COMPANY_ORG_ID
    assert held <= set(ROLES) and not held & set(REMOVED_ROLES)
    assert {"super_admin", "trainer", "evaluator", "content_manager"} <= held
    students = (
        await db.execute(
            select(func.count())
            .select_from(OrgMembership)
            .where(OrgMembership.organization_id == COMPANY_ORG_ID, OrgMembership.member_type == "student")
        )
    ).scalar_one()
    assert students >= 5


# --------------------------------------------------------------------------- single company (D7)


async def test_single_company_accounts_roles_and_batches(db) -> None:
    """Exactly one live org; only the target roles, at platform or batch scope; staff on
    DEMO-CSE-27; students active members of the two demo batches; no college-era accounts."""
    from app.core.company import COMPANY_ORG_ID
    from app.modules.orgs.models import Batch, BatchMember, Organization, OrgMembership
    from app.modules.rbac.catalogue import GRANT_SCOPE_TYPES
    from app.modules.rbac.service import active_grants

    await _run_all(db)
    live = list((await db.execute(select(Organization).where(Organization.deleted_at.is_(None)))).scalars())
    assert [o.id for o in live] == [COMPANY_ORG_ID] and live[0].org_type == "internal"
    batches = {
        b.code: b
        for b in (await db.execute(select(Batch).where(Batch.code.in_(dev_users.BATCHES)))).scalars()
    }
    assert set(batches) == {dev_users.BATCH_CODE, dev_users.SECOND_BATCH_CODE}
    assert {b.organization_id for b in batches.values()} == {COMPANY_ORG_ID}

    expected = {
        "admin": ("super_admin", "platform"),
        "admin2": ("super_admin", "platform"),
        "trainer": ("trainer", "batch"),
        "evaluator": ("evaluator", "batch"),
        "content": ("content_manager", "platform"),
    }
    for local, (role, scope) in expected.items():
        u = await _user(db, f"{local}@{dev_users.DOMAIN}")
        grants = await active_grants(db, u.id)
        assert [(g.role, g.scope_type) for g in grants] == [(role, scope)], local
        if scope == "batch":
            assert grants[0].scope_id == batches[dev_users.BATCH_CODE].id
        assert u.is_synthetic and u.status == "active"
    roles = {"super_admin", "trainer", "evaluator", "content_manager"}
    for local, _name, role, _scope in dev_users.PEOPLE:
        u = await _user(db, f"{local}@{dev_users.DOMAIN}")
        for g in await active_grants(db, u.id):
            assert g.role in roles and g.scope_type in GRANT_SCOPE_TYPES and g.scope_type != "organization"
        if role is not None:
            continue
        code = dev_users.STUDENT_BATCH.get(local, dev_users.BATCH_CODE)
        member = (
            await db.execute(
                select(BatchMember).where(
                    BatchMember.user_id == u.id,
                    BatchMember.batch_id == batches[code].id,
                    BatchMember.status == "active",
                )
            )
        ).scalar_one()
        assert member.member_role == "student"
        om = (
            await db.execute(
                select(OrgMembership).where(
                    OrgMembership.user_id == u.id, OrgMembership.organization_id == COMPANY_ORG_ID
                )
            )
        ).scalar_one()
        assert (om.status, om.member_type) == ("active", "student")
    for legacy in dev_users.LEGACY_LOCALS:
        found = (
            await db.execute(select(User.id).where(User.email == f"{legacy}@{dev_users.DOMAIN}"))
        ).first()
        assert found is None  # the seed never creates them


async def test_demo_content_for_every_feature(db) -> None:
    from app.modules.assessments.models import TestAssignment
    from app.modules.coding.models import CodingProblem
    from app.modules.engage.models import EngageActivity, EngageQuestion
    from app.modules.learning.models import Assignment, AssignmentAllocation, AssignmentSubmission
    from app.modules.orgs.models import Batch
    from app.modules.paths import service as paths
    from app.modules.paths.models import LearningPath, LearningPathVersionStep, PathAllocation, PathArticle
    from app.modules.placement.models import QuestionBank, QuestionBankItem

    await _run_all(db)
    batch = (await db.execute(select(Batch).where(Batch.code == dev_users.BATCH_CODE))).scalar_one()
    evaluator = await _user(db, "evaluator@dev.techdrona.local")

    bank = (
        await db.execute(select(QuestionBank).where(QuestionBank.name == company_demo.BANK_NAME))
    ).scalar_one()
    items = select(func.count()).select_from(QuestionBankItem).where(QuestionBankItem.bank_id == bank.id)
    assert (await db.execute(items)).scalar_one() == len(placement_demo.QUESTIONS)

    art = (
        await db.execute(select(PathArticle).where(PathArticle.title == company_demo.ARTICLE_TITLE))
    ).scalar_one()
    assert (art.status, art.audience, art.batch_ids) == ("published", "batches", [batch.id])
    lp = (
        await db.execute(select(LearningPath).where(LearningPath.title == company_demo.PATH_TITLE))
    ).scalar_one()
    assert lp.status == "published" and lp.current_version_id is not None
    steps = list(
        (
            await db.execute(
                select(LearningPathVersionStep).where(
                    LearningPathVersionStep.path_version_id == lp.current_version_id
                )
            )
        ).scalars()
    )
    urls = [s.url for s in steps if s.url]
    assert len(urls) == 2 and all(paths.embeddable(u) for u in urls)  # D9 allow-list
    alloc = (await db.execute(select(PathAllocation).where(PathAllocation.path_id == lp.id))).scalar_one()
    assert (alloc.target_type, alloc.batch_id, alloc.status) == ("batch", batch.id, "active")

    act = (
        await db.execute(select(EngageActivity).where(EngageActivity.title == company_demo.ACTIVITY_TITLE))
    ).scalar_one()
    assert act.batch_id == batch.id and act.deleted_at is None
    qs = select(func.count()).select_from(EngageQuestion).where(EngageQuestion.activity_id == act.id)
    assert (await db.execute(qs)).scalar_one() == 2

    ta = (await db.execute(select(TestAssignment).where(TestAssignment.batch_id == batch.id))).scalar_one()
    assert ta.release_mode == "manual"
    a = (
        await db.execute(select(Assignment).where(Assignment.title == company_demo.ASSIGNMENT_TITLE))
    ).scalar_one()
    al = (
        await db.execute(select(AssignmentAllocation).where(AssignmentAllocation.assignment_id == a.id))
    ).scalar_one()
    assert al.evaluator_ids == [evaluator.id] and al.batch_id == batch.id
    sub = (
        await db.execute(select(AssignmentSubmission).where(AssignmentSubmission.assignment_id == a.id))
    ).scalar_one()
    assert sub.status == "submitted" and sub.graded_at is None

    problems = select(func.count()).select_from(CodingProblem).where(CodingProblem.slug.like("demo-%"))
    assert (await db.execute(problems)).scalar_one() == len(coding_demo.PROBLEMS)


async def test_legacy_college_accounts_are_retired_idempotently(db) -> None:
    """D7: a database from the old dev dump may still hold coordinator@/support@; dev_users
    deactivates them (grants revoked, memberships closed) once, and touches nothing else."""
    from app.core.company import COMPANY_ORG_ID
    from app.modules.orgs.models import Batch, BatchMember, OrgMembership
    from app.modules.rbac.service import active_grants
    from tests.identity.factory import grant, make_user

    await dev_users.seed(db)
    await system_context(db, "test.legacy")
    batch = (await db.execute(select(Batch).where(Batch.code == dev_users.BATCH_CODE))).scalar_one()
    legacy = await make_user(db, email=f"coordinator@{dev_users.DOMAIN}")
    real = await make_user(db, email="coordinator@example.com")  # not a dev demo account
    await system_context(db, "test.legacy")
    for uid in (legacy.id, real.id):
        (await db.execute(select(User).where(User.id == uid))).scalar_one().is_synthetic = uid == legacy.id
        await grant(db, uid, "trainer", scope_type="batch", scope_id=batch.id)
        await system_context(db, "test.legacy")
        db.add(
            OrgMembership(
                id=uuid.uuid4(),
                organization_id=COMPANY_ORG_ID,
                user_id=uid,
                member_type="staff",
                status="active",
                source="staff",
            )
        )
        db.add(
            BatchMember(
                id=uuid.uuid4(),
                batch_id=batch.id,
                organization_id=COMPANY_ORG_ID,
                user_id=uid,
                member_role="trainer",
            )
        )
    await db.flush()

    assert await dev_users.purge_legacy(db) == 1
    assert await dev_users.purge_legacy(db) == 0
    assert await dev_users.seed(db) == {}  # the seed purges too and stays idempotent
    await system_context(db, "test.legacy")
    u = await _user(db, legacy.email)
    assert u.status == "deactivated" and await active_grants(db, u.id) == []
    oms = (await db.execute(select(OrgMembership.status).where(OrgMembership.user_id == u.id))).scalars()
    assert set(oms) == {"left"}
    bms = (await db.execute(select(BatchMember.status).where(BatchMember.user_id == u.id))).scalars()
    assert set(bms) == {"removed"}
    untouched = await _user(db, real.email)
    assert untouched.status == "active" and [g.role for g in await active_grants(db, untouched.id)] == [
        "trainer"
    ]
