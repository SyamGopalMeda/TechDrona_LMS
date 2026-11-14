"""Request-scoped read memo for ``ScopedStore`` (Firestore cost: no second billed read of the same
document inside ONE HTTP request).

Why: on the Firebase stack every document read is billed, and one request often reads the same
document twice through different modules (the session resolver loads ``users`` / ``auth_sessions``
and the handler loads them again; a course page reads the same ``course_versions`` document from
three helpers). On the VM each of those was a Postgres ``SELECT`` inside the same request.

Scope and lifetime (no cross-request caching, so no revocation/permission staleness):

* The memo dict lives in the request's ASGI state, created by ``RequestContextMiddleware`` at the
  start of the request and dropped in its ``finally`` -- outside a request (jobs, tasks, tests
  without the middleware) nothing is memoised.
* Only the collections in ``DOC_COLLECTIONS`` (document reads: ``get`` / ``get_many``, and query
  results that hand back whole documents) and ``QUERY_COLLECTIONS`` (whole query results, keyed
  by the query) are memoised. Reads inside a transaction are never memoised (they must join the
  transaction's read set).
* Any write staged through the store (transaction ``set/create/update/delete``, ``create``,
  ``import_documents``, ``delete_all``) forgets that document AND every memoised query of its
  collection before the write is sent, so a request always re-reads what it wrote.
* Taking a lease / request lock (``claim_lease``) clears the whole memo: code that serialises on a
  lock re-reads everything after it holds the lock, exactly as a ``SELECT`` after the lock did.
* Values are deep-copied in and out, so a caller mutating a returned dict cannot leak into a
  later read.

The only observable difference: a second read of the same document in the same request returns
what the first read returned, instead of a commit another request made in the milliseconds
between the two reads -- the same outcome as both reads running together.
"""

from __future__ import annotations

import copy
from typing import Any

from app.core.firestore import instance_cache
from app.core.request_context import _request_state

STATE_KEY = "td_fs_read_memo"

# Physical collection names (lms_*). Read on (almost) every request, written rarely, and never
# polled inside a request.
DOC_COLLECTIONS = frozenset(
    {
        "lms_users",
        "lms_user_profiles",
        "lms_auth_sessions",
        "lms_devices",
        "lms_courses",
        "lms_courses_by_slug",
        "lms_course_versions",
        "lms_lessons",
    }
)
QUERY_COLLECTIONS = frozenset({"lms_consents"})

_MISSING: Any = object()


def begin() -> dict[str, Any]:
    """A fresh memo for one request (``RequestContextMiddleware``)."""
    return {"docs": {}, "queries": {}}


def _memo() -> dict[str, Any] | None:
    state = _request_state.get()
    if not state:
        return None
    memo = state.get(STATE_KEY)
    return memo if isinstance(memo, dict) else None


def get_doc(physical: str, doc_id: str) -> Any:
    """``_MISSING`` when not memoised; ``None`` for a memoised "does not exist"; else a copy."""
    if physical not in DOC_COLLECTIONS:
        return _MISSING
    memo = _memo()
    if memo is None:
        return _MISSING
    hit = memo["docs"].get((physical, doc_id), _MISSING)
    if hit is _MISSING or hit is None:
        return hit
    return copy.deepcopy(hit)


def put_doc(physical: str, doc_id: str, data: dict[str, Any] | None) -> None:
    if physical not in DOC_COLLECTIONS:
        return
    memo = _memo()
    if memo is not None:
        memo["docs"][(physical, doc_id)] = None if data is None else copy.deepcopy(data)


def get_query(physical: str, key: Any) -> Any:
    if physical not in QUERY_COLLECTIONS:
        return _MISSING
    memo = _memo()
    if memo is None:
        return _MISSING
    hit = memo["queries"].get((physical, key), _MISSING)
    return hit if hit is _MISSING else copy.deepcopy(hit)


def put_query(physical: str, key: Any, value: Any) -> None:
    if physical not in QUERY_COLLECTIONS:
        return
    memo = _memo()
    if memo is not None:
        memo["queries"][(physical, key)] = copy.deepcopy(value)


def forget(physical: str, doc_id: str | None = None) -> None:
    """A write to ``physical/doc_id`` (``None``: the whole collection) is about to be sent."""
    instance_cache.bump(physical)  # per-process caches too (in or outside a request)
    memo = _memo()
    if memo is None:
        return
    docs, queries = memo["docs"], memo["queries"]
    if doc_id is None:
        for k in [k for k in docs if k[0] == physical]:
            del docs[k]
    else:
        docs.pop((physical, doc_id), None)
    for k in [k for k in queries if k[0] == physical]:
        del queries[k]


def clear() -> None:
    """Forget everything (a lock was taken: what follows must see the latest commits)."""
    memo = _memo()
    if memo is not None:
        memo["docs"].clear()
        memo["queries"].clear()


MISSING: Any = _MISSING  # the "not memoised" sentinel (typed Any for callers)
