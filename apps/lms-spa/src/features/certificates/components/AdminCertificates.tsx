"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import {
  Badge,
  Button,
  Card,
  Checkbox,
  ConfirmDialog,
  FilterBar,
  FormField,
  Input,
  PageHeader,
  Pagination,
  Segmented,
  Select,
  StatGrid,
  StatTile,
  Table,
  Tabs,
  Textarea,
  nextCursorStack,
  previousCursorStack,
  useToast,
  type BadgeTone,
} from "@/components/ui";
import { api } from "@/lib/api/client";
import { useApi, seg } from "@/features/trainer/shared/use-api";
import { useFailToast } from "@/features/trainer/shared/ui";
import { outboxItem, type AdminCertificate, type ApproveResult, type CertSummary, type CursorPage, type DueRow, type IssueDueResult, type OutboxRow, type OutboxStatus } from "../lib/types";
import { CreateTab, DocSettingsTab, RegisterTab, TemplatesTab } from "./AdminDocuments";
import { pdfUrlFromBase64 } from "../lib/docs";
import { OfferLettersTab } from "./OfferLetters";
import { formatDate, formatDateTime } from "@/lib/format";

const EMAIL_TONE: Record<OutboxStatus, BadgeTone> = { awaiting: "warning", pending: "info", sent: "success", failed: "danger", cancelled: "neutral" };
const EMAIL_LABEL: Record<OutboxStatus, string> = { awaiting: "Awaiting approval", pending: "Sending", sent: "Sent", failed: "Failed", cancelled: "Cancelled" };
const REASON_LABEL: Record<string, string> = {
  lessons_incomplete: "Required lessons not complete",
  final_test_pending: "Final test not passed yet",
  no_certificate: "This course has no certificate",
  not_eligible: "Not eligible",
};

export function reasonLabel(reason: string | null | undefined): string {
  return reason ? (REASON_LABEL[reason] ?? reason.replace(/_/g, " ")) : "";
}

function EmailBadge({ status }: { status: OutboxStatus | null | undefined }) {
  if (!status) return <span className="text-fg-muted">—</span>;
  return (
    <Badge tone={EMAIL_TONE[status]} dot>
      {EMAIL_LABEL[status]}
    </Badge>
  );
}

function Learner({ name, email }: { name: string | null; email: string | null }) {
  return (
    <div className="min-w-0">
      <p className="font-medium text-fg">{name || "—"}</p>
      {email ? <p className="truncate text-xs text-fg-muted">{email}</p> : null}
    </div>
  );
}

/**
 * ADM-017 Admin > Certificates: KPI tiles, the issued register (search, filter, revoke,
 * regenerate, PDF, verify link), the due list (issue one / all eligible), the email approval
 * queue (approve & send / cancel) and the auto-send setting. `initialCourse` comes from `?course=`.
 */
export function AdminCertificates({ initialCourse = "" }: { initialCourse?: string }) {
  const [courseId, setCourseId] = useState(initialCourse);
  const [tab, setTab] = useState("issued");
  const summary = useApi<CertSummary>("admin/certificates/summary", { course_id: courseId || undefined });
  const refresh = () => void summary.reload();
  const s = summary.data;

  return (
    <div>
      <PageHeader
        title="Certificates & documents"
        description="Course certificates, letters (offer, admission, recommendation) and other certificates: create and send them, the register, the emails waiting for your approval, wording and settings."
        meta={courseId ? <Badge tone="brand">Filtered to one course</Badge> : undefined}
        actions={
          courseId ? (
            <Button variant="secondary" size="sm" onClick={() => setCourseId("")}>
              Show all courses
            </Button>
          ) : undefined
        }
      />
      <StatGrid columns={6} className="mb-6">
        <StatTile label="Issued" value={s ? String(s.issued) : null} icon="award" tone="highlight" />
        <StatTile label="Valid" value={s ? String(s.valid) : null} icon="check" tone="success" hint={s && s.without_pdf ? `${s.without_pdf} without PDF` : undefined} />
        <StatTile label="Revoked" value={s ? String(s.revoked) : null} icon="alert" tone={s && s.revoked ? "danger" : "neutral"} />
        <StatTile label="Due" value={s ? String(s.due_eligible) : null} icon="hourglass" tone={s && s.due_eligible ? "warning" : "neutral"} hint={s ? `${s.due} without a certificate` : undefined} />
        <StatTile
          label="Awaiting approval"
          value={s ? String(s.outbox.awaiting) : null}
          icon="inbox"
          tone={s && s.outbox.awaiting ? "warning" : "neutral"}
          hint={s ? (s.auto_send ? "Auto-send is on" : "Auto-send is off") : undefined}
        />
        <StatTile
          label="Documents"
          value={s ? String(s.documents?.valid ?? 0) : null}
          icon="document"
          tone="neutral"
          hint={s?.documents && (s.documents.revoked || s.documents.superseded) ? `${s.documents.revoked} revoked, ${s.documents.superseded} corrected` : "Letters and other certificates"}
        />
      </StatGrid>
      <Tabs
        label="Certificates and documents"
        value={tab}
        onValueChange={setTab}
        items={[
          { id: "issued", label: "Issued", content: <IssuedTab courseId={courseId} onCourse={setCourseId} onChanged={refresh} /> },
          { id: "due", label: s ? `Due (${s.due_eligible})` : "Due", content: <DueTab courseId={courseId} onChanged={refresh} /> },
          { id: "create", label: "Create & send", content: <CreateTab onIssued={() => { refresh(); setTab("register"); }} onChanged={refresh} /> },
          { id: "offers", label: "Offer letters", content: <OfferLettersTab /> },
          { id: "register", label: "Documents register", content: <RegisterTab onChanged={refresh} /> },
          { id: "queue", label: s ? `Approval queue (${s.outbox.awaiting})` : "Approval queue", content: <QueueTab courseId={courseId} onChanged={refresh} /> },
          { id: "templates", label: "Templates", content: <TemplatesTab /> },
          { id: "settings", label: "Settings", content: <SettingsTab onChanged={refresh} /> },
          { id: "doc-settings", label: "Document settings", content: <DocSettingsTab onChanged={refresh} /> },
        ]}
      />
    </div>
  );
}

/* ------------------------------------------------------------------ Issued */

function IssuedTab({ courseId, onCourse, onChanged }: { courseId: string; onCourse: (id: string) => void; onChanged: () => void }) {
  const [q, setQ] = useState("");
  const [status, setStatus] = useState("");
  const [stack, setStack] = useState<(string | undefined)[]>([undefined]);
  const cursor = stack[stack.length - 1];
  const list = useApi<CursorPage<AdminCertificate>>("admin/certificates", { course_id: courseId || undefined, status: status || undefined, q: q.trim() || undefined, cursor, limit: 25 });
  const [busy, setBusy] = useState<string | null>(null);
  const [revoking, setRevoking] = useState<AdminCertificate | null>(null);
  const [reason, setReason] = useState("");
  const fail = useFailToast();
  const toast = useToast();

  const courses = useMemo(() => {
    const m = new Map<string, string>();
    for (const c of list.data?.data ?? []) m.set(c.course_id, c.course_title ?? c.course_id);
    if (courseId && !m.has(courseId)) m.set(courseId, "Selected course");
    return [...m].map(([value, label]) => ({ value, label }));
  }, [list.data, courseId]);

  const resetPage = () => setStack([undefined]);

  async function download(c: AdminCertificate) {
    setBusy(`pdf:${c.id}`);
    try {
      const r = await api.get<{ url: string }>(`admin/certificates/${seg(c.id)}/pdf`);
      if (r.url) window.open(r.url, "_blank", "noopener,noreferrer");
      if (!c.pdf_available) await list.reload();
    } catch (err) {
      fail(err, "Couldn't open the PDF");
    } finally {
      setBusy(null);
    }
  }

  async function regenerate(c: AdminCertificate) {
    setBusy(`regen:${c.id}`);
    try {
      await api.post(`admin/certificates/${seg(c.id)}/regenerate`, undefined, { idempotencyKey: true });
      toast.show({ tone: "success", title: "PDF regenerated", description: c.public_code });
      await list.reload();
      onChanged();
    } catch (err) {
      fail(err, "Couldn't regenerate the PDF");
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="space-y-4 pt-4">
      <Table<AdminCertificate>
        caption="Issued certificates"
        rows={list.data?.data}
        rowKey={(r) => r.id}
        loading={list.loading}
        error={list.error}
        onRetry={() => void list.reload()}
        toolbar={
          <FilterBar variant="plain" label="Filter certificates" columns={3}>
            <FormField label="Search">
              {(p) => (
                <Input
                  {...p}
                  type="search"
                  placeholder="Name, email or certificate number"
                  value={q}
                  onChange={(e) => {
                    setQ(e.target.value);
                    resetPage();
                  }}
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
                  ]}
                />
              )}
            </FormField>
            <FormField label="Course">
              {(p) => (
                <Select
                  {...p}
                  value={courseId}
                  onChange={(e) => {
                    onCourse(e.target.value);
                    resetPage();
                  }}
                  options={[{ value: "", label: "All courses" }, ...courses]}
                />
              )}
            </FormField>
          </FilterBar>
        }
        empty={{ title: "No certificates found", description: "Certificates appear here as soon as they are issued, automatically or by hand.", icon: "award" }}
        columns={[
          { key: "learner", header: "Learner", cell: (r) => <Learner name={r.name_on_certificate} email={r.email} /> },
          { key: "course", header: "Course", cell: (r) => r.course_title ?? "—" },
          { key: "issued", header: "Issued", cell: (r) => formatDate(r.issued_at), priority: "secondary" },
          {
            key: "status",
            header: "Status",
            cell: (r) =>
              r.status === "revoked" ? (
                <Badge tone="danger" dot>
                  Revoked
                </Badge>
              ) : (
                <Badge tone="success" dot>
                  Valid
                </Badge>
              ),
          },
          { key: "email", header: "Email", cell: (r) => <EmailBadge status={r.email_status} />, priority: "secondary" },
          {
            key: "code",
            header: "Number",
            cell: (r) => (
              <Link href={`/verify/${encodeURIComponent(r.public_code)}`} target="_blank" className="font-mono text-sm text-fg-link hover:text-fg-link-hover">
                {r.public_code}
              </Link>
            ),
          },
          {
            key: "actions",
            header: <span className="sr-only">Actions</span>,
            align: "right",
            cell: (r) =>
              r.status === "revoked" ? (
                <span className="text-xs text-fg-muted">{r.revoked_at ? `Revoked ${formatDate(r.revoked_at)}` : null}</span>
              ) : (
                <div className="flex flex-wrap justify-end gap-2">
                  <Button size="sm" variant="secondary" loading={busy === `pdf:${r.id}`} onClick={() => void download(r)} aria-label={`Download PDF ${r.public_code}`}>
                    PDF
                  </Button>
                  <Button size="sm" variant="ghost" loading={busy === `regen:${r.id}`} onClick={() => void regenerate(r)} aria-label={`Regenerate PDF ${r.public_code}`}>
                    Regenerate
                  </Button>
                  <Button
                    size="sm"
                    variant="danger-secondary"
                    onClick={() => {
                      setReason("");
                      setRevoking(r);
                    }}
                    aria-label={`Revoke ${r.public_code}`}
                  >
                    Revoke
                  </Button>
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
        label="Certificate pages"
      />
      <ConfirmDialog
        open={revoking !== null}
        onClose={() => setRevoking(null)}
        title="Revoke this certificate?"
        description={revoking ? `${revoking.name_on_certificate} · ${revoking.course_title ?? ""} · ${revoking.public_code}. The public verify page will show it as revoked.` : undefined}
        confirmLabel="Revoke certificate"
        danger
        onConfirm={async () => {
          if (!revoking) return;
          if (reason.trim().length < 5) throw new Error("Write a reason of at least 5 characters.");
          await api.post(`certificates/${seg(revoking.id)}/revoke`, { reason: reason.trim() }, { idempotencyKey: true });
          toast.show({ tone: "success", title: "Certificate revoked", description: revoking.public_code });
          await list.reload();
          onChanged();
        }}
      >
        <FormField label="Reason" required hint="Recorded in the audit log; not shown publicly.">
          {(p) => <Textarea {...p} rows={3} value={reason} onChange={(e) => setReason(e.target.value)} />}
        </FormField>
      </ConfirmDialog>
    </div>
  );
}

/* ------------------------------------------------------------------ Due */

function DueTab({ courseId, onChanged }: { courseId: string; onChanged: () => void }) {
  const due = useApi<{ data: DueRow[]; eligible: number }>("admin/certificates/due", { course_id: courseId || undefined });
  const [busy, setBusy] = useState<string | null>(null);
  const [confirmAll, setConfirmAll] = useState(false);
  const [previewed, setPreviewed] = useState(false);
  const fail = useFailToast();
  const toast = useToast();
  const eligible = due.data?.eligible ?? 0;
  const firstEligible = due.data?.data.find((r) => r.eligible);

  /** The certificate this learner would get (nothing stored). "Issue all" waits for one preview. */
  async function preview(row: DueRow) {
    setBusy(`preview:${row.enrolment_id}`);
    try {
      const r = await api.post<{ pdf_base64: string }>("admin/certificates/due/preview", { enrolment_id: row.enrolment_id });
      if (r.kind === "ok") {
        const url = pdfUrlFromBase64(r.data.pdf_base64);
        window.open(url, "_blank", "noopener,noreferrer");
        window.setTimeout(() => URL.revokeObjectURL(url), 60_000);
        setPreviewed(true);
      }
    } catch (err) {
      fail(err, "Couldn't build the preview");
    } finally {
      setBusy(null);
    }
  }

  async function issue(body: { enrolment_ids?: string[]; course_id?: string }) {
    const r = await api.post<IssueDueResult>("admin/certificates/due/issue", body, { idempotencyKey: true });
    const out = r.kind === "ok" ? r.data : null;
    toast.show({
      tone: out && out.issued ? "success" : "warning",
      title: out && out.issued ? `${out.issued} certificate${out.issued === 1 ? "" : "s"} issued` : "Nothing issued",
      description: out && out.skipped.length ? `${out.skipped.length} not eligible yet.` : undefined,
    });
    await due.reload();
    onChanged();
  }

  async function issueOne(row: DueRow) {
    setBusy(row.enrolment_id);
    try {
      await issue({ enrolment_ids: [row.enrolment_id] });
    } catch (err) {
      fail(err, "Couldn't issue the certificate");
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="space-y-4 pt-4">
      <Card
        title="Learners due a certificate"
        description="Completed enrolments and enrolments in batches that have ended, without a certificate. Only learners who meet the course's certificate rule can be issued one."
        actions={
          <>
            {!previewed && eligible ? <span className="text-sm text-fg-muted">Preview one certificate first.</span> : null}
            <Button variant="secondary" disabled={!firstEligible} loading={busy === `preview:${firstEligible?.enrolment_id}`} onClick={() => firstEligible && void preview(firstEligible)}>
              Preview a certificate
            </Button>
            <Button onClick={() => setConfirmAll(true)} disabled={!eligible || !previewed}>
              {`Issue all eligible (${eligible})`}
            </Button>
          </>
        }
        padding="none"
      >
        <Table<DueRow>
          caption="Due certificates"
          rows={due.data?.data}
          rowKey={(r) => r.enrolment_id}
          loading={due.loading}
          error={due.error}
          onRetry={() => void due.reload()}
          empty={{ title: "Nobody is due a certificate", description: "When a learner completes a course or their batch ends, they appear here until a certificate is issued.", icon: "check" }}
          columns={[
            { key: "learner", header: "Learner", cell: (r) => <Learner name={r.name} email={r.email} /> },
            { key: "course", header: "Course", cell: (r) => r.course_title ?? "—" },
            {
              key: "why",
              header: "Due because",
              cell: (r) => (r.due_because === "completed" ? `Completed ${formatDate(r.completed_at)}` : `Batch ${r.batch_name ?? ""} ended ${formatDate(r.batch_ends_on)}`),
              priority: "secondary",
            },
            { key: "progress", header: "Progress", cell: (r) => `${Math.round(r.progress_pct)}%`, priority: "secondary" },
            {
              key: "state",
              header: "Rule",
              cell: (r) =>
                r.eligible ? (
                  <Badge tone="success" dot>
                    Eligible
                  </Badge>
                ) : (
                  <Badge tone="neutral">{reasonLabel(r.reason)}</Badge>
                ),
            },
            {
              key: "action",
              header: <span className="sr-only">Issue</span>,
              align: "right",
              cell: (r) =>
                r.eligible ? (
                  <div className="flex justify-end gap-2">
                    <Button size="sm" variant="ghost" loading={busy === `preview:${r.enrolment_id}`} onClick={() => void preview(r)} aria-label={`Preview certificate for ${r.name ?? r.email ?? "learner"}`}>
                      Preview
                    </Button>
                    <Button size="sm" loading={busy === r.enrolment_id} onClick={() => void issueOne(r)} aria-label={`Issue certificate to ${r.name ?? r.email ?? "learner"}`}>
                      Issue
                    </Button>
                  </div>
                ) : null,
            },
          ]}
        />
      </Card>
      <ConfirmDialog
        open={confirmAll}
        onClose={() => setConfirmAll(false)}
        title={`Issue ${eligible} certificate${eligible === 1 ? "" : "s"}?`}
        description="Each eligible learner gets a certificate with a PDF. Their emails follow the auto-send setting (otherwise they wait in the approval queue)."
        confirmLabel="Issue certificates"
        onConfirm={() => issue(courseId ? { course_id: courseId } : {})}
      />
    </div>
  );
}

/* ------------------------------------------------------------------ Approval queue */

const QUEUE_FILTERS: { value: OutboxStatus; label: string }[] = [
  { value: "awaiting", label: "Awaiting approval" },
  { value: "pending", label: "Sending" },
  { value: "failed", label: "Failed" },
  { value: "sent", label: "Sent" },
  { value: "cancelled", label: "Cancelled" },
];

function QueueTab({ courseId, onChanged }: { courseId: string; onChanged: () => void }) {
  const [status, setStatus] = useState<OutboxStatus>("awaiting");
  const [stack, setStack] = useState<(string | undefined)[]>([undefined]);
  const queue = useApi<CursorPage<OutboxRow>>("admin/certificates/outbox", { status, course_id: courseId || undefined, cursor: stack[stack.length - 1], limit: 50 });
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState(false);
  const fail = useFailToast();
  const toast = useToast();
  const rows = queue.data?.data;
  const actionable = (r: OutboxRow) => r.status === "awaiting" || r.status === "failed" || r.status === "pending";
  const approvable = (r: OutboxRow) => r.status === "awaiting" || r.status === "failed";

  async function run(kind: "approve" | "cancel", ids: string[]) {
    if (!ids.length) return;
    setBusy(true);
    try {
      const r = await api.post<ApproveResult & { cancelled?: number }>(`admin/certificates/outbox/${kind}`, { ids }, { idempotencyKey: true });
      const out = r.kind === "ok" ? r.data : null;
      if (kind === "approve")
        toast.show({
          tone: out && out.failed ? "warning" : "success",
          title: `${out?.approved ?? 0} approved`,
          description: out ? `${out.sent} sent${out.pending ? `, ${out.pending} sending shortly` : ""}${out.failed ? `, ${out.failed} failed` : ""}.` : undefined,
        });
      else toast.show({ tone: "success", title: `${out?.cancelled ?? 0} cancelled` });
      setSelected(new Set());
      await queue.reload();
      onChanged();
    } catch (err) {
      fail(err, kind === "approve" ? "Couldn't send the emails" : "Couldn't cancel the emails");
    } finally {
      setBusy(false);
    }
  }

  const toggle = (id: string) =>
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  const selectable = (rows ?? []).filter(actionable);
  const allSelected = selectable.length > 0 && selectable.every((r) => selected.has(r.id));
  const chosen = (rows ?? []).filter((r) => selected.has(r.id));

  return (
    <div className="space-y-4 pt-4">
      <Segmented
        legend="Show"
        hideLegend
        name="queue-status"
        variant="pills"
        value={status}
        onChange={(v) => {
          setStatus(v);
          setSelected(new Set());
          setStack([undefined]);
        }}
        options={QUEUE_FILTERS.map((f) => ({ ...f, label: queue.data?.counts?.[f.value] !== undefined ? `${f.label} (${queue.data.counts[f.value]})` : f.label }))}
      />
      <Table<OutboxRow>
        caption="Certificate emails"
        rows={rows}
        rowKey={(r) => r.id}
        loading={queue.loading}
        error={queue.error}
        onRetry={() => void queue.reload()}
        toolbar={
          selectable.length ? (
            <div className="flex flex-wrap items-center gap-3">
              <Checkbox
                label={allSelected ? "Clear selection" : "Select all"}
                checked={allSelected}
                onChange={() => setSelected(allSelected ? new Set() : new Set(selectable.map((r) => r.id)))}
              />
              <Button size="sm" loading={busy} disabled={!chosen.some(approvable)} onClick={() => void run("approve", chosen.filter(approvable).map((r) => r.id))}>
                {`Approve & send (${chosen.filter(approvable).length})`}
              </Button>
              <Button size="sm" variant="secondary" disabled={busy || !chosen.length} onClick={() => void run("cancel", chosen.map((r) => r.id))}>
                {`Cancel (${chosen.length})`}
              </Button>
            </div>
          ) : undefined
        }
        empty={{
          title: status === "awaiting" ? "Nothing waiting for approval" : "No emails here",
          description: status === "awaiting" ? "Certificate emails wait here while auto-send is off." : undefined,
          icon: "inbox",
        }}
        columns={[
          {
            key: "pick",
            header: <span className="sr-only">Select</span>,
            cell: (r) =>
              actionable(r) ? (
                <input
                  type="checkbox"
                  className="h-4 w-4 accent-[var(--color-brand,#10224f)]"
                  aria-label={`Select ${outboxItem(r)?.name ?? r.id}`}
                  checked={selected.has(r.id)}
                  onChange={() => toggle(r.id)}
                />
              ) : null,
          },
          { key: "learner", header: "Recipient", cell: (r) => <Learner name={outboxItem(r)?.name ?? null} email={outboxItem(r)?.email ?? null} /> },
          {
            key: "course",
            header: "Document",
            cell: (r) => (
              <div className="min-w-0">
                <p className="text-fg">{outboxItem(r)?.title ?? "—"}</p>
                <p className="text-xs text-fg-muted">{outboxItem(r)?.label}</p>
              </div>
            ),
          },
          { key: "code", header: "Number", cell: (r) => <span className="font-mono text-sm">{outboxItem(r)?.number}</span>, priority: "secondary" },
          { key: "queued", header: "Queued", cell: (r) => formatDateTime(r.created_at, { year: true }), priority: "secondary" },
          {
            key: "status",
            header: "Status",
            cell: (r) => (
              <div>
                <EmailBadge status={r.status} />
                {r.last_error ? <p className="mt-1 text-xs text-danger-fg">{r.last_error}</p> : null}
                {r.sent_at ? <p className="mt-1 text-xs text-fg-muted">{formatDateTime(r.sent_at, { year: true })}</p> : null}
              </div>
            ),
          },
          {
            key: "actions",
            header: <span className="sr-only">Actions</span>,
            align: "right",
            cell: (r) => (
              <div className="flex flex-wrap justify-end gap-2">
                {approvable(r) ? (
                  <Button size="sm" disabled={busy} onClick={() => void run("approve", [r.id])} aria-label={`Approve and send to ${outboxItem(r)?.name ?? r.id}`}>
                    {r.status === "failed" ? "Retry" : "Approve & send"}
                  </Button>
                ) : null}
                {actionable(r) ? (
                  <Button size="sm" variant="ghost" disabled={busy} onClick={() => void run("cancel", [r.id])} aria-label={`Cancel email to ${outboxItem(r)?.name ?? r.id}`}>
                    Cancel
                  </Button>
                ) : null}
              </div>
            ),
          },
        ]}
      />
      <Pagination
        hasMore={Boolean(queue.data?.page.has_more)}
        hasPrevious={stack.length > 1}
        loading={queue.loading}
        onNext={() => setStack((st) => nextCursorStack(st, queue.data?.page.next_cursor ?? null))}
        onPrevious={() => setStack((st) => previousCursorStack(st))}
        label="Email pages"
      />
    </div>
  );
}

/* ------------------------------------------------------------------ Settings */

function SettingsTab({ onChanged }: { onChanged: () => void }) {
  const settings = useApi<{ auto_send: boolean; flag_key: string }>("admin/certificates/settings");
  const [busy, setBusy] = useState(false);
  const fail = useFailToast();
  const toast = useToast();
  const on = settings.data?.auto_send ?? false;

  async function setAuto(next: boolean) {
    setBusy(true);
    try {
      await api.put("admin/certificates/settings", { auto_send: next });
      toast.show({ tone: "success", title: next ? "Auto-send turned on" : "Auto-send turned off" });
      await settings.reload();
      onChanged();
    } catch (err) {
      fail(err, "Couldn't change the setting");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="pt-4">
      <Card title="Certificate emails" description="Every certificate gets a PDF and an email to the learner with the PDF attached.">
        <div className="space-y-4">
          <Checkbox
            label="Send certificate emails automatically"
            description={
              on
                ? "On: emails go out within a minute of issue. Turn off to review each one in the approval queue first."
                : "Off (recommended while testing): emails wait in the approval queue until an admin approves them."
            }
            checked={on}
            disabled={busy || settings.loading || Boolean(settings.error)}
            onChange={(e) => void setAuto(e.target.checked)}
          />
          <p className="text-sm text-fg-secondary">
            A daily job also issues certificates to learners whose batch has ended and who meet the course&apos;s certificate rule. Their emails follow this setting.
          </p>
        </div>
      </Card>
    </div>
  );
}
