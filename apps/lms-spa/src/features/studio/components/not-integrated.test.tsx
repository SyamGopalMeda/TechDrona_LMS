import { screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { mockApi, renderWithProviders } from "@/features/auth/test/mock-api";
import { AiNotIntegratedNotice, JudgeNotIntegratedNotice, resetNotIntegratedCache } from "./NotIntegrated";

let restore: (() => void) | undefined;
afterEach(() => {
  restore?.();
  resetNotIntegratedCache();
});

describe("not integrated notices (fake AI adapter / fake judge)", () => {
  it("says AI is not integrated while the api reports the placeholder adapter", async () => {
    ({ restore } = mockApi({ "GET me/enabled-apps": { body: { apps: {}, ai_enabled: true, ai_simulated: true } } }));
    renderWithProviders(<AiNotIntegratedNotice />);
    expect(await screen.findByText(/returns sample text, not real AI output/)).toBeInTheDocument();
  });

  it("says the code runner is not integrated while the judge is the placeholder", async () => {
    ({ restore } = mockApi({ "GET coding/languages": { body: { data: [], judge: { simulated: true } } } }));
    renderWithProviders(<JudgeNotIntegratedNotice />);
    expect(await screen.findByText(/code is not executed/)).toBeInTheDocument();
  });

  it("shows nothing when the read fails (no flag)", async () => {
    ({ restore } = mockApi({}));
    renderWithProviders(<JudgeNotIntegratedNotice />);
    await new Promise((r) => setTimeout(r, 20));
    expect(screen.queryByRole("note")).toBeNull();
  });
});
