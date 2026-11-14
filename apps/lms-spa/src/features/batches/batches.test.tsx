import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { mockApi, renderWithProviders } from "@/features/auth/test/mock-api";
import { activeHref } from "@/components/shell/PortalNav";
import { gradingBaseFor } from "@/features/trainer/shared/portal-base";
import { PORTALS } from "@/lib/nav/portals";
import { AdminBatchDetail, BatchList } from "./components/Batches";

// Typing-heavy dialog flows: allow for slow CI runners when the whole suite runs in parallel.
vi.setConfig({ testTimeout: 20000 });

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn(), replace: vi.fn(), refresh: vi.fn() }), usePathname: () => "/admin/batches" }));

const cleanups: (() => void)[] = [];
afterEach(() => {
  while (cleanups.length) cleanups.pop()!();
});

const batch = { id: "b1", organization_id: "co", name: "Full-stack Jan 27", code: "FS-JAN-27", academic_year: "2026-27", graduation_year: null, starts_on: "2027-01-05", ends_on: null, status: "active" };
const report = {
  batch_id: "b1",
  week_start: "2026-11-02",
  learners_total: 1,
  weekly_learning_time: { n: "<10", median_s: "<10", p90_s: "<10", suppressed: true },
  learners: [],
  progress_distribution: null,
  lesson_funnel: null,
  measurement_version: 1,
};

describe("Admin batches (ADM-013)", () => {
  it("lists batches with admin links and creates one", async () => {
    const api = mockApi({
      "GET batches": { body: { data: [batch] } },
      "POST batches": { status: 201, body: { ...batch, id: "b2" } },
    });
    cleanups.push(api.restore);
    renderWithProviders(<BatchList />);
    expect(await screen.findByRole("link", { name: "Full-stack Jan 27" })).toHaveAttribute("href", "/admin/batches/b1");
    expect(screen.getByText("2026-27")).toBeInTheDocument();
    // "Create batch" lives in the page header next to the h1 (Phase 2).
    const header = screen.getByRole("heading", { level: 1, name: "Batches" }).closest("header")!;
    expect(within(header).getByRole("button", { name: "Create batch" })).toBeInTheDocument();
    await userEvent.click(screen.getAllByRole("button", { name: "Create batch" })[0]!);
    const dialog = await screen.findByRole("dialog");
    await userEvent.click(within(dialog).getByRole("button", { name: "Create" }));
    expect(await within(dialog).findByText("Enter a batch name.")).toBeInTheDocument();
    await userEvent.type(within(dialog).getByLabelText(/^Name/), "Data cohort");
    await userEvent.type(within(dialog).getByLabelText(/^Code/), "DATA-27");
    await userEvent.type(within(dialog).getByLabelText(/^Intake/), "2026-27");
    await userEvent.click(within(dialog).getByRole("button", { name: "Create" }));
    await waitFor(() => expect(api.calls.find((c) => c.method === "POST")?.body).toMatchObject({ name: "Data cohort", code: "DATA-27", academic_year: "2026-27" }));
    expect(api.calls.some((c) => c.url.includes("orgs/"))).toBe(false);
    // Status left on Automatic: the api decides (planned for a future start), so none is sent.
    expect(api.calls.find((c) => c.method === "POST")?.body).not.toHaveProperty("status");
  });

  it("sends an explicitly chosen status", async () => {
    const api = mockApi({ "GET batches": { body: { data: [batch] } }, "POST batches": { status: 201, body: { ...batch, id: "b3" } } });
    cleanups.push(api.restore);
    renderWithProviders(<BatchList />);
    await userEvent.click((await screen.findAllByRole("button", { name: "Create batch" }))[0]!);
    const dialog = await screen.findByRole("dialog");
    await userEvent.type(within(dialog).getByLabelText(/^Name/), "Later cohort");
    await userEvent.type(within(dialog).getByLabelText(/^Code/), "LATER-27");
    await userEvent.selectOptions(within(dialog).getByLabelText(/^Status/), "planned");
    await userEvent.click(within(dialog).getByRole("button", { name: "Create" }));
    await waitFor(() => expect(api.calls.find((c) => c.method === "POST")?.body).toMatchObject({ code: "LATER-27", status: "planned" }));
  });
});

describe("Admin batch detail (ADM-014)", () => {
  const routes = () => ({
    "GET batches/b1": { body: batch },
    "GET batches/b1/members": { body: { data: [{ user_id: "u1", full_name: "Asha Rao", member_role: "student", added_at: "2026-11-01T00:00:00Z" }] } },
    "GET analytics/reports/batches/b1": { body: report },
    "GET rbac/grants": { body: { data: [{ grant_id: "g1", user_id: "t1", role_key: "evaluator", scope_type: "batch", scope_id: "b1", granted_at: "2026-11-01T00:00:00Z", expires_at: null }] } },
    "GET admin/users": { body: { data: [{ user_id: "u2", display_name: "Ravi Kumar", email: "ravi@example.com", status: "active", roles: ["student"] }], page: { next_cursor: null, has_more: false } } },
    "POST batches/b1/members": { body: { added: 1 } },
    "DELETE batches/b1/members/u1": { body: { removed: true } },
    "POST rbac/grants": { status: 201, body: { grant_id: "g2" } },
  });

  it("links students to the admin user view and shows batch staff", async () => {
    const api = mockApi(routes());
    cleanups.push(api.restore);
    renderWithProviders(<AdminBatchDetail batchId="b1" />);
    expect((await screen.findAllByRole("link", { name: "Asha Rao" }))[0]).toHaveAttribute("href", "/admin/users/u1");
    expect(await screen.findByText("Evaluator")).toBeInTheDocument();
    // Phase 2: the batch name is the h1 with breadcrumbs back to the list; staff show a readable reference, not a UUID.
    expect(await screen.findByRole("heading", { level: 1, name: "Full-stack Jan 27" })).toBeInTheDocument();
    expect(within(screen.getByRole("navigation", { name: "Breadcrumb" })).getByRole("link", { name: "Batches" })).toHaveAttribute("href", "/admin/batches");
    expect(screen.getByRole("link", { name: "User #T1" })).toHaveAttribute("href", "/admin/users/t1");
    expect(screen.queryByText("t1")).not.toBeInTheDocument();
    const grantCall = api.calls.find((c) => c.url.includes("rbac/grants"));
    expect(grantCall?.url).toContain("scope_type=batch");
    expect(grantCall?.url).toContain("scope_id=b1");
  });

  it("adds an existing account found by search", async () => {
    const api = mockApi(routes());
    cleanups.push(api.restore);
    renderWithProviders(<AdminBatchDetail batchId="b1" />);
    await userEvent.click(await screen.findByRole("button", { name: "Add student" }));
    const dialog = await screen.findByRole("dialog");
    await userEvent.type(within(dialog).getByLabelText(/Find a person/), "ravi");
    await userEvent.click(await within(dialog).findByRole("button", { name: "Choose Ravi Kumar" }));
    await userEvent.click(within(dialog).getByRole("button", { name: "Add to batch" }));
    await waitFor(() => expect(api.calls.find((c) => c.method === "POST" && c.url.includes("members"))?.body).toEqual({ user_ids: ["u2"], member_role: "student" }));
  });

  it("assigns an evaluator at batch scope", async () => {
    const api = mockApi(routes());
    cleanups.push(api.restore);
    renderWithProviders(<AdminBatchDetail batchId="b1" />);
    await userEvent.click(await screen.findByRole("button", { name: "Assign trainer or evaluator" }));
    const dialog = await screen.findByRole("dialog");
    await userEvent.selectOptions(within(dialog).getByLabelText(/^Role/), "evaluator");
    await userEvent.type(within(dialog).getByLabelText(/Find a person/), "ravi");
    await userEvent.click(await within(dialog).findByRole("button", { name: "Choose Ravi Kumar" }));
    await userEvent.type(within(dialog).getByLabelText(/^Reason/), "Grades the January cohort");
    await userEvent.click(within(dialog).getByRole("button", { name: "Assign" }));
    await waitFor(() =>
      expect(api.calls.find((c) => c.method === "POST" && c.url.includes("rbac/grants"))?.body).toMatchObject({ user_id: "u2", role_key: "evaluator", scope_type: "batch", scope_id: "b1" }),
    );
  });
});

describe("shared navigation helpers", () => {
  it("highlights the most specific admin nav item and keeps portal roots exact", () => {
    const nav = PORTALS.admin.nav;
    const roots = ["/admin", "/finance", "/desk", "/security", "/mentor"];
    expect(activeHref(nav, "/finance/orders/42", roots)).toBe("/finance/orders");
    expect(activeHref(nav, "/finance", roots)).toBe("/finance");
    expect(activeHref(nav, "/admin/batches/b1", roots)).toBe("/admin/batches");
    expect(activeHref(nav, "/admin/unknown", roots)).toBeNull();
  });

  it("keeps grading links inside the evaluator portal", () => {
    expect(gradingBaseFor("/evaluator")).toBe("/evaluator");
    expect(gradingBaseFor("/evaluator/tests")).toBe("/evaluator");
    expect(gradingBaseFor("/evaluatorx")).toBe("/trainer");
    expect(gradingBaseFor("/trainer/grading")).toBe("/trainer");
  });
});
