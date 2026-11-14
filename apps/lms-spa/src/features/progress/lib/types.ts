/**
 * Student self analytics (ANL-04/05). Both routes return `dict[str, Any]`; the shapes below are
 * verified against app/modules/analytics/router.py (my_summary, my_learning_time) and
 * app/modules/analytics/reports.py (student_metrics, learning_time_series).
 */

export type TimeMetricKey = "m1" | "m2" | "m3" | "m4" | "m5";

/** verified: reports.py student_metrics() via router.py my_summary */
export interface AnalyticsSummary {
  user_id: string;
  /** M5 learning time; `this_week_s` is Monday (IST) → today */
  learning_time: { today_s: number; this_week_s: number; metric: string };
  /** analytics-owned topic mastery (the progress page uses PLC-25 me/mastery instead) */
  mastery: { topic_id: string; band: string; mastery: number; weighted_accuracy: number; n: number; model_version: string }[];
  /** `accuracy` is 0..1, null when nothing answered */
  accuracy_by_topic: { topic_id: string; answered: number; correct: number; accuracy: number | null; learning_s: number }[];
  tests: { test_attempt_id: string; attempt_time_s: number; time_on_test_page_s: number }[];
  coding: { runs: number; submissions: number; accepted: number };
  lessons_completed: number;
  how_we_measure: { measurement_version: string; params: Record<string, unknown>; learning_time_metric: string };
  /** absent for minors (neutral count only, no streak mechanic); null in org drill-downs */
  active_days_streak?: number | null;
  active_days_last_30: number;
}

/** verified: reports.py learning_time_series() points[] */
export interface LearningTimeBucket {
  /** IST date `YYYY-MM-DD` (week start for grain=week) */
  period_start: string;
  /** M5 */
  learning_s: number;
  /** M2 */
  active_s: number;
  /** M3 */
  video_s: number;
  /** M4 */
  assessment_s: number;
  /** grain=week only */
  active_days?: number;
}

/** verified: router.py my_learning_time */
export interface LearningTimeSeries {
  grain: "day" | "week";
  measurement_version: string;
  metric: string;
  points: LearningTimeBucket[];
}

/** Chart view model (one M5 value per day/week). */
export interface LearningTimePoint {
  date: string;
  m5_s: number | null;
}
