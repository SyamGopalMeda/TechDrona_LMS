"""Analytics test helpers: users/orgs factories, a page simulator that produces wire events,
an allow-all entitlement checker and a scope-aware permission checker."""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.access import AccessDecision, get_access_checker, register_access_checker
from app.core.db import system_context, tenant_context
from app.core.ids import uuid7
from app.core.principal import Principal, RoleGrant
from app.core.time import IST, utcnow
from app.modules.analytics import hooks
from app.modules.analytics.schemas import BatchIn
from app.modules.analytics.service import ingest_batch


def uuid7_at(dt: datetime) -> str:
    ms = int(dt.timestamp() * 1000)
    r = int.from_bytes(os.urandom(10), "big")
    rand_a = r & 0xFFF
    rand_b = (r >> 12) & ((1 << 62) - 1)
    value = (ms << 80) | (0x7 << 76) | (rand_a << 64) | (0b10 << 62) | rand_b
    return str(uuid.UUID(int=value))


def ist(day: Any, hh: int, mm: int = 0, ss: float = 0.0) -> datetime:
    base = datetime(day.year, day.month, day.day, hh, mm, tzinfo=IST)
    return (base + timedelta(seconds=ss)).astimezone(UTC)


@dataclass
class Page:
    """Simulates one page instance of the web tracker (one ``page_instance_id``)."""

    surface: str
    entity: dict[str, str] = field(default_factory=dict)
    route: str = "/app/learn/[courseSlug]/[lessonId]"
    tab_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    page_instance_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    t0: datetime | None = None
    seq: int = 0

    def ev(
        self, event_type: str, at: datetime, payload: dict[str, Any], entity: dict[str, str] | None = None
    ) -> dict:
        if self.t0 is None:
            self.t0 = at
        e = {
            "event_id": uuid7_at(at),
            "event_type": event_type,
            "schema_version": 1,
            "occurred_at": at.isoformat(),
            "mono_ms": max(0, int((at - self.t0).total_seconds() * 1000)),
            "tab_id": self.tab_id,
            "page_instance_id": self.page_instance_id,
            "seq": self.seq,
            "route": self.route,
            "surface": self.surface,
            "payload": payload,
        }
        ent = entity if entity is not None else self.entity
        if ent:
            e["entity"] = {k: str(v) for k, v in ent.items()}
        self.seq += 1
        return e

    def view(self, at: datetime, visible: bool = True, focused: bool = True) -> dict:
        return self.ev("page.view", at, {"nav_type": "navigate", "visible": visible, "focused": focused})

    def hb(
        self,
        at: datetime,
        *,
        active_ms: int = 15000,
        visible: bool = True,
        focused: bool = True,
        input_recent: bool = True,
        media: bool = False,
        kind: str = "engaged",
        interval_ms: int = 15000,
        entity: dict[str, str] | None = None,
        media_info: dict[str, Any] | None = None,
        **extra: Any,
    ) -> dict:
        payload: dict[str, Any] = {
            "kind": kind,
            "sample_interval_ms": interval_ms,
            "active_ms": active_ms if kind == "engaged" else 0,
            "state": {
                "visible": visible,
                "focused": focused,
                "input_recent": input_recent,
                "media_playing": media,
            },
            **extra,
        }
        if media_info:
            payload["media"] = media_info
        return self.ev("page.heartbeat", at, payload, entity)

    def hide(self, at: datetime, reason: str = "pagehide") -> dict:
        return self.ev("page.hide", at, {"reason": reason})

    def idle(self, at: datetime, idle: bool = True, threshold: int = 90) -> dict:
        return self.ev("page.idle_change", at, {"idle": idle, "idle_threshold_s": threshold})

    def blur(self, at: datetime) -> dict:
        return self.ev("page.blur", at, {})


def batch(events: list[dict], sent_at: datetime | None = None) -> dict:
    return {
        "sent_at": (sent_at or utcnow()).isoformat(),
        "client": {
            "app_version": "web-test",
            "platform": "web",
            "tz_offset_min": 330,
            "measurement_version": "tm-1.0",
        },
        "events": events,
    }


async def ingest(
    db: AsyncSession,
    principal: Principal,
    events: list[dict],
    *,
    now: datetime | None = None,
    sent_at: datetime | None = None,
) -> list[dict]:
    """Service-level ingest in chunks of 100 under the principal's RLS context."""
    now = now or utcnow()
    out: list[dict] = []
    for i in range(0, len(events), 100):
        await tenant_context(db, principal)
        b = BatchIn.model_validate(batch(events[i : i + 100], sent_at or now))
        res = await ingest_batch(db, principal, b, now=now)
        out.extend(res.results)
    return out


async def make_user(db: AsyncSession, *, minor: bool = False, synthetic: bool = False) -> uuid.UUID:
    await system_context(db, "test.analytics")
    uid = uuid7()
    await db.execute(
        text(
            "INSERT INTO users (id, email, status, is_minor, is_synthetic, age_verified_at, age_verification_method) "
            "VALUES (:id, :e, 'active', :m, :s, now(), 'self_declared')"
        ),
        {"id": uid, "e": f"a{uid.hex[-12:]}@example.com", "m": minor, "s": synthetic},
    )
    return uid


async def grant_consent(db: AsyncSession, user_id: uuid.UUID, purpose: str, action: str = "granted") -> None:
    await system_context(db, "test.analytics")
    await db.execute(
        text(
            "INSERT INTO consents (id, user_id, purpose, action, notice_version, channel) "
            "VALUES (:id, :u, :p, :a, 'v1', 'web')"
        ),
        {"id": uuid7(), "u": user_id, "p": purpose, "a": action},
    )


async def make_org(db: AsyncSession) -> uuid.UUID:
    """Single company: the one company organization (inserted by migration orgs_0002)."""
    from app.core.company import COMPANY_ORG_ID

    return COMPANY_ORG_ID


async def add_member(db: AsyncSession, org: uuid.UUID, user: uuid.UUID, member_type: str = "student") -> None:
    await system_context(db, "test.analytics")
    await db.execute(
        text(
            "INSERT INTO org_memberships (id, organization_id, user_id, member_type, status) "
            "VALUES (:id, :o, :u, :t, 'active') ON CONFLICT DO NOTHING"
        ),
        {"id": uuid7(), "o": org, "u": user, "t": member_type},
    )


async def make_batch(db: AsyncSession, org: uuid.UUID, creator: uuid.UUID) -> uuid.UUID:
    await system_context(db, "test.analytics")
    bid = uuid7()
    await db.execute(
        text(
            "INSERT INTO batches (id, organization_id, name, code, created_by) VALUES (:id, :o, 'B', :c, :u)"
        ),
        {"id": bid, "o": org, "c": bid.hex[-10:], "u": creator},
    )
    return bid


async def add_batch_member(db: AsyncSession, batch_id: uuid.UUID, org: uuid.UUID, user: uuid.UUID) -> None:
    await system_context(db, "test.analytics")
    await db.execute(
        text(
            "INSERT INTO batch_members (id, batch_id, organization_id, user_id, member_role) "
            "VALUES (:id, :b, :o, :u, 'student')"
        ),
        {"id": uuid7(), "b": batch_id, "o": org, "u": user},
    )


def principal_for(
    user_id: uuid.UUID,
    *,
    adult: bool = True,
    device_id: uuid.UUID | None = None,
    org_ids: tuple[uuid.UUID, ...] = (),
    grants: tuple[RoleGrant, ...] = (),
    scope: str = "full",
    is_platform: bool = False,
) -> Principal:
    return Principal(
        user_id=user_id,
        session_id=uuid7(),
        device_id=device_id or uuid7(),
        is_minor=not adult,
        privacy_tier="adult" if adult else "minor",
        org_ids=org_ids,
        grants=grants,
        scope=scope,  # type: ignore[arg-type]
        is_platform=is_platform,
    )


class _AllowAll:
    async def check(
        self, session: Any, principal: Any, resource_type: Any, resource_id: Any, *, is_free: bool = False
    ):
        return AccessDecision(True, "test")


@pytest.fixture(autouse=True)
def allow_entitlements() -> Iterator[None]:
    from app.main import discover_routers

    discover_routers("all")  # import modules first: entitlements registers its checker on import
    prev = get_access_checker()
    register_access_checker(_AllowAll())
    hooks.register_engagement_toucher(_noop_touch)
    yield
    register_access_checker(prev)
    hooks.register_engagement_toucher(None)


TOUCHED: list[uuid.UUID] = []


async def _noop_touch(session_id: uuid.UUID) -> None:
    TOUCHED.append(session_id)


@dataclass
class ScopedAuth:
    """Scope-aware stand-in for the RBAC checker: grants are (user, perm, scope_type, scope_id);
    an organization grant covers that org's batches (``batch_orgs``)."""

    base: Any
    grants: set[tuple[uuid.UUID, str, str, uuid.UUID | None]] = field(default_factory=set)
    batch_orgs: dict[uuid.UUID, uuid.UUID] = field(default_factory=dict)

    def login(self, principal: Principal) -> dict[str, str]:
        return self.base.login(principal)

    def grant(
        self, principal: Principal, perm: str, scope_type: str = "platform", scope_id: uuid.UUID | None = None
    ):
        self.grants.add((principal.user_id, perm, scope_type, scope_id))

    async def has_permission(self, principal: Any, permission: str, scope: Any, request: Any) -> bool:
        chain = {("platform", None), (scope.scope_type, scope.scope_id)}
        if scope.scope_type == "batch" and scope.scope_id in self.batch_orgs:
            chain.add(("organization", self.batch_orgs[scope.scope_id]))
        return any((principal.user_id, permission, st, sid) in self.grants for st, sid in chain)


@pytest.fixture
def scoped_auth(auth: Any) -> Iterator[ScopedAuth]:
    from app.core import auth as core_auth

    sa = ScopedAuth(auth)
    core_auth.register_permission_checker(sa)
    yield sa
    core_auth.register_permission_checker(auth)


@pytest.fixture
def now() -> datetime:
    return utcnow()


async def make_attempt(
    db: AsyncSession,
    user: uuid.UUID,
    *,
    started_at: datetime,
    submitted_at: datetime | None = None,
    deadline_at: datetime | None = None,
    organization_id: uuid.UUID | None = None,
) -> uuid.UUID:
    """A real ``test_attempts`` row (plus its test) so ingest can verify ``test_attempt_id``."""
    await system_context(db, "test.analytics")
    tid, aid = uuid7(), uuid7()
    await db.execute(
        text(
            "INSERT INTO tests (id, organization_id, test_kind, title, review_policy, integrity_settings, "
            "created_by, status) VALUES (:id, :o, 'mock', 'T', '{}'::jsonb, '{}'::jsonb, :u, 'published')"
        ),
        {"id": tid, "o": organization_id, "u": user},
    )
    await db.execute(
        text(
            "INSERT INTO test_attempts (id, test_id, test_version, user_id, organization_id, attempt_no, status, "
            "selection_seed, layout, started_at, deadline_at, submitted_at, submit_reason, idempotency_key) "
            "VALUES (:id, :t, 1, :u, :o, 1, :st, :seed, '{}'::jsonb, :s, :d, :sub, :r, :k)"
        ),
        {
            "id": aid,
            "t": tid,
            "u": user,
            "o": organization_id,
            "st": "submitted" if submitted_at else "in_progress",
            "seed": os.urandom(16),
            "s": started_at,
            "d": deadline_at,
            "sub": submitted_at,
            "r": "user" if submitted_at else None,
            "k": aid.hex,
        },
    )
    return aid
