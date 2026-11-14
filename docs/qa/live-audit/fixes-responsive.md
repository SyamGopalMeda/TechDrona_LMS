# Responsive and UI-polish fixes (from the live audit)

- **Date:** 2026-11-14
- **Sources:** `responsive.md` F1, F3–F8; `staff-portals.md` F6 (Find a page) and F8 (touch targets); `admin.md` item 15 (Ctrl K hint).
- **Scope:** visual and accessibility polish only. No behaviour, API or route changes. Not deployed.
- **Code:** `apps/lms-spa/src`. Every changed file is mirrored byte-for-byte under `apps/lms-spa/spa-overrides/` (same path relative to `src/`), so `npm run sync` keeps it.

## Changes

| Finding | Fix | Files |
|---|---|---|
| F1: page title larger on phones (30 px) than desktop (28 px) | The shared page header `<h1>` is now `text-[1.5rem] leading-8 sm:text-[1.75rem] sm:leading-9`: 24 px on phones, 28 px from `sm`. | `components/ui/Display.tsx` (`PageHeader`) |
| F3: standalone links under 24 px tall | New shared class `standaloneLinkClass` (`inline-flex min-h-6 items-center`), exported from `@/components/ui`. Applied to: legal "Related" links (`ContentDoc` `linkCls`), "Forgot password?" on /login, both standalone "Back to log in" links on /forgot-password, "Start practising" on /app/progress. The "How we measure time" `<summary>` gets `py-0.5` (20 → 24 px). Inline links inside sentences are left alone (WCAG 2.5.8 inline exception), including the "Back to log in" inside the success notice. | `components/ui/touch.ts` (new), `components/ui/index.ts`, `features/public/components/ContentDoc.tsx`, `features/auth/components/LoginForm.tsx`, `features/auth/components/PasswordRecovery.tsx`, `features/progress/components/ProgressDashboard.tsx` |
| F4 / staff F8: 20 px checkboxes, 16 px radios | On coarse pointers (`@media (pointer: coarse)`) the shared `Checkbox` input and the `Segmented` option-card radio become 24×24; mouse/desktop sizes are unchanged (20 px and 16 px). The checkbox class is also exported as `choiceInputClass`. This covers /login, /signup, /admin/ai, /security/restrictions, studio lesson/test/taxonomy checkboxes and the `/trainer/engage/new` "Instant / Scheduled" and "Members only" radios (all `Segmented`). | `components/ui/Checkbox.tsx`, `components/ui/Controls.tsx`, `components/ui/touch.ts` |
| F5: no search in the student "More" sheet | `searchable` passed to the sheet's `PortalNav`. | `components/shell/MobileTabBar.tsx` |
| F6 / admin 15: 10 px "Ctrl K" hint | Raised to 11 px (`text-[11px] leading-4`). The collapsed-section count pill was also 10 px and is now 11 px. | `components/shell/PortalNav.tsx` |
| F7: staff Menu panel sometimes stays open after navigating | The panel also closes on any click/tap on a link inside it (`onClickCapture` checking `closest("a[href]")`), so it no longer waits for a late pathname update from a lazy route. Clicks on the search box or section toggles keep it open. The pathname, Escape and scrim closes are unchanged. | `components/shell/PortalFrame.tsx` (`StaffMenu`) |
| Staff F6: "Find a page" quality | New exported `searchNav(items, query)` / `navMatchRank()`. Ranking (best first, nav order breaks ties): 0 label starts with the query; 1 every query word starts, or shares a stem with, a label word; 2 label contains the query; 3 optional `keywords` match; 4 section name matches. A simple suffix stemmer (`stem()`: -ings, -ing, -ers, -er, -es, -ed, -s, -e, keeping at least 3 letters) makes "grade"/"grades" find "Grading". "tests" now lists "Tests" before items that are only in a "… & tests" section. Plain substring matches still work. Enter still opens the first (now the best) result. | `components/shell/PortalNav.tsx` |

## F8: tablet portrait (810 px) uses the phone layout. Left as a design decision

Not changed. The `lg` (1024 px) breakpoint is shared by the sidebar, the staff Menu bar, the student tab bar, the `pb-24` tab-bar clearance, the main padding and the `scroll-padding-bottom` rule in `globals.css`. Moving the rail to `md` means changing all of these together, plus `PortalShell.tsx`, which another workstream owns. That is more than a polish change. The audit found the 810 px layout works: two-column grids, nothing hidden and no overflow. Recommendation if it is wanted later: show the existing icon-only rail (`--td-layout-sidebar-collapsed`) from `md` and hide the Menu bar and tab bar from `md`, in one change with a visual check on an iPad. The stranded last stat card (e.g. seven tiles on /finance/admissions) is a separate `StatGrid` column choice and is also left as is.

## Tests

All run with `npx vitest run <files> --pool=threads --no-file-parallelism` in `apps/lms-spa`; all pass.

| File | Result | New tests |
|---|---|---|
| `src/components/shell/nav-shell.test.tsx` | 19/19 | stemmer; "grade" finds Grading; label-before-section ranking ("tests", "test results", "pract"); substring fallback and no-match; ranked results in the box; Ctrl K hint 11 px; Find a page in the More sheet (F5); Menu closes on link tap before the pathname changes (F7); Menu stays open on a search-box click |
| `src/components/ui/kit.test.tsx` | 22/22 | phone h1 size (F1); 24 px coarse-pointer checkbox and radio (F4); `standaloneLinkClass` (F3) |
| `src/components/ui/ui.test.tsx` | 22/22 | (regression) |
| `src/features/auth/components/auth.test.tsx` | 12/12 | (regression) |
| `src/features/public/components/public.test.tsx`, `src/features/public/public-pages.test.ts` | 23/23, 37/37 | (regression) |
| `src/features/engage/components/engage.test.tsx`, `src/features/progress/progress.test.tsx` | 23 total, all pass | (regression) |

No build, type-check, emulator or browser run (RAM limit). Confirm F7 by hand on an iPad after the next deploy, and rerun `qa/live-e2e/tests/audit-responsive.spec.ts`.

## Still open (outside this change's file ownership)

- **F3, remaining standalone links:** `features/unblock/components/AccountStatus.tsx:119` ("Check a review request", "Contact support", "Privacy requests"), /app/courses "My registrations" (`features/site-catalog`), /mentor "Open queue", /college-portal "Browse courses" / "Help centre", the same `linkCls` pattern in `HelpCentre.tsx:5` and `FreeResources.tsx:14`, and the /admin "Go to Batches" and table name links. Each needs `standaloneLinkClass` added to its class list.
- **F2:** course-card title links and the 10.9 px kicker (`features/site-catalog`).
- **Raw checkbox/radio inputs that bypass the shared components** (still 20 px or 16 px on touch): `features/studio/components/Questions.tsx:419` (the `/studio/questions/new` checkboxes in staff F8), `features/engage/components/ActivityBuilder.tsx:149`, `features/engage/components/LiveRun.tsx:128`, `features/question-bank/components/QuestionEditorDialog.tsx:403` and `:484`, `features/question-bank/QuestionBankPicker.tsx:329`. Replace their `h-5 w-5` (or `h-4 w-4`) with `choiceInputClass` from `@/components/ui`.
- **Staff F6, the rest:** add a `keywords?: string[]` field to `NavItem` (`lib/nav/portals.ts`) with synonyms such as mark/grade, profile/settings. `navMatchRank` already reads `keywords` when it is present. Also add the account links (Settings, Account status) to the search index; they are in the account menu, not the nav.
