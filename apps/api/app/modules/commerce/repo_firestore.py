"""Commerce on Firestore (``TD_STORE_COMMERCE=firestore``).

The engine (SQL interpreter, unit of work, optimistic commit, RLS emulation) is shared with
admissions and lives in ``app/core/firestore/sqlstore.py``. Commerce's tables, RLS families,
unique constraints, money CHECKs and the ``ex_price_overlap`` commit check are ``store_specs.SPEC``.
This module keeps the commerce-facing names and the ledger invariants.
"""

from __future__ import annotations

from typing import Any

from app.core.firestore.repository import FirestoreRepository, platform_only
from app.core.firestore.sqlstore import (
    CheckViolation,
    Interpreter,
    Result,
    Scope,
    UnsupportedStatement,
    tables_of,
)
from app.core.firestore.sqlstore import UnitOfWork as _UnitOfWork
from app.core.firestore.sqlstore import run as _run
from app.core.firestore.sqlstore import visible as _visible
from app.core.firestore.store import ScopedStore
from app.modules.commerce.store_specs import SPEC

JOB = "commerce"
PLATFORM = "commerce.platform"  # held by no role: only the system job passes @platform_only


def UnitOfWork(client: Any = None) -> _UnitOfWork:
    return _UnitOfWork(SPEC, client=client)


def visible(table: str, obj: Any, scope: Scope) -> bool:
    return _visible(SPEC, table, obj, scope)


async def run(uow: _UnitOfWork, scope: Scope, stmt: Any) -> Result:
    return await _run(uow, scope, stmt)


class CommerceRepo(FirestoreRepository):
    """Typed entry points outside the SQL path (verification, invariants).
    Platform-only: request code goes through the engine, which applies the per-row RLS."""

    @platform_only(PLATFORM)
    async def invariants(self) -> list[str]:
        """Ledger invariants (MIGRATION-PLAN §4.1 verify): refunds vs ``orders.refunded_paise``,
        coupon caps, contiguous invoice numbers per series/FY. Returns the violations."""
        problems: list[str] = []
        orders = {d.id: d.data for d in await self.store.scan("orders")}
        committed: dict[str, int] = {}
        for d in await self.store.scan("refunds"):
            r = d.data
            if r.get("status") in ("approved", "processing", "processed"):
                committed[r["order_id"]] = committed.get(r["order_id"], 0) + int(r["amount_paise"])
        for oid, o in orders.items():
            ref = int(o.get("refunded_paise") or 0)
            if ref > int(o["total_paise"]) or ref < 0:
                problems.append(f"order {oid}: refunded_paise {ref} outside [0, total]")
            if committed.get(oid, 0) > int(o["total_paise"]):
                problems.append(f"order {oid}: refunds exceed the total")
        for c in await self.store.scan("coupons"):
            mx = c.data.get("max_redemptions")
            if mx is not None and int(c.data.get("redeemed_count") or 0) > int(mx):
                problems.append(f"coupon {c.id}: redeemed_count above max_redemptions")
        series: dict[str, list[int]] = {}
        for inv in await self.store.scan("invoices"):
            prefix, _, n = str(inv.data["invoice_number"]).rpartition("/")
            series.setdefault(prefix, []).append(int(n))
        for prefix, ns in series.items():
            ns.sort()
            if ns != list(range(ns[0], ns[0] + len(ns))):
                problems.append(f"invoice series {prefix}: numbers not contiguous")
        return problems


def repo(client: Any = None) -> CommerceRepo:
    return CommerceRepo(ScopedStore.system(JOB, client=client))


__all__ = [
    "CheckViolation",
    "CommerceRepo",
    "Interpreter",
    "Result",
    "Scope",
    "UnitOfWork",
    "UnsupportedStatement",
    "repo",
    "run",
    "tables_of",
    "visible",
]
