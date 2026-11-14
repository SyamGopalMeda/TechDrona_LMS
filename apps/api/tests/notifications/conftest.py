"""Stage 4 fixtures (real resolver/checker, fake email/SMS capture, Browser).

Store matrix (docs/firebase/p2.md): ``@pytest.mark.usefixtures("notifications_backend")`` runs
a test on Postgres and on the Firestore emulator (``TD_STORE_NOTIFICATIONS``)."""

from tests.firestore.conftest import firestore_emulator  # noqa: F401
from tests.firestore.matrix import backend_fixture
from tests.identity.fixtures import browser, mail, real_auth, sms  # noqa: F401

notifications_backend = backend_fixture("notifications")
