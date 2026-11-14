/**
 * Bulk documents (Create & send > Bulk): spreadsheet template, upload parsing, chunked issuing and
 * the results workbook. API: apps/api/app/modules/learning/doc_admin.py (`/admin/documents/bulk/*`)
 * and doc_bulk.py. SheetJS (`xlsx`, pinned 0.20.3 from cdn.sheetjs.com) is loaded on demand only.
 */

import type * as XLSXTypes from "xlsx";
import type { DocField, DocTypeDef, IssuedDoc } from "./docs";
import type { OutboxStatus } from "./types";

export type XLSX = typeof XLSXTypes;

/** Lazy SheetJS: kept out of the main bundle until someone downloads a template or uploads a file. */
export const loadXlsx = (): Promise<XLSX> => import("xlsx");

export const MAX_ROWS = 1000;
export const ISSUE_CHUNK = 25;
export const PDF_CHUNK = 10;

export interface BulkRow {
  /** Spreadsheet line (header = 1), or the position in the picked list. */
  row: number;
  name: string;
  email: string;
  mobile?: string;
  college?: string;
  reg_no?: string;
  fields: Record<string, string>;
  user_id?: string;
  enrolment_id?: string;
  batch_id?: string;
  course_id?: string;
}

export interface BulkCheckRow {
  row: number;
  name: string;
  email: string;
  ok: boolean;
  errors: string[];
  missing: string[];
  warnings: string[];
  fields: Record<string, string>;
}

export interface BulkValidateResult {
  doc_type: string;
  total: number;
  ok: number;
  failed: number;
  settings_problem: string | null;
  email_ready: boolean;
  auto_send: boolean;
  rows: BulkCheckRow[];
}

export interface BulkIssueRowResult {
  row: number;
  status: "issued" | "failed" | "deferred";
  document_id?: string;
  ref_no?: string;
  verify_url?: string;
  name?: string;
  email?: string;
  user_linked?: boolean;
  pdf_available?: boolean;
  email_status?: OutboxStatus | "error" | null;
  error?: string;
  code?: string;
  missing?: string[] | null;
}

export interface BulkIssueResult {
  bulk_id: string;
  doc_type: string;
  issued: number;
  failed: number;
  deferred: number;
  results: BulkIssueRowResult[];
}

export type BulkRunDoc = IssuedDoc & { bulk_row: number | null; bulk_id: string | null };

export interface BulkRunResponse {
  bulk_id: string;
  data: BulkRunDoc[];
  counts: Record<string, number>;
}

export interface BulkPdfsResult {
  files: { id: string; ref_no: string; filename: string; pdf_base64: string }[];
  skipped: { id: string; reason: string }[];
}

export interface BulkEnrolment {
  enrolment_id: string;
  user_id: string;
  name: string;
  email: string;
  mobile: string;
  course_id: string;
  course_title: string;
  batch_id: string | null;
  status: string;
}

/* ------------------------------------------------------------------ columns */

export interface BulkColumn {
  key: string;
  /** "name" | "email" | ... (recipient) or a field key. */
  kind: "recipient" | "field";
  header: string;
  required: boolean;
  help: string;
  aliases: string[];
  field?: DocField;
}

const RECIPIENT_COLUMNS: Omit<BulkColumn, "kind">[] = [
  { key: "name", header: "Student name", required: true, help: "As it should be printed.", aliases: ["name", "full name", "recipient name", "recipient", "candidate name"] },
  { key: "email", header: "Student email", required: true, help: "Where the document is sent; also links it to the student's LMS account.", aliases: ["email", "email address", "e-mail", "mail", "recipient email"] },
  { key: "mobile", header: "Mobile", required: false, help: "Optional. Digits, optionally with + and the country code.", aliases: ["mobile number", "phone", "phone number", "whatsapp", "contact"] },
  { key: "college", header: "College", required: false, help: "Optional; printed under the name on letters.", aliases: ["college name", "institution"] },
  { key: "reg_no", header: "Registration no.", required: false, help: "Optional.", aliases: ["registration number", "reg no", "register no", "regno"] },
];

export function bulkColumns(def: DocTypeDef): BulkColumn[] {
  return [
    ...RECIPIENT_COLUMNS.map((c) => ({ ...c, kind: "recipient" as const })),
    ...def.fields.map((f) => ({
      key: f.key,
      kind: "field" as const,
      header: f.label,
      required: Boolean(f.required),
      help: fieldHelp(f),
      aliases: [f.key],
      field: f,
    })),
  ];
}

function fieldHelp(f: DocField): string {
  const parts: string[] = [];
  if (f.kind === "date") parts.push("Date as YYYY-MM-DD (e.g. 2026-12-01); DD/MM/YYYY and Excel dates are converted.");
  if (f.kind === "select") parts.push(`One of: ${(f.options ?? []).join(", ")}.`);
  if (f.kind === "longtext") parts.push("Several lines allowed (Alt+Enter in Excel).");
  if (f.hint) parts.push(f.hint);
  return parts.join(" ") || "Free text.";
}

function example(c: BulkColumn): string {
  if (c.kind === "recipient") return ({ name: "Ananya Reddy", email: "ananya.reddy@example.com", mobile: "+91 98765 43210", college: "ABC Engineering College", reg_no: "21CS045" } as Record<string, string>)[c.key] ?? "";
  const f = c.field!;
  if (f.kind === "date") return "2026-12-01";
  if (f.kind === "select") return f.options?.[0] ?? "";
  if (f.kind === "money") return "₹5,000 per month";
  if (f.kind === "longtext") return "First point\nSecond point";
  const eg = /^e\.g\.\s*(.+)$/i.exec(f.hint ?? "");
  return eg ? eg[1]!.split(/,| or /)[0]!.trim() : `Example ${f.label.toLowerCase()}`;
}

/** The workbook to download: "Documents" (headers + one example row) and "Instructions". */
export function buildTemplate(x: XLSX, def: DocTypeDef): Uint8Array {
  const cols = bulkColumns(def);
  const data = x.utils.aoa_to_sheet([cols.map((c) => c.header), cols.map(example)]);
  data["!cols"] = cols.map((c) => ({ wch: Math.min(Math.max(c.header.length + 4, 16), 40) }));
  const help = x.utils.aoa_to_sheet([
    [`${def.label}: bulk template`],
    ["Fill one row per student on the Documents sheet (replace the example row). Keep the header row as it is."],
    ["Upload the file in Admin > Certificates & documents > Create & send > Bulk. Every row is checked before anything is issued; you preview a document before issuing."],
    [],
    ["Column", "Required", "What to enter"],
    ...cols.map((c) => [c.header, c.required ? "Yes" : "No", c.help]),
  ]);
  help["!cols"] = [{ wch: 32 }, { wch: 10 }, { wch: 100 }];
  const wb = x.utils.book_new();
  x.utils.book_append_sheet(wb, data, "Documents");
  x.utils.book_append_sheet(wb, help, "Instructions");
  return new Uint8Array(x.write(wb, { type: "array", bookType: "xlsx" }) as ArrayBuffer);
}

const norm = (s: unknown): string =>
  String(s ?? "")
    .toLowerCase()
    .replace(/\*/g, "")
    .replace(/[^a-z0-9]+/g, " ")
    .trim();

const pad = (n: number) => String(n).padStart(2, "0");
const MONTHS = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"];

/** A date cell -> YYYY-MM-DD: Excel serials, ISO, DD/MM/YYYY (also - and .), "1 December 2026". */
export function toIsoDate(x: XLSX | null, v: unknown): string {
  if (typeof v === "number" && x) {
    const d = x.SSF.parse_date_code(v);
    if (d && d.y) return `${d.y}-${pad(d.m)}-${pad(d.d)}`;
  }
  if (v instanceof Date && !Number.isNaN(v.getTime())) return `${v.getFullYear()}-${pad(v.getMonth() + 1)}-${pad(v.getDate())}`;
  const s = String(v ?? "").trim();
  let m = /^(\d{4})-(\d{1,2})-(\d{1,2})$/.exec(s);
  if (m) return `${m[1]}-${pad(+m[2]!)}-${pad(+m[3]!)}`;
  m = /^(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})$/.exec(s);
  if (m) return `${m[3]}-${pad(+m[2]!)}-${pad(+m[1]!)}`;
  m = /^(\d{1,2})\s+([A-Za-z]+),?\s+(\d{4})$/.exec(s);
  if (m) {
    const mi = MONTHS.indexOf(m[2]!.slice(0, 3).toLowerCase());
    if (mi >= 0) return `${m[3]}-${pad(mi + 1)}-${pad(+m[1]!)}`;
  }
  return s;
}

function cellText(v: unknown): string {
  if (v === null || v === undefined) return "";
  if (typeof v === "number") return String(v);
  if (v instanceof Date) return toIsoDate(null, v);
  return String(v).replace(/\r\n/g, "\n").trim();
}

function fieldValue(x: XLSX | null, f: DocField, v: unknown): string {
  if (f.kind === "date") return toIsoDate(x, v);
  const s = cellText(v);
  if (f.kind === "select") {
    const hit = (f.options ?? []).find((o) => o.toLowerCase() === s.toLowerCase());
    return hit ?? s;
  }
  return s;
}

export interface ParsedSheet {
  rows: BulkRow[];
  /** Headers that matched nothing (shown so a misspelt column is noticed). */
  unknown: string[];
  /** Required columns missing from the header row. */
  missingColumns: string[];
  truncated: boolean;
}

/** Rows of the first sheet (`sheet_to_json(header: 1)`) -> bulk rows for this document type. */
export function rowsFromTable(x: XLSX | null, def: DocTypeDef, table: unknown[][]): ParsedSheet {
  const cols = bulkColumns(def);
  const match = (h: unknown): BulkColumn | undefined => {
    const n = norm(h);
    if (!n) return undefined;
    return cols.find((c) => norm(c.header) === n || norm(c.key) === n || c.aliases.some((a) => norm(a) === n));
  };
  const headerAt = table.findIndex((r) => Array.isArray(r) && r.some((h) => ["name", "email"].includes(match(h)?.key ?? "")));
  if (headerAt < 0) return { rows: [], unknown: [], missingColumns: ["Student name", "Student email"], truncated: false };
  const header = table[headerAt]!;
  const map = header.map(match);
  const unknown = header.filter((h, i) => norm(h) && !map[i]).map((h) => String(h));
  const present = new Set(map.filter(Boolean).map((c) => c!.key));
  const missingColumns = cols.filter((c) => c.required && !present.has(c.key)).map((c) => c.header);
  const rows: BulkRow[] = [];
  let truncated = false;
  for (let i = headerAt + 1; i < table.length; i++) {
    const line = table[i] ?? [];
    if (!line.some((v) => cellText(v))) continue;
    if (rows.length >= MAX_ROWS) {
      truncated = true;
      break;
    }
    const r: BulkRow = { row: i + 1, name: "", email: "", fields: {} };
    map.forEach((c, j) => {
      if (!c) return;
      const v = line[j];
      if (c.kind === "field") {
        const s = fieldValue(x, c.field!, v);
        if (s) r.fields[c.key] = s;
      } else {
        (r as unknown as Record<string, string>)[c.key] = cellText(v);
      }
    });
    rows.push(r);
  }
  return { rows, unknown, missingColumns, truncated };
}

function readBytes(file: Blob): Promise<Uint8Array> {
  return new Promise((resolve, reject) => {
    const r = new FileReader();
    r.onload = () => resolve(new Uint8Array(r.result as ArrayBuffer));
    r.onerror = () => reject(new Error("The file could not be read."));
    r.readAsArrayBuffer(file);
  });
}

/** Parse an uploaded .xlsx / .xls / .csv file (first sheet; a sheet named "Documents" first). */
export async function parseFile(file: File, def: DocTypeDef): Promise<ParsedSheet> {
  const x = await loadXlsx();
  const bytes = await readBytes(file);
  const csv = /\.csv$/i.test(file.name) || file.type === "text/csv";
  // CSV as UTF-8 text (TextDecoder drops a BOM) with `raw`: values stay as typed (no number / date guessing)
  const wb = csv ? x.read(new TextDecoder("utf-8").decode(bytes), { type: "string", raw: true }) : x.read(bytes, { type: "array" });
  const first = wb.SheetNames.find((n) => n.toLowerCase() === "documents") ?? wb.SheetNames[0];
  const ws = first ? wb.Sheets[first] : undefined;
  if (!ws) return { rows: [], unknown: [], missingColumns: ["Student name", "Student email"], truncated: false };
  const table = x.utils.sheet_to_json<unknown[]>(ws, { header: 1, raw: true, defval: "", blankrows: false });
  return rowsFromTable(x, def, table);
}

/** Fill empty field cells with the "same for every row" values. */
export function withCommon(rows: BulkRow[], common: Record<string, string>): BulkRow[] {
  const fill = Object.entries(common).filter(([, v]) => v.trim());
  if (!fill.length) return rows;
  return rows.map((r) => ({ ...r, fields: { ...Object.fromEntries(fill), ...Object.fromEntries(Object.entries(r.fields).filter(([, v]) => v.trim())) } }));
}

/** The JSON a row is sent as (empty optional values left out). */
export function rowBody(r: BulkRow, docType: string): Record<string, unknown> {
  return {
    row: r.row,
    name: r.name,
    email: r.email,
    mobile: r.mobile || undefined,
    college: r.college || undefined,
    reg_no: r.reg_no || undefined,
    fields: Object.fromEntries(Object.entries(r.fields).filter(([, v]) => v.trim())),
    user_id: r.user_id || undefined,
    // course completion certificates of LMS enrolments belong to the Due tab
    enrolment_id: docType === "cert_completion" ? undefined : r.enrolment_id || undefined,
    batch_id: r.batch_id || undefined,
    course_id: r.course_id || undefined,
  };
}

/* ------------------------------------------------------------------ issuing in chunks */

export interface IssueProgress {
  done: number;
  total: number;
  issued: number;
  failed: number;
}

/**
 * Issue rows in chunks of `size` (each call stays well inside the 60 s request limit). Each chunk
 * has its own idempotency key; a network failure retries the chunk once with the same key (the
 * server replays the first answer, nothing is issued twice). Rows the server could not reach in
 * time come back `deferred` and are sent again. A refusal of the whole call (e.g. settings
 * missing) stops the run and marks the remaining rows failed.
 */
export async function issueInChunks(
  rows: BulkRow[],
  send: (chunk: BulkRow[], key: string) => Promise<BulkIssueResult>,
  onProgress: (p: IssueProgress) => void,
  opts: { size?: number; newKey?: () => string; retryable?: (err: unknown) => boolean } = {},
): Promise<{ results: BulkIssueRowResult[]; stopped: unknown }> {
  const size = opts.size ?? ISSUE_CHUNK;
  const newKey = opts.newKey ?? (() => crypto.randomUUID());
  const retryable = opts.retryable ?? (() => false);
  const queue = [...rows];
  const final = new Map<number, BulkIssueRowResult>();
  const progress = () => {
    const all = [...final.values()];
    onProgress({ done: all.length, total: rows.length, issued: all.filter((r) => r.status === "issued").length, failed: all.filter((r) => r.status === "failed").length });
  };
  let stalls = 0;
  let stopped: unknown = null;
  progress();
  while (queue.length) {
    const chunk = queue.splice(0, size);
    const key = newKey();
    let out: BulkIssueResult;
    try {
      try {
        out = await send(chunk, key);
      } catch (err) {
        if (!retryable(err)) throw err;
        out = await send(chunk, key);
      }
    } catch (err) {
      stopped = err;
      for (const r of [...chunk, ...queue]) final.set(r.row, { row: r.row, status: "failed", error: "Not issued: the request failed." });
      queue.length = 0;
      break;
    }
    const deferred: BulkRow[] = [];
    for (const res of out.results) {
      if (res.status === "deferred") {
        const r = chunk.find((c) => c.row === res.row);
        if (r) deferred.push(r);
      } else final.set(res.row, res);
    }
    stalls = deferred.length === chunk.length ? stalls + 1 : 0;
    if (stalls >= 3) {
      for (const r of [...deferred, ...queue]) final.set(r.row, { row: r.row, status: "failed", error: "Not issued: the server is too busy. Try these rows again." });
      queue.length = 0;
    } else queue.unshift(...deferred);
    progress();
  }
  return { results: rows.map((r) => final.get(r.row) ?? { row: r.row, status: "failed", error: "Not issued." }), stopped };
}

/* ------------------------------------------------------------------ results */

export function absoluteUrl(path: string): string {
  return typeof window === "undefined" ? path : new URL(path, window.location.origin).toString();
}

const EMAIL_TEXT: Record<string, string> = { awaiting: "Awaiting approval", pending: "Queued to send", sent: "Sent", failed: "Failed", cancelled: "Cancelled", error: "Not queued" };

export function emailText(s: BulkIssueRowResult["email_status"]): string {
  return s ? (EMAIL_TEXT[s] ?? s) : "Not emailed";
}

/** The results workbook: one line per uploaded row with its reference and verification link. */
export function buildResults(x: XLSX, def: DocTypeDef, rows: BulkRow[], results: BulkIssueRowResult[]): Uint8Array {
  const by = new Map(results.map((r) => [r.row, r]));
  const head = ["Row", "Student name", "Student email", "Mobile", "Status", "Reference", "Verification link", "Email", "Problem"];
  const lines = rows.map((r) => {
    const res = by.get(r.row);
    return [
      r.row,
      r.name,
      r.email,
      r.mobile ?? "",
      res?.status === "issued" ? "Issued" : "Not issued",
      res?.ref_no ?? "",
      res?.verify_url ? absoluteUrl(res.verify_url) : "",
      res?.status === "issued" ? emailText(res.email_status) : "",
      res?.status === "issued" ? "" : [res?.error, res?.missing?.length ? `Fill in: ${res.missing.join(", ")}` : ""].filter(Boolean).join(" "),
    ];
  });
  const ws = x.utils.aoa_to_sheet([head, ...lines]);
  ws["!cols"] = [{ wch: 6 }, { wch: 26 }, { wch: 30 }, { wch: 16 }, { wch: 11 }, { wch: 20 }, { wch: 48 }, { wch: 18 }, { wch: 60 }];
  const wb = x.utils.book_new();
  x.utils.book_append_sheet(wb, ws, def.short.slice(0, 31));
  return new Uint8Array(x.write(wb, { type: "array", bookType: "xlsx" }) as ArrayBuffer);
}

/** Save bytes as a file (the browser's download). */
export function saveBytes(bytes: Uint8Array, filename: string, type: string): void {
  const url = URL.createObjectURL(new Blob([bytes as BlobPart], { type }));
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 60_000);
}

export const XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet";

export function slug(s: string): string {
  return s.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "") || "documents";
}
