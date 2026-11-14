"""``coding.public`` submission reads for assessments on Firestore (no Postgres):
``get_submission``, ``attempt_submissions`` and ``attempt_code_signals`` (the ``cs`` CTE of
``assessments.integrity.FLAGS_SQL``: max submits per problem per clock hour, similarity flags)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from app.core.ids import uuid7
from app.modules.coding import public as coding_public
from app.modules.coding.models import CodeSubmission
from app.modules.coding.repo_firestore import system_repo


def _sub(
    user: uuid.UUID, attempt: uuid.UUID | None, problem: uuid.UUID, at: datetime, **kw: Any
) -> CodeSubmission:
    return CodeSubmission(
        id=uuid7(),
        user_id=user,
        organization_id=None,
        coding_problem_id=problem,
        problem_version=1,
        language_key="python3",
        mode=kw.pop("mode", "submit"),
        attempt_id=attempt,
        source_code="x",
        status=kw.pop("status", "completed"),
        judge_provider="fake",
        queue_name="judge_assessment",
        idempotency_key=f"submit:{uuid.uuid4()}",
        queued_at=at,
        similarity_flag=kw.pop("similarity_flag", False),
        **kw,
    )


async def test_attempt_reads_and_code_signals(coding_fs: Any) -> None:
    r = system_repo("test.seed")
    user, other = uuid.uuid4(), uuid.uuid4()
    a1, a2, a3 = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    p1, p2 = uuid.uuid4(), uuid.uuid4()
    h = datetime(2026, 11, 12, 10, 5, tzinfo=UTC)
    subs = [
        # a1: 3 submits on p1 within 10:00-11:00, 1 at 11:01; 1 on p2; 2 similarity flags
        _sub(user, a1, p1, h, similarity_flag=True),
        _sub(user, a1, p1, h + timedelta(minutes=20)),
        _sub(user, a1, p1, h + timedelta(minutes=50), similarity_flag=True),
        _sub(user, a1, p1, h + timedelta(minutes=56)),
        _sub(user, a1, p2, h),
        _sub(user, a1, p1, h, mode="run"),  # runs never count
        _sub(user, None, p1, h),  # practice: no attempt
        # a2: one submit
        _sub(other, a2, p1, h),
    ]
    for s in subs:
        await r.add_submission(s.user_id, s)

    signals = await coding_public.attempt_code_signals(None, [a1, a2, a3])
    assert signals == {a1: (3, 2), a2: (1, 0)}  # a3: no submissions -> absent (coalesce 0)
    assert await coding_public.attempt_code_signals(None, []) == {}

    mine = await coding_public.attempt_submissions(None, attempt_id=a1, user_id=user, problem_id=p1)
    assert [s.id for s in mine] == [s.id for s in subs[:4]]  # submit mode only, oldest first
    runs = await coding_public.attempt_submissions(
        None, attempt_id=a1, user_id=user, problem_id=p1, mode="run"
    )
    assert [s.id for s in runs] == [subs[5].id]
    assert await coding_public.attempt_submissions(None, attempt_id=a1, user_id=other, problem_id=p1) == []

    got = await coding_public.get_submission(None, subs[0].id)
    assert got is not None and got.attempt_id == a1 and got.similarity_flag is True
    assert await coding_public.get_submission(None, uuid.uuid4()) is None
