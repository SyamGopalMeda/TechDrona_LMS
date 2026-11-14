"""Support desk (SUP-01..15): tickets, SLA, internal notes, lanes, merge/escalate, limited user
lookup with masking, support-triggered emails, audit, and permission denials."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from sqlalchemy import update

from app.modules.identity import clock
from app.modules.identity.models import User
from tests.identity.factory import Browser
from tests.security.helpers import adult, idem, staff, staff_browser
from tests.support import helpers as h

pytestmark = pytest.mark.usefixtures("support_backend")


def ticket_body(category: str = "device_reset", **kw):
    return {
        "category": category,
        "subject": "Cannot sign in on my new laptop",
        "body": "It says I have too many devices. Please help me remove the old one.",
        "context": {"route": "/login", "browser": "Chrome 130", "os": "Windows"},
        **kw,
    }


async def student_browser(client, db):
    u = await adult(db)
    b = Browser(client, ip="203.0.113.44")
    r = await b.login(u.email)
    assert r.json()["result"] == "authenticated", r.text
    return u, b


async def test_ticket_lifecycle_sla_internal_notes_and_csat(client, db) -> None:
    _u, sb = await student_browser(client, db)
    agent = await staff(db, "super_admin")
    ab = await staff_browser(client, agent, ip="198.18.0.21")

    bad = await sb.post("/support/tickets", ticket_body(subject="no"))
    assert bad.status_code in (400, 422)
    created = await sb.post("/support/tickets", ticket_body(), headers=idem())
    assert created.status_code == 201, created.text
    t = created.json()
    assert t["status"] == "open" and t["priority"] == "high" and t["ticket_number"].startswith("TD-T-")
    first_due = datetime.fromisoformat(t["first_response_due_at"]) - datetime.fromisoformat(t["created_at"])
    assert first_due == timedelta(hours=4) and not t["sla"]["first_response_breached"]
    tid = t["ticket_id"]

    mine = (await sb.get("/me/support/tickets")).json()["data"]
    assert [x["ticket_id"] for x in mine] == [tid]

    q = await ab.get("/support/queue")
    assert q.status_code == 200 and any(x["ticket_id"] == tid for x in q.json()["data"])
    row = next(x for x in q.json()["data"] if x["ticket_id"] == tid)
    assert "****@" in row["requester"]["email_masked"] and q.json()["counts"]["open"] >= 1

    assigned = await ab.patch(f"/support/tickets/{tid}", {"assign_to_me": True})
    assert assigned.status_code == 200 and assigned.json()["assigned_to"] == str(agent.id)
    note = await ab.post(
        f"/support/tickets/{tid}/messages", {"body": "Checked devices: 3 trusted.", "visibility": "internal"}
    )
    assert note.status_code == 201 and note.json()["visibility"] == "internal"
    reply = await ab.post(
        f"/support/tickets/{tid}/messages", {"body": "Please remove one device in Settings."}
    )
    assert reply.status_code == 201 and reply.json()["author_kind"] == "agent"

    student_view = (await sb.get(f"/support/tickets/{tid}")).json()
    assert student_view["viewer"] == "requester" and student_view["status"] == "pending_user"
    assert [m["visibility"] for m in student_view["messages"]] == ["public"]
    assert student_view["first_responded_at"] is not None
    agent_view = (await ab.get(f"/support/tickets/{tid}")).json()
    assert agent_view["viewer"] == "agent" and {m["visibility"] for m in agent_view["messages"]} == {
        "public",
        "internal",
    }

    sneaky = await sb.post(f"/support/tickets/{tid}/messages", {"body": "hi", "visibility": "internal"})
    assert sneaky.status_code == 403
    back = await sb.post(f"/support/tickets/{tid}/messages", {"body": "Still stuck, sorry."})
    assert back.status_code == 201
    assert (await sb.get(f"/support/tickets/{tid}")).json()["status"] == "open"

    early_csat = await sb.post(f"/support/tickets/{tid}/csat", {"score": 5})
    assert early_csat.status_code == 409
    resolved = await ab.patch(f"/support/tickets/{tid}", {"status": "resolved"})
    assert resolved.json()["status"] == "resolved" and resolved.json()["resolved_at"]
    assert (
        await sb.post(f"/support/tickets/{tid}/csat", {"score": 4, "comment": "Quick"})
    ).status_code == 200
    assert (await sb.post(f"/support/tickets/{tid}/csat", {"score": 5})).status_code == 409
    reopened = await sb.post(f"/support/tickets/{tid}/reopen", {"reason": "It broke again"})
    assert reopened.json()["status"] == "open" and reopened.json()["resolved_at"] is None
    closed = await ab.patch(f"/support/tickets/{tid}", {"status": "closed"})
    assert closed.json()["status"] == "closed"
    assert (await sb.post(f"/support/tickets/{tid}/messages", {"body": "again"})).status_code == 409
    assert (await sb.post(f"/support/tickets/{tid}/reopen", {})).status_code == 409

    # SLA breach shows once the deadline passes (first response missed on a fresh ticket).
    t2 = (await sb.post("/support/tickets", ticket_body("technical"))).json()
    await h.patch_ticket(db, t2["ticket_id"], first_response_due_at=clock.now() - timedelta(minutes=1))
    q2 = (await ab.get("/support/queue", params={"category": "technical"})).json()
    late = next(x for x in q2["data"] if x["ticket_id"] == t2["ticket_id"])
    assert late["sla"]["first_response_breached"] and q2["counts"]["breached"] >= 1


async def test_lanes_cross_user_isolation_escalation_merge_and_rate_limit(client, db) -> None:
    u, sb = await student_browser(client, db)
    _other, ob = await student_browser(client, db)
    agent = await staff(db, "super_admin")
    ab = await staff_browser(client, agent, ip="198.18.0.22")
    cm = await staff(db, "content_manager")
    cmb = await staff_browser(client, cm, ip="198.18.0.23")

    dev = (await sb.post("/support/tickets", ticket_body())).json()
    bill = (await sb.post("/support/tickets", ticket_body("billing", subject="Charged twice"))).json()
    content = (await sb.post("/support/tickets", ticket_body("content", subject="Video broken"))).json()

    assert (await ob.get(f"/support/tickets/{dev['ticket_id']}")).status_code == 404
    assert (await ob.post(f"/support/tickets/{dev['ticket_id']}/messages", {"body": "x"})).status_code == 404
    assert (await ob.get("/me/support/tickets")).json()["data"] == []
    assert (await sb.get("/support/queue")).status_code == 403
    assert (await sb.patch(f"/support/tickets/{dev['ticket_id']}", {"status": "closed"})).status_code == 403
    assert (await sb.get("/support/macros")).status_code == 403
    assert len((await ab.get("/support/macros")).json()["data"]) >= 3

    # Admin (D2: support/finance/security folded into Admin) sees every lane.
    admin_ids = {x["ticket_id"] for x in (await ab.get("/support/queue")).json()["data"]}
    assert {dev["ticket_id"], bill["ticket_id"], content["ticket_id"]} <= admin_ids
    # Content managers keep the content lane only.
    cm_ids = {x["ticket_id"] for x in (await cmb.get("/support/queue")).json()["data"]}
    assert (
        content["ticket_id"] in cm_ids and dev["ticket_id"] not in cm_ids and bill["ticket_id"] not in cm_ids
    )
    assert (await cmb.get(f"/support/tickets/{dev['ticket_id']}")).status_code == 404

    esc = await ab.post(
        f"/support/tickets/{dev['ticket_id']}/escalate", {"to": "content", "note": "Course video issue"}
    )
    assert esc.status_code == 200 and esc.json()["status"] == "pending_internal"
    cm_ids = {x["ticket_id"] for x in (await cmb.get("/support/queue")).json()["data"]}
    assert dev["ticket_id"] in cm_ids  # escalation lane

    bad_assign = await ab.patch(f"/support/tickets/{dev['ticket_id']}", {"assigned_to": str(u.id)})
    assert bad_assign.status_code == 422

    foreign = (await ob.post("/support/tickets", ticket_body("other"))).json()
    cross = await ab.post(
        f"/support/tickets/{dev['ticket_id']}/merge", {"into_ticket_id": foreign["ticket_id"]}
    )
    assert cross.status_code == 422
    merged = await ab.post(
        f"/support/tickets/{bill['ticket_id']}/merge", {"into_ticket_id": dev["ticket_id"]}
    )
    assert merged.status_code == 200 and merged.json()["ticket_id"] == dev["ticket_id"]
    src = (await sb.get(f"/support/tickets/{bill['ticket_id']}")).json()
    assert src["status"] == "closed" and src["merged_into_id"] == dev["ticket_id"]

    # 10 tickets per day per requester (3 already created)
    for _ in range(7):
        assert (await sb.post("/support/tickets", ticket_body("other"))).status_code == 201
    limited = await sb.post("/support/tickets", ticket_body("other"))
    assert limited.status_code == 429


async def test_user_lookup_masking_notes_and_support_emails(client, db, mail, audited) -> None:
    u, sb = await student_browser(client, db)
    t = (await sb.post("/support/tickets", ticket_body("account_access"))).json()
    agent = await staff(db, "super_admin")
    ab = await staff_browser(client, agent, ip="198.18.0.24")

    assert (await ab.get(f"/support/users/{u.id}")).json()["code"] == "reason_code_required"
    assert (await sb.get(f"/support/users/{u.id}", params={"reason_code": "ticket"})).status_code == 403
    look = await ab.get(
        f"/support/users/{u.id}", params={"reason_code": "ticket", "ticket_id": t["ticket_id"]}
    )
    assert look.status_code == 200, look.text
    body = look.json()
    assert body["email_masked"].count("*") >= 4 and u.email not in look.text
    assert body["restriction"] is None and body["email_verified"] and body["devices"]["total"] >= 1
    assert any(x["ticket_id"] == t["ticket_id"] for x in body["tickets"])
    assert all(s["ip_masked"] != "203.0.113.44" for s in body["active_sessions"])
    assert "support.user_lookup" in audited

    note = await ab.post(
        f"/support/users/{u.id}/notes", {"body": "Called the student", "ticket_id": t["ticket_id"]}
    )
    assert note.status_code == 201
    look2 = await ab.get(f"/support/users/{u.id}", params={"reason_code": "ticket"})
    assert look2.json()["notes"][0]["body"] == "Called the student"

    verified = await ab.post(f"/support/users/{u.id}/resend-verification", {"reason_code": "ticket"})
    assert verified.status_code == 409
    await db.execute(update(User).where(User.id == u.id).values(email_verified_at=None))
    sent = await ab.post(
        f"/support/users/{u.id}/resend-verification", {"reason_code": "ticket"}, headers=idem()
    )
    assert sent.status_code == 202 and sent.json()["sent_to"].count("*") >= 4
    assert "/verify/email/" in mail.sent[-1].text

    reset = await ab.post(f"/support/users/{u.id}/password-reset-email", {"reason_code": "ticket"})
    assert reset.status_code == 202, reset.text
    assert "/reset-password/" in mail.sent[-1].text
    assert {"support.verification_resent", "support.password_reset_sent"} <= set(audited)
    no_reason = await ab.post(f"/support/users/{u.id}/password-reset-email", {"reason_code": "gossip"})
    assert no_reason.json()["code"] == "reason_code_required"
