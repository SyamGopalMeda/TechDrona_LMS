"""Firestore collections of the sessions module (``TD_STORE_SESSIONS=firestore``).

Same conventions as ``identity/store_specs.py`` (one ``fs_codec`` mapper per table, Postgres
primary keys as document ids, bytea as hex):

* ``auth_sessions/{id}``   looked up per request by ``token_hash`` (single-field equality index)
* ``devices/{id}``         looked up by ``device_key_hash`` (``in`` over the keyring digests)
* ``user_devices/{id}``    owned by ``user_id``
* ``user_devices_live/{user_id:device_id}`` ``{user_device_id}``: the partial unique index
  ``ux_ud_user_device`` (``trust_status <> 'removed'``); written in the same transaction as the
  user_devices document
* ``login_attempts/{id}``, ``session_network_observations/{id}``: append-style streams (Postgres
  partitions). No TTL is set, so retention is unchanged until the purge job moves (data-ops).
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from app.core.firestore.backfill import Row, TableMapping, register_mapping
from app.core.firestore.collections import CollectionSpec, register_collection
from app.core.firestore.ids import compose_id
from app.modules.identity.fs_codec import row_doc
from app.modules.sessions.models import (
    AuthSession,
    Device,
    LoginAttempt,
    SessionNetworkObservation,
    UserDevice,
)

SESSIONS = "auth_sessions"
DEVICES = "devices"
USER_DEVICES = "user_devices"
UD_LIVE = "user_devices_live"
ATTEMPTS = "login_attempts"
OBSERVATIONS = "session_network_observations"

register_collection(
    CollectionSpec(SESSIONS, "owned", read_permission="session.read", write_permission="session.revoke")
)
register_collection(CollectionSpec(DEVICES, "system"))
register_collection(
    CollectionSpec(USER_DEVICES, "owned", read_permission="session.read", write_permission="device.reset")
)
register_collection(CollectionSpec(UD_LIVE, "system"))
# R-SEC (admin_0001 retention_policies: 395 days, CERT-In logs >= 1 year): the store stamps
# ``expire_at`` (Firestore TTL field) on insert; the backfill computes it from the row's time.
AUTH_LOG_RETENTION = timedelta(days=395)
register_collection(CollectionSpec(ATTEMPTS, "system", ttl=AUTH_LOG_RETENTION))
register_collection(CollectionSpec(OBSERVATIONS, "system", ttl=AUTH_LOG_RETENTION))


def ip_prefix(ip: Any) -> str | None:
    """The network an address belongs to for per-network checks: IPv4 /24, IPv6 /48
    (``203.0.113.0/24``, ``2001:db8:1::/48``). ``None`` for no / an invalid address."""
    import ipaddress

    if ip is None or ip == "":
        return None
    try:
        addr = ipaddress.ip_address(str(ip).split("/")[0])
    except ValueError:
        return None
    plen = 24 if addr.version == 4 else 48
    return str(ipaddress.ip_network(f"{addr}/{plen}", strict=False))


def attempt_doc(r: Row) -> dict[str, Any]:
    return {
        **row_doc(LoginAttempt, r),
        "expire_at": r["attempted_at"] + AUTH_LOG_RETENTION,
        # Firestore-only index field (no Postgres column): the attempt's /24 or /48 network
        "ip_prefix": ip_prefix(r.get("ip")),
    }


def observation_doc(r: Row) -> dict[str, Any]:
    return {**row_doc(SessionNetworkObservation, r), "expire_at": r["first_seen_at"] + AUTH_LOG_RETENTION}


def live_id(user_id: object, device_id: object) -> str:
    return compose_id(str(user_id), str(device_id))


for _model, _coll in (
    (AuthSession, SESSIONS),
    (Device, DEVICES),
    (UserDevice, USER_DEVICES),
):
    register_mapping(
        TableMapping(
            "sessions",
            _model.__tablename__,
            _coll,
            lambda r: str(r["id"]),
            (lambda m: lambda r: row_doc(m, r))(_model),
        )
    )
register_mapping(
    TableMapping(
        "sessions",
        "user_devices",
        UD_LIVE,
        lambda r: live_id(r["user_id"], r["device_id"]),
        lambda r: {"user_device_id": str(r["id"])},
        where="trust_status <> 'removed'",
    )
)
register_mapping(TableMapping("sessions", "login_attempts", ATTEMPTS, lambda r: str(r["id"]), attempt_doc))
register_mapping(
    TableMapping(
        "sessions", "session_network_observations", OBSERVATIONS, lambda r: str(r["id"]), observation_doc
    )
)
