"""Regression tests for wave-2 fixes in support (fix agent ``w2b``): an appeal ticket can carry
the invalidated attempt it is about (weblearn request 4, FR-ASM-012 appeal via support)."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

from app.core.db import system_context
from tests.identity.factory import company_org
from tests.support import helpers as h
from tests.support.test_audit_fixes import _student, body


async def _attempt(db, user_id) -> uuid.UUID:
    await system_context(db, "t")
    test_id, attempt_id = uuid.uuid4(), uuid.uuid4()
    await db.execute(
        text(
            "INSERT INTO tests (id, test_kind, title, review_policy, created_by) "
            "VALUES (:t, 'mock', 'Mock 1', '{}'::jsonb, :u)"
        ),
        {"t": test_id, "u": user_id},
    )
    await db.execute(
        text(
            "INSERT INTO test_attempts (id, test_id, test_version, user_id, attempt_no, status, "
            "selection_seed, layout, idempotency_key) VALUES (:a, :t, 1, :u, 1, 'in_progress', "
            "decode('00112233445566778899aabbccddeeff', 'hex'), '{}'::jsonb, :k)"
        ),
        {"a": attempt_id, "t": test_id, "u": user_id, "k": f"k-{attempt_id.hex}"},
    )
    await db.flush()
    return attempt_id


@pytest.mark.usefixtures("support_backend")
async def test_ticket_links_own_attempt_only(client, db) -> None:
    org = company_org()
    u, sb = await _student(client, db, org)
    other, _ = await _student(client, db, org)
    mine = await _attempt(db, u.id)
    theirs = await _attempt(db, other.id)

    r = await sb.post("/support/tickets", {**body("assessment"), "related_attempt_id": str(mine)})
    assert r.status_code == 201, r.text
    assert r.json()["related_attempt_id"] == str(mine)
    await system_context(db, "t")
    t = await h.ticket(db, r.json()["ticket_id"])
    assert t is not None and t.context["attempt_id"] == str(mine)
    got = await sb.get(f"/support/tickets/{r.json()['ticket_id']}")
    assert got.json()["related_attempt_id"] == str(mine)

    for bad in (theirs, uuid.uuid4()):
        r = await sb.post("/support/tickets", {**body("appeal"), "related_attempt_id": str(bad)})
        assert r.status_code == 422, r.text
        assert r.json()["errors"][0]["field"] == "related_attempt_id"

    plain = await sb.post("/support/tickets", body("assessment"))
    assert plain.status_code == 201 and plain.json()["related_attempt_id"] is None
