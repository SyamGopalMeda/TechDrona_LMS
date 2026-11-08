"""AUD-01..03 endpoints."""

from __future__ import annotations


def _reviewer(make_principal, auth, **kw):
    p = make_principal(is_platform=True, roles=("super_admin",), tier="privileged", **kw)
    auth.grant(p, "audit.read")
    return p, auth.login(p)


async def test_list_filter_paginate_and_get(write_and_seal, client, db, auth, make_principal) -> None:
    marker = await write_and_seal(3)
    _, h = _reviewer(make_principal, auth)

    r = await client.get("/api/v1/audit/events", params={"action": marker, "limit": 2}, headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert [e["action"] for e in body["data"]] == [marker, marker]
    assert body["page"]["has_more"] is True and body["page"]["limit"] == 2
    seqs = [e["seq"] for e in body["data"]]
    assert seqs == sorted(seqs, reverse=True)
    assert len(body["data"][0]["row_hash"]) == 64

    r2 = await client.get(
        "/api/v1/audit/events",
        params={"action": marker, "limit": 2, "cursor": body["page"]["next_cursor"]},
        headers=h,
    )
    assert r2.status_code == 200
    assert len(r2.json()["data"]) == 1 and r2.json()["page"]["has_more"] is False

    one = await client.get(f"/api/v1/audit/events/{seqs[0]}", headers=h)
    assert one.status_code == 200
    assert one.json()["after_state"]["nested"] == {"a": 1, "b": 2}
    assert one.json()["ip"] == "203.0.113.7"
    assert one.headers["cache-control"] == "no-store"


async def test_bad_cursor_and_missing_seq(client, auth, make_principal) -> None:
    _, h = _reviewer(make_principal, auth)
    r = await client.get("/api/v1/audit/events", params={"cursor": "tampered.cursor"}, headers=h)
    assert r.status_code == 400 and r.json()["code"] == "invalid_cursor"
    r = await client.get("/api/v1/audit/events/999999999999", headers=h)
    assert r.status_code == 404 and r.json()["code"] == "not_found"


async def test_chain_status(write_and_seal, client, db, auth, make_principal) -> None:
    await write_and_seal(2)
    _, h = _reviewer(make_principal, auth)
    r = await client.get("/api/v1/audit/chain-status", headers=h)
    assert r.status_code == 200
    body = r.json()
    assert body["verified"] is True and body["checked_rows"] >= 2 and body["first_bad_seq"] is None


async def test_requires_session_and_permission(client, db, auth, make_principal) -> None:
    assert (await client.get("/api/v1/audit/events")).json()["code"] == "unauthenticated"
    p = make_principal(is_platform=True)
    r = await client.get("/api/v1/audit/events", headers=auth.login(p))
    assert r.status_code == 403 and r.json()["permission"] == "audit.read"


async def test_rls_hides_audit_from_non_platform_context(
    write_and_seal, client, db, auth, make_principal
) -> None:
    """Even with the permission (e.g. a mis-grant), a non-platform principal reads nothing."""
    marker = await write_and_seal(1)
    p = make_principal(is_platform=False)
    auth.grant(p, "audit.read")
    r = await client.get("/api/v1/audit/events", params={"action": marker}, headers=auth.login(p))
    assert r.status_code == 200 and r.json()["data"] == []
