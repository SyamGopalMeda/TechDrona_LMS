"""Security data path on Firestore (data model + backfill mappers; no repository yet).
Emulator only, no Postgres."""

from __future__ import annotations

import pytest

from app.core.db import Base
from app.core.firestore.collections import get_spec
from app.modules.security import models as m
from tests.audit.fs.support import roundtrip_module

pytestmark = pytest.mark.usefixtures("fs_env")

MODELS = [
    c
    for c in vars(m).values()
    if isinstance(c, type) and issubclass(c, Base) and c is not Base and c.__module__ == m.__name__
]


async def test_every_table_maps_and_round_trips() -> None:
    import app.modules.security.store_specs  # noqa: F401

    assert await roundtrip_module("security", MODELS) == len(MODELS) == 15


def test_families_follow_rls() -> None:
    import app.modules.security.store_specs  # noqa: F401

    assert get_spec("security_signals").family == "owned" and get_spec("security_signals").append_only
    assert get_spec("case_decisions").append_only and get_spec("risk_rule_versions").append_only
    assert get_spec("security_counters").family == "system"
    assert get_spec("unblock_requests").read_permission == "security.unblock.triage"
