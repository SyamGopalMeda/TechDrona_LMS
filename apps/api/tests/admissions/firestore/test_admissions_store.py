"""Admissions on the Firestore emulator: the real service code (``verify_claim``, ``courses``)
on the shared SQL-on-Firestore engine, the deferred ledger trigger, the partial unique indexes,
append-only events and the repository wiring. Audit / outbox (Postgres, other modules) recorded."""

from __future__ import annotations

import asyncio
import uuid
from datetime import date
from typing import Any

import pytest
from sqlalchemy import select

from app.core.errors import ProblemError
from app.core.firestore.sqlstore import CheckViolation
from app.core.ids import uuid7
from app.core.principal import Principal
from app.core.time import utcnow
from app.modules.admissions import datastore as ads
from app.modules.admissions import service as svc
from app.modules.admissions.models import (
    AdmissionEvent,
    AdmissionFeePlan,
    AdmissionPaymentClaim,
    AdmissionRegistration,
    CourseStatus,
)
from tests.commerce.firestore.conftest import FakeSession


@pytest.fixture
def pg(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    rec: list[str] = []

    async def audit(_s: Any, _a: Any, action: str, *a: Any, **k: Any) -> None:
        rec.append(action)

    async def emit(_s: Any, name: str, *a: Any, **k: Any) -> None:
        rec.append(name)

    monkeypatch.setattr(svc, "audit", audit)
    monkeypatch.setattr(svc, "emit_event", emit)
    return rec


async def _registration(
    s: Any, *, email: str = "asha@example.com", fee: int = 500_000
) -> AdmissionRegistration:
    plan = AdmissionFeePlan(
        id=uuid7(),
        course_slug=f"py-{uuid.uuid4().hex[:6]}",
        title="Python",
        fee_paise=fee,
        min_first_paise=100_000,
        access_min_paise=200_000,
    )
    ads.add(s, plan)
    r = AdmissionRegistration(
        id=uuid7(),
        reg_no="TDR-" + uuid.uuid4().hex[:8].upper(),
        fee_plan_id=plan.id,
        course_slug=plan.course_slug,
        course_title="Python",
        name="Asha Rao",
        email=email,
        phone="+919876543210",
        college="RVCE",
        branch="CSE",
        year="3",
        fee_paise=fee,
        access_min_paise=200_000,
        policy="instalments",
        allow_instalments=True,
        min_first_paise=100_000,
        balance_paise=fee,
        consent_text="ok",
        consent_at=utcnow(),
        open_claims=1,
        status="pending_verification",
    )
    ads.add(s, r)
    await s.commit()
    return r


async def _claim(
    s: Any, reg: AdmissionRegistration, *, utr: str, amount: int = 200_000
) -> AdmissionPaymentClaim:
    c = AdmissionPaymentClaim(
        id=uuid7(),
        registration_id=reg.id,
        provider="manual_upi",
        method="upi",
        amount_paise=amount,
        utr=utr,
        paid_on=date(2026, 11, 1),
        proof_key=f"k/{utr}",
        proof_sha256=uuid.uuid4().hex * 2,
    )
    ads.add(s, c)
    await s.commit()
    return c


def _staff() -> svc.Actor:
    return svc.Actor(Principal(user_id=uuid7(), session_id=uuid7(), is_platform=True), "staff")


async def test_verify_claim_moves_ledger_and_double_approve_is_idempotent(
    fs: Any, session: Any, pg: Any
) -> None:
    reg = await _registration(session)
    c = await _claim(session, reg, utr="UTR12345")

    async def approve() -> dict[str, Any]:
        for i in range(20):
            s = FakeSession().as_platform()
            try:
                out = await svc.verify_claim(
                    s, _staff(), c.id, amount_paise=200_000, note="ok", checked=True, auto_enrol=False
                )
                await s.commit()
                return out
            except ProblemError as e:
                if e.code != "conflict":
                    raise
                await asyncio.sleep(0.02 * (i + 1))
        raise AssertionError("no progress")

    outs = await asyncio.gather(approve(), approve(), approve())
    assert sum(1 for o in outs if o.get("already_verified")) == 2
    s = FakeSession().as_platform()
    r = (
        await ads.execute(s, select(AdmissionRegistration).where(AdmissionRegistration.id == reg.id))
    ).scalar_one()
    assert (r.verified_total_paise, r.balance_paise, r.open_claims) == (200_000, 300_000, 0)
    events = (
        (await ads.execute(s, select(AdmissionEvent).where(AdmissionEvent.registration_id == reg.id)))
        .scalars()
        .all()
    )
    assert [e.action for e in events] == ["payment.verified"]
    assert pg.count("admissions.payment.verified") >= 1  # recorder also sees rolled-back attempts


async def test_ledger_trigger_rejects_a_total_without_verified_claims(fs: Any, session: Any) -> None:
    reg = await _registration(session)
    s = FakeSession().as_platform()
    r = await ads.get(s, AdmissionRegistration, reg.id, with_for_update=True)
    r.verified_total_paise, r.balance_paise = 100_000, 400_000  # no verified claim backs it
    with pytest.raises(CheckViolation, match="ck_areg_ledger_sum"):
        await s.commit()


async def test_one_live_registration_per_course_and_email(fs: Any, session: Any) -> None:
    reg = await _registration(session, email="ravi@example.com")
    s = FakeSession().as_platform()
    dup = AdmissionRegistration(
        **{c.key: getattr(reg, c.key) for c in AdmissionRegistration.__table__.columns}
    )
    dup.id, dup.reg_no = uuid7(), "TDR-" + uuid.uuid4().hex[:8].upper()
    ads.add(s, dup)
    with pytest.raises(ProblemError) as ei:
        await s.commit()
    assert ei.value.code == "conflict"
    # cancelling the first frees the slot (partial index WHERE status NOT IN rejected/cancelled)
    s2 = FakeSession().as_platform()
    first = await ads.get(s2, AdmissionRegistration, reg.id)
    first.status = "cancelled"
    await s2.commit()
    s3 = FakeSession().as_platform()
    ads.add(s3, dup)
    await s3.commit()


async def test_utr_lock_until_released(fs: Any, session: Any) -> None:
    reg = await _registration(session)
    c = await _claim(session, reg, utr="UTRLOCK1")
    s = FakeSession().as_platform()
    ads.add(
        s,
        AdmissionPaymentClaim(
            id=uuid7(),
            registration_id=reg.id,
            provider="manual_upi",
            method="upi",
            amount_paise=1000,
            utr="UTRLOCK1",
            paid_on=date(2026, 11, 2),
            proof_key="k2",
            proof_sha256="a" * 64,
        ),
    )
    with pytest.raises(ProblemError):
        await s.commit()
    s2 = FakeSession().as_platform()
    cur = await ads.get(s2, AdmissionPaymentClaim, c.id)
    cur.locks_released = True
    await s2.commit()
    s3 = FakeSession().as_platform()
    ads.add(
        s3,
        AdmissionPaymentClaim(
            id=uuid7(),
            registration_id=reg.id,
            provider="manual_upi",
            method="upi",
            amount_paise=1000,
            utr="UTRLOCK1",
            paid_on=date(2026, 11, 2),
            proof_key="k3",
            proof_sha256="b" * 64,
        ),
    )
    await s3.commit()


async def test_events_are_append_only(fs: Any, session: Any) -> None:
    ev = AdmissionEvent(id=uuid7(), action="registration.created", actor_label="x")
    ads.add(session, ev)
    await session.commit()
    s = FakeSession().as_platform()
    e = await ads.get(s, AdmissionEvent, ev.id)
    e.detail = "edited"
    with pytest.raises(ProblemError) as ei:
        await s.commit()
    assert ei.value.code == "permission_denied"


async def test_course_status_rows_insert_once_and_lock(fs: Any, session: Any) -> None:
    from app.modules.admissions import courses

    await courses.ensure_row(session, "ml-101")
    await courses.ensure_row(session, "ml-101")  # ON CONFLICT DO NOTHING
    await session.commit()
    s = FakeSession().as_platform()
    rows = (await ads.execute(s, select(CourseStatus))).scalars().all()
    assert [(r.course_slug, r.status) for r in rows] == [("ml-101", courses.DEFAULT)]
    row = await ads.get(s, CourseStatus, "ml-101", with_for_update=True)
    assert row is not None


async def test_platform_only_rls(fs: Any, session: Any) -> None:
    await _registration(session)
    user = FakeSession().as_user(uuid7())
    assert (await ads.execute(user, select(AdmissionRegistration))).scalars().all() == []


def test_backfill_mappings_cover_every_admissions_table() -> None:
    from app.core.firestore.backfill import mappings
    from app.modules.admissions.store_specs import TABLES

    assert {m.table for m in mappings("admissions")} == set(TABLES)
