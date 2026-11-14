"""Firestore data model of media playback (``TD_STORE_MEDIA=firestore``; data-content agent,
docs/firebase/agents/data-content.md). Media binaries stay on S3/VdoCipher and asset metadata
(``lesson_assets``) belongs to catalog, so the only media table is ``playback_sessions``.

* ``playback_sessions/{id}`` — one document per session, ``owned`` by ``user_id`` (Postgres RLS
  ``O``). Postgres partitions the table monthly and drops partitions after 180 days (R-PLAY,
  D11); here every document carries ``expire_at = started_at + 180 days`` and a Firestore **TTL
  policy** on ``expire_at`` deletes it (``firestore.indexes.fragment.json`` field override). The
  backfill computes the same ``expire_at``. ``provider_otp_ref_hash`` (32 bytes) is stored as hex.
* ``playback_users/{user_id}`` — ``{active_ids, starts}``: the user's active session ids and the
  start times of the last hour. It replaces ``pg_advisory_xact_lock('play:'||user_id)``: every
  issue runs one transaction that reads and rewrites this document, so the stale clean-up, the
  stream cap, the take-over and the 30-per-hour token limit are serialised per user exactly as
  under the advisory lock. It is a **derived index**, not backfilled: a missing document is
  seeded inside the first issuing transaction from the user's sessions (so verify never drifts).
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any

from app.core.firestore.backfill import Row, TableMapping, register_mapping
from app.core.firestore.collections import CollectionSpec, register_collection

PLAYBACK = "playback_sessions"
PLAYBACK_USERS = "playback_users"
RETENTION = timedelta(days=180)

register_collection(
    CollectionSpec(
        PLAYBACK, "owned", owner_writes=False, read_permission=None, write_permission=None, ttl=RETENTION
    )
)
register_collection(CollectionSpec(PLAYBACK_USERS, "system"))

FIELDS = (
    "id",
    "started_at",
    "user_id",
    "auth_session_id",
    "device_id",
    "tab_id",
    "lesson_asset_id",
    "provider",
    "provider_otp_ref_hash",
    "status",
    "otp_expires_at",
    "last_heartbeat_at",
    "last_position_s",
    "ended_at",
    "end_reason",
)


def playback_doc(r: Row) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k in FIELDS:
        v = r.get(k)
        if isinstance(v, uuid.UUID):
            v = str(v)
        elif isinstance(v, (bytes, memoryview)):
            v = bytes(v).hex()
        out[k] = v
    out["expire_at"] = r["started_at"] + RETENTION
    return out


register_mapping(TableMapping("media", "playback_sessions", PLAYBACK, lambda r: str(r["id"]), playback_doc))
