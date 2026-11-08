import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { PlayerStep } from "../lib/types";
import { ArticleRenderer } from "./ArticleRenderer";
import { StepRail, firstActionable, stepEmbedUrl } from "./Learner";
import { move, toEditor, toStepIn, totals } from "./PathEditor";

describe("ArticleRenderer", () => {
  it("renders markup in the source as text, never as HTML", () => {
    const { container } = render(
      <ArticleRenderer source={'## Hi <img src=x onerror="alert(1)">\n\n<script>alert(1)</script> and [bad](javascript:alert(1))'} />,
    );
    expect(container.querySelector("script")).toBeNull();
    expect(container.querySelector("img")).toBeNull();
    expect(container.querySelector("a")).toBeNull();
    expect(container.textContent).toContain("<script>alert(1)</script>");
  });

  it("renders callouts, code with copy + output, tables and exercises with show answer", () => {
    render(
      <ArticleRenderer
        source={[
          "## Intro",
          ":::watch-out",
          "Careful",
          ":::",
          "```python",
          "print(1)",
          "```",
          "```output",
          "1",
          "```",
          "| A | B |",
          "| --- | --- |",
          "| x | y |",
          ":::exercise Q1",
          "Question?",
          ":::answer",
          "Secret answer",
          ":::",
          "[docs](https://docs.python.org)",
        ].join("\n")}
      />,
    );
    expect(screen.getByRole("heading", { name: "Intro" }).id).toBe("intro");
    expect(screen.getByLabelText("Watch out")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Copy code" })).toBeInTheDocument();
    expect(screen.getByText("Output")).toBeInTheDocument();
    expect(screen.getByRole("table")).toBeInTheDocument();
    expect(screen.queryByText("Secret answer")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Show answer" }));
    expect(screen.getByText("Secret answer")).toBeInTheDocument();
    const link = screen.getByRole("link", { name: "docs" });
    expect(link).toHaveAttribute("rel", "noopener noreferrer");
  });
});

const step = (over: Partial<PlayerStep>): PlayerStep => ({
  step_key: "k",
  parent_key: null,
  number: "1",
  depth: 0,
  step_type: "video",
  title: "Step",
  description_md: null,
  est_hours: 1,
  credits: 5,
  url: null,
  embeddable: false,
  lesson_id: null,
  assignment_id: null,
  test_id: null,
  article_id: null,
  state: "available",
  credits_awarded: 0,
  due_date: null,
  opened_at: null,
  completed_at: null,
  min_dwell_seconds: 30,
  ...over,
});

describe("StepRail", () => {
  const steps = [
    step({ step_key: "a", number: "1", title: "Install", state: "completed" }),
    step({ step_key: "b", number: "2", title: "Read docs", step_type: "reading", state: "in_progress" }),
    step({ step_key: "c", number: "3", title: "Project", step_type: "assignment", state: "locked", credits: 25 }),
  ];

  it("shows step states, credits and the lock, and reports selection", () => {
    const onSelect = vi.fn();
    render(<StepRail steps={steps} selected="b" onSelect={onSelect} />);
    const buttons = screen.getAllByRole("button");
    expect(buttons.map((b) => b.getAttribute("data-state"))).toEqual(["completed", "in_progress", "locked"]);
    expect(buttons[1]).toHaveAttribute("aria-current", "step");
    expect(screen.getByRole("img", { name: "Locked" })).toBeInTheDocument();
    expect(screen.getByText(/25 credits/)).toBeInTheDocument();
    fireEvent.click(buttons[2]!);
    expect(onSelect).toHaveBeenCalledWith(steps[2]);
  });

  it("opens on the step in progress", () => {
    expect(firstActionable(steps)?.step_key).toBe("b");
  });
});

describe("D9 step embeds", () => {
  const yt = "https://www.youtube-nocookie.com/embed/dQw4w9WgXcQ";
  it("frames only when the server says embeddable and the client allow-list agrees", () => {
    expect(stepEmbedUrl(step({ url: yt, embeddable: true }))).toBe(yt);
    expect(stepEmbedUrl(step({ url: yt, embeddable: false }))).toBeNull();
    expect(stepEmbedUrl(step({ url: "https://example.com/x", embeddable: true }))).toBeNull();
    expect(stepEmbedUrl(step({ url: yt, embeddable: true, step_type: "assignment" }))).toBeNull();
  });
});

describe("path editor model", () => {
  it("round-trips steps, derives super-step totals and reorders", () => {
    const base = { description_md: null, url: "https://x.dev", lesson_id: null, assignment_id: null, test_id: null, article_id: null };
    const ed = toEditor([
      { ...base, step_key: "s1", step_type: "reading", title: "R", est_hours: 1.5, credits: 10, children: [] },
      {
        ...base,
        step_key: "g",
        step_type: "super_step",
        title: "G",
        est_hours: 0,
        credits: 0,
        children: [{ ...base, step_key: "c1", step_type: "video", title: "V", est_hours: 2, credits: 5, children: [] }],
      },
    ]);
    expect(totals(ed)).toEqual({ hours: 3.5, credits: 15, count: 2 });
    const out = toStepIn(move(ed, 1, 0));
    expect(out[0]!.step_key).toBe("g");
    expect(out[0]!.children[0]!.step_key).toBe("c1");
    expect(out[1]!.children).toEqual([]);
    expect("_k" in out[0]!).toBe(false);
  });

  it("never sends the server-computed embeddable flag back (StepIn forbids extra fields)", () => {
    const out = toStepIn(
      toEditor([
        { description_md: null, url: "https://x.dev", embeddable: true, lesson_id: null, assignment_id: null, test_id: null, article_id: null, step_key: "s1", step_type: "video", title: "V", est_hours: 1, credits: 1, children: [] },
      ]),
    );
    expect("embeddable" in out[0]!).toBe(false);
  });
});
