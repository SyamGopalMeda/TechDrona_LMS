"""Owner scenarios SCN-01, 05, 06, 07, 08, 09 (sharing family, HC rules, circuit breaker) with
real persistence: signals → versioned evaluation → restriction / case / outbox."""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select

from app.core.models import OutboxEvent
from app.modules.identity import clock
from app.modules.security import engine, signals
from app.modules.security import restrictions as rx
from app.modules.security.models import (
    AccountRestriction,
    RiskEvaluation,
    RiskRuleVersion,
    SecurityCase,
)
from app.modules.sessions import service as ss
from app.modules.sessions.models import AuthSession, LoginAttempt, UserDevice
from tests.security.helpers import (
    BASE,
    activate_rule,
    adult,
    device_session,
    enforce,
    freeze,
    overlap,
    set_policy,
    signals_of,
)


async def evals(db, uid) -> list[RiskEvaluation]:
    return list(
        (
            await db.execute(
                select(RiskEvaluation)
                .where(RiskEvaluation.user_id == uid)
                .order_by(RiskEvaluation.evaluated_at)
            )
        ).scalars()
    )


async def two_cities(db, uid, monkeypatch, start):
    freeze(monkeypatch, start)
    d1 = await device_session(db, uid, ip="49.36.10.5", asn=24560, region="TG", owner_verified_at=start)
    d3 = await device_session(
        db, uid, ip="183.82.1.9", asn=18209, region="MH", os_family="Mac OS X", owner_verified_at=start
    )
    return d1, d3


async def day_overlap(db, uid, monkeypatch, legs, day):
    t = BASE - timedelta(days=day)
    freeze(monkeypatch, t + timedelta(minutes=30))
    return await signals.ingest_engaged_buckets(db, uid, overlap(legs, t))


# --------------------------------------------------------------------------- SCN-05


async def test_scn05a_relayed_otp_sharer_l1_l2_then_l3(db, monkeypatch) -> None:
    await enforce(db)
    u = await adult(db)
    d1, d3 = await two_cities(db, u.id, monkeypatch, BASE - timedelta(days=11))
    # day -10: the relayed verification on D3 completes while D1 is active elsewhere → SH-13
    freeze(monkeypatch, BASE - timedelta(days=10))
    await db.execute(
        AuthSession.__table__.update().where(AuthSession.id == d1[1]).values(last_seen_at=clock.now())
    )
    assert await signals.check_sh13(db, await db.get(engine.User, u.id), d3[0], clock.now()) is not None
    levels = {}
    for day in (9, 6, 3):
        await day_overlap(db, u.id, monkeypatch, [d1, d3], day)
        levels[day] = await rx.active_for(db, u.id, "sharing")
    assert levels[9] is not None and levels[9].level == 1  # ≈ 30 → L1 notice
    assert levels[3] is not None and levels[3].level == 2  # ≈ 47 → L2 "Confirm it's you"
    assert {str(d) for d in levels[3].reverify_device_ids} == {str(d1[0]), str(d3[0])}
    # L2 re-verification passed (relayed again) on both devices
    freeze(monkeypatch, BASE - timedelta(days=2, hours=12))
    await db.execute(
        UserDevice.__table__.update().where(UserDevice.user_id == u.id).values(owner_verified_at=clock.now())
    )
    assert await signals.check_l2_pass(db, u.id)
    assert (await rx.active_for(db, u.id, "sharing")).level == 2  # score still ≥ 35
    freeze(monkeypatch, BASE - timedelta(days=1))
    await signals.report_event(db, "SH-03", user_id=u.id, source="playback", evidence={"takeovers": 3})
    freeze(monkeypatch, BASE)
    await engine.record_signal(db, rule_key="SH-05", user_id=u.id, source="nightly", evidence={"devices": 6})
    await day_overlap(db, u.id, monkeypatch, [d1, d3], 0)
    r = await rx.active_for(db, u.id, "sharing")
    assert r is not None and r.level == 3 and r.source == "engine" and r.hc_rule is None
    assert r.ends_at is not None and abs((r.ends_at - r.starts_at) - timedelta(hours=24)) < timedelta(
        seconds=5
    )
    ev = [e for e in await evals(db, u.id) if e.mode == "enforce"][-1]
    assert ev.action == "restrict_L3" and 70 <= float(ev.score) <= 73
    # HC-01 met too, but its built-in launch status is shadow: recorded, never acted on (RE §5.6)
    assert any(e.mode == "shadow" and e.gates.get("hc_rule") == "HC-01" for e in await evals(db, u.id))
    assert ev.gates["separated_days"] >= 2 and ev.gates["l2_condition"] is True
    case = await db.get(SecurityCase, r.case_id)
    assert (
        case.opened_reason == "engine_L3" and case.priority == "medium" and case.case_ref.startswith("SEC-")
    )
    assert case.sla_decision_due - case.created_at == timedelta(hours=72)
    # all sessions revoked (risk_L3), evidence carries /16 prefixes only, no raw IPs
    assert {
        s.status for s in (await db.execute(select(AuthSession).where(AuthSession.user_id == u.id))).scalars()
    } == {"revoked"}
    sh01 = (await signals_of(db, u.id, "SH-01"))[0]
    assert sh01.evidence["net_a"].endswith("/16") and "49.36.10.5" not in str(sh01.evidence)
    out = (
        (await db.execute(select(OutboxEvent).where(OutboxEvent.event_type == "account.restricted")))
        .scalars()
        .all()
    )
    assert any(o.payload["user_id"] == str(u.id) for o in out)
    assert (await db.get(engine.User, u.id)).restriction_level == 3


async def test_scn05a2_two_days_l2_only_and_5c_mobile_sharer_under_detected(db, monkeypatch) -> None:
    await enforce(db)
    u = await adult(db)
    d1, d3 = await two_cities(db, u.id, monkeypatch, BASE - timedelta(days=11))
    freeze(monkeypatch, BASE - timedelta(days=10))
    await engine.record_signal(
        db, rule_key="SH-13", user_id=u.id, source="system", device_id=d3[0], evidence={"device": str(d3[0])}
    )
    await day_overlap(db, u.id, monkeypatch, [d1, d3], 3)
    freeze(monkeypatch, BASE - timedelta(days=1))
    await signals.report_event(db, "SH-03", user_id=u.id, source="playback")
    freeze(monkeypatch, BASE)
    await engine.record_signal(db, rule_key="SH-05", user_id=u.id, source="nightly")
    await day_overlap(db, u.id, monkeypatch, [d1, d3], 0)
    r = await rx.active_for(db, u.id, "sharing")
    assert r.level == 2 and 53 <= float((await evals(db, u.id))[-1].score) <= 57

    # 5c: the sharer only ever uses Jio mobile data → S2 x 0.1 (relayed device owner-verified), no SH-13
    v = await adult(db)
    freeze(monkeypatch, BASE - timedelta(days=11))
    p1 = await device_session(db, v.id, ip="49.36.10.6", owner_verified_at=clock.now())
    p2 = await device_session(
        db,
        v.id,
        ip="106.200.1.9",
        asn=55836,
        network_type="mobile",
        region="MH",
        os_family="Android",
        device_class="mobile",
        owner_verified_at=clock.now(),
    )
    for day in (9, 6, 3, 0):
        await day_overlap(db, v.id, monkeypatch, [p1, p2], day)
    classes = {s.multipliers["separation_class"] for s in await signals_of(db, v.id, "SH-01")}
    assert classes == {"S2"}
    r2 = await rx.active_for(db, v.id, "sharing")
    assert r2 is None or r2.level <= 1  # expected, accepted under-detection (UD-01)


# --------------------------------------------------------------------------- SCN-01 / SCN-07 / SCN-08


async def test_scn01_laptop_then_phone_daily_overlap_scores_l0(db, monkeypatch) -> None:
    await enforce(db)
    u = await adult(db)
    freeze(monkeypatch, BASE - timedelta(days=31))
    lap = await device_session(db, u.id, ip="49.36.10.7", owner_verified_at=BASE - timedelta(days=5))
    ph = await device_session(
        db,
        u.id,
        ip="106.200.1.10",
        asn=55836,
        network_type="mobile",
        os_family="Android",
        device_class="mobile",
        owner_verified_at=BASE - timedelta(days=5),
    )
    for day in range(30, -1, -1):
        await day_overlap(db, u.id, monkeypatch, [lap, ph], day)
    assert await rx.active_for(db, u.id, "sharing") is None  # ≈ 15 steady → L0
    st = await rx.get_state(db, u.id)
    assert float(st.sharing_score) < 25


async def test_scn07_geo_inconsistent_broadband_sh10_only_and_mobile_excluded(db, monkeypatch) -> None:
    await enforce(db)
    u = await adult(db)
    freeze(monkeypatch, BASE - timedelta(hours=1))
    await device_session(db, u.id, ip="49.36.10.8", region="TG")
    freeze(monkeypatch, BASE - timedelta(minutes=20))
    await device_session(db, u.id, ip="122.160.1.8", asn=24560, region="DL")
    freeze(monkeypatch, BASE)
    made = await signals.derive_daily_signals(db, u.id)
    assert made == ["SH-10"]
    await engine.evaluate_sharing(db, u.id, trigger="nightly")
    assert await rx.active_for(db, u.id, "sharing") is None  # ≤ 8 → L0, never on geo alone
    m = await adult(db)
    freeze(monkeypatch, BASE - timedelta(hours=1))
    await device_session(db, m.id, ip="106.200.1.11", asn=55836, network_type="mobile", region="TG")
    freeze(monkeypatch, BASE - timedelta(minutes=30))
    await device_session(db, m.id, ip="106.201.1.11", asn=55836, network_type="mobile", region="DL")
    freeze(monkeypatch, BASE)
    assert await signals.derive_daily_signals(db, m.id) == []  # mobile ASN excluded


async def test_scn07_first_login_outside_india_is_to09_notice_only(db, monkeypatch) -> None:
    u = await adult(db)
    la = LoginAttempt(
        id=engine.uuid7(),
        attempted_at=clock.now(),
        user_id=u.id,
        identifier_hash=b"x" * 32,
        method="password",
        outcome="success",
        ip="203.0.113.50",
        geo_country="SG",
    )
    db.add(la)
    await db.flush()
    await signals.on_login_attempt(db, la)
    assert [s.rule_key for s in await signals_of(db, u.id)] == ["TO-09"]
    ev = (await evals(db, u.id))[-1]
    assert ev.family == "takeover" and float(ev.score) == 15 and ev.action == "none"


async def test_scn08_vpn_student_capped_and_tor_adds_takeover_only(db, monkeypatch) -> None:
    await enforce(db)
    u = await adult(db)
    for day in range(10, -1, -1):
        freeze(monkeypatch, BASE - timedelta(days=day))
        la = LoginAttempt(
            id=engine.uuid7(),
            attempted_at=clock.now(),
            user_id=u.id,
            identifier_hash=b"v" * 32,
            method="password",
            outcome="success",
            ip="185.1.1.1",
            network_type="vpn_proxy",
            asn=9009,
        )
        db.add(la)
        await db.flush()
        await signals.on_login_attempt(db, la)
    await engine.evaluate_sharing(db, u.id, trigger="nightly")
    assert len(await signals_of(db, u.id, "SH-09")) == 11
    assert float((await rx.get_state(db, u.id)).sharing_score) <= 10
    assert await rx.active_for(db, u.id, "sharing") is None
    la = LoginAttempt(
        id=engine.uuid7(),
        attempted_at=clock.now(),
        user_id=u.id,
        identifier_hash=b"v" * 32,
        method="password",
        outcome="success",
        ip="185.2.2.2",
        network_type="tor",
    )
    db.add(la)
    await db.flush()
    await signals.on_login_attempt(db, la)
    assert await signals_of(db, u.id, "TO-07")
    assert (await rx.restriction_state(db, u.id)).step_up_required is False  # 15 < 40


# --------------------------------------------------------------------------- SCN-06


async def test_scn06_shared_pc_minor_and_restricted_device_reuse(db, monkeypatch) -> None:
    """Single company (D5): registered lab devices and AB-11 are gone."""
    await enforce(db)
    users = [await adult(db) for _ in range(6)]
    kid = await adult(db, minor=True, monitoring=False)
    d0, _ = await device_session(db, users[0].id, ip="49.36.20.1")
    for x in [*users[1:], kid]:
        db.add(
            UserDevice(
                id=engine.uuid7(),
                user_id=x.id,
                device_id=d0,
                trust_status="trusted",
                trusted_at=clock.now(),
                last_used_at=clock.now(),
            )
        )
    await db.flush()
    for x in users:
        assert "SH-11" in await signals.derive_daily_signals(db, x.id)  # (a) 4 pts each
    assert await signals.derive_daily_signals(db, kid.id) == []  # (c) minors: nothing computed
    assert await signals_of(db, kid.id) == []
    # (e) AB-10: device of an L3 account signs in to another account within 7 days
    bad = users[0]
    case = await engine.open_case(db, user_id=bad.id, family="sharing", level=3, opened_reason="engine_L3")
    await rx.apply_restriction(
        db,
        user_id=bad.id,
        level=3,
        family="sharing",
        source="engine",
        actor=engine.SYSTEM,
        case_id=case.id,
        ends_at=clock.now() + timedelta(hours=24),
    )
    other = users[1]
    la = LoginAttempt(
        id=engine.uuid7(),
        attempted_at=clock.now(),
        user_id=other.id,
        identifier_hash=b"o" * 32,
        method="password",
        outcome="success",
        device_id=d0,
    )
    db.add(la)
    await db.flush()
    await signals.on_login_attempt(db, la)
    assert await signals_of(db, other.id, "AB-10")
    assert (await rx.active_for(db, other.id, "sharing")) is None  # never restricts on its own


# --------------------------------------------------------------------------- SCN-09


async def hc_setup(db, monkeypatch, *, days=(8, 4, 0), l2_days_ago=5):
    u = await adult(db)
    d1, d3 = await two_cities(db, u.id, monkeypatch, BASE - timedelta(days=15))
    st = await rx.get_state(db, u.id)
    st.l2_issued_at = BASE - timedelta(days=l2_days_ago)
    for day in days[:-1]:
        await day_overlap(db, u.id, monkeypatch, [d1, d3], day)
    return u, d1, d3, days[-1]


async def test_scn09e_hc01_active_restricts_regardless_of_score(db, monkeypatch) -> None:
    await enforce(db, hc=True)
    await activate_rule(db, "HC-01", {"min_devices": 2, "min_days": 3, "window_days": 14})
    u, d1, d3, last = await hc_setup(db, monkeypatch)
    await day_overlap(db, u.id, monkeypatch, [d1, d3], last)
    r = await rx.active_for(db, u.id, "sharing")
    assert r is not None and r.level == 3 and r.hc_rule == "HC-01"
    ev = (await evals(db, u.id))[-1]
    assert (
        ev.action == "restrict_L3"
        and ev.gates["hc_rule"] == "HC-01"
        and len(ev.gates["hc"]["qualifying_days"]) == 3
    )
    assert float(ev.score) < 70  # score not required
    case = await db.get(SecurityCase, r.case_id)
    assert case.opened_reason == "engine_hc_L3" and case.hc_rule == "HC-01" and case.recommended_level is None


async def test_scn09f_hc01_shadow_or_switch_off_records_shadow_only(db, monkeypatch) -> None:
    await enforce(db, hc=False)  # master switch false (launch default)
    await activate_rule(db, "HC-01")
    u, d1, d3, last = await hc_setup(db, monkeypatch)
    await day_overlap(db, u.id, monkeypatch, [d1, d3], last)
    shadow = [e for e in await evals(db, u.id) if e.gates.get("hc_rule") == "HC-01"]
    assert shadow and shadow[-1].mode == "shadow" and shadow[-1].action == "restrict_L3"
    r = await rx.active_for(db, u.id, "sharing")
    assert r is None or r.level < 3 or r.hc_rule is None


async def test_scn09d_risk_mode_shadow_writes_evaluations_without_actions(db, monkeypatch) -> None:
    u = await adult(db)  # risk.mode default = shadow
    d1, d3 = await two_cities(db, u.id, monkeypatch, BASE - timedelta(days=11))
    for day in (9, 6, 3, 0):
        await day_overlap(db, u.id, monkeypatch, [d1, d3], day)
    rows = await evals(db, u.id)
    assert rows and all(e.mode == "shadow" for e in rows) and any(e.action != "none" for e in rows)
    assert await rx.active_restrictions(db, u.id) == []


async def test_scn09h_minor_with_hc_facts_gets_nothing(db, monkeypatch) -> None:
    await enforce(db, hc=True)
    await activate_rule(db, "HC-01")
    kid = await adult(db, minor=True)
    d1, d3 = await two_cities(db, kid.id, monkeypatch, BASE - timedelta(days=15))
    for day in (8, 4, 0):
        assert await day_overlap(db, kid.id, monkeypatch, [d1, d3], day) == []
    assert await signals_of(db, kid.id) == [] and await evals(db, kid.id) == []


async def test_scn09i_hc02_three_users_high_priority_never_l4(db, monkeypatch) -> None:
    await enforce(db, hc=True)
    await activate_rule(db, "HC-02", {"min_days": 2, "window_days": 7})
    u = await adult(db)
    freeze(monkeypatch, BASE - timedelta(days=8))
    legs = [
        await device_session(db, u.id, ip=ip, asn=asn, region=reg, os_family=os_)
        for ip, asn, reg, os_ in (
            ("49.36.10.5", 24560, "TG", "Windows"),
            ("183.82.1.9", 18209, "MH", "Mac OS X"),
            ("117.200.1.1", 17488, "KA", "Linux"),
        )
    ]
    st = await rx.get_state(db, u.id)
    st.l2_issued_at = BASE - timedelta(days=5)
    await day_overlap(db, u.id, monkeypatch, legs, 3)
    await day_overlap(db, u.id, monkeypatch, legs, 0)
    r = await rx.active_for(db, u.id, "sharing")
    assert r is not None and r.level == 3 and r.hc_rule == "HC-02"
    case = await db.get(SecurityCase, r.case_id)
    assert case.priority == "high" and case.recommended_level != 4


async def test_scn09c_deferral_keeps_attempt_session(db, monkeypatch) -> None:
    await enforce(db)
    u = await adult(db)
    a = await device_session(db, u.id, ip="49.36.10.5")
    b = await device_session(db, u.id, ip="183.82.1.9", asn=18209, region="MH")

    async def holding(session, ids):
        return {a[1]} & set(ids)

    ss.register_active_attempt_lookup(holding)
    try:
        case = await engine.open_case(db, user_id=u.id, family="sharing", level=3, opened_reason="engine_L3")
        r, _ = await rx.apply_restriction(
            db, user_id=u.id, level=3, family="sharing", source="engine", actor=engine.SYSTEM, case_id=case.id
        )
    finally:
        ss.register_active_attempt_lookup(None)
    assert r.deferred_until is not None and r.deferred_until - r.starts_at == timedelta(hours=3)
    assert (await db.get(AuthSession, a[1])).status == "active"
    assert (await db.get(AuthSession, b[1])).end_reason == "risk_L3"
    assert "l3_deferred" in (await rx.restriction_state(db, u.id)).restrictions


async def test_cb03_daily_limit_51st_not_applied_and_breaker_trips(db, monkeypatch) -> None:
    await enforce(db, hc=True)
    await set_policy(db, "risk.hc.circuit_breaker.max_daily_restrictions", 5)
    v = await activate_rule(db, "HC-01")
    for _ in range(5):
        x = await adult(db)
        db.add(
            AccountRestriction(
                id=engine.uuid7(),
                user_id=x.id,
                level=3,
                family="sharing",
                scope="learning_access",
                source="engine",
                starts_at=clock.now(),
                hc_rule="HC-01",
                created_at=clock.now(),
            )
        )
    await db.flush()
    u, d1, d3, last = await hc_setup(db, monkeypatch)
    await day_overlap(db, u.id, monkeypatch, [d1, d3], last)
    shadow = [e for e in await evals(db, u.id) if e.gates.get("breaker") == "tripped_daily_limit"]
    assert shadow and shadow[0].mode == "shadow"
    r = await rx.active_for(db, u.id, "sharing")
    assert r is None or r.hc_rule is None
    await db.refresh(v)
    assert (
        v.status == "shadow" and v.status_change_reason == "circuit_breaker" and v.status_changed_by is None
    )


async def _hc_decisions(db, outcomes: list[str]) -> None:
    from app.modules.security.models import CaseDecision

    for o in outcomes:
        x = await adult(db)
        case = await engine.open_case(
            db, user_id=x.id, family="sharing", level=3, opened_reason="engine_hc_L3"
        )
        db.add(
            AccountRestriction(
                id=engine.uuid7(),
                user_id=x.id,
                level=3,
                family="sharing",
                scope="learning_access",
                source="engine",
                starts_at=clock.now(),
                hc_rule="HC-01",
                case_id=case.id,
                created_at=clock.now(),
            )
        )
        reviewer = await adult(db)
        db.add(
            CaseDecision(
                id=engine.uuid7(),
                case_id=case.id,
                outcome=o,
                rationale="r",
                student_summary="x" * 60,
                decided_by=reviewer.id,
                created_at=clock.now(),
            )
        )
    await db.flush()


async def test_cb06_absolute_fp_threshold_and_per_rule_breaker(db, monkeypatch) -> None:
    v1 = await activate_rule(db, "HC-01")
    v2 = await activate_rule(db, "HC-02")
    await _hc_decisions(db, ["lift_false_positive", "uphold", "uphold"])
    assert not await engine.check_fp_breaker(db, "HC-01")  # 1 FP of 3 → stays active
    await _hc_decisions(db, ["lift_false_positive"])
    assert await engine.check_fp_breaker(db, "HC-01")  # 2 FP → trips
    await db.refresh(v1)
    await db.refresh(v2)
    assert v1.status == "shadow" and v1.status_change_reason == "circuit_breaker"
    assert v2.status == "active"  # CB-04: per rule
    alerts = (
        await db.execute(select(OutboxEvent).where(OutboxEvent.event_type == "security.alert_raised"))
    ).scalars()
    assert any(a.payload.get("kind") == "circuit_breaker" for a in alerts)
    assert (
        await db.execute(select(RiskRuleVersion).where(RiskRuleVersion.id == v1.id))
    ).scalar_one().status == "shadow"
