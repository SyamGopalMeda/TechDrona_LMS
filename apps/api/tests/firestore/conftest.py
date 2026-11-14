"""Firestore emulator fixtures (docs/firebase/p0.md §Tests).

* Uses a running emulator at ``TD_TEST_FIRESTORE_EMULATOR_HOST`` / ``FIRESTORE_EMULATOR_HOST``
  (default ``127.0.0.1:18080``, the firebase.json port) when one answers.
* Otherwise starts the Firestore emulator jar from the Firebase CLI cache with Java (small heap)
  and stops it at session end. ``TD_TEST_FIRESTORE_AUTOSTART=0`` disables that.
* No emulator and no Java/jar -> the emulator tests SKIP with a message saying what to install.

Each test gets a fresh ``AsyncClient`` (gRPC channels are bound to the test's event loop) on a
per-run ``demo-*`` project whose documents are wiped before the test.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import httpx
import pytest

DEFAULT_HOST = "127.0.0.1:18080"
TEST_PROJECT = "demo-" + os.environ.get("TD_TEST_DB_NAME", "techdrona-test").replace("_", "-").lower()[:24]
HOW_TO = (
    "Firestore emulator unavailable. Install Java 11+ (winget install EclipseAdoptium.Temurin.21.JDK) "
    "and the Firebase CLI (npm i -g firebase-tools), then run `firebase emulators:start --only firestore` "
    "from the repo root, or let this fixture start the cached jar."
)


def _host() -> str:
    return (
        os.environ.get("TD_TEST_FIRESTORE_EMULATOR_HOST")
        or os.environ.get("FIRESTORE_EMULATOR_HOST")
        or DEFAULT_HOST
    )


def _alive(host: str) -> bool:
    try:
        return httpx.get(f"http://{host}/", timeout=1.0).status_code == 200
    except httpx.HTTPError:
        return False


def _find_jar() -> Path | None:
    cache = Path.home() / ".cache" / "firebase" / "emulators"
    jars = sorted(cache.glob("cloud-firestore-emulator-*.jar"))
    return jars[-1] if jars else None


@pytest.fixture(scope="session")
def firestore_emulator() -> Iterator[str]:
    host = _host()
    if _alive(host):
        yield host
        return
    java, jar = shutil.which("java"), _find_jar()
    if os.environ.get("TD_TEST_FIRESTORE_AUTOSTART") == "0" or not java or not jar:
        pytest.skip(HOW_TO)
    h, _, port = host.rpartition(":")
    proc = subprocess.Popen(  # noqa: S603 - fixed argv, local emulator only
        [java, "-Xmx384m", "-jar", str(jar), f"--host={h}", f"--port={port}"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.monotonic() + 60
        while not _alive(host):
            if proc.poll() is not None or time.monotonic() > deadline:
                pytest.skip(HOW_TO + f" (auto-start on {host} failed)")
            time.sleep(0.5)
        yield host
    finally:
        _stop_tree(proc)


def _stop_tree(proc: subprocess.Popen[bytes]) -> None:
    """On Windows ``javapath/java.exe`` is a launcher that spawns the real JVM: kill the tree."""
    if sys.platform == "win32":
        subprocess.run(  # noqa: S603 - fixed argv
            ["taskkill", "/T", "/F", "/PID", str(proc.pid)],  # noqa: S607
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    else:
        proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()


def clear_emulator(host: str, project: str = TEST_PROJECT) -> None:
    r = httpx.delete(
        f"http://{host}/emulator/v1/projects/{project}/databases/(default)/documents", timeout=60.0
    )
    r.raise_for_status()


@pytest.fixture
async def fs_client(firestore_emulator: str, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[object]:
    from app.core.config import Settings
    from app.core.firestore.client import aclose, make_client

    monkeypatch.setenv("FIRESTORE_EMULATOR_HOST", firestore_emulator)
    clear_emulator(firestore_emulator)
    s = Settings(  # type: ignore[call-arg]
        _env_file=None,
        APP_ENV="test",
        FIRESTORE_EMULATOR_HOST=firestore_emulator,
        FIREBASE_PROJECT_ID=TEST_PROJECT,
    )
    client = make_client(s)
    assert client.project == TEST_PROJECT
    try:
        yield client
    finally:
        await aclose(client)
