"""Test authoring, assignments, overrides and result release (ASM-03..16, ASM-21)."""

from __future__ import annotations

import dataclasses
import uuid
from datetime import timedelta
from typing import Any

from fastapi import Request
from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import audit
from app.core.auth import PLATFORM_SCOPE, ScopeRef
from app.core.errors import ProblemError
from app.core.ids import uuid7
from app.core.principal import Principal
from app.core.time import to_rfc3339, utcnow
from app.modules.assessments import datastore as adb
from app.modules.assessments.models import (
    AttemptEvent,
    AttemptOverride,
    AttemptResult,
    Test,
    TestAssignment,
    TestAttempt,
    TestSection,
    TestSectionRule,
)
from app.modules.assessments.schemas import (
    AssignmentCreate,
    AssignmentPatch,
    OverrideCreate,
    ReviewPolicy,
    SectionsPut,
    TestCreate,
    TestSettings,
)
from app.modules.placement import bank, grading
from app.modules.placement import public as placement_public
from app.modules.placement.policies import batch_org, has_permission, require

POOL_FACTOR = 3  # recommended pool size per random rule (system-architecture §7.2, policy)


def _iso(dt: Any) -> str | None:
    return to_rfc3339(dt) if dt else None


def default_review_policy(kind: str) -> dict[str, Any]:
    if kind in ("practice_set", "course_quiz", "diagnostic"):
        full = {
            "score": True,
            "correctness": True,
            "answer_key": True,
            "explanation": True,
            "section_analytics": True,
            "rank": False,
        }
        return ReviewPolicy(after_submit=full, after_close=full).model_dump(mode="json")
    if kind == "drive":
        return ReviewPolicy(
            after_submit={},
            after_close={"score": True, "section_analytics": True},
        ).model_dump(mode="json")
    return ReviewPolicy().model_dump(mode="json")


def test_out(t: Test) -> dict[str, Any]:
    return {
        "id": str(t.id),
        "organization_id": str(t.organization_id) if t.organization_id else None,
        "batch_id": str(t.batch_id) if t.batch_id else None,
        "test_kind": t.test_kind,
        "title": t.title,
        "slug": t.slug,
        "company_id": str(t.company_id) if t.company_id else None,
        "company_path_id": str(t.company_path_id) if t.company_path_id else None,
        "status": t.status,
        "version": t.version,
        "duration_seconds": t.duration_seconds,
        "grace_seconds": t.grace_seconds,
        "navigation_mode": t.navigation_mode,
        "attempts_allowed": t.attempts_allowed,
        "grading_method": t.grading_method,
        "shuffle_questions": t.shuffle_questions,
        "shuffle_options": t.shuffle_options,
        "review_policy": t.review_policy,
        "integrity_settings": t.integrity_settings,
        "pass_percentage": str(t.pass_percentage) if t.pass_percentage is not None else None,
        "is_free": t.is_free,
        "available_from": _iso(t.available_from),
        "available_until": _iso(t.available_until),
        "settings_locked_at": _iso(t.settings_locked_at),
        "published_at": _iso(t.published_at),
    }


async def get_test(session: AsyncSession, test_id: uuid.UUID) -> Test:
    t = await adb.get(session, Test, test_id)
    if t is None:
        raise ProblemError("not_found")
    return t


async def sections_of(
    session: AsyncSession, test_id: uuid.UUID
) -> list[tuple[TestSection, list[TestSectionRule]]]:
    secs = list(
        (
            await adb.execute(
                session,
                select(TestSection).where(TestSection.test_id == test_id).order_by(TestSection.position),
            )
        ).scalars()
    )
    out = []
    for s in secs:
        rules = list(
            (
                await adb.execute(
                    session,
                    select(TestSectionRule)
                    .where(TestSectionRule.test_section_id == s.id)
                    .order_by(TestSectionRule.position),
                )
            ).scalars()
        )
        out.append((s, rules))
    return out


def sections_out(
    secs: list[tuple[TestSection, list[TestSectionRule]]], *, with_rules: bool
) -> list[dict[str, Any]]:
    out = []
    for s, rules in secs:
        d: dict[str, Any] = {
            "section_id": str(s.id),
            "title": s.title,
            "position": s.position,
            "duration_seconds": s.duration_seconds,
            "instructions_md": s.instructions_md,
            "question_count": sum(r.draw_count for r in rules),
        }
        if with_rules:
            d["rules"] = [
                {
                    "rule_id": str(r.id),
                    "position": r.position,
                    "rule_type": r.rule_type,
                    "question_id": str(r.question_id) if r.question_id else None,
                    "question_version_id": str(r.question_version_id) if r.question_version_id else None,
                    "topic_id": str(r.topic_id) if r.topic_id else None,
                    "company_id": str(r.company_id) if r.company_id else None,
                    "question_types": r.question_types,
                    "difficulty_min": r.difficulty_min,
                    "difficulty_max": r.difficulty_max,
                    "draw_count": r.draw_count,
                    "marks_each": str(r.marks_each) if r.marks_each is not None else None,
                    "negative_marks_each": str(r.negative_marks_each)
                    if r.negative_marks_each is not None
                    else None,
                }
                for r in rules
            ]
        out.append(d)
    return out


async def _check_refs(session: AsyncSession, company_id: uuid.UUID | None, path_id: uuid.UUID | None) -> None:
    if company_id is not None and await placement_public.get_company(session, company_id) is None:
        raise ProblemError(
            "validation_failed",
            errors=[{"field": "company_id", "code": "not_found", "message": "unknown company"}],
        )
    if path_id is not None and await placement_public.get_company_path(session, path_id) is None:
        raise ProblemError(
            "validation_failed",
            errors=[{"field": "company_path_id", "code": "not_found", "message": "unknown company path"}],
        )


def _window_ok(frm: Any, until: Any) -> None:
    if frm is not None and until is not None and until <= frm:
        raise ProblemError(
            "validation_failed",
            errors=[
                {"field": "available_until", "code": "invalid", "message": "must be after available_from"}
            ],
        )


async def create_test(
    session: AsyncSession, principal: Principal, body: TestCreate, org_id: uuid.UUID | None
) -> Test:
    await _check_refs(session, body.company_id, body.company_path_id)
    _window_ok(body.available_from, body.available_until)
    t = Test(
        id=uuid7(),
        organization_id=org_id,
        test_kind=body.test_kind,
        title=body.title,
        slug=body.slug,
        company_id=body.company_id,
        company_path_id=body.company_path_id,
        status="draft",
        version=1,
        duration_seconds=body.duration_seconds,
        grace_seconds=body.grace_seconds
        if body.grace_seconds is not None
        else (0 if body.test_kind == "drive" else 30),
        navigation_mode=body.navigation_mode or "free",
        attempts_allowed=body.attempts_allowed,
        grading_method=body.grading_method or "highest",
        shuffle_questions=True if body.shuffle_questions is None else body.shuffle_questions,
        shuffle_options=True if body.shuffle_options is None else body.shuffle_options,
        review_policy=body.review_policy.model_dump(mode="json")
        if body.review_policy
        else default_review_policy(body.test_kind),
        integrity_settings=body.integrity_settings.model_dump(mode="json", exclude_none=True)
        if body.integrity_settings
        else {"fullscreen": False, "log_focus": True, "log_paste": True},
        pass_percentage=body.pass_percentage,
        is_free=bool(body.is_free),
        available_from=body.available_from,
        available_until=body.available_until,
        created_by=principal.user_id,
        batch_id=body.batch_id,
    )
    adb.add(session, t)
    await adb.flush(session)
    return t


def _ensure_unlocked(t: Test) -> None:
    if t.settings_locked_at is not None:
        raise ProblemError("test_settings_locked", locked_at=to_rfc3339(t.settings_locked_at))


async def patch_test(session: AsyncSession, t: Test, body: TestSettings) -> Test:
    _ensure_unlocked(t)
    fields = body.model_fields_set
    await _check_refs(session, body.company_id, body.company_path_id)
    for name in fields:
        value = getattr(body, name)
        if name == "review_policy":
            if value is None:
                continue
            value = value.model_dump(mode="json")
        if name == "integrity_settings" and value is not None:
            value = value.model_dump(mode="json", exclude_none=True)
        if (
            name
            in (
                "title",
                "navigation_mode",
                "grading_method",
                "grace_seconds",
                "shuffle_questions",
                "shuffle_options",
                "integrity_settings",
                "is_free",
            )
            and value is None
        ):
            continue
        setattr(t, name, value)
    _window_ok(t.available_from, t.available_until)
    await adb.flush(session)
    return t


async def put_sections(session: AsyncSession, t: Test, body: SectionsPut) -> None:
    _ensure_unlocked(t)
    for i, sec in enumerate(body.sections):
        for j, r in enumerate(sec.rules):
            f = f"sections.{i}.rules.{j}"
            if r.rule_type == "fixed" and r.coding_problem_id is not None:
                qid = await coding_question_for_problem(session, r.coding_problem_id)
                if qid is None:
                    raise ProblemError(
                        "validation_failed",
                        errors=[
                            {
                                "field": f"{f}.coding_problem_id",
                                "code": "not_found",
                                "message": "no active, published coding question uses this coding problem",
                            }
                        ],
                    )
                r.question_id = qid
            if r.rule_type == "fixed":
                q = await placement_public.get_question(session, r.question_id) if r.question_id else None
                if q is None or q.deleted_at is not None:
                    raise ProblemError(
                        "validation_failed",
                        errors=[
                            {"field": f"{f}.question_id", "code": "not_found", "message": "unknown question"}
                        ],
                    )
                if r.question_version_id is not None:
                    qv = await placement_public.get_version(session, r.question_version_id)
                    if qv is None or qv.question_id != q.id:
                        raise ProblemError(
                            "validation_failed",
                            errors=[
                                {
                                    "field": f"{f}.question_version_id",
                                    "code": "invalid",
                                    "message": "version does not belong to the question",
                                }
                            ],
                        )
            else:
                assert r.topic_id is not None
                await bank.get_topic(session, r.topic_id)
    for s, _rules in await sections_of(session, t.id):
        await adb.delete(session, s)
    await adb.flush(session)
    for i, sec in enumerate(body.sections):
        s = TestSection(
            id=uuid7(),
            test_id=t.id,
            organization_id=t.organization_id,
            title=sec.title,
            position=i + 1,
            duration_seconds=sec.duration_seconds,
            instructions_md=sec.instructions_md,
        )
        adb.add(session, s)
        await adb.flush(session)
        for j, r in enumerate(sec.rules):
            adb.add(
                session,
                TestSectionRule(
                    id=uuid7(),
                    test_section_id=s.id,
                    organization_id=t.organization_id,
                    position=j + 1,
                    rule_type=r.rule_type,
                    question_id=r.question_id,
                    question_version_id=r.question_version_id,
                    topic_id=r.topic_id,
                    company_id=r.company_id,
                    question_types=r.question_types,
                    difficulty_min=r.difficulty_min,
                    difficulty_max=r.difficulty_max,
                    draw_count=r.draw_count,
                    marks_each=r.marks_each,
                    negative_marks_each=r.negative_marks_each,
                ),
            )
    await adb.flush(session)


async def fixed_version(session: AsyncSession, rule: TestSectionRule) -> uuid.UUID | None:
    """The published version a fixed rule delivers (pinned or current), or None."""
    if rule.question_version_id is not None:
        qv = await placement_public.get_version(session, rule.question_version_id)
        return qv.id if qv is not None and qv.status in ("published", "retired") and qv.published_at else None
    q = await placement_public.get_question(session, rule.question_id) if rule.question_id else None
    if q is None or q.status != "active" or q.current_version_id is None:
        return None
    return q.current_version_id


async def coding_question_for_problem(session: AsyncSession, problem_id: uuid.UUID) -> uuid.UUID | None:
    """The active bank ``coding`` question whose current published version wraps ``problem_id``
    (newest first when several do), visible to the caller (RLS), else None."""
    return await placement_public.coding_question_for_problem(session, problem_id)


async def _coding_pool(session: AsyncSession, rule: TestSectionRule) -> list[uuid.UUID]:
    """Published coding question versions of the rule's topic subtree (same filters as the
    objective ``bank.published_pool``: difficulty, company tag)."""
    assert rule.topic_id is not None
    return await placement_public.coding_pool(
        session, rule.topic_id, rule.difficulty_min, rule.difficulty_max, rule.company_id
    )


async def rule_pool(session: AsyncSession, rule: TestSectionRule) -> list[uuid.UUID]:
    if rule.rule_type == "fixed":
        v = await fixed_version(session, rule)
        return [v] if v else []
    assert rule.topic_id is not None
    types = rule.question_types
    if not types or grading.CODING_TYPE not in types:
        return await bank.published_pool(
            session,
            topic_id=rule.topic_id,
            difficulty_min=rule.difficulty_min,
            difficulty_max=rule.difficulty_max,
            question_types=types,
            company_id=rule.company_id,
        )
    # Coding sections (webstaff request 10): coding questions, plus any objective types listed.
    pool = await _coding_pool(session, rule)
    objective = [x for x in types if x != grading.CODING_TYPE]
    if objective:
        pool += await bank.published_pool(
            session,
            topic_id=rule.topic_id,
            difficulty_min=rule.difficulty_min,
            difficulty_max=rule.difficulty_max,
            question_types=objective,
            company_id=rule.company_id,
        )
    return sorted(set(pool))


async def validate(session: AsyncSession, t: Test) -> dict[str, Any]:
    """Feasibility of every draw rule *together* (BE-03), mirroring ``attempts.build_layout``:
    fixed questions are reserved first across the whole test (a duplicate fixed question is
    infeasible); each random rule, in delivery order, must still have ``draw_count`` questions
    after removing the fixed ones and the worst case of what earlier random rules may have drawn
    from the overlap of their pools (so every start succeeds, whatever the seed)."""
    secs = await sections_of(session, t.id)
    pools: dict[uuid.UUID, list[uuid.UUID]] = {}
    fixed_seen: set[uuid.UUID] = set()
    fixed_dupes: set[uuid.UUID] = set()
    for _s, rules in secs:
        for r in rules:
            pools[r.id] = await rule_pool(session, r)
            if r.rule_type == "fixed":
                for v in pools[r.id]:
                    (fixed_dupes if v in fixed_seen else fixed_seen).add(v)
    report = []
    ok = bool(secs)
    earlier_random: list[tuple[set[uuid.UUID], int]] = []
    for s, rules in secs:
        for r in rules:
            pool = pools[r.id]
            if r.rule_type == "fixed":
                available = len(pool)
                item_ok = available >= r.draw_count and not (set(pool) & fixed_dupes)
                reason = None if item_ok else ("duplicate_fixed_question" if pool else "pool_too_small")
            else:
                own = set(pool) - fixed_seen
                lost = sum(min(n, len(other & own)) for other, n in earlier_random)
                available = len(own) - lost
                item_ok = available >= r.draw_count
                reason = None
                if not item_ok:
                    reason = "pool_too_small" if len(pool) < r.draw_count else "overlaps_other_rules"
                earlier_random.append((own, r.draw_count))
            ok = ok and item_ok
            report.append(
                {
                    "section_id": str(s.id),
                    "rule_id": str(r.id),
                    "rule_type": r.rule_type,
                    "pool_size": len(pool),
                    "available": max(available, 0),
                    "required": r.draw_count,
                    "ok": item_ok,
                    "reason": reason,
                    "recommended_ok": r.rule_type == "fixed" or len(pool) >= POOL_FACTOR * r.draw_count,
                }
            )
    return {"test_id": str(t.id), "feasible": ok, "has_sections": bool(secs), "rules": report}


async def publish(session: AsyncSession, t: Test) -> Test:
    report = await validate(session, t)
    if not report["feasible"]:
        raise ProblemError(
            "invalid_state_transition",
            detail="Not enough published questions for every draw rule (run validate for details).",
            validation=report,
        )
    if t.status == "archived":
        raise ProblemError("invalid_state_transition", detail="Archived tests cannot be published.")
    if t.published_at is not None:
        t.version += 1
    t.status = "published"
    t.published_at = utcnow()
    await adb.flush(session)
    return t


async def archive(session: AsyncSession, t: Test) -> int:
    """Retire a test (QA 2026-11, F11): it can no longer be published, assigned or started, its
    open assignment windows end now (a window not yet opened never opens), and learners' lists
    drop it (``/me/tests`` lists published tests, plus tests the learner already attempted, which
    keep their attempts and results). Returns how many assignment windows were closed."""
    if t.status == "archived":
        raise ProblemError("invalid_state_transition", detail="This test is already archived.")
    now = utcnow()
    open_windows = (
        await adb.execute(
            session,
            select(TestAssignment).where(
                TestAssignment.test_id == t.id, TestAssignment.available_until > now
            ),
        )
    ).scalars()
    closed = 0
    for a in open_windows:
        if a.available_from >= now:
            a.available_from = now - timedelta(seconds=1)
        a.available_until = now
        closed += 1
    t.status = "archived"
    await adb.flush(session)
    return closed


# --------------------------------------------------------------------------- permissions


async def can_test(
    request: Request, session: AsyncSession, principal: Principal, permission: str, t: Test
) -> bool:
    """``permission`` on test ``t``. Platform/organization-scoped holders: every test they own.
    Batch-scoped trainers (matrix ``test.edit`` trainer = B/C): only tests they created
    themselves, never another batch trainer's test in the same org (ADM-49, SoD-08). A test with
    an owning batch (``tests.batch_id``, set when created with ``batch_id``) is checked against
    that batch's scope: every trainer of the owning batch, no trainer of another batch."""
    from app.modules.placement.policies import can_in_org

    if t.organization_id is None:
        return await has_permission(request, principal, permission, PLATFORM_SCOPE)
    if await has_permission(request, principal, permission, ScopeRef("organization", t.organization_id)):
        return True
    if t.batch_id is not None:
        return await has_permission(request, principal, permission, ScopeRef("batch", t.batch_id))
    if t.created_by != principal.user_id:
        return False
    return await can_in_org(request, session, principal, permission, t.organization_id)


async def can_read_test(request: Request, session: AsyncSession, principal: Principal, t: Test) -> bool:
    """Read-only studio view (sections, rules) for the grading screens: authors (``test.edit``)
    and holders of ``test.results.read`` (evaluators) on the test's owning batch / org /
    platform scope or on a batch the test is assigned to. Never grants any write."""
    if await can_test(request, session, principal, "test.edit", t):
        return True
    if await attempt_scope_allows(
        request, principal, "test.results.read", batch_id=t.batch_id, org_id=t.organization_id
    ):
        return True
    batches = (
        await adb.execute(
            session,
            select(TestAssignment.batch_id).where(
                TestAssignment.test_id == t.id, TestAssignment.batch_id.is_not(None)
            ),
        )
    ).scalars()
    for b in set(batches):
        if b is not None and await has_permission(
            request, principal, "test.results.read", ScopeRef("batch", b)
        ):
            return True
    return False


async def reads_results_anywhere(request: Request, principal: Principal) -> bool:
    """Holds ``test.results.read`` at platform scope or through any batch grant (evaluators)."""
    if await has_permission(request, principal, "test.results.read", PLATFORM_SCOPE):
        return True
    for g in principal.grants:
        if g.scope_type == "batch" and g.scope_id is not None:
            if await has_permission(request, principal, "test.results.read", ScopeRef("batch", g.scope_id)):
                return True
    return False


async def require_test_perm(
    request: Request, session: AsyncSession, principal: Principal, permission: str, t: Test
) -> None:
    if not await can_test(request, session, principal, permission, t):
        raise ProblemError("permission_denied", permission=permission)


async def attempt_scope_allows(
    request: Request,
    principal: Principal,
    permission: str,
    *,
    batch_id: uuid.UUID | None,
    org_id: uuid.UUID | None,
) -> bool:
    if (
        permission == "test.results.read"
        and principal.has_role("content_manager")
        and not principal.has_role("super_admin")
    ):
        # ADM-44 / ASM-22 (QA 2026-11-11, D1): a content manager's test.results.read is "item statistics
        # only" and never opens one learner's attempt (result, review, evaluation). Any other role they
        # also hold still applies, exactly like the test-report listing above.
        rest = tuple(g for g in principal.grants if g.role != "content_manager")
        if not rest:
            return False
        principal = dataclasses.replace(
            principal, grants=rest, is_platform=any(g.scope_type == "platform" for g in rest)
        )
    if batch_id is not None and await has_permission(
        request, principal, permission, ScopeRef("batch", batch_id)
    ):
        return True
    if org_id is not None:
        return await has_permission(request, principal, permission, ScopeRef("organization", org_id))
    return await has_permission(request, principal, permission, PLATFORM_SCOPE)


# --------------------------------------------------------------------------- assignments


def assignment_out(a: TestAssignment) -> dict[str, Any]:
    return {
        "id": str(a.id),
        "test_id": str(a.test_id),
        "organization_id": str(a.organization_id) if a.organization_id else None,
        "batch_id": str(a.batch_id) if a.batch_id else None,
        "available_from": _iso(a.available_from),
        "available_until": _iso(a.available_until),
        "attempts_allowed": a.attempts_allowed,
        "release_mode": a.release_mode,
        "results_release_at": _iso(a.results_release_at),
    }


async def assignment_scope(
    session: AsyncSession, body_batch: uuid.UUID | None, body_org: uuid.UUID | None
) -> tuple[ScopeRef, uuid.UUID]:
    if body_batch is not None:
        org = await batch_org(session, body_batch)
        if org is None or (body_org is not None and body_org != org):
            raise ProblemError("not_found")
        return ScopeRef("batch", body_batch), org
    assert body_org is not None
    return ScopeRef("organization", body_org), body_org


async def create_assignment(
    request: Request, session: AsyncSession, principal: Principal, t: Test, body: AssignmentCreate
) -> TestAssignment:
    scope, org = await assignment_scope(session, body.batch_id, None)
    await require(request, principal, "test.assign", scope)
    if t.organization_id is not None and t.organization_id != org:
        # Another tenant's test can never be assigned here (no existence disclosure).
        raise ProblemError("not_found")
    if t.organization_id is not None and not await can_read_test(request, session, principal, t):
        # Single company: every company test shares the org, so the org check above no longer
        # separates batches. A trainer may assign only company tests they can see (their batch's
        # tests / their own); another batch's test stays undisclosed (404).
        raise ProblemError("not_found")
    if t.status != "published":
        raise ProblemError("invalid_state_transition", detail="Publish the test before assigning it.")
    a = TestAssignment(
        id=uuid7(),
        test_id=t.id,
        organization_id=org,
        batch_id=body.batch_id,
        available_from=body.available_from,
        available_until=body.available_until,
        attempts_allowed=body.attempts_allowed,
        release_mode=body.release_mode,
        results_release_at=body.results_release_at,
        assigned_by=principal.user_id,
    )
    adb.add(session, a)
    await adb.flush(session)
    await audit(
        session,
        principal,
        "test.assigned",
        "test_assignment",
        a.id,
        organization_id=org,
        after=assignment_out(a),
    )
    return a


async def get_assignment(session: AsyncSession, assignment_id: uuid.UUID) -> TestAssignment:
    a = await adb.get(session, TestAssignment, assignment_id)
    if a is None:
        raise ProblemError("not_found")
    return a


async def require_assignment_perm(
    request: Request, principal: Principal, permission: str, a: TestAssignment
) -> None:
    if not await attempt_scope_allows(
        request, principal, permission, batch_id=a.batch_id, org_id=a.organization_id
    ):
        raise ProblemError("permission_denied", permission=permission)


async def list_assignments(
    request: Request, session: AsyncSession, principal: Principal, t: Test
) -> list[dict[str, Any]]:
    rows = (
        await adb.execute(
            session,
            select(TestAssignment)
            .where(TestAssignment.test_id == t.id)
            .order_by(TestAssignment.available_from),
        )
    ).scalars()
    out = []
    for a in rows:
        # Assigners see their assignments; evaluators (``test.results.release`` without
        # ``test.assign``) see the ones they release results for (TRN-011 report page).
        for perm in ("test.assign", "test.results.release"):
            if await attempt_scope_allows(
                request, principal, perm, batch_id=a.batch_id, org_id=a.organization_id
            ):
                out.append(assignment_out(a))
                break
    return out


async def patch_assignment(
    session: AsyncSession, principal: Principal, a: TestAssignment, body: AssignmentPatch
) -> dict[str, Any]:
    before = assignment_out(a)
    for name in body.model_fields_set:
        value = getattr(body, name)
        if name in ("available_from", "available_until", "release_mode") and value is None:
            continue
        setattr(a, name, value)
    if a.available_until <= a.available_from:
        raise ProblemError(
            "validation_failed",
            errors=[
                {"field": "available_until", "code": "invalid", "message": "must be after available_from"}
            ],
        )
    if a.release_mode == "scheduled" and a.results_release_at is None:
        raise ProblemError(
            "validation_failed",
            errors=[
                {
                    "field": "results_release_at",
                    "code": "required",
                    "message": "required for scheduled release",
                }
            ],
        )
    await adb.flush(session)
    warnings = []
    if a.available_until < utcnow():
        warnings.append("window_in_past")
    await audit(
        session,
        principal,
        "test.assignment_changed",
        "test_assignment",
        a.id,
        organization_id=a.organization_id,
        before=before,
        after=assignment_out(a),
    )
    return {**assignment_out(a), "warnings": warnings}


# --------------------------------------------------------------------------- overrides


def override_out(o: AttemptOverride) -> dict[str, Any]:
    return {
        "id": str(o.id),
        "test_id": str(o.test_id),
        "test_assignment_id": str(o.test_assignment_id) if o.test_assignment_id else None,
        "user_id": str(o.user_id) if o.user_id else None,
        "batch_id": str(o.batch_id) if o.batch_id else None,
        "extra_time_seconds": o.extra_time_seconds,
        "extra_attempts": o.extra_attempts,
        "window_extension_seconds": o.window_extension_seconds,
        "reason": o.reason,
        "granted_by": str(o.granted_by),
        "created_at": _iso(o.created_at),
    }


async def _is_member(
    session: AsyncSession, user_id: uuid.UUID, *, batch_id: uuid.UUID | None, org_id: uuid.UUID | None
) -> bool:
    from app.modules.orgs import public as orgs_public

    if batch_id is not None:
        return await orgs_public.is_batch_member(session, batch_id, user_id)
    if org_id is not None:
        return bool(await orgs_public.org_memberships(session, user_ids=[user_id], organization_id=org_id))
    return True


async def create_override(
    request: Request, session: AsyncSession, principal: Principal, t: Test, body: OverrideCreate
) -> AttemptOverride:
    a: TestAssignment | None = None
    if body.test_assignment_id is not None:
        a = await get_assignment(session, body.test_assignment_id)
        if a.test_id != t.id:
            raise ProblemError("not_found")
    elif body.user_id is not None and body.batch_id is None:
        # ADM-42: a per-student override sent as just ``{user_id}`` by a batch-scoped trainer
        # resolves to the test's assignment for a batch the student belongs to and the granter
        # can grant overrides on (org/platform holders keep the test-level scope below).
        org_scope = ScopeRef("organization", t.organization_id) if t.organization_id else PLATFORM_SCOPE
        if not await has_permission(request, principal, "test.override.grant", org_scope):
            for cand in (
                await adb.execute(
                    session,
                    select(TestAssignment)
                    .where(TestAssignment.test_id == t.id, TestAssignment.batch_id.is_not(None))
                    .order_by(TestAssignment.available_until.desc()),
                )
            ).scalars():
                assert cand.batch_id is not None
                if await _is_member(
                    session, body.user_id, batch_id=cand.batch_id, org_id=None
                ) and await has_permission(
                    request, principal, "test.override.grant", ScopeRef("batch", cand.batch_id)
                ):
                    a = cand
                    break
    if body.batch_id is not None:
        org = await batch_org(session, body.batch_id)
        if org is None:
            raise ProblemError("not_found")
        scope: ScopeRef = ScopeRef("batch", body.batch_id)
        batch_scope: uuid.UUID | None = body.batch_id
    elif a is not None:
        org = a.organization_id
        batch_scope = a.batch_id
        scope = (
            ScopeRef("batch", a.batch_id)
            if a.batch_id
            else ScopeRef("organization", org)
            if org
            else PLATFORM_SCOPE
        )
    else:
        org = t.organization_id
        batch_scope = None
        scope = ScopeRef("organization", org) if org else PLATFORM_SCOPE
    await require(request, principal, "test.override.grant", scope)
    if t.organization_id is not None and org is not None and t.organization_id != org:
        raise ProblemError("not_found")
    if body.user_id is not None and not await _is_member(
        session, body.user_id, batch_id=batch_scope, org_id=org
    ):
        raise ProblemError("not_found")
    o = AttemptOverride(
        id=uuid7(),
        test_id=t.id,
        test_assignment_id=a.id if a else None,
        organization_id=org,
        user_id=body.user_id,
        batch_id=body.batch_id,
        extra_time_seconds=body.extra_time_seconds,
        extra_attempts=body.extra_attempts,
        window_extension_seconds=body.window_extension_seconds,
        reason=body.reason,
        granted_by=principal.user_id,
    )
    adb.add(session, o)
    await adb.flush(session)
    # Extra time also applies to attempts already in progress (power cut mid-test, FR-ASM-007).
    if body.extra_time_seconds:
        cond = TestAttempt.user_id == body.user_id if body.user_id else TestAttempt.batch_id == body.batch_id
        running = (
            await adb.execute(
                session,
                select(TestAttempt).where(
                    TestAttempt.test_id == t.id, TestAttempt.status == "in_progress", cond
                ),
            )
        ).scalars()
        now = utcnow()
        for att in running:
            if att.deadline_at is not None:
                att.deadline_at = att.deadline_at + timedelta(seconds=body.extra_time_seconds)
            att.extra_time_seconds += body.extra_time_seconds
            adb.add(
                session,
                AttemptEvent(
                    id=uuid7(),
                    occurred_at=now,
                    attempt_id=att.id,
                    user_id=att.user_id,
                    organization_id=att.organization_id,
                    event_type="override_applied",
                    payload={
                        "kind": "extra_time",
                        "override_id": str(o.id),
                        "seconds": body.extra_time_seconds,
                    },
                ),
            )
        await adb.flush(session)
    await audit(
        session,
        principal,
        "test.override_granted",
        "attempt_override",
        o.id,
        organization_id=org,
        subject_user_id=body.user_id,
        reason=body.reason,
        after=override_out(o),
    )
    return o


async def list_overrides(
    request: Request, session: AsyncSession, principal: Principal, t: Test
) -> list[dict[str, Any]]:
    rows = (
        await adb.execute(
            session,
            select(AttemptOverride)
            .where(AttemptOverride.test_id == t.id)
            .order_by(AttemptOverride.created_at),
        )
    ).scalars()
    out = []
    for o in rows:
        batch = o.batch_id
        if batch is None and o.test_assignment_id is not None:
            a = await adb.get(session, TestAssignment, o.test_assignment_id)
            batch = a.batch_id if a else None
        if await attempt_scope_allows(
            request, principal, "test.override.grant", batch_id=batch, org_id=o.organization_id
        ):
            out.append(override_out(o))
    return out


# --------------------------------------------------------------------------- results


async def list_attempts(
    request: Request, session: AsyncSession, principal: Principal, t: Test
) -> list[dict[str, Any]]:
    rows = (
        await adb.execute(
            session,
            select(TestAttempt, AttemptResult)
            .outerjoin(AttemptResult, AttemptResult.attempt_id == TestAttempt.id)
            .where(TestAttempt.test_id == t.id)
            .order_by(TestAttempt.started_at),
        )
    ).all()
    out = []
    cache: dict[tuple[Any, Any], bool] = {}
    reader = principal
    if principal.has_role("content_manager") and not principal.has_role("super_admin"):
        # ADM-44: content managers hold test.results.read as "item stats only" (ASM-22). Their
        # grant never exposes per-learner rows; any other role they also hold still applies.
        rest = tuple(g for g in principal.grants if g.role != "content_manager")
        reader = dataclasses.replace(
            principal, grants=rest, is_platform=any(g.scope_type == "platform" for g in rest)
        )
        if not rest:
            raise ProblemError(
                "permission_denied",
                permission="test.results.read",
                detail="Content managers see item statistics only (test report).",
            )
    for att, res in rows:
        key = (att.batch_id, att.organization_id)
        if key not in cache:
            cache[key] = await attempt_scope_allows(
                request, reader, "test.results.read", batch_id=att.batch_id, org_id=att.organization_id
            )
        if not cache[key]:
            continue
        out.append(
            {
                "attempt_id": str(att.id),
                "user_id": str(att.user_id),
                "attempt_no": att.attempt_no,
                "status": att.status,
                "submit_reason": att.submit_reason,
                "started_at": _iso(att.started_at),
                "submitted_at": _iso(att.submitted_at),
                "rebind_count": att.rebind_count,
                "integrity_status": att.integrity_status,
                "score": str(res.score) if res else None,
                "max_score": str(res.max_score) if res else None,
                "percentage": str(res.percentage) if res else None,
            }
        )
    return out


async def release_results(
    request: Request, session: AsyncSession, principal: Principal, t: Test, assignment_id: uuid.UUID
) -> dict[str, Any]:
    a = await get_assignment(session, assignment_id)
    if a.test_id != t.id:
        raise ProblemError("not_found")
    await require_assignment_perm(request, principal, "test.results.release", a)
    now = utcnow()
    a.results_release_at = now
    if a.release_mode != "manual":
        a.release_mode = "manual"
    ids = select(TestAttempt.id).where(TestAttempt.test_assignment_id == a.id)
    res = await adb.execute(
        session,
        update(AttemptResult)
        .where(AttemptResult.attempt_id.in_(ids), or_(AttemptResult.released_at.is_(None)))
        .values(released_at=now)
        .execution_options(synchronize_session=False),
    )
    await adb.flush(session)
    await audit(
        session,
        principal,
        "test.results_released",
        "test_assignment",
        a.id,
        organization_id=a.organization_id,
    )
    return {"test_assignment_id": str(a.id), "released_at": to_rfc3339(now), "results_released": res.rowcount}  # type: ignore[attr-defined,unused-ignore]
