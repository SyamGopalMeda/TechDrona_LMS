/*
 * Batch delivery (plan, schedule, classes, attendance). verified: apps/api/app/modules/orgs/classes.py
 * and course_plan.py (orgs_0005). Moved from the website back office (AdminCourses.jsx course plans,
 * AdminLearning.jsx "Classes & attendance"); the schedule is computed by the api only.
 */

export const ACTIVITY_KINDS = [
  { value: "project", label: "Project" },
  { value: "assignment", label: "Assignment" },
  { value: "presentation", label: "Presentation" },
  { value: "assessment", label: "Assessment" },
  { value: "test", label: "Test / quiz" },
  { value: "mock_interview", label: "Mock interview" },
] as const;
export type ActivityKind = (typeof ACTIVITY_KINDS)[number]["value"];

/** Website numbering: 0 = Sunday … 6 = Saturday; the editor shows Monday first. */
export const WEEK_ORDER = [1, 2, 3, 4, 5, 6, 0] as const;
export const DAY_NAMES = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"] as const;

export interface PlanActivity {
  id: string;
  kind: ActivityKind;
  title: string;
  due: string | null;
  required: boolean;
}

export interface PlanWeek {
  title: string;
  topics: string[];
  activities: PlanActivity[];
}

/** `course_plan.PlanBody` */
export interface BatchPlanBody {
  total_hours: number;
  daily_hours: number;
  working_days: number[];
  holidays: string[];
  class_time: string | null;
  meet_url: string | null;
  registrations_open: boolean;
  weeks: PlanWeek[];
}

export interface ScheduleActivity extends PlanActivity {
  week: number;
  week_title: string;
  due_effective: string | null;
}

export interface ScheduleWeek {
  n: number;
  from: string | null;
  to: string | null;
  days: string[];
  title: string;
  topics: string[];
  activities: ScheduleActivity[];
  beyond_schedule: boolean;
}

/** `course_plan.schedule_out` */
export interface Schedule {
  sessions: number;
  weeks_count: number;
  hours_planned: number;
  days_per_week: number;
  start_date: string | null;
  end_date: string | null;
  current_week: number;
  today: string;
  weeks: ScheduleWeek[];
  required_activities: number;
}

export interface BatchBrief {
  id: string;
  name: string;
  code: string;
  status: string;
  starts_on: string | null;
  ends_on: string | null;
  course_id: string | null;
  website_course_slug: string | null;
}

/** GET/PUT batches/{id}/plan */
export interface BatchPlanResponse {
  batch: BatchBrief;
  has_plan: boolean;
  plan: BatchPlanBody;
  min_attendance_percent: number | null;
  source_ref: string | null;
  updated_at: string | null;
  schedule: Schedule;
}

export type Mark = "P" | "L" | "A";

export interface MarkCounts {
  P: number;
  L: number;
  A: number;
  marked: number;
}

export interface ClassSession {
  id: string;
  batch_id: string;
  session_date: string;
  starts_at: string | null;
  duration_minutes: number | null;
  topic: string;
  meet_url: string | null;
  recording_url: string | null;
  notes?: string | null;
  cancelled: boolean;
  attendance?: MarkCounts;
}

/** GET batches/{id}/sessions */
export interface SessionList {
  today: string;
  students: number;
  data: ClassSession[];
}

export interface RosterMark {
  user_id: string;
  full_name: string | null;
  in_batch: boolean;
  status: Mark | null;
  marked_at: string | null;
}

/** GET batches/{id}/sessions/{sid}/attendance */
export interface SessionAttendance {
  session: ClassSession;
  data: RosterMark[];
}

export interface AttendanceSummary {
  present: number;
  late: number;
  absent: number;
  marked: number;
  percent: number | null;
}

/** GET batches/{id}/attendance */
export interface BatchAttendance {
  min_attendance_percent: number | null;
  classes_marked: number;
  batch: AttendanceSummary;
  data: (AttendanceSummary & { user_id: string; full_name: string | null; below_minimum: boolean })[];
}

export interface MyClass extends ClassSession {
  my_status?: Mark | null;
}

export interface MyBatchClasses {
  batch: BatchBrief;
  class_time: string | null;
  meet_url: string | null;
  current_week: number;
  weeks_count: number;
  end_date: string | null;
  current_week_title: string | null;
  min_attendance_percent: number | null;
  attendance: AttendanceSummary;
  upcoming: MyClass[];
  recent: MyClass[];
}

/** GET me/classes */
export interface MyClasses {
  today: string;
  batches: MyBatchClasses[];
}

export const MARK_LABEL: Record<Mark, string> = { P: "Present", L: "Late", A: "Absent" };

export const EMPTY_PLAN: BatchPlanBody = {
  total_hours: 0,
  daily_hours: 2,
  working_days: [1, 2, 3, 4, 5],
  holidays: [],
  class_time: null,
  meet_url: null,
  registrations_open: false,
  weeks: [],
};

/** Website `newId()` (activity ids must match ^[\w-]{4,40}$). */
export function newActivityId(): string {
  return `a${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`;
}

const DATE = /^\d{4}-\d{2}-\d{2}$/;

/** "Mon, 02 Nov" for an ISO date (UTC, so the calendar day never shifts). */
export function fmtDay(iso: string | null | undefined): string {
  if (!iso || !DATE.test(iso)) return "";
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(Date.UTC(y!, m! - 1, d!)).toLocaleDateString("en-IN", { weekday: "short", day: "2-digit", month: "short", timeZone: "UTC" });
}

export function pctText(p: number | null | undefined): string {
  return typeof p === "number" ? `${p}%` : "—";
}
