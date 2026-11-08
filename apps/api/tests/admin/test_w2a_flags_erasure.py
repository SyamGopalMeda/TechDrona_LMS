"""w2a admin fixes: the cached flag reader for session-less consumers (ADM-17 / core R5) and
``mentoring`` as a required erasure module (DB-01, learn R11)."""

from __future__ import annotations

import uuid

from app.modules.admin import flags
from app.modules.admin import privacy as prv
from tests.security.helpers import staff, staff_browser

KEY = "risk.fingerprint_collection"


def test_evaluate_rule() -> None:
    u = uuid.uuid4()
    snap = flags.FlagSnapshot(True, 0, frozenset({u}))
    assert flags.evaluate(snap) is False  # 0 % is off, also for anonymous callers
    assert flags.evaluate(snap, user_id=uuid.uuid4()) is False
    assert flags.evaluate(snap, user_id=u) is True  # allowlist wins
    assert flags.evaluate(flags.FlagSnapshot(True, 100, frozenset())) is True
    assert flags.evaluate(flags.FlagSnapshot(False, 100, frozenset())) is False
    assert flags.evaluate(None) is False
    assert flags.evaluate(snap, org_id=uuid.uuid4()) is False  # no org allowlist any more


async def test_cached_reader_caches_and_patch_invalidates(client, db) -> None:
    flags.invalidate()
    try:
        assert await flags.cached_flag_enabled(KEY) is False  # seeded off
        sa = await staff(db, "super_admin")
        bsa = await staff_browser(client, sa, ip="198.18.3.21")
        r = await bsa.patch(f"/admin/feature-flags/{KEY}", {"is_enabled": True, "rollout_percent": 100})
        assert r.status_code == 200, r.text
        assert await flags.cached_flag_enabled(KEY) is True  # the PATCH cleared the cache
        flags._cache[KEY] = (flags._cache[KEY][0], flags.FlagSnapshot(False, 0, frozenset()))
        assert await flags.cached_flag_enabled(KEY) is False  # served from the cache within the TTL
        flags._cache[KEY] = (flags._cache[KEY][0] - flags.CACHE_TTL_S, flags._cache[KEY][1])
        assert await flags.cached_flag_enabled(KEY) is True  # expired entry is re-read
        await bsa.patch(f"/admin/feature-flags/{KEY}", {"is_enabled": False, "rollout_percent": 0})
    finally:
        flags.invalidate()


async def test_mentoring_is_a_required_erasure_module(app) -> None:
    assert "mentoring" in prv.REQUIRED_ERASURE_MODULES
    providers = prv.erasure_providers()
    assert set(prv.REQUIRED_ERASURE_MODULES) <= set(providers), set(prv.REQUIRED_ERASURE_MODULES) - set(
        providers
    )
