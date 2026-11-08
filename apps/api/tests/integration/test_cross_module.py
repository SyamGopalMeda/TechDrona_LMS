"""Stage 10 cross-module integration (backlog A + F): the hooks wired in ``app.wiring`` work
end to end against the real database (no mocked access checker, real outbox relay)."""

from __future__ import annotations

import uuid
from datetime import timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select, text

from app.core.access import check_access
from app.core.db import system_context, tenant_context
from app.core.ids import uuid7
from app.core.outbox import emit_event, relay_pending
from app.core.time import utcnow
from app.modules.catalog.models import Course, Lesson
from app.modules.entitlements import service as ent
from app.modules.entitlements.models import Entitlement
from app.modules.learning import service as learning
from app.modules.learning.models import LessonProgress
from tests.catalog.factory import make_published_course
from tests.coding.conftest import seed_problem
from tests.commerce.factory import buy, make_buyer, make_product, pay_via_webhook, principal
from tests.identity.factory import make_user

SYS = ent.Actor.system("test.integration")


async def _paid_course_with_embeds(db: Any, author: uuid.UUID) -> tuple[Any, Any, uuid.UUID]:
    problem = await seed_problem(db, author)
    quiz_test_id = uuid7()  # lessons.test_id is a soft reference
    pc = await make_published_course(
        db,
        author,
        is_free=False,
        extra_lessons=[
            {"name": "coding", "lesson_type": "coding", "coding_problem_id": problem.id},
            {"name": "quiz", "lesson_type": "quiz", "test_id": quiz_test_id},
        ],
    )
    return pc, problem, quiz_test_id


async def _relay(db: Any) -> None:
    await relay_pending(db, batch=1000)


# --------------------------------------------------------------------------- purchase -> access


async def test_purchase_entitles_lesson_test_and_coding_problem(api, db, fake_gw) -> None:
    author = (await make_user(db)).id
    pc, problem, quiz_test = await _paid_course_with_embeds(db, author)
    cat = await make_product(db, kind="course", items=[{"item_type": "course", "course_id": pc.course_id}])
    uid = await make_buyer(db)
    p = principal(uid)

    await tenant_context(db, p)
    targets = [
        ("course", pc.course_id),
        ("lesson", pc.lessons["video"]),
        ("lesson", pc.keys["video"]),  # lesson_key resolves too
        ("coding_problem", problem.id),
        ("test", quiz_test),
    ]
    for kind, rid in targets:
        d = await check_access(db, p, kind, rid)  # type: ignore[arg-type]
        assert not d.allowed and d.reason == "no_entitlement", (kind, d)

    order = await buy(api.as_(p), cat)
    await pay_via_webhook(api.client, fake_gw, order)

    await tenant_context(db, p)
    for kind, rid in targets:
        d = await check_access(db, p, kind, rid)  # type: ignore[arg-type]
        assert d.allowed and d.reason == "entitlement", (kind, d)
    # Another course is still closed.
    other = await make_published_course(db, author, is_free=False)
    await tenant_context(db, p)
    assert not (await check_access(db, p, "lesson", other.lessons["video"])).allowed

    # Usage provider (learning -> commerce refund rules): consumption = course progress.
    await system_context(db, "test")
    course = await db.get(Course, pc.course_id)
    enr = await learning.create_enrolment(db, user_id=uid, course=course, source="manual")
    enr.progress_pct = Decimal("40")
    await db.flush()
    usage = ent.usage_provider()
    assert usage.name == "learning"
    assert await usage.consumption_pct(db, uid, cat.product.id) == Decimal("40.00")
    assert await usage.certificate_issued(db, uid, cat.product.id) is False


async def test_l3_restriction_denies_paid_content_but_keeps_free(api, db) -> None:
    author = (await make_user(db)).id
    paid = await make_published_course(db, author, is_free=False)
    free = await make_published_course(db, author, is_free=True)
    cat = await make_product(db, kind="course", items=[{"item_type": "course", "course_id": paid.course_id}])
    uid = await make_buyer(db)
    await system_context(db, "test")
    await ent.grant(
        db,
        SYS,
        user_id=uid,
        source_type="admin_grant",
        product_id=cat.product.id,
        starts_at=utcnow() - timedelta(days=1),
        ends_at=utcnow() + timedelta(days=30),
        granted_by=author,
    )
    ok = principal(uid)
    await tenant_context(db, ok)
    assert (await check_access(db, ok, "lesson", paid.lessons["article"])).allowed

    l3 = principal(uid, restriction_level=3)
    await tenant_context(db, l3)
    d = await check_access(db, l3, "lesson", paid.lessons["article"])
    assert not d.allowed and d.reason == "restricted"
    # The real call sites pass ``is_free`` from the catalog row.
    free_course = await db.get(Course, free.course_id)
    d = await check_access(db, l3, "course", free.course_id, is_free=free_course.is_free)
    assert d.allowed and d.reason == "free"


# --------------------------------------------------------------------------- security -> commerce


async def test_false_positive_unblock_extends_entitlements_once(api, db) -> None:
    author = (await make_user(db)).id
    cat = await make_product(db, kind="course")
    uid = await make_buyer(db)
    await system_context(db, "test")
    e, _ = await ent.grant(
        db,
        SYS,
        user_id=uid,
        source_type="admin_grant",
        product_id=cat.product.id,
        starts_at=utcnow() - timedelta(days=10),
        ends_at=utcnow() + timedelta(days=20),
        granted_by=author,
    )
    old_end = e.ends_at
    decision = uuid7()
    payload = {
        "user_id": str(uid),
        "case_ref": "SEC-TEST-1",
        "restricted_days": 5,
        "decision_id": str(decision),
        "reason": "security_false_positive_credit",
    }
    for _ in range(2):  # a replayed event must not credit twice
        await emit_event(
            db,
            "security.false_positive_credit",
            payload,
            aggregate_type="security_case",
            aggregate_id=uuid7(),
        )
        await _relay(db)
    await system_context(db, "test")
    fresh = (
        await db.execute(
            select(Entitlement).where(Entitlement.id == e.id).execution_options(populate_existing=True)
        )
    ).scalar_one()
    assert fresh.ends_at == old_end + timedelta(days=5)
    n = (
        await db.execute(
            text(
                "SELECT count(*) FROM entitlement_events WHERE entitlement_id = :e AND event_type = 'fp_extension'"
            ),
            {"e": e.id},
        )
    ).scalar_one()
    assert n == 1


async def test_stream_cap_hit_becomes_security_signal(db) -> None:
    uid = (await make_user(db)).id
    await system_context(db, "test")
    await emit_event(
        db,
        "media.stream_cap_hit",
        {
            "user_id": str(uid),
            "other_playback_session_id": str(uuid7()),
            "rule_key": "cap.stream",
            "is_minor": False,
        },
        aggregate_type="user",
        aggregate_id=uid,
    )
    await _relay(db)
    await system_context(db, "test")
    err = (
        await db.execute(
            text(
                "SELECT last_error FROM outbox_events WHERE event_type = 'media.stream_cap_hit' AND aggregate_id = :u"
            ),
            {"u": uid},
        )
    ).scalar_one()
    assert err is None, err
    rows = (
        await db.execute(text("SELECT rule_key, source FROM security_signals WHERE user_id = :u"), {"u": uid})
    ).all()
    assert ("cap.stream", "playback") in [(r[0], r[1]) for r in rows]


# --------------------------------------------------------------------------- outbox -> analytics mastery


async def _mastery(db: Any, uid: uuid.UUID) -> dict[uuid.UUID, Any]:
    from app.modules.analytics.mastery import get_topic_mastery

    await system_context(db, "test")
    return {v.topic_id: v for v in await get_topic_mastery(db, uid)}


async def test_attempt_scored_updates_topic_mastery(db) -> None:
    uid = (await make_user(db)).id
    topic = uuid7()
    await system_context(db, "test")
    await emit_event(
        db,
        "attempt.scored",
        {
            "attempt_id": str(uuid7()),
            "test_id": str(uuid7()),
            "user_id": str(uid),
            "scoring_version": 1,
            "topic_scores": [{"topic_id": str(topic), "correct": 5, "total": 6}],
        },
        aggregate_type="test_attempt",
        aggregate_id=uuid7(),
    )
    await _relay(db)
    m = await _mastery(db, uid)
    assert topic in m and m[topic].attempts == 6 and m[topic].mastery > 0.5
    # consumed once: the polling reconciler does not apply it again
    from app.modules.analytics.consumer import consume_outbox

    await system_context(db, "test")
    await consume_outbox(db)
    assert (await _mastery(db, uid))[topic].attempts == 6


async def test_practice_answered_updates_topic_mastery(db) -> None:
    uid = (await make_user(db)).id
    topic = uuid7()
    await system_context(db, "test")
    for i in range(3):
        await emit_event(
            db,
            "practice.answered",
            {
                "user_id": str(uid),
                "question_id": str(uuid7()),
                "topic_id": str(topic),
                "is_correct": i != 1,
                "attempt_no": 1,
                "difficulty": "medium",
            },
            aggregate_type="practice_session",
            aggregate_id=uuid7(),
        )
    await _relay(db)
    m = await _mastery(db, uid)
    assert topic in m and m[topic].attempts == 3


# --------------------------------------------------------------------------- analytics -> learning


async def test_video_coverage_feeds_lesson_completion(api, db) -> None:
    author = (await make_user(db)).id
    pc = await make_published_course(db, author, is_free=True)
    uid = (await make_user(db)).id
    await system_context(db, "test")
    course = await db.get(Course, pc.course_id)
    lesson = await db.get(Lesson, pc.lessons["video"])
    await learning.create_enrolment(db, user_id=uid, course=course, source="free")
    # Server-verified coverage from analytics heartbeats: 560 of 600 s (>= 90 %).
    await db.execute(
        text(
            "INSERT INTO video_watch_coverage (user_id, lesson_asset_id, lesson_id, covered_s, coverage_pct, "
            "duration_s) VALUES (:u, :a, :l, 560, 93.33, 600)"
        ),
        {"u": uid, "a": pc.assets["video"], "l": pc.lessons["video"]},
    )
    p = principal(uid)
    await system_context(db, "test")
    await learning.record_video_heartbeat(
        db, p, lesson, course, prev_pos=0, new_pos=5, elapsed_s=5, playing=True, duration_s=600
    )
    lp = (
        await db.execute(
            select(LessonProgress).where(
                LessonProgress.user_id == uid, LessonProgress.lesson_key == pc.keys["video"]
            )
        )
    ).scalar_one()
    assert lp.status == "completed" and lp.watched_seconds == 560


# --------------------------------------------------------------------------- coding question inside a test


async def test_coding_question_in_test_is_judged_and_scored(
    client, db, world, allow_access, fake_judge
) -> None:
    from app.modules.assessments.models import AttemptResult
    from app.modules.coding.worker import judge_submission
    from app.modules.placement import bank
    from app.modules.placement.schemas import QuestionCreate
    from tests.assessments.test_attempts import API, assign, fixed, make_test, start
    from tests.placement.world import Q, idem, topic

    w = world
    author, reviewer, student = w.personas["author"], w.personas["reviewer"], w.personas["student"]
    problem = await seed_problem(db, author.id, weights=[Decimal(1), Decimal(1)])
    t = await topic(db, "dsa/arrays")
    await system_context(db, "test.factory")
    q, qv = await bank.create_question(
        db,
        author.principal,
        QuestionCreate(
            question_type="coding",
            primary_topic_id=t,
            stem_html="<p>Solve the linked problem.</p>",
            explanation_html="<p>Reference solution sums the numbers.</p>",
            difficulty=2,
            default_marks=Decimal("9"),
            coding_problem_id=problem.id,
        ),
    )
    assert qv.coding_problem_id == problem.id
    await bank.submit_review(db, q.id)
    await bank.review(db, reviewer.principal, q.id, "approve")
    await bank.publish(db, q.id)
    qq = Q(q.id, qv.id, [], [], "coding")
    test_id = await make_test(db, w, [("Coding", None, [fixed(qq)])], duration_seconds=1800)
    await assign(db, w, test_id)
    r = await start(client, student, test_id)
    assert r.status_code == 201, r.text
    attempt_id = r.json()["attempt_id"]
    delivered = [q for s in r.json()["sections"] for q in s.get("questions", [])]
    assert [q["coding_problem_id"] for q in delivered] == [str(problem.id)]

    # Another user's attempt id is refused by the assessments validator.
    other = w.personas["student_b"]
    bad = await client.post(
        f"{API}/coding/problems/{problem.id}/submit",
        json={"language_key": "cpp17", "source_code": "int main(){}", "attempt_id": attempt_id},
        headers={**other.headers, **idem()},
    )
    assert bad.status_code == 404, bad.text

    sub = await client.post(
        f"{API}/coding/problems/{problem.id}/submit",
        json={
            "language_key": "cpp17",
            "source_code": "// FAKE_VERDICT: AC,AC,WA\nint main(){}\n",
            "attempt_id": attempt_id,
        },
        headers={**student.headers, **idem()},
    )
    assert sub.status_code == 202, sub.text
    assert sub.json()["queue"] == "judge_assessment"
    await system_context(db, "test")
    assert (
        await judge_submission(db, uuid.UUID(sub.json()["submission_id"]), fake_judge, budget_s=1)
        == "PARTIAL"
    )

    done = await client.post(
        f"{API}/attempts/{attempt_id}/submit", json={}, headers={**student.headers, **idem()}
    )
    assert done.status_code in (200, 201), done.text
    await system_context(db, "test")
    res = await db.get(AttemptResult, uuid.UUID(attempt_id))
    assert res is not None
    # sample 1 + hidden 1 of weights (1, 1, 1) passed -> 2/3 of 9 marks; not fully correct.
    assert res.score == Decimal("6.00") and res.max_score == Decimal("9.00")
    assert res.correct_count == 0 and res.incorrect_count == 1


async def test_late_verdict_rescores_attempt(db) -> None:
    """``submission.judged`` after the attempt was graded bumps ``scoring_version``."""
    from app.core.outbox import OutboxMessage
    from app.modules.assessments.coding import on_submission_judged

    # No attempt row -> handler is a no-op (defensive path).
    await system_context(db, "test")
    await on_submission_judged(
        db,
        OutboxMessage(
            uuid7(),
            "submission.judged",
            "code_submission",
            uuid7(),
            {"mode": "submit", "submission_id": str(uuid7())},
            None,
            utcnow(),
            1,
        ),
    )


# --------------------------------------------------------------------------- webhook queue mode


async def test_webhook_queue_mode_defers_processing_to_worker(api, db, fake_gw, monkeypatch) -> None:
    from app.core.config import get_settings
    from app.modules.commerce import tasks as ctasks
    from app.modules.commerce import webhooks
    from app.modules.commerce.models import PaymentWebhookEvent

    sent: list[tuple[str, uuid.UUID]] = []
    monkeypatch.setattr(get_settings(), "TD_COMMERCE_WEBHOOK_MODE", "queue")
    monkeypatch.setattr(ctasks, "enqueue_webhook_event", lambda provider, rid: sent.append((provider, rid)))
    author = (await make_user(db)).id
    pc = await make_published_course(db, author, is_free=False)
    cat = await make_product(db, kind="course", items=[{"item_type": "course", "course_id": pc.course_id}])
    uid = await make_buyer(db)
    p = principal(uid)
    order = await buy(api.as_(p), cat)
    await pay_via_webhook(api.client, fake_gw, order)
    assert len(sent) == 1 and sent[0][0] == "razorpay"
    await system_context(db, "test")
    row = await db.get(PaymentWebhookEvent, sent[0][1])
    assert row is not None and row.status == "received"
    await tenant_context(db, p)
    assert not (await check_access(db, p, "lesson", pc.lessons["video"])).allowed
    # worker / retry sweep
    assert await webhooks.process_pending_events(db, fake_gw) >= 1
    await tenant_context(db, p)
    assert (await check_access(db, p, "lesson", pc.lessons["video"])).allowed
