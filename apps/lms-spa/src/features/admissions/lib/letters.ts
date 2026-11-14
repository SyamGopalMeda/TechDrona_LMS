/**
 * Admission / offer letter step after enrolment. Backend: GET /admin/admissions/registrations/{id}/letter,
 * POST /admin/admissions/letters/drafts, GET|PUT /admin/admissions/letter-settings (admissions/letters.py);
 * the letter itself is previewed / issued / corrected through /admin/documents (learning/doc_admin.py).
 */

import type { IssuedDoc, Recipient } from "@/features/certificates/lib/docs";
import { formatDate } from "@/lib/format";

export type LetterType = "offer_course" | "offer_internship";
export const LETTER_TYPES: { value: LetterType; label: string }[] = [
  { value: "offer_course", label: "Course admission letter" },
  { value: "offer_internship", label: "Internship offer letter" },
];

/** letters.summary: the letter in force, on the registrations list and page. */
export interface LetterSummary {
  id: string;
  doc_type: string;
  short: string;
  ref_no: string;
  issue_date: string;
  status: "valid" | "revoked" | "superseded";
  origin: string;
}

/** The prefilled letter (letters.draft): what POST /admin/documents needs. */
export interface LetterDraft {
  doc_type: LetterType;
  recipient: Required<Recipient>;
  fields: Record<string, string>;
  issue_date: string;
  user_id: string | null;
  enrolment_id: string | null;
  batch_id: string | null;
  course_id: string | null;
}

export interface IssuedLetter extends IssuedDoc {
  batch_id?: string | null;
  /** Absolute public verification page (shared on WhatsApp). */
  verify_link: string;
}

/** GET /admin/admissions/registrations/{id}/letter (one item of POST /admin/admissions/letters/drafts). */
export interface LetterStep {
  registration_id: string;
  reg_no: string;
  name: string;
  phone: string;
  course_title: string;
  enrolled_at: string | null;
  ready: boolean;
  reason: string | null;
  draft: LetterDraft | null;
  letter: IssuedLetter | null;
  letters: IssuedLetter[];
  email: { connected: boolean; auto_send: boolean };
  settings_problem: string | null;
  auto_open: boolean;
}

export type LetterEmailMode = "send" | "queue" | "none";

/** Email per the documents settings: none without email, else sent now (auto-send) or queued for approval. */
export function letterEmailMode(email: LetterStep["email"]): LetterEmailMode {
  if (!email.connected) return "none";
  return email.auto_send ? "send" : "queue";
}

export function issueLabel(mode: LetterEmailMode): string {
  return mode === "send" ? "Issue & send" : mode === "queue" ? "Issue & queue email" : "Issue letter";
}

/** "Letter issued: TD-AL-2026-AB12CD (14 Nov 2026)". */
export function letterLine(l: Pick<LetterSummary, "ref_no" | "issue_date">): string {
  return `Letter issued: ${l.ref_no} (${formatDate(l.issue_date)})`;
}

/** The short WhatsApp message with the verification link. */
export function letterMessage(who: { name: string; course_title: string }, l: Pick<IssuedLetter, "ref_no" | "short" | "verify_link">): string {
  const what = (l.short || "admission letter").toLowerCase();
  return [
    `Hi ${who.name}, welcome to ${who.course_title} at Tech Drona!`,
    "",
    `Your ${what} is ready. Reference: ${l.ref_no}`,
    `View and verify it here: ${l.verify_link}`,
  ].join("\n");
}

/** Carry the details over when the admin switches between the course and the internship letter. */
const SAME: [string, string][] = [
  ["program", "role"],
  ["batch_start", "start_date"],
];
export function switchLetterFields(fields: Record<string, string>, to: LetterType): Record<string, string> {
  const out = { ...fields };
  for (const [course, intern] of SAME) {
    const [from, into] = to === "offer_internship" ? [course, intern] : [intern, course];
    if (out[from] && !out[into]) out[into] = out[from]!;
  }
  if (to === "offer_internship" && !out.intern_stipend) out.intern_stipend = "Unpaid";
  return out;
}

/** POST /admin/documents body for a registration's letter. */
export function issueBody(input: { doc_type: LetterType; recipient: Recipient; fields: Record<string, string>; issue_date: string; draft: LetterDraft; email: LetterEmailMode }) {
  const { recipient: r, draft } = input;
  return {
    doc_type: input.doc_type,
    recipient: { name: r.name.trim(), email: r.email.trim(), college: r.college?.trim() || undefined, reg_no: r.reg_no?.trim() || undefined },
    fields: cleanFields(input.fields),
    issue_date: input.issue_date || undefined,
    user_id: draft.user_id ?? undefined,
    enrolment_id: draft.enrolment_id ?? undefined,
    batch_id: draft.batch_id ?? undefined,
    course_id: draft.course_id ?? undefined,
    email: input.email,
  };
}

export function cleanFields(fields: Record<string, string>): Record<string, string> {
  return Object.fromEntries(Object.entries(fields).filter(([, v]) => v.trim()));
}

/**
 * Runs `fn` over `items`, `size` at a time, reporting progress after each one. A failure is
 * recorded for that item and the rest continue.
 */
export async function runInChunks<T, R>(items: T[], size: number, fn: (item: T) => Promise<R>, onProgress?: (done: number, total: number) => void): Promise<({ ok: true; value: R } | { ok: false; error: unknown })[]> {
  const out: ({ ok: true; value: R } | { ok: false; error: unknown })[] = [];
  let done = 0;
  for (let i = 0; i < items.length; i += size) {
    const part = await Promise.all(
      items.slice(i, i + size).map(async (item) => {
        try {
          return { ok: true as const, value: await fn(item) };
        } catch (error) {
          return { ok: false as const, error };
        } finally {
          done += 1;
          onProgress?.(done, items.length);
        }
      }),
    );
    out.push(...part);
  }
  return out;
}

/* ------------------------------------------------------------------ bulk (POST /admin/documents/bulk/issue) */

/** One row of the documents bulk issue (doc_admin.BulkRowIn). */
export interface BulkLetterRow {
  row: number;
  name: string;
  email: string;
  college?: string;
  reg_no?: string;
  fields: Record<string, string>;
  user_id?: string;
  enrolment_id?: string;
  batch_id?: string;
  course_id?: string;
}

/** doc_bulk.issue_rows answer (only what the letter step reads). */
export interface BulkLetterResult {
  results: { row: number; status: "issued" | "failed" | "deferred"; ref_no?: string; error?: string }[];
}

export type LetterOutcome = { ref_no: string } | { error: string };

export function bulkRow(row: number, d: LetterDraft): BulkLetterRow {
  const r = d.recipient;
  return {
    row,
    name: r.name,
    email: r.email,
    college: r.college || undefined,
    reg_no: r.reg_no || undefined,
    fields: cleanFields(d.fields),
    user_id: d.user_id ?? undefined,
    enrolment_id: d.enrolment_id ?? undefined,
    batch_id: d.batch_id ?? undefined,
    course_id: d.course_id ?? undefined,
  };
}

/**
 * Issue the drafts through the documents bulk endpoint: one call per letter type and chunk of
 * `size`; rows the server defers (time budget) are sent again, at most `maxRounds` times.
 * `send(docType, rows)` posts one chunk (with its own idempotency key). Keys of the result: the
 * index of each draft in `drafts`; `into` collects them as they come (kept when a chunk fails).
 */
export async function issueLettersInBulk(
  drafts: LetterDraft[],
  send: (docType: LetterType, rows: BulkLetterRow[]) => Promise<BulkLetterResult>,
  onProgress?: (done: number, total: number) => void,
  { size = 25, maxRounds = 5, into }: { size?: number; maxRounds?: number; into?: Map<number, LetterOutcome> } = {},
): Promise<Map<number, LetterOutcome>> {
  const out = into ?? new Map<number, LetterOutcome>();
  const report = () => onProgress?.(out.size, drafts.length);
  for (const type of [...new Set(drafts.map((d) => d.doc_type))]) {
    let queue = drafts.map((d, i) => ({ d, i })).filter((x) => x.d.doc_type === type);
    for (let round = 0; queue.length && round < maxRounds; round++) {
      const again: typeof queue = [];
      for (let i = 0; i < queue.length; i += size) {
        const chunk = queue.slice(i, i + size);
        const res = await send(type, chunk.map((x) => bulkRow(x.i + 1, x.d)));
        for (const x of chunk) {
          const r = res.results.find((y) => y.row === x.i + 1);
          if (!r || r.status === "deferred") again.push(x);
          else out.set(x.i, r.status === "issued" ? { ref_no: r.ref_no ?? "" } : { error: r.error || "Couldn't issue this letter" });
        }
        report();
      }
      queue = again;
    }
    for (const x of queue) out.set(x.i, { error: "Not reached in time: issue it again." });
    report();
  }
  return out;
}

/** A PDF (base64 from the preview) in a new tab: the tab is opened inside the click, then pointed at the file. */
export function pdfTab(): Window | null {
  return typeof window.open === "function" ? window.open("", "_blank") : null;
}

export function showPdf(tab: Window | null, url: string): void {
  if (tab) {
    tab.opener = null;
    tab.location.href = url;
  } else {
    window.open(url, "_blank", "noopener,noreferrer");
  }
}
