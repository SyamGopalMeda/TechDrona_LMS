/**
 * Exam vocabulary shared by the Exams screen and the college page (port of the exports of js/views/exams.js).
 * Display words only: the stored research values never change (owner-reviewed wording, docs/qa/college-portal/colleges-branches.md).
 */
import type { Tone } from "../../ui";

/** Stored `status` values, in the order of the edit form's select. */
export const EXAM_STATUSES = ["Upcoming", "In Progress", "Completed", "No Current Exams Found", "Unverified"] as const;
/** Stored `evidence` values. */
export const EXAM_EVIDENCE = ["Officially confirmed", "Official university timetable (affiliation-based)", "Unverified (calendar-planned)", "Conflicting", "Unverified"] as const;
export const EXAM_CONFIDENCE = ["High", "Medium", "Low"] as const;

/** Display words for the stored status values. */
export const EXAM_STATUS_LABEL: Record<string, string> = {
  Upcoming: "Upcoming",
  "In Progress": "In progress",
  Completed: "Finished",
  "No Current Exams Found": "No exams announced",
  Unverified: "Not confirmed",
};

export const EXAM_STATUS_TONE: Record<string, Tone> = {
  "In Progress": "bad",
  Upcoming: "warn",
  Completed: "good",
  "No Current Exams Found": "neutral",
  Unverified: "neutral",
};

export const EVIDENCE_LABEL: Record<string, string> = {
  "Officially confirmed": "Official notice",
  "Official university timetable (affiliation-based)": "University timetable",
  "Unverified (calendar-planned)": "Academic calendar (planned)",
  Conflicting: "Sources disagree",
  Unverified: "Not confirmed",
};

export const CONF_TONE: Record<string, Tone> = { High: "good", Medium: "info", Low: "warn" };

/**
 * Plain label of a stored evidence value ("Officially confirmed" → "Official notice"). With `confidence` the college
 * page's merged badge text: "Official notice · high confidence".
 */
export function evidenceLabel(evidence: string | null | undefined, confidence?: string | null): string {
  const base = evidence ? (EVIDENCE_LABEL[evidence] ?? evidence) : "";
  return confidence ? `${base}${base ? " · " : ""}${String(confidence).toLowerCase()} confidence` : base;
}

/** Every http(s) URL in a free-text source field (some rows hold two: "https://a … ; https://b"). */
export function sourceUrls(text: string | null | undefined): string[] {
  const found = String(text ?? "").match(/https?:\/\/[^\s;,|<>"']+/gi) ?? [];
  const out: string[] = [];
  for (const raw of found) {
    const u = raw.replace(/[.)\]]+$/, "");
    if (!out.includes(u)) out.push(u);
  }
  return out;
}

function hostOf(u: string): string {
  try {
    return new URL(u).hostname.replace(/^www\./, "");
  } catch {
    return u;
  }
}

/**
 * Source field → links: each URL gets its own link (the multi-URL fix: two URLs used to make one broken link).
 * No value → "no source"; text without a URL → "source noted" (full text on hover).
 */
export function SourceLinks({ text }: { text: string | null | undefined }) {
  if (!text || !String(text).trim()) return <span className="ex-nosrc">no source</span>;
  const urls = sourceUrls(text);
  if (!urls.length)
    return (
      <span className="adm-muted td-muted" title={String(text)}>
        source noted
      </span>
    );
  return (
    <span className="ex-links">
      {urls.map((u, i) => (
        <a key={u} href={u} target="_blank" rel="noopener noreferrer" title={u}>
          {urls.length > 1 ? `${hostOf(u)} (${i + 1})` : hostOf(u)}
        </a>
      ))}
    </span>
  );
}
