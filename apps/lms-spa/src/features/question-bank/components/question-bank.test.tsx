import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { mockApi, problem, renderWithProviders } from "@/features/auth/test/mock-api";
import type { Bank } from "../lib/types";
import { BankDetail } from "./BankDetail";
import { BankList, VIEW_KEY } from "./BankList";
import { BulkImportDialog } from "./BulkImportDialog";
import { GenerateDialog } from "./GenerateDialog";
import { QuestionEditorDialog, buildContent, emptyEditor, serverType, validateEditor } from "./QuestionEditorDialog";

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn(), replace: vi.fn() }) }));

let restore: (() => void) | undefined;
afterEach(() => {
  restore?.();
  restore = undefined;
  try {
    window.localStorage.clear();
  } catch {
    /* ignore */
  }
});

const bank = (over: Partial<Bank> = {}): Bank => ({
  id: "b1",
  organization_id: null,
  name: "Python lists",
  subject: "Programming",
  description: null,
  question_count: 5,
  type_counts: { mcq_single: 3, mcq_multi: 2 },
  tags: ["python", "lists"],
  created_at: "2026-11-01T10:00:00Z",
  updated_at: "2026-11-02T10:00:00Z",
  last_added_at: "2026-11-02T10:00:00Z",
  created_by: "u1",
  ...over,
});

const listBody = {
  items: [bank(), bank({ id: "b2", name: "Arrays", subject: null, question_count: 10, type_counts: { coding: 10 } })],
  total: 2,
  counters: { banks: 2, questions: 15, subjects: 1 },
  subjects: [
    { subject: "Programming", count: 1 },
    { subject: null, count: 1 },
  ],
  limit: 100,
  offset: 0,
};

describe("BankList", () => {
  it("shows the counters and remembers the grid/list choice", async () => {
    const api = mockApi({ "GET studio/question-banks": { body: listBody } });
    restore = api.restore;
    renderWithProviders(<BankList />);
    expect(await screen.findByText("Python lists")).toBeInTheDocument();
    expect(screen.getByText("Banks").closest("div")?.parentElement).toHaveTextContent("2");
    expect(screen.getByText("Questions").closest("div")?.parentElement).toHaveTextContent("15");
    expect(screen.getByText("Subjects").closest("div")?.parentElement).toHaveTextContent("1");
    expect(screen.getByText("2 banks")).toBeInTheDocument();
    // Grid by default: cards with type-count chips and an "Open bank" link.
    expect(screen.getByText("5 MCQ")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open bank Arrays" })).toHaveAttribute("href", "/studio/question-banks/b2");

    await userEvent.click(screen.getByRole("button", { name: "List" }));
    expect(screen.getByRole("button", { name: "List" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.queryByText("Open bank →")).not.toBeInTheDocument();
    expect(screen.getByText("10 Qs")).toBeInTheDocument();
    expect(window.localStorage.getItem(VIEW_KEY)).toBe("list");
  });

  it("starts in list view when that was remembered", async () => {
    window.localStorage.setItem(VIEW_KEY, "list");
    const api = mockApi({ "GET studio/question-banks": { body: listBody } });
    restore = api.restore;
    renderWithProviders(<BankList />);
    expect(await screen.findByText("10 Qs")).toBeInTheDocument();
  });
});

describe("BankDetail header", () => {
  it("uses the kit PageHeader: breadcrumbs, the bank name as h1, one primary action", async () => {
    const api = mockApi({
      "GET studio/question-banks/b1/questions": { body: { bank: bank({ question_count: 0, type_counts: {} }), items: [], total: 0, type_counts: {}, tags: [], limit: 100, offset: 0 } },
    });
    restore = api.restore;
    renderWithProviders(<BankDetail bankId="b1" />);
    expect(await screen.findByRole("heading", { level: 1, name: "Python lists" })).toBeInTheDocument();
    expect(within(screen.getByRole("navigation", { name: "Breadcrumb" })).getByRole("link", { name: "Question banks" })).toHaveAttribute("href", "/studio/question-banks");
    expect(screen.getByRole("button", { name: "Delete bank" })).toBeInTheDocument();
    // The empty bank does not add a second "Add question" primary.
    expect(screen.getAllByRole("button", { name: "Add question" })).toHaveLength(1);
    expect(screen.getByText("This bank is empty")).toBeInTheDocument();
  });
});

describe("BulkImportDialog", () => {
  it("validates, lists problems and copies the fix prompt for the model", async () => {
    const user = userEvent.setup();
    const api = mockApi({
      "GET studio/question-banks": { body: listBody },
      "POST studio/question-banks/import/prompt": { body: { prompt: "You are an expert assessment author…", schema: {} } },
      "POST studio/question-banks/import/validate": (c) =>
        (c.body as { raw: string }).raw.startsWith("[")
          ? { body: { ok: true, count: 1, problem_count: 0, problems: [], fix_prompt: null, items: [{ index: 0, type: "mcq", text: "What is 2+2?", options: [], tags: [], sample_cases: 0, hidden_cases: 0 }] } }
          : {
              body: {
                ok: false,
                count: 0,
                problem_count: 2,
                problems: [
                  { index: null, field: "", message: "The pasted text isn't valid JSON." },
                  { index: 1, field: "options", message: "Add at least two options." },
                ],
                fix_prompt: "Please fix: invalid JSON",
                items: [],
              },
            },
      "POST studio/question-banks/import": { status: 201, body: { bank: bank({ id: "b9", name: "New bank" }), question_ids: ["q1"], count: 1 } },
    });
    restore = api.restore;
    const onImported = vi.fn();
    renderWithProviders(<BulkImportDialog open onClose={() => undefined} onImported={onImported} debounceMs={0} />);
    expect(await screen.findByText("You are an expert assessment author…")).toBeInTheDocument();
    const importBtn = screen.getByRole("button", { name: "Import" });
    expect(importBtn).toBeDisabled();

    await user.type(screen.getByLabelText("Model response (JSON)"), "not json");
    await user.click(screen.getByRole("button", { name: "Validate" }));
    const panel = (await screen.findAllByText(/2 problems found/)).find((el) => el.closest("[role=alert]"))!;
    const box = panel.closest("[role=alert]") as HTMLElement;
    expect(within(box).getByText(/Whole response/)).toBeInTheDocument();
    expect(within(box).getByText(/Item #2/)).toBeInTheDocument();
    expect(importBtn).toBeDisabled();
    await user.click(within(box).getByRole("button", { name: "Copy for the model" }));
    expect(await navigator.clipboard.readText()).toBe("Please fix: invalid JSON");

    await user.clear(screen.getByLabelText("Model response (JSON)"));
    await user.click(screen.getByLabelText("Model response (JSON)"));
    await user.paste('[{"question":"What is 2+2?"}]');
    await user.click(screen.getByRole("button", { name: "Validate" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Import" })).toBeEnabled());
    await user.click(screen.getByRole("button", { name: "Import" }));
    await waitFor(() => expect(onImported).toHaveBeenCalled());
    const call = api.calls.find((c) => c.method === "POST" && c.path === "studio/question-banks/import")!;
    expect(call.headers["Idempotency-Key"] ?? call.headers["idempotency-key"]).toBeTruthy();
    expect(call.body).toMatchObject({ question_type: "mcq", raw: '[{"question":"What is 2+2?"}]', source: "bulk" });
  });
});

const preview = (i: number) => ({ index: i, type: "mcq", text: `Draft question ${i + 1}`, options: [{ text: "A", correct: true }, { text: "B", correct: false }], tags: ["python"], sample_cases: 0, hidden_cases: 0 });

describe("GenerateDialog", () => {
  it("reviews drafts, counts the selection and saves only the selected ones", async () => {
    const drafts = [0, 1, 2].map((i) => ({ question: `Draft question ${i + 1}` }));
    const api = mockApi({
      "GET studio/question-banks": { body: listBody },
      "POST studio/question-banks/generate": { body: { drafts, previews: [0, 1, 2].map(preview), problems: [] } },
      "POST studio/question-banks/import": { status: 201, body: { bank: bank(), question_ids: ["q1", "q2"], count: 2 } },
    });
    restore = api.restore;
    const onSaved = vi.fn();
    renderWithProviders(<GenerateDialog open onClose={() => undefined} defaultBankId="b1" onSaved={onSaved} />);
    const generate = screen.getByRole("button", { name: "Generate" });
    expect(generate).toBeDisabled();
    await userEvent.type(screen.getByLabelText(/^Topic/), "Python lists");
    await userEvent.click(generate);
    expect(await screen.findByText("3 drafted · 3 selected")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Save 3 to bank" })).toBeEnabled();

    await userEvent.click(screen.getByLabelText("Keep draft 2"));
    expect(screen.getByText("3 drafted · 2 selected")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Clear" }));
    expect(screen.getByRole("button", { name: "Save 0 to bank" })).toBeDisabled();
    await userEvent.click(screen.getByRole("button", { name: "Select all" }));
    await userEvent.click(screen.getByLabelText("Keep draft 2"));
    await userEvent.click(screen.getByRole("button", { name: "Save 2 to bank" }));
    await waitFor(() => expect(onSaved).toHaveBeenCalled());
    const gen = api.calls.find((c) => c.path === "studio/question-banks/generate")!;
    expect(gen.body).toMatchObject({ source_mode: "topic", topic: "Python lists", question_type: "mcq", count: 5 });
    const save = api.calls.find((c) => c.path === "studio/question-banks/import")!;
    expect(save.body).toMatchObject({ source: "ai", bank_id: "b1", items: [drafts[0], drafts[2]] });
  });

  it("shows the shared AI error state when AI is turned off", async () => {
    const api = mockApi({
      "GET studio/question-banks": { body: listBody },
      "POST studio/question-banks/generate": problem(403, "ai_disabled", "AI is disabled"),
    });
    restore = api.restore;
    renderWithProviders(<GenerateDialog open onClose={() => undefined} onSaved={() => undefined} />);
    await userEvent.type(screen.getByLabelText(/^Topic/), "Graphs");
    await userEvent.click(screen.getByRole("button", { name: "Generate" }));
    expect(await screen.findByText("AI help is turned off")).toBeInTheDocument();
  });
});

describe("QuestionEditorDialog", () => {
  it("creates a multi-answer MCQ when several options are ticked", async () => {
    const api = mockApi({ "POST studio/questions": { status: 201, body: { question_id: "q1" } } });
    restore = api.restore;
    const onSaved = vi.fn();
    renderWithProviders(<QuestionEditorDialog open onClose={() => undefined} bankId="b1" onSaved={onSaved} />);
    await userEvent.type(screen.getByLabelText(/^Question description/), "Which are Python sequence types?");
    await userEvent.type(screen.getByLabelText("Option 1"), "list");
    await userEvent.type(screen.getByLabelText("Option 2"), "tuple");
    await userEvent.type(screen.getByLabelText("Option 3"), "dict");
    await userEvent.click(screen.getByRole("button", { name: "Remove option 4" }));
    await userEvent.click(screen.getByLabelText("Option 2 is correct"));
    const tags = screen.getByLabelText("Tags");
    await userEvent.type(tags, "python{Enter}");
    await userEvent.click(screen.getByRole("button", { name: "Add question" }));
    await waitFor(() => expect(onSaved).toHaveBeenCalled());
    expect(api.calls.find((c) => c.path === "studio/questions")?.body).toMatchObject({
      question_type: "mcq_multi",
      bank_id: "b1",
      stem_html: "Which are Python sequence types?",
      options: [
        { html: "list", is_correct: true },
        { html: "tuple", is_correct: true },
        { html: "dict", is_correct: false },
      ],
      tags: [{ tag_type: "custom", value: "python" }],
      difficulty: 3,
    });
  });

  it("builds payloads for the ungraded types and checks the rules", () => {
    const wc = { ...emptyEditor("word_cloud"), stem: "One word for today?" };
    expect(buildContent(wc)).toMatchObject({ options: [], settings: { max_words: 3, max_chars: 20 }, explanation_html: null });
    expect(validateEditor({ ...wc, wcMaxWords: "9" })["settings.max_words"]).toBeTruthy();
    const survey = { ...emptyEditor("survey"), stem: "How was the session?" };
    expect(buildContent(survey)).toMatchObject({ settings: { scale: "likert", points: 5 }, options: [{ html: "Strongly disagree" }, {}, {}, {}, { html: "Strongly agree" }] });
    const mcq = { ...emptyEditor("mcq"), stem: "Pick one please", options: [{ html: "a", is_correct: true, image: null }, { html: "b", is_correct: true, image: null }] };
    expect(serverType(mcq)).toBe("mcq_multi");
    expect(validateEditor(mcq, { fixedType: "mcq_single" }).options).toMatch(/exactly one/);
    expect(validateEditor(mcq, { forReview: true }).explanation_html).toMatch(/required before review/);
    expect(validateEditor({ ...emptyEditor("coding"), stem: "Solve the problem" }).coding_problem_id).toBeTruthy();
  });
});
