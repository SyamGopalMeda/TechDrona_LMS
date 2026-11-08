"""Judge gateway, verdict mapping, crypto, production refusal, worker, assessments interface."""

from __future__ import annotations

import base64
import json
import uuid
from decimal import Decimal

import httpx
import pytest
from sqlalchemy import select

from app.core.config import Settings
from app.core.db import system_context
from app.core.startup_checks import production_problems
from app.modules.coding import crypto, service
from app.modules.coding.judge_gateway import (
    FakeJudgeAdapter,
    Judge0Adapter,
    JudgeConfigurationError,
    JudgeJob,
    JudgeLimits,
    JudgeRunResult,
    JudgeTimeout,
    JudgeUnavailable,
    get_judge_adapter,
    run_jobs,
    set_judge_adapter,
)
from app.modules.coding.judge_gateway.checker import ScoredCase, aggregate, case_verdict, outputs_match
from app.modules.coding.judge_gateway.fake import fake_verdicts
from app.modules.coding.judge_gateway.judge0 import map_status
from app.modules.coding.models import CodeSubmission, CodingTestCase
from app.modules.coding.worker import judge_submission, process_pending
from tests.coding.conftest import KEY_V1, KEY_V2, idem, seed_problem

LIMITS = JudgeLimits.for_problem(
    time_limit_ms=2000,
    wall_limit_ms=5000,
    memory_limit_kb=262144,
    time_multiplier=1.0,
    memory_extra_kb=0,
    max_processes=64,
)


def _settings(**kw) -> Settings:
    base = dict(
        APP_ENV="prod",
        TD_DISABLE_API_DOCS=True,
        TD_COOKIE_SECURE=True,
        TD_SERVICE_TOKEN="f" * 64,
        JUDGE_PROVIDER="judge0_cloud",
        SMS_PROVIDER="msg91",
        EMAIL_PROVIDER="ses",
        VDOCIPHER_MODE="live",
        TD_APP_ENVELOPE_KMS_KEY_ID="alias/x",
        S3_KMS_KEY_ID="alias/y",
    )
    base.update(kw)
    return Settings(_env_file=None, **base)  # type: ignore[call-arg]


# --------------------------------------------------------------------------- production refusal


def test_fake_adapter_refused_in_production() -> None:
    problems = production_problems(_settings(JUDGE_PROVIDER="fake"))
    assert any("FakeJudgeAdapter" in p for p in problems)
    assert not any("FakeJudgeAdapter" in p for p in production_problems(_settings()))
    with pytest.raises(JudgeConfigurationError):
        get_judge_adapter(_settings(JUDGE_PROVIDER="fake"))
    set_judge_adapter(FakeJudgeAdapter())
    try:
        with pytest.raises(JudgeConfigurationError):
            get_judge_adapter(_settings(JUDGE_PROVIDER="judge0_cloud"))
    finally:
        set_judge_adapter(None)
    assert isinstance(get_judge_adapter(_settings(APP_ENV="test", JUDGE_PROVIDER="fake")), FakeJudgeAdapter)
    with pytest.raises(JudgeConfigurationError):  # placeholder credentials
        get_judge_adapter(_settings(APP_ENV="test", JUDGE_PROVIDER="judge0_cloud"))


def test_testcase_key_refused_in_production(monkeypatch) -> None:
    from app.core.config import reset_settings_cache

    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("TD_K_TESTCASE_KEY_V1", "local-placeholder-REPLACE")
    reset_settings_cache()
    crypto.reset_testcase_keyring()
    try:
        with pytest.raises(crypto.TestCaseCryptoError, match="production"):
            crypto.get_testcase_keyring()
    finally:
        monkeypatch.undo()
        reset_settings_cache()
        crypto.reset_testcase_keyring()


# --------------------------------------------------------------------------- crypto


def test_encryption_round_trip_and_tamper_detection() -> None:
    pid = uuid.uuid4()
    sealed = crypto.seal_case(pid, "1 2 3\n", "6\n")
    assert b"1 2 3" not in sealed.input_blob and b"6\n" not in sealed.expected_blob
    assert crypto.key_version(sealed.wrapped_data_key) == 1
    assert crypto.open_case(pid, sealed.wrapped_data_key, sealed.input_blob, sealed.expected_blob) == (
        "1 2 3\n",
        "6\n",
    )
    with pytest.raises(crypto.TestCaseCryptoError):  # AAD binds the problem id
        crypto.open_case(uuid.uuid4(), sealed.wrapped_data_key, sealed.input_blob, sealed.expected_blob)
    tampered = bytearray(sealed.input_blob)
    tampered[-1] ^= 1
    with pytest.raises(crypto.TestCaseCryptoError):
        crypto.open_case(pid, sealed.wrapped_data_key, bytes(tampered), sealed.expected_blob)
    # Swapping input/expected blobs is detected too.
    with pytest.raises(crypto.TestCaseCryptoError):
        crypto.open_case(pid, sealed.wrapped_data_key, sealed.expected_blob, sealed.input_blob)


def test_key_rotation_rewrap() -> None:
    pid = uuid.uuid4()
    v1 = crypto.TestCaseKeyring.from_env(
        {"TD_K_TESTCASE_KEY_V1": KEY_V1, "TD_K_TESTCASE_ACTIVE_VERSION": "1"}
    )
    sealed = crypto.seal_case(pid, "in", "out", v1)
    both = crypto.TestCaseKeyring.from_env(
        {"TD_K_TESTCASE_KEY_V1": KEY_V1, "TD_K_TESTCASE_KEY_V2": KEY_V2, "TD_K_TESTCASE_ACTIVE_VERSION": "2"}
    )
    assert both.production_safe
    assert crypto.open_case(pid, sealed.wrapped_data_key, sealed.input_blob, sealed.expected_blob, both) == (
        "in",
        "out",
    )
    rewrapped = crypto.rewrap(sealed.wrapped_data_key, pid, both)
    assert crypto.key_version(rewrapped) == 2
    assert crypto.rewrap(rewrapped, pid, both) is rewrapped
    v2_only = crypto.TestCaseKeyring.from_env(
        {"TD_K_TESTCASE_KEY_V2": KEY_V2, "TD_K_TESTCASE_ACTIVE_VERSION": "2"}
    )
    assert crypto.open_case(pid, rewrapped, sealed.input_blob, sealed.expected_blob, v2_only) == ("in", "out")
    with pytest.raises(crypto.TestCaseCryptoError, match="version 1 not loaded"):
        crypto.open_case(pid, sealed.wrapped_data_key, sealed.input_blob, sealed.expected_blob, v2_only)
    weak = crypto.TestCaseKeyring.from_env({"TD_K_TESTCASE_KEY_V1": "local-REPLACE"})
    assert not weak.production_safe and crypto.TestCaseKeyring.from_env({}).is_dev_fallback


async def test_db_key_rotation_job(db, actors, monkeypatch, fake_judge) -> None:
    author = await actors()
    p = await seed_problem(db, author.id)
    monkeypatch.setenv("TD_K_TESTCASE_KEY_V2", KEY_V2)
    monkeypatch.setenv("TD_K_TESTCASE_ACTIVE_VERSION", "2")
    crypto.reset_testcase_keyring()
    assert await service.rotate_wrapped_keys(db) == 2
    assert await service.rotate_wrapped_keys(db) == 0
    rows = (
        (
            await db.execute(
                select(CodingTestCase).where(
                    CodingTestCase.coding_problem_id == p.id, CodingTestCase.is_hidden.is_(True)
                )
            )
        )
        .scalars()
        .all()
    )
    assert {crypto.key_version(r.wrapped_data_key or b"") for r in rows} == {2}
    # Retire v1: the worker can still decrypt every hidden case.
    monkeypatch.delenv("TD_K_TESTCASE_KEY_V1")
    crypto.reset_testcase_keyring()
    sub = await service.create_submission(
        db,
        user_id=author.id,
        organization_id=None,
        problem=p,
        language_key="python3",
        mode="submit",
        source_code="# FAKE_VERDICT: AC",
        idempotency_key="rotation-check-1",
    )
    assert await judge_submission(db, sub.id, fake_judge, budget_s=1) == "AC"


# --------------------------------------------------------------------------- verdicts / checker


def test_checker_and_verdict_mapping() -> None:
    assert outputs_match("6  \n\n", "6\n", "exact", None)
    assert not outputs_match("6 0\n", "6\n", "exact", None)
    assert outputs_match("1   2\n3", "1 2 3\n", "token", None)
    assert outputs_match("0.3333334\n", "0.3333333", "float_tolerance", {"abs": 1e-6})
    assert not outputs_match("0.34", "0.33", "float_tolerance", None)
    assert outputs_match("x", "x", "custom", None) is None
    ok = JudgeRunResult("t", "ok", stdout="6\n")
    assert case_verdict(ok, "6\n", "exact", None) == "AC"
    assert case_verdict(ok, "7\n", "exact", None) == "WA"
    assert case_verdict(ok, None, "exact", None) == "AC"
    assert case_verdict(ok, "6\n", "custom", None) == "IE"
    for st in ("CE", "TLE", "MLE", "RE", "IE"):
        assert case_verdict(JudgeRunResult("t", st), "6\n", "exact", None) == st  # type: ignore[arg-type]
    # Judge0 status ids
    assert [map_status(i) for i in (1, 2, 3, 5, 6, 7, 11, 13, 14, 99)] == [
        "pending",
        "pending",
        "ok",
        "TLE",
        "CE",
        "RE",
        "RE",
        "IE",
        "RE",
        "IE",
    ]
    assert map_status(7, memory_kb=262000, memory_limit_kb=262144) == "MLE"
    assert fake_verdicts("x") == ["WA"] and fake_verdicts("# FAKE_VERDICT: AC, TLE") == ["AC", "TLE"]


def test_aggregate_scoring() -> None:
    cases = [
        ScoredCase(1, Decimal(1), "AC"),
        ScoredCase(2, Decimal(4), "WA"),
        ScoredCase(3, Decimal(5), "AC"),
    ]
    a = aggregate(cases, "weighted_cases")
    assert (a.verdict, a.score, a.max_score, a.passed) == ("PARTIAL", Decimal(6), Decimal(10), 2)
    assert a.awarded == {1: Decimal(1), 2: Decimal(0), 3: Decimal(5)}
    b = aggregate(cases, "all_or_nothing")
    assert (b.verdict, b.score) == ("WA", Decimal(0))
    c = aggregate([ScoredCase(1, Decimal(1), "TLE"), ScoredCase(2, Decimal(1), "RE")], "weighted_cases")
    assert c.verdict == "RE" and c.score == 0
    assert aggregate([ScoredCase(1, Decimal(2), "AC")], "all_or_nothing").score == Decimal(2)


# --------------------------------------------------------------------------- Judge0 adapter (mocked HTTP)


async def test_judge0_adapter_batch_payload_and_polling() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.method == "POST":
            return httpx.Response(201, json=[{"token": "t1"}, {"token": "t2"}])
        polls = sum(1 for r in seen if r.method == "GET")
        if polls == 1:
            return httpx.Response(
                200,
                json={
                    "submissions": [
                        {"token": "t1", "status": {"id": 2}},
                        {"token": "t2", "status": {"id": 1}},
                    ]
                },
            )
        out = base64.b64encode(b"6\n").decode()
        return httpx.Response(
            200,
            json={
                "submissions": [
                    {
                        "token": "t1",
                        "status": {"id": 3},
                        "stdout": out,
                        "time": "0.012",
                        "memory": 3100,
                        "exit_code": 0,
                    },
                    {"token": "t2", "status": {"id": 5}, "stdout": None, "time": "5.0", "memory": 900},
                ]
            },
        )

    adapter = Judge0Adapter(
        "https://judge.example.test", "secret-key", transport=httpx.MockTransport(handler)
    )
    big = JudgeLimits.for_problem(
        time_limit_ms=5000,
        wall_limit_ms=10000,
        memory_limit_kb=524288,
        time_multiplier=2.5,
        memory_extra_kb=65536,
        max_processes=500,
    )
    jobs = [
        JudgeJob(1, "print(6)", "python3", 71, "1 2 3\n", LIMITS, expected_output="SECRET"),
        JudgeJob(2, "print(6)", "python3", 71, "x\n", big, expected_output="SECRET"),
    ]
    results = await run_jobs(adapter, jobs, budget_s=5, first_delay_s=0.01)
    assert [r.status for r in results] == ["ok", "TLE"]
    assert results[0].stdout == "6\n" and results[0].time_ms == 12 and results[0].memory_kb == 3100

    post = seen[0]
    assert post.url.path == "/submissions/batch" and post.url.params["base64_encoded"] == "true"
    assert post.headers["X-Auth-Token"] == "secret-key"
    payload = json.loads(post.content)["submissions"]
    for item in payload:
        assert item["enable_network"] is False
        assert "expected_output" not in item  # checking happens in our worker
        assert base64.b64decode(item["source_code"]) == b"print(6)"
    assert base64.b64decode(payload[0]["stdin"]) == b"1 2 3\n"
    # Hard caps: CPU 5 s, wall 10 s, memory 256 MB.
    assert payload[1]["cpu_time_limit"] == 5.0 and payload[1]["wall_time_limit"] == 10.0
    assert payload[1]["memory_limit"] == 262144 and payload[1]["max_processes_and_or_threads"] == 128
    assert payload[0]["cpu_time_limit"] == 2.0 and payload[0]["wall_time_limit"] == 5.0
    get = seen[1]
    assert get.url.params["tokens"] == "t1,t2"


async def test_judge0_adapter_unavailable_and_timeout() -> None:
    down = Judge0Adapter(
        "https://judge.example.test", "k", transport=httpx.MockTransport(lambda r: httpx.Response(503))
    )
    with pytest.raises(JudgeUnavailable):
        await down.submit_batch([JudgeJob(1, "x", "c", 50, "", LIMITS)])

    def slow(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(201, json=[{"token": "t1"}])
        return httpx.Response(200, json={"submissions": [{"token": "t1", "status": {"id": 1}}]})

    stuck = Judge0Adapter("https://judge.example.test", "k", transport=httpx.MockTransport(slow))
    with pytest.raises(JudgeTimeout):
        await run_jobs(stuck, [JudgeJob(1, "x", "c", 50, "", LIMITS)], budget_s=0.05, first_delay_s=0.01)
    with pytest.raises(ValueError):
        Judge0Adapter("http://insecure.example", "k")


# --------------------------------------------------------------------------- worker failure handling


class _Down(FakeJudgeAdapter):
    async def submit_batch(self, jobs):  # type: ignore[override]
        raise JudgeUnavailable("down")


class _Stuck(FakeJudgeAdapter):
    async def poll(self, tokens):  # type: ignore[override]
        return [JudgeRunResult(t, "pending") for t in tokens]


async def test_worker_outage_requeues_and_timeout_retries_once(client, db, actors, access) -> None:
    author = await actors()
    p = await seed_problem(db, author.id)
    st = await actors()
    r = await client.post(
        f"/api/v1/coding/problems/{p.id}/submit",
        json={"language_key": "python3", "source_code": "# FAKE_VERDICT: AC"},
        headers=idem(st.headers),
    )
    sid = uuid.UUID(r.json()["submission_id"])
    assert await judge_submission(db, sid, _Down(), budget_s=0.05) == "requeued_judge_degraded"
    g = (await client.get(f"/api/v1/coding/submissions/{sid}", headers=st.headers)).json()
    assert g["status"] == "queued" and g["notice"] == "judge_degraded"
    assert await judge_submission(db, sid, _Stuck(), budget_s=0.01) == "requeued_after_timeout"
    assert await judge_submission(db, sid, _Stuck(), budget_s=0.01) == "judge_timeout"
    g = (await client.get(f"/api/v1/coding/submissions/{sid}", headers=st.headers)).json()
    assert g["status"] == "judge_timeout"
    assert await judge_submission(db, sid, FakeJudgeAdapter()) == "not_claimed"


async def test_process_pending_priority_and_outbox(client, db, actors, access, fake_judge) -> None:
    author = await actors()
    p = await seed_problem(db, author.id)
    st = await actors()
    r = await client.post(
        f"/api/v1/coding/problems/{p.id}/run",
        json={"language_key": "python3", "source_code": "# FAKE_VERDICT: AC"},
        headers=idem(st.headers),
    )
    run_id = uuid.UUID(r.json()["submission_id"])
    await system_context(db, "test.factory")
    h = await service.judge_for_attempt(
        db,
        user_id=st.id,
        organization_id=None,
        attempt_id=uuid.uuid4(),
        problem_id=p.id,
        language_key="python3",
        source_code="# FAKE_VERDICT: AC,WA",
        idempotency_key="attempt-key-1",
    )
    assert h.queue == "judge_assessment" and h.status == "queued"
    again = await service.judge_for_attempt(
        db,
        user_id=st.id,
        organization_id=None,
        attempt_id=uuid.uuid4(),
        problem_id=p.id,
        language_key="python3",
        source_code="# FAKE_VERDICT: AC,WA",
        idempotency_key="attempt-key-1",
    )
    assert again.submission_id == h.submission_id
    await db.flush()
    done = await process_pending(fake_judge, limit=10)
    order = list(done)
    assert order.index(h.submission_id) < order.index(run_id)  # judge_assessment before judge_run
    assert done[h.submission_id] == "PARTIAL" and done[run_id] == "AC"
    j = await service.get_attempt_judgement(db, h.submission_id)
    assert j is not None and j.status == "completed" and j.verdict == "PARTIAL"
    assert j.score == Decimal(1) and j.max_score == Decimal(3)  # sample AC; both hidden WA
    await system_context(db, "test.check")
    from app.core.models import OutboxEvent

    evts = (
        (
            await db.execute(
                select(OutboxEvent).where(
                    OutboxEvent.event_type == "submission.judged", OutboxEvent.aggregate_id == h.submission_id
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(evts) == 1 and "SECRET" not in json.dumps(evts[0].payload)
    sub = await db.get(CodeSubmission, h.submission_id)
    assert sub is not None and sub.attempt_id is not None


async def test_submit_with_attempt_fails_closed_without_validator(client, db, actors, access) -> None:
    author = await actors()
    p = await seed_problem(db, author.id)
    st = await actors()
    # Stage 10: app.wiring registers the assessments validator -> an unknown attempt is a 404.
    r = await client.post(
        f"/api/v1/coding/problems/{p.id}/submit",
        json={"language_key": "python3", "source_code": "x", "attempt_id": str(uuid.uuid4())},
        headers=idem(st.headers),
    )
    assert r.status_code == 404, r.text
    service.register_attempt_validator(None)
    r = await client.post(
        f"/api/v1/coding/problems/{p.id}/submit",
        json={"language_key": "python3", "source_code": "x", "attempt_id": str(uuid.uuid4())},
        headers=idem(st.headers),
    )
    assert r.status_code == 409 and r.json()["code"] == "attempt_closed"

    calls = []

    async def validator(session, principal, attempt_id, problem_id):
        calls.append((attempt_id, problem_id))

    service.register_attempt_validator(validator)
    try:
        att = uuid.uuid4()
        r = await client.post(
            f"/api/v1/coding/problems/{p.id}/submit",
            json={"language_key": "python3", "source_code": "x", "attempt_id": str(att)},
            headers=idem(st.headers),
        )
        assert r.status_code == 202 and r.json()["queue"] == "judge_assessment"
        assert calls == [(att, p.id)]
    finally:
        service.register_attempt_validator(None)
