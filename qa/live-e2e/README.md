# Live-site audit (Playwright on Google Cloud Build)

Tests run ONLY against the live sites (https://techdrona-lms-app.web.app, https://techdrona-website.web.app) and ONLY in the cloud. Nothing heavy runs on the laptop.

    bash qa/live-e2e/run.sh tests/<spec>.spec.ts [--projects=desktop,laptop,tablet,tablet-landscape,phone-android,phone-iphone,phone-small|all] [--roles=admin,content,trainer,evaluator,student] [--workers=2] [--shots]

The script prints `qa/live-e2e/runs/<build-id>/`, which holds `results.json`, `exit_code` and `findings/*.json`. With `--shots` it also downloads the screenshots.
- Full artifacts: gs://td-qa-reports-f4fe3/runs/<build-id>/ (deleted after 30 days).
- Machine: e2-standard-2. It is covered by the 2,500 free Cloud Build minutes a month; a 35-check smoke run takes about 3 minutes.

**QA accounts** (synthetic, qa-*@qa.techdrona.test; the owner approved them 2026-11-14):

| Role | Scope |
|---|---|
| admin (super_admin) | platform |
| content (content_manager) | platform |
| trainer | batch "Generative AI" |
| evaluator | batch "Generative AI" |
| student | platform |

- Credentials are kept only in Secret Manager `td-qa-creds`. `lib/global-setup.ts` signs each role in once per run.
- Session cookies are deleted before the results are uploaded.

**Helpers** (`lib/probe.ts`):
- `watch(page)` collects console errors and failed API calls.
- `layoutIssues(page)` reports horizontal scroll, content overflowing the viewport, and small tap targets on touch devices.
- `shot()` saves a screenshot.

**Rules for specs:**
- Navigation and reading only. Never submit forms that create, change or delete live data.
- Write machine-readable findings to `out/findings/<spec>-*.json`.
