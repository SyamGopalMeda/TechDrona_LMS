"""ScopedStore on the Firestore emulator: authorization families, transactions, uniqueness,
counters, pagination, leases and the retry-safety guard."""

from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import Any

import pytest

from app.core.errors import ProblemError
from app.core.firestore.collections import CollectionSpec, register_collection, unregister_collection
from app.core.firestore.errors import (
    ExternalIOInTransactionError,
    NotFoundError,
    StoreAccessDeniedError,
    TransactionTooLargeError,
    UniqueViolationError,
)
from app.core.firestore.ids import compose_id
from app.core.firestore.repository import FirestoreRepository, assert_repository_scoped, platform_only
from app.core.firestore.store import ScopedStore, ScopedTransaction, forbid_in_transaction, in_transaction

NOTES = CollectionSpec(
    "t_notes",
    "owned",
    read_permission="notes.read_any",
    write_permission="notes.manage",
    ttl=timedelta(days=30),
)
COURSES = CollectionSpec("t_courses", "shared", write_permission="catalog.manage")
SECRETS = CollectionSpec(
    "t_secrets", "shared", read_permission="secrets.read", write_permission="secrets.manage"
)
LEDGER = CollectionSpec("t_ledger", "owned", owner_writes=True, append_only=True)
JOBS = CollectionSpec("t_jobs", "system")
SPECS = (NOTES, COURSES, SECRETS, LEDGER, JOBS)


@pytest.fixture(autouse=True)
def _specs() -> Any:
    for s in SPECS:
        register_collection(s)
    yield
    for s in SPECS:
        unregister_collection(s.name)


@pytest.fixture
def people(make_principal: Any, auth: Any) -> dict[str, Any]:
    alice, bob, staff = make_principal(), make_principal(), make_principal(tier="staff")
    for perm in ("notes.read_any", "notes.manage", "catalog.manage", "secrets.read"):
        auth.grant(staff, perm)
    return {"alice": alice, "bob": bob, "staff": staff}


def st(p: Any, client: Any) -> ScopedStore:
    return ScopedStore(p, client=client)


# ---------------------------------------------------------------- authorization families


async def test_owned_rows_are_invisible_to_other_users(fs_client: Any, people: dict[str, Any]) -> None:
    a, b, staff = (st(people[k], fs_client) for k in ("alice", "bob", "staff"))
    doc = await a.create("t_notes", {"user_id": people["alice"].user_id, "text": "mine"})
    assert doc["schema_version"] == 1 and doc["created_at"] == doc["updated_at"]
    assert doc["expire_at"] - doc["created_at"] == timedelta(days=30)

    assert (await a.get("t_notes", doc.id))["text"] == "mine"
    assert await b.get("t_notes", doc.id) is None  # RLS-style: not found, not forbidden
    assert (await staff.get("t_notes", doc.id)) is not None  # staff with notes.read_any

    with pytest.raises(NotFoundError):
        await b.update("t_notes", doc.id, {"text": "pwned"})
    with pytest.raises(NotFoundError):
        await b.delete("t_notes", doc.id)
    # Bob cannot plant a row owned by Alice, nor steal hers.
    with pytest.raises(StoreAccessDeniedError):
        await b.create("t_notes", {"user_id": people["alice"].user_id, "text": "x"})
    with pytest.raises(StoreAccessDeniedError):
        await a.update("t_notes", doc.id, {"user_id": people["bob"].user_id})
    updated = await a.update("t_notes", doc.id, {"text": "edited"})
    assert updated["text"] == "edited" and updated["updated_at"] >= doc["updated_at"]
    with pytest.raises(ValueError):
        await a.update("t_notes", doc.id, {"created_at": doc["created_at"]})


async def test_owned_queries_must_name_the_user(fs_client: Any, people: dict[str, Any]) -> None:
    a, b, staff = (st(people[k], fs_client) for k in ("alice", "bob", "staff"))
    await a.create("t_notes", {"user_id": people["alice"].user_id, "text": "a"})
    await b.create("t_notes", {"user_id": people["bob"].user_id, "text": "b"})
    assert [d["text"] for d in (await a.query("t_notes", user_id=people["alice"].user_id)).items] == ["a"]
    with pytest.raises(StoreAccessDeniedError):
        await a.query("t_notes")  # all users
    with pytest.raises(StoreAccessDeniedError):
        await a.query("t_notes", user_id=people["bob"].user_id)
    assert len((await staff.query("t_notes")).items) == 2
    assert (
        await staff.count("t_notes") == 2 and await a.count("t_notes", user_id=people["alice"].user_id) == 1
    )


async def test_shared_and_system_families(fs_client: Any, people: dict[str, Any]) -> None:
    a, staff = st(people["alice"], fs_client), st(people["staff"], fs_client)
    with pytest.raises(StoreAccessDeniedError):
        await a.create("t_courses", {"title": "x"})
    c = await staff.create("t_courses", {"title": "Python"}, doc_id="python")
    assert (await a.get("t_courses", c.id))["title"] == "Python"  # any principal reads shared rows
    s = await ScopedStore.system("test.seed", client=fs_client).create("t_secrets", {"v": 1})
    assert await a.get("t_secrets", s.id) is None and await staff.get("t_secrets", s.id) is not None
    with pytest.raises(StoreAccessDeniedError):
        await a.query("t_secrets")
    with pytest.raises(StoreAccessDeniedError):
        await staff.create("t_jobs", {"k": 1})  # system family: named jobs only
    j = await ScopedStore.system("test.job", client=fs_client).create("t_jobs", {"k": 1})
    assert await staff.get("t_jobs", j.id) is None
    with pytest.raises(KeyError):
        await a.get("t_unregistered", "x")
    with pytest.raises(TypeError):
        ScopedStore(None, client=fs_client)  # type: ignore[arg-type]


async def test_append_only(fs_client: Any, people: dict[str, Any]) -> None:
    a = st(people["alice"], fs_client)
    row = await a.create("t_ledger", {"user_id": people["alice"].user_id, "event": "granted"})
    with pytest.raises(StoreAccessDeniedError):
        await a.update("t_ledger", row.id, {"event": "revoked"})
    with pytest.raises(StoreAccessDeniedError):
        await a.delete("t_ledger", row.id)
    await ScopedStore.system("retention.purge", client=fs_client).delete("t_ledger", row.id)


# ---------------------------------------------------------------- uniqueness, transactions, counters


async def test_deterministic_id_uniqueness(fs_client: Any, people: dict[str, Any]) -> None:
    a = st(people["alice"], fs_client)
    eid = compose_id(people["alice"].user_id, "course-1")
    await a.create("t_notes", {"user_id": people["alice"].user_id}, doc_id=eid)
    with pytest.raises(UniqueViolationError):
        await a.create("t_notes", {"user_id": people["alice"].user_id}, doc_id=eid)

    async def twice(tx: ScopedTransaction) -> None:
        await tx.create("t_notes", {"user_id": people["alice"].user_id}, doc_id=eid)

    with pytest.raises(UniqueViolationError):
        await a.run_transaction(twice)


async def test_unique_reservation_is_atomic_with_the_row(fs_client: Any, people: dict[str, Any]) -> None:
    a, b = st(people["alice"], fs_client), st(people["bob"], fs_client)

    def signup(p: Any, email: str) -> Any:
        async def fn(tx: ScopedTransaction) -> str:
            await tx.reserve_unique("email", email, owner=("t_notes", str(p.user_id)))
            await tx.create("t_notes", {"user_id": p.user_id, "email": email}, doc_id=str(p.user_id))
            return str(p.user_id)

        return fn

    await a.run_transaction(signup(people["alice"], "Asha@Example.in"))
    with pytest.raises(UniqueViolationError):
        await b.run_transaction(signup(people["bob"], "asha@example.in "))
    assert await b.get("t_notes", str(people["bob"].user_id)) is None  # nothing half-written

    async def release(tx: ScopedTransaction) -> bool:
        return await tx.release_unique(
            "email", "asha@example.in", owner=("t_notes", str(people["alice"].user_id))
        )

    assert await a.run_transaction(release) is True
    await b.run_transaction(signup(people["bob"], "asha@example.in"))


async def test_failed_transaction_writes_nothing(fs_client: Any, people: dict[str, Any]) -> None:
    a = st(people["alice"], fs_client)

    async def boom(tx: ScopedTransaction) -> None:
        await tx.create("t_notes", {"user_id": people["alice"].user_id}, doc_id="half")
        raise RuntimeError("validation failed after the first write")

    with pytest.raises(RuntimeError):
        await a.run_transaction(boom)
    assert await a.get("t_notes", "half") is None


async def test_gap_free_sequence_under_concurrency(fs_client: Any, people: dict[str, Any]) -> None:
    sys_store = ScopedStore.system("test.numbers", client=fs_client)

    async def take(tx: ScopedTransaction) -> int:
        n = await tx.next_sequence("order_number")
        await tx.create("t_jobs", {"n": n}, doc_id=f"order-{n}")
        return n

    got = await asyncio.gather(*(sys_store.run_transaction(take, max_attempts=20) for _ in range(8)))
    assert sorted(got) == list(range(1, 9))
    assert {
        d["n"] for d in (await sys_store.query("t_jobs", order_by=(("n", "asc"),), limit=20)).items
    } == set(range(1, 9))


async def test_external_io_is_forbidden_inside_transactions(fs_client: Any, people: dict[str, Any]) -> None:
    a = st(people["alice"], fs_client)
    sent: list[str] = []

    async def send_email() -> None:
        forbid_in_transaction("email send")
        sent.append("mail")

    async def bad(tx: ScopedTransaction) -> None:
        await send_email()

    with pytest.raises(ExternalIOInTransactionError):
        await a.run_transaction(bad)

    async def good(tx: ScopedTransaction) -> str:
        assert in_transaction()
        d = await tx.create("t_notes", {"user_id": people["alice"].user_id})
        tx.after_commit(send_email)
        return d.id

    await a.run_transaction(good)
    assert sent == ["mail"] and not in_transaction()


async def test_transaction_write_cap(fs_client: Any, people: dict[str, Any]) -> None:
    sys_store = ScopedStore.system("test.bulk", client=fs_client)

    async def big(tx: ScopedTransaction) -> None:
        for i in range(401):
            await tx.create("t_jobs", {"i": i})

    with pytest.raises(TransactionTooLargeError):
        await sys_store.run_transaction(big)


# ---------------------------------------------------------------- pagination and leases


async def test_cursor_pagination_is_stable_and_signed(fs_client: Any, people: dict[str, Any]) -> None:
    a = st(people["alice"], fs_client)
    uid = people["alice"].user_id
    for i in range(7):  # same rank for pairs -> the document id breaks ties
        await a.create("t_notes", {"user_id": uid, "rank": i // 2}, doc_id=f"n{i}")
    seen: list[str] = []
    cursor = None
    while True:
        page = await a.query("t_notes", user_id=uid, order_by=(("rank", "desc"),), limit=3, cursor=cursor)
        seen += [d.id for d in page.items]
        assert page.meta()["has_more"] == (page.next_cursor is not None)
        if not page.has_more:
            break
        cursor = page.next_cursor
    assert seen == ["n6", "n5", "n4", "n3", "n2", "n1", "n0"]
    first = await a.query("t_notes", user_id=uid, order_by=(("rank", "desc"),), limit=3)
    with pytest.raises(ProblemError):  # a cursor is bound to its query shape
        await a.query("t_notes", user_id=uid, order_by=(("rank", "asc"),), cursor=first.next_cursor)
    with pytest.raises(ProblemError):
        await a.query("t_notes", user_id=uid, cursor="tampered.value")
    # datetime keys round-trip through the cursor
    by_time = await a.query("t_notes", user_id=uid, limit=4)
    rest = await a.query("t_notes", user_id=uid, limit=4, cursor=by_time.next_cursor)
    assert len(by_time.items) == 4 and len(rest.items) == 3
    assert not {d.id for d in by_time.items} & {d.id for d in rest.items}


async def test_leases(fs_client: Any) -> None:
    s = ScopedStore.system("audit.sealer", client=fs_client)
    assert await s.claim_lease("audit_sealer", "w1", timedelta(seconds=30))
    assert not await s.claim_lease("audit_sealer", "w2", timedelta(seconds=30))
    assert await s.claim_lease("audit_sealer", "w1", timedelta(seconds=30))  # renew
    assert not await s.release_lease("audit_sealer", "w2")
    assert await s.release_lease("audit_sealer", "w1")
    assert await s.claim_lease("audit_sealer", "w2", timedelta(seconds=30))


# ---------------------------------------------------------------- repository contract


class _GoodRepo(FirestoreRepository):
    async def list_for_user(self, user_id: Any) -> Any:
        return await self.store.query("t_notes", user_id=user_id)

    @platform_only("notes.read_any")
    async def list_everyone(self) -> Any:
        return await self.store.query("t_notes")


class _BadRepo(FirestoreRepository):
    async def list_everyone(self) -> Any:
        return await self.store.query("t_notes")


async def test_repository_contract(fs_client: Any, people: dict[str, Any]) -> None:
    assert_repository_scoped(_GoodRepo)
    with pytest.raises(AssertionError, match="list_everyone"):
        assert_repository_scoped(_BadRepo)
    with pytest.raises(StoreAccessDeniedError):
        await _GoodRepo(st(people["alice"], fs_client)).list_everyone()
    assert (await _GoodRepo(st(people["staff"], fs_client)).list_everyone()).items == []
