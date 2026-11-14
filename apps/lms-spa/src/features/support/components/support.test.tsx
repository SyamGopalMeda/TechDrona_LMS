import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { mockApi, problem, renderWithProviders } from "@/features/auth/test/mock-api";
import { MyTicket, MyTickets, NewTicketForm } from "./StudentSupport";
import { SupportUnblockTriage, TicketDetail, TicketQueue, UserLookup, resolveTicketId } from "./SupportDesk";

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn(), replace: vi.fn() }) }));

const cleanups: (() => void)[] = [];
afterEach(() => {
  while (cleanups.length) cleanups.pop()!();
});

const page = { next_cursor: null, has_more: false, limit: 1 };
const devices = {
  data: [{ user_device_id: "d1", label: "Chrome on Windows", user_label: null, trust_status: "trusted", last_used_at: null }],
  limits: { max_trusted: 2, support_resets_used_30d: 0 },
  page,
};
const sessions = {
  data: [{ session_id: "s1", status: "active", device_label: "Chrome on Windows", approx_region: "KA", ip: "49.36.112.x", last_active_at: null }],
  page,
};

describe("Support user lookup (SUP-003/004)", () => {
  it("needs a ticket, sends reason_code=ticket, shows masked data only and grants a device reset", async () => {
    const api = mockApi({
      "GET users/u1/devices": { body: devices },
      "GET users/u1/sessions": { body: sessions },
      "POST users/u1/devices/d1/reset": { body: { removed: true, support_resets_used_30d: 1, support_resets_max_30d: 1 } },
    });
    cleanups.push(api.restore);
    renderWithProviders(<UserLookup userId="u1" />);
    expect(api.calls).toHaveLength(0);
    await userEvent.type(screen.getByLabelText(/Ticket number/), "T-481");
    await userEvent.click(screen.getByRole("button", { name: "Open" }));
    expect(await screen.findByText("Support resets left (last 30 days): 1")).toBeInTheDocument();
    expect(api.calls.every((c) => c.url.includes("reason_code=ticket"))).toBe(true);
    expect(screen.getByText("49.36.112.x")).toBeInTheDocument();
    expect(screen.queryByText(/Reveal full IP/)).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Reset Chrome on Windows" }));
    const dialog = await screen.findByRole("dialog");
    await userEvent.type(within(dialog).getByLabelText(/Reason/), "Laptop replaced");
    await userEvent.click(within(dialog).getByRole("button", { name: "Reset device" }));
    await waitFor(() => expect(api.calls.some((c) => c.method === "POST")).toBe(true));
    // ticket_id is a UUID field on DeviceResetIn; a free-text ticket goes into the reason.
    expect(api.calls.find((c) => c.method === "POST")!.body).toMatchObject({ reason_code: "ticket", reason: "Ticket T-481: Laptop replaced", ticket_id: null });
  });

  it("explains a quota-exhausted reset", async () => {
    const api = mockApi({
      "GET users/u1/devices": { body: devices },
      "GET users/u1/sessions": { body: sessions },
      "POST users/u1/devices/d1/reset": problem(409, "device_replacement_quota_exhausted", "Reset limit reached", { detail: "A security reviewer must approve another reset." }),
    });
    cleanups.push(api.restore);
    renderWithProviders(<UserLookup userId="u1" ticketId="T-1" />);
    await userEvent.click(await screen.findByRole("button", { name: "Reset Chrome on Windows" }));
    const dialog = await screen.findByRole("dialog");
    await userEvent.type(within(dialog).getByLabelText(/Reason/), "Second laptop");
    await userEvent.click(within(dialog).getByRole("button", { name: "Reset device" }));
    expect(await within(dialog).findByText("A security reviewer must approve another reset.")).toBeInTheDocument();
  });
});

const ticket = {
  ticket_id: "t1",
  ticket_number: "TD-T-2026-000001",
  requester_id: "u1",
  category: "account_access",
  subject: "Cannot sign in",
  body: "My login fails every time since yesterday.",
  status: "open",
  priority: "high",
  assigned_to: null,
  is_grievance: false,
  escalated_to: null,
  merged_into_id: null,
  related_order_id: null,
  related_case_id: null,
  related_unblock_request_id: null,
  first_response_due_at: new Date(Date.now() - 3_600_000).toISOString(),
  resolution_due_at: new Date(Date.now() + 86_400_000).toISOString(),
  first_responded_at: null,
  resolved_at: null,
  closed_at: null,
  created_at: "2026-11-03T10:00:00.000Z",
  updated_at: "2026-11-03T10:00:00.000Z",
  sla: { first_response_breached: true, resolution_breached: false },
  csat_score: null,
  message_count: 1,
  requester: { user_id: "u1", display_name: "Asha", email_masked: "a***@example.com" },
};

describe("Support ticket queue (SUP-001)", () => {
  it("lists tickets with SLA state and counts, and filters by status", async () => {
    const api = mockApi({ "GET support/queue": { body: { data: [ticket], page, counts: { open: 1, pending_user: 0, pending_internal: 0, breached: 1, unassigned: 1 } } } });
    cleanups.push(api.restore);
    renderWithProviders(<TicketQueue />);
    expect(await screen.findByText("TD-T-2026-000001")).toBeInTheDocument();
    expect(screen.getByText(/Breached/)).toBeInTheDocument();
    expect(screen.getByText("SLA breached")).toBeInTheDocument();
    await userEvent.selectOptions(screen.getByLabelText("Status"), "pending_user");
    await waitFor(() => expect(api.calls.some((c) => c.url.includes("status=pending_user"))).toBe(true));
  });
});

describe("Support ticket detail (SUP-002)", () => {
  it("shows internal notes, posts an internal note and assigns to me", async () => {
    const thread = {
      ...ticket,
      viewer: "agent",
      messages: [{ message_id: "m1", author_kind: "agent", author_id: "a1", visibility: "internal", body: "Checked devices", created_at: "2026-11-03T11:00:00.000Z" }],
    };
    const api = mockApi({
      "GET support/tickets/t1": { body: thread },
      "GET support/macros": { body: { data: [{ macro_id: "mac1", title: "Device reset done", body: "We reset your device.", category: "device_reset" }] } },
      "POST support/tickets/t1/messages": { status: 201, body: { message_id: "m2", author_kind: "agent", author_id: "a1", visibility: "internal", body: "x", created_at: "2026-11-03T12:00:00.000Z" } },
      "PATCH support/tickets/t1": { body: ticket },
    });
    cleanups.push(api.restore);
    renderWithProviders(<TicketDetail ticketId="t1" />);
    expect(await screen.findByText("Checked devices")).toBeInTheDocument();
    expect(screen.getByText("Internal note")).toBeInTheDocument();
    await userEvent.selectOptions(await screen.findByLabelText("Insert macro"), "mac1");
    await userEvent.click(screen.getByRole("checkbox", { name: /Internal note/ }));
    await userEvent.click(screen.getByRole("button", { name: "Add note" }));
    await waitFor(() => expect(api.calls.some((c) => c.method === "POST")).toBe(true));
    expect(api.calls.find((c) => c.method === "POST")!.body).toEqual({ body: "We reset your device.", visibility: "internal" });
    await userEvent.click(screen.getByRole("button", { name: "Assign to me" }));
    await waitFor(() => expect(api.calls.find((c) => c.method === "PATCH")?.body).toEqual({ assign_to_me: true }));
  });

  it("confirms before closing a ticket and opens each dialog with fresh fields (audit 0.5/0.7)", async () => {
    const api = mockApi({
      "GET support/tickets/t1": { body: { ...ticket, viewer: "agent", messages: [] } },
      "GET support/macros": { body: { data: [] } },
      "PATCH support/tickets/t1": { body: ticket },
    });
    cleanups.push(api.restore);
    renderWithProviders(<TicketDetail ticketId="t1" />);
    await userEvent.selectOptions(await screen.findByLabelText("Status"), "closed");
    let dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText("Close this ticket?")).toBeInTheDocument();
    expect(api.calls.some((c) => c.method === "PATCH")).toBe(false);
    await userEvent.click(within(dialog).getByRole("button", { name: "Close ticket" }));
    await waitFor(() => expect(api.calls.find((c) => c.method === "PATCH")?.body).toEqual({ status: "closed" }));

    // A note typed for one escalation never carries into the next dialog.
    await userEvent.click(screen.getByRole("button", { name: "Escalate" }));
    dialog = await screen.findByRole("dialog");
    await userEvent.type(within(dialog).getByLabelText(/^Note/), "secret context for security");
    await userEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));
    await userEvent.click(screen.getByRole("button", { name: "Escalate" }));
    dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByLabelText(/^Note/)).toHaveValue("");
  });
});

describe("Support user summary (SUP-11..14)", () => {
  it("shows masked account data and sends a password-reset email", async () => {
    const summary = {
      user_id: "u1",
      display_name: "Asha",
      email_masked: "a***@example.com",
      phone_masked: "+91******10",
      status: "active",
      privacy_tier: "adult",
      is_minor: false,
      email_verified: true,
      phone_verified: false,
      created_at: "2026-01-01T00:00:00.000Z",
      last_login_at: null,
      mfa_enrolled: false,
      restriction: null,
      devices: { trusted_count: 1, total: 2 },
      active_sessions: [],
      entitlements: [],
      recent_orders: [{ order_number: "TD-O-1", status: "paid", total_paise: 99900, created_at: "2026-10-01T00:00:00.000Z" }],
      notes: [],
      tickets: [],
    };
    const api = mockApi({
      "GET support/users/u1": { body: summary },
      "GET users/u1/devices": { body: devices },
      "GET users/u1/sessions": { body: sessions },
      "POST support/users/u1/password-reset-email": { status: 202, body: { status: "sent", sent_to: "a***@example.com" } },
    });
    cleanups.push(api.restore);
    renderWithProviders(<UserLookup userId="u1" ticketId="T-9" />);
    expect(await screen.findByText(/a\*\*\*@example.com · verified/)).toBeInTheDocument();
    expect(screen.getByText(/TD-O-1/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Send password-reset email" }));
    const dialog = await screen.findByRole("dialog");
    await userEvent.click(within(dialog).getByRole("button", { name: "Send" }));
    await waitFor(() => expect(api.calls.some((c) => c.method === "POST" && c.path === "support/users/u1/password-reset-email")).toBe(true));
    expect(api.calls.find((c) => c.method === "POST")!.body).toEqual({ reason_code: "ticket", ticket_id: null });
  });
});

describe("Student support (STU-025)", () => {
  it("creates a ticket with disclosed context", async () => {
    const api = mockApi({ "POST support/tickets": { status: 201, body: ticket } });
    cleanups.push(api.restore);
    renderWithProviders(<NewTicketForm from="/app/courses" />);
    await userEvent.click(screen.getByRole("button", { name: "Send" }));
    expect(await screen.findByText("Choose a topic.")).toBeInTheDocument();
    expect(api.calls).toHaveLength(0);
    await userEvent.selectOptions(screen.getByLabelText(/Topic/), "technical");
    await userEvent.type(screen.getByLabelText(/Subject/), "Video stalls");
    await userEvent.type(screen.getByLabelText(/What happened/), "The lesson video stops after a minute.");
    expect(screen.getByText(/Page: \/app\/courses/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Send" }));
    await waitFor(() => expect(api.calls).toHaveLength(1));
    expect(api.calls[0]!.body).toMatchObject({ category: "technical", subject: "Video stalls", context: { route: "/app/courses" } });
    expect(api.calls[0]!.headers["idempotency-key"]).toBeTruthy();
  });

  it("hides internal notes, reopens a resolved ticket and offers CSAT", async () => {
    const thread = {
      ...ticket,
      status: "resolved",
      viewer: "requester",
      messages: [
        { message_id: "m1", author_kind: "agent", author_id: "a1", visibility: "public", body: "Fixed now", created_at: "2026-11-03T11:00:00.000Z" },
        { message_id: "m2", author_kind: "agent", author_id: "a1", visibility: "internal", body: "Secret note", created_at: "2026-11-03T11:00:00.000Z" },
      ],
    };
    const api = mockApi({ "GET support/tickets/t1": { body: thread }, "POST support/tickets/t1/reopen": { body: { ...ticket, status: "open" } } });
    cleanups.push(api.restore);
    renderWithProviders(<MyTicket ticketId="t1" />);
    expect(await screen.findByText("Fixed now")).toBeInTheDocument();
    expect(screen.queryByText("Secret note")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Send rating" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Reopen ticket" }));
    await waitFor(() => expect(api.calls.some((c) => c.method === "POST" && c.path === "support/tickets/t1/reopen")).toBe(true));
  });

  it("URL-encodes the ticket id taken from the route (FE-30)", async () => {
    const api = mockApi({});
    cleanups.push(api.restore);
    renderWithProviders(<MyTicket ticketId="../me/devices" />);
    await waitFor(() => expect(api.calls.length).toBeGreaterThan(0));
    expect(api.calls[0]!.url).toContain("support/tickets/..%2Fme%2Fdevices");
    expect(api.calls.every((c) => !c.path.startsWith("me/"))).toBe(true);
  });

  it("maps ?topic= to category, links the appeal attempt and uploads attachments (w2b R4, BE-17)", async () => {
    const attempt = "0192f3a4-1111-7aaa-8bbb-123456789abc";
    const api = mockApi({
      "POST media/uploads/file": { status: 201, body: { purpose: "support_attachment", s3_key: "uploads/support_attachment/u1/x/shot.png", upload: { url: "https://uploads.example.com/", fields: { key: "k" } }, expires_at: "2026-11-03T12:00:00Z", max_bytes: 4 } },
      "POST support/tickets": { status: 201, body: ticket },
    });
    cleanups.push(api.restore);
    const provider = vi.fn(async () => new Response(null, { status: 204 }));
    vi.stubGlobal("fetch", provider);
    cleanups.push(() => vi.unstubAllGlobals());
    renderWithProviders(<NewTicketForm from="/app/attempts/x/appeal" topic="assessment" attemptId={attempt} />);
    expect((screen.getByLabelText(/Topic/) as HTMLSelectElement).value).toBe("assessment");
    await userEvent.type(screen.getByLabelText(/Subject/), "Appeal my attempt");
    await userEvent.type(screen.getByLabelText(/What happened/), "My attempt was invalidated by mistake.");
    await userEvent.upload(screen.getByLabelText(/Attachments/), new File(["abcd"], "shot.png", { type: "image/png" }));
    await userEvent.click(screen.getByRole("button", { name: "Send" }));
    await waitFor(() => expect(api.calls.some((c) => c.path === "support/tickets")).toBe(true));
    expect(api.calls[0]!.body).toMatchObject({ purpose: "support_attachment", filename: "shot.png", content_type: "image/png", size_bytes: 4 });
    expect(provider).toHaveBeenCalledTimes(1);
    expect(api.calls.find((c) => c.path === "support/tickets")!.body).toMatchObject({
      category: "assessment",
      related_attempt_id: attempt,
      attachments: [{ s3_key: "uploads/support_attachment/u1/x/shot.png", filename: "shot.png", content_type: "image/png", size_bytes: 4 }],
    });
  });

  it("ignores an unknown topic and a malformed attempt id", async () => {
    const api = mockApi({ "POST support/tickets": { status: 201, body: ticket } });
    cleanups.push(api.restore);
    renderWithProviders(<NewTicketForm topic="nope" attemptId="../x" />);
    expect((screen.getByLabelText(/Topic/) as HTMLSelectElement).value).toBe("");
    await userEvent.selectOptions(screen.getByLabelText(/Topic/), "account_access");
    await userEvent.type(screen.getByLabelText(/Subject/), "Cannot join");
    await userEvent.type(screen.getByLabelText(/What happened/), "My sign-in link fails every time.");
    await userEvent.click(screen.getByRole("button", { name: "Send" }));
    await waitFor(() => expect(api.calls).toHaveLength(1));
    expect(api.calls[0]!.body).not.toHaveProperty("related_attempt_id");
  });

  it("opens a ticket attachment through the short-lived download route", async () => {
    const thread = { ...ticket, viewer: "requester", attachments: [{ filename: "shot.png", content_type: "image/png", size_bytes: 2048 }], messages: [] };
    const api = mockApi({
      "GET support/tickets/t1": { body: thread },
      "GET support/tickets/t1/attachments/ticket/0": { body: { url: "https://uploads.example.com/signed", expires_at: "x", filename: "shot.png" } },
    });
    cleanups.push(api.restore);
    const open = vi.spyOn(window, "open").mockReturnValue(null);
    cleanups.push(() => open.mockRestore());
    renderWithProviders(<MyTicket ticketId="t1" />);
    await userEvent.click(await screen.findByRole("button", { name: /shot\.png/ }));
    await waitFor(() => expect(open).toHaveBeenCalledWith("https://uploads.example.com/signed", "_blank", "noopener,noreferrer"));
  });

  it("lists own tickets", async () => {
    const api = mockApi({ "GET me/support/tickets": { body: { data: [ticket], page } } });
    cleanups.push(api.restore);
    renderWithProviders(<MyTickets />);
    expect(await screen.findByText("Cannot sign in")).toBeInTheDocument();
    // The page's one main action is a primary button (not an outline link).
    const create = screen.getByRole("link", { name: "New ticket" });
    expect(create).toHaveAttribute("href", "/app/support/new");
    expect(create.className).toContain("bg-brand");
  });

  it("gives the new-ticket form breadcrumbs and a styled file picker", () => {
    renderWithProviders(<NewTicketForm />);
    const crumbs = screen.getByRole("navigation", { name: /breadcrumb/i });
    expect(within(crumbs).getByRole("link", { name: "Support" })).toHaveAttribute("href", "/app/support");
    expect(screen.getByLabelText(/Attachments/).className).toContain("file:");
    expect(screen.getByRole("link", { name: "Cancel" })).toHaveAttribute("href", "/app/support");
  });
});

describe("Support unblock triage (SUP-005)", () => {
  it("lists open requests with their route", async () => {
    const api = mockApi({
      "GET support/unblock-requests": {
        body: {
          data: [
            { reference: "APL-1", state: "submitted", level: 2, route: "support" },
            { reference: "APL-2", state: "submitted", level: 3, route: "security" },
          ],
        },
      },
    });
    cleanups.push(api.restore);
    renderWithProviders(<SupportUnblockTriage />);
    expect(await screen.findByText("APL-1")).toBeInTheDocument();
    expect(screen.getByText("APL-2")).toBeInTheDocument();
    expect(screen.getByText("Security")).toBeInTheDocument();
    // Old-shape rows (no ids) get no actions and an honest notice.
    expect(screen.queryByRole("button", { name: /Forward/ })).not.toBeInTheDocument();
    expect(screen.getByText(/older requests cannot be lifted or forwarded/)).toBeInTheDocument();
  });

  it("lifts an L1/L2 restriction and forwards an L3 request (ADM-27/INV-06)", async () => {
    const api = mockApi({
      "GET support/unblock-requests": {
        body: {
          data: [
            { request_id: "r1", reference: "APL-1", case_ref: "CASE-1", state: "submitted", level: 2, route: "support", submitted_at: null, restrictions: [{ restriction_id: "x1", level: 2, family: "sharing", liftable_by_support: true }] },
            { request_id: "r2", reference: "APL-2", case_ref: "CASE-2", state: "submitted", level: 3, route: "security", submitted_at: null, restrictions: [{ restriction_id: "x2", level: 3, family: "sharing", liftable_by_support: false }] },
          ],
          page: { next_cursor: null, has_more: false, limit: 25 },
        },
      },
      "POST security/restrictions/x1/lift": { body: { restriction_id: "x1", ended_at: "2026-11-03T00:00:00Z" } },
      "POST support/unblock-requests/r2/forward": { body: { reference: "APL-2", forwarded: true, priority: "high" } },
    });
    cleanups.push(api.restore);
    renderWithProviders(<SupportUnblockTriage />);
    expect(await screen.findByText("APL-1")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Lift sharing temporary restriction for APL-2" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Forward APL-1 to security" })).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Lift sharing verification check for APL-1" }));
    let dialog = await screen.findByRole("dialog");
    await userEvent.click(within(dialog).getByLabelText(/Reason/));
    await userEvent.paste("Student verified on a call");
    await userEvent.click(within(dialog).getByRole("button", { name: "Lift restriction" }));
    await waitFor(() => expect(api.calls.find((c) => c.path === "security/restrictions/x1/lift")?.body).toEqual({ reason: "Student verified on a call" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());

    await userEvent.click(screen.getByRole("button", { name: "Forward APL-2 to security" }));
    dialog = await screen.findByRole("dialog");
    await userEvent.click(within(dialog).getByLabelText(/Reason/));
    await userEvent.paste("Needs L3 review");
    await userEvent.click(within(dialog).getByRole("button", { name: "Forward" }));
    await waitFor(() => expect(api.calls.find((c) => c.path === "support/unblock-requests/r2/forward")?.body).toEqual({ reason: "Needs L3 review" }));
  });
});

describe("Desk Phase 2 presentation (audit 1.7/1.11)", () => {
  const agent = "0b1c2d3e-4f50-6172-8394-a5b6c7d8e9f0";

  it("ticket detail: breadcrumbs back to the queue, the subject as h1, status in the header and readable references", async () => {
    const api = mockApi({
      "GET support/tickets/t1": { body: { ...ticket, assigned_to: agent, related_case_id: agent, viewer: "agent", messages: [] } },
      "GET support/macros": { body: { data: [] } },
    });
    cleanups.push(api.restore);
    renderWithProviders(<TicketDetail ticketId="t1" />);
    expect(await screen.findByRole("heading", { level: 1, name: "Cannot sign in" })).toBeInTheDocument();
    const crumbs = screen.getByRole("navigation", { name: "Breadcrumb" });
    expect(within(crumbs).getByRole("link", { name: "Ticket queue" })).toHaveAttribute("href", "/desk");
    expect(screen.getByText("Agent #C7D8E9F0")).toBeInTheDocument();
    expect(screen.getByText("Case #C7D8E9F0")).toBeInTheDocument();
    expect(screen.queryByText(agent)).not.toBeInTheDocument();
  });

  it("merge: a ticket number is resolved to its id; an unknown number says so", async () => {
    const api = mockApi({ "GET support/queue": { body: { data: [{ ...ticket, ticket_id: "t9", ticket_number: "TD-T-2026-000009" }], page } } });
    cleanups.push(api.restore);
    await expect(resolveTicketId(" td-t-2026-000009 ")).resolves.toBe("t9");
    await expect(resolveTicketId("TD-T-2026-000777")).rejects.toMatchObject({ detail: expect.stringContaining("No open ticket is numbered TD-T-2026-000777") });
    await expect(resolveTicketId(agent)).resolves.toBe(agent);
  });

  it("user lookup: the person's name is the title (not the id) and resets are disabled when none are left", async () => {
    const api = mockApi({
      "GET support/users/u1": { body: { user_id: "u1", display_name: "Asha", email_masked: "a***@example.com", status: "active", devices: { trusted_count: 1, total: 1 }, entitlements: [], recent_orders: [], notes: [], tickets: [] } },
      "GET users/u1/devices": { body: { ...devices, limits: { support_resets_used_30d: 1 } } },
      "GET users/u1/sessions": { body: { data: [], page } },
    });
    cleanups.push(api.restore);
    renderWithProviders(<UserLookup userId="u1" ticketId="TD-T-1" />);
    expect(await screen.findByRole("heading", { level: 1, name: "Asha" })).toBeInTheDocument();
    expect(await screen.findByText(/No support resets are left/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Reset Chrome on Windows" })).toBeDisabled();
    expect(screen.getByText("Not signed in anywhere")).toBeInTheDocument();
  });

  it("queue: search waits for typing to pause, and the empty status option says what it shows", async () => {
    const api = mockApi({ "GET support/queue": { body: { data: [ticket], page, counts: { open: 1, breached: 0, unassigned: 0 } } } });
    cleanups.push(api.restore);
    renderWithProviders(<TicketQueue />);
    expect(await screen.findByText("TD-T-2026-000001")).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "All open tickets" })).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText(/^Search/), "sign");
    await waitFor(() => expect(api.calls.some((c) => c.url.includes("q=sign"))).toBe(true));
    expect(api.calls.some((c) => c.url.includes("q=s&") || c.url.endsWith("q=s"))).toBe(false);
  });
});
