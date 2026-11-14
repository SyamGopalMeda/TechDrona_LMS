"""Public API of catalog for other modules (Firestore migration).

Every read and write other modules do on the catalog tables goes through these functions; each
runs on Postgres or Firestore per ``TD_STORE_CATALOG`` (``api.py`` documents the semantics: the
caller's session and RLS / TN visibility, system lookups where stated). ORM classes are
re-exported so callers import catalog types from one place.

Consumers still to switch (docs/firebase/agents/data-content.md): ``admin/accounts.py`` (use
``course_status_counts``) and ``admissions/student.py`` (use ``get_courses`` for slugs).
"""

from __future__ import annotations

from app.modules.catalog.api import (
    Course,
    CourseModule,
    CourseVersion,
    Lesson,
    LessonAsset,
    Resource,
    asset_lesson_id_system,
    asset_with_parents,
    assets_by_s3_key,
    course_ids_for_lessons,
    course_org_system,
    course_status_counts,
    create_asset,
    current_outline_lessons,
    find_lessons,
    get_assets,
    get_courses,
    get_lessons,
    get_resources,
    get_versions,
    lesson_assets,
    lesson_resources,
    lesson_with_parents,
    lock_pending_scan_assets,
    search_published_lessons,
    update_asset,
    update_lesson,
)
from app.modules.catalog.service import (
    ensure_permission,
    get_version,
    lesson_out,
    register_publish_hook,
    system_lookup,
    version_tree,
)

__all__ = [
    "Course",
    "CourseModule",
    "CourseVersion",
    "Lesson",
    "LessonAsset",
    "Resource",
    "asset_lesson_id_system",
    "asset_with_parents",
    "assets_by_s3_key",
    "course_ids_for_lessons",
    "course_org_system",
    "course_status_counts",
    "create_asset",
    "current_outline_lessons",
    "ensure_permission",
    "find_lessons",
    "get_assets",
    "get_courses",
    "get_lessons",
    "get_resources",
    "get_version",
    "get_versions",
    "lesson_assets",
    "lesson_out",
    "lesson_resources",
    "lesson_with_parents",
    "lock_pending_scan_assets",
    "register_publish_hook",
    "search_published_lessons",
    "system_lookup",
    "update_asset",
    "update_lesson",
    "version_tree",
]
