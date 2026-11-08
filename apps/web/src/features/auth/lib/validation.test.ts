import { describe, expect, it } from "vitest";
import { looksLikeSecret } from "@/features/unblock/lib/copy";
import { defaultCapChoice } from "./login-flow";
import { ageOn, normaliseIndianMobile, safeNextPath, validatePassword } from "./validation";

describe("ageOn (DOB age gate)", () => {
  const on = new Date(2026, 10, 3); // 3 Nov 2026
  it("computes completed years", () => {
    expect(ageOn("2008-11-03", on)).toBe(18);
    expect(ageOn("2008-11-04", on)).toBe(17);
    expect(ageOn("2006-04-12", on)).toBe(20);
  });
  it("rejects impossible or future dates", () => {
    expect(ageOn("2006-02-30", on)).toBeNull();
    expect(ageOn("2030-01-01", on)).toBeNull();
    expect(ageOn("nope", on)).toBeNull();
  });
});

describe("safeNextPath", () => {
  it("allows same-origin paths only", () => {
    expect(safeNextPath("/app/learning")).toBe("/app/learning");
    expect(safeNextPath("//evil.example")).toBe("/app");
    expect(safeNextPath("https://evil.example")).toBe("/app");
    expect(safeNextPath("/\\evil")).toBe("/app");
    expect(safeNextPath("/api/v1/auth/logout")).toBe("/app");
    expect(safeNextPath(undefined, "/x")).toBe("/x");
  });

  it("rejects control characters, whitespace and backslashes that the URL parser strips (SEC-04)", () => {
    const origin = "http://localhost:3000";
    for (const evil of [
      "/\t/evil.example",
      new URLSearchParams("next=/%09/evil.example").get("next"),
      "/\n/evil.example",
      "/\r\n/evil.example",
      "/\u0000/evil.example",
      "/\u007F/evil.example",
      "/ /evil.example",
      "/app\\..\\\\evil.example",
      "/\\/evil.example",
    ]) {
      const out = safeNextPath(evil);
      expect(out).toBe("/app");
      expect(new URL(out, origin).origin).toBe(origin);
    }
  });

  it("returns the normalised same-origin path and keeps query and hash", () => {
    expect(safeNextPath("/app/courses?tab=mine#top")).toBe("/app/courses?tab=mine#top");
    expect(safeNextPath("/app/../admin")).toBe("/admin");
    expect(safeNextPath("/app/../api/v1/auth/logout")).toBe("/app");
    expect(safeNextPath("/api")).toBe("/app");
  });
});

describe("contact and password rules", () => {
  it("normalises Indian mobiles", () => {
    expect(normaliseIndianMobile("98765 43221")).toBe("+919876543221");
    expect(normaliseIndianMobile("+91-9876543221")).toBe("+919876543221");
    expect(normaliseIndianMobile("12345")).toBeNull();
  });
  it("applies the 15/128 password rule", () => {
    expect(validatePassword("short")).toMatch(/15/);
    expect(validatePassword("x".repeat(129))).toMatch(/128/);
    expect(validatePassword("correct-horse-battery")).toBeNull();
  });
});

describe("looksLikeSecret (unblock DLP mirror)", () => {
  it("flags OTPs and passwords", () => {
    expect(looksLikeSecret("my OTP is 482913 please")).toBe(true);
    expect(looksLikeSecret("password: hunter2")).toBe(true);
    expect(looksLikeSecret("I moved from Hyderabad to Pune on 30 October with my laptop")).toBe(false);
  });
});

describe("defaultCapChoice", () => {
  it("pre-selects the oldest session without an active attempt", () => {
    expect(
      defaultCapChoice([
        { session_id: "a", device_label: "A", last_active_at: "2026-11-03T10:00:00Z", has_active_attempt: true },
        { session_id: "b", device_label: "B", last_active_at: "2026-11-03T09:00:00Z" },
        { session_id: "c", device_label: "C", last_active_at: "2026-11-03T09:30:00Z" },
      ]),
    ).toBe("b");
  });
});
