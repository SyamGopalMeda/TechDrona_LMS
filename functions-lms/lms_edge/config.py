"""Edge configuration: the same environment variables as the Next.js BFF (lib/bff/config.ts).

==============================  ==========================================================
``TD_CSRF_KEY`` (+ ``_PREVIOUS``)  CSRF HMAC key(s); required (>= 32 chars in secure mode)
``TD_SERVICE_TOKEN``             service token presented to the API (``Authorization: Service``)
``TD_PUBLIC_BASE_URL``           public origin (Origin check, ``X-Forwarded-Host/-Proto``)
``TD_TRUSTED_PROXY_HOPS``        proxies in front of the edge appending to X-Forwarded-For
``TD_ORIGIN_VERIFY_HEADER``      optional shared secret header (defence in depth)
``TD_BFF_PROXY_TIMEOUT_MS``      upstream timeout (default 15000)
``TD_ADMISSIONS_ALLOWED_ORIGINS`` website origins for the public admissions bridge
``TD_COOKIE_SECURE``             outside production: ``true`` = ``__Host-`` names + Secure
``TD_EDGE_COOKIE_PACKING``       ``session`` (default: pack into ``__session`` for Hosting)
                                 or ``split`` (separate cookies exactly like Next.js)
``TD_EDGE_TRUST_VIEWER_ADDRESS`` ``true`` only behind an edge that overwrites
                                 ``CloudFront-Viewer-Address`` (Caddy did; Hosting does not)
==============================  ==========================================================
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlsplit

CookieMode = Literal["secure", "dev-insecure"]
Packing = Literal["session", "split"]

COOKIE_BASE = {"session": "td_session", "device": "td_device", "remember": "td_remember", "csrf": "td_csrf"}
HOSTING_COOKIE = "__session"  # the only cookie Firebase Hosting forwards to functions
PRODUCTION_ENVS = {"prod", "production"}


class ConfigError(Exception):
    pass


@dataclass(frozen=True)
class EdgeConfig:
    csrf_keys: tuple[str, ...]
    service_token: str
    public_origin: str
    proxy_timeout_s: float
    origin_verify_value: str
    trusted_proxy_hops: int
    cookie_mode: CookieMode
    packing: Packing
    trust_viewer_address: bool
    admissions_origins: frozenset[str]

    def cookie_name(self, kind: str) -> str:
        base = COOKIE_BASE[kind]
        return f"__Host-{base}" if self.cookie_mode == "secure" else base


def cookie_mode(env: Mapping[str, str]) -> CookieMode:
    if env.get("APP_ENV", "local") in PRODUCTION_ENVS or env.get("NODE_ENV") == "production":
        return "secure"
    return "secure" if env.get("TD_COOKIE_SECURE", "").lower() == "true" else "dev-insecure"


def _origin(url: str) -> str:
    u = urlsplit(url)
    return f"{u.scheme}://{u.netloc}"


def admissions_origins(env: Mapping[str, str]) -> frozenset[str]:
    raw = (
        env.get("TD_ADMISSIONS_ALLOWED_ORIGINS")
        or env.get("TD_WEBSITE_URL")
        or env.get("NEXT_PUBLIC_SITE_URL")
        or ""
    )
    out: set[str] = set()
    for part in raw.split(","):
        v = part.strip()
        if not v:
            continue
        try:
            u = urlsplit(v)
        except ValueError:
            continue
        if not u.scheme or not u.netloc:
            continue
        if u.scheme == "https" or u.hostname in ("localhost", "127.0.0.1"):
            out.add(_origin(v))
    return frozenset(out)


def _int(v: str | None, default: int) -> int:
    try:
        n = int(v) if v is not None else default
    except ValueError:
        return default
    return n


def load_config(env: Mapping[str, str] | None = None) -> EdgeConfig:
    env = os.environ if env is None else env
    mode = cookie_mode(env)
    key = env.get("TD_CSRF_KEY", "")
    if not key:
        raise ConfigError("TD_CSRF_KEY is not set")
    if mode == "secure" and (len(key) < 32 or "REPLACE" in key):
        raise ConfigError("TD_CSRF_KEY must be a real 256-bit secret outside local development")
    timeout = _int(env.get("TD_BFF_PROXY_TIMEOUT_MS"), 15000)
    hops = _int(env.get("TD_TRUSTED_PROXY_HOPS"), 0)
    packing = env.get("TD_EDGE_COOKIE_PACKING", "session")
    if packing not in ("session", "split"):
        raise ConfigError("TD_EDGE_COOKIE_PACKING must be session or split")
    return EdgeConfig(
        csrf_keys=tuple(k for k in (key, env.get("TD_CSRF_KEY_PREVIOUS", "")) if k),
        service_token=env.get("TD_SERVICE_TOKEN", ""),
        public_origin=_origin(
            env.get("TD_PUBLIC_BASE_URL") or env.get("NEXT_PUBLIC_BASE_URL") or "http://localhost:3000"
        ),
        proxy_timeout_s=(timeout if timeout > 0 else 15000) / 1000.0,
        origin_verify_value=env.get("TD_ORIGIN_VERIFY_HEADER", ""),
        trusted_proxy_hops=hops if hops >= 0 else 0,
        cookie_mode=mode,
        packing=packing,  # type: ignore[arg-type]
        trust_viewer_address=env.get("TD_EDGE_TRUST_VIEWER_ADDRESS", "").lower() == "true",
        admissions_origins=admissions_origins(env),
    )
