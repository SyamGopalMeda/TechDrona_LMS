/**
 * Student import (Admin › Users › Import students): the spreadsheet template, parsing an uploaded
 * .xlsx / .csv into JSON rows for `POST admin/students/import`, the results download, and the
 * login message shared on WhatsApp.
 *
 * SheetJS (`xlsx`, pinned to 0.20.3 from the SheetJS distribution: the npm-registry copy stopped
 * at 0.18.5, which has known prototype-pollution / ReDoS issues with untrusted files) is loaded
 * lazily with `import("xlsx")`, so it is only downloaded when someone opens the import or downloads
 * a file. The pure helpers below (`recordsFromMatrix`, `cellText`, ...) need no library and are
 * what the tests exercise.
 */

/** Column order of the template (and the API row fields). */
export const TEMPLATE_COLUMNS = ["full_name", "email", "mobile", "student_type", "course", "batch", "college", "branch", "year", "start_date", "end_date"] as const;
export type ImportColumn = (typeof TEMPLATE_COLUMNS)[number];
export const REQUIRED_COLUMNS: readonly ImportColumn[] = ["full_name", "email"];
/** verified: app/modules/admin/students.py MAX_ROWS (per request; also the file limit). */
export const MAX_ROWS = 500;
/**
 * Rows per "apply" request: every new account costs a password hash and ~a dozen Firestore writes,
 * and the API (Cloud Functions behind Hosting) stops a request at 60 s. Each chunk is its own
 * idempotent request; the results are merged.
 */
export const APPLY_CHUNK = 25;
/** Existing accounts per bulk-enrol request (no account creation: cheaper per row). */
export const ENROL_CHUNK = 50;

export function chunk<T>(list: T[], size: number): T[][] {
  const out: T[][] = [];
  for (let i = 0; i < list.length; i += size) out.push(list.slice(i, i + size));
  return out;
}

const COUNT_KEYS = ["total", "new", "created", "existing", "errors", "enrolled", "added_to_batch", "emailed"] as const;

/** One response from several chunk responses (+ extra rows, e.g. the dry run's error rows). */
export function mergeResponses(parts: ImportResponse[], extraRows: ImportRowResult[] = []): ImportResponse {
  const rows = [...parts.flatMap((p) => p.rows), ...extraRows].sort((a, b) => a.row - b.row);
  const counts = Object.fromEntries(COUNT_KEYS.map((k) => [k, parts.reduce((n, p) => n + (p.counts[k] ?? 0), 0)])) as unknown as ImportCounts;
  counts.total += extraRows.length;
  counts.errors += extraRows.filter((r) => r.status === "error").length;
  return { dry_run: false, mode: parts[0]?.mode ?? "rows", counts, rows, credentials_withheld: parts.some((p) => p.credentials_withheld) };
}
export const STUDENTS_SHEET = "Students";
export const INSTRUCTIONS_SHEET = "Instructions";

/** One row as the API takes it (`ImportRowIn`): text fields + the spreadsheet row number. */
export type ImportRow = { row: number } & Partial<Record<ImportColumn, string>>;

export interface ImportOptions {
  courses: { id: string; slug: string; title: string; status: string }[];
  batches: { id: string; name: string; code: string; course_id: string | null; starts_on: string | null; ends_on: string | null }[];
  student_types: string[];
  max_rows: number;
  email_integrated: boolean;
}

/** verified: app/modules/admin/students.py `_row_out`. */
export interface ImportRowResult {
  row: number;
  full_name: string;
  email: string | null;
  student_type: string | null;
  status: "new" | "existing" | "created" | "error";
  errors: string[];
  warnings: string[];
  user_id: string | null;
  username: string | null;
  temporary_password: string | null;
  course: { id: string; slug: string; title: string } | null;
  batch: { id: string; name: string; code: string } | null;
  enrolled: boolean;
  added_to_batch: boolean;
  email_status: "sent" | "not_connected" | "failed" | null;
}

export interface ImportCounts {
  total: number;
  new: number;
  created: number;
  existing: number;
  errors: number;
  enrolled: number;
  added_to_batch: number;
  emailed: number;
}

export interface ImportResponse {
  dry_run: boolean;
  mode: "rows" | "users";
  counts: ImportCounts;
  rows: ImportRowResult[];
  /** true on a replayed request: the temporary passwords were shown the first time only. */
  credentials_withheld?: boolean;
}

/** Header words people use, mapped to the template column. */
const HEADER_ALIASES: Record<string, ImportColumn> = {
  name: "full_name",
  full_name: "full_name",
  student_name: "full_name",
  email: "email",
  email_address: "email",
  e_mail: "email",
  mail: "email",
  mobile: "mobile",
  mobile_number: "mobile",
  mobile_no: "mobile",
  phone: "mobile",
  phone_number: "mobile",
  whatsapp: "mobile",
  whatsapp_number: "mobile",
  student_type: "student_type",
  type: "student_type",
  course: "course",
  course_slug: "course",
  course_title: "course",
  course_name: "course",
  batch: "batch",
  batch_name: "batch",
  batch_code: "batch",
  college: "college",
  college_name: "college",
  branch: "branch",
  department: "branch",
  year: "year",
  year_of_study: "year",
  start_date: "start_date",
  start: "start_date",
  from: "start_date",
  end_date: "end_date",
  end: "end_date",
  to: "end_date",
};

/** "Full Name *" -> "full_name" -> the column it means (or null when unknown). */
export function headerColumn(header: unknown): ImportColumn | null {
  const key = String(header ?? "")
    .toLowerCase()
    .replace(/\(.*?\)|\*/g, "")
    .trim()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "");
  return HEADER_ALIASES[key] ?? null;
}

const pad = (n: number) => String(n).padStart(2, "0");

/** A cell as text: dates as YYYY-MM-DD, whole numbers without exponent (mobile numbers), trimmed. */
export function cellText(v: unknown): string {
  if (v === null || v === undefined) return "";
  if (v instanceof Date) return Number.isNaN(v.getTime()) ? "" : `${v.getFullYear()}-${pad(v.getMonth() + 1)}-${pad(v.getDate())}`;
  if (typeof v === "number") return Number.isInteger(v) ? v.toFixed(0) : String(v);
  if (typeof v === "boolean") return v ? "true" : "false";
  return String(v).replace(/\s+/g, " ").trim();
}

export interface ParsedSheet {
  rows: ImportRow[];
  /** Headers that match no column (ignored). */
  ignored: string[];
  /** Required columns the sheet doesn't have. */
  missing: ImportColumn[];
}

/**
 * Rows of cells (first non-empty row = headers) -> API rows. Empty rows are skipped; `row` is the
 * spreadsheet row number so errors point at the right line.
 */
export function recordsFromMatrix(matrix: unknown[][]): ParsedSheet {
  const headerAt = matrix.findIndex((r) => Array.isArray(r) && r.some((c) => cellText(c) !== ""));
  if (headerAt < 0) return { rows: [], ignored: [], missing: [...REQUIRED_COLUMNS] };
  const headers = (matrix[headerAt] ?? []).map((h) => ({ raw: cellText(h), col: headerColumn(h) }));
  const seen = new Set<ImportColumn>();
  const cols = headers.map((h) => {
    if (!h.col || seen.has(h.col)) return null; // first column of a kind wins
    seen.add(h.col);
    return h.col;
  });
  const ignored = headers.filter((h, i) => h.raw && cols[i] === null).map((h) => h.raw);
  const rows: ImportRow[] = [];
  for (let i = headerAt + 1; i < matrix.length; i++) {
    const cells = matrix[i] ?? [];
    const row: ImportRow = { row: i + 1 };
    let any = false;
    cols.forEach((col, j) => {
      if (!col) return;
      const text = cellText(cells[j]);
      if (text) {
        row[col] = text;
        any = true;
      }
    });
    if (any) rows.push(row);
  }
  return { rows, ignored, missing: REQUIRED_COLUMNS.filter((c) => !seen.has(c)) };
}

type XLSXModule = typeof import("xlsx");
let xlsxPromise: Promise<XLSXModule> | null = null;
/** SheetJS, loaded on first use. */
export function loadXlsx(): Promise<XLSXModule> {
  xlsxPromise ??= import("xlsx");
  return xlsxPromise;
}

/** The sheet to read: "Students", else the first sheet that isn't the instructions. */
export function pickSheet(names: string[]): string | undefined {
  return names.find((n) => n.trim().toLowerCase() === STUDENTS_SHEET.toLowerCase()) ?? names.find((n) => n.trim().toLowerCase() !== INSTRUCTIONS_SHEET.toLowerCase()) ?? names[0];
}

/** `Blob.text()` / `arrayBuffer()`, with a FileReader fallback (older browsers, jsdom). */
function readBlob(file: Blob, kind: "text"): Promise<string>;
function readBlob(file: Blob, kind: "buffer"): Promise<ArrayBuffer>;
function readBlob(file: Blob, kind: "text" | "buffer"): Promise<string | ArrayBuffer> {
  if (kind === "text" && typeof file.text === "function") return file.text();
  if (kind === "buffer" && typeof file.arrayBuffer === "function") return file.arrayBuffer();
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result as string | ArrayBuffer);
    reader.onerror = () => reject(reader.error ?? new Error("read failed"));
    if (kind === "text") reader.readAsText(file);
    else reader.readAsArrayBuffer(file);
  });
}

/** Read an uploaded .xlsx / .xls / .csv file. CSV cells stay text (no number/date guessing). */
export async function parseStudentFile(file: File): Promise<ParsedSheet> {
  const XLSX = await loadXlsx();
  const isCsv = /\.csv$/i.test(file.name) || file.type === "text/csv";
  const wb = isCsv ? XLSX.read(await readBlob(file, "text"), { type: "string", raw: true }) : XLSX.read(await readBlob(file, "buffer"), { type: "array", cellDates: true });
  const name = pickSheet(wb.SheetNames);
  const ws = name ? wb.Sheets[name] : undefined;
  if (!ws) return { rows: [], ignored: [], missing: [...REQUIRED_COLUMNS] };
  const matrix = XLSX.utils.sheet_to_json<unknown[]>(ws, { header: 1, raw: true, defval: "", blankrows: true });
  return recordsFromMatrix(matrix);
}

/** What each template column means (the Instructions sheet). */
export const COLUMN_HELP: Record<ImportColumn, string> = {
  full_name: "Required. The student's full name.",
  email: "Required. Their email address. An account that already uses this email is linked (never created twice).",
  mobile: "Optional. 10-digit Indian mobile number or +country code. Used for WhatsApp sharing.",
  student_type: "course or internship (empty = course). Internship = interns who never registered on the website.",
  course: "Optional. The course slug or its exact title (see the list below). The student is enrolled in it.",
  batch: "Optional. The batch name or code (see the list below). The student is added to it (and to its course).",
  college: "Optional. College name.",
  branch: "Optional. Branch / department.",
  year: "Optional. Year of study, e.g. 3.",
  start_date: "Optional. Start date (internships), YYYY-MM-DD or DD-MM-YYYY.",
  end_date: "Optional. End date (internships), YYYY-MM-DD or DD-MM-YYYY.",
};

/** The Instructions sheet as rows of cells. */
export function instructionRows(options?: Pick<ImportOptions, "courses" | "batches"> | null): string[][] {
  const out: string[][] = [
    ["Tech Drona LMS — student import"],
    [""],
    ["Fill in the Students sheet: one student per row, keep the header row. Max 500 rows per file."],
    ["Every new student gets a username (td + 6 digits) and a temporary password, shown once after the import (download the results)."],
    ["They must choose their own password at their first sign-in. Every student must be 18 or older."],
    [""],
    ["Column", "What to enter"],
    ...TEMPLATE_COLUMNS.map((c) => [c, COLUMN_HELP[c]]),
  ];
  if (options?.courses.length) {
    out.push([""], ["Courses (course column: slug or title)", ""], ["slug", "title"], ...options.courses.map((c) => [c.slug, c.title]));
  }
  if (options?.batches.length) {
    out.push([""], ["Batches (batch column: name or code)", ""], ["name", "code"], ...options.batches.map((b) => [b.name, b.code]));
  }
  return out;
}

/** Example row in the template (so the format is obvious). */
export const EXAMPLE_ROW: Record<ImportColumn, string> = {
  full_name: "Asha Rao",
  email: "asha.rao@example.com",
  mobile: "9876543210",
  student_type: "internship",
  course: "",
  batch: "",
  college: "RV College of Engineering",
  branch: "CSE",
  year: "3",
  start_date: "2026-12-01",
  end_date: "2027-01-31",
};

function autoWidth(rows: string[][]): { wch: number }[] {
  const n = Math.max(0, ...rows.map((r) => r.length));
  return Array.from({ length: n }, (_, i) => ({ wch: Math.min(60, Math.max(10, ...rows.map((r) => (r[i] ?? "").length + 2))) }));
}

/** Download `student-import-template.xlsx` (Students + Instructions sheets). */
export async function downloadTemplate(options?: Pick<ImportOptions, "courses" | "batches"> | null): Promise<void> {
  const XLSX = await loadXlsx();
  const wb = XLSX.utils.book_new();
  const students = [[...TEMPLATE_COLUMNS], TEMPLATE_COLUMNS.map((c) => EXAMPLE_ROW[c])];
  const ws = XLSX.utils.aoa_to_sheet(students);
  ws["!cols"] = autoWidth(students);
  XLSX.utils.book_append_sheet(wb, ws, STUDENTS_SHEET);
  const help = instructionRows(options);
  const hs = XLSX.utils.aoa_to_sheet(help);
  hs["!cols"] = [{ wch: 38 }, { wch: 100 }];
  XLSX.utils.book_append_sheet(wb, hs, INSTRUCTIONS_SHEET);
  XLSX.writeFile(wb, "student-import-template.xlsx");
}

export const RESULT_COLUMNS = ["row", "full_name", "email", "status", "username", "temporary_password", "student_type", "course", "batch", "enrolled", "added_to_batch", "email_status", "messages"] as const;

const STATUS_WORDS: Record<ImportRowResult["status"], string> = { new: "New", existing: "Existing account", created: "Created", error: "Error" };
export const statusWord = (s: ImportRowResult["status"]) => STATUS_WORDS[s] ?? s;

/** The results as rows of cells (header first). The temporary password appears only here. */
export function resultMatrix(rows: ImportRowResult[]): string[][] {
  return [
    [...RESULT_COLUMNS],
    ...rows.map((r) => [
      String(r.row),
      r.full_name,
      r.email ?? "",
      statusWord(r.status),
      r.username ?? "",
      r.temporary_password ?? "",
      r.student_type ?? "",
      r.course?.title ?? "",
      r.batch?.name ?? "",
      r.enrolled ? "yes" : "",
      r.added_to_batch ? "yes" : "",
      r.email_status ?? "",
      [...r.errors, ...r.warnings].join(" "),
    ]),
  ];
}

/** Download the results as .xlsx or .csv. */
export async function downloadResults(rows: ImportRowResult[], format: "xlsx" | "csv"): Promise<void> {
  const XLSX = await loadXlsx();
  const wb = XLSX.utils.book_new();
  const data = resultMatrix(rows);
  const ws = XLSX.utils.aoa_to_sheet(data);
  ws["!cols"] = autoWidth(data);
  XLSX.utils.book_append_sheet(wb, ws, "Results");
  const stamp = new Date().toISOString().slice(0, 16).replace(/[:T]/g, "-");
  XLSX.writeFile(wb, `student-import-results-${stamp}.${format}`, { bookType: format });
}

/** The sign-in page of this LMS. */
export const loginUrl = () => (typeof window === "undefined" ? "/login" : `${window.location.origin}/login`);

/** Plain-text login details (Copy / WhatsApp). */
export function loginMessage(d: { name: string; username: string | null; email: string | null; password: string | null; mustChange: boolean; url?: string }): string {
  const lines = [`Hi ${d.name}, your Tech Drona LMS account is ready.`, "", `Log in: ${d.url ?? loginUrl()}`];
  if (d.username) lines.push(`Username: ${d.username}`);
  if (d.email) lines.push(`Email: ${d.email}`);
  if (d.password) {
    lines.push(`Temporary password: ${d.password}`);
    if (d.mustChange) lines.push("", "You'll be asked to choose your own password when you first log in.");
  }
  return lines.join("\n");
}

/** wa.me link with the message; Indian 10-digit numbers get the 91 country code. */
export function whatsappLink(phone: string | null | undefined, text: string): string {
  let digits = String(phone ?? "").replace(/\D/g, "");
  if (digits.length === 11 && digits.startsWith("0")) digits = digits.slice(1);
  if (digits.length === 10) digits = `91${digits}`;
  return `https://wa.me/${digits}?text=${encodeURIComponent(text)}`;
}
