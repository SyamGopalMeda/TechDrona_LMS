import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { mockApi, problem, renderWithProviders } from "@/features/auth/test/mock-api";
import { FeedbackForm, MeetingLink, MentorSessionDetail, MentorSessions, MentorStudent, MentorStudents } from "./Mentor";
import { SlotForm } from "./Slots";

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn(), replace: vi.fn() }) }));

let restore: (() => void) | undefined;
afterEach(() => restore?.());

const page = { next_cursor: null, has_more: false, limit: 50 };

describe("MeetingLink", () => {
  it("renders only http(s) links, in a new tab without opener", () => {
    render(<MeetingLink url="https://meet.google.com/abc-defg-hij" />);
    const a = screen.getByRole("link", { name: /Join meeting \(meet.google.com\)/ });
    expect(a).toHaveAttribute("target", "_blank");
    expect(a).toHaveAttribute("rel", "noopener noreferrer");
  });
  it("refuses other schemes", () => {
    render(<MeetingLink url="javascript:alert(1)" />);
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
    expect(screen.getByText("No meeting link yet")).toBeInTheDocument();
  });
});

const future = new Date(Date.now() + 2 * 86400_000).toISOString();
const past = new Date(Date.now() - 3600_000).toISOString();
const session = {
  id: "bk1",
  slot_id: "s1",
  status: "booked",
  starts_at: future,
  ends_at: future,
  duration_minutes: 60,
  session_kind: "mock_interview",
  company_id: null,
  mentor_id: "m1",
  mentor_name: "Mentor",
  meeting_url: null,
  quota_consumed: true,
  credit_restored: false,
  cancelled_at: null,
  created_at: past,
  free_change_until: future,
  feedback: null,
  student_id: "u1",
  student_name: "Ananya Reddy",
  feedback_due_at: future,
  feedback_overdue: false,
};

describe("MentorSessions (MEN-001)", () => {
  it("shows counts and upcoming sessions", async () => {
    const api = mockApi({
      "GET mentor/sessions": { body: { data: [session], page, counts: { upcoming: 1, pending_feedback: 2 } } },
      "GET mentor/resume-reviews": { body: { data: [] } },
    });
    restore = api.restore;
    renderWithProviders(<MentorSessions />);
    expect(await screen.findByRole("link", { name: "Ananya Reddy" })).toHaveAttribute("href", "/mentor/sessions/bk1");
    expect(await screen.findByText("2")).toBeInTheDocument();
  });
});

describe("MentorSessionDetail (MEN-003)", () => {
  it("shows the feedback form once the session started and private notes", async () => {
    const api = mockApi({
      "GET mentor/sessions/bk1": { body: { ...session, starts_at: past, notes: [{ id: "n1", student_id: "u1", author_id: "m1", author_name: "Mentor", booking_id: null, body: "Needs DP practice", created_at: past }], weak_topics: ["DP"] } },
    });
    restore = api.restore;
    renderWithProviders(<MentorSessionDetail bookingId="bk1" />);
    expect(await screen.findByText("Needs DP practice")).toBeInTheDocument();
    expect(screen.getByText("Private — never shown to the student.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Submit feedback" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "I missed this session" })).toBeInTheDocument();
    // Phase 2: the session is named in the h1 with breadcrumbs back to Sessions.
    expect(screen.getByRole("heading", { level: 1, name: /with Ananya Reddy$/ })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Sessions" })).toHaveAttribute("href", "/mentor");
  });
});

describe("FeedbackForm", () => {
  it("requires all five scores before sending", async () => {
    const api = mockApi({});
    restore = api.restore;
    renderWithProviders(<FeedbackForm bookingId="bk1" onDone={vi.fn()} />);
    fireEvent.change(screen.getByLabelText(/Communication/), { target: { value: "4" } });
    fireEvent.click(screen.getByRole("button", { name: "Submit feedback" }));
    expect(await screen.findByText(/Score overall from 1 to 5/)).toBeInTheDocument();
    expect(api.calls).toHaveLength(0);
  });

  it("posts the rubric with an idempotency key", async () => {
    const onDone = vi.fn();
    const api = mockApi({ "POST mentor/bookings/bk1/feedback": { status: 201, body: { id: "f1" } } });
    restore = api.restore;
    renderWithProviders(<FeedbackForm bookingId="bk1" onDone={onDone} />);
    for (const label of [/Communication/, /Problem solving/, /Technical depth/, /Confidence/, /Overall/]) fireEvent.change(screen.getByLabelText(label), { target: { value: "3" } });
    fireEvent.click(screen.getByRole("button", { name: "Submit feedback" }));
    await waitFor(() => expect(onDone).toHaveBeenCalled());
    const call = api.calls[0]!;
    expect(call.body).toEqual({ scores: { communication: 3, problem_solving: 3, technical_depth: 3, confidence: 3, overall: 3 } });
    expect(Object.keys(call.headers).map((h) => h.toLowerCase())).toContain("idempotency-key");
  });
});

describe("SlotForm (MEN-002)", () => {
  it("shows the overlap conflict from 409 slot_overlap", async () => {
    const api = mockApi({ "POST mentor/slots": problem(409, "slot_overlap", "Overlaps another slot", { conflicts: [{ starts_at: future, ends_at: future }] }) });
    restore = api.restore;
    renderWithProviders(<SlotForm onCreated={vi.fn()} />);
    const local = new Date(Date.now() + 86400_000);
    const v = `${local.getFullYear()}-${String(local.getMonth() + 1).padStart(2, "0")}-${String(local.getDate()).padStart(2, "0")}T10:00`;
    fireEvent.change(screen.getByLabelText(/Starts at/), { target: { value: v } });
    fireEvent.click(screen.getByRole("button", { name: "Publish slot" }));
    expect(await screen.findByText("This overlaps another of your slots")).toBeInTheDocument();
    expect(screen.getByText(/^Overlaps /)).toBeInTheDocument();
    expect((api.calls[0]!.body as { slots: { duration_minutes: number }[] }).slots[0]!.duration_minutes).toBe(60);
  });

  it("rejects a past start time without calling the api", async () => {
    const api = mockApi({});
    restore = api.restore;
    renderWithProviders(<SlotForm onCreated={vi.fn()} />);
    fireEvent.change(screen.getByLabelText(/Starts at/), { target: { value: "2020-01-01T10:00" } });
    fireEvent.click(screen.getByRole("button", { name: "Publish slot" }));
    expect(await screen.findByText("Choose a time in the future")).toBeInTheDocument();
    expect(api.calls).toHaveLength(0);
  });
});

const student = {
  user_id: "u1",
  full_name: "Ananya Reddy",
  batch_id: "b1",
  batch_name: "CSE-A",
  batches: [{ batch_id: "b1", name: "CSE-A" }],
  target_companies: [],
  next_session_at: null,
};

describe("MentorStudents", () => {
  it("lists assigned students with their batches", async () => {
    const api = mockApi({ "GET mentor/students": { body: { data: [student], page: { next_cursor: null, has_more: false, limit: 100 } } } });
    restore = api.restore;
    renderWithProviders(<MentorStudents />);
    expect(await screen.findByRole("link", { name: "Ananya Reddy" })).toHaveAttribute("href", "/mentor/students/u1");
    expect(screen.getByText("CSE-A")).toBeInTheDocument();
  });
});

describe("MentorStudent (MEN-004)", () => {
  it("shows weak topics, feedback history and adds a private note", async () => {
    const api = mockApi({
      "GET mentor/students/u1": {
        body: {
          ...student,
          readiness: [],
          topics: [{ topic_id: "t1", name: "Dynamic programming", mastery: 0.2, band: "weak", attempts: 12 }],
          weak_topics: ["Dynamic programming"],
          feedback: [{ id: "f1", booking_id: "bk1", mentor_id: "m1", scores: { communication: 4, problem_solving: 3, technical_depth: 2, confidence: 5, overall: 3 }, comments: "Good energy", released_at: past, created_at: past, starts_at: past, session_kind: "mock_interview" }],
          notes: [],
        },
      },
      "POST mentor/students/u1/notes": { status: 201, body: { id: "n2", student_id: "u1", author_id: "m1", author_name: "Me", booking_id: null, body: "Follow up on DP", created_at: past } },
    });
    restore = api.restore;
    renderWithProviders(<MentorStudent userId="u1" />);
    expect(await screen.findByText("Weakest topics: Dynamic programming")).toBeInTheDocument();
    expect(screen.getByText("12")).toBeInTheDocument();
    expect(screen.getByText("Good energy")).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 1, name: "Ananya Reddy" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Students" })).toHaveAttribute("href", "/mentor/students");
    fireEvent.change(screen.getByLabelText("Add a note"), { target: { value: "Follow up on DP" } });
    fireEvent.click(screen.getByRole("button", { name: "Save note" }));
    expect(await screen.findByText("Follow up on DP", { selector: "p" })).toBeInTheDocument();
  });
});
