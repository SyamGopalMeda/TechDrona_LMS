"""Résumé builder (module ``mentoring``) on Firestore: data path + repository invariants
(emulator only, no Postgres). The mentoring sessions feature was removed
(docs/cleanup/feature-removal-plan.md §3.1).

Run: ``TD_TEST_DB_NAME=learning_test .venv/Scripts/python -m pytest --noconftest -p no:cacheprovider
tests/mentoring/test_fs_repo.py``. The HTTP flows on Firestore: ``fs/test_mentoring_http.py``."""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime
from typing import Any

import pytest

from tests.learning.fs_harness import backfill_rows, firestore_emulator, fs  # noqa: F401
from tests.learning.test_fs_data_path import synthetic


def _now() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


def _resume(u: uuid.UUID, **over: Any) -> Any:
    from app.modules.mentoring.models import Resume

    base = dict(id=uuid.uuid4(), user_id=u, template_key="ats_classic", version_no=1, content={},
                checklist_score=0, is_current=True, created_at=_now())  # fmt: skip
    base.update(over)
    return Resume(**base)


async def test_backfill_verify(fs: Any, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    from app.modules.mentoring import models as m
    from app.modules.mentoring import store_specs as ss
    from app.modules.mentoring.repo_firestore import repo

    res = synthetic(m.Resume, version_no=2, content={"headline": "x", "skills": ["a"]})
    reports = await backfill_rows(monkeypatch, "mentoring", {"resumes": [res]}, fs)
    by = {r.collection: r for r in reports}
    assert set(by) == set(ss.COLLECTIONS)
    assert all(r.ok for r in reports), [r.as_dict() for r in reports if not r.ok]
    assert by[ss.RESUME_VERSIONS].fs_docs == 1
    assert [x.id for x in await repo().resumes_of(res["user_id"])] == [res["id"]]


async def test_resume_versions_concurrent_and_current_flag(fs: Any) -> None:  # noqa: F811
    from app.modules.mentoring.repo_firestore import repo

    rp = repo()
    u = uuid.uuid4()

    def r() -> Any:
        return _resume(u, content={"headline": "h"}, checklist_score=10, pdf_s3_key=None, pdf_pending_key=None,
                       pdf_uploaded_at=None)  # fmt: skip

    made = await asyncio.gather(*(rp.new_version(u, r()) for _ in range(4)))
    assert sorted(x.version_no for x in made) == [1, 2, 3, 4]
    rows = await rp.resumes_of(u)
    assert [x.version_no for x in rows] == [4, 3, 2, 1]
    assert sum(1 for x in rows if x.is_current) == 1 and rows[0].is_current


async def test_erase_user(fs: Any) -> None:  # noqa: F811
    from app.modules.mentoring.repo_firestore import repo

    rp = repo()
    u = uuid.uuid4()
    await rp.new_version(u, _resume(u))
    await rp.new_version(u, _resume(u))
    assert await rp.erase_user(u) == {"resumes_deleted": 2}
    assert await rp.resumes_of(u) == []
    assert await rp.erase_user(u) == {"resumes_deleted": 0}
    # the version keys went with the résumés: numbering restarts at 1
    assert (await rp.new_version(u, _resume(u))).version_no == 1


def test_repository_scoped() -> None:
    from app.core.firestore.repository import assert_repository_scoped
    from app.modules.mentoring.repo_firestore import MentoringRepo

    assert_repository_scoped(MentoringRepo)
