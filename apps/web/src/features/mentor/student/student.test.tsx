import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { mockApi, problem, renderWithProviders } from "@/features/auth/test/mock-api";
import { StudentMentoring } from "./Mentoring";
import { StudentResume } from "./Resume";

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn(), replace: vi.fn() }) }));

let restore: (() => void) | undefined;
afterEach(() => restore?.());

const page = { next_cursor: null, has_more: false, limit: 50 };
const quota = { has_package: true, mentor_sessions_remaining: 2, resume_reviews_remaining: 1 };
const future = new Date(Date.now() + 2 * 86400_000).toISOString();
const slot = { id: "s1", mentor_id: "m1", mentor_name: "Priya", organization_id: null, starts_at: future, ends_at: future, duration_minutes: 45, session_kind: "mock_interview", company_id: null, status: "open" };

describe("StudentMentoring (STU-013)", () => {
  it("shows the no-package state on 403 entitlement_required", async () => {
    const api = mockApi({
      "GET mentoring/slots": problem(403, "entitlement_required", "Access requires a plan"),
      "GET me/mentoring/bookings": { body: { data: [], page, quota: { has_package: false, mentor_sessions_remaining: 0, resume_reviews_remaining: 0 } } },
    });
    restore = api.restore;
    renderWithProviders(<StudentMentoring />);
    expect(await screen.findByText("Mock interviews come with a placement package")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "See plans" })).toHaveAttribute("href", "/app/billing");
  });

  it("books a slot with an idempotency key", async () => {
    const api = mockApi({
      "GET mentoring/slots": { body: { data: [slot], page, quota } },
      "GET me/mentoring/bookings": { body: { data: [], page, quota } },
      "POST mentoring/bookings": { status: 201, body: { id: "bk1" } },
    });
    restore = api.restore;
    renderWithProviders(<StudentMentoring />);
    fireEvent.click(await screen.findByRole("button", { name: "Book" }));
    await waitFor(() => expect(api.calls.some((c) => c.method === "POST")).toBe(true));
    const post = api.calls.find((c) => c.method === "POST")!;
    expect(post.body).toEqual({ slot_id: "s1" });
    expect(Object.keys(post.headers).map((h) => h.toLowerCase())).toContain("idempotency-key");
    expect(await screen.findByText("Session booked")).toBeInTheDocument();
  });

  it("tells the student when the quota is used up", async () => {
    const api = mockApi({
      "GET mentoring/slots": { body: { data: [slot], page, quota } },
      "GET me/mentoring/bookings": { body: { data: [], page, quota } },
      "POST mentoring/bookings": problem(403, "entitlement_required", "Access requires a plan"),
    });
    restore = api.restore;
    renderWithProviders(<StudentMentoring />);
    fireEvent.click(await screen.findByRole("button", { name: "Book" }));
    expect(await screen.findByText("No mentor sessions left")).toBeInTheDocument();
  });
});

const resume = {
  id: "r1",
  template_key: "ats_classic",
  version_no: 1,
  content: { headline: "SDE intern", summary: "", education: [], skills: ["Python"], projects: [], internships: [], achievements: [], certifications: [] },
  checklist_score: 40,
  checklist: [{ key: "skills", label: "List at least 5 skills", done: false }],
  is_current: true,
  has_pdf: false,
  pdf_uploaded_at: null,
  created_at: future,
  updated_at: future,
  reviews: [],
};

describe("StudentResume (STU-014)", () => {
  it("saves the résumé and requests a mentor review", async () => {
    const api = mockApi({
      "GET me/resumes": { body: { data: [resume], quota, suggested_certifications: [{ title: "Python Basics", issuer: "Tech Drona" }] } },
      "PUT me/resumes/r1": ({ body }) => ({ body: { ...resume, ...(body as object), checklist_score: 55 } }),
      "POST me/resumes/r1/review-requests": { status: 201, body: { id: "rv1", resume_id: "r1", status: "requested", note: null, requested_at: future, completed_at: null, comments: [], summary: null } },
    });
    restore = api.restore;
    renderWithProviders(<StudentResume />);
    expect(await screen.findByText("Checklist score 40/100")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText(/Skills/), { target: { value: "Python, SQL" } });
    fireEvent.click(screen.getByRole("button", { name: /Add my Tech Drona certificates/ }));
    fireEvent.click(screen.getByRole("button", { name: "Save résumé" }));
    await waitFor(() => expect(api.calls.some((c) => c.method === "PUT")).toBe(true));
    const put = api.calls.find((c) => c.method === "PUT")!.body as { content: { skills: string[]; certifications: { title: string }[] } };
    expect(put.content.skills).toEqual(["Python", "SQL"]);
    expect(put.content.certifications[0]!.title).toBe("Python Basics");
    expect((await screen.findAllByText("Checklist score 55/100", { exact: false })).length).toBeGreaterThan(0);

    fireEvent.click(screen.getByRole("button", { name: "Request mentor review" }));
    expect(await screen.findByText(/A review is pending/)).toBeInTheDocument();
    const post = api.calls.find((c) => c.path === "me/resumes/r1/review-requests")!;
    expect(Object.keys(post.headers).map((h) => h.toLowerCase())).toContain("idempotency-key");
  });

  it("offers to start a résumé when there is none", async () => {
    const api = mockApi({ "GET me/resumes": { body: { data: [], quota, suggested_certifications: [] } } });
    restore = api.restore;
    renderWithProviders(<StudentResume />);
    fireEvent.click(await screen.findByRole("button", { name: "Start my résumé" }));
    expect(screen.getByRole("button", { name: "Save résumé" })).toBeInTheDocument();
  });
});
