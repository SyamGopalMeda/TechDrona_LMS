"""Admissions tests: real resolver/permission checker, captured email, BFF Browser, in-memory
document store (payment proofs / resumes)."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest

from tests.identity.fixtures import browser, mail, real_auth, sms  # noqa: F401


@pytest.fixture(autouse=True)
def security_hooks(app: Any) -> Iterator[None]:
    from app.modules.admin.policy import identity_resolver
    from app.modules.identity.policy import register_policy_resolver
    from app.modules.security.router import install_hooks

    install_hooks()
    register_policy_resolver(identity_resolver)
    yield


@pytest.fixture(autouse=True)
def docs() -> Iterator[Any]:
    from app.modules.commerce.documents import MemoryDocumentStore, set_document_store

    store = MemoryDocumentStore()
    set_document_store(store)
    yield store
    set_document_store(None)
