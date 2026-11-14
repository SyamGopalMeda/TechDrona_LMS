"""Audit read API (api-specification §24, AUD-01..03). Read-only: no endpoint can modify
or delete audit rows. Every query is itself audited (``audit.query``).

Results are filtered by role (AUD-01, role matrix §3 ``audit.read``; SoD-01). Single company
(owner decision D2): the security reviewer and finance admin roles were folded into Admin, so
``super_admin`` @P is the only reader and sees every event with the full IP. The event-family
filter below stays for any future family-scoped reader role: rows outside the caller's families
are invisible (detail → 404) and callers outside ``FULL_IP_ROLES`` get the IP truncated.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import Depends, Query, Request
from sqlalchemy import ColumnElement, false, or_, select

from app.core.audit import audit
from app.core.auth import require_permission
from app.core.db import PrincipalDbSession
from app.core.errors import ProblemError
from app.core.firestore.backend import uses_firestore
from app.core.pagination import DEFAULT_LIMIT, MAX_LIMIT, decode_cursor, page_meta
from app.core.principal import Principal
from app.core.routing import authenticated_router
from app.modules.audit.models import AuditLog
from app.modules.audit.schemas import (
    AuditEventDetailOut,
    AuditEventList,
    AuditEventOut,
    ChainStatusOut,
    PageMeta,
)
from app.modules.audit.sealer import verify_chain
from app.modules.rbac.catalogue import admin_roles

router = authenticated_router(prefix="/audit", tags=["audit"])

AuditReader = Annotated[Principal, Depends(require_permission("audit.read"))]

# Event families (by action prefix, target type, or the action type of an approval request).
SECURITY_PREFIXES = ("security.", "risk.", "unblock.", "case.", "restriction.")
SECURITY_TARGETS = (
    "security_case",
    "security_incident",
    "security_report",
    "security_report_export",
    "security_bulk_lift",
    "unblock_request",
    "account_restriction",
    "risk_rule_version",
    "risk_evaluation",
    "risk_engine",
)
COMMERCE_PREFIXES = (
    "commerce.",
    "order.",
    "invoice.",
    "refund.",
    "coupon.",
    "plan.",
    "price.",
    "product.",
    "subscription.",
    "reconciliation.",
    "payment.",
    "credit_note.",
)
COMMERCE_TARGETS = (
    "order",
    "invoice",
    "refund",
    "coupon",
    "plan",
    "price",
    "product",
    "subscription",
    "reconciliation_run",
    "gst_export",
    "payment",
    "payment_webhook",
    "credit_note",
)
_FAMILIES = {
    "security": (SECURITY_PREFIXES, SECURITY_TARGETS),
    "commerce": (COMMERCE_PREFIXES, COMMERCE_TARGETS),
}
# role key -> event family it may read; empty since D2 (only Admin reads the audit log).
_ROLE_FAMILIES: dict[str, str] = {}
FULL_IP_ROLES = tuple(sorted(admin_roles()))


def _families(principal: Principal) -> set[str] | None:
    """``None`` = unrestricted (super_admin); otherwise the event families the caller may read."""
    if any(principal.has_role(r_, "platform") for r_ in admin_roles()):
        return None
    return {fam for role, fam in _ROLE_FAMILIES.items() if principal.has_role(role, "platform")}


def _family_filter(families: set[str]) -> ColumnElement[bool]:
    conds: list[ColumnElement[bool]] = []
    for fam in sorted(families):
        prefixes, targets = _FAMILIES[fam]
        conds.append(AuditLog.target_type.in_(targets))
        conds.extend(AuditLog.action.startswith(p, autoescape=True) for p in prefixes)
        approval_type = AuditLog.after_state["action_type"].astext
        conds.extend(
            (AuditLog.target_type == "approval_request") & approval_type.startswith(p, autoescape=True)
            for p in prefixes
        )
    return or_(*conds) if conds else false()


def _family_match(families: set[str]) -> Any:
    """``_family_filter`` as a Python predicate over an audit row (Firestore store)."""

    def keep(row: Any) -> bool:
        for fam in sorted(families):
            prefixes, targets = _FAMILIES[fam]
            if row.target_type in targets or any(row.action.startswith(p) for p in prefixes):
                return True
            st = row.after_state
            approval_type = st.get("action_type") if isinstance(st, dict) else None
            if (
                row.target_type == "approval_request"
                and isinstance(approval_type, str)
                and any(approval_type.startswith(p) for p in prefixes)
            ):
                return True
        return False

    return keep


def _utc(dt: datetime) -> datetime:
    # Postgres reads a zone-less timestamp in the session zone (UTC).
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


def _mask_ip(ip: str | None) -> str | None:
    if ip is None:
        return None
    import ipaddress

    addr = ipaddress.ip_address(ip.split("/")[0])
    prefix = 24 if addr.version == 4 else 48
    return str(ipaddress.ip_network(f"{addr}/{prefix}", strict=False))


@router.get("/events", response_model=AuditEventList, openapi_extra={"x-td-idle": "extends"})
async def list_events(
    request: Request,
    session: PrincipalDbSession,
    principal: AuditReader,
    action: str | None = None,
    actor_user_id: uuid.UUID | None = None,
    subject_user_id: uuid.UUID | None = None,
    target_type: str | None = None,
    target_id: uuid.UUID | None = None,
    organization_id: uuid.UUID | None = None,
    reason_code: str | None = None,
    from_: Annotated[datetime | None, Query(alias="from")] = None,
    to: datetime | None = None,
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = DEFAULT_LIMIT,
) -> AuditEventList:
    if from_ and to and to < from_:
        raise ProblemError(
            "validation_failed", 422, errors=[{"field": "to", "code": "before_from", "message": "to < from"}]
        )
    families = _families(principal)
    if uses_firestore("audit"):
        fs_rows, fs_more = await _list_events_fs(
            principal,
            families,
            {
                "action": action,
                "actor_user_id": actor_user_id,
                "subject_user_id": subject_user_id,
                "target_type": target_type,
                "target_id": target_id,
                "organization_id": organization_id,
                "reason_code": reason_code,
            },
            from_,
            to,
            cursor,
            limit,
        )
        await audit(
            session,
            principal,
            "audit.query",
            "audit_log",
            after={k: str(v) for k, v in request.query_params.items() if k != "cursor"},
        )
        return AuditEventList(
            data=[AuditEventOut.from_row(r) for r in fs_rows],
            page=PageMeta(**page_meta({"seq": fs_rows[-1].seq} if fs_more and fs_rows else None, limit)),
        )
    q = select(AuditLog)
    if families is not None:
        q = q.where(_family_filter(families))
    for col, val in (
        (AuditLog.action, action),
        (AuditLog.actor_user_id, actor_user_id),
        (AuditLog.subject_user_id, subject_user_id),
        (AuditLog.target_type, target_type),
        (AuditLog.target_id, target_id),
        (AuditLog.organization_id, organization_id),
        (AuditLog.reason_code, reason_code),
    ):
        if val is not None:
            q = q.where(col == val)
    if from_:
        q = q.where(AuditLog.occurred_at >= from_)
    if to:
        q = q.where(AuditLog.occurred_at < to)
    if cursor:
        pos = decode_cursor(cursor)
        try:
            q = q.where(AuditLog.seq < int(pos["seq"]))
        except (KeyError, TypeError, ValueError) as e:
            raise ProblemError("invalid_cursor") from e
    rows = (await session.execute(q.order_by(AuditLog.seq.desc()).limit(limit + 1))).scalars().all()
    more = len(rows) > limit
    rows = rows[:limit]
    await audit(
        session,
        principal,
        "audit.query",
        "audit_log",
        after={k: str(v) for k, v in request.query_params.items() if k != "cursor"},
    )
    return AuditEventList(
        data=[AuditEventOut.from_row(r) for r in rows],
        page=PageMeta(**page_meta({"seq": rows[-1].seq} if more and rows else None, limit)),
    )


@router.get("/events/{seq}", response_model=AuditEventDetailOut, openapi_extra={"x-td-idle": "extends"})
async def get_event(seq: int, session: PrincipalDbSession, principal: AuditReader) -> AuditEventDetailOut:
    families = _families(principal)
    row: Any
    if uses_firestore("audit"):
        from app.modules.audit.repo_firestore import reader_repo

        row = await reader_repo(principal).get_event(seq)
        if row is not None and families is not None and not _family_match(families)(row):
            row = None
    else:
        q = select(AuditLog).where(AuditLog.seq == seq)
        if families is not None:
            q = q.where(_family_filter(families))
        row = (await session.execute(q)).scalar_one_or_none()
    if row is None:
        raise ProblemError("not_found")
    await audit(session, principal, "audit.query", "audit_log", after={"seq": seq})
    out = AuditEventDetailOut.from_row(row)
    if not any(principal.has_role(r_, "platform") for r_ in FULL_IP_ROLES):
        out.ip = _mask_ip(out.ip)
    return out


@router.get("/chain-status", response_model=ChainStatusOut, openapi_extra={"x-td-idle": "neutral"})
async def chain_status(session: PrincipalDbSession, principal: AuditReader) -> ChainStatusOut:
    if uses_firestore("audit"):
        from app.modules.audit.repo_firestore import chain_repo

        result = await chain_repo().verify_chain_cached()
    else:
        result = await verify_chain(session)
    return ChainStatusOut(
        verified=result.ok,
        checked_rows=result.checked,
        last_seq=result.last_seq,
        last_row_hash=result.last_hash.hex() if result.last_hash else None,
        first_bad_seq=result.first_bad_seq,
        reason=result.reason,
    )


async def _list_events_fs(
    principal: Principal,
    families: set[str] | None,
    equals: dict[str, Any],
    from_: datetime | None,
    to: datetime | None,
    cursor: str | None,
    limit: int,
) -> tuple[list[Any], bool]:
    """Firestore twin of the ``list_events`` query (same rows, same order, same cursor)."""
    from app.modules.audit.repo_firestore import reader_repo

    before_seq: int | None = None
    if cursor:
        pos = decode_cursor(cursor)
        try:
            before_seq = int(pos["seq"])
        except (KeyError, TypeError, ValueError) as e:
            raise ProblemError("invalid_cursor") from e
    fam = _family_match(families) if families is not None else None
    lo = _utc(from_) if from_ else None
    hi = _utc(to) if to else None

    def keep(row: Any) -> bool:
        if lo is not None and row.occurred_at < lo:
            return False
        if hi is not None and row.occurred_at >= hi:
            return False
        return fam is None or fam(row)

    if families is not None and not families:
        return [], False  # ``false()``: a reader with no family sees nothing
    return await reader_repo(principal).list_events(
        equals=equals, before_seq=before_seq, limit=limit, keep=keep if (lo or hi or fam) else None
    )
