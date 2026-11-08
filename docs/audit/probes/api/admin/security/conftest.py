"""Audit scratch (admin area, security console): reuse the security test fixtures."""

from tests.identity.fixtures import browser, mail, real_auth, sms  # noqa: F401
from tests.security.conftest import security_hooks  # noqa: F401
