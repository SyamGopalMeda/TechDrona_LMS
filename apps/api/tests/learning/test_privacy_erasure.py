"""DB-01: erasure providers of learning, placement, support and mentoring are registered with
``admin.privacy`` and remove or minimise the user's personal data (idempotently)."""

from __future__ import annotations

import pytest
from sqlalchemy import func, select

from app.core import access
from app.core.db import system_context
from app.core.ids import uuid7
from app.core.time import utcnow
from app.modules.learning.models import Certificate, Enrolment, LessonProgress
from tests.catalog.factory import make_published_course, student
from tests.identity.factory import make_user


@pytest.fixture(autouse=True)
def fake_video():
    from app.modules.media import providers

    providers.set_video_provider(providers.FakeVideoProvider())
    prev = access.get_access_checker()
    access.register_access_checker(None)
    yield
    access.register_access_checker(prev)
    providers.set_video_provider(None)


def test_providers_registered_for_owned_modules() -> None:
    import app.modules.learning.router
    import app.modules.mentoring.router
    import app.modules.placement.router
    import app.modules.support.router  # noqa: F401
    from app.modules.admin.privacy import erasure_providers

    regs = erasure_providers()
    for m in ("learning", "placement", "support", "mentoring"):
        assert m in regs, m


@pytest.mark.usefixtures("catalog_backend")
async def test_learning_erasure(browser, db) -> None:
    from app.modules.learning import privacy
    from app.modules.learning import service as ls

    author = await make_user(db)
    pc = await make_published_course(db, author.id, is_free=True)
    u = await student(db, browser)
    assert (await browser.post("/me/enrolments", {"course_id": str(pc.course_id)})).status_code == 201
    await system_context(db, "t")
    for k in ("article", "video"):
        assert await ls.record_completion(db, u.id, pc.keys[k], {"kind": "test"})
    await db.flush()
    out = await privacy.erase_user(db, u.id)
    assert out["lesson_progress_deleted"] == 2 and out["certificates_revoked"] == 1
    assert out["enrolments_withdrawn"] == 1
    n = (await db.execute(select(func.count()).where(LessonProgress.user_id == u.id))).scalar_one()
    assert n == 0
    cert = (
        await db.execute(
            select(Certificate).where(Certificate.user_id == u.id).execution_options(populate_existing=True)
        )
    ).scalar_one()
    assert cert.name_on_certificate == privacy.ERASED_NAME and cert.revoked_at is not None
    enr = (
        await db.execute(
            select(Enrolment).where(Enrolment.user_id == u.id).execution_options(populate_existing=True)
        )
    ).scalar_one()
    assert enr.status == "withdrawn"
    again = await privacy.erase_user(db, u.id)
    assert all(v == 0 for v in again.values()), again


@pytest.mark.usefixtures("catalog_backend")
async def test_placement_and_mentoring_erasure(db) -> None:
    from app.modules.mentoring import privacy as mp
    from app.modules.mentoring.models import Resume
    from app.modules.placement import privacy as pp
    from app.modules.placement.models import PracticeSession, Recommendation

    u = await make_user(db)
    await system_context(db, "t")
    db.add(PracticeSession(id=uuid7(), user_id=u.id, mode="adaptive"))
    db.add(
        Recommendation(
            id=uuid7(),
            user_id=u.id,
            rule_key="weak_topic",
            reason="r",
            target_type="topic",
            target_id=uuid7(),
            expires_at=utcnow(),
        )
    )
    db.add(Resume(id=uuid7(), user_id=u.id, template_key="ats_classic", content={"name": "Asha"}))
    await db.flush()
    out = await pp.erase_user(db, u.id)
    assert out["practice_sessions_deleted"] == 1 and out["recommendations_deleted"] == 1
    assert (await pp.erase_user(db, u.id))["practice_sessions_deleted"] == 0
    mo = await mp.erase_user(db, u.id)
    assert mo["resumes_deleted"] == 1
    n = (await db.execute(select(func.count()).where(Resume.user_id == u.id))).scalar_one()
    assert n == 0
