"""Helpers for hand-written Alembic migrations (module migrations import these).

    from app.core.migration_helpers import enable_rls, add_updated_at_trigger, revoke_app_writes

    def upgrade() -> None:
        op.execute("CREATE TABLE batches (...)")
        enable_rls("batches", "T")
        add_updated_at_trigger("batches")

Policy families per database-schema.md §2.2: ``T``, ``TN``, ``U``, ``O``.
"""

from __future__ import annotations

import re

from alembic import op

APP_ROLES = "td_app, td_readonly"

_IDENT = re.compile(r"^[a-z_][a-z0-9_]*$")

_PREDICATES: dict[str, tuple[str, str]] = {
    "T": (
        "organization_id = ANY (app.org_ids()) OR app.is_platform()",
        "organization_id = ANY (app.org_ids()) OR app.is_platform()",
    ),
    "TN": (
        "organization_id IS NULL OR organization_id = ANY (app.org_ids()) OR app.is_platform()",
        "(organization_id IS NULL AND app.is_platform()) OR organization_id = ANY (app.org_ids()) "
        "OR app.is_platform()",
    ),
    "U": (
        "user_id = app.user_id() OR (organization_id IS NOT NULL AND organization_id = ANY (app.org_ids())) "
        "OR app.is_platform()",
        "user_id = app.user_id() OR (organization_id IS NOT NULL AND organization_id = ANY (app.org_ids())) "
        "OR app.is_platform()",
    ),
    "O": ("user_id = app.user_id() OR app.is_platform()", "user_id = app.user_id() OR app.is_platform()"),
}


def _check(name: str) -> str:
    if not _IDENT.match(name):
        raise ValueError(f"not a plain identifier: {name!r}")
    return name


def rls_sql(table: str, family: str, roles: str = APP_ROLES) -> list[str]:
    t = _check(table)
    using, check = _PREDICATES[family]
    pol = f"p_{family.lower()}"
    return [
        f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY",
        f"ALTER TABLE {t} FORCE ROW LEVEL SECURITY",
        f"CREATE POLICY {pol} ON {t} FOR ALL TO {roles} USING ({using}) WITH CHECK ({check})",
    ]


def enable_rls(table: str, family: str, roles: str = APP_ROLES) -> None:
    for stmt in rls_sql(table, family, roles):
        op.execute(stmt)


def add_updated_at_trigger(table: str) -> None:
    t = _check(table)
    op.execute(
        f"CREATE TRIGGER trg_set_updated_at BEFORE UPDATE ON {t} "
        f"FOR EACH ROW EXECUTE FUNCTION app.set_updated_at()"
    )


def revoke_app_writes(table: str, keep_insert: bool = True) -> None:
    """Append-only tables: td_app may INSERT (optionally) and SELECT, never UPDATE/DELETE."""
    t = _check(table)
    op.execute(f"REVOKE UPDATE, DELETE, TRUNCATE ON {t} FROM td_app")
    if not keep_insert:
        op.execute(f"REVOKE INSERT ON {t} FROM td_app")
