"""Load the role/permission catalogue (``app.modules.rbac.catalogue``) into ``roles``,
``permissions`` and ``role_permissions``.

Reference data (not demo data): safe in every environment. Idempotent upsert keyed by
``role_key`` / ``permission_key``; role_permissions rows not in the catalogue are removed so
the database always equals the role matrix. Ids are deterministic (UUIDv5) so every
environment agrees.

Run: ``python -m app.seeds.rbac_seed`` (uses DATABASE_MIGRATION_URL: td_app cannot write
these tables). Migration ``rbac_0002`` calls ``sync(connection)``.
"""

from __future__ import annotations

import re
import uuid

from sqlalchemy import Connection, text

from app.modules.rbac.catalogue import PERMISSIONS, ROLES, role_permission_pairs

_NS = uuid.UUID("6f1c2a9e-5d1b-4f7a-9c1e-2b7d3e4f5a60")


def role_id(key: str) -> uuid.UUID:
    return uuid.uuid5(_NS, f"role:{key}")


def permission_id(key: str) -> uuid.UUID:
    return uuid.uuid5(_NS, f"permission:{key}")


def _role_keys_allowed_by_schema(conn: Connection) -> frozenset[str] | None:
    """Role keys the ``roles.role_key`` CHECK currently accepts (``None`` = no such CHECK).

    ``rbac_0002`` (applied long ago) syncs the *live* catalogue against the rbac_0001 CHECK,
    which predates roles added later (``evaluator``); those are skipped there and added by the
    revision that widens the CHECK (``rbac_0004``), which calls ``sync`` again."""
    defs = conn.execute(
        text(
            "SELECT pg_get_constraintdef(c.oid) FROM pg_constraint c "
            "WHERE c.conrelid = 'roles'::regclass AND c.contype = 'c' "
            "AND pg_get_constraintdef(c.oid) LIKE '%role_key%'"
        )
    ).scalars()
    keys: set[str] | None = None
    for d in defs:
        found = set(re.findall(r"'([a-z_]+)'", d))
        keys = found if keys is None else keys & found
    return frozenset(keys) if keys is not None else None


def sync(conn: Connection) -> dict[str, int]:
    allowed = _role_keys_allowed_by_schema(conn)
    roles = [r for r in ROLES.values() if allowed is None or r.key in allowed]
    for r in roles:
        conn.execute(
            text(
                "INSERT INTO roles (id, role_key, name, session_tier, mfa_required, allowed_scope_types, "
                "is_system) "
                "VALUES (:id, :k, :n, :t, :m, :s, true) ON CONFLICT (role_key) DO UPDATE SET "
                "name = EXCLUDED.name, session_tier = EXCLUDED.session_tier, "
                "mfa_required = EXCLUDED.mfa_required, "
                "allowed_scope_types = EXCLUDED.allowed_scope_types"
            ),
            {
                "id": role_id(r.key),
                "k": r.key,
                "n": r.name,
                "t": r.session_tier,
                "m": r.mfa_required,
                "s": list(r.allowed_scope_types),
            },
        )
    for p in PERMISSIONS.values():
        conn.execute(
            text(
                "INSERT INTO permissions (id, permission_key, module, description, is_sensitive) "
                "VALUES (:id, :k, :m, :d, :s) ON CONFLICT (permission_key) DO UPDATE SET "
                "module = EXCLUDED.module, description = EXCLUDED.description, "
                "is_sensitive = EXCLUDED.is_sensitive"
            ),
            {"id": permission_id(p.key), "k": p.key, "m": p.module, "d": p.description, "s": p.is_sensitive},
        )
    role_keys = {r.key for r in roles}
    pairs = [(r, p) for r, p in role_permission_pairs() if r in role_keys]
    conn.execute(
        text(
            "DELETE FROM role_permissions rp USING roles r, permissions p "
            "WHERE rp.role_id = r.id AND rp.permission_id = p.id "
            "AND NOT ((r.role_key || '|' || p.permission_key) = ANY (:keep))"
        ),
        {"keep": [f"{r}|{p}" for r, p in pairs]},
    )
    for role, perm in pairs:
        conn.execute(
            text(
                "INSERT INTO role_permissions (role_id, permission_id) "
                "SELECT r.id, p.id FROM roles r, permissions p "
                "WHERE r.role_key = :r AND p.permission_key = :p "
                "ON CONFLICT DO NOTHING"
            ),
            {"r": role, "p": perm},
        )
    return {"roles": len(roles), "permissions": len(PERMISSIONS), "role_permissions": len(pairs)}


def main() -> None:  # pragma: no cover - CLI
    from sqlalchemy import create_engine

    from app.core.config import get_settings

    url = get_settings().migration_url
    for prefix in ("postgresql+asyncpg://", "postgresql+psycopg2://", "postgresql://"):
        if url.startswith(prefix):
            url = "postgresql+psycopg://" + url[len(prefix) :]
    engine = create_engine(url)
    with engine.begin() as conn:
        print(sync(conn))
    engine.dispose()


if __name__ == "__main__":  # pragma: no cover
    main()
