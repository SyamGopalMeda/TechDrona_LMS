import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { apiRequest, apiRequestRaw, api, buildUrl, configureApiClient, mfaEnrolPath } from "./client";
import { ApiError } from "./errors";

function problem(status: number, body: Record<string, unknown>, requestId = "REQ-1") {
  return new Response(JSON.stringify({ type: "x", title: "T", detail: "D", status, request_id: requestId, ...body }), {
    status,
    headers: { "content-type": "application/problem+json", "x-request-id": requestId },
  });
}

function json(status: number, body: unknown, headers: Record<string, string> = {}) {
  return new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json", "x-request-id": "REQ-OK", ...headers } });
}

describe("api client", () => {
  let restore: () => void = () => {};
  const navigate = vi.fn();

  beforeEach(() => {
    document.cookie = "td_csrf=v1.token.sig; path=/";
    navigate.mockReset();
  });
  afterEach(() => {
    restore();
    document.cookie = "td_csrf=; max-age=0; path=/";
  });

  it("builds URLs under /api/v1", () => {
    expect(buildUrl("me")).toBe("/api/v1/me");
    expect(buildUrl("/api/v1/me", { a: 1, b: null, c: "x y" })).toBe("/api/v1/me?a=1&c=x+y");
  });

  it("sends CSRF + idempotency headers on unsafe methods only", async () => {
    const fetchImpl = vi.fn(async () => json(201, { id: "1" }));
    restore = configureApiClient({ fetchImpl, navigate });
    const r = await api.post<{ id: string }>("support/tickets", { a: 1 }, { idempotencyKey: true });
    expect(r).toMatchObject({ kind: "ok", status: 201, data: { id: "1" }, requestId: "REQ-OK" });
    const headers = (fetchImpl.mock.calls[0] as unknown as [string, RequestInit])[1].headers as Record<string, string>;
    expect(headers["x-csrf-token"]).toBe("v1.token.sig");
    expect(headers["idempotency-key"]).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-7/);
    await api.get("me");
    const getHeaders = (fetchImpl.mock.calls[1] as unknown as [string, RequestInit])[1].headers as Record<string, string>;
    expect(getHeaders["x-csrf-token"]).toBeUndefined();
  });

  it("returns approval_pending as a non-error outcome", async () => {
    const approval = { status: "approval_pending", approval_request_id: "a1", action_type: "policy.change", required_approver_role: "super_admin", expires_at: "2026-11-06T10:15:00.000Z" };
    restore = configureApiClient({ fetchImpl: vi.fn(async () => json(202, approval)), navigate });
    const r = await api.post("admin/policies/x", {});
    expect(r.kind).toBe("approval_pending");
    if (r.kind === "approval_pending") expect(r.approval.approval_request_id).toBe("a1");
  });

  it("opens step-up and retries once with the same Idempotency-Key", async () => {
    const fetchImpl = vi
      .fn()
      .mockResolvedValueOnce(problem(401, { code: "step_up_required", step_up: { max_age_seconds: 300, allowed_methods: ["totp"], options_url: "/api/v1/auth/step-up/options" } }))
      .mockResolvedValueOnce(json(200, { done: true }));
    const requestStepUp = vi.fn(async () => true);
    restore = configureApiClient({ fetchImpl, navigate, requestStepUp });
    const r = await apiRequest("finance/refunds/1/decision", { method: "POST", body: {}, idempotencyKey: true });
    expect(r.kind).toBe("ok");
    expect(requestStepUp).toHaveBeenCalledTimes(1);
    const k1 = ((fetchImpl.mock.calls[0] as [string, RequestInit])[1].headers as Record<string, string>)["idempotency-key"];
    const k2 = ((fetchImpl.mock.calls[1] as [string, RequestInit])[1].headers as Record<string, string>)["idempotency-key"];
    expect(k1).toBeTruthy();
    expect(k1).toBe(k2);
  });

  it("throws the step-up problem when the user cancels", async () => {
    const fetchImpl = vi.fn(async () =>
      problem(401, { code: "step_up_required", step_up: { max_age_seconds: 300, allowed_methods: ["totp"], options_url: "/x" } }),
    );
    restore = configureApiClient({ fetchImpl, navigate, requestStepUp: async () => false });
    await expect(api.post("x", {})).rejects.toMatchObject({ code: "step_up_required", status: 401, requestId: "REQ-1" });
    expect(fetchImpl).toHaveBeenCalledTimes(1);
  });

  it("redirects account_restricted to /account/restricted with the case reference", async () => {
    restore = configureApiClient({
      fetchImpl: vi.fn(async () => problem(403, { code: "account_restricted", case_ref: "SEC-2611-7KQ4MZ", level: 3 })),
      navigate,
    });
    const err = await api.get("app/courses").catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(navigate).toHaveBeenCalledWith("/account/restricted?case_ref=SEC-2611-7KQ4MZ&level=3");
  });

  it("routes pending login steps and expired sessions", async () => {
    restore = configureApiClient({
      fetchImpl: vi
        .fn()
        .mockResolvedValueOnce(problem(401, { code: "login_incomplete", next_step: "session_choice" }))
        .mockResolvedValueOnce(problem(401, { code: "session_expired", reason: "idle_timeout" })),
      navigate,
      currentPath: () => "/app/tests",
    });
    await api.get("me").catch(() => undefined);
    await api.get("me").catch(() => undefined);
    expect(navigate).toHaveBeenNthCalledWith(1, "/login/session-choice");
    expect(navigate).toHaveBeenNthCalledWith(2, "/login?next=%2Fapp%2Ftests&reason=session_expired");
  });

  it("hands session_cap_reached and playback_conflict to hooks", async () => {
    const onSessionChoiceRequired = vi.fn();
    const onPlaybackConflict = vi.fn();
    restore = configureApiClient({
      fetchImpl: vi
        .fn()
        .mockResolvedValueOnce(problem(409, { code: "session_cap_reached", sessions: [], max_concurrent: 2 }))
        .mockResolvedValueOnce(problem(409, { code: "playback_conflict", other_device_label: "Phone", takeover_allowed: true })),
      navigate,
      onSessionChoiceRequired,
      onPlaybackConflict,
    });
    await api.post("auth/login", {}).catch(() => undefined);
    const err = await api.post("media/playback-sessions", {}).catch((e: unknown) => e);
    expect(onSessionChoiceRequired).toHaveBeenCalledTimes(1);
    expect(onPlaybackConflict).toHaveBeenCalledWith(expect.objectContaining({ other_device_label: "Phone" }));
    expect((err as ApiError).code).toBe("playback_conflict");
  });

  it("refreshes the CSRF cookie and retries once on csrf_failed", async () => {
    const fetchImpl = vi
      .fn()
      .mockResolvedValueOnce(problem(403, { code: "csrf_failed" }))
      .mockResolvedValueOnce(new Response(null, { status: 204 }))
      .mockResolvedValueOnce(json(200, { ok: 1 }));
    restore = configureApiClient({ fetchImpl, navigate });
    const r = await api.post("x", {});
    expect(r.kind).toBe("ok");
    expect((fetchImpl.mock.calls[1] as [string])[0]).toBe("/api/v1/_bff/csrf");
  });

  it("maps network failures to ApiError status 0", async () => {
    restore = configureApiClient({
      fetchImpl: vi.fn(async () => {
        throw new TypeError("Failed to fetch");
      }),
      navigate,
    });
    const err = (await api.get("me").catch((e: unknown) => e)) as ApiError;
    expect(err.status).toBe(0);
    expect(err.code).toBe("network_error");
    expect(err.title).toMatch(/offline/i);
  });
  it("INV-10: 403 mfa_enrolment_required sends the user to enrol_url (or the default page)", async () => {
    restore = configureApiClient({
      fetchImpl: vi.fn(async () => problem(403, { code: "mfa_enrolment_required", enrol_url: "/app/settings/security/mfa" })),
      navigate,
      currentPath: () => "/admin/users",
    });
    await expect(api.get("admin/users")).rejects.toMatchObject({ status: 403, code: "mfa_enrolment_required" });
    expect(navigate).toHaveBeenCalledWith("/app/settings/security/mfa");
  });

  it("INV-10: does not loop when already on the enrolment page, and rejects unsafe enrol_url values", async () => {
    restore = configureApiClient({
      fetchImpl: vi.fn(async () => problem(403, { code: "mfa_enrolment_required", enrol_url: "/app/settings/security/mfa" })),
      navigate,
      currentPath: () => "/app/settings/security/mfa?x=1",
    });
    await expect(api.get("me")).rejects.toBeInstanceOf(ApiError);
    expect(navigate).not.toHaveBeenCalled();
    expect(mfaEnrolPath("https://evil.example")).toBe("/app/settings/security/mfa");
    expect(mfaEnrolPath("//evil.example")).toBe("/app/settings/security/mfa");
    expect(mfaEnrolPath("/\\evil.example")).toBe("/app/settings/security/mfa");
    expect(mfaEnrolPath(undefined)).toBe("/app/settings/security/mfa");
  });

  it("apiRequestRaw returns the raw Response and throws ApiError on a problem", async () => {
    const fetchImpl = vi
      .fn()
      .mockResolvedValueOnce(new Response("a,b", { status: 200, headers: { "content-type": "text/csv" } }))
      .mockResolvedValueOnce(problem(409, { code: "invalid_state_transition" }));
    restore = configureApiClient({ fetchImpl, navigate });
    const res = await apiRequestRaw("security/reports/exports/e1");
    expect(await res.text()).toBe("a,b");
    await expect(apiRequestRaw("security/reports/exports/e2")).rejects.toMatchObject({ status: 409, code: "invalid_state_transition" });
  });
});
