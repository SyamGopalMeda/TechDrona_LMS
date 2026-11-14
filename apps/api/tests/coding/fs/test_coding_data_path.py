"""Coding data path on Firestore: mappers, backfill -> verify (no Postgres), encrypted blob store."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from app.core.firestore.repository import assert_repository_scoped
from app.core.ids import uuid7
from app.modules.coding import models as cm
from tests.placement.fs.backfill_helper import backfill_and_verify, fake_rows, sample_row

MODELS = [
    cm.JudgeLanguage,
    cm.CodingProblem,
    cm.CodingTestCase,
    cm.CodingTestCaseBlob,
    cm.CodingReferenceSolution,
    cm.CodingProblemValidation,
    cm.CodingDraft,
    cm.CodeSubmission,
    cm.SubmissionResult,
    cm.CodingTestCaseContentToken,
]


@pytest.mark.parametrize("model", MODELS, ids=lambda m: m.__tablename__)
def test_mapper_round_trip_keeps_model_values(model: Any) -> None:
    from app.modules.coding.store_specs import orm_doc, orm_of, row_doc

    row = sample_row(model)
    doc = row_doc(model, row)
    json.dumps(doc, default=str)
    assert not any(isinstance(v, (Decimal, bytes)) for v in doc.values())
    back = orm_of(model, doc)
    for c in model.__table__.columns:
        assert getattr(back, c.key) == row[c.key] or str(getattr(back, c.key)) == str(row[c.key]), c.key
    assert orm_doc(back) == doc


def test_fsmap_copies_are_identical() -> None:
    root = Path(__file__).resolve().parents[3] / "app/modules"
    body = [
        (root / m / "fsmap.py").read_text(encoding="utf-8").split('"""', 2)[2]
        for m in ("placement", "coding")
    ]
    assert body[0] == body[1]


async def test_backfill_verify_with_key_documents(coding_fs: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.firestore.store import ScopedStore
    from app.modules.coding.store_specs import DRAFTS, PROBLEMS_BY_SLUG, TOKENS, slug_id

    tables: dict[str, list[dict[str, Any]]] = {m.__tablename__: [sample_row(m)] for m in MODELS}
    p = sample_row(cm.CodingProblem, organization_id=None, slug="Two-Sum")
    tables["coding_problems"] = [p]
    tables["code_submissions"].append(sample_row(cm.CodeSubmission, idempotency_key=None))
    fake_rows(monkeypatch, tables)
    reports = {r.collection: r for r in await backfill_and_verify("coding", coding_fs)}
    bad = [r.as_dict() for r in reports.values() if not r.ok]
    assert not bad, bad
    assert reports["code_submissions_idem"].fs_docs == 1
    st = ScopedStore.system("test.read", client=coding_fs)
    assert (await st.get(PROBLEMS_BY_SLUG, slug_id(None, "two-sum")))["problem_id"] == str(p["id"])
    tok = tables["coding_testcase_content_tokens"][0]
    assert await st.get(TOKENS, bytes(tok["token_hash"]).hex()) is not None
    d = tables["coding_drafts"][0]
    from app.core.firestore.ids import compose_id

    assert await st.get(DRAFTS, compose_id(str(d["user_id"]), str(d["coding_problem_id"]), d["language_key"]))


def test_blob_over_the_chunk_cap_is_refused() -> None:
    from app.modules.coding.store_specs import MAX_BLOB_BYTES, MAX_CHUNKS, blob_doc

    assert blob_doc(sample_row(cm.CodingTestCaseBlob, ciphertext=b"x" * (MAX_BLOB_BYTES + 1)))["chunks"] == 2
    with pytest.raises(ValueError):
        blob_doc(sample_row(cm.CodingTestCaseBlob, ciphertext=b"x" * (MAX_BLOB_BYTES * MAX_CHUNKS + 1)))


async def test_large_blob_chunked_store_and_backfill(coding_fs: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """A 2 MB sealed case: blobstore splits it into chunk documents and reads the same bytes back;
    the backfill writes the same layout and verifies clean."""
    from app.modules.coding import blobstore
    from app.modules.coding.crypto import open_case, seal_case
    from app.modules.coding.store_specs import chunk_rows_of

    pid = uuid7()
    big_in = "7 " * 1_000_000
    sealed = seal_case(pid, big_in, "ok.")
    assert len(sealed.input_blob) > 2 * 750_000
    key = await blobstore.put_blob(None, problem_id=pid, organization_id=None, ciphertext=sealed.input_blob)  # type: ignore[arg-type]
    k2 = await blobstore.put_blob(None, problem_id=pid, organization_id=None, ciphertext=sealed.expected_blob)  # type: ignore[arg-type]
    got = await blobstore.get_blob(None, key)  # type: ignore[arg-type]
    assert got == sealed.input_blob
    assert open_case(pid, sealed.wrapped_data_key, got, await blobstore.get_blob(None, k2))[0] == big_in  # type: ignore[arg-type]
    # backfill of a big Postgres row -> head + chunks, verify clean, readable through blobstore
    row = sample_row(cm.CodingTestCaseBlob, ciphertext=sealed.input_blob)
    tables: dict[str, list[dict[str, Any]]] = {
        "coding_test_case_blobs": [row],
        "coding_test_case_blob_chunks": chunk_rows_of([row]),
    }
    fake_rows(monkeypatch, tables)
    import os

    from tests.firestore.conftest import clear_emulator

    clear_emulator(os.environ["FIRESTORE_EMULATOR_HOST"])  # backfill starts from an empty store
    reports = {r.collection: r for r in await backfill_and_verify("coding", coding_fs)}
    assert reports["coding_test_case_blob_chunks"].fs_docs == 3 and reports["coding_test_case_blobs"].ok
    assert all(r.ok for r in reports.values()), [r.as_dict() for r in reports.values() if not r.ok]
    assert await blobstore.get_blob(None, f"db:blob/{row['id']}") == sealed.input_blob  # type: ignore[arg-type]


async def test_encrypted_blob_store_on_firestore(coding_fs: Any) -> None:
    """Sealed hidden case -> blobstore (Firestore) -> same ciphertext -> decrypts with the same key."""
    from app.modules.coding import blobstore
    from app.modules.coding.crypto import open_case, seal_case
    from app.modules.coding.repo_firestore import CodingBlobRepo

    assert_repository_scoped(CodingBlobRepo)
    pid = uuid7()
    sealed = seal_case(pid, "1 2\n", "3\n")
    k_in = await blobstore.put_blob(None, problem_id=pid, organization_id=None, ciphertext=sealed.input_blob)  # type: ignore[arg-type]
    k_ex = await blobstore.put_blob(
        None, problem_id=pid, organization_id=None, ciphertext=sealed.expected_blob
    )  # type: ignore[arg-type]
    assert k_in.startswith("db:blob/")
    got_in = await blobstore.get_blob(None, k_in)  # type: ignore[arg-type]
    got_ex = await blobstore.get_blob(None, k_ex)  # type: ignore[arg-type]
    assert got_in == sealed.input_blob
    assert open_case(pid, sealed.wrapped_data_key, got_in, got_ex) == ("1 2\n", "3\n")
    with pytest.raises(blobstore.BlobNotFound):
        await blobstore.get_blob(None, f"db:blob/{uuid7()}")  # type: ignore[arg-type]


def test_index_fragment_is_valid() -> None:
    frag = Path(__file__).resolve().parents[3] / "app/modules/coding/firestore.indexes.fragment.json"
    data = json.loads(frag.read_text(encoding="utf-8"))
    assert data["indexes"] and all(i["collectionGroup"].startswith("lms_") for i in data["indexes"])


async def test_submission_idempotency_and_conditional_update(coding_fs: Any) -> None:
    from app.core.firestore.store import ScopedStore
    from app.modules.coding.repo_firestore import SYSTEM_VIEW, CodingRepo

    assert_repository_scoped(CodingRepo)
    r = CodingRepo(ScopedStore.system("test.coding"), SYSTEM_VIEW)
    u = uuid7()

    def sub() -> Any:
        return cm.CodeSubmission(
            **sample_row(
                cm.CodeSubmission,
                user_id=u,
                organization_id=None,
                status="queued",
                idempotency_key="submit:k1",
                mode="submit",
            )
        )

    import asyncio

    out = await asyncio.gather(*[r.create_submission(u, sub()) for _ in range(4)])
    assert sum(1 for _s, created in out if created) == 1 and len({s.id for s, _ in out}) == 1
    sid = out[0][0].id
    assert (await r.submission_by_idempotency(u, "submit:k1")).id == sid
    assert await r.update_submission(sid, {"status": "rejected"}, if_status="queued") is True
    assert await r.update_submission(sid, {"status": "rejected"}, if_status="queued") is False
    assert (await r.get_submission(sid)).status == "rejected"
