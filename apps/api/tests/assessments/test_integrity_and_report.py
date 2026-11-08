"""Assessments: advisory integrity flags (ASM-19), review decisions (ASM-20), invalidation
(ASM-18) and the test report (ASM-22)."""

from __future__ import annotations

import os
import uuid
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from typing import Any

import pytest

from app.core.db import system_context
from app.core.ids import uuid7
from app.core.time import utcnow
from app.modules.assessments import integrity as integ
from app.modules.assessments.models import (
    AttemptEvent,
    AttemptResponse,
    AttemptResult,
    TestAttempt,
    TestSection,
)
from app.modules.assessments.report import K_MIN_ITEM, point_biserial
from tests.assessments.test_attempts import fixed, make_bank, make_test, sql, standard
from tests.identity.factory import add_member, make_user
from tests.placement.world import Persona, World, idem

API = "/api/v1"


# --------------------------------------------------------------------------- helpers


@pytest.fixture
def audits(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, dict[str, Any]]]:
    """Spy on ``audit()`` (td_app cannot read audit_outbox)."""
    seen: list[tuple[str, dict[str, Any]]] = []
    orig = integ.audit

    async def spy(session: Any, actor: Any, action: str, *a: Any, **kw: Any) -> Any:
        seen.append((action, kw))
        return await orig(session, actor, action, *a, **kw)

    monkeypatch.setattr(integ, "audit", spy)
    return seen


def stepped_up(w: World, who: Persona) -> dict[str, str]:
    p = replace(who.principal, last_step_up_at=utcnow())
    return w.auth.login(p)


async def events(db: Any, attempt_id: str, kind: str, n: int) -> None:
    await system_context(db, "test.factory")
    att = await db.get(TestAttempt, uuid.UUID(attempt_id))
    for i in range(n):
        db.add(
            AttemptEvent(
                id=uuid7(),
                occurred_at=utcnow(),
                attempt_id=att.id,
                user_id=att.user_id,
                organization_id=att.organization_id,
                event_type=kind,
                client_seq=1000 + i,
                payload={"advisory": True},
                ip="203.0.113.7",
            )
        )
    await db.flush()


async def flagged_attempt(db: Any, w: World, client: Any, *, submit: bool = True) -> tuple[uuid.UUID, str]:
    test_id, _, body = await standard(db, w, client)
    aid = body["attempt_id"]
    await events(db, aid, "focus_lost", integ.FOCUS_LOST_REVIEW_MIN + 1)
    await events(db, aid, "paste", 1)  # below threshold: counted, not a reason
    if submit:
        r = await client.post(
            f"{API}/attempts/{aid}/submit", json={}, headers={**w.personas["student"].headers, **idem()}
        )
        assert r.status_code == 200, r.text
    return test_id, aid


async def platform_admin(w: World) -> Persona:
    return await w.persona(
        "sec", grants=(("super_admin", "platform", None),), is_platform=True, tier="privileged"
    )


# --------------------------------------------------------------------------- ASM-19


async def test_flags_list_scoped_and_without_ips(client, world: World, db) -> None:
    test_id, aid = await flagged_attempt(db, world, client)
    # an unflagged attempt of legacy org B's student stays out of everyone's queue
    trainer = world.personas["trainer_a"]
    r = await client.get(f"{API}/integrity/flags", headers=trainer.headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert [f["attempt_id"] for f in body["data"]] == [aid]
    f = body["data"][0]
    assert f["status"] == "open" and f["decision"] is None
    assert f["signals"]["focus_lost"] == integ.FOCUS_LOST_REVIEW_MIN + 1 and f["signals"]["paste"] == 1
    assert [x["code"] for x in f["reasons"]] == ["focus_lost"]
    assert f["recommendation"] == "review_recommended" and f["test_id"] == str(test_id)
    assert body["thresholds"]["focus_lost"] == integ.FOCUS_LOST_REVIEW_MIN
    assert "203.0.113" not in r.text and "ip" not in f
    assert body["page"]["has_more"] is False
    # filters
    r = await client.get(f"{API}/integrity/flags", params={"status": "decided"}, headers=trainer.headers)
    assert r.json()["data"] == []
    r = await client.get(f"{API}/integrity/flags", params={"test_id": str(uuid7())}, headers=trainer.headers)
    assert r.json()["data"] == []
    r = await client.get(
        f"{API}/integrity/flags", params={"batch_id": str(world.batch_a)}, headers=trainer.headers
    )
    assert len(r.json()["data"]) == 1
    # the batch evaluator and a platform Admin see it
    r = await client.get(f"{API}/integrity/flags", headers=world.personas["evaluator_a"].headers)
    assert [x["attempt_id"] for x in r.json()["data"]] == [aid]
    sec = await platform_admin(world)
    r = await client.get(f"{API}/integrity/flags", headers=sec.headers)
    assert aid in [x["attempt_id"] for x in r.json()["data"]]
    # cross-tenant trainer: invisible; student: no permission
    r = await client.get(f"{API}/integrity/flags", headers=world.personas["trainer_b"].headers)
    assert r.status_code == 200 and r.json()["data"] == []
    r = await client.get(f"{API}/integrity/flags", headers=world.personas["student"].headers)
    assert r.status_code == 403 and r.json()["code"] == "permission_denied"


async def test_flags_cursor_pagination_and_validation(client, world: World, db) -> None:
    _, qs = await make_bank(db, world)
    ids = []
    for i in range(3):
        s = await world.persona(f"stu{i}", org_ids=(world.org_a,))
        await add_member(db, world.org_a, s.id, "student", world.batch_a)
    test_id = await make_test(db, world, [("S", None, [fixed(qs[0])])], duration_seconds=600)
    from tests.assessments.test_attempts import assign, start

    await assign(db, world, test_id)
    for i in range(3):
        r = await start(client, world.personas[f"stu{i}"], test_id)
        assert r.status_code == 201, r.text
        ids.append(r.json()["attempt_id"])
        await events(db, ids[-1], "fullscreen_exit", integ.FULLSCREEN_EXIT_REVIEW_MIN)
    h = world.personas["trainer_a"].headers
    r = await client.get(f"{API}/integrity/flags", params={"limit": 2}, headers=h)
    p1 = r.json()
    assert len(p1["data"]) == 2 and p1["page"]["has_more"] is True
    r = await client.get(
        f"{API}/integrity/flags", params={"limit": 2, "cursor": p1["page"]["next_cursor"]}, headers=h
    )
    p2 = r.json()
    assert len(p2["data"]) == 1 and p2["page"]["has_more"] is False
    assert {x["attempt_id"] for x in p1["data"] + p2["data"]} == set(ids)
    r = await client.get(f"{API}/integrity/flags", params={"cursor": "garbage"}, headers=h)
    assert r.status_code == 400 and r.json()["code"] == "invalid_cursor"
    r = await client.get(f"{API}/integrity/flags", params={"status": "nope"}, headers=h)
    assert r.status_code in (400, 422)
    r = await client.get(f"{API}/integrity/flags", params={"limit": 0}, headers=h)
    assert r.status_code in (400, 422)


# --------------------------------------------------------------------------- ASM-20 / ASM-18


async def test_decision_no_action_idempotent_and_audited(client, world: World, db, audits) -> None:
    _, aid = await flagged_attempt(db, world, client)
    trainer = world.personas["trainer_a"]
    url = f"{API}/attempts/{aid}/integrity-decision"
    body = {"outcome": "no_action", "note": "Student explained the power cut."}
    key = idem()
    r = await client.post(url, json=body, headers={**trainer.headers, **key})
    assert r.status_code == 201, r.text
    d = r.json()
    assert d["outcome"] == "no_action" and d["integrity_status"] == "cleared"
    assert d["attempt_status"] in ("submitted", "graded")
    r2 = await client.post(url, json=body, headers={**trainer.headers, **key})
    assert r2.status_code == 201 and r2.json()["decision_id"] == d["decision_id"]
    r3 = await client.post(url, json=body, headers=trainer.headers)  # natural dedupe, no key
    assert r3.status_code == 200 and r3.json()["decision_id"] == d["decision_id"]
    assert r3.json()["replayed"] is True
    rows = await sql(db, "SELECT outcome FROM attempt_integrity_decisions WHERE attempt_id = :a", a=aid)
    assert [x[0] for x in rows] == ["no_action"]
    assert [a for a, _ in audits] == ["attempt.integrity_decided"]
    assert audits[0][1]["reason"] == body["note"]
    # flag now shows as decided
    r = await client.get(f"{API}/integrity/flags", params={"status": "decided"}, headers=trainer.headers)
    f = r.json()["data"][0]
    assert f["status"] == "decided" and f["decision"]["outcome"] == "no_action"
    # student never sees the score changed
    st = await sql(db, "SELECT status, integrity_status FROM test_attempts WHERE id = :a", a=aid)
    assert st[0][1] == "cleared" and st[0][0] != "invalidated"


async def test_decision_validation_and_denials(client, world: World, db) -> None:
    _, aid = await flagged_attempt(db, world, client)
    url = f"{API}/attempts/{aid}/integrity-decision"
    trainer = world.personas["trainer_a"]
    r = await client.post(url, json={"outcome": "no_action"}, headers=trainer.headers)
    assert r.status_code in (400, 422)
    r = await client.post(url, json={"outcome": "ban", "note": "nope nope"}, headers=trainer.headers)
    assert r.status_code in (400, 422)
    r = await client.post(url, json={"outcome": "no_action", "note": "x"}, headers=trainer.headers)
    assert r.status_code in (400, 422)
    ok = {"outcome": "no_action", "note": "looks fine"}
    # cross-tenant trainer -> 404
    r = await client.post(url, json=ok, headers=world.personas["trainer_b"].headers)
    assert r.status_code == 404
    # the student themself -> 403
    r = await client.post(url, json=ok, headers=world.personas["student"].headers)
    assert r.status_code == 403 and r.json()["code"] == "permission_denied"
    # restricted principal (L3 read-only session) is refused by the principal gate
    p = replace(trainer.principal, scope="restricted", restriction_level=3)
    r = await client.post(url, json=ok, headers=world.auth.login(p))
    assert r.status_code == 403
    r = await client.get(f"{API}/integrity/flags", headers=world.auth.login(p))
    assert r.status_code == 403
    rows = await sql(db, "SELECT count(*) FROM attempt_integrity_decisions WHERE attempt_id = :a", a=aid)
    assert rows[0][0] == 0


async def test_decision_invalidate_needs_step_up_and_notifies(client, world: World, db, audits) -> None:
    _, aid = await flagged_attempt(db, world, client)
    trainer = world.personas["trainer_a"]
    url = f"{API}/attempts/{aid}/integrity-decision"
    body = {"outcome": "invalidate", "note": "Confirmed with proctor footage."}
    r = await client.post(url, json=body, headers=trainer.headers)
    assert r.status_code == 401 and r.json()["code"] == "step_up_required"
    h = stepped_up(world, trainer)
    r = await client.post(url, json=body, headers=h)
    assert r.status_code == 201, r.text
    assert r.json()["attempt_status"] == "invalidated" and r.json()["integrity_status"] == "invalidated"
    st = await sql(db, "SELECT status, integrity_status FROM test_attempts WHERE id = :a", a=aid)
    assert tuple(st[0]) == ("invalidated", "invalidated")
    ev = await sql(db, "SELECT event_type FROM attempt_events WHERE attempt_id = :a", a=aid)
    assert "invalidate" in [e[0] for e in ev]
    n = await sql(
        db,
        "SELECT template_key, data FROM notifications WHERE user_id = :u",
        u=world.personas["student"].id,
    )
    assert any(t == "assessment.attempt_invalidated" and d["attempt_id"] == aid for t, d in n)
    assert {a for a, _ in audits} == {"attempt.invalidated", "attempt.integrity_decided"}
    # cannot change after invalidation
    r = await client.post(url, json={"outcome": "no_action", "note": "changed my mind"}, headers=h)
    assert r.status_code == 409 and r.json()["code"] == "invalid_state_transition"
    # security reviewer may decide but not invalidate (no attempt.invalidate)
    _, aid2 = await flagged_attempt_for(db, world, client)
    sec = await platform_admin(world)
    r = await client.post(
        f"{API}/attempts/{aid2}/integrity-decision", json=body, headers=stepped_up(world, sec)
    )
    assert r.status_code == 403 and r.json()["permission"] == "attempt.invalidate"


async def flagged_attempt_for(db: Any, w: World, client: Any) -> tuple[uuid.UUID, str]:
    """A second flagged attempt by a fresh batch-A student."""
    s = await w.persona(f"stu_{uuid7().hex[:6]}", org_ids=(w.org_a,))
    await add_member(db, w.org_a, s.id, "student", w.batch_a)
    _, qs = await make_bank(db, w)
    test_id = await make_test(db, w, [("S", None, [fixed(qs[0])])], duration_seconds=600)
    from tests.assessments.test_attempts import assign, start

    await assign(db, w, test_id)
    r = await start(client, s, test_id)
    aid = r.json()["attempt_id"]
    await events(db, aid, "disconnect", integ.DISCONNECT_REVIEW_MIN)
    await client.post(f"{API}/attempts/{aid}/submit", json={}, headers={**s.headers, **idem()})
    return test_id, aid


async def test_decision_in_progress_cannot_be_invalidated(client, world: World, db) -> None:
    _, aid = await flagged_attempt(db, world, client, submit=False)
    h = stepped_up(world, world.personas["trainer_a"])
    r = await client.post(
        f"{API}/attempts/{aid}/integrity-decision",
        json={"outcome": "invalidate", "note": "too early"},
        headers=h,
    )
    assert r.status_code == 409 and r.json()["code"] == "invalid_state_transition"
    r = await client.post(f"{API}/attempts/{aid}/invalidate", json={"reason": "too early"}, headers=h)
    assert r.status_code == 409


async def test_refer_security_opens_integrity_referral_case(client, world: World, db) -> None:
    _, aid = await flagged_attempt(db, world, client)
    sec = await platform_admin(world)
    r = await client.post(
        f"{API}/attempts/{aid}/integrity-decision",
        json={"outcome": "refer_security", "note": "Pattern matches a known answer-sharing ring."},
        headers=sec.headers,
    )
    assert r.status_code == 201, r.text
    ref = r.json()["security_case_ref"]
    assert ref and r.json()["integrity_status"] == "review_recommended"
    rows = await sql(
        db,
        "SELECT opened_reason, user_id FROM security_cases WHERE case_ref = :r",
        r=ref,
    )
    assert rows[0][0] == "integrity_referral" and rows[0][1] == world.personas["student"].id
    notes = await sql(
        db,
        "SELECT body FROM case_notes n JOIN security_cases c ON c.id = n.case_id WHERE c.case_ref = :r",
        r=ref,
    )
    assert any(aid in b[0] and "focus_lost" in b[0] for b in notes)


async def test_asm18_invalidate(client, world: World, db, audits) -> None:
    _, aid = await flagged_attempt(db, world, client)
    url = f"{API}/attempts/{aid}/invalidate"
    r = await client.post(url, json={"reason": "x"}, headers=stepped_up(world, world.personas["trainer_a"]))
    assert r.status_code in (400, 422)
    r = await client.post(url, json={"reason": "impersonation"}, headers=world.personas["trainer_a"].headers)
    assert r.status_code == 401 and r.json()["code"] == "step_up_required"
    r = await client.post(
        url, json={"reason": "impersonation"}, headers=stepped_up(world, world.personas["trainer_b"])
    )
    assert r.status_code == 404
    r = await client.post(
        url, json={"reason": "impersonation"}, headers=stepped_up(world, world.personas["student"])
    )
    assert r.status_code == 403
    r = await client.post(
        url, json={"reason": "impersonation"}, headers=stepped_up(world, world.personas["trainer_a"])
    )
    assert r.status_code == 200, r.text
    assert r.json() == {"attempt_id": aid, "status": "invalidated", "integrity_status": "invalidated"}
    assert [a for a, _ in audits] == ["attempt.invalidated"]
    r = await client.post(
        url, json={"reason": "impersonation"}, headers=stepped_up(world, world.personas["trainer_a"])
    )
    assert r.status_code == 409


# --------------------------------------------------------------------------- ASM-22


async def seed_graded(
    db: Any, w: World, test_id: uuid.UUID, n: int, *, batch: uuid.UUID | None = None
) -> list[uuid.UUID]:
    """``n`` graded attempts: student i answers question j correctly iff j <= i % (questions+1)."""
    await system_context(db, "test.factory")
    from sqlalchemy import select

    sec = (await db.execute(select(TestSection).where(TestSection.test_id == test_id))).scalars().first()
    rule_qvs = await sql(
        db,
        "SELECT r.question_version_id, r.question_id FROM test_section_rules r "
        "WHERE r.test_section_id = :s ORDER BY r.position",
        s=sec.id,
    )
    qvs = []
    for qv, qid in rule_qvs:
        if qv is None:
            qv = (
                await sql(
                    db,
                    "SELECT id FROM question_versions WHERE question_id = :q ORDER BY version_no DESC LIMIT 1",
                    q=qid,
                )
            )[0][0]
        qvs.append(qv)
    await system_context(db, "test.factory")
    ids = []
    now = utcnow()
    for i in range(n):
        u = await make_user(db)
        await system_context(db, "test.factory")
        aid = uuid7()
        k = i % (len(qvs) + 1)
        correct = [j < k for j in range(len(qvs))]
        db.add(
            TestAttempt(
                id=aid,
                test_id=test_id,
                test_version=1,
                user_id=u.id,
                organization_id=w.org_a,
                batch_id=batch or w.batch_a,
                attempt_no=1,
                status="graded",
                selection_seed=os.urandom(16),
                layout={},
                started_at=now - timedelta(minutes=30),
                submitted_at=now,
                submit_reason="user" if i % 3 else "deadline",
                idempotency_key=f"seed-{aid}",
            )
        )
        await db.flush()
        for j, qv in enumerate(qvs):
            db.add(
                AttemptResponse(
                    id=uuid7(),
                    attempt_id=aid,
                    user_id=u.id,
                    organization_id=w.org_a,
                    test_section_id=sec.id,
                    question_version_id=qv,
                    response={},
                    client_seq=j,
                    time_spent_ms=10_000,
                    is_correct=correct[j],
                )
            )
        pct = Decimal(100 * sum(correct) / len(qvs)).quantize(Decimal("0.01"))
        db.add(
            AttemptResult(
                attempt_id=aid,
                user_id=u.id,
                organization_id=w.org_a,
                test_id=test_id,
                score=Decimal(sum(correct)),
                max_score=Decimal(len(qvs)),
                percentage=pct,
                correct_count=sum(correct),
                incorrect_count=len(qvs) - sum(correct),
                unanswered_count=0,
                time_taken_seconds=600,
                section_scores=[],
                topic_scores=[],
            )
        )
        await db.flush()
        ids.append(aid)
    return ids


async def report_test(db: Any, w: World) -> uuid.UUID:
    _, qs = await make_bank(db, w)
    return await make_test(db, w, [("Quant", None, [fixed(q) for q in qs])], duration_seconds=1800)


async def test_report_full_with_item_analysis(client, world: World, db) -> None:
    test_id = await report_test(db, world)
    await seed_graded(db, world, test_id, K_MIN_ITEM + 2)
    r = await client.get(f"{API}/tests/{test_id}/report", headers=world.personas["trainer_a"].headers)
    assert r.status_code == 200, r.text
    rep = r.json()
    assert rep["scope"] == "full" and rep["attempts_count"] == K_MIN_ITEM + 2
    assert sum(b["count"] for b in rep["distribution"]["buckets"]) == K_MIN_ITEM + 2
    assert len(rep["distribution"]["buckets"]) == 10
    sub = rep["submissions"]
    assert sub["submitted"] + sub["auto_submitted"] == sub["total"] and sub["auto_submitted"] == 4
    assert rep["sections"][0]["avg_time_seconds"] == 40.0 and rep["sections"][0]["attempts"] == 12
    items = rep["items"]
    assert items["suppressed"] is False and len(items["data"]) == 4
    first = items["data"][0]
    assert first["suppressed"] is False and 0 < first["difficulty_p"] < 1
    assert first["discrimination"] is not None and first["discrimination"] > 0
    # cross-tenant trainer: test is a platform test, but none of the attempts are in scope
    r = await client.get(f"{API}/tests/{test_id}/report", headers=world.personas["trainer_b"].headers)
    assert r.status_code == 200 and r.json()["attempts_count"] == 0
    assert r.json()["items"]["suppressed"] is True
    # student: no permission
    r = await client.get(f"{API}/tests/{test_id}/report", headers=world.personas["student"].headers)
    assert r.status_code == 403
    # unknown test
    r = await client.get(f"{API}/tests/{uuid7()}/report", headers=world.personas["trainer_a"].headers)
    assert r.status_code == 404


async def test_report_k_floor_suppression_and_content_manager(client, world: World, db) -> None:
    test_id = await report_test(db, world)
    await seed_graded(db, world, test_id, K_MIN_ITEM - 1)
    h = world.personas["admin"].headers
    rep = (await client.get(f"{API}/tests/{test_id}/report", headers=h)).json()
    assert rep["attempts_count"] == K_MIN_ITEM - 1
    assert rep["items"]["suppressed"] is True and rep["items"]["data"] == []
    assert rep["distribution"] is not None
    # batch filter
    rep = (
        await client.get(f"{API}/tests/{test_id}/report", params={"batch_id": str(world.batch_a2)}, headers=h)
    ).json()
    assert rep["attempts_count"] == 0
    # content managers get item statistics only
    await seed_graded(db, world, test_id, 2)
    rep = (await client.get(f"{API}/tests/{test_id}/report", headers=world.personas["author"].headers)).json()
    assert rep["scope"] == "item_stats_only"
    assert rep["distribution"] is None and rep["submissions"] is None and rep["sections"] is None
    assert rep["items"]["suppressed"] is False and all(not i["suppressed"] for i in rep["items"]["data"])


def test_point_biserial() -> None:
    assert point_biserial([1, 0], [1.0, 1.0]) is None
    assert point_biserial([1, 1, 1], [1.0, 2.0, 3.0]) is None
    r = point_biserial([0, 0, 1, 1], [10.0, 20.0, 80.0, 90.0])
    assert r is not None and 0.9 < r <= 1.0
