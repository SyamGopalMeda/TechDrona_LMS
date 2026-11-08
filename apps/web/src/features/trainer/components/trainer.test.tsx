import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  mockApi,
  problem,
  renderWithProviders,
} from "@/features/auth/test/mock-api";
import { BatchReportView } from "@/features/batches/components/Batches";
import type { BatchReport } from "@/features/batches/lib/types";
import { AssignTestDialog } from "./AssignTest";
import { GradeSubmission, GradingQueue } from "./Grading";
import { AttemptLog, TestOverrides, TestReportPanel } from "./TestOps";
import { TrainerDashboard } from "./TrainerDashboard";
import type { ApiState } from "../shared/use-api";
import type { IntegrityFlag, TestReport } from "../lib/types";
import { IntegrityReview } from "./Integrity";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/trainer/grading",
}));

let restore: (() => void) | undefined;
afterEach(() => restore?.());

const grants = {
  data: [
    {
      grant_id: "g1",
      role_key: "trainer",
      scope_type: "batch",
      scope_id: "b1",
      organization_id: "o1",
    },
  ],
};
const batch = { id: "b1", name: "CSE 2027 A", code: "CSE-A", status: "active" };
const flag: IntegrityFlag = {
  attempt_id: "a1",
  test_id: "t1",
  test_title: "DSA Weekly 3",
  user_id: "u1",
  student_name: "Ananya Reddy",
  organization_id: "o1",
  batch_id: "b1",
  attempt_status: "submitted",
  attempt_no: 1,
  started_at: "2026-11-03T09:00:00.000Z",
  submitted_at: "2026-11-03T10:00:00.000Z",
  integrity_status: "none",
  signals: {
    focus_lost: 7,
    fullscreen_exit: 0,
    paste: 0,
    disconnect: 0,
    rebind: 0,
    rebind_refused: 0,
    reattach_same_device: 0,
    session_revoked_security: 0,
    code_submit_burst: 0,
    similarity_flags: 0,
  },
  reasons: [
    {
      code: "focus_lost",
      label: "Left the test window",
      count: 7,
      threshold: 5,
    },
  ],
  recommendation: "review_recommended",
  status: "open",
  decision: null,
};

describe("TrainerDashboard (TRN-001)", () => {
  it("shows the empty state when no batch is assigned", async () => {
    const api = mockApi({ "GET me/grants": { body: { data: [] } } });
    restore = api.restore;
    renderWithProviders(<TrainerDashboard />);
    expect(
      await screen.findByText("You haven't been assigned a batch yet"),
    ).toBeInTheDocument();
  });

  it("lists my batches from grants and tests I can assign", async () => {
    const api = mockApi({
      "GET me/grants": { body: grants },
      "GET batches/b1": { body: batch },
      "GET studio/tests": {
        body: {
          items: [
            {
              id: "t1",
              title: "DSA Weekly 3",
              test_kind: "mock",
              status: "published",
              duration_seconds: 3600,
            },
          ],
        },
      },
      "GET integrity/flags": {
        body: {
          data: [flag],
          page: { next_cursor: "c2", has_more: true, limit: 25 },
          thresholds: {},
        },
      },
    });
    restore = api.restore;
    renderWithProviders(<TrainerDashboard />);
    expect(
      await screen.findByRole("link", { name: "CSE 2027 A" }),
    ).toHaveAttribute("href", "/trainer/batches/b1");
    expect(await screen.findByText("1+")).toBeInTheDocument();
    expect(api.calls.find((c) => c.path === "integrity/flags")?.url).toContain(
      "status=open",
    );
    expect(
      await screen.findByRole("link", { name: "DSA Weekly 3" }),
    ).toHaveAttribute("href", "/trainer/tests/t1/edit");
  });
});

describe("AssignTestDialog (ASM-10)", () => {
  it("validates the window and assigns the test to a batch", async () => {
    const api = mockApi({
      "GET tests/t1/assignments": { body: { items: [] } },
      "POST tests/t1/assignments": { status: 201, body: { id: "as1" } },
    });
    restore = api.restore;
    const onAssigned = vi.fn();
    renderWithProviders(
      <AssignTestDialog
        open
        testId="t1"
        testTitle="DSA Weekly 3"
        batches={[{ value: "b1", label: "CSE 2027 A" }]}
        onClose={() => {}}
        onAssigned={onAssigned}
      />,
    );
    await screen.findByText("Not assigned yet");

    await userEvent.click(screen.getByRole("button", { name: "Assign test" }));
    expect(await screen.findByText("Choose a batch.")).toBeInTheDocument();

    await userEvent.selectOptions(screen.getByLabelText(/^Batch/), "b1");
    await userEvent.type(screen.getByLabelText(/^Opens/), "2026-11-07T09:00");
    await userEvent.type(screen.getByLabelText(/^Closes/), "2026-11-07T08:00");
    await userEvent.click(screen.getByRole("button", { name: "Assign test" }));
    expect(
      await screen.findByText("The window must close after it opens."),
    ).toBeInTheDocument();

    await userEvent.clear(screen.getByLabelText(/^Closes/));
    await userEvent.type(screen.getByLabelText(/^Closes/), "2026-11-09T21:00");
    await userEvent.selectOptions(
      screen.getByLabelText("Release results"),
      "manual",
    );
    await userEvent.click(screen.getByRole("button", { name: "Assign test" }));
    await waitFor(() => expect(onAssigned).toHaveBeenCalled());
    const body = api.calls.find((c) => c.method === "POST")!.body as Record<
      string,
      unknown
    >;
    expect(body).toMatchObject({
      batch_id: "b1",
      attempts_allowed: 1,
      release_mode: "manual",
      results_release_at: null,
    });
    expect(new Date(body.available_from as string).getTime()).toBeLessThan(
      new Date(body.available_until as string).getTime(),
    );
    expect(
      await screen.findByText("Assigned DSA Weekly 3 to CSE 2027 A"),
    ).toBeInTheDocument();
  });

  it("shows a window conflict inline", async () => {
    const api = mockApi({
      "GET tests/t1/assignments": { body: { items: [] } },
      "POST tests/t1/assignments": problem(
        409,
        "window_conflict",
        "Window conflict",
        { detail: "CSE 2027 A already has Aptitude Mock 2 in this window." },
      ),
    });
    restore = api.restore;
    renderWithProviders(
      <AssignTestDialog
        open
        testId="t1"
        testTitle="DSA Weekly 3"
        batches={[{ value: "b1", label: "CSE 2027 A" }]}
        onClose={() => {}}
      />,
    );
    await userEvent.selectOptions(await screen.findByLabelText(/^Batch/), "b1");
    await userEvent.type(screen.getByLabelText(/^Opens/), "2026-11-07T09:00");
    await userEvent.type(screen.getByLabelText(/^Closes/), "2026-11-07T11:00");
    await userEvent.click(screen.getByRole("button", { name: "Assign test" }));
    expect(
      await screen.findByText(/already has Aptitude Mock 2/),
    ).toBeInTheDocument();
  });
});

describe("AttemptLog", () => {
  it("shows rebind counts and integrity status, and grants a rebind override", async () => {
    const api = mockApi({
      "GET me/grants": { body: grants },
      "GET batches/b1": { body: batch },
      "GET batches/b1/members": {
        body: {
          data: [
            {
              user_id: "u1",
              full_name: "Ananya Reddy",
              member_role: "student",
            },
          ],
        },
      },
      "GET tests/t1/attempts": {
        body: {
          items: [
            {
              attempt_id: "a1",
              user_id: "u1",
              attempt_no: 1,
              status: "in_progress",
              submit_reason: null,
              started_at: "2026-11-03T09:00:00.000Z",
              submitted_at: null,
              rebind_count: 2,
              integrity_status: "review_recommended",
              score: null,
              max_score: null,
              percentage: null,
            },
          ],
        },
      },
      "POST attempts/a1/rebind-override": {
        status: 201,
        body: { attempt_id: "a1", granted: true },
      },
    });
    restore = api.restore;
    renderWithProviders(<AttemptLog testId="t1" />);
    const row = (await screen.findByText("Ananya Reddy")).closest("tr")!;
    expect(within(row).getByText("2")).toBeInTheDocument();
    expect(within(row).getByText("Review recommended")).toBeInTheDocument();

    await userEvent.click(
      within(row).getByRole("button", { name: "Allow device change" }),
    );
    const allow = await screen.findByRole("button", { name: "Allow" });
    expect(allow).toBeDisabled();
    await userEvent.type(screen.getByLabelText(/Reason/), "Laptop died");
    await userEvent.click(allow);
    await waitFor(() =>
      expect(
        api.calls.find((c) => c.path === "attempts/a1/rebind-override")?.body,
      ).toEqual({ reason: "Laptop died" }),
    );
  });
});

describe("TestOverrides (TRN-007)", () => {
  it("requires a reason and sends seconds to the api", async () => {
    const api = mockApi({
      "GET tests/t1/overrides": { body: { items: [] } },
      "GET me/grants": { body: grants },
      "GET batches/b1": { body: batch },
      "GET batches/b1/members": {
        body: {
          data: [
            { user_id: "u1", full_name: "Ravi Kumar", member_role: "student" },
          ],
        },
      },
      "POST tests/t1/overrides": { status: 201, body: { id: "o1" } },
    });
    restore = api.restore;
    renderWithProviders(<TestOverrides testId="t1" />);
    await screen.findByRole("option", { name: "CSE 2027 A" });
    await userEvent.selectOptions(screen.getByLabelText(/^Batch/), "b1");
    await screen.findByRole("option", { name: "Ravi Kumar" });
    await userEvent.selectOptions(screen.getByLabelText(/^Student/), "u1");
    await userEvent.clear(screen.getByLabelText(/Extra time/));
    await userEvent.type(screen.getByLabelText(/Extra time/), "15");
    await userEvent.click(
      screen.getByRole("button", { name: "Grant override" }),
    );
    expect(await screen.findByText(/A reason is required/)).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText(/^Reason/), "Power cut");
    await userEvent.click(
      screen.getByRole("button", { name: "Grant override" }),
    );
    await waitFor(() =>
      expect(api.calls.find((c) => c.method === "POST")?.body).toEqual({
        user_id: "u1",
        extra_time_seconds: 900,
        extra_attempts: 0,
        window_extension_seconds: 0,
        reason: "Power cut",
      }),
    );
  });
});

describe("GradingQueue (TRN-008)", () => {
  it("grades a submission", async () => {
    const api = mockApi({
      "GET assignments": {
        body: {
          data: [
            {
              id: "as1",
              assignment_id: "as1",
              title: "Arrays worksheet",
              batch_id: "b1",
              batch_name: "CSE-A",
              max_score: 10,
              max_points: 10,
              pending_count: 1,
              grades_released: false,
            },
          ],
          page: { next_cursor: null, has_more: false, limit: 100 },
        },
      },
      "GET batches/b1/members": {
        body: {
          data: [
            { user_id: "u1", full_name: "Ravi Kumar", member_role: "student" },
          ],
        },
      },
      "GET assignments/as1/submissions": {
        body: {
          data: [
            {
              id: "s1",
              assignment_id: "as1",
              user_id: "u1",
              attempt_no: 1,
              submitted_at: "2026-11-02T10:00:00.000Z",
              status: "late",
              body_text: null,
              link_url: null,
              file_s3_keys: [],
              score: null,
            },
          ],
          page: { next_cursor: null, has_more: false, limit: 200 },
        },
      },
      "POST assignment-submissions/s1/grade": { body: { ok: true } },
    });
    restore = api.restore;
    renderWithProviders(<GradingQueue />);
    await userEvent.selectOptions(
      await screen.findByLabelText("Assignment"),
      "as1",
    );
    expect(await screen.findByText("Late")).toBeInTheDocument();
    await userEvent.click(
      await screen.findByRole("button", { name: "Grade Ravi Kumar" }),
    );
    await userEvent.type(screen.getByLabelText(/Points/), "11");
    await userEvent.click(screen.getByRole("button", { name: "Save grade" }));
    expect(await screen.findByText("Enter 0 to 10.")).toBeInTheDocument();
    await userEvent.clear(screen.getByLabelText(/Points/));
    await userEvent.type(screen.getByLabelText(/Points/), "8");
    await userEvent.click(screen.getByRole("button", { name: "Save grade" }));
    await waitFor(() =>
      expect(api.calls.find((c) => c.method === "POST")?.body).toEqual({
        action: "grade",
        score: 8,
        feedback_md: null,
      }),
    );
  });
});

describe("BatchReportView (ANL-06)", () => {
  const state = (
    over: Partial<ApiState<BatchReport>>,
  ): ApiState<BatchReport> => ({
    data: undefined,
    error: null,
    loading: false,
    reload: async () => {},
    ...over,
  });

  it("shows the whole-report k-floor notice", async () => {
    const { ApiError } = await import("@/lib/api/errors");
    const err = new ApiError(
      403,
      {
        type: "x",
        title: "Too few",
        status: 403,
        code: "k_anonymity_floor",
        request_id: "r",
        k_min: 12,
      } as never,
      "r",
    );
    renderWithProviders(<BatchReportView state={state({ error: err })} />);
    expect(screen.getByText("Too few students to show")).toBeInTheDocument();
    expect(screen.getByText(/at least 12 students/)).toBeInTheDocument();
  });

  it("shows suppressed learning time and students needing attention", () => {
    const data: BatchReport = {
      batch_id: "b1",
      week_start: "2026-11-02",
      learners_total: 8,
      weekly_learning_time: {
        n: "<10",
        median_s: "<10",
        p90_s: "<10",
        suppressed: true,
      },
      learners: [
        {
          user_id: "u1",
          weekly_learning_s: 3600,
          weak_topics: 3,
          needs_attention: true,
          reasons: ["weak_required_topics"],
        },
        {
          user_id: "u2",
          weekly_learning_s: 0,
          weak_topics: 0,
          needs_attention: false,
          reasons: [],
        },
      ],
      progress_distribution: null,
      lesson_funnel: null,
      measurement_version: 1,
    };
    renderWithProviders(
      <BatchReportView state={state({ data })} names={{ u1: "Ravi Kumar" }} />,
    );
    expect(screen.getAllByText("Too few to show")).toHaveLength(2);
    expect(screen.getByText("Ravi Kumar")).toBeInTheDocument();
    expect(screen.getByText("Weak in 2+ required topics")).toBeInTheDocument();
  });
});

describe("IntegrityReview (TRN-010)", () => {
  it("lists advisory flags and records a decision with a required note", async () => {
    const api = mockApi({
      "GET me/grants": { body: grants },
      "GET batches/b1": { body: batch },
      "GET studio/tests": { body: { items: [] } },
      "GET integrity/flags": {
        body: {
          data: [flag],
          page: { next_cursor: null, has_more: false, limit: 25 },
          thresholds: { focus_lost: 5 },
        },
      },
      "POST attempts/a1/integrity-decision": {
        status: 201,
        body: {
          decision_id: "d1",
          attempt_id: "a1",
          outcome: "refer_security",
          note: "x",
          decided_at: "",
          decided_by: "",
          attempt_status: "submitted",
          integrity_status: "review_recommended",
          security_case_ref: "SEC-1",
        },
      },
    });
    restore = api.restore;
    renderWithProviders(<IntegrityReview />);
    const row = (await screen.findByText("Ananya Reddy")).closest("tr")!;
    expect(within(row).getByText(/Left the test window/)).toBeInTheDocument();
    expect(within(row).getByText("Review recommended")).toBeInTheDocument();
    expect(screen.queryByText(/cheat/i)).not.toBeInTheDocument();

    await userEvent.click(
      within(row).getByRole("button", { name: "Review Ananya Reddy" }),
    );
    await userEvent.click(
      await screen.findByRole("button", { name: "Record decision" }),
    );
    expect(await screen.findByText("Choose an outcome.")).toBeInTheDocument();
    expect(screen.getByText(/Add a note/)).toBeInTheDocument();
    await userEvent.click(screen.getByLabelText(/Refer to security/));
    await userEvent.type(
      screen.getByLabelText(/^Note/),
      "Repeated focus loss during coding section",
    );
    await userEvent.click(
      screen.getByRole("button", { name: "Record decision" }),
    );
    await waitFor(() => {
      const call = api.calls.find((c) => c.method === "POST");
      expect(call?.body).toEqual({
        outcome: "refer_security",
        note: "Repeated focus loss during coding section",
      });
      expect(Object.keys(call!.headers).map((h) => h.toLowerCase())).toContain(
        "idempotency-key",
      );
    });
    expect(
      await screen.findByText(/Security case SEC-1 opened/),
    ).toBeInTheDocument();
  });

  it("disables invalidation while the attempt is in progress", async () => {
    const api = mockApi({
      "GET me/grants": { body: grants },
      "GET batches/b1": { body: batch },
      "GET studio/tests": { body: { items: [] } },
      "GET integrity/flags": {
        body: {
          data: [{ ...flag, attempt_status: "in_progress" }],
          page: { next_cursor: null, has_more: false, limit: 25 },
          thresholds: {},
        },
      },
    });
    restore = api.restore;
    renderWithProviders(<IntegrityReview />);
    await userEvent.click(
      await screen.findByRole("button", { name: "Review Ananya Reddy" }),
    );
    expect(
      await screen.findByLabelText(/Invalidate the attempt/),
    ).toBeDisabled();
  });
});

describe("TestReportPanel (TRN-011, ASM-22)", () => {
  const report: TestReport = {
    test_id: "t1",
    title: "DSA Weekly 3",
    scope: "full",
    k_min: 10,
    attempts_count: 4,
    distribution: {
      buckets: [
        { label: "0-10", from: 0, to: 10, count: 1 },
        { label: "90-100", from: 90, to: 100, count: 3 },
      ],
      mean: 72.5,
      median: 91,
    },
    submissions: { submitted: 3, auto_submitted: 1, admin_force: 0, total: 4 },
    sections: [
      {
        section_id: "s1",
        title: "Quant",
        position: 1,
        avg_time_seconds: 125,
        attempts: 4,
      },
    ],
    items: { suppressed: true, reason: "k_floor", data: [] },
  };

  it("shows distribution, submit counts, section times and the item k-floor notice", async () => {
    const api = mockApi({ "GET tests/t1/report": { body: report } });
    restore = api.restore;
    renderWithProviders(<TestReportPanel testId="t1" />);
    expect(
      await screen.findByRole("list", { name: "Attempts per score band" }),
    ).toBeInTheDocument();
    expect(screen.getByText("90-100%")).toBeInTheDocument();
    expect(screen.getByText("Auto-submitted")).toBeInTheDocument();
    expect(screen.getByText("2 min 5 s")).toBeInTheDocument();
    expect(screen.getByText("Too few students to show")).toBeInTheDocument();
  });

  it("shows item stats only for content managers", async () => {
    const api = mockApi({
      "GET tests/t1/report": {
        body: {
          ...report,
          scope: "item_stats_only",
          distribution: null,
          submissions: null,
          sections: null,
          items: {
            suppressed: false,
            reason: null,
            data: [
              {
                question_version_id: "q1",
                question_id: "Q1",
                section_title: "Quant",
                position: 1,
                n: 12,
                difficulty_p: 0.5,
                discrimination: 0.31,
                suppressed: false,
              },
            ],
          },
        },
      },
    });
    restore = api.restore;
    renderWithProviders(<TestReportPanel testId="t1" />);
    expect(await screen.findByText("0.31")).toBeInTheDocument();
    expect(screen.getByText(/item statistics only/)).toBeInTheDocument();
    expect(screen.queryByText("Score distribution")).not.toBeInTheDocument();
  });
});

describe("GradeSubmission (TRN-009)", () => {
  it("shows not-found when the submission isn't visible (404)", async () => {
    restore = mockApi({}).restore;
    renderWithProviders(
      <GradeSubmission submissionId="s1" assignmentId={null} />,
    );
    expect(await screen.findByText("Submission not found")).toBeInTheDocument();
  });

  it("loads the submission by id (LRN-16a) and opens the grade form", async () => {
    const api = mockApi({
      "GET assignments": {
        body: {
          data: [
            {
              id: "as1",
              assignment_id: "as1",
              title: "Arrays",
              batch_id: "b1",
              max_points: 10,
              grades_released: false,
            },
          ],
          page: { next_cursor: null, has_more: false, limit: 100 },
        },
      },
      "GET batches/b1/members": {
        body: {
          data: [
            { user_id: "u1", full_name: "Ravi Kumar", member_role: "student" },
          ],
        },
      },
      "GET assignment-submissions/s1": {
        body: {
          id: "s1",
          assignment_id: "as1",
          user_id: "u1",
          attempt_no: 1,
          status: "submitted",
          file_s3_keys: [],
          score: null,
        },
      },
    });
    restore = api.restore;
    // No ?assignment= needed: the assignment id comes from the submission.
    renderWithProviders(
      <GradeSubmission submissionId="s1" assignmentId={null} />,
    );
    expect(
      await screen.findByRole("button", { name: "Save grade" }),
    ).toBeInTheDocument();
  });
});
