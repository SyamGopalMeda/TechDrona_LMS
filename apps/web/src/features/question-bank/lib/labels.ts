import type { ImportKind, QuestionType } from "./types";

/** UI groups for question types: MCQ covers single and multi answer. */
export type TypeGroup = "mcq" | "coding" | "essay" | "poll" | "survey" | "word_cloud" | "numeric" | "fill_blank";

export const GROUPS: { key: TypeGroup; label: string; types: QuestionType[]; icon: string }[] = [
  { key: "mcq", label: "MCQ", types: ["mcq_single", "mcq_multi"], icon: "☑" },
  { key: "coding", label: "Code", types: ["coding"], icon: "</>" },
  { key: "essay", label: "Essay", types: ["essay"], icon: "✎" },
  { key: "poll", label: "Poll", types: ["poll"], icon: "▤" },
  { key: "survey", label: "Survey", types: ["survey"], icon: "☷" },
  { key: "word_cloud", label: "Words", types: ["word_cloud"], icon: "☁" },
  { key: "numeric", label: "Numeric", types: ["numeric"], icon: "#" },
  { key: "fill_blank", label: "Fill in the blank", types: ["fill_blank"], icon: "_" },
];

/** UI group of a server question_type (unknown types fall back to their own name). */
export function groupOf(type: string): TypeGroup | null {
  return GROUPS.find((g) => (g.types as string[]).includes(type))?.key ?? null;
}

export function typeLabel(type: string): string {
  const g = GROUPS.find((x) => (x.types as string[]).includes(type) || x.key === type);
  return g?.label ?? type.replace(/_/g, " ");
}

export function typeIcon(type: string): string {
  return GROUPS.find((x) => (x.types as string[]).includes(type) || x.key === type)?.icon ?? "?";
}

/** Type counts per UI group (mcq_single + mcq_multi → MCQ), in display order, zero counts dropped. */
export function groupCounts(typeCounts: Record<string, number> | undefined): { key: TypeGroup | string; label: string; count: number }[] {
  const out: { key: TypeGroup | string; label: string; count: number }[] = [];
  const seen = new Set<string>();
  for (const g of GROUPS) {
    const count = g.types.reduce((n, t) => n + (typeCounts?.[t] ?? 0), 0);
    g.types.forEach((t) => seen.add(t));
    if (count > 0) out.push({ key: g.key, label: g.label, count });
  }
  for (const [t, n] of Object.entries(typeCounts ?? {})) if (!seen.has(t) && n > 0) out.push({ key: t, label: typeLabel(t), count: n });
  return out;
}

/** The group with the most questions (ties → display order), or null for an empty bank. */
export function dominantGroup(typeCounts: Record<string, number> | undefined): { key: string; label: string } | null {
  const counts = groupCounts(typeCounts);
  if (!counts.length) return null;
  return counts.reduce((best, c) => (c.count > best.count ? c : best));
}

/** The import / AI type tiles. */
export const KINDS: { value: ImportKind; label: string; icon: string; hint: string }[] = [
  { value: "code", label: "Code", icon: "</>", hint: "Programming problem" },
  { value: "mcq", label: "MCQ", icon: "☑", hint: "One or many correct" },
  { value: "essay", label: "Essay", icon: "✎", hint: "Written answer" },
  { value: "poll", label: "Poll", icon: "▤", hint: "Opinion, no answer" },
  { value: "survey", label: "Survey", icon: "☷", hint: "Scale or open" },
  { value: "word_cloud", label: "Words", icon: "☁", hint: "Word cloud" },
];

/** Types that are scored (an explanation is required before review). */
export const GRADED_TYPES = ["mcq_single", "mcq_multi", "coding", "essay", "numeric", "fill_blank"];

/** Plain-text preview of sanitised question HTML. */
export function plainText(html: string | null | undefined): string {
  return (html ?? "")
    .replace(/<[^>]*>/g, " ")
    .replace(/&nbsp;/g, " ")
    .replace(/&amp;/g, "&")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .replace(/\s+/g, " ")
    .trim();
}

/** Default Likert labels for 3..7 points. */
export function likertLabels(points: number): string[] {
  switch (points) {
    case 3:
      return ["Disagree", "Neutral", "Agree"];
    case 4:
      return ["Strongly disagree", "Disagree", "Agree", "Strongly agree"];
    case 6:
      return ["Strongly disagree", "Disagree", "Somewhat disagree", "Somewhat agree", "Agree", "Strongly agree"];
    case 7:
      return ["Strongly disagree", "Disagree", "Somewhat disagree", "Neutral", "Somewhat agree", "Agree", "Strongly agree"];
    default:
      return ["Strongly disagree", "Disagree", "Neutral", "Agree", "Strongly agree"];
  }
}

/** Copy text to the clipboard; false when the browser refuses (no permission / insecure context). */
export async function copyText(text: string): Promise<boolean> {
  try {
    if (!navigator.clipboard?.writeText) return false;
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    return false;
  }
}

export function shortDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" });
}
