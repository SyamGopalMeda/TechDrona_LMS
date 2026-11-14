"""Test report (api-specification ASM-22): score distribution, submit vs auto-submit, average
section time and item analysis (difficulty p-value, point-biserial discrimination).

Item statistics are suppressed below the analytics k-floor (``K_MIN_ITEM``, 10): the whole item
table when fewer than k graded attempts are in scope, and any single item answered by fewer than
k of them. Content managers (platform ``test.results.read`` without an org/batch role) get item
statistics only — no per-cohort distribution or timing.
"""

from __future__ import annotations

import math
import statistics
import uuid
from typing import Any

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ProblemError
from app.core.principal import Principal
from app.modules.assessments import datastore as adb
from app.modules.assessments.integrity import Scope, scope_of
from app.modules.assessments.models import AttemptResponse, AttemptResult, Test, TestAttempt, TestSection

try:  # analytics k-floor policy (import only; fall back to the documented default)
    from app.modules.analytics.params import K_MIN_ITEM as _K_MIN_ITEM
except ImportError:  # pragma: no cover
    _K_MIN_ITEM = 10

K_MIN_ITEM: int = _K_MIN_ITEM
BUCKET_WIDTH = 10  # percentage points per distribution bucket
GRADED_STATUSES = ("submitted", "auto_submitted", "grading", "awaiting_manual", "graded")
AUTO_REASONS = ("deadline", "section_end", "session_end")


def _r(x: float | None, nd: int = 3) -> float | None:
    return None if x is None else round(x, nd)


def point_biserial(xs: list[int], totals: list[float]) -> float | None:
    """r_pb between a 0/1 item score and the total score (population SD)."""
    n = len(xs)
    if n < 2:
        return None
    ones = [t for x, t in zip(xs, totals, strict=True) if x]
    zeros = [t for x, t in zip(xs, totals, strict=True) if not x]
    if not ones or not zeros:
        return None
    sd = statistics.pstdev(totals)
    if sd == 0:
        return None
    p = len(ones) / n
    return (statistics.fmean(ones) - statistics.fmean(zeros)) / sd * math.sqrt(p * (1 - p))


def _distribution(pcts: list[float]) -> dict[str, Any]:
    buckets = []
    for lo in range(0, 100, BUCKET_WIDTH):
        hi = lo + BUCKET_WIDTH
        count = sum(1 for p in pcts if lo <= p < hi or (hi == 100 and p == 100))
        buckets.append({"label": f"{lo}-{hi}", "from": lo, "to": hi, "count": count})
    return {
        "buckets": buckets,
        "mean": _r(statistics.fmean(pcts), 2) if pcts else None,
        "median": _r(statistics.median(pcts), 2) if pcts else None,
    }


def _in_scope(att: TestAttempt, scope: Scope) -> bool:
    return (
        scope.platform
        or (att.organization_id is not None and att.organization_id in scope.orgs)
        or (att.batch_id is not None and att.batch_id in scope.batches)
    )


async def build_report(
    request: Request,
    session: AsyncSession,
    principal: Principal,
    test: Test,
    *,
    batch_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    scope = await scope_of(request, principal, "test.results.read")
    if scope.empty:
        raise ProblemError("permission_denied", permission="test.results.read")
    item_only = (
        scope.platform and principal.has_role("content_manager") and not principal.has_role("super_admin")
    )
    q = (
        select(TestAttempt, AttemptResult)
        .join(AttemptResult, AttemptResult.attempt_id == TestAttempt.id)
        .where(TestAttempt.test_id == test.id, TestAttempt.status.in_(GRADED_STATUSES))
    )
    if batch_id is not None:
        q = q.where(TestAttempt.batch_id == batch_id)
    rows = [(a, r) for a, r in (await adb.execute(session, q)).all() if _in_scope(a, scope)]
    n = len(rows)
    totals = {a.id: float(r.percentage) for a, r in rows}
    out: dict[str, Any] = {
        "test_id": str(test.id),
        "title": test.title,
        "scope": "item_stats_only" if item_only else "full",
        "k_min": K_MIN_ITEM,
        "attempts_count": n,
        "distribution": None,
        "submissions": None,
        "sections": None,
    }
    secs = {
        s.id: s
        for s in (
            await adb.execute(session, select(TestSection).where(TestSection.test_id == test.id))
        ).scalars()
    }
    responses = (
        (
            await adb.execute(
                session, select(AttemptResponse).where(AttemptResponse.attempt_id.in_(list(totals)))
            )
        )
        .scalars()
        .all()
        if totals
        else []
    )
    if not item_only:
        out["distribution"] = _distribution(list(totals.values()))
        reasons = [a.submit_reason for a, _ in rows]
        out["submissions"] = {
            "submitted": sum(1 for x in reasons if x == "user"),
            "auto_submitted": sum(1 for x in reasons if x in AUTO_REASONS),
            "admin_force": sum(1 for x in reasons if x == "admin_force"),
            "total": n,
        }
        per: dict[uuid.UUID, dict[uuid.UUID, int]] = {}
        for resp in responses:
            per.setdefault(resp.test_section_id, {}).setdefault(resp.attempt_id, 0)
            per[resp.test_section_id][resp.attempt_id] += resp.time_spent_ms
        out["sections"] = [
            {
                "section_id": str(s.id),
                "title": s.title,
                "position": s.position,
                "avg_time_seconds": _r(statistics.fmean(per[s.id].values()) / 1000, 1)
                if per.get(s.id)
                else None,
                "attempts": len(per.get(s.id, {})),
            }
            for s in sorted(secs.values(), key=lambda s: s.position)
        ]
    out["items"] = await _items(session, responses, totals, secs, n)
    return out


async def _items(
    session: AsyncSession,
    responses: Any,
    totals: dict[uuid.UUID, float],
    secs: dict[uuid.UUID, TestSection],
    n: int,
) -> dict[str, Any]:
    if n < K_MIN_ITEM:
        return {
            "suppressed": True,
            "reason": f"Item statistics need at least {K_MIN_ITEM} graded attempts (k-anonymity floor).",
            "data": [],
        }
    by_item: dict[uuid.UUID, list[tuple[int, float]]] = {}
    item_section: dict[uuid.UUID, uuid.UUID] = {}
    for resp in responses:
        by_item.setdefault(resp.question_version_id, []).append(
            (1 if resp.is_correct else 0, totals[resp.attempt_id])
        )
        item_section[resp.question_version_id] = resp.test_section_id
    qmap: dict[uuid.UUID, uuid.UUID] = {}
    if by_item:
        from app.modules.assessments import xmod

        qmap = {qv: v.question_id for qv, v in (await xmod.version_topics(session, list(by_item))).items()}

    def order(qv: uuid.UUID) -> tuple[int, str]:
        s = secs.get(item_section[qv])
        return (s.position if s else 0, str(qv))

    data = []
    for pos, qv in enumerate(sorted(by_item, key=order), start=1):
        pairs = by_item[qv]
        sec = secs.get(item_section[qv])
        suppressed = len(pairs) < K_MIN_ITEM
        xs = [x for x, _ in pairs]
        data.append(
            {
                "question_version_id": str(qv),
                "question_id": str(qmap[qv]) if qv in qmap else None,
                "section_title": sec.title if sec else None,
                "position": pos,
                "n": len(pairs),
                "difficulty_p": None if suppressed else _r(sum(xs) / len(xs)),
                "discrimination": None if suppressed else _r(point_biserial(xs, [t for _, t in pairs])),
                "suppressed": suppressed,
            }
        )
    return {"suppressed": False, "reason": None, "data": data}
