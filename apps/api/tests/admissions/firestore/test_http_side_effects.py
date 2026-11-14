"""Admissions login email over HTTP, no Postgres: the email leaves only if the transaction can
commit (Postgres: ``SET CONSTRAINTS ALL IMMEDIATE`` before the send; Firestore: the commit's
checks run first through ``sqlstore.precheck_all``)."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
from sqlalchemy import select

from app.core.ids import uuid7
from app.core.principal import Principal
from app.core.time import utcnow
from app.modules.admissions import datastore as ads
from app.modules.admissions.models import AdmissionEvent, AdmissionFeePlan, AdmissionRegistration
from tests.commerce.firestore.conftest import FakeSession


@pytest.fixture
async def http(fs: Any, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[dict[str, Any]]:
    from app.core import auth as core_auth
    from app.core import runtime
    from app.core.firestore.backend import reset_store_backends
    from app.main import create_app
    from app.modules.admissions import admin as adm
    from app.modules.notifications import adapters, service

    monkeypatch.setenv("TD_ROUTER_SET", "all")
    for m in (
        "COMMERCE",
        "CORE",
        "AUDIT",
        "ORGS",
        "ENTITLEMENTS",
        "IDENTITY",
        "LEARNING",
        "SESSIONS",
        "RBAC",
    ):
        monkeypatch.setenv(f"TD_STORE_{m}", "firestore")
    reset_store_backends()
    monkeypatch.setattr(runtime, "postgres_enabled", lambda: False)
    sent: list[str] = []

    async def fake_send(to: str, *a: Any, **k: Any) -> bool:
        sent.append(to)
        return True

    monkeypatch.setattr(service, "send_email", fake_send)
    monkeypatch.setattr(adapters, "email_integrated", lambda: True)
    staff = Principal(user_id=uuid7(), session_id=uuid7(), is_platform=True, is_minor=False)
    app = create_app()
    app.dependency_overrides[core_auth.require_active_principal] = lambda: staff
    app.dependency_overrides[adm.VERIFY.dependency] = lambda: staff
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test"
    ) as c:
        yield {"client": c, "sent": sent}


async def _enrolled_student() -> AdmissionRegistration:
    from app.modules.identity import public as identity
    from app.modules.identity.models import User, UserProfile

    uid = uuid7()
    email = f"stu-{uuid.uuid4().hex[:6]}@example.com"
    await identity.create_user(
        FakeSession().as_platform(),
        User(id=uid, email=email, username=f"td{uuid.uuid4().hex[:6]}", status="active", is_minor=False),
        UserProfile(user_id=uid, full_name="Asha Rao"),
    )
    s = FakeSession().as_platform()
    plan = AdmissionFeePlan(
        id=uuid7(),
        course_slug="py-201",
        title="Python",
        fee_paise=300_000,
        min_first_paise=100_000,
        access_min_paise=100_000,
    )
    ads.add(s, plan)
    reg = AdmissionRegistration(
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
        fee_paise=300_000,
        access_min_paise=100_000,
        policy="full",
        allow_instalments=False,
        min_first_paise=100_000,
        balance_paise=300_000,
        consent_text="ok",
        consent_at=utcnow(),
        status="enrolled",
        enrolled_at=utcnow(),
        user_id=uid,
    )
    ads.add(s, reg)
    await s.commit()
    return reg


async def _sent_at(reg_id: uuid.UUID) -> Any:
    s = FakeSession().as_platform()
    r = (
        await ads.execute(s, select(AdmissionRegistration).where(AdmissionRegistration.id == reg_id))
    ).scalar_one()
    return r.login_email_sent_at


async def test_login_email_is_sent_and_recorded(http: dict[str, Any]) -> None:
    reg = await _enrolled_student()
    r = await http["client"].post(
        f"/api/v1/admin/admissions/registrations/{reg.id}/login-email",
        json={"reset_password": False, "must_change_password": False},
    )
    assert r.status_code == 200, r.text
    assert r.json()["email"]["sent"] is True
    assert http["sent"] == [reg.email]
    assert await _sent_at(reg.id) is not None


async def test_failed_ledger_check_sends_no_email(
    http: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The transaction breaks the ledger before the send (``verified_total_paise`` without a
    verified claim): the deferred check fails first, no email leaves and nothing is committed."""
    from app.modules.admissions import onboarding

    reg = await _enrolled_student()
    real = onboarding.login_message

    def corrupt(r: Any, *a: Any, **k: Any) -> Any:
        r.verified_total_paise, r.balance_paise = 100_000, 200_000  # no verified claim backs it
        return real(r, *a, **k)

    monkeypatch.setattr(onboarding, "login_message", corrupt)
    r = await http["client"].post(
        f"/api/v1/admin/admissions/registrations/{reg.id}/login-email",
        json={"reset_password": False, "must_change_password": False},
    )
    assert r.status_code >= 500, r.text  # Postgres: the ledger trigger's 23514 is a 500 too
    assert http["sent"] == []  # no email
    assert await _sent_at(reg.id) is None  # nothing committed
    s = FakeSession().as_platform()
    evs = (
        await ads.execute(s, select(AdmissionEvent).where(AdmissionEvent.registration_id == reg.id))
    ).scalars()
    assert list(evs) == []
