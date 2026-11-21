"""Learning background jobs (Celery) and outbox consumers - certificate automation.

* outbox ``learning.certificate_issued`` -> ``certificates.on_certificate_issued``: PDF render +
  store, then one queued email (``awaiting`` approval unless ``certificates.auto_send`` is on).
* outbox ``learning.enrolled`` -> ``documents.on_enrolled``: the admission letter (issued
  document ``offer_course``) + its queued email.
* ``learning.certificate_outbox_send`` (beat, 60 s) - sends ``pending`` certificate and
  document emails.
* ``learning.certificates_batch_end`` (beat, daily 01:30 IST = 20:00 UTC) - issues certificates
  for enrolments whose batch ended and whose course rule is met (idempotent).
* ``learning.certificate_pdf_backfill`` (on demand) - PDFs for certificates issued before the
  renderer existed. Run once after deploy::

      python -m app.modules.learning.tasks backfill
"""

from __future__ import annotations

import sys
import uuid
from typing import Any

import structlog
from celery import shared_task
from celery.schedules import crontab

from app.core.audit import AuditActor
from app.core.db import job_session
from app.core.jobs import register_periodic, run_async
from app.core.outbox import OutboxMessage, register_handler

log = structlog.get_logger("app.learning.tasks")

SEND_TASK = "learning.certificate_outbox_send"
BATCH_END_TASK = "learning.certificates_batch_end"
BACKFILL_TASK = "learning.certificate_pdf_backfill"


async def on_certificate_issued(session: Any, msg: OutboxMessage) -> None:
    from app.modules.learning import certificates as certs

    try:
        cid = uuid.UUID(str(msg.payload.get("certificate_id")))
    except ValueError:
        log.warning("certificate_issued_bad_payload", event_id=str(msg.id))
        return
    await certs.on_certificate_issued(session, cid, str(msg.payload.get("issue_source") or "rule"))


register_handler("learning.certificate_issued", on_certificate_issued)


async def on_enrolled(session: Any, msg: OutboxMessage) -> None:
    """``learning.enrolled`` -> admission letter (``offer_course``) issued once and its email
    queued (awaiting approval unless auto-send is on). Skips free self-enrolments, a switched-off
    ``auto_admission_letter`` setting and incomplete document settings."""
    from app.modules.learning import documents as docs

    try:
        eid = uuid.UUID(str(msg.payload.get("enrolment_id")))
    except ValueError:
        log.warning("enrolled_bad_payload", event_id=str(msg.id))
        return
    await docs.on_enrolled(session, eid, str(msg.payload.get("source") or ""))


register_handler("learning.enrolled", on_enrolled)


# Quiz, practice-set and coding lessons complete on submission, like assignment lessons
# (learning/router.py ``submit_assignment``): the owning module only announces the submission and
# learning marks every lesson that points at that test / problem as completed for the learner in
# each active enrolment containing it (``service.record_completion``; it then recomputes progress
# and issues the course certificate when the rule is met). Before 2026-11-21 nothing called
# ``record_completion`` for these lesson types, so a course with one could never complete.
_TEST_LESSON_EVIDENCE = {"quiz": "quiz_submitted", "practice_set": "practice_set_submitted"}


def _uuid(v: Any) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(v))
    except ValueError:
        return None


async def on_attempt_submitted(session: Any, msg: OutboxMessage) -> None:
    """``attempt.submitted`` (assessments, user or auto submit) -> quiz / practice-set lessons."""
    from app.modules.catalog import public as catalog_api
    from app.modules.learning import service as svc

    test_id, user_id = _uuid(msg.payload.get("test_id")), _uuid(msg.payload.get("user_id"))
    if test_id is None or user_id is None:
        log.warning("attempt_submitted_bad_payload", event_id=str(msg.id))
        return
    kinds: dict[uuid.UUID, str] = {}
    for le in await catalog_api.find_lessons(session, test_id=test_id):
        if le.lesson_type in _TEST_LESSON_EVIDENCE:
            kinds.setdefault(le.lesson_key, _TEST_LESSON_EVIDENCE[le.lesson_type])
    for key, kind in kinds.items():
        await svc.record_completion(
            session, user_id, key, {"kind": kind, "attempt_id": str(msg.payload.get("attempt_id") or "")}
        )


async def on_code_submitted(session: Any, msg: OutboxMessage) -> None:
    """``submission.created`` (coding, mode ``submit``) -> coding lessons. The judge may be
    switched off (JUDGE_PROVIDER=disabled), so completion does not wait for a verdict."""
    from app.modules.catalog import public as catalog_api
    from app.modules.learning import service as svc

    if msg.payload.get("mode") != "submit":
        return
    problem_id, user_id = _uuid(msg.payload.get("problem_id")), _uuid(msg.payload.get("user_id"))
    if problem_id is None or user_id is None:
        log.warning("code_submitted_bad_payload", event_id=str(msg.id))
        return
    keys = {
        le.lesson_key
        for le in await catalog_api.find_lessons(session, coding_problem_id=problem_id)
        if le.lesson_type == "coding"
    }
    for key in keys:
        await svc.record_completion(
            session,
            user_id,
            key,
            {"kind": "coding_submitted", "submission_id": str(msg.payload.get("submission_id") or "")},
        )


register_handler("attempt.submitted", on_attempt_submitted)
register_handler("submission.created", on_code_submitted)


async def _send() -> dict[str, int]:
    from app.modules.learning import certificates as certs

    async with job_session("learning.certificate_outbox_send") as session:
        return await certs.send_pending(session)


async def _batch_end() -> dict[str, Any]:
    from app.modules.learning import certificates as certs

    async with job_session("learning.certificates_batch_end") as session:
        out = await certs.issue_due(
            session,
            AuditActor.system("learning.certificates_batch_end"),
            batch_ended_only=True,
            origin="batch_end",
        )
    return {"issued": out["issued"], "skipped": len(out["skipped"])}


async def _backfill(limit: int = 200) -> int:
    from app.modules.learning import certificates as certs

    async with job_session("learning.certificate_pdf_backfill") as session:
        return await certs.backfill_pdfs(session, limit=limit)


@shared_task(name=SEND_TASK, ignore_result=True)
def certificate_outbox_send() -> dict[str, int]:
    r = run_async(_send())
    if any(r.values()):
        log.info("certificate_emails", **r)
    return r


@shared_task(name=BATCH_END_TASK, ignore_result=True)
def certificates_batch_end() -> dict[str, Any]:
    r = run_async(_batch_end())
    log.info("certificates_batch_end", **r)
    return r


@shared_task(name=BACKFILL_TASK, ignore_result=True)
def certificate_pdf_backfill(limit: int = 200) -> int:
    n = run_async(_backfill(limit))
    log.info("certificate_pdf_backfill", generated=n)
    return n


register_periodic(SEND_TASK, SEND_TASK, 60.0, options={"expires": 120})
register_periodic(BATCH_END_TASK, BATCH_END_TASK, crontab(hour=20, minute=0), options={"expires": 3600})


if __name__ == "__main__":  # python -m app.modules.learning.tasks backfill [limit]
    if len(sys.argv) >= 2 and sys.argv[1] == "backfill":
        from app.core.models_registry import import_all_models

        import_all_models()
        total = 0
        lim = int(sys.argv[2]) if len(sys.argv) > 2 else 200
        while True:
            n = run_async(_backfill(lim))
            total += n
            if n < lim:
                break
        print(f"generated {total} certificate PDF(s)")
    else:
        print("usage: python -m app.modules.learning.tasks backfill [limit]")
