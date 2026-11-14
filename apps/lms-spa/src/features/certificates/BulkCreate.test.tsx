import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { mockApi, renderWithProviders } from "@/features/auth/test/mock-api";
import { CreateTab } from "./components/AdminDocuments";
import { buildResults, buildTemplate, issueInChunks, loadXlsx, rowBody, rowsFromTable, toIsoDate, withCommon, type BulkIssueResult, type BulkRow } from "./lib/bulk";
import type { DocTypeDef } from "./lib/docs";
import { crc32, makeZip } from "./lib/zip";

vi.setConfig({ testTimeout: 30000 });
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn(), replace: vi.fn(), refresh: vi.fn() }), usePathname: () => "/admin/certificates" }));

const cleanups: (() => void)[] = [];
afterEach(() => {
  while (cleanups.length) cleanups.pop()!();
  vi.restoreAllMocks();
});

const internship: DocTypeDef = {
  key: "cert_internship",
  label: "Internship certificate",
  short: "Internship certificate",
  layout: "certificate",
  prefix: "IC",
  fields: [
    { key: "role", label: "Internship role / track", kind: "text", required: true, hint: "e.g. Full Stack Development Intern" },
    { key: "start_date", label: "Start date", kind: "date", required: true },
    { key: "end_date", label: "End date", kind: "date" },
    { key: "mode", label: "Mode", kind: "select", options: ["Online", "On-site", "Hybrid"], required: true },
  ],
  paragraphs: ["This is to certify that"],
  sections: null,
  email_key: "cert_internship",
};
const types = { types: [internship], emails: [], settings_problem: null };

describe("bulk documents: spreadsheet helpers", () => {
  it("maps headers by label, key or alias and normalises dates and choices", () => {
    const table = [
      ["Tech Drona interns"],
      ["Name", "E-mail", "Phone", "Internship role / track", "start_date", "End date", "MODE", "Shoe size"],
      ["Ananya Reddy", "ananya@example.test", "+91 98765 43210", "Full Stack Intern", "01/12/2026", 46387, "online", "7"],
      ["", "", "", "", "", "", "", ""],
      ["Ravi Kumar", "ravi@example.test", 919876543210, "Data Intern", "2026-1-5", "5 March 2027", "Hybrid", ""],
    ];
    const parsed = rowsFromTable(null, internship, table);
    expect(parsed.unknown).toEqual(["Shoe size"]);
    expect(parsed.missingColumns).toEqual([]);
    expect(parsed.rows).toHaveLength(2);
    expect(parsed.rows[0]).toMatchObject({ row: 3, name: "Ananya Reddy", email: "ananya@example.test", mobile: "+91 98765 43210", fields: { role: "Full Stack Intern", start_date: "2026-12-01", mode: "Online" } });
    expect(parsed.rows[1]).toMatchObject({ row: 5, mobile: "919876543210", fields: { start_date: "2026-01-05", end_date: "2027-03-05", mode: "Hybrid" } });
    // an Excel serial date without SheetJS stays as typed (the server reports it)
    expect(parsed.rows[0]!.fields.end_date).toBe("46387");
    expect(rowsFromTable(null, internship, [["Role"], ["x"]]).missingColumns).toEqual(["Student name", "Student email"]);
  });

  it("converts Excel serial dates with SheetJS and round-trips the template", async () => {
    const x = await loadXlsx();
    expect(toIsoDate(x, 46357)).toBe("2026-12-01");
    const bytes = buildTemplate(x, internship);
    const wb = x.read(bytes, { type: "array" });
    expect(wb.SheetNames).toEqual(["Documents", "Instructions"]);
    const table = x.utils.sheet_to_json<unknown[]>(wb.Sheets.Documents!, { header: 1, raw: true, defval: "" });
    expect(table[0]).toEqual(["Student name", "Student email", "Mobile", "College", "Registration no.", "Internship role / track", "Start date", "End date", "Mode"]);
    const parsed = rowsFromTable(x, internship, table);
    expect(parsed.rows[0]).toMatchObject({ name: "Ananya Reddy", fields: { role: "Full Stack Development Intern", start_date: "2026-12-01", mode: "Online" } });
    const help = x.utils.sheet_to_json<unknown[]>(wb.Sheets.Instructions!, { header: 1, raw: true, defval: "" });
    expect(help.some((r) => r[0] === "Mode" && r[1] === "Yes" && String(r[2]).includes("Online, On-site, Hybrid"))).toBe(true);
  });

  it("fills empty cells from the common details and drops the enrolment for completion certificates", () => {
    const rows: BulkRow[] = [{ row: 2, name: "A", email: "a@x.test", fields: { mode: "Hybrid", role: "" }, enrolment_id: "e1" }];
    expect(withCommon(rows, { mode: "Online", role: "Intern", end_date: "" })[0]!.fields).toEqual({ mode: "Hybrid", role: "Intern" });
    expect(rowBody(rows[0]!, "cert_completion").enrolment_id).toBeUndefined();
    expect(rowBody(rows[0]!, "cert_internship").enrolment_id).toBe("e1");
  });

  it("issues in chunks, re-sends deferred rows, retries a network failure with the same key and stops on a refusal", async () => {
    const rows: BulkRow[] = Array.from({ length: 5 }, (_, i) => ({ row: i + 2, name: `P${i}`, email: `p${i}@x.test`, fields: {} }));
    const keys: string[] = [];
    let n = 0;
    let failedOnce = false;
    const send = vi.fn(async (chunk: BulkRow[], key: string): Promise<BulkIssueResult> => {
      keys.push(key);
      if (chunk.some((r) => r.row === 4) && !failedOnce) {
        failedOnce = true;
        throw new Error("network");
      }
      const results = chunk.map((r, i) => (n === 0 && i === 1 ? { row: r.row, status: "deferred" as const } : { row: r.row, status: "issued" as const, ref_no: `TD-IC-2026-${r.row}` }));
      n++;
      return { bulk_id: "b", doc_type: "cert_internship", issued: 0, failed: 0, deferred: 0, results };
    });
    const progress = vi.fn();
    let k = 0;
    const out = await issueInChunks(rows, send, progress, { size: 2, newKey: () => `k${k++}`, retryable: () => true });
    expect(out.stopped).toBeNull();
    expect(out.results.map((r) => r.status)).toEqual(["issued", "issued", "issued", "issued", "issued"]);
    // chunk 1 = rows 2,3 (3 deferred); chunk 2 = rows 3,4 -> network error, retried with the same key
    expect(keys.slice(1, 3)).toEqual(["k1", "k1"]);
    expect(progress).toHaveBeenLastCalledWith({ done: 5, total: 5, issued: 5, failed: 0 });

    const refused = await issueInChunks(rows, async () => Promise.reject(new Error("settings")), () => undefined, { size: 2 });
    expect(refused.stopped).toBeInstanceOf(Error);
    expect(refused.results.every((r) => r.status === "failed")).toBe(true);
  });

  it("writes a valid stored ZIP and a results sheet with references and links", async () => {
    expect(crc32(new TextEncoder().encode("123456789"))).toBe(0xcbf43926);
    const z = makeZip([
      { name: "a.pdf", data: new Uint8Array([1, 2, 3]) },
      { name: "a.pdf", data: new Uint8Array([4]) },
    ]);
    const view = new DataView(z.buffer);
    expect(view.getUint32(0, true)).toBe(0x04034b50);
    const end = z.length - 22;
    expect(view.getUint32(end, true)).toBe(0x06054b50);
    expect(view.getUint16(end + 10, true)).toBe(2);
    expect(new TextDecoder().decode(z)).toContain("a (2).pdf");

    const x = await loadXlsx();
    const rows: BulkRow[] = [
      { row: 2, name: "Ananya", email: "a@x.test", mobile: "+91 1", fields: {} },
      { row: 3, name: "Ravi", email: "r@x.test", fields: {} },
    ];
    const bytes = buildResults(x, internship, rows, [
      { row: 2, status: "issued", ref_no: "TD-IC-2026-AAAAAA", verify_url: "/verify/TD-IC-2026-AAAAAA", email_status: null },
      { row: 3, status: "failed", error: "Fill in: Start date." },
    ]);
    const wb = x.read(bytes, { type: "array" });
    const t = x.utils.sheet_to_json<unknown[]>(wb.Sheets[wb.SheetNames[0]!]!, { header: 1, raw: true, defval: "" });
    expect(t[1]).toEqual([2, "Ananya", "a@x.test", "+91 1", "Issued", "TD-IC-2026-AAAAAA", "http://localhost:3000/verify/TD-IC-2026-AAAAAA", "Not emailed", ""]);
    expect(t[2]![4]).toBe("Not issued");
    expect(t[2]![8]).toContain("Start date");
  });
});

describe("bulk documents: Create & send > Bulk", () => {
  it("uploads a CSV, shows row checks, requires a preview, issues with an idempotency key and shows the run", async () => {
    const bulkId = "0198f3a1-0000-7000-8000-000000000001";
    vi.spyOn(crypto, "randomUUID").mockReturnValue(bulkId as `${string}-${string}-${string}-${string}-${string}`);
    const open = vi.spyOn(window, "open").mockReturnValue(null);
    const createUrl = vi.fn(() => "blob:preview");
    Object.assign(URL, { createObjectURL: createUrl, revokeObjectURL: vi.fn() });
    const validated = {
      doc_type: "cert_internship",
      total: 2,
      ok: 1,
      failed: 1,
      settings_problem: null,
      email_ready: false,
      auto_send: false,
      rows: [
        { row: 2, name: "Ananya Reddy", email: "ananya@example.test", ok: true, errors: [], missing: [], warnings: [], fields: {} },
        { row: 3, name: "Ravi Kumar", email: "ravi@example.test", ok: false, errors: ["Start date: use a date (YYYY-MM-DD)."], missing: [], warnings: [] },
      ],
    };
    const runDoc = {
      id: "d1", doc_type: "cert_internship", label: "Internship certificate", short: "Internship certificate", layout: "certificate", ref_no: "TD-IC-2026-AAAAAA",
      recipient: { name: "Ananya Reddy", email: "ananya@example.test" }, title: null, user_id: null, enrolment_id: null, course_id: null, fields: {}, subject: null,
      issue_date: "2026-11-14", status: "valid", origin: "manual", replaces_id: null, superseded_by_id: null, revoked_at: null, revoke_reason: null, pdf_available: true,
      content_sha256: null, template_version: "x", verify_url: "/verify/TD-IC-2026-AAAAAA", created_at: null, email_status: null, bulk_id: bulkId, bulk_row: 2,
    };
    const api = mockApi({
      "GET admin/documents/types": { body: types },
      "POST admin/documents/bulk/validate": { body: validated },
      "POST admin/documents/preview": { body: { pdf_base64: "JVBERg==", missing: [], leftovers: [], settings_problem: null, subject: "" } },
      "POST admin/documents/bulk/issue": (call) => ({
        body: {
          bulk_id: bulkId,
          doc_type: "cert_internship",
          issued: 1,
          failed: 0,
          deferred: 0,
          results: (call.body as { rows: { row: number }[] }).rows.map((r) => ({ row: r.row, status: "issued", document_id: "d1", ref_no: "TD-IC-2026-AAAAAA", verify_url: "/verify/TD-IC-2026-AAAAAA", name: "Ananya Reddy", email_status: null })),
        },
      }),
      [`GET admin/documents/bulk/${bulkId}`]: { body: { bulk_id: bulkId, data: [runDoc], counts: { valid: 1 } } },
    });
    cleanups.push(api.restore);
    const onIssued = vi.fn();
    const onChanged = vi.fn();
    renderWithProviders(<CreateTab onIssued={onIssued} onChanged={onChanged} />);
    await userEvent.click(await screen.findByRole("radio", { name: /Bulk/ }));
    const input = await screen.findByLabelText(/Upload filled file/);
    await waitFor(() => expect(input).not.toBeDisabled());
    const csv = "Student name,Student email,Internship role / track,Start date,Mode\nAnanya Reddy,ananya@example.test,Full Stack Intern,01/12/2026,online\nRavi Kumar,ravi@example.test,Data Intern,soon,Online\n";
    await userEvent.upload(input, new File([csv], "interns.csv", { type: "text/csv" }));

    await waitFor(() => expect(api.calls.some((c) => c.path === "admin/documents/bulk/validate")).toBe(true));
    const sent = api.calls.find((c) => c.path === "admin/documents/bulk/validate")!.body as { doc_type: string; rows: { row: number; fields: Record<string, string> }[] };
    expect(sent.doc_type).toBe("cert_internship");
    expect(sent.rows[0]).toMatchObject({ row: 2, name: "Ananya Reddy", fields: { role: "Full Stack Intern", start_date: "2026-12-01", mode: "Online" } });

    const table = await screen.findByRole("table", { name: "Rows to issue" });
    expect(within(table).getByText("OK")).toBeInTheDocument();
    expect(within(table).getByText("Start date: use a date (YYYY-MM-DD).")).toBeInTheDocument();
    expect(screen.getByRole("note")).toHaveTextContent(/Email isn.t connected yet/);
    const issue = screen.getByRole("button", { name: "Issue 1 document" });
    expect(issue).toBeDisabled();
    expect(screen.getByText("Preview at least one document first.")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Preview row 2" }));
    await waitFor(() => expect(open).toHaveBeenCalledWith("blob:preview", "_blank", "noopener,noreferrer"));
    expect(api.calls.find((c) => c.path === "admin/documents/preview")!.body).toMatchObject({ doc_type: "cert_internship", recipient: { name: "Ananya Reddy", email: "ananya@example.test" } });
    await waitFor(() => expect(issue).not.toBeDisabled());

    await userEvent.click(issue);
    await userEvent.click(await screen.findByRole("button", { name: "Issue documents" }));
    expect(await screen.findByText("1 internship certificate issued")).toBeInTheDocument();
    const call = api.calls.find((c) => c.path === "admin/documents/bulk/issue")!;
    expect(call.headers["idempotency-key"]).toBeTruthy();
    expect(call.body).toMatchObject({ doc_type: "cert_internship", bulk_id: bulkId, label: "interns.csv", email: "none" });
    expect((call.body as { rows: unknown[] }).rows).toHaveLength(1); // the row with a problem is skipped
    expect(onChanged).toHaveBeenCalled();
    expect(onIssued).not.toHaveBeenCalled();
    expect(await screen.findByRole("link", { name: "TD-IC-2026-AAAAAA" })).toHaveAttribute("href", "/verify/TD-IC-2026-AAAAAA");
    expect(screen.getByRole("table", { name: "Rows not issued" })).toHaveTextContent("Skipped: the row had problems when checked.");
    expect(screen.getByRole("button", { name: "Download all PDFs (ZIP)" })).not.toBeDisabled();
  });
});
