# ADR-0004: Analytics storage — partitioned PostgreSQL now, ClickHouse evaluation later

* **Status:** Accepted for v1 (Brief §1) — implementation **Planned**; ClickHouse/BigQuery = **Proposed for re-evaluation** at triggers below
* **Related:** `system-architecture.md §13`, `database-schema.md §12`; event schema owned by Analytics Engineer

## Context

Learning analytics (time-on-task, topic accuracy, cohort percentiles, TPO dashboards) need raw events and aggregates. Estimated peak ingest ~500 events/s, 3–10 M rows/day (system-architecture §19). The team is small; data must stay in ap-south-1 and respect DPDP consent and minor rules (research §8 [Verified]).

## Decision

* Ingest: API validates and enriches events, writes to a Redis Stream; `worker-analytics` batches (≤ 1,000 rows / 2 s) and `COPY`s into Postgres.
* Raw tables `analytics_events`, `activity_heartbeats` are **monthly RANGE-partitioned** (`pg_partman`), BRIN on time, raw retention `analytics_events` **90 days** and `activity_heartbeats` **35 days** (drop partition — no DELETE storms); `engagement_intervals` 13 months (brief v0.2 §1, PO-13).
* Partition key is `event_ts`, derived from the client UUIDv7 `event_id`; PK `(event_id, event_ts)`, so per-event idempotency (`ON CONFLICT DO NOTHING`) works across partitions (analytics CP-1, `contract-reconciliation.md` §2.4).
* Derived: `engagement_intervals` (sessionized every 5 min), `daily_learning_aggregates` (hourly/nightly). Dashboards read aggregates from the **read replica** only.
* Events are xAPI-shaped for portability (research §6 [Rec]).

## Re-evaluation triggers (any one)

1. Retained raw rows > 300 M or raw + aggregate storage > 500 GB.
2. p95 dashboard query on aggregates > 2 s after index/rollup tuning.
3. Analytics load causes replica lag > 60 s or primary CPU > 60 % sustained from ingest.
4. Product needs ad-hoc exploration over > 90 days of raw events.

## Alternatives evaluated for later

| Option | Pros | Cons |
|---|---|---|
| ClickHouse (self-managed on EC2 or ClickHouse Cloud in an AWS Mumbai region if available) | Columnar, cheap storage, fast aggregations, native TTL | New ops surface; residency must be verified; eventual consistency |
| BigQuery | Serverless | Data leaves AWS; India region exists (asia-south1) but cross-cloud egress + DPA complexity |
| TimescaleDB extension | Stays Postgres | Not available on RDS; would force self-managed Postgres |
| Redshift Serverless | AWS-native, ap-south-1 | Cost at small scale; still a second system |

Migration path when triggered: keep Redis Stream ingest; add a ClickHouse sink consumer in parallel (dual-write), backfill from partitions, switch dashboards, then shorten Postgres raw retention to 7 days.

## Consequences

* (+) No new datastore at launch; same backup, RLS, and residency controls.
* (−) Postgres is not a columnar engine; requires disciplined rollups and short raw retention.
* (−) Heavy ad-hoc analysis must use exports until a warehouse exists.
