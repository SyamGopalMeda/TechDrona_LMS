import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { SegmentError } from "./SegmentError";

describe("SegmentError (per-segment error.tsx, UI audit 0.2)", () => {
  it("offers Try again (reset), a link to the portal home and the digest as a reference, never the raw message", async () => {
    const reset = vi.fn();
    const spy = vi.spyOn(console, "error").mockImplementation(() => {});
    const error = Object.assign(new Error("db password=hunter2"), { digest: "3982329900" });
    render(<SegmentError error={error} reset={reset} homeHref="/admin" homeLabel="Go to admin home" />);
    expect(screen.getByRole("heading", { level: 1, name: "This page could not be loaded" })).toHaveFocus();
    expect(screen.getByRole("link", { name: "Go to admin home" })).toHaveAttribute("href", "/admin");
    expect(screen.getByText("3982329900")).toBeInTheDocument();
    expect(screen.queryByText(/hunter2/)).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(reset).toHaveBeenCalled();
    spy.mockRestore();
  });
});
