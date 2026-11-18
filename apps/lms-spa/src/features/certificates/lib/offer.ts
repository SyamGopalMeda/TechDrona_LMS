/**
 * Internship offer letters (Certificates & documents > Offer letters): a browser-only generator.
 * The letter is the "modern corporate" Tech Drona template (navy band, glance table, terms,
 * HR signature, acceptance form); PDFs are drawn in the browser by ./offerpdf.ts, so nothing is
 * stored on the server. Dates: start = letter date + 1 day; end = start + N months - 1 day.
 */

import type { XLSX } from "./bulk";

export interface OfferSettings {
  company: string;
  address: string;
  website: string;
  role: string;
  mode: string;
  months: number;
  signatory: string;
  designation: string;
  /** Next reference number (TD-OL-2026-0161); bumped after every generated letter. */
  nextRef: string;
  /** PNG/JPEG data URL of the signatory's signature (kept in this browser only). */
  signature: string;
}

export const DEFAULT_SETTINGS: OfferSettings = {
  company: "Tech Drona",
  address: "Vijayawada, Andhra Pradesh",
  website: "https://techdrona.in/",
  role: "Full Stack & Agentic AI Developer Intern",
  mode: "hybrid",
  months: 4,
  signatory: "S D Sai Guptha",
  designation: "Human Resources Department",
  nextRef: "TD-OL-2026-0161",
  signature: "",
};

export const MODES = ["hybrid", "online", "on-site"] as const;

/** One letter's inputs (a form entry or a spreadsheet row). */
export interface OfferInput {
  name: string;
  email: string;
  /** ISO yyyy-mm-dd. */
  letterDate: string;
  ref: string;
  role: string;
  mode: string;
  months: number;
  /** Optional overrides (ISO); otherwise derived from the letter date. */
  start?: string;
  end?: string;
}

/** Everything the PDF and the email need, already formatted. */
export interface OfferLetter {
  name: string;
  firstName: string;
  email: string;
  ref: string;
  role: string;
  mode: string;
  date: string;
  start: string;
  end: string;
  duration: string;
  company: string;
  address: string;
  website: string;
  signatory: string;
  designation: string;
  signature: string;
}

const MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];

function parts(iso: string): [number, number, number] {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso);
  if (!m) throw new Error(`Invalid date: ${iso}`);
  return [Number(m[1]), Number(m[2]), Number(m[3])];
}

const iso = (d: Date) => `${d.getUTCFullYear()}-${String(d.getUTCMonth() + 1).padStart(2, "0")}-${String(d.getUTCDate()).padStart(2, "0")}`;

export function isIsoDate(s: string): boolean {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(s)) return false;
  const [y, m, d] = parts(s);
  const dt = new Date(Date.UTC(y, m - 1, d));
  return dt.getUTCMonth() === m - 1 && dt.getUTCDate() === d;
}

export function addDays(s: string, n: number): string {
  const [y, m, d] = parts(s);
  return iso(new Date(Date.UTC(y, m - 1, d + n)));
}

/** Same day N months later (clamped to the month's last day: 31 Jan + 1 = 28/29 Feb). */
export function addMonths(s: string, n: number): string {
  const [y, m, d] = parts(s);
  const last = new Date(Date.UTC(y, m - 1 + n + 1, 0)).getUTCDate();
  return iso(new Date(Date.UTC(y, m - 1 + n, Math.min(d, last))));
}

/** "3 November 2026". */
export function longDate(s: string): string {
  const [y, m, d] = parts(s);
  return `${d} ${MONTHS[m - 1]} ${y}`;
}

export function periodOf(letterDate: string, months: number): { start: string; end: string } {
  const start = addDays(letterDate, 1);
  return { start, end: addDays(addMonths(start, months), -1) };
}

/** "TD-OL-2026-0151" -> "TD-OL-2026-0152" (keeps the zero padding). */
export function nextRef(ref: string): string {
  const m = /^(.*?)(\d+)$/.exec(ref.trim());
  if (!m) return ref;
  return m[1] + String(Number(m[2]) + 1).padStart(m[2]!.length, "0");
}

export function todayIso(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

/** Problems that stop a letter from being generated (empty when it is ready). */
export function offerErrors(i: OfferInput): string[] {
  const e: string[] = [];
  if (!i.name.trim()) e.push("Name is required");
  if (!isIsoDate(i.letterDate)) e.push("Letter date is missing or invalid");
  if (!i.ref.trim()) e.push("Reference number is required");
  if (!i.role.trim()) e.push("Role is required");
  if (!(i.months >= 1 && i.months <= 24)) e.push("Duration must be 1 to 24 months");
  if (i.start && !isIsoDate(i.start)) e.push("Start date is invalid");
  if (i.end && !isIsoDate(i.end)) e.push("End date is invalid");
  if (i.email && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(i.email)) e.push("Email looks invalid");
  return e;
}

export function buildOffer(i: OfferInput, s: OfferSettings): OfferLetter {
  const p = periodOf(i.letterDate, i.months);
  const name = i.name.trim().replace(/\s+/g, " ");
  return {
    name,
    firstName: name,
    email: i.email.trim(),
    ref: i.ref.trim(),
    role: i.role.trim(),
    mode: (i.mode || "hybrid").trim().toLowerCase(),
    date: longDate(i.letterDate),
    start: longDate(i.start || p.start),
    end: longDate(i.end || p.end),
    duration: `${i.months} month${i.months === 1 ? "" : "s"} (${i.months * 4} weeks)`,
    company: s.company,
    address: s.address,
    website: s.website,
    signatory: s.signatory,
    designation: s.designation,
    signature: s.signature,
  };
}

/** "TD-OL-2026-0152 - Perikela Jaya Satya Sai Prakash.pdf". */
export function offerFileName(l: Pick<OfferLetter, "ref" | "name">): string {
  return `${l.ref} - ${l.name}`.replace(/[^A-Za-z0-9 .-]+/g, "").trim() + ".pdf";
}

/* ------------------------------------------------------------------ email draft */

export interface EmailDraft {
  to: string;
  subject: string;
  body: string;
  attachment: string;
}

export function emailDraft(l: OfferLetter): EmailDraft {
  const modeLine =
    l.mode === "hybrid" ? "Hybrid (live online sessions and on-site project days)" : l.mode === "online" ? "Online (live online sessions)" : l.mode[0]!.toUpperCase() + l.mode.slice(1);
  const body = [
    `Dear ${l.name},`,
    "",
    `Congratulations! We are pleased to offer you an internship with ${l.company} as a ${l.role}.`,
    "",
    `Your offer letter (Ref. No. ${l.ref}) is attached to this email. In brief:`,
    "",
    `- Role: ${l.role}`,
    `- Internship period: ${l.start} to ${l.end} (${l.duration.replace(/ \(.*\)$/, "")})`,
    `- Mode: ${modeLine}`,
    "",
    "To accept the offer:",
    "1. Read the offer letter and its terms and conditions.",
    "2. Sign the Acceptance of Offer form at the end of the letter.",
    "3. Reply to this email with a scanned copy or a clear photo of the signed form within 7 days of receiving this email.",
    "",
    "If you have any questions, reply to this email and we'll be glad to help.",
    "",
    "We look forward to working with you.",
    "",
    "Warm regards,",
    l.signatory,
    l.designation,
    l.company,
    l.address,
    l.website,
  ].join("\n");
  return { to: l.email, subject: `Internship Offer Letter – ${l.role} | ${l.company}`, body, attachment: offerFileName(l) };
}

/** Gmail compose window prefilled with the draft (the PDF is attached by hand). */
export function gmailComposeUrl(d: EmailDraft): string {
  const q = new URLSearchParams({ view: "cm", fs: "1", to: d.to, su: d.subject, body: d.body });
  return `https://mail.google.com/mail/?${q.toString()}`;
}

export function mailtoUrl(d: EmailDraft): string {
  return `mailto:${encodeURIComponent(d.to)}?subject=${encodeURIComponent(d.subject)}&body=${encodeURIComponent(d.body)}`;
}

/* ------------------------------------------------------------------ spreadsheet */

export const TEMPLATE_HEADERS = ["Name", "Email", "Letter date", "Ref No", "Role", "Mode", "Duration (months)", "Start date", "End date"] as const;

const HEADER_KEYS: Record<string, keyof SheetRow> = {
  name: "name",
  "full name": "name",
  "student name": "name",
  email: "email",
  "email id": "email",
  "letter date": "letterDate",
  date: "letterDate",
  "ref no": "ref",
  ref: "ref",
  "reference no": "ref",
  "intern id": "ref",
  role: "role",
  mode: "mode",
  "duration (months)": "months",
  duration: "months",
  months: "months",
  "start date": "start",
  "end date": "end",
};

interface SheetRow {
  name: string;
  email: string;
  letterDate: string;
  ref: string;
  role: string;
  mode: string;
  months: string;
  start: string;
  end: string;
}

export function templateWorkbook(x: XLSX, s: OfferSettings): Uint8Array {
  const ws = x.utils.aoa_to_sheet([
    [...TEMPLATE_HEADERS],
    ["Perikela Jaya Satya Sai Prakash", "student@example.com", "2026-11-02", "", s.role, s.mode, s.months, "", ""],
  ]);
  ws["!cols"] = [{ wch: 34 }, { wch: 30 }, { wch: 13 }, { wch: 18 }, { wch: 40 }, { wch: 10 }, { wch: 18 }, { wch: 13 }, { wch: 13 }];
  const help = x.utils.aoa_to_sheet([
    ["Column", "Required", "Notes"],
    ["Name", "Yes", "Full name as it should appear on the letter."],
    ["Email", "No", "Used for the email draft."],
    ["Letter date", "Yes", "The letter's date (yyyy-mm-dd, dd-mm-yyyy or an Excel date). Start = next day."],
    ["Ref No", "No", "Blank = next number automatically (from the Offer letters settings)."],
    ["Role", "No", `Blank = ${s.role}`],
    ["Mode", "No", "hybrid, online or on-site. Blank = " + s.mode],
    ["Duration (months)", "No", `Blank = ${s.months}. End = start + months - 1 day.`],
    ["Start date / End date", "No", "Only to override the calculated period."],
  ]);
  help["!cols"] = [{ wch: 22 }, { wch: 10 }, { wch: 80 }];
  const wb = x.utils.book_new();
  x.utils.book_append_sheet(wb, ws, "Offer letters");
  x.utils.book_append_sheet(wb, help, "How to fill");
  return new Uint8Array(x.write(wb, { type: "array", bookType: "xlsx" }) as ArrayBuffer);
}

/** A spreadsheet cell -> ISO date (Excel serials, yyyy-mm-dd, dd-mm-yyyy, dd/mm/yyyy, "2 November 2026"). */
export function cellDate(v: unknown): string {
  if (v === null || v === undefined || v === "") return "";
  if (v instanceof Date && !Number.isNaN(v.getTime())) return `${v.getFullYear()}-${String(v.getMonth() + 1).padStart(2, "0")}-${String(v.getDate()).padStart(2, "0")}`;
  if (typeof v === "number" && v > 20000 && v < 80000) return addDays("1899-12-30", Math.floor(v));
  const t = String(v).trim();
  let m = /^(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})$/.exec(t);
  if (m) return `${m[1]}-${m[2]!.padStart(2, "0")}-${m[3]!.padStart(2, "0")}`;
  m = /^(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})$/.exec(t);
  if (m) return `${m[3]}-${m[2]!.padStart(2, "0")}-${m[1]!.padStart(2, "0")}`;
  m = /^(\d{1,2})(?:st|nd|rd|th)?[\s-]+([A-Za-z]+)[\s,-]+(\d{4})$/.exec(t);
  if (m) {
    const mi = MONTHS.findIndex((n) => n.toLowerCase().startsWith(m![2]!.toLowerCase().slice(0, 3)));
    if (mi >= 0) return `${m[3]}-${String(mi + 1).padStart(2, "0")}-${m[1]!.padStart(2, "0")}`;
  }
  return t; // left as typed: offerErrors reports it
}

/**
 * Upload -> letter inputs. Blank Ref No cells get consecutive numbers from `firstRef`;
 * blank Role / Mode / Duration take the settings' values.
 */
export function parseOfferSheet(x: XLSX, bytes: Uint8Array, s: OfferSettings, firstRef: string): OfferInput[] {
  const wb = x.read(bytes, { type: "array" });
  const ws = wb.Sheets[wb.SheetNames[0]!];
  if (!ws) return [];
  const table = x.utils.sheet_to_json<unknown[]>(ws, { header: 1, raw: true, defval: "", blankrows: false });
  const [head, ...rows] = table;
  if (!head) return [];
  const cols = head.map((h) => HEADER_KEYS[String(h).trim().toLowerCase()]);
  if (!cols.includes("name")) throw new Error("The first sheet needs a 'Name' column (download the template).");
  let ref = firstRef;
  const out: OfferInput[] = [];
  for (const r of rows) {
    const row: Partial<Record<keyof SheetRow, unknown>> = {};
    cols.forEach((k, i) => {
      if (k) row[k] = r[i];
    });
    const name = String(row.name ?? "").trim();
    if (!name) continue;
    let rowRef = String(row.ref ?? "").trim();
    if (!rowRef) {
      rowRef = ref;
      ref = nextRef(ref);
    }
    out.push({
      name,
      email: String(row.email ?? "").trim(),
      letterDate: cellDate(row.letterDate),
      ref: rowRef,
      role: String(row.role ?? "").trim() || s.role,
      mode: String(row.mode ?? "").trim().toLowerCase() || s.mode,
      months: Number(String(row.months ?? "").trim() || s.months),
      start: cellDate(row.start) || undefined,
      end: cellDate(row.end) || undefined,
    });
  }
  return out;
}

/* ------------------------------------------------------------------ settings (this browser) */

const KEY = "td.offer-letters.settings";

export function loadSettings(): OfferSettings {
  try {
    const raw = window.localStorage.getItem(KEY);
    return raw ? { ...DEFAULT_SETTINGS, ...(JSON.parse(raw) as Partial<OfferSettings>) } : { ...DEFAULT_SETTINGS };
  } catch {
    return { ...DEFAULT_SETTINGS };
  }
}

export function saveSettings(s: OfferSettings): boolean {
  try {
    window.localStorage.setItem(KEY, JSON.stringify(s));
    return true;
  } catch {
    return false;
  }
}
