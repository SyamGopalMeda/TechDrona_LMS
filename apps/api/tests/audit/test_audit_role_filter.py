"""ADM-14 (AUD-01, SoD-01): the audit log is filtered by role. Single company (owner decision D2):
the finance admin and security reviewer roles were folded into Admin, so ``super_admin`` reads
every event with the full IP, and any other holder of ``audit.read`` (including a stale token
carrying a removed role key) sees nothing."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.core.audit import AuditActor, audit
from app.core.ids import uuid7
from app.modules.audit.sealer import seal_once


async def _write(committed_engine: AsyncEngine, sealer_engine: AsyncEngine) -> str:
    """Three events sharing one unique action prefix: security, commerce and other."""
    m = uuid7().hex[:12]
    async with committed_engine.connect() as conn, conn.begin():
        s = AsyncSession(bind=conn)
        actor = AuditActor("user", user_id=uuid7(), session_id=uuid7(), roles=("super_admin",))
        await audit(s, actor, f"security.t{m}.viewed", "security_case", uuid7(), ip="203.0.113.9")
        await audit(s, actor, f"refund.t{m}.approved", "refund", uuid7(), ip="203.0.113.10")
        await audit(s, actor, f"identity.t{m}.changed", "user", uuid7(), ip="203.0.113.11")
        await s.close()
    while await seal_once(sealer_engine):
        pass
    return m


def _login(make_principal: Any, auth: Any, *roles: str) -> dict[str, str]:
    p = make_principal(is_platform=True, roles=roles, tier="privileged")
    auth.grant(p, "audit.read")
    return auth.login(p)


async def _rows(client: Any, h: dict[str, str], m: str) -> dict[str, dict[str, Any]]:
    out = {}
    for fam in ("security", "refund", "identity"):
        action = f"{fam}.t{m}." + {"security": "viewed", "refund": "approved", "identity": "changed"}[fam]
        r = await client.get("/api/v1/audit/events", params={"action": action}, headers=h)
        assert r.status_code == 200, r.text
        for row in r.json()["data"]:
            out[fam] = row
    return out


async def test_admin_sees_every_family_with_full_ip(
    client, db, auth, make_principal, committed_engine: AsyncEngine, sealer_engine: AsyncEngine
) -> None:
    m = await _write(committed_engine, sealer_engine)
    sa = _login(make_principal, auth, "super_admin")
    every = await _rows(client, sa, m)
    assert set(every) == {"security", "refund", "identity"}
    full = await client.get(f"/api/v1/audit/events/{every['refund']['seq']}", headers=sa)
    assert full.status_code == 200 and full.json()["ip"] == "203.0.113.10"
    sec = await client.get(f"/api/v1/audit/events/{every['security']['seq']}", headers=sa)
    assert sec.json()["ip"] == "203.0.113.9"


async def test_removed_roles_and_non_admins_see_nothing(
    client, db, auth, make_principal, committed_engine: AsyncEngine, sealer_engine: AsyncEngine
) -> None:
    m = await _write(committed_engine, sealer_engine)
    every = await _rows(client, _login(make_principal, auth, "super_admin"), m)
    for roles in (("security_reviewer",), ("finance_admin",), ("security_reviewer", "finance_admin"), ()):
        h = _login(make_principal, auth, *roles)
        assert await _rows(client, h, m) == {}, roles
        d = await client.get(f"/api/v1/audit/events/{every['refund']['seq']}", headers=h)
        assert d.status_code == 404, roles
