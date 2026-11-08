# ADR-0008: Background jobs — Celery on a dedicated Redis broker, transactional outbox

* **Status:** Accepted (Brief §1 default confirmed) — implementation **Planned**
* **Related:** `system-architecture.md §14`

## Context

Workloads: payment webhook processing, attempt auto-submit and scoring, judge orchestration, notifications/OTP, analytics ingest and rollups, CSV roster imports and exports, partition maintenance, audit chain sealing. Requirements: at-least-once with idempotent handlers, priority isolation (auto-submit must not wait behind exports), scheduled jobs, Python ecosystem, small team.

## Decision

* **Celery 5** with **Redis** as broker on a **separate ElastiCache replication group** (`queue`, `maxmemory-policy noeviction`), distinct from the cache cluster (`allkeys-lru`).
* `acks_late=True`, `task_reject_on_worker_lost=True`, prefetch 1 for long tasks, visibility timeout above the longest task; results not stored in Redis (state is in Postgres).
* Queues and ECS services: `critical`, `default`, `judge_*`, `notifications`, `analytics`, `reports`, `maintenance` (system-architecture §14), each autoscaled on queue age/depth.
* All tasks take ids, are idempotent (guarded UPDATEs, unique keys), and use exponential backoff with a max retry count; poison messages go to a `dead` queue with alerts.
* **Transactional outbox** (`outbox_events`) for domain events: written in the business transaction, relayed by a LISTEN/NOTIFY-woken poller using `FOR UPDATE SKIP LOCKED`.
* **Celery beat** single replica with a Redis leader lock for schedules; time-critical deadline handling uses a Redis ZSET sweeper (5 s) plus a DB safety sweeper (60 s).
* High-volume analytics ingest uses Redis Streams consumer groups (not Celery messages) for batching efficiency.

## Alternatives considered

| Option | Why not |
|---|---|
| Dramatiq / RQ / arq | Simpler, but smaller ecosystems; Celery's routing, beat and tooling are well known. Dramatiq remains a viable swap if Celery operational issues arise. |
| AWS SQS + workers | Durable and managed; but no native priorities/ETA semantics we need for sweepers, extra latency; consider SQS as broker if Redis broker durability becomes a concern. |
| Temporal | Excellent for long workflows; too heavy for v1. |
| Postgres-based queue (e.g. procrastinate) | Fewer moving parts, but adds write load to the primary DB at drive peaks. |

## Consequences

* (+) Familiar stack; clear priority isolation; outbox gives reliable cross-module events.
* (−) Redis broker is not as durable as SQS/Kafka; mitigated by Multi-AZ, `noeviction`, idempotent tasks and DB-based safety sweepers/reconciliation.
* (−) Celery configuration pitfalls (prefetch, visibility timeout) must be codified and tested.
