import type { ReactNode } from "react";
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { mockApi, renderWithProviders } from "@/features/auth/test/mock-api";
import { ProgressDashboard } from "./components/ProgressDashboard";
import { rangeForDays, TIME_METRICS } from "./lib/metrics";

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn(), replace: vi.fn() }) }));
// recharts' ResponsiveContainer needs layout; jsdom has none.
vi.mock("recharts", async (orig) => {
  const mod = await orig<typeof import("recharts")>();
  return { ...mod, ResponsiveContainer: ({ children }: { children: ReactNode }) => <div data-testid="chart">{children}</div> };
});

let restore: (() => void) | undefined;
afterEach(() => restore?.());

// verified shape: analytics reports.student_metrics() via router my_summary
const summary = {
  user_id: "u1",
  learning_time: { today_s: 2_700, this_week_s: 18_000, metric: "M5" },
  mastery: [],
  accuracy_by_topic: [{ topic_id: "t1", answered: 42, correct: 34, accuracy: 0.8095, learning_s: 2_016 }],
  tests: [],
  coding: { runs: 30, submissions: 10, accepted: 6 },
  lessons_completed: 3,
  how_we_measure: { measurement_version: "tm-1.0", params: {}, learning_time_metric: "M5" },
  active_days_streak: 4,
  active_days_last_30: 9,
};

const subjects = {
  items: [
    {
      id: "s1", parent_id: null, kind: "subject", slug: "quant", name: "Quant", path: "quant", depth: 0, position: 0, is_active: true, question_count: 10,
      children: [{ id: "t1", parent_id: "s1", kind: "topic", slug: "pct", name: "Percentages", path: "quant/pct", depth: 1, position: 0, is_active: true, question_count: 10, children: [] }],
    },
  ],
};

describe("time metric labels", () => {
  it("labels M5 as learning time and never presents M1 as study time", () => {
    expect(TIME_METRICS[0]).toMatchObject({ key: "m5", label: "Learning time" });
    expect(TIME_METRICS.find((m) => m.key === "m1")!.label).toBe("Time signed in (approx.)");
    expect(TIME_METRICS.find((m) => m.key === "m1")!.isNot).toMatch(/Not study time/);
  });

  it("builds IST date ranges", () => {
    expect(rangeForDays(7, new Date("2026-11-03T20:00:00Z"))).toEqual({ from: "2026-10-29", to: "2026-11-04" });
  });
});

describe("ProgressDashboard", () => {
  it("shows the five time measures with the browser-measured caveat and a table alternative to the chart", async () => {
    const api = mockApi({
      "GET me/analytics/summary": { body: summary },
      "GET me/analytics/learning-time": {
        body: {
          grain: "day",
          measurement_version: "tm-1.0",
          metric: "M5",
          points: Array.from({ length: 7 }, (_, i) => ({
            period_start: `2026-10-2${i}`,
            learning_s: i === 3 ? 0 : 600 * (i + 1),
            active_s: 4_000,
            video_s: 1_000,
            assessment_s: 0,
          })),
        },
      },
      "GET placement/subjects": { body: subjects },
      "GET me/mastery": {
        body: {
          method: "ewma-practice-v1",
          method_note: "EWMA (alpha 0.3) of practice correctness.",
          topics: [{ topic_id: "t1", name: "Percentages", path: "quant/pct", answered: 42, correct: 34, accuracy: 0.81, weighted_accuracy: 0.82, band: "mastered", last_practiced_at: "2026-11-03T10:00:00Z" }],
        },
      },
    });
    restore = api.restore;
    renderWithProviders(<ProgressDashboard />);

    expect(await screen.findByText("45 min")).toBeInTheDocument(); // today M5
    const timeTable = screen.getByRole("table", { name: /Five time measures/ });
    for (const label of ["Learning time", "Active time (est.)", "Video playback time", "Test time", "Time signed in (approx.)"]) {
      expect(within(timeTable).getByText(label)).toBeInTheDocument();
    }
    expect(within(timeTable).getByText("7 h 47 min")).toBeInTheDocument(); // M2 = 7 × 4,000 s
    expect(within(timeTable).getByText("Not reported yet")).toBeInTheDocument(); // M1 isn't returned by the backend
    expect(screen.getAllByText(/Browser-measured estimate/).length).toBeGreaterThan(0);

    expect(await screen.findByRole("img", { name: /How much learning time/ })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "View as table" }));
    const table = screen.getByRole("table", { name: /How much learning time/ });
    expect(within(table).getByText("0 s")).toBeInTheDocument();
    expect(within(table).getAllByRole("row")).toHaveLength(8);

    expect(await screen.findByText("Mastered")).toBeInTheDocument();
    expect(screen.getByRole("table", { name: "Accuracy and learning time by topic" })).toBeInTheDocument();
    const call = api.calls.find((c) => c.path === "me/analytics/learning-time")!;
    expect(call.url).toMatch(/grain=day/);
  }, 15_000); // recharts render: 1.3-4 s alone, over the 5 s default under the full parallel run
});
