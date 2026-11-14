"""Public API of entitlements for other modules (Firestore migration).

Every read and write other modules do on ``entitlements`` / ``entitlement_events`` goes through
these functions; each runs on Postgres or Firestore per ``TD_STORE_ENTITLEMENTS`` and writes the
audit row and outbox event in the caller's session. A state change takes the row lock on
Postgres and re-reads the document in one transaction on Firestore (``service._apply``).

Mapping for today's direct selects (docs/firebase/agents/data-content.md, R3-R7):

* by id ``with_for_update()`` -> ``get_entitlement(..., for_update=True)`` (or ``lock``)
* by ``subscription_id`` -> ``for_subscription(..., for_update=True)``
* joins through ``order_items`` / ``coupon_redemptions`` -> read those ids from commerce's own
  tables, then ``for_order_items`` / ``for_coupon_redemptions``
* by ``user_id`` (+ statuses) -> ``user_entitlements``; mentoring ``_usable`` ->
  ``usable_entitlements`` / ``is_usable``
* ``GROUP BY source_type`` reports -> ``source_type_counts``
* mentoring credit-back (lock + increment + ``record_event``) -> ``credit_quota``

Commerce on Firestore (later): ``firestore_repo().grant_many_tx`` / ``transition_many_tx`` run
inside commerce's own ``ScopedTransaction`` so an order and its entitlements commit together.
"""

from __future__ import annotations

from typing import Any

from app.modules.entitlements.models import Entitlement, EntitlementEvent
from app.modules.entitlements.service import (
    PRECEDENCE,
    QUOTA_FEATURES,
    RESTRICTION_LOCKS,
    Actor,
    change_product,
    consume_quota,
    covering_scope,
    credit_quota,
    effective_state,
    enter_grace,
    entitlement_history,
    entitlement_json,
    evaluate,
    event_exists,
    expire_due,
    extend_entitlements_for_restriction,
    extend_to,
    for_coupon_redemptions,
    for_order_items,
    for_subscription,
    get_entitlement,
    grant,
    is_usable,
    lock,
    pick_winner,
    record_event,
    register_resource_parent_resolver,
    register_usage_provider,
    reinstate,
    restore,
    revoke,
    revoked_by_source,
    source_type_counts,
    suspend,
    usable_entitlements,
    usage_provider,
    user_entitlements,
)


def firestore_repo() -> Any:
    """The Firestore repository, for a caller already running a ``ScopedTransaction``
    (``grant_many_tx`` / ``transition_many_tx``). Only with ``TD_STORE_ENTITLEMENTS=firestore``."""
    from app.modules.entitlements.repo_firestore import repo

    return repo()


__all__ = [
    "PRECEDENCE",
    "QUOTA_FEATURES",
    "RESTRICTION_LOCKS",
    "Actor",
    "Entitlement",
    "EntitlementEvent",
    "change_product",
    "consume_quota",
    "covering_scope",
    "credit_quota",
    "effective_state",
    "enter_grace",
    "entitlement_history",
    "entitlement_json",
    "evaluate",
    "event_exists",
    "expire_due",
    "extend_entitlements_for_restriction",
    "extend_to",
    "firestore_repo",
    "for_coupon_redemptions",
    "for_order_items",
    "for_subscription",
    "get_entitlement",
    "grant",
    "is_usable",
    "lock",
    "pick_winner",
    "record_event",
    "register_resource_parent_resolver",
    "register_usage_provider",
    "reinstate",
    "restore",
    "revoke",
    "revoked_by_source",
    "source_type_counts",
    "suspend",
    "usable_entitlements",
    "usage_provider",
    "user_entitlements",
]
