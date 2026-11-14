"""Firestore part of the startup safety gate (called from ``app.core.startup_checks``).

* Every environment: ``TD_STORE_*`` must parse, and a service-account key must never live inside
  the repository tree (it would be one ``git add -A`` away from a leak).
* Production, when any module is on Firestore: no emulator, no ``demo-*`` project, a project id
  and a readable service-account file are required.
"""

from __future__ import annotations

from pathlib import Path

from app.core.config import _REPO_ROOT, Settings
from app.core.firestore.backend import StoreConfigError, parse_backends

DEMO_PROJECT_PREFIX = "demo-"


def _inside_repo(path: Path) -> bool:
    try:
        return path.resolve().is_relative_to(_REPO_ROOT.resolve())
    except OSError:
        return False


def always_problems(s: Settings, env: dict[str, str]) -> list[str]:
    out: list[str] = []
    try:
        parse_backends(env)
    except StoreConfigError as e:
        out.append(f"invalid store switch: {e}")
    if s.FIREBASE_SERVICE_ACCOUNT_FILE and _inside_repo(Path(s.FIREBASE_SERVICE_ACCOUNT_FILE)):
        out.append("FIREBASE_SERVICE_ACCOUNT_FILE must point outside the repository (never commit keys)")
    return out


def production_problems(s: Settings, env: dict[str, str]) -> list[str]:
    try:
        on_firestore = [m for m, b in parse_backends(env).items() if b == "firestore"]
    except StoreConfigError:
        return []  # reported by always_problems
    if not on_firestore:
        return []
    out: list[str] = []
    if s.FIRESTORE_EMULATOR_HOST:
        out.append("FIRESTORE_EMULATOR_HOST must not be set in production")
    project = s.FIREBASE_PROJECT_ID.strip()
    if not project or project.startswith(DEMO_PROJECT_PREFIX):
        out.append("FIREBASE_PROJECT_ID missing or a demo-* emulator project")
    key = s.FIREBASE_SERVICE_ACCOUNT_FILE.strip()
    if not key and s.TD_RUNTIME == "firebase":
        return out  # Cloud Functions: Application Default Credentials, no key file
    if not key:
        out.append(
            "FIREBASE_SERVICE_ACCOUNT_FILE missing (modules on Firestore: "
            + ", ".join(sorted(on_firestore))
            + ")"
        )
    elif not Path(key).is_file():
        out.append("FIREBASE_SERVICE_ACCOUNT_FILE does not point to a readable file")
    return out
