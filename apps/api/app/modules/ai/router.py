"""ai endpoints: platform AI settings, app toggles and usage (Admin), the current user's enabled
apps (nav gating) and their own tutor history.

Single company (WS3): these were ``/admin/orgs/{organization_id}/...``; they are now platform
settings at ``/admin/ai-settings``, ``/admin/apps`` and ``/admin/ai-usage``.

Permissions (checked at PLATFORM scope; only Admin holds them):

* settings / apps read and write — ``feature_flag.manage`` (writes need a fresh step-up and are
  audit-logged; the old ``org.settings.update`` permission no longer exists)
* usage read — ``analytics.read.platform``

Provider API keys are never returned or accepted: the response only says whether one is
configured.
"""

from __future__ import annotations

import re
import uuid
from datetime import date, timedelta
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import delete, update

from app.core.audit import audit
from app.core.auth import PLATFORM_SCOPE, require_active_principal, require_permission
from app.core.db import PrincipalDbSession
from app.core.errors import ProblemError
from app.core.principal import Principal
from app.core.routing import authenticated_router
from app.core.time import to_rfc3339, within
from app.modules.ai import service as ai
from app.modules.ai import store
from app.modules.ai.adapters import load_config
from app.modules.ai.models import AIUsage, TutorTurn
from app.modules.identity import clock

r = authenticated_router(tags=["ai"])
me_r = authenticated_router(prefix="/me", tags=["ai"], route_tag="l3_readonly", idle="neutral")
NEUTRAL = {"x-td-idle": "neutral"}
SETTINGS = "feature_flag.manage"
USAGE = "analytics.read.platform"
STEP_UP_SECONDS = 300
MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


def _perm(key: str) -> Any:
    return Depends(require_permission(key, scope=PLATFORM_SCOPE))


def _step_up(principal: Principal, seconds: int = STEP_UP_SECONDS) -> None:
    if not within(principal.last_step_up_at, timedelta(seconds=seconds), now=clock.now()):
        raise ProblemError(
            "step_up_required",
            step_up={
                "max_age_seconds": seconds,
                "allowed_methods": ["totp"],
                "options_url": "/api/v1/auth/step-up/options",
            },
        )


def _vf(field: str, code: str, msg: str) -> ProblemError:
    return ProblemError("validation_failed", 422, errors=[{"field": field, "code": code, "message": msg}])


# --------------------------------------------------------------------------- schemas


class AISettingsPatch(BaseModel):
    """Caps are always numbers: NULL ("unlimited") is no longer accepted (SEC-05)."""

    model_config = ConfigDict(extra="forbid")
    enabled: bool | None = None
    model: str | None = Field(default=None, min_length=1, max_length=100)
    monthly_token_cap: int | None = Field(default=None, ge=0, le=10_000_000_000)
    monthly_call_cap: int | None = Field(default=None, ge=0, le=100_000_000)
    per_activity_default_cap: int | None = Field(default=None, ge=0, le=10_000)
    tutor_per_minute: int | None = Field(default=None, ge=1, le=1000)
    tutor_per_day: int | None = Field(default=None, ge=1, le=100_000)
    generate_per_hour: int | None = Field(default=None, ge=1, le=10_000)
    generate_per_day: int | None = Field(default=None, ge=1, le=100_000)


class AppsPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    apps: dict[str, bool] = Field(min_length=1, max_length=len(store.APPS))


# --------------------------------------------------------------------------- outputs


def _settings_out(s: store.PlatformAI) -> dict[str, Any]:
    cfg = load_config()
    return {
        "ai": {
            "enabled": s.enabled,
            "model": s.model if s.model in cfg.allowed_models else cfg.default_model,
            "monthly_token_cap": s.monthly_token_cap,
            "monthly_call_cap": s.monthly_call_cap,
            "per_activity_default_cap": s.per_activity_default_cap,
            "tutor_per_minute": s.tutor_per_minute,
            "tutor_per_day": s.tutor_per_day,
            "generate_per_hour": s.generate_per_hour,
            "generate_per_day": s.generate_per_day,
            "updated_at": to_rfc3339(s.updated_at) if s.updated_at else None,
        },
        "provider": {"name": cfg.provider, "configured": cfg.configured},
        "allowed_models": list(cfg.allowed_models),
    }


def _apps_out(apps: dict[str, bool]) -> dict[str, Any]:
    return {
        "apps": [
            {"app_key": k, "label": label, "category": cat, "enabled": apps.get(k, True)}
            for k, (label, cat) in store.APPS.items()
        ],
    }


# --------------------------------------------------------------------------- AI settings


@r.get("/admin/ai-settings", openapi_extra=NEUTRAL)
async def get_ai_settings(
    session: PrincipalDbSession, principal: Principal = _perm(SETTINGS)
) -> dict[str, Any]:
    return _settings_out(await store.read_settings(session))


@r.patch("/admin/ai-settings")
async def patch_ai_settings(
    body: AISettingsPatch, session: PrincipalDbSession, principal: Principal = _perm(SETTINGS)
) -> dict[str, Any]:
    _step_up(principal)
    changes = body.model_dump(exclude_unset=True)
    for k, v in changes.items():
        if v is None and k != "model":
            raise _vf(k, "required", f"{k} needs a value; it cannot be cleared")
    if changes.get("model") is not None and changes["model"] not in load_config().allowed_models:
        raise _vf("model", "not_allowed", "Choose one of the allowed models")
    before = await store.read_settings(session)
    await store.write_settings(session, changes, principal.user_id)
    after = await store.read_settings(session)
    await audit(
        session,
        principal,
        "ai.settings.updated",
        "ai_settings",
        None,
        before={k: getattr(before, k) for k in changes},
        after={k: getattr(after, k) for k in changes},
    )
    return _settings_out(after)


# --------------------------------------------------------------------------- apps


@r.get("/admin/apps", openapi_extra=NEUTRAL)
async def get_apps(session: PrincipalDbSession, principal: Principal = _perm(SETTINGS)) -> dict[str, Any]:
    return _apps_out(await store.read_apps(session))


@r.patch("/admin/apps")
async def patch_apps(
    body: AppsPatch, session: PrincipalDbSession, principal: Principal = _perm(SETTINGS)
) -> dict[str, Any]:
    _step_up(principal)
    unknown = sorted(set(body.apps) - set(store.APPS))
    if unknown:
        raise _vf("apps", "unknown_app", f"Unknown app keys: {', '.join(unknown)}")
    before = await store.read_apps(session)
    await store.write_apps(session, body.apps, principal.user_id)
    after = await store.read_apps(session)
    changed = {k: after[k] for k in body.apps if before.get(k) != after[k]}
    await audit(
        session,
        principal,
        "ai.apps.updated",
        "app_settings",
        None,
        before={k: before[k] for k in changed},
        after=changed,
    )
    return _apps_out(after)


# --------------------------------------------------------------------------- usage


@r.get("/admin/ai-usage", openapi_extra=NEUTRAL)
async def get_ai_usage(
    session: PrincipalDbSession,
    month: str | None = Query(default=None, description="YYYY-MM (UTC); default current month"),
    principal: Principal = _perm(USAGE),
) -> dict[str, Any]:
    if month is not None and not MONTH_RE.match(month):
        raise _vf("month", "invalid", "Use YYYY-MM")
    d = date(int(month[:4]), int(month[5:]), 1) if month else clock.now().date()
    s = await store.system_settings(session)
    return {
        **(await store.usage_summary(session, d)),
        "caps": {"monthly_token_cap": s.monthly_token_cap, "monthly_call_cap": s.monthly_call_cap},
    }


# --------------------------------------------------------------------------- me


@me_r.get("/enabled-apps")
async def my_enabled_apps(
    session: PrincipalDbSession, principal: Principal = Depends(require_active_principal)
) -> dict[str, Any]:
    """The platform app set for nav gating (the same for every user)."""
    apps = await store.system_apps(session)
    ai_on = await ai.ai_enabled(session)
    if not ai_on:
        apps = {k: (v if store.APPS[k][1] != "ai" else False) for k, v in apps.items()}
    return {"apps": apps, "ai_enabled": ai_on}


@me_r.get("/ai/tutor-history")
async def my_tutor_history(
    session: PrincipalDbSession,
    context_type: Literal["assignment", "path_step", "practice"],
    context_id: uuid.UUID,
    item_id: uuid.UUID | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    principal: Principal = Depends(require_active_principal),
) -> dict[str, Any]:
    """The caller's own tutor history for one activity (SEC-17; RLS: own rows)."""
    turns = await ai.tutor_history(
        session,
        user_id=principal.user_id,
        context_type=context_type,
        context_id=context_id,
        item_id=item_id,
        limit=limit,
    )
    return {"data": turns}


# --------------------------------------------------------------------------- privacy erasure


async def erase_user(session: Any, user_id: uuid.UUID) -> dict[str, Any]:
    """DB-01: pseudonymise the usage ledger (counts/costs stay for platform reporting) and
    delete the learner's tutor history (``ai_tutor_turns``)."""
    res = await session.execute(update(AIUsage).where(AIUsage.user_id == user_id).values(user_id=None))
    turns = await session.execute(delete(TutorTurn).where(TutorTurn.user_id == user_id))
    await session.flush()
    return {
        "ai_usage_pseudonymised": int(getattr(res, "rowcount", 0) or 0),
        "ai_tutor_turns_deleted": int(getattr(turns, "rowcount", 0) or 0),
    }


def _register_erasure() -> None:
    from app.modules.admin.privacy import register_erasure_provider

    register_erasure_provider("ai", erase_user)


_register_erasure()

router = APIRouter()
for _r in (r, me_r):
    router.include_router(_r)
