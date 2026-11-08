# Audit Phase B — Fix Brief (binding for every fix agent)

Coordinator: lead session. 2026-11-03.

## Inputs
Audit findings (verified, with evidence): `docs/audit/00-feature-inventory.md` (INV-), `backend-business-logic.md` (BE-), `security-authz.md` (SEC-), `database-integrity.md` (DB-), `commerce-integrations.md` (COM-), `admin-staff-portals.md` (ADM-), `frontend-ux.md` (FE-), `e2e-workflows.md` (E2E-, may still be in progress). Probes reproducing them: `apps/api/tests/_audit_scratch/**`, `apps/web/src/__audit_scratch__/`.
Requirements: see `docs/audit/AUDIT-BRIEF.md` §1. Conventions: `docs/implementation-conventions.md`. Use CodeGraph (`codegraph_explore`) before grep/Read.

## Your scope = your OWNED PATHS
Fix every issue (all severities, Critical→Low) from ANY audit file whose fix lies in your owned paths. Duplicate IDs across files describe the same bug — fix once, list all IDs.
If a fix needs an edit outside your owned paths: do NOT make it; write it as a request in your fixes file (§Requests, with exact change wanted). The coordinator dispatches those later.

## Process per issue
1. Reproduce first (run the audit probe or write a failing test). If it does not reproduce, mark `Not reproduced` with evidence; do not change code.
2. Minimal fix preserving architecture, business rules, stack and branding. No mock data in production paths. No disabling/skipping tests.
3. Turn the reproduction into a permanent regression test in the module's normal test folder (`apps/api/tests/<module>/`, web `*.test.tsx` next to the feature, or `apps/web/e2e/`).
4. Run your modules' full test suites + ruff + mypy (api) or lint + typecheck + vitest (web) for touched code. Report real results.

## Decisions already made by the coordinator (apply, don't re-ask)
- Owner's verbatim requirements (`docs/source-requirements-excerpt.md`) win over our derived docs. So: ALL H1–H12 report views are audit-logged (ADM-10).
- API spec wins over code where the spec is explicit and feasible (e.g. SEC-09 student step-up: follow the spec's allowed methods; if a student has no second factor enrolled, use email OTP step-up as the spec's fallback if defined, otherwise keep password and document it in your fixes file).
- Not-built UI pages: build them against the EXISTING APIs with real data; legal pages (terms/privacy/refund) get structured content derived from `docs/privacy-and-data-retention.md` and product rules, with a visible "Draft — pending legal review" banner (no invented legal claims).
- External providers without credentials (SES, MSG91, Razorpay live, VdoCipher, Judge0): implement the real adapter code against the provider's documented API where missing, keep it unverified, and make production startup refuse to run without real config. Do not call real providers.
- Unique-constraint races must return 409 problem+json, never 500. Validation errors: one consistent status per the API spec.

## Safety
- Use your own test DBs: `TD_TEST_DB_NAME=techdrona_fix_<agentkey>` (+ `_2` etc.), `TD_TEST_RESET_DB=1`. Never touch the `techdrona` dev DB, never run `scripts/reset-dev-data.ps1`, never stop/restart docker containers, never drop other DBs, never print secrets, never git push/commit.
- Migrations: new revisions only in your owned module branches (`<module>_<NNNN>`), never edit an already-applied revision.

## Output
Write `docs/audit/fixes/<agentkey>.md`: table `ID(s) | Severity | Fix summary | Files | Regression test | Result (Fixed+tested / Not reproduced / Deferred: reason / Request to other owner)`, then §Requests, then the exact test commands and results. Final message to coordinator (<350 words): counts fixed/deferred/not-reproduced, test results, requests for other owners.
