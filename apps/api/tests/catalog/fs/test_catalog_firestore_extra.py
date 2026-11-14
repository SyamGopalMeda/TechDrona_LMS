"""Catalog additions of the data-content agent, on the emulator (no Postgres)."""

from __future__ import annotations

from typing import Any

from app.core.ids import uuid7
from app.core.time import utcnow


def _course(status: str, *, org: Any = None, deleted: bool = False) -> dict[str, Any]:
    from app.modules.catalog.store_specs import course_doc

    now = utcnow()
    return course_doc(
        {
            "id": uuid7(),
            "organization_id": org,
            "slug": f"c-{uuid7().hex[:8]}",
            "title": "T",
            "course_kind": "standard",
            "visibility": "public",
            "status": status,
            "is_free": False,
            "current_version_id": None,
            "primary_topic_id": None,
            "completeness_pct": 0,
            "created_by": uuid7(),
            "created_at": now,
            "updated_at": now,
            "deleted_at": now if deleted else None,
        }
    )


async def test_course_status_counts_follow_tn_visibility(fs_client: Any) -> None:
    from app.core.firestore.store import ScopedStore
    from app.modules.catalog.repo_firestore import SYSTEM_VIEW, CatalogReadRepo, Visibility
    from app.modules.catalog.store_specs import COURSES

    org = uuid7()
    docs = [
        _course("published"),
        _course("published"),
        _course("draft"),
        _course("draft", deleted=True),
        _course("draft", org=org),
    ]
    store = ScopedStore.system("test", client=fs_client)  # type: ignore[arg-type]
    await store.import_documents(COURSES, [(d["id"], d) for d in docs])
    anon = CatalogReadRepo(ScopedStore.system("catalog.read", client=fs_client), Visibility())  # type: ignore[arg-type]
    member = CatalogReadRepo(
        ScopedStore.system("catalog.read", client=fs_client),  # type: ignore[arg-type]
        Visibility(org_ids=frozenset({str(org)})),
    )
    plat = CatalogReadRepo(ScopedStore.system("catalog.read", client=fs_client), SYSTEM_VIEW)  # type: ignore[arg-type]
    assert await anon.status_counts() == {"published": 2, "draft": 1}
    assert await member.status_counts() == {"published": 2, "draft": 2}
    assert await plat.status_counts() == {"published": 2, "draft": 2}


def test_catalog_repositories_pass_the_scope_lint() -> None:
    from app.core.firestore.repository import assert_repository_scoped
    from app.modules.catalog.repo_firestore import CatalogReadRepo, CatalogWriteRepo

    assert_repository_scoped(CatalogReadRepo)
    assert_repository_scoped(CatalogWriteRepo)
