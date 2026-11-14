"""Firestore repository of the orgs module (``TD_STORE_ORGS=firestore``).

Covers the public service functions (``orgs/service.py``) and the cross-module hooks other
modules call (``sessions.resolver.org_ids_for``, ``rbac.service.batch_org`` / ``org_exists``).
The batch, class and import routes (``router.py``, ``classes.py``, ``import_website_plans.py``)
are **not** ported yet (see data-access.md). Named job ``orgs.store``; every method is
``@platform_only``.
"""

from __future__ import annotations

import uuid
from typing import Any

from app.core.firestore.errors import UniqueViolationError
from app.core.firestore.ids import compose_id
from app.core.firestore.repository import platform_only
from app.core.firestore.store import Doc, ScopedTransaction
from app.core.ids import uuid7
from app.modules.identity import clock
from app.modules.identity.fs_base import AccessRepo
from app.modules.identity.fs_codec import doc_obj
from app.modules.orgs.models import (
    Batch,
    BatchMember,
    BatchPlan,
    ClassAttendance,
    ClassSession,
    Organization,
    OrgMembership,
)
from app.modules.orgs.store_specs import (
    ATTENDANCE,
    BATCH_CODES,
    BATCHES,
    CLASS_DATES,
    CLASSES,
    MEMBERS,
    MEMBERS_LIVE,
    MEMBERSHIP_KEY,
    MEMBERSHIPS,
    ORGS,
    PLANS,
    attendance_id,
    member_live_key,
    membership_key,
)

PERM = "org.read"
JOB = "orgs.store"


class OrgsRepo(AccessRepo):
    @platform_only(PERM)
    async def get_org(self, org_id: uuid.UUID) -> Organization | None:
        return await self._get_obj(Organization, ORGS, str(org_id))

    @platform_only(PERM)
    async def live_org_ids(self) -> set[uuid.UUID]:
        return {
            o.id
            for o in await self._objs(Organization, ORGS)
            if o.deleted_at is None and o.status == "active"
        }

    @platform_only(PERM)
    async def get_batch(self, batch_id: uuid.UUID) -> Batch | None:
        return await self._get_obj(Batch, BATCHES, str(batch_id))

    @platform_only(PERM)
    async def get_batches(self, batch_ids: list[uuid.UUID]) -> dict[uuid.UUID, Batch]:
        docs = await self.store.get_many(BATCHES, [str(b) for b in batch_ids])
        return {uuid.UUID(k): doc_obj(Batch, d.data) for k, d in docs.items()}

    @platform_only(PERM)
    async def save_org(self, org: Organization) -> Organization:
        return await self._upsert(ORGS, str(org.id), org)

    @platform_only(PERM)
    async def insert_batch(self, batch: Batch) -> Batch:
        """Insert a batch; ``UniqueViolationError`` when the org already has its code."""
        key = compose_id(str(batch.organization_id), batch.code)

        async def fn(tx: ScopedTransaction) -> Doc:
            if await tx.get(BATCH_CODES, key) is not None:
                raise UniqueViolationError(BATCH_CODES, key)
            d = await tx.create(BATCHES, self.new_doc(batch), doc_id=str(batch.id))
            await tx.put(BATCH_CODES, key, {"batch_id": str(batch.id)})
            return d

        return doc_obj(Batch, (await self.store.run_transaction(fn)).data)

    @platform_only(PERM)
    async def save_batch(self, batch: Batch) -> Batch:
        """Overwrite a batch; a code change moves the ``batches_by_code`` reservation."""
        bid = str(batch.id)

        async def fn(tx: ScopedTransaction) -> Doc:
            cur = await tx.get(BATCHES, bid)
            if cur is None:
                raise UniqueViolationError(BATCHES, bid)
            old_key = compose_id(str(cur["organization_id"]), cur["code"])
            new_key = compose_id(str(batch.organization_id), batch.code)
            moved = new_key != old_key
            held = await tx.get(BATCH_CODES, new_key) if moved else None
            old_ref = await tx.get(BATCH_CODES, old_key) if moved else None
            if held is not None and held["batch_id"] != bid:
                raise UniqueViolationError(BATCH_CODES, new_key)
            d = await self._tx_upsert(tx, BATCHES, bid, batch, cur)
            if moved:
                if old_ref is not None and old_ref["batch_id"] == bid:
                    await tx.delete_read(BATCH_CODES, old_key, old_ref.data)
                await tx.put(BATCH_CODES, new_key, {"batch_id": bid})
            return d

        return doc_obj(Batch, (await self.store.run_transaction(fn)).data)

    @platform_only(PERM)
    async def batch_by_code(self, org_id: uuid.UUID, code: str) -> Batch | None:
        ref = await self.store.get(BATCH_CODES, compose_id(str(org_id), code))
        return await self.get_batch(uuid.UUID(ref["batch_id"])) if ref else None

    @platform_only(PERM)
    async def list_batches(self) -> list[Batch]:
        return await self._objs(Batch, BATCHES)

    @platform_only(PERM)
    async def save_plan(self, plan: BatchPlan) -> BatchPlan:
        return await self._upsert(PLANS, str(plan.batch_id), plan)

    @platform_only(PERM)
    async def plan_by_source_ref(self, source_ref: str) -> BatchPlan | None:
        rows = await self._objs(BatchPlan, PLANS, filters=(("source_ref", "==", source_ref),))
        return rows[0] if rows else None

    # ------------------------------------------------------------------ classes / attendance

    @platform_only(PERM)
    async def get_class(self, class_id: uuid.UUID) -> ClassSession | None:
        return await self._get_obj(ClassSession, CLASSES, str(class_id))

    @platform_only(PERM)
    async def classes_of(self, batch_id: uuid.UUID) -> list[ClassSession]:
        rows = await self._objs(ClassSession, CLASSES, filters=(("batch_id", "==", str(batch_id)),))
        return sorted(rows, key=lambda c: (c.session_date, str(c.id)))

    @platform_only(PERM)
    async def insert_class(self, c: ClassSession) -> ClassSession:
        """Insert a class; ``UniqueViolationError`` for a second class on the same date."""
        key = compose_id(str(c.batch_id), c.session_date.isoformat())

        async def fn(tx: ScopedTransaction) -> Doc:
            if await tx.get(CLASS_DATES, key) is not None:
                raise UniqueViolationError(CLASS_DATES, key)
            d = await tx.create(CLASSES, self.new_doc(c), doc_id=str(c.id))
            await tx.put(CLASS_DATES, key, {"session_id": str(c.id)})
            return d

        return doc_obj(ClassSession, (await self.store.run_transaction(fn)).data)

    @platform_only(PERM)
    async def save_class(self, c: ClassSession) -> ClassSession:
        """Overwrite a class; a date change moves the per-date reservation."""
        cid = str(c.id)

        async def fn(tx: ScopedTransaction) -> Doc:
            cur = await tx.get(CLASSES, cid)
            if cur is None:
                raise UniqueViolationError(CLASSES, cid)
            old_key = compose_id(str(cur["batch_id"]), cur["session_date"])
            new_key = compose_id(str(c.batch_id), c.session_date.isoformat())
            moved = new_key != old_key
            held = await tx.get(CLASS_DATES, new_key) if moved else None
            old_ref = await tx.get(CLASS_DATES, old_key) if moved else None
            if held is not None and held["session_id"] != cid:
                raise UniqueViolationError(CLASS_DATES, new_key)
            d = await self._tx_upsert(tx, CLASSES, cid, c, cur)
            if moved:
                if old_ref is not None and old_ref["session_id"] == cid:
                    await tx.delete_read(CLASS_DATES, old_key, old_ref.data)
                await tx.put(CLASS_DATES, new_key, {"session_id": cid})
            return d

        return doc_obj(ClassSession, (await self.store.run_transaction(fn)).data)

    @platform_only(PERM)
    async def delete_class(self, class_id: uuid.UUID) -> bool:
        """Delete a class with its attendance marks and date reservation."""
        c = await self.get_class(class_id)
        if c is None:
            return False
        marks = await self._all(ATTENDANCE, filters=(("session_id", "==", str(class_id)),))
        key = compose_id(str(c.batch_id), c.session_date.isoformat())

        async def fn(tx: ScopedTransaction) -> bool:
            ref = await tx.get(CLASS_DATES, key)
            cur = await tx.get(CLASSES, str(class_id))
            for m in marks:
                await tx.delete_read(ATTENDANCE, m.id, m.data)
            if cur is not None:
                await tx.delete_read(CLASSES, cur.id, cur.data)
            if ref is not None and ref["session_id"] == str(class_id):
                await tx.delete_read(CLASS_DATES, key, ref.data)
            return cur is not None

        return await self.store.run_transaction(fn)

    @platform_only(PERM)
    async def get_attendance(self, session_id: uuid.UUID, user_id: uuid.UUID) -> ClassAttendance | None:
        return await self._get_obj(ClassAttendance, ATTENDANCE, attendance_id(session_id, user_id))

    @platform_only(PERM)
    async def attendance_of(
        self,
        *,
        batch_id: uuid.UUID | None = None,
        session_id: uuid.UUID | None = None,
        user_id: uuid.UUID | None = None,
    ) -> list[ClassAttendance]:
        f: list[Any] = []
        if batch_id is not None:
            f.append(("batch_id", "==", str(batch_id)))
        if session_id is not None:
            f.append(("session_id", "==", str(session_id)))
        return await self._objs(ClassAttendance, ATTENDANCE, user_id=user_id, filters=tuple(f))

    @platform_only(PERM)
    async def save_attendance(self, a: ClassAttendance) -> ClassAttendance:
        return await self._upsert(ATTENDANCE, attendance_id(a.session_id, a.user_id), a)

    @platform_only(PERM)
    async def delete_attendance(self, session_id: uuid.UUID, user_id: uuid.UUID) -> None:
        aid = attendance_id(session_id, user_id)
        if await self.store.get(ATTENDANCE, aid) is not None:
            await self.store.delete(ATTENDANCE, aid)

    # ------------------------------------------------------------------ membership / member rows

    @platform_only(PERM)
    async def get_membership(self, membership_id: uuid.UUID) -> OrgMembership | None:
        return await self._get_obj(OrgMembership, MEMBERSHIPS, str(membership_id))

    @platform_only(PERM)
    async def membership_of(self, org_id: uuid.UUID, user_id: uuid.UUID) -> OrgMembership | None:
        ref = await self.store.get(MEMBERSHIP_KEY, membership_key(org_id, user_id))
        return await self.get_membership(uuid.UUID(ref["membership_id"])) if ref else None

    @platform_only(PERM)
    async def insert_membership(self, m: OrgMembership) -> OrgMembership:
        key = membership_key(m.organization_id, m.user_id)

        async def fn(tx: ScopedTransaction) -> Doc:
            if await tx.get(MEMBERSHIP_KEY, key) is not None:
                raise UniqueViolationError(MEMBERSHIP_KEY, key)
            d = await tx.create(MEMBERSHIPS, self.new_doc(m), doc_id=str(m.id))
            await tx.put(MEMBERSHIP_KEY, key, {"membership_id": str(m.id)})
            return d

        return doc_obj(OrgMembership, (await self.store.run_transaction(fn)).data)

    @platform_only(PERM)
    async def save_membership(self, m: OrgMembership) -> OrgMembership:
        return await self._upsert(MEMBERSHIPS, str(m.id), m)

    @platform_only(PERM)
    async def get_batch_member(self, member_id: uuid.UUID) -> BatchMember | None:
        return await self._get_obj(BatchMember, MEMBERS, str(member_id))

    @platform_only(PERM)
    async def save_batch_member(self, m: BatchMember) -> BatchMember:
        """Overwrite a member row; leaving ``active`` frees the ``ux_bm_live`` slot."""
        key = member_live_key(m.batch_id, m.user_id, m.member_role)

        async def fn(tx: ScopedTransaction) -> Doc:
            cur = await tx.get(MEMBERS, str(m.id))
            ref = await tx.get(MEMBERS_LIVE, key)
            live = None
            if m.status == "active" and ref is not None and ref["member_id"] != str(m.id):
                live = await tx.get(MEMBERS, ref["member_id"])
            if live is not None and live.get("status") == "active":
                raise UniqueViolationError(MEMBERS_LIVE, key)
            d = await self._tx_upsert(tx, MEMBERS, str(m.id), m, cur)
            if m.status != "active" and ref is not None and ref["member_id"] == str(m.id):
                await tx.delete_read(MEMBERS_LIVE, key, ref.data)
            elif m.status == "active" and (ref is None or ref["member_id"] != str(m.id)):
                await tx.put(MEMBERS_LIVE, key, {"member_id": str(m.id)})
            return d

        return doc_obj(BatchMember, (await self.store.run_transaction(fn)).data)

    # ------------------------------------------------------------------ memberships

    @platform_only(PERM)
    async def memberships_for(self, user_id: uuid.UUID) -> list[OrgMembership]:
        return await self._objs(OrgMembership, MEMBERSHIPS, user_id=user_id)

    @platform_only(PERM)
    async def active_membership_org_ids(self, user_id: uuid.UUID) -> list[uuid.UUID]:
        return [m.organization_id for m in await self.memberships_for(user_id) if m.status == "active"]

    @platform_only(PERM)
    async def active_student_org_ids(self, user_id: uuid.UUID) -> list[uuid.UUID]:
        live = await self.live_org_ids()
        ids = {
            m.organization_id
            for m in await self.memberships_for(user_id)
            if m.status == "active" and m.member_type == "student" and m.organization_id in live
        }
        return sorted(ids)

    @platform_only(PERM)
    async def ensure_membership(
        self, org_id: uuid.UUID, user_id: uuid.UUID, *, member_type: str, added_by: uuid.UUID | None
    ) -> OrgMembership:
        """``ensure_org_membership`` in one transaction (``uq_org_memberships_org_user``)."""
        key = membership_key(org_id, user_id)

        async def fn(tx: ScopedTransaction) -> Doc:
            ref = await tx.get(MEMBERSHIP_KEY, key)
            cur = await tx.get(MEMBERSHIPS, ref["membership_id"]) if ref is not None else None
            now = clock.now()
            if cur is None:
                m = OrgMembership(
                    id=uuid7(),
                    organization_id=org_id,
                    user_id=user_id,
                    member_type=member_type,
                    status="active",
                    joined_at=now,
                    invited_by=added_by,
                    source="staff",
                )
                d = await tx.create(MEMBERSHIPS, self.new_doc(m), doc_id=str(m.id))
                await tx.put(MEMBERSHIP_KEY, key, {"membership_id": str(m.id)})
                return d
            changes: dict[str, Any] = {}
            if cur.get("status") != "active":
                changes.update(status="active", left_at=None, joined_at=cur.get("joined_at") or now)
            if member_type == "staff" and cur.get("member_type") != "staff":
                changes["member_type"] = "staff"
            return await tx.update_read(MEMBERSHIPS, cur, changes) if changes else cur

        return doc_obj(OrgMembership, (await self.store.run_transaction(fn)).data)

    @platform_only(PERM)
    async def end_student_membership_if_no_batches(self, org_id: uuid.UUID, user_id: uuid.UUID) -> bool:
        members = await self.batch_memberships_for(user_id)
        if any(b.organization_id == org_id and b.status == "active" for b in members):
            return False
        key = membership_key(org_id, user_id)

        async def fn(tx: ScopedTransaction) -> bool:
            ref = await tx.get(MEMBERSHIP_KEY, key)
            cur = await tx.get(MEMBERSHIPS, ref["membership_id"]) if ref is not None else None
            if cur is None or cur.get("member_type") != "student" or cur.get("status") != "active":
                return False
            await tx.update_read(MEMBERSHIPS, cur, {"status": "left", "left_at": clock.now()})
            return True

        return await self.store.run_transaction(fn)

    # ------------------------------------------------------------------ batch members

    @platform_only(PERM)
    async def batch_memberships_for(self, user_id: uuid.UUID) -> list[BatchMember]:
        return await self._objs(BatchMember, MEMBERS, user_id=user_id)

    @platform_only(PERM)
    async def batch_members(self, batch_id: uuid.UUID) -> list[BatchMember]:
        return await self._objs(BatchMember, MEMBERS, filters=(("batch_id", "==", str(batch_id)),))

    @platform_only(PERM)
    async def add_batch_member(self, m: BatchMember) -> BatchMember:
        """Insert an active member; ``UniqueViolationError`` when the live (batch, user, role)
        row exists (``ux_bm_live``)."""
        key = member_live_key(m.batch_id, m.user_id, m.member_role)

        async def fn(tx: ScopedTransaction) -> Doc:
            ref = await tx.get(MEMBERS_LIVE, key)
            if ref is not None:
                cur = await tx.get(MEMBERS, ref["member_id"])
                if cur is not None and cur.get("status") == "active":
                    from app.core.firestore.errors import UniqueViolationError

                    raise UniqueViolationError(MEMBERS_LIVE, key)
            d = await tx.create(MEMBERS, self.new_doc(m), doc_id=str(m.id))
            await tx.put(MEMBERS_LIVE, key, {"member_id": str(m.id)})
            return d

        return doc_obj(BatchMember, (await self.store.run_transaction(fn)).data)

    @platform_only(PERM)
    async def remove_batch_member(
        self, member_id: uuid.UUID, *, status: str = "removed"
    ) -> BatchMember | None:
        async def fn(tx: ScopedTransaction) -> Doc | None:
            cur = await tx.get(MEMBERS, str(member_id))
            if cur is None:
                return None
            key = member_live_key(cur["batch_id"], cur["user_id"], cur["member_role"])
            ref = await tx.get(MEMBERS_LIVE, key)
            d = await tx.update_read(MEMBERS, cur, {"status": status, "removed_at": clock.now()})
            if ref is not None and ref["member_id"] == str(member_id):
                await tx.delete_read(MEMBERS_LIVE, key, ref.data)
            return d

        d = await self.store.run_transaction(fn)
        return doc_obj(BatchMember, d.data) if d else None

    # ------------------------------------------------------------------ delivery (read side)

    @platform_only(PERM)
    async def batch_plan(self, batch_id: uuid.UUID) -> BatchPlan | None:
        return await self._get_obj(BatchPlan, PLANS, str(batch_id))

    @platform_only(PERM)
    async def attendance_statuses(self, batch_id: uuid.UUID, user_id: uuid.UUID) -> list[str]:
        """Marks of a learner in a batch, ignoring cancelled classes."""
        marks = await self._objs(
            ClassAttendance, ATTENDANCE, user_id=user_id, filters=(("batch_id", "==", str(batch_id)),)
        )
        classes = await self.store.get_many(CLASSES, [str(a.session_id) for a in marks])
        live = {k for k, d in classes.items() if not doc_obj(ClassSession, d.data).cancelled}
        return [a.status for a in marks if str(a.session_id) in live]


def system_repo(job: str = JOB) -> OrgsRepo:
    from app.modules.identity.fs_journal import JournalingStore

    return OrgsRepo(JournalingStore.system(job))
