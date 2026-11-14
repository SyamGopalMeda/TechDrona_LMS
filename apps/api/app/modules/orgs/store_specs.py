"""Firestore collections of the orgs module (``TD_STORE_ORGS=firestore``).

* ``organizations/{id}``           the single company row (``ux_organizations_singleton``)
* ``org_memberships/{id}``         + ``org_memberships_by_user/{org_id:user_id}`` ``{membership_id}``
                                   (``uq_org_memberships_org_user``)
* ``batches/{id}``                 + ``batches_by_code/{org_id:code}`` (``uq_batches_org_code``)
* ``batch_members/{id}``           + ``batch_members_live/{batch_id:user_id:member_role}``
                                   (``ux_bm_live``, ``status = 'active'``)
* ``batch_plans/{batch_id}``       plan JSON as a map
* ``class_sessions/{id}``          + ``class_sessions_by_date/{batch_id:date}``
                                   (``uq_class_sessions_batch_date``)
* ``class_attendance/{session_id:user_id}`` (``uq_class_attendance_session_user`` as the id;
                                   the Postgres ``id`` is kept as a field)

Note: Postgres ``app.caller_is_org_staff()`` (orgs_0004) reads ``org_memberships`` inside every
US-family RLS policy, so while any US table stays on Postgres the Postgres copy must stay current
(see data-access.md: do not flip orgs before those tables move, or dual-write).
"""

from __future__ import annotations

from app.core.firestore.backfill import TableMapping, register_mapping
from app.core.firestore.collections import CollectionSpec, register_collection
from app.core.firestore.ids import compose_id
from app.modules.identity.fs_codec import row_doc
from app.modules.orgs.models import (
    Batch,
    BatchMember,
    BatchPlan,
    ClassAttendance,
    ClassSession,
    Organization,
    OrgMembership,
)

ORGS = "organizations"
MEMBERSHIPS = "org_memberships"
MEMBERSHIP_KEY = "org_memberships_by_user"
BATCHES = "batches"
BATCH_CODES = "batches_by_code"
MEMBERS = "batch_members"
MEMBERS_LIVE = "batch_members_live"
PLANS = "batch_plans"
CLASSES = "class_sessions"
CLASS_DATES = "class_sessions_by_date"
ATTENDANCE = "class_attendance"

register_collection(CollectionSpec(ORGS, "shared", read_permission=None, write_permission="org.update"))
register_collection(
    CollectionSpec(
        MEMBERSHIPS, "owned", read_permission="org.member.read", write_permission="batch.member.manage"
    )
)
register_collection(CollectionSpec(BATCHES, "shared", read_permission=None, write_permission="batch.update"))
register_collection(
    CollectionSpec(
        MEMBERS, "owned", read_permission="org.member.read", write_permission="batch.member.manage"
    )
)
register_collection(CollectionSpec(PLANS, "shared", read_permission=None, write_permission="batch.update"))
register_collection(
    CollectionSpec(CLASSES, "shared", read_permission=None, write_permission="batch.class.manage")
)
register_collection(
    CollectionSpec(
        ATTENDANCE, "owned", read_permission="org.member.read", write_permission="batch.class.manage"
    )
)
for _c in (MEMBERSHIP_KEY, BATCH_CODES, MEMBERS_LIVE, CLASS_DATES):
    register_collection(CollectionSpec(_c, "system"))


def membership_key(org_id: object, user_id: object) -> str:
    return compose_id(str(org_id), str(user_id))


def member_live_key(batch_id: object, user_id: object, role: str) -> str:
    return compose_id(str(batch_id), str(user_id), role)


def attendance_id(session_id: object, user_id: object) -> str:
    return compose_id(str(session_id), str(user_id))


def _id(r: dict[str, object]) -> str:
    return str(r["id"])


for _model, _coll in (
    (Organization, ORGS),
    (OrgMembership, MEMBERSHIPS),
    (Batch, BATCHES),
    (BatchMember, MEMBERS),
    (ClassSession, CLASSES),
):
    register_mapping(
        TableMapping("orgs", _model.__tablename__, _coll, _id, (lambda m: lambda r: row_doc(m, r))(_model))
    )
register_mapping(
    TableMapping(
        "orgs",
        "batch_plans",
        PLANS,
        lambda r: str(r["batch_id"]),
        lambda r: row_doc(BatchPlan, r),
        order_by="batch_id",
    )
)
register_mapping(
    TableMapping(
        "orgs",
        "class_attendance",
        ATTENDANCE,
        lambda r: attendance_id(r["session_id"], r["user_id"]),
        lambda r: row_doc(ClassAttendance, r),
    )
)
register_mapping(
    TableMapping(
        "orgs",
        "org_memberships",
        MEMBERSHIP_KEY,
        lambda r: membership_key(r["organization_id"], r["user_id"]),
        lambda r: {"membership_id": str(r["id"])},
    )
)
register_mapping(
    TableMapping(
        "orgs",
        "batches",
        BATCH_CODES,
        lambda r: compose_id(str(r["organization_id"]), r["code"]),
        lambda r: {"batch_id": str(r["id"])},
    )
)
register_mapping(
    TableMapping(
        "orgs",
        "batch_members",
        MEMBERS_LIVE,
        lambda r: member_live_key(r["batch_id"], r["user_id"], r["member_role"]),
        lambda r: {"member_id": str(r["id"])},
        where="status = 'active'",
    )
)
register_mapping(
    TableMapping(
        "orgs",
        "class_sessions",
        CLASS_DATES,
        lambda r: compose_id(str(r["batch_id"]), r["session_date"].isoformat()),
        lambda r: {"session_id": str(r["id"])},
    )
)
