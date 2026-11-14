"""Firestore repository of guided learning paths (``TD_STORE_PATHS=firestore``).

``paths/store.py`` dispatches here; the Postgres SQL stays in ``store.py``. Data model:
``store_specs.py`` (paths and versions embed their step trees). Values come back as **transient
ORM instances** with the model column types (UUID, Decimal, date, aware datetime), so the
service's logic and serializers run unchanged; Postgres server defaults are filled in on insert
exactly as ``eager_defaults`` loads them (``fill_defaults``).

Uniqueness: ``UNIQUE (path_id, step_key)`` holds because the draft tree is one document written
whole; ``UNIQUE (path_id, version_no)`` because publish reads the path and checks ``version_no``
inside the transaction that writes the version; ``UNIQUE (allocation_id, user_id, step_key)``
because progress ids are deterministic (``progress_id``).
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterable, Sequence
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Boolean, Date, DateTime, Integer, Numeric
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

from app.core.errors import ProblemError
from app.core.firestore.errors import UniqueViolationError
from app.core.firestore.repository import FirestoreRepository, platform_only
from app.core.firestore.store import Doc, Filter, Order, ScopedStore, ScopedTransaction
from app.core.time import utcnow
from app.modules.paths.models import (
    LearningPath,
    LearningPathStep,
    LearningPathVersion,
    LearningPathVersionStep,
    PathAllocation,
    PathArticle,
    PathStepProgress,
)
from app.modules.paths.store_specs import (
    ALLOCATIONS,
    ARTICLES,
    PATHS,
    PROGRESS,
    STEP_FIELDS,
    VERSIONS,
    link_arrays,
    plain,
    progress_id,
)

JOB = "paths"
MARK = "path.manage"  # ``@platform_only`` marker; the repository always runs on the system job
_PAGE = 100
_IN = 30


# =========================================================================== doc <-> ORM


def _dt(v: Any) -> datetime | None:
    if v is None:
        return None
    if isinstance(v, datetime):
        v = v.astimezone(UTC)
        return datetime(v.year, v.month, v.day, v.hour, v.minute, v.second, v.microsecond, tzinfo=UTC)
    return datetime.fromisoformat(str(v)).astimezone(UTC)


def _col_value(col: Any, v: Any) -> Any:
    t = col.type
    if v is None:
        return None
    if isinstance(t, PG_UUID):
        return uuid.UUID(str(v))
    if isinstance(t, Numeric):
        return Decimal(str(v))
    if isinstance(t, DateTime):
        return _dt(v)
    if isinstance(t, Date):
        return v if isinstance(v, date) else date.fromisoformat(str(v))
    if isinstance(t, ARRAY):
        inner = t.item_type
        return [uuid.UUID(str(x)) if isinstance(inner, PG_UUID) else x for x in v]
    return v


def orm[T](cls: type[T], d: dict[str, Any], **extra: Any) -> T:
    """A transient ``cls`` from a document (model column types)."""
    kw = {c.key: _col_value(c, extra.get(c.key, d.get(c.key))) for c in cls.__table__.columns}  # type: ignore[attr-defined]
    return cls(**kw)


def fields(obj: Any) -> dict[str, Any]:
    """Column values of an ORM instance as stored values."""
    return {c.key: plain(getattr(obj, c.key)) for c in type(obj).__table__.columns}


def _server_default(col: Any, now: datetime) -> Any:
    sd = col.server_default
    if sd is None:
        return None
    raw = str(getattr(sd, "arg", "")).strip()
    if raw.lower() == "now()":
        return now
    if raw.startswith("'") and raw.endswith("'"):
        raw = raw[1:-1]
    t = col.type
    if isinstance(t, Boolean):
        return raw.lower() == "true"
    if isinstance(t, Integer):
        return int(raw)
    if isinstance(t, Numeric):
        return Decimal(raw)
    if isinstance(t, JSONB):
        return json.loads(raw)
    if isinstance(t, ARRAY):
        return []
    return raw


def fill_defaults(obj: Any, now: datetime | None = None) -> Any:
    """Set unset columns to their Postgres ``server_default`` (as ``eager_defaults`` would)."""
    now = now or utcnow()
    for c in type(obj).__table__.columns:
        if getattr(obj, c.key) is None and c.server_default is not None:
            setattr(obj, c.key, _server_default(c, now))
    return obj


def _steps_of(cls: type[Any], d: dict[str, Any], **parent: Any) -> list[Any]:
    return [orm(cls, s, **parent) for s in d.get("steps") or []]


def _step_doc(r: Any) -> dict[str, Any]:
    return {k: plain(getattr(r, k)) for k in STEP_FIELDS}


def _like(q: str | None) -> Any:
    needle = (q or "").lower()
    return lambda s: needle in (s or "").lower()


# =========================================================================== repository


class PathsRepo(FirestoreRepository):
    """On the named system job ``paths``; route-level checks (``path.manage`` / ``path.allocate``
    / learner targeting) stay in the service, as on Postgres."""

    async def _all(self, coll: str, filters: Sequence[Filter] = (), order: Sequence[Order] = ()) -> list[Doc]:
        out: list[Doc] = []
        cursor: str | None = None
        while True:
            page = await self.store.query(coll, filters=filters, order_by=order, limit=_PAGE, cursor=cursor)
            out.extend(page.items)
            if not page.next_cursor:
                return out
            cursor = page.next_cursor

    async def _in(
        self, coll: str, fld: str, values: Iterable[Any], extra: Sequence[Filter] = ()
    ) -> list[Doc]:
        vals = list(dict.fromkeys(str(v) for v in values))
        out: list[Doc] = []
        for i in range(0, len(vals), _IN):
            out += await self._all(coll, [*extra, (fld, "in", vals[i : i + _IN])])
        return out

    # ------------------------------------------------------------------ paths

    @platform_only(MARK)
    async def get_path(self, path_id: uuid.UUID) -> LearningPath | None:
        d = await self.store.get(PATHS, str(path_id))
        return orm(LearningPath, d.data) if d else None

    @platform_only(MARK)
    async def list_paths(self, status: str | None, q: str | None, limit: int) -> list[LearningPath]:
        docs = await self._all(PATHS, order=(("updated_at", "desc"),))
        match = _like(q)
        out = [
            orm(LearningPath, d.data)
            for d in docs
            if (d["status"] == status if status else d["status"] != "archived")
            and (not q or match(d["title"]))
        ]
        return out[:limit]

    @platform_only(MARK)
    async def draft_rows(self, path_id: uuid.UUID) -> list[LearningPathStep]:
        d = await self.store.get(PATHS, str(path_id))
        if d is None:
            return []
        return _steps_of(LearningPathStep, d.data, path_id=d["id"], organization_id=d["organization_id"])

    @platform_only(MARK)
    async def insert_path(self, p: LearningPath) -> None:
        fill_defaults(p)
        await self.store.create(PATHS, {**fields(p), "steps": [], "article_ids": []}, doc_id=str(p.id))

    @platform_only(MARK)
    async def save_path(self, p: LearningPath, steps: list[Any] | None = None) -> None:
        """Write the path's columns (and, with ``steps``, replace the embedded draft tree)."""
        changes = {k: v for k, v in fields(p).items() if k not in ("id", "created_at", "updated_at")}
        if steps is not None:
            docs = [_step_doc(fill_defaults(s)) for s in steps]
            changes["steps"] = docs
            changes["article_ids"] = link_arrays(docs)["article_ids"]
        await self.store.update(PATHS, str(p.id), changes)

    @platform_only(MARK)
    async def draft_steps_using_article(self, article_id: uuid.UUID) -> int:
        docs = await self._all(PATHS, [("article_ids", "array-contains", str(article_id))])
        return sum(1 for d in docs for s in d.get("steps") or [] if s.get("article_id") == str(article_id))

    @platform_only(MARK)
    async def publish(
        self, p: LearningPath, v: LearningPathVersion, rows: list[LearningPathVersionStep]
    ) -> None:
        """Version + embedded steps + path pointers in one transaction (``UNIQUE (path_id,
        version_no)``: a concurrent publish of the same number fails with 409)."""
        fill_defaults(v)
        steps = [_step_doc(fill_defaults(r)) for r in rows]

        async def body(tx: ScopedTransaction) -> None:
            cur = await tx.get(PATHS, str(p.id))
            if cur is None:
                raise ProblemError("not_found")
            if int(cur["version_no"]) + 1 != v.version_no:
                raise ProblemError("conflict", detail="This path was published concurrently; reload.")
            await tx.create(VERSIONS, {**fields(v), "steps": steps, **link_arrays(steps)}, doc_id=str(v.id))
            changes = {k: val for k, val in fields(p).items() if k not in ("id", "created_at", "updated_at")}
            await tx.update_read(PATHS, cur, changes)

        await self.store.run_transaction(body)

    # ------------------------------------------------------------------ versions

    @platform_only(MARK)
    async def get_version(self, version_id: uuid.UUID) -> LearningPathVersion | None:
        d = await self.store.get(VERSIONS, str(version_id))
        return orm(LearningPathVersion, d.data) if d else None

    @platform_only(MARK)
    async def version_rows(self, version_id: uuid.UUID) -> list[LearningPathVersionStep]:
        d = await self.store.get(VERSIONS, str(version_id))
        if d is None:
            return []
        return _steps_of(
            LearningPathVersionStep, d.data, path_version_id=d["id"], organization_id=d["organization_id"]
        )

    @platform_only(MARK)
    async def versions_linking(self, field: str, ref_id: uuid.UUID) -> set[uuid.UUID]:
        """Versions with a step whose ``field`` (assignment_id / test_id / article_id) is ``ref_id``."""
        arr = {"assignment_id": "assignment_ids", "test_id": "test_ids", "article_id": "article_ids"}[field]
        docs = await self._all(VERSIONS, [(arr, "array-contains", str(ref_id))])
        return {uuid.UUID(d.id) for d in docs}

    # ------------------------------------------------------------------ allocations

    @platform_only(MARK)
    async def get_allocation(self, allocation_id: uuid.UUID) -> PathAllocation | None:
        d = await self.store.get(ALLOCATIONS, str(allocation_id))
        return orm(PathAllocation, d.data) if d else None

    @platform_only(MARK)
    async def allocations_for_path(self, path_id: uuid.UUID) -> list[PathAllocation]:
        docs = await self._all(ALLOCATIONS, [("path_id", "==", str(path_id))], (("created_at", "desc"),))
        return [orm(PathAllocation, d.data) for d in docs]

    @platform_only(MARK)
    async def insert_allocation(self, a: PathAllocation) -> None:
        fill_defaults(a)
        await self.store.create(ALLOCATIONS, fields(a), doc_id=str(a.id))

    @platform_only(MARK)
    async def save_allocation(self, a: PathAllocation) -> None:
        changes = {k: v for k, v in fields(a).items() if k not in ("id", "created_at", "updated_at")}
        await self.store.update(ALLOCATIONS, str(a.id), changes)

    @platform_only(MARK)
    async def revoke_active_for_path(self, path_id: uuid.UUID, at: datetime) -> int:
        docs = await self._all(ALLOCATIONS, [("path_id", "==", str(path_id)), ("status", "==", "active")])
        for d in docs:
            await self.store.update(ALLOCATIONS, d.id, {"status": "revoked", "revoked_at": at})
        return len(docs)

    async def allocations_for_user(
        self,
        user_id: uuid.UUID,
        batch_ids: set[uuid.UUID],
        *,
        allocation_id: uuid.UUID | None = None,
        version_ids: set[uuid.UUID] | None = None,
    ) -> list[PathAllocation]:
        """Active allocations targeting ``user_id`` (chosen learner, or one of ``batch_ids`` where
        they are an active student), newest first; optionally one id / these versions only."""
        if allocation_id is not None:
            d = await self.store.get(ALLOCATIONS, str(allocation_id))
            docs = [d] if d is not None else []
        else:
            docs = await self._all(
                ALLOCATIONS, [("status", "==", "active"), ("user_ids", "array-contains", str(user_id))]
            )
            if batch_ids:
                docs += await self._in(ALLOCATIONS, "batch_id", batch_ids, [("status", "==", "active")])
        seen: dict[str, PathAllocation] = {}
        for d in docs:
            a = orm(PathAllocation, d.data)
            if a.status != "active" or not (user_id in a.user_ids or a.batch_id in batch_ids):
                continue
            if version_ids is not None and a.path_version_id not in version_ids:
                continue
            seen.setdefault(d.id, a)
        return sorted(seen.values(), key=lambda a: (a.created_at, str(a.id)), reverse=True)

    # ------------------------------------------------------------------ progress

    @platform_only(MARK)
    async def progress_for_allocation(self, allocation_id: uuid.UUID) -> list[PathStepProgress]:
        docs = await self._all(PROGRESS, [("allocation_id", "==", str(allocation_id))])
        return [orm(PathStepProgress, d.data) for d in docs]

    async def progress(self, user_id: uuid.UUID, allocation_id: uuid.UUID) -> list[PathStepProgress]:
        page_docs: list[Doc] = []
        cursor: str | None = None
        while True:
            page = await self.store.query(
                PROGRESS,
                user_id=user_id,
                filters=[("allocation_id", "==", str(allocation_id))],
                order_by=(),
                limit=_PAGE,
                cursor=cursor,
            )
            page_docs += page.items
            if not page.next_cursor:
                break
            cursor = page.next_cursor
        return [orm(PathStepProgress, d.data) for d in page_docs]

    async def insert_progress(self, user_id: uuid.UUID, pr: PathStepProgress, *, if_absent: bool) -> bool:
        """Create the progress row; ``if_absent``: an existing one is kept (``ON CONFLICT DO
        NOTHING``) and ``False`` is returned."""
        fill_defaults(pr)
        try:
            await self.store.create(
                PROGRESS, fields(pr), doc_id=progress_id(pr.allocation_id, user_id, pr.step_key)
            )
        except UniqueViolationError:
            if if_absent:
                return False
            raise
        return True

    async def save_progress(self, user_id: uuid.UUID, pr: PathStepProgress) -> None:
        changes = {k: v for k, v in fields(pr).items() if k not in ("id", "created_at", "updated_at")}
        await self.store.update(PROGRESS, progress_id(pr.allocation_id, user_id, pr.step_key), changes)

    # ------------------------------------------------------------------ articles

    @platform_only(MARK)
    async def get_article(self, article_id: uuid.UUID) -> PathArticle | None:
        d = await self.store.get(ARTICLES, str(article_id))
        if d is None or d.get("deleted_at") is not None:
            return None
        return orm(PathArticle, d.data)

    @platform_only(MARK)
    async def list_articles(
        self, q: str | None, limit: int, org_id: uuid.UUID | None = None
    ) -> list[PathArticle]:
        docs = await self._all(ARTICLES, [("deleted_at", "==", None)], (("updated_at", "desc"),))
        match = _like(q)
        out = [
            orm(PathArticle, d.data)
            for d in docs
            if (not q or match(d["title"])) and (org_id is None or d["organization_id"] == str(org_id))
        ]
        return out[:limit]

    @platform_only(MARK)
    async def insert_article(self, a: PathArticle) -> None:
        fill_defaults(a)
        await self.store.create(ARTICLES, fields(a), doc_id=str(a.id))

    @platform_only(MARK)
    async def save_article(self, a: PathArticle) -> None:
        changes = {k: v for k, v in fields(a).items() if k not in ("id", "created_at", "updated_at")}
        await self.store.update(ARTICLES, str(a.id), changes)


def repo() -> PathsRepo:
    return PathsRepo(ScopedStore.system(JOB))
