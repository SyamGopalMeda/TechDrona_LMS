# Accessibility and responsive audit (audit phase)

> **Superseded (2026-11-14):** this audits the retired Next.js app; the LMS now runs on Firebase — see `docs/firebase-migration-plan.md` and `docs/firebase/`. The scripts moved to `docs/archive/redesign-next-app/a11y/`; the raw `results/*.json` and the `docs/redesign/shots/` screenshots cited below were deleted in cleanup D4 (recover them from git commit `24134de` if needed).

Agent: a11y-responsive · date 2026-11-07 · stack: live dev http://localhost:13000, **light theme only**.
I changed no application code. Scripts are in `docs/archive/redesign-next-app/a11y/` (`audit.cjs`, `dialogs.cjs`, `summarize.cjs`), raw results are in `docs/archive/redesign-next-app/a11y/results/*.json`, and screenshots are in `docs/redesign/shots/a11y/<page>-<mobile|tablet|desktop>.png` (viewport-only, 91 files, about 3.9 MB).

## Method (labelled per BRIEF)

- **automated-tested**: Playwright chromium visited 28 unique URLs (29 page keys) at 390×844, 820×1180 and 1440×900, which is 87 page-viewport runs. Each run did the following:
  - **axe-core** (`@axe-core/playwright`, already in `apps/web/node_modules`) with the tags wcag2a/aa, 2.1a/aa, 2.2aa and best-practice. Colour contrast is covered by axe's `color-contrast` rule.
  - **Custom DOM checks**: horizontal overflow, landmarks, heading order, targets under 24 px and under 44 px, fixed or sticky elements, clipped text, images without alt, unnamed fields, skip link and `lang`.
  - **Tab walk** (30 stops): visible focus ring (outline or box-shadow), off-screen focus, focus covered by another element (`elementFromPoint`), and a trap heuristic.
  - **Mobile only**: open, Tab, Esc and focus-return checks on the navigation toggle.
  - **Desktop, forms only**: submit the form empty, then check `aria-invalid`, `aria-describedby`, live regions and where focus lands.
- **automated-tested (dialogs.cjs)**: I opened four `Dialog`s ("New bank" on desktop and mobile, "New test", "New assignment") and checked focus on open, Tab, Esc and focus return. I never submitted them.
- **code-reviewed**: I traced causes into source (CodeGraph and file reads). File and line references are given below.
- Accounts: `ravi.student`, admin, trainer, evaluator, content. I did not use `student@`, because device-cap replacement on that shared fixture failed (the radio labels were all "last used now" from parallel agents).
- Side effect (dev DB): the profile form check pressed **Save changes** on `/app/settings/profile` for `ravi.student` without changing any values. The page showed "Profile saved." and no data changed.
- **not-verifiable / not covered**:
  - Dark theme and forced-colours mode.
  - The course player, the timed-test runner and the coding workspace. `ravi.student` has no enrolment, so the `/app/learn/...` link could not be resolved. `e2e/a11y.integration.spec.ts` already covers these screens.
  - Screen-reader output. Announcements were inferred from the DOM.
  - The finance, security and desk portals.

## Headline

- **The base is solid.**
  - axe reported **0 colour-contrast violations** and only **4 distinct axe rules across 87 runs**.
  - Every page has `lang="en-IN"`, a unique `<title>`, one `<h1>`, a `main#main` landmark and a working "Skip to content" link.
  - No page overflows horizontally at 390 px.
  - Every Tab stop showed a visible focus ring, and no keyboard trap was found.
  - The native `<dialog>` gives a real modal with Esc support.
- **The real problems are structural and responsive.** Most of them live in a handful of shared components. Fixing those once fixes most pages.

## Shared-component fixes (fix these first: they cover most findings)

Design-system agent: items S1–S6 are in `src/components/ui` or `src/components/shell`. Please fold them into the restyle.

| # | Sev | WCAG | Component / file | Problem (evidence) | Fix |
|---|---|---|---|---|---|
| S1 | **High** | 1.4.10 Reflow, 1.3.2 | `components/ui/Table.tsx` (used by every staff list) | At 390 px the table squeezes the first column to one word per line, and the actions column (Assign / Attempts / Evaluation / Overrides / Report) sits off-screen inside the horizontal scroller. Nothing on screen shows that the table scrolls. Evidence: `trn-tests-mobile.png`, `std-questions-mobile.png`, `adm-users-mobile.png`. The primary row actions cannot be seen on phones. | Below `sm`, render each row as a stacked card (label: value pairs, actions as full-width buttons at the bottom). Alternatively, give the first column `min-w-[12rem]` and add edge-fade or scroll-shadow affordances. Keep the focusable `role=region` wrapper. |
| S2 | **High** | 2.4.11 Focus Not Obscured (AA, 2.2) | `components/shell/MobileTabBar.tsx` and `PortalShell.tsx` sticky header; global CSS | When an element receives focus, the browser scrolls it to the viewport edge, and it ends up **under the fixed 56 px bottom tab bar**. The Tab walk confirmed this for "Save changes" (`/app/settings/profile`), "Manage" (`/app`) and the topic links (`/app/practice`). The sticky `header.z-topbar` similarly covered the focused "Menu" summary on `/studio/questions` (tablet). `main pb-24` only fixes the end of the page. | `html { scroll-padding-top: var(--topbar-h); }`, plus, on the student shell below `lg`, `scroll-padding-bottom: calc(3.5rem + env(safe-area-inset-bottom) + 8px)`. |
| S3 | **High** | 2.4.3 Focus Order, 4.1.2 | `components/shell/MobileTabBar.tsx:69-72` | The "More" sheet is rendered **before** the `<nav>` in the DOM. After pressing "More" (`aria-expanded=true`), Tab moves forward **out of the page**, and the sheet links can only be reached with Shift+Tab. Focus does not move into the sheet, the sheet has no name or role, and Esc does not return focus to "More". The heuristic check was automated; the DOM order was code-reviewed. | Render the sheet after the nav (or `flex-col-reverse`). Move focus to the first link on open and back to "More" on Esc or close. Give the sheet `role="dialog" aria-modal` with a label, or make it a labelled `nav` disclosure. Ideally reuse the `Dialog` component as a bottom sheet. |
| S4 | **Med** | 2.4.3, 3.3.1 | `components/ui/Button.tsx:33` (`disabled={disabled \|\| loading}`) | When a submit button enters `loading`, it becomes `disabled`, and **focus drops to `<body>`**. Observed on the profile save (`focusAfterSubmit: body`). This affects every async form. | During `loading`, use `aria-disabled="true"` and block clicks in the handler instead of the `disabled` attribute. |
| S5 | **Med** | 2.4.3 | `components/ui/Dialog.tsx:28-40` | Focus returns to the opener only through the `open: true→false` branch. Callers that **unmount** the dialog (`{open ? <NewTestDialog open …/> : null}` at `features/studio/components/Tests.tsx:179`) lose focus to `<body>` after Esc. This was measured on `/studio/tests`. "New bank" and "New assignment" return focus correctly. | Also restore `opener` focus in the effect cleanup or on unmount. Optionally move initial focus to the first field (this already happens through the native dialog). |
| S6 | **Med** | 2.5.8 Target Size (AA ≥24 px); 2.5.5 (AAA 44) | `Button.tsx` size `sm` = `h-8` (32 px), used for "Sign out" in every portal header and for "Sign up" in the public header (inline `h-8`); `Tabs.tsx` tabs are 38 px tall; `PortalShell.tsx:51` staff mobile `<summary>Menu</summary>` is **20 px tall**; Checkbox is 20×20 (its label extends the hit area, which is acceptable) | On touch, the most-used chrome is under 44 px. The staff "Menu" summary fails even the 24 px AA minimum. | Make `sm` `min-h-[36px]` on desktop and `min-h-touch` (44 px) below `md`. Tabs: `min-h-touch`. Summary: `py-3 block`. Standalone text links ("Manage", "All tests", "View instructions", "Grade", "Review", table title links, 19–20 px tall): add `py-2 -my-2` or `inline-flex min-h-6`. |
| S7 | Med | 4.1.3, 3.3.1 | `components/ui/FormField.tsx:55` (`role="alert"` on **every** field error) | An empty submit of signup fires 5 field alerts plus the `ErrorSummary` at the same moment, which is noisy and usually truncated by screen readers. Login and support do the same. | Use a plain `<p id>` for field errors, wired with `aria-describedby` (already done). Keep a single announcement: the summary, or one polite live region. |
| S8 | Low | 4.1.2 | Two divergent `LoadingBlock` implementations: `features/trainer/shared/ui.tsx:115` (`aria-label` on a role-less div, which is an **axe serious `aria-prohibited-attr`** on `/trainer` mobile) and `features/learning/components/States.tsx:19` (correct) | The two implementations behave inconsistently. | Move one `LoadingBlock` (`role="status"` plus sr-only text) into `components/ui/Display.tsx` and delete the trainer copy. |
| S9 | Low | 1.4.1 | Link styling: `text-fg-link` without underline inside running text | axe **serious `link-in-text-block`** on `/courses/[slug]` ("See **plans**", `features/catalog/components/CourseAccess.tsx:77`). The same pattern appears in `AccessList.tsx:53` and `Billing.tsx:165`. | Have `globals.css` underline links inside `p`, or add an `underline` default to a shared `TextLink`. |
| S10 | Low | 1.3.1 / UX | `PublicShell.tsx` header | At 390 and 820 px the seven nav items wrap onto **two lines** of 20 px-tall text links (the header is about 120 px). There is no menu toggle. "Log in" is plain text; "Sign up" is 32 px tall. Evidence: `pub-landing-mobile.png`. | Below `md`: show logo, "Log in" and "Sign up" (44 px), plus a "Menu" disclosure for the five other links. Footer links are also 20 px tall; add `py-1.5`. |
| S11 | Low | 3.3.2 / cognitive | `PortalShell` page headers across portals | Internal requirement codes (`ADM-004`, `TRN-001`, `TRN-005`, `CMS-004`) are rendered as eyebrows above each `<h1>`. They are meaningless to users and work against the "extreme simplicity" goal. | Remove them from the UI (keep them in comments or `data-` attributes). |
| S12 | Low | 2.4.11 | Staff portals below `lg` (that includes the 820 px tablet) | The sidebar is hidden and navigation sits behind a collapsed `<details>Menu`, which is easy to miss on tablet. | Show the sidebar from `md`, or turn the menu into a visible top tab or segmented nav at tablet sizes. |

## Per-page findings

Notes on reading these tables:
- "–" means nothing beyond the shared items above.
- Each page inherits S2/S6 (all portals), S3 (student, mobile and tablet), S10 (public) and S11 (staff).
- Severity: **High** blocks or hides a task for a group of users; **Med** is a WCAG AA failure with a workaround; **Low** is best practice or AAA.

### Public (PublicShell)

| Page | Mobile 390 | Tablet 820 | Desktop 1440 |
|---|---|---|---|
| `/` landing | S10: two-row header nav with tiny targets | S10 | – (axe clean) |
| `/login` | Form good: on an empty submit both fields get `aria-invalid` and `describedby` errors, and focus stays on the button (acceptable). S6: "Forgot password?" is 20 px tall | same | same |
| `/signup` | **Med**: the DOB "DD" select is truncated to "DI" (3 equal columns at 390; `SignupForm.tsx:182`; `pub-signup-mobile.png`). **Med 3.3.1/1.3.1**: after an empty submit, 7 fields are `aria-invalid` but only 3 have `aria-describedby`. The DOB selects (`SignupForm.tsx:176-186`) point to the error only from the `<fieldset>`, and the terms checkbox has none. Focus correctly moves to the ErrorSummary. S7 (6 simultaneous alerts) | Same field-association issue; DOB fits | same |
| `/courses` | "Clear" link 32×20 (S6) | – | – |
| `/courses/demo-aptitude-paid` | **axe serious link-in-text-block** (S9) | same | same; sticky "Access" aside is fine |
| `/pricing` | – | – | – |
| `/forgot-password` | "Back to sign in" link 20 px tall | – | – |

### Student (PortalShell `student` and MobileTabBar)

| Page | Mobile 390 | Tablet 820 | Desktop 1440 |
|---|---|---|---|
| `/app` dashboard | **High S2**: focused "Manage" and "My learning" sit under the tab bar. S3 (More sheet). Card-header links ("My learning", "All tests", "Manage") are 20 px tall. "Browse free courses" is a 32 px `sm` button | S3; small links | Small links; sidebar links 36 px tall (fine for pointer use) |
| `/app/courses` → redirects to `/app/learning` | S3 | S3 | – |
| `/app/practice` | **High S2**: topic link under the tab bar; "Review incorrect & bookmarked" 20 px | – | – |
| `/app/tests` | Tabs 38 px (S6); "View instructions" 20 px | same | – |
| `/app/assignments` | Tabs 38 px | same | – |
| `/app/settings/profile` | **High S2**: "Save changes" under the tab bar when focused | – | **Med S4**: focus is lost to body after Save |
| `/app/support/new` | Native file input is unstyled and 20 px tall (`features/support/components/StudentSupport.tsx:158`); "Cancel" is an `sm` button. The validation pattern is correct (3/3 fields `aria-invalid` and described) | same | same |

### Admin / Trainer / Evaluator / Studio (PortalShell staff)

All of these share: staff "Menu" summary 20 px tall below `lg` (S6/S12); "Sign out" 32 px; sticky header; requirement-code eyebrow (S11).

| Page | Mobile 390 | Tablet 820 | Desktop 1440 |
|---|---|---|---|
| `/admin` | – | – | – (axe clean) |
| `/admin/users` | **High S1**: contact and status columns are off-screen (`adm-users-mobile.png`); row name links 19 px | S1 is milder | Row links 19 px tall |
| `/admin/batches` | S1 | Batch links 19 px | same |
| `/admin/users/[id]` | – | – | – |
| `/trainer` | **axe serious aria-prohibited-attr** while loading (S8) | **axe moderate landmark-unique**: two "Tests" regions (`TrainerDashboard.tsx:127`, the section and the inner TestsList). The row actions "Attempts / Evaluation / Overrides / Report" are 20 px text links packed together | same as tablet |
| `/trainer/tests` | **High S1**: Assign and the other row actions are invisible; titles wrap one word per line (`trn-tests-mobile.png`) | Row actions packed | Same small links |
| `/trainer/grading` | "Evaluate" link is 53×20; its sr-only suffix is OK | same | same |
| `/trainer/assignments` | **axe moderate heading-order**: an `h3` card title directly under the `h1` (`features/learning/assignment-manager/AssignmentManagerList.tsx:178`; use `h2`) | same | same. "New assignment" dialog: modal, focus inside, Esc closes, focus returns ✔ |
| `/evaluator` | Same as `/trainer/grading` (shared component) | same | same |
| `/evaluator/tests` | S1 | – | – |
| `/studio` | – | – | – |
| `/studio/courses` | S1 | Course links 19 px | same |
| `/studio/questions` | **High S1**: question text wraps to 6+ lines in a narrow column; the status column is cut off (`std-questions-mobile.png`) | **S2**: the focused "Menu" summary is covered by the sticky header | Long question links (good) |
| `/studio/question-banks` | "New bank" dialog: modal, labelled, fits, Esc ✔, focus returns ✔ | – | same ✔ |
| `/studio/tests` | – | – | **Med S5**: after Esc on "New test", focus is lost to body |

### Dialog behaviour (automated, `results/dialogs.json`, shots `dialog-case1-4.png`)

- All four dialogs are native `:modal`, have `aria-labelledby`, put initial focus on the first input, close on Esc, and fit within both viewports.
- Tabbing past the last control goes to the browser chrome (`body`), not to the page behind it. That is native `<dialog>` behaviour and acceptable.
- The only failure is focus return on the unmounted dialog (S5).

## Suggested order for the fix phase

1. S2 scroll-padding (two lines of CSS; fixes focus being hidden on every student page).
2. S1 Table mobile card mode (fixes every staff list).
3. S3 More-sheet focus and DOM order.
4. S4 Button `loading`.
5. S5 Dialog unmount restore.
6. S6 target sizes in Button `sm`, Tabs and the staff Menu.
7. S7 one announcement per submit.
8. Per-page items: signup DOB width and `describedby` (`SignupForm.tsx`), `AssignmentManagerList` `h2`, TrainerDashboard duplicate region, CourseAccess underline, LoadingBlock consolidation, PublicShell mobile header, removing the requirement codes.

To re-run after the restyle: `node docs/archive/redesign-next-app/a11y/audit.cjs [public|student|admin|trainer|evaluator|content]`, then `node docs/archive/redesign-next-app/a11y/summarize.cjs`. Also re-check contrast in **dark mode** (not covered here) once the new tokens land.
