"""Browser cookies of the edge (port of lib/bff/cookies.ts) plus ``__session`` packing.

Two layouts (``TD_EDGE_COOKIE_PACKING``):

* ``split``: exactly the Next.js BFF: ``__Host-td_session``/``__Host-td_device``/
  ``__Host-td_remember`` (HttpOnly, SameSite=Lax, the API's Max-Age) and ``__Host-td_csrf``
  (readable, SameSite=Strict, browser-session lifetime). Dev-insecure mode drops ``__Host-`` and
  ``Secure`` like Next.js.
* ``session`` (default, Firebase Hosting): session, device, remember and the CSRF token are
  packed into one HttpOnly ``__session`` cookie, ``v1.<base64url(JSON)>`` with
  ``{"s": [value, expires_epoch], "d": [...], "r": [...], "c": [token, null]}``. Each part keeps
  its own expiry (expired parts are dropped when read); the cookie's Max-Age is the longest
  remaining part (no Max-Age when only browser-session parts remain; cleared when empty).
  The readable ``td_csrf`` cookie is still issued with the same value and attributes, so browser
  JavaScript (``readCsrfToken``) and the ``X-CSRF-Token`` header are unchanged; the edge compares
  the header with the packed copy, because Hosting does not forward ``td_csrf``.

No signature on the packed cookie: each part is the same opaque credential the browser held
before (HMAC'd device token, random session/remember tokens, signed CSRF token) and is validated
exactly as before, so tampering gains nothing that editing separate cookies did not.
"""

from __future__ import annotations

import base64
import json
import math
import time
from dataclasses import dataclass, field
from email.utils import parsedate_to_datetime

from lms_edge.config import COOKIE_BASE, HOSTING_COOKIE, EdgeConfig

KIND_KEYS = {"session": "s", "device": "d", "remember": "r", "csrf": "c"}
_KEYS_KIND = {v: k for k, v in KIND_KEYS.items()}
PACK_VERSION = "v1"
MAX_PACKED = 3800  # stay under the 4096-byte per-cookie limit


def parse_cookie_header(header: str | None) -> dict[str, str]:
    """First occurrence wins (same as parseCookieHeader)."""
    out: dict[str, str] = {}
    if not header:
        return out
    for part in header.split(";"):
        idx = part.find("=")
        if idx <= 0:
            continue
        name, value = part[:idx].strip(), part[idx + 1 :].strip()
        if name and name not in out:
            out[name] = value
    return out


def serialize_cookie(
    name: str,
    value: str,
    secure: bool,
    *,
    http_only: bool,
    same_site: str,
    max_age: int | None = None,
    expires: str | None = None,
) -> str:
    parts = [f"{name}={value}", "Path=/"]
    if max_age is not None:
        parts.append(f"Max-Age={math.trunc(max_age)}")
    if expires:
        parts.append(f"Expires={expires}")
    if secure:
        parts.append("Secure")
    if http_only:
        parts.append("HttpOnly")
    parts.append(f"SameSite={same_site}")
    return "; ".join(parts)


@dataclass
class ParsedSetCookie:
    name: str
    value: str
    max_age: int | None = None
    expires: str | None = None


def parse_set_cookie(header: str) -> ParsedSetCookie | None:
    pair, *attrs = header.split(";")
    idx = pair.find("=")
    if idx <= 0:
        return None
    parsed = ParsedSetCookie(pair[:idx].strip(), pair[idx + 1 :].strip())
    for attr in attrs:
        k, _, v = attr.partition("=")
        key = k.strip().lower()
        if key == "max-age":
            try:
                parsed.max_age = int(v.strip())
            except ValueError:
                pass
        elif key == "expires":
            parsed.expires = v.strip()
    return parsed


def cookie_kind_from_name(name: str) -> str | None:
    base = name[len("__Host-") :] if name.startswith("__Host-") else name
    for kind, b in COOKIE_BASE.items():
        if b == base:
            return kind
    return None


def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64d(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def unpack(value: str | None, now: float) -> dict[str, tuple[str, float | None]]:
    if not value or not value.startswith(PACK_VERSION + ".") or len(value) > 4096:
        return {}
    try:
        data = json.loads(_b64d(value[len(PACK_VERSION) + 1 :]))
    except (ValueError, UnicodeDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    out: dict[str, tuple[str, float | None]] = {}
    for key, item in data.items():
        kind = _KEYS_KIND.get(key)
        if kind is None or not isinstance(item, list) or len(item) != 2:
            continue
        val, exp = item
        if not isinstance(val, str) or not val or not (exp is None or isinstance(exp, int | float)):
            continue
        if exp is not None and exp <= now:
            continue
        out[kind] = (val, exp)
    return out


def pack(jar: dict[str, tuple[str, float | None]]) -> str:
    data = {KIND_KEYS[k]: [v, (int(e) if e is not None else None)] for k, (v, e) in sorted(jar.items())}
    return PACK_VERSION + "." + _b64e(json.dumps(data, separators=(",", ":")).encode())


def _expiry(parsed: ParsedSetCookie, now: float) -> float | None:
    if parsed.max_age is not None:
        return now + parsed.max_age
    if parsed.expires:
        try:
            return parsed_expires(parsed.expires)
        except (TypeError, ValueError):
            return None
    return None


def parsed_expires(expires: str) -> float:
    return parsedate_to_datetime(expires).timestamp()


@dataclass
class CookieJar:
    """The browser's credentials as the edge sees them, and the Set-Cookie headers to send back."""

    config: EdgeConfig
    now: float = field(default_factory=time.time)
    values: dict[str, tuple[str, float | None]] = field(default_factory=dict)
    _split_out: list[str] = field(default_factory=list)
    _visible_csrf: str | None = None
    _dirty: bool = False

    @classmethod
    def from_header(
        cls, config: EdgeConfig, cookie_header: str | None, now: float | None = None
    ) -> CookieJar:
        jar = cls(config, now if now is not None else time.time())
        cookies = parse_cookie_header(cookie_header)
        if config.packing == "session":
            jar.values = unpack(cookies.get(HOSTING_COOKIE), jar.now)
        else:
            for kind in COOKIE_BASE:
                v = cookies.get(config.cookie_name(kind))
                if v:
                    jar.values[kind] = (v, None)
        return jar

    def get(self, kind: str) -> str | None:
        item = self.values.get(kind)
        return item[0] if item else None

    @property
    def secure(self) -> bool:
        return self.config.cookie_mode == "secure"

    def set_from_upstream(self, kind: str, parsed: ParsedSetCookie) -> None:
        """Re-issue an API cookie (HttpOnly, SameSite=Lax, the API's Max-Age/Expires)."""
        cleared = parsed.value == "" or (parsed.max_age is not None and parsed.max_age <= 0)
        if self.config.packing == "split":
            self._split_out.append(
                serialize_cookie(
                    self.config.cookie_name(kind),
                    parsed.value,
                    self.secure,
                    http_only=True,
                    same_site="Lax",
                    max_age=parsed.max_age,
                    expires=parsed.expires,
                )
            )
        self._dirty = True
        if cleared:
            self.values.pop(kind, None)
        else:
            self.values[kind] = (parsed.value, _expiry(parsed, self.now))

    def set_csrf(self, token: str) -> None:
        """Issue the readable CSRF cookie (and its packed copy)."""
        self.values["csrf"] = (token, None)
        self._visible_csrf = token
        self._dirty = True

    def reissue_visible_csrf(self) -> None:
        """Re-send the readable cookie with the current token (packed mode bootstrap)."""
        tok = self.get("csrf")
        if tok:
            self._visible_csrf = tok

    def set_cookie_headers(self) -> list[str]:
        out = list(self._split_out)
        if self.config.packing == "session" and self._dirty:
            persistent = [e for _v, e in self.values.values() if e is not None]
            if not self.values:
                out.append(
                    serialize_cookie(
                        HOSTING_COOKIE, "", self.secure, http_only=True, same_site="Lax", max_age=0
                    )
                )
            else:
                value = pack(self.values)
                if len(value) > MAX_PACKED:  # never expected (tokens are < 200 chars each)
                    raise ValueError("packed __session cookie too large")
                max_age = max(1, math.ceil(max(persistent) - self.now)) if persistent else None
                out.append(
                    serialize_cookie(
                        HOSTING_COOKIE, value, self.secure, http_only=True, same_site="Lax", max_age=max_age
                    )
                )
        if self._visible_csrf is not None:
            # Not HttpOnly: client code reads it to echo it in X-CSRF-Token (double submit).
            out.append(
                serialize_cookie(
                    self.config.cookie_name("csrf"),
                    self._visible_csrf,
                    self.secure,
                    http_only=False,
                    same_site="Strict",
                )
            )
        return out
