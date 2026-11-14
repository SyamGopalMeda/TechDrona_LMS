"""Restrictions L1-L4 and T-protect (RE §6, §7.2, §8; UNB §6).

* ``restriction_state`` is registered as ``sessions.hooks.register_restriction_lookup``: every
  authenticated request derives its scope from the active restrictions (bound to ``user_id``,
  never to device, session or IP).
* ``users.restriction_level`` is the cache column (max active sharing level) kept in sync on
  every change so the sessions default lookup still fails closed if the hook is absent.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import AuditActor, audit
from app.core.db import as_system
from app.core.firestore.backend import uses_firestore
from app.core.ids import uuid7
from app.core.outbox import emit_event
from app.core.principal import Principal
from app.core.time import to_rfc3339
from app.modules.identity import clock
from app.modules.identity import public as identity_public
from app.modules.security import adapters as ad
from app.modules.security.models import AccountRestriction, SecurityCase, SecurityUserState
from app.modules.sessions import service as ss
from app.modules.sessions.hooks import RestrictionState

SCOPE_FOR_LEVEL = {1: "learning_access", 2: "learning_access", 3: "learning_access", 4: "status_only"}
DEFER_MAX = timedelta(hours=3)
STEP_UP_AMR = ("totp", "passkey", "recovery_code", "otp_sms")


def _fs() -> bool:
    return uses_firestore("security")


def _repo() -> Any:
    from app.modules.security.repo_firestore import system_repo

    return system_repo()


async def active_restrictions(session: AsyncSession, user_id: uuid.UUID) -> list[AccountRestriction]:
    if _fs():
        return list(await _repo().active_restrictions(user_id))
    return list(
        (
            await session.execute(
                select(AccountRestriction).where(
                    AccountRestriction.user_id == user_id, AccountRestriction.ended_at.is_(None)
                )
            )
        ).scalars()
    )


async def active_for(session: AsyncSession, user_id: uuid.UUID, family: str) -> AccountRestriction | None:
    if _fs():
        found: Any = await _repo().active_for(user_id, family)
        return found
    return (
        await session.execute(
            select(AccountRestriction)
            .where(
                AccountRestriction.user_id == user_id,
                AccountRestriction.family == family,
                AccountRestriction.ended_at.is_(None),
            )
            .with_for_update()
        )
    ).scalar_one_or_none()


async def get_state(session: AsyncSession, user_id: uuid.UUID) -> SecurityUserState:
    if _fs():
        fs_state: Any = await _repo().ensure_state(user_id)
        return fs_state
    st = await session.get(SecurityUserState, user_id)
    if st is None:
        st = SecurityUserState(user_id=user_id, sharing_score=0, takeover_score=0, sharing_level=0)
        session.add(st)
        await session.flush()
    return st


async def _step_up_required(session: AsyncSession, user_id: uuid.UUID) -> bool:
    from app.core.config import get_settings

    if get_settings().account_protection_off:
        return False
    if _fs():
        return await _step_up_required_fs(session, user_id)
    st = await session.get(SecurityUserState, user_id)
    if st is None or st.step_up_required_since is None:
        return False
    if st.step_up_cleared_at is not None and st.step_up_cleared_at >= st.step_up_required_since:
        return False
    user = await identity_public.get_user(session, user_id)
    amr: list[str] = list(STEP_UP_AMR)
    if user is not None and not (user.phone_e164 and user.phone_verified_at):
        amr.append("otp_email")
    if await ad.stepped_up_sessions_since(session, user_id, st.step_up_required_since, amr):
        st.step_up_cleared_at = clock.now()
        await session.flush()
        return False
    return True


async def _maybe_end_protect_lock(session: AsyncSession, r: AccountRestriction) -> bool:
    """T-protect ends on self-service recovery: a password reset after the lock (RE §6.2), or at
    once while ``TD_ACCOUNT_PROTECTION_OFF`` is on (testing phase)."""
    from app.core.config import get_settings

    off = get_settings().account_protection_off
    if _fs():
        pw_at = await ad.password_set_at(session, r.user_id)
        if off or (pw_at is not None and pw_at > r.starts_at):
            await end_restriction(session, r, "takeover_recovered", ended_by=None)
            await ad.set_must_change_password(session, r.user_id, False)
            return True
        return False
    pw_set = await ad.password_set_at(session, r.user_id)
    if off or (pw_set is not None and pw_set > r.starts_at):
        await end_restriction(session, r, "takeover_recovered", ended_by=None)
        await ad.set_must_change_password(session, r.user_id, False)
        return True
    return False


async def restriction_state(session: AsyncSession, user_id: uuid.UUID) -> RestrictionState:
    """``sessions.hooks`` restriction lookup (RE §7.2 steps 5-7). Runs inside the request
    resolver and may end a recovered protect-lock or clear a passed step-up; enforcement rows are
    owner read-only (DB-05), so it runs as a named system job and restores the caller's context."""
    if _fs():
        return await _restriction_state(session, user_id)
    async with as_system(session, "security.restriction_state"):
        return await _restriction_state(session, user_id)


async def _restriction_state(session: AsyncSession, user_id: uuid.UUID) -> RestrictionState:
    level = 0
    case_ref: str | None = None
    until: datetime | None = None
    locks: set[str] = set()
    takeover = False
    for r in await active_restrictions(session, user_id):
        if r.family == "takeover" and r.scope == "protect_lock":
            if not await _maybe_end_protect_lock(session, r):
                takeover = True
            continue
        if r.level > level:
            level = r.level
            until = r.ends_at
            if r.case_id and _fs():
                case_ref = await _repo().case_ref(r.case_id)
            elif r.case_id:
                case_ref = (
                    await session.execute(select(SecurityCase.case_ref).where(SecurityCase.id == r.case_id))
                ).scalar_one_or_none()
        if r.level == 2:
            locks.add("device_verification_required")
            locks.update(f"reverify:{d}" for d in r.reverify_device_ids)
        if r.level >= 3:
            locks.update(
                {"video_locked", "attempt_locked", "practice_locked", "download_locked", "certificate_locked"}
            )
        if r.deferred_until is not None and r.deferred_until > clock.now():
            locks.add("l3_deferred")
    return RestrictionState(
        level=level,
        case_ref=case_ref,
        until=until,
        restrictions=frozenset(locks),
        takeover_lock=takeover,
        step_up_required=await _step_up_required(session, user_id),
    )


async def recompute_cache(session: AsyncSession, user_id: uuid.UUID) -> int:
    if _fs():
        rows = await _repo().active_restrictions(user_id)
        lvl_fs = max((int(x.level) for x in rows if x.family == "sharing"), default=0)
        await ad.set_restriction_cache(session, user_id, lvl_fs)
        return lvl_fs
    lvl = (
        await session.execute(
            select(func.coalesce(func.max(AccountRestriction.level), 0)).where(
                AccountRestriction.user_id == user_id,
                AccountRestriction.ended_at.is_(None),
                AccountRestriction.family == "sharing",
            )
        )
    ).scalar_one()
    await ad.set_restriction_cache(session, user_id, int(lvl))  # users cache + active session scopes
    return int(lvl)


async def _clear_remember(session: AsyncSession, user_id: uuid.UUID) -> None:
    await ad.clear_remembered_devices(session, user_id)


async def revoke_for_level(
    session: AsyncSession,
    user_id: uuid.UUID,
    level: int,
    *,
    family: str,
    keep_session_id: uuid.UUID | None = None,
    ended_by: uuid.UUID | None = None,
) -> tuple[int, uuid.UUID | None]:
    """Session effects of a restriction (RE §6.1, §7.4, §8). Returns (revoked, deferred_session).

    * L3 sharing: all *other* sessions revoked (``risk_L3``); a session holding an in-progress
      attempt is kept (deferral, max 3 h) and the triggering session (if any) stays in
      restricted scope.
    * L4: every session revoked (``admin_L4``) with the ``sessions_valid_after`` cut-off.
    * T-protect: every session revoked (``takeover_protect``), immediately, attempt or not.
    """
    await _clear_remember(session, user_id)
    if family == "takeover":
        n = await ss.revoke_all_sessions(session, user_id, "takeover_protect", ended_by=ended_by)
        return n, None
    if level >= 4:
        n = await ss.revoke_all_sessions(session, user_id, "admin_L4", ended_by=ended_by)
        return n, None
    if level == 3:
        active = await ss.active_sessions(session, user_id)
        held = await ss.sessions_with_attempts(session, [s.id for s in active])
        keep = set(held)
        if keep_session_id is not None:
            keep.add(keep_session_id)
        from app.modules.sessions import public as sp

        n = await sp.end_sessions(
            session, user_id, status="revoked", reason="risk_L3", ended_by=ended_by, except_ids=keep
        )
        return n, (next(iter(held)) if held else None)
    return 0, None


async def apply_restriction(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    level: int,
    family: str,
    source: str,
    actor: Principal | AuditActor,
    ends_at: datetime | None = None,
    case_id: uuid.UUID | None = None,
    applied_by: uuid.UUID | None = None,
    evaluation_id: uuid.UUID | None = None,
    hc_rule: str | None = None,
    ruleset_version: str | None = None,
    rule_keys: list[str] | None = None,
    reverify_device_ids: list[uuid.UUID] | None = None,
    keep_session_id: uuid.UUID | None = None,
    reason: str | None = None,
) -> tuple[AccountRestriction, int]:
    """Insert the new active restriction of ``family`` (the previous one is ``superseded``) and
    apply its session effects. Returns (restriction, sessions_revoked)."""
    now = clock.now()
    if _fs():
        fs_r: Any = await _apply_fs(
            session,
            now=now,
            user_id=user_id,
            level=level,
            family=family,
            source=source,
            actor=actor,
            ends_at=ends_at,
            case_id=case_id,
            applied_by=applied_by,
            evaluation_id=evaluation_id,
            hc_rule=hc_rule,
            ruleset_version=ruleset_version,
            rule_keys=rule_keys,
            reverify_device_ids=reverify_device_ids,
            keep_session_id=keep_session_id,
            reason=reason,
        )
        return fs_r
    prev = await active_for(session, user_id, family)
    if prev is not None:
        prev.ended_at = now
        prev.end_reason = "superseded"
        prev.ended_by = applied_by
        await session.flush()
    scope = "protect_lock" if family == "takeover" else SCOPE_FOR_LEVEL[level]
    r = AccountRestriction(
        id=uuid7(),
        created_at=clock.now(),
        user_id=user_id,
        level=level,
        family=family,
        scope=scope,
        source=source,
        starts_at=now,
        ends_at=ends_at,
        case_id=case_id,
        applied_by=applied_by,
        evaluation_id=evaluation_id,
        hc_rule=hc_rule,
        ruleset_version=ruleset_version,
        rule_keys=rule_keys or [],
        reverify_device_ids=reverify_device_ids or [],
    )
    session.add(r)
    await session.flush()
    revoked, deferred_session = 0, None
    if level >= 3 or family == "takeover":
        revoked, deferred_session = await revoke_for_level(
            session, user_id, level, family=family, keep_session_id=keep_session_id, ended_by=applied_by
        )
        if deferred_session is not None and family == "sharing" and level == 3:
            r.deferred_until = now + DEFER_MAX
    if family == "takeover":
        await ad.set_must_change_password(session, user_id, True)
    await recompute_cache(session, user_id)
    await audit(
        session,
        actor,
        "security.restriction.apply",
        "account_restriction",
        r.id,
        subject_user_id=user_id,
        reason=reason,
        after={
            "level": level,
            "family": family,
            "scope": scope,
            "source": source,
            "ends_at": to_rfc3339(ends_at) if ends_at else None,
            "deferred_until": to_rfc3339(r.deferred_until) if r.deferred_until else None,
            "hc_rule": hc_rule,
            "sessions_revoked": revoked,
        },
    )
    if level >= 3 or family == "takeover":
        await emit_event(
            session,
            "account.restricted",
            {"user_id": str(user_id), "level": level, "family": family, "restriction_id": str(r.id)},
            aggregate_type="account_restriction",
            aggregate_id=r.id,
        )
    return r, revoked


async def end_restriction(
    session: AsyncSession,
    r: AccountRestriction,
    reason: str,
    *,
    ended_by: uuid.UUID | None,
    decision_id: uuid.UUID | None = None,
    actor: Principal | AuditActor | None = None,
    reason_text: str | None = None,
) -> None:
    if r.ended_at is not None:
        return
    r.ended_at = clock.now()
    r.end_reason = reason
    r.ended_by = ended_by
    r.decision_id = decision_id or r.decision_id
    if _fs():
        await _repo().save_restriction(r.user_id, r)
    else:
        await session.flush()
    await recompute_cache(session, r.user_id)
    await audit(
        session,
        actor or AuditActor.system("security.restrictions"),
        "security.restriction.lift",
        "account_restriction",
        r.id,
        subject_user_id=r.user_id,
        reason=reason_text,
        after={"end_reason": reason, "level": r.level, "family": r.family},
    )
    if r.level >= 3 or r.family == "takeover":
        await emit_event(
            session,
            "restriction.lifted",
            {"user_id": str(r.user_id), "restriction_id": str(r.id), "end_reason": reason},
            aggregate_type="account_restriction",
            aggregate_id=r.id,
        )


def restriction_out(r: AccountRestriction, case_ref: str | None = None) -> dict[str, Any]:
    return {
        "restriction_id": str(r.id),
        "user_id": str(r.user_id),
        "level": r.level,
        "family": r.family,
        "scope": r.scope,
        "source": r.source,
        "hc_rule": r.hc_rule,
        "starts_at": to_rfc3339(r.starts_at),
        "ends_at": to_rfc3339(r.ends_at) if r.ends_at else None,
        "deferred_until": to_rfc3339(r.deferred_until) if r.deferred_until else None,
        "state": "ended" if r.ended_at else ("lift_pending" if r.lift_pending_at else "active"),
        "case_id": str(r.case_id) if r.case_id else None,
        "case_ref": case_ref,
        "ended_at": to_rfc3339(r.ended_at) if r.ended_at else None,
        "end_reason": r.end_reason,
    }


# --------------------------------------------------------------------------- Firestore paths
# (``TD_STORE_SECURITY=firestore``; data-ops agent). Rows live in Firestore; identity/sessions
# side effects go through ``security.adapters`` with the caller's session, as before.


async def _step_up_required_fs(session: AsyncSession, user_id: uuid.UUID) -> bool:
    repo = _repo()
    st = await repo.get_state(user_id)
    if st is None or st.step_up_required_since is None:
        return False
    if st.step_up_cleared_at is not None and st.step_up_cleared_at >= st.step_up_required_since:
        return False
    amr: list[str] = list(STEP_UP_AMR)
    if not await ad.user_contact_verified(session, user_id):
        amr.append("otp_email")
    if await ad.stepped_up_sessions_since(session, user_id, st.step_up_required_since, amr):
        st.step_up_cleared_at = clock.now()
        await repo.save_state(user_id, st)
        return False
    return True


async def _apply_fs(
    session: AsyncSession,
    *,
    now: datetime,
    user_id: uuid.UUID,
    level: int,
    family: str,
    source: str,
    actor: Principal | AuditActor,
    ends_at: datetime | None,
    case_id: uuid.UUID | None,
    applied_by: uuid.UUID | None,
    evaluation_id: uuid.UUID | None,
    hc_rule: str | None,
    ruleset_version: str | None,
    rule_keys: list[str] | None,
    reverify_device_ids: list[uuid.UUID] | None,
    keep_session_id: uuid.UUID | None,
    reason: str | None,
) -> tuple[Any, int]:
    """``apply_restriction`` on Firestore: supersede + insert is one transaction (one active row
    per user and family); session effects, the user cache, audit and the outbox event use the
    caller's session exactly as the Postgres path."""
    from app.modules.security.store_specs import RestrictionRow

    scope = "protect_lock" if family == "takeover" else SCOPE_FOR_LEVEL[level]
    repo = _repo()
    row = RestrictionRow(
        id=uuid7(),
        created_at=clock.now(),
        user_id=user_id,
        level=level,
        family=family,
        scope=scope,
        source=source,
        starts_at=now,
        ends_at=ends_at,
        evaluation_id=evaluation_id,
        case_id=case_id,
        applied_by=applied_by,
        hc_rule=hc_rule,
        ruleset_version=ruleset_version,
        rule_keys=rule_keys or [],
        reverify_device_ids=reverify_device_ids or [],
    )
    _prev, r = await repo.insert_restriction(user_id, row)
    revoked, deferred_session = 0, None
    if level >= 3 or family == "takeover":
        revoked, deferred_session = await revoke_for_level(
            session, user_id, level, family=family, keep_session_id=keep_session_id, ended_by=applied_by
        )
        if deferred_session is not None and family == "sharing" and level == 3:
            r.deferred_until = now + DEFER_MAX
            await repo.save_restriction(user_id, r)
    if family == "takeover":
        await ad.set_must_change_password(session, user_id, True)
    await recompute_cache(session, user_id)
    await audit(
        session,
        actor,
        "security.restriction.apply",
        "account_restriction",
        r.id,
        subject_user_id=user_id,
        reason=reason,
        after={
            "level": level,
            "family": family,
            "scope": scope,
            "source": source,
            "ends_at": to_rfc3339(ends_at) if ends_at else None,
            "deferred_until": to_rfc3339(r.deferred_until) if r.deferred_until else None,
            "hc_rule": hc_rule,
            "sessions_revoked": revoked,
        },
    )
    if level >= 3 or family == "takeover":
        await emit_event(
            session,
            "account.restricted",
            {"user_id": str(user_id), "level": level, "family": family, "restriction_id": str(r.id)},
            aggregate_type="account_restriction",
            aggregate_id=r.id,
        )
    return r, revoked
