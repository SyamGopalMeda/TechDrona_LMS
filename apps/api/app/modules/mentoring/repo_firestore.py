"""Firestore repository of the résumé builder (``TD_STORE_MENTORING=firestore``; model in
``store_specs.py``).

Rows come back as transient ORM instances so ``service.py``'s serializers are shared. Every public
method takes the ``user_id`` it acts for or is ``@platform_only``; the repository runs as a named
system job. ``FOR UPDATE`` sections (new version, PDF completion) are transactions.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from app.core.errors import ProblemError
from app.core.firestore.errors import UniqueViolationError
from app.core.firestore.repository import FirestoreRepository, platform_only
from app.core.firestore.rows import doc_of, orm_of
from app.core.firestore.store import Doc, ScopedStore, ScopedTransaction
from app.core.time import utcnow
from app.modules.mentoring import store_specs as ss
from app.modules.mentoring.models import Resume

# ``@platform_only`` marker for reads by id (the service checks ownership); the repository always
# runs on a system job.
PERM = "user.read"


def conflict() -> ProblemError:
    return ProblemError(
        "conflict", detail="Another request changed this at the same time. Refresh and try again."
    )


def _new(obj: Any, now: datetime) -> dict[str, Any]:
    d = doc_of(obj)
    if not d.get("created_at"):
        d["created_at"] = now
    d.pop("updated_at", None)
    return d


class MentoringRepo(FirestoreRepository):
    async def _all(
        self, coll: str, *, filters: Any = (), order_by: Any = (), user_id: Any = None
    ) -> list[Doc]:
        out: list[Doc] = []
        cursor: str | None = None
        while True:
            page = await self.store.query(
                coll, user_id=user_id, filters=filters, order_by=order_by, limit=500, cursor=cursor
            )
            out += page.items
            if not page.next_cursor:
                return out
            cursor = page.next_cursor

    # ================================================================== résumés

    async def resumes_of(self, user_id: uuid.UUID, limit: int = 50) -> list[Resume]:
        page = await self.store.query(
            ss.RESUMES, user_id=user_id, order_by=(("version_no", "desc"),), limit=limit
        )
        return [orm_of(Resume, d.data) for d in page.items]

    @platform_only(PERM)
    async def get_resume(self, resume_id: uuid.UUID) -> Resume | None:
        d = await self.store.get(ss.RESUMES, str(resume_id))
        return orm_of(Resume, d.data) if d else None

    async def new_version(self, user_id: uuid.UUID, r: Resume) -> Resume:
        """Insert ``r`` as version ``max+1`` and clear the previous ``is_current``, atomically
        (``resume_versions/{user:n}`` makes a concurrent duplicate number fail and retry)."""
        now = utcnow()
        for _ in range(5):
            mine = await self._all(ss.RESUMES, user_id=user_id)
            last = max((int(d["version_no"]) for d in mine), default=0)
            current = [d.id for d in mine if d.get("is_current")]

            async def fn(tx: ScopedTransaction, last: int = last, current: list[str] = current) -> Resume:
                if await tx.raw_get(ss.RESUME_VERSIONS, ss.version_key(user_id, last + 1)) is not None:
                    raise UniqueViolationError(ss.RESUME_VERSIONS, "")
                if str(r.id) not in current and await tx.raw_get(ss.RESUMES, str(r.id)) is not None:
                    raise UniqueViolationError(ss.RESUMES, str(r.id))
                cur_docs = await tx.get_many(ss.RESUMES, current)
                r.version_no = last + 1
                for d in cur_docs.values():
                    if d.get("is_current"):
                        await tx.update_read(ss.RESUMES, d, {"is_current": False})
                tx.raw_create(
                    ss.RESUME_VERSIONS,
                    ss.version_key(user_id, r.version_no),
                    {"resume_id": str(r.id), "created_at": now},
                )
                d = await tx.create(ss.RESUMES, _new(r, now), doc_id=str(r.id))
                return orm_of(Resume, d.data)

            try:
                return await self.store.run_transaction(fn)
            except UniqueViolationError as e:
                if e.collection in (ss.RESUMES, "lms_" + ss.RESUMES):
                    raise
                continue
        raise conflict()

    async def complete_pdf(self, user_id: uuid.UUID, resume_id: uuid.UUID, key: str, now: datetime) -> Resume:
        """Check the pending upload key and promote it, in one transaction (the Postgres
        ``FOR UPDATE`` on the résumé): a concurrent complete or a new upload cannot interleave."""

        async def fn(tx: ScopedTransaction) -> Resume:
            cur = await tx.get(ss.RESUMES, str(resume_id))
            if cur is None or cur.get("user_id") != str(user_id):
                raise ProblemError("not_found")
            if not cur.get("pdf_pending_key") or key != cur.get("pdf_pending_key"):
                msg = "This upload was not started for this résumé."
                raise ProblemError(
                    "validation_failed", errors=[{"field": "key", "code": "invalid", "message": msg}]
                )
            d = await tx.update_read(
                ss.RESUMES, cur, {"pdf_s3_key": key, "pdf_pending_key": None, "pdf_uploaded_at": now}
            )
            return orm_of(Resume, d.data)

        return await self.store.run_transaction(fn)

    async def update_resume(
        self, user_id: uuid.UUID, resume_id: uuid.UUID, changes: dict[str, Any]
    ) -> Resume:
        return orm_of(Resume, (await self.store.update(ss.RESUMES, str(resume_id), changes)).data)

    # ================================================================== erasure (DB-01)

    async def erase_user(self, user_id: uuid.UUID) -> dict[str, int]:
        st = self.store
        resumes = await self._all(ss.RESUMES, user_id=user_id)
        for d in resumes:
            await st.delete(ss.RESUMES, d.id)
            k = await st.get(ss.RESUME_VERSIONS, ss.version_key(user_id, d["version_no"]))
            if k is not None:
                await st.delete(ss.RESUME_VERSIONS, k.id)
        return {"resumes_deleted": len(resumes)}


def repo(job: str = "mentoring.service") -> MentoringRepo:
    return MentoringRepo(ScopedStore.system(job))
