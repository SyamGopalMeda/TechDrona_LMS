"""Parity: background jobs on the Firebase stack (no Postgres session factory at all).

Each job used to open ``get_sessionmaker()`` unconditionally and so raised
``PostgresDisabledError`` on Firebase; on the VM it runs in a Postgres system transaction. Here
every job must complete (VM: returns a count / dict and commits)."""

from __future__ import annotations

from tests.parity.harness import World, grant, publish_paid_course


async def test_jobs_run_without_postgres(web: World) -> None:
    from app.modules.admin import tasks as admin_tasks
    from app.modules.assessments import tasks as assessment_tasks
    from app.modules.learning import tasks as learning_tasks
    from app.modules.media import tasks as media_tasks
    from app.modules.notifications import tasks as notification_tasks
    from app.modules.placement import tasks as placement_tasks
    from app.modules.support import tasks as support_tasks

    w = web
    course = await publish_paid_course(w)
    student, sh = await w.learner("jobs")
    await grant(w, student.user_id, {"course_id": course.id})
    await w.call(
        "POST",
        "/support/tickets",
        sh,
        expect=201,
        json={"category": "technical", "subject": "Video", "body": "The video does not load."},
    )

    assert await support_tasks.auto_close() >= 0
    assert await media_tasks.scan_sweep() >= 0
    assert await notification_tasks.renewal_reminders() >= 0
    assert isinstance(await learning_tasks._send(), dict)
    assert isinstance(await learning_tasks._batch_end(), dict)
    assert await learning_tasks._backfill(10) >= 0
    assert await admin_tasks.break_glass_expiry() >= 0
    assert await placement_tasks.media_scan_sweep() >= 0
    assert await assessment_tasks.run_once() >= 0

    from app.modules.analytics import tasks as analytics_tasks
    from app.modules.commerce import tasks as commerce_tasks
    from app.modules.security import tasks as security_tasks

    for fn in (
        commerce_tasks.webhook_retry,
        commerce_tasks.refund_submit_retry,
        commerce_tasks.order_expiry,
        commerce_tasks.entitlement_expiry,
        commerce_tasks.reconciliation,
        analytics_tasks.run_exports_sweep,
    ):
        assert isinstance(await fn(), dict), fn
    for name in security_tasks.JOBS:
        assert isinstance(await security_tasks.run_job(name), dict), name
    await w.relay()
