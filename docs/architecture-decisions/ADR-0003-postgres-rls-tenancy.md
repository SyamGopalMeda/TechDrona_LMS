# ADR-0003: Tenant isolation with application scoping plus PostgreSQL RLS (FORCE)

> **Superseded (2026-11-14):** the LMS runs on Firebase (Vite React SPA + Cloud Functions + Firestore, project `billing-f4fe3`) — see `docs/firebase-migration-plan.md` and `docs/firebase/`. PostgreSQL RLS is not used by the live Firestore stack.

* **Status:** Accepted (Brief §1) — implementation **Planned**
* **Related:** `database-schema.md §2`, `system-architecture.md §6.5`
* **Amended by:** [ADR-0015](ADR-0015-single-company.md) (2026-11-06). Tech Drona is now a single company: exactly one internal organization (`COMPANY_ORG_ID`) exists and the college tenants described below are removed. The RLS mechanism is kept unchanged as defence in depth; ADR-0015 adds student-to-student PII hardening because all batch students share the one org.

## Context

Colleges (organizations) buy seats and see their students' progress; they must never see another college's data. D2C users have no organization. Platform staff need cross-tenant access. Application bugs (missing `WHERE organization_id = …`) are the most common cause of multi-tenant leaks (OWASP API1/API3). PostgreSQL RLS is bypassed by table owners unless `FORCE ROW LEVEL SECURITY` is set, and PK/unique/FK checks bypass RLS (research §8 [Verified]).

## Decision

* Shared schema, shared tables, `organization_id` column on tenant-scoped tables (denormalised from parents so predicates stay single-column and indexable).
* Application layer remains primary: every repository query is scoped and object-level authorization is checked in services.
* Defence in depth: `ENABLE` + `FORCE ROW LEVEL SECURITY` on all tenant/personal tables; app role `td_app` is not the owner; migrations run as `td_owner`.
* Context via transaction-local GUCs set by `core.db` at transaction start: `app.user_id`, `app.org_ids` (CSV of orgs the principal belongs to or administers), `app.is_platform` (platform-scoped grants or named system jobs), `app.actor`. Using `set_config(..., true)` keeps context transaction-scoped, so pooled connections cannot leak it.
* Four policy families: `T`, `TN`, `U`, `O` (schema §2.2). Global reference tables have no RLS.
* Tenant-visible uniqueness is always composite with `organization_id`; no cross-tenant existence oracles via unique violations in user-facing flows.
* CI: an integration test suite runs every repository query as two different tenants and asserts zero cross-tenant rows; a migration lint fails if a table with `organization_id` lacks RLS + FORCE.

## Alternatives considered

| Option | Why not |
|---|---|
| Schema-per-tenant | Hundreds of colleges → migration fan-out, connection/catalog bloat; D2C users don't fit. |
| Database-per-tenant | Cost and ops; cross-tenant platform analytics hard. |
| App-only scoping | Single missed filter leaks data; no safety net. |

## Consequences

* (+) Two independent layers must fail for a leak.
* (−) Policies add planner overhead; mitigated by `organization_id` indexes and STABLE helper functions.
* (−) Developers must remember RLS when debugging "missing rows"; tooling prints active GUCs in debug logs (non-prod).
* (−) Connection-pooler choice constrained (transaction-local context only; RDS Proxy pinning to be verified).
