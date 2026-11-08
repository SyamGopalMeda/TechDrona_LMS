# WS3: Admin and AI (per-org settings become platform settings)

| | |
|---|---|
| Status | Done (REMOVAL-PLAN §1.2 admin/AI, §2.3, §5 step 6, §6 WS3, owner decisions D2 and D10) |
| Date | 2026-11-07 |
| Dev DB | Not touched. Tests ran only on the scratch DB `techdrona_ws3`. |
| Owned | `apps/api/app/modules/{admin,ai}/**`, migrations `admin_0004`, `ai_0002`, `tests/{admin,ai}/**` |

## 1. Migrations

Both depend on `orgs_0001` only (never `orgs_0002`, see ws1.md §2).

| Revision | Effect |
|---|---|
| `ai_0002_platform_settings` (after `ai_0001`) | Creates `ai_settings` (singleton, `id smallint CHECK (id=1)`) with non-NULL caps: `monthly_token_cap` 50M, `monthly_call_cap` 50k, `per_activity_default_cap` **20** (D10), `tutor_per_minute` 10, `tutor_per_day` 200, `generate_per_hour` 30, `generate_per_day` 100. Creates `app_settings(app_key PK, enabled)` (absent row = enabled). Seeds both from the company org's `ai_org_settings` / `org_app_settings` rows if present (NULL caps → defaults), then drops those two tables. `ai_usage` gets the `reserved` outcome, a `created_at` index, column UPDATE grants for finalisation and a trigger that only lets a `reserved` row change once. New `ai_tutor_turns` (server-side tutor history). All new tables have FORCE RLS: settings = platform only; turns = own rows or platform. |
| `admin_0004_platform_policy` (after `admin_0003`) | Deletes organization-scoped `policy_settings` rows and every row of the removed key `org.notify_coordinator_on_restriction`. Drops `policy_settings.org_overridable` and `feature_flags.org_allowlist`. The scope CHECK becomes `platform\|plan\|user` (`ck_ps_scope_type`). Remaps `privacy_requests.requester_relationship='college'` to `'self'` and tightens that CHECK (`ck_prq_relationship`). `break_glass_sessions.elevated_role` now defaults to `super_admin`. FORCE RLS is lifted only around the data steps and restored in the same transaction. |

Both `downgrade()`s restore the schema only. Restore the data from the backup dump.

## 2. Admin module

- **Policy** (`policy.py`):
  - Precedence is now **user > plan > platform > code default**. `resolve`, `get_value` and `identity_resolver` still accept `org_id`, but ignore it.
  - `PolicyKey.org` is gone. The scopes are `platform`, `plan` and `user`; `organization` now gives a 422.
  - Removed key: `org.notify_coordinator_on_restriction`.
  - **Registered** `auth.require_mfa_students` (bool, default false), so Admin can now set it through the policy API.
  - `PROPOSE_NAMESPACES = {"super_admin": ("",)}` (D2).
  - The tighten error code was renamed to `override_may_only_tighten`.
- **Flags:** `org_allowlist` was removed from the model, the snapshot, `FlagPatch` (sending it now gives a 400) and the output. Calls with `org_id=` still work; the value is ignored.
- **Router:**
  - Deleted `GET /orgs/{org_id}/privacy-requests`.
  - Policy changes require approver role `super_admin`, with handler roles `admin_roles()`.
- **Accounts:**
  - The dashboard no longer has the `organizations` tile.
  - User detail no longer has `organizations`.
  - MFA reset: the approver role is `super_admin` and handler roles are `admin_roles()`. Dual control means two different admins.
  - `ALERT_ROLES = admin_roles()`.
  - **Break-glass activation is retired**: `POST /admin/break-glass` now returns 405. The role it elevated to (`security_reviewer`) is gone, and Admin already holds every break-glass permission. List, end and review, and the expiry job, still work for historic sessions.

## 3. AI module

### 3.1 Routes

| Route | Permission (platform scope) |
|---|---|
| `GET/PATCH /admin/ai-settings` | `feature_flag.manage`. PATCH needs a step-up within 300 s and is audited as `ai.settings.updated`. Caps can no longer be set to null. |
| `GET/PATCH /admin/apps` | `feature_flag.manage`. PATCH needs a step-up and is audited as `ai.apps.updated`. |
| `GET /admin/ai-usage?month=YYYY-MM` | `analytics.read.platform`. Returns platform totals, broken down by feature and by day, plus the caps. |
| `GET /me/enabled-apps` | Returns the platform set `{apps, ai_enabled}`. The `org_id` query and the `organization_id` field were removed. |
| `GET /me/ai/tutor-history?context_type=&context_id=&item_id=&limit=` | The caller's own turns only (RLS). |

`/admin/orgs/{id}/ai-settings|apps|ai-usage` now return 404. Web phase 2 must repoint `AI_ADMIN_BASE` in `apps/web/src/features/ai/admin/endpoints.ts`, and drop `organization_id` / `org_allowlist` / `org_overridable` from its types.

### 3.2 Security fixes

- **SEC-05:** per-user rate limits.
  - `enforce_tutor_rate` (Redis key `ai:tutor:{uid}`) and `enforce_generate_rate` (key `ai:generate:{uid}`) take their limits from `ai_settings`.
  - A limit hit returns 429 `rate_limited`.
  - `tutor_reply`, `generate_questions` and `generate_path` enforce them internally.
- **SEC-14 and SEC-15:** `store.reserve` runs in its own short committed transaction (`ledger_tx`). It:
  - takes a `pg_advisory_xact_lock`;
  - checks the platform month caps, counting in-flight `reserved` rows;
  - checks the tutor limit for the learner and activity, when given;
  - inserts a `reserved` row carrying the worst-case estimate.

  The provider is then called with no AI lock and no AI transaction open. `store.finalize` then writes the real outcome and tokens in another short transaction, so spend is recorded even if the request rolls back. The old `lock_tutor_context`, which held a lock across the provider call, is gone.
- **SEC-17:**
  - `tagged()` now escapes `<tag>` and `</tag>` regardless of case or whitespace, as `&lt;/tag&gt;`.
  - Tutor history is kept on the server in `ai_tutor_turns`. The client `history` argument is ignored.
  - The erasure provider deletes a user's turns and pseudonymises their usage rows.
- **SEC-19:** `require_app_enabled(session, app_key="question_banks")` and `is_app_enabled` are the helpers. WS5 calls them in `_bank_for` and `resolve`.

The copy no longer says "organization" or "college students".

## 4. APIs for WS4 and WS5 (`app.modules.ai.service`)

```python
async def require_app_enabled(session, org_id=None, *, app_key: str) -> None   # 403 app_disabled; org_id ignored
async def is_app_enabled(session, app_key: str) -> bool
async def ai_enabled(session, *, org_id=None, app_key: str | None = None) -> bool  # org_id ignored
async def enforce_tutor_rate(principal: Principal | uuid.UUID, *, session=None) -> None  # 429 rate_limited
async def enforce_generate_rate(principal: Principal | uuid.UUID, *, session=None) -> None
async def tutor_reply(session, *, user_id, context_type, context_id, mode, question_md, learner_input,
                      per_learner_limit=None, item_id=None, org_id=None, history=None) -> dict
    # {"reply_md", "used", "limit"}; limit = min(per_learner_limit, platform cap 20); history IGNORED
async def tutor_history(session, *, user_id, context_type, context_id, item_id=None, limit=50) -> list[dict]
    # [{"role": "learner"|"tutor", "content", "created_at"}] oldest first, caller RLS
generate_questions / grade_response / generate_path: unchanged keywords; org_id optional and ignored
```

**WS4 (`learning/structured_api.py` tutor route):**
- Pass `item_id=body.item_id`.
- Stop sending `history`; the client field can go.
- Optionally expose `tutor_history`, or let the web use `/me/ai/tutor-history`.
- `tutor_reply` already rate-limits. Call `enforce_tutor_rate` yourself only to refuse a request early (that counts one extra hit).
- `ai_help_limit = None` now means the platform default of 20 (D10).
- **Residual SEC-15 risk:** the AI module no longer holds anything during the provider call, but the caller's request transaction is still open. Do not take `FOR UPDATE` locks before `tutor_reply`.

**WS5:** in `placement/qbank_router.py`, call `require_app_enabled(session, app_key="question_banks")` in `_bank_for` and `resolve`.

**Everyone:** drop `org_id=` at the call sites. WS3 will remove the parameter after WS4 and WS5 merge.

**Semantic change:** an app toggle now applies to every user. Before, `org_id=None` (public learners) was always allowed.

## 5. Tests (real runs, scratch DB `techdrona_ws3`)

Command, run from `apps/api`:

```
TD_TEST_DB_NAME=techdrona_ws3 TD_TEST_RESET_DB=1 .venv/Scripts/python -m pytest tests/admin tests/ai tests/authz -q
```

Result: **90 passed** in 3 min 05 s, on a fresh database run through `alembic upgrade heads`.

- `tests/ai` covers:
  - platform gating and `org_id` being ignored;
  - non-NULL caps, and that caps are platform-wide;
  - D10 default 20, which Admin can edit;
  - the tutor's 429 after its rate limit, and the generate rate limit;
  - a reservation that is visible while the provider runs (SEC-15), and an in-flight reservation that blocks a concurrent call over the cap (SEC-14);
  - that the ledger is immutable;
  - server-side history: forged client turns are ignored, history is per item, RLS shows own rows only;
  - the case-insensitive tag escape;
  - the new admin routes, permissions and step-up, that the old `/admin/orgs/*` routes return 404, `/me/enabled-apps` and erasure.
- `tests/admin` covers:
  - precedence user > plan > platform;
  - that organization scope is rejected and the removed key is gone;
  - the MFA key being registered;
  - dual control with two admins, for policy changes, MFA resets and privileged grants;
  - that flags no longer have an org allowlist;
  - that break-glass activation is retired while history is still managed;
  - that the org privacy route is gone.
- `ruff check .`, `ruff format --check .` and `mypy app` (258 files) are clean.
