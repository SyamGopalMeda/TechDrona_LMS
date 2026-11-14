"""Code scan: no function of the admin module runs SQL without a Firestore branch.

A function "runs SQL" when it calls ``session.execute/get/add/scalar/scalars/delete/merge``
or builds a statement with SQLAlchemy ``select/update/delete/insert/text/func``. It is accepted
when the same function also branches on the store: a call to ``uses_firestore`` / ``_fs`` /
``fs`` / ``postgres_enabled``, or a test of ``session`` truthiness (``if session`` /
``if not session``: the request session is ``NO_POSTGRES``, falsy, on the Firebase stack), or
when its name ends in ``_pg`` (a Postgres-only helper; every call site must itself be guarded,
which this scan checks too).
"""

from __future__ import annotations

import ast
from pathlib import Path

ADMIN = Path(__file__).resolve().parents[3] / "app" / "modules" / "admin"
SQL_ATTRS = {"execute", "get", "add", "scalar", "scalars", "delete", "merge", "add_all"}
SQL_FUNCS = {"select", "update", "delete", "insert", "text", "pg_insert"}
GUARD_CALLS = {"uses_firestore", "_fs", "fs", "postgres_enabled", "_pg_enabled"}
SKIP_FILES = {
    "models.py",
    "store_specs.py",
    "fs_rows.py",
}  # ORM / backfill mappings (Postgres reads by design)


def _is_session(node: ast.AST) -> bool:
    return isinstance(node, ast.Name) and node.id in {"session", "db", "s"}


def _runs_sql(fn: ast.AST) -> list[int]:
    lines: list[int] = []
    for n in ast.walk(fn):
        if not isinstance(n, ast.Call):
            continue
        f = n.func
        if isinstance(f, ast.Attribute) and f.attr in SQL_ATTRS and _is_session(f.value):
            lines.append(n.lineno)
        elif isinstance(f, ast.Name) and f.id in SQL_FUNCS:
            lines.append(n.lineno)
    return lines


def _guarded(fn: ast.AST) -> bool:
    for n in ast.walk(fn):
        if isinstance(n, ast.Call):
            f = n.func
            name = f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else ""
            if name in GUARD_CALLS:
                return True
        if isinstance(n, (ast.If, ast.IfExp)):
            t = n.test
            if isinstance(t, ast.UnaryOp) and isinstance(t.op, ast.Not):
                t = t.operand
            if _is_session(t):
                return True
            if isinstance(t, ast.BoolOp) and any(_is_session(v) for v in t.values):
                return True
    return False


def _functions(tree: ast.AST) -> list[ast.FunctionDef | ast.AsyncFunctionDef]:
    return [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]


def _innermost(fn: ast.AST) -> ast.AST:
    """The function without its nested functions (they are scanned on their own)."""
    clone = ast.parse(ast.unparse(fn)).body[0]
    for n in ast.walk(clone):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n is not clone:
            n.body = [ast.Pass()]
    return clone


def scan() -> list[str]:
    bad: list[str] = []
    pg_helpers: set[str] = set()
    trees = {}
    for path in sorted(ADMIN.glob("*.py")):
        if path.name in SKIP_FILES:
            continue
        trees[path] = ast.parse(path.read_text(encoding="utf-8"))
    for path, tree in trees.items():
        for fn in _functions(tree):
            if fn.name.endswith("_pg"):
                pg_helpers.add(fn.name)
                continue
            body = _innermost(fn)
            lines = _runs_sql(body)
            if lines and not _guarded(body):
                # a nested function inherits the guard of its enclosing function
                parents = [p for p in _functions(tree) if p is not fn and any(c is fn for c in ast.walk(p))]
                if not any(_guarded(_innermost(p)) for p in parents):
                    bad.append(f"{path.name}:{fn.lineno} {fn.name} (SQL at lines {lines})")
    # every call of a *_pg helper must sit in a guarded function
    for path, tree in trees.items():
        for fn in _functions(tree):
            calls = {
                n.func.id
                for n in ast.walk(_innermost(fn))
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in pg_helpers
            }
            if calls and not fn.name.endswith("_pg") and not _guarded(_innermost(fn)):
                bad.append(f"{path.name}:{fn.lineno} {fn.name} calls Postgres-only {sorted(calls)} unguarded")
    return bad


def test_every_admin_sql_path_has_a_firestore_branch() -> None:
    bad = scan()
    assert bad == [], "admin functions running SQL with no Firestore branch:\n" + "\n".join(bad)


if __name__ == "__main__":
    print("\n".join(scan()) or "clean")
