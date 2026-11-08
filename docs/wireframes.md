# Tech Drona LMS: Low-fidelity Wireframes (v1.0)

Owner: UX/UI Designer. Status: **Planned**. Screen IDs, routes and states come from `docs/product-requirements.md` §6; visual rules, tokens and exact copy from `docs/design-system.md` (§ references below as DS §x); routes from `docs/sitemap.md`.

> **Single-company mode (2026-11-06, [ADR-0015](architecture-decisions/ADR-0015-single-company.md)).** The college coordinator dashboard, seat pools, college invites, institution contracts and org tiles are removed. §15 now shows the Admin batches screens and the public corporate enquiry form. Finance, support, security and mentor screens are sections of the Admin portal (role `super_admin`).

Conventions: `[Button]` primary/secondary button · `( )` radio · `[ ]` checkbox · `▾` select · `▓` filled/progress · `░` track · `{var}` template value · `…` truncated. Desktop frames are ~1280 px, mobile ~360 px. Every authenticated screen also implements the standard states L/E/X/B/R(/O) (DS §5.15); only screen-specific states are listed.

Contents
1. Landing (PUB-001) · 2. Pricing (PUB-008) · 3. Signup, age gate, guardian consent (PUB-011, PUB-015) · 4. Login, new-device OTP, device limit, session-cap chooser (PUB-012) · 5. Student dashboard (STU-001) · 6. Course player + playback conflict (PLY-001, PLY-005) · 7. Practice question (PRC-003) · 8. Timed test (TST-001…005) · 9. Coding workspace (COD-002) · 10. Results & analytics (STU-010, STU-011) · 11. Devices & sessions (STU-022) · 12. Restricted account (STU-026 L3, PUB-021 L4) · 13. Unblock request form + status · 14. Trainer dashboard (TRN-001) · 15. Admin batches (`/admin/batches`) + corporate enquiry form (`/enquiries`) · 16. Security dashboard + queue (SEC-001, SEC-002/H1) · 17. Case detail (SEC-003) · 18. Policy settings (ADM-006) · 19. Finance dashboard (FIN-001) · 20. Admin dashboard (ADM-001) + approvals (ADM-010)

---

## 1. Landing — PUB-001 `/`

```
┌──────────────────────────────────────────────────────────────────────────────┐
│ ◠ Tech Drona   Courses  Placement  Companies  Pricing  Enquiries   Sign in [Take free diagnostic] │
├──────────────────────────────────────────────────────────────────────────────┤
│ (surface-brand band)                                                         │
│  Know exactly how ready you are                       ┌──────────────────┐   │
│  for your placement drive.                            │  ◠ readiness 58% │   │
│  Company-pattern mocks, explained practice and a      │  TCS NQT         │   │
│  readiness score with a published method.             │  Quant  ▓▓▓▓░ dev │   │
│  [Take the free 30-min diagnostic]  [See pricing]     │  Logic  ▓▓░░░ weak│   │
│  No card needed · Results in 30 minutes               └──────────────────┘   │
├──────────────────────────────────────────────────────────────────────────────┤
│ Prepare by company:  [TCS NQT] [Infosys] [Accenture] [Wipro] [Cognizant] [All →] │
├──────────────────────────────────────────────────────────────────────────────┤
│ What you get (3 cards)                                                       │
│ ┌ Practice with explanations ┐ ┌ Mocks that don't lose answers ┐ ┌ Readiness you can trust ┐ │
├──────────────────────────────────────────────────────────────────────────────┤
│ Rules we publish (published-numbers strip, DS §1)                            │
│  3 devices · 2 signed-in sessions · 1 video at a time · 2 device changes / 30 days │
│  Refund: full refund within 7 days if < 20% used and no certificate —        │
│  discounted purchases included.         [Device policy] [Refund policy]      │
├──────────────────────────────────────────────────────────────────────────────┤
│ Training your team? Tell us what you need.          [Send a corporate enquiry]│
├──────────────────────────────────────────────────────────────────────────────┤
│ Outcomes (with cohort + sample size) · Verified certificates (/verify/{id})  │
├──────────────────────────────────────────────────────────────────────────────┤
│ Footer (surface-brand): links · Grievance officer · Status                   │
└──────────────────────────────────────────────────────────────────────────────┘
```
Responsive: < 768 hero stacks (copy first, readiness card below, illustrative only); company chips become a horizontal scroll row with visible edge fade; cards 1-column. Nav → hamburger sheet; primary CTA stays in header as compact button.
States: L (static skeleton for company chips only; hero is static HTML), X (company chips fail → hide row). Performance: no hero video, no carousel; LCP is the headline text.
Signed-in visitor: header shows "Go to dashboard" instead of Sign in/CTA.

## 2. Pricing — PUB-008 `/pricing`

```
┌──────────────────────────────────────────────────────────────────────────────┐
│ Pricing                                    Prices include 18% GST.           │
│ Billing: ( ) Monthly  (•) Annual   — no fake discounts; annual = 12 × monthly − real saving shown │
├──────────────────────────────────────────────────────────────────────────────┤
│ ┌ Free ───────────┐ ┌ All-access ★ ─────────┐ ┌ Company path ────┐ ┌ Placement package ┐ │
│ │ ₹0              │ │ ₹{price}/year         │ │ from ₹{price}    │ │ ₹{price}          │ │
│ │ Diagnostic,     │ │ ≈ ₹{x}/month          │ │ 180 days         │ │ paths + 3 mentor  │ │
│ │ 10 free Qs/topic│ │ All courses, practice,│ │ One company:     │ │ interviews +      │ │
│ │ free courses    │ │ mocks, coding         │ │ pattern, mocks   │ │ resume review     │ │
│ │ [Start free]    │ │ [Get All-access]      │ │ [Choose company▾]│ │ [Get package]     │ │
│ │                 │ │ Renews {date}. Cancel │ │                  │ │                   │ │
│ │                 │ │ any time, 1 click.    │ │                  │ │                   │ │
│ └─────────────────┘ └───────────────────────┘ └──────────────────┘ └───────────────────┘ │
│ Refund rule (same text as Terms): Full refund within 7 days …  [Read policy] │
├──────────────────────────────────────────────────────────────────────────────┤
│ Compare plans (table: features × plans, ✓/— with text, sticky first column)  │
│ Buying for a team? → [Send a corporate enquiry] (/enquiries)                 │
│ FAQ (accordion): renewals, UPI AutoPay, GST invoice, device policy           │
└──────────────────────────────────────────────────────────────────────────────┘
```
Rules: no strike-through anchor unless a real time-bound sale (FR-COM-002), then show sale dates. "★" marks recommended with text "Most chosen", not urgency.
Responsive: plan cards become a vertical stack ordered Free → All-access → Path → Package; comparison table becomes per-plan accordions. Signed-in states: "Current plan" badge; minor without consent → CTA "Ask a parent to approve".

## 3. Signup, age gate and guardian consent — PUB-011, PUB-015

```
Step 1 of 3: Create your account                        Already have one? Sign in
┌──────────────────────────────────────────┐
│ Full name            [                 ] │
│ Email                [                 ] │
│ Mobile  +91 ▾        [          ]        │
│ Date of birth        [DD▾][Month▾][YYYY▾]│  hint: "Used to apply the right privacy protections."
│ Password             [               ][👁]│  hint: "15+ characters, or 8+ if you turn on 2-step." meter
│ ── or ──  [Create with passkey]  [Continue with Google]                       │
│ Consents (itemised, none pre-ticked):                                        │
│ [ ] I agree to the Terms and Privacy Notice (required)                       │
│ [ ] Send me study reminders by email/SMS (optional)                          │
│ [ ] Product news and offers (optional; hidden for under-18)                  │
│ [Create account]                                                             │
└──────────────────────────────────────────┘
Step 2: Verify mobile → OTP input [ _ _ _ _ _ _ ]  "Resend code in 0:42"  (rate-limit state)
```
**Age gate branch (age < 18 on signup date):**
```
┌──────────────────────────────────────────────────────────────┐
│ ⓘ A parent or guardian needs to agree                        │
│ Because you're under 18, a parent or guardian needs to agree │
│ before you can start. We'll send them a link.                │
│ Guardian's name   [            ]                             │
│ Guardian's mobile/email [            ]                       │
│ [Send request]       You can still browse free content.      │
│ Status: ○ Sent  ○ Opened  ○ Approved   [Resend] (max 3)      │
└──────────────────────────────────────────────────────────────┘
```
**Guardian side — PUB-015 `/guardian-consent/[token]`:** plain notice (what data, why, who sees it, how to withdraw) → verify guardian's own contact by OTP → choices `[I agree]` `[I don't agree]` → confirmation. States: expired link ("Ask {student} to send a new request"), declined, already consented.
Account in `pending_guardian_consent`: student portal shows only a waiting card + free content.
Responsive: single column at all sizes (max 480 px card on desktop). Errors inline + error summary at top on submit. Existing account → "An account with this email may already exist. [Sign in] or [Reset password]" (non-enumerating wording).

## 4. Login, new-device OTP, device limit, session-cap chooser — PUB-012

```
Sign in
┌──────────────────────────────────────┐
│ [Sign in with passkey]               │
│ ── or ──                             │
│ Email or mobile  [                 ] │
│ Password         [               ][👁]│
│ [ ] Remember this device (30 days)   │  students on trusted devices only
│ [Sign in]          Forgot password?  │
│ [Continue with Google] (students)    │
└──────────────────────────────────────┘
Throttled: inline "Too many attempts. Try again in 0:58, or reset your password." (live countdown)
MFA: "Enter the 6-digit code from your authenticator app" / passkey prompt / recovery code link
```
**New device (FR-SES-003):**
```
┌ Confirm this new device ─────────────────────────────────────┐
│ We sent a 6-digit code to ••••••••78. Enter it to add        │
│ "Chrome on Windows" to your devices.                         │
│ [ _ _ _ _ _ _ ]   Resend in 0:42 · Send by email instead      │
│ You can have up to 3 devices. You're using 2 of 3.           │
│ [Confirm]   [Skip for now — browse free content only]        │
└──────────────────────────────────────────────────────────────┘
```
**Device limit (FR-SES-004/005):**
```
┌ You have 3 registered devices ───────────────────────────────┐
│ Remove one to continue on this device. Removing a device     │
│ counts as a replacement: 1 of 2 used in the last 30 days.    │
│ ( ) Chrome on Windows · last used 2 Nov · Telangana (approx.)│
│ ( ) Android · Redmi Note 12 · today · Telangana              │
│ ( ) Safari on iPad · 12 Oct · Karnataka                      │
│ [Remove and continue]   [Cancel]                             │
└──────────────────────────────────────────────────────────────┘
Quota exhausted variant: list hidden; DS §9.2 replacement_cap copy + [Contact support].
```
**Session-cap chooser (FR-SES-006)** — exact copy DS §9.4:
```
┌ You're signed in on 2 devices ───────────────────────────────┐
│ Sign out of one to continue here.                            │
│ (•) Chrome on Windows · Hyderabad (approx.) · active 2 h ago │
│ ( ) Android · Redmi Note 12 · active now                     │
│     ⚠ Test in progress: TCS NQT Mock 3                        │
│       Signing out this device would interrupt your test.     │
│ [Sign out selected and continue]   [Cancel]                  │
└──────────────────────────────────────────────────────────────┘
All other sessions hold attempts → "You can't sign in here right now" (409 session_cap_reached).
```
Blocked branches: L4 → status-only `/account/restricted`; hard-disabled → generic invalid-credentials message (out-of-band email handles recovery). T-protect → "We've secured your account" flow.
Responsive: dialogs become full-screen sheets < 640; radio rows ≥ 56 px tall; device rows show label on line 1, meta on line 2.

## 5. Student dashboard — STU-001 `/app`

```
┌ Sidebar ─────┐┌ Top bar: search · 🔔 · ? · avatar ───────────────────────────────┐
│ Home ▌       ││ [Global banners slot: restriction / grace / offline]               │
│ My learning  │├────────────────────────────────────────────────────────────────────┤
│ Path         ││ Good evening, Ananya         TCS drive in 74 days · [Edit goals]   │
│ Practice     ││ ┌ Continue learning ─────────────────────┐ ┌ Readiness ───────────┐ │
│ Tests        ││ │ DSA Foundations · L12 Two pointers     │ │  ◠58%   ◠41%   ◠66%  │ │
│ Coding       ││ │ ▓▓▓▓▓▓░░░░ 62%        [Resume]         │ │  TCS   Infosys Accent.│ │
│ Analytics    ││ │ + 2 more cards                          │ │  How is this computed?│ │
│ Mentoring    ││ └────────────────────────────────────────┘ └───────────────────────┘ │
│ Certificates ││ ┌ Today's plan (why?) ───────────────────┐ ┌ Upcoming ─────────────┐ │
│ ──────────── ││ │ 1 Seating arrangement · 10 Qs  weak ⓘ  │ │ Accenture mock (CSE-A)│ │
│ Billing      ││ │   "Lowest mastery in TCS syllabus"     │ │ closes Sat 22:00      │ │
│ Account      ││ │ 2 Blood relations · lesson 8 min       │ │ Assignment 3 · due Mon│ │
│ status ✓     ││ │ 3 TCS sectional mock: Quant            │ │ Mock interview · Tue  │ │
│ Settings     ││ └────────────────────────────────────────┘ └───────────────────────┘ │
│ Help         ││ ┌ Skill snapshot (30 days, accuracy) ────┐ ┌ Learning time (M5) ───┐ │
└──────────────┘│ │ Quant   ▓▓▓▓▓▓▓░ 72%                   │ │ ▁▃▅▂▇▅▃  4 h 10 min   │ │
                │ │ Logical ▓▓▓▓░░░░ 48%  …                │ │ How we measure time   │ │
                │ └────────────────────────────────────────┘ └───────────────────────┘ │
                │ ┌ Recent results ─────────┐ ┌ Access & billing ─┐ ┌ Account status ┐ │
                │ │ TCS Mock 2 · 61/100 ·   │ │ All-access renews │ │ ✓ All clear     │ │
                │ │ 72nd pct (provisional)  │ │ 3 Dec · [Manage]  │ │ [Devices]       │ │
                │ └─────────────────────────┘ └───────────────────┘ └─────────────────┘ │
                │ Batch card (batch students): CSE-A · Trainer Dr. Suresh [Contact]     │
                └────────────────────────────────────────────────────────────────────────┘
```
States: first-run (no diagnostic) replaces Readiness + Today's plan with one card "Take the 30-minute diagnostic to get your plan [Start]"; expiring entitlement banner (≤ 14 days); grace banner; restriction banner (L1–L3) and Account status card shows the risk badge; minors: Today's plan without commercial items, no streak nudges.
Responsive: ≥ 1280 two-column grid as drawn; 768–1279 single main column with Readiness first row; < 768 bottom tab bar, cards stacked: Continue → Today's plan → Upcoming → Readiness → others. Readiness rings shrink to 72 px in a horizontal row.

## 6. Course player with watermark and playback conflict — PLY-001, PLY-005

```
┌ ← DSA Foundations   Lesson 12 of 40 · Two pointers         [Notes] [⋯] ┐
├─────────────────────────────────────────────────┬──────────────────────┤
│ ┌───────────────────────────────────────────┐   │ Contents   ▾ Module 3 │
│ │                                           │   │ ✓ 11 Sliding window  │
│ │      a•••@gmail.com · U7K2 · 3 Nov 21:14  │   │ ▶ 12 Two pointers    │
│ │      (watermark, moves every 30–60 s)     │   │ ○ 13 Practice set    │
│ │                                           │   │ ○ 14 Quiz            │
│ │                  ▶                        │   │                      │
│ │  [captions region reserved bottom 20%]    │   │ Resources (PDF)      │
│ └─▶ ⟲10 ⟳10 ──●──────── 04:12/12:30 1x CC HD ⛶┘   │                      │
│ Tabs: Overview | Transcript | Notes | Resources │                      │
│ [← Previous]                     [Mark complete / Next →] │             │
└─────────────────────────────────────────────────┴──────────────────────┘
```
**PLY-005 playback conflict** (modal over the frame; copy DS §9.5):
```
┌ Video is playing on another device ──────────────────────┐
│ Your plan allows 1 video at a time. "Android · Redmi     │
│ Note 12" is playing Two pointers.                        │
│ [Stop it and play here]   [Not now]                      │
│ Why only one? One account is for one person. Device policy│
└──────────────────────────────────────────────────────────┘
Other device after takeover: frame shows "Playback moved to another device … [Play here instead]".
```
States: DRM unsupported (frame replaced with supported-browser list), token denied/restricted (paywall card in frame), blocked L3 (frame shows "Learning access paused until {date}. [See details]"), L2 on this device (Confirm-it's-you interstitial), media processing, offline (transcript readable, "Video needs a connection"), preview mode PLY-004 (yellow-free info banner "Preview — not visible to students").
Responsive: < 1024 contents become a drawer ("Contents" button); < 768 player full width at top, tabs below, sticky Next bar at bottom; landscape → full-screen player. Watermark scales with frame (min 11 px rendered, opacity 35% + shadow).

## 7. Practice question — PRC-003 `/app/practice/sessions/[id]`

```
┌ ← Logical · Seating arrangement   Question 4 of 10   ▓▓▓░░░░░░░   [Bookmark ☆] [Report] ┐
├──────────────────────────────────────────────────────────────────────────────┤
│ Difficulty ●●●○○ · ~90 s · Tags: TCS, Infosys · Pattern-aligned practice     │
│                                                                              │
│ Eight people A–H sit around a circular table facing the centre. … Who sits   │
│ second to the left of D?                                         (text md)  │
│                                                                              │
│ ( ) A  E                                                                     │
│ ( ) B  F                                                                     │
│ ( ) C  G                                                                     │
│ ( ) D  H                                                                     │
│ [Check answer]                         [Show hint] (reduces mastery weight)  │
├──────────────────────────────────────────────────────────────────────────────┤
│ After check:  ✓ Correct  (success-subtle)  /  ✕ Not quite — the answer is C (danger-fg text + icon) │
│ Explanation (step by step, LaTeX/images) · [Watch video explanation]         │
│ [Try a similar question]                                  [Next question →]  │
└──────────────────────────────────────────────────────────────────────────────┘
Set complete summary: 7/10 · mastery Seating arrangement: developing → 62% weighted accuracy · [Retry incorrect] [Next set]
```
States: offline → answers queued ("Saved on this device — will sync"), Check still gives feedback from cached key only if the set was prefetched; else "Feedback will appear when you're back online". Minors: no hint-based nudges. R (premium topic) → paywall card.
Responsive: options become full-width 56 px rows; sticky bottom action bar with Check/Next; header compresses to "4/10" + progress bar.

## 8. Timed test — TST-001…TST-005

**TST-001 Instructions & system check**
```
TCS NQT Full Mock 3 · 90 min · 3 sections · Negative marking −0.25
Pattern table · Marking · Navigation: sections in order, no return
System check:  ✓ Browser supported  ✓ Connection stable (180 ms)  ○ Full screen (recommended) [Enter full screen]
Integrity notice: "We record events like leaving full screen or switching tabs. They're reviewed by a person and never penalise you automatically."
[ ] I've read the instructions        [Start test]   (disabled reason shown if not verified / window closed)
```
**TST-002 Attempt runner (desktop)**
```
┌ TCS NQT Mock 3 │ Section A: Quant ▾ │ ● Saved 3 s ago │   ⏱ 41:12   │ [Questions 12/30] [Submit section] ┐
├─[Reconnect banner slot, full width, non-dismissible while offline]──────────────────────┤
├──────────────────────────────────────────────────────┬─────────────────────────────────┤
│ Q12  · +1 / −0.25                    [ ] Mark for review │ Legend: □ Not visited 10        │
│ A train 240 m long passes a pole in 12 s …            │  ▭ Not answered 2  ■✓ Answered 15│
│                                                       │  ● Marked 2  ●✓ Answered+marked 1│
│ ( ) 18 km/h                                           │ ┌──┬──┬──┬──┬──┬──┐             │
│ ( ) 54 km/h                                           │ │1✓│2✓│3–│4●│5✓│6✓│  …          │
│ ( ) 72 km/h                                           │ ├──┼──┼──┼──┼──┼──┤             │
│ ( ) 90 km/h                                           │ │..│..│[12]│..│□ │□ │  current=ring│
│                                                       │ └──┴──┴──┴──┴──┴──┘             │
│ [Clear response]          [← Previous] [Save & next →]│ Calculator (if allowed)         │
└──────────────────────────────────────────────────────┴─────────────────────────────────┘
```
Autosave indicator states: Saving… → Saved {s} s ago → Offline — answers stored on this device → Reconnecting… → All answers synced (DS §5.11).
**Reconnect banner (offline):**
```
┌ ⚠ You're offline. Keep answering — your answers are saved on this device and will sync when you're back online. The timer keeps running on our server. ┐
On reconnect (6 s): ✓ Back online. 4 answers synced.
```
**Open on another device (FR-SES-011)** — read-only overlay (DS §9.6): "This test is open on another device … 38:40 left. [Continue on this device] [Go back] · You can do this 2 more times."
**TST-003 Submit confirmation:** "Submit Section A? Answered 25 · Not answered 3 · Marked 2 · Not visited 0 · Time left 12:04. You can't return to this section." [Back to test] [Submit section].
**TST-004 Resume after crash:**
```
┌ Welcome back — your test is safe ───────────────────────┐
│ We've restored 25 answers. The timer kept running on    │
│ our server, so you have 49:02 left.                     │
│ ⟳ 3 answers saved on this device are being synced… ✓    │
│ [Resume test]                                           │
└─────────────────────────────────────────────────────────┘
```
**TST-005 Submitted:** "Test submitted at 11:32 IST. Results: {immediately | on 5 Nov | after review}." [View results] [Back to tests].
States: time warnings 10/5/1 min (colour + icon + polite announcement); section locked; auto-submitted; deadline passed offline (DS §9.7); judge outage extension notice; accommodation profile (extra time shown as "Includes your extra 15 min").
Responsive: < 1024 palette becomes a bottom sheet opened by "Questions 12/30"; test bar wraps to two rows (title+timer / save status+submit) on < 640; options full-width; Previous/Next sticky at bottom. Timer always visible (sticky). No global navigation anywhere in the runner.

## 9. Coding workspace — COD-002 `/app/coding/[slug]` (and COD-004 inside tests)

```
┌ ← Problems  Two Sum Variants · Medium · Arrays      Python 3.11 ▾  Aa  ◐  ⟲ Reset  ? Shortcuts ┐
├──────────────────────────────┬──────────────────────────────────────────────────┤
│ Statement | Submissions | Editorial🔒 │ 1  def solve(nums, k):                │
│ Given an array … (Markdown+LaTeX)│ 2      …                                    │
│ Constraints: 1 ≤ n ≤ 10^5     │                                                │
│ Input / Output format         │                                                │
│ Sample 1  in: … out: …        │                             Code saved 5 s ago │
│                               ├──────────────────────────────────────────────────┤
│                               │ Testcases | Custom input | Results               │
│                               │ Results (after Submit):                          │
│                               │ ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓░░░ 17 of 20 hidden tests passed · Score 85/100 │
│                               │ Sample 1 ✓ Accepted 0.04 s · Sample 2 ✓          │
│                               │ Case 7  ✕ Wrong answer   Case 12 ⏱ Time limit exceeded │
│                               │ Case 19 ✕ Wrong answer   (hidden: no input/output shown) │
│                               │                    [Run  Ctrl+Enter] [Submit  Ctrl+Shift+Enter] │
└──────────────────────────────┴──────────────────────────────────────────────────┘
```
Run vs Submit: Run = samples + custom input, shows full I/O diff; Submit = hidden cases, shows summary + per-case verdicts only. Both buttons show loading during any in-flight request; Submit disabled while one submit is in flight.
States: running ("Running on 2 samples…"), queued ("Queued — results will appear here · 0:24"), compile error (mono compiler output, first error line link jumps editor), rate-limited ("You can submit again in 0:40"), judge outage, autosaved, editorial locked ("Unlocks after you solve or after 5 attempts").
Inside a test (COD-004): test bar + timer on top, palette includes coding questions, "last/best submission counts" note.
Responsive: 768–1023 statement and editor become tabs (Problem | Code | Results); < 768 small-screen notice (DS §5.12) with readable statement. Splitter has keyboard handles and "Reset layout" button.

## 10. Results and analytics — STU-010, STU-011

**STU-010 Results**
```
TCS NQT Mock 3 · submitted 3 Nov 11:32 · Score 61/100 · 72nd percentile (provisional ⓘ) · cohort: 1,284 first attempts
┌ Sections ─────────────────────────────────────────┐ ┌ You vs batch / topper ─────┐
│ Quant   18/30 ▓▓▓▓▓▓░░░  accuracy 72% · 28 min    │ │ horizontal bars, 1 axis     │
│ Logical 21/40 ▓▓▓▓▓░░░░  …                        │ │ (table view toggle)         │
│ Verbal  22/30 …                                   │ └─────────────────────────────┘
└───────────────────────────────────────────────────┘
Question review (per review matrix): filters All | Incorrect | Skipped | Marked; each row: Q#, your answer, correct (if released), time, [Explanation]
```
States: results pending release ("Results on 5 Nov 10:00 IST"), provisional rank, regraded notice ("Question 14's key was corrected on 4 Nov; your score changed 59 → 61"), invalidated (reason + appeal link).
**STU-011 Skill analytics**
```
Filters: Period [Last 8 weeks ▾]  Subject [All ▾]
┌ Company readiness ─┐ ┌ Strongest 3 / Weakest 3 ─┐ ┌ Percentile ───────────────┐
│ ◠58 TCS ◠41 Inf.   │ │ ↑ Percentages 82%         │ │ Batch CSE-A: 64th (n=142) │
│ "% of syllabus with│ │ ↓ Seating arr. weak       │ │ Platform 2027 grads: 71st │
│  mastery ≥ 60"     │ └───────────────────────────┘ └───────────────────────────┘
Mastery heatmap (topics × subtopics, indigo sequential, band label in each cell, table view)
Accuracy & avg time per topic (table) · Trend 8 weeks (line, one axis) · Learning time M5 by day
[How these numbers are computed] → method panel (mastery-1.0, measurement version tm-1.0)
```
States: insufficient data (< 20 questions) → "Answer 20 questions to unlock analytics" with progress; k-floor suppression ("Too few students in your batch to show a percentile").
Responsive: tiles stack; heatmap becomes per-subject accordions with band chips; charts keep table toggle.

## 11. Devices and sessions — STU-022 `/app/settings/devices`

```
Devices & sessions                                                Account status: ✓ All clear
┌ Our published limits ─────────────────────────────────────────────────────────┐
│ 3 devices · 2 signed-in sessions · 1 video at a time · 2 device changes / 30 days │
│ Verifying a device with a code does not exempt simultaneous use from two different │
│ home or office networks.  [Read the device policy]                             │
└───────────────────────────────────────────────────────────────────────────────┘
Device changes: 1 of 2 used · resets on 14 Nov
┌ Your devices (2 of 3) ───────────────────────────────────────────────────────┐
│ 💻 Chrome on Windows  "Home laptop" [Rename]  · This device                   │
│    Trusted · verified by SMS · first seen 2 Sep · last used now · Hyderabad   │
│ 📱 Android · Redmi Note 12 · Trusted · last used 2 h ago   [Remove device]    │
│ ⏳ Safari on iPad · Pending verification · [Verify] [Remove]                 │
└──────────────────────────────────────────────────────────────────────────────┘
┌ Signed-in sessions (2 of 2) ─────────────────────── [Sign out all other sessions] ┐
│ ● This session · Chrome on Windows · started 09:02 · active now · IP 49.37.x.x │
│ ○ Android app · started yesterday · active 2 h ago · ⚠ Test in progress  [Sign out] │
└──────────────────────────────────────────────────────────────────────────────┘
Login history (last 30 days): time · device · approx. location · result (success / wrong password / blocked)
Restriction history: none / list with case refs → STU-026
```
Confirm dialogs: "Remove Safari on iPad? It will be signed out and this counts as 1 of your 2 device changes." / "Sign out Android app? A test is in progress there; it will keep its time on our server but you'll need to reopen it."
States: quota exhausted (Remove buttons replaced by "Contact support to change a device"), current device pending verification (top banner + Verify), re-auth required (step-up dialog for device management if auth > 24 h).
Responsive: rows become cards; actions in an overflow menu "⋯" with full-text items; limits strip wraps to 2×2 grid.

## 12. Restricted account — STU-026 (L3) and PUB-021 (L4)

**STU-026 `/app/account-status` with L3 active** (copy verbatim unblock §1.3):
```
┌ (risk-l3-subtle panel, pause icon, pips ●●●○) ───────────────────────────────┐
│ Learning access paused until 4 Nov, 10:15 IST                                 │
│ Case reference: SEC-2611-7KQ4MZ [copy]                                        │
│ Our account-protection system paused video lessons, tests and practice on    │
│ your account for 24 hours. Here's why:                                        │
│ • {explanation_1}                                                             │
│ • {explanation_2}                                                             │
│ Our Terms allow one person per account, with up to 2 signed-in devices and 1 │
│ video at a time (Device policy).                                              │
│ What still works: your dashboard and progress, devices page, billing, support│
│ and privacy requests. Nothing has been deleted. …                            │
│ What happens next: when the pause ends, you'll confirm your identity …        │
│ Think this is a mistake? Ask for a review now. A person, not a computer, …   │
│ [Request a review]  [Review my devices]  [Read the device policy]            │
└──────────────────────────────────────────────────────────────────────────────┘
Review request: (status card if one exists — §13)        History: past restrictions with outcome
```
Other states of STU-026: all clear (L0 card "✓ All clear — no restrictions on your account" + published limits), L1 (notice + Review devices), L2 ("Confirm it's you" with [Send code]). Global banner on allowed routes: "Learning access paused until {date}. [See details]".
**PUB-021 `/account/restricted` (L4, status-only shell)** — copy verbatim unblock §1.4:
```
┌ ◠ Tech Drona                                             Help · Sign out ┐
│ 🔒 Your account is suspended pending review   (risk-l4 tokens, ●●●●)     │
│ Case reference: SEC-2611-7KQ4MZ                                          │
│ After reviewing activity on your account, our security team has         │
│ suspended access while the case is open. Reason: {reviewer_summary}.    │
│ You can still sign in to see this page, ask for a review, contact        │
│ support, manage billing (including cancelling renewals), and make privacy│
│ requests. Your data and purchases have not been deleted.                 │
│ [Request a review]  [Contact support]                                    │
│ ── Your request ── (status tracker §13)                                  │
│ ── Billing ── Subscription renews 3 Dec [Cancel renewal]  Invoices       │
│ ── Privacy ── [Request my data] [Delete my account]                      │
└──────────────────────────────────────────────────────────────────────────┘
```
Responsive: single column always; action buttons full width on mobile, stacked with primary first. No links to gated routes. Minors never see sharing copy (only deterministic caps / T-protect).

## 13. Unblock request form and status (STU-026 / PUB-021)

```
Request a review · Case SEC-2611-7KQ4MZ (read-only)              Step 1 of 1, autosaved (draft)
What happened? (choose all that apply)
 [ ] All devices are mine            [ ] A family member used my account
 [ ] I shared my login with a friend [ ] My account may have been hacked
 [ ] I was travelling / using VPN  [ ] Other
Your explanation (30–2,000 characters)  [                                          ] 0/2000
  hint: "Please don't include passwords or codes."
Devices you recognise (unticked devices will be signed out when you send this)
 [✓] Chrome on Windows · last used today · Telangana
 [ ] Android · Redmi 12 · 3 Nov · Karnataka
 [ ] None of these
Supporting document (optional, max 2 × 5 MB, PDF/PNG/JPG)  [Upload]
  "Do not upload ID documents unless we ask; if asked, mask all but last 4 digits."
Preferred contact: (•) In-app ( ) Email a•••@gmail.com ( ) SMS ••78   (verified only)
[ ] The information I've given is true. I understand one account is for one person.
[Send request]                          Response time: first reply within 24 h
```
Submit success: "Request sent — Reference APL-2611-3HX9RB. We'll update you here and by email."
**Status tracker** (copy DS §9.8):
```
APL-2611-3HX9RB · for SEC-2611-7KQ4MZ
┌ (current state card) Under review ───────────────────────────────────────────┐
│ A reviewer is looking at your case. We'll reply by 6 Nov, 10:00 IST.          │
└──────────────────────────────────────────────────────────────────────────────┘
● Submitted 3 Nov 21:40 ── ● Under review 4 Nov 09:10 ── ○ Decision ── ○ Closed
Messages (in-app thread with reviewer's student-visible notes) · [Withdraw request]
```
Info-requested state: question card + reply box (same validation) + due date; SLA paused note. Escalated: badge "With senior reviewer". Rejected: reason + [Appeal] (once, 14 days) + grievance officer link. Errors: rate limit ("You can send 3 requests in 30 days. Next available {date}."), one open request per case (form replaced by status).
Responsive: single column; checklist rows 48 px; sticky Send bar on mobile.

## 14. Trainer dashboard — TRN-001 `/trainer`

```
Trainer · Kavya                                         Batches: [All ▾]
┌ My batches ─────────────────────────────────────────────────────────────────┐
│ Batch    Students  Avg progress  Active 7d   Next test                       │
│ CSE-A    142       ▓▓▓▓▓░ 58%    71%         DSA Weekly 3 · Sat              │
│ CSE-B    138       ▓▓▓▓░░ 49%    64%         —                               │
└─────────────────────────────────────────────────────────────────────────────┘
┌ Grading queue ─────────┐ ┌ Live / upcoming tests ──────────┐ ┌ Integrity review ───┐
│ 23 pending · oldest 3 d│ │ DSA Weekly 3 · open             │ │ 2 flags · DSA W3    │
│ 4 overdue  [Grade →]   │ │ started 98 · submitted 61 · not │ │ review recommended  │
└────────────────────────┘ │ started 44  [Overrides] [Report]│ │ [Review →]          │
                           └─────────────────────────────────┘ └─────────────────────┘
┌ At-risk students (12) ──────────────────────┐ ┌ Topic weakness (batch, lowest 5) ───┐
│ Name · batch · progress · last active · reason│ │ DP 31% · Graphs 38% … (bars, labels)│
└─────────────────────────────────────────────┘ └─────────────────────────────────────┘
Content reports on my content (3) →
```
States: no batches (E: "You haven't been assigned a batch yet. An admin assigns batches."), live test counters refresh every 60 s with "Updated hh:mm". Integrity flags are labelled "advisory — review recommended", never "cheating".
Responsive: batch table → cards; widgets single column ordered Grading → Live tests → At-risk → rest.

## 15. Admin batches — `/admin/batches`, `/admin/batches/[batch_id]` and corporate enquiry — `/enquiries`

**Batches list** (Admin portal)
```
Batches                                                     [+ New batch]
Search [          ]  Status [Active ▾]
┌ Code ── Name ─────────────── Intake ─ Graduation year ─ Members ─ Status ─┐
│ CSE-A   Placement batch A     2026     2027              48        Active  │
│ JAVA-2  Java full stack 2     2026     —                 31        Active  │
└────────────────────────────────────────────────────────────────────────────┘
```
New batch (dialog): Code, Name, Intake (optional), Graduation year (optional) → [Create]. Errors: duplicate code ("A batch with this code already exists").

**Batch detail**
```
CSE-A · Placement batch A · Active                    [Edit] [Archive ⬆]
┌ Staff ─────────────────────────────────────┐ ┌ Add member ─────────────────────────┐
│ Trainer   Dr. Suresh       [Remove]        │ │ Search existing account by email    │
│ Evaluator Priya K.         [Remove]        │ │ [ a•••@gmail.com        ] [Add]     │
│ [Assign trainer] [Assign evaluator]        │ └─────────────────────────────────────┘
└────────────────────────────────────────────┘
┌ Members (48) ── Name ─────── Email ──────────── Joined ─── Status ── ─────┐
│ Anil R.   a•••@gmail.com   1 Nov   Active   [View] [Remove]               │
└──────────────────────────────────────────────────────────────────────────┘
```
Members are existing accounts added one by one (no roster import or invites). [View] opens `/admin/users/[user_id]`. States: empty batch ("No members yet. Add an existing account by email."), account not found (non-enumerating: "No eligible account matches that email"), archived batch (read-only).

**Corporate enquiry — PUB-010 `/enquiries`** (public shell, no sign-in)
```
Corporate and bulk enquiries
Training a team? Tell us what you need and we'll get back within 2 business days.
Name *            [                    ]
Company *         [                    ]
Work email *      [                    ]
Phone             [                    ]
Message *         [                                        ] 0/2000
[ ] I agree that Tech Drona may contact me about this enquiry (Privacy policy) *
[Send enquiry]
```
Validation inline + error summary on submit; success: "Thanks — we've received your enquiry."; rate-limited error: "Too many enquiries from this connection. Try again later." Responsive: single column, max 560 px card.

## 16. Security dashboard and suspicious-activity queue — SEC-001, SEC-002 (H1)

**SEC-001 `/security`** (tiles summarise H1–H12 + ENG; each tile links to its report)
```
Account security · risk.mode: ACTIVE · HC rules: ON · breaker: closed   [Kill switch ⬆]
┌ H1 Queue ───────┐┌ H5 Restricted ──┐┌ H6 Unblock ─────┐┌ H7 Review time ┐┌ H8 False positives ┐
│ 18 open         ││ L3 41 · L4 6    ││ 9 submitted     ││ 1st resp p50 6 h││ L3 FP 4.1% (30 d)  │
│ 3 SLA breached  ││ +7 in 24 h      ││ 2 info · 1 esc  ││ decision p90 52h││ ⚠ rule SH-07 v6: 3 │
└─────────────────┘└─────────────────┘└─────────────────┘└────────────────┘└────────────────────┘
┌ H3 Concurrent-use events (7 d) ┐┌ H4 Network clusters ┐┌ H10 Active sessions ┐┌ ENG Engine health ┐
│ stream conflicts / session-cap ││ campus NAT candidates││ 2,941 now · at cap  ││ L0–L4 over time    │
│ hits per day (bars)            ││ 4 · CGNAT watch      ││ 312                 ││ shadow vs active   │
└────────────────────────────────┘└──────────────────────┘└─────────────────────┘└────────────────────┘
H2 Device–account graph · H9 Repeat incidents · H11 Activity context · H12 Timeline → opened per case
```
**SEC-002 `/security/cases` (H1)**
```
Filters: Level [L2–L4 ▾] Family [Sharing ▾] Org [▾] Rule [▾] SLA [Breached ▾] Assignee [Me/Unassigned ▾]
Tabs: Open cases (18) | High score, no case (adults)
┌──────────────┬─────┬──────┬─────────┬──────────────────────────────┬──────┬─────────┬──────────┬──────┬────┐
│ Case         │Level│Score │HC rule  │Top explanations              │Age   │SLA      │Assignee  │Org   │Rpt │
├──────────────┼─────┼──────┼─────────┼──────────────────────────────┼──────┼─────────┼──────────┼──────┼────┤
│SEC-2611-7KQ4MZ│L3 ●●●○│78  │HC-01    │S3 overlap 4 days · 3 devices │ 20 h │ ⚠ 4 h   │ Neha     │GITAM │ ↺  │
│SEC-2611-…     │L2 ●●○○│52  │—        │stream conflicts · new device │  2 d │ ✓ 1 d   │ —[Claim] │ —    │    │
└──────────────┴─────┴──────┴─────────┴──────────────────────────────┴──────┴─────────┴──────────┴──────┴────┘
```
Rules: opening a per-user view asks for a reason code (case_review / appeal / takeover_investigation / qa_sample). Exports ⬆; per-user rows ⇄ second admin. Conflict check on Claim ("You applied this restriction, so another reviewer must take it").
Responsive: consoles target ≥ 1024; at 768–1023 table hides Score/HC/Org into a row expander; < 768 read-only card list with "Open on a larger screen to decide" (decisions disabled on phones).

## 17. Case detail — SEC-003 `/security/cases/[case_id]`

```
┌ Header ─────────────────────────────────────────────────────────────────────────────────┐
│ SEC-2611-7KQ4MZ · L3 Temporary restriction ●●●○ · Sharing · Under review · Neha        │
│ Restriction since 3 Nov 10:15 · ends 4 Nov 10:15 · Recommended: L3 · ⚑ High-risk: no    │
│ SLA: first response ✓ · decision due in 52 h        Linked request: APL-2611-3HX9RB     │
├─ Tabs: Explanation | Timeline (H12) | Concurrency (H3) | Devices graph (H2) | Submission | History | Notes ─┤
│ Explanation (must be opened before deciding ✓)                                         │
│  Ruleset v7 · HC-01 (qualifying days 4) · score 78                                      │
│  Category breakdown: overlap 54 · stream 14 · device churn 10                           │
│  • SH-01 S3 overlap, 2 devices, 3 Nov (12 buckets) +18 (decayed 16.2)                    │
│  • SH-03 stream conflicts ×5 in 7 d +14 …                                               │
│  Student sees: "Your account was active on two devices in different locations…"         │
│ Concurrency Gantt (H3): device rows × time; overlaps hatched + label S0–S3; /24 nets    │
│   [Reveal full IP] → reason dialog (audited)                                            │
│ Timeline (H12): logins · sessions · net changes · caps · signals · evaluations ▁▃▇ · OTP │
├─────────────────────────────────────────────────────────────┬───────────────────────────┤
│ Student submission: "A family member used my account" …      │ DECISION PANEL  ⬆          │
│ Devices recognised: Chrome/Win ✓  Android ✗ (revoked)       │ Outcome ▾ [Lift (warning)  │
│ Attachments: 1 (sandboxed viewer, download off)              │   Lift — false positive    │
│                                                              │   Reduce to L2 · Uphold    │
│                                                              │   Convert to L4]           │
│                                                              │ Rationale (internal) [   ] │
│                                                              │ Student summary (≥ 50 ch.) │
│                                                              │ [                        ] │
│                                                              │ Preview as student ▸       │
│                                                              │ Conditions/exception ▾     │
│                                                              │ [✓] Extension credit (FP)  │
│                                                              │ [✓🔒] Requires second      │
│                                                              │   approval — high-risk lift│
│                                                              │ [Submit for approval]      │
└─────────────────────────────────────────────────────────────┴───────────────────────────┘
```
**Second-approval state** (after submit, or for the second reviewer):
```
┌ ⓘ Waiting for a second approver · proposed by Neha 4 Nov 11:02 · expires in 71 h ──────┐
│ Proposal: Lift — false positive · extension credit 2 days · summary (as student sees) │
│ Neha sees: [Withdraw proposal]                                                         │
│ Second reviewer (≠ proposer, ≠ applier) sees: [Approve ⬆]  [Send back] (reason required)│
└───────────────────────────────────────────────────────────────────────────────────────┘
Decided state: decision record (outcome, by, approved_by, time), panel read-only; "No delete".
```
Minor case: Concurrency/Graph tabs show "No behavioural data for minor accounts — by design"; only deterministic cap events.
Guard rails: Submit disabled with reason until Explanation and Timeline tabs were opened ("Open Explanation and Timeline before deciding"); no bulk decisions.
Responsive: ≥ 1280 two-column with sticky decision panel; 1024–1279 decision panel becomes a bottom sheet "Decide"; < 1024 read-only.

## 18. Policy settings — ADM-006 `/admin/policies`

```
Policy settings                                     Pending approvals (1) → ADM-010
Keys per account-security-and-risk-engine.md §3.2.
Category: [Devices & sessions] [Refunds] [Grace] [OTP limits] [Assessment] [Risk engine]
┌ Devices & sessions ─────────────────────────────────────────────────────────────────┐
│ Key                               Current   Proposed   Effective           Status    │
│ devices.student.max_trusted       3         [3   ]                                    │
│ sessions.student.max_concurrent   2         [2   ]                                    │
│ playback.max_concurrent_streams   1         [1   ]                                    │
│ devices.student.max_replacements_per_30d 2  [3   ]     00:00 IST 5 Nov  ⏳ Pending ⇄  │
│ assessment.rebind_requires_otp_at_level  L2 [L2 ▾]                                    │
└─────────────────────────────────────────────────────────────────────────────────────┘
Change summary: replacements 2 → 3 · reason [Exam season…] · affects published Device policy text ⚠
[Propose change ⬆]   → "Another super admin must approve this. Requests expire after 72 h."
History: who, what, when, approved by, effective (audit-linked)
```
States: pending approval (row locked, banner with requester + expiry; requester can withdraw), scheduled effective date, validation error (out of allowed range shown inline, e.g. "Max 100"), published-text impact warning when a public number changes (Device policy page + strip must update).
Responsive: desktop-first; < 1024 rows become cards with Current/Proposed side-by-side.

## 19. Finance dashboard — FIN-001 `/finance`

```
Revenue · Period [MTD ▾]  Data: live (payments), 02:00 IST (aggregates)
┌ GMV ─────────┐┌ Net revenue ───┐┌ Refunds ─────────┐┌ MRR ──────────┐┌ Payment success ┐
│ ₹18,42,300   ││ ₹15,61,200     ││ ₹42,900 · 31     ││ ₹6,12,000     ││ 96.4% ▼0.3 pt   │
│ ▲ 12% vs Oct ││ ex-GST         ││ 98.6% in SLA     ││ 1,402 subs    ││ UPI 97.1%       │
└──────────────┘└────────────────┘└──────────────────┘└───────────────┘└─────────────────┘
┌ Revenue by day (bars; one axis; table toggle) ─────────────┐ ┌ Failed payments (7 d) ─────┐
└────────────────────────────────────────────────────────────┘ │ reason · count · [View]    │
┌ Refund queue ─────────────────────┐ ┌ Invoices ──────────────────┐ └────────────────────────────┘
│ 6 eligible · 2 ineligible (override⇄)│ │ 214 issued MTD · GST export │ ┌ Reconciliation ───────────┐
│ oldest 3 business days [Open →]    │ │ 2 credit notes pending     │ │ 4 mismatches [Resolve →]  │
└────────────────────────────────────┘ └────────────────────────────┘ └───────────────────────────┘
Pending approvals I can decide (≠ my requests): coupon 60% off · goodwill refund ₹4,999
```
States: webhook lag banner (> 5 min) "Payment confirmations are delayed; orders may show 'confirming'"; approvals require step-up; values ₹ Indian grouping, tabular.
Responsive: KPI tiles 2-up on tablet, 1-up on phone; charts keep table toggle.

## 20. Admin — ADM-001 `/admin` and ADM-010 approvals

```
Platform overview                                   Audit chain: ✓ verified 02:10 IST
┌ Users ──────────────┐┌ Revenue snapshot ─┐┌ Batches ─────────────┐┌ Platform health ───────┐
│ 98,214 registered   ││ GMV today ₹84,200 ││ 12 active            ││ API p95 212 ms ✓        │
│ DAU 9,812 · minors  ││ MRR ₹6.12 L       ││ 486 batch students   ││ autosave err 0.08% ✓   │
│ 6.1%                ││ pay success 96.4% ││ 3 new enquiries      ││ judge wait 12 s ✓       │
└─────────────────────┘└───────────────────┘└──────────────────────┘│ webhook lag p95 40 s ✓ │
┌ Content ───────────┐┌ Security summary (counts only) ┐┌ Governance ───┘────────────────┐
│ completeness 91%   ││ L3 41 · L4 6 (7 d) · open 18   ││ Approvals pending 4 · privacy  │
│ 12 error reports   ││ appeals overdue 1               ││ requests due ≤ 7 d: 2          │
└────────────────────┘└────────────────────────────────┘└────────────────────────────────┘
```
**ADM-010 Approvals queue**
```
Filter: Type [All ▾] Status [Pending ▾]
┌ Change policy · devices.student.max_replacements_per_30d 2 → 3 ─────────────────────────────────┐
│ Requested by Sanjay R. · 4 Nov 10:12 · expires in 70 h · reason "Exam season…"       │
│ Diff (before → after) · effective 00:00 IST next day · impact: Device policy text     │
│ [Approve ⬆]  [Send back]                (hidden for requester: "You requested this,  │
│                                           so another approver must decide.")          │
└──────────────────────────────────────────────────────────────────────────────────────┘
```
Break-glass (ADM-012): active state shows a persistent `danger-subtle` top banner with countdown in every console screen ("Break-glass session active — 42:10 left · all views are recorded").
States: audit chain break detected → `danger` banner + link to ADM-008; approvals expired (greyed, "Expired — request again").
Responsive: tiles 2-up/1-up; approval cards full width; Approve requires ≥ 1024 or confirm dialog on tablet.

---

## Appendix: cross-screen behaviour checklist

| Behaviour | Screens |
|---|---|
| Global restriction banner (L1–L3) | All `/app` routes; hidden inside status-only shell |
| Offline banner | All; test runner uses its own reconnect banner |
| Step-up dialog | STU-021, STU-022 (device mgmt when auth > 24 h), all staff sensitive actions |
| Second-approval banner | ADM-005/006/010, FIN-003/005, SEC-003/005/006 |
| Reason-code prompt | SEC-003 tabs, SEC-007, SUP-003 (without ticket), "Reveal full IP" |
| Method/measurement links | STU-001, STU-011, PRC-005, TRN-001 (time and readiness widgets) |
| Provisional labels | STU-010, STU-001 recent results, TRN-011 |
