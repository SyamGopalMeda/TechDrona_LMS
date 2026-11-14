"""Admin privacy requests, erasure ledger, retention policies and break-glass on Firestore
(``TD_STORE_ADMIN=firestore``). Emulator only, no Postgres."""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from app.core.errors import ProblemError
from app.core.firestore.errors import StoreAccessDeniedError
from app.core.firestore.repository import assert_repository_scoped
from app.core.firestore.store import ScopedStore
from app.core.ids import uuid7
from app.modules.admin import privacy as prv
from app.modules.admin import store_specs as sp
from app.modules.admin.repo_firestore_privacy import (
    BreakGlassRepo,
    PrivacyRepo,
    break_glass_repo,
    privacy_repo,
)

FS_MODULES = ("admin",)
pytestmark = pytest.mark.usefixtures("fs_env")
NOW = datetime(2026, 11, 12, 9, 0, tzinfo=UTC)


def test_scope_lint() -> None:
    assert_repository_scoped(PrivacyRepo)
    assert_repository_scoped(BreakGlassRepo)


def test_row_mapping_round_trip() -> None:
    pg = {
        "id": uuid7(),
        "request_ref": "PRV-1",
        "user_id": uuid7(),
        "requested_by": None,
        "requester_relationship": "self",
        "organization_id": None,
        "request_type": "access_export",
        "status": "completed",
        "details": None,
        "identity_verification_method": "session",
        "identity_verified_at": NOW,
        "received_at": NOW,
        "due_at": NOW + timedelta(days=30),
        "cooling_off_until": None,
        "completed_at": NOW,
        "response_summary": "ok",
        "export_job_id": None,
        "export_payload": {"sessions": [[1, 2]], "n": 5.0},
        "assigned_to": None,
        "legal_hold": False,
        "idempotency_key": None,
        "created_at": NOW,
        "updated_at": NOW,
        "extra_column": 1,
    }
    doc = sp.PrivacyRow.from_pg(pg).doc()
    back = sp.PrivacyRow.of(doc)
    for k in sp.PrivacyRow.KINDS:
        assert getattr(back, k) == pg[k], k
    assert isinstance(back.export_payload["n"], float)
    ret = sp.RetentionRow.of(
        sp.RetentionRow.from_pg({"id": uuid7(), "retention_interval": timedelta(days=180)}).doc()
    )
    assert ret.retention_interval.days == 180
    led = sp.ErasureLedgerRow.of(
        sp.ErasureLedgerRow.from_pg({"id": uuid7(), "subject_hash": b"\x01\x02"}).doc()
    )
    assert led.subject_hash == b"\x01\x02"


async def test_learner_flow_and_isolation(make_principal: Any, auth: Any) -> None:
    alice, bob = make_principal(), make_principal()
    a1 = await prv.create(None, alice.user_id, "access_export", "pls", None, principal=alice)  # type: ignore[arg-type]
    a2 = await prv.create(None, alice.user_id, "erasure", None, "idem-1", principal=alice)  # type: ignore[arg-type]
    assert a2.status == "cooling_off" and a2.cooling_off_until is not None
    assert prv.request_out(a1)["request_ref"].startswith("PRV")
    mine = await prv.list_own(None, alice)  # type: ignore[arg-type]
    assert [r.id for r in mine] == [a2.id, a1.id]  # received_at desc
    assert await prv.count_own_since(None, alice, datetime.now(UTC) - timedelta(days=1)) == 2  # type: ignore[arg-type]
    assert await prv.load(None, a1.id, principal=bob, own=True) is None  # type: ignore[arg-type]
    with pytest.raises(StoreAccessDeniedError):
        await privacy_repo(bob).list_for_user(alice.user_id)
    with pytest.raises(StoreAccessDeniedError):  # learner cannot plant a request for someone else
        await prv.create(None, alice.user_id, "grievance", None, None, principal=bob)  # type: ignore[arg-type]
    x = await prv.load(None, a1.id, principal=alice, own=True)  # type: ignore[arg-type]
    x.status = "withdrawn"
    await prv.save(alice, x, own=True)
    again = await prv.load(None, a1.id, principal=alice, own=True)  # type: ignore[arg-type]
    assert again.status == "withdrawn" and prv.request_out(again) == prv.request_out(x)


async def test_staff_queue_counts_and_optimistic_lock(make_principal: Any, auth: Any) -> None:
    learner, staff, other = make_principal(), make_principal(), make_principal()
    auth.grant(staff, "privacy.request.process")
    r1 = await prv.create(None, learner.user_id, "grievance", None, None, principal=learner)  # type: ignore[arg-type]
    r2 = await prv.create(None, learner.user_id, "access_export", None, None, principal=learner)  # type: ignore[arg-type]
    with pytest.raises(StoreAccessDeniedError):
        await prv.queue(None, other)  # type: ignore[arg-type]
    q = await prv.queue(None, staff)  # type: ignore[arg-type]
    assert {r.id for r in q} == {r1.id, r2.id}
    assert [r.due_at for r in q] == sorted(r.due_at for r in q)
    assert await prv.open_counts(None, datetime.now(UTC)) == (2, 0)  # type: ignore[arg-type]
    assert await prv.open_counts(None, datetime.now(UTC) + timedelta(days=31)) == (2, 2)  # type: ignore[arg-type]
    a = await prv.load(None, r1.id, principal=staff, own=False)  # type: ignore[arg-type]
    b = await prv.load(None, r1.id, principal=staff, own=False)  # type: ignore[arg-type]
    a.status, a.completed_at, a.response_summary = "completed", datetime.now(UTC), "done"
    await prv.save(staff, a)
    b.status = "rejected"
    with pytest.raises(ProblemError) as e:
        await prv.save(staff, b)
    assert e.value.code == "conflict"
    assert (await prv.open_counts(None, datetime.now(UTC)))[0] == 1  # type: ignore[arg-type]
    assert r1.id in {r.id for r in await prv.queue(None, staff)}  # completed in the last 30 days


async def test_request_ref_unique(make_principal: Any) -> None:
    alice = make_principal()
    repo = privacy_repo(alice)
    row = sp.PrivacyRow(
        id=uuid7(),
        request_ref="PRV-SAME",
        user_id=alice.user_id,
        request_type="grievance",
        received_at=NOW,
        due_at=NOW,
    )
    await repo.create(alice.user_id, row)
    dup = sp.PrivacyRow(
        id=uuid7(),
        request_ref="PRV-SAME",
        user_id=alice.user_id,
        request_type="grievance",
        received_at=NOW,
        due_at=NOW,
    )
    with pytest.raises(ProblemError):
        await repo.create(alice.user_id, dup)


async def test_erasure_ledger_append_only(make_principal: Any, auth: Any) -> None:
    sysrepo = privacy_repo(None, "admin.privacy_erasure")
    row = sp.ErasureLedgerRow(
        id=uuid7(),
        privacy_request_id=None,
        subject_hash=prv.subject_hash(uuid7()),
        erased_at=NOW,
        scope={"modules": ["analytics"], "sessions_revoked": 2},
        pending_modules=["identity"],
    )
    await sysrepo.append_ledger(row)
    got = await sysrepo.ledger()
    assert len(got) == 1 and got[0].subject_hash == row.subject_hash and got[0].scope["sessions_revoked"] == 2
    staff = make_principal()
    auth.grant(staff, "privacy.request.process")
    with pytest.raises(StoreAccessDeniedError):  # system collection
        await privacy_repo(staff).append_ledger(row)
    with pytest.raises(StoreAccessDeniedError):
        await ScopedStore.system("x").update(sp.ERASURE_LEDGER, str(row.id), {"pending_modules": []})


async def test_retention_policies_sorted(make_principal: Any, auth: Any) -> None:
    st = ScopedStore.system("firestore.backfill")
    rows = [
        sp.RetentionRow.from_pg(
            {
                "id": uuid7(),
                "table_name": t,
                "retention_interval": timedelta(days=d),
                "data_category": "c",
                "retention_class": "r",
                "basis": "b",
                "deletion_method": "delete",
                "job_name": "j",
                "owner_module": "m",
                "legal_hold_aware": True,
                "is_active": True,
            }
        )
        for t, d in (("zz", 1), ("aa", 30), ("mm", 7))
    ]
    await st.import_documents(sp.RETENTION, [(str(r.id), r.doc()) for r in rows])
    reader = make_principal()
    auth.grant(reader, "audit.read")
    got = await privacy_repo(reader).retention_policies()
    assert [r.table_name for r in got] == ["aa", "mm", "zz"] and got[0].retention_interval.days == 30
    with pytest.raises(StoreAccessDeniedError):
        await privacy_repo(make_principal()).retention_policies()


async def test_break_glass_lifecycle(make_principal: Any, auth: Any) -> None:
    from app.modules.admin.accounts import bg_out

    holder = uuid7()
    st = ScopedStore.system("firestore.backfill")
    active = sp.BreakGlassRow(
        id=uuid7(),
        user_id=holder,
        reason="r" * 30,
        status="active",
        started_at=NOW - timedelta(hours=2),
        expires_at=NOW - timedelta(minutes=1),
        created_at=NOW,
        updated_at=NOW,
    )
    ended = sp.BreakGlassRow(
        id=uuid7(),
        user_id=uuid7(),
        reason="old",
        status="ended",
        started_at=NOW - timedelta(days=3),
        expires_at=NOW - timedelta(days=3),
        ended_at=NOW - timedelta(days=3),
        created_at=NOW,
        updated_at=NOW,
    )
    await st.import_documents(sp.BREAK_GLASS, [(str(b.id), b.doc()) for b in (active, ended)])
    repo = break_glass_repo(None)
    assert [b.id for b in await repo.list_sessions(None)] == [active.id, ended.id]
    assert [b.id for b in await repo.list_sessions("ended")] == [ended.id]
    assert (await repo.active_for(holder)).id == active.id
    assert await repo.active_for(uuid7()) is None
    assert await repo.count_active() == 1
    due = await repo.due_for_expiry(NOW)
    assert [b.id for b in due] == [active.id]
    b = due[0]
    b.status, b.ended_at, b.end_reason = "expired", b.expires_at, "expired"
    await repo.save(b)
    assert await repo.count_active() == 0
    out = bg_out(await repo.get(active.id))
    assert out["status"] == "expired" and out["end_reason"] == "expired"
    with pytest.raises(StoreAccessDeniedError):
        await break_glass_repo(make_principal()).count_active()


async def test_concurrent_saves_one_wins(make_principal: Any, auth: Any) -> None:
    staff, learner = make_principal(), make_principal()
    auth.grant(staff, "privacy.request.process")
    r = await prv.create(None, learner.user_id, "grievance", None, None, principal=learner)  # type: ignore[arg-type]
    copies = [await prv.load(None, r.id, principal=staff, own=False) for _ in range(4)]  # type: ignore[arg-type]
    for i, c in enumerate(copies):
        c.response_summary = f"v{i}"

    async def save(c: Any) -> str:
        try:
            await prv.save(staff, c)
            return "ok"
        except ProblemError as e:
            return e.code

    res = await asyncio.gather(*(save(c) for c in copies))
    assert res.count("ok") == 1 and res.count("conflict") == 3


def test_index_fragment() -> None:
    p = Path(sp.__file__).with_name("firestore.indexes.fragment.json")
    declared = {tuple(f["fieldPath"] for f in i["fields"]) for i in json.loads(p.read_text())["indexes"]}
    assert ("user_id", "received_at") in declared and ("status", "started_at") in declared
    assert uuid.UUID(str(uuid7()))
