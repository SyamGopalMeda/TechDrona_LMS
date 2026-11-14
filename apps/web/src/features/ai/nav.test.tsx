import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { PortalNav } from "@/components/shell/PortalNav";
import { mockApi } from "@/features/auth/test/mock-api";
import { PORTALS, type NavItem } from "@/lib/nav/portals";
import { resetNavAppsCache } from "./hooks/useNavApps";

vi.mock("next/navigation", () => ({ usePathname: () => "/trainer", useRouter: () => ({ push: vi.fn(), replace: vi.fn() }) }));

const cleanups: (() => void)[] = [];
afterEach(() => {
  while (cleanups.length) cleanups.pop()!();
  resetNavAppsCache();
});

const items: NavItem[] = [
  { href: "/trainer", label: "Home", screen: "X" },
  { href: "/trainer/engage", label: "Engage", screen: "X", appKey: "engage" },
  { href: "/trainer/paths", label: "Learning paths", screen: "X", appKey: "paths" },
];

describe("PortalNav app gating", () => {
  it("hides items whose app is turned off", async () => {
    const api = mockApi({
      "GET me/enabled-apps": { body: { organization_id: "o1", apps: { engage: false, paths: true }, ai_enabled: true } },
    });
    cleanups.push(api.restore);
    render(<PortalNav items={items} label="Trainer navigation" root="/trainer" />);
    expect(screen.getByRole("link", { name: "Engage" })).toBeInTheDocument(); // shown while loading
    await waitFor(() => expect(screen.queryByRole("link", { name: "Engage" })).not.toBeInTheDocument());
    expect(screen.getByRole("link", { name: "Learning paths" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Home" })).toBeInTheDocument();
  });

  it("fails open on error", async () => {
    const api = mockApi({ "GET me/enabled-apps": { status: 503, body: { code: "service_unavailable", status: 503, title: "x" } } });
    cleanups.push(api.restore);
    render(<PortalNav items={items} label="Trainer navigation" root="/trainer" />);
    await waitFor(() => expect(api.calls.length).toBe(1));
    await new Promise((r) => setTimeout(r, 20));
    expect(screen.getByRole("link", { name: "Engage" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Learning paths" })).toBeInTheDocument();
  });

  it("makes no request when no item is gated, and shares one request between navs", async () => {
    const api = mockApi({ "GET me/enabled-apps": { body: { organization_id: null, apps: {}, ai_enabled: true } } });
    cleanups.push(api.restore);
    render(<PortalNav items={[items[0]!]} label="a" root="/trainer" />);
    expect(api.calls.length).toBe(0);
    render(<PortalNav items={items} label="b" root="/trainer" />);
    render(<PortalNav items={items} label="c" root="/trainer" />);
    await waitFor(() => expect(api.calls.length).toBe(1));
  });

  it("tags the engage, paths and assignment nav entries", () => {
    const keyed = Object.values(PORTALS).flatMap((p) => p.nav.filter((n) => n.appKey).map((n) => `${n.href}:${n.appKey}`));
    expect(keyed).toEqual(
      expect.arrayContaining([
        "/app/engage:engage",
        "/app/path/my:paths",
        "/app/assignments:assignments",
        "/trainer/engage:engage",
        "/trainer/paths:paths",
        "/trainer/assignments:assignments",
      ]),
    );
  });
});
