"""Question banks (WISEMAN-FEATURES qbank build): named banks, new question types, bulk import
via prompt, Generate with AI (drafts only), picker resolve and question images."""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from sqlalchemy import text

from app.core.db import system_context
from app.core.errors import ProblemError
from app.modules.placement import bank, bulk_import, grading
from tests.placement.world import World, find_keys, idem, question, topic

API = "/api/v1"
KEY_V1 = "11" * 32


@pytest.fixture(autouse=True)
def audited(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Spy on ``audit()`` in the qbank router (td_app cannot read audit_outbox)."""
    from app.modules.placement import qbank_router

    actions: list[str] = []
    real = qbank_router.audit

    async def spy(session: Any, actor: Any, action: str, *a: Any, **kw: Any) -> Any:
        actions.append(action)
        return await real(session, actor, action, *a, **kw)

    monkeypatch.setattr(qbank_router, "audit", spy)
    return actions


@pytest.fixture(autouse=True)
def testcase_key(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    from app.modules.coding.crypto import reset_testcase_keyring

    monkeypatch.setenv("TD_K_TESTCASE_KEY_V1", KEY_V1)
    monkeypatch.setenv("TD_K_TESTCASE_ACTIVE_VERSION", "1")
    monkeypatch.delenv("TD_K_TESTCASE_KEY_V2", raising=False)
    reset_testcase_keyring()
    yield
    reset_testcase_keyring()


def mcq_items(n: int = 2) -> list[dict[str, Any]]:
    return [
        {
            "question": f"Which list method appends an item? ({i})",
            "options": [
                {"text": "append", "correct": True},
                {"text": "extend", "correct": i == 1},
                {"text": "pop", "correct": False},
            ],
            "explanation": "append adds one item.",
            "difficulty": "easy",
            "tags": ["python", "lists"],
        }
        for i in range(n)
    ]


async def _bank(client: Any, who: Any, **kw: Any) -> dict[str, Any]:
    r = await client.post(
        f"{API}/studio/question-banks",
        json={"name": "Py lists", "subject": "programming", **kw},
        headers=who.headers,
    )
    assert r.status_code == 201, r.text
    return r.json()


async def _count(db: Any, sql: str, **p: Any) -> int:
    await system_context(db, "test")
    return int((await db.execute(text(sql), p)).scalar_one())


# --------------------------------------------------------------------------- banks


async def test_bank_crud_counters_membership(client, world: World, db, audited) -> None:
    author, student = world.personas["author"], world.personas["student"]
    b = await _bank(client, author)
    assert b["question_count"] == 0 and b["organization_id"] is None
    body = {
        "question_type": "mcq_multi",
        "bank_id": b["id"],
        "stem_html": "<p>Pick the mutable types</p>",
        "options": [
            {"html": "list", "is_correct": True},
            {"html": "dict", "is_correct": True},
            {"html": "tuple"},
        ],
        "explanation_html": "<p>tuples are immutable</p>",
        "difficulty": 2,
        "tags": [{"tag_type": "custom", "value": "python"}],
    }
    r = await client.post(f"{API}/studio/questions", json=body, headers=author.headers)
    assert r.status_code == 201, r.text
    q1 = r.json()
    assert q1["banks"] == [{"id": b["id"], "name": "Py lists"}]
    # no topic given: the global "Uncategorised" subject is used
    await system_context(db, "test")
    path = (
        await db.execute(text("SELECT path FROM topics WHERE id = :t"), {"t": q1["primary_topic_id"]})
    ).scalar_one()
    assert path == "uncategorised"

    r = await client.get(f"{API}/studio/question-banks", headers=author.headers)
    assert r.status_code == 200, r.text
    listing = r.json()
    assert listing["counters"]["banks"] >= 1 and listing["counters"]["questions"] >= 1
    mine = next(x for x in listing["items"] if x["id"] == b["id"])
    assert mine["type_counts"] == {"mcq_multi": 1} and mine["tags"] == ["python"]
    r = await client.get(f"{API}/studio/question-banks?types=poll", headers=author.headers)
    assert all(x["id"] != b["id"] for x in r.json()["items"])

    r = await client.get(f"{API}/studio/question-banks/{b['id']}/questions?q=mutable", headers=author.headers)
    detail = r.json()
    assert detail["total"] == 1 and detail["items"][0]["latest_version"]["correct_count"] == 2
    assert detail["tags"] == ["python"] and detail["items"][0]["published_version_id"] is None

    # "From bank": add an existing (published) question to a second bank
    t = await topic(db, "quant/percent")
    existing = await question(db, author, world.personas["reviewer"], t)
    b2 = await _bank(client, author, name="Aptitude")
    r = await client.post(
        f"{API}/studio/question-banks/{b2['id']}/questions",
        json={"question_ids": [str(existing.question_id), q1["question_id"]]},
        headers=author.headers,
    )
    assert r.status_code == 200 and r.json()["added"] == 2
    assert r.json()["bank"]["question_count"] == 2

    # removing a published question with purge is refused; plain removal works
    r = await client.delete(
        f"{API}/studio/question-banks/{b2['id']}/questions/{existing.question_id}?purge=true",
        headers=author.headers,
    )
    assert r.status_code == 409
    r = await client.delete(
        f"{API}/studio/question-banks/{b2['id']}/questions/{existing.question_id}", headers=author.headers
    )
    assert r.json() == {"removed": True, "purged": False}
    # purge a never-published draft
    r = await client.delete(
        f"{API}/studio/question-banks/{b['id']}/questions/{q1['question_id']}?purge=true",
        headers=author.headers,
    )
    assert r.json()["purged"] is True
    r = await client.get(f"{API}/studio/questions/{q1['question_id']}", headers=author.headers)
    assert r.status_code == 404

    r = await client.patch(
        f"{API}/studio/question-banks/{b['id']}", json={"name": "Lists v2"}, headers=author.headers
    )
    assert r.json()["name"] == "Lists v2"
    r = await client.delete(f"{API}/studio/question-banks/{b['id']}", headers=author.headers)
    assert r.json()["deleted"] is True
    r = await client.get(f"{API}/studio/question-banks/{b['id']}", headers=author.headers)
    assert r.status_code == 404
    assert {"question_bank.created", "question_bank.changed", "question_bank.deleted"} <= set(audited)

    r = await client.get(f"{API}/studio/question-banks", headers=student.headers)
    assert r.status_code == 403


async def test_bank_tenant_isolation(client, world: World) -> None:
    ta, tb = world.personas["trainer_a"], world.personas["trainer_b"]
    b = await _bank(client, ta, organization_id=str(world.org_a))
    # Single company: a company bank is shared by every company editor (ADM-41), including a
    # trainer of another batch; a learner never reaches it.
    r = await client.get(f"{API}/studio/question-banks/{b['id']}", headers=tb.headers)
    assert r.status_code == 200, r.text
    r = await client.get(f"{API}/studio/question-banks", headers=tb.headers)
    assert any(x["id"] == b["id"] for x in r.json()["items"])
    r = await client.get(
        f"{API}/studio/question-banks/{b['id']}", headers=world.personas["student_b"].headers
    )
    assert r.status_code == 403
    # a trainer never creates platform banks: without an owner the bank is the company's
    r = await client.post(f"{API}/studio/question-banks", json={"name": "x"}, headers=ta.headers)
    assert r.status_code == 201 and r.json()["organization_id"] == str(world.org_a)
    # a student creates nothing
    r = await client.post(
        f"{API}/studio/question-banks", json={"name": "x"}, headers=world.personas["student"].headers
    )
    assert r.status_code == 403


# --------------------------------------------------------------------------- question types


async def test_new_types_create_validate_and_deliver(client, world: World, db) -> None:
    author, reviewer = world.personas["author"], world.personas["reviewer"]

    async def create(body: dict[str, Any]) -> Any:
        return await client.post(
            f"{API}/studio/questions", json={"difficulty": 1, **body}, headers=author.headers
        )

    r = await create(
        {
            "question_type": "poll",
            "stem_html": "<p>Favourite language?</p>",
            "options": [{"html": "Python"}, {"html": "Java"}],
            "settings": {"allow_multiple": True},
        }
    )
    assert r.status_code == 201, r.text
    poll = r.json()
    assert poll["versions"][0]["settings"] == {"allow_multiple": True}
    r = await create(
        {
            "question_type": "poll",
            "stem_html": "<p>x</p>",
            "options": [{"html": "a", "is_correct": True}, {"html": "b"}],
        }
    )
    assert r.status_code == 400  # polls are ungraded

    r = await create(
        {
            "question_type": "survey",
            "stem_html": "<p>The pace was right</p>",
            "settings": {"scale": "likert", "points": 5},
        }
    )
    assert r.status_code == 201, r.text
    labels = [o["html"] for o in r.json()["versions"][0]["options"]]
    assert labels[0] == "Strongly disagree" and len(labels) == 5
    r = await create(
        {"question_type": "survey", "stem_html": "<p>Any comments?</p>", "settings": {"scale": "open"}}
    )
    assert r.status_code == 201 and r.json()["versions"][0]["options"] == []
    r = await create(
        {"question_type": "word_cloud", "stem_html": "<p>One word</p>", "settings": {"max_words": 2}}
    )
    assert r.json()["versions"][0]["settings"] == {"max_words": 2, "max_chars": 30}
    r = await create({"question_type": "word_cloud", "stem_html": "<p>x</p>", "settings": {"max_words": 9}})
    assert r.status_code == 400

    r = await create(
        {
            "question_type": "essay",
            "stem_html": "<p>Explain GIL</p>",
            "answer_key": {
                "reference_answer_html": "<p>A mutex<script>x</script></p>",
                "rubric": [{"criterion": "Defines GIL", "marks": 2}],
            },
            "settings": {"max_words": 200},
            "default_marks": "2",
        }
    )
    assert r.status_code == 201, r.text
    essay = r.json()
    key = essay["versions"][0]["answer_key"]
    assert "script" not in key["reference_answer_html"] and key["rubric"] == [
        {"criterion": "Defines GIL", "max_marks": "2", "marks": "2"}
    ]
    assert key["reference_answer_md"].startswith("A mutex")
    # the assessments/assignments key format (passed to ai.grade_response)
    r = await create(
        {
            "question_type": "essay",
            "stem_html": "<p>Define a closure</p>",
            "answer_key": {
                "reference_answer_md": "A function that captures variables.",
                "rubric": [{"criterion": "Definition", "max_marks": 3, "description": "mentions scope"}],
            },
            "settings": {"max_words": 40},
        }
    )
    assert r.status_code == 201, r.text
    k2 = r.json()["versions"][0]["answer_key"]
    assert k2["reference_answer_md"] == "A function that captures variables."
    assert k2["rubric"][0]["max_marks"] == "3" and k2["rubric"][0]["description"] == "mentions scope"
    # graded essay needs an explanation before review; the ungraded poll does not
    r = await client.post(
        f"{API}/studio/questions/{essay['question_id']}/submit-review", headers=author.headers
    )
    assert r.status_code == 400
    qid = uuid.UUID(poll["question_id"])
    r = await client.post(f"{API}/studio/questions/{qid}/submit-review", headers=author.headers)
    assert r.status_code == 200, r.text
    await client.post(
        f"{API}/studio/questions/{qid}/review", json={"decision": "approve"}, headers=reviewer.headers
    )
    r = await client.post(f"{API}/studio/questions/{qid}/publish", headers=reviewer.headers)
    assert r.status_code == 200, r.text

    await system_context(db, "test")
    q = await bank.get_question(db, qid)
    bundles = await bank.load_bundles(db, [q.current_version_id])  # type: ignore[list-item]
    dto = bank.delivery(bundles[q.current_version_id])  # type: ignore[index]
    assert dto["settings"] == {"allow_multiple": True} and find_keys(dto) == set()
    # objective items keep their historical delivery shape
    t = await topic(db, "quant/ratio")
    mcq = await question(db, author, reviewer, t)
    mdto = bank.delivery((await bank.load_bundles(db, [mcq.qv_id]))[mcq.qv_id])
    assert "settings" not in mdto and "stem_images" not in mdto and "image_url" not in mdto["options"][0]


def test_grading_new_types() -> None:
    a, b = uuid.uuid4(), uuid.uuid4()
    ids = {a, b}
    assert grading.normalise_response("poll", {"option_ids": [str(a), str(b)]}, ids, {"allow_multiple": True})
    with pytest.raises(ProblemError):
        grading.normalise_response("poll", {"option_ids": [str(a), str(b)]}, ids, {"allow_multiple": False})
    assert grading.normalise_response("survey", {"text": " fine "}, set()) == {"text": "fine"}
    assert grading.normalise_response("word_cloud", {"words": [" CV "]}, set(), {"max_words": 1}) == {
        "words": ["CV"]
    }
    with pytest.raises(ProblemError):
        grading.normalise_response("word_cloud", {"words": ["a", "b"]}, set(), {"max_words": 1})
    assert grading.normalise_response("essay", {"text": ""}, set()) is None
    for t in ("essay", "poll", "survey", "word_cloud"):
        assert grading.is_correct(t, {"text": "x"}, set(), None) is None


# --------------------------------------------------------------------------- bulk import


async def test_prompt_and_validate_with_fix_prompt(client, world: World) -> None:
    author = world.personas["author"]
    r = await client.post(
        f"{API}/studio/question-banks/import/prompt",
        json={
            "question_type": "code",
            "count": 5,
            "subject": "Python",
            "topic": "Sets",
            "instructions": "Python Sets",
        },
        headers=author.headers,
    )
    assert r.status_code == 200, r.text
    prompt = r.json()["prompt"]
    assert "exactly 5 programming question(s)" in prompt and '"hidden": false' in prompt
    assert 'subject "Python"' in prompt and "Additional instructions: Python Sets" in prompt

    r = await client.post(
        f"{API}/studio/question-banks/import/validate",
        json={"question_type": "mcq", "raw": '[{"question": "x", }'},
        headers=author.headers,
    )
    out = r.json()
    assert (
        out["ok"] is False and out["problem_count"] == 1 and "Invalid JSON" in out["problems"][0]["message"]
    )

    bad = mcq_items(2)
    bad[1]["options"] = [{"text": "a", "correct": False}, {"text": "b", "correct": False}]
    bad[0]["colour"] = "red"
    r = await client.post(
        f"{API}/studio/question-banks/import/validate",
        json={"question_type": "mcq", "raw": "```json\n" + json.dumps(bad) + "\n```"},
        headers=author.headers,
    )
    out = r.json()
    assert out["problem_count"] == 2
    assert {(p["index"], p["field"]) for p in out["problems"]} == {(0, "colour"), (1, "options")}
    assert "Item 2 · options" in out["fix_prompt"] and "Item 1 · colour" in out["fix_prompt"]
    assert "return ONLY the corrected JSON array" in out["fix_prompt"]

    r = await client.post(
        f"{API}/studio/question-banks/import/validate",
        json={"question_type": "mcq", "raw": json.dumps(mcq_items(2))},
        headers=author.headers,
    )
    out = r.json()
    assert out["ok"] and out["count"] == 2 and out["fix_prompt"] is None
    assert out["items"][0]["options"][0] == {"text": "append", "correct": True}


async def test_import_all_or_nothing_idempotent_drafts(client, world: World, db, audited) -> None:
    author = world.personas["author"]
    before = await _count(db, "SELECT count(*) FROM questions")
    bad = mcq_items(3)
    bad[2]["options"] = [{"text": "only one"}]
    r = await client.post(
        f"{API}/studio/question-banks/import",
        json={"question_type": "mcq", "raw": json.dumps(bad), "new_bank_name": "Lists"},
        headers={**author.headers, **idem()},
    )
    assert r.status_code == 400 and r.json()["problem_count"] >= 1 and r.json()["fix_prompt"]
    assert await _count(db, "SELECT count(*) FROM questions") == before
    assert await _count(db, "SELECT count(*) FROM question_banks WHERE name = 'Lists'") == 0

    r = await client.post(
        f"{API}/studio/question-banks/import",
        json={"question_type": "mcq", "raw": json.dumps(mcq_items(2))},
        headers=author.headers,
    )
    assert r.status_code == 400 and r.json()["code"] == "idempotency_key_required"

    h = {**author.headers, **idem()}
    payload = {"question_type": "mcq", "raw": json.dumps(mcq_items(2)), "topic": "Lists", "subject": "Python"}
    r = await client.post(f"{API}/studio/question-banks/import", json=payload, headers=h)
    assert r.status_code == 201, r.text
    out = r.json()
    assert out["count"] == 2 and out["bank"]["question_count"] == 2 and out["bank"]["subject"] == "Python"
    assert out["bank"]["name"].startswith("Lists · MCQ")
    assert out["bank"]["type_counts"] == {"mcq_single": 1, "mcq_multi": 1}
    r2 = await client.post(f"{API}/studio/question-banks/import", json=payload, headers=h)
    assert r2.status_code == 201 and r2.json()["question_ids"] == out["question_ids"]
    assert await _count(db, "SELECT count(*) FROM questions") == before + 2
    for qid in out["question_ids"]:
        d = (await client.get(f"{API}/studio/questions/{qid}", headers=author.headers)).json()
        assert d["status"] == "draft" and d["versions"][0]["status"] == "draft"
        assert {t["value"] for t in d["tags"]} == {"python", "lists", "bulk-import"}
    assert audited.count("question_bank.imported") == 1  # the replay is not re-audited

    # import into an existing bank
    r = await client.post(
        f"{API}/studio/question-banks/import",
        json={
            "question_type": "poll",
            "items": [{"question": "Tea or coffee?", "options": ["Tea", "Coffee"], "tags": ["fun"]}],
            "bank_id": out["bank"]["id"],
        },
        headers={**author.headers, **idem()},
    )
    assert r.status_code == 201, r.text
    assert r.json()["bank"]["question_count"] == 3


async def test_import_code_creates_draft_problem_with_sealed_hidden_cases(client, world: World, db) -> None:
    author, trainer = world.personas["author"], world.personas["trainer_a"]
    secret = "4\n10 20 30 999123"
    item = {
        "title": "Unique count",
        "description": "Count distinct numbers.",
        "sampleInput": "3\n1 1 2",
        "sampleOutput": "2",
        "acceptanceCriteria": "",
        "testCases": [
            {"input": "2\n5 5", "expectedOutput": "1", "hidden": False},
            {"input": secret, "expectedOutput": "4", "hidden": True},
        ],
        "tags": ["python", "sets"],
    }
    r = await client.post(
        f"{API}/studio/question-banks/import/validate",
        json={"question_type": "code", "items": [item]},
        headers=author.headers,
    )
    prev = r.json()["items"][0]
    assert prev["hidden_cases"] == 1 and prev["sample_cases"] == 2 and secret not in r.text
    r = await client.post(
        f"{API}/studio/question-banks/import",
        json={"question_type": "code", "items": [item], "new_bank_name": "Sets"},
        headers={**author.headers, **idem()},
    )
    assert r.status_code == 201, r.text
    assert secret not in r.text
    qid = r.json()["question_ids"][0]
    d = await client.get(f"{API}/studio/questions/{qid}", headers=author.headers)
    assert secret not in d.text
    pid = d.json()["versions"][0]["coding_problem_id"]
    await system_context(db, "test")
    rows = (
        await db.execute(
            text(
                "SELECT is_hidden, sample_input FROM coding_test_cases WHERE coding_problem_id = :p ORDER BY ordinal"
            ),
            {"p": pid},
        )
    ).all()
    assert [r_[0] for r_ in rows] == [False, False, True] and rows[2][1] is None  # hidden case sealed
    status = (
        await db.execute(text("SELECT status FROM coding_problems WHERE id = :p"), {"p": pid})
    ).scalar_one()
    assert status == "draft"
    # review requires the linked coding problem to be published first
    r = await client.post(f"{API}/studio/questions/{qid}/submit-review", headers=author.headers)
    assert r.status_code == 409

    # trainers may not author hidden test cases at org scope without the coding permissions
    r = await client.post(
        f"{API}/studio/question-banks/import",
        json={"question_type": "code", "items": [item], "organization_id": str(world.org_a)},
        headers={**trainer.headers, **idem()},
    )
    assert r.status_code in (403, 404)


# --------------------------------------------------------------------------- AI + picker


async def test_generate_with_ai_returns_drafts_and_saves_via_import(
    client, world: World, db, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.modules.ai import service as ai

    author = world.personas["author"]
    seen: dict[str, Any] = {}

    async def fake(session: Any, *, org_id: Any, user_id: Any, spec: Any) -> list[dict[str, Any]]:
        seen["spec"] = spec
        return [
            {
                "question_type": "mcq",
                "stem_md": f"What does len([1,2,{i}]) return?",
                "difficulty": "easy",
                "tags": ["python", "lists"],
                "explanation_md": "Three items.",
                "options": [{"text": "3", "is_correct": True}, {"text": "2", "is_correct": False}],
                "test_cases": [],
                "source": "ai",
            }
            for i in range(spec.count)
        ]

    monkeypatch.setattr(ai, "generate_questions", fake)
    r = await client.post(
        f"{API}/studio/question-banks/generate",
        json={"source_mode": "topic", "topic": "Python lists", "question_type": "mcq", "count": 3},
        headers=author.headers,
    )
    assert r.status_code == 200, r.text
    out = r.json()
    assert seen["spec"].topic == "Python lists" and seen["spec"].count == 3
    assert len(out["drafts"]) == 3 and out["drafts"][0]["options"][0] == {"text": "3", "correct": True}
    r = await client.post(
        f"{API}/studio/question-banks/import",
        json={"question_type": "mcq", "items": out["drafts"][:2], "source": "ai"},
        headers={**author.headers, **idem()},
    )
    assert r.status_code == 201, r.text
    d = (
        await client.get(f"{API}/studio/questions/{r.json()['question_ids'][0]}", headers=author.headers)
    ).json()
    assert d["status"] == "draft" and "ai-generated" in {t["value"] for t in d["tags"]}

    async def disabled(*a: Any, **k: Any) -> Any:
        raise ai.AIDisabled()

    monkeypatch.setattr(ai, "generate_questions", disabled)
    r = await client.post(
        f"{API}/studio/question-banks/generate",
        json={"source_mode": "topic", "topic": "x", "question_type": "mcq", "count": 1},
        headers=author.headers,
    )
    assert r.status_code == 403 and r.json()["code"] == "ai_disabled"
    r = await client.post(
        f"{API}/studio/question-banks/generate",
        json={"source_mode": "company", "question_type": "mcq", "count": 1},
        headers=author.headers,
    )
    assert r.status_code in (400, 422)


async def test_resolve_for_picker(client, world: World, db) -> None:
    author, reviewer, trainer = (
        world.personas["author"],
        world.personas["reviewer"],
        world.personas["trainer_a"],
    )
    t = await topic(db, "quant/avg")
    pub = await question(db, author, reviewer, t)
    draft = await question(db, author, reviewer, t, publish=False)
    r = await client.post(
        f"{API}/studio/question-banks/resolve",
        json={"question_ids": [str(pub.question_id), str(draft.question_id)]},
        headers=author.headers,
    )
    assert r.status_code == 200, r.text
    items = {x["question_id"]: x for x in r.json()["items"]}
    assert items[str(draft.question_id)]["version"] is None
    v = items[str(pub.question_id)]["version"]
    assert v["question_version_id"] == str(pub.qv_id) and items[str(pub.question_id)]["keys_visible"]
    assert sum(o["is_correct"] for o in v["options"]) == 1
    r = await client.post(
        f"{API}/studio/question-banks/resolve",
        json={"question_ids": [str(draft.question_id)], "prefer": "latest"},
        headers=author.headers,
    )
    assert r.json()["items"][0]["version"]["status"] == "draft"
    # trainers of org A cannot resolve platform questions without question.create on the platform
    r = await client.post(
        f"{API}/studio/question-banks/resolve",
        json={"question_ids": [str(pub.question_id)]},
        headers=trainer.headers,
    )
    assert r.status_code == 403


async def backdate_media(db: Any, mid: str, seconds: int = 400) -> None:
    """Move an upload request past the presign window (SEC-18)."""
    await system_context(db, "test.factory")
    await db.execute(
        text("UPDATE question_media SET created_at = created_at - make_interval(secs => :s) WHERE id = :i"),
        {"s": seconds, "i": uuid.UUID(mid)},
    )


async def test_question_images_upload_scan_and_serve(
    client, world: World, db, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.modules.media import providers

    class Pending:
        is_fake = True
        result: str | None = None

        def immediate_result(self, key: str) -> str | None:
            return self.result

    scanner = Pending()
    monkeypatch.setattr(providers, "get_scanner", lambda: scanner)
    author, student = world.personas["author"], world.personas["student"]
    r = await client.post(
        f"{API}/studio/question-media/uploads",
        json={"filename": "graph.png", "content_type": "image/png", "size_bytes": 1000},
        headers=author.headers,
    )
    assert r.status_code == 201, r.text
    mid = r.json()["media_id"]
    assert r.json()["upload"]["url"].startswith("http")
    r = await client.post(
        f"{API}/studio/question-media/uploads",
        json={"filename": "x.svg", "content_type": "image/svg+xml", "size_bytes": 10},
        headers=author.headers,
    )
    assert r.status_code == 400
    r = await client.post(f"{API}/studio/question-media/{mid}/complete", headers=author.headers)
    assert r.json()["scan_status"] == "pending" and r.json()["url"] is None
    r = await client.get(f"{API}/question-media/{mid}", headers=student.headers, follow_redirects=False)
    assert r.status_code == 404
    scanner.result = "clean"
    # SEC-18: clean is not accepted while the presigned upload could still replace the bytes
    r = await client.post(f"{API}/studio/question-media/{mid}/complete", headers=author.headers)
    assert r.json()["scan_status"] == "pending" and r.json()["clean_not_before"]
    await backdate_media(db, mid)
    r = await client.post(f"{API}/studio/question-media/{mid}/complete", headers=author.headers)
    assert r.json()["status"] == "ready" and r.json()["url"] == f"/api/v1/question-media/{mid}"
    r = await client.get(f"{API}/question-media/{mid}", headers=student.headers, follow_redirects=False)
    assert r.status_code == 307 and "question_image" in r.headers["location"]

    t = await topic(db, "quant/graphs")
    r = await client.post(
        f"{API}/studio/questions",
        json={
            "question_type": "mcq_single",
            "primary_topic_id": str(t),
            "stem_html": "<p>Read the graph</p>",
            "stem_image_ids": [mid],
            "options": [{"html": "a", "is_correct": True, "image_id": mid}, {"html": "b"}],
            "explanation_html": "<p>x</p>",
            "difficulty": 1,
        },
        headers=author.headers,
    )
    assert r.status_code == 201, r.text
    v = r.json()["versions"][0]
    assert v["stem_images"][0]["media_id"] == mid and v["options"][0]["image"]["media_id"] == mid
    r = await client.post(
        f"{API}/studio/questions",
        json={
            "question_type": "poll",
            "stem_html": "<p>x</p>",
            "stem_image_ids": [str(uuid.uuid4())],
            "options": [{"html": "a"}, {"html": "b"}],
            "difficulty": 1,
        },
        headers=author.headers,
    )
    assert r.status_code == 400


def test_import_schema_and_ai_adapter_shapes() -> None:
    assert set(bulk_import.ITEM_SCHEMAS) == set(bulk_import.KINDS)
    assert bulk_import.QUESTION_IMPORT_SCHEMA["type"] == "array"
    survey = bulk_import.from_ai_item(
        "survey", {"stem_md": "Rate it", "options": [{"text": t} for t in ("a", "b", "c")], "tags": []}
    )
    items, probs = bulk_import.validate_items("survey", [survey])
    assert not probs and items[0].data["labels"] == ["a", "b", "c"]
    code = bulk_import.from_ai_item(
        "code",
        {
            "stem_md": "Sum",
            "test_cases": [{"input": "1 2", "expected_output": "3", "hidden": True}],
            "tags": ["x"],
        },
    )
    items, probs = bulk_import.validate_items("code", [code])
    assert not probs and items[0].preview()["hidden_cases"] == 1
