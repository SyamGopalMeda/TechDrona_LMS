"""Public, store-neutral API of the ai module (data-ops agent).

Other modules import only this file from ``ai``. Every function works on Postgres and on Firestore
(``TD_STORE_AI``); ``session`` is ignored by the Firestore paths of the settings/ledger/history
(the provider gate and the callers' own work may still use it).
"""

from __future__ import annotations

from app.modules.ai.adapters import load_config, production_problem
from app.modules.ai.service import (
    AIDisabled,
    AIError,
    AIQuotaExceeded,
    AIUnavailable,
    GradeSuggestion,
    PathGenSpec,
    QuestionGenSpec,
    ai_enabled,
    generate_path,
    generate_questions,
    grade_response,
    is_app_enabled,
    require_app_enabled,
    tutor_history,
    tutor_reply,
)
from app.modules.ai.store import APPS, PlatformAI, system_apps, system_settings

__all__ = [
    "APPS",
    "AIDisabled",
    "AIError",
    "AIQuotaExceeded",
    "AIUnavailable",
    "GradeSuggestion",
    "PathGenSpec",
    "PlatformAI",
    "QuestionGenSpec",
    "ai_enabled",
    "ai_simulated",
    "generate_path",
    "generate_questions",
    "grade_response",
    "is_app_enabled",
    "load_config",
    "production_problem",
    "require_app_enabled",
    "system_apps",
    "system_settings",
    "tutor_history",
    "tutor_reply",
]


def ai_simulated() -> bool:
    """True while the fake adapter is configured (screens say AI is not integrated yet)."""
    return load_config().provider == "fake"
