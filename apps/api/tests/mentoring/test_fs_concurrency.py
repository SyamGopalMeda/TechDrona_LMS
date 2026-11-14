"""Row-lock parity on Firestore (résumé PDF). Résumé versions are covered in ``test_fs_repo.py``
(transactional). Emulator only."""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

from tests.learning.fs_harness import firestore_emulator, fs  # noqa: F401
from tests.mentoring.test_fs_repo import _now


async def test_concurrent_pdf_complete_one_winner(fs: Any) -> None:  # noqa: F811
    from app.core.errors import ProblemError
    from app.modules.mentoring.models import Resume
    from app.modules.mentoring.repo_firestore import repo

    rp = repo()
    u = uuid.uuid4()
    r = await rp.new_version(u, Resume(id=uuid.uuid4(), user_id=u, template_key="ats_classic", version_no=1,
                                       content={}, checklist_score=0, is_current=True, created_at=_now()))  # fmt: skip
    await rp.update_resume(u, r.id, {"pdf_pending_key": "resumes/k1.pdf"})

    async def complete() -> str:
        try:
            return (await rp.complete_pdf(u, r.id, "resumes/k1.pdf", _now())).pdf_s3_key or ""
        except ProblemError as e:
            return e.code

    out = await asyncio.gather(*(complete() for _ in range(4)))
    # Postgres: FOR UPDATE serialises them; the first promotes the key, the rest see no pending key
    assert out.count("resumes/k1.pdf") == 1 and out.count("validation_failed") == 3
    with_other_user = await asyncio.gather(
        rp.complete_pdf(uuid.uuid4(), r.id, "x", _now()), return_exceptions=True
    )
    assert isinstance(with_other_user[0], ProblemError) and with_other_user[0].code == "not_found"
