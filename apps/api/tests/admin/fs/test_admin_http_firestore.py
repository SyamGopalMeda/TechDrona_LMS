"""Admin routes through the FastAPI app on Firestore with no Postgres (request session is
``NO_POSTGRES``): privacy requests end to end, feature flags, retention, break-glass, dashboard
pieces owned by data-ops. Identity/sessions/security reads go through their ``public`` APIs."""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any

from app.core.firestore.store import ScopedStore
from app.core.ids import uuid7
from app.modules.admin import store_specs as sp
from app.modules.audit.repo_firestore import sealer_repo
from app.modules.identity import clock

FS_MODULES = ("admin", "audit", "core", "identity", "sessions", "security", "rbac", "notifications")
P = "/api/v1"


def _idem() -> dict[str, str]:
    return {"Idempotency-Key": str(uuid.uuid4())}


def _staff(make_principal: Any, auth: Any, *perms: str) -> dict[str, str]:
    p = make_principal(
        is_platform=True,
        roles=("super_admin",),
        tier="privileged",
        last_step_up_at=clock.now(),
        is_minor=False,
    )
    for perm in perms:
        auth.grant(p, perm)
    return auth.login(p)


async def test_privacy_request_lifecycle(fs_http: Any, make_principal: Any) -> None:
    client, _rec, auth = fs_http
    learner = make_principal(is_minor=False)
    hl = auth.login(learner)
    hs = _staff(make_principal, auth, "privacy.request.process")

    r = await client.post(
        f"{P}/me/privacy-requests", json={"request_type": "access_export"}, headers={**hl, **_idem()}
    )
    assert r.status_code == 201, r.text
    rid = r.json()["request_id"]
    assert r.json()["status"] == "in_progress" and r.json()["export_available"] is False
    g = await client.post(
        f"{P}/me/privacy-requests",
        json={"request_type": "grievance", "details": "Slow"},
        headers={**hl, **_idem()},
    )
    assert g.status_code == 201
    mine = (await client.get(f"{P}/me/privacy-requests", headers=hl)).json()["data"]
    assert [x["request_id"] for x in mine] == [g.json()["request_id"], rid]
    other = auth.login(make_principal())
    assert (await client.get(f"{P}/me/privacy-requests/{rid}", headers=other)).status_code == 404
    assert (await client.get(f"{P}/me/privacy-requests/{rid}/export", headers=hl)).status_code == 409

    queue = (await client.get(f"{P}/admin/privacy-requests", headers=hs)).json()["data"]
    assert {x["request_id"] for x in queue} == {rid, g.json()["request_id"]}
    assert all("overdue" in x for x in queue)
    detail = await client.get(f"{P}/admin/privacy-requests/{rid}", headers=hs)
    assert detail.status_code == 200 and detail.json()["user_id"] == str(learner.user_id)
    v = await client.post(
        f"{P}/admin/privacy-requests/{rid}/verify-identity", json={"method": "manual"}, headers=hs
    )
    assert v.status_code == 200 and v.json()["identity_verification_method"] == "manual"
    done = await client.post(
        f"{P}/admin/privacy-requests/{rid}/complete",
        json={"response_summary": "Export generated"},
        headers={**hs, **_idem()},
    )
    assert done.status_code == 200, done.text
    assert done.json()["status"] == "completed" and done.json()["export_available"] is True
    exp = await client.get(f"{P}/me/privacy-requests/{rid}/export", headers=hl)
    assert exp.status_code == 200 and exp.json()["account"]["user_id"] == str(learner.user_id)
    assert {"consents", "sessions", "devices", "restrictions", "unblock_requests"} <= exp.json().keys()
    w = await client.post(f"{P}/me/privacy-requests/{rid}/withdraw", headers=hl)
    assert w.status_code == 409 and w.json()["code"] == "invalid_state_transition"
    rej = await client.post(
        f"{P}/admin/privacy-requests/{g.json()['request_id']}/reject",
        json={"reason": "Duplicate"},
        headers=hs,
    )
    assert rej.status_code == 200 and rej.json()["status"] == "rejected"
    # the audit trail of every step reached the Firestore chain
    assert await sealer_repo().seal_pending(100) >= 6
    assert (
        await ScopedStore.system("t").count("privacy_requests", filters=(("status", "==", "completed"),))
    ) == 1


async def test_daily_create_limit(fs_http: Any, make_principal: Any) -> None:
    client, _rec, auth = fs_http
    h = auth.login(make_principal(is_minor=False))
    for _ in range(3):
        r = await client.post(
            f"{P}/me/privacy-requests", json={"request_type": "grievance"}, headers={**h, **_idem()}
        )
        assert r.status_code == 201
    r = await client.post(
        f"{P}/me/privacy-requests", json={"request_type": "grievance"}, headers={**h, **_idem()}
    )
    assert r.status_code == 429 and r.json()["code"] == "rate_limited"


async def test_flags_retention_break_glass(fs_http: Any, make_principal: Any) -> None:
    client, _rec, auth = fs_http
    st = ScopedStore.system("firestore.backfill")
    await st.import_documents(
        sp.FLAGS,
        [
            (
                "x.demo",
                {
                    "id": str(uuid7()),
                    "flag_key": "x.demo",
                    "description": "d",
                    "is_enabled": False,
                    "rollout_percent": 0,
                    "user_allowlist": [],
                    "updated_by": None,
                },
            )
        ],
    )
    ret = sp.RetentionRow.from_pg(
        {
            "id": uuid7(),
            "table_name": "login_attempts",
            "retention_interval": timedelta(days=90),
            "data_category": "security",
            "retention_class": "R-SEC",
            "basis": "b",
            "deletion_method": "drop_partition",
            "job_name": "j",
            "owner_module": "sessions",
            "legal_hold_aware": True,
            "is_active": True,
        }
    )
    await st.import_documents(sp.RETENTION, [(str(ret.id), ret.doc())])
    bg = sp.BreakGlassRow(
        id=uuid7(),
        user_id=uuid7(),
        reason="r" * 30,
        status="ended",
        started_at=clock.now() - timedelta(days=1),
        expires_at=clock.now() - timedelta(hours=20),
        ended_at=clock.now() - timedelta(hours=20),
        created_at=clock.now(),
        updated_at=clock.now(),
    )
    await st.import_documents(sp.BREAK_GLASS, [(str(bg.id), bg.doc())])

    h = _staff(make_principal, auth, "feature_flag.manage", "audit.read", "breakglass.activate")
    flags = (await client.get(f"{P}/admin/feature-flags", headers=h)).json()["data"]
    assert [f["flag_key"] for f in flags] == ["x.demo"]
    pt = await client.patch(
        f"{P}/admin/feature-flags/x.demo", json={"is_enabled": True, "rollout_percent": 50}, headers=h
    )
    assert pt.status_code == 200 and pt.json()["is_enabled"] is True and pt.json()["rollout_percent"] == 50
    assert (
        await client.patch(f"{P}/admin/feature-flags/nope", json={"is_enabled": True}, headers=h)
    ).status_code == 404
    rp = (await client.get(f"{P}/admin/retention-policies", headers=h)).json()["data"]
    assert rp[0]["table_name"] == "login_attempts" and rp[0]["retention_days"] == 90
    lst = (await client.get(f"{P}/admin/break-glass", headers=h)).json()
    assert [x["break_glass_id"] for x in lst["data"]] == [str(bg.id)] and lst["active"] is None
    assert lst["data"][0]["review_status"] == "pending"
    rv = await client.post(
        f"{P}/admin/break-glass/{bg.id}/review", json={"note": "Justified by INC-1"}, headers=h
    )
    assert rv.status_code == 200 and rv.json()["review_status"] == "reviewed"
    again = await client.post(
        f"{P}/admin/break-glass/{bg.id}/review", json={"note": "Second review"}, headers=h
    )
    assert again.status_code == 409


async def test_maintenance_flag_read_from_firestore(fs_http: Any, make_principal: Any) -> None:
    """Platform finding: the maintenance-mode middleware reads the flag from Firestore."""
    from app.modules.admin import flags

    client, _rec, auth = fs_http
    st = ScopedStore.system("firestore.backfill")
    doc = {
        "id": str(uuid7()),
        "flag_key": "platform.maintenance_mode",
        "description": "m",
        "is_enabled": True,
        "rollout_percent": 100,
        "user_allowlist": [],
        "updated_by": None,
    }
    await st.import_documents(sp.FLAGS, [("platform.maintenance_mode", doc)])
    flags.invalidate()
    try:
        h = auth.login(make_principal(is_minor=False))
        r = await client.post(
            f"{P}/me/privacy-requests", json={"request_type": "grievance"}, headers={**h, **_idem()}
        )
        assert r.status_code == 503 and r.json()["code"] == "maintenance"
        assert (
            await client.get(f"{P}/me/privacy-requests", headers=h)
        ).status_code == 200  # reads still work
    finally:
        flags.invalidate()
