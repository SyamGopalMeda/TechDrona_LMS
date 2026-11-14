"""Firestore data model of coding (``TD_STORE_CODING``; docs/firebase/agents/data-assess.md).

**Data path only**: collections, mappers, backfill, verify and indexes. No repository or
dispatch yet, so the switch must stay ``postgres``. The judge is untouched (fake/demo provider).

One document per row (``coding.fsmap``), physical names ``lms_<table>``:

* TN: ``coding_problems``, ``coding_test_cases``, ``coding_test_case_blobs``,
  ``coding_reference_solutions/{problem_id:language_key}`` (``ux_crs_problem_lang``),
  ``coding_problem_validations``. ``judge_languages`` is global (seeded by migrations).
* US (``user_id``): ``code_submissions``, ``submission_results/{submission_id:ordinal}``
  (``UNIQUE (code_submission_id, ordinal)``).
* O (``user_id``): ``coding_drafts/{user_id:problem_id:language_key}``
  (``ux_cd_user_problem_lang``), ``coding_testcase_content_tokens/{hex(token_hash)}``
  (``token_hash`` UNIQUE; a token lookup is one ``get``).

Encryption is unchanged: ``coding_test_case_blobs.ciphertext`` and
``coding_test_cases.wrapped_data_key`` are copied as the same encrypted bytes (base64 in the
document; decryption keeps using ``coding.crypto`` with the same key ring). A Firestore document
is at most 1 MiB, so a blob document holds at most ~750 KB of ciphertext; larger test data needs
larger ciphertext is split: the blob document keeps the metadata with ``chunks = n`` and an empty
``ciphertext``, and ``coding_test_case_blob_chunks/{blob_id:n}`` hold the pieces (written in one
transaction by ``repo_firestore.CodingBlobRepo``; the backfill writes the same layout). One
Firestore commit is at most 10 MiB, so a blob is capped at ``MAX_CHUNKS`` pieces (~9 MB); bigger
test data would need Cloud Storage (not needed for the current data).

Key documents:

* ``coding_problems_by_slug/{org|platform:slug}`` = ``{problem_id}`` (``ux_cp_slug``).
* ``code_submissions_idem/{user_id:idempotency_key}`` = ``{submission_id}``.
* The "one in-flight submission per user" advisory lock of ``service.submit`` becomes a lease
  on ``locks/coding_submit:{user_id}`` (``ScopedStore.claim_lease``), no stored data.
* ``UNIQUE (coding_problem_id, problem_version, ordinal)`` on test cases is kept by the authoring
  transaction that replaces a problem version's cases (no key document needed: cases are only
  written there).
"""

from __future__ import annotations

from typing import Any

from app.core.firestore.backfill import Row, TableMapping, register_mapping
from app.core.firestore.collections import CollectionSpec, register_collection
from app.core.firestore.ids import compose_id
from app.modules.coding.fsmap import orm_doc, orm_of, register_table, row_doc
from app.modules.coding.models import (
    CodeSubmission,
    CodingDraft,
    CodingProblem,
    CodingProblemValidation,
    CodingReferenceSolution,
    CodingTestCase,
    CodingTestCaseBlob,
    CodingTestCaseContentToken,
    JudgeLanguage,
    SubmissionResult,
)

M = "coding"

LANGUAGES = "judge_languages"
PROBLEMS = "coding_problems"
PROBLEMS_BY_SLUG = "coding_problems_by_slug"
CASES = "coding_test_cases"
BLOBS = "coding_test_case_blobs"
REF_SOLUTIONS = "coding_reference_solutions"
VALIDATIONS = "coding_problem_validations"
SUBMISSIONS = "code_submissions"
SUBMISSIONS_IDEM = "code_submissions_idem"
BLOB_CHUNKS = "coding_test_case_blob_chunks"
RESULTS = "submission_results"
DRAFTS = "coding_drafts"
TOKENS = "coding_testcase_content_tokens"

MAX_BLOB_BYTES = 750_000  # base64 (x4/3) + fields must stay under the 1 MiB document limit
MAX_CHUNKS = 12  # 12 x ~1 MiB documents stay under the 10 MiB commit limit

register_collection(CollectionSpec(LANGUAGES, "shared", read_permission=None, write_permission=None))
for _name in (PROBLEMS, PROBLEMS_BY_SLUG, CASES, REF_SOLUTIONS, VALIDATIONS):
    register_collection(
        CollectionSpec(_name, "shared", read_permission=None, write_permission="coding_problem.manage")
    )
# Blobs hold hidden test data (encrypted): only named jobs and holders of the hidden-read permission.
register_collection(
    CollectionSpec(
        BLOBS,
        "shared",
        read_permission="coding_test_case.hidden.read",
        write_permission="coding_problem.manage",
    )
)
for _name in (SUBMISSIONS, RESULTS):
    register_collection(
        CollectionSpec(
            _name, "owned", read_permission="test.results.read", write_permission="test.results.read"
        )
    )
for _name in (DRAFTS, TOKENS):
    register_collection(CollectionSpec(_name, "owned", read_permission=None, write_permission=None))
register_collection(CollectionSpec(SUBMISSIONS_IDEM, "system"))
register_collection(
    CollectionSpec(
        BLOB_CHUNKS,
        "shared",
        read_permission="coding_test_case.hidden.read",
        write_permission="coding_problem.manage",
    )
)


def chunk_id(blob_id: Any, n: int) -> str:
    return compose_id(str(blob_id), str(n))


def split_chunks(data: bytes) -> list[bytes]:
    parts = [data[i : i + MAX_BLOB_BYTES] for i in range(0, len(data), MAX_BLOB_BYTES)]
    if len(parts) > MAX_CHUNKS:
        raise ValueError("test case ciphertext larger than MAX_CHUNKS x MAX_BLOB_BYTES")
    return parts


def slug_id(organization_id: Any, slug: str) -> str:
    return compose_id(str(organization_id) if organization_id else "platform", str(slug).lower())


def blob_doc(r: Row) -> dict[str, Any]:
    data = bytes(r["ciphertext"])
    if len(data) <= MAX_BLOB_BYTES:
        return row_doc(CodingTestCaseBlob, r)
    return {**row_doc(CodingTestCaseBlob, {**r, "ciphertext": b""}), "chunks": len(split_chunks(data))}


async def _chunk_rows(session: Any) -> list[Row]:
    """Backfill loader: the pieces of every blob over ``MAX_BLOB_BYTES``."""
    from sqlalchemy import text

    res = await session.execute(
        text("SELECT * FROM coding_test_case_blobs WHERE octet_length(ciphertext) > :m ORDER BY id"),
        {"m": MAX_BLOB_BYTES},
    )
    out: list[Row] = []
    for r in res.mappings().all():
        for n, part in enumerate(split_chunks(bytes(r["ciphertext"]))):
            out.append({**dict(r), "ciphertext": part, "n": n})
    return out


def chunk_rows_of(blob_rows: list[Row]) -> list[Row]:
    """Same expansion as ``_chunk_rows`` for rows already in memory (tests)."""
    return [
        {**r, "ciphertext": part, "n": n}
        for r in blob_rows
        if len(bytes(r["ciphertext"])) > MAX_BLOB_BYTES
        for n, part in enumerate(split_chunks(bytes(r["ciphertext"])))
    ]


for _model in (JudgeLanguage, CodingProblem, CodingTestCase, CodingProblemValidation, CodeSubmission):
    register_table(M, _model)
register_mapping(TableMapping(M, "coding_test_case_blobs", BLOBS, lambda r: str(r["id"]), blob_doc))
register_mapping(
    TableMapping(
        M,
        "coding_test_case_blob_chunks",
        BLOB_CHUNKS,
        lambda r: chunk_id(r["id"], int(r["n"])),
        lambda r: {**row_doc(CodingTestCaseBlob, r), "n": int(r["n"])},
        loader=_chunk_rows,
    )
)
register_table(
    M, CodingReferenceSolution, doc_id=lambda r: compose_id(str(r["coding_problem_id"]), r["language_key"])
)
register_table(
    M, SubmissionResult, doc_id=lambda r: compose_id(str(r["code_submission_id"]), str(r["ordinal"]))
)
register_table(
    M,
    CodingDraft,
    doc_id=lambda r: compose_id(str(r["user_id"]), str(r["coding_problem_id"]), r["language_key"]),
)
register_table(M, CodingTestCaseContentToken, doc_id=lambda r: bytes(r["token_hash"]).hex())
register_mapping(
    TableMapping(
        M,
        "coding_problems",
        PROBLEMS_BY_SLUG,
        lambda r: slug_id(r["organization_id"], r["slug"]),
        lambda r: {"problem_id": str(r["id"])},
    )
)
register_mapping(
    TableMapping(
        M,
        "code_submissions",
        SUBMISSIONS_IDEM,
        lambda r: compose_id(str(r["user_id"]), r["idempotency_key"]),
        lambda r: {"submission_id": str(r["id"]), "user_id": str(r["user_id"])},
        where="idempotency_key IS NOT NULL",
    )
)

__all__ = ["orm_doc", "orm_of", "row_doc"]
