# Full Application Audit — Shared Brief (Phase A: audit only)

Coordinator: lead session. Started 2026-11-03. Every audit agent reads this file first.

## 1. Source of truth for "expected behaviour"
Read in this order (skim, then use as reference):
- `docs/source-requirements-excerpt.md` (owner's verbatim requirements, Section H reports H1–H12, Phase 8 scenarios)
- `docs/blueprint-brief.md` (contracts), `docs/product-requirements.md`, `docs/role-permission-matrix.md`
- `docs/api-specification.md`, `docs/database-schema.md`, `docs/sitemap.md`, `docs/wireframes.md`
- `docs/account-security-and-risk-engine.md`, `docs/account-unblock-workflow.md`, `docs/security-threat-model.md`, `docs/privacy-and-data-retention.md`, `docs/analytics-event-schema.md`
- `docs/architecture-decisions/ADR-*.md`, `docs/implementation-conventions.md`
- Current claimed state: `docs/implementation-status.md`, `docs/qa-report-backend.md`, `docs/qa-report-e2e.md`, `docs/stage10-integration-backlog.md`
Do NOT trust the status docs — they are claims to verify.

## 2. Code navigation
The repo is indexed by CodeGraph. Use the `codegraph_explore` MCP tool (or shell `codegraph explore "<query>"`) BEFORE grep/Read for code. Backend: `apps/api/app/` (modules under `app/modules/<name>/`). Web: `apps/web/src/` (App Router pages in `src/app`, features in `src/features`, BFF in `src/lib/bff` and `src/app/api`).

## 3. Phase A rules (audit only)
- **Do NOT modify any application source, migration, config, test, seed, or doc file** except your own findings file `docs/audit/<your-area>.md`. Scratch probes/scripts go in your scratchpad or `apps/api/tests/_audit_scratch/<area>/` (you may create tests there to reproduce issues; they will be reviewed later).
- **Never fabricate**: every finding must include the evidence you actually observed (command + trimmed output, file:line, HTTP status/body). If you could not reproduce it, mark it `Suspected` not `Confirmed`.
- **Never** print or copy secrets (.env values, keys, tokens, passwords other than the documented dev demo password, OTPs, raw session ids).
- **Database safety**: For pytest use your OWN database: set `TD_TEST_DB_NAME=techdrona_audit_<area>` and `TD_TEST_RESET_DB=1` (from `apps/api`, `.venv/Scripts/python -m pytest ...`). Do NOT touch `techdrona` (dev DB), do not run `scripts/reset-dev-data.ps1`, do not `docker compose down -v`, do not drop any database other than your own `techdrona_audit_<area>`. Only the E2E-workflow agent may drive the running stack (http://localhost:13000 web, :18000 api, :8025 mailpit) and only through normal app actions.
- Do not stop or restart docker containers (other agents depend on them). Infra: Postgres :15432, Redis :16379/:16380.
- Do not deploy, call real external services, or push to git.

## 4. Findings file format (`docs/audit/<area>.md`)
Start with a **feature/coverage inventory table** for your area: `Feature/Req ID | Requirement source | Code location | Audit method | Result (Verified OK / Issue / Not built / Blocked)`.
Then one block per issue:

```
### <AREA>-<NN>: <title>
- Severity: Critical | High | Medium | Low
- Status: Confirmed | Suspected
- Component: file:line (and endpoint/page)
- Requirement: doc § / req id
- Repro: steps or test
- Expected / Actual:
- Evidence: (actual output)
- Root cause:
- Recommended fix (minimal, preserve architecture):
- Suggested owner paths (files the fixer would edit):
```
Severity guide: Critical = security hole, data loss/leak, cross-tenant access, money wrong, core workflow dead. High = requirement broken or backend permission gap, frontend calling non-existent API. Medium = incomplete/inconsistent behaviour, missing error handling. Low = cosmetic/docs drift.

End with a short summary: counts per severity, what you could not test and why.

## 5. Final message to the coordinator
Return: path of your findings file, counts per severity, the top 10 issues (ID + one line), and any conflicts with other areas you noticed. Keep it under 400 words.
