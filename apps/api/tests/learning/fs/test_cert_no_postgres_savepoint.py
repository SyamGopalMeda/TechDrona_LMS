"""Regression (migration parity, cost-media sweep): certificate code wrapped steps in
``session.begin_nested()``. On the Firebase stack the request session is ``NO_POSTGRES``, where that
raised ``PostgresDisabledError``: LRN-33 ``issue_due`` answered 500 and the in-app certificate
notice (``_notify_in_app``) was silently dropped. ``certificates.savepoint`` keeps the savepoint
on SQL sessions and skips it on the no-Postgres placeholder."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any

import pytest

from app.core.audit import AuditActor
from app.core.db import NO_POSTGRES


async def test_issue_due_on_the_no_postgres_session(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.modules.learning import certificates as certs

    eid = uuid.uuid4()
    cert = SimpleNamespace(id=uuid.uuid4(), organization_id=None, user_id=uuid.uuid4(), public_code="ABC")
    queued: list[Any] = []

    async def due(session: Any, **kw: Any) -> list[dict[str, Any]]:
        return [{"enrolment_id": str(eid), "eligible": True, "reason": None}]

    async def get(session: Any, model: Any, pk: Any) -> Any:
        return SimpleNamespace(id=pk)

    async def issue(session: Any, enr: Any) -> Any:
        return cert

    async def queue(session: Any, c: Any, *, origin: str) -> None:
        queued.append((c.id, origin))

    async def aud(*a: Any, **k: Any) -> None:
        return None

    monkeypatch.setattr(certs, "due_enrolments", due)
    monkeypatch.setattr(certs.fss, "get", get)
    monkeypatch.setattr(certs.svc, "maybe_issue_certificate", issue)
    monkeypatch.setattr(certs, "queue_email", queue)
    monkeypatch.setattr(certs, "audit", aud)
    out = await certs.issue_due(NO_POSTGRES, AuditActor.system("test.certs"))
    assert out["issued"] == 1 and out["certificate_ids"] == [str(cert.id)]
    assert queued == [(cert.id, "batch_end")]


async def test_in_app_notice_is_sent_on_the_no_postgres_session(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.modules.learning import certificates as certs
    from app.modules.notifications import public as notifications

    sent: list[Any] = []

    async def notify(session: Any, user_id: Any, key: str, **kw: Any) -> None:
        sent.append((user_id, key, kw["dedupe_key"]))

    monkeypatch.setattr(notifications, "notify", notify)
    cert = SimpleNamespace(id=uuid.uuid4(), user_id=uuid.uuid4(), public_code="ABC")
    await certs._notify_in_app(NO_POSTGRES, cert, "Python")  # type: ignore[arg-type]
    assert sent == [(cert.user_id, certs.EMAIL_TEMPLATE_KEY, f"certificate:{cert.id}")]


def test_savepoint_is_kept_on_sql_sessions() -> None:
    from app.modules.learning import certificates as certs

    marker = object()
    sql = SimpleNamespace(begin_nested=lambda: marker)
    assert certs.savepoint(sql) is marker  # type: ignore[arg-type]
