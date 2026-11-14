import { api } from "@/lib/api/client";
import type { AnalyticsSummary, LearningTimeBucket, LearningTimeSeries, TimeMetricKey } from "./types";
import { todayIST } from "@/lib/time";

/**
 * The five time metrics (analytics-event-schema §3.11) with the honest labels required by
 * design-system §6 rule 6: M5 is the headline "Learning time"; M1 is never study time.
 */
export const TIME_METRICS: { key: TimeMetricKey; label: string; description: string; isNot: string }[] = [
  {
    key: "m5",
    label: "Learning time",
    description: "Time on lessons, practice, tests and coding with signs of learning activity (playing a video, scrolling, answering, running code).",
    isNot: "Excludes dashboards, catalog, account and billing pages, and active time with no learning activity.",
  },
  {
    key: "m2",
    label: "Active time (est.)",
    description: "Time this site was visible and you interacted with it recently, across all your tabs and devices (overlaps counted once).",
    isNot: "Not proof of attention.",
  },
  {
    key: "m3",
    label: "Video playback time",
    description: "Time lesson videos were playing.",
    isNot: "Includes playback in a hidden tab; not a learning measure on its own.",
  },
  {
    key: "m4",
    label: "Test time",
    description: "Time from starting each test to submitting it, from our server's clock.",
    isNot: "Includes time away from the screen; says nothing about effort per question.",
  },
  {
    key: "m1",
    label: "Time signed in (approx.)",
    description: "From your first to last activity in each sitting, including pauses up to 30 minutes.",
    isNot: "Not study time: it includes idle open tabs.",
  },
];

export const BROWSER_CAVEAT =
  "Browser-measured estimate. These numbers come from what your browser reports (visible tab, recent input, media playing). They can't prove attention or who was at the keyboard, and they can miss time when you're offline. Use them as a guide, not a grade.";

/**
 * Period totals of the time measures, summed from the learning-time buckets (ANL-05 returns
 * M2–M5 per bucket). M1 ("time signed in") is not reported by the backend, so it is null.
 */
export function periodTotals(points: LearningTimeBucket[] | undefined): Record<TimeMetricKey, number | null> {
  if (!points) return { m1: null, m2: null, m3: null, m4: null, m5: null };
  const sum = (f: (b: LearningTimeBucket) => number) => points.reduce((a, b) => a + f(b), 0);
  return { m1: null, m2: sum((b) => b.active_s), m3: sum((b) => b.video_s), m4: sum((b) => b.assessment_s), m5: sum((b) => b.learning_s) };
}

export function rangeForDays(days: number, now: Date = new Date()): { from: string; to: string } {
  const to = todayIST(now);
  const from = todayIST(new Date(now.getTime() - (days - 1) * 86_400_000));
  return { from, to };
}

export const progressApi = {
  summary: () => api.get<AnalyticsSummary>("me/analytics/summary"),
  learningTime: (from: string, to: string, grain: "day" | "week") =>
    api.get<LearningTimeSeries>("me/analytics/learning-time", { query: { from, to, grain } }),
};
