"""Pass-2 requests to pass 1: signal suppression through the system write (``expire_at`` kept)
and evidence retention released when a case is closed (no Postgres)."""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import update

from app.core.db import NO_POSTGRES
from app.core.firestore.store import ScopedStore
from app.core.ids import uuid7
from app.modules.identity import clock
from app.modules.security import models as m
from app.modules.security import store_specs as sp
from app.modules.security.repo_fs_cases import SecSession, _Uow, _uow
from tests.audit.fs.support import sample_row
from tests.security.fs.test_pass1_routes_http_firestore import _catalogue, _ready_case
from tests.security.fs.test_unblock_review_http_firestore import _reviewer

FS_MODULES = ("security", "identity", "sessions", "rbac", "admin", "audit", "core", "notifications", "orgs")


async def _signal(user_id: Any, *, expire_at: Any) -> dict[str, Any]:
    row = {
        **sample_row(m.SecuritySignal),
        "id": uuid7(),
        "user_id": user_id,
        "family": "sharing",
        "suppressed_by_decision_id": None,
        "occurred_at": clock.now() - timedelta(days=2),
    }
    doc = sp.SignalRow.from_pg(row).doc()
    doc["expire_at"] = expire_at
    did = f"{row['id']}:{row['occurred_at'].isoformat()}"
    from app.core.firestore.backfill import mappings
    from app.modules.security.store_specs import SignalRow  # noqa: F401

    mp = next(x for x in mappings("security") if x.collection == "security_signals")
    did = mp.doc_id(row)
    await ScopedStore.system("firestore.backfill").import_documents("security_signals", [(did, doc)])
    return {**row, "_doc_id": did}


@pytest.mark.usefixtures("fs_env")
async def test_signal_suppression_keeps_expire_at() -> None:
    uid = uuid7()
    keep = clock.now() + timedelta(days=100)
    sig = await _signal(uid, expire_at=keep)
    token = _uow.set(_Uow())
    try:
        s = SecSession(NO_POSTGRES)
        dec = uuid7()
        n = (
            await s.execute(
                update(m.SecuritySignal)
                .where(m.SecuritySignal.user_id == uid, m.SecuritySignal.suppressed_by_decision_id.is_(None))
                .values(suppressed_by_decision_id=dec)
            )
        ).rowcount
        assert n == 1
        with pytest.raises(PermissionError):  # any other field stays append-only
            await s.execute(
                update(m.SecuritySignal).where(m.SecuritySignal.user_id == uid).values(family="x")
            )
    finally:
        _uow.reset(token)
    d = await ScopedStore.system("t").get("security_signals", sig["_doc_id"])
    assert d is not None and d["suppressed_by_decision_id"] == str(dec)
    assert d["expire_at"] == keep and d["family"] == "sharing"


async def test_close_releases_evidence(fs_http: Any, make_principal: Any) -> None:
    from app.modules.identity import public as idp
    from app.modules.identity.models import User

    client, _rec, auth = fs_http
    await _catalogue()
    me = make_principal(is_minor=False)
    now = clock.now()
    await idp.create_user(
        NO_POSTGRES,
        User(
            id=me.user_id,
            email=f"e{uuid7().hex[-8:]}@example.com",
            email_verified_at=now,
            status="active",
            is_minor=False,
            age_verified_at=now,
            age_verification_method="self_declared",
        ),
    )
    case = {
        **sample_row(m.SecurityCase),
        "id": uuid7(),
        "user_id": me.user_id,
        "case_ref": "SEC-2026-CLOSE1",
        "family": "sharing",
        "level": 0,
        "status": "open",
        "priority": "medium",
        "assignee_id": None,
        "first_response_at": None,
        "high_risk_reasons": [],
        "panel_views": {},
        "legal_hold": False,
        "version": 1,
        "closed_at": None,
        "created_at": now,
        "updated_at": now,
    }
    await ScopedStore.system("firestore.backfill").import_documents(
        "security_cases", [(str(case["id"]), sp.CaseRow.from_pg(case).doc())]
    )
    sig = await _signal(me.user_id, expire_at=None)  # held while the case is open
    hr = _reviewer(make_principal, auth)
    et = await _ready_case(client, hr, case, me)
    r = await client.post(
        f"/api/v1/security/cases/{case['id']}/decisions",
        json={"outcome": "close_no_action", "rationale": "Nothing found."},
        headers={**hr, "Idempotency-Key": str(uuid.uuid4()), "If-Match": et},
    )
    assert r.status_code == 201, r.text
    stored = await ScopedStore.system("t").get("security_cases", str(case["id"]))
    assert stored is not None and stored["status"] == "closed"
    d = await ScopedStore.system("t").get("security_signals", sig["_doc_id"])
    assert d is None or d.get("expire_at") is not None  # retention restored (or already purged by TTL)
