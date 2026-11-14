import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Exams } from "./Exams";
import { SourceLinks, evidenceLabel, sourceUrls } from "./exams/labels";
import { countdown, fourOneDone, textWindows, windowsOf, type ExamCollege } from "./exams/model";
import { cleanupOverlays, currentSearch, mockApi, renderPortal, resetAll } from "./live/test-utils";

const TODAY = "2026-11-14";
const meta = { districts: [{ id: "guntur", name: "Guntur" }, { id: "krishna", name: "Krishna" }], cities: [], courses: [], settings: {}, counts: {}, demo: false };
const colleges: ExamCollege[] = [
  {
    college_id: "c1",
    name: "Alpha Engineering College",
    district_id: "guntur",
    exam_state: "in_exams",
    outreach_from: "2026-12-01",
    rows: [
      { id: 11, semester: "3-1", status: "In Progress", endsem_start: "2026-11-10", endsem_end: "2026-11-20", source_url: "https://jntuk.edu.in/a.pdf; https://alpha.ac.in/t.pdf", evidence: "Officially confirmed", confidence: "High" },
    ],
  },
  {
    college_id: "c2",
    name: "Beta Institute",
    district_id: "krishna",
    exam_state: "clear",
    rows: [{ id: 21, semester: "4-1", status: "Completed", endsem_start: "2026-10-01", endsem_end: "2026-10-10" }],
  },
];

beforeEach(() => {
  resetAll();
  vi.useFakeTimers({ shouldAdvanceTime: true, now: new Date(`${TODAY}T06:00:00Z`) });
});
afterEach(() => {
  cleanupOverlays();
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe("exam model and labels", () => {
  it("parses windows, countdowns and the 4-1 rule", () => {
    expect(textWindows("Mid-II 2026-11-09 to 2026-11-14")).toEqual([{ start: "2026-11-09", end: "2026-11-14" }]);
    expect(windowsOf(colleges[0]!.rows![0]!)[0]).toMatchObject({ kind: "endsem", start: "2026-11-10", end: "2026-11-20", trust: "confirmed" });
    expect(countdown(colleges[0]!.rows![0]!).text).toBe("ends in 6 days");
    expect(fourOneDone(colleges[1]!)).toBe(true);
    expect(fourOneDone(colleges[0]!)).toBe(false);
  });

  it("labels evidence and splits multi-URL sources into separate links", () => {
    expect(evidenceLabel("Officially confirmed")).toBe("Official notice");
    expect(evidenceLabel("Officially confirmed", "High")).toBe("Official notice · high confidence");
    expect(sourceUrls("https://a.in/x.pdf, https://b.in/y.pdf")).toEqual(["https://a.in/x.pdf", "https://b.in/y.pdf"]);
    render(<SourceLinks text="see https://www.jntuk.edu.in/n.pdf;https://alpha.ac.in/t.pdf." />);
    const links = screen.getAllByRole("link");
    expect(links.map((a) => a.getAttribute("href"))).toEqual(["https://www.jntuk.edu.in/n.pdf", "https://alpha.ac.in/t.pdf"]);
    expect(links[0]).toHaveTextContent("jntuk.edu.in (1)");
  });
});

describe("Exams screen", () => {
  it("shows state cards, outreach panel and filters by state through the URL", async () => {
    mockApi({ "GET exams": colleges, "GET meta": meta, "GET live/announcements": { items: [], source: {} } });
    renderPortal(<Exams />, { path: "/colleges/exams?view=list" });
    expect(await screen.findByText("Exams & outreach windows")).toBeInTheDocument();
    await screen.findByText("2 of 2 colleges");
    const states = screen.getByRole("group", { name: "Filter by exam state" });
    fireEvent.click(within(states).getByRole("button", { name: /In exams now/ }));
    await waitFor(() => expect(currentSearch()).toContain("state=in_exams"));
    expect(screen.getByText("1 of 2 colleges")).toBeInTheDocument();
    // outreach panel: Beta finished 4-1
    expect(screen.getByText("Open now — 4-1 exams finished")).toBeInTheDocument();
    // list view: multi-URL source = two links
    expect(screen.getByRole("link", { name: "jntuk.edu.in (1)" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "alpha.ac.in (2)" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Clear filters" }));
    await waitFor(() => expect(screen.getByText("2 of 2 colleges")).toBeInTheDocument());
  });

  it("edits an exam row with PATCH and validates the source link", async () => {
    const calls = mockApi({ "GET exams": colleges, "GET meta": meta, "GET live/announcements": { items: [] }, "PATCH exams/11": { ok: true }, "POST exams": { id: 99 } });
    renderPortal(<Exams />, { path: "/colleges/exams?view=list" });
    fireEvent.click(await screen.findByRole("button", { name: "Edit 3-1 exam details for Alpha Engineering College" }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText("Edit exam details")).toBeInTheDocument();
    const src = within(dialog).getByLabelText("Source link");
    fireEvent.change(src, { target: { value: "" } });
    expect(within(dialog).getByText(/Needed when the status is "In progress"/)).toBeInTheDocument();
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    expect(calls.some((c) => c.method === "PATCH")).toBe(false);
    fireEvent.change(src, { target: { value: "https://jntuk.edu.in/new.pdf" } });
    fireEvent.change(within(dialog).getByLabelText("Mid exams"), { target: { value: "Mid-II 2026-11-09 to 2026-11-14" } });
    expect(within(dialog).getByText(/On the timeline: 9 Nov 2026 – 14 Nov 2026/)).toBeInTheDocument();
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(calls.find((c) => c.method === "PATCH")?.path).toBe("exams/11"));
    const body = calls.find((c) => c.method === "PATCH")!.body as Record<string, unknown>;
    expect(body).toMatchObject({ status: "In Progress", source_url: "https://jntuk.edu.in/new.pdf", mid_window: "Mid-II 2026-11-09 to 2026-11-14", verified_on: TODAY });
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    // a missing semester → POST
    fireEvent.click(screen.getByRole("button", { name: "Add 4-1 exam details for Alpha Engineering College" }));
    const d2 = await screen.findByRole("dialog");
    expect(within(d2).getByText("Add exam details")).toBeInTheDocument();
    fireEvent.click(within(d2).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(calls.find((c) => c.method === "POST")?.body).toMatchObject({ college_id: "c1", semester: "4-1", status: "Unverified" }));
  });

  it("draws the timeline with editable bars and hides edits for viewers", async () => {
    mockApi({ "GET exams": colleges, "GET meta": meta, "GET live/announcements": { items: [] } });
    const { unmount } = renderPortal(<Exams />, { path: "/colleges/exams?view=timeline" });
    expect(await screen.findByRole("region", { name: "Exam timeline" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Alpha Engineering College, 3-1: End-sem exams/ })).toBeInTheDocument();
    unmount();
    renderPortal(<Exams />, { path: "/colleges/exams?view=list", ui: { canWrite: false } });
    await screen.findByText("2 of 2 colleges");
    expect(screen.queryByRole("button", { name: /exam details for/ })).toBeNull();
  });

  it("shows an error card with retry", async () => {
    mockApi({ "GET exams": () => new Response("{}", { status: 500 }), "GET meta": meta });
    renderPortal(<Exams />, { path: "/colleges/exams" });
    expect(await screen.findByText("Could not load the exam calendar")).toBeInTheDocument();
  });
});
