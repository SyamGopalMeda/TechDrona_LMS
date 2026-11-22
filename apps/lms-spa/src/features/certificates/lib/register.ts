/**
 * Offer letter register: every candidate added on the Offer letters page (Excel upload or the
 * form) and where their letter stands. Kept in this browser (localStorage), no server, no AI:
 *
 *   Not generated --Generate--> To send --Mark as sent--> Sent (--Undo--> To send)
 *
 * Generating assigns the next reference number (blank Ref No cells) and freezes the letter's
 * details, so opening it later always gives the same letter. PDFs are drawn on demand from that
 * snapshot (nothing large is stored). The register downloads as an Excel file with the same
 * columns as the upload template plus Status / Sent on; uploading that file restores it, which is
 * also the backup for a new browser or laptop.
 */

import type { XLSX } from "./bulk";
import {
  LETTER_KINDS,
  STATUS_HEADERS,
  TEMPLATE_HEADERS,
  buildOffer,
  emailDraft,
  longDate,
  nextRef,
  offerErrors,
  offerFileName,
  type LetterKind,
  type OfferInput,
  type OfferLetter,
  type OfferSettings,
  type SheetEntry,
} from "./offer";

export type LetterStatus = "new" | "generated" | "sent";

export interface OfferRecord {
  id: string;
  input: OfferInput;
  status: LetterStatus;
  /** Frozen at generation (signature left out: the current settings' signature is used). */
  letter?: OfferLetter;
  addedOn: string;
  generatedOn?: string;
  sentOn?: string;
}

export const STATUS_LABEL: Record<LetterStatus, string> = { new: "Not generated", generated: "To send", sent: "Sent" };

let seq = 0;
export function newId(): string {
  seq += 1;
  return `${Date.now().toString(36)}-${seq.toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
}

const norm = (s: string) => s.trim().toLowerCase().replace(/\s+/g, " ");

/** Status column of an uploaded register -> status ("" / unknown = new). */
export function parseStatus(v: string): LetterStatus {
  const t = norm(v);
  if (t.startsWith("sent")) return "sent";
  if (t === "to send" || t === "generated" || t === "ready") return "generated";
  return "new";
}

export interface AddResult {
  records: OfferRecord[];
  added: number;
  updated: number;
}

/**
 * Upload rows -> register. A row matches an existing candidate by Ref No (when the sheet has one)
 * or by name + email; a match is updated (unless its letter was already generated or sent and the
 * row does not carry a status), otherwise the row is added. Rows that say "To send" / "Sent"
 * (a downloaded register) come back with that status and their letter frozen.
 */
export function addEntries(records: OfferRecord[], entries: SheetEntry[], s: OfferSettings, today: string): AddResult {
  const out = records.slice();
  let added = 0;
  let updated = 0;
  for (const e of entries) {
    const status = parseStatus(e.status);
    // same number AND same person; a different person with a taken number is added and fails on Generate
    const byRef = e.refGiven ? out.findIndex((r) => (r.letter?.ref ?? r.input.ref) === e.input.ref && norm(r.input.name) === norm(e.input.name)) : -1;
    const idx = byRef >= 0 ? byRef : out.findIndex((r) => norm(r.input.name) === norm(e.input.name) && norm(r.input.email) === norm(e.input.email));
    const restored = (base: Partial<OfferRecord>): OfferRecord => {
      const rec: OfferRecord = { id: newId(), addedOn: today, ...base, input: e.input, status: "new", letter: undefined, generatedOn: undefined, sentOn: undefined };
      if (status !== "new" && e.input.ref && !offerErrors(e.input).length) {
        rec.status = status;
        rec.letter = freeze(buildOffer(e.input, s));
        rec.generatedOn = e.input.letterDate;
        if (status === "sent") rec.sentOn = e.sentOn || today;
      }
      return rec;
    };
    if (idx < 0) {
      out.push(restored({}));
      added += 1;
      continue;
    }
    const cur = out[idx]!;
    if (cur.status !== "new" && status === "new") continue; // an issued letter is not overwritten by a plain row
    out[idx] = restored({ id: cur.id, addedOn: cur.addedOn });
    updated += 1;
  }
  return { records: out, added, updated };
}

function freeze(l: OfferLetter): OfferLetter {
  return { ...l, signature: "" };
}

function usedRefs(records: OfferRecord[]): Set<string> {
  const s = new Set<string>();
  for (const r of records) {
    const ref = r.letter?.ref ?? r.input.ref;
    if (ref) s.add(ref);
  }
  return s;
}

export interface GenerateResult {
  records: OfferRecord[];
  settings: OfferSettings;
  generated: string[];
  failed: { id: string; name: string; errors: string[] }[];
}

/**
 * Generates the letters of `ids` (records that are not generated yet): blank refs get the next
 * number of their template's series (skipping numbers already in the register), the details are
 * validated and frozen. Returns the updated next numbers in `settings`.
 */
export function generate(records: OfferRecord[], ids: string[], s: OfferSettings, today: string): GenerateResult {
  const want = new Set(ids);
  // refs held by other rows (a pending row's own typed ref does not block itself)
  const used = usedRefs(records.filter((r) => !(want.has(r.id) && r.status === "new")));
  let settings = { ...s };
  const generated: string[] = [];
  const failed: GenerateResult["failed"] = [];
  const out = records.map((r) => {
    if (!want.has(r.id) || r.status !== "new") return r;
    let input = r.input;
    let next = settings;
    if (!input.ref.trim()) {
      const key = input.kind === "employment" ? "empNextRef" : "nextRef";
      let ref = settings[key];
      while (used.has(ref)) ref = nextRef(ref);
      input = { ...input, ref };
      next = { ...settings, [key]: nextRef(ref) };
    }
    const errors = offerErrors(input);
    if (r.input.ref.trim() && used.has(input.ref)) errors.push(`Ref ${input.ref} is already used by another letter`);
    if (errors.length) {
      failed.push({ id: r.id, name: r.input.name, errors });
      return r;
    }
    used.add(input.ref);
    settings = next;
    generated.push(r.id);
    return { ...r, input, status: "generated" as const, letter: freeze(buildOffer(input, settings)), generatedOn: today };
  });
  return { records: out, settings, generated, failed };
}

export function markSent(records: OfferRecord[], ids: string[], today: string): OfferRecord[] {
  const want = new Set(ids);
  return records.map((r) => (want.has(r.id) && r.status === "generated" ? { ...r, status: "sent", sentOn: today } : r));
}

export function undoSent(records: OfferRecord[], ids: string[]): OfferRecord[] {
  const want = new Set(ids);
  return records.map((r) => (want.has(r.id) && r.status === "sent" ? { ...r, status: "generated", sentOn: undefined } : r));
}

/** Back to "Not generated" for editing; the reference number is kept. */
export function reopen(records: OfferRecord[], id: string, input: OfferInput): OfferRecord[] {
  return records.map((r) => (r.id === id ? { ...r, input: { ...input, ref: input.ref || r.letter?.ref || r.input.ref }, status: "new", letter: undefined, generatedOn: undefined, sentOn: undefined } : r));
}

export function removeRecords(records: OfferRecord[], ids: string[]): OfferRecord[] {
  const want = new Set(ids);
  return records.filter((r) => !want.has(r.id));
}

/** Problems to show next to a not-generated row (the ref is assigned on generation, so not required yet). */
export function rowErrors(r: OfferRecord): string[] {
  if (r.status !== "new") return [];
  return offerErrors({ ...r.input, ref: r.input.ref || "pending" });
}

export function counts(records: OfferRecord[]): Record<LetterStatus | "all", number> {
  const c = { all: records.length, new: 0, generated: 0, sent: 0 };
  for (const r of records) c[r.status] += 1;
  return c;
}

/* ------------------------------------------------------------------ persistence (this browser) */

const KEY = "td.offer-letters.register.v1";

export function loadRegister(): OfferRecord[] {
  try {
    const raw = window.localStorage.getItem(KEY);
    const v = raw ? (JSON.parse(raw) as unknown) : [];
    return Array.isArray(v) ? (v as OfferRecord[]) : [];
  } catch {
    return [];
  }
}

export function saveRegister(records: OfferRecord[]): boolean {
  try {
    window.localStorage.setItem(KEY, JSON.stringify(records));
    return true;
  } catch {
    return false;
  }
}

/* ------------------------------------------------------------------ exports */

function kindShort(k: LetterKind | undefined): string {
  return LETTER_KINDS.find((x) => x.value === (k ?? "internship"))!.short;
}

/** Register -> Excel: the upload template's columns + Status / Sent on (uploading it restores the register). */
export function registerWorkbook(x: XLSX, records: OfferRecord[]): Uint8Array {
  const rows = records.map((r) => {
    const i = r.letter ? { ...r.input, ref: r.letter.ref } : r.input;
    const emp = i.kind === "employment";
    return [
      i.name,
      i.email,
      kindShort(i.kind),
      i.letterDate,
      i.ref,
      i.role,
      i.mode,
      emp ? "" : i.months,
      i.start ?? "",
      emp ? "" : (i.end ?? ""),
      emp ? (i.ctc ?? "") : "",
      emp ? (i.probation ?? "") : "",
      emp ? (i.location ?? "") : "",
      STATUS_LABEL[r.status],
      r.sentOn ?? "",
    ];
  });
  const ws = x.utils.aoa_to_sheet([[...TEMPLATE_HEADERS, ...STATUS_HEADERS], ...rows]);
  ws["!cols"] = [34, 30, 12, 12, 18, 40, 10, 10, 14, 12, 16, 10, 24, 14, 12].map((wch) => ({ wch }));
  ws["!autofilter"] = { ref: `A1:O${rows.length + 1}` };
  const wb = x.utils.book_new();
  x.utils.book_append_sheet(wb, ws, "Offer letters register");
  return new Uint8Array(x.write(wb, { type: "array", bookType: "xlsx" }) as ArrayBuffer);
}

const esc = (s: string) => s.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]!);

/** A standalone page with every draft and Copy buttons (works offline, e.g. from the ZIP). */
export function draftsHtml(letters: { letter: OfferLetter; folder: string }[], title = "Offer letter email drafts"): string {
  const cards = letters
    .map(({ letter, folder }, i) => {
      const d = emailDraft(letter);
      const copy = (v: string) => `<button data-c="${esc(v)}">Copy</button>`;
      return `<section class="card"><div class="hd"><span class="n">${i + 1}</span><b>${esc(letter.name)}</b><span class="ref">${esc(letter.ref)}</span></div>
<div class="row"><span class="k">To</span><code>${esc(d.to || "(no email)")}</code>${d.to ? copy(d.to) : "<span></span>"}</div>
<div class="row"><span class="k">Subject</span><code>${esc(d.subject)}</code>${copy(d.subject)}</div>
<div class="row"><span class="k">Attach</span><code>${esc(`${folder}/${d.attachment}`)}</code><span></span></div>
<div class="row top"><span class="k">Body</span><pre>${esc(d.body)}</pre>${copy(d.body)}</div></section>`;
    })
    .join("\n");
  return `<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>${esc(title)}</title>
<style>body{margin:0;background:#f5f6fa;color:#1b2340;font:15px/1.5 system-ui,Segoe UI,sans-serif}main{max-width:900px;margin:0 auto;padding:24px 16px}h1{margin:0 0 4px;font-size:22px}p.s{color:#5b6380;margin:0 0 20px}
.card{background:#fff;border:1px solid #e2e5ee;border-radius:10px;padding:14px 16px;margin-bottom:14px}.hd{display:flex;gap:10px;align-items:center;margin-bottom:8px;flex-wrap:wrap}
.n{background:#1f2a5c;color:#fff;border-radius:50%;width:24px;height:24px;display:inline-grid;place-items:center;font-size:12px}.ref{color:#5b6380;font-size:13px}
.row{display:grid;grid-template-columns:64px 1fr auto;gap:10px;align-items:center;padding:5px 0;border-top:1px solid #e2e5ee}.row.top{align-items:start}.k{color:#5b6380;font-size:13px}
code{font:13px Consolas,monospace;overflow-wrap:anywhere}pre{margin:0;white-space:pre-wrap;font:13px/1.45 system-ui,Segoe UI,sans-serif}
button{border:1px solid #1f2a5c;background:#fff;color:#1f2a5c;border-radius:6px;padding:4px 10px;cursor:pointer;font-size:13px}button.ok{background:#1e7d4f;border-color:#1e7d4f;color:#fff}</style></head>
<body><main><h1>${esc(title)}</h1><p class="s">${letters.length} email${letters.length === 1 ? "" : "s"}. For each: copy To, Subject and Body into a new email, attach the PDF shown, send, then click "Mark as sent" for that person in the LMS.</p>
${cards}</main><script>document.querySelectorAll('button[data-c]').forEach(function(b){b.onclick=function(){var t=b.getAttribute('data-c');var done=function(){b.textContent='Copied';b.className='ok';setTimeout(function(){b.textContent='Copy';b.className=''},1500)};if(navigator.clipboard){navigator.clipboard.writeText(t).then(done,function(){fallback(t);done()})}else{fallback(t);done()}}});function fallback(t){var a=document.createElement('textarea');a.value=t;document.body.appendChild(a);a.select();document.execCommand('copy');a.remove()}</script></body></html>`;
}

export const FOLDER_TO_SEND = "1 To Send";
export const FOLDER_SENT = "2 Sent";

export function folderOf(r: OfferRecord): string {
  return r.status === "sent" ? FOLDER_SENT : FOLDER_TO_SEND;
}

/** Short description of a record's letter for the table ("Internship · 22 Nov 2026 – 21 Mar 2027"). */
export function letterSummary(r: OfferRecord): string {
  const l = r.letter;
  const i = r.input;
  if (l) return l.kind === "employment" ? `Joining ${l.start} · ${l.ctc}` : `${l.start} – ${l.end}`;
  if (!i.letterDate) return "No letter date";
  try {
    return `Letter date ${longDate(i.letterDate)}`;
  } catch {
    return `Letter date ${i.letterDate}`;
  }
}

export { offerFileName };
