import { describe, expect, it } from "vitest";
import * as XLSX from "xlsx";
import { PDFDocument } from "pdf-lib";
import {
  DEFAULT_SETTINGS,
  addMonths,
  buildOffer,
  cellDate,
  emailDraft,
  gmailComposeUrl,
  longDate,
  nextRef,
  offerErrors,
  offerFileName,
  parseOfferSheet,
  periodOf,
  templateWorkbook,
  type OfferInput,
} from "./lib/offer";
import { renderOfferPdf } from "./lib/offerpdf";

const input = (o: Partial<OfferInput> = {}): OfferInput => ({
  name: "Perikela Jaya Satya Sai Prakash",
  email: "student@example.com",
  letterDate: "2026-11-02",
  ref: "TD-OL-2026-0152",
  role: DEFAULT_SETTINGS.role,
  mode: "hybrid",
  months: 4,
  ...o,
});

describe("offer letter dates", () => {
  it("starts the day after the letter date and ends N months later minus a day", () => {
    expect(periodOf("2026-11-02", 4)).toEqual({ start: "2026-11-03", end: "2027-03-02" });
    expect(periodOf("2026-11-06", 4)).toEqual({ start: "2026-11-07", end: "2027-03-06" });
    expect(periodOf("2026-12-31", 1)).toEqual({ start: "2027-01-01", end: "2027-01-31" });
  });
  it("clamps month ends", () => {
    expect(addMonths("2027-01-31", 1)).toBe("2027-02-28");
  });
  it("formats long dates", () => {
    expect(longDate("2026-11-03")).toBe("3 November 2026");
  });
  it("reads spreadsheet dates in common formats", () => {
    expect(cellDate("2026-11-02")).toBe("2026-11-02");
    expect(cellDate("02-11-2026")).toBe("2026-11-02");
    expect(cellDate("2/11/2026")).toBe("2026-11-02");
    expect(cellDate("2 November 2026")).toBe("2026-11-02");
    expect(cellDate(46328)).toBe("2026-11-02"); // Excel serial
    expect(cellDate("")).toBe("");
  });
});

describe("offer letter inputs", () => {
  it("numbers refs with padding", () => {
    expect(nextRef("TD-OL-2026-0151")).toBe("TD-OL-2026-0152");
    expect(nextRef("TD-OL-2026-0999")).toBe("TD-OL-2026-1000");
  });
  it("validates", () => {
    expect(offerErrors(input())).toEqual([]);
    expect(offerErrors(input({ name: " ", letterDate: "2026-02-30", email: "x" }))).toEqual(["Name is required", "Letter date is missing or invalid", "Email looks invalid"]);
  });
  it("builds the letter and file name", () => {
    const l = buildOffer(input(), DEFAULT_SETTINGS);
    expect(l).toMatchObject({ date: "2 November 2026", start: "3 November 2026", end: "2 March 2027", duration: "4 months (16 weeks)" });
    expect(offerFileName(l)).toBe("TD-OL-2026-0152 - Perikela Jaya Satya Sai Prakash.pdf");
  });
});

describe("email draft", () => {
  it("has the subject, period and acceptance steps", () => {
    const d = emailDraft(buildOffer(input(), DEFAULT_SETTINGS));
    expect(d.to).toBe("student@example.com");
    expect(d.subject).toBe("Internship Offer Letter – Full Stack & Agentic AI Developer Intern | Tech Drona");
    expect(d.body).toContain("Internship period: 3 November 2026 to 2 March 2027 (4 months)");
    expect(d.body).toContain("Ref. No. TD-OL-2026-0152");
    expect(d.body).toContain("within 7 days of receiving this email");
    expect(d.body.trim().endsWith("https://techdrona.in/")).toBe(true);
    expect(gmailComposeUrl(d)).toContain("to=student%40example.com");
  });
});

describe("Excel bulk", () => {
  it("round-trips the template and fills blank refs and defaults", () => {
    const tpl = templateWorkbook(XLSX, DEFAULT_SETTINGS);
    const rows = parseOfferSheet(XLSX, tpl, DEFAULT_SETTINGS, "TD-OL-2026-0161");
    expect(rows).toHaveLength(1);
    expect(rows[0]).toMatchObject({ ref: "TD-OL-2026-0161", letterDate: "2026-11-02", months: 4, mode: "hybrid" });
  });
  it("reads a sheet with its own columns", () => {
    const ws = XLSX.utils.aoa_to_sheet([
      ["Full Name", "Email", "Letter date", "Ref No", "Duration (months)"],
      ["A One", "a@x.com", "06-11-2026", "", ""],
      ["B Two", "", "2026-11-12", "TD-OL-2026-0300", 6],
      ["", "", "", "", ""],
      ["C Three", "", "", "", ""],
    ]);
    const wb = XLSX.utils.book_new();
    XLSX.utils.book_append_sheet(wb, ws, "S");
    const bytes = new Uint8Array(XLSX.write(wb, { type: "array", bookType: "xlsx" }) as ArrayBuffer);
    const rows = parseOfferSheet(XLSX, bytes, DEFAULT_SETTINGS, "TD-OL-2026-0161");
    expect(rows.map((r) => [r.name, r.ref, r.letterDate, r.months])).toEqual([
      ["A One", "TD-OL-2026-0161", "2026-11-06", 4],
      ["B Two", "TD-OL-2026-0300", "2026-11-12", 6],
      ["C Three", "TD-OL-2026-0162", "", 4],
    ]);
    expect(offerErrors(rows[2]!)).toContain("Letter date is missing or invalid");
  });
  it("needs a Name column", () => {
    const wb = XLSX.utils.book_new();
    XLSX.utils.book_append_sheet(wb, XLSX.utils.aoa_to_sheet([["Student", "Email"], ["x", "y"]]), "S");
    const bytes = new Uint8Array(XLSX.write(wb, { type: "array", bookType: "xlsx" }) as ArrayBuffer);
    expect(() => parseOfferSheet(XLSX, bytes, DEFAULT_SETTINGS, "TD-OL-2026-0161")).toThrow(/Name/);
  });
});

describe("offer letter PDF", () => {
  it("renders a two-page A4 letter", async () => {
    const bytes = await renderOfferPdf(buildOffer(input(), DEFAULT_SETTINGS));
    const doc = await PDFDocument.load(bytes);
    expect(doc.getPageCount()).toBe(2);
    expect(Math.round(doc.getPage(0).getWidth())).toBe(595);
    expect(doc.getTitle()).toBe("Internship Offer Letter TD-OL-2026-0152");
  });
  it("does not throw on characters Helvetica cannot draw", async () => {
    const bytes = await renderOfferPdf(buildOffer(input({ name: "Ravi 名前 Kumar" }), DEFAULT_SETTINGS));
    expect(bytes.length).toBeGreaterThan(1000);
  });
});
