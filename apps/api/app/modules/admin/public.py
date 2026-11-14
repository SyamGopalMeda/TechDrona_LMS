"""Public, store-neutral API of the admin module (data-ops agent).

Other modules import **only this file** from ``admin``: every function works on Postgres and on
Firestore (``TD_STORE_ADMIN``). ``session`` is the caller's Postgres session; it is ignored when
admin is on Firestore (pass ``None`` there).

* Feature flags: ``flag_enabled``, ``cached_flag_enabled``, ``invalidate_flag``, ``patch_flag``.
* Policy settings: ``get_value``, ``active_policy_setting``, ``active_policy_settings``,
  ``active_user_exception_count``, ``write_setting`` (+ the
  ``policy`` module for its registry helpers: ``spec``, ``validate_value``, ``REGISTRY`` ...).
* Dual-control approvals: ``approvals`` (the rbac ``approval_requests`` table, owned by rbac;
  re-exported for the handler registry: ``register``, ``ApprovalHandler``, ``new_request``...).
* Privacy: ``register_erasure_provider``, ``ErasureProvider``, ``subject_hash``,
  ``privacy_open_counts``, ``OPEN_PRIVACY_STATES``.
* Break-glass: ``active_break_glass_count``, ``expire_break_glass``.
* Retention: ``retention_policies``, ``retention_interval`` (a ``PgInterval``: Postgres
  interval semantics, with ``add_interval`` / ``subtract_interval`` / ``interval_days``),
  ``active_retention_intervals``, ``ensure_retention_defaults`` (Firestore seed of the
  migration rows).
* Policy rows of case decisions: ``policy_case_decision_ids``, ``policy_settings_for_case_decisions``.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from app.core.errors import ProblemError
from app.core.firestore.backend import uses_firestore
from app.core.principal import Principal
from app.modules.admin import approvals, policy
from app.modules.admin.flags import cached_flag_enabled, flag_enabled
from app.modules.admin.flags import invalidate as invalidate_flag
from app.modules.admin.intervals import PgInterval, add_interval, interval_days, subtract_interval
from app.modules.admin.policy import active_user_exception_count, get_value, write_setting
from app.modules.admin.privacy import OPEN_STATES as OPEN_PRIVACY_STATES
from app.modules.admin.privacy import ErasureProvider, register_erasure_provider, subject_hash

__all__ = [
    "OPEN_PRIVACY_STATES",
    "ErasureProvider",
    "FlagState",
    "PgInterval",
    "active_break_glass_count",
    "active_policy_setting",
    "active_policy_settings",
    "active_retention_intervals",
    "active_user_exception_count",
    "add_interval",
    "approvals",
    "cached_flag_enabled",
    "ensure_retention_defaults",
    "expire_break_glass",
    "flag_enabled",
    "get_value",
    "interval_days",
    "invalidate_flag",
    "patch_flag",
    "policy",
    "policy_case_decision_ids",
    "policy_settings_for_case_decisions",
    "privacy_open_counts",
    "register_erasure_provider",
    "retention_interval",
    "retention_policies",
    "subject_hash",
    "subtract_interval",
    "write_setting",
]


class FlagState:
    """The flag fields callers read (``id`` for the audit target, the rest for display)."""

    def __init__(self, f: Any) -> None:
        self.id: uuid.UUID = f.id
        self.flag_key: str = f.flag_key
        self.description: str = f.description
        self.is_enabled: bool = bool(f.is_enabled)
        self.rollout_percent: int = int(f.rollout_percent)
        self.user_allowlist: list[uuid.UUID] = list(f.user_allowlist or [])


async def patch_flag(
    session: Any, principal: Principal, key: str, changes: dict[str, Any]
) -> tuple[FlagState, FlagState]:
    """Change a feature flag as ``principal`` (the store re-checks ``feature_flag.manage`` on
    Firestore). Returns (before, after); ``ProblemError('not_found')`` for an unknown key. The
    caller audits; the flag cache is invalidated here."""
    if uses_firestore("admin"):
        from app.core.firestore.store import ScopedStore
        from app.modules.admin.repo_firestore import AdminSettingsRepo

        prev, after = await AdminSettingsRepo(ScopedStore(principal)).patch_flag(
            key, changes, principal.user_id
        )
        invalidate_flag(key)
        return FlagState(prev), FlagState(after)
    from sqlalchemy import select

    from app.modules.admin.models import FeatureFlag

    f = (await session.execute(select(FeatureFlag).where(FeatureFlag.flag_key == key))).scalar_one_or_none()
    if f is None:
        raise ProblemError("not_found")
    before = FlagState(f)
    for k, v in changes.items():
        setattr(f, k, v)
    f.updated_by = principal.user_id
    await session.flush()
    invalidate_flag(key)
    return before, FlagState(f)


async def privacy_open_counts(session: Any, now: datetime) -> tuple[int, int]:
    """(open, overdue) privacy requests (admin dashboard)."""
    from app.modules.admin.accounts import _privacy_counts

    return await _privacy_counts(session, OPEN_PRIVACY_STATES, now)


async def active_break_glass_count(session: Any) -> int:
    from app.modules.admin.accounts import _bg_active_count

    return await _bg_active_count(session)


async def expire_break_glass(session: Any) -> int:
    """System job ``admin.break_glass_expiry`` (session: system context, for grants and audit)."""
    from app.modules.admin.accounts import expire_break_glass as _expire

    return await _expire(session)


async def retention_policies(session: Any) -> list[Any]:
    """Every retention policy row (ORM-compatible attributes), ordered by ``table_name``."""
    if uses_firestore("admin"):
        from app.modules.admin.repo_firestore_privacy import privacy_repo

        return list(await privacy_repo(None, "admin.retention").retention_policies())
    from sqlalchemy import select

    from app.modules.admin.models import RetentionPolicy

    return list(
        (await session.execute(select(RetentionPolicy).order_by(RetentionPolicy.table_name))).scalars()
    )


async def active_policy_setting(
    session: Any, key: str, *, scope_type: str = "platform", scope_id: uuid.UUID | None = None
) -> Any | None:
    """The active ``policy_settings`` row of ``key`` at one scope (``PolicySetting`` on Postgres,
    ``PolicyRow`` with the same attributes on Firestore), or ``None``. Read this instead of the
    ``policy_settings`` table / collection (security retention, pass 2 and 3). For the effective
    value with precedence and code defaults use ``get_value``."""
    return await policy.active_row(session, key, scope_type, scope_id)


async def active_policy_settings(
    session: Any, keys: list[str], *, scope_type: str = "platform", scope_id: uuid.UUID | None = None
) -> dict[str, Any]:
    """``{key: active row}`` for several keys at one scope (keys without an active row are absent)."""
    out: dict[str, Any] = {}
    if uses_firestore("admin"):
        from app.modules.admin.repo_firestore import system_repo

        for r in await system_repo("admin.policy").active_rows([(k, scope_type, scope_id) for k in keys]):
            out[r.setting_key] = r
        return out
    for k in keys:
        row = await policy.active_row(session, k, scope_type, scope_id)
        if row is not None:
            out[k] = row
    return out


async def retention_interval(session: Any, table: str) -> PgInterval | None:
    """The retention interval of ``table``: the shortest active ``retention_policies`` row (as the
    purge functions use it), with its months/days/microseconds kept (``ts - iv`` follows Postgres:
    ``'1 year'`` is a calendar year). ``None`` when no active row has an interval."""
    if uses_firestore("admin"):
        rows = [
            r.retention_interval
            for r in await retention_policies(None)
            if r.table_name == table and r.is_active and r.retention_interval is not None
        ]
        return min(rows) if rows else None
    from sqlalchemy import text

    from app.modules.admin.intervals import components_sql, from_components

    res = await session.execute(
        text(
            "SELECT " + components_sql("retention_interval") + " FROM retention_policies "  # noqa: S608
            "WHERE table_name = :t AND is_active AND retention_interval IS NOT NULL"
        ),
        {"t": table},
    )
    ivs = [iv for row in res.mappings().all() if (iv := from_components(dict(row))) is not None]
    return min(ivs) if ivs else None


async def ensure_retention_defaults(session: Any) -> int:
    """Firestore: insert the migration-seeded ``retention_policies`` rows that are missing (by
    ``(table_name, data_category)``; existing rows, admin edits included, are never changed).
    Postgres: the migrations own the rows -- nothing to do. Returns the number created."""
    if not uses_firestore("admin"):
        return 0
    from app.modules.admin.repo_firestore_privacy import privacy_repo

    return await privacy_repo(None, "admin.retention").ensure_retention_defaults()


async def active_retention_intervals(session: Any) -> dict[str, PgInterval | None]:
    """``{table_name: interval}`` for every table with an **active** ``retention_policies`` row:
    the shortest active interval (``min(retention_interval)`` of ``maint.purge_expired_rows``), or
    ``None`` when the active rows carry no interval (the SQL purge raises then). Tables without an
    active row are absent (``maint.run_retention`` skips them)."""
    if uses_firestore("admin"):
        out: dict[str, PgInterval | None] = {}
        for r in await retention_policies(None):
            if not r.is_active:
                continue
            iv = PgInterval.coerce(r.retention_interval)
            cur = out.get(r.table_name)
            out[r.table_name] = iv if cur is None else (cur if iv is None else min(cur, iv))
        return out
    from sqlalchemy import text

    res = await session.execute(text("SELECT DISTINCT table_name FROM retention_policies WHERE is_active"))
    return {str(t): await retention_interval(session, str(t)) for t in res.scalars().all()}


async def policy_settings_for_case_decisions(session: Any, decision_ids: Any) -> list[Any]:
    """Every ``policy_settings`` row (any version) whose ``case_decision_id`` is one of
    ``decision_ids`` (``PolicySetting`` on Postgres, ``PolicyRow`` on Firestore)."""
    ids = [uuid.UUID(str(d)) for d in dict.fromkeys(decision_ids or ())]
    if not ids:
        return []
    if uses_firestore("admin"):
        from app.modules.admin.repo_firestore import PolicyRow, system_repo
        from app.modules.admin.store_specs import POLICY

        store = system_repo("admin.policy").store
        out: list[Any] = []
        for i in range(0, len(ids), 30):
            cursor: str | None = None
            while True:
                page = await store.query(
                    POLICY,
                    filters=(("case_decision_id", "in", [str(x) for x in ids[i : i + 30]]),),
                    order_by=(),
                    limit=200,
                    cursor=cursor,
                )
                out += [PolicyRow.of(d.data) for d in page.items]
                if not page.next_cursor:
                    break
                cursor = page.next_cursor
        return out
    from sqlalchemy import select

    from app.modules.admin.models import PolicySetting

    rows = await session.execute(select(PolicySetting).where(PolicySetting.case_decision_id.in_(ids)))
    return list(rows.scalars().all())


async def policy_case_decision_ids(session: Any, decision_ids: Any) -> set[uuid.UUID]:
    """Which of ``decision_ids`` are referenced by a ``policy_settings`` row (security's
    ``purge_closed_cases`` NOT EXISTS check)."""
    return {
        r.case_decision_id
        for r in await policy_settings_for_case_decisions(session, decision_ids)
        if r.case_decision_id is not None
    }
