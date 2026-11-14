"""Prepare functions-lms/ for `firebase deploy --only functions:lms` (does NOT deploy).

1. Copy apps/api/app -> functions-lms/app (fresh copy; __pycache__, tests and .env files skipped).
   The function imports exactly the code the VM image runs.
2. Regenerate schedules.json from the beat registry (tools/gen_schedules.py).
3. Precompile main.py, lms_edge/ and app/ to bytecode (``__pycache__/*.cpython-313.pyc``,
   PEP 552 checked-hash pycs, so they never go stale whatever the file mtimes after upload). Google's Python
   buildpack precompiles only the pip dependencies, not the function source, so without this every
   cold start of every instance compiled ~430 source files before the first request
   (~2 s of CPU). Needs a Python 3.13 interpreter (runtime python313); skipped otherwise.
4. Check that functions-lms/venv exists (the Firebase CLI loads main.py with it to discover the
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


RUNTIME_PY = (3, 13)  # firebase.json "runtime": "python313"; .pyc files are per minor version

_COMPILE = r"""
import compileall, py_compile, sys
from pathlib import Path
root = Path(sys.argv[1])
mode = py_compile.PycInvalidationMode.CHECKED_HASH
ok = compileall.compile_file(str(root / "main.py"), quiet=1, force=True, invalidation_mode=mode)
for d in ("lms_edge", "app"):
    ok = compileall.compile_dir(str(root / d), quiet=1, force=True, invalidation_mode=mode, workers=1) and ok
sys.exit(0 if ok else 1)
"""


def precompile() -> None:
    """Ship bytecode with the source (see step 3 above). firebase.json no longer ignores
    ``__pycache__``/``*.pyc`` for this codebase; the venv and tools/ stay ignored."""
    py = API / ".venv" / ("Scripts" if sys.platform == "win32" else "bin") / "python"
    ver = subprocess.run(  # noqa: S603
        [str(py), "-c", "import sys; print('%d.%d' % sys.version_info[:2])"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    if ver != "%d.%d" % RUNTIME_PY:
        print(f"WARNING: {py} is Python {ver}, runtime is python313: bytecode NOT precompiled")  # noqa: T201
        return
    subprocess.run([str(py), "-c", _COMPILE, str(HERE)], check=True)  # noqa: S603
    print("precompiled main.py, lms_edge/, app/ (checked-hash .pyc)")  # noqa: T201


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
    precompile()
    check_venv()
    print("functions-lms is ready for: firebase deploy --only functions:lms --project billing-f4fe3")  # noqa: T201
