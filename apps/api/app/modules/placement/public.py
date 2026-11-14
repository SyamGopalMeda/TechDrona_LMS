"""Store-neutral read API of placement for other modules (Firestore migration, round 2).

Every read another module does on placement tables has a function here. Each one runs the
same SQL that the caller ran before when ``TD_STORE_PLACEMENT=postgres``, or reads the
Firestore repository when it is ``firestore``. Results are plain values or transient ORM
instances, so callers keep their logic. Callers (other agents' modules) still need to switch
to these functions; see docs/firebase/agents/data-assess.md §6.

The functions run in the caller's session context: RLS on Postgres, and the same predicate
evaluated by ``repo_firestore.visibility`` on Firestore.

| Function | Replaces |
|---|---|
| ``get_question`` / ``get_version`` | ``session.get(Question/QuestionVersion)`` (learning/structured.py) |
| ``topic_names`` | ``select(Topic)`` in ``mentoring/service.py`` ``weak_topics`` |
| ``topic_roots`` | the recursive ``topics`` CTE in ``analytics/jobs.py`` ``_category_of`` |
| ``topic_with_root`` | the ``topics`` joins in ``wiring.coding_problem_parents`` |
| ``existing_company_ids`` | ``select(Company.id)`` in ``mentoring/service*.py`` |
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.firestore.backend import uses_firestore
from app.modules.placement.models import Company, Question, QuestionVersion, Topic


def _fs() -> bool:
    return uses_firestore("placement")


async def _repo(session: AsyncSession) -> Any:
    from app.modules.placement import repo_firestore

    return await repo_firestore.repo(session)


async def get_question(session: AsyncSession, question_id: uuid.UUID) -> Question | None:
    """The question row as ``session.get`` returns it (soft-deleted rows included; RLS applies)."""
    if _fs():
        return await (await _repo(session)).get_question(question_id)
    return await session.get(Question, question_id)


async def get_version(session: AsyncSession, version_id: uuid.UUID) -> QuestionVersion | None:
    if _fs():
        got = (await (await _repo(session)).get_versions([version_id])).get(version_id)
        return got[0] if got else None
    return await session.get(QuestionVersion, version_id)


async def topic_names(session: AsyncSession, topic_ids: Iterable[uuid.UUID]) -> dict[uuid.UUID, str]:
    ids = list(dict.fromkeys(topic_ids))
    if not ids:
        return {}
    if _fs():
        r = await _repo(session)
        return {t.id: t.name for t in await r.get_topics(ids)}
    rows = await session.execute(select(Topic).where(Topic.id.in_(ids)))
    return {t.id: t.name for t in rows.scalars()}


async def topic_roots(session: AsyncSession, topic_ids: Iterable[uuid.UUID]) -> dict[uuid.UUID, uuid.UUID]:
    """Root ``subject`` of each topic (walks ``parent_id`` up, like the recursive CTE)."""
    ids = list(dict.fromkeys(topic_ids))
    if not ids:
        return {}
    if _fs():
        r = await _repo(session)
        by_id = {t.id: t for t in await r.all_topics()}
        out: dict[uuid.UUID, uuid.UUID] = {}
        for tid in ids:
            cur = by_id.get(tid)
            seen: set[uuid.UUID] = set()
            while cur is not None and cur.parent_id is not None and cur.id not in seen:
                seen.add(cur.id)
                cur = by_id.get(cur.parent_id)
            if cur is not None and cur.parent_id is None:
                out[tid] = cur.id
        return out
    rows = (
        await session.execute(
            text(
                """
                WITH RECURSIVE up(start_id, id, parent_id) AS (
                    SELECT t.id, t.id, t.parent_id FROM topics t WHERE t.id = ANY(:ids)
                    UNION ALL
                    SELECT up.start_id, p.id, p.parent_id FROM topics p JOIN up ON p.id = up.parent_id
                )
                SELECT start_id, id FROM up WHERE parent_id IS NULL
                """
            ),
            {"ids": ids},
        )
    ).all()
    return {r[0]: r[1] for r in rows}


async def topic_with_root(
    session: AsyncSession, topic_id: uuid.UUID
) -> tuple[uuid.UUID, uuid.UUID | None] | None:
    """``(topic_id, id of the topic whose path is the first path segment)``; ``None`` if unknown."""
    if _fs():
        r = await _repo(session)
        t = await r.get_topic(topic_id)
        if t is None:
            return None
        return t.id, await r.topic_id_by_path(t.path.split("/", 1)[0])
    row = (
        await session.execute(
            text(
                "SELECT t.id, r.id FROM topics t LEFT JOIN topics r ON r.path = split_part(t.path, '/', 1) "
                "WHERE t.id = :i"
            ),
            {"i": topic_id},
        )
    ).first()
    return (row[0], row[1]) if row else None


async def existing_company_ids(session: AsyncSession, company_ids: Iterable[uuid.UUID]) -> set[uuid.UUID]:
    ids = list(dict.fromkeys(company_ids))
    if not ids:
        return set()
    if _fs():
        r = await _repo(session)
        return {c.id for c in await r.companies() if c.id in set(ids)}
    return set((await session.execute(select(Company.id).where(Company.id.in_(ids)))).scalars())


async def get_company(session: AsyncSession, company_id: uuid.UUID) -> Company | None:
    if _fs():
        return await (await _repo(session)).get_company(company_id)
    return await session.get(Company, company_id)


async def get_topic(session: AsyncSession, topic_id: uuid.UUID) -> Topic | None:
    if _fs():
        return await (await _repo(session)).get_topic(topic_id)
    return await session.get(Topic, topic_id)


async def coding_question_for_problem(session: AsyncSession, problem_id: uuid.UUID) -> uuid.UUID | None:
    """The active ``coding`` question whose current published version wraps ``problem_id`` (newest
    first), visible to the caller (RLS)."""
    from app.modules.placement import grading

    if not _fs():
        from app.modules.placement.models import QuestionVersion

        return (
            await session.execute(
                select(Question.id)
                .join(QuestionVersion, QuestionVersion.id == Question.current_version_id)
                .where(
                    Question.question_type == grading.CODING_TYPE,
                    Question.status == "active",
                    Question.deleted_at.is_(None),
                    QuestionVersion.status == "published",
                    QuestionVersion.coding_problem_id == problem_id,
                )
                .order_by(Question.created_at.desc(), Question.id.desc())
                .limit(1)
            )
        ).scalar_one_or_none()

    r = await _repo(session)
    qs = [
        q for q in await r.all_questions() if q.question_type == grading.CODING_TYPE and q.status == "active"
    ]
    vs = await r.get_versions([q.current_version_id for q in qs if q.current_version_id])
    hits = [
        q
        for q in qs
        if q.current_version_id in vs
        and vs[q.current_version_id][0].status == "published"
        and vs[q.current_version_id][0].coding_problem_id == problem_id
    ]
    hits.sort(key=lambda q: (q.created_at, q.id), reverse=True)
    return hits[0].id if hits else None


async def coding_pool(
    session: AsyncSession,
    topic_id: uuid.UUID,
    difficulty_min: int | None,
    difficulty_max: int | None,
    company_id: uuid.UUID | None,
) -> list[uuid.UUID]:
    """Published coding question versions in the topic subtree (same filters as the objective
    ``bank.published_pool``: difficulty, company tag), ordered by version id."""
    from app.modules.placement import bank, grading

    t = await bank.get_topic(session, topic_id)
    if not _fs():
        from sqlalchemy import or_

        from app.modules.placement.models import QuestionTag, QuestionVersion

        q = (
            select(QuestionVersion.id)
            .join(Question, Question.current_version_id == QuestionVersion.id)
            .join(Topic, Topic.id == Question.primary_topic_id)
            .where(
                Question.status == "active",
                Question.deleted_at.is_(None),
                QuestionVersion.status == "published",
                Question.question_type == grading.CODING_TYPE,
                QuestionVersion.coding_problem_id.is_not(None),
                or_(Topic.id == t.id, Topic.path.like(t.path + "/%")),
            )
        )
        if difficulty_min is not None:
            q = q.where(QuestionVersion.difficulty >= difficulty_min)
        if difficulty_max is not None:
            q = q.where(QuestionVersion.difficulty <= difficulty_max)
        if company_id is not None:
            q = q.where(
                Question.id.in_(
                    select(QuestionTag.question_id).where(
                        QuestionTag.tag_type == "company", QuestionTag.company_id == company_id
                    )
                )
            )
        return list((await session.execute(q.order_by(QuestionVersion.id))).scalars())
    r = await _repo(session)
    sub = {x.id for x in await r.subtree(t.path)}
    qs = [
        q
        for q in await r.all_questions()
        if q.status == "active"
        and q.question_type == grading.CODING_TYPE
        and q.primary_topic_id in sub
        and q.current_version_id is not None
    ]
    if company_id is not None:
        tagged = await r.question_ids_tagged(company_id=company_id)
        qs = [q for q in qs if q.id in tagged]
    vs = await r.get_versions([q.current_version_id for q in qs])
    return sorted(
        k
        for k, (v, _o) in vs.items()
        if v.status == "published"
        and v.coding_problem_id is not None
        and (difficulty_min is None or v.difficulty >= difficulty_min)
        and (difficulty_max is None or v.difficulty <= difficulty_max)
    )


# --------------------------------------------------------------------------- re-exports (round 4)
# Already store-neutral (they dispatch on ``TD_STORE_PLACEMENT`` themselves, or touch no store):
# other modules import them from here instead of ``bank`` / ``grading`` / ``policies`` / ``richtext``.
from app.modules.placement.bank import Bundle, delivery, key_payload, load_bundles, versions_of  # noqa: E402
from app.modules.placement.grading import is_correct, normalise_response  # noqa: E402
from app.modules.placement.policies import can_in_org, has_permission  # noqa: E402
from app.modules.placement.richtext import html_of  # noqa: E402

__all__ = [
    "Bundle",
    "can_in_org",
    "coding_pool",
    "coding_question_for_problem",
    "delivery",
    "existing_company_ids",
    "get_company",
    "get_question",
    "get_topic",
    "get_version",
    "has_permission",
    "html_of",
    "is_correct",
    "key_payload",
    "load_bundles",
    "normalise_response",
    "topic_names",
    "topic_roots",
    "topic_with_root",
    "versions_of",
]
