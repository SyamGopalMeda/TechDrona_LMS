/** Test helpers for Home, Reports, Targets, Planner and Team: a fetch mock routed by API path + a portal wrapper. */
import { act, render } from "@testing-library/react";
import type { ReactNode } from "react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router";
import { vi } from "vitest";
import { configurePortalApi, resetPortalApiForTests } from "../../lib/api";
import { clearPortalCacheForTests } from "../../lib/cache";
import { resetScopeForTests, setDistrictScope } from "../../lib/scope";
import { OverlayHost, PortalUiProvider, type PortalUi } from "../../ui";
import { FormsHost } from "../../forms/host";
import { resetOverlaysForTests } from "../../ui/Overlay";
import { closeAllDialogs } from "../../forms";

export function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
}

export interface Call {
  method: string;
  path: string;
  query: URLSearchParams;
  body: unknown;
}

/** `routes["GET summary"] = body | (call) => Response | body`. Unknown routes answer 404. */
export function mockApi(routes: Record<string, unknown>): Call[] {
  const calls: Call[] = [];
  const fetchImpl = vi.fn(async (url: string | URL | Request, init?: RequestInit) => {
    const u = new URL(String(url), "http://x");
    const path = u.pathname.replace(/^\/college-portal\/api\//, "");
    const method = (init?.method ?? "GET").toUpperCase();
    const call: Call = { method, path, query: u.searchParams, body: init?.body ? JSON.parse(String(init.body)) : undefined };
    calls.push(call);
    const r = routes[`${method} ${path}`];
    if (r === undefined) return json(404, { error: "Not found" });
    const out = typeof r === "function" ? (r as (c: Call) => unknown)(call) : r;
    return out instanceof Response ? out : json(200, out);
  });
  configurePortalApi({ fetchImpl: fetchImpl as unknown as typeof fetch, onSignedOut: () => undefined });
  return calls;
}

export function resetAll(): void {
  localStorage.clear();
  resetScopeForTests();
  setDistrictScope("all");
  resetPortalApiForTests();
  clearPortalCacheForTests();
}

export function cleanup(): void {
  act(() => {
    closeAllDialogs();
    resetOverlaysForTests();
  });
}

let lastSearch = "";
function LocationProbe() {
  lastSearch = useLocation().search;
  return null;
}
export const currentSearch = (): string => lastSearch;

/** Render a screen at `path` (route `pattern`) inside the portal providers. */
export function renderAt(node: ReactNode, { path = "/colleges", pattern = "*", ui = {} }: { path?: string; pattern?: string; ui?: Partial<PortalUi> } = {}) {
  const value: PortalUi = { overlayRoot: document.body, form: "desktop", coarse: true, canWrite: true, ...ui };
  return render(
    <MemoryRouter initialEntries={[path]}>
      <PortalUiProvider value={value}>
        <Routes>
          <Route path={pattern} element={node} />
        </Routes>
        <LocationProbe />
        <FormsHost />
        <OverlayHost />
      </PortalUiProvider>
    </MemoryRouter>,
  );
}
