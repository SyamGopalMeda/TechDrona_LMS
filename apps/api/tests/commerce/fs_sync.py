"""Store matrix support for the commerce tests (``TD_STORE_COMMERCE=firestore``).

The factories write catalogue rows straight into the Postgres test transaction; on the
Firestore leg those rows must also exist in Firestore (the app's requests read Firestore).
``mirror`` copies the given ORM rows (as detached copies, so the Postgres instances are never
touched) through the commerce engine, committed at once. A no-op on the Postgres leg."""

from __future__ import annotations

from typing import Any


async def mirror(*objs: Any) -> None:
    from app.modules.commerce import datastore as ds

    if not ds.on_firestore():
        return
    from app.modules.commerce import store_specs as sp
    from app.modules.commerce.repo_firestore import Scope, UnitOfWork

    u = UnitOfWork()
    for o in objs:
        model = type(o)
        u.add(sp.from_doc(model, sp.to_doc(model, o)), Scope.platform())
    await u.commit()
