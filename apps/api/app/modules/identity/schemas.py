"""Request/response models for identity (AUTH-*, ME-*)."""

from __future__ import annotations

import uuid
from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Purpose = Literal[
    "terms",
    "privacy_notice",
    "core_service",
    "security_monitoring",
    "analytics_personalisation",
    "device_fingerprint",
    "marketing_email",
    "marketing_sms",
    "assessment_integrity",
    "analytics_product",
]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ConsentItem(Strict):
    purpose: Purpose
    notice_version: str = Field(min_length=1, max_length=40)
    granted: bool


class GuardianIn(Strict):
    name: str = Field(min_length=1, max_length=200)
    email: str | None = Field(default=None, max_length=254)
    phone: str | None = Field(default=None, max_length=20)
    relationship: Literal["parent", "legal_guardian"]


class SignupIn(Strict):
    full_name: str = Field(min_length=1, max_length=200)
    email: str | None = Field(default=None, max_length=254)
    mobile: str | None = Field(default=None, max_length=20)
    date_of_birth: date
    password: str = Field(min_length=1, max_length=1024)
    consents: list[ConsentItem] = Field(default_factory=list, max_length=20)
    guardian: GuardianIn | None = None


class TokenIn(Strict):
    token: str = Field(min_length=16, max_length=128)


class LoginIn(Strict):
    identifier: str = Field(min_length=1, max_length=254)
    password: str = Field(min_length=1, max_length=1024)
    remember_device: bool = False


class MfaVerifyIn(Strict):
    method: Literal["totp", "recovery_code"]
    code: str = Field(min_length=6, max_length=32)


class DeviceSendIn(Strict):
    channel: Literal["email", "sms"]


class DeviceVerifyIn(Strict):
    code: str | None = Field(default=None, min_length=6, max_length=10)
    method: Literal["otp", "totp"] = "otp"
    remove_user_device_id: uuid.UUID | None = None


class SessionChoiceIn(Strict):
    end_session_id: uuid.UUID | None = None
    cancel: bool = False
    confirm_attempt_session: bool = False


class ForgotIn(Strict):
    identifier: str = Field(min_length=1, max_length=254)


class ResetIn(Strict):
    token: str = Field(min_length=16, max_length=128)
    new_password: str = Field(min_length=1, max_length=1024)


class ChangePasswordIn(Strict):
    current_password: str = Field(min_length=1, max_length=1024)
    new_password: str = Field(min_length=1, max_length=1024)
    revoke_other_sessions: bool = True


class StepUpOptionsIn(Strict):
    purpose: str | None = Field(default=None, max_length=64)
    send_otp_via: Literal["email", "sms"] | None = None


class StepUpIn(Strict):
    method: Literal["totp", "password", "email_otp", "sms_otp"]
    code: str | None = Field(default=None, max_length=32)
    password: str | None = Field(default=None, max_length=1024)


class RememberIn(Strict):
    remember_token: str = Field(min_length=16, max_length=128)


class GuardianDecisionIn(Strict):
    otp_code: str = Field(min_length=6, max_length=10)
    decision: Literal["consent", "decline"]
    declaration: bool = False


class ConsentChangeIn(Strict):
    purpose: Purpose
    action: Literal["granted", "withdrawn"]
    notice_version: str = Field(min_length=1, max_length=40)
    context_ref: uuid.UUID | None = None


class TotpConfirmIn(Strict):
    code: str = Field(min_length=6, max_length=10)


class TotpBeginIn(Strict):
    label: str | None = Field(default=None, max_length=60)


class ProfilePatchIn(Strict):
    full_name: str | None = Field(default=None, min_length=1, max_length=200)
    display_name: str | None = Field(default=None, max_length=100)
    college_name_text: str | None = Field(default=None, max_length=200)
    degree: str | None = Field(default=None, max_length=100)
    branch: str | None = Field(default=None, max_length=100)
    graduation_year: int | None = Field(default=None, ge=1990, le=2100)
    target_role: str | None = Field(default=None, max_length=100)
