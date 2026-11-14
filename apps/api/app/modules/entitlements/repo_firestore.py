"""Firestore repository of entitlements (``TD_STORE_ENTITLEMENTS=firestore``).

``service.py`` dispatches here when the switch is on; the Postgres path is unchanged. Data model:
``store_specs.py``. Return values are **transient ORM instances** (``Entitlement``,
``EntitlementEvent``) with the model column types (UUID, aware datetime), so serializers and
callers work unchanged. They are never added to a session.

Concurrency (Postgres: ``SELECT ... FOR UPDATE`` on the entitlement, then mutate). Here every
state change is a **step** (``Callable[[Entitlement], dict | None]``): the transaction reads the
current document, builds a fresh transient ``Entitlement``, runs the step on it (the step holds
the guard, e.g. "revoke only if not revoked yet", and returns the ``entitlement_events`` row or
``None`` for "no change") and writes the changed fields **and** the event row in one commit.
The step re-runs on a fresh copy if the transaction is retried, so a concurrent change is always
seen, exactly like a row lock (no lost update, one event per real transition).

Grants are idempotent per source (``ux_ent_order_item`` / ``ux_ent_sub`` / ``ux_ent_coupon``):
``entitlement_sources/{kind:id}`` is created in the granting transaction; a concurrent second
grant fails its commit, re-reads and returns the first entitlement with ``created=False``.

Transactions owned by another module (commerce, once it moves): ``grant_many_tx`` and
``transition_many_tx`` run inside the caller's ``ScopedTransaction`` (all reads first, then all
writes, as Firestore requires), so an order and its entitlements can commit together.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Iterable, Sequence
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import DateTime
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

from app.core.firestore.codec import to_store
from app.core.firestore.errors import UniqueViolationError
from app.core.firestore.repository import FirestoreRepository, platform_only
from app.core.firestore.store import Doc, Filter, Order, ScopedStore, ScopedTransaction
from app.core.ids import uuid7
from app.core.time import utcnow
from app.modules.entitlements.models import Entitlement, EntitlementEvent
from app.modules.entitlements.store_specs import (
    ENT_FIELDS,
    ENTS,
    EVENTS,
    READ_PERMISSION,
    SOURCES,
    source_id,
    source_key,
)

JOB = "entitlements"
_PAGE = 100
_IN = 30  # Firestore ``in`` filter limit
_GRANT_ATTEMPTS = 3

Step = Callable[[Entitlement], dict[str, Any] | None]


# =========================================================================== doc <-> ORM


def _u(v: Any) -> uuid.UUID | None:
    return uuid.UUID(str(v)) if v else None


def _dt(v: Any) -> datetime | None:
    if v is None:
        return None
    if isinstance(v, datetime):
        v = v.astimezone(UTC)
        return datetime(v.year, v.month, v.day, v.hour, v.minute, v.second, v.microsecond, tzinfo=UTC)
    return datetime.fromisoformat(str(v)).astimezone(UTC)


def _orm[T](cls: type[T], d: dict[str, Any]) -> T:
    kw: dict[str, Any] = {}
    for col in cls.__table__.columns:  # type: ignore[attr-defined]
        v = d.get(col.key)
        if isinstance(col.type, PG_UUID):
            v = _u(v)
        elif isinstance(col.type, DateTime):
            v = _dt(v)
        kw[col.key] = v
    return cls(**kw)


def ent_of(d: dict[str, Any]) -> Entitlement:
    return _orm(Entitlement, d)


def event_of(d: dict[str, Any]) -> EntitlementEvent:
    e = _orm(EntitlementEvent, d)
    e.delta = dict(d.get("delta") or {})
    return e


def ent_fields(e: Entitlement) -> dict[str, Any]:
    """The document fields of an ORM entitlement (store types)."""
    return {k: to_store(getattr(e, k)) for k in ENT_FIELDS}


def copy_into(src: Entitlement, dst: Entitlement) -> None:
    """Refresh a caller's instance with the committed state (the caller keeps its reference)."""
    for k in ENT_FIELDS:
        setattr(dst, k, getattr(src, k))


# =========================================================================== CHECK constraints

_REF_COLS = ("order_item_id", "subscription_id", "coupon_redemption_id")
_REQUIRED_REF = {
    "purchase": "order_item_id",
    "placement_package": "order_item_id",
    "subscription": "subscription_id",
    "coupon_grant": "coupon_redemption_id",
}


def check_row(v: dict[str, Any]) -> None:
    """The Postgres CHECKs of ``entitlements`` (ck_ent_target/source/window/open_end/grace/revoked).
    A violation raises ``ValueError`` (Postgres: ``IntegrityError``, both a 500)."""
    if all(v.get(k) is None for k in ("product_id", "course_id", "feature_key")):
        raise ValueError("ck_ent_target: product_id, course_id or feature_key is required")
    st = v["source_type"]
    refs = {k for k in _REF_COLS if v.get(k) is not None}
    need = _REQUIRED_REF.get(st)
    if st == "institution_contract":
        if v.get("status") != "revoked":
            raise ValueError("ck_ent_no_institution")
    elif need is not None:
        if refs != {need}:
            raise ValueError(f"ck_ent_source: {st} needs exactly {need}")
    elif st == "admin_grant":
        if refs or v.get("granted_by") is None:
            raise ValueError("ck_ent_source: admin_grant needs granted_by and no source reference")
    elif st in ("free_enrolment", "trial"):
        if refs:
            raise ValueError(f"ck_ent_source: {st} takes no source reference")
    else:
        raise ValueError(f"unknown source_type {st!r}")
    starts, ends = v.get("starts_at"), v.get("ends_at")
    if ends is not None and starts is not None and not ends > starts:
        raise ValueError("ck_ent_window: ends_at must be after starts_at")
    if ends is None and st not in ("free_enrolment", "admin_grant"):
        raise ValueError("ck_ent_open_end")
    if v.get("status") == "grace" and v.get("grace_ends_at") is None:
        raise ValueError("ck_ent_grace")
    if (v.get("status") == "revoked") != (v.get("revoked_at") is not None):
        raise ValueError("ck_ent_revoked")
    for q in ("mentor_sessions_remaining", "mocks_remaining", "resume_reviews_remaining"):
        if v.get(q) is not None and int(v[q]) < 0:
            raise ValueError(f"{q} must be >= 0")


def _event_doc(ent: Entitlement, ev: dict[str, Any], now: datetime) -> tuple[str, dict[str, Any]]:
    eid = str(ev.get("id") or uuid7())
    return eid, {
        "id": eid,
        "entitlement_id": str(ent.id),
        "user_id": str(ent.user_id),
        "organization_id": to_store(ent.organization_id),
        "event_type": ev["event_type"],
        "from_status": ev.get("from_status"),
        "to_status": ev.get("to_status"),
        "delta": to_store(ev.get("delta") or {}),
        "reason": ev.get("reason"),
        "actor_type": ev["actor_type"],
        "actor_user_id": to_store(ev.get("actor_user_id")),
        "source_ref": to_store(ev.get("source_ref")),
        "occurred_at": now,
    }


# =========================================================================== repository


class EntitlementRepo(FirestoreRepository):
    """Built on the named system job ``entitlements`` (``repo()``), or on a principal's store for
    reads of the principal's own rows (``repo(principal)``): the store then applies the ``owned``
    rule (own rows, or ``entitlement.read``)."""

    # ------------------------------------------------------------------ primitives

    async def _all(
        self,
        coll: str,
        *,
        user_id: Any = None,
        filters: Sequence[Filter] = (),
        order_by: Sequence[Order] = (),
    ) -> list[Doc]:
        out: list[Doc] = []
        cursor: str | None = None
        while True:
            page = await self.store.query(
                coll, user_id=user_id, filters=filters, order_by=order_by, limit=_PAGE, cursor=cursor
            )
            out.extend(page.items)
            if not page.next_cursor:
                return out
            cursor = page.next_cursor

    # ------------------------------------------------------------------ reads

    @platform_only(READ_PERMISSION)
    async def get(self, entitlement_id: uuid.UUID) -> Entitlement | None:
        d = await self.store.get(ENTS, str(entitlement_id))
        return ent_of(d.data) if d else None

    @platform_only(READ_PERMISSION)
    async def get_many(self, ids: Iterable[uuid.UUID]) -> dict[uuid.UUID, Entitlement]:
        docs = await self.store.get_many(ENTS, [str(i) for i in ids])
        return {uuid.UUID(k): ent_of(d.data) for k, d in docs.items()}

    async def for_user(self, user_id: uuid.UUID) -> list[Entitlement]:
        """Every entitlement of ``user_id``, newest first (``created_at`` desc, id desc)."""
        docs = await self._all(ENTS, user_id=user_id, order_by=(("created_at", "desc"),))
        return [ent_of(d.data) for d in docs]

    @platform_only(READ_PERMISSION)
    async def by_source(self, kind: str, ids: Iterable[uuid.UUID]) -> dict[uuid.UUID, Entitlement]:
        """``{source id: entitlement}`` for ``kind`` = order_item / subscription / coupon_redemption."""
        wanted = [i for i in dict.fromkeys(ids) if i is not None]
        if not wanted:
            return {}
        srcs = await self.store.get_many(SOURCES, [source_id(kind, i) for i in wanted])
        by_key = {source_id(kind, i): i for i in wanted}
        ents = await self.get_many(uuid.UUID(d["entitlement_id"]) for d in srcs.values())
        out: dict[uuid.UUID, Entitlement] = {}
        for key, d in srcs.items():
            e = ents.get(uuid.UUID(d["entitlement_id"]))
            if e is not None:
                out[by_key[key]] = e
        return out

    async def events(self, user_id: uuid.UUID, entitlement_id: uuid.UUID) -> list[EntitlementEvent]:
        """History of one entitlement (owned by ``user_id``), oldest first."""
        docs = await self._all(
            EVENTS,
            user_id=user_id,
            filters=[("entitlement_id", "==", str(entitlement_id))],
            order_by=(("occurred_at", "asc"),),
        )
        return [event_of(d.data) for d in docs]

    async def has_event(self, user_id: uuid.UUID, event_type: str, source_ref: uuid.UUID) -> bool:
        page = await self.store.query(
            EVENTS,
            user_id=user_id,
            filters=[("event_type", "==", event_type), ("source_ref", "==", str(source_ref))],
            order_by=(),
            limit=1,
        )
        return bool(page.items)

    @platform_only(READ_PERMISSION)
    async def revoked_ids_by_source(self, source_ref: uuid.UUID) -> list[uuid.UUID]:
        docs = await self._all(
            EVENTS, filters=[("event_type", "==", "revoked"), ("source_ref", "==", str(source_ref))]
        )
        return list(dict.fromkeys(uuid.UUID(d["entitlement_id"]) for d in docs))

    @platform_only(READ_PERMISSION)
    async def due_for_expiry(self, now: datetime) -> list[Entitlement]:
        """``active`` past ``ends_at`` and ``grace`` past ``grace_ends_at`` (indexes
        ``status, ends_at`` / ``status, grace_ends_at``)."""
        a = await self._all(
            ENTS, filters=[("status", "==", "active"), ("ends_at", "<=", now)], order_by=(("ends_at", "asc"),)
        )
        g = await self._all(
            ENTS,
            filters=[("status", "==", "grace"), ("grace_ends_at", "<=", now)],
            order_by=(("grace_ends_at", "asc"),),
        )
        seen: dict[str, Entitlement] = {}
        for d in [*a, *g]:
            seen.setdefault(d.id, ent_of(d.data))
        return [seen[k] for k in sorted(seen)]

    @platform_only(READ_PERMISSION)
    async def created_between(
        self, source_types: Sequence[str], range_from: datetime, range_to: datetime
    ) -> list[Entitlement]:
        docs: list[Doc] = []
        for i in range(0, len(source_types), _IN):
            docs += await self._all(
                ENTS,
                filters=[
                    ("source_type", "in", list(source_types[i : i + _IN])),
                    ("created_at", ">=", range_from),
                    ("created_at", "<", range_to),
                ],
                order_by=(("created_at", "asc"),),
            )
        return [ent_of(d.data) for d in docs]

    # ------------------------------------------------------------------ writes (own transaction)

    @platform_only(READ_PERMISSION)
    async def grant(self, values: dict[str, Any], event: dict[str, Any]) -> tuple[Entitlement, bool]:
        """Insert ``values`` + its ``granted`` event, idempotent per source. ``(ent, created)``."""
        for attempt in range(_GRANT_ATTEMPTS):
            try:
                res = await self.store.run_transaction(lambda tx: self.grant_many_tx(tx, [(values, event)]))
                return res[0]
            except UniqueViolationError:
                if attempt == _GRANT_ATTEMPTS - 1:
                    raise
        raise AssertionError("unreachable")

    @platform_only(READ_PERMISSION)
    async def transition(
        self, entitlement_id: uuid.UUID, step: Step
    ) -> tuple[Entitlement | None, dict[str, Any] | None]:
        """Apply ``step`` to the current state in one transaction: ``(entitlement, event)``;
        ``event`` is ``None`` when the step made no change, the entitlement ``None`` if missing."""
        res = await self.store.run_transaction(lambda tx: self.transition_many_tx(tx, [entitlement_id], step))
        return res[0]

    @platform_only(READ_PERMISSION)
    async def append_event(self, ent: Entitlement, event: dict[str, Any]) -> None:
        """An event without a state change of this repository (``record_event`` from callers)."""
        eid, doc = _event_doc(ent, event, utcnow())
        await self.store.create(EVENTS, doc, doc_id=eid)

    # ------------------------------------------------------------------ in a caller's transaction

    @platform_only(READ_PERMISSION)
    async def grant_many_tx(
        self, tx: ScopedTransaction, items: Sequence[tuple[dict[str, Any], dict[str, Any]]]
    ) -> list[tuple[Entitlement, bool]]:
        """Grants inside ``tx``: reads every source first, then writes. ``items`` are
        ``(entitlement values, granted-event fields)``; the values carry the new ``id``."""
        keys = [source_key(v) for v, _ in items]
        srcs = await tx.get_many(SOURCES, [k for k in keys if k])
        existing = await tx.get_many(ENTS, [d["entitlement_id"] for d in srcs.values()])
        now = utcnow()
        out: list[tuple[Entitlement, bool]] = []
        planned: dict[str, Entitlement] = {}
        for (values, event), key in zip(items, keys, strict=True):
            if key and key in srcs and srcs[key]["entitlement_id"] in existing:
                out.append((ent_of(existing[srcs[key]["entitlement_id"]].data), False))
                continue
            if key and key in planned:  # the same source twice in one call
                out.append((planned[key], False))
                continue
            row = {k: to_store(values.get(k)) for k in ENT_FIELDS if k not in ("created_at", "updated_at")}
            check_row(row)
            doc = await tx.create(ENTS, row, doc_id=str(row["id"]))
            if key:
                await tx.create(
                    SOURCES, {"entitlement_id": str(row["id"]), "user_id": str(row["user_id"])}, doc_id=key
                )
            ent = ent_of(doc.data)
            eid, ev = _event_doc(ent, event, now)
            await tx.create(EVENTS, ev, doc_id=eid)
            if key:
                planned[key] = ent
            out.append((ent, True))
        return out

    @platform_only(READ_PERMISSION)
    async def transition_many_tx(
        self, tx: ScopedTransaction, ids: Sequence[uuid.UUID], step: Step
    ) -> list[tuple[Entitlement | None, dict[str, Any] | None]]:
        """Apply ``step`` to each entitlement inside ``tx`` (reads first, then writes)."""
        docs = await tx.get_many(ENTS, [str(i) for i in ids])
        now = utcnow()
        out: list[tuple[Entitlement | None, dict[str, Any] | None]] = []
        for i in ids:
            d = docs.get(str(i))
            if d is None:
                out.append((None, None))
                continue
            ent = ent_of(d.data)
            before = ent_fields(ent)
            ev = step(ent)
            if ev is None:
                out.append((ent, None))
                continue
            after = ent_fields(ent)
            changes = {
                k: v for k, v in after.items() if k not in ("created_at", "updated_at") and v != before[k]
            }
            check_row({**before, **changes})
            if changes:
                written = await tx.update_read(ENTS, d, changes)
                ent.updated_at = _dt(written.data["updated_at"])  # type: ignore[assignment]
            eid, evd = _event_doc(ent, ev, now)
            await tx.create(EVENTS, evd, doc_id=eid)
            out.append((ent, {**ev, "id": eid, "occurred_at": now}))
        return out


def repo(principal: Any = None) -> EntitlementRepo:
    """System-job repository (``principal=None``) or a principal-scoped one (own rows)."""
    return EntitlementRepo(ScopedStore(principal) if principal is not None else ScopedStore.system(JOB))
