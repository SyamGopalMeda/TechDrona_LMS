"""Base class + static contract for per-module Firestore repositories (MIGRATION-PLAN §1.4 #2).

Later phases write ``app/modules/<m>/repo_firestore.py``::

    class NotificationRepo(FirestoreRepository):
        async def list_for_user(self, user_id: UUID, cursor: str | None) -> Page: ...

        @platform_only("notifications.admin")
        async def purge_older_than(self, days: int) -> int: ...

Rule (checked by ``assert_repository_scoped`` in each module's contract test): every public
async method takes a ``user_id`` parameter or is decorated ``@platform_only(permission)``.
"""

from __future__ import annotations

import functools
import inspect
from collections.abc import Awaitable, Callable
from typing import Any, ParamSpec, TypeVar

from app.core.firestore.errors import StoreAccessDeniedError
from app.core.firestore.store import ScopedStore

P = ParamSpec("P")
R = TypeVar("R")

_PLATFORM_ONLY_ATTR = "__td_platform_only__"


class FirestoreRepository:
    def __init__(self, store: ScopedStore) -> None:
        if not isinstance(store, ScopedStore):
            raise TypeError("repositories are built from a ScopedStore (principal or system job)")
        self.store = store


def platform_only(permission: str) -> Callable[[Callable[P, Awaitable[R]]], Callable[P, Awaitable[R]]]:
    """The caller must be a system job or hold ``permission`` (checked before the method runs)."""

    def deco(fn: Callable[P, Awaitable[R]]) -> Callable[P, Awaitable[R]]:
        @functools.wraps(fn)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            repo = args[0]
            if not isinstance(repo, FirestoreRepository):
                raise TypeError("@platform_only is for FirestoreRepository methods")
            if not await repo.store.has_permission(permission):
                raise StoreAccessDeniedError(f"{fn.__qualname__} needs {permission}")
            return await fn(*args, **kwargs)

        setattr(wrapper, _PLATFORM_ONLY_ATTR, permission)
        return wrapper

    return deco


def unscoped_methods(repo_cls: type[Any]) -> list[str]:
    """Public async methods with neither a ``user_id`` parameter nor ``@platform_only``."""
    bad: list[str] = []
    for name, fn in inspect.getmembers(repo_cls, predicate=inspect.isfunction):
        if name.startswith("_") or not inspect.iscoroutinefunction(fn):
            continue
        if getattr(fn, _PLATFORM_ONLY_ATTR, None):
            continue
        if "user_id" not in inspect.signature(fn).parameters:
            bad.append(name)
    return sorted(bad)


def assert_repository_scoped(repo_cls: type[Any]) -> None:
    bad = unscoped_methods(repo_cls)
    if bad:
        raise AssertionError(
            f"{repo_cls.__name__}: methods {bad} must take user_id or be @platform_only(permission)"
        )
