"""Live role audit 2026-11-14 (docs/qa/live-audit/fixes-api.md): API fixes on the Firebase stack
(every module on Firestore, no Postgres) with the REAL permission checker over the role catalogue.

* F1: an Evaluator reads its own batch and roster (``GET /batches/{id}``, ``/members``,
  ``?mine=true``) and nothing of another batch.
* #11: the scheduled reconciliation writes no run while no payment gateway is connected.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from app.core.company import COMPANY_ORG_ID
from app.core.principal import Principal, RoleGrant
from tests.parity.test_rbac_audit import _batch, rw  # noqa: F401  (``rw`` is a fixture)


async def _staff(w: Any, role: str, scope_type: str, scope_id: uuid.UUID | None) -> dict[str, str]:
    from app.core.ids import uuid7
    from app.core.time import utcnow

    now = utcnow()
    p = Principal(
        user_id=uuid7(),
        session_id=uuid7(),
        tier="staff",
        org_ids=(COMPANY_ORG_ID,),
        grants=(RoleGrant(role, scope_type, scope_id),),  # type: ignore[arg-type]
        aal=2,
        mfa_level="totp",
        auth_time=now,
        last_step_up_at=now,
        is_minor=False,
        device_id=uuid.uuid4(),
    )
    await w._user(p, name=role)
    return w.auth.login(p)  # type: ignore[no-any-return]


async def test_evaluator_reads_own_batch_and_roster_only(rw: Any) -> None:  # noqa: F811
    w = rw
    _, ah = await w.staff()
    ba, bb = await _batch(w, ah, "EV-A"), await _batch(w, ah, "EV-B")
    student, _ = await w.learner("ev-student")
    other, _ = await w.learner("ev-other")
    await w.call("POST", f"/batches/{ba}/members", ah, json={"user_ids": [str(student.user_id)]})
    await w.call("POST", f"/batches/{bb}/members", ah, json={"user_ids": [str(other.user_id)]})
    eh = await _staff(w, "evaluator", "batch", ba)

    # own batch: metadata, roster, and the batch lists
    r = await w.call("GET", f"/batches/{ba}", eh)
    assert r.json()["id"] == str(ba) and r.json()["name"] == "Batch EV-A"
    r = await w.call("GET", f"/batches/{ba}/members", eh)
    assert [m["user_id"] for m in r.json()["data"]] == [str(student.user_id)], r.text
    r = await w.call("GET", "/batches?mine=true", eh)
    assert [b["id"] for b in r.json()["data"]] == [str(ba)], r.text
    r = await w.call("GET", "/batches", eh)
    assert [b["id"] for b in r.json()["data"]] == [str(ba)], r.text

    # another batch: nothing (403), an unknown batch: 404
    await w.call("GET", f"/batches/{bb}", eh, expect=403)
    await w.call("GET", f"/batches/{bb}/members", eh, expect=403)
    await w.call("GET", f"/batches/{uuid.uuid4()}", eh, expect=404)

    # read only: no writes, and classes / attendance stay Trainer + Admin
    await w.call("PATCH", f"/batches/{ba}", eh, expect=403, json={"name": "renamed"})
    await w.call("POST", f"/batches/{ba}/members", eh, expect=403, json={"user_ids": [str(other.user_id)]})
    await w.call("GET", f"/batches/{ba}/sessions", eh, expect=403)
    await w.call("GET", f"/batches/{ba}/attendance", eh, expect=403)

    # unchanged: the batch trainer still reads; a content manager (platform) still cannot
    th = await _staff(w, "trainer", "batch", ba)
    await w.call("GET", f"/batches/{ba}/members", th)
    ch = await _staff(w, "content_manager", "platform", None)
    await w.call("GET", f"/batches/{ba}", ch, expect=403)
    await w.call("GET", f"/batches/{ba}/members", ch, expect=403)
    assert (await w.call("GET", "/batches?mine=true", ch)).json() == {"data": []}


# --------------------------------------------------------------------------- reconciliation


async def test_scheduled_reconciliation_skips_without_gateway(monkeypatch: pytest.MonkeyPatch) -> None:
    from contextlib import asynccontextmanager

    from app.modules.commerce import admin, gateway, tasks

    runs: list[dict[str, Any]] = []

    async def fake_run(_session: Any, gw: Any, **kw: Any) -> Any:
        runs.append(kw)
        return {"id": "run"}

    @asynccontextmanager
    async def fake_session() -> Any:
        yield object()

    async def no_ctx(*_a: Any, **_k: Any) -> None:
        return None

    monkeypatch.setattr(admin, "run_reconciliation", fake_run)
    monkeypatch.setattr(admin, "run_json", lambda run: dict(run))
    monkeypatch.setattr(tasks, "store_session", fake_session)
    monkeypatch.setattr(tasks, "system_context", no_ctx)
    monkeypatch.setattr(gateway, "get_gateway", lambda name="razorpay": object())

    # not connected (fake provider or no real key): no run, so no "0 orders" row
    monkeypatch.setattr(gateway, "gateway_status", lambda: {"provider": "fake", "integrated": False})
    out = await tasks.reconciliation()
    assert out == {"skipped": "gateway_not_integrated", "provider": "fake"}
    assert runs == []

    # connected: the hourly run happens as before
    monkeypatch.setattr(gateway, "gateway_status", lambda: {"provider": "razorpay", "integrated": True})
    out = await tasks.reconciliation()
    assert out == {"id": "run"} and len(runs) == 1 and runs[0]["triggered_by"] == "system:beat"
