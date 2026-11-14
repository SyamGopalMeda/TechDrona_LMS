"""Admissions routers (auto-included under /api/v1) + outbox handlers + the larger body limit of
the public and signed-in student upload routes (JSON with base64 files; everything else keeps
the 256 KiB default)."""

from __future__ import annotations

from fastapi import APIRouter

from app.core.middleware import register_body_limit
from app.modules.admissions.admin import staff
from app.modules.admissions.notify import register_outbox_handlers
from app.modules.admissions.public import BODY_LIMIT, pub
from app.modules.admissions.student import BODY_LIMIT as ME_BODY_LIMIT
from app.modules.admissions.student import CLAIM_PATH, REGISTER_PATH, me

register_body_limit("/api/v1/public/admissions/registrations", BODY_LIMIT)
register_body_limit("/api/v1/public/admissions/claims", BODY_LIMIT)
register_body_limit(REGISTER_PATH, ME_BODY_LIMIT)
register_body_limit(CLAIM_PATH, ME_BODY_LIMIT)
register_outbox_handlers()

router = APIRouter()
for _r in (pub, me, staff):
    router.include_router(_r)
