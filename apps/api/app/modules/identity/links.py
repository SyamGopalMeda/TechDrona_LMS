"""Links to the web app that the API puts in emails (verify email, reset password, …).

The base URL is ``WEB_BASE_URL`` (environment) and falls back to ``TD_PUBLIC_BASE_URL``.
``WEB_ROUTES`` must match real Next.js pages under ``apps/web/src/app`` — the test
``tests/identity/test_email_links.py`` checks every template against the page tree.
"""

from __future__ import annotations

import os
from urllib.parse import quote

from app.core.config import get_settings

# name -> path template; ``{token}`` segments map to ``[token]`` dynamic route folders.
WEB_ROUTES: dict[str, str] = {
    "verify_email": "/verify/email/{token}",
    "reset_password": "/reset-password/{token}",
    "forgot_password": "/forgot-password",
    "guardian_consent": "/guardian-consent/{token}",
    "login": "/login",
    "support_ticket": "/app/support/{ticket_id}",
    "order": "/app/orders/{order_id}",
    "billing": "/app/billing",
}


def web_base_url() -> str:
    base = os.environ.get("WEB_BASE_URL") or get_settings().TD_PUBLIC_BASE_URL
    return base.rstrip("/")


def web_path(name: str, **params: str) -> str:
    template = WEB_ROUTES[name]
    return template.format(**{k: quote(str(v), safe="") for k, v in params.items()})


def web_link(name: str, **params: str) -> str:
    return web_base_url() + web_path(name, **params)
