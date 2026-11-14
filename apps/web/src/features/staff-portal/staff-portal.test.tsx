import { render, screen } from "@testing-library/react";
import type { ReactElement } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ToastProvider } from "@/components/ui";
import { ApiError } from "@/lib/api/errors";
import { canEnterPortal, homePortal, reachablePortals } from "./access";

const server = vi.hoisted(() => ({ hasSessionCookie: vi.fn(), serverApiGet: vi.fn() }));
const redirect = vi.hoisted(() =>
  vi.fn((to: string) => {
    throw new Error(`REDIRECT ${to}`);
  }),
);
vi.mock("server-only", () => ({}));
vi.mock("@/lib/api/server", () => server);
vi.mock("next/navigation", () => ({ redirect, useRouter: () => ({ push: vi.fn(), replace: vi.fn(), refresh: vi.fn() }) }));

const { StaffPortalGate } = await import("./StaffPortalGate");

afterEach(() => {
  server.hasSessionCookie.mockReset();
  server.serverApiGet.mockReset();
  redirect.mockClear();
});

async function renderGate(portal: Parameters<typeof StaffPortalGate>[0]["portal"]) {
  const el = (await StaffPortalGate({ portal, children: <p>PORTAL CONTENT</p> })) as ReactElement;
  return render(<ToastProvider>{el}</ToastProvider>);
}

describe("ADM-12 staff portal role gate", () => {
  it("maps /me/grants portals to portal access; super admin may open staff read views", () => {
    expect(canEnterPortal(["/app"], "admin")).toBe(false);
    expect(canEnterPortal(["/app"], "studio")).toBe(false);
    expect(canEnterPortal(["/trainer"], "trainer")).toBe(true);
    expect(canEnterPortal(["/desk"], "support")).toBe(true);
    expect(canEnterPortal(["/finance"], "security")).toBe(false);
    expect(canEnterPortal(["/admin"], "security")).toBe(true);
    expect(canEnterPortal(undefined, "trainer")).toBe(false);
    expect(canEnterPortal(["/evaluator"], "evaluator")).toBe(true);
    expect(canEnterPortal(["/trainer"], "evaluator")).toBe(false);
    // The api maps the evaluator role to /trainer; a live evaluator grant still opens /evaluator.
    expect(canEnterPortal(["/trainer"], "evaluator", ["evaluator"])).toBe(true);
    expect(canEnterPortal(["/trainer"], "evaluator", ["trainer"])).toBe(false);
    expect(canEnterPortal(["/admin"], "finance")).toBe(true);
    expect(canEnterPortal(["/admin"], "evaluator")).toBe(true);
    // D2: finance / support / security / mentoring are Admin sections, not separate portals.
    expect(reachablePortals(["/app", "/desk", "/evaluator", "/admin"])).toEqual([
      { href: "/app", title: "Student" },
      { href: "/evaluator", title: "Evaluator" },
      { href: "/admin", title: "Admin" },
    ]);
  });

  it("picks the home portal: most privileged first, null only without any portal", () => {
    expect(homePortal(["/app"])).toBe("/app");
    expect(homePortal(["/app", "/trainer"])).toBe("/trainer");
    expect(homePortal(["/admin", "/app"])).toBe("/admin");
    expect(homePortal(["/evaluator"])).toBe("/evaluator");
    expect(homePortal(["/desk"])).toBe("/desk");
    expect(homePortal([])).toBeNull();
    expect(homePortal(undefined)).toBeNull();
    expect(homePortal(["/nowhere"])).toBeNull();
  });

  it("redirects a student opening /admin straight to the Student portal (no 403 page)", async () => {
    server.hasSessionCookie.mockResolvedValue(true);
    server.serverApiGet.mockResolvedValue({ data: [{ role_key: "student" }], portals: ["/app"] });
    await expect(renderGate("admin")).rejects.toThrow("REDIRECT /app");
    expect(server.serverApiGet).toHaveBeenCalledWith("me/grants");
  });

  it("redirects a trainer opening the content studio to /trainer", async () => {
    server.hasSessionCookie.mockResolvedValue(true);
    server.serverApiGet.mockResolvedValue({ data: [{ role_key: "trainer" }], portals: ["/app", "/trainer"] });
    await expect(renderGate("studio")).rejects.toThrow("REDIRECT /trainer");
  });

  it("shows a friendly LMS page (no portal content) when the account opens no portal at all", async () => {
    server.hasSessionCookie.mockResolvedValue(true);
    server.serverApiGet.mockResolvedValue({ data: [], portals: [] });
    await renderGate("admin");
    expect(redirect).not.toHaveBeenCalled();
    expect(screen.queryByText("PORTAL CONTENT")).not.toBeInTheDocument();
    expect(screen.queryByText("403")).not.toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /account isn.t set up yet/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Sign out" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Get help" })).toHaveAttribute("href", "/help");
    // LMS chrome only: none of the company website's header links.
    expect(screen.queryByRole("link", { name: /contact/i })).not.toBeInTheDocument();
  });

  it("renders the portal for a granted role", async () => {
    server.hasSessionCookie.mockResolvedValue(true);
    server.serverApiGet.mockResolvedValue({ data: [], portals: ["/studio"] });
    await renderGate("studio");
    expect(screen.getByText("PORTAL CONTENT")).toBeInTheDocument();
  });

  it("does not fetch without a session (the shell redirects to sign-in)", async () => {
    server.hasSessionCookie.mockResolvedValue(false);
    await renderGate("finance");
    expect(server.serverApiGet).not.toHaveBeenCalled();
    expect(screen.getByText("PORTAL CONTENT")).toBeInTheDocument();
  });

  it("redirects to sign-in on 401 and falls through on other api failures", async () => {
    server.hasSessionCookie.mockResolvedValue(true);
    server.serverApiGet.mockRejectedValueOnce(new ApiError(401, null, "r1"));
    await expect(renderGate("evaluator")).rejects.toThrow("REDIRECT /login?next=%2Fevaluator");
    server.serverApiGet.mockRejectedValueOnce(new ApiError(503, null, "r2"));
    await renderGate("evaluator");
    expect(screen.getByText("PORTAL CONTENT")).toBeInTheDocument();
  });
});
