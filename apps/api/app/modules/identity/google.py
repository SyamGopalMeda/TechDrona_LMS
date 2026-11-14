"""Google sign-in through Firebase Auth (docs/firebase/MIGRATION-PLAN.md §5.1, P1).

The browser signs in with Google using the Firebase JS SDK, sends the resulting Firebase **ID
token** to ``POST /auth/login/google`` and signs out of Firebase immediately. This module only
*verifies* that token; the LMS session, device binding, risk gates, consents and audit stay in
the existing identity/sessions pipeline (``router.login_google``).

Verification follows Firebase's documented rules for third-party JWT libraries:

* header ``alg`` = ``RS256`` and ``kid`` is one of Google's current ``securetoken`` signing
  certificates (fetched over HTTPS, cached for the response's ``Cache-Control: max-age``);
* signature valid; ``exp`` in the future and ``iat`` not in the future (small leeway);
* ``aud`` = the Firebase project id, ``iss`` = ``https://securetoken.google.com/<project id>``;
* ``sub`` (the Firebase uid) non-empty and at most 128 characters; ``auth_time`` not in the
  future and no older than the caller's freshness window;
* ``firebase.sign_in_provider`` = ``google.com``, ``email`` present and ``email_verified`` is
  ``true``.

No service-account credential is needed for this (only the public certificates), so token
revocation (``check_revoked``) is not checked; the token is single-use instead
(:func:`claim_token_once`) and the LMS session has its own lifecycle.

Tests install a fake verifier with :func:`set_verifier` and never call Google.
"""

from __future__ import annotations

import hashlib
import re
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

import jwt
import structlog
from cryptography import x509
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core import ratelimit as rl
from app.core.config import ENV_FILES
from app.core.errors import ProblemError

log = structlog.get_logger("app.identity.google")

CERTS_URL = "https://www.googleapis.com/robot/v1/metadata/x509/securetoken@system.gserviceaccount.com"
ISSUER_PREFIX = "https://securetoken.google.com/"
LEEWAY_SECONDS = 60
DEFAULT_CERT_MAX_AGE = 3600
# One-time use of an ID token (replay stop). Firebase ID tokens live for one hour.
REPLAY_TTL_SECONDS = 3600
PRODUCTION_ENVS = frozenset({"prod", "production"})


class GoogleSignInSettings(BaseSettings):
    """Read from the same env files as ``app.core.config.Settings`` (kept separate so this
    feature does not touch the shared settings class)."""

    model_config = SettingsConfigDict(env_file=ENV_FILES, env_file_encoding="utf-8", extra="ignore")

    # The project whose Auth issues the tokens (``aud``). First non-empty of: an explicit
    # override, the web app's public config, the backend's Firebase project. ``demo-*`` ids
    # (Firestore emulator) are refused: emulator tokens are unsigned.
    TD_GOOGLE_SIGNIN_PROJECT_ID: str = ""
    NEXT_PUBLIC_FIREBASE_PROJECT_ID: str = ""
    FIREBASE_PROJECT_ID: str = ""
    # Kill switch: false makes POST /auth/login/google answer 503 google_signin_unavailable.
    TD_GOOGLE_SIGNIN_ENABLED: bool = True
    # Firebase Auth emulator (dev/test only): its ID tokens are unsigned (``alg: none``) and are
    # accepted ONLY when this is set and APP_ENV is not production (``emulator_mode``). Then
    # ``demo-*`` project ids are allowed (the emulator's project).
    FIREBASE_AUTH_EMULATOR_HOST: str = ""
    APP_ENV: str = "local"

    def emulator_mode(self) -> bool:
        if not self.FIREBASE_AUTH_EMULATOR_HOST.strip():
            return False
        if self.APP_ENV in PRODUCTION_ENVS:
            log.error("google_auth_emulator_refused_in_production")
            return False
        return True

    def project_id(self) -> str:
        for v in (
            self.TD_GOOGLE_SIGNIN_PROJECT_ID,
            self.NEXT_PUBLIC_FIREBASE_PROJECT_ID,
            self.FIREBASE_PROJECT_ID,
        ):
            if v.strip():
                pid = v.strip()
                return "" if pid.startswith("demo-") and not self.emulator_mode() else pid
        return ""


class TokenRejected(Exception):
    """The ID token is not acceptable. ``reason`` is logged, never returned to the client."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class GoogleIdentity:
    uid: str
    email: str
    name: str | None
    auth_time: datetime


class Verifier(Protocol):
    async def verify(self, token: str) -> dict[str, Any]:
        """Return the token's claims after signature/aud/iss/exp checks or raise TokenRejected."""
        ...


CertFetcher = Callable[[], Awaitable[tuple[dict[str, str], int]]]


async def fetch_google_certs() -> tuple[dict[str, str], int]:
    """Google's current ``kid -> PEM certificate`` map and its cache lifetime in seconds."""
    import httpx

    async with httpx.AsyncClient(timeout=5.0) as client:
        resp = await client.get(CERTS_URL)
    resp.raise_for_status()
    certs = resp.json()
    if not isinstance(certs, dict):
        raise TokenRejected("certs_malformed")
    m = re.search(r"max-age=(\d+)", resp.headers.get("cache-control", ""))
    return {str(k): str(v) for k, v in certs.items()}, int(m.group(1)) if m else DEFAULT_CERT_MAX_AGE


class FirebaseTokenVerifier:
    def __init__(self, project_id: str, *, fetch_certs: CertFetcher = fetch_google_certs) -> None:
        if not project_id:
            raise ValueError("project_id is required")
        self.project_id = project_id
        self._fetch = fetch_certs
        self._certs: dict[str, str] = {}
        self._expires = 0.0

    async def _certificates(self, *, force: bool = False) -> dict[str, str]:
        if force or not self._certs or time.monotonic() >= self._expires:
            try:
                certs, max_age = await self._fetch()
            except TokenRejected:
                raise
            except Exception as e:  # network / JSON: the token cannot be checked
                log.warning("google_certs_fetch_failed", error=type(e).__name__)
                raise TokenRejected("certs_unavailable") from e
            self._certs, self._expires = certs, time.monotonic() + max(60, min(max_age, 86_400))
        return self._certs

    async def verify(self, token: str) -> dict[str, Any]:
        try:
            header = jwt.get_unverified_header(token)
        except jwt.PyJWTError as e:
            raise TokenRejected("malformed") from e
        if header.get("alg") != "RS256":
            raise TokenRejected("bad_alg")
        kid = header.get("kid")
        if not isinstance(kid, str) or not kid:
            raise TokenRejected("no_kid")
        certs = await self._certificates()
        if kid not in certs:  # Google rotates keys: refresh once before rejecting
            certs = await self._certificates(force=True)
        pem = certs.get(kid)
        if pem is None:
            raise TokenRejected("unknown_kid")
        try:
            key = x509.load_pem_x509_certificate(pem.encode()).public_key()
            claims: dict[str, Any] = jwt.decode(
                token,
                key,  # type: ignore[arg-type]
                algorithms=["RS256"],
                audience=self.project_id,
                issuer=ISSUER_PREFIX + self.project_id,
                leeway=LEEWAY_SECONDS,
                options={"require": ["exp", "iat", "aud", "iss", "sub", "auth_time"]},
            )
        except jwt.ExpiredSignatureError as e:
            raise TokenRejected("expired") from e
        except (jwt.PyJWTError, ValueError) as e:
            raise TokenRejected(type(e).__name__) from e
        iat = claims.get("iat")
        if not isinstance(iat, int | float) or iat > time.time() + LEEWAY_SECONDS:
            raise TokenRejected("iat_in_future")
        return claims


class EmulatorTokenVerifier:
    """Accepts the Firebase **Auth emulator's** unsigned ID tokens (``alg: none``), with the same
    aud / iss / exp / iat / required-claim checks as ``FirebaseTokenVerifier``. Only built by
    ``get_verifier`` in emulator mode, which is refused in production; the constructor refuses
    production too (defence in depth)."""

    def __init__(self, project_id: str) -> None:
        from app.core.config import get_settings

        if get_settings().APP_ENV in PRODUCTION_ENVS:
            raise RuntimeError("the Auth emulator token verifier is never used in production")
        if not project_id:
            raise ValueError("project_id is required")
        self.project_id = project_id

    async def verify(self, token: str) -> dict[str, Any]:
        try:
            header = jwt.get_unverified_header(token)
        except jwt.PyJWTError as e:
            raise TokenRejected("malformed") from e
        if header.get("alg") != "none":
            raise TokenRejected("bad_alg")
        try:
            claims: dict[str, Any] = jwt.decode(
                token,
                options={
                    "verify_signature": False,
                    "verify_exp": True,
                    "verify_aud": True,
                    "verify_iss": True,
                    "require": ["exp", "iat", "aud", "iss", "sub", "auth_time"],
                },
                audience=self.project_id,
                issuer=ISSUER_PREFIX + self.project_id,
                leeway=LEEWAY_SECONDS,
            )
        except jwt.ExpiredSignatureError as e:
            raise TokenRejected("expired") from e
        except (jwt.PyJWTError, ValueError) as e:
            raise TokenRejected(type(e).__name__) from e
        iat = claims.get("iat")
        if not isinstance(iat, int | float) or iat > time.time() + LEEWAY_SECONDS:
            raise TokenRejected("iat_in_future")
        return claims


def identity_from_claims(
    claims: dict[str, Any], *, project_id: str, now: datetime, max_auth_age: timedelta
) -> GoogleIdentity:
    """Semantic checks that apply whatever verified the signature (also under test fakes)."""
    if claims.get("aud") != project_id or claims.get("iss") != ISSUER_PREFIX + project_id:
        raise TokenRejected("aud_iss")
    sub = claims.get("sub")
    if not isinstance(sub, str) or not 0 < len(sub) <= 128:
        raise TokenRejected("sub")
    fb = claims.get("firebase")
    if not isinstance(fb, dict) or fb.get("sign_in_provider") != "google.com":
        raise TokenRejected("provider")
    email = claims.get("email")
    if not isinstance(email, str) or not email:
        raise TokenRejected("no_email")
    if claims.get("email_verified") is not True:
        raise TokenRejected("email_unverified")
    at = claims.get("auth_time")
    if not isinstance(at, int | float):
        raise TokenRejected("auth_time")
    auth_time = datetime.fromtimestamp(at, tz=UTC)
    if auth_time > now + timedelta(seconds=LEEWAY_SECONDS):
        raise TokenRejected("auth_time_future")
    if now - auth_time > max_auth_age:
        raise TokenRejected("auth_time_stale")
    name = claims.get("name")
    return GoogleIdentity(
        uid=sub,
        email=email,
        name=(name.strip()[:200] or None) if isinstance(name, str) else None,
        auth_time=auth_time,
    )


async def claim_token_once(token: str) -> bool:
    """True the first time this exact token is presented (SHA-256 kept for its lifetime).

    Fails **closed**: if the counter store is down the sign-in is refused (503), because a
    replayed token would otherwise be a full login."""
    key = "auth_google_idt:" + hashlib.sha256(token.encode()).hexdigest()
    try:
        (count,) = await rl.get_backend().incr([(key, REPLAY_TTL_SECONDS)])
    except Exception as e:
        log.warning("google_replay_store_unavailable", error=type(e).__name__)
        raise ProblemError(
            "service_unavailable", detail="Google sign-in is unavailable right now. Try again shortly."
        ) from e
    return int(count) == 1


# --------------------------------------------------------------------------- configuration

_verifier: Verifier | None = None
_verifier_project: str | None = None
_override = False


def settings() -> GoogleSignInSettings:
    return GoogleSignInSettings()


def set_verifier(v: Verifier | None, project_id: str | None = None) -> None:
    """Tests: install a fake (``None`` restores the env-configured verifier)."""
    global _verifier, _verifier_project, _override
    _verifier, _verifier_project, _override = v, project_id, v is not None


def get_verifier() -> tuple[Verifier, str] | None:
    """``(verifier, project_id)`` or ``None`` when Google sign-in is off or not configured."""
    global _verifier, _verifier_project
    if _override and _verifier is not None and _verifier_project:
        return _verifier, _verifier_project
    cfg = settings()
    pid = cfg.project_id()
    if not cfg.TD_GOOGLE_SIGNIN_ENABLED or not pid:
        return None
    want: type = EmulatorTokenVerifier if cfg.emulator_mode() else FirebaseTokenVerifier
    if _verifier is None or _verifier_project != pid or type(_verifier) is not want:
        _verifier, _verifier_project = want(pid), pid
    return _verifier, pid
