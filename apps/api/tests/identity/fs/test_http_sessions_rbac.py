"""HTTP tests of the sessions and rbac routes on Firestore with no Postgres (``http`` fixture).

Sessions are minted directly (``sign_in``: device + session rows through the sessions service,
cookies handed to the ``Browser``) so these tests do not depend on the login route; the
resolver, permission checker, unit of work, audit and idempotency run for real.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

import pyotp

from app.modules.identity import clock
from app.modules.sessions import service as ss
from app.modules.sessions.repo_firestore import system_repo as sessions_repo
from app.modules.sessions.ua import parse_ua
from tests.identity.fs.conftest import fs_user, seed_catalogue

TIERS = {"super_admin": "privileged", "student": "student"}


async def sign_in(http: Any, user: Any, *, role: str = "student", browser: Any = None) -> Any:
    """An active session (+ trusted device) for ``user``; returns the Browser carrying it."""
    b = browser or http
    info = ss.ClientInfo(ip=b.ip, ua=parse_ua(b.ua), device_token=b.device)
    dev, raw, _new = await ss.resolve_device(None, info)  # type: ignore[arg-type]
    ud = await ss.ensure_user_device(None, user.id, dev)  # type: ignore[arg-type]
    await ss.trust_device(None, ud, None, owner_verified=False)  # type: ignore[arg-type]
    staff = role != "student"
    s, token = await ss.create_session(
        None,  # type: ignore[arg-type]
        user_id=user.id,
        tier=TIERS[role],
        status="active",
        created_via="password",
        info=info,
        device=dev,
        user_device=ud,
        amr=["pwd", "totp"] if staff else ["pwd"],
        aal=2 if staff else 1,
    )
    if staff:  # fresh step-up for the P5 / staff step-up checks
        s.last_step_up_at = clock.now()
        await sessions_repo().save_session(s)
    b.session, b.device = token, raw
    return s


async def admin(http: Any, email: str = "admin@x.in") -> Any:
    u = await fs_user(email, roles=("super_admin",), totp_secret=pyotp.random_base32())
    return u, await sign_in(http, u, role="super_admin")


# --------------------------------------------------------------------------- sessions (self)


async def test_my_sessions_devices_and_revocation(http: Any) -> None:
    u = await fs_user("me@x.in")
    other = http.fork(ua=http.ua)
    s_other = await sign_in(http, u, browser=other)
    s_me = await sign_in(http, u)

    r = await http.get("/me/sessions")
    assert r.status_code == 200, r.text
    ids = {x["session_id"]: x for x in r.json()["data"]}
    assert set(ids) == {str(s_me.id), str(s_other.id)} and ids[str(s_me.id)]["is_current"]

    r = await http.get("/me/devices")
    assert r.status_code == 200, r.text
    devs = r.json()["data"]
    assert len(devs) == 2 and r.json()["limits"]["cap_tier"] == "student"
    mine = next(d for d in devs if d["is_current"])
    r = await http.patch(f"/me/devices/{mine['user_device_id']}", {"user_label": "Laptop"})
    assert r.status_code == 200 and r.json()["user_label"] == "Laptop", r.text
    r = await http.get("/me/devices")
    assert (
        next(d for d in r.json()["data"] if d["is_current"])["user_label"] == "Laptop"
    )  # persisted (fs_uow)

    r = await http.get("/me/device-policy")
    assert r.status_code == 200 and r.json()["sessions"]["max_concurrent"] == 2, r.text

    await ss.record_login_attempt(
        None,  # type: ignore[arg-type]
        identifier=(1, b"\x01" * 32),
        user_id=u.id,
        outcome="success",
        info=ss.ClientInfo(ip="203.0.113.10", ua=parse_ua(http.ua), device_token=None),
    )
    r = await http.get("/me/login-history")
    assert r.status_code == 200 and [a["result"] for a in r.json()["attempts"]] == ["success"], r.text

    r = await http.delete(f"/me/sessions/{s_other.id}")
    assert r.status_code == 200 and r.json()["revoked"], r.text
    assert (await sessions_repo().get_session(s_other.id)).end_reason == "user_revoked_other"  # type: ignore[union-attr]
    r = await http.delete(f"/me/sessions/{uuid.uuid4()}")
    assert r.status_code == 404
    r = await other.get("/me/sessions")
    assert r.status_code == 401, r.text  # the revoked session is refused

    s3 = await sign_in(http, u, browser=http.fork(ua=http.ua))
    r = await http.post("/me/sessions/revoke-others")
    assert r.status_code == 200 and r.json()["revoked"] == 1, r.text
    assert (await sessions_repo().get_session(s3.id)).status == "revoked"  # type: ignore[union-attr]
    r = await http.get("/me/login-history")
    assert {e["session_id"] for e in r.json()["ended_sessions"]} >= {str(s_other.id), str(s3.id)}

    other_dev = next(d for d in devs if not d["is_current"])
    r = await http.delete(f"/me/devices/{other_dev['user_device_id']}")
    assert r.status_code == 200 and r.json()["removed"], r.text
    r = await http.get("/me/devices")
    left = [d["user_device_id"] for d in r.json()["data"]]
    assert mine["user_device_id"] in left and other_dev["user_device_id"] not in left
    r = await http.delete(f"/me/devices/{other_dev['user_device_id']}")
    assert r.status_code == 404


# --------------------------------------------------------------------------- sessions (staff)


async def test_admin_session_and_device_endpoints(http: Any) -> None:
    _a, _s = await admin(http)
    student = await fs_user("stu@x.in")
    sb = http.fork(ua=http.ua)
    s1 = await sign_in(http, student, browser=sb)

    r = await http.get(f"/users/{student.id}/sessions")
    assert (
        r.status_code == 400
        or r.status_code == 422
        or r.json().get("type", "").endswith("reason-code-required")
    )
    r = await http.get(f"/users/{student.id}/sessions", params={"reason_code": "ticket"})
    assert r.status_code == 200 and [x["session_id"] for x in r.json()["data"]] == [str(s1.id)], r.text
    r = await http.get(f"/users/{uuid.uuid4()}/sessions", params={"reason_code": "ticket"})
    assert r.status_code == 404

    r = await http.get(f"/users/{student.id}/devices", params={"reason_code": "ticket"})
    assert r.status_code == 200, r.text
    assert r.json()["limits"]["support_resets_used_30d"] == 0
    ud_id = r.json()["data"][0]["user_device_id"]

    r = await http.post(
        f"/users/{student.id}/sessions/revoke",
        {"session_id": str(uuid.uuid4()), "reason_code": "ticket", "reason": "lost phone"},
    )
    assert r.status_code == 404, r.text
    r = await http.post(
        f"/users/{student.id}/sessions/revoke",
        {"session_id": str(s1.id), "reason_code": "ticket", "reason": "lost phone"},
    )
    assert r.status_code == 200 and r.json()["revoked"] == 1, r.text

    s2 = await sign_in(http, student, browser=sb)
    r = await http.post(
        f"/users/{student.id}/sessions/revoke",
        {"all": True, "reason_code": "ticket", "reason": "compromised"},
    )
    assert r.status_code == 200 and r.json()["revoked"] == 1, r.text
    assert (await sessions_repo().get_session(s2.id)).end_reason == "admin_kill"  # type: ignore[union-attr]
    from app.modules.identity.repo_firestore import system_repo as identity_repo

    assert (await identity_repo().get_user(student.id)).sessions_valid_after is not None  # type: ignore[union-attr]

    r = await http.post(
        f"/users/{student.id}/devices/{ud_id}/reset", {"reason_code": "ticket", "reason": "new phone"}
    )
    assert r.status_code == 200 and r.json()["support_resets_used_30d"] == 1, r.text
    r = await http.post(
        f"/users/{student.id}/devices/{ud_id}/reset", {"reason_code": "ticket", "reason": "again"}
    )
    assert r.status_code == 404


async def test_staff_endpoints_denied_to_students(http: Any) -> None:
    await seed_catalogue()
    student = await fs_user("plain@x.in")
    await sign_in(http, student)
    r = await http.get(f"/users/{student.id}/sessions", params={"reason_code": "ticket"})
    assert r.status_code == 403, r.text
    r = await http.get("/rbac/roles")
    assert r.status_code == 403, r.text
    r = await http.get("/rbac/grants")
    assert r.status_code == 403, r.text
    r = await http.post(
        "/rbac/grants",
        {"user_id": str(student.id), "role_key": "trainer", "scope_type": "platform", "reason": "promote"},
        headers={"Idempotency-Key": "k-denied-0001"},
    )
    assert r.status_code == 403, r.text


# --------------------------------------------------------------------------- rbac


async def test_roles_permissions_grants_and_revoke(http: Any) -> None:
    a, _s = await admin(http)
    r = await http.get("/rbac/roles")
    assert r.status_code == 200, r.text
    keys = [x["role_key"] for x in r.json()["data"]]
    assert keys == sorted(keys) and "super_admin" in keys
    r = await http.get("/rbac/permissions")
    assert r.status_code == 200 and r.json()["data"], r.text

    target = await fs_user("t@x.in")
    tb = http.fork(ua=http.ua)
    ts = await sign_in(http, target, browser=tb)
    body = {
        "user_id": str(target.id),
        "role_key": "content_manager",
        "scope_type": "platform",
        "reason": "new cm",
    }
    r = await http.post("/rbac/grants", body, headers={"Idempotency-Key": "k-grant-00001"})
    assert r.status_code == 201, r.text
    gid = r.json()["grant_id"]
    replay = await http.post("/rbac/grants", body, headers={"Idempotency-Key": "k-grant-00001"})
    assert replay.status_code == 201 and replay.json()["grant_id"] == gid  # idempotent replay
    again = await http.post("/rbac/grants", body, headers={"Idempotency-Key": "k-grant-00002"})
    assert again.status_code == 409, again.text  # live grant exists
    assert (await sessions_repo().get_session(ts.id)).end_reason == "privilege_change"  # type: ignore[union-attr]

    r = await http.get("/rbac/grants", params={"user_id": str(target.id)})
    assert [g["grant_id"] for g in r.json()["data"]] == [gid], r.text
    r = await http.post(
        "/rbac/grants",
        {**body, "user_id": str(a.id)},
        headers={"Idempotency-Key": "k-grant-self1"},
    )
    assert r.status_code == 403 or r.status_code == 409, r.text  # SoD-05: no self-grant

    await sign_in(http, target, browser=tb)
    r = await tb.get("/me/grants")
    assert r.status_code == 200 and [g["role_key"] for g in r.json()["data"]] == ["content_manager"], r.text

    r = await http.post(f"/rbac/grants/{gid}/revoke", {"reason": "left the team"})
    assert r.status_code == 200 and r.json()["revoked"], r.text
    r = await http.post(f"/rbac/grants/{gid}/revoke", {"reason": "left the team"})
    assert r.status_code == 409, r.text
    r = await http.post(f"/rbac/grants/{uuid.uuid4()}/revoke", {"reason": "nothing"})
    assert r.status_code == 404
    r = await http.get("/rbac/grants", params={"user_id": str(target.id)})
    assert r.json()["data"] == []


async def test_privileged_grant_dual_control_single_execution(http: Any, monkeypatch: Any) -> None:
    from app.core.config import get_settings

    monkeypatch.setattr(type(get_settings()), "simple_auth", property(lambda _s: False))
    a1, _ = await admin(http, "a1@x.in")
    b2 = http.fork(ua=http.ua)
    a2 = await fs_user("a2@x.in", roles=("super_admin",), totp_secret=pyotp.random_base32())
    await sign_in(http, a2, role="super_admin", browser=b2)
    target = await fs_user("promoted@x.in")

    body = {
        "user_id": str(target.id),
        "role_key": "super_admin",
        "scope_type": "platform",
        "reason": "co-admin",
    }
    r = await http.post("/rbac/grants", body, headers={"Idempotency-Key": "k-priv-000001"})
    assert r.status_code == 202 and r.json()["status"] == "approval_pending", r.text
    apr_id = r.json()["approval_request_id"]

    r = await http.post(f"/rbac/approval-requests/{apr_id}/approve", {})
    assert r.status_code == 403, r.text  # maker != checker (a second admin exists)

    b3 = b2.fork(ua=b2.ua)
    await sign_in(http, a2, role="super_admin", browser=b3)
    res = await asyncio.gather(
        b2.post(f"/rbac/approval-requests/{apr_id}/approve", {"note": "ok"}),
        b3.post(f"/rbac/approval-requests/{apr_id}/approve", {"note": "ok"}),
    )
    codes = sorted(x.status_code for x in res)
    assert codes == [200, 409], [x.text for x in res]
    from app.modules.rbac.repo_firestore import system_repo as rbac_repo

    grants = await rbac_repo().active_grants(target.id, clock.now())
    assert [k for _g, k in grants] == ["super_admin"]  # executed exactly once
    stored = await rbac_repo().get_approval(uuid.UUID(apr_id))
    assert stored is not None and stored.status == "executed" and stored.executed_at is not None

    # reject path
    t2 = await fs_user("promoted2@x.in")
    r = await http.post(
        "/rbac/grants", {**body, "user_id": str(t2.id)}, headers={"Idempotency-Key": "k-priv-000002"}
    )
    apr2 = r.json()["approval_request_id"]
    r = await b2.post(f"/rbac/approval-requests/{apr2}/reject", {"note": "no"})
    assert r.status_code == 200 and r.json()["status"] == "rejected", r.text
    r = await b2.post(f"/rbac/approval-requests/{apr2}/approve", {})
    assert r.status_code == 409
    assert a1.id != a2.id
