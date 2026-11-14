"""Firestore paths sort text like the VM's Postgres (glibc ``en_US.utf8``) via
``app.core.firestore.collation``: not by code point (``"Zeta" < "beta"``)."""

from __future__ import annotations

from typing import Any

import pytest

from app.core.ids import uuid7
from app.core.principal import Principal
from app.modules.placement import bank, banks
from app.modules.placement.schemas import BankCreate, CompanyCreate, TopicCreate

pytestmark = pytest.mark.usefixtures("placement_fs")

NAMES = ["Zeta", "beta", "Alpha", "co-op", "co op", "coop", "éclair", "Echo"]
# glibc en_US.UTF-8: case-insensitive first, punctuation/space ignored then tie-broken, accents
# after the base letters; code-point order would be Alpha, Echo, Zeta, beta, co op, ...
EXPECTED = ["Alpha", "beta", "co op", "co-op", "coop", "Echo", "éclair", "Zeta"]


def _p() -> Principal:
    return Principal(user_id=uuid7(), session_id=uuid7(), grants=())


async def test_companies_sorted_by_postgres_collation(fake_session: Any) -> None:
    for i, n in enumerate(NAMES):
        await bank.create_company(fake_session, CompanyCreate(slug=f"c{i}", name=n))
    assert [c["name"] for c in await bank.list_companies(fake_session)] == EXPECTED


async def test_subject_tree_siblings_sorted_by_name(fake_session: Any) -> None:
    for i, n in enumerate(NAMES):
        await bank.create_topic(fake_session, TopicCreate(slug=f"t{i}", name=n, position=0))
    assert [n["name"] for n in await bank.subject_tree(fake_session)] == EXPECTED


async def test_bank_list_sorted_by_lower_name(fake_session: Any) -> None:
    for n in NAMES:
        await banks.create_bank(fake_session, _p(), BankCreate(name=n))
    out = await banks.list_banks(fake_session, organization_ids=[None], sort="name")
    assert [b["name"] for b in out["items"]] == EXPECTED
