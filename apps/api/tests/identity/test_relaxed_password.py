"""TD_PASSWORD_POLICY_RELAXED (owner decision 2026-11-11, testing phase): simple passwords allowed
(min 6, no blocklist / personal-info checks); the full policy applies without the switch."""

from __future__ import annotations

import pytest

from app.modules.identity.passwords import password_problems


def test_full_policy_without_the_switch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TD_PASSWORD_POLICY_RELAXED", raising=False)
    assert password_problems("admin123") == ["password_too_short"]
    assert password_problems("tirumala-admin-123456", context=("tirumala",)) == [
        "password_contains_personal_info"
    ]


def test_relaxed_policy_allows_simple_passwords(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TD_PASSWORD_POLICY_RELAXED", "true")
    assert password_problems("admin123") == []
    assert password_problems("tirumalarajumahali@admin123", context=("tirumalarajumahali",)) == []
    assert password_problems("abc12") == ["password_too_short"]
    assert password_problems("x" * 129) == ["password_too_long"]
