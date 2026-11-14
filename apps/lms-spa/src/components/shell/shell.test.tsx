import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { mockApi, renderWithProviders } from "@/features/auth/test/mock-api";
import { PORTALS } from "@/lib/nav/portals";
import { MobileTabBar, STUDENT_TABS, isFocusRoute } from "./MobileTabBar";
import { PortalSwitcher } from "./PortalSwitcher";

const nav = vi.hoisted(() => ({ pathname: "/app/practice/aptitude" }));
vi.mock("next/navigation", () => ({ usePathname: () => nav.pathname, useRouter: () => ({ push: vi.fn(), replace: vi.fn() }) }));

let restore: (() => void) | undefined;
afterEach(() => restore?.());

describe("MobileTabBar (FE-32)", () => {
  it("renders Home · Learn · Practice · Tests · More and marks the active tab", async () => {
    renderWithProviders(<MobileTabBar tabs={STUDENT_TABS} nav={PORTALS.student.nav} label="Student navigation" root="/app" />);
    expect(screen.getByRole("navigation", { name: "Primary" })).toHaveTextContent("HomeLearnPracticeTestsMore");
    expect(screen.getByRole("link", { name: "Practice" })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("link", { name: "Home" })).not.toHaveAttribute("aria-current");
    const more = screen.getByRole("button", { name: "More" });
    expect(more).toHaveAttribute("aria-expanded", "false");
    await userEvent.click(more);
    expect(screen.getByRole("navigation", { name: "Student navigation" })).toBeInTheDocument();
    await userEvent.keyboard("{Escape}");
    expect(screen.queryByRole("navigation", { name: "Student navigation" })).not.toBeInTheDocument();
  });

  it("puts the More sheet after the bar, focuses it on open and returns focus on Escape (audit S3)", async () => {
    renderWithProviders(<MobileTabBar tabs={STUDENT_TABS} nav={PORTALS.student.nav} label="Student navigation" root="/app" />);
    const more = screen.getByRole("button", { name: "More" });
    await userEvent.click(more);
    const sheetNav = screen.getByRole("navigation", { name: "Student navigation" });
    const bar = screen.getByRole("navigation", { name: "Primary" });
    expect(bar.compareDocumentPosition(sheetNav) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(sheetNav.contains(document.activeElement)).toBe(true);
    await userEvent.keyboard("{Escape}");
    expect(more).toHaveFocus();
  });
});

describe("MobileTabBar on focus-shell routes (final verification, mobile e2e)", () => {
  afterEach(() => {
    nav.pathname = "/app/practice/aptitude";
  });

  it("classifies the focus routes from design-system §4", () => {
    for (const p of ["/app/attempts/a1", "/app/attempts/a1/resume", "/app/practice/sessions/ps1", "/app/learn/dsa/l1", "/app/coding/two-sum"]) {
      expect(isFocusRoute(p), p).toBe(true);
    }
    for (const p of ["/app", "/app/practice", "/app/practice/aptitude", "/app/coding", "/app/coding/two-sum/submissions", "/app/attempts/a1/submitted", "/app/tests"]) {
      expect(isFocusRoute(p), p).toBe(false);
    }
  });

  it("does not render over a practice session's bottom action bar", () => {
    nav.pathname = "/app/practice/sessions/ps1";
    renderWithProviders(<MobileTabBar tabs={STUDENT_TABS} nav={PORTALS.student.nav} label="Student navigation" root="/app" />);
    expect(screen.queryByRole("navigation", { name: "Primary" })).not.toBeInTheDocument();
  });
});

describe("PortalSwitcher (FE-32)", () => {
  it("lists granted portals from me/grants when there is more than one", async () => {
    restore = mockApi({ "GET me/grants": { body: { data: [], portals: ["/app", "/trainer"] } } }).restore;
    renderWithProviders(<PortalSwitcher current="student" />);
    expect(await screen.findByText("Switch portal")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Trainer" })).toHaveAttribute("href", "/trainer");
  });

  it("is hidden for single-portal users", async () => {
    const api = mockApi({ "GET me/grants": { body: { data: [], portals: ["/app"] } } });
    restore = api.restore;
    renderWithProviders(<PortalSwitcher current="student" />);
    await waitFor(() => expect(api.calls.length).toBe(1));
    expect(screen.queryByText("Switch portal")).not.toBeInTheDocument();
  });
});

describe("shell identity reads share the session cache (docs/perf/spa-requests.md)", () => {
  it("two switchers and the account menu make one me/grants and one me request", async () => {
    const { AccountMenu } = await import("./AccountMenu");
    const api = mockApi({
      "GET me/grants": { body: { data: [], portals: ["/app", "/trainer"] } },
      "GET me": { body: { user: { email: "a@example.com" }, profile: { display_name: "Asha Rao" } } },
    });
    restore = api.restore;
    renderWithProviders(
      <>
        <PortalSwitcher current="student" />
        <PortalSwitcher current="trainer" />
        <AccountMenu links={[]} />
      </>,
    );
    expect(await screen.findAllByText("Switch portal")).toHaveLength(2);
    expect(await screen.findByRole("button", { name: "Account: Asha Rao" })).toBeInTheDocument();
    expect(api.calls.filter((c) => c.path === "me/grants")).toHaveLength(1);
    expect(api.calls.filter((c) => c.path === "me")).toHaveLength(1);
  });
});
