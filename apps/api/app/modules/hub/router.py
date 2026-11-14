"""Central login hub (module launcher + module switcher).

One sign-in (the LMS login: password, MFA, device and session rules) opens three modules, each
with its own dashboard and its own role model:

* ``lms``      Tech Drona LMS. Roles: RBAC grants (student, trainer, evaluator, content manager,
               admin). Lands on the user's most privileged portal (sessions.login.PORTALS).
* ``colleges`` Colleges Management (/admin/college-data, proxied portal). Admin role only: the
               same rule the portal proxy enforces (apps/web/src/lib/college-portal/proxy.ts).
* ``website``  Company Website Admin Panel (TD_WEBSITE_URL/admin). Roles: the website's own team
               list (web_team: owner, staff, trainer, mentor). Opened with a Firebase custom token,
               so no second sign-in.

The list is a convenience for the UI; each module still authorises every request itself.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends

from app.core.audit import audit
from app.core.auth import require_active_principal, require_step_up
from app.core.config import get_settings
from app.core.db import PrincipalDbSession
from app.core.errors import ProblemError
from app.core.firestore.errors import FirestoreUnavailableError
from app.core.firestore.website import WebsiteMember, mint_website_token, website_member
from app.core.principal import Principal
from app.core.routing import authenticated_router, public_router
from app.modules.identity import public as identity_public
from app.modules.identity.public import User
from app.modules.sessions.login import LANDING_ORDER, PORTALS

log = logging.getLogger(__name__)

me_r = authenticated_router(prefix="/me", tags=["hub"], route_tag="account_status", idle="neutral")
sso_r = authenticated_router(prefix="/sso", tags=["hub"])

COLLEGES_HREF = "/college-portal/index.html"  # full-page portal (owner 2026-11-12), like the website admin
UNAVAILABLE = "Website sign-in is unavailable right now."
WEBSITE_SSO_HREF = "/sso/website"  # web BFF route: asks POST /sso/website, then hands the token over


def lms_landing(principal: Principal) -> str:
    held = set(principal.role_keys)
    for role in LANDING_ORDER:
        if role in held:
            return PORTALS[role]
    return PORTALS["student"]


def can_open_colleges(principal: Principal) -> bool:
    return principal.has_role("super_admin")


async def _user(session: Any, principal: Principal) -> User | None:
    # identity.public: works on both stores (TD_STORE_IDENTITY).
    return await identity_public.get_user(session, principal.user_id)


async def _website_access(user: User | None) -> tuple[WebsiteMember | None, str | None]:
    """(member, reason-if-not). Never raises: the launcher must load even if Firebase is down."""
    if not get_settings().TD_WEBSITE_URL.strip():
        return None, "not_configured"
    if user is None or not user.email:
        return None, "no_email"
    if user.email_verified_at is None:
        return None, "email_not_verified"
    try:
        member = await website_member(user.email)
    except FirestoreUnavailableError:
        return None, "unavailable"
    except Exception:  # network / permission problems: hide the module, keep the hub working
        log.warning("hub: website team lookup failed", exc_info=True)
        return None, "unavailable"
    return (member, None) if member else (None, "not_a_member")


@me_r.get("/modules")
async def my_modules(
    session: PrincipalDbSession, principal: Principal = Depends(require_active_principal)
) -> dict[str, Any]:
    """The modules this user may open (only those), in launcher order."""
    modules: list[dict[str, Any]] = [
        {
            "key": "lms",
            "title": "Tech Drona LMS",
            "description": "Courses, batches, learners, tests and certificates.",
            "href": lms_landing(principal),
            "external": False,
            "roles": list(principal.role_keys) or ["student"],
        }
    ]
    if can_open_colleges(principal):
        modules.append(
            {
                "key": "colleges",
                "title": "Colleges Management",
                "description": "Colleges, branches, contacts, outreach and follow-ups.",
                "href": COLLEGES_HREF,
                "external": True,  # not a Next page: a full page load into the portal
                "roles": ["editor"],
            }
        )
    member, reason = await _website_access(await _user(session, principal))
    if member is not None:
        modules.append(
            {
                "key": "website",
                "title": "Company Website Admin",
                "description": "Enquiries, registrations, visitors, email, members and site settings.",
                "href": WEBSITE_SSO_HREF,
                "external": True,
                "roles": [member.role],
            }
        )
    elif reason == "unavailable" and principal.has_role("super_admin"):
        # Single sign-on needs the Firebase service-account key; until it is installed (or if Firebase
        # is unreachable) an Admin still gets the module, opening the website admin's own sign-in page.
        modules.append(
            {
                "key": "website",
                "title": "Company Website Admin",
                "description": "Enquiries, registrations, visitors, email, members and site settings. "
                "Sign in there with your website admin email and password.",
                "href": get_settings().TD_WEBSITE_URL.strip().rstrip("/") + "/admin",
                "external": True,
                "roles": ["owner"],
            }
        )
    return {"modules": modules}


@sso_r.post("/website")
async def website_sso(
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
    _s: Principal = Depends(require_step_up("staff")),
) -> dict[str, Any]:
    """Single sign-on into the website admin: a one-hour Firebase custom token for the caller's
    verified email, issued only to an active web_team member. The website's own rules still decide
    what that role may do. The token opens another system's admin panel, so it needs a fresh
    step-up (staff window, S10) like other sensitive staff actions; the web page calls this from
    the browser, where the API client's step-up dialog answers the 401 and retries."""
    user = await _user(session, principal)
    member, reason = await _website_access(user)
    if member is None or user is None:
        if reason == "unavailable" or reason == "not_configured":
            raise ProblemError("service_unavailable", 503, detail=UNAVAILABLE)
        raise ProblemError(
            "permission_denied",
            detail="Your account is not on the company website's team. Ask the website owner to add you.",
            reason=reason,
        )
    try:
        token = await mint_website_token(member.email, member.name)
    except FirestoreUnavailableError:
        raise ProblemError("service_unavailable", 503, detail=UNAVAILABLE) from None
    except PermissionError:
        raise ProblemError("permission_denied", detail="Your website sign-in account is disabled.") from None
    await audit(session, principal, "hub.sso.website", "user", principal.user_id, after={"role": member.role})
    return {"token": token, "url": get_settings().TD_WEBSITE_URL.rstrip("/") + "/admin", "role": member.role}


pub_r = public_router(tags=["hub"])


def _safe(fn: Any) -> bool | None:
    try:
        return bool(fn())
    except Exception:  # a status check must never break the page that asks
        log.warning("hub: integration status check failed", exc_info=True)
        return None


def integration_status() -> dict[str, Any]:
    """Which outside services are really connected (owner rule 2026-11-12: anything not
    integrated must say so instead of pretending). No secrets, only booleans; safe to show publicly."""
    from app.modules.notifications.adapters import email_integrated, sms_integrated

    def _ai() -> bool:
        from app.modules.ai.public import ai_simulated

        return not ai_simulated()

    def _payments() -> bool:
        from app.modules.commerce.gateway import gateway_status

        return bool(gateway_status().get("integrated"))

    def _video() -> bool:
        from app.modules.media.providers import get_video_provider

        return not get_video_provider().is_fake

    def _website_sso() -> bool:
        return bool(get_settings().FIREBASE_SERVICE_ACCOUNT_FILE.strip())

    checks = {
        "email": email_integrated,
        "sms": sms_integrated,
        "payments": _payments,
        "ai": _ai,
        "code_judge": lambda: get_settings().JUDGE_PROVIDER.lower() != "fake",
        "video": _video,
        "website_sso": _website_sso,
    }
    return {k: _safe(v) for k, v in checks.items()}


@pub_r.get("/public/integrations", openapi_extra={"x-td-idle": "neutral"})
async def integrations() -> dict[str, Any]:
    # ``simple_auth``: TD_SIMPLE_AUTH is on (email + password only; MFA, device codes and step-up
    # are not used), so the web hides those screens. A mode flag, not a service: kept out of
    # ``integrations``.
    return {"integrations": integration_status(), "simple_auth": bool(get_settings().simple_auth)}


router = APIRouter()
router.include_router(me_r)
router.include_router(pub_r)
router.include_router(sso_r)
