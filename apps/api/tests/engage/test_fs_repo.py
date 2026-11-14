"""engage on Firestore: data path + repository invariants + aggregation folds (emulator only).

Runs without Postgres (``--noconftest``; see ``tests/learning/fs_harness.py``). The HTTP flows on
Firestore are covered by ``test_engage_firestore_matrix.py`` (needs Postgres for users/RBAC)."""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from tests.learning.fs_harness import backfill_rows, firestore_emulator, fs  # noqa: F401
from tests.learning.test_fs_data_path import synthetic

T0 = datetime(2026, 11, 1, 9, 0, tzinfo=UTC)


def _activity(**over: Any) -> Any:
    from app.modules.engage.models import EngageActivity

    base = dict(
        id=uuid.uuid4(), organization_id=None, batch_id=None, owner_id=uuid.uuid4(), activity_type="quiz",
        title="Warm-up", description=None, run_mode="instant", audience="public", identity_mode="named",
        results_mode="live", pacing="all_at_once", winner_rule="fastest_first", participant_limit=None,
        opens_at=None, closes_at=None, deleted_at=None,
    )  # fmt: skip
    base.update(over)
    return EngageActivity(**base)


def _question(a: Any, pos: int) -> Any:
    from app.modules.engage.models import EngageQuestion

    return EngageQuestion(
        id=uuid.uuid4(), activity_id=a.id, organization_id=None, position=pos, kind="single_choice",
        prompt=f"Q{pos}", options=[{"id": "a", "text": "A", "is_correct": True}, {"id": "b", "text": "B", "is_correct": False}],
        max_words=None, source_question_id=None, source_version_id=None,
    )  # fmt: skip


async def _launch(rp: Any, a: Any, qs: list[Any], *, codes: Any = None, limit: int | None = None) -> Any:
    from app.core.time import utcnow
    from app.modules.engage import service as pg
    from app.modules.engage.models import EngageRun

    now = utcnow()
    settings = {**pg.settings_of(a), "participant_limit": limit}

    def build(n: int) -> EngageRun:
        return EngageRun(
            id=uuid.uuid4(), activity_id=a.id, organization_id=None, run_no=n, join_code="", status="scheduled",
            settings=settings, questions=[pg._snapshot(q) for q in qs], current_position=0, revealed_positions=[],
            closed_positions=[], results_published=False, state_version=1, opens_at=None, closes_at=None,
            opened_at=None, closed_at=None, finalised_at=None, created_by=a.owner_id, created_at=now,
        )  # fmt: skip

    return await rp.launch(a, build, codes or pg._join_code, now)


async def test_backfill_verify(fs: Any, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    from app.modules.engage import models as m
    from app.modules.engage import store_specs as ss

    act = synthetic(m.EngageActivity, deleted_at=None)
    gone = synthetic(m.EngageActivity)
    q = synthetic(
        m.EngageQuestion, activity_id=act["id"], options=[{"id": "a", "text": "A", "is_correct": True}]
    )
    run = synthetic(
        m.EngageRun, activity_id=act["id"], join_code="ABCDEFGH", run_no=1, revealed_positions=[0, 2]
    )
    p1 = synthetic(m.EngageParticipant, run_id=run["id"], seq=1)
    p2 = synthetic(m.EngageParticipant, run_id=run["id"], seq=2)
    r1 = synthetic(m.EngageResponse, run_id=run["id"], participant_id=p1["id"], answer={"option_ids": ["a"]})
    rows = {
        "engage_activities": [act, gone],
        "engage_questions": [q],
        "engage_runs": [run],
        "engage_participants": [p1, p2],
        "engage_responses": [r1],
    }

    async def seqs(session: Any, mapping: Any) -> list[dict[str, Any]]:  # the GROUP BY source
        return [{"id": run["id"], "value": 2}]

    from tests.learning import fs_harness

    real = fs_harness.fake_rows(rows)

    async def rows_fn(session: Any, mapping: Any) -> list[dict[str, Any]]:
        return await (seqs if "max(seq)" in mapping.table else real)(session, mapping)

    from app.core.firestore import backfill as bf

    monkeypatch.setattr(bf, "_rows", rows_fn)
    await bf.backfill(None, "engage", client=fs)  # type: ignore[arg-type]
    reports = await bf.verify(None, "engage", client=fs)  # type: ignore[arg-type]
    assert {r.collection for r in reports} == set(ss.COLLECTIONS)
    assert all(r.ok for r in reports), [r.as_dict() for r in reports if not r.ok]
    from app.modules.engage.repo_firestore import repo

    rp = repo()
    got = await rp.get_activity(act["id"])
    assert got is not None and got.title == act["title"] and got.deleted_at is None
    listed = await rp.list_activities(activity_type=None, title_like=None, limit=200)
    assert [a.id for a in listed] == [act["id"]]  # soft-deleted rows are excluded
    assert await rp.run_id_by_code("ABCDEFGH") == run["id"]
    p = await rp.participant(run["id"], p1["user_id"])
    assert p is not None and p.seq == 1 and p.id == p1["id"]


async def test_launch_closes_live_runs_and_numbers_runs(fs: Any) -> None:  # noqa: F811
    from app.modules.engage.repo_firestore import repo

    rp = repo()
    a = _activity()
    qs = [_question(a, 0), _question(a, 1)]
    await rp.create_activity(a, qs)
    assert [q.position for q in await rp.questions_of(a.id)] == [0, 1]
    r1 = await _launch(rp, a, qs)
    r2 = await _launch(rp, a, qs)
    assert (r1.run_no, r2.run_no) == (1, 2) and r1.join_code != r2.join_code
    runs = await rp.runs_of(a.id)
    assert [(r.run_no, r.status) for r in runs] == [(2, "scheduled"), (1, "closed")]
    assert runs[1].state_version == 2
    assert (await rp.latest_runs([a.id]))[a.id].run_no == 2
    assert (await rp.question_counts([a.id])) == {a.id: 2}


async def test_join_code_collision_retries(fs: Any) -> None:  # noqa: F811
    from app.modules.engage.repo_firestore import repo

    rp = repo()
    a = _activity()
    await rp.create_activity(a, [_question(a, 0)])
    seq = iter(["AAAAAAAA", "AAAAAAAA", "BBBBBBBB"])
    r1 = await _launch(rp, a, [_question(a, 0)], codes=lambda: "AAAAAAAA")
    r2 = await _launch(rp, a, [_question(a, 0)], codes=lambda: next(seq))
    assert (r1.join_code, r2.join_code) == ("AAAAAAAA", "BBBBBBBB")


async def test_concurrent_joins_get_distinct_seq_and_limit_holds(fs: Any) -> None:  # noqa: F811
    from app.modules.engage.repo_firestore import JoinRefused, repo

    rp = repo()
    a = _activity()
    r = await _launch(rp, a, [_question(a, 0)], limit=5)
    users = [uuid.uuid4() for _ in range(8)]

    async def one(u: uuid.UUID) -> Any:
        try:
            return (await rp.join(r.id, u, "nick", None))[0].seq
        except JoinRefused as e:
            return e.reason

    out = await asyncio.gather(*(one(u) for u in users))
    seqs = sorted(x for x in out if isinstance(x, int))
    assert seqs == [1, 2, 3, 4, 5]
    assert out.count("full") == 3
    again, created = await rp.join(r.id, users[out.index(1)], "nick", None)
    assert not created and again.seq == 1  # re-joining is idempotent
    assert await rp.participant_count(r.id) == 5


async def test_join_refused_when_closed(fs: Any) -> None:  # noqa: F811
    from app.modules.engage.repo_firestore import JoinRefused, repo

    rp = repo()
    a = _activity()
    r = await _launch(rp, a, [_question(a, 0)])

    def close(x: Any) -> None:
        x.status = "closed"

    await rp.mutate_run(r.id, close)
    with pytest.raises(JoinRefused) as e:
        await rp.join(r.id, uuid.uuid4(), None, None)
    assert e.value.reason == "closed"


async def test_one_answer_per_question_and_aggregation(fs: Any) -> None:  # noqa: F811
    from app.modules.engage import service_fs
    from app.modules.engage.models import EngageResponse
    from app.modules.engage.repo_firestore import repo

    rp = repo()
    a = _activity()
    q0 = _question(a, 0)
    r = await _launch(rp, a, [q0])
    ps = [(await rp.join(r.id, uuid.uuid4(), f"P{i}", None))[0] for i in range(3)]

    def resp(p: Any, opt: str) -> EngageResponse:
        return EngageResponse(
            id=uuid.uuid4(), run_id=r.id, participant_id=p.id, organization_id=None, user_id=p.user_id,
            question_id=q0.id, answer={"option_ids": [opt]}, terms=[], filtered=False, is_correct=opt == "a",
        )  # fmt: skip

    assert await rp.answer(ps[1].user_id, resp(ps[1], "a")) is not None
    assert await rp.answer(ps[0].user_id, resp(ps[0], "a")) is not None
    assert await rp.answer(ps[2].user_id, resp(ps[2], "b")) is not None
    assert await rp.answer(ps[0].user_id, resp(ps[0], "b")) is None  # already answered
    responses = await rp.responses(r.id)
    assert service_fs.counts_of(3, responses) == (3, 3, 3)
    agg = service_fs.aggregate(responses)
    assert agg["answered"] == {str(q0.id): 3}
    assert agg["choice"][str(q0.id)] == {"a": 2, "b": 1}
    run = await rp.get_run(r.id)
    assert run is not None
    run.opened_at = run.created_at
    ranked, winners, _ = service_fs.leaderboard(run, await rp.participants_map(r.id), responses)
    assert winners[str(q0.id)]["fastest"] == "P1"  # earliest correct answer wins
    assert [x["label"] for x in ranked] == ["P1", "P0"] and ranked[0]["wins"] == 1
    mine = await rp.my_responses(ps[0].user_id, ps[0].id)
    assert [x.answer for x in mine] == [{"option_ids": ["a"]}]
    assert [p.run_id for p in await rp.my_participations(ps[0].user_id)] == [r.id]


def test_word_and_rating_folds_match_sql_semantics() -> None:
    from app.modules.engage import service_fs
    from app.modules.engage.models import EngageResponse

    q = uuid.uuid4()

    def r(**kw: Any) -> EngageResponse:
        base = dict(id=uuid.uuid4(), participant_id=uuid.uuid4(), question_id=q, answer={}, terms=[], filtered=False,
                    is_correct=None, answered_at=T0)  # fmt: skip
        base.update(kw)
        return EngageResponse(**base)

    rows = [
        r(terms=["python", "java"]),
        r(terms=["python"]),
        r(terms=["rust"], filtered=True),  # filtered terms are not counted
        r(terms=["go"]),
        r(answer={"rating": 4}),
        r(answer={"rating": 4}),
        r(answer={"rating": 2}),
    ]
    agg = service_fs.aggregate(rows)
    assert agg["words"][str(q)] == [
        {"term": "python", "count": 2},
        {"term": "go", "count": 1},
        {"term": "java", "count": 1},
    ]
    assert agg["ratings"][str(q)] == {"4": 2, "2": 1}
    assert agg["answered"][str(q)] == 7


async def test_mutate_run_is_atomic_and_refresh_applies_timer(fs: Any) -> None:  # noqa: F811
    from app.core.errors import ProblemError
    from app.modules.engage.repo_firestore import repo

    rp = repo()
    a = _activity()
    r = await _launch(rp, a, [_question(a, 0)])

    def boom(x: Any) -> None:
        x.status = "open"
        raise ProblemError("invalid_state_transition")

    with pytest.raises(ProblemError):
        await rp.mutate_run(r.id, boom)
    assert (await rp.get_run(r.id)).status == "scheduled"  # type: ignore[union-attr]

    def expire(x: Any) -> None:
        x.closes_at = datetime.now(UTC) - timedelta(seconds=1)

    await rp.mutate_run(r.id, expire)
    cur = await rp.get_run(r.id)
    assert cur is not None and cur.status == "scheduled"
    cur = await rp.refresh_run(cur)
    assert cur.status == "closed" and cur.closed_at is not None


async def test_delete_activity_closes_runs_and_hides(fs: Any) -> None:  # noqa: F811
    from app.modules.engage.repo_firestore import repo

    rp = repo()
    a = _activity()
    await rp.create_activity(a, [_question(a, 0)])
    r = await _launch(rp, a, [_question(a, 0)])
    await rp.delete_activity(a.id, datetime.now(UTC))
    got = await rp.get_activity(a.id)
    assert got is not None and got.deleted_at is not None
    assert (await rp.get_run(r.id)).status == "closed"  # type: ignore[union-attr]
    assert await rp.list_activities(activity_type=None, title_like=None, limit=10) == []


async def test_list_filters_type_and_title_case_insensitively(fs: Any) -> None:  # noqa: F811
    from app.modules.engage.repo_firestore import repo

    rp = repo()
    a1 = _activity(title="Monday Quiz")
    a2 = _activity(title="Poll of the day", activity_type="poll", winner_rule=None)
    for a in (a1, a2):
        await rp.create_activity(a, [])
    assert [a.id for a in await rp.list_activities(activity_type="poll", title_like=None, limit=10)] == [
        a2.id
    ]
    assert [a.id for a in await rp.list_activities(activity_type=None, title_like="QUIZ", limit=10)] == [
        a1.id
    ]


async def test_erase_user(fs: Any) -> None:  # noqa: F811
    from app.modules.engage.models import EngageResponse
    from app.modules.engage.repo_firestore import repo

    rp = repo()
    a = _activity(activity_type="survey", winner_rule=None)
    q = _question(a, 0)
    r = await _launch(rp, a, [q])
    u = uuid.uuid4()
    p, _ = await rp.join(r.id, u, "Nick", None)
    await rp.answer(u, EngageResponse(
        id=uuid.uuid4(), run_id=r.id, participant_id=p.id, organization_id=None, user_id=u, question_id=q.id,
        answer={"text": "secret"}, terms=["secret"], filtered=False, is_correct=None,
    ))  # fmt: skip
    out = await rp.erase_user(u)
    assert out == {"participant_names_cleared": 1, "text_answers_erased": 1}
    assert (await rp.participant(r.id, u)).display_name is None  # type: ignore[union-attr]
    assert [x.answer for x in await rp.responses(r.id)] == [{"erased": True}]
    assert await rp.erase_user(u) == {"participant_names_cleared": 0, "text_answers_erased": 0}


def test_repository_scoped() -> None:
    from app.core.firestore.repository import assert_repository_scoped
    from app.modules.engage.repo_firestore import EngageRepo

    assert_repository_scoped(EngageRepo)


def test_word_ties_follow_postgres_en_us_collation() -> None:
    """``ORDER BY n DESC, t`` on Postgres uses the database collation (glibc en_US.utf8): mixed
    case, accents and punctuation do not sort by code point (known glibc orders, see
    tests/platform/test_collation.py)."""
    from app.modules.engage import service_fs
    from app.modules.engage.models import EngageResponse

    q = uuid.uuid4()
    terms = ["Resume", "résumé", "resume", "coop", "Co-op", "co-op", "co op", "B", "a", "A", "b"]
    rows = [
        EngageResponse(id=uuid.uuid4(), participant_id=uuid.uuid4(), question_id=q, answer={}, terms=[t],
                       filtered=False, is_correct=None, answered_at=T0)
        for t in terms
    ] + [
        EngageResponse(id=uuid.uuid4(), participant_id=uuid.uuid4(), question_id=q, answer={}, terms=["zz"],
                       filtered=False, is_correct=None, answered_at=T0)
        for _ in range(2)
    ]  # fmt: skip
    words = [w["term"] for w in service_fs.aggregate(rows)["words"][str(q)]]
    assert words[0] == "zz"  # the higher count first
    ties = words[1:]
    # glibc en_US.utf8: "a" < "A" < "b" < "B"; "co op" < "co-op" < "coop" < "Co-op";
    # "resume" < "Resume" < "résumé" (code point order would put every capital first)
    assert ties == ["a", "A", "b", "B", "co op", "co-op", "coop", "Co-op", "resume", "Resume", "résumé"]
