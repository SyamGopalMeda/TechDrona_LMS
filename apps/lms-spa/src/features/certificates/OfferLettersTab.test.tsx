import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { renderWithProviders } from "@/features/auth/test/mock-api";
import { OfferLettersTab } from "./components/OfferLetters";

vi.setConfig({ testTimeout: 30000 });

async function addCandidate(user: ReturnType<typeof userEvent.setup>, name: string, email: string, date: string) {
  await user.click(screen.getByRole("button", { name: "Add one candidate" }));
  const dialog = await screen.findByRole("dialog");
  await user.type(within(dialog).getByLabelText(/Full name/), name);
  await user.type(within(dialog).getByLabelText(/^Email/), email);
  const d = within(dialog).getByLabelText(/Letter date/);
  await user.clear(d);
  await user.type(d, date);
  await user.click(within(dialog).getByRole("button", { name: "Add to list" }));
}

describe("Offer letters tab", () => {
  it("add -> generate -> email draft -> mark as sent, and the list survives a reload", async () => {
    window.localStorage.clear();
    const user = userEvent.setup();
    const { unmount } = renderWithProviders(<OfferLettersTab />);
    expect(screen.getByText("No candidates yet")).toBeInTheDocument();

    await addCandidate(user, "Asrith Reddy Satti", "asrith@example.com", "2026-11-02");
    expect(await screen.findByText("Asrith Reddy Satti")).toBeInTheDocument();
    expect(screen.getByText("Not generated")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Generate internship offer letter" }));
    expect(await screen.findByText("To send")).toBeInTheDocument();
    expect(screen.getByText("TD-OL-2026-0172")).toBeInTheDocument();
    expect(screen.getByText("3 November 2026 – 2 March 2027")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Email draft" }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText("asrith@example.com")).toBeInTheDocument();
    expect(within(dialog).getByText("TD-OL-2026-0172 - Asrith Reddy Satti.pdf")).toBeInTheDocument();
    expect((within(dialog).getByLabelText("Email body") as HTMLTextAreaElement).value).toContain("Dear Asrith Reddy Satti,");
    await user.click(within(dialog).getByRole("button", { name: "Mark as sent" }));
    expect(await screen.findByText(/^Sent \d/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Undo sent" })).toBeInTheDocument();

    unmount();
    renderWithProviders(<OfferLettersTab />);
    expect(screen.getByText("Asrith Reddy Satti")).toBeInTheDocument();
    expect(screen.getByText(/^Sent \d/)).toBeInTheDocument();
  });

  it("asks for the name before adding", async () => {
    window.localStorage.clear();
    const user = userEvent.setup();
    renderWithProviders(<OfferLettersTab />);
    await user.click(screen.getByRole("button", { name: "Add one candidate" }));
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: "Add to list" }));
    expect(within(dialog).getByText("Enter the name")).toBeInTheDocument();
  });

  it("offers the employment template with its own fields", async () => {
    window.localStorage.clear();
    const user = userEvent.setup();
    renderWithProviders(<OfferLettersTab />);
    await user.click(screen.getByRole("button", { name: "Add one candidate" }));
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByLabelText("Employment offer letter"));
    expect(within(dialog).getByLabelText(/Annual CTC/)).toBeInTheDocument();
    expect(within(dialog).getByLabelText(/Date of joining/)).toBeInTheDocument();
  });
});
