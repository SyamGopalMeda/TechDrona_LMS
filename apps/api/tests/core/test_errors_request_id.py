from __future__ import annotations

from app.core.errors import ERROR_CATALOGUE, ProblemError

PROBLEM = "application/problem+json"


def _assert_problem(resp, status: int, code: str) -> dict:
    assert resp.status_code == status, resp.text
    assert resp.headers["content-type"].startswith(PROBLEM)
    body = resp.json()
    for k in ("type", "title", "status", "detail", "code", "request_id"):
        assert k in body
    assert body["status"] == status
    assert body["code"] == code
    assert body["type"] == "https://techdrona.in/problems/" + code.replace("_", "-")
    assert body["request_id"] == resp.headers["x-request-id"]
    return body


async def test_unknown_route_is_problem_not_found(probe_client) -> None:
    _assert_problem(await probe_client.get("/api/v1/nope"), 404, "not_found")


async def test_problem_error_extension_members(probe_client) -> None:
    body = _assert_problem(await probe_client.get("/api/v1/_probe/problem"), 409, "invalid_state_transition")
    assert body["current_state"] == "closed"
    assert body["allowed"] == ["reopen"]


async def test_validation_error_lists_fields(probe_client) -> None:
    resp = await probe_client.post("/api/v1/_probe/echo", json={"name": "a", "count": "x", "extra": 1})
    body = _assert_problem(resp, 400, "validation_failed")
    fields = {e["field"] for e in body["errors"]}
    assert {"count", "extra"} <= fields


async def test_unhandled_exception_hides_details(probe_client) -> None:
    resp = await probe_client.get("/api/v1/_probe/boom")
    body = _assert_problem(resp, 500, "internal_error")
    assert "secret internal detail" not in resp.text
    assert "Traceback" not in resp.text
    assert body["detail"] == ERROR_CATALOGUE["internal_error"][1]


async def test_request_id_generated_and_echoed(probe_client) -> None:
    r1 = await probe_client.get("/api/v1/health/live")
    rid = r1.headers["x-request-id"]
    assert len(rid) == 26  # ULID rendering of a UUIDv7
    r2 = await probe_client.get("/api/v1/health/live", headers={"X-Request-Id": "bff-req-0001-abcdef"})
    assert r2.headers["x-request-id"] == "bff-req-0001-abcdef"


async def test_unsafe_incoming_request_id_is_replaced(probe_client) -> None:
    bad = "<script>alert(1)</script>"
    r = await probe_client.get("/api/v1/health/live", headers={"X-Request-Id": bad})
    assert r.headers["x-request-id"] != bad
    assert len(r.headers["x-request-id"]) == 26


async def test_body_limit_413(probe_client) -> None:
    resp = await probe_client.post(
        "/api/v1/_probe/echo",
        content=b"{" + b" " * (300 * 1024) + b"}",
        headers={"content-type": "application/json"},
    )
    body = _assert_problem(resp, 413, "payload_too_large")
    assert body["max_bytes"] == 256 * 1024


def test_problem_error_rejects_reserved_ext() -> None:
    try:
        ProblemError("not_found", code="x")  # type: ignore[call-arg]
    except (ValueError, TypeError):
        return
    raise AssertionError("reserved member accepted")


def test_catalogue_contains_spec_codes() -> None:
    for code in (
        "unauthenticated",
        "step_up_required",
        "account_restricted",
        "idempotency_key_reuse",
        "playback_conflict",
        "attempt_bound_elsewhere",
        "maintenance",
    ):
        assert code in ERROR_CATALOGUE
