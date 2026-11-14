"""Postgres text ordering for in-memory sorts on Firestore data (cross-cutting parity, round 4).

The VM database is the official ``postgres:16-bookworm`` image (``infra/docker/postgres``) with
no ``POSTGRES_INITDB_ARGS`` and no ``COLLATE`` in any migration, so every ``text`` column sorts
by the cluster default: **libc ``en_US.utf8``** (glibc ISO 14651 tables), and ``citext`` compares
``lower(a)`` with ``lower(b)`` under the same collation. Postgres then breaks collation ties
with a plain byte comparison (``varstr_cmp``: deterministic collations).

``sort_key(value)`` reproduces that order:

* **exact** -- when the process has the glibc ``en_US.UTF-8`` locale (Linux with the locale
  installed): ``locale.strxfrm`` + the code-point tie-break, i.e. what Postgres does;
* **emulated** otherwise (Windows dev machines, minimal Cloud Functions images): the Unicode
  Collation Algorithm (``pyuca``, DUCET 10.0) with *shifted* variable weighting -- spaces and
  punctuation are ignored on levels 1-3 and only break ties on level 4, exactly the glibc
  behaviour (``"co op" < "co-op" < "coop"``; ``"a b" < "ab"``) -- then lower case before upper
  case, accents compared forwards, then the code-point tie-break. Verified identical to glibc
  2.41 ``en_US.UTF-8`` on the corpus in ``tests/platform/test_collation.py`` (generated with
  ``locale.strcoll`` in a Linux shell). Known, documented differences of the emulation: glibc's
  table is ISO 14651 (Unicode 13+ in recent glibc) vs DUCET 10.0, so rare scripts/symbols added
  after Unicode 10 and some CJK compatibility forms may order differently.

Helpers:

* ``sort_key(v)`` / ``citext_key(v)`` (``lower()`` first, as ``citext`` does; ``lower`` uses
  Python's Unicode lower-casing, which equals glibc's ``tolower`` for every cased letter in use);
* ``null_key(v, desc=False, nulls=None)`` -- Postgres NULL placement: ``ASC`` = NULLS LAST,
  ``DESC`` = NULLS FIRST, overridable with ``nulls="first"|"last"``;
* ``order_key(v, desc=False, nulls=None, citext=False)`` -- one key usable with
  ``sorted(..., key=..., reverse=desc)``;
* ``compare(a, b)`` -- -1/0/1 like ``strcmp`` under the collation (for comparators).

Non-text values (numbers, dates, UUIDs, bools) keep their natural order; only ``str`` goes
through the collation.
"""

from __future__ import annotations

import locale
import threading
import unicodedata
from functools import lru_cache
from typing import Any, Literal

Nulls = Literal["first", "last"] | None
_LOCALES = ("en_US.UTF-8", "en_US.utf8")
_lock = threading.Lock()
_mode: str | None = None  # "glibc" | "uca"


def _init() -> str:
    global _mode
    if _mode is not None:
        return _mode
    with _lock:
        if _mode is None:
            mode = "uca"
            import sys

            if sys.platform.startswith("linux"):
                for name in _LOCALES:
                    try:
                        locale.setlocale(locale.LC_COLLATE, name)
                        mode = "glibc"
                        break
                    except locale.Error:
                        continue
            _mode = mode
    return _mode


def mode() -> str:
    """``glibc`` (exact) or ``uca`` (emulated); see the module docstring."""
    return _init()


# --------------------------------------------------------------------------- UCA (shifted) emulation


# glibc en_US.UTF-8 level-4 order of the ignorable characters (measured with ``locale.strxfrm``
# on glibc 2.41: ASCII punctuation in code-point order, then the common typographic marks). DUCET
# orders them differently (e.g. ``-`` before ``#``), so their level-4 weight is this rank; other
# variable characters keep their DUCET primary (after these).
GLIBC_SHIFTED_ORDER = "".join(
    [chr(c) for c in range(0x20, 0x7F) if not chr(c).isalnum() and chr(c) != "$"]
    + [chr(c) for c in (0xA0, 0xA7, 0xA9, 0xAE, 0xB0, 0xB1, 0xB6, 0xB7, 0xD7, 0xF7)]
    + [chr(c) for c in (0x2013, 0x2014, 0x2018, 0x2019, 0x201C, 0x201D, 0x2022, 0x2026)]
)


@lru_cache(maxsize=1)
def _collator() -> tuple[Any, int, dict[int, int]]:
    import os

    import pyuca

    c = pyuca.Collator()
    # Highest primary weight of a *variable* element (``[*....]`` in allkeys.txt): spaces,
    # punctuation and symbols. Elements at or below it are "shifted" (ignored on levels 1-3).
    path = os.path.join(os.path.dirname(pyuca.__file__), f"allkeys-{c.UCA_VERSION}.txt")
    top = 0
    with open(path, encoding="utf-8") as f:
        for line in f:
            body = line.split("#", 1)[0]
            if "[*" not in body:
                continue
            for part in body.split("[*")[1:]:
                top = max(top, int(part.split(".", 1)[0], 16))
    ranks: dict[int, int] = {}
    for i, ch in enumerate(GLIBC_SHIFTED_ORDER):
        ces = c.collation_elements([ch])
        if len(ces) == 1 and 0 < ces[0][0] <= top:
            ranks.setdefault(ces[0][0], i + 1)
    return c, top, ranks


@lru_cache(maxsize=65536)
def _uca_key(s: str) -> tuple[Any, ...]:
    c, top, ranks = _collator()
    ces = c.collation_elements(unicodedata.normalize("NFD", s))
    l1: list[int] = []
    l2: list[int] = []
    l3: list[int] = []
    l4: list[int] = []
    after_variable = False
    for ce in ces:
        p = ce[0] if ce else 0
        s2 = ce[1] if len(ce) > 1 else 0
        s3 = ce[2] if len(ce) > 2 else 0
        if p != 0 and p <= top:  # variable: shifted to level 4 (glibc rank when known)
            l4.append(ranks.get(p, 0x1000 + p))
            after_variable = True
            continue
        if p == 0 and after_variable:  # ignorable following a variable: ignored completely
            continue
        after_variable = False
        if p:
            l1.append(p)
            l4.append(0xFFFF)
        if s2:
            l2.append(s2)
        if s3:
            l3.append(s3)
    return (tuple(l1), tuple(l2), tuple(l3), tuple(l4))


# --------------------------------------------------------------------------- public API


def collate_key(s: str) -> tuple[Any, ...]:
    """Collation key of one string (no tie-break)."""
    if _init() == "glibc":
        return (locale.strxfrm(s),)
    return _uca_key(s)


def sort_key(value: Any) -> Any:
    """Postgres ``ORDER BY`` key of a text value: collation, then the byte tie-break.
    Non-strings are returned unchanged (natural order)."""
    if isinstance(value, str):
        return (collate_key(value), value.encode("utf-8"))
    return value


def citext_key(value: Any) -> Any:
    """``citext`` / ``ORDER BY lower(x)``: the collation of the lower-cased value."""
    if isinstance(value, str):
        low = value.lower()
        return (collate_key(low), low.encode("utf-8"))
    return value


def compare(a: str, b: str) -> int:
    ka, kb = sort_key(a), sort_key(b)
    return (ka > kb) - (ka < kb)


def null_key(value: Any, *, desc: bool = False, nulls: Nulls = None) -> int:
    """Rank for NULL placement in a key used with ``reverse=desc``: Postgres default is NULLS
    LAST for ASC and NULLS FIRST for DESC (both = "NULL is larger than every value")."""
    if nulls is None:
        nulls = "first" if desc else "last"
    is_null = value is None
    # reverse=desc flips the rank, so pre-flip it to land where requested.
    want_last = nulls == "last"
    big = want_last != desc
    return (1 if is_null else 0) if big else (0 if is_null else 1)


def order_key(
    value: Any, *, desc: bool = False, nulls: Nulls = None, citext: bool = False
) -> tuple[Any, ...]:
    """Key for ``sorted(rows, key=lambda r: order_key(r[col], desc=d), reverse=d)``."""
    rank = null_key(value, desc=desc, nulls=nulls)
    if value is None:
        return (rank,)
    return (rank, citext_key(value) if citext else sort_key(value))


def sort_rows(
    rows: list[Any], keys: list[tuple[Any, bool]], *, nulls: dict[int, Nulls] | None = None
) -> list[Any]:
    """Multi-column ``ORDER BY``: ``keys`` = [(getter, desc), ...]; stable sorts from the last
    key to the first (each column may have its own direction and NULL placement)."""
    out = list(rows)
    for i in range(len(keys) - 1, -1, -1):
        get, desc = keys[i]
        nl: Nulls = (nulls or {}).get(i)

        def key(r: Any, g: Any = get, d: bool = desc, n: Nulls = nl) -> tuple[Any, ...]:
            return order_key(g(r), desc=d, nulls=n)

        out.sort(key=key, reverse=desc)
    return out
