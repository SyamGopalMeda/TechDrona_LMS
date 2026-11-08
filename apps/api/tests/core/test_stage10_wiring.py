"""Stage 10 wiring: hook registrations, Celery beat entries, public ``check_permission``,
policy-driven playback caps, the ``attempt_rebind`` OTP purpose and placement mastery read
from analytics."""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from sqlalchemy import text

from app.core import auth as core_auth
from app.core.auth import PLATFORM_SCOPE, ScopeRef, check_permission
from app.core.db import system_context
from app.core.errors import ProblemError
from app.core.ids import uuid7
from app.core.outbox import handlers_for
from app.core.principal import Principal


def _p() -> Principal:
    return Principal(user_id=uuid7(), session_id=uuid7())


def test_wire_all_registers_every_hook(app: Any) -> None:
    from app.modules.analytics import hooks as ah
    from app.modules.coding import service as coding
    from app.modules.entitlements import service as ent
    from app.modules.learning import service as learning
    from app.modules.security import signals
    from app.wiring import wire_all

    wire_all()  # idempotent
    assert {"lesson", "resource", "coding_problem", "test"} <= set(ent._parent_resolvers)
    assert ent.usage_provider().name == "learning"
    assert learning._coverage_lookup is not None and learning._final_test_lookup is not None
    assert coding._attempt_validator is not None
    assert signals.engaged_bucket_feed() is not None
    assert type(ah.lesson_meta_lookup()).__name__ == "CatalogLessonMeta"
    for et in (
        "attempt.scored",
        "practice.answered",
        "media.stream_cap_hit",
        "security.false_positive_credit",
    ):
        assert handlers_for(et), et
    # attempt.graded is NOT an emitted event (decision: keep attempt.scored)
    assert not handlers_for("attempt.graded")
    # analytics (mastery) + paths (assessment-step completion); each registered exactly once
    scored = [f"{h.__module__}.{h.__qualname__}" for h in handlers_for("attempt.scored")]
    assert len(scored) == len(set(scored)) == 2, scored
    assert any(".analytics." in n for n in scored) and any(".paths." in n for n in scored), scored


def test_celery_beat_has_every_module_job() -> None:
    from app.worker import celery_app

    beat = celery_app.conf.beat_schedule
    expected = {
        "core.outbox_relay",
        "assessments.deadline_sweeper",
        "analytics.interval_builder",
        "analytics.video_coverage",
        "analytics.daily_aggregator",
        "analytics.rollups",
        "analytics.security_feed",
        "analytics.retention_purge",
        "analytics.outbox_consumer",
        "security.decay_recompute",
        "security.restriction_expiry",
        "security.sla_breach_alerts",
        "commerce.webhook_retry",
        "commerce.reconciliation",
        "commerce.order_expiry",
        "entitlements.expiry",
    }
    assert expected <= set(beat)
    # COM-09/COM-15: every beat entry goes to a queue the compose/ECS ``worker`` consumes
    # (judging is swept by the worker-judge DB poller, not by beat).
    consumed = {"critical", "default", "notifications", "analytics", "reports", "maintenance"}
    queues = {e.get("options", {}).get("queue", "default") for e in beat.values()}
    assert queues <= consumed, queues - consumed
    assert beat["assessments.deadline_sweeper"]["options"]["queue"] == "critical"
    assert beat["commerce.webhook_retry"]["options"]["queue"] == "critical"
    assert beat["security.sla_breach_alerts"]["args"] == ("security.sla_breach_alerts",)
    tasks = set(celery_app.tasks)
    for name in {e["task"] for e in beat.values()} | {
        "commerce.process_webhook_event",
        "coding.judge_submission",
    }:
        assert name in tasks, name


async def test_public_check_permission() -> None:
    prev = core_auth._permission_checker

    class Checker:
        async def has_permission(
            self, principal: Any, permission: str, scope: ScopeRef, request: Any
        ) -> bool:
            if scope.scope_type == "organization":
                raise ProblemError("not_found")
            return permission == "course.edit"

    try:
        core_auth.register_permission_checker(None)
        assert await check_permission(_p(), "course.edit") is False  # fail closed
        core_auth.register_permission_checker(Checker())
        assert await check_permission(_p(), "course.edit", PLATFORM_SCOPE) is True
        assert await check_permission(_p(), "audit.read") is False
        org = ScopeRef("organization", uuid7())
        assert await check_permission(_p(), "course.edit", org) is False
        with pytest.raises(ProblemError):
            await check_permission(_p(), "course.edit", org, cross_tenant_raises=True)
        with pytest.raises(ValueError):
            await check_permission(_p(), "NOT A KEY")
    finally:
        core_auth.register_permission_checker(prev)


async def test_playback_caps_come_from_policy(db: Any) -> None:
    from app.modules.identity import policy as ip
    from app.modules.media import service as media

    await system_context(db, "test")
    pol = await media.playback_policy(db, uuid7())
    assert (pol.max_concurrent_streams, pol.otp_ttl_seconds, pol.stale_after_seconds) == (1, 300, 90)

    prev = ip._resolver
    values = {
        "playback.max_concurrent_streams": 2,
        "playback.otp_ttl_seconds": 99999,
        "playback.heartbeat_seconds": "x",
    }

    async def resolver(session: Any, key: str, org_id: Any, user_id: Any) -> Any:
        return values.get(key, 120)

    ip.register_policy_resolver(resolver)
    try:
        pol = await media.playback_policy(db, uuid7())
        assert pol.max_concurrent_streams == 2
        assert pol.otp_ttl_seconds == media.OTP_TTL_SECONDS  # out of bounds -> safe default
        assert pol.heartbeat_seconds == media.HEARTBEAT_SECONDS  # malformed -> safe default
        assert pol.stale_after_seconds == 120
    finally:
        ip.register_policy_resolver(prev)


async def test_attempt_rebind_otp_purpose_is_accepted(db: Any) -> None:
    from tests.identity.factory import make_user

    uid = (await make_user(db)).id
    await system_context(db, "test")
    await db.execute(
        text(
            "INSERT INTO verification_tokens (id, user_id, purpose, channel, destination_hmac, token_hash, "
            "expires_at) VALUES (:i, :u, 'attempt_rebind', 'sms', :h, :h, now() + interval '5 minutes')"
        ),
        {"i": uuid7(), "u": uid, "h": b"\x01" * 32},
    )
    with pytest.raises(Exception, match="check"):
        async with db.begin_nested():
            await db.execute(
                text(
                    "INSERT INTO verification_tokens (id, user_id, purpose, channel, destination_hmac, token_hash, "
                    "expires_at) VALUES (:i, :u, 'bogus', 'sms', :h, :h, now())"
                ),
                {"i": uuid7(), "u": uid, "h": b"\x02" * 32},
            )


async def test_placement_mastery_prefers_analytics(db: Any) -> None:
    from app.modules.placement import practice
    from tests.identity.factory import make_user
    from tests.placement.world import topic

    uid = (await make_user(db)).id
    t = await topic(db, "quant/ratios")
    await system_context(db, "test")
    out = await practice.mastery(db, Principal(user_id=uid, session_id=uuid.uuid4()))
    assert out["topics"] == []
    await db.execute(
        text(
            "INSERT INTO topic_mastery (user_id, topic_id, theta, band, weighted_accuracy, n_eff, attempts, "
            "model_version) VALUES (:u, :t, -1.2, 'weak', 0.3, 12, 12, 'tm-1.0')"
        ),
        {"u": uid, "t": t},
    )
    out = await practice.mastery(db, Principal(user_id=uid, session_id=uuid.uuid4()))
    (item,) = out["topics"]
    assert out["method"] == practice.ANALYTICS_METHOD
    assert (
        item["topic_id"] == str(t)
        and item["band"] == "beginner"
        and item["method"] == "analytics-topic-mastery"
    )
    assert item["answered"] == 12
