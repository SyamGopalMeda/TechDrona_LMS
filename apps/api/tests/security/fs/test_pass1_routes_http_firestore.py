"""Round 6: every remaining pass-1 security route through the FastAPI app on Firestore, no
Postgres (assign, decision approvals, restrictions, manual verification, unblock review actions,
support forward, PII reveal, disown, responses, appeal, reverify, attachments)."""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any

from app.core.firestore.store import ScopedStore
from app.core.ids import uuid7
from app.modules.identity import clock
from app.modules.security import models as m
from app.modules.security import store_specs as sp
from tests.audit.fs.support import sample_row
from tests.security.fs.test_unblock_review_http_firestore import EXPLAIN, _reviewer, _setup

FS_MODULES = ("security", "identity", "sessions", "rbac", "admin", "audit", "core", "notifications", "orgs")
P = "/api/v1"


def _idem() -> dict[str, str]:
    return {"Idempotency-Key": str(uuid.uuid4())}


async def _submitted(client: Any, h: dict[str, str], case_ref: str) -> dict[str, Any]:
    r = await client.post(
        f"{P}/security/unblock-requests",
        json={
            "case_ref": case_ref,
            "what_happened": ["shared_computer"],
            "explanation": EXPLAIN,
            "declaration": True,
            "submit": True,
            "none_recognised": True,
        },
        headers={**h, **_idem()},
    )
    assert r.status_code == 201, r.text
    return r.json()


async def _etag(client: Any, hr: dict[str, str], rid: str) -> str:
    det = await client.get(
        f"{P}/security/review/unblock-requests/{rid}", params={"reason_code": "appeal"}, headers=hr
    )
    assert det.status_code == 200, det.text
    return det.headers["etag"]


async def test_unblock_review_actions(fs_http: Any, make_principal: Any) -> None:
    client, _rec, auth = fs_http
    me, case = await _setup(make_principal)
    h = auth.login(me)
    ur = await _submitted(client, h, case["case_ref"])
    rid = ur["request_id"]
    hr = _reviewer(make_principal, auth)

    c = await client.post(
        f"{P}/security/review/unblock-requests/{rid}/claim",
        headers={**hr, "If-Match": await _etag(client, hr, rid)},
    )
    assert c.status_code == 200, c.text
    ri = await client.post(
        f"{P}/security/review/unblock-requests/{rid}/request-info",
        json={"template_key": "shared_computer_details"},
        headers={**hr, "If-Match": c.headers["etag"]},
    )
    assert ri.status_code == 200, ri.text
    assert ri.json()["state"] == "info_requested"
    resp = await client.post(
        f"{P}/security/unblock-requests/{rid}/responses",
        json={"explanation": "It is the computer lab at my college library, desk 4."},
        headers={**h, **_idem()},
    )
    assert resp.status_code == 200, resp.text
    esc = await client.post(
        f"{P}/security/review/unblock-requests/{rid}/escalate",
        json={"reason": "Needs a senior look"},
        headers={**hr, "If-Match": await _etag(client, hr, rid)},
    )
    assert esc.status_code == 200, esc.text
    fw = await client.post(
        f"{P}/support/unblock-requests/{rid}/forward", json={"reason": "Student called"}, headers=hr
    )
    assert fw.status_code == 200, fw.text
    assert fw.json()["forwarded"] is True and fw.json()["priority"] in ("high", "urgent")
    sb = await client.post(
        f"{P}/security/review/unblock-requests/{rid}/send-back",
        json={"note": "Please take this back to triage"},
        headers={**hr, "If-Match": await _etag(client, hr, rid)},
    )
    assert sb.status_code == 403 and sb.json()["rule"] == "SoD-06"  # the escalating reviewer cannot
    hr2 = _reviewer(make_principal, auth)
    sb2 = await client.post(
        f"{P}/security/review/unblock-requests/{rid}/send-back",
        json={"note": "Please take this back to triage"},
        headers={**hr2, "If-Match": await _etag(client, hr2, rid)},
    )
    assert sb2.status_code == 200, sb2.text
    assert sb2.json()["state"] == "under_review"


async def _ready_case(client: Any, hr: dict[str, str], case: dict[str, Any], me: Any) -> str:
    rc = {"reason_code": "case_review"}
    cid = case["id"]
    assert (
        await client.get(f"{P}/security/cases/{cid}/explanation", params=rc, headers=hr)
    ).status_code == 200
    tl = await client.get(
        f"{P}/security/users/{me.user_id}/timeline", params={**rc, "case_ref": case["case_ref"]}, headers=hr
    )
    assert tl.status_code == 200, tl.text
    det = await client.get(f"{P}/security/cases/{cid}", params=rc, headers=hr)
    return det.headers["etag"]


LIFT = {
    "outcome": "lift_conditions",
    "rationale": "Contact change needed before lifting.",
    "student_summary": "We will lift the restriction once your contact details are updated, as agreed.",
    "conditions": {"contact_change": True},
}


async def _catalogue() -> None:
    """Real rbac roles/permissions in Firestore: security's ``has_perm`` checks grants against the
    rbac catalogue (not the test FakeAuth)."""
    from app.modules.rbac.service import reset_role_permission_cache
    from tests.identity.fs.conftest import seed_catalogue

    await seed_catalogue()
    reset_role_permission_cache()


async def test_assign_and_decision_approvals(fs_http: Any, make_principal: Any) -> None:
    client, _rec, auth = fs_http
    await _catalogue()
    me, case = await _setup(make_principal)
    cid = case["id"]
    hr = _reviewer(make_principal, auth)
    other_rv = make_principal(
        is_platform=True, roles=("super_admin",), tier="privileged", last_step_up_at=clock.now()
    )
    for perm in (
        "security.case.read",
        "security.case.decide",
        "approval.decide",
        "security.evidence.read",
        "security.case.assign",
    ):
        auth.grant(other_rv, perm)
    h2 = auth.login(other_rv)

    et = await _ready_case(client, hr, case, me)
    a = await client.post(
        f"{P}/security/cases/{cid}/assign",
        json={"assignee_id": str(other_rv.user_id)},
        headers={**hr, "If-Match": et},
    )
    assert a.status_code == 200, a.text
    assert a.json()["assignee_id"] == str(other_rv.user_id)
    et = a.headers["etag"]

    p1 = await client.post(
        f"{P}/security/cases/{cid}/decisions", json=LIFT, headers={**hr, **_idem(), "If-Match": et}
    )
    assert p1.status_code == 202, p1.text
    ar1 = p1.json()["approval_request_id"]
    et = (
        await client.get(f"{P}/security/cases/{cid}", params={"reason_code": "case_review"}, headers=hr)
    ).headers["etag"]
    wd = await client.post(
        f"{P}/security/cases/{cid}/approval-requests/{ar1}/withdraw", headers={**hr, "If-Match": et}
    )
    assert wd.status_code == 200, wd.text

    et = await _ready_case(client, hr, case, me)
    p2 = await client.post(
        f"{P}/security/cases/{cid}/decisions", json=LIFT, headers={**hr, **_idem(), "If-Match": et}
    )
    assert p2.status_code == 202, p2.text
    ar2 = p2.json()["approval_request_id"]
    et = (
        await client.get(f"{P}/security/cases/{cid}", params={"reason_code": "case_review"}, headers=h2)
    ).headers["etag"]
    sb = await client.post(
        f"{P}/security/cases/{cid}/approval-requests/{ar2}/send-back",
        json={"note": "Add the evidence summary"},
        headers={**h2, "If-Match": et},
    )
    assert sb.status_code == 200, sb.text

    et = await _ready_case(client, hr, case, me)
    p3 = await client.post(
        f"{P}/security/cases/{cid}/decisions", json=LIFT, headers={**hr, **_idem(), "If-Match": et}
    )
    assert p3.status_code == 202, p3.text
    ar3 = p3.json()["approval_request_id"]
    et = (
        await client.get(f"{P}/security/cases/{cid}", params={"reason_code": "case_review"}, headers=h2)
    ).headers["etag"]
    ok = await client.post(
        f"{P}/security/cases/{cid}/approval-requests/{ar3}/approve",
        json={"note": "Agreed"},
        headers={**h2, **_idem(), "If-Match": et},
    )
    assert ok.status_code == 200, ok.text
    mine = (await client.get(f"{P}/me/security/cases/{case['case_ref']}", headers=auth.login(me))).json()
    assert mine["decision"]["outcome"] == "lift_conditions"


async def test_restrictions_manual_verification_pii(fs_http: Any, make_principal: Any) -> None:
    from app.core.db import NO_POSTGRES
    from app.modules.identity import public as idp
    from app.modules.identity.models import User
    from app.modules.sessions import public as spub
    from app.modules.sessions.models import AuthSession

    client, _rec, auth = fs_http
    await _catalogue()
    me, case = await _setup(make_principal)
    hr = _reviewer(make_principal, auth)

    b = make_principal(is_minor=False)
    now = clock.now()
    await idp.create_user(
        NO_POSTGRES,
        User(
            id=b.user_id,
            email=f"b{uuid7().hex[-8:]}@example.com",
            email_verified_at=now,
            status="active",
            is_minor=False,
            age_verified_at=now,
            age_verification_method="self_declared",
        ),
    )
    ap = await client.post(
        f"{P}/security/restrictions",
        json={"user_id": str(b.user_id), "level": 1, "rationale": "Repeated sharing signals"},
        headers={**hr, **_idem()},
    )
    assert ap.status_code == 201, ap.text
    rid = ap.json()["restriction_id"]
    again = await client.post(
        f"{P}/security/restrictions",
        json={"user_id": str(b.user_id), "level": 1, "rationale": "dup"},
        headers={**hr, **_idem()},
    )
    assert again.status_code == 409
    lift = await client.post(
        f"{P}/security/restrictions/{rid}/lift", json={"reason": "False positive"}, headers=hr
    )
    assert lift.status_code == 200, lift.text
    assert lift.json()["state"] == "ended"

    # L3 needs a decision, not a lift
    st = ScopedStore.system("t")
    l3 = (await st.query("account_restrictions", user_id=str(me.user_id), order_by=())).items[0]
    no = await client.post(f"{P}/security/restrictions/{l3.id}/lift", json={"reason": "please"}, headers=hr)
    assert no.status_code == 409 and no.json()["case_ref"] == case["case_ref"]

    # PII reveal of a session IP linked to the case user
    s_row = {
        **sample_row(AuthSession),
        "id": uuid7(),
        "user_id": me.user_id,
        "ip_first": "198.51.100.7",
        "status": "active",
    }
    await spub.add_session(NO_POSTGRES, AuthSession(**s_row))
    pii = await client.post(
        f"{P}/security/pii-reveals",
        json={
            "evidence_ref": f"as_{s_row['id']}",
            "reason_code": "case_review",
            "case_ref": case["case_ref"],
        },
        headers=hr,
    )
    assert pii.status_code == 200, pii.text
    assert pii.json()["value"] == "198.51.100.7"

    # manual verification: the L3 passed its end date and the student has no eligible contact
    await st.update("account_restrictions", l3.id, {"ends_at": now - timedelta(hours=1)})
    mv = await client.post(
        f"{P}/security/restrictions/{l3.id}/manual-verification",
        json={"method": "video_call", "note": "Verified on a video call with ID."},
        headers={**hr, **_idem()},
    )
    assert mv.status_code == 200, mv.text
    left = await st.get("account_restrictions", l3.id)
    assert left is not None and left["ended_at"] is not None


async def test_student_attachments_reverify_appeal(fs_http: Any, make_principal: Any, mail: Any) -> None:
    from app.core.db import NO_POSTGRES
    from app.modules.identity import public as idp
    from app.modules.security import public as secp
    from tests.identity.fixtures import last_code

    client, _rec, auth = fs_http
    await _catalogue()
    me, case = await _setup(make_principal)
    # a contact verified well before the restriction started: OTP re-verification is possible
    await idp.update_user(NO_POSTGRES, me.user_id, email_verified_at=clock.now() - timedelta(days=60))
    h = auth.login(me)
    r = await client.post(
        f"{P}/security/unblock-requests",
        json={
            "case_ref": case["case_ref"],
            "what_happened": ["shared_computer"],
            "explanation": EXPLAIN,
            "declaration": True,
        },
        headers={**h, **_idem()},
    )
    assert r.status_code == 201, r.text
    rid = r.json()["request_id"]
    up = await client.post(
        f"{P}/security/unblock-requests/{rid}/attachments",
        json={"filename": "lab photo.png", "content_type": "image/png", "size_bytes": 1000},
        headers={**h, **_idem()},
    )
    assert up.status_code == 201, up.text
    att_id = up.json()["attachment_id"]
    bad = await client.post(
        f"{P}/security/unblock-requests/{rid}/attachments",
        json={"filename": "x.exe", "content_type": "application/x-msdownload", "size_bytes": 10},
        headers={**h, **_idem()},
    )
    assert bad.status_code == 415
    sub = await client.post(
        f"{P}/security/unblock-requests/{rid}/submit",
        json={"none_recognised": True},
        headers={**h, **_idem()},
    )
    assert sub.status_code == 200, sub.text

    hr = _reviewer(make_principal, auth)
    key = (await secp.pending_unblock_attachment_keys(NO_POSTGRES, 10))[0]
    assert await secp.set_unblock_attachment_scan(NO_POSTGRES, key, "clean") == 1
    view = await client.get(
        f"{P}/security/review/unblock-requests/{rid}/attachments/{att_id}",
        params={"reason_code": "appeal"},
        headers=hr,
    )
    assert view.status_code == 200, view.text
    assert view.json()["attachment_id"] == att_id and view.json()["download"] is False

    # reviewer lifts as a false positive -> lift pending -> the student re-verifies by OTP
    et = await _ready_case(client, hr, case, me)
    dec = await client.post(
        f"{P}/security/cases/{case['id']}/decisions",
        json={
            "outcome": "lift_false_positive",
            "unblock_request_id": rid,
            "rationale": "Library computer confirmed.",
            "student_summary": "We checked and this was a shared library computer; "
            "please confirm it is you to finish.",
        },
        headers={**hr, **_idem(), "If-Match": et},
    )
    assert dec.status_code == 201, dec.text
    s = await client.post(f"{P}/auth/reverify/start", json={"channel": "email"}, headers=h)
    assert s.status_code == 200, s.text
    wrong = await client.post(
        f"{P}/auth/reverify/complete", json={"otp_code": "000000", "devices": []}, headers={**h, **_idem()}
    )
    assert wrong.status_code == 400 and wrong.json()["code"] == "otp_invalid"
    done = await client.post(
        f"{P}/auth/reverify/complete",
        json={"otp_code": last_code(mail), "devices": []},
        headers={**h, **_idem()},
    )
    assert done.status_code == 200, done.text
    assert done.json()["restriction_ended"] is True


async def test_appeal_after_uphold_and_disown(fs_http: Any, make_principal: Any) -> None:
    client, _rec, auth = fs_http
    await _catalogue()
    me, case = await _setup(make_principal)
    h = auth.login(me)
    ur = await _submitted(client, h, case["case_ref"])
    rid = ur["request_id"]
    hr = _reviewer(make_principal, auth)
    et = await _ready_case(client, hr, case, me)
    dec = await client.post(
        f"{P}/security/cases/{case['id']}/decisions",
        json={
            "outcome": "uphold",
            "unblock_request_id": rid,
            "rationale": "Clear evidence.",
            "student_summary": "We reviewed your request and the restriction stays for now; "
            "you may appeal once.",
        },
        headers={**hr, **_idem(), "If-Match": et},
    )
    assert dec.status_code == 201, dec.text
    ap = await client.post(
        f"{P}/security/unblock-requests/{rid}/appeal",
        json={"explanation": "I can show my library card and the desk booking for that day."},
        headers={**h, **_idem()},
    )
    assert ap.status_code == 200, ap.text
    twice = await client.post(
        f"{P}/security/unblock-requests/{rid}/appeal",
        json={"explanation": "Trying to appeal a second time, which is not allowed."},
        headers={**h, **_idem()},
    )
    assert twice.status_code == 409

    # disown a "new sign-in" notice: protect lock on the account
    notice = {
        **sample_row(m.SecurityNotice),
        "id": uuid7(),
        "user_id": me.user_id,
        "event_ref": "EVT-ABC123",
        "disowned_at": None,
    }
    await ScopedStore.system("firestore.backfill").import_documents(
        "security_notices", [(str(notice["id"]), sp.NoticeRow.from_pg(notice).doc())]
    )
    other = auth.login(make_principal())
    assert (
        await client.post(f"{P}/me/security/events/EVT-ABC123/disown", json={"confirm": True}, headers=other)
    ).status_code == 404
    d = await client.post(f"{P}/me/security/events/EVT-ABC123/disown", json={"confirm": True}, headers=h)
    assert d.status_code == 200, d.text
    assert d.json()["result"] == "protected"
    again = await client.post(f"{P}/me/security/events/EVT-ABC123/disown", json={"confirm": True}, headers=h)
    assert again.status_code == 409
