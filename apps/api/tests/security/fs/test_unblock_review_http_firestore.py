"""Pass 1 through the FastAPI app on Firestore (no Postgres): unblock request lifecycle (learner),
review queues and case detail (reviewer), support triage list."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from app.core.db import NO_POSTGRES
from app.core.firestore.store import ScopedStore
from app.core.ids import uuid7
from app.modules.identity import clock
from app.modules.identity import public as idp
from app.modules.identity.models import User
from app.modules.security import models as m
from app.modules.security import store_specs as sp
from tests.audit.fs.support import sample_row

FS_MODULES = ("security", "identity", "sessions", "rbac", "admin", "audit", "core", "notifications", "orgs")
EXPLAIN = "I share this laptop with my brother at home; it is the only device we have."


async def _setup(make_principal: Any) -> tuple[Any, dict[str, Any]]:
    me = make_principal(is_minor=False, restriction_level=3)
    now = clock.now()
    await idp.create_user(
        NO_POSTGRES,
        User(
            id=me.user_id,
            email=f"u{uuid7().hex[-8:]}@example.com",
            email_verified_at=now,
            status="active",
            is_minor=False,
            age_verified_at=now,
            age_verification_method="self_declared",
        ),
    )
    case = {
        **sample_row(m.SecurityCase),
        "id": uuid7(),
        "user_id": me.user_id,
        "case_ref": "SEC-2026-QWERTY",
        "family": "sharing",
        "level": 3,
        "status": "open",
        "priority": "medium",
        "assignee_id": None,
        "first_response_at": None,
        "high_risk_reasons": [],
        "panel_views": {},
        "assigned_to": None,
        "version": 1,
        "sla_decision_due": now + timedelta(days=2),
        "closed_at": None,
        "created_at": now,
        "updated_at": now,
    }
    restr = {
        **sample_row(m.AccountRestriction),
        "id": uuid7(),
        "user_id": me.user_id,
        "case_id": case["id"],
        "level": 3,
        "family": "sharing",
        "scope": "learning_access",
        "ended_at": None,
        "lift_pending_at": None,
        "deferred_until": None,
        "ends_at": now + timedelta(days=7),
        "created_at": now,
        "updated_at": now,
    }
    st = ScopedStore.system("firestore.backfill")
    await st.import_documents("security_cases", [(str(case["id"]), sp.CaseRow.from_pg(case).doc())])
    await st.import_documents(
        "account_restrictions", [(str(restr["id"]), sp.RestrictionRow.from_pg(restr).doc())]
    )
    await st.import_documents(
        "restriction_heads", [(f"{me.user_id}:sharing", {"active_id": str(restr["id"])})]
    )
    return me, case


async def test_learner_unblock_lifecycle(fs_http: Any, make_principal: Any) -> None:
    client, _rec, auth = fs_http
    me, case = await _setup(make_principal)
    h = auth.login(me)
    form = await client.get(
        "/api/v1/security/unblock-requests/form", params={"case_ref": case["case_ref"]}, headers=h
    )
    assert form.status_code == 200, form.text
    r = await client.post(
        "/api/v1/security/unblock-requests",
        json={
            "case_ref": case["case_ref"],
            "what_happened": ["shared_computer"],
            "explanation": EXPLAIN,
            "declaration": True,
        },
        headers={**h, "Idempotency-Key": str(uuid7())},
    )
    assert r.status_code == 201, r.text
    ur = r.json()
    assert ur["state"] == "draft" and ur["reference"].startswith("APL-")
    dup = await client.post(
        "/api/v1/security/unblock-requests",
        json={"case_ref": case["case_ref"]},
        headers={**h, "Idempotency-Key": str(uuid7())},
    )
    assert dup.status_code == 409 and dup.json()["code"] == "unblock_request_open"
    lst = (await client.get("/api/v1/security/unblock-requests", headers=h)).json()["data"]
    assert [x["reference"] for x in lst] == [ur["reference"]] and lst[0]["case_ref"] == case["case_ref"]
    by_ref = await client.get(f"/api/v1/security/unblock-requests/by-reference/{ur['reference']}", headers=h)
    assert by_ref.status_code == 200
    other = auth.login(make_principal())
    assert (
        await client.get(f"/api/v1/security/unblock-requests/by-reference/{ur['reference']}", headers=other)
    ).status_code == 404
    rid = ur["request_id"]
    sub = await client.post(
        f"/api/v1/security/unblock-requests/{rid}/submit",
        json={"none_recognised": True},
        headers={**h, "Idempotency-Key": str(uuid7())},
    )
    assert sub.status_code == 200, sub.text
    assert sub.json()["state"] != "draft"
    one = (await client.get(f"/api/v1/security/unblock-requests/{rid}", headers=h)).json()
    assert one["reference"] == ur["reference"]

    rv = make_principal(
        is_platform=True, roles=("super_admin",), tier="privileged", last_step_up_at=clock.now()
    )
    for perm in (
        "security.case.read",
        "security.unblock.triage",
        "security.case.assign",
        "security.case.note",
    ):
        auth.grant(rv, perm)
    hr = auth.login(rv)
    cases = await client.get("/api/v1/security/cases", headers=hr)
    assert cases.status_code == 200, cases.text
    assert [c["case_ref"] for c in cases.json()["data"]] == [case["case_ref"]]
    assert cases.json()["counts"] == {"open": 1}
    detail = await client.get(
        f"/api/v1/security/cases/{case['id']}", params={"reason_code": "case_review"}, headers=hr
    )
    assert detail.status_code == 200, detail.text
    queue = await client.get("/api/v1/security/review/unblock-requests", headers=hr)
    assert queue.status_code == 200, queue.text
    assert [x["reference"] for x in queue.json()["data"]] == [ur["reference"]]
    support = await client.get("/api/v1/support/unblock-requests", headers=hr)
    assert support.status_code == 200, support.text
    assert support.json()["data"][0]["case_ref"] == case["case_ref"]
    assert support.json()["data"][0]["restrictions"][0]["level"] == 3
    note = await client.post(
        f"/api/v1/security/cases/{case['id']}/notes",
        json={"body": "Checked device graph; looks like a family PC.", "visibility": "internal"},
        headers=hr,
    )
    assert note.status_code == 201, note.text

    wd = await client.post(
        f"/api/v1/security/unblock-requests/{rid}/withdraw", headers={**h, "Idempotency-Key": str(uuid7())}
    )
    assert wd.status_code in (200, 409), wd.text


def _reviewer(make_principal: Any, auth: Any) -> dict[str, str]:
    rv = make_principal(
        is_platform=True, roles=("super_admin",), tier="privileged", last_step_up_at=clock.now()
    )
    for perm in (
        "security.case.read",
        "security.unblock.triage",
        "security.case.assign",
        "security.case.note",
        "security.case.decide",
        "security.restriction.apply_l1l2",
        "security.restriction.apply_l3l4",
        "security.restriction.lift_l1l2",
        "security.restriction.lift_l3l4",
        "security.evidence.read",
        "security.status.read",
    ):
        auth.grant(rv, perm)
    return auth.login(rv)


async def test_reviewer_case_and_unblock_actions(fs_http: Any, make_principal: Any) -> None:
    client, _rec, auth = fs_http
    me, case = await _setup(make_principal)
    h = auth.login(me)
    r = await client.post(
        "/api/v1/security/unblock-requests",
        json={
            "case_ref": case["case_ref"],
            "what_happened": ["shared_computer"],
            "explanation": EXPLAIN,
            "declaration": True,
            "submit": True,
            "none_recognised": True,
        },
        headers={**h, "Idempotency-Key": str(uuid7())},
    )
    assert r.status_code == 201, r.text
    rid = r.json()["request_id"]
    hr = _reviewer(make_principal, auth)

    claim = await client.post(
        f"/api/v1/security/cases/{case['id']}/claim", headers={**hr, "If-Match": '"v1"'}
    )
    assert claim.status_code == 200, claim.text
    assert claim.json()["status"] == "under_review" and claim.headers["etag"] == '"v2"'
    stale = await client.post(
        f"/api/v1/security/cases/{case['id']}/claim", headers={**hr, "If-Match": '"v1"'}
    )
    assert stale.status_code == 412

    det = await client.get(
        f"/api/v1/security/review/unblock-requests/{rid}", params={"reason_code": "appeal"}, headers=hr
    )
    assert det.status_code == 200, det.text
    info = await client.post(
        f"/api/v1/security/review/unblock-requests/{rid}/request-info",
        json={"template_key": "shared_computer_details"},
        headers={**hr, "Idempotency-Key": str(uuid7()), "If-Match": det.headers.get("etag", '"v1"')},
    )
    assert info.status_code in (200, 409), info.text

    lst = await client.get(
        "/api/v1/security/restrictions",
        params={"user_id": str(me.user_id), "reason_code": "case_review"},
        headers=hr,
    )
    assert lst.status_code == 200, lst.text
    assert [x["level"] for x in lst.json()["data"]] == [3]
    evs = await client.get(
        "/api/v1/security/evaluations",
        params={"user_id": str(me.user_id), "reason_code": "case_review"},
        headers=hr,
    )
    assert evs.status_code == 200, evs.text

    other = make_principal()
    await idp.create_user(
        NO_POSTGRES,
        User(
            id=other.user_id,
            email=f"o{uuid7().hex[-8:]}@example.com",
            email_verified_at=clock.now(),
            status="active",
            is_minor=False,
            age_verified_at=clock.now(),
            age_verification_method="self_declared",
        ),
    )
    manual = await client.post(
        "/api/v1/security/cases",
        json={"user_id": str(other.user_id), "note": "Escalated by support after a call."},
        headers={**hr, "Idempotency-Key": str(uuid7())},
    )
    assert manual.status_code == 201, manual.text
    assert manual.json()["case_ref"].startswith("SEC-")


async def test_decision_notes_assign_explanation(fs_http: Any, make_principal: Any) -> None:
    client, _rec, auth = fs_http
    me, case = await _setup(make_principal)
    hr = _reviewer(make_principal, auth)
    cid = case["id"]
    rc = {"reason_code": "case_review"}
    expl = await client.get(f"/api/v1/security/cases/{cid}/explanation", params=rc, headers=hr)
    assert expl.status_code == 200, expl.text
    n = await client.post(
        f"/api/v1/security/cases/{cid}/notes",
        json={"body": "We are looking into it.", "visibility": "student"},
        headers=hr,
    )
    assert n.status_code == 201, n.text
    mine = (await client.get(f"/api/v1/me/security/cases/{case['case_ref']}", headers=auth.login(me))).json()
    assert [x["body"] for x in mine["notes"]] == ["We are looking into it."]
    claim = await client.post(f"/api/v1/security/cases/{cid}/claim", headers={**hr, "If-Match": '"v1"'})
    assert claim.status_code == 200, claim.text
    tl = await client.get(
        f"/api/v1/security/users/{me.user_id}/timeline",
        params={**rc, "case_ref": case["case_ref"]},
        headers=hr,
    )
    assert tl.status_code == 200, tl.text
    d = await client.post(
        f"/api/v1/security/cases/{cid}/decisions",
        json={
            "outcome": "uphold",
            "rationale": "Evidence of two cities within an hour.",
            "student_summary": "We reviewed your account and the restriction stays in place for now. "
            "You can appeal once.",
        },
        headers={**hr, "Idempotency-Key": str(uuid7()), "If-Match": claim.headers["etag"]},
    )
    assert d.status_code in (200, 201, 202), d.text
    mine = (await client.get(f"/api/v1/me/security/cases/{case['case_ref']}", headers=auth.login(me))).json()
    assert mine["decision"]["outcome"] == "uphold"
