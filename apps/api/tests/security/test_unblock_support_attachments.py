"""Support unblock triage (UNB-17/18, SEC-21 by support; ADM-27 / INV-06), unblock attachments
(UNB-03/16; INV-12), the draft submit and info-request loop (UNB-04/07/13; INV-16) and the
DB-05 RLS split (learners cannot write their own enforcement rows)."""

from __future__ import annotations

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from app.core.db import set_rls_context, system_context
from app.modules.identity import clock
from app.modules.security import engine
from app.modules.security import restrictions as rx
from app.modules.security.models import AccountRestriction, CaseNote, UnblockRequest
from tests.security.helpers import adult, idem, staff, staff_browser
from tests.security.test_scn_unblock import EXPL, restricted_student, submit_request


async def _l2(db):
    u = await adult(db)
    case = await engine.open_case(db, user_id=u.id, family="sharing", level=2, opened_reason="engine_L3")
    r, _ = await rx.apply_restriction(
        db,
        user_id=u.id,
        level=2,
        family="sharing",
        source="engine",
        actor=engine.SYSTEM,
        case_id=case.id,
        rule_keys=["SH-01"],
    )
    return u, case, r


async def test_support_list_ids_forward_and_lift_l1l2_only(client, db, sms) -> None:
    _u, b, case, r3, laptop_ud, _ = await restricted_student(db, client)
    sub = await submit_request(b, case.case_ref, laptop_ud)
    assert sub.status_code in (200, 201), sub.text
    sup = await staff(db, "super_admin")
    bs = await staff_browser(client, sup, ip="198.18.0.21")

    rows = (await bs.get("/support/unblock-requests")).json()["data"]
    row = next(x for x in rows if x["reference"] == sub.json()["reference"])
    assert row["request_id"] == sub.json()["request_id"]
    assert row["route"] == "security" and row["level"] == 3 and row["case_ref"] == case.case_ref
    assert row["restrictions"] == [
        {"restriction_id": str(r3.id), "level": 3, "family": "sharing", "liftable_by_support": False}
    ]
    assert "explanation" not in row and "what_happened" not in row  # no evidence for support

    # L3 cannot be lifted by support: it needs a case decision
    no = await bs.post(f"/security/restrictions/{r3.id}/lift", {"reason": "caller asked"})
    assert no.status_code == 409 and no.json()["code"] == "decision_required", no.text

    # UNB-18 forward: internal note, priority raised, audited
    fw = await bs.post(
        f"/support/unblock-requests/{row['request_id']}/forward", {"reason": "L3, please review"}
    )
    assert fw.status_code == 200 and fw.json()["forwarded"] is True and fw.json()["priority"] == "high", (
        fw.text
    )
    await system_context(db, "test.notes")
    notes = (
        await db.execute(
            select(CaseNote.body).where(CaseNote.case_id == case.id, CaseNote.visibility == "internal")
        )
    ).scalars()
    assert any(x.startswith("Forwarded by support: L3, please review") for x in notes)

    # forward of a closed request is refused
    ur = await db.get(UnblockRequest, sub.json()["request_id"])
    ur.state, ur.closure_reason = "closed", "withdrawn"
    await db.flush()
    again = await bs.post(
        f"/support/unblock-requests/{row['request_id']}/forward", {"reason": "again please"}
    )
    assert again.status_code == 409 and again.json()["code"] == "invalid_state_transition"

    # an L2 restriction is liftable by support (SEC-21, security.restriction.lift_l1l2)
    _u2, _c2, r2 = await _l2(db)
    ok = await bs.post(f"/security/restrictions/{r2.id}/lift", {"reason": "OTP verified on call"})
    assert ok.status_code == 200 and ok.json()["state"] == "ended", ok.text
    end = (
        await db.execute(select(AccountRestriction.end_reason).where(AccountRestriction.id == r2.id))
    ).scalar()
    assert end == "case_decision"


async def test_unblock_attachments_upload_and_reviewer_view(client, db, sms) -> None:
    _u, b, case, _r, laptop_ud, _ = await restricted_student(db, client)
    draft = await b.post(
        "/security/unblock-requests", {"case_ref": case.case_ref, "submit": False}, headers=idem()
    )
    assert draft.status_code == 201, draft.text
    rid = draft.json()["request_id"]
    url = f"/security/unblock-requests/{rid}/attachments"

    form = (await b.get("/security/unblock-requests/form", params={"case_ref": case.case_ref})).json()
    assert form["attachments"]["max_files"] == 2 and "application/pdf" in form["attachments"]["content_types"]

    bad_type = await b.post(
        url, {"filename": "x.exe", "content_type": "application/x-msdownload", "size_bytes": 10}
    )
    assert bad_type.status_code == 415
    too_big = await b.post(
        url, {"filename": "a.pdf", "content_type": "application/pdf", "size_bytes": 6 * 1024 * 1024}
    )
    assert too_big.status_code == 413
    a1 = await b.post(
        url, {"filename": "../exit letter.pdf", "content_type": "application/pdf", "size_bytes": 2048}
    )
    assert a1.status_code == 201, a1.text
    up = a1.json()
    assert up["filename"] == "exit_letter.pdf" and up["upload"]["fields"]["Content-Type"] == "application/pdf"
    assert f"/{rid}/" in up["upload"]["fields"]["key"]
    a2 = await b.post(url, {"filename": "photo.jpg", "content_type": "image/jpeg", "size_bytes": 4096})
    assert a2.status_code == 201
    a3 = await b.post(url, {"filename": "more.png", "content_type": "image/png", "size_bytes": 10})
    assert a3.status_code == 422 and a3.json()["code"] == "validation_failed"

    # someone else's request is invisible
    other = await adult(db)
    from tests.identity.factory import Browser

    bo = Browser(client)
    assert (await bo.login(other.email)).json()["result"] == "authenticated"
    assert (
        await bo.post(url, {"filename": "a.pdf", "content_type": "application/pdf", "size_bytes": 10})
    ).status_code == 404

    view = (await b.get(f"/security/unblock-requests/{rid}")).json()
    assert [a["attachment_id"] for a in view["attachments"]] == [
        up["attachment_id"],
        a2.json()["attachment_id"],
    ]
    assert all("s3_key" not in a for a in view["attachments"])

    # submit the draft (UNB-04): attachments travel with the request
    for k, v in {
        "what_happened": ["family_member_used"],
        "explanation": EXPL,
        "recognised_user_device_ids": [str(laptop_ud)],
        "preferred_contact": "sms",
        "declaration": True,
    }.items():
        assert (await b.patch(f"/security/unblock-requests/{rid}", {k: v})).status_code == 200
    sub = await b.post(f"/security/unblock-requests/{rid}/submit", {}, headers=idem())
    assert sub.status_code == 200 and sub.json()["state"] == "submitted", sub.text
    late = await b.post(url, {"filename": "c.pdf", "content_type": "application/pdf", "size_bytes": 10})
    assert late.status_code == 409  # only while draft / info requested / appealable

    rv = await staff(db)
    rb = await staff_browser(client, rv, ip="198.18.0.22")
    att_url = f"/security/review/unblock-requests/{rid}/attachments/{up['attachment_id']}"
    assert (await rb.get(att_url)).json()["code"] == "reason_code_required"
    ok = await rb.get(att_url, params={"reason_code": "case_review"})
    assert ok.status_code == 200, ok.text
    body = ok.json()
    assert body["download"] is False and "X-Amz-Signature=" in body["url"]
    assert "response-content-disposition" not in body["url"]
    assert (
        await rb.get(
            f"/security/review/unblock-requests/{rid}/attachments/nope", params={"reason_code": "case_review"}
        )
    ).status_code == 404
    detail = (
        await rb.get(f"/security/review/unblock-requests/{rid}", params={"reason_code": "case_review"})
    ).json()
    assert detail["attachments"][0]["scan_status"] == "clean" and "s3_key" not in detail["attachments"][0]
    sup = await staff(db, "evaluator")
    bs = await staff_browser(client, sup, ip="198.18.0.23")
    assert (await bs.get(att_url, params={"reason_code": "case_review"})).status_code == 403  # no evidence


async def test_request_info_and_student_response_loop(client, db, sms) -> None:
    _u, b, case, _r, laptop_ud, _ = await restricted_student(db, client)
    sub = await submit_request(b, case.case_ref, laptop_ud)
    rid = sub.json()["request_id"]
    rv = await staff(db)
    rb = await staff_browser(client, rv, ip="198.18.0.24")

    async def tag() -> str:
        r = await rb.get(f"/security/review/unblock-requests/{rid}", params={"reason_code": "case_review"})
        return r.headers["etag"]

    cl = await rb.post(
        f"/security/review/unblock-requests/{rid}/claim", {}, headers={"If-Match": await tag()}
    )
    assert cl.status_code == 200, cl.text
    info = await rb.post(
        f"/security/review/unblock-requests/{rid}/request-info",
        {"template_key": "shared_computer_details", "message": "Where is it?"},
        headers={"If-Match": await tag()},
    )
    assert info.status_code == 200 and info.json()["state"] == "info_requested", info.text
    view = (await b.get(f"/security/unblock-requests/{rid}")).json()
    assert view["state"] == "info_requested" and view["info_requested_due"]
    # attachments may be added while information is requested
    att = await b.post(
        f"/security/unblock-requests/{rid}/attachments",
        {"filename": "lab.pdf", "content_type": "application/pdf", "size_bytes": 99},
    )
    assert att.status_code == 201
    resp = await b.post(
        f"/security/unblock-requests/{rid}/responses",
        {
            "explanation": "It was the CSE lab, room 204, on the second floor of the main block, every Tuesday."
        },
        headers=idem(),
    )
    assert resp.status_code == 200 and resp.json()["state"] == "under_review", resp.text
    again = await b.post(
        f"/security/unblock-requests/{rid}/responses",
        {
            "explanation": "It was the CSE lab, room 204, on the second floor of the main block, every Tuesday."
        },
        headers=idem(),
    )
    assert again.status_code == 409


async def test_db05_learner_cannot_write_own_enforcement_rows(db) -> None:
    u, case, r = await _l2(db)
    await db.flush()
    await set_rls_context(db, user_id=str(u.id))
    # the owner can still read
    assert (
        await db.execute(select(AccountRestriction.id).where(AccountRestriction.id == r.id))
    ).scalar_one() == r.id
    for table, ident in (("account_restrictions", r.id), ("security_cases", case.id)):
        upd = await db.execute(text(f"update {table} set updated_at = now() where id = :i"), {"i": ident})
        assert upd.rowcount == 0, table  # write policy hides the row from UPDATE
        nested = await db.begin_nested()
        with pytest.raises(DBAPIError, match="permission denied"):
            await db.execute(text(f"delete from {table} where id = :i"), {"i": ident})
        await nested.rollback()
    for table in ("security_user_state", "security_notices", "unblock_requests"):
        upd = await db.execute(text(f"update {table} set user_id = user_id where user_id = :u"), {"u": u.id})
        assert upd.rowcount == 0, table
        dele = await db.execute(text(f"delete from {table} where user_id = :u"), {"u": u.id})
        assert dele.rowcount == 0, table
    nested = await db.begin_nested()
    with pytest.raises(DBAPIError, match="row-level security"):
        await db.execute(
            text(
                "insert into account_restrictions (id,user_id,level,family,scope,source)"
                " values (gen_random_uuid(),:u,1,'sharing','learning_access','engine')"
            ),
            {"u": u.id},
        )
    await nested.rollback()
    # platform scope (staff / system jobs) keeps write access
    await system_context(db, "test.db05")
    upd = await db.execute(
        text("update account_restrictions set updated_at = now() where id = :i"), {"i": r.id}
    )
    assert upd.rowcount == 1
    _ = clock
