"""Name ordering parity (round 8): ``identity.public.users_ordered_by_full_name`` (batch student
lists) and the other Firestore text sorts of the access modules order like the VM database
(``ORDER BY full_name NULLS LAST, user_id`` with the ``en_US.utf8`` collation).

On Postgres the ORDER BY runs in SQL (unchanged collation). On Firestore the order comes from
``identity.textsort.text_key``, which uses the platform's shared ``core.firestore.collation``
when it exists; the collation-specific expectations below are skipped until then."""

from __future__ import annotations

import importlib.util
import uuid
from typing import Any

import pytest

from app.core.ids import uuid7
from app.modules.identity import public as ipub
from app.modules.identity.models import User, UserProfile
from app.modules.identity.repo_firestore import system_repo

S: Any = None
HAS_COLLATION = importlib.util.find_spec("app.core.firestore.collation") is not None


async def _user(name: str | None) -> uuid.UUID:
    uid = uuid7()
    profile = UserProfile(user_id=uid, full_name=name) if name is not None else None
    await system_repo().create_user(User(id=uid, email=None, status="active", is_minor=False), profile)
    return uid


async def test_nulls_last_and_equal_names_by_id(fs: Any) -> None:
    ids = {n: await _user(n) for n in ("Carol", "Asha")}
    twin_a, twin_b = await _user("Ravi"), await _user("Ravi")
    nameless = await _user(None)
    got = await ipub.users_ordered_by_full_name(S, [nameless, twin_b, ids["Carol"], twin_a, ids["Asha"]])
    names = [n for _u, n in got]
    assert names == ["Asha", "Carol", "Ravi", "Ravi", None]
    ravis = [u for u, n in got if n == "Ravi"]
    assert ravis == sorted([twin_a, twin_b], key=lambda u: u.bytes)  # tie-breaker: user_id
    assert got[-1][0] == nameless
    assert await ipub.users_ordered_by_full_name(S, []) == []


@pytest.mark.skipif(not HAS_COLLATION, reason="waiting for app.core.firestore.collation (platform)")
async def test_collation_case_accents_spaces(fs: Any) -> None:
    """glibc en_US.utf8: case and accents are secondary/tertiary differences (``alice`` and
    ``Álice`` sort together with ``Alice``, lower case first), not code-point order."""
    from app.core.firestore.collation import sort_key  # type: ignore[import-not-found,unused-ignore]

    names = ["Zoe", "álice", "Bob", "alice", "Alice", "bob smith", "Bobby", "Álice", "o'neil", "O'Neil"]
    uids = [await _user(n) for n in names]
    got = [n for _u, n in await ipub.users_ordered_by_full_name(S, uids)]
    assert got == sorted(names, key=sort_key)
    assert got.index("alice") < got.index("Bob") and got.index("Álice") < got.index("Bob")
    assert got[-1] == "Zoe"
