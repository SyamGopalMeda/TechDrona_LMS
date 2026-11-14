import { TM_1_0_DEFAULTS, type Surface, type TimeModelParams } from "./time-model";
import { CONFIG_URL } from "./transport";

/**
 * GET /api/v1/analytics/config (ANL-03) — active tm-* parameters (§5.4: read at boot, never
 * hard-code). The response shape is not yet fixed in api-specification.md; this parser
 * accepts `{ measurement_version, params: { heartbeat_interval_s, flush_interval_s,
 * keepalive_interval_s, idle_threshold_s, idle_threshold_by_surface_s: {surface: s} } }`
 * and clamps each value to the allowed range in §3.1. Unknown/missing → tm-1.0 defaults.
 */

function clampS(value: unknown, min: number, max: number, fallbackMs: number): number {
  if (typeof value !== "number" || !Number.isFinite(value)) return fallbackMs;
  return Math.min(max, Math.max(min, value)) * 1000;
}

export function parseAnalyticsConfig(body: unknown): TimeModelParams {
  if (!body || typeof body !== "object") return TM_1_0_DEFAULTS;
  const b = body as { measurement_version?: unknown; params?: Record<string, unknown> };
  if (b.measurement_version !== undefined && b.measurement_version !== "tm-1.0") return TM_1_0_DEFAULTS;
  const p = b.params ?? {};
  const bySurface: Partial<Record<Surface, number>> = { ...TM_1_0_DEFAULTS.idleMsBySurface };
  const rawSurface = p.idle_threshold_by_surface_s;
  if (rawSurface && typeof rawSurface === "object") {
    for (const [k, v] of Object.entries(rawSurface as Record<string, unknown>)) {
      bySurface[k as Surface] = clampS(v, 30, 600, bySurface[k as Surface] ?? TM_1_0_DEFAULTS.idleMs);
    }
  }
  return {
    measurementVersion: "tm-1.0",
    heartbeatMs: clampS(p.heartbeat_interval_s, 10, 30, TM_1_0_DEFAULTS.heartbeatMs),
    flushMs: clampS(p.flush_interval_s, 15, 60, TM_1_0_DEFAULTS.flushMs),
    keepaliveMs: clampS(p.keepalive_interval_s, 120, 600, TM_1_0_DEFAULTS.keepaliveMs),
    idleMs: clampS(p.idle_threshold_s, 30, 600, TM_1_0_DEFAULTS.idleMs),
    idleMsBySurface: bySurface,
  };
}

let cached: Promise<TimeModelParams | null> | null = null;

/**
 * Resolves to `null` when the api refuses analytics for this session (403: e.g. learning access
 * paused, `account_restricted`): the caller then starts no tracker, so a restricted learner's
 * pages don't keep posting events that are all refused. Other failures fall back to tm-1.0.
 */
export function loadAnalyticsConfig(fetchImpl: typeof fetch = (...a) => globalThis.fetch(...a)): Promise<TimeModelParams | null> {
  cached ??= fetchImpl(CONFIG_URL, { credentials: "same-origin", headers: { accept: "application/json" } })
    .then(async (res) => (res.ok ? parseAnalyticsConfig(await res.json()) : res.status === 403 ? null : TM_1_0_DEFAULTS))
    .catch(() => TM_1_0_DEFAULTS);
  return cached;
}

/** Tests only: forget the cached config. */
export function resetAnalyticsConfigCache(): void {
  cached = null;
}
