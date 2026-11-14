"""Regression tests for audit Phase B fixes in support (BE-16, BE-17 categories, BE-32 P1
derivation, ADM-38 queue order across pages)."""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from sqlalchemy import update

from app.core.db import system_context, tenant_context
from app.core.ids import uuid7
from app.core.principal import Principal
from app.modules.identity import clock
from app.modules.support.models import SupportTicket, SupportTicketMessage
from tests.identity.factory import Browser, add_member, company_org
from tests.security.helpers import adult, staff, staff_browser
from tests.support import helpers as h


def body(category: str) -> dict:
    return {
        "category": category,
        "subject": "Cannot open my batch",
        "body": "My batch does not show up on the dashboard after signing in.",
    }


async def _student(client, db, org=None):
    """A batch student of the company org (org member) when ``org`` is given."""
    u = await adult(db)
    if org is not None:
        await add_member(db, org, u.id, "student")
    b = Browser(client, ip="203.0.113.71")
    r = await b.login(u.email)
    assert r.json()["result"] == "authenticated", r.text
    return u, b


@pytest.mark.usefixtures("support_backend")
async def test_single_company_no_college_lane_or_org_field(client, db) -> None:
    """Single company: the ``college_access`` category and the ``organization_id`` body field
    are gone (422), tickets carry no organization, and DTOs no longer expose one."""
    _s, sb = await _student(client, db, company_org())
    assert (await sb.post("/support/tickets", body("college_access"))).status_code in (400, 422)
    with_org = {**body("technical"), "organization_id": str(company_org())}
    assert (await sb.post("/support/tickets", with_org)).status_code in (400, 422)
    t = (await sb.post("/support/tickets", body("technical"))).json()
    assert "organization_id" not in t
    await system_context(db, "t")
    row = await h.ticket(db, t["ticket_id"])
    assert row is not None and row.organization_id is None


async def test_rls_company_org_tickets_not_visible_to_other_members(client, db) -> None:
    """support_0004: tickets that still carry the company org id (legacy rows re-homed by
    orgs_0003) are readable only by their requester or platform staff — another batch student
    of the same org cannot read them at the database level."""
    org = company_org()
    a, sb = await _student(client, db, org)
    b, _ = await _student(client, db, org)
    t = (await sb.post("/support/tickets", body("technical"))).json()
    tid = uuid.UUID(t["ticket_id"])
    assert (
        await sb.post(f"/support/tickets/{tid}/messages", {"body": "More detail here"})
    ).status_code == 201
    await system_context(db, "t")
    await db.execute(update(SupportTicket).where(SupportTicket.id == tid).values(organization_id=org))
    await db.execute(
        update(SupportTicketMessage)
        .where(SupportTicketMessage.support_ticket_id == tid)
        .values(organization_id=org)
    )
    seen_by_b = await _ticket_count(db, Principal(b.id, uuid7(), org_ids=(org,)), tid)
    seen_by_a = await _ticket_count(db, Principal(a.id, uuid7(), org_ids=(org,)), tid)
    assert (seen_by_b, seen_by_a) == ((0, 0), (1, 1))


async def _ticket_count(db, principal, tid) -> tuple[int, int]:
    from sqlalchemy import text

    await tenant_context(db, principal)
    assert (await db.execute(text("select current_user"))).scalar() == "td_app"
    t = (await db.execute(text("select count(*) from support_tickets where id = :t"), {"t": tid})).scalar()
    m = (
        await db.execute(
            text("select count(*) from support_ticket_messages where support_ticket_id = :t"), {"t": tid}
        )
    ).scalar()
    await system_context(db, "t")
    return int(t or 0), min(int(m or 0), 1)


@pytest.mark.usefixtures("support_backend")
async def test_fr_sup_001_categories_and_lanes(client, db) -> None:
    """BE-17 (categories): certificate and appeal tickets can be created and land in the right
    lane (appeal -> Admin, certificate -> content managers and Admin)."""
    _s, sb = await _student(client, db)
    created = {}
    for cat in ("certificate", "appeal"):
        r = await sb.post("/support/tickets", body(cat))
        assert r.status_code == 201, r.text
        created[cat] = r.json()
    assert created["appeal"]["priority"] == "high"
    adm = await staff_browser(client, await staff(db, "super_admin"), ip="198.18.0.73")
    cm = await staff_browser(client, await staff(db, "content_manager"), ip="198.18.0.74")
    adm_ids = {t["ticket_id"] for t in (await adm.get("/support/queue")).json()["data"]}
    cm_ids = {t["ticket_id"] for t in (await cm.get("/support/queue")).json()["data"]}
    assert {created["appeal"]["ticket_id"], created["certificate"]["ticket_id"]} <= adm_ids
    assert created["certificate"]["ticket_id"] in cm_ids and created["appeal"]["ticket_id"] not in cm_ids


@pytest.mark.usefixtures("support_backend")
async def test_assessment_ticket_with_running_attempt_is_p1(client, db) -> None:
    """BE-32: an assessment ticket from a learner with a test in progress is P1 (``high``,
    first response 4 h); without a running attempt it stays ``normal``."""
    from datetime import datetime

    from sqlalchemy import text

    u, sb = await _student(client, db)
    normal = (await sb.post("/support/tickets", body("assessment"))).json()
    assert normal["priority"] == "normal"

    await system_context(db, "t")
    test_id = uuid.uuid4()
    await db.execute(
        text(
            "INSERT INTO tests (id, test_kind, title, review_policy, created_by) "
            "VALUES (:t, 'mock', 'Mock 1', '{}'::jsonb, :u)"
        ),
        {"t": test_id, "u": u.id},
    )
    await db.execute(
        text(
            "INSERT INTO test_attempts (id, test_id, test_version, user_id, attempt_no, status, "
            "selection_seed, layout, idempotency_key) VALUES (:a, :t, 1, :u, 1, 'in_progress', "
            "decode('00112233445566778899aabbccddeeff', 'hex'), '{}'::jsonb, 'k1')"
        ),
        {"a": uuid.uuid4(), "t": test_id, "u": u.id},
    )
    raised = (await sb.post("/support/tickets", body("assessment"))).json()
    assert raised["priority"] == "high"
    window = datetime.fromisoformat(raised["first_response_due_at"]) - datetime.fromisoformat(
        raised["created_at"]
    )
    assert window == timedelta(hours=4)


@pytest.mark.usefixtures("support_backend")
async def test_queue_sla_order_across_pages(client, db) -> None:
    """ADM-38: the queue is ordered by resolution deadline across pages, not within a page."""
    _s, sb = await _student(client, db)
    agent = await staff(db, "super_admin")
    ab = await staff_browser(client, agent, ip="198.18.0.75")
    ids = [(await sb.post("/support/tickets", body("other"))).json()["ticket_id"] for _ in range(5)]
    await system_context(db, "t")
    now = clock.now()
    # newest ticket has the earliest deadline
    for i, tid in enumerate(ids):
        await h.patch_ticket(db, tid, resolution_due_at=now + timedelta(hours=100 - i * 10))
    order: list[str] = []
    cursor = None
    while True:
        params = {"category": "other", "limit": 2, **({"cursor": cursor} if cursor else {})}
        page = (await ab.get("/support/queue", params=params)).json()
        order += [t["ticket_id"] for t in page["data"] if t["ticket_id"] in ids]
        cursor = page["page"]["next_cursor"]
        if not page["page"]["has_more"]:
            break
    assert order == list(reversed(ids))


@pytest.mark.usefixtures("support_backend")
async def test_be17_attachments_upload_attach_and_download(client, db) -> None:
    """BE-17 attachments: MED-02 ``support_attachment`` upload, attach on SUP-01/SUP-04 (own
    keys only), download for requester and platform agent, 404 for outsiders."""
    s, sb = await _student(client, db)
    up = await sb.post(
        "/media/uploads/file",
        {
            "purpose": "support_attachment",
            "filename": "screen shot.png",
            "content_type": "image/png",
            "size_bytes": 2048,
        },
    )
    assert up.status_code == 201, up.text
    key = up.json()["s3_key"]
    assert key.startswith(f"uploads/support_attachment/{s.id}/")
    att = {"s3_key": key, "filename": "screen.png", "content_type": "image/png", "size_bytes": 2048}
    t = await sb.post("/support/tickets", {**body("technical"), "attachments": [att]})
    assert t.status_code == 201, t.text
    tid = t.json()["ticket_id"]
    assert t.json()["attachments"] == [
        {"filename": "screen.png", "content_type": "image/png", "size_bytes": 2048}
    ]
    m = await sb.post(f"/support/tickets/{tid}/messages", {"body": "more", "attachments": [att]})
    assert m.status_code == 201 and m.json()["attachments"][0]["filename"] == "screen.png", m.text
    foreign = {**att, "s3_key": f"uploads/support_attachment/{uuid.uuid4()}/x/screen.png"}
    bad = await sb.post(f"/support/tickets/{tid}/messages", {"body": "x", "attachments": [foreign]})
    assert bad.status_code in (400, 422) and bad.json()["code"] == "validation_failed"
    d = await sb.get(f"/support/tickets/{tid}/attachments/ticket/0")
    assert d.status_code == 200 and "X-Amz-Signature" in d.json()["url"], d.text
    assert (await sb.get(f"/support/tickets/{tid}/attachments/{m.json()['message_id']}/0")).status_code == 200
    assert (await sb.get(f"/support/tickets/{tid}/attachments/ticket/1")).status_code == 404
    agent = await staff(db, "super_admin")
    ab = await staff_browser(client, agent, ip="198.18.0.79")
    assert (await ab.get(f"/support/tickets/{tid}/attachments/ticket/0")).status_code == 200
    _o, ob = await _student(client, db)
    assert (await ob.get(f"/support/tickets/{tid}/attachments/ticket/0")).status_code == 404


@pytest.mark.usefixtures("support_backend")
async def test_db01_support_erasure_minimises_tickets(client, db) -> None:
    from app.modules.support import privacy

    s, sb = await _student(client, db)
    t = (await sb.post("/support/tickets", body("technical"))).json()
    assert (
        await sb.post(f"/support/tickets/{t['ticket_id']}/messages", {"body": "my phone is 9999"})
    ).status_code == 201
    await system_context(db, "t")
    out = await privacy.erase_user(db, s.id)
    assert out["tickets_minimised"] == 1 and out["messages_redacted"] == 1
    row = await h.ticket(db, t["ticket_id"])
    assert row.subject == privacy.ERASED_SUBJECT and row.body == privacy.ERASED_BODY and row.context == {}
    (msg,) = await h.thread(db, row.id)
    assert msg.redacted_at is not None and "9999" not in msg.body
    again = await privacy.erase_user(db, s.id)
    assert again["tickets_minimised"] == 0 and again["messages_redacted"] == 0
