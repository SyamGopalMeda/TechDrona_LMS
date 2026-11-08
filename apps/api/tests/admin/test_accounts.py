"""ADM-01..05 (dashboard, user search/view, deactivate/reactivate, dual-control MFA reset = two
different admins) and ADM-17..19 break-glass (activation retired in the single-company build;
historic sessions can still be listed, ended, expired and reviewed by another Admin)."""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from sqlalchemy import select, update

from app.core.db import system_context
from app.core.ids import uuid7
from app.modules.admin.accounts import add_business_days, expire_break_glass
from app.modules.admin.models import BreakGlassSession
from app.modules.identity import clock
from app.modules.identity.models import MfaFactor
from app.modules.sessions.models import AuthSession
from tests.identity.factory import Browser
from tests.security.helpers import adult, idem, staff, staff_browser


async def test_dashboard_and_user_search_detail(client, db) -> None:
    sa = await staff(db, "super_admin")
    bsa = await staff_browser(client, sa, ip="198.18.1.1")
    sec = await staff(db, "content_manager")
    bsec = await staff_browser(client, sec, ip="198.18.1.2")
    student = await adult(db)

    dash = await bsa.get("/admin/dashboard")
    assert dash.status_code == 200, dash.text
    d = dash.json()
    assert d["users"]["total"] >= 3 and d["users"]["active"] >= 1
    assert {"support", "security", "approvals", "privacy", "break_glass", "commerce"} <= d.keys()
    assert "organizations" not in d  # single company: no org tiles
    assert (await bsec.get("/admin/dashboard")).status_code == 403

    found = await bsa.get("/admin/users", params={"q": student.email})
    assert found.status_code == 200 and [x["user_id"] for x in found.json()["data"]] == [str(student.id)]
    by_id = (await bsa.get("/admin/users", params={"q": str(sec.id)})).json()["data"]
    assert by_id[0]["roles"] == ["content_manager"]
    detail = await bsa.get(f"/admin/users/{sec.id}")
    body = detail.json()
    assert body["grants"][0]["role"] == "content_manager" and body["mfa"]["enrolled"] is True
    assert "organizations" not in body
    assert body["sessions"]["active"] >= 1 and body["break_glass_active"] is False
    sb = Browser(client)
    await sb.login(student.email)
    assert (await sb.get("/admin/users")).status_code == 403
    assert (await sb.get(f"/admin/users/{sec.id}")).status_code == 403


async def test_deactivate_and_reactivate_with_reason_step_up_and_idempotency(client, db) -> None:
    sa = await staff(db, "super_admin")
    student = await adult(db)
    sb = Browser(client)
    assert (await sb.login(student.email)).json()["result"] == "authenticated"

    bsa = await staff_browser(client, sa, ip="198.18.1.4")
    await db.execute(
        update(AuthSession)
        .where(AuthSession.user_id == sa.id)
        .values(last_step_up_at=clock.now() - timedelta(hours=1))
    )
    r = await bsa.post(f"/admin/users/{student.id}/deactivate", {"reason": "Fraud report"}, headers=idem())
    assert r.status_code == 401 and r.json()["code"] == "step_up_required"
    await db.execute(
        update(AuthSession).where(AuthSession.user_id == sa.id).values(last_step_up_at=clock.now())
    )
    assert (await bsa.post(f"/admin/users/{student.id}/deactivate", {"reason": "Fraud report"})).json()[
        "code"
    ] == "idempotency_key_required"
    assert (
        await bsa.post(f"/admin/users/{student.id}/deactivate", {"reason": "x"}, headers=idem())
    ).status_code in (400, 422)
    self_ = await bsa.post(f"/admin/users/{sa.id}/deactivate", {"reason": "Testing myself"}, headers=idem())
    assert self_.status_code == 403 and self_.json()["code"] == "sod_violation"

    key = idem()
    done = await bsa.post(f"/admin/users/{student.id}/deactivate", {"reason": "Fraud report"}, headers=key)
    assert done.status_code == 200 and done.json()["status"] == "deactivated"
    assert done.json()["sessions_revoked"] >= 1
    replay = await bsa.post(f"/admin/users/{student.id}/deactivate", {"reason": "Fraud report"}, headers=key)
    assert replay.json() == done.json()
    assert (await sb.get("/me")).status_code == 401
    again = await bsa.post(
        f"/admin/users/{student.id}/deactivate", {"reason": "Fraud report"}, headers=idem()
    )
    assert again.status_code == 409
    fresh = Browser(client)
    assert (await fresh.login(student.email)).status_code == 401

    support = await staff(db, "content_manager")
    bsup = await staff_browser(client, support, ip="198.18.1.5")
    denied = await bsup.post(f"/admin/users/{student.id}/reactivate", {"reason": "Cleared"}, headers=idem())
    assert denied.status_code == 403
    back = await bsa.post(
        f"/admin/users/{student.id}/reactivate", {"reason": "Report cleared"}, headers=idem()
    )
    assert back.status_code == 200 and back.json()["status"] == "active"
    assert (await sb.login(student.email)).json()["result"] == "authenticated"


async def test_mfa_reset_needs_a_second_admin(client, db) -> None:
    target = await staff(db, "trainer")
    a1 = await staff(db, "super_admin")
    a2 = await staff(db, "super_admin")
    cm = await staff(db, "content_manager")
    b1 = await staff_browser(client, a1, ip="198.18.1.6")
    b2 = await staff_browser(client, a2, ip="198.18.1.8")
    bcm = await staff_browser(client, cm, ip="198.18.1.7")

    body = {"reason": "Lost phone; verified on video call", "verification_method": "video_call"}
    assert (await bcm.post(f"/admin/users/{target.id}/mfa-reset", body, headers=idem())).status_code == 403
    req = await b1.post(f"/admin/users/{target.id}/mfa-reset", body, headers=idem())
    assert req.status_code == 202, req.text
    assert req.json()["status"] == "approval_pending" and req.json()["action_type"] == "user.mfa.reset"
    assert req.json()["required_approver_role"] == "super_admin"
    aid = req.json()["approval_request_id"]
    dup = await b1.post(f"/admin/users/{target.id}/mfa-reset", body, headers=idem())
    assert dup.status_code == 409

    own = await b1.post(f"/admin/approvals/{aid}/approve", {"note": "ok"}, headers=idem())
    assert own.json()["code"] == "sod_violation"  # maker != checker
    peer = await bcm.post(f"/admin/approvals/{aid}/approve", {"note": "ok"}, headers=idem())
    assert peer.status_code in (403, 404)  # non-admins cannot approve MFA resets
    await system_context(db, "t")
    assert (
        await db.execute(
            select(MfaFactor).where(MfaFactor.user_id == target.id, MfaFactor.revoked_at.is_(None))
        )
    ).first() is not None

    ok = await b2.post(f"/admin/approvals/{aid}/approve", {"note": "identity confirmed"}, headers=idem())
    assert ok.status_code == 200, ok.text
    assert ok.json()["status"] == "executed" and ok.json()["result"]["factors_removed"] >= 1
    await system_context(db, "t")
    left = (
        await db.execute(
            select(MfaFactor).where(MfaFactor.user_id == target.id, MfaFactor.revoked_at.is_(None))
        )
    ).first()
    assert left is None
    detail = await b2.get(f"/admin/users/{target.id}")
    assert detail.status_code == 200 and detail.json()["mfa"]["enrolled"] is False


async def _historic_session(db, user_id, *, minutes: int = 30) -> uuid.UUID:
    """A break-glass session as left by the pre-single-company build (activation is retired)."""
    await system_context(db, "test.bg")
    now = clock.now()
    bid = uuid7()
    db.add(
        BreakGlassSession(
            id=bid,
            user_id=user_id,
            reason="Incident INC-42: reviewer team unreachable, active takeover",
            status="active",
            started_at=now,
            expires_at=now + timedelta(minutes=minutes),
            review_due_at=add_business_days(now + timedelta(minutes=minutes), 2),
            created_at=now,
            updated_at=now,
        )
    )
    await db.flush()
    return bid


async def test_break_glass_activation_retired_history_still_managed(
    client, db, monkeypatch: pytest.MonkeyPatch
) -> None:
    sa1 = await staff(db, "super_admin")
    sa2 = await staff(db, "super_admin")
    cm = await staff(db, "content_manager")
    b1 = await staff_browser(client, sa1, ip="198.18.1.9")
    b2 = await staff_browser(client, sa2, ip="198.18.1.10")
    bcm = await staff_browser(client, cm, ip="198.18.1.11")

    act = await b1.post("/admin/break-glass", {"reason": "x" * 30}, headers=idem())
    assert act.status_code in (404, 405)  # retired: Admin already holds every break-glass permission
    assert (await bcm.get("/admin/break-glass")).status_code == 403

    bid = await _historic_session(db, sa1.id)
    row = (await db.execute(select(BreakGlassSession).where(BreakGlassSession.id == bid))).scalar_one()
    assert row.elevated_role == "super_admin"  # admin_0004 default
    listing = (await b2.get("/admin/break-glass")).json()
    assert any(x["break_glass_id"] == str(bid) for x in listing["data"]) and listing["active"] is None
    assert (await b1.get("/admin/break-glass")).json()["active"]["break_glass_id"] == str(bid)

    early_review = await b2.post(f"/admin/break-glass/{bid}/review", {"note": "Looks fine"})
    assert early_review.status_code == 409
    ended = await b1.post(f"/admin/break-glass/{bid}/end", {"note": "Resolved"})
    assert ended.status_code == 200 and ended.json()["status"] == "ended"
    assert ended.json()["review_status"] == "pending"
    inbox = (await b2.get("/me/notifications")).json()["data"]
    assert any(n["template_key"] == "admin.break_glass_ended" for n in inbox), inbox  # every Admin alerted
    own = await b1.post(f"/admin/break-glass/{bid}/review", {"note": "Self review"})
    assert own.json()["code"] == "sod_violation"
    reviewed = await b2.post(f"/admin/break-glass/{bid}/review", {"note": "Justified by INC-42 timeline"})
    assert reviewed.json()["review_status"] == "reviewed" and reviewed.json()["reviewed_by"] == str(sa2.id)

    # The expiry job still closes historic sessions.
    bid2 = await _historic_session(db, sa2.id)
    later = clock.now() + timedelta(hours=3)
    monkeypatch.setattr(clock, "now", lambda: later)
    await system_context(db, "admin.break_glass_expiry")
    assert await expire_break_glass(db) >= 1
    row2 = (await db.execute(select(BreakGlassSession).where(BreakGlassSession.id == bid2))).scalar_one()
    assert row2.status == "expired" and row2.end_reason == "expired"
    monkeypatch.undo()
