"""COM-06: SES email and MSG91 SMS adapters (request shapes per the providers' documented APIs;
no live provider is called)."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from app.core.config import reset_settings_cache
from app.modules.notifications import adapters
from app.modules.notifications.adapters import (
    Msg91Error,
    Msg91SmsAdapter,
    OutboundEmail,
    OutboundSms,
    SesEmailAdapter,
)


@pytest.fixture
def provider_env(monkeypatch) -> Any:
    monkeypatch.setenv("EMAIL_FROM_ADDRESS", "no-reply@techdrona.in")
    monkeypatch.setenv("AWS_REGION", "ap-south-1")
    monkeypatch.setenv("SES_CONFIGURATION_SET_TRANSACTIONAL", "td-transactional")
    monkeypatch.setenv("MSG91_AUTH_KEY", "auth-key-123")
    monkeypatch.setenv("MSG91_SENDER_ID", "TCHDRN")
    monkeypatch.setenv("MSG91_DLT_ENTITY_ID", "1201160000000000001")
    monkeypatch.setenv("MSG91_TEMPLATE_ID_OTP", "tmpl-otp")
    monkeypatch.setenv("MSG91_TEMPLATE_ID_SECURITY_NOTICE", "tmpl-sec")
    monkeypatch.setenv("MSG91_BASE_URL", "https://control.msg91.test/api/v5")
    reset_settings_cache()
    yield
    monkeypatch.undo()
    reset_settings_cache()


class FakeSes:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def send_email(self, **kw: Any) -> dict[str, Any]:
        self.calls.append(kw)
        return {"MessageId": "0100018f-ses-id"}


async def test_ses_adapter_sends_simple_email_with_configuration_set(provider_env) -> None:
    fake = FakeSes()
    mid = await SesEmailAdapter(client=fake).send(
        OutboundEmail("ananya@example.com", "Verify", "Click the link", "security", "auth.verify_email")
    )
    assert mid == "0100018f-ses-id"
    (req,) = fake.calls
    assert req["FromEmailAddress"] == "Tech Drona <no-reply@techdrona.in>"
    assert req["Destination"] == {"ToAddresses": ["ananya@example.com"]}
    assert req["Content"]["Simple"]["Subject"]["Data"] == "Verify"
    assert req["Content"]["Simple"]["Body"]["Text"]["Data"] == "Click the link"
    assert req["ConfigurationSetName"] == "td-transactional"
    assert {"Name": "template", "Value": "auth.verify_email"} in req["EmailTags"]


async def test_msg91_adapter_posts_flow_with_dlt_template_and_otp_variable(provider_env) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"type": "success", "message": "req-42"})

    a = Msg91SmsAdapter(transport=httpx.MockTransport(handler))
    ref = await a.send(OutboundSms("+919876543221", "482913 is your Tech Drona code.", "otp"))
    assert ref == "req-42"
    (req,) = seen
    assert str(req.url) == "https://control.msg91.test/api/v5/flow"
    assert req.headers["authkey"] == "auth-key-123"
    body = json.loads(req.content)
    assert body["template_id"] == "tmpl-otp" and body["sender"] == "TCHDRN"
    assert body["recipients"] == [{"mobiles": "919876543221", "otp": "482913"}]
    assert body["DLT_TE_ID"] == "1201160000000000001"


async def test_msg91_adapter_refuses_unmapped_templates_and_provider_errors(provider_env) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"type": "error", "message": "Invalid template"})

    a = Msg91SmsAdapter(transport=httpx.MockTransport(handler))
    with pytest.raises(Msg91Error):
        await a.send(OutboundSms("+919876543221", "hello", "marketing.promo"))
    with pytest.raises(Msg91Error):
        await a.send(OutboundSms("+919876543221", "Tech Drona: sign-in paused", "security.notice"))


def test_provider_selection_uses_real_adapters(provider_env, monkeypatch) -> None:
    monkeypatch.setenv("EMAIL_PROVIDER", "ses")
    monkeypatch.setenv("SMS_PROVIDER", "msg91")
    reset_settings_cache()
    prev_e, prev_s = adapters._email, adapters._sms
    adapters.set_email_adapter(None)
    adapters.set_sms_adapter(None)
    try:
        assert isinstance(adapters.get_email_adapter(), SesEmailAdapter)
        assert isinstance(adapters.get_sms_adapter(), Msg91SmsAdapter)
    finally:
        adapters.set_email_adapter(prev_e)
        adapters.set_sms_adapter(prev_s)
