"""PLC-33..35 question error reports: learner report, studio triage queue, resolve + notify."""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from sqlalchemy import select

from app.core.db import system_context
from tests.placement.world import topic


@pytest.fixture
def audited(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    import app.modules.placement.reports as rp

    actions: list[str] = []
    real = rp.audit

    async def spy(session: Any, actor: Any, action: str, *a: Any, **kw: Any) -> Any:
        actions.append(action)
        return await real(session, actor, action, *a, **kw)

    monkeypatch.setattr(rp, "audit", spy)
    return actions


async def _q(world: Any, *, org: uuid.UUID | None = None, publish: bool = True) -> Any:
    from tests.placement.world import question

    t = await topic(world.db, "quant/percentages")
    return await question(
        world.db, world.personas["author"], world.personas["reviewer"], t, org=org, publish=publish
    )


REPORT = {"category": "wrong_answer", "message": "Option B is also correct."}


async def test_report_queue_resolve_and_notify(client, world, audited) -> None:
    q = await _q(world)
    student = world.personas["student"]
    author = world.personas["author"]

    r = await client.post(f"/api/v1/questions/{q.question_id}/reports", json=REPORT, headers=student.headers)
    assert r.status_code == 201, r.text
    rep = r.json()
    assert rep["status"] == "open" and rep["question_id"] == str(q.question_id)
    assert rep["category"] == "wrong_answer" and rep["resolution"] is None

    # One open report per user per question (also when addressed by version id).
    dup = await client.post(f"/api/v1/questions/{q.qv_id}/reports", json=REPORT, headers=student.headers)
    assert dup.status_code == 409 and dup.json()["reason"] == "report_already_open"

    # Another learner (other org) can report a platform question by its version id.
    other = world.personas["student_b"]
    r2 = await client.post(
        f"/api/v1/questions/{q.qv_id}/reports",
        json={"category": "typo", "message": "Typo in the stem"},
        headers=other.headers,
    )
    assert r2.status_code == 201 and r2.json()["question_version_id"] == str(q.qv_id)

    queue = await client.get(
        "/api/v1/studio/question-reports", params={"status": "open"}, headers=author.headers
    )
    assert queue.status_code == 200, queue.text
    body = queue.json()
    ids = [x["report_id"] for x in body["data"]]
    assert rep["report_id"] in ids and r2.json()["report_id"] in ids
    assert body["open_count"] >= 2

    res = await client.post(
        f"/api/v1/studio/question-reports/{rep['report_id']}/resolve",
        json={"resolution": "fixed", "note": "Key corrected in v2."},
        headers=author.headers,
    )
    assert res.status_code == 200, res.text
    out = res.json()
    assert (
        out["status"] == "resolved" and out["resolution"] == "fixed" and out["resolved_by"] == str(author.id)
    )
    assert "question.report_resolved" in audited
    again = await client.post(
        f"/api/v1/studio/question-reports/{rep['report_id']}/resolve",
        json={"resolution": "fixed"},
        headers=author.headers,
    )
    assert again.status_code == 409

    resolved = await client.get(
        "/api/v1/studio/question-reports", params={"status": "resolved"}, headers=author.headers
    )
    assert [x["report_id"] for x in resolved.json()["data"]] == [rep["report_id"]]

    # Reporter notified in-app.
    from app.modules.notifications.models import Notification

    await system_context(world.db, "test.check")
    notes = (
        (
            await world.db.execute(
                select(Notification).where(
                    Notification.user_id == student.id,
                    Notification.template_key == "placement.question_report_resolved",
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(notes) == 1 and notes[0].data["resolution"] == "fixed"

    # After resolution the learner may report again.
    r3 = await client.post(f"/api/v1/questions/{q.question_id}/reports", json=REPORT, headers=student.headers)
    assert r3.status_code == 201


async def test_report_validation_and_visibility(client, world) -> None:
    student = world.personas["student"]
    q = await _q(world)
    url = f"/api/v1/questions/{q.question_id}/reports"
    for bad in (
        {"category": "rude", "message": "x"},
        {"category": "typo", "message": ""},
        {"category": "typo", "message": "x" * 1001},
        {"category": "typo"},
        {"category": "typo", "message": "ok", "extra": 1},
    ):
        r = await client.post(url, json=bad, headers=student.headers)
        assert r.status_code == 400, (bad, r.text)
    blank = await client.post(url, json={"category": "typo", "message": "   "}, headers=student.headers)
    assert blank.status_code == 400

    assert (
        await client.post(f"/api/v1/questions/{uuid.uuid4()}/reports", json=REPORT, headers=student.headers)
    ).status_code == 404
    draft = await _q(world, publish=False)
    r = await client.post(
        f"/api/v1/questions/{draft.question_id}/reports", json=REPORT, headers=student.headers
    )
    assert r.status_code == 404
    # Cross-tenant (single company): a company question is invisible to a public learner who
    # is not a member of the company (RLS -> 404).
    org_q = await _q(world, org=world.org_a)
    public = await world.persona("public_learner")
    r = await client.post(
        f"/api/v1/questions/{org_q.question_id}/reports",
        json=REPORT,
        headers=public.headers,
    )
    assert r.status_code == 404
    # Mismatched version id.
    r = await client.post(
        url, json={**REPORT, "question_version_id": str(org_q.qv_id)}, headers=student.headers
    )
    assert r.status_code == 404


async def test_queue_and_resolve_permissions(client, world) -> None:
    student = world.personas["student"]
    platform_q = await _q(world)
    org_q = await _q(world, org=world.org_a)
    rp = (
        await client.post(
            f"/api/v1/questions/{platform_q.question_id}/reports", json=REPORT, headers=student.headers
        )
    ).json()
    ro = (
        await client.post(
            f"/api/v1/questions/{org_q.question_id}/reports", json=REPORT, headers=student.headers
        )
    ).json()

    # Students cannot reach the studio queue or resolve (even their own report).
    r = await client.get("/api/v1/studio/question-reports", headers=student.headers)
    assert r.status_code == 403
    r = await client.post(
        f"/api/v1/studio/question-reports/{rp['report_id']}/resolve",
        json={"resolution": "invalid"},
        headers=student.headers,
    )
    assert r.status_code == 403

    # A role without question.edit (the batch evaluator) is denied the queue.
    coord = world.personas["evaluator_a"]
    assert (await client.get("/api/v1/studio/question-reports", headers=coord.headers)).status_code == 403

    # Org-scoped editor (trainer A, batch grant in org A) sees org A's report, not the platform one.
    trainer_a = world.personas["trainer_a"]
    q_a = await client.get("/api/v1/studio/question-reports", headers=trainer_a.headers)
    assert q_a.status_code == 200
    ids = {x["report_id"] for x in q_a.json()["data"]}
    assert ro["report_id"] in ids and rp["report_id"] not in ids
    r = await client.post(
        f"/api/v1/studio/question-reports/{rp['report_id']}/resolve",
        json={"resolution": "invalid"},
        headers=trainer_a.headers,
    )
    assert r.status_code == 404

    # Single company: company questions are shared content, so a trainer of another company
    # batch shares the company queue (never the platform report).
    trainer_b = world.personas["trainer_b"]
    q_b = await client.get("/api/v1/studio/question-reports", headers=trainer_b.headers)
    assert q_b.status_code == 200
    ids_b = {x["report_id"] for x in q_b.json()["data"]}
    assert ro["report_id"] in ids_b and rp["report_id"] not in ids_b
    r = await client.post(
        f"/api/v1/studio/question-reports/{ro['report_id']}/resolve",
        json={"resolution": "duplicate", "note": "Same as an earlier report."},
        headers=trainer_a.headers,
    )
    assert r.status_code == 200 and r.json()["resolution"] == "duplicate"

    bad = await client.post(
        f"/api/v1/studio/question-reports/{rp['report_id']}/resolve",
        json={"resolution": "maybe"},
        headers=world.personas["author"].headers,
    )
    assert bad.status_code == 400
    missing = await client.post(
        f"/api/v1/studio/question-reports/{uuid.uuid4()}/resolve",
        json={"resolution": "fixed"},
        headers=world.personas["author"].headers,
    )
    assert missing.status_code == 404


async def test_restricted_principal_cannot_report(client, world) -> None:
    q = await _q(world)
    restricted = await world.persona(
        "restricted", org_ids=(world.org_a,), scope="restricted", restriction_level=2
    )
    r = await client.post(
        f"/api/v1/questions/{q.question_id}/reports", json=REPORT, headers=restricted.headers
    )
    assert r.status_code == 403 and r.json()["code"] == "account_restricted"
