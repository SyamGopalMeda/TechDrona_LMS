import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { mockApi, renderWithProviders } from "@/features/auth/test/mock-api";
import { QuestionBankPicker } from "./index";

let restore: (() => void) | undefined;
afterEach(() => restore?.());

const bank = {
  id: "b1",
  organization_id: null,
  name: "Python lists",
  subject: "Programming",
  description: null,
  question_count: 3,
  type_counts: { mcq_single: 3 },
  tags: ["python"],
  created_at: "2026-11-01T10:00:00Z",
  updated_at: "2026-11-02T10:00:00Z",
  last_added_at: "2026-11-02T10:00:00Z",
  created_by: "u1",
};

const row = (id: string, published: boolean) => ({
  question_id: id,
  question_type: "mcq_single",
  status: published ? "active" : "draft",
  organization_id: null,
  primary_topic_id: null,
  tags: ["python"],
  added_at: "2026-11-02T10:00:00Z",
  published_version_id: published ? `pv-${id}` : null,
  latest_version: { question_version_id: `lv-${id}`, version_no: 1, status: published ? "published" : "draft", reviewed: published, difficulty: 2, stem_html: `<p>Question ${id}</p>`, option_count: 4, correct_count: 1, has_images: false },
});

describe("QuestionBankPicker", () => {
  it("selects the entire bank (published only) and maps the resolved questions", async () => {
    const api = mockApi({
      "GET studio/question-banks": {
        body: { items: [bank], total: 1, counters: { banks: 1, questions: 3, subjects: 1 }, subjects: [{ subject: "Programming", count: 1 }], limit: 100, offset: 0 },
      },
      "GET studio/question-banks/b1/questions": { body: { bank, items: [row("q1", true), row("q2", false), row("q3", true)], total: 3, type_counts: { mcq_single: 3 }, tags: ["python"], limit: 100, offset: 0 } },
      "POST studio/question-banks/resolve": {
        body: {
          items: ["q1", "q3"].map((id) => ({
            question_id: id,
            question_type: "mcq_single",
            tags: ["python"],
            keys_visible: true,
            version: {
              question_version_id: `pv-${id}`,
              version_no: 1,
              status: "published",
              difficulty: 2,
              stem_html: `<p>Question ${id}</p>`,
              stem_images: [{ media_id: "m1", url: "/api/v1/question-media/m1" }],
              settings: {},
              default_marks: "1",
              default_negative: "0",
              expected_seconds: null,
              coding_problem_id: null,
              options: [
                { option_id: "o1", label: "A", html: "x", image: { media_id: "m2", url: "/api/v1/question-media/m2" }, is_correct: true },
                { option_id: "o2", label: "B", html: "y", image: null, is_correct: false },
              ],
            },
          })),
        },
      },
    });
    restore = api.restore;
    const onPick = vi.fn();
    renderWithProviders(<QuestionBankPicker open onClose={() => undefined} onPick={onPick} />);
    expect(await screen.findByText("MCQ banks")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /Python lists/ }));
    expect(await screen.findByText("← All banks")).toBeInTheDocument();
    expect(screen.getByText(/Not published yet/)).toBeInTheDocument();
    expect(screen.getAllByText("4 options")).toHaveLength(3);

    await userEvent.click(screen.getByRole("button", { name: "Select entire bank (2)" }));
    expect(screen.getByText("2 selected")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Add questions" }));
    await waitFor(() => expect(onPick).toHaveBeenCalledTimes(1));

    expect(api.calls.find((c) => c.path === "studio/question-banks/resolve")?.body).toEqual({ question_ids: ["q1", "q3"], prefer: "published" });
    const picked = onPick.mock.calls[0]![0];
    expect(picked).toHaveLength(2);
    expect(picked[0]).toEqual({
      question_id: "q1",
      question_version_id: "pv-q1",
      question_type: "mcq_single",
      stem_html: "<p>Question q1</p>",
      stem_images: [{ media_id: "m1", url: "/api/v1/question-media/m1" }],
      options: [
        { option_id: "o1", label: "A", html: "x", image_url: "/api/v1/question-media/m2", is_correct: true },
        { option_id: "o2", label: "B", html: "y", image_url: null, is_correct: false },
      ],
      settings: {},
      tags: ["python"],
      difficulty: 2,
      bank_id: "b1",
      keys_visible: true,
    });
  });
});
