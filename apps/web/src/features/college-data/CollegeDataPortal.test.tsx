import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { CollegeDataPortal, FRAME_LOAD_TIMEOUT_MS, fillHeight, loadedAsDocument } from "./CollegeDataPortal";

describe("CollegeDataPortal (ADM-015)", () => {
  it("embeds the same-origin portal and offers a full-screen link", async () => {
    render(<CollegeDataPortal />);
    expect(screen.getByRole("heading", { level: 1, name: "College Data Portal" })).toBeInTheDocument();
    const frame = await screen.findByTitle("College Data Portal");
    expect(frame.tagName).toBe("IFRAME");
    expect(frame).toHaveAttribute("src", "/college-portal/index.html");
    expect(frame).toHaveAttribute("referrerpolicy", "same-origin");
    const link = screen.getByRole("link", { name: /Open full screen/ });
    expect(link).toHaveAttribute("href", "/college-portal/index.html");
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", "noopener");
  });

  it("shows a loading state until the frame loads, then hides it", async () => {
    render(<CollegeDataPortal />);
    const frame = await screen.findByTitle("College Data Portal");
    expect(screen.getByRole("status")).toHaveTextContent("Loading the College Data Portal…");
    fireEvent.load(frame);
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  describe("slow frame fallback", () => {
    afterEach(() => vi.useRealTimers());
    it("offers Open full screen and Try again when the frame has not loaded in time", async () => {
      vi.useFakeTimers();
      render(<CollegeDataPortal />);
      await act(async () => {
        await Promise.resolve();
      });
      expect(screen.getByTitle("College Data Portal")).toBeInTheDocument();
      act(() => {
        vi.advanceTimersByTime(FRAME_LOAD_TIMEOUT_MS + 1);
      });
      expect(screen.getByText(/taking longer than usual/)).toBeInTheDocument();
      expect(screen.getAllByRole("link", { name: /Open full screen/ })).toHaveLength(2);
      act(() => {
        fireEvent.click(screen.getByRole("button", { name: "Try again" }));
      });
      expect(screen.queryByText(/taking longer than usual/)).not.toBeInTheDocument();
      expect(screen.getByTitle("College Data Portal")).toBeInTheDocument();
    });
  });

  it("fills the viewport below the frame without a fixed phone minimum of 600px", () => {
    expect(fillHeight(812, 200)).toBe(588);
    expect(fillHeight(500, 300)).toBe(320);
  });

  describe("loadedAsDocument (frame CSP is per document)", () => {
    afterEach(() => vi.restoreAllMocks());
    const navEntry = (name: string) => vi.spyOn(performance, "getEntriesByType").mockReturnValue([{ name } as PerformanceEntry]);

    it("is true when the document was loaded at this path", () => {
      navEntry("http://localhost:3000/admin/college-data?x=1");
      expect(loadedAsDocument("/admin/college-data")).toBe(true);
    });
    it("is false after a client-side navigation from another page", () => {
      navEntry("http://localhost:3000/admin");
      expect(loadedAsDocument("/admin/college-data")).toBe(false);
    });
    it("assumes true without Navigation Timing", () => {
      vi.spyOn(performance, "getEntriesByType").mockReturnValue([]);
      expect(loadedAsDocument("/admin/college-data")).toBe(true);
    });
  });
});
