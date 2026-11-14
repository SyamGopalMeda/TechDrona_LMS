import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it } from "vitest";
import { mockApi, renderWithProviders } from "@/features/auth/test/mock-api";
import { AnnounceButton } from "./components/AnnounceButton";

let restore: (() => void) | undefined;
afterEach(() => restore?.());

describe("AnnounceButton (batch announcements)", () => {
  it("sends a subject and message to the batch with an Idempotency-Key", async () => {
    const api = mockApi({ "POST batches/b1/announcements": { status: 201, body: { recipients: 24, announcement_id: "a1" } } });
    restore = api.restore;
    renderWithProviders(<AnnounceButton batchId="b1" batchName="March cohort" />);
    await userEvent.click(screen.getByRole("button", { name: "Message students" }));
    const dialog = await screen.findByRole("dialog", { name: "Message March cohort" });
    await userEvent.click(within(dialog).getByRole("button", { name: "Send message" }));
    expect(await within(dialog).findByText("Add a subject.")).toBeInTheDocument();
    await userEvent.type(within(dialog).getByLabelText(/Subject/), "Class moved");
    await userEvent.type(within(dialog).getByLabelText(/^Message/), "Tomorrow's class starts at 11.");
    await userEvent.click(within(dialog).getByLabelText(/Also send by email/));
    await userEvent.click(within(dialog).getByRole("button", { name: "Send message" }));
    await waitFor(() => expect(api.calls.some((c) => c.method === "POST")).toBe(true));
    const call = api.calls.find((c) => c.method === "POST")!;
    expect(call.body).toEqual({ title: "Class moved", body: "Tomorrow's class starts at 11.", send_email: true });
    expect(call.headers["idempotency-key"]).toBeTruthy();
    expect(await screen.findByText(/24 students will see it/)).toBeInTheDocument();
  });
});
