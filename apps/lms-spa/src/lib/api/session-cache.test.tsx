import { act, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { mockApi, problem } from "@/features/auth/test/mock-api";
import { api } from "./client";
import { ApiError } from "./errors";
import {
  clearIdentityCache,
  DEFAULT_HANDLE,
  getIdentity,
  peekIdentity,
  PERSIST_TTL_MS,
  prefetchIdentityWithProbe,
  refreshIdentity,
  useIdentity,
} from "./session-cache";

const GRANTS = { data: [{ role_key: "super_admin" }], portals: ["/admin"] };
const ME_A = { user: { id: "user-a", email: "a@example.com" } };
const ME_B = { user: { id: "user-b", email: "b@example.com" } };
const STORAGE_KEY = "td.identity.v1";

let restore: (() => void) | undefined;
afterEach(() => {
  restore?.();
  restore = undefined;
  document.cookie = "td_csrf=test-csrf-token; path=/";
  vi.useRealTimers();
});

const countOf = (calls: { method: string; path: string }[], path: string) => calls.filter((c) => c.method === "GET" && c.path === path).length;

describe("session cache: de-duplication", () => {
  it("shares one in-flight request between concurrent callers and serves later ones from memory", async () => {
    const m = mockApi({ "GET me/grants": { body: GRANTS } });
    restore = m.restore;
    const [a, b, c] = await Promise.all([getIdentity("me/grants"), getIdentity("me/grants"), getIdentity("me/grants")]);
    expect(a).toEqual(GRANTS);
    expect(b).toBe(a);
    expect(c).toBe(a);
    expect(await getIdentity("me/grants")).toBe(a);
    expect(countOf(m.calls, "me/grants")).toBe(1);
    expect(peekIdentity("me/grants")).toEqual(GRANTS);
  });

  it("does not cache errors", async () => {
    let n = 0;
    const m = mockApi({ "GET me/grants": () => (++n === 1 ? problem(503, "unavailable", "Down") : { body: GRANTS }) });
    restore = m.restore;
    await expect(getIdentity("me/grants")).rejects.toBeInstanceOf(ApiError);
    expect(peekIdentity("me/grants")).toBeUndefined();
    expect(await getIdentity("me/grants")).toEqual(GRANTS);
    expect(countOf(m.calls, "me/grants")).toBe(2);
  });

  it("force and refreshIdentity() ask the API again", async () => {
    let n = 0;
    const m = mockApi({ "GET me": () => ({ body: { user: { id: "user-a", email: `v${++n}` } } }) });
    restore = m.restore;
    await getIdentity("me");
    await refreshIdentity();
    expect(peekIdentity<{ user: { email: string } }>("me")?.user.email).toBe("v2");
    await getIdentity("me", { force: true });
    expect(countOf(m.calls, "me")).toBe(3);
  });
});

describe("session cache: invalidation", () => {
  it("drops everything on a 401 from any request", async () => {
    const m = mockApi({ "GET me/grants": { body: GRANTS }, "GET me": { body: ME_A }, "GET batches": problem(401, "session_expired", "Expired") });
    restore = m.restore;
    await getIdentity("me/grants");
    await getIdentity("me");
    await api.get("batches", { handle: { auth: false } }).catch(() => undefined);
    expect(peekIdentity("me/grants")).toBeUndefined();
    expect(peekIdentity("me")).toBeUndefined();
    expect(sessionStorage.getItem(STORAGE_KEY)).toBeNull();
  });

  it("drops everything on a 403, but not on a CSRF or step-up retry", async () => {
    const m = mockApi({
      "GET me/grants": { body: GRANTS },
      "POST things": problem(401, "step_up_required", "Confirm"),
      "GET admin/secret": problem(403, "forbidden", "No"),
    });
    restore = m.restore;
    await getIdentity("me/grants");
    await api.post("things", {}, { handle: { stepUp: false } }).catch(() => undefined);
    expect(peekIdentity("me/grants")).toEqual(GRANTS);
    await api.get("admin/secret").catch(() => undefined);
    expect(peekIdentity("me/grants")).toBeUndefined();
  });

  it("clears on sign-out (auth/logout) and on sign-in (auth/login)", async () => {
    const m = mockApi({ "GET me/grants": { body: GRANTS }, "POST auth/logout": { status: 204 }, "POST auth/login": { body: { status: "ok" } } });
    restore = m.restore;
    await getIdentity("me/grants");
    expect(sessionStorage.getItem(STORAGE_KEY)).not.toBeNull();
    await api.post("auth/logout");
    expect(peekIdentity("me/grants")).toBeUndefined();
    expect(sessionStorage.getItem(STORAGE_KEY)).toBeNull();
    await getIdentity("me/grants");
    await api.post("auth/login", { email: "x", password: "y" });
    expect(peekIdentity("me/grants")).toBeUndefined();
  });

  it("re-reads the grants after this user's own role-grant change and updates mounted hooks", async () => {
    let portals = ["/admin"];
    const m = mockApi({ "GET me/grants": () => ({ body: { data: [], portals } }), "POST rbac/grants": { status: 201, body: {} } });
    restore = m.restore;
    function Probe() {
      const g = useIdentity<{ portals: string[] }>("me/grants");
      return <p>{g.data ? g.data.portals.join(",") : "none"}</p>;
    }
    render(<Probe />);
    expect(await screen.findByText("/admin")).toBeInTheDocument();
    portals = ["/admin", "/trainer"];
    await act(async () => {
      await api.post("rbac/grants", { role_key: "trainer" });
    });
    expect(await screen.findByText("/admin,/trainer")).toBeInTheDocument();
    expect(countOf(m.calls, "me/grants")).toBe(2);
  });

  it("clears when the session probe says signed out", async () => {
    const m = mockApi({ "GET me/grants": { body: GRANTS }, "GET _bff/session": { body: { session: false, refreshed: false } } });
    restore = m.restore;
    await getIdentity("me/grants");
    const { invalidateSession, probeSession } = await import("@/spa/session");
    invalidateSession();
    expect(await probeSession()).toBe("no");
    expect(peekIdentity("me/grants")).toBeUndefined();
    invalidateSession();
  });

  it("clears on entering an auth page (sign-in, sign-out, password change)", async () => {
    const m = mockApi({ "GET me/grants": { body: GRANTS } });
    restore = m.restore;
    const { onPathChange } = await import("@/spa/session");
    await getIdentity("me/grants");
    onPathChange("/admin", "/admin/users");
    expect(peekIdentity("me/grants")).toEqual(GRANTS);
    onPathChange("/admin/users", "/change-password");
    expect(peekIdentity("me/grants")).toBeUndefined();
  });
});

describe("session cache: per session and per user", () => {
  it("never serves another session's values (td_csrf changed: signed in again, maybe in another tab)", async () => {
    const m = mockApi({ "GET me/grants": { body: GRANTS } });
    restore = m.restore;
    await getIdentity("me/grants");
    document.cookie = "td_csrf=another-session; path=/";
    expect(peekIdentity("me/grants")).toBeUndefined();
    await getIdentity("me/grants");
    expect(countOf(m.calls, "me/grants")).toBe(2);
  });

  it("drops the previous user's values when GET me answers for another user", async () => {
    let me = ME_A;
    const m = mockApi({ "GET me": () => ({ body: me }), "GET me/grants": { body: GRANTS } });
    restore = m.restore;
    await getIdentity("me");
    await getIdentity("me/grants");
    me = ME_B;
    await getIdentity("me", { force: true });
    expect(peekIdentity("me/grants")).toBeUndefined();
    expect(peekIdentity("me")).toEqual(ME_B);
  });

  it("a full reload reuses sessionStorage for the same session, within the time limit only", async () => {
    const m = mockApi({ "GET me/grants": { body: GRANTS } });
    restore = m.restore;
    await getIdentity("me/grants");
    const stored = sessionStorage.getItem(STORAGE_KEY)!;
    expect(stored).not.toContain("test-csrf-token");

    // A reload: fresh module state, same tab storage.
    vi.resetModules();
    const fresh = await import("./session-cache");
    sessionStorage.setItem(STORAGE_KEY, stored);
    expect(fresh.peekIdentity("me/grants")).toEqual(GRANTS);

    // Older than the limit: not reused.
    vi.resetModules();
    const old = JSON.parse(stored) as { entries: Record<string, { at: number }> };
    old.entries["me/grants"]!.at = Date.now() - PERSIST_TTL_MS - 1;
    sessionStorage.setItem(STORAGE_KEY, JSON.stringify(old));
    const later = await import("./session-cache");
    expect(later.peekIdentity("me/grants")).toBeUndefined();

    // Another session: not reused, and removed.
    vi.resetModules();
    sessionStorage.setItem(STORAGE_KEY, stored);
    document.cookie = "td_csrf=another-session; path=/";
    const other = await import("./session-cache");
    expect(other.peekIdentity("me/grants")).toBeUndefined();
    expect(sessionStorage.getItem(STORAGE_KEY)).toBeNull();
    other.resetIdentityCacheForTests();
    later.resetIdentityCacheForTests();
    fresh.resetIdentityCacheForTests();
  });

  it("clearIdentityCache() forgets memory and storage", async () => {
    restore = mockApi({ "GET me": { body: ME_A } }).restore;
    await getIdentity("me");
    clearIdentityCache();
    expect(peekIdentity("me")).toBeUndefined();
    expect(sessionStorage.getItem(STORAGE_KEY)).toBeNull();
  });
});

describe("session cache: failure handling and prefetch", () => {
  it("a caller that relied on the client's sign-in redirect still gets it when the shared read fails", async () => {
    const m = mockApi({ "GET me": problem(401, "session_expired", "Expired") });
    restore = m.restore;
    await expect(getIdentity("me", { handle: DEFAULT_HANDLE })).rejects.toBeInstanceOf(ApiError);
    expect(m.navigate).toHaveBeenCalledWith(expect.stringMatching(/^\/login\?/));
  });

  it("silent callers get the error without a redirect", async () => {
    const m = mockApi({ "GET me": problem(401, "session_expired", "Expired") });
    restore = m.restore;
    await expect(getIdentity("me")).rejects.toBeInstanceOf(ApiError);
    expect(m.navigate).not.toHaveBeenCalled();
    expect(countOf(m.calls, "me")).toBe(1);
  });

  it("prefetch alongside the session probe retries a 401 once after the probe, and callers join it", async () => {
    let n = 0;
    const m = mockApi({ "GET me/grants": () => (++n === 1 ? problem(401, "unauthenticated", "No session yet") : { body: GRANTS }) });
    restore = m.restore;
    let finishProbe!: () => void;
    const probe = new Promise<void>((r) => (finishProbe = r));
    prefetchIdentityWithProbe(["me/grants"], probe);
    const joined = getIdentity("me/grants");
    await waitFor(() => expect(countOf(m.calls, "me/grants")).toBe(1));
    finishProbe();
    expect(await joined).toEqual(GRANTS);
    expect(countOf(m.calls, "me/grants")).toBe(2);
  });

  it("useIdentity renders a cached value on the first render (no request, no loading state)", async () => {
    const m = mockApi({ "GET me": { body: ME_A } });
    restore = m.restore;
    await getIdentity("me");
    function Probe() {
      const me = useIdentity<typeof ME_A>("me");
      return <p>{me.loading ? "loading" : me.data?.user.email}</p>;
    }
    render(<Probe />);
    expect(screen.getByText("a@example.com")).toBeInTheDocument();
    expect(countOf(m.calls, "me")).toBe(1);
  });
});
