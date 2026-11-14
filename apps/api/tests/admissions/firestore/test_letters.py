"""Admission / offer letter step on Firestore over HTTP (no Postgres): the draft prefilled from the
registration, the letter found again after it is issued in the documents register (linked by the
LMS user + registration number / enrolment), the registrations list / page showing it, the bulk
drafts and the "open the step after enrolling" setting.

    TD_TEST_NO_PG=1 .venv/Scripts/python -m pytest tests/admissions/firestore/test_letters.py \
        --confcutdir=tests/admissions/firestore -p no:cacheprovider
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import date
from typing import Any

import httpx
import pytest

from app.core.ids import uuid7
from app.core.principal import Principal
from app.core.time import utcnow
from app.modules.admissions import datastore as ads
from app.modules.admissions.models import AdmissionFeePlan, AdmissionRegistration
from tests.commerce.firestore.conftest import FakeSession

API = "/api/v1/admin/admissions"


class _Store:
    def __init__(self) -> None:
        self.objects: dict[tuple[str, str], tuple[bytes, str]] = {}

    async def put(self, bucket: str, key: str, data: bytes, ctype: str) -> None:
        self.objects[(bucket, key)] = (data, ctype)


@pytest.fixture
async def http(fs: Any, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[httpx.AsyncClient]:
    from app.core import auth as core_auth
    from app.core import runtime
    from app.core.firestore.backend import reset_store_backends
    from app.main import create_app
    from app.modules.admissions import admin as adm
    from app.modules.learning import certificates as certs
    from app.modules.learning import documents as docs
    from app.modules.notifications import adapters

    monkeypatch.setenv("TD_ROUTER_SET", "all")
    for m in (
        "ADMIN",
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
    monkeypatch.setattr(adapters, "email_integrated", lambda: False)

    async def fake_audit(*a: Any, **k: Any) -> None:
        return None

    async def fake_render(doc: Any) -> bytes:
        return b"%PDF-1.4 letter"

    store = _Store()
    monkeypatch.setattr(docs, "audit", fake_audit)
    monkeypatch.setattr(docs, "render", fake_render)
    monkeypatch.setattr(docs, "_site_url", lambda: "https://lms.example")
    monkeypatch.setattr(certs, "_store", lambda: store)
    monkeypatch.setattr(certs, "_bucket", lambda: "certs")
    staff = Principal(user_id=uuid7(), session_id=uuid7(), is_platform=True, is_minor=False)
    app = create_app()
    app.dependency_overrides[core_auth.require_active_principal] = lambda: staff
    app.dependency_overrides[adm.VERIFY.dependency] = lambda: staff
    app.dependency_overrides[adm.READ.dependency] = lambda: staff
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test"
    ) as c:
        yield c


async def _registration(*, enrolled: bool = True, slug: str = "py-201", title: str = "Python") -> Any:
    uid = uuid7() if enrolled else None
    s = FakeSession().as_platform()
    plan = AdmissionFeePlan(
        id=uuid7(),
        course_slug=f"{slug}-{uuid.uuid4().hex[:4]}",
        title=title,
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
        course_title=title,
        name="Asha Rao",
        email=f"stu-{uuid.uuid4().hex[:6]}@example.com",
        phone="+919876543210",
        college="RVCE",
        branch="CSE",
        year="3rd year",
        preferred_mode="online",
        fee_paise=300_000,
        access_min_paise=100_000,
        policy="full",
        allow_instalments=False,
        min_first_paise=100_000,
        balance_paise=300_000,
        consent_text="ok",
        consent_at=utcnow(),
        status="enrolled" if enrolled else "registered",
        enrolled_at=utcnow() if enrolled else None,
        user_id=uid,
    )
    ads.add(s, reg)
    await s.commit()
    return reg


async def _issue(draft: dict[str, Any], **override: Any) -> Any:
    """What ``POST /admin/documents`` does with the draft the SPA sends."""
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.modules.learning import documents as docs

    class _Actor:
        user_id = uuid.uuid4()

    s = AsyncSession()
    await docs.save_settings(
        s, _Actor(), {"company": "Tech Drona", "signatory": "A. Head", "designation": "Director"}
    )
    recipient = {**draft["recipient"], **override.pop("recipient", {})}
    return await docs.issue_document(
        s,
        _Actor(),
        doc_type=draft["doc_type"],
        recipient=recipient,
        fields=draft["fields"],
        issue_date=date.fromisoformat(draft["issue_date"]),
        user_id=uuid.UUID(draft["user_id"]),
        enrolment_id=uuid.UUID(draft["enrolment_id"]) if draft["enrolment_id"] else None,
        **override,
    )


async def test_draft_then_issued_letter_shows_on_the_registration(http: httpx.AsyncClient) -> None:
    reg = await _registration()
    r = await http.get(f"{API}/registrations/{reg.id}/letter")
    assert r.status_code == 200, r.text
    step = r.json()
    assert step["ready"] is True and step["letter"] is None and step["letters"] == []
    assert step["email"] == {"connected": False, "auto_send": step["email"]["auto_send"]}
    assert step["auto_open"] is True
    d = step["draft"]
    assert d["doc_type"] == "offer_course"
    assert d["recipient"] == {"name": "Asha Rao", "email": reg.email, "college": "RVCE", "reg_no": reg.reg_no}
    assert d["fields"]["program"] == "Python"
    assert d["fields"]["mode"] == "Online"
    assert d["fields"]["fee_total"] == "Rs 3,000" and d["fields"]["fee_balance"] == "Rs 3,000"
    assert "fee_paid" not in d["fields"]  # nothing verified yet: not printed
    assert d["fields"]["batch_start"] and d["issue_date"]
    assert d["user_id"] == str(reg.user_id)

    # issued through the documents register with the draft -> linked to the registration
    doc = await _issue(d)
    other = await _issue(d, recipient={"reg_no": "TDR-OTHER001"})  # another registration's letter
    assert other.ref_no != doc.ref_no
    step = (await http.get(f"{API}/registrations/{reg.id}/letter")).json()
    assert step["letter"]["ref_no"] == doc.ref_no and doc.ref_no.startswith("TD-AL-")
    assert [x["ref_no"] for x in step["letters"]] == [doc.ref_no]
    assert step["letter"]["verify_link"] == f"https://lms.example/verify/{doc.ref_no}"
    assert step["letter"]["status"] == "valid"

    page = (await http.get(f"{API}/registrations/{reg.id}")).json()
    assert page["letter"]["ref_no"] == doc.ref_no and page["letter"]["short"] == "Admission letter"
    assert page["letter_step_auto"] is True
    rows = (await http.get(f"{API}/registrations", params={"course_slug": reg.course_slug})).json()["data"]
    assert [x["letter"]["ref_no"] for x in rows] == [doc.ref_no]


async def test_bulk_drafts_internship_and_not_enrolled(http: httpx.AsyncClient) -> None:
    intern = await _registration(slug="web-internship", title="Web Development Internship")
    waiting = await _registration(enrolled=False)
    r = await http.post(
        f"{API}/letters/drafts", json={"registration_ids": [str(intern.id), str(waiting.id), str(uuid7())]}
    )
    assert r.status_code == 200, r.text
    a, b = r.json()["data"]
    assert a["registration_id"] == str(intern.id) and a["ready"] is True
    assert a["draft"]["doc_type"] == "offer_internship"
    f = a["draft"]["fields"]
    assert f["role"] == "Web Development Internship" and f["intern_stipend"] == "Unpaid"
    assert f["course_year"] == "CSE, 3rd year" and "no_fee" not in f
    assert b["registration_id"] == str(waiting.id) and b["ready"] is False and b["draft"] is None
    assert b["reason"]
    assert (await http.post(f"{API}/letters/drafts", json={"registration_ids": []})).status_code in (400, 422)


async def test_letter_step_setting(http: httpx.AsyncClient) -> None:
    assert (await http.get(f"{API}/letter-settings")).json() == {"auto_open": True}
    r = await http.put(f"{API}/letter-settings", json={"auto_open": False})
    assert r.status_code == 200, r.text
    assert (await http.get(f"{API}/letter-settings")).json() == {"auto_open": False}
    reg = await _registration()
    assert (await http.get(f"{API}/registrations/{reg.id}")).json()["letter_step_auto"] is False
    await http.put(f"{API}/letter-settings", json={"auto_open": True})
    assert (await http.get(f"{API}/registrations/{reg.id}/letter")).json()["auto_open"] is True


def test_letter_type() -> None:
    from app.modules.admissions.letters import letter_type

    def reg(slug: str, title: str) -> Any:
        return AdmissionRegistration(course_slug=slug, course_title=title)

    assert letter_type(reg("java", "Full Stack Java")) == "offer_course"
    assert letter_type(reg("summer-internship", "Summer programme")) == "offer_internship"
    assert letter_type(reg("ai", "AI Interns 2026")) == "offer_internship"
    assert letter_type(reg("international", "International Business")) == "offer_course"
