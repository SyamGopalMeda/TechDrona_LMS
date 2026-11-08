# Tech Drona LMS — API (`apps/api`)

FastAPI modular monolith. Foundation (`app/core`, `app/modules/audit`, migrations env, test
fixtures) is owned by the Backend Foundation engineer; every other `app/modules/<module>` is
owned by its module agent. Binding rules: `docs/implementation-conventions.md`.

## Quick start (Windows dev machine; same commands in CI)

```powershell
docker compose up -d                                   # repo root: postgres, redis x2, mailpit
cd apps/api
python -m venv .venv
.venv/Scripts/pip install -e ".[dev]"
.venv/Scripts/alembic upgrade heads                    # every module branch
.venv/Scripts/pytest                                   # uses database techdrona_test
.venv/Scripts/ruff check . ; .venv/Scripts/mypy
.venv/Scripts/uvicorn app.main:app --reload --port 8000
```

Settings come from the environment, then `apps/api/.env`, then the repo-root `.env`
(`cp .env.example .env`). Tests derive `techdrona_test` URLs from `DATABASE_URL`,
`DATABASE_MIGRATION_URL`, `DATABASE_AUDIT_SEALER_URL` (or `TEST_*` overrides).
`TD_TEST_RESET_DB=1` drops/recreates `techdrona_test` first (needs the compose superuser
`techdrona`).

## Database roles (what we chose)

| Connection | Role | Notes |
|---|---|---|
| `DATABASE_MIGRATION_URL` | `td_owner` | Alembic only; owns every object. Migrations always run through psycopg (multi-statement DDL). |
| `DATABASE_URL` | `td_app` | API + workers. Not owner, `NOBYPASSRLS` → `FORCE ROW LEVEL SECURITY` really applies (tests assert `current_user = td_app`). |
| `DATABASE_AUDIT_SEALER_URL` | `td_audit_sealer` | Only role that can INSERT into `audit_log`. |
| `DATABASE_READ_URL` | `td_readonly` | SELECT, RLS applies. |

docker-compose creates the login roles (`scripts/db-init`). `core_base_0001` creates any that
are missing as `NOLOGIN` (if it has CREATEROLE) and sets default privileges so tables created
later by the migration role grant DML to `td_app` and SELECT to `td_readonly`. Optional
`TD_DB_SET_ROLE=td_app` makes every app transaction `SET LOCAL ROLE td_app` if you
deliberately connect as a superuser (not needed with compose).

## Extension points for module agents

| Need | Use |
|---|---|
| Router (auto-discovered, mounted at `/api/v1`) | `app/modules/<m>/router.py` exposing `router = authenticated_router(prefix=..., route_tag="default", idle="extends")` or `public_router(...)` from `app.core.routing`. Per-route overrides: `openapi_extra={"x-td-route-tag": "account_status", "x-td-idle": "neutral"}`. Webhooks: `webhook_router` (mounted when `TD_ROUTER_SET=webhooks`). |
| Models (auto-imported) | `app/modules/<m>/models.py`, subclass `app.core.db.Base`. |
| DB session | `session: DbSession` (public, empty RLS context) or `session: PrincipalDbSession` (principal's RLS context) from `app.core.db`; system jobs: `system_context(session, "job_name")`. Commit happens before the response is sent. |
| Principal | `Depends(require_active_principal)` → `app.core.principal.Principal`. |
| Session lookup (sessions module) | `app.core.auth.register_session_resolver(obj)`; `obj.resolve(request, session_token, ctx: RouteContext) -> Principal`. Until registered: `401 unauthenticated`. Device cookie value: `request.state.device_token`; client IP: `request.state.client_ip`; BFF activity header: `request.state.activity`. |
| Permissions (rbac module) | `app.core.auth.register_permission_checker(obj)`; `obj.has_permission(principal, key, ScopeRef, request) -> bool`. Routes: `Depends(require_permission("key", scope=scope_from_path("org_id", "organization")))`. Until registered: `403 permission_denied`. |
| Step-up | `Depends(require_step_up("privileged" \| "staff" \| "student" \| seconds))`. |
| Errors | `raise ProblemError("code", **extension_members)` (`app.core.errors`; catalogue = api-spec §2). |
| Idempotency | `await idempotent(request, session, user_id=..., operation=op, money=...)` with `op() -> IdemResult` (`app.core.idempotency`). |
| Domain events | `await emit_event(session, "module.thing_happened", payload, aggregate_type=..., aggregate_id=...)` (`app.core.outbox`). |
| Audit | `await audit(session, principal_or_AuditActor, "action.key", "target_type", target_id, ...)` (`app.core.audit`). |
| Migrations | Own branch per module: `revision="<m>_0001"`, `down_revision=None`, `branch_labels=("<m>",)`, `depends_on=("core_base",)`; RLS via `app.core.migration_helpers.enable_rls(table, "T"\|"TN"\|"U"\|"O")`, `add_updated_at_trigger(table)`, `revoke_app_writes(table)`. |
| Fake adapters | `app.core.startup_checks.register_fake_adapter(name, lambda s: ...)` — refused at startup when `APP_ENV=prod`. |
| IDs / time / money / crypto | `app.core.ids.uuid7()`, `app.core.time.utcnow()/to_rfc3339()`, `app.core.money.*` (paise), `app.core.security.hash_password/verify_password/generate_token/hash_token/get_keyring("device"\|"login")`. |
| Tests | fixtures `db`, `client`, `app`, `auth` (`auth.login(principal) -> headers`, `auth.grant(principal, perm)`), `make_principal`, `committed_engine`, `sealer_engine` (`tests/conftest.py`). |

## Cross-module wiring and background jobs (Stage 10)

* `app/wiring.py` — `wire_all()` plugs module extension points together (entitlement parent
  resolvers, usage provider, video coverage / final-test lookups, coding attempt validator,
  engaged-bucket feed, lesson meta) and registers outbox handlers (analytics consumer,
  `media.stream_cap_hit` -> security signal, `security.false_positive_credit` -> entitlement
  extension, `submission.judged` -> coding-question re-score). Called by `create_app()` and the
  Celery app, so API and workers share one wiring.
* Celery (`app.worker`): `celery -A app.worker worker -Q critical,default`, `celery -A app.worker
  beat`, and on the judge host `-Q judge_assessment,judge_submit,judge_run`. Beat entries come
  from each module's `tasks.py` (`register_periodic`): outbox relay, audit seal, assessments
  deadline sweeper (5 s, critical), analytics jobs, security decay/expiry/SLA/heartbeat,
  commerce webhook retry (critical) / order expiry / reconciliation, entitlement expiry, coding
  pending sweep.
* `TD_COMMERCE_WEBHOOK_MODE=inline|queue` — `queue` hands verified webhooks to
  `commerce.process_webhook_event` on the `critical` queue.
* Public permission probe for services: `app.core.auth.check_permission(principal, key, scope)`.
* OpenAPI: `python -m app.scripts.export_openapi` writes `apps/api/openapi.json`.

## Audit

`audit()` writes `audit_outbox` in the business transaction. The sealer
(`python -m app.modules.audit.sealer [--once]`, role `td_audit_sealer`) assigns gap-free `seq`
and `row_hash = sha256(prev_hash ‖ canonical_json(row))` into partitioned, append-only
`audit_log` (UPDATE/DELETE/TRUNCATE revoked and trigger-blocked). `GET /api/v1/audit/events`,
`/audit/events/{seq}`, `/audit/chain-status` require `audit.read` and a platform context.
S3 Object Lock anchoring and AUD-04/05 are Planned.
