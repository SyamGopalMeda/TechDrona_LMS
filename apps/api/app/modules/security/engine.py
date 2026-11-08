"""Risk engine orchestration (RE §5.2-§5.8, §6, §9): load versioned rules and policy, run the
pure scorer (``rules.py``), write explainable ``risk_evaluations`` and apply graduated actions.

Mode semantics (AMB-23): ``risk.mode`` (``off``/``shadow``/``enforce``) and the kill switch govern
the **sharing family only**. Takeover protections, deterministic caps and AB-*/IN-* always act.
Minors: no sharing signals, no evaluations of any family; takeover rules act deterministically.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

import structlog
from sqlalchemy import and_, func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import AuditActor, audit
from app.core.ids import uuid7
from app.core.outbox import emit_event
from app.core.principal import Principal
from app.modules.admin.policy import get_value
from app.modules.identity import clock
from app.modules.identity.models import User
from app.modules.security import restrictions as rx
from app.modules.security.catalogue import (
    BUILTIN_HC,
    BUILTIN_RULESETS,
    REPLAY_RULES,
    RULES_BY_KEY,
)
from app.modules.security.models import (
    AccountRestriction,
    CaseDecision,
    RiskEvaluation,
    RiskRule,
    RiskRuleVersion,
    SecurityCase,
    SecurityNotice,
    SecuritySignal,
)
from app.modules.security.policies import sharing_policy
from app.modules.security.refs import make_ref
from app.modules.security.rules import (
    SharingContext,
    Sig,
    hc01,
    hc02,
    score_sharing,
    score_takeover,
)
from app.modules.sessions.models import UserDevice

log = structlog.get_logger("app.security.engine")
SYSTEM = AuditActor.system("security.engine")
SYNC_TRIGGERS = frozenset({"login", "playback", "attempt", "rebind", "verification", "manual_review"})
CONFIRMED_OUTCOMES = ("uphold", "lift_with_warning", "lift_conditions", "convert_L4", "reduce_level")


# --------------------------------------------------------------------------- rules / versions


async def ruleset(session: AsyncSession, family: str) -> tuple[dict[str, Any], str]:
    row = (
        await session.execute(
            select(RiskRuleVersion).where(
                RiskRuleVersion.family == family,
                RiskRuleVersion.rule_id.is_(None),
                RiskRuleVersion.status == "active",
            )
        )
    ).scalar_one_or_none()
    base = dict(BUILTIN_RULESETS[family])
    if row is not None:
        merged = {**base, **row.definition}
        return merged, row.ruleset_version
    return base, str(base["ruleset_version"])


async def rule_version(session: AsyncSession, key: str) -> RiskRuleVersion | None:
    """Most relevant DB version of one rule: active, else latest shadow."""
    rows = (
        (
            await session.execute(
                select(RiskRuleVersion)
                .join(RiskRule, RiskRule.id == RiskRuleVersion.rule_id)
                .where(RiskRule.key == key, RiskRuleVersion.status.in_(("active", "shadow")))
                .order_by(RiskRuleVersion.created_at.desc())
            )
        )
        .scalars()
        .all()
    )
    for r in rows:
        if r.status == "active":
            return r
    return rows[0] if rows else None


async def rule_status(session: AsyncSession, key: str) -> tuple[str, dict[str, Any], str]:
    """(status, params, semver) for an HC rule: a DB version wins over the built-in."""
    v = await rule_version(session, key)
    if v is not None:
        return v.status, dict(v.definition.get("params", {})), v.semver
    b = BUILTIN_HC.get(key, {"status": "draft", "params": {}, "semver": "1.0.0"})
    return str(b["status"]), dict(b["params"]), str(b["semver"])


async def risk_mode(session: AsyncSession) -> str:
    return str(await get_value(session, "risk.mode"))


# --------------------------------------------------------------------------- signals


async def record_signal(
    session: AsyncSession,
    *,
    rule_key: str,
    user_id: uuid.UUID | None,
    source: str,
    evidence: dict[str, Any] | None = None,
    occurred_at: datetime | None = None,
    base_points: float | None = None,
    multipliers: dict[str, Any] | None = None,
    auth_session_id: uuid.UUID | None = None,
    device_id: uuid.UUID | None = None,
    user: User | None = None,
) -> SecuritySignal | None:
    """Write one ``security_signals`` row. Sharing signals are never written for minors or
    synthetic accounts (RE §4.4); takeover signals for minors carry 0 points."""
    rd = RULES_BY_KEY[rule_key]
    family = rd.family
    minor = False
    if user_id is not None:
        user = user or await session.get(User, user_id)
        minor = bool(user is None or user.is_minor)
        if family == "sharing" and (minor or (user is not None and user.is_synthetic)):
            return None
    if base_points is None:
        if family == "sharing":
            defn, _ = await ruleset(session, "sharing")
            base_points = float(defn["points"].get(rule_key, 0))
        elif family == "takeover":
            defn, _ = await ruleset(session, "takeover")
            base_points = float(defn["points"].get(rule_key, 0))
        else:
            base_points = 0.0
    if minor and family == "takeover":
        base_points = 0.0
    defn_family = family if family in BUILTIN_RULESETS else None
    version = None
    if defn_family:
        _, rv = await ruleset(session, defn_family)
        version = rv.rsplit("-", 1)[-1]
    sig = SecuritySignal(
        id=uuid7(),
        occurred_at=occurred_at or clock.now(),
        user_id=user_id,
        family=family,
        rule_key=rule_key,
        rule_version=version,
        category=rd.category if family == "sharing" else None,
        base_points=Decimal(str(round(base_points, 2))),
        multipliers=multipliers or {},
        evidence=evidence or {},
        source=source,
        auth_session_id=auth_session_id,
        device_id=device_id,
        is_minor_at_time=minor,
    )
    session.add(sig)
    await session.flush()
    return sig


def to_sig(s: SecuritySignal) -> Sig:
    return Sig(
        id=str(s.id),
        rule=s.rule_key,
        category=s.category,
        occurred_at=s.occurred_at,
        base_points=float(s.base_points),
        multipliers=dict(s.multipliers or {}),
        evidence=dict(s.evidence or {}),
        rule_version=s.rule_version,
    )


async def user_signals(
    session: AsyncSession, user_id: uuid.UUID, family: str, since: datetime, until: datetime | None = None
) -> list[SecuritySignal]:
    q = select(SecuritySignal).where(
        SecuritySignal.user_id == user_id,
        SecuritySignal.family == family,
        SecuritySignal.occurred_at > since,
        SecuritySignal.suppressed_by_decision_id.is_(None),
    )
    if until is not None:
        q = q.where(SecuritySignal.occurred_at <= until)
    return list((await session.execute(q.order_by(SecuritySignal.occurred_at))).scalars())


async def has_monitoring_consent(session: AsyncSession, user_id: uuid.UUID) -> bool:
    from app.modules.identity.service import current_consents

    state = await current_consents(session, user_id)
    return state.get("security_monitoring", {}).get("state") == "granted"


async def primary_org(session: AsyncSession, user_id: uuid.UUID) -> uuid.UUID | None:
    from app.modules.orgs.models import OrgMembership

    return (
        await session.execute(
            select(OrgMembership.organization_id)
            .where(OrgMembership.user_id == user_id, OrgMembership.status == "active")
            .order_by(OrgMembership.organization_id)
            .limit(1)
        )
    ).scalar_one_or_none()


# --------------------------------------------------------------------------- cases


async def sla_hours(session: AsyncSession, family: str, level: int) -> tuple[int, int]:
    first = await get_value(session, "unblock.sla.first_response_hours")
    dec = await get_value(session, "unblock.sla.decision_hours")
    key = "takeover" if family == "takeover" else ("L4" if level >= 4 else "L3")
    return int(first.get(key, 24)), int(dec.get(key, 72))


async def confirmed_incidents(session: AsyncSession, user_id: uuid.UUID, days: int) -> int:
    since = clock.now() - timedelta(days=days)
    return int(
        (
            await session.execute(
                select(func.count())
                .select_from(CaseDecision)
                .join(SecurityCase, SecurityCase.id == CaseDecision.case_id)
                .where(
                    SecurityCase.user_id == user_id,
                    SecurityCase.family == "sharing",
                    CaseDecision.outcome.in_(CONFIRMED_OUTCOMES),
                    CaseDecision.created_at > since,
                )
            )
        ).scalar_one()
    )


async def high_risk_reasons(session: AsyncSession, user_id: uuid.UUID) -> list[str]:
    """UNB §5 rule 1: reseller pattern, repeat incident, staff role, device graph."""
    from app.modules.rbac.service import active_grants

    reasons: list[str] = []
    since = clock.now() - timedelta(days=30)
    rules = set(
        (
            await session.execute(
                select(SecuritySignal.rule_key).where(
                    SecuritySignal.user_id == user_id,
                    SecuritySignal.occurred_at > since,
                    SecuritySignal.suppressed_by_decision_id.is_(None),
                )
            )
        ).scalars()
    )
    if {"SH-09", "SH-11", "SH-06"} <= rules:
        reasons.append("reseller_pattern")
    if await confirmed_incidents(session, user_id, 180) >= 2:
        reasons.append("repeat_incident")
    if any(g.role != "student" for g in await active_grants(session, user_id)):
        reasons.append("staff_account")
    return reasons


async def open_case(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    family: str,
    level: int,
    opened_reason: str,
    priority: str = "medium",
    hc_rule: str | None = None,
    recommended_level: int | None = None,
    actor: Principal | AuditActor = SYSTEM,
) -> SecurityCase:
    existing = (
        await session.execute(
            select(SecurityCase)
            .where(
                SecurityCase.user_id == user_id,
                SecurityCase.family == family,
                SecurityCase.status != "closed",
            )
            .order_by(SecurityCase.created_at.desc())
            .limit(1)
            .with_for_update()
        )
    ).scalar_one_or_none()
    now = clock.now()
    first_h, dec_h = await sla_hours(session, family, level)
    reasons = await high_risk_reasons(session, user_id)
    repeats = await confirmed_incidents(session, user_id, 180)
    if existing is not None:
        existing.level = max(existing.level, level)
        if recommended_level:
            existing.recommended_level = recommended_level
        if priority == "high" and existing.priority in ("low", "medium"):
            existing.priority = "high"
        existing.hc_rule = existing.hc_rule or hc_rule
        existing.is_high_risk = existing.is_high_risk or bool(reasons)
        existing.high_risk_reasons = sorted(set(existing.high_risk_reasons) | set(reasons))
        existing.version += 1
        await session.flush()
        return existing
    case = SecurityCase(
        id=uuid7(),
        created_at=clock.now(),
        case_ref=make_ref("SEC"),
        user_id=user_id,
        organization_id=await primary_org(session, user_id),
        family=family,
        level=level,
        recommended_level=recommended_level,
        priority=priority,
        status="open",
        opened_reason=opened_reason,
        is_high_risk=bool(reasons),
        high_risk_reasons=reasons,
        repeat_count=repeats,
        hc_rule=hc_rule,
        sla_first_response_due=now + timedelta(hours=first_h),
        sla_decision_due=now + timedelta(hours=dec_h),
        panel_views={},
        version=1,
    )
    session.add(case)
    await session.flush()
    await audit(
        session,
        actor,
        "case.opened",
        "security_case",
        case.id,
        subject_user_id=user_id,
        after={
            "case_ref": case.case_ref,
            "level": level,
            "opened_reason": opened_reason,
            "priority": priority,
        },
    )
    return case


async def notify_user(
    session: AsyncSession,
    user_id: uuid.UUID,
    template_key: str,
    *,
    subject: str,
    text_body: str,
    data: dict[str, Any] | None = None,
    sms: bool = False,
    dedupe_key: str | None = None,
) -> None:
    from app.modules.notifications.service import notify, send_sms

    user = await session.get(User, user_id)
    if user is None:
        return
    await notify(
        session,
        user_id,
        template_key,
        category="security",
        data=data or {},
        channels=("in_app", "email") if user.email else ("in_app",),
        priority="high",
        is_minor=user.is_minor,
        email_to=user.email,
        email_subject=subject,
        email_text=text_body,
        dedupe_key=dedupe_key,
    )
    if sms and user.phone_e164 and user.phone_verified_at:
        await send_sms(user.phone_e164, f"Tech Drona: {subject}", template_key=template_key)


# --------------------------------------------------------------------------- sharing


async def sharing_context(
    session: AsyncSession, user_id: uuid.UUID, now: datetime
) -> tuple[SharingContext, Any]:
    st = await rx.get_state(session, user_id)
    devs = (
        await session.execute(
            select(UserDevice.device_id, UserDevice.owner_verified_at).where(UserDevice.user_id == user_id)
        )
    ).all()
    verified = {str(d): ts for d, ts in devs}
    tainted = {
        str(d)
        for d in (
            await session.execute(
                select(SecuritySignal.device_id).where(
                    SecuritySignal.user_id == user_id,
                    SecuritySignal.rule_key == "SH-13",
                    SecuritySignal.occurred_at > now - timedelta(days=30),
                    SecuritySignal.suppressed_by_decision_id.is_(None),
                )
            )
        ).scalars()
        if d
    }
    active = await rx.active_for(session, user_id, "sharing")
    current = active.level if active is not None else 0
    repeat_days = int(await get_value(session, "risk.repeat_window_days"))
    repeat = await confirmed_incidents(session, user_id, repeat_days) > 0
    ctx = SharingContext(
        owner_verified_at=verified,
        sh13_tainted=frozenset(tainted),
        current_level=current,
        l2_issued_at=st.l2_issued_at,
        l2_passed_at=st.l2_passed_at,
        repeat=repeat,
    )
    return ctx, st


async def _hc_exclusions(session: AsyncSession, user: User, s3: list[Sig]) -> list[str]:
    """HC-01 conditions (3)-(5) plus consent: reasons the rule may not fire."""
    from app.modules.admin.models import PolicySetting

    out: list[str] = []
    if user.is_synthetic:
        out.append("synthetic")
    if not await has_monitoring_consent(session, user.id):
        out.append("no_security_monitoring_consent")
    now = clock.now()
    exc = (
        await session.execute(
            select(func.count())
            .select_from(PolicySetting)
            .where(
                PolicySetting.scope_type == "user",
                PolicySetting.scope_id == user.id,
                PolicySetting.is_active.is_(True),
                PolicySetting.expires_at > now,
            )
        )
    ).scalar_one()
    if exc:
        out.append("user_exception")
    fp = (
        await session.execute(
            select(func.count())
            .select_from(CaseDecision)
            .join(SecurityCase, SecurityCase.id == CaseDecision.case_id)
            .where(
                SecurityCase.user_id == user.id,
                SecurityCase.family == "sharing",
                CaseDecision.outcome == "lift_false_positive",
                CaseDecision.created_at > now - timedelta(days=30),
            )
        )
    ).scalar_one()
    if fp:
        out.append("recent_false_positive_lift")
    return out


async def _hc_daily_ok(session: AsyncSession, rule: str) -> bool:
    """RE §5.7 (b): checked before applying, under a per-rule advisory lock."""
    await session.execute(text("SELECT pg_advisory_xact_lock(hashtext('hc:' || :r))"), {"r": rule})
    limit = int(await get_value(session, "risk.hc.circuit_breaker.max_daily_restrictions"))
    n = (
        await session.execute(
            select(func.count())
            .select_from(AccountRestriction)
            .where(
                AccountRestriction.hc_rule == rule,
                AccountRestriction.created_at > clock.now() - timedelta(hours=24),
            )
        )
    ).scalar_one()
    return int(n) < limit


async def trip_breaker(session: AsyncSession, rule: str, reason: str) -> bool:
    """Move the rule's active version to shadow (system actor, ``circuit_breaker``) and alert."""
    v = await rule_version(session, rule)
    if v is None or v.status != "active":
        return False
    v.status = "shadow"
    v.status_changed_at = clock.now()
    v.status_changed_by = None
    v.status_change_reason = "circuit_breaker"
    await session.execute(update(RiskRule).where(RiskRule.key == rule).values(active_version_id=None))
    await session.flush()
    await audit(
        session,
        SYSTEM,
        "security.rule.circuit_breaker",
        "risk_rule_version",
        v.id,
        after={"rule": rule, "reason": reason},
    )
    await emit_event(
        session,
        "security.alert_raised",
        {"kind": "circuit_breaker", "rule": rule, "reason": reason, "route": "security_lead"},
        aggregate_type="risk_rule_version",
        aggregate_id=v.id,
    )
    return True


async def check_fp_breaker(session: AsyncSession, rule: str) -> bool:
    """RE §5.7 (a): trips when FP lifts among the last ``min_decisions`` decided HC-applied
    restrictions exceed ``max_fp_rate x min_decisions`` (absolute threshold)."""
    rate = float(await get_value(session, "risk.hc.circuit_breaker.max_fp_rate"))
    n = int(await get_value(session, "risk.hc.circuit_breaker.min_decisions"))
    hc_cases = select(AccountRestriction.case_id).where(AccountRestriction.hc_rule == rule)
    rows = (
        (
            await session.execute(
                select(CaseDecision.outcome)
                .where(CaseDecision.case_id.in_(hc_cases))
                .order_by(CaseDecision.created_at.desc())
                .limit(n)
            )
        )
        .scalars()
        .all()
    )
    fps = sum(1 for o in rows if o == "lift_false_positive")
    if fps > rate * n + 1e-9:
        return await trip_breaker(session, rule, f"false_positive_rate:{fps}/{len(rows)}")
    return False


async def evaluate_sharing(
    session: AsyncSession,
    user_id: uuid.UUID,
    *,
    trigger: str,
    now: datetime | None = None,
    keep_session_id: uuid.UUID | None = None,
) -> RiskEvaluation | None:
    now = now or clock.now()
    user = await session.get(User, user_id)
    if user is None or user.is_minor or user.is_synthetic:
        return None  # RE §4.4: nothing is computed or written for minors
    mode = await risk_mode(session)
    if mode == "off":
        return None
    policy = await sharing_policy(session, user_id)
    definition, rs_version = await ruleset(session, "sharing")
    rows = await user_signals(session, user_id, "sharing", now - timedelta(days=policy.window_days), now)
    sigs = [to_sig(r) for r in rows]
    ctx, st = await sharing_context(session, user_id, now)
    result = score_sharing(sigs, now, policy, ctx, {k: float(v) for k, v in definition["caps"].items()})
    level_before = ctx.current_level
    gates = dict(result.gates)
    action = result.action
    level_after = result.level_after
    eval_mode = "enforce" if mode == "enforce" else "shadow"
    org = await primary_org(session, user_id)
    prev_score = float(st.sharing_score)

    def _row(
        mode_: str, action_: str, lvl_after: int, gates_: dict[str, Any], keys: list[str]
    ) -> RiskEvaluation:
        return RiskEvaluation(
            id=uuid7(),
            evaluated_at=now,
            user_id=user_id,
            organization_id=org,
            family="sharing",
            mode=mode_,
            ruleset_version=rs_version,
            trigger=trigger,
            window={
                "from": (now - timedelta(days=policy.window_days)).isoformat(),
                "to": now.isoformat(),
                "half_life_days": policy.half_life_days,
            },
            signals=result.contributions,
            subtotals=result.subtotals,
            repeat_multiplier=Decimal(str(result.repeat_multiplier)),
            score=Decimal(str(result.score)),
            previous_score=Decimal(str(prev_score)),
            level_before=level_before,
            level_after=min(lvl_after, 3) if level_before < 4 else level_before,
            gates=gates_,
            action=action_,
            explanation_keys=keys + [k for k in result.explanation_keys if k not in keys],
            auth_session_id=keep_session_id,
            is_minor_at_time=False,
        )

    # High-confidence rules (RE §5.6): evaluated when S3 overlaps exist. A match that may not be
    # acted on (switch off, rule in shadow, risk.mode not enforce, daily limit) is written as a
    # separate ``mode = shadow`` row and the account continues on the scored path.
    hc_applied: str | None = None
    s3 = [s for s in sigs if s.rule == "SH-01" and s.multipliers.get("separation_class") == "S3"]
    if s3 and level_before < 3:
        for rule, fn in (("HC-02", hc02), ("HC-01", hc01)):
            status, params, _semver = await rule_status(session, rule)
            info = fn(s3, now, params or BUILTIN_HC[rule]["params"], ctx.l2_issued_at)
            if not info["met"]:
                continue
            excl = await _hc_exclusions(session, user, s3)
            if excl:
                gates.setdefault("hc_excluded", {})[rule] = excl
                continue
            hc_gates = {**gates, "hc_rule": rule, "hc": info}
            key = RULES_BY_KEY[rule].explanation_key
            master = bool(await get_value(session, "risk.hc.auto_restrict_enabled"))
            if status == "active" and master and mode == "enforce":
                if await _hc_daily_ok(session, rule):
                    hc_applied = rule
                    gates = hc_gates
                    action, level_after = "restrict_L3", 3
                    result.explanation_keys = [key, *result.explanation_keys]
                    break
                await trip_breaker(session, rule, "tripped_daily_limit")
                hc_gates["breaker"] = "tripped_daily_limit"
            session.add(_row("shadow", "restrict_L3", 3, hc_gates, [key]))
            await session.flush()
            break

    changed = level_after != level_before or abs(result.score - prev_score) >= 5
    write = changed or trigger in SYNC_TRIGGERS or action != "none"
    ev: RiskEvaluation | None = None
    if write:
        ev = _row(eval_mode, action, level_after, gates, [])
    st.sharing_score = Decimal(str(result.score))
    st.last_evaluated_at = now
    if eval_mode == "enforce" and ev is not None and action != "none":
        # The action fills restriction_id / case_id before the append-only row is inserted.
        await _apply_sharing_action(
            session, user, ev, action, level_before, level_after, result, hc_applied, keep_session_id
        )
        st.sharing_level = level_after
    if ev is not None:
        session.add(ev)
    await session.flush()
    return ev


async def _apply_sharing_action(
    session: AsyncSession,
    user: User,
    ev: RiskEvaluation,
    action: str,
    level_before: int,
    level_after: int,
    result: Any,
    hc_rule: str | None,
    keep_session_id: uuid.UUID | None,
) -> None:
    now = clock.now()
    rule_keys = sorted({c["rule"] for c in result.contributions if c["decayed_points"] > 0})
    if action == "notice_L1":
        r, _ = await rx.apply_restriction(
            session,
            user_id=user.id,
            level=1,
            family="sharing",
            source="engine",
            actor=SYSTEM,
            evaluation_id=ev.id,
            ruleset_version=ev.ruleset_version,
            rule_keys=rule_keys,
        )
        ev.restriction_id = r.id
        await notify_user(
            session,
            user.id,
            "security.l1_notice",
            subject="New activity on your account",
            text_body="We noticed your account being used on several devices recently. If these are "
            "all yours, you don't need to do anything. If you don't recognise one, sign it out "
            "and change your password.",
            data={"explanation_keys": ev.explanation_keys},
        )
    elif action == "require_otp_L2":
        devices = sorted(
            {
                d
                for c in result.contributions
                if c["decayed_points"] > 0 and c["rule"] in ("SH-01", "SH-13")
                for d in (
                    c["evidence"].get("device_a"),
                    c["evidence"].get("device_b"),
                    c["evidence"].get("device"),
                )
                if d
            }
        )
        r, _ = await rx.apply_restriction(
            session,
            user_id=user.id,
            level=2,
            family="sharing",
            source="engine",
            actor=SYSTEM,
            evaluation_id=ev.id,
            ruleset_version=ev.ruleset_version,
            rule_keys=rule_keys,
            reverify_device_ids=[uuid.UUID(d) for d in devices],
        )
        ev.restriction_id = r.id
        st = await rx.get_state(session, user.id)
        st.l2_issued_at = now
        await notify_user(
            session,
            user.id,
            "security.l2_verify",
            subject="Confirm it's you",
            text_body="To keep your account and your test results yours, we need to confirm your "
            "devices belong to you. Sign in and confirm with a code sent to your registered phone.",
            data={"explanation_keys": ev.explanation_keys},
            sms=True,
        )
    elif action == "restrict_L3":
        repeat = await confirmed_incidents(
            session, user.id, int(await get_value(session, "risk.repeat_window_days"))
        )
        durations = list(await get_value(session, "risk.L3.duration_hours"))
        hours = durations[1] if repeat and len(durations) > 1 else durations[0]
        reseller = bool(result.gates.get("reseller_pattern"))
        case = await open_case(
            session,
            user_id=user.id,
            family="sharing",
            level=3,
            opened_reason="engine_hc_L3" if hc_rule else "engine_L3",
            priority="high" if hc_rule == "HC-02" or reseller else "medium",
            hc_rule=hc_rule,
        )
        r, _ = await rx.apply_restriction(
            session,
            user_id=user.id,
            level=3,
            family="sharing",
            source="engine",
            actor=SYSTEM,
            ends_at=now + timedelta(hours=int(hours)),
            case_id=case.id,
            evaluation_id=ev.id,
            hc_rule=hc_rule,
            ruleset_version=ev.ruleset_version,
            rule_keys=rule_keys,
            keep_session_id=keep_session_id,
        )
        ev.restriction_id, ev.case_id = r.id, case.id
        await notify_user(
            session,
            user.id,
            "security.l3_restricted",
            subject="Learning access paused",
            text_body=f"Our account-protection system paused video lessons, tests and practice on "
            f"your account for {hours} hours. Case reference: {case.case_ref}. If you think this "
            "is a mistake, sign in and request a review.",
            data={"case_ref": case.case_ref, "explanation_keys": ev.explanation_keys},
        )
        if result.gates.get("l4_recommend"):
            ev.action = "restrict_L3"
            case.recommended_level = 4
            case.priority = "high"
    elif action == "recommend_L4":
        case = await open_case(
            session,
            user_id=user.id,
            family="sharing",
            level=level_before,
            opened_reason="engine_recommend_L4",
            priority="high",
            recommended_level=4,
        )
        ev.case_id = case.id
    elif action == "deescalate":
        cur = await rx.active_for(session, user.id, "sharing")
        if cur is not None and cur.level < 3:
            await rx.end_restriction(session, cur, "deescalated", ended_by=None)
            if level_after > 0:
                r, _ = await rx.apply_restriction(
                    session,
                    user_id=user.id,
                    level=level_after,
                    family="sharing",
                    source="engine",
                    actor=SYSTEM,
                    evaluation_id=ev.id,
                    ruleset_version=ev.ruleset_version,
                    rule_keys=rule_keys,
                )
                ev.restriction_id = r.id
    await session.flush()


# --------------------------------------------------------------------------- takeover


async def protect_lock(
    session: AsyncSession, user: User, rule: str, *, actor: Principal | AuditActor = SYSTEM
) -> AccountRestriction:
    """T-protect (RE §6.2): revoke all sessions, must_change_password, remember-device off,
    email + SMS. Self-service recovery (OTP + password reset) ends it."""
    existing = await rx.active_for(session, user.id, "takeover")
    if existing is not None and existing.scope == "protect_lock":
        return existing
    r, _ = await rx.apply_restriction(
        session,
        user_id=user.id,
        level=3,
        family="takeover",
        source="engine",
        actor=actor,
        hc_rule=rule if rule.startswith("HC-T") else None,
        rule_keys=[rule],
    )
    ref = make_ref("ACC")
    session.add(
        SecurityNotice(
            id=uuid7(), created_at=clock.now(), event_ref=ref, user_id=user.id, kind="replay", rule_key=rule
        )
    )
    await notify_user(
        session,
        user.id,
        "security.takeover_protect",
        subject="We've secured your account",
        text_body=f"We noticed sign-in activity that may not have been you, so we've signed out all "
        f"devices to protect your account. Reference: {ref}. To continue, verify with a code and "
        "choose a new password.",
        data={"event_ref": ref, "rule": rule},
        sms=True,
    )
    return r


async def evaluate_takeover(
    session: AsyncSession, user_id: uuid.UUID, *, trigger: str, auth_session_id: uuid.UUID | None = None
) -> RiskEvaluation | None:
    """Adults: score with thresholds T-step-up ≥ 40, T-protect ≥ 70. HC-T rules for everyone.
    Minors: deterministic rules only, no evaluation rows (RE §4.4)."""
    now = clock.now()
    user = await session.get(User, user_id)
    if user is None:
        return None
    definition, rs_version = await ruleset(session, "takeover")
    sigs_rows = await user_signals(session, user_id, "takeover", now - timedelta(days=30), now)
    hc = await _hc_takeover(session, user, sigs_rows, now)
    if user.is_minor:
        if hc:
            await protect_lock(session, user, hc)
        return None
    window = int(await get_value(session, "risk.window_days"))
    half = float(await get_value(session, "risk.decay_half_life_days"))
    score, contrib = score_takeover(
        [to_sig(s) for s in sigs_rows],
        now,
        window,
        half,
        {k: float(v) for k, v in definition["points"].items()},
    )
    st = await rx.get_state(session, user_id)
    th = definition.get("thresholds", {"step_up": 40, "protect": 70})
    action = "none"
    if hc or score >= float(th["protect"]):
        action = "protect_lock"
    elif score >= float(th["step_up"]):
        active_step = st.step_up_required_since is not None and (
            st.step_up_cleared_at is None or st.step_up_cleared_at < st.step_up_required_since
        )
        if not active_step or trigger in ("login",):
            action = "step_up"
    prev = float(st.takeover_score)
    ev = RiskEvaluation(
        id=uuid7(),
        evaluated_at=now,
        user_id=user_id,
        organization_id=await primary_org(session, user_id),
        family="takeover",
        mode="enforce",
        ruleset_version=rs_version,
        trigger=trigger,
        window={
            "from": (now - timedelta(days=window)).isoformat(),
            "to": now.isoformat(),
            "half_life_days": half,
        },
        signals=contrib,
        subtotals={"T": score},
        repeat_multiplier=Decimal("1.00"),
        score=Decimal(str(score)),
        previous_score=Decimal(str(prev)),
        level_before=0,
        level_after=0,
        gates={"hc_rule": hc, "step_up_threshold": th["step_up"], "protect_threshold": th["protect"]},
        action=action,
        explanation_keys=sorted({RULES_BY_KEY[c["rule"]].explanation_key for c in contrib}),
        auth_session_id=auth_session_id,
        is_minor_at_time=False,
    )
    st.takeover_score = Decimal(str(score))
    if action == "protect_lock":
        r = await protect_lock(session, user, hc or "TO-score")
        ev.restriction_id = r.id
    elif action == "step_up":
        st.step_up_required_since = now
        await notify_user(
            session,
            user_id,
            "security.step_up",
            subject="Was this you?",
            text_body="We noticed unusual sign-in activity. The next time you sign in or change "
            "important settings we'll ask you to confirm it's you. If this wasn't you, secure "
            "your account.",
            dedupe_key=f"stepup:{now:%Y%m%d%H}",
        )
    session.add(ev)
    await session.flush()
    return ev


async def _hc_takeover(
    session: AsyncSession, user: User, sigs: list[SecuritySignal], now: datetime
) -> str | None:
    """HC-T2 / HC-T3 and the minors' TO-03 lock-after-3 (RE §4.4, §5.6). HC-T1 needs the
    breached-password check (TO-02), which is Planned."""
    day = now - timedelta(hours=24)
    hour = now - timedelta(hours=1)
    replays = [s for s in sigs if s.rule_key in REPLAY_RULES and s.occurred_at > day]
    if replays:
        status, _, _ = await rule_status(session, "HC-T3")
        if status == "active":
            confirming = len(replays) >= 2 or any(
                s.rule_key in ("TO-06", "TO-02", "TO-03") and s.occurred_at > day for s in sigs
            )
            if confirming:
                return "HC-T3"
    t2_status, _, _ = await rule_status(session, "HC-T2")
    if t2_status == "active":
        to05 = any(s.rule_key == "TO-05" and s.occurred_at > hour for s in sigs)
        to03 = any(s.rule_key == "TO-03" and s.occurred_at > hour for s in sigs)
        ab03 = (
            await session.execute(
                select(func.count())
                .select_from(SecuritySignal)
                .where(
                    SecuritySignal.user_id == user.id,
                    SecuritySignal.rule_key == "AB-03",
                    SecuritySignal.occurred_at > hour,
                )
            )
        ).scalar_one()
        if to05 and (to03 or ab03):
            return "HC-T2"
    if user.is_minor:
        n = sum(1 for s in sigs if s.rule_key == "TO-03" and s.occurred_at > hour)
        definition, _ = await ruleset(session, "takeover")
        if n >= int(definition["params"].get("minor_to03_lock", 3)):
            return "TO-03"
    return None


async def disown(session: AsyncSession, user: User, notice: SecurityNotice) -> AccountRestriction:
    """SEC-46 "This wasn't me" → HC-T3 → T-protect."""
    notice.disowned_at = clock.now()
    await record_signal(
        session,
        rule_key="HC-T3",
        user_id=user.id,
        source="system",
        evidence={"event_ref": notice.event_ref, "trigger": "disowned"},
        base_points=0.0,
        user=user,
    )
    r = await protect_lock(session, user, "HC-T3")
    if not user.is_minor:
        ev = RiskEvaluation(
            id=uuid7(),
            evaluated_at=clock.now(),
            user_id=user.id,
            family="takeover",
            mode="enforce",
            ruleset_version=(await ruleset(session, "takeover"))[1],
            trigger="manual_review",
            window={},
            signals=[],
            subtotals={},
            score=Decimal("0"),
            level_before=0,
            level_after=0,
            gates={"hc_rule": "HC-T3", "trigger": "owner_disowned"},
            action="protect_lock",
            restriction_id=r.id,
            explanation_keys=["hct3.replay"],
            is_minor_at_time=False,
        )
        session.add(ev)
        await session.flush()
    return r


async def evaluations_for(
    session: AsyncSession,
    user_id: uuid.UUID,
    family: str | None,
    since: datetime | None,
    until: datetime | None,
) -> list[RiskEvaluation]:
    conds: list[Any] = [RiskEvaluation.user_id == user_id]
    if family:
        conds.append(RiskEvaluation.family == family)
    if since:
        conds.append(RiskEvaluation.evaluated_at >= since)
    if until:
        conds.append(RiskEvaluation.evaluated_at <= until)
    return list(
        (
            await session.execute(
                select(RiskEvaluation)
                .where(and_(*conds))
                .order_by(RiskEvaluation.evaluated_at.desc())
                .limit(200)
            )
        ).scalars()
    )
