"""Mentoring + résumé endpoints (api-spec §13.1 PLC-36..52 and mentor console additions).

Student (S = own data, premium placement package where noted):
  GET  /mentoring/slots                              PLC-36 (package)
  POST /mentoring/bookings                           PLC-37 (package + quota, Idempotency-Key required)
  POST /mentoring/bookings/{id}/reschedule           PLC-38 (>= 12 h before keeps the credit)
  POST /mentoring/bookings/{id}/cancel               PLC-39 (>= 12 h before credits back)
  GET  /me/mentoring/bookings                        PLC-40 (bookings + released feedback)
  GET  /me/resumes | POST /me/resumes                PLC-47 (+ create a new version)
  PUT  /me/resumes/{id}                              PLC-48
  POST /me/resumes/{id}/pdf-upload[/complete]        presigned S3 upload of a PDF (PLC-49 render: Planned)
  GET  /me/resumes/{id}/pdf                          presigned download
  POST /me/resumes/{id}/review-requests              PLC-50 (package + quota, Idempotency-Key required)
Mentor:
  GET/POST /mentor/slots, DELETE /mentor/slots/{id}  PLC-41/42 (mentor.slot.manage)
  GET /mentor/sessions, GET|PATCH /mentor/sessions/{id}   PLC-43 + session detail / meeting link
  POST /mentor/bookings/{id}/feedback                PLC-44 (mentor.feedback.write)
  POST /mentor/bookings/{id}/no-show                 PLC-45 (mentor.feedback.write)
  GET|POST /mentor/students/{user_id}/notes          private notes (read: mentor.notes.read; write:
                                                     mentor.feedback.write; assigned students only)
  GET /mentor/resume-reviews, POST .../{id}/feedback PLC-51/52 (mentor.feedback.write)
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse

from app.core.auth import require_active_principal
from app.core.db import PrincipalDbSession
from app.core.idempotency import IdemResult, idempotent
from app.core.pagination import DEFAULT_LIMIT, MAX_LIMIT
from app.core.principal import Principal
from app.core.routing import authenticated_router
from app.modules.mentoring import service as svc
from app.modules.mentoring.schemas import (
    BookIn,
    CancelIn,
    FeedbackIn,
    MeetingLinkIn,
    NoShowIn,
    NoteIn,
    PdfCompleteIn,
    PdfUploadIn,
    RescheduleIn,
    ResumeIn,
    ReviewFeedbackIn,
    ReviewRequestIn,
    SessionKind,
    SlotsIn,
)

stu = authenticated_router(tags=["mentoring"])
men = authenticated_router(prefix="/mentor", tags=["mentoring-mentor"])

Limit = Annotated[int, Query(ge=1, le=MAX_LIMIT)]
CurrentPrincipal = Annotated[Principal, Depends(require_active_principal)]
NEUTRAL = {"x-td-idle": "neutral"}


# --------------------------------------------------------------------------- student: mentoring


@stu.get("/mentoring/slots", openapi_extra=NEUTRAL)
async def plc_36_slots(
    session: PrincipalDbSession,
    principal: CurrentPrincipal,
    session_kind: SessionKind | None = None,
    from_: Annotated[datetime | None, Query(alias="from")] = None,
    cursor: str | None = None,
    limit: Limit = DEFAULT_LIMIT,
) -> dict[str, Any]:
    return await svc.list_open_slots(
        session, principal, session_kind=session_kind, after=from_, cursor=cursor, limit=limit
    )


@stu.post("/mentoring/bookings", status_code=201)
async def plc_37_book(
    body: BookIn, request: Request, session: PrincipalDbSession, principal: CurrentPrincipal
) -> JSONResponse:
    key = request.headers.get("Idempotency-Key") or ""

    async def op() -> IdemResult:
        out = await svc.book(session, principal, body.slot_id, key)
        return IdemResult(out, 201, uuid.UUID(out["id"]))

    return await idempotent(request, session, user_id=principal.user_id, operation=op)


@stu.post("/mentoring/bookings/{booking_id}/reschedule")
async def plc_38_reschedule(
    booking_id: uuid.UUID,
    body: RescheduleIn,
    request: Request,
    session: PrincipalDbSession,
    principal: CurrentPrincipal,
) -> JSONResponse:
    async def op() -> IdemResult:
        return IdemResult(await svc.reschedule(session, principal, booking_id, body.slot_id))

    return await idempotent(request, session, user_id=principal.user_id, operation=op, required=False)


@stu.post("/mentoring/bookings/{booking_id}/cancel")
async def plc_39_cancel(
    booking_id: uuid.UUID,
    request: Request,
    session: PrincipalDbSession,
    principal: CurrentPrincipal,
    body: CancelIn | None = None,
) -> JSONResponse:
    async def op() -> IdemResult:
        return IdemResult(await svc.cancel(session, principal, booking_id))

    return await idempotent(request, session, user_id=principal.user_id, operation=op, required=False)


@stu.get("/me/mentoring/bookings", openapi_extra=NEUTRAL)
async def plc_40_my_bookings(
    session: PrincipalDbSession,
    principal: CurrentPrincipal,
    cursor: str | None = None,
    limit: Limit = DEFAULT_LIMIT,
) -> dict[str, Any]:
    return await svc.my_bookings(session, principal, cursor=cursor, limit=limit)


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


@stu.post("/me/resumes/{resume_id}/review-requests", status_code=201)
async def plc_50_review_request(
    resume_id: uuid.UUID,
    request: Request,
    session: PrincipalDbSession,
    principal: CurrentPrincipal,
    body: ReviewRequestIn | None = None,
) -> JSONResponse:
    note = body.note if body else None

    async def op() -> IdemResult:
        out = await svc.request_review(session, principal, resume_id, note)
        return IdemResult(out, 201, uuid.UUID(out["id"]))

    return await idempotent(request, session, user_id=principal.user_id, operation=op)


# --------------------------------------------------------------------------- mentor: slots


@men.get("/slots", openapi_extra=NEUTRAL)
async def mentor_slots(
    request: Request,
    session: PrincipalDbSession,
    principal: CurrentPrincipal,
    from_: Annotated[datetime | None, Query(alias="from")] = None,
    to: datetime | None = None,
) -> dict[str, Any]:
    return {"data": await svc.list_mentor_slots(session, request, principal, after=from_, before=to)}


@men.post("/slots", status_code=201)
async def plc_41_publish_slots(
    body: SlotsIn, request: Request, session: PrincipalDbSession, principal: CurrentPrincipal
) -> JSONResponse:
    async def op() -> IdemResult:
        return IdemResult({"data": await svc.create_slots(session, request, principal, body)}, 201)

    return await idempotent(request, session, user_id=principal.user_id, operation=op, required=False)


@men.delete("/slots/{slot_id}")
async def plc_42_delete_slot(
    slot_id: uuid.UUID, request: Request, session: PrincipalDbSession, principal: CurrentPrincipal
) -> dict[str, Any]:
    return await svc.delete_slot(session, request, principal, slot_id)


# --------------------------------------------------------------------------- mentor: sessions


@men.get("/sessions", openapi_extra=NEUTRAL)
async def plc_43_sessions(
    request: Request,
    session: PrincipalDbSession,
    principal: CurrentPrincipal,
    view: Literal["upcoming", "pending_feedback", "past", "all"] = "upcoming",
    cursor: str | None = None,
    limit: Limit = DEFAULT_LIMIT,
) -> dict[str, Any]:
    return await svc.mentor_sessions(session, request, principal, view=view, cursor=cursor, limit=limit)


@men.get("/sessions/{booking_id}", openapi_extra=NEUTRAL)
async def mentor_session_detail(
    booking_id: uuid.UUID, request: Request, session: PrincipalDbSession, principal: CurrentPrincipal
) -> dict[str, Any]:
    return await svc.session_detail(session, request, principal, booking_id)


@men.patch("/sessions/{booking_id}")
async def mentor_session_link(
    booking_id: uuid.UUID,
    body: MeetingLinkIn,
    request: Request,
    session: PrincipalDbSession,
    principal: CurrentPrincipal,
) -> dict[str, Any]:
    url = str(body.meeting_url) if body.meeting_url is not None else None
    return await svc.set_meeting_link(session, request, principal, booking_id, url)


@men.post("/bookings/{booking_id}/feedback", status_code=201)
async def plc_44_feedback(
    booking_id: uuid.UUID,
    body: FeedbackIn,
    request: Request,
    session: PrincipalDbSession,
    principal: CurrentPrincipal,
) -> JSONResponse:
    async def op() -> IdemResult:
        return IdemResult(await svc.submit_feedback(session, request, principal, booking_id, body), 201)

    return await idempotent(request, session, user_id=principal.user_id, operation=op, required=False)


@men.post("/bookings/{booking_id}/no-show")
async def plc_45_no_show(
    booking_id: uuid.UUID,
    body: NoShowIn,
    request: Request,
    session: PrincipalDbSession,
    principal: CurrentPrincipal,
) -> JSONResponse:
    async def op() -> IdemResult:
        return IdemResult(await svc.mark_no_show(session, request, principal, booking_id, body.party))

    return await idempotent(request, session, user_id=principal.user_id, operation=op, required=False)


# --------------------------------------------------------------------------- mentor: notes


@men.get("/students/{user_id}/notes", openapi_extra=NEUTRAL)
async def mentor_notes(
    user_id: uuid.UUID, request: Request, session: PrincipalDbSession, principal: CurrentPrincipal
) -> dict[str, Any]:
    return {"data": await svc.list_notes(session, request, principal, user_id)}


@men.post("/students/{user_id}/notes", status_code=201)
async def mentor_add_note(
    user_id: uuid.UUID,
    body: NoteIn,
    request: Request,
    session: PrincipalDbSession,
    principal: CurrentPrincipal,
) -> dict[str, Any]:
    return await svc.add_note(session, request, principal, user_id, body.body, body.booking_id)


# --------------------------------------------------------------------------- mentor: résumé reviews


@men.get("/resume-reviews", openapi_extra=NEUTRAL)
async def plc_51_review_queue(
    request: Request,
    session: PrincipalDbSession,
    principal: CurrentPrincipal,
    status: Literal["open", "completed"] = "open",
) -> dict[str, Any]:
    return {"data": await svc.review_queue(session, request, principal, status)}


@men.post("/resume-reviews/{review_id}/feedback")
async def plc_52_review_feedback(
    review_id: uuid.UUID,
    body: ReviewFeedbackIn,
    request: Request,
    session: PrincipalDbSession,
    principal: CurrentPrincipal,
) -> JSONResponse:
    async def op() -> IdemResult:
        return IdemResult(await svc.review_feedback(session, request, principal, review_id, body))

    return await idempotent(request, session, user_id=principal.user_id, operation=op, required=False)


router = APIRouter()
for _r in (stu, men):
    router.include_router(_r)


# DB-01: register this module's erasure provider with admin privacy (import-time registration).
from app.modules.mentoring import privacy as _privacy  # noqa: E402

_privacy.register()
