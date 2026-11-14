import { describe, expect, it } from "vitest";
import { safeHttpsUrl, videoEmbedUrl } from "./embed";
import { parseArticle, parseInline, safeHref, slugify, tocOf } from "./markdown";
import { estimateFinish, formatPlanDate, perDayFromPace, planSummary, weeklyHours } from "./pace";

describe("pace helpers", () => {
  it("builds per-day hours for each mode", () => {
    expect(weeklyHours(perDayFromPace({ mode: "every_day", hours_per_day: 2 }))).toBe(14);
    const wd = perDayFromPace({ mode: "weekdays", hours_per_day: 2 });
    expect(wd.sat).toBe(0);
    expect(wd.mon).toBe(2);
    expect(weeklyHours(wd)).toBe(10);
    expect(weeklyHours(perDayFromPace({ mode: "weekends", hours_per_day: 3 }))).toBe(6);
    expect(weeklyHours(perDayFromPace({ mode: "weekdays_weekends", hours_per_day: 1, weekend_hours: 4 }))).toBe(13);
    const custom = perDayFromPace({ mode: "custom", per_day: { mon: 1, tue: 0, wed: 2, thu: 0, fri: 0, sat: 99, sun: -1 } });
    expect(custom.sat).toBe(24);
    expect(custom.sun).toBe(0);
  });

  it("estimates the finish date (20h at 2h/day = 10 days)", () => {
    expect(estimateFinish("2026-11-05", 20, perDayFromPace({ mode: "every_day", hours_per_day: 2 }))).toEqual({ finishDate: "2026-11-14", days: 10 });
    // 2026-11-07 is a Saturday: weekdays-only needs Mon + Tue for 4h
    expect(estimateFinish("2026-11-07", 4, perDayFromPace({ mode: "weekdays", hours_per_day: 2 }))).toEqual({ finishDate: "2026-11-10", days: 4 });
    expect(estimateFinish("2026-11-07", 4, perDayFromPace({ mode: "custom", per_day: { mon: 0, tue: 0, wed: 0, thu: 0, fri: 0, sat: 0, sun: 0 } }))).toBeNull();
    expect(estimateFinish("not-a-date", 4, perDayFromPace({ mode: "every_day", hours_per_day: 1 }))).toBeNull();
  });

  it("formats the plan summary", () => {
    expect(formatPlanDate("2026-11-14")).toBe("14 Nov 2026");
    expect(planSummary(14, 20, "2026-11-14", 10)).toBe("14h/week · path is 20h · finishes in ≈ 10 days (14 Nov 2026)");
    expect(planSummary(0, 20, null, null)).toContain("add study hours");
  });
});

describe("embed helpers", () => {
  it("builds privacy-friendly embeds and rejects non-https", () => {
    expect(videoEmbedUrl("https://www.youtube.com/watch?v=dQw4w9WgXcQ")).toBe("https://www.youtube-nocookie.com/embed/dQw4w9WgXcQ");
    expect(videoEmbedUrl("https://youtu.be/dQw4w9WgXcQ?t=3")).toBe("https://www.youtube-nocookie.com/embed/dQw4w9WgXcQ");
    expect(videoEmbedUrl("https://vimeo.com/123456789")).toBe("https://player.vimeo.com/video/123456789");
    expect(videoEmbedUrl("http://www.youtube.com/watch?v=dQw4w9WgXcQ")).toBeNull();
    expect(videoEmbedUrl("https://example.com/video.mp4")).toBeNull();
    expect(safeHttpsUrl("javascript:alert(1)")).toBeNull();
  });
});

describe("article markdown", () => {
  const src = [
    "# Title",
    "## Variables Are References",
    "Some **bold** and `code`.",
    "",
    "```python",
    "x = 1",
    "print(x)",
    "```",
    "```output",
    "1",
    "```",
    "",
    ":::key-idea",
    "Names point to objects.",
    ":::",
    "",
    ":::exercise Try it",
    "What prints?",
    ":::answer",
    "It prints 1.",
    ":::",
    "",
    "| A | B |",
    "| :-- | --: |",
    "| 1 | 2 |",
    "",
    "## Variables Are References",
    "- one",
    "- two",
  ].join("\n");

  it("parses every block type", () => {
    const blocks = parseArticle(src);
    expect(blocks.map((b) => b.type)).toEqual(["heading", "heading", "paragraph", "code", "callout", "exercise", "table", "heading", "list"]);
    const code = blocks[3]!;
    expect(code.type === "code" && code.output).toBe("1");
    const ex = blocks[5]!;
    expect(ex.type === "exercise" && ex.title).toBe("Try it");
    expect(ex.type === "exercise" && ex.answer.length).toBe(1);
    const table = blocks[6]!;
    expect(table.type === "table" && table.align).toEqual(["left", "right"]);
  });

  it("builds a de-duplicated TOC of ## / ### headings", () => {
    expect(tocOf(parseArticle(src))).toEqual([
      { id: "variables-are-references", text: "Variables Are References", level: 2 },
      { id: "variables-are-references-2", text: "Variables Are References", level: 2 },
    ]);
    expect(slugify("  What's Next?  ")).toBe("what-s-next");
  });

  it("unknown callouts fall back to note", () => {
    const [b] = parseArticle(":::danger\nx\n:::");
    expect(b?.type === "callout" && b.kind).toBe("note");
  });

  it("keeps unsafe links as text", () => {
    expect(safeHref("javascript:alert(1)")).toBeNull();
    expect(safeHref("//evil.example")).toBeNull();
    expect(safeHref("/app/path")).toBe("/app/path");
    expect(parseInline("[x](javascript:alert(1))").every((t) => t.t === "text")).toBe(true);
  });
});
