"""Firestore repository for feature flags and policy settings (``TD_STORE_ADMIN=firestore``).

The Postgres code paths in ``flags.py`` / ``policy.py`` / ``router.py`` dispatch here when the
switch is on; the HTTP contract is unchanged. Rows come back as ``FlagRow`` / ``PolicyRow`` with
the same attribute names (and Python types) as the ORM models, so serializers are shared.

Authorization (replacing "RLS: NONE" + router checks): routes keep their permission checks
(``feature_flag.manage``, ``policy.edit``/``policy.propose`` + dual control, case decisions).
The repository is built from ``ScopedStore(principal)`` where a principal acts (flag PATCH,
listing) and from a named system job where Postgres used a system/internal read
(``admin.flags``, ``admin.policy``); every method is ``@platform_only``.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, fields
from datetime import datetime
from typing import Any

from app.core.errors import ProblemError
from app.core.firestore.repository import FirestoreRepository, platform_only
from app.core.firestore.store import ScopedStore, ScopedTransaction
from app.core.ids import uuid7
from app.core.time import utcnow
from app.modules.admin.store_specs import FLAGS, POLICY, POLICY_HEADS, head_id

FLAG_PERM = "feature_flag.manage"
POLICY_PERM = "policy.edit"


def _uuid(v: Any) -> uuid.UUID | None:
    return uuid.UUID(str(v)) if v else None


@dataclass
class FlagRow:
    id: uuid.UUID
    flag_key: str
    description: str
    is_enabled: bool
    rollout_percent: int
    user_allowlist: list[uuid.UUID]
    updated_by: uuid.UUID | None = None

    @classmethod
    def of(cls, d: dict[str, Any]) -> FlagRow:
        return cls(
            id=uuid.UUID(d["id"]),
            flag_key=d["flag_key"],
            description=d.get("description") or "",
            is_enabled=bool(d.get("is_enabled")),
            rollout_percent=int(d.get("rollout_percent") or 0),
            user_allowlist=[uuid.UUID(x) for x in d.get("user_allowlist") or []],
            updated_by=_uuid(d.get("updated_by")),
        )


@dataclass
class PolicyRow:
    id: uuid.UUID
    setting_key: str
    scope_type: str
    scope_id: uuid.UUID | None
    value: Any
    value_schema: str
    min_value: Any
    max_value: Any
    plan_overridable: bool
    locked: bool
    version: int
    is_active: bool
    effective_from: datetime
    expires_at: datetime | None
    case_decision_id: uuid.UUID | None
    change_reason: str
    changed_by: uuid.UUID
    approved_by: uuid.UUID | None
    approval_request_id: uuid.UUID | None
    created_at: datetime

    _UUIDS = ("scope_id", "case_decision_id", "approved_by", "approval_request_id")

    @classmethod
    def of(cls, d: dict[str, Any]) -> PolicyRow:
        kw: dict[str, Any] = {f.name: d.get(f.name) for f in fields(cls)}
        kw["id"] = uuid.UUID(d["id"])
        kw["changed_by"] = uuid.UUID(d["changed_by"])
        for k in cls._UUIDS:
            kw[k] = _uuid(d.get(k))
        return cls(**kw)

    def live(self, now: datetime) -> bool:
        return (
            self.is_active
            and self.effective_from <= now
            and (self.expires_at is None or self.expires_at > now)
        )


class AdminSettingsRepo(FirestoreRepository):
    # ------------------------------------------------------------------ flags

    @platform_only(FLAG_PERM)
    async def list_flags(self) -> list[FlagRow]:
        from app.core.firestore.collation import order_key

        out: list[FlagRow] = []
        cursor: str | None = None
        while True:
            # read in document-id order (the flag key), then ORDER BY flag_key as Postgres does:
            # Firestore orders text by raw bytes, the VM database by its en_US collation
            page = await self.store.query(FLAGS, order_by=(), limit=100, cursor=cursor)
            out += [FlagRow.of(d.data) for d in page.items]
            if not page.next_cursor:
                return sorted(out, key=lambda f: order_key(f.flag_key))
            cursor = page.next_cursor

    @platform_only(FLAG_PERM)
    async def get_flag(self, key: str) -> FlagRow | None:
        d = await self.store.get(FLAGS, key)
        return FlagRow.of(d.data) if d else None

    @platform_only(FLAG_PERM)
    async def patch_flag(self, key: str, changes: dict[str, Any], by: uuid.UUID) -> tuple[FlagRow, FlagRow]:
        """(before, after); ``not_found`` for an unknown key (flags are created by migrations)."""

        async def fn(tx: ScopedTransaction) -> tuple[FlagRow, FlagRow]:
            cur = await tx.get(FLAGS, key)
            if cur is None:
                raise ProblemError("not_found")
            upd = {**changes, "updated_by": by}
            if "user_allowlist" in upd:
                upd["user_allowlist"] = [str(u) for u in upd["user_allowlist"]]
            after = await tx.update(FLAGS, key, upd)
            return FlagRow.of(cur.data), FlagRow.of(after.data)

        return await self.store.run_transaction(fn)

    # ------------------------------------------------------------------ policy reads

    @platform_only(POLICY_PERM)
    async def active_rows(self, scopes: list[tuple[str, str, Any]]) -> list[PolicyRow]:
        """Active rows for ``(setting_key, scope_type, scope_id)`` triples (two batched reads)."""
        heads = await self.store.get_many(POLICY_HEADS, [head_id(*s) for s in scopes])
        ids = [h["active_id"] for h in heads.values() if h.get("active_id")]
        rows = await self.store.get_many(POLICY, ids)
        return [PolicyRow.of(r.data) for r in rows.values()]

    @platform_only(POLICY_PERM)
    async def history(self, key: str) -> list[PolicyRow]:
        """Every version of a key, newest first (``created_at desc``, as the Postgres route)."""
        out: list[PolicyRow] = []
        cursor: str | None = None
        while True:
            page = await self.store.query(
                POLICY,
                filters=(("setting_key", "==", key),),
                order_by=(("created_at", "desc"),),
                limit=100,
                cursor=cursor,
            )
            out += [PolicyRow.of(d.data) for d in page.items]
            if not page.next_cursor:
                return out
            cursor = page.next_cursor

    @platform_only(POLICY_PERM)
    async def user_exception_count(self, subject_id: uuid.UUID, now: datetime) -> int:
        """Active, unexpired user-scope rows of one user (security HC-01 exclusion)."""
        page = await self.store.query(
            POLICY,
            filters=(
                ("scope_type", "==", "user"),
                ("scope_id", "==", str(subject_id)),
                ("is_active", "==", True),
            ),
            order_by=(),
            limit=100,
        )
        return sum(1 for d in page.items if d.get("expires_at") is not None and d["expires_at"] > now)

    # ------------------------------------------------------------------ policy writes

    @platform_only(POLICY_PERM)
    async def write_version(self, row: dict[str, Any]) -> PolicyRow:
        """Deactivate the scope's active row and insert ``row`` as the next version, atomically.

        ``policy_heads`` serialises concurrent writers of one key+scope (Firestore aborts and
        retries the loser), so versions stay unique and exactly one row is active."""
        hid = head_id(row["setting_key"], row["scope_type"], row["scope_id"])
        new_id = row.get("id") or str(uuid7())

        async def fn(tx: ScopedTransaction) -> PolicyRow:
            head = await tx.get(POLICY_HEADS, hid)
            old = await tx.get(POLICY, head["active_id"]) if head and head.get("active_id") else None
            version = int(head["version"]) + 1 if head else 1
            now = utcnow()
            data = {
                **row,
                "id": new_id,
                "version": version,
                "is_active": True,
                "effective_from": row.get("effective_from") or now,
            }
            if old is not None:
                await tx.put(POLICY, old.id, {**old.data, "is_active": False})
            created = await tx.create(POLICY, data, doc_id=new_id)
            await tx.put(
                POLICY_HEADS,
                hid,
                {
                    "setting_key": row["setting_key"],
                    "scope_type": row["scope_type"],
                    "scope_id": row["scope_id"],
                    "active_id": new_id,
                    "version": version,
                },
            )
            return PolicyRow.of(created.data)

        return await self.store.run_transaction(fn)


def system_repo(job: str) -> AdminSettingsRepo:
    return AdminSettingsRepo(ScopedStore.system(job))
