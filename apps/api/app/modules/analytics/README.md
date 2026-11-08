# analytics module (tm-1.0)

Spec: `docs/analytics-event-schema.md` (authoritative), api-spec §20 (ANL), database-schema §12.

## Endpoints (all under `/api/v1`)

| ID | Route | Auth |
|---|---|---|
| ANL-01 | `POST /analytics/events` | session, ownership (no permission key); `x-td-idle: engaged_only` |
| ANL-02 | `POST /analytics/events/beacon` | as ANL-01; `204`; BFF validates body `csrf`, API rejects a forwarded `Sec-Fetch-Site` other than `same-origin` |
| ANL-03 | `GET /analytics/config` | session; tm params + permitted purposes (shape matches `apps/web/src/lib/analytics/config.ts`) |
| ANL-04 | `GET /me/analytics/summary` | own data, route tag `l3_readonly` (ownership, no permission key) |
| ANL-05 | `GET /me/analytics/learning-time?from&to&grain=day\|week` | own data |
| ANL-06 | `GET /analytics/reports/batches/{batch_id}` | `analytics.read` (trainer, Admin) or `progress.read` (evaluator) @batch; a platform grant covers every batch |
| ANL-07/08 | removed (single company: no organization reports) | — |
| ANL-09 | `GET /analytics/reports/courses/{course_id}` | `analytics.read` @course |
| ANL-10 | `GET /analytics/reports/platform` | `analytics.read.platform` |
| ANL-12 | `GET /analytics/ingest-health` | `analytics.read.platform` |

| ANL-13 | `POST /exports` `{report_key, scope:{type,id}, reason?}` | `report.export.request` **and** `analytics.read` at the scope (trainer @B, Admin @P); S10 step-up for PII, P5 for bulk/privileged; 10/day per user; `202 {export_job_id, status: running \| awaiting_approval}` |
| ANL-14 | `GET /exports`, `GET /exports/{id}` | requester only (`account_status` tag) |
| ANL-15 | `GET /exports/{id}/download` | requester only; 302 to a presigned GET (≤ 2 min) or JSON `{url, expires_at, filename, sha256, downloads_remaining}` with `Accept: application/json`; ≤ 5 per job; audited `export.download` |
| (added) | `POST /exports/{id}/approve`, `/reject` | `report.export.approve` (super_admin, P5, ≠ requester) — thin wrappers over `admin.approvals.decide` (ADM-14/15 work too) |

Not implemented: ANL-11 (commerce report).

## Exports (`exports.py`, `export_store.py`)

Report keys: `batch.progress` (batch, per learner, PII), `content.course_usage`
(course, aggregates), `platform.overview` (platform, aggregates). CSVs come from the same
`reports.*` functions as the screens, so k-floor cells read `<10`; aggregate cells inside a
`suppressed` group are blanked to `<10` too. PII exports estimated above 10,000 rows wait in
`awaiting_approval` with an `export.bulk_pii` approval request (`target_type=export_job`; the
security module's handler for that action type dispatches to `exports.execute_approved` /
`on_rejected`). Security reports (H1–H12, ENG, `security.*`) keep SEC-32/SEC-47
(`security_report_exports`); `POST /exports` answers `422 use_security_export`.
Generation: Celery `analytics.export_generate(job_id)` (sent only when a worker app is loaded or
`TD_EXPORTS_SEND_TASKS=1`) and the 60 s `analytics.exports_sweep` beat entry (picks up stale
`running` jobs, expires files after 24 h and deletes the object, closes jobs whose approval
lapsed). Storage: `TD_EXPORT_STORE=s3|fake` (unset → `s3` in production, `fake` elsewhere);
private bucket `S3_BUCKET_EXPORTS`, SSE; the S3 PUT is SigV4 over httpx and **not verified
against AWS**; downloads reuse `media.storage.presign_get`. The fake writes to
`TD_EXPORT_FAKE_DIR` (temp dir) and is refused at startup in production when selected.
`export_jobs` deviations: `download_count`, `watermark`, `failure_code`, `format`, `reason`,
`completed_at` (migration `analytics_0002`).

## Jobs (`python -m app.modules.analytics.jobs <name>`; Celery task `analytics.run_job`, beat in `tasks.py`)

`outbox_consumer` (30 s) · `interval_builder` (60 s) · `video_coverage` (60 s) ·
`daily_aggregator` (15 min today; dirty days) · `rollups` (03:30 IST weekly + cohort with
k-floor) · `security_feed` (04:30 IST) · `retention_purge` (daily).

## Interfaces for other modules

* **security** — `analytics.feeds.get_activity_summary(session, user_id, from_date, to_date)`,
  `analytics.feeds.get_engaged_buckets(session, user_id, from_ts, to_ts)`. Adults with active
  `security_monitoring` consent only; minors and synthetic users always `[]`. Note: both set a
  named system context on the session passed in.
* **learning** — `analytics.evidence.video_coverage(...)`, `lesson_time_evidence(...)`,
  `watched_seconds_for_lesson(...)` (`app.wiring` registers an equivalent lookup that also maps
  `lesson_key` -> lesson row ids with `learning.service.register_video_coverage_lookup`).
* **placement** — `analytics.mastery.get_topic_mastery(session, user_id, topic_ids=None)`,
  `mastery.rollup(views, parent_of)`.
* Hooks other modules may register: `hooks.register_org_resolver` (enrolment org of an event;
  default = `entity.batch_id` membership), `hooks.register_lesson_meta_lookup` (lesson
  `est_reading_minutes`, asset `duration_s`), `hooks.register_engagement_toucher`.

## Outbox consumption

`consumer.on_outbox_event` is registered with `app.core.outbox.register_handler` for every type
in `HANDLED_TYPES` (by `app.wiring`), so the core relay delivers events in its own transaction.
The polling `outbox_consumer` (own cursor + 10-min look-back) is kept as a 10-minute reconciler
for events the relay never hands to analytics (marked dispatched by a process without the
handler, or dead-lettered). Both paths record ids in `analytics_consumed_events`, so nothing is
applied twice. Event name: assessments emits `attempt.scored` (the architecture doc's
`attempt.graded` is not used). Handled: `practice.answered`, `attempt.started|submitted|scored`,
`submission.judged`, `learning.*`, `session.ended`, `consent.changed` (payload contract in
`consumer.py`).

## Retention

Only DEFAULT partitions exist (no pg_partman / `maint.*` functions yet), so
`retention_purge` deletes in key batches: heartbeats 35 d, raw events 90 d, intervals 13 months,
identifiable aggregates 24 months, feed 180 d, rejection counters 90 d. If
`maint.drop_expired_partitions(regclass)` exists and is executable it is called first.
`jobs.erase_user()` is the privacy provider (account deletion).

## Schema deviations from database-schema §12 (owner: analytics)

heartbeats `sample_interval_ms`, `editor_focused`, `route`, `topic_id`, `privacy_tier`;
intervals `last_sample_at`, `provisional_end`, `privacy_tier`, close reasons
`blur|mode_change|gap`, `active_s numeric`; daily kind `lesson_asset` (`organization` removed in analytics_0003) and
`assessment_active_s`; weekly kind `organization` (removed in analytics_0003); `topic_mastery` decayed sums + band
`insufficient_data`, `topic_id` soft ref; `video_watch_coverage.duration_s` nullable +
`lesson_id`/`covered_s`; `question_item_stats` soft ref + `n_updates`; dirty-day reasons
`interval_rebuild|server_event`; ops tables `analytics_job_state`, `analytics_consumed_events`.
