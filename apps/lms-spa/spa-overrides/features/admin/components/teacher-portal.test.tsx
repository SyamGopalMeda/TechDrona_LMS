import { screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { mockApi, renderWithProviders } from "@/features/auth/test/mock-api";
import { taughtBatchCount, TeacherPortalCard } from "./Governance";

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn(), replace: vi.fn() }), usePathname: () => "/admin" }));

const cleanups: (() => void)[] = [];
afterEach(() => {
  while (cleanups.length) cleanups.pop()!();
});

const admin = { grant_id: "g1", role_key: "super_admin", scope_type: "platform", scope_id: null };
const teaches = { grant_id: "g2", role_key: "trainer", scope_type: "batch", scope_id: "b1" };

describe("Your Teacher Portal (Admin dashboard)", () => {
  it("renders nothing until the Admin is the trainer of a batch (live audit M2)", async () => {
    const api = mockApi({ "GET me/grants": { body: { data: [admin], portals: ["/admin"] } } });
    cleanups.push(api.restore);
    renderWithProviders(<TeacherPortalCard />);
    await waitFor(() => expect(api.calls.some((c) => c.path === "me/grants")).toBe(true));
    await new Promise((r) => setTimeout(r, 20));
    expect(screen.queryByText("Your Teacher Portal")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Be a Teacher" })).not.toBeInTheDocument();
  });

  it("opens /trainer in the same session once the Admin teaches a batch", async () => {
    const api = mockApi({ "GET me/grants": { body: { data: [admin, teaches], portals: ["/admin", "/trainer"] } } });
    cleanups.push(api.restore);
    renderWithProviders(<TeacherPortalCard />);
    const link = await screen.findByRole("link", { name: "Be a Teacher" });
    expect(link).toHaveAttribute("href", "/trainer");
    expect(screen.getByText(/You teach 1 batch\./)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Be a Teacher" })).not.toBeInTheDocument();
  });

  it("counts only trainer grants at batch scope", () => {
    expect(taughtBatchCount(undefined)).toBe(0);
    expect(taughtBatchCount([admin, { ...teaches, role_key: "evaluator" }, { ...teaches, scope_type: "course" }])).toBe(0);
    expect(taughtBatchCount([teaches, { ...teaches, grant_id: "g3" }, { ...teaches, scope_id: "b2" }])).toBe(2);
  });
});
