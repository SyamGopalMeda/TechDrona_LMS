import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { mockApi, renderWithProviders } from "@/features/auth/test/mock-api";
import { CertificateVerification } from "@/features/catalog/components/CertificateVerification";
import { AdminCertificates } from "./components/AdminCertificates";
import { CreateTab, DocSettingsTab, RegisterTab, TemplatesTab } from "./components/AdminDocuments";
import { missingFields, toLines, type DocTypeDef } from "./lib/docs";
import { outboxItem, type OutboxRow } from "./lib/types";

vi.setConfig({ testTimeout: 20000 });
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn(), replace: vi.fn(), refresh: vi.fn() }), usePathname: () => "/admin/certificates" }));

const cleanups: (() => void)[] = [];
afterEach(() => {
  while (cleanups.length) cleanups.pop()!();
});

const admission: DocTypeDef = {
  key: "offer_course",
  label: "Course admission letter",
  short: "Admission letter",
  layout: "letter",
  prefix: "AL",
  fields: [
    { key: "program", label: "Program / course", kind: "text", required: true },
    { key: "batch_start", label: "Batch start date", kind: "date", required: true },
    { key: "duration", label: "Duration", kind: "text", required: true },
    { key: "mode", label: "Mode", kind: "select", options: ["Online", "On-site", "Hybrid"], required: true },
  ],
  paragraphs: ["Dear {{first_name}},"],
  sections: { hero: "Congratulations", benefits: [], terms: ["T1"], next: [], accept: false },
  email_key: "offer_course",
};
const lor: DocTypeDef = { ...admission, key: "lor", label: "Letter of recommendation", short: "Recommendation (LOR)", prefix: "LR", fields: [{ key: "relationship", label: "How we know the student", kind: "text", required: true }], sections: null };
const types = { types: [admission, lor], emails: [], settings_problem: null };
const doc = {
  id: "d1",
  doc_type: "offer_course",
  label: "Course admission letter",
  short: "Admission letter",
  layout: "letter",
  ref_no: "TD-AL-2026-7K3QX9",
  recipient: { name: "Ananya Reddy", email: "ananya@example.test" },
  title: "Full Stack",
  user_id: null,
  enrolment_id: null,
  course_id: null,
  fields: { program: "Full Stack", batch_start: "2026-12-01", duration: "16 weeks", mode: "Online" },
  subject: "Admission confirmed: Full Stack",
  issue_date: "2026-11-11",
  status: "valid",
  origin: "manual",
  replaces_id: null,
  superseded_by_id: null,
  revoked_at: null,
  revoke_reason: null,
  pdf_available: true,
  content_sha256: "ab",
  template_version: "doc-letter-v1",
  verify_url: "/verify/TD-AL-2026-7K3QX9",
  created_at: "2026-11-11T10:00:00Z",
  email_status: "sent",
};
const page = (data: unknown[]) => ({ data, page: { next_cursor: null, has_more: false, limit: 25 }, counts: { valid: 1, revoked: 0, superseded: 0 } });

describe("Certificates & documents: create and send", () => {
  it("renders the fields of the chosen type, blocks issuing until required details are filled, then issues", async () => {
    const api = mockApi({
      "GET admin/documents/types": { body: types },
      "POST admin/documents": { status: 201, body: doc },
    });
    cleanups.push(api.restore);
    const onIssued = vi.fn();
    renderWithProviders(<CreateTab onIssued={onIssued} />);
    const issue = await screen.findByRole("button", { name: "Issue & send" });
    expect(await screen.findByLabelText(/Batch start date/)).toBeInTheDocument();
    expect(issue).toBeDisabled();
    await userEvent.type(screen.getByLabelText(/Student name/), "Ananya Reddy");
    await userEvent.type(screen.getByLabelText(/Student email/), "ananya@example.test");
    await userEvent.type(screen.getByLabelText(/Program \/ course/), "Full Stack");
    await userEvent.type(screen.getByLabelText(/Batch start date/), "2026-12-01");
    await userEvent.type(screen.getByLabelText(/^Duration/), "16 weeks");
    await userEvent.selectOptions(screen.getByLabelText(/^Mode/), "Online");
    await waitFor(() => expect(issue).not.toBeDisabled());
    await userEvent.click(issue);
    await waitFor(() => expect(onIssued).toHaveBeenCalled());
    const call = api.calls.find((c) => c.method === "POST" && c.path === "admin/documents");
    expect(call?.headers["idempotency-key"]).toBeTruthy();
    expect(call?.body).toMatchObject({ doc_type: "offer_course", email: "send", recipient: { name: "Ananya Reddy", email: "ananya@example.test" }, fields: { program: "Full Stack", batch_start: "2026-12-01", duration: "16 weeks", mode: "Online" } });
  });

  it("switching type shows that type's fields", async () => {
    const api = mockApi({ "GET admin/documents/types": { body: types } });
    cleanups.push(api.restore);
    renderWithProviders(<CreateTab onIssued={vi.fn()} />);
    await screen.findByLabelText(/Batch start date/);
    await userEvent.selectOptions(screen.getByLabelText(/^Type/), "lor");
    expect(await screen.findByLabelText(/How we know the student/)).toBeInTheDocument();
    expect(screen.queryByLabelText(/Batch start date/)).not.toBeInTheDocument();
  });
});

describe("Certificates & documents: register", () => {
  it("lists documents with a verify link and revokes with a reason", async () => {
    const api = mockApi({
      "GET admin/documents/types": { body: types },
      "GET admin/documents": { body: page([doc]) },
      "POST admin/documents/d1/revoke": { body: { ...doc, status: "revoked" } },
    });
    cleanups.push(api.restore);
    renderWithProviders(<RegisterTab onChanged={vi.fn()} />);
    expect(await screen.findByText("Ananya Reddy")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "TD-AL-2026-7K3QX9" })).toHaveAttribute("href", "/verify/TD-AL-2026-7K3QX9");
    await userEvent.click(screen.getByRole("button", { name: "Revoke TD-AL-2026-7K3QX9" }));
    const dialog = await screen.findByRole("dialog");
    await userEvent.type(within(dialog).getByLabelText(/Reason/), "Issued in error");
    await userEvent.click(within(dialog).getByRole("button", { name: "Revoke document" }));
    await waitFor(() => expect(api.calls.find((c) => c.path === "admin/documents/d1/revoke")?.body).toEqual({ reason: "Issued in error", public_reason: false }));
  });
});

describe("Certificates & documents: templates and settings", () => {
  it("saves edited paragraphs and letter sections", async () => {
    const api = mockApi({
      "GET admin/documents/templates": {
        body: {
          documents: { offer_course: { label: "Course admission letter", default: { paragraphs: ["Dear {{first_name}},", "Welcome."], sections: { hero: "Hi", benefits: ["B1"], terms: ["T1"], next: [], accept: false } }, override: null } },
          emails: { offer_course: { label: "Course admission", attach: "offer_course", default: { subject: "S", body: "B" }, override: null } },
        },
      },
      "PUT admin/documents/templates/document/offer_course": { body: { kind: "document", key: "offer_course", override: {} } },
    });
    cleanups.push(api.restore);
    renderWithProviders(<TemplatesTab />);
    const paras = await screen.findByLabelText(/Paragraphs/);
    await waitFor(() => expect(paras).toHaveValue("Dear {{first_name}},\n\nWelcome."));
    await userEvent.click(screen.getByRole("button", { name: "Save wording" }));
    await waitFor(() =>
      expect(api.calls.find((c) => c.method === "PUT")?.body).toEqual({
        content: { paragraphs: ["Dear {{first_name}},", "Welcome."], sections: { hero: "Hi", benefits: ["B1"], terms: ["T1"], next: [], accept: false } },
      }),
    );
  });

  it("saves the letterhead and signatory", async () => {
    const settings = { company: "Tech Drona", legal_name: "", tagline: "Debug your career. Deploy your dreams.", address: "", phone: "", email: "", website: "", reg_lines: [], signatory: "", designation: "", signatory_email: "", signatory_phone: "", signatory2: "", designation2: "", portal_url: "", auto_admission_letter: true, images: { signature: false, seal: false, signature2: false, logo_left: false, logo_right: false }, problem: "Add the signatory's name and designation in Documents → Settings.", auto_send: false };
    const api = mockApi({ "GET admin/documents/settings": { body: settings }, "PUT admin/documents/settings": { body: { ...settings, problem: null } } });
    cleanups.push(api.restore);
    renderWithProviders(<DocSettingsTab onChanged={vi.fn()} />);
    expect(await screen.findByText(/Add the signatory's name/)).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText(/Signatory name/), "A Signatory");
    await userEvent.type(screen.getByLabelText(/Signatory designation/), "Director");
    await userEvent.click(screen.getByRole("button", { name: "Save settings" }));
    await waitFor(() => expect(api.calls.find((c) => c.method === "PUT")?.body).toMatchObject({ signatory: "A Signatory", designation: "Director", auto_admission_letter: true, watermark: true, reg_lines: [] }));
  });

  it("switches the Tech Drona watermark off", async () => {
    const settings = { company: "Tech Drona", legal_name: "", tagline: "", address: "", phone: "", email: "", website: "", reg_lines: [], signatory: "A", designation: "B", signatory_email: "", signatory_phone: "", signatory2: "", designation2: "", portal_url: "", auto_admission_letter: true, watermark: true, images: { signature: false, seal: false, signature2: false, logo_left: false, logo_right: false }, problem: null, auto_send: false };
    const api = mockApi({ "GET admin/documents/settings": { body: settings }, "PUT admin/documents/settings": { body: { ...settings, watermark: false } } });
    cleanups.push(api.restore);
    renderWithProviders(<DocSettingsTab onChanged={vi.fn()} />);
    const box = await screen.findByRole("checkbox", { name: /Show Tech Drona watermark on documents/ });
    await waitFor(() => expect(box).toBeChecked());
    await userEvent.click(box);
    await userEvent.click(screen.getByRole("button", { name: "Save settings" }));
    await waitFor(() => expect(api.calls.find((c) => c.method === "PUT")?.body).toMatchObject({ watermark: false }));
  });
});

describe("Certificates & documents: page and helpers", () => {
  it("shows the new tabs and lists document emails in the approval queue", async () => {
    const summary = { issued: 0, valid: 0, revoked: 0, without_pdf: 0, due: 0, due_eligible: 0, outbox: { awaiting: 1, pending: 0, sent: 0, failed: 0, cancelled: 0 }, auto_send: false, documents: { valid: 3, revoked: 0, superseded: 0 } };
    const row = { id: "o9", status: "awaiting", origin: "enrolment", attempts: 0, last_error: null, approved_at: null, sent_at: null, cancelled_at: null, created_at: "2026-11-11T10:00:00Z", certificate: null, item: { kind: "document", id: "d1", name: "Ananya Reddy", email: "ananya@example.test", title: "Full Stack", label: "Admission letter", number: "TD-AL-2026-7K3QX9" } };
    const api = mockApi({
      "GET admin/certificates/summary": { body: summary },
      "GET admin/certificates": { body: page([]) },
      "GET admin/certificates/outbox": { body: { ...page([row]), counts: summary.outbox } },
    });
    cleanups.push(api.restore);
    renderWithProviders(<AdminCertificates />);
    for (const name of ["Create & send", "Documents register", "Templates", "Document settings"]) expect(await screen.findByRole("tab", { name })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("tab", { name: /Approval queue/ }));
    expect(await screen.findByText("Admission letter")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Approve and send to Ananya Reddy" })).toBeInTheDocument();
  });

  it("derives queue items for older certificate rows and checks required fields", () => {
    const cert = { id: "c1", public_code: "ABCDEFGH2345", name_on_certificate: "A", email: "a@x.test", course_title: "DSA" } as unknown as OutboxRow["certificate"];
    expect(outboxItem({ id: "o1", certificate: cert } as OutboxRow)).toMatchObject({ kind: "certificate", number: "ABCDEFGH2345", title: "DSA" });
    expect(missingFields(admission, { name: "A", email: "" }, {})[0]).toBe("Student email");
    expect(missingFields(admission, { name: "", email: "bad" }, {})).toEqual(["Student name", "Valid student email", "Program / course", "Batch start date", "Duration", "Mode"]);
    expect(toLines(" a \n\n b ")).toEqual(["a", "b"]);
  });
});

describe("Public verification of documents", () => {
  it("shows a valid letter without its text, and a superseded one pointing to the correction", () => {
    const { unmount } = render(
      <CertificateVerification
        code="TD-AL-2026-7K3QX9"
        data={{ kind: "document", status: "valid", ref_no: "TD-AL-2026-7K3QX9", doc_type: "offer_course", label: "Course admission letter", layout: "letter", recipient: "Ananya Reddy", issued_at: "2026-11-11", program: "Full Stack", signatory: "A Signatory, Director", issuer: "Tech Drona", related: [{ ref_no: "TD-CC-2026-ABCDEF", label: "Completion certificate" }], pdf_check: true }}
      />,
    );
    expect(screen.getByText("Valid document")).toBeInTheDocument();
    expect(screen.getByText("Full Stack")).toBeInTheDocument();
    expect(screen.getByText("A Signatory, Director")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "TD-CC-2026-ABCDEF" })).toHaveAttribute("href", "/verify/TD-CC-2026-ABCDEF");
    expect(screen.getByText("Check a PDF copy")).toBeInTheDocument();
    unmount();
    render(<CertificateVerification code="TD-AL-2026-7K3QX9" data={{ kind: "document", status: "superseded", ref_no: "TD-AL-2026-7K3QX9", layout: "letter", recipient: "Ananya Reddy", issued_at: "2026-11-11", superseded_by: "TD-AL-2026-NEWREF" }} />);
    expect(screen.getByText("Superseded by a corrected copy")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "TD-AL-2026-NEWREF" })).toHaveAttribute("href", "/verify/TD-AL-2026-NEWREF");
  });
});
