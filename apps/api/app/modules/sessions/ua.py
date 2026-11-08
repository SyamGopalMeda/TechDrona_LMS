"""Minimal User-Agent parsing (family, major, OS, device class). The raw UA is never stored,
only ``SHA-256(ua)`` (``ua_hash``)."""

from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass

from app.core.security import sha256

_BROWSERS = (
    ("Edge", re.compile(r"Edg(?:e|A|iOS)?/(\d+)")),
    ("Opera", re.compile(r"OPR/(\d+)")),
    ("Samsung Internet", re.compile(r"SamsungBrowser/(\d+)")),
    ("Firefox", re.compile(r"(?:Firefox|FxiOS)/(\d+)")),
    ("Chrome", re.compile(r"(?:Chrome|CriOS)/(\d+)")),
    ("Safari", re.compile(r"Version/(\d+).*Safari/")),
)
_OS = (
    ("Android", re.compile(r"Android")),
    ("iOS", re.compile(r"iPhone|iPad|iPod")),
    ("Windows", re.compile(r"Windows NT")),
    ("macOS", re.compile(r"Mac OS X|Macintosh")),
    ("ChromeOS", re.compile(r"CrOS")),
    ("Linux", re.compile(r"Linux")),
)


@dataclass(frozen=True, slots=True)
class UaInfo:
    family: str
    major: str | None
    os_family: str
    device_class: str
    ua_hash: bytes | None

    @property
    def label(self) -> str:
        return f"{self.family} on {self.os_family}"


def parse_ua(ua: str | None) -> UaInfo:
    ua = (ua or "")[:1024]
    family, major = "Other", None
    for name, rx in _BROWSERS:
        m = rx.search(ua)
        if m:
            family, major = name, m.group(1)
            break
    os_family = next((name for name, rx in _OS if rx.search(ua)), "Other")
    if "iPad" in ua or "Tablet" in ua:
        device_class = "tablet"
    elif "Mobi" in ua or os_family in ("Android", "iOS"):
        device_class = "mobile"
    elif os_family in ("Windows", "macOS", "Linux", "ChromeOS"):
        device_class = "desktop"
    else:
        device_class = "unknown"
    return UaInfo(family, major, os_family, device_class, sha256(ua.encode()) if ua else None)


def valid_ip(raw: str | None) -> str | None:
    if not raw:
        return None
    try:
        return str(ipaddress.ip_address(raw.strip()))
    except ValueError:
        return None


def net_cluster(ip: str | None) -> str | None:
    """Coarse network cluster 'AS0:<prefix>' (/16 IPv4, /32 IPv6) until the offline ASN DB exists."""
    if not ip:
        return None
    addr = ipaddress.ip_address(ip)
    plen = 16 if addr.version == 4 else 32
    return f"AS0:{ipaddress.ip_network(f'{ip}/{plen}', strict=False)}"


def mask_ip(ip: str | None) -> str | None:
    """/24 (IPv4) or /48 (IPv6) for M2 views."""
    if not ip:
        return None
    addr = ipaddress.ip_address(ip)
    plen = 24 if addr.version == 4 else 48
    return str(ipaddress.ip_network(f"{ip}/{plen}", strict=False))
