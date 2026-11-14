"""Signal ingestion (RE §4, §5.2): login/session events (``sessions.hooks`` sink), engaged-bucket
overlaps (SH-01/SH-02 via the analytics feed interface), verification at a distance (SH-13),
daily derived signals (SH-04..07, SH-10, SH-11) and abuse/integrity detections (AB-*, IN-*).

Network evidence stores only /16 prefixes, network types, state codes and counts (RE §9).
"""

from __future__ import annotations

import functools
import ipaddress
import math
import uuid
from collections import defaultdict
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from itertools import pairwise
from typing import TYPE_CHECKING, Any, Protocol

import structlog
from sqlalchemy import and_, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import as_system
from app.core.ids import uuid7
from app.core.outbox import emit_event
from app.modules.admin.policy import get_value
from app.modules.identity import clock
from app.modules.security import engine
from app.modules.security import repo_fs_engine as fx
from app.modules.security import restrictions as rx
from app.modules.security.models import (
    CaseNote,
    SecurityCounter,
    SecurityNotice,
    SecuritySignal,
)
from app.modules.security.refs import make_ref
from app.modules.security.rules import CLASS_ORDER, NetLeg, classify_pair, ist_day

if TYPE_CHECKING:  # annotations only: rows come from identity.public / sessions.public
    from app.modules.identity.models import User
    from app.modules.sessions.models import AuthSession, LoginAttempt, UserDevice

log = structlog.get_logger("app.security.signals")
FAILURES = ("bad_credentials", "unknown_identifier")
PRIMARY_OK = ("success", "mfa_required", "device_otp_required")
STRONG_METHODS = ("sms_otp", "totp", "passkey")
FIXED_LINE = ("broadband", "education")

# State centroids (lat, lon) for SH-10 (ISO 3166-2:IN codes); unknown states are skipped.
STATE_CENTROIDS: dict[str, tuple[float, float]] = {
    "TG": (17.9, 79.0),
    "AP": (15.9, 79.7),
    "MH": (19.6, 75.5),
    "KA": (15.3, 75.7),
    "TN": (11.1, 78.7),
    "KL": (10.9, 76.3),
    "GA": (15.3, 74.1),
    "DL": (28.6, 77.2),
    "UP": (26.8, 80.9),
    "UT": (30.1, 79.0),
    "HR": (29.1, 76.1),
    "PB": (31.1, 75.3),
    "CH": (30.7, 76.8),
    "HP": (31.1, 77.2),
    "JK": (33.8, 76.6),
    "RJ": (27.0, 74.2),
    "GJ": (22.3, 71.2),
    "MP": (23.5, 77.9),
    "CT": (21.3, 81.9),
    "OR": (20.9, 84.0),
    "JH": (23.6, 85.3),
    "BR": (25.1, 85.3),
    "WB": (22.9, 87.9),
    "AS": (26.2, 92.9),
}


def km_between(a: str | None, b: str | None) -> float | None:
    if not a or not b or a not in STATE_CENTROIDS or b not in STATE_CENTROIDS:
        return None
    (la1, lo1), (la2, lo2) = STATE_CENTROIDS[a], STATE_CENTROIDS[b]
    p1, p2 = math.radians(la1), math.radians(la2)
    dp, dl = p2 - p1, math.radians(lo2 - lo1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * 6371 * math.asin(math.sqrt(h))


def source24(ip: str | None) -> str | None:
    if not ip:
        return None
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return None
    plen = 24 if addr.version == 4 else 48
    return str(ipaddress.ip_network(f"{ip}/{plen}", strict=False))


def mask16(cluster: str | None) -> str | None:
    if not cluster:
        return None
    asn, _, net = cluster.partition(":") if cluster.startswith("AS") else ("AS0", ":", cluster)
    try:
        n = ipaddress.ip_network(net, strict=False)
    except ValueError:
        return cluster
    if n.version == 4:
        return f"{asn}:{ipaddress.ip_network(f'{n.network_address}/16', strict=False)}"
    return f"{asn}:{ipaddress.ip_network(f'{n.network_address}/32', strict=False)}"


async def _user(session: AsyncSession, user_id: uuid.UUID) -> User | None:
    """``identity.public.get_user`` (Postgres: ``session.get(User, id)``)."""
    u: User | None = await fx.get_user(session, user_id)
    return u


async def _scalar(session: AsyncSession, stmt: Any, on_firestore: Callable[[], Awaitable[Any]]) -> Any:
    """``(await session.execute(stmt)).scalar_one()``; Firestore: ``on_firestore()``."""
    if fx.fs():
        return await on_firestore()
    return (await session.execute(stmt)).scalar_one()


async def _attempts(
    session: AsyncSession,
    user_id: uuid.UUID,
    outcome: str,
    since: datetime,
    *,
    country: str | None = None,
    exclude_id: Any = None,
) -> int:
    """Firestore: login attempts of a user with ``outcome`` and ``attempted_at > since``."""
    from app.modules.sessions import public as sp

    rows = await sp.list_login_attempts(session, since=since, user_id=user_id, outcomes=[outcome])
    return sum(
        1
        for a in rows
        if (country is None or a.geo_country == country) and (exclude_id is None or a.id != exclude_id)
    )


def _in_net(ip: Any, net: Any) -> bool:
    """``ip << net`` (inet containment; other address families never match)."""
    if not ip:
        return False
    try:
        addr = ipaddress.ip_address(str(ip).split("/")[0])
    except ValueError:
        return False
    return addr.version == net.version and addr in net


def _source_aggregates(rows: list[Any]) -> tuple[Any, int]:
    """The two ``login_attempts`` aggregates of AB-04 / AB-05 over the attempts of one source:
    (failures not pre-auth-blocked, distinct identifiers among them) and the number of
    identifiers with <= 2 attempts (``GROUP BY identifier_hash``; NULL is a group)."""
    from collections import Counter
    from types import SimpleNamespace

    fails = [a for a in rows if a.outcome in FAILURES and a.pre_auth_blocked is False]
    per_ident = Counter(a.identifier_hash for a in rows)
    n = SimpleNamespace(
        n=len(fails), accts=len({a.identifier_hash for a in fails if a.identifier_hash is not None})
    )
    return n, sum(1 for c in per_ident.values() if c <= 2)


async def _source_counts(session: AsyncSession, ip: str | None, since: datetime) -> tuple[Any, int]:
    """AB-04 / AB-05 aggregates for the /24 (/48) source of ``ip`` over
    ``sessions.public.list_login_attempts_in_prefix`` (Postgres: ``ip << network``; Firestore:
    the indexed ``ip_prefix``). The containment is re-checked on each row."""
    from app.modules.sessions import public as sp

    src = source24(ip)
    if src is None or ip is None:
        return _source_aggregates([])
    net = ipaddress.ip_network(src, strict=False)
    rows = [a for a in await sp.list_login_attempts_in_prefix(session, ip, since=since) if _in_net(a.ip, net)]
    return _source_aggregates(rows)


# --------------------------------------------------------------------------- counters


async def bump(session: AsyncSession, key: str, now: datetime) -> None:
    if fx.fs():
        await fx.repo().bump(key, now)
        return
    bucket = now.replace(second=0, microsecond=0)
    await session.execute(
        pg_insert(SecurityCounter)
        .values(counter_key=key, bucket_start=bucket, count=1)
        .on_conflict_do_update(
            index_elements=["counter_key", "bucket_start"], set_={"count": SecurityCounter.count + 1}
        )
    )


async def count_since(session: AsyncSession, key: str, since: datetime) -> int:
    if fx.fs():
        return await fx.repo().count_since(key, since)
    return int(
        (
            await session.execute(
                select(func.coalesce(func.sum(SecurityCounter.count), 0)).where(
                    SecurityCounter.counter_key == key, SecurityCounter.bucket_start >= since
                )
            )
        ).scalar_one()
    )


async def recent_signal(
    session: AsyncSession,
    rule: str,
    since: datetime,
    *,
    user_id: uuid.UUID | None = None,
    source: str | None = None,
) -> bool:
    if fx.fs():
        r = fx.repo()
        rows = (
            [s for s in await r.user_signals(user_id, rule_key=rule) if s.occurred_at > since]
            if user_id is not None
            else await r.rule_signals_since(rule, since)
        )
        return any(source is None or (s.evidence or {}).get("source") == source for s in rows)
    conds: list[Any] = [SecuritySignal.rule_key == rule, SecuritySignal.occurred_at > since]
    if user_id is not None:
        conds.append(SecuritySignal.user_id == user_id)
    if source is not None:
        conds.append(SecuritySignal.evidence["source"].astext == source)
    return bool(
        (
            await session.execute(select(func.count()).select_from(SecuritySignal).where(and_(*conds)))
        ).scalar_one()
    )


async def abuse_params(session: AsyncSession) -> dict[str, Any]:
    d, _ = await engine.ruleset(session, "abuse")
    return dict(d["params"])


# --------------------------------------------------------------------------- login events


async def _owner_verified_refresh(
    session: AsyncSession, user_id: uuid.UUID, device_id: uuid.UUID | None, method: str
) -> None:
    """AMB-22: any SMS-OTP / passkey / TOTP challenge on a device refreshes owner verification."""
    if device_id is None:
        return
    from app.modules.sessions import public as sp

    uds = await sp.list_user_devices(session, user_id=user_id, device_id=device_id, live_only=True)
    if len(uds) > 1:
        from sqlalchemy.exc import MultipleResultsFound

        raise MultipleResultsFound("Multiple rows were found when one or none was required")
    if uds:
        ud = uds[0]
        ud.owner_verified_at = clock.now()
        if ud.verification_method is None:
            ud.verification_method = method
        await sp.add_user_device(session, ud)


async def check_l2_pass(session: AsyncSession, user_id: uuid.UUID) -> bool:
    """L2 clears when every device in the L2 evidence re-verified (SMS OTP / passkey / TOTP)
    after the L2 was issued (RE §6.1); the score hysteresis then applies."""
    r = await rx.active_for(session, user_id, "sharing")
    if r is None or r.level != 2:
        return False
    from app.modules.sessions import public as sp

    rows = [(d.device_id, d.owner_verified_at) for d in await sp.list_user_devices(session, user_id=user_id)]
    verified = {d for d, ts in rows if ts is not None and ts >= r.starts_at}
    needed = set(r.reverify_device_ids)
    if needed and not needed <= verified:
        return False
    st = await rx.get_state(session, user_id)
    st.l2_passed_at = clock.now()
    await fx.flush(session, st)
    await engine.evaluate_sharing(session, user_id, trigger="verification")
    return True


async def _ab_source_checks(session: AsyncSession, la: LoginAttempt, now: datetime) -> None:
    src = source24(la.ip)
    if src is None:
        return
    p = await abuse_params(session)
    row, spray = await _source_counts(session, la.ip, now - timedelta(hours=1))
    if (
        row.n >= int(p["ab04_failures"])
        and row.accts >= int(p["ab04_accounts"])
        and not await recent_signal(session, "AB-04", now - timedelta(hours=24), source=src)
    ):
        await engine.record_signal(
            session,
            rule_key="AB-04",
            user_id=None,
            source="login",
            evidence={"source": src, "failures_1h": row.n, "accounts_1h": row.accts},
        )
        await emit_event(
            session,
            "security.alert_raised",
            {"kind": "AB-04", "source": src, "route": "security_lead"},
            aggregate_type="security_source",
            aggregate_id=uuid7(),
        )
    if spray >= int(p["ab05_accounts"]) and not await recent_signal(
        session, "AB-05", now - timedelta(hours=1), source=src
    ):
        await engine.record_signal(
            session,
            rule_key="AB-05",
            user_id=None,
            source="login",
            evidence={"source": src, "accounts_1h": int(spray)},
        )


async def _flagged_source(session: AsyncSession, ip: str | None, now: datetime) -> str | None:
    src = source24(ip)
    if src and await recent_signal(session, "AB-04", now - timedelta(hours=24), source=src):
        return src
    return None


async def _device_checks(session: AsyncSession, user: User, la: LoginAttempt, now: datetime) -> None:
    if la.device_id is None:
        return
    # AB-10: a device of an account under active L3/L4 used by another account within 7 days.
    others = await _ab10_restricted(session, user, la.device_id, now)
    for r in others:
        if await recent_signal(session, "AB-10", now - timedelta(days=1), user_id=user.id):
            break
        await engine.record_signal(
            session,
            rule_key="AB-10",
            user_id=user.id,
            source="login",
            evidence={"device": str(la.device_id), "restricted_account": str(r.user_id)},
            device_id=la.device_id,
            user=user,
        )
        if r.case_id:
            await fx.add(
                session,
                fx.new(
                    CaseNote,
                    id=uuid7(),
                    case_id=r.case_id,
                    author_id=None,
                    visibility="internal",
                    body=f"AB-10: a device of this account signed in to another account "
                    f"({str(user.id)[:8]}) on {now:%Y-%m-%d}.",
                ),
            )


async def _ab10_restricted(
    session: AsyncSession, user: User, device_id: uuid.UUID, now: datetime
) -> list[Any]:
    """Active sharing L3+ restrictions of other accounts that used ``device_id`` in the last 7
    days (the join ``account_restrictions x user_devices``: one row per pair), devices through
    ``sessions.public``."""
    from app.modules.sessions import public as sp

    out: list[Any] = []
    since = now - timedelta(days=7)
    for ud in await sp.list_user_devices(session, device_id=device_id, last_used_after=since):
        if ud.user_id == user.id:
            continue
        out += [
            r
            for r in await rx.active_restrictions(session, ud.user_id)
            if r.level >= 3 and r.family == "sharing"
        ]
    return out


async def on_login_attempt(session: AsyncSession, la: LoginAttempt) -> None:
    now = la.attempted_at or clock.now()
    if la.outcome in FAILURES and not la.pre_auth_blocked:
        await _ab_source_checks(session, la, now)
    if la.user_id is None:
        return
    user = await _user(session, la.user_id)
    if user is None:
        return
    tdef, _ = await engine.ruleset(session, "takeover")
    tp = tdef["params"]
    takeover_changed = False
    if la.outcome == "bad_credentials" and not la.pre_auth_blocked:
        since01 = now - timedelta(minutes=int(tp["to01_minutes"]))
        n = await _attempts(session, user.id, "bad_credentials", since01)
        if n >= int(tp["to01_failures"]) and not await recent_signal(
            session, "TO-01", now - timedelta(minutes=int(tp["to01_minutes"])), user_id=user.id
        ):
            await engine.record_signal(
                session,
                rule_key="TO-01",
                user_id=user.id,
                source="login",
                evidence={"failures": int(n)},
                user=user,
            )
            takeover_changed = True
    elif la.outcome == "mfa_failed":
        since03 = now - timedelta(minutes=int(tp["to03_minutes"]))
        n = await _attempts(session, user.id, "mfa_failed", since03)
        if n >= int(tp["to03_count"]):
            await engine.record_signal(
                session,
                rule_key="TO-03",
                user_id=user.id,
                source="login",
                evidence={"mfa_failures_1h": int(n)},
                auth_session_id=la.auth_session_id,
                user=user,
            )
            takeover_changed = True
    elif la.outcome == "success":
        p = await abuse_params(session)
        n1 = await _attempts(session, user.id, "success", now - timedelta(hours=1))
        n24 = await _attempts(session, user.id, "success", now - timedelta(hours=24))
        if (n1 >= int(p["ab01_per_hour"]) or n24 >= int(p["ab01_per_day"])) and not await recent_signal(
            session, "AB-01", now - timedelta(hours=1), user_id=user.id
        ):
            await engine.record_signal(
                session,
                rule_key="AB-01",
                user_id=user.id,
                source="login",
                evidence={"logins_1h": int(n1), "logins_24h": int(n24)},
                user=user,
            )
            if not user.is_minor:
                await engine.record_signal(
                    session,
                    rule_key="TO-11",
                    user_id=user.id,
                    source="login",
                    evidence={"from": "AB-01"},
                    user=user,
                )
                takeover_changed = True
        if la.network_type == "tor":
            await engine.record_signal(
                session,
                rule_key="TO-07",
                user_id=user.id,
                source="login",
                evidence={"network_type": "tor"},
                user=user,
            )
            takeover_changed = True
        if la.network_type in ("hosting", "vpn_proxy", "tor") and not await recent_signal(
            session, "SH-09", now - timedelta(days=1), user_id=user.id
        ):
            await engine.record_signal(
                session,
                rule_key="SH-09",
                user_id=user.id,
                source="login",
                evidence={
                    "network_type": la.network_type,
                    "asn": la.asn,
                },
                user=user,
            )
        if la.geo_country and la.geo_country != "IN":
            seen = await _attempts(
                session,
                user.id,
                "success",
                now - timedelta(days=180),
                country=la.geo_country,
                exclude_id=la.id,
            )
            if not seen:
                await engine.record_signal(
                    session,
                    rule_key="TO-09",
                    user_id=user.id,
                    source="login",
                    evidence={"country": la.geo_country},
                    user=user,
                )
                takeover_changed = True
        await _device_checks(session, user, la, now)
        if la.mfa_method in ("totp", "sms_otp", "passkey"):
            await _owner_verified_refresh(session, user.id, la.device_id, la.mfa_method)
            await check_l2_pass(session, user.id)
    if la.outcome in PRIMARY_OK:  # correct password (MFA / device OTP may still be pending)
        src = await _flagged_source(session, la.ip, now)
        hour_ago = now - timedelta(hours=1)
        if src is not None and not await recent_signal(session, "TO-05", hour_ago, user_id=user.id):
            await engine.record_signal(
                session,
                rule_key="TO-05",
                user_id=user.id,
                source="login",
                evidence={"source": src},
                auth_session_id=la.auth_session_id,
                user=user,
            )
            takeover_changed = True
    if takeover_changed:
        await engine.evaluate_takeover(session, user.id, trigger="login", auth_session_id=la.auth_session_id)


# --------------------------------------------------------------------------- session / device events


async def on_replay_blocked(
    session: AsyncSession, s: AuthSession, rule: str, observed: dict[str, Any] | None = None
) -> None:
    """TO-04 / TO-08: that session is already revoked by the resolver; record the signal, notify
    the owner with a "This wasn't me" reference and run the takeover evaluation (RE §6.2).
    Evidence carries the session's expected UA family / OS and, when the resolver passes them,
    the observed ones (E2E-09), so a drift block can be explained."""
    user = await _user(session, s.user_id)
    if user is None:
        return
    evidence: dict[str, Any] = {
        "session": str(s.id)[:8],
        "device": str(s.device_id) if s.device_id else None,
        "expected_ua_family": s.ua_family,
        "expected_os_family": s.os_family,
    }
    if observed:
        evidence["observed_ua_family"] = observed.get("ua_family")
        evidence["observed_os_family"] = observed.get("os_family")
    await engine.record_signal(
        session,
        rule_key=rule,
        user_id=user.id,
        source="system",
        evidence=evidence,
        auth_session_id=s.id,
        device_id=s.device_id,
        user=user,
    )
    ref = make_ref("ACC")
    await fx.add(
        session,
        fx.new(
            SecurityNotice,
            id=uuid7(),
            created_at=clock.now(),
            event_ref=ref,
            user_id=user.id,
            kind="replay",
            rule_key=rule,
            auth_session_id=s.id,
        ),
    )
    await fx.flush(session)
    await engine.notify_user(
        session,
        user.id,
        "security.session_replay",
        subject="We signed out a session that looked unusual",
        text_body="A sign-in from one of your devices was used from a different browser, "
        "so we signed it out. "
        "Your other devices are still signed in. If this wasn't you, secure your account.",
        data={"event_ref": ref, "disown_url": f"/app/settings/security/not-me/{ref}"},
    )
    await engine.evaluate_takeover(session, user.id, trigger="login", auth_session_id=s.id)


async def _network_at(session: AsyncSession, auth_session_id: uuid.UUID, at: datetime) -> dict[str, Any]:
    """The session's newest network observation at ``at`` (else its first network), through
    ``sessions.public``."""
    from app.modules.sessions import public as sp

    seen = await sp.list_observations(session, auth_session_id=auth_session_id, until=at)
    return _network_of(seen[-1] if seen else None, await sp.get_session(session, auth_session_id))


def _network_of(obs: Any, s: Any) -> dict[str, Any]:
    if obs is not None:
        return {
            "net_cluster": obs.net_cluster,
            "asn": obs.asn,
            "network_type": obs.network_type,
            "geo_region": obs.geo_region,
        }
    if s is not None:
        return {
            "net_cluster": s.net_cluster_first,
            "asn": s.asn,
            "network_type": s.network_type,
            "geo_region": s.geo_region,
        }
    return {"net_cluster": None, "asn": None, "network_type": None, "geo_region": None}


async def on_device_trusted(session: AsyncSession, ud: UserDevice, method: str | None) -> None:
    """SH-13 (verification at a distance) + L2 re-verification bookkeeping."""
    user = await _user(session, ud.user_id)
    if user is None:
        return
    now = clock.now()
    if not user.is_minor:
        await check_sh13(session, user, ud.device_id, now)
    if method in STRONG_METHODS:
        await check_l2_pass(session, user.id)


async def check_sh13(
    session: AsyncSession, user: User, device_id: uuid.UUID, now: datetime
) -> SecuritySignal | None:
    sdef, _ = await engine.ruleset(session, "sharing")
    win = timedelta(minutes=int(sdef["params"].get("sh13_window_minutes", 15)))
    return await _check_sh13(session, user, device_id, now, win)


async def _check_sh13(
    session: AsyncSession, user: User, device_id: uuid.UUID, now: datetime, win: timedelta
) -> Any:
    """SH-13: sessions through ``sessions.public``; the per-device signal check on the security
    store."""
    from app.modules.sessions import public as sp

    mine_all = await sp.list_sessions(session, user_id=user.id, device_id=device_id)
    if not mine_all:
        return None
    mine = mine_all[-1]  # newest created_at
    net_b = await _network_at(session, mine.id, now)
    if net_b["network_type"] not in FIXED_LINE:
        return None
    others = [
        o
        for o in await sp.list_sessions(
            session,
            user_id=user.id,
            exclude_device_id=device_id,
            last_seen_after=now - win,
            last_seen_until=now + win,
        )
        if o.device_id is not None  # SQL: NULL <> :device is not true
    ]
    for o in others:
        net_a = await _network_at(session, o.id, o.last_seen_at)
        if net_a["network_type"] in FIXED_LINE and net_a["net_cluster"] != net_b["net_cluster"]:
            if await recent_signal(
                session, "SH-13", now - timedelta(days=30), user_id=user.id
            ) and await _sh13_on_device(session, user.id, device_id):
                return None  # one occurrence per verified device
            return await engine.record_signal(
                session,
                rule_key="SH-13",
                user_id=user.id,
                source="system",
                device_id=device_id,
                evidence={
                    "device": str(device_id),
                    "other_device": str(o.device_id) if o.device_id else None,
                    "net_a": mask16(net_a["net_cluster"]),
                    "net_b": mask16(net_b["net_cluster"]),
                    "region_a": net_a["geo_region"],
                    "region_b": net_b["geo_region"],
                },
                user=user,
            )
    return None


async def _sh13_on_device(session: AsyncSession, user_id: uuid.UUID, device_id: uuid.UUID) -> int:
    if fx.fs():
        return sum(
            1 for s in await fx.repo().user_signals(user_id, rule_key="SH-13") if s.device_id == device_id
        )
    return int(
        (
            await session.execute(
                select(func.count())
                .select_from(SecuritySignal)
                .where(
                    SecuritySignal.rule_key == "SH-13",
                    SecuritySignal.device_id == device_id,
                    SecuritySignal.user_id == user_id,
                )
            )
        ).scalar_one()
    )


async def on_restricted_denial(session: AsyncSession, user_id: uuid.UUID, path: str) -> None:
    """AB-08: ≥ 30 ``403 account_restricted`` in 10 min → info signal only (never escalates)."""
    now = clock.now()
    key = f"ab08:{user_id}"
    await bump(session, key, now)
    p = await abuse_params(session)
    n = await count_since(session, key, now - timedelta(minutes=10))
    if n >= int(p["ab08_denials"]) and not await recent_signal(
        session, "AB-08", now - timedelta(minutes=10), user_id=user_id
    ):
        await engine.record_signal(
            session,
            rule_key="AB-08",
            user_id=user_id,
            source="system",
            evidence={"denials_10min": n, "last_route": path},
        )


async def on_unknown_token(session: AsyncSession, ip: str | None) -> bool:
    """AB-07: ≥ 20 unknown tokens per /24 in 10 min → that /24 throttled 15 min."""
    src = source24(ip)
    if src is None:
        return False
    now = clock.now()
    if await recent_signal(session, "AB-07", now - timedelta(minutes=15), source=src):
        return True
    key = f"ab07:{src}"
    await bump(session, key, now)
    p = await abuse_params(session)
    n = await count_since(session, key, now - timedelta(minutes=10))
    if n >= int(p["ab07_unknown_tokens"]):
        await engine.record_signal(
            session,
            rule_key="AB-07",
            user_id=None,
            source="system",
            evidence={"source": src, "unknown_tokens_10min": n},
        )
        if n >= 100:
            await emit_event(
                session,
                "security.alert_raised",
                {"kind": "AB-07", "source": src, "route": "security_lead"},
                aggregate_type="security_source",
                aggregate_id=uuid7(),
            )
        return True
    return False


class SecurityEventSink:
    """``sessions.hooks.SecurityEvents`` implementation. Failures are logged, never raised into
    the authentication path (a broken detector must not lock users out)."""

    async def _guard(
        self, session: AsyncSession, name: str, fn: Callable[[], Awaitable[Any]], default: Any = None
    ) -> Any:
        try:
            if not session:
                # Firebase stack (``NO_POSTGRES``): no savepoint; the Firestore writes of the
                # detector are immediate. The system-job scope still applies (notifications).
                async with fx.detector_scope(), as_system(session, f"security.hook.{name}"):
                    return await fn()
            # Detectors write engine state (signals, security_user_state, notices) that the
            # subject may only read (DB-05): run as a named system job, restoring the caller's
            # RLS context afterwards.
            async with (
                session.begin_nested(),
                as_system(session, f"security.hook.{name}"),
                fx.detector_scope(),
            ):
                return await fn()
        except Exception as e:  # pragma: no cover - defensive
            log.error("security_hook_failed", hook=name, error=type(e).__name__, detail=str(e)[:200])
            return default

    async def login_attempt(self, session: AsyncSession, attempt: Any) -> None:
        await self._guard(session, "login_attempt", lambda: on_login_attempt(session, attempt))

    async def replay_blocked(
        self, session: AsyncSession, auth_session: Any, rule: str, observed: dict[str, Any] | None = None
    ) -> None:
        await self._guard(
            session, "replay_blocked", lambda: on_replay_blocked(session, auth_session, rule, observed)
        )

    async def device_trusted(self, session: AsyncSession, user_device: Any, method: str | None) -> None:
        await self._guard(session, "device_trusted", lambda: on_device_trusted(session, user_device, method))

    async def restricted_denial(self, session: AsyncSession, user_id: uuid.UUID, path: str) -> None:
        await self._guard(session, "restricted_denial", lambda: on_restricted_denial(session, user_id, path))

    async def unknown_token(self, session: AsyncSession, ip: str | None) -> bool:
        return bool(await self._guard(session, "unknown_token", lambda: on_unknown_token(session, ip), False))


# --------------------------------------------------------------------------- engaged buckets (SH-01/SH-02)


@dataclass(frozen=True)
class EngagedBucket:
    device_id: uuid.UUID
    auth_session_id: uuid.UUID
    bucket_start: datetime  # 5-minute bucket
    activity_kind: str = "engaged"


class EngagedBucketFeed(Protocol):
    """``analytics.feeds.get_engaged_buckets`` contract (RE §1.2): adults with an active
    ``security_monitoring`` consent only."""

    async def get_engaged_buckets(
        self, session: AsyncSession, user_id: uuid.UUID, start: datetime, end: datetime
    ) -> Sequence[EngagedBucket]: ...


_feed: EngagedBucketFeed | None = None


def register_engaged_bucket_feed(feed: EngagedBucketFeed | None) -> None:
    global _feed
    _feed = feed


def engaged_bucket_feed() -> EngagedBucketFeed | None:
    return _feed


async def _leg(session: AsyncSession, user_id: uuid.UUID, b: EngagedBucket, cache: dict[Any, Any]) -> NetLeg:
    net = await _network_at(session, b.auth_session_id, b.bucket_start + timedelta(minutes=5))
    dev = cache.get(("dev", b.device_id))
    if dev is None:
        from app.modules.sessions import public as sp

        dev = await sp.get_device(session, b.device_id)
        cache[("dev", b.device_id)] = dev
    cluster = net["net_cluster"]
    return NetLeg(
        device_id=str(b.device_id),
        net_cluster=cluster,
        asn=net["asn"],
        network_type=net["network_type"],
        geo_region=net["geo_region"],
        os_family=dev.os_family if dev else None,
        device_class=dev.device_class if dev else None,
    )


async def ingest_engaged_buckets(
    session: AsyncSession, user_id: uuid.UUID, buckets: Sequence[EngagedBucket], *, evaluate: bool = True
) -> list[SecuritySignal]:
    """SH-01 per device pair per IST day with ≥ 3 overlapping engaged buckets (most separated
    class of the day) and SH-02 when the pair's states differ."""
    user = await _user(session, user_id)
    if user is None or user.is_minor or user.is_synthetic:
        return []
    sdef, _ = await engine.ruleset(session, "sharing")
    min_buckets = int(sdef["params"].get("overlap_min_buckets", 3))
    cgnat = frozenset(int(a) for a in await get_value(session, "risk.cgnat_asns"))
    by_bucket: dict[datetime, dict[uuid.UUID, EngagedBucket]] = defaultdict(dict)
    for b in buckets:
        by_bucket[b.bucket_start][b.device_id] = b
    cache: dict[Any, Any] = {}
    pair_days: dict[tuple[Any, ...], list[tuple[datetime, str, NetLeg, NetLeg]]] = defaultdict(list)
    for t, devs in sorted(by_bucket.items()):
        ids = sorted(devs, key=str)
        for i in range(len(ids)):
            for j in range(i + 1, len(ids)):
                a = await _leg(session, user_id, devs[ids[i]], cache)
                b2 = await _leg(session, user_id, devs[ids[j]], cache)
                cls, fp = classify_pair(a, b2, cgnat)
                pair_days[(ist_day(t), ids[i], ids[j])].append((t, cls + ("fp" if fp else ""), a, b2))
    out: list[SecuritySignal] = []
    for (day, da, db), rows in sorted(
        pair_days.items(), key=lambda kv: (kv[0][0], str(kv[0][1]), str(kv[0][2]))
    ):
        if len(rows) < min_buckets:
            continue
        exists = await _scalar(
            session,
            select(func.count())
            .select_from(SecuritySignal)
            .where(
                SecuritySignal.user_id == user_id,
                SecuritySignal.rule_key == "SH-01",
                SecuritySignal.evidence["pair"].astext == f"{da}|{db}",
                SecuritySignal.evidence["day"].astext == day.isoformat(),
            ),
            functools.partial(_sh01_exists_fs, user_id, f"{da}|{db}", day.isoformat()),
        )
        if exists:
            continue
        best = max(rows, key=lambda r: CLASS_ORDER[r[1][:2]])
        cls = best[1][:2]
        fp = best[1].endswith("fp")
        _, _, la, lb = best
        last_t = max(r[0] for r in rows)
        evidence = {
            "pair": f"{da}|{db}",
            "day": day.isoformat(),
            "device_a": str(da),
            "device_b": str(db),
            "overlap_buckets": len(rows),
            "buckets": [r[0].isoformat() for r in rows if r[1][:2] == cls],
            "net_a": mask16(la.net_cluster),
            "net_b": mask16(lb.net_cluster),
            "net_type_a": la.network_type,
            "net_type_b": lb.network_type,
            "region_a": la.geo_region,
            "region_b": lb.geo_region,
        }
        sig = await engine.record_signal(
            session,
            rule_key="SH-01",
            user_id=user_id,
            source="heartbeat_batch",
            occurred_at=last_t + timedelta(minutes=5),
            evidence=evidence,
            multipliers={"separation_class": cls, "fp_match": fp},
            user=user,
        )
        if sig is not None:
            out.append(sig)
        if (
            la.geo_region
            and lb.geo_region
            and la.geo_region != lb.geo_region
            and la.net_cluster != lb.net_cluster
        ):
            s2 = await engine.record_signal(
                session,
                rule_key="SH-02",
                user_id=user_id,
                source="heartbeat_batch",
                occurred_at=last_t + timedelta(minutes=5),
                evidence={
                    "pair": f"{da}|{db}",
                    "day": day.isoformat(),
                    "region_a": la.geo_region,
                    "region_b": lb.geo_region,
                },
                user=user,
            )
            if s2 is not None:
                out.append(s2)
    if out and evaluate:
        await engine.evaluate_sharing(session, user_id, trigger="heartbeat_batch")
    return out


async def _sh01_exists_fs(user_id: uuid.UUID, pair: str, day: str) -> int:
    return sum(
        1
        for s in await fx.repo().user_signals(user_id, rule_key="SH-01")
        if _astext((s.evidence or {}).get("pair")) == pair and _astext((s.evidence or {}).get("day")) == day
    )


def _astext(v: Any) -> str | None:
    """JSONB ``->>``: strings as is, other scalars as their JSON text, null as NULL."""
    if v is None:
        return None
    if isinstance(v, str):
        return v
    import json

    return json.dumps(v)


async def run_heartbeat_batch(
    session: AsyncSession, user_ids: Sequence[uuid.UUID], start: datetime, end: datetime
) -> int:
    """5-minute micro-batch: pull engaged buckets from the registered feed and ingest."""
    feed = _feed
    if feed is None:
        return 0
    n = 0
    for uid in user_ids:
        buckets = await feed.get_engaged_buckets(session, uid, start, end)
        n += len(await ingest_engaged_buckets(session, uid, buckets))
    return n


# --------------------------------------------------------------------------- daily derived signals


async def derive_daily_signals(
    session: AsyncSession, user_id: uuid.UUID, now: datetime | None = None
) -> list[str]:
    """Nightly per-adult derivations: SH-04, SH-05, SH-06, SH-07, SH-10, SH-11 (RE §4.2)."""
    now = now or clock.now()
    user = await _user(session, user_id)
    if user is None or user.is_minor or user.is_synthetic:
        return []
    sdef, _ = await engine.ruleset(session, "sharing")
    p = sdef["params"]
    made: list[str] = []
    dd = _Daily(session, user_id, now)

    async def once(rule: str, evidence: dict[str, Any], points: float | None = None) -> None:
        if not await recent_signal(session, rule, now - timedelta(hours=23), user_id=user_id):
            if await engine.record_signal(
                session,
                rule_key=rule,
                user_id=user_id,
                source="nightly",
                evidence=evidence,
                base_points=points,
                occurred_at=now,
                user=user,
            ):
                made.append(rule)

    n30 = await dd.n30()
    if n30 >= int(p["sh05_high"]):
        await once("SH-05", {"distinct_devices_30d": int(n30)}, float(p.get("sh05_high_points", 16)))
    elif n30 >= int(p["sh05_low"]):
        await once("SH-05", {"distinct_devices_30d": int(n30)})
    new24 = await dd.new24()
    if new24 >= int(p["sh06_new_devices"]):
        await once("SH-06", {"new_devices_24h": int(new24)})
    evicted = await dd.evicted()
    if evicted >= int(p["sh04_evictions"]):
        await once("SH-04", {"evictions_24h": int(evicted)})
    abandoned = await dd.abandoned()
    if abandoned >= int(p["sh07_abandoned"]):
        await once("SH-07", {"abandoned_7d": int(abandoned)})
    # SH-11: a device used by ≥ 4 accounts in 7 days (sessions.public runs the GROUP BY on Postgres).
    from app.modules.sessions import public as sp

    shared = await sp.shared_devices_of_user(
        session, user_id, min_accounts=int(p["sh11_accounts"]), since=now - timedelta(days=7)
    )
    if shared:
        await once("SH-11", {"devices": [str(d) for d in shared][:5]})
    # SH-10: consecutive sessions in far-apart states within 2 h (excluding mobile/CGNAT legs).
    cgnat = frozenset(int(a) for a in await get_value(session, "risk.cgnat_asns"))
    recent = await dd.recent()
    for a, b in pairwise(recent):
        if b.created_at - a.created_at > timedelta(hours=int(p["sh10_max_hours"])):
            continue
        if "mobile" in (a.network_type, b.network_type) or a.asn in cgnat or b.asn in cgnat:
            continue
        km = km_between(a.geo_region, b.geo_region)
        if km is not None and km > float(p["sh10_min_km"]):
            await once("SH-10", {"region_a": a.geo_region, "region_b": b.geo_region, "km": round(km)})
            break
    return made


class _Daily:
    """Reads of ``derive_daily_signals`` through ``sessions.public`` / ``identity.public``."""

    def __init__(self, session: AsyncSession, user_id: uuid.UUID, now: datetime) -> None:
        self.session, self.user_id, self.now = session, user_id, now

    async def n30(self) -> int:
        from app.modules.sessions import public as sp

        rows = await sp.list_sessions(
            self.session, user_id=self.user_id, created_after=self.now - timedelta(days=30)
        )
        return len({s.device_id for s in rows if s.device_id is not None})

    async def new24(self) -> int:
        from app.modules.sessions import public as sp

        rows = await sp.list_user_devices(
            self.session, user_id=self.user_id, created_after=self.now - timedelta(hours=24)
        )
        return len(rows)

    async def evicted(self) -> int:
        from app.modules.sessions import public as sp

        rows = await sp.list_sessions(
            self.session,
            user_id=self.user_id,
            end_reason="session_cap_evicted",
            ended_after=self.now - timedelta(hours=24),
        )
        return len(rows)

    async def abandoned(self) -> int:
        from app.modules.identity import public as idp

        rows = await idp.verification_tokens_of(
            self.session,
            self.user_id,
            purpose="new_device_otp",
            created_after=self.now - timedelta(days=7),
        )
        return sum(1 for t in rows if t.consumed_at is None and t.expires_at < self.now)

    async def recent(self) -> list[Any]:
        from app.modules.sessions import public as sp

        return list(
            await sp.list_sessions(
                self.session, user_id=self.user_id, created_after=self.now - timedelta(days=1)
            )
        )


# --------------------------------------------------------------------------- external detections


async def report_event(
    session: AsyncSession,
    kind: str,
    *,
    user_id: uuid.UUID | None = None,
    evidence: dict[str, Any] | None = None,
    source: str = "system",
    device_id: uuid.UUID | None = None,
    auth_session_id: uuid.UUID | None = None,
) -> SecuritySignal | None:
    """Entry point for other modules (media SH-03/cap.stream, assessments SH-08/cap.attempt_bind,
    webhooks AB-12, analytics IN-01/IN-02, coding IN-03, repositories AB-09). Threshold rules
    are counted here; the signal is written when the threshold is reached."""
    now = clock.now()
    ev = dict(evidence or {})
    p = await abuse_params(session)
    idef, _ = await engine.ruleset(session, "integrity")
    ip = idef["params"]
    thresholds: dict[str, tuple[str, int, timedelta]] = {
        "AB-09.not_found": (f"ab09nf:{user_id}", int(p["ab09_404_per_min"]), timedelta(minutes=1)),
        "AB-09.cross_tenant": (f"ab09ct:{user_id}", int(p["ab09_cross_tenant_per_hour"]), timedelta(hours=1)),
        "IN-02": (f"in02:{auth_session_id}", int(ip["in02_rejections"]), timedelta(hours=1)),
        "IN-03": (f"in03:{user_id}:{ev.get('problem_id')}", int(ip["in03_submits"]), timedelta(hours=1)),
    }
    if kind in thresholds:
        key, limit, window = thresholds[kind]
        await bump(session, key, now)
        n = await count_since(session, key, now - window)
        rule = kind.split(".")[0]
        if n < limit or await recent_signal(session, rule, now - window, user_id=user_id):
            return None
        ev["count"] = n
        sig = await engine.record_signal(
            session,
            rule_key=rule,
            user_id=user_id,
            source=source,
            evidence=ev,
            auth_session_id=auth_session_id,
            device_id=device_id,
        )
        if rule == "AB-09":
            await emit_event(
                session,
                "security.alert_raised",
                {"kind": "AB-09", "user_id": str(user_id), "route": "security_lead"},
                aggregate_type="user",
                aggregate_id=user_id or uuid7(),
            )
        return sig
    sig = await engine.record_signal(
        session,
        rule_key=kind,
        user_id=user_id,
        source=source,
        evidence=ev,
        auth_session_id=auth_session_id,
        device_id=device_id,
    )
    if sig is not None and sig.family == "sharing" and user_id is not None:
        await engine.evaluate_sharing(session, user_id, trigger="playback" if kind == "SH-03" else "attempt")
    return sig
