"""Public, store-neutral API of the audit module (data-ops agent).

Writers keep using ``app.core.audit.audit(session, ...)`` for Postgres transactions. Modules whose
business writes are in Firestore record the audit row **in the same Firestore transaction** with
``record_in_tx`` (the sealer drains both outboxes into the one chain, see ``sealer.seal_once``).

* ``record_in_tx(tx, actor, action, target_type, target_id=None, **kw)`` -- inside
  ``ScopedStore.run_transaction``; same arguments and record as ``core.audit.audit``.
* ``record_now(...)`` -- its own one-document transaction (no business write to pair with).
* ``build_record(...)`` -- the outbox payload (for platform code that writes it itself).
* ``seal_once(engine)`` -- one sealing round (worker / sealer service).
* ``verify_chain(session)`` -- whole-chain verification on the active store.
"""

from __future__ import annotations

from typing import Any

from app.core.audit import AuditActor
from app.core.firestore.backend import uses_firestore
from app.modules.audit.chain import ChainVerification
from app.modules.audit.repo_firestore import build_record
from app.modules.audit.repo_firestore import enqueue as record_in_tx
from app.modules.audit.repo_firestore import enqueue_now as record_now
from app.modules.audit.sealer import seal_once

__all__ = [
    "AuditActor",
    "ChainVerification",
    "build_record",
    "record_in_tx",
    "record_now",
    "seal_once",
    "verify_chain",
]


async def verify_chain(session: Any, from_seq: int = 1) -> ChainVerification:
    if uses_firestore("audit"):
        from app.modules.audit.repo_firestore import chain_repo

        return await chain_repo().verify_chain(from_seq)
    from app.modules.audit.sealer import verify_chain as _pg

    return await _pg(session, from_seq)
