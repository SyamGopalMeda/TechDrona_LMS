"""Topic mastery v1 (Elo-style, explainable; analytics-event-schema §6.2). Single writer of
``topic_mastery`` (CP-11). **Time is not an input to mastery.**

    P(correct) = sigmoid(theta_{u,t} - b_q)
    theta ← theta + K_u · w · (r - P),     K_u = 0.4 / (1 + 0.05 · n_{u,t})
    b_q seed: easy -1.0, medium 0.0, hard +1.0 (item recalibration nightly: Planned)
    w: test 1.0; practice first attempt 1.0; retry 0.5; after solution 0.0; after hint x 0.5;
       secondary topic tags x 0.5
    displayed m = sigmoid(theta); bands: insufficient_data (n_eff < 5), weak (< 0.40),
       developing (0.40-0.70), strong (>= 0.70)
    weighted accuracy = sum w·decay·r / sum w·decay, decay = 0.5^(age_days/30)

Inputs arrive as domain events from the transactional outbox (CP-8); see ``consumer.py``.
Placement reads mastery through ``get_topic_mastery``.
"""

from __future__ import annotations

import math
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.firestore.backend import uses_firestore
from app.core.time import utcnow
from app.modules.analytics.params import MASTERY_MODEL_VERSION

DIFFICULTY_SEED = {"easy": -1.0, "medium": 0.0, "hard": 1.0}


def sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


def band_for(theta: float, n_eff: float) -> str:
    if n_eff <= 0:
        return "not_started"
    if n_eff < 5:
        return "insufficient_data"
    m = sigmoid(theta)
    if m < 0.40:
        return "weak"
    if m < 0.70:
        return "developing"
    return "strong"


def response_weight(
    *, source: str, attempt_no: int = 1, after_solution: bool = False, after_hint: bool = False
) -> float:
    if source == "test":
        return 1.0
    if after_solution:
        return 0.0
    w = 1.0 if attempt_no <= 1 else 0.5
    if after_hint:
        w *= 0.5
    return w


@dataclass
class MasteryState:
    theta: float = 0.0
    n_eff: float = 0.0
    attempts: int = 0
    correct: int = 0
    wa_num: float = 0.0
    wa_den: float = 0.0
    last_practiced_at: datetime | None = None

    @property
    def weighted_accuracy(self) -> float:
        return 0.0 if self.wa_den <= 0 else max(0.0, min(1.0, self.wa_num / self.wa_den))

    @property
    def band(self) -> str:
        return band_for(self.theta, self.n_eff)


def elo_update(state: MasteryState, *, correct: bool, b: float, w: float, at: datetime) -> MasteryState:
    """Pure update. ``w = 0`` still counts the attempt but leaves theta and accuracy unchanged."""
    s = MasteryState(**state.__dict__)
    s.attempts += 1
    s.correct += 1 if correct else 0
    if w > 0:
        r = 1.0 if correct else 0.0
        p = sigmoid(s.theta - b)
        k = 0.4 / (1.0 + 0.05 * s.n_eff)
        s.theta = max(-9.0, min(9.0, s.theta + k * w * (r - p)))
        s.n_eff += w
        decay = 1.0
        if s.last_practiced_at is not None and at > s.last_practiced_at:
            decay = 0.5 ** ((at - s.last_practiced_at).total_seconds() / 86400 / 30)
        s.wa_num = s.wa_num * decay + w * r
        s.wa_den = s.wa_den * decay + w
    if s.last_practiced_at is None or at > s.last_practiced_at:
        s.last_practiced_at = at
    return s


@dataclass(frozen=True)
class ScoredResponse:
    user_id: uuid.UUID
    topic_ids: tuple[uuid.UUID, ...]  # primary first, then secondary tags
    correct: bool | None  # None = skipped -> no update
    difficulty: str | None
    source: str  # practice | test
    attempt_no: int = 1
    after_solution: bool = False
    after_hint: bool = False
    at: datetime | None = None
    question_version_id: uuid.UUID | None = None
    organization_id: uuid.UUID | None = None


def _fs() -> bool:
    from app.core.firestore.backend import uses_firestore

    return uses_firestore("analytics")


async def _item_difficulty(session: AsyncSession, r: ScoredResponse) -> float:
    if r.question_version_id is not None and _fs():
        from app.modules.analytics import fs_raw

        fb = await fs_raw.item_difficulty(r.question_version_id)
        if fb is not None:
            return fb
    elif r.question_version_id is not None:
        row = (
            await session.execute(
                text("SELECT difficulty_b FROM question_item_stats WHERE question_version_id = :q"),
                {"q": r.question_version_id},
            )
        ).first()
        if row and row[0] is not None:
            return float(row[0])
    return DIFFICULTY_SEED.get((r.difficulty or "medium").lower(), 0.0)


async def apply_response(session: AsyncSession, r: ScoredResponse) -> int:
    """Update every tagged topic for one scored response. Returns rows touched."""
    if r.correct is None or not r.topic_ids:
        return 0
    b = await _item_difficulty(session, r)
    base_w = response_weight(
        source=r.source, attempt_no=r.attempt_no, after_solution=r.after_solution, after_hint=r.after_hint
    )
    at = r.at or utcnow()
    touched = 0
    for i, topic in enumerate(dict.fromkeys(r.topic_ids)):
        w = base_w if i == 0 else base_w * 0.5
        if _fs():
            from app.modules.analytics import fs_raw

            def update(cur: Any, w: float = w) -> dict[str, Any]:
                st = (
                    MasteryState(
                        float(cur.theta),
                        float(cur.n_eff),
                        cur.attempts,
                        cur.correct,
                        cur.wa_num,
                        cur.wa_den,
                        cur.last_practiced_at,
                    )
                    if cur is not None
                    else MasteryState()
                )
                new = elo_update(st, correct=bool(r.correct), b=b, w=w, at=at)
                return {
                    "theta": round(new.theta, 3),
                    "n_eff": round(new.n_eff, 2),
                    "attempts": new.attempts,
                    "correct": new.correct,
                    "weighted_accuracy": round(new.weighted_accuracy, 4),
                    "wa_num": new.wa_num,
                    "wa_den": new.wa_den,
                    "band": new.band,
                    "last_practiced_at": new.last_practiced_at,
                    "model_version": MASTERY_MODEL_VERSION,
                }

            await fs_raw.upsert_mastery(r.user_id, topic, r.organization_id, update)
            touched += 1
            continue
        row = (
            await session.execute(
                text(
                    "SELECT theta, n_eff, attempts, correct, wa_num, wa_den, last_practiced_at FROM "
                    "topic_mastery "
                    "WHERE user_id = :u AND topic_id = :t FOR UPDATE"
                ),
                {"u": r.user_id, "t": topic},
            )
        ).first()
        state = (
            MasteryState(float(row[0]), float(row[1]), row[2], row[3], row[4], row[5], row[6])
            if row
            else MasteryState()
        )
        new = elo_update(state, correct=r.correct, b=b, w=w, at=at)
        await session.execute(
            text(
                """
                INSERT INTO topic_mastery (user_id, topic_id, organization_id, theta, n_eff, attempts,
                    correct,
                    weighted_accuracy, wa_num, wa_den, band, last_practiced_at, model_version, updated_at)
                VALUES (:u, :t, :o, :theta, :n, :a, :c, :wa, :wn, :wd, :band, :lp, :mv, now())
                ON CONFLICT (user_id, topic_id) DO UPDATE SET
                    theta = EXCLUDED.theta, n_eff = EXCLUDED.n_eff, attempts = EXCLUDED.attempts,
                    correct = EXCLUDED.correct, weighted_accuracy = EXCLUDED.weighted_accuracy,
                    wa_num = EXCLUDED.wa_num, wa_den = EXCLUDED.wa_den, band = EXCLUDED.band,
                    last_practiced_at = EXCLUDED.last_practiced_at,
                    organization_id = coalesce(topic_mastery.organization_id, EXCLUDED.organization_id),
                    model_version = EXCLUDED.model_version, updated_at = now()
                """
            ),
            {
                "u": r.user_id,
                "t": topic,
                "o": r.organization_id,
                "theta": round(new.theta, 3),
                "n": round(new.n_eff, 2),
                "a": new.attempts,
                "c": new.correct,
                "wa": round(new.weighted_accuracy, 4),
                "wn": new.wa_num,
                "wd": new.wa_den,
                "band": new.band,
                "lp": new.last_practiced_at,
                "mv": MASTERY_MODEL_VERSION,
            },
        )
        touched += 1
    return touched


# --------------------------------------------------------------------------- read interface


@dataclass(frozen=True)
class TopicMasteryView:
    topic_id: uuid.UUID
    mastery: float  # sigmoid(theta)
    band: str
    weighted_accuracy: float
    n_eff: float
    attempts: int
    last_practiced_at: datetime | None
    model_version: str


async def get_topic_mastery(
    session: AsyncSession, user_id: uuid.UUID, topic_ids: list[uuid.UUID] | None = None
) -> list[TopicMasteryView]:
    """Placement/recommendations interface (CP-11). Runs under the caller's RLS context."""
    if uses_firestore("analytics"):
        return await _fs_topic_mastery(user_id, topic_ids)
    sql = (
        "SELECT topic_id, theta, band, weighted_accuracy, n_eff, attempts, last_practiced_at, model_version "
        "FROM topic_mastery WHERE user_id = :u"
    )
    params: dict[str, Any] = {"u": user_id}
    if topic_ids is not None:
        sql += " AND topic_id = ANY(:ts)"
        params["ts"] = list(topic_ids)
    rows = (await session.execute(text(sql + " ORDER BY topic_id"), params)).all()
    return [
        TopicMasteryView(
            topic_id=r[0],
            mastery=round(sigmoid(float(r[1])), 4),
            band=r[2],
            weighted_accuracy=float(r[3]),
            n_eff=float(r[4]),
            attempts=r[5],
            last_practiced_at=r[6],
            model_version=r[7],
        )
        for r in rows
    ]


def rollup(
    views: list[TopicMasteryView], parent_of: dict[uuid.UUID, uuid.UUID | None]
) -> dict[uuid.UUID, float]:
    """subtopic -> topic -> category: n_eff-weighted mean of m (§6.2)."""
    acc: dict[uuid.UUID, tuple[float, float]] = {}
    for v in views:
        node: uuid.UUID | None = v.topic_id
        seen: set[uuid.UUID] = set()
        while node is not None and node not in seen:
            seen.add(node)
            s, n = acc.get(node, (0.0, 0.0))
            acc[node] = (s + v.mastery * v.n_eff, n + v.n_eff)
            node = parent_of.get(node)
    return {k: (s / n if n > 0 else 0.0) for k, (s, n) in acc.items()}


async def _fs_topic_mastery(user_id: uuid.UUID, topic_ids: list[uuid.UUID] | None) -> list[TopicMasteryView]:
    from app.modules.analytics.repo_firestore import feed_repo
    from app.modules.analytics.store_specs import TopicRow

    want = None if topic_ids is None else {str(t) for t in topic_ids}
    out: list[TopicMasteryView] = []
    for d in await feed_repo("analytics.mastery_read").topic_mastery(user_id):
        if want is not None and d.get("topic_id") not in want:
            continue
        r = TopicRow.of(d)
        out.append(
            TopicMasteryView(
                topic_id=r.topic_id,
                mastery=round(sigmoid(float(r.theta)), 4),
                band=r.band,
                weighted_accuracy=float(r.weighted_accuracy),
                n_eff=float(r.n_eff),
                attempts=r.attempts,
                last_practiced_at=r.last_practiced_at,
                model_version=r.model_version,
            )
        )
    return out
