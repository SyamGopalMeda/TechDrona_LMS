"""Firestore repository of placement (``TD_STORE_PLACEMENT=firestore``; data model in ``store_specs``).

``bank.py`` dispatches here when the switch is on; the Postgres path is unchanged. Return values
are **transient ORM instances** (``Topic``, ``Question``, ``QuestionVersion``, ``QuestionOption``,
...) with the model column types, so ``topic_out`` / ``version_out`` / ``Bundle`` / ``delivery``
and every caller keep working unchanged. They are never added to a session.

RLS equivalence. Postgres RLS on the bank tables is ``TN`` and on the learner tables ``U``/``US``.
Reads use the named system job ``placement.read`` and apply the same predicate with the
**caller's** Postgres session context (``app.user_id`` / ``app.org_ids`` / ``app.is_platform`` and
``app.caller_is_org_staff()``), exactly like ``catalog/repo_firestore.py``. Writes apply the
``WITH CHECK`` predicate (a violation is 403 ``permission_denied``; Postgres raised 500).

Invariants, each inside one Firestore transaction:

* ``topics.path`` unique (``topics_by_path``); a subtree move rewrites every descendant's path and
  path key in the same transaction (Postgres: one ``UPDATE ... LIKE old/%``).
* ``companies.slug`` unique (``companies_by_slug``).
* Published/retired question versions are immutable and cannot return to draft (Postgres
  triggers ``placement_qv_immutable`` / ``placement_qo_immutable``): ``assert_version_change``
  runs on every version write; options are embedded in the version, so they share the guard.
* Publish: previous published versions retired + the version published + the question pointer
  set, atomically.
* ``question_tags`` ``ux_qt`` and ``question_bank_items`` / ``practice_responses`` uniques are
  deterministic document ids.
* Practice answer: the response (deterministic id) and the session counters commit together
  (Postgres: INSERT + ``SET answered_count = answered_count + 1``); a concurrent duplicate gets
  the stored response back.
"""

from __future__ import annotations

import uuid
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import text

from app.core.errors import ProblemError
from app.core.firestore.collation import sort_key
from app.core.firestore.errors import UniqueViolationError
from app.core.firestore.repository import FirestoreRepository, platform_only
from app.core.firestore.store import Doc, ScopedStore, ScopedTransaction
from app.core.ids import uuid7
from app.core.time import utcnow
from app.modules.placement.models import (
    Company,
    PracticeResponse,
    PracticeSession,
    Question,
    QuestionBank,
    QuestionBankItem,
    QuestionMedia,
    QuestionOption,
    QuestionReport,
    QuestionTag,
    QuestionVersion,
    Recommendation,
    Topic,
)
from app.modules.placement.store_specs import (
    BANK_ITEMS,
    BANKS,
    COMPANIES,
    COMPANIES_BY_SLUG,
    MEDIA,
    QUESTIONS,
    RECS,
    RECS_ACTIVE,
    REPORTS,
    REPORTS_OPEN,
    RESPONSES,
    SESSIONS,
    TAGS,
    TOPICS,
    TOPICS_BY_PATH,
    VERSIONS,
    bank_item_id,
    open_report_id,
    orm_doc,
    orm_of,
    path_key,
    rec_active_id,
    response_id,
    tag_id,
    tag_ref,
)

READ_JOB = "placement.read"
ERASED_TEXT = "[erased]"  # same marker as privacy.ERASED_TEXT
WRITE_JOB = "placement.write"
BANK_PERM = "question.edit"
TAXONOMY_PERM = "taxonomy.manage"
COMPANY_PERM = "company_path.manage"  # the write permission of ``companies``
_PAGE = 300
FROZEN = ("published", "retired")
# Columns the Postgres trigger freezes once a version is published/retired (placement_0005).
FROZEN_FIELDS = (
    "stem",
    "answer_key",
    "explanation",
    "difficulty",
    "default_marks",
    "default_negative",
    "content_hash",
    "question_id",
    "version_no",
    "settings",
    "options",
)


class QuestionVersionImmutableError(RuntimeError):
    """Same rule (and like Postgres, an internal error) as the ``placement_qv_immutable`` trigger."""


# =========================================================================== RLS context


@dataclass(frozen=True, slots=True)
class Visibility:
    user_id: str = ""
    org_ids: frozenset[str] = frozenset()
    is_platform: bool = False
    org_staff: bool = False

    def sees(self, org: Any) -> bool:
        """TN USING."""
        return org is None or self.is_platform or str(org) in self.org_ids

    def may_write(self, org: Any) -> bool:
        """TN WITH CHECK."""
        return self.is_platform or (org is not None and str(org) in self.org_ids)

    def sees_owned(self, user_id: Any, org: Any) -> bool:
        """US (orgs_0004 rewrote every ``U`` policy to this)."""
        return (
            self.is_platform
            or (bool(self.user_id) and str(user_id) == self.user_id)
            or (org is not None and str(org) in self.org_ids and self.org_staff)
        )


SYSTEM_VIEW = Visibility(is_platform=True)
_GUC = text(
    "SELECT current_setting('app.user_id', true), current_setting('app.org_ids', true), "
    "current_setting('app.is_platform', true), app.caller_is_org_staff()"
)


async def visibility(session: Any) -> Visibility:
    """RLS context: the caller's Postgres transaction GUCs, or (no Postgres: ``db.NO_POSTGRES`` /
    ``None``) the request principal / system scope recorded by ``placement.rls``."""
    if not session:
        from app.modules.placement.rls import current_scope

        uid, orgs, plat, staff = await current_scope()
        return Visibility(uid, orgs, plat, staff)
    from app.modules.placement.rls import memory_gucs

    guc = memory_gucs(session)
    if isinstance(guc, dict):  # sqlstore.MemoryTx: the RLS GUCs are kept in memory
        from app.modules.placement.rls import current_scope

        staff = (await current_scope())[3]
        return Visibility(
            guc.get("app.user_id", ""),
            frozenset(o for o in guc.get("app.org_ids", "").split(",") if o),
            guc.get("app.is_platform", "off") == "on",
            staff,
        )
    uid, orgs, plat, staff = (await session.execute(_GUC)).one()
    return Visibility(
        str(uid or ""),
        frozenset(o for o in (orgs or "").split(",") if o),
        (plat or "off") == "on",
        bool(staff),
    )


def _u(v: Any) -> uuid.UUID | None:
    return uuid.UUID(str(v)) if v else None


def _forbid() -> ProblemError:
    return ProblemError("permission_denied")


def options_of_doc(d: dict[str, Any]) -> list[QuestionOption]:
    opts = [orm_of(QuestionOption, o) for o in (d.get("options") or {}).values()]
    return sorted(opts, key=lambda o: o.position)


def version_doc(qv: QuestionVersion, options: Sequence[QuestionOption]) -> dict[str, Any]:
    return {**orm_doc(qv), "options": {str(o.id): orm_doc(o) for o in options}}


def assert_version_change(old: dict[str, Any] | None, new: dict[str, Any]) -> None:
    """``placement_qv_immutable`` + ``placement_qo_immutable`` on a stored version document."""
    if old is None or old.get("status") not in FROZEN:
        return
    for f in FROZEN_FIELDS:
        if f in new and new[f] != old.get(f):
            raise QuestionVersionImmutableError("published question versions are immutable")
    if "status" in new and new["status"] not in FROZEN:
        raise QuestionVersionImmutableError("published question versions cannot return to draft")


# =========================================================================== repository


class PlacementRepo(FirestoreRepository):
    def __init__(self, store: ScopedStore, vis: Visibility) -> None:
        super().__init__(store)
        self.vis = vis

    async def _all(self, coll: str, filters: Sequence[Any] = (), order: str = "created_at") -> list[Doc]:
        out: list[Doc] = []
        cursor: str | None = None
        while True:
            page = await self.store.query(
                coll, filters=tuple(filters), order_by=((order, "asc"),), limit=_PAGE, cursor=cursor
            )
            out += page.items
            if not page.next_cursor:
                return out
            cursor = page.next_cursor

    def _visible(self, docs: Iterable[Doc]) -> list[Doc]:
        return [d for d in docs if self.vis.sees(d.get("organization_id"))]

    # ------------------------------------------------------------------ taxonomy (global)

    @platform_only(TAXONOMY_PERM)
    async def get_topic(self, topic_id: uuid.UUID) -> Topic | None:
        d = await self.store.get(TOPICS, str(topic_id))
        return orm_of(Topic, d.data) if d else None

    @platform_only(TAXONOMY_PERM)
    async def topic_id_by_path(self, path: str) -> uuid.UUID | None:
        d = await self.store.get(TOPICS_BY_PATH, path_key(path))
        return _u(d.get("topic_id")) if d else None

    @platform_only(TAXONOMY_PERM)
    async def get_topics(self, ids: Iterable[Any]) -> list[Topic]:
        docs = await self.store.get_many(TOPICS, [str(i) for i in ids])
        return [orm_of(Topic, d.data) for d in docs.values()]

    @platform_only(TAXONOMY_PERM)
    async def all_topics(self) -> list[Topic]:
        return [orm_of(Topic, d.data) for d in await self._all(TOPICS)]

    @platform_only(TAXONOMY_PERM)
    async def subtree(self, path: str) -> list[Topic]:
        """The topic at ``path`` and every descendant (``path = p OR path LIKE p || '/%'``)."""
        docs = await self._all(TOPICS, (("path", ">=", path), ("path", "<", path + "/")), order="path")
        return [orm_of(Topic, d.data) for d in docs if d["path"] == path or d["path"].startswith(path + "/")]

    @platform_only(TAXONOMY_PERM)
    async def create_topic(self, t: Topic) -> Topic:
        doc = orm_doc(t)

        async def fn(tx: ScopedTransaction) -> None:
            if await tx.get(TOPICS_BY_PATH, path_key(t.path)) is not None:
                raise ProblemError(
                    "invalid_state_transition", detail="A topic with this slug already exists here."
                )
            await tx.create(TOPICS_BY_PATH, {"topic_id": str(t.id)}, doc_id=path_key(t.path))
            await tx.create(TOPICS, doc, doc_id=str(t.id))

        try:
            await self.store.run_transaction(fn)
        except UniqueViolationError as e:
            raise ProblemError(
                "invalid_state_transition", detail="A topic with this slug already exists here."
            ) from e
        return t

    @platform_only(TAXONOMY_PERM)
    async def save_topic(self, t: Topic, old_path: str) -> Topic:
        """Write ``t``; when its path changed, re-path the subtree and move the path keys."""
        moved = t.path != old_path
        subtree = await self.subtree(old_path) if moved else []

        async def fn(tx: ScopedTransaction) -> None:
            if moved and await tx.get(TOPICS_BY_PATH, path_key(t.path)) is not None:
                raise ProblemError(
                    "invalid_state_transition", detail="A topic with this slug already exists here."
                )
            cur = await tx.get(TOPICS, str(t.id))
            if cur is None:
                raise ProblemError("not_found")
            for d in subtree:
                if d.id == t.id:
                    continue
                new_path = t.path + d.path[len(old_path) :]
                await tx.put(TOPICS, str(d.id), {**orm_doc(d), "path": new_path, "updated_at": utcnow()})
                tx.raw_delete(TOPICS_BY_PATH, path_key(d.path))
                await tx.put(TOPICS_BY_PATH, path_key(new_path), {"topic_id": str(d.id)})
            await tx.put(TOPICS, str(t.id), {**orm_doc(t), "created_at": cur.get("created_at")})
            if moved:
                tx.raw_delete(TOPICS_BY_PATH, path_key(old_path))
                await tx.put(TOPICS_BY_PATH, path_key(t.path), {"topic_id": str(t.id)})

        await self.store.run_transaction(fn)
        return t

    # ------------------------------------------------------------------ questions (TN)

    @platform_only(BANK_PERM)
    async def all_questions(self) -> list[Question]:
        """Every visible, non-deleted question (small corpus: in-memory filters, plan §1.6)."""
        docs = self._visible(await self._all(QUESTIONS))
        return [orm_of(Question, d.data) for d in docs if d.get("deleted_at") is None]

    @platform_only(BANK_PERM)
    async def get_question(self, question_id: uuid.UUID) -> Question | None:
        d = await self.store.get(QUESTIONS, str(question_id))
        if d is None or not self.vis.sees(d.get("organization_id")):
            return None
        return orm_of(Question, d.data)

    @platform_only(BANK_PERM)
    async def get_questions(self, ids: Iterable[Any]) -> dict[uuid.UUID, Question]:
        docs = await self.store.get_many(QUESTIONS, [str(i) for i in ids])
        return {
            uuid.UUID(k): orm_of(Question, d.data)
            for k, d in docs.items()
            if self.vis.sees(d.get("organization_id"))
        }

    @platform_only(BANK_PERM)
    async def versions_of(
        self, question_ids: Iterable[Any]
    ) -> list[tuple[QuestionVersion, list[QuestionOption]]]:
        """Versions of the questions, ``version_no`` descending per question."""
        out: list[tuple[QuestionVersion, list[QuestionOption]]] = []
        ids = [str(i) for i in dict.fromkeys(question_ids)]
        for i in range(0, len(ids), 30):
            docs = await self._all(VERSIONS, (("question_id", "in", ids[i : i + 30]),))
            out += [(orm_of(QuestionVersion, d.data), options_of_doc(d.data)) for d in self._visible(docs)]
        out.sort(key=lambda p: (str(p[0].question_id), -p[0].version_no))
        return out

    @platform_only(BANK_PERM)
    async def get_versions(
        self, qv_ids: Iterable[Any]
    ) -> dict[uuid.UUID, tuple[QuestionVersion, list[QuestionOption]]]:
        docs = await self.store.get_many(VERSIONS, [str(i) for i in qv_ids])
        return {
            uuid.UUID(k): (orm_of(QuestionVersion, d.data), options_of_doc(d.data))
            for k, d in docs.items()
            if self.vis.sees(d.get("organization_id"))
        }

    @platform_only(BANK_PERM)
    async def create_question(
        self, q: Question, qv: QuestionVersion, options: Sequence[QuestionOption], tags: Sequence[QuestionTag]
    ) -> None:
        if not self.vis.may_write(q.organization_id):
            raise _forbid()
        now = utcnow()
        q.created_at = q.created_at or now
        q.updated_at = now

        async def fn(tx: ScopedTransaction) -> None:
            await tx.create(QUESTIONS, orm_doc(q), doc_id=str(q.id))
            await tx.create(VERSIONS, version_doc(qv, options), doc_id=str(qv.id))
            for t in tags:
                await tx.create(TAGS, orm_doc(t), doc_id=tag_id(q.id, t.tag_type, tag_ref(t)))

        await self.store.run_transaction(fn)

    @platform_only(BANK_PERM)
    async def create_questions_in_bank(
        self,
        entries: Sequence[tuple[Question, QuestionVersion, Sequence[QuestionOption], Sequence[QuestionTag]]],
        bank: QuestionBank | None,
        added_by: uuid.UUID,
    ) -> None:
        """Bulk import: questions, versions, tags and bank items, plus ``last_added_at``.
        Chunked into transactions of at most ~350 writes (all entries were validated before)."""
        for q, _qv, _o, _t in entries:
            if not self.vis.may_write(q.organization_id):
                raise _forbid()
        chunk: list[Any] = []
        size = 0
        chunks: list[list[Any]] = []
        for e in entries:
            n = 3 + len(e[3])
            if chunk and size + n > 350:
                chunks.append(chunk)
                chunk, size = [], 0
            chunk.append(e)
            size += n
        if chunk:
            chunks.append(chunk)
        now = utcnow()
        for part in chunks:

            async def fn(tx: ScopedTransaction, part: list[Any] = part) -> None:
                cur = await tx.get(BANKS, str(bank.id)) if bank is not None else None
                for q, qv, opts, tags in part:
                    await tx.create(QUESTIONS, orm_doc(q), doc_id=str(q.id))
                    await tx.create(VERSIONS, version_doc(qv, opts), doc_id=str(qv.id))
                    for t in tags:
                        await tx.create(TAGS, orm_doc(t), doc_id=tag_id(q.id, t.tag_type, tag_ref(t)))
                    if bank is not None:
                        item = QuestionBankItem(
                            id=uuid7(),
                            bank_id=bank.id,
                            question_id=q.id,
                            organization_id=bank.organization_id,
                            added_by=added_by,
                            added_at=now,
                        )
                        await tx.create(BANK_ITEMS, orm_doc(item), doc_id=bank_item_id(bank.id, q.id))
                if cur is not None:
                    await tx.update_read(BANKS, cur, {"last_added_at": now})

            await self.store.run_transaction(fn)

    @platform_only(BANK_PERM)
    async def save_version(
        self, qv: QuestionVersion, options: Sequence[QuestionOption] | None = None
    ) -> None:
        """Insert or rewrite a version (``options=None`` keeps the stored options). Refused when
        the stored version is published/retired and a frozen field changes (trigger rule)."""
        if not self.vis.may_write(qv.organization_id):
            raise _forbid()

        async def fn(tx: ScopedTransaction) -> None:
            cur = await tx.get(VERSIONS, str(qv.id))
            new = orm_doc(qv)
            new["options"] = (
                {str(o.id): orm_doc(o) for o in options}
                if options is not None
                else (cur.get("options") if cur else {}) or {}
            )
            assert_version_change(cur.data if cur else None, new)
            if cur is not None:
                new["created_at"] = cur.get("created_at")
            await tx.put(VERSIONS, str(qv.id), new)

        await self.store.run_transaction(fn)

    @platform_only(BANK_PERM)
    async def save_question(self, q: Question) -> None:
        if not self.vis.may_write(q.organization_id):
            raise _forbid()
        await self.store.update(
            QUESTIONS, str(q.id), {k: v for k, v in orm_doc(q).items() if k != "created_at"}
        )

    @platform_only(BANK_PERM)
    async def publish(self, q: Question, qv: QuestionVersion) -> None:
        """Retire the published version(s), publish ``qv``, point the question at it (one tx)."""
        if not self.vis.may_write(q.organization_id):
            raise _forbid()

        async def fn(tx: ScopedTransaction) -> None:
            cur = await tx.get(VERSIONS, str(qv.id))
            olds = await tx.query(
                VERSIONS, filters=(("question_id", "==", str(q.id)), ("status", "==", "published"))
            )
            qdoc = await tx.get(QUESTIONS, str(q.id))
            if cur is None or qdoc is None:
                raise ProblemError("not_found")
            for o in olds:
                if o.id != str(qv.id):
                    assert_version_change(o.data, {"status": "retired"})
                    await tx.put(VERSIONS, o.id, {**o.data, "status": "retired"})
            new = {**cur.data, **{k: v for k, v in orm_doc(qv).items() if k not in ("created_at", "options")}}
            assert_version_change(cur.data, new)
            await tx.put(VERSIONS, str(qv.id), new)
            await tx.put(
                QUESTIONS,
                str(q.id),
                {**qdoc.data, **{k: v for k, v in orm_doc(q).items() if k != "created_at"}},
            )

        await self.store.run_transaction(fn)

    @platform_only(BANK_PERM)
    async def retire(self, q: Question, qv: QuestionVersion | None) -> None:
        if not self.vis.may_write(q.organization_id):
            raise _forbid()

        async def fn(tx: ScopedTransaction) -> None:
            cur = await tx.get(VERSIONS, str(qv.id)) if qv is not None else None
            qdoc = await tx.get(QUESTIONS, str(q.id))
            if qdoc is None:
                raise ProblemError("not_found")
            if cur is not None and qv is not None:
                assert_version_change(cur.data, {"status": qv.status})
                await tx.put(VERSIONS, cur.id, {**cur.data, "status": qv.status})
            await tx.put(
                QUESTIONS,
                str(q.id),
                {**qdoc.data, **{k: v for k, v in orm_doc(q).items() if k != "created_at"}},
            )

        await self.store.run_transaction(fn)

    @platform_only(BANK_PERM)
    async def tags_of(self, question_ids: Iterable[Any]) -> list[QuestionTag]:
        ids = [str(i) for i in dict.fromkeys(question_ids)]
        out: list[QuestionTag] = []
        for i in range(0, len(ids), 30):
            docs = await self._all(TAGS, (("question_id", "in", ids[i : i + 30]),))
            out += [orm_of(QuestionTag, d.data) for d in self._visible(docs)]
        return out

    @platform_only(BANK_PERM)
    async def question_ids_tagged(
        self, *, company_id: Any = None, value: str | None = None
    ) -> set[uuid.UUID]:
        if company_id is not None:
            f: tuple[Any, ...] = (("tag_type", "==", "company"), ("company_id", "==", str(company_id)))
        else:
            f = (("tag_value", "==", value),)
        return {uuid.UUID(d["question_id"]) for d in await self._all(TAGS, f)}

    @platform_only(BANK_PERM)
    async def banks_of_question(self, question_id: uuid.UUID) -> list[tuple[uuid.UUID, str]]:
        items = await self._all(BANK_ITEMS, (("question_id", "==", str(question_id)),), order="added_at")
        banks = await self.store.get_many(BANKS, [d["bank_id"] for d in self._visible(items)])
        rows = [
            (uuid.UUID(b.id), b["name"])
            for b in banks.values()
            if b.get("deleted_at") is None and self.vis.sees(b.get("organization_id"))
        ]
        return sorted(rows, key=lambda r: sort_key(r[1]))  # ORDER BY question_banks.name

    @platform_only(BANK_PERM)
    async def get_media(self, media_id: Any) -> QuestionMedia | None:
        d = await self.store.get(MEDIA, str(media_id))
        if d is None or not self.vis.sees(d.get("organization_id")):
            return None
        return orm_of(QuestionMedia, d.data)

    @platform_only(BANK_PERM)
    async def active_counts_by_topic(self) -> Counter[uuid.UUID]:
        docs = self._visible(await self._all(QUESTIONS, (("status", "==", "active"),)))
        return Counter(uuid.UUID(d["primary_topic_id"]) for d in docs if d.get("deleted_at") is None)

    # ------------------------------------------------------------------ companies (global)

    @platform_only(COMPANY_PERM)
    async def get_company(self, company_id: Any) -> Company | None:
        d = await self.store.get(COMPANIES, str(company_id))
        return orm_of(Company, d.data) if d else None

    @platform_only(COMPANY_PERM)
    async def companies(self) -> list[Company]:
        rows = [orm_of(Company, d.data) for d in await self._all(COMPANIES)]
        return sorted(rows, key=lambda c: sort_key(c.name))  # ORDER BY companies.name

    @platform_only(COMPANY_PERM)
    async def create_company(self, c: Company) -> Company:
        key = str(c.slug).lower()

        async def fn(tx: ScopedTransaction) -> None:
            if await tx.get(COMPANIES_BY_SLUG, key) is not None:
                raise ProblemError(
                    "invalid_state_transition", detail="A company with this slug already exists."
                )
            await tx.create(COMPANIES_BY_SLUG, {"company_id": str(c.id)}, doc_id=key)
            await tx.create(COMPANIES, orm_doc(c), doc_id=str(c.id))

        try:
            await self.store.run_transaction(fn)
        except UniqueViolationError as e:
            raise ProblemError(
                "invalid_state_transition", detail="A company with this slug already exists."
            ) from e
        return c

    # ------------------------------------------------------------------ practice (owned, US)

    async def get_session(self, user_id: uuid.UUID, ps_id: uuid.UUID) -> PracticeSession | None:
        d = await self.store.get(SESSIONS, str(ps_id))
        if d is None or str(d.get("user_id")) != str(user_id):
            return None
        return orm_of(PracticeSession, d.data)

    async def create_session(self, user_id: uuid.UUID, ps: PracticeSession) -> PracticeSession:
        if str(ps.user_id) != str(user_id):
            raise _forbid()
        await self.store.create(SESSIONS, orm_doc(ps), doc_id=str(ps.id))
        return ps

    async def save_session(self, user_id: uuid.UUID, ps: PracticeSession, fields: Sequence[str]) -> None:
        if str(ps.user_id) != str(user_id):
            raise _forbid()
        doc = orm_doc(ps)
        await self.store.update(SESSIONS, str(ps.id), {f: doc[f] for f in fields})

    async def responses(self, user_id: uuid.UUID, ps_id: uuid.UUID) -> list[PracticeResponse]:
        docs = await self._owned_all(RESPONSES, user_id, (("practice_session_id", "==", str(ps_id)),))
        return [orm_of(PracticeResponse, d.data) for d in docs]

    async def history(self, user_id: uuid.UUID) -> list[PracticeResponse]:
        """Every response of the user, ``answered_at`` descending."""
        docs = await self._owned_all(RESPONSES, user_id, ())
        rows = [orm_of(PracticeResponse, d.data) for d in docs]
        rows.sort(key=lambda r: r.answered_at, reverse=True)
        return rows

    async def _owned_all(self, coll: str, user_id: uuid.UUID, filters: Sequence[Any]) -> list[Doc]:
        out: list[Doc] = []
        cursor: str | None = None
        while True:
            page = await self.store.query(
                coll,
                user_id=user_id,
                filters=tuple(filters),
                order_by=(("created_at", "asc"),),
                limit=_PAGE,
                cursor=cursor,
            )
            out += [d for d in page.items if self.vis.sees_owned(d.get("user_id"), d.get("organization_id"))]
            if not page.next_cursor:
                return out
            cursor = page.next_cursor

    async def record_answer(
        self,
        user_id: uuid.UUID,
        r: PracticeResponse,
        *,
        counts_correct: bool,
        on_created: Any = None,
    ) -> tuple[PracticeResponse, bool, PracticeSession]:
        """Insert the response and bump the session counters atomically.

        Returns ``(response, created, session)``; when the response already exists (a concurrent
        duplicate answer) the stored one comes back with ``created=False`` and nothing changes."""
        if str(r.user_id) != str(user_id):
            raise _forbid()
        rid = response_id(r.practice_session_id, r.question_version_id)
        prior = [
            d
            for d in await self._owned_all(
                RESPONSES, user_id, (("question_version_id", "==", str(r.question_version_id)),)
            )
        ]

        async def fn(tx: ScopedTransaction) -> tuple[PracticeResponse, bool, PracticeSession]:
            ps = await tx.get(SESSIONS, str(r.practice_session_id))
            existing = await tx.get(RESPONSES, rid)
            if ps is None or str(ps.get("user_id")) != str(user_id):
                raise ProblemError("not_found")
            if existing is not None:
                return orm_of(PracticeResponse, existing.data), False, orm_of(PracticeSession, ps.data)
            r.attempt_no = len(prior) + 1
            await tx.create(RESPONSES, orm_doc(r), doc_id=rid)
            after = await tx.update_read(
                SESSIONS,
                ps,
                {
                    "answered_count": int(ps.get("answered_count") or 0) + 1,
                    "correct_count": int(ps.get("correct_count") or 0) + (1 if counts_correct else 0),
                },
            )
            if on_created is not None:  # e.g. the outbox event, atomic with the answer
                on_created(tx, r)
            return r, True, orm_of(PracticeSession, after.data)

        return await self.store.run_transaction(fn)

    async def mark_served(
        self, user_id: uuid.UUID, ps_id: uuid.UUID, qv_id: str, flag: str
    ) -> PracticeSession:
        """Set ``served[i][flag] = True`` for the question in one transaction (no lost update
        between concurrent reveals; Postgres held ``FOR UPDATE`` on the session row)."""

        async def fn(tx: ScopedTransaction) -> PracticeSession:
            cur = await tx.get(SESSIONS, str(ps_id))
            if cur is None or str(cur.get("user_id")) != str(user_id):
                raise ProblemError("not_found")
            served = [dict(x) for x in cur.get("served") or []]
            for x in served:
                if x.get("qv") == qv_id:
                    x[flag] = True
                    break
            else:
                raise ProblemError("not_found")
            after = await tx.update_read(SESSIONS, cur, {"served": served, "updated_at": utcnow()})
            return orm_of(PracticeSession, after.data)

        return await self.store.run_transaction(fn)

    async def complete_session(self, user_id: uuid.UUID, ps_id: uuid.UUID) -> tuple[PracticeSession, bool]:
        """``active`` -> ``completed`` once; returns ``(session, changed)``."""

        async def fn(tx: ScopedTransaction) -> tuple[PracticeSession, bool]:
            cur = await tx.get(SESSIONS, str(ps_id))
            if cur is None or str(cur.get("user_id")) != str(user_id):
                raise ProblemError("not_found")
            if cur.get("status") != "active":
                return orm_of(PracticeSession, cur.data), False
            now = utcnow()
            after = await tx.update_read(SESSIONS, cur, {"status": "completed", "ended_at": now})
            return orm_of(PracticeSession, after.data), True

        return await self.store.run_transaction(fn)

    async def sessions_of(self, user_id: uuid.UUID) -> list[PracticeSession]:
        return [orm_of(PracticeSession, d.data) for d in await self._owned_all(SESSIONS, user_id, ())]

    # ------------------------------------------------------------------ recommendations (owned)

    async def recommendations(self, user_id: uuid.UUID) -> list[Recommendation]:
        return [orm_of(Recommendation, d.data) for d in await self._owned_all(RECS, user_id, ())]

    async def get_recommendation(self, user_id: uuid.UUID, rec_id: uuid.UUID) -> Recommendation | None:
        d = await self.store.get(RECS, str(rec_id))
        if d is None or str(d.get("user_id")) != str(user_id):
            return None
        return orm_of(Recommendation, d.data)

    async def save_recommendations(
        self, user_id: uuid.UUID, rows: Sequence[Recommendation], *, new_ids: set[uuid.UUID]
    ) -> None:
        """Write changed and new rows; keeps ``recommendations_active`` (``ux_rec_dedupe``) in
        step: a new active row reserves its key (a duplicate is skipped, as the partial unique
        index would have refused it), a row leaving ``active`` releases it. Chunked by 100 rows
        per transaction (each row is up to 2 writes)."""
        for i in range(0, len(rows), 100):
            chunk = [r for r in rows[i : i + 100] if str(r.user_id) == str(user_id)]

            async def fn(tx: ScopedTransaction, chunk: Sequence[Recommendation] = chunk) -> None:
                keys = {r.id: rec_active_id(r.user_id, r.rule_key, r.target_type, r.target_id) for r in chunk}
                held = await tx.get_many(RECS_ACTIVE, list(keys.values()))
                curs = await tx.get_many(RECS, [str(r.id) for r in chunk if r.id not in new_ids])
                for r in chunk:
                    k, doc = keys[r.id], orm_doc(r)
                    if r.id in new_ids:
                        if r.status == "active":
                            if k in held:
                                continue
                            await tx.put(
                                RECS_ACTIVE, k, {"recommendation_id": str(r.id), "user_id": str(r.user_id)}
                            )
                        await tx.create(RECS, doc, doc_id=str(r.id))
                        continue
                    cur = curs.get(str(r.id))
                    if cur is None:
                        continue
                    await tx.update_read(RECS, cur, {f: v for f, v in doc.items() if f != "created_at"})
                    owner = held.get(k)
                    if (
                        r.status != "active"
                        and owner is not None
                        and owner.get("recommendation_id") == str(r.id)
                    ):
                        tx.raw_delete(RECS_ACTIVE, k)

            await self.store.run_transaction(fn)

    # ------------------------------------------------------------------ media (TN)

    @platform_only(BANK_PERM)
    async def create_media(self, m: QuestionMedia) -> QuestionMedia:
        if not self.vis.may_write(m.organization_id):
            raise _forbid()
        await self.store.create(MEDIA, orm_doc(m), doc_id=str(m.id))
        return m

    @platform_only(BANK_PERM)
    async def save_media(self, m: QuestionMedia) -> None:
        await self.store.update(MEDIA, str(m.id), {k: v for k, v in orm_doc(m).items() if k != "created_at"})

    @platform_only(BANK_PERM)
    async def pending_media(self, limit: int) -> list[QuestionMedia]:
        """Oldest pending images (the sweep runs as one job: no SKIP LOCKED needed)."""
        page = await self.store.query(
            MEDIA,
            filters=(("scan_status", "==", "pending"),),
            order_by=(("created_at", "asc"),),
            limit=limit,
        )
        return [orm_of(QuestionMedia, d.data) for d in page.items]

    # ------------------------------------------------------------------ question banks (TN)

    @platform_only(BANK_PERM)
    async def visible_banks(self) -> list[QuestionBank]:
        docs = self._visible(await self._all(BANKS))
        return [orm_of(QuestionBank, d.data) for d in docs]

    @platform_only(BANK_PERM)
    async def get_bank(self, bank_id: Any) -> QuestionBank | None:
        d = await self.store.get(BANKS, str(bank_id))
        if d is None or not self.vis.sees(d.get("organization_id")):
            return None
        return orm_of(QuestionBank, d.data)

    @platform_only(BANK_PERM)
    async def save_bank(self, b: QuestionBank, *, new: bool = False) -> QuestionBank:
        if not self.vis.may_write(b.organization_id):
            raise _forbid()
        if new:
            await self.store.create(BANKS, orm_doc(b), doc_id=str(b.id))
        else:
            await self.store.update(
                BANKS, str(b.id), {k: v for k, v in orm_doc(b).items() if k != "created_at"}
            )
        return b

    @platform_only(BANK_PERM)
    async def bank_items(self, bank_ids: Iterable[Any]) -> list[QuestionBankItem]:
        ids = [str(i) for i in dict.fromkeys(bank_ids)]
        out: list[QuestionBankItem] = []
        for i in range(0, len(ids), 30):
            docs = await self._all(BANK_ITEMS, (("bank_id", "in", ids[i : i + 30]),), order="added_at")
            out += [orm_of(QuestionBankItem, d.data) for d in self._visible(docs)]
        return out

    @platform_only(BANK_PERM)
    async def add_bank_items(self, b: QuestionBank, items: Sequence[QuestionBankItem]) -> int:
        """Insert items (``UNIQUE (bank_id, question_id)`` = document id; existing ones are
        skipped) and stamp ``last_added_at`` on the bank in the same transaction."""
        if not self.vis.may_write(b.organization_id):
            raise _forbid()
        added = 0
        for i in range(0, len(items), 300):
            part = items[i : i + 300]

            async def fn(tx: ScopedTransaction, part: Sequence[QuestionBankItem] = part) -> int:
                ids = [bank_item_id(x.bank_id, x.question_id) for x in part]
                have = await tx.get_many(BANK_ITEMS, ids)
                cur = await tx.get(BANKS, str(b.id))
                if cur is None:
                    raise ProblemError("not_found")
                n = 0
                for doc_id, x in zip(ids, part, strict=True):
                    if doc_id not in have:
                        await tx.create(BANK_ITEMS, orm_doc(x), doc_id=doc_id)
                        n += 1
                if n:
                    await tx.update_read(BANKS, cur, {"last_added_at": utcnow()})
                return n

            added += await self.store.run_transaction(fn)
        return added

    @platform_only(BANK_PERM)
    async def remove_bank_item(self, bank_id: Any, question_id: Any) -> bool:
        doc_id = bank_item_id(bank_id, question_id)

        async def fn(tx: ScopedTransaction) -> bool:
            cur = await tx.get(BANK_ITEMS, doc_id)
            if cur is None or not self.vis.sees(cur.get("organization_id")):
                return False
            await tx.delete_read(BANK_ITEMS, doc_id, cur.data)
            return True

        return await self.store.run_transaction(fn)

    # ------------------------------------------------------------------ question reports (US)

    @platform_only(BANK_PERM)
    async def visible_reports(self) -> list[QuestionReport]:
        """Every report the caller's RLS (US) shows: own rows, org staff rows, all for platform."""
        docs = await self._all(REPORTS)
        return [
            orm_of(QuestionReport, d.data)
            for d in docs
            if self.vis.sees_owned(d.get("user_id"), d.get("organization_id"))
        ]

    @platform_only(BANK_PERM)
    async def get_report(self, report_id: Any) -> QuestionReport | None:
        d = await self.store.get(REPORTS, str(report_id))
        if d is None or not self.vis.sees_owned(d.get("user_id"), d.get("organization_id")):
            return None
        return orm_of(QuestionReport, d.data)

    async def create_report(self, user_id: uuid.UUID, r: QuestionReport) -> QuestionReport:
        """Insert an open report; ``question_reports_open`` keeps one open report per learner and
        question (``ux_qr_open_per_user``). A duplicate raises ``invalid_state_transition``
        with the open report's id, like the route's pre-check."""
        key = open_report_id(user_id, r.question_id)

        async def fn(tx: ScopedTransaction) -> QuestionReport:
            held = await tx.get(REPORTS_OPEN, key)
            if held is not None:
                raise ProblemError(
                    "invalid_state_transition",
                    detail="You already reported this question; we're looking into it.",
                    reason="report_already_open",
                    report_id=str(held["report_id"]),
                )
            await tx.put(REPORTS_OPEN, key, {"report_id": str(r.id)})
            await tx.create(REPORTS, orm_doc(r), doc_id=str(r.id))
            return r

        return await self.store.run_transaction(fn)

    @platform_only(BANK_PERM)
    async def resolve_report(self, report_id: Any, changes: dict[str, Any]) -> QuestionReport:
        """``open`` -> ``resolved`` once (the ``FOR UPDATE`` re-check), releasing the open key."""

        async def fn(tx: ScopedTransaction) -> QuestionReport:
            cur = await tx.get(REPORTS, str(report_id))
            if cur is None:
                raise ProblemError("not_found")
            key = open_report_id(cur["user_id"], cur["question_id"])
            held = await tx.get(REPORTS_OPEN, key)
            if cur.get("status") != "open":
                raise ProblemError("invalid_state_transition", detail="This report is already resolved.")
            after = await tx.update_read(REPORTS, cur, changes)
            if held is not None and held.get("report_id") == cur.id:
                tx.raw_delete(REPORTS_OPEN, key)
            return orm_of(QuestionReport, after.data)

        return await self.store.run_transaction(fn)

    # ------------------------------------------------------------------ erasure (privacy)

    async def erase_user(self, user_id: uuid.UUID) -> dict[str, int]:
        """Delete practice responses, sessions and recommendations of the user and scrub the
        message of their question reports (``privacy.erase_user``)."""
        counts: dict[str, int] = {}
        for coll, key in ((RESPONSES, "responses"), (SESSIONS, "sessions"), (RECS, "recs")):
            docs = await self._owned_all(coll, user_id, ())
            for i in range(0, len(docs), 200):

                async def fn(
                    tx: ScopedTransaction, part: list[Doc] = docs[i : i + 200], c: str = coll
                ) -> None:
                    for d in part:
                        await tx.delete_read(c, d.id, d.data)
                        if c == RECS and d.get("status") == "active":
                            tx.raw_delete(
                                RECS_ACTIVE,
                                rec_active_id(d["user_id"], d["rule_key"], d["target_type"], d["target_id"]),
                            )

                await self.store.run_transaction(fn)
            counts[key] = len(docs)
        reports = [d for d in await self._owned_all(REPORTS, user_id, ()) if d.get("message") != ERASED_TEXT]
        for d in reports:
            await self.store.update(REPORTS, d.id, {"message": ERASED_TEXT})
        counts["reports"] = len(reports)
        return counts


# =========================================================================== factories


async def repo(session: Any) -> PlacementRepo:
    """Repository with the caller's RLS visibility (``None`` session = anonymous)."""
    return PlacementRepo(ScopedStore.system(READ_JOB), await visibility(session))


def system_repo() -> PlacementRepo:
    return PlacementRepo(ScopedStore.system(WRITE_JOB), SYSTEM_VIEW)
