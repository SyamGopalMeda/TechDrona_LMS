/**
 * Offer letters (Certificates & documents > Offer letters): a browser-only generator.
 * Two predefined templates share the "modern corporate" Tech Drona layout (navy band, glance table,
 * terms, HR signature, acceptance form), drawn in the browser by ./offerpdf.ts:
 *
 * * internship: start = letter date + 1 day; end = start + N months - 1 day.
 * * employment: joining date = start date (default letter date + 1 day), annual CTC, probation.
 *
 * Nothing is stored on the server: the candidate register lives in this browser (./register.ts).
 */

import type { XLSX } from "./bulk";

export type LetterKind = "internship" | "employment";

export const LETTER_KINDS: { value: LetterKind; label: string; short: string }[] = [
  { value: "internship", label: "Internship offer letter", short: "Internship" },
  { value: "employment", label: "Employment offer letter", short: "Employment" },
];

export function kindLabel(k: LetterKind): string {
  return LETTER_KINDS.find((x) => x.value === k)?.label ?? "Offer letter";
}

/** "Internship" / "Employment" / blank -> kind (anything mentioning job/employ/full-time = employment). */
export function parseKind(v: unknown): LetterKind {
  const t = String(v ?? "").trim().toLowerCase();
  return /employ|job|full[- ]?time|permanent/.test(t) ? "employment" : "internship";
}

export interface OfferSettings {
  company: string;
  address: string;
  website: string;
  role: string;
  mode: string;
  months: number;
  signatory: string;
  designation: string;
  /** Next internship reference number (TD-OL-2026-0161); bumped after every generated letter. */
  nextRef: string;
  /** PNG/JPEG data URL of the signatory's signature (kept in this browser only). */
  signature: string;
  /** Employment template defaults. */
  empRole: string;
  empNextRef: string;
  ctc: string;
  probation: number;
  location: string;
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
  nextRef: "TD-OL-2026-0172",
  signature: "",
  empRole: "",
  empNextRef: "TD-EO-2026-0001",
  ctc: "",
  probation: 6,
  location: "Vijayawada, Andhra Pradesh",
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
  /** Optional overrides (ISO); otherwise derived from the letter date. Employment: start = joining date. */
  start?: string;
  end?: string;
  /** Template; internship when absent. */
  kind?: LetterKind;
  /** Employment only: annual CTC as printed ("₹4,20,000 per annum"), probation months, work location. */
  ctc?: string;
  probation?: number;
  location?: string;
}

/** Everything the PDF and the email need, already formatted. */
export interface OfferLetter {
  kind: LetterKind;
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
  /** Employment only ("" for internships). */
  ctc: string;
  probation: string;
  location: string;
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
  const emp = i.kind === "employment";
  if (!i.name.trim()) e.push("Name is required");
  if (!isIsoDate(i.letterDate)) e.push("Letter date is missing or invalid");
  if (!i.ref.trim()) e.push("Reference number is required");
  if (!i.role.trim()) e.push(emp ? "Position is required" : "Role is required");
  if (emp) {
    if (!(i.ctc ?? "").trim()) e.push("Annual CTC is required");
    const p = i.probation ?? 0;
    if (!(p >= 0 && p <= 12)) e.push("Probation must be 0 to 12 months");
  } else if (!(i.months >= 1 && i.months <= 24)) e.push("Duration must be 1 to 24 months");
  if (i.start && !isIsoDate(i.start)) e.push(emp ? "Joining date is invalid" : "Start date is invalid");
  if (i.end && !isIsoDate(i.end)) e.push("End date is invalid");
  if (i.email && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(i.email)) e.push("Email looks invalid");
  return e;
}

/** A plain number becomes "₹4,20,000 per annum" (Indian grouping); text is kept as typed. */
export function formatCtc(v: string): string {
  const t = v.trim();
  const n = /^(?:rs\.?|inr|₹)?\s*([\d,]+(?:\.\d+)?)$/i.exec(t);
  if (!n) return t;
  const num = Number(n[1]!.replace(/,/g, ""));
  if (!Number.isFinite(num)) return t;
  return `₹${num.toLocaleString("en-IN")} per annum`;
}

export function buildOffer(i: OfferInput, s: OfferSettings): OfferLetter {
  const name = i.name.trim().replace(/\s+/g, " ");
  const kind: LetterKind = i.kind ?? "internship";
  const common = {
    kind,
    name,
    firstName: name,
    email: i.email.trim(),
    ref: i.ref.trim(),
    role: i.role.trim(),
    mode: (i.mode || "hybrid").trim().toLowerCase(),
    date: longDate(i.letterDate),
    company: s.company,
    address: s.address,
    website: s.website,
    signatory: s.signatory,
    designation: s.designation,
    signature: s.signature,
  };
  if (kind === "employment") {
    const p = i.probation ?? s.probation;
    return {
      ...common,
      start: longDate(i.start || addDays(i.letterDate, 1)),
      end: "",
      duration: "",
      ctc: formatCtc(i.ctc ?? ""),
      probation: p > 0 ? `${p} month${p === 1 ? "" : "s"}` : "",
      location: (i.location || s.location).trim(),
    };
  }
  const p = periodOf(i.letterDate, i.months);
  return {
    ...common,
    start: longDate(i.start || p.start),
    end: longDate(i.end || p.end),
    duration: `${i.months} month${i.months === 1 ? "" : "s"} (${i.months * 4} weeks)`,
    ctc: "",
    probation: "",
    location: "",
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

function modeLine(mode: string): string {
  return mode === "hybrid" ? "Hybrid (live online sessions and on-site project days)" : mode === "online" ? "Online (live online sessions)" : mode[0]!.toUpperCase() + mode.slice(1);
}

const ACCEPT_STEPS = [
  "To accept the offer:",
  "1. Read the offer letter and its terms and conditions.",
  "2. Sign the Acceptance of Offer form at the end of the letter.",
  "3. Reply to this email with a scanned copy or a clear photo of the signed form within 7 days of receiving this email.",
];

export function emailDraft(l: OfferLetter): EmailDraft {
  const sign = ["Warm regards,", l.signatory, l.designation, l.company, l.address, l.website];
  if (l.kind === "employment") {
    const body = [
      `Dear ${l.name},`,
      "",
      `Congratulations! We are pleased to offer you the position of ${l.role} at ${l.company}.`,
      "",
      `Your offer letter (Ref. No. ${l.ref}) is attached to this email. In brief:`,
      "",
      `- Position: ${l.role}`,
      `- Date of joining: ${l.start}`,
      `- Annual CTC: ${l.ctc}`,
      `- Location: ${l.location}`,
      ...(l.probation ? [`- Probation: ${l.probation}`] : []),
      "",
      ...ACCEPT_STEPS,
      "",
      "If you have any questions, reply to this email and we'll be glad to help.",
      "",
      "We look forward to welcoming you to the team.",
      "",
      ...sign,
    ].join("\n");
    return { to: l.email, subject: `Employment Offer Letter – ${l.role} | ${l.company}`, body, attachment: offerFileName(l) };
  }
  const body = [
    `Dear ${l.name},`,
    "",
    `Congratulations! We are pleased to offer you an internship with ${l.company} as a ${l.role}.`,
    "",
    `Your offer letter (Ref. No. ${l.ref}) is attached to this email. In brief:`,
    "",
    `- Role: ${l.role}`,
    `- Internship period: ${l.start} to ${l.end} (${l.duration.replace(/ \(.*\)$/, "")})`,
    `- Mode: ${modeLine(l.mode)}`,
    "",
    ...ACCEPT_STEPS,
    "",
    "If you have any questions, reply to this email and we'll be glad to help.",
    "",
    "We look forward to working with you.",
    "",
    ...sign,
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

export const TEMPLATE_HEADERS = [
  "Name",
  "Email",
  "Letter type",
  "Letter date",
  "Ref No",
  "Role / Position",
  "Mode",
  "Duration (months)",
  "Start / Joining date",
  "End date",
  "Annual CTC",
  "Probation (months)",
  "Location",
] as const;

/** Register-only columns (the register export adds them; an upload with them restores the status). */
export const STATUS_HEADERS = ["Status", "Sent on"] as const;

export type SheetKey =
  | "name"
  | "email"
  | "kind"
  | "letterDate"
  | "ref"
  | "role"
  | "mode"
  | "months"
  | "start"
  | "end"
  | "ctc"
  | "probation"
  | "location"
  | "status"
  | "sentOn"
  | "department"
  | "notes";

const HEADER_KEYS: Record<string, SheetKey> = {
  name: "name",
  "full name": "name",
  "student name": "name",
  "candidate name": "name",
  "full name (as on offer letter)": "name",
  email: "email",
  "email id": "email",
  "letter type": "kind",
  type: "kind",
  template: "kind",
  "letter date": "letterDate",
  date: "letterDate",
  "ref no": "ref",
  ref: "ref",
  "reference no": "ref",
  "intern id": "ref",
  "offer letter ref": "ref",
  role: "role",
  position: "role",
  designation: "role",
  "role / position": "role",
  mode: "mode",
  "duration (months)": "months",
  duration: "months",
  months: "months",
  "start date": "start",
  "joining date": "start",
  "date of joining": "start",
  "start / joining date": "start",
  "end date": "end",
  ctc: "ctc",
  "annual ctc": "ctc",
  salary: "ctc",
  "probation (months)": "probation",
  probation: "probation",
  location: "location",
  "work location": "location",
  status: "status",
  "letter status": "status",
  "sent on": "sentOn",
  department: "department",
  notes: "notes",
  remarks: "notes",
};

export function templateWorkbook(x: XLSX, s: OfferSettings): Uint8Array {
  const ws = x.utils.aoa_to_sheet([
    [...TEMPLATE_HEADERS],
    ["Perikela Jaya Satya Sai Prakash", "student@example.com", "Internship", "2026-11-02", "", s.role, s.mode, s.months, "", "", "", "", ""],
    ["Example Candidate", "candidate@example.com", "Employment", "2026-12-01", "", s.empRole || "Software Developer", "on-site", "", "2026-12-15", "", "420000", s.probation, s.location],
  ]);
  ws["!cols"] = [34, 30, 13, 13, 18, 40, 10, 18, 20, 13, 16, 18, 28].map((wch) => ({ wch }));
  const help = x.utils.aoa_to_sheet([
    ["Column", "Required", "Notes"],
    ["Name", "Yes", "Full name as it should appear on the letter."],
    ["Email", "No", "Used for the email draft."],
    ["Letter type", "No", "Internship or Employment. Blank = Internship."],
    ["Letter date", "Yes", "The letter's date (yyyy-mm-dd, dd-mm-yyyy or an Excel date)."],
    ["Ref No", "No", "Blank = next number automatically when the letter is generated."],
    ["Role / Position", "No", `Blank = ${s.role} (internship)${s.empRole ? ` or ${s.empRole} (employment)` : "; required for employment"}.`],
    ["Mode", "No", "hybrid, online or on-site. Blank = " + s.mode],
    ["Duration (months)", "Internship", `Blank = ${s.months}. Internship starts the day after the letter date; end = start + months - 1 day.`],
    ["Start / Joining date", "No", "Internship: overrides the start. Employment: the date of joining (blank = day after the letter date)."],
    ["End date", "No", "Internship only: overrides the calculated end."],
    ["Annual CTC", "Employment", "e.g. 420000 (printed as ₹4,20,000 per annum) or your own text."],
    ["Probation (months)", "No", `Employment only. Blank = ${s.probation}; 0 = no probation.`],
    ["Location", "No", `Employment only. Blank = ${s.location}.`],
    ["Status / Sent on", "No", "Only in a register you downloaded: uploading it again restores which letters were sent."],
  ]);
  help["!cols"] = [{ wch: 22 }, { wch: 12 }, { wch: 90 }];
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
  const t = String(v).trim().replace(/^date\s*/i, "");
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

/** One uploaded row: the letter inputs plus register-only columns (status restore). */
export interface SheetEntry {
  input: OfferInput;
  /** True when the sheet gave the Ref No (otherwise it is assigned on generation). */
  refGiven: boolean;
  status: string;
  sentOn: string;
}

/**
 * Upload -> rows. Blank Ref No cells stay blank (`refGiven` false) and are numbered when the
 * letter is generated; blank Role / Mode / Duration / Probation / Location take the settings' values.
 */
export function readOfferSheet(x: XLSX, bytes: Uint8Array, s: OfferSettings): SheetEntry[] {
  const wb = x.read(bytes, { type: "array" });
  const ws = wb.Sheets[wb.SheetNames[0]!];
  if (!ws) return [];
  const table = x.utils.sheet_to_json<unknown[]>(ws, { header: 1, raw: true, defval: "", blankrows: false });
  const [head, ...rows] = table;
  if (!head) return [];
  const cols = head.map((h) => HEADER_KEYS[String(h).trim().toLowerCase()]);
  if (!cols.includes("name")) throw new Error("The first sheet needs a 'Name' column (download the template).");
  const out: SheetEntry[] = [];
  for (const r of rows) {
    const row: Partial<Record<SheetKey, unknown>> = {};
    cols.forEach((k, i) => {
      if (k && row[k] === undefined) row[k] = r[i];
    });
    const str = (k: SheetKey) => String(row[k] ?? "").trim();
    const name = str("name");
    if (!name) continue;
    const kind = parseKind(row.kind);
    const emp = kind === "employment";
    const probation = str("probation");
    out.push({
      input: {
        name,
        email: str("email"),
        kind,
        letterDate: cellDate(row.letterDate),
        ref: str("ref"),
        role: str("role") || (emp ? s.empRole : s.role),
        mode: str("mode").toLowerCase() || (emp ? "on-site" : s.mode),
        months: Number(str("months") || s.months),
        start: cellDate(row.start) || undefined,
        end: emp ? undefined : cellDate(row.end) || undefined,
        ...(emp ? { ctc: str("ctc") || s.ctc, probation: probation === "" ? s.probation : Number(probation), location: str("location") || s.location } : {}),
      },
      refGiven: str("ref") !== "",
      status: str("status"),
      sentOn: cellDate(row.sentOn),
    });
  }
  return out;
}

/**
 * Upload -> letter inputs (older callers). Blank Ref No cells get consecutive numbers from
 * `firstRef`; blank Role / Mode / Duration take the settings' values.
 */
export function parseOfferSheet(x: XLSX, bytes: Uint8Array, s: OfferSettings, firstRef: string): OfferInput[] {
  let ref = firstRef;
  return readOfferSheet(x, bytes, s).map(({ input, refGiven }) => {
    if (refGiven) return input;
    const r = ref;
    ref = nextRef(ref);
    return { ...input, ref: r };
  });
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
