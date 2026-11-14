import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { mockApi, renderWithProviders } from "@/features/auth/test/mock-api";
import { TestBuilder, codingRuleErrors, toSectionsBody } from "./Tests";

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn(), replace: vi.fn() }) }));

let restore: (() => void) | undefined;
afterEach(() => restore?.());

const PROBLEM = "01900000-0000-7000-8000-0000000000c1";

const def = {
  id: "t1",
  title: "DSA Weekly 3",
  test_kind: "mock",
  status: "draft",
  version: 1,
  duration_seconds: 3600,
  navigation_mode: "free",
  attempts_allowed: 1,
  shuffle_questions: true,
  pass_percentage: null,
  settings_locked_at: null,
  batch_id: "b1",
  sections: [
    {
      section_id: "s1",
      title: "Section A",
      position: 0,
      duration_seconds: null,
      instructions_md: null,
      question_count: 2,
      rules: [
        { rule_id: "r1", position: 0, rule_type: "random", question_id: null, question_version_id: null, topic_id: "arrays", company_id: null, question_types: ["coding"], difficulty_min: 2, difficulty_max: 4, draw_count: 2, marks_each: "10", negative_marks_each: null },
      ],
    },
  ],
};

describe("test builder coding section (w2a webstaff R10, ADM-49)", () => {
  it("serialises a fixed coding rule by coding_problem_id and keeps question_types on random rules", () => {
    const body = toSectionsBody([
      {
        title: "Coding",
        duration_minutes: null,
        rules: [
          { rule_type: "fixed", coding_problem_id: PROBLEM, question_id: null, topic_id: "", difficulty_min: 1, difficulty_max: 5, draw_count: 1, marks_each: 10, negative_marks_each: 0 },
          { rule_type: "random", question_types: ["coding"], topic_id: "t", difficulty_min: 1, difficulty_max: 5, draw_count: 2, marks_each: 5, negative_marks_each: 0 },
        ],
      },
    ]);
    const [fixed, random] = body.sections[0]!.rules;
    expect(fixed).toMatchObject({ rule_type: "fixed", coding_problem_id: PROBLEM, draw_count: 1 });
    expect(fixed).not.toHaveProperty("question_id");
    expect(random).toMatchObject({ rule_type: "random", question_types: ["coding"] });
  });

  it("maps the 422 for an unknown coding problem to a plain message", () => {
    const out = codingRuleErrors({ "sections.0.rules.1.coding_problem_id": "no active, published coding question uses this coding problem", title: "x" });
    expect(out["sections.0.rules.1.coding_problem_id"]).toMatch(/No published coding question uses this problem/);
    expect(out.title).toBe("x");
  });

  it("adds a coding problem from the picker, shows Batch-owned, and saves it; a 422 lands on the rule", async () => {
    const api = mockApi({
      "GET studio/tests/t1": { body: def },
      "GET studio/coding/problems/published": { body: { data: [{ problem_id: PROBLEM, slug: "two-sum", title: "Two Sum", difficulty: 3, version_no: 1, organization_id: null }], page: { next_cursor: null, has_more: false, limit: 100 } } },
      "PATCH studio/tests/t1": { body: def },
      "PUT studio/tests/t1/sections": {
        status: 422,
        body: {
          type: "x",
          title: "Validation failed",
          status: 422,
          code: "validation_failed",
          errors: [{ field: "sections.0.rules.1.coding_problem_id", code: "not_found", message: "no active, published coding question uses this coding problem" }],
        },
      },
    });
    restore = api.restore;
    renderWithProviders(<TestBuilder testId="t1" />);
    expect(await screen.findByText("Batch-owned")).toBeInTheDocument();
    expect(screen.getByLabelText("Coding questions only (coding section)")).toBeChecked();

    await userEvent.click(screen.getByRole("button", { name: "Add coding problem" }));
    const dialog = await screen.findByRole("dialog");
    await userEvent.click(await within(dialog).findByRole("button", { name: "Add Two Sum" }));
    // COD-24 picker (test.create, incl. batch trainers), not the coding_problem.manage studio list.
    expect(api.calls.some((c) => c.path === "studio/coding/problems/published")).toBe(true);
    expect(api.calls.some((c) => c.path === "studio/coding/problems")).toBe(false);
    await userEvent.click(within(dialog).getByRole("button", { name: "Done" }));
    expect(screen.getByText(/Coding problem:/)).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(api.calls.some((c) => c.method === "PUT")).toBe(true));
    const put = api.calls.find((c) => c.method === "PUT")!.body as { sections: { rules: Record<string, unknown>[] }[] };
    expect(put.sections[0]!.rules[0]).toMatchObject({ rule_type: "random", question_types: ["coding"] });
    expect(put.sections[0]!.rules[1]).toMatchObject({ rule_type: "fixed", coding_problem_id: PROBLEM });
    expect(await screen.findByText(/No published coding question uses this problem yet/)).toBeInTheDocument();
  });
});
