# ADR-0001: Modular monolith (FastAPI) with an isolated code-execution boundary

* **Status:** Accepted (product owner decision 2026-11-03, Brief §1) — implementation **Planned**
* **Deciders:** Product owner, System Architect
* **Related:** ADR-0005, ADR-0008, ADR-0009, `system-architecture.md §4`

## Context

Tech Drona needs LMS, placement-prep, assessment, coding, commerce, security and analytics capabilities, with a small team and a launch-scale load of 50k registered / 5k concurrent / 2k concurrent test-takers. Many workflows are transactional across domains (payment → entitlement → enrolment; attempt submit → scoring → recommendations). Untrusted student code is the one workload with a fundamentally different trust level (research §8: Judge0 CVSS 10.0 escapes [Verified]).

## Decision

1. One FastAPI application (`apps/api`) containing 18 modules (Brief §2) as Python packages under `app/modules/`, sharing one PostgreSQL database, deployed as one container image with several ECS services (`api`, `api-webhooks`, `worker-*`, `scheduler`) that differ only by entrypoint/router set.
2. Hard module boundaries: each module owns its tables; other modules may import only `modules.<x>.public`; asynchronous collaboration through a transactional outbox. Enforced in CI by `import-linter` contracts and a table-ownership manifest test.
3. Code execution is **never** in-process: the `coding.judge_gateway` sub-package runs only in the `worker-judge` service and talks to an external/isolated judge (ADR-0005).

## Alternatives considered

| Option | Why not |
|---|---|
| Microservices per domain | Distributed transactions for payment/entitlement/enrolment, more infra, more on-call surface; team too small; Brief §1 forbids in v1. |
| Unstructured monolith | Fast initially but couples security-critical code (sessions, restrictions, payments) to everything; hard to extract later. |
| Serverless functions (Lambda) | Cold starts on test-start bursts; long-lived DB connections and Celery-style jobs awkward; RLS context per invocation adds complexity. |

## Consequences

* (+) Single transaction boundary for money/entitlement flows; simple local development; one deploy.
* (+) Modules can later be extracted along `public.py` + event seams if scale demands (analytics first, see ADR-0004).
* (−) One shared database is a scaling and blast-radius concentration point; mitigated by read replica, partitioning, caching.
* (−) Discipline required: boundary violations must fail CI, not code review.
* (−) A bad deploy affects all modules; mitigated by blue/green ECS deploys and feature flags.
