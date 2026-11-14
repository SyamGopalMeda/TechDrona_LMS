"""Firestore data model of entitlements (``TD_STORE_ENTITLEMENTS=firestore``; data-content agent,
docs/firebase/agents/data-content.md).

Collections (UUIDs stay document ids):

* ``entitlements/{id}`` — the row, one document per entitlement. Family ``owned`` by ``user_id``
  (Postgres RLS ``O``: own rows, or platform). Owners never write (``owner_writes=False``): every
  change goes through the entitlements repository on a named system job, like the Postgres code,
  which mutates entitlements only inside ``as_system`` / ``system_context`` or from commerce jobs.
* ``entitlement_events/{id}`` — the append-only history (Postgres ``revoke_app_writes``), owned by
  ``user_id``. Written in the **same Firestore transaction** as the entitlement change.
* ``entitlement_sources/{kind:source_id}`` — ``{entitlement_id, user_id}``; ``kind`` is
  ``order_item`` / ``subscription`` / ``coupon_redemption``. Replaces the partial unique indexes
  ``ux_ent_order_item`` / ``ux_ent_sub`` / ``ux_ent_coupon``: the grant creates it in the same
  transaction as the entitlement, so a second grant for the same source finds the first
  (``grant`` is idempotent, ADR-0006) and two concurrent grants cannot both win.
"""

from __future__ import annotations

import uuid
from typing import Any

from app.core.firestore.backfill import Row, TableMapping, register_mapping
from app.core.firestore.collections import CollectionSpec, register_collection
from app.core.firestore.ids import compose_id

ENTS = "entitlements"
EVENTS = "entitlement_events"
SOURCES = "entitlement_sources"

READ_PERMISSION = "entitlement.read"

register_collection(
    CollectionSpec(ENTS, "owned", owner_writes=False, read_permission=READ_PERMISSION, write_permission=None)
)
register_collection(
    CollectionSpec(
        EVENTS,
        "owned",
        owner_writes=False,
        read_permission=READ_PERMISSION,
        write_permission=None,
        append_only=True,
    )
)
register_collection(CollectionSpec(SOURCES, "system"))

# Source columns with a partial unique index in Postgres -> ``entitlement_sources`` kind.
SOURCE_KINDS: tuple[tuple[str, str], ...] = (
    ("order_item_id", "order_item"),
    ("subscription_id", "subscription"),
    ("coupon_redemption_id", "coupon_redemption"),
)

ENT_FIELDS = (
    "id",
    "user_id",
    "organization_id",
    "product_id",
    "course_id",
    "feature_key",
    "source_type",
    "order_item_id",
    "subscription_id",
    "coupon_redemption_id",
    "granted_by",
    "grant_reason",
    "status",
    "starts_at",
    "ends_at",
    "grace_ends_at",
    "mentor_sessions_remaining",
    "mocks_remaining",
    "resume_reviews_remaining",
    "revoked_at",
    "revoked_by",
    "revoke_reason",
    "created_at",
    "updated_at",
)
EVENT_FIELDS = (
    "id",
    "entitlement_id",
    "user_id",
    "organization_id",
    "event_type",
    "from_status",
    "to_status",
    "delta",
    "reason",
    "actor_type",
    "actor_user_id",
    "source_ref",
    "occurred_at",
)


def source_id(kind: str, value: Any) -> str:
    return compose_id(kind, str(value))


def source_key(values: dict[str, Any]) -> str | None:
    """The ``entitlement_sources`` id of an entitlement (``None``: no unique source)."""
    for col, kind in SOURCE_KINDS:
        if values.get(col) is not None:
            return source_id(kind, values[col])
    return None


def _plain(v: Any) -> Any:
    return str(v) if isinstance(v, uuid.UUID) else v


def ent_doc(r: Row) -> dict[str, Any]:
    return {k: _plain(r.get(k)) for k in ENT_FIELDS}


def event_doc(r: Row) -> dict[str, Any]:
    out = {k: _plain(r.get(k)) for k in EVENT_FIELDS}
    out["delta"] = dict(r.get("delta") or {})
    return out


def source_doc(r: Row) -> dict[str, Any]:
    return {"entitlement_id": str(r["id"]), "user_id": str(r["user_id"])}


async def load_sources(session: Any) -> list[Row]:
    from sqlalchemy import text

    res = await session.execute(
        text(
            "SELECT id, user_id, order_item_id, subscription_id, coupon_redemption_id FROM entitlements "
            "WHERE order_item_id IS NOT NULL OR subscription_id IS NOT NULL "
            "OR coupon_redemption_id IS NOT NULL ORDER BY id"
        )
    )
    return [dict(r) for r in res.mappings().all()]


register_mapping(TableMapping("entitlements", "entitlements", ENTS, lambda r: str(r["id"]), ent_doc))
register_mapping(
    TableMapping("entitlements", "entitlement_events", EVENTS, lambda r: str(r["id"]), event_doc)
)
register_mapping(
    TableMapping(
        "entitlements",
        "entitlements",
        SOURCES,
        lambda r: source_key(r) or "",
        source_doc,
        loader=load_sources,
    )
)
