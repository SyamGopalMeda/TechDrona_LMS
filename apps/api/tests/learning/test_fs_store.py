"""learning ``fs_store`` unit of work on the emulator (no Postgres: an unbound AsyncSession only
carries ``session.info``; its own flush has nothing to do)."""

from __future__ import annotations

import uuid
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


def _enrolment(user: uuid.UUID, course: uuid.UUID) -> Any:
    from app.modules.learning.models import Enrolment

    return Enrolment(
        id=uuid.uuid4(), user_id=user, course_id=course, course_version_id=uuid.uuid4(), source="self"
    )


async def test_create_defaults_keys_update_delete(fs: Any, fs_on: Any) -> None:  # noqa: F811
    from app.core.errors import ProblemError
    from app.modules.learning import fs_store as fss
    from app.modules.learning import store_specs as ss
    from app.modules.learning.models import Enrolment

    s = _session()
    u, c = uuid.uuid4(), uuid.uuid4()
    e = _enrolment(u, c)
    fss.add(s, e)
    await fss.flush(s)
    assert e.status == "active" and e.progress_pct == Decimal("0") and e.enrolled_at is not None
    assert e.created_at is not None and e.updated_at is not None
    assert await fss.key_target(ss.ENROLMENT_KEYS, ss.enrolment_key(u, c)) == str(e.id)

    s2 = _session()
    fss.add(s2, _enrolment(u, c))
    with pytest.raises(ProblemError) as err:
        await fss.flush(s2)
    assert err.value.code == "conflict" and "already enrolled" in (err.value.detail or "")

    s3 = _session()
    got = await fss.get(s3, Enrolment, e.id)
    assert got is not None and got.progress_pct == Decimal("0")
    got.progress_pct = Decimal("42.50")
    got.status = "completed"
    await fss.flush(s3)
    again = await fss.get(_session(), Enrolment, e.id)
    assert again is not None and again.progress_pct == Decimal("42.50") and again.status == "completed"
    rows = await fss.find(_session(), Enrolment, filters=(("user_id", "==", u),))
    assert [r.id for r in rows] == [e.id]

    s4 = _session()
    victim = await fss.get(s4, Enrolment, e.id)
    await fss.delete(s4, victim)
    await fss.flush(s4)
    assert await fss.get(_session(), Enrolment, e.id) is None
    assert await fss.key_target(ss.ENROLMENT_KEYS, ss.enrolment_key(u, c)) is None


async def test_partial_unique_key_moves_with_status(fs: Any, fs_on: Any) -> None:  # noqa: F811
    from app.core.errors import ProblemError
    from app.modules.learning import fs_store as fss
    from app.modules.learning import store_specs as ss
    from app.modules.learning.models import AssignmentRegradeRequest

    sub = uuid.uuid4()

    def rr() -> AssignmentRegradeRequest:
        return AssignmentRegradeRequest(
            id=uuid.uuid4(), submission_id=sub, assignment_id=uuid.uuid4(), user_id=uuid.uuid4(), reason="r"
        )

    s = _session()
    first = rr()
    fss.add(s, first)
    await fss.flush(s)
    assert first.status == "open"
    s2 = _session()
    fss.add(s2, rr())
    with pytest.raises(ProblemError):  # one open request per submission
        await fss.flush(s2)
    s3 = _session()
    cur = await fss.get(s3, AssignmentRegradeRequest, first.id)
    assert cur is not None
    cur.status = "resolved"
    await fss.flush(s3)
    assert await fss.key_target(ss.REGRADE_OPEN, str(sub)) is None
    s4 = _session()
    fss.add(s4, rr())  # a new open request is allowed now
    await fss.flush(s4)


async def test_identity_map_and_progress_composite_id(fs: Any, fs_on: Any) -> None:  # noqa: F811
    from app.modules.learning import fs_store as fss
    from app.modules.learning import store_specs as ss
    from app.modules.learning.models import LessonProgress

    s = _session()
    enr, key = uuid.uuid4(), uuid.uuid4()
    lp = LessonProgress(enrolment_id=enr, lesson_key=key, user_id=uuid.uuid4(), watched_intervals=[[0, 10]])
    fss.add(s, lp)
    await fss.flush(s)
    assert lp.status == "not_started" and lp.watched_seconds == 0
    s2 = _session()
    a = await fss.get(s2, LessonProgress, ss.progress_id(enr, key))
    b = (await fss.find(s2, LessonProgress, filters=(("enrolment_id", "==", enr),)))[0]
    assert a is b and a.watched_intervals == [[0, 10]]
    a.watched_intervals = [[0, 10], [20, 30]]
    await fss.flush(s2)
    c = await fss.get(_session(), LessonProgress, ss.progress_id(enr, key))
    assert c is not None and c.watched_intervals == [[0, 10], [20, 30]]
