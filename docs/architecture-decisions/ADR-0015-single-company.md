# ADR-0015: Single-company mode — one invisible company organization

* **Status:** Accepted (owner decision, 2026-11-06) — implementation **In progress** (workstreams WS1–WS6 in [`docs/single-company/REMOVAL-PLAN.md`](../single-company/REMOVAL-PLAN.md))
* **Supersedes in part:** ADR-0003 (tenancy model: the multi-college tenancy it describes now has exactly one tenant), the B2B/college sections of `blueprint-brief.md`, `product-requirements.md` and `role-permission-matrix.md`
* **Related:** ADR-0003, ADR-0006, ADR-0009, `docs/single-company/REMOVAL-PLAN.md` §2 and §8

## Context

Tech Drona was designed to sell both directly to learners (D2C) and to colleges through institution contracts (B2B): a college portal (`/college/**`), college coordinators, contracts and seats, B2B invoices, invitations and roster import, per-organization settings, trusted networks and lab devices. The owner decided that the LMS serves **Tech Drona only**: learners are public students who pay through Razorpay, and Tech Drona runs its own batches. Every college and multi-organization feature must be **removed completely, not hidden**.

About 110 `organization_id` columns, the RLS families `T`, `TN` and `U`, `app.org_ids()`, `Principal.org_ids` and every scope check depend on organizations.

## Decision

**Option B: keep one invisible company organization.**

* One `organizations` row with `org_type='internal'` and a fixed id `COMPANY_ORG_ID` (`api/core/company.py`), name "Tech Drona", slug `techdrona`. The database enforces a singleton (`CHECK (org_type='internal')` plus a unique index on `(true)`). No API can create, edit or suspend organizations; `/orgs/**` is deleted.
* Users never see, pick or manage the organization. NOT NULL `organization_id` columns hold `COMPANY_ORG_ID`; nullable ones keep `NULL` = platform content.
* Grant scopes are `platform`, `batch` and `course`; `organization` is dropped as a grant scope.
* **Batches stay** as the company's cohorts, managed by Admin at `/admin/batches` (`GET/POST /batches`, members added one by one from existing accounts).
* Per-org settings become platform settings: `ai_settings` singleton (non-NULL caps; AI tutor default 20 messages per learner per activity), `app_settings`, policy precedence user > plan > platform, no feature-flag org allowlist.
* RLS hardening: `app.user_visible_in_orgs` only lets staff see members and members see staff, so students cannot read each other's PII at the database level.
* **Roles (owner decision D2):** Admin (`super_admin`, displayed "Admin"), Trainer, **Evaluator** (new; grades and publishes results, no authoring, never grades own work), Content manager, Student. `college_coordinator`, `finance_admin`, `support_agent`, `security_reviewer` and `placement_mentor` are removed; their duties and permissions move to Admin. Dual-control rules become "two different admins" (maker ≠ checker).
* **Removed:** college portal, invitations and roster import, contracts, seats and contract/offline-PO invoicing, org reports, lab/shared devices, trusted networks, the public "For colleges" page.
* **Kept:** optional buyer GSTIN on B2C tax invoices; historic contract invoices are exported to `backups/archived-contract-invoices/` and the invoice rows are kept as legal records; optional learner profile field "Institution (optional)".
* **Added:** public corporate enquiry form `/enquiries` (`POST /api/v1/public/enquiries`, rate-limited, stored server-side and shown to Admin in the support queue); learning-path embeds from `www.youtube-nocookie.com`, `player.vimeo.com`, `docs.google.com` and `drive.google.com` via CSP `frame-src` and a strict iframe `sandbox`, with a server-side allow-list.

## Alternatives considered

| Option | Why not |
|---|---|
| A. Drop organizations entirely | Rewrite of ~110 columns, every RLS policy, `Principal` and scope checks: weeks of security-critical change for no visible benefit |
| B′. Platform only (`organization_id` NULL everywhere) | `TN` write checks require `is_platform()`, so batch trainers could no longer write their tests, banks or paths |
| Hide the college features behind a flag | Rejected by the owner: features must be removed, not hidden |

## Consequences

* (+) The tested RLS model stays; risk is concentrated in data migration and permission remapping.
* (+) Smaller product surface, fewer roles, no B2B billing.
* (−) All batch students share one org, which raises the severity of intra-org findings (SEC-01, SEC-02) and requires the RLS hardening above.
* (−) Dual control needs at least two distinct Admins.
* (−) Docs written before 2026-11-06 still describe colleges in places; each carries a single-company note pointing here.
