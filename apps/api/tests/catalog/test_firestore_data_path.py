"""Catalog Firestore data path (P2, docs/firebase/p2.md): the demo catalogue backfills into the
emulator, verifies (counts + per-document SHA-256 + summed checksum), and the assembled read
model (course card, embedded outline, lesson topics, slug index) equals what the Postgres
service returns today."""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from app.core.firestore.backfill import backfill, verify
from app.modules.catalog import service as cat
from app.seeds import catalog_demo, dev_users
from tests.firestore.matrix import activate_firestore


@pytest.fixture
async def fs(request: pytest.FixtureRequest, db: Any, monkeypatch: pytest.MonkeyPatch) -> Any:
    restore = await activate_firestore(request, db, monkeypatch, ())  # switch stays postgres
    try:
        yield
    finally:
        await restore()


async def test_demo_catalogue_backfills_verifies_and_matches_the_service(db: Any, fs: None) -> None:
    from app.core.db import system_context
    from app.core.firestore.store import ScopedStore
    from app.modules.catalog.store_specs import slug_id

    await dev_users.seed(db)
    assert await catalog_demo.seed(db) == ["demo-dsa-free", "demo-aptitude-paid"]
    written = await backfill(db, "catalog")
    assert written["courses"] >= 2 and written["lessons"] > 0
    reports = await verify(db, "catalog")
    assert {r.collection for r in reports} == {
        "courses",
        "courses_by_slug",
        "course_versions",
        "lessons",
        "lesson_assets",
        "resources",
    }
    assert all(r.ok for r in reports), [r.as_dict() for r in reports if not r.ok]

    store = ScopedStore.system("test.catalog")
    await system_context(db, "test.catalog")
    course, version = await cat.public_course_by_slug(db, "demo-dsa-free")
    idx = await store.get("courses_by_slug", slug_id(None, "DEMO-DSA-free"))  # case-insensitive
    assert idx is not None and idx["course_id"] == str(course.id)

    doc = await store.get("courses", str(course.id))
    assert doc is not None
    counts = (await cat.published_lesson_counts(db, [version.id])).get(version.id)
    card = cat.public_card(course, version, counts)
    fs_card = doc["card"]
    assert (fs_card["lesson_count"], fs_card["duration_seconds"]) == (
        card["lesson_count"],
        card["duration_seconds"],
    )
    assert (fs_card["title"], fs_card["category"], fs_card["tags"]) == (
        card["title"],
        card["category"],
        card["tags"],
    )
    assert doc["status"] == "published" and doc["current_version_id"] == str(version.id)

    v = await store.get("course_versions", str(version.id))
    assert v is not None
    pg_outline = (await cat.version_out(db, version, full=False))["modules"]
    fs_outline = [
        {
            "id": m["id"],
            "module_key": m["module_key"],
            "title": m["title"],
            "position": m["position"],
            "lessons": [{k: le[k] for k in pg_outline[0]["lessons"][0]} for le in m["lessons"]],
        }
        for m in v["outline"]
    ]
    assert fs_outline == pg_outline  # same order (position) and same lesson summaries
    assert v["lesson_count"] == card["lesson_count"]

    first = pg_outline[0]["lessons"][0]
    le = await store.get("lessons", first["id"])
    assert le is not None and le["course_id"] == str(course.id) and le["lesson_key"] == first["lesson_key"]
    assert uuid.UUID(le["course_version_id"]) == version.id


async def test_backfill_is_idempotent_and_replace_reseeds(db: Any, fs: None) -> None:
    await dev_users.seed(db)
    await catalog_demo.seed(db)
    a = await backfill(db, "catalog")
    b = await backfill(db, "catalog")
    assert a == b
    c = await backfill(db, "catalog", replace=True)
    assert c == a and all(r.ok for r in await verify(db, "catalog"))
