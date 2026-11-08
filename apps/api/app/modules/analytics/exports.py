"""Report exports (api-spec ANL-13..15, §1.7 dual control; database-schema §12 ``export_jobs``).

Flow: ``request_export`` (ANL-13) authorises ``report.export.request`` (+ ``analytics.read``)
at the requested scope, enforces step-up (S10 for PII, P5 for bulk or privileged requesters)
and 10 jobs/day per user, then either queues generation (``running``) or — for personal data
above ``BULK_PII_ROWS`` rows — creates an ``export.bulk_pii`` approval request
(``awaiting_approval``; approver a ``super_admin`` holding ``report.export.approve``, ≠
requester). Generation (Celery ``analytics.export_generate`` + the ``analytics.exports_sweep``
safety net) builds the CSV from the same report functions the screens use, so k-floor
suppression (``"<10"``) is identical; the file is watermarked with requester + time, written
to the private exports bucket, hashed (sha256) and expires after 24 h. Downloads (ANL-15) are
requester-only, ≤ 5 per job, through a presigned GET valid ≤ 2 minutes, audited
``export.download``.

Security report keys (H1-H12, ENG) keep their own pipeline (SEC-32/SEC-47,
``security_report_exports``); ``POST /exports`` answers ``422 use_security_export`` for them.
"""

from __future__ import annotations

import csv
import hashlib
import io
import sys
import uuid
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import AuditActor, audit
from app.core.auth import PLATFORM_SCOPE, ScopeRef, check_permission
from app.core.errors import ProblemError
from app.core.ids import uuid7
from app.core.principal import Principal
from app.core.time import ist_date, to_rfc3339
from app.modules.admin import approvals as apr
from app.modules.analytics import reports
from app.modules.analytics.export_store import get_export_store
from app.modules.analytics.models import ExportJob
from app.modules.identity import clock
from app.modules.rbac.models import ApprovalRequest
from app.modules.security.policies import P5, S10, require_fresh_step_up

log = structlog.get_logger("app.analytics.exports")

BULK_PII_ROWS = 10_000
DAILY_LIMIT = 10
MAX_DOWNLOADS = 5
FILE_TTL = timedelta(hours=24)
STALE_RUNNING = timedelta(seconds=30)
GENERATE_TASK = "analytics.export_generate"
APPROVAL_ACTION = "export.bulk_pii"
TARGET_TYPE = "export_job"


@dataclass(frozen=True)
class ReportDef:
    key: str
    title: str
    scope_type: str  # batch | course | platform
    contains_pii: bool


REPORTS: dict[str, ReportDef] = {
    r.key: r
    for r in (
        ReportDef("batch.progress", "Batch progress (per learner)", "batch", True),
        ReportDef("content.course_usage", "Course usage (aggregates)", "course", False),
        ReportDef("platform.overview", "Platform overview (aggregates)", "platform", False),
    )
}


def catalogue() -> list[dict[str, Any]]:
    return [
        {"report_key": r.key, "title": r.title, "scope_type": r.scope_type, "contains_pii": r.contains_pii}
        for r in REPORTS.values()
    ]


# --------------------------------------------------------------------------- output


def _effective_status(job: ExportJob) -> str:
    if job.status == "ready" and job.expires_at is not None and job.expires_at <= clock.now():
        return "expired"
    return job.status


def job_out(job: ExportJob) -> dict[str, Any]:
    r = REPORTS.get(job.report_key)
    return {
        "export_job_id": str(job.id),
        "report_key": job.report_key,
        "title": r.title if r else job.report_key,
        "scope": {"type": job.scope_type, "id": str(job.scope_id) if job.scope_id else None},
        "status": _effective_status(job),
        "format": job.format,
        "contains_pii": job.contains_pii,
        "row_count": job.row_count,
        "approval_request_id": str(job.approval_request_id) if job.approval_request_id else None,
        "reason": job.reason,
        "failure_code": job.failure_code,
        "file_sha256": job.file_sha256.hex() if job.file_sha256 else None,
        "downloads_remaining": max(0, MAX_DOWNLOADS - (job.download_count or 0)),
        "created_at": to_rfc3339(job.created_at) if job.created_at else None,
        "completed_at": to_rfc3339(job.completed_at) if job.completed_at else None,
        "expires_at": to_rfc3339(job.expires_at) if job.expires_at else None,
    }


# --------------------------------------------------------------------------- request (ANL-13)


def _invalid(field: str, code: str, message: str) -> ProblemError:
    return ProblemError("validation_failed", 422, errors=[{"field": field, "code": code, "message": message}])


def _validated_filters(raw: Any) -> dict[str, Any]:
    """BE-25: reports are trailing windows anchored on an as-of day, so the only supported
    filter is ``to`` (the as-of IST date, not in the future). Anything else (including
    ``from``) is rejected instead of being stored and silently ignored."""
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise _invalid("filters", "invalid", "filters must be an object.")
    unsupported = sorted(k for k in raw if k != "to")
    if unsupported:
        raise _invalid(
            f"filters.{unsupported[0]}",
            "unsupported_filter",
            "Only filters.to (the report's as-of date) is supported; reports cover trailing windows.",
        )
    if "to" not in raw:
        return {}
    try:
        to = date.fromisoformat(str(raw["to"]))
    except ValueError as e:
        raise _invalid("filters.to", "invalid_date", "filters.to must be a YYYY-MM-DD date.") from e
    if to > ist_date(clock.now()):
        raise _invalid("filters.to", "in_future", "filters.to cannot be in the future.")
    return {"to": to.isoformat()}


def _as_of(job: ExportJob) -> date:
    to = (job.filters or {}).get("to")
    return date.fromisoformat(to) if to else ist_date(clock.now())


async def _scope_org(session: AsyncSession, scope_type: str, scope_id: uuid.UUID | None) -> uuid.UUID | None:
    if scope_type == "batch" and scope_id is not None:
        org = await reports.batch_org(session, scope_id)
        if org is None:
            raise ProblemError("not_found")
        return org
    return None


async def _require_scope_perm(principal: Principal, key: str, scope: ScopeRef, request: Any) -> None:
    if not await check_permission(principal, key, scope, request, cross_tenant_raises=True):
        raise ProblemError("permission_denied", permission=key)


async def _estimate_rows(session: AsyncSession, r: ReportDef, scope_id: uuid.UUID | None) -> int:
    if r.key == "batch.progress" and scope_id is not None:
        return await reports.count_batch_students(session, scope_id)
    return 0


async def _check_daily_limit(session: AsyncSession, principal: Principal) -> None:
    since = clock.now() - timedelta(days=1)
    n = (
        await session.execute(
            select(func.count())
            .select_from(ExportJob)
            .where(ExportJob.requested_by == principal.user_id, ExportJob.created_at > since)
        )
    ).scalar_one()
    if n >= DAILY_LIMIT:
        raise ProblemError(
            "rate_limited", detail="You can request at most 10 exports a day.", retry_after_s=3600
        )


async def request_export(
    session: AsyncSession, principal: Principal, body: dict[str, Any], request: Any = None
) -> dict[str, Any]:
    key = str(body.get("report_key") or "")
    if key.startswith("security.") or key.upper() in {f"H{i}" for i in range(1, 13)} | {"ENG"}:
        raise _invalid(
            "report_key",
            "use_security_export",
            "Security reports are exported with POST /security/reports/{report_key}/exports (SEC-32).",
        )
    r = REPORTS.get(key)
    if r is None:
        raise _invalid("report_key", "unknown_report", "Unknown report key.")
    scope = body.get("scope") or {}
    scope_type = scope.get("type")
    raw_id = scope.get("id")
    if scope_type != r.scope_type:
        raise _invalid("scope.type", "scope_mismatch", f"{key} is exported at {r.scope_type} scope.")
    scope_id: uuid.UUID | None = None
    if r.scope_type != "platform":
        try:
            scope_id = uuid.UUID(str(raw_id))
        except (TypeError, ValueError) as e:
            raise _invalid("scope.id", "required", "A scope id is required.") from e
    org = await _scope_org(session, r.scope_type, scope_id)
    ref = PLATFORM_SCOPE if r.scope_type == "platform" else ScopeRef(r.scope_type, scope_id)  # type: ignore[arg-type]
    await _require_scope_perm(principal, "report.export.request", ref, request)
    await _require_scope_perm(principal, "analytics.read", ref, request)

    contains_pii = r.contains_pii
    estimate = await _estimate_rows(session, r, scope_id) if contains_pii else 0
    bulk = contains_pii and estimate > BULK_PII_ROWS
    if bulk or principal.tier == "privileged":
        require_fresh_step_up(principal, P5)
    elif contains_pii:
        require_fresh_step_up(principal, S10)
    await _check_daily_limit(session, principal)

    job = ExportJob(
        id=uuid7(),
        requested_by=principal.user_id,
        organization_id=org,
        report_key=key,
        scope_type=r.scope_type,
        scope_id=scope_id,
        filters=_validated_filters(body.get("filters")),
        format="csv",
        contains_pii=contains_pii,
        status="awaiting_approval" if bulk else "running",
        reason=body.get("reason"),
        reason_code=body.get("reason_code"),
        created_at=clock.now(),
    )
    session.add(job)
    await session.flush()
    approval_id: str | None = None
    if bulk:
        req = await apr.new_request(
            session,
            principal,
            action_type=APPROVAL_ACTION,
            target_type=TARGET_TYPE,
            target_id=job.id,
            payload={
                "export_job_id": str(job.id),
                "report_key": key,
                "scope_id": str(scope_id),
                "rows": estimate,
            },
            reason=job.reason or f"export {key}",
            required_approver_role="super_admin",
            organization_id=org,
        )
        job.approval_request_id = req.id
        approval_id = str(req.id)
        await session.flush()
    await audit(
        session,
        principal,
        "export.requested",
        TARGET_TYPE,
        job.id,
        organization_id=org,
        reason=job.reason,
        after={
            "report_key": key,
            "scope_type": r.scope_type,
            "scope_id": str(scope_id) if scope_id else None,
            "contains_pii": contains_pii,
            "status": job.status,
        },
    )
    if not bulk:
        dispatch(job.id)
    out: dict[str, Any] = {
        "export_job_id": str(job.id),
        "status": job.status,
        "contains_pii": contains_pii,
        "report_key": key,
    }
    if approval_id:
        out["approval_request_id"] = approval_id
        out["required_approver_role"] = "super_admin"
    return out


# --------------------------------------------------------------------------- read (ANL-14)


async def own_job(session: AsyncSession, principal: Principal, job_id: uuid.UUID) -> ExportJob:
    job = await session.get(ExportJob, job_id)
    if job is None or job.requested_by != principal.user_id:
        raise ProblemError("not_found")
    return job


async def list_jobs(
    session: AsyncSession,
    principal: Principal,
    *,
    scope_type: str | None = None,
    scope_id: uuid.UUID | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    q = select(ExportJob).where(ExportJob.requested_by == principal.user_id)
    if scope_type:
        q = q.where(ExportJob.scope_type == scope_type)
    if scope_id:
        q = q.where(ExportJob.scope_id == scope_id)
    rows = (await session.execute(q.order_by(ExportJob.created_at.desc()).limit(limit))).scalars().all()
    return [job_out(j) for j in rows]


# --------------------------------------------------------------------------- download (ANL-15)


async def download(
    session: AsyncSession, principal: Principal, job_id: uuid.UUID, request_id: str | None
) -> dict[str, Any]:
    job = (
        await session.execute(select(ExportJob).where(ExportJob.id == job_id).with_for_update())
    ).scalar_one_or_none()
    if job is None or job.requested_by != principal.user_id:
        raise ProblemError("not_found")
    status = _effective_status(job)
    if status != "ready" or not job.file_s3_key:
        raise ProblemError("invalid_state_transition", current_state=status, allowed=["ready"])
    if job.download_count >= MAX_DOWNLOADS:
        raise ProblemError(
            "rate_limited", detail="This export was already downloaded 5 times.", retry_after_s=0
        )
    now = clock.now()
    job.download_count += 1
    job.downloaded_at = now
    await session.flush()
    filename = f"{job.report_key.replace('.', '-')}-{ist_date(job.completed_at or now).isoformat()}.csv"
    url, url_expires = get_export_store().download_url(job.file_s3_key, filename)
    await audit(
        session,
        principal,
        "export.download",
        TARGET_TYPE,
        job.id,
        organization_id=job.organization_id,
        request_id=request_id,
        after={"report_key": job.report_key, "download": job.download_count},
    )
    return {
        "url": url,
        "expires_at": to_rfc3339(url_expires),
        "filename": filename,
        "sha256": job.file_sha256.hex() if job.file_sha256 else None,
        "downloads_remaining": MAX_DOWNLOADS - job.download_count,
    }


# --------------------------------------------------------------------------- approval (§1.7)


async def _job_for_approval(session: AsyncSession, req: ApprovalRequest) -> ExportJob:
    job = await session.get(ExportJob, uuid.UUID(str(req.payload["export_job_id"])))
    if job is None:
        raise ProblemError("not_found")
    return job


async def execute_approved(
    session: AsyncSession, principal: Principal, req: ApprovalRequest
) -> dict[str, Any]:
    """``export.bulk_pii`` executor for ``target_type='export_job'`` (registered through the
    security module's handler, which owns that action type for its own exports)."""
    job = await _job_for_approval(session, req)
    if job.status != "awaiting_approval":
        raise ProblemError(
            "invalid_state_transition", current_state=job.status, allowed=["awaiting_approval"]
        )
    job.status = "running"
    await session.flush()
    await audit(
        session,
        principal,
        "export.approved",
        TARGET_TYPE,
        job.id,
        organization_id=job.organization_id,
        after={"report_key": job.report_key, "approval_request_id": str(req.id)},
    )
    dispatch(job.id)
    return {"export_job_id": str(job.id), "status": job.status}


async def on_rejected(session: AsyncSession, principal: Principal, req: ApprovalRequest) -> None:
    job = await _job_for_approval(session, req)
    if job.status == "awaiting_approval":
        job.status = "rejected"
        await session.flush()
        await audit(
            session,
            principal,
            "export.rejected",
            TARGET_TYPE,
            job.id,
            organization_id=job.organization_id,
            reason=req.decision_note,
            after={"approval_status": req.status},
        )


async def decide(
    session: AsyncSession, principal: Principal, job_id: uuid.UUID, *, approve: bool, note: str | None
) -> dict[str, Any]:
    job = await session.get(ExportJob, job_id)
    if job is None or job.approval_request_id is None:
        raise ProblemError("not_found")
    out = await apr.decide(session, principal, job.approval_request_id, approve=approve, note=note)
    await session.refresh(job)
    if out.get("_expired"):
        job.status = "rejected"
        await session.flush()
        raise ProblemError("invalid_state_transition", current_state="expired", allowed=[])
    return {
        "export_job_id": str(job.id),
        "approval_request_id": out["approval_request_id"],
        "status": job.status,
    }


# --------------------------------------------------------------------------- generation


def _cell(v: Any) -> Any:
    if isinstance(v, list):
        return ";".join(str(x) for x in v)
    if isinstance(v, bool):
        return "true" if v else "false"
    return v


def _flatten(prefix: str, value: Any, out: list[dict[str, Any]], suppressed: bool = False) -> None:
    if isinstance(value, dict):
        sup = suppressed or value.get("suppressed") is True
        for k, v in value.items():
            if k == "suppressed":
                continue
            _flatten(f"{prefix}.{k}" if prefix else k, v, out, sup)
    elif isinstance(value, list) and value and all(isinstance(x, dict) for x in value):
        for i, item in enumerate(value):
            _flatten(f"{prefix}[{i}]", item, out, suppressed)
    else:
        if value is None:
            return
        if suppressed and isinstance(value, int | float) and not isinstance(value, bool):
            value = reports.SUPPRESSED  # k-floor: the screen hides these cells too
        out.append({"metric": prefix, "value": _cell(value)})


async def _build(session: AsyncSession, job: ExportJob) -> tuple[list[str], list[dict[str, Any]], list[str]]:
    today = _as_of(job)
    notes: list[str] = [f"as_of={today.isoformat()}"] if (job.filters or {}).get("to") else []
    if job.report_key == "batch.progress":
        assert job.scope_id is not None
        data = await reports.batch_report(session, job.scope_id, today=today)
        if data is None:
            raise ProblemError("not_found")
        dist = data["weekly_learning_time"]
        notes.append(
            f"week_start={data['week_start']} learners_total={data['learners_total']} "
            f"weekly_learning_time n={dist['n']} median_s={dist['median_s']} p90_s={dist['p90_s']}"
        )
        cols = ["user_id", "weekly_learning_s", "weak_topics", "needs_attention", "reasons"]
        return cols, [{c: _cell(row[c]) for c in cols} for row in data["learners"]], notes
    if job.report_key == "content.course_usage":
        assert job.scope_id is not None
        data = await reports.course_report(session, job.scope_id, today=today)
    elif job.report_key == "platform.overview":
        data = await reports.platform_report(session, today=today)
    else:
        raise ProblemError("not_found")
    flat: list[dict[str, Any]] = []
    _flatten("", {k: v for k, v in data.items() if not k.endswith("_id")}, flat)
    return ["metric", "value"], flat, notes


def render_csv(
    job: ExportJob, cols: list[str], rows: list[dict[str, Any]], notes: list[str], stamp: str
) -> tuple[str, bytes]:
    watermark = (
        f"Tech Drona export {job.report_key} | job {job.id} | requested by {job.requested_by} | "
        f"generated {stamp} | confidential: do not forward"
    )
    buf = io.StringIO()
    buf.write(f"# {watermark}\n")
    buf.write(
        f"# k-floor: cells covering fewer than {reports.K_MIN_COHORT} learners show {reports.SUPPRESSED}\n"
    )
    for n in notes:
        buf.write(f"# {n}\n")
    w = csv.DictWriter(buf, fieldnames=cols, extrasaction="ignore", lineterminator="\n")
    w.writeheader()
    for row in rows:
        w.writerow(row)
    return watermark, buf.getvalue().encode("utf-8")


async def generate(session: AsyncSession, job_id: uuid.UUID) -> str:
    """Build, store and finalise one ``running`` job. Returns the resulting status."""
    job = (
        await session.execute(
            select(ExportJob).where(ExportJob.id == job_id).with_for_update(skip_locked=True)
        )
    ).scalar_one_or_none()
    if job is None or job.status != "running":
        return job.status if job is not None else "missing"
    now = clock.now()
    stage = "report_error"
    try:
        async with session.begin_nested():
            cols, rows, notes = await _build(session, job)
        watermark, data = render_csv(job, cols, rows, notes, to_rfc3339(now))
        key = f"exports/{job.id}/{job.report_key.replace('.', '-')}.csv"
        stage = "storage_error"
        await get_export_store().put(key, data, "text/csv; charset=utf-8")
    except Exception as e:  # report or storage failure: the job fails, never half-ready
        log.warning("export.generation_failed", export_job_id=str(job.id), error=type(e).__name__)
        job.status = "failed"
        job.failure_code = stage
        await session.flush()
        await audit(
            session, AuditActor.system("analytics.export_generate"), "export.failed", TARGET_TYPE, job.id
        )
        return job.status
    job.file_s3_key = key
    digest = hashlib.sha256(data).digest()
    job.file_sha256 = digest
    job.watermark = watermark
    job.row_count = len(rows)
    job.completed_at = now
    job.expires_at = now + FILE_TTL
    job.status = "ready"
    await session.flush()
    await audit(
        session,
        AuditActor.system("analytics.export_generate"),
        "export.generated",
        TARGET_TYPE,
        job.id,
        organization_id=job.organization_id,
        after={"report_key": job.report_key, "row_count": job.row_count, "sha256": digest.hex()},
    )
    return job.status


async def sweep(session: AsyncSession, *, generate_limit: int = 20) -> dict[str, int]:
    """Expire ready files past ``expires_at`` (object deleted), close jobs whose approval
    lapsed, and generate ``running`` jobs nobody picked up (broker outage / no queue)."""
    now = clock.now()
    store = get_export_store()
    expired = 0
    for job in (
        (
            await session.execute(
                select(ExportJob).where(ExportJob.status == "ready", ExportJob.expires_at <= now).limit(500)
            )
        )
        .scalars()
        .all()
    ):
        if job.file_s3_key:
            try:
                await store.delete(job.file_s3_key)
            except Exception as e:  # retried on the next sweep? no: the bucket lifecycle rule also deletes
                log.warning("export.delete_failed", export_job_id=str(job.id), error=type(e).__name__)
        job.status = "expired"
        expired += 1
    lapsed = 0
    waiting = (
        await session.execute(
            select(ExportJob, ApprovalRequest)
            .join(ApprovalRequest, ApprovalRequest.id == ExportJob.approval_request_id)
            .where(ExportJob.status == "awaiting_approval")
        )
    ).all()
    for job, req in waiting:
        if req.status in ("rejected", "cancelled", "expired") or (
            req.status == "pending" and req.expires_at <= now
        ):
            if req.status == "pending":
                req.status = "expired"
            job.status = "rejected"
            lapsed += 1
    await session.flush()
    stale = (
        (
            await session.execute(
                select(ExportJob.id)
                .where(ExportJob.status == "running", ExportJob.updated_at <= now - STALE_RUNNING)
                .order_by(ExportJob.created_at)
                .limit(generate_limit)
            )
        )
        .scalars()
        .all()
    )
    generated = 0
    for jid in stale:
        await generate(session, jid)
        generated += 1
    return {"expired": expired, "approval_lapsed": lapsed, "generated": generated}


# --------------------------------------------------------------------------- dispatch


def dispatch(job_id: uuid.UUID) -> None:
    """Best-effort hand-off to the worker (``analytics.export_generate``, countdown 2 s so the
    request transaction has committed). Only when a Celery app is already loaded in this
    process (workers) or ``TD_EXPORTS_SEND_TASKS=1`` (API with a broker); otherwise the
    ``analytics.exports_sweep`` beat entry picks the job up within a minute."""
    import os

    mod = sys.modules.get("app.worker")
    if mod is None and os.environ.get("TD_EXPORTS_SEND_TASKS") == "1":
        try:
            import importlib

            mod = importlib.import_module("app.worker")
        except Exception:  # pragma: no cover
            mod = None
    app = getattr(mod, "celery_app", None) if mod is not None else None
    if app is None:
        return
    try:
        app.send_task(GENERATE_TASK, args=[str(job_id)], countdown=2)
    except Exception as e:  # broker down: the sweep covers it
        log.warning("export.enqueue_failed", export_job_id=str(job_id), error=type(e).__name__)
