"""Pure, deterministic risk scoring (RE §4.2.1, §5.1-§5.3, §5.6). No I/O: same inputs → same
output, so evaluations are explainable and replayable for shadow comparisons.

    score_family = min(100, M_repeat x Σ p_i x m_i x 0.5^((t - t_i)/H))

* per-signal 7-day caps on weighted points (``counted = false`` beyond the cap);
* the S2 multiplier is resolved at scoring time from each device's owner-verification state;
* network signals (SH-02/09/10) are capped together at ``risk.network_points_cap``;
* state signals (SH-05) contribute only their latest occurrence, undecayed.
"""

from __future__ import annotations

import ipaddress
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any

from app.modules.security.catalogue import (
    CONCURRENCY_RULES,
    NETWORK_RULES,
    RULES_BY_KEY,
    STATE_SIGNALS,
)

IST_OFFSET = timedelta(hours=5, minutes=30)


def ist_day(dt: datetime) -> date:
    return (dt.astimezone(UTC) + IST_OFFSET).date()


@dataclass(frozen=True)
class Sig:
    id: str
    rule: str
    category: str | None
    occurred_at: datetime
    base_points: float
    multipliers: dict[str, Any] = field(default_factory=dict)
    evidence: dict[str, Any] = field(default_factory=dict)
    rule_version: str | None = None


@dataclass(frozen=True)
class SharingPolicy:
    window_days: int = 30
    half_life_days: float = 7
    network_cap: float = 20
    l1: float = 25
    l2: float = 45
    l3: float = 70
    l4_recommend: float = 90
    min_categories: int = 2
    min_distinct_days: int = 3
    min_separated_days: int = 2
    s0: float = 0.1
    s1: float = 0.1
    s2_verified: float = 0.1
    s2_unverified: float = 0.3
    s3: float = 1.0
    owner_verification_days: int = 30


@dataclass(frozen=True)
class SharingContext:
    owner_verified_at: dict[str, datetime | None] = field(default_factory=dict)  # device_id -> ts
    sh13_tainted: frozenset[str] = frozenset()  # devices verified in an SH-13 way (30 d)
    current_level: int = 0
    l2_issued_at: datetime | None = None
    l2_passed_at: datetime | None = None
    repeat: bool = False


@dataclass
class SharingResult:
    score: float
    subtotals: dict[str, float]
    contributions: list[dict[str, Any]]
    gates: dict[str, Any]
    level_after: int
    action: str
    explanation_keys: list[str]
    repeat_multiplier: float
    categories: list[str]


def decay_factor(t: datetime, ti: datetime, half_life_days: float) -> float:
    days = max(0.0, (t - ti).total_seconds() / 86400.0)
    return float(0.5 ** (days / half_life_days))


def _verified(ctx: SharingContext, device: str | None, now: datetime, policy: SharingPolicy) -> bool:
    if not device or device in ctx.sh13_tainted:
        return False
    ts = ctx.owner_verified_at.get(device)
    return ts is not None and now - ts <= timedelta(days=policy.owner_verification_days)


def resolve_multiplier(
    sig: Sig, now: datetime, policy: SharingPolicy, ctx: SharingContext
) -> tuple[float, dict[str, Any]]:
    """Multiplier for one occurrence at scoring time (+ the multipliers record)."""
    rec: dict[str, Any] = {k: v for k, v in sig.multipliers.items() if k not in ("counted",)}
    m = 1.0
    if sig.rule == "SH-01":
        cls = str(sig.multipliers.get("separation_class", "S3"))
        if cls == "S0":
            sep = 0.0 if sig.multipliers.get("fp_match") else policy.s0
        elif cls == "S1":
            sep = policy.s1
        elif cls == "S2":
            both = _verified(ctx, sig.evidence.get("device_a"), now, policy) and _verified(
                ctx, sig.evidence.get("device_b"), now, policy
            )
            sep = policy.s2_verified if both else policy.s2_unverified
            rec["owner_verified_both"] = both
        else:
            sep = policy.s3  # 🔒 1.0: never discounted by verification
        rec["separation_class"] = cls
        rec["separation"] = sep
        m *= sep
    return m, rec


def score_sharing(
    signals: list[Sig],
    now: datetime,
    policy: SharingPolicy,
    ctx: SharingContext,
    caps: dict[str, float],
) -> SharingResult:
    window_start = now - timedelta(days=policy.window_days)
    sigs = sorted(
        (s for s in signals if window_start < s.occurred_at <= now and s.rule in RULES_BY_KEY),
        key=lambda s: (s.occurred_at, s.id),
    )
    # state signals: latest occurrence only
    latest_state: dict[str, Sig] = {}
    for s in sigs:
        if s.rule in STATE_SIGNALS:
            latest_state[s.rule] = s
    counted_hist: dict[str, list[tuple[datetime, float]]] = defaultdict(list)
    contributions: list[dict[str, Any]] = []
    per_cat: dict[str, float] = defaultdict(float)
    network_raw = 0.0
    for s in sigs:
        m, rec = resolve_multiplier(s, now, policy, ctx)
        weighted = s.base_points * m
        if s.rule in STATE_SIGNALS:
            counted = latest_state.get(s.rule) is s and now - s.occurred_at <= timedelta(days=1)
            decayed = weighted if counted else 0.0
        else:
            cap = caps.get(s.rule)
            hist = counted_hist[s.rule]
            in_window = sum(p for t, p in hist if s.occurred_at - t < timedelta(days=7))
            counted = cap is None or in_window + weighted <= cap + 1e-9
            if counted:
                hist.append((s.occurred_at, weighted))
            decayed = weighted * decay_factor(now, s.occurred_at, policy.half_life_days) if counted else 0.0
        rec["counted"] = counted
        cat = s.category or "-"
        if s.rule in NETWORK_RULES:
            network_raw += decayed
        else:
            per_cat[cat] += decayed
        contributions.append(
            {
                "signal_id": s.id,
                "rule": s.rule,
                "rule_version": s.rule_version,
                "category": s.category,
                "occurred_at": s.occurred_at.isoformat(),
                "base_points": s.base_points,
                "multipliers": rec,
                "decayed_points": round(decayed, 2),
                "evidence": s.evidence,
            }
        )
    network_capped = min(network_raw, policy.network_cap)
    per_cat["N"] = per_cat.get("N", 0.0) + network_capped
    repeat_m = 1.25 if ctx.repeat else 1.0
    raw = sum(v for k, v in per_cat.items() if k != "-") + per_cat.get("-", 0.0)
    score = round(min(100.0, repeat_m * raw), 2)
    subtotals = {
        "C": round(per_cat.get("C", 0.0), 2),
        "D": round(per_cat.get("D", 0.0), 2),
        "N": round(network_capped, 2),
        "network_raw": round(network_raw, 2),
        "network_capped": round(network_capped, 2),
    }
    categories = sorted(c for c in ("C", "D", "N") if per_cat.get(c, 0.0) > 0.0)
    gates = sharing_gates(sigs, now, policy, ctx, categories, score)
    level, action = next_level(score, gates, ctx, policy)
    keys: list[str] = []
    for c in sorted(contributions, key=lambda c: -float(c["decayed_points"])):
        if c["decayed_points"] > 0:
            k = RULES_BY_KEY[c["rule"]].explanation_key
            if k not in keys:
                keys.append(k)
    return SharingResult(
        score=score,
        subtotals=subtotals,
        contributions=contributions,
        gates=gates,
        level_after=level,
        action=action,
        explanation_keys=keys[:5],
        repeat_multiplier=repeat_m,
        categories=categories,
    )


def _is_separated(s: Sig) -> bool:
    return (s.rule == "SH-01" and s.multipliers.get("separation_class") == "S3") or s.rule == "SH-13"


def sharing_gates(
    sigs: list[Sig],
    now: datetime,
    policy: SharingPolicy,
    ctx: SharingContext,
    categories: list[str],
    score: float,
) -> dict[str, Any]:
    d14 = now - timedelta(days=14)
    d7 = now - timedelta(days=7)
    c_days = sorted(
        {ist_day(s.occurred_at) for s in sigs if s.rule in CONCURRENCY_RULES and s.occurred_at > d14}
    )
    sep_days = sorted({ist_day(s.occurred_at) for s in sigs if _is_separated(s) and s.occurred_at > d14})
    c_in_7 = any(s.rule in CONCURRENCY_RULES and s.occurred_at > d7 for s in sigs)
    l2_reached = ctx.l2_issued_at is not None
    l2_condition = False
    if ctx.l2_issued_at is not None:
        if ctx.l2_passed_at is None or ctx.l2_passed_at < ctx.l2_issued_at:
            l2_condition = now - ctx.l2_issued_at >= timedelta(hours=24)  # failed / abandoned
        else:
            l2_condition = any(s.rule in CONCURRENCY_RULES and s.occurred_at > ctx.l2_passed_at for s in sigs)
    rules = {s.rule for s in sigs}
    reseller = {"SH-09", "SH-11", "SH-06"} <= rules
    gates = {
        "min_categories": len(categories) >= policy.min_categories,
        "categories": categories,
        "distinct_days": len(c_days),
        "distinct_days_required": policy.min_distinct_days,
        "separated_days": len(sep_days),
        "separated_days_required": policy.min_separated_days,
        "concurrency_in_7d": c_in_7,
        "l2_reached": l2_reached,
        "l2_condition": l2_condition,
        "reseller_pattern": reseller,
        "hc_rule": None,
    }
    gates["l3"] = bool(
        score >= policy.l3
        and gates["min_categories"]
        and len(c_days) >= policy.min_distinct_days
        and len(sep_days) >= policy.min_separated_days
        and l2_reached
        and l2_condition
    )
    gates["l4_recommend"] = bool(score >= policy.l4_recommend and (ctx.repeat or reseller))
    return gates


def next_level(
    score: float, gates: dict[str, Any], ctx: SharingContext, policy: SharingPolicy
) -> tuple[int, str]:
    """Target level and action with hysteresis (RE §5.3). The engine never moves into L4."""
    cur = ctx.current_level
    if cur >= 3:
        return cur, ("recommend_L4" if gates.get("l4_recommend") and cur == 3 else "none")
    if gates.get("l3"):
        return 3, "restrict_L3"
    target = 0
    if score >= policy.l2 and gates.get("concurrency_in_7d"):
        target = 2
    elif score >= policy.l1:
        target = 1
    if cur == 2 and target < 2:
        passed = ctx.l2_passed_at is not None and (
            ctx.l2_issued_at is None or ctx.l2_passed_at >= ctx.l2_issued_at
        )
        if not (passed and score < 35):
            target = 2
    if cur == 1 and target == 0 and score >= 15:
        target = 1
    if target > cur:
        return target, {1: "notice_L1", 2: "require_otp_L2"}[target]
    if target < cur:
        return target, "deescalate"
    return target, "none"


# --------------------------------------------------------------------------- takeover


def score_takeover(
    signals: list[Sig], now: datetime, window_days: int, half_life_days: float, points: dict[str, float]
) -> tuple[float, list[dict[str, Any]]]:
    start = now - timedelta(days=window_days)
    out: list[dict[str, Any]] = []
    total = 0.0
    for s in sorted(signals, key=lambda s: (s.occurred_at, s.id)):
        if not (start < s.occurred_at <= now) or s.rule not in points:
            continue
        d = s.base_points * decay_factor(now, s.occurred_at, half_life_days)
        total += d
        out.append(
            {
                "signal_id": s.id,
                "rule": s.rule,
                "rule_version": s.rule_version,
                "occurred_at": s.occurred_at.isoformat(),
                "base_points": s.base_points,
                "multipliers": {},
                "decayed_points": round(d, 2),
                "evidence": s.evidence,
            }
        )
    return round(min(100.0, total), 2), out


# --------------------------------------------------------------------------- HC rules


def hc01(
    s3_overlaps: list[Sig], now: datetime, params: dict[str, Any], l2_issued_at: datetime | None
) -> dict[str, Any]:
    """HC-01 condition (1)+(2): S3 overlaps of ≥ min_devices devices on ≥ min_days IST days
    within window_days; an L2 re-verification issued ≥ 24 h before the last qualifying day with
    at least one qualifying day after it. Conditions (3)-(5) are checked by the caller."""
    win = now - timedelta(days=int(params.get("window_days", 14)))
    rel = [s for s in s3_overlaps if s.occurred_at > win and s.multipliers.get("separation_class") == "S3"]
    days = sorted({ist_day(s.occurred_at) for s in rel})
    devices = sorted({d for s in rel for d in (s.evidence.get("device_a"), s.evidence.get("device_b")) if d})
    met_overlap = len(devices) >= int(params.get("min_devices", 2)) and len(days) >= int(
        params.get("min_days", 3)
    )
    remedy = False
    if l2_issued_at is not None and rel:
        last = max(s.occurred_at for s in rel)
        remedy = last - l2_issued_at >= timedelta(hours=24) and any(s.occurred_at > l2_issued_at for s in rel)
    return {
        "met": met_overlap and remedy,
        "qualifying_days": [d.isoformat() for d in days],
        "devices": devices,
        "remedy_first": remedy,
        "params": params,
    }


def hc02(
    s3_overlaps: list[Sig], now: datetime, params: dict[str, Any], l2_issued_at: datetime | None
) -> dict[str, Any]:
    """HC-02: ≥ 3 device tokens with S3 overlaps over ≥ 3 distinct fixed-line clusters in the
    same 30-minute period on ≥ min_days days within window_days (+ HC-01 conditions 2-5)."""
    win = now - timedelta(days=int(params.get("window_days", 7)))
    rel = [s for s in s3_overlaps if s.occurred_at > win and s.multipliers.get("separation_class") == "S3"]
    per_day: dict[date, list[tuple[datetime, str, str]]] = defaultdict(list)
    for s in rel:
        for b in s.evidence.get("buckets", []):
            t = datetime.fromisoformat(b)
            for dev, net in (("device_a", "net_a"), ("device_b", "net_b")):
                if s.evidence.get(dev) and s.evidence.get(net):
                    per_day[ist_day(t)].append((t, s.evidence[dev], s.evidence[net]))
    qualifying: list[date] = []
    for day, legs in per_day.items():
        legs.sort()
        for i, (t0, _, _) in enumerate(legs):
            window = [x for x in legs[i:] if x[0] - t0 < timedelta(minutes=30)]
            if len({d for _, d, _ in window}) >= 3 and len({n for _, _, n in window}) >= 3:
                qualifying.append(day)
                break
    qualifying.sort()
    remedy = False
    if l2_issued_at is not None and rel:
        last = max(s.occurred_at for s in rel)
        remedy = last - l2_issued_at >= timedelta(hours=24) and any(s.occurred_at > l2_issued_at for s in rel)
    return {
        "met": len(qualifying) >= int(params.get("min_days", 2)) and remedy,
        "qualifying_days": [d.isoformat() for d in qualifying],
        "remedy_first": remedy,
        "params": params,
    }


# --------------------------------------------------------------------------- separation classes


@dataclass(frozen=True)
class NetLeg:
    device_id: str
    net_cluster: str | None
    asn: int | None
    network_type: str | None
    geo_region: str | None
    os_family: str | None = None
    device_class: str | None = None
    fp_hash: str | None = None


FIXED_LINE = frozenset({"broadband", "education"})


def _prefix16(cluster: str | None) -> str | None:
    if not cluster:
        return None
    try:
        net = ipaddress.ip_network(
            cluster.split(":", 1)[1] if cluster.startswith("AS") else cluster, strict=False
        )
    except ValueError:
        return None
    if net.version == 4:
        return str(ipaddress.ip_network(f"{net.network_address}/16", strict=False))
    return str(ipaddress.ip_network(f"{net.network_address}/32", strict=False))


def classify_pair(a: NetLeg, b: NetLeg, cgnat_asns: frozenset[int]) -> tuple[str, bool]:
    """(class, fp_match) per RE §4.2.1 for two legs observed in the same bucket."""
    fp_match = bool(a.fp_hash and a.fp_hash == b.fp_hash)
    same_cluster = bool(a.net_cluster and a.net_cluster == b.net_cluster)
    if fp_match or (same_cluster and a.os_family == b.os_family and a.device_class == b.device_class):
        return "S0", fp_match
    mobile_same = (
        a.network_type == "mobile"
        and b.network_type == "mobile"
        and a.asn is not None
        and a.asn == b.asn
        and a.geo_region == b.geo_region
    )
    if same_cluster or mobile_same:
        return "S1", False

    def indeterminate(x: NetLeg) -> bool:
        return (x.network_type or "unknown") not in FIXED_LINE or (x.asn is not None and x.asn in cgnat_asns)

    if indeterminate(a) or indeterminate(b):
        return "S2", False
    diff_asn = a.asn is not None and b.asn is not None and a.asn != b.asn and a.asn != 0 and b.asn != 0
    if diff_asn or _prefix16(a.net_cluster) != _prefix16(b.net_cluster):
        return "S3", False
    return "S2", False


CLASS_ORDER = {"S0": 0, "S1": 1, "S2": 2, "S3": 3}
