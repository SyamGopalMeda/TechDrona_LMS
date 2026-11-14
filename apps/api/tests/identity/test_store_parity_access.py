"""Postgres -> Firestore parity for the access modules (needs Postgres AND the emulator).

Backfills identity, sessions, rbac and orgs from the migrated (and dev-seeded) Postgres test
database, verifies every collection, and checks the Firestore service paths return what the
Postgres paths return for the same rows. Written 2026-11-12 by the data-access agent; NOT yet
executed (Postgres was down during that run) — see docs/firebase/agents/data-access.md.
"""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import select

from app.core.db import system_context
from app.modules.identity import service as ids
from app.modules.identity.models import User
from app.modules.rbac import service as rbac
from tests.firestore.matrix import activate_firestore

MODULES = ("identity", "sessions", "rbac", "orgs")


@pytest.fixture
async def seeded(db: Any) -> Any:
    from tests.identity.factory import make_user

    await system_context(db, "test.parity")
    u = await make_user(db, email="parity@x.in", password="correct horse battery", with_totp=True)
    await db.flush()
    return u


async def test_backfill_verify_and_service_parity(
    request: pytest.FixtureRequest, db: Any, monkeypatch: pytest.MonkeyPatch, seeded: Any
) -> None:
    from app.core.firestore.backfill import verify

    await system_context(db, "test.parity")
    users = (await db.execute(select(User).where(User.deleted_at.is_(None)))).scalars().all()
    pg_perms = await rbac.role_permission_map(db)
    pg = {
        u.email: (await ids.current_consents(db, u.id), [f.id for f in await ids.active_factors(db, u.id)])
        for u in users
        if u.email
    }
    pg_grants = {u.id: sorted(g.id for g in await rbac.active_grants(db, u.id)) for u in users}
    rbac.reset_role_permission_cache()

    restore = await activate_firestore(request, db, monkeypatch, MODULES)
    try:
        for m in MODULES:
            reports = await verify(db, m)
            assert all(r.ok for r in reports), [r.as_dict() for r in reports if not r.ok]
        assert await rbac.role_permission_map(None) == pg_perms  # type: ignore[arg-type]
        for email, (consents, factors) in pg.items():
            fu = await ids.find_user(None, "email", email)  # type: ignore[arg-type]
            assert fu is not None
            assert await ids.current_consents(None, fu.id) == consents  # type: ignore[arg-type]
            assert [f.id for f in await ids.active_factors(None, fu.id)] == factors  # type: ignore[arg-type]
            assert sorted(g.id for g in await rbac.active_grants(None, fu.id)) == pg_grants[fu.id]  # type: ignore[arg-type]
        cred = await ids.get_credential(None, seeded.id)  # type: ignore[arg-type]
        assert cred is not None and await ids.check_password(cred, "correct horse battery")
    finally:
        rbac.reset_role_permission_cache()
        await restore()
