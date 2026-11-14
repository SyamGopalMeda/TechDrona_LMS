"""DEV / DEMO DATA ONLY — worked security scenarios for the reviewer console, the student
restricted screen and the Playwright ``@integration`` suite. Refuses to run when ``APP_ENV`` is
production.

Run after ``python -m app.seeds.dev_users``:  ``python -m app.seeds.security_demo``

Each fixture is a separate synthetic student, so one seed serves every spec in one pass and
``student@dev.techdrona.local`` stays a clean learner (no case, never restricted):

* ``restricted.student@`` — two devices on distant fixed-line networks (TG / MH) with S3
  overlaps on 4 days (worked example B, RE §5.1) → real ``security_signals`` rows, an ``enforce``
  ``risk_evaluations`` row that links them (``restrict_L3``), the L3 restriction pointing at that
  evaluation and its ``SEC-`` case. **No** unblock request (the identity spec files one).
  ``email_verified_at`` is ≥ 30 days before the restriction, so AUTH-21 re-verification is
  eligible once a reviewer lifts it.
* ``reverify.student@`` — the same L3 scenario, already decided ``lift_false_positive`` by
  ``security@`` → restriction ``lift_pending`` (the SCN-10 reverify spec consumes it).
* ``suspended.student@`` — the L3 scenario plus reseller-pattern signals (SH-06/09/11 → the
  case is ``is_high_risk``), escalated to **L4** by ``admin@`` (not reviewer A ``security@`` nor
  reviewer B ``security2@``), with a submitted ``APL-`` unblock request: the dual-control
  SEC-09/SEC-10 fixture. Its case id is ``E2E_L4_CASE_ID`` (see ``app.seeds.e2e_env``).

Sharing signals are never recorded for synthetic accounts in production code (RE §4.4). The seed
lifts ``is_synthetic`` for the few statements that write the demo signals, inside the same
transaction, and sets it back before commit — no other session ever sees the flag cleared.

Idempotent: a fixture account that already has a security case is left untouched.
"""

from __future__ import annotations

import asyncio
import hashlib
import sys
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import get_settings
from app.core.db import make_engine, system_context
from app.core.ids import uuid7
from app.core.models_registry import import_all_models
from app.core.principal import Principal
from app.core.security import hash_token
from app.modules.admin.policy import get_value
from app.modules.identity import clock
from app.modules.identity.models import Consent, User
from app.modules.security import cases as cs
from app.modules.security import engine as eng
from app.modules.security import signals
from app.modules.security.models import (
    AccountRestriction,
    RiskEvaluation,
    SecurityCase,
    UnblockRequest,
)
from app.modules.security.policies import sharing_policy
from app.modules.security.refs import make_ref
from app.modules.security.rules import score_sharing
from app.modules.sessions.models import AuthSession, Device, SessionNetworkObservation, UserDevice
from app.seeds import seeds_allowed
from app.seeds.sync import sync_touched

# Seeds run standalone: register every module's tables so cross-module FKs resolve.
import_all_models()

DOMAIN = "dev.techdrona.local"
RESTRICTED = f"restricted.student@{DOMAIN}"
REVERIFY = f"reverify.student@{DOMAIN}"
SUSPENDED = f"suspended.student@{DOMAIN}"
DECIDER = f"security@{DOMAIN}"  # decides the reverify fixture (reviewer A in E2E)
L4_APPLIER = f"admin@{DOMAIN}"  # applies the L4: neither E2E reviewer A nor B (SoD-06)
VERIFIED_BEFORE_RESTRICTION = timedelta(days=30)


@dataclass(frozen=True)
class Fixture:
    email: str
    kind: str  # "l3" | "lift_pending" | "l4"


FIXTURES = (
    Fixture(RESTRICTED, "l3"),
    Fixture(REVERIFY, "lift_pending"),
    Fixture(SUSPENDED, "l4"),
)


class ProductionRefused(RuntimeError):
    pass


def guard() -> None:
    if not seeds_allowed():
        raise ProductionRefused("security_demo seed refuses to run outside APP_ENV local/dev/test")


async def _user(session: AsyncSession, email: str) -> User:
    user = (await session.execute(select(User).where(User.email == email))).scalar_one_or_none()
    if user is None:
        raise RuntimeError(f"{email} not found - run `python -m app.seeds.dev_users` first")
    return user


def _staff(user_id: uuid.UUID) -> Principal:
    return Principal(user_id=user_id, session_id=uuid7(), tier="staff", is_platform=True, is_minor=False)


def utc_days_ago(days: int) -> datetime:
    return clock.now() - timedelta(days=days)


async def _device(
    session: AsyncSession, user: User, ip: str, asn: int, region: str, os_family: str
) -> tuple[uuid.UUID, uuid.UUID]:
    now = utc_days_ago(12)
    dev = Device(
        id=uuid7(),
        # Deterministic per account + OS: no real browser ever holds this key.
        device_key_hash=hashlib.sha256(f"td-dev-seed:{user.email}:{os_family}".encode()).digest(),
        client_type="web",
        ua_family="Chrome",
        os_family=os_family,
        device_class="desktop",
        label_hint=f"Chrome on {os_family}",
        first_seen_at=now,
        last_seen_at=now,
    )
    session.add(dev)
    await session.flush()
    ud = UserDevice(
        id=uuid7(),
        user_id=user.id,
        device_id=dev.id,
        trust_status="trusted",
        trusted_at=now,
        owner_verified_at=now,
        verification_method="sms_otp",
        last_used_at=now,
    )
    session.add(ud)
    await session.flush()
    cluster = f"AS{asn}:{'.'.join(ip.split('.')[:3])}.0/24"
    s = AuthSession(
        id=uuid7(),
        token_hash=hash_token(uuid7().hex),
        user_id=user.id,
        device_id=dev.id,
        user_device_id=ud.id,
        client_type="web",
        session_tier="student",
        status="expired",
        created_via="password",
        amr=["pwd"],
        auth_time=now,
        created_at=now,
        last_seen_at=now,
        idle_expires_at=now + timedelta(hours=1),
        absolute_expires_at=now + timedelta(hours=24),
        ip_first=ip,
        ip_last=ip,
        net_cluster_first=cluster,
        net_cluster_last=cluster,
        asn=asn,
        network_type="broadband",
        geo_region=region,
        ended_at=now + timedelta(hours=1),
        end_reason="idle_timeout",
    )
    session.add(s)
    await session.flush()
    session.add(
        SessionNetworkObservation(
            id=uuid7(),
            first_seen_at=now,
            last_seen_at=now,
            auth_session_id=s.id,
            user_id=user.id,
            net_cluster=cluster,
            asn=asn,
            network_type="broadband",
            geo_region=region,
        )
    )
    await session.flush()
    return dev.id, s.id


async def _write_signals(session: AsyncSession, user: User, *, reseller: bool) -> None:
    """Demo devices + the engine's own signal writers (SH-01/02 from heartbeat buckets, SH-05,
    and for the high-risk fixture the reseller trio SH-06/09/11)."""
    if not (
        await session.execute(
            select(Consent.id).where(Consent.user_id == user.id, Consent.purpose == "security_monitoring")
        )
    ).first():
        session.add(
            Consent(
                id=uuid7(),
                user_id=user.id,
                purpose="security_monitoring",
                action="granted",
                notice_version="2026-11-01",
                channel="web",
            )
        )
    a = await _device(session, user, "49.36.10.5", 24560, "TG", "Windows")
    b = await _device(session, user, "183.82.1.9", 18209, "MH", "Mac OS X")
    real_now = clock.now
    base = real_now().replace(minute=0, second=0, microsecond=0)
    user.is_synthetic = False  # see module docstring: restored below, same transaction
    await session.flush()
    try:
        for day in (9, 6, 3, 0):
            t = base - timedelta(days=day)
            clock.now = lambda t=t: t + timedelta(minutes=30)  # type: ignore[misc]
            await signals.ingest_engaged_buckets(
                session,
                user.id,
                [
                    signals.EngagedBucket(d, s, t + timedelta(minutes=5 * k))
                    for k in range(4)
                    for d, s in (a, b)
                ],
                evaluate=False,
            )
        clock.now = real_now
        await eng.record_signal(session, rule_key="SH-05", user_id=user.id, source="nightly", user=user)
        if reseller:
            for key, evidence in (
                ("SH-06", {"new_devices_24h": 4}),
                ("SH-09", {"asn": 14061, "asn_kind": "hosting"}),
                ("SH-11", {"device": str(a[0]), "accounts_on_device": 5}),
            ):
                await eng.record_signal(
                    session, rule_key=key, user_id=user.id, source="nightly", evidence=evidence, user=user
                )
    finally:
        clock.now = real_now
        user.is_synthetic = True
        await session.flush()


async def _engine_l3(
    session: AsyncSession, user: User, *, reseller: bool
) -> tuple[SecurityCase, AccountRestriction, RiskEvaluation]:
    """Signals → an explainable ``enforce`` evaluation (the pure scorer over the real signal
    rows) → case + L3 restriction linked to that evaluation, as ``_apply_sharing_action`` does."""
    if user.email_verified_at is None or user.email_verified_at > clock.now() - VERIFIED_BEFORE_RESTRICTION:
        # AUTH-21: the contact must predate the restriction by > 7 days (B3b).
        user.email_verified_at = clock.now() - VERIFIED_BEFORE_RESTRICTION - timedelta(days=15)
    await _write_signals(session, user, reseller=reseller)
    st = await eng.rx.get_state(session, user.id)
    now = clock.now()
    st.l2_issued_at = now - timedelta(days=3)
    st.l2_passed_at = now - timedelta(days=2)
    policy = await sharing_policy(session, user.id)
    definition, rs_version = await eng.ruleset(session, "sharing")
    rows = await eng.user_signals(session, user.id, "sharing", now - timedelta(days=policy.window_days), now)
    ctx, _ = await eng.sharing_context(session, user.id, now)
    result = score_sharing(
        [eng.to_sig(r) for r in rows], now, policy, ctx, {k: float(v) for k, v in definition["caps"].items()}
    )
    ev = RiskEvaluation(
        id=uuid7(),
        evaluated_at=now,
        user_id=user.id,
        organization_id=await eng.primary_org(session, user.id),
        family="sharing",
        mode="enforce",
        ruleset_version=rs_version,
        trigger="manual_review",
        window={
            "from": (now - timedelta(days=policy.window_days)).isoformat(),
            "to": now.isoformat(),
            "half_life_days": policy.half_life_days,
        },
        signals=result.contributions,
        subtotals=result.subtotals,
        repeat_multiplier=Decimal(str(result.repeat_multiplier)),
        score=Decimal(str(result.score)),
        previous_score=Decimal(str(float(st.sharing_score))),
        level_before=ctx.current_level,
        level_after=3,
        gates={**result.gates, "dev_seed": "security_demo"},
        action="restrict_L3",
        explanation_keys=list(result.explanation_keys),
        is_minor_at_time=False,
    )
    case = await eng.open_case(
        session,
        user_id=user.id,
        family="sharing",
        level=3,
        opened_reason="engine_L3",
        priority="high" if reseller else "medium",
    )
    durations = list(await get_value(session, "risk.L3.duration_hours"))
    hours = int(durations[0])
    r, _ = await eng.rx.apply_restriction(
        session,
        user_id=user.id,
        level=3,
        family="sharing",
        source="engine",
        actor=eng.SYSTEM,
        case_id=case.id,
        evaluation_id=ev.id,
        ruleset_version=rs_version,
        ends_at=now + timedelta(hours=hours),
        rule_keys=sorted({c["rule"] for c in result.contributions if c["decayed_points"] > 0}),
    )
    # The append-only evaluation row is inserted once its links are known (engine order).
    ev.restriction_id, ev.case_id = r.id, case.id
    session.add(ev)
    st.sharing_score = Decimal(str(result.score))
    st.sharing_level = 3
    st.last_evaluated_at = now
    await session.flush()
    return case, r, ev


async def _lift_pending(session: AsyncSession, case: SecurityCase, r: AccountRestriction) -> None:
    decider = await _user(session, DECIDER)
    await cs.finalize_decision(
        session,
        _staff(decider.id),
        case,
        {
            "case_id": str(case.id),
            "restriction_id": str(r.id),
            "unblock_request_id": None,
            "outcome": "lift_false_positive",
            "resulting_level": None,
            "rationale": "DEV SEED: both devices verified as the student's own (hostel move).",
            "student_summary": "We reviewed the activity on your account and found it was yours. "
            "Confirm it's you with a one-time code to get your access back.",
            "conditions": {},
            "extension_days": 0,
            "false_positive_rule_keys": [],
            "second_approval_reasons": [],
        },
        decided_by=decider.id,
    )


async def _escalate_l4(session: AsyncSession, user: User, case: SecurityCase) -> None:
    applier = await _user(session, L4_APPLIER)
    r, _ = await eng.rx.apply_restriction(
        session,
        user_id=user.id,
        level=4,
        family="sharing",
        source="reviewer",
        actor=_staff(applier.id),
        case_id=case.id,
        applied_by=applier.id,
        reason="DEV SEED: reseller pattern on top of the L3 sharing case",
    )
    case.level = 4
    case.recommended_level = 4
    case.version += 1
    now = clock.now()
    session.add(
        UnblockRequest(
            id=uuid7(),
            reference=make_ref("APL"),
            case_id=case.id,
            user_id=user.id,
            restriction_id=r.id,
            state="submitted",
            what_happened=["all_devices_mine", "travelling_or_vpn"],
            explanation="I moved from my hostel in Hyderabad to my home in Pune; both laptops are "
            "mine and I used my office VPN.",
            preferred_contact="in_app",
            declaration_at=now,
            submitted_at=now,
            timeline=[{"at": now.isoformat(), "state": "submitted"}],
            version=1,
        )
    )
    await session.flush()


async def seed(session: AsyncSession) -> dict[str, str]:
    """Returns ``{email: case_ref}`` for the fixtures created by this run (empty when present)."""
    guard()
    await system_context(session, "seed.security_demo")
    made: dict[str, str] = {}
    for fx in FIXTURES:
        user = await _user(session, fx.email)
        if (await session.execute(select(SecurityCase.id).where(SecurityCase.user_id == user.id))).first():
            continue
        case, r, _ = await _engine_l3(session, user, reseller=fx.kind == "l4")
        if fx.kind == "lift_pending":
            await _lift_pending(session, case, r)
        elif fx.kind == "l4":
            await _escalate_l4(session, user, case)
        made[fx.email] = case.case_ref
    await session.flush()
    return made


async def main() -> int:
    guard()
    engine = make_engine(get_settings().DATABASE_URL)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session, session.begin():
            made = await seed(session)
            await sync_touched(session, "security", "identity", "sessions")
    finally:
        await engine.dispose()
    if not made:
        print("DEV/DEMO security scenarios: already present")
    for email, ref in made.items():
        print(f"DEV/DEMO security scenario for {email}: {ref}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(asyncio.run(main()))
