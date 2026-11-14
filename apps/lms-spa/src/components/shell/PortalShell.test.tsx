import { act, render, screen, waitFor } from "@testing-library/react";
import { Suspense, type ReactNode } from "react";
import { MemoryRouter } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";

/*
 * SPA-specific test. Role/portal navigation
 * fix (docs/firebase/agents/role-nav-fix.md): PortalShell notes which portal's shell is on screen,
 * so the shared account pages (/app/settings/*, /app/account-status) that a staff member opens from
 * the account menu keep that staff shell instead of dropping them into the Student portal.
 */
vi.mock("@/spa/session", () => ({ probeSession: () => Promise.resolve("yes") }));
vi.mock("./PortalSwitcher", () => ({ PortalSwitcher: () => null }));
vi.mock("./ModuleSwitcher", () => ({ ModuleSwitcher: () => null }));
vi.mock("@/features/notifications/components/NotificationBell", () => ({ NotificationBell: () => null }));
vi.mock("./PortalFrame", () => ({
  PortalFrame: ({ title, actions, children, nav }: { title: string; actions: ReactNode; children: ReactNode; nav: { label: string }[] }) => (
    <div>
      <p>{`FRAME ${title}`}</p>
      <p data-testid="nav">{nav.map((n) => n.label).join("|")}</p>
      {actions}
      {children}
    </div>
  ),
}));
vi.mock("./AccountMenu", () => ({
  AccountMenu: ({ links }: { links: { href: string; label: string }[] }) => (
    <ul>
      {links.map((l) => (
        <li key={l.href}>{`${l.label} -> ${l.href}`}</li>
      ))}
    </ul>
  ),
}));
vi.mock("next/navigation", () => ({ usePathname: () => "/admin", useRouter: () => ({ push: vi.fn(), replace: vi.fn() }) }));

const { PortalShell } = await import("./PortalShell");
const { GateView, lastShellPortal, resetStudentGate } = await import("@/features/staff-portal/StaffPortalGate");
const { mockApi } = await import("@/features/auth/test/mock-api");
const { resetIntegrationsCache } = await import("./Integrations");

const cleanups: (() => void)[] = [];
afterEach(() => {
  resetStudentGate();
  resetIntegrationsCache();
  while (cleanups.length) cleanups.pop()!();
});

type Grants = { portals?: string[]; data?: { role_key: string }[] };

async function mount(portal: Parameters<typeof PortalShell>[0]["portal"], url: string, grants?: Grants) {
  await act(async () => {
    render(
      <MemoryRouter initialEntries={[url]}>
        <Suspense fallback={null}>
          <GateView decision={{ kind: "enter", grants }}>
            <PortalShell portal={portal}>
              <p>PAGE</p>
            </PortalShell>
          </GateView>
        </Suspense>
      </MemoryRouter>,
    );
  });
  await screen.findByText("PAGE");
}

describe("PortalShell portal memory (role/portal navigation fix)", () => {
  it("notes the staff portal on screen; its Settings link opens the shared account page", async () => {
    await mount("admin", "/admin/users");
    expect(lastShellPortal()).toBe("admin");
    expect(screen.getByText("FRAME Admin")).toBeInTheDocument();
    expect(screen.getByText("Settings -> /app/settings/profile")).toBeInTheDocument();
  });

  it("notes the trainer shell for an admin in their Teacher Portal", async () => {
    await mount("trainer", "/trainer/batches/b1");
    expect(lastShellPortal()).toBe("trainer");
  });

  it("students keep the same account links", async () => {
    await mount("student", "/app");
    expect(lastShellPortal()).toBe("student");
    expect(screen.getByText("Settings -> /app/settings/profile")).toBeInTheDocument();
    expect(screen.getByText("Account status -> /app/account-status")).toBeInTheDocument();
  });
});

/* Live audit 2026-11-14 (docs/qa/live-audit/fixes-nav.md): the shell lists only what the caller can use. */
describe("PortalShell nav visibility (live audit)", () => {
  const OWNER = { portals: ["/admin"], data: [{ role_key: "super_admin" }] };
  const integrations = (payments: boolean) => {
    const api = mockApi({ "GET public/integrations": { body: { integrations: { payments }, simple_auth: true } } });
    cleanups.push(api.restore);
  };

  it("admin: no gateway pages while payments are not connected, and no hidden items", async () => {
    integrations(false);
    await mount("admin", "/admin", OWNER);
    const nav = (await screen.findByTestId("nav")).textContent!.split("|");
    expect(nav).toContain("Admissions");
    expect(nav).toContain("System status");
    for (const gone of ["Revenue", "Orders", "Coupons", "Mentor sessions", "Feature flags", "Break-glass", "Corporate enquiries", "Risk rules"]) expect(nav).not.toContain(gone);
  });

  it("admin: gateway pages appear once payments are connected", async () => {
    integrations(true);
    await mount("finance", "/finance/admissions", OWNER);
    await waitFor(() => expect(screen.getByTestId("nav").textContent).toContain("Orders"));
  });

  it("an Admin in the Content studio sees only Courses, Review queue and account settings", async () => {
    integrations(false);
    await mount("studio", "/studio/courses", OWNER);
    expect(screen.getByTestId("nav").textContent).toBe("Review queue|Courses|Account settings");
  });

  it("a Content manager keeps the full studio nav", async () => {
    integrations(false);
    await mount("studio", "/studio", { portals: ["/studio"], data: [{ role_key: "content_manager" }] });
    expect(screen.getByTestId("nav").textContent).toContain("Taxonomy");
  });
});
