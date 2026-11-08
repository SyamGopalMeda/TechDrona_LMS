"""Pure scoring engine (RE §4.2.1, §5.1-§5.3, §5.6): worked examples A, B, C, caps, network cap,
separation classes, HC-01/HC-02 conditions. No database."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.modules.security.catalogue import BUILTIN_RULESETS
from app.modules.security.rules import (
    NetLeg,
    SharingContext,
    SharingPolicy,
    Sig,
    classify_pair,
    hc01,
    hc02,
    score_sharing,
)

NOW = datetime(2026, 11, 3, 6, 0, tzinfo=UTC)
CAPS = {k: float(v) for k, v in BUILTIN_RULESETS["sharing"]["caps"].items()}
P = BUILTIN_RULESETS["sharing"]["points"]
POL = SharingPolicy()
_n = 0


def sig(rule: str, days_ago: float, cat: str, cls: str | None = None, **ev: str) -> Sig:
    global _n
    _n += 1
    m = {"separation_class": cls} if cls else {}
    return Sig(
        id=f"s{_n}",
        rule=rule,
        category=cat,
        occurred_at=NOW - timedelta(days=days_ago),
        base_points=float(P[rule]),
        multipliers=m,
        evidence=ev,
    )


def example_b(days: tuple[int, ...] = (9, 6, 3, 0)) -> list[Sig]:
    out = [sig("SH-13", 10, "D", device="d3")]
    for d in days:
        out.append(sig("SH-01", d, "C", "S3", device_a="d1", device_b="d3", buckets=[]))
        out.append(sig("SH-02", d, "N"))
    out += [sig("SH-03", 1, "C"), sig("SH-05", 0, "D")]
    return out


def test_worked_example_b_reaches_l3_even_when_every_device_is_owner_verified() -> None:
    ctx = SharingContext(
        owner_verified_at={"d1": NOW, "d3": NOW},
        current_level=2,
        l2_issued_at=NOW - timedelta(days=3),
        l2_passed_at=NOW - timedelta(days=2, hours=12),
    )
    r = score_sharing(example_b(), NOW, POL, ctx, CAPS)
    assert 70 <= r.score <= 72.5, r.score  # RE §5.1: ≈ 71
    assert r.gates["l3"] and r.level_after == 3 and r.action == "restrict_L3"
    assert r.gates["categories"] == ["C", "D", "N"]
    assert r.gates["distinct_days"] == 5 and r.gates["separated_days"] == 5
    # SH-02 at day -3 exceeds its 7-day cap and is recorded with counted = false
    sh02 = [c for c in r.contributions if c["rule"] == "SH-02"]
    assert [c["multipliers"]["counted"] for c in sh02] == [True, True, False, True]
    assert "sh01.overlap_two_devices" in r.explanation_keys


def test_worked_example_b_two_overlap_days_is_l2_only() -> None:
    ctx = SharingContext(owner_verified_at={"d1": NOW, "d3": NOW})
    r = score_sharing(example_b((3, 0)), NOW, POL, ctx, CAPS)
    assert 53 <= r.score <= 57, r.score  # ≈ 55
    assert not r.gates["l3"] and r.level_after == 2 and r.action == "require_otp_L2"


def _daily_s2(days: int) -> list[Sig]:
    return [sig("SH-01", d, "C", "S2", device_a="lap", device_b="phone") for d in range(days)]


def test_worked_example_a_s2_steady_state_and_reweighting() -> None:
    both = SharingContext(owner_verified_at={"lap": NOW, "phone": NOW})
    assert 14 <= score_sharing(_daily_s2(30), NOW, POL, both, CAPS).score <= 16  # ≈ 15 → L0
    email_only = SharingContext(owner_verified_at={"lap": NOW})
    unverified = score_sharing(_daily_s2(30), NOW, POL, email_only, CAPS)
    assert 44 <= unverified.score <= 46 and unverified.level_after == 2  # ≈ 45 → L2
    # phone later owner-verified: earlier S2 overlaps re-weight to 0.1 at scoring time; L2 clears
    passed = SharingContext(
        owner_verified_at={"lap": NOW, "phone": NOW},
        current_level=2,
        l2_issued_at=NOW - timedelta(days=1),
        l2_passed_at=NOW,
    )
    r = score_sharing(_daily_s2(30), NOW, POL, passed, CAPS)
    assert r.score < 35 and r.level_after == 0 and r.action == "deescalate"


def test_owner_verification_older_than_30_days_counts_as_unverified() -> None:
    stale = SharingContext(owner_verified_at={"lap": NOW, "phone": NOW - timedelta(days=31)})
    assert score_sharing(_daily_s2(30), NOW, POL, stale, CAPS).score > 40


def test_worked_example_c_mobile_only_sharer_is_accepted_under_detection() -> None:
    ctx = SharingContext(owner_verified_at={"lap": NOW, "phone": NOW})
    sigs = [sig("SH-01", d, "C", "S2", device_a="lap", device_b="phone") for d in (9, 6, 3, 0)]
    sigs += [sig("SH-03", 1, "C"), sig("SH-05", 0, "D")]
    r = score_sharing(sigs, NOW, POL, ctx, CAPS)
    assert r.score < 25 and r.level_after <= 1 and not r.gates["l3"]  # UD-01: L0/L1 is the expected outcome


def test_network_signals_alone_never_exceed_l1() -> None:
    sigs = [sig(rule, d, "N") for d in range(0, 28, 2) for rule in ("SH-02", "SH-09", "SH-10")]
    r = score_sharing(sigs, NOW, POL, SharingContext(), CAPS)
    assert r.subtotals["N"] <= 20 and r.score <= 20 and r.level_after <= 1


def test_no_trusted_network_discount_and_repeat_modifier() -> None:
    """Single company (D5): a legacy ``trusted`` evidence flag no longer discounts a signal."""
    sigs = [
        Sig(id="t", rule="SH-09", category="N", occurred_at=NOW, base_points=4, evidence={"trusted": True})
    ]
    assert score_sharing(sigs, NOW, POL, SharingContext(), CAPS).score > 0
    base = score_sharing(example_b(), NOW, POL, SharingContext(), CAPS).score
    rep = score_sharing(example_b(), NOW, POL, SharingContext(repeat=True), CAPS)
    assert rep.repeat_multiplier == 1.25 and abs(rep.score - min(100, base * 1.25)) < 0.05


def test_s0_with_fingerprint_match_scores_zero() -> None:
    s = Sig(
        id="f",
        rule="SH-01",
        category="C",
        occurred_at=NOW,
        base_points=15,
        multipliers={"separation_class": "S0", "fp_match": True},
    )
    assert score_sharing([s], NOW, POL, SharingContext(), CAPS).score == 0


def leg(dev: str, cluster: str, asn: int, nt: str, region: str = "TG", **kw: object) -> NetLeg:
    return NetLeg(device_id=dev, net_cluster=cluster, asn=asn, network_type=nt, geo_region=region, **kw)  # type: ignore[arg-type]


def test_separation_classes() -> None:
    cg = frozenset({55836})
    a = leg("a", "AS24560:49.36.10.0/24", 24560, "broadband", os_family="Windows", device_class="desktop")
    same_machine = leg(
        "b", "AS24560:49.36.10.0/24", 24560, "broadband", os_family="Windows", device_class="desktop"
    )
    assert classify_pair(a, same_machine, cg) == ("S0", False)  # SEP-01
    phone_home = leg(
        "b", "AS24560:49.36.10.0/24", 24560, "broadband", os_family="Android", device_class="mobile"
    )
    assert classify_pair(a, phone_home, cg)[0] == "S1"  # SEP-02
    jio = leg("b", "AS55836:106.200.1.0/24", 55836, "mobile", os_family="Android", device_class="mobile")
    assert classify_pair(a, jio, cg)[0] == "S2"  # SEP-03
    vpn = leg("b", "AS9009:185.1.1.0/24", 9009, "vpn_proxy")
    assert classify_pair(a, vpn, cg)[0] == "S2"  # SCN-08: a VPN leg is never S3
    pune = leg("b", "AS18209:183.82.1.0/24", 18209, "broadband", "MH")
    assert classify_pair(a, pune, cg)[0] == "S3"  # SEP-04


def test_hc01_needs_three_days_and_remedy_first() -> None:
    s3 = [sig("SH-01", d, "C", "S3", device_a="d1", device_b="d3") for d in (8, 4, 0)]
    params = {"min_devices": 2, "min_days": 3, "window_days": 14}
    assert hc01(s3, NOW, params, NOW - timedelta(days=5))["met"]
    assert not hc01(s3, NOW, params, None)["met"]  # no L2 issued first
    assert not hc01(s3[1:], NOW, params, NOW - timedelta(days=5))["met"]  # 2 days only
    assert not hc01(s3, NOW, params, NOW - timedelta(hours=12))["met"]  # L2 < 24 h before the last day


def test_hc02_three_separated_clusters_in_one_half_hour() -> None:
    def day(d: int) -> list[Sig]:
        t = (NOW - timedelta(days=d)).isoformat()
        nets = {"x": "AS1:1.1.0.0/16", "y": "AS2:2.2.0.0/16", "z": "AS3:3.3.0.0/16"}
        out = []
        for a, b in (("x", "y"), ("x", "z"), ("y", "z")):
            out.append(sig("SH-01", d, "C", "S3", device_a=a, device_b=b, net_a=nets[a], net_b=nets[b]))
            out[-1].evidence["buckets"] = [t]  # type: ignore[index]
        return out

    met = hc02(day(3) + day(0), NOW, {"min_days": 2, "window_days": 7}, NOW - timedelta(days=4))
    assert met["met"] and len(met["qualifying_days"]) == 2
    assert not hc02(day(0), NOW, {"min_days": 2, "window_days": 7}, NOW - timedelta(days=4))["met"]
