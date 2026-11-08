# Feature build from the reference demo — Build Brief (binding for every build agent)

Coordinator: lead session. 2026-11-06.

## Goal
The owner showed a demo video of another LMS and wants its useful teaching features in Tech Drona:
assignment creation, assessment creation, exam protocols (proctoring/integrity), polls/live
activities, learning-path creation, question banks and AI help. The catalogue of exactly what the
demo shows is in `docs/wiseman-reference/part-1.md … part-4.md` (read the parts relevant to you
fully: exact fields, options, workflows). Build the FUNCTIONALITY in Tech Drona's own stack,
design system and branding. **Never copy the other product's name, logo, wording of marketing
copy, or visual identity.** Use Tech Drona terminology and existing UI components.

## Ground rules
1. Use CodeGraph (`codegraph_explore`) before grep/Read. First do a short gap analysis of your area:
   what Tech Drona already has vs. the demo. Extend existing code; don't duplicate it.
2. Follow `docs/implementation-conventions.md` and existing module patterns: FastAPI module under
   `apps/api/app/modules/<name>/` (`models.py`, `router.py` exporting `router`, service files;
   routers auto-discovered), problem+json errors via `ProblemError`, RBAC via the existing
   `perm(...)`/`ensure_permission` scope checks (never frontend-only checks), RLS on every new
   table (copy the pattern of the nearest module migration), audit-log staff actions, idempotency
   on create endpoints where the module already uses it, outbox events for cross-module effects.
3. Migrations: new revisions only in your own module branch (`<module>_<NNNN>`); a brand-new module
   gets its own branch (`<module>_0001`, branch label = module name; `depends_on` the revisions it
   references). New RBAC permission keys/role grants are inserted by a data step in YOUR module's
   migration (`depends_on` the latest rbac revision) — never edit rbac's own migrations.
   Never edit an applied revision.
4. Web (Next.js 15, `apps/web/src`): pages in `src/app/...`, features in `src/features/<name>/`,
   API calls through the existing BFF/api client; keep CSRF/CSP patterns; responsive; a11y labels.
   Add your navigation entries with a minimal Edit to the existing nav config of the right portal.
5. AI: use ONLY `app.modules.ai.service` (contract already written — read it). Never call a model
   provider from your module. AI results are suggestions: stored as draft/pending, a human (or
   deterministic rule) finalizes. If the ai agent hasn't implemented a function yet, monkeypatch it
   in your tests; the UI must show a clear error state for 403/429/503 `ai_*` problems.
6. Student code is never executed on the API server — coding questions go through the existing
   `coding` module / judge worker.
7. No mock data in production paths; seeds only in dev seed scripts (you may add demo rows to the
   existing dev seed in a module-scoped function if one exists for your module).
8. Tests: backend `apps/api/tests/<module>/` (pytest; own DB `TD_TEST_DB_NAME=techdrona_feat_<key>`
   + `TD_TEST_RESET_DB=1`, run from `apps/api` with `.venv/Scripts/python -m pytest`), plus ruff +
   mypy on touched code. Web: vitest tests next to components, `pnpm lint`, `pnpm typecheck`
   (run in `apps/web`). Report real results only.

## Safety (same as the audit)
Never touch the `techdrona` dev DB, never run `scripts/reset-dev-data.ps1`, never stop/restart
docker containers, never drop other DBs, never print secrets, never git commit/push. Do not
regenerate `apps/api/openapi.json` or web generated API types — the coordinator does that once at
the end (list your new endpoints in your report instead).

## Ownership (edit only your paths; for anything else write a Request in your report)
| key | owns |
|---|---|
| ai | `apps/api/app/modules/ai/**` (implement the contract), ai migrations, `apps/api/tests/ai/`, admin web pages for org AI settings + per-org app enablement under `apps/web/src/app/admin/organizations/[id]/…` and `src/features/ai/` (shared AI UI pieces: tutor panel component, "Generate with AI" error states) |
| qbank | `apps/api/app/modules/placement/**` (question banks, question types, bulk import, AI generation endpoint), placement migrations, its tests, the question-bank web pages/features (existing studio question pages + `src/features/question-bank/`) incl. the reusable "Import questions from a bank" picker component |
| assign | assignment parts of `apps/api/app/modules/learning/**`, learning migrations, `apps/api/tests/learning/`, web `src/app/app/assignments/**`, `src/app/trainer/assignments/**`, `src/app/trainer/grading/**`, `src/features/learning/**` (assignment parts) |
| exam | `apps/api/app/modules/assessments/**`, assessments migrations, its tests, web `src/features/assessment/**`, `src/app/app/attempts/**`, `src/app/trainer/tests/**`, `src/app/trainer/integrity/**`, test-builder pages under studio |
| engage | NEW module `apps/api/app/modules/engage/**`, engage migrations, `apps/api/tests/engage/`, web `src/features/engage/**`, `src/app/trainer/engage/**`, `src/app/app/engage/**` (+ a join route) |
| paths | NEW module `apps/api/app/modules/paths/**`, paths migrations, `apps/api/tests/paths/`, web `src/features/paths/**`, `src/app/trainer/paths/**`, learner path pages (`src/app/app/path/**` — check what exists; company paths in `placement` stay untouched) |

Shared files (nav config, dev seed entry list, `app/wiring.py` handler registration): minimal
additive Edits only, re-read right before editing, never reformat.

## Output
Write `docs/wiseman-reference/build/<key>.md`: gap analysis table (demo feature → existed /
built / deferred-with-reason), endpoints added (method, path, permission), tables/migrations,
web pages, tests + exact commands and real results, Requests for other owners. Final message to
coordinator < 350 words.
