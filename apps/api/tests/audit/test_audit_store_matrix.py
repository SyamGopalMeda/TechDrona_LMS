"""AUD-01..03 on both stores (data-ops agent): the same HTTP calls answer the same way with
``TD_STORE_AUDIT=postgres`` and ``=firestore``.

On Firestore the fixture backfills ``audit_log`` + the head from the Postgres test database (the
cutover path), and ``write_and_seal`` drains the Postgres outbox into the Firestore chain (the
transition sealer, ``sealer._seal_into_firestore``). Needs Postgres and the emulator."""

from __future__ import annotations

import pytest

from tests.firestore.conftest import firestore_emulator  # noqa: F401
from tests.firestore.matrix import backend_fixture

audit_backend = backend_fixture("audit")
pytestmark = pytest.mark.usefixtures("audit_backend")


def _reviewer(make_principal, auth):
    p = make_principal(is_platform=True, roles=("super_admin",), tier="privileged")
    auth.grant(p, "audit.read")
    return auth.login(p)


async def test_list_paginate_get_on_both_stores(write_and_seal, client, db, auth, make_principal) -> None:
    marker = await write_and_seal(3)
    h = _reviewer(make_principal, auth)
    r = await client.get("/api/v1/audit/events", params={"action": marker, "limit": 2}, headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert [e["action"] for e in body["data"]] == [marker, marker] and body["page"]["has_more"] is True
    seqs = [e["seq"] for e in body["data"]]
    assert seqs == sorted(seqs, reverse=True) and len(body["data"][0]["row_hash"]) == 64
    r2 = await client.get(
        "/api/v1/audit/events",
        params={"action": marker, "limit": 2, "cursor": body["page"]["next_cursor"]},
        headers=h,
    )
    assert len(r2.json()["data"]) == 1 and r2.json()["page"]["has_more"] is False
    one = await client.get(f"/api/v1/audit/events/{seqs[0]}", headers=h)
    assert one.status_code == 200
    assert one.json()["after_state"]["nested"] == {"a": 1, "b": 2} and one.json()["ip"] == "203.0.113.7"
    missing = await client.get("/api/v1/audit/events/999999999999", headers=h)
    assert missing.status_code == 404
    bad = await client.get("/api/v1/audit/events", params={"cursor": "tampered.cursor"}, headers=h)
    assert bad.status_code == 400 and bad.json()["code"] == "invalid_cursor"


async def test_chain_status_on_both_stores(write_and_seal, client, db, auth, make_principal) -> None:
    await write_and_seal(2)
    r = await client.get("/api/v1/audit/chain-status", headers=_reviewer(make_principal, auth))
    assert r.status_code == 200
    body = r.json()
    assert body["verified"] is True and body["checked_rows"] >= 2 and body["first_bad_seq"] is None
