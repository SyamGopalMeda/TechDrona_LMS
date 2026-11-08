import { isAnswered, type AnswerState } from "./resume";

/** Question-palette states (design-system §3.4, FR-ASM-014). */
export type PaletteState = "not_visited" | "not_answered" | "answered" | "marked" | "answered_marked";

export const PALETTE_LABEL: Record<PaletteState, string> = {
  not_visited: "Not visited",
  not_answered: "Not answered",
  answered: "Answered",
  marked: "Marked for review",
  answered_marked: "Answered and marked for review",
};

export function paletteState(answer: AnswerState | undefined, visited: boolean): PaletteState {
  const answered = isAnswered(answer?.response);
  const flagged = !!answer?.flagged;
  if (answered && flagged) return "answered_marked";
  if (flagged) return "marked";
  if (answered) return "answered";
  return visited ? "not_answered" : "not_visited";
}

export type PaletteCounts = Record<PaletteState, number>;

export function paletteCounts(ids: string[], answers: Map<string, AnswerState>, visited: Set<string>): PaletteCounts {
  const counts: PaletteCounts = { not_visited: 0, not_answered: 0, answered: 0, marked: 0, answered_marked: 0 };
  for (const id of ids) counts[paletteState(answers.get(id), visited.has(id))] += 1;
  return counts;
}

/** Accessible name, e.g. "Question 12, answered, marked for review". */
export function paletteAriaLabel(n: number, state: PaletteState, current: boolean): string {
  const s =
    state === "answered_marked" ? "answered, marked for review" : state === "marked" ? "marked for review" : PALETTE_LABEL[state].toLowerCase();
  return `Question ${n}, ${s}${current ? ", current" : ""}`;
}
