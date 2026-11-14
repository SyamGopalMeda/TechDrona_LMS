import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { College } from "../../lib/types";
import { LiveSources } from "../LiveSources";
import { Notices } from "../Notices";
import { CollegeLiveCard, ResearchBadge } from "./CollegeLiveCard";
import { liveSummary } from "./store";
import { cleanupOverlays, currentSearch, json, mockApi, renderPortal, resetAll } from "./test-utils";

const NOW = "2026-11-14T10:00:00Z";
const liveData = {
  now: NOW,
  refreshing: false,
  sources: [
    { id: "eapcet", name: "AP EAPCET 2026", url: "https://eapcet.ap.gov.in", last_status: "ok", last_success_at: "2026-11-14T09:50:00Z", last_attempt_at: "2026-11-14T09:50:00Z", fresh: true, item_count: 320 },
    { id: "jntuk", name: "JNTUK notifications", url: "https://jntuk.edu.in", last_status: "error", last_error: "timeout", last_success_at: "2026-11-13T09:00:00Z" },
  ],
  coverage: { colleges: 170, linked_eapcet: 150, linked_ecet: 120, linked_jntuk: 140, website_checked: 100, website_ok: 90 },
  automation: [{ topic: "Seats", status: "automatic", source: "EAPCET" }],
  recent_changes: [{ at: "2026-11-14T09:00:00Z", source: "eapcet", college_id: "c9", college_name: "Gamma College", summary: "left over 50 → 40" }],
};

beforeEach(() => {
  resetAll();
  vi.useFakeTimers({ shouldAdvanceTime: true, now: new Date(NOW) });
});
afterEach(() => {
  cleanupOverlays();
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe("Official sources", () => {
  it("asks for a background refresh once on mount and lists sources, coverage and changes", async () => {
    const calls = mockApi({ "GET live": liveData, "POST live/refresh": { ...liveData, refreshing: true } });
    renderPortal(<LiveSources />, { path: "/colleges/live" });
    expect(await screen.findByText("AP EAPCET 2026")).toBeInTheDocument();
    const gets = calls.filter((c) => c.method === "GET" && c.path === "live");
    expect(gets).toHaveLength(1);
    expect(gets[0]!.query.get("refresh")).toBe("1");
    expect(screen.getByText("1 source unreachable — showing last copy")).toBeInTheDocument();
    expect(screen.getByText("Unreachable — showing last copy")).toBeInTheDocument();
    expect(screen.getByText("In B.Tech counselling (EAPCET)")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Gamma College" })).toHaveAttribute("href", "/colleges/college/c9");
    fireEvent.click(screen.getByRole("button", { name: "Check sources now" }));
    await waitFor(() => expect(calls.some((c) => c.method === "POST" && c.path === "live/refresh")).toBe(true));
    expect(await screen.findByRole("button", { name: "Checking…" })).toBeDisabled();
  });

  it("says so when the server has no live endpoints", async () => {
    mockApi({});
    renderPortal(<LiveSources />, { path: "/colleges/live" });
    expect(await screen.findByText("Live official data is not available here")).toBeInTheDocument();
    expect(liveSummary()).toBeNull();
  });
});

describe("Official notices", () => {
  const answer = {
    items: [
      { uid: "n1", title: "B.Tech IV-I end exam timetable", url: "https://jntuk.edu.in/n1.pdf", date: "2026-11-13", category: "exam", is_new: true, attachments: [{ name: "Timetable", url: "https://jntuk.edu.in/t.pdf" }] },
      { uid: "n2", title: "Holiday circular", url: "javascript:alert(1)", date: "2026-11-01", category: "holiday" },
    ],
    categories: [
      { id: "exam", label: "Exams", count: 1 },
      { id: "holiday", label: "Holidays", count: 1 },
    ],
    source: { name: "JNTUK notifications", url: "https://jntuk.edu.in", last_status: "ok", last_success_at: "2026-11-14T09:00:00Z" },
  };

  it("lists notices with safe links, filters by type and search in the URL", async () => {
    const calls = mockApi({ "GET live/announcements": answer, "GET live": liveData });
    renderPortal(<Notices />, { path: "/colleges/notices" });
    expect(await screen.findByRole("link", { name: "B.Tech IV-I end exam timetable" })).toHaveAttribute("rel", "noopener noreferrer");
    expect(screen.getByText("New")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Timetable/ })).toHaveAttribute("href", "https://jntuk.edu.in/t.pdf");
    // a non-http link is shown as text
    expect(screen.queryByRole("link", { name: "Holiday circular" })).toBeNull();
    expect(screen.getByText("2 notices")).toBeInTheDocument();
    fireEvent.click(within(screen.getByRole("group", { name: "Notice type" })).getByRole("button", { name: /Exams/ }));
    await waitFor(() => expect(currentSearch()).toContain("category=exam"));
    await waitFor(() => expect(calls.some((c) => c.path === "live/announcements" && c.query.get("category") === "exam")).toBe(true));
    fireEvent.change(screen.getByRole("searchbox", { name: "Search notices" }), { target: { value: "timetable" } });
    await waitFor(() => expect(currentSearch()).toContain("q=timetable"));
    await waitFor(() => expect(calls.some((c) => c.path === "live/announcements" && c.query.get("q") === "timetable")).toBe(true));
  });
});

describe("College live card", () => {
  const college = { id: "c1", name: "Alpha Engineering College", short_name: "Alpha" } as College;
  const live = {
    checked_at: "2026-11-14T09:55:00Z",
    signal: "listed",
    signal_text: "Listed in the official counselling list.",
    presence: { eapcet: true, ecet: false, jntuk_affiliated: true, website: true },
    eapcet: {
      link: { basis: "research_code", code: "ALPH" },
      record: { code: "ALPH", name: "ALPHA ENGG COLLEGE", phone: "0863-222", branches: [{ code: "CSE", name: "Computer Science", total_seats: 120, filled: 100, left_over_seats: 20, fee: 60000 }], totals: { seats: 120, filled: 100, left_over: 20 } },
      source: { name: "AP EAPCET 2026", url: "https://eapcet.ap.gov.in", last_success_at: "2026-11-14T09:50:00Z" },
    },
    ecet: null,
    jntuk: { link: { basis: "name", score: 0.92 }, record: null, source: { name: "JNTUK", last_success_at: "2026-11-14T09:50:00Z" } },
    website: { ok: true, checked_at: "2026-11-14T09:40:00Z" },
    diffs: [{ field: "phone", label: "Office phone", ours: "0863-111", live: "0863-222", source_name: "AP EAPCET 2026", checked_at: "2026-11-14T09:50:00Z" }],
    announcements: [],
  };

  it("shows presence, records and accepts an official value with PATCH", async () => {
    const calls = mockApi({ "GET live/college/c1": live, "PATCH colleges/c1": { ok: true } });
    renderPortal(
      <>
        <CollegeLiveCard collegeId="c1" college={college} />
        <ResearchBadge />
      </>,
      { path: "/colleges/college/c1" },
    );
    expect(await screen.findByText("Listed in B.Tech counselling (EAPCET 2026)")).toBeInTheDocument();
    expect(screen.getByText("Linked by college code (ALPH)")).toBeInTheDocument();
    expect(screen.getByText("Linked by name — please check · 92% match")).toBeInTheDocument();
    expect(screen.getByText("Computer Science")).toBeInTheDocument();
    expect(screen.getByText("One value differs from the official source", { exact: false })).toBeInTheDocument();
    expect(screen.getAllByText("Researched Nov 2026 (not live)").length).toBeGreaterThan(0);
    fireEvent.click(screen.getByRole("button", { name: "Use official value" }));
    const dlg = await screen.findByRole("alertdialog").catch(() => screen.findByRole("dialog"));
    expect(within(dlg).getByText("Replace office phone?")).toBeInTheDocument();
    fireEvent.click(within(dlg).getByRole("button", { name: "Use official value" }));
    await waitFor(() => expect(calls.find((c) => c.method === "PATCH")?.body).toMatchObject({ phone: "0863-222", sources: { phone: "AP EAPCET 2026, fetched 14 Nov 2026" } }));
  });

  it("hides the accept action for viewers and shows the unavailable note on 404", async () => {
    mockApi({ "GET live/college/c1": live });
    const { unmount } = renderPortal(<CollegeLiveCard collegeId="c1" college={college} />, { ui: { canWrite: false } });
    await screen.findByText("Office phone", { selector: ".lv-diff__label" });
    expect(screen.queryByRole("button", { name: "Use official value" })).toBeNull();
    unmount();
    mockApi({ "GET live/college/c2": () => json(404, { error: "no" }) });
    renderPortal(<CollegeLiveCard collegeId="c2" college={college} />);
    expect(await screen.findByText("Live official data is not available here")).toBeInTheDocument();
  });
});
