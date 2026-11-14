"""Admin > Payments > Admissions over HTTP on Firestore, no Postgres (the live stack): fee plans,
payment details, course status (``no_fee_plan``), the public plan / status map, registrations
list (filters, last payment, paging), overview and the claims queue."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import date, timedelta
from typing import Any

import httpx
import pytest

from app.core.ids import uuid7
from app.core.principal import Principal
from app.core.time import utcnow
from app.modules.admissions import datastore as ads
from app.modules.admissions.models import AdmissionFeePlan, AdmissionPaymentClaim, AdmissionRegistration
from tests.commerce.firestore.conftest import FakeSession

FEE = 500_000  # Rs 5,000


@pytest.fixture
async def api(fs: Any, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[httpx.AsyncClient]:
    from app.core import auth as core_auth
    from app.core import runtime
    from app.core.firestore.backend import reset_store_backends
    from app.main import create_app
    from app.modules.admissions import admin as adm

    monkeypatch.setenv("TD_ROUTER_SET", "all")
    for m in (
        "CATALOG",
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
    staff = Principal(user_id=uuid7(), session_id=uuid7(), is_platform=True, is_minor=False)
    app = create_app()
    app.dependency_overrides[core_auth.require_active_principal] = lambda: staff
    for dep in (adm.READ, adm.VERIFY, adm.REVERSE, adm.PLANS):
        app.dependency_overrides[dep.dependency] = lambda: staff
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test/api/v1"
    ) as c:
        yield c


def _plan(slug: str, **over: Any) -> dict[str, Any]:
    return {
        "slug": slug,
        "title": "NextGen Career Accelerator 2026",
        "fee_paise": FEE,
        "active": False,
    } | over


async def _pay(api: httpx.AsyncClient) -> None:
    r = await api.put(
        "/admin/admissions/pay-settings", json={"phone": "9876543210", "preferred_app": "PhonePe"}
    )
    assert r.status_code == 200, r.text


async def test_fee_plan_validation(api: httpx.AsyncClient) -> None:
    slug = f"ng-{uuid.uuid4().hex[:6]}"
    for body, code in (
        (_plan(slug, fee_paise=0), "invalid_plan"),
        (_plan(slug, fee_paise=50), "invalid_plan"),  # below Rs 1
        (
            _plan(
                slug,
                allow_instalments=True,
                schedule=[{"label": "1", "amount_paise": 200_000}, {"label": "2", "amount_paise": 200_000}],
            ),
            "invalid_plan",
        ),  # 4,000 != 5,000
        (_plan(slug, batch_id=str(uuid7())), "unknown_batch"),
        (_plan(slug, course_id=str(uuid7())), "unknown_course"),
        (_plan("Bad Slug!"), "invalid_slug"),
    ):
        r = await api.put("/admin/admissions/plans", json=body)
        assert r.status_code == 422, (body, r.text)
        assert r.json()["errors"][0]["code"] == code, r.text
    r = await api.put("/admin/admissions/plans", json=_plan(slug, fee_paise=-1))
    assert r.status_code == 400, r.text  # request validation (negative fee)
    # nothing was stored by the refused saves
    plans = (await api.get("/admin/admissions/plans")).json()
    assert slug not in [p["slug"] for p in plans["data"]]


async def test_plan_create_edit_and_course_status(api: httpx.AsyncClient) -> None:
    slug = f"ng-{uuid.uuid4().hex[:6]}"
    r = await api.put("/admin/admissions/plans", json=_plan(slug))
    assert r.status_code == 200, r.text
    plan_id = r.json()["fee_plan_id"]
    env = (await api.get("/admin/admissions/plans")).json()
    (p,) = [x for x in env["data"] if x["slug"] == slug]
    assert p["active"] is False and p["fee_paise"] == FEE and p["fee_plan_id"] == plan_id
    assert set(env) == {"data", "pay", "batches"}
    assert r.json()["course_status"] == "coming_soon" and r.json()["effective_status"] == "coming_soon"

    # inactive plan: the course can't open (409 no_fee_plan); the new course reads coming_soon
    r = await api.put(f"/admin/courses/{slug}/status", json={"status": "open"})
    assert r.status_code == 409 and r.json()["code"] == "no_fee_plan", r.text
    assert (await api.get("/public/courses/status")).json()["data"][slug] == "coming_soon"
    pub = await api.get(f"/public/admissions/plans/{slug}")
    assert pub.status_code == 200 and pub.json()["registration_open"] is False

    # Edit (same id, same slug): activate. Payment details are needed first.
    r = await api.put("/admin/admissions/plans", json=_plan(slug, active=True, fee_plan_id=plan_id))
    assert r.status_code == 422 and r.json()["errors"][0]["code"] == "pay_to_missing", r.text
    await _pay(api)
    r = await api.put("/admin/admissions/plans", json=_plan(slug, active=True, fee_plan_id=plan_id))
    assert r.status_code == 200 and r.json()["active"] is True and r.json()["fee_plan_id"] == plan_id

    # Edit cannot move the plan to another slug (it would leave the old course and registrations behind)
    r = await api.put("/admin/admissions/plans", json=_plan(slug + "-x", fee_plan_id=plan_id))
    assert r.status_code == 409 and r.json()["errors"][0]["code"] == "slug_locked", r.text
    r = await api.put("/admin/admissions/plans", json=_plan(slug, fee_plan_id=str(uuid7())))
    assert r.status_code == 404, r.text
    plans = (await api.get("/admin/admissions/plans")).json()["data"]
    assert [x["slug"] for x in plans if x["slug"].startswith(slug)] == [slug]

    r = await api.put(f"/admin/courses/{slug}/status", json={"status": "open"})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "open" and r.json()["effective_status"] == "open"
    assert (await api.get("/public/courses/status")).json()["data"][slug] == "open"
    pub = (await api.get(f"/public/admissions/plans/{slug}")).json()
    assert pub["registration_open"] is True and pub["fee_paise"] == FEE and pub["pay_configured"] is True

    # Deactivating while open: the switch stays "open" but every reader sees "closed"
    r = await api.put("/admin/admissions/plans", json=_plan(slug, active=False, fee_plan_id=plan_id))
    assert r.status_code == 200, r.text
    assert r.json()["course_status"] == "open" and r.json()["effective_status"] == "closed"  # SPA warns
    rows = {x["course_slug"]: x for x in (await api.get("/admin/courses/status")).json()["data"]}
    assert rows[slug]["status"] == "open" and rows[slug]["effective_status"] == "closed"
    assert rows[slug]["plan_active"] is False and rows[slug]["title"] == "NextGen Career Accelerator 2026"
    assert (await api.get("/public/courses/status")).json()["data"][slug] == "closed"
    assert (await api.get(f"/public/admissions/plans/{slug}")).json()["registration_open"] is False


async def test_new_plan_refused_for_pay_to_leaves_no_course_row(api: httpx.AsyncClient) -> None:
    slug = f"np-{uuid.uuid4().hex[:6]}"
    r = await api.put("/admin/admissions/plans", json=_plan(slug, active=True))
    assert r.status_code == 422 and r.json()["errors"][0]["code"] == "pay_to_missing", r.text
    rows = [x["course_slug"] for x in (await api.get("/admin/courses/status")).json()["data"]]
    assert slug not in rows
    assert slug not in (await api.get("/public/courses/status")).json()["data"]
    assert slug not in [x["slug"] for x in (await api.get("/admin/admissions/plans")).json()["data"]]


async def test_plan_active_switch(api: httpx.AsyncClient) -> None:
    slug = f"sw-{uuid.uuid4().hex[:6]}"
    r = await api.put("/admin/admissions/plans", json=_plan(slug, title="Switch me", upi_id="x"))
    assert r.status_code == 422  # bad UPI ID (sanity: per-plan pay-to is validated)
    r = await api.put("/admin/admissions/plans", json=_plan(slug, title="Switch me"))
    assert r.status_code == 200, r.text
    r = await api.post(f"/admin/admissions/plans/{slug}/active", json={"active": True})
    assert r.status_code == 422 and r.json()["errors"][0]["code"] == "pay_to_missing", r.text
    await _pay(api)
    r = await api.post(f"/admin/admissions/plans/{slug}/active", json={"active": True})
    assert r.status_code == 200, r.text
    assert r.json()["active"] is True and r.json()["title"] == "Switch me" and r.json()["fee_paise"] == FEE
    assert (await api.put(f"/admin/courses/{slug}/status", json={"status": "open"})).status_code == 200
    r = await api.post(f"/admin/admissions/plans/{slug}/active", json={"active": False})
    assert r.status_code == 200, r.text
    assert r.json()["active"] is False
    assert r.json()["course_status"] == "open" and r.json()["effective_status"] == "closed"
    assert (await api.get("/public/courses/status")).json()["data"][slug] == "closed"
    r = await api.post(f"/admin/admissions/plans/{slug}/active", json={"active": True})
    assert r.json()["effective_status"] == "open"
    assert (
        await api.post("/admin/admissions/plans/nope-123/active", json={"active": True})
    ).status_code == 404
    assert (await api.post(f"/admin/admissions/plans/{slug}/active", json={})).status_code == 400


_PLANS: dict[str, uuid.UUID] = {}


async def _registration(slug: str, n: int, open_claims: int = 0) -> AdmissionRegistration:
    s = FakeSession().as_platform()
    if slug not in _PLANS:
        plan = AdmissionFeePlan(
            id=uuid7(), course_slug=slug, title="T", fee_paise=FEE, min_first_paise=FEE, access_min_paise=FEE
        )
        ads.add(s, plan)
        _PLANS[slug] = plan.id
    r = AdmissionRegistration(
        id=uuid7(),
        reg_no="TDR-" + uuid.uuid4().hex[:8].upper(),
        fee_plan_id=_PLANS[slug],
        course_slug=slug,
        course_title="T",
        name=f"Student {n}",
        email=f"s{n}-{uuid.uuid4().hex[:6]}@example.com",
        phone="+919876543210",
        college="RVCE",
        branch="CSE",
        year="3",
        fee_paise=FEE,
        access_min_paise=FEE,
        policy="full",
        allow_instalments=False,
        min_first_paise=FEE,
        balance_paise=FEE,
        consent_text="ok",
        consent_at=utcnow(),
        status="pending_verification",
        open_claims=open_claims,
    )
    ads.add(s, r)
    await s.commit()
    return r


async def _claim(reg: AdmissionRegistration, utr: str, at_offset: int, status: str = "rejected") -> uuid.UUID:
    s = FakeSession().as_platform()
    now = utcnow()
    cid = uuid7()
    ads.add(
        s,
        AdmissionPaymentClaim(
            id=cid,
            registration_id=reg.id,
            provider="manual_upi",
            method="upi",
            amount_paise=FEE,
            utr=utr,
            paid_on=date.today() - timedelta(days=at_offset),
            proof_key=f"k/{utr}",
            proof_sha256=uuid.uuid4().hex * 2,
            status=status,
            reviewed_at=None if status == "pending" else now,
            locks_released=status != "pending",
            submitted_at=now - timedelta(minutes=at_offset),
        ),
    )
    await s.commit()
    return cid


async def test_registrations_list_filters_last_payment_and_paging(api: httpx.AsyncClient) -> None:
    slug = f"rg-{uuid.uuid4().hex[:6]}"
    a = await _registration(slug, 1)
    b = await _registration(slug, 2)
    await _registration(f"other-{uuid.uuid4().hex[:6]}", 3)
    await _claim(a, "111111111111", at_offset=30)  # older
    await _claim(a, "222222222222", at_offset=1, status="pending")  # newest

    r = await api.get("/admin/admissions/registrations", params={"course_slug": slug})
    assert r.status_code == 200, r.text
    rows = {x["registration_id"]: x for x in r.json()["data"]}
    assert set(rows) == {str(a.id), str(b.id)}
    # the most recent payment (DISTINCT ON on Postgres)
    assert rows[str(a.id)]["last_utr"] == "222222222222"
    assert rows[str(a.id)]["last_claim_status"] == "pending"
    assert rows[str(b.id)]["last_utr"] is None
    assert rows[str(a.id)]["has_account"] is False and rows[str(a.id)]["letter"] is None

    page1 = (
        await api.get("/admin/admissions/registrations", params={"course_slug": slug, "limit": 1})
    ).json()
    assert len(page1["data"]) == 1 and page1["page"]["next_cursor"]
    page2 = (
        await api.get(
            "/admin/admissions/registrations",
            params={"course_slug": slug, "limit": 1, "cursor": page1["page"]["next_cursor"]},
        )
    ).json()
    assert (
        len(page2["data"]) == 1 and page2["data"][0]["registration_id"] != page1["data"][0]["registration_id"]
    )

    st = await api.get("/admin/admissions/registrations", params={"course_slug": slug, "status": "enrolled"})
    assert st.status_code == 200 and st.json()["data"] == []
    q = await api.get("/admin/admissions/registrations", params={"q": "Student 2", "course_slug": slug})
    assert [x["registration_id"] for x in q.json()["data"]] == [str(b.id)]

    d = await api.get(f"/admin/admissions/registrations/{a.id}")
    assert d.status_code == 200, d.text
    assert [c["utr"] for c in d.json()["claims"]] == ["222222222222", "111111111111"]

    claims = await api.get("/admin/admissions/claims", params={"registration_id": str(a.id)})
    assert claims.status_code == 200, claims.text
    assert [c["utr"] for c in claims.json()["data"]] == ["222222222222"]

    ov = await api.get("/admin/admissions/overview")
    assert ov.status_code == 200, ov.text
    (course,) = [c for c in ov.json()["courses"] if c["slug"] == slug]
    assert course["registered"] == 2 and course["pending"] == 1


async def test_registration_and_claim_actions(api: httpx.AsyncClient) -> None:
    """The registration panel and queue actions on Firestore: contact, needs-info, verify,
    reverse, record payment, fee change, status, enrol, reject + release, verify-and-enrol."""
    slug = f"ac-{uuid.uuid4().hex[:6]}"
    x = await _registration(slug, 1, open_claims=1)
    c1 = await _claim(x, "333333333333", at_offset=2, status="pending")
    base = f"/admin/admissions/registrations/{x.id}"

    r = await api.patch(f"{base}/contact", json={"phone": "98765 43211"})
    assert r.status_code == 200, r.text
    r = await api.patch(f"{base}/contact", json={"phone": "12345"})
    assert r.status_code == 422 and r.json()["errors"][0]["code"] == "invalid_mobile"

    r = await api.post(f"/admin/admissions/claims/{c1}/needs-info", json={"reason": "Blurry screenshot"})
    assert r.status_code == 200, r.text
    r = await api.post(f"/admin/admissions/claims/{c1}/verify", json={"amount_paise": FEE, "checked": False})
    assert r.status_code == 422, r.text
    r = await api.post(f"/admin/admissions/claims/{c1}/verify", json={"amount_paise": FEE, "checked": True})
    assert r.status_code == 200, r.text
    reg = r.json()["registration"]
    assert reg["verified_total_paise"] == FEE and reg["balance_paise"] == 0
    assert "enrolment didn't finish" in (r.json().get("warning") or "")  # plan not linked to a batch

    r = await api.post(f"/admin/admissions/claims/{c1}/reverse", json={"reason": "Bounced"})
    assert r.status_code == 200, r.text
    assert r.json()["registration"]["verified_total_paise"] == 0

    r = await api.post(
        f"{base}/payments",
        json={
            "amount_paise": 200_000,
            "method": "cash",
            "utr": None,
            "paid_on": date.today().isoformat(),
            "note": None,
            "checked": True,
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["registration"]["verified_total_paise"] == 200_000
    assert r.json()["registration"]["status"] == "partially_paid"

    r = await api.post(f"{base}/fee", json={"fee_paise": 100_000, "reason": "Scholarship"})
    assert r.status_code == 422 and r.json()["errors"][0]["code"] == "below_verified", r.text
    r = await api.post(f"{base}/fee", json={"fee_paise": 400_000, "reason": "Scholarship"})
    assert r.status_code == 200, r.text
    assert (
        r.json()["registration"]["fee_paise"] == 400_000
        and r.json()["registration"]["balance_paise"] == 200_000
    )

    r = await api.post(f"{base}/status", json={"status": "cancelled", "reason": "Dropped out"})
    assert r.status_code == 200, r.text
    r = await api.post(f"{base}/status", json={"status": "reopen", "reason": "Came back"})
    assert r.status_code == 200, r.text
    assert r.json()["registration"]["status"] == "partially_paid"

    r = await api.post(f"{base}/enrol", json={})
    assert r.status_code in (409, 422), r.text  # not eligible yet (access needs the full fee)

    d = (await api.get(base)).json()
    assert [e["action"] for e in d["events"]]  # trail recorded

    # queue: reject with locks released, then verify-and-enrol needs a batch when the plan has none
    y = await _registration(slug, 2, open_claims=2)
    c2 = await _claim(y, "444444444444", at_offset=3, status="pending")
    c3 = await _claim(y, "555555555555", at_offset=1, status="pending")
    r = await api.post(
        f"/admin/admissions/claims/{c2}/reject", json={"reason": "Wrong UTR", "release_locks": True}
    )
    assert r.status_code == 200, r.text
    r = await api.post(f"/admin/admissions/claims/{c3}/verify-and-enrol", json={})
    assert r.status_code == 422 and r.json()["errors"][0]["code"] == "batch_required", r.text
    r = await api.post(f"/admin/admissions/claims/{c3}/verify-and-enrol", json={"batch_id": str(uuid7())})
    assert r.status_code == 422 and r.json()["errors"][0]["code"] == "unknown_batch", r.text
    # both refusals rolled back the verification
    q = (await api.get("/admin/admissions/claims", params={"registration_id": str(y.id)})).json()["data"]
    assert [c["status"] for c in q] == ["pending"]


def test_course_status_permissions() -> None:
    """Whoever sees the fee plans (``payment.read``) sees their course status; only
    ``price.manage`` changes it or a plan."""
    from app.modules.admissions import admin as adm

    def deps(path: str, method: str) -> set[Any]:
        (route,) = [r for r in adm.staff.routes if r.path == path and method in r.methods]  # type: ignore[attr-defined]
        return {d.call for d in route.dependant.dependencies}  # type: ignore[attr-defined]

    assert adm.READ.dependency in deps("/admin/courses/status", "GET")
    assert adm.READ.dependency in deps("/admin/admissions/plans", "GET")
    assert adm.PLANS.dependency in deps("/admin/courses/{slug}/status", "PUT")
    assert adm.PLANS.dependency in deps("/admin/admissions/plans", "PUT")
    assert adm.PLANS.dependency in deps("/admin/admissions/plans/{slug}/active", "POST")
