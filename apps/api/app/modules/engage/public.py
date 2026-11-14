"""Public, store-neutral API of ``engage`` for other modules (``TD_STORE_ENGAGE``).

No module outside engage reads engage tables today; the dev seed creates activities through
:func:`create_activity`. Every function here dispatches to Firestore when the switch is on.
"""

from __future__ import annotations

from app.modules.engage.service import (
    activity_detail,
    create_activity,
    list_activities,
    my_runs,
)

__all__ = ["activity_detail", "create_activity", "list_activities", "my_runs"]
