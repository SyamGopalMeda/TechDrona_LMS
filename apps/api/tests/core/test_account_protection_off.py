"""TD_ACCOUNT_PROTECTION_OFF (testing phase): no takeover lock or step-up, an existing protect-lock
ends at the next sign-in; ignored in production."""

from __future__ import annotations

from app.core.config import Settings


def test_setting_off_by_default_and_ignored_in_production() -> None:
    assert Settings(APP_ENV="staging").account_protection_off is False
    assert Settings(APP_ENV="staging", TD_ACCOUNT_PROTECTION_OFF=True).account_protection_off is True
    assert Settings(APP_ENV="production", TD_ACCOUNT_PROTECTION_OFF=True).account_protection_off is False
