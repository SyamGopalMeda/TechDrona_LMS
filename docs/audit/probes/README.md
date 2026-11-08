# Audit probes (evidence, not tests)

Moved here by fix wave 3 (w3be, 2026-11-04) so that `pytest` no longer collects probes that
assert the audited bugs (most of them now fail by design, because the bugs are fixed).

* `api/` — was `apps/api/tests/_audit_scratch/` (37 files, unchanged). The audit findings in
  `docs/audit/*.md` still cite the old paths; read them as `docs/audit/probes/api/...`.
* `web/` — `apps/web/src/__audit_scratch__/` was already empty when moved, so nothing was copied.

To re-run an API probe, copy it back under `apps/api/tests/` (probes import `tests.*` fixtures)
and run it against your own test DB (`TD_TEST_DB_NAME=...`), never the dev DB.
