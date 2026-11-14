import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes, useLocation } from "react-router";
import { OverlayHost, PortalUiProvider, type PortalUi } from "../../ui";
import { resetDialogsForTests } from "../../forms/host";
import { FormsHost } from "../../forms/host";
import { CollegePage } from "../College";
import { cleanupOverlays, json, mockApi, resetAll } from "../live/test-utils";
import { CollegeFormDialog } from "./CollegeForm";
import { examInfo, naacGrade, nirfText, ownershipText, shape, type CollegeData } from "./model";

let search = "";
function Probe() {
  search = useLocation().search;
  return null;
}
function renderCollege(path: string, ui: Partial<PortalUi> = {}) {
  const value: PortalUi = { overlayRoot: document.body, form: "desktop", coarse: false, canWrite: true, ...ui };
  return render(
    <MemoryRouter initialEntries={[path]}>
      <PortalUiProvider value={value}>
        <Routes>
          <Route
            path="/colleges/college/:id"
            element={
              <>
                <CollegePage />
                <Probe />
              </>
            }
          />
          <Route path="*" element={<Probe />} />
        </Routes>
        <FormsHost />
        <OverlayHost />
      </PortalUiProvider>
    </MemoryRouter>,
  );
}

const college = {
  id: "c9",
  sno: 12,
  name: "Vasireddy Venkatadri Institute of Technology",
  short_name: "VVIT",
  district_id: "guntur",
  city_id: "nambur",
  op_status: "operational",
  targeted: 1,
  phone: "0863-2399999",
  email: "office@vvit.net",
  website: "https://vvit.net",
  ownership: "Pvt autonomous",
  naac: "A+; 3.49; 2nd cycle (College site)",
  nirf: "Not in 2025 Engg top 300",
  tier: "Tier 1",
  verified_fields: { phone: { source: "https://vvit.net/contact", verified_on: "2026-11-01", verified_by: "Ravi" } },
  field_status: { phone: "verified", email: "unverified", website: "unverified", name: "unverified", ownership: "unverified" },
  data_status: "partly_verified",
};
const branches = [
  { id: 1, college_id: "c9", code: "CSE", name: "Computer Science", category: "it_core", is_relevant: 1, intake_per_year: 180, intake_basis: "verified", final_year: 170, final_year_basis: "estimated", eligible_estimate: 170, eligible_basis: "estimated", strength_total: 720, strength_basis: "estimated", rollup: { target: 20, enrolled: 5, remaining: 15 } },
  { id: 2, college_id: "c9", code: "ECE", name: "Electronics", category: "circuit", is_relevant: 1, intake_per_year: 120, intake_basis: "verified", final_year: 110, final_year_basis: "estimated", eligible_estimate: 66, eligible_basis: "estimated", rollup: {} },
  { id: 3, college_id: "c9", code: "CIV", name: "Civil", category: "core", is_relevant: 0, intake_per_year: 60, intake_basis: "verified", rollup: {} },
];
const people = [
  { id: 101, college_id: "c9", role: "college_lead", full_name: "Lakshmi Lead", phone: "9876543210", email: null, reports_to: null, status: "active", joined_on: null, assignment_status: "assigned" },
  { id: 102, college_id: "c9", role: "ambassador", full_name: "Arjun Amb", phone: "9876500000", email: null, reports_to: 101, status: "active", joined_on: null, branch_ids: [1], assignment_status: "assigned" },
];
const detail = {
  college,
  rollup: { target: 40, enrolled: 10, remaining: 30, pct: 0.25, on_track: false, pace_status: "behind" },
  branches,
  people,
  exams: [
    {
      id: 7,
      college_id: "c9",
      semester: "4-1",
      exam_body: "JNTUK",
      status: "Upcoming",
      evidence: "Officially confirmed",
      confidence: "High",
      endsem_start: "2026-12-01",
      endsem_end: "2026-12-12",
      source_url: "https://jntuk.edu.in/a.pdf ; https://vvit.net/exams",
      verified_on: "2026-11-03",
    },
  ],
  followups: [{ id: 5, scope_type: "branch", scope_id: "1", status: "open", due_date: "2026-11-20", title: "Visit CSE HOD", issue: null, owner_person_id: null, owner_name: null, notes: null, last_contact: null, created_at: "", created_by: "", done_at: null }],
  recent_activities: [],
  recent_enrollments: [],
  audit: [{ id: 1, at: "2026-11-10T09:30:00Z", actor: "Ravi", action: "update", entity: "branch", entity_id: "1", before: { intake_per_year: 120, code: "CSE" }, after: { intake_per_year: 180, code: "CSE" } }],
  contacts: [
    { id: 31, college_id: "c9", branch_id: null, name: "Office", role: "office", phone: "08632399999", email: null, basis: "pending", status: "untested" },
    { id: 32, college_id: "c9", branch_id: null, name: "Mr TPO", role: "tpo", phone: "9000000001", email: null, basis: "verified", status: "working", last_call: { called_at: "2026-11-12T10:00:00Z", outcome: "connected_interested" } },
  ],
  calls: [],
  call_info: { call_status: "in_progress", calls_total: 1, contact_counts: { total: 2, working: 1 } },
};
const meta = {
  districts: [{ id: "guntur", name: "Guntur" }],
  cities: [{ id: "nambur", district_id: "guntur", name: "Nambur" }],
  courses: [],
  settings: {},
  counts: {},
  demo: false,
};
const branchDetail = {
  branch: { ...branches[0], college_short_name: "VVIT", intake_source: "https://eapcet.ap.gov.in/seats", intake_year: "2026-27", notes: "From EAPCET." },
  rollup: { target: 20, enrolled: 5, remaining: 15, reached: 40 },
  people: [people[1]],
  followups: [],
  activities: [],
  enrollments: [],
};

function api(extra: Record<string, unknown> = {}) {
  return mockApi({ "GET colleges/c9": detail, "GET meta": meta, "GET people": people, "GET branches/1": branchDetail, "GET summary": { target: 40 }, ...extra });
}

beforeEach(() => {
  resetAll();
  vi.useFakeTimers({ shouldAdvanceTime: true, now: new Date("2026-11-14T10:00:00Z") });
});
afterEach(() => {
  cleanupOverlays();
  act(() => resetDialogsForTests());
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe("college model", () => {
  it("rewords research values", () => {
    expect(naacGrade("A+; 3.49; 2nd cycle (College site)")).toBe("A+");
    expect(nirfText("Not in 2025 Engg top 300")).toBe("Not ranked");
    expect(nirfText("Engg 201-300 (official)")).toBe("Engineering 201-300");
    expect(ownershipText("Pvt autonomous")).toBe("Private college (autonomous)");
  });
  it("shapes coverage and exam state", () => {
    const d = detail as unknown as CollegeData;
    const s = shape(d, null);
    expect(s.lead?.full_name).toBe("Lakshmi Lead");
    expect(s.branches.find((b) => b.code === "ECE")?._gap).toBe(true);
    expect(s.branches.find((b) => b.code === "CSE")?._gap).toBe(false);
    expect(s.branches.find((b) => b.code === "CSE")?._nextFu?.title).toBe("Visit CSE HOD");
    const ex = examInfo(d);
    expect(ex.next?.start).toBe("2026-12-01");
    expect(ex.outreachFrom).toBe("2026-12-13");
  });
});

describe("College page", () => {
  it("shows the header, KPIs and the college information with key fields first", async () => {
    api();
    renderCollege("/colleges/college/c9");
    expect(await screen.findByRole("heading", { level: 1, name: college.name })).toBeInTheDocument();
    expect(screen.getByText("Lakshmi Lead", { selector: "a" })).toHaveAttribute("href", "/colleges/person/101");
    expect(screen.getByText("Target branches with an ambassador")).toBeInTheDocument();
    expect(screen.getByText("1 / 2")).toBeInTheDocument();
    expect(screen.getByText("Office phone")).toBeInTheDocument();
    expect(screen.getByText("NAAC grade")).toBeInTheDocument();
    expect(screen.getByText("A+")).toBeInTheDocument();
    expect(screen.getByText("NIRF ranking (2025)")).toBeInTheDocument();
    expect(screen.getByText("Not ranked")).toBeInTheDocument();
    expect(screen.getByText("Private college (autonomous)")).toBeInTheDocument();
    // reference detail is folded under "More details"
    const more = screen.getByText("More details").closest("details")!;
    expect(within(more).getByText("Master list no.")).toBeInTheDocument();
    expect(within(more).getByText("Research tier")).toBeInTheDocument();
    expect(screen.getByText("Next steps")).toBeInTheDocument();
    expect(screen.getByText("1 target branch has no ambassador")).toBeInTheDocument();
  });

  it("switches tabs through the URL and shows the team tree with a vacant branch slot", async () => {
    api({ "GET performance": { rows: [{ id: 102, actual: 3, target: 5, status: "behind", pct: 60 }] } });
    renderCollege("/colleges/college/c9");
    fireEvent.click(await screen.findByRole("tab", { name: /Team/ }));
    expect(search).toContain("tab=team");
    expect(await screen.findByText("ECE — no ambassador")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Arjun Amb" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Add ambassador" })).toBeInTheDocument();
  });

  it("maps old tab names and shows the change history with plain field names", async () => {
    api();
    renderCollege("/colleges/college/c9?tab=history");
    expect(await screen.findByText("Change history")).toBeInTheDocument();
    await waitFor(() => expect(search).toContain("tab=activity"));
    expect(screen.getByText("seats / year")).toBeInTheDocument();
    expect(screen.getByText("Visit CSE HOD · CSE")).toBeInTheDocument();
  });

  it("branches tab: 3 figures per card, filters, empty search and the drawer from ?branch=", async () => {
    api();
    renderCollege("/colleges/college/c9?tab=branches");
    const cse = (await screen.findByRole("button", { name: "Open branch Computer Science" })) as HTMLElement;
    expect(within(cse).getByText("Seats / year")).toBeInTheDocument();
    expect(within(cse).getByText("Final-year students")).toBeInTheDocument();
    expect(within(cse).getByText("Likely prospects (est.)")).toBeInTheDocument();
    expect(within(cse).queryByText("Students, all 4 years (est.)")).toBeNull();
    expect(screen.getByText("3 branches")).toBeInTheDocument();
    fireEvent.click(screen.getByLabelText("Target branches only"));
    expect(screen.getByText("Showing 2 of 3")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Find a branch"), { target: { value: "zzz" } });
    expect(screen.getByText("No branch matches “zzz”")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Show all branches" }));
    expect(screen.getByText("3 branches")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Open branch Computer Science" }));
    expect(search).toContain("branch=1");
    const dlg = await screen.findByRole("dialog");
    expect(await within(dlg).findByText("Students, all 4 years (est.)")).toBeInTheDocument();
    expect(within(dlg).getByText("Target branch")).toBeInTheDocument();
    expect(within(dlg).getByText("eapcet.ap.gov.in")).toBeInTheDocument();
    expect(within(dlg).getByText("(2026-27)", { exact: false })).toBeInTheDocument();
    expect(within(dlg).getByText("From EAPCET.")).toBeInTheDocument();
  });

  it("exams tab gives every source URL its own link and one merged evidence badge", async () => {
    api();
    renderCollege("/colleges/college/c9?tab=exams");
    expect(await screen.findByText("Exam windows")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /jntuk\.edu\.in · PDF/ })).toHaveAttribute("href", "https://jntuk.edu.in/a.pdf");
    expect(screen.getByRole("link", { name: /vvit\.net/ })).toHaveAttribute("href", "https://vvit.net/exams");
    expect(screen.getByText("Official notice · high confidence")).toBeInTheDocument();
    expect(screen.getByText(/Next: 4-1 end-sem exams start 1 Dec 2026/)).toBeInTheDocument();
  });

  it("contacts tab lists working numbers first with the reviewed wording", async () => {
    api();
    renderCollege("/colleges/college/c9?tab=calls");
    const items = await screen.findAllByRole("listitem");
    const contactItems = items.filter((li) => li.classList.contains("vcc-item"));
    expect(contactItems[0]).toHaveTextContent("Mr TPO");
    expect(contactItems[1]).toHaveTextContent("Not tried yet");
    expect(screen.getByText("No calls logged yet")).toBeInTheDocument();
  });

  it("hides write actions for viewers", async () => {
    api();
    renderCollege("/colleges/college/c9", { canWrite: false });
    expect(await screen.findByRole("heading", { level: 1 })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Log call" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Edit details" })).toBeNull();
  });

  it("says when the college does not exist", async () => {
    mockApi({ "GET colleges/zz": () => json(404, { error: "Not found" }), "GET meta": meta });
    renderCollege("/colleges/college/zz");
    expect(await screen.findByText("College not found")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Browse all colleges" })).toHaveAttribute("href", "/colleges/colleges");
  });
});

describe("College form", () => {
  function renderForm(collegeId: string | null, onDone = vi.fn()) {
    render(
      <MemoryRouter>
        <PortalUiProvider value={{ overlayRoot: document.body, form: "desktop", coarse: false, canWrite: true }}>
          <CollegeFormDialog open collegeId={collegeId} defaults={{ district_id: "guntur" }} onDone={onDone} />
          <FormsHost />
          <OverlayHost />
        </PortalUiProvider>
      </MemoryRouter>,
    );
    return onDone;
  }

  it("edit sends only the changed fields with their source, and stamps unchanged ones via /verify", async () => {
    const calls = api({ "PATCH colleges/c9": { ok: true }, "POST colleges/c9/verify": { ok: true } });
    const onDone = renderForm("c9");
    const dlg = await screen.findByRole("dialog", { name: "Edit college — VVIT" });
    expect(within(dlg).getByText("Master list no. 12 (fixed)")).toBeInTheDocument();
    fireEvent.change(within(dlg).getByLabelText("Office email"), { target: { value: "Admin@VVIT.net" } });
    fireEvent.change(within(dlg).getByLabelText("Source for Office email"), { target: { value: "https://vvit.net/contact" } });
    fireEvent.change(within(dlg).getByLabelText("Source for Website"), { target: { value: "Checked the site" } });
    fireEvent.click(within(dlg).getByRole("button", { name: "Save changes" }));
    await waitFor(() => expect(onDone).toHaveBeenCalledWith({ id: "c9" }));
    const patch = calls.find((c) => c.method === "PATCH");
    expect(patch?.body).toEqual({ email: "admin@vvit.net", sources: { email: "https://vvit.net/contact" } });
    const verify = calls.find((c) => c.method === "POST" && c.path === "colleges/c9/verify");
    expect(verify?.body).toEqual({ fields: ["website"], source: "Checked the site" });
  });

  it("create validates, then posts the new college", async () => {
    const calls = mockApi({ "GET meta": meta, "GET colleges": [], "POST colleges": { id: "c171" } });
    const onDone = renderForm(null);
    const dlg = (await screen.findByRole("button", { name: "Add college" })).closest<HTMLElement>("[role=dialog]")!;
    fireEvent.click(within(dlg).getByRole("button", { name: "Add college" }));
    expect(await within(dlg).findByText("Required")).toBeInTheDocument();
    expect(within(dlg).getByText("Choose the city or town")).toBeInTheDocument();
    fireEvent.change(within(dlg).getByLabelText(/^Official name/), { target: { value: "New Engineering College" } });
    fireEvent.change(within(dlg).getByLabelText(/^City \/ town/), { target: { value: "nambur" } });
    fireEvent.change(within(dlg).getByLabelText("Office phone"), { target: { value: "abc" } });
    fireEvent.click(within(dlg).getByRole("button", { name: "Add college" }));
    expect(await within(dlg).findByText(/Use digits only/)).toBeInTheDocument();
    fireEvent.change(within(dlg).getByLabelText("Office phone"), { target: { value: "9876543210" } });
    fireEvent.click(within(dlg).getByRole("button", { name: "Add college" }));
    await waitFor(() => expect(onDone).toHaveBeenCalledWith({ id: "c171" }));
    const post = calls.find((c) => c.method === "POST" && c.path === "colleges");
    expect(post?.body).toMatchObject({ name: "New Engineering College", district_id: "guntur", city_id: "nambur", phone: "9876543210", targeted: 1, op_status: "operational" });
  });
});
