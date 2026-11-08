import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { mockApi, renderWithProviders } from "@/features/auth/test/mock-api";
import { useActivityTracker } from "@/lib/analytics/use-activity-tracker";
import { CodingQuestion } from "./components/CodingQuestion";
import { CodingWorkspace } from "./components/CodingWorkspace";
import { codingApi } from "./lib/api";

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn(), replace: vi.fn() }) }));
vi.mock("./components/CodeEditor", () => ({
  CodeEditor: (p: { value: string; onChange: (v: string) => void; ariaLabel: string; onFocus?: () => void; onBlur?: () => void }) => (
    <textarea aria-label={p.ariaLabel} value={p.value} onChange={(e) => p.onChange(e.target.value)} onFocus={p.onFocus} onBlur={p.onBlur} />
  ),
}));

function handle() {
  const noop = () => undefined;
  return {
    video: { play: noop, pause: noop, seek: noop, rateChange: noop, ended: noop, bufferingStart: noop, bufferingEnd: noop, error: noop, timeUpdate: noop },
    event: vi.fn(),
    editor: { focus: vi.fn(), blur: vi.fn(), edit: vi.fn() },
    scrollDepth: vi.fn(),
  };
}
const own = vi.hoisted(() => ({ h: null as unknown }));
vi.mock("@/lib/analytics/use-activity-tracker", () => ({ getTabId: () => "tab-1", useActivityTracker: vi.fn(() => own.h) }));

const PID = "01900000-0000-7000-8000-0000000000d1";
const problemBody = {
  problem_id: PID,
  slug: "two-sum",
  title: "Two Sum",
  version_no: 1,
  statement_md: "Given numbers.",
  input_format_md: null,
  output_format_md: null,
  constraints_md: null,
  difficulty: 3,
  limits: { time_limit_ms: 2000, wall_limit_ms: 5000, memory_limit_kb: 262144 },
  allowed_languages: ["python3"],
  scoring_mode: "partial",
  is_free: true,
  samples: [],
  languages: [{ language_key: "python3", display_name: "Python", starter_template: "" }],
};
const routes = {
  "GET coding/problems/two-sum": { body: problemBody },
  "GET coding/languages": { body: { data: [{ language_key: "python3", display_name: "Python" }] } },
};

let restore: (() => void) | undefined;
beforeEach(() => {
  own.h = handle();
  vi.mocked(useActivityTracker).mockClear();
});
afterEach(() => {
  restore?.();
  vi.unstubAllGlobals();
});

describe("coding learning signals (FE-07 / FE-16)", () => {
  it("standalone workspace mounts its own tracker on the coding surface and reports editor focus/blur/edits", async () => {
    const api = mockApi(routes);
    restore = api.restore;
    vi.stubGlobal("fetch", api.fetchImpl);
    renderWithProviders(<CodingWorkspace slug="two-sum" />);
    const editor = await screen.findByLabelText("Code editor, python3", {}, { timeout: 5_000 });
    expect(vi.mocked(useActivityTracker)).toHaveBeenLastCalledWith(
      expect.objectContaining({ route: "/app/coding/[slug]", surface: "coding", entity: { coding_problem_id: PID }, enabled: true }),
    );
    const h = own.h as ReturnType<typeof handle>;
    fireEvent.focus(editor);
    fireEvent.change(editor, { target: { value: "print(1)" } });
    fireEvent.blur(editor);
    expect(h.editor.focus).toHaveBeenCalledWith("python3");
    expect(h.editor.edit).toHaveBeenCalled();
    expect(h.editor.blur).toHaveBeenCalledWith("python3");
  });

  it("embedded in a test, editor signals go to the host (attempt) tracker and no second tracker runs", async () => {
    const api = mockApi(routes);
    restore = api.restore;
    vi.stubGlobal("fetch", api.fetchImpl);
    const host = handle();
    renderWithProviders(<CodingWorkspace slug="two-sum" attemptId="att" embedded tracker={host} />);
    const editor = await screen.findByLabelText("Code editor, python3", {}, { timeout: 5_000 });
    expect(vi.mocked(useActivityTracker)).toHaveBeenLastCalledWith(expect.objectContaining({ enabled: false }));
    fireEvent.focus(editor);
    expect(host.editor.focus).toHaveBeenCalledWith("python3");
  });
});

describe("CodingQuestion (FE-06, w2a weblearn R3): opened by id inside an attempt", () => {
  it("opens COD-03 by problem id with attempt_id and sends attempt_id on draft load and run", async () => {
    const api = mockApi({
      [`GET coding/problems/${PID}`]: { body: problemBody },
      "GET coding/languages": routes["GET coding/languages"],
      [`GET coding/problems/${PID}/drafts/python3`]: { status: 404, body: { type: "x", title: "nf", status: 404, code: "not_found" } },
      [`PUT coding/problems/${PID}/drafts/python3`]: { body: { problem_id: PID, language_key: "python3", source_code: "x", updated_at: "2026-11-03T00:00:00Z" } },
      [`POST coding/problems/${PID}/run`]: { status: 202, body: { submission_id: "s-run", status: "queued" } },
      [`POST coding/problems/${PID}/submit`]: { status: 202, body: { submission_id: "s-sub", status: "queued" } },
      "GET coding/submissions/s-run": { body: { submission_id: "s-run", status: "completed", kind: "run", results: [] } },
      "GET coding/submissions/s-sub": { body: { submission_id: "s-sub", status: "completed", kind: "submit", results: [] } },
    });
    restore = api.restore;
    vi.stubGlobal("fetch", api.fetchImpl);
    renderWithProviders(<CodingQuestion problemId={PID} attemptId="att-1" />);
    const editor = await screen.findByLabelText("Code editor, python3", {}, { timeout: 5_000 });
    expect(screen.getByText("Your last submission counts for this test.")).toBeInTheDocument();
    // No COD-02 walk to find a slug any more.
    expect(api.calls.some((c) => c.path === "coding/problems")).toBe(false);
    const cod03 = api.calls.find((c) => c.method === "GET" && c.path === `coding/problems/${PID}`);
    expect(cod03?.url).toContain("attempt_id=att-1");
    await waitFor(() => expect(api.calls.find((c) => c.path.endsWith("/drafts/python3") && c.method === "GET")?.url).toContain("attempt_id=att-1"));

    fireEvent.change(editor, { target: { value: "print(1)" } });
    fireEvent.click(screen.getByRole("button", { name: /^run/i }));
    await waitFor(() => expect(api.calls.find((c) => c.path.endsWith("/run"))).toBeTruthy());
    expect((api.calls.find((c) => c.path.endsWith("/run"))!.body as { attempt_id: string }).attempt_id).toBe("att-1");
  });

  it("COD-04 draft save carries attempt_id in the query string", async () => {
    const api = mockApi({
      [`PUT coding/problems/${PID}/drafts/python3`]: { body: { problem_id: PID, language_key: "python3", source_code: "x", updated_at: "2026-11-03T00:00:00Z" } },
    });
    restore = api.restore;
    await codingApi.saveDraft(PID, "python3", "x", "att-1");
    expect(api.calls[api.calls.length - 1]!.url).toContain("attempt_id=att-1");
  });
});
