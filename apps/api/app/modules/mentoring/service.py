"""Résumé builder business logic (api-spec PLC-47..49, FR-PLC-015).

The mentoring feature (slots, bookings, feedback, mentor notes, résumé reviews and their quotas)
was removed (docs/cleanup/feature-removal-plan.md §3.1); the package keeps its name as the résumé
home. Résumés are owner-only (``resumes`` RLS O on Postgres; ``owned`` with no staff read
permission on Firestore).
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import system_context, tenant_context
from app.core.errors import ProblemError
from app.core.firestore.backend import uses_firestore
from app.core.ids import uuid7
from app.core.principal import Principal
from app.core.time import utcnow
from app.modules.mentoring.models import Resume
from app.modules.mentoring.schemas import ResumeIn

PDF_MAX_BYTES = 5 * 1024 * 1024


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


@asynccontextmanager
async def as_system(session: AsyncSession, principal: Principal, job: str) -> AsyncIterator[None]:
    """Run a block under a named system context, flush, then restore the principal's. Without a
    Postgres session (Firebase stack) there is no RLS context to switch: the block just runs."""
    if not session:
        yield
        return
    await system_context(session, job)
    try:
        yield
        await session.flush()
    finally:
        await tenant_context(session, principal)


def _field_error(field: str, message: str, code: str = "invalid") -> ProblemError:
    return ProblemError("validation_failed", errors=[{"field": field, "code": code, "message": message}])


# --------------------------------------------------------------------------- résumés

CHECKLIST = (
    ("headline", "Add a one-line headline"),
    ("summary", "Write a summary of at least 50 characters"),
    ("education", "Add your education"),
    ("skills", "List at least 5 skills"),
    ("projects", "Describe at least one project"),
    ("internships", "Add an internship or work experience"),
    ("achievements", "Add an achievement"),
    ("certifications", "Add a certification"),
)


def checklist(content: dict[str, Any]) -> tuple[int, list[dict[str, Any]]]:
    done = {
        "headline": bool((content.get("headline") or "").strip()),
        "summary": len((content.get("summary") or "").strip()) >= 50,
        "education": bool(content.get("education")),
        "skills": len(content.get("skills") or []) >= 5,
        "projects": any((p.get("description") or "").strip() for p in content.get("projects") or []),
        "internships": bool(content.get("internships")),
        "achievements": bool(content.get("achievements")),
        "certifications": bool(content.get("certifications")),
    }
    items = [{"key": k, "label": label, "done": done[k]} for k, label in CHECKLIST]
    score = round(100 * sum(1 for i in items if i["done"]) / len(items))
    return score, items


def resume_json(r: Resume) -> dict[str, Any]:
    score, items = checklist(r.content)
    return {
        "id": str(r.id),
        "template_key": r.template_key,
        "version_no": r.version_no,
        "content": r.content,
        "checklist_score": r.checklist_score if r.checklist_score is not None else score,
        "checklist": items,
        "is_current": r.is_current,
        "has_pdf": r.pdf_s3_key is not None,
        "pdf_uploaded_at": _iso(r.pdf_uploaded_at),
        "created_at": _iso(r.created_at),
        "updated_at": _iso(r.updated_at),
    }


async def _suggested_certifications(session: AsyncSession, principal: Principal) -> list[dict[str, Any]]:
    """Tech Drona certificates of the caller (FR-PLC-015 auto-fill)."""
    from app.modules.catalog import public as catalog_api
    from app.modules.learning import public as learning_public

    async with as_system(session, principal, "mentoring.certificates"):
        certs = [
            (c.course_id, c.issued_at, c.public_code)
            for c in await learning_public.certificates_of_user(session, principal.user_id)
        ]
        courses = await catalog_api.get_courses(session, {r[0] for r in certs})
    # inner join on courses, then the old LIMIT 30
    rows = [(courses[cid].title, issued, code) for cid, issued, code in certs if cid in courses][:30]
    return [
        {"title": t, "issuer": "Tech Drona", "issued_on": issued.date().isoformat(), "credential_id": code}
        for t, issued, code in rows
    ]


async def list_resumes(session: AsyncSession, principal: Principal) -> dict[str, Any]:
    if uses_firestore("mentoring"):
        from app.modules.mentoring import service_fs

        return await service_fs.list_resumes(session, principal)
    rows = list(
        (
            await session.execute(
                select(Resume)
                .where(Resume.user_id == principal.user_id)
                .order_by(Resume.version_no.desc())
                .limit(50)
            )
        ).scalars()
    )
    return {
        "data": [resume_json(r) for r in rows],
        "suggested_certifications": await _suggested_certifications(session, principal),
    }


async def _new_version(
    session: AsyncSession, principal: Principal, body: ResumeIn, rid: uuid.UUID | None = None
) -> Resume:
    if uses_firestore("mentoring"):
        from app.modules.mentoring import service_fs

        return await service_fs.new_version(principal, body, rid)
    content = body.content.model_dump(mode="json")
    score, _ = checklist(content)
    last = (
        await session.execute(select(func.max(Resume.version_no)).where(Resume.user_id == principal.user_id))
    ).scalar_one()
    await session.execute(
        update(Resume).where(Resume.user_id == principal.user_id, Resume.is_current).values(is_current=False)
    )
    r = Resume(
        id=rid or uuid7(),
        user_id=principal.user_id,
        template_key=body.template_key,
        version_no=(last or 0) + 1,
        content=content,
        checklist_score=score,
        is_current=True,
    )
    session.add(r)
    await session.flush()
    await session.refresh(r)
    return r


async def create_resume(session: AsyncSession, principal: Principal, body: ResumeIn) -> dict[str, Any]:
    return resume_json(await _new_version(session, principal, body))


async def _own_resume(
    session: AsyncSession, principal: Principal, rid: uuid.UUID, *, lock: bool = False
) -> Resume:
    if uses_firestore("mentoring"):
        from app.modules.mentoring import service_fs

        return await service_fs.own_resume(principal, rid)
    q = select(Resume).where(Resume.id == rid, Resume.user_id == principal.user_id)
    r = (await session.execute(q.with_for_update() if lock else q)).scalar_one_or_none()
    if r is None:
        raise ProblemError("not_found")
    return r


async def save_resume(
    session: AsyncSession, principal: Principal, rid: uuid.UUID, body: ResumeIn
) -> tuple[dict[str, Any], bool]:
    """PLC-48 PUT: update an own résumé in place, or create it with the client-chosen id."""
    if uses_firestore("mentoring"):
        from app.modules.mentoring import service_fs

        return await service_fs.save_resume(session, principal, rid, body)
    r = (
        await session.execute(
            select(Resume).where(Resume.id == rid, Resume.user_id == principal.user_id).with_for_update()
        )
    ).scalar_one_or_none()
    if r is None:
        async with as_system(session, principal, "mentoring.resume_id_check"):
            taken = (await session.execute(select(Resume.id).where(Resume.id == rid))).scalar_one_or_none()
        if taken is not None:
            raise ProblemError("not_found")
        return resume_json(await _new_version(session, principal, body, rid)), True
    content = body.content.model_dump(mode="json")
    r.content = content
    r.template_key = body.template_key
    r.checklist_score = checklist(content)[0]
    await session.flush()
    await session.refresh(r)
    return resume_json(r), False


async def pdf_upload(
    session: AsyncSession, principal: Principal, rid: uuid.UUID, filename: str, size_bytes: int
) -> dict[str, Any]:
    from app.modules.media.public import presign_post, safe_filename, storage_settings

    r = await _own_resume(session, principal, rid, lock=True)
    base = safe_filename(filename)
    if not base.lower().endswith(".pdf"):
        base += ".pdf"
    key = f"resumes/{principal.user_id}/{r.id}/{uuid7()}-{base}"
    post = presign_post(
        storage_settings().S3_BUCKET_UPLOADS, key, content_type="application/pdf", max_bytes=PDF_MAX_BYTES
    )
    if uses_firestore("mentoring"):
        from app.modules.mentoring import service_fs

        await service_fs.set_pdf_pending(principal, r.id, key)
    else:
        r.pdf_pending_key = key
        await session.flush()
    return {
        "url": post.url,
        "fields": post.fields,
        "key": key,
        "expires_at": _iso(post.expires_at),
        "max_bytes": PDF_MAX_BYTES,
    }


async def pdf_complete(
    session: AsyncSession, principal: Principal, rid: uuid.UUID, key: str
) -> dict[str, Any]:
    if uses_firestore("mentoring"):
        from app.modules.mentoring import service_fs

        return await service_fs.pdf_complete(session, principal, rid, key)
    r = await _own_resume(session, principal, rid, lock=True)
    if not r.pdf_pending_key or key != r.pdf_pending_key:
        raise _field_error("key", "This upload was not started for this résumé.")
    r.pdf_s3_key = key
    r.pdf_pending_key = None
    r.pdf_uploaded_at = utcnow()
    await session.flush()
    await session.refresh(r)
    return resume_json(r)


async def pdf_download(session: AsyncSession, principal: Principal, rid: uuid.UUID) -> dict[str, Any]:
    from app.modules.media.public import presign_get, storage_settings

    r = await _own_resume(session, principal, rid)
    if not r.pdf_s3_key:
        raise ProblemError("not_found")
    url, exp = presign_get(
        storage_settings().S3_BUCKET_UPLOADS, r.pdf_s3_key, filename=f"resume-v{r.version_no}.pdf"
    )
    return {"url": url, "expires_at": _iso(exp)}
