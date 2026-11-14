"""Bridge to the company website (web_* collections) for the central login and module switcher.

billing-f4fe3 has one Firestore database shared by three modules (lms_*, web_*, col_*; see
collections.LMS_PREFIX). ScopedStore can only reach lms_*. The central login needs exactly two
things from the website side, and this module is the only code allowed to do them:

* read ONE ``web_team/{email}`` entry: the website Admin Panel's own role model (owner, staff,
  trainer, mentor; firestore.rules in the website repo). It decides whether the signed-in LMS user
  may open the website admin and with which role. Read-only, never listed.
* mint a Firebase custom token for that email, so the website admin signs in without a second
  password (single sign-on). The website's rules then apply as usual: they check the verified
  email and the web_team entry, exactly as for a password sign-in.

Real project only: the emulator has no service-account key to sign custom tokens with.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from app.core.firestore import client as client_mod
from app.core.firestore.errors import FirestoreUnavailableError

WEB_TEAM = "web_team"
WEBSITE_ROLES = frozenset({"owner", "staff", "trainer", "mentor"})
SSO_CLAIM = "td_sso"


@dataclass(frozen=True, slots=True)
class WebsiteMember:
    email: str
    name: str
    role: str
    active: bool


def _doc_id(email: str) -> str | None:
    e = (email or "").strip().lower()
    # the website keys team entries by the lower-cased email; anything path-like is never a member
    if not e or "/" in e or "@" not in e or len(e) > 254:
        return None
    return e


async def website_member(email: str) -> WebsiteMember | None:
    """The active website team entry for this email, or None."""
    doc_id = _doc_id(email)
    if doc_id is None:
        return None
    snap = await client_mod.get_client().collection(WEB_TEAM).document(doc_id).get()
    if not snap.exists:
        return None
    d = snap.to_dict() or {}
    role = str(d.get("role") or "")
    if role not in WEBSITE_ROLES or d.get("active") is not True:
        return None
    return WebsiteMember(email=doc_id, name=str(d.get("name") or ""), role=role, active=True)


def _mint(email: str, display_name: str) -> str:
    from firebase_admin import auth

    app = client_mod.admin_app()
    try:
        user = auth.get_user_by_email(email, app=app)
    except auth.UserNotFoundError:
        user = auth.create_user(email=email, email_verified=True, display_name=display_name or None, app=app)
    if user.disabled:
        raise PermissionError("the website sign-in account for this email is disabled")
    if not user.email_verified:
        # The caller has checked that the LMS has verified this email; the website rules need the flag.
        auth.update_user(user.uid, email_verified=True, app=app)
    token = auth.create_custom_token(user.uid, {SSO_CLAIM: "lms"}, app=app)
    return token.decode() if isinstance(token, bytes) else str(token)


async def mint_website_token(email: str, display_name: str = "") -> str:
    """Custom token for the website's Firebase Auth user with this (LMS-verified) email."""
    doc_id = _doc_id(email)
    if doc_id is None:
        raise ValueError("not a usable email")
    if client_mod.get_settings().FIRESTORE_EMULATOR_HOST.strip():
        raise FirestoreUnavailableError("website single sign-on needs the real Firebase project")
    return await asyncio.to_thread(_mint, doc_id, display_name)
