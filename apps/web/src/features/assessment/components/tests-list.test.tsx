import { screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { mockApi, renderWithProviders } from "@/features/auth/test/mock-api";
import type { TestRowData } from "../lib/types";
import { TestsList, testRowAction } from "./TestsList";

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn(), replace: vi.fn() }) }));

let restore: (() => void) | undefined;
afterEach(() => restore?.());

const row = (id: string, status: string, extra: Partial<TestRowData> = {}): TestRowData => ({
  test_id: id,
  title: `Mock ${id}`,
  test_kind: "mock",
  duration_seconds: 3600,
  test_assignment_id: null,
  available_from: null,
  available_until: null,
  attempts_used: 0,
  attempts_left: 1,
  status,
  in_progress_attempt_id: null,
  last_attempt: null,
  ...extra,
});

describe("TestsList (STU-009)", () => {
  it("picks one action per row: resume, results or open", () => {
    expect(testRowAction(row("a", "in_progress", { in_progress_attempt_id: "att1" }))).toEqual({ href: "/app/attempts/att1", label: "Resume test" });
    expect(testRowAction(row("b", "available"))).toEqual({ href: "/app/tests/b", label: "Open test" });
    const done = row("c", "completed", { last_attempt: { attempt_id: "att9" } as TestRowData["last_attempt"] });
    expect(testRowAction(done)).toEqual({ href: "/app/tests/c/results/att9", label: "View results" });
  });

  it("makes each row one clickable card and hides the redundant 'Available' badge", async () => {
    restore = mockApi({
      "GET me/tests": { body: { items: [row("a", "available"), row("b", "in_progress", { in_progress_attempt_id: "att1" })], server_now: "" } },
      "GET me/attempts": { body: { items: [], page: { next_cursor: null } } },
    }).restore;
    renderWithProviders(<TestsList />);
    const open = await screen.findByRole("link", { name: "Open test: Mock a" });
    expect(open).toHaveAttribute("href", "/app/tests/a");
    expect(open.className).toContain("after:inset-0");
    const card = open.closest("li")!;
    expect(within(card).queryByText("Available")).not.toBeInTheDocument();
    const resume = screen.getByRole("link", { name: "Resume test: Mock b" });
    expect(within(resume.closest("li")!).getByText("In progress")).toBeInTheDocument();
    expect(screen.getByText("Timed mock tests and tests from your trainer.")).toBeInTheDocument();
  });
});
