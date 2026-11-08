"""DPDP data-principal rights requests (privacy-and-data-retention §5; API §23 PRV-*) — basic flow.

Request lifecycle: ``received`` → (``identity_verification``) → ``in_progress`` → ``completed`` /
``rejected``; erasure starts in ``cooling_off`` (14 days, withdrawable). Completion of an
``access_export`` stores a JSON export of the principal's own records.

Erasure (DB-01; privacy §5 and §7 ``account_erasure``): revoke all sessions
(``account_deleted``), deactivate the account, then call every registered module erasure
provider (``register_erasure_provider``; the ``privacy_provider.delete()`` of privacy §7). Each
run appends an ``erasure_ledger`` row (``subject_hash``, never the user id) so backup restores can
re-apply deletions. The request is only marked ``completed`` once every module listed in
``REQUIRED_ERASURE_MODULES`` has a provider and it ran; otherwise it stays ``in_progress`` with
the missing modules named in ``response_summary``, and completing it again re-runs the
(idempotent) providers.
"""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ids import uuid7
from app.core.time import to_rfc3339
from app.modules.admin.models import ErasureLedger, PrivacyRequest
from app.modules.identity import clock

REQUEST_TYPES = (
    "access_export",
    "correction",
    "erasure",
    "grievance",
    "nomination",
    "consent_withdrawal_help",
)
OPEN_STATES = ("received", "identity_verification", "in_progress", "awaiting_requester", "cooling_off")
COOLING_OFF = timedelta(days=14)
DUE = {"grievance": timedelta(days=30), "access_export": timedelta(days=30)}
DEFAULT_DUE = timedelta(days=90)
RETAINED_BY_LAW = ["invoices (72 months)", "security logs (>= 1 year)", "audit log (3 years)"]


def new_ref() -> str:
    from app.modules.security.refs import make_ref

    return make_ref("PRV")


def request_out(r: PrivacyRequest, *, staff: bool = False) -> dict[str, Any]:
    out: dict[str, Any] = {
        "request_id": str(r.id),
        "request_ref": r.request_ref,
        "request_type": r.request_type,
        "status": r.status,
        "received_at": to_rfc3339(r.received_at),
        "due_at": to_rfc3339(r.due_at),
        "cooling_off_until": to_rfc3339(r.cooling_off_until) if r.cooling_off_until else None,
        "completed_at": to_rfc3339(r.completed_at) if r.completed_at else None,
        "response_summary": r.response_summary,
        "export_available": r.export_payload is not None,
    }
    if r.request_type == "erasure":
        out["retained_by_law"] = RETAINED_BY_LAW
    if staff:
        out.update(
            {
                "user_id": str(r.user_id) if r.user_id else None,
                "requester_relationship": r.requester_relationship,
                "details": r.details,
                "identity_verification_method": r.identity_verification_method,
                "identity_verified_at": to_rfc3339(r.identity_verified_at)
                if r.identity_verified_at
                else None,
                "overdue": r.status in OPEN_STATES and r.due_at <= clock.now(),
            }
        )
    return out


async def create(
    session: AsyncSession, user_id: uuid.UUID, request_type: str, details: str | None, idem: str | None
) -> PrivacyRequest:
    now = clock.now()
    r = PrivacyRequest(
        id=uuid7(),
        request_ref=new_ref(),
        user_id=user_id,
        requested_by=user_id,
        requester_relationship="self",
        request_type=request_type,
        status="cooling_off" if request_type == "erasure" else "in_progress",
        details=details,
        identity_verification_method="session",
        identity_verified_at=now,
        received_at=now,
        due_at=now + DUE.get(request_type, DEFAULT_DUE),
        cooling_off_until=now + COOLING_OFF if request_type == "erasure" else None,
        idempotency_key=idem,
    )
    session.add(r)
    await session.flush()
    return r


async def build_export(session: AsyncSession, user_id: uuid.UUID) -> dict[str, Any]:
    """The principal's own records (identity, consents, sessions, devices, security status)."""
    from app.modules.identity.models import Consent, User, UserProfile
    from app.modules.security.models import AccountRestriction, UnblockRequest
    from app.modules.sessions.models import AuthSession, UserDevice

    user = await session.get(User, user_id)
    profile = await session.get(UserProfile, user_id)
    consents = (await session.execute(select(Consent).where(Consent.user_id == user_id))).scalars().all()
    sessions = (
        (await session.execute(select(AuthSession).where(AuthSession.user_id == user_id).limit(500)))
        .scalars()
        .all()
    )
    devices = (await session.execute(select(UserDevice).where(UserDevice.user_id == user_id))).scalars().all()
    restr = (
        (await session.execute(select(AccountRestriction).where(AccountRestriction.user_id == user_id)))
        .scalars()
        .all()
    )
    unb = (
        (await session.execute(select(UnblockRequest).where(UnblockRequest.user_id == user_id)))
        .scalars()
        .all()
    )
    return {
        "generated_at": to_rfc3339(clock.now()),
        "account": {
            "user_id": str(user_id),
            "email": user.email if user else None,
            "phone": user.phone_e164 if user else None,
            "status": user.status if user else None,
            "full_name": profile.full_name if profile else None,
        },
        "consents": [
            {
                "purpose": c.purpose,
                "action": c.action,
                "notice_version": c.notice_version,
                "at": to_rfc3339(c.created_at),
            }
            for c in consents
        ],
        "sessions": [
            {
                "created_at": to_rfc3339(s.created_at),
                "status": s.status,
                "end_reason": s.end_reason,
                "device": f"{s.ua_family} on {s.os_family}",
            }
            for s in sessions
        ],
        "devices": [{"user_device_id": str(d.id), "trust_status": d.trust_status} for d in devices],
        "restrictions": [
            {
                "level": r.level,
                "family": r.family,
                "starts_at": to_rfc3339(r.starts_at),
                "ended_at": to_rfc3339(r.ended_at) if r.ended_at else None,
            }
            for r in restr
        ],
        "unblock_requests": [{"reference": u.reference, "state": u.state} for u in unb],
    }


ErasureProvider = Callable[[AsyncSession, uuid.UUID], Awaitable[dict[str, Any]]]
_ERASURE_PROVIDERS: dict[str, ErasureProvider] = {}
# Modules holding personal data of a learner (privacy §3 D-categories). Erasure is complete only
# when each of these has run its provider.
REQUIRED_ERASURE_MODULES: tuple[str, ...] = (
    "identity",
    "analytics",
    "learning",
    "assessments",
    "coding",
    "placement",
    "support",
    "notifications",
    "mentoring",  # résumés and mentor notes are personal data (DB-01, learn R11)
    "media",  # user-owned objects in the uploads bucket (core request 7)
)


def register_erasure_provider(module: str, provider: ErasureProvider) -> None:
    """Called by a module at import time: ``provider(session, user_id)`` erases or anonymises that
    module's rows for ``user_id`` (keeping legal holds in minimal form) and returns a summary.
    It must be idempotent: an erasure may be re-run until every module has a provider."""
    _ERASURE_PROVIDERS[module] = provider


def erasure_providers() -> dict[str, ErasureProvider]:
    _builtin_providers()
    return dict(_ERASURE_PROVIDERS)


def _builtin_providers() -> None:
    """Providers that already exist as public module functions (registered lazily, so the admin
    module does not import them at start-up)."""
    if "analytics" not in _ERASURE_PROVIDERS:
        from app.modules.analytics.jobs import erase_user

        async def _analytics(session: AsyncSession, user_id: uuid.UUID) -> dict[str, Any]:
            return dict(await erase_user(session, user_id))

        _ERASURE_PROVIDERS["analytics"] = _analytics


def subject_hash(user_id: uuid.UUID) -> bytes:
    return hashlib.sha256(f"erasure:{user_id}".encode()).digest()


@dataclass
class ErasureResult:
    sessions_revoked: int
    ran: dict[str, Any] = field(default_factory=dict)
    missing: list[str] = field(default_factory=list)

    @property
    def complete(self) -> bool:
        return not self.missing


async def execute_erasure(
    session: AsyncSession, user_id: uuid.UUID, request_id: uuid.UUID | None = None
) -> ErasureResult:
    from app.modules.identity.models import User
    from app.modules.sessions import service as ss

    n = await ss.revoke_all_sessions(session, user_id, "account_deleted")
    await session.execute(update(User).where(User.id == user_id).values(status="deactivated"))
    result = ErasureResult(sessions_revoked=n)
    for module, provider in sorted(erasure_providers().items()):
        result.ran[module] = await provider(session, user_id)
    result.missing = [m for m in REQUIRED_ERASURE_MODULES if m not in result.ran]
    session.add(
        ErasureLedger(
            id=uuid7(),
            privacy_request_id=request_id,
            subject_hash=subject_hash(user_id),
            erased_at=clock.now(),
            scope={"modules": sorted(result.ran), "sessions_revoked": n},
            pending_modules=result.missing,
        )
    )
    await session.flush()
    return result
