import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";
import { configurePortalApi, resetPortalApiForTests } from "../lib/api";
import { clearPortalCacheForTests } from "../lib/cache";
import { today } from "../lib/fmt";
import { addDays } from "./util";
import { PortalUiProvider } from "../ui/context";
import { OverlayHost, resetOverlaysForTests } from "../ui/Overlay";
import { addContact, editContact } from "./Contact";
import { addFollowup, markFollowupDone, openFollowupForm, rescheduleFollowup, rescheduleFollowups } from "./Followup";
import { FormsHost, resetDialogsForTests } from "./host";
import { CALL_STATUS, CONTACT_STATUS, OUTCOMES, formatPhone, isCallBack, normAnyPhone, normPhone, reasonOf } from "./labels";
import { logCall } from "./LogCall";

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
        <FormsHost />
        <OverlayHost />
      </PortalUiProvider>
    </MemoryRouter>,
  );
}

afterEach(() => {
  act(() => {
    resetDialogsForTests();
    resetOverlaysForTests();
  });
  clearPortalCacheForTests();
  resetPortalApiForTests();
});

const CONTACTS = [
  { id: 5, college_id: "c9", name: "Dr Rao", role: "principal", phone: "+919876543210", email: null, basis: "verified", status: "untested", branch_id: null },
  { id: 6, college_id: "c9", name: null, role: "office", phone: "+918632344700", email: null, basis: "pending", status: "working", branch_id: null },
];
const COLLEGE = { college: { id: "c9", name: "KL University", short_name: "KLU" }, branches: [{ id: 1, code: "CSE", name: "Computer Science", is_relevant: 1 }], people: [], contacts: CONTACTS };

describe("vocabulary (owner-reviewed wording)", () => {
  it("keeps the stored keys and the plain labels", () => {
    expect(CALL_STATUS.not_called![0]).toBe("Not called yet");
    expect(CALL_STATUS.contacted![0]).toBe("Spoke to them");
    expect(CALL_STATUS.participation_confirmed![0]).toBe("College agreed");
    expect(CONTACT_STATUS.untested![0]).toBe("Not tried yet");
    expect(CONTACT_STATUS.invalid![0]).toBe("Wrong number");
    expect(OUTCOMES.connected_callback!.label).toBe("Asked to call back");
    expect(OUTCOMES.wrong_number!.label).toBe("Wrong person");
    expect(Object.values(OUTCOMES).every((o) => !!o.hint)).toBe(true);
    expect(Object.keys(OUTCOMES)).toHaveLength(11);
  });
  it("shows call-backs as their own reason", () => {
    expect(reasonOf({ issue: "other", title: "Call back KLU" })).toEqual(["Call-back", "info"]);
    expect(isCallBack({ issue: "data", title: "Call back KLU" })).toBe(false);
    expect(reasonOf({ issue: "other", title: "Visit" })[0]).toBe("General");
    expect(reasonOf({ issue: "ambassador_gap" })[0]).toBe("No ambassador");
  });
  it("formats and normalises phone numbers like the server", () => {
    expect(formatPhone("+919876543210")).toBe("+91 98765 43210");
    expect(formatPhone("98765-43210")).toBe("+91 98765 43210");
    expect(normAnyPhone("0863 2344700")).toBe("+918632344700");
    expect(normAnyPhone("040 2345 6789")).toBe("+914023456789");
    expect(normPhone("040 2345 6789")).toBeNull();
    expect(normPhone("+1 555 123 4567")).toBeNull();
  });
});

describe("logCall", () => {
  it("needs an outcome, suggests the call-back date and posts the call", async () => {
    const calls = mockApi((m, url) => {
      if (m === "GET" && url.includes("/colleges/c9")) return json(200, COLLEGE);
      if (m === "POST" && url.endsWith("/calls")) return json(201, { call: { id: 1 }, contact: { ...CONTACTS[1], status: "working" }, followup: { id: 3, due_date: addDays(today(), 1) } });
      return undefined;
    });
    mount();
    const onSaved = vi.fn();
    let done: Promise<unknown> = Promise.resolve();
    act(() => {
      done = logCall({ college_id: "c9", onSaved });
    });
    await screen.findByRole("button", { name: "Save call" });
    const d = screen.getByRole("dialog", { name: "Log call — KLU" });
    // the working number is picked first
    expect(within(d).getByRole("radio", { name: /College office/ })).toHaveAttribute("aria-checked", "true");
    fireEvent.click(within(d).getByRole("button", { name: "Save call" }));
    expect(await within(d).findByText("Choose what happened on the call.")).toBeInTheDocument();
    // "agreed" is only possible after speaking to someone
    const agreed = within(d).getByRole("checkbox", { name: /agreed to take part/ });
    expect(agreed).toBeDisabled();
    fireEvent.click(within(d).getByRole("radio", { name: "Line busy" }));
    expect(within(d).getByLabelText("Pick a call-back date")).toHaveValue(addDays(today(), 1));
    expect(within(d).getByRole("radio", { name: "Line busy" })).toHaveAttribute("title", "Engaged tone, or the call was cut");
    fireEvent.click(within(d).getByRole("radio", { name: "Interested" }));
    expect(within(d).getByLabelText("Pick a call-back date")).toHaveValue(addDays(today(), 3)); // untouched: follows the outcome
    fireEvent.click(agreed);
    fireEvent.change(within(d).getByLabelText("Notes"), { target: { value: "Principal keen" } });
    fireEvent.click(within(d).getByRole("button", { name: "Save call" }));
    await act(async () => {
      await done;
    });
    const post = calls.find((c) => c.method === "POST")!;
    expect(post.body).toMatchObject({ college_id: "c9", contact_id: 6, outcome: "connected_interested", notes: "Principal keen", confirms_participation: true });
    expect(onSaved).toHaveBeenCalled();
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(await screen.findByText(/Call logged · number: working · call-back/)).toBeInTheDocument();
  });
});

describe("contacts", () => {
  it("needs a phone or an email, then posts the contact", async () => {
    const calls = mockApi((m, url) => {
      if (m === "GET" && url.includes("/colleges/c9")) return json(200, COLLEGE);
      if (m === "POST" && url.endsWith("/contacts")) return json(201, { id: 7 });
      return undefined;
    });
    mount();
    let done: Promise<unknown> = Promise.resolve();
    act(() => {
      done = addContact({ college_id: "c9" });
    });
    await screen.findByLabelText("Phone");
    const d = screen.getByRole("dialog", { name: "Add contact — KLU" });
    expect(within(d).queryByLabelText(/Number status/)).toBeNull();
    fireEvent.click(within(d).getByRole("button", { name: "Add contact" }));
    expect(await within(d).findByText("Add a phone number or an email.")).toBeInTheDocument();
    fireEvent.change(within(d).getByLabelText("Phone"), { target: { value: "98765 43210" } });
    fireEvent.change(within(d).getByLabelText(/Branch \(for a head of department\)/), { target: { value: "1" } });
    fireEvent.click(within(d).getByRole("button", { name: "Add contact" }));
    await act(async () => {
      await done;
    });
    expect(calls.find((c) => c.method === "POST")!.body).toEqual({
      college_id: "c9", role: "tpo", name: null, phone: "98765 43210", email: null, basis: "pending", source_url: null, notes: null, branch_id: 1,
    });
  });

  it("edits with the number status and deletes", async () => {
    const calls = mockApi((m, url) => {
      if (m === "GET" && url.includes("/colleges/c9")) return json(200, COLLEGE);
      if (m === "DELETE") return json(200, { ok: true });
      return undefined;
    });
    mount();
    act(() => {
      void editContact(CONTACTS[0] as never);
    });
    // the loading modal is replaced by the form once the college is loaded
    expect(await screen.findByLabelText(/Number status/)).toHaveValue("untested");
    const d = screen.getByRole("dialog", { name: "Edit contact — Dr Rao · Principal" });
    fireEvent.click(within(d).getByRole("button", { name: "Delete contact" }));
    fireEvent.click(await screen.findByRole("button", { name: "Delete" }));
    await waitFor(() => expect(calls.some((c) => c.method === "DELETE" && c.url.endsWith("/contacts/5"))).toBe(true));
  });
});

const PEOPLE = { items: [{ id: 11, full_name: "Anu Amb", role: "ambassador", status: "active", college_id: "c9", college_short_name: "KLU" }], total: 1 };
const COLLEGES = [{ id: "c9", name: "KL University", short_name: "KLU", targeted: 1, district_id: "guntur" }];
const ROW = { id: 40, scope_type: "college", scope_id: "c9", owner_person_id: null, owner_name: "Anu Amb", due_date: addDays(today(), -2), status: "open", issue: "other", title: "Call back KLU", notes: "n1", last_contact: null, created_at: "", created_by: "", done_at: null, _scope: { label: "KLU" } };

describe("follow-up dialogs", () => {
  it("adds a follow-up about a fixed college (locked scope)", async () => {
    const calls = mockApi((m, url) => {
      if (m === "GET" && url.includes("/colleges")) return json(200, COLLEGES);
      if (m === "GET" && url.includes("/people")) return json(200, PEOPLE);
      if (m === "GET" && url.includes("/session")) return json(200, { user: "Asha (asha@x.in)", role: "editor", sso: true });
      if (m === "POST") return json(201, { id: 41 });
      return undefined;
    });
    mount();
    let done: Promise<unknown> = Promise.resolve();
    act(() => {
      done = addFollowup({ scope_type: "college", scope_id: "c9", label: "KLU" });
    });
    const d = await screen.findByRole("dialog", { name: "New follow-up — KLU" });
    expect(within(d).queryByLabelText(/This follow-up is about/)).toBeNull();
    expect(within(d).getByLabelText("Reason")).toHaveValue("other");
    fireEvent.click(within(d).getByRole("button", { name: "Add follow-up" }));
    expect(await within(d).findByText("Describe what needs to happen.")).toBeInTheDocument();
    fireEvent.change(within(d).getByLabelText(/What needs to happen/), { target: { value: "Seminar slot" } });
    fireEvent.click(within(d).getByRole("button", { name: "Next week" }));
    fireEvent.change(within(d).getByLabelText("Assigned to"), { target: { value: "Anu Amb" } });
    fireEvent.click(within(d).getByRole("button", { name: "Add follow-up" }));
    await act(async () => {
      await done;
    });
    expect(calls.find((c) => c.method === "POST")!.body).toMatchObject({
      scope_type: "college", scope_id: "c9", issue: "other", title: "Seminar slot", owner_name: "Anu Amb", owner_person_id: 11, due_date: addDays(today(), 7), status: "open",
    });
  });

  it("switches the scope fields and maps server field errors", async () => {
    mockApi((m, url) => {
      if (m === "GET" && url.includes("/colleges/c9")) return json(200, COLLEGE);
      if (m === "GET" && url.includes("/colleges")) return json(200, COLLEGES);
      if (m === "GET" && url.includes("/people")) return json(200, PEOPLE);
      if (m === "POST") return json(400, { error: "Bad scope", fields: { scope_id: "Unknown branch" } });
      return undefined;
    });
    mount();
    act(() => {
      void openFollowupForm({});
    });
    const d = await screen.findByRole("dialog", { name: "New follow-up" });
    fireEvent.change(within(d).getByLabelText(/This follow-up is about/), { target: { value: "branch" } });
    await waitFor(() => expect(within(d).getByLabelText(/College/)).toBeInTheDocument());
    fireEvent.change(within(d).getByLabelText(/^College/), { target: { value: "c9" } });
    await waitFor(() => expect(within(d).getByRole("option", { name: "CSE — Computer Science" })).toBeInTheDocument());
    fireEvent.change(within(d).getByLabelText(/^Branch/), { target: { value: "1" } });
    fireEvent.change(within(d).getByLabelText(/What needs to happen/), { target: { value: "Check CSE" } });
    fireEvent.click(within(d).getByRole("button", { name: "Add follow-up" }));
    expect(await within(d).findByText("Unknown branch")).toBeInTheDocument();
  });

  it("marks done and schedules the next one", async () => {
    const calls = mockApi((m) => (m === "PATCH" ? json(200, {}) : m === "POST" ? json(201, { id: 42 }) : undefined));
    mount();
    let done: Promise<unknown> = Promise.resolve();
    act(() => {
      done = markFollowupDone(ROW as never);
    });
    const d = await screen.findByRole("dialog", { name: "Mark follow-up done" });
    fireEvent.change(within(d).getByLabelText("What happened?"), { target: { value: "Spoke to HOD" } });
    fireEvent.click(within(d).getByRole("button", { name: "Mark done" }));
    await act(async () => {
      await done;
    });
    expect(calls[0]).toMatchObject({ method: "PATCH", body: { status: "done", last_contact: today(), notes: `n1\n[${today()}] Spoke to HOD` } });
    expect(calls[1]).toMatchObject({ method: "POST", body: { scope_type: "college", scope_id: "c9", title: "Call back KLU", due_date: addDays(today(), 7), notes: "Previous: Spoke to HOD" } });
  });

  it("reschedules one (with a reason) and many", async () => {
    const calls = mockApi((m) => (m === "PATCH" ? json(200, {}) : undefined));
    mount();
    let done: Promise<unknown> = Promise.resolve();
    act(() => {
      done = rescheduleFollowup(ROW as never);
    });
    let d = await screen.findByRole("dialog", { name: "Reschedule follow-up" });
    fireEvent.change(within(d).getByLabelText(/New due date/), { target: { value: addDays(today(), -1) } });
    fireEvent.click(within(d).getByRole("button", { name: "Reschedule" }));
    expect(await within(d).findByText("Pick today or a later date.")).toBeInTheDocument();
    fireEvent.change(within(d).getByLabelText(/New due date/), { target: { value: addDays(today(), 3) } });
    fireEvent.change(within(d).getByLabelText("Why?"), { target: { value: "Exams" } });
    fireEvent.click(within(d).getByRole("button", { name: "Reschedule" }));
    await act(async () => {
      await done;
    });
    expect(calls[0]!.body).toEqual({ due_date: addDays(today(), 3), notes: `n1\n[${today()}] Moved to ${addDays(today(), 3)}: Exams` });
    act(() => {
      done = rescheduleFollowups([1, 2]);
    });
    d = await screen.findByRole("dialog", { name: "Reschedule 2 follow-ups" });
    expect(within(d).queryByLabelText("Why?")).toBeNull();
    fireEvent.click(within(d).getByRole("button", { name: "Reschedule" }));
    await act(async () => {
      await done;
    });
    expect(calls.slice(1).map((c) => c.url.replace(/.*\/api\//, ""))).toEqual(["followups/1", "followups/2"]);
  });
});
