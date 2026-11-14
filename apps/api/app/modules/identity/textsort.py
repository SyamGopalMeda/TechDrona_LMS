"""Text ordering on the Firestore path that matches the VM database's collation.

Postgres sorts ``text`` with the cluster collation (``en_US.utf8``, glibc), not by code point.
Firestore paths that must return rows in the order the SQL ``ORDER BY`` gave use ``text_key``.
It delegates to the platform's shared ``app.core.firestore.collation.sort_key`` (being built by
the platform agent); until that module exists it falls back to plain code-point order, which is
identical for the ASCII lower-case keys (role keys, batch codes) and may differ for mixed-case
or accented names -- see docs/firebase/agents/data-access.md §13.
"""

from __future__ import annotations

from typing import Any


def text_key(value: str | None) -> Any:
    """Sort key for one text value (``None`` is the caller's NULLS FIRST/LAST decision)."""
    try:
        from app.core.firestore.collation import sort_key  # type: ignore[import-not-found,unused-ignore]
    except ImportError:
        return value or ""
    return sort_key(value or "")
