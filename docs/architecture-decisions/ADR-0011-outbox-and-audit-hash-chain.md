# ADR-0011: Transactional outbox and hash-chained append-only audit log

* **Status:** Proposed (adds tables `outbox_events`, `audit_outbox` — CCP-1, CCP-2) — implementation **Planned**
* **Related:** ADR-0008, `system-architecture.md §14, §21`, `database-schema.md §2.3, §13`

## Context

Cross-module side effects (entitlement → enrolment → notification → cache invalidation) must not be lost or double-applied. Privileged actions must be logged in an append-only, tamper-evident audit trail (OWASP logging; DPDP Rule 6(c) [Verified]; Brief §2 "append-only, hash-chained audit log"). A hash chain requires a total order, which concurrent writers cannot produce cheaply.

## Decision

* **Outbox:** modules insert `outbox_events` rows in their business transaction; a relay dispatches them (LISTEN/NOTIFY + 1 s poll, `FOR UPDATE SKIP LOCKED`), handlers are idempotent by `event_id`.
* **Audit:** `core.audit.record()` inserts into `audit_outbox` in the same transaction as the action (so an audit record exists iff the action committed). A single leader-locked **sealer** (every 2 s) reads `audit_outbox` in `(occurred_at, id)` order, assigns gap-free `seq`, computes `row_hash = sha256(prev_hash ‖ canonical_json(row))`, inserts into partitioned `audit_log`, and deletes the outbox rows in one transaction.
* `audit_log` privileges: INSERT for `td_audit_sealer` only, SELECT for reviewers; UPDATE/DELETE revoked from all roles and blocked by trigger; old partitions dropped only after R-AUDIT retention through `maint.drop_expired_partitions()` executed by `td_maintenance` (v0.3; `database-schema.md` §1.2). The sealer runs as a dedicated 1-task ECS service `audit-sealer` holding the `td_audit_sealer` credentials and the only `s3:PutObject` on the `td-audit-anchor` bucket (Object Lock compliance mode, 8 years = R-AUDIT).
* Hourly anchoring: `{max_seq, row_hash, timestamp}` written to an S3 bucket with Object Lock (compliance mode) in ap-south-1; a daily verifier job recomputes the chain and alerts on mismatch.

## Alternatives considered

| Option | Why not |
|---|---|
| Hash computed inline per transaction with a global lock | Serialises all audited transactions; contention at peaks. |
| Per-actor or per-shard chains | Weaker global ordering; verification more complex. Possible later optimisation. |
| AWS QLDB | Deprecated by AWS; external system. |
| CloudTrail-style log files only | Not queryable for case reviews; harder to join with domain data. |

## Consequences

* (+) Exactly-once audit semantics tied to commits; tamper evidence verifiable offline.
* (−) Audit visibility lags commits by a few seconds.
* (−) Single sealer is a throughput ceiling (thousands of rows/s — far above expected audit volume).
