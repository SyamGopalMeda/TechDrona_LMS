"""Firestore data model of the catalog (MIGRATION-PLAN §3.1 "catalog", P2; docs/firebase/p2.md).

P2: collections, mappers, indexes, backfill and verification. P2b: the repository
(``repo_firestore.py``) reads and writes these documents behind ``TD_STORE_CATALOG``.

Collections (UUIDs stay document ids):

* ``courses/{id}`` — the course row, plus ``card``: the public card fields of the current
  published version (title, summary, level, language, category, tags, published_at,
  lesson_count, duration_seconds), so the public listing is one query on ``courses``
  (index ``status, visibility, organization_id, published_at``) instead of a join.
* ``courses_by_slug/{org|platform:slug}`` — ``{course_id}``: slug uniqueness per catalogue
  (Postgres ``ux_courses_slug``, soft-deleted courses excluded) and the slug lookup.
* ``course_versions/{id}`` — the version row with the **embedded outline** (modules and lesson
  summaries, ordered by position) plus ``lesson_count`` / ``duration_seconds``. A published
  version is immutable, so the embedded copy never goes stale.
* ``lessons/{id}`` — the full lesson (article body, refs) with ``course_id`` and the embedded
  ``topics`` (``lesson_topics``, primary first).
* ``lesson_assets/{id}``, ``resources/{id}`` — one document per row.

Postgres RLS on these tables is ``TN`` (organization or global) which, single company, means
"staff with the course permission" for drafts and "anyone" for the published, public catalogue.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.firestore.backfill import Row, TableMapping, register_mapping
from app.core.firestore.collections import CollectionSpec, register_collection
from app.core.firestore.ids import compose_id

COURSES = "courses"
COURSES_BY_SLUG = "courses_by_slug"
VERSIONS = "course_versions"
LESSONS = "lessons"
ASSETS = "lesson_assets"
RESOURCES = "resources"

for _name, _write in (
    (COURSES, "course.edit"),
    (COURSES_BY_SLUG, "course.create"),
    (VERSIONS, "course.edit"),
    (LESSONS, "course.edit"),
    (ASSETS, "course.edit"),
    (RESOURCES, "resource.manage"),
):
    # Reads of unpublished content are filtered by the repository (status / visibility), like
    # the Postgres public queries; the store-level rule is "any authenticated principal".
    register_collection(CollectionSpec(_name, "shared", read_permission=None, write_permission=_write))


def _s(v: Any) -> str | None:
    return str(v) if v is not None else None


def _num(v: Any) -> Any:
    return float(v) if isinstance(v, Decimal) else v


def slug_id(organization_id: Any, slug: str) -> str:
    return compose_id(str(organization_id) if organization_id else "platform", slug.lower())


# --------------------------------------------------------------------------- mappers


def course_doc(r: Row) -> dict[str, Any]:
    out = {
        "id": str(r["id"]),
        "organization_id": _s(r["organization_id"]),
        "slug": r["slug"],
        "slug_lc": r["slug"].lower(),
        "title": r["title"],
        "course_kind": r["course_kind"],
        "visibility": r["visibility"],
        "status": r["status"],
        "is_free": bool(r["is_free"]),
        "current_version_id": _s(r["current_version_id"]),
        "primary_topic_id": _s(r["primary_topic_id"]),
        "completeness_pct": _num(r["completeness_pct"]),
        "created_by": str(r["created_by"]),
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "deleted_at": r["deleted_at"],
        # Authoring pointers (P2b): the editable version (``draft``/``in_review``, at most one)
        # and the highest version number. Every authoring transaction reads the course document,
        # so concurrent draft clones / publishes serialise on it.
        "draft_version_id": _s(r.get("draft_version_id")),
        "last_version_no": int(r.get("last_version_no") or 0),
        "card": None,
        "published_at": None,
    }
    if r.get("v_id") is not None:
        out["published_at"] = r["v_published_at"]
        out["card"] = {
            "title": r["v_title"],
            "summary": r["v_summary"],
            "level": r["v_level"],
            "language": r["v_language"],
            "category": r["v_category"],
            "tags": list(r["v_tags"] or []),
            "published_at": r["v_published_at"],
            "lesson_count": int(r["v_lesson_count"] or 0),
            "duration_seconds": int(r["v_duration"] or 0),
        }
    return out


def version_doc(r: Row) -> dict[str, Any]:
    keys = (
        "version_no",
        "title",
        "summary",
        "description_md",
        "level",
        "language",
        "category",
        "certificate_rule",
        "completeness_plan",
        "status",
        "change_type",
        "changelog",
        "submitted_at",
        "published_at",
        "created_at",
        "updated_at",
    )
    return {
        "id": str(r["id"]),
        "course_id": str(r["course_id"]),
        "organization_id": _s(r["organization_id"]),
        **{k: r[k] for k in keys},
        "outcomes": list(r["outcomes"] or []),
        "tags": list(r["tags"] or []),
        "created_by": str(r["created_by"]),
        "submitted_by": _s(r["submitted_by"]),
        "published_by": _s(r["published_by"]),
        "outline": r["outline"],
        "lesson_count": r["lesson_count"],
        "duration_seconds": r["duration_seconds"],
    }


LESSON_SUMMARY = (
    "lesson_key",
    "title",
    "lesson_type",
    "position",
    "is_required",
    "is_free_preview",
    "duration_seconds",
    "est_reading_minutes",
)


def lesson_doc(r: Row) -> dict[str, Any]:
    return {
        "id": str(r["id"]),
        "course_id": str(r["course_id"]),
        "course_version_id": str(r["course_version_id"]),
        "course_module_id": str(r["course_module_id"]),
        "organization_id": _s(r["organization_id"]),
        **{k: (str(r[k]) if k == "lesson_key" else r[k]) for k in LESSON_SUMMARY},
        "article_body": r["article_body"],
        "test_id": _s(r["test_id"]),
        "coding_problem_id": _s(r["coding_problem_id"]),
        "assignment_id": _s(r["assignment_id"]),
        "live_url": r["live_url"],
        "topics": r["topics"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
    }


def _plain(r: Row) -> dict[str, Any]:
    import uuid

    return {k: (str(v) if isinstance(v, uuid.UUID) else _num(v)) for k, v in r.items()}


# --------------------------------------------------------------------------- loaders (assembled docs)


async def _all(session: AsyncSession, sql: str) -> list[Row]:
    return [dict(r) for r in (await session.execute(text(sql))).mappings().all()]


async def load_courses(session: AsyncSession) -> list[Row]:
    return await _all(
        session,
        """
        SELECT c.*, v.id AS v_id, v.title AS v_title, v.summary AS v_summary, v.level AS v_level,
               v.language AS v_language, v.category AS v_category, v.tags AS v_tags,
               v.published_at AS v_published_at,
               (SELECT count(*) FROM lessons l WHERE l.course_version_id = v.id) AS v_lesson_count,
               (SELECT coalesce(sum(l.duration_seconds), 0) FROM lessons l
                 WHERE l.course_version_id = v.id) AS v_duration,
               (SELECT d.id FROM course_versions d WHERE d.course_id = c.id
                   AND d.status IN ('draft', 'in_review') ORDER BY d.id LIMIT 1) AS draft_version_id,
               (SELECT max(x.version_no) FROM course_versions x WHERE x.course_id = c.id)
                 AS last_version_no
          FROM courses c
          LEFT JOIN course_versions v ON v.id = c.current_version_id AND v.status = 'published'
         ORDER BY c.id
        """,
    )


async def load_versions(session: AsyncSession) -> list[Row]:
    versions = await _all(session, "SELECT * FROM course_versions ORDER BY id")
    modules = await _all(session, "SELECT * FROM course_modules ORDER BY course_version_id, position, id")
    lessons = await _all(session, "SELECT * FROM lessons ORDER BY course_module_id, position, id")
    by_module: dict[Any, list[dict[str, Any]]] = {}
    for le in lessons:
        by_module.setdefault(le["course_module_id"], []).append(
            {"id": str(le["id"]), **{k: (str(le[k]) if k == "lesson_key" else le[k]) for k in LESSON_SUMMARY}}
        )
    outline: dict[Any, list[dict[str, Any]]] = {}
    for m in modules:
        outline.setdefault(m["course_version_id"], []).append(
            {
                "id": str(m["id"]),
                "module_key": str(m["module_key"]),
                "title": m["title"],
                "position": m["position"],
                "lessons": by_module.get(m["id"], []),
            }
        )
    for v in versions:
        mods = outline.get(v["id"], [])
        flat = [le for m in mods for le in m["lessons"]]
        v["outline"] = mods
        v["lesson_count"] = len(flat)
        v["duration_seconds"] = sum(int(le["duration_seconds"] or 0) for le in flat)
    return versions


async def load_lessons(session: AsyncSession) -> list[Row]:
    rows = await _all(
        session,
        "SELECT l.*, v.course_id FROM lessons l "
        "JOIN course_versions v ON v.id = l.course_version_id ORDER BY l.id",
    )
    topics = await _all(session, "SELECT * FROM lesson_topics ORDER BY lesson_id, is_primary DESC, topic_id")
    by_lesson: dict[Any, list[dict[str, Any]]] = {}
    for t in topics:
        by_lesson.setdefault(t["lesson_id"], []).append(
            {"topic_id": str(t["topic_id"]), "is_primary": bool(t["is_primary"])}
        )
    for r in rows:
        r["topics"] = by_lesson.get(r["id"], [])
    return rows


async def load_slugs(session: AsyncSession) -> list[Row]:
    return await _all(
        session, "SELECT id, organization_id, slug FROM courses WHERE deleted_at IS NULL ORDER BY id"
    )


register_mapping(
    TableMapping("catalog", "courses", COURSES, lambda r: str(r["id"]), course_doc, loader=load_courses)
)
register_mapping(
    TableMapping(
        "catalog",
        "courses",
        COURSES_BY_SLUG,
        lambda r: slug_id(r["organization_id"], r["slug"]),
        lambda r: {"course_id": str(r["id"])},
        loader=load_slugs,
    )
)
register_mapping(
    TableMapping(
        "catalog", "course_versions", VERSIONS, lambda r: str(r["id"]), version_doc, loader=load_versions
    )
)
register_mapping(
    TableMapping("catalog", "lessons", LESSONS, lambda r: str(r["id"]), lesson_doc, loader=load_lessons)
)
register_mapping(TableMapping("catalog", "lesson_assets", ASSETS, lambda r: str(r["id"]), _plain))
register_mapping(TableMapping("catalog", "resources", RESOURCES, lambda r: str(r["id"]), _plain))
