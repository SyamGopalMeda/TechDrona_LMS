"""Firestore collections of the admin settings slice (MIGRATION-PLAN P2; docs/firebase/p2.md).

Moved with ``TD_STORE_ADMIN=firestore``: ``feature_flags`` and ``policy_settings`` (both
"RLS: NONE (platform config)" in Postgres). Privacy requests, erasure ledger, retention policies
and break-glass sessions stay on Postgres for now (see p2.md "not moved yet").

* ``feature_flags/{flag_key}`` — the flag row (``id`` kept for audit ``target_id``).
* ``policy_settings/{id}`` — every version row, as in Postgres (versioned; never deleted).
* ``policy_heads/{setting_key:scope_type:scope_id|-}`` — ``{active_id, version}``: the
  "one active row per key and scope" invariant (Postgres ``ux_ps_active``) and the version
  counter. Written in the same transaction as the version rows.
"""

from __future__ import annotations

from typing import Any

from app.core.firestore.backfill import Row, TableMapping, register_mapping
from app.core.firestore.collections import CollectionSpec, register_collection
from app.core.firestore.ids import compose_id

FLAGS = "feature_flags"
POLICY = "policy_settings"
POLICY_HEADS = "policy_heads"

register_collection(
    CollectionSpec(FLAGS, "shared", read_permission=None, write_permission="feature_flag.manage")
)
# Policy values are read by every module (security engine, sessions, playback): platform config.
# Writes happen only after the router / approval / case-decision checks, through a named job.
register_collection(CollectionSpec(POLICY, "shared", read_permission=None, write_permission="policy.edit"))
register_collection(
    CollectionSpec(POLICY_HEADS, "shared", read_permission=None, write_permission="policy.edit")
)


def head_id(key: str, scope_type: str, scope_id: Any) -> str:
    return compose_id(key, scope_type, str(scope_id) if scope_id else "-")


def flag_doc(r: Row) -> dict[str, Any]:
    return {
        "id": str(r["id"]),
        "flag_key": r["flag_key"],
        "description": r["description"],
        "is_enabled": bool(r["is_enabled"]),
        "rollout_percent": int(r["rollout_percent"]),
        "user_allowlist": [str(u) for u in (r["user_allowlist"] or [])],
        "updated_by": str(r["updated_by"]) if r["updated_by"] else None,
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
    }


def _opt(v: Any) -> str | None:
    return str(v) if v is not None else None


def policy_doc(r: Row) -> dict[str, Any]:
    return {
        "id": str(r["id"]),
        "setting_key": r["setting_key"],
        "scope_type": r["scope_type"],
        "scope_id": _opt(r["scope_id"]),
        "value": r["value"],
        "value_schema": r["value_schema"],
        "min_value": r["min_value"],
        "max_value": r["max_value"],
        "plan_overridable": bool(r["plan_overridable"]),
        "locked": bool(r["locked"]),
        "version": int(r["version"]),
        "is_active": bool(r["is_active"]),
        "effective_from": r["effective_from"],
        "expires_at": r["expires_at"],
        "case_decision_id": _opt(r["case_decision_id"]),
        "change_reason": r["change_reason"],
        "changed_by": str(r["changed_by"]),
        "approved_by": _opt(r["approved_by"]),
        "approval_request_id": _opt(r["approval_request_id"]),
        "created_at": r["created_at"],
    }


def head_doc(r: Row) -> dict[str, Any]:
    return {
        "setting_key": r["setting_key"],
        "scope_type": r["scope_type"],
        "scope_id": _opt(r["scope_id"]),
        "active_id": _opt(r["active_id"]),
        "version": int(r["version"]),
    }


register_mapping(
    TableMapping("admin", "feature_flags", FLAGS, lambda r: r["flag_key"], flag_doc, order_by="flag_key")
)
register_mapping(TableMapping("admin", "policy_settings", POLICY, lambda r: str(r["id"]), policy_doc))
register_mapping(
    TableMapping(
        "admin",
        "(SELECT setting_key, scope_type, scope_id, max(version) AS version, "
        "(array_agg(id) FILTER (WHERE is_active))[1] AS active_id "
        "FROM policy_settings GROUP BY setting_key, scope_type, scope_id) AS heads",
        POLICY_HEADS,
        lambda r: head_id(r["setting_key"], r["scope_type"], r["scope_id"]),
        head_doc,
        order_by="setting_key, scope_type, scope_id",
    )
)


# --------------------------------------------------------------------------- privacy / break-glass
# (data-ops agent, docs/firebase/agents/data-ops.md). Same switch: ``TD_STORE_ADMIN=firestore``
# moves these together with flags and policy.
#
# * ``privacy_requests/{id}`` -- owned by ``user_id`` (RLS ``O``): the learner reads their own, staff
#   need ``privacy.request.process``. ``request_ref`` is unique through ``uniq_privacy_ref``.
#   ``export_payload`` is JSON text (``fs_rows`` kind ``json``).
# * ``erasure_ledger/{id}`` -- system, append-only (``revoke_app_writes``); ``subject_hash`` hex.
# * ``retention_policies/{id}`` -- read-only platform config (``audit.read``). Postgres stays the
#   source for the ``maint.*`` purge SQL until P7; re-run the backfill after a migration that
#   changes the table.
# * ``break_glass_sessions/{id}`` -- shared, ``breakglass.activate`` for read and write.

from app.modules.admin.fs_rows import FsRow  # noqa: E402

PRIVACY = "privacy_requests"
ERASURE_LEDGER = "erasure_ledger"
RETENTION = "retention_policies"
BREAK_GLASS = "break_glass_sessions"
PRIVACY_PERM = "privacy.request.process"
BREAK_GLASS_PERM = "breakglass.activate"
PRIVACY_REF_NS = "privacy_ref"

register_collection(
    CollectionSpec(PRIVACY, "owned", read_permission=PRIVACY_PERM, write_permission=PRIVACY_PERM)
)
register_collection(CollectionSpec(ERASURE_LEDGER, "system", append_only=True))
register_collection(CollectionSpec(RETENTION, "shared", read_permission="audit.read"))
register_collection(
    CollectionSpec(BREAK_GLASS, "shared", read_permission=BREAK_GLASS_PERM, write_permission=BREAK_GLASS_PERM)
)


class PrivacyRow(FsRow):
    KINDS = {
        "id": "uuid",
        "request_ref": "str",
        "user_id": "uuid",
        "requested_by": "uuid",
        "requester_relationship": "str",
        "organization_id": "uuid",
        "request_type": "str",
        "status": "str",
        "details": "str",
        "identity_verification_method": "str",
        "identity_verified_at": "dt",
        "received_at": "dt",
        "due_at": "dt",
        "cooling_off_until": "dt",
        "completed_at": "dt",
        "response_summary": "str",
        "export_job_id": "uuid",
        "export_payload": "json",
        "assigned_to": "uuid",
        "legal_hold": "bool",
        "idempotency_key": "str",
        "created_at": "dt",
        "updated_at": "dt",
    }
    DEFAULTS = {"requester_relationship": "self", "status": "received", "legal_hold": False}


class ErasureLedgerRow(FsRow):
    KINDS = {
        "id": "uuid",
        "privacy_request_id": "uuid",
        "subject_hash": "hex",
        "erased_at": "dt",
        "scope": "json",
        "pending_modules": "list",
    }
    DEFAULTS = {"pending_modules": []}


class RetentionRow(FsRow):
    KINDS = {
        "id": "uuid",
        "data_category": "str",
        "table_name": "str",
        "retention_class": "str",
        "retention_interval": "interval",
        "basis": "str",
        "deletion_method": "str",
        "legal_hold_aware": "bool",
        "job_name": "str",
        "owner_module": "str",
        "is_active": "bool",
        "updated_by": "uuid",
        "created_at": "dt",
        "updated_at": "dt",
    }


class BreakGlassRow(FsRow):
    KINDS = {
        "id": "uuid",
        "user_id": "uuid",
        "reason": "str",
        "elevated_role": "str",
        "role_grant_id": "uuid",
        "status": "str",
        "started_at": "dt",
        "expires_at": "dt",
        "ended_at": "dt",
        "end_reason": "str",
        "ended_by": "uuid",
        "review_due_at": "dt",
        "reviewed_by": "uuid",
        "reviewed_at": "dt",
        "review_note": "str",
        "created_at": "dt",
        "updated_at": "dt",
    }
    DEFAULTS = {"elevated_role": "super_admin", "status": "active"}


from app.modules.admin.intervals import components_sql as _components_sql  # noqa: E402

_IV_SQL = _components_sql("r.retention_interval")
_RETENTION_SQL = f"(SELECT r.*, {_IV_SQL} FROM retention_policies r) AS rp"  # noqa: S608 - static


def _row_mapping(table: str, coll: str, cls: type[FsRow]) -> None:
    register_mapping(
        TableMapping("admin", table, coll, lambda r: str(r["id"]), lambda r: cls.from_pg(r).doc())
    )


_row_mapping("privacy_requests", PRIVACY, PrivacyRow)
_row_mapping("erasure_ledger", ERASURE_LEDGER, ErasureLedgerRow)


# retention_interval is read with its (months, days, microseconds) components: asyncpg's
# timedelta would turn '1 year' into 365 days (admin.intervals).
def _retention_doc(r: Row) -> dict[str, Any]:
    from app.modules.admin.intervals import from_components

    return RetentionRow.from_pg({**r, "retention_interval": from_components(r)}).doc()


register_mapping(
    TableMapping(
        "admin",
        _RETENTION_SQL,
        RETENTION,
        lambda r: str(r["id"]),
        _retention_doc,
    )
)
_row_mapping("break_glass_sessions", BREAK_GLASS, BreakGlassRow)


# --------------------------------------------------------------------------- student records
# Admin > Users "Student type" and the Excel import (2026-11-14): ``student_records/{user_id}`` holds
# what the LMS account itself has no field for -- ``student_type`` (``course`` / ``internship``),
# college / branch / year and the internship start / end dates. Optional: an account without a
# record is a regular (course) learner, so older accounts need no backfill. Written by the named
# job ``admin.students`` after the route's ``user.invite`` check; read with ``user.read``.

STUDENT_RECORDS = "student_records"
register_collection(
    CollectionSpec(STUDENT_RECORDS, "shared", read_permission="user.read", write_permission="user.invite")
)
