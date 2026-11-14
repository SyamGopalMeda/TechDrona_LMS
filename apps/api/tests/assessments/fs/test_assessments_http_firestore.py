"""Assessments HTTP API through the FastAPI app on Firestore with no Postgres
(``TD_STORE_ASSESSMENTS=firestore``; request session = ``MemoryTx``): author -> publish ->
override -> attempt -> autosave -> submit -> grade -> result, integrity decisions, idempotency
and the one-open-attempt rule."""

from __future__ import annotations

import uuid
from typing import Any

from app.modules.identity import clock

FS_MODULES = (
    "assessments",
    "placement",
    "coding",
    "core",
    "audit",
    "identity",
    "sessions",
    "rbac",
    "notifications",
    "orgs",
    "entitlements",
    "ai",
    "analytics",
    "security",
    "learning",
    "paths",
    "admin",
)
P = "/api/v1"


STAFF_PERMS = (
    "taxonomy.manage",
    "question.create",
    "question.edit",
    "question.review",
    "question.publish",
    "question.answer_key.read",
    "test.create",
    "test.edit",
    "test.assign",
    "test.override.grant",
    "test.results.read",
    "test.results.release",
    "integrity.flag.read",
    "integrity.flag.decide",
    "attempt.invalidate",
)


def _idem() -> dict[str, str]:
    return {"Idempotency-Key": str(uuid.uuid4())}


def _staff(make_principal: Any, auth: Any) -> dict[str, str]:
    p = make_principal(
        is_platform=True, roles=("admin",), tier="privileged", last_step_up_at=clock.now(), is_minor=False
    )
    for perm in STAFF_PERMS:
        auth.grant(p, perm)
    return auth.login(p)


async def _question(
    client: Any, author: dict[str, str], reviewer: dict[str, str], body: dict[str, Any]
) -> str:
    r = await client.post(f"{P}/studio/questions", json=body, headers={**author, **_idem()})
    assert r.status_code == 201, r.text
    qid = r.json()["question_id"]
    assert (await client.post(f"{P}/studio/questions/{qid}/submit-review", headers=author)).status_code == 200
    rv = await client.post(
        f"{P}/studio/questions/{qid}/review", json={"decision": "approve"}, headers=reviewer
    )
    assert rv.status_code == 200, rv.text
    pub = await client.post(f"{P}/studio/questions/{qid}/publish", headers=reviewer)
    assert pub.status_code == 200, pub.text
    return qid


async def _published_test(
    client: Any, author: dict[str, str], reviewer: dict[str, str]
) -> tuple[str, str, str]:
    topic = await client.post(f"{P}/studio/topics", json={"slug": "apt", "name": "Aptitude"}, headers=author)
    tid = topic.json()["id"]
    mcq = await _question(
        client,
        author,
        reviewer,
        {
            "question_type": "mcq_single",
            "primary_topic_id": tid,
            "stem_html": "<p>2+2?</p>",
            "options": [{"html": "4", "is_correct": True}, {"html": "5"}],
            "explanation_html": "<p>x</p>",
            "difficulty": 2,
        },
    )
    essay = await _question(
        client,
        author,
        reviewer,
        {
            "question_type": "essay",
            "primary_topic_id": tid,
            "stem_html": "<p>Explain recursion.</p>",
            "explanation_html": "<p>A function calling itself.</p>",
            "difficulty": 3,
        },
    )
    t = await client.post(
        f"{P}/studio/tests",
        json={"title": "Mock 1", "test_kind": "mock", "duration_seconds": 1800, "attempts_allowed": 2},
        headers={**author, **_idem()},
    )
    assert t.status_code == 201, t.text
    test_id = t.json()["id"]
    secs = await client.put(
        f"{P}/studio/tests/{test_id}/sections",
        json={
            "sections": [
                {
                    "title": "Section A",
                    "rules": [
                        {"rule_type": "fixed", "question_id": mcq, "marks_each": "2"},
                        {"rule_type": "fixed", "question_id": essay, "marks_each": "5"},
                    ],
                }
            ]
        },
        headers=author,
    )
    assert secs.status_code == 200, secs.text
    pub = await client.post(f"{P}/studio/tests/{test_id}/publish", headers={**author, **_idem()})
    assert pub.status_code == 200, pub.text
    return test_id, mcq, essay


async def test_author_attempt_grade_result(fs_http: Any, allow_access: Any, make_principal: Any) -> None:
    # allow_access after fs_http: app creation (wiring) registers the real entitlement checker, whose
    # test->course resolver (wiring.test_parents) is not under test here
    client, _rec, auth = fs_http
    author, reviewer = _staff(make_principal, auth), _staff(make_principal, auth)
    test_id, _mcq, _essay = await _published_test(client, author, reviewer)

    learner = make_principal(is_minor=False)
    hl = auth.login(learner)
    ov = await client.post(
        f"{P}/tests/{test_id}/overrides",
        json={"user_id": str(learner.user_id), "extra_time_seconds": 600, "reason": "Accommodation"},
        headers={**author, **_idem()},
    )
    assert ov.status_code in (200, 201), ov.text

    key = _idem()
    st = await client.post(f"{P}/attempts", json={"test_id": test_id}, headers={**hl, **key})
    assert st.status_code == 201, st.text
    att = st.json()
    aid = att["attempt_id"]
    replay = await client.post(f"{P}/attempts", json={"test_id": test_id}, headers={**hl, **key})
    assert replay.status_code == 201 and replay.json()["attempt_id"] == aid
    again = await client.post(f"{P}/attempts", json={"test_id": test_id}, headers={**hl, **_idem()})
    assert again.status_code == 409 and again.json()["code"] == "active_attempt_exists", again.text

    questions = [q for sec in att["sections"] for q in sec.get("questions", [])]
    assert len(questions) == 2, att["sections"]
    by_type = {q["type"]: q for q in questions}
    m, e = by_type["mcq_single"], by_type["essay"]
    save = await client.post(
        f"{P}/attempts/{aid}/autosave",
        json={
            "items": [
                {
                    "question_version_id": m["question_version_id"],
                    "response": {"option_ids": [m["options"][0]["option_id"]]},
                    "client_seq": 1,
                },
                {
                    "question_version_id": e["question_version_id"],
                    "response": {"text": "It calls itself."},
                    "client_seq": 2,
                },
            ]
        },
        headers=hl,
    )
    assert save.status_code == 200, save.text
    sub = await client.post(f"{P}/attempts/{aid}/submit", json={}, headers={**hl, **_idem()})
    assert sub.status_code == 200, sub.text

    ev = await client.get(f"{P}/attempts/{aid}/evaluation", headers=author)
    assert ev.status_code == 200, ev.text
    grade = await client.post(
        f"{P}/attempts/{aid}/items/{e['question_version_id']}/grade",
        json={"marks": "4", "feedback": "Good"},
        headers={**reviewer, **_idem()},
    )
    assert grade.status_code == 200, grade.text

    res = await client.get(f"{P}/attempts/{aid}/result", headers=hl)
    assert res.status_code == 200, res.text
    mine = await client.get(f"{P}/me/attempts", headers=hl)
    assert mine.status_code == 200 and mine.json()["items"][0]["attempt_id"] == aid, mine.text
    other = auth.login(make_principal())
    assert (await client.get(f"{P}/attempts/{aid}/result", headers=other)).status_code == 404

    dec = await client.post(
        f"{P}/attempts/{aid}/integrity-decision",
        json={"outcome": "no_action", "note": "Reviewed, fine"},
        headers={**author, **_idem()},
    )
    assert dec.status_code in (200, 201), dec.text
    listing = await client.get(f"{P}/tests/{test_id}/attempts", headers=author)
    assert listing.status_code == 200, listing.text


async def _batch_with(learner_id: Any, staff_id: Any) -> Any:
    """A company batch with the learner (orgs on Firestore, through its public API)."""
    from datetime import UTC, datetime

    from app.core.company import COMPANY_ORG_ID
    from app.core.ids import uuid7
    from app.modules.orgs import public as orgs_public
    from app.modules.orgs.models import Batch, BatchMember

    now = datetime.now(UTC)
    b = Batch(
        id=uuid7(),
        organization_id=COMPANY_ORG_ID,
        name="Batch A",
        code=f"B{uuid7().hex[-6:]}",
        status="active",
        created_by=staff_id,
        created_at=now,
        updated_at=now,
    )
    await orgs_public.add_batch(None, b)  # type: ignore[arg-type]
    await orgs_public.add_batch_member(
        None,  # type: ignore[arg-type]
        BatchMember(
            id=uuid7(),
            batch_id=b.id,
            organization_id=COMPANY_ORG_ID,
            user_id=learner_id,
            member_role="student",
            status="active",
            added_by=staff_id,
            added_at=now,
            updated_at=now,
        ),
    )
    return b


async def test_assignment_release_invalidate_and_studio(
    fs_http: Any, allow_access: Any, make_principal: Any
) -> None:
    from datetime import UTC, datetime, timedelta

    client, _rec, auth = fs_http
    author, reviewer = _staff(make_principal, auth), _staff(make_principal, auth)
    test_id, _mcq, _essay = await _published_test(client, author, reviewer)
    from app.core.company import COMPANY_ORG_ID

    # a batch student's principal carries the company organisation (TN visibility of assignments)
    learner = make_principal(is_minor=False, org_ids=(COMPANY_ORG_ID,))
    hl = auth.login(learner)
    batch = await _batch_with(learner.user_id, uuid.uuid4())

    now = datetime.now(UTC)
    asg = await client.post(
        f"{P}/tests/{test_id}/assignments",
        json={
            "batch_id": str(batch.id),
            "available_from": (now - timedelta(minutes=5)).isoformat(),
            "available_until": (now + timedelta(days=1)).isoformat(),
            "release_mode": "manual",
        },
        headers={**author, **_idem()},
    )
    assert asg.status_code == 201, asg.text
    aid_asg = asg.json()["id"]
    assert [
        a["id"]
        for a in (await client.get(f"{P}/tests/{test_id}/assignments", headers=author)).json()["items"]
    ] == [aid_asg]
    patched = await client.patch(
        f"{P}/test-assignments/{aid_asg}", json={"attempts_allowed": 1}, headers=author
    )
    assert patched.status_code == 200, patched.text

    mine = await client.get(f"{P}/me/tests", headers=hl)
    assert mine.status_code == 200, mine.text
    detail = await client.get(f"{P}/tests/{test_id}", headers=hl)
    assert detail.status_code == 200, detail.text

    st = await client.post(
        f"{P}/attempts", json={"test_id": test_id, "test_assignment_id": aid_asg}, headers={**hl, **_idem()}
    )
    assert st.status_code == 201, st.text
    att_id = st.json()["attempt_id"]
    assert (await client.get(f"{P}/attempts/{att_id}/time", headers=hl)).status_code == 200
    assert (await client.get(f"{P}/attempts/{att_id}/state", headers=hl)).status_code == 200
    sub = await client.post(
        f"{P}/attempts/{att_id}/submit", json={"confirm_unanswered": 2}, headers={**hl, **_idem()}
    )
    assert sub.status_code == 200, sub.text
    # attempt limit 1 on the assignment
    again = await client.post(
        f"{P}/attempts", json={"test_id": test_id, "test_assignment_id": aid_asg}, headers={**hl, **_idem()}
    )
    assert again.status_code == 409 and again.json()["code"] == "attempt_limit_reached", again.text

    rel = await client.post(
        f"{P}/tests/{test_id}/results/release",
        json={"test_assignment_id": aid_asg},
        headers={**author, **_idem()},
    )
    assert rel.status_code == 200, rel.text
    assert (await client.get(f"{P}/attempts/{att_id}/result", headers=hl)).status_code == 200
    assert (await client.get(f"{P}/attempts/{att_id}/review", headers=hl)).status_code == 200

    flags = await client.get(f"{P}/integrity/flags", headers=author)
    assert flags.status_code == 200, flags.text
    inv = await client.post(
        f"{P}/attempts/{att_id}/invalidate",
        json={"reason": "Impersonation confirmed"},
        headers={**author, **_idem()},
    )
    assert inv.status_code == 200, inv.text
    rep = await client.get(f"{P}/tests/{test_id}/report", headers=author)
    assert rep.status_code == 200, rep.text
    ev = await client.get(f"{P}/tests/{test_id}/evaluation", headers=author)
    assert ev.status_code == 200, ev.text
    ovs = await client.get(f"{P}/tests/{test_id}/overrides", headers=author)
    assert ovs.status_code == 200, ovs.text

    listed = await client.get(f"{P}/studio/tests", headers=author)
    assert listed.status_code == 200 and test_id in {t["id"] for t in listed.json()["items"]}, listed.text
    got = await client.get(f"{P}/studio/tests/{test_id}", headers=author)
    assert got.status_code == 200, got.text
    val = await client.post(f"{P}/studio/tests/{test_id}/validate", headers=author)
    assert val.status_code == 200, val.text
    arch = await client.post(f"{P}/studio/tests/{test_id}/archive", headers={**author, **_idem()})
    assert arch.status_code == 200, arch.text


async def test_jobs_and_erasure(fs_http: Any, allow_access: Any, make_principal: Any) -> None:
    """The attempt sweeper closes an overdue attempt; erasure scrubs the learner's attempts."""
    from datetime import UTC, datetime, timedelta

    from sqlalchemy import select

    from app.core.firestore.sqlstore import store_session
    from app.modules.assessments import datastore as adb
    from app.modules.assessments import privacy, tasks
    from app.modules.assessments.models import TestAttempt

    client, _rec, auth = fs_http
    author, reviewer = _staff(make_principal, auth), _staff(make_principal, auth)
    test_id, _m, _e = await _published_test(client, author, reviewer)
    learner = make_principal(is_minor=False)
    hl = auth.login(learner)
    st = await client.post(f"{P}/attempts", json={"test_id": test_id}, headers={**hl, **_idem()})
    att_id = uuid.UUID(st.json()["attempt_id"])
    from app.core.db import system_context

    async with store_session() as s:  # push the deadline into the past (as time passing would)
        await system_context(s, "test.clock")
        a = (await adb.execute(s, select(TestAttempt).where(TestAttempt.id == att_id))).scalar_one()
        a.deadline_at = datetime.now(UTC) - timedelta(hours=1)
    closed = await tasks.run_once()
    assert closed >= 1
    async with store_session() as s:
        await system_context(s, "test.read")
        a = (await adb.execute(s, select(TestAttempt).where(TestAttempt.id == att_id))).scalar_one()
        assert a.status != "in_progress"
    async with store_session() as s:
        out = await privacy.erase_user(s, learner.user_id)
    assert isinstance(out, dict)


async def test_sequential_sections_resume_and_rebind_override(
    fs_http: Any, allow_access: Any, make_principal: Any
) -> None:
    client, _rec, auth = fs_http
    author, reviewer = _staff(make_principal, auth), _staff(make_principal, auth)
    topic = await client.post(f"{P}/studio/topics", json={"slug": "seq", "name": "Seq"}, headers=author)
    tid = topic.json()["id"]
    qids = []
    for i in range(2):
        qids.append(
            await _question(
                client,
                author,
                reviewer,
                {
                    "question_type": "mcq_single",
                    "primary_topic_id": tid,
                    "stem_html": f"<p>Q{i}</p>",
                    "options": [{"html": "a", "is_correct": True}, {"html": "b"}],
                    "explanation_html": "<p>x</p>",
                    "difficulty": 2,
                },
            )
        )
    t = await client.post(
        f"{P}/studio/tests",
        json={"title": "Seq", "test_kind": "mock", "duration_seconds": 1800, "navigation_mode": "sequential"},
        headers={**author, **_idem()},
    )
    test_id = t.json()["id"]
    patch = await client.patch(f"{P}/studio/tests/{test_id}", json={"grace_seconds": 30}, headers=author)
    assert patch.status_code == 200, patch.text
    await client.put(
        f"{P}/studio/tests/{test_id}/sections",
        json={
            "sections": [
                {"title": f"S{i}", "rules": [{"rule_type": "fixed", "question_id": q}]}
                for i, q in enumerate(qids)
            ]
        },
        headers=author,
    )
    assert (
        await client.post(f"{P}/studio/tests/{test_id}/publish", headers={**author, **_idem()})
    ).status_code == 200

    learner = make_principal(is_minor=False)
    hl = auth.login(learner)
    st = await client.post(f"{P}/attempts", json={"test_id": test_id}, headers={**hl, **_idem()})
    assert st.status_code == 201, st.text
    aid = st.json()["attempt_id"]
    secs = st.json()["sections"]
    assert [s["status"] for s in secs] == ["active", "not_started"], secs
    sub1 = await client.post(
        f"{P}/attempts/{aid}/sections/{secs[0]['section_id']}/submit", json={}, headers={**hl, **_idem()}
    )
    assert sub1.status_code == 200, sub1.text
    state = await client.get(f"{P}/attempts/{aid}/state", headers=hl)
    assert [s["status"] for s in state.json()["sections"]][1] == "active", state.text
    res = await client.post(f"{P}/attempts/{aid}/resume", json={}, headers=hl)
    assert res.status_code == 200, res.text
    ov = await client.post(
        f"{P}/attempts/{aid}/rebind-override", json={"reason": "Laptop died"}, headers={**author, **_idem()}
    )
    assert ov.status_code == 201, ov.text
    done = await client.post(
        f"{P}/attempts/{aid}/submit", json={"confirm_unanswered": 2}, headers={**hl, **_idem()}
    )
    assert done.status_code == 200, done.text
    assert done.json()["status"] in ("graded", "submitted", "awaiting_manual"), done.text


async def test_ai_grading_suggestion_then_human_grade(
    fs_http: Any, allow_access: Any, make_principal: Any
) -> None:
    """ASM-26 through ``ai.public`` with the fake provider: a pending AI suggestion on the essay,
    a re-run skips it, then the evaluator's mark finalises the item."""
    client, _rec, auth = fs_http
    author, reviewer = _staff(make_principal, auth), _staff(make_principal, auth)
    test_id, _mcq, _essay = await _published_test(client, author, reviewer)
    learner = make_principal(is_minor=False)
    hl = auth.login(learner)
    st = await client.post(f"{P}/attempts", json={"test_id": test_id}, headers={**hl, **_idem()})
    aid = st.json()["attempt_id"]
    essay = next(q for sec in st.json()["sections"] for q in sec.get("questions", []) if q["type"] == "essay")
    await client.post(
        f"{P}/attempts/{aid}/autosave",
        json={
            "items": [
                {
                    "question_version_id": essay["question_version_id"],
                    "response": {"text": "A function that calls itself until a base case."},
                    "client_seq": 1,
                }
            ]
        },
        headers=hl,
    )
    assert (
        await client.post(
            f"{P}/attempts/{aid}/submit", json={"confirm_unanswered": 1}, headers={**hl, **_idem()}
        )
    ).status_code == 200

    run = await client.post(
        f"{P}/tests/{test_id}/evaluation/ai-grade", json={"attempt_id": aid}, headers={**reviewer, **_idem()}
    )
    assert run.status_code == 200, run.text
    assert run.json()["graded"] == 1 and run.json()["failed"] == 0, run.text
    again = await client.post(
        f"{P}/tests/{test_id}/evaluation/ai-grade", json={"attempt_id": aid}, headers={**reviewer, **_idem()}
    )
    assert again.json()["skipped"] == 1 and again.json()["graded"] == 0, again.text
    ev = await client.get(f"{P}/attempts/{aid}/evaluation", headers=reviewer)
    items = [it for s in ev.json()["sections"] for it in s["items"]]
    grade = next(it["grade"] for it in items if it["type"] == "essay")
    assert grade["ai_status"] == "pending" and grade["ai_marks"] is not None, grade
    done = await client.post(
        f"{P}/attempts/{aid}/items/{essay['question_version_id']}/grade",
        json={"marks": "3", "feedback": "Accepted"},
        headers={**reviewer, **_idem()},
    )
    assert done.status_code == 200, done.text


async def test_rebind_with_otp(fs_http: Any, allow_access: Any, make_principal: Any) -> None:
    """ATT-04/05: another device at restriction level >= 2 needs an OTP (identity on Firestore,
    email through the in-memory adapter); a wrong code is refused, the right one rebinds."""
    import re
    from datetime import UTC, datetime

    from app.core.ids import uuid7
    from app.modules.identity import public as identity_public
    from app.modules.identity.models import User
    from app.modules.notifications.adapters import MemoryEmailAdapter, get_email_adapter, set_email_adapter

    client, _rec, auth = fs_http
    author, reviewer = _staff(make_principal, auth), _staff(make_principal, auth)
    test_id, _m, _e = await _published_test(client, author, reviewer)
    uid = uuid7()
    now = datetime.now(UTC)
    await identity_public.create_user(
        None,  # type: ignore[arg-type]
        User(
            id=uid,
            email=f"u{uid.hex[-8:]}@example.com",
            email_verified_at=now,
            status="active",
            is_minor=False,
            created_at=now,
            updated_at=now,
        ),
    )
    first = make_principal(user_id=uid, is_minor=False, device_id=uuid7())
    st = await client.post(
        f"{P}/attempts", json={"test_id": test_id}, headers={**auth.login(first), **_idem()}
    )
    assert st.status_code == 201, st.text
    aid = st.json()["attempt_id"]

    second = make_principal(user_id=uid, is_minor=False, device_id=uuid7(), restriction_level=2)
    h2 = auth.login(second)
    prev = get_email_adapter()
    mail = MemoryEmailAdapter()
    set_email_adapter(mail)
    try:
        need = await client.post(
            f"{P}/attempts/{aid}/rebind", json={"confirm": True}, headers={**h2, **_idem()}
        )
        assert need.status_code == 400 and need.json().get("otp_required") is True, need.text
        sent = await client.post(f"{P}/attempts/{aid}/rebind/otp", headers=h2)
        assert sent.status_code == 200 and sent.json()["sent"] is True, sent.text
        code = re.search(r"\b(\d{6})\b", mail.sent[-1].text).group(1)  # type: ignore[union-attr]
        bad = await client.post(
            f"{P}/attempts/{aid}/rebind",
            json={"confirm": True, "otp_code": "000000" if code != "000000" else "111111"},
            headers={**h2, **_idem()},
        )
        assert bad.status_code >= 400, bad.text
        ok = await client.post(
            f"{P}/attempts/{aid}/rebind", json={"confirm": True, "otp_code": code}, headers={**h2, **_idem()}
        )
        assert ok.status_code == 200, ok.text
        assert ok.json()["attempt_id"] == aid and ok.json()["status"] == "in_progress"
    finally:
        set_email_adapter(prev)


async def test_outbox_handler_rescores_without_postgres(
    fs_http: Any, allow_access: Any, make_principal: Any
) -> None:
    """``on_submission_judged`` with the relay's ``session=None`` (no Postgres): ignored events and
    unknown submissions return quietly instead of touching Postgres."""
    from datetime import UTC, datetime

    from app.core.ids import uuid7
    from app.core.outbox import OutboxMessage
    from app.modules.assessments.coding import on_submission_judged

    msg = OutboxMessage(
        id=uuid7(),
        event_type="coding.submission_judged",
        aggregate_type="code_submission",
        aggregate_id=uuid7(),
        payload={"mode": "submit", "submission_id": str(uuid7())},
        organization_id=None,
        occurred_at=datetime.now(UTC),
        attempt=1,
    )
    await on_submission_judged(None, msg)  # type: ignore[arg-type]
    await on_submission_judged(None, OutboxMessage(**{**msg.__dict__, "payload": {"mode": "run"}}))  # type: ignore[arg-type]
