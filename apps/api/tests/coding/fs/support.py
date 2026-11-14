"""Shared helpers for the coding Firestore tests (no Postgres)."""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

# The four languages ``coding_0001`` seeds (same ids and values).
LANGUAGES: list[dict[str, Any]] = [
    {"id": "0193f000-0000-7000-8000-000000000001", "language_key": "c", "display_name": "C", "pid": 50},
    {
        "id": "0193f000-0000-7000-8000-000000000002",
        "language_key": "cpp17",
        "display_name": "C++17",
        "pid": 54,
    },
    {
        "id": "0193f000-0000-7000-8000-000000000003",
        "language_key": "java17",
        "display_name": "Java",
        "pid": 62,
    },
    {
        "id": "0193f000-0000-7000-8000-000000000004",
        "language_key": "python3",
        "display_name": "Python 3",
        "pid": 71,
    },
]


async def seed_languages() -> None:
    from app.core.firestore.store import ScopedStore
    from app.core.time import utcnow
    from app.modules.coding.models import JudgeLanguage
    from app.modules.coding.store_specs import LANGUAGES as COLL
    from app.modules.coding.store_specs import row_doc

    docs = []
    for x in LANGUAGES:
        row = {
            "id": uuid.UUID(x["id"]),
            "language_key": x["language_key"],
            "display_name": x["display_name"],
            "version_label": None,
            "provider_language_id": x["pid"],
            "time_multiplier": Decimal("1.0"),
            "memory_extra_kb": 0,
            "max_processes": 64,
            "is_enabled": True,
            "starter_template": f"// {x['language_key']}\n",
            "updated_at": utcnow(),
        }
        docs.append((x["id"], row_doc(JudgeLanguage, row)))
    await ScopedStore.system("test.seed").import_documents(COLL, docs)
