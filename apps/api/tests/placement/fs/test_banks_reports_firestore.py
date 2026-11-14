"""Question banks, bulk import, learner reports, media sweep and erasure on Firestore (no Postgres).

Route handlers wrap these with idempotency/audit (Postgres core, not part of this module); the
module functions they call are exercised directly."""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from app.core.errors import ProblemError
from app.core.ids import uuid7
from app.core.principal import Principal
from app.modules.placement import bank, banks, bulk_import
from app.modules.placement.schemas import BankCreate, BankPatch, OptionIn, QuestionCreate, TopicCreate

pytestmark = pytest.mark.usefixtures("placement_fs")


def _p() -> Principal:
    return Principal(user_id=uuid7(), session_id=uuid7(), grants=())


async def _published(s: Any, topic_id: uuid.UUID, stem: str, tags: list[Any] | None = None) -> Any:
    q, _ = await bank.create_question(
        s,
        _p(),
        QuestionCreate(
            question_type="mcq_single",
            primary_topic_id=topic_id,
            stem_html=f"<p>{stem}</p>",
            options=[OptionIn(html="a", is_correct=True), OptionIn(html="b")],
            explanation_html="<p>x</p>",
            difficulty=2,
            tags=tags or [],
        ),
    )
    await bank.submit_review(s, q.id)
    rv = _p()
    await bank.review(s, rv, q.id, "approve")
    await bank.publish(s, q.id, rv)
    return q


async def test_banks_lifecycle(fake_session: Any) -> None:
    from app.modules.placement.schemas import TagIn

    s = fake_session
    top = await bank.create_topic(s, TopicCreate(slug="apt", name="Apt"))
    q1 = await _published(s, top.id, "Prime numbers", [TagIn(tag_type="skill", value="primes")])
    q2 = await _published(s, top.id, "Ratios")
    b = await banks.create_bank(s, _p(), BankCreate(name="  Quant  ", subject="Maths"))
    assert (b.name, b.last_added_at) == ("Quant", None)
    assert await banks.add_questions(s, _p(), b, [q1.id, q2.id, q1.id]) == 2
    assert await banks.add_questions(s, _p(), b, [q1.id]) == 0  # already in: skipped
    b = await banks.get_bank(s, b.id)
    assert b.last_added_at is not None
    detail = await banks.bank_detail(s, b)
    assert detail["question_count"] == 2 and detail["type_counts"] == {"mcq_single": 2}
    assert detail["tags"] == ["primes"]
    listed = await banks.list_banks(s, organization_ids=[None], text_query="qua")
    assert listed["total"] == 1 and listed["counters"] == {"banks": 1, "questions": 2, "subjects": 1}
    page = await banks.bank_questions(s, b, text_query="PRIME")
    assert [i["question_id"] for i in page["items"]] == [str(q1.id)] and page["tags"] == ["primes"]
    assert (await banks.bank_questions(s, b, tag="primes"))["total"] == 1
    resolved = await banks.resolve_questions(s, [q1.id], keys_visible={q1.id: True})
    assert resolved[0]["version"]["options"][0]["is_correct"] is True and resolved[0]["tags"] == ["primes"]
    b = await banks.patch_bank(s, b, BankPatch(subject=None))
    assert (await banks.get_bank(s, b.id)).subject is None
    # published question: removal OK, purge refused (and nothing removed)
    with pytest.raises(ProblemError):
        await banks.remove_question(s, b, q2.id, purge=True)
    assert (await banks.bank_detail(s, b))["question_count"] == 2
    assert await banks.remove_question(s, b, q2.id, purge=False) is False
    with pytest.raises(ProblemError):
        await banks.remove_question(s, b, q2.id, purge=False)
    # a never-published draft can be purged
    draft, _ = await bank.create_question(
        s,
        _p(),
        QuestionCreate(
            question_type="mcq_single",
            primary_topic_id=top.id,
            stem_html="<p>d</p>",
            options=[OptionIn(html="a", is_correct=True), OptionIn(html="b")],
            difficulty=1,
        ),
    )
    await banks.add_questions(s, _p(), b, [draft.id])
    assert await banks.remove_question(s, b, draft.id, purge=True) is True
    with pytest.raises(ProblemError):
        await bank.get_question(s, draft.id)
    await banks.delete_bank(s, b)
    with pytest.raises(ProblemError):
        await banks.get_bank(s, b.id)


async def test_bulk_import_all_or_nothing(fake_session: Any) -> None:
    s = fake_session
    b = await banks.create_bank(s, _p(), BankCreate(name="Imported"))
    good = {"question": "2+2?", "options": [{"text": "4", "correct": True}, {"text": "5", "correct": False}]}
    items, problems = bulk_import.check("mcq", None, [good, {**good, "question": "3+3?"}])
    assert not problems, problems
    ids = await bulk_import.import_items(s, _p(), items, bank=b, primary_topic_id=None, source="test")
    assert len(ids) == 2
    assert (await banks.bank_detail(s, await banks.get_bank(s, b.id)))["question_count"] == 2
    q = await bank.get_question(s, ids[0])
    assert q.status == "draft" and (await bank.get_topic(s, q.primary_topic_id)).path == "uncategorised"


async def test_reports_queue_and_resolve(fake_session: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.modules.placement import reports
    from app.modules.placement.repo_firestore import repo

    s = fake_session
    top = await bank.create_topic(s, TopicCreate(slug="apt", name="Apt"))
    q = await _published(s, top.id, "Typo here")
    me = _p()
    target, _ = await reports._resolve_target(s, q.id, None)
    assert target.id == q.id
    from app.core.time import utcnow
    from app.modules.placement.models import QuestionReport

    def rep() -> QuestionReport:
        now = utcnow()
        return QuestionReport(
            id=uuid7(),
            question_id=q.id,
            question_version_id=None,
            organization_id=None,
            user_id=me.user_id,
            category="typo",
            message="typo",
            status="open",
            resolution=None,
            resolution_note=None,
            resolved_by=None,
            resolved_at=None,
            created_at=now,
            updated_at=now,
        )

    r = await repo(s)
    first = await r.create_report(me.user_id, rep())
    with pytest.raises(ProblemError) as e:
        await r.create_report(me.user_id, rep())  # one open report per learner + question
    assert e.value.code == "invalid_state_transition"

    async def allow(org: Any) -> bool:
        return True

    queue = await reports._fs_queue(s, allow, "open", None, 10)
    assert queue["open_count"] == 1 and queue["data"] == [reports.report_out(first)]
    done = await r.resolve_report(
        first.id,
        {"status": "resolved", "resolution": "fixed", "resolved_by": me.user_id, "resolved_at": utcnow()},
    )
    assert done.status == "resolved"
    with pytest.raises(ProblemError):
        await r.resolve_report(first.id, {"status": "resolved"})
    await r.create_report(me.user_id, rep())  # open key released: may report again
    assert (await reports._fs_queue(s, allow, None, None, 10))["open_count"] == 1


async def test_erasure_and_media_sweep(fake_session: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.time import utcnow
    from app.modules.placement import privacy, qbank_router, tasks
    from app.modules.placement.models import PracticeSession, QuestionMedia
    from app.modules.placement.repo_firestore import repo

    s = fake_session
    r = await repo(s)
    uid = uuid7()
    now = utcnow()
    await r.create_session(
        uid,
        PracticeSession(
            id=uuid7(),
            user_id=uid,
            organization_id=None,
            mode="topic_set",
            topic_id=uuid7(),
            company_path_step_id=None,
            status="active",
            target_count=1,
            answered_count=0,
            correct_count=0,
            served=[],
            started_at=now,
            ended_at=None,
            updated_at=now,
        ),
    )
    out = await privacy.erase_user(s, uid)
    assert out["practice_sessions_deleted"] == 1 and await r.sessions_of(uid) == []

    m = QuestionMedia(
        id=uuid7(),
        organization_id=None,
        s3_key=f"qm/{uuid7()}/a.png",
        content_type="image/png",
        size_bytes=10,
        status="uploading",
        scan_status="pending",
        created_by=uid,
        created_at=now,
        updated_at=now,
    )
    await r.create_media(m)

    async def clean(mm: Any) -> bool:
        mm.scan_status, mm.status = "clean", "ready"
        return True

    monkeypatch.setattr(qbank_router, "refresh_scan", clean)
    assert await tasks.media_scan_sweep() == 1
    got = await r.get_media(m.id)
    assert (got.scan_status, got.status) == ("clean", "ready")
    assert await tasks.media_scan_sweep() == 0
