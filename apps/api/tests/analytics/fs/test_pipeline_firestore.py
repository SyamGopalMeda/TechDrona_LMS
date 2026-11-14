"""Analytics pipeline on Firestore (``TD_STORE_ANALYTICS=firestore``), emulator only, no Postgres.

Ingest (batch documents) -> outbox consumer -> interval builder -> daily aggregation, with the
**same golden values as the Postgres pipeline** (``tests/analytics/test_pipeline.py`` example 1,
spec §3.13): the time model and the aggregation code are shared, only the row access differs, so
equal inputs must give equal ``daily_learning_aggregates`` rows. Counters are also checked
against numbers computed directly from the fixture events.

Other modules are stubbed at analytics' boundary (catalog lesson/asset ownership, entitlement
checker, org resolver, lesson metadata, identity user flags, placement topic roots).
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from app.core.ids import uuid7
from app.core.time import ist_date
from tests.analytics.conftest import Page, batch, ist, principal_for
from tests.paths.fs.http_harness import FakeSession

FS_MODULES = ("analytics",)
pytestmark = pytest.mark.usefixtures("fs_env")


def steps(start: datetime, end: datetime, step: int = 15) -> list[datetime]:
    out, t = [], start + timedelta(seconds=step)
    while t <= end:
        out.append(t)
        t += timedelta(seconds=step)
    return out


class _Allow:
    async def check(
        self, session: Any, principal: Any, rtype: Any, rid: Any, *, is_free: bool = False
    ) -> Any:
        from app.core.access import AccessDecision

        return AccessDecision(True, "test")


@pytest.fixture
def world(monkeypatch: pytest.MonkeyPatch) -> Iterator[dict[str, Any]]:
    from app.core.access import get_access_checker, register_access_checker
    from app.modules.analytics import consumer, hooks, jobs, service

    course, lesson, asset = uuid7(), uuid7(), uuid7()

    async def lesson_course(session: Any, ctx: Any, lid: uuid.UUID) -> uuid.UUID | None:
        return course if lid == lesson else None

    async def asset_lesson(session: Any, ctx: Any, aid: uuid.UUID) -> uuid.UUID | None:
        return lesson if aid == asset else None

    async def no_org(session: Any, principal: Any, ref: Any) -> None:
        return None

    async def adult(session: Any, user_id: uuid.UUID) -> tuple[str, bool]:
        return ("adult", False)

    async def touch(session_id: uuid.UUID) -> None:
        return None

    class Meta(hooks.LessonMetaLookup):
        async def assets(self, session: Any, ids: set[uuid.UUID]) -> dict[uuid.UUID, hooks.AssetMeta]:
            return {a: hooks.AssetMeta(duration_s=1800) for a in ids if a == asset}

    from app.modules.placement import public as placement

    async def no_roots(session: Any, topic_ids: Any) -> dict[uuid.UUID, uuid.UUID]:
        return {}  # topics unknown to placement: no category (as the Postgres CTE returns nothing)

    monkeypatch.setattr(placement, "topic_roots", no_roots)
    prev = get_access_checker()
    register_access_checker(_Allow())  # type: ignore[arg-type]
    monkeypatch.setattr(service, "_lesson_course", lesson_course)
    monkeypatch.setattr(service, "_asset_lesson", asset_lesson)
    monkeypatch.setattr(jobs, "_user_flags", adult)
    monkeypatch.setattr(consumer, "_user", adult)
    hooks.register_org_resolver(no_org)
    hooks.register_lesson_meta_lookup(Meta())
    hooks.register_engagement_toucher(touch)
    try:
        yield {"course": course, "lesson": lesson, "asset": asset}
    finally:
        register_access_checker(prev)
        hooks.register_org_resolver(None)
        hooks.register_lesson_meta_lookup(None)
        hooks.register_engagement_toucher(None)


async def _ingest(session: Any, p: Any, events: list[dict[str, Any]], now: datetime) -> list[dict[str, Any]]:
    from app.modules.analytics.schemas import BatchIn
    from app.modules.analytics.service import ingest_batch

    out: list[dict[str, Any]] = []
    for i in range(0, len(events), 100):
        res = await ingest_batch(session, p, BatchIn.model_validate(batch(events[i : i + 100], now)), now=now)
        out += res.results
    return out


async def _daily(uid: uuid.UUID, day: Any) -> dict[tuple[str, uuid.UUID], Any]:
    from app.modules.analytics import fs_raw

    return {(r.entity_kind, r.entity_id): r for r in await fs_raw.daily_rows(uid, day)}


async def _build(session: Any, now: datetime, day: Any) -> None:
    from app.modules.analytics.jobs import run_daily_aggregation, run_interval_builder

    await run_interval_builder(session, now=now)
    await run_daily_aggregation(session, days=[day], now=now)


async def test_example1_golden_values_on_firestore(world: dict[str, Any]) -> None:
    from app.modules.analytics.consumer import handle_domain_event
    from app.modules.analytics.mastery import get_topic_mastery

    now = datetime.now(UTC)
    day = ist_date(now) - timedelta(days=1)
    uid = uuid7()
    p = principal_for(uid)
    course, lesson, asset, topic = world["course"], world["lesson"], world["asset"], uuid7()
    q1, q2, q3 = (uuid7() for _ in range(3))
    a = Page("lesson_video", {"course_id": course, "lesson_id": lesson, "lesson_asset_id": asset})
    t0 = ist(day, 10)
    ev = [a.view(t0)]
    for i, t in enumerate(steps(t0, ist(day, 10, 30))):
        focused = t <= ist(day, 10, 20)
        media = {
            "lesson_asset_id": str(asset),
            "position_s": 15.0 * (i + 1),
            "rate": 1.0,
            "played_ranges": [[15.0 * i, 15.0 * (i + 1)]],
        }
        ev.append(a.hb(t, focused=focused, input_recent=focused, media=True, media_info=media))
        if t == ist(day, 10, 20):
            ev.append(a.blur(t))
    ev.append(a.ev("video.ended", ist(day, 10, 30), {"position_s": 1800.0, "duration_s": 1800.0}))
    ev.append(a.idle(ist(day, 10, 30)))
    b = Page("practice", {"topic_id": topic}, route="/app/practice/[setId]")
    t1 = ist(day, 10, 20)
    ev.append(b.view(t1))
    for t in steps(t1, ist(day, 10, 40)):
        q = q1 if t <= ist(day, 10, 24) else q2 if t <= ist(day, 10, 31) else q3
        ev.append(b.hb(t, entity={"topic_id": topic, "question_id": q}))
    ev.append(b.hide(ist(day, 10, 40)))

    session = FakeSession()
    results = await _ingest(session, p, ev, now)
    bad = [r for r in results if r["status"] != "accepted"]
    assert not bad, bad[:3]
    # one batch document per client batch (cost-safe), not one per event
    from app.modules.analytics import fs_raw

    docs = await fs_raw.all_docs(fs_raw.BATCHES, user_id=uid)
    assert len(docs) == -(-len(ev) // 100)
    # a retried batch is all duplicates
    again = await _ingest(session, p, ev[:100], now)
    assert {r["status"] for r in again} == {"duplicate"}

    answers = [(q1, ist(day, 10, 24)), (q2, ist(day, 10, 31)), (q3, ist(day, 10, 37))]
    for q, at in answers:
        ok = await handle_domain_event(
            session,
            event_id=uuid7(),
            event_type="practice.answered",
            payload={
                "user_id": str(uid),
                "question_id": str(q),
                "topic_ids": [str(topic)],
                "is_correct": True,
                "attempt_no": 1,
                "difficulty": "medium",
                "answered_at": at.isoformat(),
            },
            occurred_at=at,
        )
        assert ok

    await _build(session, now, day)
    rows = await _daily(uid, day)
    total = rows[("_total", uid)]
    # golden values of tests/analytics/test_pipeline.py example 1 (spec §3.13)
    assert total.m2_active_s == 2400  # union, not the 50-min per-tab sum
    assert total.m3_video_playback_s == 1800
    assert total.m5_learning_s == 2400
    assert total.m1_session_elapsed_s == 2400
    assert total.m4_assessment_s == 0
    assert rows[("lesson", lesson)].m2_active_s == 1200
    assert rows[("topic", topic)].m2_active_s == 1200
    assert rows[("course", course)].m2_active_s == 1200
    # counters computed from the fixture: 3 answers, all correct on the first attempt
    assert (total.questions_attempted, total.questions_correct, total.first_attempt_correct) == (
        len(answers),
        len(answers),
        len(answers),
    )
    assert rows[("topic", topic)].questions_attempted == len(answers)

    mastery = await get_topic_mastery(session, uid)
    assert mastery[0].topic_id == topic and mastery[0].band == "insufficient_data"
    assert mastery[0].attempts == len(answers)

    # every job re-run is idempotent; nothing left dirty
    await _build(session, now, day)
    again_rows = await _daily(uid, day)
    assert {k: (r.m2_active_s, r.m5_learning_s) for k, r in again_rows.items()} == {
        k: (r.m2_active_s, r.m5_learning_s) for k, r in rows.items()
    }
    assert (uid, day) not in await fs_raw.dirty_days()


async def test_counters_match_the_fixture(world: dict[str, Any]) -> None:
    """``questions_*`` / ``code_*`` / ``lessons_completed`` per entity are plain counts of the
    day's server events: compute them from the fixture and compare."""
    from app.modules.analytics.service import insert_server_event

    now = datetime.now(UTC)
    day = ist_date(now) - timedelta(days=1)
    uid, topic, course = uuid7(), uuid7(), uuid7()
    fixture = [
        ("practice.answer_submitted", {"is_correct": True, "attempt_no": 1}, {"topic_id": topic}),
        ("practice.answer_submitted", {"is_correct": False, "attempt_no": 1}, {"topic_id": topic}),
        ("practice.answer_submitted", {"is_correct": True, "attempt_no": 2}, {"topic_id": topic}),
        ("coding.run", {}, {}),
        ("coding.submission_judged", {"mode": "submit", "verdict": "AC"}, {}),
        ("learning.lesson_completed", {}, {"course_id": course}),
    ]
    for i, (et, payload, ent) in enumerate(fixture):
        at = ist(day, 9, i)
        assert await insert_server_event(
            None,  # type: ignore[arg-type]
            event_id=uuid7(),
            event_type=et,
            user_id=uid,
            privacy_tier="adult",
            occurred_at=at,
            payload=payload,
            entity=ent,
        )
    session = FakeSession()
    await _build(session, now, day)
    rows = await _daily(uid, day)
    answers = [p for et, p, _ in fixture if et == "practice.answer_submitted"]
    expect = {
        "questions_attempted": len(answers),
        "questions_correct": sum(1 for p in answers if p["is_correct"]),
        "first_attempt_correct": sum(1 for p in answers if p["is_correct"] and p["attempt_no"] <= 1),
        "code_runs": sum(1 for et, _, _ in fixture if et == "coding.run"),
        "code_submissions": sum(
            1 for et, p, _ in fixture if et == "coding.submission_judged" and p.get("mode") == "submit"
        ),
        "code_accepted": sum(
            1 for et, p, _ in fixture if et == "coding.submission_judged" and p.get("verdict") == "AC"
        ),
        "lessons_completed": sum(1 for et, _, _ in fixture if et == "learning.lesson_completed"),
    }
    total = rows[("_total", uid)]
    assert {k: getattr(total, k) for k in expect} == expect
    assert rows[("topic", topic)].questions_attempted == len(answers)
    assert rows[("course", course)].lessons_completed == 1
