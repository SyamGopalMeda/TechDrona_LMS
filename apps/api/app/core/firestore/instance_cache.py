"""Short per-process cache of rarely written Firestore data (latency: one fewer round trip).

For data read on hot paths but changed rarely by an admin (policy settings): a value is kept for
``ttl`` seconds and dropped at once when THIS process writes any document of a collection it was
read from (``bump``, called by ``request_memo.forget`` on every write the store sends). Another
instance's write is seen after at most ``ttl`` seconds -- only use this where that delay is
acceptable (settings), never for revocation / permission state.

Entries are kept per Firestore client (a new client -- another project, a wiped test emulator --
starts empty) and values are deep-copied in and out.
"""

from __future__ import annotations

import copy
import time
import weakref
from collections.abc import Sequence
from typing import Any

MISSING: Any = object()

_Entry = tuple[float, tuple[str, ...], tuple[int, ...], Any]  # (expires, physical, generations, value)

_generation: dict[str, int] = {}


def bump(physical: str) -> None:
    """A write to ``physical`` is about to be sent (invalidates cached reads of it)."""
    _generation[physical] = _generation.get(physical, 0) + 1


def generations(physical: Sequence[str]) -> tuple[int, ...]:
    return tuple(_generation.get(p, 0) for p in physical)


class TtlCache:
    def __init__(self, ttl: float, *, max_entries: int = 2048) -> None:
        self.ttl = ttl
        self.max_entries = max_entries
        self._by_client: weakref.WeakKeyDictionary[Any, dict[Any, _Entry]] = weakref.WeakKeyDictionary()

    def _entries(self, client: Any) -> dict[Any, _Entry]:
        try:
            return self._by_client.setdefault(client, {})
        except TypeError:  # not weak-referenceable: no caching
            return {}

    def get(self, client: Any, key: Any, physical: Sequence[str]) -> Any:
        hit = self._entries(client).get(key)
        if hit is None:
            return MISSING
        expires, phys, gens, value = hit
        if time.monotonic() >= expires or generations(phys) != gens:
            self._entries(client).pop(key, None)
            return MISSING
        return copy.deepcopy(value)

    def put(self, client: Any, key: Any, physical: Sequence[str], gens: tuple[int, ...], value: Any) -> None:
        """``gens``: ``generations(physical)`` taken BEFORE the read (a write racing the read
        leaves the entry already stale)."""
        entries = self._entries(client)
        if len(entries) >= self.max_entries:
            entries.clear()
        entries[key] = (time.monotonic() + self.ttl, tuple(physical), gens, copy.deepcopy(value))

    def clear(self) -> None:
        self._by_client = weakref.WeakKeyDictionary()
