"""Paths data path on the emulator (no Postgres): the mappers' documents survive a Firestore round
trip with the same per-document hash ``verify`` computes, the embedded step trees keep their
order, decimals stay exact and progress ids are deterministic. (The Postgres-backed backfill ->
verify run is in the report's "not run" list: Postgres was down.)"""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

from app.core.ids import uuid7
from app.core.time import utcnow

API = Path(__file__).resolve().parents[3]


def _step(i: int, parent: Any = None) -> dict[str, Any]:
    return {
        "id": uuid7(),
        "path_id": None,
        "path_version_id": None,
        "organization_id": uuid7(),
        "step_key": uuid7(),
        "parent_key": parent,
        "position": i,
        "step_type": "lesson",
        "title": f"S{i}",
        "description_md": "",
        "est_hours": Decimal("1.50"),
        "credits": 2,
        "url": None,
        "lesson_id": uuid7(),
        "assignment_id": None,
        "test_id": None,
        "article_id": None,
        "created_at": utcnow(),
    }


async def test_documents_round_trip_with_verify_hashes(fs_client: Any) -> None:
    from app.core.firestore.backfill import doc_hash
    from app.core.firestore.store import ScopedStore
    from app.modules.paths.store_specs import (
        ALLOCATIONS,
        PATHS,
        PROGRESS,
        _embed,
        progress_id,
        row_doc,
    )

    now = utcnow()
    pid = uuid7()
    path = {
        "id": pid,
        "organization_id": uuid7(),
        "title": "P",
        "description_md": "",
        "level": "beginner",
        "status": "draft",
        "source": "manual",
        "version_no": 0,
        "current_version_id": None,
        "has_unpublished_changes": True,
        "created_by": uuid7(),
        "created_at": now,
        "updated_at": now,
    }
    root = _step(0)
    steps = [root | {"path_id": pid}, _step(0, root["step_key"]) | {"path_id": pid}]
    [pdoc] = [row_doc(r) for r in _embed([dict(path)], steps, "path_id", ("article_ids",))]
    assert [s["title"] for s in pdoc["steps"]] == ["S0", "S0"] and pdoc["steps"][0]["est_hours"] == "1.50"
    alloc = {
        "id": uuid7(),
        "organization_id": uuid7(),
        "path_id": pid,
        "path_version_id": uuid7(),
        "target_type": "users",
        "batch_id": None,
        "user_ids": [uuid7(), uuid7()],
        "flow": "self_paced",
        "sequential": False,
        "start_date": date(2026, 11, 1),
        "pace": {"mode": "weekly", "hours": Decimal("4.00")},
        "weekly_hours": Decimal("4.00"),
        "total_hours": Decimal("12.50"),
        "finish_date": date(2026, 12, 1),
        "status": "active",
        "created_by": uuid7(),
        "revoked_at": None,
        "created_at": now,
        "updated_at": now,
    }
    adoc = row_doc(alloc)
    assert adoc["start_date"] == "2026-11-01" and adoc["pace"]["hours"] == "4.00"
    prog = {
        "id": uuid7(),
        "allocation_id": alloc["id"],
        "organization_id": uuid7(),
        "user_id": alloc["user_ids"][0],
        "step_key": root["step_key"],
        "status": "completed",
        "opened_at": now,
        "completed_at": now,
        "credits_awarded": 2,
        "source": "manual",
        "evidence": {},
        "created_at": now,
        "updated_at": now,
    }
    gid = progress_id(prog["allocation_id"], prog["user_id"], prog["step_key"])
    assert gid == progress_id(prog["allocation_id"], prog["user_id"], prog["step_key"])
    store = ScopedStore.system("firestore.backfill", client=fs_client)  # type: ignore[arg-type]
    pairs = [(PATHS, str(pid), pdoc), (ALLOCATIONS, str(alloc["id"]), adoc), (PROGRESS, gid, row_doc(prog))]
    for coll, doc_id, data in pairs:
        await store.import_documents(coll, [(doc_id, data)])
    for coll, doc_id, data in pairs:
        back = await store.get(coll, doc_id)
        assert back is not None and doc_hash(back.data, list(data)) == doc_hash(data), coll


def test_index_fragment_declares_the_path_queries() -> None:
    frag = json.loads((API / "app/modules/paths/firestore.indexes.fragment.json").read_text())
    groups = {i["collectionGroup"] for i in frag["indexes"]}
    assert {"lms_path_articles", "lms_path_allocations", "lms_path_step_progress"} <= groups
    assert {o["fieldPath"] for o in frag["fieldOverrides"]} >= {"steps", "body_md", "toc"}
