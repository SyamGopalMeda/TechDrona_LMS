"""Firestore repository of coding (``TD_STORE_CODING=firestore``; data model in ``store_specs``).

Slices built so far:

* encrypted test-case blobs (``blobstore.py``): ciphertext stored exactly as ``coding.crypto``
  produced it; documents over ``MAX_BLOB_BYTES`` are split into ``coding_test_case_blob_chunks``
  written in the same transaction as the blob document (so a blob of any size up to the
  transaction cap is stored), and reassembled on read;
* problem / test case / language / submission reads behind ``coding.public`` and the
  assessments interface of ``service.py``;
* ``create_submission``: the submission and its idempotency key in one transaction (Postgres
  ``UNIQUE (user_id, idempotency_key)``); the in-flight limit uses a lease on
  ``locks/coding_submit:{user}`` instead of ``pg_advisory_xact_lock``.

RLS: TN (problems, cases, blobs) and US/O (submissions, results, drafts, tokens) evaluated with
the caller's Postgres context (``visibility``; a copy of placement's, because coding may not
import placement).
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import DateTime, text

from app.core.errors import ProblemError
from app.core.firestore.errors import UniqueViolationError
from app.core.firestore.ids import compose_id
from app.core.firestore.repository import FirestoreRepository, platform_only
from app.core.firestore.store import Doc, ScopedStore, ScopedTransaction
from app.core.time import utcnow
from app.modules.coding.fsmap import to_doc_value
from app.modules.coding.models import (
    CodeSubmission,
    CodingDraft,
    CodingProblem,
    CodingProblemValidation,
    CodingReferenceSolution,
    CodingTestCase,
    CodingTestCaseBlob,
    CodingTestCaseContentToken,
    JudgeLanguage,
    SubmissionResult,
)
from app.modules.coding.store_specs import (
    BLOB_CHUNKS,
    BLOBS,
    CASES,
    DRAFTS,
    LANGUAGES,
    MAX_BLOB_BYTES,
    PROBLEMS,
    PROBLEMS_BY_SLUG,
    REF_SOLUTIONS,
    RESULTS,
    SUBMISSIONS,
    SUBMISSIONS_IDEM,
    TOKENS,
    VALIDATIONS,
    chunk_id,
    orm_doc,
    orm_of,
    slug_id,
    split_chunks,
)

HIDDEN_PERM = "coding_test_case.hidden.read"
MANAGE_PERM = "coding_problem.manage"
RESULTS_PERM = "test.results.read"
_PAGE = 300


@dataclass(frozen=True, slots=True)
class Visibility:
    user_id: str = ""
    org_ids: frozenset[str] = frozenset()
    is_platform: bool = False
    org_staff: bool = False

    def sees(self, org: Any) -> bool:
        return org is None or self.is_platform or str(org) in self.org_ids

    def sees_owned(self, user_id: Any, org: Any) -> bool:
        return (
            self.is_platform
            or (bool(self.user_id) and str(user_id) == self.user_id)
            or (org is not None and str(org) in self.org_ids and self.org_staff)
        )


SYSTEM_VIEW = Visibility(is_platform=True)
_GUC = text(
    "SELECT current_setting('app.user_id', true), current_setting('app.org_ids', true), "
    "current_setting('app.is_platform', true), app.caller_is_org_staff()"
)


async def visibility(session: Any) -> Visibility:
    """RLS context: Postgres GUCs, or (no Postgres) the request principal / system scope
    recorded by ``coding.rls``. ``session=None`` outside a request = system job (blob store)."""
    if session is None:
        return SYSTEM_VIEW
    if not session:
        from app.modules.coding.rls import current_scope

        uid, orgs, plat, staff = await current_scope()
        return Visibility(uid, orgs, plat, staff)
    from app.modules.coding.rls import memory_gucs

    guc = memory_gucs(session)
    if isinstance(guc, dict):
        # the SQL engine's ``MemoryTx`` (no Postgres): the RLS GUCs live in memory and there is no
        # ``app.caller_is_org_staff()``; org staff comes from the request principal, as above
        from app.modules.coding.rls import current_scope

        staff = (await current_scope())[3]
        return Visibility(
            str(guc.get("app.user_id") or ""),
            frozenset(o for o in str(guc.get("app.org_ids") or "").split(",") if o),
            guc.get("app.is_platform", "off") == "on",
            staff,
        )
    uid, orgs, plat, staff = (await session.execute(_GUC)).one()
    return Visibility(
        str(uid or ""),
        frozenset(o for o in (orgs or "").split(",") if o),
        (plat or "off") == "on",
        bool(staff),
    )


# =========================================================================== blobs


class CodingBlobRepo(FirestoreRepository):
    @platform_only(MANAGE_PERM)
    async def put(self, blob: CodingTestCaseBlob) -> None:
        if blob.created_at is None:
            blob.created_at = utcnow()
        data = bytes(blob.ciphertext)
        if len(data) <= MAX_BLOB_BYTES:
            await self.store.create(BLOBS, orm_doc(blob), doc_id=str(blob.id))
            return
        parts = split_chunks(data)
        head = orm_doc(blob)
        head["ciphertext"] = ""
        head["chunks"] = len(parts)

        async def fn(tx: ScopedTransaction) -> None:
            await tx.create(BLOBS, head, doc_id=str(blob.id))
            for n, part in enumerate(parts):
                piece = CodingTestCaseBlob(
                    id=blob.id,
                    coding_problem_id=blob.coding_problem_id,
                    organization_id=blob.organization_id,
                    ciphertext=part,
                    created_at=blob.created_at,
                )
                await tx.create(BLOB_CHUNKS, {**orm_doc(piece), "n": n}, doc_id=chunk_id(blob.id, n))

        await self.store.run_transaction(fn)

    @platform_only(HIDDEN_PERM)
    async def ciphertext(self, blob_id: uuid.UUID) -> bytes | None:
        d = await self.store.get(BLOBS, str(blob_id))
        if d is None:
            return None
        n = int(d.get("chunks") or 0)
        if not n:
            return orm_of(CodingTestCaseBlob, d.data).ciphertext
        parts = await self.store.get_many(BLOB_CHUNKS, [chunk_id(blob_id, i) for i in range(n)])
        if len(parts) != n:
            raise ProblemError("internal_error", detail="test case blob is incomplete")
        return b"".join(
            orm_of(CodingTestCaseBlob, parts[chunk_id(blob_id, i)].data).ciphertext for i in range(n)
        )


def blob_repo(*, write: bool) -> CodingBlobRepo:
    return CodingBlobRepo(ScopedStore.system("coding.blob_write" if write else "coding.blob_read"))


# =========================================================================== problems & submissions


class CodingRepo(FirestoreRepository):
    def __init__(self, store: ScopedStore, vis: Visibility) -> None:
        super().__init__(store)
        self.vis = vis

    async def _all(self, coll: str, filters: Sequence[Any] = (), order: str = "created_at") -> list[Doc]:
        out: list[Doc] = []
        cursor: str | None = None
        while True:
            page = await self.store.query(
                coll, filters=tuple(filters), order_by=((order, "asc"),), limit=_PAGE, cursor=cursor
            )
            out += page.items
            if not page.next_cursor:
                return out
            cursor = page.next_cursor

    @platform_only(MANAGE_PERM)
    async def get_problem(self, problem_id: Any) -> CodingProblem | None:
        d = await self.store.get(PROBLEMS, str(problem_id))
        return orm_of(CodingProblem, d.data) if d and self.vis.sees(d.get("organization_id")) else None

    @platform_only(MANAGE_PERM)
    async def problems_by_slug(self, slug: str) -> list[CodingProblem]:
        docs = await self._all(PROBLEMS, (("slug", "==", slug),))
        return [orm_of(CodingProblem, d.data) for d in docs if self.vis.sees(d.get("organization_id"))]

    @platform_only(MANAGE_PERM)
    async def problem_id_for_slug(self, organization_id: Any, slug: str) -> uuid.UUID | None:
        d = await self.store.get(PROBLEMS_BY_SLUG, slug_id(organization_id, slug))
        return uuid.UUID(d["problem_id"]) if d else None

    @platform_only(MANAGE_PERM)
    async def cases(self, problem_id: Any, version: int) -> list[CodingTestCase]:
        docs = await self._all(
            CASES,
            (("coding_problem_id", "==", str(problem_id)), ("problem_version", "==", version)),
            order="ordinal",
        )
        return [orm_of(CodingTestCase, d.data) for d in docs if self.vis.sees(d.get("organization_id"))]

    @platform_only(MANAGE_PERM)
    async def languages(self) -> list[JudgeLanguage]:
        from app.core.firestore.collation import sort_key

        rows = [orm_of(JudgeLanguage, d.data) for d in await self._all(LANGUAGES, order="language_key")]
        return sorted(rows, key=lambda x: sort_key(x.language_key))  # Postgres text order

    @platform_only(RESULTS_PERM)
    async def get_submission(self, submission_id: Any) -> CodeSubmission | None:
        d = await self.store.get(SUBMISSIONS, str(submission_id))
        if d is None or not self.vis.sees_owned(d.get("user_id"), d.get("organization_id")):
            return None
        return orm_of(CodeSubmission, d.data)

    async def submissions_of(self, user_id: uuid.UUID, filters: Iterable[Any] = ()) -> list[CodeSubmission]:
        out: list[Doc] = []
        cursor: str | None = None
        while True:
            page = await self.store.query(
                SUBMISSIONS,
                user_id=user_id,
                filters=tuple(filters),
                order_by=(("queued_at", "asc"),),
                limit=_PAGE,
                cursor=cursor,
            )
            out += page.items
            if not page.next_cursor:
                break
            cursor = page.next_cursor
        return [
            orm_of(CodeSubmission, d.data)
            for d in out
            if self.vis.sees_owned(d.get("user_id"), d.get("organization_id"))
        ]

    async def submission_by_idempotency(self, user_id: uuid.UUID, key: str) -> CodeSubmission | None:
        from app.core.firestore.ids import compose_id

        d = await self.store.get(SUBMISSIONS_IDEM, compose_id(str(user_id), key))
        return await self.get_submission(d["submission_id"]) if d else None

    async def create_submission(self, user_id: uuid.UUID, sub: CodeSubmission) -> tuple[CodeSubmission, bool]:
        """Insert with the idempotency key in one transaction; a repeat returns the stored one."""
        from app.core.firestore.ids import compose_id

        if str(sub.user_id) != str(user_id):
            raise ProblemError("permission_denied")
        iid = compose_id(str(user_id), sub.idempotency_key) if sub.idempotency_key else None

        async def fn(tx: ScopedTransaction) -> tuple[CodeSubmission, bool]:
            if iid is not None:
                prior = await tx.get(SUBMISSIONS_IDEM, iid)
                if prior is not None:
                    got = await tx.get(SUBMISSIONS, prior["submission_id"])
                    if got is not None:
                        return orm_of(CodeSubmission, got.data), False
            await tx.create(SUBMISSIONS, orm_doc(sub), doc_id=str(sub.id))
            if iid is not None:
                await tx.put(SUBMISSIONS_IDEM, iid, {"submission_id": str(sub.id), "user_id": str(user_id)})
            return sub, True

        return await self.store.run_transaction(fn)

    @platform_only(RESULTS_PERM)
    async def update_submission(
        self, submission_id: Any, changes: dict[str, Any], *, if_status: str | None = None
    ) -> bool:
        """Conditional update (``WHERE status = if_status``); False when the condition failed."""

        async def fn(tx: ScopedTransaction) -> bool:
            cur = await tx.get(SUBMISSIONS, str(submission_id))
            if cur is None or (if_status is not None and cur.get("status") != if_status):
                return False
            await tx.update_read(SUBMISSIONS, cur, changes)
            return True

        return await self.store.run_transaction(fn)

    # ------------------------------------------------------------------ round 3: problems (TN)

    @platform_only(MANAGE_PERM)
    async def problems(self, *, status: str | None = None) -> list[CodingProblem]:
        """Every visible problem (optionally one status), unordered."""
        flt = (("status", "==", status),) if status is not None else ()
        return [
            orm_of(CodingProblem, d.data)
            for d in await self._all(PROBLEMS, flt)
            if self.vis.sees(d.get("organization_id"))
        ]

    @platform_only(MANAGE_PERM)
    async def get_problems(self, ids: Iterable[Any]) -> list[CodingProblem]:
        docs = await self.store.get_many(PROBLEMS, [str(i) for i in ids])
        return [
            orm_of(CodingProblem, d.data) for d in docs.values() if self.vis.sees(d.get("organization_id"))
        ]

    @platform_only(MANAGE_PERM)
    async def create_problem(self, p: CodingProblem) -> CodingProblem:
        """Insert with the ``ux_cp_slug`` key document in one transaction. An existing slug is the
        same ``validation_failed`` as the Postgres pre-check; a concurrent loser gets ``conflict``."""
        fill_defaults(p)
        key = slug_id(p.organization_id, p.slug)

        async def fn(tx: ScopedTransaction) -> Doc:
            if await tx.get(PROBLEMS_BY_SLUG, key) is not None:
                raise duplicate_slug()
            await tx.create(PROBLEMS_BY_SLUG, {"problem_id": str(p.id)}, doc_id=key)
            return await tx.create(PROBLEMS, orm_doc(p), doc_id=str(p.id))

        try:
            d = await self.store.run_transaction(fn)
        except UniqueViolationError as e:
            raise conflict() from e
        return orm_of(CodingProblem, d.data)

    @platform_only(MANAGE_PERM)
    async def save_problem(
        self,
        p: CodingProblem,
        fields: Sequence[str],
        *,
        expect_version: int,
        new_cases: Sequence[CodingTestCase] = (),
    ) -> None:
        """Write the changed ``fields`` of ``p`` and insert ``new_cases`` atomically.

        Guards (Postgres: ``UNIQUE (coding_problem_id, problem_version, ordinal)`` on the inserted
        cases): the stored ``version_no`` must still be ``expect_version`` (two concurrent version
        bumps), and no stored case of the target version may already use a new case's ordinal (two
        concurrent case adds). Either race answers ``409 conflict``, like the unique violation."""
        for c in new_cases:
            fill_defaults(c)
        targets = sorted({c.problem_version for c in new_cases})

        async def fn(tx: ScopedTransaction) -> None:
            cur = await tx.get(PROBLEMS, str(p.id))
            if cur is None or not self.vis.sees(cur.get("organization_id")):
                raise ProblemError("not_found")
            if int(cur.get("version_no") or 0) != expect_version:
                raise conflict()
            taken: set[tuple[int, int]] = set()
            for v in targets:
                for d in await tx.query(
                    CASES, filters=(("coding_problem_id", "==", str(p.id)), ("problem_version", "==", v))
                ):
                    taken.add((v, int(d["ordinal"])))
            if any((c.problem_version, c.ordinal) in taken for c in new_cases):
                raise conflict()
            if fields:
                doc = orm_doc(p)
                await tx.update_read(PROBLEMS, cur, {f: doc[f] for f in fields})
            for c in new_cases:
                await tx.create(CASES, orm_doc(c), doc_id=str(c.id))

        await self.store.run_transaction(fn)
        if fields:
            p.updated_at = utcnow()  # coding_problems updated_at trigger

    @platform_only(MANAGE_PERM)
    async def get_case(self, case_id: Any) -> CodingTestCase | None:
        d = await self.store.get(CASES, str(case_id))
        return orm_of(CodingTestCase, d.data) if d and self.vis.sees(d.get("organization_id")) else None

    @platform_only(MANAGE_PERM)
    async def get_cases(self, ids: Iterable[Any]) -> list[CodingTestCase]:
        docs = await self.store.get_many(CASES, [str(i) for i in ids])
        return [
            orm_of(CodingTestCase, d.data) for d in docs.values() if self.vis.sees(d.get("organization_id"))
        ]

    @platform_only(HIDDEN_PERM)
    async def hidden_cases(self) -> list[CodingTestCase]:
        docs = await self._all(CASES, (("is_hidden", "==", True),))
        return [orm_of(CodingTestCase, d.data) for d in docs]

    @platform_only(HIDDEN_PERM)
    async def set_wrapped_keys(self, keys: dict[uuid.UUID, bytes]) -> None:
        items = list(keys.items())
        for i in range(0, len(items), 400):
            part = items[i : i + 400]

            async def fn(tx: ScopedTransaction, part: list[tuple[uuid.UUID, bytes]] = part) -> None:
                docs = await tx.get_many(CASES, [str(cid) for cid, _ in part])
                for cid, wrapped in part:
                    d = docs.get(str(cid))
                    if d is not None:
                        enc = to_doc_value(CodingTestCase.__table__.c.wrapped_data_key, wrapped)
                        await tx.update_read(CASES, d, {"wrapped_data_key": enc})

            await self.store.run_transaction(fn)

    # ------------------------------------------------------------------ reference solutions / validations

    @platform_only(MANAGE_PERM)
    async def ref_solutions(self, problem_id: Any) -> list[CodingReferenceSolution]:
        docs = await self._all(
            REF_SOLUTIONS, (("coding_problem_id", "==", str(problem_id)),), order="language_key"
        )
        from app.core.firestore.collation import sort_key

        rows = [
            orm_of(CodingReferenceSolution, d.data) for d in docs if self.vis.sees(d.get("organization_id"))
        ]
        return sorted(rows, key=lambda x: sort_key(x.language_key))  # ORDER BY language_key

    @platform_only(MANAGE_PERM)
    async def put_ref_solution(self, r: CodingReferenceSolution) -> CodingReferenceSolution:
        """Upsert on ``(coding_problem_id, language_key)`` (``ON CONFLICT DO UPDATE``)."""
        fill_defaults(r)
        rid = compose_id(str(r.coding_problem_id), r.language_key)

        async def fn(tx: ScopedTransaction) -> Doc:
            cur = await tx.get(REF_SOLUTIONS, rid)
            if cur is None:
                return await tx.create(REF_SOLUTIONS, orm_doc(r), doc_id=rid)
            if not self.vis.sees(cur.get("organization_id")):
                raise ProblemError("not_found")
            return await tx.update_read(
                REF_SOLUTIONS, cur, {"source_code": r.source_code, "updated_by": str(r.updated_by)}
            )

        return orm_of(CodingReferenceSolution, (await self.store.run_transaction(fn)).data)

    @platform_only(MANAGE_PERM)
    async def latest_validation(self, problem_id: Any) -> CodingProblemValidation | None:
        """``ORDER BY created_at DESC, id DESC LIMIT 1`` (the store's tie-break is the id)."""
        page = await self.store.query(
            VALIDATIONS,
            filters=(("coding_problem_id", "==", str(problem_id)),),
            order_by=(("created_at", "desc"),),
            limit=1,
        )
        for d in page.items:
            if self.vis.sees(d.get("organization_id")):
                return orm_of(CodingProblemValidation, d.data)
        return None

    @platform_only(MANAGE_PERM)
    async def validations_since(self, requested_by: Any, since: datetime) -> int:
        docs = await self._all(
            VALIDATIONS, (("requested_by", "==", str(requested_by)), ("created_at", ">", since))
        )
        return sum(1 for d in docs if self.vis.sees(d.get("organization_id")))

    @platform_only(MANAGE_PERM)
    async def create_validation(self, v: CodingProblemValidation) -> CodingProblemValidation:
        fill_defaults(v)
        await self.store.create(VALIDATIONS, orm_doc(v), doc_id=str(v.id))
        return v

    # ------------------------------------------------------------------ submissions (US)

    @platform_only(RESULTS_PERM)
    async def count_submissions(self, filters: Sequence[Any]) -> int:
        """All users (system-scoped counts: queue depth / position)."""
        return await self.store.count(SUBMISSIONS, filters=tuple(filters))

    @platform_only(RESULTS_PERM)
    async def all_submissions(self, filters: Sequence[Any], order: str = "queued_at") -> list[CodeSubmission]:
        docs = await self._all(SUBMISSIONS, filters, order=order)
        return [
            orm_of(CodeSubmission, d.data)
            for d in docs
            if self.vis.sees_owned(d.get("user_id"), d.get("organization_id"))
        ]

    async def add_submission(self, user_id: uuid.UUID, sub: CodeSubmission) -> CodeSubmission:
        """Insert (``UNIQUE (user_id, idempotency_key)``): a stored key answers ``409 conflict`` like
        the Postgres unique violation."""
        fill_defaults(sub)
        stored, created = await self.create_submission(user_id, sub)
        if not created:
            raise conflict()
        return stored

    @platform_only(RESULTS_PERM)
    async def results_of(self, sub: CodeSubmission) -> list[SubmissionResult]:
        out: list[Doc] = []
        cursor: str | None = None
        while True:
            page = await self.store.query(
                RESULTS,
                user_id=sub.user_id,
                filters=(("code_submission_id", "==", str(sub.id)),),
                order_by=(("ordinal", "asc"),),
                limit=_PAGE,
                cursor=cursor,
            )
            out += page.items
            if not page.next_cursor:
                break
            cursor = page.next_cursor
        return [
            orm_of(SubmissionResult, d.data)
            for d in out
            if self.vis.sees_owned(d.get("user_id"), d.get("organization_id"))
        ]

    @platform_only(RESULTS_PERM)
    async def record_judgement(
        self,
        submission_id: Any,
        results: Sequence[SubmissionResult],
        changes: dict[str, Any],
        event: dict[str, Any] | None = None,
    ) -> None:
        """Worker ``record``: the per-case results, the submission update and the
        ``submission.judged`` outbox event in one transaction (``UNIQUE (code_submission_id,
        ordinal)`` = the result document id)."""
        from app.core.firestore.core_store import emit_event_tx

        docs = [(compose_id(str(r.code_submission_id), str(r.ordinal)), orm_doc(r)) for r in results]
        enc = _encode(CodeSubmission, changes)

        async def fn(tx: ScopedTransaction) -> None:
            cur = await tx.get(SUBMISSIONS, str(submission_id))
            if cur is None:
                raise ProblemError("not_found")
            for rid, doc in docs:
                await tx.create(RESULTS, doc, doc_id=rid)
            await tx.update_read(SUBMISSIONS, cur, enc)
            if event is not None:
                emit_event_tx(tx, **event)

        await self.store.run_transaction(fn)

    @platform_only(RESULTS_PERM)
    async def set_submission(self, submission_id: Any, changes: dict[str, Any]) -> bool:
        """Unconditional ``UPDATE ... WHERE id = :id`` (typed values encoded like the mapper)."""
        return await self.update_submission(submission_id, _encode(CodeSubmission, changes))

    @platform_only(RESULTS_PERM)
    async def requeue_stale(self, cutoff: datetime) -> int:
        """``UPDATE ... SET status='queued', started_at=NULL WHERE status='running' AND
        started_at < cutoff`` (each row re-checked in its own transaction)."""
        docs = await self._all(
            SUBMISSIONS, (("status", "==", "running"), ("started_at", "<", cutoff)), order="started_at"
        )
        n = 0
        for d in docs:

            async def fn(tx: ScopedTransaction, sid: str = d.id) -> bool:
                cur = await tx.get(SUBMISSIONS, sid)
                if cur is None or cur.get("status") != "running":
                    return False
                started = cur.get("started_at")
                if started is None or started >= cutoff:
                    return False
                await tx.update_read(SUBMISSIONS, cur, {"status": "queued", "started_at": None})
                return True

            n += int(await self.store.run_transaction(fn))
        return n

    # ------------------------------------------------------------------ drafts (O)

    async def get_draft(self, user_id: uuid.UUID, problem_id: Any, language_key: str) -> CodingDraft | None:
        d = await self.store.get(DRAFTS, compose_id(str(user_id), str(problem_id), language_key))
        if d is None or str(d.get("user_id")) != str(user_id):
            return None
        return orm_of(CodingDraft, d.data)

    async def save_draft(
        self,
        user_id: uuid.UUID,
        draft: CodingDraft,
        *,
        window_start: datetime,
        per_minute: int,
        limited: Any,
    ) -> CodingDraft:
        """Insert or update the ``(user, problem, language)`` draft with the 20/min window counter,
        in one transaction (Postgres: ``ON CONFLICT DO NOTHING`` + ``SELECT ... FOR UPDATE``).
        ``limited()`` builds the error raised when the window is full (nothing is written)."""
        if str(draft.user_id) != str(user_id):
            raise ProblemError("permission_denied")
        fill_defaults(draft)
        did = compose_id(str(user_id), str(draft.coding_problem_id), draft.language_key)
        now = draft.updated_at

        async def fn(tx: ScopedTransaction) -> Doc:
            cur = await tx.get(DRAFTS, did)
            if cur is None:
                return await tx.create(DRAFTS, orm_doc(draft), doc_id=did)
            started = cur.get("window_started_at")
            if started is not None and started > window_start:
                if int(cur.get("window_count") or 0) >= per_minute:
                    raise limited()
                window: dict[str, Any] = {"window_count": int(cur.get("window_count") or 0) + 1}
            else:
                window = {"window_started_at": now, "window_count": 1}
            return await tx.update_read(DRAFTS, cur, {**window, "source_code": draft.source_code})

        return orm_of(CodingDraft, (await self.store.run_transaction(fn)).data)

    # ------------------------------------------------------------------ content tokens (O)

    async def token_requests_since(self, user_id: uuid.UUID, since: datetime) -> int:
        docs = await self._owned(TOKENS, user_id, (("created_at", ">", since),))
        return len({d.get("request_id") for d in docs})

    async def add_tokens(self, user_id: uuid.UUID, tokens: Sequence[CodingTestCaseContentToken]) -> None:
        if any(str(t.user_id) != str(user_id) for t in tokens):
            raise ProblemError("permission_denied")

        async def fn(tx: ScopedTransaction) -> None:
            for t in tokens:
                fill_defaults(t)
                doc = orm_doc(t)
                # Retention of the 30/h counter rows (Postgres: 30 days); ``expires_at`` is the
                # 5-minute link expiry and must not drive deletion (see coding.md, Requests).
                doc["expire_at"] = t.created_at + TOKEN_RETENTION
                await tx.create(TOKENS, doc, doc_id=bytes(t.token_hash).hex())

        await self.store.run_transaction(fn)

    async def redeem_token(
        self, user_id: uuid.UUID, token_hash: bytes, now: datetime
    ) -> CodingTestCaseContentToken | None:
        """Single use: ``UPDATE ... SET used_at = now WHERE hash AND user AND used_at IS NULL AND
        expires_at > now RETURNING *`` as one transaction (a concurrent second redeem gets None)."""
        tid = bytes(token_hash).hex()

        async def fn(tx: ScopedTransaction) -> Doc | None:
            cur = await tx.get(TOKENS, tid)
            if (
                cur is None
                or str(cur.get("user_id")) != str(user_id)
                or cur.get("used_at") is not None
                or not cur.get("expires_at")
                or cur.get("expires_at") <= now
            ):
                return None
            return await tx.update_read(TOKENS, cur, {"used_at": now})

        d = await self.store.run_transaction(fn)
        return orm_of(CodingTestCaseContentToken, d.data) if d is not None else None

    # ------------------------------------------------------------------ erasure

    async def _owned(
        self, coll: str, user_id: uuid.UUID, filters: Sequence[Any], order: str = "created_at"
    ) -> list[Doc]:
        out: list[Doc] = []
        cursor: str | None = None
        while True:
            page = await self.store.query(
                coll,
                user_id=user_id,
                filters=tuple(filters),
                order_by=((order, "asc"),),
                limit=_PAGE,
                cursor=cursor,
            )
            out += [d for d in page.items if self.vis.sees_owned(d.get("user_id"), d.get("organization_id"))]
            if not page.next_cursor:
                return out
            cursor = page.next_cursor

    async def erase_user(self, user_id: uuid.UUID, erased: str) -> dict[str, int]:
        """Privacy erasure (same effect and counts as ``privacy.erase_user`` on Postgres): delete
        drafts; clear submission content where ``source_code <> erased``; clear stdout excerpts."""
        drafts = await self._owned(DRAFTS, user_id, ())
        subs = [
            d
            for d in await self._owned(SUBMISSIONS, user_id, (), order="queued_at")
            if d.get("source_code") != erased
        ]
        outs = [
            d
            for d in await self._owned(RESULTS, user_id, (), order="ordinal")
            if d.get("stdout_excerpt") is not None
        ]
        n_drafts = n_subs = n_outs = 0

        async def _apply(coll: str, ids: list[str], op: str) -> int:
            done = 0
            for i in range(0, len(ids), 400):
                part = ids[i : i + 400]

                async def fn(tx: ScopedTransaction, part: list[str] = part) -> int:
                    got = await tx.get_many(coll, part)
                    k = 0
                    for doc_id in part:
                        cur = got.get(doc_id)
                        if cur is None:
                            continue
                        if op == "delete":
                            await tx.delete_read(coll, doc_id, cur.data)
                        elif op == "source":
                            if cur.get("source_code") == erased:
                                continue
                            await tx.update_read(
                                coll,
                                cur,
                                {
                                    "source_code": erased,
                                    "custom_input": None,
                                    "compile_output": None,
                                    "normalized_sha256": None,
                                },
                            )
                        else:
                            if cur.get("stdout_excerpt") is None:
                                continue
                            await tx.update_read(coll, cur, {"stdout_excerpt": None})
                        k += 1
                    return k

                done += await self.store.run_transaction(fn)
            return done

        n_drafts = await _apply(DRAFTS, [d.id for d in drafts], "delete")
        n_subs = await _apply(SUBMISSIONS, [d.id for d in subs], "source")
        n_outs = await _apply(RESULTS, [d.id for d in outs], "stdout")
        return {
            "coding_drafts_deleted": n_drafts,
            "code_submissions_cleared": n_subs,
            "submission_outputs_cleared": n_outs,
        }


# =========================================================================== helpers

TOKEN_RETENTION = timedelta(days=30)


def conflict() -> ProblemError:
    """What a Postgres unique violation answers (``core.errors.unique_conflict_problem``)."""
    return ProblemError(
        "conflict", detail="Another request changed this at the same time. Refresh and try again."
    )


def duplicate_slug() -> ProblemError:
    return ProblemError(
        "validation_failed",
        errors=[{"field": "slug", "code": "duplicate", "message": "A problem with this slug exists."}],
    )


def fill_defaults(obj: Any) -> Any:
    """Column defaults a Postgres INSERT would apply to a transient instance: Python-side scalar
    defaults (``version_no=1``, ``retry_count=0``, ...) and ``DEFAULT now()`` timestamps."""
    now = utcnow()
    for c in type(obj).__table__.columns:
        if getattr(obj, c.key) is not None:
            continue
        if c.default is not None and getattr(c.default, "is_scalar", False):
            setattr(obj, c.key, c.default.arg)
        elif c.server_default is not None and not c.nullable and isinstance(c.type, DateTime):
            setattr(obj, c.key, now)
    return obj


def _encode(model: Any, changes: dict[str, Any]) -> dict[str, Any]:
    cols = model.__table__.columns
    return {k: to_doc_value(cols[k], v) for k, v in changes.items()}


async def repo(session: Any) -> CodingRepo:
    return CodingRepo(ScopedStore.system("coding.read"), await visibility(session))


def system_repo(job: str) -> CodingRepo:
    """Platform-scope repository for named jobs (judge worker, erasure, key rotation)."""
    return CodingRepo(ScopedStore.system(job), SYSTEM_VIEW)
