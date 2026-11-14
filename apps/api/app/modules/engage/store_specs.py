# ruff: noqa: E501 - the data-model tables in the docstring are wide
"""Firestore data model of ``engage`` (MIGRATION-PLAN §3.1 "engage"; docs/firebase/agents/data-learning.md).

Moved together by ``TD_STORE_ENGAGE=firestore``; the repository is ``repo_firestore.py`` and the
Firestore service path ``service_fs.py``.

==================================  =========================================  ===================================
collection (doc id)                 holds                                      replaces
==================================  =========================================  ===================================
engage_activities/{id}              row + ``deleted`` (deleted_at IS NOT NULL)  RLS TN; ix_ea_org (listing index)
engage_questions/{id}               row                                        UNIQUE (activity_id, position)
engage_runs/{id}                    row (question snapshot embedded)           RLS TN
engage_join_codes/{code}            {run_id}                                   UNIQUE join_code
engage_run_keys/{activity:run_no}   {run_id}                                   UNIQUE (activity_id, run_no)
engage_participants/{run:user}      row (``id`` field kept)                    UNIQUE (run_id, user_id); RLS U
engage_seq/{run_id}                 {value} = last participant seq             UNIQUE (run_id, seq) + count(*)
engage_responses/{participant:q}    row (``id`` field kept)                    UNIQUE (participant_id, question_id); RLS U
==================================  =========================================  ===================================

Aggregations (counts, choice/word/rating distributions, leaderboard) read a run's responses with
one equality query and fold them in Python with the same ordering rules as the SQL.
"""

from __future__ import annotations

from typing import Any

from app.core.firestore.backfill import TableMapping, register_mapping
from app.core.firestore.collections import CollectionSpec, register_collection
from app.core.firestore.ids import compose_id
from app.core.firestore.rows import doc_mapper
from app.modules.engage.models import (
    EngageActivity,
    EngageParticipant,
    EngageQuestion,
    EngageResponse,
    EngageRun,
)

MODULE = "engage"
PERM = "engage.activity.manage"

ACTIVITIES = "engage_activities"
QUESTIONS = "engage_questions"
RUNS = "engage_runs"
JOIN_CODES = "engage_join_codes"
RUN_KEYS = "engage_run_keys"
PARTICIPANTS = "engage_participants"
SEQ = "engage_seq"
RESPONSES = "engage_responses"

for _n in (ACTIVITIES, QUESTIONS, RUNS):
    register_collection(CollectionSpec(_n, "shared", read_permission=None, write_permission=PERM))
for _n in (PARTICIPANTS, RESPONSES):
    register_collection(CollectionSpec(_n, "owned", read_permission=PERM, write_permission=PERM))
for _n in (JOIN_CODES, RUN_KEYS, SEQ):
    register_collection(CollectionSpec(_n, "system"))


def participant_id(run_id: Any, user_id: Any) -> str:
    return compose_id(str(run_id), str(user_id))


def response_id(participant_id_: Any, question_id: Any) -> str:
    return compose_id(str(participant_id_), str(question_id))


def run_key(activity_id: Any, run_no: int) -> str:
    return compose_id(str(activity_id), int(run_no))


activity_doc = doc_mapper(EngageActivity, extra=lambda r: {"deleted": r.get("deleted_at") is not None})
question_doc = doc_mapper(EngageQuestion)
run_doc = doc_mapper(EngageRun)
participant_doc = doc_mapper(EngageParticipant)
response_doc = doc_mapper(EngageResponse)

register_mapping(TableMapping(MODULE, "engage_activities", ACTIVITIES, lambda r: str(r["id"]), activity_doc))
register_mapping(TableMapping(MODULE, "engage_questions", QUESTIONS, lambda r: str(r["id"]), question_doc))
register_mapping(TableMapping(MODULE, "engage_runs", RUNS, lambda r: str(r["id"]), run_doc))
register_mapping(
    TableMapping(
        MODULE, "engage_runs", JOIN_CODES, lambda r: r["join_code"], lambda r: {"run_id": str(r["id"])}
    )
)
register_mapping(
    TableMapping(
        MODULE,
        "engage_runs",
        RUN_KEYS,
        lambda r: run_key(r["activity_id"], r["run_no"]),
        lambda r: {"run_id": str(r["id"])},
    )
)
register_mapping(
    TableMapping(
        MODULE,
        "engage_participants",
        PARTICIPANTS,
        lambda r: participant_id(r["run_id"], r["user_id"]),
        participant_doc,
    )
)
register_mapping(
    TableMapping(
        MODULE,
        "(SELECT run_id AS id, max(seq) AS value FROM engage_participants GROUP BY run_id) AS seqs",
        SEQ,
        lambda r: str(r["id"]),
        lambda r: {"value": int(r["value"])},
    )
)
register_mapping(
    TableMapping(
        MODULE,
        "engage_responses",
        RESPONSES,
        lambda r: response_id(r["participant_id"], r["question_id"]),
        response_doc,
    )
)

COLLECTIONS = (ACTIVITIES, QUESTIONS, RUNS, JOIN_CODES, RUN_KEYS, PARTICIPANTS, SEQ, RESPONSES)
