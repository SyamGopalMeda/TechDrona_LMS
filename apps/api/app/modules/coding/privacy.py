"""Erasure provider for coding (privacy s.8(7), DB-01): registered with
``admin.privacy.register_erasure_provider`` at import (``router.py`` imports this module).

Erased for the user: drafts (deleted), and the content of every submission: source code,
custom input, compiler output, the normalised hash used for plagiarism matching and the per-case
stdout excerpts. Kept in minimal form: submission rows with verdict/score/cases (they back test
scores and judge accounting). Idempotent.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import system_context

ERASED = "/* erased at the learner's request */"


async def erase_user(session: AsyncSession, user_id: uuid.UUID) -> dict[str, Any]:
    await system_context(session, "coding.privacy_erase")
    drafts = await session.execute(text("DELETE FROM coding_drafts WHERE user_id = :u"), {"u": user_id})
    subs = await session.execute(
        text(
            "UPDATE code_submissions SET source_code = :e, custom_input = NULL, compile_output = NULL, "
            "normalized_sha256 = NULL WHERE user_id = :u AND source_code <> :e"
        ),
        {"u": user_id, "e": ERASED},
    )
    outs = await session.execute(
        text(
            "UPDATE submission_results SET stdout_excerpt = NULL "
            "WHERE user_id = :u AND stdout_excerpt IS NOT NULL"
        ),
        {"u": user_id},
    )
    return {
        "coding_drafts_deleted": int(getattr(drafts, "rowcount", 0) or 0),
        "code_submissions_cleared": int(getattr(subs, "rowcount", 0) or 0),
        "submission_outputs_cleared": int(getattr(outs, "rowcount", 0) or 0),
    }


def register() -> None:
    from app.modules.admin.privacy import register_erasure_provider

    register_erasure_provider("coding", erase_user)


register()
