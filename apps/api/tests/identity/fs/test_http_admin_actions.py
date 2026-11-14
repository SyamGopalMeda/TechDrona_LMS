"""Admin privileged actions on Firestore with no Postgres: ADM-04 deactivate / reactivate, ADM-05
MFA reset (dual control) and break-glass end / review -- success, and a forced failure after the
action's writes that must leave nothing behind (no state change, no audit row, no outbox event),
as the single Postgres transaction would."""

from __future__ import annotations

import json
import uuid
from datetime import timedelta
from typing import Any

import pyotp
import pytest

import app.core.firestore.core_store
import app.modules.admin.store_specs
import app.modules.audit.store_specs  # noqa: F401 - registers the collections scanned below
from app.core.firestore.store import ScopedStore
from app.core.ids import uuid7
from app.modules.identity import clock
from app.modules.identity import public as ipub
from app.modules.rbac import public as rbac_public
from app.modules.sessions import public as spub
from tests.identity.fs.conftest import fs_user
from tests.identity.fs.test_http_sessions_rbac import admin, sign_in

S: Any = None


@pytest.fixture
def admin_fs(http: Any, monkeypatch: pytest.MonkeyPatch) -> Any:
    """``http`` plus TD_STORE_ADMIN=firestore (break-glass rows live in the admin module)."""
    from app.core.firestore.backend import reset_store_backends

    monkeypatch.setenv("TD_STORE_ADMIN", "firestore")
    reset_store_backends()
    return http


def _idem() -> dict[str, str]:
    return {"Idempotency-Key": uuid.uuid4().hex}


async def _scan(coll: str) -> list[dict[str, Any]]:
    return [d.data for d in await ScopedStore.system("test.scan").scan(coll)]


async def _audit_actions() -> list[str]:
    return sorted(json.loads(d["record_json"])["action"] for d in await _scan("audit_outbox"))


async def _outbox_types() -> list[str]:
    return sorted(str(d.get("event_type")) for d in await _scan("outbox_events"))


def _fail_on(monkeypatch: pytest.MonkeyPatch, action: str) -> Any:
    """``admin.accounts.audit`` raises for ``action`` (after the action's own writes)."""
    import app.modules.admin.accounts as acc

    real = acc.audit

    async def boom(session: Any, actor: Any, act: str, *a: Any, **kw: Any) -> Any:
        if act == action:
            raise RuntimeError("forced failure after the action's writes")
        return await real(session, actor, act, *a, **kw)

    monkeypatch.setattr(acc, "audit", boom)
    return real


async def _post(http: Any, path: str, body: dict[str, Any], headers: Any = None) -> int:
    try:
        r = await http.post(path, body, headers=headers)
    except RuntimeError as e:  # the ASGI test transport re-raises the app's 500 exception
        assert "forced failure" in str(e)
        return 500
    assert r.status_code < 300, r.text
    return int(r.status_code)


# --------------------------------------------------------------------------- deactivate / reactivate


async def test_deactivate_reactivate_and_failure_rollback(
    admin_fs: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.modules.admin.accounts as acc

    http = admin_fs
    target = await fs_user("target@x.in")
    t_session = await sign_in(http, target, browser=http.fork())
    await admin(http, "boss@x.in")
    audit0, outbox0 = await _audit_actions(), await _outbox_types()

    real = _fail_on(monkeypatch, "admin.user.deactivated")
    code = await _post(http, f"/admin/users/{target.id}/deactivate", {"reason": "abuse report"}, _idem())
    assert code == 500
    u = await ipub.get_user(S, target.id)
    assert u is not None and u.status == "active" and u.sessions_valid_after is None
    assert (await spub.get_session(S, t_session.id)).status == "active"  # type: ignore[union-attr]
    assert await _audit_actions() == audit0 and await _outbox_types() == outbox0
    acc.audit = real

    r = await http.post(f"/admin/users/{target.id}/deactivate", {"reason": "abuse report"}, headers=_idem())
    assert (
        r.status_code == 200 and r.json()["status"] == "deactivated" and r.json()["sessions_revoked"] == 1
    ), r.text
    assert (await ipub.get_user(S, target.id)).status == "deactivated"  # type: ignore[union-attr]
    assert (await spub.get_session(S, t_session.id)).status == "revoked"  # type: ignore[union-attr]
    assert "admin.user.deactivated" in await _audit_actions()
    assert "identity.user_deactivated" in await _outbox_types()

    _fail_on(monkeypatch, "admin.user.reactivated")
    code = await _post(http, f"/admin/users/{target.id}/reactivate", {"reason": "appeal ok"}, _idem())
    assert code == 500
    assert (await ipub.get_user(S, target.id)).status == "deactivated"  # type: ignore[union-attr]
    acc.audit = real
    r = await http.post(f"/admin/users/{target.id}/reactivate", {"reason": "appeal ok"}, headers=_idem())
    assert r.status_code == 200 and r.json()["status"] == "active", r.text
    assert (await ipub.get_user(S, target.id)).status == "active"  # type: ignore[union-attr]


# --------------------------------------------------------------------------- MFA reset (dual control)


async def test_mfa_reset_success_and_failure_rollback(admin_fs: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    import app.modules.admin.accounts as acc

    http = admin_fs
    target = await fs_user("lost@x.in", totp_secret=pyotp.random_base32())
    t_session = await sign_in(http, target, browser=http.fork())
    await admin(http, "maker@x.in")
    r = await http.post(
        f"/admin/users/{target.id}/mfa-reset",
        {"reason": "lost phone, verified on video", "verification_method": "video_call"},
        headers=_idem(),
    )
    assert r.status_code == 202, r.text
    approval_id = r.json()["approval_request_id"]
    r = await http.post(
        f"/admin/users/{target.id}/mfa-reset",
        {"reason": "lost phone, verified on video", "verification_method": "video_call"},
        headers=_idem(),
    )
    assert r.status_code == 409, r.text  # one pending reset per user
    await admin(http, "checker@x.in")
    audit0 = await _audit_actions()

    real = _fail_on(monkeypatch, "admin.user.mfa_reset")
    code = await _post(http, f"/admin/approvals/{approval_id}/approve", {"note": "ok"}, _idem())
    assert code == 500
    assert [f.factor_type for f in await ipub.active_factors(S, target.id)] == ["totp"]
    assert (await spub.get_session(S, t_session.id)).status == "active"  # type: ignore[union-attr]
    req = await rbac_public.get_approval(S, uuid.UUID(approval_id))
    assert req is not None and req.status == "pending" and req.decided_by is None
    assert await _audit_actions() == audit0
    acc.audit = real

    r = await http.post(f"/admin/approvals/{approval_id}/approve", {"note": "ok"}, headers=_idem())
    assert r.status_code == 200 and r.json()["status"] == "executed", r.text
    assert r.json()["result"]["factors_removed"] == 1
    assert await ipub.active_factors(S, target.id) == []
    assert (await spub.get_session(S, t_session.id)).status == "revoked"  # type: ignore[union-attr]
    assert {"admin.user.mfa_reset", "approval.executed"} <= set(await _audit_actions())


# --------------------------------------------------------------------------- break-glass


async def _break_glass(holder: Any) -> tuple[uuid.UUID, uuid.UUID]:
    """An active break-glass session with its elevated grant (as activation creates them)."""
    from app.modules.rbac.models import RoleGrant
    from app.modules.rbac.repo_firestore import system_repo as rbac_repo

    role = await rbac_repo().role_by_key("super_admin")
    assert role is not None
    g = await rbac_repo().create_grant(
        RoleGrant(id=uuid7(), user_id=holder.id, role_id=role.id, scope_type="platform", granted_by=uuid7()),
        "super_admin",
    )
    now = clock.now()
    bid = uuid7()
    doc = {
        "id": str(bid),
        "user_id": str(holder.id),
        "reason": "prod incident",
        "elevated_role": "super_admin",
        "role_grant_id": str(g.id),
        "status": "active",
        "started_at": now,
        "expires_at": now + timedelta(hours=1),
        "ended_at": None,
        "end_reason": None,
        "ended_by": None,
        "review_due_at": None,
        "reviewed_by": None,
        "reviewed_at": None,
        "review_note": None,
        "created_at": now,
        "updated_at": now,
    }
    await ScopedStore.system("test.seed").import_documents("break_glass_sessions", [(str(bid), doc)])
    return bid, g.id


async def test_break_glass_end_review_and_failure_rollback(
    admin_fs: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.modules.admin.accounts as acc

    http = admin_fs
    holder = await fs_user("oncall@x.in")
    await admin(http, "lead@x.in")
    bid, gid = await _break_glass(holder)
    audit0 = await _audit_actions()

    real = _fail_on(monkeypatch, "admin.break_glass.ended")
    code = await _post(http, f"/admin/break-glass/{bid}/end", {"note": "done"}, _idem())
    assert code == 500
    bg = (await ScopedStore.system("t").get("break_glass_sessions", str(bid))).data  # type: ignore[union-attr]
    assert bg["status"] == "active" and bg["ended_at"] is None
    g = await rbac_public.get_grant(S, gid)
    assert g is not None and g.revoked_at is None  # the elevated grant was restored
    assert await _audit_actions() == audit0
    acc.audit = real

    r = await http.post(f"/admin/break-glass/{bid}/end", {"note": "done"}, headers=_idem())
    assert r.status_code == 200 and r.json()["status"] == "ended", r.text
    assert (await rbac_public.get_grant(S, gid)).revoked_at is not None  # type: ignore[union-attr]

    _fail_on(monkeypatch, "admin.break_glass.reviewed")
    code = await _post(http, f"/admin/break-glass/{bid}/review", {"note": "reviewed fine"}, _idem())
    assert code == 500
    bg = (await ScopedStore.system("t").get("break_glass_sessions", str(bid))).data  # type: ignore[union-attr]
    assert bg["reviewed_at"] is None
    acc.audit = real
    r = await http.post(f"/admin/break-glass/{bid}/review", {"note": "reviewed fine"}, headers=_idem())
    assert r.status_code == 200, r.text
    bg = (await ScopedStore.system("t").get("break_glass_sessions", str(bid))).data  # type: ignore[union-attr]
    assert bg["reviewed_at"] is not None
