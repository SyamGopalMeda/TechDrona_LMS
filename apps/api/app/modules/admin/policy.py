"""Policy settings: key registry (defaults, bounds, flags), resolution and versioned changes.

Precedence (single company, admin_0004): user exception > plan > platform row > code default.
There is no organization layer any more. Every key has bounds and flags (``plan_overridable``,
``locked``); values outside the bounds are rejected. Locked (🔒) keys exist only at platform
scope. Changes are versioned rows (old row ``is_active = false``); reads are uncached DB reads, so a change is
effective immediately (well within the 60 s budget).

``TD_STORE_ADMIN=firestore``: rows live in ``policy_settings/{id}`` with ``policy_heads`` as the
one-active-row-per-scope invariant and version counter (``repo_firestore``). The ``session``
arguments are then unused (kept so callers in Postgres modules need no change).

``identity.policy.get_policy`` delegates here once the admin module is imported
(``register_policy_resolver``), so every module reads the same values.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import and_, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ProblemError
from app.core.firestore.backend import uses_firestore
from app.core.ids import uuid7
from app.modules.admin.models import PolicySetting
from app.modules.identity import clock


@dataclass(frozen=True)
class PolicyKey:
    key: str
    default: Any
    kind: str  # int | number | bool | enum | int_list | object | text
    min: Any = None
    max: Any = None
    choices: tuple[Any, ...] = ()
    plan: bool = False
    locked: bool = False
    tighten: str | None = None  # "lower" | "higher": overrides may only move this way
    namespace_extra: tuple[str, ...] = field(default=())


_K = PolicyKey
_KEYS: tuple[PolicyKey, ...] = (
    # sessions / devices / playback / assessment (RE §3.2)
    _K("sessions.student.max_concurrent", 2, "int", 1, 5, plan=True),
    _K(
        "sessions.student.at_limit_behavior",
        "prompt_choose",
        "enum",
        choices=("prompt_choose", "evict_oldest", "deny"),
    ),
    _K("sessions.staff.max_concurrent", 3, "int", 1, 5),
    _K("sessions.student.idle_minutes", 60, "int", 15, 60, tighten="lower"),
    _K("sessions.student.absolute_hours", 24, "int", 4, 24, tighten="lower"),
    _K("sessions.remember_device.max_days", 30, "int", 0, 30, plan=True, tighten="lower"),
    _K("devices.student.max_trusted", 3, "int", 1, 10, plan=True),
    # faculty (trainer, evaluator, content manager); also admins when devices.admin.cap_enabled
    _K("devices.staff.max_trusted", 3, "int", 1, 10),
    _K("devices.admin.cap_enabled", False, "bool"),
    _K("devices.student.max_replacements_per_30d", 2, "int", 0, 10, plan=True),
    _K("devices.new_device_verification", "otp", "enum", choices=("otp", "otp_plus_email_notice")),
    _K("devices.trusted_inactivity_expiry_days", 90, "int", 30, 180),
    _K("playback.max_concurrent_streams", 1, "int", 1, 3, plan=True),
    _K("playback.heartbeat_seconds", 30, "int", 15, 60),
    _K("playback.stale_after_seconds", 90, "int", 60, 180),
    _K("playback.takeover_behavior", "prompt_takeover", "enum", choices=("prompt_takeover", "deny")),
    _K("playback.otp_ttl_seconds", 300, "int", 60, 900),
    _K("assessment.single_device_binding", True, "bool"),
    _K("assessment.max_rebinds_per_attempt", 2, "int", 0, 5),
    _K("assessment.idle_hold_extra_minutes", 5, "int", 0, 15),
    _K("assessment.rebind_requires_otp_at_level", "L2", "enum", choices=("L0", "L1", "L2", "L3")),
    # risk engine
    _K("risk.mode", "shadow", "enum", choices=("off", "shadow", "enforce"), locked=True),
    _K("risk.hc.auto_restrict_enabled", False, "bool", locked=True),
    _K("risk.hc.circuit_breaker.max_fp_rate", 0.05, "number", 0.01, 0.2),
    _K("risk.hc.circuit_breaker.min_decisions", 20, "int", 10, 100),
    _K("risk.hc.circuit_breaker.max_daily_restrictions", 50, "int", 5, 500),
    _K("risk.window_days", 30, "int", 14, 60),
    _K("risk.decay_half_life_days", 7, "int", 3, 14),
    _K("risk.threshold.L1", 25, "number", 10, 100, plan=True, tighten="higher"),
    _K("risk.threshold.L2", 45, "number", 10, 100, plan=True, tighten="higher"),
    _K("risk.threshold.L3", 70, "number", 10, 100, plan=True, tighten="higher"),
    _K("risk.threshold.L4_recommend", 90, "number", 10, 100, plan=True, tighten="higher"),
    _K("risk.L3.min_categories", 2, "int", 2, 3),
    _K("risk.L3.min_distinct_days", 3, "int", 2, 7),
    _K("risk.L3.min_separated_days", 2, "int", 1, 7),
    _K("risk.L3.duration_hours", [24, 72], "int_list", 12, 168),
    _K("risk.repeat_window_days", 180, "int", 90, 365),
    _K("risk.network_points_cap", 20, "number", 0, 25, locked=True),
    _K("risk.fingerprint.enabled", False, "bool"),
    _K("risk.fingerprint.points_cap", 10, "number", 0, 10, locked=True),
    _K("risk.minors_scoring_enabled", False, "bool", locked=True),
    _K("risk.separation.multiplier.S0", 0.1, "number", 0, 0.5),
    _K("risk.separation.multiplier.S1", 0.1, "number", 0, 0.5),
    _K("risk.separation.multiplier.S2_verified", 0.1, "number", 0, 0.5),
    _K("risk.separation.multiplier.S2_unverified", 0.3, "number", 0, 0.5),
    _K("risk.separation.multiplier.S3", 1.0, "number", 1.0, 1.0, locked=True),
    _K("risk.owner_verification.max_age_days", 30, "int", 7, 90),
    _K("risk.owner_verification.refresh_prompt_days", 5, "int", 0, 14),
    _K("risk.cgnat_asns", [55836, 45609, 38266, 55410, 9829, 45271], "int_list", 1, 4294967295),
    # login / otp / auth (identity defaults; RE §3.2)
    _K("login.backoff_base_seconds", 1, "int", 1, 10),
    _K("login.backoff_cap_seconds", 900, "int", 60, 3600),
    _K("login.hard_disable_after_failures", 50, "int", 10, 100),
    _K("login.ip_failed_limit_per_10min", 30, "int", 10, 200),
    _K("otp.ttl_seconds", 300, "int", 120, 600),
    _K("otp.sms.max_per_number_per_hour", 3, "int", 1, 10),
    _K("otp.sms.max_per_number_per_day", 10, "int", 1, 30),
    _K("otp.max_verify_attempts", 5, "int", 3, 10),
    _K("otp.email.max_per_hour", 10, "int", 1, 30),
    _K("otp.email.max_per_day", 30, "int", 1, 100),
    _K("auth.password_reset_ttl_minutes", 30, "int", 10, 60),
    _K("auth.email_verify_ttl_hours", 24, "int", 1, 72),
    _K("auth.pending_login_minutes", 10, "int", 5, 30),
    _K("auth.session_choice_minutes", 5, "int", 1, 10),
    _K("auth.step_up_window.privileged", 300, "int", 60, 300),
    _K("auth.step_up_window.staff", 600, "int", 60, 600),
    _K("auth.step_up_window.student", 900, "int", 60, 900),
    _K("auth.require_mfa_students", False, "bool"),
    # unblock (UNB §3, §4.3)
    _K("unblock.max_open_requests", 1, "int", 1, 1, locked=True),
    _K("unblock.max_requests_per_30d", 3, "int", 1, 5),
    _K("unblock.sla.first_response_hours", {"L3": 24, "L4": 48, "escalated": 24, "takeover": 12}, "object"),
    _K("unblock.sla.decision_hours", {"L3": 72, "L4": 120, "escalated": 72, "takeover": 48}, "object"),
    _K("unblock.false_positive_extension", True, "bool", plan=True),
    # keys, analytics floors
    _K("security.keys.k_device.current_version", 1, "int", 1, 1000, locked=True),
    _K("security.keys.k_login.current_version", 1, "int", 1, 1000, locked=True),
    _K("analytics.k_min.cohort", 10, "int", 5, 50),
)
REGISTRY: dict[str, PolicyKey] = {k.key: k for k in _KEYS}

# Namespaces each proposer role may propose (ADM-09; API I-02). Single company (owner decision
# D2): the security and finance roles were folded into Admin, who may propose any key; dual
# control is "two different admins" (the approval queue refuses requester == approver).
PROPOSE_NAMESPACES: dict[str, tuple[str, ...]] = {"super_admin": ("",)}


def spec(key: str) -> PolicyKey:
    k = REGISTRY.get(key)
    if k is None:
        raise ProblemError(
            "not_found", detail="Unknown policy key", errors=[{"field": "setting_key", "code": "unknown_key"}]
        )
    return k


def _vf(code: str, message: str, **ext: Any) -> ProblemError:
    return ProblemError(
        "validation_failed", 422, errors=[{"field": "value", "code": code, "message": message}], **ext
    )


def validate_value(k: PolicyKey, value: Any) -> Any:
    """Type and bounds check; returns the normalised value."""

    def _num(v: Any) -> float:
        if isinstance(v, bool) or not isinstance(v, int | float):
            raise _vf("invalid_type", f"{k.key} expects a number")
        return float(v)

    if k.kind == "bool":
        if not isinstance(value, bool):
            raise _vf("invalid_type", f"{k.key} expects true/false")
        return value
    if k.kind == "enum":
        if value not in k.choices:
            raise _vf("invalid_choice", f"{k.key} must be one of {list(k.choices)}", allowed=list(k.choices))
        return value
    if k.kind in ("int", "number"):
        v = _num(value)
        if k.kind == "int" and int(v) != v:
            raise _vf("invalid_type", f"{k.key} expects an integer")
        if (k.min is not None and v < k.min) or (k.max is not None and v > k.max):
            raise _vf(
                "out_of_bounds",
                f"{k.key} must be between {k.min} and {k.max}",
                min_value=k.min,
                max_value=k.max,
            )
        return int(v) if k.kind == "int" else v
    if k.kind == "int_list":
        if not isinstance(value, list) or not value:
            raise _vf("invalid_type", f"{k.key} expects a non-empty list of integers")
        out = []
        for item in value:
            v = _num(item)
            if int(v) != v or (k.min is not None and v < k.min) or (k.max is not None and v > k.max):
                raise _vf(
                    "out_of_bounds",
                    f"{k.key} items must be integers in {k.min}..{k.max}",
                    min_value=k.min,
                    max_value=k.max,
                )
            out.append(int(v))
        return out
    if k.kind == "object":
        if not isinstance(value, dict):
            raise _vf("invalid_type", f"{k.key} expects an object")
        return value
    return value


# --------------------------------------------------------------------------- resolution


def _live(now: datetime) -> Any:
    return and_(
        PolicySetting.is_active.is_(True),
        PolicySetting.effective_from <= now,
        or_(PolicySetting.expires_at.is_(None), PolicySetting.expires_at > now),
    )


async def resolve(
    session: AsyncSession,
    key: str,
    *,
    user_id: uuid.UUID | None = None,
    org_id: uuid.UUID | None = None,
    plan_id: uuid.UUID | None = None,
) -> Any:
    """Effective value: user exception > plan > platform row > code default.

    ``org_id`` is accepted for old callers and ignored (single company)."""
    del org_id
    k = REGISTRY.get(key)
    now = clock.now()
    if uses_firestore("admin"):
        return await _fs_resolve(key, k, now, user_id=user_id, plan_id=plan_id)
    conds = [PolicySetting.scope_type == "platform"]
    if k is None or not k.locked:
        if user_id is not None:
            conds.append(and_(PolicySetting.scope_type == "user", PolicySetting.scope_id == user_id))
        if plan_id is not None and (k is None or k.plan):
            conds.append(and_(PolicySetting.scope_type == "plan", PolicySetting.scope_id == plan_id))
    rows = (
        await session.execute(
            select(PolicySetting.scope_type, PolicySetting.scope_id, PolicySetting.value).where(
                PolicySetting.setting_key == key, _live(now), or_(*conds)
            )
        )
    ).all()
    return _best(key, k, rows)


def _best(key: str, k: PolicyKey | None, rows: Any) -> Any:
    if not rows:
        if k is not None:
            return k.default
        from app.modules.identity.policy import DEFAULTS

        return DEFAULTS.get(key)
    rank = {"user": 0, "plan": 1, "platform": 2}
    best = sorted(rows, key=lambda r: (rank.get(r.scope_type, 9), str(r.scope_id)))[0]
    return best.value


async def _fs_resolve(
    key: str, k: PolicyKey | None, now: datetime, *, user_id: uuid.UUID | None, plan_id: uuid.UUID | None
) -> Any:
    from app.modules.admin.repo_firestore import system_repo

    scopes: list[tuple[str, str, Any]] = [(key, "platform", None)]
    if k is None or not k.locked:
        if user_id is not None:
            scopes.append((key, "user", user_id))
        if plan_id is not None and (k is None or k.plan):
            scopes.append((key, "plan", plan_id))
    rows = await system_repo("admin.policy").active_rows(scopes)
    return _best(key, k, [r for r in rows if r.live(now)])


async def get_value(session: AsyncSession, key: str, **kw: Any) -> Any:
    return await resolve(session, key, **kw)


async def identity_resolver(
    session: AsyncSession, key: str, org_id: uuid.UUID | None, user_id: uuid.UUID | None
) -> Any:
    return await resolve(session, key, org_id=org_id, user_id=user_id)


# --------------------------------------------------------------------------- changes


async def active_row(session: AsyncSession, key: str, scope_type: str, scope_id: uuid.UUID | None) -> Any:
    """The active row (``PolicySetting`` or, on Firestore, ``PolicyRow``) of one key and scope."""
    if uses_firestore("admin"):
        from app.modules.admin.repo_firestore import system_repo

        found = await system_repo("admin.policy").active_rows([(key, scope_type, scope_id)])
        return found[0] if found else None
    return (
        await session.execute(
            select(PolicySetting).where(
                PolicySetting.setting_key == key,
                PolicySetting.scope_type == scope_type,
                PolicySetting.scope_id.is_(None) if scope_id is None else PolicySetting.scope_id == scope_id,
                PolicySetting.is_active.is_(True),
            )
        )
    ).scalar_one_or_none()


async def active_platform_rows(session: AsyncSession, keys: list[str]) -> dict[str, Any]:
    """Active platform-scope rows of many keys at once (the settings listing)."""
    if uses_firestore("admin"):
        from app.modules.admin.repo_firestore import system_repo

        rows = await system_repo("admin.policy").active_rows([(k, "platform", None) for k in keys])
        return {r.setting_key: r for r in rows}
    res = (
        await session.execute(
            select(PolicySetting).where(
                PolicySetting.setting_key.in_(keys),
                PolicySetting.scope_type == "platform",
                PolicySetting.scope_id.is_(None),
                PolicySetting.is_active.is_(True),
            )
        )
    ).scalars()
    return {r.setting_key: r for r in res}


async def history_rows(session: AsyncSession, key: str) -> list[Any]:
    """Every version of a key (all scopes), newest first."""
    if uses_firestore("admin"):
        from app.modules.admin.repo_firestore import system_repo

        return await system_repo("admin.policy").history(key)
    return list(
        (
            await session.execute(
                select(PolicySetting)
                .where(PolicySetting.setting_key == key)
                .order_by(PolicySetting.created_at.desc())
            )
        )
        .scalars()
        .all()
    )


async def active_user_exception_count(session: AsyncSession, user_id: uuid.UUID, now: datetime) -> int:
    """Active, unexpired user-scope exceptions of one user (security HC-01 exclusion)."""
    if uses_firestore("admin"):
        from app.modules.admin.repo_firestore import system_repo

        return await system_repo("admin.policy").user_exception_count(user_id, now)
    from sqlalchemy import func

    n = (
        await session.execute(
            select(func.count())
            .select_from(PolicySetting)
            .where(
                PolicySetting.scope_type == "user",
                PolicySetting.scope_id == user_id,
                PolicySetting.is_active.is_(True),
                PolicySetting.expires_at > now,
            )
        )
    ).scalar_one()
    return int(n or 0)


async def _next_version_pg(
    session: AsyncSession, key: str, scope_type: str, scope_id: uuid.UUID | None
) -> int:
    from sqlalchemy import func

    v = (
        await session.execute(
            select(func.max(PolicySetting.version)).where(
                PolicySetting.setting_key == key,
                PolicySetting.scope_type == scope_type,
                PolicySetting.scope_id.is_(None) if scope_id is None else PolicySetting.scope_id == scope_id,
            )
        )
    ).scalar_one()
    return int(v or 0) + 1


SCOPE_TYPES = ("platform", "plan", "user")


def check_scope(k: PolicyKey, scope_type: str, scope_id: uuid.UUID | None, value: Any) -> None:
    if scope_type not in SCOPE_TYPES:
        raise _vf("invalid_scope", "Unknown scope type")
    if (scope_type == "platform") != (scope_id is None):
        raise _vf("invalid_scope", "scope_id is required except at platform scope")
    if scope_type != "platform" and k.locked:
        raise _vf("locked_key", f"{k.key} is locked: platform scope only")
    if scope_type == "plan" and not k.plan:
        raise _vf("not_overridable_at_scope", f"{k.key} cannot be overridden per plan")
    if scope_type == "plan" and k.tighten and k.kind in ("int", "number"):
        if (k.tighten == "lower" and value > k.default) or (k.tighten == "higher" and value < k.default):
            raise _vf("override_may_only_tighten", f"{k.key} overrides may only tighten the platform value")


async def write_setting(
    session: AsyncSession,
    *,
    key: str,
    scope_type: str,
    scope_id: uuid.UUID | None,
    value: Any,
    changed_by: uuid.UUID,
    change_reason: str,
    approved_by: uuid.UUID | None = None,
    approval_request_id: uuid.UUID | None = None,
    effective_from: datetime | None = None,
    expires_at: datetime | None = None,
    case_decision_id: uuid.UUID | None = None,
) -> Any:
    """Insert a new active version (the previous active row of that scope is deactivated)."""
    k = spec(key)
    value = validate_value(k, value)
    if uses_firestore("admin"):
        from app.modules.admin.repo_firestore import system_repo

        return await system_repo("admin.policy").write_version(
            {
                "setting_key": key,
                "scope_type": scope_type,
                "scope_id": str(scope_id) if scope_id else None,
                "value": value,
                "value_schema": k.kind,
                "min_value": k.min,
                "max_value": k.max,
                "plan_overridable": k.plan,
                "locked": k.locked,
                "expires_at": expires_at,
                "effective_from": effective_from,
                "case_decision_id": str(case_decision_id) if case_decision_id else None,
                "change_reason": change_reason,
                "changed_by": str(changed_by),
                "approved_by": str(approved_by) if approved_by else None,
                "approval_request_id": str(approval_request_id) if approval_request_id else None,
            }
        )
    await session.execute(
        update(PolicySetting)
        .where(
            PolicySetting.setting_key == key,
            PolicySetting.scope_type == scope_type,
            PolicySetting.scope_id.is_(None) if scope_id is None else PolicySetting.scope_id == scope_id,
            PolicySetting.is_active.is_(True),
        )
        .values(is_active=False)
    )
    row = PolicySetting(
        id=uuid7(),
        setting_key=key,
        scope_type=scope_type,
        scope_id=scope_id,
        value=value,
        value_schema=k.kind,
        min_value=k.min,
        max_value=k.max,
        plan_overridable=k.plan,
        locked=k.locked,
        version=await _next_version_pg(session, key, scope_type, scope_id),
        is_active=True,
        expires_at=expires_at,
        case_decision_id=case_decision_id,
        change_reason=change_reason,
        changed_by=changed_by,
        approved_by=approved_by,
        approval_request_id=approval_request_id,
    )
    if effective_from is not None:
        row.effective_from = effective_from
    session.add(row)
    await session.flush()
    return row


def setting_out(k: PolicyKey, row: Any) -> dict[str, Any]:
    return {
        "setting_key": k.key,
        "value": row.value if row else k.default,
        "default": k.default,
        "source": "platform_row" if row else "default",
        "version": row.version if row else 0,
        "kind": k.kind,
        "min_value": k.min,
        "max_value": k.max,
        "choices": list(k.choices) or None,
        "plan_overridable": k.plan,
        "locked": k.locked,
    }
