"""Row-lock parity on Firestore (enrolments). Emulator only.

* ``lock_enrolment`` (advisory lock) + insert -> ``enrolment_keys``: concurrent self-enrolments
  give ONE enrolment, created once; the others get the winner (Postgres: they wait, then find it).
* ``on_course_published`` (``FOR UPDATE`` on the enrolments): concurrent publish hooks migrate an
  enrolment once (one ``learning.version_migrated``) and its progress is recomputed atomically.
"""

from __future__ import annotations

import asyncio
import uuid
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest

from tests.learning.fs_harness import firestore_emulator, fs  # noqa: F401
from tests.learning.test_fs_enrol import _course, _lesson, _session, env  # noqa: F401


async def test_concurrent_self_enrol_one_enrolment(
    fs: Any,  # noqa: F811
    env: Any,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.modules.learning import fs_store as fss
    from app.modules.learning import service as svc
    from app.modules.learning.models import Enrolment

    v = uuid.uuid4()
    env.versions[v] = SimpleNamespace(id=v, title="Py", certificate_rule=None)
    course = _course(v)
    course.is_free = True
    user = uuid.uuid4()

    async def access(*a: Any, **k: Any) -> Any:
        await asyncio.sleep(0.05)  # widen the race window
        return SimpleNamespace(expires_at=None, reason="free", allowed=True)

    monkeypatch.setattr(svc, "course_enrollable", lambda c, p: True)
    monkeypatch.setattr(svc, "require_access", access)
    monkeypatch.setattr(svc, "_source_for", lambda c, d: ("free", None))
    principal = SimpleNamespace(user_id=user)
    out = await asyncio.gather(*(svc.self_enrol(_session(), principal, course) for _ in range(4)))
    assert len({e.id for e, _ in out}) == 1
    assert sum(1 for _, created in out if created) == 1  # 201 once, 200 for the others
    rows = await fss.find(_session(), Enrolment, filters=(("user_id", "==", user),))
    assert len(rows) == 1
    assert sum(1 for k, _ in env.events if k == "learning.enrolled") == 1


async def test_concurrent_publish_migrates_once(fs: Any, env: Any) -> None:  # noqa: F811
    from app.modules.learning import service as svc

    v1, v2 = uuid.uuid4(), uuid.uuid4()
    env.versions[v1] = SimpleNamespace(id=v1, title="C", certificate_rule=None)
    env.versions[v2] = SimpleNamespace(id=v2, title="C", certificate_rule=None)
    l1 = _lesson(v1, kind="quiz")
    l2 = SimpleNamespace(**{**vars(l1), "id": uuid.uuid4(), "course_version_id": v2})
    extra = _lesson(v2, kind="quiz")
    env.lessons += [l1, l2, extra]
    course = _course(v1)
    users = [uuid.uuid4() for _ in range(3)]
    for u in users:
        await svc.create_enrolment(_session(), user_id=u, course=course, source="free")
        await svc.record_completion(_session(), u, l1.lesson_key, {"kind": "quiz_submitted"})
    course.current_version_id = v2
    version = SimpleNamespace(id=v2, change_type="minor")
    await asyncio.gather(*(svc.on_course_published(_session(), course, version) for _ in range(3)))
    migrated = [p for k, p in env.events if k == "learning.version_migrated"]
    assert sorted(p["user_id"] for p in migrated) == sorted(str(u) for u in users)  # once per enrolment
    for u in users:
        e = await svc.get_enrolment(_session(), u, course.id)
        assert e is not None and e.course_version_id == v2 and e.status == "active"
        assert e.progress_pct == Decimal("50.00") and e.completed_at is None
