"use client";

import Link from "next/link";
import { Suspense, lazy, useEffect, useMemo, useState } from "react";
import {
  Badge,
  Button,
  Card,
  Checkbox,
  ConfirmDialog,
  Dialog,
  FilterBar,
  FormField,
  Input,
  LoadingBlock,
  Pagination,
  Segmented,
  Select,
  Table,
  Textarea,
  nextCursorStack,
  previousCursorStack,
  useToast,
  type BadgeTone,
} from "@/components/ui";
import { api } from "@/lib/api/client";
import { useApi, seg } from "@/features/trainer/shared/use-api";
import { useFailToast } from "@/features/trainer/shared/ui";
import type { CursorPage, OutboxStatus } from "../lib/types";
import {
  DOC_STATUS_LABEL,
  isEmail,
  missingFields,
  pdfUrlFromBase64,
  readImage,
  toLines,
  type DocField,
  type DocSettings,
  type DocStatus,
  type DocTypesResponse,
  type IssuedDoc,
  type IssuedDocDetail,
  type LetterSections,
  type Prefill,
  type PreviewResult,
  type Recipient,
  type TemplatesCatalogue,
} from "../lib/docs";
import { formatDate, formatDateTime } from "@/lib/format";

const STATUS_TONE: Record<DocStatus, BadgeTone> = { valid: "success", revoked: "danger", superseded: "neutral" };
const EMAIL_LABEL: Record<OutboxStatus, string> = { awaiting: "Awaiting approval", pending: "Sending", sent: "Sent", failed: "Failed", cancelled: "Cancelled" };
const EMAIL_TONE: Record<OutboxStatus, BadgeTone> = { awaiting: "warning", pending: "info", sent: "success", failed: "danger", cancelled: "neutral" };
const EMPTY_RECIPIENT: Recipient = { name: "", email: "", college: "", reg_no: "" };
type EmailMode = "send" | "queue" | "none";

function DocStatusBadge({ status }: { status: DocStatus }) {
  return (
    <Badge tone={STATUS_TONE[status]} dot>
      {DOC_STATUS_LABEL[status]}
    </Badge>
  );
}

function EmailBadge({ status }: { status: OutboxStatus | null | undefined }) {
  if (!status) return <span className="text-fg-muted">—</span>;
  return (
    <Badge tone={EMAIL_TONE[status]} dot>
      {EMAIL_LABEL[status]}
    </Badge>
  );
}

function openPdf(b64: string) {
  const url = pdfUrlFromBase64(b64);
  window.open(url, "_blank", "noopener,noreferrer");
  window.setTimeout(() => URL.revokeObjectURL(url), 60_000);
}

/** One input for a document field (text / date / long text / money / select). */
export function FieldInput({ field, value, onChange }: { field: DocField; value: string; onChange: (v: string) => void }) {
  return (
    <FormField label={field.label} required={field.required} hint={field.hint}>
      {(p) =>
        field.kind === "longtext" ? (
          <Textarea {...p} rows={3} value={value} onChange={(e) => onChange(e.target.value)} />
        ) : field.kind === "select" ? (
          <Select {...p} value={value} onChange={(e) => onChange(e.target.value)} options={[{ value: "", label: "Choose…" }, ...(field.options ?? []).map((o) => ({ value: o, label: o }))]} />
        ) : (
          <Input {...p} type={field.kind === "date" ? "date" : "text"} value={value} onChange={(e) => onChange(e.target.value)} />
        )
      }
    </FormField>
  );
}

function RecipientFields({ value, onChange }: { value: Recipient; onChange: (r: Recipient) => void }) {
  const set = (k: keyof Recipient) => (e: { target: { value: string } }) => onChange({ ...value, [k]: e.target.value });
  return (
    <div className="grid gap-4 sm:grid-cols-2">
      <FormField label="Student name" required hint="As it should be printed.">
        {(p) => <Input {...p} value={value.name} onChange={set("name")} autoComplete="off" />}
      </FormField>
      <FormField label="Student email" required error={value.email.trim() && !isEmail(value.email) ? "Enter a valid email address" : undefined}>
        {(p) => <Input {...p} type="email" value={value.email} onChange={set("email")} autoComplete="off" />}
      </FormField>
      <FormField label="College" hint="Optional; printed under the name on letters.">
        {(p) => <Input {...p} value={value.college ?? ""} onChange={set("college")} />}
      </FormField>
      <FormField label="Registration no." hint="Optional.">
        {(p) => <Input {...p} value={value.reg_no ?? ""} onChange={set("reg_no")} />}
      </FormField>
    </div>
  );
}

/* ------------------------------------------------------------------ Create & send */

// Bulk (Excel / picked students) is a separate chunk: SheetJS and the bulk UI load only when used.
const BulkCreate = lazy(() => import("./BulkCreate"));

/** One document (form) or many (Bulk: spreadsheet / picked students). `onChanged` refreshes the
 * counts without leaving the tab (the bulk results stay on screen); `onIssued` after one document. */
export function CreateTab({ onIssued, onChanged }: { onIssued: () => void; onChanged?: () => void }) {
  const [mode, setMode] = useState<"one" | "bulk">("one");
  return (
    <div className="pt-4">
      <Segmented<"one" | "bulk">
        legend="Create"
        hideLegend
        name="create-mode"
        variant="pills"
        value={mode}
        onChange={setMode}
        options={[
          { value: "one", label: "One document" },
          { value: "bulk", label: "Bulk (Excel / students)" },
        ]}
      />
      {mode === "one" ? (
        <SingleCreate onIssued={onIssued} />
      ) : (
        <div className="pt-4">
          <Suspense fallback={<LoadingBlock label="Loading bulk create…" />}>
            <BulkCreate onIssued={onChanged ?? (() => undefined)} />
          </Suspense>
        </div>
      )}
    </div>
  );
}

function SingleCreate({ onIssued }: { onIssued: () => void }) {
  const catalogue = useApi<DocTypesResponse>("admin/documents/types");
  const [docType, setDocType] = useState("offer_course");
  const [recipient, setRecipient] = useState<Recipient>(EMPTY_RECIPIENT);
  const [fields, setFields] = useState<Record<string, string>>({});
  const [issueDate, setIssueDate] = useState("");
  const [email, setEmail] = useState<EmailMode>("send");
  const [enrolmentId, setEnrolmentId] = useState("");
  const [links, setLinks] = useState<Partial<Prefill>>({});
  const [busy, setBusy] = useState<"" | "preview" | "issue" | "prefill">("");
  const [leftovers, setLeftovers] = useState<string[]>([]);
  const fail = useFailToast();
  const toast = useToast();
  const types = catalogue.data?.types;
  const def = types?.find((t) => t.key === docType);
  const missing = missingFields(def, recipient, fields);

  const typeOptions = useMemo(
    () => [
      ...(types ?? []).filter((t) => t.layout === "letter").map((t) => ({ value: t.key, label: `Letter · ${t.label}` })),
      ...(types ?? []).filter((t) => t.layout === "certificate").map((t) => ({ value: t.key, label: `Certificate · ${t.label}` })),
    ],
    [types],
  );

  async function prefill() {
    if (!enrolmentId.trim()) return;
    setBusy("prefill");
    try {
      const p = await api.get<Prefill>("admin/documents/prefill", { query: { enrolment_id: enrolmentId.trim() } });
      setRecipient({ ...EMPTY_RECIPIENT, ...p.recipient });
      setFields((f) => ({ ...f, ...p.fields }));
      setLinks(p);
      toast.show({ tone: "success", title: "Filled from the enrolment" });
    } catch (err) {
      fail(err, "Couldn't read that enrolment");
    } finally {
      setBusy("");
    }
  }

  async function preview() {
    setBusy("preview");
    try {
      const r = await api.post<PreviewResult>("admin/documents/preview", { doc_type: docType, recipient, fields, issue_date: issueDate || undefined });
      if (r.kind === "ok") {
        setLeftovers(r.data.leftovers);
        openPdf(r.data.pdf_base64);
      }
    } catch (err) {
      fail(err, "Couldn't build the preview");
    } finally {
      setBusy("");
    }
  }

  async function issue() {
    setBusy("issue");
    try {
      const body = {
        doc_type: docType,
        recipient: { name: recipient.name.trim(), email: recipient.email.trim(), college: recipient.college || undefined, reg_no: recipient.reg_no || undefined },
        fields: Object.fromEntries(Object.entries(fields).filter(([k, v]) => v.trim() && def?.fields.some((f) => f.key === k))),
        issue_date: issueDate || undefined,
        user_id: links.user_id,
        enrolment_id: docType === "cert_completion" ? undefined : links.enrolment_id,
        batch_id: links.batch_id ?? undefined,
        course_id: links.course_id,
        email,
      };
      const r = await api.post<IssuedDoc>("admin/documents", body, { idempotencyKey: true });
      const d = r.kind === "ok" ? r.data : null;
      toast.show({
        tone: "success",
        title: `${def?.short ?? "Document"} issued`,
        description: d ? `${d.ref_no}${d.email_status ? ` · email ${EMAIL_LABEL[d.email_status].toLowerCase()}` : ""}` : undefined,
      });
      setRecipient(EMPTY_RECIPIENT);
      setFields({});
      setLinks({});
      setEnrolmentId("");
      setLeftovers([]);
      onIssued();
    } catch (err) {
      fail(err, "Couldn't issue the document");
    } finally {
      setBusy("");
    }
  }

  return (
    <div className="space-y-4 pt-4">
      {catalogue.data?.settings_problem ? (
        <Card title="Finish the document settings first" icon="alert" description={catalogue.data.settings_problem} />
      ) : null}
      <Card title="Document" icon="document" description="Choose what to issue. Letters are A4 portrait on the letterhead; certificates use the certificate design. Every document gets a reference number and a public verification page.">
        <div className="grid gap-4 sm:grid-cols-3">
          <FormField label="Type" required>
            {(p) => (
              <Select
                {...p}
                value={docType}
                onChange={(e) => {
                  setDocType(e.target.value);
                  setLeftovers([]);
                }}
                options={typeOptions.length ? typeOptions : [{ value: docType, label: "Loading…" }]}
              />
            )}
          </FormField>
          <FormField label="Issue date" hint="Empty = today (IST).">
            {(p) => <Input {...p} type="date" value={issueDate} onChange={(e) => setIssueDate(e.target.value)} />}
          </FormField>
          <FormField label="Email">
            {(p) => (
              <Select
                {...p}
                value={email}
                onChange={(e) => setEmail(e.target.value as EmailMode)}
                options={[
                  { value: "send", label: "Send now with the PDF attached" },
                  { value: "queue", label: "Put in the approval queue" },
                  { value: "none", label: "Don't email (download only)" },
                ]}
              />
            )}
          </FormField>
        </div>
        {docType === "cert_completion" ? (
          <p className="mt-3 text-sm text-fg-secondary">For LMS courses, completion certificates are issued from the Due tab. Use this for programmes run outside an LMS enrolment.</p>
        ) : null}
      </Card>
      <Card title="Recipient" icon="user" description="Type the details, or fill them from an LMS enrolment (course, batch dates and the learner).">
        <div className="mb-4 flex flex-wrap items-end gap-2">
          <FormField label="Enrolment ID" hint="Optional: links the document to the enrolment.">
            {(p) => <Input {...p} value={enrolmentId} onChange={(e) => setEnrolmentId(e.target.value)} placeholder="e.g. 0193…" className="font-mono" />}
          </FormField>
          <Button variant="secondary" loading={busy === "prefill"} disabled={!enrolmentId.trim()} onClick={() => void prefill()}>
            Fill from enrolment
          </Button>
        </div>
        <RecipientFields value={recipient} onChange={setRecipient} />
      </Card>
      {def ? (
        <Card title="Details" icon="pen" description={`What the ${def.short.toLowerCase()} says. Required details are marked; empty optional ones are simply left out.`}>
          <div className="grid gap-4 sm:grid-cols-2">
            {def.fields.map((f) => (
              <div key={f.key} className={f.kind === "longtext" ? "sm:col-span-2" : undefined}>
                <FieldInput field={f} value={fields[f.key] ?? ""} onChange={(v) => setFields((x) => ({ ...x, [f.key]: v }))} />
              </div>
            ))}
          </div>
        </Card>
      ) : null}
      {leftovers.length ? (
        <p role="alert" className="text-sm font-medium text-danger-fg">
          {`Template text is still in the wording: ${leftovers.join(", ")}. Fix it in Templates before issuing.`}
        </p>
      ) : null}
      <div className="flex flex-wrap items-center gap-3">
        <Button variant="secondary" loading={busy === "preview"} onClick={() => void preview()}>
          Preview PDF
        </Button>
        <Button loading={busy === "issue"} disabled={missing.length > 0 || Boolean(catalogue.data?.settings_problem)} onClick={() => void issue()}>
          {email === "send" ? "Issue & send" : "Issue"}
        </Button>
        {missing.length ? <p className="text-sm text-fg-muted">{`Still needed: ${missing.join(", ")}.`}</p> : null}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ Documents register */

export function RegisterTab({ onChanged }: { onChanged: () => void }) {
  const catalogue = useApi<DocTypesResponse>("admin/documents/types");
  const [q, setQ] = useState("");
  const [docType, setDocType] = useState("");
  const [status, setStatus] = useState("");
  const [stack, setStack] = useState<(string | undefined)[]>([undefined]);
  const list = useApi<CursorPage<IssuedDoc>>("admin/documents", { q: q.trim() || undefined, doc_type: docType || undefined, status: status || undefined, cursor: stack[stack.length - 1], limit: 25 });
  const [busy, setBusy] = useState<string | null>(null);
  const [detail, setDetail] = useState<string | null>(null);
  const [revoking, setRevoking] = useState<IssuedDoc | null>(null);
  const [reason, setReason] = useState("");
  const [publicReason, setPublicReason] = useState(false);
  const [reissuing, setReissuing] = useState<IssuedDoc | null>(null);
  const [reFields, setReFields] = useState<Record<string, string>>({});
  const fail = useFailToast();
  const toast = useToast();
  const resetPage = () => setStack([undefined]);
  const reload = async () => {
    await list.reload();
    onChanged();
  };

  async function download(d: IssuedDoc) {
    setBusy(`pdf:${d.id}`);
    try {
      const r = await api.get<{ url: string }>(`admin/documents/${seg(d.id)}/pdf`);
      if (r.url) window.open(r.url, "_blank", "noopener,noreferrer");
    } catch (err) {
      fail(err, "Couldn't open the PDF");
    } finally {
      setBusy(null);
    }
  }

  async function resend(d: IssuedDoc) {
    setBusy(`mail:${d.id}`);
    try {
      await api.post(`admin/documents/${seg(d.id)}/email`, { mode: "send" }, { idempotencyKey: true });
      toast.show({ tone: "success", title: "Email sent", description: `${d.ref_no} to ${d.recipient.email}` });
      await reload();
    } catch (err) {
      fail(err, "Couldn't send the email");
    } finally {
      setBusy(null);
    }
  }

  const reDef = catalogue.data?.types.find((t) => t.key === reissuing?.doc_type);

  return (
    <div className="space-y-4 pt-4">
      <Table<IssuedDoc>
        caption="Issued documents"
        rows={list.data?.data}
        rowKey={(r) => r.id}
        loading={list.loading}
        error={list.error}
        onRetry={() => void list.reload()}
        toolbar={
          <FilterBar variant="plain" label="Filter documents" columns={3}>
            <FormField label="Search">
              {(p) => (
                <Input
                  {...p}
                  type="search"
                  placeholder="Name, email or reference"
                  value={q}
                  onChange={(e) => {
                    setQ(e.target.value);
                    resetPage();
                  }}
                />
              )}
            </FormField>
            <FormField label="Type">
              {(p) => (
                <Select
                  {...p}
                  value={docType}
                  onChange={(e) => {
                    setDocType(e.target.value);
                    resetPage();
                  }}
                  options={[{ value: "", label: "All types" }, ...(catalogue.data?.types ?? []).map((t) => ({ value: t.key, label: t.short }))]}
                />
              )}
            </FormField>
            <FormField label="Status">
              {(p) => (
                <Select
                  {...p}
                  value={status}
                  onChange={(e) => {
                    setStatus(e.target.value);
                    resetPage();
                  }}
                  options={[
                    { value: "", label: "All" },
                    { value: "valid", label: "Valid" },
                    { value: "revoked", label: "Revoked" },
                    { value: "superseded", label: "Superseded" },
                  ]}
                />
              )}
            </FormField>
          </FilterBar>
        }
        empty={{ title: "No documents yet", description: "Letters and certificates you create appear here, with their emails and verification links.", icon: "document" }}
        columns={[
          {
            key: "recipient",
            header: "Recipient",
            cell: (r) => (
              <div className="min-w-0">
                <p className="font-medium text-fg">{r.recipient.name}</p>
                <p className="truncate text-xs text-fg-muted">{r.recipient.email}</p>
              </div>
            ),
          },
          {
            key: "doc",
            header: "Document",
            cell: (r) => (
              <div className="min-w-0">
                <p className="text-fg">{r.short}</p>
                {r.title ? <p className="truncate text-xs text-fg-muted">{r.title}</p> : null}
              </div>
            ),
          },
          { key: "issued", header: "Issued", cell: (r) => formatDate(r.issue_date), priority: "secondary" },
          { key: "status", header: "Status", cell: (r) => <DocStatusBadge status={r.status} /> },
          { key: "email", header: "Email", cell: (r) => <EmailBadge status={r.email_status} />, priority: "secondary" },
          {
            key: "ref",
            header: "Reference",
            cell: (r) => (
              <Link href={`/verify/${encodeURIComponent(r.ref_no)}`} target="_blank" className="font-mono text-sm text-fg-link hover:text-fg-link-hover">
                {r.ref_no}
              </Link>
            ),
          },
          {
            key: "actions",
            header: <span className="sr-only">Actions</span>,
            align: "right",
            cell: (r) => (
              <div className="flex flex-wrap justify-end gap-2">
                <Button size="sm" variant="ghost" onClick={() => setDetail(r.id)} aria-label={`Details ${r.ref_no}`}>
                  Details
                </Button>
                {r.status === "valid" ? (
                  <>
                    <Button size="sm" variant="secondary" loading={busy === `pdf:${r.id}`} onClick={() => void download(r)} aria-label={`Download PDF ${r.ref_no}`}>
                      PDF
                    </Button>
                    <Button size="sm" variant="ghost" loading={busy === `mail:${r.id}`} onClick={() => void resend(r)} aria-label={`Email ${r.ref_no}`}>
                      Email
                    </Button>
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() => {
                        setReFields({ ...r.fields });
                        setReissuing(r);
                      }}
                      aria-label={`Correct ${r.ref_no}`}
                    >
                      Correct
                    </Button>
                    <Button
                      size="sm"
                      variant="danger-secondary"
                      onClick={() => {
                        setReason("");
                        setPublicReason(false);
                        setRevoking(r);
                      }}
                      aria-label={`Revoke ${r.ref_no}`}
                    >
                      Revoke
                    </Button>
                  </>
                ) : null}
              </div>
            ),
          },
        ]}
      />
      <Pagination
        hasMore={Boolean(list.data?.page.has_more)}
        hasPrevious={stack.length > 1}
        loading={list.loading}
        onNext={() => setStack((st) => nextCursorStack(st, list.data?.page.next_cursor ?? null))}
        onPrevious={() => setStack((st) => previousCursorStack(st))}
        label="Document pages"
      />
      {detail ? <DocDetailDialog id={detail} onClose={() => setDetail(null)} /> : null}
      <ConfirmDialog
        open={revoking !== null}
        onClose={() => setRevoking(null)}
        title="Revoke this document?"
        description={revoking ? `${revoking.recipient.name} · ${revoking.short} · ${revoking.ref_no}. The public verify page will show it as revoked; unsent emails are cancelled.` : undefined}
        confirmLabel="Revoke document"
        danger
        onConfirm={async () => {
          if (!revoking) return;
          if (reason.trim().length < 5) throw new Error("Write a reason of at least 5 characters.");
          await api.post(`admin/documents/${seg(revoking.id)}/revoke`, { reason: reason.trim(), public_reason: publicReason }, { idempotencyKey: true });
          toast.show({ tone: "success", title: "Document revoked", description: revoking.ref_no });
          await reload();
        }}
      >
        <div className="space-y-3">
          <FormField label="Reason" required hint="Recorded in the audit log.">
            {(p) => <Textarea {...p} rows={3} value={reason} onChange={(e) => setReason(e.target.value)} />}
          </FormField>
          <Checkbox label="Show the reason on the public verify page" checked={publicReason} onChange={(e) => setPublicReason(e.target.checked)} />
        </div>
      </ConfirmDialog>
      <ConfirmDialog
        open={reissuing !== null}
        onClose={() => setReissuing(null)}
        title="Issue a corrected copy?"
        description={reissuing ? `A new ${reissuing.short.toLowerCase()} replaces ${reissuing.ref_no}; the old one shows as superseded on the verify page. The new email waits in the approval queue.` : undefined}
        confirmLabel="Issue corrected copy"
        onConfirm={async () => {
          if (!reissuing) return;
          const r = await api.post<IssuedDoc>(`admin/documents/${seg(reissuing.id)}/reissue`, { fields: reFields, email: "queue" }, { idempotencyKey: true });
          toast.show({ tone: "success", title: "Corrected copy issued", description: r.kind === "ok" ? r.data.ref_no : undefined });
          await reload();
        }}
      >
        <div className="grid max-h-[50vh] gap-3 overflow-y-auto">
          {(reDef?.fields ?? []).map((f) => (
            <FieldInput key={f.key} field={f} value={reFields[f.key] ?? ""} onChange={(v) => setReFields((x) => ({ ...x, [f.key]: v }))} />
          ))}
        </div>
      </ConfirmDialog>
    </div>
  );
}

function DocDetailDialog({ id, onClose }: { id: string; onClose: () => void }) {
  const d = useApi<IssuedDocDetail>(`admin/documents/${seg(id)}`);
  const doc = d.data;
  return (
    <Dialog open onClose={onClose} title={doc ? `${doc.short} · ${doc.ref_no}` : "Document"} description={doc ? `${doc.recipient.name} · ${doc.recipient.email}` : undefined} size="lg">
      {doc ? (
        <div className="space-y-4 text-sm">
          <div className="flex flex-wrap items-center gap-2">
            <DocStatusBadge status={doc.status} />
            <span className="text-fg-muted">{`Issued ${formatDate(doc.issue_date)} · ${doc.origin}`}</span>
            {doc.content_sha256 ? <span className="font-mono text-xs text-fg-muted" title="SHA-256 of the PDF">{doc.content_sha256.slice(0, 16)}…</span> : null}
          </div>
          {doc.subject ? <p className="font-medium text-fg">{doc.subject}</p> : null}
          <div className="space-y-2 rounded-md border border-line bg-surface-sunken p-3 text-fg-secondary">
            {doc.paragraphs.map((p, i) => (
              <p key={i}>{p}</p>
            ))}
          </div>
          <div>
            <h3 className="mb-1 font-display font-bold text-fg-heading">Emails</h3>
            {doc.emails.length ? (
              <ul className="space-y-1">
                {doc.emails.map((e) => (
                  <li key={e.id} className="flex flex-wrap items-center gap-2">
                    <EmailBadge status={e.status} />
                    <span className="text-fg-muted">{`${e.origin} · ${formatDateTime(e.sent_at ?? e.created_at, { year: true })}${e.to ? ` · to ${e.to}` : ""}`}</span>
                    {e.last_error ? <span className="text-danger-fg">{e.last_error}</span> : null}
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-fg-muted">Not emailed yet.</p>
            )}
          </div>
          {doc.related.length ? (
            <div>
              <h3 className="mb-1 font-display font-bold text-fg-heading">Other documents for this person</h3>
              <ul className="space-y-1">
                {doc.related.map((r) => (
                  <li key={r.id}>
                    <Link href={`/verify/${encodeURIComponent(r.ref_no)}`} target="_blank" className="font-mono text-fg-link">
                      {r.ref_no}
                    </Link>{" "}
                    <span className="text-fg-muted">{`${r.label} · ${DOC_STATUS_LABEL[r.status]}`}</span>
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
        </div>
      ) : (
        <p className="text-sm text-fg-muted">{d.error ? "Couldn't load the document." : "Loading…"}</p>
      )}
    </Dialog>
  );
}

/* ------------------------------------------------------------------ Templates */

const PLACEHOLDER_HINT =
  "Placeholders: {{name}} {{first_name}} {{email}} {{company}} {{program}} {{role}} {{ref_no}} {{cert_no}} {{verify_url}} {{date}} and every detail of the type (e.g. {{batch_start}}). Phrases such as {{period_phrase}} read naturally when a detail is empty.";

export function TemplatesTab() {
  const cat = useApi<TemplatesCatalogue>("admin/documents/templates");
  const [kind, setKind] = useState<"document" | "email">("document");
  const [key, setKey] = useState("offer_course");
  const [paragraphs, setParagraphs] = useState("");
  const [sections, setSections] = useState<{ hero: string; benefits: string; terms: string; next: string; accept: boolean } | null>(null);
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");
  const [busy, setBusy] = useState(false);
  const fail = useFailToast();
  const toast = useToast();
  const entries = kind === "document" ? cat.data?.documents : cat.data?.emails;
  const keys = Object.keys(entries ?? {});

  // load the current wording (override or default) into the editor
  useEffect(() => {
    if (!cat.data) return;
    if (kind === "document") {
      const e = cat.data.documents[key];
      if (!e) return;
      const paras = e.override?.paragraphs ?? e.default.paragraphs;
      setParagraphs(paras.join("\n\n"));
      const s: LetterSections | null = e.default.sections ? { ...e.default.sections, ...(e.override?.sections ?? {}) } : null;
      setSections(s ? { hero: s.hero ?? "", benefits: (s.benefits ?? []).join("\n"), terms: (s.terms ?? []).join("\n"), next: (s.next ?? []).join("\n"), accept: s.accept !== false } : null);
    } else {
      const e = cat.data.emails[key];
      if (!e) return;
      setSubject(e.override?.subject ?? e.default.subject);
      setBody(e.override?.body ?? e.default.body);
    }
  }, [cat.data, kind, key]);

  async function save() {
    setBusy(true);
    try {
      const content =
        kind === "document"
          ? {
              paragraphs: paragraphs.split(/\n\s*\n/).map((p) => p.trim()).filter(Boolean),
              ...(sections ? { sections: { hero: sections.hero, benefits: toLines(sections.benefits), terms: toLines(sections.terms), next: toLines(sections.next), accept: sections.accept } } : {}),
            }
          : { subject, body };
      await api.put(`admin/documents/templates/${kind}/${seg(key)}`, { content });
      toast.show({ tone: "success", title: "Wording saved", description: "New documents use it; issued ones keep their wording." });
      await cat.reload();
    } catch (err) {
      fail(err, "Couldn't save the wording");
    } finally {
      setBusy(false);
    }
  }

  async function reset() {
    setBusy(true);
    try {
      await api.delete(`admin/documents/templates/${kind}/${seg(key)}`);
      toast.show({ tone: "success", title: "Back to the default wording" });
      await cat.reload();
    } catch (err) {
      fail(err, "Couldn't reset the wording");
    } finally {
      setBusy(false);
    }
  }

  const current = entries?.[key];
  return (
    <div className="space-y-4 pt-4">
      <div className="flex flex-wrap items-end gap-4">
        <Segmented
          legend="Wording of"
          hideLegend
          name="template-kind"
          variant="pills"
          value={kind}
          onChange={(v) => {
            setKind(v);
            setKey(v === "document" ? "offer_course" : "offer_course");
          }}
          options={[
            { value: "document", label: "Documents" },
            { value: "email", label: "Emails" },
          ]}
        />
        <FormField label={kind === "document" ? "Document" : "Email"}>
          {(p) => <Select {...p} value={key} onChange={(e) => setKey(e.target.value)} options={keys.map((k) => ({ value: k, label: entries?.[k]?.label ?? k }))} />}
        </FormField>
        {current ? <Badge tone={current.override ? "brand" : "neutral"}>{current.override ? "Edited" : "Default wording"}</Badge> : null}
      </div>
      <Card title="Wording" icon="pen" description={PLACEHOLDER_HINT}>
        {kind === "document" ? (
          <div className="space-y-4">
            <FormField label="Paragraphs" hint="Separate paragraphs with an empty line.">
              {(p) => <Textarea {...p} rows={12} value={paragraphs} onChange={(e) => setParagraphs(e.target.value)} />}
            </FormField>
            {sections ? (
              <>
                <FormField label="Congratulations line">{(p) => <Input {...p} value={sections.hero} onChange={(e) => setSections({ ...sections, hero: e.target.value })} />}</FormField>
                <FormField label="What you'll gain" hint="One per line.">
                  {(p) => <Textarea {...p} rows={4} value={sections.benefits} onChange={(e) => setSections({ ...sections, benefits: e.target.value })} />}
                </FormField>
                <FormField label="Terms and conditions" hint="One per line (numbered in the letter).">
                  {(p) => <Textarea {...p} rows={8} value={sections.terms} onChange={(e) => setSections({ ...sections, terms: e.target.value })} />}
                </FormField>
                <FormField label="Next steps" hint="One per line.">
                  {(p) => <Textarea {...p} rows={3} value={sections.next} onChange={(e) => setSections({ ...sections, next: e.target.value })} />}
                </FormField>
                <Checkbox label="Print the acceptance form" checked={sections.accept} onChange={(e) => setSections({ ...sections, accept: e.target.checked })} />
              </>
            ) : null}
          </div>
        ) : (
          <div className="space-y-4">
            <FormField label="Subject" required>{(p) => <Input {...p} value={subject} onChange={(e) => setSubject(e.target.value)} />}</FormField>
            <FormField label="Body" required hint="Separate paragraphs with an empty line. “Regards, {company}” is added at the end.">
              {(p) => <Textarea {...p} rows={10} value={body} onChange={(e) => setBody(e.target.value)} />}
            </FormField>
            {current?.attach ? <p className="text-sm text-fg-secondary">The document PDF is attached to this email.</p> : null}
          </div>
        )}
        <div className="mt-4 flex flex-wrap gap-2">
          <Button loading={busy} onClick={() => void save()}>
            Save wording
          </Button>
          <Button variant="secondary" disabled={busy || !current?.override} onClick={() => void reset()}>
            Reset to default
          </Button>
        </div>
      </Card>
    </div>
  );
}

/* ------------------------------------------------------------------ Document settings */

const TEXT_SETTINGS: { key: keyof DocSettings; label: string; hint?: string; wide?: boolean }[] = [
  { key: "company", label: "Company name" },
  { key: "legal_name", label: "Registered name", hint: "If different from the company name. Printed as the issuing organisation on certificates." },
  { key: "tagline", label: "Tagline / department", hint: "Printed under the organisation name on certificates and letters. The default tagline is already part of the logo, so it is not repeated." },
  { key: "address", label: "Address", wide: true },
  { key: "phone", label: "Phone" },
  { key: "email", label: "Email" },
  { key: "website", label: "Website" },
  { key: "portal_url", label: "Learning portal URL", hint: "Empty = this LMS." },
  { key: "signatory", label: "Signatory name" },
  { key: "designation", label: "Signatory designation" },
  { key: "signatory_email", label: "Signatory email", hint: "Printed on recommendation letters." },
  { key: "signatory_phone", label: "Signatory phone" },
];
type ImageSlot = "signature" | "seal" | "logo_left" | "logo_right";
const IMAGE_SLOTS: { slot: ImageSlot; label: string; hint: string }[] = [
  { slot: "signature", label: "Signature", hint: "The authorised signatory's signature, printed on every certificate and letter. Without it a blank signature line is printed." },
  { slot: "seal", label: "Seal / stamp", hint: "Company stamp, printed beside the signature on letters." },
  { slot: "logo_left", label: "Left logo", hint: "Optional, top-left of certificates and the letterhead. Empty = nothing printed." },
  { slot: "logo_right", label: "Right logo", hint: "Optional, top-right of certificates and the letterhead. Empty = nothing printed." },
];
const IMAGE_LABEL = Object.fromEntries(IMAGE_SLOTS.map((s) => [s.slot, s.label])) as Record<ImageSlot, string>;

export function DocSettingsTab({ onChanged }: { onChanged: () => void }) {
  const st = useApi<DocSettings>("admin/documents/settings");
  const [form, setForm] = useState<Record<string, string>>({});
  const [regLines, setRegLines] = useState("");
  const [autoLetter, setAutoLetter] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const fail = useFailToast();
  const toast = useToast();

  useEffect(() => {
    const s = st.data;
    if (!s) return;
    setForm(Object.fromEntries(TEXT_SETTINGS.map((f) => [f.key, String(s[f.key] ?? "")])));
    setRegLines((s.reg_lines ?? []).join("\n"));
    setAutoLetter(s.auto_admission_letter);
  }, [st.data]);

  async function save() {
    setBusy("save");
    try {
      await api.put("admin/documents/settings", { ...form, reg_lines: toLines(regLines).slice(0, 4), auto_admission_letter: autoLetter });
      toast.show({ tone: "success", title: "Document settings saved" });
      await st.reload();
      onChanged();
    } catch (err) {
      fail(err, "Couldn't save the settings");
    } finally {
      setBusy(null);
    }
  }

  async function upload(slot: ImageSlot, file: File | undefined) {
    if (!file) return;
    setBusy(slot);
    try {
      const data_url = await readImage(file);
      await api.put(`admin/documents/settings/images/${slot}`, { data_url });
      toast.show({ tone: "success", title: `${IMAGE_LABEL[slot]} uploaded` });
      await st.reload();
    } catch (err) {
      fail(err, "Couldn't upload the image");
    } finally {
      setBusy(null);
    }
  }

  async function remove(slot: ImageSlot) {
    setBusy(slot);
    try {
      await api.delete(`admin/documents/settings/images/${slot}`);
      await st.reload();
    } catch (err) {
      fail(err, "Couldn't remove the image");
    } finally {
      setBusy(null);
    }
  }

  async function view(slot: ImageSlot) {
    try {
      const r = await api.get<{ url: string }>(`admin/documents/settings/images/${slot}`);
      if (r.url) window.open(r.url, "_blank", "noopener,noreferrer");
    } catch (err) {
      fail(err, "Couldn't open the image");
    }
  }

  const s = st.data;
  return (
    <div className="space-y-4 pt-4">
      {s?.problem ? <Card title="Needed before documents can be issued" icon="alert" description={s.problem} /> : null}
      <Card title="Letterhead and signatory" icon="building" description="Printed on every letter and certificate. Issued documents keep the details they were issued with.">
        <div className="grid gap-4 sm:grid-cols-2">
          {TEXT_SETTINGS.map((f) => (
            <div key={f.key} className={f.wide ? "sm:col-span-2" : undefined}>
              <FormField label={f.label} hint={f.hint} required={f.key === "signatory" || f.key === "designation"}>
                {(p) => <Input {...p} value={form[f.key] ?? ""} onChange={(e) => setForm((x) => ({ ...x, [f.key]: e.target.value }))} />}
              </FormField>
            </div>
          ))}
          <div className="sm:col-span-2">
            <FormField label="Registration lines" hint="Up to 4 lines (CIN, GSTIN, Udyam…), printed in the letter footer.">
              {(p) => <Textarea {...p} rows={3} value={regLines} onChange={(e) => setRegLines(e.target.value)} />}
            </FormField>
          </div>
        </div>
      </Card>
      <Card title="Signature, seal and logos" icon="image" description="PNG or JPEG under 300 KB, ideally on a transparent background. Upload only logos the company is authorised to use (for example, accreditation or registration marks it has been granted); government emblems need written permission.">
        <ul className="space-y-3">
          {IMAGE_SLOTS.map(({ slot, hint }) => (
            <li key={slot} className="flex flex-wrap items-center gap-3">
              <span className="w-40 font-medium text-fg">{IMAGE_LABEL[slot]}</span>
              <Badge tone={s?.images[slot] ? "success" : "neutral"}>{s?.images[slot] ? "Uploaded" : "Not set"}</Badge>
              <label className="cursor-pointer text-sm font-semibold text-fg-link">
                <span>{s?.images[slot] ? "Replace" : "Upload"}</span>
                <input type="file" accept="image/png,image/jpeg" className="sr-only" aria-label={`Upload ${IMAGE_LABEL[slot]}`} disabled={busy === slot} onChange={(e) => void upload(slot, e.target.files?.[0])} />
              </label>
              {s?.images[slot] ? (
                <>
                  <Button size="sm" variant="ghost" onClick={() => void view(slot)}>
                    View
                  </Button>
                  <Button size="sm" variant="ghost" loading={busy === slot} onClick={() => void remove(slot)}>
                    Remove
                  </Button>
                </>
              ) : null}
              <span className="basis-full text-sm text-fg-secondary">{hint}</span>
            </li>
          ))}
        </ul>
      </Card>
      <Card title="Automation" icon="bolt" description={`Emails follow the auto-send setting in Settings (now ${s?.auto_send ? "on: sent at once" : "off: they wait for approval"}).`}>
        <Checkbox
          label="Issue an admission letter when a learner is enrolled"
          description="For paid, manual and batch enrolments (not free self-enrolments). The letter's email waits in the approval queue unless auto-send is on."
          checked={autoLetter}
          onChange={(e) => setAutoLetter(e.target.checked)}
        />
      </Card>
      <Button loading={busy === "save"} disabled={st.loading} onClick={() => void save()}>
        Save settings
      </Button>
    </div>
  );
}
