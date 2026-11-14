"""Firestore collections of the audit module (MIGRATION-PLAN §3.5; docs/firebase/agents/data-ops.md).

Moved with ``TD_STORE_AUDIT=firestore`` (the hash-chained log, its head and the Firestore outbox):

* ``audit_outbox/{uuid}`` -- ``{id, occurred_at, record_json}``: one pending audit record, written
  in the same Firestore transaction as the business write (``repo_firestore.enqueue``). ``record``
  is kept as canonical JSON text so nested arrays (not storable in Firestore), big integers and the
  int/float distinction survive exactly as in the Postgres JSONB. System family, append-only:
  only the sealer (a named system job) deletes.
* ``audit_log/{seq:012d}`` -- one sealed row with every ``AuditLog`` column. ``prev_hash`` /
  ``row_hash`` are 64-char hex strings; ``before_state`` / ``after_state`` are JSON text
  (``*_json``) for the same reason as the outbox. ``occurred_at`` is a Timestamp (microsecond
  precision) plus ``occurred_at_s`` (RFC 3339 micro string, the exact hash input). Read needs
  ``audit.read``; no principal may write; append-only.
* ``audit_meta/head`` -- ``{seq, row_hash, last_pg_ids}``: the chain head, updated in the same
  transaction as the appended rows, so ``seq`` stays gap-free. ``last_pg_ids`` = ids of the last
  batch drained from the Postgres outbox (cross-store re-delivery guard, see ``sealer.py``).

The Postgres ``audit_outbox`` is not backfilled: the app role can only INSERT into it, and the
sealer drains it into whichever chain is active (stop the sealer, backfill, flip, restart).
"""

from __future__ import annotations

import json
from typing import Any

from app.core.firestore.backfill import Row, TableMapping, register_mapping
from app.core.firestore.collections import CollectionSpec, register_collection
from app.core.time import to_rfc3339_micro

OUTBOX = "audit_outbox"
LOG = "audit_log"
META = "audit_meta"
HEAD = "head"
READ_PERM = "audit.read"

register_collection(CollectionSpec(OUTBOX, "system", append_only=True))
register_collection(CollectionSpec(LOG, "shared", read_permission=READ_PERM, append_only=True))
register_collection(CollectionSpec(META, "system"))

UUID_FIELDS = ("id", "actor_user_id", "actor_session_id", "target_id", "organization_id", "subject_user_id")
RECORD_FIELDS = (
    "actor_type",
    "actor_user_id",
    "actor_session_id",
    "actor_roles",
    "action",
    "target_type",
    "target_id",
    "organization_id",
    "subject_user_id",
    "reason_code",
    "reason",
    "before_state",
    "after_state",
    "request_id",
    "ip",
)


def log_id(seq: int) -> str:
    return f"{int(seq):012d}"


def dump_json(v: Any) -> str | None:
    """JSON text for a JSONB value (``None`` stays ``None``, so SQL NULL != JSON null is kept)."""
    return None if v is None else json.dumps(v, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def load_json(v: str | None) -> Any:
    return None if v is None else json.loads(v)


def _opt(v: Any) -> str | None:
    return None if v is None else str(v)


def log_doc(r: Row) -> dict[str, Any]:
    """``audit_log`` row (or a freshly sealed row dict) -> document."""
    out: dict[str, Any] = {
        "seq": int(r["seq"]),
        "occurred_at": r["occurred_at"],
        "occurred_at_s": to_rfc3339_micro(r["occurred_at"]),
        "actor_roles": list(r.get("actor_roles") or []),
        "before_state_json": dump_json(r.get("before_state")),
        "after_state_json": dump_json(r.get("after_state")),
        "prev_hash": bytes(r["prev_hash"]).hex(),
        "row_hash": bytes(r["row_hash"]).hex(),
    }
    for f in RECORD_FIELDS:
        if f not in ("actor_roles", "before_state", "after_state"):
            out[f] = _opt(r.get(f))
    out["id"] = str(r["id"])
    return out


def head_doc(r: Row) -> dict[str, Any]:
    return {"seq": int(r["seq"]), "row_hash": bytes(r["row_hash"]).hex()}


register_mapping(TableMapping("audit", "audit_log", LOG, lambda r: log_id(r["seq"]), log_doc, order_by="seq"))
register_mapping(
    TableMapping(
        "audit",
        "(SELECT seq, row_hash FROM audit_log ORDER BY seq DESC LIMIT 1) AS head",
        META,
        lambda r: HEAD,
        head_doc,
        order_by="seq",
    )
)
