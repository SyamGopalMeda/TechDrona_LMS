/**
 * Draws the "modern corporate" internship offer letter (A4) with pdf-lib, in the browser.
 * Mirrors the HTML template used for the first batch (TD-OL-2026-0151..0160): navy band with the
 * white lockup, accent stripe, glance table, terms, HR signature, acceptance form, faint logo
 * watermark on every page and a "Page x of y" footer. Images are optional (tests run without).
 */

import { PDFDocument, StandardFonts, rgb, type PDFFont, type PDFImage, type PDFPage, type RGB } from "pdf-lib";
import type { OfferLetter } from "./offer";

export interface OfferAssets {
  /** PNG of the white lockup (header band). */
  lockup?: Uint8Array;
  /** PNG of the navy logo mark (watermark). */
  mark?: Uint8Array;
  /** PNG or JPEG of the signature. */
  signature?: { bytes: Uint8Array; type: "png" | "jpg" };
}

const MM = 72 / 25.4;
const PW = 210 * MM;
const PH = 297 * MM;
const MX = 18 * MM;
const TW = PW - 2 * MX;
const TOP = 16 * MM; // later pages
const BOTTOM = PH - 18 * MM;

const hex = (h: string): RGB => rgb(parseInt(h.slice(1, 3), 16) / 255, parseInt(h.slice(3, 5), 16) / 255, parseInt(h.slice(5, 7), 16) / 255);
const NAVY = hex("#16224a");
const ACCENT = hex("#2f6fe4");
const INK = hex("#1f2433");
const MUTED = hex("#5c6478");
const LINE = hex("#dfe3ec");
const SOFT = hex("#f4f6fb");
const WHITE = rgb(1, 1, 1);

export function offerTerms(l: Pick<OfferLetter, "company">): string[] {
  const C = l.company;
  return [
    "This offer is based on the information and documents you provided. It may be withdrawn if any of it is found to be incorrect.",
    `This internship is a training and learning engagement, not employment. It carries no salary or employment benefits, and it does not guarantee a job offer; any pre-placement offer is at the sole discretion of ${C}, based on your performance.`,
    "You will follow the program schedule shared by the program team, both for online sessions and on-site days. Leave needs prior approval from the program team; unapproved absence for more than three consecutive working days may lead to the internship being ended.",
    `You will keep confidential all information, code, data and material of ${C} and its clients, during and after the internship.`,
    `Work you create during the internship, including code, documents and designs, belongs to ${C} unless agreed otherwise in writing. You may describe your role and contribution in your résumé and portfolio without disclosing confidential material.`,
    "At the end of the internship you will return all company material and delete any company data you hold; your access to company systems will be withdrawn.",
    "You will follow our code of conduct, IT-use and anti-harassment (POSH) policies. Any concern or grievance can be raised in confidence with the HR team.",
    `Either side may end the internship with fifteen days' written notice; ${C} may end it immediately for misconduct or breach of confidentiality. The certificate is issued only when the internship is completed successfully.`,
    "This offer lapses if it is not accepted within one week (7 days) of the date this letter is emailed to you.",
  ];
}

function modeText(mode: string): string {
  return mode === "hybrid"
    ? "hybrid mode, combining live online sessions with on-site project days"
    : mode === "online"
      ? "online mode, through live online sessions"
      : `${mode} mode`;
}

export function offerParagraphs(l: OfferLetter): { intro: string; body: string[] } {
  return {
    intro: `Congratulations! We are pleased to offer you an internship with ${l.company} as ${l.role}. This letter sets out the terms of your internship.`,
    body: [
      `Your internship will run from ${l.start} to ${l.end}, a period of ${l.duration}. It will be conducted in ${modeText(l.mode)}. The schedule will be shared by the program team.`,
      "During the internship you will work on live projects under the guidance of our team. When you complete it successfully, meeting the attendance and work requirements, you will receive an internship certificate stating your role and period, which you may submit to your college for academic credit where your college allows it.",
      "To accept this offer, sign the acceptance form at the end of this letter and return a scanned copy by replying to the offer email within one week (7 days) of receiving it.",
      "We look forward to working with you and wish you a rewarding internship.",
    ],
  };
}

class Writer {
  page!: PDFPage;
  y = 0; // distance from the top
  pages: PDFPage[] = [];

  constructor(
    readonly doc: PDFDocument,
    readonly reg: PDFFont,
    readonly bold: PDFFont,
    readonly mark?: PDFImage,
  ) {}

  /** Characters Helvetica (WinAnsi) cannot draw become "?" instead of throwing. */
  safe(t: string): string {
    return Array.from(t.replace(/[‘’]/g, "'").replace(/[“”]/g, '"'))
      .map((ch) => {
        try {
          this.reg.encodeText(ch);
          return ch;
        } catch {
          return "?";
        }
      })
      .join("");
  }

  w(t: string, size: number, bold = false): number {
    return (bold ? this.bold : this.reg).widthOfTextAtSize(t, size);
  }

  newPage(first = false): void {
    this.page = this.doc.addPage([PW, PH]);
    this.pages.push(this.page);
    if (this.mark) {
      const w = 120 * MM;
      const h = (w * this.mark.height) / this.mark.width;
      this.page.drawImage(this.mark, { x: PW / 2 - w / 2, y: PH - PH * 0.52 - h / 2, width: w, height: h, opacity: 0.045 });
    }
    this.y = first ? 0 : TOP;
  }

  ensure(h: number): void {
    if (this.y + h > BOTTOM) this.newPage();
  }

  text(t: string, x: number, top: number, size: number, opts: { bold?: boolean; color?: RGB; spacing?: number; opacity?: number } = {}): number {
    const font = opts.bold ? this.bold : this.reg;
    const s = this.safe(t);
    const baseline = PH - top - size * 0.8;
    if (!opts.spacing) {
      this.page.drawText(s, { x, y: baseline, size, font, color: opts.color ?? INK, opacity: opts.opacity });
      return font.widthOfTextAtSize(s, size);
    }
    let cx = x;
    for (const ch of s) {
      this.page.drawText(ch, { x: cx, y: baseline, size, font, color: opts.color ?? INK, opacity: opts.opacity });
      cx += font.widthOfTextAtSize(ch, size) + opts.spacing;
    }
    return cx - x - opts.spacing;
  }

  spacedWidth(t: string, size: number, spacing: number, bold = false): number {
    const s = this.safe(t);
    return this.w(s, size, bold) + spacing * Math.max(0, s.length - 1);
  }

  rect(x: number, top: number, w: number, h: number, opts: { fill?: RGB; border?: RGB; bw?: number; opacity?: number }): void {
    this.page.drawRectangle({
      x,
      y: PH - top - h,
      width: w,
      height: h,
      color: opts.fill,
      borderColor: opts.border,
      borderWidth: opts.border ? (opts.bw ?? 0.75) : 0,
      opacity: opts.opacity,
    });
  }

  hline(x1: number, x2: number, top: number, color: RGB, t = 0.75): void {
    this.page.drawLine({ start: { x: x1, y: PH - top }, end: { x: x2, y: PH - top }, thickness: t, color });
  }

  wrap(t: string, size: number, width: number, bold = false): string[] {
    const words = this.safe(t).split(/\s+/).filter(Boolean);
    const lines: string[] = [];
    let cur = "";
    for (const word of words) {
      const next = cur ? `${cur} ${word}` : word;
      if (cur && this.w(next, size, bold) > width) {
        lines.push(cur);
        cur = word;
      } else cur = next;
    }
    if (cur) lines.push(cur);
    return lines;
  }

  para(t: string, opts: { size?: number; bold?: boolean; color?: RGB; gap?: number; x?: number; width?: number } = {}): void {
    const size = opts.size ?? 10.5;
    const lh = size * 1.55;
    for (const ln of this.wrap(t, size, opts.width ?? TW, opts.bold)) {
      this.ensure(lh);
      this.text(ln, opts.x ?? MX, this.y + (lh - size) / 2, size, { bold: opts.bold, color: opts.color });
      this.y += lh;
    }
    this.y += opts.gap ?? 3 * MM;
  }

  h2(t: string, underline = true): void {
    this.ensure(6 * MM + 30 + 2 * 16);
    this.y += 6 * MM;
    this.text(t.toUpperCase(), MX, this.y, 10.5, { bold: true, color: NAVY, spacing: 0.8 });
    this.y += 10.5 * 1.3 + 1.5 * MM;
    if (underline) this.hline(MX, PW - MX, this.y, LINE);
    this.y += 2.5 * MM;
  }
}

/** One offer letter as PDF bytes. */
export async function renderOfferPdf(l: OfferLetter, assets: OfferAssets = {}): Promise<Uint8Array> {
  const doc = await PDFDocument.create();
  doc.setTitle(`Internship Offer Letter ${l.ref}`);
  doc.setSubject(`Internship Offer Letter: ${l.name}`);
  doc.setAuthor(l.company);
  doc.setCreator(`${l.company} LMS`);
  doc.setProducer(`${l.company} LMS`);
  const reg = await doc.embedFont(StandardFonts.Helvetica);
  const bold = await doc.embedFont(StandardFonts.HelveticaBold);
  const lockup = assets.lockup ? await doc.embedPng(assets.lockup) : undefined;
  const mark = assets.mark ? await doc.embedPng(assets.mark) : undefined;
  const sig = assets.signature ? await (assets.signature.type === "png" ? doc.embedPng(assets.signature.bytes) : doc.embedJpg(assets.signature.bytes)) : undefined;

  const W = new Writer(doc, reg, bold, mark);
  W.newPage(true);

  // header band + stripe
  const bandH = 31 * MM;
  W.rect(0, 0, PW, bandH, { fill: NAVY });
  if (lockup) {
    const h = 13 * MM;
    const w = (h * lockup.width) / lockup.height;
    W.page.drawImage(lockup, { x: MX, y: PH - bandH / 2 - h / 2, width: w, height: h });
  } else {
    W.text(l.company.toUpperCase(), MX, bandH / 2 - 8, 16, { bold: true, color: WHITE, spacing: 1.5 });
  }
  for (const [i, line] of [l.address, l.website].entries()) {
    const t = W.safe(line);
    W.text(t, PW - MX - W.w(t, 8), bandH / 2 - 10 + i * 12, 8, { color: WHITE, opacity: 0.9 });
  }
  const stripeH = 1.6 * MM;
  const steps = 60;
  const [a, b] = [ACCENT, hex("#7aa7ff")];
  for (let i = 0; i < steps; i++) {
    const t = i / (steps - 1);
    W.rect((PW * i) / steps, bandH, PW / steps + 0.5, stripeH, { fill: rgb(a.red + (b.red - a.red) * t, a.green + (b.green - a.green) * t, a.blue + (b.blue - a.blue) * t) });
  }
  W.y = bandH + stripeH + 9 * MM;

  // ref + date
  const refW = W.text("Ref. No.", MX, W.y, 9.5, { color: MUTED });
  W.text(l.ref, MX + refW + 3, W.y, 9.5, { bold: true });
  const dateV = W.w(W.safe(l.date), 9.5, true);
  W.text(l.date, PW - MX - dateV, W.y, 9.5, { bold: true });
  W.text("Date", PW - MX - dateV - 3 - W.w("Date", 9.5), W.y, 9.5, { color: MUTED });
  W.y += 9.5 * 1.55;

  // title + accent rule
  W.y += 8 * MM;
  W.text("Internship Offer Letter", MX, W.y, 19, { bold: true, color: NAVY, spacing: 0.3 });
  W.y += 19 * 1.25 + 1 * MM;
  W.rect(MX, W.y, 18 * MM, 1.2 * MM, { fill: ACCENT });
  W.y += 1.2 * MM + 6 * MM;

  // recipient
  W.text("To,", MX, W.y, 10.5);
  W.y += 10.5 * 1.55;
  W.text(l.name, MX, W.y, 11.5, { bold: true, color: NAVY });
  W.y += 11.5 * 1.55 + 5 * MM;

  W.para(`Subject: Offer of internship: ${l.role}`, { bold: true, gap: 4 * MM });
  W.para(`Dear ${l.firstName},`);
  const { intro, body } = offerParagraphs(l);
  W.para(intro);

  // glance table: Role (full width), then Period | Duration | Mode
  W.y += 2 * MM;
  const padX = 4 * MM;
  const vLh = 9.5 * 1.4;
  const colW = TW / 3;
  const cells: [string, string][] = [
    ["Period", `${l.start} – ${l.end}`],
    ["Duration", l.duration],
    ["Mode", l.mode[0]!.toUpperCase() + l.mode.slice(1)],
  ];
  const cellLines = cells.map(([, v]) => W.wrap(v, 9.5, colW - 2 * padX, true));
  const roleLines = W.wrap(l.role, 9.5, TW - 2 * padX, true);
  const hOf = (n: number) => 3 * MM * 2 + 7 * 1.4 + 1 + n * vLh;
  const row1 = hOf(roleLines.length);
  const row2 = hOf(Math.max(...cellLines.map((c) => c.length)));
  const gTop = W.y;
  W.rect(MX, gTop, TW, row1 + row2, { fill: SOFT });
  const cell = (label: string, lines: string[], x: number, top: number) => {
    W.text(label.toUpperCase(), x + padX, top + 3 * MM, 7, { color: MUTED, spacing: 0.8 });
    lines.forEach((v, i) => W.text(v, x + padX, top + 3 * MM + 7 * 1.4 + 1 + i * vLh, 9.5, { bold: true, color: NAVY }));
  };
  cell("Role", roleLines, MX, gTop);
  cells.forEach(([label], i) => cell(label, cellLines[i]!, MX + colW * i, gTop + row1));
  W.hline(MX, PW - MX, gTop + row1, LINE);
  for (const i of [1, 2]) W.page.drawLine({ start: { x: MX + colW * i, y: PH - gTop - row1 }, end: { x: MX + colW * i, y: PH - gTop - row1 - row2 }, thickness: 0.75, color: LINE });
  W.rect(MX, gTop, TW, row1 + row2, { border: LINE });
  W.y = gTop + row1 + row2 + 6 * MM;

  for (const p of body) W.para(p);

  // terms
  W.h2("Terms and conditions");
  const indent = 5.5 * MM;
  offerTerms(l).forEach((t, i) => {
    const lines = W.wrap(t, 10.5, TW - indent);
    const lh = 10.5 * 1.55;
    W.ensure(lh * Math.min(2, lines.length));
    W.text(`${i + 1}.`, MX + indent - 4 - W.w(`${i + 1}.`, 10.5, true), W.y + (lh - 10.5) / 2, 10.5, { bold: true, color: ACCENT });
    for (const ln of lines) {
      W.ensure(lh);
      W.text(ln, MX + indent, W.y + (lh - 10.5) / 2, 10.5);
      W.y += lh;
    }
    W.y += 1.2 * MM;
  });

  // signature block (kept together)
  const sigH = 17 * MM;
  W.ensure(5 * MM + 16 + (sig ? sigH + 2 * MM : 10 * MM) + 34);
  W.y += 5 * MM;
  W.text(`For ${l.company},`, MX, W.y, 10.5);
  W.y += 10.5 * 1.55;
  if (sig) {
    const w = (sigH * sig.width) / sig.height;
    W.page.drawImage(sig, { x: MX - 1 * MM, y: PH - W.y - 1 * MM - sigH, width: w, height: sigH });
    W.y += sigH + 2 * MM;
  } else W.y += 10 * MM;
  W.text(l.signatory, MX, W.y, 10.5, { bold: true, color: NAVY });
  W.y += 10.5 * 1.55;
  W.text(l.designation, MX, W.y, 10.5);
  W.y += 10.5 * 1.55;

  // acceptance form (kept together)
  const pad = 7 * MM;
  const accText = `I, ${l.name}, have read and understood the terms of this letter (Ref. ${l.ref}) and accept the internship offer made by ${l.company}.`;
  const accLines = W.wrap(accText, 10.5, TW - 2 * pad);
  const fieldsH = 8 * MM + 2 * (8 + 6) + 8 * MM;
  const boxH = 1.4 * MM + 6 * MM + 10.5 * 1.3 + 3 * MM + accLines.length * 10.5 * 1.55 + fieldsH + 6 * MM;
  W.y += 5 * MM;
  W.ensure(boxH);
  const bTop = W.y;
  W.rect(MX, bTop, TW, boxH, { fill: WHITE, border: LINE });
  W.rect(MX, bTop, TW, 1.4 * MM, { fill: NAVY });
  let y = bTop + 1.4 * MM + 6 * MM;
  W.text("ACCEPTANCE OF OFFER", MX + pad, y, 10.5, { bold: true, color: NAVY, spacing: 0.8 });
  y += 10.5 * 1.3 + 3 * MM;
  for (const ln of accLines) {
    W.text(ln, MX + pad, y + (10.5 * 1.55 - 10.5) / 2, 10.5);
    y += 10.5 * 1.55;
  }
  y += 8 * MM;
  const fw = (TW - 2 * pad - 10 * MM) / 2;
  const labels = ["Candidate's signature", "Date", "Name", "Place"];
  labels.forEach((lab, i) => {
    const fx = MX + pad + (i % 2) * (fw + 10 * MM);
    const fy = y + Math.floor(i / 2) * (8 + 6 + 8 * MM);
    W.hline(fx, fx + fw, fy, INK, 0.75);
    W.text(lab.toUpperCase(), fx, fy + 1.2 * MM, 8, { color: MUTED, spacing: 0.6 });
  });
  W.y = bTop + boxH;

  // footers
  const n = W.pages.length;
  W.pages.forEach((p, i) => {
    W.page = p;
    const top = PH - 10 * MM;
    W.text(`${l.company} · ${l.website}`, MX, top, 7, { color: MUTED });
    const t = `Page ${i + 1} of ${n}`;
    W.text(t, PW - MX - W.w(t, 7), top, 7, { color: MUTED });
  });

  return doc.save();
}

/* ------------------------------------------------------------------ browser assets */

/** Draw an image URL (SVG or raster) onto a canvas and return PNG bytes. */
async function rasterize(src: string, widthPx: number): Promise<Uint8Array | undefined> {
  if (typeof document === "undefined") return undefined;
  const img = new Image();
  img.decoding = "async";
  img.src = src;
  try {
    await img.decode();
  } catch {
    return undefined;
  }
  const ratio = img.naturalHeight / img.naturalWidth || 1;
  const canvas = document.createElement("canvas");
  canvas.width = widthPx;
  canvas.height = Math.round(widthPx * ratio);
  const ctx = canvas.getContext("2d");
  if (!ctx) return undefined;
  ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
  const blob = await new Promise<Blob | null>((r) => canvas.toBlob(r, "image/png"));
  return blob ? new Uint8Array(await blob.arrayBuffer()) : undefined;
}

let brand: Promise<Pick<OfferAssets, "lockup" | "mark">> | undefined;

/** Logos from /brand (cached) plus the signature data URL from the settings. */
export async function loadOfferAssets(signatureDataUrl: string): Promise<OfferAssets> {
  brand ??= Promise.all([rasterize("/brand/logo-lockup-white.svg", 1400), rasterize("/brand/logo-mark-navy.svg", 1000)]).then(([lockup, mark]) => ({ lockup, mark }));
  const out: OfferAssets = { ...(await brand) };
  const m = /^data:image\/(png|jpe?g);base64,(.+)$/.exec(signatureDataUrl);
  if (m) {
    const bin = atob(m[2]!);
    const bytes = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
    out.signature = { bytes, type: m[1] === "png" ? "png" : "jpg" };
  } else {
    const local = await localSignature();
    if (local) out.signature = { bytes: local, type: "png" };
  }
  return out;
}

/** Git-ignored fallback signature (public/local/offer-signature.png, this laptop only; the repo
 * is public, so the HR signature is never committed). Used when the settings hold no signature,
 * e.g. in a new browser whose localStorage is empty. Missing file -> no signature. */
export const LOCAL_SIGNATURE_URL = "/local/offer-signature.png";

export async function localSignature(): Promise<Uint8Array | undefined> {
  try {
    const r = await fetch(LOCAL_SIGNATURE_URL);
    if (!r.ok || !(r.headers.get("content-type") ?? "").startsWith("image/png")) return undefined;
    return new Uint8Array(await r.arrayBuffer());
  } catch {
    return undefined;
  }
}
