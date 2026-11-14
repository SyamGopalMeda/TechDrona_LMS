"""DEV / DEMO DATA ONLY — single-company demo content so every new feature has something to click.
Never run against production: refuses outside ``APP_ENV`` local/dev/test.

Run after ``dev_users``, ``placement_demo`` and ``e2e_demo`` (it reuses their accounts, questions
and the trainer's ``demo-batch-weekly-test``):  ``python -m app.seeds.company_demo``

Creates in the company org (``COMPANY_ORG_ID``), idempotent by the stable keys below:

* question bank ``[DEMO] Aptitude starter bank`` (platform, by ``content@``) holding every
  ``demo:`` placement question (WS5 question banks);
* path article ``[DEMO] Welcome to CSE 2027`` published with audience ``batches`` →
  ``DEMO-CSE-27`` (WS4 ``paths_0002``);
* learning path ``[DEMO] Placement foundations`` (by ``trainer@``): an embeddable YouTube
  (``www.youtube-nocookie.com/embed``) video step and a Google Docs preview reading step (D9),
  the article above and the platform mock ``demo-aptitude-mock``; published and allocated to
  ``DEMO-CSE-27``;
* engage quiz ``[DEMO] Monday warm-up quiz`` on ``DEMO-CSE-27`` (owner ``trainer@``), ready to launch;
* test assignment of ``demo-batch-weekly-test`` to ``DEMO-CSE-27`` (manual result release, so the
  evaluator can publish results — D3);
* structured assignment ``[DEMO] DBMS short answers`` for ``DEMO-CSE-27``, allocated with
  ``evaluator@`` as named evaluator (``pure_manual`` engine) and one submitted answer from
  ``asha.student@`` waiting to be graded.

Services are not called where they need an HTTP request / permission checker (path create and
allocate, engage create, test assign, assignment allocate); the rows are written exactly as those
services write them, and the request-free service helpers are reused for the rest.
"""

from __future__ import annotations

import asyncio
import sys
import uuid
from datetime import timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.company import COMPANY_ORG_ID
from app.core.config import get_settings
from app.core.db import make_engine, system_context
from app.core.ids import uuid7
from app.core.models_registry import import_all_models
from app.core.principal import Principal
from app.core.time import utcnow
from app.modules.assessments.models import Test, TestAssignment
from app.modules.engage import service as engage
from app.modules.engage.models import EngageActivity
from app.modules.engage.schemas import ActivityIn, OptionIn, QuestionIn
from app.modules.identity.models import User
from app.modules.learning import structured as st
from app.modules.learning.models import (
    Assignment,
    AssignmentAllocation,
    AssignmentItem,
    AssignmentSubmission,
)
from app.modules.orgs.models import Batch
from app.modules.paths import service as paths
from app.modules.paths.models import LearningPath, PathAllocation, PathArticle
from app.modules.placement import banks
from app.modules.placement.models import Question, QuestionBank
from app.modules.placement.schemas import BankCreate
from app.seeds import dev_users, e2e_demo, placement_demo, seeds_allowed
from app.seeds.sync import sync_touched

# Seeds run standalone: register every module's tables so cross-module FKs resolve.
import_all_models()

DOMAIN = dev_users.DOMAIN
CONTENT = f"content@{DOMAIN}"
TRAINER = f"trainer@{DOMAIN}"
EVALUATOR = f"evaluator@{DOMAIN}"
SUBMITTER = f"asha.student@{DOMAIN}"
BATCH_CODE = dev_users.BATCH_CODE

BANK_NAME = "[DEMO] Aptitude starter bank"
ARTICLE_TITLE = "[DEMO] Welcome to CSE 2027"
PATH_TITLE = "[DEMO] Placement foundations"
ACTIVITY_TITLE = "[DEMO] Monday warm-up quiz"
ASSIGNMENT_TITLE = "[DEMO] DBMS short answers"
# D9: only these embed forms render inline (paths.service.embeddable).
VIDEO_URL = "https://www.youtube-nocookie.com/embed/8hly31xKli0"
READING_URL = "https://docs.google.com/document/d/1DemoTechDronaReadingNotes/preview"

ARTICLE_BODY = """# Welcome to CSE 2027

This batch follows the **Placement foundations** path. Each week:

## What to do
- Watch the lesson video and read the notes.
- Take the weekly test your trainer assigns.
- Join the Monday warm-up quiz in Engage.

## Getting help
Ask your trainer in the batch announcements. *(Synthetic demo content.)*
"""

ESSAY_PROMPT = "Explain, in your own words, why a database table is normalised to 3NF. Give one example."
ESSAY_ANSWER = (
    "Normalising to 3NF removes transitive dependencies, so each fact is stored once. Example: "
    "keep the department name in a departments table instead of repeating it on every employee row."
)


class ProductionRefused(RuntimeError):
    pass


def guard() -> None:
    if not seeds_allowed():
        raise ProductionRefused("company_demo seed refuses to run outside APP_ENV local/dev/test")


async def _uid(session: AsyncSession, email: str) -> uuid.UUID:
    uid = (await session.execute(select(User.id).where(User.email == email))).scalar_one_or_none()
    if uid is None:
        raise RuntimeError(f"{email} not found - run `python -m app.seeds.dev_users` first")
    return uid


def _p(uid: uuid.UUID, *, platform: bool = False) -> Principal:
    if platform:
        return Principal(user_id=uid, session_id=uuid7(), tier="staff", is_platform=True)
    return Principal(user_id=uid, session_id=uuid7(), tier="staff", org_ids=(COMPANY_ORG_ID,))


async def _batch(session: AsyncSession) -> Batch:
    b = (
        await session.execute(
            select(Batch).where(Batch.organization_id == COMPANY_ORG_ID, Batch.code == BATCH_CODE)
        )
    ).scalar_one_or_none()
    if b is None:
        raise RuntimeError(f"batch {BATCH_CODE} not found - run `python -m app.seeds.dev_users` first")
    return b


async def _test(session: AsyncSession, slug: str, seed_name: str) -> Test:
    t = (await session.execute(select(Test).where(Test.slug == slug))).scalar_one_or_none()
    if t is None:
        raise RuntimeError(f"test {slug} not found - run `python -m app.seeds.{seed_name}` first")
    return t


async def _question_bank(session: AsyncSession, content: uuid.UUID) -> int:
    b = (
        await session.execute(
            select(QuestionBank).where(
                QuestionBank.name == BANK_NAME,
                QuestionBank.organization_id.is_(None),
                QuestionBank.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    made = 0
    if b is None:
        b = await banks.create_bank(
            session,
            _p(content, platform=True),
            BankCreate(
                name=BANK_NAME,
                subject="Aptitude and CS fundamentals",
                description="Synthetic demo bank: the original sample questions from placement_demo.",
            ),
        )
        made = 1
    qids = list(
        (
            await session.execute(
                select(Question.id)
                .where(Question.external_ref.like("demo:%"), Question.status == "active")
                .order_by(Question.external_ref)
            )
        ).scalars()
    )
    await banks.add_questions(session, _p(content, platform=True), b, qids)  # skips present ones
    return made


async def _article(session: AsyncSession, trainer: uuid.UUID, batch: Batch) -> tuple[PathArticle, int]:
    a = (
        await session.execute(
            select(PathArticle).where(
                PathArticle.title == ARTICLE_TITLE,
                PathArticle.organization_id == COMPANY_ORG_ID,
                PathArticle.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if a is not None:
        return a, 0
    p = _p(trainer)
    a = await paths._new_article(
        session,
        p,
        COMPANY_ORG_ID,
        title=ARTICLE_TITLE,
        subtitle="How this batch works",
        level="beginner",
        est_minutes=3,
        body_md=ARTICLE_BODY,
    )
    await paths.publish_article(None, session, p, a, {"audience": "batches", "batch_ids": [batch.id]})  # type: ignore[arg-type]
    return a, 1


async def _path(session: AsyncSession, trainer: uuid.UUID, batch: Batch, article: PathArticle) -> int:
    lp = (
        await session.execute(
            select(LearningPath).where(
                LearningPath.title == PATH_TITLE,
                LearningPath.organization_id == COMPANY_ORG_ID,
                LearningPath.status != "archived",
            )
        )
    ).scalar_one_or_none()
    made = 0
    p = _p(trainer)
    if lp is None:
        # Mirrors paths.service.create_path (which needs the request-bound permission checker).
        lp = LearningPath(
            id=uuid7(),
            organization_id=COMPANY_ORG_ID,
            title=PATH_TITLE,
            description_md="Synthetic demo path: one week of aptitude and DSA basics.",
            level="beginner",
            source="manual",
            status="draft",
            version_no=0,
            has_unpublished_changes=True,
            created_by=trainer,
        )
        session.add(lp)
        await session.flush()
        mock = await _test(session, placement_demo.DEMO_TEST_SLUG, "placement_demo")
        steps: list[dict[str, Any]] = [
            {
                "step_type": "article",
                "title": "Read the batch welcome",
                "article_id": article.id,
                "est_hours": 0.25,
            },
            {
                "step_type": "super_step",
                "title": "Week 1: arrays and complexity",
                "children": [
                    {
                        "step_type": "video",
                        "title": "Big-O in ten minutes",
                        "url": VIDEO_URL,
                        "est_hours": 0.5,
                        "credits": 5,
                    },
                    {
                        "step_type": "reading",
                        "title": "Lecture notes (Google Docs)",
                        "url": READING_URL,
                        "est_hours": 0.5,
                        "credits": 5,
                    },
                ],
            },
            {
                "step_type": "assessment",
                "title": "Aptitude mock",
                "test_id": mock.id,
                "est_hours": 0.5,
                "credits": 10,
            },
        ]
        await paths.replace_steps(session, p, lp, steps)
        await paths.publish_path(session, p, lp)
        made = 1
    allocated = (
        await session.execute(
            select(PathAllocation.id).where(
                PathAllocation.path_id == lp.id,
                PathAllocation.batch_id == batch.id,
                PathAllocation.status == "active",
            )
        )
    ).first()
    if allocated is None and lp.current_version_id is not None:
        # Mirrors paths.service.create_allocation (batch target).
        start = utcnow().date()
        pace = {"mode": "weekdays", "hours_per_day": 1}
        plan = await paths._plan_for(lp, session, start, pace)
        session.add(
            PathAllocation(
                id=uuid7(),
                organization_id=COMPANY_ORG_ID,
                path_id=lp.id,
                path_version_id=lp.current_version_id,
                target_type="batch",
                batch_id=batch.id,
                user_ids=[],
                flow="lenient",
                sequential=False,
                start_date=start,
                pace={"mode": "weekdays", "per_day": paths._plan_out(plan)["per_day"]},
                weekly_hours=plan["weekly_hours"],
                total_hours=plan["total_hours"],
                finish_date=plan["finish_date"],
                status="active",
                created_by=trainer,
            )
        )
        await session.flush()
    return made


async def _engage(session: AsyncSession, trainer: uuid.UUID, batch: Batch) -> int:
    if (
        await session.execute(
            select(EngageActivity.id).where(
                EngageActivity.title == ACTIVITY_TITLE,
                EngageActivity.batch_id == batch.id,
                EngageActivity.deleted_at.is_(None),
            )
        )
    ).first():
        return 0
    body = engage.validate_activity(
        ActivityIn(
            activity_type="quiz",
            title=ACTIVITY_TITLE,
            description="Two quick questions to start the week (synthetic demo).",
            batch_id=batch.id,
            questions=[
                QuestionIn(
                    kind="single_choice",
                    prompt="Worst-case steps for binary search on a sorted array of n items?",
                    options=[
                        OptionIn(text="O(n)"),
                        OptionIn(text="O(log n)", is_correct=True),
                        OptionIn(text="O(1)"),
                    ],
                ),
                QuestionIn(
                    kind="single_choice",
                    prompt="Which OSI layer routes packets between networks?",
                    options=[
                        OptionIn(text="Transport"),
                        OptionIn(text="Network", is_correct=True),
                        OptionIn(text="Session"),
                    ],
                ),
            ],
        )
    )
    # Mirrors engage.service.create_activity for a batch activity (owner = the batch trainer).
    a = EngageActivity(id=uuid7(), owner_id=trainer)
    engage._apply_settings(a, body, batch.organization_id)
    session.add(a)
    await session.flush()
    session.add_all(engage._question_rows(a, body))
    await session.flush()
    return 1


async def _test_assignment(session: AsyncSession, trainer: uuid.UUID, batch: Batch) -> int:
    t = await _test(session, e2e_demo.TRAINER_TEST_SLUG, "e2e_demo")
    if (
        await session.execute(
            select(TestAssignment.id).where(
                TestAssignment.test_id == t.id, TestAssignment.batch_id == batch.id
            )
        )
    ).first():
        return 0
    now = utcnow()
    # Mirrors assessments.studio.create_assignment.
    session.add(
        TestAssignment(
            id=uuid7(),
            test_id=t.id,
            organization_id=batch.organization_id,
            batch_id=batch.id,
            available_from=now - timedelta(days=1),
            available_until=now + timedelta(days=30),
            attempts_allowed=None,
            release_mode="manual",
            assigned_by=trainer,
        )
    )
    await session.flush()
    return 1


async def _structured_assignment(
    session: AsyncSession, trainer: uuid.UUID, evaluator: uuid.UUID, batch: Batch
) -> int:
    a = (
        await session.execute(
            select(Assignment).where(
                Assignment.title == ASSIGNMENT_TITLE,
                Assignment.batch_id == batch.id,
                Assignment.submission_type == "structured",
            )
        )
    ).scalar_one_or_none()
    made = 0
    now = utcnow()
    if a is None:
        a = Assignment(
            id=uuid7(),
            organization_id=batch.organization_id,
            batch_id=batch.id,
            title=ASSIGNMENT_TITLE,
            instructions_md="Answer in a few sentences. Synthetic demo assignment.",
            submission_type="structured",
            ai_help_enabled=False,
            max_score=Decimal("10"),
            allowed_file_types=["pdf", "txt"],
            due_at=now + timedelta(days=14),
            created_by=trainer,
        )
        session.add(a)
        await session.flush()
        await st.put_structure(
            session,
            a,
            [
                st.SectionSpec(
                    title="Short answers",
                    max_score=Decimal("10"),
                    items=[
                        st.ItemSpec(
                            source="inline",
                            item_type="essay",
                            prompt_md=ESSAY_PROMPT,
                            marks=Decimal("10"),
                            reference_answer_md="Mentions transitive dependencies and gives a valid split.",
                        )
                    ],
                )
            ],
        )
        made = 1
    al = (
        await session.execute(select(AssignmentAllocation).where(AssignmentAllocation.assignment_id == a.id))
    ).scalar_one_or_none()
    if al is None:
        sections = [s.id for s, _ in await st.load_structure(session, a.id)]
        # Mirrors structured_api.allocate: batch target, the evaluator named, manual grading.
        al = AssignmentAllocation(
            id=uuid7(),
            assignment_id=a.id,
            organization_id=batch.organization_id,
            batch_id=batch.id,
            user_ids=[],
            start_at=now - timedelta(days=1),
            due_at=now + timedelta(days=14),
            section_engines=st.check_engines({str(s): "pure_manual" for s in sections}, sections),
            evaluator_ids=[evaluator],
            extensions={},
            created_by=trainer,
        )
        session.add(al)
        await session.flush()
    learner = await _uid(session, SUBMITTER)
    sub = (
        await session.execute(
            select(AssignmentSubmission).where(
                AssignmentSubmission.assignment_id == a.id, AssignmentSubmission.user_id == learner
            )
        )
    ).scalar_one_or_none()
    if sub is None:
        # Mirrors start_workspace + autosave + submit_workspace for one learner.
        sub = AssignmentSubmission(
            id=uuid7(),
            assignment_id=a.id,
            user_id=learner,
            organization_id=a.organization_id,
            attempt_no=1,
            status="submitted",
            submitted_at=now,
            allocation_id=al.id,
            file_s3_keys=[],
        )
        session.add(sub)
        await session.flush()
        item = (
            await session.execute(select(AssignmentItem).where(AssignmentItem.assignment_id == a.id))
        ).scalar_one()
        await st.upsert_response(session, sub, item, {"text": ESSAY_ANSWER})
        await st.refresh_auto_marks(session, sub, al)
    return made


async def seed(session: AsyncSession) -> dict[str, int]:
    guard()
    await system_context(session, "seed.company_demo")
    content = await _uid(session, CONTENT)
    trainer = await _uid(session, TRAINER)
    evaluator = await _uid(session, EVALUATOR)
    batch = await _batch(session)
    made = {"question_banks": await _question_bank(session, content)}
    article, made["articles"] = await _article(session, trainer, batch)
    made["paths"] = await _path(session, trainer, batch, article)
    made["engage_activities"] = await _engage(session, trainer, batch)
    made["test_assignments"] = await _test_assignment(session, trainer, batch)
    made["structured_assignments"] = await _structured_assignment(session, trainer, evaluator, batch)
    await session.flush()
    return made


async def main() -> int:
    guard()
    engine = make_engine(get_settings().DATABASE_URL)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session, session.begin():
            made = await seed(session)
            await sync_touched(
                session,
                "identity",
                "orgs",
                "learning",
                "assessments",
                "engage",
                "paths",
                "placement",
            )
    finally:
        await engine.dispose()
    print("DEV/DEMO single-company content ready:", made)
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(asyncio.run(main()))
