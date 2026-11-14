import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { mockApi, problem, renderWithProviders } from "@/features/auth/test/mock-api";
import { GradingQueue } from "./Grading";
import { TrainerBatchPage } from "./TrainerBatchPage";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/trainer/grading",
}));

let restore: (() => void) | undefined;
afterEach(() => restore?.());

describe("GradingQueue release guard (WS-UI 0.7)", () => {
  it("asks for confirmation before releasing grades and names what is still ungraded", async () => {
    const api = mockApi({
      "GET assignments": {
        body: {
          data: [
            {
              id: "as1",
              assignment_id: "as1",
              title: "Arrays worksheet",
              batch_id: "b1",
              batch_name: "CSE-A",
              max_score: 10,
              max_points: 10,
              pending_count: 2,
              grades_released: false,
            },
          ],
          page: { next_cursor: null, has_more: false, limit: 100 },
        },
      },
      "GET batches/b1/members": { body: { data: [] } },
      "GET assignments/as1/submissions": { body: { data: [], page: { next_cursor: null, has_more: false, limit: 200 } } },
      "POST assignments/as1/release-grades": { body: { assignment_id: "as1", grades_released: true } },
    });
    restore = api.restore;
    renderWithProviders(<GradingQueue />);
    await userEvent.click(await screen.findByRole("button", { name: "Show submissions for Arrays worksheet" }));
    await userEvent.click(await screen.findByRole("button", { name: "Release grades" }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText(/Students in CSE-A will see their grades/)).toBeInTheDocument();
    expect(within(dialog).getByText("2 submissions are still waiting to be graded.")).toBeInTheDocument();
    expect(api.calls.some((c) => c.method === "POST")).toBe(false);

    await userEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));
    expect(api.calls.some((c) => c.method === "POST")).toBe(false);

    await userEvent.click(screen.getByRole("button", { name: "Release grades" }));
    await userEvent.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Release grades" }));
    await waitFor(() => expect(api.calls.some((c) => c.method === "POST" && c.path === "assignments/as1/release-grades")).toBe(true));
  });
});

describe("Trainer batch page (WS-UI 0.8)", () => {
  it("uses the batch name as the h1 and shows batch progress once", async () => {
    const api = mockApi({
      "GET batches/b1": { body: { id: "b1", organization_id: "o1", name: "CSE 2027 A", code: "CSE-A", status: "active", starts_on: null, ends_on: null } },
      "GET batches/b1/members": { body: { data: [] } },
      "GET analytics/reports/batches/b1": problem(404, "not_found", "Not found"),
    });
    restore = api.restore;
    renderWithProviders(<TrainerBatchPage batchId="b1" />);
    expect(await screen.findByRole("heading", { level: 1, name: "CSE 2027 A" })).toBeInTheDocument();
    await waitFor(() => expect(api.calls.some((c) => c.path === "analytics/reports/batches/b1")).toBe(true));
    expect(screen.getAllByText("Batch progress")).toHaveLength(1);
  });
});
