"""learning service / router helpers on Firestore (emulator only, no Postgres).

Run: ``TD_TEST_DB_NAME=learning_test .venv/Scripts/python.exe -m pytest --noconftest -p no:cacheprovider
-q tests/learning/test_fs_enrol.py``. Postgres-only collaborators (outbox, audit, catalog, identity)
are replaced by recorders; an unbound ``AsyncSession`` carries the fs_store unit of work."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest

from tests.learning.fs_harness import firestore_emulator, fs  # noqa: F401


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Firestore switch on + fakes for the Postgres collaborators of learning.service."""
    from app.core.firestore.backend import reset_store_backends
    from app.modules.learning import service as svc

    monkeypatch.setenv("TD_STORE_LEARNING", "firestore")
    reset_store_backends()
    events: list[tuple[str, dict[str, Any]]] = []
    audits: list[str] = []

    async def emit(session: Any, kind: str, payload: dict[str, Any], **kw: Any) -> None:
        events.append((kind, payload))

    async def aud(session: Any, actor: Any, action: str, *a: Any, **kw: Any) -> None:
        audits.append(action)

    monkeypatch.setattr(svc, "emit_event", emit)
    monkeypatch.setattr(svc, "audit", aud)
    # wiring.py registers Postgres-backed analytics/assessment lookups when the app is imported
    monkeypatch.setattr(svc, "_coverage_lookup", None)
    monkeypatch.setattr(svc, "_final_test_lookup", None, raising=False)
    world = SimpleNamespace(events=events, audits=audits, lessons=[], versions={})

    async def find_lessons(session: Any, **kw: Any) -> list[Any]:
        out = world.lessons
        if kw.get("version_id") is not None:
            out = [le for le in out if le.course_version_id == kw["version_id"]]
        if kw.get("lesson_key") is not None:
            out = [le for le in out if le.lesson_key == kw["lesson_key"]]
        for f in ("test_id", "coding_problem_id"):
            if kw.get(f) is not None:
                out = [le for le in out if getattr(le, f, None) == kw[f]]
        if kw.get("required_only"):
            out = [le for le in out if le.is_required]
        return out

    async def get_versions(session: Any, ids: Any) -> dict[Any, Any]:
        return {i: world.versions[i] for i in ids if i in world.versions}

    async def get_profile(session: Any, user_id: Any) -> Any:
        return SimpleNamespace(full_name="Asha Learner")

    monkeypatch.setattr(svc.catalog_api, "find_lessons", find_lessons)
    monkeypatch.setattr(svc.catalog_api, "get_versions", get_versions)
    from app.modules.identity import public as identity_public

    monkeypatch.setattr(identity_public, "get_profile", get_profile)
    yield world
    monkeypatch.delenv("TD_STORE_LEARNING", raising=False)
    reset_store_backends()


def _session() -> Any:
    from sqlalchemy.ext.asyncio import AsyncSession

    return AsyncSession()


def _course(version_id: uuid.UUID) -> Any:
    return SimpleNamespace(id=uuid.uuid4(), current_version_id=version_id, organization_id=None)


def _lesson(version_id: uuid.UUID, kind: str = "video", duration: int = 100) -> Any:
    return SimpleNamespace(
        id=uuid.uuid4(),
        lesson_key=uuid.uuid4(),
        course_version_id=version_id,
        duration_seconds=duration,
        lesson_type=kind,
        is_required=True,
        est_reading_minutes=1,
    )


async def test_enrol_progress_completion_and_certificate(fs: Any, env: Any) -> None:  # noqa: F811
    from app.core.errors import ProblemError
    from app.modules.learning import service as svc
    from app.modules.learning.models import Certificate, Enrolment

    v = uuid.uuid4()
    env.versions[v] = SimpleNamespace(
        id=v, title="Python 101", certificate_rule={"required_lessons_pct": 100}
    )
    lesson = _lesson(v)
    env.lessons.append(lesson)
    course = _course(v)
    user = uuid.uuid4()
    s = _session()
    enr = await svc.create_enrolment(s, user_id=user, course=course, source="free")
    assert enr.status == "active" and enr.progress_pct == Decimal("0")
    with pytest.raises(ProblemError) as e:
        await svc.create_enrolment(_session(), user_id=user, course=course, source="free")
    assert e.value.code == "invalid_state_transition"

    s2 = _session()
    got = await svc.get_enrolment(s2, user, course.id)
    assert got is not None and got.id == enr.id
    principal = SimpleNamespace(user_id=user)
    # implausible jump: position saved, nothing credited
    assert not await svc.record_video_heartbeat(
        s2, principal, lesson, course, prev_pos=0, new_pos=80, elapsed_s=5, playing=True, duration_s=None
    )
    for a, b in ((0, 30), (30, 60), (60, 92)):
        assert await svc.record_video_heartbeat(
            s2, principal, lesson, course, prev_pos=a, new_pos=b, elapsed_s=20, playing=True, duration_s=None
        )
    lp = await svc.get_progress(_session(), got, lesson.lesson_key, create=False)
    assert lp is not None, "none"
    assert (lp.watched_intervals, lp.status, lp.watched_seconds) == ([[0, 92]], "completed", 92)
    assert lp.progress_pct == Decimal("100.00")
    after = await svc.get_enrolment(_session(), user, course.id)
    assert after is not None and after.status == "completed" and after.progress_pct == Decimal("100.00")
    kinds = [k for k, _ in env.events]
    assert kinds == [
        "learning.enrolled",
        "learning.lesson_completed",
        "learning.course_completed",
        "learning.certificate_issued",
    ]
    from app.modules.learning import fs_enrol

    cert = await fs_enrol.certificate_of_enrolment(_session(), enr.id)
    assert cert is not None and cert.name_on_certificate == "Asha Learner" and cert.issue_source == "rule"
    assert (await fs_enrol.certificate_by_code(None, cert.public_code)).id == cert.id  # type: ignore[union-attr]
    with pytest.raises(ProblemError):  # one certificate per enrolment
        await svc.issue_certificate(_session(), after, source="manual")

    s3 = _session()
    revoked = await svc.revoke_certificates_for_courses(s3, principal, user, {course.id})  # type: ignore[arg-type]
    assert revoked == [cert.id] and env.audits == ["certificate.revoke"]
    c2 = await fs_enrol.certificate_of_enrolment(_session(), enr.id)
    assert c2 is not None and c2.revoked_at is not None and c2.revoke_reason == "refund"
    assert await svc.revoke_certificates_for_courses(_session(), principal, user, {course.id}) == []  # type: ignore[arg-type]
    assert isinstance(await svc.progress_map(_session(), enr.id), dict)
    assert Certificate and Enrolment


async def test_revoke_for_entitlement_and_self_enrol_reactivation(fs: Any, env: Any) -> None:  # noqa: F811
    from app.modules.learning import fs_store as fss
    from app.modules.learning import service as svc
    from app.modules.learning.models import Enrolment

    v = uuid.uuid4()
    env.versions[v] = SimpleNamespace(id=v, title="SQL", certificate_rule={"required_lessons_pct": 0})
    course = _course(v)
    ent = uuid.uuid4()
    user = uuid.uuid4()
    s = _session()
    enr = await svc.create_enrolment(s, user_id=user, course=course, source="entitlement", entitlement_id=ent)
    cert = await svc.issue_certificate(s, enr, source="manual")
    out = await svc.revoke_certificates_for_entitlement(_session(), SimpleNamespace(user_id=user), ent)  # type: ignore[arg-type]
    assert out == [cert.id]
    # withdrawn enrolments are reactivated in place
    s2 = _session()
    e = await fss.get(s2, Enrolment, enr.id)
    assert e is not None
    e.status = "withdrawn"
    await fss.flush(s2)
    assert (await svc.get_enrolment(_session(), user, course.id)).status == "withdrawn"  # type: ignore[union-attr]


async def test_article_completion_and_record_completion(fs: Any, env: Any) -> None:  # noqa: F811
    from app.core.errors import ProblemError
    from app.modules.learning import fs_store as fss
    from app.modules.learning import service as svc
    from app.modules.learning.models import LessonProgress

    v = uuid.uuid4()
    env.versions[v] = SimpleNamespace(id=v, title="Docs", certificate_rule=None)
    art = _lesson(v, kind="article")
    quiz = _lesson(v, kind="quiz")
    env.lessons += [art, quiz]
    course = _course(v)
    user = uuid.uuid4()
    s = _session()
    enr = await svc.create_enrolment(s, user_id=user, course=course, source="free")
    with pytest.raises(ProblemError):  # not opened yet
        await svc.record_article_completion(s, enr, art, {"scrolled_to_end": True})
    lp = await svc.mark_opened(s, enr, art)
    assert lp.status == "in_progress" and lp.first_opened_at is not None
    lp.first_opened_at = datetime.now(UTC) - timedelta(minutes=5)
    await fss.flush(s)
    done = await svc.record_article_completion(s, enr, art, {"scrolled_to_end": True})
    assert done.status == "completed"
    assert (await svc.get_enrolment(_session(), user, course.id)).progress_pct == Decimal("50.00")  # type: ignore[union-attr]
    assert await svc.record_completion(_session(), user, quiz.lesson_key, {"kind": "quiz_submitted"})
    assert not await svc.record_completion(
        _session(), uuid.uuid4(), quiz.lesson_key, {"kind": "quiz_submitted"}
    )
    e = await svc.get_enrolment(_session(), user, course.id)
    assert e is not None and e.status == "completed" and e.progress_pct == Decimal("100.00")
    rows = await fss.find(_session(), LessonProgress, filters=(("enrolment_id", "==", enr.id),))
    assert {r.status for r in rows} == {"completed"}


async def test_minor_publish_migrates_and_reopens(fs: Any, env: Any) -> None:  # noqa: F811
    from app.modules.learning import service as svc

    v1, v2 = uuid.uuid4(), uuid.uuid4()
    env.versions[v1] = SimpleNamespace(id=v1, title="C", certificate_rule=None)
    env.versions[v2] = SimpleNamespace(id=v2, title="C", certificate_rule=None)
    l1 = _lesson(v1, kind="quiz")
    l2 = SimpleNamespace(**{**vars(l1), "id": uuid.uuid4(), "course_version_id": v2})
    extra = _lesson(v2, kind="quiz")
    env.lessons += [l1, l2, extra]
    course = _course(v1)
    user = uuid.uuid4()
    enr = await svc.create_enrolment(_session(), user_id=user, course=course, source="free")
    await svc.record_completion(_session(), user, l1.lesson_key, {"kind": "quiz_submitted"})
    assert (await svc.get_enrolment(_session(), user, course.id)).status == "completed"  # type: ignore[union-attr]
    course.current_version_id = v2
    await svc.on_course_published(_session(), course, SimpleNamespace(id=v2, change_type="minor"))
    e = await svc.get_enrolment(_session(), user, course.id)
    assert e is not None and e.course_version_id == v2 and e.status == "active"
    assert e.progress_pct == Decimal("50.00") and e.completed_at is None
    assert enr.id == e.id


async def test_privacy_erasure(fs: Any, env: Any) -> None:  # noqa: F811
    from app.modules.learning import privacy
    from app.modules.learning import service as svc

    v = uuid.uuid4()
    env.versions[v] = SimpleNamespace(id=v, title="E", certificate_rule={"required_lessons_pct": 0})
    lesson = _lesson(v, kind="quiz")
    env.lessons.append(lesson)
    course = _course(v)
    user = uuid.uuid4()
    s = _session()
    enr = await svc.create_enrolment(s, user_id=user, course=course, source="free")
    await svc.get_progress(s, enr, lesson.lesson_key)
    await svc.issue_certificate(s, enr, source="manual")
    out = await privacy.erase_user(_session(), user)
    assert out == {
        "lesson_progress_deleted": 1,
        "submissions_scrubbed": 0,
        "certificates_revoked": 1,
        "enrolments_withdrawn": 1,
    }
    again = await privacy.erase_user(_session(), user)
    assert again == {
        "lesson_progress_deleted": 0,
        "submissions_scrubbed": 0,
        "certificates_revoked": 0,
        "enrolments_withdrawn": 0,
    }


async def test_router_queries(fs: Any, env: Any) -> None:  # noqa: F811
    from app.modules.learning import fs_enrol
    from app.modules.learning import fs_store as fss
    from app.modules.learning.models import Assignment, AssignmentAllocation, AssignmentSubmission, Enrolment

    user, batch, course = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    now = datetime.now(UTC)
    s = _session()
    e_old = Enrolment(id=uuid.uuid4(), user_id=user, course_id=uuid.uuid4(), course_version_id=uuid.uuid4(),
                      source="free", last_activity_at=now - timedelta(days=2), batch_id=batch)  # fmt: skip
    e_new = Enrolment(id=uuid.uuid4(), user_id=user, course_id=course, course_version_id=uuid.uuid4(),
                      source="free", last_activity_at=now, batch_id=batch)  # fmt: skip
    e_none = Enrolment(
        id=uuid.uuid4(), user_id=user, course_id=uuid.uuid4(), course_version_id=uuid.uuid4(), source="free"
    )
    fss.add_all(s, [e_old, e_new, e_none])

    def asg(**kw: Any) -> Assignment:
        base = dict(id=uuid.uuid4(), title="A", instructions_md="", submission_type="text", max_score=Decimal(10),
                    allowed_file_types=[], created_by=uuid.uuid4())  # fmt: skip
        base.update(kw)
        return Assignment(**base)

    a_batch = asg(batch_id=batch, due_at=now + timedelta(days=1))
    a_course = asg(course_id=course)
    a_other = asg(batch_id=uuid.uuid4())
    a_struct = asg(submission_type="structured")
    a_hidden = asg(submission_type="structured")
    fss.add_all(s, [a_batch, a_course, a_other, a_struct, a_hidden])
    fss.add(s, AssignmentAllocation(id=uuid.uuid4(), assignment_id=a_struct.id, organization_id=uuid.uuid4(),
                                    user_ids=[user], due_at=now, created_by=user, evaluator_ids=[uuid.UUID(int=7)]))  # fmt: skip
    fss.add(s, AssignmentAllocation(id=uuid.uuid4(), assignment_id=a_hidden.id, organization_id=uuid.uuid4(),
                                    batch_id=batch, due_at=now, created_by=user, visible_from=now + timedelta(days=3)))  # fmt: skip
    fss.add(
        s,
        AssignmentSubmission(
            id=uuid.uuid4(), assignment_id=a_batch.id, user_id=user, attempt_no=1, status="submitted"
        ),
    )
    await fss.flush(s)

    mine = await fs_enrol.my_enrolments(_session(), user)
    assert [e.id for e in mine] == [e_new.id, e_old.id, e_none.id]  # last_activity desc, nulls last
    elig = await fs_enrol.eligible_assignments(_session(), user, {batch}, {course}, now)
    assert {a.id for a in elig} == {a_batch.id, a_course.id, a_struct.id}
    assert next(a.id for a in fs_enrol.order_due_nulls_last(elig)) == a_batch.id
    assert await fs_enrol.pending_counts(_session(), [a_batch.id]) == {a_batch.id: 1}
    page = await fs_enrol.enrolment_page(_session(), batch_id=None, course_id=None, after=None, limit=1)
    assert len(page) == 2 and all(e.batch_id == batch for e in page)
    cands = await fs_enrol.staff_assignment_candidates(
        _session(), user_id=uuid.UUID(int=7), platform=False, batches=set(), courses=set(),
        batch_id=None, course_id=None, status=None,
    )  # fmt: skip
    assert [a.id for a in cands] == [a_struct.id]  # named evaluator
    counts = await fs_enrol.completed_lesson_counts(_session(), [e_new.id])
    assert counts == {}


def _msg(event_type: str, payload: dict[str, Any]) -> Any:
    from app.core.outbox import OutboxMessage

    return OutboxMessage(
        id=uuid.uuid4(),
        event_type=event_type,
        aggregate_type="x",
        aggregate_id=uuid.uuid4(),
        payload=payload,
        organization_id=None,
        occurred_at=datetime.now(UTC),
        attempt=1,
    )


async def test_quiz_practice_and_coding_lessons_complete_on_submission(fs: Any, env: Any) -> None:  # noqa: F811
    """Owner bug 2026-11-21: quiz, practice-set and coding lessons never completed (nothing called
    record_completion), so courses with them could never earn a certificate. The learning outbox
    handlers now complete them from ``attempt.submitted`` / ``submission.created``."""
    from app.modules.learning import service as svc
    from app.modules.learning import tasks

    v = uuid.uuid4()
    env.versions[v] = SimpleNamespace(id=v, title="Python", certificate_rule={"required_lessons_pct": 100})
    test_q, test_p, problem = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    quiz, practice, code = _lesson(v, kind="quiz"), _lesson(v, kind="practice_set"), _lesson(v, kind="coding")
    quiz.test_id, practice.test_id, code.coding_problem_id = test_q, test_p, problem
    env.lessons += [quiz, practice, code]
    course = _course(v)
    user, other = uuid.uuid4(), uuid.uuid4()
    enr = await svc.create_enrolment(_session(), user_id=user, course=course, source="free")

    async def status(lesson: Any) -> str | None:
        lp = await svc.get_progress(_session(), enr, lesson.lesson_key, create=False)
        return lp.status if lp is not None else None

    # someone else's submission completes nothing for this learner
    await tasks.on_attempt_submitted(_session(), _msg("attempt.submitted", {"test_id": str(test_q), "user_id": str(other)}))
    assert await status(quiz) is None
    await tasks.on_attempt_submitted(
        _session(), _msg("attempt.submitted", {"test_id": str(test_q), "user_id": str(user), "attempt_id": "a1"})
    )
    assert await status(quiz) == "completed"
    await tasks.on_attempt_submitted(_session(), _msg("attempt.submitted", {"test_id": str(test_p), "user_id": str(user)}))
    assert await status(practice) == "completed"
    # "Run" is not a submission; "Submit" completes the coding lesson (no verdict needed)
    run = {"problem_id": str(problem), "user_id": str(user), "mode": "run", "submission_id": "s0"}
    await tasks.on_code_submitted(_session(), _msg("submission.created", run))
    assert await status(code) is None
    await tasks.on_code_submitted(_session(), _msg("submission.created", {**run, "mode": "submit", "submission_id": "s1"}))
    assert await status(code) == "completed"
    after = await svc.get_enrolment(_session(), user, course.id)
    assert after is not None and after.status == "completed" and after.progress_pct == Decimal("100.00")
    assert "learning.certificate_issued" in [k for k, _ in env.events]
    lp = await svc.get_progress(_session(), enr, code.lesson_key, create=False)
    assert lp is not None and lp.evidence == {"kind": "coding_submitted", "submission_id": "s1"}
    # bad payloads are ignored, not raised (the relay would retry them forever)
    await tasks.on_attempt_submitted(_session(), _msg("attempt.submitted", {"test_id": "nope", "user_id": str(user)}))
    await tasks.on_code_submitted(_session(), _msg("submission.created", {"mode": "submit", "problem_id": "x"}))
