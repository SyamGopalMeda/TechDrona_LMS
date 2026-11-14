"""Security pass 2 on Firestore (``TD_STORE_SECURITY=firestore``): the risk engine
(``engine.py``), signal ingestion and counters (``signals.py``) and the evidence views
(``timeline.py``). Security pass 2 agent; docs/firebase/agents/security-pass2.md.

The engine keeps **one** copy of its logic. ``engine.py`` / ``signals.py`` / ``timeline.py`` call
the small helpers at the bottom of this file only where they touched a security table; on Postgres
those helpers are the exact SQLAlchemy calls they replace. Identity, sessions, rbac and orgs are
reached only through their ``public.py`` (see ``security/adapters.py`` and the ``*_fs`` helpers).

Documents are the ``security.store_specs`` row classes on the collections the backfill fills
(same ids: ``compose_id(id, occurred_at)`` for signals, ``compose_id(id, evaluated_at)`` for
evaluations), so the other security passes read the same rows.

* **Retention (R-RISK, privacy §7 D7):** ``security_signals`` and ``risk_evaluations`` carry
  ``expire_at = occurred_at / evaluated_at + 180 days`` (Firestore TTL policy; Postgres drops the
  monthly partitions after 180 days).
* **Counters** (``security_counters``, 2-day retention): one document per
  ``(counter_key, minute bucket, shard)``; a bump is a Firestore transaction on one of
  ``COUNTER_SHARDS`` shards (exact count, contention spread over the shards); a window count sums
  every document of the key with ``bucket_start >= since`` (backfilled unsharded documents
  included). ``expire_at = bucket + 2 days``.
* Writes are immediate (the Postgres hook ran in a savepoint; here a detector that fails half way
  keeps the signals it already wrote -- they are append-only evidence).
* ``FOR UPDATE`` reads become optimistic saves (``save_row``: 409 ``conflict`` on a lost race);
  ``security_user_state`` saves only the changed fields (SQLAlchemy's UPDATE semantics).
"""

from __future__ import annotations

import random
import time
import uuid
from collections.abc import AsyncIterator, Iterable
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from app.core.firestore.backend import uses_firestore
from app.core.firestore.collections import get_spec
from app.core.firestore.ids import compose_id
from app.core.firestore.repository import FirestoreRepository, platform_only
from app.core.firestore.store import Doc, ScopedStore, ScopedTransaction
from app.core.time import utcnow
from app.modules.admin.fs_rows import FsRow, model_doc_id, save_row
from app.modules.security import models as m
from app.modules.security.store_specs import (
    CaseDecisionRow,
    CaseNoteRow,
    CaseRow,
    CounterRow,
    NoticeRow,
    RestrictionRow,
    RiskEvaluationRow,
    RiskRuleRow,
    RiskRuleVersionRow,
    SignalRow,
)


async def _all(store: ScopedStore, coll: str, **kw: Any) -> list[Doc]:
    """``repo_firestore._all`` imported lazily: ``store_specs`` imports this module, and
    ``repo_firestore`` imports ``store_specs`` (an import cycle when ``repo_firestore`` loads first)."""
    from app.modules.security.repo_firestore import _all as page_all

    return await page_all(store, coll, **kw)


SIGNALS = "security_signals"
EVALS = "risk_evaluations"
COUNTERS = "security_counters"
RULES = "risk_rules"
VERSIONS = "risk_rule_versions"
CASES = "security_cases"
DECISIONS = "case_decisions"
NOTES = "case_notes"
NOTICES = "security_notices"
RESTRICTIONS = "account_restrictions"
STATE = "security_user_state"

RISK_RETENTION = timedelta(days=180)
COUNTER_RETENTION = timedelta(days=2)
COUNTER_SHARDS = 4
SYS = "security.case.read"  # @platform_only key: system jobs pass
_IN = 30  # Firestore ``in`` limit

_signal_doc_id = model_doc_id(m.SecuritySignal)
_eval_doc_id = model_doc_id(m.RiskEvaluation)

# ORM model -> (collection, row class) for the inserts the engine makes.
_ROWS: dict[Any, tuple[str, Any]] = {
    m.SecuritySignal: (SIGNALS, SignalRow),
    m.RiskEvaluation: (EVALS, RiskEvaluationRow),
    m.SecurityCase: (CASES, CaseRow),
    m.CaseNote: (NOTES, CaseNoteRow),
    m.SecurityNotice: (NOTICES, NoticeRow),
}
_COLL_OF_ROW = {cls: coll for coll, cls in _ROWS.values()}


def fs() -> bool:
    return uses_firestore("security")


def _numeric_scales(model: Any) -> dict[str, int]:
    from sqlalchemy import Numeric

    return {
        c.key: int(c.type.scale or 0)
        for c in model.__table__.columns
        if isinstance(c.type, Numeric) and getattr(c.type, "scale", None) is not None
    }


_SCALES = {coll: _numeric_scales(mdl) for mdl, (coll, _cls) in _ROWS.items()}


def _quantized(coll: str, data: dict[str, Any]) -> dict[str, Any]:
    """NUMERIC(p, s) columns as Postgres stores them (rounded half away from zero to ``s``)."""
    for k, s in _SCALES.get(coll, {}).items():
        v = data.get(k)
        if v is not None:
            data[k] = str(Decimal(v).quantize(Decimal(1).scaleb(-s), rounding=ROUND_HALF_UP))
    return data


def _doc_id(coll: str, row: Any) -> str:
    if coll == SIGNALS:
        return str(_signal_doc_id({"id": row.id, "occurred_at": row.occurred_at}))
    if coll == EVALS:
        return str(_eval_doc_id({"id": row.id, "evaluated_at": row.evaluated_at}))
    return str(row.id)


# --------------------------------------------------------------------------- retention (R-RISK)
# Postgres ``maint.purge_expired_rows`` deletes ``security_signals`` / ``risk_evaluations`` older
# than the active ``retention_policies.retention_interval`` of the table, **except** rows of a user
# who has a security case that is not closed or is on legal hold (and, for evaluations, rows whose
# own ``case_id`` is such a case). Rows without a user are never held. On Firestore the TTL field
# ``expire_at`` is that predicate: ``None`` while the subject is held, else time + interval.

_TIME_FIELD = {SIGNALS: "occurred_at", EVALS: "evaluated_at"}
_interval_cache: dict[str, tuple[float, Any]] = {}
_INTERVAL_TTL_S = 300.0


async def retention_interval(table: str, session: Any = None) -> Any:
    """``admin.public.retention_interval``: the shortest active ``retention_policies`` interval
    of ``table`` as a ``PgInterval`` (months / days / microseconds, as the purge functions use it),
    cached 5 minutes. 180 days when there is no active row (the Postgres purge refuses to run
    then; the Firestore TTL needs a value), or when admin is on Postgres and no session is at
    hand."""
    from app.modules.admin.intervals import PgInterval

    hit = _interval_cache.get(table)
    if hit is not None and hit[0] > time.monotonic():
        return hit[1]
    value: Any = PgInterval.from_timedelta(RISK_RETENTION)
    if uses_firestore("admin") or session:
        from app.modules.admin import public as ap

        iv = await ap.retention_interval(session, table)
        if iv is not None:
            value = iv
    _interval_cache[table] = (time.monotonic() + _INTERVAL_TTL_S, value)
    return value


def expires(ts: datetime, interval: Any) -> datetime:
    """``ts + interval`` with Postgres calendar semantics (``admin.intervals.add_interval``)."""
    from app.modules.admin.intervals import add_interval

    return add_interval(ts, interval)


def _held(cases: Iterable[Any]) -> bool:
    return any(c.status != "closed" or bool(c.legal_hold) for c in cases)


# --------------------------------------------------------------------------- detector journal
# The Postgres sink runs each detector in a SAVEPOINT: a detector that fails half way leaves
# nothing behind -- no signals, counters, engine rows, restrictions, user-state / session /
# user changes, notifications, audit rows or outbox events. On Firestore ``detector_scope()``
# opens its own undo journal of the access modules (``identity.fs_journal``): the identity and
# sessions repositories (``JournalingStore``) record their before-images into it, this
# repository records compensations for its own writes, and the engine records the documents it
# makes other modules write without a journal (notifications). Restrictions, family heads and
# user state are journaled by ``security.repo_firestore`` (``JournalingStore``). Audit rows and
# outbox events (``core.outbox.emit_event``, buffered) are checkpointed and truncated. On failure
# everything is undone in reverse order; on success the journal is handed to the enclosing scope.


def _journal() -> Any:
    from app.modules.identity import fs_journal

    return fs_journal.current()


def _log(*entry: Any) -> None:
    """Record a compensation for one of this repository's writes in the open journal."""
    j = _journal()
    if j is None:
        return
    if entry[0] == "resync":  # runs last: after the case and evidence writes are undone
        j.order.insert(0, lambda e=entry: _undo_one(e))
    else:
        j.order.append(lambda e=entry: _undo_one(e))


def record_created(collection: str, doc_id: str) -> None:
    """A document another module just created inside the scope (undo = delete)."""
    j = _journal()
    if j is not None:
        j.record(collection, doc_id, None)


async def capture(collection: str, doc_id: str) -> None:
    """Before-image of a document another module is about to write inside the scope."""
    from app.modules.identity import fs_journal

    await fs_journal.capture(collection, doc_id)


def on_rollback(cb: Any) -> None:
    from app.modules.identity import fs_journal

    fs_journal.on_rollback(cb)


async def _undo_one(e: tuple[Any, ...]) -> None:
    import structlog

    store = ScopedStore.system("security.detector_rollback")

    async def fn(tx: ScopedTransaction) -> None:
        if e[0] == "delete":
            if await tx.raw_get(e[1], e[2]) is not None:
                tx.raw_delete(e[1], e[2])
        elif e[0] == "decr":
            cur = await tx.raw_get(COUNTERS, e[1])
            if cur is not None:
                n = int(cur.get("count", 0)) - 1
                if n <= 0:
                    tx.raw_delete(COUNTERS, e[1])
                else:
                    tx.raw_set(COUNTERS, e[1], {**cur, "count": n, "updated_at": utcnow()})
        elif e[0] == "restore":
            cur = await tx.raw_get(e[1], e[2])
            if cur is not None:
                tx.raw_set(e[1], e[2], {**cur, **e[3], "updated_at": utcnow()})

    try:
        if e[0] == "resync":
            await repo().sync_evidence(e[1])
        else:
            await store.run_transaction(fn)
    except Exception as exc:  # pragma: no cover - keep compensating the rest
        structlog.get_logger("app.security.engine").error(
            "security_detector_rollback_failed", step=e[0], error=type(exc).__name__
        )


@asynccontextmanager
async def detector_scope() -> AsyncIterator[None]:
    """Savepoint replacement for one detector (no-op on Postgres): ``identity.fs_journal.savepoint()``
    (its writes are undone on its own failure even when the sink catches the error; on success
    they join an enclosing journal), and
    ``core.request_commit.buffer_open()`` for audit rows / outbox events (a checkpoint of the
    request's buffers, or buffers of its own committed when the detector succeeds)."""
    if not fs():
        yield
        return
    from app.core import request_commit
    from app.modules.identity import fs_journal

    async with request_commit.buffer_open(), fs_journal.savepoint():
        yield


# --------------------------------------------------------------------------- other-module writes


def notification_created(user_id: uuid.UUID, notification_id: Any, dedupe_key: str | None) -> None:
    """After ``notifications.notify`` inside a detector: the documents it created (inbox row and
    dedupe marker, from ``notifications.public.created_documents``) are deleted on rollback."""
    if _journal() is None or notification_id is None:
        return
    from app.modules.notifications import public as notifications_public

    for coll, doc_id in notifications_public.created_documents(user_id, notification_id, dedupe_key):
        record_created(coll, doc_id)


class EngineRepo(FirestoreRepository):
    """Named system job (the Postgres engine ran as ``as_system`` too); routes keep their
    permission checks."""

    # ------------------------------------------------------------------ inserts / saves

    @platform_only(SYS)
    async def insert(self, row: FsRow) -> FsRow:
        coll = _COLL_OF_ROW[type(row)]
        data = _quantized(coll, row.doc())
        if coll in _TIME_FIELD:
            held = row.user_id is not None and _held(await self.cases_of(row.user_id))
            data["expire_at"] = (
                None if held else expires(getattr(row, _TIME_FIELD[coll]), await retention_interval(coll))
            )
        doc_id = _doc_id(coll, row)
        if data.get("user_id") or get_spec(coll).family != "owned":
            d = await self.store.create(coll, data, doc_id=doc_id)
        else:
            # Signals without a subject (AB-04/05/07 per source): the owned-collection create
            # check needs an owner, so the system job writes the document directly.
            spec = get_spec(coll)

            async def fn(tx: ScopedTransaction) -> Doc:
                now = utcnow()
                stored = {**data, "created_at": now, "updated_at": now, "schema_version": spec.schema_version}
                tx.raw_create(coll, doc_id, stored)
                return Doc(doc_id, stored)

            d = await self.store.run_transaction(fn)
        _log("delete", coll, doc_id)
        row.mark_saved(d.data)
        return row

    @platform_only(SYS)
    async def save(self, row: FsRow) -> FsRow:
        """Optimistic save of a changed case / notice row (``FOR UPDATE`` replacement)."""
        coll = _COLL_OF_ROW[type(row)]
        old = {k: (row._snapshot or {}).get(k) for k in row.changes()}

        async def fn(tx: ScopedTransaction) -> Doc | None:
            return await save_row(tx, coll, row)

        d = await self.store.run_transaction(fn)
        if d is not None:
            _log("restore", coll, str(row.id), old)
            row.mark_saved(d.data)
        return row

    async def save_state_fields(self, user_id: uuid.UUID, st: Any) -> Any:
        """Write only the changed columns of ``security_user_state`` (the ORM's UPDATE)."""
        ch = st.changes()
        if not ch:
            return st

        async def fn(tx: ScopedTransaction) -> tuple[Doc, dict[str, Any] | None]:
            cur = await tx.get(STATE, str(user_id))
            if cur is None:
                return await tx.create(STATE, st.doc(), doc_id=str(user_id)), None
            return await tx.update_read(STATE, cur, ch), {k: cur.get(k) for k in ch}

        d, old = await self.store.run_transaction(fn)
        if old is None:
            _log("delete", STATE, str(user_id))
        else:
            _log("restore", STATE, str(user_id), old)
        st.mark_saved(d.data)
        return st

    # ------------------------------------------------------------------ signals

    async def user_signals(
        self, user_id: uuid.UUID, *, family: str | None = None, rule_key: str | None = None
    ) -> list[Any]:
        """Every signal of a user (optionally one family / rule), oldest first."""
        f: list[Any] = []
        if family is not None:
            f.append(("family", "==", family))
        if rule_key is not None:
            f.append(("rule_key", "==", rule_key))
        docs = await _all(self.store, SIGNALS, user_id=user_id, filters=tuple(f), order_by=())
        rows = [SignalRow.of(d) for d in docs]
        rows.sort(key=lambda r: (r.occurred_at, str(r.id)))
        return rows

    @platform_only(SYS)
    async def rule_signals_since(self, rule_key: str, since: datetime) -> list[Any]:
        """Signals of one rule with ``occurred_at > since`` (any user; index rule_key+occurred_at)."""
        docs = await _all(
            self.store,
            SIGNALS,
            filters=(("rule_key", "==", rule_key), ("occurred_at", ">", since)),
            order_by=(("occurred_at", "asc"),),
        )
        return [SignalRow.of(d) for d in docs]

    # ------------------------------------------------------------------ evaluations

    async def evaluations(self, user_id: uuid.UUID, family: str | None = None) -> list[Any]:
        f: Any = (("family", "==", family),) if family else ()
        docs = await _all(self.store, EVALS, user_id=user_id, filters=f, order_by=())
        return [RiskEvaluationRow.of(d) for d in docs]

    # ------------------------------------------------------------------ counters

    @platform_only(SYS)
    async def bump(self, key: str, now: datetime) -> int:
        bucket = now.replace(second=0, microsecond=0)
        shard = random.randrange(COUNTER_SHARDS)  # noqa: S311 - load spreading, not security
        doc_id = compose_id(key, bucket.isoformat(), shard)
        spec = get_spec(COUNTERS)

        async def fn(tx: ScopedTransaction) -> int:
            cur = await tx.raw_get(COUNTERS, doc_id)
            n = int((cur or {}).get("count", 0)) + 1
            ts = utcnow()
            _log("decr", doc_id)
            tx.raw_set(
                COUNTERS,
                doc_id,
                {
                    "counter_key": key,
                    "bucket_start": bucket,
                    "count": n,
                    "shard": shard,
                    "expire_at": bucket + COUNTER_RETENTION,
                    "created_at": (cur or {}).get("created_at") or ts,
                    "updated_at": ts,
                    "schema_version": spec.schema_version,
                },
            )
            return n

        return int(await self.store.run_transaction(fn))

    @platform_only(SYS)
    async def count_since(self, key: str, since: datetime) -> int:
        docs = await _all(
            self.store,
            COUNTERS,
            filters=(("counter_key", "==", key), ("bucket_start", ">=", since)),
            order_by=(("bucket_start", "asc"),),
        )
        return sum(int(CounterRow.of(d).count or 0) for d in docs)

    # ------------------------------------------------------------------ rules

    @platform_only(SYS)
    async def active_ruleset_row(self, family: str) -> Any | None:
        docs = await _all(
            self.store,
            VERSIONS,
            filters=(("family", "==", family), ("rule_id", "==", None), ("status", "==", "active")),
            order_by=(),
        )
        if len(docs) > 1:
            from sqlalchemy.exc import MultipleResultsFound

            raise MultipleResultsFound("Multiple rows were found when one or none was required")
        return RiskRuleVersionRow.of(docs[0]) if docs else None

    @platform_only(SYS)
    async def rules_by_key(self, key: str) -> list[Any]:
        docs = await _all(self.store, RULES, filters=(("key", "==", key),), order_by=())
        return [RiskRuleRow.of(d) for d in docs]

    @platform_only(SYS)
    async def live_rule_versions(self, key: str) -> list[Any]:
        """Versions of rule ``key`` in status active/shadow, newest ``created_at`` first."""
        rows: list[Any] = []
        for rule in await self.rules_by_key(key):
            docs = await _all(self.store, VERSIONS, filters=(("rule_id", "==", str(rule.id)),), order_by=())
            rows += [RiskRuleVersionRow.of(d) for d in docs]
        rows = [r for r in rows if r.status in ("active", "shadow")]
        rows.sort(key=lambda r: (r.created_at, str(r.id)), reverse=True)
        return rows

    @platform_only(SYS)
    async def save_rule_version(self, row: Any) -> Any:
        """Status change of a rule version. ``risk_rule_versions`` is append-only for principals
        (definitions are immutable); the engine's circuit breaker changes only the status columns,
        as the Postgres UPDATE did, with the optimistic ``updated_at`` check."""
        ch = row.changes()
        if not ch:
            return row

        async def fn(tx: ScopedTransaction) -> dict[str, Any]:
            from app.core.errors import ProblemError

            cur = await tx.raw_get(VERSIONS, str(row.id))
            if cur is None:
                raise ProblemError("not_found")
            if cur.get("updated_at") != row._stored_updated_at:
                raise ProblemError("conflict")
            new = {**cur, **ch, "updated_at": utcnow()}
            tx.raw_set(VERSIONS, str(row.id), new)
            return new

        old = {k: (row._snapshot or {}).get(k) for k in ch}
        row.mark_saved(await self.store.run_transaction(fn))
        _log("restore", VERSIONS, str(row.id), old)
        return row

    @platform_only(SYS)
    async def clear_active_version(self, key: str) -> int:
        n = 0
        for rule in await self.rules_by_key(key):

            async def fn(tx: ScopedTransaction, rid: str = str(rule.id)) -> Doc:
                return await tx.update(RULES, rid, {"active_version_id": None})

            await self.store.run_transaction(fn)
            _log("restore", RULES, str(rule.id), {"active_version_id": rule.doc().get("active_version_id")})
            n += 1
        return n

    # ------------------------------------------------------------------ cases / decisions / notices

    async def cases_of(self, user_id: uuid.UUID, family: str | None = None) -> list[Any]:
        f: Any = (("family", "==", family),) if family else ()
        docs = await _all(self.store, CASES, user_id=user_id, filters=f, order_by=())
        return [CaseRow.of(d) for d in docs]

    @platform_only(SYS)
    async def decisions_for_cases(self, case_ids: list[uuid.UUID]) -> list[Any]:
        ids = sorted({str(c) for c in case_ids})
        out: list[Any] = []
        for i in range(0, len(ids), _IN):
            chunk = ids[i : i + _IN]
            docs = await _all(self.store, DECISIONS, filters=(("case_id", "in", chunk),), order_by=())
            out += [CaseDecisionRow.of(d) for d in docs]
        return out

    @platform_only(SYS)
    async def notes_for_case(self, case_id: uuid.UUID) -> list[Any]:
        docs = await _all(self.store, NOTES, filters=(("case_id", "==", str(case_id)),), order_by=())
        return [CaseNoteRow.of(d) for d in docs]

    @platform_only(SYS)
    async def restrictions_by_hc_rule(self, rule: str) -> list[Any]:
        docs = await _all(self.store, RESTRICTIONS, filters=(("hc_rule", "==", rule),), order_by=())
        return [RestrictionRow.of(d) for d in docs]

    async def restrictions_of(self, user_id: uuid.UUID) -> list[Any]:
        docs = await _all(self.store, RESTRICTIONS, user_id=user_id, order_by=())
        return [RestrictionRow.of(d) for d in docs]

    # ------------------------------------------------------------------ evidence retention holds

    async def evidence_held(self, user_id: uuid.UUID) -> bool:
        """The purge predicate: the user has a case that is not closed or is on legal hold."""
        return _held(await self.cases_of(user_id))

    async def sync_evidence(self, user_id: uuid.UUID) -> int:
        """Set ``expire_at`` of every signal and evaluation of ``user_id`` to what the purge
        predicate says now: ``None`` (kept) while held, else event time + retention interval
        (already past -> the TTL deletes it, as the next daily purge would). Returns the number
        of documents changed."""
        held = await self.evidence_held(user_id)
        changed = 0
        for coll in (SIGNALS, EVALS):
            interval = await retention_interval(coll)
            field = _TIME_FIELD[coll]
            todo: list[tuple[str, Any]] = []
            for d in await _all(self.store, coll, user_id=user_id, order_by=()):
                want = None if held else expires(d.data[field], interval)
                if d.data.get("expire_at") != want:
                    todo.append((d.id, want))
            for i in range(0, len(todo), 400):
                chunk = todo[i : i + 400]

                async def fn(tx: ScopedTransaction, chunk: list[Any] = chunk, coll: str = coll) -> None:
                    current = [(doc_id, await tx.raw_get(coll, doc_id), want) for doc_id, want in chunk]
                    for doc_id, cur, want in current:
                        if cur is not None:
                            tx.raw_set(coll, doc_id, {**cur, "expire_at": want})

                await self.store.run_transaction(fn)
            changed += len(todo)
        return changed


def repo(job: str = "security.engine") -> EngineRepo:
    return EngineRepo(ScopedStore.system(job))


async def hold_evidence(user_ids: Iterable[uuid.UUID]) -> int:
    """Call **after** a case of these users is written open (created, re-opened) or put on
    legal hold: their signals and evaluations stop expiring. Recomputed from the cases (the
    source of truth), so it is idempotent and safe to call more than needed."""
    return await _sync_many(user_ids)


async def release_evidence(user_ids: Iterable[uuid.UUID]) -> int:
    """Call **after** a case of these users is written closed or its legal hold is lifted: if
    no other open or held case remains, ``expire_at`` is restored (time + retention interval)."""
    return await _sync_many(user_ids)


async def held_subjects(
    user_ids: Iterable[uuid.UUID], case_ids: Iterable[uuid.UUID]
) -> tuple[set[uuid.UUID], set[uuid.UUID]]:
    """The two ``NOT EXISTS`` checks of ``maint.purge_expired_rows`` for security evidence:
    (users who have a case that is not closed or is on legal hold, cases among ``case_ids``
    that are not closed or are on legal hold). One query per user, one batched get for cases."""
    r = repo("security.retention")
    users: set[uuid.UUID] = set()
    for uid in dict.fromkeys(user_ids):
        if _held(await r.cases_of(uid)):
            users.add(uid)
    ids = [str(c) for c in dict.fromkeys(case_ids)]
    docs = await r.store.get_many(CASES, ids) if ids else {}
    cases = {uuid.UUID(i) for i, d in docs.items() if _held([CaseRow.of(d)])}
    return users, cases


async def _sync_many(user_ids: Iterable[uuid.UUID]) -> int:
    if not fs():
        return 0
    r = repo("security.evidence_hold")
    n = 0
    for uid in dict.fromkeys(user_ids):
        n += await r.sync_evidence(uid)
        _log("resync", uid)
    return n


# =========================================================================== store-neutral helpers
# On Postgres each helper is exactly the SQLAlchemy call it replaced.


def new(model: Any, **kw: Any) -> Any:
    """``model(**kw)``: the ORM object (Postgres) or the security row class (Firestore)."""
    if not fs():
        return model(**kw)
    return _ROWS[model][1](**kw)


async def add(session: Any, obj: Any) -> None:
    """``session.add(obj)``; Firestore: insert the row now (append-only evidence, new cases)."""
    if not fs():
        session.add(obj)
        return
    await repo().insert(obj)


async def flush(session: Any, *states: Any) -> None:
    """``await session.flush()``; Firestore: save the changed ``security_user_state`` rows (and
    flush a Postgres session of the mixed stack, which other modules may use)."""
    if not fs():
        await session.flush()
        return
    if session:
        await session.flush()
    for st in states:
        if st is not None:
            await repo().save_state_fields(st.user_id, st)


async def save(session: Any, row: Any) -> None:
    """Postgres: the change is flushed with the session (``FOR UPDATE`` row). Firestore: an
    optimistic save of a case / notice row."""
    if not fs():
        await session.flush()
        return
    await repo().save(row)


# --------------------------------------------------------------------------- other modules (public.py)


async def get_user(session: Any, user_id: uuid.UUID | None) -> Any:
    from app.modules.identity import public as idp

    return await idp.get_user(session, user_id) if user_id is not None else None


async def security_monitoring_granted(session: Any, user_id: uuid.UUID) -> bool:
    """``identity.service.current_consents`` (platform consents: no context, no organization;
    newest per purpose) for ``security_monitoring``, through ``identity.public``."""
    from app.modules.identity import public as idp

    rows = [
        c
        for c in await idp.consents_of(session, user_id)
        if c.purpose == "security_monitoring" and c.context_ref is None and c.organization_id is None
    ]
    if not rows:
        return False
    newest = max(rows, key=lambda c: (c.created_at, str(c.id)))
    return bool(newest.action == "granted")


async def primary_org(session: Any, user_id: uuid.UUID) -> uuid.UUID | None:
    from app.modules.orgs import public as op

    ids = await op.active_org_ids(session, user_id)  # sorted by id (= uuid byte order)
    return ids[0] if ids else None


async def has_staff_grant(session: Any, user_id: uuid.UUID) -> bool:
    from app.modules.rbac import public as rp

    return any(k != "student" for _g, k in await rp.live_grants(session, user_ids=[user_id]))


def window_between(v: datetime | None, since: datetime, until: datetime) -> bool:
    """SQL ``v BETWEEN since AND until`` (both inclusive; NULL is not between)."""
    return v is not None and since <= v <= until


ONE_US = timedelta(microseconds=1)


# =========================================================================== backfill: expire_at
# The backfill copies ``security_signals`` / ``risk_evaluations`` / ``security_counters`` with
# ``store_specs`` mappers that carry no ``expire_at``. These extra mappings fold one field into
# the same documents (``_combined`` merges rows of one collection by document id), computed by
# Postgres itself with the purge predicate of ``maint.purge_expired_rows`` (kept while the
# subject has a case that is not closed or is on legal hold; evaluations also while their own
# case is) and the active ``retention_policies`` interval (Postgres interval arithmetic; 180 days
# when no row is active). Counters: ``bucket_start`` + 2 days. ``verify`` then checks the field.

_HELD_SQL = (
    "EXISTS (SELECT 1 FROM security_cases sc WHERE sc.user_id = s.user_id "
    "AND (sc.status <> 'closed' OR sc.legal_hold))"
)
_INTERVAL_SQL = (
    "COALESCE((SELECT min(rp.retention_interval) FROM retention_policies rp "
    "WHERE rp.table_name = '{t}' AND rp.is_active), interval '180 days')"
)
BACKFILL_EXPIRY_SQL = {
    SIGNALS: (
        "SELECT s.id, s.occurred_at, CASE WHEN "
        + _HELD_SQL
        + " THEN NULL ELSE s.occurred_at + "
        + _INTERVAL_SQL.format(t=SIGNALS)
        + " END AS expire_at "
        "FROM security_signals s ORDER BY s.id, s.occurred_at"
    ),
    EVALS: (
        "SELECT s.id, s.evaluated_at, CASE WHEN " + _HELD_SQL + " OR EXISTS (SELECT 1 FROM "  # noqa: S608 - static SQL (module constants)
        "security_cases c2 WHERE c2.id = s.case_id AND (c2.status <> 'closed' OR c2.legal_hold)) "
        "THEN NULL ELSE s.evaluated_at + " + _INTERVAL_SQL.format(t=EVALS) + " END AS expire_at "
        "FROM risk_evaluations s ORDER BY s.id, s.evaluated_at"
    ),
    COUNTERS: (
        "SELECT counter_key, bucket_start, bucket_start + interval '2 days' AS expire_at "
        "FROM security_counters ORDER BY counter_key, bucket_start"
    ),
}


def _expiry_loader(coll: str) -> Any:
    async def load(session: Any) -> list[dict[str, Any]]:
        from sqlalchemy import text

        res = await session.execute(text(BACKFILL_EXPIRY_SQL[coll]))
        return [dict(r) for r in res.mappings().all()]

    return load


def register_backfill_expiry() -> None:
    from app.core.firestore.backfill import TableMapping, register_mapping

    ids = {
        SIGNALS: model_doc_id(m.SecuritySignal),
        EVALS: model_doc_id(m.RiskEvaluation),
        COUNTERS: model_doc_id(m.SecurityCounter),
    }
    for coll, doc_id in ids.items():
        register_mapping(
            TableMapping(
                "security",
                f"{coll}:expire_at",
                coll,
                doc_id,
                lambda r: {"expire_at": r["expire_at"]},
                loader=_expiry_loader(coll),
            )
        )


register_backfill_expiry()
