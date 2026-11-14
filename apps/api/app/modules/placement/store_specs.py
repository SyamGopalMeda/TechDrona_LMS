"""Firestore data model of placement (``TD_STORE_PLACEMENT=firestore``; docs/firebase/agents/data-assess.md).

Every table keeps its rows one-to-one as documents (UUIDs stay document ids) except the options,
which are embedded in their version, plus a few key documents that replace Postgres unique
indexes. Physical names get the ``lms_`` prefix (``collections.physical_name``).

* ``topics/{id}``; ``topics_by_path/{path_key(path)}`` = ``{topic_id}`` (``topics.path`` UNIQUE; also covers
  ``UNIQUE (parent_id, slug)`` and ``ux_topics_root_slug`` because path = parent path + slug).
* ``companies/{id}``; ``companies_by_slug/{slug}`` = ``{company_id}`` (``companies.slug`` UNIQUE).
* ``questions/{id}``.
* ``question_versions/{id}`` with ``options`` = ``{option_id: option}`` embedded
  (``question_options``). A published or retired version and its options are immutable (Postgres
  triggers ``placement_qv_immutable`` / ``placement_qo_immutable``): the repository refuses the
  write (``repo_firestore.assert_version_mutable``), and options can't change separately because
  they live in the version document.
* ``question_tags/{question_id:tag_type:ref}`` (``ux_qt``: deterministic id), keeps ``id``.
* ``question_media/{id}``, ``question_reports/{id}`` (owned by ``user_id``);
  ``question_reports_open/{user_id:question_id}`` (``ux_qr_open_per_user``, only open reports).
* ``question_banks/{id}``; ``question_bank_items/{bank_id:question_id}`` (UNIQUE), keeps ``id``.
* ``practice_sessions/{id}`` (owned); ``practice_responses/{session_id:question_version_id}``
  (owned; ``UNIQUE (practice_session_id, question_version_id)``), keeps ``id``.
* ``recommendations/{id}`` (owned); ``recommendations_active/{user:rule:target_type:target_id}``
  (``ux_rec_dedupe``, only active rows).

Value mapping (``core.firestore.rows.row_doc``): UUID -> str, ``numeric`` -> canonical decimal string
(``"1.00"``, Firestore has no decimal), ``bytea`` (``content_hash``) -> base64, ``uuid[]`` -> list
of str, JSONB and timestamps verbatim. ``orm_of`` is the exact inverse, so repositories return transient
ORM instances and the existing serializers (``topic_out``, ``version_out``, ...) are shared.
"""

from __future__ import annotations

import functools
from typing import Any

from app.core.firestore.backfill import Row, TableMapping, register_mapping
from app.core.firestore.collections import CollectionSpec, register_collection
from app.core.firestore.ids import compose_id
from app.core.firestore.rows import orm_doc, row_doc
from app.core.firestore.rows import orm_of_scaled as orm_of
from app.modules.placement.models import (
    Company,
    PracticeResponse,
    PracticeSession,
    Question,
    QuestionBank,
    QuestionBankItem,
    QuestionMedia,
    QuestionOption,
    QuestionReport,
    QuestionTag,
    QuestionVersion,
    Recommendation,
    Topic,
)

M = "placement"

TOPICS = "topics"
TOPICS_BY_PATH = "topics_by_path"
COMPANIES = "companies"
COMPANIES_BY_SLUG = "companies_by_slug"
QUESTIONS = "questions"
VERSIONS = "question_versions"
TAGS = "question_tags"
MEDIA = "question_media"
REPORTS = "question_reports"
REPORTS_OPEN = "question_reports_open"
BANKS = "question_banks"
BANK_ITEMS = "question_bank_items"
SESSIONS = "practice_sessions"
RESPONSES = "practice_responses"
RECS = "recommendations"
RECS_ACTIVE = "recommendations_active"

# Shared (RLS none / TN). The TN read predicate is applied by the repository with the caller's
# Postgres context (like catalog); writes go through the route's permission check first.
for _name, _write in (
    (TOPICS, "taxonomy.manage"),
    (TOPICS_BY_PATH, "taxonomy.manage"),
    (COMPANIES, "company_path.manage"),
    (COMPANIES_BY_SLUG, "company_path.manage"),
    (QUESTIONS, "question.edit"),
    (VERSIONS, "question.edit"),
    (TAGS, "question.edit"),
    (MEDIA, "question.edit"),
    (BANKS, "question.edit"),
    (BANK_ITEMS, "question.edit"),
    (REPORTS_OPEN, "question.edit"),
):
    register_collection(CollectionSpec(_name, "shared", read_permission=None, write_permission=_write))

# Learner-owned (RLS U/US): the owner reads and writes; staff need the permission.
for _name, _perm in (
    (SESSIONS, "test.results.read"),
    (RESPONSES, "test.results.read"),
    (RECS, "test.results.read"),
    (REPORTS, "question.edit"),
):
    register_collection(CollectionSpec(_name, "owned", read_permission=_perm, write_permission=_perm))
register_collection(CollectionSpec(RECS_ACTIVE, "system"))


# --------------------------------------------------------------------------- key documents


def path_key(path: str) -> str:
    """``topics_by_path`` document id (a path has ``/``, which a document id can't)."""
    return compose_id(*path.split("/"))


def tag_ref(r: Row | Any) -> str:
    g = r.get if isinstance(r, dict) else lambda k: getattr(r, k)
    ref = g("topic_id") or g("company_id") or g("tag_value")
    return str(ref)


def tag_id(question_id: Any, tag_type: str, ref: str) -> str:
    return compose_id(str(question_id), tag_type, ref)


def bank_item_id(bank_id: Any, question_id: Any) -> str:
    return compose_id(str(bank_id), str(question_id))


def response_id(session_id: Any, qv_id: Any) -> str:
    return compose_id(str(session_id), str(qv_id))


def open_report_id(user_id: Any, question_id: Any) -> str:
    return compose_id(str(user_id), str(question_id))


def rec_active_id(user_id: Any, rule_key: str, target_type: str, target_id: Any) -> str:
    return compose_id(str(user_id), rule_key, target_type, str(target_id))


def option_entry(r: Row) -> dict[str, Any]:
    return {"options": {str(r["id"]): row_doc(QuestionOption, r)}}


# --------------------------------------------------------------------------- backfill mappings


def _m(table: str, coll: str, model: type[Any], doc_id: Any = None, **kw: Any) -> None:
    register_mapping(
        TableMapping(
            M,
            table,
            coll,
            doc_id or (lambda r: str(r["id"])),
            functools.partial(row_doc, model),
            **kw,
        )
    )


_m("topics", TOPICS, Topic)
register_mapping(
    TableMapping(
        M, "topics", TOPICS_BY_PATH, lambda r: path_key(r["path"]), lambda r: {"topic_id": str(r["id"])}
    )
)
_m("companies", COMPANIES, Company)
register_mapping(
    TableMapping(
        M,
        "companies",
        COMPANIES_BY_SLUG,
        lambda r: str(r["slug"]).lower(),
        lambda r: {"company_id": str(r["id"])},
    )
)
_m("questions", QUESTIONS, Question)
_m("question_versions", VERSIONS, QuestionVersion)
register_mapping(
    TableMapping(
        M,
        "question_options",
        VERSIONS,
        lambda r: str(r["question_version_id"]),
        option_entry,
        group=VERSIONS,
    )
)
_m("question_tags", TAGS, QuestionTag, lambda r: tag_id(r["question_id"], r["tag_type"], tag_ref(r)))
_m("question_media", MEDIA, QuestionMedia)
_m("question_reports", REPORTS, QuestionReport)
register_mapping(
    TableMapping(
        M,
        "question_reports",
        REPORTS_OPEN,
        lambda r: open_report_id(r["user_id"], r["question_id"]),
        lambda r: {"report_id": str(r["id"])},
        where="status = 'open'",
    )
)
_m("question_banks", BANKS, QuestionBank)
_m(
    "question_bank_items",
    BANK_ITEMS,
    QuestionBankItem,
    lambda r: bank_item_id(r["bank_id"], r["question_id"]),
)
_m("practice_sessions", SESSIONS, PracticeSession)
_m(
    "practice_responses",
    RESPONSES,
    PracticeResponse,
    lambda r: response_id(r["practice_session_id"], r["question_version_id"]),
)
_m("recommendations", RECS, Recommendation)
register_mapping(
    TableMapping(
        M,
        "recommendations",
        RECS_ACTIVE,
        lambda r: rec_active_id(r["user_id"], r["rule_key"], r["target_type"], r["target_id"]),
        lambda r: {"recommendation_id": str(r["id"]), "user_id": str(r["user_id"])},
        where="status = 'active'",
    )
)


__all__ = ["orm_doc", "orm_of", "row_doc"]
