"""Idempotency-Key handling (api-specification §1.8) backed by ``idempotency_keys``.

Usage inside a route (session = the request's transaction)::

    @router.post("/orders", status_code=201)
    async def create_order(request: Request, body: OrderIn, session: PrincipalDbSession,
                           principal: Principal = Depends(require_active_principal)):
        async def op() -> IdemResult:
            order = await service.create(session, ...)
            return IdemResult(body=OrderOut.model_validate(order).model_dump(mode="json"),
                              status=201, resource_id=order.id)
        return await idempotent(request, session, user_id=principal.user_id, operation=op,
                                money=True)

Semantics:
* missing header -> ``400 idempotency_key_required`` (``required=True``);
* replay with same request hash -> stored status/body + ``Idempotency-Replayed: true``;
* same key, different hash -> ``409 idempotency_key_reuse``;
* concurrent duplicate -> blocks on the unique key until the original commits, then replays
  (or ``409 idempotency_in_progress`` if it still sees ``in_progress``);
* 4xx ``ProblemError`` results are stored and replayed (business writes rolled back to a
  savepoint); 5xx/unexpected errors are not stored; ``401 step_up_required`` is not stored.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse
from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import PROBLEM_CONTENT_TYPE, ProblemError
from app.core.ids import uuid7
from app.core.models import IdempotencyKey
from app.core.request_context import get_request_id
from app.core.time import utcnow

HEADER = "Idempotency-Key"
DEFAULT_TTL = timedelta(hours=24)
MONEY_TTL = timedelta(days=7)
_NOT_STORED_CODES = frozenset({"step_up_required"})


@dataclass(slots=True)
class IdemResult:
    body: Any
    status: int = 200
    resource_id: uuid.UUID | None = None
    headers: dict[str, str] | None = None


def _valid_key(key: str) -> bool:
    return 8 <= len(key) <= 128 and all(33 <= ord(c) <= 126 for c in key)


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str).encode(
        "utf-8"
    )


async def request_hash(request: Request) -> bytes:
    """SHA-256(canonical JSON body ‖ canonical path params)."""
    raw = await request.body()
    try:
        body_part = canonical_json(json.loads(raw)) if raw else b""
    except (ValueError, UnicodeDecodeError):
        body_part = raw
    return hashlib.sha256(body_part + b"\x1f" + canonical_json(dict(request.path_params))).digest()


def route_key(request: Request) -> str:
    route = request.scope.get("td_route") or request.scope.get("route")
    path = getattr(route, "path", request.url.path)
    return f"{request.method} {path}"


def _replay(row: IdempotencyKey) -> JSONResponse:
    body = row.response_body
    is_problem = (
        isinstance(body, dict) and "code" in body and "type" in body and (row.response_status or 0) >= 400
    )
    return JSONResponse(
        body,
        status_code=row.response_status or 200,
        headers={"Idempotency-Replayed": "true"},
        media_type=PROBLEM_CONTENT_TYPE if is_problem else None,
    )


async def idempotent(
    request: Request,
    session: AsyncSession,
    *,
    user_id: uuid.UUID | None,
    operation: Callable[[], Awaitable[IdemResult]],
    required: bool = True,
    money: bool = False,
) -> JSONResponse:
    key = request.headers.get(HEADER)
    if not key:
        if required:
            raise ProblemError("idempotency_key_required")
        res = await operation()
        return JSONResponse(res.body, status_code=res.status, headers=res.headers)
    if not _valid_key(key):
        raise ProblemError(
            "validation_failed",
            errors=[{"field": HEADER, "code": "invalid", "message": "8-128 printable ASCII characters"}],
        )

    rkey = route_key(request)
    rhash = await request_hash(request)
    now = utcnow()
    ttl = MONEY_TTL if money else DEFAULT_TTL

    # Purge an expired previous use of this key so it can be reused.
    await session.execute(
        delete(IdempotencyKey).where(
            IdempotencyKey.user_id.is_not_distinct_from(user_id),
            IdempotencyKey.route_key == rkey,
            IdempotencyKey.idem_key == key,
            IdempotencyKey.expires_at < now,
        )
    )
    row_id = uuid7()
    inserted = await session.execute(
        pg_insert(IdempotencyKey)
        .values(
            id=row_id,
            user_id=user_id,
            route_key=rkey,
            idem_key=key,
            request_hash=rhash,
            status="in_progress",
            expires_at=now + ttl,
        )
        .on_conflict_do_nothing()
        .returning(IdempotencyKey.id)
    )
    if inserted.scalar_one_or_none() is None:
        existing = (
            await session.execute(
                select(IdempotencyKey).where(
                    IdempotencyKey.user_id.is_not_distinct_from(user_id),
                    IdempotencyKey.route_key == rkey,
                    IdempotencyKey.idem_key == key,
                )
            )
        ).scalar_one_or_none()
        if existing is None:  # deleted concurrently; ask the client to retry
            raise ProblemError("idempotency_in_progress", headers={"Retry-After": "1"})
        if existing.request_hash != rhash:
            raise ProblemError("idempotency_key_reuse")
        if existing.status == "in_progress":
            raise ProblemError("idempotency_in_progress", headers={"Retry-After": "1"})
        return _replay(existing)

    savepoint = await session.begin_nested()
    try:
        result = await operation()
    except ProblemError as exc:
        if exc.status >= 500 or exc.code in _NOT_STORED_CODES:
            raise
        await savepoint.rollback()
        problem = exc.to_body(get_request_id())
        await _finish(session, row_id, "failed", exc.status, problem, None)
        return JSONResponse(
            problem, status_code=exc.status, headers=exc.headers, media_type=PROBLEM_CONTENT_TYPE
        )
    if savepoint.is_active:
        await savepoint.commit()
    body = json.loads(canonical_json(result.body)) if result.body is not None else None
    await _finish(session, row_id, "completed", result.status, body, result.resource_id)
    return JSONResponse(body, status_code=result.status, headers=result.headers)


async def _finish(
    session: AsyncSession,
    row_id: uuid.UUID,
    status: str,
    response_status: int,
    body: Any,
    resource_id: uuid.UUID | None,
) -> None:
    await session.execute(
        update(IdempotencyKey)
        .where(IdempotencyKey.id == row_id)
        .values(status=status, response_status=response_status, response_body=body, resource_id=resource_id)
    )
