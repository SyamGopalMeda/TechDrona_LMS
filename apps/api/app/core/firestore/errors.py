"""Store-layer errors (no google imports, so callers can catch them cheaply)."""

from __future__ import annotations

from app.core.errors import ProblemError


class StoreError(RuntimeError):
    pass


class FirestoreUnavailableError(StoreError):
    """Firestore is not configured / reachable for this process."""


class UniqueViolationError(StoreError):
    """A deterministic id or uniqueness reservation already exists (Postgres UNIQUE equivalent)."""

    def __init__(self, collection: str, doc_id: str) -> None:
        super().__init__(f"{collection}/{doc_id} already exists")
        self.collection = collection
        self.doc_id = doc_id


class NotFoundError(StoreError):
    """Missing OR not visible to the caller (same answer, like RLS: no existence oracle)."""


class StoreAccessDeniedError(StoreError):
    """The caller may see the row but not perform this write (or a ``platform_only`` call)."""


class ExternalIOInTransactionError(StoreError):
    """External I/O attempted inside a Firestore transaction callback (it may re-run on retry)."""


class TransactionTooLargeError(StoreError):
    pass


class TransactionContentionError(StoreError, ProblemError):
    """Still aborted after ``max_attempts`` (hot document / lock timeout).

    Also a ``ProblemError``: uncaught, it renders as the app's contention answer -- ``409 conflict``
    "Another request changed this at the same time. Refresh and try again." with ``Retry-After: 1``
    (the same body ``sqlstore`` raises), never a raw 500."""

    def __init__(self, message: str = "transaction contention") -> None:
        ProblemError.__init__(
            self,
            "conflict",
            detail="Another request changed this at the same time. Refresh and try again.",
            headers={"Retry-After": "1"},
        )
        self.args = (message,)
