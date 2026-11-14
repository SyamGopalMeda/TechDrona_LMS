"""Lint: raw Firestore access exists only inside ``app/core/firestore/`` (MIGRATION-PLAN §1.4).

Admin-SDK traffic bypasses ``firestore.rules``; the ``ScopedStore`` checks are the only
authorization layer, so nothing else may open a client, a collection or a transaction.
``firebase_admin.auth`` (ID-token verification, P1) is allowed — it touches no data.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

API_DIR = Path(__file__).resolve().parents[2]
APP_DIR = API_DIR / "app"
STORE_DIR = APP_DIR / "core" / "firestore"
REPO_ROOT = API_DIR.parents[1]

FORBIDDEN_MODULES = ("google.cloud.firestore", "google.cloud.firestore_v1", "firebase_admin.firestore")
PRIVATE_STORE_MODULES = ("app.core.firestore.client",)


def _violations(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    out: list[str] = []
    label = str(path.relative_to(API_DIR)) if API_DIR in path.parents else path.name
    for node in ast.walk(tree):
        names: list[str] = []
        if isinstance(node, ast.Import):
            names = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            names = [node.module] + [f"{node.module}.{a.name}" for a in node.names]
        for n in names:
            if n.startswith(FORBIDDEN_MODULES) or n.startswith(PRIVATE_STORE_MODULES):
                out.append(f"{label}:{node.lineno} imports {n}")
                break
        if isinstance(node, ast.Call):
            fn = node.func
            # firebase_admin.firestore.client() / firestore_async.client() via an attribute chain
            if isinstance(fn, ast.Attribute) and fn.attr == "client" and isinstance(fn.value, ast.Attribute):
                if fn.value.attr in {"firestore", "firestore_async"}:
                    out.append(f"{label}:{node.lineno} calls {fn.value.attr}.client()")
    return out


def test_no_raw_firestore_outside_store_layer() -> None:
    bad: list[str] = []
    for path in APP_DIR.rglob("*.py"):
        if STORE_DIR in path.parents:
            continue
        bad += _violations(path)
    assert not bad, "raw Firestore access outside app/core/firestore/:\n" + "\n".join(bad)


def test_lint_catches_a_violation(tmp_path: Path) -> None:
    sample = API_DIR / "tests" / "firestore" / "_lint_sample.py"
    try:
        sample.write_text(
            "from google.cloud import firestore\nfrom app.core.firestore.client import get_client\n"
            "import firebase_admin.firestore_async as fa\n",
            encoding="utf-8",
        )
        assert len(_violations(sample)) >= 3
    finally:
        sample.unlink(missing_ok=True)


def test_lms_repo_never_deploys_firestore_rules() -> None:
    """billing-f4fe3 has ONE Firestore database shared by three modules (web_*, lms_*, col_*).

    The project's single rules file lives in the company-website repo, the only module whose
    browsers read Firestore directly. It has no match block for lms_* or col_* collections, so
    browsers are denied there; tests/fees.security.test.mjs "S1" in that repo proves it. If this
    repo deployed its own rules, it would replace the website's rules and break the website,
    so firebase.json here must carry indexes only, and no rules file may linger.
    """
    cfg = json.loads((REPO_ROOT / "firebase.json").read_text(encoding="utf-8"))
    assert "rules" not in cfg["firestore"]
    assert cfg["firestore"]["indexes"] == "firestore.indexes.json"
    assert not (REPO_ROOT / "firestore.rules").exists()


def test_lms_collections_and_indexes_live_under_lms_prefix() -> None:
    """Every LMS collection, index and TTL policy is under lms_*, never web_* or col_*."""
    from app.core.firestore.collections import LMS_PREFIX, physical_name

    assert physical_name("courses") == "lms_courses"
    assert physical_name("uniq_email") == "lms_uniq_email"
    assert physical_name("lms_courses") == "lms_courses"  # never doubled
    spec = json.loads((REPO_ROOT / "firestore.indexes.json").read_text(encoding="utf-8"))
    groups = {i["collectionGroup"] for i in spec["indexes"]} | {
        o["collectionGroup"] for o in spec.get("fieldOverrides", [])
    }
    assert groups and all(g.startswith(LMS_PREFIX) for g in groups), sorted(groups)


def test_firebase_json_fixed_emulator_ports() -> None:
    cfg = json.loads((REPO_ROOT / "firebase.json").read_text(encoding="utf-8"))
    assert cfg["firestore"]["location"] == "asia-south1"
    em = cfg["emulators"]
    assert em["firestore"]["port"] == 18080 and em["auth"]["port"] == 19099
    stack_ports = {5432, 6379, 6380, 1025, 8025, 9000, 18000, 18001, 13000, 8001, 15432, 16380}
    used = [v["port"] for v in em.values() if isinstance(v, dict) and "port" in v]
    assert not set(used) & stack_ports
    assert (
        json.loads((REPO_ROOT / ".firebaserc").read_text(encoding="utf-8"))["projects"]["default"]
        == "billing-f4fe3"
    )
