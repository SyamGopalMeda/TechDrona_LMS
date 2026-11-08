"""Phase-A audit probes. Each test prints evidence; assertions encode the OBSERVED behaviour."""
from __future__ import annotations

import uuid

from app.core.access import AccessDecision, register_access_checker, get_access_checker
from tests.placement.test_placement import _practice_bank
from tests.placement.world import World, correct_response, idem, wrong_response

API = "/api/v1"


class Toggle:
    def __init__(self) -> None:
        self.allow = True

    async def check(self, session, principal, resource_type, resource_id, *, is_free=False):
        return AccessDecision(self.allow, "entitlement" if self.allow else "no_entitlement")


async def test_practice_answer_after_entitlement_lost(client, world: World, db) -> None:
    prev = get_access_checker()
    tog = Toggle()
    register_access_checker(tog)
    try:
        t, qs = await _practice_bank(db, world, 2)
        st = world.personas["student"]
        r = await client.post(f"{API}/practice/sessions", json={"topic_id": str(t)}, headers={**st.headers, **idem()})
        assert r.status_code == 201, r.text
        s = r.json()
        tog.allow = False  # entitlement revoked/expired mid-set
        qv = s["items"][0]["question"]["question_version_id"]
        by = {str(q.qv_id): q for q in qs}
        r = await client.post(
            f"{API}/practice/sessions/{s['session_id']}/answers",
            json={"question_version_id": qv, "response": wrong_response(by[qv]), "time_spent_ms": 5},
            headers={**st.headers, **idem()},
        )
        print("ANSWER_AFTER_REVOKE", r.status_code, sorted(r.json().keys()))
        r2 = await client.post(
            f"{API}/practice/sessions/{s['session_id']}/questions/{s['items'][1]['question']['question_version_id']}/reveal",
            json={"kind": "solution"}, headers=st.headers)
        print("REVEAL_AFTER_REVOKE", r2.status_code, sorted(r2.json().keys()))
        r3 = await client.get(f"{API}/practice/sessions/{s['session_id']}", headers=st.headers)
        print("STATE_AFTER_REVOKE", r3.status_code)
    finally:
        register_access_checker(prev)


async def test_reveal_then_answer_counts_correct(client, world: World, db, allow_access) -> None:
    t, qs = await _practice_bank(db, world, 1)
    st = world.personas["student"]
    s = (await client.post(f"{API}/practice/sessions", json={"topic_id": str(t)}, headers={**st.headers, **idem()})).json()
    qv = s["items"][0]["question"]["question_version_id"]
    await client.post(f"{API}/practice/sessions/{s['session_id']}/questions/{qv}/reveal", json={"kind": "solution"}, headers=st.headers)
    r = await client.post(f"{API}/practice/sessions/{s['session_id']}/answers",
        json={"question_version_id": qv, "response": correct_response(qs[0]), "time_spent_ms": 1}, headers={**st.headers, **idem()})
    c = (await client.post(f"{API}/practice/sessions/{s['session_id']}/complete", headers=st.headers)).json()
    print("REVEAL_THEN_ANSWER", r.json()["is_correct"], r.json()["solution_viewed"], "summary", c["correct"], c["accuracy"])


async def test_company_step_on_draft_path(client, world: World, db, allow_access) -> None:
    t, qs = await _practice_bank(db, world, 2)
    author, student = world.personas["author"], world.personas["student"]
    cid = (await client.post(f"{API}/studio/companies", json={"slug": "draftco", "name": "DraftCo", "hub_status": "published"}, headers=author.headers)).json()["id"]
    pid = str(uuid.uuid4())
    body = {"company_id": cid, "role_name": "SE", "status": "draft",
            "pattern": [{"section": "Q", "topic_id": str(t), "weight": 1, "minutes": 10, "question_count": 5}],
            "steps": [{"step_type": "practice_set", "title": "S", "topic_id": str(t)}]}
    r = await client.put(f"{API}/studio/company-paths/{pid}", json=body, headers=author.headers)
    print("PUT_DRAFT", r.status_code, r.json().get("status"))
    step_id = r.json()["steps"][0]["id"]
    r = await client.get(f"{API}/me/company-paths/draftco", headers=student.headers)
    print("STUDENT_GET_DRAFT_PATH", r.status_code)
    r = await client.post(f"{API}/practice/sessions", json={"mode": "company_step", "company_path_step_id": step_id}, headers={**student.headers, **idem()})
    print("PRACTICE_DRAFT_STEP", r.status_code)


async def test_validation_shape(client, world: World, db, allow_access) -> None:
    st = world.personas["student"]
    r = await client.post(f"{API}/practice/sessions", json={"topic_id": "nope"}, headers={**st.headers, **idem()})
    print("PRACTICE_BAD_UUID", r.status_code, r.headers.get("content-type"), r.json().get("code"))
    r = await client.get(f"{API}/practice/sessions/{uuid.uuid4()}", headers=st.headers)
    print("PRACTICE_404", r.status_code, r.json().get("code"))
    r = await client.post(f"{API}/practice/sessions", json={"topic_id": str(uuid.uuid4())}, headers={**st.headers, **idem()})
    print("PRACTICE_UNKNOWN_TOPIC", r.status_code, r.json().get("code"))
    r = await client.post(f"{API}/practice/sessions", json={"topic_id": str(uuid.uuid4()), "count": 100000}, headers={**st.headers, **idem()})
    print("PRACTICE_HUGE_COUNT", r.status_code, r.json().get("code"))


async def test_other_student_session_404(client, world: World, db, allow_access) -> None:
    t, qs = await _practice_bank(db, world, 1)
    a = world.personas["student"]
    b = world.personas["student_b"]
    s = (await client.post(f"{API}/practice/sessions", json={"topic_id": str(t)}, headers={**a.headers, **idem()})).json()
    r = await client.get(f"{API}/practice/sessions/{s['session_id']}", headers=b.headers)
    print("OTHER_STUDENT_SESSION", r.status_code)
