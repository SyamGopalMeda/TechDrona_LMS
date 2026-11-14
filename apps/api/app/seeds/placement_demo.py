"""DEV / DEMO DATA ONLY — a small, ORIGINAL sample question bank, one demo company and one
free demo mock for local development and demos. Never run against production: the script
refuses when ``APP_ENV`` is ``prod``/``production``.

Every question below was written for this seed (no third-party or "actual exam" content); each
is tagged ``source = demo`` and has ``external_ref = demo:<key>``. They are illustrative
"pattern-aligned practice" items only.

Run after ``alembic upgrade heads`` and ``python -m app.seeds.dev_users`` (the content manager
``content@dev.techdrona.local`` authors, ``admin@dev.techdrona.local`` reviews):

    python -m app.seeds.placement_demo

Idempotent: questions whose ``external_ref`` already exists, and the demo company/test, are skipped.
"""

from __future__ import annotations

import asyncio
import sys
import uuid
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import get_settings
from app.core.db import make_engine, system_context
from app.core.ids import uuid7
from app.core.models_registry import import_all_models
from app.core.principal import Principal
from app.modules.assessments import studio
from app.modules.assessments.models import Test
from app.modules.assessments.schemas import RuleIn, SectionIn, SectionsPut, TestCreate
from app.modules.identity.models import User
from app.modules.placement import bank
from app.modules.placement.models import Company, Question, Topic
from app.modules.placement.schemas import (
    CompanyCreate,
    OptionIn,
    QuestionCreate,
    TagIn,
)
from app.seeds import seeds_allowed
from app.seeds.sync import sync_touched

# Seeds run standalone: register every module's tables so cross-module FKs resolve.
import_all_models()

AUTHOR_EMAIL = "content@dev.techdrona.local"
REVIEWER_EMAIL = "admin@dev.techdrona.local"
DEMO_COMPANY_SLUG = "demo-tech"
DEMO_TEST_SLUG = "demo-aptitude-mock"

# (subject slug, subject name, topic slug, topic name)
TOPICS = [
    ("quant", "Quantitative Aptitude", "percentages", "Percentages"),
    ("quant", "Quantitative Aptitude", "time-speed-distance", "Time, Speed and Distance"),
    ("logical", "Logical Reasoning", "series", "Number Series"),
    ("logical", "Logical Reasoning", "coding-decoding", "Coding-Decoding"),
    ("verbal", "Verbal Ability", "vocabulary", "Vocabulary"),
    ("programming", "Programming", "python-basics", "Python Basics"),
    ("dsa", "Data Structures and Algorithms", "searching", "Searching"),
    ("dsa", "Data Structures and Algorithms", "trees", "Trees"),
    ("cs-core", "CS Fundamentals", "dbms", "DBMS"),
    ("cs-core", "CS Fundamentals", "networks", "Computer Networks"),
]


@dataclass
class DemoQ:
    key: str
    topic: str  # "<subject>/<topic>"
    qtype: str
    stem: str
    explanation: str
    options: list[tuple[str, bool]] = field(default_factory=list)
    answer_key: dict[str, Any] | None = None
    difficulty: int = 2


QUESTIONS: list[DemoQ] = [
    DemoQ(
        "q-pct-1",
        "quant/percentages",
        "mcq_single",
        "A price is raised by 20% and the new price is then reduced by 20%. What is the net change?",
        "Take 100: after +20% it is 120; 20% of 120 is 24, so it falls to 96 — a 4% decrease.",
        [("No change", False), ("4% decrease", True), ("4% increase", False), ("2% decrease", False)],
    ),
    DemoQ(
        "q-tsd-1",
        "quant/time-speed-distance",
        "numeric",
        "A 150 m long train passes a signal post in 10 seconds. What is its speed in km/h?",
        "Speed = 150 / 10 = 15 m/s; 15 x 18/5 = 54 km/h.",
        answer_key={"value": "54", "tolerance": "0"},
    ),
    DemoQ(
        "q-ser-1",
        "logical/series",
        "mcq_single",
        "Find the next number: 3, 7, 15, 31, ?",
        "Each term is (previous x 2) + 1: 31 x 2 + 1 = 63.",
        [("47", False), ("62", False), ("63", True), ("65", False)],
    ),
    DemoQ(
        "q-cod-1",
        "logical/coding-decoding",
        "mcq_single",
        "In a code, every letter is replaced by the next letter of the alphabet (CAT becomes DBU). "
        "How is LEMON written?",
        "Shift each letter by one: L-M, E-F, M-N, O-P, N-O, giving MFNPO.",
        [("MFNPO", True), ("KDLNM", False), ("MFOPN", False), ("NFNPO", False)],
    ),
    DemoQ(
        "q-voc-1",
        "verbal/vocabulary",
        "fill_blank",
        "Fill in the blank with one word meaning 'unwilling': Ravi was ______ to lend his new bike.",
        "'Reluctant' means unwilling or hesitant.",
        answer_key={"accepted": ["reluctant"], "case_sensitive": False},
    ),
    DemoQ(
        "q-voc-2",
        "verbal/vocabulary",
        "mcq_single",
        "Choose the word closest in meaning to CANDID.",
        "Candid means honest and open, i.e. frank.",
        [("Frank", True), ("Secretive", False), ("Careful", False), ("Angry", False)],
    ),
    DemoQ(
        "q-py-1",
        "programming/python-basics",
        "mcq_single",
        "What does this Python code print? <pre><code>print(len([1, [2, 3], 4]))</code></pre>",
        "The list has three elements: 1, the inner list [2, 3], and 4.",
        [("3", True), ("4", False), ("2", False), ("Error", False)],
    ),
    DemoQ(
        "q-py-2",
        "programming/python-basics",
        "mcq_multi",
        "Which of these Python built-in types are immutable? (Select all that apply.)",
        "tuple and str cannot be changed in place; list and dict can.",
        [("tuple", True), ("list", False), ("str", True), ("dict", False)],
    ),
    DemoQ(
        "q-dsa-1",
        "dsa/searching",
        "mcq_single",
        "What is the worst-case time complexity of binary search on a sorted array of n elements?",
        "Each comparison halves the search range, so about log2(n) steps are needed.",
        [("O(n)", False), ("O(log n)", True), ("O(n log n)", False), ("O(1)", False)],
    ),
    DemoQ(
        "q-dsa-2",
        "dsa/trees",
        "numeric",
        "What is the maximum number of nodes in a binary tree of height 3, if the root alone has height 0?",
        "Levels 0..3 hold at most 1 + 2 + 4 + 8 = 15 nodes (2^(h+1) - 1).",
        answer_key={"value": "15", "tolerance": "0"},
        difficulty=3,
    ),
    DemoQ(
        "q-db-1",
        "cs-core/dbms",
        "mcq_single",
        "Removing partial dependencies of non-key attributes on a composite key brings a relation "
        "to which normal form?",
        "2NF requires 1NF plus no partial dependency on part of a candidate key.",
        [("1NF", False), ("2NF", True), ("3NF", False), ("BCNF", False)],
    ),
    DemoQ(
        "q-cn-1",
        "cs-core/networks",
        "mcq_single",
        "Which OSI layer is primarily responsible for routing packets between networks?",
        "Routing (logical addressing and path selection) is the job of the Network layer.",
        [("Data link", False), ("Network", True), ("Transport", False), ("Session", False)],
    ),
]


class ProductionRefused(RuntimeError):
    pass


def guard() -> None:
    if not seeds_allowed():
        raise ProductionRefused("placement_demo seed refuses to run outside APP_ENV local/dev/test")


async def _user(session: AsyncSession, email: str) -> uuid.UUID:
    uid = (await session.execute(select(User.id).where(User.email == email))).scalar_one_or_none()
    if uid is None:
        raise RuntimeError(f"{email} not found - run `python -m app.seeds.dev_users` first")
    return uid


async def _topics(session: AsyncSession) -> dict[str, uuid.UUID]:
    out: dict[str, uuid.UUID] = {}
    for i, (sslug, sname, tslug, tname) in enumerate(TOPICS):
        for path, slug, name, parent, kind, depth in (
            (sslug, sslug, sname, None, "subject", 0),
            (f"{sslug}/{tslug}", tslug, tname, sslug, "topic", 1),
        ):
            if path in out:
                continue
            tid = (await session.execute(select(Topic.id).where(Topic.path == path))).scalar_one_or_none()
            if tid is None:
                tid = uuid7()
                session.add(
                    Topic(
                        id=tid,
                        parent_id=out.get(parent) if parent else None,
                        kind=kind,
                        slug=slug,
                        name=name,
                        path=path,
                        depth=depth,
                        position=i,
                    )
                )
                await session.flush()
            out[path] = tid
    return out


async def seed(session: AsyncSession) -> dict[str, int]:
    guard()
    await system_context(session, "seed.placement_demo")
    author = Principal(user_id=await _user(session, AUTHOR_EMAIL), session_id=uuid7(), is_platform=True)
    reviewer = Principal(user_id=await _user(session, REVIEWER_EMAIL), session_id=uuid7(), is_platform=True)
    topics = await _topics(session)
    created = 0
    for dq in QUESTIONS:
        ref = f"demo:{dq.key}"
        if (await session.execute(select(Question.id).where(Question.external_ref == ref))).first():
            continue
        body = QuestionCreate(
            question_type=dq.qtype,
            primary_topic_id=topics[dq.topic],
            stem_html=f"<p>{dq.stem}</p>",
            options=[OptionIn(html=t, is_correct=c) for t, c in dq.options],
            answer_key=dq.answer_key,
            explanation_html=f"<p>{dq.explanation}</p>",
            difficulty=dq.difficulty,
            default_marks=Decimal("1"),
            default_negative=Decimal("0"),
            expected_seconds=60,
            tags=[TagIn(tag_type="source", value="demo")],
            external_ref=ref,
        )
        q, _ = await bank.create_question(session, author, body)
        await bank.submit_review(session, q.id)
        await bank.review(session, reviewer, q.id, "approve")
        await bank.publish(session, q.id)
        created += 1

    company = (
        await session.execute(select(Company).where(Company.slug == DEMO_COMPANY_SLUG))
    ).scalar_one_or_none()
    if company is None:
        company = await bank.create_company(
            session,
            CompanyCreate(
                slug=DEMO_COMPANY_SLUG,
                name="Demo Tech (sample company)",
                industry="IT services",
                hub_status="published",
                description_md="Sample company hub for demos. Pattern-aligned practice only.",
            ),
        )

    test_made = 0
    if not (await session.execute(select(Test.id).where(Test.slug == DEMO_TEST_SLUG))).first():
        t = await studio.create_test(
            session,
            author,
            TestCreate(
                title="Demo Aptitude Mock (sample)",
                slug=DEMO_TEST_SLUG,
                test_kind="mock",
                duration_seconds=20 * 60,
                is_free=True,
                company_id=company.id,
                attempts_allowed=3,
            ),
            None,
        )
        await studio.put_sections(
            session,
            t,
            SectionsPut(
                sections=[
                    SectionIn(
                        title="Aptitude and Reasoning",
                        rules=[
                            RuleIn(
                                rule_type="random",
                                topic_id=topics["quant"],
                                draw_count=2,
                                negative_marks_each=Decimal("0.25"),
                            ),
                            RuleIn(
                                rule_type="random",
                                topic_id=topics["logical"],
                                draw_count=2,
                                negative_marks_each=Decimal("0.25"),
                            ),
                        ],
                    ),
                    SectionIn(
                        title="Technical",
                        rules=[
                            RuleIn(rule_type="random", topic_id=topics["programming"], draw_count=1),
                            RuleIn(rule_type="random", topic_id=topics["dsa"], draw_count=1),
                            RuleIn(rule_type="random", topic_id=topics["cs-core"], draw_count=1),
                        ],
                    ),
                ]
            ),
        )
        await studio.publish(session, t)
        test_made = 1
    await session.flush()
    return {"questions_created": created, "tests_created": test_made}


async def main() -> int:
    guard()
    engine = make_engine(get_settings().DATABASE_URL)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session, session.begin():
            result = await seed(session)
            await sync_touched(session, "placement", "assessments", "identity")
    finally:
        await engine.dispose()
    print("DEV/DEMO placement content ready (synthetic, original sample items):", result)
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(asyncio.run(main()))
