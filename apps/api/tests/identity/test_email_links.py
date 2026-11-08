"""Email links point at real web routes (apps/web/src/app) and honour WEB_BASE_URL."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.modules.identity.links import WEB_ROUTES, web_base_url, web_link, web_path
from tests.identity.factory import GOOD_PASSWORD, REQUIRED_CONSENTS, make_user
from tests.identity.fixtures import last_link_token

WEB_APP = Path(__file__).resolve().parents[3] / "web" / "src" / "app"


def _web_route_patterns() -> set[str]:
    """Every page route as a normalised path: route groups dropped, ``[x]`` -> ``{}``."""
    out: set[str] = set()
    for page in WEB_APP.rglob("page.tsx"):
        parts = [
            p for p in page.parent.relative_to(WEB_APP).parts if not (p.startswith("(") and p.endswith(")"))
        ]
        out.add("/" + "/".join("{}" if p.startswith("[") else p for p in parts))
    return out


def _normalise(template: str) -> str:
    return re.sub(r"\{[^}]+\}", "{}", template)


@pytest.mark.skipif(not WEB_APP.is_dir(), reason="web app sources not present")
def test_every_email_link_template_is_a_web_page() -> None:
    routes = _web_route_patterns()
    missing = {name: t for name, t in WEB_ROUTES.items() if _normalise(t) not in routes}
    assert not missing, f"email link templates without a web page: {missing}"
    # the old API-style paths must not come back
    assert "/auth/verify-email" not in routes and "/auth/reset" not in routes


def test_web_base_url_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WEB_BASE_URL", "https://learn.example.in/")
    assert web_base_url() == "https://learn.example.in"
    assert web_link("reset_password", token="a/b c") == "https://learn.example.in/reset-password/a%2Fb%20c"
    monkeypatch.delenv("WEB_BASE_URL")
    assert web_base_url().startswith("http")
    assert web_path("verify_email", token="xyz") == "/verify/email/xyz"


async def test_reset_and_verify_emails_link_to_web_pages(browser, db, mail, monkeypatch) -> None:
    monkeypatch.setenv("WEB_BASE_URL", "https://web.test")
    u = await make_user(db)
    r = await browser.post("/auth/password/forgot", {"identifier": u.email})
    assert r.status_code == 202
    text = mail.sent[-1].text
    token = last_link_token(mail)
    assert f"https://web.test/reset-password/{token}" in text and "?token=" not in text
    signup = await browser.post(
        "/auth/signup",
        {
            "full_name": "Link Tester",
            "email": "link.tester.unique@example.com",
            "date_of_birth": "2000-04-01",
            "password": GOOD_PASSWORD,
            "consents": REQUIRED_CONSENTS,
        },
    )
    assert signup.status_code == 201, signup.text
    verify = mail.sent[-1].text
    assert re.search(r"https://web\.test/verify/email/[^\s/?]+", verify), verify
