import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import * as XLSX from "xlsx";
import { mockApi, renderWithProviders } from "@/features/auth/test/mock-api";
import { ImportStudents } from "./StudentImport";
import { UserSearch } from "./Users";
import { cellText, chunk, headerColumn, instructionRows, mergeResponses, parseStudentFile, pickSheet, recordsFromMatrix, resultMatrix, TEMPLATE_COLUMNS, whatsappLink, type ImportResponse, type ImportRowResult } from "../lib/student-import";

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn(), replace: vi.fn() }) }));

const cleanups: (() => void)[] = [];
afterEach(() => {
  while (cleanups.length) cleanups.pop()!();
});

const OPTIONS = {
  courses: [{ id: "c1", slug: "python-101", title: "Python Basics", status: "published" }],
  batches: [{ id: "b1", name: "March Batch", code: "MAR-26", course_id: null, starts_on: null, ends_on: null }],
  student_types: ["course", "internship"],
  max_rows: 500,
  email_integrated: false,
};

const result = (over: Partial<ImportRowResult>): ImportRowResult => ({
  row: 2,
  full_name: "Asha Rao",
  email: "asha@x.in",
  student_type: "course",
  status: "new",
  errors: [],
  warnings: [],
  user_id: null,
  username: null,
  temporary_password: null,
  course: { id: "c1", slug: "python-101", title: "Python Basics" },
  batch: null,
  enrolled: false,
  added_to_batch: false,
  email_status: null,
  ...over,
});

const counts = (over: Partial<ImportResponse["counts"]>): ImportResponse["counts"] => ({ total: 0, new: 0, created: 0, existing: 0, errors: 0, enrolled: 0, added_to_batch: 0, emailed: 0, ...over });

describe("student import: template parsing", () => {
  it("maps the headers people type to the template columns", () => {
    expect(headerColumn("Full Name *")).toBe("full_name");
    expect(headerColumn("E-mail")).toBe("email");
    expect(headerColumn("WhatsApp Number")).toBe("mobile");
    expect(headerColumn("Student type")).toBe("student_type");
    expect(headerColumn("Course slug")).toBe("course");
    expect(headerColumn("Start date (YYYY-MM-DD)")).toBe("start_date");
    expect(headerColumn("Notes")).toBeNull();
  });

  it("turns cells into text: dates as YYYY-MM-DD, mobile numbers without exponent", () => {
    expect(cellText(new Date(2026, 11, 1))).toBe("2026-12-01");
    expect(cellText(9876543210)).toBe("9876543210");
    expect(cellText("  Asha   Rao ")).toBe("Asha Rao");
    expect(cellText(null)).toBe("");
  });

  it("reads rows under the header, skips empty rows, keeps the spreadsheet row number", () => {
    const parsed = recordsFromMatrix([[], ["Name", "Email", "Mobile", "Notes"], ["Asha", "asha@x.in", 9876543210, "x"], ["", "", "", ""], ["Bala", "bala@x.in", "", ""]]);
    expect(parsed.missing).toEqual([]);
    expect(parsed.ignored).toEqual(["Notes"]);
    expect(parsed.rows).toEqual([
      { row: 3, full_name: "Asha", email: "asha@x.in", mobile: "9876543210" },
      { row: 5, full_name: "Bala", email: "bala@x.in" },
    ]);
    expect(recordsFromMatrix([["name", "phone"], ["A", "1"]]).missing).toEqual(["email"]);
  });

  it("picks the Students sheet, not the instructions", () => {
    expect(pickSheet(["Instructions", "Students"])).toBe("Students");
    expect(pickSheet(["Instructions", "Sheet1"])).toBe("Sheet1");
  });

  it("parses a real .xlsx (SheetJS) with date cells and the Instructions sheet first", async () => {
    const wb = XLSX.utils.book_new();
    XLSX.utils.book_append_sheet(wb, XLSX.utils.aoa_to_sheet(instructionRows(OPTIONS)), "Instructions");
    const ws = XLSX.utils.aoa_to_sheet([[...TEMPLATE_COLUMNS], ["Asha Rao", "asha@x.in", 9876543210, "internship", "python-101", "March Batch", "RVCE", "CSE", 3, new Date(2026, 11, 1), "2027-01-31"]], { cellDates: true });
    XLSX.utils.book_append_sheet(wb, ws, "Students");
    const buf = XLSX.write(wb, { type: "array", bookType: "xlsx" }) as ArrayBuffer;
    const parsed = await parseStudentFile(new File([buf], "students.xlsx"));
    expect(parsed.missing).toEqual([]);
    expect(parsed.rows).toEqual([
      { row: 2, full_name: "Asha Rao", email: "asha@x.in", mobile: "9876543210", student_type: "internship", course: "python-101", batch: "March Batch", college: "RVCE", branch: "CSE", year: "3", start_date: "2026-12-01", end_date: "2027-01-31" },
    ]);
  });

  it("parses a .csv as text (no number or date guessing)", async () => {
    const csv = "full_name,email,mobile,start_date\nAsha Rao,asha@x.in,09876543210,01-12-2026\n";
    const parsed = await parseStudentFile(new File([csv], "students.csv", { type: "text/csv" }));
    expect(parsed.rows).toEqual([{ row: 2, full_name: "Asha Rao", email: "asha@x.in", mobile: "09876543210", start_date: "01-12-2026" }]);
  });

  it("lists the courses and batches in the instructions, and the password only in the results", () => {
    const flat = instructionRows(OPTIONS).flat();
    expect(flat).toContain("python-101");
    expect(flat).toContain("March Batch");
    const m = resultMatrix([result({ status: "created", username: "td123456", temporary_password: "Ab3defGh9k" })]);
    expect(m[0]).toContain("temporary_password");
    expect(m[1]).toContain("Ab3defGh9k");
    expect(whatsappLink("98765 43210", "hi")).toBe("https://wa.me/919876543210?text=hi");
  });

  it("chunks and merges responses (counts summed, extra error rows added, sorted by row)", () => {
    expect(chunk([1, 2, 3, 4, 5], 2)).toEqual([[1, 2], [3, 4], [5]]);
    const a: ImportResponse = { dry_run: false, mode: "rows", counts: counts({ total: 1, created: 1 }), rows: [result({ row: 4, status: "created" })] };
    const b: ImportResponse = { dry_run: false, mode: "rows", counts: counts({ total: 1, existing: 1 }), rows: [result({ row: 2, status: "existing" })] };
    const m = mergeResponses([a, b], [result({ row: 3, status: "error", errors: ["x"] })]);
    expect(m.rows.map((r) => r.row)).toEqual([2, 3, 4]);
    expect(m.counts).toMatchObject({ total: 3, created: 1, existing: 1, errors: 1 });
  });
});

describe("Import students page", () => {
  it("previews the file (dry run), imports, and shows the one-time login details", async () => {
    const dry: ImportResponse = {
      dry_run: true,
      mode: "rows",
      counts: counts({ total: 2, new: 1, errors: 1 }),
      rows: [result({}), result({ row: 3, full_name: "Bala", email: "bad", status: "error", errors: ['"bad" isn\'t a valid email address.'] })],
    };
    const applied: ImportResponse = {
      dry_run: false,
      mode: "rows",
      credentials_withheld: false,
      counts: counts({ total: 1, created: 1, enrolled: 1 }),
      rows: [result({ status: "created", user_id: "u1", username: "td123456", temporary_password: "Ab3defGh9k", enrolled: true })],
    };
    const api = mockApi({
      "GET admin/students/import/options": { body: OPTIONS },
      "POST admin/students/import": (call) => ({ body: call.url.includes("dry_run=true") ? dry : applied }),
    });
    cleanups.push(api.restore);
    renderWithProviders(<ImportStudents />);
    const csv = "full_name,email,course\nAsha Rao,asha@x.in,python-101\nBala,bad,\n";
    await userEvent.upload(screen.getByLabelText("Choose the student file"), new File([csv], "students.csv", { type: "text/csv" }));

    expect(await screen.findByText('"bad" isn\'t a valid email address.')).toBeInTheDocument();
    const dryCall = api.calls.find((c) => c.method === "POST" && c.url.includes("dry_run=true"))!;
    expect((dryCall.body as { rows: unknown[] }).rows).toEqual([
      { row: 2, full_name: "Asha Rao", email: "asha@x.in", course: "python-101" },
      { row: 3, full_name: "Bala", email: "bad" },
    ]);
    // the import needs the 18+ confirmation; only the valid row is counted
    const importBtn = screen.getByRole("button", { name: "Import 1 student" });
    expect(importBtn).toBeDisabled();
    // email isn't connected: the option is off, with a note
    expect(screen.getByRole("checkbox", { name: /Email the login details/ })).toBeDisabled();
    await userEvent.click(screen.getByRole("checkbox", { name: /18 or older/ }));
    await userEvent.click(importBtn);

    expect(await screen.findByText("Ab3defGh9k")).toBeInTheDocument();
    const applyCall = api.calls.find((c) => c.method === "POST" && !c.url.includes("dry_run"))!;
    expect(applyCall.headers["idempotency-key"]).toBeTruthy();
    expect(applyCall.body).toMatchObject({ confirm_adult: true, must_change_password: true, send_email: false });
    // only the valid row is sent; the preview's error row stays in the results (once)
    expect((applyCall.body as { rows: { row: number }[] }).rows.map((r) => r.row)).toEqual([2]);
    expect(screen.getAllByText(/isn't a valid email address/)).toHaveLength(1);
    expect(screen.getByText(/Download the login details now/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Send login details" })).toBeDisabled();
    expect(screen.getByText(/Send login details works once email is connected/)).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Share login details of Asha Rao" }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByRole("link", { name: "Share on WhatsApp" }).getAttribute("href")).toContain("Ab3defGh9k");
  });

  it("imports a big file in chunks (one idempotent request per 25 rows) and merges the results", async () => {
    const n = 30;
    const preview: ImportResponse = { dry_run: true, mode: "rows", counts: counts({ total: n, new: n }), rows: Array.from({ length: n }, (_, i) => result({ row: i + 2, email: `s${i}@x.in` })) };
    const api = mockApi({
      "GET admin/students/import/options": { body: OPTIONS },
      "POST admin/students/import": (call) => {
        if (call.url.includes("dry_run=true")) return { body: preview };
        const sent = (call.body as { rows: { row: number; email: string }[] }).rows;
        return { body: { dry_run: false, mode: "rows", counts: counts({ total: sent.length, created: sent.length }), rows: sent.map((r) => result({ row: r.row, email: r.email, status: "created", username: `td${r.row}`, temporary_password: `pw${r.row}` })) } };
      },
    });
    cleanups.push(api.restore);
    renderWithProviders(<ImportStudents />);
    const csv = ["full_name,email", ...Array.from({ length: n }, (_, i) => `Student ${i},s${i}@x.in`)].join("\n");
    await userEvent.upload(screen.getByLabelText("Choose the student file"), new File([csv], "big.csv", { type: "text/csv" }));
    await userEvent.click(await screen.findByRole("checkbox", { name: /18 or older/ }));
    await userEvent.click(screen.getByRole("button", { name: `Import ${n} students` }));
    expect(await screen.findByText("pw31")).toBeInTheDocument();
    const applies = api.calls.filter((c) => c.method === "POST" && !c.url.includes("dry_run"));
    expect(applies.map((c) => (c.body as { rows: unknown[] }).rows.length)).toEqual([25, 5]);
    expect(new Set(applies.map((c) => c.headers["idempotency-key"])).size).toBe(2);
  });

  it("refuses a file without the required columns before calling the API", async () => {
    const api = mockApi({ "GET admin/students/import/options": { body: OPTIONS } });
    cleanups.push(api.restore);
    renderWithProviders(<ImportStudents />);
    await userEvent.upload(screen.getByLabelText("Choose the student file"), new File(["name,phone\nA,1\n"], "x.csv", { type: "text/csv" }));
    expect(await screen.findByText(/The file has no email column/)).toBeInTheDocument();
    expect(api.calls.some((c) => c.method === "POST")).toBe(false);
  });
});

describe("Users list: bulk enrol", () => {
  it("enrols the selected users through the import API (user_ids mode)", async () => {
    const users = [
      { user_id: "u1", display_name: "Asha", email: "a@x.in", phone_masked: null, status: "active", is_minor: false, restriction_level: 0, roles: [], created_at: "2026-11-01T00:00:00Z", last_login_at: null },
      { user_id: "u2", display_name: "Bala", email: "b@x.in", phone_masked: null, status: "active", is_minor: false, restriction_level: 0, roles: [], created_at: "2026-11-01T00:00:00Z", last_login_at: null },
    ];
    const done: ImportResponse = { dry_run: false, mode: "users", counts: counts({ total: 2, existing: 2, enrolled: 2 }), rows: [] };
    const api = mockApi({
      "GET admin/users": { body: { data: users, page: { next_cursor: null, has_more: false, limit: 25 } } },
      "GET admin/students/import/options": { body: OPTIONS },
      "POST admin/students/import": { body: done },
    });
    cleanups.push(api.restore);
    renderWithProviders(<UserSearch />);
    await userEvent.click(await screen.findByRole("checkbox", { name: "Select Asha" }));
    await userEvent.click(screen.getByRole("checkbox", { name: "Select Bala" }));
    await userEvent.click(screen.getByRole("button", { name: "Enrol in course/batch" }));
    const dialog = await screen.findByRole("dialog");
    await waitFor(() => expect(within(dialog).getByRole("option", { name: "Python Basics (python-101)" })).toBeInTheDocument());
    await userEvent.selectOptions(within(dialog).getByLabelText("Course"), "c1");
    await userEvent.click(within(dialog).getByRole("button", { name: "Enrol" }));
    await waitFor(() => expect(api.calls.some((c) => c.method === "POST" && c.path === "admin/students/import")).toBe(true));
    const call = api.calls.find((c) => c.method === "POST")!;
    expect(call.body).toMatchObject({ user_ids: ["u1", "u2"], course: "c1", batch: null });
    expect(call.headers["idempotency-key"]).toBeTruthy();
  });

  it("Add user: a student with no password gets a generated login, shown once with WhatsApp", async () => {
    const api = mockApi({
      "GET admin/users": { body: { data: [], page: { next_cursor: null, has_more: false, limit: 25 } } },
      "GET admin/students/import/options": { body: OPTIONS },
      "POST admin/users": { status: 201, body: { user_id: "u9", status: "active", role: null, must_change_password: true, username: "td654321", temporary_password: "Zx8kLmNp2q", student_type: "internship", enrolment: null } },
    });
    cleanups.push(api.restore);
    window.sessionStorage.clear();
    renderWithProviders(<UserSearch openAdd />);
    const dialog = await screen.findByRole("dialog");
    await userEvent.type(within(dialog).getByLabelText(/Full name/), "Ira Intern");
    await userEvent.type(within(dialog).getByLabelText(/^Email/), "ira@x.in");
    await userEvent.selectOptions(within(dialog).getByLabelText("Student type"), "internship");
    await userEvent.type(within(dialog).getByLabelText(/Reason/), "Summer intern");
    await userEvent.click(within(dialog).getByRole("checkbox", { name: /18 or older/ }));
    await userEvent.click(within(dialog).getByRole("button", { name: "Create account" }));
    expect(await screen.findByText("Zx8kLmNp2q")).toBeInTheDocument();
    expect(screen.getByText("td654321")).toBeInTheDocument();
    const post = api.calls.find((c) => c.method === "POST")!;
    expect(post.body).toMatchObject({ password: null, must_change_password: true, student_type: "internship", course_id: null, batch_id: null });
  });
});
