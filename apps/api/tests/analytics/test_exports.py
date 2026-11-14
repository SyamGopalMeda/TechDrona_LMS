"""Report exports (ANL-13..15): request -> (approval) -> generation -> download link, with the
real session resolver / RBAC checker, the Celery task body run inline and the fake store."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import timedelta
from typing import Any

import pytest

from app.core.ids import uuid7
from app.modules.analytics import exports as ax
from app.modules.analytics.export_store import FakeExportStore, set_export_store
from app.modules.analytics.models import ExportJob
from app.modules.analytics.tasks import run_export, run_exports_sweep
from app.modules.identity import clock
from tests.identity.factory import (
    Browser,
    UserHandle,
    add_member,
    company_org,
    grant,
    make_batch,
    make_user,
    staff_login,
    step_up,
)
from tests.identity.fixtures import mail, real_auth, sms  # noqa: F401

JSON = {"Accept": "application/json"}


@pytest.fixture
def store(tmp_path: Any) -> Iterator[FakeExportStore]:
    s = FakeExportStore(tmp_path)
    set_export_store(s)
    yield s
    set_export_store(None)


@pytest.fixture
def audited(monkeypatch: Any) -> list[tuple[str, str]]:
    """Spy on ``audit()`` in the exports service (td_app cannot read audit_outbox)."""
    calls: list[tuple[str, str]] = []
    real = ax.audit

    async def spy(session: Any, actor: Any, action: str, target_type: str, *a: Any, **kw: Any) -> Any:
        calls.append((action, target_type))
        return await real(session, actor, action, target_type, *a, **kw)

    monkeypatch.setattr(ax, "audit", spy)
    return calls


_ip = iter(range(10, 250))


async def login(client: Any, user: UserHandle, *, fresh: bool = True) -> Browser:
    b = Browser(client, ip=f"198.18.7.{next(_ip)}")
    await staff_login(b, user)
    if fresh:
        await step_up(b, user)
    return b


async def staff(
    db: Any, role: str, scope_type: str = "platform", scope_id: uuid.UUID | None = None
) -> UserHandle:
    u = await make_user(db, with_totp=True)
    await grant(db, u.id, role, scope_type, scope_id)
    return u


async def cohort(db: Any, n_students: int = 3) -> tuple[uuid.UUID, list[uuid.UUID]]:
    """A batch of the company org with ``n_students`` active students."""
    org = company_org()
    creator = await make_user(db)
    batch = await make_batch(db, org, creator.id)
    students = []
    for _ in range(n_students):
        s = await make_user(db)
        await add_member(db, org, s.id, batch_id=batch)
        students.append(s.id)
    return batch, students


async def job_row(db: Any, job_id: str) -> ExportJob:
    from app.core.db import system_context

    await system_context(db, "test.exports")
    job = await db.get(ExportJob, uuid.UUID(job_id))
    assert job is not None
    await db.refresh(job)
    return job


def batch_body(batch: uuid.UUID, **kw: Any) -> dict[str, Any]:
    return {"report_key": "batch.progress", "scope": {"type": "batch", "id": str(batch)}, **kw}


PLATFORM = {"report_key": "platform.overview", "scope": {"type": "platform"}}


# --------------------------------------------------------------------------- happy path


async def test_platform_export_generation_download_and_audit(client, db, store, audited) -> None:
    admin = await staff(db, "super_admin")
    b = await login(client, admin)

    res = await b.post("/exports", {**PLATFORM, "reason": "Monthly review"})
    assert res.status_code == 202, res.text
    body = res.json()
    assert body["status"] == "running" and body["contains_pii"] is False
    assert "organization_id" not in body
    jid = body["export_job_id"]

    assert await run_export(uuid.UUID(jid)) == "ready"
    got = (await b.get(f"/exports/{jid}")).json()
    assert got["status"] == "ready" and got["row_count"] > 0 and len(got["file_sha256"]) == 64
    assert got["scope"] == {"type": "platform", "id": None} and got["downloads_remaining"] == 5
    listed = (await b.get("/exports", params={"scope_type": "platform"})).json()
    assert [j["export_job_id"] for j in listed["data"]] == [jid]

    job = await job_row(db, jid)
    data = store.read(job.file_s3_key or "")
    assert data is not None
    import hashlib

    assert hashlib.sha256(data).digest() == job.file_sha256
    first = data.decode().splitlines()[0]
    assert first.startswith("# Tech Drona export platform.overview") and str(admin.id) in first
    assert job.expires_at is not None and job.completed_at is not None
    assert job.expires_at - job.completed_at == timedelta(hours=24)

    dl = await b.get(f"/exports/{jid}/download", headers=JSON)
    assert dl.status_code == 200, dl.text
    out = dl.json()
    assert "X-Amz-Signature=" in out["url"] and "X-Amz-Expires=120" in out["url"]
    assert out["downloads_remaining"] == 4 and out["sha256"] == job.file_sha256.hex()
    redirect = await b.get(f"/exports/{jid}/download")
    assert redirect.status_code == 302 and "X-Amz-Signature=" in redirect.headers["location"]
    for _ in range(3):
        assert (await b.get(f"/exports/{jid}/download", headers=JSON)).status_code == 200
    over = await b.get(f"/exports/{jid}/download", headers=JSON)
    assert over.status_code == 429 and over.json()["code"] == "rate_limited"

    actions = [a for a, _t in audited]
    assert actions.count("export.requested") == 1 and actions.count("export.generated") == 1
    assert actions.count("export.download") == 5
    assert all(t == "export_job" for _a, t in audited)


async def test_trainer_batch_export_is_pii_and_requester_only(client, db, store, monkeypatch) -> None:
    batch, students = await cohort(db, 2)
    trainer = await staff(db, "trainer", "batch", batch)
    b = await login(client, trainer, fresh=False)
    body = batch_body(batch)
    # PII export needs a step-up within 10 minutes (S10); the MFA login counts as one
    real_now = clock.now
    later = real_now() + timedelta(minutes=11)
    monkeypatch.setattr(clock, "now", lambda: later)
    need = await b.post("/exports", body)
    assert need.status_code == 401 and need.json()["code"] == "step_up_required"
    monkeypatch.setattr(clock, "now", real_now)
    res = await b.post("/exports", body)
    assert res.status_code == 202 and res.json()["contains_pii"] is True
    jid = res.json()["export_job_id"]
    # not ready yet
    early = await b.get(f"/exports/{jid}/download", headers=JSON)
    assert early.status_code == 409 and early.json()["code"] == "invalid_state_transition"
    assert await run_export(uuid.UUID(jid)) == "ready"
    job = await job_row(db, jid)
    text = (store.read(job.file_s3_key or "") or b"").decode()
    assert text.splitlines()[0].startswith("# Tech Drona export batch.progress")
    assert "user_id,weekly_learning_s,weak_topics,needs_attention,reasons" in text
    assert all(str(s) in text for s in students) and job.row_count == 2
    assert "weekly_learning_time n=<10" in text  # aggregate line keeps the k-floor

    # someone else (even another trainer of the same batch) cannot see or download it
    other = await staff(db, "trainer", "batch", batch)
    bo = await login(client, other)
    assert (await bo.get(f"/exports/{jid}")).status_code == 404
    assert (await bo.get(f"/exports/{jid}/download", headers=JSON)).status_code == 404
    assert (await bo.get("/exports")).json()["data"] == []

    # trainer: another batch and platform reports are out of scope
    other_batch, _ = await cohort(db, 1)
    denied = await b.post("/exports", batch_body(other_batch))
    assert denied.status_code in (403, 404)
    assert (await b.post("/exports", PLATFORM)).status_code == 403


# --------------------------------------------------------------------------- dual control


async def test_bulk_pii_export_needs_a_second_admin(client, db, store, audited, monkeypatch) -> None:
    monkeypatch.setattr(ax, "BULK_PII_ROWS", 2)
    batch, _students = await cohort(db, 3)
    # requester also holds super_admin so the SoD check (approver != requester) is reachable
    requester = await staff(db, "trainer", "batch", batch)
    await grant(db, requester.id, "super_admin")
    sa = await staff(db, "super_admin")
    cm = await staff(db, "content_manager")
    b, bsa, bcm = await login(client, requester), await login(client, sa), await login(client, cm)

    res = await b.post("/exports", batch_body(batch, reason="Placement cell"))
    assert res.status_code == 202, res.text
    assert (
        res.json()["status"] == "awaiting_approval" and res.json()["required_approver_role"] == "super_admin"
    )
    jid, apr_id = res.json()["export_job_id"], res.json()["approval_request_id"]
    assert await run_export(uuid.UUID(jid)) == "awaiting_approval"  # nothing generated before approval

    own = await b.post(f"/exports/{jid}/approve", {"note": "mine"}, headers={"Idempotency-Key": uuid7().hex})
    assert own.status_code == 403 and own.json()["code"] == "sod_violation"
    nope = await bcm.post(f"/exports/{jid}/approve", {}, headers={"Idempotency-Key": uuid7().hex})
    assert nope.status_code in (403, 404)  # only Admin approves exports
    ok = await bsa.post(f"/exports/{jid}/approve", {"note": "ok"}, headers={"Idempotency-Key": uuid7().hex})
    assert ok.status_code == 200, ok.text
    assert ok.json() == {"export_job_id": jid, "approval_request_id": apr_id, "status": "running"}
    assert await run_export(uuid.UUID(jid)) == "ready"
    assert (await job_row(db, jid)).row_count == 3

    # reject path
    res2 = await b.post("/exports", batch_body(batch))
    jid2 = res2.json()["export_job_id"]
    rej = await bsa.post(f"/exports/{jid2}/reject", {"note": "too broad"})
    assert rej.status_code == 200 and rej.json()["status"] == "rejected"
    assert (await b.get(f"/exports/{jid2}")).json()["status"] == "rejected"
    again = await bsa.post(f"/exports/{jid2}/approve", {}, headers={"Idempotency-Key": uuid7().hex})
    assert again.status_code == 409

    actions = [a for a, _t in audited]
    assert {"export.requested", "export.approved", "export.rejected", "export.generated"} <= set(actions)


# --------------------------------------------------------------------------- denials / validation


async def test_cross_batch_validation_and_rate_limit(client, db, store, monkeypatch) -> None:
    batch_a, _ = await cohort(db, 1)
    batch_b, _ = await cohort(db, 1)
    trainer = await staff(db, "trainer", "batch", batch_a)
    b = await login(client, trainer)
    assert (await b.post("/exports", batch_body(batch_b))).status_code in (403, 404)
    assert (await b.post("/exports", batch_body(uuid7()))).status_code == 404

    def code(r: Any) -> str:
        assert r.status_code == 422, r.text
        return r.json()["errors"][0]["code"]

    assert (
        code(await b.post("/exports", {**batch_body(batch_a), "report_key": "nope.report"}))
        == "unknown_report"
    )
    # the college/coordinator reports are gone
    for gone in ("coordinator.org_overview", "coordinator.org_learners", "coordinator.batch_progress"):
        assert code(await b.post("/exports", {**batch_body(batch_a), "report_key": gone})) == "unknown_report"
    assert (
        code(await b.post("/exports", {**batch_body(batch_a), "report_key": "security.blocked-accounts"}))
        == "use_security_export"
    )
    mismatch = {"report_key": "batch.progress", "scope": {"type": "platform"}}
    assert code(await b.post("/exports", mismatch)) == "scope_mismatch"
    assert (
        code(await b.post("/exports", {"report_key": "batch.progress", "scope": {"type": "batch"}}))
        == "required"
    )
    for bad_scope in ("galaxy", "organization"):
        bad = await b.post("/exports", {"report_key": "x", "scope": {"type": bad_scope, "id": str(uuid7())}})
        assert bad.status_code in (400, 422) and bad.json()["code"] == "validation_failed"
    assert (await b.get("/exports", params={"scope_type": "organization"})).status_code in (400, 422)

    # 10/day per user
    monkeypatch.setattr(ax, "DAILY_LIMIT", 1)
    assert (await b.post("/exports", batch_body(batch_a))).status_code == 202
    limited = await b.post("/exports", batch_body(batch_a))
    assert limited.status_code == 429 and limited.json()["code"] == "rate_limited"


async def test_platform_export_by_admin_and_student_denied(client, db, store) -> None:
    admin = await staff(db, "super_admin")
    ba = await login(client, admin)
    res = await ba.post("/exports", PLATFORM)
    assert res.status_code == 202, res.text
    assert await run_export(uuid.UUID(res.json()["export_job_id"])) == "ready"
    student = await make_user(db)
    bs = Browser(client, ip="198.18.9.9")
    assert (await bs.login(student.email)).status_code == 200
    assert (await bs.post("/exports", PLATFORM)).status_code == 403
    assert (await bs.get(f"/exports/{res.json()['export_job_id']}")).status_code == 404


async def test_download_rechecks_scope_permission(client, db, store) -> None:
    """ANL-15: the download re-runs the request-time check (``report.export.request`` +
    ``analytics.read`` on the export's own scope). A trainer whose grant on that batch was
    revoked after requesting cannot fetch the file any more."""
    from sqlalchemy import text, update

    from app.core.db import system_context
    from app.modules.rbac.models import RoleGrant as RG

    batch, _students = await cohort(db, 1)
    keep, _ = await cohort(db, 1)
    trainer = await make_user(db, with_totp=True)
    await grant(db, trainer.id, "trainer", "batch", keep)  # stays staff after the revoke
    gid = await grant(db, trainer.id, "trainer", "batch", batch)
    b = await login(client, trainer)
    res = await b.post("/exports", batch_body(batch))
    assert res.status_code == 202, res.text
    jid = res.json()["export_job_id"]
    assert await run_export(uuid.UUID(jid)) == "ready"
    assert (await b.get(f"/exports/{jid}/download", headers=JSON)).status_code == 200

    await system_context(db, "test.factory")
    await db.execute(update(RG).where(RG.id == gid).values(revoked_at=text("now()")))
    await db.flush()
    denied = await b.get(f"/exports/{jid}/download", headers=JSON)
    assert denied.status_code in (403, 404), denied.text
    if denied.status_code == 403:
        assert denied.json()["permission"] == "report.export.request"
    job = await job_row(db, jid)
    assert job.download_count == 1  # the refused attempt did not consume a download


async def test_restricted_principal_cannot_request(client, auth) -> None:
    from app.core.principal import Principal

    p = Principal(user_id=uuid7(), session_id=uuid7(), scope="restricted", is_minor=False)
    auth.grant(p, "report.export.request")
    r = await client.post("/api/v1/exports", json=PLATFORM, headers=auth.login(p))
    assert r.status_code == 403 and r.json()["code"] == "account_restricted"


# --------------------------------------------------------------------------- expiry


async def test_expiry_and_sweep(client, db, store, monkeypatch) -> None:
    admin = await staff(db, "super_admin")
    b = await login(client, admin)
    jid = (await b.post("/exports", PLATFORM)).json()["export_job_id"]
    assert await run_export(uuid.UUID(jid)) == "ready"
    key = (await job_row(db, jid)).file_s3_key or ""
    assert store.read(key) is not None

    # 24 h later (shift the file's expiry instead of the clock: the login session would lapse)
    job = await job_row(db, jid)
    job.expires_at = clock.now() - timedelta(minutes=1)
    await db.flush()
    assert (await b.get(f"/exports/{jid}")).json()["status"] == "expired"
    gone = await b.get(f"/exports/{jid}/download", headers=JSON)
    assert gone.status_code == 409 and gone.json()["current_state"] == "expired"
    out = await run_exports_sweep()
    assert out["expired"] >= 1
    job = await job_row(db, jid)
    assert job.status == "expired" and store.read(key) is None


# --------------------------------------------------------------------------- BE-25 filters


async def test_export_filters_are_applied_or_rejected(client, db, store) -> None:
    admin = await staff(db, "super_admin")
    b = await login(client, admin)
    body = dict(PLATFORM)
    today = clock.now().date()
    bad = await b.post("/exports", {**body, "filters": {"from": "2026-10-01", "to": today.isoformat()}})
    assert bad.status_code == 422 and bad.json()["errors"][0]["code"] == "unsupported_filter"
    future = await b.post("/exports", {**body, "filters": {"to": (today + timedelta(days=3)).isoformat()}})
    assert future.status_code == 422 and future.json()["errors"][0]["code"] == "in_future"
    as_of = (today - timedelta(days=14)).isoformat()
    ok = await b.post("/exports", {**body, "filters": {"to": as_of}})
    assert ok.status_code == 202, ok.text
    jid = ok.json()["export_job_id"]
    assert await run_export(uuid.UUID(jid)) == "ready"
    job = await job_row(db, jid)
    assert job.filters == {"to": as_of}
    assert f"# as_of={as_of}" in (store.read(job.file_s3_key or "") or b"").decode()
