"""Analytics HTTP gaps on Firestore, no Postgres (round 6):

* ``POST /analytics/events`` and ``/analytics/events/beacon`` (incl. a retried batch -> all
  ``duplicate``, and the beacon's same-origin rule), ``GET /analytics/config``;
* bulk export -> ``admin.approvals`` approval (rbac on Firestore) -> approve / reject over HTTP ->
  the generate task body -> download; the sweep task body.

Request sessions are ``NO_POSTGRES`` (routes run on core's ``MemoryTx``); ``TD_STORE_*`` =
firestore for analytics, rbac and core (idempotency). Other modules are stubbed at analytics'
boundary (entitlement checker, catalog ownership, org resolver, identity consents, report inputs).
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from datetime import timedelta
from typing import Any

import httpx
import pytest

from app.core.ids import uuid7
from app.core.time import ist_date, utcnow
from tests.analytics.conftest import Page, batch, ist
from tests.analytics.fs.test_pipeline_firestore import steps, world  # noqa: F401  (fixture)
from tests.paths.fs.http_harness import install_fake_db, stub_core

FS_MODULES = ("analytics", "rbac", "core", "audit")
pytestmark = pytest.mark.usefixtures("fs_env")
API = "/api/v1"


@pytest.fixture
async def web(world: dict[str, Any], monkeypatch: pytest.MonkeyPatch, auth: Any) -> AsyncIterator[Any]:  # noqa: F811
    from app.core.firestore import sqlstore
    from app.main import create_app
    from app.modules.analytics import exports as ex
    from app.modules.analytics import fs_reports
    from app.modules.analytics import router as arouter
    from app.modules.identity import public as idp
    from app.modules.learning import public as learning

    stub_core(monkeypatch, [])
    monkeypatch.setattr(sqlstore, "_postgres_available", lambda: False)

    async def no_audit(*a: Any, **k: Any) -> None:
        return None

    async def no_limits(*a: Any, **k: Any) -> None:
        return None

    async def consents(session: Any, user_id: uuid.UUID) -> list[Any]:
        return []

    async def scope_org(session: Any, scope_type: str, scope_id: Any) -> None:
        return None

    async def many_rows(session: Any, r: Any, scope_id: Any) -> int:
        return ex.BULK_PII_ROWS + 1  # forces the bulk-PII approval path

    async def students(session: Any, batch_id: uuid.UUID) -> list[uuid.UUID]:
        return []

    async def no_enrolments(session: Any, users: Any) -> list[Any]:
        return []

    for mod in (ex, arouter):
        if hasattr(mod, "audit"):
            monkeypatch.setattr(mod, "audit", no_audit)
    monkeypatch.setattr(arouter, "enforce_rate_limits", no_limits)
    monkeypatch.setattr(idp, "consents_of", consents)
    monkeypatch.setattr(ex, "_scope_org", scope_org)
    monkeypatch.setattr(ex, "_estimate_rows", many_rows)
    monkeypatch.setattr(ex, "dispatch", lambda job_id: None)  # no broker; the task body is run below
    monkeypatch.setattr(fs_reports, "batch_org", lambda s, b: _org())
    monkeypatch.setattr(fs_reports, "batch_students", students)
    monkeypatch.setattr(learning, "enrolments_of_users", no_enrolments)
    app = create_app()
    install_fake_db(app)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def _org() -> uuid.UUID:
    return uuid.UUID(int=0)


async def test_ingest_events_beacon_dedupe_and_config(web: Any, auth: Any, make_principal: Any) -> None:
    uid = uuid7()
    p = make_principal(user_id=uid, privacy_tier="adult", is_minor=False)
    h = {**auth.login(p), "Content-Type": "application/json"}
    now = utcnow()
    day = ist_date(now)
    page = Page("practice", {"topic_id": str(uuid7())}, route="/app/practice/[setId]")
    t0 = ist(day, 0, 1) if ist(day, 0, 1) < now else now - timedelta(minutes=5)
    events = [page.view(t0), *[page.hb(t) for t in steps(t0, t0 + timedelta(minutes=2))]]
    body = json.dumps(batch(events, now), default=str)

    r = await web.post(f"{API}/analytics/events", content=body, headers=h)
    assert r.status_code == 200, r.text
    out = r.json()
    assert (out["accepted"], out["duplicate"], out["rejected"]) == (len(events), 0, 0)
    again = (await web.post(f"{API}/analytics/events", content=body, headers=h)).json()
    assert (again["accepted"], again["duplicate"]) == (0, len(events))  # retried batch: all duplicate

    from app.modules.analytics import fs_raw

    assert len(await fs_raw.all_docs(fs_raw.BATCHES, user_id=uid)) == 1  # one document per batch

    more = [page.hb(t) for t in steps(t0 + timedelta(minutes=2), t0 + timedelta(minutes=3))]
    beacon = json.dumps(batch(more, now), default=str)
    cross = await web.post(
        f"{API}/analytics/events/beacon", content=beacon, headers={**h, "sec-fetch-site": "cross-site"}
    )
    assert cross.status_code == 403 and cross.json()["code"] == "csrf_failed"
    ok = await web.post(
        f"{API}/analytics/events/beacon", content=beacon, headers={**h, "sec-fetch-site": "same-origin"}
    )
    assert ok.status_code == 204
    assert len(await fs_raw.all_docs(fs_raw.BATCHES, user_id=uid)) == 2

    cfg = await web.get(f"{API}/analytics/config", headers=h)
    assert cfg.status_code == 200, cfg.text
    c = cfg.json()
    assert c == {**c} and json.dumps(c)  # the config payload of an adult without product consent
    from app.modules.analytics.router import config_payload

    assert c == json.loads(json.dumps(config_payload(False, "adult"), default=str))


async def _request_bulk(web: Any, h: dict[str, str], batch_id: uuid.UUID) -> dict[str, Any]:
    r = await web.post(
        f"{API}/exports",
        json={
            "report_key": "batch.progress",
            "scope": {"type": "batch", "id": str(batch_id)},
            "reason": "cohort review",
        },
        headers=h,
    )
    assert r.status_code == 202, r.text
    return r.json()


async def test_export_approve_generate_download_reject_and_sweep(
    web: Any, auth: Any, make_principal: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.modules.analytics import tasks

    requester = make_principal(is_platform=True, last_step_up_at=utcnow(), roles=("admin",))
    approver = make_principal(is_platform=True, last_step_up_at=utcnow(), roles=("super_admin",))
    for perm in ("analytics.read", "report.export.request", "progress.read"):
        auth.grant(requester, perm)
    for perm in ("report.export.approve", "approval.decide", "analytics.read"):
        auth.grant(approver, perm)
    rh, ah = auth.login(requester), auth.login(approver)
    # rbac boundary: the approver's stored role grants are not seeded in this emulator test, so
    # admin.approvals' rbac permission check consults the test grants instead
    from app.modules.admin import approvals as apr_mod

    async def granted(session: Any, principal: Any, perm: str, scope: Any = None, *a: Any, **k: Any) -> bool:
        return (principal.user_id, perm) in auth.perms

    monkeypatch.setattr(apr_mod.rs, "check_permission", granted)
    batch_id = uuid7()

    job = await _request_bulk(web, rh, batch_id)
    jid = job.get("export_job_id") or job["id"]
    assert job["status"] == "awaiting_approval" and job["approval_request_id"]
    early = await web.get(f"{API}/exports/{jid}/download", headers={**rh, "accept": "application/json"})
    assert early.status_code == 409  # not ready yet

    key = {"Idempotency-Key": str(uuid.uuid4())}
    ap = await web.post(f"{API}/exports/{jid}/approve", json={"note": "ok"}, headers={**ah, **key})
    assert ap.status_code == 200, ap.text
    assert ap.json()["status"] in ("approved", "executed") or "approval_request_id" in ap.json()

    # the worker task body (generate) on the no-Postgres stack
    await tasks.run_export(uuid.UUID(jid))
    st = (await web.get(f"{API}/exports/{jid}", headers=rh)).json()
    assert st["status"] == "ready", st
    dl = await web.get(f"{API}/exports/{jid}/download", headers={**rh, "accept": "application/json"})
    assert dl.status_code == 200 and dl.json()["url"], dl.text
    redirect = await web.get(f"{API}/exports/{jid}/download", headers=rh, follow_redirects=False)
    assert redirect.status_code == 302

    job2 = await _request_bulk(web, rh, batch_id)
    j2 = job2.get("export_job_id") or job2["id"]
    rj = await web.post(f"{API}/exports/{j2}/reject", json={"note": "no"}, headers=ah)
    assert rj.status_code == 200, rj.text
    assert (await web.get(f"{API}/exports/{j2}", headers=rh)).json()["status"] == "rejected"

    out = await tasks.run_exports_sweep()
    assert set(out) == {"expired", "approval_lapsed", "generated"}
