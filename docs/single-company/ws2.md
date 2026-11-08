# WS2: Commerce and entitlements (B2B removal)

| | |
|---|---|
| Status | Done. Migrations `entitlements_0003` and `commerce_0004` are in the Alembic graph. |
| Date | 2026-11-07 |
| Plan | `REMOVAL-PLAN.md` §1.2 (commerce and entitlements), §5 step 5, §6 WS2, and §8 D1 and D2 |
| Dev DB | Not touched. Runs used `techdrona_ws2`, plus `techdrona_ws2_dump`, which is a restore of `backups/techdrona-dev-before-college-removal-20261106.dump`. |

## 1. Code changes

### Commerce
- **`router.py`:**
  - Removed `_own_org`.
  - Removed `/finance/contracts`: GET and POST, PATCH `{id}`, `{id}/terminate`, and GET and POST `{id}/invoices`.
  - Removed `/orgs/{id}/contract`, `/orgs/{id}/invoices` and `/orgs/{id}/invoices/{id}/pdf`.
  - Approver role is now `ADMIN_ROLE` (`super_admin`) for refunds, coupons and prices.
- **`admin.py`:**
  - Removed `contract_json`, `create_contract`, `amend_contract` and `terminate_contract`, and the `commerce.contract.terminate` approval.
  - The public catalogue filter is now just `status == active`.
  - The coupon JSON no longer has `organization_id`.
- **`billing.py`:** removed `issue_contract_invoice` (COM-42). Nothing in commerce reads the college columns of `organizations` any more.
- **`billing_approvals.py`:** every approver set is `admin_roles()`, and the contract-terminate action is gone.
- **`policy.py`:** removed the `CONTRACT_*` and `SEAT_*` constants.
- **`schemas.py`:** removed `ContractIn`, `ContractPatchIn`, `ContractInvoiceIn`, `CouponIn.organization_id` and the `institution_seat` product kind.
- **`pricing.py`:** removed the college coupon rule (`org_ids`) and `included_via_college`.
- **`models.py`:** removed `InstitutionContract`, `Invoice.contract_id` and `Coupon.organization_id`. `Invoice.description` and `due_on` stay, for the legacy invoices.
- **`documents.py`:** an invoice line uses `inv.description or product name`. The footer no longer mentions institution invoices.
- **`service.py`:** `invoice_json` has no `contract_id`. Legacy offline-PO orders are still never auto-expired.

**Kept:** B2C checkout and the optional buyer GSTIN (`BillingIn.gstin`). Tax invoices and credit notes still split CGST/SGST/IGST, and the GST register still has its B2B/B2C column (D1).

### Entitlements
- **`router.py`:**
  - Removed `/orgs/{id}/seats`, `/seats/assignments` and `/seats/revocations`.
  - `GET /users/{id}/entitlements` is now for platform staff only; the coordinator `org_id` branch is gone.
  - The SoD-01 `security_reviewer` refusal was removed: that role is folded into Admin (D2), and large grants still need a second Admin.
- **`service.py`:**
  - Removed the `institution_contract` precedence and the contract-membership check in `evaluate`.
  - Removed all seat, waitlist and contract code, and `on_member_removed`.
  - `grant()` no longer has the `institution_contract_id` parameter.
  - In the restriction extension, `uncredited_days` is kept in the result but is always empty.
- **`models.py`:** removed `SeatWaitlist` and `Entitlement.institution_contract_id`.
- **`cache.py`:** removed `seat_reassigned` from the cache-bump event types.

### Other files
- **`wiring.py`:** the COM-04 `orgs.member_removed` hook is gone. Only the cache-invalidation registration remains.
- **`seeds/commerce_demo.py`:** `DEMO-COLLEGE-SEAT` was removed.
- **Acceptance:** `rg -i "contract|seat|institution_|included_via_college"` finds none of these symbols in commerce, entitlements, `wiring.py` or the seed. The matches that remain elsewhere belong to other workstreams (§4).

## 2. Migrations

| Revision | Depends on | Effect |
|---|---|---|
| `entitlements_0003` | `entitlements_0002` | See the list below. |
| `commerce_0004` | `commerce_0003`, plus `entitlements_0003` and `orgs_0001` (never `orgs_0002`) | See the list below. |

**What `entitlements_0003` does:**
- Revokes every institution entitlement that is not already revoked: `revoke_reason` is `contract_terminated`, and an event `revoked` is written with reason `college_removal`. The rows are kept.
- Drops `seat_waitlist`.
- Drops `institution_contract_id`, `ux_ent_seat` and `ix_ent_contract_active`.
- Rebuilds `ck_ent_source`, and adds `ck_ent_no_institution`, so that `institution_contract` is valid only on revoked rows.
- Changes the RLS family of `entitlements` and `entitlement_events` from **U to O**.

**What `commerce_0004` does:**
1. **Archives first (D1).** It creates `commerce_b2b_archive`: FORCE RLS, platform read-only, and no writes for `td_app`. It copies into it:
   - contract invoices and their credit notes, with the order, the order lines, the contract number, the PO and `pdf_s3_key`;
   - contracts, with a snapshot of the college organization (GSTIN and billing details);
   - college coupons.

   The invoice rows themselves are **kept**. When `backups/` exists next to the code, or `TD_B2B_ARCHIVE_DIR` is set, it also writes JSON files to `backups/archived-contract-invoices/`.
2. Expires the college coupons, then drops `coupons.organization_id`. The coupons policy becomes `p_coupons_read` (anyone may read) and `p_coupons_write` (only the platform may write).
3. Retires `institution_seat` products and adds `ck_product_no_institution_seat`.
4. Drops `invoices.contract_id` and the `institution_contracts` table.
5. Changes the RLS family of `orders`, `order_items`, `payments`, `refunds` and `invoices` from **U to O**.

**Why both migrations move tables to RLS family O:** once `orgs_0003` re-homes the legacy B2B rows to the company org, family U would let every company member read the college orders, invoices and entitlements. FORCE RLS stays on everywhere.

**Downgrades** restore the schema only, and keep the archive table.

**PDFs:** they stay in the invoices bucket, at the `pdf_s3_key` recorded in the archive. `/finance/invoices/{id}/pdf` still serves or re-renders them, because the invoice rows are kept.

## 3. Results (real runs)

- **Unmodified official command:** 81 passed, 2 failed (both in WS4 learning routes). See §5.
- **Earlier runs:** the WS3 migration `ai_0002` failed with an RLS error on `ai_settings` during `alembic upgrade heads`. I ran the suites with a scratch pytest plugin that upgrades every head except that one. The plugin is not in the repo.
  - `tests/commerce` and `tests/entitlements`: **70 passed**.
  - `tests/authz`: 9 failures, all `relation "app_settings" does not exist` (caused by the skipped WS3 revision), plus one WS5 `/support/enquiries` refusal. There were no commerce or entitlement violations.
- **`ruff check`** passes on `app`, my migrations and tests. **`ruff format`** passes on my files. **`mypy app`** passes: no issues in 258 source files.
- **Dump path** (restored into `techdrona_ws2_dump`, then `alembic upgrade commerce_0004`):
  - The dev data has **0 contracts, 0 invoices, 0 institution entitlements and 0 college coupons**. Its only B2B row is the `DEMO-COLLEGE-SEAT` product, which was retired.
  - So there was nothing to export, and `backups/archived-contract-invoices/` was not created.
  - Afterwards, FORCE RLS is still on for all ten tables.
- **Data path:** I downgraded both WS2 revisions, seeded a contract, a contract invoice, a credit note, a live seat entitlement, a waitlist row and a college coupon, and upgraded twice. Results:
  - Archive rows: `contract_invoice=2`, `institution_contract=1`, `college_coupon=1`. The second upgrade was a no-op.
  - Both invoices were kept.
  - The entitlement ended `revoked/contract_terminated`, with a `college_removal` event.
  - The coupon expired and the seat product was retired.
  - The organization snapshot includes `gstin`.
  - The JSON files and `index.json` were written to a scratch `TD_B2B_ARCHIVE_DIR`.

**New or converted tests:**
- B2C buyer-GSTIN invoices: intra-state gives CGST and SGST, inter-state gives IGST. The PDF text and the GST register are checked.
- The B2B routes return 404 or 405. College coupons and seat products are rejected with 422.
- A legacy offline-PO invoice still renders, is not auto-expired, and is hidden from a company member by RLS.
- The archive table is locked: FORCE RLS, and `td_app` cannot insert.
- Institution entitlements are history only, and family O hides one member's entitlements from another.
- The coupon policies: anyone may read, only the platform may write.
- The outbox consumers: `orgs.member_removed` has no handler.
- Removed tests: the seat, contract, COM-04 and COM-20 tests.
- `finance_admin` and `security_reviewer` principals became `super_admin`.

## 4. Requests to other workstreams

- **WS1:**
  - Add `commerce_0004` and `entitlements_0003` to `orgs_0003`'s `depends_on`. The organization snapshot reads the college columns, so it must run before they are dropped.
  - The DEPRECATED college columns in `orgs/models.py` are no longer read by WS2. WS1 can drop the mapping, and fix the comment at `orgs/models.py:30`.
  - In `core/errors.py:117-118`, `seat_pool_exhausted` and `reassignment_allowance_exhausted` are now unused. Delete them, together with `tests/core/test_errors_request_id.py:87`.
  - In `rbac/catalogue.py`, `contract.*` and `seat.*` appear only in `REMOVED_PERMISSIONS`. That is expected.
- **WS3:** `ai_0002` failed during my earlier runs (an RLS violation on `ai_settings`). It now migrates (§5).

## 5. Final run of the official command (unmodified)

```
TD_TEST_DB_NAME=techdrona_ws2 TD_TEST_RESET_DB=1 .venv/Scripts/python -m pytest tests/commerce tests/entitlements tests/authz -q
```

Result: **81 passed, 2 failed** in 3 min 8 s. Both failures are `tests/authz/test_authz_matrix.py[other_trainer]` and `[other_evaluator]`. The cause is in WS4's code:

- The cross-tenant probes `GET /enrolments` and `GET /progress` return 403 `permission_denied` where the test expects 404.
- These are learning routes, not WS2's. **WS4** should fix them.
- **WS4:** the docstring at `notifications/consumers.py:60` mentions institution (contract) invoices.
- **WS5:** `audit/router.py:79` lists the target type `institution_contract`, which is now historic only. `analytics/reports.py:523` has `seat_utilisation` in the org report.
- **WS6:**
  - In OpenAPI and the web app, these routes are gone: `/finance/contracts*`, `/orgs/{id}/contract`, `/orgs/{id}/invoices*` and `/orgs/{id}/seats*`.
  - `invoice_json.contract_id`, `coupon_json.organization_id` and `CouponIn.organization_id` are gone.
  - The `institution_seat` product kind is gone.
  - The quote warning `included_via_college` is gone.
  - `GET /users/{id}/entitlements` no longer takes an `org_id` parameter.
- **Coordinator:**
  - After applying `commerce_0004` to the dev database from the host, check `backups/archived-contract-invoices/`. The dump has no contract invoices, so expect nothing there.
  - Inside a container, the archive exists only in the table.
