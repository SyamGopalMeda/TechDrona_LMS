"""Commerce billing approvals are all-or-nothing with the approval decision on Firestore: the
executor's engine commit joins the access undo journal (data-access.md §9)."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from typing import Any

import pytest

from app.core.ids import uuid7
from app.core.principal import Principal
from app.modules.commerce import datastore as ds
from app.modules.commerce.models import GstExport
from tests.commerce.firestore.conftest import FakeSession


async def _status(job_id: Any) -> str:
    return str((await ds.get(FakeSession().as_platform(), GstExport, job_id)).status)


async def test_gst_export_rejection_rolls_back_with_the_decision(fs: Any, session: Any) -> None:
    from app.modules.commerce import billing_approvals
    from app.modules.identity.fs_journal import journal

    job = GstExport(
        id=uuid7(),
        requested_by=uuid7(),
        period_from=date(2026, 4, 1),
        period_to=date(2026, 4, 30),
        status="awaiting_approval",
    )
    ds.add(session, job)
    await session.commit()
    req = SimpleNamespace(payload={"gst_export_id": str(job.id)})
    approver = Principal(user_id=uuid7(), session_id=uuid7(), is_platform=True)

    with pytest.raises(RuntimeError):
        async with journal():
            await billing_approvals._on_reject(None, approver, req)
            assert await _status(job.id) == "rejected"
            raise RuntimeError("approval.executed audit failed")
    assert await _status(job.id) == "awaiting_approval"

    async with journal():
        await billing_approvals._on_reject(None, approver, req)
    assert await _status(job.id) == "rejected"
