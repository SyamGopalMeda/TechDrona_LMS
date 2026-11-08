"""DEV / DEMO DATA ONLY — learner/trainer fixtures the Playwright ``@integration`` suite needs on
top of the content seeds. Refuses to run when ``APP_ENV`` is production.

Run after ``dev_users`` and ``placement_demo``:  ``python -m app.seeds.e2e_demo``

Creates (idempotent by slug / grant reason):

* the ``security_monitoring`` consent for ``student@`` (paid checkout needs it for adults,
  PO-03; the restricted fixtures get theirs from ``security_demo``);
* an ``all_practice`` admin grant (365 days, granted by ``admin@``) for the clean learner
  ``student@dev.techdrona.local`` so ``POST /practice/sessions`` is allowed (B3f);
* ``e2e-timed-test`` — a free, published, platform mock of 4 fixed single-choice questions, no
  shuffling, 30 minutes, ``attempts_allowed = 100`` so the timed-test, multi-tab and a11y specs can
  start attempts in one run, and again after a few re-runs (``E2E_TEST_ID``);
* ``demo-batch-weekly-test`` — a published test owned by the company org and authored by
  ``trainer@`` (batch-scoped grant), so ``GET /studio/tests`` as the trainer lists it (B3d);
* one pending ``policy.change`` approval requested by ``admin2@`` (dual control: ``admin@`` can
  open and decide it), so the super-admin approvals spec has a real payload to show. The change
  re-states the current value of ``sessions.staff.max_concurrent`` (a no-op if approved). It
  expires after the normal 72 h approval TTL; a dev-data reset creates a fresh one.
"""

from __future__ import annotations

import asyncio
import sys
import uuid
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.company import COMPANY_ORG_ID
from app.core.config import get_settings
from app.core.db import make_engine, system_context
from app.core.ids import uuid7
from app.core.models_registry import import_all_models
from app.core.principal import Principal
from app.core.time import utcnow
from app.modules.admin import approvals as apr
from app.modules.admin import policy as pol
from app.modules.assessments import studio
from app.modules.assessments.models import Test
from app.modules.assessments.schemas import RuleIn, SectionIn, SectionsPut, TestCreate
from app.modules.entitlements import service as ents
from app.modules.entitlements.models import Entitlement
from app.modules.identity.models import Consent, User
from app.modules.placement.models import Question
from app.modules.rbac.models import ApprovalRequest
from app.seeds import seeds_allowed

# Seeds run standalone: register every module's tables so cross-module FKs resolve.
import_all_models()

DOMAIN = "dev.techdrona.local"
STUDENT = f"student@{DOMAIN}"
GRANTER = f"admin@{DOMAIN}"
AUTHOR = f"content@{DOMAIN}"
TRAINER = f"trainer@{DOMAIN}"
APPROVAL_REQUESTER = f"admin2@{DOMAIN}"
APPROVAL_SETTING = "sessions.staff.max_concurrent"
APPROVAL_REASON = "DEV SEED: pending dual-control approval for the e2e approvals spec (e2e_demo)"
PRACTICE_FEATURE = "all_practice"
GRANT_REASON = "DEV SEED: practice access for the demo learner (e2e_demo)"
E2E_TEST_SLUG = "e2e-timed-test"
E2E_TEST_ATTEMPTS = 100
TRAINER_TEST_SLUG = "demo-batch-weekly-test"
# Single-choice items from placement_demo (the runner specs tick radio buttons on Q1 and Q2).
E2E_QUESTIONS = ("demo:q-pct-1", "demo:q-ser-1", "demo:q-cod-1", "demo:q-voc-2")
TRAINER_QUESTIONS = ("demo:q-py-1", "demo:q-dsa-1", "demo:q-db-1", "demo:q-cn-1")


class ProductionRefused(RuntimeError):
    pass


def guard() -> None:
    if not seeds_allowed():
        raise ProductionRefused("e2e_demo seed refuses to run outside APP_ENV local/dev/test")


async def _uid(session: AsyncSession, email: str) -> uuid.UUID:
    uid = (await session.execute(select(User.id).where(User.email == email))).scalar_one_or_none()
    if uid is None:
        raise RuntimeError(f"{email} not found - run `python -m app.seeds.dev_users` first")
    return uid


async def _questions(session: AsyncSession, refs: tuple[str, ...]) -> list[uuid.UUID]:
    rows = dict(
        (
            await session.execute(
                select(Question.external_ref, Question.id).where(Question.external_ref.in_(refs))
            )
        ).all()
    )
    missing = [r for r in refs if r not in rows]
    if missing:
        raise RuntimeError(f"questions {missing} not found - run `python -m app.seeds.placement_demo` first")
    return [rows[r] for r in refs]


async def _checkout_consent(session: AsyncSession) -> int:
    student = await _uid(session, STUDENT)
    if (
        await session.execute(
            select(Consent.id).where(Consent.user_id == student, Consent.purpose == "security_monitoring")
        )
    ).first():
        return 0
    session.add(
        Consent(
            id=uuid7(),
            user_id=student,
            purpose="security_monitoring",
            action="granted",
            notice_version="2026-11-01",
            channel="support",
        )
    )
    return 1


async def _practice_grant(session: AsyncSession) -> int:
    student = await _uid(session, STUDENT)
    if (
        await session.execute(
            select(Entitlement.id).where(
                Entitlement.user_id == student,
                Entitlement.feature_key == PRACTICE_FEATURE,
                Entitlement.grant_reason == GRANT_REASON,
            )
        )
    ).first():
        return 0
    granter = await _uid(session, GRANTER)
    now = utcnow()
    await ents.grant(
        session,
        ents.Actor.system("seed.e2e_demo"),
        user_id=student,
        source_type="admin_grant",
        feature_key=PRACTICE_FEATURE,
        granted_by=granter,
        reason=GRANT_REASON,
        starts_at=now - timedelta(minutes=1),
        ends_at=now + timedelta(days=365),
    )
    return 1


async def _pending_approval(session: AsyncSession) -> int:
    requester = await _uid(session, APPROVAL_REQUESTER)
    if (
        await session.execute(
            select(ApprovalRequest.id).where(
                ApprovalRequest.requested_by == requester,
                ApprovalRequest.request_reason == APPROVAL_REASON,
                ApprovalRequest.status == "pending",
                ApprovalRequest.expires_at > utcnow(),
            )
        )
    ).first():
        return 0
    value = await pol.get_value(session, APPROVAL_SETTING)
    await apr.new_request(
        session,
        Principal(user_id=requester, session_id=uuid7(), is_platform=True),
        action_type="policy.change",
        target_type="policy_setting",
        target_id=None,
        payload={
            "setting_key": APPROVAL_SETTING,
            "scope_type": "platform",
            "scope_id": None,
            "value": value,
            "effective_from": None,
            "change_reason": APPROVAL_REASON,
        },
        reason=APPROVAL_REASON,
        required_approver_role="super_admin",
    )
    return 1


async def _test(
    session: AsyncSession,
    *,
    slug: str,
    title: str,
    author: Principal,
    org_id: uuid.UUID | None,
    questions: list[uuid.UUID],
    attempts: int,
    is_free: bool,
) -> int:
    if (await session.execute(select(Test.id).where(Test.slug == slug))).first():
        return 0
    t = await studio.create_test(
        session,
        author,
        TestCreate(
            title=title,
            slug=slug,
            test_kind="mock",
            duration_seconds=30 * 60,
            attempts_allowed=attempts,
            shuffle_questions=False,
            shuffle_options=False,
            is_free=is_free,
        ),
        org_id,
    )
    await studio.put_sections(
        session,
        t,
        SectionsPut(
            sections=[
                SectionIn(
                    title="Section A",
                    rules=[RuleIn(rule_type="fixed", question_id=q) for q in questions],
                )
            ]
        ),
    )
    await studio.publish(session, t)
    return 1


async def seed(session: AsyncSession) -> dict[str, int]:
    guard()
    await system_context(session, "seed.e2e_demo")
    made = {
        "consents": await _checkout_consent(session),
        "practice_grants": await _practice_grant(session),
        "tests": 0,
        "approvals": await _pending_approval(session),
    }
    content = Principal(user_id=await _uid(session, AUTHOR), session_id=uuid7(), is_platform=True)
    made["tests"] += await _test(
        session,
        slug=E2E_TEST_SLUG,
        title="E2E Timed Test (dev fixture)",
        author=content,
        org_id=None,
        questions=await _questions(session, E2E_QUESTIONS),
        attempts=E2E_TEST_ATTEMPTS,
        is_free=True,
    )
    org_id = COMPANY_ORG_ID
    trainer = Principal(
        user_id=await _uid(session, TRAINER), session_id=uuid7(), tier="staff", org_ids=(org_id,)
    )
    made["tests"] += await _test(
        session,
        slug=TRAINER_TEST_SLUG,
        title="Demo Batch Weekly Test (sample)",
        author=trainer,
        org_id=org_id,
        questions=await _questions(session, TRAINER_QUESTIONS),
        attempts=1,
        is_free=False,
    )
    await session.flush()
    return made


async def main() -> int:
    guard()
    engine = make_engine(get_settings().DATABASE_URL)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session, session.begin():
            made = await seed(session)
    finally:
        await engine.dispose()
    print("DEV/DEMO e2e fixtures ready:", made)
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(asyncio.run(main()))
