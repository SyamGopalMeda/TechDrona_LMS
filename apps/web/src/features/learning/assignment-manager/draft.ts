import type { InlineItemType, ItemOption, RubricCriterion, SectionStaff, StructureIn, StructureItemIn } from "./types";
import type { PickedQuestion } from "./bank-picker";

/** Editable copy of one section item (marks kept as the input's text). */
export interface DraftItem {
  key: string;
  id?: string;
  source: "bank" | "inline";
  item_type: string;
  question_id: string | null;
  question_version_id: string | null;
  coding_problem_id: string | null;
  prompt_md: string | null;
  stem_html: string | null;
  options: ItemOption[];
  marks: string;
  rubric: { criteria: RubricCriterion[] } | null;
  reference_answer_md: string | null;
}

export interface DraftSection {
  key: string;
  id?: string;
  title: string;
  max_score: number | null;
  items: DraftItem[];
}

let seq = 0;
export const newKey = (p = "k") => `${p}-${Date.now().toString(36)}-${(seq++).toString(36)}`;

export function toDraft(sections: SectionStaff[]): DraftSection[] {
  return [...sections]
    .sort((a, b) => a.position - b.position)
    .map((s) => ({
      key: s.id,
      id: s.id,
      title: s.title,
      max_score: s.max_score,
      items: [...s.items]
        .sort((a, b) => a.position - b.position)
        .map((i) => ({
          key: i.id,
          id: i.id,
          source: i.source,
          item_type: i.item_type,
          question_id: i.question_id,
          question_version_id: i.question_version_id,
          coding_problem_id: i.coding_problem_id,
          prompt_md: i.prompt_md,
          stem_html: i.stem_html,
          options: i.options ?? [],
          marks: String(i.marks ?? 0),
          rubric: i.rubric,
          reference_answer_md: i.reference_answer_md,
        })),
    }));
}

export function emptySection(n: number): DraftSection {
  return { key: newKey("s"), title: `Section ${n}`, max_score: null, items: [] };
}

export function duplicateSection(s: DraftSection): DraftSection {
  return {
    key: newKey("s"),
    title: `${s.title} (copy)`,
    max_score: s.max_score,
    items: s.items.map((i) => ({ ...i, key: newKey("i"), id: undefined })),
  };
}

export function fromPicked(q: PickedQuestion): DraftItem {
  return {
    key: newKey("i"),
    source: "bank",
    item_type: q.question_type,
    question_id: q.question_id,
    question_version_id: q.question_version_id ?? null,
    coding_problem_id: null,
    prompt_md: null,
    stem_html: q.stem_html,
    options: [],
    marks: String(q.default_marks ?? 0),
    rubric: null,
    reference_answer_md: null,
  };
}

export function inlineItem(item_type: InlineItemType, prompt: string, marks: number): DraftItem {
  return {
    key: newKey("i"),
    source: "inline",
    item_type,
    question_id: null,
    question_version_id: null,
    coding_problem_id: null,
    prompt_md: prompt,
    stem_html: null,
    options: [],
    marks: String(marks),
    rubric: null,
    reference_answer_md: null,
  };
}

export function itemMarks(i: DraftItem): number {
  const n = Number(i.marks);
  return Number.isFinite(n) && n > 0 ? n : 0;
}

export function sectionMarks(s: DraftSection): number {
  return s.items.reduce((t, i) => t + itemMarks(i), 0);
}

export function allocatedMarks(sections: DraftSection[]): number {
  return Math.round(sections.reduce((t, s) => t + sectionMarks(s), 0) * 100) / 100;
}

/** Items with zero / empty marks (shown in the mismatch warning). */
export function zeroMarkItems(sections: DraftSection[]): number {
  return sections.reduce((t, s) => t + s.items.filter((i) => itemMarks(i) === 0).length, 0);
}

export function toStructureIn(sections: DraftSection[]): StructureIn {
  return {
    sections: sections.map((s) => ({
      title: s.title.trim() || "Untitled section",
      max_score: s.max_score,
      items: s.items.map((i): StructureItemIn => {
        const marks = itemMarks(i);
        if (i.source === "bank" && i.question_id) {
          return { source: "bank", question_id: i.question_id, question_version_id: i.question_version_id, marks };
        }
        return {
          source: "inline",
          item_type: i.item_type as InlineItemType,
          prompt_md: i.prompt_md ?? "",
          marks,
          ...(i.coding_problem_id ? { coding_problem_id: i.coding_problem_id } : {}),
          ...(i.rubric ? { rubric: i.rubric } : {}),
          ...(i.reference_answer_md ? { reference_answer_md: i.reference_answer_md } : {}),
        };
      }),
    })),
  };
}
