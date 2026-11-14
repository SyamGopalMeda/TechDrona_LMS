# Cost: scheduler, sub-minute loops and idle polling (agent "cost-scheduler", 2026-11-13)

Goal: keep the LMS Firebase deployment (project billing-f4fe3, region asia-south1) inside the free
tiers when idle and at small scale, **without changing any feature or behaviour**. Nothing was
deployed.

## TL;DR

| Idle day (no users, empty demo DB, emulator-measured) | Before (32 scheduled functions) | After (1 dispatcher) |
|---|---|---|
| Cloud Scheduler jobs (free: 3 per billing account) | **32** | **1** |
| Function invocations / day | 17,936 | 1,440 (+3 maintenance hand-offs) |
| Billed instance time / day (vCPU-s ≈ GiB-s at 1 GiB) | ≈ 216,000 s for the three 50 s loops alone, plus ~14k short calls and ~500 cold starts | ≈ 144 s (1,440 ticks × 100 ms billing minimum; measured 53 ms wall, 47 ms CPU per tick) |
| Billed vCPU-s / month | **≈ 6.5 M** (≈ ₹21k) | **≈ 4.3 k** (+ occasional cold starts of ~4 s) |
| Firestore reads / day (free 50k) | **184,154** (128/min) | **4,188** (2.9/min) |
| Firestore writes / day (free 20k) | **40,589** | **3,150** |
| Firestore deletes / day (free 20k) | **37,440** | **0** |
| Firestore reads / month | 5.5 M | 126 k |

Measured with `functions-lms/tools/firestore_cost_probe.py`. The "before" numbers are per-run
costs measured on the unchanged code, multiplied by each job's cadence. The "after" numbers come
from running the real dispatcher for 1,440 simulated minutes (Sunday 00:00–23:59 UTC). Both runs
used the emulator at 127.0.0.1:18080 with project `demo-costprobe`.

## What changed

### 1. One dispatcher instead of 32 scheduled functions
- **`functions-lms/main.py`**
  - The `lmsJob*` loop is gone.
  - New `lmsScheduler` function: `on_schedule("* * * * *", Etc/UTC)`, 1 GiB, cpu 1, concurrency 1, timeout 540 s.
  - The task-queue handlers now call `cloudtasks.run_handed_off`.
- **`apps/api/app/core/scheduler.py`** (new)
  - `tick(capp, at)` runs every beat entry whose cron matches the minute `at` (UTC). `at` is the event's `schedule_time`, so a late or retried invocation still evaluates the right minute.
  - The crons are exactly `cloudtasks.cron_for` (what `schedules.json` holds and the old functions used). The matcher is standard 5-field cron (Vixie day-of-month/day-of-week OR).
  - `maintenance`-queue entries go to `lmsTasksMaintenance` (540 s budget, one at a time). The payload carries `periodic=<job>`, so a failure is logged, not retried — exactly like the old scheduled function.
  - Everything else runs inline, critical-queue entries first. After 45 s of a tick, the remaining due entries are handed to their queue's task function. Nothing is ever skipped for lack of time.
  - Failures are loud. An inline job that raises is logged with `log.exception("periodic_job_failed")` at ERROR, with its traceback. The tick then logs `scheduler_tick_failures` at ERROR. A hand-off whose job fails logs `periodic_job_failed` at ERROR too. Today 5 jobs fail like this on every run; see risk 6.
  - Overlap: same as before. The old functions did not prevent two minutes' runs of a slow job overlapping either. The jobs keep their own guards (leases, claims, `FOR UPDATE`, idempotent writes).
- **`schedules.json` / `gen_schedules.py`**: unchanged. They remain the manifest; the drift test still guards them.
- **`app/core/cloudtasks.py`**
  - `send_task(..., periodic=, periodic_loop=)` adds the hand-off markers to the payload.
  - `run_handed_off` runs a hand-off or a plain task.
  - `run_periodic(loop=)` controls whether a hand-off repeats.
  - An exact `eta` (fractional delay) becomes `schedule_time`, so a kick is never dispatched before its time. Integer countdowns are unchanged.

### 2. No more always-looping sub-minute jobs
The sub-minute jobs are now event-driven, implemented in `apps/api/app/core/jobhints.py` (new) plus a small hook in `app/core/firestore/store.py`. This applies only in **event mode**: `TD_TASKS_BACKEND=cloudtasks` and no Postgres, i.e. the final Firebase stack.

- **Outbox relay and audit seal.**
  - After any `ScopedStore` transaction (or direct create) that *creates* an `outbox_events` or `audit_outbox` document commits, a Cloud Task for `td.core.outbox_relay` / `td.core.audit_seal` goes to `lmsTasksCritical`.
  - It is scheduled at the next whole second, strictly after the commit.
  - Each process sends at most one task per second per job (in-memory dedupe), so a burst of writes costs one task.
- **Deadline sweeper.**
  - A commit that writes an in-progress `test_attempts` row, or an `active` `attempt_sections` row, with a `deadline_at` schedules `assessments.deadline_sweeper` at `deadline_at + 1 s`. Rewrites with the same deadline, such as answer saves, are deduped per process.
  - In event mode the sweep itself (`assessments/tasks.py::_schedule_next`) schedules the next sweep at the earliest remaining `deadline + grace` + 1 s. This covers grace periods, sections that advance, and extra time.
- **Backstop.** All three still run once a minute from the dispatcher while they have work, so a lost kick costs at most a minute (see the latency table).
- **Hybrid stack (Firebase + Postgres).** No kicks. The dispatcher hands the sub-minute entries to `lmsTasksCritical` every minute with `periodic_loop`, and they loop 50 s there exactly as before. Postgres-side writes are invisible to Firestore hints, so the event path would not be safe there.
- **VM (`TD_RUNTIME` ≠ firebase, Celery).** Nothing here runs. Celery beat keeps the 5 s / 2 s schedules. All new hooks are no-ops: `jobhints.active()` is False.

Raw Firestore access for all of this lives in **`app/core/firestore/jobstate.py`** (new; the store-boundary lint test passes): the hint document, `limit(1)` existence checks and the relay's eligibility check.

### 3. Cheap idle minutes: work hints plus an hourly full sweep
**The hint document.** `lms_scheduler_state/hints` is one document.
- Every `ScopedStore` transaction that writes a *watched* collection also sets `w.<collection> = SERVER_TIMESTAMP` **in the same commit**, so the hint exists if and only if the data does.
- A process writes the hint for a collection at most once per 30 s, so it costs about one extra write per collection per instance per 30 s, and no extra round trip.

**Recording an idle verdict.** After a gated job runs, its gate decides whether the job is provably idle:
- it has nothing to do now, **and**
- it can only get work again through a write to one of its watched collections.

The gate decides this with a `limit(1)` existence query, or from the run's own result. The dispatcher then records `idle.<job> = S`, where S is the server read time of the tick.

**Skipping.** Later ticks read the hint document (**1 read**) and skip the job while no watched collection has `w >= S − 90 s`.

**Hourly full sweep.** Each gated job still runs in full once an hour, at a fixed per-job minute that matches its cron. So a write that somehow bypassed the hint delays work by **at most 60 minutes and can never lose it**. Every write path in `ScopedStore` is hooked (`_staged`, `create`, `import_documents`, `delete_all`). The only Firestore writers outside it are idempotency keys and kv, which no gated job watches.

**Proof of the margin.** A commit at c either wrote the hint (w ≥ c) or the same process committed one at h > c − 30 s. For any verdict time S < c: w > c − 30 > S − 90. The extra 60 s is margin for clock skew between client and server.

| Gated job (cron) | Watches | Idle when |
|---|---|---|
| admin.break_glass_expiry (1 min) | break_glass_sessions | no `status == active` |
| analytics.exports_sweep (1 min) | export_jobs | no `status in (ready, awaiting_approval, running)` |
| analytics.interval_builder (1 min) | analytics_batches, engagement_intervals | the run found `page_instances == 0`; a skip writes the same `analytics_job_state` update an idle run writes (blind update) |
| analytics.video_coverage (1 min) | analytics_batches | the run found `assets == 0`; same bookkeeping |
| assessments.deadline_sweeper (1 min, was 5 s) | test_attempts, attempt_sections, tests | no `status == in_progress` attempt |
| coding.process_pending (1 min) | code_submissions | no `status in (queued, running)` |
| commerce.webhook_retry (1 min) | payment_webhook_events | no `status == received` |
| core.audit_seal (1 min, was 2 s) | audit_outbox | outbox empty |
| core.outbox_relay (1 min, was 5 s) | outbox_events | nothing with `pending_at`, and no dead letter below the current `TD_OUTBOX_MAX_ATTEMPTS` (a fingerprint re-checks the verdict when that setting changes) |
| learning.certificate_outbox_send (1 min) | certificate_outbox | no `status == pending` |
| commerce.refund_submit_retry (2 min) | refunds | no `status == approved` |
| placement.media_scan_sweep (2 min) | question_media | no `scan_status == pending` |
| commerce.order_expiry (5 min) | orders | no `status in (created, pending_payment)` |
| security.heartbeat_batch (5 min) | auth_sessions | no session with `last_seen_at >= now − 15 min` (a monotone window) |
| security.restriction_expiry (5 min) | account_restrictions | no `level == 3 and family == sharing` row |

**Rules for the predicates.**
- Each predicate is the job's own pushed-down filter, or broader. A broader predicate only makes the job run more often than needed, never less.
- Time-driven jobs (expiry, retry back-off) count as busy while any candidate row exists, so they run at their full cadence exactly as before.

**Jobs that are not gated.** They have no single-collection predicate, or they write or call out on every run:
- analytics.daily_aggregator and analytics.outbox_consumer;
- entitlements.expiry (lifetime entitlements would keep it busy anyway);
- security.sla_breach_alerts and media.scan_sweep;
- all hourly and daily jobs.

These run exactly at their cron, as before.

**Other idle-cost fixes, with identical behaviour.**
- **`app/worker.py::_seal_once`.** Without Postgres it seals only the Firestore outbox. Before, every run also opened a Postgres engine and failed with ConnectionRefused *after* sealing (4 s wall per run, logged as a failed job).
- **`modules/audit/repo_firestore.py::seal_pending`.** It checks for pending rows (1 read) before taking the sealer lease. An empty outbox no longer costs a lease claim and release: 2 reads, 1 write and 1 delete per run. That was 26 runs a minute, i.e. 37k deletes a day.
- **`modules/analytics/fs_raw.py::record_idle_run`.** Writes the `analytics_job_state` fields that `set_state(job, None, result)` leaves after an idle run (`last_run_at`, `last_result`, `last_duration_ms`, `updated_at`), so the ingest-health report shows the same "last run" values while the job is skipped.

## Worst-case latency per job

Old cadence for the 5 s jobs: the loop ran every 5 s for about 50 s, then waited for the next minute's invocation. Its worst case was therefore the ~10 s gap plus Cloud Scheduler jitter (≈ 10–11 s), with the function always warm. The same holds for the 2 s seal.

| Job | Before (worst) | After (worst, normal path) | After (kick lost / Cloud Tasks down) |
|---|---|---|---|
| core.outbox_relay | ≈ 10–11 s | ≤ 1 s window + Cloud Tasks dispatch (< 1 s) ⇒ **≈ 2 s** warm. A cold `lmsTasksCritical` adds its start-up (import ≈ 3.5–4 s CPU measured), ⇒ **≈ 6–8 s**, still ≤ before | next dispatcher minute: ≤ 60 s |
| core.audit_seal | ≈ 10–11 s | same as relay: ≈ 2 s warm, ≈ 6–8 s cold | ≤ 60 s |
| assessments.deadline_sweeper | ≈ 10–11 s after `deadline + grace` | task at `ceil(deadline) + 1 s`, then a precise re-schedule at `deadline + grace + 1 s` ⇒ ≈ 2 s warm, ≈ 6–8 s cold. Exceptions, each ≤ 60 s via the minute backstop: an admin *reduces* a live test's grace, or the attempt was written while event mode was off | ≤ 60 s. Students never see a late close: the attempt endpoints already expire lazily |
| every other every-N-minute job | its cron tick | **the same cron tick.** A work-creating write commits its hint atomically, so the next due tick runs the job | a write that bypassed the store hook: ≤ 60 min (hourly full sweep). No such write path is known |
| hourly / daily / weekly jobs | cron | same cron. Maintenance jobs are handed to `lmsTasksMaintenance` in the same minute | — |

## Cloud Tasks and invocations at small scale
- **Idle:** 0 kicks, plus 3 maintenance hand-offs a day (≈ 6 ops a day).
- **Activity:** at most one relay task, one seal task and one task per distinct deadline second, per API instance, per second (enqueue plus dispatch ≈ 2 ops each).
- **Example:** a few hundred committing requests a day ⇒ < 1–2 k ops a day (free tier: 1 M a month ≈ 33 k a day).

## How to measure again
```
cd apps/api
.venv/Scripts/python ../../functions-lms/tools/firestore_cost_probe.py --mode jobs        # per-run cost of every entry
.venv/Scripts/python ../../functions-lms/tools/firestore_cost_probe.py --mode dispatcher  # 1,440 simulated minutes
```
- **What it counts:** reads (one per returned or missing document, **one per empty query**), writes, deletes, transactions and Cloud Tasks enqueues. It instruments the GAPIC client at the RPC level.
- **Safety:** it refuses non-`demo-*` projects and wipes only its own project.

## Tests
- **New file:** `apps/api/tests/platform/test_scheduler.py`, 29 tests, using the emulator where needed.
- **Cadence over a simulated week:** for every entry, the dispatcher's due set equals a Celery-schedule oracle computed from the beat objects, not from the cron strings. Weekly totals are spot-checked.
- **Cron edge cases:** day-of-month/day-of-week OR, `7` = Sunday, ranges with steps.
- **Gate well-formedness:** only every-N-minute entries are gated; each has exactly one full-sweep minute per hour that matches its cron; every watched name is a registered collection.
- **Tick behaviour:** inline runs (critical queue first), maintenance hand-off payload, budget overflow handed off rather than skipped, failures logged, the hybrid stack keeps its 50 s loops, `run_handed_off` semantics.
- **Event mode on the emulator:**
  - **Hints:** the hint is written in the same commit, with per-process throttling; skip, wake-up and the hourly full sweep; fingerprint and margin rules.
  - **Kicks:** the relay is kicked within 1 s and after the commit; the seal is kicked within 1 s; a deadline write schedules the sweeper at deadline + 1 s once; the sweeper schedules the next deadline + grace; per-window kick coalescing; a failed kick is logged, not raised.
  - **Gates:** the relay gate sees pending events and revivable dead letters; an empty audit seal takes no lease.
  - **Outside event mode:** nothing is hinted or kicked.
- Verification runs (ruff, mypy, pytest): see "Verification" below.

## Risks and notes for the owner
1. **Deploy must delete the 32 old `lmsJob*` functions.** Accept the CLI's deletion prompt, or deploy with `--force`; `functions-lms/deploy/deploy.sh` has no `--force`. Otherwise they keep running alongside `lmsScheduler`: double runs and the old cost.
2. **Request path.**
   - The first commit per second per API instance that creates outbox or audit rows makes one Cloud Tasks enqueue call (≈ 20–80 ms). So does an attempt start or section change with a new deadline.
   - Hint writes add no round trip: they ride in the same commit, at about one extra billed write per watched collection per instance per 30 s.
3. **The hint document is a hot document under heavy write load.** Writers throttle themselves to one write per collection per 30 s per instance, which keeps it far below Firestore's 1 write/s/doc guidance up to dozens of instances.
4. **Firestore field types.** The predicates mirror the jobs' own pushed-down filters, so stored representations match. A predicate that ever matched nothing by mistake would delay that job's work by up to 60 min (the hourly full sweep). It would not lose any work.
5. **Bookkeeping writes.** Keeping `analytics_job_state.last_run_at` current while interval_builder and video_coverage are skipped costs 2 writes a minute (≈ 2.9k of the 3.15k writes a day). If the owner accepts a "last run" that only moves when there is work, those writes can go.
6. **Pre-existing issues found (not changed; behaviour-preserving scope):**
   - **Five jobs fail on every run on the no-Postgres Firebase stack** with `PostgresDisabledError`, because they call `get_sessionmaker()`: `learning.certificate_outbox_send`, `learning.certificates_batch_end`, `media.scan_sweep`, `notifications.renewal_reminders`, `support.auto_close`.
     - `core.maint_partitions` and `core.maint_retention` use psycopg (Postgres-only).
     - `security.purge_closed_cases` raises `ValueError` on Firestore.
   - **`analytics.interval_builder` never goes idle once analytics data exists.** It re-discovers its newest batch through the 2-minute overlap window on every run (`received_at > wm − 2 min`, while `wm` equals that batch's `received_at`), so it rebuilds the last page every minute.
   - **`analytics.video_coverage` re-reads every batch since the last video heartbeat** on every run, because its watermark only advances on video heartbeats.
   - **`analytics.outbox_consumer`'s watermark goes stale** and it re-reads the outbox since that point every 10 minutes.

   These are for the analytics owner. The gates stay correct (the job just stays "busy"), but production idle cost with data will be higher than the empty-DB figures above for those jobs.
7. **Other agents edited `app/core/firestore/store.py` concurrently** (request read memo). My edits there are minimal hooks:
   - an optional `data`/`created` on `_staged`;
   - `before_commit`/`after_commit` calls in `run_transaction`;
   - `_hint_direct` after `create`, `import_documents` and `delete_all`;
   - two helper functions.

   The 5 mypy errors that remain in store.py are in the request-memo code (lines ≈ 278/389–394), not in these hooks.
