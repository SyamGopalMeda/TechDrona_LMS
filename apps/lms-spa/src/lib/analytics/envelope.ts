import type { Surface } from "./time-model";

/** Wire envelope (analytics-event-schema §1.4). Identity fields are set by the server only. */

export type EntityRef = Partial<
  Record<
    | "course_id"
    | "course_version_id"
    | "lesson_id"
    | "lesson_asset_id"
    | "topic_id"
    | "company_path_id"
    | "question_id"
    | "question_version_id"
    | "test_id"
    | "test_attempt_id"
    | "test_section_id"
    | "coding_problem_id"
    | "assignment_id",
    string
  >
>;

export interface AnalyticsEvent {
  event_id: string;
  event_type: string;
  schema_version: number;
  occurred_at: string;
  mono_ms: number;
  tab_id: string;
  page_instance_id: string;
  seq: number;
  route: string;
  surface?: Surface;
  entity?: EntityRef;
  payload: Record<string, unknown>;
}

export interface AnalyticsBatch {
  sent_at: string;
  csrf?: string;
  client: {
    app_version: string;
    platform: "web" | "android_webview" | "ios_webview";
    tz_offset_min?: number;
    measurement_version: "tm-1.0";
  };
  events: AnalyticsEvent[];
}

export interface IngestResult {
  event_id: string;
  status: "accepted" | "duplicate" | "rejected";
  code?: string;
}

export interface IngestResponse {
  accepted: number;
  duplicate: number;
  rejected: number;
  results: IngestResult[];
  server_time?: string;
  config_version?: string;
}

/** Entity ids are UUIDs on the wire (server rejects the whole event otherwise). */
export const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** Drops empty or non-UUID entity values (e.g. a slug from a route param) so the event stays valid. */
export function cleanEntity(entity: EntityRef | undefined): EntityRef | undefined {
  if (!entity) return undefined;
  const out: EntityRef = {};
  for (const [k, v] of Object.entries(entity) as [keyof EntityRef, string | undefined][]) {
    // `batch_id` is never sent: the server derives the org/batch itself (BE-02, E2E-05).
    if ((k as string) === "batch_id") continue;
    if (typeof v === "string" && UUID_PATTERN.test(v)) out[k] = v;
  }
  return Object.keys(out).length ? out : undefined;
}

/** Route templates only — never raw URLs or query strings (§1.1). */
export const ROUTE_TEMPLATE_PATTERN = /^\/[A-Za-z0-9_\-/[\]]*$/;

export function assertRouteTemplate(route: string): string {
  if (route.length > 200 || !ROUTE_TEMPLATE_PATTERN.test(route)) {
    throw new Error(`analytics: route must be a route template, got "${route}"`);
  }
  return route;
}

/** RFC 3339 with the local offset and millisecond precision (e.g. 2026-11-03T15:45:02.123+05:30). */
export function rfc3339WithOffset(epochMs: number): string {
  const d = new Date(epochMs);
  const offsetMin = -d.getTimezoneOffset();
  const local = new Date(epochMs + offsetMin * 60_000);
  const sign = offsetMin >= 0 ? "+" : "-";
  const abs = Math.abs(offsetMin);
  const hh = String(Math.floor(abs / 60)).padStart(2, "0");
  const mm = String(abs % 60).padStart(2, "0");
  return `${local.toISOString().slice(0, 23)}${sign}${hh}:${mm}`;
}

/** Max events per request (§5.2) and a conservative body budget under the 64 KiB limit. */
export const MAX_EVENTS_PER_BATCH = 100;
export const MAX_BATCH_BYTES = 60 * 1024;
