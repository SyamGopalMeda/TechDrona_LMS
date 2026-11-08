"""Coding test fixtures: fake judge, entitlement checker switch, users, problems."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.access import AccessDecision, get_access_checker, register_access_checker
from app.core.db import system_context
from app.core.principal import Principal
from app.modules.coding import service
from app.modules.coding.crypto import reset_testcase_keyring
from app.modules.coding.judge_gateway import FakeJudgeAdapter, set_judge_adapter
from app.modules.coding.schemas import ProblemCreateIn, TestCaseIn
from tests.identity.factory import make_user

KEY_V1 = "a1" * 32
KEY_V2 = "b2" * 32
# Distinctive hidden data: tests assert these strings never appear in any response.
HIDDEN_INPUT = "424242 SECRET_HIDDEN_INPUT_7f3a\n"
HIDDEN_EXPECTED = "SECRET_HIDDEN_EXPECTED_9c1e\n"


@pytest.fixture(autouse=True)
def testcase_key(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("TD_K_TESTCASE_KEY_V1", KEY_V1)
    monkeypatch.setenv("TD_K_TESTCASE_ACTIVE_VERSION", "1")
    monkeypatch.delenv("TD_K_TESTCASE_KEY_V2", raising=False)
    reset_testcase_keyring()
    yield
    reset_testcase_keyring()


@pytest.fixture
def fake_judge() -> Iterator[FakeJudgeAdapter]:
    adapter = FakeJudgeAdapter()
    set_judge_adapter(adapter)
    yield adapter
    set_judge_adapter(None)


class _Access:
    def __init__(self) -> None:
        self.allow = True
        self.calls: list[tuple[str, uuid.UUID]] = []

    async def check(
        self, session: Any, principal: Any, resource_type: Any, resource_id: Any, *, is_free: bool = False
    ):
        self.calls.append((resource_type, resource_id))
        if is_free:
            return AccessDecision(True, "free")
        return AccessDecision(self.allow, "entitlement" if self.allow else "no_entitlement")


@pytest.fixture
def access() -> Iterator[_Access]:
    prev = get_access_checker()
    a = _Access()
    register_access_checker(a)
    yield a
    register_access_checker(prev)


@dataclass
class Actor:
    principal: Principal
    headers: dict[str, str]

    @property
    def id(self) -> uuid.UUID:
        return self.principal.user_id


@pytest.fixture
def actors(db: AsyncSession, auth: Any) -> Any:
    async def _make(*perms: str, **kw: Any) -> Actor:
        u = await make_user(db)
        p = Principal(user_id=u.id, session_id=uuid.uuid4(), **kw)
        for perm in perms:
            auth.grant(p, perm)
        return Actor(p, auth.login(p))

    return _make


def idem(headers: dict[str, str], key: str | None = None) -> dict[str, str]:
    return {**headers, "Idempotency-Key": key or f"k-{uuid.uuid4()}"}


async def seed_problem(
    db: AsyncSession,
    author: uuid.UUID,
    *,
    slug: str | None = None,
    hidden: int = 2,
    weights: list[Decimal] | None = None,
    scoring_mode: str = "weighted_cases",
    is_free: bool = False,
    publish: bool = True,
) -> Any:
    await system_context(db, "test.factory")
    p = await service.create_problem(
        db,
        Principal(user_id=author, session_id=uuid.uuid4()),
        ProblemCreateIn(
            slug=slug or f"sum-{uuid.uuid4().hex[:8]}",
            title="Sum of numbers",
            statement_md="Print the sum.",
            difficulty=1,
            scoring_mode=scoring_mode,  # type: ignore[arg-type]
            is_free=is_free,
        ),
    )
    await service.add_test_case(db, p, TestCaseIn(kind="sample", input="3\n1 2 3\n", expected_output="6\n"))
    ws = weights or [Decimal(1)] * hidden
    for i, w in enumerate(ws):
        await service.add_test_case(
            db,
            p,
            TestCaseIn(
                kind="hidden", input=f"{i}{HIDDEN_INPUT}", expected_output=f"{i}{HIDDEN_EXPECTED}", weight=w
            ),
        )
    if publish:
        p.status = "published"
        await db.flush()
    return p
