"""Advisory integrity review (api-specification ASM-18/19/20; RE §4.5 IN-03).

Integrity signals are *advisory*: they are aggregated per attempt from ``attempt_events`` (and
coding submit bursts / similarity flags from ``code_submissions``) into "review recommended"
flags. Nothing here changes a score automatically; only a human decision (ASM-20) or an explicit
invalidation (ASM-18) changes an attempt. IP addresses are never read or returned.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from fastapi import Request
from sqlalchemy import bindparam, select, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import audit
from app.core.auth import PLATFORM_SCOPE, ScopeRef, require_step_up
from app.core.db import system_context
from app.core.errors import ProblemError
from app.core.ids import uuid7
from app.core.pagination import decode_cursor, page_meta
from app.core.principal import Principal
from app.core.time import utcnow
from app.modules.assessments import attempts as svc
from app.modules.assessments.models import AttemptIntegrityDecision, TestAttempt
from app.modules.placement.policies import has_permission

# --------------------------------------------------------------------------- thresholds
# Per-attempt counts at or above which an attempt is flagged "review recommended".
FOCUS_LOST_REVIEW_MIN = 5
FULLSCREEN_EXIT_REVIEW_MIN = 3
PASTE_REVIEW_MIN = 3
DISCONNECT_REVIEW_MIN = 4
REBIND_REVIEW_MIN = 2
REBIND_REFUSED_REVIEW_MIN = 1
REATTACH_REVIEW_MIN = 3
SESSION_REVOKED_SECURITY_REVIEW_MIN = 1
CODE_SUBMIT_BURST_REVIEW_MIN = 20  # IN-03 hidden-test probing: submits per problem per hour
SIMILARITY_REVIEW_MIN = 1
WINDOW_BLUR_REVIEW_MIN = 5
COPY_CUT_REVIEW_MIN = 5
RESIZE_REVIEW_MIN = 10
RIGHT_CLICK_REVIEW_MIN = 10

# signal key -> (threshold, label). Keys are also the SQL column aliases below (constants only).
THRESHOLDS: dict[str, tuple[int, str]] = {
    "focus_lost": (FOCUS_LOST_REVIEW_MIN, "Left the test window"),
    "fullscreen_exit": (FULLSCREEN_EXIT_REVIEW_MIN, "Exited full screen"),
    "paste": (PASTE_REVIEW_MIN, "Pasted content"),
    "window_blur": (WINDOW_BLUR_REVIEW_MIN, "Window inactive"),
    "copy": (COPY_CUT_REVIEW_MIN, "Copied content"),
    "cut": (COPY_CUT_REVIEW_MIN, "Cut content"),
    "resize": (RESIZE_REVIEW_MIN, "Resized the window"),
    "right_click": (RIGHT_CLICK_REVIEW_MIN, "Right-clicked"),
    "disconnect": (DISCONNECT_REVIEW_MIN, "Connection dropped"),
    "rebind": (REBIND_REVIEW_MIN, "Switched device"),
    "rebind_refused": (REBIND_REFUSED_REVIEW_MIN, "Device switch refused"),
    "reattach_same_device": (REATTACH_REVIEW_MIN, "Re-attached after re-login"),
    "session_revoked_security": (SESSION_REVOKED_SECURITY_REVIEW_MIN, "Session ended by security"),
    "code_submit_burst": (CODE_SUBMIT_BURST_REVIEW_MIN, "Rapid code submissions (hidden-test probing)"),
    "similarity_flags": (SIMILARITY_REVIEW_MIN, "Code similarity flagged"),
}
EVENT_SIGNALS = (
    "focus_lost",
    "fullscreen_exit",
    "paste",
    "window_blur",
    "copy",
    "cut",
    "resize",
    "right_click",
    "disconnect",
    "rebind",
    "rebind_refused",
    "reattach_same_device",
    "session_revoked_security",
)
OUTCOME_STATUS = {"no_action": "cleared", "refer_security": "review_recommended", "invalidate": "invalidated"}
CLOSED_FOR_INVALIDATION = ("in_progress", "abandoned", "invalidated")


# --------------------------------------------------------------------------- scope


@dataclass
class Scope:
    platform: bool = False
    orgs: set[uuid.UUID] = field(default_factory=set)
    batches: set[uuid.UUID] = field(default_factory=set)

    @property
    def empty(self) -> bool:
        return not (self.platform or self.orgs or self.batches)


async def scope_of(request: Request, principal: Principal, permission: str) -> Scope:
    """Every org/batch at which ``principal`` holds ``permission`` (platform = everything)."""
    s = Scope()
    if await has_permission(request, principal, permission, PLATFORM_SCOPE):
        s.platform = True
        return s
    orgs = set(principal.org_ids) | {
        g.scope_id for g in principal.grants if g.scope_type == "organization" and g.scope_id
    }
    for o in orgs:
        if await has_permission(request, principal, permission, ScopeRef("organization", o)):
            s.orgs.add(o)
    for g in principal.grants:
        if g.scope_type == "batch" and g.scope_id and g.scope_id not in s.batches:
            if await has_permission(request, principal, permission, ScopeRef("batch", g.scope_id)):
                s.batches.add(g.scope_id)
    return s


def _uuid_list(name: str) -> Any:
    return bindparam(name, type_=ARRAY(PG_UUID(as_uuid=True)))


# --------------------------------------------------------------------------- flags (ASM-19)


def _iso(dt: datetime | None) -> str | None:
    return svc.iso(dt)


def _reasons(signals: dict[str, int]) -> list[dict[str, Any]]:
    out = []
    for key, (threshold, label) in THRESHOLDS.items():
        n = signals.get(key, 0)
        if n >= threshold:
            out.append({"code": key, "label": label, "count": n, "threshold": threshold})
    return out


_EV_COLS = ",\n      ".join(f"count(*) FILTER (WHERE event_type = '{k}') AS {k}" for k in EVENT_SIGNALS)
_EV_TYPES = ", ".join(f"'{k}'" for k in EVENT_SIGNALS)
_FLAG_COND = " OR ".join(f"coalesce({k}, 0) >= {t}" for k, (t, _) in THRESHOLDS.items())

FLAGS_SQL = f"""
WITH ev AS (
  SELECT attempt_id,
      {_EV_COLS}
  FROM attempt_events
  WHERE event_type IN ({_EV_TYPES})
  GROUP BY attempt_id
), cs AS (
  SELECT attempt_id, max(c) AS code_submit_burst, sum(sim) AS similarity_flags
  FROM (
    SELECT attempt_id, coding_problem_id, date_trunc('hour', queued_at) AS h,
           count(*) AS c, count(*) FILTER (WHERE similarity_flag) AS sim
    FROM code_submissions
    WHERE attempt_id IS NOT NULL AND mode = 'submit'
    GROUP BY 1, 2, 3
  ) x
  GROUP BY attempt_id
), dec AS (
  SELECT DISTINCT ON (attempt_id) id AS decision_id, attempt_id, outcome, note, created_at AS decided_at,
         decided_by, security_case_ref
  FROM attempt_integrity_decisions
  ORDER BY attempt_id, created_at DESC
), base AS (
  SELECT a.id, a.test_id, t.title AS test_title, a.user_id,
         coalesce(u.display_name, u.full_name) AS student_name,
         a.organization_id, a.batch_id, a.status AS attempt_status, a.attempt_no, a.started_at,
         a.submitted_at, a.integrity_status,
         {", ".join(f"coalesce(ev.{k}, 0) AS {k}" for k in EVENT_SIGNALS)},
         coalesce(cs.code_submit_burst, 0) AS code_submit_burst,
         coalesce(cs.similarity_flags, 0) AS similarity_flags,
         dec.decision_id, dec.outcome, dec.note, dec.decided_at, dec.decided_by, dec.security_case_ref
  FROM test_attempts a
  JOIN tests t ON t.id = a.test_id
  LEFT JOIN user_profiles u ON u.user_id = a.user_id
  LEFT JOIN ev ON ev.attempt_id = a.id
  LEFT JOIN cs ON cs.attempt_id = a.id
  LEFT JOIN dec ON dec.attempt_id = a.id
  WHERE (:platform OR a.organization_id = ANY (:orgs) OR a.batch_id = ANY (:batches))
    AND (CAST(:test_id AS uuid) IS NULL OR a.test_id = CAST(:test_id AS uuid))
    AND (CAST(:batch_id AS uuid) IS NULL OR a.batch_id = CAST(:batch_id AS uuid))
    AND (CAST(:attempt_id AS uuid) IS NULL OR a.id = CAST(:attempt_id AS uuid))
)
SELECT * FROM base
WHERE ({_FLAG_COND} OR decision_id IS NOT NULL OR integrity_status = 'review_recommended')
  AND (:status = 'all' OR (:status = 'open' AND decision_id IS NULL)
       OR (:status = 'decided' AND decision_id IS NOT NULL))
  AND (CAST(:c_started AS timestamptz) IS NULL
       OR (started_at, id) < (CAST(:c_started AS timestamptz), CAST(:c_id AS uuid)))
ORDER BY started_at DESC, id DESC
LIMIT :lim
"""  # noqa: S608 - only module constants are interpolated; values are bound


def _flag_out(r: Any) -> dict[str, Any]:
    m = r._mapping
    signals = {k: int(m[k] or 0) for k in THRESHOLDS}
    decision = None
    if m["decision_id"] is not None:
        decision = {
            "decision_id": str(m["decision_id"]),
            "outcome": m["outcome"],
            "note": m["note"],
            "decided_at": _iso(m["decided_at"]),
            "decided_by": str(m["decided_by"]),
            "security_case_ref": m["security_case_ref"],
        }
    return {
        "attempt_id": str(m["id"]),
        "test_id": str(m["test_id"]),
        "test_title": m["test_title"],
        "user_id": str(m["user_id"]),
        "student_name": m["student_name"],
        "organization_id": str(m["organization_id"]) if m["organization_id"] else None,
        "batch_id": str(m["batch_id"]) if m["batch_id"] else None,
        "attempt_status": m["attempt_status"],
        "attempt_no": m["attempt_no"],
        "started_at": _iso(m["started_at"]),
        "submitted_at": _iso(m["submitted_at"]),
        "integrity_status": m["integrity_status"],
        "signals": signals,
        "reasons": _reasons(signals),
        "recommendation": "review_recommended",
        "status": "decided" if decision else "open",
        "decision": decision,
    }


async def _query_flags(
    session: AsyncSession,
    scope: Scope,
    *,
    test_id: uuid.UUID | None = None,
    batch_id: uuid.UUID | None = None,
    attempt_id: uuid.UUID | None = None,
    status: str = "all",
    cursor: dict[str, Any] | None = None,
    limit: int = 25,
) -> list[Any]:
    stmt = text(FLAGS_SQL).bindparams(_uuid_list("orgs"), _uuid_list("batches"))
    params = {
        "platform": scope.platform,
        "orgs": list(scope.orgs),
        "batches": list(scope.batches),
        "test_id": test_id,
        "batch_id": batch_id,
        "attempt_id": attempt_id,
        "status": status,
        "c_started": datetime.fromisoformat(str(cursor["s"])) if cursor else None,
        "c_id": uuid.UUID(str(cursor["id"])) if cursor else None,
        "lim": limit,
    }
    return list((await session.execute(stmt, params)).all())


async def list_flags(
    request: Request,
    session: AsyncSession,
    principal: Principal,
    *,
    test_id: uuid.UUID | None,
    batch_id: uuid.UUID | None,
    status: str | None,
    cursor: str | None,
    limit: int,
) -> dict[str, Any]:
    scope = await scope_of(request, principal, "integrity.flag.read")
    if scope.empty:
        raise ProblemError("permission_denied", permission="integrity.flag.read")
    pos = decode_cursor(cursor) if cursor else None
    if pos is not None:
        try:
            datetime.fromisoformat(str(pos["s"]))
            uuid.UUID(str(pos["id"]))
        except (KeyError, ValueError) as e:
            raise ProblemError("invalid_cursor") from e
    rows = await _query_flags(
        session,
        scope,
        test_id=test_id,
        batch_id=batch_id,
        status=status or "all",
        cursor=pos,
        limit=limit + 1,
    )
    more = len(rows) > limit
    rows = rows[:limit]
    nxt = None
    if more and rows:
        last = rows[-1]._mapping
        nxt = {"s": last["started_at"].isoformat(), "id": str(last["id"])}
    return {
        "data": [_flag_out(r) for r in rows],
        "page": page_meta(nxt, limit),
        "thresholds": {k: t for k, (t, _) in THRESHOLDS.items()},
    }


async def attempt_signals(session: AsyncSession, attempt: TestAttempt) -> dict[str, int]:
    rows = await _query_flags(session, Scope(platform=True), attempt_id=attempt.id, limit=1)
    if not rows:
        return {}
    return {k: v for k, v in _flag_out(rows[0])["signals"].items() if v}


# --------------------------------------------------------------------------- decisions (ASM-20)


async def _latest_decision(session: AsyncSession, attempt_id: uuid.UUID) -> AttemptIntegrityDecision | None:
    return (
        await session.execute(
            select(AttemptIntegrityDecision)
            .where(AttemptIntegrityDecision.attempt_id == attempt_id)
            .order_by(AttemptIntegrityDecision.created_at.desc(), AttemptIntegrityDecision.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


def decision_out(d: AttemptIntegrityDecision, att: TestAttempt, *, replayed: bool = False) -> dict[str, Any]:
    return {
        "decision_id": str(d.id),
        "attempt_id": str(d.attempt_id),
        "outcome": d.outcome,
        "note": d.note,
        "decided_at": _iso(d.created_at),
        "decided_by": str(d.decided_by),
        "attempt_status": att.status,
        "integrity_status": att.integrity_status,
        "security_case_ref": d.security_case_ref,
        "replayed": replayed,
    }


async def load_for_staff(
    request: Request, session: AsyncSession, principal: Principal, attempt_id: uuid.UUID, permission: str
) -> TestAttempt:
    """Attempt visible under RLS and ``permission`` held at its batch/org; foreign = 404; one's
    own attempt = 403 ``conflict_of_interest`` (every caller is a write)."""
    from app.modules.assessments import studio

    att = await svc.load_attempt(session, attempt_id, lock=True)
    if not await studio.attempt_scope_allows(
        request, principal, permission, batch_id=att.batch_id, org_id=att.organization_id
    ):
        raise ProblemError(
            "permission_denied" if att.user_id == principal.user_id else "not_found", permission=permission
        )
    if att.user_id == principal.user_id:
        # SEC-10: no integrity decision or invalidation on one's own attempt.
        raise ProblemError("conflict_of_interest", detail="You cannot decide on your own attempt.")
    return att


async def _open_referral(
    session: AsyncSession, principal: Principal, att: TestAttempt, note: str, signals: dict[str, int]
) -> tuple[uuid.UUID, str]:
    """SEC-12 style ``integrity_referral`` case. ``security_cases`` is RLS O (subject/platform),
    so this single insert runs as a named system job; the principal's context is restored."""
    from app.modules.security import cases as sec_cases
    from app.modules.security import engine as sec_engine

    await session.flush()
    async with system_context(session, "assessments.integrity_referral"):
        case = await sec_engine.open_case(
            session,
            user_id=att.user_id,
            family="sharing",
            level=0,
            opened_reason="integrity_referral",
            priority="medium",
            actor=principal,
        )
        summary = ", ".join(f"{k}={v}" for k, v in sorted(signals.items())) or "none"
        await sec_cases.case_note(
            session,
            case.id,
            principal.user_id,
            "internal",
            f"Integrity referral for attempt {att.id} (test {att.test_id}). Signals: {summary}. "
            f"Reviewer note: {note}",
        )
        await session.flush()
        return case.id, case.case_ref


async def _notify_invalidated(session: AsyncSession, principal: Principal, att: TestAttempt) -> None:
    from app.modules.notifications.service import notify

    await session.flush()
    async with system_context(session, "assessments.notify_invalidated"):
        await notify(
            session,
            att.user_id,
            "assessment.attempt_invalidated",
            category="learning",
            data={
                "attempt_id": str(att.id),
                "test_id": str(att.test_id),
                "appeal_url": f"/app/support/new?topic=assessment&attempt_id={att.id}",
            },
            channels=("in_app",),
            organization_id=att.organization_id,
            priority="high",
            dedupe_key=f"attempt_invalidated:{att.id}",
        )
        await session.flush()


async def invalidate(
    session: AsyncSession, principal: Principal, att: TestAttempt, reason: str, *, source: str
) -> None:
    """ASM-18: human-reviewed invalidation. Caller has checked ``attempt.invalidate`` + step-up."""
    if att.status in CLOSED_FOR_INVALIDATION:
        raise ProblemError(
            "invalid_state_transition",
            detail="Only a submitted attempt can be invalidated.",
            attempt_status=att.status,
        )
    before = {"status": att.status, "integrity_status": att.integrity_status}
    att.status = "invalidated"
    att.integrity_status = "invalidated"
    await svc.add_event(
        session,
        att,
        "invalidate",
        principal=principal,
        payload={"source": source, "by": str(principal.user_id)},
    )
    await session.flush()
    await audit(
        session,
        principal,
        "attempt.invalidated",
        "test_attempt",
        att.id,
        organization_id=att.organization_id,
        subject_user_id=att.user_id,
        reason=reason,
        before=before,
        after={"status": att.status, "integrity_status": att.integrity_status, "source": source},
    )
    await _notify_invalidated(session, principal, att)


async def decide(
    request: Request,
    session: AsyncSession,
    principal: Principal,
    attempt_id: uuid.UUID,
    outcome: str,
    note: str,
) -> tuple[dict[str, Any], int]:
    att = await load_for_staff(request, session, principal, attempt_id, "integrity.flag.decide")
    if outcome == "invalidate":
        from app.modules.assessments import studio

        if not await studio.attempt_scope_allows(
            request, principal, "attempt.invalidate", batch_id=att.batch_id, org_id=att.organization_id
        ):
            raise ProblemError("permission_denied", permission="attempt.invalidate")
        await require_step_up("staff")(principal)
    latest = await _latest_decision(session, att.id)
    if latest is not None:
        if latest.outcome == outcome and latest.note == note:
            return decision_out(latest, att, replayed=True), 200  # natural idempotency
        if latest.outcome == "invalidate":
            raise ProblemError("invalid_state_transition", detail="This attempt was already invalidated.")
    if outcome == "invalidate" and att.status in CLOSED_FOR_INVALIDATION:
        raise ProblemError(
            "invalid_state_transition",
            detail="Only a submitted attempt can be invalidated.",
            attempt_status=att.status,
        )
    signals = await attempt_signals(session, att)
    case_id: uuid.UUID | None = None
    case_ref: str | None = None
    if outcome == "refer_security":
        case_id, case_ref = await _open_referral(session, principal, att, note, signals)
    if outcome == "invalidate":
        await invalidate(session, principal, att, note, source="integrity_review")
    else:
        att.integrity_status = OUTCOME_STATUS[outcome]
    d = AttemptIntegrityDecision(
        id=uuid7(),
        attempt_id=att.id,
        test_id=att.test_id,
        user_id=att.user_id,
        organization_id=att.organization_id,
        batch_id=att.batch_id,
        outcome=outcome,
        note=note,
        signals=signals,
        security_case_id=case_id,
        security_case_ref=case_ref,
        decided_by=principal.user_id,
        created_at=utcnow(),
    )
    session.add(d)
    await session.flush()
    await audit(
        session,
        principal,
        "attempt.integrity_decided",
        "test_attempt",
        att.id,
        organization_id=att.organization_id,
        subject_user_id=att.user_id,
        reason=note,
        before={"decision": latest.outcome if latest else None},
        after={"outcome": outcome, "security_case_ref": case_ref, "signals": signals},
    )
    return decision_out(d, att), 201
