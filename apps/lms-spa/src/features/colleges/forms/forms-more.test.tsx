import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";
import { configurePortalApi, resetPortalApiForTests } from "../lib/api";
import { clearPortalCacheForTests } from "../lib/cache";
import { PortalUiProvider } from "../ui/context";
import { OverlayHost, resetOverlaysForTests } from "../ui/Overlay";
import { FormsHost, resetDialogsForTests } from "./host";
import { editBranch } from "./Branch";
import { recordEnrollment } from "./Enrollment";
import { personDialog } from "./People";
import { parsePeriod, periodKey, periodLabel, saveTargetRow, mondayOf } from "./targets";

const json = (status: number, body: unknown) => new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });

type Route = (method: string, url: string, body: unknown) => Response | undefined;
function mockApi(route: Route) {
  const calls: { method: string; url: string; body: unknown }[] = [];
  const fetchImpl = vi.fn(async (url: string, init?: RequestInit) => {
    const method = (init?.method ?? "GET").toUpperCase();
    const body = init?.body ? JSON.parse(String(init.body)) : undefined;
    calls.push({ method, url, body });
    return route(method, url, body) ?? json(404, { error: "not found" });
  });
  configurePortalApi({ fetchImpl: fetchImpl as unknown as typeof fetch, onSignedOut: () => undefined });
  return calls;
}

function mount() {
  return render(
    <MemoryRouter>
      <PortalUiProvider value={{ overlayRoot: document.body, form: "desktop", coarse: false, canWrite: true }}>
        <FormsHost />
        <OverlayHost />
      </PortalUiProvider>
    </MemoryRouter>,
  );
}

const COLLEGE = {
  college: { id: "c9", name: "KL University", short_name: "KLU" },
  branches: [
    { id: 1, code: "CSE", name: "Computer Science", is_relevant: 1 },
    { id: 2, code: "ECE", name: "Electronics", is_relevant: 1 },
  ],
  people: [
    { id: 10, full_name: "Ravi Lead", role: "college_lead", status: "active", branch_ids: [] },
    { id: 11, full_name: "Anu Amb", role: "ambassador", status: "active", branch_ids: [2] },
  ],
};

afterEach(() => {
  act(() => {
    resetDialogsForTests();
    resetOverlaysForTests();
  });
  clearPortalCacheForTests();
  resetPortalApiForTests();
});

describe("target helpers", () => {
  it("parses and labels periods", () => {
    expect(parsePeriod("month:2026-11")).toEqual({ kind: "month", month: "2026-11" });
    expect(parsePeriod("2026-11-02")).toEqual({ kind: "week", week: "2026-11-02" });
    expect(parsePeriod("program")).toEqual({ kind: "programme" });
    expect(periodKey("week", null, "2026-11-02")).toBe("week:2026-11-02");
    expect(periodLabel("week:2026-11-02")).toBe("Week of 2 Nov 2026");
    expect(periodLabel("programme")).toBe("Programme");
    expect(periodLabel("month:2026-11")).toMatch(/November 2026/);
    expect(mondayOf("2026-11-05")).toBe("2026-11-02");
  });

  it("saveTargetRow falls back to POST on old servers, refuses min/max there", async () => {
    const calls = mockApi((m) => (m === "PUT" ? json(404, { error: "no" }) : m === "POST" ? json(201, { id: 1 }) : undefined));
    await saveTargetRow({ scope_type: "person", scope_id: 5, target: 3 });
    expect(calls.map((c) => c.method)).toEqual(["PUT", "POST"]);
    expect(calls[1]!.body).toMatchObject({ scope_type: "person", scope_id: "5", target: 3 });
    await expect(saveTargetRow({ scope_type: "person", scope_id: 5, target: 3, max: 4 })).rejects.toMatchObject({ status: 400 });
  });
});

describe("personDialog (add)", () => {
  it("validates the name and phone rule, then posts the person", async () => {
    const calls = mockApi((m, url) => {
      if (url.includes("/colleges/c9")) return json(200, COLLEGE);
      if (url.includes("/health")) return json(200, { version: "v4.2" });
      if (m === "GET" && url.includes("/people")) return json(200, { items: [] });
      if (m === "POST" && url.endsWith("/people")) return json(201, { id: 99, full_name: "Sai", role: "ambassador" });
      return undefined;
    });
    mount();
    let done: Promise<unknown>;
    act(() => {
      done = personDialog({ college_id: "c9" });
    });
    await screen.findByText("Add a person — KLU");
    // ambassador by default (the college has a lead); the only valid lead is pre-picked
    expect((screen.getByLabelText(/Reports to/) as HTMLSelectElement).value).toBe("10");
    fireEvent.click(screen.getByRole("button", { name: "Add person" }));
    expect(await screen.findByText("Name is required.")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText(/Full name/), { target: { value: "Sai" } });
    fireEvent.change(screen.getByLabelText(/Mobile number/), { target: { value: "12345" } });
    fireEvent.click(screen.getByRole("button", { name: "Add person" }));
    expect((await screen.findAllByText(/Enter a 10-digit Indian mobile number/)).length).toBeGreaterThan(0);
    fireEvent.change(screen.getByLabelText(/Mobile number/), { target: { value: "98765 43210" } });
    fireEvent.click(screen.getByRole("checkbox", { name: /ECE/ }));
    fireEvent.click(screen.getByRole("button", { name: "Add person" }));
    await waitFor(() => expect(calls.some((c) => c.method === "POST")).toBe(true));
    const post = calls.find((c) => c.method === "POST")!;
    expect(post.body).toMatchObject({ college_id: "c9", full_name: "Sai", role: "ambassador", reports_to: 10, phone: "+919876543210", branch_ids: [2], status: "active" });
    await expect(done!).resolves.toMatchObject({ id: 99 });
  });
});

describe("recordEnrollment", () => {
  it("fills the amount from the course price and posts the record", async () => {
    const calls = mockApi((m, url) => {
      if (url.includes("/colleges/c9")) return json(200, COLLEGE);
      if (url.includes("/meta")) return json(200, { districts: [], cities: [], courses: [{ id: 1, name: "Full-Stack", price_inr: 5000, active: 1 }, { id: 2, name: "Data", price_inr: 20000, active: 1 }], settings: {}, counts: {}, demo: false });
      if (m === "POST" && url.endsWith("/enrollments")) return json(201, { id: 7, stage: "confirmed" });
      return undefined;
    });
    mount();
    let done: Promise<unknown>;
    act(() => {
      done = recordEnrollment({ college_id: "c9" });
    });
    await screen.findByText("Record enrollment — KLU");
    fireEvent.change(screen.getByLabelText(/^Course/), { target: { value: "2" } });
    expect((screen.getByLabelText(/Amount paid/) as HTMLInputElement).value).toBe("20000");
    // choosing CSE hides the ECE ambassador from "Credit to"
    fireEvent.change(screen.getByLabelText(/Student's branch/), { target: { value: "1" } });
    const credit = screen.getByLabelText(/Credit to/) as HTMLSelectElement;
    expect([...credit.options].map((o) => o.textContent)).toEqual(["— No one credited —", "Ravi Lead (College lead)"]);
    fireEvent.change(credit, { target: { value: "10" } });
    fireEvent.click(screen.getByRole("button", { name: "Save record" }));
    await waitFor(() => expect(calls.some((c) => c.method === "POST")).toBe(true));
    expect(calls.find((c) => c.method === "POST")!.body).toMatchObject({ college_id: "c9", course_id: 2, amount_inr: 20000, branch_id: 1, person_id: 10, stage: "confirmed" });
    await expect(done!).resolves.toMatchObject({ id: 7 });
  });
});

describe("editBranch", () => {
  it("deletes after confirmation", async () => {
    const calls = mockApi((m, url) => (m === "DELETE" && url.endsWith("/branches/5") ? json(200, { ok: true }) : undefined));
    mount();
    let done: Promise<unknown>;
    act(() => {
      done = editBranch({ id: 5, code: "CSE", name: "Computer Science", category: "it_core", is_relevant: 1 });
    });
    await screen.findByText("Edit branch — CSE");
    expect((screen.getByLabelText(/Branch code/) as HTMLInputElement).value).toBe("CSE");
    fireEvent.click(screen.getByRole("button", { name: "Delete branch" }));
    await screen.findByText(/People keep their records/);
    fireEvent.click(screen.getByRole("button", { name: "Delete" }));
    await waitFor(() => expect(calls.some((c) => c.method === "DELETE")).toBe(true));
    await expect(done!).resolves.toBeNull();
  });
});
