import { screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { mockApi, renderWithProviders } from "@/features/auth/test/mock-api";
import { outcomesFor } from "./Integrity";
import { TestsList } from "./TestsList";

/* Live audit 2026-11-14 (docs/qa/live-audit/staff-portals.md §4 and F5; fixes in fixes-nav.md). */
vi.mock("next/navigation", () => ({ usePathname: () => "/evaluator/tests", useRouter: () => ({ push: vi.fn(), replace: vi.fn() }), useSearchParams: () => new URLSearchParams() }));

const cleanups: (() => void)[] = [];
afterEach(() => {
  while (cleanups.length) cleanups.pop()!();
});

describe("Evaluator portal copy and actions", () => {
  it("never offers 'Invalidate the attempt' to evaluators (attempt.invalidate is trainer-only)", () => {
    expect(outcomesFor(true).map((o) => o.value)).toEqual(["no_action", "refer_security"]);
    expect(outcomesFor(false).map((o) => o.value)).toEqual(["no_action", "refer_security", "invalidate"]);
  });

  it("the evaluator's empty Tests list does not talk about creating tests", async () => {
    const api = mockApi({ "GET studio/tests": { body: { items: [], page: { next_cursor: null, has_more: false } } } });
    cleanups.push(api.restore);
    renderWithProviders(<TestsList batches={[]} basePath="/evaluator" evaluateOnly />);
    expect(await screen.findByText(/Tests assigned to your batches appear here when students submit attempts/)).toBeInTheDocument();
    expect(screen.queryByText(/Tests you create/)).not.toBeInTheDocument();
  });
});
