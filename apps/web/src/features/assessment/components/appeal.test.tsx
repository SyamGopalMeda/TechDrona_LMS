import { screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { mockApi, renderWithProviders } from "@/features/auth/test/mock-api";
import { AppealView, appealTicketHref } from "./AppealView";

let restore: (() => void) | undefined;
afterEach(() => restore?.());

const base = { attempt_id: "a1", phase: "after_submit", visible: {}, submitted_at: "2026-11-03T10:00:00Z", submit_reason: "user", integrity_status: "invalidated", released_at: null };

describe("Appeal page (INV-09: /app/attempts/{id}/appeal)", () => {
  it("routes an invalidated attempt into an assessment support ticket that carries the attempt", async () => {
    const api = mockApi({ "GET attempts/a1/result": { body: { ...base, status: "invalidated", appeal_url: "/app/attempts/a1/appeal" } } });
    restore = api.restore;
    renderWithProviders(<AppealView attemptId="a1" />);
    const link = await screen.findByRole("link", { name: "Start an appeal" });
    expect(link).toHaveAttribute("href", appealTicketHref("a1"));
    expect(appealTicketHref("a1")).toBe("/app/support/new?topic=assessment&attempt_id=a1&from=%2Fapp%2Fattempts%2Fa1%2Fappeal");
  });

  it("says there is nothing to appeal for a normal attempt", async () => {
    const api = mockApi({ "GET attempts/a1/result": { body: { ...base, status: "graded" } } });
    restore = api.restore;
    renderWithProviders(<AppealView attemptId="a1" />);
    expect(await screen.findByText("There is nothing to appeal for this attempt")).toBeInTheDocument();
  });
});
