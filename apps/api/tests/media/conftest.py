"""Real resolver/checker, fake email/SMS capture, Browser (Stage 4 fixtures)."""

from tests.catalog.conftest import catalog_backend, firestore_emulator  # noqa: F401
from tests.catalog.factory import audited  # noqa: F401
from tests.identity.fixtures import browser, mail, real_auth, sms  # noqa: F401
