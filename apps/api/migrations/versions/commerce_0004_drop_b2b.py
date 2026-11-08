"""commerce: drop the B2B institution contracts, contract invoicing and college coupons

Revision ID: commerce_0004
Revises: commerce_0003
Create Date: 2026-11-07

Single-company LMS (docs/single-company/REMOVAL-PLAN.md §1.2, §5 step 5, owner decision D1; WS2).
B2C checkout, GST invoices with an optional buyer GSTIN (CGST/SGST/IGST) and credit notes stay.

1. **Archive first (D1).** Contract invoices are legal GST records (72 months): their rows are
   **kept** in ``invoices`` (with ``description`` / ``due_on``). Before anything is dropped, a
   snapshot is copied into the new platform-only, append-only table ``commerce_b2b_archive``:

   * ``contract_invoice`` — every invoice with a ``contract_id`` and every credit note against
     one: the invoice row, its order and order lines, the contract number / PO and the
     ``pdf_s3_key`` (the PDF object itself stays in the invoices bucket);
   * ``institution_contract`` — every contract row plus a snapshot of the college organization
     (GSTIN, billing name/address, state code — ``orgs_0003`` drops those columns);
   * ``college_coupon`` — every coupon that was restricted to an organization.

   When the migration runs from a checkout of the repository (``backups/`` exists next to
   ``apps/``) or ``TD_B2B_ARCHIVE_DIR`` is set, the same snapshot is also written as JSON
   files to ``backups/archived-contract-invoices/`` (one file per invoice / contract plus
   ``index.json``). Inside a container without that directory only the table is written;
   export it later with ``SELECT payload FROM commerce_b2b_archive``.
2. College coupons (``coupons.organization_id IS NOT NULL``) are expired, then the column is
   dropped. The coupons policies become "everyone may read, only platform may write" — what
   ``TN`` meant for rows without an organization (and DELETE is now platform-only too).
3. Products of kind ``institution_seat`` are retired; ``ck_product_no_institution_seat`` keeps
   the kind valid only for retired (historic) rows.
4. ``invoices.contract_id`` and the ``institution_contracts`` table are dropped.
5. RLS: ``orders``, ``order_items``, ``payments``, ``refunds`` and ``invoices`` move from family
   ``U`` (own rows + rows of the caller's organizations) to ``O`` (own rows only). The org branch
   only served the college coordinator; after ``orgs_0003`` re-homes the legacy B2B rows to the
   company organization it would expose them to every company member. FORCE RLS stays on.

Depends on ``entitlements_0003`` (drops the last FK into ``institution_contracts``). Must run
before ``orgs_0003_rehome_and_lock`` (the organization snapshot reads columns it drops).

Data migrations run as the table owner; FORCE RLS applies to the owner, so it is lifted for the
statements and restored in the same transaction.

Downgrade restores the schema (``institution_contracts`` with RLS ``T``, ``invoices.contract_id``,
``coupons.organization_id`` with ``TN``, the ``U`` policies) but **not** the data; it keeps
``commerce_b2b_archive`` (legal records). Restore the data from
``backups/techdrona-dev-before-college-removal-20261106.dump`` or from the archive table.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from alembic import op
from sqlalchemy import text
from sqlalchemy.engine import Connection

from app.core.migration_helpers import add_updated_at_trigger, enable_rls, rls_sql

revision: str = "commerce_0004"
down_revision: str | Sequence[str] | None = "commerce_0003"
branch_labels: str | Sequence[str] | None = None
# NB: never ``orgs_0002`` here (Alembic 1.20 drops it from alembic_version; see ws1.md §2).
depends_on: str | Sequence[str] | None = ("entitlements_0003", "orgs_0001")

USER_TABLES = ("orders", "order_items", "payments", "refunds", "invoices")
FORCED = (
    "invoices",
    "institution_contracts",
    "coupons",
    "products",
    "orders",
    "order_items",
    "payments",
    "refunds",
    "organizations",
    "commerce_b2b_archive",
)
ARCHIVE_SUBDIR = "archived-contract-invoices"


def _lift_force(conn: Connection, tables: Sequence[str]) -> list[str]:
    """Lift FORCE RLS (owner-run data migration) on the tables that have it; returns them."""
    forced = list(
        conn.execute(
            text(
                "SELECT relname FROM pg_class WHERE relname = ANY (:t) AND relkind IN ('r','p') "
                "AND relforcerowsecurity AND relnamespace = 'public'::regnamespace"
            ),
            {"t": list(tables)},
        ).scalars()
    )
    for t in forced:
        op.execute(f"ALTER TABLE {t} NO FORCE ROW LEVEL SECURITY")
    return forced


def _restore_force(tables: Sequence[str]) -> None:
    for t in tables:
        op.execute(f"ALTER TABLE {t} FORCE ROW LEVEL SECURITY")


def _swap_policy(table: str, old: str, family: str) -> None:
    op.execute(f"DROP POLICY IF EXISTS {old} ON {table}")
    op.execute(f"DROP POLICY IF EXISTS p_{family.lower()} ON {table}")
    for stmt in rls_sql(table, family):  # ENABLE, FORCE, CREATE POLICY
        op.execute(stmt)


def _has_table(conn: Connection, name: str) -> bool:
    return bool(conn.execute(text("SELECT to_regclass(:n) IS NOT NULL"), {"n": f"public.{name}"}).scalar())


def _has_column(conn: Connection, table: str, column: str) -> bool:
    return bool(
        conn.execute(
            text(
                "SELECT 1 FROM information_schema.columns "
                "WHERE table_schema = 'public' AND table_name = :t AND column_name = :c"
            ),
            {"t": table, "c": column},
        ).scalar()
    )


def _create_archive() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS commerce_b2b_archive (
          id                        uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
          record_type               text        NOT NULL
                                    CHECK (record_type IN ('contract_invoice','institution_contract','college_coupon')),
          source_id                 uuid        NOT NULL,
          original_organization_id  uuid        NULL,
          payload                   jsonb       NOT NULL,
          archived_by               text        NOT NULL,
          archived_at               timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT ux_b2b_archive_source UNIQUE (record_type, source_id)
        );
        COMMENT ON TABLE commerce_b2b_archive IS
          'Owner: commerce | RLS: platform read only | Retention: R-FIN (72 months) | PII: P2 | append-only; '
          'archived B2B contract invoices, contracts and college coupons (single company, D1)';
        """
    )
    op.execute("ALTER TABLE commerce_b2b_archive ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE commerce_b2b_archive FORCE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS p_platform_read ON commerce_b2b_archive")
    op.execute(
        "CREATE POLICY p_platform_read ON commerce_b2b_archive FOR SELECT TO td_app, td_readonly "
        "USING (app.is_platform())"
    )
    op.execute("REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON commerce_b2b_archive FROM td_app")


def _archive_rows() -> None:
    """Copy the B2B rows into ``commerce_b2b_archive`` (idempotent on ``(record_type, source_id)``)."""
    op.execute(
        """
        INSERT INTO commerce_b2b_archive (record_type, source_id, original_organization_id, payload, archived_by)
        SELECT 'institution_contract', c.id, c.organization_id,
               jsonb_build_object('contract', to_jsonb(c), 'organization', to_jsonb(o)),
               'commerce_0004'
          FROM institution_contracts c
          LEFT JOIN organizations o ON o.id = c.organization_id
        ON CONFLICT ON CONSTRAINT ux_b2b_archive_source DO NOTHING
        """
    )
    op.execute(
        """
        WITH ci AS (
          SELECT i.id FROM invoices i WHERE i.contract_id IS NOT NULL
          UNION
          SELECT cn.id FROM invoices cn
            JOIN invoices i ON i.id = cn.original_invoice_id
           WHERE i.contract_id IS NOT NULL
        )
        INSERT INTO commerce_b2b_archive (record_type, source_id, original_organization_id, payload, archived_by)
        SELECT 'contract_invoice', i.id, coalesce(i.organization_id, c.organization_id),
               jsonb_build_object(
                 'invoice', to_jsonb(i),
                 'order', to_jsonb(ord),
                 'order_items', coalesce(
                   (SELECT jsonb_agg(to_jsonb(oi) ORDER BY oi.id) FROM order_items oi WHERE oi.order_id = i.order_id),
                   '[]'::jsonb),
                 'contract_id', coalesce(i.contract_id, orig.contract_id),
                 'contract_number', c.contract_number,
                 'po_number', c.po_number,
                 'pdf_s3_key', i.pdf_s3_key
               ),
               'commerce_0004'
          FROM ci
          JOIN invoices i ON i.id = ci.id
          JOIN orders ord ON ord.id = i.order_id
          LEFT JOIN invoices orig ON orig.id = i.original_invoice_id
          LEFT JOIN institution_contracts c ON c.id = coalesce(i.contract_id, orig.contract_id)
        ON CONFLICT ON CONSTRAINT ux_b2b_archive_source DO NOTHING
        """
    )
    op.execute(
        """
        INSERT INTO commerce_b2b_archive (record_type, source_id, original_organization_id, payload, archived_by)
        SELECT 'college_coupon', cp.id, cp.organization_id, to_jsonb(cp), 'commerce_0004'
          FROM coupons cp
         WHERE cp.organization_id IS NOT NULL
        ON CONFLICT ON CONSTRAINT ux_b2b_archive_source DO NOTHING
        """
    )


def _archive_dir() -> Path | None:
    env = os.environ.get("TD_B2B_ARCHIVE_DIR")
    if env:
        return Path(env)
    here = Path(__file__).resolve()
    if len(here.parents) > 4:
        backups = here.parents[4] / "backups"  # <repo>/apps/api/migrations/versions/<this>
        if backups.is_dir():
            return backups / ARCHIVE_SUBDIR
    return None


def _safe(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", name)[:120] or "unnamed"


def _export_files(conn: Connection) -> None:
    """Best-effort JSON export of the archive to ``backups/archived-contract-invoices/``."""
    rows = conn.execute(
        text(
            "SELECT record_type, source_id::text, payload FROM commerce_b2b_archive "
            "WHERE record_type IN ('contract_invoice','institution_contract') ORDER BY record_type, source_id"
        )
    ).all()
    if not rows:
        return
    target = _archive_dir()
    if target is None:
        print(
            f"commerce_0004: {len(rows)} B2B records archived in commerce_b2b_archive; no backups/ "
            "directory here, so no JSON files were written (set TD_B2B_ARCHIVE_DIR to export)."
        )
        return
    try:
        target.mkdir(parents=True, exist_ok=True)
        index: list[dict[str, Any]] = []
        for record_type, source_id, raw in rows:
            payload = json.loads(raw) if isinstance(raw, str) else raw
            if record_type == "contract_invoice":
                number = str((payload.get("invoice") or {}).get("invoice_number") or source_id)
                fname = f"invoice-{_safe(number)}.json"
            else:
                number = str((payload.get("contract") or {}).get("contract_number") or source_id)
                fname = f"contract-{_safe(number)}.json"
            (target / fname).write_text(json.dumps(payload, indent=2, sort_keys=True, default=str), "utf-8")
            index.append(
                {"record_type": record_type, "source_id": source_id, "number": number, "file": fname}
            )
        (target / "index.json").write_text(
            json.dumps({"exported_by": "commerce_0004", "records": index}, indent=2), "utf-8"
        )
        print(f"commerce_0004: exported {len(index)} B2B records to {target}")
    except OSError as e:  # the table copy is the authoritative archive
        print(f"commerce_0004: JSON export to {target} failed ({e}); the archive table has the data")


def upgrade() -> None:
    conn = op.get_bind()
    _create_archive()
    forced = _lift_force(conn, FORCED)

    # 1. Archive (D1) — before any column or table is dropped.
    if _has_table(conn, "institution_contracts") and _has_column(conn, "invoices", "contract_id"):
        _archive_rows()
        _export_files(conn)

    # 2. College coupons: expire, then drop the organization column.
    if _has_column(conn, "coupons", "organization_id"):
        op.execute(
            """
            UPDATE coupons
               SET status = 'expired', valid_until = least(coalesce(valid_until, now()), now()),
                   updated_at = now()
             WHERE organization_id IS NOT NULL
            """
        )
    op.execute("DROP POLICY IF EXISTS p_tn ON coupons")
    op.execute("DROP POLICY IF EXISTS p_coupons_read ON coupons")
    op.execute("DROP POLICY IF EXISTS p_coupons_write ON coupons")
    op.execute("ALTER TABLE coupons DROP COLUMN IF EXISTS organization_id")
    op.execute("CREATE POLICY p_coupons_read ON coupons FOR SELECT TO td_app, td_readonly USING (true)")
    op.execute(
        "CREATE POLICY p_coupons_write ON coupons FOR ALL TO td_app, td_readonly "
        "USING (app.is_platform()) WITH CHECK (app.is_platform())"
    )

    # 3. Institution seat products are retired and may never be re-activated.
    op.execute(
        "UPDATE products SET status = 'retired', updated_at = now() "
        "WHERE product_kind = 'institution_seat' AND status <> 'retired'"
    )
    op.execute("ALTER TABLE products DROP CONSTRAINT IF EXISTS ck_product_no_institution_seat")
    op.execute(
        "ALTER TABLE products ADD CONSTRAINT ck_product_no_institution_seat "
        "CHECK (product_kind <> 'institution_seat' OR status = 'retired')"
    )

    # 4. Contract invoicing and the contracts table.
    op.execute("DROP INDEX IF EXISTS ix_inv_contract")
    op.execute("ALTER TABLE invoices DROP COLUMN IF EXISTS contract_id")
    op.execute("DROP TABLE IF EXISTS institution_contracts")

    # 5. Own rows only on the money tables.
    for t in USER_TABLES:
        _swap_policy(t, "p_u", "O")

    _restore_force([t for t in forced if t != "institution_contracts"])


def downgrade() -> None:
    """Schema only; restore the data from the dump or ``commerce_b2b_archive`` (see docstring)."""
    for t in USER_TABLES:
        _swap_policy(t, "p_o", "U")
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS institution_contracts (
          id                uuid PRIMARY KEY,
          organization_id   uuid        NOT NULL REFERENCES organizations(id),
          contract_number   text        NOT NULL UNIQUE,
          product_id        uuid        NOT NULL REFERENCES products(id),
          seat_count        int         NOT NULL CHECK (seat_count > 0),
          starts_on         date        NOT NULL,
          ends_on           date        NOT NULL,
          amount_paise      bigint      NOT NULL CHECK (amount_paise >= 0),
          price_per_seat_paise bigint   NULL CHECK (price_per_seat_paise >= 0),
          billing_schedule  text        NOT NULL DEFAULT 'upfront' CHECK (billing_schedule IN ('upfront','milestones')),
          po_number         text        NULL,
          order_id          uuid        NULL REFERENCES orders(id),
          dpa_version       text        NOT NULL,
          dpa_signed_at     timestamptz NOT NULL,
          data_return_days  smallint    NOT NULL DEFAULT 30,
          grace_days        smallint    NOT NULL DEFAULT 7 CHECK (grace_days BETWEEN 0 AND 60),
          reassignment_allowance int    NOT NULL CHECK (reassignment_allowance >= 0),
          reassignments_used int        NOT NULL DEFAULT 0 CHECK (reassignments_used >= 0),
          seats_burned      int         NOT NULL DEFAULT 0 CHECK (seats_burned >= 0),
          status            text        NOT NULL DEFAULT 'active' CHECK (status IN ('draft','active','expired','terminated')),
          version           int         NOT NULL DEFAULT 1,
          terminated_at     timestamptz NULL,
          created_by        uuid        NOT NULL REFERENCES users(id),
          created_at        timestamptz NOT NULL DEFAULT now(),
          updated_at        timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT ck_ic_dates CHECK (ends_on > starts_on),
          CONSTRAINT ck_ic_reassign CHECK (reassignments_used <= reassignment_allowance),
          CONSTRAINT ck_ic_terminated CHECK ((status = 'terminated') = (terminated_at IS NOT NULL))
        );
        CREATE INDEX IF NOT EXISTS ix_ic_org ON institution_contracts (organization_id);
        COMMENT ON TABLE institution_contracts IS 'Owner: commerce | RLS: T | Retention: R-FIN | PII: P2';

        ALTER TABLE invoices ADD COLUMN IF NOT EXISTS contract_id uuid NULL REFERENCES institution_contracts(id);
        CREATE INDEX IF NOT EXISTS ix_inv_contract ON invoices (contract_id) WHERE contract_id IS NOT NULL;

        ALTER TABLE products DROP CONSTRAINT IF EXISTS ck_product_no_institution_seat;
        """
    )
    enable_rls("institution_contracts", "T")
    add_updated_at_trigger("institution_contracts")
    op.execute("DROP POLICY IF EXISTS p_coupons_read ON coupons")
    op.execute("DROP POLICY IF EXISTS p_coupons_write ON coupons")
    op.execute(
        "ALTER TABLE coupons ADD COLUMN IF NOT EXISTS organization_id uuid NULL REFERENCES organizations(id)"
    )
    enable_rls("coupons", "TN")
