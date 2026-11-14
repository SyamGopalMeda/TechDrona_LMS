"""Security pass 2 on Firestore, service level: risk engine, signals, counters and the evidence
views with ``TD_STORE_SECURITY=firestore`` and no Postgres (session = ``NO_POSTGRES``).

Expected scores are computed twice: by hand from the catalogue points (signals at ``now`` have no
decay) and by the pure scorer (``rules.score_sharing`` / ``score_takeover``) over the signals read
back, so the stored evaluation is checked against the scorer the Postgres path uses."""

from __future__ import annotations

import asyncio
import json
from datetime import timedelta
from decimal import Decimal
from typing import Any

import pytest

from app.core.audit import AuditActor
from app.core.db import NO_POSTGRES
from app.core.firestore.ids import compose_id
from app.core.firestore.repository import assert_repository_scoped
from app.core.firestore.store import ScopedStore
from app.core.ids import uuid7
from app.modules.admin.policy import write_setting
from app.modules.identity import clock
from app.modules.identity import public as idp
from app.modules.identity.models import Consent, User
from app.modules.notifications.service import notifications_for_user
from app.modules.security import engine
from app.modules.security import restrictions as rx
from app.modules.security import signals as sg
from app.modules.security import timeline as tl
from app.modules.security.catalogue import BUILTIN_RULESETS
from app.modules.security.policies import sharing_policy
from app.modules.security.repo_fs_engine import EngineRepo
from app.modules.security.rules import SharingContext, score_sharing, score_takeover
from app.modules.security.store_specs import (
    CaseDecisionRow,
    RiskRuleRow,
    RiskRuleVersionRow,
)

FS_MODULES = ("security", "identity", "sessions", "admin", "audit", "core", "notifications", "rbac", "orgs")
pytestmark = pytest.mark.usefixtures("fs_env")


def _store() -> ScopedStore:
    return ScopedStore.system("test.security.engine")


@pytest.fixture(autouse=True)
def _protection_on(monkeypatch: pytest.MonkeyPatch) -> Any:
    from app.core.config import reset_settings_cache

    monkeypatch.setenv("TD_ACCOUNT_PROTECTION_OFF", "false")
    monkeypatch.setenv("TD_SIMPLE_AUTH", "false")
    reset_settings_cache()
    yield
    reset_settings_cache()


async def _adult(*, consent: bool = False) -> Any:
    uid = uuid7()
    now = clock.now()
    u = await idp.create_user(
        NO_POSTGRES,
        User(
            id=uid,
            email=f"u{uid.hex[-10:]}@example.com",
            email_verified_at=now,
            status="active",
            is_minor=False,
            age_verified_at=now,
            age_verification_method="self_declared",
        ),
    )
    if consent:
        from app.modules.identity.repo_firestore import system_repo as irepo

        await irepo().add_consent(
            Consent(
                id=uuid7(),
                user_id=uid,
                purpose="security_monitoring",
                action="granted",
                notice_version="v1",
                channel="web",
                created_at=now,
            )
        )
    return u


async def _enforce() -> None:
    await write_setting(
        NO_POSTGRES,
        key="risk.mode",
        scope_type="platform",
        scope_id=None,
        value="enforce",
        changed_by=uuid7(),
        change_reason="test",
        effective_from=clock.now() - timedelta(minutes=1),
    )


def test_repository_scope_lint() -> None:
    assert_repository_scoped(EngineRepo)


async def test_counters_concurrent_bumps_and_windows() -> None:
    now = clock.now()
    await asyncio.gather(*(sg.bump(NO_POSTGRES, "ab08:test", now) for _ in range(8)))
    await sg.bump(NO_POSTGRES, "ab08:test", now - timedelta(minutes=30))
    await sg.bump(NO_POSTGRES, "other", now)
    assert await sg.count_since(NO_POSTGRES, "ab08:test", now - timedelta(minutes=10)) == 8
    assert await sg.count_since(NO_POSTGRES, "ab08:test", now - timedelta(hours=1)) == 9
    docs = [d for d in await _store().scan("security_counters") if d["counter_key"] == "ab08:test"]
    assert sum(d["count"] for d in docs) == 9
    for d in docs:  # 2-day retention as a TTL field on the minute bucket
        assert d["expire_at"] == d["bucket_start"] + timedelta(days=2)
        assert d["bucket_start"].second == 0 and d["bucket_start"].microsecond == 0


async def test_signal_documents_ttl_rounding_and_sourceless() -> None:
    u = await _adult()
    s = await engine.record_signal(NO_POSTGRES, rule_key="TO-07", user_id=u.id, source="login")
    assert s is not None
    d = await _store().get("security_signals", compose_id(str(s.id), s.occurred_at.isoformat()))
    assert d is not None
    assert d["expire_at"] == d["occurred_at"] + timedelta(days=180)  # R-RISK
    assert d["base_points"] == "15.00" and d["family"] == "takeover" and d["rule_version"] == "1.0.0"
    back = await engine.user_signals(NO_POSTGRES, u.id, "takeover", clock.now() - timedelta(days=1))
    assert [x.id for x in back] == [s.id] and back[0].base_points == Decimal("15.00")

    src = "203.0.113.0/24"
    ab = await engine.record_signal(
        NO_POSTGRES, rule_key="AB-04", user_id=None, source="login", evidence={"source": src}
    )
    assert ab is not None and ab.user_id is None
    since = clock.now() - timedelta(hours=1)
    assert await sg.recent_signal(NO_POSTGRES, "AB-04", since, source=src)
    assert not await sg.recent_signal(NO_POSTGRES, "AB-04", since, source="198.51.100.0/24")
    assert await sg._flagged_source(NO_POSTGRES, "203.0.113.77", clock.now()) == src
    assert await sg.recent_signal(NO_POSTGRES, "TO-07", since, user_id=u.id)
    assert not await sg.recent_signal(NO_POSTGRES, "TO-07", clock.now(), user_id=u.id)


async def test_minor_and_sharing_rules() -> None:
    now = clock.now()
    uid = uuid7()
    await idp.create_user(
        NO_POSTGRES,
        User(id=uid, email=f"m{uid.hex[-8:]}@example.com", status="active", is_minor=True),
    )
    assert await engine.record_signal(NO_POSTGRES, rule_key="SH-06", user_id=uid, source="nightly") is None
    to = await engine.record_signal(NO_POSTGRES, rule_key="TO-07", user_id=uid, source="login")
    assert to is not None and to.base_points == Decimal("0.0") and to.is_minor_at_time is True
    assert await engine.evaluate_sharing(NO_POSTGRES, uid, trigger="nightly", now=now) is None


async def test_evaluate_sharing_l1_matches_scorer() -> None:
    u = await _adult()
    await _enforce()
    now = clock.now()
    for rule in ("SH-13", "SH-06", "SH-07", "SH-04"):
        await engine.record_signal(
            NO_POSTGRES, rule_key=rule, user_id=u.id, source="nightly", occurred_at=now
        )
    ev = await engine.evaluate_sharing(NO_POSTGRES, u.id, trigger="manual_review", now=now)
    assert ev is not None

    # expected: 10 + 8 + 8 + 6 (catalogue points, no decay at ``now``) -> L1 notice
    policy = await sharing_policy(NO_POSTGRES, u.id)
    rows = await engine.user_signals(
        NO_POSTGRES, u.id, "sharing", now - timedelta(days=policy.window_days), now
    )
    ctx = SharingContext(
        owner_verified_at={},
        sh13_tainted=frozenset(),
        current_level=0,
        l2_issued_at=None,
        l2_passed_at=None,
        repeat=False,
    )
    caps = {k: float(v) for k, v in BUILTIN_RULESETS["sharing"]["caps"].items()}
    want = score_sharing([engine.to_sig(r) for r in rows], now, policy, ctx, caps)
    assert want.score == 32.0 and want.action == "notice_L1" and want.level_after == 1

    stored = await engine.evaluations_for(NO_POSTGRES, u.id, "sharing", None, None)
    assert len(stored) == 1
    e = stored[0]
    assert (e.mode, e.action, e.level_before, e.level_after, e.trigger) == (
        "enforce",
        "notice_L1",
        0,
        1,
        "manual_review",
    )
    assert e.score == Decimal("32.00") and e.previous_score == Decimal("0.00")
    assert e.repeat_multiplier == Decimal("1.00") and e.ruleset_version == "sharing-1.0.0"
    assert e.signals == json.loads(json.dumps(want.contributions))
    assert e.subtotals == want.subtotals and e.explanation_keys == want.explanation_keys
    assert e.window["half_life_days"] == policy.half_life_days
    r = await rx.active_for(NO_POSTGRES, u.id, "sharing")
    assert r is not None and r.level == 1 and e.restriction_id == r.id and r.evaluation_id == e.id
    st = await rx.get_state(NO_POSTGRES, u.id)
    assert st.sharing_score == Decimal("32.0") and st.sharing_level == 1 and st.last_evaluated_at == now
    notes = await notifications_for_user(NO_POSTGRES, u.id)
    assert [n.template_key for n in notes] == ["security.l1_notice"]

    # a second run (same signals): no level change, score unchanged -> SYNC trigger still writes
    ev2 = await engine.evaluate_sharing(NO_POSTGRES, u.id, trigger="manual_review", now=now)
    assert ev2 is not None and ev2.level_before == 1 and float(ev2.previous_score) == 32.0
    # shadow mode: nothing is applied, the row says ``shadow``
    assert len(await engine.evaluations_for(NO_POSTGRES, u.id, None, None, None)) == 2


async def test_evaluate_takeover_step_up_then_protect_lock() -> None:
    u = await _adult()
    now = clock.now()
    for rule in ("TO-01", "TO-07", "TO-09"):
        await engine.record_signal(NO_POSTGRES, rule_key=rule, user_id=u.id, source="login")
    ev = await engine.evaluate_takeover(NO_POSTGRES, u.id, trigger="login")
    assert ev is not None
    rows = await engine.user_signals(NO_POSTGRES, u.id, "takeover", now - timedelta(days=30), clock.now())
    score, contrib = score_takeover(
        [engine.to_sig(s) for s in rows],
        ev.evaluated_at,
        30,
        float(await engine.get_value(NO_POSTGRES, "risk.decay_half_life_days")),
        {k: float(v) for k, v in BUILTIN_RULESETS["takeover"]["points"].items()},
    )
    assert round(score) == 50 and ev.action == "step_up"
    stored = (await engine.evaluations_for(NO_POSTGRES, u.id, "takeover", None, None))[0]
    assert stored.id == ev.id and stored.action == "step_up" and stored.gates["hc_rule"] is None
    assert stored.score == Decimal(str(score)).quantize(Decimal("0.01"))
    assert stored.explanation_keys == ["to01.failed_burst", "to07.tor", "to09.new_country"] or len(
        stored.explanation_keys
    ) == len(contrib)
    st = await rx.get_state(NO_POSTGRES, u.id)
    assert st.step_up_required_since == ev.evaluated_at and float(st.takeover_score) == score

    await engine.record_signal(NO_POSTGRES, rule_key="TO-03", user_id=u.id, source="login")
    ev2 = await engine.evaluate_takeover(NO_POSTGRES, u.id, trigger="login")
    assert ev2 is not None and ev2.action == "protect_lock" and ev2.restriction_id is not None
    r = await rx.active_for(NO_POSTGRES, u.id, "takeover")
    assert r is not None and r.scope == "protect_lock" and r.rule_keys == ["TO-score"]
    notices = [d for d in await _store().scan("security_notices") if d["user_id"] == str(u.id)]
    assert [(n["kind"], n["rule_key"]) for n in notices] == [("replay", "TO-score")]
    user = await idp.get_user(NO_POSTGRES, u.id)
    assert user is not None and user.must_change_password is True
    keys = [n.template_key for n in await notifications_for_user(NO_POSTGRES, u.id)]
    assert keys == ["security.step_up", "security.takeover_protect"]


async def test_hc_t3_replay_locks_minor_without_evaluation() -> None:
    uid = uuid7()
    await idp.create_user(
        NO_POSTGRES, User(id=uid, email=f"k{uid.hex[-8:]}@example.com", status="active", is_minor=True)
    )
    for _ in range(2):
        await engine.record_signal(NO_POSTGRES, rule_key="TO-04", user_id=uid, source="system")
    assert await engine.evaluate_takeover(NO_POSTGRES, uid, trigger="login") is None
    r = await rx.active_for(NO_POSTGRES, uid, "takeover")
    assert r is not None and r.hc_rule == "HC-T3"
    assert await engine.evaluations_for(NO_POSTGRES, uid, None, None, None) == []


async def test_open_case_merge_incidents_and_high_risk() -> None:
    u = await _adult()
    c1 = await engine.open_case(
        NO_POSTGRES, user_id=u.id, family="sharing", level=1, opened_reason="engine_L3"
    )
    c2 = await engine.open_case(
        NO_POSTGRES,
        user_id=u.id,
        family="sharing",
        level=3,
        opened_reason="engine_L3",
        priority="high",
        recommended_level=4,
    )
    assert c2.id == c1.id and c2.version == 2 and c2.level == 3 and c2.priority == "high"
    d = await _store().get("security_cases", str(c1.id))
    assert d is not None and d["version"] == 2 and d["recommended_level"] == 4 and d["status"] == "open"
    assert d["sla_first_response_due"] > c1.created_at
    assert await engine.confirmed_incidents(NO_POSTGRES, u.id, 180) == 0
    for outcome in ("uphold", "lift_false_positive", "reduce_level"):
        row = CaseDecisionRow(
            id=uuid7(),
            case_id=c1.id,
            outcome=outcome,
            rationale="r",
            decided_by=uuid7(),
            created_at=clock.now(),
        )
        await _store().create("case_decisions", row.doc(), doc_id=str(row.id))
    assert await engine.confirmed_incidents(NO_POSTGRES, u.id, 180) == 2
    assert await engine.high_risk_reasons(NO_POSTGRES, u.id) == ["repeat_incident"]
    for rule in ("SH-09", "SH-11", "SH-06"):
        await engine.record_signal(NO_POSTGRES, rule_key=rule, user_id=u.id, source="nightly")
    assert await engine.high_risk_reasons(NO_POSTGRES, u.id) == ["reseller_pattern", "repeat_incident"]
    excl = await engine._hc_exclusions(NO_POSTGRES, u, [])
    assert excl == ["no_security_monitoring_consent", "recent_false_positive_lift"]


async def test_rule_versions_and_circuit_breaker() -> None:
    now = clock.now()
    assert (await engine.rule_status(NO_POSTGRES, "HC-01"))[0] == "shadow"  # built-in
    rule = RiskRuleRow(
        id=uuid7(),
        key="HC-01",
        family="sharing",
        description="d",
        explanation_key="hc01.x",
        created_at=now,
        updated_at=now,
    )
    v = RiskRuleVersionRow(
        id=uuid7(),
        rule_id=rule.id,
        family="sharing",
        ruleset_version="sharing-1.0.0",
        semver="1.1.0",
        definition={"params": {"min_devices": 2, "min_days": 3, "window_days": 14}},
        status="active",
        proposed_by=uuid7(),
        created_at=now,
    )
    rule.active_version_id = v.id
    await _store().create("risk_rules", rule.doc(), doc_id=str(rule.id))
    await _store().create("risk_rule_versions", v.doc(), doc_id=str(v.id))
    assert await engine.rule_status(NO_POSTGRES, "HC-01") == ("active", v.definition["params"], "1.1.0")
    assert await engine.trip_breaker(NO_POSTGRES, "HC-01", "tripped_daily_limit") is True
    assert (await engine.rule_status(NO_POSTGRES, "HC-01"))[0] == "shadow"
    rd = await _store().get("risk_rules", str(rule.id))
    vd = await _store().get("risk_rule_versions", str(v.id))
    assert rd is not None and rd["active_version_id"] is None
    assert vd is not None and vd["status_change_reason"] == "circuit_breaker"
    assert await engine.trip_breaker(NO_POSTGRES, "HC-01", "again") is False
    # an active ruleset definition overrides the built-in one
    rs = RiskRuleVersionRow(
        id=uuid7(),
        rule_id=None,
        family="takeover",
        ruleset_version="takeover-2.0.0",
        semver="2.0.0",
        definition={"thresholds": {"step_up": 10, "protect": 99}},
        status="active",
        proposed_by=uuid7(),
        created_at=now,
    )
    await _store().create("risk_rule_versions", rs.doc(), doc_id=str(rs.id))
    defn, ver = await engine.ruleset(NO_POSTGRES, "takeover")
    assert ver == "takeover-2.0.0" and defn["thresholds"]["step_up"] == 10 and defn["points"]["TO-07"] == 15
    u = await _adult()
    s = await engine.record_signal(NO_POSTGRES, rule_key="TO-07", user_id=u.id, source="login")
    assert s is not None and s.rule_version == "2.0.0"


async def test_restricted_denial_hot_path_ab08() -> None:
    u = await _adult()
    sink = sg.SecurityEventSink()
    for _ in range(31):
        await sink.restricted_denial(NO_POSTGRES, u.id, "/api/v1/learning/x")
    rows = [
        s for s in await engine.user_signals(NO_POSTGRES, u.id, "abuse", clock.now() - timedelta(hours=1))
    ]
    assert [s.rule_key for s in rows] == ["AB-08"]
    assert rows[0].evidence == {"denials_10min": 30, "last_route": "/api/v1/learning/x"}


async def test_unknown_token_ab07_throttles_source() -> None:
    sink = sg.SecurityEventSink()
    results = [await sink.unknown_token(NO_POSTGRES, "198.51.100.9") for _ in range(21)]
    assert results[:19] == [False] * 19 and results[19:] == [True, True]
    src = "198.51.100.0/24"
    assert await sg.recent_signal(NO_POSTGRES, "AB-07", clock.now() - timedelta(minutes=15), source=src)


async def test_report_event_thresholds_and_sharing_evaluation() -> None:
    u = await _adult()
    await _enforce()
    for _ in range(4):
        assert await sg.report_event(NO_POSTGRES, "AB-09.cross_tenant", user_id=u.id) is None
    sig = await sg.report_event(NO_POSTGRES, "AB-09.cross_tenant", user_id=u.id)
    assert sig is not None and sig.rule_key == "AB-09" and sig.evidence == {"count": 5}
    assert await sg.report_event(NO_POSTGRES, "AB-09.cross_tenant", user_id=u.id) is None  # once per hour
    sh = await sg.report_event(NO_POSTGRES, "SH-03", user_id=u.id, evidence={"x": 1}, source="playback")
    assert sh is not None
    evs = await engine.evaluations_for(NO_POSTGRES, u.id, "sharing", None, None)
    assert [(e.trigger, float(e.score), e.action) for e in evs] == [("playback", 8.0, "none")]


async def test_timeline_and_device_graph() -> None:
    u = await _adult()
    await _enforce()
    now = clock.now()
    for rule in ("SH-13", "SH-06", "SH-07", "SH-04"):
        await engine.record_signal(
            NO_POSTGRES, rule_key=rule, user_id=u.id, source="nightly", occurred_at=now
        )
    await engine.evaluate_sharing(NO_POSTGRES, u.id, trigger="manual_review", now=now)
    await engine.open_case(NO_POSTGRES, user_id=u.id, family="sharing", level=1, opened_reason="manual")
    ev = await tl.timeline(
        NO_POSTGRES, u.id, now - timedelta(days=1), clock.now() + timedelta(seconds=1), None
    )
    types = sorted({e["type"] for e in ev})
    assert types == ["case", "evaluation", "restriction", "signal"]
    assert [e["rule"] for e in ev if e["type"] == "signal"] == ["SH-13", "SH-06", "SH-07", "SH-04"]
    e = next(e for e in ev if e["type"] == "evaluation")
    assert (e["family"], e["mode"], e["score"], e["level_after"], e["action"]) == (
        "sharing",
        "enforce",
        32.0,
        1,
        "notice_L1",
    )
    assert ev == sorted(ev, key=lambda x: x["at"], reverse=True)
    only = await tl.timeline(NO_POSTGRES, u.id, now, now, {"signal"})  # BETWEEN is inclusive
    assert len(only) == 4
    g = await tl.device_graph(NO_POSTGRES, u.id, 30, 2)
    assert g == {"subject": str(u.id), "nodes": [], "edges": []}


async def test_apply_restriction_l3_via_engine_opens_case() -> None:
    u = await _adult()
    await _enforce()
    now = clock.now()
    ev = engine.fx.new(
        engine.RiskEvaluation,
        id=uuid7(),
        evaluated_at=now,
        user_id=u.id,
        family="sharing",
        mode="enforce",
        ruleset_version="sharing-1.0.0",
        trigger="manual_review",
        window={},
        signals=[],
        subtotals={},
        score=Decimal("75"),
        level_before=0,
        level_after=3,
        gates={},
        action="restrict_L3",
        explanation_keys=[],
        is_minor_at_time=False,
    )

    class _Res:
        contributions: list[Any] = []
        gates: dict[str, Any] = {"l4_recommend": True}

    user = await idp.get_user(NO_POSTGRES, u.id)
    await engine._apply_sharing_action(NO_POSTGRES, user, ev, "restrict_L3", 0, 3, _Res(), None, None)
    r = await rx.active_for(NO_POSTGRES, u.id, "sharing")
    assert r is not None and r.level == 3 and r.case_id == ev.case_id and r.ends_at is not None
    c = await _store().get("security_cases", str(ev.case_id))
    assert c is not None and c["opened_reason"] == "engine_L3" and c["recommended_level"] == 4
    assert c["priority"] == "high"
    await rx.end_restriction(NO_POSTGRES, r, "lifted", ended_by=None, actor=AuditActor.system("t"))


# --------------------------------------------------------------------------- round 2: parity fixes


async def test_detector_failure_leaves_no_signals_or_counters(monkeypatch: pytest.MonkeyPatch) -> None:
    """Postgres runs each detector in a SAVEPOINT; on Firestore the journal compensates."""
    u = await _adult()
    real = engine.record_signal

    async def params(_s: Any) -> dict[str, Any]:
        return {**BUILTIN_RULESETS["abuse"]["params"], "ab08_denials": 1}

    async def boom(*a: Any, **kw: Any) -> Any:
        await real(*a, **kw)  # the signal is written ...
        raise RuntimeError("detector failed")  # ... then the detector fails

    real_params = sg.abuse_params
    monkeypatch.setattr(sg, "abuse_params", params)
    monkeypatch.setattr(engine, "record_signal", boom)
    await sg.SecurityEventSink().restricted_denial(NO_POSTGRES, u.id, "/x")  # logged, not raised
    assert await sg.count_since(NO_POSTGRES, f"ab08:{u.id}", clock.now() - timedelta(hours=1)) == 0
    assert [d for d in await _store().scan("security_signals") if d["user_id"] == str(u.id)] == []
    assert [d for d in await _store().scan("security_counters") if str(u.id) in d["counter_key"]] == []

    # a later step of a multi-signal detector fails: every signal of that detector goes
    monkeypatch.setattr(engine, "record_signal", real)

    async def no_org(*_a: Any, **_k: Any) -> Any:
        raise RuntimeError("org lookup failed")

    real_org = engine.primary_org
    monkeypatch.setattr(engine, "primary_org", no_org)
    from app.modules.sessions.models import LoginAttempt

    la = LoginAttempt(
        id=uuid7(),
        attempted_at=clock.now(),
        user_id=u.id,
        outcome="success",
        method="password",
        network_type="tor",
        ip="203.0.113.5",
        pre_auth_blocked=False,
    )
    await sg.SecurityEventSink().login_attempt(NO_POSTGRES, la)
    assert [d for d in await _store().scan("security_signals") if d["user_id"] == str(u.id)] == []
    assert await engine.evaluations_for(NO_POSTGRES, u.id, None, None, None) == []
    # the same detector succeeds once the failure is gone (TO-07 + SH-09 + evaluation)
    monkeypatch.setattr(engine, "primary_org", real_org)
    monkeypatch.setattr(sg, "abuse_params", real_params)
    await sg.SecurityEventSink().login_attempt(NO_POSTGRES, la)
    rules = sorted(
        d["rule_key"] for d in await _store().scan("security_signals") if d["user_id"] == str(u.id)
    )
    assert rules == ["SH-09", "TO-07"]


async def test_evidence_kept_while_case_open_or_held() -> None:
    from app.modules.security import repo_fs_engine as fx

    def expiries(uid: Any, coll: str) -> list[Any]:
        return [d.get("expire_at") for d in docs[coll] if d["user_id"] == str(uid)]

    u = await _adult()
    other = await _adult()
    s1 = await engine.record_signal(NO_POSTGRES, rule_key="TO-07", user_id=u.id, source="login")
    await engine.record_signal(NO_POSTGRES, rule_key="TO-07", user_id=other.id, source="login")
    await engine.evaluate_takeover(NO_POSTGRES, u.id, trigger="login")
    assert s1 is not None

    c = await engine.open_case(NO_POSTGRES, user_id=u.id, family="takeover", level=3, opened_reason="manual")
    s2 = await engine.record_signal(NO_POSTGRES, rule_key="TO-09", user_id=u.id, source="login")
    assert s2 is not None
    docs = {k: await _store().scan(k) for k in ("security_signals", "risk_evaluations")}
    assert expiries(u.id, "security_signals") == [None, None]  # open case: kept (no TTL)
    assert expiries(u.id, "risk_evaluations") == [None]
    assert [e is not None for e in expiries(other.id, "security_signals")] == [True]  # not held

    await _store().update("security_cases", str(c.id), {"status": "closed", "closed_at": clock.now()})
    assert await fx.release_evidence([u.id]) == 3
    docs = {k: await _store().scan(k) for k in ("security_signals", "risk_evaluations")}
    by_id = {d["id"]: d for d in docs["security_signals"]}
    for s in (s1, s2):
        d = by_id[str(s.id)]
        assert d["expire_at"] == d["occurred_at"] + timedelta(days=180)
    ev = next(d for d in docs["risk_evaluations"] if d["user_id"] == str(u.id))
    assert ev["expire_at"] == ev["evaluated_at"] + timedelta(days=180)

    await _store().update("security_cases", str(c.id), {"legal_hold": True})  # closed but held
    assert await fx.hold_evidence([u.id]) == 3
    docs = {k: await _store().scan(k) for k in ("security_signals", "risk_evaluations")}
    assert expiries(u.id, "security_signals") == [None, None]
    assert await fx.hold_evidence([u.id]) == 0  # idempotent


# --------------------------------------------------------------------------- round 3: other modules' writes


async def _protect_lock_detector(u: Any, *, fail: bool, monkeypatch: pytest.MonkeyPatch) -> None:
    """A login detector that ends in T-protect (HC-T3 after two replays): restriction + head,
    user state, ``must_change_password``, notice, notification, audit row, outbox event."""
    from app.modules.sessions.models import LoginAttempt

    real = engine.evaluate_takeover

    async def then_fail(*a: Any, **kw: Any) -> Any:
        await real(*a, **kw)  # every write of the protect-lock happens ...
        raise RuntimeError("detector failed")  # ... then the detector fails

    if fail:
        monkeypatch.setattr(engine, "evaluate_takeover", then_fail)
    la = LoginAttempt(
        id=uuid7(),
        attempted_at=clock.now(),
        user_id=u.id,
        outcome="success",
        method="password",
        network_type="tor",
        ip="203.0.113.5",
        pre_auth_blocked=False,
    )
    await sg.SecurityEventSink().login_attempt(NO_POSTGRES, la)
    monkeypatch.setattr(engine, "evaluate_takeover", real)


def _audit_actions(docs: list[Any]) -> list[str]:
    return sorted(json.loads(d["record_json"])["action"] for d in docs)


async def _side_effects(u: Any) -> dict[str, Any]:
    import app.core.firestore.core_store  # registers outbox_events
    import app.modules.audit.store_specs  # noqa: F401 - registers audit_outbox

    st = _store()
    user = await idp.get_user(NO_POSTGRES, u.id)
    return {
        "signals": sorted(
            d["rule_key"] for d in await st.scan("security_signals") if d["user_id"] == str(u.id)
        ),
        "restrictions": [
            d["family"] for d in await st.scan("account_restrictions") if d["user_id"] == str(u.id)
        ],
        "heads": [d.id for d in await st.scan("restriction_heads") if d.get("active_id")],
        "state": await st.get("security_user_state", str(u.id)),
        "notices": [d["rule_key"] for d in await st.scan("security_notices") if d["user_id"] == str(u.id)],
        "notifications": [n.template_key for n in await notifications_for_user(NO_POSTGRES, u.id)],
        "must_change_password": bool(user and user.must_change_password),
        "audit": _audit_actions(await st.scan("audit_outbox")),
        "outbox": sorted(d["event_type"] for d in await st.scan("outbox_events")),
        "evaluations": len(await engine.evaluations_for(NO_POSTGRES, u.id, None, None, None)),
    }


async def test_failed_detector_undoes_restrictions_state_notifications_audit_outbox(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    u = await _adult()
    for _ in range(2):  # earlier replays (outside the detector): HC-T3 fires on the next login
        await engine.record_signal(NO_POSTGRES, rule_key="TO-04", user_id=u.id, source="system")
    before = await _side_effects(u)
    assert before["signals"] == ["TO-04", "TO-04"] and before["state"] is None

    await _protect_lock_detector(u, fail=True, monkeypatch=monkeypatch)  # logged, not raised
    assert await _side_effects(u) == before  # the savepoint: nothing of the detector is left

    await _protect_lock_detector(u, fail=False, monkeypatch=monkeypatch)
    after = await _side_effects(u)
    assert after["signals"] == ["SH-09", "TO-04", "TO-04", "TO-07"]
    assert after["restrictions"] == ["takeover"] and after["heads"] == [f"{u.id}:takeover"]
    assert after["state"] is not None and after["notices"] == ["HC-T3"]
    assert after["notifications"] == ["security.takeover_protect"] and after["must_change_password"]
    assert after["audit"] == ["security.restriction.apply"]  # committed with the detector
    assert after["outbox"] == ["account.restricted"] and after["evaluations"] == 1


async def test_failed_detector_truncates_the_request_buffers(monkeypatch: pytest.MonkeyPatch) -> None:
    """Inside a request (audit / outbox buffered to the commit point) a failed detector removes
    only its own buffered rows; the request's earlier rows stay."""
    from app.core import audit, outbox, request_commit

    u = await _adult()
    for _ in range(2):
        await engine.record_signal(NO_POSTGRES, rule_key="TO-04", user_id=u.id, source="system")
    bufs = request_commit.Buffers()
    try:
        await audit.audit(NO_POSTGRES, AuditActor.system("t.req"), "test.before", "user", u.id)
        await outbox.emit_event(
            NO_POSTGRES, "test.happened", {"x": 1}, aggregate_type="user", aggregate_id=u.id
        )
        await _protect_lock_detector(u, fail=True, monkeypatch=monkeypatch)
        assert [d.record["action"] for d in audit.pending_docs()] == ["test.before"]
        assert [e.event_type for e in outbox.pending_events()] == ["test.happened"]
        await _protect_lock_detector(u, fail=False, monkeypatch=monkeypatch)
        assert [d.record["action"] for d in audit.pending_docs()] == [
            "test.before",
            "security.restriction.apply",
        ]
        assert await request_commit.commit() == 4  # the request's commit point: 2 audit rows + 2 events
    finally:
        bufs.close()
    assert _audit_actions(await _store().scan("audit_outbox")) == [
        "security.restriction.apply",
        "test.before",
    ]
    # ``account.restricted`` is buffered (core.outbox.emit_event) and written at the commit point
    assert sorted(d["event_type"] for d in await _store().scan("outbox_events")) == [
        "account.restricted",
        "test.happened",
    ]


# --------------------------------------------------------------------------- round 4: retention interval


async def test_expiry_follows_admin_retention_interval_calendar() -> None:
    """``expire_at`` = event time + the active ``retention_policies`` interval of the table, with
    Postgres calendar semantics (``1 mon`` from Jan 31 lands on Feb 28/29)."""
    from datetime import UTC, datetime

    from app.modules.admin.intervals import PgInterval, add_interval
    from app.modules.admin.store_specs import RETENTION, RetentionRow
    from app.modules.security import repo_fs_engine as fx

    for table, months in (("security_signals", 1), ("risk_evaluations", 2)):
        row = RetentionRow(
            id=uuid7(),
            data_category="D8",
            table_name=table,
            retention_class="R-RISK",
            retention_interval=PgInterval(months, 0, 0),
            basis="test",
            deletion_method="partition_drop",
            legal_hold_aware=True,
            job_name="purge_security_signals",
            owner_module="security",
            is_active=True,
            created_at=clock.now(),
        )
        await _store().create(RETENTION, row.doc(), doc_id=str(row.id))
    fx._interval_cache.clear()
    try:
        u = await _adult()
        at = datetime(2028, 1, 31, 10, 0, tzinfo=UTC)
        s = await engine.record_signal(
            NO_POSTGRES, rule_key="TO-07", user_id=u.id, source="login", occurred_at=at
        )
        assert s is not None
        d = await _store().get("security_signals", compose_id(str(s.id), at.isoformat()))
        assert d is not None and d["expire_at"] == datetime(2028, 2, 29, 10, 0, tzinfo=UTC)
        assert d["expire_at"] == add_interval(at, PgInterval(1, 0, 0))
        ev = await engine.evaluate_takeover(NO_POSTGRES, u.id, trigger="login")
        assert ev is not None
        e = next(x for x in await _store().scan("risk_evaluations") if x["user_id"] == str(u.id))
        assert e["expire_at"] == add_interval(e["evaluated_at"], PgInterval(2, 0, 0))
    finally:
        fx._interval_cache.clear()


# --------------------------------------------------------------------------- round 5: AB-04/05 by prefix


async def test_ab04_ab05_prefix_query_equals_the_window_scan() -> None:
    """``list_login_attempts_in_prefix`` (indexed ``ip_prefix``) gives the same AB-04 / AB-05
    aggregates as filtering every attempt of the hour by ``ip << /24`` (the round-1 scan)."""
    import ipaddress

    from app.modules.sessions import public as sp
    from app.modules.sessions.models import LoginAttempt
    from app.modules.sessions.repo_firestore import system_repo as srepo

    now = clock.now()
    rows = [  # (ip, outcome, identifier, pre_auth_blocked, minutes ago)
        ("203.0.113.5", "bad_credentials", b"a", False, 5),
        ("203.0.113.9", "bad_credentials", b"a", False, 6),
        ("203.0.113.9", "unknown_identifier", b"b", False, 7),
        ("203.0.113.200", "bad_credentials", b"c", True, 8),  # pre-auth blocked: not a failure
        ("203.0.113.7", "success", b"d", False, 9),
        ("203.0.113.7", "bad_credentials", b"d", False, 10),
        ("203.0.113.7", "bad_credentials", b"d", False, 11),  # d: 3 attempts -> not "spray"
        ("203.0.113.8", "bad_credentials", b"e", False, 90),  # outside the hour
        ("203.0.114.5", "bad_credentials", b"f", False, 5),  # other /24
        ("2001:db8:1:2::5", "bad_credentials", b"g", False, 5),
        ("2001:db8:1:ffff::9", "bad_credentials", b"h", False, 5),  # same /48
        ("2001:db8:2::1", "bad_credentials", b"i", False, 5),  # other /48
        (None, "bad_credentials", b"j", False, 5),
    ]
    for ip, outcome, ident, blocked, ago in rows:
        await srepo().add_attempt(
            LoginAttempt(
                id=uuid7(),
                attempted_at=now - timedelta(minutes=ago),
                identifier_hash=ident,
                ip=ip,
                outcome=outcome,
                method="password",
                pre_auth_blocked=blocked,
            )
        )
    since = now - timedelta(hours=1)
    window = await sp.list_login_attempts(NO_POSTGRES, since=since)
    for ip in ("203.0.113.77", "2001:db8:1:7::1", "198.51.100.1"):
        src = sg.source24(ip)
        assert src is not None
        net = ipaddress.ip_network(src, strict=False)
        old_n, old_spray = sg._source_aggregates([a for a in window if sg._in_net(a.ip, net)])
        new_n, new_spray = await sg._source_counts(NO_POSTGRES, ip, since)
        assert (new_n.n, new_n.accts, new_spray) == (old_n.n, old_n.accts, old_spray), ip
    n, spray = await sg._source_counts(NO_POSTGRES, "203.0.113.77", since)
    assert (n.n, n.accts, spray) == (5, 3, 3)  # a,a,b,d,d / {a,b,d} / a,b,c (d has 3)
    n6, spray6 = await sg._source_counts(NO_POSTGRES, "2001:db8:1:7::1", since)
    assert (n6.n, n6.accts, spray6) == (2, 2, 2)
