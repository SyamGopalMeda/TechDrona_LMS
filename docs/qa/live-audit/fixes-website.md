# Website fixes for the live audit (2026-11-14)

- **Audit:** `website.md` (findings 1–13) and `responsive.md` F9
- **Source:** `d:\company website\TECH DRONA LMS\tech drona`. All paths below are relative to it.
- **Deployed:** `npm run build`, then `node scripts/make-deploy-config.mjs && firebase deploy --only hosting:website --config firebase.deploy.json --project billing-f4fe3`. The site is https://techdrona-website.web.app.
- **Not tested in a local browser or dev server**, because the laptop is low on RAM. Each fix was checked against the build output and with curl on the live site. The next Playwright audit run on Cloud Build should confirm the visual fixes (items 2, 3, 5, 6, 7).

## Changes

| # | Audit item | Change | Files |
|---|---|---|---|
| 1 | **High.** `catalog.json` has no CORS header | Added a `hosting.headers` rule for `/catalog.json`: `Access-Control-Allow-Origin: *` and `Cache-Control: public, max-age=300`. `make-deploy-config.mjs` copies `hosting.headers` into `firebase.deploy.json` unchanged (it removes only functions, emulators and function rewrites), so the rule belongs in `firebase.json`. | `firebase.json` |
| 2 | Lead popup opens over the open menu | When the popup timer fires, the popup checks whether the menu is open (`html.nav-locked`) or any `[aria-modal="true"]` dialog is showing. If one is, it checks again every 1.5 s and opens only after the dialog closes. The menu panel's z-index went from 250 to 265, so it now sits above the cookie bar (260) and stays below the popup (270). | `src/components/VisitorKit.jsx`, `src/styles/global.css` (section 60) |
| 3 | Cookie bar clips "Accept cookies" at 320 px and covers 19–31 % of a phone screen | At 760 px and below, the actions can wrap, so the button can no longer be pushed off screen. At 420 px and below, the bar is compact: smaller padding and text, and the second sentence ("By clicking 'Accept cookies', you consent…") is hidden, because the button label already says it. The full text still shows on larger screens. | `VisitorKit.jsx` (the second sentence is wrapped in `span.ck-more`), `global.css` |
| 4 | `Home.jsx:276` null error after leaving home during a slide change | `change()` and the warm-up rAF `run()` return early when `media.current` is null. The unmount cleanup now also clears `leaveTimer`. | `src/pages/Home.jsx` |
| 5 | `#register`, `#hire` and other deep links land off target | The header offset already comes from `html { scroll-padding-top: var(--header-h) }`; `scrollToHash` now also adds the target's own `scroll-margin-top`. After a jump on page load, a `ResizeObserver` on `<body>` lands on the target again whenever the page height changes (late images, reveal sections). It stops after 2.5 s, or as soon as the visitor scrolls, taps or presses a key. | `src/App.jsx` |
| 6 | Tap targets under 24 px | On touch screens (`pointer: coarse`) and at 860 px and below, invisible padding with an equal negative margin makes these targets at least 24 px tall without moving anything: course-card titles (`.cc h3 a`), footer "Privacy Policy" and "Cookie settings", cookie-bar "View privacy policy", breadcrumbs (now also on tablet-landscape), and the menu's "View all …" and email links. The email links inside sentences on `/verify` are inline text links, which WCAG 2.5.8 exempts, so they were not changed. | `global.css` |
| 6 | Labels under 12 px | Raised to 12 px: `/training` program "Format/Length" labels, audience tag and status pill (`.pc-facts small`, `.pc-aud`, `.pc-live`); `/courses` fact labels and "Tech stack" label; `/projects` site addresses and thumbnail captions (`.wk-url`, `.wk-thumb span`). The illustrations (training honeycomb, solution and course mock-ups) were left as they are: they are `role="img"` with an `aria-label`, so their tiny text is decorative. | `global.css` |
| 7 | `tr:orig-true` serves full originals; slow `/solutions` and `/courses` | New helper `src/lib/imagekit.js` (`ikWidth`, `ikDensitySet`) turns a built `tr:orig-true` URL into a `tr:w-<n>` URL. Local paths are unchanged, so dev and `ASSET_CDN=off` builds still work. **`/solutions`:** the 24 project chips drew 800-px screenshots in a 48×30 box; they now load 96/144-px copies by screen density, about 2.3 KB each instead of about 25 KB. **`/courses`:** the poster gets a 720w candidate between 480w and the 1000w original. **Every page except home:** `index.html` preloaded the home hero still (100–290 KB, high priority) on every route. A small inline script now adds those preloads only on `/`. Desktop images are unchanged: large renders still pick the original files. | `src/lib/imagekit.js`, `src/pages/Solutions.jsx`, `src/pages/Courses.jsx`, `index.html` |
| 7 | Soft `/courses` hero on phones | No higher-resolution phone crop exists: the 900 px phone file is already larger than its 838 px crop of the original. So the zoom is capped instead: on screens of 900 px and below, the picture is at most 1.6× the screen width (it was up to 3.8×) and stays anchored to the bottom, where the hero's fade shows it. About 2× upscaling at DPR 3 instead of 4–5×. | `global.css` |
| F9 | `/courses` stats tile: "Certificate" overflows at 320 px | At 380 px and below, the stat icon and padding are smaller, and the label can break if it still does not fit. | `global.css` |
| 8 | `/favicon.ico` returned the HTML shell | Added `public/favicon.ico`, the existing `favicon-32.png` wrapped in an ICO container. It is now served as `image/x-icon`. | `public/favicon.ico` |
| 8 | Soft 404s | `Seo` has a new `noindex` prop: it renders `<meta name="robots" content="noindex">` and leaves out the canonical and `og:url`. `NotFound` uses it. The page used to have a separate robots meta plus a canonical to `/404`. | `src/components/ui.jsx`, `src/pages/NotFound.jsx` |
| — | `index.html` hygiene (audit item 5, related) | Removed the duplicate ImageKit preconnect: the Vite plugin injects one. Added the missing `</head>`. | `index.html` |

### Real 404 status: not changed
Hosting rewrites every path (`"source": "**"`) to `/index.html`, so unknown URLs return HTTP 200 with the React "Page not found" page. A real 404 needs explicit route patterns instead of the catch-all, plus a `dist/404.html`. Any route missing from that list would then break, so this is a separate, deliberate change. Until then, the `noindex` on the NotFound page keeps search engines from indexing those URLs.

### F9 item judged a false positive
"Program-month `<li>` items overflow (≥1080 px)": these are the items of `.ch-roadmap-sr`. Above 900 px that list is visually hidden (a 1-px, clipped box for screen readers), so its items overflow it by design. Below 900 px it is shown as a normal list. No change.

### Not in scope (left as audited)
- Form validation on blur (audit item 7).
- Static description and OG tags in `index.html`.
- `/verify` using `onSnapshot` instead of a one-off read.
- sslip.io fallbacks in the source (audit item 15).
- The stale root `catalog.json`. It is not deployed and was left in place.

## Build and deploy
- `npm run build`: passed. Vite build, then `dist/catalog.json: 8 courses`, then "Brand check passed". There is one existing size warning, for the `docrender` chunk.
- `make-deploy-config.mjs`: `firebase.deploy.json` contains the `/catalog.json` header rule.
- Deploy: `hosting[techdrona-website]`, 298 files (28 new), release complete.

## Live verification (curl, 2026-11-14)
- `curl -sI https://techdrona-website.web.app/catalog.json` returned `200`, `Access-Control-Allow-Origin: *`, `Cache-Control: public, max-age=300` and `Content-Type: application/json`. The same request with `Origin: https://techdrona-lms-app.web.app` also returned `Access-Control-Allow-Origin: *`.
- `/` returned 200. The main bundle changed from `assets/index-CyBThcN0.js` to `assets/index-BNwguwaI.js`. The live CSS (`index-BuEgl1zg.css`) contains the new rules (`.mp{z-index:265}`, `.ck .ck-more{display:none}`), and the live HTML contains the home-only preload script.
- `/solutions`, `/courses`, `/training`, `/projects` and `/recruitment` returned 200.
- `/favicon.ico` returned 200 `image/x-icon`. It used to return `text/html`.
- An ImageKit width transform used by the chips (`tr:w-96`) returned 200 and 2.3 KB.

## Owner decisions (not changed)
1. **SEO domain:** the canonical URLs, `og:url`, `og:image`, JSON-LD, `robots.txt` and `sitemap.xml` all use `techdrona.in`, while the domain plan is `techdrona.com`. The places to change: `src/data/content.js` (`SITE.url`), `index.html` (`og:image` and JSON-LD), `public/robots.txt` and `public/sitemap.xml`.
2. **Terms of Service and Refund/Cancellation pages**, which payment gateways require for the pay flow. The owner supplies the content; then add `/terms` and `/refund-policy`, and link them in the footer and next to the pay buttons.
3. **Real HTTP 404s:** replace the catch-all rewrite with explicit route patterns. See above.
4. **Cookie text on small phones:** the consent sentence is hidden at 420 px and below. If the owner wants that sentence on every screen, delete the `.ck .ck-more { display: none; }` rule.
