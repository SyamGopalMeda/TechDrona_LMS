import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { mockApi, renderWithProviders } from "@/features/auth/test/mock-api";
import { PORTALS } from "@/lib/nav/portals";
import { BatchPlan } from "./components/BatchPlan";
import { ClassesAttendance } from "./components/ClassesAttendance";
import { MyClasses } from "./components/MyClasses";
import type { BatchPlanResponse, Schedule } from "./lib/delivery";

vi.setConfig({ testTimeout: 20000 });

const cleanups: (() => void)[] = [];
afterEach(() => {
  while (cleanups.length) cleanups.pop()!();
});

const schedule: Schedule = {
  sessions: 10,
  weeks_count: 2,
  hours_planned: 20,
  days_per_week: 5,
  start_date: "2026-11-02",
  end_date: "2026-11-13",
  current_week: 2,
  today: "2026-11-10",
  required_activities: 1,
  weeks: [
    { n: 1, from: "2026-11-02", to: "2026-11-08", days: ["2026-11-02", "2026-11-03", "2026-11-04", "2026-11-05", "2026-11-06"], title: "Basics", topics: ["HTML"], activities: [], beyond_schedule: false },
    {
      n: 2,
      from: "2026-11-09",
      to: "2026-11-15",
      days: ["2026-11-09", "2026-11-10", "2026-11-11", "2026-11-12", "2026-11-13"],
      title: "Project",
      topics: [],
      activities: [{ id: "p1-submit", kind: "project", title: "Submit project", due: null, required: true, week: 2, week_title: "Project", due_effective: "2026-11-13" }],
      beyond_schedule: false,
    },
  ],
};

const planRes: BatchPlanResponse = {
  batch: { id: "b1", name: "MERN Jan", code: "web-mern", status: "active", starts_on: "2026-11-02", ends_on: "2026-11-13", course_id: null, website_course_slug: "mern-stack-development" },
  has_plan: true,
  plan: {
    total_hours: 20,
    daily_hours: 2,
    working_days: [1, 2, 3, 4, 5],
    holidays: [],
    class_time: "18:30",
    meet_url: "https://meet.example.com/abc",
    registrations_open: false,
    weeks: [
      { title: "Basics", topics: ["HTML"], activities: [] },
      { title: "Project", topics: [], activities: [{ id: "p1-submit", kind: "project", title: "Submit project", due: null, required: true }] },
    ],
  },
  min_attendance_percent: 75,
  source_ref: "web_courses/abc",
  updated_at: null,
  schedule,
};

describe("Batch plan tab", () => {
  it("shows the computed weeks read-only for trainers", async () => {
    const api = mockApi({ "GET batches/b1/plan": { body: planRes } });
    cleanups.push(api.restore);
    renderWithProviders(<BatchPlan batchId="b1" />);
    const weeks = await screen.findByRole("list", { name: "Weeks" });
    expect(within(weeks).getByText("Basics")).toBeInTheDocument();
    expect(within(weeks).getByText("This week")).toBeInTheDocument();
    expect(screen.getByText(/Submit project · due/)).toBeInTheDocument();
    expect(screen.getByText("75% for the certificate")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Save plan" })).not.toBeInTheDocument();
  });

  it("lets an Admin edit a week and saves the whole plan", async () => {
    const api = mockApi({
      "GET batches/b1/plan": { body: planRes },
      "GET admin/courses/overview": { body: { courses: [{ course_id: "c1", title: "MERN stack", slug: "mern" }] } },
      "POST batches/b1/plan/preview": { body: schedule },
      "PUT batches/b1/plan": { body: planRes },
    });
    cleanups.push(api.restore);
    renderWithProviders(<BatchPlan batchId="b1" editable />);
    const title = await screen.findByLabelText("Week 1 title");
    await userEvent.clear(title);
    await userEvent.type(title, "HTML & CSS");
    await userEvent.click(screen.getByRole("button", { name: "Sat" }));
    await userEvent.selectOptions(screen.getByLabelText(/LMS course/), "c1");
    await userEvent.click(screen.getByRole("button", { name: "Save plan" }));
    await waitFor(() => expect(api.calls.find((c) => c.method === "PUT")).toBeTruthy());
    const body = api.calls.find((c) => c.method === "PUT")!.body as { plan: { weeks: { title: string }[]; working_days: number[] }; course_id: string; starts_on: string; min_attendance_percent: number };
    expect(body.plan.weeks[0]!.title).toBe("HTML & CSS");
    expect(body.plan.working_days).toEqual([1, 2, 3, 4, 5, 6]);
    expect(body).toMatchObject({ course_id: "c1", starts_on: "2026-11-02", min_attendance_percent: 75 });
  });
});

describe("Classes & attendance tab", () => {
  const routes = () => ({
    "GET batches/b1/sessions": {
      body: {
        today: "2026-11-10",
        students: 2,
        data: [
          { id: "s1", batch_id: "b1", session_date: "2026-11-09", starts_at: "18:30", duration_minutes: 120, topic: "Week 2: Project", meet_url: "https://meet.example.com/abc", recording_url: "https://videos.example.com/r1", notes: null, cancelled: false, attendance: { P: 0, L: 0, A: 0, marked: 0 } },
          { id: "s2", batch_id: "b1", session_date: "2026-11-12", starts_at: "18:30", duration_minutes: 120, topic: "Week 2: APIs", meet_url: "https://meet.example.com/abc", recording_url: null, notes: null, cancelled: false, attendance: { P: 0, L: 0, A: 0, marked: 0 } },
        ],
      },
    },
    "GET batches/b1/attendance": {
      body: { min_attendance_percent: 75, classes_marked: 0, batch: { present: 0, late: 0, absent: 0, marked: 0, percent: null }, data: [{ user_id: "u1", full_name: "Asha", present: 0, late: 0, absent: 0, marked: 0, percent: null, below_minimum: false }] },
    },
    "GET batches/b1/sessions/s1/attendance": {
      body: {
        session: { id: "s1", batch_id: "b1", session_date: "2026-11-09", starts_at: null, duration_minutes: null, topic: "Week 2: Project", meet_url: null, recording_url: null, notes: null, cancelled: false },
        data: [
          { user_id: "u1", full_name: "Asha", in_batch: true, status: null, marked_at: null },
          { user_id: "u2", full_name: "Ravi", in_batch: true, status: "A", marked_at: "2026-11-09T14:00:00Z" },
        ],
      },
    },
    "PUT batches/b1/sessions/s1/attendance": { body: { session: { id: "s1" } } },
  });

  it("marks attendance P / L / A from the class card", async () => {
    const api = mockApi(routes());
    cleanups.push(api.restore);
    renderWithProviders(<ClassesAttendance batchId="b1" canManage />);
    // upcoming by default; past classes behind the "Past" pill
    expect(await screen.findByRole("heading", { name: "Week 2: APIs" })).toBeInTheDocument();
    await userEvent.click(screen.getByLabelText("Past"));
    const card = await screen.findByRole("article", { name: /Week 2: Project/ });
    expect(within(card).getByRole("link", { name: "Recording" })).toHaveAttribute("href", "https://videos.example.com/r1");
    await userEvent.click(within(card).getByRole("button", { name: "Mark attendance" }));
    const dialog = await screen.findByRole("dialog");
    await userEvent.click(await within(dialog).findByRole("button", { name: "Late: Asha" }));
    await userEvent.click(within(dialog).getByRole("button", { name: "Present: Ravi" }));
    expect(within(dialog).getByRole("button", { name: "Present: Ravi" })).toHaveAttribute("aria-pressed", "true");
    await userEvent.click(within(dialog).getByRole("button", { name: "Save attendance" }));
    await waitFor(() => expect(api.calls.find((c) => c.method === "PUT")).toBeTruthy());
    expect(api.calls.find((c) => c.method === "PUT")!.body).toEqual({
      marks: [
        { user_id: "u1", status: "L" },
        { user_id: "u2", status: "P" },
      ],
    });
  });

  it("is read-only without the manage permission", async () => {
    const api = mockApi(routes());
    cleanups.push(api.restore);
    renderWithProviders(<ClassesAttendance batchId="b1" />);
    expect(await screen.findByRole("heading", { name: "Week 2: APIs" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Add class" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Mark attendance/ })).not.toBeInTheDocument();
  });
});

describe("My classes (STU-040)", () => {
  it("shows the next class with its join link, recordings and attendance", async () => {
    const api = mockApi({
      "GET me/classes": {
        body: {
          today: "2026-11-10",
          batches: [
            {
              batch: planRes.batch,
              class_time: "18:30",
              meet_url: "https://meet.example.com/abc",
              current_week: 2,
              weeks_count: 2,
              end_date: "2026-11-13",
              current_week_title: "Project",
              min_attendance_percent: 75,
              attendance: { present: 1, late: 0, absent: 1, marked: 2, percent: 50 },
              upcoming: [{ id: "s3", batch_id: "b1", session_date: "2026-11-10", starts_at: "18:30", duration_minutes: 120, topic: "Week 2: APIs", meet_url: "https://meet.example.com/abc", recording_url: null, cancelled: false }],
              recent: [{ id: "s1", batch_id: "b1", session_date: "2026-11-09", starts_at: "18:30", duration_minutes: 120, topic: "Week 2: Project", meet_url: null, recording_url: "https://videos.example.com/r1", cancelled: false, my_status: "A" }],
            },
          ],
        },
      },
    });
    cleanups.push(api.restore);
    renderWithProviders(<MyClasses />);
    expect(await screen.findByRole("link", { name: "Join class" })).toHaveAttribute("href", "https://meet.example.com/abc");
    expect(screen.getByText("Today")).toBeInTheDocument();
    expect(screen.getByText("Week 2 of 2 · Project")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Watch recording" })).toHaveAttribute("href", "https://videos.example.com/r1");
    expect(screen.getByText("Absent")).toBeInTheDocument();
    expect(screen.getByText("Below the 75% needed for the certificate.")).toBeInTheDocument();
  });

  it("is in the student navigation", () => {
    expect(PORTALS.student.nav.some((n) => n.href === "/app/classes" && n.label === "My classes")).toBe(true);
  });
});
