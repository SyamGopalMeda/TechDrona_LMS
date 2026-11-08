"""Section H reports H1-H12 + ENG (RE §10; API SEC-30..32).

Access: ``security.case.read`` @P for every report; reports with per-user rows also need
``security.evidence.read`` and a ``reason_code`` (single company, D2: Admin holds both).
Aggregate cells below ``analytics.k_min.cohort`` are suppressed. Every view is audited
(source-req §H; ADM-10). Exports: CSV, watermarked; every export of a per-user report needs a
second, different admin (ADM-01, D2), and aggregate exports never carry identifying columns.

Period filters (ADM-06/09): ``from`` / ``to`` accept an ISO date (IST calendar day; ``to`` is
inclusive) or an ISO date-time (naive = IST). Per-report filters are listed in ``REPORTS``.
"""

from __future__ import annotations

import csv
import io
import itertools
import statistics
import uuid
from collections import defaultdict
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ProblemError
from app.core.time import to_rfc3339
from app.modules.admin.policy import get_value
from app.modules.identity import clock
from app.modules.security.models import (
    AccountRestriction,
    CaseDecision,
    RiskEvaluation,
    SecurityCase,
    SecurityReportExport,
    SecuritySignal,
    SecurityUserState,
    UnblockRequest,
)
from app.modules.sessions.models import AuthSession, LoginAttempt, SessionNetworkObservation, UserDevice

REPORTS: dict[str, dict[str, Any]] = {
    "top-suspicious-accounts": {
        "id": "H1",
        "title": "Top suspicious accounts",
        "per_user": True,
        "filters": ["level", "family", "rule", "sla_state", "assignee"],
    },
    "account-device-associations": {
        "id": "H2",
        "title": "Multiple-account/device associations",
        "per_user": True,
        "filters": ["min_accounts", "days"],
    },
    "concurrent-login-events": {
        "id": "H3",
        "title": "Concurrent login events",
        "per_user": True,
        "filters": ["from", "to", "user_id", "rule"],
    },
    "repeated-network-device-associations": {
        "id": "H4",
        "title": "Repeated IP/device associations",
        "per_user": False,
        "filters": ["from", "to"],
    },
    "blocked-accounts": {
        "id": "H5",
        "title": "Blocked accounts",
        "per_user": True,
        "filters": ["level", "family", "source"],
    },
    "pending-unblock-requests": {
        "id": "H6",
        "title": "Pending unblock requests",
        "per_user": True,
        "filters": ["level", "state"],
    },
    "average-review-time": {
        "id": "H7",
        "title": "Average review time",
        "per_user": False,
        "filters": ["from", "to", "level", "reviewer"],
    },
    "false-positive-rate": {
        "id": "H8",
        "title": "False-positive rate",
        "per_user": False,
        "filters": ["from", "to"],
    },
    "repeat-incidents": {"id": "H9", "title": "Repeat incidents", "per_user": True, "filters": []},
    "active-session-counts": {
        "id": "H10",
        "title": "Active-session counts",
        "per_user": False,
        "filters": ["tier", "client_type"],
    },
    "learning-activity": {
        "id": "H11",
        "title": "Daily/weekly/monthly learning activity",
        "per_user": False,
        "filters": ["from", "to", "granularity"],
    },
    "device-login-history": {
        "id": "H12",
        "title": "Device and login history",
        "per_user": True,
        "filters": ["from", "to", "user_id"],
    },
    "engine-health": {"id": "ENG", "title": "Policy and engine health", "per_user": False, "filters": []},
}
SECURITY_EXPORT_KEYS = frozenset(
    k
    for k, v in REPORTS.items()
    if v["id"] in ("H1", "H2", "H3", "H4", "H5", "H6", "H7", "H8", "H9", "H12", "ENG")
)
IST = ZoneInfo("Asia/Kolkata")
# Columns that identify a person, a device or a case. Aggregate exports never carry them (ADM-01).
IDENTIFYING_COLUMNS = frozenset(
    {"user_id", "case_ref", "assignee", "reference", "device_id", "session_id", "auth_session_id"}
)
H3_MAX_DAYS = 14


def _iso(v: datetime | None) -> str | None:
    return to_rfc3339(v) if v else None


async def _k(session: AsyncSession) -> int:
    return int(await get_value(session, "analytics.k_min.cohort"))


def _bad(field: str, message: str) -> ProblemError:
    return ProblemError(
        "validation_failed", 422, errors=[{"field": field, "code": "invalid", "message": message}]
    )


def parse_instant(value: str, field: str, *, end_of_day: bool = False) -> datetime:
    """ADM-09: a value with an offset keeps it; a naive date-time or a bare date is IST (the
    reports' timezone). A bare ``to`` date is inclusive (the end of that IST day)."""
    try:
        if len(value) == 10:
            d = date.fromisoformat(value)
            dt = datetime.combine(d + timedelta(days=1) if end_of_day else d, time(), IST)
        else:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=IST)
    except ValueError as e:
        raise _bad(field, "Use an ISO 8601 date or date-time") from e
    return dt.astimezone(UTC)


def _uuid_filter(f: dict[str, Any], key: str) -> uuid.UUID | None:
    v = f.get(key)
    if v in (None, ""):
        return None
    try:
        return uuid.UUID(str(v))
    except ValueError as e:
        raise _bad(key, "Must be a UUID") from e


def _int_filter(f: dict[str, Any], key: str) -> int | None:
    v = f.get(key)
    if v in (None, ""):
        return None
    try:
        return int(v)
    except (TypeError, ValueError) as e:
        raise _bad(key, "Must be an integer") from e


def _str_filter(f: dict[str, Any], key: str) -> str | None:
    v = f.get(key)
    return None if v in (None, "") else str(v)


def validate_filters(key: str, f: dict[str, Any]) -> None:
    """Cheap up-front validation so an export never waits for approval with bad filters."""
    for name in ("from", "to"):
        if f.get(name):
            parse_instant(str(f[name]), name, end_of_day=name == "to")
    for name in ("user_id", "assignee", "reviewer"):
        _uuid_filter(f, name)
    if key == "device-login-history" and not f.get("user_id"):
        raise ProblemError(
            "validation_failed",
            422,
            errors=[{"field": "user_id", "code": "required", "message": "H12 needs a user_id filter"}],
        )


async def run_report(session: AsyncSession, key: str, filters: dict[str, Any]) -> dict[str, Any]:
    now = clock.now()
    frm, to = filters.get("from"), filters.get("to")
    since = parse_instant(str(frm), "from") if frm else now - timedelta(days=30)
    until = min(parse_instant(str(to), "to", end_of_day=True), now) if to else now
    if until < since:
        raise _bad("to", "'to' is before 'from'")
    fn = _RUNNERS[key]
    rows, extra = await fn(session, filters, since, until)
    return {
        "report_key": key,
        "report_id": REPORTS[key]["id"],
        "title": REPORTS[key]["title"],
        "generated_at": to_rfc3339(now),
        "period": {"from": to_rfc3339(since), "to": to_rfc3339(until), "timezone": "Asia/Kolkata"},
        "filters_applied": {k: v for k, v in filters.items() if k in REPORTS[key]["filters"]},
        "rows": rows,
        **extra,
    }


async def _h1(
    session: AsyncSession, f: dict[str, Any], since: datetime, now: datetime
) -> tuple[list[Any], dict[str, Any]]:
    from app.modules.security.cases import sla_state

    q = select(SecurityCase).where(SecurityCase.status != "closed")
    if (lvl := _int_filter(f, "level")) is not None:
        q = q.where(SecurityCase.level == lvl)
    if fam := _str_filter(f, "family"):
        q = q.where(SecurityCase.family == fam)
    if assignee := _uuid_filter(f, "assignee"):
        q = q.where(SecurityCase.assignee_id == assignee)
    rule, sla_want = _str_filter(f, "rule"), _str_filter(f, "sla_state")
    cases = (await session.execute(q.order_by(SecurityCase.created_at))).scalars().all()
    prio = {"urgent": 0, "high": 1, "medium": 2, "low": 3}
    rows = []
    for c in sorted(cases, key=lambda c: (prio.get(c.priority, 9), c.sla_decision_due or now)):
        sla = sla_state(c, now)
        if sla_want and sla != sla_want:
            continue
        st = await session.get(SecurityUserState, c.user_id)
        ev = (
            await session.execute(
                select(RiskEvaluation.explanation_keys)
                .where(RiskEvaluation.user_id == c.user_id)
                .order_by(RiskEvaluation.evaluated_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        keys = list(ev or [])
        if rule and c.hc_rule != rule:
            rule_keys = (
                await session.execute(
                    select(AccountRestriction.rule_keys).where(AccountRestriction.case_id == c.id)
                )
            ).scalars()
            if not any(rule in (rk or []) for rk in rule_keys):
                continue
        rows.append(
            {
                "case_ref": c.case_ref,
                "user_id": str(c.user_id),
                "level": c.level,
                "priority": c.priority,
                "score": float(st.sharing_score) if st else None,
                "hc_rule": c.hc_rule,
                "top_explanation_keys": keys[:3],
                "age_hours": int((now - c.created_at).total_seconds() // 3600),
                "sla_state": sla,
                "assignee": str(c.assignee_id) if c.assignee_id else None,
                "repeat": c.repeat_count > 0,
                "family": c.family,
            }
        )
    no_case = (
        (
            await session.execute(
                select(SecurityUserState)
                .where(
                    SecurityUserState.sharing_score > 0,
                    SecurityUserState.user_id.not_in(
                        select(SecurityCase.user_id).where(SecurityCase.status != "closed")
                    ),
                )
                .order_by(SecurityUserState.sharing_score.desc())
                .limit(50)
            )
        )
        .scalars()
        .all()
    )
    return rows, {
        "highest_scores_without_case": [
            {
                "user_id": str(s.user_id),
                "sharing_score": float(s.sharing_score),
                "takeover_score": float(s.takeover_score),
            }
            for s in no_case
        ]
    }


async def _h2(
    session: AsyncSession, f: dict[str, Any], since: datetime, now: datetime
) -> tuple[list[Any], dict[str, Any]]:
    n = _int_filter(f, "min_accounts") or 4
    days = _int_filter(f, "days") or 7
    q = (
        select(UserDevice.device_id, func.count(func.distinct(UserDevice.user_id)).label("accounts"))
        .where(UserDevice.last_used_at > now - timedelta(days=days))
        .group_by(UserDevice.device_id)
        .having(func.count(func.distinct(UserDevice.user_id)) >= n)
    )
    rows = [{"device_id": str(d), "accounts": int(a)} for d, a in (await session.execute(q)).all()]
    return rows, {"note": "Per-user device/account graph: SEC-15 /security/users/{user_id}/device-graph"}


async def _h3(
    session: AsyncSession, f: dict[str, Any], since: datetime, now: datetime
) -> tuple[list[Any], dict[str, Any]]:
    if now - since > timedelta(days=H3_MAX_DAYS):
        if f.get("from"):
            raise _bad("from", f"H3 covers at most {H3_MAX_DAYS} days")
        since = now - timedelta(days=H3_MAX_DAYS)
    q = select(SecuritySignal).where(
        SecuritySignal.rule_key.in_(("SH-01", "SH-03", "cap.session", "cap.stream")),
        SecuritySignal.occurred_at > since,
        SecuritySignal.occurred_at <= now,
    )
    if uid := _uuid_filter(f, "user_id"):
        q = q.where(SecuritySignal.user_id == uid)
    if rule := _str_filter(f, "rule"):
        q = q.where(SecuritySignal.rule_key == rule)
    sigs = (await session.execute(q.order_by(SecuritySignal.occurred_at.desc()).limit(500))).scalars().all()
    rows = [
        {
            "at": _iso(s.occurred_at),
            "user_id": str(s.user_id),
            "rule": s.rule_key,
            "separation_class": s.multipliers.get("separation_class"),
            "net_type_a": s.evidence.get("net_type_a"),
            "net_type_b": s.evidence.get("net_type_b"),
            "region_a": s.evidence.get("region_a"),
            "region_b": s.evidence.get("region_b"),
        }
        for s in sigs
    ]
    return rows, {"window_days_max": H3_MAX_DAYS}


async def _h4(
    session: AsyncSession, f: dict[str, Any], since: datetime, now: datetime
) -> tuple[list[Any], dict[str, Any]]:
    k = await _k(session)
    q = (
        select(
            SessionNetworkObservation.net_cluster,
            func.count(func.distinct(SessionNetworkObservation.user_id)),
        )
        .where(
            SessionNetworkObservation.first_seen_at > since, SessionNetworkObservation.first_seen_at <= now
        )
        .group_by(SessionNetworkObservation.net_cluster)
        .order_by(func.count(func.distinct(SessionNetworkObservation.user_id)).desc())
        .limit(100)
    )
    rows = []
    for cluster, n in (await session.execute(q)).all():
        rows.append(
            {"cluster": cluster, "accounts": int(n)} if n >= k else {"cluster": cluster, "suppressed": True}
        )
    flagged = (
        await session.execute(
            select(SecuritySignal.rule_key, SecuritySignal.evidence).where(
                SecuritySignal.rule_key.in_(("AB-04", "AB-05")),
                SecuritySignal.occurred_at > since,
                SecuritySignal.occurred_at <= now,
            )
        )
    ).all()
    return rows, {"flagged_sources": [{"rule": r, "source": e.get("source")} for r, e in flagged], "k_min": k}


async def _h5(
    session: AsyncSession, f: dict[str, Any], since: datetime, now: datetime
) -> tuple[list[Any], dict[str, Any]]:
    q = select(AccountRestriction).where(
        AccountRestriction.ended_at.is_(None),
        (AccountRestriction.level >= 3) | (AccountRestriction.family == "takeover"),
    )
    if (lvl := _int_filter(f, "level")) is not None:
        q = q.where(AccountRestriction.level == lvl)
    if fam := _str_filter(f, "family"):
        q = q.where(AccountRestriction.family == fam)
    source = _str_filter(f, "source")
    rs_ = (await session.execute(q.order_by(AccountRestriction.starts_at.desc()))).scalars().all()
    rows = []
    for r in rs_:
        case = await session.get(SecurityCase, r.case_id) if r.case_id else None
        src = f"HC rule {r.hc_rule}" if r.hc_rule and r.family == "sharing" else r.source
        if source and source not in (r.source, src, r.hc_rule):
            continue
        rows.append(
            {
                "user_id": str(r.user_id),
                "level": r.level,
                "family": r.family,
                "scope": r.scope,
                "since": _iso(r.starts_at),
                "ends_at": _iso(r.ends_at),
                "deferred_until": _iso(r.deferred_until),
                "source": src,
                "case_ref": case.case_ref if case else None,
            }
        )
    return rows, {}


async def _h6(
    session: AsyncSession, f: dict[str, Any], since: datetime, now: datetime
) -> tuple[list[Any], dict[str, Any]]:
    from app.modules.rbac.models import ApprovalRequest

    states = ("submitted", "under_review", "info_requested", "escalated")
    want_state = _str_filter(f, "state")
    want_level = _int_filter(f, "level")
    urs = (
        (
            await session.execute(
                select(UnblockRequest)
                .where(UnblockRequest.state.in_((want_state,) if want_state else states))
                .order_by(UnblockRequest.submitted_at)
            )
        )
        .scalars()
        .all()
    )
    rows = []
    kept = []
    for u in urs:
        case = await session.get(SecurityCase, u.case_id)
        if want_level is not None and (case is None or case.level != want_level):
            continue
        kept.append(u)
        pend = (
            await session.execute(
                select(func.count())
                .select_from(ApprovalRequest)
                .where(
                    ApprovalRequest.action_type == "security.case.decision",
                    ApprovalRequest.target_id == u.case_id,
                    ApprovalRequest.status == "pending",
                )
            )
        ).scalar_one()
        rows.append(
            {
                "reference": u.reference,
                "case_ref": case.case_ref if case else None,
                "state": u.state,
                "level": case.level if case else None,
                "sla_decision_due": _iso(case.sla_decision_due) if case else None,
                "pending_second_approval": bool(pend),
                "assignee": str(u.assigned_to) if u.assigned_to else None,
            }
        )
    return rows, {"counts": {s: sum(1 for u in kept if u.state == s) for s in states}}


def _pct(vals: list[float], q: float) -> float:
    s = sorted(vals)
    i = min(len(s) - 1, max(0, round(q * (len(s) - 1))))
    return round(s[i], 1)


async def _h7(
    session: AsyncSession, f: dict[str, Any], since: datetime, now: datetime
) -> tuple[list[Any], dict[str, Any]]:
    k = await _k(session)
    q = (
        select(UnblockRequest, SecurityCase)
        .join(SecurityCase, SecurityCase.id == UnblockRequest.case_id)
        .where(UnblockRequest.submitted_at > since, UnblockRequest.submitted_at <= now)
    )
    if reviewer := _uuid_filter(f, "reviewer"):
        q = q.where(UnblockRequest.assigned_to == reviewer)
    if (lvl := _int_filter(f, "level")) is not None:
        q = q.where(SecurityCase.level == lvl)
    groups: dict[tuple[str, int], list[tuple[Any, Any]]] = defaultdict(list)
    for u, c in (await session.execute(q)).all():
        assert u.submitted_at is not None
        wk = u.submitted_at.astimezone(IST).isocalendar()
        groups[(f"{wk[0]}-W{wk[1]:02d}", c.level)].append((u, c))
    rows: list[dict[str, Any]] = []
    for (week, level), items in sorted(groups.items()):
        if len(items) < k:
            rows.append({"week": week, "level": level, "requests": None, "suppressed": True})
            continue
        fr = [
            ((c.first_response_at - u.submitted_at).total_seconds() / 3600)
            for u, c in items
            if c.first_response_at
        ]
        dec = [((u.decided_at - u.submitted_at).total_seconds() / 3600) for u, c in items if u.decided_at]
        ok = [
            1 for u, c in items if u.decided_at and c.sla_decision_due and u.decided_at <= c.sla_decision_due
        ]
        rows.append(
            {
                "week": week,
                "level": level,
                "requests": len(items),
                "first_response_median_h": round(statistics.median(fr), 1) if fr else None,
                "first_response_p90_h": _pct(fr, 0.9) if fr else None,
                "decision_median_h": round(statistics.median(dec), 1) if dec else None,
                "decision_p90_h": _pct(dec, 0.9) if dec else None,
                "sla_compliance_pct": round(100 * len(ok) / len(dec), 1) if dec else None,
            }
        )
    return rows, {"k_min": k}


FP_RULE_WEEKLY_ALERT = 3  # RE §10 H8: a rule contributing > 3 false-positive cases in a week


async def _h8(
    session: AsyncSession, f: dict[str, Any], since: datetime, now: datetime
) -> tuple[list[Any], dict[str, Any]]:
    """ADM-02: one row per L3/L4 decision (never DISTINCT over non-unique columns). A decision
    contributes each dimension once even when its case had several restrictions."""
    from app.modules.security.engine import rule_version

    q = (
        select(
            CaseDecision.id,
            CaseDecision.outcome,
            CaseDecision.created_at,
            AccountRestriction.ruleset_version,
            AccountRestriction.hc_rule,
            AccountRestriction.rule_keys,
        )
        .join(AccountRestriction, AccountRestriction.case_id == CaseDecision.case_id)
        .where(
            CaseDecision.created_at > since,
            CaseDecision.created_at <= now,
            AccountRestriction.level.in_((3, 4)),
        )
    )
    decisions: dict[uuid.UUID, tuple[str, datetime, set[tuple[str, str]]]] = {}
    for did, outcome, at, rv, hc, keys in (await session.execute(q)).all():
        dims = (
            {("ruleset", rv or "-")}
            | ({("hc_rule", hc)} if hc else set())
            | {("rule", k_) for k_ in keys or []}
        )
        if did in decisions:
            decisions[did][2].update(dims)
        else:
            decisions[did] = (outcome, at, dims)
    by: dict[tuple[str, str], list[int]] = defaultdict(lambda: [0, 0])
    weekly_fp: dict[tuple[str, str], int] = defaultdict(int)
    for outcome, at, dims in decisions.values():
        fp = outcome == "lift_false_positive"
        for d in dims:
            by[d][0] += 1
            by[d][1] += 1 if fp else 0
            if fp and d[0] in ("rule", "hc_rule"):
                wk = at.astimezone(IST).isocalendar()
                weekly_fp[(d[1], f"{wk[0]}-W{wk[1]:02d}")] += 1
    rows: list[dict[str, Any]] = [
        {
            "dimension": d,
            "key": key,
            "decisions": n,
            "false_positives": fp,
            "fp_rate": round(fp / n, 3) if n else None,
        }
        for (d, key), (n, fp) in sorted(by.items())
    ]
    breakers = {}
    for hc in ("HC-01", "HC-02"):
        v = await rule_version(session, hc)
        breakers[hc] = (
            "open"
            if v is not None and v.status_change_reason == "circuit_breaker" and v.status == "shadow"
            else "closed"
        )
    alerts: list[dict[str, Any]] = [
        {"alert": "l3_fp_rate_above_10pct", **r}
        for r in rows
        if r["dimension"] == "ruleset" and r["fp_rate"] is not None and float(r["fp_rate"]) > 0.10
    ]
    alerts += [
        {"alert": "rule_fp_cases_per_week_above_3", "key": rule, "week": week, "false_positives": n}
        for (rule, week), n in sorted(weekly_fp.items())
        if n > FP_RULE_WEEKLY_ALERT
    ]
    return rows, {"circuit_breakers": breakers, "alerts": alerts}


async def _h9(
    session: AsyncSession, f: dict[str, Any], since: datetime, now: datetime
) -> tuple[list[Any], dict[str, Any]]:
    """ADM-03: incidents are distinct L3+ cases with a confirmed decision in 180 days; the
    interval is between the first confirmations of consecutive cases."""
    from app.modules.security.engine import CONFIRMED_OUTCOMES

    q = (
        select(SecurityCase.user_id, SecurityCase.id, CaseDecision.created_at, CaseDecision.outcome)
        .join(SecurityCase, SecurityCase.id == CaseDecision.case_id)
        .where(
            CaseDecision.outcome.in_(CONFIRMED_OUTCOMES),
            CaseDecision.created_at > now - timedelta(days=180),
            CaseDecision.created_at <= now,
            SecurityCase.level >= 3,
        )
        .order_by(CaseDecision.created_at)
    )
    first: dict[uuid.UUID, dict[uuid.UUID, datetime]] = defaultdict(dict)
    latest: dict[uuid.UUID, str] = {}
    for user_id, case_id, at, outcome in (await session.execute(q)).all():
        first[user_id].setdefault(case_id, at)
        latest[user_id] = outcome
    rows = []
    for user_id, per_case in first.items():
        if len(per_case) < 2:
            continue
        times = sorted(per_case.values())
        gaps = [(b - a).total_seconds() / 86400 for a, b in itertools.pairwise(times)]
        rows.append(
            {
                "user_id": str(user_id),
                "confirmed_incidents": len(times),
                "first": _iso(times[0]),
                "last": _iso(times[-1]),
                "interval_days": round(min(gaps), 1),
                "latest_outcome": latest[user_id],
            }
        )
    return rows, {}


async def _h10(
    session: AsyncSession, f: dict[str, Any], since: datetime, now: datetime
) -> tuple[list[Any], dict[str, Any]]:
    k = await _k(session)
    active = (AuthSession.status == "active", AuthSession.absolute_expires_at > now)
    q = select(AuthSession.session_tier, AuthSession.client_type, func.count()).where(*active)
    if tier := _str_filter(f, "tier"):
        q = q.where(AuthSession.session_tier == tier)
    if ct := _str_filter(f, "client_type"):
        q = q.where(AuthSession.client_type == ct)
    rows = [
        {"tier": t, "client_type": c, "active_sessions": int(n)}
        if n >= k
        else {"tier": t, "client_type": c, "active_sessions": None, "suppressed": True}
        for t, c, n in (
            await session.execute(q.group_by(AuthSession.session_tier, AuthSession.client_type))
        ).all()
    ]
    per_user = (
        select(AuthSession.user_id, func.count().label("n"))
        .where(*active, AuthSession.session_tier == "student")
        .group_by(AuthSession.user_id)
        .subquery()
    )
    dist_rows = (await session.execute(select(per_user.c.n, func.count()).group_by(per_user.c.n))).all()
    distribution = {str(int(n)): (int(users) if users >= k else None) for n, users in sorted(dist_rows)}
    cap = int(await get_value(session, "sessions.student.max_concurrent"))
    at_cap = sum(int(users) for n, users in dist_rows if int(n) >= cap)
    return rows, {
        "k_min": k,
        "student_sessions_per_user": distribution,
        "students_at_session_cap": at_cap if at_cap == 0 or at_cap >= k else None,
        "student_session_cap": cap,
    }


async def _h11(
    session: AsyncSession, f: dict[str, Any], since: datetime, now: datetime
) -> tuple[list[Any], dict[str, Any]]:
    """ADM-04: aggregate learning activity from the analytics public feed (never raw tables)."""
    from app.modules.analytics.feeds import get_learning_activity

    gran = _str_filter(f, "granularity") or "day"
    if gran not in ("day", "week", "month"):
        raise _bad("granularity", "Use day, week or month")
    k = await _k(session)
    buckets = await get_learning_activity(
        session,
        since.astimezone(IST).date(),
        now.astimezone(IST).date(),
        granularity=gran,
        k_min=k,
    )
    rows = [
        {
            "period_start": b.period_start.isoformat(),
            "active_learners": b.active_learners,
            "engaged_minutes": b.engaged_minutes,
            "learning_minutes": b.learning_minutes,
            **({"suppressed": True} if b.suppressed else {}),
        }
        for b in buckets
    ]
    return rows, {
        "granularity": gran,
        "scope": "platform",
        "k_min": k,
        "source": "analytics.feeds.get_learning_activity",
        "available": True,
    }


async def _h12(
    session: AsyncSession, f: dict[str, Any], since: datetime, now: datetime
) -> tuple[list[Any], dict[str, Any]]:
    uid = _uuid_filter(f, "user_id")
    if uid is None:
        raise ProblemError(
            "validation_failed",
            422,
            errors=[{"field": "user_id", "code": "required", "message": "H12 needs a user_id filter"}],
        )
    from app.modules.security.timeline import timeline

    events = await timeline(session, uid, since, now, None)
    return events, {"user_id": str(uid)}


async def _eng(
    session: AsyncSession, f: dict[str, Any], since: datetime, now: datetime
) -> tuple[list[Any], dict[str, Any]]:
    from app.modules.security.controls import engine_state

    dist = (
        await session.execute(
            select(AccountRestriction.level, func.count())
            .where(AccountRestriction.ended_at.is_(None), AccountRestriction.family == "sharing")
            .group_by(AccountRestriction.level)
        )
    ).all()
    shadow = (
        await session.execute(
            select(func.count())
            .select_from(RiskEvaluation)
            .where(
                RiskEvaluation.mode == "shadow",
                RiskEvaluation.evaluated_at > since,
                RiskEvaluation.gates["hc_rule"].astext.is_not(None),
            )
        )
    ).scalar_one()
    enforced = (
        await session.execute(
            select(func.count())
            .select_from(AccountRestriction)
            .where(AccountRestriction.hc_rule.is_not(None), AccountRestriction.created_at > since)
        )
    ).scalar_one()
    vol = (
        await session.execute(
            select(SecuritySignal.rule_key, func.count())
            .where(SecuritySignal.occurred_at > since)
            .group_by(SecuritySignal.rule_key)
        )
    ).all()
    failures = (
        await session.execute(
            select(func.count())
            .select_from(LoginAttempt)
            .where(
                LoginAttempt.attempted_at > now - timedelta(minutes=10),
                LoginAttempt.outcome.in_(("bad_credentials", "unknown_identifier")),
            )
        )
    ).scalar_one()
    return [], {
        "state": await engine_state(session),
        "level_distribution": {str(lvl): int(n) for lvl, n in dist},
        "hc": {"shadow_matches": int(shadow), "enforced": int(enforced)},
        "signal_volumes": {k: int(n) for k, n in vol},
        "login_failures_10min": int(failures),
    }


_RUNNERS = {
    "top-suspicious-accounts": _h1,
    "account-device-associations": _h2,
    "concurrent-login-events": _h3,
    "repeated-network-device-associations": _h4,
    "blocked-accounts": _h5,
    "pending-unblock-requests": _h6,
    "average-review-time": _h7,
    "false-positive-rate": _h8,
    "repeat-incidents": _h9,
    "active-session-counts": _h10,
    "learning-activity": _h11,
    "device-login-history": _h12,
    "engine-health": _eng,
}


def _flatten(v: Any) -> Any:
    return v if not isinstance(v, list | dict) else str(v)


def export_rows(job: SecurityReportExport, data: dict[str, Any]) -> list[dict[str, Any]]:
    """Rows written to the CSV. A per-user export (approved by a second reviewer) keeps every
    column. Anything else drops identifying columns (defence in depth for aggregate reports),
    and an aggregate report whose data lives outside ``rows`` (ENG) is flattened to key/value."""
    rows: list[dict[str, Any]] = list(data["rows"])
    if not rows and data["report_key"] == "engine-health":
        skip = {"report_key", "report_id", "title", "generated_at", "period", "filters_applied", "rows"}
        rows = [{"metric": k, "value": _flatten(v)} for k, v in data.items() if k not in skip]
    if job.include_per_user_rows:
        return rows
    return [{k: v for k, v in r.items() if k not in IDENTIFYING_COLUMNS} for r in rows]


async def render_export(session: AsyncSession, job: SecurityReportExport) -> None:
    data = await run_report(session, job.report_key, dict(job.filters or {}))
    rows = export_rows(job, data)
    buf = io.StringIO()
    stamp = to_rfc3339(clock.now())
    watermark = f"Tech Drona security export {job.report_key} requested by {job.requested_by} at {stamp}"
    buf.write(f"# {watermark}\n")
    cols: list[str] = []
    if rows:
        cols = sorted({k for r in rows for k in r})
        w = csv.DictWriter(buf, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: _flatten(v) for k, v in r.items()})
    job.content = buf.getvalue()
    job.contains_pii = bool(IDENTIFYING_COLUMNS.intersection(cols))
    job.watermark = watermark
    job.row_count = len(rows)
    job.status = "completed"
    job.completed_at = clock.now()
    job.download_expires_at = clock.now() + timedelta(hours=24)
    await session.flush()
