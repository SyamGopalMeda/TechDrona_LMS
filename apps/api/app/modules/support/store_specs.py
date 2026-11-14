"""Firestore collections of the support module (MIGRATION-PLAN P2; ``TD_STORE_SUPPORT``).

* ``support_tickets/{id}`` — the ticket row. Family ``owned`` on ``requester_id`` (Postgres
  ``p_custom``: ``requester_id = app.user_id() OR app.is_platform()``).
* ``support_ticket_messages/{id}`` — one document per message, with the ticket's
  ``requester_id`` copied in (Postgres "RLS via ticket": the same predicate on the parent). No
  delete path (td_app has no DELETE); erasure redacts in place.
* ``support_user_notes/{id}`` — ``system`` + append-only (Postgres: platform-only RLS, no UPDATE
  or DELETE for td_app). Read and written only by named jobs after the route checks.
* ``corporate_enquiries/{id}`` — ``system`` (Postgres: ``app.is_platform()`` only; no DELETE).
* ``support_counters/{support_ticket|corporate_enquiry}`` — ``{value}``: the gap-free number
  sequences (``tx.next_sequence(..., collection=support_counters)``), seeded by the backfill from
  ``support_ticket_number_seq`` / ``corporate_enquiry_number_seq``. Ticket numbers and enquiry
  references are allocated in the same transaction as the row they name.
"""

from __future__ import annotations

from typing import Any

from app.core.firestore.backfill import Row, TableMapping, register_mapping
from app.core.firestore.collections import CollectionSpec, register_collection

TICKETS = "support_tickets"
MESSAGES = "support_ticket_messages"
NOTES = "support_user_notes"
ENQUIRIES = "corporate_enquiries"
COUNTERS = "support_counters"
TICKET_SEQ = "support_ticket"
ENQUIRY_SEQ = "corporate_enquiry"

register_collection(CollectionSpec(TICKETS, "owned", owner_field="requester_id"))
register_collection(CollectionSpec(MESSAGES, "owned", owner_field="requester_id"))
register_collection(CollectionSpec(NOTES, "system", append_only=True))
register_collection(CollectionSpec(ENQUIRIES, "system"))
register_collection(CollectionSpec(COUNTERS, "system"))

TICKET_UUIDS = (
    "requester_id",
    "organization_id",
    "assigned_to",
    "related_order_id",
    "related_case_id",
    "related_unblock_request_id",
    "privacy_request_id",
    "merged_into_id",
)
TICKET_FIELDS = (
    "category",
    "subject",
    "body",
    "status",
    "priority",
    "is_grievance",
    "escalated_to",
    "context",
    "first_response_due_at",
    "resolution_due_at",
    "first_responded_at",
    "resolved_at",
    "closed_at",
    "last_message_at",
    "csat_score",
    "csat_comment",
    "csat_at",
    "ticket_number",
    "created_at",
    "updated_at",
)


def _opt(v: Any) -> str | None:
    return str(v) if v is not None else None


def ticket_doc(r: Row) -> dict[str, Any]:
    d: dict[str, Any] = {"id": str(r["id"])}
    d |= {k: _opt(r[k]) for k in TICKET_UUIDS}
    d |= {k: r[k] for k in TICKET_FIELDS}
    d["context"] = dict(r["context"] or {})
    d["is_grievance"] = bool(r["is_grievance"])
    return d


def message_doc(r: Row) -> dict[str, Any]:
    return {
        "id": str(r["id"]),
        "support_ticket_id": str(r["support_ticket_id"]),
        "requester_id": str(r["requester_id"]),
        "organization_id": _opt(r["organization_id"]),
        "author_id": _opt(r["author_id"]),
        "author_kind": r["author_kind"],
        "visibility": r["visibility"],
        "body": r["body"],
        "attachments": list(r["attachments"] or []),
        "redacted_at": r["redacted_at"],
        "created_at": r["created_at"],
    }


def note_doc(r: Row) -> dict[str, Any]:
    return {
        "id": str(r["id"]),
        "user_id": str(r["user_id"]),
        "author_id": str(r["author_id"]),
        "support_ticket_id": _opt(r["support_ticket_id"]),
        "body": r["body"],
        "created_at": r["created_at"],
    }


ENQUIRY_FIELDS = (
    "reference",
    "name",
    "company",
    "email",
    "phone",
    "message",
    "consent_at",
    "notice_version",
    "status",
    "staff_note",
    "closed_at",
    "created_at",
    "updated_at",
)


def enquiry_doc(r: Row) -> dict[str, Any]:
    return {"id": str(r["id"]), "assigned_to": _opt(r["assigned_to"])} | {k: r[k] for k in ENQUIRY_FIELDS}


def counter_doc(r: Row) -> dict[str, Any]:
    return {"value": int(r["value"])}


register_mapping(TableMapping("support", "support_tickets", TICKETS, lambda r: str(r["id"]), ticket_doc))
register_mapping(
    TableMapping(
        "support",
        "(SELECT m.*, t.requester_id FROM support_ticket_messages m "
        "JOIN support_tickets t ON t.id = m.support_ticket_id) AS m",
        MESSAGES,
        lambda r: str(r["id"]),
        message_doc,
    )
)
register_mapping(TableMapping("support", "support_user_notes", NOTES, lambda r: str(r["id"]), note_doc))
register_mapping(
    TableMapping("support", "corporate_enquiries", ENQUIRIES, lambda r: str(r["id"]), enquiry_doc)
)
register_mapping(
    TableMapping(
        "support",
        "(SELECT 'support_ticket' AS name, CASE WHEN is_called THEN last_value ELSE 0 END AS value "
        "FROM support_ticket_number_seq UNION ALL "
        "SELECT 'corporate_enquiry', CASE WHEN is_called THEN last_value ELSE 0 END "
        "FROM corporate_enquiry_number_seq) AS c",
        COUNTERS,
        lambda r: r["name"],
        counter_doc,
        order_by="name",
    )
)
