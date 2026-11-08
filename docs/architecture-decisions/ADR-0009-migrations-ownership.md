# ADR-0009: Database migrations — single Alembic history, single schema owner

* **Status:** Accepted (Brief §1 "Alembic (single migration owner)") — implementation **Planned**
* **Related:** ADR-0001, ADR-0003, `database-schema.md`

## Context

18 modules share one PostgreSQL database. Multiple migration histories would race on ordering, cross-module FKs and RLS policies. Schema changes during drives or payment peaks must not lock hot tables.

## Decision

* One Alembic environment at `apps/api/migrations`, one linear history (merge heads rejected in CI).
* `docs/database-schema.md` (System Architect) is the design source of truth; module teams propose changes via PR to both the doc and a migration; schema-owner review required (CODEOWNERS).
* Every table appears in exactly one module's ownership manifest; CI fails on unowned or doubly-owned tables.
* Migrations run as `td_owner` in a one-off ECS task **before** the new app version deploys; app runs as `td_app` (no DDL rights).
* **Expand → migrate → contract** for breaking changes: add nullable column / new table → deploy code writing both → backfill in batches (Celery `maintenance`) → switch reads → drop old in a later release.
* Online-safety lint (e.g. `squawk`) in CI: `CREATE INDEX CONCURRENTLY` (in autocommit migration blocks), no `ALTER COLUMN TYPE` on large tables, `lock_timeout = '5s'` and `statement_timeout` set per migration, NOT NULL added via `CHECK … NOT VALID` then `VALIDATE`.
* Every new table with `organization_id` or `user_id` must include its RLS policy + FORCE in the same migration (lint rule).
* Partitions are created by `pg_partman` maintenance, not by migrations; migrations only create parent tables and register them. **v0.3:** premake and retention drops run on the Celery `maintenance` queue as the login role `td_maintenance`, which may only `EXECUTE` the `SECURITY DEFINER` functions `maint.run_partition_maintenance()` and `maint.drop_expired_partitions(parent regclass)` owned by `td_owner` (`database-schema.md` §1.2). The functions drop only partitions older than the `retention_policies` value; `td_app` keeps no DDL right.
* Seed/reference data (roles, permissions, topics) via idempotent data migrations.
* Migration freeze windows around scheduled drives (from `test_assignments`) and month-end billing.

## Alternatives considered

| Option | Why not |
|---|---|
| Per-module Alembic branches | Ordering conflicts, cross-module FK races. |
| Migrations run at app startup | Concurrent tasks race; app role would need DDL rights. |
| Declarative diff tools only (e.g. auto-generate in prod) | Unreviewed DDL; unsafe locks. |

## Consequences

* (+) Deterministic schema history; RLS can't be forgotten; safe online changes.
* (−) Schema owner becomes a review bottleneck; mitigated by lint automation and clear CODEOWNERS.
