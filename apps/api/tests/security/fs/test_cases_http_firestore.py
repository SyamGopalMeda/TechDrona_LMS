"""Pass 1 (cases): the learner case view through the FastAPI app on Firestore (no Postgres)."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from app.core.firestore.store import ScopedStore
from app.core.ids import uuid7
from app.modules.identity import clock
from app.modules.security import models as m
from app.modules.security import store_specs as sp
from tests.audit.fs.support import sample_row

FS_MODULES = ("security", "audit", "core", "admin")


async def _put(coll: str, cls: Any, rows: list[dict[str, Any]]) -> None:
    await ScopedStore.system("firestore.backfill").import_documents(
        coll, [(str(r["id"]), cls.from_pg(r).doc()) for r in rows]
    )


async def test_my_case_projection(fs_http: Any, make_principal: Any) -> None:
    client, _rec, auth = fs_http
    me = make_principal()
    now = clock.now()
    case = {
        **sample_row(m.SecurityCase),
        "id": uuid7(),
        "user_id": me.user_id,
        "case_ref": "SEC-2026-ABC123",
        "family": "sharing",
        "level": 3,
        "status": "open",
    }
    await _put("security_cases", sp.CaseRow, [case])
    notes = [
        {
            **sample_row(m.CaseNote, 0),
            "id": uuid7(),
            "case_id": case["id"],
            "visibility": "student",
            "body": "first",
            "created_at": now - timedelta(hours=2),
        },
        {
            **sample_row(m.CaseNote, 1),
            "id": uuid7(),
            "case_id": case["id"],
            "visibility": "internal",
            "body": "hidden",
            "created_at": now - timedelta(hours=1),
        },
        {
            **sample_row(m.CaseNote, 2),
            "id": uuid7(),
            "case_id": case["id"],
            "visibility": "student",
            "body": "second",
            "created_at": now,
        },
    ]
    await _put("case_notes", sp.CaseNoteRow, notes)
    decisions = [
        {
            **sample_row(m.CaseDecision, i),
            "id": uuid7(),
            "case_id": case["id"],
            "outcome": o,
            "student_summary": f"s-{o}",
            "created_at": now - timedelta(minutes=10 - i),
        }
        for i, o in enumerate(("uphold", "lift"))
    ]
    await _put("case_decisions", sp.CaseDecisionRow, decisions)
    restr = {
        **sample_row(m.AccountRestriction),
        "id": uuid7(),
        "user_id": me.user_id,
        "case_id": case["id"],
        "level": 3,
        "ended_at": None,
        "lift_pending_at": None,
        "ends_at": now + timedelta(days=7),
    }
    await _put("account_restrictions", sp.RestrictionRow, [restr])

    r = await client.get("/api/v1/me/security/cases/SEC-2026-ABC123", headers=auth.login(me))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["case_ref"] == "SEC-2026-ABC123" and body["level"] == 3 and body["status"] == "open"
    assert [n["body"] for n in body["notes"]] == ["first", "second"]
    assert body["decision"]["outcome"] == "lift" and body["restriction"]["state"] == "active"
    other = auth.login(make_principal())
    assert (await client.get("/api/v1/me/security/cases/SEC-2026-ABC123", headers=other)).status_code == 404
