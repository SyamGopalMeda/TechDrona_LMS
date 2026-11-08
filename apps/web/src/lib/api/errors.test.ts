import { afterEach, describe, expect, it, vi } from "vitest";
import { api, configureApiClient } from "./client";
import { ApiError, parseRetryAfter } from "./errors";

describe("parseRetryAfter", () => {
  it("parses delay-seconds", () => {
    expect(parseRetryAfter("120")).toBe(120);
    expect(parseRetryAfter(" 0 ")).toBe(0);
  });

  it("parses an HTTP-date relative to now (rounded up, never negative)", () => {
    const now = Date.parse("Tue, 03 Nov 2026 10:00:00 GMT");
    expect(parseRetryAfter("Tue, 03 Nov 2026 10:00:30 GMT", now)).toBe(30);
    expect(parseRetryAfter("Tue, 03 Nov 2026 09:59:00 GMT", now)).toBe(0);
  });

  it("returns null when absent or invalid", () => {
    expect(parseRetryAfter(null)).toBeNull();
    expect(parseRetryAfter(undefined)).toBeNull();
    expect(parseRetryAfter("")).toBeNull();
    expect(parseRetryAfter("soon")).toBeNull();
    expect(parseRetryAfter("-5")).toBeNull();
  });
});

describe("ApiError.retryAfter", () => {
  let restore: () => void = () => {};
  afterEach(() => restore());

  it("defaults to null", () => {
    expect(new ApiError(500, null, null).retryAfter).toBeNull();
  });

  it("is populated from the Retry-After header of a 429 response", async () => {
    const res = new Response(
      JSON.stringify({ type: "x", title: "Too many requests", detail: "D", status: 429, code: "rate_limited", request_id: "REQ-9" }),
      { status: 429, headers: { "content-type": "application/problem+json", "x-request-id": "REQ-9", "retry-after": "17" } },
    );
    restore = configureApiClient({ fetchImpl: vi.fn(async () => res), navigate: vi.fn() });
    const err = await api.get("catalog/courses").catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).status).toBe(429);
    expect((err as ApiError).retryAfter).toBe(17);
  });

  it("is null when the header is missing", async () => {
    const res = new Response("oops", { status: 503, headers: { "content-type": "text/plain" } });
    restore = configureApiClient({ fetchImpl: vi.fn(async () => res), navigate: vi.fn() });
    const err = (await api.get("me").catch((e: unknown) => e)) as ApiError;
    expect(err.retryAfter).toBeNull();
  });
});
