"""Tech Drona LMS on Cloud Functions for Firebase (codebase ``lms``, region asia-south1).

Functions:

* ``lmsApi`` (HTTPS): Firebase Hosting rewrites ``/api/**`` here. Runs the unchanged FastAPI app
  (``app.main.create_app``) behind ``lms_edge.EdgeApp`` (the Next.js BFF behaviour: cookies,
  CSRF, Fetch Metadata, header translation, public admissions bridge), through the a2wsgi
  ASGI->WSGI adapter that Cloud Functions' Flask runtime needs.
* ``lmsTasks`` / ``lmsTasksCritical`` / ``lmsTasksMaintenance`` (Cloud Tasks task-queue functions):
  the Celery queues ``default`` / ``critical`` / ``maintenance``. Payload
  ``{"task", "args", "kwargs"}`` sent by ``app.core.cloudtasks`` (every Celery ``send_task`` /
  ``apply_async`` / ``delay`` when ``TD_TASKS_BACKEND=cloudtasks``).
* ``lmsScheduler`` (scheduled, every 2 hours, UTC): the ONE Cloud Scheduler job. It runs every
  beat entry of ``schedules.json`` whose cron is due since the previous tick (``app.core.scheduler.tick``; same
  cadence as the former one-function-per-entry ``lmsJob*`` functions), hands maintenance entries
  to ``lmsTasksMaintenance`` (540 s) and skips provably idle entries (work hints, weekly full
  sweep). Outbox relay, audit seal, certificate emails and the deadline sweeper are kicked by the writes that create
  their work (``app.core.jobhints``) instead of looping. docs/firebase/agents/cost-scheduler.md.

The API code is ``./app`` (copied from ``apps/api/app`` by ``tools/build.py`` before a deploy);
for local runs from the repo it is imported from ``../apps/api`` directly.
"""

from __future__ import annotations

import gc
import os
import sys
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from firebase_functions import https_fn, options, params, scheduler_fn, tasks_fn

HERE = Path(__file__).resolve().parent
if not (HERE / "app").is_dir():  # repo checkout: use the API source in place
    sys.path.insert(0, str(HERE.parent / "apps" / "api"))

# Everything here is the Firebase runtime: Firestore cache/rate limits, Cloud Tasks, packed
# __session cookie. Explicit environment values (functions .env files) still win.
os.environ.setdefault("TD_RUNTIME", "firebase")

REGION = "asia-south1"

# Secret Manager secrets, exposed to the code under the SAME environment names the VM's
# server.env uses (app.core.config / lib/bff/config.ts). Create each one before the first deploy
# (`firebase functions:secrets:set NAME`); the list is secrets.txt (one name per line, `#`
# comments) so a provider key can be added without a code change. See
# docs/firebase/agents/platform.md.
SECRET_NAMES: tuple[str, ...] = tuple(
    line.split("#", 1)[0].strip()
    for line in (HERE / "secrets.txt").read_text(encoding="utf-8").splitlines()
    if line.split("#", 1)[0].strip()
)
SECRETS = [params.SecretParam(n) for n in SECRET_NAMES]

API_MIN_INSTANCES = params.IntParam("LMS_API_MIN_INSTANCES", default=0)  # serverless only: no always-on instance (owner 2026-11-14)

_wsgi: Any = None
_celery: Any = None

# Cold start: the first requests of a new instance arrive together (the SPA fires several API
# calls on page load) on the runtime's request threads. Without a lock each of them would run
# create_app() itself on the instance's single vCPU; with it one thread builds and the rest wait.
_build_lock = threading.Lock()


@contextmanager
def _cold_build() -> Iterator[None]:
    """Build-once section: serialised, with the cyclic GC paused while thousands of long-lived
    module, class and route objects are created (it would otherwise rescan them over and over;
    ~0.3 s of a cold start). ``gc.freeze()`` then moves them out of future collections."""
    with _build_lock:
        was_enabled = gc.isenabled()
        gc.disable()
        try:
            yield
        finally:
            gc.freeze()
            if was_enabled:
                gc.enable()


def api_wsgi() -> Any:
    """The WSGI app (built once per instance; a2wsgi runs one event loop for all requests)."""
    global _wsgi
    if _wsgi is None:
        with _cold_build():
            if _wsgi is None:
                from a2wsgi import ASGIMiddleware
                from lms_edge import EdgeApp

                from app.main import create_app

                _wsgi = ASGIMiddleware(EdgeApp(create_app()))  # type: ignore[arg-type]
    return _wsgi


def celery_app() -> Any:
    global _celery
    if _celery is None:
        with _cold_build():
            if _celery is None:
                from app.worker import celery_app as capp

                _celery = capp
    return _celery


@https_fn.on_request(
    region=REGION,
    memory=options.MemoryOption.GB_1,
    cpu=1,
    concurrency=40,
    timeout_sec=60,  # Hosting rewrites time out at 60 s anyway
    min_instances=API_MIN_INSTANCES,
    secrets=SECRETS,
    invoker="public",
)
def lmsApi(req: https_fn.Request) -> https_fn.Response:  # noqa: N802 - Firebase function id
    return run_wsgi(api_wsgi(), req)


_webhooks_wsgi: Any = None


def webhooks_wsgi() -> Any:
    """The ``api-webhooks`` service: the same API with ``TD_ROUTER_SET=webhooks``, no BFF."""
    global _webhooks_wsgi
    if _webhooks_wsgi is None:
        with _cold_build():
            if _webhooks_wsgi is None:
                from a2wsgi import ASGIMiddleware
                from lms_edge.webhooks import WebhookEdge

                from app.core.config import get_settings
                from app.main import create_app

                s = get_settings().model_copy(
                    update={"TD_ROUTER_SET": "webhooks", "TD_SERVICE_NAME": "api-webhooks"}
                )
                _webhooks_wsgi = ASGIMiddleware(
                    WebhookEdge(create_app(s), trusted_proxy_hops=max(1, s.TD_TRUSTED_PROXY_HOPS))
                )  # type: ignore[arg-type]
    return _webhooks_wsgi


# Payment provider webhooks (Razorpay, Cashfree): providers call the function URL
# https://asia-south1-<project>.cloudfunctions.net/lmsWebhooks/api/v1/webhooks/<provider>.
# Hosting keeps answering 404 for /api/v1/webhooks/* exactly like the VM's BFF did.
@https_fn.on_request(
    region=REGION,
    memory=options.MemoryOption.MB_512,
    cpu=1,
    concurrency=20,
    timeout_sec=60,
    secrets=SECRETS,
    invoker="public",
)
def lmsWebhooks(req: https_fn.Request) -> https_fn.Response:  # noqa: N802 - Firebase function id
    return run_wsgi(webhooks_wsgi(), req)


def run_wsgi(app: Any, req: https_fn.Request) -> https_fn.Response:
    """Run the WSGI app and return its response verbatim (Flask's ``Response`` would otherwise
    add ``Content-Type: text/html`` to bodiless answers such as the CSRF bootstrap's 204).

    The body is read once through Flask (``get_data(cache=True)``: handles chunked uploads from
    the Hosting proxy, and functions-framework's own after-request read finds it cached) and
    handed to the app as a sized ``wsgi.input``; reading the raw stream directly hung on
    chunked POSTs from the Hosting emulator."""
    import io

    body = req.get_data(cache=True)
    environ = dict(req.environ)
    environ["wsgi.input"] = io.BytesIO(body)
    environ["CONTENT_LENGTH"] = str(len(body))
    environ.pop("HTTP_TRANSFER_ENCODING", None)
    environ.pop("wsgi.input_terminated", None)
    captured: dict[str, Any] = {}

    def start_response(status: str, headers: list[tuple[str, str]], exc_info: Any = None) -> Any:
        captured["status"], captured["headers"] = status, headers
        return lambda _data: None

    chunks = app(environ, start_response)
    try:
        body = b"".join(chunks)
    finally:
        close = getattr(chunks, "close", None)
        if close is not None:
            close()
    resp = https_fn.Response(body, status=captured["status"])
    resp.headers.clear()
    for k, v in captured["headers"]:
        resp.headers.add(k, v)
    return resp


def _run_task_request(req: tasks_fn.CallableRequest[Any]) -> None:
    from app.core.cloudtasks import run_handed_off

    run_handed_off(celery_app(), dict(req.data or {}))


def _named(name: str, fn: Any) -> Any:
    """Firebase takes the entry point from ``__name__`` at decoration time: name it first."""
    fn.__name__ = fn.__qualname__ = name
    return fn


def _task_function(name: str, *, max_attempts: int, min_backoff: int, concurrent: int) -> Any:
    def handler(req: tasks_fn.CallableRequest[Any]) -> None:
        _run_task_request(req)

    return tasks_fn.on_task_dispatched(
        retry_config=options.RetryConfig(max_attempts=max_attempts, min_backoff_seconds=min_backoff),
        rate_limits=options.RateLimits(max_concurrent_dispatches=concurrent),
        region=REGION,
        memory=options.MemoryOption.GB_1,
        timeout_sec=540,
        secrets=SECRETS,
    )(_named(name, handler))


# Celery queues -> task-queue functions (app.core.runtime TD_CLOUD_TASKS_QUEUES).
lmsTasks = _task_function("lmsTasks", max_attempts=5, min_backoff=10, concurrent=10)  # noqa: N816
lmsTasksCritical = _task_function("lmsTasksCritical", max_attempts=10, min_backoff=2, concurrent=20)  # noqa: N816
lmsTasksMaintenance = _task_function("lmsTasksMaintenance", max_attempts=3, min_backoff=60, concurrent=1)  # noqa: N816


# The one scheduled function: every beat entry (schedules.json, regenerated from the registry by
# tools/gen_schedules.py) at its own cron, dispatched by app.core.scheduler. Concurrency 1: a tick
# owns its instance; a tick that overruns its inline budget hands the rest to the task queues.
@scheduler_fn.on_schedule(
    schedule="0 */2 * * *",  # every 2 h: app.core.scheduler.TICK_MINUTES (idle cost, owner 2026-11-19)
    timezone=scheduler_fn.Timezone("Etc/UTC"),  # Celery beat runs in UTC
    region=REGION,
    memory=options.MemoryOption.GB_1,  # inline jobs had 1 GiB as separate functions
    cpu=1,
    concurrency=1,
    timeout_sec=540,
    secrets=SECRETS,
)
def lmsScheduler(event: scheduler_fn.ScheduledEvent) -> None:  # noqa: N802 - Firebase function id
    from app.core.scheduler import tick

    tick(celery_app(), getattr(event, "schedule_time", None))
