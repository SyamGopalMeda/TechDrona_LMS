"""Factories and helpers for the security / admin integration tests (everything is rolled back)."""

from __future__ import annotations

import os
import random
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import system_context
from app.core.ids import uuid7
from app.core.security import hash_token
from app.modules.admin import policy as pol
from app.modules.identity import clock
from app.modules.identity.models import Consent, User
from app.modules.security.models import RiskRule, RiskRuleVersion, SecuritySignal
from app.modules.security.signals import EngagedBucket
from app.modules.sessions.models import AuthSession, Device, SessionNetworkObservation, UserDevice
from tests.identity.factory import NOTICE, Browser, UserHandle, grant, make_user, staff_login, step_up

# 06:00 UTC = 11:30 IST: consecutive "days" are distinct IST calendar days.
BASE = datetime.now(UTC).replace(hour=6, minute=0, second=0, microsecond=0)


@contextmanager
def at(monkeypatch: Any, when: datetime) -> Iterator[None]:
    """Run with the module clock frozen at ``when`` (sessions/identity/security all use it)."""
    monkeypatch.setattr(clock, "now", lambda: when)
    try:
        yield
    finally:
        monkeypatch.undo()


def freeze(monkeypatch: Any, when: datetime) -> None:
    monkeypatch.setattr(clock, "now", lambda: when)


def phone() -> str:
    return "+9198" + "".join(random.choice("0123456789") for _ in range(8))


async def adult(
    db: AsyncSession, *, monitoring: bool = True, with_phone: bool = True, minor: bool = False, **kw: Any
) -> UserHandle:
    u = await make_user(db, phone=phone() if with_phone else None, minor=minor, **kw)
    old = clock.now() - timedelta(days=60)
    await db.execute(
        update(User)
        .where(User.id == u.id)
        .values(email_verified_at=old, phone_verified_at=old if with_phone else None)
    )
    if monitoring:
        db.add(
            Consent(
                id=uuid7(),
                user_id=u.id,
                purpose="security_monitoring",
                action="granted",
                notice_version=NOTICE,
                channel="web",
            )
        )
    await db.flush()
    return u


_actor: dict[str, uuid.UUID] = {}


async def set_policy(
    db: AsyncSession, key: str, value: Any, scope_type: str = "platform", scope_id: uuid.UUID | None = None
) -> None:
    await system_context(db, "test.policy")
    actor = await make_user(db)
    await pol.write_setting(
        db,
        key=key,
        scope_type=scope_type,
        scope_id=scope_id,
        value=value,
        changed_by=actor.id,
        change_reason="test fixture",
        effective_from=clock.now() - timedelta(days=400),
    )
    await db.flush()


async def enforce(db: AsyncSession, hc: bool = False) -> None:
    await set_policy(db, "risk.mode", "enforce")
    if hc:
        await set_policy(db, "risk.hc.auto_restrict_enabled", True)


async def activate_rule(db: AsyncSession, key: str, params: dict[str, Any] | None = None) -> RiskRuleVersion:
    """A dual-approved active DB version of one rule (fixture shortcut for SEC-24..28)."""
    await system_context(db, "test.rules")
    a, b = await make_user(db), await make_user(db)
    rid = (await db.execute(select(RiskRule.id).where(RiskRule.key == key))).scalar_one()
    v = RiskRuleVersion(
        id=uuid7(),
        rule_id=rid,
        family="sharing" if key.startswith("HC-0") else "takeover",
        ruleset_version=f"{key}-9.0.0",
        semver="9.0.0",
        definition={"params": params or {}},
        status="active",
        proposed_by=a.id,
        approved_by=b.id,
        approved_at=clock.now(),
        shadow_started_at=clock.now() - timedelta(days=20),
        created_at=clock.now(),
    )
    db.add(v)
    await db.flush()
    return v


async def staff(db: AsyncSession, role: str = "super_admin") -> UserHandle:
    u = await make_user(db, with_totp=True)
    await grant(db, u.id, role)
    return u


async def staff_browser(client: Any, user: UserHandle, *, ip: str = "198.18.0.5") -> Browser:
    b = Browser(client, ip=ip)
    await staff_login(b, user)
    await step_up(b, user)
    return b


async def device_session(
    db: AsyncSession,
    user_id: uuid.UUID,
    *,
    ip: str,
    network_type: str = "broadband",
    asn: int = 24560,
    region: str = "TG",
    ua_family: str = "Chrome",
    os_family: str = "Windows",
    device_class: str = "desktop",
    owner_verified_at: datetime | None = None,
) -> tuple[uuid.UUID, uuid.UUID]:
    """A trusted device + active session observed on one network (direct DB fixture)."""
    await system_context(db, "test.sessions")
    now = clock.now()
    dev = Device(
        id=uuid7(),
        device_key_hash=os.urandom(32),
        client_type="web",
        ua_family=ua_family,
        os_family=os_family,
        device_class=device_class,
        label_hint=f"{ua_family} on {os_family}",
        first_seen_at=now,
        last_seen_at=now,
    )
    db.add(dev)
    await db.flush()
    ud = UserDevice(
        id=uuid7(),
        user_id=user_id,
        device_id=dev.id,
        trust_status="trusted",
        trusted_at=now,
        last_used_at=now,
        owner_verified_at=owner_verified_at,
        verification_method="sms_otp" if owner_verified_at else "email_otp",
        counts_toward_cap=True,
    )
    db.add(ud)
    await db.flush()
    cluster = f"AS{asn}:{'.'.join(ip.split('.')[:3])}.0/24"
    s = AuthSession(
        id=uuid7(),
        token_hash=hash_token(uuid7().hex),
        user_id=user_id,
        device_id=dev.id,
        user_device_id=ud.id,
        client_type="web",
        session_tier="student",
        status="active",
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
        network_type=network_type,
        geo_region=region,
        ua_family=ua_family,
        os_family=os_family,
        device_class=device_class,
    )
    db.add(s)
    await db.flush()
    db.add(
        SessionNetworkObservation(
            id=uuid7(),
            first_seen_at=now - timedelta(days=40),
            last_seen_at=now,
            auth_session_id=s.id,
            user_id=user_id,
            net_cluster=cluster,
            asn=asn,
            network_type=network_type,
            geo_region=region,
        )
    )
    await db.flush()
    return dev.id, s.id


def overlap(legs: list[tuple[uuid.UUID, uuid.UUID]], start: datetime, n: int = 4) -> list[EngagedBucket]:
    return [
        EngagedBucket(device_id=d, auth_session_id=s, bucket_start=start + timedelta(minutes=5 * k))
        for k in range(n)
        for d, s in legs
    ]


async def signals_of(
    db: AsyncSession, user_id: uuid.UUID | None, rule: str | None = None
) -> list[SecuritySignal]:
    q = select(SecuritySignal).where(SecuritySignal.user_id == user_id) if user_id else select(SecuritySignal)
    if rule:
        q = q.where(SecuritySignal.rule_key == rule)
    return list((await db.execute(q)).scalars())


def idem() -> dict[str, str]:
    return {"Idempotency-Key": uuid.uuid4().hex}
