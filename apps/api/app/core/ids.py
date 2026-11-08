"""Identifiers (ADR-0012): UUIDv7 generated in the application.

``uuid7()`` follows RFC 9562 §5.7 with a 12-bit monotonic counter in ``rand_a`` so ids
generated in the same millisecond by this process stay strictly increasing.
"""

from __future__ import annotations

import os
import threading
import time
import uuid

_lock = threading.Lock()
_last_ms = 0
_counter = 0

_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def uuid7() -> uuid.UUID:
    global _last_ms, _counter
    with _lock:
        ms = time.time_ns() // 1_000_000
        if ms > _last_ms:
            _last_ms = ms
            _counter = int.from_bytes(os.urandom(2), "big") & 0x7FF  # leave headroom
        else:
            ms = _last_ms
            _counter += 1
            if _counter > 0xFFF:  # counter overflow: borrow the next millisecond
                _last_ms += 1
                ms = _last_ms
                _counter = 0
        counter = _counter
    rand_b = int.from_bytes(os.urandom(8), "big") & ((1 << 62) - 1)
    value = (ms & ((1 << 48) - 1)) << 80
    value |= 0x7 << 76
    value |= counter << 64
    value |= 0b10 << 62
    value |= rand_b
    return uuid.UUID(int=value)


def uuid7_timestamp_ms(u: uuid.UUID) -> int:
    """Unix milliseconds embedded in a UUIDv7."""
    if u.version != 7:
        raise ValueError("not a UUIDv7")
    return u.int >> 80


def ulid_from_uuid(u: uuid.UUID) -> str:
    """26-char Crockford base32 rendering (used for request ids such as 01JC9V6R...)."""
    n = u.int
    out = []
    for _ in range(26):
        out.append(_CROCKFORD[n & 0x1F])
        n >>= 5
    return "".join(reversed(out))


def new_request_id() -> str:
    return ulid_from_uuid(uuid7())
