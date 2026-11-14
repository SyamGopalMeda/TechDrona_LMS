"""DEV / DEMO DATA ONLY — a small synthetic catalogue for local development and demos.
Never run against production: the script refuses when ``APP_ENV`` is ``prod``/``production``.
Video assets point at fake VdoCipher ids (``demo-fake-*``) that only the FakeVideoProvider
(``VDOCIPHER_MODE=stub``) can "play"; no media binaries are created.

Run after ``alembic upgrade heads`` and ``python -m app.seeds.dev_users``:
``python -m app.seeds.catalog_demo``

Creates (idempotent by slug, platform catalogue, authored by content@dev.techdrona.local):

* ``demo-dsa-free``      free, public — article + video lesson, certificate on 100 %
* ``demo-aptitude-paid`` paid, public — free-preview video + article (needs an entitlement)
"""

from __future__ import annotations

import asyncio
import sys
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import get_settings
from app.core.db import make_engine, system_context
from app.core.ids import uuid7
from app.core.models_registry import import_all_models
from app.core.time import utcnow
from app.modules.catalog.models import Course, CourseModule, CourseVersion, Lesson, LessonAsset
from app.modules.identity.models import User
from app.seeds import seeds_allowed
from app.seeds.sync import sync_touched

# Seeds run standalone: register every module's tables so cross-module FKs resolve.
import_all_models()

AUTHOR_EMAIL = "content@dev.techdrona.local"
PUBLISHER_EMAIL = "admin@dev.techdrona.local"

COURSES: list[dict[str, Any]] = [
    {
        "slug": "demo-dsa-free",
        "title": "[DEMO] DSA Warm-up",
        "summary": "Synthetic demo course: arrays and complexity.",
        "is_free": True,
        "category": "dsa",
        "lessons": [
            {
                "title": "Why Big-O matters",
                "lesson_type": "article",
                "est_reading_minutes": 3,
                "article_body": {"type": "doc", "content": [{"type": "paragraph", "text": "Demo content."}]},
            },
            {"title": "Arrays in 10 minutes", "lesson_type": "video", "duration_seconds": 600},
        ],
    },
    {
        "slug": "demo-aptitude-paid",
        "title": "[DEMO] Quantitative Aptitude",
        "summary": "Synthetic demo paid course with a free preview.",
        "is_free": False,
        "category": "aptitude",
        "lessons": [
            {
                "title": "Ratios preview",
                "lesson_type": "video",
                "duration_seconds": 300,
                "is_free_preview": True,
            },
            {
                "title": "Percentages",
                "lesson_type": "article",
                "est_reading_minutes": 5,
                "article_body": {"type": "doc", "content": [{"type": "paragraph", "text": "Demo content."}]},
            },
        ],
    },
]


class ProductionRefused(RuntimeError):
    pass


def guard() -> None:
    if not seeds_allowed():
        raise ProductionRefused("catalog_demo seed refuses to run outside APP_ENV local/dev/test")


async def _user_id(session: AsyncSession, email: str) -> uuid.UUID:
    uid = (await session.execute(select(User.id).where(User.email == email))).scalar_one_or_none()
    if uid is None:
        raise RuntimeError(f"{email} not found: run `python -m app.seeds.dev_users` first")
    return uid


async def seed(session: AsyncSession) -> list[str]:
    guard()
    await system_context(session, "seed.catalog_demo")
    author = await _user_id(session, AUTHOR_EMAIL)
    publisher = await _user_id(session, PUBLISHER_EMAIL)
    made: list[str] = []
    for spec in COURSES:
        exists = (
            await session.execute(
                select(Course.id).where(Course.slug == spec["slug"], Course.organization_id.is_(None))
            )
        ).first()
        if exists:
            continue
        cid, vid, mid = uuid7(), uuid7(), uuid7()
        session.add(
            Course(
                id=cid,
                slug=spec["slug"],
                title=spec["title"],
                visibility="public",
                status="published",
                is_free=spec["is_free"],
                created_by=author,
            )
        )
        await session.flush()
        session.add(
            CourseVersion(
                id=vid,
                course_id=cid,
                version_no=1,
                title=spec["title"],
                summary=spec["summary"],
                category=spec["category"],
                level="beginner",
                tags=["demo"],
                status="published",
                change_type="major",
                published_at=utcnow(),
                published_by=publisher,
                created_by=author,
                certificate_rule={"required_lessons_pct": 100},
            )
        )
        await session.flush()
        session.add(
            CourseModule(id=mid, course_version_id=vid, module_key=uuid7(), title="Module 1", position=0)
        )
        await session.flush()
        for pos, ls in enumerate(spec["lessons"]):
            lid = uuid7()
            session.add(
                Lesson(
                    id=lid,
                    course_module_id=mid,
                    course_version_id=vid,
                    lesson_key=uuid7(),
                    position=pos,
                    **ls,
                )
            )
            await session.flush()
            if ls["lesson_type"] == "video":
                session.add(
                    LessonAsset(
                        id=uuid7(),
                        lesson_id=lid,
                        asset_type="video",
                        provider="vdocipher",
                        provider_asset_id=f"demo-fake-{lid.hex[:16]}",
                        status="available",
                        scan_status="not_required",
                        duration_seconds=ls["duration_seconds"],
                    )
                )
        await session.flush()
        course = await session.get(Course, cid)
        assert course is not None
        course.current_version_id = vid
        await session.flush()
        made.append(spec["slug"])
    return made


async def main() -> int:
    guard()
    engine = make_engine(get_settings().DATABASE_URL)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session, session.begin():
            made = await seed(session)
            await sync_touched(session, "catalog", "identity")
            # TD_STORE_CATALOG=firestore: the demo catalogue is copied to Firestore too (p2.md).
            from app.core.firestore.backfill import sync_if_enabled

            synced = await sync_if_enabled(session, "catalog")
            if synced:
                print("Firestore:", synced)
    finally:
        await engine.dispose()
    print("DEV/DEMO catalogue ready:", ", ".join(made) or "(already present)")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(asyncio.run(main()))
