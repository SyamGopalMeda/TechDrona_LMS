"""Résumé service, Firestore path (``TD_STORE_MENTORING=firestore``).

``service.py`` dispatches here. Certificates (learning) and course titles (catalog) are the same
calls as on Postgres; the JSON shapes come from ``service.py``'s serializers.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ProblemError
from app.core.ids import uuid7
from app.core.principal import Principal
from app.core.time import utcnow
from app.modules.mentoring import service as pg
from app.modules.mentoring.models import Resume
from app.modules.mentoring.repo_firestore import MentoringRepo
from app.modules.mentoring.repo_firestore import repo as _repo
from app.modules.mentoring.schemas import ResumeIn


def repo() -> MentoringRepo:
    return _repo("mentoring.service")


# =========================================================================== résumés


async def list_resumes(session: AsyncSession, principal: Principal) -> dict[str, Any]:
    rows = await repo().resumes_of(principal.user_id, 50)
    return {
        "data": [pg.resume_json(r) for r in rows],
        "suggested_certifications": await pg._suggested_certifications(session, principal),
    }


async def new_version(principal: Principal, body: ResumeIn, rid: uuid.UUID | None = None) -> Resume:
    content = body.content.model_dump(mode="json")
    score, _ = pg.checklist(content)
    r = Resume(
        id=rid or uuid7(),
        user_id=principal.user_id,
        template_key=body.template_key,
        version_no=1,
        content=content,
        checklist_score=score,
        pdf_s3_key=None,
        pdf_pending_key=None,
        pdf_uploaded_at=None,
        is_current=True,
        created_at=utcnow(),
    )
    return await repo().new_version(principal.user_id, r)


async def own_resume(principal: Principal, rid: uuid.UUID) -> Resume:
    r = await repo().get_resume(rid)
    if r is None or r.user_id != principal.user_id:
        raise ProblemError("not_found")
    return r


async def save_resume(
    session: AsyncSession, principal: Principal, rid: uuid.UUID, body: ResumeIn
) -> tuple[dict[str, Any], bool]:
    r = await repo().get_resume(rid)
    if r is None:
        return pg.resume_json(await new_version(principal, body, rid)), True
    if r.user_id != principal.user_id:
        raise ProblemError("not_found")
    content = body.content.model_dump(mode="json")
    r = await repo().update_resume(
        principal.user_id,
        rid,
        {"content": content, "template_key": body.template_key, "checklist_score": pg.checklist(content)[0]},
    )
    return pg.resume_json(r), False


async def set_pdf_pending(principal: Principal, rid: uuid.UUID, key: str) -> None:
    await repo().update_resume(principal.user_id, rid, {"pdf_pending_key": key})


async def pdf_complete(
    session: AsyncSession, principal: Principal, rid: uuid.UUID, key: str
) -> dict[str, Any]:
    await own_resume(principal, rid)
    r = await repo().complete_pdf(principal.user_id, rid, key, utcnow())
    return pg.resume_json(r)


async def erase_user(user_id: uuid.UUID) -> dict[str, Any]:
    return await _repo("mentoring.erasure").erase_user(user_id)
