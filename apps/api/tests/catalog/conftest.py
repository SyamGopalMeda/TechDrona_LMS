"""Real resolver/checker, fake email/SMS capture, Browser (Stage 4 fixtures).

Store matrix (docs/firebase/p2.md): ``@pytest.mark.usefixtures("catalog_backend")`` runs a test on
Postgres and with ``TD_STORE_CATALOG=firestore`` on the emulator (the catalog is backfilled from
the Postgres test database first; ``tests.catalog.factory`` copies its rows when the switch is on).
"""

from tests.catalog.factory import audited  # noqa: F401
from tests.firestore.conftest import firestore_emulator  # noqa: F401
from tests.firestore.matrix import backend_fixture
from tests.identity.fixtures import browser, mail, real_auth, sms  # noqa: F401

catalog_backend = backend_fixture("catalog")
