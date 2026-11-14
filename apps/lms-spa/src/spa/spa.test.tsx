import { act, render, screen, waitFor } from "@testing-library/react";
import { Suspense } from "react";
import { createMemoryRouter, MemoryRouter, Route, RouterProvider, Routes, type RouteObject } from "react-router";
import { describe, expect, it } from "vitest";
import Link from "next/link";
import { notFound, redirect, usePathname, useSearchParams } from "next/navigation";
import { asyncComponent, propsKey } from "./async";
import { SegmentBoundary } from "./boundary";
import { resolveTitle, robotsContent } from "./metadata";
import { searchToRecord } from "./runtime";
import { hostingHeaders, staticCsp } from "./hosting-headers";
import { PAGE_COUNT } from "./routes.gen";
import { configureApiClient } from "@/lib/api/client";
import { homeRedirect, invalidateSession, probeSession } from "./session";

function mount(routes: RouteObject[], url: string) {
  const router = createMemoryRouter(routes, { initialEntries: [url] });
  render(<RouterProvider router={router} />);
  return router;
}

/** Suspending trees must render inside an awaited act() so React's retries flush. */
async function mountAsync(routes: RouteObject[], url: string) {
  const router = createMemoryRouter(routes, { initialEntries: [url] });
  await act(async () => {
    render(<RouterProvider router={router} />);
  });
  return router;
}

describe("route tree", () => {
  it("has every apps/web page", () => {
    // 204 apps/web pages + 3 SPA-only pages (live audit): /app/orders index redirect, /admin/system, /college-portal/* "being moved"
    // + /admin/system and the /college-portal "being moved" fallback (fixes-nav.md).
    expect(PAGE_COUNT).toBe(207);
  });
});

describe("next/* shims", () => {
  it("next/link renders internal links through the router and external ones as anchors", () => {
    mount([{ path: "/", element: <><Link href="/app/courses">In</Link><Link href="https://example.com/x">Out</Link><Link href={{ pathname: "/help", query: { q: "a b" } }}>Q</Link></> }], "/");
    expect(screen.getByText("In").getAttribute("href")).toBe("/app/courses");
    expect(screen.getByText("Out").getAttribute("href")).toBe("https://example.com/x");
    expect(screen.getByText("Q").getAttribute("href")).toBe("/help?q=a+b");
  });

  it("usePathname / useSearchParams read the router location", () => {
    function Show() {
      return <p>{`${usePathname()}|${useSearchParams().get("next")}`}</p>;
    }
    mount([{ path: "/login", element: <Show /> }], "/login?next=%2Fapp");
    expect(screen.getByText("/login|/app")).toBeInTheDocument();
  });
});

describe("async (ex-server) components", () => {
  it("render after their data loads", async () => {
    const Page = asyncComponent(async ({ id }: { id: string }) => <p>item {id}</p>, "test#Page");
    await mountAsync([{ path: "/x/:id", element: <Suspense fallback={<p>loading</p>}><Page id="7" /></Suspense> }], "/x/7");
    expect(await screen.findByText("item 7")).toBeInTheDocument();
  });

  it("redirect() becomes a client navigation", async () => {
    // Library-mode router: data-router navigations build a fetch Request, which jsdom's
    // AbortSignal cannot satisfy under Node 24 (test-environment limitation only).
    const Gate = asyncComponent(async () => redirect("/help?next=%2Fapp"), "test#Gate");
    function Where() {
      return <p>{`at ${usePathname()}?next=${useSearchParams().get("next")}`}</p>;
    }
    await act(async () => {
      render(
        <MemoryRouter initialEntries={["/app"]}>
          <Routes>
            <Route path="/app" element={<SegmentBoundary><Suspense fallback={null}><Gate /></Suspense></SegmentBoundary>} />
            <Route path="/help" element={<Where />} />
          </Routes>
        </MemoryRouter>,
      );
    });
    expect(await screen.findByText("at /help?next=/app")).toBeInTheDocument();
  });

  it("notFound() renders the not-found view; other errors the segment error view", async () => {
    const Missing = asyncComponent(async () => notFound(), "test#Missing");
    const Broken = asyncComponent(async () => {
      throw new Error("boom");
    }, "test#Broken");
    await mountAsync(
      [
        {
          path: "/",
          element: (
            <SegmentBoundary notFound={() => <p>404 view</p>} errorComponent={({ error }) => <p>error: {error.message}</p>}>
              <Suspense fallback={null}>
                <Missing />
              </Suspense>
              <Suspense fallback={null}>
                <Broken />
              </Suspense>
            </SegmentBoundary>
          ),
        },
      ],
      "/",
    );
    await waitFor(() => expect(screen.queryByText("404 view") ?? screen.queryByText("error: boom")).toBeInTheDocument());
  });

  it("keys props by value for data and by identity for elements", () => {
    expect(propsKey({ a: 1, b: [2] })).toBe(propsKey({ a: 1, b: [2] }));
    const el = <p />;
    expect(propsKey({ el })).toBe(propsKey({ el }));
    expect(propsKey({ el })).not.toBe(propsKey({ el: <p /> }));
  });
});

describe("metadata and search params", () => {
  it("applies the root title template", () => {
    const tpl = { default: "Tech Drona", template: "%s · Tech Drona" };
    expect(resolveTitle("Log in", tpl)).toBe("Log in · Tech Drona");
    expect(resolveTitle(undefined, tpl)).toBe("Tech Drona");
    expect(resolveTitle({ absolute: "X" }, tpl)).toBe("X");
    expect(robotsContent({ index: false, follow: false })).toBe("noindex, nofollow");
  });

  it("builds Next-style searchParams records", () => {
    expect(searchToRecord("?a=1&b=2&a=3")).toEqual({ a: ["1", "3"], b: "2" });
  });
});

describe("Hosting headers", () => {
  it("static CSP has no nonce, no strict-dynamic and no unsafe script sources", () => {
    const csp = staticCsp({});
    expect(csp).not.toMatch(/nonce-|strict-dynamic|unsafe-eval/);
    expect(csp).toMatch(/script-src 'self' /);
    expect(csp).not.toMatch(/script-src[^;]*unsafe-inline/);
    expect(csp).toContain("frame-ancestors 'none'");
  });

  it("relaxes COOP and adds sign-in hosts only on /login and /signup", () => {
    const rules = hostingHeaders({ firebaseAuthDomain: "demo.firebaseapp.com" });
    const login = rules.find((r) => r.source === "/login");
    expect(login?.headers).toContainEqual({ key: "Cross-Origin-Opener-Policy", value: "same-origin-allow-popups" });
    expect(login?.headers.find((h) => h.key === "Content-Security-Policy")?.value).toContain("https://demo.firebaseapp.com");
    expect(rules[0]?.headers.find((h) => h.key === "Content-Security-Policy")?.value).not.toContain("firebaseapp.com");
  });
});

describe("session probe (GET /api/v1/_bff/session)", () => {
  function withFetch(impl: (url: string) => Response | Promise<Response>) {
    const calls: string[] = [];
    const restore = configureApiClient({
      fetchImpl: (async (input: RequestInfo | URL) => {
        calls.push(String(input));
        return impl(String(input));
      }) as typeof fetch,
    });
    invalidateSession();
    return { calls, restore };
  }
  const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });

  it("maps the edge contract {session, refreshed} and memoises one call", async () => {
    const { calls, restore } = withFetch(() => json({ session: true, refreshed: true }));
    expect(await probeSession()).toBe("yes");
    expect(await probeSession()).toBe("yes");
    expect(calls).toEqual(["/api/v1/_bff/session"]);
    restore();
  });

  it("is 'no' without a session and 'unknown' when the API is unreachable or not JSON", async () => {
    let r = withFetch(() => json({ session: false, refreshed: false }));
    expect(await probeSession()).toBe("no");
    r.restore();
    r = withFetch(() => new Response("<!doctype html>", { status: 200, headers: { "content-type": "text/html" } }));
    expect(await probeSession()).toBe("unknown");
    r.restore();
    r = withFetch(() => json({ code: "unavailable" }, 503));
    expect(await probeSession()).toBe("unknown");
    r.restore();
    invalidateSession();
  });

  it("sends a document load of / to /login or /modules like Caddy did", () => {
    expect(homeRedirect("/", "no")).toBe("/login");
    expect(homeRedirect("/", "unknown")).toBe("/login");
    expect(homeRedirect("/", "yes")).toBe("/modules");
    expect(homeRedirect("/help", "yes")).toBeNull();
  });
});
