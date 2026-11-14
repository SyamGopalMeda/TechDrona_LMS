"""Row-lock parity on Firestore (assignments). Emulator only.

Classes: serialised last-writer (autosave), lease-held work (AI grading calls AI once per item),
locked state transition over two rows (regrade resolve + submission reopen), and
read-then-insert retried on a uniqueness key (submission attempt numbers)."""

from __future__ import annotations

import asyncio
import uuid
from types import SimpleNamespace
from typing import Any

import pytest

from tests.learning.fs_harness import firestore_emulator, fs  # noqa: F401
from tests.learning.test_fs_assign import _allocate, _assignment, _session, _spec, _submission, fs_on  # noqa: F401


async def _setup(
    status: str = "draft", engine: str = "pure_ai"
) -> tuple[Any, Any, Any, list[Any], uuid.UUID]:
    from app.modules.learning import structured as st

    s = _session()
    a = await _assignment(s)
    await st.put_structure(s, a, _spec(2))
    user = uuid.uuid4()
    al = await _allocate(s, a, user_ids=[user], engine=engine)
    sub = await _submission(s, a, al, user, status=status)
    items = [it for _sec, its in await st.load_structure(s, a.id) for it in its]
    return a, al, sub, items, user


async def test_concurrent_first_autosaves_conflict_like_postgres(
    fs: Any,  # noqa: F811
    fs_on: Any,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two first saves of the same item that both found no row: Postgres inserts twice and the
    unique index fails the second with 409 ``conflict``; Firestore must answer the same."""
    from app.core.errors import ProblemError
    from app.modules.learning import fs_assign as fsa
    from app.modules.learning import structured as st

    _a, _al, sub, items, _u = await _setup()
    n = 4
    barrier = asyncio.Barrier(n)
    real = fsa.response_for

    async def read_then_wait(*a: Any, **k: Any) -> Any:
        row = await real(*a, **k)
        await barrier.wait()  # every request has read "no row yet" before any inserts
        return row

    monkeypatch.setattr(fsa, "response_for", read_then_wait)

    async def save(t: str) -> str:
        try:
            await st.upsert_response(_session(), sub, items[0], {"text": t})
            return "ok"
        except ProblemError as e:
            return e.code

    out = await asyncio.gather(*(save(f"draft {i}") for i in range(n)))
    assert out.count("ok") == 1 and out.count("conflict") == n - 1, out
    monkeypatch.setattr(fsa, "response_for", real)
    rows = await st.responses_of(_session(), sub.id)
    assert list(rows) == [items[0].id]
    winner = rows[items[0].id].response["text"]
    assert winner.startswith("draft ")


async def test_concurrent_later_autosaves_serialise(fs: Any, fs_on: Any) -> None:  # noqa: F811
    """Saves of an existing row (``FOR UPDATE``): all succeed, one row, the last one wins."""
    from app.modules.learning import structured as st

    _a, _al, sub, items, _u = await _setup()
    await st.upsert_response(_session(), sub, items[0], {"text": "first"})
    texts = [f"draft {i}" for i in range(6)]
    out = await asyncio.gather(*(st.upsert_response(_session(), sub, items[0], {"text": t}) for t in texts))
    assert len({r.id for r in out}) == 1
    rows = await st.responses_of(_session(), sub.id)
    assert list(rows) == [items[0].id] and rows[items[0].id].response["text"] in texts


async def test_ai_grading_runs_once_per_item(fs: Any, fs_on: Any, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    from app.modules.ai import public as ai
    from app.modules.learning import structured as st

    _a, al, sub, items, _u = await _setup(status="submitted")
    for it in items:
        await st.upsert_response(_session(), sub, it, {"text": "an answer"})
    await st.queue_ai(_session(), [sub], {al.id: al})
    calls: list[str] = []

    async def fake_grade(*_a: Any, **_k: Any) -> Any:
        calls.append("x")
        await asyncio.sleep(0.2)
        return SimpleNamespace(marks=3, feedback_md="ok", confidence=0.9, criteria=[])

    monkeypatch.setattr(ai, "grade_response", fake_grade)
    done = await asyncio.gather(*(st.run_queued_ai(_session(), [sub.id], uuid.uuid4()) for _ in range(3)))
    assert sum(done) == 2 and len(calls) == 2  # each item sent to AI exactly once
    rows = await st.responses_of(_session(), sub.id)
    assert {r.ai_status for r in rows.values()} == {"pending"}


async def test_concurrent_regrade_resolutions_one_winner(fs: Any, fs_on: Any) -> None:  # noqa: F811
    from app.core.errors import ProblemError
    from app.modules.learning import fs_store as fss
    from app.modules.learning import structured_api as sapi
    from app.modules.learning.models import AssignmentRegradeRequest, AssignmentSubmission

    a, _al, sub, _items, user = await _setup(status="graded")
    rr = AssignmentRegradeRequest(
        id=uuid.uuid4(), submission_id=sub.id, assignment_id=a.id, user_id=user, reason="please recheck"
    )
    s = _session()
    fss.add(s, rr)
    await fss.flush(s)
    grader = SimpleNamespace(user_id=uuid.uuid4())

    async def resolve(action: str) -> str:
        body = SimpleNamespace(action=action, note=f"{action} note", reopen=action == "resolve")
        try:
            got = await sapi._resolve_regrade_fs(_session(), grader, rr.id, None, body)
            return got.status
        except ProblemError as e:
            return e.code

    out = await asyncio.gather(resolve("resolve"), resolve("reject"), resolve("resolve"))
    winners = [o for o in out if o in ("resolved", "rejected")]
    assert len(winners) == 1 and out.count("invalid_state_transition") == 2
    stored = await fss.get(_session(), AssignmentRegradeRequest, rr.id)
    sub_now = await fss.get(_session(), AssignmentSubmission, sub.id)
    assert stored is not None and sub_now is not None and stored.status == winners[0]
    # the submission is reopened only by a "resolve" winner, in the same transaction
    assert sub_now.status == ("submitted" if winners[0] == "resolved" else "graded")


async def test_concurrent_submissions_take_distinct_attempts(fs: Any, fs_on: Any) -> None:  # noqa: F811
    from app.core.errors import ProblemError
    from app.modules.learning import fs_enrol
    from app.modules.learning import router as lr

    s = _session()
    a = await _assignment(s, max_attempts=2)
    a.submission_type = "text"
    principal = SimpleNamespace(user_id=uuid.uuid4())
    body = SimpleNamespace(body_text="answer", link_url=None, file_s3_keys=[], code_submission_id=None)
    from app.core.time import utcnow

    async def submit() -> Any:
        try:
            return (await lr._submit_fs(_session(), principal, a, body, "on_time", utcnow())).attempt_no
        except ProblemError as e:
            return e.code

    out = await asyncio.gather(*(submit() for _ in range(4)))
    assert sorted(x for x in out if isinstance(x, int)) == [1, 2]  # Postgres: serialised by FOR UPDATE
    assert out.count("attempt_limit_reached") == 2
    subs = await fs_enrol.submissions_of(_session(), a.id, user_id=principal.user_id)
    assert sorted(x.attempt_no for x in subs) == [1, 2]
