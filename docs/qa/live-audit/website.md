# Live audit: public website and its LMS links

- **Date:** 2026-11-14
- **Website:** https://techdrona-website.web.app
- **LMS:** https://techdrona-lms-app.web.app
- **Method:** Playwright on Cloud Build (`qa/live-e2e`), live sites only. No QA login was used. No form was submitted: fields were only focused and blurred, and buttons were checked to exist.
- **Spec:** `qa/live-e2e/tests/audit-website.spec.ts`

## Runs

| Build | Scope | Result |
|---|---|---|
| `3f334141-762c-473c-a39d-f0a9c32cc65c` | crawl, LMS links, responsive and forms on all 7 devices | 29 passed, 6 failed (menu test blocked by finding 2) |
| `99ebf028-a328-4e6b-ac26-907533cd24ae` | menu test only, with the cookie bar answered and the popup snoozed | 7/7 passed |

- **Findings (JSON):** `qa/live-e2e/runs/<build>/findings/website-*.json`
- **Screenshots:** `gs://td-qa-reports-f4fe3/runs/<build>/artifacts/` (deleted after 30 days). A sample was copied to `qa/live-e2e/runs/3f334141-762c-473c-a39d-f0a9c32cc65c/shots/`.
- **Website source paths** are relative to `d:\company website\TECH DRONA LMS\tech drona`.

## Summary

The website is in good shape:
- No broken internal links.
- No horizontal scroll on any of the 7 devices.
- Every page has its own title, one meta description, a canonical link and one h1.
- All 60 in-page `#hash` targets exist.
- All external and brochure links return 200.
- No page links to the old VM (sslip.io).
- Every website link into the LMS works: Login goes to `/continue`, which goes to `/login`; `/learn` goes to `/app` and `/teach` to `/trainer`.
- The course-status API answers with the right CORS header, and every course page shows the status it returns (all "Coming soon").
- The mobile menu opens, closes (Escape, the X button and the scrim), locks page scroll and reaches all 36 items on every device.

The real problems:
1. `catalog.json` has no CORS header, so the LMS cannot read it.
2. The lead popup opens on top of the open menu.
3. The cookie bar clips its "Accept cookies" button on a 320 px phone.
4. Unknown URLs are "soft 404s": they return HTTP 200.
5. The canonical URL, OG and sitemap use the domain `techdrona.in`, while the domain plan is `techdrona.com`.
6. There are no Terms or Refund pages on a site that takes payments.

## Page inventory (desktop crawl, build 3f334141)

Load = time to the `load` event, then to network idle, in ms. Every page answers HTTP 200, because the site is an SPA with a rewrite to `index.html`.

| Path | Lands on | Title | Load / idle ms | Notes |
|---|---|---|---|---|
| `/` | `/` | Tech Drona \| Software, AI, Cloud, Training & Technology Procurement | 1951 / 1975 | Hero video slideshow |
| `/solutions` | `/solutions` | Software Development, CRM & Web Applications \| Tech Drona | 1722 / 4227 | 24 images; decorative text 6.6 px |
| `/software-solutions` | same page | same as `/solutions` | 1004 / 2143 | Canonical points to `/solutions` (correct) |
| `/training` | `/training` | Training, Internships & Careers \| Tech Drona | 960 / 1663 | 82 text elements under 12 px |
| `/courses` | `/courses` | Courses \| Tech Drona | 1036 / 3094 | 8 course cards, all "Coming soon" |
| `/courses/nextgen-career-accelerator-2026` | same | NextGen Career Accelerator 2026 \| Tech Drona | 527 / 2241 | Waitlist form ("Notify me when it opens") |
| `/courses/python-full-stack-development` | same | Python Full Stack Development \| Tech Drona | 614 / 1017 | Waitlist and brochure |
| `/courses/java-full-stack-spring-boot-microservices` | same | Java Full Stack Development with Spring Boot and Microservices \| Tech Drona | 795 / 2387 | |
| `/courses/mern-stack-development` | same | MERN Stack Development \| Tech Drona | 610 / 1091 | |
| `/courses/mean-stack-development` | same | MEAN Stack Development \| Tech Drona | 525 / 992 | |
| `/courses/generative-ai` | same | Generative AI \| Tech Drona | 799 / 1233 | |
| `/courses/agentic-ai` | same | Agentic AI \| Tech Drona | 575 / 2168 | |
| `/courses/aws-and-devops` | same | AWS and DevOps \| Tech Drona | 850 / 1253 | |
| `/apply/internship` | same | Apply for an internship \| Tech Drona | 1125 / 1960 | 8 tracks, form |
| `/verify` | same | Verify a certificate or letter \| Tech Drona | 764 / **15776** | Network idle late: Firestore listener |
| `/payment/status` | same | Payment status \| Tech Drona | 917 / 1483 | "We couldn't confirm the payment" (expected without a reference) |
| `/pay-installment` | same | Pay an installment \| Tech Drona | 904 / 1530 | Form |
| `/my-registrations` | `/pay-installment` | Pay an installment \| Tech Drona | 653 / 1265 | Redirect (intended) |
| `/register` | `/courses/nextgen-career-accelerator-2026#register` | NextGen Career Accelerator 2026 \| Tech Drona | 445 / 2342 | Redirect (intended) |
| `/procurement` | same | Technology Procurement & Lab Setup \| Tech Drona | 896 / 2497 | Enquiry form |
| `/recruitment` | same | Recruitment & Workforce Solutions \| Tech Drona | 1218 / 2805 | Enquiry form |
| `/projects` | same | Products & Client Projects \| Tech Drona | 675 / 2449 | 6 external client sites (all 200) |
| `/about` | same | About Us \| Tech Drona | 739 / 1884 | |
| `/contact` | same | Contact \| Tech Drona | 822 / 1893 | Enquiry form |
| `/privacy` | same | Privacy Policy \| Tech Drona | 661 / 1666 | The only legal page |
| `/unsubscribe` | same | Unsubscribe \| Tech Drona | 571 / 1244 | Error message without a token (expected) |
| `/about.html`, `/products.html` | `/about`, `/projects` | | ~575 | Old URLs redirect correctly |
| `/blog`, `/resources`, `/terms`, `/this-page-does-not-exist-qa` | same | Page not found \| Tech Drona | ~400–700 | 404 page renders, but HTTP is **200** (finding 4) |
| `/learn`, `/learn/x`, `/teach` | LMS `/login?next=/app` or `/login?next=/trainer` | Log in · Tech Drona | | Work |
| `/admin` | website `/admin` | Back office \| Tech Drona | | The old website back office is still served (`X-Robots-Tag: noindex`) |

There is no blog, resources or terms page, and nothing links to one. Those URLs were probed on purpose.

**Static files:**
- `/robots.txt`, `/sitemap.xml`, `/site.webmanifest`, `/favicon-32.png`, `/apple-touch-icon.png`, `/og-image.jpg` and `/catalog.json` all return 200 with the right content type.
- `/favicon.ico` returns 200 `text/html` (the SPA shell).

## Website → LMS links (build 3f334141, desktop)

| Link | Where | Result |
|---|---|---|
| Header "Login" → `https://techdrona-lms-app.web.app/continue` | All pages (`Layout.jsx:207,261`); "Login to Tech Drona" in the mobile menu (`Layout.jsx:192`) | Lands on LMS `/login?next=%2Fcontinue`, h1 "Log in", no console errors |
| `/learn`, `/teach` (old portal URLs) | `App.jsx:150-152` `LmsRedirect` | LMS `/login?next=/app` and `/login?next=/trainer` |
| LMS `/app`, `/trainer`, `/continue`, `/login` | | 200, sign-in page |
| LMS `/register` | | 200 "Register for a course", but **console shows the catalog.json CORS error** (finding 1) |
| Register buttons (`${LMS}/register/<slug>`) | `CourseRegistration.jsx:687` | Not rendered today: the LMS reports every course as `coming_soon`, so course pages show the waitlist form instead. Correct behaviour. |
| `GET ${LMS}/api/public/courses/status` from the website origin | `lib/courseStatus.js:55` | 200, `Access-Control-Allow-Origin: https://techdrona-website.web.app`, 8 slugs all `coming_soon`. Badges on `/courses` and on each course page say "Coming soon", which matches. |
| Links to the old VM (`sslip.io`) | All crawled pages | **None.** sslip.io is still in source, but not in links (finding 15) |

## Findings

### 1. HIGH: `catalog.json` has no CORS header; the LMS dashboard and `/register` cannot load it
- **Device:** all
- **URL:** https://techdrona-website.web.app/catalog.json, fetched from https://techdrona-lms-app.web.app
- **Evidence** (`findings/website-lms-links.json` → `catalogJson`, `catalogFromLmsOrigin`):
  - The file exists and is real JSON: 200, `content-type: application/json`, 8 courses, `generated_at` 2026-11-13T13:35Z. `scripts/build-catalog-json.mjs` writes it to `dist/` during `npm run build`.
  - The response headers hold no `Access-Control-Allow-Origin`. The OPTIONS reply has none either.
  - A browser `fetch()` from the LMS origin fails with "blocked by CORS policy: No 'Access-Control-Allow-Origin' header is present". The same error appears in the console on LMS `/register`, besides the student dashboard.
  - The LMS caller is `apps/lms-spa/src/features/site-catalog/lib/catalog.ts:359` (GET with an `accept: application/json` header). That is a CORS "simple request", so only the response header is missing; no preflight handling is needed.
- **Source:** `firebase.json` → `hosting.headers` (line 46). No rule matches `/catalog.json`.
- **Fix:** add this block to `hosting.headers` in `tech drona/firebase.json`:

  ```json
  {
    "source": "/catalog.json",
    "headers": [
      { "key": "Access-Control-Allow-Origin", "value": "*" },
      { "key": "Cache-Control", "value": "public, max-age=300" }
    ]
  }
  ```

  `*` is safe: the file is public course data and the fetch sends no credentials. It also keeps working after the move to `lms.techdrona.com`. Hosting cannot echo the request origin, so a fixed value such as `https://techdrona-lms-app.web.app` would have to be changed at the domain cut-over. The shorter cache (instead of the default `max-age=3600`) lets course edits reach the LMS sooner. Then rebuild and redeploy the website (`npm run build`, which regenerates `dist/catalog.json`).
- **Note:** `tech drona/catalog.json` at the repo root (dated 11 Nov) is a stale copy. It is not deployed and can be deleted to avoid confusion.

### 2. MEDIUM: the lead popup opens on top of the open menu and blocks it
- **Device:** all 7. Seen on desktop, laptop, tablet, tablet-landscape, iPhone 13 and iPhone SE. Pixel 7 finished before the timer fired.
- **URL:** any page not in `NO_POPUP`, for example `/`
- **Evidence:**
  - Build 3f334141, test "navigation menu": `.mp-sec-btn` click timed out because "`<div class="lp">` … intercepts pointer events".
  - Screenshot: `shots/navigation-menu-phone-small__test-failed-1.png`. The "Let's stay in touch" sheet covers the open menu.
  - `findings/website-nav-phone-android.json` → items: 28 of 36 menu items "covered by BUTTON.lp-google".
  - The popup also opened over ordinary pages during the responsive run (`/verify` desktop and laptop, `/training` tablet-landscape and Pixel 7). On phones it is a bottom sheet covering 100 % of the viewport.
- **Source:**
  - `src/components/VisitorKit.jsx:79-83`: the timer is 20 s when the cookie bar is unanswered, 4 s after it is answered, and it ignores other dialogs.
  - z-index: `.lp` is 270 (`src/styles/global.css:5492`) and `.mp` is 250 (`global.css:5330`).
- **Fix:**
  - In the popup effect, do not open while the menu or another modal is open: check `document.documentElement.classList.contains("nav-locked")` or `document.querySelector('[aria-modal="true"]')`. Re-check when the menu closes (pass `open` from Header via context or an event).
  - Consider showing it only after real engagement (scroll depth, or a second page view) rather than a timer.
- **Retest:** with the popup snoozed (build 99ebf028), the menu passes everywhere: it opens, scroll is locked, all 36 items are reachable and not covered, it closes with Esc, X and the scrim (tablet and desktop), and a link navigates and closes the panel.

### 3. MEDIUM: the cookie bar clips "Accept cookies" on small phones and covers a fifth to a third of the screen
- **Device:**
  - Clipping: iPhone SE (320 px).
  - Coverage: Pixel 7 19 %, iPhone 13 24 %, iPhone SE 31 %, tablet-landscape 20 %.
- **URL:** every page, until the visitor answers
- **Evidence:**
  - `shots/responsive-layout-phone-small__top-_.png`, `…__top-_courses_nextgen_career_accelerator_2026.png` and `…__full-_verify.png`: the primary button runs past the right edge ("Accept cookie|").
  - The layout probe also reports the bar overlapping content: "Explore training" CTA (iPhone 13 and SE), the `/pay-installment` registration-number input (iPhone 13), and the `/training` sticky sub-nav (laptop, tablet).
- **Source:** `src/styles/global.css:5959-5963`. `.ck-actions { flex-wrap: nowrap }` and `.ck-link { white-space: nowrap }` at 16 px force the link and the button onto one line, which is wider than 320 px.
- **Fix:**

  ```css
  @media (max-width: 420px) {
    .ck { gap: 12px; padding-block: 14px; }
    .ck .ck-text { font-size: 14px; }
    .ck-actions { flex-wrap: wrap; justify-content: center; width: 100%; }
    .ck-actions .ck-btn { flex: 1 1 100%; }
  }
  ```

  Also shorten the text on phones. Optionally reserve `padding-bottom` on `body` equal to the bar's height while it is shown, so it never hides form fields.

### 4. MEDIUM (SEO): soft 404s, because unknown URLs return HTTP 200
- **Device:** n/a
- **URL:** `/blog`, `/terms`, `/this-page-does-not-exist-qa`, …
- **Evidence:** `findings/website-crawl-http.json`. The status is 200 `text/html`, and the page shows "Page not found" with canonical `https://techdrona.in/404`. `/favicon.ico` also returns the HTML shell.
- **Source:**
  - `firebase.json` rewrite `"source": "**" → /index.html`
  - `src/pages/NotFound.jsx:6`
  - `src/components/ui.jsx:106-118` (`Seo`)
- **Fix:**
  - Minimum: render `<meta name="robots" content="noindex" />` on `NotFound`. For example, add a `noindex` prop to `Seo`, and drop the canonical there.
  - Better: replace the catch-all rewrite with explicit route patterns (`/`, `/courses/**`, `/verify/**`, etc.). Then unknown paths fall through to a `dist/404.html`, which Hosting serves with HTTP 404.
  - Add a real `public/favicon.ico`.

### 5. MEDIUM (SEO and branding): canonical, OG, JSON-LD and sitemap use `techdrona.in`, but the domain plan is `techdrona.com`
- **Device:** n/a
- **URL:** all pages
- **Evidence:**
  - Every page's canonical and `og:url` is `https://techdrona.in/…`.
  - `og:image`, the JSON-LD `url` and `logo`, the `robots.txt` Sitemap line and every `sitemap.xml` `<loc>` all use techdrona.in.
  - The company email is `info@techdrona.com`.
  - The domain decision (2026-11-12) puts the website at `techdrona.com` and the LMS at `lms.techdrona.com`.
  - If techdrona.in is not owned and pointed at this site, search engines get canonicals to another host and social previews lose their image.
- **Source:**
  - `src/data/content.js:7` (`SITE.url`)
  - `index.html:17` (og:image) and `index.html:29-30` (JSON-LD)
  - `public/robots.txt`
  - `public/sitemap.xml`
- **Fix:** the owner confirms the final domain. Then set it in those 4 places; better, generate `robots.txt` and `sitemap.xml` at build time from `SITE.url`.
- **Related:**
  - `index.html` has no static `<meta name="description">` and no static `og:title` or `og:description`. React adds them after JavaScript runs, so WhatsApp, LinkedIn and Facebook link previews (which do not run JS) show no description.
  - `index.html` also lacks `</head>`.
  - The served HTML has a duplicate `<link rel="preconnect" href="https://ik.imagekit.io">`.
  - Add a static default description and OG tags to `index.html`.

### 6. MEDIUM (compliance): no Terms of Service or Refund/Cancellation policy, on a site that takes payments
- **Device:** n/a
- **URL:** footer, `/terms` (404)
- **Evidence:**
  - The only legal link is Privacy Policy (footer "Company" column, `src/components/Layout.jsx:338-343`, and `footer-legal`).
  - The site has `/pay-installment`, `/payment/status` and pay functions (`/api/pay/order`, `/api/pay/webhook`).
  - Indian payment gateways (Razorpay and others) require Terms, Refund/Cancellation and Contact pages to be linked.
- **Fix:** add `/terms` and `/refund-policy` pages, plus a shipping/delivery statement if the gateway asks for one. Link them in the footer and next to the pay buttons.

### 7. LOW: forms do not validate on blur
- **Device:** all
- **URL:** `/contact`, `/procurement`, `/recruitment`, `/apply/internship`, the course waitlist, `/pay-installment`
- **Evidence:**
  - `findings/website-forms-*.json`: focusing and blurring every empty required field produced 0 inline messages on every device. Errors appear only after Submit, which the audit did not press.
  - Good otherwise:
    - All inputs are 16 px (no iOS zoom).
    - Labels are present.
    - Submit buttons are 41–62 px tall.
    - No form overflows on the iPhone SE.
- **Source:** `src/components/EnquiryForm.jsx:12-25,42-45` (`setErrors` runs only in `submit`). The other forms use the same pattern.
- **Fix:** validate a field on `onBlur` once it has been touched, and add `aria-describedby` that points at the error.

### 8. LOW: JavaScript error after leaving the home page during a slide change
- **Device:** desktop
- **URL:** `/` → any page
- **Evidence:** build 99ebf028 `findings/website-nav-desktop.json`: `pageerror: TypeError: Cannot read properties of null (reading 'getBoundingClientRect')`.
- **Source:**
  - `src/pages/Home.jsx:276`: `change()` runs from `leaveTimer` 420 ms after `go()`, by which time the hero has unmounted and `media.current` is null.
  - `src/pages/Home.jsx:221`: same risk inside the rAF.
- **Fix:** return early with `if (!media.current) return;` in `change` and `run`, and clear `leaveTimer` in an unmount cleanup.

### 9. LOW: some `#hash` deep links land in the wrong place
- **Device:** desktop
- **Evidence:** `findings/website-crawl-hashes.json`. After loading these URLs, the target's distance from the top of the viewport was:

  | URL | Distance |
  |---|---|
  | `/courses/python-full-stack-development#register` | 838 px (900 px viewport, so the form starts at the bottom edge) |
  | `/courses/mean-stack-development#register` | 699 px |
  | `/courses/mern-stack-development#register` | 300 px |
  | `/recruitment#hire` | 299 px |
  | `/procurement#quote` | 211 px |
  | `/projects#companion` | −157 px (overshoots) |

  All 60 targets exist.
- **Source:** `src/App.jsx:82-108` and `:136-145`. `scrollToHash` measures once; images and reveal sections then change the height. The `load` + `fonts.ready` re-settle does not cover late lazy images.
- **Fix:** after the first jump, re-run `scrollToHash` when a `ResizeObserver` on `main` sees a height change, for up to about 2 s. Alternatively, reserve image heights with `width`/`height` attributes or `aspect-ratio` above those anchors.

### 10. LOW: slow loads on tablet and phone emulation
- **Device:** tablet, tablet-landscape, Pixel 7
- **Evidence:** time to `load`, from `findings/website-responsive-*.json`. It varies between runs; the iPhone SE run was mostly under 1 s.

  | URL | Time to load |
  |---|---|
  | `/solutions` | 8.6–10 s |
  | `/courses` | 5.5–10.6 s |
  | `/about` (Pixel) | 7 s |
  | `/` (phones) | about 3.9 s |
  | `/verify` (network idle) | 15.8 s, from a long-lived Firestore listener |

- **Likely cause:** every media URL uses ImageKit `tr:orig-true` (`index.html:13-14` and the `media` helpers), which serves original-size files and skips ImageKit's resizing and format negotiation. Hero films are also loading.
- **Fix:**
  - Use ImageKit transforms (`tr:w-<n>,f-auto,q-75`) with `srcset` widths.
  - Defer below-the-fold films.
  - On `/verify`, use a one-off `getDoc` instead of `onSnapshot`.

### 11. LOW: small tap targets
- **Device:** tablet and phones
- **Evidence:** `findings/website-responsive-*.json` → `layout` "tap:" entries, and `findings/website-nav-*.json` → items with h < 44:

  | Element | Size |
  |---|---|
  | Course-card title links on `/courses` and `/training` | 23 px tall |
  | Footer "Privacy Policy" and "Cookie settings" | 22 px |
  | Cookie-bar "View privacy policy" | 20 px |
  | Breadcrumb "Home" and "Courses" (tablet-landscape) | 17 px |
  | `info@techdrona.com` on `/verify` | 20 px |
  | Menu "View all solutions", "View all training & careers" and the email link | 22 px |

- **Source:**
  - `src/styles/global.css:6045-6047` (`.cc h3 a`)
  - The `.footer-legal` and `.ck-link` rules
  - `.mp-all` and `.mp-mail` (Layout.jsx:182,193)
- **Fix:** give these links `display:inline-block; padding-block: 10px` or `min-height: 44px` (or at least 24 px, the WCAG 2.2 AA minimum) on touch layouts.

### 12. LOW: text under 12 px
- **Device:** all
- **Content text:**
  - `/projects` `.wk-url` labels: 10 px.
  - `/training` "Format/Length" labels and `/training` chips on phones: 9.5–10.5 px. That is 82 to 92 elements under 12 px on `/training`.
- **Decorative mock-ups:** `/solutions` CRM mock 6.6 px, `/courses` card art 7–9 px, home hero widgets 8–9.5 px. These are acceptable if they are `aria-hidden`.
- **Fix:** raise the content labels to at least 12 px, and make sure the decorative mock-ups have `aria-hidden="true"`.

### 13. LOW: `/courses` hero image is soft on phones
- **Device:** phones
- **Evidence:** `courses-hero-m.webp` (900 px wide) is drawn at 1270–1474 CSS px wide, which is 4–5 device pixels per image pixel at DPR 3.
- **Source:** `src/components/CoursesHero.jsx:53`
- **Fix:** supply a 1600–2000 px mobile source with `srcset` (w-descriptors), or reduce the zoom/scale effect on phones.

### 14. INFO: menu and header are fine on every device (build 99ebf028)
- The hamburger appears on all sizes, including desktop next to the full nav. That is a design choice.
- On phones the header shows logo + Login + menu, and "Contact us" moves into the menu.
- The header is 69–79 px (6–11 % of the viewport).
- The panel is full width up to 412 px and a 440 px drawer above that.
- All 36 items are reachable and uncovered. The page is locked while the menu is open and unlocked on close.
- Desktop dropdowns open on click and on hover.

### 15. INFO: sslip.io (old VM) still in the website source, though not in any public link
- `src/lib/docs.js:86`: the document/QR fallback origin is `https://35-244-50-26.sslip.io` when there is no `settings.website`. It only applies on localhost, but would print VM links on certificates if `location` is unavailable.
- `src/pages/Admin.jsx:1234`: placeholder text.
- `src/lib/docrender.js:1130`: a comment.
- **Fix:** fall back to `SITE.url` instead.

### 16. INFO: console noise on iOS WebKit
- **Evidence:**
  - `@firebase/firestore … RPC_ERROR HTTP error has no status`, and Listen-channel `ERR_ABORTED` or "Load request cancelled", on `/privacy`, `/procurement`, `/apply/internship`, `/pay-installment` and the course page.
  - Google `gapi` and `__/auth/iframe.js` cancelled.
- **Cause:** requests cancelled when the test navigated away. They do not affect users.
- **Fix:** only to reduce noise, avoid opening Firestore listeners on static marketing pages (`web_course_public` could come from `catalog.json` plus the LMS status API).

## Needs a manual look
- Full-page screenshots of `/contact` and `/verify` on iPhone SE have large empty areas: about 1200 px under the contact form and about 600 px of plain hexagon background on `/verify`.
- The audit scrolled the page first, so this is most likely a full-page capture artifact of the scroll-reveal animations, and the forms themselves were measured as present. It is still worth one look on a real phone.
- See `shots/forms-no-submission--phone-small__form-_contact.png` and `shots/responsive-layout-phone-small__full-_verify.png`.

## Not covered
- Real submissions (enquiry, internship application, waitlist, payment) and email delivery. These are forbidden on live data.
- Signed-in LMS pages. The catalog.json CORS failure was reproduced from the LMS origin without signing in.
