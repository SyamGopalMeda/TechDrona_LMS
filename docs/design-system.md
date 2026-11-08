# Tech Drona LMS: Design System (v1.0)

Owner: UX/UI Designer. Status: **Planned** (Stage 2 product design). Tokens are implemented in `packages/design-tokens` (source of truth: `tokens.json`; generated `tokens.css`, `tailwind-v4.css`; `tailwind-preset.js`).
Read with: `docs/product-requirements.md` (screen IDs, journeys, dashboards), `docs/account-unblock-workflow.md` §1 (restriction copy, verbatim), `docs/account-security-and-risk-engine.md` §6 and §10, `docs/analytics-event-schema.md` §3.11 and §6, `docs/role-permission-matrix.md` §5 and §8. Companion docs: `docs/sitemap.md`, `docs/wireframes.md`.

If this document and the PRD disagree on behaviour, the PRD wins; if they disagree on visual or copy treatment, this document wins. Restriction copy in `account-unblock-workflow.md` §1 is reproduced by reference and must not be reworded in the UI.

---

## 1. Brand direction

**Idea: "aim with clarity".** Drona is the teacher who trains archers to see only the target. The product helps a student see exactly where they stand and what to do next, and helps Tech Drona's trainers see the same thing honestly. The brand is therefore:

| Attribute | Means in the UI | Never |
|---|---|---|
| **Precise** | Real numbers with units and method links; tabular figures; exact dates in IST | Vague badges ("Rockstar!"), inflated percentages, fake urgency |
| **Calm and premium** | Generous whitespace, one strong colour (Drona Indigo), restrained accent, quiet surfaces | Gradients everywhere, neon, confetti, auto-playing hero video, countdown-to-sale timers |
| **Corporate-trustworthy** | Consistent grid, predictable navigation, policies written in plain English and linked where they apply | Dark patterns: pre-ticked boxes, strike-through anchors, hidden cancel, confirm-shaming |
| **Mentor-like** | Copy that explains *why* and *what next*; never blames | Accusatory security copy, red full-screen alarms |

**Originality guard.** Tech Drona must not look like PrepInsta (orange/purple, dense promo blocks, discount anchors) or Coursera (bright #0056D2 blue, university-logo walls). Our hue is a deep blue-violet indigo (H≈235°) with a teal accent, cool neutral ink, and a geometric display face.

**Signature motifs** (use sparingly; maximum one per screen):
- **Aim arc**: a thin 2 px arc segment (brand or accent) used in the readiness ring, the logo lock-up and empty-state illustrations. It is the only decorative shape.
- **Readiness ring**: a target-style ring (track + filled arc + number in the centre) used only for company readiness (§7.4).
- **Published-numbers strip**: the "3 devices · 2 sessions · 1 stream · 2 replacements/30 days" strip appears on Home, Pricing, Device policy and STU-022 in the same component, reinforcing differentiator D4.

**Logo usage (placeholder until the brand mark is final).** Wordmark "Tech Drona" in Plus Jakarta Sans 800, "Drona" in `brand`; minimum clear space = cap height; on dark/brand bands use `fg-on-surface-brand`. Favicon: the aim arc over a "D" counter.

**Motion stance.** Motion explains change (a panel opens, a value updates); it never decorates. No parallax, no looping animations, no animated counters on dashboards, no skeleton shimmer under reduced motion.

---

## 2. Design principles

1. **Explain every state.** Each screen implements L/E/X/B/R(/O) (PRD §6) with a sentence that says what happened and the next action. No dead ends.
2. **Server truth, shown honestly.** Timers, autosave, payment status and restrictions display the server's state and its freshness ("Saved 3 s ago", "Updated 02:00 IST"). Never fake progress.
3. **Protect work first.** Any action that can lose work (sign out a session, rebind a test, leave a test, revoke a device) names the work at risk and defaults to the safe choice.
4. **Least data on screen.** Show only what the viewer's role and tier allow (role matrix §8 tiers M0–M3). Masked IPs by default; "Reveal" requires a reason and is audited.
5. **Colour is never alone.** Every status, risk level, palette state and series pairs colour with a label, icon or shape.
6. **Performance is design.** Mid-range Android on 4G is the reference device (NFR-PERF-03). Prefer text and CSS over images; test-runner route JS ≤ 200 KB gz; fonts subset and `display=swap`.
7. **One way to do a thing.** One primary button per view; consistent placement (primary right in dialogs on desktop, full-width stacked on mobile with primary first).

---

## 3. Tokens reference

All values live in `packages/design-tokens/tokens.json`. CSS variables are prefixed `--td-`. Tailwind class names come from the preset (e.g. `bg-surface`, `text-fg-muted`, `border-line-control`, `bg-risk-l3-subtle`).

### 3.1 Colour: primitives

| Ramp | Role | Key steps |
|---|---|---|
| `neutral` (cool ink) | Text, surfaces, borders | 50 `#F5F6FA` · 100 `#ECEEF4` · 200 `#DCE0EA` · 500 `#737C91` · 600 `#566074` · 700 `#3F4859` · 900 `#1A1F2B` · 925 `#161B25` · 950 `#10141C` |
| `indigo` ("Drona Indigo") | Brand, focus, links, sequential charts | 50 `#EEF0FB` · 300 `#939DE6` · 500 `#4B55C8` · **600 `#3B43B0` (primary)** · 700 `#2F358F` · 900 `#1C2052` · 950 `#121433` |
| `teal` ("Arrow Teal") | Accent: progress highlights, marketing emphasis, L0 "all clear" | 50 `#E8F7F5` · 300 `#6FD0C3` · 700 `#0D6B62` |
| `green` / `amber` / `red` / `blue` | Status: success / warning / danger / info | see tokens.json |
| `orange` / `plum` | Risk L3 / L4 only | see tokens.json |

Primitives are not used directly in product UI (the preset exposes them under `primitive.*` only for illustrations and marketing).

### 3.2 Colour: semantic (light | dark)

| Token | Light | Dark | Use |
|---|---|---|---|
| `surface-canvas` | `#F5F6FA` | `#10141C` | App background behind cards |
| `surface` | `#FFFFFF` | `#161B25` | Cards, panels, tables, inputs |
| `surface-raised` | `#FFFFFF` + shadow | `#1A1F2B` + ring shadow | Menus, popovers, dialogs |
| `surface-sunken` / `surface-subtle` | `#ECEEF4` | `#0B0E14` / `#232A38` | Wells, table headers, code input |
| `surface-hover` / `surface-selected` | `#E3E6EE` / `#EEF0FB` | `#2A3140` / `#20244A` | Row hover / selected nav, selected row |
| `surface-brand` | `#1C2052` | `#121433` | Marketing hero band, footer |
| `fg` / `fg-secondary` / `fg-muted` | `#1A1F2B` / `#3F4859` / `#566074` | `#ECEEF4` / `#C3C9D7` / `#9AA2B5` | Body / supporting / metadata (all ≥ 4.5:1 on every surface) |
| `fg-disabled` | `#9AA2B5` | `#566074` | Disabled text (exempt from 1.4.3; always paired with `aria-disabled` and a reason tooltip where relevant) |
| `fg-link` | `#3B43B0` | `#939DE6` | Links (underlined in body text) |
| `line` / `line-strong` | `#DCE0EA` / `#C3C9D7` | `#2A3140` / `#3F4859` | Decorative dividers, card borders |
| `line-control` | `#737C91` | `#737C91` | Input, checkbox, radio, toggle borders (≥ 3:1, SC 1.4.11) |
| `brand` / `brand-hover` / `brand-active` | `#3B43B0` / `#2F358F` / `#262B70` | `#939DE6` / `#BCC3F1` / `#DDE1F8` | Primary button, active indicators |
| `brand-on` | `#FFFFFF` | `#121433` | Text on brand |
| `brand-subtle` / `brand-on-subtle` | `#EEF0FB` / `#2F358F` | `#20244A` / `#BCC3F1` | Selected nav, chips, info cards |
| `accent` / `accent-subtle` | `#0D6B62` / `#E8F7F5` | `#6FD0C3` / `#0F2E2B` | Secondary emphasis (max one accent element per view) |
| `focus` + `focus-offset` | `#4B55C8` + white | `#939DE6` + `#161B25` | 2 px offset + 2 px ring (`shadow-focus`) |
| `success-*`, `warning-*`, `danger-*`, `info-*` | `fg`, `subtle`, `border`, `solid`, `on-solid` per status | dark equivalents | Alerts, toasts, badges, validation |
| `overlay-scrim` | `#10141C` @ 64% | `#000` @ 72% | Modal backdrop |
| `overlay-watermark` | white @ 35% + 35% black shadow | same | Video watermark text (§6.10) |

### 3.3 Risk levels (L0–L4)

Designed to be **non-alarmist and colour-blind safe**: no level uses pure red (red is reserved for form errors and destructive actions); the ramp moves teal → blue → amber → orange → plum; each level always ships with a **label**, an **icon** and a **level meter** (4 pips, filled = level), so meaning never depends on hue. Validated with the dataviz CVD validator (all-pairs: normal-vision ΔE ≥ 15.8 light; CVD ΔE 7.9 deutan worst pair, i.e. inside the "secondary encoding required" band, which the label + pips satisfy).

| Level | Student-facing label | Staff label | Icon (Lucide) | Pips | Light `solid` / `fg` on `subtle` | Dark `solid` / `fg` |
|---|---|---|---|---|---|---|
| L0 | All clear | L0 · None | `shield-check` | ○○○○ | `#00917F` / `#00695C` on `#E6F5F2` | `#16A08D` / `#5FD0BD` |
| L1 | New activity | L1 · Notice | `info` | ●○○○ | `#1F64B8` / `#1F5FAE` on `#EAF3FD` | `#3987E5` / `#8AB8F2` |
| L2 | Confirm it's you | L2 · Verify | `smartphone` (+check) | ●●○○ | `#E0A000` / `#7A5000` on `#FDF5E0` | `#F2C84B` / `#F2C84B` |
| L3 | Learning access paused | L3 · Temporary restriction | `pause-circle` | ●●●○ | `#C2410C` / `#9A3412` on `#FDECE4` | `#D4502F` / `#F39A7F` |
| L4 | Account suspended pending review | L4 · Suspended | `lock` | ●●●● | `#7A3A8A` / `#6B2F7A` on `#F5EBF7` | `#B65FC0` / `#D9A1DF` |
| T-protect | We've secured your account | T-protect | `shield-alert` | — (separate family) | uses `info` tokens | uses `info` tokens |

Rules: students never see the words "risk", "score" or "L3"; they see the student label. Staff consoles show `L3 · Temporary restriction` plus pips.

### 3.4 Question-palette states (TST-002, FR-ASM-014)

Five states follow Indian exam-UI conventions but add **shape and glyph** so they survive colour-blindness and greyscale printing:

| State | Fill / text | Shape | Glyph | Token |
|---|---|---|---|---|
| Not visited | `surface` / `fg-secondary`, 1 px `line-control` border | Square, radius `sm` | number only | `qstate-not-visited*` |
| Not answered (visited) | `danger-subtle` / `red-700`, border `red-500` | Square with notched bottom edge | number + small "–" | `qstate-not-answered*` |
| Answered | `green-600` / white | Rounded square, radius `md` | number + ✓ corner tick | `qstate-answered*` |
| Marked for review | `plum-600` / white | Circle | number | `qstate-marked*` |
| Answered & marked | `plum-600` / white | Circle | number + ✓ tick in a green dot at bottom-right | both |
| Current question (overlay) | 2 px `qstate-current-ring` outer ring | — | — | — |

Each tile is ≥ 40×40 px (44 on touch), keyboard-focusable, and its accessible name reads e.g. "Question 12, answered, marked for review". A legend with counts is always visible above the grid.

### 3.5 Chart palette

| Job | Tokens | Rule |
|---|---|---|
| Categorical (identity) | `chart-1` … `chart-8` (light: `#2A78D6 #EB6834 #1BAF7A #EDA100 #E87BA4 #008300 #6250D6 #E34948`; dark steps per tokens) | Fixed order, never cycled. Adjacent-pair CVD ΔE ≥ 8.4 in both modes (validated). For scatter/all-pairs forms use slots 1–3 only. Slots 3–5 are < 3:1 on white: direct labels or the table view are mandatory when they are used. |
| Sequential (magnitude: heatmaps, mastery heatmap) | `chart-seq-1` … `chart-seq-8` (indigo, light→dark; reversed in dark mode) | One hue, monotone lightness. |
| Ordinal bands (readiness 0–40/40–60/60–80/80–100; mastery weak/developing/strong) | `chart-band-1` … `chart-band-4` | Single indigo hue, validated ordinal (light end ≥ 2:1). Bands are **not** red/amber/green: a weak topic is a learning target, not a failure. |
| Status in charts (SLA breach, error rate over threshold) | `success/warning/danger-solid` | Reserved; always with icon + label. |
| Risk levels in charts (H5, ENG) | `risk-l0…l4-solid` | Only for risk-level series; always with level labels. |
| Chrome | `chart-grid`, `chart-axis`, `chart-label` | Hairline grid, recessive axis, labels ≥ 4.5:1. |

### 3.6 Typography

| Family | Font (Google Fonts, OFL) | Use |
|---|---|---|
| `font-display` | **Plus Jakarta Sans** 600/700/800 | Headings h1–h3, marketing display, metric values |
| `font-sans` | **Inter** 400/500/600/700 | All UI and body text, tables, forms, question text |
| `font-mono` | **JetBrains Mono** 400/500/700 | Code editor, compiler output, case refs (`SEC-2611-7KQ4MZ`), test timer |

Fallbacks include `Noto Sans Devanagari` and `Noto Sans Telugu` for the planned Hindi/Telugu UI. Self-host via `next/font/google` (subset `latin`, `latin-ext`; `display: swap`); never block render on fonts.

| Size token | rem / px | Line height | Roles |
|---|---|---|---|
| `xs` | 0.75 / 12 | 16 | captions, overline, table meta (never body) |
| `sm` | 0.875 / 14 | 20 | labels, dense tables, helper text |
| `base` | 1 / 16 | 24 | body, options, inputs (inputs never below 16 px on mobile to avoid zoom) |
| `md` | 1.125 / 18 | 28 | question stems, lead paragraphs |
| `lg` | 1.25 / 20 | 28 | h4, timer |
| `xl` | 1.5 / 24 | 32 | h3 (mobile h2) |
| `2xl` | 1.875 / 30 | 38 | h2 (mobile h1) |
| `3xl` | 2.25 / 36 | 44 | h1, metric values |
| `4xl`–`5xl` | 48–60 | 56–68 | marketing display only |

Numbers: `tabular-nums` in tables, timers, scores, prices and dashboards. Money formatted Indian style `₹1,23,456` (NFR-I18N-01); dates `3 Nov 2026, 10:15 IST`; relative times only for < 24 h ("3 min ago") with the absolute time in a tooltip.

### 3.7 Spacing, layout, radii, elevation

- **Spacing**: 4 px base (Tailwind default scale). Component padding 12/16 px; card padding 16 (mobile) / 24 (desktop); section gap 32–48 px.
- **Layout**: gutters 16 px (< 768) / 24 px; content max 72 rem (1152 px); prose max 45 rem; sidebar 264 px (collapsed 72 px); top bar 56 px; test bar 56 px; palette panel 288 px; drawer 448 px.
- **Grid**: 4 columns < 640, 8 columns 640–1023, 12 columns ≥ 1024.
- **Radii**: `sm` 4 (chips, palette tiles), `md` 6 (buttons, inputs), `lg` 8 (cards), `xl` 12 (dialogs, marketing cards), `full` (avatars, pills). Corporate feel: never above 16 px on product UI.
- **Elevation**: `shadow-xs` cards on canvas (light), `sm` sticky bars, `md` dropdowns, `lg` dialogs/drawers, `xl` command palette. In dark mode shadows add a 1 px light ring because shadows read poorly on dark.
- **Targets**: minimum 24×24 (SC 2.5.8); default interactive height 40 px; touch 44 px.

### 3.8 Motion

| Token | Value | Reduced motion | Use |
|---|---|---|---|
| `duration-fast` | 120 ms | 80 ms (opacity only) | hover, press, toggle |
| `duration-base` | 180 ms | 0 | dropdowns, tooltips, accordions |
| `duration-slow` | 240 ms | 0 | dialogs, drawers |
| `duration-slower` | 320 ms | 0 | page-level transitions (rare) |
| `ease-standard` / `enter` / `exit` | cubic-bezier | — | — |

No motion over 320 ms; no motion on the test runner except the autosave dot fade; skeletons are static under reduced motion; charts render without entry animation.

### 3.9 Breakpoints and z-index

Breakpoints: `xs` 360, `sm` 640, `md` 768 (coding workspace minimum), `lg` 1024 (sidebar persistent), `xl` 1280, `2xl` 1536.
z-index: base 0 · raised 10 · sticky 100 · sidebar 200 · topbar 300 · banner 400 · dropdown 1000 · overlay 1300 · drawer 1350 · modal 1400 · popover 1500 · toast 1600 · tooltip 1700 · skip-link 9999. The video watermark is inside the player's stacking context (above video, below player controls), never global.

### 3.10 Theming

Light is default. Dark follows `prefers-color-scheme` unless the user chose a theme (`<html data-theme="light|dark">`, stored in the profile and a cookie to avoid flash). The test runner and code editor follow the same setting; the editor's Monaco theme maps to `surface-sunken` / `fg` / chart hues for syntax. High-contrast and forced-colours: borders and focus remain visible (`forced-colors` rule in tokens.css); never rely on background colour alone for selection.

---

## 4. Layout shells

| Shell | Used by | Structure |
|---|---|---|
| **Public** | PUB-* | Top nav (logo, Courses, Placement, Companies, Pricing, Enquiries, Sign in, primary "Take free diagnostic"), content, footer (`surface-brand`) with policies, grievance officer, status link. Mobile: hamburger → full-height sheet. |
| **Portal** | `/app`, `/trainer`, `/evaluator`, `/studio`, `/admin` (Admin portal also contains `/mentor`, `/desk`, `/finance`, `/security`) | Left sidebar (persistent ≥ 1024, drawer below), top bar (search, notifications, help, portal switcher (FR-RBAC-002), avatar menu with theme + sign out). Global banners slot under the top bar (restriction, grace, maintenance, offline). Student portal uses a bottom tab bar on < 768 (Home, Learn, Practice, Tests, More). |
| **Focus** | Course player, practice session, timed test, coding workspace | No sidebar. Slim top bar with exit, title and context controls. Test runner has no global navigation at all (leaving requires confirmation). |
| **Status-only** | PUB-021 (`status_only` session) | Minimal header (logo, Help, Sign out), single column, no portal nav, no links to gated routes. |
| **Console** | Staff portals | Same as Portal but denser: tables at `sm` text, 40 px rows, sticky filters row, right-hand detail drawer for quick look. Staff session timeout warning modal at T-2 min (WCAG 2.2.1). |

---

## 5. Component specifications

Every component is built in `packages/ui` on Radix primitives with these tokens (implementation owned by frontend agents). States listed are mandatory. "Restricted" means no entitlement or no permission; "blocked" means account restriction L3/L4.

### 5.1 Button

| Variant | Visual | Use |
|---|---|---|
| Primary | `bg-brand text-brand-on`, hover `brand-hover` | One per view |
| Secondary | `surface` + 1 px `line-control` border, `text-fg` | Alternatives |
| Ghost | transparent, `text-fg-secondary`, hover `surface-hover` | Toolbars, tertiary |
| Danger | `bg-danger-solid text-danger-on-solid` | Destructive confirmations only (in dialogs) |
| Link | `text-fg-link` underline | Inline |

Sizes: sm 32 px (desktop dense tables only), md 40 px, lg 48 px (marketing, mobile primary). States: default, hover, active, **focus-visible** (`shadow-focus`), disabled (`opacity-disabled`, `aria-disabled`, reason in tooltip if non-obvious), **loading** (spinner replaces leading icon, label stays, width locked, `aria-busy`), **blocked** (rendered as secondary with a lock icon and text "Paused — see account status" linking to STU-026), **restricted** (lock icon + "Unlock" → access options). Never disable a submit button to signal validation errors; validate on submit and focus the first error.

### 5.2 Form fields

Label above input (never placeholder-only), optional hint below label, error below input with `danger-fg` + icon + text, `aria-describedby` wired. Inputs 40 px (44 touch), 16 px text. States: default, hover (border `fg-muted`), focus (`shadow-focus`), filled, error, disabled, read-only (`surface-subtle`, no border change), **autosaving/saved** for drafts. Password fields: show/hide toggle, paste allowed, passkey offered first (SC 3.3.8). OTP: single input with `autocomplete="one-time-code"`, `inputmode="numeric"`, 6 digits, resend with visible cool-down ("Resend code in 0:42"), and the rate-limit message when capped. DOB: three selects (day, month, year) or native date on mobile; never free text.

### 5.3 Alerts, banners and toasts

| Type | Placement | Persistence | Tokens |
|---|---|---|---|
| Inline alert | Inside content | Until resolved | `{status}-subtle` + 4 px left border `{status}-border` + icon + title + body + action |
| Global banner | Under top bar, full width | Dismissible only if informational; restriction / grace / offline banners are not dismissible | Same, compact 48 px |
| Toast | Bottom-right (desktop), bottom (mobile, above tab bar) | 6 s, pause on hover/focus; never for errors that need action | `surface-raised` + status icon |

Order of global banners when several apply: offline > restriction (L2–L4) > test-in-progress elsewhere > payment grace > maintenance > informational. Show max 2; the rest collapse into "2 more notices".

### 5.4 Cards and stat tiles

Card: `surface`, `rounded-lg`, 1 px `line` border (light) / ring (dark), padding 16/24, header (title `h4`, optional action link right). Stat tile: label (`sm`, `fg-muted`), value (`metric`, tabular), delta (icon ▲/▼ + text, coloured by meaning, never colour-only), freshness footnote ("Updated 02:00 IST"), method link where the number is derived (readiness, mastery, time). States: L (static skeleton of the same size), E ("No data yet" + why + action), X (inline error with retry and `request_id`).

### 5.5 Tables

Header `surface-subtle`, `sm` semibold; rows 48 px (40 dense for consoles); zebra off; hover `surface-hover`; selected `surface-selected` + checkbox; sticky header; numeric columns right-aligned tabular. Sorting via header buttons with `aria-sort`. Pagination (cursor-based "Load more" or page numbers in consoles). Mobile: tables collapse to stacked cards showing the 3 most important columns plus a "Details" disclosure; never horizontal-scroll whole pages (a scrollable table region with a visible scroll shadow is acceptable inside consoles). Empty: illustration-free sentence + action. Masked data (IP /24) uses `font-mono` and a "Reveal" button that opens the reason-code dialog.

### 5.6 Navigation

Sidebar items: icon + label, active = `brand-subtle` background + `brand-on-subtle` text + 3 px left indicator. Group headings `overline`. Badges for counts (grading queue, SLA breaches) use neutral badges; red badges only for overdue/breached. Breadcrumbs on depth ≥ 3 in consoles. Portal switcher shows only portals with a grant.

### 5.7 Dialogs and drawers

Dialog widths: sm 400, md 560, lg 720; full-screen sheet below 640. Title, body, actions (primary right on desktop; stacked full width on mobile). Focus trapped, `Esc` closes unless the dialog guards data loss (test submit, rebind) where `Esc` = cancel. Destructive dialogs restate the object and consequence in the title ("Sign out Rahul's iPhone?"). Drawers (448 px) for quick-look in consoles; never for multi-step forms.

### 5.8 Step-up authentication dialog

Triggered when an API returns `step_up_required` (window 5/10/15 min per role matrix §5). Modal, not a page redirect, so context is preserved; after success the original action re-submits automatically with the same Idempotency-Key. Staff: passkey first, TOTP second; SMS/email never offered. Students (contact/MFA changes): passkey, TOTP, or SMS OTP. Copy in §9.3.

### 5.9 Approval (second-person) components

- **Pending-approval banner** on the object: `info-subtle`, icon `users`, "Waiting for a second approver · requested by {name} · expires in 71 h". Requester sees "Withdraw request"; other eligible approvers see "Review and decide".
- **Approval card** (ADM-010, SEC-005, FIN-005): requester, action, diff (before → after), reason, evidence links, expiry countdown, Approve / Send back (reason required). The approve button is hidden (not just disabled) for the requester, with text "You requested this, so another approver must decide."
- **Decision form auto-flag**: "Requires second approval" checkbox shown checked and locked with explanation tooltip (unblock §7).

### 5.10 Video player (PLY-001)

VdoCipher player in a 16:9 frame, `surface-sunken` letterbox. **Watermark**: user's masked email or mobile + short user ID + date-time (IST), `overlay-watermark` text with `watermark-shadow`, 12–14 px, repositioned every 30–60 s to one of 6 safe zones; never covers captions (captions region reserved bottom 20%); rendered by the DRM player where possible (dynamic watermark), our overlay only as a fallback. Controls: play, ±10 s, speed (0.75–2×), captions (on by default when available), quality, transcript toggle, full screen. States: loading (poster + spinner), DRM unsupported (instructions with supported browsers), playback conflict (§9.5 dialog), token denied (restricted/blocked card replaces the frame), media processing, offline (cached transcript still readable), error (retry + `request_id`).

### 5.11 Test runner components (TST-002)

- **Timer**: `font-mono` `lg` bold tabular, in the test bar; format `HH:MM:SS` (>1 h) or `MM:SS`. Colours: default `timer`, ≤ 10 min `timer-warn` + clock icon, ≤ 1 min `timer-critical` + icon (no flashing). Live region announces only at 10, 5 and 1 min (polite, not assertive). Accommodation profile "no time-pressure warnings" suppresses colour changes and announcements. A "Hide timer" toggle reveals a compact "Time is running" pill.
- **Autosave indicator**: dot + text in the test bar: `Saving…` (neutral) → `Saved 3 s ago` (success dot) → `Offline — answers stored on this device` (warning dot, persistent) → `Reconnecting…` → `All answers synced` (success, 4 s). `role="status"`.
- **Reconnect banner**: full-width `warning-subtle`, non-dismissible while offline: "You're offline. Keep answering — your answers are saved on this device and will sync when you're back online. The timer keeps running on our server." On reconnect: `success-subtle` "Back online. 4 answers synced." for 6 s.
- **Question palette**: §3.4; collapsible side panel (≥ 1024) or bottom sheet (< 1024) opened by a "Questions 12/30" button.
- **Section tabs**: tab list with counts; locked sections (sequential) show a lock icon and "Opens after you submit Section A".
- **Submit confirmation (TST-003)**: counts by palette state, time left, a warning if unanswered > 0, primary "Submit section" / "Submit test", secondary "Back to test".

### 5.12 Coding workspace (COD-002)

Split view: statement (left, 40%, resizable via keyboard-accessible splitter) | editor (right) over a results panel (tabs: Testcases, Custom input, Results). Toolbar: language select, font size, theme, reset to starter (confirm), shortcuts help. Buttons: **Run** (secondary, `Ctrl+Enter`) and **Submit** (primary, `Ctrl+Shift+Enter`); while either is in flight both show loading and Submit is disabled (max 1 in-flight). Results: sample cases show input/expected/actual with verdict chips (AC, WA, TLE, MLE, RE, CE, each with icon + full name on hover); hidden cases show a **summary bar** ("17 of 20 hidden tests passed · Score 85/100") and a list "Case 7: Wrong answer" with no data. CE shows compiler output in mono. Queued state: "Queued — results will appear here" with elapsed time. Rate-limit: inline "You can submit again in 0:40". Autosave status at editor footer "Code saved 5 s ago". Below 768 px: notice "The coding workspace needs a larger screen (tablet or laptop). You can read the problem here." with statement still readable.

### 5.13 Level meter, risk badge, case reference

- **Risk badge**: pill `risk-lN-subtle` + `risk-lN-fg` text + icon + label; staff variant adds pips.
- **Level meter**: 4 pips 8×8 px, gap 4 px, filled with `risk-lN-border`, empty with `line-strong`; `aria-label="Level 3 of 4"`.
- **Case reference chip**: `font-mono`, `surface-subtle`, copy button ("Copied"). Never a link that exposes data without auth.

### 5.14 Readiness ring and mastery bar

Readiness ring: 120 px (dashboard) / 72 px (compact), 8 px stroke, track `line`, fill `brand`, centre value `metric` with `%`, label below (company name), footnote "Method" link → disclosure panel. "Insufficient data" state: dashed track, text "Practise 20 more questions to see this". Mastery bar: band chip (`weak`/`developing`/`strong`/`insufficient data`) using `chart-band-*` + weighted accuracy % next to it (analytics §6.2).

### 5.15 Empty, loading, error, blocked, restricted, offline (standard states)

| State | Pattern | Copy pattern |
|---|---|---|
| **L Loading** | Static skeleton matching final layout (no CLS); spinners only inside buttons and < 1 s waits; after 10 s show "Still loading…" + retry | — |
| **E Empty** | Sentence + primary next action; optional small aim-arc illustration on student screens only | "No tests assigned yet. When your trainer assigns one, it appears here. Meanwhile, try a free mock." |
| **X Error** | Inline card with title from problem+json `title`, one-line help, **Retry**, collapsible "Reference: {request_id}" with copy | "We couldn't load your results. Try again. If it keeps happening, share reference REQ-… with support." |
| **B Blocked (L3/L4)** | Global restriction banner + gated routes redirect to STU-026 (L3) or session ends to PUB-021 (L4) | Verbatim from `account-unblock-workflow.md` §1.3/§1.4 |
| **R Restricted (entitlement)** | Paywall card in place of the content: what it is, the access options from the upsell hint (plan, path), refund rule one-liner | "This lesson is part of the TCS NQT path. Get the path (₹1,499, 180 days) or All-access. Full refund within 7 days if you've used less than 20%." |
| **R Restricted (permission)** | 403 page, no hint whether the object exists | "You don't have access to this page. If you think you should, contact support." |
| **O Offline** | Global banner; disable actions that need the network with the reason; queue practice answers; test runner per §5.11 | "You're offline. We'll keep what you've done and sync it when you reconnect." |

---

## 6. Data-visualisation rules

1. **Pick the form by job.** Single headline → stat tile; part-to-whole of ≤ 4 → stacked bar (not pie); distribution (readiness, scores) → histogram/banded bar; change over time → line (≥ 6 points) or bars (< 6); ranking → horizontal bar sorted; matrix (topic × student) → heatmap with sequential indigo; Gantt (H3) → horizontal bars per device on a shared time axis.
2. **One y-axis only.** Never dual axes; use two charts.
3. **Categorical colours in fixed order**, following the entity (a batch keeps its colour across charts and filters). Max 8; more → "Other" or small multiples.
4. **Every chart has**: title stating the question ("Readiness for TCS NQT, CSE-A, 142 students"), unit, period, freshness, a legend when ≥ 2 series (plus direct labels when ≤ 4), hover tooltip with exact values, and a "View as table" toggle (keyboard and screen-reader path).
5. **Honest numbers**: show *n* (sample size) on cohort statistics; suppress groups below k-floors (`analytics.k_min.cohort` ≥ 10) with "Too few students to show"; label provisional values ("Provisional until integrity review completes"); label measurement version when comparing periods (analytics §3.12).
6. **Time metrics** use the five definitions from `analytics-event-schema.md` §3.11. Headline "Learning time" = M5. Never present M1 as study time; label it "Time signed in (approx.)". Show the "How we measure time" link wherever time appears.
7. **Mastery and readiness** use ordinal indigo bands, not traffic lights; the method disclosure panel is one click away.
8. **Security charts**: concurrency Gantt shows separation class S0–S3 with pattern + label (S3 = diagonal hatch + "S3 separated"), not colour only; IPs masked to /24 or /48; minors never appear in sharing views (show "No behavioural data for minor accounts — by design" where a reviewer opens one).
9. **No animation** on load; no 3D; no gauges except the readiness ring; gridlines hairline `chart-grid`.
10. **Dark mode** uses the dark chart steps (validated against `#161B25`), not inverted light colours.

---

## 7. Accessibility rules (WCAG 2.2 AA, NFR-ACC-01)

- **Contrast**: all text pairs ≥ 4.5:1, UI/graphics ≥ 3:1 — verified by `npm run check` in `packages/design-tokens` (190/190 required pairs pass in light and dark).
- **Keyboard**: everything operable by keyboard, including palette navigation (arrow keys within the grid, `Enter` to open), option selection (`1`–`4`/`A`–`D` shortcuts announced in help, off by default for screen-reader users), mark for review (`M`), next/previous (`N`/`P`), Run/Submit shortcuts. Shortcuts never single-key without a modifier unless they can be turned off (SC 2.1.4).
- **Focus**: visible 2 px ring with 2 px offset; never obscured by sticky bars or the reconnect banner (SC 2.4.11) — sticky regions add `scroll-padding-top`.
- **Targets** ≥ 24×24 (SC 2.5.8); default 40 px.
- **No drag-only** (SC 2.5.7): splitters, reorderable learning path and Gantt zoom have button alternatives.
- **Consistent help** (SC 3.2.6): Help link in the same place in every shell, including status-only.
- **Redundant entry** (SC 3.3.7): unblock form pre-fills case and devices; checkout pre-fills profile.
- **Accessible authentication** (SC 3.3.8): paste allowed, passkeys, no CAPTCHA on unblock or login (rate limits instead), OTP autofill.
- **Timing** (SC 2.2.1): session-expiry warning 2 min before idle timeout with "Stay signed in"; test timers are an essential exception but accommodation profiles add time automatically.
- **Live regions**: autosave (`status`, polite), timer milestones only, toasts (`status`), form errors on submit (focus moves to error summary).
- **Media**: captions on all lesson videos; transcripts; maths rendered with MathML/KaTeX with accessible output.
- **Motion**: respect `prefers-reduced-motion`; no flashing.
- **Language**: `lang` set per page; plain English at roughly grade 8 reading level for student copy.
- **Testing**: axe-core in CI (0 serious/critical), manual NVDA + TalkBack per release.

---

## 8. Content and voice

**Voice**: a calm, competent mentor. Short sentences. Second person. Active voice. Specific numbers and dates. No exclamation marks in system messages; at most one in celebratory moments (certificate earned).

| Do | Don't |
|---|---|
| "Learning access paused until 4 Nov, 10:15 IST" | "ACCOUNT BLOCKED!!" |
| "You're signed in on 2 devices. Sign out of one to continue." | "Too many logins detected." |
| "Full refund within 7 days if you've used less than 20% and no certificate was issued — discounted purchases included." | "*T&C apply" |
| "Couldn't save. We'll keep trying. Your answer is stored on this device." | "Error 500" |
| "Pattern-aligned practice" | "Actual TCS questions" |

**Formatting**: sentence case for headings and buttons; buttons are verbs ("Request a review", not "Submit"); dates `D Mon YYYY, HH:MM IST`; durations "7 days", "2 business days"; money `₹1,499` with "incl. GST"; device labels "Chrome on Windows · Hyderabad, Telangana (approx.)".

**Security copy rules** (from unblock doc §1): every message states what happened, why, what still works, what to do next, and the case reference. Explanations come from the rule's `explanation_key`, never raw signals. Minors never see sharing copy. No accusation.

---

## 9. Exact copy patterns

Template variables in `{braces}`. Strings live in the i18n catalogue under the keys shown.

### 9.1 Restriction (L1–L4, T-protect)

Use **verbatim** the copy in `docs/account-unblock-workflow.md` §1.1 (L1 banner), §1.2 (L2 "Confirm it's you"), §1.3 (L3 "Learning access paused until {ends_at_local}"), §1.4 (L4 "Your account is suspended pending review"), §1.5 (T-protect "We've secured your account"), §1.6 (signed-out device), §1.6a (session replay notice), §1.6b (bulk false-positive lift). Presentation:

| Level | Surface | Visual |
|---|---|---|
| L1 | Dismissible global banner (dismiss hides for 7 days, stays on STU-022/026) + email | `risk-l1` tokens, `info` icon |
| L2 | Interstitial page on the affected device (replaces player/test start); other routes show a compact banner "Confirm it's you to continue videos and tests on this device. [Confirm]" | `risk-l2` |
| L3 | Full-screen state on gated routes (STU-026 content) + persistent global banner "Learning access paused until {ends_at_local}. [See details]" on allowed routes | `risk-l3`, pause icon |
| L4 | PUB-021 status-only page | `risk-l4`, lock icon |

Short labels for badges and lists (`security.restriction.badge.*`): "All clear", "New activity", "Confirm it's you", "Paused until {date}", "Suspended — under review".
Support (SUP-003) lift button disabled tooltip: "Admin security review only".

### 9.2 Login, new device and limits

| Key | Copy |
|---|---|
| `auth.new_device.title` | **Confirm this new device** |
| `auth.new_device.body` | We sent a 6-digit code to {masked_contact}. Enter it to add "{device_label}" to your devices. Until then you can browse free content and your account settings. |
| `auth.new_device.limit_note` | You can have up to 3 devices. You're using {n} of 3. |
| `auth.device_limit.title` | **You have 3 registered devices** |
| `auth.device_limit.body` | Remove one to continue on this device. Removing a device counts as a replacement: {used} of 2 used in the last 30 days{reset_clause}. |
| `auth.device_limit.reset_clause` | ; the next one frees up on {date} |
| `auth.replacement_cap.body` | You've changed devices twice in 30 days. Your next change is available on {date}, or [contact support] and we'll help. |
| `auth.throttled.body` | Too many attempts. Try again in {mm:ss}, or [reset your password]. |
| `auth.invalid` | That email/mobile and password don't match. Check them and try again. |

### 9.3 Step-up (re-authentication)

| Key | Copy |
|---|---|
| `stepup.title` | **Confirm it's you** |
| `stepup.body.staff` | {action_label} needs a fresh check. Use your passkey or authenticator app. This keeps sensitive actions safe even if someone else gets to your unlocked computer. |
| `stepup.body.student` | To change your {contact_or_security_setting}, confirm it's you. |
| `stepup.cta.passkey` | Use passkey |
| `stepup.cta.totp` | Enter authenticator code |
| `stepup.cta.sms` (students only) | Send code to ••{last2} |
| `stepup.success` | Confirmed. Continuing… |
| `stepup.failed` | That code didn't work. Check the time on your phone and try again. |
| `stepup.expiry_note` | You won't be asked again for {window} minutes. |

`{action_label}` examples: "Approving a refund", "Deciding this case", "Exporting this report", "Changing device policy".

### 9.4 Session-cap chooser (FR-SES-006, risk engine §6.3)

> **You're signed in on 2 devices**
> Sign out of one to continue here.
>
> ( ) **Chrome on Windows** · Hyderabad (approx.) · active 2 h ago  *(pre-selected: oldest without a test in progress)*
> ( ) **Android app · Redmi Note 12** · Hyderabad (approx.) · active now · **Test in progress: TCS NQT Mock 3**
>     ↳ "Signing out this device would interrupt your test. We recommend choosing the other one."
>
> [Sign out selected and continue]  [Cancel]

Variants:
- `session_cap.all_attempts`: **You can't sign in here right now** — "Both of your other devices have a test in progress. Finish or submit the test there first, then sign in here. [Help]" (409 `session_cap_reached`).
- `session_cap.same_browser_note` (no prompt, toast after login): "We signed out your earlier session in this browser."
- Selected device signed out: toast "Signed out {device_label}." on this device; the other device shows §1.6 copy "You were signed out on this device. This happened because you signed in on another device. If this wasn't you, [secure your account]."

### 9.5 Playback conflict (PLY-005, FR-SES-007)

> **Video is playing on another device**
> Your plan allows 1 video at a time. "{other_device_label}" is playing *{lesson_title}*.
> [Stop it and play here]  [Not now]
> *Why only one?* One account is for one person ([Device policy]).

After takeover, the other device's player shows: **"Playback moved to another device"** — "This video is now playing on {device_label}. [Play here instead]". Repeated takeovers show no extra warning to the student (signals are logged server-side only for adults).

### 9.6 Test bound to another device (FR-SES-011)

> **This test is open on another device**
> *{test_title}* is in progress on {device_label}. The timer keeps running on our server: **{remaining}** left.
> [Continue on this device]  [Go back]
> *Continuing here closes the test on the other device. You can do this {rebinds_left} more time(s) for this test.*{otp_clause}

`{otp_clause}` (when level ≥ L2): " We'll send a code to confirm it's you." Proctored drive: "This is a supervised drive. Ask your trainer to allow switching devices." (button "Continue" hidden).

### 9.7 Timed-test crash recovery and offline (TST-004, FR-ASM-005/006)

| Key | Copy |
|---|---|
| `attempt.resume.title` | **Welcome back — your test is safe** |
| `attempt.resume.body` | We've restored {answered} answers. The timer kept running on our server, so you have **{remaining}** left. |
| `attempt.resume.pending` | {n} answers saved on this device are being synced… |
| `attempt.resume.synced` | All answers synced. |
| `attempt.resume.conflict` | We kept your most recent answer for {n} question(s) you changed on another device. |
| `attempt.resume.cta` | Resume test |
| `attempt.offline.banner` | You're offline. Keep answering — your answers are saved on this device and will sync when you're back online. The timer keeps running on our server. |
| `attempt.reconnecting` | Reconnecting… |
| `attempt.back_online` | Back online. {n} answers synced. |
| `attempt.autosave.saving` / `.saved` / `.failed` | Saving… / Saved {s} s ago / Couldn't save — retrying. Your answer is stored on this device. |
| `attempt.deadline_passed_offline` | Time ended while you were offline. We submitted the answers we had received by {deadline_local}. Answers made after that time couldn't be counted. [See submission] |
| `attempt.autosubmitted` | Time's up. Your test was submitted automatically at {time_local}. |
| `attempt.judge_outage` | Code results are delayed. Your submission is queued, and we've added {minutes} minutes to your time for the delay. |
| `attempt.warn.10` / `.5` / `.1` | 10 minutes left. / 5 minutes left. / 1 minute left. |

### 9.8 Unblock request status (8 states; STU-026, PUB-021)

Status tracker = vertical stepper (Submitted → Under review → Decision → Closed) with the current state card on top. Copy (`unblock.status.*`):

| State | Badge | Card copy |
|---|---|---|
| `draft` | Draft | "You've started a review request. It's saved for 7 days. [Continue]" |
| `submitted` | Submitted | "We've received your request {APL}. A reviewer will pick it up soon. First response within {first_response_sla}." |
| `under_review` | Under review | "A reviewer is looking at your case. We'll reply by {decision_due_local}." |
| `info_requested` | We need more information | "The reviewer asked: "{question}". Please reply by {due_local}. Your review is paused until you reply. [Reply]" |
| `escalated` | With senior reviewer | "Your case is with a senior reviewer for a second check. We'll reply by {due_local}." |
| `approved` | Approved | "Good news: we're lifting the pause. {next_steps}" (e.g. "Confirm it's you with a code, then your access returns.") |
| `rejected` | Not approved | "We've reviewed your request and the pause stays until {ends_at_local}. Reason: {student_summary}. You can appeal once, within 14 days. [Appeal] · You can also contact our Grievance Officer." |
| `closed` | Closed | by `closure_reason`: completed "Your access is back. Thanks for your patience."; rejected_final "This case is closed."; withdrawn "You withdrew this request."; no_response "We closed this request because we didn't hear back in 7 days. You can open a new one."; moot "The pause ended and you've confirmed your devices, so this request is closed." |

Form submit success: "**Request sent** — Reference {APL}. We'll update you here and by {channel}."

### 9.9 Other high-stakes strings

- Payment confirming: "Payment received by your bank. Confirming with Razorpay…" → after 15 min "This is taking longer than usual. We'll email you as soon as it's confirmed. Your money is safe. [Contact support]".
- Cancel subscription: "Cancel renewal? You keep access until {period_end}. No further charges." [Cancel renewal] [Keep subscription].
- Under-18 at signup: "Because you're under 18, a parent or guardian needs to agree before you can start. We'll send them a link. You can still browse free content."
- Export requiring approval: "Export requested. Another {approver_role} must approve it before it's ready. You'll be notified."

---

## 10. Iconography, imagery, illustration

- Icons: **Lucide** (ISC), 20 px in UI, 16 px in dense tables, 1.75 stroke. Icons accompany text; icon-only buttons have `aria-label` and tooltip.
- Imagery: real student and campus photography (Indian context, consented), natural light, no stock "thumbs up". Marketing only; product UI uses no photos except avatars and course thumbnails (16:9, 4 px radius).
- Illustrations: line-only, 2 px stroke, brand + accent, built on the aim arc; used for empty states and onboarding only.

---

## 11. Notes for frontend implementers

1. Import `@techdrona/design-tokens/tokens.css` once in the root layout; set `data-theme` on `<html>` from the user preference cookie before paint (inline script) to avoid flash.
2. Tailwind v3: `presets: [require("@techdrona/design-tokens/tailwind-preset")]`. Tailwind v4: `@import "@techdrona/design-tokens/tailwind-v4.css";` after `@import "tailwindcss";` and `tokens.css`. Do not use `dark:` variants for colours; semantic tokens already switch.
3. Use semantic names only (`bg-surface`, `text-fg-muted`, `border-line-control`, `bg-risk-l3-subtle`, `text-timer-warn`, `bg-qstate-answered`). Raw hex in components fails review.
4. Fonts: `next/font/google` with `Inter`, `Plus_Jakarta_Sans`, `JetBrains_Mono`; assign to `--td-font-sans/display/mono` via the `variable` option.
5. After changing `tokens.json`, run `npm run test` in `packages/design-tokens` (rebuilds CSS, re-checks contrast; exits non-zero on failure).
6. Copy strings in §9 are the canonical English source for the i18n catalogue.
