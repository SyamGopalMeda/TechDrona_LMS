"""Store-neutral persistence helpers for ``learning`` (``TD_STORE_LEARNING``).

Learning code was written against the SQLAlchemy unit of work: load ORM rows, mutate attributes,
``session.add`` new rows, ``await session.flush()``. This module keeps that shape on both stores so
the ~340 call sites port mechanically:

=====================================  ====================================================
Postgres idiom                         store-neutral call
=====================================  ====================================================
``await session.get(M, pk)``           ``await fss.get(session, M, pk)``
``select(M).where(...)``               ``await fss.find(session, M, filters=..., order_by=...)``
``session.add(obj)``                   ``fss.add(session, obj)``
``await session.delete(obj)``          ``await fss.delete(session, obj)``
``await session.flush()``              ``await fss.flush(session)``
``await session.refresh(obj)``         ``await fss.refresh(session, obj)``
=====================================  ====================================================

On Postgres every helper is the SQLAlchemy call itself (the Postgres code paths keep their exact
queries where ordering/locking/RLS matter; these helpers are for the Firestore branch and for
simple shared spots). On Firestore:

* rows come back as transient ORM instances (``fs_rows.orm_of``), **tracked** in
  ``session.info`` with a snapshot of their document;
* ``flush`` writes, in order: pending creates (row + uniqueness key documents, one transaction
  per row), pending deletes (row + keys), then a field diff of every tracked row (key documents
  are moved when a key field changes, e.g. a regrade leaving ``open``). Server defaults
  (``now()``, ``'active'``, ``'{}'`` ...) are applied on create and written back to the object,
  as a Postgres ``RETURNING``/refresh would;
* a uniqueness conflict raises ``ProblemError`` 409 with the code/detail Postgres maps the
  constraint to (``fss.UniqueConflict`` when the caller passes ``raise_unique=True``).

Everything runs as the named system job ``learning.*`` (Postgres used ``system_context`` / RLS):
callers keep their explicit authorization checks.
"""

from __future__ import annotations

import contextvars
import json
import uuid
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any, TypeVar, cast

from sqlalchemy import ARRAY, JSON, Boolean, Integer, Numeric, SmallInteger
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ProblemError
from app.core.firestore.backend import uses_firestore
from app.core.firestore.errors import UniqueViolationError
from app.core.time import utcnow
from app.modules.learning import store_specs as ss
from app.modules.learning.cert_models import CertificateOutbox
from app.modules.learning.doc_models import DocumentSettings, DocumentTemplate, IssuedDocument
from app.modules.learning.fs_rows import as_dt, doc_of, orm_of
from app.modules.learning.models import (
    Assignment,
    AssignmentAllocation,
    AssignmentItem,
    AssignmentItemResponse,
    AssignmentRegradeRequest,
    AssignmentSection,
    AssignmentSubmission,
    Certificate,
    Enrolment,
    LessonProgress,
)

T = TypeVar("T")
JOB = "learning.store"
_INFO = "learning_fs_unit"


def fs() -> bool:
    return uses_firestore("learning")


def store(job: str = JOB) -> Any:
    from app.core.firestore.store import ScopedStore

    return ScopedStore.system(job)


class UniqueConflict(Exception):
    """A learning uniqueness rule was violated on Firestore (Postgres: IntegrityError)."""

    def __init__(self, constraint: str) -> None:
        super().__init__(constraint)
        self.constraint = constraint


# Postgres constraint names -> the 409 the API answers (same as core.errors' registry).
_CONFLICT_DETAIL = {"enrolments_user_id_course_id_key": "You are already enrolled in this course."}


def conflict_problem(constraint: str) -> ProblemError:
    return ProblemError(
        "conflict",
        detail=_CONFLICT_DETAIL.get(
            constraint, "Another request changed this at the same time. Refresh and try again."
        ),
    )


# =========================================================================== model registry

Key = tuple[str, str, dict[str, Any], str]  # (key collection, key id, payload, pg constraint)


@dataclass(frozen=True)
class Table:
    model: type[Any]
    collection: str
    doc_id: Callable[[Any], str]
    keys: Callable[[Any], list[Key]] = field(default=lambda o: [])


def _s(v: Any) -> str:
    return str(v)


def _enrolment_keys(o: Any) -> list[Key]:
    return [
        (
            ss.ENROLMENT_KEYS,
            ss.enrolment_key(o.user_id, o.course_id),
            {"enrolment_id": _s(o.id)},
            "enrolments_user_id_course_id_key",
        )
    ]


def _certificate_keys(o: Any) -> list[Key]:
    return [
        (ss.CERT_CODES, o.public_code, {"certificate_id": _s(o.id)}, "certificates_public_code_key"),
        (
            ss.CERT_BY_ENROLMENT,
            _s(o.enrolment_id),
            {"certificate_id": _s(o.id)},
            "certificates_enrolment_id_key",
        ),
    ]


def _outbox_keys(o: Any) -> list[Key]:
    out: list[Key] = []
    if o.certificate_id is not None:
        out.append(
            (
                ss.CERT_OUTBOX_KEYS,
                ss.outbox_cert_key(o.certificate_id),
                {"outbox_id": _s(o.id)},
                "certificate_outbox_certificate_id_key",
            )
        )
    if o.document_id is not None and o.origin == "enrolment":
        out.append(
            (
                ss.CERT_OUTBOX_KEYS,
                ss.outbox_doc_auto_key(o.document_id),
                {"outbox_id": _s(o.id)},
                "ux_cob_document_auto",
            )
        )
    return out


def _submission_keys(o: Any) -> list[Key]:
    return [
        (
            ss.SUBMISSION_KEYS,
            ss.submission_key(o.assignment_id, o.user_id, o.attempt_no or 1),
            {"submission_id": _s(o.id)},
            "assignment_submissions_assignment_id_user_id_attempt_no_key",
        )
    ]


def _response_keys(o: Any) -> list[Key]:
    return [
        (
            ss.RESPONSE_KEYS,
            ss.response_key(o.submission_id, o.item_id),
            {"response_id": _s(o.id)},
            "assignment_item_responses_submission_id_item_id_key",
        )
    ]


def _regrade_keys(o: Any) -> list[Key]:
    if o.status != "open":
        return []
    return [(ss.REGRADE_OPEN, _s(o.submission_id), {"regrade_id": _s(o.id)}, "ux_arr_one_open")]


def _document_keys(o: Any) -> list[Key]:
    out: list[Key] = [
        (ss.DOCUMENT_KEYS, ss.doc_ref_key(o.ref_no), {"document_id": _s(o.id)}, "issued_documents_ref_no_key")
    ]
    if o.replaces_id is not None:
        out.append(
            (
                ss.DOCUMENT_KEYS,
                ss.doc_replaces_key(o.replaces_id),
                {"document_id": _s(o.id)},
                "ux_idoc_replaces",
            )
        )
    if o.origin == "enrolment" and o.enrolment_id is not None:
        out.append(
            (
                ss.DOCUMENT_KEYS,
                ss.doc_enrolment_auto_key(o.enrolment_id, o.doc_type),
                {"document_id": _s(o.id)},
                "ux_idoc_enrolment_auto",
            )
        )
    return out


def _by_id(o: Any) -> str:
    return _s(o.id)


TABLES: dict[type[Any], Table] = {
    t.model: t
    for t in (
        Table(Enrolment, ss.ENROLMENTS, _by_id, _enrolment_keys),
        Table(LessonProgress, ss.PROGRESS, lambda o: ss.progress_id(o.enrolment_id, o.lesson_key)),
        Table(Certificate, ss.CERTIFICATES, _by_id, _certificate_keys),
        Table(CertificateOutbox, ss.CERT_OUTBOX, _by_id, _outbox_keys),
        Table(Assignment, ss.ASSIGNMENTS, _by_id),
        Table(AssignmentSection, ss.SECTIONS, _by_id),
        Table(AssignmentItem, ss.ITEMS, _by_id),
        Table(AssignmentAllocation, ss.ALLOCATIONS, _by_id),
        Table(AssignmentSubmission, ss.SUBMISSIONS, _by_id, _submission_keys),
        Table(AssignmentItemResponse, ss.RESPONSES, _by_id, _response_keys),
        Table(AssignmentRegradeRequest, ss.REGRADES, _by_id, _regrade_keys),
        Table(IssuedDocument, ss.DOCUMENTS, _by_id, _document_keys),
        Table(DocumentTemplate, ss.DOC_TEMPLATES, lambda o: ss.template_id(o.kind, o.template_key)),
        Table(DocumentSettings, ss.DOC_SETTINGS, lambda o: ss.DOC_SETTINGS_ID),
    )
}


def table(model: type[Any]) -> Table:
    try:
        return TABLES[model]
    except KeyError:
        raise TypeError(f"{model.__name__} is not a learning table") from None


# =========================================================================== server defaults


def _default(col: Any, now: datetime) -> Any:
    sd = col.server_default
    if sd is None:
        return None
    arg = getattr(sd, "arg", None)
    if not isinstance(arg, str):  # func.now() / clock_timestamp()
        return now
    t = col.type
    if isinstance(t, Boolean):
        return arg.lower() == "true"
    if isinstance(t, (Integer, SmallInteger)):
        return int(arg)
    if isinstance(t, Numeric):
        return Decimal(arg)
    if isinstance(t, ARRAY):
        return []
    if isinstance(t, JSON):
        return json.loads(arg)
    return arg


def apply_defaults(obj: Any, now: datetime | None = None) -> None:
    now = now or utcnow()
    for col in type(obj).__table__.columns:
        if getattr(obj, col.key, None) is None and col.server_default is not None:
            setattr(obj, col.key, _default(col, now))


# =========================================================================== unit of work


@dataclass
class _Unit:
    tracked: dict[tuple[str, str], tuple[Any, dict[str, Any]]] = field(default_factory=dict)
    pending: list[tuple[str, Any]] = field(default_factory=list)


_ctx_unit: contextvars.ContextVar[_Unit | None] = contextvars.ContextVar("learning_fs_unit", default=None)


def _real(session: Any) -> bool:
    """A usable SQLAlchemy session (not ``None`` and not core's falsy ``NO_POSTGRES``)."""
    return session is not None and bool(session)


def _unit(session: AsyncSession | None) -> _Unit:
    """The unit of work: on the request session, or (no Postgres session at all: ``None`` /
    ``NO_POSTGRES`` on the final Firebase stack) on the current asyncio context."""
    if not _real(session):
        cu = _ctx_unit.get()
        if cu is None:
            cu = _Unit()
            _ctx_unit.set(cu)
        return cu
    assert session is not None
    u = session.info.get(_INFO)
    if u is None:
        u = session.info[_INFO] = _Unit()
    return cast(_Unit, u)


def _ident(obj: Any) -> tuple[str, str]:
    t = table(type(obj))
    return t.collection, t.doc_id(obj)


def track[T](session: AsyncSession | None, obj: T) -> T:
    """Remember ``obj``'s current document so ``flush`` writes only what changed."""
    u = _unit(session)
    key = _ident(obj)
    cur = u.tracked.get(key)
    if _real(session) and cur is not None and cur[0] is not obj:
        # the same row loaded twice: keep the first instance's identity (a mini identity map)
        return cast(T, cur[0])
    u.tracked[key] = (obj, doc_of(obj))
    return obj


def _of[T](session: AsyncSession | None, model: type[T], data: dict[str, Any]) -> T:
    return track(session, orm_of(model, data))


async def get[T](session: AsyncSession | None, model: type[T], pk: Any, *, job: str = JOB) -> T | None:
    """``session.get(model, pk)``; ``pk`` is the id (or the composite doc id for progress/templates)."""
    if not fs():
        assert session is not None
        return await session.get(model, pk)
    t = table(model)
    doc_id = pk if isinstance(pk, str) else _s(pk)
    if _real(session):
        hit = _unit(session).tracked.get((t.collection, doc_id))
        if hit is not None:
            return cast(T, hit[0])
    d = await store(job).get(t.collection, doc_id)
    return _of(session, model, d.data) if d else None


async def get_many[T](
    session: AsyncSession | None, model: type[T], pks: Iterable[Any], *, job: str = JOB
) -> dict[uuid.UUID, T]:
    """Rows by id (missing ids omitted), keyed by UUID id."""
    t = table(model)
    ids = [_s(p) for p in dict.fromkeys(pks) if p is not None]
    out: dict[uuid.UUID, T] = {}
    if not ids:
        return out
    if not fs():
        assert session is not None
        from sqlalchemy import select

        m: Any = model
        rows = (await session.execute(select(m).where(m.id.in_([uuid.UUID(i) for i in ids])))).scalars()
        return {r.id: cast(T, r) for r in rows}
    docs = await store(job).get_many(t.collection, ids)
    for k, d in docs.items():
        out[uuid.UUID(k)] = _of(session, model, d.data)
    return out


Filter = tuple[str, str, Any]
Order = tuple[str, str]


async def find[T](
    session: AsyncSession | None,
    model: type[T],
    *,
    filters: Sequence[Filter] = (),
    order_by: Sequence[Order] = (),
    limit: int | None = None,
    where: Callable[[T], bool] | None = None,
    job: str = JOB,
) -> list[T]:
    """Firestore query on the model's collection (equality/range/in/array-contains filters on
    document fields; ``where`` is an extra in-memory predicate applied before ``limit``).
    Firestore only — Postgres paths keep their own SQL."""
    t = table(model)
    st = store(job)
    out: list[T] = []
    cursor: str | None = None
    while True:
        page = await st.query(
            t.collection, filters=list(filters), order_by=list(order_by), limit=500, cursor=cursor
        )
        for d in page.items:
            obj = _of(session, model, d.data)
            if where is None or where(obj):
                out.append(obj)
                if limit is not None and len(out) >= limit:
                    return out
        if not page.next_cursor:
            return out
        cursor = page.next_cursor


async def first[T](session: AsyncSession | None, model: type[T], **kw: Any) -> T | None:
    rows = await find(session, model, limit=1, **kw)
    return rows[0] if rows else None


async def count(model: type[Any], filters: Sequence[Filter] = (), *, job: str = JOB) -> int:
    return int(await store(job).count(table(model).collection, filters=list(filters)))


async def key_target(key_collection: str, key_id: str, *, job: str = JOB) -> str | None:
    """The row id a uniqueness key document points at (e.g. the enrolment of (user, course))."""
    d = await store(job).get(key_collection, key_id)
    if d is None:
        return None
    return next((str(v) for k, v in d.data.items() if k.endswith("_id")), None)


def add(session: AsyncSession, obj: Any) -> None:
    if not fs():
        session.add(obj)
        return
    _unit(session).pending.append(("create", obj))


def add_all(session: AsyncSession, objs: Iterable[Any]) -> None:
    for o in objs:
        add(session, o)


async def delete(session: AsyncSession, obj: Any) -> None:
    if not fs():
        await session.delete(obj)
        return
    _unit(session).pending.append(("delete", obj))


async def refresh(session: AsyncSession, obj: Any) -> None:
    if not fs():
        await session.refresh(obj)


async def flush(session: AsyncSession, *, raise_unique: bool = False) -> None:
    """``session.flush()`` + (Firestore) persist pending creates/deletes and tracked changes."""
    if _real(session):
        await session.flush()
    if not fs():
        return
    u = _unit(session)
    pending, u.pending = u.pending, []
    try:
        for op, obj in pending:
            if op == "create":
                await _create(session, obj)
            else:
                await _delete(session, obj)
        for key, (obj, snap) in list(u.tracked.items()):
            await _save(session, key, obj, snap)
    except UniqueConflict as e:
        if raise_unique:
            raise
        raise conflict_problem(e.constraint) from None


async def _create(session: AsyncSession, obj: Any) -> None:
    from app.core.firestore.store import ScopedTransaction

    t = table(type(obj))
    now = utcnow()
    apply_defaults(obj, now)
    doc_id = t.doc_id(obj)
    data = doc_of(obj)
    keys = t.keys(obj)

    async def fn(tx: ScopedTransaction) -> dict[str, Any]:
        for kc, kid, _p, cons in keys:
            if await tx.raw_get(kc, kid) is not None:
                raise UniqueConflict(cons)
        if await tx.raw_get(t.collection, doc_id) is not None:
            raise UniqueConflict(f"{t.collection}_pkey")
        for kc, kid, payload, _c in keys:
            tx.raw_create(kc, kid, {**payload, "created_at": now})
        created = await tx.create(t.collection, data, doc_id=doc_id)
        return created.data

    try:
        stored = await store().run_transaction(fn)
    except UniqueViolationError:
        raise UniqueConflict(keys[0][3] if keys else f"{t.collection}_pkey") from None
    _sync(obj, stored)
    _unit(session).tracked[(t.collection, doc_id)] = (obj, doc_of(obj))


async def _delete(session: AsyncSession, obj: Any) -> None:
    from app.core.firestore.store import ScopedTransaction

    t = table(type(obj))
    doc_id = t.doc_id(obj)
    keys = t.keys(obj)

    async def fn(tx: ScopedTransaction) -> None:
        cur = await tx.raw_get(t.collection, doc_id)
        held = []
        for kc, kid, payload, _c in keys:
            k = await tx.raw_get(kc, kid)
            if k is not None and all(k.get(f) == v for f, v in payload.items()):
                held.append((kc, kid))  # only keys this row holds
        if cur is not None:
            tx.raw_delete(t.collection, doc_id)
        for kc, kid in held:
            tx.raw_delete(kc, kid)

    await store().run_transaction(fn)
    _unit(session).tracked.pop((t.collection, doc_id), None)


async def _save(session: AsyncSession, key: tuple[str, str], obj: Any, snap: dict[str, Any]) -> None:
    from app.core.firestore.store import ScopedTransaction

    t = table(type(obj))
    now_doc = doc_of(obj)
    diff = {k: v for k, v in now_doc.items() if k not in ("created_at", "updated_at") and snap.get(k) != v}
    if not diff:
        return
    before = {(kc, kid): (p, c) for kc, kid, p, c in t.keys(orm_of(type(obj), snap))}
    after = {(kc, kid): (p, c) for kc, kid, p, c in t.keys(obj)}
    gone = [k for k in before if k not in after]
    new = [(k, after[k]) for k in after if k not in before]
    doc_id = key[1]

    async def fn(tx: ScopedTransaction) -> dict[str, Any]:
        for (kc, kid), (_p, cons) in new:
            if await tx.raw_get(kc, kid) is not None:
                raise UniqueConflict(cons)
        cur = await tx.get(t.collection, doc_id)
        if cur is None:
            from app.core.errors import ProblemError

            raise ProblemError("not_found")
        for kc, kid in gone:
            tx.raw_delete(kc, kid)
        for (kc, kid), (payload, _c) in new:
            tx.raw_create(kc, kid, {**payload, "created_at": utcnow()})
        d = await tx.update_read(t.collection, cur, diff)
        return d.data

    stored = await store().run_transaction(fn)
    _sync(obj, {"updated_at": stored.get("updated_at")})
    _unit(session).tracked[key] = (obj, doc_of(obj))


def _sync(obj: Any, stored: dict[str, Any]) -> None:
    """Write store-stamped timestamps back to the object (a Postgres refresh after insert)."""
    for k in ("created_at", "updated_at"):
        if k in type(obj).__table__.columns and stored.get(k) is not None:
            setattr(obj, k, as_dt(stored[k]))


# =========================================================================== row locks (FOR UPDATE)


def evict(session: AsyncSession | None, obj: Any) -> None:
    """Forget a tracked row, so the next ``get`` reads the stored document again."""
    _unit(session).tracked.pop(_ident(obj), None)


def _adopt(session: AsyncSession | None, fresh: Any) -> Any:
    """Make the tracked instance (if any) carry ``fresh``'s values and snapshot; return it."""
    u = _unit(session)
    key = _ident(fresh)
    cur = u.tracked.get(key)
    obj = cur[0] if cur is not None else fresh
    if obj is not fresh:
        for col in type(fresh).__table__.columns:
            setattr(obj, col.key, getattr(fresh, col.key))
    u.tracked[key] = (obj, doc_of(obj))
    return obj


LOCKS = "locks"  # app.core.firestore.collections.LOCKS (leases)
LEASE_TTL_S = 300
# A waiter gives up after the lease TTL (+ margin): an expired lease means the holder died.
LEASE_WAIT_S = LEASE_TTL_S + 5.0


class LeaseBusy(Exception):
    """A lease the transaction respects is held (internal: the caller waits and retries)."""


async def locked[T, R](
    session: AsyncSession | None,
    model: type[T],
    pks: Iterable[Any],
    fn: Callable[[dict[Any, T]], R],
    *,
    job: str = JOB,
    respect_leases: Sequence[str] = (),
) -> tuple[R, dict[Any, T]]:
    """``SELECT ... FOR UPDATE`` + mutate + flush as ONE Firestore transaction (Firestore only).

    The rows are read inside the transaction; ``fn(rows)`` checks and mutates them (keep it pure:
    no I/O — it re-runs with fresh rows when a concurrent writer wins the commit, exactly like a
    Postgres transaction that waited for the row lock); the field diffs (and moved uniqueness
    keys) are written in the same transaction. Missing ids are absent from ``rows`` (keyed by
    UUID id, or by document id for composite-key tables). Returns ``(fn's result, rows after
    commit)``; the rows replace the session's tracked instances."""
    result, out = await locked_multi(
        session, [(model, pks)], lambda rows: fn(rows[model]), job=job, respect_leases=respect_leases
    )
    return result, out[model]


async def locked_multi[R](
    session: AsyncSession | None,
    specs: Sequence[tuple[type[Any], Iterable[Any]]],
    fn: Callable[[dict[type[Any], dict[Any, Any]]], R],
    *,
    job: str = JOB,
    respect_leases: Sequence[str] = (),
    lease_wait_s: float = LEASE_WAIT_S,
) -> tuple[R, dict[type[Any], dict[Any, Any]]]:
    """``locked`` over rows of several tables (e.g. a regrade request and its submission).

    ``respect_leases``: lease keys (as given to ``lease()``) that stand for a Postgres row lock
    held by other work (e.g. an e-mail being sent). The transaction reads those lease documents
    too; while one is held, it waits (polling) and retries — like a Postgres statement waiting on
    the row lock — and then acts on the rows as the holder left them. Because the lease document
    is in the transaction's read set, a lease claimed concurrently aborts and retries this
    transaction (never both proceed)."""
    import asyncio

    from app.core.firestore.store import ScopedTransaction

    plan_in = [(m, table(m), [_s(p) for p in dict.fromkeys(pks) if p is not None]) for m, pks in specs]
    out: dict[type[Any], dict[Any, Any]] = {}

    async def body(tx: ScopedTransaction) -> R:
        out.clear()
        now = utcnow()
        for key in respect_leases:
            held = await tx.raw_get(LOCKS, f"learning.{key}")
            if held is not None and held.get("expire_at") is not None and held["expire_at"] > now:
                raise LeaseBusy(key)
        loaded: dict[type[Any], tuple[Table, dict[str, Any], dict[Any, Any], dict[Any, dict[str, Any]]]] = {}
        for m, t, ids in plan_in:
            docs = await tx.get_many(t.collection, ids)
            rows = {(uuid.UUID(k) if t.doc_id is _by_id else k): orm_of(m, d.data) for k, d in docs.items()}
            loaded[m] = (t, docs, rows, {k: doc_of(v) for k, v in rows.items()})
        result = fn({m: v[2] for m, v in loaded.items()})
        plans = []
        for m, (t, docs, rows, snaps) in loaded.items():
            for k, obj in rows.items():
                now_doc = doc_of(obj)
                diff = {
                    f: v
                    for f, v in now_doc.items()
                    if f not in ("created_at", "updated_at") and snaps[k].get(f) != v
                }
                if not diff:
                    continue
                before = {(kc, kid): (p, c) for kc, kid, p, c in t.keys(orm_of(m, snaps[k]))}
                after = {(kc, kid): (p, c) for kc, kid, p, c in t.keys(obj)}
                gone = [x for x in before if x not in after]
                new = [(x, after[x]) for x in after if x not in before]
                plans.append((t, docs[str(k)], obj, diff, gone, new))
        for _t, _d, _o, _diff, _gone, new in plans:  # every read before the first write
            for (kc, kid), (_p, cons) in new:
                if await tx.raw_get(kc, kid) is not None:
                    raise UniqueConflict(cons)
        for t, cur, obj, diff, gone, new in plans:
            for kc, kid in gone:
                tx.raw_delete(kc, kid)
            for (kc, kid), (payload, _c) in new:
                tx.raw_create(kc, kid, {**payload, "created_at": utcnow()})
            d = await tx.update_read(t.collection, cur, diff)
            _sync(obj, {"updated_at": d.data.get("updated_at")})
        out.update({m: v[2] for m, v in loaded.items()})
        return result

    loop = asyncio.get_running_loop()
    deadline = loop.time() + lease_wait_s
    delay = 0.02
    while True:
        try:
            result = await store(job).run_transaction(body)
            break
        except UniqueConflict as e:
            raise conflict_problem(e.constraint) from None
        except LeaseBusy:
            if loop.time() >= deadline:
                raise ProblemError(
                    "conflict", detail="Another request is working on this item. Try again shortly."
                ) from None
            await asyncio.sleep(delay)
            delay = min(delay * 2, 0.5)
    adopted = {m: {k: _adopt(session, v) for k, v in rows.items()} for m, rows in out.items()}
    return result, adopted


async def lease(key: str, ttl_s: int = LEASE_TTL_S, *, job: str = JOB) -> str | None:
    """Claim ``locks/learning.<key>`` (``SKIP LOCKED`` / row-lock-while-working replacement):
    the holder id, or ``None`` when someone else holds it."""
    from datetime import timedelta

    holder = _s(uuid.uuid4())
    ok = await store(job).claim_lease(f"learning.{key}", holder, timedelta(seconds=ttl_s))
    return holder if ok else None


async def release(key: str, holder: str, *, job: str = JOB) -> None:
    await store(job).release_lease(f"learning.{key}", holder)


def copy_into(obj: Any, fresh: Any) -> Any:
    """Give ``obj`` the column values of ``fresh`` (the same row read in a locked section)."""
    if fresh is not obj:
        for col in type(obj).__table__.columns:
            setattr(obj, col.key, getattr(fresh, col.key))
    return obj


# =========================================================================== SQL text semantics


def like(value: str | None, pattern: str, *, escape: str = "\\") -> bool:
    """Postgres ``value LIKE pattern``: ``%`` = any run, ``_`` = one character, ``escape``
    (default backslash) makes the next character literal; a NULL value never matches.
    Registers search with ``lower(col) LIKE '%term%'`` where the term is not escaped, so a
    ``_`` or ``%`` typed by the user is a wildcard on Postgres — and therefore here too."""
    import re

    if value is None:
        return False
    out = []
    i = 0
    while i < len(pattern):
        ch = pattern[i]
        if escape and ch == escape and i + 1 < len(pattern):
            out.append(re.escape(pattern[i + 1]))
            i += 2
            continue
        out.append(".*" if ch == "%" else "." if ch == "_" else re.escape(ch))
        i += 1
    return re.fullmatch("".join(out), value, flags=re.S) is not None


async def system_row(session: AsyncSession, principal: Any, stmt: Any) -> Any:
    """Postgres only: one scope-resolution lookup on **learning's own tables** in a named system
    context, then the principal's RLS context is restored (what ``catalog.system_lookup`` did for
    these lookups; the Firestore branches read the row with ``fss.get``)."""
    from app.core.db import system_context, tenant_context

    await system_context(session, "learning.scope_lookup")
    try:
        return (await session.execute(stmt)).first()
    finally:
        await tenant_context(session, principal)
