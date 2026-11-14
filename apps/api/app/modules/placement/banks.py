"""Named question banks (placement_0005): collections of bank questions with a subject and an
owning organization (None = platform bank).

Banks are an organising layer over ``questions``: a question can sit in several banks, and the
global question bank, topics, company paths, practice pools and tests keep reading ``questions``
exactly as before. Membership never changes a question's content, workflow or visibility.

Public interface for other modules (assignments, tests, live activities):
``resolve_questions`` (current published / latest version with options, settings and images)
and ``bank_out``.
"""

from __future__ import annotations

import uuid
from collections import Counter, defaultdict
from typing import Any

from sqlalchemy import false, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.core.errors import ProblemError
from app.core.firestore.collation import citext_key
from app.core.ids import uuid7
from app.core.principal import Principal
from app.core.time import to_rfc3339, utcnow
from app.modules.placement import bank as qbank
from app.modules.placement.models import (
    Question,
    QuestionBank,
    QuestionBankItem,
    QuestionOption,
    QuestionTag,
    QuestionVersion,
)
from app.modules.placement.richtext import html_of
from app.modules.placement.schemas import BankCreate, BankPatch

NO_SUBJECT = "__none__"
TOP_TAGS = 8


def _like(text: str) -> str:
    return "%" + text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def _org_filter(col: Any, organization_ids: list[uuid.UUID | None]) -> Any:
    orgs = [o for o in organization_ids if o is not None]
    conds = []
    if orgs:
        conds.append(col.in_(orgs))
    if None in organization_ids:
        conds.append(col.is_(None))
    return or_(*conds) if conds else false()


async def _stats(
    session: AsyncSession, bank_ids: list[uuid.UUID]
) -> tuple[dict[uuid.UUID, Counter[str]], dict[uuid.UUID, list[str]]]:
    """(type counts per bank, top tags per bank) over live (not soft-deleted) questions."""
    types: dict[uuid.UUID, Counter[str]] = defaultdict(Counter)
    tags: dict[uuid.UUID, list[str]] = {}
    if not bank_ids:
        return types, tags
    if qbank._fs():
        return await _fs_stats(session, bank_ids)
    rows = await session.execute(
        select(QuestionBankItem.bank_id, Question.question_type, func.count())
        .join(Question, Question.id == QuestionBankItem.question_id)
        .where(QuestionBankItem.bank_id.in_(bank_ids), Question.deleted_at.is_(None))
        .group_by(QuestionBankItem.bank_id, Question.question_type)
    )
    for bid, qtype, n in rows.all():
        types[bid][qtype] = int(n)
    trows = await session.execute(
        select(QuestionBankItem.bank_id, QuestionTag.tag_value, func.count())
        .join(QuestionTag, QuestionTag.question_id == QuestionBankItem.question_id)
        .join(Question, Question.id == QuestionBankItem.question_id)
        .where(
            QuestionBankItem.bank_id.in_(bank_ids),
            QuestionTag.tag_value.is_not(None),
            Question.deleted_at.is_(None),
        )
        .group_by(QuestionBankItem.bank_id, QuestionTag.tag_value)
    )
    per: dict[uuid.UUID, list[tuple[int, str]]] = defaultdict(list)
    for bid, val, n in trows.all():
        per[bid].append((-int(n), str(val)))
    for bid, vals in per.items():
        tags[bid] = [v for _n, v in sorted(vals)[:TOP_TAGS]]
    return types, tags


def bank_out(
    b: QuestionBank, types: Counter[str] | None = None, tags: list[str] | None = None
) -> dict[str, Any]:
    types = types or Counter()
    return {
        "id": str(b.id),
        "organization_id": str(b.organization_id) if b.organization_id else None,
        "name": b.name,
        "subject": b.subject,
        "description": b.description,
        "default_topic_id": str(b.default_topic_id) if b.default_topic_id else None,
        "question_count": sum(types.values()),
        "type_counts": dict(types),
        "tags": tags or [],
        "created_by": str(b.created_by),
        "created_at": to_rfc3339(b.created_at) if b.created_at else None,
        "updated_at": to_rfc3339(b.updated_at) if b.updated_at else None,
        "last_added_at": to_rfc3339(b.last_added_at) if b.last_added_at else None,
    }


async def bank_detail(session: AsyncSession, b: QuestionBank) -> dict[str, Any]:
    types, tags = await _stats(session, [b.id])
    return bank_out(b, types.get(b.id), tags.get(b.id))


async def list_banks(
    session: AsyncSession,
    *,
    organization_ids: list[uuid.UUID | None],
    text_query: str | None = None,
    subject: str | None = None,
    types: list[str] | None = None,
    sort: str = "newest",
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    if qbank._fs():
        return await _fs_list_banks(
            session, organization_ids, text_query, subject, types, sort, limit, offset
        )
    base = select(QuestionBank).where(
        QuestionBank.deleted_at.is_(None), _org_filter(QuestionBank.organization_id, organization_ids)
    )
    visible = list((await session.execute(base)).scalars())
    vis_ids = [b.id for b in visible]
    q = base
    if text_query:
        like = _like(text_query)
        q = q.where(or_(QuestionBank.name.ilike(like), QuestionBank.subject.ilike(like)))
    if subject == NO_SUBJECT:
        q = q.where(QuestionBank.subject.is_(None))
    elif subject:
        q = q.where(QuestionBank.subject == subject)
    if types:
        q = q.where(
            select(QuestionBankItem.id)
            .join(Question, Question.id == QuestionBankItem.question_id)
            .where(
                QuestionBankItem.bank_id == QuestionBank.id,
                Question.question_type.in_(types),
                Question.deleted_at.is_(None),
            )
            .exists()
        )
    order = {
        "name": (func.lower(QuestionBank.name), QuestionBank.id),
        "updated": (
            func.coalesce(QuestionBank.last_added_at, QuestionBank.updated_at).desc(),
            QuestionBank.id,
        ),
    }.get(sort, (QuestionBank.created_at.desc(), QuestionBank.id.desc()))
    total = (await session.execute(select(func.count()).select_from(q.subquery()))).scalar_one()
    rows = list((await session.execute(q.order_by(*order).limit(limit).offset(offset))).scalars())
    tcounts, tags = await _stats(session, [b.id for b in rows])
    n_questions = 0
    if vis_ids:
        n_questions = (
            await session.execute(
                select(func.count(func.distinct(QuestionBankItem.question_id)))
                .join(Question, Question.id == QuestionBankItem.question_id)
                .where(QuestionBankItem.bank_id.in_(vis_ids), Question.deleted_at.is_(None))
            )
        ).scalar_one()
    subj = Counter(b.subject for b in visible)
    return {
        "items": [bank_out(b, tcounts.get(b.id), tags.get(b.id)) for b in rows],
        "total": int(total),
        "counters": {
            "banks": len(visible),
            "questions": int(n_questions),
            "subjects": len([s for s in subj if s]),
        },
        "subjects": [
            {"subject": s, "count": n}
            for s, n in sorted(subj.items(), key=lambda kv: (kv[0] is None, kv[0] or ""))
        ],
        "limit": limit,
        "offset": offset,
    }


async def get_bank(session: AsyncSession, bank_id: uuid.UUID) -> QuestionBank:
    b = (
        await (await qbank._repo(session)).get_bank(bank_id)
        if qbank._fs()
        else await session.get(QuestionBank, bank_id)
    )
    if b is None or b.deleted_at is not None:
        raise ProblemError("not_found")
    return b


def _clean(s: str | None) -> str | None:
    return s.strip() if s and s.strip() else None


async def create_bank(session: AsyncSession, principal: Principal, body: BankCreate) -> QuestionBank:
    if body.default_topic_id is not None:
        await qbank._validate_topic(session, body.default_topic_id, "default_topic_id")
    name = _clean(body.name)
    if name is None:
        raise ProblemError(
            "validation_failed", errors=[{"field": "name", "code": "required", "message": "name is required"}]
        )
    b = QuestionBank(
        id=uuid7(),
        organization_id=body.organization_id,
        name=name,
        subject=_clean(body.subject),
        description=_clean(body.description),
        default_topic_id=body.default_topic_id,
        created_by=principal.user_id,
    )
    if qbank._fs():
        now = utcnow()
        b.last_added_at, b.created_at, b.updated_at, b.deleted_at = None, now, now, None
        return await (await qbank._repo(session)).save_bank(b, new=True)
    session.add(b)
    await session.flush()
    await session.refresh(b)
    return b


async def patch_bank(session: AsyncSession, b: QuestionBank, body: BankPatch) -> QuestionBank:
    fields = body.model_fields_set
    if "name" in fields and body.name is not None:
        name = _clean(body.name)
        if name is None:
            raise ProblemError(
                "validation_failed",
                errors=[{"field": "name", "code": "required", "message": "name is required"}],
            )
        b.name = name
    if "subject" in fields:
        b.subject = _clean(body.subject)
    if "description" in fields:
        b.description = _clean(body.description)
    if "default_topic_id" in fields:
        if body.default_topic_id is not None:
            await qbank._validate_topic(session, body.default_topic_id, "default_topic_id")
        b.default_topic_id = body.default_topic_id
    b.updated_at = utcnow()
    if qbank._fs():
        return await (await qbank._repo(session)).save_bank(b)
    await session.flush()
    return b


async def delete_bank(session: AsyncSession, b: QuestionBank) -> None:
    """Soft delete: the bank disappears, its questions stay in the global bank."""
    b.deleted_at = utcnow()
    if qbank._fs():
        b.updated_at = b.deleted_at
        await (await qbank._repo(session)).save_bank(b)
        return
    await session.flush()


async def add_questions(
    session: AsyncSession, principal: Principal, b: QuestionBank, question_ids: list[uuid.UUID]
) -> int:
    """Add existing questions (visible under RLS, owned by the bank's org or the platform)."""
    if qbank._fs():
        return await _fs_add_questions(session, principal, b, question_ids)
    existing = set(
        (
            await session.execute(
                select(QuestionBankItem.question_id).where(QuestionBankItem.bank_id == b.id)
            )
        ).scalars()
    )
    added = 0
    for i, qid in enumerate(dict.fromkeys(question_ids)):
        q = await session.get(Question, qid)
        if (
            q is None
            or q.deleted_at is not None
            or (q.organization_id is not None and q.organization_id != b.organization_id)
            # SEC-16: a company bank takes platform questions only once they are published, so
            # an unpublished platform draft is never readable through it.
            or (
                q.organization_id is None
                and b.organization_id is not None
                and (q.status != "active" or q.current_version_id is None)
            )
        ):
            raise ProblemError(
                "validation_failed",
                errors=[{"field": f"question_ids.{i}", "code": "not_found", "message": "unknown question"}],
            )
        if qid in existing:
            continue
        session.add(
            QuestionBankItem(
                id=uuid7(),
                bank_id=b.id,
                question_id=qid,
                organization_id=b.organization_id,
                added_by=principal.user_id,
            )
        )
        added += 1
    if added:
        b.last_added_at = utcnow()
    await session.flush()
    return added


async def remove_question(
    session: AsyncSession, b: QuestionBank, question_id: uuid.UUID, *, purge: bool
) -> bool:
    """Remove from the bank; with ``purge`` also soft-delete a never-published question.
    Returns whether the question was purged."""
    if qbank._fs():
        return await _fs_remove_question(session, b, question_id, purge=purge)
    item = (
        await session.execute(
            select(QuestionBankItem).where(
                QuestionBankItem.bank_id == b.id, QuestionBankItem.question_id == question_id
            )
        )
    ).scalar_one_or_none()
    if item is None:
        raise ProblemError("not_found")
    await session.delete(item)
    purged = False
    if purge:
        q = await qbank.get_question(session, question_id)
        ever_published = (
            await session.execute(
                select(QuestionVersion.id).where(
                    QuestionVersion.question_id == q.id, QuestionVersion.published_at.is_not(None)
                )
            )
        ).first()
        if ever_published is not None or q.current_version_id is not None:
            raise ProblemError(
                "invalid_state_transition",
                detail="Published questions cannot be deleted; retire them instead.",
            )
        q.deleted_at = utcnow()
        purged = True
    await session.flush()
    return purged


def _bank_version_join(b: QuestionBank, newest: Any) -> Any:
    """The version shown for each bank row: the newest one for questions the bank's owner
    authors; for a platform question in a company bank only its published version (SEC-16:
    platform drafts stay with content managers)."""
    own = (QuestionVersion.question_id == Question.id) & (QuestionVersion.version_no == newest)
    if b.organization_id is None:
        return own
    return (Question.organization_id.is_not(None) & own) | (
        Question.organization_id.is_(None)
        & Question.current_version_id.is_not(None)
        & (QuestionVersion.id == Question.current_version_id)
    )


async def bank_questions(
    session: AsyncSession,
    b: QuestionBank,
    *,
    qtype: str | None = None,
    difficulty: int | None = None,
    tag: str | None = None,
    text_query: str | None = None,
    published_only: bool = False,
    limit: int = 100,
    offset: int = 0,
) -> dict[str, Any]:
    if qbank._fs():
        return await _fs_bank_questions(
            session,
            b,
            qtype=qtype,
            difficulty=difficulty,
            tag=tag,
            text_query=text_query,
            published_only=published_only,
            limit=limit,
            offset=offset,
        )
    lv = aliased(QuestionVersion)
    newest = select(func.max(lv.version_no)).where(lv.question_id == Question.id).scalar_subquery()
    base = (
        select(Question, QuestionVersion, QuestionBankItem.added_at)
        .join(QuestionBankItem, QuestionBankItem.question_id == Question.id)
        .join(QuestionVersion, _bank_version_join(b, newest))
        .where(QuestionBankItem.bank_id == b.id, Question.deleted_at.is_(None))
    )
    q = base
    if qtype:
        q = q.where(Question.question_type.in_(qtype.split(",")))
    if difficulty is not None:
        q = q.where(QuestionVersion.difficulty == difficulty)
    if tag:
        q = q.where(Question.id.in_(select(QuestionTag.question_id).where(QuestionTag.tag_value == tag)))
    if published_only:
        q = q.where(Question.status == "active", Question.current_version_id.is_not(None))
    if text_query:
        like = _like(text_query)
        stem_text = func.regexp_replace(QuestionVersion.stem["html"].astext, "<[^>]+>", "", "g")
        q = q.where(
            or_(
                stem_text.ilike(like),
                Question.id.in_(select(QuestionTag.question_id).where(QuestionTag.tag_value.ilike(like))),
            )
        )
    total = (await session.execute(select(func.count()).select_from(q.subquery()))).scalar_one()
    rows = (
        await session.execute(
            q.order_by(QuestionBankItem.added_at.desc(), Question.id).limit(limit).offset(offset)
        )
    ).all()
    qv_ids = [r[1].id for r in rows]
    opts = await qbank.options_of(session, qv_ids)
    qids = [r[0].id for r in rows]
    tag_rows = (
        await session.execute(
            select(QuestionTag.question_id, QuestionTag.tag_value).where(
                QuestionTag.question_id.in_(qids), QuestionTag.tag_value.is_not(None)
            )
        )
        if qids
        else None
    )
    tags_by: dict[uuid.UUID, list[str]] = defaultdict(list)
    for qid, val in tag_rows.all() if tag_rows is not None else []:
        tags_by[qid].append(str(val))
    types, _ = await _stats(session, [b.id])
    all_tags = sorted(
        {
            str(t)
            for t in (
                await session.execute(
                    select(QuestionTag.tag_value)
                    .join(QuestionBankItem, QuestionBankItem.question_id == QuestionTag.question_id)
                    .join(Question, Question.id == QuestionTag.question_id)
                    .where(
                        QuestionBankItem.bank_id == b.id,
                        QuestionTag.tag_value.is_not(None),
                        Question.deleted_at.is_(None),
                    )
                )
            ).scalars()
        }
    )
    items = []
    for question, v, added_at in rows:
        vopts = opts.get(v.id, [])
        items.append(
            {
                "question_id": str(question.id),
                "question_type": question.question_type,
                "status": question.status,
                "organization_id": str(question.organization_id) if question.organization_id else None,
                "primary_topic_id": str(question.primary_topic_id),
                "tags": sorted(tags_by.get(question.id, [])),
                "added_at": to_rfc3339(added_at),
                "published_version_id": str(question.current_version_id)
                if question.status == "active" and question.current_version_id
                else None,
                "latest_version": {
                    "question_version_id": str(v.id),
                    "version_no": v.version_no,
                    "status": v.status,
                    "reviewed": v.reviewed_by is not None,
                    "difficulty": v.difficulty,
                    "stem_html": html_of(v.stem) or "",
                    "option_count": len(vopts),
                    "correct_count": sum(1 for o in vopts if o.is_correct),
                    "has_images": bool((v.stem or {}).get("images"))
                    or any(o.body and o.body.get("image") for o in vopts),
                },
            }
        )
    return {
        "bank": bank_out(b, types.get(b.id)),
        "items": items,
        "total": int(total),
        "type_counts": dict(types.get(b.id) or {}),
        "tags": all_tags,
        "limit": limit,
        "offset": offset,
    }


async def resolve_questions(
    session: AsyncSession,
    question_ids: list[uuid.UUID],
    *,
    prefer: str = "published",
    keys_visible: dict[uuid.UUID, bool] | None = None,
) -> list[dict[str, Any]]:
    """Full content of the chosen questions for importing into an assignment, test or live
    activity: the current published version (``prefer="published"``; ``version`` is None when
    there is none) or the newest version (``"latest"``). Answer keys only where
    ``keys_visible[question_id]`` is true. Hidden coding test cases are never included (they
    live in the coding module; only ``coding_problem_id`` is returned)."""
    from app.modules.placement import public

    out: list[dict[str, Any]] = []
    for qid in dict.fromkeys(question_ids):
        q = await public.get_question(session, qid)
        if q is None or q.deleted_at is not None:
            raise ProblemError("not_found")
        if prefer == "published":
            v = (
                await public.get_version(session, q.current_version_id)
                if q.status == "active" and q.current_version_id
                else None
            )
        else:
            v = await qbank.latest_version(session, q.id)
        options: list[QuestionOption] = (await qbank.options_of(session, [v.id])).get(v.id, []) if v else []
        tags = await _tag_values(session, q.id)
        visible = bool((keys_visible or {}).get(q.id))
        out.append(
            {
                "question_id": str(q.id),
                "question_type": q.question_type,
                "organization_id": str(q.organization_id) if q.organization_id else None,
                "tags": sorted(tags),
                "keys_visible": visible,
                "version": qbank.version_out(v, options, include_keys=visible) if v else None,
            }
        )
    return out


# --------------------------------------------------------------------------- Firestore paths
# (``TD_STORE_PLACEMENT=firestore``): the same results computed from the repository in memory
# (MIGRATION-PLAN §1.6: banks are a small corpus).


async def _tag_values(session: AsyncSession, question_id: uuid.UUID) -> list[str]:
    if qbank._fs():
        return [t.tag_value for t in await (await qbank._repo(session)).tags_of([question_id]) if t.tag_value]
    return [
        str(v)
        for v in (
            await session.execute(
                select(QuestionTag.tag_value).where(
                    QuestionTag.question_id == question_id, QuestionTag.tag_value.is_not(None)
                )
            )
        ).scalars()
    ]


async def _fs_live_items(
    session: AsyncSession, bank_ids: list[uuid.UUID]
) -> tuple[list[QuestionBankItem], dict[uuid.UUID, Question]]:
    r = await qbank._repo(session)
    items = await r.bank_items(bank_ids)
    qs = await r.get_questions({i.question_id for i in items})
    live = {k: q for k, q in qs.items() if q.deleted_at is None}
    return [i for i in items if i.question_id in live], live


async def _fs_stats(
    session: AsyncSession, bank_ids: list[uuid.UUID]
) -> tuple[dict[uuid.UUID, Counter[str]], dict[uuid.UUID, list[str]]]:
    types: dict[uuid.UUID, Counter[str]] = defaultdict(Counter)
    tags: dict[uuid.UUID, list[str]] = {}
    items, live = await _fs_live_items(session, bank_ids)
    for i in items:
        types[i.bank_id][live[i.question_id].question_type] += 1
    tag_rows = await (await qbank._repo(session)).tags_of({i.question_id for i in items})
    by_q: dict[uuid.UUID, list[str]] = defaultdict(list)
    for t in tag_rows:
        if t.tag_value is not None:
            by_q[t.question_id].append(t.tag_value)
    per: dict[uuid.UUID, Counter[str]] = defaultdict(Counter)
    for i in items:
        for v in by_q.get(i.question_id, []):
            per[i.bank_id][v] += 1
    for bid, c in per.items():
        tags[bid] = [v for _n, v in sorted((-n, v) for v, n in c.items())[:TOP_TAGS]]
    return types, tags


def _org_ok(org: uuid.UUID | None, organization_ids: list[uuid.UUID | None]) -> bool:
    return org in organization_ids


async def _fs_list_banks(
    session: AsyncSession,
    organization_ids: list[uuid.UUID | None],
    text_query: str | None,
    subject: str | None,
    types: list[str] | None,
    sort: str,
    limit: int,
    offset: int,
) -> dict[str, Any]:
    r = await qbank._repo(session)
    visible = [
        b
        for b in await r.visible_banks()
        if b.deleted_at is None and _org_ok(b.organization_id, organization_ids)
    ]
    rows = list(visible)
    if text_query:
        needle = text_query.lower()
        rows = [b for b in rows if needle in b.name.lower() or needle in (b.subject or "").lower()]
    if subject == NO_SUBJECT:
        rows = [b for b in rows if b.subject is None]
    elif subject:
        rows = [b for b in rows if b.subject == subject]
    if types:
        items, live = await _fs_live_items(session, [b.id for b in rows])
        has = {i.bank_id for i in items if live[i.question_id].question_type in types}
        rows = [b for b in rows if b.id in has]
    if sort == "name":
        rows.sort(key=lambda b: (citext_key(b.name), b.id))  # ORDER BY lower(name), id
    elif sort == "updated":
        rows.sort(key=lambda b: b.id)
        rows.sort(key=lambda b: b.last_added_at or b.updated_at, reverse=True)
    else:
        rows.sort(key=lambda b: (b.created_at, b.id), reverse=True)
    total = len(rows)
    rows = rows[offset : offset + limit]
    tcounts, tags = await _fs_stats(session, [b.id for b in rows])
    vis_items, _ = await _fs_live_items(session, [b.id for b in visible]) if visible else ([], {})
    subj = Counter(b.subject for b in visible)
    return {
        "items": [bank_out(b, tcounts.get(b.id), tags.get(b.id)) for b in rows],
        "total": total,
        "counters": {
            "banks": len(visible),
            "questions": len({i.question_id for i in vis_items}),
            "subjects": len([s for s in subj if s]),
        },
        "subjects": [
            {"subject": s, "count": n}
            for s, n in sorted(subj.items(), key=lambda kv: (kv[0] is None, kv[0] or ""))
        ],
        "limit": limit,
        "offset": offset,
    }


async def _fs_add_questions(
    session: AsyncSession, principal: Principal, b: QuestionBank, question_ids: list[uuid.UUID]
) -> int:
    from app.modules.placement import public

    r = await qbank._repo(session)
    existing = {i.question_id for i in await r.bank_items([b.id])}
    new: list[QuestionBankItem] = []
    now = utcnow()
    for i, qid in enumerate(dict.fromkeys(question_ids)):
        q = await public.get_question(session, qid)
        if (
            q is None
            or q.deleted_at is not None
            or (q.organization_id is not None and q.organization_id != b.organization_id)
            or (
                q.organization_id is None
                and b.organization_id is not None
                and (q.status != "active" or q.current_version_id is None)
            )
        ):
            raise ProblemError(
                "validation_failed",
                errors=[{"field": f"question_ids.{i}", "code": "not_found", "message": "unknown question"}],
            )
        if qid in existing:
            continue
        new.append(
            QuestionBankItem(
                id=uuid7(),
                bank_id=b.id,
                question_id=qid,
                organization_id=b.organization_id,
                added_by=principal.user_id,
                added_at=now,
            )
        )
    added = await r.add_bank_items(b, new) if new else 0
    if added:
        fresh = await r.get_bank(b.id)
        if fresh is not None:
            b.last_added_at, b.updated_at = fresh.last_added_at, fresh.updated_at
    return added


async def _fs_remove_question(
    session: AsyncSession, b: QuestionBank, question_id: uuid.UUID, *, purge: bool
) -> bool:
    r = await qbank._repo(session)
    if purge:  # checks first: Postgres rolled the whole request back on the error below
        q = await qbank.get_question(session, question_id)
        versions = await qbank.versions_of(session, q.id)
        if not any(i.question_id == question_id for i in await r.bank_items([b.id])):
            raise ProblemError("not_found")
        if any(v.published_at is not None for v in versions) or q.current_version_id is not None:
            raise ProblemError(
                "invalid_state_transition",
                detail="Published questions cannot be deleted; retire them instead.",
            )
    if not await r.remove_bank_item(b.id, question_id):
        raise ProblemError("not_found")
    if purge:
        q.deleted_at = utcnow()
        q.updated_at = q.deleted_at
        await r.save_question(q)
        return True
    return False


async def _fs_bank_questions(
    session: AsyncSession,
    b: QuestionBank,
    *,
    qtype: str | None,
    difficulty: int | None,
    tag: str | None,
    text_query: str | None,
    published_only: bool,
    limit: int,
    offset: int,
) -> dict[str, Any]:
    import re

    r = await qbank._repo(session)
    items, live = await _fs_live_items(session, [b.id])
    vers = await r.versions_of(list(live))
    newest: dict[uuid.UUID, Any] = {}
    by_id: dict[uuid.UUID, Any] = {}
    for v, o in vers:  # version_no descending per question
        newest.setdefault(v.question_id, (v, o))
        by_id[v.id] = (v, o)
    tag_rows = await r.tags_of(list(live))
    tags_by: dict[uuid.UUID, list[str]] = defaultdict(list)
    for t in tag_rows:
        if t.tag_value is not None:
            tags_by[t.question_id].append(str(t.tag_value))
    rows: list[tuple[Question, Any, Any, Any]] = []
    for i in items:
        q = live[i.question_id]
        if b.organization_id is None or q.organization_id is not None:
            pick = newest.get(q.id)
        else:
            pick = by_id.get(q.current_version_id) if q.current_version_id else None
        if pick is not None:
            rows.append((q, pick[0], pick[1], i.added_at))
    if qtype:
        allowed = set(qtype.split(","))
        rows = [x for x in rows if x[0].question_type in allowed]
    if difficulty is not None:
        rows = [x for x in rows if x[1].difficulty == difficulty]
    if tag:
        rows = [x for x in rows if tag in tags_by.get(x[0].id, [])]
    if published_only:
        rows = [x for x in rows if x[0].status == "active" and x[0].current_version_id is not None]
    if text_query:
        needle = text_query.lower()
        strip = re.compile(r"<[^>]+>")
        rows = [
            x
            for x in rows
            if needle in strip.sub("", str((x[1].stem or {}).get("html") or "")).lower()
            or any(needle in t.lower() for t in tags_by.get(x[0].id, []))
        ]
    rows.sort(key=lambda x: x[0].id)
    rows.sort(key=lambda x: x[3], reverse=True)
    total = len(rows)
    page = rows[offset : offset + limit]
    types, _ = await _fs_stats(session, [b.id])
    all_tags = sorted({t for i in items for t in tags_by.get(i.question_id, [])})
    out = []
    for question, v, vopts, added_at in page:
        out.append(
            {
                "question_id": str(question.id),
                "question_type": question.question_type,
                "status": question.status,
                "organization_id": str(question.organization_id) if question.organization_id else None,
                "primary_topic_id": str(question.primary_topic_id),
                "tags": sorted(tags_by.get(question.id, [])),
                "added_at": to_rfc3339(added_at),
                "published_version_id": str(question.current_version_id)
                if question.status == "active" and question.current_version_id
                else None,
                "latest_version": {
                    "question_version_id": str(v.id),
                    "version_no": v.version_no,
                    "status": v.status,
                    "reviewed": v.reviewed_by is not None,
                    "difficulty": v.difficulty,
                    "stem_html": html_of(v.stem) or "",
                    "option_count": len(vopts),
                    "correct_count": sum(1 for o in vopts if o.is_correct),
                    "has_images": bool((v.stem or {}).get("images"))
                    or any(o.body and o.body.get("image") for o in vopts),
                },
            }
        )
    return {
        "bank": bank_out(b, types.get(b.id)),
        "items": out,
        "total": total,
        "type_counts": dict(types.get(b.id) or {}),
        "tags": all_tags,
        "limit": limit,
        "offset": offset,
    }
