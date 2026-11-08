"""Phase-A audit probes (STU-*). Assertions encode the OBSERVED behaviour; each prints evidence."""
from __future__ import annotations

from tests.placement.world import World, topic

API = "/api/v1"


async def test_trainer_batch_scope_studio_lists(client, world: World) -> None:
    """TRN-003 / CMS-004 lists for a batch-scoped trainer (the only grant a coordinator can give)."""
    tr = world.personas["trainer_a"]
    c = await client.get(f"{API}/studio/courses", params={"limit": 100}, headers=tr.headers)
    q = await client.get(f"{API}/studio/questions", headers=tr.headers)
    t = await client.get(f"{API}/studio/tests", headers=tr.headers)
    print("TRAINER_COURSES", c.status_code, c.text[:160])
    print("TRAINER_QUESTIONS", q.status_code, q.text[:160])
    print("TRAINER_TESTS", t.status_code, t.text[:120])
    assert c.status_code == 403
    assert q.status_code == 403
    assert t.status_code == 200


async def test_trainer_create_test_and_course_bodies(client, world: World) -> None:
    """Bodies exactly as TestBlueprints / CourseList send them (no organization_id/batch_id)."""
    tr = world.personas["trainer_a"]
    web_body = {"title": "DSA weekly", "test_kind": "mock", "duration_seconds": 3600,
                "navigation_mode": "free", "attempts_allowed": 1}
    r1 = await client.post(f"{API}/studio/tests", json=web_body, headers=tr.headers)
    r2 = await client.post(f"{API}/studio/tests", json={**web_body, "organization_id": str(world.org_a)}, headers=tr.headers)
    r3 = await client.post(f"{API}/studio/tests", json={**web_body, "batch_id": str(world.batch_a)}, headers=tr.headers)
    rc = await client.post(f"{API}/studio/courses", json={"title": "Org course", "slug": "org-course-x"}, headers=tr.headers)
    print("CREATE_TEST web body", r1.status_code, "| +organization_id", r2.status_code, "| +batch_id", r3.status_code)
    print("CREATE_COURSE web body", rc.status_code, rc.text[:160])
    assert r1.status_code == 403 and r2.status_code == 403 and r3.status_code == 201
    assert rc.status_code == 403


async def test_trainer_per_student_override_and_cross_batch_edit(client, world: World) -> None:
    tr = world.personas["trainer_a"]
    st = world.personas["student"]
    r = await client.post(f"{API}/studio/tests", json={"title": "Weekly", "test_kind": "mock", "duration_seconds": 3600,
                          "batch_id": str(world.batch_a)}, headers=tr.headers)
    assert r.status_code == 201, r.text
    tid = r.json()["id"]
    base = {"extra_time_seconds": 900, "extra_attempts": 0, "window_extension_seconds": 0, "reason": "power cut"}
    # TestOverrides sends {user_id} only when a student is chosen, {batch_id} for the whole batch.
    per_student = await client.post(f"{API}/tests/{tid}/overrides", json={**base, "user_id": str(st.id)}, headers=tr.headers)
    whole_batch = await client.post(f"{API}/tests/{tid}/overrides", json={**base, "batch_id": str(world.batch_a)}, headers=tr.headers)
    both = await client.post(f"{API}/tests/{tid}/overrides", json={**base, "user_id": str(st.id), "batch_id": str(world.batch_a)}, headers=tr.headers)
    print("OVERRIDE per-student(web body)", per_student.status_code, per_student.text[:160])
    print("OVERRIDE whole-batch", whole_batch.status_code, "| user+batch", both.status_code, both.text[:300])
    assert per_student.status_code == 403
    assert whole_batch.status_code == 201
    assert both.status_code == 400

    # A trainer of ANOTHER batch in the same org edits/publishes this test.
    other = await world.persona("trainer_a2", grants=(("trainer", "batch", world.batch_a2),), org_ids=(world.org_a,), tier="staff")
    g = await client.get(f"{API}/studio/tests/{tid}", headers=other.headers)
    p = await client.patch(f"{API}/studio/tests/{tid}", json={"title": "Renamed by other batch trainer"}, headers=other.headers)
    ov = await client.get(f"{API}/tests/{tid}/overrides", headers=other.headers)
    print("CROSS_BATCH get", g.status_code, "patch", p.status_code, p.json().get("title") if p.status_code == 200 else p.text[:120],
          "| overrides visible:", len(ov.json().get("items", [])) if ov.status_code == 200 else ov.status_code)
    assert g.status_code == 200 and p.status_code == 200


def _qbody(tid) -> dict:
    return {"question_type": "mcq_single", "primary_topic_id": str(tid), "stem_html": "<p>2+2?</p>",
            "options": [{"html": "4", "is_correct": True}, {"html": "5", "is_correct": False}],
            "explanation_html": "<p>basic</p>", "difficulty": 2, "tags": []}


async def test_question_sod_gaps(client, world: World, db) -> None:
    author = world.personas["author"]
    reviewer = world.personas["reviewer"]
    t = await topic(db, "audit/sod")

    # (a) author submits, reviewer approves, AUTHOR publishes.
    r = await client.post(f"{API}/studio/questions", json=_qbody(t), headers=author.headers)
    assert r.status_code == 201, r.text
    qid = r.json()["question_id"]
    s = await client.post(f"{API}/studio/questions/{qid}/submit-review", json={}, headers=author.headers)
    a = await client.post(f"{API}/studio/questions/{qid}/review", json={"decision": "approve"}, headers=reviewer.headers)
    pub = await client.post(f"{API}/studio/questions/{qid}/publish", json={}, headers=author.headers)
    print("SOD_A submit", s.status_code, "approve", a.status_code, "publish-by-author", pub.status_code, pub.text[:160])
    assert pub.status_code == 200

    # (b) reviewer rewrites the author's draft in place, submits and approves their own content.
    r = await client.post(f"{API}/studio/questions", json=_qbody(t), headers=author.headers)
    qid2 = r.json()["question_id"]
    body = {k: v for k, v in _qbody(t).items() if k not in ("question_type", "primary_topic_id", "tags")}
    body["stem_html"] = "<p>Completely rewritten by reviewer</p>"
    e = await client.post(f"{API}/studio/questions/{qid2}/versions", json=body, headers=reviewer.headers)
    s2 = await client.post(f"{API}/studio/questions/{qid2}/submit-review", json={}, headers=reviewer.headers)
    a2 = await client.post(f"{API}/studio/questions/{qid2}/review", json={"decision": "approve"}, headers=reviewer.headers)
    p2 = await client.post(f"{API}/studio/questions/{qid2}/publish", json={}, headers=reviewer.headers)
    d = await client.get(f"{API}/studio/questions/{qid2}", headers=reviewer.headers)
    v = d.json()["versions"][0]
    print("SOD_B edit", e.status_code, "submit", s2.status_code, "self-approve", a2.status_code, "publish", p2.status_code,
          "| version_no", v["version_no"], "authored_by==author", v["authored_by"] == str(author.id),
          "reviewed_by==reviewer", v["reviewed_by"] == str(reviewer.id), "stem", v["stem_html"])
    assert a2.status_code == 200 and p2.status_code == 200


async def test_content_manager_reads_per_learner_attempts(client, world: World, db, allow_access) -> None:
    """Matrix: content_manager test.results.read = 'P (item stats only)'."""
    from tests.assessments.test_integrity_and_report import flagged_attempt

    test_id, aid = await flagged_attempt(db, world, client)
    cm = world.personas["author"]
    rep = await client.get(f"{API}/tests/{test_id}/report", headers=cm.headers)
    att = await client.get(f"{API}/tests/{test_id}/attempts", headers=cm.headers)
    rows = att.json().get("items", []) if att.status_code == 200 else []
    print("CM_REPORT", rep.status_code, rep.json().get("scope"))
    print("CM_ATTEMPTS", att.status_code, [{k: r[k] for k in ("user_id", "status", "percentage", "integrity_status")} for r in rows][:2],
          "student_is_visible", any(r["user_id"] == str(world.personas["student"].id) for r in rows))
    assert rep.json().get("scope") == "item_stats_only"
    assert att.status_code == 200 and rows
