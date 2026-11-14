import { act, render, screen } from "@testing-library/react";
import { Suspense } from "react";
import { MemoryRouter, Route, Routes } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ToastProvider } from "@/components/ui";
import { ApiError } from "@/lib/api/errors";
import { adminStudioRedirect, canEnterPortal, decideStudentArea, homePortal, isSharedAccountPath, reachablePortals, studioAccess, switcherPortals } from "./access";

const server = vi.hoisted(() => ({ hasSessionCookie: vi.fn(), serverApiGet: vi.fn() }));
const redirect = vi.hoisted(() =>
  vi.fn((to: string) => {
    throw new Error(`REDIRECT ${to}`);
  }),
);
vi.mock("server-only", () => ({}));
vi.mock("@/lib/api/server", () => server);
// Client redirects render their target (a full-document navigation, e.g. to /login, is not available in jsdom).
vi.mock("@/spa/boundary", () => ({ ClientRedirect: ({ to }: { to: string }) => <p>{`REDIRECT ${to}`}</p> }));
vi.mock("next/navigation", () => ({ redirect, useRouter: () => ({ push: vi.fn(), replace: vi.fn(), refresh: vi.fn() }) }));

const { decideStaffPortal, GateView, StaffPortalGate, StudentPortalGate, noteShellPortal, resetStudentGate, useStaffGrants } = await import("./StaffPortalGate");

afterEach(() => {
  resetStudentGate();
  server.hasSessionCookie.mockReset();
  server.serverApiGet.mockReset();
  redirect.mockClear();
});

/*
 * SPA port: the gate decides in the browser (decideStaffPortal) and GateView renders the decision.
 * A redirect decision goes through the mocked redirect() here so the assertions stay the same.
 */
async function renderGate(portal: Parameters<typeof decideStaffPortal>[0]) {
  const decision = await decideStaffPortal(portal);
  if (decision.kind === "redirect") redirect(decision.to);
  return render(
    <ToastProvider>
      <GateView decision={decision}>
        <p>PORTAL CONTENT</p>
      </GateView>
    </ToastProvider>,
  );
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
    // D2: finance / support / security are Admin sections, not separate portals.
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

/*
 * Role/portal navigation fix (docs/firebase/agents/role-nav-fix.md): the owner (super_admin only,
 * me/grants portals ["/admin"]) clicked "Settings" in the Admin account menu and landed in the
 * Student portal, then wandered on to /app/certificates. The Student portal is now gated like the
 * staff portals; the shared account pages render inside the caller's staff shell.
 */
const OWNER = { data: [{ role_key: "super_admin" }], portals: ["/admin"] };
const STUDENT = { data: [{ role_key: "student" }], portals: ["/app"] };
const NO_GRANTS = { data: [], portals: ["/app"] };
const TRAINER = { data: [{ role_key: "trainer" }], portals: ["/trainer"] };
const ADMIN_TEACHER = { data: [{ role_key: "super_admin" }, { role_key: "trainer" }], portals: ["/admin", "/trainer"] };
const ADMIN_STUDENT = { data: [{ role_key: "super_admin" }, { role_key: "student" }], portals: ["/admin", "/app"] };

describe("Student portal gate (decideStudentArea)", () => {
  it("knows the shared account pages", () => {
    for (const p of ["/app/settings/profile", "/app/settings/security/mfa", "/app/settings/security/not-me/x", "/app/account-status", "/app/settings"]) {
      expect(isSharedAccountPath(p)).toBe(true);
    }
    for (const p of ["/app", "/app/certificates", "/app/settingsx", "/app/support/new", "/admin/settings"]) expect(isSharedAccountPath(p)).toBe(false);
  });

  it("students (student grant or no grant at all) keep exactly the Student portal", () => {
    for (const g of [STUDENT, NO_GRANTS, ADMIN_STUDENT]) {
      for (const p of ["/app", "/app/certificates", "/app/settings/profile", "/app/account-status"]) {
        expect(decideStudentArea(g, p)).toEqual({ kind: "shell", portal: "student" });
      }
    }
    // Unknown grants (no session, api down, no portals) fail open, as before.
    expect(decideStudentArea(null, "/app/tests")).toEqual({ kind: "shell", portal: "student" });
    expect(decideStudentArea({ data: [] }, "/app/tests")).toEqual({ kind: "shell", portal: "student" });
  });

  it("sends a staff-only account opening a student page to its home portal", () => {
    expect(decideStudentArea(OWNER, "/app/certificates")).toEqual({ kind: "redirect", to: "/admin" });
    expect(decideStudentArea(OWNER, "/app")).toEqual({ kind: "redirect", to: "/admin" });
    expect(decideStudentArea(TRAINER, "/app/tests")).toEqual({ kind: "redirect", to: "/trainer" });
    expect(decideStudentArea({ data: [{ role_key: "content_manager" }], portals: ["/studio"] }, "/app")).toEqual({ kind: "redirect", to: "/studio" });
    expect(decideStudentArea({ data: [{ role_key: "evaluator" }], portals: ["/evaluator"] }, "/app/learning")).toEqual({ kind: "redirect", to: "/evaluator" });
  });

  it("renders the shared account pages in the staff shell: last staff portal if allowed, else home", () => {
    expect(decideStudentArea(OWNER, "/app/settings/profile")).toEqual({ kind: "shell", portal: "admin" });
    expect(decideStudentArea(OWNER, "/app/account-status", "finance")).toEqual({ kind: "shell", portal: "finance" });
    expect(decideStudentArea(TRAINER, "/app/settings/devices")).toEqual({ kind: "shell", portal: "trainer" });
    // An admin who is also a batch teacher, coming from "Your Teacher Portal", stays in the Trainer shell.
    expect(decideStudentArea(ADMIN_TEACHER, "/app/settings/profile", "trainer")).toEqual({ kind: "shell", portal: "trainer" });
    // A remembered portal the account cannot open is ignored.
    expect(decideStudentArea(TRAINER, "/app/settings/profile", "admin")).toEqual({ kind: "shell", portal: "trainer" });
    // Admin + student coming from the Admin portal keeps the Admin shell; from the Student portal, the Student shell.
    expect(decideStudentArea(ADMIN_STUDENT, "/app/settings/profile", "admin")).toEqual({ kind: "shell", portal: "admin" });
    expect(decideStudentArea(ADMIN_STUDENT, "/app/settings/profile", "student")).toEqual({ kind: "shell", portal: "student" });
  });
});

describe("StudentPortalGate (rendered)", () => {
  async function mount(url: string) {
    // act(): let the suspended gate resolve its me/grants promise (as in src/spa/spa.test.tsx).
    await act(async () => {
      render(
      <ToastProvider>
        <MemoryRouter initialEntries={[url]}>
          <Suspense fallback={<p>LOADING</p>}>
            <Routes>
              <Route path="/app/*" element={<StudentPortalGate>{(portal) => <p>SHELL {portal}</p>}</StudentPortalGate>} />
            </Routes>
          </Suspense>
        </MemoryRouter>
      </ToastProvider>,
      );
    });
    await screen.findByText(/SHELL|REDIRECT /);
  }

  it("owner: Settings opens in the Admin shell", async () => {
    server.hasSessionCookie.mockResolvedValue(true);
    server.serverApiGet.mockResolvedValue(OWNER);
    await mount("/app/settings/profile");
    expect(screen.getByText("SHELL admin")).toBeInTheDocument();
    expect(server.serverApiGet).toHaveBeenCalledWith("me/grants");
  });

  it("owner opening /app/certificates is sent to /admin", async () => {
    server.hasSessionCookie.mockResolvedValue(true);
    server.serverApiGet.mockResolvedValue(OWNER);
    await mount("/app/certificates");
    expect(screen.getByText("REDIRECT /admin")).toBeInTheDocument();
  });

  it("uses the shell the user came from (noted by PortalShell)", async () => {
    server.hasSessionCookie.mockResolvedValue(true);
    server.serverApiGet.mockResolvedValue(ADMIN_TEACHER);
    noteShellPortal("trainer");
    await mount("/app/settings/security");
    expect(screen.getByText("SHELL trainer")).toBeInTheDocument();
  });

  it("a student sees the Student shell everywhere under /app", async () => {
    server.hasSessionCookie.mockResolvedValue(true);
    server.serverApiGet.mockResolvedValue(STUDENT);
    await mount("/app/certificates");
    expect(screen.getByText("SHELL student")).toBeInTheDocument();
  });

  it("no session: no grants call, Student shell (which sends the visitor to sign-in)", async () => {
    server.hasSessionCookie.mockResolvedValue(false);
    await mount("/app/tests");
    expect(server.serverApiGet).not.toHaveBeenCalled();
    expect(screen.getByText("SHELL student")).toBeInTheDocument();
  });

  it("401 sends the visitor to sign-in", async () => {
    server.hasSessionCookie.mockResolvedValue(true);
    server.serverApiGet.mockRejectedValueOnce(new ApiError(401, null, "r1"));
    await mount("/app/tests?x=1");
    expect(screen.getByText("REDIRECT /login?next=%2Fapp%2Ftests%3Fx%3D1")).toBeInTheDocument();
  });

  it("api down: Student shell (fail open)", async () => {
    server.hasSessionCookie.mockResolvedValue(true);
    server.serverApiGet.mockRejectedValueOnce(new ApiError(503, null, "r2"));
    await mount("/app/tests");
    expect(screen.getByText("SHELL student")).toBeInTheDocument();
  });
});

/* Live audit 2026-11-14 (docs/qa/live-audit/fixes-nav.md): Admin in the Content studio, portal switcher. */
describe("Admin in the Content studio (admin.md F2)", () => {
  it("classifies studio access by role, not by the super-admin read rule", () => {
    expect(studioAccess(["/studio"])).toBe("full");
    expect(studioAccess(["/admin"], ["super_admin", "content_manager"])).toBe("full");
    expect(studioAccess(["/admin"], ["super_admin"])).toBe("admin");
    expect(studioAccess(["/trainer"], ["trainer"])).toBe("none");
    expect(studioAccess(undefined)).toBe("none");
  });

  it("keeps the course pages and the review queue, and sends every other studio page to the course list", () => {
    for (const ok of ["/studio/courses", "/studio/courses/c1", "/studio/courses/c1/edit?x=1", "/studio/review", "/studio/review/q1"]) expect(adminStudioRedirect(ok), ok).toBeNull();
    for (const no of ["/studio", "/studio/taxonomy", "/studio/questions", "/studio/question-banks", "/studio/reports/errors", "/studio/coding", "/studio/media", "/studio/tests", "/studio/coursesx"]) {
      expect(adminStudioRedirect(no), no).toBe("/studio/courses");
    }
  });

  async function mountStudio(url: string) {
    function Shell() {
      const g = useStaffGrants();
      return <p>{`STUDIO ${g?.portals?.join(",") ?? "?"}`}</p>;
    }
    await act(async () => {
      render(
        <ToastProvider>
          <MemoryRouter initialEntries={[url]}>
            <Suspense fallback={<p>LOADING</p>}>
              <Routes>
                <Route
                  path="/studio/*"
                  element={
                    <StaffPortalGate portal="studio">
                      <Shell />
                    </StaffPortalGate>
                  }
                />
              </Routes>
            </Suspense>
          </MemoryRouter>
        </ToastProvider>,
      );
    });
    await screen.findByText(/STUDIO|REDIRECT /);
  }

  it("redirects an Admin opening /studio/taxonomy to the course list", async () => {
    server.hasSessionCookie.mockResolvedValue(true);
    server.serverApiGet.mockResolvedValue(OWNER);
    await mountStudio("/studio/taxonomy");
    expect(screen.getByText("REDIRECT /studio/courses")).toBeInTheDocument();
  });

  it("lets an Admin into /studio/review and shares the grants with the shell", async () => {
    server.hasSessionCookie.mockResolvedValue(true);
    server.serverApiGet.mockResolvedValue(OWNER);
    await mountStudio("/studio/review");
    expect(screen.getByText("STUDIO /admin")).toBeInTheDocument();
  });

  it("a Content manager keeps every studio page", async () => {
    server.hasSessionCookie.mockResolvedValue(true);
    server.serverApiGet.mockResolvedValue({ data: [{ role_key: "content_manager" }], portals: ["/studio"] });
    await mountStudio("/studio/taxonomy");
    expect(screen.getByText("STUDIO /studio")).toBeInTheDocument();
  });
});

describe("Portal switcher list (admin.md F3)", () => {
  it("an Admin gets Admin and Content studio, and the Teacher portal only with a trainer grant", () => {
    expect(switcherPortals(["/admin"], ["super_admin"])).toEqual([
      { href: "/studio", title: "Content studio" },
      { href: "/admin", title: "Admin" },
    ]);
    expect(switcherPortals(ADMIN_TEACHER.portals, ["super_admin", "trainer"]).map((p) => p.href)).toEqual(["/trainer", "/studio", "/admin"]);
  });

  it("single-portal staff and students see only their own portal (switcher stays hidden)", () => {
    expect(switcherPortals(["/trainer"], ["trainer"])).toEqual([{ href: "/trainer", title: "Trainer" }]);
    expect(switcherPortals(["/app"], ["student"])).toEqual([{ href: "/app", title: "Student" }]);
    expect(switcherPortals(["/studio"], ["content_manager"])).toEqual([{ href: "/studio", title: "Content studio" }]);
    // The api maps evaluators to /evaluator; a live evaluator grant lists it even if portals lag.
    expect(switcherPortals(["/trainer"], ["trainer", "evaluator"]).map((p) => p.href)).toEqual(["/trainer", "/evaluator"]);
    expect(switcherPortals(undefined)).toEqual([]);
  });
});

/* Fewer identity requests (docs/perf/spa-requests.md): the gates read me/grants through the session cache. */
describe("portal gates and the session cache", () => {
  function mountAdmin() {
    return render(
      <ToastProvider>
        <MemoryRouter initialEntries={["/admin"]}>
          <Suspense fallback={<p>LOADING</p>}>
            <Routes>
              <Route
                path="/admin/*"
                element={
                  <StaffPortalGate portal="admin">
                    <p>ADMIN CONTENT</p>
                  </StaffPortalGate>
                }
              />
            </Routes>
          </Suspense>
        </MemoryRouter>
      </ToastProvider>,
    );
  }

  it("a second portal entry decides from the cached grants: no request, no probe, no suspension", async () => {
    server.hasSessionCookie.mockResolvedValue(true);
    server.serverApiGet.mockResolvedValue(OWNER);
    expect(await decideStaffPortal("admin")).toEqual({ kind: "enter", grants: OWNER });
    expect(server.serverApiGet).toHaveBeenCalledTimes(1);
    server.hasSessionCookie.mockClear();
    mountAdmin();
    // Rendered synchronously on the first pass (no LOADING / skeleton).
    expect(screen.getByText("ADMIN CONTENT")).toBeInTheDocument();
    expect(server.serverApiGet).toHaveBeenCalledTimes(1);
    expect(server.hasSessionCookie).not.toHaveBeenCalled();
  });

  it("the Student gate shares the same cached grants with the staff gate", async () => {
    server.hasSessionCookie.mockResolvedValue(true);
    server.serverApiGet.mockResolvedValue(OWNER);
    await decideStaffPortal("admin");
    await act(async () => {
      render(
        <ToastProvider>
          <MemoryRouter initialEntries={["/app/settings/profile"]}>
            <Routes>
              <Route path="/app/*" element={<StudentPortalGate>{(portal) => <p>SHELL {portal}</p>}</StudentPortalGate>} />
            </Routes>
          </MemoryRouter>
        </ToastProvider>,
      );
    });
    expect(screen.getByText("SHELL admin")).toBeInTheDocument();
    expect(server.serverApiGet).toHaveBeenCalledTimes(1);
  });

  it("shows the portal skeleton (not a blank page) while the grants load", async () => {
    server.hasSessionCookie.mockResolvedValue(true);
    let finish!: (v: unknown) => void;
    server.serverApiGet.mockReturnValue(new Promise((r) => (finish = r)));
    await act(async () => {
      mountAdmin();
    });
    expect(screen.queryByText("LOADING")).not.toBeInTheDocument();
    expect(screen.getByText("Loading…").closest("[aria-busy]")).toBeInTheDocument();
    await act(async () => {
      finish(OWNER);
    });
    expect(await screen.findByText("ADMIN CONTENT")).toBeInTheDocument();
    expect(server.serverApiGet).toHaveBeenCalledTimes(1);
  });
});
