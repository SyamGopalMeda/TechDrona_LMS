import { describe, expect, it } from "vitest";
import * as XLSX from "xlsx";
import { PDFDocument } from "pdf-lib";
import { DEFAULT_SETTINGS, buildOffer, emailDraft, formatCtc, inr, offerErrors, parsePayments, paymentsText, readOfferSheet, rupees, type OfferInput } from "./lib/offer";
import { letterContent, renderOfferPdf } from "./lib/offerpdf";
import { addEntries, balance, counts, draftsHtml, generate, markSent, paidTotal, payState, registerWorkbook, removeRecords, reopen, rowErrors, setPayments, undoSent } from "./lib/register";

const S = { ...DEFAULT_SETTINGS, nextRef: "TD-OL-2026-0172", empNextRef: "TD-EO-2026-0001", empRole: "Software Developer" };

function sheet(rows: unknown[][]): Uint8Array {
  const wb = XLSX.utils.book_new();
  XLSX.utils.book_append_sheet(wb, XLSX.utils.aoa_to_sheet(rows), "S");
  return new Uint8Array(XLSX.write(wb, { type: "array", bookType: "xlsx" }) as ArrayBuffer);
}

const emp = (o: Partial<OfferInput> = {}): OfferInput => ({
  kind: "employment",
  name: "Ravi Kumar",
  email: "ravi@example.com",
  letterDate: "2026-12-01",
  ref: "TD-EO-2026-0001",
  role: "Software Developer",
  mode: "on-site",
  months: 4,
  start: "2026-12-15",
  ctc: "420000",
  probation: 6,
  location: "Vijayawada, Andhra Pradesh",
  ...o,
});

describe("offer letter register", () => {
  const upload = () =>
    readOfferSheet(
      XLSX,
      sheet([
        ["Name", "Email", "Letter type", "Letter date"],
        ["A One", "a@x.com", "", "21-11-2026"],
        ["B Two", "b@x.com", "Employment", "2026-12-01"],
        ["C Three", "", "", ""],
      ]),
      { ...S, ctc: "300000" },
    );

  it("adds uploaded rows as not generated and shows what is missing", () => {
    const { records, added } = addEntries([], upload(), S, "2026-11-22");
    expect(added).toBe(3);
    expect(records.map((r) => r.status)).toEqual(["new", "new", "new"]);
    expect(records[1]!.input).toMatchObject({ kind: "employment", ctc: "300000", ref: "" });
    expect(rowErrors(records[0]!)).toEqual([]);
    expect(rowErrors(records[2]!)).toContain("Letter date is missing or invalid");
  });

  it("generates with the next number of each series, skips invalid rows, then marks sent", () => {
    const { records } = addEntries([], upload(), S, "2026-11-22");
    const res = generate(records, records.map((r) => r.id), S, "2026-11-22");
    expect(res.generated).toHaveLength(2);
    expect(res.failed.map((f) => f.name)).toEqual(["C Three"]);
    expect(res.records[0]!.letter?.ref).toBe("TD-OL-2026-0172");
    expect(res.records[1]!.letter?.ref).toBe("TD-EO-2026-0001");
    expect(res.settings.nextRef).toBe("TD-OL-2026-0173");
    expect(res.settings.empNextRef).toBe("TD-EO-2026-0002");
    expect(res.records[0]!.letter?.signature).toBe("");
    const sent = markSent(res.records, [res.records[0]!.id], "2026-11-23");
    expect(sent[0]).toMatchObject({ status: "sent", sentOn: "2026-11-23" });
    expect(counts(sent)).toMatchObject({ all: 3, new: 1, generated: 1, sent: 1 });
    expect(undoSent(sent, [sent[0]!.id])[0]).toMatchObject({ status: "generated", sentOn: undefined });
  });

  it("never reuses a number already in the register and refuses a typed duplicate", () => {
    const base = generate(addEntries([], upload().slice(0, 1), S, "d").records, [], S, "d").records;
    const one = generate(base, [base[0]!.id], S, "d");
    // settings still at 0172 (e.g. another browser): the next letter skips to 0173
    const more = addEntries(one.records, readOfferSheet(XLSX, sheet([["Name", "Letter date"], ["D Four", "2026-11-21"]]), S), S, "d");
    const two = generate(more.records, [more.records[1]!.id], S, "d");
    expect(two.records[1]!.letter?.ref).toBe("TD-OL-2026-0173");
    const dup = addEntries(two.records, readOfferSheet(XLSX, sheet([["Name", "Letter date", "Ref No"], ["E Five", "2026-11-21", "TD-OL-2026-0172"]]), S), S, "d");
    const three = generate(dup.records, [dup.records[2]!.id], S, "d");
    expect(three.failed[0]!.errors.join()).toMatch(/already used/);
  });

  it("re-uploading the downloaded register restores statuses; plain rows do not overwrite issued letters", () => {
    const { records } = addEntries([], upload().slice(0, 2), S, "2026-11-22");
    const g = generate(records, records.map((r) => r.id), S, "2026-11-22").records;
    const s = markSent(g, [g[0]!.id], "2026-11-23");
    const bytes = registerWorkbook(XLSX, s);
    const restored = addEntries([], readOfferSheet(XLSX, bytes, S), S, "2026-11-30").records;
    expect(restored.map((r) => [r.input.name, r.status, r.letter?.ref, r.sentOn])).toEqual([
      ["A One", "sent", "TD-OL-2026-0172", "2026-11-23"],
      ["B Two", "generated", "TD-EO-2026-0001", undefined],
    ]);
    const again = addEntries(s, readOfferSheet(XLSX, sheet([["Name", "Email", "Letter date"], ["A One", "a@x.com", "2026-01-01"]]), S), S, "x");
    expect(again.records[0]).toMatchObject({ status: "sent" });
    expect(again.added + again.updated).toBe(0);
  });

  it("editing an issued letter keeps its number and sends it back to not generated; remove works", () => {
    const { records } = addEntries([], upload().slice(0, 1), S, "d");
    const g = generate(records, [records[0]!.id], S, "d").records;
    const r = reopen(g, g[0]!.id, { ...g[0]!.input, name: "A One Renamed", ref: "" });
    expect(r[0]).toMatchObject({ status: "new", letter: undefined });
    expect(r[0]!.input).toMatchObject({ name: "A One Renamed", ref: "TD-OL-2026-0172" });
    expect(removeRecords(r, [r[0]!.id])).toEqual([]);
  });

  it("builds an offline drafts page with copy buttons and the attachment path", () => {
    const l = buildOffer(emp(), S);
    const html = draftsHtml([{ letter: l, folder: "1 To Send" }]);
    expect(html).toContain("ravi@example.com");
    expect(html).toContain("1 To Send/TD-EO-2026-0001 - Ravi Kumar.pdf");
    expect(html).toContain("data-c=");
  });
});

describe("employment offer letter", () => {
  it("validates CTC and probation", () => {
    expect(offerErrors(emp())).toEqual([]);
    expect(offerErrors(emp({ ctc: "" }))).toContain("Annual CTC is required");
    expect(offerErrors(emp({ probation: 13 }))).toContain("Probation must be 0 to 12 months");
    expect(offerErrors(emp({ role: "" }))).toContain("Position is required");
  });

  it("formats CTC with Indian grouping and keeps free text", () => {
    expect(formatCtc("420000")).toBe("₹4,20,000 per annum");
    expect(formatCtc("Rs 1,200,000")).toBe("₹12,00,000 per annum");
    expect(formatCtc("₹30,000 per month")).toBe("₹30,000 per month");
  });

  it("has its own wording, email and a two-page PDF", async () => {
    const l = buildOffer(emp(), S);
    expect(l).toMatchObject({ start: "15 December 2026", ctc: "₹4,20,000 per annum", probation: "6 months" });
    const c = letterContent(l);
    expect(c.title).toBe("Employment Offer Letter");
    expect(c.cells.map((x) => x[0])).toEqual(["Date of joining", "Annual CTC", "Location"]);
    expect(c.body.join(" ")).toContain("probation for 6 months");
    expect(c.acceptance).toContain("I will join on 15 December 2026");
    const noProb = letterContent(buildOffer(emp({ probation: 0 }), S));
    expect(noProb.body.join(" ")).not.toContain("probation");
    const d = emailDraft(l);
    expect(d.subject).toBe("Employment Offer Letter – Software Developer | Tech Drona");
    expect(d.body).toContain("- Annual CTC: ₹4,20,000 per annum");
    const doc = await PDFDocument.load(await renderOfferPdf(l));
    expect(doc.getTitle()).toBe("Employment Offer Letter TD-EO-2026-0001");
    expect(doc.getPageCount()).toBeGreaterThanOrEqual(1);
  });

  it("joining date defaults to the day after the letter date", () => {
    expect(buildOffer(emp({ start: undefined }), S).start).toBe("2 December 2026");
  });

  it("leaves the internship wording as it was", () => {
    const l = buildOffer({ name: "A One", email: "", letterDate: "2026-11-21", ref: "TD-OL-2026-0172", role: S.role, mode: "hybrid", months: 4 }, S);
    const c = letterContent(l);
    expect(c.title).toBe("Internship Offer Letter");
    expect(c.subject).toBe(`Subject: Offer of internship: ${S.role}`);
    expect(c.cells).toEqual([
      ["Period", "22 November 2026 – 21 March 2027"],
      ["Duration", "4 months (16 weeks)"],
      ["Mode", "Hybrid"],
    ]);
    expect(c.acceptance).toBe("I, A One, have read and understood the terms of this letter (Ref. TD-OL-2026-0172) and accept the internship offer made by Tech Drona.");
  });
});


describe("candidate payments", () => {
  it("reads fee and part payments from the sheet and works out the balance", () => {
    const entries = readOfferSheet(
      XLSX,
      sheet([
        ["Student Name", "Letter date", "Amount (₹)", "Paid on", "Total fee"],
        ["A One", "2026-11-02", "2,500", "02-11-2026", ""],
        ["B Two", "2026-11-02", 5000, "2026-11-02", 5000],
        ["C Three", "2026-11-02", "", "", 3000],
        ["D Four", "2026-11-02", "", "", ""],
      ]),
      S,
    );
    const { records } = addEntries([], entries, S, "d");
    expect(records.map((r) => [payState(r), paidTotal(r), balance(r)])).toEqual([
      ["part", 2500, 2500],
      ["paid", 5000, 0],
      ["unpaid", 0, 3000],
      ["unpaid", 0, 5000],
    ]);
    expect(records[0]!.payments).toEqual([{ date: "2026-11-02", amount: 2500 }]);
    expect(counts(records).due).toBe(3);
  });

  it("keeps every payment through the downloaded register, and a payments sheet updates issued letters", () => {
    const { records } = addEntries([], readOfferSheet(XLSX, sheet([["Name", "Letter date"], ["A One", "2026-11-02"]]), S), S, "d");
    const g = generate(records, [records[0]!.id], S, "d").records;
    const withPay = setPayments(g, g[0]!.id, 5000, [
      { date: "2026-11-20", amount: 2000, note: "UPI 998" },
      { date: "2026-11-02", amount: 2500 },
    ]);
    expect(withPay[0]!.payments!.map((p) => p.date)).toEqual(["2026-11-02", "2026-11-20"]);
    const text = paymentsText(withPay[0]!.payments!);
    expect(text).toBe("2026-11-02: ₹2,500; 2026-11-20: ₹2,000 (UPI 998)");
    expect(parsePayments(text)).toEqual(withPay[0]!.payments);
    const back = addEntries([], readOfferSheet(XLSX, registerWorkbook(XLSX, withPay), S), S, "x").records;
    expect(back[0]).toMatchObject({ status: "generated", fee: 5000 });
    expect(balance(back[0]!)).toBe(500);
    // a later plain sheet with only a payment column updates the issued letter's payments
    const upd = addEntries(withPay, readOfferSheet(XLSX, sheet([["Name", "Letter date", "Amount paid", "Paid on"], ["A One", "2026-11-02", 5000, "2026-11-25"]]), S), S, "y");
    expect(upd.updated).toBe(1);
    expect(upd.records[0]).toMatchObject({ status: "generated", payments: [{ date: "2026-11-25", amount: 5000 }] });
  });

  it("formats rupees and parses amounts", () => {
    expect(inr(2500)).toBe("₹2,500");
    expect(inr(125000)).toBe("₹1,25,000");
    expect(rupees("Rs. 2,500")).toBe(2500);
    expect(rupees("₹3000")).toBe(3000);
    expect(Number.isNaN(rupees("abc"))).toBe(true);
  });
});
