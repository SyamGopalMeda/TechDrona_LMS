"""Retention parity on Firestore (agent retention-fs; docs/firebase/agents/retention-fs.md).

``td.core.maint_retention`` / ``security.purge_closed_cases`` on a stack with no Postgres delete
exactly what ``maint.run_retention`` / ``maint.purge_closed_cases`` delete on the VM: rows inside the
window stay, rows outside go, held evidence and FK-referenced sessions stay, admin-edited
intervals apply, the TTL stamps never fire before the SQL predicate, and every run is audited.

Emulator: ``TD_TEST_NO_PG=1 TD_TEST_DB_NAME=retention_fs``.
"""

from __future__ import annotations

import importlib.util
import json
import re
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from app.core.ids import uuid7
from tests.audit.fs.support import fs_env  # noqa: F401

FS_MODULES = (
    "admin",
    "assessments",
    "audit",
    "core",
    "identity",
    "media",
    "notifications",
    "rbac",
    "security",
    "sessions",
    "support",
)
API = Path(__file__).resolve().parents[2]
D = timedelta(days=1)


@pytest.fixture
def no_pg(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core import runtime

    monkeypatch.setattr(runtime, "postgres_enabled", lambda: False)  # the Firebase stack


def _now() -> datetime:
    n = datetime.now(UTC)
    return n.replace(microsecond=0)


def _st() -> Any:
    from app.core.firestore.store import ScopedStore

    return ScopedStore.system("test.retention")


async def _put(coll: str, docs: dict[str, dict[str, Any]]) -> None:
    await _st().import_documents(coll, list(docs.items()))


async def _ids(coll: str) -> set[str]:
    return {d.id for d in await _st().scan(coll)}


async def _doc(coll: str, doc_id: str) -> dict[str, Any] | None:
    d = await _st().get(coll, doc_id)
    return None if d is None else d.data


async def _audits(action: str) -> list[dict[str, Any]]:
    import app.modules.audit.store_specs  # noqa: F401 - registers audit_outbox

    out = []
    for d in await _st().scan("audit_outbox"):
        rec = json.loads(d.data["record_json"])
        if rec["action"] == action:
            out.append(rec)
    return out


async def _set_policy(table: str, **changes: Any) -> None:
    """An admin edit of the seeded policy row (the document as the backfill / console writes it)."""
    from app.modules.admin import public as admin_public
    from app.modules.admin.retention_defaults import DEFAULT_POLICIES

    await admin_public.ensure_retention_defaults(None)
    p = next(x for x in DEFAULT_POLICIES if x.table_name == table)
    cur = await _doc("retention_policies", str(p.doc_id))
    assert cur is not None
    if "retention_interval" in changes and changes["retention_interval"] is not None:
        changes["retention_interval"] = changes["retention_interval"].doc()
    await _put("retention_policies", {str(p.doc_id): {**cur, **changes}})


# --------------------------------------------------------------------------- seeds (real mappers)


def _attempt(at: datetime) -> tuple[str, dict[str, Any]]:
    from app.modules.sessions.store_specs import attempt_doc

    i = uuid7()
    return str(i), attempt_doc({"id": i, "attempted_at": at, "outcome": "failed", "ip": "203.0.113.9"})


def _observation(at: datetime) -> tuple[str, dict[str, Any]]:
    from app.modules.sessions.store_specs import observation_doc

    i = uuid7()
    row = {"id": i, "first_seen_at": at, "last_seen_at": at, "auth_session_id": uuid7(), "user_id": uuid7()}
    return str(i), observation_doc({**row, "net_cluster": "c1"})


def _session(ended: datetime | None, absolute: datetime) -> tuple[str, dict[str, Any]]:
    from app.modules.identity.fs_codec import row_doc
    from app.modules.sessions.models import AuthSession

    i = uuid7()
    row = {"id": i, "user_id": uuid7(), "status": "ended" if ended else "active"}
    return str(i), row_doc(AuthSession, {**row, "ended_at": ended, "absolute_expires_at": absolute})


def _signal(at: datetime, user: uuid.UUID | None, now: datetime) -> tuple[str, dict[str, Any]]:
    from app.core.firestore.ids import compose_id
    from app.modules.security.store_specs import SignalRow

    i = uuid7()
    row = SignalRow(id=i, occurred_at=at, user_id=user, family="sharing", rule_key="r", source="t")
    return compose_id(str(i), at.isoformat()), {**row.doc(), "expire_at": at + 180 * D}


def _evaluation(at: datetime, user: uuid.UUID, case: uuid.UUID | None) -> tuple[str, dict[str, Any]]:
    from app.modules.security.store_specs import RiskEvaluationRow

    i = uuid7()
    row = RiskEvaluationRow(id=i, evaluated_at=at, user_id=user, case_id=case, family="sharing")
    return str(i), {**row.doc(), "expire_at": at + 180 * D}


def _case(user: uuid.UUID, *, status: str, legal_hold: bool = False) -> tuple[str, dict[str, Any]]:
    from app.modules.security.store_specs import CaseRow

    i = uuid7()
    row = CaseRow(
        id=i,
        case_ref=f"SC-{i.hex[:8]}",
        user_id=user,
        family="sharing",
        level=2,
        status=status,
        legal_hold=legal_hold,
        opened_reason="t",
    )
    return str(i), row.doc()


def _playback(at: datetime) -> tuple[str, dict[str, Any]]:
    from app.modules.media.store_specs import playback_doc

    i = uuid7()
    return str(i), playback_doc({"id": i, "started_at": at, "user_id": uuid7(), "status": "ended"})


def _event(at: datetime) -> tuple[str, dict[str, Any]]:
    from app.core.firestore.sqlstore import to_doc
    from app.modules.assessments.models import AttemptEvent

    i = uuid7()
    return str(i), to_doc(
        AttemptEvent,
        {
            "id": i,
            "occurred_at": at,
            "attempt_id": uuid7(),
            "user_id": uuid7(),
            "event_type": "blur",
            "payload": {},
        },
    )


def _token(model: Any, expires: datetime, consumed: datetime | None) -> tuple[str, dict[str, Any]]:
    from app.modules.identity.store_specs import token_doc

    i = uuid7()
    row = {
        "id": i,
        "user_id": uuid7(),
        "purpose": "email_verify",
        "expires_at": expires,
        "consumed_at": consumed,
    }
    return str(i), token_doc(model, row)


def _outbox(occurred: datetime, dispatched: datetime | None, attempts: int) -> tuple[str, dict[str, Any]]:
    from app.core.firestore.core_store import event_doc

    i = uuid7()
    d = event_doc(i, "core.test_happened", {}, "x", uuid7(), None, occurred)
    d.update(attempts=attempts, dispatched_at=dispatched)
    if dispatched is not None or attempts >= 10:
        d.pop("pending_at", None)
    return str(i), d


def _idem(expires: datetime) -> tuple[str, dict[str, Any]]:
    i = uuid.uuid4().hex
    return i, {"status": "done", "created_at": expires - D, "expires_at": expires, "expire_at": expires}


def _notification(created: datetime, key: str | None) -> list[tuple[str, str, dict[str, Any]]]:
    from app.modules.notifications.store_specs import (
        DEDUPE,
        NOTIFICATIONS,
        dedupe_doc,
        dedupe_id,
        notification_doc,
    )

    i, user = uuid7(), uuid7()
    row = {
        "id": i,
        "user_id": user,
        "organization_id": None,
        "template_key": "t",
        "template_version": 1,
        "category": "system",
        "channels": ["in_app"],
        "data": {},
        "priority": "normal",
        "status": "sent",
        "delivery": {},
        "dedupe_key": key,
        "read_at": None,
        "created_at": created,
        "updated_at": created,
    }
    out = [(NOTIFICATIONS, str(i), notification_doc(row))]
    if key:
        out.append((DEDUPE, dedupe_id(user, key), dedupe_doc(row)))
    return out


async def _seed_bound_attempt(session_id: str) -> None:
    from app.core.firestore.sqlstore import to_doc
    from app.modules.assessments.models import TestAttempt
    from app.modules.assessments.store_specs import SPEC

    v = {
        "id": uuid7(),
        "test_id": uuid7(),
        "test_version": 1,
        "user_id": uuid7(),
        "attempt_no": 1,
        "status": "submitted",
        "selection_seed": b"s",
        "layout": {},
        "bound_session_id": uuid.UUID(session_id),
    }
    await _put("test_attempts", {SPEC.doc_id("test_attempts", v): to_doc(TestAttempt, v)})


# --------------------------------------------------------------------------- the defaults


def _migration(name: str) -> Any:
    path = API / "migrations" / "versions" / name
    spec = importlib.util.spec_from_file_location(f"_mig_{path.stem}", path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _iv(text: str) -> Any:
    from app.modules.admin.intervals import PgInterval

    n, unit = text.split()
    k = int(n)
    return {"days": PgInterval(days=k), "months": PgInterval(months=k), "year": PgInterval(months=12 * k)}[
        unit
    ]


def test_seed_defaults_match_the_migrations() -> None:
    """``retention_defaults`` = admin_0001 + core_base_0002 + support_0003, final state."""
    from app.modules.admin.retention_defaults import DEFAULT_POLICIES

    want: dict[tuple[str, str], tuple[Any, ...]] = {}
    admin = (API / "migrations" / "versions" / "admin_0001_admin.py").read_text(encoding="utf-8")
    pat = r"\(gen_random_uuid\(\), '(\w+)', '(\w+)', '([\w-]+)', interval '([^']+)', '([^']+)', '(\w+)', '(\w+)', '(\w+)'\)"
    for cat, table, cls, iv, basis, method, job, owner in re.findall(pat, admin):
        want[(table, cat)] = (cls, _iv(iv), basis, method, job, owner)
    assert len(want) == 5
    want = {
        k: (*v[:4], "purge_security_signals" if v[4] == "purge_risk" else v[4], v[5]) for k, v in want.items()
    }
    core = _migration("core_base_0002_maint.py")
    for table, cat, cls, iv, basis, method, job, owner in core.NEW_POLICIES:
        want[(table, cat)] = (cls, _iv(iv), basis, method, job, owner)
    sup = _migration("support_0003_security_purge_closed_cases.py")
    old = want.pop(("unblock_requests", "D9"))
    want[("unblock_requests", "D8")] = (
        old[0],
        old[1],
        "Case closure + 1 year; 3 years if disputed or legal hold (privacy D8)",
        old[3],
        "purge_closed_cases",
        old[5],
    )
    for table, basis in sup.NEW_POLICIES:
        want[(table, "D8")] = ("R-RISK", _iv("1 year"), basis, "row_delete", "purge_closed_cases", "security")
    got = {
        (p.table_name, p.data_category): (
            p.retention_class,
            p.retention_interval,
            p.basis,
            p.deletion_method,
            p.job_name,
            p.owner_module,
        )
        for p in DEFAULT_POLICIES
    }
    assert got == want


def test_targets_mirror_run_retention_order() -> None:
    from app.core import retention_fs

    sql = _migration("core_base_0002_maint.py").RUN_RETENTION
    tables = re.findall(r"'(\w+)'", sql.split("FOREACH t IN ARRAY ARRAY[")[1].split("] LOOP")[0])
    assert [t.table for t in retention_fs.all_targets()] == tables


def test_eligible_from_is_never_before_the_predicate() -> None:
    from app.core.retention_fs import eligible_from
    from app.modules.admin.intervals import PgInterval, subtract_interval

    for basis, iv in (
        (datetime(2028, 2, 29, 10, tzinfo=UTC), PgInterval(months=12)),
        (datetime(2027, 1, 31, 12, tzinfo=UTC), PgInterval(months=1)),
        (datetime(2027, 5, 3, 1, 2, 3, tzinfo=UTC), PgInterval(days=395)),
        (datetime(2027, 5, 3, tzinfo=UTC), PgInterval()),
    ):
        t = eligible_from(basis, iv)
        assert subtract_interval(t, iv) >= basis  # the SQL selects the row from just after t
        assert subtract_interval(t - timedelta(days=1), iv) < basis or not iv.months
        assert t - basis <= iv.as_timedelta() + timedelta(days=3)


def test_guarded_ttl_fields_are_indexed() -> None:
    """The TTL guard queries ``expire_at < horizon``: the field needs its ascending index (the TTL
    overrides used to exempt it with ``indexes: []``)."""
    from app.core import retention_fs

    spec = json.loads((API.parents[1] / "firestore.indexes.json").read_text(encoding="utf-8"))
    ov = {(o["collectionGroup"], o["fieldPath"]): o for o in spec["fieldOverrides"]}
    for t in retention_fs.all_targets():
        if t.ttl:
            o = ov[("lms_" + t.collection, "expire_at")]
            assert o["ttl"] and {"order": "ASCENDING", "queryScope": "COLLECTION"} in o["indexes"], t.table


# --------------------------------------------------------------------------- the job


async def test_retention_deletes_exactly_the_sql_rows(fs_env: Any, no_pg: None) -> None:  # noqa: F811
    from app.core import retention_fs
    from app.modules.identity.models import PasswordResetToken, VerificationToken
    from app.modules.notifications.store_specs import DEDUPE, NOTIFICATIONS

    now = _now()
    keep: dict[str, set[str]] = {}
    gone: dict[str, set[str]] = {}

    async def seed(
        coll: str, kept: list[tuple[str, dict[str, Any]]], deleted: list[tuple[str, dict[str, Any]]]
    ) -> None:
        await _put(coll, dict(kept + deleted))
        keep.setdefault(coll, set()).update(i for i, _ in kept)
        gone.setdefault(coll, set()).update(i for i, _ in deleted)

    await seed("login_attempts", [_attempt(now - 394 * D)], [_attempt(now - 396 * D)])
    await seed("session_network_observations", [_observation(now - 394 * D)], [_observation(now - 396 * D)])
    bound = _session(now - 400 * D, now - 399 * D)
    await _seed_bound_attempt(bound[0])
    await seed(
        "auth_sessions",
        # ended recently (coalesce picks ended_at), live, FK-referenced by a test attempt
        [_session(now - 10 * D, now - 400 * D), _session(None, now - 10 * D), bound],
        [_session(now - 400 * D, now - 300 * D), _session(None, now - 400 * D)],
    )
    open_u, closed_u, free_u, hold_u = uuid7(), uuid7(), uuid7(), uuid7()
    await _put(
        "security_cases",
        dict(
            [
                _case(open_u, status="open"),
                _case(closed_u, status="closed"),
                (hold := _case(hold_u, status="closed", legal_hold=True)),
            ]
        ),
    )
    hold_case = uuid.UUID(hold[0])
    await seed(
        "security_signals",
        [
            _signal(now - 181 * D, open_u, now),
            _signal(now - 181 * D, hold_u, now),
            _signal(now - 179 * D, free_u, now),
        ],
        [
            _signal(now - 181 * D, free_u, now),
            _signal(now - 181 * D, closed_u, now),
            _signal(now - 181 * D, None, now),
        ],
    )
    await seed(
        "risk_evaluations",
        # held through the user, held through the evaluation's own (legal-hold) case
        [_evaluation(now - 181 * D, open_u, None), _evaluation(now - 181 * D, free_u, hold_case)],
        [_evaluation(now - 181 * D, free_u, None), _evaluation(now - 181 * D, closed_u, None)],
    )
    await seed("playback_sessions", [_playback(now - 179 * D)], [_playback(now - 181 * D)])
    await seed("attempt_events", [_event(now - 700 * D)], [_event(now - 740 * D)])
    for model, coll in (
        (VerificationToken, "verification_tokens"),
        (PasswordResetToken, "password_reset_tokens"),
    ):
        await seed(
            coll,
            [_token(model, now - 6 * D, None), _token(model, now + D, now - 6 * D)],
            # consumed 8 days ago (coalesce picks consumed_at although expires_at is future), expired
            [_token(model, now + D, now - 8 * D), _token(model, now - 8 * D, None)],
        )
    await seed(
        "outbox_events",
        [
            _outbox(now - 8 * D, now - 6 * D, 1),
            _outbox(now - 30 * D, None, 3),
            _outbox(now - 6 * D, None, 10),
        ],
        [_outbox(now - 9 * D, now - 8 * D, 1), _outbox(now - 8 * D, None, 10)],
    )
    await seed("idempotency_keys", [_idem(now + timedelta(hours=1))], [_idem(now - timedelta(hours=1))])
    kept_n = _notification(now - 300 * D, "k1")
    old_n = _notification(now - 370 * D, "k2")
    for coll, i, d in kept_n + old_n:
        await _put(coll, {i: d})
    keep[NOTIFICATIONS] = {kept_n[0][1]}
    keep[DEDUPE] = {kept_n[1][1]}
    gone[NOTIFICATIONS] = {old_n[0][1]}
    gone[DEDUPE] = {old_n[1][1]}

    rows = await retention_fs.run_retention(now=now)

    for coll in keep:
        left = await _ids(coll)
        assert keep[coll] <= left, coll
        assert not (gone[coll] & left), coll
    assert await _ids("test_attempts")  # untouched
    by_table = {r["table_name"]: r["rows_deleted"] for r in rows}
    assert by_table == {
        "login_attempts": 1,
        "session_network_observations": 1,
        "auth_sessions": 2,
        "security_signals": 3,
        "risk_evaluations": 2,
        "playback_sessions": 1,
        "attempt_events": 1,
        "verification_tokens": 2,
        "password_reset_tokens": 2,
        "outbox_events": 2,
        "idempotency_keys": 1,
        "notifications": 1,
    }
    [rec] = await _audits("maint.retention.purged")
    assert rec["actor_roles"] == ["system:maint.retention"] and rec["target_type"] == "retention_policy"
    assert rec["after_state"] == {
        t: {"partitions_dropped": 0, "rows_deleted": n} for t, n in by_table.items()
    }
    # held evidence keeps no TTL stamp (the guard runs for security every day)
    held_sig = next(
        i
        for i, d in [(i, await _doc("security_signals", i)) for i in keep["security_signals"]]
        if d and d["user_id"] == str(open_u)
    )
    assert (await _doc("security_signals", held_sig))["expire_at"] is None  # type: ignore[index]


async def test_admin_edited_intervals_and_ttl_guard(fs_env: Any, no_pg: None) -> None:  # noqa: F811
    from app.core import retention_fs
    from app.modules.admin.intervals import PgInterval, add_interval
    from app.modules.notifications.store_specs import DEDUPE, NOTIFICATIONS

    now = _now()
    await _set_policy("login_attempts", retention_interval=PgInterval(days=30))  # shortened
    await _set_policy("notifications", retention_interval=PgInterval(months=24))  # lengthened
    await _set_policy("playback_sessions", is_active=False)  # deactivated: the SQL skips it
    a_old, a_new = _attempt(now - 40 * D), _attempt(now - 20 * D)
    await _put("login_attempts", dict([a_old, a_new]))
    notif = _notification(now - 400 * D, "k")  # its 365-day TTL stamp is already in the past
    for coll, i, d in notif:
        await _put(coll, {i: d})
    play = _playback(now - 400 * D)
    await _put("playback_sessions", dict([play]))

    rows = await retention_fs.run_retention(now=now)

    assert await _ids("login_attempts") == {a_new[0]}
    n_id, m_id = notif[0][1], notif[1][1]
    assert await _ids(NOTIFICATIONS) == {n_id} and await _ids(DEDUPE) == {m_id}
    want = add_interval(now - 400 * D, PgInterval(months=24))
    for coll, i in ((NOTIFICATIONS, n_id), (DEDUPE, m_id)):
        exp = (await _doc(coll, i))["expire_at"]  # type: ignore[index]
        assert exp >= want and exp - want < timedelta(days=4), coll  # the TTL can no longer fire early
    assert await _ids("playback_sessions") == {play[0]}
    assert (await _doc("playback_sessions", play[0]))["expire_at"] is None  # type: ignore[index]
    tables = {r["table_name"] for r in rows}
    assert "playback_sessions" not in tables and {"login_attempts", "notifications"} <= tables
    [rec] = await _audits("maint.retention.purged")
    assert "playback_sessions" not in rec["after_state"]
    assert rec["after_state"]["login_attempts"] == {"partitions_dropped": 0, "rows_deleted": 1}


async def test_active_policy_without_interval_fails_before_deleting(fs_env: Any, no_pg: None) -> None:  # noqa: F811
    from app.core import retention_fs

    now = _now()
    await _set_policy("outbox_events", retention_interval=None)
    old = _attempt(now - 400 * D)
    await _put("login_attempts", dict([old]))
    with pytest.raises(ValueError, match="outbox_events has no active retention policy"):
        await retention_fs.run_retention(now=now)
    assert await _ids("login_attempts") == {old[0]}
    assert await _audits("maint.retention.purged") == []


async def test_empty_run_is_audited_and_cheap(fs_env: Any, no_pg: None) -> None:  # noqa: F811
    from app.core import maintenance

    rows = await maintenance.run_retention()
    assert rows is not None and {r["rows_deleted"] for r in rows} == {0} and len(rows) == 12
    [rec] = await _audits("maint.retention.purged")
    assert set(rec["after_state"]) == {r["table_name"] for r in rows}
    assert len(await _ids("retention_policies")) == 17  # migration rows seeded once
    await maintenance.run_retention()
    assert len(await _ids("retention_policies")) == 17
    assert len(await _audits("maint.retention.purged")) == 2  # every run is audited


async def test_seed_never_overrides_existing_rows(fs_env: Any, no_pg: None) -> None:  # noqa: F811
    from app.modules.admin import public as admin_public
    from app.modules.admin.intervals import PgInterval

    backfilled = {
        "id": str(uuid.uuid4()),
        "data_category": "D7",
        "table_name": "login_attempts",
        "retention_class": "R-SEC",
        "retention_interval": PgInterval(days=500).doc(),
        "basis": "x",
        "deletion_method": "partition_drop",
        "legal_hold_aware": True,
        "job_name": "purge_auth_logs",
        "owner_module": "sessions",
        "is_active": True,
    }
    await _put("retention_policies", {backfilled["id"]: backfilled})
    assert await admin_public.ensure_retention_defaults(None) == 16
    assert (await admin_public.active_retention_intervals(None))["login_attempts"] == PgInterval(days=500)


async def test_purge_closed_cases_runs_on_an_unseeded_firestore(fs_env: Any, no_pg: None) -> None:  # noqa: F811
    """No ``retention_policies`` documents (no migrations): the job seeds them instead of raising
    "security_cases has no active retention policy"; a case closed 400 days ago goes."""
    from app.modules.security import retention
    from app.modules.security.store_specs import CaseRow

    old_i, old = _case(uuid7(), status="closed")
    young_i, young = _case(uuid7(), status="closed")
    old["closed_at"] = CaseRow(closed_at=_now() - 400 * D).doc()["closed_at"]
    young["closed_at"] = CaseRow(closed_at=_now() - 30 * D).doc()["closed_at"]
    await _put("security_cases", {old_i: old, young_i: young})
    out = await retention.purge_closed_cases()
    assert out is not None and out["rows_deleted"]["security_cases"] == 1
    assert await _ids("security_cases") == {young_i}
    assert await _audits("security.closed_cases.purged")


# --------------------------------------------------------------------------- dispatch


def test_partitions_are_a_logged_noop_without_postgres(no_pg: None, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core import maintenance

    async def boom(*_a: Any) -> Any:
        raise AssertionError("no Postgres call on Firebase")

    from structlog.testing import capture_logs

    monkeypatch.setattr(maintenance, "_call", boom)
    with capture_logs() as logs:
        assert maintenance.maint_partitions.run() == 0  # the task body: success, nothing to do
    assert [(x["event"], x["log_level"]) for x in logs] == [("partitions_noop", "info")]


async def test_vm_keeps_the_sql_path(monkeypatch: pytest.MonkeyPatch) -> None:
    """No module on Firestore (the VM): one ``maint.run_retention`` call, nothing else."""
    from app.core import maintenance, retention_fs
    from app.core.firestore import backend

    calls: list[str] = []

    async def fake(sql: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        calls.append(sql)
        if "run_partition_maintenance" in sql:
            return [{"parent": "login_attempts", "partition_name": "p", "action": "exists", "moved_rows": 0}]
        return [{"table_name": "login_attempts", "partitions_dropped": 1, "rows_deleted": 2}]

    async def no_fs(*_a: Any, **_k: Any) -> Any:
        raise AssertionError("Firestore retention on the VM")

    from app.core import runtime

    monkeypatch.setattr(runtime, "postgres_enabled", lambda: True)
    monkeypatch.setattr(backend, "firestore_modules", lambda: ())
    monkeypatch.setattr(maintenance, "_call", fake)
    monkeypatch.setattr(retention_fs, "run_retention", no_fs)
    assert retention_fs.firestore_targets() == []
    rows = await maintenance.run_retention()
    assert calls == ["SELECT * FROM maint.run_retention(:b, :mb)"] and rows and rows[0]["rows_deleted"] == 2
    calls.clear()
    await maintenance.run_partition_maintenance()
    assert calls == ["SELECT * FROM maint.run_partition_maintenance(:m)"]
