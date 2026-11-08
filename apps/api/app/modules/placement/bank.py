"""Taxonomy, question bank (versioning + review workflow), delivery DTOs and draw pools.

Public interface used by ``assessments``: ``load_bundles``, ``delivery``, ``published_pool``,
``Bundle``. Nothing here ever puts key fields into a delivery DTO.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from sqlalchemy import and_, func, or_, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.core.errors import ProblemError
from app.core.ids import uuid7
from app.core.principal import Principal
from app.core.time import to_rfc3339, utcnow
from app.modules.placement import grading
from app.modules.placement.models import (
    Company,
    CompanyPath,
    CompanyPathStep,
    Question,
    QuestionBank,
    QuestionBankItem,
    QuestionOption,
    QuestionTag,
    QuestionVersion,
    Topic,
)
from app.modules.placement.richtext import html_of, rich
from app.modules.placement.schemas import (
    CompanyCreate,
    CompanyPathPut,
    ImageRef,
    OptionDelivery,
    QuestionContent,
    QuestionCreate,
    QuestionDelivery,
    TagIn,
    TopicCreate,
    TopicPatch,
)

KINDS = ("subject", "topic", "subtopic")
LABELS = "ABCDEFGHIJ"


# --------------------------------------------------------------------------- taxonomy


def topic_out(t: Topic) -> dict[str, Any]:
    return {
        "id": str(t.id),
        "parent_id": str(t.parent_id) if t.parent_id else None,
        "kind": t.kind,
        "slug": t.slug,
        "name": t.name,
        "path": t.path,
        "depth": t.depth,
        "position": t.position,
        "is_active": t.is_active,
    }


async def get_topic(session: AsyncSession, topic_id: uuid.UUID) -> Topic:
    t = await session.get(Topic, topic_id)
    if t is None:
        raise ProblemError("not_found")
    return t


async def subtree_ids(session: AsyncSession, topic: Topic) -> list[uuid.UUID]:
    rows = await session.execute(
        select(Topic.id).where(or_(Topic.id == topic.id, Topic.path.like(topic.path + "/%")))
    )
    return list(rows.scalars())


async def subject_tree(session: AsyncSession, *, include_inactive: bool = False) -> list[dict[str, Any]]:
    """PLC-01: active taxonomy with published-question counts (visible bank only).

    ``include_inactive`` (studio taxonomy list, staff only) also returns deactivated nodes so
    they can be reactivated through PLC-03."""
    stmt = select(Topic).order_by(Topic.depth, Topic.position, Topic.name)
    if not include_inactive:
        stmt = stmt.where(Topic.is_active.is_(True))
    topics = list((await session.execute(stmt)).scalars())
    counts_rows = await session.execute(
        select(Question.primary_topic_id, func.count())
        .where(Question.status == "active", Question.deleted_at.is_(None))
        .group_by(Question.primary_topic_id)
    )
    direct = {r[0]: int(r[1]) for r in counts_rows}
    by_path = {t.path: t for t in topics}
    total: dict[uuid.UUID, int] = defaultdict(int)
    for t in topics:
        n = direct.get(t.id, 0)
        parts = t.path.split("/")
        for i in range(1, len(parts) + 1):
            anc = by_path.get("/".join(parts[:i]))
            if anc is not None:
                total[anc.id] += n
    nodes: dict[uuid.UUID, dict[str, Any]] = {}
    roots: list[dict[str, Any]] = []
    for t in topics:
        node = {**topic_out(t), "question_count": total.get(t.id, 0), "children": []}
        nodes[t.id] = node
        if t.parent_id is None:
            roots.append(node)
        elif t.parent_id in nodes:
            nodes[t.parent_id]["children"].append(node)
    return roots


async def create_topic(session: AsyncSession, body: TopicCreate) -> Topic:
    if body.parent_id is None:
        kind, depth, path = "subject", 0, body.slug
    else:
        parent = await get_topic(session, body.parent_id)
        if parent.depth >= 2:
            raise ProblemError(
                "validation_failed",
                errors=[
                    {"field": "parent_id", "code": "invalid", "message": "subtopics cannot have children"}
                ],
            )
        depth = parent.depth + 1
        kind, path = KINDS[depth], f"{parent.path}/{body.slug}"
    if (await session.execute(select(Topic.id).where(Topic.path == path))).first():
        raise ProblemError("invalid_state_transition", detail="A topic with this slug already exists here.")
    t = Topic(
        id=uuid7(),
        parent_id=body.parent_id,
        kind=kind,
        slug=body.slug,
        name=body.name,
        path=path,
        depth=depth,
        position=body.position,
    )
    session.add(t)
    await session.flush()
    return t


async def patch_topic(session: AsyncSession, topic_id: uuid.UUID, body: TopicPatch) -> tuple[Topic, int]:
    t = await get_topic(session, topic_id)
    fields = body.model_fields_set
    old_path = t.path
    new_parent = t.parent_id
    if "parent_id" in fields and body.parent_id != t.parent_id:
        if body.parent_id is None:
            raise ProblemError(
                "validation_failed",
                errors=[
                    {"field": "parent_id", "code": "invalid", "message": "a topic cannot become a subject"}
                ],
            )
        parent = await get_topic(session, body.parent_id)
        if parent.depth != t.depth - 1 or parent.path == t.path or parent.path.startswith(t.path + "/"):
            raise ProblemError(
                "validation_failed",
                errors=[{"field": "parent_id", "code": "invalid", "message": "parent must be one level up"}],
            )
        new_parent = parent.id
    slug = body.slug if "slug" in fields and body.slug else t.slug
    if new_parent is None:
        new_path = slug
    else:
        new_path = f"{(await get_topic(session, new_parent)).path}/{slug}"
    if new_path != old_path:
        if (await session.execute(select(Topic.id).where(Topic.path == new_path))).first():
            raise ProblemError(
                "invalid_state_transition", detail="A topic with this slug already exists here."
            )
        await session.execute(
            update(Topic)
            .where(Topic.path.like(old_path + "/%"))
            .values(path=func.concat(new_path, func.substr(Topic.path, len(old_path) + 1)))
            .execution_options(synchronize_session=False)
        )
        t.path, t.slug, t.parent_id = new_path, slug, new_parent
    if "name" in fields and body.name:
        t.name = body.name
    if "position" in fields and body.position is not None:
        t.position = body.position
    if "is_active" in fields and body.is_active is not None:
        t.is_active = body.is_active
    await session.flush()
    dependents = (
        await session.execute(
            select(func.count())
            .select_from(Question)
            .join(Topic, Topic.id == Question.primary_topic_id)
            .where(or_(Topic.id == t.id, Topic.path.like(t.path + "/%")), Question.deleted_at.is_(None))
        )
    ).scalar_one()
    return t, int(dependents)


# --------------------------------------------------------------------------- question bank


@dataclass(frozen=True)
class Bundle:
    question: Question
    version: QuestionVersion
    options: tuple[QuestionOption, ...]

    @property
    def qtype(self) -> str:
        return self.question.question_type

    @property
    def option_ids(self) -> set[uuid.UUID]:
        return {o.id for o in self.options}

    @property
    def correct_option_ids(self) -> set[uuid.UUID]:
        return {o.id for o in self.options if o.is_correct}


def content_hash(qtype: str, content: dict[str, Any]) -> bytes:
    canon = json.dumps({"type": qtype, **content}, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canon.encode()).digest()


MEDIA_URL = "/api/v1/question-media/{}"


def media_url(media_id: Any) -> str:
    return MEDIA_URL.format(media_id)


def _option_inputs(qtype: str, body: QuestionContent) -> list[dict[str, Any]]:
    """Option dicts to store; a Likert survey without labels gets the default scale labels."""
    opts = [o.model_dump() for o in body.options]
    if qtype == "survey" and not opts and (body.settings or {}).get("scale") == "likert":
        points = (body.settings or {}).get("points", 5)
        labels = grading.LIKERT_LABELS.get(points) if isinstance(points, int) else None
        if labels is None:
            raise grading._bad("settings.points", "must be a whole number from 3 to 7")
        opts = [{"html": lab, "is_correct": False, "feedback_html": None, "image_id": None} for lab in labels]
    return opts


def _content_dict(qtype: str, body: QuestionContent) -> tuple[dict[str, Any], dict[str, Any] | None]:
    opts = _option_inputs(qtype, body)
    key = grading.validate_key(qtype, opts, body.answer_key)
    if key and key.get("reference_answer_html"):
        key["reference_answer_html"] = (rich(key["reference_answer_html"]) or {}).get("html", "")
    settings = grading.validate_settings(qtype, body.settings, len(opts))
    stem = rich(body.stem_html) or {"html": ""}
    if not stem["html"]:
        raise ProblemError(
            "validation_failed",
            errors=[{"field": "stem_html", "code": "required", "message": "stem is empty"}],
        )
    if body.stem_image_ids:
        stem["images"] = [str(i) for i in dict.fromkeys(body.stem_image_ids)]
    content = {
        "stem": stem,
        "options": [
            {
                "html": (rich(o["html"]) or {}).get("html", ""),
                "is_correct": o["is_correct"],
                "fb": o["feedback_html"],
                **({"image": str(o["image_id"])} if o.get("image_id") else {}),
            }
            for o in opts
        ],
        "answer_key": key,
        "explanation": rich(body.explanation_html),
        "difficulty": body.difficulty,
        "marks": str(body.default_marks),
        "negative": str(body.default_negative),
    }
    if settings:
        content["settings"] = settings
    return content, key


async def _check_media(session: AsyncSession, qv: QuestionVersion, body: QuestionContent) -> None:
    """Referenced images must exist in the version's org (or the platform) and not be infected."""
    from app.modules.placement.models import QuestionMedia

    refs = [(f"stem_image_ids.{i}", m) for i, m in enumerate(body.stem_image_ids)] + [
        (f"options.{i}.image_id", o.image_id) for i, o in enumerate(body.options) if o.image_id
    ]
    for field, mid in refs:
        m = await session.get(QuestionMedia, mid)
        if (
            m is None
            or m.scan_status == "infected"
            or (m.organization_id is not None and m.organization_id != qv.organization_id)
        ):
            raise grading._bad(field, "unknown or rejected image", "not_found")


async def _write_content(
    session: AsyncSession, qv: QuestionVersion, qtype: str, body: QuestionContent
) -> None:
    content, key = _content_dict(qtype, body)
    await _check_media(session, qv, body)
    if qtype == grading.CODING_TYPE:
        if body.coding_problem_id is None:
            raise grading._bad("coding_problem_id", "required for coding questions", "required")
        from app.modules.coding.service import get_problem

        # A draft problem of the same organization may be linked while the question is a draft
        # (bulk/AI import creates both); submit-for-review requires it to be published.
        try:
            problem = await get_problem(session, body.coding_problem_id)
        except ProblemError as e:
            raise grading._bad("coding_problem_id", "unknown coding problem", "not_found") from e
        if problem.status == "retired" or (
            problem.status != "published" and problem.organization_id != qv.organization_id
        ):
            raise grading._bad("coding_problem_id", "unknown or unpublished coding problem", "not_found")
        content["coding_problem_id"] = str(body.coding_problem_id)
    elif body.coding_problem_id is not None:
        raise grading._bad("coding_problem_id", "only coding questions reference a coding problem")
    qv.coding_problem_id = body.coding_problem_id
    qv.stem = content["stem"]
    qv.answer_key = key
    qv.settings = content.get("settings", {})
    qv.explanation = content["explanation"]
    qv.difficulty = body.difficulty
    qv.item_rating = 700 + 100 * body.difficulty  # 800..1200 (system-architecture §7.3)
    qv.default_marks = body.default_marks
    qv.default_negative = body.default_negative
    qv.expected_seconds = body.expected_seconds
    qv.content_hash = content_hash(qtype, content)
    await session.flush()
    existing = (
        await session.execute(select(QuestionOption).where(QuestionOption.question_version_id == qv.id))
    ).scalars()
    for old in existing:
        await session.delete(old)
    await session.flush()
    for i, o in enumerate(_option_inputs(qtype, body)):
        obody = rich(o["html"]) or {"html": ""}
        if o.get("image_id"):
            obody["image"] = str(o["image_id"])
        session.add(
            QuestionOption(
                id=uuid7(),
                question_version_id=qv.id,
                organization_id=qv.organization_id,
                label=LABELS[i],
                body=obody,
                is_correct=bool(o["is_correct"]),
                position=i + 1,
                feedback=rich(o["feedback_html"]),
            )
        )
    await session.flush()


async def _validate_topic(session: AsyncSession, topic_id: uuid.UUID, field: str) -> Topic:
    t = await session.get(Topic, topic_id)
    if t is None:
        raise ProblemError(
            "validation_failed", errors=[{"field": field, "code": "not_found", "message": "unknown topic"}]
        )
    return t


async def _write_tags(session: AsyncSession, q: Question, tags: list[TagIn]) -> None:
    seen: set[tuple[str, str]] = set()
    for i, tag in enumerate(tags):
        if tag.tag_type == "topic":
            if tag.topic_id is None:
                raise ProblemError(
                    "validation_failed",
                    errors=[{"field": f"tags.{i}.topic_id", "code": "required", "message": "required"}],
                )
            await _validate_topic(session, tag.topic_id, f"tags.{i}.topic_id")
            ref = str(tag.topic_id)
        elif tag.tag_type == "company":
            if tag.company_id is None or await session.get(Company, tag.company_id) is None:
                raise ProblemError(
                    "validation_failed",
                    errors=[
                        {"field": f"tags.{i}.company_id", "code": "invalid", "message": "unknown company"}
                    ],
                )
            ref = str(tag.company_id)
        else:
            if not tag.value:
                raise ProblemError(
                    "validation_failed",
                    errors=[{"field": f"tags.{i}.value", "code": "required", "message": "required"}],
                )
            ref = tag.value
        if (tag.tag_type, ref) in seen:
            continue
        seen.add((tag.tag_type, ref))
        session.add(
            QuestionTag(
                id=uuid7(),
                question_id=q.id,
                organization_id=q.organization_id,
                tag_type=tag.tag_type,
                topic_id=tag.topic_id if tag.tag_type == "topic" else None,
                company_id=tag.company_id if tag.tag_type == "company" else None,
                tag_value=tag.value if tag.tag_type not in ("topic", "company") else None,
            )
        )
    await session.flush()


UNCATEGORISED_SLUG = "uncategorised"


async def uncategorised_topic(session: AsyncSession) -> uuid.UUID:
    """The global "Uncategorised" subject (created on first use) for questions imported or
    authored in a bank without a taxonomy topic (polls, surveys, free-text subjects)."""
    found = (
        await session.execute(select(Topic.id).where(Topic.path == UNCATEGORISED_SLUG))
    ).scalar_one_or_none()
    if found is not None:
        return found
    t = Topic(
        id=uuid7(),
        parent_id=None,
        kind="subject",
        slug=UNCATEGORISED_SLUG,
        name="Uncategorised",
        path=UNCATEGORISED_SLUG,
        depth=0,
        position=10_000,
    )
    session.add(t)
    await session.flush()
    return t.id


async def create_question(
    session: AsyncSession,
    principal: Principal,
    body: QuestionCreate,
    *,
    default_topic_id: uuid.UUID | None = None,
) -> tuple[Question, QuestionVersion]:
    topic_id = body.primary_topic_id or default_topic_id or await uncategorised_topic(session)
    await _validate_topic(session, topic_id, "primary_topic_id")
    q = Question(
        id=uuid7(),
        organization_id=body.organization_id,
        question_type=body.question_type,
        primary_topic_id=topic_id,
        status="draft",
        external_ref=body.external_ref,
        created_by=principal.user_id,
    )
    session.add(q)
    await session.flush()
    qv = QuestionVersion(
        id=uuid7(),
        question_id=q.id,
        organization_id=q.organization_id,
        version_no=1,
        stem={},
        difficulty=body.difficulty,
        status="draft",
        content_hash=b"\0" * 32,
        authored_by=principal.user_id,
    )
    session.add(qv)
    await session.flush()
    await _write_content(session, qv, q.question_type, body)
    await _write_tags(session, q, body.tags)
    return q, qv


async def get_question(session: AsyncSession, question_id: uuid.UUID) -> Question:
    q = await session.get(Question, question_id)
    if q is None or q.deleted_at is not None:
        raise ProblemError("not_found")
    return q


async def versions_of(session: AsyncSession, question_id: uuid.UUID) -> list[QuestionVersion]:
    return list(
        (
            await session.execute(
                select(QuestionVersion)
                .where(QuestionVersion.question_id == question_id)
                .order_by(QuestionVersion.version_no.desc())
            )
        ).scalars()
    )


async def latest_version(session: AsyncSession, question_id: uuid.UUID) -> QuestionVersion:
    vs = await versions_of(session, question_id)
    if not vs:
        raise ProblemError("not_found")
    return vs[0]


async def edit_question(
    session: AsyncSession, principal: Principal, question_id: uuid.UUID, body: QuestionContent
) -> QuestionVersion:
    """PLC-07: a draft is edited in place; a published/retired latest version gets a new draft."""
    q = await get_question(session, question_id)
    latest = await latest_version(session, question_id)
    if latest.status == "in_review":
        raise ProblemError(
            "invalid_state_transition", detail="This version is in review; request changes first."
        )
    if latest.status == "draft":
        qv = latest
        qv.reviewed_by = None
        # SoD (audit ADM-46): anyone who changes the draft in place becomes a co-author and can
        # no longer review or publish this version.
        if principal.user_id != qv.authored_by and principal.user_id not in (qv.edited_by or []):
            qv.edited_by = [*(qv.edited_by or []), principal.user_id]
    else:
        qv = QuestionVersion(
            id=uuid7(),
            question_id=q.id,
            organization_id=q.organization_id,
            version_no=latest.version_no + 1,
            stem={},
            difficulty=body.difficulty,
            status="draft",
            content_hash=b"\0" * 32,
            authored_by=principal.user_id,
        )
        session.add(qv)
        await session.flush()
    await _write_content(session, qv, q.question_type, body)
    return qv


async def submit_review(session: AsyncSession, question_id: uuid.UUID) -> QuestionVersion:
    q = await get_question(session, question_id)
    qv = await latest_version(session, question_id)
    if qv.status != "draft":
        raise ProblemError("invalid_state_transition", detail="Only a draft can be submitted for review.")
    if q.question_type == grading.CODING_TYPE and qv.coding_problem_id is not None:
        from app.modules.coding.models import CodingProblem

        problem = await session.get(CodingProblem, qv.coding_problem_id)
        if problem is None or problem.status != "published":
            raise ProblemError(
                "invalid_state_transition",
                detail="Publish the linked coding problem (with validated test cases) first.",
            )
    # Ungraded types (poll/survey/word cloud) have nothing to explain.
    if q.question_type not in grading.UNGRADED_TYPES and not html_of(qv.explanation):
        raise ProblemError(
            "validation_failed",
            errors=[
                {"field": "explanation_html", "code": "required", "message": "an explanation is mandatory"}
            ],
        )
    qv.status = "in_review"
    await session.flush()
    return qv


def _is_contributor(qv: QuestionVersion, user_id: uuid.UUID) -> bool:
    return user_id == qv.authored_by or user_id in (qv.edited_by or [])


async def review(
    session: AsyncSession,
    principal: Principal,
    question_id: uuid.UUID,
    decision: str,
    comment: str | None = None,
) -> QuestionVersion:
    await get_question(session, question_id)
    qv = await latest_version(session, question_id)
    if qv.status != "in_review":
        raise ProblemError("invalid_state_transition", detail="Nothing is waiting for review.")
    # SoD (matrix question.review: reviewer != author) applies to platform AND org-private
    # questions, and to everyone who edited the version (audit ADM-46).
    if _is_contributor(qv, principal.user_id):
        raise ProblemError(
            "sod_violation", detail="The reviewer must be a different person from the author and editors."
        )
    if decision == "approve":
        qv.reviewed_by = principal.user_id
    else:
        qv.status = "draft"
        qv.reviewed_by = None
    qv.review_comment = comment.strip() if comment and comment.strip() else None
    await session.flush()
    return qv


async def publish(
    session: AsyncSession, question_id: uuid.UUID, principal: Principal | None = None
) -> QuestionVersion:
    """``principal`` is the acting publisher (PLC-10); system/seed callers pass None."""
    q = await get_question(session, question_id)
    qv = await latest_version(session, question_id)
    if qv.status != "in_review" or qv.reviewed_by is None:
        raise ProblemError("invalid_state_transition", detail="Only an approved version can be published.")
    # matrix question.publish = "P (!= author)" (audit ADM-48).
    if principal is not None and _is_contributor(qv, principal.user_id):
        raise ProblemError(
            "sod_violation", detail="The publisher must be a different person from the author."
        )
    now = utcnow()
    # Supersede the previously published version (attempts keep referencing it).
    await session.execute(
        update(QuestionVersion)
        .where(QuestionVersion.question_id == q.id, QuestionVersion.status == "published")
        .values(status="retired")
        .execution_options(synchronize_session=False)
    )
    qv.status = "published"
    qv.published_at = now
    q.current_version_id = qv.id
    q.status = "active"
    await session.flush()
    return qv


async def retire(session: AsyncSession, question_id: uuid.UUID, reason: str | None = None) -> Question:
    q = await get_question(session, question_id)
    if q.status != "active" or q.current_version_id is None:
        raise ProblemError("invalid_state_transition", detail="Only an active question can be retired.")
    cur = await session.get(QuestionVersion, q.current_version_id)
    if cur is not None and cur.status == "published":
        cur.status = "retired"
    q.status = "retired"
    q.retired_reason = reason.strip() if reason and reason.strip() else None
    await session.flush()
    return q


async def options_of(session: AsyncSession, qv_ids: list[uuid.UUID]) -> dict[uuid.UUID, list[QuestionOption]]:
    out: dict[uuid.UUID, list[QuestionOption]] = defaultdict(list)
    if not qv_ids:
        return out
    rows = await session.execute(
        select(QuestionOption)
        .where(QuestionOption.question_version_id.in_(qv_ids))
        .order_by(QuestionOption.question_version_id, QuestionOption.position)
    )
    for o in rows.scalars():
        out[o.question_version_id].append(o)
    return out


def _image(media_id: Any) -> dict[str, str] | None:
    return {"media_id": str(media_id), "url": media_url(media_id)} if media_id else None


def stem_images(stem: dict[str, Any] | None) -> list[dict[str, str]]:
    return [{"media_id": str(m), "url": media_url(m)} for m in (stem or {}).get("images") or []]


def version_out(qv: QuestionVersion, options: list[QuestionOption], *, include_keys: bool) -> dict[str, Any]:
    out: dict[str, Any] = {
        "question_version_id": str(qv.id),
        "version_no": qv.version_no,
        "status": qv.status,
        "difficulty": qv.difficulty,
        "stem_html": html_of(qv.stem) or "",
        "default_marks": str(qv.default_marks),
        "default_negative": str(qv.default_negative),
        "expected_seconds": qv.expected_seconds,
        "authored_by": str(qv.authored_by),
        "reviewed_by": str(qv.reviewed_by) if qv.reviewed_by else None,
        "edited_by": [str(u) for u in (qv.edited_by or [])],
        "review_comment": qv.review_comment,
        "published_at": to_rfc3339(qv.published_at) if qv.published_at else None,
        "content_hash": qv.content_hash.hex(),
        "coding_problem_id": str(qv.coding_problem_id) if qv.coding_problem_id else None,
        "settings": qv.settings or {},
        "stem_images": stem_images(qv.stem),
        "options": [
            {
                "option_id": str(o.id),
                "label": o.label,
                "html": html_of(o.body) or "",
                "image": _image(o.body.get("image") if o.body else None),
            }
            for o in options
        ],
    }
    if include_keys:
        out["answer_key"] = qv.answer_key
        out["explanation_html"] = html_of(qv.explanation)
        out["correct_option_ids"] = [str(o.id) for o in options if o.is_correct]
        for od, o in zip(out["options"], options, strict=True):
            od["is_correct"] = o.is_correct
            od["feedback_html"] = html_of(o.feedback)
    return out


async def question_detail(session: AsyncSession, q: Question, *, include_keys: bool) -> dict[str, Any]:
    versions = await versions_of(session, q.id)
    opts = await options_of(session, [v.id for v in versions])
    tags = (await session.execute(select(QuestionTag).where(QuestionTag.question_id == q.id))).scalars()
    banks = (
        await session.execute(
            select(QuestionBank.id, QuestionBank.name)
            .join(QuestionBankItem, QuestionBankItem.bank_id == QuestionBank.id)
            .where(QuestionBankItem.question_id == q.id, QuestionBank.deleted_at.is_(None))
            .order_by(QuestionBank.name)
        )
    ).all()
    return {
        "banks": [{"id": str(b[0]), "name": b[1]} for b in banks],
        "question_id": str(q.id),
        "organization_id": str(q.organization_id) if q.organization_id else None,
        "question_type": q.question_type,
        "primary_topic_id": str(q.primary_topic_id),
        "status": q.status,
        "retired_reason": q.retired_reason,
        "current_version_id": str(q.current_version_id) if q.current_version_id else None,
        "created_by": str(q.created_by),
        "keys_visible": include_keys,
        "tags": [
            {
                "tag_type": t.tag_type,
                "topic_id": str(t.topic_id) if t.topic_id else None,
                "company_id": str(t.company_id) if t.company_id else None,
                "value": t.tag_value,
            }
            for t in tags
        ],
        "versions": [version_out(v, opts.get(v.id, []), include_keys=include_keys) for v in versions],
    }


async def search_questions(
    session: AsyncSession,
    *,
    topic_id: uuid.UUID | None,
    difficulty: int | None,
    status: str | None,
    company_id: uuid.UUID | None,
    tag: str | None,
    author: uuid.UUID | None,
    organization_ids: list[uuid.UUID | None] | None,
    limit: int,
    offset: int,
    version_status: str | None = None,
    text_query: str | None = None,
) -> list[dict[str, Any]]:
    q = select(Question).where(Question.deleted_at.is_(None))
    if text_query:
        # Stem search on the latest version's text (markup stripped, LIKE wildcards literal).
        sv = aliased(QuestionVersion)
        newest_no = select(func.max(sv.version_no)).where(sv.question_id == Question.id).scalar_subquery()
        stem_text = func.regexp_replace(QuestionVersion.stem["html"].astext, "<[^>]+>", "", "g")
        like = "%" + text_query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        q = q.where(
            select(QuestionVersion.id)
            .where(
                QuestionVersion.question_id == Question.id,
                QuestionVersion.version_no == newest_no,
                stem_text.ilike(like),
            )
            .exists()
        )
    if topic_id is not None:
        t = await get_topic(session, topic_id)
        q = q.join(Topic, Topic.id == Question.primary_topic_id).where(
            or_(Topic.id == t.id, Topic.path.like(t.path + "/%"))
        )
    if status:
        q = q.where(Question.status == status)
    if version_status:
        # Filter on the LATEST version's workflow state (audit ADM-54: review queue).
        lv = aliased(QuestionVersion)
        newest = select(func.max(lv.version_no)).where(lv.question_id == Question.id).scalar_subquery()
        cond = [QuestionVersion.question_id == Question.id, QuestionVersion.version_no == newest]
        if version_status == "awaiting_review":
            cond += [QuestionVersion.status == "in_review", QuestionVersion.reviewed_by.is_(None)]
        elif version_status == "approved":
            cond += [QuestionVersion.status == "in_review", QuestionVersion.reviewed_by.is_not(None)]
        else:
            cond.append(QuestionVersion.status == version_status)
        q = q.where(select(QuestionVersion.id).where(*cond).exists())
    if author:
        q = q.where(Question.created_by == author)
    if company_id:
        q = q.where(
            Question.id.in_(
                select(QuestionTag.question_id).where(
                    QuestionTag.tag_type == "company", QuestionTag.company_id == company_id
                )
            )
        )
    if tag:
        q = q.where(Question.id.in_(select(QuestionTag.question_id).where(QuestionTag.tag_value == tag)))
    if difficulty is not None:
        q = q.where(
            Question.id.in_(
                select(QuestionVersion.question_id).where(QuestionVersion.difficulty == difficulty)
            )
        )
    if organization_ids is not None:
        conds = []
        orgs = [o for o in organization_ids if o is not None]
        if orgs:
            conds.append(Question.organization_id.in_(orgs))
        if None in organization_ids:
            conds.append(Question.organization_id.is_(None))
        q = q.where(or_(*conds) if conds else and_(False))  # type: ignore[arg-type]
    rows = list(
        (await session.execute(q.order_by(Question.created_at.desc()).limit(limit).offset(offset))).scalars()
    )
    latest: dict[uuid.UUID, QuestionVersion] = {}
    if rows:
        vrows = await session.execute(
            select(QuestionVersion)
            .where(QuestionVersion.question_id.in_([r.id for r in rows]))
            .order_by(QuestionVersion.question_id, QuestionVersion.version_no.desc())
        )
        for ver in vrows.scalars():
            latest.setdefault(ver.question_id, ver)
    out = []
    for r in rows:
        v = latest.get(r.id)
        out.append(
            {
                "question_id": str(r.id),
                "organization_id": str(r.organization_id) if r.organization_id else None,
                "question_type": r.question_type,
                "primary_topic_id": str(r.primary_topic_id),
                "status": r.status,
                "retired_reason": r.retired_reason,
                "latest_version": {
                    "question_version_id": str(v.id),
                    "version_no": v.version_no,
                    "status": v.status,
                    "reviewed": v.reviewed_by is not None,
                    "difficulty": v.difficulty,
                    "stem_html": html_of(v.stem) or "",
                }
                if v
                else None,
            }
        )
    return out


# --------------------------------------------------------------------------- delivery


async def load_bundles(session: AsyncSession, qv_ids: list[uuid.UUID]) -> dict[uuid.UUID, Bundle]:
    if not qv_ids:
        return {}
    rows = await session.execute(
        select(QuestionVersion, Question)
        .join(Question, Question.id == QuestionVersion.question_id)
        .where(QuestionVersion.id.in_(qv_ids))
    )
    opts = await options_of(session, list(qv_ids))
    return {qv.id: Bundle(q, qv, tuple(opts.get(qv.id, []))) for qv, q in rows.all()}


@dataclass(frozen=True, slots=True)
class AnswerShape:
    """What validating a learner's answer needs (no stem, bodies or keys)."""

    qtype: str
    option_ids: frozenset[uuid.UUID]
    coding_problem_id: uuid.UUID | None


async def load_answer_shapes(session: AsyncSession, qv_ids: list[uuid.UUID]) -> dict[uuid.UUID, AnswerShape]:
    """One light query for the autosave hot path (instead of ``load_bundles``' full rows)."""
    if not qv_ids:
        return {}
    rows = await session.execute(
        select(
            QuestionVersion.id,
            Question.question_type,
            QuestionVersion.coding_problem_id,
            func.array_agg(QuestionOption.id).filter(QuestionOption.id.is_not(None)),
        )
        .join(Question, Question.id == QuestionVersion.question_id)
        .outerjoin(QuestionOption, QuestionOption.question_version_id == QuestionVersion.id)
        .where(QuestionVersion.id.in_(set(qv_ids)))
        .group_by(QuestionVersion.id, Question.question_type, QuestionVersion.coding_problem_id)
    )
    return {
        qv_id: AnswerShape(qtype, frozenset(opt_ids or ()), problem_id)
        for qv_id, qtype, problem_id, opt_ids in rows.all()
    }


def delivery(
    b: Bundle,
    *,
    option_order: list[str] | None = None,
    marks: Decimal | None = None,
    negative: Decimal | None = None,
) -> dict[str, Any]:
    """Key-free question payload (``QuestionDelivery``)."""
    by_id = {str(o.id): o for o in b.options}
    ordered = [by_id[i] for i in option_order if i in by_id] if option_order else list(b.options)
    images = stem_images(b.version.stem)
    dto = QuestionDelivery(
        question_version_id=b.version.id,
        type=b.qtype,
        topic_id=b.question.primary_topic_id,
        difficulty=b.version.difficulty,
        stem_html=html_of(b.version.stem) or "",
        options=[
            OptionDelivery(
                option_id=o.id,
                label=o.label,
                html=html_of(o.body) or "",
                image_url=media_url(o.body["image"]) if o.body and o.body.get("image") else None,
            )
            for o in ordered
        ],
        marks=marks,
        negative_marks=negative,
        expected_seconds=b.version.expected_seconds,
        coding_problem_id=b.version.coding_problem_id,
        settings=b.version.settings or None,
        stem_images=[ImageRef(media_id=uuid.UUID(i["media_id"]), url=i["url"]) for i in images] or None,
    )
    out = dto.model_dump(mode="json")
    # Objective items keep their historical shape (optional members only when present).
    for k in ("coding_problem_id", "settings", "stem_images"):
        if out.get(k) is None:
            out.pop(k, None)
    for od in out["options"]:
        if od.get("image_url") is None:
            od.pop("image_url", None)
    return out


def key_payload(b: Bundle) -> dict[str, Any]:
    """Answer key + explanation (only for review/feedback paths that the policy allows)."""
    out: dict[str, Any] = {"explanation_html": html_of(b.version.explanation)}
    if b.qtype in grading.MCQ_TYPES:
        out["correct_option_ids"] = sorted(str(i) for i in b.correct_option_ids)
    elif b.qtype == grading.ESSAY_TYPE:
        out["reference_answer_html"] = (b.version.answer_key or {}).get("reference_answer_html")
    elif b.qtype in grading.UNGRADED_TYPES or b.qtype == grading.CODING_TYPE:
        pass
    else:
        key = b.version.answer_key or {}
        out["correct_answer"] = (
            key.get("value") if b.qtype == "numeric" else (key.get("accepted") or [None])[0]
        )
    return out


async def published_pool(
    session: AsyncSession,
    *,
    topic_id: uuid.UUID,
    difficulty_min: int | None = None,
    difficulty_max: int | None = None,
    question_types: list[str] | None = None,
    company_id: uuid.UUID | None = None,
) -> list[uuid.UUID]:
    """Current published versions of active questions in the topic subtree (visible bank)."""
    t = await get_topic(session, topic_id)
    q = (
        select(QuestionVersion.id)
        .join(Question, Question.current_version_id == QuestionVersion.id)
        .join(Topic, Topic.id == Question.primary_topic_id)
        .where(
            Question.status == "active",
            Question.deleted_at.is_(None),
            QuestionVersion.status == "published",
            Question.question_type.in_(sorted(grading.OBJECTIVE_TYPES)),
            or_(Topic.id == t.id, Topic.path.like(t.path + "/%")),
        )
    )
    if difficulty_min is not None:
        q = q.where(QuestionVersion.difficulty >= difficulty_min)
    if difficulty_max is not None:
        q = q.where(QuestionVersion.difficulty <= difficulty_max)
    if question_types:
        q = q.where(Question.question_type.in_(question_types))
    if company_id is not None:
        q = q.where(
            Question.id.in_(
                select(QuestionTag.question_id).where(
                    QuestionTag.tag_type == "company", QuestionTag.company_id == company_id
                )
            )
        )
    return list((await session.execute(q.order_by(QuestionVersion.id))).scalars())


# --------------------------------------------------------------------------- companies & paths


def company_out(c: Company) -> dict[str, Any]:
    return {
        "id": str(c.id),
        "slug": c.slug,
        "name": c.name,
        "industry": c.industry,
        "hub_status": c.hub_status,
        "description_md": c.description_md,
    }


async def create_company(session: AsyncSession, body: CompanyCreate) -> Company:
    if (await session.execute(select(Company.id).where(Company.slug == body.slug))).first():
        raise ProblemError("invalid_state_transition", detail="A company with this slug already exists.")
    c = Company(
        id=uuid7(),
        slug=body.slug,
        name=body.name,
        industry=body.industry,
        description_md=body.description_md,
        hub_status=body.hub_status,
    )
    session.add(c)
    await session.flush()
    return c


async def path_steps(session: AsyncSession, path_id: uuid.UUID) -> list[CompanyPathStep]:
    return list(
        (
            await session.execute(
                select(CompanyPathStep)
                .where(CompanyPathStep.company_path_id == path_id)
                .order_by(CompanyPathStep.position)
            )
        ).scalars()
    )


def path_out(p: CompanyPath, steps: list[CompanyPathStep]) -> dict[str, Any]:
    return {
        "id": str(p.id),
        "company_id": str(p.company_id),
        "organization_id": str(p.organization_id) if p.organization_id else None,
        "role_name": p.role_name,
        "version_no": p.version_no,
        "status": p.status,
        "pattern": p.pattern,
        "published_at": to_rfc3339(p.published_at) if p.published_at else None,
        "steps": [
            {
                "id": str(s.id),
                "position": s.position,
                "step_type": s.step_type,
                "title": s.title,
                "topic_id": str(s.topic_id) if s.topic_id else None,
                "test_id": str(s.test_id) if s.test_id else None,
                "lesson_key": str(s.lesson_key) if s.lesson_key else None,
                "is_required": s.is_required,
            }
            for s in steps
        ],
    }


async def list_companies(session: AsyncSession) -> list[dict[str, Any]]:
    companies = list((await session.execute(select(Company).order_by(Company.name))).scalars())
    paths = list((await session.execute(select(CompanyPath).order_by(CompanyPath.role_name))).scalars())
    by_company: dict[uuid.UUID, list[dict[str, Any]]] = defaultdict(list)
    for p in paths:
        by_company[p.company_id].append(path_out(p, await path_steps(session, p.id)))
    return [{**company_out(c), "paths": by_company.get(c.id, [])} for c in companies]


async def put_company_path(
    session: AsyncSession, principal: Principal, path_id: uuid.UUID, body: CompanyPathPut
) -> CompanyPath:
    if await session.get(Company, body.company_id) is None:
        raise ProblemError(
            "validation_failed",
            errors=[{"field": "company_id", "code": "not_found", "message": "unknown company"}],
        )
    for i, sec in enumerate(body.pattern):
        await _validate_topic(session, sec.topic_id, f"pattern.{i}.topic_id")
    for i, st in enumerate(body.steps):
        if st.topic_id is not None:
            await _validate_topic(session, st.topic_id, f"steps.{i}.topic_id")
        if (
            st.test_id is not None
            and not (
                await session.execute(text("SELECT 1 FROM tests WHERE id = :id"), {"id": st.test_id})
            ).first()
        ):
            raise ProblemError(
                "validation_failed",
                errors=[{"field": f"steps.{i}.test_id", "code": "not_found", "message": "unknown test"}],
            )
    pattern = [s.model_dump(mode="json") for s in body.pattern]
    p = await session.get(CompanyPath, path_id)
    now = utcnow()
    if p is None:
        taken = (
            await session.execute(
                select(func.max(CompanyPath.version_no)).where(
                    CompanyPath.company_id == body.company_id, CompanyPath.role_name == body.role_name
                )
            )
        ).scalar_one()
        p = CompanyPath(
            id=path_id,
            company_id=body.company_id,
            organization_id=body.organization_id,
            role_name=body.role_name,
            version_no=(taken or 0) + 1,
            pattern=pattern,
            status=body.status,
            published_at=now if body.status == "published" else None,
            created_by=principal.user_id,
        )
        session.add(p)
        await session.flush()
    else:
        if p.organization_id != body.organization_id or p.company_id != body.company_id:
            raise ProblemError(
                "invalid_state_transition", detail="Owner and company of a path cannot change."
            )
        if p.role_name != body.role_name:
            raise ProblemError("invalid_state_transition", detail="Create a new path for a different role.")
        p.version_no += 1
        p.pattern = pattern
        if body.status == "published" and p.status != "published":
            p.published_at = now
        p.status = body.status
        for s in await path_steps(session, p.id):
            await session.delete(s)
        await session.flush()
    for i, st in enumerate(body.steps):
        session.add(
            CompanyPathStep(
                id=uuid7(),
                company_path_id=p.id,
                organization_id=p.organization_id,
                position=i + 1,
                step_type=st.step_type,
                lesson_key=st.lesson_key,
                test_id=st.test_id,
                topic_id=st.topic_id,
                title=st.title,
                is_required=st.is_required,
            )
        )
    await session.flush()
    return p
