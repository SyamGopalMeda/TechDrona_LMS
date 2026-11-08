"""Read-only access to product policy values (``policy_settings``, owned by the admin module).

Until the admin module ships the table, every lookup returns the documented default
(account-security-and-risk-engine §3.2). Resolution when the table exists: user exception >
platform default, active rows only (plans are resolved by the admin resolver). Single-company
LMS: there is no organization layer any more; ``org_id`` is accepted for backwards
compatibility and ignored.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

DEFAULTS: dict[str, Any] = {
    "sessions.student.max_concurrent": 2,
    "sessions.student.at_limit_behavior": "prompt_choose",
    "sessions.staff.max_concurrent": 3,
    "sessions.remember_device.max_days": 30,
    "devices.student.max_trusted": 3,
    "devices.student.max_replacements_per_30d": 2,
    "devices.trusted_inactivity_expiry_days": 90,
    "login.backoff_base_seconds": 1,
    "login.backoff_cap_seconds": 900,
    "login.hard_disable_after_failures": 50,
    "login.ip_failed_limit_per_10min": 30,
    "otp.ttl_seconds": 300,
    "otp.sms.max_per_number_per_hour": 3,
    "otp.sms.max_per_number_per_day": 10,
    "otp.max_verify_attempts": 5,
    "otp.email.max_per_hour": 10,  # proposed key (email OTP caps are not in RE §3.2)
    "otp.email.max_per_day": 30,
    "auth.password_reset_ttl_minutes": 30,
    "auth.email_verify_ttl_hours": 24,
    "auth.pending_login_minutes": 10,
    "auth.session_choice_minutes": 5,
    # Single-company replacement of the per-org ``settings.require_mfa_students`` (FR-ORG-002).
    "auth.require_mfa_students": False,
}

_table_exists: bool | None = None

PolicyResolver = Callable[[AsyncSession, str, "uuid.UUID | None", "uuid.UUID | None"], Awaitable[Any]]
_resolver: PolicyResolver | None = None


def register_policy_resolver(fn: PolicyResolver | None) -> None:
    """Admin module hook: ``await fn(session, key, org_id, user_id)`` (registry defaults, plan
    scope, bounds). Registered when ``app.modules.admin.router`` is imported. ``org_id`` is
    always ``None`` now (kept in the signature until the admin module drops it)."""
    global _resolver
    _resolver = fn


async def _has_table(session: AsyncSession) -> bool:
    global _table_exists
    if _table_exists is None:
        r = await session.execute(text("SELECT to_regclass('public.policy_settings') IS NOT NULL"))
        _table_exists = bool(r.scalar())
    return _table_exists


def reset_policy_cache() -> None:
    global _table_exists
    _table_exists = None


async def get_policy(
    session: AsyncSession,
    key: str,
    *,
    org_id: uuid.UUID | None = None,
    user_id: uuid.UUID | None = None,
) -> Any:
    del org_id  # single-company: no organization policy layer
    if _resolver is not None:
        return await _resolver(session, key, None, user_id)
    default = DEFAULTS.get(key)
    if not await _has_table(session):
        return default
    rows = (
        await session.execute(
            text(
                "SELECT scope_type, scope_id, value FROM policy_settings "
                "WHERE setting_key = :k AND is_active AND effective_from <= now() "
                "AND (expires_at IS NULL OR expires_at > now()) "
                "AND (scope_type = 'platform' OR (scope_type = 'user' AND scope_id = :uid))"
            ),
            {"k": key, "uid": user_id},
        )
    ).all()
    rank = {"user": 0, "platform": 1}
    if not rows:
        return default
    best = sorted(rows, key=lambda r: rank.get(r.scope_type, 9))[0]
    return best.value
