import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { mockApi, renderWithProviders } from "@/features/auth/test/mock-api";
import { PORTALS } from "@/lib/nav/portals";
import { AccountMenu } from "./AccountMenu";
import { MobileTabBar, STUDENT_TABS, isFocusRoute } from "./MobileTabBar";
import { PortalFrame, StaffMenu } from "./PortalFrame";
import { PortalNav } from "./PortalNav";

const nav = vi.hoisted(() => ({ pathname: "/app/practice/aptitude" }));
vi.mock("next/navigation", () => ({ usePathname: () => nav.pathname, useRouter: () => ({ push: vi.fn(), replace: vi.fn() }) }));

let restore: (() => void) | undefined;
afterEach(() => {
  restore?.();
  restore = undefined;
  nav.pathname = "/app/practice/aptitude";
  window.localStorage.clear();
});

describe("PortalNav sections (Phase 1.5)", () => {
  it("sections the student nav with expanded disclosure headings and 44px items", () => {
    nav.pathname = "/app/tests";
    render(<PortalNav items={PORTALS.student.nav} label="Student navigation" root="/app" />);
    const navEl = screen.getByRole("navigation", { name: "Student navigation" });
    for (const s of ["Learn", "Practice & tests", "Placement", "Account"]) {
      expect(within(navEl).getByRole("button", { name: s })).toHaveAttribute("aria-expanded", "true");
    }
    const active = screen.getByRole("link", { name: "Tests" });
    expect(active).toHaveAttribute("aria-current", "page");
    expect(active).toHaveClass("min-h-touch");
    expect(screen.getByRole("link", { name: "Interview prep" })).toHaveAttribute("href", "/app/interview-prep");
  });

  it("opens only the current section of the long admin nav; sections toggle", async () => {
    nav.pathname = "/finance/orders/42";
    render(<PortalNav items={PORTALS.admin.nav} label="Admin navigation" root="/admin" />);
    expect(screen.getByRole("button", { name: "Payments" })).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("link", { name: "Orders" })).toHaveAttribute("aria-current", "page");
    const people = screen.getByRole("button", { name: "People" });
    expect(people).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByRole("link", { name: "Users" })).not.toBeInTheDocument();
    await userEvent.click(people);
    expect(people).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("link", { name: "Users" })).toBeVisible();
  });

  it("finds a page from the search box and remembers opened sections", async () => {
    nav.pathname = "/admin";
    const { unmount } = render(<PortalNav items={PORTALS.admin.nav} label="Admin navigation" root="/admin" searchable />);
    await userEvent.type(screen.getByRole("searchbox", { name: "Find a page" }), "refu");
    const results = screen.getByRole("list", { name: "Matching pages" });
    expect(within(results).getByRole("link", { name: /Refunds/ })).toHaveAttribute("href", "/finance/refunds");
    expect(within(results).queryByRole("link", { name: /Users/ })).not.toBeInTheDocument();
    await userEvent.clear(screen.getByRole("searchbox", { name: "Find a page" }));
    await userEvent.click(screen.getByRole("button", { name: "Security" }));
    unmount();
    render(<PortalNav items={PORTALS.admin.nav} label="Admin navigation" root="/admin" searchable />);
    expect(await screen.findByRole("link", { name: "Risk rules" })).toBeVisible();
  });

  it("scrolls the current item into view", () => {
    const spy = vi.fn();
    const original = Element.prototype.scrollIntoView;
    Element.prototype.scrollIntoView = spy;
    try {
      nav.pathname = "/security/rules";
      render(<PortalNav items={PORTALS.admin.nav} label="Admin navigation" root="/admin" />);
      expect(spy).toHaveBeenCalledWith({ block: "nearest" });
    } finally {
      Element.prototype.scrollIntoView = original;
    }
  });
});

describe("MobileTabBar More sheet (Phase 1.6)", () => {
  it("is a titled sheet over a scrim with a close button, without the tab destinations", async () => {
    renderWithProviders(<MobileTabBar tabs={STUDENT_TABS} nav={PORTALS.student.nav} label="Student navigation" root="/app" />);
    const more = screen.getByRole("button", { name: "More" });
    await userEvent.click(more);
    const sheet = screen.getByRole("dialog", { name: "More" });
    const sheetNav = within(sheet).getByRole("navigation", { name: "Student navigation" });
    expect(within(sheetNav).queryByRole("link", { name: "Tests" })).not.toBeInTheDocument();
    expect(within(sheetNav).getByRole("link", { name: "Billing" })).toBeInTheDocument();
    await userEvent.click(within(sheet).getByRole("button", { name: "Close menu" }));
    expect(screen.queryByRole("dialog", { name: "More" })).not.toBeInTheDocument();
    expect(more).toHaveFocus();
    expect(more).toHaveClass("text-xs");
  });

  it("treats checkout as a focus route", () => {
    expect(isFocusRoute("/app/checkout/new")).toBe(true);
    expect(isFocusRoute("/app/checkout/ord_1")).toBe(true);
    expect(isFocusRoute("/app/billing")).toBe(false);
  });
});

describe("PortalFrame and StaffMenu (Phase 1.6)", () => {
  it("drops the sidebar on focus routes and keeps it elsewhere", () => {
    nav.pathname = "/app/coding/two-sum";
    const { container, unmount } = render(
      <PortalFrame nav={PORTALS.student.nav} label="Student navigation" root="/app" isStudent>
        <p>page</p>
      </PortalFrame>,
    );
    expect(container.querySelector("aside")).toBeNull();
    expect(screen.getByRole("main")).toHaveTextContent("page");
    unmount();
    nav.pathname = "/app/tests";
    // The sidebar footer signs out (useSignOut needs the toast provider).
    const again = renderWithProviders(
      <PortalFrame nav={PORTALS.student.nav} label="Student navigation" root="/app" isStudent>
        <p>page</p>
      </PortalFrame>,
    );
    const aside = again.container.querySelector("aside");
    expect(aside).not.toBeNull();
    expect(within(aside as HTMLElement).getByRole("button", { name: "Sign out" })).toBeInTheDocument();
    expect(within(aside as HTMLElement).getByRole("link", { name: "Tech Drona website" })).toHaveAttribute("href", "https://35-244-50-26.sslip.io");
  });

  it("shows the current page in the staff Menu button and closes on navigation and Escape", async () => {
    nav.pathname = "/trainer/grading";
    const { rerender } = render(<StaffMenu nav={PORTALS.trainer.nav} label="Trainer navigation" root="/trainer" />);
    const button = screen.getByRole("button", { name: /Menu.*Grading/ });
    await userEvent.click(button);
    expect(button).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("navigation", { name: "Trainer navigation" })).toBeInTheDocument();
    nav.pathname = "/trainer/tests";
    rerender(<StaffMenu nav={PORTALS.trainer.nav} label="Trainer navigation" root="/trainer" />);
    await waitFor(() => expect(screen.queryByRole("navigation", { name: "Trainer navigation" })).not.toBeInTheDocument());
    const now = screen.getByRole("button", { name: /Menu.*Tests/ });
    await userEvent.click(now);
    await userEvent.keyboard("{Escape}");
    expect(now).toHaveAttribute("aria-expanded", "false");
    expect(now).toHaveFocus();
  });
});

describe("AccountMenu (Phase 1.6)", () => {
  it("shows who is signed in, account links and sign out; Escape closes it", async () => {
    restore = mockApi({ "GET me": { body: { user: { id: "u1", email: "asha@example.com" }, profile: { display_name: "Asha Rao" } } } }).restore;
    renderWithProviders(<AccountMenu links={[{ href: "/app/settings/profile", label: "Settings" }]} />);
    const button = await screen.findByRole("button", { name: "Account: Asha Rao" });
    await userEvent.click(button);
    expect(button).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText("asha@example.com")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Settings" })).toHaveAttribute("href", "/app/settings/profile");
    expect(screen.getByRole("button", { name: "Sign out" })).toBeInTheDocument();
    await userEvent.keyboard("{Escape}");
    expect(button).toHaveAttribute("aria-expanded", "false");
    expect(button).toHaveFocus();
  });

  it("still works when the profile can't be loaded", async () => {
    const api = mockApi({ "GET me": { status: 500, body: { title: "x" } } });
    restore = api.restore;
    renderWithProviders(<AccountMenu links={[]} />);
    await waitFor(() => expect(api.calls.length).toBe(1));
    await act(async () => {});
    expect(screen.getByRole("button", { name: "Account" })).toBeInTheDocument();
  });
});
