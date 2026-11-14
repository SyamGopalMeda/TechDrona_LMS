# Tech Drona LMS — design system (redesign v2)

Owner: UI/UX & Branding agent, 2026-11-07. Binding for every page-group agent. Read
`docs/redesign/BRIEF.md` first.

**One rule:** pages use the shared kit (`@/components/ui`) and semantic Tailwind tokens
(`bg-surface`, `text-fg-heading`, `bg-brand`…). Never hard-code hex colours, raw Tailwind palette
classes (`bg-blue-600`), other fonts, or a logo other than `<Logo />`.

---

## 1. Brand evidence (where every value comes from)

Source of truth: the official website source `D:\company website\tech drona\` (techdrona.in).
`D:\company website\Logo.png` is GloomDev — never used.

| What | Value | Evidence |
|---|---|---|
| Primary navy (logo) | `#032269` | `src/styles/global.css:18` `--navy`; every logo SVG root `fill="#032269"` (`dist/img/logo-lockup-navy.svg`, `logo-mark-navy.svg`, `logo-full-navy.svg`); header comment global.css:11 "navy (#032269 from the logo)" |
| Navy hover | `#0A3390` | global.css:19 `--navy-600`; `.btn--primary:hover` global.css:130 |
| Navy ink / deep | `#1C3F99`, `#0F1A3A`, `#0A0F1F` | global.css:23 `--navy-ink`, :27 `--ink-2` (headings), :20 `--navy-950` |
| Periwinkle | `#B4C3EC` | global.css:24 (used for dark-mode brand) |
| Navy washes | `#EEF1F9`/`#EEF2FB`, `#DFE4F2`, `#EAF0FD`, `#F3F6FD`, `#F7F9FD`, `#C9D4F1` | global.css:36-37; lms.css:30 (`.lx-tag`), :103 (active nav), :102 (nav hover), lms.css `#f7f9fd`, :120 |
| Text | ink `#121722`, slate `#4A5160`, muted `#5A6170` | global.css:26, :28, :29 |
| Canvases | portal `#F4F6FA`; public ivory `#FAF8F4` | lms.css:4 `html.is-learn body`; global.css:33 `--cream`, `index.html` `theme-color #faf8f4`, `dist/site.webmanifest` |
| Lines | `#E6EAF1`, `#EEF1F6`, `#D5DCEA` | lms.css:41 `.lx-card`, :104, :21 |
| Accent green | `#0D7A4F`, tint `#EAF5EE`, dark `#0B553A`, mint `#8EE0B8` | global.css:2935 `--accent/--accent-tint` ("navy for headings and filled buttons, green as the accent"), :4482 `.btn--green`, :5981 `.ft-col h2` |
| Status tags | good `#E6F6EE/#0B6B44`, bad `#FDECEA/#A12A1C`, warn `#FFF3DD/#8A5200`, muted `#EFF1F4/#5F6470` | lms.css:31-34 `.lx-tag--*` |
| Error | border `#C2412D`, solid `#B42318` | global.css:183 `.has-error`, lms.css (`#b42318`) |
| Fonts | Plus Jakarta Sans 500-800 (headings, buttons, nav), Inter 400-700 (body) | `index.html` Google Fonts link; global.css:40-41 `--head`, `--body`; :66 body 16px/1.65 |
| Buttons | navy fill, white, Jakarta 600 15px, 8px radius, min-height 44px; outline = white + navy/22 border | global.css:125-132 `.btn` |
| Inputs | 1px border, 8px radius, 12/14px padding, focus navy border + 3px navy/12 halo | global.css:180-182 `.field input` |
| Cards | white, 1px line, 12-16px radius, `--sh-card` | global.css:54, :140; lms.css:41 `.lx-card` (16px) |
| Radii | 8 / 12 / 18 / 22 / pill | global.css:48-52 |
| Shadows | card, raised, float | global.css:54-56 |
| Portal shell | 248px white sidebar, active item `#EAF0FD` + navy text, 800-weight 21px page title | lms.css:95-113 |
| Footer | navy band, white lockup, mint uppercase column headings | global.css:5973-5983, `src/components/Layout.jsx:345` |
| Slogan | "Debug your career. Deploy your dreams." | `index.html` JSON-LD `slogan` |
| Icons | `favicon-32.png`, `apple-touch-icon.png` (180), `icon-512.png` | `dist/` + `index.html` `<link rel=icon>` |

Live https://techdrona.in was not re-fetched; values above are read from the deployed build's
source (`dist/` mirrors `public/`).

**Deviations (documented, for accessibility):** form control borders use `#737C91` (website
`#D6D3CB` is 1.4:1, fails WCAG 1.4.11); info status keeps an accessible blue (`#1A5499` on
`#EAF3FD`) because the site has no info colour; dark-mode navy surfaces `#16244F`/`#1C2D5E` are
derived (the website has no dark mode).

### Assets in the LMS

| File | Use |
|---|---|
| `apps/web/public/brand/logo-lockup-navy.svg` | Header logo (mark + wordmark, 922×200) on white/light |
| `apps/web/public/brand/logo-lockup-white.svg` | Footer / navy band only |
| `apps/web/public/brand/logo-mark-navy.svg` | Square mark for tight spaces |
| `apps/web/public/favicon-32.png`, `apple-touch-icon.png`, `icon-512.png` | Favicons / PWA (wired in `src/app/layout.tsx` metadata + `src/app/manifest.ts`) |
| `apps/web/public/favicon.ico` | Legacy `/favicon.ico` request (was a dynamic 404 page, perf-baseline P11): ICO wrapper around the unchanged official `favicon-32.png` (static; the middleware matcher already skips it) |
| `apps/web/public/fonts/*.woff2` | Self-hosted Plus Jakarta Sans + Inter (latin, latin-ext), `src/styles/fonts.css` |

All copied byte-for-byte from `tech drona/dist/` (favicon.ico only re-wraps favicon-32.png).

Fonts are self-hosted with `@font-face` + `preload` (`src/styles/fonts.css`, `layout.tsx`) rather than `next/font/local`: the website's files are split latin / latin-ext by `unicode-range`, which `next/font/local` cannot express. The result is the same: no Google Fonts request, `font-display: swap`. Use `<Logo />` (`@/components/ui`), never an `<img>` to them directly.

---

## 2. Tokens

Source: `packages/design-tokens/tokens.json` (v2.0.0) → `npm run build` (in that package) generates
`tokens.css`; `npm run check` verifies **218/218 required WCAG 2.2 AA pairs pass** (light + dark).
`apps/web/src/styles/fallback-tokens/tokens.css` is a verbatim copy. Tailwind names = token path.

### Colour (light — the brand)

| Tailwind class part | Hex | Use |
|---|---|---|
| `surface-canvas` | `#F4F6FA` | Portal page background |
| `surface-warm` | `#FAF8F4` | Public pages background (ivory) |
| `surface` / `surface-raised` | `#FFFFFF` | Cards, tables, header, sidebar, dialogs |
| `surface-subtle` | `#F7F9FD` | Table header, dialog footer, quiet panels |
| `surface-sunken` | `#EFF1F4` | Skeletons, neutral badge, disabled inputs |
| `surface-hover` / `surface-selected` | `#F3F6FD` / `#EAF0FD` | Row/nav hover; active nav item |
| `surface-brand` | `#032269` | Navy band (footer, hero) — text `fg-on-surface-brand` (white) |
| `fg` | `#121722` | Body text |
| `fg-heading` | `#0F1A3A` | Headings, titles, metric values |
| `fg-secondary` | `#4A5160` | Supporting text, descriptions |
| `fg-muted` | `#5A6170` | Hints, meta, captions (still 5.9:1) |
| `fg-disabled` | `#9AA2B5` | Disabled only |
| `fg-link` / `fg-link-hover` | `#0A3390` / `#032269` | Links |
| `brand` / `brand-hover` / `brand-active` | `#032269` / `#0A3390` / `#0F1A3A` | Primary buttons, active indicators, icons |
| `brand-subtle` / `brand-on-subtle` | `#EEF2FB` / `#032269` | Chips, icon wells, portal title pill |
| `accent` / `accent-subtle` / `accent-on-subtle` | `#0D7A4F` / `#EAF5EE` / `#0B6B44` | Eyebrows, success-ish highlights, checks (never filled buttons) |
| `accent-on-brand` | `#8EE0B8` | Headings on the navy band |
| `line` / `line-subtle` / `line-strong` | `#E6EAF1` / `#EEF1F6` / `#D5DCEA` | Borders, dividers, dashed empty states |
| `line-control` | `#737C91` | Input/select/checkbox borders (3:1) |
| `focus` | `#0A3390` | Focus ring (`shadow-focus` = 2px white + 2px navy) |
| `success-*` | fg `#0B6B44`, subtle `#E6F6EE`, border `#0D7A4F`, solid `#0B6B44` | Approved/active/paid |
| `warning-*` | fg `#8A5200`, subtle `#FFF3DD`, border `#B07006`, solid `#F2A516` (ink text) | Pending/needs action |
| `danger-*` | fg `#A12A1C`, subtle `#FDECEA`, border `#C2412D`, solid `#B42318` | Rejected/failed/errors/destructive |
| `info-*` | fg `#1A5499`, subtle `#EAF3FD`, border `#2A78D6`, solid `#1F64B8` | Scheduled/in progress/notices |

Opacity modifiers work (`bg-brand/10`, `border-brand/30`). Risk (`risk-l0..l4`), question palette
(`qstate-*`), timer and chart tokens are unchanged from v1 (charts keep their validated palette).

**Dark mode** exists (OS `prefers-color-scheme`, or `data-theme="dark"`) and is retuned: brand =
periwinkle `#B4C3EC`, navy-tinted selection. Light is the brand; design and screenshot in light first,
then sanity-check dark. Never use `dark:` variants — tokens switch automatically.

### Typography

| Role | Classes | Spec |
|---|---|---|
| Page title (h1) | `PageHeader` (or `font-display text-2xl sm:text-[1.75rem] font-extrabold text-fg-heading`) | Jakarta 800, 24→28px |
| Section heading (h2) | `SectionHeader` (or `Card titleSize="lg"`): `font-display text-lg font-extrabold` | Jakarta 800 20px |
| Card title (h2/h3) | `font-display text-base font-bold text-fg-heading` (Card does this) | Jakarta 700 16px |
| Table cells, card descriptions | `text-[0.9375rem]` (kit default) | 15px |
| Eyebrow | `font-display text-xs font-bold uppercase tracking-[0.12em] text-accent` | website `.eyebrow` |
| Body | default (`font-sans` Inter 16px / 1.6) | |
| Secondary / help | `text-sm text-fg-secondary` / `text-[0.8125rem] text-fg-muted` | 14 / 13px |
| Metric | `font-display text-2xl font-extrabold tabular-nums text-fg-heading` (StatTile) | |
| Buttons, tabs, nav, badges | `font-display font-semibold`/`font-bold` | Jakarta |
| Code | `font-mono` | |

`h1–h4` default to the display family automatically. Minimum text size 12px (`text-xs`).

### Radius, shadow, spacing, layout

| Token | Value | Use |
|---|---|---|
| `rounded-sm` | 6px | Small chips, inner elements |
| `rounded-md` | 8px | Buttons, inputs, nav items (website `--r-sm`) |
| `rounded-lg` | 12px | Icon wells, menus, nav items |
| `rounded-xl` | 16px | Cards, tables, empty/error states, toasts (website `.lx-card`) |
| `rounded-2xl` | 20px | Dialogs, auth cards, sheets |
| `rounded-full` | pill | Badges, avatars |
| `shadow-xs` | hairline | Cards, tables, inputs |
| `shadow-sm` | website `--sh-card` | Hoverable cards |
| `shadow-md` / `shadow-lg` / `shadow-xl` | header / raised / float | Menus, toasts, dialogs |
| Spacing | Tailwind 4px scale | Page sections `space-y-6`; card padding `p-5 sm:p-6`; grid gaps `gap-4` (tiles) / `gap-6` (sections) |
| Layout | `h-topbar` 56px, `w-sidebar` 264px, main max `max-w-wide` (90rem; pages pick `PageContainer` widths), `min-h-touch` 44px | |

Buttons and inputs are **44px** tall by default (`md`); `sm` is 44px below `md` and 36px on desktop (tables/toolbars).

---

## 3. Components (`import { … } from "@/components/ui"`)

All APIs are backward compatible; new props are optional.

| Component | Use it for | Rules |
|---|---|---|
| `Button` `variant="primary|secondary|ghost|danger|danger-secondary"` `size="sm|md|lg"` `loading` | Actions | **One primary per view.** Secondary = navy outline. `danger` only for irreversible actions inside a confirm Dialog; `danger-secondary` for the button that opens it. Verb-first labels ("Approve request"). |
| `LinkButton` / `buttonClasses()` | Navigation that looks like a button | Never put `onClick` navigation on a `Button`. |
| `Input`, `Textarea`, `Select`, `Checkbox` inside `FormField` | Forms | Always a visible label; `hint` for format; `error` text says how to fix. Never placeholder-as-label. |
| `Card` `title` `description` `actions` | Grouping related content | One idea per card; title is a noun ("Upcoming tests"); `actions` = small secondary buttons/links. |
| `Table` | Lists of records | Pass `caption`, `empty={{title, description, action}}`, `loading`, `error`, `onRetry`. Right-align numbers. Row actions as `size="sm"` buttons, max 2 visible. |
| `Badge` `tone` `dot` / **`StatusBadge status="pending"`** | Status | Use `StatusBadge` for any machine status — see §5. Text always present. |
| `StatTile` `label` `value` `hint` `icon` `tone` | Dashboard numbers | `value={null}` when unknown (shows —), never fake numbers. 2 per row on phones, 4 max on desktop. |
| `PageHeader` `title` `description` `actions` `eyebrow` `breadcrumbs` `back` | Top of every page | See §4. |
| `Breadcrumbs` | Trail for depth ≥ 2 | Usually via `PageHeader breadcrumbs`. |
| `Tabs` | Switching views of the same object | ≤ 6 tabs; not for primary navigation. |
| `Dialog` `title` `description` `footer` | Confirmations, short forms | Footer: secondary "Cancel" left, primary/danger right. |
| `useToast().show({title, tone})` | Result of an action | Past tense ("Request approved"). Errors stay until dismissed. |
| `Skeleton` / `LoadingBlock` | Loading placeholders | Match the final layout's shape; `LoadingBlock` for a whole region (announces once). |
| `ErrorSummary` `errors` `fieldIds` | Failed form submit | The one announcement per submit (§7 S7). `fieldIds` = the FormField control ids. |
| `EmptyState` `title` `description` `action` `icon` | Nothing to show | Say why it's empty + the one next step. |
| `ErrorState` `error` `onRetry` | Failed load | Pass the ApiError so the reference id shows. |
| `Pagination` | Cursor lists | Unchanged. |
| `Logo` `variant="lockup|mark"` `tone="navy|white"` | Brand | Size with a height class only. White only on `bg-surface-brand`. |
| `PageContainer` `width="prose|content|wide|full"` / `pageWidthClass()` | Page width | prose 45rem (forms, settings, reading), content 72rem (default), wide 90rem (data-heavy). Don't use ad-hoc `max-w-2xl/3xl/4xl` for pages. |
| `SectionHeader` `title` `description` `actions` | Section heading (h2, 20px) | Between the 28px h1 and 16px card titles. `Card titleSize="lg"` gives the same level on a card. |
| `StatGrid` `columns` + `StatTile` `href` `tone` `size="compact"` | Dashboard numbers | 2 per row on phones. `href` makes the tile a link to the queue behind the number; `tone="warning|danger"` (no icon) adds an accent bar. |
| `KeyValueList` `items` `columns` | Facts about one record | Missing values show "—". |
| `FilterBar` `label` `columns` `actions` `variant` | Filters above a list | A named `search` landmark. Pass it as `Table toolbar={…}` with `variant="plain"` so it stays visible when the list is empty. |
| `Segmented` `variant="cards|pills"` / `Chip` | Single choice / quick filter toggles | Native radios / `aria-pressed`; 44px on touch. |
| `ProgressBar` `value` `label` `showValue` / `ProgressRing` | Progress | Server-reported values only. |
| `ConfirmDialog` `title` `confirmLabel` `danger` `onConfirm` | "Are you sure?" | Use instead of `window.confirm`; a thrown error shows inline and keeps it open. |
| `Dialog` `size="sm|md|lg|xl"` | | Has a × button, a scrolling body, a pinned footer, and is a bottom sheet on phones. |
| `Table` `toolbar` `stickyHeader` · column `priority="secondary"` | | Secondary columns hide at tablet widths; blank cells ("—") are dropped from the stacked phone card. |
| `EmptyState` `variant="inline"` `icon="search|calendar|book|document|chart|lock|users|bell|code|card|chat|award|shield|check|inbox"` | | Use `inline` inside a Card; pick a topic icon. |
| `PageHeader` `breadcrumbs` `back` `meta` | | Detail pages: breadcrumbs + the entity's name as the h1 + `meta={<StatusBadge …/>}`. |
| `LoadingBlock` `rows` `size="line|row|card"` | Loading | The one loading pattern (feature `Loading`/`LoadingBlock` copies now wrap it). |

Shells (`src/components/shell`) already render the logo, portal name, sidebar/drawer, mobile tab
bar, sign-out, portal switcher and notification bell. **Pages must not render their own app header,
logo or sidebar.**

---

## 4. Page layout pattern (every portal page)

```tsx
<PageHeader
  breadcrumbs={[{ label: "Admin", href: "/admin" }, { label: "Users" }]}   // depth ≥ 2 only
  title="Users"                                                         // = nav label
  description="Invite people, change roles and suspend accounts."        // ONE line: what this page is for
  actions={<LinkButton href="/admin/users/invite">Invite user</LinkButton>} // ONE primary action
/>
<div className="space-y-6">
  {/* filters (if any) → content (Table / cards) → secondary info */}
</div>
```

1. **Title** matches the sidebar label, so users know where they are (active nav item + title + breadcrumbs).
2. **One-line purpose** in plain words for a first-time user (no jargon, no screen ids).
3. **One primary action** top-right (stacks under the title on phones). Other actions are secondary/ghost.
4. **Content**: most important thing first. Dashboards: StatTiles row → "what needs your attention" list → recent activity.
5. Every data region handles Loading (Skeleton) / Empty (EmptyState with next step) / Error (ErrorState with retry).
6. Public/auth pages: centred card (`max-w-md`, `rounded-2xl bg-surface p-6 sm:p-8 shadow-lg border border-line`), title + one line + form + one primary full-width button.
7. Phones (360-430px): single column, no horizontal page scroll (wide tables scroll inside their own region), tap targets ≥ 44px.

---

## 5. Status vocabulary (`StatusBadge`, `STATUS_VOCABULARY`)

| Tone | Meaning | Statuses → label |
|---|---|---|
| warning (amber) | Waiting on someone / needs action | pending → Pending, pending_review → Pending review, in_review, awaiting_payment, requested |
| success (green) | Done / good / on | approved, active, published, completed, passed, paid, verified, graded, resolved, enabled → On |
| info (blue) | Moving / scheduled | submitted, scheduled, in_progress, processing, open |
| brand (navy) | Happening now / new | live, new |
| danger (red) | Problem / refused | rejected, failed, blocked, suspended, overdue |
| neutral (grey) | Parked / off / ended | inactive, disabled → Off, draft, archived, closed, expired, cancelled, refunded, not_started |

The full list (≈100 statuses, incl. admin, commerce, support, trainer and learner states) is `STATUS_VOCABULARY` in `Display.tsx`; `statusTone()` / `statusLabel()` read it. Feature badges (`StateBadge`, `TicketStatusBadge`, `EnquiryStatusBadge`, trainer/engage `StatusBadge`, `OrderStatusBadge`) take their tone from it and only override wording. Add new statuses there, never in a local colour map.
Unknown statuses render neutral with a humanised label (`in_review` → "In review"). Override with
`label`/`tone` only when the domain needs a better word (e.g. `status="pending" label="Awaiting evaluator"`).
Use the same word everywhere for the same state.

---

## 6. Do / don't for page agents

**Do**
- Use `PageHeader` on every page with title + one-line description + at most one primary action.
- Use `StatusBadge` for every status; `Card`/`Table`/`EmptyState`/`ErrorState` instead of hand-rolled boxes.
- Use semantic tokens only (`text-fg-secondary`, `border-line`, `bg-brand-subtle`).
- Write labels as a first-time user would say them ("Approve", "Your courses", "Due Friday").
- Keep forms one column on phones; put the primary submit last and full-width on phones.
- Use `LinkButton` for navigation, `Button` for actions; `loading` while a request runs.
- Check 360px width and keyboard focus (visible navy ring) on every page you touch.

**Don't**
- Don't hard-code colours (`#…`, `bg-blue-600`, inline `style={{color}}`), fonts, or shadows.
- Don't add a second logo, app header, or sidebar inside pages; don't use any other logo file.
- Don't use colour alone to convey status; don't invent new status words for existing states.
- Don't put more than one filled (primary) button in a view; never a filled green button (green is accent, navy is action).
- Don't show internal ids (screen ids like "ADM-004", UUIDs) as headings or eyebrows for end users.
- Don't use `dark:` variants; don't use text smaller than 12px; don't remove focus outlines.
- Don't change `src/components/ui`, shells or tokens — ask the design-system owner (additive needs → request).

---

## 7. Accessibility built into the kit (audit `a11y-responsive.md` S1–S7)

| Item | Where | Behaviour (automated-tested in `ui.test.tsx` / `shell.test.tsx` unless noted) |
|---|---|---|
| S1 | `Table` | Below `sm` rows render as stacked cards: each cell shows its column header (`data-label`), actions stay visible; explicit `table/row/cell` roles keep semantics. Give columns plain-string headers so the label shows. |
| S2 | `globals.css` | `scroll-padding-top` = topbar (+ public header), `scroll-padding-bottom` = tab bar on the student shell below `lg` (code-reviewed; CSS not testable in jsdom). |
| S3 | `MobileTabBar` | "More" sheet follows the bar in DOM order, focus moves to its first link, Escape closes and returns focus to "More". |
| S4 | `Button loading` | Stays focusable (`aria-disabled`, `aria-busy`), ignores clicks and implicit submit. Tests should assert `aria-disabled`, not `toBeDisabled()`, for loading. |
| S5 | `Dialog` | Focus returns to the opener on close **and** when the caller unmounts it. |
| S6 | `Button sm`, `Tabs`, staff `Menu`, breadcrumbs/back link | ≥ 44px on touch (sm button below `md`, tabs, Menu summary); small inline links ≥ 24px. Page agents: give standalone text links `inline-flex min-h-6 items-center` (or use `LinkButton size="sm"`). |
| S7 | `FormField` + `ErrorSummary` | Field errors are plain text wired by `aria-describedby` + `aria-invalid`, **not** `role="alert"`. Each form announces once: render `<ErrorSummary errors={…} fieldIds={…} />` at the top of the form; it is the only alert, takes focus when the errors change and links each message to its field. |
| S8 | `LoadingBlock` | `<LoadingBlock label="Loading tests…" />` = one `role=status` with sr-only text + skeleton lines. Use it instead of feature-local copies (`features/trainer/shared/ui.tsx` should switch). |
| Codes | `PageHeader` | An `eyebrow` containing a screen code (`ADM-004`, `SEC · ADM-006`) is not rendered. Page agents: remove such eyebrows; feature components that print codes themselves must drop them too. |

## 8. Files

- Tokens: `packages/design-tokens/tokens.json` (+ generated `tokens.css`, `tailwind-v4.css`), `scripts/check-contrast.mjs`
- Fallback copy: `apps/web/src/styles/fallback-tokens/{tokens.css,tailwind-preset.cjs}`
- Global CSS / fonts: `apps/web/src/app/globals.css`, `apps/web/src/styles/fonts.css`, `apps/web/public/fonts/`
- Kit: `apps/web/src/components/ui/*` (new: `Logo.tsx`, `LinkButton`, `Textarea`, `StatusBadge`, `Breadcrumbs`, `ErrorSummary.tsx`, `LoadingBlock`)
- Shells: `apps/web/src/components/shell/{PortalShell,PortalNav,MobileTabBar,PortalSwitcher,PublicShell}.tsx`
- Root: `apps/web/src/app/layout.tsx` (icons, theme colour, font preload), `apps/web/src/app/manifest.ts`
- Screenshots (deleted in cleanup D4 on 2026-11-14; recover from git commit `24134de`): `docs/redesign/shots/design/` — `before-*` = running container :13000, `after-*` = `next start -p 13100` of this build (same dev API :18000); login, student dashboard and admin dashboard at 1440 (`-desktop`) and 390 px (`-mobile`), each signed in fresh in its own browser context (2026-11-08). All 12 captured and checked: the after shots show the real logo, navy brand, and no `ADM-001` eyebrow. The first pass in `shots/design-system/` has invalid `after-*-dashboard-*` shots (they landed on the login page); use this folder.

## Dashboards (2026-11-10)

Portal landing pages follow one layout (`components/ui/Dashboard.tsx`):

- **Sidebar**: dark navy (`bg-surface-brand`) on desktop, grouped sections, active item with an accent bar; footer with "Public website" and "Sign out" (`PortalFrame` → `PortalNav tone="dark"`). The phone Menu sheet keeps the light nav.
- **`DashboardHero`**: full-bleed navy band with the h1, one-line purpose and today's date (IST). Pass a `<StatGrid>` as children: the tiles overlap the band's lower edge.
- **`StatTile`**: status dot + label, corner icon (`icon="users"` etc. from the kit `Icon` set), large value, hint. Use `tone="highlight"` for the one solid-navy tile a dashboard leads with; `warning`/`danger` only when the number needs action. `size="compact"` tiles (inside cards) are flat, without a shadow.
- **Panels**: `Card icon="…" actions={<ViewAllLink href="…" />}`.
- **`QuickActions`**: icon + label + one-line hint + arrow tiles; `columns={3}` in a full-width card, default 2 in a half-width card.

Used on `/admin`, `/app`, `/trainer`, `/evaluator`, `/studio`. Other pages keep the light `PageHeader`.
