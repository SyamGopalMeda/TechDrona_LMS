"""Security module router (auto-discovered) and hook registration.

Importing this module registers:

* ``sessions.hooks.register_restriction_lookup(restriction_state)`` — scope derivation for every
  authenticated request (blocked users cannot reach non-allowed routes through any API);
* ``sessions.hooks.register_security_events(SecurityEventSink())`` — signal ingestion;
* the dual-control executors in ``admin.approvals``.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.modules.security import api_engine, api_review, api_student
from app.modules.security.controls import register_handlers
from app.modules.security.restrictions import restriction_state
from app.modules.security.signals import SecurityEventSink
from app.modules.sessions.hooks import register_restriction_lookup, register_security_events


def install_hooks() -> None:
    register_restriction_lookup(restriction_state)
    register_security_events(SecurityEventSink())
    register_handlers()


install_hooks()

router = APIRouter()
router.include_router(api_student.r)
router.include_router(api_review.r)
router.include_router(api_engine.r)
