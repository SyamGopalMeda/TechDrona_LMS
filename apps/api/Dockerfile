# syntax=docker/dockerfile:1.7
# =============================================================================
# td-api — one backend image; the role is picked by command/env (ECS task defs):
#   api / api-webhooks : default CMD (uvicorn; TD_ROUTER_SET=user|webhooks)
#   migrate            : alembic upgrade heads
#   worker-* / beat    : celery -A <app> worker|beat ...
#   worker-judge       : python -m app.modules.coding.worker
#   audit-sealer       : python -m app.modules.audit.sealer
# Owner: DevOps. Build context: apps/api.
# Base image pinned by tag + multi-arch index digest (deployment-and-operations §8.2, G-11;
# audit COM-23). Renovate/Dependabot bumps the digest; override with --build-arg PYTHON_IMAGE.
# =============================================================================

ARG PYTHON_IMAGE=python:3.12-slim-bookworm@sha256:e697c81897302a4c4333bade000d98038fbb21eb064f8ee1fd42d02ebcd9d337

# --- builder: resolve and install runtime dependencies into a venv ---------------
FROM ${PYTHON_IMAGE} AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:${PATH}"

WORKDIR /build
# Dependency layer first (cache-friendly): install the project's declared deps only.
# COM-23: when apps/api/requirements.lock (pip constraints, exact versions) exists it is
# applied so builds are reproducible; without it the pyproject ranges resolve to the newest
# matching releases and a warning is printed. The [k] glob keeps COPY valid while it is absent.
COPY pyproject.toml requirements.loc[k] ./
RUN python -c "import tomllib; print('\n'.join(tomllib.load(open('pyproject.toml', 'rb'))['project']['dependencies']))" > /tmp/requirements.txt
RUN pip install --upgrade pip setuptools wheel \
    && if [ -f requirements.lock ]; then \
         pip install -r /tmp/requirements.txt -c requirements.lock; \
       else \
         echo "WARNING: apps/api/requirements.lock missing - dependency versions are not pinned" >&2; \
         pip install -r /tmp/requirements.txt; \
       fi

# --- runtime: slim, non-root, no build tools, no tests, no seeds --------------------
FROM ${PYTHON_IMAGE} AS runtime

ARG TD_RELEASE=local-dev
LABEL org.opencontainers.image.title="td-api" \
      org.opencontainers.image.source="https://github.com/techdrona/techdrona-lms" \
      org.opencontainers.image.revision="${TD_RELEASE}"

ENV PATH="/opt/venv/bin:${PATH}" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/srv/api \
    TZ=UTC \
    TD_RELEASE=${TD_RELEASE} \
    TD_API_PORT=8000 \
    UVICORN_WORKERS=2

RUN groupadd --system --gid 10001 td \
    && useradd --system --uid 10001 --gid td --home-dir /srv/api --shell /usr/sbin/nologin td

COPY --from=builder /opt/venv /opt/venv

WORKDIR /srv/api
# .dockerignore excludes .venv, tests, caches, local env files.
COPY --chown=root:root . /srv/api
# G-21: demo seed scripts and test hooks must be absent from the production image. Only the
# reference-data loader app/seeds/rbac_seed.py stays (migration rbac_0002 imports it).
RUN rm -rf /srv/api/tests /srv/api/.venv \
    && { [ ! -d /srv/api/app/seeds ] || find /srv/api/app/seeds -type f ! -name '__init__.py' ! -name 'rbac_seed.py' -delete; } \
    && find /srv/api -name '__pycache__' -prune -exec rm -rf {} + \
    && chmod -R a+rX,go-w /srv/api

USER 10001:10001
EXPOSE 8000

# /healthz = liveness without dependencies (deployment-and-operations §11.5)
HEALTHCHECK --interval=15s --timeout=3s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import os,sys,urllib.request; sys.exit(0 if urllib.request.urlopen(f\"http://127.0.0.1:{os.environ.get('TD_API_PORT','8000')}/healthz\", timeout=2).status == 200 else 1)"]

# Forwarded headers are trusted only from FORWARDED_ALLOW_IPS (uvicorn env; set to the
# ALB subnets in ECS). Default here is uvicorn's own default (127.0.0.1).
CMD ["sh", "-c", "exec uvicorn --factory app.main:create_app --host 0.0.0.0 --port \"${TD_API_PORT}\" --workers \"${UVICORN_WORKERS}\" --proxy-headers --no-server-header --no-access-log"]
