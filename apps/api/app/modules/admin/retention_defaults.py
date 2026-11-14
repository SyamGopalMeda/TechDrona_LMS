"""The ``retention_policies`` rows the migrations seed, in their final state (Firestore seed).

On Postgres the rows come from ``admin_0001`` (5 rows), ``core_base_0002`` (``NEW_POLICIES``;
renames job ``purge_risk`` -> ``purge_security_signals``) and ``support_0003`` (the ``unblock_requests``
row becomes D8 / ``purge_closed_cases`` and 4 case tables are added). A Firestore-only stack has no
migrations, so ``ensure_retention_defaults`` (``repo_firestore_privacy``) inserts each row that is
missing -- by ``(table_name, data_category)``, the Postgres unique key -- exactly like the
migrations' ``INSERT ... ON CONFLICT DO NOTHING``. Existing documents (backfilled rows, admin edits
of ``retention_interval`` / ``is_active``) are never touched.

``tests/platform/test_retention_firestore.py`` checks this list against the migration constants.
"""

from __future__ import annotations

import uuid
from typing import NamedTuple

from app.modules.admin.intervals import PgInterval


class DefaultPolicy(NamedTuple):
    table_name: str
    data_category: str
    retention_class: str
    retention_interval: PgInterval
    basis: str
    deletion_method: str
    job_name: str
    owner_module: str

    @property
    def doc_id(self) -> uuid.UUID:
        """Deterministic id: two concurrent seeds create one document, not two."""
        return uuid.uuid5(_NS, f"{self.table_name}|{self.data_category}")


_NS = uuid.UUID("6f1c3a52-2f4e-4d0b-9a61-0c7d1e5b8a10")
_CASE_BASIS = "Case closure + 1 year; 3 years if disputed or legal hold (privacy D8)"
_TOKEN_BASIS = "7 days after expiry/consumption (schema R-TOKEN)"  # noqa: S105 - not a secret

DEFAULT_POLICIES: tuple[DefaultPolicy, ...] = (
    # admin_0001 (+ core_base_0002 job rename, support_0003 unblock_requests update)
    DefaultPolicy(
        "login_attempts",
        "D7",
        "R-SEC",
        PgInterval(days=395),
        "CERT-In logs >= 1 year",
        "partition_drop",
        "purge_auth_logs",
        "sessions",
    ),
    DefaultPolicy(
        "session_network_observations",
        "D7",
        "R-SEC",
        PgInterval(days=395),
        "CERT-In logs >= 1 year",
        "partition_drop",
        "purge_auth_logs",
        "sessions",
    ),
    DefaultPolicy(
        "security_signals",
        "D8",
        "R-RISK",
        PgInterval(days=180),
        "Risk evidence (RE §4.5)",
        "partition_drop",
        "purge_security_signals",
        "security",
    ),
    DefaultPolicy(
        "risk_evaluations",
        "D8",
        "R-RISK",
        PgInterval(days=180),
        "Risk evidence (RE §9)",
        "partition_drop",
        "purge_security_signals",
        "security",
    ),
    DefaultPolicy(
        "unblock_requests",
        "D8",
        "R-RISK",
        PgInterval(days=365),
        _CASE_BASIS,
        "row_delete",
        "purge_closed_cases",
        "security",
    ),
    # core_base_0002 NEW_POLICIES
    DefaultPolicy(
        "auth_sessions",
        "D5",
        "R-SEC",
        PgInterval(days=395),
        "Ended sessions: CERT-In logs >= 1 year (privacy §7)",
        "row_delete",
        "purge_auth_logs",
        "sessions",
    ),
    DefaultPolicy(
        "playback_sessions",
        "D11",
        "R-PLAY",
        PgInterval(days=180),
        "Video playback (privacy D11)",
        "partition_drop",
        "purge_playback",
        "media",
    ),
    DefaultPolicy(
        "attempt_events",
        "D15",
        "R-ASSESS-EVT",
        PgInterval(months=24),
        "Attempt events (schema R-ASSESS-EVT)",
        "partition_drop",
        "purge_attempt_events",
        "assessments",
    ),
    DefaultPolicy(
        "verification_tokens",
        "TOKEN",
        "R-TOKEN",
        PgInterval(days=7),
        _TOKEN_BASIS,
        "row_delete",
        "purge_tokens",
        "identity",
    ),
    DefaultPolicy(
        "password_reset_tokens",
        "TOKEN",
        "R-TOKEN",
        PgInterval(days=7),
        _TOKEN_BASIS,
        "row_delete",
        "purge_tokens",
        "identity",
    ),
    DefaultPolicy(
        "outbox_events",
        "OPS",
        "R-OPS",
        PgInterval(days=7),
        "Dispatched or dead-lettered domain events (schema §17)",
        "row_delete",
        "purge_outbox",
        "core",
    ),
    DefaultPolicy(
        "idempotency_keys",
        "OPS",
        "R-OPS",
        PgInterval(),
        "Removed once expires_at (24 h / 7 d money) passes",
        "row_delete",
        "purge_idempotency",
        "core",
    ),
    DefaultPolicy(
        "notifications",
        "D13",
        "R-NOTIF",
        PgInterval(months=12),
        "Notification logs 1 year (privacy D13)",
        "row_delete",
        "purge_notifications",
        "notifications",
    ),
    # support_0003 NEW_POLICIES
    DefaultPolicy(
        "security_cases",
        "D8",
        "R-RISK",
        PgInterval(months=12),
        "Security cases: closure + 1 year; 3 years if disputed or legal hold (privacy D8)",
        "row_delete",
        "purge_closed_cases",
        "security",
    ),
    DefaultPolicy(
        "case_notes",
        "D8",
        "R-RISK",
        PgInterval(months=12),
        "Reviewer notes: with their case (privacy D8)",
        "row_delete",
        "purge_closed_cases",
        "security",
    ),
    DefaultPolicy(
        "case_decisions",
        "D8",
        "R-RISK",
        PgInterval(months=12),
        "Case decisions: with their case (privacy D8)",
        "row_delete",
        "purge_closed_cases",
        "security",
    ),
    DefaultPolicy(
        "account_restrictions",
        "D8",
        "R-RISK",
        PgInterval(months=12),
        "Case-linked restrictions: with their case (privacy D8)",
        "row_delete",
        "purge_closed_cases",
        "security",
    ),
)
