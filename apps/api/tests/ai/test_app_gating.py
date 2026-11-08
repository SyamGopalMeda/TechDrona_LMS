"""Platform app toggles (single company): ``require_app_enabled`` / ``is_app_enabled`` /
``ai_enabled``. Enabled by default; once Admin turns an app off it is off for everyone (with or
without an ``org_id``, which is ignored). The call sites in engage, paths, learning,
assessments and question banks belong to WS4 / WS5 and are covered by their suites."""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from app.core.errors import ProblemError
from app.modules.ai import service as ai
from tests.ai.conftest import disable_app


async def test_defaults_enabled(db: Any) -> None:
    for key in ai.APP_KEYS:
        assert await ai.is_app_enabled(db, key) is True
        await ai.require_app_enabled(db, app_key=key)


@pytest.mark.parametrize("org_id", [None, uuid.uuid4()])
async def test_disabled_for_everyone(db: Any, org_id: uuid.UUID | None) -> None:
    await disable_app(db, "engage")
    with pytest.raises(ProblemError) as e:
        await ai.require_app_enabled(db, org_id=org_id, app_key="engage")
    assert e.value.status == 403 and e.value.code == "app_disabled" and e.value.ext["app_key"] == "engage"
    await ai.require_app_enabled(db, org_id=org_id, app_key="paths")  # other apps untouched


async def test_sec19_question_banks_toggle_helper(db: Any) -> None:
    """WS5 calls ``require_app_enabled(session, app_key="question_banks")`` in ``_bank_for`` and
    ``resolve`` so every question-bank route honours the platform toggle."""
    assert await ai.is_app_enabled(db, "question_banks") is True
    await disable_app(db, "question_banks")
    assert await ai.is_app_enabled(db, "question_banks") is False
    with pytest.raises(ProblemError) as e:
        await ai.require_app_enabled(db, app_key="question_banks")
    assert e.value.code == "app_disabled"


async def test_unknown_key(db: Any) -> None:
    with pytest.raises(ValueError):
        await ai.require_app_enabled(db, app_key="nope")
    with pytest.raises(ValueError):
        await ai.is_app_enabled(db, "nope")


async def test_ai_apps_follow_toggle(db: Any) -> None:
    await disable_app(db, "ai_grading")
    assert await ai.ai_enabled(db, org_id=uuid.uuid4(), app_key="ai_grading") is False
    assert await ai.ai_enabled(db, app_key="ai_tutor") is True
