import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { mockApi, renderWithProviders } from "@/features/auth/test/mock-api";
import { NotificationBell } from "./components/NotificationBell";
import { NotificationsInbox } from "./components/NotificationsInbox";
import { renderNotification, safeAppPath } from "./lib/templates";

vi.mock("next/navigation", () => ({ usePathname: () => "/app", useRouter: () => ({ push: vi.fn(), replace: vi.fn() }) }));

let restore: (() => void) | undefined;
afterEach(() => restore?.());

const page = { next_cursor: null, has_more: false, limit: 20 };
const items = [
  { notification_id: "n1", template_key: "security.unblock_info_requested", category: "security", priority: "high", data: { reference: "APL-2611-3HX9RB" }, read_at: null, created_at: "2026-11-03T10:00:00Z" },
  { notification_id: "n2", template_key: "batch.announcement", category: "learning", priority: "normal", data: { title: "Mock test on Friday", body: "Bring your laptop." }, read_at: "2026-11-03T11:00:00Z", created_at: "2026-11-02T10:00:00Z" },
];

describe("NotificationsInbox (STU-024, INV-07)", () => {
  it("renders readable titles, links and marks one / all as read", async () => {
    const api = mockApi({
      "GET me/notifications": { body: { data: items, unread_count: 1, page } },
      "POST me/notifications/n1/read": { body: { notification_id: "n1", read_at: "2026-11-03T12:00:00Z" } },
      "POST me/notifications/read-all": { body: { marked: 0 } },
    });
    restore = api.restore;
    renderWithProviders(<NotificationsInbox />);
    expect(await screen.findByText("We need a little more information")).toBeInTheDocument();
    expect(screen.getByText("Mock test on Friday")).toBeInTheDocument();
    expect(screen.getByText("Bring your laptop.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "View request" })).toHaveAttribute("href", "/unblock-request?reference=APL-2611-3HX9RB#status");
    await userEvent.click(screen.getByRole("button", { name: /Mark “We need a little more information” as read/ }));
    await waitFor(() => expect(api.calls.some((c) => c.method === "POST" && c.path === "me/notifications/n1/read")).toBe(true));
    await userEvent.click(screen.getByRole("button", { name: /^Unread/ }));
    await waitFor(() => expect(api.calls.some((c) => c.url.includes("unread_only=true"))).toBe(true));
  });

  it("shows an empty state", async () => {
    restore = mockApi({ "GET me/notifications": { body: { data: [], unread_count: 0, page } } }).restore;
    renderWithProviders(<NotificationsInbox />);
    expect(await screen.findByText("No notifications yet")).toBeInTheDocument();
    // Nothing unread: the bulk action is hidden rather than shown disabled.
    expect(screen.queryByRole("button", { name: "Mark all as read" })).not.toBeInTheDocument();
    expect(screen.queryByText(/isn't available yet/)).not.toBeInTheDocument();
  });
});

describe("NotificationBell", () => {
  it("shows the unread count without triggering global handlers", async () => {
    const api = mockApi({ "GET me/notifications": { body: { data: [], unread_count: 3, page } } });
    restore = api.restore;
    renderWithProviders(<NotificationBell />);
    expect(await screen.findByRole("link", { name: "Notifications, 3 unread" })).toHaveAttribute("href", "/app/notifications");
    expect(api.calls[0]!.url).toContain("unread_only=true");
  });

  it("hides the count when the request fails", async () => {
    const api = mockApi({});
    restore = api.restore;
    renderWithProviders(<NotificationBell />);
    await waitFor(() => expect(api.calls.length).toBe(1));
    expect(screen.getByRole("link", { name: "Notifications" })).toBeInTheDocument();
    expect(api.navigate).not.toHaveBeenCalled();
  });
});

describe("notification templates", () => {
  it("only follows same-origin app paths from notification data", () => {
    expect(safeAppPath("/app/support/new?topic=assessment")).toBe("/app/support/new?topic=assessment");
    expect(safeAppPath("//evil.example")).toBeUndefined();
    expect(safeAppPath("/\\evil.example")).toBeUndefined();
    expect(safeAppPath("/\t/evil.example")).toBeUndefined();
    expect(safeAppPath("/api/v1/me/security/events/x/disown")).toBeUndefined();
    expect(safeAppPath("https://evil.example")).toBeUndefined();
  });

  it("maps the session-replay notice to the human not-me page, not the api URL", () => {
    const r = renderNotification({ template_key: "security.session_replay", category: "security", data: { event_ref: "EV-1", disown_url: "/api/v1/me/security/events/EV-1/disown" } });
    expect(r.href).toBe("/app/settings/security/not-me/EV-1");
    expect(renderNotification({ template_key: "unknown.key", category: "billing", data: {} }).title).toBe("Billing update");
  });
});
