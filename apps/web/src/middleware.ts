import { NextResponse, type NextRequest } from "next/server";
import { cookieMode, cookieName, loadBffConfig, type BffConfig } from "@/lib/bff/config";
import { serializeCookie } from "@/lib/bff/cookies";
import { mintCsrfToken, verifyCsrfToken } from "@/lib/bff/csrf";
import { isTopLevelUserNavigation, refreshRememberedSession } from "@/lib/bff/remember";
import { buildCsp, cspOptionsFromEnv } from "@/lib/security/csp";
import { isPortalPath } from "@/lib/nav/portals";
import { analyticsConfig, googleSignInConfig } from "@/lib/firebase/config";

/**
 * Page middleware (not used for /api/*: the BFF route handler does its own checks).
 *
 * 1. Per-request CSP nonce (security-threat-model "XSS" row).
 * 2. Portal routes require a session cookie to be PRESENT; otherwise redirect to /login.
 *    This is a UX gate only — the api authorises every request (require_active_principal).
 * 3. Issues/refreshes the td_csrf cookie so client code can make unsafe calls.
 * 4. Authenticated pages are `Cache-Control: no-store`.
 * 5. Remember-device (AUTH-28, SEC-07): a top-level user navigation to a portal route with no
 *    session cookie but a `td_remember` cookie is re-authenticated server-side by the BFF
 *    (service token) and re-navigated to the same URL with the new cookies. Background
 *    requests and prefetches never trigger it (api-specification §1.2).
 */
/** Env is fixed for the process lifetime; resolve CSP sources once. */
const cspOptions = cspOptionsFromEnv();
/** Google sign-in (Firebase Auth) hosts are allowed only on the pages that offer it. */
const GOOGLE_SIGNIN_PATHS = new Set(["/login", "/signup"]);
const googleAuthDomain = googleSignInConfig()?.authDomain ?? null;
const analyticsHosts = analyticsConfig() !== null;
/** The only LMS page allowed to frame same-origin content (`frame-src 'self'`). */
const COLLEGE_DATA_PAGE = "/admin/college-data";
const SIGNED_IN_PAGES = new Set(["/modules", "/continue"]);

function bffConfigOrNull(): BffConfig | null {
  try {
    return loadBffConfig();
  } catch {
    return null;
  }
}

export async function middleware(request: NextRequest): Promise<NextResponse> {
  const { pathname, search } = request.nextUrl;
  const session = request.cookies.get(cookieName("session"))?.value;
  // The module hub and the /continue resume link need a session too (and get the remember-me refresh).
  const portal = isPortalPath(pathname) || SIGNED_IN_PAGES.has(pathname);

  if (portal && !session) {
    const remember = request.cookies.get(cookieName("remember"))?.value;
    let clearRemember: string[] = [];
    if (remember && isTopLevelUserNavigation(request.headers)) {
      const config = bffConfigOrNull();
      if (config) {
        const outcome = await refreshRememberedSession(
          request.headers,
          remember,
          request.cookies.get(cookieName("device"))?.value,
          { config },
        );
        if (outcome.kind === "refreshed") {
          const again = NextResponse.redirect(request.nextUrl.clone(), 303);
          again.headers.set("cache-control", "no-store");
          for (const c of outcome.setCookies) again.headers.append("set-cookie", c);
          return again;
        }
        clearRemember = outcome.setCookies;
      }
    }
    const login = request.nextUrl.clone();
    login.pathname = "/login";
    login.search = "";
    login.searchParams.set("next", `${pathname}${search}`);
    const res = NextResponse.redirect(login);
    for (const c of clearRemember) res.headers.append("set-cookie", c);
    return res;
  }

  const nonce = Buffer.from(globalThis.crypto.getRandomValues(new Uint8Array(16))).toString("base64");
  const csp = buildCsp(nonce, {
    ...cspOptions,
    firebaseAuthDomain: GOOGLE_SIGNIN_PATHS.has(pathname) ? googleAuthDomain : null,
    analytics: analyticsHosts,
    // The College Data Portal page frames the same-origin /college-portal/ app (route handler).
    frameSelf: pathname === COLLEGE_DATA_PAGE,
  });
  const requestHeaders = new Headers(request.headers);
  requestHeaders.set("x-nonce", nonce);
  requestHeaders.set("content-security-policy", csp);
  // Deep links (commerce request): server components (PortalShell) read the requested path to
  // build `/login?next=<path>` instead of the portal prefix. Browser-supplied values are overwritten.
  requestHeaders.set("x-td-request-path", `${request.nextUrl.pathname}${request.nextUrl.search}`);

  const response = NextResponse.next({ request: { headers: requestHeaders } });
  response.headers.set("content-security-policy", csp);
  if (portal) response.headers.set("cache-control", "no-store");

  const key = process.env.TD_CSRF_KEY;
  if (key) {
    const existing = request.cookies.get(cookieName("csrf"))?.value;
    if (!existing || !verifyCsrfToken([key], existing, session)) {
      response.headers.append(
        "set-cookie",
        serializeCookie(cookieName("csrf"), mintCsrfToken(key, session), cookieMode(), {
          httpOnly: false,
          sameSite: "Strict",
        }),
      );
    }
  }
  return response;
}

export const config = {
  runtime: "nodejs",
  matcher: [
    {
      // Pages only: skip the BFF, Next internals and static files (incl. /vendor: Monaco worker
      // scripts must not get the page CSP, whose 'strict-dynamic' would block importScripts).
      // /college-portal/* is the College Data Portal proxy: its route handler authenticates every
      // request and passes through the portal's own CSP (its module scripts carry no nonce).
      source: "/((?!api/|vendor/|college-portal(?:/|$)|_next/static|_next/image|favicon.ico|robots.txt|sitemap.xml|.*\\.(?:svg|png|jpg|jpeg|gif|webp|ico|txt|woff2?)$).*)",
      missing: [
        { type: "header", key: "next-router-prefetch" },
        { type: "header", key: "purpose", value: "prefetch" },
      ],
    },
  ],
};
