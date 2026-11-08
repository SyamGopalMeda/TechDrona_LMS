"""Entitlement lifecycle, history and the access checker.

Every state change writes one ``entitlement_events`` row, one ``audit_outbox`` row and one
``entitlement.<event>`` outbox event (FR-ENT-004). Callers own the transaction.

Extension points for other modules:

* ``register_resource_parent_resolver(resource_type, fn)`` — catalog/coding/placement map a
  lesson/resource/coding problem to its parents (course, company path, topic) so products
  covering the parent cover the child.
* ``register_usage_provider(p)`` — learning/assessments report consumption %, certificates
  and started mocks for the refund rule (FR-COM-008). Until one is
  registered consumption reads as 0 % (reported as ``usage_source = "none"``).
* ``extend_entitlements_for_restriction(...)`` — security module (BR-ENT-12 / CPR).
"""

from __future__ import annotations

import math
import uuid
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Literal, Protocol

from sqlalchemy import or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.access import AccessDecision, ResourceType
from app.core.audit import AuditActor, audit
from app.core.db import system_context
from app.core.errors import ProblemError
from app.core.ids import uuid7
from app.core.outbox import emit_event
from app.core.principal import Principal
from app.core.time import utcnow
from app.modules.commerce.models import ProductItem
from app.modules.entitlements.models import Entitlement, EntitlementEvent

PRECEDENCE = {
    "placement_package": 2,
    "subscription": 3,
    "purchase": 4,
    "coupon_grant": 4,
    "admin_grant": 5,
    "trial": 5,
    "free_enrolment": 6,
}
FEATURE_FOR: dict[str, str] = {
    "course": "all_courses",
    "lesson": "all_courses",
    "resource": "all_courses",
    "test": "all_tests",
    "question_set": "all_practice",
    "coding_problem": "all_coding",
    "company_path": "all_company_paths",
}
QUOTA_FEATURES = {
    "mentor_sessions": "mentor_sessions_remaining",
    "mock_tests": "mocks_remaining",
    "resume_reviews": "resume_reviews_remaining",
}
RESTRICTION_LOCKS = frozenset({"premium_locked", "learning_locked", "content_locked"})
STAFF_PREVIEW_PERMISSION: dict[str, str] = {
    "course": "course.preview",
    "lesson": "course.preview",
    "resource": "course.preview",
    "test": "test.edit",
    "question_set": "question.edit",
    "coding_problem": "coding_problem.manage",
    "company_path": "company_path.manage",
    "product": "product.manage",
}


# --------------------------------------------------------------------------- actors


@dataclass(frozen=True, slots=True)
class Actor:
    """Who caused an entitlement change: ``user`` (principal), ``system`` job, ``gateway``."""

    kind: Literal["user", "system", "gateway"]
    principal: Principal | None = None
    job: str = "entitlements"

    @classmethod
    def user(cls, p: Principal) -> Actor:
        return cls("user", p)

    @classmethod
    def system(cls, job: str) -> Actor:
        return cls("system", job=job)

    @classmethod
    def gateway(cls, job: str = "commerce.webhook") -> Actor:
        return cls("gateway", job=job)

    @property
    def user_id(self) -> uuid.UUID | None:
        return self.principal.user_id if self.principal else None

    def audit_actor(self) -> Principal | AuditActor:
        if self.principal is not None:
            return self.principal
        if self.kind == "gateway":
            return AuditActor("gateway", system_job=self.job)
        return AuditActor.system(self.job)


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


async def record_event(
    session: AsyncSession,
    ent: Entitlement,
    event_type: str,
    actor: Actor,
    *,
    from_status: str | None = None,
    to_status: str | None = None,
    delta: dict[str, Any] | None = None,
    reason: str | None = None,
    source_ref: uuid.UUID | None = None,
) -> None:
    session.add(
        EntitlementEvent(
            id=uuid7(),
            entitlement_id=ent.id,
            user_id=ent.user_id,
            organization_id=ent.organization_id,
            event_type=event_type,
            from_status=from_status,
            to_status=to_status,
            delta=delta or {},
            reason=reason,
            actor_type=actor.kind,
            actor_user_id=actor.user_id,
            source_ref=source_ref,
        )
    )
    await session.flush()
    await audit(
        session,
        actor.audit_actor(),
        f"entitlement.{event_type}",
        "entitlement",
        ent.id,
        organization_id=ent.organization_id,
        subject_user_id=ent.user_id,
        reason=reason,
        after={"source_type": ent.source_type, "status": to_status or ent.status, **(delta or {})},
    )
    await emit_event(
        session,
        f"entitlement.{event_type}",
        {"entitlement_id": str(ent.id), "user_id": str(ent.user_id), "source_type": ent.source_type},
        aggregate_type="entitlement",
        aggregate_id=ent.id,
        organization_id=ent.organization_id,
    )
    # Decision cache: invalidate now (in-transaction), again right after this transaction
    # commits (COM-21) and once more post-commit via the outbox handler
    # ``on_entitlement_event`` (cache.py explains why all three).
    from app.modules.entitlements import cache

    await cache.bump(ent.user_id)
    cache.bump_after_commit(session, ent.user_id)


async def on_entitlement_event(session: AsyncSession, msg: Any) -> None:
    """Outbox handler for every ``entitlement.*`` event: post-commit cache invalidation."""
    from app.modules.entitlements import cache

    uid = (msg.payload or {}).get("user_id")
    if uid:
        await cache.bump(uuid.UUID(str(uid)))


def register_cache_invalidation() -> None:
    from app.core.outbox import register_handler
    from app.modules.entitlements import cache

    for et in cache.EVENT_TYPES:
        register_handler(f"entitlement.{et}", on_entitlement_event)


def entitlement_json(e: Entitlement) -> dict[str, Any]:
    return {
        "entitlement_id": str(e.id),
        "product_id": str(e.product_id) if e.product_id else None,
        "course_id": str(e.course_id) if e.course_id else None,
        "feature_key": e.feature_key,
        "organization_id": str(e.organization_id) if e.organization_id else None,
        "source_type": e.source_type,
        "source_ref": str(e.order_item_id or e.subscription_id or e.coupon_redemption_id or "") or None,
        "status": e.status,
        "starts_at": _iso(e.starts_at),
        "ends_at": _iso(e.ends_at),
        "grace_ends_at": _iso(e.grace_ends_at),
        "quotas": {
            "mentor_sessions_remaining": e.mentor_sessions_remaining,
            "mocks_remaining": e.mocks_remaining,
            "resume_reviews_remaining": e.resume_reviews_remaining,
        },
        "revoke_reason": e.revoke_reason,
    }


# --------------------------------------------------------------------------- grant


async def quotas_for_product(session: AsyncSession, product_id: uuid.UUID) -> dict[str, int]:
    rows = (
        await session.execute(
            select(ProductItem.feature_key, ProductItem.quantity).where(
                ProductItem.product_id == product_id,
                ProductItem.feature_key.in_(tuple(QUOTA_FEATURES)),
            )
        )
    ).all()
    return {QUOTA_FEATURES[k]: int(q or 0) for k, q in rows if k}


async def grant(
    session: AsyncSession,
    actor: Actor,
    *,
    user_id: uuid.UUID,
    source_type: str,
    starts_at: datetime,
    ends_at: datetime | None,
    product_id: uuid.UUID | None = None,
    course_id: uuid.UUID | None = None,
    feature_key: str | None = None,
    organization_id: uuid.UUID | None = None,
    order_item_id: uuid.UUID | None = None,
    subscription_id: uuid.UUID | None = None,
    coupon_redemption_id: uuid.UUID | None = None,
    granted_by: uuid.UUID | None = None,
    reason: str | None = None,
    grace_ends_at: datetime | None = None,
    source_ref: uuid.UUID | None = None,
) -> tuple[Entitlement, bool]:
    """Create an entitlement idempotently. Returns ``(entitlement, created)``; a second call
    for the same order item / subscription / coupon redemption returns the
    existing row (``UNIQUE`` indexes, ADR-0006)."""
    quotas = await quotas_for_product(session, product_id) if product_id else {}
    eid = uuid7()
    values: dict[str, Any] = {
        "id": eid,
        "user_id": user_id,
        "organization_id": organization_id,
        "product_id": product_id,
        "course_id": course_id,
        "feature_key": feature_key,
        "source_type": source_type,
        "order_item_id": order_item_id,
        "subscription_id": subscription_id,
        "coupon_redemption_id": coupon_redemption_id,
        "granted_by": granted_by,
        "grant_reason": reason,
        "status": "active",
        "starts_at": starts_at,
        "ends_at": ends_at,
        "grace_ends_at": grace_ends_at,
        **quotas,
    }
    inserted = (
        await session.execute(
            pg_insert(Entitlement).values(**values).on_conflict_do_nothing().returning(Entitlement.id)
        )
    ).scalar_one_or_none()
    if inserted is None:
        cond = (
            Entitlement.order_item_id == order_item_id
            if order_item_id
            else Entitlement.subscription_id == subscription_id
            if subscription_id
            else Entitlement.coupon_redemption_id == coupon_redemption_id
        )
        existing = (await session.execute(select(Entitlement).where(cond))).scalar_one()
        return existing, False
    ent = (await session.execute(select(Entitlement).where(Entitlement.id == eid))).scalar_one()
    await record_event(
        session,
        ent,
        "granted",
        actor,
        to_status="active",
        delta={"starts_at": _iso(starts_at), "ends_at": _iso(ends_at), **quotas},
        reason=reason,
        source_ref=source_ref,
    )
    return ent, True


# --------------------------------------------------------------------------- transitions


async def change_product(
    session: AsyncSession,
    ent: Entitlement,
    product_id: uuid.UUID,
    actor: Actor,
    *,
    reason: str,
    source_ref: uuid.UUID | None = None,
) -> bool:
    """COM-14: move a subscription entitlement to the new plan's product in place (one
    entitlement per subscription, ``ux_ent_sub``). Quotas never shrink mid-period."""
    if ent.product_id == product_id:
        return False
    old = ent.product_id
    ent.product_id = product_id
    quotas = await quotas_for_product(session, product_id)
    for col, val in quotas.items():
        cur = getattr(ent, col, None)
        setattr(ent, col, max(int(cur or 0), int(val or 0)))
    await session.flush()
    await record_event(
        session,
        ent,
        "plan_changed",
        actor,
        from_status=ent.status,
        to_status=ent.status,
        delta={"from_product_id": str(old) if old else None, "to_product_id": str(product_id)},
        reason=reason,
        source_ref=source_ref,
    )
    return True


async def lock(session: AsyncSession, entitlement_id: uuid.UUID) -> Entitlement | None:
    return (
        await session.execute(select(Entitlement).where(Entitlement.id == entitlement_id).with_for_update())
    ).scalar_one_or_none()


async def extend_to(
    session: AsyncSession,
    ent: Entitlement,
    new_ends_at: datetime,
    actor: Actor,
    *,
    reason: str | None = None,
    grace_ends_at: datetime | None = None,
    event_type: str = "extended",
    source_ref: uuid.UUID | None = None,
) -> bool:
    """Move ``ends_at`` forward (never backwards). A ``grace`` entitlement is restored."""
    if ent.status in ("revoked", "suspended"):
        return False
    if ent.ends_at is not None and new_ends_at <= ent.ends_at and ent.status == "active":
        return False
    old_end, old_status = ent.ends_at, ent.status
    ent.ends_at = max(new_ends_at, ent.ends_at) if ent.ends_at else new_ends_at
    ent.grace_ends_at = grace_ends_at
    restored = ent.status in ("grace", "expired")
    ent.status = "active"
    await session.flush()
    await record_event(
        session,
        ent,
        "restored" if restored and event_type == "extended" else event_type,
        actor,
        from_status=old_status,
        to_status="active",
        delta={"old_ends_at": _iso(old_end), "new_ends_at": _iso(ent.ends_at)},
        reason=reason,
        source_ref=source_ref,
    )
    return True


async def enter_grace(
    session: AsyncSession, ent: Entitlement, grace_ends_at: datetime, actor: Actor, *, reason: str
) -> bool:
    if ent.status != "active":
        return False
    ent.status = "grace"
    ent.grace_ends_at = grace_ends_at
    await session.flush()
    await record_event(
        session,
        ent,
        "entered_grace",
        actor,
        from_status="active",
        to_status="grace",
        delta={"grace_ends_at": _iso(grace_ends_at)},
        reason=reason,
    )
    return True


async def suspend(session: AsyncSession, ent: Entitlement, actor: Actor, *, reason: str) -> bool:
    if ent.status not in ("active", "grace"):
        return False
    old = ent.status
    ent.status = "suspended"
    await session.flush()
    await record_event(
        session, ent, "suspended", actor, from_status=old, to_status="suspended", reason=reason
    )
    return True


async def restore(session: AsyncSession, ent: Entitlement, actor: Actor, *, reason: str) -> bool:
    """``suspended``/``grace`` → ``active`` with dates unchanged (BR-ENT-11)."""
    if ent.status not in ("suspended", "grace"):
        return False
    old = ent.status
    ent.status = "active"
    if old == "grace":
        ent.grace_ends_at = None
    await session.flush()
    await record_event(session, ent, "restored", actor, from_status=old, to_status="active", reason=reason)
    return True


async def reinstate(
    session: AsyncSession,
    ent: Entitlement,
    actor: Actor,
    *,
    reason: str,
    source_ref: uuid.UUID | None = None,
) -> bool:
    """Undo a revocation (COM-03: the provider reported the refund that caused it as failed,
    so the customer keeps what they paid for). Dates are unchanged: an entitlement whose
    ``ends_at`` has passed comes back as ``expired``."""
    if ent.status != "revoked":
        return False
    now = utcnow()
    ent.status = "expired" if ent.ends_at is not None and ent.ends_at <= now else "active"
    ent.revoked_at = None
    ent.revoked_by = None
    ent.revoke_reason = None
    await session.flush()
    await record_event(
        session,
        ent,
        "restored",
        actor,
        from_status="revoked",
        to_status=ent.status,
        reason=reason,
        source_ref=source_ref,
    )
    return True


async def revoked_by_source(session: AsyncSession, source_ref: uuid.UUID) -> list[Entitlement]:
    """Entitlements whose latest ``revoked`` event carries ``source_ref`` (e.g. a refund id)."""
    ids = (
        await session.execute(
            select(EntitlementEvent.entitlement_id).where(
                EntitlementEvent.event_type == "revoked", EntitlementEvent.source_ref == source_ref
            )
        )
    ).scalars()
    wanted = list(dict.fromkeys(ids))
    if not wanted:
        return []
    return list(
        (
            await session.execute(
                select(Entitlement)
                .where(Entitlement.id.in_(wanted), Entitlement.status == "revoked")
                .with_for_update()
            )
        ).scalars()
    )


async def revoke(
    session: AsyncSession,
    ent: Entitlement,
    actor: Actor,
    *,
    reason_code: str,
    note: str | None = None,
    delta: dict[str, Any] | None = None,
    source_ref: uuid.UUID | None = None,
) -> bool:
    if ent.status == "revoked":
        return False
    old = ent.status
    ent.status = "revoked"
    ent.revoked_at = utcnow()
    ent.revoked_by = actor.user_id
    ent.revoke_reason = reason_code
    await session.flush()
    await record_event(
        session,
        ent,
        "revoked",
        actor,
        from_status=old,
        to_status="revoked",
        delta={"revoke_reason": reason_code, **(delta or {})},
        reason=note or reason_code,
        source_ref=source_ref,
    )
    return True


async def expire_due(session: AsyncSession, now: datetime | None = None) -> dict[str, int]:
    """Nightly job (system context): active past ``ends_at`` → ``grace`` (if a grace window
    was set, BR-ENT-17) or ``expired``; ``grace`` past ``grace_ends_at`` → ``expired``."""
    now = now or utcnow()
    actor = Actor.system("entitlements.expiry")
    counts = {"entered_grace": 0, "expired": 0}
    rows = (
        (
            await session.execute(
                select(Entitlement)
                .where(
                    or_(
                        (Entitlement.status == "active") & (Entitlement.ends_at <= now),
                        (Entitlement.status == "grace") & (Entitlement.grace_ends_at <= now),
                    )
                )
                .with_for_update(skip_locked=True)
            )
        )
        .scalars()
        .all()
    )
    for ent in rows:
        old = ent.status
        if old == "active" and ent.grace_ends_at is not None and now < ent.grace_ends_at:
            ent.status = "grace"
            counts["entered_grace"] += 1
            evt = "entered_grace"
        else:
            ent.status = "expired"
            counts["expired"] += 1
            evt = "expired"
        await session.flush()
        await record_event(session, ent, evt, actor, from_status=old, to_status=ent.status)
    return counts


# --------------------------------------------------------------------------- quotas (BR-ENT-03)


async def consume_quota(
    session: AsyncSession,
    user_id: uuid.UUID,
    quota: Literal["mentor_sessions", "mock_tests", "resume_reviews"],
    actor: Actor,
    *,
    source_ref: uuid.UUID | None = None,
    now: datetime | None = None,
) -> Entitlement | None:
    """Draw one unit from the usable entitlement ending soonest; ``None`` if none left."""
    now = now or utcnow()
    col = getattr(Entitlement, QUOTA_FEATURES[quota])
    ent = (
        await session.execute(
            select(Entitlement)
            .where(
                Entitlement.user_id == user_id,
                Entitlement.status.in_(("active", "grace")),
                Entitlement.starts_at <= now,
                or_(
                    Entitlement.ends_at.is_(None), Entitlement.ends_at > now, Entitlement.grace_ends_at > now
                ),
                col > 0,
            )
            .order_by(Entitlement.ends_at.asc().nulls_last(), Entitlement.created_at)
            .limit(1)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if ent is None:
        return None
    before = getattr(ent, QUOTA_FEATURES[quota])
    setattr(ent, QUOTA_FEATURES[quota], before - 1)
    await session.flush()
    await record_event(
        session,
        ent,
        "quota_consumed",
        actor,
        delta={quota: {"from": before, "to": before - 1}},
        source_ref=source_ref,
    )
    return ent


# --------------------------------------------------------------------------- usage provider


class UsageProvider(Protocol):
    name: str

    async def consumption_pct(
        self, session: AsyncSession, user_id: uuid.UUID, product_id: uuid.UUID
    ) -> Decimal: ...
    async def certificate_issued(
        self, session: AsyncSession, user_id: uuid.UUID, product_id: uuid.UUID
    ) -> bool: ...
    async def mocks_started(
        self, session: AsyncSession, user_id: uuid.UUID, product_id: uuid.UUID
    ) -> int: ...


class NoUsageProvider:
    """Placeholder until learning/assessments register real usage data."""

    name = "none"

    async def consumption_pct(
        self, session: AsyncSession, user_id: uuid.UUID, product_id: uuid.UUID
    ) -> Decimal:
        return Decimal("0")

    async def certificate_issued(
        self, session: AsyncSession, user_id: uuid.UUID, product_id: uuid.UUID
    ) -> bool:
        return False

    async def mocks_started(self, session: AsyncSession, user_id: uuid.UUID, product_id: uuid.UUID) -> int:
        return 0


_usage: UsageProvider = NoUsageProvider()


def register_usage_provider(provider: UsageProvider | None) -> None:
    global _usage
    _usage = provider or NoUsageProvider()


def usage_provider() -> UsageProvider:
    return _usage


# --------------------------------------------------------------------------- access checker

ParentResolver = Callable[[AsyncSession, uuid.UUID], Awaitable[list[tuple[str, uuid.UUID]]]]
_parent_resolvers: dict[str, ParentResolver] = {}


def register_resource_parent_resolver(resource_type: str, fn: ParentResolver | None) -> None:
    """e.g. ``register_resource_parent_resolver("lesson", lambda s, id: [("course", cid)])``."""
    if fn is None:
        _parent_resolvers.pop(resource_type, None)
    else:
        _parent_resolvers[resource_type] = fn


async def _targets(session: AsyncSession, rtype: str, rid: uuid.UUID) -> list[tuple[str, uuid.UUID]]:
    out = [(rtype, rid)]
    frontier = [(rtype, rid)]
    for _ in range(3):  # lesson -> course; coding_problem -> topic/path; bounded depth
        nxt: list[tuple[str, uuid.UUID]] = []
        for t, i in frontier:
            fn = _parent_resolvers.get(t)
            if fn is not None:
                for parent in await fn(session, i):
                    if parent not in out:
                        out.append(parent)
                        nxt.append(parent)
        frontier = nxt
        if not frontier:
            break
    return out


async def covering_scope(
    session: AsyncSession, rtype: str, rid: uuid.UUID
) -> tuple[set[uuid.UUID], set[uuid.UUID], set[str]]:
    """(product ids, course ids, feature keys) whose entitlements cover the resource."""
    targets = await _targets(session, rtype, rid)
    features = {FEATURE_FOR[t] for t, _ in targets if t in FEATURE_FOR}
    conds = []
    cols = {
        "course": ProductItem.course_id,
        "test": ProductItem.test_id,
        "company_path": ProductItem.company_path_id,
        "question_set": ProductItem.topic_id,
    }
    for t, i in targets:
        if t in cols:
            conds.append(cols[t] == i)
    if features:
        conds.append(ProductItem.feature_key.in_(features))
    products: set[uuid.UUID] = {i for t, i in targets if t == "product"}
    if conds:
        products |= set((await session.execute(select(ProductItem.product_id).where(or_(*conds)))).scalars())
    courses = {i for t, i in targets if t == "course"}
    return products, courses, features


def effective_state(ent: Entitlement, now: datetime) -> str:
    """``active`` | ``grace`` | ``suspended`` | ``expired`` | ``revoked`` | ``not_started``."""
    if ent.status in ("revoked", "suspended"):
        return ent.status
    if ent.starts_at > now:
        return "not_started"
    if ent.status == "expired":
        return "expired"
    if ent.status == "grace":
        return "grace" if ent.grace_ends_at and now < ent.grace_ends_at else "expired"
    if ent.ends_at is None or now < ent.ends_at:
        return "active"
    if ent.grace_ends_at and now < ent.grace_ends_at:
        return "grace"
    return "expired"


def _end_key(ent: Entitlement) -> float:
    end = ent.grace_ends_at if ent.status == "grace" else ent.ends_at
    return math.inf if end is None else end.timestamp()


def pick_winner(ents: Iterable[Entitlement]) -> Entitlement | None:
    """BR-ENT-02: placement package > subscription > purchase/coupon >
    admin/trial > free; ties go to the one ending latest."""
    ordered = sorted(ents, key=lambda e: (PRECEDENCE.get(e.source_type, 9), -_end_key(e)))
    return ordered[0] if ordered else None


async def _staff_preview(session: AsyncSession, principal: Principal, rtype: str, rid: uuid.UUID) -> bool:
    perm = STAFF_PREVIEW_PERMISSION.get(rtype)
    if not perm or not principal.grants or all(g.role == "student" for g in principal.grants):
        return False
    try:
        from app.core.auth import ScopeRef
        from app.modules.rbac.service import check_permission
    except ImportError:  # pragma: no cover - rbac always present
        return False
    scope = ScopeRef("course", rid) if rtype == "course" else ScopeRef("platform")
    try:
        return await check_permission(session, principal, perm, scope)
    except ProblemError:
        return False


@dataclass(slots=True)
class Evaluation:
    decision: AccessDecision
    winner: Entitlement | None = None
    candidates: list[Entitlement] = field(default_factory=list)
    via: str = "entitlement"


async def evaluate(
    session: AsyncSession,
    principal: Principal,
    resource_type: str,
    resource_id: uuid.UUID,
    *,
    is_free: bool = False,
    at: datetime | None = None,
) -> Evaluation:
    now = at or utcnow()
    restricted = principal.restriction_level >= 3 or bool(RESTRICTION_LOCKS & set(principal.restrictions))
    if is_free:  # BR-ENT-04: free resources stay available even under a restriction
        return Evaluation(AccessDecision(True, "free"), via="free")
    if restricted:
        return Evaluation(AccessDecision(False, "restricted"), via="restriction")
    if await _staff_preview(session, principal, resource_type, resource_id):
        return Evaluation(AccessDecision(True, "staff"), via="staff_preview")
    products, courses, features = await covering_scope(session, resource_type, resource_id)
    conds = []
    if products:
        conds.append(Entitlement.product_id.in_(products))
    if courses:
        conds.append(Entitlement.course_id.in_(courses))
    if features:
        conds.append(Entitlement.feature_key.in_(features))
    if not conds:
        return Evaluation(AccessDecision(False, "no_entitlement"))
    ents = list(
        (
            await session.execute(
                select(Entitlement).where(Entitlement.user_id == principal.user_id, or_(*conds))
            )
        ).scalars()
    )
    states = {e.id: effective_state(e, now) for e in ents}
    usable = [e for e in ents if states[e.id] in ("active", "grace")]
    winner = pick_winner(usable)
    if winner is not None:
        st = states[winner.id]
        end = winner.grace_ends_at if st == "grace" else winner.ends_at
        return Evaluation(
            AccessDecision(True, "in_grace" if st == "grace" else "entitlement", (winner.id,), end),
            winner,
            ents,
        )
    found = set(states.values())
    if "suspended" in found:
        reason = "suspended_payment"
    elif "expired" in found:
        reason = "expired"
    else:
        reason = "no_entitlement"
    return Evaluation(AccessDecision(False, reason), None, ents)


class EntitlementAccessChecker:
    """``app.core.access.AccessChecker`` implementation (FR-ENT-001) with the 60 s decision
    cache (``entitlements.cache``) in front of ``evaluate``."""

    async def check(
        self,
        session: AsyncSession,
        principal: Principal,
        resource_type: ResourceType,
        resource_id: uuid.UUID,
        *,
        is_free: bool = False,
    ) -> AccessDecision:
        from app.modules.entitlements import cache

        restricted = principal.restriction_level >= 3 or bool(RESTRICTION_LOCKS & set(principal.restrictions))
        skip = is_free or restricted or not cache.enabled()
        ver = None if skip else await cache.version(principal.user_id)
        if ver is not None:
            hit = await cache.get(principal, ver, resource_type, resource_id)
            if hit is not None:
                return hit
        decision = (await evaluate(session, principal, resource_type, resource_id, is_free=is_free)).decision
        if ver is not None:
            await cache.put(principal, ver, resource_type, resource_id, decision)
        return decision


def register_outbox_handlers() -> None:
    """Entitlement consumers: cache invalidation for ``entitlement.*``. Called at import of
    ``entitlements.router`` (API and worker both import every module router through
    ``wiring.wire_all``)."""
    register_cache_invalidation()


# --------------------------------------------------------------------------- security hook


async def extend_entitlements_for_restriction(
    session: AsyncSession,
    user_id: uuid.UUID,
    days: int,
    reason: str,
    *,
    case_ref: str | None = None,
    restricted_since: datetime | None = None,
    source_ref: uuid.UUID | None = None,
) -> dict[str, Any]:
    """BR-ENT-12 / FR-SEC-008: credit ``days`` to every time-bound entitlement that was usable
    during an overturned restriction (system action, SoD-01 allows it). ``uncredited_days``
    is kept in the result for API compatibility and is always empty.

    Runs in the caller's transaction under a system context (``app.is_platform``) that is
    restored on return (DB-06).
    Idempotency is the caller's responsibility (one call per case decision; pass the decision
    id as ``source_ref``)."""
    if days <= 0:
        raise ValueError("days must be positive")
    if not reason:
        raise ValueError("reason is required")
    async with system_context(session, "entitlements.fp_extension"):
        actor = Actor.system("security.fp_extension")
        since = restricted_since or utcnow()
        rows = (
            (
                await session.execute(
                    select(Entitlement)
                    .where(
                        Entitlement.user_id == user_id,
                        Entitlement.ends_at.is_not(None),
                        or_(
                            Entitlement.status.in_(("active", "grace")),
                            (Entitlement.status == "expired") & (Entitlement.ends_at >= since),
                        ),
                    )
                    .with_for_update()
                )
            )
            .scalars()
            .all()
        )
        out: dict[str, Any] = {"extended": 0, "entitlement_ids": [], "uncredited_days": {}}
        now = utcnow()
        for ent in rows:
            assert ent.ends_at is not None
            old_end, old_status = ent.ends_at, ent.status
            new_end = ent.ends_at + timedelta(days=days)
            uncredited = 0
            if ent.grace_ends_at is not None:
                ent.grace_ends_at = ent.grace_ends_at + timedelta(days=days)
            ent.ends_at = new_end
            if ent.status == "expired" and new_end > now:
                ent.status = "active"
            await session.flush()
            await record_event(
                session,
                ent,
                "fp_extension",
                actor,
                from_status=old_status,
                to_status=ent.status,
                delta={
                    "old_ends_at": _iso(old_end),
                    "new_ends_at": _iso(new_end),
                    "days": days,
                    "uncredited_days": uncredited,
                    "case_ref": case_ref,
                },
                reason=reason,
                source_ref=source_ref,
            )
            out["extended"] += 1
            out["entitlement_ids"].append(str(ent.id))
            if uncredited:
                out["uncredited_days"][str(ent.id)] = uncredited
        await session.flush()
    return out
