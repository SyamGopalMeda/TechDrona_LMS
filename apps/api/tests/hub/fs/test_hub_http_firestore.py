"""Hub on the Firebase stack: no Postgres, identity on Firestore (``identity.public.get_user``)."""

from __future__ import annotations

from typing import Any

from app.core.db import NO_POSTGRES
from app.core.ids import uuid7
from app.modules.identity import clock
from app.modules.identity import public as idp
from app.modules.identity.models import User

FS_MODULES = ("identity", "audit", "core", "ai", "admin")


async def test_modules_and_integrations_without_postgres(
    fs_http: Any, make_principal: Any, monkeypatch: Any
) -> None:
    from app.core.config import reset_settings_cache

    monkeypatch.setenv("TD_WEBSITE_URL", "https://website.example")
    reset_settings_cache()
    client, _rec, auth = fs_http
    p = make_principal(roles=("student",))
    now = clock.now()
    await idp.create_user(
        NO_POSTGRES,
        User(
            id=p.user_id,
            email=f"u{uuid7().hex[-8:]}@example.com",
            email_verified_at=None,
            status="active",
            is_minor=False,
            age_verified_at=now,
            age_verification_method="self_declared",
        ),
    )
    r = await client.get("/api/v1/me/modules", headers=auth.login(p))
    assert r.status_code == 200, r.text
    assert [m["key"] for m in r.json()["modules"]] == ["lms"]  # e-mail not verified: no website module
    pub = await client.get("/api/v1/public/integrations")
    assert pub.status_code == 200 and "ai" in str(pub.json())
    monkeypatch.delenv("TD_WEBSITE_URL")
    reset_settings_cache()
