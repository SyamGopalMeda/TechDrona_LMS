# ADR-0010: Next.js as same-origin BFF; FastAPI not internet-exposed

> **Superseded (2026-11-14):** the LMS runs on Firebase (Vite React SPA + Cloud Functions + Firestore, project `billing-f4fe3`) — see `docs/firebase-migration-plan.md` and `docs/firebase/`. The Next.js BFF is retired on the Firebase stack (it still serves only the legacy VM until that is retired).

* **Status:** Accepted (Brief §1 "Next.js acts as same-origin BFF") — implementation **Planned**
* **Related:** ADR-0002, `system-architecture.md §3, §5`

## Context

The browser must never hold bearer tokens. Cookies should be `__Host-` prefixed (same origin, no Domain). We want one origin for pages and API calls (no CORS), and a single place for CSRF and Fetch-Metadata checks.

## Decision

* CloudFront → ALB → `web` (Next.js) for all browser traffic, including `/api/v1/*`, which a thin Next.js route handler (`app/api/v1/[...path]/route.ts`) proxies to the internal `api` service. Server components call `api` directly over the private network.
* The BFF performs Fetch-Metadata and CSRF validation **and issues the `td_csrf` cookie** (v0.3: minted by the BFF whenever the `api` response sets or rotates `__Host-td_session`; the beacon body token is validated by the BFF too). `TD_CSRF_KEY` is provisioned to `web` only; `api` never issues or holds it. The BFF also strips hop-by-hop and spoofable headers, and adds `X-TD-Session` (raw cookie token), `X-TD-Device`, `X-TD-Client-IP` (from CloudFront/ALB), `traceparent`, `X-Request-Id`, and a service credential (`Authorization: Service <token>`, rotated via Secrets Manager).
* `api` accepts traffic only from `web` (security group + service token), except `/api/v1/webhooks/*`, which CloudFront/ALB route directly to `api-webhooks` (HMAC-authenticated, no CSRF).
* Streaming bodies (uploads go direct to S3 via presigned POST; SSE for judge results is proxied without buffering).

## Alternatives considered

| Option | Why not |
|---|---|
| Browser calls FastAPI directly on a sub-path via ALB path routing | Fewer hops, but CSRF/headers logic duplicated and API becomes internet-facing. Kept as a fallback for latency-critical routes (autosave) if BFF overhead proves material in load tests. |
| Separate API subdomain + CORS | Breaks `__Host-` cookie model; CORS complexity. |

## Consequences

* (+) Single origin, no tokens in JS, one security choke point.
* (−) Extra hop (~1–3 ms in-VPC) and Node CPU for proxying; `web` must scale with API traffic.
* (−) The BFF is security-critical code; covered by tests for header stripping and service-token handling.
