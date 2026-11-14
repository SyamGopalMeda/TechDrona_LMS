"""close_no_action (security_0004): a manually opened case with no restriction can be closed
without touching the account; it is refused while a restriction is active. Reason mandatory,
student summary optional, decision audited."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import select

from app.modules.identity.models import User
from app.modules.security.models import CaseDecision, CaseNote, SecurityCase
from tests.security.helpers import adult, idem, staff, staff_browser
from tests.security.test_scn_unblock import SUMMARY, decide, restricted_student, review_panels


async def _manual_case(db, client):
    u = await adult(db)
    reviewer = await staff(db)
    rb = await staff_browser(client, reviewer)
    r = await rb.post(
        "/security/cases",
        {
            "user_id": str(u.id),
            "note": "Support escalation: learner asked us to check sign-ins.",
            "priority": "low",
        },
        headers=idem(),
    )
    assert r.status_code == 201, r.text
    case = await db.get(SecurityCase, r.json()["case_id"])
    return u, rb, case


@pytest.fixture
def decide_audits(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Spy on ``audit()`` in the cases module (td_app cannot read audit_log / audit_outbox)."""
    from app.modules.security import cases

    seen: list[dict[str, Any]] = []
    real = cases.audit

    async def spy(session: Any, actor: Any, action: str, *a: Any, **kw: Any) -> Any:
        seen.append({"action": action, "target": a[1] if len(a) > 1 else None, **kw})
        return await real(session, actor, action, *a, **kw)

    monkeypatch.setattr(cases, "audit", spy)
    return seen


async def test_manual_case_closes_without_action(client, db, decide_audits) -> None:
    u, rb, case = await _manual_case(db, client)
    # the old outcomes still need a restriction, and now point at close_no_action
    await review_panels(rb, case)
    up = await decide(rb, case, "uphold")
    assert up.status_code == 409 and up.json()["allowed"] == ["close_no_action"], up.text
    # reason stays mandatory
    no_reason = await decide(rb, case, "close_no_action", rationale="", student_summary="")
    assert no_reason.status_code in (400, 422)
    # a short student summary is still refused when given
    short = await decide(rb, case, "close_no_action", student_summary="too short")
    assert short.status_code == 422 and short.json()["errors"][0]["field"] == "student_summary"
    # no level / conditions with this outcome
    lvl = await decide(rb, case, "close_no_action", student_summary="", resulting_level=1)
    assert lvl.status_code == 422
    ok = await decide(rb, case, "close_no_action", student_summary="")
    assert ok.status_code == 201, ok.text
    assert ok.json()["outcome"] == "close_no_action" and ok.json()["restriction"]["state"] is None
    db.expunge_all()
    c = await db.get(SecurityCase, case.id)
    assert c.status == "closed" and c.closed_at is not None
    d = (await db.execute(select(CaseDecision).where(CaseDecision.case_id == case.id))).scalar_one()
    assert d.outcome == "close_no_action" and d.rationale and d.student_summary is None
    notes = (
        (
            await db.execute(
                select(CaseNote).where(CaseNote.case_id == case.id, CaseNote.visibility == "student")
            )
        )
        .scalars()
        .all()
    )
    assert notes == []  # nothing is sent to a learner who may never have known about the case
    assert (await db.get(User, u.id)).restriction_level == 0
    rows = [a for a in decide_audits if a["action"] == "case.decide" and a["target"] == case.id]
    assert len(rows) == 1 and rows[0]["after"]["outcome"] == "close_no_action" and rows[0]["reason"]
    # a closed case takes no further decision
    again = await decide(rb, c, "close_no_action", student_summary="")
    assert again.status_code == 409


async def test_close_no_action_with_summary_posts_student_note(client, db) -> None:
    _u, rb, case = await _manual_case(db, client)
    await review_panels(rb, case)
    ok = await decide(rb, case, "close_no_action")  # SUMMARY (>= 50 chars) from the helper
    assert ok.status_code == 201, ok.text
    db.expunge_all()
    notes = (
        (
            await db.execute(
                select(CaseNote).where(CaseNote.case_id == case.id, CaseNote.visibility == "student")
            )
        )
        .scalars()
        .all()
    )
    assert [n.body for n in notes] == [SUMMARY]


async def test_close_no_action_refused_while_restricted(client, db, sms) -> None:
    _u, _b, case, _r, _laptop, _other = await restricted_student(db, client)
    rb = await staff_browser(client, await staff(db))
    await review_panels(rb, case)
    res = await decide(rb, case, "close_no_action", student_summary="")
    assert res.status_code == 409 and res.json()["current_state"] == "active_restriction", res.text
    assert "uphold" in res.json()["allowed"]
