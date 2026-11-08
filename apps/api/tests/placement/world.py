"""Factories shared by the placement and assessments test packages.

Principals are real users (FK targets) resolved by the ``FakeAuth`` session resolver, with the
real ``RbacPermissionChecker`` so permission scopes (platform / organization / batch) and
cross-tenant 404s behave exactly as in production. Principals that take attempts also get real
``devices`` / ``auth_sessions`` rows (attempt binding FKs, idle hold, session-too-short).
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field
from datetime import timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import system_context
from app.core.ids import uuid7
from app.core.principal import Principal, RoleGrant
from app.core.time import utcnow
from app.modules.placement import bank
from app.modules.placement.models import Topic
from app.modules.placement.schemas import OptionIn, QuestionCreate
from tests.identity.factory import add_member, company_org, make_batch, make_user


@dataclass
class Persona:
    principal: Principal
    headers: dict[str, str]
    email: str = ""

    @property
    def id(self) -> uuid.UUID:
        return self.principal.user_id


async def make_device(db: AsyncSession) -> uuid.UUID:
    from app.modules.sessions.models import Device

    await system_context(db, "test.factory")
    did = uuid7()
    db.add(
        Device(
            id=did,
            device_key_hash=hashlib.sha256(did.bytes).digest(),
            client_type="web",
            ua_family="Chrome",
            os_family="Windows",
        )
    )
    await db.flush()
    return did


async def make_auth_session(
    db: AsyncSession,
    user_id: uuid.UUID,
    device_id: uuid.UUID | None,
    *,
    tier: str = "student",
    absolute: timedelta = timedelta(hours=12),
    ua: str = "Chrome",
    os_family: str = "Windows",
) -> uuid.UUID:
    from app.modules.sessions.models import AuthSession

    await system_context(db, "test.factory")
    sid = uuid7()
    now = utcnow()
    db.add(
        AuthSession(
            id=sid,
            token_hash=hashlib.sha256(sid.bytes).digest(),
            user_id=user_id,
            device_id=device_id,
            client_type="web",
            session_tier=tier,
            created_via="password",
            idle_expires_at=now + timedelta(minutes=30),
            absolute_expires_at=now + absolute,
            ua_family=ua,
            os_family=os_family,
        )
    )
    await db.flush()
    return sid


@dataclass
class World:
    db: AsyncSession
    auth: Any
    org_a: uuid.UUID = field(default_factory=uuid7)
    org_b: uuid.UUID = field(default_factory=uuid7)
    batch_a: uuid.UUID = field(default_factory=uuid7)
    batch_a2: uuid.UUID = field(default_factory=uuid7)
    batch_b: uuid.UUID = field(default_factory=uuid7)
    personas: dict[str, Persona] = field(default_factory=dict)

    async def persona(
        self,
        name: str,
        *,
        grants: tuple[tuple[str, str, uuid.UUID | None], ...] = (),
        org_ids: tuple[uuid.UUID, ...] = (),
        is_platform: bool = False,
        tier: str = "student",
        with_session: bool = True,
        restriction_level: int = 0,
        scope: str = "full",
        minor: bool = False,
    ) -> Persona:
        u = await make_user(self.db, minor=minor)
        device_id = await make_device(self.db) if with_session else None
        session_id = await make_auth_session(self.db, u.id, device_id, tier=tier) if with_session else uuid7()
        p = Principal(
            user_id=u.id,
            session_id=session_id,
            tier=tier,  # type: ignore[arg-type]
            scope=scope,  # type: ignore[arg-type]
            device_id=device_id,
            org_ids=org_ids,
            grants=tuple(RoleGrant(r, st, sid) for r, st, sid in grants),  # type: ignore[arg-type]
            is_platform=is_platform,
            restriction_level=restriction_level,
            is_minor=minor,
        )
        persona = Persona(p, self.auth.login(p), u.email)
        self.personas[name] = persona
        return persona

    async def new_session(
        self,
        who: Persona,
        *,
        same_device: bool,
        restriction_level: int | None = None,
        absolute: timedelta = timedelta(hours=12),
    ) -> Persona:
        """Another session of the same user (same device = crash/re-login; else another device)."""
        device_id = who.principal.device_id if same_device else await make_device(self.db)
        sid = await make_auth_session(
            self.db, who.id, device_id, absolute=absolute, ua="Firefox", os_family="Android"
        )
        from dataclasses import replace

        p = replace(
            who.principal,
            session_id=sid,
            device_id=device_id,
            restriction_level=who.principal.restriction_level
            if restriction_level is None
            else restriction_level,
        )
        return Persona(p, self.auth.login(p), who.email)


async def build_world(db: AsyncSession, auth: Any) -> World:
    w = World(db, auth)
    founder = await make_user(db)
    # Single company (orgs_0003 allows exactly one live org): "A" and "B" are both the company
    # org. Cross-tenant isolation is now cross-BATCH: trainer_b / student_b live in batch_b,
    # which no "A" persona holds a grant on or belongs to. ``org_b`` stays as an alias so the
    # suites keep their names.
    w.org_a = company_org()
    w.org_b = company_org()
    w.batch_a = await make_batch(db, w.org_a, founder.id)
    w.batch_a2 = await make_batch(db, w.org_a, founder.id)
    w.batch_b = await make_batch(db, w.org_b, founder.id)
    await w.persona("author", grants=(("content_manager", "platform", None),), is_platform=True, tier="staff")
    await w.persona(
        "reviewer", grants=(("content_manager", "platform", None),), is_platform=True, tier="staff"
    )
    await w.persona("trainer_a", grants=(("trainer", "batch", w.batch_a),), org_ids=(w.org_a,), tier="staff")
    await w.persona(
        "admin",
        grants=(("super_admin", "platform", None),),
        org_ids=(w.org_a,),
        is_platform=True,
        tier="staff",
    )
    await w.persona(
        "evaluator_a", grants=(("evaluator", "batch", w.batch_a),), org_ids=(w.org_a,), tier="staff"
    )
    await w.persona("trainer_b", grants=(("trainer", "batch", w.batch_b),), org_ids=(w.org_b,), tier="staff")
    s = await w.persona("student", org_ids=(w.org_a,))
    await add_member(db, w.org_a, s.id, "student", w.batch_a)
    s2 = await w.persona("student_b", org_ids=(w.org_b,))
    await add_member(db, w.org_b, s2.id, "student", w.batch_b)
    for name, org, batch in (("trainer_a", w.org_a, w.batch_a), ("trainer_b", w.org_b, w.batch_b)):
        await add_member(db, org, w.personas[name].id, "staff", batch)
    await add_member(db, w.org_a, w.personas["evaluator_a"].id, "staff", w.batch_a)
    return w


# --------------------------------------------------------------------------- content


async def topic(db: AsyncSession, path: str, name: str | None = None) -> uuid.UUID:
    """Create (or fetch) a topic chain from a slash path, e.g. 'quant/percentages'."""
    await system_context(db, "test.factory")
    parent: uuid.UUID | None = None
    parts = path.split("/")
    tid: uuid.UUID | None = None
    for i in range(len(parts)):
        p = "/".join(parts[: i + 1])
        row = (await db.execute(text("SELECT id FROM topics WHERE path = :p"), {"p": p})).first()
        if row:
            tid = row[0]
        else:
            tid = uuid7()
            db.add(
                Topic(
                    id=tid,
                    parent_id=parent,
                    kind=("subject", "topic", "subtopic")[i],
                    slug=parts[i],
                    name=name if (name and i == len(parts) - 1) else parts[i].title(),
                    path=p,
                    depth=i,
                )
            )
            await db.flush()
        parent = tid
    assert tid is not None
    return tid


@dataclass
class Q:
    question_id: uuid.UUID
    qv_id: uuid.UUID
    correct: list[uuid.UUID]
    wrong: list[uuid.UUID]
    qtype: str


async def question(
    db: AsyncSession,
    author: Persona,
    reviewer: Persona,
    topic_id: uuid.UUID,
    *,
    qtype: str = "mcq_single",
    difficulty: int = 2,
    marks: str = "1",
    negative: str = "0",
    org: uuid.UUID | None = None,
    stem: str = "Demo question",
    publish: bool = True,
) -> Q:
    """Create a question through the bank service and (by default) run the full review flow."""
    await system_context(db, "test.factory")
    options: list[OptionIn] = []
    key: dict[str, Any] | None = None
    if qtype == "mcq_single":
        options = [OptionIn(html=f"opt {i}", is_correct=i == 1) for i in range(4)]
    elif qtype == "mcq_multi":
        options = [OptionIn(html=f"opt {i}", is_correct=i in (0, 2)) for i in range(4)]
    elif qtype == "numeric":
        key = {"value": "12.5", "tolerance": "0.01"}
    elif qtype == "fill_blank":
        key = {"accepted": ["Photosynthesis"], "case_sensitive": False}
    body = QuestionCreate(
        question_type=qtype,
        primary_topic_id=topic_id,
        organization_id=org,
        stem_html=f"<p>{stem}</p>",
        options=options,
        answer_key=key,
        explanation_html="<p>Because it is the demo key.</p>",
        difficulty=difficulty,
        default_marks=Decimal(marks),
        default_negative=Decimal(negative),
    )
    q, qv = await bank.create_question(db, author.principal, body)
    if publish:
        await bank.submit_review(db, q.id)
        await bank.review(db, reviewer.principal, q.id, "approve")
        await bank.publish(db, q.id)
    opts = (await bank.options_of(db, [qv.id])).get(qv.id, [])
    return Q(
        q.id,
        qv.id,
        [o.id for o in opts if o.is_correct],
        [o.id for o in opts if not o.is_correct],
        qtype,
    )


def correct_response(q: Q) -> dict[str, Any]:
    if q.qtype in ("mcq_single", "mcq_multi"):
        return {"option_ids": [str(i) for i in q.correct]}
    if q.qtype == "numeric":
        return {"value": "12.5"}
    return {"value": "photosynthesis"}


def wrong_response(q: Q) -> dict[str, Any]:
    if q.qtype in ("mcq_single", "mcq_multi"):
        return {"option_ids": [str(q.wrong[0])]}
    if q.qtype == "numeric":
        return {"value": "99"}
    return {"value": "respiration"}


FORBIDDEN_KEYS = {
    "is_correct",
    "answer_key",
    "explanation",
    "explanation_html",
    "correct_option_ids",
    "correct_answer",
}


def find_keys(payload: Any, keys: set[str] = FORBIDDEN_KEYS) -> set[str]:
    """Every forbidden key name present anywhere in a JSON payload."""
    found: set[str] = set()
    if isinstance(payload, dict):
        for k, v in payload.items():
            if k == "visible":  # visibility flags, not key material
                continue
            if k in keys:
                found.add(k)
            found |= find_keys(v, keys)
    elif isinstance(payload, list):
        for v in payload:
            found |= find_keys(v, keys)
    return found


def idem() -> dict[str, str]:
    return {"Idempotency-Key": f"k-{uuid7().hex}"}
