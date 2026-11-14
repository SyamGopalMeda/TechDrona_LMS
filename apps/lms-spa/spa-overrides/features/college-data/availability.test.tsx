import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { checkCollegePortal, isCollegePortalPage, resetCollegePortalCheck } from "./availability";
import { CollegeDataPortal } from "./CollegeDataPortal";

/* Live audit 2026-11-14 (admin.md F1): the College Data Portal is not deployed on Hosting yet. */
afterEach(() => {
  vi.unstubAllGlobals();
  resetCollegePortalCheck();
});

const SPA_SHELL = '<!doctype html><html><head><title>Tech Drona</title></head><body><div id="root"></div><script type="module" src="/assets/index-abc.js"></script></body></html>';
const PORTAL = "<!doctype html><html><head><title>Tech Drona — Outreach Portal</title></head><body><main></main></body></html>";

describe("College Data Portal availability", () => {
  it("tells the real portal page from the LMS app fallback and from errors", () => {
    expect(isCollegePortalPage(200, PORTAL)).toBe(true);
    expect(isCollegePortalPage(200, SPA_SHELL)).toBe(false);
    expect(isCollegePortalPage(404, PORTAL)).toBe(false);
    expect(isCollegePortalPage(502, "")).toBe(false);
  });

  it("is unknown (null) when the check itself fails", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => Promise.reject(new TypeError("offline"))));
    await expect(checkCollegePortal()).resolves.toBeNull();
  });

  it("the Admin page shows 'being moved' instead of a blocked frame while the portal is missing", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(SPA_SHELL, { status: 200, headers: { "content-type": "text/html" } })));
    render(<CollegeDataPortal />);
    expect(await screen.findByText("College Data Portal is being moved")).toBeInTheDocument();
    expect(screen.queryByTitle("College Data Portal")).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "All modules" })).toHaveAttribute("href", "/modules");
  });

  it("embeds the portal once it is deployed", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(PORTAL, { status: 200, headers: { "content-type": "text/html" } })));
    render(<CollegeDataPortal />);
    await waitFor(() => expect(screen.getByTitle("College Data Portal").tagName).toBe("IFRAME"));
    expect(screen.queryByText("College Data Portal is being moved")).not.toBeInTheDocument();
  });
});
