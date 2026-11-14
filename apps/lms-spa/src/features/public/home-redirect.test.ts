/** `/` has no page of its own any more: it forwards to /modules (signed in) or /login. */
import { afterEach, describe, expect, it, vi } from "vitest";
import { isRedirectError } from "@/spa/shims/navigation";
import type { SessionState } from "@/spa/session";

const state = vi.hoisted(() => ({ value: "no" as SessionState }));
vi.mock("@/spa/session", async (orig) => ({ ...(await orig<typeof import("@/spa/session")>()), probeSession: async () => state.value }));

import Home from "@/app/(public)/page";

async function target(): Promise<string> {
  try {
    await Home.server({});
  } catch (e) {
    if (isRedirectError(e)) return e.url;
    throw e;
  }
  throw new Error("expected a redirect");
}

afterEach(() => {
  state.value = "no";
});

describe("/ (old landing page)", () => {
  it.each([
    ["yes", "/modules"],
    ["no", "/login"],
    ["unknown", "/login"],
  ] as const)("session %s → %s", async (s, to) => {
    state.value = s;
    expect(await target()).toBe(to);
  });
});
