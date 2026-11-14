"""Dual-control approvals on Firestore with no Postgres: ``/admin/approvals`` (ADM-12..16) and the
RBAC-07/08 approve/reject routes, including the parity rule that a failing privileged action
leaves the request ``pending`` (as the Postgres rollback does)."""

from __future__ import annotations

import asyncio
import uuid
from datetime import timedelta
from typing import Any

from app.core.ids import uuid7
from app.modules.identity import clock
from app.modules.rbac import public as rbac_public
from app.modules.rbac.models import ApprovalRequest
from app.modules.rbac.repo_firestore import system_repo as rbac_repo
from app.modules.rbac.service import payload_hash
from tests.identity.fs.conftest import fs_user
from tests.identity.fs.test_http_sessions_rbac import admin


async def _request(
    requester: uuid.UUID, grantee: uuid.UUID, role_key: str = "super_admin"
) -> ApprovalRequest:
    payload = {
        "user_id": str(grantee),
        "role_key": role_key,
        "scope_type": "platform",
        "scope_id": None,
        "expires_at": None,
        "reason": "test",
    }
    return await rbac_repo().add_approval(
        ApprovalRequest(
            id=uuid7(),
            action_type="rbac.grant.privileged",
            target_type="user",
            target_id=grantee,
            payload=payload,
            payload_hash=payload_hash(payload),
            requested_by=requester,
            request_reason="test",
            required_approver_role="super_admin",
            status="pending",
            expires_at=clock.now() + timedelta(hours=72),
            created_at=clock.now(),
        )
    )


def _idem() -> dict[str, str]:
    return {"Idempotency-Key": uuid.uuid4().hex}


async def test_failed_execution_rolls_the_claim_back(http: Any) -> None:
    """The executor fails (unknown role in the payload -> 422): the request is pending again with
    no decision recorded, on both decision routes; a later valid decision still works once."""
    maker, _ = await admin(http, "maker@x.in")
    _checker, _ = await admin(http, "checker@x.in")
    grantee = uuid7()
    bad = await _request(maker.id, grantee, role_key="no_such_role")

    r = await http.post(f"/rbac/approval-requests/{bad.id}/approve", {"note": "ok"})
    assert r.status_code == 422, r.text
    got = await rbac_public.get_approval(None, bad.id)  # type: ignore[arg-type]
    assert got is not None and got.status == "pending"
    assert got.decided_by is None and got.decided_at is None and got.decision_note is None

    r = await http.post(f"/admin/approvals/{bad.id}/approve", {"note": "ok"}, headers=_idem())
    assert r.status_code == 422, r.text
    got = await rbac_public.get_approval(None, bad.id)  # type: ignore[arg-type]
    assert got is not None and got.status == "pending" and got.decided_by is None

    # still decidable afterwards: reject wins once
    r = await http.post(f"/admin/approvals/{bad.id}/reject", {"note": "no"}, headers=_idem())
    assert r.status_code == 200 and r.json()["status"] == "rejected", r.text
    r = await http.post(f"/admin/approvals/{bad.id}/reject", {"note": "no"}, headers=_idem())
    assert r.status_code == 409, r.text


async def test_admin_queue_list_get_approve_cancel(http: Any) -> None:
    maker, _ = await admin(http, "maker2@x.in")
    _checker, _ = await admin(http, "checker2@x.in")
    grantee = await fs_user("grantee2@x.in")
    good = await _request(maker.id, grantee.id)

    r = await http.get("/admin/approvals")
    assert r.status_code == 200, r.text
    assert str(good.id) in [x["approval_request_id"] for x in r.json()["data"]]
    r = await http.get(f"/admin/approvals/{good.id}")
    assert r.status_code == 200 and r.json()["payload"]["role_key"] == "super_admin", r.text
    r = await http.get(f"/admin/approvals/{uuid.uuid4()}")
    assert r.status_code == 404

    # two concurrent approvals: one executes, the other gets 409
    rs = await asyncio.gather(
        http.post(f"/admin/approvals/{good.id}/approve", {"note": "a"}, headers=_idem()),
        http.post(f"/admin/approvals/{good.id}/approve", {"note": "b"}, headers=_idem()),
    )
    codes = sorted(x.status_code for x in rs)
    assert codes == [200, 409], [x.text[-300:] for x in rs]
    done = await rbac_public.get_approval(None, good.id)  # type: ignore[arg-type]
    assert done is not None and done.status == "executed" and done.executed_at is not None
    grants = await rbac_public.live_grants(None, user_ids=[grantee.id], role_keys=["super_admin"])  # type: ignore[arg-type]
    assert len(grants) == 1
    r = await http.get("/admin/approvals", params={"status": "executed"})
    assert str(good.id) in [x["approval_request_id"] for x in r.json()["data"]]

    # the requester cancels their own pending request (checker's session is current in http)
    mine = await _request(_checker.id, uuid7())
    r = await http.post(f"/admin/approvals/{mine.id}/cancel")
    assert r.status_code == 200 and r.json()["status"] == "cancelled", r.text
    c = await rbac_public.get_approval(None, mine.id)  # type: ignore[arg-type]
    assert c is not None and c.status == "cancelled" and c.decided_at is None
    r = await http.post(f"/admin/approvals/{mine.id}/cancel")
    assert r.status_code == 409, r.text
    other = await _request(maker.id, uuid7())
    r = await http.post(f"/admin/approvals/{other.id}/cancel")
    assert r.status_code == 403, r.text  # not the requester


async def test_expired_request_answers_409_and_stays_expired(http: Any) -> None:
    maker, _ = await admin(http, "maker3@x.in")
    _checker, _ = await admin(http, "checker3@x.in")
    old = await _request(maker.id, uuid7())
    await rbac_repo().save_approval(
        ApprovalRequest(
            **{
                **{c.key: getattr(old, c.key) for c in ApprovalRequest.__table__.columns},
                "expires_at": clock.now() - timedelta(minutes=1),
            }
        )  # type: ignore[arg-type]
    )
    r = await http.post(f"/admin/approvals/{old.id}/approve", {"note": "late"}, headers=_idem())
    assert r.status_code == 409, r.text
    got = await rbac_public.get_approval(None, old.id)  # type: ignore[arg-type]
    assert got is not None and got.status == "expired"


async def test_public_api_for_other_modules(http: Any) -> None:
    maker, _ = await admin(http, "maker4@x.in")
    coupon = uuid7()
    req = await rbac_repo().add_approval(
        ApprovalRequest(
            id=uuid7(),
            action_type="commerce.coupon.activate",
            target_type="coupon",
            target_id=coupon,
            payload={},
            payload_hash=payload_hash({}),
            requested_by=maker.id,
            request_reason="r",
            required_approver_role="super_admin",
            status="pending",
            expires_at=clock.now() + timedelta(hours=1),
            created_at=clock.now(),
        )
    )
    S: Any = None
    assert set(await rbac_public.get_approvals(S, [req.id])) == {req.id}
    perms = await rbac_public.role_permission_map(S)
    assert "approval.decide" in perms["super_admin"]
    assert await rbac_public.batch_org(S, uuid7()) is None
    g = (await rbac_public.live_grants(S, user_ids=[maker.id]))[0][0]
    from app.core.audit import AuditActor

    revoked = await rbac_public.revoke_grant(
        S, AuditActor.system("test.breakglass"), g.id, maker.id, "break-glass"
    )
    assert revoked.revoked_at is not None
    assert await rbac_public.live_grants(S, user_ids=[maker.id]) == []


# --------------------------------------------------------------------------- round 4: whole-action rollback


async def _audit_actions() -> list[str]:
    from app.core.firestore.store import ScopedStore
    from app.modules.audit.store_specs import OUTBOX

    docs = await ScopedStore.system("test.audit").scan(OUTBOX)
    import json

    return sorted(str(json.loads(d.data["record_json"]).get("action")) for d in docs)


async def _post_failing(http: Any, route: str, headers: Any = None) -> int:
    """POST that is expected to fail with a server error (the ASGI test transport re-raises
    the app's exception after the 500 response was produced)."""
    try:
        r = await http.post(route, {"note": "go"}, headers=headers)
    except RuntimeError as e:
        assert "forced failure" in str(e)
        return 500
    return int(r.status_code)


def _fail_on(monkeypatch: Any, module: Any, action: str) -> Any:
    """Make ``module.audit`` raise for ``action`` (a failure AFTER the grant was written);
    returns the real function (put it back with ``module.audit = real``)."""
    real = module.audit

    async def boom(session: Any, actor: Any, act: str, *a: Any, **kw: Any) -> Any:
        if act == action:
            raise RuntimeError("forced failure after the action's writes")
        return await real(session, actor, act, *a, **kw)

    monkeypatch.setattr(module, "audit", boom)
    return real


async def test_failure_after_grant_write_undoes_everything(http: Any, monkeypatch: Any) -> None:
    """approval.executed audit fails after rbac.service.create_grant wrote the grant, ended the
    grantee's sessions and moved users.sessions_valid_after: everything is undone, as one Postgres
    transaction would be, on both decision routes."""
    import app.modules.admin.approvals as admin_apr
    import app.modules.rbac.router as rbac_router
    from app.modules.identity import public as ipub
    from app.modules.sessions import public as spub
    from tests.identity.fs.test_http_sessions_rbac import sign_in

    maker, _ = await admin(http, "maker5@x.in")
    grantee = await fs_user("grantee5@x.in")
    g_session = await sign_in(http, grantee, browser=http.fork())
    _checker, _ = await admin(http, "checker5@x.in")
    req = await _request(maker.id, grantee.id)
    before_audit = await _audit_actions()

    for route, module, headers in (
        (f"/rbac/approval-requests/{req.id}/approve", rbac_router, None),
        (f"/admin/approvals/{req.id}/approve", admin_apr, _idem()),
    ):
        real = _fail_on(monkeypatch, module, "approval.executed")
        assert await _post_failing(http, route, headers) >= 500, route
        got = await rbac_public.get_approval(None, req.id)  # type: ignore[arg-type]
        assert got is not None and got.status == "pending" and got.decided_by is None, route
        assert await rbac_public.live_grants(None, user_ids=[grantee.id]) == [], route  # type: ignore[arg-type]
        all_grants = await rbac_repo().grants_for(grantee.id)
        assert all_grants == [], route  # the grant document itself is gone
        s = await spub.get_session(None, g_session.id)  # type: ignore[arg-type]
        assert s is not None and s.status == "active", route  # session rotation undone
        u = await ipub.get_user(None, grantee.id)  # type: ignore[arg-type]
        assert u is not None and u.sessions_valid_after is None, route
        assert await _audit_actions() == before_audit, route  # no audit row
        module.audit = real

    # with the failure gone the same request executes once
    r = await http.post(f"/rbac/approval-requests/{req.id}/approve", {"note": "go"})
    assert r.status_code == 200 and r.json()["status"] == "executed", r.text
    assert len(await rbac_public.live_grants(None, user_ids=[grantee.id])) == 1  # type: ignore[arg-type]
    assert "approval.executed" in await _audit_actions()


async def test_failure_after_revoke_write_restores_the_grant(http: Any, monkeypatch: Any) -> None:
    import app.modules.rbac.router as rbac_router

    maker, _ = await admin(http, "maker6@x.in")
    target, _ = await admin(http.fork(), "target6@x.in")
    _checker, _ = await admin(http, "checker6@x.in")
    ((g, _k),) = await rbac_public.live_grants(None, user_ids=[target.id])  # type: ignore[arg-type]
    payload = {"grant_id": str(g.id), "reason": "test"}
    req = await rbac_repo().add_approval(
        ApprovalRequest(
            id=uuid7(),
            action_type="rbac.revoke.privileged",
            target_type="role_grant",
            target_id=g.id,
            payload=payload,
            payload_hash=payload_hash(payload),
            requested_by=maker.id,
            request_reason="test",
            required_approver_role="super_admin",
            status="pending",
            expires_at=clock.now() + timedelta(hours=72),
            created_at=clock.now(),
        )
    )
    _fail_on(monkeypatch, rbac_router, "approval.executed")
    assert await _post_failing(http, f"/rbac/approval-requests/{req.id}/approve") >= 500
    still = await rbac_public.live_grants(None, user_ids=[target.id])  # type: ignore[arg-type]
    assert [x[0].id for x in still] == [g.id] and still[0][0].revoked_at is None
    got = await rbac_public.get_approval(None, req.id)  # type: ignore[arg-type]
    assert got is not None and got.status == "pending"
    # the live-slot reservation was restored too: a duplicate grant is still refused
    from app.core.errors import ProblemError
    from app.modules.rbac.models import RoleGrant

    dup = RoleGrant(
        id=uuid7(), user_id=target.id, role_id=g.role_id, scope_type="platform", granted_by=maker.id
    )
    try:
        await rbac_repo().create_grant(dup, "super_admin")
        raise AssertionError("duplicate live grant accepted")
    except ProblemError as e:
        assert e.code == "invalid_state_transition"
