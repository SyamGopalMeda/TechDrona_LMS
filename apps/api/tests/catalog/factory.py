"""Shared factories for catalog / learning / media tests (direct DB writes in a system
context on the rolled-back test connection, plus browser logins through the real stack)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import system_context
from app.core.ids import uuid7
from app.core.time import utcnow
from app.modules.catalog.models import Course, CourseModule, CourseVersion, Lesson, LessonAsset
from tests.identity.factory import Browser, UserHandle, grant, make_user, staff_login
from tests.identity.fixtures import last_code


@dataclass
class PublishedCourse:
    course_id: uuid.UUID
    version_id: uuid.UUID
    slug: str
    lessons: dict[str, uuid.UUID] = field(default_factory=dict)  # name -> lesson id
    keys: dict[str, uuid.UUID] = field(default_factory=dict)  # name -> lesson_key
    assets: dict[str, uuid.UUID] = field(default_factory=dict)  # name -> asset id


async def make_published_course(
    db: AsyncSession,
    author: uuid.UUID,
    *,
    is_free: bool = True,
    org_id: uuid.UUID | None = None,
    title: str = "Data Structures for Placements",
    visibility: str = "public",
    certificate_rule: dict[str, Any] | None = None,
    video_preview: bool = False,
    extra_lessons: list[dict[str, Any]] | None = None,
) -> PublishedCourse:
    """Published course: one module with a required article (est 2 min) and a required video
    (600 s, ready VdoCipher asset)."""
    await system_context(db, "test.factory")
    cid, vid = uuid7(), uuid7()
    slug = f"course-{cid.hex[-10:]}"
    db.add(
        Course(
            id=cid,
            organization_id=org_id,
            slug=slug,
            title=title,
            visibility=visibility,
            status="published",
            is_free=is_free,
            created_by=author,
        )
    )
    await db.flush()
    db.add(
        CourseVersion(
            id=vid,
            course_id=cid,
            organization_id=org_id,
            version_no=1,
            title=title,
            summary="Arrays, linked lists and trees for campus placements",
            tags=["dsa", "placements"],
            category="dsa",
            level="beginner",
            status="published",
            published_at=utcnow(),
            published_by=author,
            created_by=author,
            certificate_rule=certificate_rule
            if certificate_rule is not None
            else {"required_lessons_pct": 100},
        )
    )
    await db.flush()
    mid = uuid7()
    db.add(
        CourseModule(
            id=mid,
            course_version_id=vid,
            organization_id=org_id,
            module_key=uuid7(),
            title="Basics",
            position=0,
        )
    )
    await db.flush()
    pc = PublishedCourse(cid, vid, slug)
    specs: list[dict[str, Any]] = [
        {
            "name": "article",
            "lesson_type": "article",
            "est_reading_minutes": 2,
            "article_body": {"doc": "Arrays"},
        },
        {"name": "video", "lesson_type": "video", "duration_seconds": 600, "is_free_preview": video_preview},
        *(extra_lessons or []),
    ]
    for pos, spec in enumerate(specs):
        spec = dict(spec)
        name = spec.pop("name")
        lid, key = uuid7(), uuid7()
        db.add(
            Lesson(
                id=lid,
                course_module_id=mid,
                course_version_id=vid,
                organization_id=org_id,
                lesson_key=key,
                title=name.title(),
                position=pos,
                **spec,
            )
        )
        await db.flush()
        pc.lessons[name], pc.keys[name] = lid, key
        if spec["lesson_type"] == "video":
            aid = uuid7()
            db.add(
                LessonAsset(
                    id=aid,
                    lesson_id=lid,
                    organization_id=org_id,
                    asset_type="video",
                    provider="vdocipher",
                    provider_asset_id=f"vid{aid.hex}",
                    status="available",
                    scan_status="not_required",
                    duration_seconds=600,
                )
            )
            pc.assets[name] = aid
    await db.flush()
    from sqlalchemy import update

    await db.execute(update(Course).where(Course.id == cid).values(current_version_id=vid))
    await db.flush()
    return pc


async def staff(
    db: AsyncSession, browser: Browser, role: str, scope: str = "platform", scope_id: Any = None
) -> UserHandle:
    u = await make_user(db, with_totp=True)
    await grant(db, u.id, role, scope, scope_id)
    await staff_login(browser, u)
    return u


async def student(db: AsyncSession, browser: Browser, **kw: Any) -> UserHandle:
    u = await make_user(db, **kw)
    r = await browser.login(u.email)
    assert r.status_code == 200 and r.json()["result"] == "authenticated", r.text
    return u


async def login_new_device(b: Browser, mail: Any, email: str) -> None:
    r = await b.login(email)
    assert r.status_code == 200 and r.json()["result"] == "device_verification_required", r.text
    assert (await b.post("/auth/device-verification/send", {"channel": "email"})).status_code == 200
    r = await b.post("/auth/device-verification/verify", {"code": last_code(mail)})
    assert r.status_code == 200 and r.json()["result"] == "authenticated", r.text


def idem() -> dict[str, str]:
    return {"Idempotency-Key": str(uuid.uuid4())}


@pytest.fixture
def audited(monkeypatch: Any) -> list[str]:
    """Spy on ``audit()`` calls of the catalog/learning/media modules (td_app cannot read
    audit_outbox)."""
    from app.core import audit as core_audit

    actions: list[str] = []
    real = core_audit.audit

    async def spy(session: Any, actor: Any, action: str, *a: Any, **kw: Any) -> Any:
        actions.append(action)
        return await real(session, actor, action, *a, **kw)

    import app.modules.catalog.router as cr
    import app.modules.learning.router as lr
    import app.modules.learning.service as ls

    for mod in (cr, lr, ls):
        monkeypatch.setattr(mod, "audit", spy)
    return actions
