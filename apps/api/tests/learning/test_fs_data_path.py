"""learning: Firestore data path (store_specs + fs_rows + backfill/verify), emulator only.

Runs without Postgres (see ``tests/learning/fs_harness.py``)."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import ARRAY, JSON, Boolean, Date, DateTime, Integer, LargeBinary, Numeric, SmallInteger, Text
from sqlalchemy.dialects.postgresql import REAL
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

from tests.learning.fs_harness import backfill_rows, firestore_emulator, fs  # noqa: F401

T0 = datetime(2026, 11, 1, 9, 30, 15, 123456, tzinfo=UTC)


def synthetic(model: Any, **over: Any) -> dict[str, Any]:
    """A full row of ``model`` as ``SELECT *`` returns it (Python types per column)."""
    row: dict[str, Any] = {}
    for i, c in enumerate(model.__table__.columns):
        t = c.type
        if isinstance(t, PG_UUID):
            v: Any = uuid.uuid4()
        elif isinstance(t, ARRAY):
            v = [uuid.uuid4()] if isinstance(t.item_type, PG_UUID) else ["pdf", "zip"]
        elif isinstance(t, JSON):
            v = {"k": [1, 2], "nested": [[0, 10], [20, 30]], "u": "x"}
        elif isinstance(t, DateTime):
            v = T0 + timedelta(minutes=i)
        elif isinstance(t, Date):
            v = date(2026, 11, 2)
        elif isinstance(t, Numeric):
            v = Decimal("12.50")
        elif isinstance(t, LargeBinary):
            v = b"\x00\xffhash"
        elif isinstance(t, Boolean):
            v = True
        elif isinstance(t, (Integer, SmallInteger)):
            v = 3
        elif isinstance(t, REAL):
            v = 0.75
        elif isinstance(t, Text):
            v = f"{c.name}-text"
        else:  # pragma: no cover
            raise AssertionError(f"no synthetic value for {c.name}: {t!r}")
        row[c.name] = v
    row.update(over)
    return row


def world() -> dict[str, list[dict[str, Any]]]:
    from app.modules.learning import models as m
    from app.modules.learning.cert_models import CertificateOutbox
    from app.modules.learning.doc_models import DocumentSettings, DocumentTemplate, IssuedDocument

    enr = synthetic(m.Enrolment, progress_pct=Decimal("33.33"), completed_at=None)
    enr2 = synthetic(m.Enrolment)
    prog = synthetic(
        m.LessonProgress, enrolment_id=enr["id"], watched_intervals=[[0, 15], [30, 45]], evidence=None
    )
    cert = synthetic(m.Certificate, enrolment_id=enr["id"], public_code="ABCDEFGHJK23")
    asg = synthetic(m.Assignment, rubric=None)
    sec = synthetic(m.AssignmentSection, assignment_id=asg["id"], max_score=None)
    item = synthetic(m.AssignmentItem, assignment_id=asg["id"], section_id=sec["id"])
    alloc = synthetic(m.AssignmentAllocation, assignment_id=asg["id"])
    sub = synthetic(m.AssignmentSubmission, assignment_id=asg["id"], attempt_no=1)
    resp = synthetic(
        m.AssignmentItemResponse, submission_id=sub["id"], item_id=item["id"], ai_criteria=[{"c": 1}]
    )
    rr_open = synthetic(m.AssignmentRegradeRequest, submission_id=sub["id"], status="open")
    rr_done = synthetic(m.AssignmentRegradeRequest, submission_id=sub["id"], status="resolved")
    doc1 = synthetic(
        IssuedDocument,
        ref_no="TD-OL-2026-ABCDEF",
        origin="enrolment",
        replaces_id=None,
        doc_type="offer_letter",
    )
    doc2 = synthetic(
        IssuedDocument, ref_no="TD-OL-2026-GHJKLM", origin="manual", replaces_id=doc1["id"], content_hash=None
    )
    ob1 = synthetic(CertificateOutbox, certificate_id=cert["id"], document_id=None)
    ob2 = synthetic(CertificateOutbox, certificate_id=None, document_id=doc1["id"], origin="enrolment")
    ob3 = synthetic(CertificateOutbox, certificate_id=None, document_id=doc1["id"], origin="resend")
    return {
        "enrolments": [enr, enr2],
        "lesson_progress": [prog],
        "certificates": [cert],
        "certificate_outbox": [ob1, ob2, ob3],
        "assignments": [asg],
        "assignment_sections": [sec],
        "assignment_items": [item],
        "assignment_allocations": [alloc],
        "assignment_submissions": [sub],
        "assignment_item_responses": [resp],
        "assignment_regrade_requests": [rr_open, rr_done],
        "issued_documents": [doc1, doc2],
        "document_templates": [synthetic(DocumentTemplate, kind="document", template_key="offer_letter")],
        "document_settings": [synthetic(DocumentSettings, id=1)],
    }


async def test_backfill_verify_every_collection(fs: Any, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    from app.modules.learning.store_specs import COLLECTIONS

    reports = await backfill_rows(monkeypatch, "learning", world(), fs)
    by = {r.collection: r for r in reports}
    assert set(by) == set(COLLECTIONS)
    bad = [r.as_dict() for r in reports if not r.ok]
    assert not bad, bad
    assert by["enrolments"].fs_docs == 2
    assert by["regrade_open"].fs_docs == 1  # partial unique: open requests only
    assert by["certificate_outbox_keys"].fs_docs == 2  # cert key + enrolment-auto document key
    assert by["issued_document_keys"].fs_docs == 4  # 2 ref_no + 1 replaces + 1 enrolment-auto


async def test_documents_round_trip_to_orm(fs: Any, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    from app.core.firestore.store import ScopedStore
    from app.modules.learning import models as m
    from app.modules.learning import store_specs as ss
    from app.modules.learning.doc_models import IssuedDocument
    from app.modules.learning.fs_rows import orm_of

    w = world()
    await backfill_rows(monkeypatch, "learning", w, fs)
    st = ScopedStore.system("learning.test")
    cases = [
        (m.Enrolment, ss.ENROLMENTS, w["enrolments"][0], str(w["enrolments"][0]["id"])),
        (
            m.LessonProgress,
            ss.PROGRESS,
            w["lesson_progress"][0],
            ss.progress_id(w["lesson_progress"][0]["enrolment_id"], w["lesson_progress"][0]["lesson_key"]),
        ),
        (m.Certificate, ss.CERTIFICATES, w["certificates"][0], str(w["certificates"][0]["id"])),
        (
            m.AssignmentAllocation,
            ss.ALLOCATIONS,
            w["assignment_allocations"][0],
            str(w["assignment_allocations"][0]["id"]),
        ),
        (
            m.AssignmentItemResponse,
            ss.RESPONSES,
            w["assignment_item_responses"][0],
            str(w["assignment_item_responses"][0]["id"]),
        ),
        (IssuedDocument, ss.DOCUMENTS, w["issued_documents"][0], str(w["issued_documents"][0]["id"])),
    ]
    for model, coll, row, doc_id in cases:
        d = await st.get(coll, doc_id)
        assert d is not None, coll
        obj = orm_of(model, d.data)
        for c in model.__table__.columns:
            assert getattr(obj, c.key) == row[c.name], (coll, c.key, getattr(obj, c.key), row[c.name])
    # Firestore forbids nested arrays: watched_intervals is wrapped in the document, unwrapped on read
    raw = await st.get(ss.PROGRESS, cases[1][3])
    assert raw is not None and raw["watched_intervals"] == [{"$l": [0, 15]}, {"$l": [30, 45]}]
    # array-contains replaces the GIN index on allocation user_ids
    uid = str(w["assignment_allocations"][0]["user_ids"][0])
    page = await st.query(ss.ALLOCATIONS, filters=(("user_ids", "array-contains", uid),), order_by=())
    assert [x.id for x in page.items] == [str(w["assignment_allocations"][0]["id"])]


async def test_uniqueness_key_documents(fs: Any, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    from app.core.firestore.errors import UniqueViolationError
    from app.core.firestore.store import ScopedStore
    from app.modules.learning import store_specs as ss

    w = world()
    await backfill_rows(monkeypatch, "learning", w, fs)
    st = ScopedStore.system("learning.test")
    e = w["enrolments"][0]
    key = await st.get(ss.ENROLMENT_KEYS, ss.enrolment_key(e["user_id"], e["course_id"]))
    assert key is not None and key["enrolment_id"] == str(e["id"])
    with pytest.raises(UniqueViolationError):  # a second enrolment of the same user in the course
        await st.create(ss.ENROLMENT_KEYS, {"enrolment_id": str(uuid.uuid4())}, doc_id=key.id)
    assert (await st.get(ss.CERT_CODES, "ABCDEFGHJK23")) is not None
    assert (await st.get(ss.CERT_BY_ENROLMENT, str(e["id"]))) is not None


async def test_verify_detects_drift(fs: Any, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    from app.core.firestore import backfill as bf
    from app.core.firestore.store import ScopedStore
    from app.modules.learning import store_specs as ss

    w = world()
    await backfill_rows(monkeypatch, "learning", w, fs)
    st = ScopedStore.system("firestore.backfill")
    eid = str(w["enrolments"][0]["id"])
    await st.import_documents(
        ss.ENROLMENTS, [(eid, {**(await st.get(ss.ENROLMENTS, eid)).data, "status": "x"})]
    )  # type: ignore[union-attr]
    await st.import_documents(ss.CERT_CODES, [("ZZZZZZZZZZ22", {"certificate_id": "x"})])
    reps = {r.collection: r for r in await bf.verify(None, "learning", client=fs)}  # type: ignore[arg-type]
    assert reps["enrolments"].mismatched == [eid] and not reps["enrolments"].ok
    assert reps["certificate_codes"].extra == ["ZZZZZZZZZZ22"]
    assert reps["assignments"].ok


def test_index_fragment_is_valid() -> None:
    p = (
        Path(__file__).resolve().parents[2]
        / "app"
        / "modules"
        / "learning"
        / "firestore.indexes.fragment.json"
    )
    data = json.loads(p.read_text(encoding="utf-8"))
    groups = {i["collectionGroup"] for i in data["indexes"]}
    assert all(g.startswith("lms_") for g in groups)
    assert {"lms_enrolments", "lms_certificates", "lms_assignment_submissions"} <= groups


def test_collections_registered_with_families() -> None:
    from app.core.firestore.collections import get_spec
    from app.modules.learning import store_specs as ss

    assert get_spec(ss.ENROLMENTS).family == "owned"
    assert get_spec(ss.ASSIGNMENTS).family == "shared"
    assert get_spec(ss.DOCUMENTS).family == "system"  # user_id is optional (recipients without accounts)
