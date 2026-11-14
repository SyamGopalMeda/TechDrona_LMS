"""Firestore-only audit tests (data-ops agent): run against the emulator **without Postgres**.

The root ``migrated_database`` (session, autouse) needs Postgres; it is overridden here so these
tests run while Docker/Postgres is down. The Postgres side of the audit module is covered by the
existing ``tests/audit`` suite.
"""

from tests.audit.fs.http_support import fs_http  # noqa: F401
from tests.audit.fs.support import fs_env, migrated_database  # noqa: F401
from tests.firestore.conftest import firestore_emulator  # noqa: F401
