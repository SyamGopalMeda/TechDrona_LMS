"""Google sign-in (AUTH-29) over HTTP on Firestore with no Postgres, with ID tokens minted by the
**Firebase Auth emulator** (127.0.0.1:19099; ``FIREBASE_AUTH_EMULATOR_HOST``). The emulator's
tokens are unsigned, so ``google.EmulatorTokenVerifier`` checks them; that path is refused in
production (tested below)."""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from datetime import date
from typing import Any

import httpx
import pytest

from app.modules.identity import google
from tests.identity.fs.conftest import fs_user

AUTH_HOST = os.environ.get("TD_TEST_AUTH_EMULATOR_HOST", "127.0.0.1:19099")
# The Auth emulator is shared and keeps accounts between runs: unique addresses per run.
RUN = uuid.uuid4().hex[:8]


def addr(name: str) -> str:
    return f"{name}-{RUN}@x.in"


def _auth_up() -> bool:
    try:
        return httpx.get(f"http://{AUTH_HOST}/", timeout=1.0).status_code == 200
    except httpx.HTTPError:
        return False


pytestmark = pytest.mark.skipif(not _auth_up(), reason="Firebase Auth emulator not running")


def mint(email: str, *, name: str = "G User", verified: bool = True) -> tuple[str, str]:
    """A Google-provider Firebase ID token from the Auth emulator: ``(token, project_id)``."""
    claims = {
        "sub": "g-" + uuid.uuid5(uuid.NAMESPACE_DNS, email).hex,
        "email": email,
        "email_verified": verified,
        "name": name,
    }
    r = httpx.post(
        f"http://{AUTH_HOST}/identitytoolkit.googleapis.com/v1/accounts:signInWithIdp?key=fake-api-key",
        json={
            "postBody": "id_token=" + json.dumps(claims) + "&providerId=google.com",
            "requestUri": "http://localhost",
            "returnIdpCredential": True,
            "returnSecureToken": True,
        },
        timeout=10.0,
    )
    assert r.status_code == 200 and "idToken" in r.json(), r.text
    token = r.json()["idToken"]
    import jwt

    return token, jwt.decode(token, options={"verify_signature": False})["aud"]


@pytest.fixture
def emulator_google(http: Any, monkeypatch: pytest.MonkeyPatch) -> Any:
    _tok, project = mint(addr("probe"))
    monkeypatch.setenv("FIREBASE_AUTH_EMULATOR_HOST", AUTH_HOST)
    monkeypatch.setenv("TD_GOOGLE_SIGNIN_PROJECT_ID", project)
    monkeypatch.setenv("TD_GOOGLE_SIGNIN_ENABLED", "true")
    google.set_verifier(None)
    yield http
    google.set_verifier(None)


async def test_google_login_existing_student(emulator_google: Any) -> None:
    http = emulator_google
    u = await fs_user(addr("gstudent"))
    token, _ = mint(u.email)
    r = await http.post("/auth/login/google", {"id_token": token})
    assert r.status_code == 200, r.text
    assert r.json()["result"] == "authenticated", r.text
    me = await http.get("/me")
    assert me.status_code == 200 and me.json()["user"]["email"] == u.email, me.text
    # the same token cannot be replayed
    r = await http.fork().post("/auth/login/google", {"id_token": token})
    assert r.status_code == 401, r.text
    # an unverified Google email is refused
    bad, _ = mint(addr("other"), verified=False)
    r = await http.fork().post("/auth/login/google", {"id_token": bad})
    assert r.status_code == 401, r.text


async def test_google_signup_new_student(emulator_google: Any) -> None:
    http = emulator_google
    token, _ = mint(addr("gnew"), name="New Learner")
    r = await http.post("/auth/login/google", {"id_token": token})
    assert r.status_code == 409 and r.json()["code"] == "google_signup_required", r.text
    assert r.json()["suggested_name"] == "New Learner"
    await asyncio.sleep(1.1)  # a new iat: an identical token would be refused as a replay
    fresh, _ = mint(addr("gnew"), name="New Learner")
    consents = [
        {"purpose": p, "notice_version": r.json()["notice_version"], "granted": True}
        for p in r.json()["required_consents"]
    ]
    r = await http.post(
        "/auth/login/google",
        {
            "id_token": fresh,
            "signup": {
                "full_name": "New Learner",
                "date_of_birth": str(date(2000, 1, 1)),
                "consents": consents,
            },
        },
    )
    assert r.status_code in (200, 201), r.text
    from app.modules.identity import public as ipub

    u = await ipub.find_user(None, "email", addr("gnew"))  # type: ignore[arg-type]
    assert u is not None and u.email_verified_at is not None
    assert (await ipub.get_profile(None, u.id)).full_name == "New Learner"  # type: ignore[arg-type, union-attr]


async def test_signed_token_path_rejects_emulator_tokens(http: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """Without the emulator setting, an unsigned emulator token is refused (bad_alg)."""
    token, project = mint(addr("x"))
    monkeypatch.delenv("FIREBASE_AUTH_EMULATOR_HOST", raising=False)
    v = google.FirebaseTokenVerifier(project.replace("demo-", "real-"))
    with pytest.raises(google.TokenRejected) as e:
        await v.verify(token)
    assert e.value.reason == "bad_alg"


def test_emulator_path_refused_in_production(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.config import reset_settings_cache

    monkeypatch.setenv("FIREBASE_AUTH_EMULATOR_HOST", AUTH_HOST)
    monkeypatch.setenv("TD_GOOGLE_SIGNIN_PROJECT_ID", "demo-techdrona-lms")
    monkeypatch.setenv("APP_ENV", "production")
    cfg = google.GoogleSignInSettings()
    assert not cfg.emulator_mode()
    assert cfg.project_id() == ""  # demo project refused -> Google sign-in unavailable
    reset_settings_cache()
    try:
        with pytest.raises(RuntimeError):
            google.EmulatorTokenVerifier("demo-techdrona-lms")
    finally:
        monkeypatch.undo()
        reset_settings_cache()
