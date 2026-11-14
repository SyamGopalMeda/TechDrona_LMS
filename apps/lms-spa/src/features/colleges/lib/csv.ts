/**
 * CSV export (port of the old js/ui/components.js csvCell / csvRow / downloadCsv).
 *
 * SEC-02: every text cell that starts with = + - @ TAB or CR gets a leading ' so a spreadsheet never runs it as a
 * formula; real numbers (including negatives) are written as numbers. UTF-8 with a BOM so Excel shows Telugu / ₹.
 *
 *   downloadCsv("colleges.csv", [["Name", "Target"], ["ABC", 12]]);
 *   downloadCsv("colleges.csv", { headers: ["Name"], rows: [["ABC"]] });
 */

export type CsvValue = string | number | boolean | null | undefined | object;

export function csvCell(v: CsvValue): string {
  if (v === null || v === undefined) return "";
  if (typeof v === "number") return Number.isFinite(v) ? String(v) : "";
  let s = typeof v === "object" ? JSON.stringify(v) : String(v);
  if (/^[=+\-@\t\r]/.test(s)) s = `'${s}`;
  return /[",\r\n]/.test(s) || /^\s|\s$/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}

export const csvRow = (cells: readonly CsvValue[]): string => cells.map(csvCell).join(",");

/** The file text (BOM + CRLF lines). */
export function csvText(rows: readonly (readonly CsvValue[])[]): string {
  return `﻿${rows.map(csvRow).join("\r\n")}`;
}

/** Download `rows` (first row = headers) or `{headers, rows}` as a CSV file. */
export function downloadCsv(filename: string, data: readonly (readonly CsvValue[])[] | { headers: readonly CsvValue[]; rows: readonly (readonly CsvValue[])[] }): void {
  const rows = Array.isArray(data) ? (data as readonly (readonly CsvValue[])[]) : [(data as { headers: readonly CsvValue[] }).headers, ...(data as { rows: readonly (readonly CsvValue[])[] }).rows];
  const url = URL.createObjectURL(new Blob([csvText(rows)], { type: "text/csv;charset=utf-8" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.style.display = "none";
  document.body.append(a);
  a.click();
  setTimeout(() => {
    URL.revokeObjectURL(url);
    a.remove();
  }, 1000);
}
