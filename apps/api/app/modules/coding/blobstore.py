"""Private ciphertext store for hidden test cases.

Phase-1 implementation keeps AES-GCM ciphertext in ``coding_test_case_blobs`` (Postgres,
RLS TN) under keys ``db:blob/<uuid>``. The S3 ``td-judge-private`` implementation (keys
``s3://…``) is Planned; the column names (``input_s3_key``/``expected_s3_key``) already
follow the target design. Only ciphertext ever goes in; plaintext never touches storage.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ids import uuid7
from app.modules.coding.models import CodingTestCaseBlob

PREFIX = "db:blob/"


class BlobNotFound(LookupError):
    pass


async def put_blob(
    session: AsyncSession, *, problem_id: uuid.UUID, organization_id: uuid.UUID | None, ciphertext: bytes
) -> str:
    blob_id = uuid7()
    session.add(
        CodingTestCaseBlob(
            id=blob_id, coding_problem_id=problem_id, organization_id=organization_id, ciphertext=ciphertext
        )
    )
    await session.flush()
    return f"{PREFIX}{blob_id}"


async def get_blob(session: AsyncSession, key: str) -> bytes:
    if not key.startswith(PREFIX):
        raise BlobNotFound(f"unsupported blob key scheme: {key.split(':', 1)[0]}")
    try:
        blob_id = uuid.UUID(key[len(PREFIX) :])
    except ValueError as e:
        raise BlobNotFound("malformed blob key") from e
    data = (
        await session.execute(select(CodingTestCaseBlob.ciphertext).where(CodingTestCaseBlob.id == blob_id))
    ).scalar_one_or_none()
    if data is None:
        raise BlobNotFound("blob not found")
    return bytes(data)
