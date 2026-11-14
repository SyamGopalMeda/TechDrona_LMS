"""Security test fixtures: real resolver/permission checker (Stage 4 fixtures) and the security
hooks always installed (other packages may have reset them)."""

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


# Store matrix (docs/firebase/p2.md): ``@pytest.mark.usefixtures("admin_backend")`` runs a test
# on Postgres and on the Firestore emulator (flags + policy settings).
from tests.firestore.conftest import firestore_emulator  # noqa: E402, F401
from tests.firestore.matrix import backend_fixture  # noqa: E402


def _invalidate_flags() -> None:
    from app.modules.admin import flags

    flags.invalidate()


admin_backend = backend_fixture("admin", on_switch=_invalidate_flags)
