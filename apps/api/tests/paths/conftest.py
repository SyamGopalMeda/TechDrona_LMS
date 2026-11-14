"""Real resolver/checker + browser fixtures (same as the learning tests)."""

from tests.catalog.conftest import catalog_backend, firestore_emulator  # noqa: F401
from tests.identity.fixtures import browser, mail, real_auth, sms  # noqa: F401
