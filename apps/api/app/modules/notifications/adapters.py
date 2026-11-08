"""Email / SMS provider adapters.

* Email: ``EMAIL_PROVIDER=smtp`` → ``SmtpEmailAdapter`` (local: Mailpit on SMTP_HOST:SMTP_PORT);
  ``fake``/``console``/``memory`` → ``MemoryEmailAdapter`` (FAKE, captures messages in memory);
  ``ses`` → ``SesEmailAdapter`` (Amazon SES v2 ``SendEmail``, simple content, optional
  configuration set ``SES_CONFIGURATION_SET_TRANSACTIONAL``; credentials from the task role).
* SMS: ``SMS_PROVIDER=console``/``fake`` → ``ConsoleSmsAdapter`` (FAKE: logs only the masked
  number and template key — never the body/OTP — and keeps the last messages in memory for
  local testing); ``msg91`` → ``Msg91SmsAdapter`` (MSG91 Flow API v5 with DLT-registered
  templates).

COM-06: the SES and MSG91 adapters follow the providers' documented APIs but have NOT been
verified against live accounts (no credentials in this environment). Production refuses to
start without their configuration (``app.core.startup_checks``).

Fakes are refused in production by ``app.core.startup_checks`` (registered below).
Tests and dev tools may override the active adapters with ``set_email_adapter`` /
``set_sms_adapter``.
"""

from __future__ import annotations

import asyncio
import re
import smtplib
from collections import deque
from dataclasses import dataclass, field
from email.message import EmailMessage as MimeMessage
from email.utils import formataddr, make_msgid
from typing import Any, Protocol

import httpx
import structlog

from app.core.config import Settings, get_settings
from app.core.security import load_env_mapping
from app.core.startup_checks import register_fake_adapter
from app.modules.identity.contacts import mask_email, mask_phone

log = structlog.get_logger("app.notifications")


@dataclass(frozen=True)
class OutboundEmail:
    to: str
    subject: str
    text: str
    category: str = "transactional"
    template_key: str = "generic"


@dataclass(frozen=True)
class OutboundSms:
    to: str
    text: str
    template_key: str = "generic"


class EmailAdapter(Protocol):
    name: str

    async def send(self, msg: OutboundEmail) -> str: ...


class SmsAdapter(Protocol):
    name: str

    async def send(self, msg: OutboundSms) -> str: ...


def _env(name: str, default: str) -> str:
    return str(load_env_mapping().get(name) or default)


class SmtpEmailAdapter:
    name = "smtp"

    def __init__(self, host: str | None = None, port: int | None = None) -> None:
        self.host = host or _env("SMTP_HOST", "localhost")
        self.port = port or int(_env("SMTP_PORT", "1025"))
        self.from_address = _env("EMAIL_FROM_ADDRESS", "no-reply@example.invalid")
        self.from_name = _env("EMAIL_FROM_NAME", "Tech Drona")

    def _send_sync(self, msg: OutboundEmail) -> str:
        mime = MimeMessage()
        mime["From"] = formataddr((self.from_name, self.from_address))
        mime["To"] = msg.to
        mime["Subject"] = msg.subject
        mid = make_msgid(domain="techdrona.local")
        mime["Message-ID"] = mid
        mime["X-TD-Template"] = msg.template_key
        mime.set_content(msg.text)
        with smtplib.SMTP(self.host, self.port, timeout=5) as smtp:
            smtp.send_message(mime)
        return mid

    async def send(self, msg: OutboundEmail) -> str:
        mid = await asyncio.to_thread(self._send_sync, msg)
        log.info("email_sent", provider="smtp", to=mask_email(msg.to), template=msg.template_key)
        return mid


@dataclass
class MemoryEmailAdapter:
    """FAKE email adapter: keeps messages in memory (tests, offline dev)."""

    name: str = "fake_memory"
    sent: list[OutboundEmail] = field(default_factory=list)

    async def send(self, msg: OutboundEmail) -> str:
        self.sent.append(msg)
        log.info("email_captured", provider=self.name, to=mask_email(msg.to), template=msg.template_key)
        return f"mem-{len(self.sent)}"


@dataclass
class ConsoleSmsAdapter:
    """FAKE SMS adapter: logs the masked destination only; bodies stay in an in-memory ring."""

    name: str = "fake_console"
    sent: deque[OutboundSms] = field(default_factory=lambda: deque(maxlen=200))

    async def send(self, msg: OutboundSms) -> str:
        self.sent.append(msg)
        log.info("sms_fake_sent", provider=self.name, to=mask_phone(msg.to), template=msg.template_key)
        return f"sms-{len(self.sent)}"


class SesEmailAdapter:
    """Amazon SES v2 ``SendEmail`` (simple content). boto3 runs in a worker thread.

    Unverified against a live account (COM-06). Errors propagate to ``send_email``, which logs
    and reports the delivery as failed without failing the business transaction."""

    name = "ses"

    def __init__(self, client: Any = None) -> None:
        s = get_settings()
        self.from_address = s.EMAIL_FROM_ADDRESS or _env("EMAIL_FROM_ADDRESS", "")
        self.from_name = s.EMAIL_FROM_NAME or "Tech Drona"
        self.region = s.AWS_REGION or _env("AWS_REGION", "ap-south-1")
        self.configuration_set = s.SES_CONFIGURATION_SET_TRANSACTIONAL
        self._client = client

    def _sesv2(self) -> Any:
        if self._client is None:
            import boto3

            self._client = boto3.client("sesv2", region_name=self.region)
        return self._client

    def request(self, msg: OutboundEmail) -> dict[str, Any]:
        req: dict[str, Any] = {
            "FromEmailAddress": formataddr((self.from_name, self.from_address)),
            "Destination": {"ToAddresses": [msg.to]},
            "Content": {
                "Simple": {
                    "Subject": {"Data": msg.subject, "Charset": "UTF-8"},
                    "Body": {"Text": {"Data": msg.text, "Charset": "UTF-8"}},
                }
            },
            "EmailTags": [
                {"Name": "template", "Value": _tag(msg.template_key)},
                {"Name": "category", "Value": _tag(msg.category)},
            ],
        }
        if self.configuration_set:
            req["ConfigurationSetName"] = self.configuration_set
        return req

    async def send(self, msg: OutboundEmail) -> str:
        client = self._sesv2()
        resp = await asyncio.to_thread(client.send_email, **self.request(msg))
        mid = str(resp.get("MessageId", ""))
        log.info("email_sent", provider="ses", to=mask_email(msg.to), template=msg.template_key)
        return mid


def _tag(value: str) -> str:
    """SES tag values allow ASCII letters, digits and ``_ - . @`` (max 256 characters)."""
    return "".join(c if c.isalnum() or c in "_-.@" else "_" for c in value)[:256] or "none"


class Msg91Error(RuntimeError):
    pass


class Msg91SmsAdapter:
    """MSG91 Flow API v5 (``POST {MSG91_BASE_URL}/flow``, header ``authkey``).

    India requires DLT-registered templates: each ``template_key`` maps to a MSG91 flow
    template id and only the template variables are sent. OTP templates carry the code as
    ``##otp##``; notice templates carry the text as ``##message##``. Unverified against a live
    account (COM-06)."""

    name = "msg91"
    OTP_KEYS = frozenset({"otp", "attempt_rebind_otp"})

    def __init__(self, transport: httpx.AsyncBaseTransport | None = None) -> None:
        s = get_settings()
        self.base_url = s.MSG91_BASE_URL.rstrip("/")
        self.auth_key = s.MSG91_AUTH_KEY
        self.sender_id = s.MSG91_SENDER_ID
        self.dlt_entity_id = s.MSG91_DLT_ENTITY_ID
        self.templates = {
            "otp": s.MSG91_TEMPLATE_ID_OTP,
            "attempt_rebind_otp": s.MSG91_TEMPLATE_ID_OTP,
            "payment": s.MSG91_TEMPLATE_ID_PAYMENT,
        }
        self.security_template = s.MSG91_TEMPLATE_ID_SECURITY_NOTICE
        self._transport = transport

    def template_for(self, template_key: str) -> str:
        tid = self.templates.get(template_key) or (
            self.security_template if template_key.startswith(("security", "auth", "session")) else ""
        )
        if not tid:
            raise Msg91Error(f"no DLT template configured for {template_key!r}")
        return tid

    def payload(self, msg: OutboundSms) -> dict[str, Any]:
        recipient: dict[str, str] = {"mobiles": msg.to.lstrip("+")}
        if msg.template_key in self.OTP_KEYS:
            m = _OTP_RE.search(msg.text)
            if not m:
                raise Msg91Error("OTP message without a code")
            recipient["otp"] = m.group(1)
        else:
            recipient["message"] = msg.text[:160]
        body: dict[str, Any] = {
            "template_id": self.template_for(msg.template_key),
            "short_url": "0",
            "recipients": [recipient],
        }
        if self.sender_id:
            body["sender"] = self.sender_id
        if self.dlt_entity_id:
            body["DLT_TE_ID"] = self.dlt_entity_id
        return body

    async def send(self, msg: OutboundSms) -> str:
        if not self.auth_key:
            raise Msg91Error("MSG91_AUTH_KEY is not configured")
        async with httpx.AsyncClient(timeout=10, transport=self._transport) as client:
            r = await client.post(
                f"{self.base_url}/flow",
                json=self.payload(msg),
                headers={"authkey": self.auth_key, "accept": "application/json"},
            )
        data = r.json() if r.content else {}
        if r.status_code >= 400 or str(data.get("type", "")).lower() == "error":
            raise Msg91Error(f"msg91 rejected the request (HTTP {r.status_code})")
        log.info("sms_sent", provider="msg91", to=mask_phone(msg.to), template=msg.template_key)
        return str(data.get("message") or data.get("request_id") or "")


_OTP_RE = re.compile(r"\b(\d{4,10})\b")


class UnavailableAdapter:
    def __init__(self, name: str) -> None:
        self.name = name

    async def send(self, msg: object) -> str:
        raise RuntimeError(f"{self.name} adapter is not implemented yet (Planned)")


_email: EmailAdapter | None = None
_sms: SmsAdapter | None = None


def get_email_adapter() -> EmailAdapter:
    global _email
    if _email is None:
        provider = get_settings().EMAIL_PROVIDER.lower()
        if provider == "smtp":
            _email = SmtpEmailAdapter()
        elif provider == "ses":
            _email = SesEmailAdapter()
        elif provider in {"fake", "console", "memory"}:
            _email = MemoryEmailAdapter()
        else:
            _email = UnavailableAdapter(f"email:{provider}")
    return _email


def get_sms_adapter() -> SmsAdapter:
    global _sms
    if _sms is None:
        provider = get_settings().SMS_PROVIDER.lower()
        if provider in {"console", "fake"}:
            _sms = ConsoleSmsAdapter()
        elif provider == "msg91":
            _sms = Msg91SmsAdapter()
        else:
            _sms = UnavailableAdapter(f"sms:{provider}")
    return _sms


def set_email_adapter(adapter: EmailAdapter | None) -> None:
    global _email
    _email = adapter


def set_sms_adapter(adapter: SmsAdapter | None) -> None:
    global _sms
    _sms = adapter


def _smtp_is_local_dev(s: Settings) -> bool:
    if s.EMAIL_PROVIDER.lower() != "smtp":
        return False
    return _env("SMTP_HOST", "localhost").lower() in {"localhost", "127.0.0.1", "mailpit"}


register_fake_adapter("email (SMTP to local Mailpit)", _smtp_is_local_dev)
