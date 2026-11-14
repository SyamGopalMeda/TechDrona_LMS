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

import contextlib
import math
import uuid
from collections.abc import AsyncGenerator, Awaitable, Callable, Iterable
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
from app.core.firestore.backend import uses_firestore
from app.core.ids import uuid7
from app.core.outbox import emit_event
from app.core.principal import Principal
from app.core.time import utcnow
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


# --------------------------------------------------------------------------- persistence switch
#
# ``TD_STORE_ENTITLEMENTS=firestore`` moves ``entitlements`` / ``entitlement_events`` to Firestore
# (``repo_firestore.py``). Audit, outbox and the decision cache stay where they are (the caller's
# Postgres session / Redis), so every change still writes its audit row and outbox event in the
# caller's transaction. Cross-store ordering: the Firestore commit happens first (as for catalog,
# docs/firebase/p2.md P2b.4 #1); grants are idempotent per source, so a retried caller does not
# grant twice.


def _fs() -> bool:
    return uses_firestore("entitlements")


@contextlib.asynccontextmanager
async def _system(session: AsyncSession, job: str) -> AsyncGenerator[None]:
    """``system_context`` on Postgres; nothing to switch without a Postgres session."""
    if not session:
        yield
        return
    async with system_context(session, job):
        yield


def _repo(principal: Principal | None = None) -> Any:
    from app.modules.entitlements.repo_firestore import repo

    return repo(principal)


Step = Callable[[Entitlement], "dict[str, Any] | None"]


def _event_fields(
    event_type: str,
    actor: Actor,
    *,
    from_status: str | None = None,
    to_status: str | None = None,
    delta: dict[str, Any] | None = None,
    reason: str | None = None,
    source_ref: uuid.UUID | None = None,
) -> dict[str, Any]:
    return {
        "event_type": event_type,
        "from_status": from_status,
        "to_status": to_status,
        "delta": delta or {},
        "reason": reason,
        "actor_type": actor.kind,
        "actor_user_id": actor.user_id,
        "source_ref": source_ref,
    }


async def _after_event(session: AsyncSession, ent: Entitlement, ev: dict[str, Any], actor: Actor) -> None:
    """Audit row + outbox event + decision-cache invalidation of one entitlement event."""
    event_type, delta = ev["event_type"], ev.get("delta") or {}
    await audit(
        session,
        actor.audit_actor(),
        f"entitlement.{event_type}",
        "entitlement",
        ent.id,
        organization_id=ent.organization_id,
        subject_user_id=ent.user_id,
        reason=ev.get("reason"),
        after={"source_type": ent.source_type, "status": ev.get("to_status") or ent.status, **delta},
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


async def _record(session: AsyncSession, ent: Entitlement, ev: dict[str, Any], actor: Actor) -> None:
    if _fs():
        await _repo().append_event(ent, ev)
    else:
        session.add(
            EntitlementEvent(
                id=uuid7(),
                entitlement_id=ent.id,
                user_id=ent.user_id,
                organization_id=ent.organization_id,
                **ev,
            )
        )
        await session.flush()
    await _after_event(session, ent, ev, actor)


async def _apply(session: AsyncSession, ent: Entitlement, actor: Actor, step: Step) -> bool:
    """Run one state change. ``step(ent)`` mutates the entitlement and returns the event fields,
    or ``None`` for "no change". Postgres: on the caller's (locked) row, then flush. Firestore: on
    the current document inside one transaction (row-lock equivalent, see repo_firestore), and
    ``ent`` is refreshed with the committed state."""
    if _fs():
        from app.modules.entitlements.repo_firestore import copy_into

        fresh, ev = await _repo().transition(ent.id, step)
        if fresh is None:
            return False
        copy_into(fresh, ent)
        if ev is None:
            return False
        await _after_event(session, ent, ev, actor)
        return True
    ev = step(ent)
    if ev is None:
        return False
    await session.flush()
    await _record(session, ent, ev, actor)
    return True


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
    """Append one event (history + audit + outbox + cache). It does **not** persist changes made
    to ``ent`` by the caller on Firestore: change state through this module's functions (e.g.
    ``credit_quota``), which write the entitlement and its event together."""
    ev = _event_fields(
        event_type,
        actor,
        from_status=from_status,
        to_status=to_status,
        delta=delta,
        reason=reason,
        source_ref=source_ref,
    )
    await _record(session, ent, ev, actor)


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
    from app.modules.commerce import public as commerce

    rows = await commerce.product_quotas(session, product_id, tuple(QUOTA_FEATURES))
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
    ev = _event_fields(
        "granted",
        actor,
        to_status="active",
        delta={"starts_at": _iso(starts_at), "ends_at": _iso(ends_at), **quotas},
        reason=reason,
        source_ref=source_ref,
    )
    if _fs():
        ent, created = await _repo().grant(values, ev)
        if created:
            await _after_event(session, ent, ev, actor)
        return ent, created
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
    await _record(session, ent, ev, actor)
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
    quotas = await quotas_for_product(session, product_id)

    def step(e: Entitlement) -> dict[str, Any] | None:
        if e.product_id == product_id:
            return None
        old = e.product_id
        e.product_id = product_id
        for col, val in quotas.items():
            cur = getattr(e, col, None)
            setattr(e, col, max(int(cur or 0), int(val or 0)))
        return _event_fields(
            "plan_changed",
            actor,
            from_status=e.status,
            to_status=e.status,
            delta={"from_product_id": str(old) if old else None, "to_product_id": str(product_id)},
            reason=reason,
            source_ref=source_ref,
        )

    return await _apply(session, ent, actor, step)


async def lock(session: AsyncSession, entitlement_id: uuid.UUID) -> Entitlement | None:
    """Postgres: the row ``FOR UPDATE``. Firestore: the current document; the state change that
    follows re-reads it inside its own transaction (``_apply``), which gives the same guarantee."""
    if _fs():
        return await _repo().get(entitlement_id)
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

    def step(e: Entitlement) -> dict[str, Any] | None:
        if e.status in ("revoked", "suspended"):
            return None
        if e.ends_at is not None and new_ends_at <= e.ends_at and e.status == "active":
            return None
        old_end, old_status = e.ends_at, e.status
        e.ends_at = max(new_ends_at, e.ends_at) if e.ends_at else new_ends_at
        e.grace_ends_at = grace_ends_at
        restored = e.status in ("grace", "expired")
        e.status = "active"
        return _event_fields(
            "restored" if restored and event_type == "extended" else event_type,
            actor,
            from_status=old_status,
            to_status="active",
            delta={"old_ends_at": _iso(old_end), "new_ends_at": _iso(e.ends_at)},
            reason=reason,
            source_ref=source_ref,
        )

    return await _apply(session, ent, actor, step)


async def enter_grace(
    session: AsyncSession, ent: Entitlement, grace_ends_at: datetime, actor: Actor, *, reason: str
) -> bool:
    def step(e: Entitlement) -> dict[str, Any] | None:
        if e.status != "active":
            return None
        e.status = "grace"
        e.grace_ends_at = grace_ends_at
        return _event_fields(
            "entered_grace",
            actor,
            from_status="active",
            to_status="grace",
            delta={"grace_ends_at": _iso(grace_ends_at)},
            reason=reason,
        )

    return await _apply(session, ent, actor, step)


async def suspend(session: AsyncSession, ent: Entitlement, actor: Actor, *, reason: str) -> bool:
    def step(e: Entitlement) -> dict[str, Any] | None:
        if e.status not in ("active", "grace"):
            return None
        old = e.status
        e.status = "suspended"
        return _event_fields("suspended", actor, from_status=old, to_status="suspended", reason=reason)

    return await _apply(session, ent, actor, step)


async def restore(session: AsyncSession, ent: Entitlement, actor: Actor, *, reason: str) -> bool:
    """``suspended``/``grace`` → ``active`` with dates unchanged (BR-ENT-11)."""

    def step(e: Entitlement) -> dict[str, Any] | None:
        if e.status not in ("suspended", "grace"):
            return None
        old = e.status
        e.status = "active"
        if old == "grace":
            e.grace_ends_at = None
        return _event_fields("restored", actor, from_status=old, to_status="active", reason=reason)

    return await _apply(session, ent, actor, step)


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

    def step(e: Entitlement) -> dict[str, Any] | None:
        if e.status != "revoked":
            return None
        now = utcnow()
        e.status = "expired" if e.ends_at is not None and e.ends_at <= now else "active"
        e.revoked_at = None
        e.revoked_by = None
        e.revoke_reason = None
        return _event_fields(
            "restored", actor, from_status="revoked", to_status=e.status, reason=reason, source_ref=source_ref
        )

    return await _apply(session, ent, actor, step)


async def revoked_by_source(session: AsyncSession, source_ref: uuid.UUID) -> list[Entitlement]:
    """Entitlements whose latest ``revoked`` event carries ``source_ref`` (e.g. a refund id)."""
    if _fs():
        r = _repo()
        wanted_fs = await r.revoked_ids_by_source(source_ref)
        got = await r.get_many(wanted_fs)
        return [got[i] for i in wanted_fs if i in got and got[i].status == "revoked"]
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
    def step(e: Entitlement) -> dict[str, Any] | None:
        if e.status == "revoked":
            return None
        old = e.status
        e.status = "revoked"
        e.revoked_at = utcnow()
        e.revoked_by = actor.user_id
        e.revoke_reason = reason_code
        return _event_fields(
            "revoked",
            actor,
            from_status=old,
            to_status="revoked",
            delta={"revoke_reason": reason_code, **(delta or {})},
            reason=note or reason_code,
            source_ref=source_ref,
        )

    return await _apply(session, ent, actor, step)


async def expire_due(session: AsyncSession, now: datetime | None = None) -> dict[str, int]:
    """Nightly job (system context): active past ``ends_at`` → ``grace`` (if a grace window
    was set, BR-ENT-17) or ``expired``; ``grace`` past ``grace_ends_at`` → ``expired``."""
    now = now or utcnow()
    actor = Actor.system("entitlements.expiry")
    counts = {"entered_grace": 0, "expired": 0}
    if _fs():
        rows = await _repo().due_for_expiry(now)
    else:
        rows = list(
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

    def step(e: Entitlement) -> dict[str, Any] | None:
        due = (e.status == "active" and e.ends_at is not None and e.ends_at <= now) or (
            e.status == "grace" and e.grace_ends_at is not None and e.grace_ends_at <= now
        )
        if not due:  # changed since it was listed (Firestore; Postgres holds the row lock)
            return None
        old = e.status
        if old == "active" and e.grace_ends_at is not None and now < e.grace_ends_at:
            e.status = "grace"
            evt = "entered_grace"
        else:
            e.status = "expired"
            evt = "expired"
        return _event_fields(evt, actor, from_status=old, to_status=e.status)

    for ent in rows:
        if await _apply(session, ent, actor, step):
            counts["entered_grace" if ent.status == "grace" else "expired"] += 1
    return counts


# --------------------------------------------------------------------------- quotas (BR-ENT-03)


def is_usable(e: Entitlement, now: datetime) -> bool:
    """The Postgres "usable" predicate of the quota queries (mentoring ``_usable`` too)."""
    return (
        e.status in ("active", "grace")
        and e.starts_at <= now
        and (e.ends_at is None or e.ends_at > now or (e.grace_ends_at is not None and e.grace_ends_at > now))
    )


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
    field_name = QUOTA_FEATURES[quota]

    def step(e: Entitlement) -> dict[str, Any] | None:
        before = getattr(e, field_name)
        if not is_usable(e, now) or (before or 0) <= 0:
            return None
        setattr(e, field_name, before - 1)
        return _event_fields(
            "quota_consumed", actor, delta={quota: {"from": before, "to": before - 1}}, source_ref=source_ref
        )

    if _fs():
        cands = [
            e
            for e in await _repo().for_user(user_id)
            if is_usable(e, now) and (getattr(e, field_name) or 0) > 0
        ]
        far = datetime.max.replace(tzinfo=now.tzinfo)
        cands.sort(key=lambda e: (e.ends_at is None, e.ends_at or far, e.created_at))
        for e in cands:  # a concurrent draw may empty one: try the next (no lost update)
            if await _apply(session, e, actor, step):
                return e
        return None
    col = getattr(Entitlement, field_name)
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
    await _apply(session, ent, actor, step)
    return ent


async def credit_quota(
    session: AsyncSession,
    entitlement_id: uuid.UUID,
    quota: Literal["mentor_sessions", "mock_tests", "resume_reviews"],
    actor: Actor,
    *,
    reason: str | None = None,
    source_ref: uuid.UUID | None = None,
) -> Entitlement | None:
    """Return one unit to an entitlement (``quota_credited``; mentoring ``credit_back``).
    ``None`` if the entitlement does not exist. Same effect as mentoring's lock + increment +
    ``record_event`` today, on either store."""
    field_name = QUOTA_FEATURES[quota]
    ent = await lock(session, entitlement_id)
    if ent is None:
        return None

    def step(e: Entitlement) -> dict[str, Any] | None:
        before = getattr(e, field_name) or 0
        setattr(e, field_name, before + 1)
        return _event_fields(
            "quota_credited",
            actor,
            delta={quota: {"from": before, "to": before + 1}},
            reason=reason,
            source_ref=source_ref,
        )

    await _apply(session, ent, actor, step)
    return ent


# --------------------------------------------------------------------------- read API for other modules
#
# Store-neutral lookups so commerce, mentoring, support, admissions and admin stop selecting from
# ``entitlements`` directly (each direct select reads stale Postgres rows once the switch is on).
# ``for_update=True`` takes the Postgres row lock; on Firestore the lock is taken by the state
# change itself (``_apply``), so it is ignored there.


async def get_entitlement(
    session: AsyncSession, entitlement_id: uuid.UUID, *, for_update: bool = False
) -> Entitlement | None:
    if _fs():
        return await _repo().get(entitlement_id)
    q = select(Entitlement).where(Entitlement.id == entitlement_id)
    return (await session.execute(q.with_for_update() if for_update else q)).scalar_one_or_none()


async def _by_source(
    session: AsyncSession, kind: str, col: Any, ids: Iterable[uuid.UUID | None], for_update: bool
) -> dict[uuid.UUID, Entitlement]:
    wanted = [i for i in dict.fromkeys(ids) if i is not None]
    if not wanted:
        return {}
    if _fs():
        return dict(await _repo().by_source(kind, wanted))
    q = select(Entitlement).where(col.in_(wanted))
    rows = (await session.execute(q.with_for_update() if for_update else q)).scalars()
    return {getattr(e, col.key): e for e in rows}


async def for_order_items(
    session: AsyncSession, order_item_ids: Iterable[uuid.UUID | None], *, for_update: bool = False
) -> dict[uuid.UUID, Entitlement]:
    """``{order_item_id: entitlement}`` (``ux_ent_order_item``)."""
    return await _by_source(session, "order_item", Entitlement.order_item_id, order_item_ids, for_update)


async def for_coupon_redemptions(
    session: AsyncSession, redemption_ids: Iterable[uuid.UUID | None], *, for_update: bool = False
) -> dict[uuid.UUID, Entitlement]:
    """``{coupon_redemption_id: entitlement}`` (``ux_ent_coupon``)."""
    return await _by_source(
        session, "coupon_redemption", Entitlement.coupon_redemption_id, redemption_ids, for_update
    )


async def for_subscription(
    session: AsyncSession, subscription_id: uuid.UUID, *, for_update: bool = False
) -> Entitlement | None:
    """The subscription's entitlement (``ux_ent_sub``: at most one)."""
    got = await _by_source(
        session, "subscription", Entitlement.subscription_id, [subscription_id], for_update
    )
    return got.get(subscription_id)


async def user_entitlements(
    session: AsyncSession,
    user_id: uuid.UUID,
    *,
    statuses: Iterable[str] | None = None,
    principal: Principal | None = None,
) -> list[Entitlement]:
    """A user's entitlements, newest first (``created_at`` desc). ``principal``: read through the
    principal's own scope on Firestore (the owner rule) instead of the system job."""
    wanted = set(statuses) if statuses is not None else None
    if _fs():
        ents = await _repo(principal).for_user(user_id)
    else:
        q = select(Entitlement).where(Entitlement.user_id == user_id)
        if wanted is not None:
            q = q.where(Entitlement.status.in_(tuple(wanted)))
        ents = list((await session.execute(q.order_by(Entitlement.created_at.desc()))).scalars())
    return [e for e in ents if wanted is None or e.status in wanted]


async def usable_entitlements(
    session: AsyncSession, user_id: uuid.UUID, now: datetime | None = None
) -> list[Entitlement]:
    """Entitlements usable at ``now`` (status active/grace, started, not past end or grace)."""
    now = now or utcnow()
    return [e for e in await user_entitlements(session, user_id) if is_usable(e, now)]


async def entitlement_history(
    session: AsyncSession, ent: Entitlement, *, principal: Principal | None = None
) -> list[EntitlementEvent]:
    """Events of ``ent``, oldest first (ENT-05)."""
    if _fs():
        return await _repo(principal).events(ent.user_id, ent.id)
    q = (
        select(EntitlementEvent)
        .where(EntitlementEvent.entitlement_id == ent.id)
        .order_by(EntitlementEvent.occurred_at)
    )
    return list((await session.execute(q)).scalars())


async def event_exists(
    session: AsyncSession, user_id: uuid.UUID, event_type: str, source_ref: uuid.UUID
) -> bool:
    """An ``entitlement_events`` row of ``user_id`` with this type and ``source_ref`` exists
    (idempotency of event-driven credits, e.g. the security false-positive extension)."""
    if _fs():
        return bool(await _repo().has_event(user_id, event_type, source_ref))
    from sqlalchemy import func

    n = (
        await session.execute(
            select(func.count())
            .select_from(EntitlementEvent)
            .where(
                EntitlementEvent.user_id == user_id,
                EntitlementEvent.event_type == event_type,
                EntitlementEvent.source_ref == source_ref,
            )
        )
    ).scalar_one()
    return bool(n)


async def source_type_counts(
    session: AsyncSession, source_types: Iterable[str], range_from: datetime, range_to: datetime
) -> dict[str, int]:
    """Entitlements created in ``[range_from, range_to)`` per source type (commerce reports)."""
    types = list(dict.fromkeys(source_types))
    if _fs():
        out: dict[str, int] = {}
        for e in await _repo().created_between(types, range_from, range_to):
            out[e.source_type] = out.get(e.source_type, 0) + 1
        return out
    from sqlalchemy import func

    rows = await session.execute(
        select(Entitlement.source_type, func.count())
        .where(
            Entitlement.source_type.in_(types),
            Entitlement.created_at >= range_from,
            Entitlement.created_at < range_to,
        )
        .group_by(Entitlement.source_type)
    )
    return {k: int(n) for k, n in rows.all()}


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
    from app.modules.commerce import public as commerce

    targets = await _targets(session, rtype, rid)
    features = {FEATURE_FOR[t] for t, _ in targets if t in FEATURE_FOR}
    by_kind: dict[str, list[uuid.UUID]] = {}
    for t, i in targets:
        by_kind.setdefault(t, []).append(i)
    products: set[uuid.UUID] = {i for t, i in targets if t == "product"}
    products |= await commerce.product_ids_covering(
        session,
        course_ids=by_kind.get("course", ()),
        test_ids=by_kind.get("test", ()),
        company_path_ids=by_kind.get("company_path", ()),
        topic_ids=by_kind.get("question_set", ()),
        feature_keys=features,
    )
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
    if _fs():
        ents = [
            e
            for e in await _repo(principal).for_user(principal.user_id)
            if e.product_id in products or e.course_id in courses or e.feature_key in features
        ]
    else:
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
    async with _system(session, "entitlements.fp_extension"):
        actor = Actor.system("security.fp_extension")
        since = restricted_since or utcnow()

        def eligible(e: Entitlement) -> bool:
            return e.ends_at is not None and (
                e.status in ("active", "grace") or (e.status == "expired" and e.ends_at >= since)
            )

        if _fs():
            rows = [e for e in await _repo().for_user(user_id) if eligible(e)]
        else:
            rows = list(
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

        def step(e: Entitlement) -> dict[str, Any] | None:
            if not eligible(e):  # changed since it was listed (Firestore)
                return None
            assert e.ends_at is not None
            old_end, old_status = e.ends_at, e.status
            new_end = e.ends_at + timedelta(days=days)
            if e.grace_ends_at is not None:
                e.grace_ends_at = e.grace_ends_at + timedelta(days=days)
            e.ends_at = new_end
            if e.status == "expired" and new_end > now:
                e.status = "active"
            return _event_fields(
                "fp_extension",
                actor,
                from_status=old_status,
                to_status=e.status,
                delta={
                    "old_ends_at": _iso(old_end),
                    "new_ends_at": _iso(new_end),
                    "days": days,
                    "uncredited_days": 0,
                    "case_ref": case_ref,
                },
                reason=reason,
                source_ref=source_ref,
            )

        for ent in rows:
            if await _apply(session, ent, actor, step):
                out["extended"] += 1
                out["entitlement_ids"].append(str(ent.id))
        if not _fs():
            await session.flush()
    return out
