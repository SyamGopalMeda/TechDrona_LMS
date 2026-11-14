"""Public lifecycle hooks for the process-wide Firestore client (``client`` stays private).

``close()`` drops the cached async client. Its gRPC channel is bound to the event loop that
created it, so code that runs each job on a fresh loop (``app.core.jobs.run_async``) closes it
before the loop ends, exactly as it already does for the SQLAlchemy engine and Redis clients.
"""

from __future__ import annotations


async def close() -> None:
    from app.core.firestore import client as client_mod

    if client_mod._client is None:
        return
    try:
        await client_mod.close_client()
    except Exception:  # never let cleanup mask the job's own result
        client_mod.set_client(None)
