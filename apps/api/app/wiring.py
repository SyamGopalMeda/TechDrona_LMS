"""Cross-module wiring (Stage 10 integration; backlog A-1..A-9).

Modules expose extension points (``register_*``) instead of importing each other's internals.
This module is the single place that plugs them together; ``app.main.create_app`` and
``app.worker.create_celery`` call ``wire_all()`` after module discovery, so the API process and
the Celery workers run with the same hooks. ``wire_all`` is idempotent and cheap: it re-asserts
every registration (tests that swap a hook and reset it to ``None`` get the defaults back on the
next ``create_app``).

Hooks (provider -> consumer):

* ``entitlements.register_resource_parent_resolver`` — catalog (lesson, resource -> course),
  coding (problem -> topic practice set / course), catalog (test -> course).
* ``entitlements.register_usage_provider`` — learning + assessments -> commerce refund rule.
* ``learning.register_video_coverage_lookup`` — analytics ``video_watch_coverage`` -> lesson
  completion evidence.
* ``learning.register_final_test_lookup`` — assessments best graded attempt -> certificates.
* ``coding.register_attempt_validator`` — assessments -> COD-07 with ``attempt_id``.
* ``security.signals.register_engaged_bucket_feed`` — analytics engaged buckets -> SH-01/02.
* ``analytics.hooks.register_lesson_meta_lookup`` — catalog reading minutes / asset durations.
* outbox ``attempt.scored``, ``practice.answered``, ... -> analytics consumer (mastery).
* outbox ``media.stream_cap_hit`` -> security signal ``cap.stream``.
* outbox ``security.false_positive_credit`` -> ``extend_entitlements_for_restriction``.
* outbox ``submission.judged`` -> assessments late re-score of coding questions.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.outbox import OutboxMessage, register_handler

log = structlog.get_logger("app.wiring")

# --------------------------------------------------------------------------- access parents


async def lesson_parents(session: AsyncSession, lesson_id: uuid.UUID) -> list[tuple[str, uuid.UUID]]:
    """lesson (row id or ``lesson_key``) -> its course."""
    from app.modules.catalog import api as catalog_api

    ids = await catalog_api.course_ids_for_lessons(session, lesson_id=lesson_id, match_lesson_key=True)
    return [("course", c) for c in ids]


async def resource_parents(session: AsyncSession, resource_id: uuid.UUID) -> list[tuple[str, uuid.UUID]]:
    from app.modules.catalog import api as catalog_api

    res = (await catalog_api.get_resources(session, [resource_id])).get(resource_id)
    if res is None:
        return []
    out: list[tuple[str, uuid.UUID]] = []
    if res.course_id is not None:
        out.append(("course", res.course_id))
    if res.lesson_id is not None:
        out.append(("lesson", res.lesson_id))
    return out


async def coding_problem_parents(session: AsyncSession, problem_id: uuid.UUID) -> list[tuple[str, uuid.UUID]]:
    """problem -> topic practice set (its topic and that topic's root subject) and every course
    that embeds it as a lesson."""
    from app.modules.coding import public as coding
    from app.modules.placement import public as placement

    out: list[tuple[str, uuid.UUID]] = []
    primary = await coding.problem_primary_topic(session, problem_id)
    found = await placement.topic_with_root(session, primary) if primary is not None else None
    if found is not None:
        tid, rid = found
        out.append(("question_set", tid))
        if rid is not None and rid != tid:
            out.append(("question_set", rid))
    from app.modules.catalog import api as catalog_api

    out += [
        ("course", c) for c in await catalog_api.course_ids_for_lessons(session, coding_problem_id=problem_id)
    ]
    return out


async def test_parents(session: AsyncSession, test_id: uuid.UUID) -> list[tuple[str, uuid.UUID]]:
    """test -> courses that embed it (company paths were removed: feature-removal-plan §3.2)."""
    from app.modules.catalog import api as catalog_api

    courses = await catalog_api.course_ids_for_lessons(session, test_id=test_id)
    return [("course", c) for c in courses]


# --------------------------------------------------------------------------- usage provider


async def _product_items(
    session: AsyncSession, product_id: uuid.UUID
) -> tuple[set[uuid.UUID], set[uuid.UUID]]:
    from app.modules.commerce import public as commerce

    return await commerce.product_item_refs(session, product_id)


class LearningUsageProvider:
    """``entitlements.UsageProvider`` from learning progress, certificates and test attempts.

    * consumption % = mean ``enrolments.progress_pct`` over the product's courses (0 for courses
      not started); products without courses use the share of their tests attempted.
    * certificate issued = any certificate for one of the product's courses.
    * mocks started = test attempts on the product's tests."""

    name = "learning"

    async def consumption_pct(
        self, session: AsyncSession, user_id: uuid.UUID, product_id: uuid.UUID
    ) -> Decimal:
        courses, tests = await _product_items(session, product_id)
        if courses:
            from app.modules.learning import public as learning

            best = await learning.max_progress_by_course(session, user_id, courses)
            total = sum((Decimal(v) for v in best.values()), Decimal("0"))
            return (total / len(courses)).quantize(Decimal("0.01"))
        if tests:
            started = await self._attempted_tests(session, user_id, tests)
            return (Decimal(100) * started / len(tests)).quantize(Decimal("0.01"))
        return Decimal("0")

    async def certificate_issued(
        self, session: AsyncSession, user_id: uuid.UUID, product_id: uuid.UUID
    ) -> bool:
        courses, _ = await _product_items(session, product_id)
        if not courses:
            return False
        from app.modules.learning import public as learning

        return await learning.has_certificate_for_courses(session, user_id, courses)

    async def mocks_started(self, session: AsyncSession, user_id: uuid.UUID, product_id: uuid.UUID) -> int:
        _, tests = await _product_items(session, product_id)
        if not tests:
            return 0
        from app.modules.assessments import public as assessments

        return int(await assessments.count_attempts(session, user_id, tests))

    @staticmethod
    async def _attempted_tests(session: AsyncSession, user_id: uuid.UUID, tests: set[uuid.UUID]) -> int:
        from app.modules.assessments import public as assessments

        return int(await assessments.count_attempted_tests(session, user_id, tests))


# --------------------------------------------------------------------------- learning lookups


async def video_coverage_lookup(
    session: AsyncSession, user_id: uuid.UUID, lesson_key: uuid.UUID
) -> int | None:
    """Analytics coverage (server-verified heartbeats) for every version of the lesson.

    BE-01 (assess request): per asset the covered seconds are capped at the asset's duration
    (``lesson_assets.duration_seconds``, else the duration recorded with the coverage), so
    coverage summed across rows can never exceed the video length."""
    from app.modules.catalog import api as catalog_api

    # Was one statement joining ``lesson_assets`` / ``lessons``; the catalog side now comes from
    # catalog.api and the LEAST / COALESCE / max run here with SQL NULL semantics.
    lesson_ids = [lesson_key] + [
        le.id for le in await catalog_api.find_lessons(session, lesson_key=lesson_key)
    ]
    from app.modules.analytics import public as analytics

    groups = await analytics.coverage_groups(session, user_id, lesson_ids)
    if not groups:
        return None
    assets = await catalog_api.get_assets(session, {g[0] for g in groups if g[0] is not None})
    best: Any = None
    for asset_id, covered, max_dur in groups:
        asset = assets.get(asset_id) if asset_id is not None else None
        cap = next(
            (v for v in (asset.duration_seconds if asset else None, max_dur, covered) if v is not None), None
        )
        vals = [v for v in (covered, cap) if v is not None]  # LEAST ignores NULLs
        s = min(vals) if vals else None
        if s is not None and (best is None or s > best):
            best = s
    return int(best) if best is not None else None


async def final_test_lookup(
    session: AsyncSession, user_id: uuid.UUID, test_id: uuid.UUID
) -> tuple[uuid.UUID, float] | None:
    """Best graded attempt of the final test (certificate rule)."""
    from app.modules.assessments import public as assessments

    return await assessments.best_result(session, user_id, test_id)


# --------------------------------------------------------------------------- analytics adapters


class AnalyticsEngagedBucketFeed:
    """``security.signals.EngagedBucketFeed`` over ``analytics.feeds.get_engaged_buckets``."""

    async def get_engaged_buckets(
        self, session: AsyncSession, user_id: uuid.UUID, start: datetime, end: datetime
    ) -> Sequence[Any]:
        from app.modules.analytics.feeds import get_engaged_buckets
        from app.modules.security.signals import EngagedBucket

        rows = await get_engaged_buckets(session, user_id, start, end)
        return [
            EngagedBucket(r.device_id, r.auth_session_id, r.bucket_5min, r.activity_kind)
            for r in rows
            if r.device_id is not None and r.auth_session_id is not None
        ]


def _catalog_lesson_meta() -> Any:
    from app.modules.analytics.hooks import AssetMeta, LessonMeta, LessonMetaLookup

    class CatalogLessonMeta(LessonMetaLookup):
        async def lessons(self, session: AsyncSession, ids: set[uuid.UUID]) -> dict[uuid.UUID, LessonMeta]:
            if not ids:
                return {}
            from app.modules.catalog import api as catalog_api

            lessons = await catalog_api.get_lessons(session, ids)
            return {
                i: LessonMeta(float(le.est_reading_minutes) if le.est_reading_minutes is not None else None)
                for i, le in lessons.items()
            }

        async def assets(self, session: AsyncSession, ids: set[uuid.UUID]) -> dict[uuid.UUID, AssetMeta]:
            if not ids:
                return {}
            from app.modules.catalog import api as catalog_api

            assets = await catalog_api.get_assets(session, ids)
            return {
                i: AssetMeta(float(a.duration_seconds) if a.duration_seconds else None)
                for i, a in assets.items()
            }

    return CatalogLessonMeta()


# --------------------------------------------------------------------------- outbox handlers


def _uuid(v: Any) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(v)) if v else None
    except ValueError:
        return None


async def on_stream_cap_hit(session: AsyncSession, msg: OutboxMessage) -> None:
    """media ``stream_cap_hit`` -> security signal ``cap.stream`` (deterministic, RE §7.3)."""
    from app.modules.security.public import report_event
    from app.modules.security.repo_fs_engine import detector_scope

    uid = _uuid(msg.payload.get("user_id"))
    if uid is None:
        return
    # A failed detector rolls its Firestore writes back (savepoint equivalent; no-op on Postgres).
    async with detector_scope():
        await _report_cap(session, report_event, uid, msg)


async def _report_cap(session: AsyncSession, report_event: Any, uid: uuid.UUID, msg: OutboxMessage) -> None:
    await report_event(
        session,
        "cap.stream",
        user_id=uid,
        source="playback",
        evidence={
            "other_playback_session_id": msg.payload.get("other_playback_session_id"),
            "outbox_event_id": str(msg.id),
        },
    )


async def on_false_positive_credit(session: AsyncSession, msg: OutboxMessage) -> None:
    """security false-positive lift -> credit the restricted days to time-bound entitlements
    (BR-ENT-12 / FR-SEC-008). Idempotent per decision (``source_ref``)."""
    from app.modules.entitlements.public import event_exists, extend_entitlements_for_restriction

    p = msg.payload
    uid = _uuid(p.get("user_id"))
    days = int(p.get("restricted_days") or 0)
    if uid is None or days <= 0:
        return
    decision = _uuid(p.get("decision_id")) or msg.id
    if await event_exists(session, uid, "fp_extension", decision):
        return
    await extend_entitlements_for_restriction(
        session,
        uid,
        days,
        str(p.get("reason") or "security_false_positive_credit"),
        case_ref=p.get("case_ref"),
        source_ref=decision,
    )


# --------------------------------------------------------------------------- entry point


def _import_extension_modules() -> None:
    """Routers and tasks register their own hooks/handlers/beat entries at import time."""
    from app.core.models_registry import _optional_import, module_names

    for name in module_names():
        _optional_import(f"app.modules.{name}.router")
        _optional_import(f"app.modules.{name}.tasks")


def wire_all() -> None:
    _import_extension_modules()

    from app.modules.analytics import hooks as analytics_hooks
    from app.modules.analytics.consumer import register_outbox_handlers
    from app.modules.assessments.coding import on_submission_judged, validate_coding_attempt
    from app.modules.coding import service as coding
    from app.modules.entitlements import service as ent
    from app.modules.learning import service as learning
    from app.modules.security import signals

    ent.register_resource_parent_resolver("lesson", lesson_parents)
    ent.register_resource_parent_resolver("resource", resource_parents)
    ent.register_resource_parent_resolver("coding_problem", coding_problem_parents)
    ent.register_resource_parent_resolver("test", test_parents)
    ent.register_usage_provider(LearningUsageProvider())
    # Entitlement decision-cache invalidation on ``entitlement.*``: explicit, not only an import
    # side effect of ``entitlements.router`` (``register_handler`` ignores duplicates, so this is
    # idempotent). The COM-04 ``orgs.member_removed`` hook went with the B2B features
    # (single company, REMOVAL-PLAN §1.2).
    ent.register_outbox_handlers()

    learning.register_video_coverage_lookup(video_coverage_lookup)
    learning.register_final_test_lookup(final_test_lookup)
    coding.register_attempt_validator(validate_coding_attempt)
    # Structured assignments: coding items are practiced through the learner's open assignment.
    from app.modules.learning.structured import coding_access_grant

    coding.register_access_grant(coding_access_grant)
    signals.register_engaged_bucket_feed(AnalyticsEngagedBucketFeed())
    analytics_hooks.register_lesson_meta_lookup(_catalog_lesson_meta())

    register_outbox_handlers()
    register_handler("media.stream_cap_hit", on_stream_cap_hit)
    register_handler("security.false_positive_credit", on_false_positive_credit)
    register_handler("submission.judged", on_submission_judged)
    _register_paths_handlers()
    _register_erasure_providers()
    _register_notification_consumers()
    _register_unique_conflicts()


def _register_unique_conflicts() -> None:
    """DB-03 / BE-15 / BE-22: concurrent duplicates that only the DB catches answer 409 with the
    code the spec defines for that rule (unlisted constraints map to the generic ``conflict``)."""
    from app.core.errors import register_unique_conflict

    register_unique_conflict("ux_att_one_open", "active_attempt_exists")
    register_unique_conflict("test_attempts_test_id_user_id_attempt_no_key", "active_attempt_exists")
    register_unique_conflict(
        "enrolments_user_id_course_id_key", "conflict", "You are already enrolled in this course."
    )
    register_unique_conflict(
        "practice_responses_practice_session_id_question_version_id_key",
        "conflict",
        "This question was already answered in this practice session.",
    )


def _register_erasure_providers() -> None:
    """DB-01: identity and notifications erase/pseudonymise their personal data during a
    privacy erasure (``app.modules.admin.privacy.execute_erasure``)."""
    from app.modules.admin.privacy import register_erasure_provider
    from app.modules.identity.erasure import erase_user as identity_erase
    from app.modules.notifications.erasure import erase_user as notifications_erase

    register_erasure_provider("identity", identity_erase)
    register_erasure_provider("notifications", notifications_erase)


def _register_notification_consumers() -> None:
    """COM-17: invoice email, cancellation email and finance alert routing."""
    from app.modules.notifications.consumers import register_commerce_consumers

    register_commerce_consumers()


def _register_paths_handlers() -> None:
    """paths: assignment / assessment path steps complete only from learning
    (``learning.submission_graded``, ``learning.grades_released``) and assessments
    (``attempt.scored``) outbox events."""
    from app.modules.paths.service import register_outbox_handlers as register_paths

    register_paths()
