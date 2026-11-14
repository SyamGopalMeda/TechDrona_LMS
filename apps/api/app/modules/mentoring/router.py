"""Résumé endpoints (api-spec §13.1 PLC-47..49). The package keeps its ``mentoring`` name: the
store switch ``TD_STORE_MENTORING``, ``core/firestore/backend.MODULES`` and the admin erasure
list depend on it. Mentoring sessions, slots, mentor notes and résumé reviews were removed
(docs/cleanup/feature-removal-plan.md §3.1).

Student (own data):
  GET  /me/resumes | POST /me/resumes                PLC-47 (+ create a new version)
  PUT  /me/resumes/{id}                              PLC-48
  POST /me/resumes/{id}/pdf-upload[/complete]        presigned S3 upload of a PDF (PLC-49 render: Planned)
  GET  /me/resumes/{id}/pdf                          presigned download
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from app.core.auth import require_active_principal
from app.core.db import PrincipalDbSession
from app.core.principal import Principal
from app.core.routing import authenticated_router
from app.modules.mentoring import service as svc
from app.modules.mentoring.schemas import PdfCompleteIn, PdfUploadIn, ResumeIn

stu = authenticated_router(tags=["mentoring"])

CurrentPrincipal = Annotated[Principal, Depends(require_active_principal)]
NEUTRAL = {"x-td-idle": "neutral"}


# --------------------------------------------------------------------------- student: résumés


@stu.get("/me/resumes", openapi_extra=NEUTRAL)
async def plc_47_resumes(session: PrincipalDbSession, principal: CurrentPrincipal) -> dict[str, Any]:
    return await svc.list_resumes(session, principal)


@stu.post("/me/resumes", status_code=201)
async def plc_47_create_resume(
    body: ResumeIn, session: PrincipalDbSession, principal: CurrentPrincipal
) -> dict[str, Any]:
    return await svc.create_resume(session, principal, body)


@stu.put("/me/resumes/{resume_id}")
async def plc_48_save_resume(
    resume_id: uuid.UUID, body: ResumeIn, session: PrincipalDbSession, principal: CurrentPrincipal
) -> JSONResponse:
    out, created = await svc.save_resume(session, principal, resume_id, body)
    return JSONResponse(out, status_code=201 if created else 200)


@stu.post("/me/resumes/{resume_id}/pdf-upload")
async def resume_pdf_upload(
    resume_id: uuid.UUID, body: PdfUploadIn, session: PrincipalDbSession, principal: CurrentPrincipal
) -> dict[str, Any]:
    return await svc.pdf_upload(session, principal, resume_id, body.filename, body.size_bytes)


@stu.post("/me/resumes/{resume_id}/pdf-upload/complete")
async def resume_pdf_complete(
    resume_id: uuid.UUID, body: PdfCompleteIn, session: PrincipalDbSession, principal: CurrentPrincipal
) -> dict[str, Any]:
    return await svc.pdf_complete(session, principal, resume_id, body.key)


@stu.get("/me/resumes/{resume_id}/pdf", openapi_extra=NEUTRAL)
async def resume_pdf_download(
    resume_id: uuid.UUID, session: PrincipalDbSession, principal: CurrentPrincipal
) -> dict[str, Any]:
    return await svc.pdf_download(session, principal, resume_id)


router = APIRouter()
router.include_router(stu)


# DB-01: register this module's erasure provider with admin privacy (import-time registration).
from app.modules.mentoring import privacy as _privacy  # noqa: E402

_privacy.register()
