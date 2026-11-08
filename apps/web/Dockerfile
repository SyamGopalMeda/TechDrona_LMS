# syntax=docker/dockerfile:1.7
# =============================================================================
# td-web — Next.js BFF (App Router), standalone output, non-root.
# Build context: REPOSITORY ROOT (ignore rules: apps/web/Dockerfile.dockerignore) (so workspace packages such as packages/design-tokens
# resolve):   docker build -f apps/web/Dockerfile -t td-web .
# Requires next.config: `output: "standalone"` (web owner). Owner of this file: DevOps.
# Release builds pin base images by digest (deployment-and-operations §8.2, G-11).
# NEXT_PUBLIC_* values are baked in at build time — never put secrets there.
# =============================================================================

# Pinned by tag + multi-arch index digest (COM-23); Renovate/Dependabot bumps it.
ARG NODE_IMAGE=node:22-alpine@sha256:fe4f6d74e20370acb04ad889077d14d0f64a9c8ea6a42bc60cddf1e844699914

# --- deps: install from lockfile only -------------------------------------------
FROM ${NODE_IMAGE} AS deps
RUN apk add --no-cache libc6-compat
WORKDIR /repo
COPY packages/ ./packages/
COPY apps/web/package.json apps/web/package-lock.json* apps/web/pnpm-lock.yaml* ./apps/web/
WORKDIR /repo/apps/web
RUN if [ -f pnpm-lock.yaml ]; then corepack enable pnpm && pnpm install --frozen-lockfile; \
    elif [ -f package-lock.json ]; then npm ci --no-audit --no-fund; \
    else echo "apps/web: no lockfile (package-lock.json or pnpm-lock.yaml) — refusing non-reproducible build" >&2 && exit 1; fi

# --- builder ---------------------------------------------------------------------
FROM ${NODE_IMAGE} AS builder
WORKDIR /repo
ENV NEXT_TELEMETRY_DISABLED=1 \
    NODE_ENV=production
ARG NEXT_PUBLIC_APP_NAME="Tech Drona"
ARG NEXT_PUBLIC_BASE_URL=http://localhost:3000
ARG NEXT_PUBLIC_ERRORS_TUNNEL=/api/v1/_errors
ARG NEXT_PUBLIC_SENTRY_DSN=
ARG NEXT_PUBLIC_ANALYTICS_SCHEMA_VERSION=1
ENV NEXT_PUBLIC_APP_NAME=${NEXT_PUBLIC_APP_NAME} \
    NEXT_PUBLIC_BASE_URL=${NEXT_PUBLIC_BASE_URL} \
    NEXT_PUBLIC_ERRORS_TUNNEL=${NEXT_PUBLIC_ERRORS_TUNNEL} \
    NEXT_PUBLIC_SENTRY_DSN=${NEXT_PUBLIC_SENTRY_DSN} \
    NEXT_PUBLIC_ANALYTICS_SCHEMA_VERSION=${NEXT_PUBLIC_ANALYTICS_SCHEMA_VERSION}
COPY --from=deps /repo/ ./
COPY packages/ ./packages/
COPY apps/web/ ./apps/web/
WORKDIR /repo/apps/web
RUN if [ -f pnpm-lock.yaml ]; then corepack enable pnpm && pnpm run build; else npm run build; fi \
    && if [ ! -f .next/standalone/server.js ] && [ ! -f .next/standalone/apps/web/server.js ]; then \
         echo "Next.js standalone output missing: set output: 'standalone' in next.config" >&2; exit 1; \
       fi
# Normalise the standalone layout (it nests under apps/web when outputFileTracingRoot is the repo root)
RUN mkdir -p /out \
    && if [ -f .next/standalone/apps/web/server.js ]; then \
         cp -R .next/standalone/. /out/ && mkdir -p /out/apps/web/.next && cp -R .next/static /out/apps/web/.next/static \
         && { [ ! -d public ] || cp -R public /out/apps/web/public; } \
         && printf 'apps/web/server.js' > /out/.entry; \
       else \
         cp -R .next/standalone/. /out/ && mkdir -p /out/.next && cp -R .next/static /out/.next/static \
         && { [ ! -d public ] || cp -R public /out/public; } \
         && printf 'server.js' > /out/.entry; \
       fi

# --- runtime -------------------------------------------------------------------------
FROM ${NODE_IMAGE} AS runtime
ARG TD_RELEASE=local-dev
LABEL org.opencontainers.image.title="td-web" \
      org.opencontainers.image.revision="${TD_RELEASE}"
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0 \
    TD_RELEASE=${TD_RELEASE}
RUN apk add --no-cache tini \
    && addgroup -S -g 10001 td && adduser -S -u 10001 -G td -h /app td
WORKDIR /app
COPY --from=builder --chown=root:root /out/ ./
# App files stay root-owned (read-only for the runtime user). On ECS the root filesystem is
# read-only; Next's optional .next/cache writes fail soft (mount a tmpfs there if ISR is used).
USER 10001:10001
EXPOSE 3000
# apps/web has no /healthz route yet (web owner); "/" renders without the api.
HEALTHCHECK --interval=15s --timeout=3s --start-period=15s --retries=3 \
    CMD wget -q -O /dev/null "http://127.0.0.1:${PORT}/" || exit 1
ENTRYPOINT ["/sbin/tini", "--"]
CMD ["sh", "-c", "exec node \"$(cat /app/.entry)\""]
