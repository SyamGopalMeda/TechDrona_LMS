"""Public API of paths for other modules (Firestore migration).

No other module reads or writes the paths tables (paths, versions, steps, allocations, articles,
step progress). The only cross-module entry point is the outbox wiring (``app/wiring.py``), which
registers the handlers that complete assignment / assessment steps from learning and assessments
events. Those handlers run on either store (``TD_STORE_PATHS``).
"""

from __future__ import annotations

from app.modules.paths.service import complete_from_evidence, embeddable, register_outbox_handlers

__all__ = ["complete_from_evidence", "embeddable", "register_outbox_handlers"]
