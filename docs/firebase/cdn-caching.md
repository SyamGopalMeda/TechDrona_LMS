# CDN caching on Firebase Hosting (LMS + website)

Set up 2026-11-14. Firebase Hosting is the CDN for both sites (project `billing-f4fe3`); what it and
the browser keep is decided only by `Cache-Control`.

## How Firebase Hosting caches (what we rely on)

- **Static files** are served from the CDN edge. `max-age` mostly controls the browser copy.
- **Function rewrites** (`/api/**`, `/sitemap.xml`, `/college-portal/**` -> `lmsApi`) are cached at the edge
  only when the response says `public` with `s-maxage` (or `max-age`). With no `Cache-Control`, Hosting
  treats dynamic content as `private`.
- **Cookies**: Hosting strips every request cookie except `__session`, and keys the cache on `__session`
  when it is present. For dynamic content Hosting adds `cookie` and `need-authorization` to `Vary`. So
  a response is shared only by requests with the same (or no) `__session` cookie and no `Authorization`.
  The website calls the LMS cross-origin without credentials, so all its visitors share one entry.
- **`Vary: Origin`** (set by `lms_edge/public.py`) is honoured: the CDN keeps one copy per `Origin`, so
  the `Access-Control-Allow-Origin` value always matches the requester (verified below).
- **Hosting headers replace the function's own `Cache-Control` on 2xx answers** (measured: before this
  change the `/**` rule's `no-cache` overwrote the API's `private, no-store` on every 200, including
  signed-in `/api/v1/*` answers). Non-2xx answers (401/403/404/5xx) keep the function's header
  (`no-store`), so errors are never cached. That is why the rules below include `/api/**`.
  `Set-Cookie` still passes: Hosting checks the function's own header (`private`, added by
  `lms_edge/app.py keep_cookies_through_hosting`) before applying the configured one.
- **Invalidation**: every `firebase deploy --only hosting:<target>` clears that site's whole CDN cache.
  Browsers still keep their copy until `max-age` runs out, which is why non-hashed files get one day,
  not one year.

## Where the rules live

- LMS: `apps/lms-spa/src/spa/hosting-headers.ts` (source) -> `node scripts/gen-static.mjs` (also run by
  `npm run build`'s prebuild) writes `apps/lms-spa/hosting-headers.json` -> `python
  functions-lms/tools/sync_hosting.py` writes `firebase.json` (target `lms`). Later rules win for the
  same header key. Test: `src/spa/spa.test.tsx` ("caches only static files ...").
- Website: `tech drona/firebase.json` -> `node scripts/make-deploy-config.mjs` -> `firebase.deploy.json`.

## LMS (`techdrona-lms-app`)

| Path | Cache-Control | Why |
|---|---|---|
| `/**` (HTML: `index.html` for every page route) | `no-cache` | Revalidated on each load so a deploy shows at once (it names the new hashed assets). |
| `/assets/**` | `public, max-age=31536000, immutable` | Vite content-hashed names; a change is a new URL. |
| `/brand/**`, `/fonts/**`, `/vendor/**` (Monaco), `/favicon.ico`, `/favicon-32.png`, `/apple-touch-icon.png`, `/icon-512.png`, `/manifest.webmanifest`, `/robots.txt` | `public, max-age=86400` | Same URL across deploys (fonts are not fingerprinted), so one day. No service worker exists. |
| `/api/**` | `private, no-store` | Personal by default: never stored by the CDN or the browser. Covers `/api/v1/me`, `/api/v1/admin/**`, everything signed-in. |
| `GET /api/public/courses/status` | `public, max-age=30, s-maxage=60` | Same JSON for every visitor (`{"data": {slug: status}}`); the website asks for it on every page view. The admin screen promises "within a minute", so the CDN keeps it 60 s and the browser 30 s (the browser counts the CDN `Age`, so worst case is about one minute). Errors (403 bad origin, 503) stay `no-store`. |
| `/college-portal`, `/college-portal/**` | `private, no-store` | Admin-only data. Unchanged. |
| `/college-portal/{css,js,vendor,assets}/**` | `private, no-cache` | Unchanged (portal answers 304). |

Not cached on purpose:
- `GET /api/public/admissions/plans/<slug>`: public, but fee and payment details on the registration
  page only (low traffic) and money-related; left `private, no-store`.
- `GET /api/v1/public/integrations`, `/api/v1/catalog/**`: called only by the LMS SPA through the BFF,
  which sets the CSRF/session cookies on the answer, so it is `private` by design.
- The API code still sets `Cache-Control: public, max-age=30` on `/public/courses/status`
  (`apps/api/app/modules/admissions/public.py STATUS_CACHE`), but the edge (`lms_edge/public.py _cors`)
  answers `no-store` and Hosting replaces it on 200. The Hosting rule is the one in force; no function
  deploy was needed.

## Website (`techdrona-website`)

| Path | Cache-Control | Why |
|---|---|---|
| `/index.html`, extensionless routes (`**/!(*.*)`) | `no-cache` | Deploys show at once. |
| `/assets/**` | `public, max-age=31536000, immutable` | Hashed JS/CSS. |
| `**/*.@(webp\|png\|jpg\|jpeg\|svg\|mp4\|woff2)` | `public, max-age=604800` | Images and video under `/img`, `/media` (unchanged). |
| `**/*.@(pdf\|ttf\|ico\|webmanifest)` | `public, max-age=86400` | Brochures (`/docs/*.pdf`) and `/docs-art` PDFs can be regenerated under the same name, so one day (was 7 days for PDFs); document fonts, favicon, manifest (were Hosting's default `max-age=3600`). |
| `/robots.txt`, `/sitemap.xml` | `public, max-age=3600` | Crawler files; short so SEO edits land the same hour. |
| `/catalog.json` | `public, max-age=300` + `Access-Control-Allow-Origin: *` | Unchanged. |

ImageKit images are on ImageKit's own CDN; not touched.

## Cloud Storage

Certificates, uploads and payment proofs live in Cloud Storage behind signed or private URLs
(`storage.googleapis.com`). They do not go through Hosting and are not cached by these rules; left as is.

## Live verification (2026-11-14, after deploy; each URL requested twice)

| URL | Cache-Control | 1st / 2nd |
|---|---|---|
| LMS `/api/public/courses/status` (`Origin: https://techdrona-website.web.app`) | `public, max-age=30, s-maxage=60`; `Access-Control-Allow-Origin: https://techdrona-website.web.app`; `Vary: Origin,cookie,need-authorization` | MISS / **HIT** |
| same, no `Origin` then with website `Origin` | separate cache entries; website copy carries ACAO | MISS, HIT / MISS (own entry) |
| same, `Origin: https://evil.example` | `no-store` (403) | MISS / MISS |
| `OPTIONS` preflight from the website | 204 with ACAO, methods, max-age 600 | works |
| LMS `/api/v1/me` | `private, no-store` | MISS / MISS |
| LMS `/api/v1/public/integrations` | `private, no-store` (was `no-cache`) | MISS / MISS |
| LMS `/college-portal/`, `/college-portal/js/app.js` | `private, no-store` | MISS / MISS |
| LMS `/favicon.ico`, `/manifest.webmanifest`, `/robots.txt`, `/fonts/inter-latin.woff2`, `/brand/logo-mark-navy.svg`, `/vendor/monaco/vs/loader.js` | `public, max-age=86400` (was `no-cache`) | MISS / HIT |
| LMS `/`, `/modules` | `no-cache` | MISS / MISS |
| Website `/favicon.ico`, `/site.webmanifest`, `/docs/techdrona-genai-brochure.pdf`, `/fonts/Cinzel-Bold.ttf` | `public, max-age=86400` | MISS / HIT |
| Website `/robots.txt`, `/sitemap.xml` | `public, max-age=3600` | MISS / HIT |
| Website `/og-image.jpg` | `public, max-age=604800` | MISS / HIT |
| Website `/catalog.json` | `public, max-age=300` | MISS / HIT |
| Website `/`, `/courses` | `no-cache` | MISS / MISS |

Re-check with:

```sh
curl -sD - -o /dev/null -H "Origin: https://techdrona-website.web.app" \
  https://techdrona-lms-app.web.app/api/public/courses/status | grep -iE "cache-control|x-cache|vary|access-control"
```

## Effect

Before: every website page view woke `lmsApi` and read Firestore for the course status (plus a rate-limit
write). Now each CDN edge location calls the function at most once a minute for it, however many
visitors there are, and a returning visitor's browser reuses it for 30 s. LMS icons, fonts and Monaco
are no longer re-validated on each page load.
