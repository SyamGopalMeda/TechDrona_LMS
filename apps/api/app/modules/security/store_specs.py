"""Firestore data model of the security module (data-ops agent; docs/firebase/agents/data-ops.md).

**Status: data path only** (collections, mappers, backfill + verify). ``security`` has no
Firestore repository yet, so ``TD_STORE_SECURITY`` must stay ``postgres``; nothing in the module
reads these collections. Each table maps 1:1 to a collection with the Postgres primary key as
document id (composite keys -> ``compose_id``) and the ORM column names (``admin.fs_rows``
kinds: UUID text, Timestamps, NUMERIC as exact text, JSONB as JSON text, bytea as hex).

Families follow the Postgres RLS comments (``O`` -> owned by ``user_id``; ``NONE (API)`` -> shared
with the route's permission; append-only where Postgres revokes UPDATE/DELETE):

* ``security_signals/{id}:{occurred_at}`` -- owned, ``security.evidence.read``, append-only
  (suppression flag only); high volume: the repository must set a TTL ``expire_at`` (R-RISK).
* ``risk_evaluations/{id}:{evaluated_at}`` -- owned, ``security.case.read``, append-only series.
* ``risk_rules/{id}``, ``risk_rule_versions/{id}`` -- shared, ``security.rule.read`` (versions
  immutable).
* ``security_counters/{counter_key}:{bucket_start}`` -- system; rate counters (2-day retention).
  Plan §3.1 moves them to the rate-limit store (Redis/Firestore runtime), not this collection.
* ``security_user_state/{user_id}``, ``account_restrictions``, ``security_cases``,
  ``security_notices``, ``unblock_requests`` -- owned by ``user_id``.
* ``case_notes``, ``case_decisions`` -- shared, ``security.case.read``, append-only.
* ``security_incidents``, ``security_bulk_lifts``, ``security_report_exports`` -- shared.
"""

from __future__ import annotations

from app.core.firestore.collections import CollectionSpec
from app.modules.admin.fs_rows import register_model
from app.modules.security import models as m

M = "security"


def _owned(name: str, read: str, *, append_only: bool = False) -> CollectionSpec:
    return CollectionSpec(name, "owned", owner_writes=False, read_permission=read, append_only=append_only)


def _shared(name: str, read: str, *, append_only: bool = False) -> CollectionSpec:
    return CollectionSpec(
        name, "shared", read_permission=read, write_permission=read, append_only=append_only
    )


SignalRow = register_model(
    M, m.SecuritySignal, _owned("security_signals", "security.evidence.read", append_only=True)
)
RiskEvaluationRow = register_model(
    M, m.RiskEvaluation, _owned("risk_evaluations", "security.case.read", append_only=True)
)
RiskRuleRow = register_model(M, m.RiskRule, _shared("risk_rules", "security.rule.read"))
RiskRuleVersionRow = register_model(
    M, m.RiskRuleVersion, _shared("risk_rule_versions", "security.rule.read", append_only=True)
)
CounterRow = register_model(M, m.SecurityCounter, CollectionSpec("security_counters", "system"))
UserStateRow = register_model(M, m.SecurityUserState, _owned("security_user_state", "security.case.read"))
RestrictionRow = register_model(
    M, m.AccountRestriction, _owned("account_restrictions", "security.status.read")
)
CaseRow = register_model(M, m.SecurityCase, _owned("security_cases", "security.case.read"))
CaseNoteRow = register_model(M, m.CaseNote, _shared("case_notes", "security.case.read", append_only=True))
CaseDecisionRow = register_model(
    M, m.CaseDecision, _shared("case_decisions", "security.case.read", append_only=True)
)
IncidentRow = register_model(M, m.SecurityIncident, _shared("security_incidents", "security.incident.read"))
NoticeRow = register_model(M, m.SecurityNotice, _owned("security_notices", "security.case.read"))
BulkLiftRow = register_model(
    M, m.SecurityBulkLift, _shared("security_bulk_lifts", "security.restriction.bulk_lift")
)
ReportExportRow = register_model(
    M, m.SecurityReportExport, _shared("security_report_exports", "security.case.read")
)
UnblockRow = register_model(M, m.UnblockRequest, _owned("unblock_requests", "security.unblock.triage"))


# ``restriction_heads/{user_id}:{family}`` -> ``{active_id}``: the Postgres partial unique index
# ``ux_ar_active_family`` (one active restriction per user and family). Written in the same
# transaction as the restriction rows.
RESTRICTION_HEADS = "restriction_heads"


def _heads_rows(session: object) -> object:
    from sqlalchemy import text

    async def load(s: object) -> list[dict[str, object]]:
        res = await s.execute(  # type: ignore[attr-defined]
            text(
                "SELECT user_id, family, id AS active_id FROM account_restrictions "
                "WHERE ended_at IS NULL ORDER BY user_id, family"
            )
        )
        return [dict(r) for r in res.mappings().all()]

    return load(session)


def _register_heads() -> None:
    from app.core.firestore.backfill import TableMapping, register_mapping
    from app.core.firestore.collections import register_collection
    from app.core.firestore.ids import compose_id

    register_collection(CollectionSpec(RESTRICTION_HEADS, "system"))
    register_mapping(
        TableMapping(
            M,
            "account_restrictions:heads",
            RESTRICTION_HEADS,
            lambda r: compose_id(str(r["user_id"]), str(r["family"])),
            lambda r: {"active_id": str(r["active_id"])},
            loader=_heads_rows,  # type: ignore[arg-type]
        )
    )


_register_heads()

# pass 2: ``expire_at`` of signals / evaluations / counters (repo_fs_engine.register_backfill_expiry)
import app.modules.security.repo_fs_engine  # noqa: E402, F401
