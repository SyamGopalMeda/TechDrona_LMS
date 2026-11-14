"""Admin module on Firestore with NO Postgres and every module switch on ``firestore`` (the final
stack): dashboard, user search / detail / create (incl. failure rollback), courses overview,
policy settings + ``policy.change`` through dual control (incl. failure rollback) and the
break-glass expiry job (incl. failure rollback). Uses the access-module HTTP harness."""

from __future__ import annotations

import json
import uuid
from datetime import timedelta
from typing import Any

import pytest

import app.core.firestore.core_store
import app.modules.admin.store_specs
import app.modules.audit.store_specs  # noqa: F401 - registers the collections scanned below
from app.core.firestore.store import ScopedStore
from app.core.ids import uuid7
from app.modules.identity import clock
from app.modules.identity import public as ipub
from app.modules.rbac import public as rbac_public
from tests.firestore.conftest import fs_client  # noqa: F401
from tests.identity.fs.conftest import fs, fs_user, http  # noqa: F401
from tests.identity.fs.test_http_sessions_rbac import admin

S: Any = None


@pytest.fixture
def admin_http(http: Any, monkeypatch: pytest.MonkeyPatch) -> Any:  # noqa: F811
    """Every ``TD_STORE_<MODULE>=firestore`` (no Postgres anywhere)."""
    from app.core.firestore.backend import MODULES, reset_store_backends

    for m in MODULES:
        monkeypatch.setenv(f"TD_STORE_{m.upper()}", "firestore")
    reset_store_backends()
    return http


def _idem() -> dict[str, str]:
    return {"Idempotency-Key": uuid.uuid4().hex}


async def _scan(coll: str) -> list[dict[str, Any]]:
    return [d.data for d in await ScopedStore.system("test.scan").scan(coll)]


async def _audit_actions() -> list[str]:
    return sorted(json.loads(d["record_json"])["action"] for d in await _scan("audit_outbox"))


def _fail_on(monkeypatch: pytest.MonkeyPatch, module: Any, action: str) -> Any:
    real = module.audit

    async def boom(session: Any, actor: Any, act: str, *a: Any, **kw: Any) -> Any:
        if act == action:
            raise RuntimeError("forced failure after the action's writes")
        return await real(session, actor, act, *a, **kw)

    monkeypatch.setattr(module, "audit", boom)
    return real


async def _post_failing(http: Any, path: str, body: dict[str, Any]) -> int:  # noqa: F811
    try:
        r = await http.post(path, body, headers=_idem())
    except RuntimeError as e:
        assert "forced failure" in str(e)
        return 500
    return int(r.status_code)


# --------------------------------------------------------------------------- reads


async def test_dashboard_search_detail_and_overview(admin_http: Any) -> None:
    http = admin_http  # noqa: F811 - the fixture is imported for pytest; this is the Browser
    learner = await fs_user("learner@x.in", full_name="Lena Learner")
    await fs_user("old@x.in")
    boss, _ = await admin(http, "boss@x.in")

    r = await http.get("/admin/dashboard")
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["users"]["active"] == 3 and d["users"]["total"] == 3
    assert d["learning"]["learners"] == 2  # the admin holds a staff role
    assert d["sessions"]["active"] == 1
    assert d["commerce"] == {"paid_orders_30d": 0, "revenue_paise_30d": 0}

    r = await http.get("/admin/users", params={"q": "lena"})
    assert r.status_code == 200, r.text
    assert [x["user_id"] for x in r.json()["data"]] == [str(learner.id)]
    r = await http.get("/admin/users", params={"status": "current", "limit": 2})
    assert r.status_code == 200 and len(r.json()["data"]) == 2 and r.json()["page"]["has_more"], r.text
    nxt = r.json()["page"]["next_cursor"]
    r = await http.get("/admin/users", params={"status": "current", "limit": 2, "cursor": nxt})
    assert r.status_code == 200 and len(r.json()["data"]) == 1, r.text

    r = await http.get(f"/admin/users/{boss.id}")
    assert r.status_code == 200, r.text
    body = r.json()
    assert [g["role"] for g in body["grants"]] == ["super_admin"]
    assert body["mfa"]["enrolled"] is True and body["sessions"]["active"] == 1

    r = await http.get("/admin/courses/overview")
    assert r.status_code == 200, r.text
    assert r.json()["totals"]["courses"] == 0


async def test_dashboard_headline_counts_leave_out_synthetic_accounts(admin_http: Any) -> None:
    """Live audit 2026-11-14 #9: QA accounts (``is_synthetic``) are not "new registrations",
    "learners" or "signed in now"."""
    from app.modules.identity.repo_firestore import system_repo as irepo
    from tests.identity.fs.test_http_sessions_rbac import sign_in

    http = admin_http  # noqa: F811
    await fs_user("real@x.in")
    qa = await fs_user("qa-student@qa.techdrona.test")
    await irepo().update_user(qa.id, is_synthetic=True)
    await sign_in(http, qa, browser=http.fork())  # the QA account is signed in elsewhere
    await admin(http, "boss2@x.in")

    r = await http.get("/admin/dashboard")
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["sessions"]["active"] == 1  # the admin's own session, not the QA one
    assert d["users"]["new_7d"] == 2 and d["users"]["new_30d"] == 2  # real@ + the admin
    assert d["learning"]["learners"] == 1
    assert d["users"]["total"] == 3  # totals still count every account


# --------------------------------------------------------------------------- create user


async def test_create_user_and_failure_rollback(admin_http: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    import app.modules.admin.accounts as acc

    http = admin_http  # noqa: F811 - the fixture is imported for pytest; this is the Browser
    await admin(http, "boss2@x.in")
    body = {
        "full_name": "New Trainer",
        "email": "trainer@x.in",
        "password": "Correct-horse-battery-9",
        "role_key": "content_manager",
        "reason": "new hire",
        "confirm_adult": True,
    }
    real = _fail_on(monkeypatch, acc, "admin.user.created")
    assert await _post_failing(http, "/admin/users", body) == 500
    assert await ipub.find_user(S, "email", "trainer@x.in") is None  # user, profile, lookup undone
    acc.audit = real

    r = await http.post("/admin/users", body, headers=_idem())
    assert r.status_code == 201, r.text
    uid = uuid.UUID(r.json()["user_id"])
    assert r.json()["role"]["status"] == "granted"
    u = await ipub.find_user(S, "email", "trainer@x.in")
    assert u is not None and u.id == uid and u.account_origin == "staff_created"
    assert [k for _g, k in await rbac_public.live_grants(S, user_ids=[uid])] == ["content_manager"]
    assert (await ipub.get_profile(S, uid)).full_name == "New Trainer"  # type: ignore[union-attr]
    r = await http.post("/admin/users", body, headers=_idem())
    assert r.status_code == 422, r.text  # already registered


# --------------------------------------------------------------------------- policy.change


async def test_policy_change_dual_control_and_failure_rollback(
    admin_http: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.modules.admin.router as admin_router

    http = admin_http  # noqa: F811 - the fixture is imported for pytest; this is the Browser
    await admin(http, "maker@x.in")
    r = await http.get("/admin/policy-settings")
    assert r.status_code == 200, r.text
    key = "sessions.student.max_concurrent"
    r = await http.post(
        f"/admin/policy-settings/{key}/changes", {"value": 3, "change_reason": "exam season"}, headers=_idem()
    )
    assert r.status_code == 202, r.text
    first = r.json()["approval_request_id"]
    await admin(http, "checker@x.in")
    r = await http.post(f"/admin/approvals/{first}/approve", {"note": "ok"}, headers=_idem())
    assert r.status_code == 200 and r.json()["result"]["version"] == 1, r.text

    # second change fails after the policy write: version 1 stays active, no version 2, pending
    await admin(http, "maker2@x.in")
    r = await http.post(
        f"/admin/policy-settings/{key}/changes", {"value": 4, "change_reason": "more exams"}, headers=_idem()
    )
    assert r.status_code == 202, r.text
    second = r.json()["approval_request_id"]
    await admin(http, "checker2@x.in")
    audit0 = await _audit_actions()
    real = _fail_on(monkeypatch, admin_router, "policy.change")
    assert await _post_failing(http, f"/admin/approvals/{second}/approve", {"note": "ok"}) == 500
    r = await http.get(f"/admin/policy-settings/{key}")
    assert r.status_code == 200, r.text
    hist = r.json()["history"]
    assert [(h["version"], h["value"], h["is_active"]) for h in hist] == [(1, 3, True)], hist
    req = await rbac_public.get_approval(S, uuid.UUID(second))
    assert req is not None and req.status == "pending"
    assert await _audit_actions() == audit0
    admin_router.audit = real

    r = await http.post(f"/admin/approvals/{second}/approve", {"note": "ok"}, headers=_idem())
    assert r.status_code == 200 and r.json()["result"]["version"] == 2, r.text
    hist = (await http.get(f"/admin/policy-settings/{key}")).json()["history"]
    assert sorted((h["version"], h["is_active"]) for h in hist) == [(1, False), (2, True)]


# --------------------------------------------------------------------------- break-glass expiry job


async def _expired_break_glass(holder: Any) -> tuple[uuid.UUID, uuid.UUID]:
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
        "reason": "incident",
        "elevated_role": "super_admin",
        "role_grant_id": str(g.id),
        "status": "active",
        "started_at": now - timedelta(hours=2),
        "expires_at": now - timedelta(minutes=1),
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


async def test_break_glass_expiry_job_and_failure_rollback(
    admin_http: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.modules.admin.accounts as acc
    from app.modules.admin.tasks import break_glass_expiry

    await admin(admin_http, "lead@x.in")  # an alert recipient
    holder = await fs_user("oncall@x.in")
    bid, gid = await _expired_break_glass(holder)

    real = _fail_on(monkeypatch, acc, "admin.break_glass.expired")
    with pytest.raises(RuntimeError):
        await break_glass_expiry()
    bg = (await ScopedStore.system("t").get("break_glass_sessions", str(bid))).data  # type: ignore[union-attr]
    assert bg["status"] == "active"
    assert (await rbac_public.get_grant(S, gid)).revoked_at is None  # type: ignore[union-attr]
    assert "admin.break_glass.expired" not in await _audit_actions()
    acc.audit = real

    assert await break_glass_expiry() == 1
    bg = (await ScopedStore.system("t").get("break_glass_sessions", str(bid))).data  # type: ignore[union-attr]
    assert bg["status"] == "expired" and bg["end_reason"] == "expired"
    assert (await rbac_public.get_grant(S, gid)).revoked_at is not None  # type: ignore[union-attr]
    assert "admin.break_glass.expired" in await _audit_actions()
    assert await break_glass_expiry() == 0


async def test_set_password_flags_and_retention(admin_http: Any) -> None:
    http = admin_http  # noqa: F811 - the fixture is imported for pytest; this is the Browser
    target = await fs_user("forgot@x.in")
    await admin(http, "boss3@x.in")
    r = await http.post(
        f"/admin/users/{target.id}/password",
        {"password": "Another-long-passphrase-7", "reason": "no email yet", "must_change_password": True},
        headers=_idem(),
    )
    assert r.status_code == 200 and r.json()["must_change_password"] is True, r.text
    cred = await ipub.get_credential(S, target.id)
    from app.modules.identity.service import check_password

    assert cred is not None and await check_password(cred, "Another-long-passphrase-7")
    assert (await ipub.get_user(S, target.id)).must_change_password is True  # type: ignore[union-attr]
    r = await http.get("/admin/feature-flags")
    assert r.status_code == 200, r.text
    r = await http.get("/admin/retention-policies")
    assert r.status_code == 200, r.text
    r = await http.get("/admin/approvals")
    assert r.status_code == 200, r.text


async def test_admin_can_set_another_admins_password(admin_http: Any) -> None:
    """Owner decision 2026-11-14: any Admin may set another Admin's password (audited; never their own)."""
    http = admin_http  # noqa: F811
    other = await fs_user("other-admin@x.in", roles=("super_admin",))
    me, _ = await admin(http, "boss4@x.in")
    r = await http.post(
        f"/admin/users/{other.id}/password",
        {"password": "Another-long-passphrase-8", "reason": "admin locked out"},
        headers=_idem(),
    )
    assert r.status_code == 200 and r.json()["password_set"] is True, r.text
    cred = await ipub.get_credential(S, other.id)
    from app.modules.identity.service import check_password

    assert cred is not None and await check_password(cred, "Another-long-passphrase-8")
    own = await http.post(
        f"/admin/users/{me.id}/password",
        {"password": "Another-long-passphrase-9", "reason": "Resetting my own password"},
        headers=_idem(),
    )
    assert own.status_code == 403 and own.json()["code"] == "sod_violation"


async def test_public_active_policy_setting(admin_http: Any) -> None:
    """``admin.public.active_policy_setting(s)``: the store-neutral read security uses."""
    from app.modules.admin import public as admin_public

    key = "sessions.student.max_concurrent"
    assert await admin_public.active_policy_setting(S, key) is None
    for v in (3, 4):
        await admin_public.write_setting(S, key=key, scope_type="platform", scope_id=None, value=v,
                                         changed_by=uuid7(), change_reason="test")  # fmt: skip
    row = await admin_public.active_policy_setting(S, key)
    assert row is not None and row.value == 4 and row.version == 2 and row.is_active
    got = await admin_public.active_policy_settings(S, [key, "otp.ttl_seconds"])
    assert list(got) == [key] and got[key].value == 4


async def test_flag_and_retention_lists_use_the_database_collation(admin_http: Any) -> None:
    """``/admin/feature-flags`` and ``/admin/retention-policies`` order like Postgres
    (``ORDER BY flag_key`` / ``table_name`` with en_US), not Firestore's raw-byte order."""
    from app.core.firestore.collation import sort_key
    from app.modules.admin.store_specs import FLAGS, RETENTION, RetentionRow

    http = admin_http  # noqa: F811
    await admin(http, "boss9@x.in")
    st = ScopedStore.system("test.seed")
    keys = ["coop_beta", "co_op", "Co_op_upper", "coop", "co-op", "a_b", "ab", "aa_z"]
    now = clock.now()
    await st.delete_all(FLAGS)
    await st.import_documents(
        FLAGS,
        [
            (
                k,
                {"id": str(uuid7()), "flag_key": k, "description": k, "is_enabled": False,
                 "rollout_percent": 0, "user_allowlist": [], "updated_by": None,
                 "created_at": now, "updated_at": now},
            )
            for k in keys
        ],
    )  # fmt: skip
    r = await http.get("/admin/feature-flags")
    assert r.status_code == 200, r.text
    got = [f["flag_key"] for f in r.json()["data"]]
    assert got == sorted(keys, key=sort_key)
    assert got != sorted(keys)  # the byte order really differs for these keys

    tables = ["login_attempts", "loginattempts", "Login_x", "a_b", "ab"]
    await st.import_documents(
        RETENTION,
        [
            (
                str(uuid7()),
                RetentionRow(id=uuid7(), data_category="c", table_name=t, retention_class="R", retention_interval=None,
                             basis="b", deletion_method="d", legal_hold_aware=True, job_name="j",
                             owner_module="m", is_active=True, updated_by=None, created_at=now,
                             updated_at=now).doc(),
            )
            for t in tables
        ],
    )  # fmt: skip
    r = await http.get("/admin/retention-policies")
    assert r.status_code == 200, r.text
    got_t = [x["table_name"] for x in r.json()["data"] if x["table_name"] in tables]
    assert got_t == sorted(tables, key=sort_key)
