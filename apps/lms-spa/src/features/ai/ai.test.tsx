import { act, render, renderHook, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { mockApi, problem, renderWithProviders } from "@/features/auth/test/mock-api";
import { ApiError } from "@/lib/api/errors";
import { AIAdmin, AISettingsSection, AIUsageSection, AuthorizedAppsSection, parseCap } from "./admin/AIAdmin";
import { AI_ADMIN_BASE } from "./admin/endpoints";
import { AIErrorState, aiProblemCode } from "./components/AIErrorState";
import { AITutorPanel } from "./components/AITutorPanel";
import { useEnabledApps } from "./hooks/useEnabledApps";

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn(), replace: vi.fn() }) }));

const cleanups: (() => void)[] = [];
afterEach(() => {
  while (cleanups.length) cleanups.pop()!();
});

const apiErr = (status: number, code: string, detail = "x") => new ApiError(status, { type: "t", title: code, status, detail, code, request_id: "req-1" }, "req-1");

/* ------------------------------------------------------------ AIErrorState */

describe("AIErrorState + aiProblemCode", () => {
  it("recognises ai_* codes from ApiError and bare problems only", () => {
    expect(aiProblemCode(apiErr(403, "ai_disabled"))).toBe("ai_disabled");
    expect(aiProblemCode(apiErr(429, "ai_quota_exceeded"))).toBe("ai_quota_exceeded");
    expect(aiProblemCode({ code: "ai_unavailable", status: 503, title: "x" })).toBe("ai_unavailable");
    expect(aiProblemCode(apiErr(403, "permission_denied"))).toBeNull();
    expect(aiProblemCode(new Error("boom"))).toBeNull();
    expect(aiProblemCode(null)).toBeNull();
  });

  it("ai_disabled: friendly copy, no retry", () => {
    render(<AIErrorState code="ai_disabled" onRetry={vi.fn()} />);
    expect(screen.getByRole("alert")).toHaveTextContent("AI help is turned off");
    expect(screen.queryByRole("button", { name: "Try again" })).not.toBeInTheDocument();
  });

  it("ai_quota_exceeded: limit copy", () => {
    render(<AIErrorState code="ai_quota_exceeded" detail="Monthly call cap reached." />);
    expect(screen.getByRole("alert")).toHaveTextContent("AI limit reached");
    expect(screen.getByText("Monthly call cap reached.")).toBeInTheDocument();
  });

  it("ai_unavailable: retry calls back", async () => {
    const onRetry = vi.fn();
    render(<AIErrorState code="ai_unavailable" onRetry={onRetry} />);
    expect(screen.getByRole("alert")).toHaveTextContent("AI is temporarily unavailable — try again later");
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(onRetry).toHaveBeenCalledOnce();
  });

  it("unknown code falls back to generic copy", () => {
    render(<AIErrorState code="something_else" />);
    expect(screen.getByRole("alert")).toHaveTextContent("AI help could not respond");
  });
});

/* ------------------------------------------------------------ AITutorPanel */

describe("AITutorPanel", () => {
  it("shows the counter and remaining count, and updates from the reply", async () => {
    const onAsk = vi.fn().mockResolvedValue({ reply_md: "Try **tracing** the loop.\n<script>x</script>", used: 2, limit: 5 });
    render(<AITutorPanel used={1} limit={5} onAsk={onAsk} />);
    expect(screen.getByText("1 of 5 used")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Guide (4)" })).toBeDisabled(); // empty input
    await userEvent.type(screen.getByLabelText("Your question or code"), "Why does my loop never end?");
    await userEvent.click(screen.getByRole("button", { name: "Guide (4)" }));
    expect(onAsk).toHaveBeenCalledWith("guide", "Why does my loop never end?");
    expect(await screen.findByText("2 of 5 used")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Explain (3)" })).toBeInTheDocument();
    // markdown is rendered as text, never as HTML
    expect(screen.getByText(/Try \*\*tracing\*\* the loop/)).toBeInTheDocument();
    expect(document.querySelector("script")).toBeNull();
  });

  it("shows Unlimited when there is no limit", () => {
    render(<AITutorPanel used={7} limit={null} onAsk={vi.fn()} />);
    expect(screen.getByText("Unlimited")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Guide" })).toBeInTheDocument();
  });

  it("disables asking once the limit is used", () => {
    render(<AITutorPanel used={3} limit={3} onAsk={vi.fn()} />);
    expect(screen.getByText("You've used all your tutor interactions for this activity. Keep going with run & test.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Guide (0)" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Explain (0)" })).toBeDisabled();
    expect(screen.getByLabelText("Your question or code")).toBeDisabled();
  });

  it("renders the AI error state when onAsk rejects with an ai_* problem", async () => {
    const onAsk = vi.fn().mockRejectedValue(apiErr(429, "ai_quota_exceeded", "Monthly call cap reached."));
    render(<AITutorPanel used={0} limit={5} onAsk={onAsk} />);
    await userEvent.type(screen.getByLabelText("Your question or code"), "help");
    await userEvent.click(screen.getByRole("button", { name: "Explain (5)" }));
    expect(await screen.findByText("AI limit reached")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Explain (5)" })).toBeDisabled();
  });

  it("offers retry for ai_unavailable", async () => {
    const onAsk = vi.fn().mockRejectedValueOnce(apiErr(503, "ai_unavailable")).mockResolvedValueOnce({ reply_md: "Think about the base case.", used: 1, limit: null });
    render(<AITutorPanel used={0} limit={null} onAsk={onAsk} />);
    await userEvent.type(screen.getByLabelText("Your question or code"), "recursion?");
    await userEvent.click(screen.getByRole("button", { name: "Explain" }));
    await userEvent.click(await screen.findByRole("button", { name: "Try again" }));
    expect(await screen.findByText("Think about the base case.")).toBeInTheDocument();
    expect(onAsk).toHaveBeenLastCalledWith("explain", "recursion?");
  });
});

/* ---------------------------------------------------------- useEnabledApps */

describe("useEnabledApps", () => {
  it("returns apps, aiEnabled and isEnabled from the platform-wide api (no org_id)", async () => {
    const api = mockApi({ "GET me/enabled-apps": { body: { apps: { engage: false, paths: true, ai_tutor: true }, ai_enabled: true } } });
    cleanups.push(api.restore);
    const { result } = renderHook(() => useEnabledApps());
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(api.calls[0]!.url).toBe("/api/v1/me/enabled-apps");
    expect(result.current.aiEnabled).toBe(true);
    expect(result.current.isEnabled("engage")).toBe(false);
    expect(result.current.isEnabled("paths")).toBe(true);
    expect(result.current.isEnabled("ai_tutor")).toBe(true);
  });

  it("gates ai_* apps on ai_enabled", async () => {
    const api = mockApi({ "GET me/enabled-apps": { body: { apps: { ai_tutor: true }, ai_enabled: false } } });
    cleanups.push(api.restore);
    const { result } = renderHook(() => useEnabledApps());
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(api.calls[0]!.url).toBe("/api/v1/me/enabled-apps");
    expect(result.current.isEnabled("ai_tutor")).toBe(false);
  });

  it("on error: apps fail open, AI fails closed", async () => {
    const api = mockApi({ "GET me/enabled-apps": problem(503, "service_unavailable", "Down") });
    cleanups.push(api.restore);
    const { result } = renderHook(() => useEnabledApps());
    await waitFor(() => expect(result.current.error).toBeTruthy());
    expect(result.current.isEnabled("assignments")).toBe(true);
    expect(result.current.aiEnabled).toBe(false);
    expect(result.current.isEnabled("ai_grading")).toBe(false);
    await act(async () => {});
  });
});

/* ------------------------------------------------------------- admin pages */

const settingsOut = {
  ai: {
    enabled: false,
    model: "claude-sonnet",
    monthly_token_cap: 50_000_000,
    monthly_call_cap: 1000,
    per_activity_default_cap: 20,
    tutor_per_minute: 10,
    tutor_per_day: 200,
    generate_per_hour: 30,
    generate_per_day: 100,
    updated_at: null,
  },
  provider: { name: "anthropic", configured: false },
  allowed_models: ["claude-sonnet", "claude-haiku"],
};

describe("AI settings form", () => {
  it("parses caps", () => {
    expect(parseCap("").error).toBeTruthy();
    expect(parseCap(" 42 ")).toEqual({ value: 42 });
    expect(parseCap("0", 1).error).toBeTruthy();
    expect(parseCap("11", 0, 10).error).toBeTruthy();
    expect(parseCap("-1").error).toBeTruthy();
    expect(parseCap("1.5").error).toBeTruthy();
  });

  it("renders current settings and submits the PATCH body", async () => {
    const api = mockApi({
      [`GET ${AI_ADMIN_BASE}/ai-settings`]: { body: settingsOut },
      [`PATCH ${AI_ADMIN_BASE}/ai-settings`]: (c) => ({ body: { ...settingsOut, ai: { ...settingsOut.ai, ...(c.body as object) } } }),
    });
    cleanups.push(api.restore);
    renderWithProviders(<AISettingsSection />);
    const toggle = await screen.findByLabelText("AI features — question drafting, grading suggestions and the learning tutor");
    expect(toggle).not.toBeChecked();
    expect(screen.getByText("Not configured")).toBeInTheDocument();
    expect(screen.getByLabelText(/^Monthly call cap/)).toHaveValue("1000");
    await userEvent.click(toggle);
    await userEvent.selectOptions(screen.getByLabelText("Model"), "claude-haiku");
    await userEvent.clear(screen.getByLabelText(/^Monthly token cap/));
    await userEvent.type(screen.getByLabelText(/^Monthly token cap/), "500000");
    await userEvent.clear(screen.getByLabelText(/^Tutor messages per activity \(default\)/));
    await userEvent.type(screen.getByLabelText(/^Tutor messages per activity \(default\)/), "3");
    await userEvent.click(screen.getByRole("button", { name: "Save AI settings" }));
    await waitFor(() => expect(api.calls.some((c) => c.method === "PATCH")).toBe(true));
    const patch = api.calls.find((c) => c.method === "PATCH")!;
    expect(patch.body).toEqual({
      enabled: true,
      model: "claude-haiku",
      monthly_call_cap: 1000,
      monthly_token_cap: 500000,
      per_activity_default_cap: 3,
      tutor_per_minute: 10,
      tutor_per_day: 200,
      generate_per_hour: 30,
      generate_per_day: 100,
    });
    expect(patch.headers["x-csrf-token"]).toBe("test-csrf-token");
    expect(await screen.findByText("AI settings saved.")).toBeInTheDocument();
  });

  it("blocks invalid caps client-side and shows server validation errors", async () => {
    const api = mockApi({
      [`GET ${AI_ADMIN_BASE}/ai-settings`]: { body: settingsOut },
      [`PATCH ${AI_ADMIN_BASE}/ai-settings`]: problem(400, "validation_failed", "Invalid", { errors: [{ field: "model", code: "invalid", message: "Model not allowed." }] }),
    });
    cleanups.push(api.restore);
    renderWithProviders(<AISettingsSection />);
    const cap = await screen.findByLabelText(/^Monthly call cap/);
    await userEvent.clear(cap);
    await userEvent.type(cap, "abc");
    await userEvent.click(screen.getByRole("button", { name: "Save AI settings" }));
    expect(screen.getByText("Enter a whole number.")).toBeInTheDocument();
    expect(api.calls.some((c) => c.method === "PATCH")).toBe(false);
    await userEvent.clear(cap);
    await userEvent.click(screen.getByRole("button", { name: "Save AI settings" }));
    expect(screen.getByText("Enter a value.")).toBeInTheDocument();
    expect(api.calls.some((c) => c.method === "PATCH")).toBe(false);
    await userEvent.type(cap, "1000");
    await userEvent.click(screen.getByRole("button", { name: "Save AI settings" }));
    expect(await screen.findByText("Model not allowed.")).toBeInTheDocument();
  });

  it("shows an error state when settings fail to load", async () => {
    const api = mockApi({ [`GET ${AI_ADMIN_BASE}/ai-settings`]: problem(403, "permission_denied", "You don't have access", { detail: "Ask a super admin." }) });
    cleanups.push(api.restore);
    renderWithProviders(<AISettingsSection />);
    expect(await screen.findByText("Ask a super admin.")).toBeInTheDocument();
  });
});

describe("Authorized apps", () => {
  it("groups apps by category and PATCHes the map", async () => {
    const apps = [
      { app_key: "assignments", label: "Assignments", category: "learning", enabled: true },
      { app_key: "engage", label: "Live activities", category: "learning", enabled: false },
      { app_key: "ai_tutor", label: "AI tutor", category: "ai", enabled: false },
    ];
    const api = mockApi({ [`GET ${AI_ADMIN_BASE}/apps`]: { body: { apps } }, [`PATCH ${AI_ADMIN_BASE}/apps`]: { body: { apps } } });
    cleanups.push(api.restore);
    renderWithProviders(<AuthorizedAppsSection />);
    const ai = await screen.findByRole("group", { name: "AI apps" });
    await userEvent.click(within(ai).getByLabelText("AI tutor"));
    await userEvent.click(screen.getByRole("button", { name: "Save apps" }));
    await waitFor(() => expect(api.calls.some((c) => c.method === "PATCH")).toBe(true));
    expect(api.calls.find((c) => c.method === "PATCH")!.body).toEqual({ apps: { assignments: true, engage: false, ai_tutor: true } });
  });
});

describe("AI usage", () => {
  it("renders totals vs caps and breakdowns", async () => {
    const api = mockApi({
      [`GET ${AI_ADMIN_BASE}/ai-usage`]: {
        body: {
          period_start: "2026-11-01",
          period_end: "2026-11-30",
          totals: { calls: 250, tokens_in: 1000, tokens_out: 500, cost_estimate: "1.2500" },
          caps: { monthly_token_cap: 50_000_000, monthly_call_cap: 1000 },
          by_feature: [{ feature: "tutor", calls: 250, tokens_in: 1000, tokens_out: 500, cost_estimate: "1.25" }],
          by_day: [{ date: "2026-11-02", calls: 250, tokens: 1500 }],
        },
      },
    });
    cleanups.push(api.restore);
    renderWithProviders(<AIUsageSection />);
    expect(await screen.findByRole("progressbar", { name: "Calls used" })).toHaveAttribute("aria-valuenow", "250");
    expect(api.calls[0]!.url).toMatch(/ai-usage\?month=\d{4}-\d{2}$/);
    expect(screen.getByText("Learning tutor")).toBeInTheDocument();
    expect(screen.getByText("2026-11-02")).toBeInTheDocument();
    expect(screen.getAllByText("$1.25").length).toBeGreaterThan(0);
  });
});

describe("AIAdmin page (/admin/ai)", () => {
  it("shows the three platform sections without an organization picker", async () => {
    const api = mockApi({ [`GET ${AI_ADMIN_BASE}/ai-settings`]: { body: settingsOut } });
    cleanups.push(api.restore);
    renderWithProviders(<AIAdmin />);
    expect(screen.getByRole("heading", { name: "AI & apps" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Organization/ })).not.toBeInTheDocument();
    for (const t of ["AI settings", "Authorized apps", "Usage"]) expect(screen.getByRole("tab", { name: t })).toBeInTheDocument();
  });
});
