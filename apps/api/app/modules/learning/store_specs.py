# ruff: noqa: E501 - the data-model tables in the docstring are wide
"""Firestore data model of ``learning`` (MIGRATION-PLAN §3.1 "learning", P4; docs/firebase/agents/data-learning.md).

STATUS: data path only (collections, mappers, uniqueness index documents, backfill + verify,
indexes). There is **no repository and no routing yet**: ``TD_STORE_LEARNING`` must stay
``postgres`` (the report lists why: ~200 SQL sites in router/structured/structured_api/documents
plus 7 other modules that query the learning tables directly).

Every table maps 1:1 to a collection keyed by the row's primary key, the document being the row
(``fs_rows`` codec: UUID -> str, Decimal -> str, bytes -> hex, nested arrays wrapped). The
Postgres UNIQUE constraints become **key documents** (``create()`` on a deterministic id fails on
a duplicate, in the same transaction as the row), backfilled from the same tables so ``verify``
checks them too:

==============================  =========================================  ===========================
collection (doc id)             holds                                      replaces
==============================  =========================================  ===========================
enrolments/{id}                 row                                        RLS U (owner + staff)
enrolment_keys/{user:course}    {enrolment_id}                             UNIQUE (user_id, course_id)
lesson_progress/{enr:lesson}    row                                        PK (enrolment_id, lesson_key)
certificates/{id}               row (content_hash hex)                     RLS U
certificate_codes/{code}        {certificate_id}                           UNIQUE public_code
certificate_by_enrolment/{enr}  {certificate_id}                           UNIQUE enrolment_id
certificate_outbox/{id}         row                                        RLS US
certificate_outbox_keys/{k}     {outbox_id}                                UNIQUE certificate_id;
                                                                           ux_cob_document_auto
assignments/{id}                row                                        RLS TN
assignment_sections/{id}        row                                        UNIQUE (assignment, position)
assignment_items/{id}           row                                        UNIQUE (section, position)
assignment_allocations/{id}     row (user_ids, evaluator_ids as str lists) RLS T; GIN user_ids ->
                                                                           array-contains
assignment_submissions/{id}     row                                        RLS U
submission_keys/{a:u:n}         {submission_id}                            UNIQUE (assignment, user, attempt)
assignment_item_responses/{id}  row                                        RLS U
item_response_keys/{sub:item}   {response_id}                              UNIQUE (submission_id, item_id)
assignment_regrade_requests/{id} row                                       RLS U
regrade_open/{submission}       {regrade_id} (status = 'open' only)        ux_arr_one_open
issued_documents/{id}           row                                        RLS US
issued_document_keys/{k}        {document_id}                              UNIQUE ref_no;
                                                                           ux_idoc_replaces;
                                                                           ux_idoc_enrolment_auto
document_templates/{kind:key}   row                                        PK (kind, template_key)
document_settings/platform      row (singleton id = 1)                     PK id = 1
==============================  =========================================  ===========================

Sections and items are top-level collections with an ``assignment_id`` field (not
subcollections): the store layer addresses top-level collections only, and an assignment's
outline is one equality query each.
"""

from __future__ import annotations

from typing import Any

from app.core.firestore.backfill import TableMapping, register_mapping
from app.core.firestore.collections import CollectionSpec, register_collection
from app.core.firestore.ids import compose_id
from app.modules.learning.cert_models import CertificateOutbox
from app.modules.learning.doc_models import DocumentSettings, DocumentTemplate, IssuedDocument
from app.modules.learning.fs_rows import doc_mapper
from app.modules.learning.models import (
    Assignment,
    AssignmentAllocation,
    AssignmentItem,
    AssignmentItemResponse,
    AssignmentRegradeRequest,
    AssignmentSection,
    AssignmentSubmission,
    Certificate,
    Enrolment,
    LessonProgress,
)

MODULE = "learning"

ENROLMENTS = "enrolments"
ENROLMENT_KEYS = "enrolment_keys"
PROGRESS = "lesson_progress"
CERTIFICATES = "certificates"
CERT_CODES = "certificate_codes"
CERT_BY_ENROLMENT = "certificate_by_enrolment"
CERT_OUTBOX = "certificate_outbox"
CERT_OUTBOX_KEYS = "certificate_outbox_keys"
ASSIGNMENTS = "assignments"
SECTIONS = "assignment_sections"
ITEMS = "assignment_items"
ALLOCATIONS = "assignment_allocations"
SUBMISSIONS = "assignment_submissions"
SUBMISSION_KEYS = "submission_keys"
RESPONSES = "assignment_item_responses"
RESPONSE_KEYS = "item_response_keys"
REGRADES = "assignment_regrade_requests"
REGRADE_OPEN = "regrade_open"
DOCUMENTS = "issued_documents"
DOCUMENT_KEYS = "issued_document_keys"
DOC_TEMPLATES = "document_templates"
DOC_SETTINGS = "document_settings"
DOC_SETTINGS_ID = "platform"

# --------------------------------------------------------------------------- access families
# Owned (RLS U/US): the learner, or staff holding the read permission (single company: the
# org-staff branch of U/US is "staff with permission X"). Writes by staff need write_permission.
_OWNED: tuple[tuple[str, str | None, str | None], ...] = (
    (ENROLMENTS, "enrolment.read", "enrolment.read"),
    (PROGRESS, "progress.read", None),
    (CERTIFICATES, "progress.read", "certificate.revoke"),
    (SUBMISSIONS, "assignment.grade", "assignment.grade"),
    (RESPONSES, "assignment.grade", "assignment.grade"),
    (REGRADES, "assignment.grade", "assignment.grade"),
)
for _name, _read, _write in _OWNED:
    register_collection(CollectionSpec(_name, "owned", read_permission=_read, write_permission=_write))

# Shared (RLS T/TN): assignment authoring.
for _name in (ASSIGNMENTS, SECTIONS, ITEMS, ALLOCATIONS):
    register_collection(
        CollectionSpec(_name, "shared", read_permission=None, write_permission="assignment.manage")
    )

# System (key documents, outbox, issued documents with optional user_id, template/settings
# config): written by the repository through named jobs after the route's own checks.
for _name in (
    ENROLMENT_KEYS,
    CERT_CODES,
    CERT_BY_ENROLMENT,
    CERT_OUTBOX,
    CERT_OUTBOX_KEYS,
    SUBMISSION_KEYS,
    RESPONSE_KEYS,
    REGRADE_OPEN,
    DOCUMENTS,
    DOCUMENT_KEYS,
    DOC_TEMPLATES,
    DOC_SETTINGS,
):
    register_collection(CollectionSpec(_name, "system"))


# --------------------------------------------------------------------------- ids


def enrolment_key(user_id: Any, course_id: Any) -> str:
    return compose_id(str(user_id), str(course_id))


def progress_id(enrolment_id: Any, lesson_key: Any) -> str:
    return compose_id(str(enrolment_id), str(lesson_key))


def submission_key(assignment_id: Any, user_id: Any, attempt_no: int) -> str:
    return compose_id(str(assignment_id), str(user_id), int(attempt_no))


def response_key(submission_id: Any, item_id: Any) -> str:
    return compose_id(str(submission_id), str(item_id))


def template_id(kind: str, template_key: str) -> str:
    return compose_id(kind, template_key)


def outbox_cert_key(certificate_id: Any) -> str:
    return compose_id("cert", str(certificate_id))


def outbox_doc_auto_key(document_id: Any) -> str:
    return compose_id("doc_auto", str(document_id))


def doc_ref_key(ref_no: str) -> str:
    return compose_id("ref", ref_no)


def doc_replaces_key(replaces_id: Any) -> str:
    return compose_id("replaces", str(replaces_id))


def doc_enrolment_auto_key(enrolment_id: Any, doc_type: str) -> str:
    return compose_id("enrolment_auto", str(enrolment_id), doc_type)


# --------------------------------------------------------------------------- mappers

enrolment_doc = doc_mapper(Enrolment)
progress_doc = doc_mapper(LessonProgress)
certificate_doc = doc_mapper(Certificate)
outbox_doc = doc_mapper(CertificateOutbox)
assignment_doc = doc_mapper(Assignment)
section_doc = doc_mapper(AssignmentSection)
item_doc = doc_mapper(AssignmentItem)
allocation_doc = doc_mapper(AssignmentAllocation)
submission_doc = doc_mapper(AssignmentSubmission)
response_doc = doc_mapper(AssignmentItemResponse)
regrade_doc = doc_mapper(AssignmentRegradeRequest)
document_doc = doc_mapper(IssuedDocument)
template_doc = doc_mapper(DocumentTemplate)
settings_doc = doc_mapper(DocumentSettings)


def _ref(field: str) -> Any:
    return lambda r: {field: str(r["id"])}


def _row(table: str, coll: str, mapper: Any, order_by: str = "id") -> None:
    register_mapping(TableMapping(MODULE, table, coll, lambda r: str(r["id"]), mapper, order_by=order_by))


_row("enrolments", ENROLMENTS, enrolment_doc)
_row("certificates", CERTIFICATES, certificate_doc)
_row("certificate_outbox", CERT_OUTBOX, outbox_doc)
_row("assignments", ASSIGNMENTS, assignment_doc)
_row("assignment_sections", SECTIONS, section_doc)
_row("assignment_items", ITEMS, item_doc)
_row("assignment_allocations", ALLOCATIONS, allocation_doc)
_row("assignment_submissions", SUBMISSIONS, submission_doc)
_row("assignment_item_responses", RESPONSES, response_doc)
_row("assignment_regrade_requests", REGRADES, regrade_doc)
_row("issued_documents", DOCUMENTS, document_doc)

register_mapping(
    TableMapping(
        MODULE,
        "lesson_progress",
        PROGRESS,
        lambda r: progress_id(r["enrolment_id"], r["lesson_key"]),
        progress_doc,
        order_by="enrolment_id, lesson_key",
    )
)
register_mapping(
    TableMapping(
        MODULE,
        "document_templates",
        DOC_TEMPLATES,
        lambda r: template_id(r["kind"], r["template_key"]),
        template_doc,
        order_by="kind, template_key",
    )
)
register_mapping(
    TableMapping(MODULE, "document_settings", DOC_SETTINGS, lambda r: DOC_SETTINGS_ID, settings_doc)
)

# ---- uniqueness key documents (verified like any other collection)
register_mapping(
    TableMapping(
        MODULE,
        "enrolments",
        ENROLMENT_KEYS,
        lambda r: enrolment_key(r["user_id"], r["course_id"]),
        _ref("enrolment_id"),
    )
)
register_mapping(
    TableMapping(MODULE, "certificates", CERT_CODES, lambda r: r["public_code"], _ref("certificate_id"))
)
register_mapping(
    TableMapping(
        MODULE, "certificates", CERT_BY_ENROLMENT, lambda r: str(r["enrolment_id"]), _ref("certificate_id")
    )
)
register_mapping(
    TableMapping(
        MODULE,
        "assignment_submissions",
        SUBMISSION_KEYS,
        lambda r: submission_key(r["assignment_id"], r["user_id"], r["attempt_no"]),
        _ref("submission_id"),
    )
)
register_mapping(
    TableMapping(
        MODULE,
        "assignment_item_responses",
        RESPONSE_KEYS,
        lambda r: response_key(r["submission_id"], r["item_id"]),
        _ref("response_id"),
    )
)
register_mapping(
    TableMapping(
        MODULE,
        "assignment_regrade_requests",
        REGRADE_OPEN,
        lambda r: str(r["submission_id"]),
        _ref("regrade_id"),
        where="status = 'open'",
    )
)


# Several key kinds share one collection: one SQL source per kind, verified together (group).
register_mapping(
    TableMapping(
        MODULE,
        "(SELECT * FROM certificate_outbox WHERE certificate_id IS NOT NULL) AS cob_cert",
        CERT_OUTBOX_KEYS,
        lambda r: outbox_cert_key(r["certificate_id"]),
        _ref("outbox_id"),
        group=CERT_OUTBOX_KEYS,
    )
)
register_mapping(
    TableMapping(
        MODULE,
        "(SELECT * FROM certificate_outbox WHERE document_id IS NOT NULL AND origin = 'enrolment') AS cob_doc",
        CERT_OUTBOX_KEYS,
        lambda r: outbox_doc_auto_key(r["document_id"]),
        _ref("outbox_id"),
        group=CERT_OUTBOX_KEYS,
    )
)
register_mapping(
    TableMapping(
        MODULE,
        "(SELECT * FROM issued_documents) AS idoc_ref",
        DOCUMENT_KEYS,
        lambda r: doc_ref_key(r["ref_no"]),
        _ref("document_id"),
        group=DOCUMENT_KEYS,
    )
)
register_mapping(
    TableMapping(
        MODULE,
        "(SELECT * FROM issued_documents WHERE replaces_id IS NOT NULL) AS idoc_rep",
        DOCUMENT_KEYS,
        lambda r: doc_replaces_key(r["replaces_id"]),
        _ref("document_id"),
        group=DOCUMENT_KEYS,
    )
)
register_mapping(
    TableMapping(
        MODULE,
        "(SELECT * FROM issued_documents WHERE origin = 'enrolment' AND enrolment_id IS NOT NULL) AS idoc_auto",
        DOCUMENT_KEYS,
        lambda r: doc_enrolment_auto_key(r["enrolment_id"], r["doc_type"]),
        _ref("document_id"),
        group=DOCUMENT_KEYS,
    )
)

# Every collection the learning module owns (tests assert each one has a mapping).
COLLECTIONS: tuple[str, ...] = (
    ENROLMENTS,
    ENROLMENT_KEYS,
    PROGRESS,
    CERTIFICATES,
    CERT_CODES,
    CERT_BY_ENROLMENT,
    CERT_OUTBOX,
    CERT_OUTBOX_KEYS,
    ASSIGNMENTS,
    SECTIONS,
    ITEMS,
    ALLOCATIONS,
    SUBMISSIONS,
    SUBMISSION_KEYS,
    RESPONSES,
    RESPONSE_KEYS,
    REGRADES,
    REGRADE_OPEN,
    DOCUMENTS,
    DOCUMENT_KEYS,
    DOC_TEMPLATES,
    DOC_SETTINGS,
)
