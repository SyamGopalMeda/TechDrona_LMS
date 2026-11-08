import { readCsrfToken } from "@/lib/api/client";
import type { AnalyticsBatch, IngestResponse } from "./envelope";

/**
 * Delivery to the real ingest endpoints (analytics-event-schema §5.1):
 *   POST /api/v1/analytics/events         fetch, X-CSRF-Token header (keepalive when unloading)
 *   POST /api/v1/analytics/events/beacon  navigator.sendBeacon, CSRF token in the body field `csrf`
 */
export const INGEST_URL = "/api/v1/analytics/events";
export const BEACON_URL = "/api/v1/analytics/events/beacon";
export const CONFIG_URL = "/api/v1/analytics/config";

export type SendOutcome =
  | { kind: "ok"; response: IngestResponse | null }
  /** Retry later (network error, 429, 5xx). `retryAfterMs` from Retry-After if present. */
  | { kind: "retry"; retryAfterMs?: number }
  /** Permanent failure for the whole batch (4xx other than 429): drop it. */
  | { kind: "drop"; status: number }
  /** Beacon queued by the browser: outcome unknown, treated as delivered. */
  | { kind: "beacon_queued" }
  | { kind: "beacon_refused" };

export interface Transport {
  send(batch: AnalyticsBatch, opts: { keepalive: boolean }): Promise<SendOutcome>;
  beacon(batch: AnalyticsBatch): SendOutcome;
}

export function createFetchTransport(
  fetchImpl: typeof fetch = (...a) => globalThis.fetch(...a),
  csrf: () => string | null = readCsrfToken,
  sendBeacon: ((url: string, data: BodyInit) => boolean) | null = typeof navigator !== "undefined" &&
  typeof navigator.sendBeacon === "function"
    ? (url, data) => navigator.sendBeacon(url, data)
    : null,
): Transport {
  return {
    async send(batch, { keepalive }) {
      const token = csrf();
      let res: Response;
      try {
        res = await fetchImpl(INGEST_URL, {
          method: "POST",
          credentials: "same-origin",
          keepalive,
          headers: { "content-type": "application/json", accept: "application/json", ...(token ? { "x-csrf-token": token } : {}) },
          body: JSON.stringify(batch),
        });
      } catch {
        return { kind: "retry" };
      }
      if (res.ok) {
        let body: IngestResponse | null = null;
        try {
          body = (await res.json()) as IngestResponse;
        } catch {
          body = null;
        }
        return { kind: "ok", response: body };
      }
      if (res.status === 429 || res.status >= 500) {
        const ra = Number.parseInt(res.headers.get("retry-after") ?? "", 10);
        return { kind: "retry", retryAfterMs: Number.isFinite(ra) ? ra * 1000 : undefined };
      }
      return { kind: "drop", status: res.status };
    },
    beacon(batch) {
      const token = csrf();
      if (!sendBeacon || !token) return { kind: "beacon_refused" };
      const blob = new Blob([JSON.stringify({ ...batch, csrf: token })], { type: "text/plain;charset=UTF-8" });
      return sendBeacon(BEACON_URL, blob) ? { kind: "beacon_queued" } : { kind: "beacon_refused" };
    },
  };
}
