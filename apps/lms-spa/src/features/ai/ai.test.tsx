import { act, render, renderHook, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { mockApi, problem, renderWithProviders } from "@/features/auth/test/mock-api";
import { ApiError } from "@/lib/api/errors";
import { AIAdmin, AuthorizedAppsSection } from "./admin/AIAdmin";
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

  it("hides the AI toggles while no AI provider is connected, but still saves their values", async () => {
    const apps = [
      { app_key: "assignments", label: "Assignments", category: "learning", enabled: true },
      { app_key: "ai_tutor", label: "AI tutor", category: "ai", enabled: false },
    ];
    const api = mockApi({
      [`GET ${AI_ADMIN_BASE}/apps`]: { body: { apps } },
      [`GET ${AI_ADMIN_BASE}/ai-settings`]: { body: { provider: { name: "disabled", configured: false } } },
      [`PATCH ${AI_ADMIN_BASE}/apps`]: { body: { apps } },
    });
    cleanups.push(api.restore);
    renderWithProviders(<AuthorizedAppsSection />);
    expect(await screen.findByText("AI apps are hidden because no AI provider is connected.")).toBeInTheDocument();
    expect(screen.queryByRole("group", { name: "AI apps" })).not.toBeInTheDocument();
    await userEvent.click(screen.getByLabelText("Assignments"));
    await userEvent.click(screen.getByRole("button", { name: "Save apps" }));
    await waitFor(() => expect(api.calls.some((c) => c.method === "PATCH")).toBe(true));
    expect(api.calls.find((c) => c.method === "PATCH")!.body).toEqual({ apps: { assignments: false, ai_tutor: false } });
  });
});

describe("AIAdmin page (/admin/ai), now \"Apps\"", () => {
  it("shows only the authorized apps, without the AI settings and Usage tabs", async () => {
    const apps = [{ app_key: "assignments", label: "Assignments", category: "learning", enabled: true }];
    const api = mockApi({ [`GET ${AI_ADMIN_BASE}/apps`]: { body: { apps } } });
    cleanups.push(api.restore);
    renderWithProviders(<AIAdmin />);
    expect(screen.getByRole("heading", { name: "Apps" })).toBeInTheDocument();
    expect(await screen.findByLabelText("Assignments")).toBeInTheDocument();
    expect(screen.queryByRole("tab")).not.toBeInTheDocument();
    expect(screen.queryByText("AI settings")).not.toBeInTheDocument();
    expect(api.calls.some((c) => c.url.includes("ai-usage"))).toBe(false);
  });
});
