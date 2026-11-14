# Data-content agent: catalog, entitlements, media, paths

> **Removed 2026-11-14** ([cleanup/feature-removal-plan.md](../../cleanup/feature-removal-plan.md)): mentoring (slots, bookings, sessions, feedback, mentor notes, résumé reviews, the `/mentor` console; the Résumé builder stays), company paths (the `companies` entity stays), corporate enquiries, `GET /catalog/search`, the public SPA pages Hosting redirects to the website, and the `/app/diagnostic`, `/admin/question-review`, `/admin/notifications`, `/app/bookmarks`, `/app/analytics` and `/security/policies` pages. Mentions below of those features are historical.

Rounds 1–2 (2026-11-12). **Every `TD_STORE_*` still defaults to `postgres`**; nothing was deployed.

Test policy (owner, round 2): there is no Docker/Postgres. Tests run on the Firestore emulator
(127.0.0.1:18080) with `TD_TEST_NO_PG=1 TD_TEST_DB_NAME=content_test`. Parity is checked later
against the live VM.

## 1. Status

| Module | Repository + routing | `public.py` | HTTP tests (Firestore, no Postgres) | Flippable? |
|---|---|---|---|---|
| **catalog** | Complete. P2b repository, plus `course_status_counts`. Routes no longer read the RLS settings from the Postgres session (§3). | Yes | Studio (create, slug conflict, draft patch, lessons, outline, submit, SoD-04, publish with idempotency, versions, list, archive) and public (list, detail, search, draft hidden). Students denied. | Yes, once the R-items below that touch catalog land (R1, R2, R12) |
| **entitlements** | Complete. Collections `entitlements`, `entitlement_events`, `entitlement_sources`. Each change re-reads the document in one transaction (the `FOR UPDATE` equivalent). Grants are idempotent per source. Product reads go through `commerce.public`. | Yes (full read/write API, plus `firestore_repo()` for callers inside a Firestore transaction) | ENT-01/02 checks, ENT-03/04/05 reads, ENT-06 manual grant (idempotent replay, step-up), revoke and a second-revoke 409 | Yes, once R3–R7 land (callers still selecting `Entitlement`) |
| **media** | Complete. `playback_sessions` with a 180-day TTL; a per-user lock document replaces the advisory lock. Identity, sessions and security (INV-12) are reached through their `public.py`. | Yes (storage and provider helpers; no other module touches `playback_sessions`) | MED-04 token issue, cap conflict with device label, take-over, MED-05 heartbeat (active, 404 to another session, 410 after take-over), MED-06 stop, cap freed | Yes |
| **paths** | **Complete (new in round 2).** All 73 SQL sites route through `paths/store.py` (Postgres SQL unchanged, Firestore through `repo_firestore.py`). Other modules' tables go through `paths/adapters.py`, which calls orgs, identity, learning and assessments `public.py`. **No SQL is left in `paths/service.py`.** | Yes (outbox wiring; no other module reads paths tables) | Author → steps → publish → allocate → learner open (ON CONFLICT no-op) → too-early / dwell → complete → `attempt.scored` evidence (idempotent) → staff progress → articles (create, list, audience publish, reader, delete) → archive revokes. Learners cannot author. | Yes |

**Platform finding handled.** Every catalog, entitlements, media and paths route covered by the
HTTP tests runs with the request session set to `NO_POSTGRES` (or `None`, see R10). Any Postgres
access fails the test. `/catalog/courses`, `/catalog/courses/{slug}` (`/catalog/search` removed 2026-11-14) and the
studio routes pass.

## 2. Data models (Firestore, `lms_` prefix)

- **catalog**: as in `p2.md`.
- **entitlements**:
  - `entitlements/{id}`: owned by user, owner cannot write;
  - `entitlement_events/{id}`: append-only, written in the same transaction as the change;
  - `entitlement_sources/{order_item|subscription|coupon_redemption:id}`: replaces the three partial unique indexes.
- **media**:
  - `playback_sessions/{id}`: owned, `expire_at` TTL;
  - `playback_users/{uid}`: lock and index, not backfilled, seeded on first use.
- **paths**:
  - `learning_paths/{id}`: embeds the draft `steps` tree plus `article_ids`.
  - `learning_path_versions/{id}`: embeds immutable `steps` plus `assignment_ids` / `test_ids` / `article_ids` for `array-contains` reverse lookups.
  - `path_articles/{id}`.
  - `path_allocations/{id}`: `user_ids` array.
  - `path_step_progress/{alloc:user:step_key}`: deterministic id replaces the UNIQUE constraint.
  - Decimals are exact strings; dates are ISO.
  - Postgres server defaults are filled on insert (`fill_defaults`, as `eager_defaults` loads them).
  - Publish checks `version_no` in one transaction, so `UNIQUE (path_id, version_no)` holds; a concurrent publish gets 409.

Indexes: `app/modules/{entitlements,media,paths}/firestore.indexes.fragment.json`, for the
coordinator to merge. The paths fragment was rewritten in round 2 for the repository's queries.

## 3. Round-2 changes

| File | Change |
|---|---|
| `app/modules/{catalog,entitlements,media,paths}/public.py` | **New.** The module boundary for other modules (catalog re-exports `api.py` plus `course_status_counts` / `register_publish_hook`; entitlements exports the full API plus a mapping for every direct select callers still use). |
| `paths/store.py`, `paths/repo_firestore.py`, `paths/adapters.py` | **New.** Persistence switch, Firestore repository, cross-module reads through other modules' `public.py`. `system_context` scopes are kept on Postgres. |
| `paths/service.py` | 73 SQL sites replaced by `store` / `adapters` calls; the logic is unchanged (diff reviewed). `link_options` passes the raw `q` to learning and assessments, which escape it themselves. |
| `paths/store_specs.py` | Link arrays on path and version documents (backfill matches the repository). |
| `catalog/repo_firestore.py`, `catalog/router.py`, `catalog/service.py` | The TN view is bound per request from the principal (studio) or as anonymous (public) through include-time dependencies. `visibility()` reads it when there is no Postgres session. `ensure_permission` no longer restores RLS on a session-less stack. |
| `entitlements/service.py`, `entitlements/router.py` | Product quotas, coverage, titles and upsell catalogue now come from `commerce.public`. `system_context` / `as_system` are skipped without a Postgres session. |
| `media/adapters.py`, `media/service.py` | **New** adapters: watermark (identity `user_cards`), device label (sessions `get_device`), INV-12 unblock scan SQL (security; moved, still SQL). |
| `tests/paths/fs/http_harness.py` | **New** shared harness: real app, sessions = `NO_POSTGRES`, FakeAuth, core audit/outbox/cache recorders, maintenance-flag stub. |
| `tests/{catalog,entitlements,media,paths}/fs/test_*_http.py` | **New** HTTP suites (§1). |

## 4. Commands and real results (2026-11-12)

```
cd apps/api
export TD_TEST_NO_PG=1 TD_TEST_DB_NAME=content_test TD_TEST_FIRESTORE_AUTOSTART=0
.venv/Scripts/python.exe -m pytest tests/catalog tests/entitlements tests/media tests/paths -q -p no:cacheprovider
#   -> 45 passed, 90 skipped (the skipped ones are the Postgres-backed suites)
ruff check (my modules + tests) -> clean
ruff format --check -> clean except tests/catalog/test_firestore_repo.py (pre-existing P2b file, not mine)
mypy app/modules/{catalog,media,entitlements,paths} -> no issues in these modules
```

Not run (policy): the Postgres matrix (`tests/entitlements/test_store_matrix.py` and the P2b
matrices) and backfill → verify against a real database.

## 5. Requests to other agents

| # | To | Request |
|---|---|---|
| R1 | data-ops (admin) | `admin/accounts.py` ~L170: use `catalog.public.course_status_counts` instead of `select(Course.status, count)`. |
| R2 | data-money (admissions) | `admissions/student.py` `_course_hrefs`: use `catalog.public.get_courses` (`.slug`). |
| R3 | data-money (commerce) | Replace direct `select(Entitlement)` (`service.py`, `billing.py`, `pricing.py`, `admin.py`) with `entitlements.public`: `for_order_items` / `for_coupon_redemptions`, `for_subscription(for_update=True)`, `user_entitlements`, `source_type_counts`. With commerce on Firestore, use `firestore_repo().grant_many_tx` / `transition_many_tx` inside the order transaction. |
| R4 | data-learning (mentoring) | Use `usable_entitlements` / `is_usable` and `credit_quota`. `credit_back`'s mutate plus `record_event` writes only the event on Firestore. |
| R5–R7 | support, admissions, seeds | Use `user_entitlements` / `get_entitlement(for_update=True)` instead of selecting `Entitlement`. |
| R8 | coordinator | Merge the three index fragments (including the `lms_playback_sessions.expire_at` TTL). |
| R9 | data-ops (ai) | FYI (round 1): `ai/store.py` briefly contained a literal NUL character, which broke imports. |
| **R10** | **platform** | `core/firestore/core_store.py` L350: `session.begin_nested() if session is not None` treats the falsy `NO_POSTGRES` as a real session and raises. It should test `if session`. My catalog and entitlements HTTP suites use `session=None` until this is fixed. |
| R11 | data-ops (security) | **Done (round 4):** `security.public` exposes `set_unblock_attachment_scan` / `pending_unblock_attachment_keys`, and `media/adapters.py` now calls them. Media touches no foreign table. |
| **R12** | platform / all | Other modules calling `catalog.public` without a Postgres session get the **anonymous** TN view unless they bind one (`catalog.repo_firestore.bind_view(principal_view(p))`). Better: core should publish the request's RLS context (principal or system job) in a `ContextVar` that `visibility()` can read. Also: `rbac.public` should re-export `role_permission_map` / `batch_org` (catalog's studio list imports them from `rbac.service`; both are store-aware). |

## 6. Known differences and gaps

1. **Cross-store ordering.** Until audit/outbox/core run on Firestore, a Firestore write commits
   before the caller's Postgres audit/outbox rows (as in P2b.4 #1).
2. **No HTTP coverage of some routes.** Only the routes listed in §1 run over HTTP. Others are
   covered at service level only:
   - catalog: resources, lesson preview, topics;
   - paths: AI generate, batch-member picker, allocation preview;
   - media: uploads and downloads.

   A remaining Postgres touch in those routes would show up only on the deployed stack.
3. **In-memory filtering.** Paths list/search filter in memory (company content, ≤ 200 shown, as on Postgres).
4. **Concurrent path publish.** Firestore returns 409 `conflict`; Postgres raised IntegrityError (500).
5. **Paths writes are plain updates.** There are no row locks on Postgres either, so last writer wins, as before.
