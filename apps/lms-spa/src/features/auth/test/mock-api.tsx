/**
 * Test-only helpers: a fetch mock routed by "METHOD path" for the BFF API client, and a
 * render wrapper with the toast provider. Never imported by application code.
 */
import { render, type RenderOptions } from "@testing-library/react";
import type { ReactElement, ReactNode } from "react";
import { vi } from "vitest";
import { ToastProvider } from "@/components/ui";
import { configureApiClient } from "@/lib/api/client";

export interface MockReply {
  status?: number;
  body?: unknown;
  headers?: Record<string, string>;
  /** Non-JSON body sent as-is (e.g. a CSV download); set `content-type` in `headers`. */
  raw?: string;
}

export interface RecordedCall {
  method: string;
  path: string;
  url: string;
  body: unknown;
  headers: Record<string, string>;
}

type Handler = MockReply | ((call: RecordedCall) => MockReply);

export function mockApi(routes: Record<string, Handler>) {
  const calls: RecordedCall[] = [];
  const navigate = vi.fn();
  const fetchImpl = vi.fn(async (input: string, init: RequestInit = {}) => {
    const method = (init.method ?? "GET").toUpperCase();
    const url = String(input);
    const path = url.replace(/^\/api\/v1\//, "").split("?")[0]!;
    const headers = (init.headers ?? {}) as Record<string, string>;
    const call: RecordedCall = { method, path, url, body: init.body ? JSON.parse(String(init.body)) : undefined, headers };
    calls.push(call);
    const h = routes[`${method} ${path}`];
    if (!h) return new Response(JSON.stringify({ type: "x", title: "Not mocked", status: 404, detail: `${method} ${path}`, code: "not_found", request_id: "req-404" }), { status: 404, headers: { "content-type": "application/problem+json" } });
    const r = typeof h === "function" ? h(call) : h;
    const status = r.status ?? 200;
    const isProblem = status >= 400;
    return new Response(r.raw !== undefined ? r.raw : r.body === undefined ? null : JSON.stringify(r.body), {
      status,
      headers: { "content-type": isProblem ? "application/problem+json" : "application/json", "x-request-id": "req-test", ...r.headers },
    });
  });
  const restore = configureApiClient({ fetchImpl: fetchImpl as unknown as typeof fetch, navigate, currentPath: () => "/test" });
  document.cookie = "td_csrf=test-csrf-token; path=/";
  return { calls, fetchImpl, navigate, restore };
}

export function problem(status: number, code: string, title: string, extra: Record<string, unknown> = {}): MockReply {
  return { status, body: { type: `https://techdrona.in/problems/${code}`, title, status, detail: extra.detail ?? title, code, request_id: "req-123", ...extra } };
}

export function renderWithProviders(ui: ReactElement, options?: RenderOptions) {
  const Wrapper = ({ children }: { children: ReactNode }) => <ToastProvider>{children}</ToastProvider>;
  return render(ui, { wrapper: Wrapper, ...options });
}
