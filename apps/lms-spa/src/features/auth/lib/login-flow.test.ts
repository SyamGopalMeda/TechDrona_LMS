import { describe, expect, it } from "vitest";
import { STAFF_LANDING, routeForLoginResult } from "./login-flow";

describe("routeForLoginResult: central login hub", () => {
  it("sends staff to /continue (last page, else the module hub) after sign-in", () => {
    expect(STAFF_LANDING).toBe("/continue");
    for (const redirect of ["/admin", "/trainer", "/studio", "/evaluator"]) {
      expect(routeForLoginResult({ result: "authenticated", redirect })).toBe(STAFF_LANDING);
    }
  });

  it("keeps students on their learning portal", () => {
    expect(routeForLoginResult({ result: "authenticated", redirect: "/app" })).toBe("/app");
    expect(routeForLoginResult({ result: "authenticated" })).toBe("/app");
  });

  it("an explicit next (deep link, /sso/website) wins over the hub", () => {
    expect(routeForLoginResult({ result: "authenticated", redirect: "/admin" }, "/sso/website")).toBe("/sso/website");
    expect(routeForLoginResult({ result: "authenticated", redirect: "/admin" }, "/admin/college-data")).toBe("/admin/college-data");
  });

  it("restrictions still take precedence", () => {
    const r = routeForLoginResult({ result: "authenticated", redirect: "/admin", restriction: { level: 3 } as never });
    expect(r).toBe("/admin");
  });

  it("must_change_password goes to /change-password first, then next (or /continue)", () => {
    expect(routeForLoginResult({ result: "authenticated", redirect: "/app", must_change_password: true })).toBe("/change-password?next=%2Fcontinue");
    expect(routeForLoginResult({ result: "authenticated", redirect: "/admin", must_change_password: true }, "/admin/users")).toBe(
      "/change-password?next=%2Fadmin%2Fusers",
    );
    expect(routeForLoginResult({ result: "authenticated", must_change_password: true }, "//evil.example")).toBe("/change-password?next=%2Fcontinue");
  });
});
