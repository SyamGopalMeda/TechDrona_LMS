"""RFC 9457 problem details (api-specification.md §1.13, error catalogue §2).

Raise ``ProblemError("code", ...)`` anywhere; the registered handlers render
``application/problem+json`` with ``type``, ``title``, ``status``, ``detail``, ``code`` and
``request_id``. Stack traces, SQL and internal ids are never returned.
"""

from __future__ import annotations

from typing import Any

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import exc as sa_exc
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.requests import ClientDisconnect
from starlette.responses import Response

from app.core.request_context import get_request_id

PROBLEM_CONTENT_TYPE = "application/problem+json"
PROBLEM_TYPE_BASE = "https://techdrona.in/problems/"

log = structlog.get_logger("app.errors")

# code -> (default HTTP status, default title). Source: api-specification.md §2.
ERROR_CATALOGUE: dict[str, tuple[int, str]] = {
    # 2.1 Generic and authentication
    "validation_failed": (400, "Some fields need attention"),
    "invalid_cursor": (400, "Invalid or expired page cursor"),
    "idempotency_key_required": (400, "Idempotency-Key header required"),
    "idempotency_key_reuse": (409, "Idempotency-Key reused with a different request"),
    "idempotency_in_progress": (409, "The original request is still being processed"),
    "unauthenticated": (401, "Please sign in"),
    "session_expired": (401, "Your session has expired"),
    "session_revoked": (401, "You have been signed out"),
    "login_incomplete": (401, "Finish signing in"),
    "step_up_required": (401, "Please confirm it's you"),
    "invalid_credentials": (401, "Incorrect sign-in details"),
    "remember_invalid": (401, "Please sign in again"),
    "csrf_failed": (403, "Request could not be verified"),
    "permission_denied": (403, "You don't have permission to do this"),
    "mfa_enrolment_required": (403, "Set up two-step verification"),
    "consent_required": (403, "Please review and accept the updated terms"),
    "contact_not_verified": (403, "Verify your contact details"),
    "minor_consent_pending": (403, "Guardian consent is pending"),
    "reason_code_required": (403, "A reason is required"),
    "sod_violation": (403, "Separation of duties"),
    "conflict_of_interest": (403, "Conflict of interest"),
    "not_found": (404, "Not found"),
    "invalid_state_transition": (409, "Action not allowed in the current state"),
    "version_conflict": (412, "This item was changed by someone else"),
    "precondition_required": (428, "If-Match header required"),
    "payload_too_large": (413, "Request too large"),
    "unsupported_media_type": (415, "Unsupported media type"),
    "rate_limited": (429, "Too many requests"),
    "throttled": (429, "Too many attempts"),
    "service_unavailable": (503, "Service temporarily unavailable"),
    "maintenance": (503, "Down for maintenance"),
    # Foundation additions (not in §2; generic transport-level failures)
    "method_not_allowed": (405, "Method not allowed"),
    # Unique-constraint race lost to a concurrent request (DB-03): never a 500.
    "conflict": (409, "This was changed by another request"),
    "internal_error": (500, "Something went wrong"),
    # 2.2 Security, sessions and devices
    "account_restricted": (403, "Account access paused"),
    "account_protect_locked": (403, "Account locked for your protection"),
    "device_verification_required": (403, "Verify this device"),
    "session_too_short_for_attempt": (409, "Session too short for this attempt"),
    "session_cap_reached": (409, "Too many active sessions"),
    "device_cap_reached": (409, "Device limit reached"),
    "device_replacement_quota_exhausted": (409, "Device replacement limit reached"),
    "playback_conflict": (409, "Video is playing on another device"),
    "playback_revoked": (410, "Playback session ended"),
    "otp_invalid": (400, "Incorrect code"),
    "otp_expired": (400, "Code expired"),
    "otp_attempts_exceeded": (429, "Too many incorrect codes"),
    "otp_send_limited": (429, "Too many codes requested"),
    "decision_required": (409, "A case decision is required"),
    "second_approval_required": (409, "A second approval is required"),
    "explanation_not_viewed": (409, "Open the explanation and timeline first"),
    "unblock_request_open": (409, "An unblock request is already open"),
    "unblock_rate_limited": (429, "Too many unblock requests"),
    "dlp_rejected": (422, "Please remove passwords or codes from your message"),
    "appeal_window_closed": (409, "Appeal window closed"),
    "appeal_already_used": (409, "Appeal already used"),
    "shadow_period_incomplete": (409, "Shadow period incomplete"),
    "k_anonymity_floor": (403, "Group too small to report"),
    # 2.3 Assessments, coding, media
    "attempt_bound_elsewhere": (409, "Test open on another device"),
    "rebind_limit_reached": (409, "Device switch limit reached"),
    "active_attempt_exists": (409, "You already have an attempt in progress"),
    "attempt_limit_reached": (409, "No attempts left"),
    "test_not_open": (409, "Test not open yet"),
    "test_window_closed": (409, "Test window closed"),
    "attempt_closed": (409, "Attempt closed"),
    "section_locked": (409, "Section locked"),
    "test_settings_locked": (409, "Test settings locked"),
    "results_not_released": (409, "Results not released yet"),
    "judge_queue_full": (409, "Code runner busy"),
    "language_not_allowed": (422, "Language not allowed"),
    "submission_in_flight": (409, "A submission is already being judged"),
    "entitlement_required": (403, "Access requires a plan"),
    # 2.4 Commerce and entitlements
    "already_owned": (409, "You already own this"),
    "coupon_invalid": (422, "Coupon invalid"),
    "coupon_expired": (422, "Coupon expired"),
    "coupon_cap_reached": (422, "Coupon limit reached"),
    "coupon_not_applicable": (422, "Coupon not applicable"),
    "order_expired": (409, "Order expired"),
    "payment_signature_invalid": (400, "Payment could not be verified"),
    "webhook_signature_invalid": (400, "Webhook signature invalid"),
    "refund_not_eligible": (409, "Refund not eligible"),
    "recurring_amount_exceeds_mandate_limit": (422, "Recurring amount exceeds mandate limit"),
}

_RESERVED = {"type", "title", "status", "detail", "code", "request_id", "instance"}


class ProblemError(Exception):
    """An API error rendered as RFC 9457 problem+json.

    ``ext`` members are added to the body (e.g. ``case_ref``, ``errors``). ``headers`` are
    added to the response (e.g. ``Retry-After``).
    """

    def __init__(
        self,
        code: str,
        status: int | None = None,
        title: str | None = None,
        detail: str | None = None,
        *,
        headers: dict[str, str] | None = None,
        **ext: Any,
    ) -> None:
        default_status, default_title = ERROR_CATALOGUE.get(code, (500, "Error"))
        self.code = code
        self.status = status or default_status
        self.title = title or default_title
        self.detail = detail or self.title
        self.headers = dict(headers or {})
        bad = _RESERVED.intersection(ext)
        if bad:
            raise ValueError(f"reserved problem members in ext: {sorted(bad)}")
        self.ext = ext
        super().__init__(f"{self.status} {code}: {self.detail}")

    def to_body(self, request_id: str | None) -> dict[str, Any]:
        body: dict[str, Any] = {
            "type": PROBLEM_TYPE_BASE + self.code.replace("_", "-"),
            "title": self.title,
            "status": self.status,
            "code": self.code,
            "detail": self.detail,
            "request_id": request_id,
        }
        body.update(self.ext)
        return body


def problem_response(exc: ProblemError, request_id: str | None = None) -> JSONResponse:
    rid = request_id or get_request_id()
    headers = dict(exc.headers)
    if rid:
        headers["X-Request-Id"] = rid
    return JSONResponse(
        exc.to_body(rid), status_code=exc.status, headers=headers, media_type=PROBLEM_CONTENT_TYPE
    )


def _validation_errors(exc: RequestValidationError) -> list[dict[str, str]]:
    out = []
    for err in exc.errors():
        loc = [str(p) for p in err.get("loc", ()) if p not in ("body", "query", "path", "header")]
        out.append(
            {
                "field": ".".join(loc) or "body",
                "code": str(err.get("type", "invalid")),
                "message": str(err.get("msg", "Invalid value")),
            }
        )
    return out


async def _problem_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, ProblemError)
    return problem_response(exc)


async def _validation_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)
    return problem_response(
        ProblemError(
            "validation_failed",
            400,
            detail="The request is not valid. Check the listed fields.",
            errors=_validation_errors(exc),
        )
    )


_HTTP_CODE_MAP = {
    400: "validation_failed",
    401: "unauthenticated",
    403: "permission_denied",
    404: "not_found",
    405: "method_not_allowed",
    413: "payload_too_large",
    415: "unsupported_media_type",
    429: "rate_limited",
    503: "service_unavailable",
}


async def _http_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, StarletteHTTPException)
    code = _HTTP_CODE_MAP.get(exc.status_code, "internal_error" if exc.status_code >= 500 else "not_found")
    # Never echo framework detail strings for 5xx; for 4xx keep the catalogue title.
    return problem_response(ProblemError(code, exc.status_code, headers=dict(exc.headers or {})))


# Seconds a client should wait before retrying when the database is saturated.
DB_BUSY_RETRY_AFTER_SECONDS = 2
# nginx's de-facto "client closed request" status; never reaches the client, only logs/metrics.
CLIENT_CLOSED_REQUEST = 499
# asyncpg errors (by class name, so asyncpg stays an optional import here) meaning the server
# is refusing new connections: transient capacity, not a bug.
_CAPACITY_ERRORS = {"TooManyConnectionsError", "CannotConnectNowError"}


def is_db_capacity_error(exc: BaseException) -> bool:
    """Connection-pool checkout timed out, or Postgres refused a new connection."""
    if isinstance(exc, sa_exc.TimeoutError):  # QueuePool limit ... reached, connection timed out
        return True
    if isinstance(exc, sa_exc.DBAPIError):
        orig = getattr(exc, "orig", None)
        names = {type(orig).__name__, type(getattr(orig, "__cause__", None)).__name__}
        return bool(names & _CAPACITY_ERRORS)
    return False


def db_busy_response(request: Request, exc: BaseException) -> JSONResponse:
    rid = getattr(request.state, "request_id", None) or get_request_id()
    log.warning("db_capacity_exhausted", exc_type=type(exc).__name__, path=request.url.path, request_id=rid)
    return problem_response(
        ProblemError(
            "service_unavailable",
            detail="The service is busy. Please try again in a moment.",
            headers={"Retry-After": str(DB_BUSY_RETRY_AFTER_SECONDS)},
        ),
        rid,
    )


def client_disconnect_response(request: Request) -> Response:
    """The client went away mid-request (page navigation, beacon cancelled): not a server error."""
    rid = getattr(request.state, "request_id", None) or get_request_id()
    log.info("client_disconnected", path=request.url.path, request_id=rid)
    return Response(status_code=CLIENT_CLOSED_REQUEST)


# --------------------------------------------------------------------------- unique violations

_UNIQUE_VIOLATION = "23505"
_EXCLUSION_VIOLATION = "23P01"
# constraint/index name -> (problem code, detail). Modules (or ``app.wiring``) register the
# specific meaning of their uniqueness rules; anything else maps to the generic ``conflict``.
_UNIQUE_CONFLICTS: dict[str, tuple[str, str | None]] = {}


def register_unique_conflict(constraint: str, code: str, detail: str | None = None) -> None:
    """Map a unique constraint/index name to the 409 problem a client should see when a
    concurrent request wins the race (DB-03/BE-15/BE-22)."""
    if code not in ERROR_CATALOGUE:
        raise ValueError(f"unknown problem code {code!r}")
    _UNIQUE_CONFLICTS[constraint] = (code, detail)


def _pg_error(exc: BaseException) -> tuple[str | None, str | None]:
    """``(sqlstate, constraint_name)`` from a SQLAlchemy DBAPIError (asyncpg or psycopg)."""
    orig = getattr(exc, "orig", None)
    candidates = [orig, getattr(orig, "__cause__", None)]
    state = constraint = None
    for c in candidates:
        if c is None:
            continue
        state = state or getattr(c, "sqlstate", None) or getattr(c, "pgcode", None)
        diag = getattr(c, "diag", None)
        constraint = (
            constraint or getattr(c, "constraint_name", None) or getattr(diag, "constraint_name", None)
        )
    return (str(state) if state else None), constraint


def unique_conflict_problem(exc: BaseException) -> ProblemError | None:
    """409 problem for a unique/exclusion violation, else ``None``."""
    if not isinstance(exc, sa_exc.IntegrityError):
        return None
    state, constraint = _pg_error(exc)
    if state not in (_UNIQUE_VIOLATION, _EXCLUSION_VIOLATION):
        return None
    code, detail = _UNIQUE_CONFLICTS.get(constraint or "", ("conflict", None))
    return ProblemError(
        code,
        detail=detail or "Another request changed this at the same time. Refresh and try again.",
    )


async def _db_error_handler(request: Request, exc: Exception) -> Response:
    if is_db_capacity_error(exc):
        return db_busy_response(request, exc)
    problem = unique_conflict_problem(exc)
    if problem is not None:
        rid = getattr(request.state, "request_id", None) or get_request_id()
        _state, constraint = _pg_error(exc)
        log.info("unique_conflict", constraint=constraint, code=problem.code, path=request.url.path)
        return problem_response(problem, rid)
    raise exc  # any other DB error stays a 500 through the outermost handler


async def _client_disconnect_handler(request: Request, exc: Exception) -> Response:
    return client_disconnect_response(request)


async def _unhandled_handler(request: Request, exc: Exception) -> Response:
    # Runs in Starlette's outermost ServerErrorMiddleware, i.e. after the request-context
    # middleware has unwound: take the id from request state.
    if is_db_capacity_error(exc):
        return db_busy_response(request, exc)
    conflict = unique_conflict_problem(exc)
    if conflict is not None:  # raised from a dependency's commit (outside the route handlers)
        return problem_response(conflict, getattr(request.state, "request_id", None) or get_request_id())
    if isinstance(exc, ClientDisconnect):
        return client_disconnect_response(request)
    rid = getattr(request.state, "request_id", None) or get_request_id()
    log.exception("unhandled_exception", exc_type=type(exc).__name__, request_id=rid)
    return problem_response(ProblemError("internal_error", 500), rid)


def install_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(ProblemError, _problem_handler)
    app.add_exception_handler(RequestValidationError, _validation_handler)
    app.add_exception_handler(StarletteHTTPException, _http_handler)
    app.add_exception_handler(sa_exc.TimeoutError, _db_error_handler)
    app.add_exception_handler(sa_exc.DBAPIError, _db_error_handler)
    app.add_exception_handler(ClientDisconnect, _client_disconnect_handler)
    app.add_exception_handler(Exception, _unhandled_handler)
