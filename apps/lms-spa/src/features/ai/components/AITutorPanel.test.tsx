import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { ApiError } from "@/lib/api/errors";
import { AITutorPanel, pairTurns } from "./AITutorPanel";

describe("AITutorPanel server-side history (SEC-17)", () => {
  it("pairs stored learner/tutor turns and skips unanswered questions", () => {
    expect(
      pairTurns([
        { role: "learner", content: "Q1" },
        { role: "tutor", content: "A1" },
        { role: "learner", content: "Q2 (no reply)" },
      ]).map((x) => [x.question, x.reply]),
    ).toEqual([["Q1", "A1"]]);
  });

  it("shows earlier turns loaded from the server and sends only the new question", async () => {
    const loadHistory = vi.fn().mockResolvedValue([
      { role: "learner", content: "Where do I start?", created_at: "2026-11-07T10:00:00Z" },
      { role: "tutor", content: "Read the input format first.", created_at: "2026-11-07T10:00:01Z" },
    ]);
    const onAsk = vi.fn().mockResolvedValue({ reply_md: "Try a loop.", used: 2, limit: 20 });
    render(<AITutorPanel used={1} limit={20} onAsk={onAsk} loadHistory={loadHistory} historyKey="a1:i1" />);
    expect(await screen.findByText("Read the input format first.")).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText("Your question or code"), "Next?");
    await userEvent.click(screen.getByRole("button", { name: /Guide/ }));
    expect(await screen.findByText("Try a loop.")).toBeInTheDocument();
    expect(onAsk).toHaveBeenCalledWith("guide", "Next?");
    expect(loadHistory).toHaveBeenCalledTimes(1);
  });

  it("explains a 429 rate_limited with the Retry-After wait", async () => {
    const err = new ApiError(429, { type: "t", title: "Too many", status: 429, detail: "x", code: "rate_limited", request_id: "r" }, "r", undefined, 30);
    render(<AITutorPanel used={0} limit={20} onAsk={vi.fn().mockRejectedValue(err)} />);
    await userEvent.type(screen.getByLabelText("Your question or code"), "Help");
    await userEvent.click(screen.getByRole("button", { name: /Explain/ }));
    expect(await screen.findByText(/Try again in 30 seconds/)).toBeInTheDocument();
  });
});
