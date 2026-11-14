"""AUD-01..03 through the FastAPI app with TD_STORE_AUDIT=firestore and no Postgres."""

from __future__ import annotations

from typing import Any

from app.core.audit import AuditActor
from app.core.ids import uuid7
from app.modules.audit import public as audit_public
from app.modules.audit.repo_firestore import sealer_repo

FS_MODULES = ("audit", "core")


def _reviewer(make_principal: Any, auth: Any) -> dict[str, str]:
    p = make_principal(is_platform=True, roles=("super_admin",), tier="privileged")
    auth.grant(p, "audit.read")
    return auth.login(p)


async def _seed(n: int, action: str) -> None:
    for i in range(n):
        await audit_public.record_now(
            AuditActor("user", user_id=uuid7(), roles=("super_admin",)),
            action,
            "probe",
            uuid7(),
            after={"i": i, "nested": {"b": 2, "a": 1}},
            ip="203.0.113.7",
        )
    while await sealer_repo().seal_pending(50):
        pass


async def test_list_paginate_get_chain_status(fs_http: Any, make_principal: Any) -> None:
    client, _rec, auth = fs_http
    await _seed(3, "test.http.list")
    h = _reviewer(make_principal, auth)
    r = await client.get("/api/v1/audit/events", params={"action": "test.http.list", "limit": 2}, headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert [e["seq"] for e in body["data"]] == [3, 2] and body["page"]["has_more"] is True
    assert len(body["data"][0]["row_hash"]) == 64
    r2 = await client.get(
        "/api/v1/audit/events",
        params={"action": "test.http.list", "limit": 2, "cursor": body["page"]["next_cursor"]},
        headers=h,
    )
    assert [e["seq"] for e in r2.json()["data"]] == [1] and r2.json()["page"]["has_more"] is False
    one = await client.get("/api/v1/audit/events/1", headers=h)
    assert one.status_code == 200
    assert one.json()["after_state"]["nested"] == {"a": 1, "b": 2} and one.json()["ip"] == "203.0.113.7"
    assert (await client.get("/api/v1/audit/events/999999", headers=h)).status_code == 404
    bad = await client.get("/api/v1/audit/events", params={"cursor": "tampered.cursor"}, headers=h)
    assert bad.status_code == 400 and bad.json()["code"] == "invalid_cursor"
    cs = (await client.get("/api/v1/audit/chain-status", headers=h)).json()
    assert cs["verified"] is True and cs["checked_rows"] == 3 and cs["last_seq"] == 3
    # every read is itself audited: core.audit writes the Firestore outbox (TD_STORE_AUDIT=firestore),
    # nothing reached Postgres, and the sealer chains the 3 audit.query rows (2 lists, 1 detail)
    assert await sealer_repo().seal_pending(50) == 3
    cs = (await client.get("/api/v1/audit/chain-status", headers=h)).json()
    assert cs["verified"] is True and cs["checked_rows"] == 6


async def test_requires_permission(fs_http: Any, make_principal: Any) -> None:
    client, _rec, auth = fs_http
    assert (await client.get("/api/v1/audit/events")).json()["code"] == "unauthenticated"
    r = await client.get("/api/v1/audit/events", headers=auth.login(make_principal(is_platform=True)))
    assert r.status_code == 403
