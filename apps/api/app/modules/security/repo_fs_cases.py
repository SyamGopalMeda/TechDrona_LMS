"""Security pass 1 on Firestore (cases, notes, decisions, unblock requests, review queues,
disown) -- data-ops agent. ``TD_STORE_SECURITY=firestore``.

``sx`` is a small **store-neutral statement runner** for the security tables, so the pass-1 code
keeps its SQLAlchemy statements and their exact semantics:

* Postgres (default): every call is the plain ``AsyncSession`` call it replaces
  (``sx.one_or_none(session, stmt)`` == ``(await session.execute(stmt)).scalar_one_or_none()``).
* Firestore: single-table ``select`` / ``update`` statements over a security model are evaluated
  against its collection: equality / ``IS NULL`` filters run in Firestore, every predicate is then
  re-checked in memory on the decoded row, followed by ``ORDER BY`` (``NULLS LAST`` honoured) and
  ``LIMIT``. Supported: ``== != < <= > >= IN NOT IN IS IS NOT``, ``and_`` / ``or_``, columns or
  ``count()`` / ``min()`` / ``max()`` projections. Anything else raises ``NotImplementedError``
  (joins and GROUP BY are rewritten by hand at the call site).

Rows are ``store_specs`` row classes (ORM attribute names and types). A request-scoped **unit of
work** keeps one object per document (like the ORM identity map); ``sx.flush`` writes new and
changed rows in one transaction with an optimistic ``updated_at`` check (409 ``conflict`` instead
of waiting on ``FOR UPDATE``). ``fs_unit_of_work`` (a route dependency) flushes at the end of a
successful request, as the Postgres request transaction commits.
"""

from __future__ import annotations

import contextvars
import operator as op
import uuid
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from typing import Any, cast

from sqlalchemy.sql import elements, operators
from sqlalchemy.sql.functions import FunctionElement
from sqlalchemy.sql.selectable import Join

from app.core.firestore.backend import uses_firestore
from app.core.firestore.repository import FirestoreRepository, platform_only
from app.core.firestore.store import Doc, ScopedStore, ScopedTransaction
from app.core.ids import uuid7
from app.modules.admin.fs_rows import FsRow, save_row
from app.modules.security import models as m
from app.modules.security import store_specs as sp

_PAGE = 100


def _model_map() -> dict[Any, tuple[str, Any]]:
    return {
        m.SecurityCase: ("security_cases", sp.CaseRow),
        m.CaseNote: ("case_notes", sp.CaseNoteRow),
        m.CaseDecision: ("case_decisions", sp.CaseDecisionRow),
        m.UnblockRequest: ("unblock_requests", sp.UnblockRow),
        m.AccountRestriction: ("account_restrictions", sp.RestrictionRow),
        m.RiskEvaluation: ("risk_evaluations", sp.RiskEvaluationRow),
        m.SecurityNotice: ("security_notices", sp.NoticeRow),
        m.SecuritySignal: ("security_signals", sp.SignalRow),
        m.SecurityUserState: ("security_user_state", sp.UserStateRow),
        m.SecurityIncident: ("security_incidents", sp.IncidentRow),
        m.RiskRule: ("risk_rules", sp.RiskRuleRow),
        m.RiskRuleVersion: ("risk_rule_versions", sp.RiskRuleVersionRow),
        m.SecurityBulkLift: ("security_bulk_lifts", sp.BulkLiftRow),
        m.SecurityReportExport: ("security_report_exports", sp.ReportExportRow),
    }


MODELS: dict[Any, tuple[str, Any]] = _model_map()
_BY_TABLE = {mdl.__tablename__: (mdl, coll, cls) for mdl, (coll, cls) in MODELS.items()}
_ROW_TO_COLL = {cls: coll for coll, cls in MODELS.values()}


def fs() -> bool:
    return uses_firestore("security")


# --------------------------------------------------------------------------- unit of work


@dataclass
class _Uow:
    rows: dict[tuple[str, str], FsRow] = field(default_factory=dict)
    new: set[tuple[str, str]] = field(default_factory=set)


_uow: contextvars.ContextVar[_Uow | None] = contextvars.ContextVar("td_sec_uow", default=None)


def _cur() -> _Uow:
    u = _uow.get()
    if u is None:
        u = _Uow()
        _uow.set(u)
    return u


def _doc_id_fns() -> dict[str, Any]:
    from app.modules.admin.fs_rows import model_doc_id, pk_columns

    out: dict[str, Any] = {}
    for mdl, (coll, _cls) in MODELS.items():
        pks = pk_columns(mdl)
        fn = model_doc_id(mdl)
        out[coll] = lambda row, fn=fn, pks=pks: fn({k: getattr(row, k) for k in pks})
    return out


_DOC_IDS: dict[str, Any] = _doc_id_fns()


def _key(row: Any) -> tuple[str, str]:
    """(collection, document id): the backfill's id rule (composite keys -> ``compose_id``)."""
    coll = _ROW_TO_COLL[type(row)]
    return coll, str(_DOC_IDS[coll](row))


def _track(row: Any) -> Any:
    u = _cur()
    k = _key(row)
    have = u.rows.get(k)
    if have is not None:
        return have
    u.rows[k] = row
    return row


async def fs_unit_of_work() -> AsyncIterator[None]:
    """Route dependency: a fresh identity map per request; pending rows are written when the
    endpoint returns without an exception (Postgres: the request transaction commits)."""
    if not fs():
        yield
        return
    token = _uow.set(_Uow())
    ok = False
    try:
        yield
        ok = True
    finally:
        try:
            if ok:
                await _flush_fs()
        finally:
            _uow.reset(token)


async def _flush_fs() -> None:
    u = _cur()
    todo = [(k, r) for k, r in u.rows.items() if k in u.new or r.changes()]
    if not todo:
        return
    store = _jstore("security.uow")

    async def fn(tx: ScopedTransaction) -> list[tuple[Any, Doc | None]]:
        current: dict[Any, Any] = {}
        for k, _r in todo:
            if k not in u.new:
                current[k] = await tx.get(k[0], k[1])
        out: list[tuple[Any, Doc | None]] = []
        for k, r in todo:
            if k in u.new:
                out.append((r, await tx.create(k[0], r.doc(), doc_id=k[1])))
            elif k[0] in _APPEND_ONLY_PATCHABLE:
                out.append((r, _patch_append_only(tx, k, r, current[k])))
            else:
                out.append(
                    (
                        r,
                        await save_row(tx, k[0], _target(k[0], r), current=current[k]),
                    )
                )
        return out

    for r, d in await store.run_transaction(fn):
        if d is not None:
            r.mark_saved(d.data)
    u.new.clear()


# ``security_signals`` is append-only (Postgres: only ``suppressed_by_decision_id`` may change).
# The store refuses ``update`` there, so the unit of work patches that one field with the system
# job's raw write, keeping every other field -- ``expire_at`` included -- as stored.
_APPEND_ONLY_PATCHABLE = {"security_signals": frozenset({"suppressed_by_decision_id"})}


def _patch_append_only(tx: ScopedTransaction, k: tuple[str, str], r: Any, cur: Doc | None) -> Doc:
    if cur is None:
        from app.core.errors import ProblemError

        raise ProblemError("not_found")
    ch = r.changes()
    bad = set(ch) - _APPEND_ONLY_PATCHABLE[k[0]]
    if bad:
        raise PermissionError(f"{k[0]} is append-only; cannot change {sorted(bad)}")
    from app.core.time import utcnow

    merged = {**cur.data, **ch, "updated_at": utcnow()}
    tx.raw_set(k[0], k[1], merged)
    seen = getattr(tx, "_seen", None)  # a JournalingStore transaction: record the before-image
    if seen is not None:
        seen.append((k[0], k[1], cur.data))
    return Doc(k[1], merged)


async def evidence_released(session: Any, user_ids: list[Any]) -> None:
    """Security pass 2 request: after a case of these users is written **closed**, restore the
    retention (``expire_at``) of their signals/evaluations unless another open or held case
    remains. The unit of work is written first so the recompute reads the closed case."""
    if not fs():
        return
    if isinstance(session, SecSession):
        await session.flush()
    else:
        await _flush_fs()
    from app.modules.security.repo_fs_engine import release_evidence

    await release_evidence(user_ids)


async def evidence_held(session: Any, user_ids: list[Any]) -> None:
    """Pass 2 request: after a case is created or re-opened outside ``engine.open_case``."""
    if not fs():
        return
    if isinstance(session, SecSession):
        await session.flush()
    else:
        await _flush_fs()
    from app.modules.security.repo_fs_engine import hold_evidence

    await hold_evidence(user_ids)


def _jstore(job: str) -> ScopedStore:
    """A system store whose writes join an open ``identity.fs_journal`` scope (automatic undo)."""
    from app.modules.identity.fs_journal import JournalingStore

    return JournalingStore.system(job)


def _target(coll: str, r: Any) -> Any:
    return _Pk(r) if coll == "security_user_state" else r


class _Pk:
    """``save_row`` keyed by ``user_id`` (``security_user_state`` has no ``id``)."""

    def __init__(self, row: Any) -> None:
        self._row = row

    def __getattr__(self, name: str) -> Any:
        return self._row.user_id if name == "id" else getattr(self._row, name)


# --------------------------------------------------------------------------- statement evaluation

_OPS: dict[Any, Callable[[Any, Any], bool]] = {
    operators.eq: op.eq,
    operators.ne: op.ne,
    operators.lt: op.lt,
    operators.le: op.le,
    operators.gt: op.gt,
    operators.ge: op.ge,
    operators.in_op: lambda a, b: a in b,
    operators.not_in_op: lambda a, b: a not in b,
    operators.is_: lambda a, b: a is b,
    operators.is_not: lambda a, b: a is not b,
}


_SUBQ: contextvars.ContextVar[dict[int, list[Any]] | None] = contextvars.ContextVar(
    "td_sec_subq", default=None
)


def _subselect(e: Any) -> Any:
    inner = getattr(e, "element", e)
    return inner if hasattr(inner, "get_final_froms") else None


def _value(e: Any) -> Any:
    cache = _SUBQ.get()
    if cache is not None and id(e) in cache:
        return cache[id(e)]
    if isinstance(e, elements.BindParameter):
        v = e.effective_value
        return list(v) if isinstance(v, (list, tuple, set, frozenset)) else v
    if isinstance(e, elements.Null):
        return None
    if isinstance(e, (elements.True_, elements.False_)):
        return isinstance(e, elements.True_)
    if isinstance(e, elements.Grouping):
        return _value(e.element)
    if isinstance(e, elements.ClauseList):
        return [_value(x) for x in e.clauses]
    raise NotImplementedError(f"security Firestore runner: value {type(e).__name__}")


def _pred(clause: Any) -> Callable[[Any], bool]:
    if clause is None:
        return lambda _r: True
    if isinstance(clause, elements.BooleanClauseList):
        parts = [_pred(c) for c in clause.clauses]
        if clause.operator is operators.and_:
            return lambda r: all(p(r) for p in parts)
        if clause.operator is operators.or_:
            return lambda r: any(p(r) for p in parts)
    if isinstance(clause, elements.Grouping):
        return _pred(clause.element)
    if isinstance(clause, elements.UnaryExpression) and clause.operator is operators.inv:
        inner = _pred(clause.element)
        return lambda r: not inner(r)
    if isinstance(clause, elements.BinaryExpression) and clause.operator in _OPS:
        col = clause.left
        if not isinstance(col, elements.ColumnElement) or not hasattr(col, "key"):
            raise NotImplementedError("security Firestore runner: left side must be a column")
        fn = _OPS[clause.operator]
        rhs = _value(clause.right)
        key = str(col.key)

        def _p(r: Any) -> bool:
            v = getattr(r, key)
            if clause.operator in (operators.is_, operators.is_not):
                return bool(fn(v, rhs))
            if v is None or (rhs is None and clause.operator not in (operators.in_op, operators.not_in_op)):
                return False  # SQL three-valued logic: comparisons with NULL are not true
            return bool(fn(v, rhs))

        return _p
    raise NotImplementedError(f"security Firestore runner: predicate {type(clause).__name__}")


def _pushdown(clause: Any, kinds: dict[str, str]) -> list[Any]:
    """Equality / IS NULL filters of the top-level AND that Firestore can apply."""
    from app.modules.admin.fs_rows import _enc

    parts = (
        list(clause.clauses)
        if isinstance(clause, elements.BooleanClauseList) and clause.operator is operators.and_
        else ([clause] if clause is not None else [])
    )
    out: list[Any] = []
    for c in parts:
        if (
            isinstance(c, elements.BinaryExpression)
            and c.operator in (operators.eq, operators.is_)
            and hasattr(c.left, "key")
            and c.left.key in kinds
        ):
            try:
                v = _value(c.right)
            except NotImplementedError:
                continue
            if kinds[c.left.key] in ("json", "list", "uuids"):
                continue
            out.append((c.left.key, "==", _enc(kinds[c.left.key], v)))
    return out


@dataclass
class _Plan:
    model: Any
    coll: str
    cls: Any
    where: Any
    order: list[tuple[str, bool, bool]]  # (key, desc, nulls_last)
    limit: int | None
    proj: list[Any]


def _plan(stmt: Any) -> _Plan:
    froms = stmt.get_final_froms()
    if len(froms) != 1 or getattr(froms[0], "name", None) not in _BY_TABLE:
        raise NotImplementedError("security Firestore runner: single security table only")
    model, coll, cls = _BY_TABLE[froms[0].name]
    order: list[tuple[str, bool, bool]] = []
    for o in getattr(stmt, "_order_by_clauses", ()):
        desc, nulls_last, el = False, None, o
        while isinstance(el, elements.UnaryExpression):
            if el.modifier is operators.desc_op:
                desc = True
            elif el.modifier is operators.nulls_last_op:
                nulls_last = True
            elif el.modifier is operators.nulls_first_op:
                nulls_last = False
            el = el.element
        if not hasattr(el, "key"):
            raise NotImplementedError("security Firestore runner: ORDER BY a column")
        # Postgres default: NULLS LAST for ASC, NULLS FIRST for DESC
        order.append((el.key, desc, (not desc) if nulls_last is None else nulls_last))
    limit = stmt._limit_clause.value if getattr(stmt, "_limit_clause", None) is not None else None
    proj = [d["expr"] for d in stmt.column_descriptions]
    return _Plan(model, coll, cls, stmt.whereclause, order, limit, proj)


def _sort(rows: list[Any], order: list[tuple[str, bool, bool]]) -> list[Any]:
    """SQL ``ORDER BY`` in memory: text in the VM database's collation (glibc ``en_US.utf8``,
    ``app.core.firestore.collation``), non-text in natural order, NULL placement per column
    (Postgres default: ASC NULLS LAST, DESC NULLS FIRST). Stable multi-key sort."""
    out = list(rows)
    for key, desc, nulls_last in reversed(order):
        out.sort(key=_order(key, desc, "last" if nulls_last else "first"), reverse=desc)
    return out


def _order(key: str, desc: bool, nulls: Any) -> Callable[[Any], Any]:
    from app.core.firestore.collation import order_key

    return lambda r: order_key(getattr(r, key), desc=desc, nulls=nulls)


class CasesRepo(FirestoreRepository):
    """Statement evaluation over the security collections (named system jobs; routes keep
    their permission checks, as the Postgres code ran under ``system_context``)."""

    @platform_only("security.case.read")
    async def rows(self, stmt: Any) -> list[Any]:
        p = _plan(stmt)
        kinds = p.cls.KINDS
        docs: list[Doc] = []
        cursor: str | None = None
        while True:
            page = await self.store.query(
                p.coll, filters=_pushdown(p.where, kinds), order_by=(), limit=_PAGE, cursor=cursor
            )
            docs += page.items
            if not page.next_cursor:
                break
            cursor = page.next_cursor
        keep = _pred(p.where)
        rows = [r for r in (p.cls.of(d) for d in docs) if keep(r)]
        rows = _sort(sorted(rows, key=lambda r: str(_key(r)[1])), p.order)
        if p.limit is not None:
            rows = rows[: p.limit]
        return [_track(r) for r in rows]


def _repo() -> CasesRepo:
    return CasesRepo(_jstore("security.cases"))


def _project(p: _Plan, rows: list[Any]) -> list[Any]:
    """Apply the SELECT list: an entity, columns, or count()/min()/max()."""
    if len(p.proj) == 1 and p.proj[0] is p.model:
        return rows
    out: list[Any] = []
    agg = [e for e in p.proj if isinstance(e, FunctionElement)]
    if agg:
        vals: list[Any] = []
        for e in p.proj:
            name = getattr(e, "name", "")
            args = list(e.clauses) if isinstance(e, FunctionElement) else []
            if name == "count":
                vals.append(len(rows))
            elif name in ("min", "max") and args and hasattr(args[0], "key"):
                xs = [getattr(r, str(args[0].key)) for r in rows if getattr(r, str(args[0].key)) is not None]
                vals.append((min if name == "min" else max)(xs) if xs else None)
            else:
                raise NotImplementedError(f"security Firestore runner: {name}()")
        return [tuple(vals)]
    for r in rows:
        vals = []
        for e in p.proj:
            if e is p.model:
                vals.append(r)
            elif hasattr(e, "key"):
                vals.append(getattr(r, e.key))
            else:
                raise NotImplementedError("security Firestore runner: projection")
        out.append(tuple(vals))
    return out


# --------------------------------------------------------------------------- public runner


class sx:
    @staticmethod
    async def all(session: Any, stmt: Any) -> list[Any]:
        """``(await session.execute(stmt)).scalars().all()``"""
        if not fs():
            return list((await session.execute(stmt)).scalars().all())
        p = _plan(stmt)
        return [t[0] if isinstance(t, tuple) else t for t in _project(p, await _repo().rows(stmt))]

    @staticmethod
    async def tuples(session: Any, stmt: Any) -> list[tuple[Any, ...]]:
        """``(await session.execute(stmt)).all()``"""
        if not fs():
            return [tuple(r) for r in (await session.execute(stmt)).all()]
        p = _plan(stmt)
        res = _project(p, await _repo().rows(stmt))
        return [t if isinstance(t, tuple) else (t,) for t in res]

    @staticmethod
    async def one_or_none(session: Any, stmt: Any) -> Any:
        """``(await session.execute(stmt)).scalar_one_or_none()``"""
        if not fs():
            return (await session.execute(stmt)).scalar_one_or_none()
        rows = await sx.all(session, stmt)
        if len(rows) > 1:
            from sqlalchemy.exc import MultipleResultsFound

            raise MultipleResultsFound("Multiple rows were found when one or none was required")
        return rows[0] if rows else None

    @staticmethod
    async def scalar(session: Any, stmt: Any) -> Any:
        """``(await session.execute(stmt)).scalar()`` (first column of the first row or None)."""
        if not fs():
            return (await session.execute(stmt)).scalar()
        rows = await sx.all(session, stmt)
        return rows[0] if rows else None

    @staticmethod
    async def get(session: Any, model: Any, pk: Any) -> Any:
        """``await session.get(model, pk)``"""
        if not fs():
            return await session.get(model, pk)
        if pk is None:
            return None
        coll, cls = MODELS[model]
        u = _cur()
        hit = u.rows.get((coll, str(pk)))
        if hit is not None:
            return hit
        d = await _jstore("security.cases").get(coll, str(pk))
        return _track(cls.of(d)) if d else None

    @staticmethod
    def new(model: Any, **kw: Any) -> Any:
        """``model(**kw)`` -- the ORM object (Postgres) or the row class (Firestore)."""
        if not fs():
            return model(**kw)
        _coll, cls = MODELS[model]
        if "id" in cls.KINDS and kw.get("id") is None:
            kw["id"] = uuid7()
        return cls(**kw)

    @staticmethod
    def add(session: Any, obj: Any) -> None:
        """``session.add(obj)``"""
        if not fs():
            session.add(obj)
            return
        u = _cur()
        k = _key(obj)
        u.rows[k] = obj
        u.new.add(k)

    @staticmethod
    async def flush(session: Any) -> None:
        """``await session.flush()`` -- Firestore: write pending rows now (other modules' work
        in a Postgres session is flushed too when there is one)."""
        if session:
            await session.flush()
        if fs():
            await _flush_fs()

    @staticmethod
    async def update(session: Any, stmt: Any) -> int:
        """``update(Model).where(...).values(...)`` -> rows changed."""
        if not fs():
            res = await session.execute(stmt)
            return int(getattr(res, "rowcount", 0) or 0)
        table = stmt.table
        model, _coll, _cls = _BY_TABLE[table.name]
        from sqlalchemy import select

        rows = await sx.all(session, select(model).where(stmt.whereclause))
        values = {c.key if hasattr(c, "key") else str(c): _value(v) for c, v in (stmt._values or {}).items()}
        for r in rows:
            for k, v in values.items():
                setattr(r, k, v)
        await _flush_fs()
        return len(rows)


def new_id() -> uuid.UUID:
    return uuid7()


# --------------------------------------------------------------------------- request session facade


class _Result:
    """The slice of ``sqlalchemy.Result`` the pass-1 code reads (``scalars=True``: one column)."""

    def __init__(
        self, rows: list[tuple[Any, ...]], rowcount: int | None = None, *, scalars: bool = False
    ) -> None:
        self._rows = rows
        self._scalar_mode = scalars
        self.rowcount = len(rows) if rowcount is None else rowcount

    def scalars(self) -> _Result:
        return _Result([(r[0],) for r in self._rows], self.rowcount, scalars=True)

    def all(self) -> list[Any]:
        return [r[0] for r in self._rows] if self._scalar_mode else list(self._rows)

    def __iter__(self) -> Any:
        return iter(self.all())

    def first(self) -> Any:
        rows = self.all()
        return rows[0] if rows else None

    def scalar(self) -> Any:
        return self._rows[0][0] if self._rows else None

    def scalar_one(self) -> Any:
        if len(self._rows) != 1:
            from sqlalchemy.exc import NoResultFound

            raise NoResultFound("No row was found when one was required")
        return self._rows[0][0]

    def scalar_one_or_none(self) -> Any:
        if len(self._rows) > 1:
            from sqlalchemy.exc import MultipleResultsFound

            raise MultipleResultsFound("Multiple rows were found when one or none was required")
        return self._rows[0][0] if self._rows else None

    def one(self) -> Any:
        if len(self._rows) != 1:
            from sqlalchemy.exc import NoResultFound

            raise NoResultFound("No row was found when one was required")
        return self._rows[0]

    def one_or_none(self) -> Any:
        return self._rows[0] if self._rows else None


class _Savepoint:
    """``begin_nested()`` stand-in: awaitable result and async context manager. Firestore has no
    savepoints; the request's unit of work is only written when the endpoint succeeds."""

    is_active = True

    async def __aenter__(self) -> _Savepoint:
        return self

    async def __aexit__(self, *exc: Any) -> None:
        self.is_active = False

    def __await__(self) -> Any:
        async def _self() -> _Savepoint:
            return self

        return _self().__await__()

    async def commit(self) -> None:
        self.is_active = False

    async def rollback(self) -> None:
        self.is_active = False


def _eq_value(where: Any, key: str) -> Any:
    parts = (
        list(where.clauses)
        if isinstance(where, elements.BooleanClauseList) and where.operator is operators.and_
        else [where]
    )
    for c in parts:
        if (
            isinstance(c, elements.BinaryExpression)
            and c.operator is operators.eq
            and getattr(c.left, "key", None) == key
        ):
            return _value(c.right)
    return None


class SecSession:
    """Stand-in for the request ``AsyncSession`` on ``TD_STORE_SECURITY=firestore``.

    Security tables go to the Firestore runner above; the other modules' tables the pass-1 code
    touches go to their ``public.py`` (identity, sessions, rbac); the RLS GUC statements of
    ``system_context`` are no-ops (named system jobs replace RLS); ``core.outbox`` inserts go to the
    Firestore outbox. Anything else raises (a statement that still needs a hand port). Falsy, like
    ``NO_POSTGRES``, so the no-Postgres helpers (``pg_system``, ``emit_any``, ``idem_session``)
    take their Firestore branch."""

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self._orm_new: list[tuple[Any, Any]] = []
        # Other modules' rows read through their public API: (object, snapshot). Changes made by
        # the security code are written back through the owner's public save at commit.
        self._foreign: dict[int, tuple[Any, dict[str, Any]]] = {}

    def _seen(self, obj: Any) -> Any:
        if obj is not None and hasattr(obj, "__table__") and id(obj) not in self._foreign:
            cols = obj.__table__.columns.keys()
            self._foreign[id(obj)] = (obj, {k: getattr(obj, k, None) for k in cols})
        return obj

    async def _save_foreign(self) -> None:
        for obj, snap in list(self._foreign.values()):
            changed = {k: getattr(obj, k, None) for k in snap if getattr(obj, k, None) != snap[k]}
            if not changed:
                continue
            name = type(obj).__name__
            if name == "ApprovalRequest":
                from app.modules.rbac import public as rbp

                await rbp.save_approval(self._inner, obj)
            elif name == "User":
                from app.modules.identity import public as idp

                await idp.save_user(self._inner, obj)
            elif name == "UserProfile":
                from app.modules.identity import public as idp

                await idp.save_profile(self._inner, obj)
            elif name == "UserCredential":
                from app.modules.identity import public as idp

                await idp.save_credential(self._inner, obj)
            elif name == "AuthSession":
                from app.modules.sessions import public as spub

                await spub.update_session(self._inner, obj.id, **changed)
            elif name == "UserDevice":
                from app.modules.sessions import public as spub

                await spub.add_user_device(self._inner, obj)
            else:
                raise NotImplementedError(f"security Firestore session: write back {name}")
            self._foreign[id(obj)] = (obj, {k: getattr(obj, k, None) for k in snap})

    def __bool__(self) -> bool:
        return False

    # ---------------------------------------------------------------- reads

    async def get(self, model: Any, pk: Any, **_kw: Any) -> Any:
        if model in MODELS:
            return await sx.get(None, model, pk)
        name = model.__name__
        if name == "User":
            from app.modules.identity import public as idp

            return self._seen(await idp.get_user(self._inner, pk))
        if name == "UserProfile":
            from app.modules.identity import public as idp

            return self._seen(await idp.get_profile(self._inner, pk))
        if name == "UserCredential":
            from app.modules.identity import public as idp

            return self._seen(await idp.get_credential(self._inner, pk))
        if name == "Device":
            from app.modules.sessions import public as spub

            return self._seen(await spub.get_device(self._inner, pk))
        if name == "AuthSession":
            from app.modules.sessions import public as spub

            return self._seen(await spub.get_session(self._inner, pk))
        if name == "LoginAttempt":
            from app.modules.sessions import public as spub

            return self._seen(await spub.get_login_attempt(self._inner, pk))
        if name == "ApprovalRequest":
            from app.modules.rbac import public as rbp

            return self._seen(await rbp.get_approval(self._inner, pk))
        if name == "RoleGrant":
            from app.modules.rbac import public as rbp

            return self._seen(await rbp.get_grant(self._inner, pk))
        raise NotImplementedError(f"security Firestore session: get({name})")

    async def _resolve_subqueries(self, clause: Any) -> None:
        """``col IN (SELECT ...)``: run the sub-select first (same facade) and remember its values."""
        if clause is None:
            return
        if isinstance(clause, (elements.BooleanClauseList, elements.ClauseList)):
            for c in clause.clauses:
                await self._resolve_subqueries(c)
            return
        if isinstance(clause, elements.Grouping):
            await self._resolve_subqueries(clause.element)
            return
        if isinstance(clause, elements.BinaryExpression):
            sub = _subselect(clause.right)
            if sub is not None:
                cache = _SUBQ.get()
                if cache is None:
                    cache = {}
                    _SUBQ.set(cache)
                res = await self.execute(sub)
                cache[id(clause.right)] = [r[0] for r in res._rows]

    async def execute(self, stmt: Any, params: Any = None, **_kw: Any) -> _Result:
        from sqlalchemy.sql.dml import Insert, Update

        await self._resolve_subqueries(getattr(stmt, "whereclause", None))

        if isinstance(stmt, elements.TextClause):
            sql = str(stmt)
            if "current_setting(" in sql:
                # Security code runs these paths under ``system_context`` on Postgres: answer the
                # GUC reads as platform scope (``app.is_platform = on``), everything else empty.
                args = sql.split("current_setting(")[1:]
                return _Result([tuple("on" if "app.is_platform" in a else "" for a in args)])
            if "set_config(" in sql:
                return _Result([("",) * sql.count("set_config(")])
            raise NotImplementedError("security Firestore session: raw SQL needs a hand port")
        if isinstance(stmt, Insert):
            if stmt.table.name == "security_counters":
                vals = {str(getattr(c, "key", c)): _value(v) for c, v in (stmt._values or {}).items()}
                await counter_bump(vals["counter_key"], vals["bucket_start"], int(vals.get("count") or 1))
                return _Result([], 1)
            if stmt.table.name == "outbox_events":
                # Through core.outbox with no Postgres session: buffered to the request (or
                # detector) commit point and dropped on failure -- never relayed before a rollback.
                from app.core.outbox import emit_event

                vals = {str(getattr(c, "key", c)): _value(v) for c, v in (stmt._values or {}).items()}
                await emit_event(
                    cast(Any, None),
                    vals["event_type"],
                    vals["payload"],
                    aggregate_type=vals["aggregate_type"],
                    aggregate_id=vals["aggregate_id"],
                    organization_id=vals.get("organization_id"),
                )
                return _Result([], 1)
            raise NotImplementedError(f"security Firestore session: insert into {stmt.table.name}")
        if isinstance(stmt, Update):
            name = getattr(stmt.table, "name", "")
            if name in _BY_TABLE:
                return _Result([], await sx.update(None, stmt))
            if name == "users":
                from app.modules.identity import public as idp

                uid = _eq_value(stmt.whereclause, "id")
                if uid is None:
                    raise NotImplementedError("security Firestore session: update(User) needs User.id ==")
                vals = {
                    c.key if hasattr(c, "key") else str(c): _value(v) for c, v in (stmt._values or {}).items()
                }
                await idp.update_user(self._inner, uid, **vals)
                return _Result([], 1)
            raise NotImplementedError(f"security Firestore session: update {name}")
        froms = stmt.get_final_froms()
        if len(froms) == 1 and getattr(froms[0], "name", None) == "security_counters":
            key = _eq_value(stmt.whereclause, "counter_key")
            since = None
            for c in getattr(stmt.whereclause, "clauses", [stmt.whereclause]):
                if (
                    getattr(getattr(c, "left", None), "key", None) == "bucket_start"
                    and c.operator is operators.ge
                ):
                    since = _value(c.right)
            if key is None or since is None:
                raise NotImplementedError("security Firestore session: counter query shape")
            return _Result([(await counter_sum(key, since),)])
        if len(froms) == 1 and isinstance(froms[0], Join):
            return await self._join_select(stmt, froms[0])
        if getattr(stmt, "_group_by_clauses", ()):
            return await self._group_select(stmt)
        if len(froms) == 1 and getattr(froms[0], "name", None) in _BY_TABLE:
            p = _plan(stmt)
            res = _project(p, await _repo().rows(stmt))
            return _Result([t if isinstance(t, tuple) else (t,) for t in res])
        if len(froms) == 1:
            return await self._foreign_select(stmt, froms[0].name)
        raise NotImplementedError("security Firestore session: joins need a hand port")

    async def _join_select(self, stmt: Any, join: Any) -> _Result:
        """``select(A[, B | B.col]).join(B, B.id == A.fk)`` between two security tables: A rows by
        the WHERE (on A's columns) and ORDER BY, then B fetched by id (inner join: rows without
        a B are dropped, as in SQL)."""
        from sqlalchemy import select as sa_select

        left, right = join.left, join.right
        if left.name not in _BY_TABLE or right.name not in _BY_TABLE or join.isouter:
            raise NotImplementedError("security Firestore session: join shape")
        a_model, b_model = _BY_TABLE[left.name][0], _BY_TABLE[right.name][0]
        on = join.onclause
        if not (isinstance(on, elements.BinaryExpression) and on.operator is operators.eq):
            raise NotImplementedError("security Firestore session: join condition")
        cols = {on.left.table.name: on.left.key, on.right.table.name: on.right.key}
        if cols.get(right.name) != "id":
            raise NotImplementedError("security Firestore session: join must be on B.id")
        fk = str(cols[left.name])
        q = sa_select(a_model)
        if stmt.whereclause is not None:
            q = q.where(stmt.whereclause)
        if getattr(stmt, "_order_by_clauses", ()):
            q = q.order_by(*stmt._order_by_clauses)
        if getattr(stmt, "_limit_clause", None) is not None:
            q = q.limit(stmt._limit_clause.value)
        out: list[tuple[Any, ...]] = []
        for a in await sx.all(None, q):
            b = await sx.get(None, b_model, getattr(a, fk))
            if b is None:
                continue
            vals: list[Any] = []
            for d in stmt.column_descriptions:
                e = d["expr"]
                if e is a_model:
                    vals.append(a)
                elif e is b_model:
                    vals.append(b)
                elif getattr(getattr(getattr(e, "expression", e), "table", None), "name", None) == right.name:
                    vals.append(getattr(b, str(e.key)))
                else:
                    vals.append(getattr(a, str(e.key)))
            out.append(tuple(vals))
        return _Result(out)

    async def _group_select(self, stmt: Any) -> _Result:
        """``select(Model.col, func.count()).where(...).group_by(Model.col)`` on a security table."""
        from sqlalchemy import select as sa_select

        groups = list(stmt._group_by_clauses)
        froms = stmt.get_final_froms()
        if len(groups) != 1 or len(froms) != 1 or froms[0].name not in _BY_TABLE:
            raise NotImplementedError("security Firestore session: GROUP BY shape")
        model = _BY_TABLE[froms[0].name][0]
        key = str(groups[0].key)
        q = sa_select(model)
        if stmt.whereclause is not None:
            q = q.where(stmt.whereclause)
        counts: dict[Any, list[Any]] = {}
        for r in await sx.all(None, q):
            counts.setdefault(getattr(r, key), []).append(r)
        out: list[tuple[Any, ...]] = []
        for k, rs in counts.items():
            vals: list[Any] = []
            for d in stmt.column_descriptions:
                e = d["expr"]
                if isinstance(e, FunctionElement) and getattr(e, "name", "") == "count":
                    vals.append(len(rs))
                elif getattr(e, "key", None) == key:
                    vals.append(k)
                else:
                    raise NotImplementedError("security Firestore session: GROUP BY projection")
            out.append(tuple(vals))
        return _Result(out)

    async def _foreign_select(self, stmt: Any, table: str) -> _Result:
        """Other modules' tables: candidate rows from their ``public.py``, then the same
        predicate / order / limit evaluation."""
        where = stmt.whereclause
        rows: list[Any]
        if table == "user_devices":
            from app.modules.sessions import public as spub

            rows = list(await spub.list_user_devices(self._inner, user_id=_eq_value(where, "user_id")))
        elif table == "login_attempts":
            from app.modules.sessions import public as spub

            la = await spub.get_login_attempt(self._inner, _eq_value(where, "id"))
            rows = [la] if la is not None else []
        elif table == "auth_sessions":
            from app.modules.sessions import public as spub

            rows = list(await spub.list_sessions(self._inner, user_id=_eq_value(where, "user_id")))
        elif table == "users":
            from app.modules.identity import public as idp

            u = await idp.get_user(self._inner, _eq_value(where, "id"))
            rows = [u] if u is not None else []
        elif table == "approval_requests":
            from app.modules.rbac import public as rbp

            rid = _eq_value(where, "id")
            if rid is not None:
                a = await rbp.get_approval(self._inner, rid)
                rows = [a] if a is not None else []
            else:
                rows = list(
                    await rbp.find_approvals(
                        self._inner,
                        target_type=_eq_value(where, "target_type"),
                        target_id=_eq_value(where, "target_id"),
                        action_type=_eq_value(where, "action_type"),
                    )
                )
        else:
            raise NotImplementedError(f"security Firestore session: select from {table}")
        keep = _pred(where)
        rows = [self._seen(r) for r in rows if keep(r)]
        p = _foreign_plan(stmt)
        rows = _sort(rows, p.order)
        if p.limit is not None:
            rows = rows[: p.limit]
        out: list[tuple[Any, ...]] = []
        for r in rows:
            vals = []
            for e in p.proj:
                vals.append(getattr(r, str(e.key)) if hasattr(e, "key") and not isinstance(e, type) else r)
            out.append(tuple(vals))
        if p.proj and isinstance(p.proj[0], FunctionElement):
            return _Result([(len(rows),)])
        return _Result(out)

    # ---------------------------------------------------------------- writes

    def add(self, obj: Any) -> None:
        if type(obj) in MODELS:
            _coll, cls = MODELS[type(obj)]
            row = cls(**{k: getattr(obj, k, None) for k in cls.KINDS})
            for k, v in cls.DEFAULTS.items():  # server defaults, visible on the ORM object too
                if getattr(row, k) is None:
                    setattr(row, k, v)
                    setattr(obj, k, v)
            if getattr(row, "id", None) is None and "id" in cls.KINDS:
                row.id = obj.id = uuid7()
            sx.add(None, row)
            self._orm_new.append((obj, row))
            return
        if isinstance(obj, FsRow):
            sx.add(None, obj)
            return
        raise NotImplementedError(f"security Firestore session: add({type(obj).__name__})")

    def _sync(self) -> None:
        for obj, row in self._orm_new:
            for k in row.KINDS:
                v = getattr(obj, k, None)
                if v is not None or getattr(row, k) is None:
                    setattr(row, k, v)

    async def flush(self, *_a: Any) -> None:
        self._sync()
        await _flush_fs()
        await self._save_foreign()

    async def refresh(self, obj: Any, *_a: Any, **_k: Any) -> None:
        return None

    def begin_nested(self) -> _Savepoint:
        return _Savepoint()

    def in_transaction(self) -> bool:
        return True

    async def commit_fs(self) -> None:
        self._sync()
        await _flush_fs()
        await self._save_foreign()


def _foreign_plan(stmt: Any) -> _Plan:
    order: list[tuple[str, bool, bool]] = []
    for o in getattr(stmt, "_order_by_clauses", ()):
        desc, el = False, o
        while isinstance(el, elements.UnaryExpression):
            desc = desc or el.modifier is operators.desc_op
            el = el.element
        order.append((str(el.key), desc, not desc))
    limit = stmt._limit_clause.value if getattr(stmt, "_limit_clause", None) is not None else None
    return _Plan(
        None, "", None, stmt.whereclause, order, limit, [d["expr"] for d in stmt.column_descriptions]
    )


def sec_route(fn: Callable[..., Any]) -> Callable[..., Any]:
    """Route decorator (pass 1): on ``TD_STORE_SECURITY=firestore`` the endpoint gets a
    ``SecSession`` instead of the Postgres session and a fresh unit of work, written when the
    endpoint returns (the Postgres transaction commit). Postgres: the endpoint, unchanged."""
    import functools

    @functools.wraps(fn)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        if not fs() or "session" not in kwargs:
            return await fn(*args, **kwargs)
        sess = SecSession(kwargs["session"])
        kwargs["session"] = sess
        token = _uow.set(_Uow())
        try:
            result = await fn(*args, **kwargs)
            await sess.commit_fs()
            return result
        finally:
            _uow.reset(token)

    return wrapper


def wrap_session(session: Any) -> Any:
    """For jobs and cross-module callers: the ``SecSession`` on Firestore, else ``session``."""
    return SecSession(session) if fs() and not isinstance(session, SecSession) else session


# --------------------------------------------------------------------------- rate counters
# ``security_counters`` (Postgres: ``INSERT ... ON CONFLICT DO UPDATE count + 1`` per 1-minute
# bucket; ``SUM(count)`` since a time). Firestore: one document per (key, bucket), incremented in a
# transaction; the sum reads the key's buckets (a handful: keys are per user and short-lived).


def _counter_id(key: str, bucket: Any) -> str:
    from app.core.firestore.ids import compose_id

    return compose_id(key, bucket.isoformat())


async def counter_bump(key: str, bucket: Any, n: int = 1) -> None:
    store = _jstore("security.counters")
    doc_id = _counter_id(key, bucket)

    async def fn(tx: ScopedTransaction) -> None:
        cur = await tx.get("security_counters", doc_id)
        count = int(cur["count"]) + n if cur else n
        await tx.put(
            "security_counters",
            doc_id,
            {
                "counter_key": key,
                "bucket_start": bucket,
                "count": count,
                **({"created_at": cur["created_at"]} if cur and cur.get("created_at") else {}),
            },
        )

    await store.run_transaction(fn)


async def counter_sum(key: str, since: Any) -> int:
    store = _jstore("security.counters")
    page = await store.query(
        "security_counters", filters=(("counter_key", "==", key),), order_by=(), limit=100
    )
    return sum(int(d["count"]) for d in page.items if d["bucket_start"] >= since)


def track_foreign(session: Any, obj: Any) -> Any:
    """A row of another module fetched through its ``public.py`` inside a ``SecSession`` request:
    remember it so changes the security code makes are written back through the owner's
    ``public.py`` at commit (Postgres: the ORM row already is in the caller's session)."""
    if isinstance(session, SecSession) and obj is not None:
        session._seen(obj)
    return obj
