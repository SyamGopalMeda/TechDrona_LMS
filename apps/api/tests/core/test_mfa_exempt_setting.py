"""TD_MFA_EXEMPT_EMAILS (demo owner override): exact, case-insensitive match; never in production."""

from app.core.config import Settings


def test_off_by_default() -> None:
    assert Settings(APP_ENV="staging").mfa_exempt("owner@example.com") is False


def test_listed_email_matches_case_insensitively() -> None:
    s = Settings(APP_ENV="staging", TD_MFA_EXEMPT_EMAILS=" Owner@Example.com , other@example.com")
    assert s.mfa_exempt("owner@example.com") is True
    assert s.mfa_exempt("OTHER@example.com") is True
    assert s.mfa_exempt("owner@example.co") is False
    assert s.mfa_exempt(None) is False


def test_ignored_in_production() -> None:
    s = Settings(APP_ENV="production", TD_MFA_EXEMPT_EMAILS="owner@example.com")
    assert s.mfa_exempt("owner@example.com") is False
