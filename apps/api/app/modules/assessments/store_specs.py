"""Assessments on Firestore through the shared SQL engine (``app/core/firestore/sqlstore.py``).

Round 3: instead of a hand-written repository per query, the module keeps its SQLAlchemy code and
runs it through ``STORE`` (``assessments/datastore.py``): with ``TD_STORE_ASSESSMENTS=postgres``
every call goes to the Postgres session unchanged; with ``firestore`` the engine interprets the
statements over Firestore documents (one per row, ``lms_<table>``), keeps a per-request unit of
work and commits it in **one Firestore transaction** at the end of the request (attempt start,
submit, scoring and grading stay all-or-nothing; rows read ``FOR UPDATE`` are version-checked,
the loser of a race gets 409 instead of waiting).

Tables, RLS families and constraints (from ``assessments_0001..0004``):

* ``read_all`` (TN): tests, test_sections, test_section_rules, test_assignments.
* ``owner`` (U/US): test_attempts, attempt_overrides, attempt_sections, attempt_responses,
  attempt_events, attempt_results, attempt_integrity_decisions, attempt_item_grades. The engine's
  owner family is "own rows or platform"; the US organisation-staff branch is not emulated (single
  company: staff work through platform grants or system contexts, as the code already does).
* Uniques: ``UNIQUE (test_id, position)``, ``UNIQUE (test_section_id, position)``,
  ``UNIQUE (test_id, user_id, attempt_no)``, ``UNIQUE (user_id, idempotency_key)``,
  ``ux_att_one_open`` (partial: only ``in_progress`` rows), ``UNIQUE (attempt_id,
  question_version_id)`` on responses. Composite primary keys become composite document ids.
* Append-only (``revoke_app_writes``): attempt_events, attempt_integrity_decisions.
* ``updated_at`` triggers: tests, test_assignments, test_attempts, attempt_results,
  attempt_item_grades.
"""

from __future__ import annotations

from typing import Any

from app.core.firestore.sqlstore import SqlModuleSpec, SqlStore
from app.modules.assessments.models import (
    AttemptEvent,
    AttemptIntegrityDecision,
    AttemptItemGrade,
    AttemptOverride,
    AttemptResponse,
    AttemptResult,
    AttemptSection,
    Test,
    TestAssignment,
    TestAttempt,
    TestSection,
    TestSectionRule,
)

MODELS: tuple[type[Any], ...] = (
    Test,
    TestSection,
    TestSectionRule,
    TestAssignment,
    TestAttempt,
    AttemptOverride,
    AttemptSection,
    AttemptResponse,
    AttemptEvent,
    AttemptResult,
    AttemptIntegrityDecision,
    AttemptItemGrade,
)

RLS = {
    "tests": "read_all",
    "test_sections": "read_all",
    "test_section_rules": "read_all",
    "test_assignments": "read_all",
    "test_attempts": "owner",
    "attempt_overrides": "owner",
    "attempt_sections": "owner",
    "attempt_responses": "owner",
    "attempt_events": "owner",
    "attempt_results": "owner",
    "attempt_integrity_decisions": "owner",
    "attempt_item_grades": "owner",
}


def _k(*parts: Any) -> str:
    return "|".join(str(p) for p in parts)


UNIQUES: dict[str, list[tuple[str, Any]]] = {
    "test_sections": [("ts_position", lambda r: _k(r.test_id, r.position))],
    "test_section_rules": [("tsr_position", lambda r: _k(r.test_section_id, r.position))],
    "test_attempts": [
        ("att_no", lambda r: _k(r.test_id, r.user_id, r.attempt_no)),
        ("att_idem", lambda r: _k(r.user_id, r.idempotency_key) if r.idempotency_key else None),
        ("att_one_open", lambda r: _k(r.test_id, r.user_id) if r.status == "in_progress" else None),
    ],
    "attempt_responses": [("resp_item", lambda r: _k(r.attempt_id, r.question_version_id))],
}


class _Spec(SqlModuleSpec):
    """``attempt_events`` has the partitioned-table primary key ``(id, occurred_at)``; ``id`` alone is
    unique (uuid7), so it is the document id (the engine's default would compose a datetime)."""

    def doc_id(self, table: str, values: Any) -> str:
        if table == "attempt_events":
            get = values.get if isinstance(values, dict) else lambda k: getattr(values, k)
            return str(get("id"))
        return super().doc_id(table, values)


SPEC = _Spec(
    module="assessments",
    models=MODELS,
    rls=RLS,
    uniques=UNIQUES,
    updated_at_trigger=frozenset(
        {"tests", "test_assignments", "test_attempts", "attempt_results", "attempt_item_grades"}
    ),
    append_only=frozenset({"attempt_events", "attempt_integrity_decisions"}),
    no_delete=frozenset({"attempt_events", "attempt_integrity_decisions"}),
    job="assessments.store",
)
STORE = SqlStore(SPEC)


def _register_backfill() -> None:
    """``SqlStore.register_backfill`` with this spec's document ids (attempt_events: ``id``)."""
    from app.core.firestore.backfill import TableMapping, register_mapping
    from app.core.firestore.sqlstore import to_doc

    for m in MODELS:
        pk = ", ".join(c.key for c in m.__table__.primary_key.columns)
        table = m.__tablename__

        def transform(r: dict[str, Any], m: type[Any] = m) -> dict[str, Any]:
            return to_doc(m, r)

        def did(r: dict[str, Any], table: str = table) -> str:
            return SPEC.doc_id(table, r)

        register_mapping(TableMapping("assessments", table, table, did, transform, order_by=pk))


_register_backfill()

__all__ = ["MODELS", "RLS", "SPEC", "STORE"]
