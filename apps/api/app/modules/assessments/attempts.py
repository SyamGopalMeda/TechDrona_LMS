"""Attempt engine (api-specification §15, ADR-0013).

* Server-authoritative timer: ``deadline_at`` fixed at start (duration + overrides, bounded by the
  window); every payload carries ``server_now``; writes after ``deadline_at + grace`` are refused
  with ``409 attempt_closed`` and the attempt is closed on the spot (lazy expiry) — the DB sweeper
  (``tasks.sweep_expired_attempts``) closes attempts nobody touches.
* Session binding: one session per attempt; a new session on the bound device re-attaches
  (no rebind consumed), another device must rebind (confirmation, OTP at >= L2, max 2).
* Answer keys never leave the server here: delivery DTOs are key-free; review fields are added
  only when the review policy's current phase allows.
* Scoring is server-side only, idempotent per ``(attempt_id, scoring_version)``.
"""

from __future__ import annotations

import contextlib
import os
import random
import uuid
from collections import defaultdict
from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import func, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import set_committed_value

from app.core.access import require_access
from app.core.db import system_context
from app.core.errors import ProblemError
from app.core.ids import uuid7
from app.core.outbox import emit_event
from app.core.principal import Principal
from app.core.time import to_rfc3339, utcnow
from app.modules.assessments import exam
from app.modules.assessments.models import (
    AttemptEvent,
    AttemptOverride,
    AttemptResponse,
    AttemptResult,
    AttemptSection,
    Test,
    TestAssignment,
    TestAttempt,
)
from app.modules.assessments.schemas import AttemptStart, AutosaveIn, AutosaveItem
from app.modules.assessments.studio import rule_pool, sections_of
from app.modules.placement import bank, grading

SESSION_HOLD_SLACK = timedelta(minutes=5)
AUTOSAVE_POLICY = {"debounce_ms": 5000, "max_interval_ms": 10000, "max_items": 50}
DEFAULT_MAX_REBINDS = 2
DEFAULT_OTP_LEVEL = 2
TERMINAL = frozenset({"submitted", "auto_submitted", "grading", "awaiting_manual", "graded", "invalidated"})
_TWO = Decimal("0.01")
# Advisory events accepted from tests without the exam protocol (historical behaviour).
LEGACY_CLIENT_EVENTS = frozenset(
    {"focus_lost", "focus_gained", "fullscreen_exit", "paste", "disconnect", "reconnect"}
)
CONNECTIVITY_EVENTS = frozenset({"focus_gained", "disconnect", "reconnect"})
# Item types graded by a person (AI may only suggest): never auto-scored.
MANUAL_TYPES = frozenset({"descriptive", "essay", "short_answer"})
MAX_MANUAL_CHARS = 20000


def iso(dt: datetime | None) -> str | None:
    return to_rfc3339(dt) if dt else None


def _q2(d: Decimal) -> Decimal:
    return d.quantize(_TWO, rounding=ROUND_HALF_UP)


# --------------------------------------------------------------------------- policy knobs


async def _policy_int(session: AsyncSession, key: str, default: int, user_id: uuid.UUID) -> int:
    from app.modules.identity.policy import get_policy

    raw = await get_policy(session, key, user_id=user_id)
    if raw is None:
        return default
    s = str(raw).strip().strip('"').upper().lstrip("L")
    try:
        return int(s)
    except ValueError:
        return default


async def max_rebinds(session: AsyncSession, user_id: uuid.UUID) -> int:
    return await _policy_int(session, "assessment.max_rebinds_per_attempt", DEFAULT_MAX_REBINDS, user_id)


async def otp_level(session: AsyncSession, user_id: uuid.UUID) -> int:
    return await _policy_int(session, "assessment.rebind_requires_otp_at_level", DEFAULT_OTP_LEVEL, user_id)


# --------------------------------------------------------------------------- events


async def add_event(
    session: AsyncSession,
    attempt: TestAttempt,
    event_type: str,
    *,
    principal: Principal | None = None,
    payload: dict[str, Any] | None = None,
    question_version_id: uuid.UUID | None = None,
    client_seq: int | None = None,
    ip: str | None = None,
    at: datetime | None = None,
) -> None:
    session.add(
        AttemptEvent(
            id=uuid7(),
            occurred_at=at or utcnow(),
            attempt_id=attempt.id,
            user_id=attempt.user_id,
            organization_id=attempt.organization_id,
            event_type=event_type,
            question_version_id=question_version_id,
            client_seq=client_seq,
            payload=payload or {},
            auth_session_id=principal.session_id if principal else None,
            ip=ip,
        )
    )


async def rebind_overrides(session: AsyncSession, attempt_id: uuid.UUID) -> int:
    rows = await session.execute(
        select(AttemptEvent.payload).where(
            AttemptEvent.attempt_id == attempt_id, AttemptEvent.event_type == "override_applied"
        )
    )
    return sum(1 for (p,) in rows.all() if isinstance(p, dict) and p.get("kind") == "rebind")


# --------------------------------------------------------------------------- loading


async def load_attempt(session: AsyncSession, attempt_id: uuid.UUID, *, lock: bool = False) -> TestAttempt:
    q = select(TestAttempt).where(TestAttempt.id == attempt_id)
    if lock:
        q = q.with_for_update()
    att = (await session.execute(q)).scalar_one_or_none()
    if att is None:
        raise ProblemError("not_found")
    return att


async def load_owned(
    session: AsyncSession, principal: Principal, attempt_id: uuid.UUID, *, lock: bool = False
) -> tuple[TestAttempt, Test]:
    att = await load_attempt(session, attempt_id, lock=lock)
    if att.user_id != principal.user_id:
        raise ProblemError("not_found")
    test = await session.get(Test, att.test_id)
    if test is None:  # pragma: no cover - FK
        raise ProblemError("not_found")
    return att, test


async def attempt_sections(session: AsyncSession, attempt_id: uuid.UUID) -> list[AttemptSection]:
    return list(
        (
            await session.execute(
                select(AttemptSection)
                .where(AttemptSection.attempt_id == attempt_id)
                .order_by(AttemptSection.position)
            )
        ).scalars()
    )


# --------------------------------------------------------------------------- eligibility


async def _member_of_batch(session: AsyncSession, user_id: uuid.UUID, batch_id: uuid.UUID) -> bool:
    from app.modules.orgs.models import BatchMember

    q = select(BatchMember.id).where(
        BatchMember.batch_id == batch_id,
        BatchMember.user_id == user_id,
        BatchMember.status == "active",
        BatchMember.removed_at.is_(None),
    )
    return (await session.execute(q.limit(1))).first() is not None


async def eligible_assignments(
    session: AsyncSession, principal: Principal, test_id: uuid.UUID
) -> list[TestAssignment]:
    rows = (
        await session.execute(
            select(TestAssignment)
            .where(TestAssignment.test_id == test_id)
            .order_by(TestAssignment.available_from.desc())
        )
    ).scalars()
    out = []
    for a in rows:
        if a.batch_id is not None:
            if await _member_of_batch(session, principal.user_id, a.batch_id):
                out.append(a)
        elif a.organization_id is not None and a.organization_id in principal.org_ids:
            out.append(a)
    return out


async def overrides_for(
    session: AsyncSession, test_id: uuid.UUID, user_id: uuid.UUID, a: TestAssignment | None
) -> tuple[int, int, int]:
    conds = [AttemptOverride.user_id == user_id]
    if a is not None and a.batch_id is not None:
        conds.append(AttemptOverride.batch_id == a.batch_id)
    from sqlalchemy import or_

    q = select(AttemptOverride).where(AttemptOverride.test_id == test_id, or_(*conds))
    t = n = w = 0
    for o in (await session.execute(q)).scalars():
        if o.test_assignment_id is not None and (a is None or o.test_assignment_id != a.id):
            continue
        t += o.extra_time_seconds
        n += o.extra_attempts
        w += o.window_extension_seconds
    return t, n, w


def window_of(test: Test, a: TestAssignment | None) -> tuple[datetime | None, datetime | None]:
    if a is not None:
        return a.available_from, a.available_until
    return test.available_from, test.available_until


async def _device_owner_verified(session: AsyncSession, principal: Principal) -> bool:
    if principal.device_id is None:
        return False
    from app.modules.sessions.models import UserDevice

    q = select(UserDevice.id).where(
        UserDevice.user_id == principal.user_id,
        UserDevice.device_id == principal.device_id,
        UserDevice.removed_at.is_(None),
        UserDevice.owner_verified_at.is_not(None),
    )
    return (await session.execute(q.limit(1))).first() is not None


async def _gate_restrictions(session: AsyncSession, principal: Principal) -> None:
    if principal.restriction_level >= 3:
        raise ProblemError("account_restricted", level=principal.restriction_level)
    if principal.restriction_level >= 2 and not await _device_owner_verified(session, principal):
        raise ProblemError("device_verification_required")


# --------------------------------------------------------------------------- session hold


async def hold_session(
    session: AsyncSession, session_id: uuid.UUID, attempt: TestAttempt, test: Test
) -> None:
    if attempt.deadline_at is None:
        return
    from app.modules.sessions.models import AuthSession

    until = attempt.deadline_at + timedelta(seconds=test.grace_seconds) + SESSION_HOLD_SLACK
    await session.execute(
        update(AuthSession)
        .where(AuthSession.id == session_id)
        .values(idle_hold_until=until)
        .execution_options(synchronize_session=False)
    )


async def lock_settings(session: AsyncSession, principal: Principal, test: Test, now: datetime) -> None:
    """``settings_locked_at`` on the first attempt (SoD-08). Students cannot write test rows under
    RLS (platform tests are TN with NULL org), so this single guarded UPDATE runs as a named
    system job and the principal's context is restored immediately."""
    if test.settings_locked_at is not None:
        return
    await session.flush()
    async with system_context(session, "assessments.lock_test_settings"):
        await session.execute(
            update(Test)
            .where(Test.id == test.id, Test.settings_locked_at.is_(None))
            .values(settings_locked_at=now)
            .execution_options(synchronize_session=False)
        )
    set_committed_value(test, "settings_locked_at", now)


# --------------------------------------------------------------------------- layout


async def build_layout(
    session: AsyncSession, test: Test, seed: bytes, integrity_consent: bool
) -> dict[str, Any]:
    rng = random.Random(seed)  # noqa: S311 - deterministic replay of a CSPRNG-seeded draw
    used: set[uuid.UUID] = set()
    out_sections = []
    sections = await sections_of(session, test.id)
    # BE-03: fixed questions are reserved before any random draw, so a random rule over the same
    # topic can never take a question a later fixed rule needs (matches studio.validate).
    reserved: set[uuid.UUID] = set()
    for _sec, rules in sections:
        for rule in rules:
            if rule.rule_type == "fixed":
                reserved.update(await rule_pool(session, rule))
    for sec, rules in sections:
        chosen: list[tuple[uuid.UUID, Any]] = []
        for rule in rules:
            blocked = used if rule.rule_type == "fixed" else used | reserved
            pool = [q for q in await rule_pool(session, rule) if q not in blocked]
            if len(pool) < rule.draw_count:
                raise ProblemError(
                    "invalid_state_transition",
                    detail="This test cannot be started right now (question pool exhausted). "
                    "Please contact support.",
                )
            picks = rng.sample(sorted(pool), rule.draw_count) if rule.rule_type == "random" else pool[:1]
            for qv in picks:
                used.add(qv)
                chosen.append((qv, rule))
        bundles = await bank.load_bundles(session, [c[0] for c in chosen])
        items = []
        for qv, rule in chosen:
            b = bundles[qv]
            opts = [str(o.id) for o in b.options]
            if test.shuffle_options and b.qtype in grading.MCQ_TYPES:
                rng.shuffle(opts)
            marks = rule.marks_each if rule.marks_each is not None else b.version.default_marks
            neg = (
                rule.negative_marks_each
                if rule.negative_marks_each is not None
                else b.version.default_negative
            )
            items.append(
                {
                    "qv": str(qv),
                    "q": str(b.question.id),
                    "topic": str(b.question.primary_topic_id),
                    "opts": opts,
                    "marks": str(marks),
                    "neg": str(neg),
                }
            )
        if test.shuffle_questions:
            rng.shuffle(items)
        out_sections.append(
            {
                "section_id": str(sec.id),
                "title": sec.title,
                "position": sec.position,
                "duration_seconds": sec.duration_seconds,
                "items": items,
            }
        )
    if not any(s["items"] for s in out_sections):
        raise ProblemError("invalid_state_transition", detail="This test has no questions yet.")
    return {"v": 1, "integrity_consent": integrity_consent, "sections": out_sections}


def layout_index(attempt: TestAttempt) -> dict[str, tuple[str, dict[str, Any]]]:
    """qv id -> (section_id, item)."""
    return {it["qv"]: (s["section_id"], it) for s in attempt.layout["sections"] for it in s["items"]}


# --------------------------------------------------------------------------- start


async def start(
    session: AsyncSession,
    principal: Principal,
    body: AttemptStart,
    *,
    idempotency_key: str,
    ip: str | None,
) -> tuple[TestAttempt, Test]:
    from app.modules.sessions.models import AuthSession

    test = await session.get(Test, body.test_id)
    if test is None or test.status != "published":
        raise ProblemError("not_found")
    await _gate_restrictions(session, principal)
    assignments = await eligible_assignments(session, principal, test.id)
    a: TestAssignment | None = None
    if body.test_assignment_id is not None:
        a = next((x for x in assignments if x.id == body.test_assignment_id), None)
        if a is None:
            raise ProblemError("not_found")
    elif assignments:
        now0 = utcnow()
        a = next((x for x in assignments if x.available_from <= now0 < x.available_until), assignments[0])
    if a is None:
        await require_access(session, principal, "test", test.id, is_free=test.is_free)
    extra_time, extra_attempts, window_ext = await overrides_for(session, test.id, principal.user_id, a)
    now = utcnow()
    frm, until = window_of(test, a)
    until_ext = until + timedelta(seconds=window_ext) if until is not None else None
    if frm is not None and now < frm:
        raise ProblemError("test_not_open", available_from=to_rfc3339(frm))
    if until_ext is not None and now >= until_ext:
        raise ProblemError("test_window_closed", available_until=to_rfc3339(until_ext))

    # DB-03/BE-22: serialise starts per (test, user). The FOR UPDATE below locks nothing while no
    # attempt row exists, so two tabs would both insert attempt_no = max+1 and the loser hit the
    # unique index (500). The transaction-scoped advisory lock makes the loser wait, then see the
    # winner's open attempt -> 409 active_attempt_exists.
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:k, 0))"),
        {"k": f"assessments.attempt_start:{test.id}:{principal.user_id}"},
    )
    open_att = (
        await session.execute(
            select(TestAttempt)
            .where(
                TestAttempt.test_id == test.id,
                TestAttempt.user_id == principal.user_id,
                TestAttempt.status == "in_progress",
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if open_att is not None and not await expire_if_due(session, open_att, test, now):
        raise ProblemError("active_attempt_exists", attempt_id=str(open_att.id))

    used = (
        await session.execute(
            select(func.count(), func.coalesce(func.max(TestAttempt.attempt_no), 0)).where(
                TestAttempt.test_id == test.id,
                TestAttempt.user_id == principal.user_id,
            )
        )
    ).one()
    n_used = int(used[0])
    allowed = (a.attempts_allowed if a and a.attempts_allowed else None) or test.attempts_allowed
    if allowed is not None and n_used >= allowed + extra_attempts:
        raise ProblemError("attempt_limit_reached")
    protocol = exam.protocol_of(test)
    if protocol.require_agreement and not body.instructions_agreed:
        raise ProblemError(
            "validation_failed",
            detail="Agree to the exam instructions to start.",
            errors=[
                {
                    "field": "instructions_agreed",
                    "code": "required",
                    "message": "agree to the conduct instructions to start the exam",
                }
            ],
        )
    # Exam protocol: agreeing to conduct instructions that state what is recorded is the consent
    # to record those events (the instructions screen shows exactly that list).
    consent = body.integrity_consent or (protocol.exam_mode and body.instructions_agreed)
    if test.integrity_settings.get("consent_mandatory") and not consent:
        raise ProblemError("consent_required", purposes=["assessment_integrity"])

    deadline: datetime | None = None
    if test.duration_seconds:
        deadline = now + timedelta(seconds=test.duration_seconds + extra_time)
    if until_ext is not None:
        deadline = min(deadline, until_ext) if deadline else until_ext
    auth = await session.get(AuthSession, principal.session_id)
    if (
        auth is not None
        and deadline is not None
        and auth.absolute_expires_at < deadline + timedelta(seconds=test.grace_seconds) + SESSION_HOLD_SLACK
    ):
        raise ProblemError("session_too_short_for_attempt", reauth_url="/login?reauth=1")

    seed = os.urandom(16)
    layout = await build_layout(session, test, seed, consent)
    attempt = TestAttempt(
        id=uuid7(),
        test_id=test.id,
        test_version=test.version,
        test_assignment_id=a.id if a else None,
        user_id=principal.user_id,
        organization_id=a.organization_id if a else test.organization_id,
        batch_id=a.batch_id if a else None,
        attempt_no=int(used[1]) + 1,
        status="in_progress",
        selection_seed=seed,
        layout=layout,
        started_at=now,
        deadline_at=deadline,
        extra_time_seconds=extra_time,
        last_seen_at=now,
        bound_session_id=principal.session_id,
        bound_device_id=principal.device_id,
        start_ip=ip,
        idempotency_key=idempotency_key,
    )
    session.add(attempt)
    await session.flush()
    sequential = test.navigation_mode != "free"
    first = True
    for s in layout["sections"]:
        active = not sequential or first
        sec_deadline = None
        if active and sequential and s.get("duration_seconds"):
            sec_deadline = now + timedelta(seconds=int(s["duration_seconds"]))
            if deadline is not None:
                sec_deadline = min(sec_deadline, deadline)
        elif active:
            sec_deadline = deadline
        session.add(
            AttemptSection(
                attempt_id=attempt.id,
                test_section_id=uuid.UUID(s["section_id"]),
                user_id=attempt.user_id,
                organization_id=attempt.organization_id,
                position=s["position"],
                status="active" if active else "not_started",
                started_at=now if active else None,
                deadline_at=sec_deadline,
            )
        )
        if first:
            attempt.current_section_id = uuid.UUID(s["section_id"])
        first = False
    await lock_settings(session, principal, test, now)
    await hold_session(session, principal.session_id, attempt, test)
    await add_event(
        session,
        attempt,
        "start",
        principal=principal,
        ip=ip,
        at=now,
        payload={
            "integrity_consent": consent,
            "instructions_agreed": body.instructions_agreed,
            "exam_mode": protocol.exam_mode,
            "test_version": test.version,
            "extra_time_seconds": extra_time,
        },
    )
    await session.flush()
    await emit_event(
        session,
        "attempt.started",
        {
            "attempt_id": str(attempt.id),
            "test_id": str(test.id),
            "user_id": str(attempt.user_id),
            "attempt_no": attempt.attempt_no,
            "started_at": to_rfc3339(now),
            "deadline_at": iso(deadline),
            "time_limit_s": test.duration_seconds,
        },
        aggregate_type="test_attempt",
        aggregate_id=attempt.id,
        organization_id=attempt.organization_id,
    )
    return attempt, test


# --------------------------------------------------------------------------- binding


async def _bound_label(session: AsyncSession, attempt: TestAttempt) -> tuple[str, datetime]:
    from app.modules.sessions.models import AuthSession

    label = "another device"
    if attempt.bound_session_id is not None:
        s = await session.get(AuthSession, attempt.bound_session_id)
        if s is not None and (s.ua_family or s.os_family):
            label = f"{s.ua_family or 'Browser'} on {s.os_family or 'unknown OS'}"
    since = (
        await session.execute(
            select(func.max(AttemptEvent.occurred_at)).where(
                AttemptEvent.attempt_id == attempt.id,
                AttemptEvent.event_type.in_(("start", "rebind", "reattach_same_device")),
            )
        )
    ).scalar_one_or_none()
    return label, since or attempt.started_at


async def binding_info(
    session: AsyncSession, attempt: TestAttempt, test: Test, principal: Principal
) -> dict[str, Any]:
    limit = await max_rebinds(session, attempt.user_id)
    overrides = await rebind_overrides(session, attempt.id)
    proctored = test.test_kind == "drive" or bool(test.integrity_settings.get("single_device_binding"))
    remaining = max(0, limit + overrides - attempt.rebind_count)
    if proctored:
        remaining = max(0, overrides - attempt.rebind_count)
    return {
        "rebinds_remaining": remaining,
        "rebind_allowed": remaining > 0,
        "otp_required": principal.restriction_level >= await otp_level(session, attempt.user_id),
        "trainer_override_required": proctored and remaining == 0,
    }


async def answered_count(session: AsyncSession, attempt_id: uuid.UUID) -> int:
    return int(
        (
            await session.execute(
                select(func.count()).where(
                    AttemptResponse.attempt_id == attempt_id, AttemptResponse.response.is_not(None)
                )
            )
        ).scalar_one()
    )


async def ensure_bound(
    session: AsyncSession,
    principal: Principal,
    attempt: TestAttempt,
    test: Test,
    *,
    read_only_summary: bool = False,
) -> bool:
    """Enforce single-session binding. Returns True when the attempt was re-attached to this
    session (same device). Raises ``409 attempt_bound_elsewhere`` for another device."""
    if attempt.status != "in_progress" or attempt.bound_session_id == principal.session_id:
        return False
    if principal.device_id is not None and principal.device_id == attempt.bound_device_id:
        previous = attempt.bound_session_id
        attempt.bound_session_id = principal.session_id
        await hold_session(session, principal.session_id, attempt, test)
        await add_event(
            session,
            attempt,
            "reattach_same_device",
            principal=principal,
            payload={"previous_session_id": str(previous) if previous else None},
        )
        await session.flush()
        return True
    label, since = await _bound_label(session, attempt)
    ext: dict[str, Any] = {
        "bound_device_label": label,
        "bound_since": to_rfc3339(since),
        **await binding_info(session, attempt, test, principal),
    }
    if read_only_summary:
        ext["read_only"] = {
            "answered_count": await answered_count(session, attempt.id),
            "deadline_at": iso(attempt.deadline_at),
            "server_now": to_rfc3339(utcnow()),
        }
    raise ProblemError(
        "attempt_bound_elsewhere",
        title="This test is open on another device",
        detail=f"This test is open on {label}. Continue here?",
        **ext,
    )


# --------------------------------------------------------------------------- expiry / sections


def closes_at(attempt: TestAttempt, test: Test) -> datetime | None:
    if attempt.deadline_at is None:
        return None
    return attempt.deadline_at + timedelta(seconds=test.grace_seconds)


async def expire_if_due(
    session: AsyncSession, attempt: TestAttempt, test: Test, now: datetime | None = None
) -> bool:
    """Close an in-progress attempt whose deadline + grace has passed. True if it is closed."""
    if attempt.status != "in_progress":
        return True
    c = closes_at(attempt, test)
    if c is None or (now or utcnow()) <= c:
        return False
    await finalize(session, attempt, test, "deadline")
    return True


async def advance_sections(
    session: AsyncSession, attempt: TestAttempt, test: Test, now: datetime
) -> list[AttemptSection]:
    """Sequential/section-locked tests: time out sections past their deadline (+grace) and start
    the next one on the server timeline (it starts when the previous one ended)."""
    secs = await attempt_sections(session, attempt.id)
    if test.navigation_mode == "free":
        return secs
    grace = timedelta(seconds=test.grace_seconds)
    changed = True
    while changed:
        changed = False
        active = next((s for s in secs if s.status == "active"), None)
        if active is None or active.deadline_at is None or now <= active.deadline_at + grace:
            break
        active.status = "timed_out"
        active.submitted_at = active.deadline_at
        nxt = next((s for s in secs if s.status == "not_started" and s.position > active.position), None)
        if nxt is not None:
            _activate(attempt, nxt, active.deadline_at)
            changed = True
    await session.flush()
    if attempt.status == "in_progress" and secs and all(s.status in ("submitted", "timed_out") for s in secs):
        # BE-10: the last section timed out with no section left -> auto-submit now, stamped at
        # the end of that section (nothing is writable any more).
        last_end = max((s.submitted_at for s in secs if s.submitted_at is not None), default=None)
        await finalize(session, attempt, test, "deadline", submitted_at=last_end)
    return secs


def _section_duration(attempt: TestAttempt, section_id: uuid.UUID) -> int | None:
    for s in attempt.layout["sections"]:
        if s["section_id"] == str(section_id):
            d = s.get("duration_seconds")
            return int(d) if d else None
    return None


def _activate(attempt: TestAttempt, sec: AttemptSection, at: datetime) -> None:
    sec.status = "active"
    sec.started_at = at
    dur = _section_duration(attempt, sec.test_section_id)
    dl = at + timedelta(seconds=dur) if dur else attempt.deadline_at
    if dl is not None and attempt.deadline_at is not None:
        dl = min(dl, attempt.deadline_at)
    sec.deadline_at = dl
    attempt.current_section_id = sec.test_section_id


async def enter_section(
    session: AsyncSession, principal: Principal, attempt: TestAttempt, test: Test, section_id: uuid.UUID
) -> None:
    now = utcnow()
    secs = await advance_sections(session, attempt, test, now)
    target = next((s for s in secs if s.test_section_id == section_id), None)
    if target is None:
        raise ProblemError("not_found")
    if test.navigation_mode == "free":
        attempt.current_section_id = section_id
    elif target.status == "active":
        pass
    elif target.status in ("submitted", "timed_out"):
        raise ProblemError("section_locked", section_id=str(section_id))
    else:
        earlier_open = [
            s for s in secs if s.position < target.position and s.status in ("active", "not_started")
        ]
        if any(s.status == "not_started" for s in earlier_open):
            raise ProblemError(
                "section_locked", section_id=str(section_id), detail="Sections are taken in order."
            )
        for s in earlier_open:  # the active one: moving on submits it (no return)
            s.status = "submitted"
            s.submitted_at = now
            await add_event(
                session,
                attempt,
                "section_submit",
                principal=principal,
                payload={"section_id": str(s.test_section_id), "implicit": True},
            )
        _activate(attempt, target, now)
    await add_event(
        session, attempt, "section_enter", principal=principal, payload={"section_id": str(section_id)}
    )
    attempt.last_seen_at = now
    await session.flush()


async def submit_section(
    session: AsyncSession, principal: Principal, attempt: TestAttempt, test: Test, section_id: uuid.UUID
) -> None:
    now = utcnow()
    secs = await advance_sections(session, attempt, test, now)
    target = next((s for s in secs if s.test_section_id == section_id), None)
    if target is None:
        raise ProblemError("not_found")
    if test.navigation_mode == "free":
        raise ProblemError(
            "invalid_state_transition", detail="Sections of this test are not submitted separately."
        )
    if target.status != "active":
        raise ProblemError("section_locked", section_id=str(section_id))
    target.status = "submitted"
    target.submitted_at = now
    await add_event(
        session, attempt, "section_submit", principal=principal, payload={"section_id": str(section_id)}
    )
    nxt = next((s for s in secs if s.status == "not_started" and s.position > target.position), None)
    if nxt is not None:
        _activate(attempt, nxt, now)
        await add_event(
            session,
            attempt,
            "section_enter",
            principal=principal,
            payload={"section_id": str(nxt.test_section_id)},
        )
        await session.flush()
    else:
        await finalize(session, attempt, test, "section_end")


# --------------------------------------------------------------------------- autosave


def _bad_text(message: str, *, code: str = "invalid", status: int = 400) -> ProblemError:
    """400 for a malformed answer; 422 for a well-formed one the question's settings reject
    (api-specification §2.1: 422 ``validation_failed`` = semantically invalid input)."""
    return ProblemError(
        "validation_failed", status, errors=[{"field": "response.text", "code": code, "message": message}]
    )


async def version_settings(session: AsyncSession, qv_ids: list[uuid.UUID]) -> dict[uuid.UUID, dict[str, Any]]:
    """Per-version non-key settings (``question_versions.settings``: poll ``allow_multiple``,
    word-cloud limits, essay ``max_words``) so response limits are enforced server-side."""
    from app.modules.placement.models import QuestionVersion

    if not qv_ids:
        return {}
    rows = await session.execute(
        select(QuestionVersion.id, QuestionVersion.settings).where(QuestionVersion.id.in_(set(qv_ids)))
    )
    return {qv: dict(st or {}) for qv, st in rows.all()}


def normalise_manual(response: Any, settings: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """Free-text answer (``descriptive``/``essay``/``short_answer``): ``{"text": "..."}``;
    ``settings.max_words`` (essay / short answer) is enforced."""
    if response is None:
        return None
    if not isinstance(response, dict):
        raise _bad_text("must be an object")
    raw = response.get("text", response.get("value"))
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return None
    if not isinstance(raw, str):
        raise _bad_text("must be a string")
    if len(raw) > MAX_MANUAL_CHARS:
        raise _bad_text("too long")
    max_words = (settings or {}).get("max_words")
    if isinstance(max_words, int) and not isinstance(max_words, bool) and len(raw.split()) > max_words:
        raise _bad_text(f"At most {max_words} words", code="too_many_words", status=422)
    return {"text": raw}


async def _write_items(
    session: AsyncSession,
    principal: Principal,
    attempt: TestAttempt,
    secs: list[AttemptSection],
    items: list[AutosaveItem],
    now: datetime,
) -> None:
    index = layout_index(attempt)
    open_sections = {str(s.test_section_id) for s in secs if s.status == "active"}
    qv_ids = []
    for i, it in enumerate(items):
        entry = index.get(str(it.question_version_id))
        if entry is None:
            raise ProblemError(
                "validation_failed",
                errors=[
                    {
                        "field": f"items.{i}.question_version_id",
                        "code": "invalid",
                        "message": "question is not part of this attempt",
                    }
                ],
            )
        if entry[0] not in open_sections:
            raise ProblemError("section_locked", section_id=entry[0])
        qv_ids.append(it.question_version_id)
    shapes = await bank.load_answer_shapes(session, qv_ids)
    settings = await version_settings(session, qv_ids)
    normalised = [
        normalise_manual(it.response, settings.get(it.question_version_id))
        if shapes[it.question_version_id].qtype in MANUAL_TYPES
        else grading.normalise_response(
            shapes[it.question_version_id].qtype,
            it.response,
            set(shapes[it.question_version_id].option_ids),
            settings.get(it.question_version_id),
        )
        for it in items
    ]
    for it, resp in zip(items, normalised, strict=True):
        shape = shapes[it.question_version_id]
        if shape.qtype == grading.CODING_TYPE:
            from app.modules.assessments.coding import check_pinned_submission

            await check_pinned_submission(session, attempt, shape.coding_problem_id, resp)
    # One multi-row upsert per save (not one statement per item). Postgres refuses to touch the
    # same row twice in one statement, so a batch keeps the newest client_seq per question: the
    # outcome equals applying the items one by one in client_seq order.
    latest: dict[uuid.UUID, tuple[AutosaveItem, dict[str, Any] | None]] = {}
    for it, resp in zip(items, normalised, strict=True):
        prev = latest.get(it.question_version_id)
        if prev is None or it.client_seq > prev[0].client_seq:
            latest[it.question_version_id] = (it, resp)
    if not latest:
        return
    stmt = pg_insert(AttemptResponse).values(
        [
            {
                "id": uuid7(),
                "attempt_id": attempt.id,
                "user_id": attempt.user_id,
                "organization_id": attempt.organization_id,
                "test_section_id": uuid.UUID(index[str(qv)][0]),
                "question_version_id": qv,
                "response": resp,
                "client_seq": it.client_seq,
                "flagged": it.flagged,
                "time_spent_ms": it.time_spent_ms,
                "first_answered_at": now if resp is not None else None,
                "saved_at": now,
            }
            for qv, (it, resp) in latest.items()
        ]
    )
    ex = stmt.excluded
    upsert = stmt.on_conflict_do_update(
        index_elements=[AttemptResponse.attempt_id, AttemptResponse.question_version_id],
        set_={
            "response": ex.response,
            "client_seq": ex.client_seq,
            "flagged": ex.flagged,
            "time_spent_ms": ex.time_spent_ms,
            "saved_at": ex.saved_at,
            "first_answered_at": func.coalesce(AttemptResponse.first_answered_at, ex.first_answered_at),
        },
        where=AttemptResponse.client_seq < ex.client_seq,
    ).returning(AttemptResponse.question_version_id)
    applied = set((await session.execute(upsert)).scalars())
    for qv, (it, resp) in latest.items():
        if qv in applied:
            await add_event(
                session,
                attempt,
                "answer_saved" if resp is not None else "answer_cleared",
                principal=principal,
                question_version_id=qv,
                client_seq=it.client_seq,
                at=now,
                payload={"flagged": it.flagged},
            )


async def autosave(
    session: AsyncSession, principal: Principal, attempt: TestAttempt, test: Test, body: AutosaveIn
) -> dict[str, Any]:
    now = utcnow()
    secs = await advance_sections(session, attempt, test, now)
    if attempt.status != "in_progress":
        raise ProblemError(
            "attempt_closed", attempt_status=attempt.status, deadline_at=iso(attempt.deadline_at)
        )
    await _write_items(session, principal, attempt, secs, body.items, now)
    ignored_events = 0
    protocol = exam.protocol_of(test)
    integrity: dict[str, Any] | None = None
    if body.events:
        if not attempt.layout.get("integrity_consent"):
            ignored_events = len(body.events)  # collected only with assessment_integrity consent
        else:
            accepted = (
                set(protocol.record_events) | CONNECTIVITY_EVENTS
                if protocol.exam_mode
                else LEGACY_CLIENT_EVENTS
            )
            counts = (await exam.event_counts(session, [attempt.id]))[attempt.id]
            stored = sum(counts.values())
            stored_conn = await exam.connectivity_event_count(session, attempt.id, CONNECTIVITY_EVENTS)
            existing: set[tuple[str, int | None]] = {
                (str(r[0]), r[1])
                for r in (
                    await session.execute(
                        select(AttemptEvent.event_type, AttemptEvent.client_seq).where(
                            AttemptEvent.attempt_id == attempt.id,
                            AttemptEvent.client_seq.in_([e.client_seq for e in body.events]),
                        )
                    )
                ).all()
            }
            for e in body.events:
                if (e.type, e.client_seq) in existing:
                    continue
                recordable = e.type not in CONNECTIVITY_EVENTS
                over_cap = (
                    stored >= exam.MAX_EVENTS_PER_ATTEMPT
                    if recordable
                    else stored_conn >= exam.MAX_CONNECTIVITY_EVENTS_PER_ATTEMPT
                )
                if e.type not in accepted or over_cap:
                    ignored_events += 1
                    continue
                existing.add((e.type, e.client_seq))
                if recordable:
                    stored += 1
                    counts[e.type] = counts.get(e.type, 0) + 1
                else:
                    stored_conn += 1
                await add_event(
                    session,
                    attempt,
                    e.type,
                    principal=principal,
                    client_seq=e.client_seq,
                    at=now,
                    payload={"client_at": iso(e.client_at), "advisory": True},
                )
            if protocol.exam_mode:
                integrity = await _apply_protocol(session, principal, attempt, test, protocol, counts)
    if body.current_section_id is not None and test.navigation_mode == "free":
        if any(s.test_section_id == body.current_section_id for s in secs):
            attempt.current_section_id = body.current_section_id
    attempt.last_seen_at = now
    await session.flush()
    seqs = [i.client_seq for i in body.items] + [e.client_seq for e in body.events]
    active = next((s for s in secs if s.test_section_id == attempt.current_section_id), None)
    if integrity is None and protocol.exam_mode:
        integrity = await exam.attempt_summary(session, attempt, test)
    out: dict[str, Any] = {
        "acked_seq": max(seqs) if seqs else None,
        "server_now": to_rfc3339(now),
        "deadline_at": iso(attempt.deadline_at),
        "section_deadline_at": iso(active.deadline_at) if active else None,
        "status": attempt.status,
        "ignored_events": ignored_events,
    }
    if integrity is not None:
        out["integrity"] = integrity
    return out


async def _apply_protocol(
    session: AsyncSession,
    principal: Principal,
    attempt: TestAttempt,
    test: Test,
    protocol: exam.Protocol,
    counts: dict[str, int],
) -> dict[str, Any]:
    """Server-side verdict on the evidence: flag for staff review at the threshold (never a
    penalty) and, only when the author opted in, end the attempt after N recorded events."""
    summary = exam.summarize(protocol, counts, attempt.integrity_status)
    if exam.should_flag(protocol, summary) and attempt.integrity_status == "none":
        attempt.integrity_status = "review_recommended"
        await add_event(
            session,
            attempt,
            "integrity_flagged",
            principal=principal,
            payload={"counts": summary["counts"], "total": summary["total"], "source": "exam_protocol"},
        )
        summary = exam.summarize(protocol, counts, attempt.integrity_status)
    if exam.should_auto_submit(protocol, summary) and attempt.status == "in_progress":
        await finalize(session, attempt, test, "integrity_limit", principal)
    return summary


# --------------------------------------------------------------------------- submit / scoring


async def finalize(
    session: AsyncSession,
    attempt: TestAttempt,
    test: Test,
    reason: str,
    principal: Principal | None = None,
    *,
    submitted_at: datetime | None = None,
) -> None:
    """in_progress -> submitted/auto_submitted, then score (idempotent)."""
    if attempt.status != "in_progress":
        return
    now = utcnow()
    auto = reason != "user"
    attempt.status = "auto_submitted" if auto else "submitted"
    attempt.submit_reason = reason
    if submitted_at is not None:
        attempt.submitted_at = min(now, submitted_at)
    else:
        attempt.submitted_at = (
            min(now, attempt.deadline_at) if reason == "deadline" and attempt.deadline_at else now
        )
    for s in await attempt_sections(session, attempt.id):
        if s.status == "active":
            s.status = "timed_out" if reason == "deadline" else "submitted"
            s.submitted_at = attempt.submitted_at
    await add_event(
        session,
        attempt,
        "auto_submit" if auto else "submit",
        principal=principal,
        at=now,
        payload={"submit_reason": reason},
    )
    await session.flush()
    await emit_event(
        session,
        "attempt.submitted",
        {
            "attempt_id": str(attempt.id),
            "test_id": str(attempt.test_id),
            "user_id": str(attempt.user_id),
            "attempt_no": attempt.attempt_no,
            "submitted_at": to_rfc3339(attempt.submitted_at),
            "submit_reason": reason,
            "auto": auto,
        },
        aggregate_type="test_attempt",
        aggregate_id=attempt.id,
        organization_id=attempt.organization_id,
    )
    await score_attempt(session, attempt, test)


async def _manual_grades(session: AsyncSession, attempt_id: uuid.UUID) -> dict[uuid.UUID, Any]:
    from app.modules.assessments.models import AttemptItemGrade

    rows = await session.execute(select(AttemptItemGrade).where(AttemptItemGrade.attempt_id == attempt_id))
    return {g.question_version_id: g for g in rows.scalars()}


async def score_attempt(
    session: AsyncSession, attempt: TestAttempt, test: Test, scoring_version: int = 1
) -> AttemptResult:
    existing = await session.get(AttemptResult, attempt.id)
    if existing is not None and existing.scoring_version >= scoring_version:
        return existing
    responses = {
        r.question_version_id: r
        for r in (
            await session.execute(select(AttemptResponse).where(AttemptResponse.attempt_id == attempt.id))
        ).scalars()
    }
    index = layout_index(attempt)
    bundles = await bank.load_bundles(session, [uuid.UUID(k) for k in index])
    manual = await _manual_grades(session, attempt.id)
    pending_manual = 0
    total = max_total = Decimal("0")
    correct_n = incorrect_n = unanswered_n = 0
    section_scores = []
    topic: dict[str, dict[str, Any]] = defaultdict(lambda: {"correct": 0, "total": 0, "time_ms": 0})
    for sec in attempt.layout["sections"]:
        s_score = s_max = Decimal("0")
        s_time = 0
        for it in sec["items"]:
            qv = uuid.UUID(it["qv"])
            b = bundles[qv]
            r = responses.get(qv)
            resp = r.response if r is not None else None
            if b.qtype in MANUAL_TYPES:
                g = manual.get(qv)
                if resp is None:
                    ok, m = None, Decimal("0")
                elif g is not None and g.final_marks is not None:
                    m = _q2(min(g.final_marks, Decimal(it["marks"])))
                    ok = m > 0
                else:
                    pending_manual += 1
                    ok, m = None, Decimal("0")
                    if r is not None:
                        r.is_correct = None
                        r.marks_awarded = None
                        s_time += r.time_spent_ms
                    s_max += Decimal(it["marks"])
                    t = topic[it["topic"]]
                    t["total"] += 1
                    t["time_ms"] += r.time_spent_ms if r is not None else 0
                    continue
            elif b.qtype == grading.CODING_TYPE:
                from app.modules.assessments.coding import coding_outcome

                ok, frac = await coding_outcome(session, attempt, b.version.coding_problem_id, resp)
                m = _q2(Decimal(it["marks"]) * frac) if ok is not None else Decimal("0")
            else:
                ok = grading.is_correct(b.qtype, resp, b.correct_option_ids, b.version.answer_key)
                m = grading.marks_for(ok, Decimal(it["marks"]), Decimal(it["neg"]))
            if r is not None:
                r.is_correct = ok
                r.marks_awarded = m
                s_time += r.time_spent_ms
            s_score += m
            s_max += Decimal(it["marks"])
            if ok is None:
                unanswered_n += 1
            elif ok:
                correct_n += 1
            else:
                incorrect_n += 1
            t = topic[it["topic"]]
            t["total"] += 1
            t["correct"] += 1 if ok else 0
            t["time_ms"] += r.time_spent_ms if r is not None else 0
        total += s_score
        max_total += s_max
        section_scores.append(
            {
                "section_id": sec["section_id"],
                "title": sec["title"],
                "score": str(_q2(s_score)),
                "max": str(_q2(s_max)),
                "time_s": s_time // 1000,
            }
        )
    pct = _q2(total / max_total * 100) if max_total > 0 else Decimal("0")
    pct = max(Decimal("-999.99"), min(Decimal("100"), pct))
    a = await session.get(TestAssignment, attempt.test_assignment_id) if attempt.test_assignment_id else None
    released_at = attempt.submitted_at if a is None or a.release_mode == "immediate" else None
    if pending_manual:
        released_at = None  # a person must finish grading before an immediate release
    if existing is not None and existing.released_at is not None:
        released_at = existing.released_at  # never un-release
    end = attempt.submitted_at or utcnow()
    values = {
        "user_id": attempt.user_id,
        "organization_id": attempt.organization_id,
        "test_id": attempt.test_id,
        "scoring_version": scoring_version,
        "score": _q2(total),
        "max_score": _q2(max_total),
        "percentage": pct,
        "correct_count": correct_n,
        "incorrect_count": incorrect_n,
        "unanswered_count": unanswered_n,
        "time_taken_seconds": max(0, int((end - attempt.started_at).total_seconds())),
        "section_scores": section_scores,
        "topic_scores": [
            {
                "topic_id": k,
                "correct": v["correct"],
                "total": v["total"],
                "avg_time_ms": v["time_ms"] // max(1, v["total"]),
            }
            for k, v in sorted(topic.items())
        ],
        "percentile": None,
        "rank": None,
        "rank_provisional": True,
        "passed": (pct >= test.pass_percentage) if test.pass_percentage is not None else None,
        "graded_at": utcnow(),
        "released_at": released_at,
    }
    if existing is None:
        result = AttemptResult(attempt_id=attempt.id, **values)
        session.add(result)
    else:
        result = existing
        for k, v in values.items():
            setattr(result, k, v)
    if attempt.status != "invalidated":
        attempt.status = "awaiting_manual" if pending_manual else "graded"
    await session.flush()
    await emit_event(
        session,
        "attempt.scored",
        {
            "attempt_id": str(attempt.id),
            "test_id": str(attempt.test_id),
            "user_id": str(attempt.user_id),
            "scoring_version": scoring_version,
            "score": str(result.score),
            "max_score": str(result.max_score),
            "percentage": str(result.percentage),
            "section_scores": section_scores,
            "topic_scores": values["topic_scores"],
        },
        aggregate_type="test_attempt",
        aggregate_id=attempt.id,
        organization_id=attempt.organization_id,
    )
    return result


async def submit(
    session: AsyncSession, principal: Principal, attempt: TestAttempt, test: Test, items: list[AutosaveItem]
) -> dict[str, Any]:
    if attempt.status == "in_progress":
        now = utcnow()
        secs = await advance_sections(session, attempt, test, now)
        if attempt.status == "in_progress":
            if items:
                await _write_items(session, principal, attempt, secs, items, now)
            await finalize(session, attempt, test, "user", principal)
    return await submitted_payload(session, attempt, test)


def release_info(
    attempt: TestAttempt, a: TestAssignment | None, now: datetime
) -> tuple[bool, str, datetime | None]:
    if a is None or a.release_mode == "immediate":
        return True, "immediate", attempt.submitted_at
    if a.release_mode == "after_window":
        return now >= a.available_until, "after_window", a.available_until
    at = a.results_release_at
    return (at is not None and now >= at), a.release_mode, at


async def submitted_payload(session: AsyncSession, attempt: TestAttempt, test: Test) -> dict[str, Any]:
    a = await session.get(TestAssignment, attempt.test_assignment_id) if attempt.test_assignment_id else None
    _, mode, at = release_info(attempt, a, utcnow())
    return {
        "attempt_id": str(attempt.id),
        "status": attempt.status,
        "submitted_at": iso(attempt.submitted_at),
        "submit_reason": attempt.submit_reason,
        "integrity_status": attempt.integrity_status,
        "integrity_flagged": attempt.integrity_status in ("review_recommended", "invalidated"),
        "result_release": {"mode": mode, "release_at": iso(at)},
        "redirect": f"/app/attempts/{attempt.id}/submitted",
        "server_now": to_rfc3339(utcnow()),
    }


# --------------------------------------------------------------------------- state payload


async def state_payload(
    session: AsyncSession, principal: Principal, attempt: TestAttempt, test: Test, *, reattached: bool = False
) -> dict[str, Any]:
    now = utcnow()
    base: dict[str, Any] = {
        "attempt_id": str(attempt.id),
        "attempt_no": attempt.attempt_no,
        "status": attempt.status,
        "test": {
            "id": str(test.id),
            "version": attempt.test_version,
            "title": test.title,
            "navigation_mode": test.navigation_mode,
            "grace_seconds": test.grace_seconds,
        },
        "protocol": exam.protocol_of(test).public(),
        "server_now": to_rfc3339(now),
        "started_at": iso(attempt.started_at),
        "deadline_at": iso(attempt.deadline_at),
    }
    if attempt.status != "in_progress":
        return {**base, **(await submitted_payload(session, attempt, test)), "sections": [], "responses": []}
    secs = {str(s.test_section_id): s for s in await attempt_sections(session, attempt.id)}
    visible_qvs = []
    for s in attempt.layout["sections"]:
        st = secs.get(s["section_id"])
        if test.navigation_mode == "free" or (st is not None and st.status == "active"):
            visible_qvs += [uuid.UUID(it["qv"]) for it in s["items"]]
    bundles = await bank.load_bundles(session, visible_qvs)
    sections_out = []
    for s in attempt.layout["sections"]:
        st = secs.get(s["section_id"])
        d: dict[str, Any] = {
            "section_id": s["section_id"],
            "title": s["title"],
            "position": s["position"],
            "status": st.status if st else "not_started",
            "deadline_at": iso(st.deadline_at) if st else None,
            "duration_seconds": s.get("duration_seconds"),
            "question_count": len(s["items"]),
        }
        if all(uuid.UUID(it["qv"]) in bundles for it in s["items"]) and (
            test.navigation_mode == "free" or (st is not None and st.status == "active")
        ):
            d["questions"] = [
                bank.delivery(
                    bundles[uuid.UUID(it["qv"])],
                    option_order=it["opts"],
                    marks=Decimal(it["marks"]),
                    negative=Decimal(it["neg"]),
                )
                for it in s["items"]
            ]
        sections_out.append(d)
    rows = (
        await session.execute(select(AttemptResponse).where(AttemptResponse.attempt_id == attempt.id))
    ).scalars()
    info = await binding_info(session, attempt, test, principal)
    out = {
        **base,
        "current_section_id": str(attempt.current_section_id) if attempt.current_section_id else None,
        "sections": sections_out,
        "responses": [
            {
                "question_version_id": str(r.question_version_id),
                "response": r.response,
                "client_seq": r.client_seq,
                "flagged": r.flagged,
                "saved_at": iso(r.saved_at),
            }
            for r in rows
        ],
        "binding": {"bound_session_id": "current", "rebinds_remaining": info["rebinds_remaining"]},
        "autosave": AUTOSAVE_POLICY,
        "integrity": await exam.attempt_summary(session, attempt, test),
    }
    if reattached:
        out["reattached"] = True
    return out


def time_payload(attempt: TestAttempt, sec: AttemptSection | None) -> dict[str, Any]:
    return {
        "attempt_id": str(attempt.id),
        "status": attempt.status,
        "server_now": to_rfc3339(utcnow()),
        "deadline_at": iso(attempt.deadline_at),
        "section_deadline_at": iso(sec.deadline_at) if sec else None,
        "current_section_id": str(attempt.current_section_id) if attempt.current_section_id else None,
    }


# --------------------------------------------------------------------------- rebind


async def rebind(
    session: AsyncSession,
    principal: Principal,
    attempt: TestAttempt,
    test: Test,
    *,
    otp_code: str | None,
) -> dict[str, Any]:
    """ATT-05. Raises on refusal; callers persist ``rebind_refused`` events via ``commit_problem``."""
    if attempt.status != "in_progress":
        raise ProblemError(
            "attempt_closed", attempt_status=attempt.status, deadline_at=iso(attempt.deadline_at)
        )
    if principal.restriction_level >= 3:
        raise ProblemError("account_restricted", level=principal.restriction_level)
    if attempt.bound_session_id == principal.session_id:
        return await state_payload(session, principal, attempt, test)
    if principal.device_id is not None and principal.device_id == attempt.bound_device_id:
        await ensure_bound(session, principal, attempt, test)
        return await state_payload(session, principal, attempt, test, reattached=True)
    await add_event(session, attempt, "rebind_requested", principal=principal)
    info = await binding_info(session, attempt, test, principal)
    if not info["rebind_allowed"]:
        await add_event(
            session,
            attempt,
            "rebind_refused",
            principal=principal,
            payload={"reason": "trainer_override_required" if info["trainer_override_required"] else "limit"},
        )
        await session.flush()
        if info["trainer_override_required"]:
            raise ProblemError(
                "permission_denied",
                detail="This test allows switching devices only with your trainer's approval.",
                trainer_override_required=True,
            )
        raise ProblemError("rebind_limit_reached", rebinds_remaining=0)
    if info["otp_required"]:
        if not otp_code:
            await add_event(
                session, attempt, "rebind_refused", principal=principal, payload={"reason": "otp_required"}
            )
            await session.flush()
            raise ProblemError(
                "validation_failed",
                detail="Enter the code we sent to confirm it's you.",
                otp_required=True,
                errors=[
                    {"field": "otp_code", "code": "otp_required", "message": "a one-time code is required"}
                ],
            )
        from app.modules.identity.service import check_otp

        res = await check_otp(
            session,
            purpose="attempt_rebind",
            code=otp_code,
            user_id=principal.user_id,
            auth_session_id=principal.session_id,
        )
        if not res.ok:
            await add_event(
                session, attempt, "rebind_refused", principal=principal, payload={"reason": "otp_invalid"}
            )
            await session.flush()
            assert res.problem is not None
            raise res.problem
    previous = (attempt.bound_session_id, attempt.bound_device_id)
    attempt.bound_session_id = principal.session_id
    attempt.bound_device_id = principal.device_id
    attempt.rebind_count += 1
    await hold_session(session, principal.session_id, attempt, test)
    await add_event(
        session,
        attempt,
        "rebind",
        principal=principal,
        payload={
            "previous_session_id": str(previous[0]) if previous[0] else None,
            "previous_device_id": str(previous[1]) if previous[1] else None,
            "rebind_count": attempt.rebind_count,
        },
    )
    await session.flush()
    return await state_payload(session, principal, attempt, test)


async def send_rebind_otp(
    session: AsyncSession, principal: Principal, attempt: TestAttempt, test: Test
) -> dict[str, Any]:
    info = await binding_info(session, attempt, test, principal)
    if not info["otp_required"]:
        return {"otp_required": False, "sent": False}
    from app.modules.identity.models import User
    from app.modules.identity.service import create_otp, otp_send_allowed
    from app.modules.notifications.service import send_email, send_sms

    user = await session.get(User, principal.user_id)
    if user is None:  # pragma: no cover
        raise ProblemError("not_found")
    channel, dest = ("sms", user.phone_e164) if user.phone_e164 else ("email", user.email)
    if not dest:
        raise ProblemError("contact_not_verified")
    wait = await otp_send_allowed(session, channel, dest)
    if wait:
        raise ProblemError("otp_send_limited", headers={"Retry-After": str(wait)}, retry_after_seconds=wait)
    _tok, code = await create_otp(
        session,
        purpose="attempt_rebind",
        channel=channel,
        destination=dest,
        user_id=principal.user_id,
        auth_session_id=principal.session_id,
        device_id=principal.device_id,
    )
    text = f"Your Tech Drona code to continue your test on this device is {code}. It expires in 5 minutes."
    if channel == "sms":
        await send_sms(dest, text, template_key="attempt_rebind_otp")
    else:
        await send_email(dest, "Continue your test on this device", text, template_key="attempt_rebind_otp")
    return {"otp_required": True, "sent": True, "channel": channel}


# --------------------------------------------------------------------------- results / review


def phase_of(
    attempt: TestAttempt,
    test: Test,
    a: TestAssignment | None,
    now: datetime,
    *,
    test_close: datetime | None = None,
    close_known: bool = False,
) -> str:
    """``after_close`` only once the test is closed for every eligible learner (BE-04): other
    assignments' windows, window extensions and still-running attempts all count (``test_close``
    from :func:`test_closes_at`). ``review_policy.release_at`` cannot release keys earlier."""
    if attempt.status == "in_progress":
        return "during"
    close = test_close if close_known else (a.available_until if a is not None else test.available_until)
    release: datetime | None = None
    rp_release = test.review_policy.get("release_at")
    if rp_release:
        try:
            release = datetime.fromisoformat(str(rp_release).replace("Z", "+00:00"))
        except ValueError:
            release = None
    if close is not None:
        if now >= close and (release is None or now >= release):
            return "after_close"
        return "after_submit"
    if release is not None and now >= release:
        return "after_close"
    return "after_submit"


async def test_closes_at(
    session: AsyncSession, principal: Principal | None, test: Test, a: TestAssignment | None
) -> datetime | None:
    """Latest moment any eligible learner can still start or continue ``test`` (BE-04).

    Assignment-based attempt: max over every assignment of the test of ``available_until`` plus
    the window extensions that can apply to it (upper bound: their sum), and the test's own window
    when set. Direct (entitlement) attempt: the test window. Running attempts of anyone extend it
    to their deadline + grace; a running attempt without a deadline keeps it open (``None``).
    ``None`` = open-ended. Reads across users and orgs, so it runs as a named system job and the
    principal's RLS context is restored immediately."""
    if principal is not None:
        await session.flush()
    ctx = (
        system_context(session, "assessments.test_close")
        if principal is not None
        else contextlib.nullcontext()
    )
    async with ctx:
        assigns = list(
            (await session.execute(select(TestAssignment).where(TestAssignment.test_id == test.id))).scalars()
        )
        overrides = list(
            (
                await session.execute(
                    select(AttemptOverride).where(
                        AttemptOverride.test_id == test.id, AttemptOverride.window_extension_seconds > 0
                    )
                )
            ).scalars()
        )
        running = (
            await session.execute(
                select(
                    func.max(TestAttempt.deadline_at),
                    func.count().filter(TestAttempt.deadline_at.is_(None)),
                ).where(TestAttempt.test_id == test.id, TestAttempt.status == "in_progress")
            )
        ).one()
    if running[1]:
        return None
    candidates: list[datetime] = []
    if a is None or not assigns:
        if test.available_until is None:
            return None
        candidates.append(test.available_until)
    else:
        if test.available_until is not None:
            candidates.append(test.available_until)
        for x in assigns:
            ext = sum(
                o.window_extension_seconds
                for o in overrides
                if o.test_assignment_id in (None, x.id) and (o.batch_id is None or o.batch_id == x.batch_id)
            )
            candidates.append(x.available_until + timedelta(seconds=ext))
    if running[0] is not None:
        candidates.append(running[0] + timedelta(seconds=test.grace_seconds))
    return max(candidates)


def visibility(test: Test, phase: str) -> dict[str, bool]:
    keys = ("score", "correctness", "answer_key", "explanation", "section_analytics", "rank")
    raw = test.review_policy.get(phase) or {}
    vis = {k: bool(raw.get(k, False)) for k in keys}
    if phase == "during":
        vis.update(correctness=False, answer_key=False, explanation=False)
    return vis


async def result_payload(
    session: AsyncSession,
    attempt: TestAttempt,
    test: Test,
    *,
    staff: bool,
    principal: Principal | None = None,
) -> dict[str, Any]:
    now = utcnow()
    if attempt.status == "in_progress":
        raise ProblemError("results_not_released", release_mode="after_submit", release_at=None)
    a = await session.get(TestAssignment, attempt.test_assignment_id) if attempt.test_assignment_id else None
    released, mode, at = release_info(attempt, a, now)
    if not released and not staff:
        raise ProblemError("results_not_released", release_mode=mode, release_at=iso(at))
    res = await session.get(AttemptResult, attempt.id)
    close = await test_closes_at(session, principal, test, a)
    phase = phase_of(attempt, test, a, now, test_close=close, close_known=True)
    vis = (
        {
            "score": True,
            "correctness": True,
            "answer_key": False,
            "explanation": False,
            "section_analytics": True,
            "rank": True,
        }
        if staff
        else visibility(test, phase)
    )
    out: dict[str, Any] = {
        "attempt_id": str(attempt.id),
        "status": attempt.status,
        "phase": phase,
        "visible": vis,
        "submitted_at": iso(attempt.submitted_at),
        "submit_reason": attempt.submit_reason,
        "integrity_status": attempt.integrity_status,
        "released_at": iso(res.released_at or (at if released else None)) if res else None,
    }
    if attempt.status == "invalidated":
        out["appeal_url"] = f"/app/attempts/{attempt.id}/appeal"
        return out
    if res is None:
        return out
    if vis["score"]:
        out.update(
            score=float(res.score),
            max_score=float(res.max_score),
            percentage=float(res.percentage),
            time_taken_seconds=res.time_taken_seconds,
            passed=res.passed,
        )
    if vis["correctness"]:
        out.update(
            correct_count=res.correct_count,
            incorrect_count=res.incorrect_count,
            unanswered_count=res.unanswered_count,
        )
    if vis["section_analytics"]:
        out["section_scores"] = res.section_scores
        out["topic_scores"] = res.topic_scores
    if vis["rank"]:
        out.update(
            rank=res.rank,
            percentile=None,
            percentile_note="insufficient_cohort",
            rank_provisional=res.rank_provisional,
        )
    return out


async def review_payload(
    session: AsyncSession,
    attempt: TestAttempt,
    test: Test,
    *,
    staff: bool,
    staff_keys: bool,
    principal: Principal | None = None,
) -> dict[str, Any]:
    now = utcnow()
    if attempt.status == "in_progress":
        raise ProblemError("results_not_released", release_mode="after_submit", release_at=None)
    a = await session.get(TestAssignment, attempt.test_assignment_id) if attempt.test_assignment_id else None
    released, mode, at = release_info(attempt, a, now)
    if not released and not staff:
        raise ProblemError("results_not_released", release_mode=mode, release_at=iso(at))
    close = await test_closes_at(session, principal, test, a)
    phase = phase_of(attempt, test, a, now, test_close=close, close_known=True)
    if staff:
        vis = {"correctness": True, "answer_key": staff_keys, "explanation": staff_keys}
    else:
        vis = visibility(test, phase)
    index = layout_index(attempt)
    bundles = await bank.load_bundles(session, [uuid.UUID(k) for k in index])
    responses = {
        r.question_version_id: r
        for r in (
            await session.execute(select(AttemptResponse).where(AttemptResponse.attempt_id == attempt.id))
        ).scalars()
    }
    sections = []
    for s in attempt.layout["sections"]:
        qs = []
        for it in s["items"]:
            qv = uuid.UUID(it["qv"])
            b = bundles[qv]
            r = responses.get(qv)
            item: dict[str, Any] = {
                **bank.delivery(
                    b, option_order=it["opts"], marks=Decimal(it["marks"]), negative=Decimal(it["neg"])
                ),
                "your_response": r.response if r else None,
                "time_spent_ms": r.time_spent_ms if r else 0,
                "flagged": r.flagged if r else False,
            }
            if b.qtype == grading.CODING_TYPE:
                from app.modules.assessments.coding import coding_review

                item["your_submission"] = await coding_review(
                    session,
                    attempt,
                    b.version.coding_problem_id,
                    r.response if r else None,
                    with_verdicts=vis["correctness"],
                )
            if vis["correctness"]:
                item["is_correct"] = r.is_correct if r else None
                item["marks_awarded"] = float(r.marks_awarded) if r and r.marks_awarded is not None else 0.0
            if vis["answer_key"] or vis["explanation"]:
                keys = bank.key_payload(b)
                if vis["answer_key"]:
                    for k in ("correct_option_ids", "correct_answer"):
                        if k in keys:
                            item[k] = keys[k]
                if vis["explanation"]:
                    item["explanation_html"] = keys["explanation_html"]
            qs.append(item)
        sections.append({"section_id": s["section_id"], "title": s["title"], "questions": qs})
    return {"attempt_id": str(attempt.id), "phase": phase, "visible": vis, "sections": sections}


# --------------------------------------------------------------------------- sessions hook


async def sessions_holding_attempts(session: AsyncSession, ids: list[uuid.UUID]) -> set[uuid.UUID]:
    """``sessions.register_active_attempt_lookup``: sessions bound to an in-progress attempt are
    never auto-evicted by the session cap (AUTH-06)."""
    rows = await session.execute(
        select(TestAttempt.bound_session_id).where(
            TestAttempt.bound_session_id.in_(ids), TestAttempt.status == "in_progress"
        )
    )
    return {r for (r,) in rows.all() if r is not None}
