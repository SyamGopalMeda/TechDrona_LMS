"""Regenerate functions-lms/schedules.json from the API's beat registry.

    cd apps/api && .venv/Scripts/python ../../functions-lms/tools/gen_schedules.py

Imports ``app.worker`` (task discovery + ``register_periodic`` calls, exactly what Celery beat
schedules) and writes one entry per beat job. ``tests/platform/test_schedules.py`` fails when the
file and the registry drift apart, so a new ``register_periodic`` cannot be forgotten.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
API = HERE.parent / "apps" / "api"


def build() -> list[dict[str, object]]:
    sys.path.insert(0, str(API))
    os.environ.setdefault("APP_ENV", "test")
    import app.worker  # noqa: F401 - registers every periodic job
    from app.core.cloudtasks import schedule_manifest

    return schedule_manifest()


def main() -> None:
    out = HERE / "schedules.json"
    out.write_text(json.dumps(build(), indent=2) + "\n", encoding="utf-8")
    print(f"wrote {out}")  # noqa: T201


if __name__ == "__main__":
    main()
