"""SEC-01 learner status page through the FastAPI app on Firestore, no Postgres."""

from __future__ import annotations

from typing import Any

from app.core.audit import AuditActor
from app.core.db import NO_POSTGRES
from app.modules.identity import clock
from app.modules.identity import public as idp
from app.modules.identity.models import User
from app.modules.security import restrictions as rx

FS_MODULES = ("security", "identity", "sessions", "admin", "audit", "core")


async def test_my_security_status(fs_http: Any, make_principal: Any) -> None:
    client, _rec, auth = fs_http
    p = make_principal(is_minor=False)
    now = clock.now()
    await idp.create_user(
        NO_POSTGRES,
        User(
            id=p.user_id,
            email="s@example.com",
            email_verified_at=now,
            status="active",
            is_minor=False,
            age_verified_at=now,
            age_verification_method="self_declared",
        ),
    )
    h = auth.login(p)
    r = await client.get("/api/v1/me/security/status", headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["level"] == 0 and body["history"] == [] and body["takeover"]["protect_locked"] is False
    assert body["policy"]["max_trusted_devices"] is not None

    actor = AuditActor.system("test.security")
    _r1, _ = await rx.apply_restriction(
        NO_POSTGRES, user_id=p.user_id, level=1, family="sharing", source="engine", actor=actor
    )
    await rx.apply_restriction(
        NO_POSTGRES, user_id=p.user_id, level=2, family="sharing", source="engine", actor=actor
    )
    body = (await client.get("/api/v1/me/security/status", headers=h)).json()
    assert body["level"] == 2 and body["family"] == "sharing" and body["scope"] == "learning_access"
    assert [x["end_reason"] for x in body["history"]] == ["superseded"]
    assert body["available_actions"] == ["manage_devices", "contact_support"]


async def test_status_shows_the_session_cap_of_the_callers_tier(fs_http: Any, make_principal: Any) -> None:
    """Live re-check 2026-11-14 (N6): staff were shown the student cap (2); staff log in under
    ``sessions.staff.max_concurrent`` (3)."""
    client, _rec, auth = fs_http
    now = clock.now()
    caps = {}
    for tier in ("student", "staff"):
        p = make_principal(is_minor=False, tier=tier)
        await idp.create_user(
            NO_POSTGRES,
            User(
                id=p.user_id,
                email=f"{tier}@example.com",
                email_verified_at=now,
                status="active",
                is_minor=False,
                age_verified_at=now,
                age_verification_method="self_declared",
            ),
        )
        r = await client.get("/api/v1/me/security/status", headers=auth.login(p))
        assert r.status_code == 200, r.text
        caps[tier] = r.json()["policy"]["max_concurrent_sessions"]
    assert caps == {"student": 2, "staff": 3}
