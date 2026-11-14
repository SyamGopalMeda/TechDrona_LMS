"""Placement on Firestore (``TD_STORE_PLACEMENT=firestore``): bank.py routed through
``repo_firestore`` on the emulator, plus the data-model mappers used by backfill/verify."""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from app.core.errors import ProblemError
from app.core.firestore.repository import assert_repository_scoped
from app.core.ids import uuid7
from app.core.principal import Principal
from app.modules.placement import bank
from app.modules.placement.models import PracticeResponse, PracticeSession, QuestionOption, QuestionVersion
from app.modules.placement.schemas import (
    CompanyCreate,
    CompanyPathPut,
    OptionIn,
    PathStepIn,
    PatternSection,
    QuestionContent,
    QuestionCreate,
    TagIn,
    TopicCreate,
    TopicPatch,
)

pytestmark = pytest.mark.usefixtures("placement_fs")


def _p() -> Principal:
    return Principal(user_id=uuid7(), session_id=uuid7(), grants=())


def _mcq(topic_id: uuid.UUID, stem: str = "What is 2+2?", **kw: Any) -> QuestionCreate:
    return QuestionCreate(
        question_type="mcq_single",
        primary_topic_id=topic_id,
        stem_html=f"<p>{stem}</p>",
        options=[OptionIn(html="3"), OptionIn(html="4", is_correct=True), OptionIn(html="5")],
        explanation_html="<p>Because.</p>",
        difficulty=2,
        **kw,
    )


def _content(stem: str) -> QuestionContent:
    return QuestionContent(
        stem_html=f"<p>{stem}</p>",
        options=[OptionIn(html="a", is_correct=True), OptionIn(html="b")],
        explanation_html="<p>x</p>",
        difficulty=3,
    )


async def _tree(s: Any) -> tuple[Any, Any, Any]:
    subj = await bank.create_topic(s, TopicCreate(slug="aptitude", name="Aptitude"))
    top = await bank.create_topic(s, TopicCreate(parent_id=subj.id, slug="numbers", name="Numbers"))
    sub = await bank.create_topic(s, TopicCreate(parent_id=top.id, slug="primes", name="Primes"))
    return subj, top, sub


async def _published(s: Any, topic_id: uuid.UUID, **kw: Any) -> tuple[Any, Any]:
    author, reviewer = _p(), _p()
    q, qv = await bank.create_question(s, author, _mcq(topic_id, **kw))
    await bank.submit_review(s, q.id)
    await bank.review(s, reviewer, q.id, "approve")
    qv = await bank.publish(s, q.id, reviewer)
    return q, qv


def test_repository_scope_lint() -> None:
    from app.modules.placement.repo_firestore import PlacementRepo

    assert_repository_scoped(PlacementRepo)


async def test_taxonomy_paths_unique_and_subtree_move(fake_session: Any) -> None:
    s = fake_session
    subj, top, sub = await _tree(s)
    assert (top.kind, top.depth, sub.path) == ("topic", 1, "aptitude/numbers/primes")
    with pytest.raises(ProblemError) as e:
        await bank.create_topic(s, TopicCreate(parent_id=subj.id, slug="numbers", name="Dup"))
    assert e.value.code == "invalid_state_transition"
    with pytest.raises(ProblemError):
        await bank.create_topic(s, TopicCreate(parent_id=sub.id, slug="deep", name="Too deep"))
    # rename the subject: every descendant path moves with it (one transaction)
    t, deps = await bank.patch_topic(s, subj.id, TopicPatch(slug="quant"))
    assert (t.path, deps) == ("quant", 0)
    assert (await bank.get_topic(s, sub.id)).path == "quant/numbers/primes"
    assert sorted(await bank.subtree_ids(s, await bank.get_topic(s, top.id))) == sorted([top.id, sub.id])
    # the old path is free again, the new one is taken
    again = await bank.create_topic(s, TopicCreate(slug="aptitude", name="Aptitude again"))
    assert again.path == "aptitude"
    with pytest.raises(ProblemError):
        await bank.create_topic(s, TopicCreate(slug="quant", name="Clash"))
    with pytest.raises(ProblemError) as e:
        await bank.get_topic(s, uuid7())
    assert e.value.code == "not_found"


async def test_question_workflow_sod_publish_and_versions(fake_session: Any) -> None:
    s = fake_session
    _subj, top, _sub = await _tree(s)
    author, editor, reviewer = _p(), _p(), _p()
    q, qv = await bank.create_question(s, author, _mcq(top.id, tags=[TagIn(tag_type="skill", value="arith")]))
    assert (qv.version_no, qv.status, qv.item_rating) == (1, "draft", 900)
    # draft edited in place by someone else -> co-author (SoD)
    qv2 = await bank.edit_question(s, editor, q.id, _content("edited stem"))
    assert qv2.id == qv.id and editor.user_id in qv2.edited_by
    await bank.submit_review(s, q.id)
    with pytest.raises(ProblemError) as e:
        await bank.review(s, editor, q.id, "approve")
    assert e.value.code == "sod_violation"
    with pytest.raises(ProblemError):
        await bank.publish(s, q.id, reviewer)  # not approved yet
    await bank.review(s, reviewer, q.id, "approve", "  looks good ")
    pub = await bank.publish(s, q.id, reviewer)
    assert pub.status == "published" and pub.published_at is not None
    q = await bank.get_question(s, q.id)
    assert (q.status, q.current_version_id) == ("active", pub.id)
    # editing a published question creates version 2; publishing it retires version 1
    v2 = await bank.edit_question(s, author, q.id, _content("second"))
    assert (v2.version_no, v2.status) == (2, "draft")
    await bank.submit_review(s, q.id)
    await bank.review(s, reviewer, q.id, "approve")
    await bank.publish(s, q.id, reviewer)
    statuses = {v.version_no: v.status for v in await bank.versions_of(s, q.id)}
    assert statuses == {2: "published", 1: "retired"}
    detail = await bank.question_detail(s, await bank.get_question(s, q.id), include_keys=True)
    assert [v["version_no"] for v in detail["versions"]] == [2, 1]
    assert detail["versions"][1]["review_comment"] == "looks good"
    assert detail["versions"][0]["options"][0]["is_correct"] is True
    assert detail["tags"] == [{"tag_type": "skill", "topic_id": None, "company_id": None, "value": "arith"}]
    assert len(detail["versions"][0]["content_hash"]) == 64
    # retire
    rq = await bank.retire(s, q.id, " outdated ")
    assert (rq.status, rq.retired_reason) == ("retired", "outdated")
    assert {v.status for v in await bank.versions_of(s, q.id)} == {"retired"}


async def test_published_versions_are_immutable(fake_session: Any) -> None:
    from app.modules.placement.repo_firestore import QuestionVersionImmutableError, repo

    s = fake_session
    _subj, top, _sub = await _tree(s)
    _q, qv = await _published(s, top.id)
    r = await repo(s)
    v, opts = (await r.get_versions([qv.id]))[qv.id]
    v.stem = {"html": "<p>tampered</p>"}
    with pytest.raises(QuestionVersionImmutableError):
        await r.save_version(v)
    v, opts = (await r.get_versions([qv.id]))[qv.id]
    v.status = "draft"
    with pytest.raises(QuestionVersionImmutableError):
        await r.save_version(v)
    v, opts = (await r.get_versions([qv.id]))[qv.id]
    opts[0].is_correct = not opts[0].is_correct  # options share the guard (embedded)
    with pytest.raises(QuestionVersionImmutableError):
        await r.save_version(v, opts)
    # allowed on a published version: non-frozen columns (e.g. review_comment), like the trigger
    v, _ = (await r.get_versions([qv.id]))[qv.id]
    v.review_comment = "note"
    await r.save_version(v)


async def test_delivery_pool_shapes_and_search(fake_session: Any) -> None:
    s = fake_session
    subj, top, sub = await _tree(s)
    co = await bank.create_company(s, CompanyCreate(slug="acme", name="Acme"))
    q1, v1 = await _published(
        s, sub.id, stem="Is 7 prime?", tags=[TagIn(tag_type="company", company_id=co.id)]
    )
    _q2, v2 = await _published(s, top.id, stem="Sum of digits")
    await bank.create_question(s, _p(), _mcq(top.id, stem="draft only"))
    pool = await bank.published_pool(s, topic_id=subj.id)
    assert pool == sorted([v1.id, v2.id])
    assert await bank.published_pool(s, topic_id=sub.id) == [v1.id]
    assert await bank.published_pool(s, topic_id=subj.id, company_id=co.id) == [v1.id]
    assert await bank.published_pool(s, topic_id=subj.id, difficulty_min=3) == []
    bundles = await bank.load_bundles(s, [v1.id, v2.id, uuid7()])
    assert set(bundles) == {v1.id, v2.id}
    b = bundles[v1.id]
    d = bank.delivery(b)
    assert d["type"] == "mcq_single" and [o["label"] for o in d["options"]] == ["A", "B", "C"]
    assert "is_correct" not in json.dumps(d)
    assert len(b.correct_option_ids) == 1
    shapes = await bank.load_answer_shapes(s, [v1.id])
    assert shapes[v1.id].option_ids == frozenset(b.option_ids)
    opts = await bank.options_of(s, [v1.id])
    assert [o.position for o in opts[v1.id]] == [1, 2, 3]
    # subject tree counts active questions up the path
    tree = await bank.subject_tree(s)
    root = next(n for n in tree if n["slug"] == "aptitude")
    assert root["question_count"] == 2 and root["children"][0]["question_count"] == 2
    # search
    common: dict[str, Any] = dict(
        topic_id=None,
        difficulty=None,
        status=None,
        company_id=None,
        tag=None,
        author=None,
        organization_ids=None,
        limit=50,
        offset=0,
    )
    assert len(await bank.search_questions(s, **common)) == 3
    hits = await bank.search_questions(s, **{**common, "text_query": "PRIME"})
    assert [h["question_id"] for h in hits] == [str(q1.id)]
    assert len(await bank.search_questions(s, **{**common, "status": "draft"})) == 1
    assert len(await bank.search_questions(s, **{**common, "company_id": co.id})) == 1
    assert len(await bank.search_questions(s, **{**common, "topic_id": sub.id})) == 1
    assert len(await bank.search_questions(s, **{**common, "version_status": "published"})) == 2
    assert len(await bank.search_questions(s, **{**common, "limit": 1, "offset": 1})) == 1


async def test_tn_visibility_hides_other_org_questions(fake_session: Any) -> None:
    from tests.placement.fs.conftest import FakeSession

    s = fake_session
    _subj, top, _sub = await _tree(s)
    org = uuid7()
    q, _ = await bank.create_question(s, _p(), _mcq(top.id, organization_id=org))
    outsider = FakeSession(user_id=str(uuid7()), is_platform=False)
    member = FakeSession(user_id=str(uuid7()), org_ids=(str(org),), is_platform=False)
    with pytest.raises(ProblemError):
        await bank.get_question(outsider, q.id)
    assert (await bank.get_question(member, q.id)).id == q.id
    # TN WITH CHECK: a non-member cannot create in that organization
    with pytest.raises(ProblemError) as e:
        await bank.create_question(outsider, _p(), _mcq(top.id, organization_id=org))
    assert e.value.code == "permission_denied"


async def test_companies_and_paths(fake_session: Any) -> None:
    s = fake_session
    subj, top, _sub = await _tree(s)
    co = await bank.create_company(s, CompanyCreate(slug="acme", name="Acme"))
    with pytest.raises(ProblemError):
        await bank.create_company(s, CompanyCreate(slug="acme", name="Acme 2"))
    body = CompanyPathPut(
        company_id=co.id,
        role_name="SDE",
        pattern=[PatternSection(section="Quant", topic_id=subj.id, weight=Decimal("1"))],
        steps=[PathStepIn(step_type="practice_set", title="Numbers", topic_id=top.id)],
    )
    pid = uuid7()
    p = await bank.put_company_path(s, _p(), pid, body)
    assert (p.version_no, p.status) == (1, "draft")
    p = await bank.put_company_path(
        s, _p(), pid, body.model_copy(update={"status": "published", "steps": body.steps * 2})
    )
    assert p.version_no == 2 and p.published_at is not None
    assert [x.position for x in await bank.path_steps(s, pid)] == [1, 2]
    # a second path for the same company+role gets the next version_no
    p2 = await bank.put_company_path(s, _p(), uuid7(), body)
    assert p2.version_no == 3  # max(version_no) + 1, as Postgres
    listed = await bank.list_companies(s)
    assert listed[0]["slug"] == "acme" and len(listed[0]["paths"]) == 2
    with pytest.raises(ProblemError):
        await bank.put_company_path(s, _p(), pid, body.model_copy(update={"role_name": "Other"}))


async def test_practice_answer_is_atomic_and_idempotent(fake_session: Any) -> None:
    from app.modules.placement.repo_firestore import repo

    s = fake_session
    r = await repo(s)
    uid = uuid7()
    now = datetime.now(UTC)
    ps = PracticeSession(
        id=uuid7(),
        user_id=uid,
        organization_id=None,
        mode="topic_set",
        topic_id=uuid7(),
        company_path_step_id=None,
        status="active",
        target_count=2,
        answered_count=0,
        correct_count=0,
        served=[],
        started_at=now,
        ended_at=None,
        updated_at=now,
    )
    await r.create_session(uid, ps)
    qv = uuid7()

    def resp() -> PracticeResponse:
        return PracticeResponse(
            id=uuid7(),
            practice_session_id=ps.id,
            user_id=uid,
            organization_id=None,
            question_version_id=qv,
            topic_id=uuid7(),
            response={"option_ids": []},
            is_correct=True,
            attempt_no=1,
            served_at=now,
            time_spent_ms=10,
            hint_used=False,
            solution_viewed=False,
            rating_before=None,
            rating_after=None,
            answered_at=now,
        )

    results = await asyncio.gather(*[r.record_answer(uid, resp(), counts_correct=True) for _ in range(4)])
    assert sum(1 for _, created, _ in results if created) == 1
    after = await r.get_session(uid, ps.id)
    assert (after.answered_count, after.correct_count) == (1, 1)
    assert len(await r.responses(uid, ps.id)) == 1
    assert await r.get_session(uuid7(), ps.id) is None  # another user's set is invisible


def test_mappers_round_trip_model_types() -> None:
    from app.modules.placement.store_specs import option_entry, orm_doc, orm_of, row_doc

    qv = QuestionVersion(
        id=uuid7(),
        question_id=uuid7(),
        organization_id=None,
        version_no=1,
        stem={"html": "x"},
        answer_key=None,
        explanation=None,
        difficulty=2,
        item_rating=900,
        default_marks=Decimal("1"),
        default_negative=Decimal("0.25"),
        expected_seconds=None,
        coding_problem_id=None,
        settings={},
        status="draft",
        content_hash=b"\x01" * 32,
        authored_by=uuid7(),
        reviewed_by=None,
        edited_by=[uuid7()],
        review_comment=None,
        published_at=None,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        updated_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    d = orm_doc(qv)
    assert d["default_marks"] == "1.00" and d["default_negative"] == "0.25"
    assert d["content_hash"] == "AQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQE=" and isinstance(
        d["edited_by"][0], str
    )
    back = orm_of(QuestionVersion, d)
    assert back.default_negative == Decimal("0.25") and back.content_hash == qv.content_hash
    assert back.edited_by == qv.edited_by and back.id == qv.id
    # backfill row (as Postgres returns it) maps to the same document as the repository writes
    assert (
        row_doc(QuestionVersion, {**d, "default_marks": Decimal("1.00"), "content_hash": b"\x01" * 32}) == d
    )
    oid = uuid7()
    o = option_entry(
        {
            "id": oid,
            "question_version_id": qv.id,
            "organization_id": None,
            "label": "A",
            "body": {"html": "a"},
            "is_correct": True,
            "position": 1,
            "feedback": None,
        }
    )
    assert o["options"][str(oid)]["question_version_id"] == str(qv.id)
    assert orm_of(QuestionOption, o["options"][str(oid)]).is_correct is True


def test_index_fragment_covers_queries() -> None:
    frag = Path(__file__).resolve().parents[3] / "app/modules/placement/firestore.indexes.fragment.json"
    data = json.loads(frag.read_text(encoding="utf-8"))
    groups = {(i["collectionGroup"], tuple(f["fieldPath"] for f in i["fields"])) for i in data["indexes"]}
    for need in [
        ("lms_question_versions", ("question_id", "created_at")),
        ("lms_question_tags", ("question_id", "created_at")),
        ("lms_company_path_steps", ("company_path_id", "position")),
        ("lms_practice_responses", ("user_id", "practice_session_id", "created_at")),
    ]:
        assert any(g == need[0] and f[: len(need[1])] == need[1] for g, f in groups), need


async def test_backfill_verify_and_repository_read_backfilled_rows(
    placement_fs: Any, fake_session: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Postgres rows (as asyncpg returns them) -> backfill -> verify clean -> bank.py reads them."""
    from app.core.firestore.backfill import verify
    from app.modules.placement import models as m
    from tests.placement.fs.backfill_helper import backfill_and_verify, fake_rows, model_row

    now = datetime(2026, 11, 1, 10, 0, tzinfo=UTC)
    uid, author, reviewer = uuid7(), uuid7(), uuid7()
    t = m.Topic(
        id=uuid7(),
        parent_id=None,
        kind="subject",
        slug="apt",
        name="Apt",
        path="apt",
        depth=0,
        position=0,
        is_active=True,
        created_at=now,
        updated_at=now,
    )
    t2 = m.Topic(
        id=uuid7(),
        parent_id=t.id,
        kind="topic",
        slug="num",
        name="Num",
        path="apt/num",
        depth=1,
        position=0,
        is_active=True,
        created_at=now,
        updated_at=now,
    )
    co = m.Company(
        id=uuid7(),
        slug="acme",
        name="Acme",
        logo_s3_key=None,
        industry=None,
        hub_status="draft",
        description_md=None,
        created_at=now,
        updated_at=now,
    )
    q = m.Question(
        id=uuid7(),
        organization_id=None,
        question_type="mcq_single",
        primary_topic_id=t2.id,
        status="active",
        current_version_id=None,
        external_ref=None,
        created_by=author,
        retired_reason=None,
        created_at=now,
        updated_at=now,
        deleted_at=None,
    )
    qv = m.QuestionVersion(
        id=uuid7(),
        question_id=q.id,
        organization_id=None,
        version_no=1,
        stem={"html": "<p>2+2</p>"},
        answer_key=None,
        explanation={"html": "x"},
        difficulty=2,
        item_rating=900,
        default_marks=Decimal("1.00"),
        default_negative=Decimal("0.00"),
        expected_seconds=None,
        coding_problem_id=None,
        settings={},
        status="published",
        content_hash=bytes(range(32)),
        authored_by=author,
        reviewed_by=reviewer,
        edited_by=[],
        review_comment=None,
        published_at=now,
        created_at=now,
        updated_at=now,
    )
    q.current_version_id = qv.id
    opts = [
        m.QuestionOption(
            id=uuid7(),
            question_version_id=qv.id,
            organization_id=None,
            label=lab,
            body={"html": lab},
            is_correct=lab == "B",
            position=i + 1,
            feedback=None,
        )
        for i, lab in enumerate("AB")
    ]
    tag = m.QuestionTag(
        id=uuid7(),
        question_id=q.id,
        organization_id=None,
        tag_type="company",
        topic_id=None,
        company_id=co.id,
        tag_value=None,
        created_at=now,
    )
    rep = m.QuestionReport(
        id=uuid7(),
        question_id=q.id,
        question_version_id=qv.id,
        organization_id=None,
        user_id=uid,
        category="wrong_answer",
        message="?",
        status="open",
        resolution=None,
        resolution_note=None,
        resolved_by=None,
        resolved_at=None,
        created_at=now,
        updated_at=now,
    )
    bk = m.QuestionBank(
        id=uuid7(),
        organization_id=None,
        name="Bank",
        subject=None,
        description=None,
        default_topic_id=None,
        created_by=author,
        last_added_at=now,
        created_at=now,
        updated_at=now,
        deleted_at=None,
    )
    item = m.QuestionBankItem(
        id=uuid7(), bank_id=bk.id, question_id=q.id, organization_id=None, added_by=author, added_at=now
    )
    ps = m.PracticeSession(
        id=uuid7(),
        user_id=uid,
        organization_id=None,
        mode="topic_set",
        topic_id=t.id,
        company_path_step_id=None,
        status="active",
        target_count=1,
        answered_count=1,
        correct_count=1,
        served=[{"qv": str(qv.id)}],
        started_at=now,
        ended_at=None,
        updated_at=now,
    )
    pr = m.PracticeResponse(
        id=uuid7(),
        practice_session_id=ps.id,
        user_id=uid,
        organization_id=None,
        question_version_id=qv.id,
        topic_id=t2.id,
        response={"option_ids": []},
        is_correct=True,
        attempt_no=1,
        served_at=now,
        time_spent_ms=5,
        hint_used=False,
        solution_viewed=False,
        rating_before=None,
        rating_after=None,
        answered_at=now,
    )
    rec = m.Recommendation(
        id=uuid7(),
        user_id=uid,
        organization_id=None,
        rule_key="weak_topic",
        rule_version=1,
        reason="r",
        evidence={},
        target_type="topic",
        target_id=t2.id,
        priority=50,
        status="active",
        generated_at=now,
        expires_at=now,
    )
    tables: dict[str, list[dict[str, Any]]] = {
        "topics": [model_row(t), model_row(t2)],
        "companies": [model_row(co)],
        "questions": [model_row(q)],
        "question_versions": [model_row(qv)],
        "question_options": [model_row(o) for o in opts],
        "question_tags": [model_row(tag)],
        "question_reports": [model_row(rep)],
        "question_banks": [model_row(bk)],
        "question_bank_items": [model_row(item)],
        "practice_sessions": [model_row(ps)],
        "practice_responses": [model_row(pr)],
        "recommendations": [model_row(rec)],
    }
    fake_rows(monkeypatch, tables)
    reports = await backfill_and_verify("placement", placement_fs)
    bad = [r.as_dict() for r in reports if not r.ok]
    assert not bad, bad
    assert {r.collection: r.fs_docs for r in reports}["question_versions"] == 1
    # the repository reads the backfilled documents as the same ORM values
    s = fake_session
    b = (await bank.load_bundles(s, [qv.id]))[qv.id]
    assert b.version.content_hash == qv.content_hash and b.version.default_marks == Decimal("1.00")
    assert [o.label for o in b.options] == ["A", "B"] and b.correct_option_ids == {opts[1].id}
    assert await bank.published_pool(s, topic_id=t.id, company_id=co.id) == [qv.id]
    assert (await bank.question_detail(s, q, include_keys=False))["banks"] == [
        {"id": str(bk.id), "name": "Bank"}
    ]
    with pytest.raises(ProblemError):  # path key backfilled too
        await bank.create_topic(s, TopicCreate(parent_id=t.id, slug="num", name="dup"))
    # a Firestore-side change is reported by verify
    tables["topics"][0]["name"] = "Changed in Postgres"
    again = {r.collection: r for r in await verify(None, "placement", client=placement_fs)}  # type: ignore[arg-type]
    assert again["topics"].mismatched == [str(t.id)]
