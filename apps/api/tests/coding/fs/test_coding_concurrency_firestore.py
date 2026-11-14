"""Coding on Firestore where Postgres relied on locks / unique constraints (no Postgres):
``ux_cp_slug``, ``UNIQUE (problem, version, ordinal)``, ``ux_cd_user_problem_lang`` + FOR UPDATE,
``ux_crs_problem_lang``, the guarded worker claim, ``UNIQUE (user_id, idempotency_key)`` and
``UNIQUE (code_submission_id, ordinal)``."""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

import pytest

from app.core.errors import ProblemError
from app.core.principal import Principal
from app.modules.coding import authoring, service, worker
from app.modules.coding.schemas import ProblemCreateIn, TestCaseIn
from tests.coding.fs.support import seed_languages


def _p() -> Principal:
    return Principal(user_id=uuid.uuid4(), session_id=uuid.uuid4())


def _body(slug: str) -> ProblemCreateIn:
    return ProblemCreateIn(slug=slug, title="Concurrency", statement_md="x", difficulty=1)


async def _settle(coros: list[Any]) -> list[Any]:
    return list(await asyncio.gather(*coros, return_exceptions=True))


async def test_concurrent_create_same_slug_one_wins(coding_fs: Any) -> None:
    await seed_languages()
    out = await _settle([service.create_problem(None, _p(), _body("same-slug")) for _ in range(4)])  # type: ignore[arg-type]
    ok = [x for x in out if not isinstance(x, BaseException)]
    errs = [x for x in out if isinstance(x, BaseException)]
    assert len(ok) == 1
    assert all(isinstance(e, ProblemError) and e.code in ("validation_failed", "conflict") for e in errs)
    # another organization may reuse the slug (key is per org)
    other = _body("same-slug")
    other.organization_id = uuid.uuid4()
    assert (await service.create_problem(None, _p(), other)).slug == "same-slug"  # type: ignore[arg-type]
    with pytest.raises(ProblemError) as e:
        await service.create_problem(None, _p(), _body("same-slug"))  # type: ignore[arg-type]
    assert e.value.code == "validation_failed"


async def test_concurrent_case_adds_never_share_an_ordinal(coding_fs: Any) -> None:
    await seed_languages()
    p = await service.create_problem(None, _p(), _body("ordinals"))  # type: ignore[arg-type]
    body = TestCaseIn(kind="sample", input="1\n", expected_output="1\n")
    out = await _settle([service.add_test_case(None, p, body) for _ in range(4)])  # type: ignore[arg-type]
    ok = [x for x in out if not isinstance(x, BaseException)]
    assert ok and all(isinstance(x, ProblemError) and x.code == "conflict" for x in out if x not in ok)
    stored = await service.list_cases(None, p)  # type: ignore[arg-type]
    assert sorted(c.ordinal for c in stored) == list(range(1, len(stored) + 1)) and len(stored) == len(ok)


async def test_concurrent_version_bumps_one_wins(coding_fs: Any) -> None:
    await seed_languages()
    p = await service.create_problem(None, _p(), _body("bumps"))  # type: ignore[arg-type]
    await service.add_test_case(None, p, TestCaseIn(kind="sample", input="1", expected_output="1"))  # type: ignore[arg-type]
    p.status = "published"
    from app.modules.coding.repo_firestore import system_repo

    r = system_repo("test")
    await r.save_problem(p, ["status"], expect_version=1)
    copies = [await r.get_problem(p.id) for _ in range(3)]
    body = TestCaseIn(kind="sample", input="2", expected_output="2")
    out = await _settle([service.add_test_case(None, c, body) for c in copies])  # type: ignore[arg-type]
    ok = [x for x in out if not isinstance(x, BaseException)]
    assert len(ok) == 1 and ok[0].problem_version == 2
    assert all(x.code == "conflict" for x in out if isinstance(x, ProblemError))
    stored = await r.get_problem(p.id)
    assert stored.version_no == 2
    assert [c.ordinal for c in await r.cases(p.id, 2)] == [1, 2]  # one copy + one new, no duplicates


async def test_concurrent_draft_saves_count_the_window(coding_fs: Any) -> None:
    """Concurrent saves are serialised by the transaction (no lost window increments, like the
    Postgres row lock); the 21st save in the window is refused and writes nothing."""
    await seed_languages()
    p = await service.create_problem(None, _p(), _body("drafts"))  # type: ignore[arg-type]
    who = _p()
    first = await _settle([authoring.save_draft(None, who, p, "python3", f"print({i})") for i in range(5)])  # type: ignore[arg-type]
    assert not [x for x in first if isinstance(x, BaseException)], first
    d = await authoring.get_draft(None, who, p.id, "python3")  # type: ignore[arg-type]
    assert d.window_count == 5
    for i in range(authoring.DRAFTS_PER_MINUTE - 5):
        await authoring.save_draft(None, who, p, "python3", f"x{i}")  # type: ignore[arg-type]
    with pytest.raises(ProblemError) as e:
        await authoring.save_draft(None, who, p, "python3", "refused")  # type: ignore[arg-type]
    assert e.value.code == "rate_limited"
    d = await authoring.get_draft(None, who, p.id, "python3")  # type: ignore[arg-type]
    assert d.window_count == authoring.DRAFTS_PER_MINUTE and d.source_code != "refused"


async def test_concurrent_reference_solution_upserts(coding_fs: Any) -> None:
    await seed_languages()
    p = await service.create_problem(None, _p(), _body("refs"))  # type: ignore[arg-type]
    out = await _settle(
        [authoring.put_reference_solution(None, _p(), p, "python3", f"# v{i}") for i in range(4)]  # type: ignore[arg-type]
    )
    assert not [x for x in out if isinstance(x, BaseException)]
    rows = await authoring.list_reference_solutions(None, p)  # type: ignore[arg-type]
    assert len(rows) == 1 and rows[0].source_code in {f"# v{i}" for i in range(4)}


async def test_claim_record_and_idempotency_key(coding_fs: Any, fake_judge: Any) -> None:
    await seed_languages()
    author = _p()
    p = await service.create_problem(None, author, _body("judge"))  # type: ignore[arg-type]
    await service.add_test_case(None, p, TestCaseIn(kind="sample", input="1", expected_output="1"))  # type: ignore[arg-type]
    await service.add_test_case(None, p, TestCaseIn(kind="hidden", input="2", expected_output="2"))  # type: ignore[arg-type]
    from app.modules.coding.repo_firestore import system_repo

    await system_repo("test").save_problem(p, [], expect_version=1)
    p.status = "published"
    await system_repo("test").save_problem(p, ["status"], expect_version=1)
    user = uuid.uuid4()
    h = await service.judge_for_attempt(
        None,  # type: ignore[arg-type]
        user_id=user,
        organization_id=None,
        attempt_id=uuid.uuid4(),
        problem_id=p.id,
        language_key="python3",
        source_code="# FAKE_VERDICT: AC",
        idempotency_key="a1",
    )
    again = await service.judge_for_attempt(
        None,  # type: ignore[arg-type]
        user_id=user,
        organization_id=None,
        attempt_id=uuid.uuid4(),
        problem_id=p.id,
        language_key="python3",
        source_code="# FAKE_VERDICT: AC",
        idempotency_key="a1",
    )
    assert again.submission_id == h.submission_id and h.queue == "judge_assessment"
    # same stored key inserted twice: the unique key answers 409 conflict
    with pytest.raises(ProblemError) as e:
        await service.create_submission(
            None,  # type: ignore[arg-type]
            user_id=user,
            organization_id=None,
            problem=p,
            language_key="python3",
            mode="submit",
            source_code="x",
            idempotency_key="a1",
        )
    assert e.value.code == "conflict"
    claims = await asyncio.gather(*[worker.claim(None, h.submission_id) for _ in range(4)])
    assert sum(claims) == 1
    work = await worker.load_work(None, h.submission_id)
    results = await worker.execute(fake_judge, work, 1)
    assert await worker.record(None, work, results) == "AC"
    from app.core.firestore.errors import UniqueViolationError

    with pytest.raises(UniqueViolationError):  # results already stored for these ordinals
        await worker.record(None, work, results)
    j = await service.get_attempt_judgement(None, h.submission_id)  # type: ignore[arg-type]
    assert j is not None and j.status == "completed" and j.verdict == "AC" and j.passed_cases == 2


async def test_stale_running_is_requeued_and_release_paths(coding_fs: Any) -> None:
    from datetime import timedelta

    from app.core.time import utcnow
    from app.modules.coding.repo_firestore import system_repo

    await seed_languages()
    p = await service.create_problem(None, _p(), _body("stale"))  # type: ignore[arg-type]
    sub = await service.create_submission(
        None,  # type: ignore[arg-type]
        user_id=uuid.uuid4(),
        organization_id=None,
        problem=p,
        language_key="python3",
        mode="run",
        source_code="x",
        idempotency_key="s1",
    )
    r = system_repo("test")
    await r.update_submission(sub.id, {"status": "running", "started_at": utcnow() - timedelta(minutes=10)})
    assert await worker.pending_ids(None, 5) == [sub.id]
    assert (await r.get_submission(sub.id)).status == "queued"
    assert await worker.claim(None, sub.id)
    work = await worker.load_work(None, sub.id)
    assert await worker._release(None, work, timed_out=True) == "requeued_after_timeout"
    s = await r.get_submission(sub.id)
    assert s.status == "queued" and s.retry_count == 1 and s.started_at is None
