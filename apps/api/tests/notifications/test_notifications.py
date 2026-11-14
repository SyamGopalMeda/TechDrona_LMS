"""Notifications: inbox (NTF-01..03), minors' marketing suppression, batch announcements
(NTF-06), SMTP adapter against the local Mailpit, fake SMS adapter masking."""

from __future__ import annotations

import json
import socket
import uuid

import httpx
import pytest
from sqlalchemy import text

from app.core.db import system_context
from app.modules.notifications.adapters import ConsoleSmsAdapter, OutboundEmail, OutboundSms, SmtpEmailAdapter
from app.modules.notifications.service import notifications_for_user, notify
from tests.identity.factory import add_member, company_org, grant, make_batch, make_user, staff_login


@pytest.mark.usefixtures("notifications_backend")
async def test_inbox_list_read_and_read_all(browser, db) -> None:
    u = await make_user(db)
    await system_context(db, "t")
    ids = [await notify(db, u.id, f"test.n{i}", category="system", data={"i": i}) for i in range(3)]
    await db.flush()
    await browser.login(u.email)
    r = await browser.get("/me/notifications", params={"limit": 2})
    body = r.json()
    assert (
        r.status_code == 200
        and body["unread_count"] == 3
        and len(body["data"]) == 2
        and body["page"]["has_more"]
    )
    r2 = await browser.get("/me/notifications", params={"limit": 2, "cursor": body["page"]["next_cursor"]})
    assert len(r2.json()["data"]) == 1
    assert (await browser.post(f"/me/notifications/{ids[0]}/read")).status_code == 200
    assert (await browser.get("/me/notifications")).json()["unread_count"] == 2
    assert (await browser.post("/me/notifications/read-all")).json()["marked"] == 2
    # another user's notification is invisible
    other = await make_user(db)
    await system_context(db, "t")
    nid = await notify(db, other.id, "test.private", category="system")
    assert (await browser.post(f"/me/notifications/{nid}/read")).status_code == 404


@pytest.mark.usefixtures("notifications_backend")
async def test_marketing_suppressed_for_minors_and_dedupe(db) -> None:
    kid = await make_user(db, minor=True)
    await system_context(db, "t")
    assert await notify(db, kid.id, "promo", category="marketing", is_minor=True) is None
    a = await notify(db, kid.id, "learn", category="learning", dedupe_key="k1")
    b = await notify(db, kid.id, "learn", category="learning", dedupe_key="k1")
    assert a is not None and b is None
    with pytest.raises(ValueError):
        await notify(db, kid.id, "x", category="nonsense")


@pytest.mark.usefixtures("notifications_backend")
async def test_batch_announcement_by_trainer_with_daily_cap(browser, db, mail) -> None:
    org = company_org()
    founder = await make_user(db)
    batch = await make_batch(db, org, founder.id)
    other_batch = await make_batch(db, org, founder.id)
    trainer = await make_user(db, with_totp=True)
    await add_member(db, org, trainer.id, "staff", batch)
    await grant(db, trainer.id, "trainer", "batch", batch)
    kids = [await make_user(db) for _ in range(2)]
    for k in kids:
        await add_member(db, org, k.id, "student", batch)
    gone = await make_user(db)
    await add_member(db, org, gone.id, "student", batch)
    await system_context(db, "t")
    await db.execute(
        text("UPDATE batch_members SET status='removed', removed_at=now() WHERE user_id=:u"), {"u": gone.id}
    )
    await staff_login(browser, trainer)
    for i in range(3):
        r = await browser.post(
            f"/batches/{batch}/announcements",
            {"title": f"T{i}", "body": "Mock test Friday", "send_email": i == 0},
        )
        assert r.status_code == 201 and r.json()["recipients"] == 2, r.text  # removed member skipped
    r = await browser.post(f"/batches/{batch}/announcements", {"title": "T4", "body": "again"})
    assert r.status_code == 429
    assert sum(1 for m in mail.sent if m.subject == "T0") == 2
    await system_context(db, "t")
    rows = await notifications_for_user(db, kids[0].id)
    assert len(rows) == 3 and all(n.organization_id == org for n in rows)
    # another batch of the company is not reachable for this trainer
    assert (
        await browser.post(f"/batches/{other_batch}/announcements", {"title": "x", "body": "y"})
    ).status_code == 403


def _mailpit_up() -> bool:
    try:
        with socket.create_connection(("localhost", 8025), timeout=1):
            return True
    except OSError:
        return False


@pytest.mark.skipif(not _mailpit_up(), reason="Mailpit (docker compose) is not running")
async def test_smtp_adapter_delivers_to_mailpit() -> None:
    marker = f"td-test-{uuid.uuid4().hex[:12]}"
    adapter = SmtpEmailAdapter(host="localhost", port=1025)
    mid = await adapter.send(
        OutboundEmail("someone@example.com", f"Subject {marker}", "hello", template_key="t")
    )
    assert mid
    async with httpx.AsyncClient() as c:
        r = await c.get("http://localhost:8025/api/v1/search", params={"query": marker})
    assert r.status_code == 200 and json.loads(r.text)["messages_count"] >= 1


async def test_fake_sms_logs_masked_number_only() -> None:
    from structlog.testing import capture_logs

    adapter = ConsoleSmsAdapter()
    with capture_logs() as logs:
        await adapter.send(OutboundSms("+919876543221", "482913 is your code", "otp"))
    out = json.dumps(logs)
    assert "+91 98xxxxxx21" in out and "9876543221" not in out and "482913" not in out
    assert adapter.sent[-1].text.startswith("482913")
