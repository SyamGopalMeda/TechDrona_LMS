"""Module switch, startup gate, ids and codec (no emulator needed)."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from app.core.config import Settings
from app.core.firestore import checks
from app.core.firestore.backend import (
    MODULES,
    StoreConfigError,
    parse_backends,
    reset_store_backends,
    store_backend,
    uses_firestore,
)
from app.core.firestore.codec import decode_position_value, encode_position_value, to_store
from app.core.firestore.ids import compose_id, hashed_id, validate_id
from app.core.startup_checks import UnsafeConfigurationError, run_startup_checks

API_DIR = Path(__file__).resolve().parents[2]


def test_module_list_matches_backend_modules() -> None:
    on_disk = {
        p.name for p in (API_DIR / "app" / "modules").iterdir() if p.is_dir() and not p.name.startswith("_")
    }
    assert on_disk | {"core"} == MODULES


def test_default_is_postgres_and_switch_parses() -> None:
    assert set(parse_backends({}).values()) == {"postgres"}
    got = parse_backends({"TD_STORE_CATALOG": "firestore", "TD_STORE_ENGAGE": "pg", "TD_STORE_AI": ""})
    assert got["catalog"] == "firestore" and got["engage"] == "postgres" and got["ai"] == "postgres"


@pytest.mark.parametrize(
    "env",
    [{"TD_STORE_CATLOG": "firestore"}, {"TD_STORE_CATALOG": "shadow"}, {"TD_STORE_CATALOG": "mongo"}],
)
def test_switch_typos_are_errors(env: dict[str, str]) -> None:
    with pytest.raises(StoreConfigError):
        parse_backends(env)


def test_store_backend_reads_process_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TD_STORE_NOTIFICATIONS", "firestore")
    reset_store_backends()
    try:
        assert uses_firestore("notifications") and store_backend("catalog") == "postgres"
        with pytest.raises(StoreConfigError):
            store_backend("nope")
    finally:
        monkeypatch.undo()
        reset_store_backends()


def _s(**kw: object) -> Settings:
    return Settings(_env_file=None, **kw)  # type: ignore[arg-type]


def test_gate_production_refuses_missing_creds_and_emulator(tmp_path: Path) -> None:
    on = {"TD_STORE_CATALOG": "firestore"}
    assert checks.production_problems(_s(APP_ENV="prod"), {}) == []  # nothing on Firestore yet
    p = checks.production_problems(_s(APP_ENV="prod"), on)
    assert any("FIREBASE_PROJECT_ID" in x for x in p) and any("FIREBASE_SERVICE_ACCOUNT_FILE" in x for x in p)
    p = checks.production_problems(
        _s(APP_ENV="prod", FIRESTORE_EMULATOR_HOST="127.0.0.1:18080", FIREBASE_PROJECT_ID="demo-x"), on
    )
    assert any("EMULATOR" in x for x in p) and any("demo-*" in x for x in p)
    key = tmp_path / "sa.json"  # outside the repo (pytest tmp dir)
    key.write_text("{}", encoding="utf-8")
    ok = _s(APP_ENV="prod", FIREBASE_PROJECT_ID="techdrona-lms", FIREBASE_SERVICE_ACCOUNT_FILE=str(key))
    assert checks.production_problems(ok, on) == []
    missing = _s(
        APP_ENV="prod", FIREBASE_PROJECT_ID="techdrona-lms", FIREBASE_SERVICE_ACCOUNT_FILE=str(key) + "x"
    )
    assert any("readable" in x for x in checks.production_problems(missing, on))


def test_gate_refuses_key_inside_repo_in_every_env(monkeypatch: pytest.MonkeyPatch) -> None:
    inside = API_DIR / "sa.json"  # never created: the path alone is refused
    assert checks.always_problems(_s(FIREBASE_SERVICE_ACCOUNT_FILE=str(inside)), {})
    with pytest.raises(UnsafeConfigurationError, match="outside the repository"):
        run_startup_checks(_s(APP_ENV="local", FIREBASE_SERVICE_ACCOUNT_FILE=str(inside)))
    monkeypatch.setenv("TD_STORE_CATALOG", "fire-store")
    with pytest.raises(UnsafeConfigurationError, match="invalid store switch"):
        run_startup_checks(_s(APP_ENV="local"))


def test_ids_are_deterministic_and_unambiguous() -> None:
    u = uuid.UUID("01900000-0000-7000-8000-000000000001")
    assert compose_id(u, "super_admin", "platform") == f"{u}:super_admin:platform"
    assert compose_id("a:b", "c") != compose_id("a", "b:c")
    assert compose_id("x/y") == "x%2Fy"
    assert hashed_id("email", " A@B.in ") == hashed_id("email", "a@b.in")
    assert hashed_id("email", "a@b.in") != hashed_id("mobile", "a@b.in")
    for bad in ("", ".", "..", "__x__", "a/b"):
        with pytest.raises(ValueError):
            validate_id(bad)
    with pytest.raises(TypeError):
        compose_id(1.5)


def test_codec() -> None:
    ist = timezone(timedelta(hours=5, minutes=30))
    out = to_store(
        {
            "u": uuid.UUID(int=1),
            "d": date(2026, 1, 2),
            "t": (1, 2),
            "at": datetime(2026, 1, 1, 5, 30, tzinfo=ist),
        }
    )
    assert out["u"] == str(uuid.UUID(int=1)) and out["d"] == "2026-01-02" and out["t"] == [1, 2]
    assert out["at"] == datetime(2026, 1, 1, tzinfo=UTC) and out["at"].tzinfo == UTC
    with pytest.raises(ValueError):
        to_store({"at": datetime(2026, 1, 1)})  # naive
    with pytest.raises(TypeError):
        to_store({"amount": Decimal("1.10")})
    now = datetime(2026, 1, 1, 1, 2, 3, 456789, tzinfo=UTC)
    assert decode_position_value(encode_position_value(now)) == now
