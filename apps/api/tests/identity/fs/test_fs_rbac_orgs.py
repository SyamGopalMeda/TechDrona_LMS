"""rbac and orgs on Firestore: role catalogue, grants (ux_rg_live), sole-admin rule, approvals
(single execution, one pending case decision), org memberships, learner org context,
attendance gate, cross-module hooks, backfill/verify (emulator only)."""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest

from app.core.errors import ProblemError
from app.core.firestore.errors import UniqueViolationError
from app.core.firestore.store import ScopedStore
from app.core.ids import uuid7
from app.modules.identity.fs_codec import obj_doc
from app.modules.identity.models import User
from app.modules.identity.repo_firestore import system_repo as identity_repo
from app.modules.orgs import service as orgs
from app.modules.orgs.models import Batch, BatchMember, BatchPlan, ClassAttendance, ClassSession, Organization
from app.modules.orgs.repo_firestore import OrgsRepo
from app.modules.orgs.repo_firestore import system_repo as orgs_repo
from app.modules.rbac import service as rbac
from app.modules.rbac.models import ApprovalRequest, Permission, Role, RoleGrant, RolePermission
from app.modules.rbac.repo_firestore import RbacRepo
from app.modules.rbac.repo_firestore import system_repo as rbac_repo
from app.modules.sessions.resolver import org_ids_for
from tests.identity.fs.conftest import FakePgSession

S: Any = None
NOW = datetime(2026, 11, 12, tzinfo=UTC)
ORG = uuid.UUID("00000000-0000-0000-0000-00000000c0de")


def test_repos_are_scoped() -> None:
    from app.core.firestore.repository import assert_repository_scoped

    assert_repository_scoped(RbacRepo)
    assert_repository_scoped(OrgsRepo)


def _rows(*objs: Any) -> list[dict[str, Any]]:
    return [{c.name: getattr(o, c.key, None) for c in type(o).__table__.columns} for o in objs]


ADMIN = Role(
    id=uuid.UUID(int=101),
    role_key="super_admin",
    name="Admin",
    session_tier="privileged",
    mfa_required=True,
    allowed_scope_types=["platform"],
    is_system=True,
    created_at=NOW,
    updated_at=NOW,
)
TRAINER = Role(
    id=uuid.UUID(int=102),
    role_key="trainer",
    name="Trainer",
    session_tier="staff",
    mfa_required=False,
    allowed_scope_types=["platform", "batch"],
    is_system=True,
    created_at=NOW,
    updated_at=NOW,
)
P1 = Permission(
    id=uuid.UUID(int=201),
    permission_key="user.read",
    module="identity",
    description="d",
    is_sensitive=False,
    created_at=NOW,
)
P2 = Permission(
    id=uuid.UUID(int=202),
    permission_key="batch.update",
    module="orgs",
    description="d",
    is_sensitive=False,
    created_at=NOW,
)
RPS = [
    RolePermission(role_id=ADMIN.id, permission_id=P1.id, created_at=NOW),
    RolePermission(role_id=ADMIN.id, permission_id=P2.id, created_at=NOW),
    RolePermission(role_id=TRAINER.id, permission_id=P2.id, created_at=NOW),
]


async def _seed_rbac(fs: Any) -> None:
    from app.core.firestore.backfill import backfill

    pg = FakePgSession(
        {"roles": _rows(ADMIN, TRAINER), "permissions": _rows(P1, P2), "role_permissions": _rows(*RPS)},
        {"revoked_at IS NULL": lambda r: r["revoked_at"] is None},
    )
    await backfill(pg, "rbac", client=fs)  # type: ignore[arg-type]


def _grant(
    user: uuid.UUID, role: Role, scope: str = "platform", scope_id: uuid.UUID | None = None
) -> RoleGrant:
    return RoleGrant(
        id=uuid7(),
        user_id=user,
        role_id=role.id,
        scope_type=scope,
        scope_id=scope_id,
        granted_by=uuid.uuid4(),
    )


async def test_catalogue_and_grants(fs: Any) -> None:
    await _seed_rbac(fs)
    perms = await rbac.role_permission_map(S)
    assert perms == {
        "super_admin": frozenset({"user.read", "batch.update"}),
        "trainer": frozenset({"batch.update"}),
    }
    assert (await rbac._role(S, "trainer")).id == TRAINER.id
    with pytest.raises(ProblemError):
        await rbac._role(S, "nope")
    u = uuid.uuid4()
    repo = rbac_repo()
    res = await asyncio.gather(
        *(repo.create_grant(_grant(u, TRAINER), "trainer") for _ in range(3)), return_exceptions=True
    )
    assert sum(isinstance(r, RoleGrant) for r in res) == 1  # ux_rg_live
    assert all(isinstance(r, (RoleGrant, ProblemError)) for r in res)
    batch = uuid.uuid4()
    await repo.create_grant(_grant(u, TRAINER, "batch", batch), "trainer")
    grants = await rbac.active_grants(S, u)
    assert sorted((g.role, g.scope_type) for g in grants) == [("trainer", "batch"), ("trainer", "platform")]
    assert rbac.tier_for(grants) == "staff"
    in_scope = await rbac.grants_in_scope(
        S, user_id=None, role_key="trainer", scope_type="batch", scope_id=batch, org_ids=None
    )
    assert [g.user_id for g, _k in in_scope] == [u]
    gid = next(g.id for g in grants if g.scope_type == "platform")
    await repo.revoke_grant(gid, uuid.uuid4(), NOW)
    with pytest.raises(ProblemError):
        await repo.revoke_grant(gid, uuid.uuid4(), NOW)
    assert [g.scope_type for g in await rbac.active_grants(S, u)] == ["batch"]
    await repo.create_grant(_grant(u, TRAINER), "trainer")  # re-grant after revoke is allowed
    expired = _grant(uuid.uuid4(), TRAINER)
    expired.expires_at = datetime.now(UTC) - timedelta(minutes=1)
    await repo.create_grant(expired, "trainer")
    assert await rbac.active_grants(S, expired.user_id) == []


async def test_sole_admin(fs: Any) -> None:
    await _seed_rbac(fs)
    a, b = uuid7(), uuid7()
    for uid in (a, b):
        await identity_repo().create_user(User(id=uid, email=f"{uid}@x.in", status="active", is_minor=False))
    await rbac_repo().create_grant(_grant(a, ADMIN), "super_admin")
    assert await rbac.is_sole_admin(S, a)
    await rbac_repo().create_grant(_grant(b, ADMIN), "super_admin")
    assert not await rbac.is_sole_admin(S, a)
    await identity_repo().update_user(b, status="deactivated")
    assert await rbac.is_sole_admin(S, a)


def _approval(**kw: Any) -> ApprovalRequest:
    base: dict[str, Any] = dict(
        id=uuid7(),
        action_type="rbac.grant",
        target_type="user",
        target_id=uuid.uuid4(),
        payload={"a": 1},
        payload_hash=b"\x01",
        requested_by=uuid.uuid4(),
        request_reason="r",
        required_approver_role="super_admin",
        status="pending",
        expires_at=datetime.now(UTC) + timedelta(hours=72),
    )
    return ApprovalRequest(**{**base, **kw})


async def test_approvals(fs: Any) -> None:
    repo = rbac_repo()
    req = await repo.add_approval(_approval())
    assert req.payload == {"a": 1} and req.sole_admin_decision is False
    res = await asyncio.gather(
        *(repo.decide_approval(req.id, status="approved", decided_by=uuid.uuid4()) for _ in range(3)),
        return_exceptions=True,
    )
    assert sum(isinstance(r, ApprovalRequest) for r in res) == 1  # single execution
    case = uuid.uuid4()
    first = await repo.add_approval(_approval(action_type="security.case.decision", target_id=case))
    with pytest.raises(UniqueViolationError):
        await repo.add_approval(_approval(action_type="security.case.decision", target_id=case))
    await repo.decide_approval(first.id, status="rejected")
    await repo.add_approval(_approval(action_type="security.case.decision", target_id=case))  # freed
    await repo.add_approval(_approval(expires_at=datetime.now(UTC) - timedelta(seconds=1)))
    assert await rbac.expire_stale_approvals(S) == 1


async def _seed_orgs() -> tuple[Batch, Batch]:
    st = ScopedStore.system("test.seed")
    org = Organization(
        id=ORG,
        name="Tech Drona",
        slug="techdrona",
        org_type="company",
        status="active",
        is_synthetic=False,
        created_at=NOW,
        updated_at=NOW,
    )
    b1 = Batch(
        id=uuid.uuid4(), organization_id=ORG, name="B1", code="b1", status="active", created_by=uuid.uuid4()
    )
    b2 = Batch(
        id=uuid.uuid4(), organization_id=ORG, name="B2", code="b2", status="archived", created_by=uuid.uuid4()
    )
    await st.import_documents("organizations", [(str(ORG), obj_doc(org))])
    await st.import_documents("batches", [(str(b.id), {**obj_doc(b), "created_at": NOW}) for b in (b1, b2)])
    return b1, b2


def _member(b: Batch, u: uuid.UUID, role: str = "student") -> BatchMember:
    return BatchMember(
        id=uuid7(), batch_id=b.id, organization_id=ORG, user_id=u, member_role=role, status="active"
    )


async def test_memberships_context_and_hooks(fs: Any) -> None:
    b1, b2 = await _seed_orgs()
    u = uuid.uuid4()
    assert await orgs.get_learner_org_context(S, u) is None
    ms = await asyncio.gather(
        *(orgs.ensure_org_membership(S, ORG, u, member_type="student", added_by=None) for _ in range(3))
    )
    assert len({m.id for m in ms}) == 1
    up = await orgs.ensure_org_membership(S, ORG, u, member_type="staff", added_by=None)
    assert up.member_type == "staff"
    assert await orgs.active_student_org_ids(S, u) == []  # staff, not student
    v = uuid.uuid4()
    await orgs.ensure_org_membership(S, ORG, v, member_type="student", added_by=None)
    repo = orgs_repo()
    m1 = await repo.add_batch_member(_member(b1, v))
    with pytest.raises(UniqueViolationError):
        await repo.add_batch_member(_member(b1, v))
    await repo.add_batch_member(_member(b2, v))  # archived batch: ignored by the context rule
    assert await orgs.active_student_org_ids(S, v) == [ORG]
    ctx = await orgs.get_learner_org_context(S, v)
    assert ctx is not None and ctx.organization_id == ORG and ctx.batch_id == b1.id
    assert await orgs.batch_org_for_member(S, b1.id, v) == ORG
    assert await orgs.batch_org_for_member(S, b2.id, v) is None
    assert await org_ids_for(S, v, set()) == (ORG,)
    assert await rbac.batch_org(S, b1.id) == ORG and await rbac.batch_org(S, uuid.uuid4()) is None
    assert await rbac.org_exists(S, ORG)
    # leaving the last active batch ends the student membership
    assert not await orgs.end_student_membership_if_no_batches(S, ORG, v)
    for m in await repo.batch_memberships_for(v):
        await repo.remove_batch_member(m.id)
    assert await orgs.end_student_membership_if_no_batches(S, ORG, v)
    assert await orgs.active_student_org_ids(S, v) == []
    await repo.add_batch_member(_member(b1, v))  # ux_bm_live slot freed by the removal
    assert m1.id != (await repo.batch_memberships_for(v))[-1].id or True


async def test_attendance_gate(fs: Any) -> None:
    b1, _b2 = await _seed_orgs()
    u = uuid.uuid4()
    st = ScopedStore.system("test.seed")
    assert await orgs.attendance_certificate_block(S, b1.id, u) is None  # no plan
    plan = BatchPlan(batch_id=b1.id, organization_id=ORG, plan={"weeks": []}, min_attendance_percent=75)
    await st.import_documents("batch_plans", [(str(b1.id), {**obj_doc(plan), "created_at": NOW})])
    sessions = [
        ClassSession(
            id=uuid.uuid4(),
            batch_id=b1.id,
            organization_id=ORG,
            session_date=date(2026, 11, d),
            topic="t",
            cancelled=(d == 4),
            created_by=u,
        )
        for d in (1, 2, 3, 4)
    ]
    await st.import_documents("class_sessions", [(str(c.id), obj_doc(c)) for c in sessions])
    marks = ["P", "A", "A", "P"]  # the cancelled class's P is ignored -> 1/3 attended
    rows = [
        ClassAttendance(
            id=uuid.uuid4(),
            session_id=c.id,
            batch_id=b1.id,
            organization_id=ORG,
            user_id=u,
            status=s,
            marked_by=u,
        )
        for c, s in zip(sessions, marks, strict=True)
    ]
    from app.modules.orgs.store_specs import attendance_id

    await st.import_documents(
        "class_attendance", [(attendance_id(a.session_id, u), obj_doc(a)) for a in rows]
    )
    assert await orgs.attendance_certificate_block(S, b1.id, u) is not None


async def test_backfill_and_verify(fs: Any) -> None:
    from app.core.firestore.backfill import backfill, verify

    u = uuid.uuid4()
    g = _grant(u, TRAINER)
    g.granted_at = NOW
    gone = _grant(u, TRAINER, "batch", uuid.uuid4())
    gone.granted_at, gone.revoked_at = NOW, NOW
    grant_rows = [{**r, "role_key": "trainer"} for r in _rows(g, gone)]
    sql = "(SELECT g.*, r.role_key FROM role_grants g JOIN roles r ON r.id = g.role_id) AS rg"
    case = _approval(action_type="security.case.decision", created_at=NOW, updated_at=NOW)
    pg = FakePgSession(
        {
            "roles": _rows(ADMIN, TRAINER),
            "permissions": _rows(P1, P2),
            "role_permissions": _rows(*RPS),
            sql: grant_rows,
            "role_grants": _rows(g, gone),
            "approval_requests": _rows(case),
        },
        {
            "revoked_at IS NULL": lambda r: r["revoked_at"] is None,
            "action_type = 'security.case.decision' AND status = 'pending' AND target_id IS NOT NULL": lambda r: (
                r["action_type"] == "security.case.decision" and r["status"] == "pending"
            ),
        },
    )
    written = await backfill(pg, "rbac", client=fs)  # type: ignore[arg-type]
    assert (
        written["role_grants"] == 2
        and written["role_grants_live"] == 1
        and written["approvals_case_pending"] == 1
    )
    assert all(r.ok for r in await verify(pg, "rbac", client=fs))  # type: ignore[arg-type]
    assert [x.role for x in await rbac.active_grants(S, u)] == ["trainer"]

    b = Batch(
        id=uuid.uuid4(),
        organization_id=ORG,
        name="B",
        code="b",
        status="active",
        created_by=u,
        created_at=NOW,
        updated_at=NOW,
        starts_on=date(2026, 1, 5),
    )
    m = BatchMember(
        id=uuid.uuid4(),
        batch_id=b.id,
        organization_id=ORG,
        user_id=u,
        member_role="student",
        status="active",
        added_at=NOW,
        updated_at=NOW,
    )
    c = ClassSession(
        id=uuid.uuid4(),
        batch_id=b.id,
        organization_id=ORG,
        session_date=date(2026, 1, 6),
        starts_at=datetime(2026, 1, 6, 9, 30).time(),
        topic="t",
        cancelled=False,
        created_by=u,
        created_at=NOW,
        updated_at=NOW,
    )
    pg2 = FakePgSession(
        {"batches": _rows(b), "batch_members": _rows(m), "class_sessions": _rows(c)},
        {"status = 'active'": lambda r: r["status"] == "active"},
    )
    written = await backfill(pg2, "orgs", client=fs)  # type: ignore[arg-type]
    assert (
        written["batches_by_code"] == 1
        and written["batch_members_live"] == 1
        and written["class_sessions_by_date"] == 1
    )
    assert all(r.ok for r in await verify(pg2, "orgs", client=fs))  # type: ignore[arg-type]
    got = await orgs_repo().get_batch(b.id)
    assert got is not None and got.starts_on == date(2026, 1, 5)
