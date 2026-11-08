# ADR-0014: Error tracking — self-hosted GlitchTip in ap-south-1 (no Sentry SaaS)

* **Status:** Accepted (Integration Lead, wave-2 consistency pass, `contract-reconciliation.md` §7) — implementation **Planned**
* **Related:** Brief v0.3 §1 Hosting ("logs retained in India"), `system-architecture.md` §3 and §21, `deployment-and-operations.md` (observability), `privacy-and-data-retention.md` §10 (processor table), ADR-0010

## Context

The wave-2 deployment design assumed Sentry SaaS for frontend and backend error tracking. Sentry SaaS stores events in the US or the EU. Error events routinely carry personal data even with scrubbing: request URLs with ids, user ids, IP addresses, breadcrumbs with form field names, and occasionally request bodies or exception messages containing emails or answers. Brief §1 requires logs to be retained in India, and Sentry SaaS was not in the privacy doc's processor table (deployment issue I-06). Students include minors, and CERT-In requires logs to be available in India.

## Decision

* Run **GlitchTip** (open source, accepts the Sentry SDK protocol) as a small self-hosted service in **AWS ap-south-1**: ECS Fargate service `errors` (web + worker tasks) behind an internal ALB reachable only from the VPC and the staff VPN/SSO, with its own database on the shared RDS instance in a separate database (`glitchtip`, own role) and the `cache` Redis cluster.
* The frontend sends browser errors through a same-origin tunnel route on the BFF (`/api/v1/_errors`, rate-limited, no cookies forwarded) so the DSN host is never public.
* SDK configuration (backend `sentry-sdk`, frontend `@sentry/nextjs`): `send_default_pii = false`; `before_send` scrubs cookies, `Authorization`, `X-CSRF-Token`, `X-TD-*` headers, request bodies, query strings and IP addresses; user context is the internal `user_id` only (no email, name or phone); breadcrumbs for form inputs disabled; no session replay.
* Event retention **90 days**; access limited to engineering on-call and `security_reviewer` via SSO; access audited.
* Sentry SaaS is **not used** in any environment holding real data. If GlitchTip proves insufficient, the fallback is self-hosted Sentry in ap-south-1, not SaaS.

## Alternatives considered

| Option | Why not |
|---|---|
| Sentry SaaS (US/EU) with scrubbing + DPA | Cross-border transfer of incidental personal data, including minors; conflicts with brief §1 "logs retained in India"; scrubbing is never complete |
| Self-hosted Sentry (full) in ap-south-1 | Data stays in India, but needs Kafka, ClickHouse, Snuba and about 16 GB RAM: too heavy for a pilot-sized team. Kept as the scale-up path |
| CloudWatch Logs only | No grouping, release tracking or source maps; slower triage |

## Consequences

* (+) Error data stays in India under our own retention; no new processor for the privacy notice.
* (+) Same SDKs as Sentry, so a later move to self-hosted Sentry needs no code change.
* (−) One more service to patch and back up (about US$30–50/month in Fargate + RDS storage); DevOps owns it.
* (−) Fewer features than Sentry SaaS (performance tracing is limited); tracing stays on OpenTelemetry → ADOT → AWS X-Ray in ap-south-1 per the deployment doc.
