"""Per-module persistence switch for the strangler migration (MIGRATION-PLAN §4.1).

``TD_STORE_<MODULE>=postgres|firestore`` (default ``postgres``; ``pg`` is accepted as an alias).
Read once per process (startup), never flipped at runtime, so a module can't split-brain between
two stores inside one process. ``shadow`` from the plan is intentionally not offered: owner
decision F1 (demo data only) replaces dual-running with backfill -> verify -> flip -> reseed.

Pure Python on purpose (no google/grpc imports): the startup gate imports it in every process.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from functools import lru_cache
from typing import Literal

from dotenv import dotenv_values

from app.core.config import ENV_FILES

Backend = Literal["postgres", "firestore"]

ENV_PREFIX = "TD_STORE_"

# ``core`` = outbox_events / idempotency_keys / locks / counters (moves with P6).
MODULES: frozenset[str] = frozenset(
    {
        "admin",
        "admissions",
        "ai",
        "analytics",
        "assessments",
        "audit",
        "catalog",
        "coding",
        "commerce",
        "core",
        "engage",
        "entitlements",
        "hub",
        "identity",
        "learning",
        "media",
        "mentoring",
        "notifications",
        "orgs",
        "paths",
        "placement",
        "rbac",
        "security",
        "sessions",
        "support",
    }
)

_ALIASES: dict[str, Backend] = {"postgres": "postgres", "pg": "postgres", "firestore": "firestore"}


class StoreConfigError(ValueError):
    pass


def raw_switch_env() -> dict[str, str]:
    """Same precedence as ``Settings``: process env > apps/api/.env > repo-root .env."""
    merged: dict[str, str] = {}
    for f in ENV_FILES:
        if f.is_file():
            merged.update({k: v for k, v in dotenv_values(f).items() if k.startswith(ENV_PREFIX) and v})
    merged.update({k: v for k, v in os.environ.items() if k.startswith(ENV_PREFIX)})
    return merged


def parse_backends(env: Mapping[str, str]) -> dict[str, Backend]:
    """Validate every ``TD_STORE_*`` entry; unknown modules and values are errors (typo guard)."""
    out: dict[str, Backend] = dict.fromkeys(MODULES, "postgres")
    problems: list[str] = []
    for key, raw in env.items():
        if not key.startswith(ENV_PREFIX):
            continue
        module = key[len(ENV_PREFIX) :].lower()
        value = (raw or "").strip().lower()
        if module not in MODULES:
            problems.append(f"{key}: unknown module {module!r}")
            continue
        if not value:
            continue
        if value not in _ALIASES:
            problems.append(f"{key}={raw!r}: expected postgres or firestore")
            continue
        out[module] = _ALIASES[value]
    if problems:
        raise StoreConfigError("; ".join(sorted(problems)))
    return out


@lru_cache(maxsize=1)
def store_backends() -> dict[str, Backend]:
    return parse_backends(raw_switch_env())


def store_backend(module: str) -> Backend:
    """The persistence backend selected for ``module`` (raises on an unknown module name)."""
    if module not in MODULES:
        raise StoreConfigError(f"unknown module {module!r}")
    return store_backends()[module]


def uses_firestore(module: str) -> bool:
    return store_backend(module) == "firestore"


def firestore_modules() -> tuple[str, ...]:
    return tuple(sorted(m for m, b in store_backends().items() if b == "firestore"))


def reset_store_backends() -> None:
    """For tests: re-read ``TD_STORE_*`` on next use."""
    store_backends.cache_clear()
