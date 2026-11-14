"""Break-glass end on the Firebase stack revokes the elevated grant through ``rbac.public``."""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any

from app.core.db import NO_POSTGRES
from app.core.firestore.store import ScopedStore
from app.core.ids import uuid7
from app.modules.admin import store_specs as sp
from app.modules.identity import clock

FS_MODULES = ("admin", "rbac", "identity", "sessions", "audit", "core", "notifications", "orgs")


async def test_end_revokes_grant_via_rbac_public(fs_http: Any, make_principal: Any) -> None:
    from app.modules.rbac import public as rbac_public
    from app.modules.rbac.models import RoleGrant
    from app.modules.rbac.service import reset_role_permission_cache
    from tests.identity.fs.conftest import seed_catalogue

    client, _rec, auth = fs_http
    await seed_catalogue()
    reset_role_permission_cache()
    holder = make_principal(
        is_platform=True, roles=("super_admin",), tier="privileged", last_step_up_at=clock.now()
    )
    auth.grant(holder, "breakglass.activate")
    from app.modules.identity import public as idp
    from app.modules.identity.models import User

    await idp.create_user(
        NO_POSTGRES,
        User(
            id=holder.user_id,
            email=f"h{uuid7().hex[-8:]}@example.com",
            email_verified_at=clock.now(),
            status="active",
            is_minor=False,
            age_verified_at=clock.now(),
            age_verification_method="self_declared",
        ),
    )
    role = await rbac_public.role_by_key(NO_POSTGRES, "super_admin")
    grant = RoleGrant(
        id=uuid7(),
        user_id=holder.user_id,
        role_id=role.id,
        scope_type="platform",
        granted_by=holder.user_id,
        granted_at=clock.now(),
        reason="break-glass",
    )
    await rbac_public.add_grant(NO_POSTGRES, grant, "super_admin")
    now = clock.now()
    bg = sp.BreakGlassRow(
        id=uuid7(),
        user_id=holder.user_id,
        reason="r" * 30,
        status="active",
        role_grant_id=grant.id,
        started_at=now - timedelta(minutes=5),
        expires_at=now + timedelta(hours=1),
        created_at=now,
        updated_at=now,
    )
    await ScopedStore.system("firestore.backfill").import_documents(sp.BREAK_GLASS, [(str(bg.id), bg.doc())])
    r = await client.post(
        f"/api/v1/admin/break-glass/{bg.id}/end",
        json={"note": "Resolved"},
        headers={**auth.login(holder), "Idempotency-Key": str(uuid.uuid4())},
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "ended"
    g = await rbac_public.get_grant(NO_POSTGRES, grant.id)
    assert g is not None and g.revoked_at is not None and g.revoked_by == holder.user_id
