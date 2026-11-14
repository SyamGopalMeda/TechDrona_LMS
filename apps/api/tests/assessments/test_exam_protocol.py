"""Exam protocol (agreement screen, recorded events, live integrity warnings, auto-flag, opt-in
auto-submit) and the evaluation flow (integrity badges, AI-suggested grading of free-text items,
human finalisation, publish via ASM-16)."""

from __future__ import annotations

import uuid
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import ValidationError

from app.modules.ai import service as ai
from app.modules.assessments import exam
from app.modules.assessments.schemas import IntegritySettings
from tests.assessments.test_attempts import assign, fixed, item, make_bank, make_test, sql, start
from tests.placement.world import World, idem, question, topic

API = "/api/v1"
EXAM = {"exam_mode": True, "flag_threshold": 5, "warn_thresholds": {"window_blur": 3}}


# --------------------------------------------------------------------------- pure units


def test_settings_validation() -> None:
    with pytest.raises(ValidationError):
        IntegritySettings(ai_hints=True)
    with pytest.raises(ValidationError):
        IntegritySettings(record_events=["telepathy"])
    with pytest.raises(ValidationError):
        IntegritySettings(warn_thresholds={"copy": 0})
    s = IntegritySettings(exam_mode=True, record_events=["paste", "focus_lost", "paste"])
    assert s.require_agreement is True and s.record_events == ["focus_lost", "paste"]


def _test(settings: dict[str, Any]) -> Any:
    return SimpleNamespace(integrity_settings=settings)


def test_protocol_defaults_and_summary() -> None:
    legacy = exam.protocol_of(_test({"log_paste": False}))
    assert not legacy.exam_mode and legacy.record_events == ("focus_lost", "fullscreen_exit")
    p = exam.protocol_of(_test({"exam_mode": True}))
    assert p.require_agreement and p.conduct_instructions == exam.DEFAULT_CONDUCT_INSTRUCTIONS
    assert "right_click" not in p.record_events and p.flag_threshold == exam.DEFAULT_FLAG_THRESHOLD
    assert p.public()["ai_hints"] is False
    s = exam.summarize(p, {"focus_lost": 2, "right_click": 9}, "none")
    assert s["total"] == 2 and not s["flagged"] and "right_click" not in s["counts"]
    s = exam.summarize(p, {"window_blur": 3}, "none")
    assert s["flagged"] and s["over_threshold"][0] == {
        "type": "window_blur",
        "label": "Window inactive",
        "count": 3,
        "threshold": 3,
    }
    assert exam.should_flag(p, s) and not exam.should_auto_submit(p, s)
    p2 = exam.protocol_of(_test({"exam_mode": True, "auto_submit_after": 2}))
    assert exam.should_auto_submit(p2, exam.summarize(p2, {"copy": 1, "paste": 1}, "none"))


# --------------------------------------------------------------------------- helpers


def ev(kind: str, seq: int) -> dict[str, Any]:
    return {"type": kind, "client_seq": seq}


async def exam_test(db: Any, w: World, **integrity: Any) -> tuple[uuid.UUID, list[Any]]:
    _, qs = await make_bank(db, w)
    test_id = await make_test(
        db,
        w,
        [("Exam", None, [fixed(q) for q in qs])],
        duration_seconds=1800,
        integrity_settings={**EXAM, **integrity},
    )
    await assign(db, w, test_id)
    return test_id, qs


async def autosave(client: Any, who: Any, aid: str, events: list[dict[str, Any]]) -> Any:
    return await client.post(f"{API}/attempts/{aid}/autosave", json={"events": events}, headers=who.headers)


# --------------------------------------------------------------------------- protocol


async def test_agreement_required_and_timer_starts_at_agreement(client, world: World, db) -> None:
    test_id, _ = await exam_test(db, world)
    student = world.personas["student"]
    detail = (await client.get(f"{API}/tests/{test_id}", headers=student.headers)).json()
    assert detail["protocol"]["exam_mode"] and detail["protocol"]["conduct_instructions"]
    assert detail["protocol"]["record_events"][0] == "focus_lost"
    r = await start(client, student, test_id)
    assert r.status_code == 400 and r.json()["errors"][0]["field"] == "instructions_agreed"
    r = await start(client, student, test_id, instructions_agreed=True)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["protocol"]["exam_mode"] and body["integrity"]["total"] == 0
    row = (
        await sql(
            db,
            "SELECT started_at, deadline_at, layout->>'integrity_consent' FROM test_attempts WHERE id = :a",
            a=body["attempt_id"],
        )
    )[0]
    assert int((row[1] - row[0]).total_seconds()) == 1800 and row[2] == "true"
    pay = (
        await sql(
            db,
            "SELECT payload FROM attempt_events WHERE attempt_id = :a AND event_type = 'start'",
            a=body["attempt_id"],
        )
    )[0][0]
    assert pay["instructions_agreed"] is True and pay["exam_mode"] is True


async def test_events_counted_flagged_and_idempotent(client, world: World, db) -> None:
    test_id, _ = await exam_test(db, world)
    student, trainer = world.personas["student"], world.personas["trainer_a"]
    aid = (await start(client, student, test_id, instructions_agreed=True)).json()["attempt_id"]
    r = await autosave(
        client, student, aid, [ev("focus_lost", 1), ev("window_blur", 2), ev("right_click", 3)]
    )
    out = r.json()
    assert r.status_code == 200 and out["ignored_events"] == 1  # right_click not recorded by default
    assert out["integrity"]["total"] == 2 and not out["integrity"]["flagged"]
    # replaying the same client_seq is not double counted
    r = await autosave(client, student, aid, [ev("window_blur", 2)])
    assert r.json()["integrity"]["total"] == 2
    r = await autosave(client, student, aid, [ev("window_blur", 4), ev("window_blur", 5)])
    integ = r.json()["integrity"]
    assert integ["flagged"] and integ["integrity_status"] == "review_recommended"
    assert integ["over_threshold"] == [
        {"type": "window_blur", "label": "Window inactive", "count": 3, "threshold": 3}
    ]
    flagged = await sql(
        db,
        "SELECT count(*) FROM attempt_events WHERE attempt_id = :a AND event_type = 'integrity_flagged'",
        a=aid,
    )
    assert flagged[0][0] == 1
    # state carries the live banner data after a reload
    st = (await client.get(f"{API}/attempts/{aid}/state", headers=student.headers)).json()
    assert st["integrity"]["counts"]["window_blur"] == 3
    # evidence, not a verdict: submit works and is graded normally, the notice is shown
    r = await client.post(
        f"{API}/attempts/{aid}/submit",
        json={"confirm_unanswered": 999},
        headers={**student.headers, **idem()},
    )
    assert r.status_code == 200 and r.json()["integrity_flagged"] is True
    assert r.json()["status"] == "graded"
    # staff review queue (ASM-19) lists it
    flags = (await client.get(f"{API}/integrity/flags?test_id={test_id}", headers=trainer.headers)).json()
    assert [f["attempt_id"] for f in flags["data"]] == [aid]


async def test_auto_submit_after_n_events_is_opt_in(client, world: World, db) -> None:
    test_id, _ = await exam_test(db, world, auto_submit_after=2)
    student = world.personas["student"]
    aid = (await start(client, student, test_id, instructions_agreed=True)).json()["attempt_id"]
    r = await autosave(client, student, aid, [ev("copy", 1)])
    assert r.json()["status"] == "in_progress"
    r = await autosave(client, student, aid, [ev("paste", 2)])
    assert r.json()["status"] == "graded"
    row = (await sql(db, "SELECT status, submit_reason FROM test_attempts WHERE id = :a", a=aid))[0]
    assert row[0] == "graded" and row[1] == "integrity_limit"
    r = await autosave(client, student, aid, [ev("paste", 3)])
    assert r.status_code == 409 and r.json()["code"] == "attempt_closed"


async def test_legacy_test_ignores_new_event_types(client, world: World, db) -> None:
    _, qs = await make_bank(db, world)
    test_id = await make_test(db, world, [("S", None, [fixed(qs[0])])], duration_seconds=600)
    await assign(db, world, test_id)
    student = world.personas["student"]
    aid = (await start(client, student, test_id, integrity_consent=True)).json()["attempt_id"]
    r = await autosave(client, student, aid, [ev("window_blur", 1), ev("focus_lost", 2)])
    assert r.json()["ignored_events"] == 1 and "integrity" not in r.json()


# --------------------------------------------------------------------------- evaluation + AI grading


async def essay_test(db: Any, w: World) -> tuple[uuid.UUID, uuid.UUID, Any]:
    t = await topic(db, "verbal/essays")
    q = await question(
        db,
        w.personas["author"],
        w.personas["reviewer"],
        t,
        qtype="fill_blank",
        marks="10",
        negative="0",
        stem="Explain",
    )
    await sql(db, "UPDATE questions SET question_type = 'descriptive' WHERE id = :q", q=q.question_id)
    _, qs = await make_bank(db, w)
    test_id = await make_test(
        db, w, [("Written", None, [fixed(q), fixed(qs[0])])], duration_seconds=1800, integrity_settings=EXAM
    )
    assignment = await assign(db, w, test_id, release_mode="manual")
    return test_id, assignment, (q, qs[0])


@pytest.fixture
def fake_ai(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    async def grade(session: Any, **kw: Any) -> ai.GradeSuggestion:
        calls.append(kw)
        return ai.GradeSuggestion(
            marks=Decimal("7"), max_marks=kw["max_marks"], feedback_md="Good", confidence=0.8
        )

    monkeypatch.setattr(ai, "grade_response", grade)
    return calls


async def test_evaluation_ai_suggestion_then_human_finalize(client, world: World, db, fake_ai) -> None:
    test_id, assignment, (essay, mcq) = await essay_test(db, world)
    student, trainer = world.personas["student"], world.personas["trainer_a"]
    aid = (await start(client, student, test_id, instructions_agreed=True)).json()["attempt_id"]
    await autosave(client, student, aid, [ev("focus_lost", 50), ev("focus_lost", 51)])
    r = await client.post(
        f"{API}/attempts/{aid}/submit",
        json={
            "confirm_unanswered": 999,
            "final_items": [
                {
                    "question_version_id": str(essay.qv_id),
                    "response": {"text": "Because ..."},
                    "client_seq": 1,
                },
                item(mcq, 2),
            ],
        },
        headers={**student.headers, **idem()},
    )
    assert r.status_code == 200 and r.json()["status"] == "awaiting_manual"

    lst = await client.get(f"{API}/tests/{test_id}/evaluation", headers=trainer.headers)
    assert lst.status_code == 200, lst.text
    row = lst.json()["items"][0]
    assert row["grading"] == {
        "items": 2,
        "finalized": 1,
        "ai_pending": 0,
        "manual_pending": 1,
        "manual_items": 1,
    }
    assert row["integrity"]["counts"]["focus_lost"] == 2 and row["released"] is False
    assert lst.json()["assignments"][0]["id"] == str(assignment)
    # learners never see the evaluation views
    r = await client.get(f"{API}/tests/{test_id}/evaluation", headers=student.headers)
    assert r.status_code in (403, 404)
    r = await client.get(f"{API}/attempts/{aid}/evaluation", headers=world.personas["trainer_b"].headers)
    assert r.status_code == 404

    r = await client.post(f"{API}/tests/{test_id}/evaluation/ai-grade", json={}, headers=trainer.headers)
    assert r.status_code == 200 and r.json()["graded"] == 1, r.text
    assert fake_ai[0]["purpose"] == "assessment" and fake_ai[0]["response_text"] == "Because ..."
    assert fake_ai[0]["max_marks"] == Decimal("10.00")
    # a suggestion is not a grade: score unchanged, still pending
    row = (await client.get(f"{API}/tests/{test_id}/evaluation", headers=trainer.headers)).json()["items"][0]
    assert row["grading"]["ai_pending"] == 1 and row["score"] == "2.00" and row["status"] == "awaiting_manual"
    again = await client.post(f"{API}/tests/{test_id}/evaluation/ai-grade", json={}, headers=trainer.headers)
    assert again.json() == {"graded": 0, "failed": 0, "skipped": 1, "stopped_reason": None}

    rev = (await client.get(f"{API}/attempts/{aid}/evaluation", headers=trainer.headers)).json()
    it = next(i for i in rev["sections"][0]["items"] if i["needs_human"])
    assert it["grade"]["ai_marks"] == "7.00" and it["grade"]["ai_status"] == "pending"

    url = f"{API}/attempts/{aid}/items/{essay.qv_id}/grade"
    r = await client.post(url, json={"marks": "11"}, headers=trainer.headers)
    assert r.status_code == 400
    r = await client.post(url, json={"marks": "8", "feedback": "Clear"}, headers=student.headers)
    assert r.status_code in (403, 404)
    r = await client.post(url, json={"marks": "8", "feedback": "Clear"}, headers=trainer.headers)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "graded" and r.json()["score"] == "10.00"
    # publish = ASM-16 release
    r = await client.post(
        f"{API}/tests/{test_id}/results/release",
        json={"test_assignment_id": str(assignment)},
        headers=trainer.headers,
    )
    assert r.status_code == 200 and r.json()["results_released"] == 1


async def test_ai_grading_error_maps_to_problem(client, world: World, db, monkeypatch) -> None:
    test_id, _, (essay, _) = await essay_test(db, world)
    student, trainer = world.personas["student"], world.personas["trainer_a"]
    aid = (await start(client, student, test_id, instructions_agreed=True)).json()["attempt_id"]
    await client.post(
        f"{API}/attempts/{aid}/submit",
        json={
            "confirm_unanswered": 999,
            "final_items": [
                {"question_version_id": str(essay.qv_id), "response": {"text": "x"}, "client_seq": 1}
            ],
        },
        headers={**student.headers, **idem()},
    )

    async def disabled(session: Any, **kw: Any) -> Any:
        raise ai.AIDisabled("off")

    monkeypatch.setattr(ai, "grade_response", disabled)
    r = await client.post(f"{API}/tests/{test_id}/evaluation/ai-grade", json={}, headers=trainer.headers)
    assert r.status_code == 403 and r.json()["code"] == "ai_disabled"


# --------------------------------------------------------------------------- version settings


def test_normalise_manual_enforces_max_words() -> None:
    from app.core.errors import ProblemError
    from app.modules.assessments.attempts import normalise_manual

    assert normalise_manual({"text": "one two three"}, {"max_words": 3}) == {"text": "one two three"}
    with pytest.raises(ProblemError) as e:
        normalise_manual({"text": "one two three four"}, {"max_words": 3})
    assert e.value.status == 422 and e.value.ext["errors"][0]["code"] == "too_many_words"
    assert normalise_manual({"text": "  "}, {"max_words": 3}) is None


async def test_essay_max_words_setting_enforced_on_autosave(client, world: World, db) -> None:
    from app.core.db import system_context
    from app.modules.placement import bank
    from app.modules.placement.schemas import QuestionCreate

    t = await topic(db, "verbal/short")
    await system_context(db, "test.factory")
    body = QuestionCreate(
        question_type="essay",
        primary_topic_id=t,
        stem_html="<p>Define recursion</p>",
        options=[],
        answer_key=None,
        explanation_html="<p>Model answer.</p>",
        difficulty=2,
        default_marks=Decimal("5"),
        default_negative=Decimal("0"),
        settings={"max_words": 3},
    )
    qq, qv = await bank.create_question(db, world.personas["author"].principal, body)
    await bank.submit_review(db, qq.id)
    await bank.review(db, world.personas["reviewer"].principal, qq.id, "approve")
    await bank.publish(db, qq.id)
    q = SimpleNamespace(question_id=qq.id, qv_id=qv.id)
    test_id = await make_test(db, world, [("Short", None, [fixed(q)])], duration_seconds=600)  # type: ignore[arg-type]
    await assign(db, world, test_id)
    student = world.personas["student"]
    aid = (await start(client, student, test_id)).json()["attempt_id"]

    async def save(text: str, seq: int) -> Any:
        body = {
            "items": [{"question_version_id": str(q.qv_id), "response": {"text": text}, "client_seq": seq}]
        }
        return await client.post(f"{API}/attempts/{aid}/autosave", json=body, headers=student.headers)

    r = await save("far too many words here", 1)
    # An invalid answer no longer blocks the whole autosave batch: it comes back in `rejected`.
    assert r.status_code == 200, r.text
    rej = r.json()["rejected"]
    assert len(rej) == 1 and rej[0]["question_version_id"] == str(q.qv_id)
    assert rej[0]["field"] == "response.text" and rej[0]["code"] == "too_many_words"
    assert rej[0]["message"] == "At most 3 words"
    assert (await save("just three words", 2)).status_code == 200
    r = await client.post(
        f"{API}/attempts/{aid}/submit",
        json={"confirm_unanswered": 999},
        headers={**student.headers, **idem()},
    )
    assert r.json()["status"] == "awaiting_manual"  # essays stay pending human/AI grading


async def test_evaluation_open_before_first_attempt_for_assigned_batch_staff(
    client, world: World, db
) -> None:
    """A platform test assigned to batch A: its batch-scoped trainer and evaluator can open the
    (still empty) evaluation instead of a 403; staff of another batch still cannot."""
    test_id, _, _ = await essay_test(db, world)
    for who in ("trainer_a", "evaluator_a"):
        r = await client.get(f"{API}/tests/{test_id}/evaluation", headers=world.personas[who].headers)
        assert r.status_code == 200, (who, r.text)
        body = r.json()
        assert body["items"] == [] and body["totals"]["attempts"] == 0
    r = await client.post(
        f"{API}/tests/{test_id}/evaluation/ai-grade", json={}, headers=world.personas["trainer_a"].headers
    )
    assert r.status_code == 200 and r.json()["graded"] == 0, r.text
    r = await client.get(f"{API}/tests/{test_id}/evaluation", headers=world.personas["trainer_b"].headers)
    assert r.status_code == 403
    r = await client.get(f"{API}/tests/{test_id}/evaluation", headers=world.personas["student"].headers)
    assert r.status_code in (403, 404)


async def test_evaluator_lists_assignments_it_releases(client, world: World, db) -> None:
    """Evaluators release results (``test.results.release``) but cannot assign tests; the report
    page still needs the batch's assignments, so they are listed for them (not for batch B)."""
    test_id, assignment, _ = await essay_test(db, world)
    r = await client.get(f"{API}/tests/{test_id}/assignments", headers=world.personas["evaluator_a"].headers)
    assert r.status_code == 200 and [a["id"] for a in r.json()["items"]] == [str(assignment)]
    r = await client.get(f"{API}/tests/{test_id}/assignments", headers=world.personas["trainer_b"].headers)
    assert r.status_code == 200 and r.json()["items"] == []
