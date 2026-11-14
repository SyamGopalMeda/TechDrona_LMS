// Regression for FE-09: the login/signup throttle countdown must honour the Retry-After header.
import { describe, expect, it } from "vitest";
import { ApiError } from "@/lib/api/errors";
import { retryAfterSeconds } from "./errors";

const problem = (extra: Record<string, unknown> = {}) =>
  ({ type: "x", title: "Too many attempts", status: 429, code: "throttled", ...extra }) as never;

describe("retryAfterSeconds", () => {
  it("falls back to the Retry-After header when the body has no extension (FE-09)", () => {
    const err = new ApiError(429, problem(), "req-1", undefined, 600);
    expect(err.retryAfter).toBe(600);
    expect(retryAfterSeconds(err)).toBe(600);
  });

  it("prefers a body extension over the header", () => {
    expect(retryAfterSeconds(new ApiError(429, problem({ retry_after_seconds: 30 }), null, undefined, 600))).toBe(30);
  });

  it("works without a problem body and caps at 24 h", () => {
    expect(retryAfterSeconds(new ApiError(429, null, null, undefined, 10))).toBe(10);
    expect(retryAfterSeconds(new ApiError(429, null, null, undefined, 999_999))).toBe(86_400);
  });

  it("returns null when no wait is known", () => {
    expect(retryAfterSeconds(new ApiError(429, problem(), null))).toBeNull();
    expect(retryAfterSeconds(new Error("x"))).toBeNull();
  });
});
