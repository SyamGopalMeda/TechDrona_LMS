# Tech Drona LMS: Sitemap (v1.0)

Owner: UX/UI Designer. Status: **Planned**, with implemented routes recorded in §13 (Stage 10 sync, 2026-11-03). Routes and screen IDs are exactly those of `docs/product-requirements.md` §6 (PRD v0.3). Entries marked **(proposed)** are UX additions not yet in the PRD; they are listed in §12 for the Product Analyst to accept or reject. Portal access follows `docs/role-permission-matrix.md` §9.

> **Single-company mode (2026-11-06, [ADR-0015](architecture-decisions/ADR-0015-single-company.md)).** Tech Drona is the only organization. The college coordinator portal, invitations, the "For colleges" page, organization admin pages and institution contracts are removed. Roles are Admin (`super_admin`), Trainer, Evaluator, Content manager and Student; the support desk, finance and security consoles keep their URLs but belong to the Admin portal and need `super_admin`. Batches are managed by Admin at `/admin/batches`. Corporate and bulk enquiries go to the website contact page (the LMS `/enquiries` URL redirects there).

> **Removed 2026-11-14 ([feature-removal-plan.md](cleanup/feature-removal-plan.md)).** Mentoring (`/mentor/**`, `/app/mentoring`; the Résumé builder `/app/resume` stays), company paths (`/app/companies/**`, `/studio/companies`), corporate enquiries (`/enquiries`, `/desk/enquiries/**`), the public pages Hosting redirects to the website (`/courses/**`, `/pricing`, `/placement/**`, `/companies/**`, `/free-resources`, `/status`), `/app/diagnostic`, `/admin/question-review`, `/admin/notifications`, `/app/bookmarks`, `/app/analytics` and `/security/policies`. `/` now only redirects (`/modules` or `/login`). The SPA has 179 pages.

Legend: `[ID]` screen ID · `(modal)` / `(drawer)` = not a route · `→` redirect/flow · 🔒 needs sign-in · ⬆ step-up MFA on entry or action · ⇄ second-person approval involved.

---

## 1. Global structure

```
techdrona.in
├── Public site (/)                       anyone
├── Account status (/account/restricted)  L4 status_only session
├── Student portal (/app)                 student                     🔒
│   ├── Course player (/app/learn/...)    focus shell
│   ├── Practice (/app/practice/...)
│   ├── Timed tests (/app/tests, /app/attempts/...)   focus shell
│   └── Coding (/app/coding/...)          focus shell (≥ 768 px)
├── Trainer (/trainer)                    trainer @ batch/course      🔒
├── Evaluator (/evaluator)                evaluator @ batch/platform  🔒
├── Content studio (/studio)              content_manager             🔒
└── Admin (/admin)                        super_admin                 🔒 ⬆
    ├── Support desk (/desk)              super_admin (part of Admin portal)
    ├── Finance (/finance)                super_admin (part of Admin portal)  ⬆
    └── Security (/security)              super_admin (part of Admin portal)  ⬆
```

Users with several grants switch portals from the avatar menu (FR-RBAC-002); only granted portals are listed. Default landing per role: role matrix §9.

---

## 2. Public site

```
/                                   [PUB-001] Redirect only → /modules (signed in) or /login
├── /signup                         [PUB-011] Sign up (DOB age gate, consents, OTP)
│   └── → under 18 → guardian step (in-flow) → /guardian-consent/[token] (guardian side)
├── /login                          [PUB-012] Sign in (password / passkey / Google; MFA; new-device OTP;
│                                              device chooser; session-cap chooser; throttled; → PUB-021)
├── /forgot-password                [PUB-013] Recovery request
├── /reset-password/[token]         [PUB-013] Set new password
├── /verify/email/[token]           [PUB-014] Email verification
├── /verify/mobile                  [PUB-014] Mobile OTP verification
├── /guardian-consent/[token]       [PUB-015] Guardian consent (approve / decline)
├── /verify/[certificate_id]        [PUB-017] Certificate verification
├── /legal/terms                    [PUB-018]
├── /legal/privacy                  [PUB-018]
├── /legal/refund-policy            [PUB-018]
├── /legal/device-policy            [PUB-018] (published numbers: 3 devices · 2 sessions · 1 stream · 2 replacements/30 d)
├── /help                           [PUB-019] Help centre, contact, grievance officer
│   └── /help/[article]             [PUB-019]
│       └── /help/how-we-measure-time  (proposed article; analytics §3.12 disclosure)
└── /account/restricted             [PUB-021] Status-only page (L4): case, appeal form, status, billing view/cancel, privacy
```

Footer (every public page): Help · Terms · Privacy · Refund policy · Device policy · Grievance officer · Certificate verification.

---

## 3. Student portal (`/app`)

Sidebar (desktop) / bottom tabs (mobile: Home · Learn · Practice · Tests · More).

```
/app                                [STU-001] Dashboard
├── /app/onboarding                 [STU-002] Goal picker
├── /app/path                       [STU-006] Learning path & recommendations
│
├── Learn
│   ├── /app/learning               [STU-004] My courses
│   ├── /app/courses/[slug]         [STU-005] Course overview
│   ├── /app/learn/[course_slug]/[lesson_id]          [PLY-001] Video lesson  /  [PLY-002] Reading  /  [PLY-003] In-lesson quiz
│   │   ├── ?preview=1              [PLY-004] Author/trainer preview
│   │   └── (modal)                 [PLY-005] Playback conflict
│   ├── /app/assignments            [STU-007] Assignments
│   │   └── /app/assignments/[id]   [STU-008] Assignment detail & submission
│   └── /app/certificates           [STU-012] Certificates
│
├── Practice
│   ├── /app/practice               [PRC-001] Practice hub
│   ├── /app/practice/[subject]     [PRC-002] Topics & mastery
│   ├── /app/practice/sessions/[session_id]           [PRC-003] Practice session
│   └── /app/practice/review        [PRC-004] Review incorrect & bookmarked
│
├── Tests
│   ├── /app/tests                  [STU-009] Tests list
│   ├── /app/tests/[test_id]        [TST-001] Instructions & system check
│   ├── /app/attempts/[attempt_id]  [TST-002] Attempt runner (focus shell)
│   │   ├── (modal)                 [TST-003] Section / final submit
│   │   └── (state)                 Open on another device (FR-SES-011)
│   ├── /app/attempts/[attempt_id]/resume     [TST-004] Resume after crash/disconnect
│   ├── /app/attempts/[attempt_id]/submitted  [TST-005] Submitted
│   └── /app/tests/[test_id]/results/[attempt_id]   [STU-010] Results & review
│
├── Coding
│   ├── /app/coding                 [COD-001] Problem list
│   ├── /app/coding/[slug]          [COD-002] Workspace
│   ├── /app/coding/[slug]/submissions        [COD-003] Submission history
│   └── (embedded in TST-002)       [COD-004] Coding question in a test
│
├── Career
│   ├── /app/resume                 [STU-014] Resume builder
│   └── /app/interview-prep         [STU-015] Interview prep
│
├── Purchases
│   ├── /app/checkout/[order_id]    [STU-016] Checkout
│   ├── /app/orders/[order_id]      [STU-017] Order status
│   ├── /app/billing                [STU-018] Subscriptions, orders, invoices, refunds
│   └── /app/access                 [STU-019] What I have access to
│
├── /app/notifications              [STU-024] Notifications & preferences
├── Support
│   ├── /app/support                [STU-025] Tickets
│   ├── /app/support/new            [STU-025] New ticket
│   └── /app/support/[ticket_id]    [STU-025] Ticket thread
├── /app/account-status             [STU-026] Account status, restriction, unblock request & status
└── Settings
    ├── /app/settings/profile       [STU-020] Profile
    ├── /app/settings/security      [STU-021] Password, MFA, passkeys, recovery codes  ⬆ (contact/MFA changes)
    ├── /app/settings/devices       [STU-022] Devices & sessions (account-integrity centre)
    └── /app/settings/privacy       [STU-023] Consents, export, deletion
```

**Route behaviour under restrictions** (FR-SEC-002, risk engine §6): L1 → all routes, banner. L2 → player/test start on unverified devices show the "Confirm it's you" interstitial. L3 (`restricted` scope) → allowed: `/app`, `/app/settings/*`, `/app/billing`, `/app/access`, `/app/orders/*`, `/app/support*`, `/app/account-status`, `/app/notifications`, `/app/certificates` (view); all player/practice/test-start/coding-submit routes redirect to `/app/account-status`. L4 (`status_only`) → only `/account/restricted` and its sub-actions.

---

## 4. Trainer portal (`/trainer`)

```
/trainer                            [TRN-001] Dashboard
├── /trainer/batches/[batch_id]     [TRN-002] Batch roster & progress
├── /trainer/courses                [TRN-003] Courses
│   └── /trainer/courses/[course_id]/edit     [TRN-004] Course builder
├── /trainer/tests                  [TRN-005] Tests
│   ├── /trainer/tests/[test_id]/edit         [TRN-006] Test builder
│   ├── /trainer/tests/[test_id]/overrides    [TRN-007] Overrides (extra time/attempt)
│   └── /trainer/tests/[test_id]/report       [TRN-011] Test analytics
├── /trainer/grading                [TRN-008] Grading queue
│   └── /trainer/grading/[submission_id]      [TRN-009] Grade submission  ⬆ (change after release)
├── /trainer/integrity              [TRN-010] Integrity review
├── /trainer/assignments            [TRN-012] Assignments
└── Preview → /app/learn/[course_slug]/[lesson_id]?preview=1   [PLY-004]
```

## 5. Evaluator portal (`/evaluator`)

Reuses the trainer grading screens with authoring hidden. Evaluators grade and publish results for their batches; they never grade their own attempt or submission.

```
/evaluator                          Grading queue (TRN-008 screen): assignments, release grades
├── /evaluator/grading/[submission_id]          Grade submission (TRN-009)
├── /evaluator/grading/assignments/[id]         Structured assignment evaluation + publish
├── /evaluator/tests                            Tests to evaluate (no create / edit / assign / overrides)
│   ├── /evaluator/tests/[test_id]/evaluation   Exam evaluation + publish results
│   └── /evaluator/tests/[test_id]/report       Test report (TRN-011)
└── /evaluator/integrity                        Integrity flags review (TRN-010)
```

## 6. Placement mentor section (removed 2026-11-14)

Mentoring was removed; see the note at the top. The Résumé builder stays at `/app/resume`.

## 7. Content studio (`/studio`)

```
/studio                             [CMS-001] Content dashboard
├── /studio/courses                 [CMS-002] Courses
│   └── /studio/courses/[course_id] [CMS-003] Course builder & versions
├── /studio/questions               [CMS-004] Question bank
│   ├── /studio/questions/[question_id]       [CMS-005] Question editor
│   └── /studio/questions/import    [CMS-006] Bulk import
├── /studio/review                  [CMS-007] Review queue
├── /studio/taxonomy                [CMS-008] Taxonomy
├── /studio/coding/[problem_id]     [CMS-010] Coding problem editor
├── /studio/tests                   [CMS-011] Template mocks
├── /studio/media                   [CMS-012] Media
└── /studio/reports/errors          [CMS-013] Reported errors
```

## 8. Support desk (`/desk`, Admin portal)

```
/desk                               [SUP-001] Ticket queue
├── /desk/tickets/[ticket_id]       [SUP-002] Ticket
├── /desk/users/[user_id]           [SUP-003] User lookup (M0 + M2)
│   └── (drawer)                    [SUP-004] Device reset / session revoke  ⬆
└── /desk/unblock-requests          [SUP-005] Unblock triage (L1/L2 lift; forward L3/L4)
```

## 9. Finance console (`/finance`, Admin portal)

```
/finance                            [FIN-001] Revenue dashboard
├── /finance/products               [FIN-002] Products, plans, prices  ⬆ ⇄ (price decrease > 20%)
├── /finance/coupons                [FIN-003] Coupons  ⬆ ⇄ (> 50% or > 1,000 redemptions)
├── /finance/orders                 [FIN-004] Orders & payments
├── /finance/refunds                [FIN-005] Refund queue  ⬆ ⇄ (goodwill / > ₹25,000)
├── /finance/subscriptions          [FIN-006] Subscriptions
├── /finance/invoices               [FIN-007] Invoices & credit notes, GST exports
└── /finance/reconciliation         [FIN-009] Reconciliation
```

## 10. Security console (`/security`, Admin portal)

```
/security                           [SEC-001] Account-security dashboard (H1–H12 + ENG tiles)
├── /security/cases                 [SEC-002] Case queue (H1 suspicious-activity queue, full)
│   └── /security/cases/[case_id]   [SEC-003] Case detail: header, explanation, timeline (H12), concurrency
│                                              Gantt (H3), device–account graph (H2), submission, notes,
│                                              decision panel  ⬆ ⇄ (second approval)
├── /security/unblock-requests      [SEC-004] Unblock requests / appeals (H6)
├── /security/restrictions          [SEC-005] Active restrictions (H5), manual apply/lift  ⬆ ⇄
├── /security/rules                 [SEC-006] Risk rules, versions, simulation  ⬆ ⇄ (publish by super_admin)
├── /security/users/[user_id]/timeline        [SEC-007] User security timeline (reason code prompt)
└── /security/reports/[report_key]  (proposed) Full-page H1–H12/ENG reports by key
        keys: top-suspicious-accounts · account-device-associations · concurrent-login-events ·
              repeated-network-device-associations · blocked-accounts · pending-unblock-requests ·
              average-review-time · false-positive-rate · repeat-incidents · active-session-counts ·
              learning-activity · device-login-history · engine-health
        exports ⬆ ⇄ (per-user rows: second admin)
```

## 11. Admin console (`/admin`)

```
/admin                              [ADM-001] Platform dashboard
├── /admin/batches                  Batches (list, create)
│   └── /admin/batches/[batch_id]   Batch detail: members add/remove, assign trainer/evaluator
├── /admin/ai                       Apps (authorized apps; AI settings only when a provider is configured)
├── /admin/users                    [ADM-004] User search (no evidence)
├── /admin/roles                    [ADM-005] Role grants  ⬆ ⇄ (privileged roles)
├── /admin/policies                 [ADM-006] Policy settings  ⬆ ⇄
├── /admin/feature-flags            [ADM-007] Feature flags
├── /admin/audit                    [ADM-008] Audit log + chain verification
├── /admin/privacy-requests         [ADM-009] Privacy requests (DPDP timers)
├── /admin/approvals                [ADM-010] Dual-control approvals queue
├── /admin/break-glass              [ADM-012] Break-glass  ⬆ (passkey only)
└── Sections: Support desk (/desk), Finance (/finance), Security (/security)
```

---

## 12. Proposed additions (for Product Analyst review)

| # | Proposal | Reason |
|---|---|---|
| UX-SM-01 | `/help/how-we-measure-time` article (or `/legal/measurement`) | Analytics §3.12 requires a student-facing "How we measure time" page; no route exists in PRD §6. |
| UX-SM-02 | `/security/reports/[report_key]` full-page report views | SEC-001 tiles need a drill-down per Section H report; keys from `api-specification.md` SEC-31. |
| UX-SM-03 | `/app/settings/appearance` folded into STU-020 (theme, reduced motion, timer display preference) | Theme choice + accommodation display settings need a home; can be a section of STU-020 instead of a route. |
| UX-SM-04 | Guardian step inside `/signup` rendered as `/signup/guardian` | Makes the under-18 step bookmarkable/resumable; PRD lists it only as a PUB-011 state. |


---

## 13. Implementation status (Stage 10 sync, 2026-11-03)

Source: `apps/web/src/app/**/page.tsx` (156 page routes; `(public)` is a route group, not a URL segment). Every route listed in §2–§11 exists as a page in `apps/web`; the per-route data status (real API vs. assumed contract) is in `docs/implementation-status.md`.

**Canonical route prefixes (confirmed in code).** The PRD prefixes are canonical: Security console `/security/*`, Support desk `/desk/*`, certificate verification `/verify/[certificate_id]`. `apps/web/next.config.ts` keeps temporary (302) aliases for links written against earlier drafts:

| Alias | Redirects to |
|---|---|
| `/admin/security`, `/admin/security/:path*` | `/security`, `/security/:path*` |
| `/verify/certificate/:id` | `/verify/:id` |

`/verify/email/[token]` and `/verify/mobile` are static segments and take precedence over `/verify/[certificate_id]`, so certificate ids can never be `email` or `mobile`.

**Routes implemented that were not listed above** (now part of the sitemap):

| Route | Portal | Notes |
|---|---|---|
| `/login/mfa`, `/login/session-choice`, `/login/verify-device` | Public | Login continuation steps (PUB-012 states promoted to routes; API tag `login_continuation`). |
| `/unblock-request` | Public route, signed-in account holder (restricted or status-only scope) | Unblock request form and status lookup by `APL-` reference (UNB-01, UNB-05/06, UNB-19/20). The reference is never an authenticator. |
| `/app/courses` | Student | In-portal catalog. |
| `/app/checkout/new` | Student | Creates the order, then redirects to `/app/checkout/[order_id]`. |
| `/app/progress` | Student | Progress analytics (recharts; lazy-load pending, backlog D). |
| `/app/settings/security/not-me/[event_ref]` | Student | "This wasn't me" link target from security notices. |
| `/trainer/tests/[test_id]/attempts` | Trainer | Attempt list per test. |
| `/studio/coding`, `/studio/tests/[test_id]` | Studio | Coding problem list and test editor. |
| `/security/approvals`, `/security/reports` | Security | Approvals queue, report index (UX-SM-02 adopted with `/security/reports/[report_key]`). |
| `/admin/users/[user_id]` | Admin | User detail. |

**Proposed routes not implemented:** `/help/how-we-measure-time` (UX-SM-01), `/app/settings/appearance` (UX-SM-03, folded into STU-020), `/signup/guardian` (UX-SM-04; guardian step remains a state inside `/signup`).

**Pages whose backend does not exist yet:** `/app/support*` and `/desk/tickets/*` (support module not built), `/app/resume`. They render against assumed contracts; see `docs/implementation-status.md`.

### Changelog

- 2026-11-14 (feature removal, [plan](cleanup/feature-removal-plan.md)): removed the 28 pages listed in the note at the top; `/` became a redirect; "AI & apps" renamed "Apps".
- 2026-11-06 (single-company conversion, WS6): removed `/college/**`, `/app/college`, `/invite/[token]`, `/colleges`, `/admin/organizations/**`, `/finance/contracts`, `/college/networks`; added `/enquiries`, `/admin/batches`, `/admin/batches/[batch_id]`, `/admin/ai`, the Evaluator portal; mentor/desk/finance/security grouped under the Admin portal.
- 2026-11-03 (Stage 10 integration sync): §13 added; route prefixes `/security`, `/desk`, `/verify/[certificate_id]` confirmed canonical with aliases; implemented-only routes recorded; UX-SM-02 marked adopted.
