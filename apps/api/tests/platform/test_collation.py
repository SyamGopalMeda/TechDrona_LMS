"""Postgres en_US.utf8 text ordering for Firestore paths (app.core.firestore.collation).

Ground truth: ``data/collation_glibc_en_US.json`` -- 12 lists (mixed case, accents, ligatures,
punctuation, spaces, digits, names, 6 x 300 random strings) sorted by glibc 2.41 ``en_US.UTF-8``
``strcoll`` with Postgres' ``strcmp`` tie-break, generated in a Linux shell.
"""

from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import column

from app.core.firestore import collation
from app.core.firestore.sqlstore import Interpreter

DATA = json.loads(
    (Path(__file__).parent / "data" / "collation_glibc_en_US.json").read_text(encoding="utf-8")
)["lists"]


@pytest.mark.parametrize("name", sorted(DATA))
def test_sort_key_matches_glibc_en_us(name: str) -> None:
    expected = DATA[name]
    shuffled = list(expected)
    random.Random(name).shuffle(shuffled)
    assert sorted(shuffled, key=collation.sort_key) == expected


def test_known_postgres_orderings() -> None:
    s = lambda xs: sorted(xs, key=collation.sort_key)  # noqa: E731
    assert s(["B", "a", "A", "b"]) == ["a", "A", "b", "B"]  # not code point (A < B < a < b)
    # case (level 3) outranks punctuation (level 4): glibc puts "Co-op" after "coop"
    assert s(["coop", "co-op", "co op", "Co-op"]) == ["co op", "co-op", "coop", "Co-op"]
    assert s(["résumé", "resume", "Resume"]) == ["resume", "Resume", "résumé"]
    assert s(["item 10", "item 2"]) == ["item 10", "item 2"]  # text, not natural order
    assert collation.compare("a", "B") == -1 and collation.compare("x", "x") == 0


def test_citext_and_lower() -> None:
    xs = ["Banana", "apple", "APPLE", "banana", "Apple"]
    out = sorted(xs, key=collation.citext_key)
    assert [x.lower() for x in out] == ["apple", "apple", "apple", "banana", "banana"]
    assert collation.citext_key("ÉCOLE") == collation.citext_key("école")


def test_null_ordering_like_postgres() -> None:
    vals: list[Any] = ["b", None, "A", "a"]

    def order(desc: bool, nulls: Any = None) -> list[Any]:
        return sorted(vals, key=lambda v: collation.order_key(v, desc=desc, nulls=nulls), reverse=desc)

    assert order(False) == ["a", "A", "b", None]  # ASC = NULLS LAST
    assert order(True) == [None, "b", "A", "a"]  # DESC = NULLS FIRST
    assert order(False, "first") == [None, "a", "A", "b"]
    assert order(True, "last") == ["b", "A", "a", None]
    rows = [{"k": "x", "n": 2}, {"k": None, "n": 1}, {"k": "X", "n": 1}, {"k": "x", "n": 1}]
    out = collation.sort_rows(rows, [(lambda r: r["n"], True), (lambda r: r["k"], False)])
    assert out == [{"k": "x", "n": 2}, {"k": "x", "n": 1}, {"k": "X", "n": 1}, {"k": None, "n": 1}]


def test_non_text_values_keep_natural_order() -> None:
    assert sorted([3, 1, 2], key=collation.sort_key) == [1, 2, 3]


class _FakeInterp:
    def _is_citext(self, col: Any) -> bool:
        return getattr(col, "name", "") == "email"


def _sort(order: list[Any], rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    items = [(r, r) for r in rows]
    out = Interpreter._sort(_FakeInterp(), items, order, lambda c, env: env[c.name])  # type: ignore[arg-type]
    return [r for r, _ in out]


def test_sql_engine_order_by_uses_the_collation() -> None:
    rows = [{"name": n} for n in ["b", "B", None, "a", "co-op", "coop", "A", "é"]]
    asc = [r["name"] for r in _sort([column("name").asc()], rows)]
    assert asc == ["a", "A", "b", "B", "co-op", "coop", "é", None]
    desc = [r["name"] for r in _sort([column("name").desc()], rows)]
    assert desc == [None, "é", "coop", "co-op", "B", "b", "A", "a"]
    nf = [r["name"] for r in _sort([column("name").asc().nulls_first()], rows)]
    assert nf[0] is None and nf[1:] == asc[:-1]
    emails = [{"email": e} for e in ["Bob@x", "alice@x", "ALICE@x"]]
    got = [r["email"] for r in _sort([column("email").asc()], emails)]
    assert [g.lower() for g in got] == ["alice@x", "alice@x", "bob@x"]
