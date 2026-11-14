"""Prepare functions-lms/ for `firebase deploy --only functions:lms` (does NOT deploy).

1. Copy apps/api/app -> functions-lms/app (fresh copy; __pycache__, tests and .env files skipped).
   The function imports exactly the code the VM image runs.
2. Regenerate schedules.json from the beat registry (tools/gen_schedules.py).
3. Check that functions-lms/venv exists (the Firebase CLI loads main.py with it to discover the
   functions) and that every requirement is installed in it.

    python functions-lms/tools/build.py          (from the repo root, any Python 3.12+)
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
REPO = HERE.parent
API = REPO / "apps" / "api"
SKIP = shutil.ignore_patterns("__pycache__", "*.pyc", ".env", ".env.*", "tests")


def copy_app() -> None:
    dst = HERE / "app"
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(API / "app", dst, ignore=SKIP)
    print(f"copied {API / 'app'} -> {dst}")  # noqa: T201


def gen_schedules() -> None:
    py = API / ".venv" / ("Scripts" if sys.platform == "win32" else "bin") / "python"
    subprocess.run([str(py), str(HERE / "tools" / "gen_schedules.py")], cwd=API, check=True)  # noqa: S603


def check_venv() -> None:
    venv_py = HERE / "venv" / ("Scripts" if sys.platform == "win32" else "bin") / "python"
    if not venv_py.exists():
        sys.exit(
            "functions-lms/venv missing: python3.13 -m venv functions-lms/venv && "
            "functions-lms/venv/bin/pip install -r functions-lms/requirements.txt"
        )
    subprocess.run(
        [str(venv_py), "-m", "pip", "install", "-q", "-r", str(HERE / "requirements.txt")], check=True
    )  # noqa: S603


if __name__ == "__main__":
    gen_schedules()
    copy_app()
    check_venv()
    print("functions-lms is ready for: firebase deploy --only functions:lms --project billing-f4fe3")  # noqa: T201
