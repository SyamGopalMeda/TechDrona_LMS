"""Firestore-only security tests (no Postgres; see tests/audit/fs/support.py)."""

from typing import Any

import pytest

from tests.audit.fs.support import fs_env, migrated_database  # noqa: F401
from tests.firestore.conftest import firestore_emulator  # noqa: F401


@pytest.fixture(autouse=True)
def security_hooks() -> Any:  # the parent fixture needs the full app; not used here
    yield


from tests.audit.fs.http_support import fs_http  # noqa: E402, F401
from tests.identity.fixtures import mail  # noqa: E402, F401
