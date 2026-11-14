"""The API function never imports ``app.worker``; a job kick from a request must still resolve
its schedule entry (found live 2026-11-13: ``LookupError: unknown periodic job 'core.outbox_relay'``
failed the commit of POST admin/users and POST me/consents)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

API = Path(__file__).resolve().parents[2]


def test_entry_for_resolves_without_worker_import() -> None:
    code = (
        "import sys; from app.main import create_app; create_app();"
        "from app.core.scheduler import entry_for;"
        "print(entry_for('core.outbox_relay').task)"
    )
    r = subprocess.run([sys.executable, "-c", code], cwd=API, capture_output=True, text=True, timeout=180)  # noqa: S603 - fixed code, own interpreter
    assert r.returncode == 0, r.stderr[-2000:]
    assert r.stdout.strip()
