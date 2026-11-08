"""Demo placement seed: original sample content, idempotent, refused in production."""

from __future__ import annotations

import pytest
from sqlalchemy import text

from app.core.db import system_context
from app.seeds import placement_demo
from tests.identity.factory import make_user


def test_placement_seed_refuses_production(monkeypatch) -> None:
    from app.core.config import reset_settings_cache

    monkeypatch.setenv("APP_ENV", "production")
    reset_settings_cache()
    try:
        with pytest.raises(placement_demo.ProductionRefused):
            placement_demo.guard()
    finally:
        monkeypatch.setenv("APP_ENV", "test")
        reset_settings_cache()


async def test_placement_seed_is_idempotent_and_drawable(db) -> None:
    await make_user(db, email=placement_demo.AUTHOR_EMAIL)
    await make_user(db, email=placement_demo.REVIEWER_EMAIL)
    first = await placement_demo.seed(db)
    assert first == {"questions_created": len(placement_demo.QUESTIONS), "tests_created": 1}
    assert await placement_demo.seed(db) == {"questions_created": 0, "tests_created": 0}
    await system_context(db, "test")
    subjects = {r[0] for r in (await db.execute(text("SELECT path FROM topics WHERE depth = 0"))).all()}
    assert subjects >= {"quant", "logical", "verbal", "programming", "dsa", "cs-core"}
    refs = (
        await db.execute(
            text("SELECT count(*) FROM questions WHERE external_ref LIKE 'demo:%' AND status = 'active'")
        )
    ).scalar()
    assert refs == len(placement_demo.QUESTIONS)
    from sqlalchemy import select

    from app.modules.assessments import studio
    from app.modules.assessments.models import Test

    t = (await db.execute(select(Test).where(Test.slug == placement_demo.DEMO_TEST_SLUG))).scalar_one()
    assert t.status == "published" and t.is_free
    assert (await studio.validate(db, t))["feasible"] is True
