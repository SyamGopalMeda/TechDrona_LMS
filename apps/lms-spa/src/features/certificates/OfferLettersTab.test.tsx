import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { renderWithProviders } from "@/features/auth/test/mock-api";
import { OfferLettersTab } from "./components/OfferLetters";

vi.setConfig({ testTimeout: 30000 });

describe("Offer letters tab", () => {
  it("generates the HR email draft from the form", async () => {
    window.localStorage.clear();
    const user = userEvent.setup();
    renderWithProviders(<OfferLettersTab />);
    expect(screen.getByLabelText(/Ref\. No\. \/ Intern ID/)).toHaveValue("TD-OL-2026-0161");
    await user.type(screen.getByLabelText(/Student's full name/), "Asrith Reddy Satti");
    await user.type(screen.getByLabelText(/^Email/), "asrith@example.com");
    const date = screen.getByLabelText(/Letter date/);
    await user.clear(date);
    await user.type(date, "2026-11-02");
    expect(screen.getByText("Period: 3 November 2026 – 2 March 2027")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Generate email draft" }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText("asrith@example.com")).toBeInTheDocument();
    expect(within(dialog).getByText("TD-OL-2026-0161 - Asrith Reddy Satti.pdf")).toBeInTheDocument();
    expect((within(dialog).getByLabelText("Email body") as HTMLTextAreaElement).value).toContain("Dear Asrith Reddy Satti,");
  });

  it("asks for the name before generating", async () => {
    window.localStorage.clear();
    const user = userEvent.setup();
    renderWithProviders(<OfferLettersTab />);
    await user.click(screen.getByRole("button", { name: "Generate email draft" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.getByText("Enter the name")).toBeInTheDocument();
  });
});
