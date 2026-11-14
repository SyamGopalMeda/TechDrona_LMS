"""Practice engine (PLC-19..27, PLC-32) on Firestore (``practice.py`` routed): no Postgres.

Consents and analytics mastery (other modules) are stubbed; the outbox event goes to Firestore;
entitlements use the allow-all checker of ``tests/placement/conftest.py``."""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

import pytest

from app.core.errors import ProblemError
from app.core.ids import uuid7
from app.core.principal import Principal
from app.modules.placement import bank, practice
from app.modules.placement.schemas import (
    OptionIn,
    PracticeAnswer,
    PracticeStart,
    QuestionCreate,
    TopicCreate,
)

pytestmark = pytest.mark.usefixtures("placement_fs", "allow_access")


@pytest.fixture(autouse=True)
def events(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, dict[str, Any]]]:
    seen: list[tuple[str, dict[str, Any]]] = []

    async def emit(session: Any, kind: str, payload: dict[str, Any], **kw: Any) -> Any:
        seen.append((kind, payload))
        return uuid7()

    async def allowed(session: Any, user_id: Any) -> bool:
        return True

    async def no_views(session: Any, user_id: Any) -> dict[Any, Any]:
        return {}

    monkeypatch.setattr(practice, "emit_event", emit)
    monkeypatch.setattr(practice, "personalisation_allowed", allowed)
    monkeypatch.setattr(practice, "analytics_mastery", no_views)
    return seen


def _p() -> Principal:
    return Principal(user_id=uuid7(), session_id=uuid7(), grants=())


def _answer(item: dict[str, Any], option: int) -> PracticeAnswer:
    q = item["question"]
    return PracticeAnswer(
        question_version_id=q["question_version_id"],
        response={"option_ids": [q["options"][option]["option_id"]]},
        time_spent_ms=5,
    )


async def _bank(s: Any, n: int = 3) -> Any:
    subj = await bank.create_topic(s, TopicCreate(slug="apt", name="Aptitude"))
    top = await bank.create_topic(s, TopicCreate(parent_id=subj.id, slug="num", name="Numbers"))
    for i in range(n):
        q, _ = await bank.create_question(
            s,
            _p(),
            QuestionCreate(
                question_type="mcq_single",
                primary_topic_id=top.id,
                stem_html=f"<p>Q{i}</p>",
                options=[OptionIn(html="right", is_correct=True), OptionIn(html="wrong")],
                explanation_html="<p>x</p>",
                difficulty=2,
            ),
        )
        await bank.submit_review(s, q.id)
        rv = _p()
        await bank.review(s, rv, q.id, "approve")
        await bank.publish(s, q.id, rv)
    return subj


async def test_practice_set_flow(fake_session: Any) -> None:
    s = fake_session
    subj = await _bank(s)
    me = _p()
    ps = await practice.start(s, me, PracticeStart(topic_id=subj.id, count=3))
    assert ps.target_count == 3 and len(ps.served) == 3
    ps = await practice.get_owned_session(s, me, ps.id, lock=True)
    st = await practice.state(s, ps)
    assert st["answered_count"] == 0 and len(st["items"]) == 3
    with pytest.raises(ProblemError):
        await practice.get_owned_session(s, _p(), ps.id)  # another learner: not found

    first, second = st["items"][0], st["items"][1]
    fbs = await asyncio.gather(*[practice.answer(s, me, ps, _answer(first, 0)) for _ in range(3)])
    assert all(f["is_correct"] is True for f in fbs)
    from app.core.firestore.core_store import OUTBOX
    from app.core.firestore.store import ScopedStore

    outbox = [
        d
        for d in await ScopedStore.system("test.read").scan(OUTBOX)
        if d["event_type"] == "practice.answered"
    ]
    assert len(outbox) == 1  # one response, one event: written in the answer's transaction
    ps = await practice.get_owned_session(s, me, ps.id)
    assert (ps.answered_count, ps.correct_count) == (1, 1)

    # reveal the solution of the second item, then answer it: recorded, never counted as correct
    qv2 = uuid.UUID(second["question"]["question_version_id"])
    sol = await practice.reveal(s, me, ps, qv2, "solution")
    assert sol["kind"] == "solution" and sol["correct_option_ids"]
    ps = await practice.get_owned_session(s, me, ps.id)
    fb = await practice.answer(s, me, ps, _answer(second, 1))
    assert fb["is_correct"] is False and fb["solution_viewed"] is True

    done = await practice.complete(s, me, ps)
    assert (done["status"], done["answered"], done["correct"], done["unanswered"]) == ("completed", 2, 1, 1)
    again = await practice.complete(s, me, await practice.get_owned_session(s, me, ps.id))
    assert again["status"] == "completed"
    with pytest.raises(ProblemError):
        await practice.answer(s, me, await practice.get_owned_session(s, me, ps.id), _answer(first, 0))

    review = await practice.review_list(s, me)
    assert [r["question_version_id"] for r in review] == [str(qv2)]
    m = await practice.mastery(s, me)
    assert m["topics"][0]["answered"] == 1 and m["method"] == practice.MASTERY_METHOD


async def test_recommendations_weak_topic(fake_session: Any) -> None:
    s = fake_session
    subj = await _bank(s, n=10)
    me = _p()
    ps = await practice.start(s, me, PracticeStart(topic_id=subj.id, count=10))
    for it in (await practice.state(s, ps))["items"]:
        await practice.answer(s, me, ps, _answer(it, 1))  # all wrong
    assert await practice.refresh_recommendations(s, me) == 1
    assert await practice.refresh_recommendations(s, me) == 1  # updated in place, no duplicate
    recs = await practice.list_recommendations(s, me)
    assert len(recs["items"]) == 1 and recs["items"][0]["target_type"] == "topic"
    rec_id = uuid.UUID(recs["items"][0]["id"])
    with pytest.raises(ProblemError):
        await practice.dismiss_recommendation(s, _p(), rec_id)
    await practice.dismiss_recommendation(s, me, rec_id)
    assert (await practice.list_recommendations(s, me))["items"] == []
    # dismissed recently: not re-created
    await practice.refresh_recommendations(s, me)
    assert (await practice.list_recommendations(s, me))["items"] == []
