"""Keep Firestore in step after a dev/demo seed (owner decision F1: demo data is reseeded).

Seeds write their demo rows to Postgres (they cross module boundaries by design). After a seed,
every module it touched that runs on Firestore (``TD_STORE_<MODULE>=firestore``) is copied with
the module's backfill mapping, so a mixed stack serves the seeded data from either store.
Modules without a backfill mapping yet are skipped.
"""

from __future__ import annotations

from typing import Any


async def sync_touched(session: Any, *modules: str) -> dict[str, Any]:
    from app.core.firestore.backend import uses_firestore
    from app.core.firestore.backfill import sync_if_enabled

    done: dict[str, Any] = {}
    for m in dict.fromkeys(modules):
        if not uses_firestore(m):
            continue
        try:
            done.update(await sync_if_enabled(session, m))
        except ModuleNotFoundError:  # no store_specs (no Firestore data model) for this module
            continue
    return done
