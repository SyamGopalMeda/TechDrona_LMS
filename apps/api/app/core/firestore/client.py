"""Firestore client factory. PRIVATE to ``app.core.firestore`` — modules use ``ScopedStore``.

* Emulator (dev/tests): ``FIRESTORE_EMULATOR_HOST`` set -> anonymous credentials, project
  ``FIREBASE_PROJECT_ID`` or ``demo-techdrona-lms``. A ``demo-*`` id can never reach a real project.
* Real project (staging/prod): Firebase Admin SDK app initialised from the service-account JSON at
  ``FIREBASE_SERVICE_ACCOUNT_FILE`` (outside the repo; startup gate enforces it) and
  ``FIREBASE_PROJECT_ID``.

The async gRPC channel is bound to the event loop that created it: the cached client is for the
app's single loop; tests build one per test with ``make_client`` and pass it to ``ScopedStore``.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from google.auth.credentials import AnonymousCredentials
from google.cloud.firestore import AsyncClient

from app.core.config import Settings, get_settings
from app.core.firestore.errors import FirestoreUnavailableError

DEFAULT_EMULATOR_PROJECT = "demo-techdrona-lms"
_ADMIN_APP_NAME = "td-lms-firestore"

_client: AsyncClient | None = None
_client_loop: Any = None


def emulator_project(s: Settings) -> str:
    p = s.FIREBASE_PROJECT_ID.strip()
    if p.startswith("demo-"):
        return p
    # Inside the Functions emulator the project is the emulator's --project (GCLOUD_PROJECT); user
    # env cannot set FIREBASE_* there (reserved prefix), and a repo .env may name the real project.
    platform = (os.environ.get("GCLOUD_PROJECT") or os.environ.get("GOOGLE_CLOUD_PROJECT") or "").strip()
    return platform if platform.startswith("demo-") else DEFAULT_EMULATOR_PROJECT


def make_client(s: Settings | None = None) -> AsyncClient:
    s = s or get_settings()
    database = s.FIRESTORE_DATABASE_ID or "(default)"
    host = s.FIRESTORE_EMULATOR_HOST.strip() or os.environ.get("FIRESTORE_EMULATOR_HOST", "").strip()
    if host:
        if s.is_production:
            raise FirestoreUnavailableError("the Firestore emulator is not allowed in production")
        # google-cloud-firestore reads the emulator host from the process environment.
        os.environ["FIRESTORE_EMULATOR_HOST"] = host
        return AsyncClient(
            project=emulator_project(s),
            credentials=AnonymousCredentials(),
            database=database,
        )
    return _admin_client(s, database)


def admin_app(s: Settings | None = None) -> Any:
    """The Firebase Admin SDK app of the real project (service account). Never the emulator."""
    import firebase_admin
    from firebase_admin import credentials

    s = s or get_settings()
    key, project = s.FIREBASE_SERVICE_ACCOUNT_FILE.strip(), s.FIREBASE_PROJECT_ID.strip()
    if not key and project and s.TD_RUNTIME == "firebase":
        # Cloud Functions: the function's own service account (Application Default Credentials).
        try:
            return firebase_admin.get_app(_ADMIN_APP_NAME)
        except ValueError:
            return firebase_admin.initialize_app(
                credentials.ApplicationDefault(), {"projectId": project}, name=_ADMIN_APP_NAME
            )
    if not key or not project:
        raise FirestoreUnavailableError(
            "Firestore is not configured: set FIRESTORE_EMULATOR_HOST (dev/tests) or "
            "FIREBASE_PROJECT_ID + FIREBASE_SERVICE_ACCOUNT_FILE"
        )
    if not Path(key).is_file():
        raise FirestoreUnavailableError("FIREBASE_SERVICE_ACCOUNT_FILE does not point to a readable file")
    try:
        return firebase_admin.get_app(_ADMIN_APP_NAME)
    except ValueError:
        return firebase_admin.initialize_app(
            credentials.Certificate(key), {"projectId": project}, name=_ADMIN_APP_NAME
        )


def _admin_client(s: Settings, database: str) -> AsyncClient:
    """A NEW AsyncClient on the Admin app's credentials. Not ``firebase_admin.firestore_async
    .client()``: that caches one client per app, so after ``run_async`` closed its loop-bound
    channel every later job got the same closed client back ("Channel is closed")."""
    app = admin_app(s)
    return AsyncClient(
        project=app.project_id or s.FIREBASE_PROJECT_ID.strip() or None,
        credentials=app.credential.get_credential(),
        database=database,
    )


def _running_loop() -> Any:
    import asyncio

    try:
        return asyncio.get_running_loop()
    except RuntimeError:
        return None


def get_client() -> AsyncClient:
    """Process-wide client (created lazily on first use). Its gRPC channel is bound to the event
    loop that created it: a client made on another (finished) loop is replaced, never reused."""
    global _client, _client_loop
    loop = _running_loop()
    if _client is None or (loop is not None and _client_loop is not None and loop is not _client_loop):
        _client = make_client()
        _client_loop = loop
    return _client


def set_client(client: AsyncClient | None) -> None:
    """Override the process client (tests)."""
    global _client, _client_loop
    _client = client
    _client_loop = _running_loop() if client is not None else None


async def aclose(client: AsyncClient) -> None:
    """Close the client's gRPC channel (the library has no public close for AsyncClient)."""
    api = getattr(client, "_firestore_api_internal", None)
    if api is not None:
        await api.transport.close()


async def close_client() -> None:
    global _client, _client_loop
    if _client is not None:
        await aclose(_client)
    _client = None
    _client_loop = None
