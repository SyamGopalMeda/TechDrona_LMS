# ruff: noqa: E501 - the data-model tables in the docstring are wide
"""Firestore data model of the résumé builder (module ``mentoring``; MIGRATION-PLAN §3.1
"mentoring"; docs/firebase/agents/data-learning.md).

Moved by ``TD_STORE_MENTORING=firestore``; repository ``repo_firestore.py``, service path
``service_fs.py``. The mentoring sessions collections (slots, bookings, feedback, notes, résumé
reviews) were removed with the feature (docs/cleanup/feature-removal-plan.md §3.1).

=====================================  ==============================================  ==================================
collection (doc id)                    holds                                           replaces
=====================================  ==============================================  ==================================
resumes/{id}                           row                                             RLS O
resume_versions/{user:n}               {resume_id}                                     UNIQUE (user_id, version_no)
=====================================  ==============================================  ==================================
"""

from __future__ import annotations

from typing import Any

from app.core.firestore.backfill import TableMapping, register_mapping
from app.core.firestore.collections import CollectionSpec, register_collection
from app.core.firestore.ids import compose_id
from app.core.firestore.rows import doc_mapper
from app.modules.mentoring.models import Resume

MODULE = "mentoring"

RESUMES = "resumes"
RESUME_VERSIONS = "resume_versions"

# Owner-only: no staff role reads another user's résumé.
register_collection(CollectionSpec(RESUMES, "owned", read_permission=None, write_permission=None))
register_collection(CollectionSpec(RESUME_VERSIONS, "system"))


def version_key(user_id: Any, version_no: int) -> str:
    return compose_id(str(user_id), int(version_no))


resume_doc = doc_mapper(Resume)


def _ref(field: str) -> Any:
    return lambda r: {field: str(r["id"])}


def _id(r: dict[str, Any]) -> str:
    return str(r["id"])


register_mapping(TableMapping(MODULE, "resumes", RESUMES, _id, resume_doc))
register_mapping(
    TableMapping(
        MODULE,
        "resumes",
        RESUME_VERSIONS,
        lambda r: version_key(r["user_id"], r["version_no"]),
        _ref("resume_id"),
    )
)

COLLECTIONS = (RESUMES, RESUME_VERSIONS)
