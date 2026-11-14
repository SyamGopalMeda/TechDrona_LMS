"""Catalog Firestore repository (Firebase P2b, ``TD_STORE_CATALOG=firestore``): transaction
invariants (one editable version, supersede, card), case-insensitive slug uniqueness under
concurrency, outline consistency, TN visibility, chunked draft clone, repository scope lint and
backfill -> edit -> verify drift detection. The API-level behaviour on both stores is covered by
the ``catalog_backend`` matrix on the existing catalog / learning / media / paths tests."""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

import pytest

from app.core.errors import ProblemError
from app.core.firestore.repository import assert_repository_scoped
from app.core.firestore.store import ScopedStore
from app.modules.catalog import repo_firestore as rf
from app.modules.catalog import service as cat
from app.modules.catalog.store_specs import COURSES, COURSES_BY_SLUG, LESSONS, VERSIONS, slug_id
from tests.catalog.factory import idem, make_published_course, staff
from tests.firestore.matrix import activate_firestore


@pytest.fixture
async def fs(request: pytest.FixtureRequest, db: Any, monkeypatch: pytest.MonkeyPatch) -> Any:
    restore = await activate_firestore(request, db, monkeypatch, ("catalog",))
    try:
        yield
    finally:
        await restore()


def _store() -> ScopedStore:
    return ScopedStore.system("test.catalog")


def _system_writer() -> rf.CatalogWriteRepo:
    return rf.CatalogWriteRepo(ScopedStore.system(rf.WRITE_JOB), rf.SYSTEM_VIEW)


async def _versions(course_id: Any) -> list[dict[str, Any]]:
    page = await _store().query(VERSIONS, filters=[("course_id", "==", str(course_id))], order_by=())
    return sorted((d.data for d in page.items), key=lambda v: v["version_no"])


async def _published_via_api(db: Any, browser: Any, slug: str) -> tuple[str, Any]:
    await staff(db, browser, "content_manager")
    r = await browser.post(
        "/studio/courses", {"title": "FS course", "slug": slug, "is_free": True, "visibility": "public"}
    )
    assert r.status_code == 201, r.text
    cid = r.json()["id"]
    for t in ("One", "Two"):
        r = await browser.post(
            f"/studio/courses/{cid}/draft/lessons",
            {"title": t, "lesson_type": "article", "article_body": {"d": t}, "duration_seconds": 60},
        )
        assert r.status_code == 201, r.text
    assert (await browser.post(f"/studio/courses/{cid}/submit-review")).status_code == 200
    publisher = browser.fork()
    await staff(db, publisher, "content_manager")
    r = await publisher.post(f"/studio/courses/{cid}/publish", {"change_type": "major"}, headers=idem())
    assert r.status_code == 200, r.text
    return cid, publisher


def test_repositories_pass_the_scope_lint() -> None:
    assert_repository_scoped(rf.CatalogReadRepo)
    assert_repository_scoped(rf.CatalogWriteRepo)


async def test_publish_invariants_one_editable_version_supersede_and_card(browser, db, fs) -> None:
    cid, publisher = await _published_via_api(db, browser, "fs-publish")
    c = await _store().get(COURSES, cid)
    assert c is not None and c["status"] == "published" and c["draft_version_id"] is None
    assert c["card"]["lesson_count"] == 2 and c["card"]["duration_seconds"] == 120
    assert c["published_at"] is not None and c["last_version_no"] == 1
    # Two concurrent first edits of the published course clone exactly one draft (v2).
    author = uuid.uuid4()
    await asyncio.gather(
        _system_writer().patch_draft(author, uuid.UUID(cid), {"title": "FS course 2"}),
        _system_writer().patch_draft(author, uuid.UUID(cid), {"summary": "Edited"}),
    )
    vs = await _versions(cid)
    assert [(v["version_no"], v["status"]) for v in vs] == [(1, "published"), (2, "draft")]
    v2 = vs[1]
    assert v2["title"] == "FS course 2" and v2["summary"] == "Edited"
    c = await _store().get(COURSES, cid)
    assert c is not None and c["draft_version_id"] == v2["id"] and c["last_version_no"] == 2
    # the clone kept lesson keys and copied the lessons (new ids, same outline)
    keys = {le["lesson_key"] for m in vs[0]["outline"] for le in m["lessons"]}
    assert {le["lesson_key"] for m in v2["outline"] for le in m["lessons"]} == keys
    assert v2["lesson_count"] == 2 and v2["duration_seconds"] == 120
    # a published version is immutable
    old_lesson = vs[0]["outline"][0]["lessons"][0]["id"]
    r = await browser.patch(f"/studio/lessons/{old_lesson}", {"title": "nope"})
    assert r.status_code == 409 and r.json()["code"] == "invalid_state_transition"
    # publish v2 -> v1 superseded, card rebuilt, pointer cleared, publish hooks ran (no error)
    assert (await browser.post(f"/studio/courses/{cid}/submit-review")).status_code == 200
    r = await publisher.post(f"/studio/courses/{cid}/publish", {"change_type": "minor"}, headers=idem())
    assert r.status_code == 200, r.text
    assert r.json()["course"]["current_version_id"] == v2["id"]
    vs = await _versions(cid)
    assert [(v["version_no"], v["status"]) for v in vs] == [(1, "superseded"), (2, "published")]
    c = await _store().get(COURSES, cid)
    assert c is not None and c["current_version_id"] == v2["id"] and c["draft_version_id"] is None
    assert c["title"] == "FS course 2" and c["card"]["title"] == "FS course 2"
    assert c["card"]["summary"] == "Edited" and c["published_at"] >= vs[0]["published_at"]
    listed = (await browser.fork().get("/catalog/courses")).json()["data"]
    assert next(x for x in listed if x["id"] == cid)["title"] == "FS course 2"


async def test_slug_unique_case_insensitive_concurrent_and_released_on_rename(browser, db, fs) -> None:
    w = _system_writer()
    user = uuid.uuid4()

    async def create(slug: str) -> Any:
        return await w.create_course(
            user,
            organization_id=None,
            slug=slug,
            title="Slug race",
            course_kind="self_paced",
            visibility="public",
            is_free=True,
            summary=None,
            certificate_rule={"required_lessons_pct": 100},
        )

    results = await asyncio.gather(create("race-slug"), create("RACE-slug"), return_exceptions=True)
    ok = [r for r in results if not isinstance(r, BaseException)]
    bad = [r for r in results if isinstance(r, BaseException)]
    assert len(ok) == 1 and len(bad) == 1, results
    assert isinstance(bad[0], ProblemError) and bad[0].status == 409
    course, _ = ok[0]
    idx = await _store().get(COURSES_BY_SLUG, slug_id(None, "Race-Slug"))
    assert idx is not None and idx["course_id"] == str(course.id)
    # rename releases the old key in the same transaction; the old slug is free again
    await w.patch_draft(user, course.id, {"slug": "race-renamed"})
    assert await _store().get(COURSES_BY_SLUG, slug_id(None, "race-slug")) is None
    assert (await _store().get(COURSES_BY_SLUG, slug_id(None, "race-renamed")))["course_id"] == str(course.id)  # type: ignore[index]
    other, _ = await create("race-slug")
    assert other.id != course.id
    with pytest.raises(ProblemError) as e:
        await w.patch_draft(user, other.id, {"slug": "RACE-RENAMED"})
    assert e.value.status == 409


async def test_outline_replace_keeps_embedded_outline_consistent(browser, db, fs) -> None:
    await staff(db, browser, "content_manager")
    r = await browser.post("/studio/courses", {"title": "Outline FS", "slug": "outline-fs"})
    cid = r.json()["id"]
    ids = []
    for i, t in enumerate(("A", "B", "C")):
        r = await browser.post(
            f"/studio/courses/{cid}/draft/lessons",
            {"title": t, "lesson_type": "article", "duration_seconds": 10 * (i + 1)},
        )
        assert r.status_code == 201, r.text
        ids.append(r.json()["id"])
    r = await browser.post(
        "/studio/resources",
        {
            "title": "Sheet",
            "resource_type": "link",
            "course_id": cid,
            "lesson_id": ids[2],
            "url": "https://example.com/x",
        },
    )
    assert r.status_code == 201, r.text
    rid = r.json()["id"]
    r = await browser.request(
        "PUT",
        f"/studio/courses/{cid}/draft/outline",
        json={"modules": [{"title": "M2", "lesson_ids": [ids[1]]}, {"title": "M1", "lesson_ids": [ids[0]]}]},
    )
    assert r.status_code == 200, r.text
    v = (await _versions(cid))[0]
    assert [m["title"] for m in v["outline"]] == ["M2", "M1"]
    assert [[le["id"] for le in m["lessons"]] for m in v["outline"]] == [[ids[1]], [ids[0]]]
    assert v["lesson_count"] == 2 and v["duration_seconds"] == 30
    assert [[le["id"] for le in m["lessons"]] for m in r.json()["modules"]] == [[ids[1]], [ids[0]]]
    assert await _store().get(LESSONS, ids[2]) is None  # removed lesson deleted
    res = await _store().get("resources", rid)
    assert res is not None and res["lesson_id"] is None  # ON DELETE SET NULL
    # lesson edits refresh the embedded summary
    r = await browser.patch(f"/studio/lessons/{ids[0]}", {"title": "A2", "duration_seconds": 100})
    assert r.status_code == 200, r.text
    v = (await _versions(cid))[0]
    assert v["outline"][1]["lessons"][0]["title"] == "A2" and v["duration_seconds"] == 120


async def test_tn_visibility_follows_the_session_context(browser, db, fs) -> None:
    from app.core.company import COMPANY_ORG_ID
    from app.core.db import tenant_context
    from app.core.ids import uuid7
    from app.core.principal import Principal

    company, _ = await _system_writer().create_course(
        uuid.uuid4(),
        organization_id=COMPANY_ORG_ID,
        slug="tn-company",
        title="Company only",
        course_kind="self_paced",
        visibility="private",
        is_free=False,
        summary=None,
        certificate_rule={},
    )
    platform, _ = await _system_writer().create_course(
        uuid.uuid4(),
        organization_id=None,
        slug="tn-platform",
        title="Platform",
        course_kind="self_paced",
        visibility="public",
        is_free=True,
        summary=None,
        certificate_rule={},
    )
    anon = await rf.reader(None)
    assert set(await anon.courses([company.id, platform.id])) == {platform.id}
    await tenant_context(db, Principal(user_id=uuid7(), session_id=uuid7()))
    assert set(await (await rf.reader(db)).courses([company.id, platform.id])) == {platform.id}
    with pytest.raises(ProblemError):
        await cat.get_course(db, company.id)
    await tenant_context(db, Principal(user_id=uuid7(), session_id=uuid7(), org_ids=(COMPANY_ORG_ID,)))
    assert (await cat.get_course(db, company.id)).organization_id == COMPANY_ORG_ID
    # TN WITH CHECK: an outsider cannot write the company row, a member can
    outsider = rf.CatalogWriteRepo(ScopedStore.system(rf.WRITE_JOB), rf.Visibility())
    with pytest.raises(ProblemError):
        await outsider.archive(uuid.uuid4(), company.id)
    member = rf.CatalogWriteRepo(
        ScopedStore.system(rf.WRITE_JOB), rf.Visibility(frozenset({str(COMPANY_ORG_ID)}))
    )
    course, before = await member.archive(uuid.uuid4(), company.id)
    assert (before, course.status) == ("draft", "archived")


async def test_large_outline_clone_is_chunked(browser, db, fs, monkeypatch) -> None:
    from tests.identity.factory import make_user

    author = (await make_user(db)).id
    extra = [{"name": f"x{i}", "lesson_type": "article", "est_reading_minutes": 1} for i in range(6)]
    pc = await make_published_course(db, author, extra_lessons=extra)
    from tests.catalog.factory import sync_catalog

    await sync_catalog(db)
    monkeypatch.setattr(rf, "CLONE_TX_LIMIT", 3)  # 8 lessons + 1 asset > 3 writes
    course, draft, _ = await _system_writer().patch_draft(uuid.uuid4(), pc.course_id, {"title": "Chunked"})
    vs = await _versions(pc.course_id)
    assert [(v["version_no"], v["status"]) for v in vs] == [(1, "published"), (2, "draft")]
    assert vs[1]["lesson_count"] == 8 and vs[1]["title"] == "Chunked"
    out = await cat.version_out(db, draft)
    assert sum(len(m["lessons"]) for m in out["modules"]) == 8
    video = next(le for m in out["modules"] for le in m["lessons"] if le["lesson_type"] == "video")
    assert len(video["assets"]) == 1 and video["assets"][0]["status"] == "ready"
    assert course.id == pc.course_id


async def test_backfill_then_edit_via_api_shows_up_in_verify(browser, db, fs) -> None:
    from app.core.firestore.backfill import verify

    cm = await staff(db, browser, "content_manager")
    pc = await make_published_course(db, cm.id)
    assert all(r.ok for r in await verify(db, "catalog"))
    r = await browser.patch(f"/studio/courses/{pc.course_id}/draft", {"title": "Edited on Firestore"})
    assert r.status_code == 200 and r.json()["version_no"] == 2
    reports = {r.collection: r for r in await verify(db, "catalog")}
    assert str(pc.course_id) in reports["courses"].mismatched  # draft pointer + last_version_no
    assert r.json()["id"] in reports["course_versions"].extra  # the draft lives in Firestore only
    assert reports["courses_by_slug"].ok and reports["resources"].ok


def test_composite_indexes_for_p2b_catalog_queries_are_declared() -> None:
    """The emulator does not enforce indexes; production does (keyset scans by ``id`` desc)."""
    import json
    from pathlib import Path

    spec = json.loads((Path(__file__).resolve().parents[4] / "firestore.indexes.json").read_text())
    declared = {
        (i["collectionGroup"].removeprefix("lms_"), tuple(f["fieldPath"] for f in i["fields"]))
        for i in spec["indexes"]
    }
    for want in (
        ("courses", ("status", "visibility", "organization_id", "id")),  # public list
        ("resources", ("access_level", "organization_id", "id")),  # free resources
        ("resources", ("course_id", "id")),  # studio resources of a course / lesson
        ("resources", ("company_id", "id")),  # studio resources of a company hub
    ):
        assert want in declared, want
