"""Firestore repository of the catalog (``TD_STORE_CATALOG=firestore``, Firebase P2b).

``service.py`` loaders, ``api.py`` functions and the ``router.py`` endpoints that run inline SQL
dispatch here when the switch is on; the Postgres path is unchanged. Data model: see
``store_specs.py`` (courses with ``card`` + authoring pointers, ``courses_by_slug``, versions with
the embedded outline, lessons with embedded topics, assets, resources).

Return values are **transient ORM instances** (``Course``, ``CourseVersion``, ``CourseModule``
built from the outline, ``Lesson``, ``LessonAsset``, ``Resource``) with the column types of the
models (UUID, aware datetime, ``Decimal`` for ``completeness_pct``), so the existing serializers
and callers work unchanged. They are never added to a session.

RLS equivalence (catalog tables are family ``TN``). Reads use the named system job
``catalog.read`` and then apply the TN read predicate with the **caller's** Postgres session
context (``app.org_ids`` / ``app.is_platform`` read back with ``current_setting``)::

    visible  <=>  organization_id IS NULL OR organization_id = ANY(org_ids) OR is_platform

so anonymous routes (``DbSession``: org-NULL rows only), principal routes and system contexts see
exactly what Postgres shows them. Writes apply the TN ``WITH CHECK`` predicate
(``is_platform OR organization_id = ANY(org_ids)``) and then write through
``ScopedStore(principal)`` when the principal holds the collections' write permissions at
platform scope (the store re-checks them), else through the named job ``catalog.write`` (course-
or batch-scoped authors, whose route-level permission check already passed; media writes that
run in the caller's or a system context).

Invariants (each enforced inside one Firestore transaction that reads the course document):

* at most one editable version: ``courses.draft_version_id`` points at it; a draft is cloned only
  when the pointer is empty, and the clone writes the pointer, so concurrent clones conflict on
  the course document and the loser retries and finds the draft;
* version numbers: ``courses.last_version_no`` + 1 in the same transaction;
* slug unique per catalogue, case-insensitive: ``courses_by_slug/{org|platform:slug_lc}`` is read
  and written in the creating / renaming transaction (old key released in it);
* publish: SoD-04, media processing / video missing checks, previous version superseded,
  ``current_version_id`` / status / title / completeness / ``card`` / ``published_at`` set, the
  draft pointer cleared — all in one transaction;
* every draft edit rebuilds the version's embedded outline, ``lesson_count`` and
  ``duration_seconds`` in the same transaction as the lesson write; published versions refuse
  edits.

A draft clone larger than ``CLONE_TX_LIMIT`` writes (lessons + assets) is chunked: the lesson and
asset documents are written first in chunks (they belong to a version id nobody references yet),
then one transaction writes the version and the course pointer; a lost race deletes the chunks.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Iterable, Sequence
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import ARRAY, DateTime, Numeric, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

from app.core.errors import ProblemError
from app.core.firestore.codec import to_store
from app.core.firestore.errors import UniqueViolationError
from app.core.firestore.repository import FirestoreRepository, platform_only
from app.core.firestore.store import MAX_TX_WRITES, Doc, Filter, ScopedStore, ScopedTransaction
from app.core.ids import uuid7
from app.core.principal import Principal
from app.core.time import utcnow
from app.modules.catalog.models import Course, CourseModule, CourseVersion, Lesson, LessonAsset, Resource
from app.modules.catalog.store_specs import (
    ASSETS,
    COURSES,
    COURSES_BY_SLUG,
    LESSON_SUMMARY,
    LESSONS,
    RESOURCES,
    VERSIONS,
    slug_id,
)

READ_JOB = "catalog.read"
WRITE_JOB = "catalog.write"
# ``@platform_only`` marker of the read repository (always built on the ``catalog.read`` job).
READ_MARK = "course.preview"
MEDIA_MARK = "media.upload"
EDITABLE = ("draft", "in_review")
IN_CHUNK = 30  # Firestore ``in`` filter limit
CLONE_TX_LIMIT = MAX_TX_WRITES - 20
_PAGE = 100


# =========================================================================== RLS context


@dataclass(frozen=True, slots=True)
class Visibility:
    """The TN predicate evaluated with the caller's Postgres session context."""

    org_ids: frozenset[str] = frozenset()
    is_platform: bool = False

    def sees(self, org: Any) -> bool:
        return org is None or self.is_platform or str(org) in self.org_ids

    def may_write(self, org: Any) -> bool:
        return self.is_platform or (org is not None and str(org) in self.org_ids)


SYSTEM_VIEW = Visibility(is_platform=True)
_GUC = text("SELECT current_setting('app.org_ids', true), current_setting('app.is_platform', true)")


# The TN view of the current request when there is no Postgres session to read it from
# (``NO_POSTGRES``, falsy): bound per request by the catalog routers from the principal
# (``bind_view``), or by a caller with ``bind_view`` / ``principal_view``. Unbound = anonymous.
_VIEW: ContextVar[Visibility | None] = ContextVar("td_catalog_view", default=None)


def principal_view(principal: Any) -> Visibility:
    """The TN predicate ``tenant_context`` would set for ``principal`` (None = anonymous)."""
    if principal is None:
        return Visibility()
    return Visibility(frozenset(str(o) for o in principal.org_ids), bool(principal.is_platform))


def bind_view(view: Visibility) -> None:
    _VIEW.set(view)


async def visibility(session: Any) -> Visibility:
    """TN context of the caller's transaction (``tenant_context`` / ``system_context`` GUCs).
    Without a Postgres session (``None`` / falsy ``NO_POSTGRES``): the bound request view."""
    if not session:
        bound = _VIEW.get()
        if bound is not None:
            return bound
        # No route binding (another module calling catalog.public without Postgres): core's
        # request context -- a named system job sees everything, else the request principal.
        from app.core.db import rls_scope
        from app.core.request_context import current_principal

        if (await rls_scope(session)).is_platform:
            return SYSTEM_VIEW
        return principal_view(current_principal())
    orgs, plat = (await session.execute(_GUC)).one()
    return Visibility(frozenset(o for o in (orgs or "").split(",") if o), (plat or "off") == "on")


# =========================================================================== doc <-> ORM


def _u(v: Any) -> uuid.UUID | None:
    return uuid.UUID(str(v)) if v else None


def _dt(v: Any) -> datetime | None:
    if v is None:
        return None
    if isinstance(v, datetime):
        v = v.astimezone(UTC)
        return datetime(v.year, v.month, v.day, v.hour, v.minute, v.second, v.microsecond, tzinfo=UTC)
    return datetime.fromisoformat(str(v)).astimezone(UTC)


def _pct(v: Any) -> Decimal:
    return Decimal(str(v if v is not None else 0)).quantize(Decimal("0.01"))


def _orm[T](cls: type[T], d: dict[str, Any]) -> T:
    """A transient instance of ``cls`` from a document (column keys only, model types)."""
    kw: dict[str, Any] = {}
    for col in cls.__table__.columns:  # type: ignore[attr-defined]
        v = d.get(col.key)
        t = col.type
        if isinstance(t, PG_UUID):
            v = _u(v)
        elif isinstance(t, DateTime):
            v = _dt(v)
        elif isinstance(t, Numeric):
            v = _pct(v)
        elif isinstance(t, ARRAY):
            v = list(v or [])
        kw[col.key] = v
    return cls(**kw)


def course_of(d: dict[str, Any]) -> Course:
    return _orm(Course, d)


def version_of(d: dict[str, Any]) -> CourseVersion:
    return _orm(CourseVersion, d)


def lesson_of(d: dict[str, Any]) -> Lesson:
    return _orm(Lesson, d)


def asset_of(d: dict[str, Any]) -> LessonAsset:
    return _orm(LessonAsset, d)


def resource_of(d: dict[str, Any]) -> Resource:
    return _orm(Resource, d)


def modules_of(v: dict[str, Any]) -> list[CourseModule]:
    return [
        CourseModule(
            id=_u(m["id"]),
            course_version_id=_u(v["id"]),
            organization_id=_u(v.get("organization_id")),
            module_key=_u(m["module_key"]),
            title=m["title"],
            position=int(m["position"]),
        )
        for m in _outline(v)
    ]


def _outline(v: dict[str, Any]) -> list[dict[str, Any]]:
    return sorted(v.get("outline") or [], key=lambda m: (int(m["position"]), str(m["id"])))


def outline_lesson_ids(v: dict[str, Any]) -> list[str]:
    return [str(le["id"]) for m in _outline(v) for le in m.get("lessons") or []]


def _summary(le: dict[str, Any]) -> dict[str, Any]:
    return {"id": str(le["id"]), **{k: le.get(k) for k in LESSON_SUMMARY}}


def rebuild_outline(version: dict[str, Any], lessons: Iterable[dict[str, Any]]) -> None:
    """Embedded outline + ``lesson_count`` + ``duration_seconds`` from the version's modules and
    its lesson documents (lessons ordered by position within their module)."""
    by_mod: dict[str, list[dict[str, Any]]] = {}
    for le in lessons:
        by_mod.setdefault(str(le["course_module_id"]), []).append(le)
    out = []
    for m in _outline(version):
        ls = sorted(by_mod.get(str(m["id"]), []), key=lambda x: (int(x["position"]), str(x["id"])))
        out.append(
            {
                "id": str(m["id"]),
                "module_key": str(m["module_key"]),
                "title": m["title"],
                "position": int(m["position"]),
                "lessons": [_summary(x) for x in ls],
            }
        )
    version["outline"] = out
    _recount(version)


def _recount(version: dict[str, Any]) -> None:
    flat = [le for m in version.get("outline") or [] for le in m.get("lessons") or []]
    version["lesson_count"] = len(flat)
    version["duration_seconds"] = sum(int(le.get("duration_seconds") or 0) for le in flat)


def _update_summary(version: dict[str, Any], lesson: dict[str, Any]) -> None:
    for m in version.get("outline") or []:
        for i, le in enumerate(m.get("lessons") or []):
            if str(le["id"]) == str(lesson["id"]):
                m["lessons"][i] = _summary(lesson)
    _recount(version)


def card_of(version: dict[str, Any], published_at: datetime) -> dict[str, Any]:
    return {
        "title": version["title"],
        "summary": version.get("summary"),
        "level": version.get("level"),
        "language": version.get("language"),
        "category": version.get("category"),
        "tags": list(version.get("tags") or []),
        "published_at": published_at,
        "lesson_count": int(version.get("lesson_count") or 0),
        "duration_seconds": int(version.get("duration_seconds") or 0),
    }


def card_version(c: dict[str, Any]) -> CourseVersion:
    """The current published version's card fields as a transient ``CourseVersion`` (public
    listing: no extra read per course)."""
    card = c.get("card") or {}
    return CourseVersion(
        id=_u(c.get("current_version_id")),
        course_id=_u(c["id"]),
        title=card.get("title"),
        summary=card.get("summary"),
        level=card.get("level"),
        language=card.get("language"),
        category=card.get("category"),
        tags=list(card.get("tags") or []),
        published_at=_dt(card.get("published_at")),
    )


def card_counts(c: dict[str, Any]) -> tuple[int, int]:
    card = c.get("card") or {}
    return int(card.get("lesson_count") or 0), int(card.get("duration_seconds") or 0)


def _clean(d: dict[str, Any]) -> dict[str, Any]:
    """Store form (UUID -> str, aware datetimes) of an in-memory document."""
    out: dict[str, Any] = to_store(d)
    return out


def _like_regex(like: str) -> re.Pattern[str]:
    """SQL ``ILIKE`` pattern (``%``, ``_``, ``\\`` escapes) as a case-insensitive regex."""
    out, esc = [], False
    for ch in like:
        if esc:
            out.append(re.escape(ch))
            esc = False
        elif ch == "\\":
            esc = True
        elif ch == "%":
            out.append(".*")
        elif ch == "_":
            out.append(".")
        else:
            out.append(re.escape(ch))
    return re.compile("".join(out), re.IGNORECASE | re.DOTALL)


def _chunks(ids: Sequence[str], n: int = IN_CHUNK) -> Iterable[list[str]]:
    for i in range(0, len(ids), n):
        yield list(ids[i : i + n])


def _not_found() -> ProblemError:
    return ProblemError("not_found")


# =========================================================================== reads


class CatalogReadRepo(FirestoreRepository):
    """Reads on the ``catalog.read`` job, filtered by the caller's TN visibility."""

    def __init__(self, store: ScopedStore, vis: Visibility) -> None:
        super().__init__(store)
        self.vis = vis

    # ------------------------------------------------------------------ primitives

    async def _all(self, coll: str, filters: Sequence[Filter]) -> list[Doc]:
        out: list[Doc] = []
        cursor: str | None = None
        while True:
            page = await self.store.query(coll, filters=filters, order_by=(), limit=_PAGE, cursor=cursor)
            out.extend(page.items)
            if not page.next_cursor:
                return out
            cursor = page.next_cursor

    async def _in(self, coll: str, fld: str, values: Iterable[str]) -> list[Doc]:
        vals = list(dict.fromkeys(str(v) for v in values))
        out: list[Doc] = []
        for chunk in _chunks(vals):
            out.extend(await self._all(coll, [(fld, "in", chunk)]))
        return out

    def _vis(self, docs: Iterable[Doc]) -> list[Doc]:
        return [d for d in docs if self.vis.sees(d.get("organization_id"))]

    async def _get(self, coll: str, doc_id: Any) -> Doc | None:
        if doc_id is None:
            return None
        d = await self.store.get(coll, str(doc_id))
        return d if d is not None and self.vis.sees(d.get("organization_id")) else None

    async def _get_many(self, coll: str, ids: Iterable[Any]) -> dict[str, Doc]:
        got = await self.store.get_many(coll, [str(i) for i in ids if i is not None])
        return {k: d for k, d in got.items() if self.vis.sees(d.get("organization_id"))}

    async def _scan_desc(
        self,
        coll: str,
        filters: Sequence[Filter],
        keep: Any,
        limit: int,
        after_id: str | None,
    ) -> tuple[list[Doc], bool]:
        """Keyset scan by ``id`` descending with an in-memory predicate (``keep(doc)``, may be
        async); returns up to ``limit`` matches and whether more exist."""
        got: list[Doc] = []
        last = after_id
        while True:
            f: list[Filter] = list(filters)
            if last:
                f.append(("id", "<", last))
            page = await self.store.query(coll, filters=f, order_by=(("id", "desc"),), limit=_PAGE)
            for d in page.items:
                ok = keep(d)
                if not isinstance(ok, bool):
                    ok = await ok
                if ok:
                    got.append(d)
                    if len(got) > limit:
                        return got[:limit], True
            if not page.next_cursor or not page.items:
                return got, False
            last = page.items[-1]["id"]

    # ------------------------------------------------------------------ scope lookups (system)

    @platform_only(READ_MARK)
    async def status_counts(self) -> dict[str, int]:
        """Visible, not soft-deleted courses per status (admin dashboard ADM-01)."""
        out: dict[str, int] = {}
        for d in self._vis(await self._all(COURSES, [("deleted_at", "==", None)])):
            out[d["status"]] = out.get(d["status"], 0) + 1
        return out

    @platform_only(READ_MARK)
    async def course_org(self, course_id: uuid.UUID) -> tuple[bool, uuid.UUID | None]:
        """(exists, organization_id) without the TN filter (rbac / scope lookups)."""
        d = await self.store.get(COURSES, str(course_id))
        return (d is not None, _u(d.get("organization_id")) if d else None)

    @platform_only(READ_MARK)
    async def lesson_scope(self, lesson_id: uuid.UUID) -> tuple[uuid.UUID, uuid.UUID | None] | None:
        d = await self.store.get(LESSONS, str(lesson_id))
        if d is None:
            return None
        cid = _u(d.get("course_id"))
        assert cid is not None
        return cid, _u(d.get("organization_id"))

    @platform_only(READ_MARK)
    async def asset_lesson_id(self, asset_id: uuid.UUID) -> uuid.UUID | None:
        d = await self.store.get(ASSETS, str(asset_id))
        return _u(d.get("lesson_id")) if d else None

    @platform_only(READ_MARK)
    async def resource_scope(
        self, resource_id: uuid.UUID
    ) -> tuple[uuid.UUID | None, uuid.UUID | None] | None:
        d = await self.store.get(RESOURCES, str(resource_id))
        return None if d is None else (_u(d.get("course_id")), _u(d.get("organization_id")))

    # ------------------------------------------------------------------ batch loaders

    @platform_only(READ_MARK)
    async def course_doc(self, course_id: Any) -> Doc | None:
        return await self._get(COURSES, course_id)

    @platform_only(READ_MARK)
    async def courses(self, ids: Iterable[Any]) -> dict[uuid.UUID, Course]:
        return {uuid.UUID(k): course_of(d.data) for k, d in (await self._get_many(COURSES, ids)).items()}

    @platform_only(READ_MARK)
    async def versions(self, ids: Iterable[Any]) -> dict[uuid.UUID, CourseVersion]:
        return {uuid.UUID(k): version_of(d.data) for k, d in (await self._get_many(VERSIONS, ids)).items()}

    @platform_only(READ_MARK)
    async def version_docs(self, ids: Iterable[Any]) -> dict[str, Doc]:
        return await self._get_many(VERSIONS, ids)

    @platform_only(READ_MARK)
    async def lessons(self, ids: Iterable[Any]) -> dict[uuid.UUID, Lesson]:
        return {uuid.UUID(k): lesson_of(d.data) for k, d in (await self._get_many(LESSONS, ids)).items()}

    @platform_only(READ_MARK)
    async def lesson_docs(self, ids: Iterable[Any]) -> dict[str, Doc]:
        return await self._get_many(LESSONS, ids)

    @platform_only(READ_MARK)
    async def assets(self, ids: Iterable[Any]) -> dict[uuid.UUID, LessonAsset]:
        return {uuid.UUID(k): asset_of(d.data) for k, d in (await self._get_many(ASSETS, ids)).items()}

    @platform_only(READ_MARK)
    async def resources(self, ids: Iterable[Any]) -> dict[uuid.UUID, Resource]:
        return {uuid.UUID(k): resource_of(d.data) for k, d in (await self._get_many(RESOURCES, ids)).items()}

    # ------------------------------------------------------------------ courses / versions

    @platform_only(READ_MARK)
    async def course_versions(self, course_id: uuid.UUID) -> list[CourseVersion]:
        """Every visible version of a course, newest ``version_no`` first."""
        docs = self._vis(await self._all(VERSIONS, [("course_id", "==", str(course_id))]))
        return sorted((version_of(d.data) for d in docs), key=lambda v: v.version_no, reverse=True)

    @platform_only(READ_MARK)
    async def editable_version(self, course_id: uuid.UUID) -> CourseVersion | None:
        docs = self._vis(await self._all(VERSIONS, [("course_id", "==", str(course_id))]))
        ed = sorted((d for d in docs if d.get("status") in EDITABLE), key=lambda d: d.id)
        return version_of(ed[0].data) if ed else None

    @platform_only(READ_MARK)
    async def version_tree(
        self, version_id: uuid.UUID
    ) -> tuple[
        list[CourseModule],
        dict[uuid.UUID, list[Lesson]],
        dict[uuid.UUID, list[LessonAsset]],
        dict[uuid.UUID, list[dict[str, Any]]],
    ]:
        """``service.version_tree`` plus the lessons' topics (embedded, primary first)."""
        v = await self.store.get(VERSIONS, str(version_id))
        if v is None:
            return [], {}, {}, {}
        modules = modules_of(v.data)
        by_module: dict[uuid.UUID, list[Lesson]] = {m.id: [] for m in modules}
        topics: dict[uuid.UUID, list[dict[str, Any]]] = {}
        ids = outline_lesson_ids(v.data)
        docs = await self._get_many(LESSONS, ids)
        lessons = [lesson_of(docs[i].data) for i in ids if i in docs]
        lessons.sort(key=lambda le: (le.position, str(le.id)))
        for le in lessons:
            by_module.setdefault(le.course_module_id, []).append(le)
            topics[le.id] = _topics(docs[str(le.id)].get("topics"))
        assets: dict[uuid.UUID, list[LessonAsset]] = {}
        if lessons:
            rows = [asset_of(d.data) for d in self._vis(await self._in(ASSETS, "lesson_id", list(docs)))]
            for a in sorted(rows, key=lambda a: (a.position, str(a.id))):
                assets.setdefault(a.lesson_id, []).append(a)
        return modules, by_module, assets, topics

    @platform_only(READ_MARK)
    async def lesson_counts(self, version_ids: Iterable[Any]) -> dict[uuid.UUID, tuple[int, int]]:
        docs = await self._get_many(VERSIONS, version_ids)
        return {
            uuid.UUID(k): (int(d.get("lesson_count") or 0), int(d.get("duration_seconds") or 0))
            for k, d in docs.items()
            if int(d.get("lesson_count") or 0) > 0
        }

    @platform_only(READ_MARK)
    async def public_course_by_slug(self, slug: str) -> tuple[Course, CourseVersion] | None:
        idx = await self.store.get(COURSES_BY_SLUG, slug_id(None, slug))
        if idx is None:
            return None
        c = await self._get(COURSES, idx["course_id"])
        if c is None or not _public(c.data) or c.get("visibility") not in ("public", "unlisted"):
            return None
        v = await self._get(VERSIONS, c.get("current_version_id"))
        if v is None:
            return None
        return course_of(c.data), version_of(v.data)

    @platform_only(READ_MARK)
    async def public_list(
        self,
        *,
        category: str | None,
        level: str | None,
        price_type: str | None,
        language: str | None,
        is_free: bool | None,
        after_id: str | None,
        limit: int,
    ) -> tuple[list[dict[str, Any]], bool]:
        """Published public platform courses (cards), id descending."""

        def keep(d: Doc) -> bool:
            c, card = d.data, d.get("card") or {}
            if not _public(c) or not self.vis.sees(c.get("organization_id")):
                return False
            if category and card.get("category") != category:
                return False
            if level and card.get("level") != level:
                return False
            if language and card.get("language") != language:
                return False
            if price_type and bool(c.get("is_free")) != (price_type == "free"):
                return False
            if is_free is not None and bool(c.get("is_free")) != is_free:
                return False
            return True

        docs, more = await self._scan_desc(
            COURSES,
            [("status", "==", "published"), ("visibility", "==", "public"), ("organization_id", "==", None)],
            keep,
            limit,
            after_id,
        )
        return [d.data for d in docs], more

    @platform_only(READ_MARK)
    async def free_resources(self, limit: int) -> list[tuple[Resource, str | None]]:
        cache: dict[str, Doc | None] = {}

        async def keep(d: Doc) -> bool:
            cid = d.get("course_id")
            if cid is None:
                return True
            if cid not in cache:
                cache[cid] = await self._get(COURSES, cid)
            c = cache[cid]
            return c is not None and c.get("status") == "published" and c.get("deleted_at") is None

        docs, _ = await self._scan_desc(
            RESOURCES,
            [("access_level", "==", "public"), ("organization_id", "==", None)],
            keep,
            limit,
            None,
        )
        out: list[tuple[Resource, str | None]] = []
        for d in docs[:limit]:
            c = cache.get(d.get("course_id")) if d.get("course_id") else None
            out.append((resource_of(d.data), c.get("slug") if c else None))
        return out

    @platform_only(READ_MARK)
    async def studio_list(
        self,
        *,
        platform: bool,
        orgs: set[uuid.UUID],
        course_ids: set[uuid.UUID],
        status: str | None,
        after_id: str | None,
        limit: int,
    ) -> tuple[list[Course], dict[uuid.UUID, CourseVersion], bool]:
        def keep(d: Doc) -> bool:
            return (
                d.get("deleted_at") is None
                and (status is None or d.get("status") == status)
                and self.vis.sees(d.get("organization_id"))
            )

        if platform:
            docs, more = await self._scan_desc(COURSES, [], keep, limit, after_id)
        else:
            found: dict[str, Doc] = {}
            for o in orgs:
                for d in await self._all(COURSES, [("organization_id", "==", str(o))]):
                    found[d.id] = d
            found.update(await self.store.get_many(COURSES, [str(c) for c in course_ids]))
            cands = sorted(
                (d for d in found.values() if keep(d) and (after_id is None or d.id < after_id)),
                key=lambda d: d.id,
                reverse=True,
            )
            docs, more = cands[:limit], len(cands) > limit
        rows = [course_of(d.data) for d in docs]
        drafts: dict[uuid.UUID, CourseVersion] = {}
        for v in self._vis(await self._in(VERSIONS, "course_id", [d.id for d in docs])):
            if v.get("status") in EDITABLE:
                drafts[uuid.UUID(v["course_id"])] = version_of(v.data)
        return rows, drafts, more

    # ------------------------------------------------------------------ lessons

    @platform_only(READ_MARK)
    async def find_lessons(
        self,
        *,
        lesson_key: uuid.UUID | None,
        version_id: uuid.UUID | None,
        assignment_id: uuid.UUID | None,
        required_only: bool,
    ) -> list[Lesson]:
        f: list[Filter] = []
        if lesson_key is not None:
            f.append(("lesson_key", "==", str(lesson_key)))
        if version_id is not None:
            f.append(("course_version_id", "==", str(version_id)))
        if assignment_id is not None:
            f.append(("assignment_id", "==", str(assignment_id)))
        if required_only:
            f.append(("is_required", "==", True))
        return [lesson_of(d.data) for d in self._vis(await self._all(LESSONS, f))]

    @platform_only(READ_MARK)
    async def version_lessons(self, version_id: uuid.UUID) -> list[Lesson]:
        docs = self._vis(await self._all(LESSONS, [("course_version_id", "==", str(version_id))]))
        return [lesson_of(d.data) for d in docs]

    @platform_only(READ_MARK)
    async def lesson_with_parents(
        self, lesson_id: uuid.UUID, statuses: Sequence[str]
    ) -> tuple[Lesson, CourseVersion, Course] | None:
        le = await self._get(LESSONS, lesson_id)
        if le is None:
            return None
        v = await self._get(VERSIONS, le.get("course_version_id"))
        if v is None or v.get("status") not in statuses:
            return None
        c = await self._get(COURSES, v.get("course_id"))
        if c is None or c.get("deleted_at") is not None:
            return None
        return lesson_of(le.data), version_of(v.data), course_of(c.data)

    @platform_only(READ_MARK)
    async def asset_with_parents(
        self, asset_id: uuid.UUID, statuses: Sequence[str]
    ) -> tuple[LessonAsset, Lesson, CourseVersion, Course] | None:
        a = await self._get(ASSETS, asset_id)
        if a is None:
            return None
        got = await self.lesson_with_parents(_u(a.get("lesson_id")), statuses)  # type: ignore[arg-type]
        return None if got is None else (asset_of(a.data), *got)

    @platform_only(READ_MARK)
    async def course_ids_for_lessons(
        self,
        *,
        lesson_id: uuid.UUID | None,
        match_lesson_key: bool,
        coding_problem_id: uuid.UUID | None,
        test_id: uuid.UUID | None,
    ) -> list[uuid.UUID]:
        docs: list[Doc] = []
        if lesson_id is not None:
            d = await self.store.get(LESSONS, str(lesson_id))
            docs = [d] if d is not None else []
            if match_lesson_key:
                docs += await self._all(LESSONS, [("lesson_key", "==", str(lesson_id))])
        elif coding_problem_id is not None:
            docs = await self._all(LESSONS, [("coding_problem_id", "==", str(coding_problem_id))])
        elif test_id is not None:
            docs = await self._all(LESSONS, [("test_id", "==", str(test_id))])
        docs = self._vis(docs)
        # PG joins course_versions under RLS too (same organization as its lessons).
        return [uuid.UUID(c) for c in dict.fromkeys(str(d["course_id"]) for d in docs)]

    @platform_only(READ_MARK)
    async def current_outline_lessons(self, course_id: uuid.UUID) -> list[tuple[uuid.UUID, str, bool]]:
        c = await self._get(COURSES, course_id)
        if c is None:
            return []
        v = await self._get(VERSIONS, c.get("current_version_id"))
        if v is None:
            return []
        return [
            (uuid.UUID(str(le["lesson_key"])), le["title"], bool(le.get("is_required")))
            for m in _outline(v.data)
            for le in sorted(m.get("lessons") or [], key=lambda x: (int(x["position"]), str(x["id"])))
        ]

    @platform_only(READ_MARK)
    async def search_published_lessons(
        self, org_id: uuid.UUID, like: str, limit: int
    ) -> list[tuple[uuid.UUID, str, str, str]]:
        rx = _like_regex(like)
        out: list[tuple[uuid.UUID, str, str, str]] = []
        courses = self._vis(await self._all(COURSES, [("status", "==", "published")]))
        courses = [
            c
            for c in courses
            if c.get("organization_id") in (None, str(org_id)) and c.get("current_version_id")
        ]
        vdocs = await self._get_many(VERSIONS, [c["current_version_id"] for c in courses])
        for c in sorted(courses, key=lambda d: d.id):
            v = vdocs.get(c["current_version_id"])
            if v is None:
                continue
            for m in _outline(v.data):
                for le in m.get("lessons") or []:
                    if rx.fullmatch(le.get("title") or ""):
                        out.append((uuid.UUID(str(le["id"])), le["title"], le["lesson_type"], c["title"]))
                        if len(out) >= limit:
                            return out
        return out

    # ------------------------------------------------------------------ assets / resources

    @platform_only(READ_MARK)
    async def lesson_assets(self, lesson_id: uuid.UUID, include_retired: bool) -> list[LessonAsset]:
        docs = self._vis(await self._all(ASSETS, [("lesson_id", "==", str(lesson_id))]))
        rows = [asset_of(d.data) for d in docs if include_retired or d.get("status") != "retired"]
        return sorted(rows, key=lambda a: (a.position, str(a.id)))

    @platform_only(READ_MARK)
    async def lesson_resources(self, lesson_id: uuid.UUID) -> list[Resource]:
        docs = self._vis(await self._all(RESOURCES, [("lesson_id", "==", str(lesson_id))]))
        return sorted((resource_of(d.data) for d in docs), key=lambda r: str(r.id))

    @platform_only(READ_MARK)
    async def assets_by_s3_key(self, s3_key: str) -> list[LessonAsset]:
        return [asset_of(d.data) for d in self._vis(await self._all(ASSETS, [("s3_key", "==", s3_key)]))]

    @platform_only(READ_MARK)
    async def pending_scan_assets(self, limit: int) -> list[LessonAsset]:
        """S3 assets waiting for a scan result, oldest first. Firestore has no ``FOR UPDATE SKIP
        LOCKED``: two concurrent sweeps may pick the same asset (the update is idempotent)."""
        docs = self._vis(
            await self._all(ASSETS, [("provider", "==", "s3"), ("scan_status", "==", "pending")])
        )
        rows = sorted((d for d in docs if d.get("s3_key") is not None), key=lambda d: d.id)
        return [asset_of(d.data) for d in rows[:limit]]

    @platform_only(READ_MARK)
    async def list_resources(
        self,
        *,
        course_id: uuid.UUID | None,
        lesson_id: uuid.UUID | None,
        company_id: uuid.UUID | None,
        after_id: str | None,
        limit: int,
    ) -> tuple[list[Resource], bool]:
        def keep(d: Doc) -> bool:
            return (
                self.vis.sees(d.get("organization_id"))
                and (course_id is None or d.get("course_id") == str(course_id))
                and (lesson_id is None or d.get("lesson_id") == str(lesson_id))
                and (company_id is None or d.get("company_id") == str(company_id))
            )

        f: list[Filter] = (
            [("course_id", "==", str(course_id))]
            if course_id is not None
            else [("company_id", "==", str(company_id))]
        )
        docs, more = await self._scan_desc(RESOURCES, f, keep, limit, after_id)
        return [resource_of(d.data) for d in docs], more


def _public(c: dict[str, Any]) -> bool:
    """``service.public_course_filter``."""
    return (
        c.get("deleted_at") is None
        and c.get("status") == "published"
        and c.get("organization_id") is None
        and c.get("current_version_id") is not None
    )


def _topics(raw: Any) -> list[dict[str, Any]]:
    ts = [{"topic_id": str(t["topic_id"]), "is_primary": bool(t.get("is_primary"))} for t in raw or []]
    return sorted(ts, key=lambda t: (not t["is_primary"], t["topic_id"]))


# =========================================================================== writes


@dataclass
class _Work:
    """In-memory authoring state of one transaction (Firestore: every read before any write)."""

    course: dict[str, Any]
    version: dict[str, Any] = field(default_factory=dict)
    lessons: dict[str, dict[str, Any]] = field(default_factory=dict)
    put_lessons: set[str] = field(default_factory=set)
    del_lessons: dict[str, dict[str, Any]] = field(default_factory=dict)
    put_assets: dict[str, dict[str, Any]] = field(default_factory=dict)
    del_assets: dict[str, dict[str, Any]] = field(default_factory=dict)
    put_resources: dict[str, dict[str, Any]] = field(default_factory=dict)
    others: list[tuple[str, str, dict[str, Any]]] = field(default_factory=list)
    course_dirty: bool = False
    version_dirty: bool = False
    cloned: bool = False  # the draft was cloned in this transaction (nothing of it is stored yet)

    def touch(self) -> None:
        """``service.touch_draft``: any edit of an ``in_review`` version sends it back to draft."""
        if self.version.get("status") == "in_review":
            self.version.update(status="draft", submitted_by=None, submitted_at=None)
        self.version_dirty = True


class CatalogWriteRepo(FirestoreRepository):
    """Authoring writes (methods take the acting ``user_id``) and media writes (``@platform_only``
    markers; built on the ``catalog.write`` job)."""

    def __init__(self, store: ScopedStore, vis: Visibility) -> None:
        super().__init__(store)
        self.vis = vis

    # ------------------------------------------------------------------ helpers

    def _check_write(self, org: Any) -> None:
        if not self.vis.may_write(org):
            # Postgres: the TN WITH CHECK policy refuses the row.
            raise ProblemError("permission_denied", detail="Not allowed to change this catalogue row.")

    async def _course(self, tx: ScopedTransaction, course_id: Any) -> dict[str, Any]:
        d = await tx.get(COURSES, str(course_id))
        if d is None or d.get("deleted_at") is not None or not self.vis.sees(d.get("organization_id")):
            raise _not_found()
        self._check_write(d.get("organization_id"))
        return dict(d.data)

    async def _assets_of(self, tx: ScopedTransaction, lesson_ids: Sequence[str]) -> list[Doc]:
        out: list[Doc] = []
        for chunk in _chunks(list(lesson_ids)):
            out.extend(await tx.query(ASSETS, filters=[("lesson_id", "in", chunk)]))
        return out

    async def _draft(self, tx: ScopedTransaction, course: dict[str, Any], user_id: uuid.UUID) -> _Work:
        """``service.ensure_draft`` inside the transaction (reads only; writes at ``_flush``)."""
        if course.get("status") == "archived":
            raise ProblemError("invalid_state_transition", detail="Archived courses cannot be edited.")
        w = _Work(course=course)
        dv = course.get("draft_version_id")
        if dv:
            vd = await tx.get(VERSIONS, dv)
            if vd is not None and vd.get("status") in EDITABLE:
                w.version = dict(vd.data)
                ids = outline_lesson_ids(w.version)
                got = await tx.get_many(LESSONS, ids)
                w.lessons = {i: dict(got[i].data) for i in ids if i in got}
                return w
        src = (
            await tx.get(VERSIONS, course["current_version_id"]) if course.get("current_version_id") else None
        )
        if src is None:
            raise ProblemError("invalid_state_transition")
        ids = outline_lesson_ids(src.data)
        src_lessons = await tx.get_many(LESSONS, ids)
        src_assets = await self._assets_of(tx, ids)
        self._clone_into(
            w, src.data, [src_lessons[i].data for i in ids if i in src_lessons], src_assets, user_id
        )
        return w

    def _clone_into(
        self,
        w: _Work,
        src: dict[str, Any],
        src_lessons: list[dict[str, Any]],
        src_assets: list[Doc],
        user_id: uuid.UUID,
        *,
        version_id: str | None = None,
        id_map: dict[str, str] | None = None,
    ) -> None:
        course = w.course
        org = course.get("organization_id")
        vid = version_id or str(uuid7())
        no = int(course.get("last_version_no") or 0) + 1
        keep = (
            "title",
            "summary",
            "description_md",
            "outcomes",
            "level",
            "language",
            "category",
            "tags",
            "certificate_rule",
            "completeness_plan",
        )
        w.version = {
            **_new_version(vid, course["id"], org, no, src["title"], None, user_id),
            **{k: src.get(k) for k in keep},
        }
        w.version["outcomes"] = list(src.get("outcomes") or [])
        w.version["tags"] = list(src.get("tags") or [])
        mod_map: dict[str, str] = {}
        outline = []
        for m in _outline(src):
            nm = str(uuid7())
            mod_map[str(m["id"])] = nm
            outline.append(
                {"id": nm, "module_key": str(m["module_key"]), "title": m["title"], "position": m["position"]}
            )
        w.version["outline"] = outline
        lmap = id_map if id_map is not None else {}
        for le in src_lessons:
            nid = lmap.setdefault(str(le["id"]), str(uuid7()))
            nl = {k: v for k, v in le.items() if k not in ("created_at", "updated_at", "schema_version")}
            nl.update(
                id=nid,
                course_module_id=mod_map.get(str(le["course_module_id"]), str(le["course_module_id"])),
                course_version_id=vid,
                organization_id=org,
                topics=_topics(le.get("topics")),
            )
            w.lessons[nid] = nl
            w.put_lessons.add(nid)
        for a in src_assets:
            if str(a["lesson_id"]) not in lmap:
                continue
            aid = str(uuid7())
            na = {k: v for k, v in a.data.items() if k not in ("created_at", "updated_at", "schema_version")}
            na.update(id=aid, lesson_id=lmap[str(a["lesson_id"])], organization_id=org)
            w.put_assets[aid] = na
        rebuild_outline(w.version, w.lessons.values())
        course.update(draft_version_id=vid, last_version_no=no)
        w.course_dirty = w.version_dirty = w.cloned = True

    async def _flush(self, tx: ScopedTransaction, w: _Work) -> None:
        if w.version_dirty or w.put_lessons or w.del_lessons:
            rebuild_outline(w.version, w.lessons.values())
            w.version_dirty = True
        for i, cur in w.del_lessons.items():
            await tx.delete_read(LESSONS, i, cur)
        for i, cur in w.del_assets.items():
            await tx.delete_read(ASSETS, i, cur)
        for i in sorted(w.put_lessons):
            if i in w.lessons:
                await tx.put(LESSONS, i, _clean(w.lessons[i]))
        for i, a in w.put_assets.items():
            await tx.put(ASSETS, i, _clean(a))
        for i, r in w.put_resources.items():
            await tx.put(RESOURCES, i, _clean(r))
        for coll, i, data in w.others:
            await tx.put(coll, i, _clean(data))
        if w.version_dirty:
            await tx.put(VERSIONS, str(w.version["id"]), _clean(w.version))
        if w.course_dirty:
            await tx.put(COURSES, str(w.course["id"]), _clean(w.course))

    async def _maybe_chunked_clone(self, course_id: uuid.UUID, user_id: uuid.UUID) -> None:
        """Large published outlines: clone the draft in chunks before the editing transaction."""
        c = await self.store.get(COURSES, str(course_id))
        if c is None or c.get("draft_version_id") or not c.get("current_version_id"):
            return
        src = await self.store.get(VERSIONS, c["current_version_id"])
        if src is None:
            return
        ids = outline_lesson_ids(src.data)
        assets = await system_reader()._in(ASSETS, "lesson_id", ids) if ids else []
        if len(ids) + len(assets) + 2 <= CLONE_TX_LIMIT:
            return
        self._check_write(c.get("organization_id"))
        lessons = await self.store.get_many(LESSONS, ids)
        w = _Work(course=dict(c.data))
        vid = str(uuid7())
        self._clone_into(
            w, src.data, [lessons[i].data for i in ids if i in lessons], assets, user_id, version_id=vid
        )
        docs: list[tuple[str, str, dict[str, Any]]] = [
            *((LESSONS, i, w.lessons[i]) for i in sorted(w.put_lessons)),
            *((ASSETS, i, a) for i, a in w.put_assets.items()),
        ]
        for start in range(0, len(docs), CLONE_TX_LIMIT):
            part = docs[start : start + CLONE_TX_LIMIT]

            async def write_part(
                tx: ScopedTransaction, part: list[tuple[str, str, dict[str, Any]]] = part
            ) -> None:
                for coll, i, data in part:
                    await tx.put(coll, i, _clean(data))

            await self.store.run_transaction(write_part)
        version, last_no = w.version, w.course["last_version_no"]

        async def finish(tx: ScopedTransaction) -> bool:
            cur = await self._course(tx, course_id)
            if cur.get("draft_version_id") or cur.get("current_version_id") != c.get("current_version_id"):
                return False
            cur.update(
                draft_version_id=vid, last_version_no=max(int(cur.get("last_version_no") or 0) + 1, last_no)
            )
            version["version_no"] = cur["last_version_no"]
            await tx.put(VERSIONS, vid, _clean(version))
            await tx.put(COURSES, str(course_id), _clean(cur))
            return True

        if not await self.store.run_transaction(finish):  # lost the race: drop the chunks
            for coll, i, _ in docs:
                cur_doc = await self.store.get(coll, i)
                if cur_doc is not None:
                    await self.store.delete(coll, i)

    async def _run(
        self, fn: Any, course_id: uuid.UUID | None = None, user_id: uuid.UUID | None = None
    ) -> Any:
        if course_id is not None and user_id is not None:
            await self._maybe_chunked_clone(course_id, user_id)
        try:
            return await self.store.run_transaction(fn)
        except UniqueViolationError as e:
            if e.collection == COURSES_BY_SLUG:
                raise _slug_conflict() from e
            raise

    # ------------------------------------------------------------------ courses

    async def create_course(
        self,
        user_id: uuid.UUID,
        *,
        organization_id: uuid.UUID | None,
        slug: str,
        title: str,
        course_kind: str,
        visibility: str,
        is_free: bool,
        summary: str | None,
        certificate_rule: dict[str, Any],
    ) -> tuple[Course, CourseVersion]:
        self._check_write(organization_id)
        cid, vid = str(uuid7()), str(uuid7())
        org = str(organization_id) if organization_id else None
        sid = slug_id(organization_id, slug)

        async def fn(tx: ScopedTransaction) -> tuple[dict[str, Any], dict[str, Any]]:
            idx = await self._slug_free(tx, sid, None)
            course = _new_course(cid, org, slug, title, course_kind, visibility, is_free, user_id)
            course.update(draft_version_id=vid, last_version_no=1)
            version = _new_version(vid, cid, org, 1, title, summary, user_id)
            version["certificate_rule"] = dict(certificate_rule)
            if idx is None:  # a concurrent create of the same slug fails the commit (409)
                await tx.create(COURSES_BY_SLUG, {"course_id": cid}, doc_id=sid)
            else:  # the slug of a soft-deleted course is free again
                await tx.put(COURSES_BY_SLUG, sid, {"course_id": cid})
            await tx.put(COURSES, cid, _clean(course))
            await tx.put(VERSIONS, vid, _clean(version))
            return course, version

        try:
            course, version = await self._run(fn)
        except UniqueViolationError as e:  # the slug index was created concurrently
            raise _slug_conflict() from e
        now = utcnow()
        for d in (course, version):
            d.setdefault("created_at", now)
            d.setdefault("updated_at", now)
        return course_of(_clean(course)), version_of(_clean(version))

    async def _slug_free(self, tx: ScopedTransaction, sid: str, own: str | None) -> Doc | None:
        """409 when ``sid`` is held by another live course; returns the index document."""
        idx = await tx.get(COURSES_BY_SLUG, sid)
        if idx is None or idx.get("course_id") == own:
            return idx
        holder = await tx.get(COURSES, idx["course_id"])
        if holder is not None and holder.get("deleted_at") is None:
            raise _slug_conflict()
        return idx

    async def patch_draft(
        self, user_id: uuid.UUID, course_id: uuid.UUID, data: dict[str, Any]
    ) -> tuple[Course, CourseVersion, dict[str, Any]]:
        """``router.patch_draft`` (ensure draft, slug change, course settings, version fields)."""

        async def fn(tx: ScopedTransaction) -> tuple[_Work, dict[str, Any]]:
            d = dict(data)
            course = await self._course(tx, course_id)
            w = await self._draft(tx, course, user_id)
            before: dict[str, Any] = {k: course.get(k) for k in ("slug", "visibility", "is_free") if k in d}
            if "slug" in d and d["slug"] is not None and d["slug"] != course["slug"]:
                org = course.get("organization_id")
                new_sid, old_sid = slug_id(org, d["slug"]), slug_id(org, course["slug"])
                if new_sid != old_sid:
                    await self._slug_free(tx, new_sid, course["id"])
                    old = await tx.get(COURSES_BY_SLUG, old_sid)
                    if old is not None and old.get("course_id") == course["id"]:
                        w.others.append(("__delete__", old_sid, dict(old.data)))
                    w.others.append((COURSES_BY_SLUG, new_sid, {"course_id": course["id"]}))
                course["slug_lc"] = str(d["slug"]).lower()
            for k in ("slug", "visibility", "is_free", "course_kind"):
                if k in d and d[k] is not None:
                    course[k] = d.pop(k)
                    w.course_dirty = True
                else:
                    d.pop(k, None)
            for k, v in d.items():
                if k in ("certificate_rule", "completeness_plan"):
                    w.version[k] = v
                elif k in ("outcomes", "tags"):
                    w.version[k] = list(v or [])
                elif v is not None or k in ("summary", "description_md", "level", "category"):
                    w.version[k] = v
            w.touch()
            await self._flush_with_slug_deletes(tx, w)
            return w, before

        w, before = await self._run(fn, course_id, user_id)
        return course_of(_clean(w.course)), version_of(_clean(w.version)), before

    async def _flush_with_slug_deletes(self, tx: ScopedTransaction, w: _Work) -> None:
        deletes = [(i, cur) for coll, i, cur in w.others if coll == "__delete__"]
        w.others = [o for o in w.others if o[0] != "__delete__"]
        for i, cur in deletes:
            await tx.delete_read(COURSES_BY_SLUG, i, cur)
        await self._flush(tx, w)

    async def replace_outline(
        self, user_id: uuid.UUID, course_id: uuid.UUID, modules_in: list[dict[str, Any]]
    ) -> tuple[Course, CourseVersion]:
        from app.modules.catalog.service import vf

        async def fn(tx: ScopedTransaction) -> _Work:
            course = await self._course(tx, course_id)
            w = await self._draft(tx, course, user_id)
            modules = {str(m["module_key"]): m for m in w.version.get("outline") or []}
            lessons = w.lessons
            seen_lessons: set[str] = set()
            seen_modules: set[str] = set()
            for i, mi in enumerate(modules_in):
                mk = str(mi["module_key"]) if mi.get("module_key") is not None else None
                if mk is not None and mk not in modules:
                    raise vf(f"modules.{i}.module_key", "unknown", "No such module in the draft")
                if mk is not None and mk in seen_modules:
                    raise vf(f"modules.{i}.module_key", "duplicate", "Module listed twice")
                for lid in (str(x) for x in mi["lesson_ids"]):
                    if lid not in lessons:
                        raise vf(f"modules.{i}.lesson_ids", "unknown", "Lesson is not part of the draft")
                    if lid in seen_lessons:
                        raise vf(f"modules.{i}.lesson_ids", "duplicate", "Lesson listed twice")
                    seen_lessons.add(lid)
                if mk is not None:
                    seen_modules.add(mk)
            outline = []
            for i, mi in enumerate(modules_in):
                mk = str(mi["module_key"]) if mi.get("module_key") is not None else None
                if mk is not None:
                    m = {**modules[mk], "title": mi["title"], "position": i}
                else:
                    m = {"id": str(uuid7()), "module_key": str(uuid7()), "title": mi["title"], "position": i}
                outline.append(m)
                for j, lid in enumerate(str(x) for x in mi["lesson_ids"]):
                    lessons[lid].update(course_module_id=m["id"], position=j)
                    w.put_lessons.add(lid)
            w.version["outline"] = outline
            removed = [lid for lid in lessons if lid not in seen_lessons]
            for lid in removed:
                cur = lessons.pop(lid)
                w.put_lessons.discard(lid)
                if not w.cloned:
                    w.del_lessons[lid] = cur
            if w.cloned:  # removed lessons of a draft cloned in this transaction were never stored
                gone = set(removed)
                w.put_assets = {k: a for k, a in w.put_assets.items() if str(a["lesson_id"]) not in gone}
            elif removed:
                for a in await self._assets_of(tx, removed):  # lesson_assets ON DELETE CASCADE
                    w.del_assets[a.id] = dict(a.data)
                for chunk in _chunks(removed):  # resources.lesson_id ON DELETE SET NULL
                    for r in await tx.query(RESOURCES, filters=[("lesson_id", "in", chunk)]):
                        w.put_resources[r.id] = {**r.data, "lesson_id": None}
            w.touch()
            await self._flush(tx, w)
            return w

        w = await self._run(fn, course_id, user_id)
        return course_of(_clean(w.course)), version_of(_clean(w.version))

    async def add_lesson(
        self,
        user_id: uuid.UUID,
        course_id: uuid.UUID,
        *,
        module_key: uuid.UUID | None,
        module_title: str | None,
        values: dict[str, Any],
    ) -> tuple[Course, Lesson]:
        from app.modules.catalog.service import check_lesson_refs, vf

        check_lesson_refs(values["lesson_type"], values)

        async def fn(tx: ScopedTransaction) -> tuple[_Work, dict[str, Any]]:
            course = await self._course(tx, course_id)
            w = await self._draft(tx, course, user_id)
            modules = _outline(w.version)
            module: dict[str, Any] | None
            if module_key is not None:
                module = next((m for m in modules if str(m["module_key"]) == str(module_key)), None)
                if module is None:
                    raise vf("module_key", "unknown", "No such module in the draft")
            elif module_title or not modules:
                module = {
                    "id": str(uuid7()),
                    "module_key": str(uuid7()),
                    "title": module_title or "Module 1",
                    "position": len(modules),
                    "lessons": [],
                }
                w.version["outline"] = [*modules, module]
            else:
                module = modules[-1]
            positions = [
                int(le["position"])
                for le in w.lessons.values()
                if str(le["course_module_id"]) == str(module["id"])
            ]
            lid = str(uuid7())
            lesson = _clean(
                {
                    **_new_lesson(lid, course, w.version, module["id"]),
                    "position": max(positions) + 1 if positions else 0,
                    **values,
                }
            )
            w.lessons[lid] = lesson
            w.put_lessons.add(lid)
            w.touch()
            await self._flush(tx, w)
            return w, lesson

        w, lesson = await self._run(fn, course_id, user_id)
        now = utcnow()
        return course_of(_clean(w.course)), lesson_of({"created_at": now, "updated_at": now, **lesson})

    async def _editable_lesson(
        self, tx: ScopedTransaction, lesson_id: uuid.UUID
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        le = await tx.get(LESSONS, str(lesson_id))
        if le is None or not self.vis.sees(le.get("organization_id")):
            raise _not_found()
        v = await tx.get(VERSIONS, le["course_version_id"])
        if v is None:
            raise _not_found()
        if v.get("status") not in EDITABLE:
            raise ProblemError(
                "invalid_state_transition",
                detail="Published lessons are immutable. Edit the lesson in the course draft.",
            )
        self._check_write(le.get("organization_id"))
        return dict(le.data), dict(v.data)

    async def patch_lesson(self, user_id: uuid.UUID, lesson_id: uuid.UUID, data: dict[str, Any]) -> Lesson:
        from app.modules.catalog.service import check_lesson_refs

        async def fn(tx: ScopedTransaction) -> dict[str, Any]:
            lesson, version = await self._editable_lesson(tx, lesson_id)
            merged = {
                k: data.get(k, lesson.get(k))
                for k in ("test_id", "coding_problem_id", "assignment_id", "live_url")
            }
            check_lesson_refs(lesson["lesson_type"], merged)
            for k, v in data.items():
                if k in ("is_required", "is_free_preview", "title") and v is None:
                    continue
                lesson[k] = v
            lesson = _clean(lesson)
            w = _Work(course={}, version=version)
            w.touch()
            _update_summary(version, lesson)
            await tx.put(LESSONS, lesson["id"], lesson)
            await tx.put(VERSIONS, version["id"], _clean(version))
            return lesson

        return lesson_of(await self._run(fn))

    async def set_topics(
        self, user_id: uuid.UUID, lesson_id: uuid.UUID, topics: list[dict[str, Any]]
    ) -> Lesson:
        from app.modules.catalog.service import vf

        async def fn(tx: ScopedTransaction) -> dict[str, Any]:
            lesson, version = await self._editable_lesson(tx, lesson_id)
            if topics and sum(1 for t in topics if t["is_primary"]) != 1:
                raise vf("topics", "one_primary", "Exactly one topic must be primary")
            if len({t["topic_id"] for t in topics}) != len(topics):
                raise vf("topics", "duplicate", "Topic listed twice")
            lesson["topics"] = _topics(topics)
            w = _Work(course={}, version=version)
            w.touch()
            await tx.put(LESSONS, lesson["id"], _clean(lesson))
            await tx.put(VERSIONS, version["id"], _clean(version))
            return lesson

        return lesson_of(await self._run(fn))

    async def submit_review(self, user_id: uuid.UUID, course_id: uuid.UUID) -> CourseVersion:
        from app.modules.catalog.service import vf

        async def fn(tx: ScopedTransaction) -> dict[str, Any]:
            course = await self._course(tx, course_id)
            v = await tx.get(VERSIONS, course["draft_version_id"]) if course.get("draft_version_id") else None
            if v is None or v.get("status") != "draft":
                raise ProblemError(
                    "invalid_state_transition", detail="Only a draft can be submitted for review."
                )
            version = dict(v.data)
            if not outline_lesson_ids(version):
                raise vf("outline", "empty", "Add at least one lesson before submitting for review")
            version.update(status="in_review", submitted_by=str(user_id), submitted_at=utcnow())
            await tx.put(VERSIONS, version["id"], _clean(version))
            return version

        return version_of(_clean(await self._run(fn)))

    async def publish(
        self, user_id: uuid.UUID, course_id: uuid.UUID, *, change_type: str, changelog: str | None
    ) -> tuple[Course, CourseVersion]:
        from app.modules.catalog.service import completeness, vf

        async def fn(tx: ScopedTransaction) -> tuple[dict[str, Any], dict[str, Any]]:
            course = await self._course(tx, course_id)
            v = await tx.get(VERSIONS, course["draft_version_id"]) if course.get("draft_version_id") else None
            if v is None or v.get("status") != "in_review":
                raise ProblemError(
                    "invalid_state_transition", detail="Only a version in review can be published."
                )
            version = dict(v.data)
            if course.get("organization_id") is None and str(user_id) in {
                version.get("created_by"),
                version.get("submitted_by"),
            }:
                raise ProblemError(
                    "sod_violation",
                    detail="A different person must publish a version you authored or submitted.",
                )
            ids = outline_lesson_ids(version)
            got = await tx.get_many(LESSONS, ids)
            lessons = [got[i].data for i in ids if i in got]
            if not lessons:
                raise vf("outline", "empty", "The version has no lessons")
            assets = [a.data for a in await self._assets_of(tx, [le["id"] for le in lessons])]
            pending = [a for a in assets if a.get("status") in ("uploading", "processing")]
            if pending:
                raise ProblemError(
                    "validation_failed",
                    422,
                    detail="Some media is still uploading or processing.",
                    errors=[
                        {
                            "field": f"assets.{a['id']}",
                            "code": "media_processing",
                            "message": "Media not ready",
                        }
                        for a in pending
                    ],
                )
            ready = {
                a["lesson_id"]
                for a in assets
                if a.get("asset_type") == "video" and a.get("status") == "available"
            }
            missing = [le for le in lessons if le.get("lesson_type") == "video" and le["id"] not in ready]
            if missing:
                raise ProblemError(
                    "validation_failed",
                    422,
                    detail="Every video lesson needs a ready video.",
                    errors=[
                        {"field": f"lessons.{le['id']}", "code": "video_missing", "message": "No ready video"}
                        for le in missing
                    ],
                )
            prev = (
                await tx.get(VERSIONS, course["current_version_id"])
                if course.get("current_version_id")
                else None
            )
            now = utcnow()
            rebuild_outline(version, lessons)
            version.update(
                status="published",
                published_at=now,
                published_by=str(user_id),
                change_type=change_type if course.get("current_version_id") is not None else "major",
                changelog=changelog,
            )
            pct = completeness(version_of(_clean(version)), len(lessons))
            course.update(
                current_version_id=version["id"],
                status="published",
                title=version["title"],
                completeness_pct=float(pct),
                card=card_of(version, now),
                published_at=now,
                draft_version_id=None,
            )
            if prev is not None and prev.get("status") == "published":
                await tx.put(VERSIONS, prev.id, _clean({**prev.data, "status": "superseded"}))
            await tx.put(VERSIONS, version["id"], _clean(version))
            await tx.put(COURSES, course["id"], _clean(course))
            return course, version

        course, version = await self._run(fn)
        return course_of(_clean(course)), version_of(_clean(version))

    async def archive(self, user_id: uuid.UUID, course_id: uuid.UUID) -> tuple[Course, str]:
        async def fn(tx: ScopedTransaction) -> tuple[dict[str, Any], str]:
            course = await self._course(tx, course_id)
            if course.get("status") == "archived":
                raise ProblemError("invalid_state_transition", detail="Course is already archived.")
            before = str(course["status"])
            course["status"] = "archived"
            await tx.put(COURSES, course["id"], _clean(course))
            return course, before

        course, before = await self._run(fn)
        return course_of(_clean(course)), before

    # ------------------------------------------------------------------ resources

    async def create_resource(self, user_id: uuid.UUID, fields: dict[str, Any]) -> Resource:
        self._check_write(fields.get("organization_id"))
        rid = str(uuid7())
        now = utcnow()
        doc = _clean({**_RESOURCE_DEFAULTS, **fields, "id": rid, "created_by": user_id})

        async def fn(tx: ScopedTransaction) -> None:
            await tx.put(RESOURCES, rid, doc)

        await self._run(fn)
        return resource_of({"created_at": now, "updated_at": now, **doc})

    async def patch_resource(
        self, user_id: uuid.UUID, resource_id: uuid.UUID, data: dict[str, Any]
    ) -> Resource:
        from app.modules.catalog.service import vf

        async def fn(tx: ScopedTransaction) -> dict[str, Any]:
            d = await tx.get(RESOURCES, str(resource_id))
            if d is None or not self.vis.sees(d.get("organization_id")):
                raise _not_found()
            self._check_write(d.get("organization_id"))
            r = dict(d.data)
            for k, v in data.items():
                if k in ("title", "access_level") and v is None:
                    continue
                r[k] = v
            r["is_public"] = r.get("access_level") == "public"
            if not (r.get("s3_key") or r.get("url")):
                raise vf("s3_key", "required", "A file key or an https URL is required")
            r = _clean(r)
            await tx.put(RESOURCES, r["id"], r)
            return r

        return resource_of(await self._run(fn))

    # ------------------------------------------------------------------ media writes

    @platform_only(MEDIA_MARK)
    async def create_asset(self, fields: dict[str, Any]) -> LessonAsset:
        self._check_write(fields.get("organization_id"))
        aid = str(fields.get("id") or uuid7())
        now = utcnow()
        doc = _clean({**_ASSET_DEFAULTS, **fields, "id": aid})

        async def fn(tx: ScopedTransaction) -> None:
            await tx.create(ASSETS, doc, doc_id=aid)

        await self._run(fn)
        return asset_of({"created_at": now, "updated_at": now, **doc})

    @platform_only(MEDIA_MARK)
    async def update_asset(self, asset_id: uuid.UUID, changes: dict[str, Any]) -> LessonAsset:
        async def fn(tx: ScopedTransaction) -> dict[str, Any]:
            d = await tx.get(ASSETS, str(asset_id))
            if d is None or not self.vis.sees(d.get("organization_id")):
                raise _not_found()
            self._check_write(d.get("organization_id"))
            a = _clean({**d.data, **changes})
            await tx.put(ASSETS, a["id"], a)
            return a

        return asset_of(await self._run(fn))

    @platform_only(MEDIA_MARK)
    async def update_lesson(self, lesson_id: uuid.UUID, changes: dict[str, Any]) -> Lesson:
        """Also keeps the version outline (and, for the current published version, the course
        card) consistent with the lesson."""

        async def fn(tx: ScopedTransaction) -> dict[str, Any]:
            d = await tx.get(LESSONS, str(lesson_id))
            if d is None or not self.vis.sees(d.get("organization_id")):
                raise _not_found()
            self._check_write(d.get("organization_id"))
            v = await tx.get(VERSIONS, d["course_version_id"])
            c = await tx.get(COURSES, d["course_id"]) if d.get("course_id") else None
            lesson = _clean({**d.data, **changes})
            await tx.put(LESSONS, lesson["id"], lesson)
            if v is not None:
                version = dict(v.data)
                _update_summary(version, lesson)
                await tx.put(VERSIONS, version["id"], _clean(version))
                if c is not None and c.get("current_version_id") == version["id"] and c.get("card"):
                    card = {**c["card"], "lesson_count": version["lesson_count"]}
                    card["duration_seconds"] = version["duration_seconds"]
                    await tx.put(COURSES, c.id, _clean({**c.data, "card": card}))
            return lesson

        return lesson_of(await self._run(fn))


def _slug_conflict() -> ProblemError:
    from app.modules.catalog.service import _slug_taken

    return ProblemError("validation_failed", 409, errors=[_slug_taken()])


def _new_course(
    cid: str,
    org: str | None,
    slug: str,
    title: str,
    course_kind: str,
    visibility: str,
    is_free: bool,
    user_id: uuid.UUID,
) -> dict[str, Any]:
    return {
        "id": cid,
        "organization_id": org,
        "slug": slug,
        "slug_lc": slug.lower(),
        "title": title,
        "course_kind": course_kind,
        "visibility": visibility,
        "status": "draft",
        "is_free": bool(is_free),
        "current_version_id": None,
        "primary_topic_id": None,
        "completeness_pct": 0.0,
        "created_by": str(user_id),
        "deleted_at": None,
        "draft_version_id": None,
        "last_version_no": 0,
        "card": None,
        "published_at": None,
    }


def _new_version(
    vid: str, cid: str, org: str | None, no: int, title: str, summary: str | None, user_id: uuid.UUID
) -> dict[str, Any]:
    return {
        "id": vid,
        "course_id": str(cid),
        "organization_id": org,
        "version_no": no,
        "title": title,
        "summary": summary,
        "description_md": None,
        "outcomes": [],
        "level": None,
        "language": "en",
        "category": None,
        "tags": [],
        "certificate_rule": None,
        "completeness_plan": None,
        "status": "draft",
        "change_type": None,
        "changelog": None,
        "created_by": str(user_id),
        "submitted_by": None,
        "submitted_at": None,
        "published_at": None,
        "published_by": None,
        "outline": [],
        "lesson_count": 0,
        "duration_seconds": 0,
    }


def _new_lesson(lid: str, course: dict[str, Any], version: dict[str, Any], module_id: str) -> dict[str, Any]:
    return {
        "id": lid,
        "course_id": str(course["id"]),
        "course_version_id": str(version["id"]),
        "course_module_id": str(module_id),
        "organization_id": course.get("organization_id"),
        "lesson_key": str(uuid7()),
        "title": "",
        "lesson_type": "article",
        "position": 0,
        "is_required": True,
        "is_free_preview": False,
        "duration_seconds": None,
        "est_reading_minutes": None,
        "article_body": None,
        "test_id": None,
        "coding_problem_id": None,
        "assignment_id": None,
        "live_url": None,
        "topics": [],
    }


_ASSET_DEFAULTS: dict[str, Any] = {
    "provider_asset_id": None,
    "s3_key": None,
    "mime_type": None,
    "size_bytes": None,
    "duration_seconds": None,
    "status": "processing",
    "scan_status": "pending",
    "position": 0,
}

_RESOURCE_DEFAULTS: dict[str, Any] = {
    "organization_id": None,
    "course_id": None,
    "lesson_id": None,
    "company_id": None,
    "access_level": "entitled",
    "s3_key": None,
    "url": None,
    "is_public": False,
}


# =========================================================================== factories


async def reader(session: Any) -> CatalogReadRepo:
    """Read repository with the caller's TN visibility (``None`` session = anonymous)."""
    return CatalogReadRepo(ScopedStore.system(READ_JOB), await visibility(session))


def system_reader() -> CatalogReadRepo:
    """Scope lookups that Postgres runs in a system context (rbac, ``catalog.scope_lookup``)."""
    return CatalogReadRepo(ScopedStore.system(READ_JOB), SYSTEM_VIEW)


# Write permissions of the collections an authoring operation touches (store_specs).
AUTHOR_PERMS = ("course.edit",)
CREATE_PERMS = ("course.edit", "course.create")
RESOURCE_PERMS = ("resource.manage",)


async def writer(
    session: Any, principal: Principal | None, perms: Sequence[str] = AUTHOR_PERMS
) -> CatalogWriteRepo:
    """Principal-scoped store when the principal holds ``perms`` at platform scope (defence in
    depth: the store re-checks them); else the ``catalog.write`` job (scoped authors and media
    writes, after the route's permission check). Both apply the TN WITH CHECK predicate."""
    vis = await visibility(session)
    if principal is not None:
        st = ScopedStore(principal)
        if all([await st.has_permission(p) for p in perms]):
            return CatalogWriteRepo(st, vis)
    return CatalogWriteRepo(ScopedStore.system(WRITE_JOB), vis)
