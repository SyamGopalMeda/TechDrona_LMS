import { renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { mockApi } from "@/features/auth/test/mock-api";
import { isTeacherPortal, useTeachingQuery, useTrainerBatches } from "./batches";

const nav = vi.hoisted(() => ({ path: "/trainer" }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn(), replace: vi.fn() }), usePathname: () => nav.path }));

const cleanups: (() => void)[] = [];
afterEach(() => {
  while (cleanups.length) cleanups.pop()!();
});

const batch = (id: string) => ({ id, organization_id: "o1", name: `Batch ${id}`, code: id, status: "active", starts_on: null, ends_on: null });
const adminWhoTeaches = {
  data: [
    { grant_id: "g1", role_key: "super_admin", scope_type: "platform", scope_id: null },
    { grant_id: "g2", role_key: "trainer", scope_type: "batch", scope_id: "b1" },
  ],
  portals: ["/admin", "/trainer"],
};

describe("useTrainerBatches: an Admin in the Teacher portal", () => {
  it("asks the api for only the batches they teach (batches?mine=true)", async () => {
    nav.path = "/trainer";
    const api = mockApi({ "GET me/grants": { body: adminWhoTeaches }, "GET batches": { body: { data: [batch("b1")] } } });
    cleanups.push(api.restore);
    const { result } = renderHook(() => useTrainerBatches());
    await waitFor(() => expect(result.current.batches).toEqual([batch("b1")]));
    const call = api.calls.find((c) => c.path === "batches")!;
    expect(new URL(call.url, "http://x").searchParams.get("mine")).toBe("true");
  });

  it("keeps every batch in the Evaluator portal (platform graders)", async () => {
    nav.path = "/evaluator";
    const api = mockApi({ "GET me/grants": { body: adminWhoTeaches }, "GET batches": { body: { data: [batch("b1"), batch("b2")] } } });
    cleanups.push(api.restore);
    const { result } = renderHook(() => useTrainerBatches());
    await waitFor(() => expect(result.current.batches?.length).toBe(2));
    expect(api.calls.find((c) => c.path === "batches")!.url).not.toContain("mine=");
  });
});

describe("teacher portal helpers", () => {
  it("recognises /trainer paths only", () => {
    expect(isTeacherPortal("/trainer")).toBe(true);
    expect(isTeacherPortal("/trainer/grading")).toBe(true);
    expect(isTeacherPortal("/trainers")).toBe(false);
    expect(isTeacherPortal("/admin")).toBe(false);
    expect(isTeacherPortal(null)).toBe(false);
  });

  it("adds teaching=true to assignment lists in the Teacher portal only", () => {
    nav.path = "/trainer/grading";
    expect(renderHook(() => useTeachingQuery()).result.current).toEqual({ teaching: true });
    nav.path = "/evaluator";
    expect(renderHook(() => useTeachingQuery()).result.current).toEqual({});
  });
});
