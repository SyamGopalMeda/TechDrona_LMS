"""Security pass 3 on Firestore (``TD_STORE_SECURITY=firestore``): controls (engine state, kill
switch, rule versions with shadow and activation, bulk lifts, report exports), ``reports.py``,
the rest of ``api_engine.py``, ``tasks.py`` and ``retention.py``.

These files keep their SQL. Statements over security tables run on the shared SQL-on-Firestore
engine (``app/core/firestore/sqlstore.py``: interpreter incl. joins, GROUP BY, ``IN (subquery)``,
unit of work committed with the request, optimistic locks for ``FOR UPDATE``), on the
**same documents** the other security repositories use: the engine is given the
``admin.fs_rows`` codec of ``security.store_specs`` (UUID text, timestamps, JSON text, hex bytes,
``compose_id`` keys) and does not re-register the collections.

RLS (Postgres comments in the security migrations): ``O`` tables -> ``owner`` on ``user_id``
(platform sees all); ``NONE`` tables -> ``open`` (the routes check permissions, as on Postgres).
Notes and decisions are append-only. Reads of other modules (approvals, sessions, devices, login
attempts, users) go through their ``public.py`` instead of SQL.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from app.core.firestore.sqlstore import Savepoint, SqlModuleSpec, SqlStore
from app.modules.admin import fs_rows
from app.modules.security import models as m
from app.modules.security import store_specs as ss

ROWS: dict[type[Any], type[fs_rows.FsRow]] = {
    m.SecuritySignal: ss.SignalRow,
    m.RiskEvaluation: ss.RiskEvaluationRow,
    m.RiskRule: ss.RiskRuleRow,
    m.RiskRuleVersion: ss.RiskRuleVersionRow,
    m.SecurityCounter: ss.CounterRow,
    m.SecurityUserState: ss.UserStateRow,
    m.AccountRestriction: ss.RestrictionRow,
    m.SecurityCase: ss.CaseRow,
    m.CaseNote: ss.CaseNoteRow,
    m.CaseDecision: ss.CaseDecisionRow,
    m.SecurityIncident: ss.IncidentRow,
    m.SecurityNotice: ss.NoticeRow,
    m.SecurityBulkLift: ss.BulkLiftRow,
    m.SecurityReportExport: ss.ReportExportRow,
    m.UnblockRequest: ss.UnblockRow,
}

RLS = {
    "security_signals": "owner",
    "risk_evaluations": "owner",
    "security_cases": "owner",
    "account_restrictions": "owner",
    "unblock_requests": "owner",
    "security_user_state": "owner",
    "security_notices": "owner",
    "risk_rules": "open",
    "risk_rule_versions": "open",
    "case_notes": "open",
    "case_decisions": "open",
    "security_incidents": "open",
    "security_counters": "open",
    "security_report_exports": "open",
    "security_bulk_lifts": "open",
}


def _values(model: type[Any], values: Any) -> dict[str, Any]:
    if isinstance(values, dict):
        return values
    return {k: getattr(values, k, None) for k in ROWS[model].KINDS}


def encode(model: type[Any], values: Any) -> dict[str, Any]:
    return ROWS[model].from_pg(_values(model, values)).doc()


def decode(model: type[Any], data: dict[str, Any]) -> Any:
    row = ROWS[model].of(data)
    return model(**{k: getattr(row, k) for k in ROWS[model].KINDS})


def doc_id_of(model: type[Any], values: Any) -> str:
    return str(fs_rows.model_doc_id(model)(_values(model, values)))


def _k(*parts: Any) -> str:
    return "|".join("" if p is None else str(p) for p in parts)


SPEC = SqlModuleSpec(
    module="security",
    models=tuple(ROWS),
    rls=RLS,
    uniques={
        "risk_rules": [("rule_key", lambda r: r.key)],
    },
    append_only=frozenset({"case_notes", "case_decisions"}),
    encode=encode,
    decode=decode,
    doc_id_of=doc_id_of,
    register_collections=False,
    job="security.controls",
)
STORE = SqlStore(SPEC)


def _join_access_journal() -> None:
    """Approval decisions (``rbac.public.decision``) and journaled routes run in the access undo
    journal (``identity.fs_journal``); engine commits made inside a scope register their undo."""
    from app.core.firestore.sqlstore import register_journal
    from app.modules.identity import fs_journal

    register_journal(fs_journal.current, fs_journal.on_rollback)


_join_access_journal()


def journaled_executor(job: str) -> Any:
    """``sqlstore.journaled_executor`` for the security store (approval executors)."""
    from app.core.firestore.sqlstore import journaled_executor as _je

    return _je(STORE, job)


def on_firestore() -> bool:
    return STORE.on_firestore()


async def execute(session: Any, stmt: Any, params: Any = None) -> Any:
    return await STORE.execute(session, stmt, params)


def add(session: Any, obj: Any) -> None:
    STORE.add(session, obj)


async def flush(session: Any) -> None:
    await STORE.flush(session)


async def refresh(session: Any, obj: Any) -> None:
    await STORE.refresh(session, obj)


async def get(session: Any, model: type[Any], ident: Any, *, with_for_update: bool = False) -> Any:
    return await STORE.get(session, model, ident, with_for_update=with_for_update)


async def persist_row(session: Any, model: type[Any], row: Any) -> Any:
    """Make a row read through another security repository (e.g. ``engine.rule_version`` on
    Firestore returns its own row object) part of this transaction: on Firestore the stored row is
    loaded ``FOR UPDATE`` into the unit of work and the attributes of ``row`` are copied onto it,
    so the change commits with the request (version-checked). Postgres: the ORM row is already in
    the session; returned unchanged."""
    if not on_firestore() or (isinstance(row, model) and STORE.uow(session).entry_of(row) is not None):
        return row
    pk = tuple(getattr(row, col.key) for col in model.__table__.primary_key.columns)
    cur = await get(session, model, pk if len(pk) > 1 else pk[0], with_for_update=True)
    if cur is None:
        return row
    for k in ROWS[model].KINDS:
        setattr(cur, k, getattr(row, k))
    return cur


def after_commit(session: Any, cb: Any) -> None:
    """``sqlstore.after_commit`` on Firestore; nothing on Postgres (callers' follow-ups there are
    no-ops, e.g. ``repo_fs_engine.release_evidence``)."""
    if on_firestore():
        from app.core.firestore.sqlstore import after_commit as _after

        _after(session, cb)


async def begin_nested(session: Any) -> Savepoint:
    return await STORE.begin_nested(session)


# =========================================================================== retention (maint.*)

ATTACHMENT_AGE_DAYS = 90
DISPUTED_AGE_YEARS = 3  # Postgres ``interval '3 years'`` (36 months)


def _three_years() -> Any:
    from app.modules.admin.public import PgInterval

    return PgInterval(months=12 * DISPUTED_AGE_YEARS)


def minus_years(ts: datetime, years: int) -> datetime:
    """``ts - interval 'N years'`` with Postgres semantics (``admin.public.subtract_interval``:
    months first, the day clamped to the month end, e.g. ``2028-02-29 - 3 years = 2025-02-28``)."""
    from app.modules.admin.public import PgInterval, subtract_interval

    return subtract_interval(ts.astimezone(UTC), PgInterval(months=12 * years))


def disputed_cutoff(now: datetime, interval: Any) -> datetime:
    """``now() - GREATEST(v_interval, interval '3 years')`` of ``maint.purge_closed_cases``.

    ``interval`` is the policy's ``PgInterval`` (a ``timedelta`` is accepted and converted).
    ``GREATEST`` ranks intervals with ``interval_cmp`` (a month counts as 30 days, so '3 years'
    ranks as 1080 days) and on a tie keeps its **first** argument (``v_interval``); the winner is
    then subtracted with its own months/days/time (``subtract_interval``)."""
    from app.modules.admin.public import PgInterval, subtract_interval

    iv = PgInterval.coerce(interval)
    assert iv is not None
    three = _three_years()
    winner = iv if iv >= three else three
    return subtract_interval(now, winner)


OPEN_UR = ("draft", "submitted", "under_review", "info_requested", "escalated")


async def maintenance_runner(sql: str, params: dict[str, Any]) -> list[dict[str, Any]] | None:
    """The ``maint.*`` retention functions of ``support_0003`` on a Firestore security store, with
    the same rows and side effects (a ``retention.Runner``):

    * ``maint.closed_case_attachments(n)``: ``(source, row_id, s3_key)`` per attachment of unblock
      requests / case notes of cases closed more than 90 days ago and not on legal hold;
    * ``maint.clear_closed_case_attachments(source, ids)``: ``[{"n": rows}]``;
    * ``maint.purge_closed_cases(batch)``: ``(table_name, rows_deleted)`` per table.

    Each call is one transaction (``store_session``), audited like the SQL functions."""
    from app.core.db import system_context
    from app.core.firestore.sqlstore import store_session

    async with store_session() as session:
        await system_context(session, "security_purge_closed_cases")
        if "maint.closed_case_attachments" in sql:
            return await _closed_case_attachments(session, int(params["n"]))
        if "maint.clear_closed_case_attachments" in sql:
            n = await _clear_attachments(session, str(params["s"]), [_uuid(x) for x in params["ids"]])
            return [{"n": n}]
        if "maint.purge_closed_cases" in sql:
            from app.modules.admin import public as admin_public

            # A Firestore-only stack has no migrations: seed the support_0003 policy rows
            # (security_cases '1 year' ...) if missing, never changing existing ones. Without
            # them the purge raised "security_cases has no active retention policy".
            await admin_public.ensure_retention_defaults(session)
            return await _purge_closed_cases(session, int(params["b"]))
    raise ValueError(f"no Firestore implementation for {sql!r}")


def _uuid(v: Any) -> Any:
    import uuid

    return v if isinstance(v, uuid.UUID) else uuid.UUID(str(v))


async def _rows(session: Any, model: type[Any], *where: Any) -> list[Any]:
    from sqlalchemy import select

    return list((await execute(session, select(model).where(*where))).scalars())


async def _eligible_attachment_cases(session: Any) -> dict[Any, Any]:

    from app.modules.identity import clock

    cut = clock.now() - timedelta(days=ATTACHMENT_AGE_DAYS)
    rows = await _rows(
        session,
        m.SecurityCase,
        m.SecurityCase.status == "closed",
        m.SecurityCase.legal_hold.is_(False),
        m.SecurityCase.closed_at < cut,
    )
    return {c.id: c for c in rows}


async def _closed_case_attachments(session: Any, limit: int) -> list[dict[str, Any]]:
    if limit < 1:
        raise ValueError("maint.closed_case_attachments: limit must be positive")
    cases = await _eligible_attachment_cases(session)
    out: list[dict[str, Any]] = []
    if not cases:
        return out
    for src, model in (("unblock_requests", m.UnblockRequest), ("case_notes", m.CaseNote)):
        rows = [r for r in await _rows(session, model, model.case_id.in_(list(cases))) if r.attachments]
        rows.sort(key=lambda r: cases[r.case_id].closed_at)
        for r in rows[:limit]:
            for a in r.attachments:
                out.append({"source": src, "row_id": r.id, "s3_key": (a or {}).get("s3_key")})
    return out


async def _clear_attachments(session: Any, source: str, ids: list[Any]) -> int:
    from app.core.audit import AuditActor, audit

    model = {"unblock_requests": m.UnblockRequest, "case_notes": m.CaseNote}.get(source)
    if model is None:
        raise ValueError(f"maint.clear_closed_case_attachments: unknown source {source}")
    cases = await _eligible_attachment_cases(session)
    n = 0
    for r in await _rows(session, model, model.id.in_(ids)):  # type: ignore[attr-defined]
        if r.case_id in cases and r.attachments:
            r.attachments = []
            n += 1
    if n > 0:
        await audit(
            session,
            AuditActor.system("security.purge_closed_cases"),
            "security.case_attachments.purged",
            source,
            None,
            after={"rows": n},
        )
    return n


async def _purge_closed_cases(session: Any, batch: int) -> list[dict[str, Any]]:

    from app.core.audit import AuditActor, audit
    from app.modules.admin import public as admin_public
    from app.modules.identity import clock
    from app.modules.support import public as support_public

    if batch < 1:
        raise ValueError("maint.purge_closed_cases: batch must be positive")
    interval = await admin_public.retention_interval(session, "security_cases")
    if interval is None:
        raise ValueError("maint.purge_closed_cases: security_cases has no active retention policy")
    now = clock.now()
    closed = await _rows(
        session,
        m.SecurityCase,
        m.SecurityCase.status == "closed",
        m.SecurityCase.closed_at.is_not(None),
        m.SecurityCase.legal_hold.is_(False),
    )
    closed.sort(key=lambda c: c.closed_at)
    ids = [c.id for c in closed]
    urs = await _rows(session, m.UnblockRequest, m.UnblockRequest.case_id.in_(ids)) if ids else []
    rs = await _rows(session, m.AccountRestriction, m.AccountRestriction.case_id.in_(ids)) if ids else []
    notes = await _rows(session, m.CaseNote, m.CaseNote.case_id.in_(ids)) if ids else []
    decs = await _rows(session, m.CaseDecision, m.CaseDecision.case_id.in_(ids)) if ids else []
    referenced = await _policy_referenced_decisions(session, {d.id for d in decs})
    disputed_before = disputed_cutoff(now, interval)
    plain_before = admin_public.subtract_interval(now, interval)
    chosen: list[Any] = []
    for c in closed:
        mine = [u for u in urs if u.case_id == c.id]
        disputed = any(u.is_second_level_appeal or u.appeal_used for u in mine)
        if not c.closed_at < (disputed_before if disputed else plain_before):
            continue
        if any(r.case_id == c.id and r.ended_at is None for r in rs):
            continue
        if any(u.state in OPEN_UR or u.attachments for u in mine):
            continue
        if any(n.case_id == c.id and n.attachments for n in notes):
            continue
        if any(d.case_id == c.id and d.id in referenced for d in decs):
            continue
        chosen.append(c.id)
        if len(chosen) >= batch:
            break
    gone = set(chosen)
    requests = {u.id for u in urs if u.case_id in gone}
    decisions = {d.id for d in decs if d.case_id in gone}
    # Detach references that outlive the case (support tickets: 3 years, privacy D13).
    await support_public.detach_security_refs(session, gone, requests)
    if decisions:
        for r in await _rows(
            session, m.AccountRestriction, m.AccountRestriction.decision_id.in_(list(decisions))
        ):
            r.decision_id = None
    restriction_ids = [r.id for r in rs if r.case_id in gone]
    if restriction_ids:
        for u in await _rows(session, m.UnblockRequest, m.UnblockRequest.restriction_id.in_(restriction_ids)):
            if u.case_id not in gone:
                u.restriction_id = None
    out: list[dict[str, Any]] = []
    summary: dict[str, int] = {}
    uow, sc = STORE.uow(session), await STORE.scope(session)
    for table, model in (
        ("case_notes", m.CaseNote),
        ("case_decisions", m.CaseDecision),
        ("unblock_requests", m.UnblockRequest),
        ("account_restrictions", m.AccountRestriction),
        ("security_cases", m.SecurityCase),
    ):
        col = model.id if table == "security_cases" else model.case_id  # type: ignore[union-attr]
        rows = await _rows(session, model, col.in_(list(gone))) if gone else []
        for row in rows:
            uow.delete(row, sc)
        out.append({"table_name": table, "rows_deleted": len(rows)})
        summary[table] = len(rows)
    await audit(
        session,
        AuditActor.system("security.purge_closed_cases"),
        "security.closed_cases.purged",
        "security_case",
        None,
        after=summary,
    )
    return out


async def _policy_referenced_decisions(session: Any, decision_ids: set[Any]) -> set[Any]:
    """Decisions referenced by ``policy_settings.case_decision_id`` (the SQL ``NOT EXISTS`` over
    ``policy_settings JOIN case_decisions``), through the admin module's public API."""
    if not decision_ids:
        return set()
    from app.modules.admin import public as admin_public

    return set(await admin_public.policy_case_decision_ids(session, decision_ids))
