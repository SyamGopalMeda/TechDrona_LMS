"""Authorization helpers and policy loading for the security module."""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import PLATFORM_SCOPE
from app.core.errors import ProblemError
from app.core.principal import Principal
from app.core.time import within
from app.modules.admin.policy import get_value
from app.modules.identity import clock
from app.modules.rbac import service as rs
from app.modules.security.catalogue import REASON_CODES
from app.modules.security.rules import SharingPolicy

P5 = 300
S10 = 600


def require_fresh_step_up(principal: Principal, seconds: int = P5) -> None:
    """Step-up freshness against the module clock (P5 / S10; api-spec §1.6)."""
    if within(principal.last_step_up_at, timedelta(seconds=seconds), now=clock.now()):
        return
    methods = ["totp"]  # SEC-11: no WebAuthn passkeys yet
    if principal.tier == "student":
        methods += ["sms_otp", "email_otp"]
    raise ProblemError(
        "step_up_required",
        detail="This action needs a fresh confirmation with your authenticator app.",
        step_up={
            "max_age_seconds": seconds,
            "allowed_methods": methods,
            "options_url": "/api/v1/auth/step-up/options",
        },
    )


def require_reason_code(reason_code: str | None) -> str:
    if not reason_code or reason_code not in REASON_CODES:
        raise ProblemError("reason_code_required", allowed_reason_codes=list(REASON_CODES))
    return reason_code


async def has_perm(session: AsyncSession, principal: Principal, perm: str) -> bool:
    return await rs.check_permission(session, principal, perm, PLATFORM_SCOPE)


async def need_perm(session: AsyncSession, principal: Principal, perm: str) -> None:
    if not await has_perm(session, principal, perm):
        raise ProblemError("permission_denied", permission=perm)


# A compressing reverse proxy (Caddy ``encode zstd gzip``) rewrites our strong ETag ``"v3"`` to
# ``"v3-zstd"`` / ``"v3-gzip"`` on compressed responses, and the browser echoes that value back
# in If-Match. The suffix only names the transfer coding of the same representation version.
_CODING_SUFFIXES = ("-zstd", "-gzip", "-br", "-deflate")


def _strip_coding(tag: str) -> str:
    t = tag.strip()
    if t.startswith("W/"):
        t = t[2:]
    t = t.strip('"')
    for suffix in _CODING_SUFFIXES:
        if t.endswith(suffix):
            return t[: -len(suffix)]
    return t


def check_if_match(request: Request, version: int, *, required: bool = True) -> None:
    raw = request.headers.get("if-match")
    if not raw:
        if required:
            raise ProblemError("precondition_required")
        return
    if _strip_coding(raw) != f"v{version}":
        raise ProblemError("version_conflict", current_etag=f'"v{version}"')


def etag(version: int) -> dict[str, str]:
    return {"ETag": f'"v{version}"'}


async def sharing_policy(session: AsyncSession, user_id: uuid.UUID | None = None) -> SharingPolicy:
    async def g(key: str) -> Any:
        return await get_value(session, key, user_id=user_id)

    return SharingPolicy(
        window_days=int(await g("risk.window_days")),
        half_life_days=float(await g("risk.decay_half_life_days")),
        network_cap=float(await g("risk.network_points_cap")),
        l1=float(await g("risk.threshold.L1")),
        l2=float(await g("risk.threshold.L2")),
        l3=float(await g("risk.threshold.L3")),
        l4_recommend=float(await g("risk.threshold.L4_recommend")),
        min_categories=int(await g("risk.L3.min_categories")),
        min_distinct_days=int(await g("risk.L3.min_distinct_days")),
        min_separated_days=int(await g("risk.L3.min_separated_days")),
        s0=float(await g("risk.separation.multiplier.S0")),
        s1=float(await g("risk.separation.multiplier.S1")),
        s2_verified=float(await g("risk.separation.multiplier.S2_verified")),
        s2_unverified=float(await g("risk.separation.multiplier.S2_unverified")),
        s3=float(await g("risk.separation.multiplier.S3")),
        owner_verification_days=int(await g("risk.owner_verification.max_age_days")),
    )
