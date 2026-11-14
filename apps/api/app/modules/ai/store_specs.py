"""Firestore collections of the AI settings slice (MIGRATION-PLAN P2; docs/firebase/p2.md).

Moved with ``TD_STORE_AI=firestore``: the platform singletons ``ai_settings`` and
``app_settings``. The usage ledger (``ai_usage``: reserve/finalise caps), tutor history and the
per-learner quota stay on Postgres for now (see p2.md "not moved yet").

* ``ai_settings/platform`` — the ``ai_settings`` row ``id = 1`` (absent = code defaults).
* ``app_settings/platform`` — ``{apps: {app_key: enabled}, updated_by: {app_key: uid}}``: one
  read per gate check instead of one per app (Spark read quota). Absent key = enabled.

Postgres RLS on both tables was "platform only (services read via system context)"; reads go
through the ``ai.settings`` system job, writes through ``ScopedStore(principal)`` with the
route's permission (``feature_flag.manage``) or the ``ai.settings`` job for seeds and fixtures.
"""

from __future__ import annotations

from typing import Any

from app.core.firestore.backfill import Row, TableMapping, register_mapping
from app.core.firestore.collections import CollectionSpec, register_collection

AI_SETTINGS = "ai_settings"
APP_SETTINGS = "app_settings"
PLATFORM_DOC = "platform"
SETTINGS_PERM = "feature_flag.manage"

register_collection(
    CollectionSpec(AI_SETTINGS, "shared", read_permission=SETTINGS_PERM, write_permission=SETTINGS_PERM)
)
register_collection(
    CollectionSpec(APP_SETTINGS, "shared", read_permission=SETTINGS_PERM, write_permission=SETTINGS_PERM)
)

SETTING_FIELDS = (
    "enabled",
    "model",
    "monthly_token_cap",
    "monthly_call_cap",
    "per_activity_default_cap",
    "tutor_per_minute",
    "tutor_per_day",
    "generate_per_hour",
    "generate_per_day",
)


def ai_settings_doc(r: Row) -> dict[str, Any]:
    return {
        **{f: r[f] for f in SETTING_FIELDS},
        "updated_by": str(r["updated_by"]) if r["updated_by"] else None,
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
    }


def app_setting_doc(r: Row) -> dict[str, Any]:
    return {
        "apps": {r["app_key"]: bool(r["enabled"])},
        "updated_by": {r["app_key"]: str(r["updated_by"]) if r["updated_by"] else None},
    }


register_mapping(
    TableMapping("ai", "ai_settings", AI_SETTINGS, lambda r: PLATFORM_DOC, ai_settings_doc, where="id = 1")
)
register_mapping(
    TableMapping(
        "ai", "app_settings", APP_SETTINGS, lambda r: PLATFORM_DOC, app_setting_doc, order_by="app_key"
    )
)


# Usage ledger, quota and tutor history (data-ops agent): same switch, registered on import.
from app.modules.ai import store_specs_usage as _usage  # noqa: E402, F401
