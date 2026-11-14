import "./env";
import "@/app/globals.css";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { createBrowserRouter, RouterProvider } from "react-router";
import { setRouter } from "./nav-store";
import { readCsrfToken } from "@/lib/api/client";
import { prefetchIdentityWithProbe } from "@/lib/api/session-cache";
import { bootstrapSession, homeRedirect } from "./session";
import { isNotFoundError, isRedirectError } from "./shims/navigation";
import { routes } from "./routes.gen";

/** Portal pages: their gate and header need `me/grants` and `me` (docs/perf/spa-requests.md). */
const PORTAL_PATH = /^\/(app|admin|trainer|evaluator|studio|desk|finance|security|colleges|continue)(\/|$)/;

async function start(): Promise<void> {
  // What the Next middleware did on a page load (remember-me re-sign-in, td_csrf), via the API
  // function, before any page asks the API for data (src/spa/session.ts).
  const probe = bootstrapSession();
  // The portal gate's grants and the header's `me`, read alongside the probe instead of after it
  // (and after the layout chunk). A browser that was signed in has a td_csrf cookie; a read that
  // fails is retried once after the probe (it may re-issue the session). Served from the session
  // cache (src/lib/api/session-cache.ts) when a recent reload already read them.
  if (PORTAL_PATH.test(window.location.pathname) && readCsrfToken()) prefetchIdentityWithProbe(["me/grants", "me"], probe);
  const session = await probe;

  // The LMS host's `/` (Caddy on the VM): /login when signed out, /modules when signed in.
  const home = homeRedirect(window.location.pathname, session);
  if (home === "/login") {
    // /login has its own response headers (Google sign-in CSP, COOP): a real document load.
    window.location.replace(`/login${window.location.search}${window.location.hash}`);
    return;
  }
  if (home) window.history.replaceState(window.history.state, "", `${home}${window.location.search}${window.location.hash}`);

  const router = createBrowserRouter(routes);
  setRouter(router);

  const container = document.getElementById("root");
  if (!container) throw new Error("#root missing from index.html");

  // redirect() / notFound() are control flow, not errors: don't log them when a boundary catches them.
  const root = createRoot(container, {
    onCaughtError(error, info) {
      if (isRedirectError(error) || isNotFoundError(error)) return;
      console.error(error, info.componentStack);
    },
  });

  // reactStrictMode: true in apps/web/next.config.ts.
  root.render(
    <StrictMode>
      <RouterProvider router={router} />
    </StrictMode>,
  );
}

void start();
