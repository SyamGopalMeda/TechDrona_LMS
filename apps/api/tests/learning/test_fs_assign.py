"""Structured assignments on Firestore (``structured`` / ``fs_assign``), emulator only.

An unbound ``AsyncSession`` only carries the ``fs_store`` unit of work; the paths exercised here
touch no Postgres table (inline items only; batch membership is stubbed where needed). The HTTP
flows (audit, outbox, RBAC, orgs) need Postgres and run in the learning matrix suite."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest

from tests.learning.fs_harness import firestore_emulator, fs  # noqa: F401


@pytest.fixture
def fs_on(monkeypatch: pytest.MonkeyPatch) -> Any:
    from app.core.firestore.backend import reset_store_backends

    monkeypatch.setenv("TD_STORE_LEARNING", "firestore")
    reset_store_backends()
    yield
    monkeypatch.delenv("TD_STORE_LEARNING", raising=False)
    reset_store_backends()


def _session() -> Any:
    from sqlalchemy.ext.asyncio import AsyncSession

    return AsyncSession()


ORG = uuid.uuid4()


async def _assignment(s: Any, **kw: Any) -> Any:
    from app.modules.learning import fs_store as fss
    from app.modules.learning.models import Assignment

    a = Assignment(
        id=uuid.uuid4(),
        organization_id=ORG,
        title=kw.pop("title", "Essay set"),
        instructions_md="Answer all",
        submission_type="structured",
        max_score=Decimal("10"),
        allowed_file_types=["pdf"],
        created_by=uuid.uuid4(),
        **kw,
    )
    fss.add(s, a)
    await fss.flush(s)
    return a


def _spec(n_items: int = 2, marks: str = "5") -> list[Any]:
    from app.modules.learning import structured as st

    items = [
        st.ItemSpec(source="inline", marks=Decimal(marks), item_type="essay", prompt_md=f"Q{j}")
        for j in range(n_items)
    ]
    return [st.SectionSpec(title="Part A", max_score=None, items=items)]


async def _allocate(
    s: Any,
    a: Any,
    *,
    user_ids: list[uuid.UUID] = (),
    batch_id: uuid.UUID | None = None,
    engine: str = "pure_ai",
    evaluators: list[uuid.UUID] = (),
    **kw: Any,
) -> Any:  # type: ignore[assignment]
    from app.modules.learning import fs_store as fss
    from app.modules.learning import structured as st
    from app.modules.learning.models import AssignmentAllocation

    structure = await st.load_structure(s, a.id)
    al = AssignmentAllocation(
        id=uuid.uuid4(),
        assignment_id=a.id,
        organization_id=ORG,
        batch_id=batch_id,
        user_ids=list(user_ids),
        due_at=kw.pop("due_at", datetime.now(UTC) + timedelta(days=3)),
        section_engines={str(sec.id): engine for sec, _ in structure},
        evaluator_ids=list(evaluators),
        extensions={},
        created_by=uuid.uuid4(),
        **kw,
    )
    fss.add(s, al)
    await fss.flush(s)
    return al


async def _submission(
    s: Any, a: Any, al: Any, user: uuid.UUID, attempt: int = 1, status: str = "draft"
) -> Any:
    from app.modules.learning import fs_store as fss
    from app.modules.learning.models import AssignmentSubmission

    sub = AssignmentSubmission(
        id=uuid.uuid4(),
        assignment_id=a.id,
        user_id=user,
        organization_id=ORG,
        attempt_no=attempt,
        status=status,
        allocation_id=al.id if al else None,
        file_s3_keys=[],
    )
    fss.add(s, sub)
    await fss.flush(s)
    return sub


async def test_structure_put_load_clone_counts(fs: Any, fs_on: Any) -> None:  # noqa: F811
    from app.modules.learning import structured as st
    from app.modules.learning.models import Assignment

    s = _session()
    a = await _assignment(s)
    before = a.updated_at
    await st.put_structure(s, a, _spec(2))
    assert a.updated_at is not None and a.updated_at >= before
    structure = await st.load_structure(_session(), a.id)
    assert [(sec.title, [it.prompt_md for it in its]) for sec, its in structure] == [("Part A", ["Q0", "Q1"])]
    assert st.marks_check(a, structure)["ok"]
    # replacing the structure deletes the old sections AND items (no FK cascade on Firestore)
    await st.put_structure(s, a, _spec(1, "10"))
    assert await st.structure_counts(_session(), [a.id]) == {a.id: (1, 1)}
    s2 = _session()
    dst = await _assignment(s2, title="copy")
    await st.clone_structure(s2, a, dst)
    got = await st.load_structure(_session(), dst.id)
    assert [it.marks for _sec, its in got for it in its] == [Decimal("10.00")]
    assert isinstance(dst, Assignment)


async def test_locked_after_first_submission_and_attempt_unique(fs: Any, fs_on: Any) -> None:  # noqa: F811
    from app.core.errors import ProblemError
    from app.modules.learning import structured as st

    s = _session()
    a = await _assignment(s)
    await st.put_structure(s, a, _spec(2))
    al = await _allocate(s, a, user_ids=[uuid.uuid4()])
    user = al.user_ids[0]
    assert not await st.is_locked(s, a.id)
    await _submission(s, a, al, user)
    assert await st.is_locked(s, a.id)
    with pytest.raises(ProblemError) as e:
        await st.put_structure(s, a, _spec(1, "10"))
    assert e.value.code == "assignment_locked"
    with pytest.raises(ProblemError) as e2:  # (assignment, user, attempt) is unique
        await _submission(_session(), a, al, user)
    assert e2.value.code == "conflict"
    await _submission(_session(), a, al, uuid.uuid4(), status="submitted")
    assert await st.unfinalized_count(_session(), a.id) == 1


async def test_allocation_visibility_sets(fs: Any, fs_on: Any) -> None:  # noqa: F811
    from app.modules.learning import structured as st

    s = _session()
    now = datetime.now(UTC)
    learner, other, ev, batch = uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    a1 = await _assignment(s, title="direct")
    await st.put_structure(s, a1, _spec(2))
    al1 = await _allocate(s, a1, user_ids=[learner], evaluators=[ev])
    a2 = await _assignment(s, title="batch")
    await st.put_structure(s, a2, _spec(2))
    await _allocate(s, a2, batch_id=batch)
    a3 = await _assignment(s, title="expired")
    await st.put_structure(s, a3, _spec(2))
    al3 = await _allocate(
        s, a3, user_ids=[learner], visible_until=now - timedelta(hours=1), due_at=now - timedelta(hours=2)
    )
    await _submission(_session(), a3, al3, learner, status="submitted")
    assert await st.is_named_evaluator(_session(), a1.id, ev)
    assert not await st.is_named_evaluator(_session(), a2.id, ev)
    assert await st.allocation_batches(_session(), a2.id) == [batch]
    got = await st.learner_allocation(_session(), learner, set(), a1)
    assert got is not None and got.id == al1.id
    assert await st.learner_allocation(_session(), other, set(), a1) is None


async def test_response_upsert_auto_marks_and_ai_queue(fs: Any, fs_on: Any) -> None:  # noqa: F811
    from app.modules.learning import structured as st

    s = _session()
    a = await _assignment(s)
    await st.put_structure(s, a, _spec(2))
    user = uuid.uuid4()
    al = await _allocate(s, a, user_ids=[user], engine="pure_ai")
    sub = await _submission(s, a, al, user)
    items = [it for _sec, its in await st.load_structure(s, a.id) for it in its]
    r1 = await st.upsert_response(s, sub, items[0], {"text": "first"})
    r1b = await st.upsert_response(_session(), sub, items[0], {"text": "second"})
    assert r1b.id == r1.id  # same (submission, item) row, updated in place
    rows = await st.responses_of(_session(), sub.id)
    assert list(rows) == [items[0].id] and rows[items[0].id].response == {"text": "second"}

    s2 = _session()
    sub2 = await _reload_sub(s2, sub.id)
    sub2.status, sub2.submitted_at = "submitted", datetime.now(UTC)
    from app.modules.learning import fs_store as fss

    await fss.flush(s2)
    queued, auto = await st.queue_ai(s2, [sub2], {al.id: al})
    # unanswered item -> rule mark 0 and a row created; answered essay -> queued for AI
    assert (queued, auto) == (1, 1)
    rows = await st.responses_of(_session(), sub.id)
    assert rows[items[1].id].auto_marks == Decimal("0") and rows[items[1].id].response is None
    assert rows[items[0].id].ai_status == "queued"


async def _reload_sub(s: Any, sid: uuid.UUID) -> Any:
    from app.modules.learning import fs_store as fss
    from app.modules.learning.models import AssignmentSubmission

    return await fss.get(s, AssignmentSubmission, sid)


async def test_run_queued_ai_stores_pending_suggestion(
    fs: Any,  # noqa: F811
    fs_on: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.modules.ai import public as ai
    from app.modules.learning import structured as st

    s = _session()
    a = await _assignment(s)
    await st.put_structure(s, a, _spec(2))
    user = uuid.uuid4()
    al = await _allocate(s, a, user_ids=[user], engine="pure_ai")
    sub = await _submission(s, a, al, user, status="submitted")
    items = [it for _sec, its in await st.load_structure(s, a.id) for it in its]
    await st.upsert_response(s, sub, items[0], {"text": "an answer"})
    await st.queue_ai(s, [sub], {al.id: al})

    class Sug:
        marks, feedback_md, confidence, criteria = 9, "good", 0.8, [{"c": "x"}]

    async def fake_grade(*_a: Any, **_k: Any) -> Any:
        return Sug()

    monkeypatch.setattr(ai, "grade_response", fake_grade)
    done = await st.run_queued_ai(_session(), [sub.id], uuid.uuid4())
    assert done == 1
    row = (await st.responses_of(_session(), sub.id))[items[0].id]
    assert (row.ai_status, row.ai_marks, row.ai_feedback_md) == ("pending", Decimal("5.00"), "good")
    assert row.final_marks is None  # never final without a staff finalize


async def test_one_open_regrade_per_submission(fs: Any, fs_on: Any) -> None:  # noqa: F811
    from app.core.errors import ProblemError
    from app.modules.learning import fs_assign as fsa
    from app.modules.learning import fs_store as fss
    from app.modules.learning import structured as st
    from app.modules.learning.models import AssignmentRegradeRequest

    s = _session()
    a = await _assignment(s)
    await st.put_structure(s, a, _spec(2))
    user = uuid.uuid4()
    al = await _allocate(s, a, user_ids=[user])
    sub = await _submission(s, a, al, user, status="graded")

    def rr() -> AssignmentRegradeRequest:
        return AssignmentRegradeRequest(
            id=uuid.uuid4(),
            submission_id=sub.id,
            assignment_id=a.id,
            user_id=user,
            reason="please recheck",
            status="open",
        )

    first = rr()
    fss.add(s, first)
    await fss.flush(s)
    s2 = _session()
    fss.add(s2, rr())
    with pytest.raises(ProblemError) as e:
        await fss.flush(s2)
    assert e.value.code == "conflict"
    reqs = await fsa.regrades_of(_session(), assignment_id=a.id)
    assert [r.id for r in reqs] == [first.id]
    s3 = _session()
    cur = await fss.get(s3, AssignmentRegradeRequest, first.id)
    cur.status = "resolved"
    await fss.flush(s3)
    fss.add(_session(), rr())  # not flushed: just checks no exception on add


async def test_release_state_read_through_fs(fs: Any, fs_on: Any) -> None:  # noqa: F811
    """Grades release is a column on the assignment (set by router release-grades); the
    learner result gate reads it back from the Firestore row."""
    from app.modules.learning import fs_store as fss
    from app.modules.learning.models import Assignment

    s = _session()
    a = await _assignment(s)
    a.grades_released_at = datetime.now(UTC)
    await fss.flush(s)
    got = await fss.get(_session(), Assignment, a.id)
    assert got is not None and got.grades_released_at is not None


async def test_coding_access_grant(fs: Any, fs_on: Any, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    from app.modules.learning import fs_store as fss
    from app.modules.learning import structured as st
    from app.modules.learning.models import AssignmentItem

    async def no_batches(_s: Any, _u: Any) -> set[uuid.UUID]:
        return set()

    monkeypatch.setattr(st, "active_batch_ids", no_batches)
    s = _session()
    a = await _assignment(s)
    await st.put_structure(s, a, _spec(1, "10"))
    problem = uuid.uuid4()
    it = (await st.load_structure(s, a.id))[0][1][0]
    it2 = await fss.get(s, AssignmentItem, it.id)
    it2.item_type, it2.coding_problem_id = "coding", problem
    await fss.flush(s)
    user = uuid.uuid4()
    al = await _allocate(s, a, user_ids=[user])

    class P:
        user_id = user

    assert not await st.coding_access_grant(_session(), P(), problem)  # not started yet
    await _submission(_session(), a, al, user)  # draft
    assert await st.coding_access_grant(_session(), P(), problem)
    assert not await st.coding_access_grant(_session(), P(), uuid.uuid4())
