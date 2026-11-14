"""Firestore data model of guided learning paths (data-content agent; docs/firebase/agents/
data-content.md). Collections, mappers, backfill and verify; the repository is ``repo_firestore.py``
(dispatch in ``store.py``). Other modules' tables are read through ``adapters.py``.

Collections (UUIDs stay document ids; ``Numeric`` values are exact decimal strings, e.g.
``"1.50"``, because the store refuses ``Decimal`` and floats would round; ``date`` is ISO):

* ``learning_paths/{id}`` — the path row plus the **embedded draft tree** ``steps`` (the
  ``learning_path_steps`` rows ordered by parent_key, position, id) and ``article_ids``.
  ``steps_save`` replaces the
  whole tree, so one document write keeps ``UNIQUE (path_id, step_key)`` and the order.
* ``learning_path_versions/{id}`` — the published version plus its embedded, immutable ``steps``
  and ``assignment_ids`` / ``test_ids`` / ``article_ids`` (``array-contains`` reverse lookups)
  (``learning_path_version_steps``). ``UNIQUE (path_id, version_no)`` becomes
  ``learning_paths.version_no`` + 1 in the publishing transaction.
* ``path_articles/{id}`` — one document per article (``body_md`` / ``toc`` unindexed).
* ``path_allocations/{id}`` — one document per allocation; ``user_ids`` is an array (learner
  lookup with ``array-contains``, Postgres GIN ``ix_pal_users``).
* ``path_step_progress/{allocation_id:user_id:step_key}`` — owned by ``user_id`` (RLS ``U``);
  the deterministic id replaces ``UNIQUE (allocation_id, user_id, step_key)``.

RLS ``T`` (single company) = staff with the path permission; learners reach paths through their
allocations, which the service checks.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from app.core.firestore.backfill import Row, TableMapping, register_mapping
from app.core.firestore.collections import CollectionSpec, register_collection
from app.core.firestore.ids import compose_id

PATHS = "learning_paths"
VERSIONS = "learning_path_versions"
ARTICLES = "path_articles"
ALLOCATIONS = "path_allocations"
PROGRESS = "path_step_progress"

for _name, _write in (
    (PATHS, "path.manage"),
    (VERSIONS, "path.publish"),
    (ARTICLES, "path_article.update"),
    (ALLOCATIONS, "path.allocate"),
):
    register_collection(CollectionSpec(_name, "shared", read_permission=None, write_permission=_write))
register_collection(
    CollectionSpec(
        PROGRESS, "owned", owner_writes=True, read_permission="path.allocate", write_permission=None
    )
)

STEP_FIELDS = (
    "id",
    "step_key",
    "parent_key",
    "position",
    "step_type",
    "title",
    "description_md",
    "est_hours",
    "credits",
    "url",
    "lesson_id",
    "assignment_id",
    "test_id",
    "article_id",
)


def plain(v: Any) -> Any:
    """Postgres value -> stored value (UUID str, exact decimal str, ISO date, lists/maps deep)."""
    if isinstance(v, uuid.UUID):
        return str(v)
    if isinstance(v, Decimal):
        return str(v)
    if isinstance(v, date) and not isinstance(v, datetime):
        return v.isoformat()
    if isinstance(v, (list, tuple)):
        return [plain(x) for x in v]
    if isinstance(v, dict):
        return {str(k): plain(x) for k, x in v.items()}
    return v


def row_doc(r: Row) -> dict[str, Any]:
    return {k: plain(v) for k, v in r.items()}


def step_doc(r: Row) -> dict[str, Any]:
    return {k: plain(r.get(k)) for k in STEP_FIELDS}


def progress_id(allocation_id: Any, user_id: Any, step_key: Any) -> str:
    return compose_id(str(allocation_id), str(user_id), str(step_key))


async def _all(session: Any, sql: str) -> list[Row]:
    from sqlalchemy import text

    return [dict(r) for r in (await session.execute(text(sql))).mappings().all()]


def link_arrays(steps: list[dict[str, Any]]) -> dict[str, list[str]]:
    """Distinct linked ids of an embedded step list (``array-contains`` reverse lookups:
    "versions linking test X", "draft steps using article Y")."""
    out: dict[str, list[str]] = {}
    for fld in ("assignment_id", "test_id", "article_id"):
        out[fld + "s"] = list(dict.fromkeys(str(s[fld]) for s in steps if s.get(fld)))
    return out


def _embed(parents: list[Row], steps: list[Row], fk: str, arrays: tuple[str, ...]) -> list[Row]:
    by: dict[Any, list[dict[str, Any]]] = {}
    for s in steps:
        by.setdefault(s[fk], []).append(step_doc(s))
    for p in parents:
        p["steps"] = by.get(p["id"], [])
        links = link_arrays(p["steps"])
        for a in arrays:
            p[a] = links[a]
    return parents


async def load_paths(session: Any) -> list[Row]:
    paths = await _all(session, "SELECT * FROM learning_paths ORDER BY id")
    steps = await _all(
        session, "SELECT * FROM learning_path_steps ORDER BY path_id, parent_key NULLS FIRST, position, id"
    )
    return _embed(paths, steps, "path_id", ("article_ids",))


async def load_versions(session: Any) -> list[Row]:
    versions = await _all(session, "SELECT * FROM learning_path_versions ORDER BY id")
    steps = await _all(
        session,
        "SELECT * FROM learning_path_version_steps "
        "ORDER BY path_version_id, parent_key NULLS FIRST, position, id",
    )
    return _embed(versions, steps, "path_version_id", ("assignment_ids", "test_ids", "article_ids"))


register_mapping(
    TableMapping("paths", "learning_paths", PATHS, lambda r: str(r["id"]), row_doc, loader=load_paths)
)
register_mapping(
    TableMapping(
        "paths", "learning_path_versions", VERSIONS, lambda r: str(r["id"]), row_doc, loader=load_versions
    )
)
register_mapping(TableMapping("paths", "path_articles", ARTICLES, lambda r: str(r["id"]), row_doc))
register_mapping(TableMapping("paths", "path_allocations", ALLOCATIONS, lambda r: str(r["id"]), row_doc))
register_mapping(
    TableMapping(
        "paths",
        "path_step_progress",
        PROGRESS,
        lambda r: progress_id(r["allocation_id"], r["user_id"], r["step_key"]),
        row_doc,
    )
)
