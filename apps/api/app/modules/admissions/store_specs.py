"""Firestore collections of the admissions module (``TD_STORE_ADMISSIONS``).

Same layout as commerce (shared engine ``app/core/firestore/sqlstore.py``): one collection per
table, same logical name (physical ``lms_<table>``), one document per row, document id = the
primary key (``course_status``: the slug; ``admission_pay_settings``: ``"1"``), every column under
its own name (UUID -> str, timestamptz -> timestamp, ``date`` -> ISO string, JSONB ``schedule`` ->
canonical JSON string).

* RLS: every admissions table is ``app.is_platform()`` only (admissions_0001/0003) -> ``platform``.
  Public routes run under ``system_context`` exactly as on Postgres.
* td_app has no DELETE on any table and no UPDATE on ``admission_events`` (append-only).
* Uniques (``uniq_admissions_*``): ``admission_fee_plans.course_slug``,
  ``admission_registrations.reg_no``, one live registration per (course, email)
  (``ux_areg_email_course``: status not rejected/cancelled), and the anti-replay locks on claims
  (``ux_apc_utr`` / ``ux_apc_proof`` / ``ux_apc_proof_original`` while ``NOT locks_released``).
* CHECKs: ``ck_afp_terms``, ``ck_areg_ledger`` / ``ck_areg_access`` / ``ck_areg_enrolled``,
  ``open_claims`` 0..3, ``ck_apc_student`` / ``ck_apc_verified`` / ``ck_apc_reviewed``.
* The deferred ledger trigger (``verified_total_paise = sum(verified claims)``) is the commit
  read-check ``ledger_sum``: evaluated in the commit transaction for every registration whose row
  or claims changed.
"""

from __future__ import annotations

from typing import Any

from app.core.firestore.sqlstore import CheckViolation, SqlModuleSpec, SqlStore, from_doc
from app.core.firestore.store import ScopedTransaction
from app.modules.admissions.models import (
    AdmissionEvent,
    AdmissionFeePlan,
    AdmissionPaymentClaim,
    AdmissionPaySettings,
    AdmissionRegistration,
    CourseStatus,
)

MODELS: tuple[type[Any], ...] = (
    CourseStatus,
    AdmissionPaySettings,
    AdmissionFeePlan,
    AdmissionRegistration,
    AdmissionPaymentClaim,
    AdmissionEvent,
)
TABLES = frozenset(m.__tablename__ for m in MODELS)
REGS = "admission_registrations"
CLAIMS = "admission_payment_claims"


def _live_reg(r: Any) -> str | None:
    if r.status in ("rejected", "cancelled"):
        return None
    return f"{r.course_slug}|{r.email}"


def _lock(field: str) -> Any:
    def key(c: Any) -> str | None:
        v = getattr(c, field)
        return None if v is None or c.locks_released else str(v)

    return key


UNIQUES: dict[str, list[tuple[str, Any]]] = {
    "admission_fee_plans": [("afp_course", lambda r: r.course_slug)],
    REGS: [("areg_reg_no", lambda r: r.reg_no), ("areg_email_course", _live_reg)],
    CLAIMS: [
        ("apc_utr", _lock("utr")),
        ("apc_proof", _lock("proof_sha256")),
        ("apc_proof_original", _lock("proof_original_sha256")),
    ],
}


def check(table: str, r: Any) -> str | None:
    if table == "admission_fee_plans":
        if not (r.access_min_paise <= r.fee_paise and r.min_first_paise <= r.fee_paise):
            return "ck_afp_terms"
    elif table == REGS:
        if not (
            0 <= r.verified_total_paise <= r.fee_paise
            and r.balance_paise == r.fee_paise - r.verified_total_paise
        ):
            return "ck_areg_ledger"
        if r.access_min_paise > r.fee_paise:
            return "ck_areg_access"
        if r.status == "enrolled" and r.enrolled_at is None:
            return "ck_areg_enrolled"
        if not (0 <= (r.open_claims or 0) <= 3):
            return "admission_registrations_open_claims_check"
    elif table == CLAIMS:
        if not (0 < r.amount_paise <= 100_000_000):
            return "admission_payment_claims_amount_paise_check"
        if r.provider == "manual_upi" and (r.utr is None or r.proof_key is None or r.proof_sha256 is None):
            return "ck_apc_student"
        if (r.status in ("verified", "reversed")) != ((r.verified_amount_paise or 0) > 0):
            return "ck_apc_verified"
        if r.status != "pending" and r.provider != "admin_entry" and r.reviewed_at is None:
            return "ck_apc_reviewed"
    return None


async def ledger_sum(tx: ScopedTransaction, work: list[Any]) -> None:
    """``trg_areg_ledger`` / ``trg_apc_ledger`` (deferred to commit): a registration's
    ``verified_total_paise`` equals the sum of its verified claims."""
    changed_regs = {e.doc_id: e.obj for e, final, ch in work if e.table == REGS and ch and final}
    claim_objs = {e.doc_id: e.obj for e, final, ch in work if e.table == CLAIMS and ch and final}
    rids = set(changed_regs) | {str(c.registration_id) for c in claim_objs.values()}
    for rid in rids:
        reg = changed_regs.get(rid)
        if reg is None:
            d = await tx.get(REGS, rid)
            if d is None:
                continue
            reg = from_doc(AdmissionRegistration, d.data)
        claims = {
            d.id: from_doc(AdmissionPaymentClaim, d.data)
            for d in await tx.query(CLAIMS, filters=[("registration_id", "==", rid)])
        }
        claims.update({k: c for k, c in claim_objs.items() if str(c.registration_id) == rid})
        expected = sum(c.verified_amount_paise or 0 for c in claims.values() if c.status == "verified")
        if reg.verified_total_paise != expected:
            raise CheckViolation(
                f"admissions ledger mismatch for registration {rid}: total "
                f"{reg.verified_total_paise} <> verified claims {expected} (ck_areg_ledger_sum)"
            )


SPEC = SqlModuleSpec(
    module="admissions",
    models=MODELS,
    rls=dict.fromkeys(TABLES, "platform"),
    uniques=UNIQUES,
    updated_at_trigger=frozenset({"course_status", "admission_fee_plans", REGS, CLAIMS}),
    no_delete=TABLES,
    append_only=frozenset({"admission_events"}),
    check=check,
    commit_reads=(ledger_sum,),
)
STORE = SqlStore(SPEC)
STORE.register_backfill()
