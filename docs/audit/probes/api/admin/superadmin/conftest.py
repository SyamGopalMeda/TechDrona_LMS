"""Audit scratch (super admin panel): reuse the admin package fixtures (real auth + security hooks)."""
from tests.admin.conftest import security_hooks  # noqa: F401
from tests.identity.fixtures import browser, mail, real_auth, sms  # noqa: F401
