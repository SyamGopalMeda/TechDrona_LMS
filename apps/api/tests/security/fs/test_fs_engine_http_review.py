"""Security pass 2: the evaluations review route (``engine.evaluations_for``) and the timeline
route reading engine output, through the FastAPI app on Firestore with no Postgres."""

from __future__ import annotations

from typing import Any

from app.core.db import NO_POSTGRES
from app.core.ids import uuid7
from app.modules.identity import clock
from app.modules.identity import public as idp
from app.modules.identity.models import User
from app.modules.security import engine

FS_MODULES = ("security", "identity", "sessions", "admin", "audit", "core", "notifications", "rbac", "orgs")


async def test_evaluations_route_lists_engine_rows(fs_http: Any, make_principal: Any) -> None:
    client, _rec, auth = fs_http
    uid = uuid7()
    now = clock.now()
    await idp.create_user(
        NO_POSTGRES,
        User(
            id=uid,
            email=f"e{uid.hex[-8:]}@example.com",
            email_verified_at=now,
            status="active",
            is_minor=False,
            age_verified_at=now,
            age_verification_method="self_declared",
        ),
    )
    for rule in ("TO-07", "TO-09"):
        await engine.record_signal(NO_POSTGRES, rule_key=rule, user_id=uid, source="login")
    ev = await engine.evaluate_takeover(NO_POSTGRES, uid, trigger="login")
    assert ev is not None
    p = make_principal(is_platform=True, roles=("super_admin",), tier="privileged", last_step_up_at=now)
    auth.grant(p, "security.evidence.read")
    h = auth.login(p)
    r = await client.get(
        "/api/v1/security/evaluations", params={"user_id": str(uid), "reason_code": "case_review"}, headers=h
    )
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert len(data) == 1
    e = data[0]
    assert e["id"] == str(ev.id) and e["family"] == "takeover" and e["trigger"] == "login"
    assert e["score"] == 30.0 and e["previous_score"] == 0.0 and e["action"] == "none"
    assert e["repeat_multiplier"] == 1.0 and e["subtotals"] == {"T": 30.0}
    assert sorted(c["rule"] for c in e["signals"]) == ["TO-07", "TO-09"]
    r = await client.get(
        "/api/v1/security/evaluations",
        params={"user_id": str(uid), "reason_code": "case_review", "family": "sharing"},
        headers=h,
    )
    assert r.status_code == 200 and r.json()["data"] == []
