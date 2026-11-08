"""DEV/DEMO ONLY — a few original, simple coding problems with sample + hidden test cases.

Never run against production (refuses outside APP_ENV local/dev/test). Problems are authored by
the content manager ``content@dev.techdrona.local`` (or ``--author <uuid>``) and published,
platform-wide (organization NULL), ``is_free=true``. Idempotent on slug.

Run after ``dev_users``: ``python -m app.seeds.coding_demo [--author <user uuid>]``
Hidden cases are encrypted with ``TD_K_TESTCASE_KEY_V{n}`` (dev fallback key if unset).
"""

from __future__ import annotations

import argparse
import asyncio
import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_sessionmaker, system_context
from app.core.models_registry import import_all_models
from app.core.principal import Principal
from app.modules.coding import service
from app.modules.coding.models import CodingProblem
from app.modules.coding.schemas import ProblemCreateIn, TestCaseIn
from app.modules.identity.models import User
from app.seeds import seeds_allowed

# Seeds run standalone: register every module's tables so cross-module FKs resolve.
import_all_models()

AUTHOR_EMAIL = "content@dev.techdrona.local"

# Original problems written for Tech Drona demo data.
PROBLEMS: list[dict[str, Any]] = [
    {
        "slug": "demo-sum-of-list",
        "title": "Sum of a List",
        "statement_md": "Given `n` integers, print their sum.",
        "input_format_md": "First line: `n`. Second line: `n` space-separated integers.",
        "output_format_md": "A single integer: the sum.",
        "constraints_md": "1 <= n <= 10^5, |a_i| <= 10^9",
        "difficulty": 1,
        "samples": [("3\n1 2 3\n", "6\n")],
        "hidden": [
            ("1\n-5\n", "-5\n", 1),
            ("5\n1000000000 1000000000 1000000000 1000000000 1000000000\n", "5000000000\n", 2),
        ],
    },
    {
        "slug": "demo-count-vowels",
        "title": "Count the Vowels",
        "statement_md": "Print how many characters of the given word are vowels (a, e, i, o, u).",
        "input_format_md": "One lowercase word.",
        "output_format_md": "An integer.",
        "constraints_md": "1 <= length <= 10^5",
        "difficulty": 1,
        "samples": [("drona\n", "2\n")],
        "hidden": [("rhythm\n", "0\n", 1), ("aeiouaeiou\n", "10\n", 1)],
    },
    {
        "slug": "demo-second-largest",
        "title": "Second Largest Distinct Value",
        "statement_md": "Print the second largest *distinct* value, or `-1` if it does not exist.",
        "input_format_md": "First line: `n`. Second line: `n` integers.",
        "output_format_md": "An integer.",
        "constraints_md": "1 <= n <= 10^5",
        "difficulty": 2,
        "samples": [("5\n4 9 9 2 7\n", "7\n")],
        "hidden": [("3\n5 5 5\n", "-1\n", 1), ("4\n-1 -2 -3 -4\n", "-2\n", 1), ("1\n10\n", "-1\n", 1)],
    },
]


class ProductionRefused(RuntimeError):
    pass


def guard() -> None:
    if not seeds_allowed():
        raise ProductionRefused("coding_demo seed refuses to run outside APP_ENV local/dev/test")


async def seed(session: AsyncSession, author: uuid.UUID | None = None) -> list[str]:
    guard()
    await system_context(session, "seed.coding_demo")
    if author is None:
        author = (
            await session.execute(select(User.id).where(User.email == AUTHOR_EMAIL))
        ).scalar_one_or_none()
        if author is None:
            raise RuntimeError(f"{AUTHOR_EMAIL} not found - run `python -m app.seeds.dev_users` first")
    principal = Principal(user_id=author, session_id=uuid.uuid4(), is_platform=True)
    created: list[str] = []
    for spec in PROBLEMS:
        exists = await session.execute(
            select(CodingProblem.id).where(
                CodingProblem.slug == spec["slug"], CodingProblem.organization_id.is_(None)
            )
        )
        if exists.first() is not None:
            continue
        p = await service.create_problem(
            session,
            principal,
            ProblemCreateIn(
                slug=spec["slug"],
                title=spec["title"],
                statement_md=spec["statement_md"],
                input_format_md=spec["input_format_md"],
                output_format_md=spec["output_format_md"],
                constraints_md=spec["constraints_md"],
                difficulty=spec["difficulty"],
                is_free=True,
            ),
        )
        for inp, out in spec["samples"]:
            await service.add_test_case(session, p, TestCaseIn(kind="sample", input=inp, expected_output=out))
        for inp, out, w in spec["hidden"]:
            await service.add_test_case(
                session, p, TestCaseIn(kind="hidden", input=inp, expected_output=out, weight=Decimal(w))
            )
        p.status = "published"  # demo shortcut: no reviewer step
        created.append(spec["slug"])
    await session.flush()
    return created


async def _run(author: uuid.UUID | None) -> list[str]:
    guard()
    async with get_sessionmaker()() as s, s.begin():
        return await seed(s, author)


def main() -> None:
    ap = argparse.ArgumentParser(description="DEV/DEMO coding problems")
    ap.add_argument("--author", type=uuid.UUID)
    a = ap.parse_args()
    print("created:", asyncio.run(_run(a.author)) or "nothing (already seeded)")


if __name__ == "__main__":  # pragma: no cover
    main()
