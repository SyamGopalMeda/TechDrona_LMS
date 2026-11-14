"""Public helpers requested by other agents, on Firestore with no Postgres:
``orgs.public.attendance_certificate_block`` (data-learning) and ``identity.public.web_base_url``."""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any

from app.core.firestore.store import ScopedStore
from app.modules.identity import public as ipub
from app.modules.identity.fs_codec import obj_doc
from app.modules.orgs import public as opub
from app.modules.orgs.models import Batch, BatchPlan, ClassAttendance, ClassSession
from app.modules.orgs.store_specs import attendance_id

S: Any = None
ORG = uuid.UUID("00000000-0000-0000-0000-00000000c0de")


async def _seed(minimum: int | None, marks: list[str], cancelled_index: int | None = None) -> tuple[Any, Any]:
    st = ScopedStore.system("test.seed")
    b = Batch(id=uuid.uuid4(), organization_id=ORG, name="B", code="b" + uuid.uuid4().hex[:6], status="active",
              created_by=uuid.uuid4())  # fmt: skip
    await st.import_documents("batches", [(str(b.id), obj_doc(b))])
    u = uuid.uuid4()
    if minimum is not None:
        plan = BatchPlan(batch_id=b.id, organization_id=ORG, plan={}, min_attendance_percent=minimum)
        await st.import_documents("batch_plans", [(str(b.id), obj_doc(plan))])
    for i, m in enumerate(marks):
        c = ClassSession(id=uuid.uuid4(), batch_id=b.id, organization_id=ORG, session_date=date(2026, 11, i + 1),
                         topic="t", cancelled=(i == cancelled_index), created_by=u)  # fmt: skip
        await st.import_documents("class_sessions", [(str(c.id), obj_doc(c))])
        a = ClassAttendance(id=uuid.uuid4(), session_id=c.id, batch_id=b.id, organization_id=ORG, user_id=u,
                            status=m, marked_by=u)  # fmt: skip
        await st.import_documents("class_attendance", [(attendance_id(c.id, u), obj_doc(a))])
    return b.id, u


async def test_attendance_certificate_block_on_firestore(fs: Any) -> None:
    # no plan / no minimum: never blocks
    bid, uid = await _seed(None, ["A", "A"])
    assert await opub.attendance_certificate_block(S, bid, uid) is None
    # 75% minimum, 1 of 3 live classes attended (the cancelled class's mark is ignored) -> blocked
    bid, uid = await _seed(75, ["P", "A", "A", "P"], cancelled_index=3)
    assert await opub.attendance_certificate_block(S, bid, uid) is not None
    # late counts as attended: 3 of 3 -> not blocked
    bid, uid = await _seed(75, ["P", "L", "P"])
    assert await opub.attendance_certificate_block(S, bid, uid) is None
    # a learner never marked is not blocked (website rule)
    assert await opub.attendance_certificate_block(S, bid, uuid.uuid4()) is None


def test_web_base_url() -> None:
    from app.modules.identity.links import web_base_url

    assert ipub.web_base_url() == web_base_url()
    assert ipub.web_link("forgot_password").startswith(ipub.web_base_url())


async def test_public_otp_functions(fs: Any) -> None:
    """``identity.public.create_otp / check_otp / otp_send_allowed`` (assessments' rebind flow)."""
    sid, uid = uuid.uuid4(), uuid.uuid4()
    assert await ipub.otp_send_allowed(S, "email", "r@x.in") == 0
    _tok, code = await ipub.create_otp(
        S, purpose="attempt_rebind", channel="email", destination="r@x.in", user_id=uid, auth_session_id=sid
    )
    bad = "000000" if code != "000000" else "111111"
    res = await ipub.check_otp(S, purpose="attempt_rebind", code=bad, user_id=uid, auth_session_id=sid)
    assert not res.ok and res.problem.code == "otp_invalid"
    res = await ipub.check_otp(S, purpose="attempt_rebind", code=code, user_id=uid, auth_session_id=sid)
    assert res.ok
    res = await ipub.check_otp(S, purpose="attempt_rebind", code=code, user_id=uid, auth_session_id=sid)
    assert not res.ok  # single use
