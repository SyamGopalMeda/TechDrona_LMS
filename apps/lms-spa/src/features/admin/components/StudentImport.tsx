"use client";

import { useEffect, useMemo, useRef, useState, type ChangeEvent } from "react";
import { Badge, Button, Card, Checkbox, Dialog, FormField, InlineProblem, PageHeader, Select, StatGrid, StatTile, Table, buttonClasses, useToast, type Column } from "@/components/ui";
import { api } from "@/lib/api/client";
import { useResource } from "@/lib/api/use-resource";
import { ActionDialog, TextArea } from "./console-ui";
import { toOutcome } from "../lib/console";
import {
  APPLY_CHUNK,
  ENROL_CHUNK,
  MAX_ROWS,
  chunk,
  downloadResults,
  downloadTemplate,
  loginMessage,
  mergeResponses,
  parseStudentFile,
  statusWord,
  whatsappLink,
  type ImportOptions,
  type ImportResponse,
  type ImportRow,
  type ImportRowResult,
} from "../lib/student-import";


async function copyText(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    return false;
  }
}

function useCopy() {
  const toast = useToast();
  return (text: string, what: string) =>
    void copyText(text).then((ok) => toast.show(ok ? { title: `${what} copied.`, tone: "success" } : { title: "Couldn't copy. Select the text and copy it yourself.", tone: "warning" }));
}

const courseOptions = (o: ImportOptions | undefined, none = "No course") => [{ value: "", label: none }, ...(o?.courses ?? []).map((c) => ({ value: c.id, label: `${c.title} (${c.slug})` }))];
const batchOptions = (o: ImportOptions | undefined, none = "No batch") => [{ value: "", label: none }, ...(o?.batches ?? []).map((b) => ({ value: b.id, label: `${b.name} (${b.code})` }))];
const TYPE_OPTIONS = [
  { value: "course", label: "Course student" },
  { value: "internship", label: "Internship student" },
];

function StatusCell({ r }: { r: ImportRowResult }) {
  const tone = r.status === "error" ? "danger" : r.status === "existing" ? "info" : "success";
  return <Badge tone={tone}>{statusWord(r.status)}</Badge>;
}

function Messages({ r }: { r: ImportRowResult }) {
  if (!r.errors.length && !r.warnings.length) return <span className="text-fg-secondary">—</span>;
  return (
    <ul className="space-y-0.5 text-sm">
      {r.errors.map((m) => (
        <li key={`e-${m}`} className="font-medium text-danger-fg">
          {m}
        </li>
      ))}
      {r.warnings.map((m) => (
        <li key={`w-${m}`} className="text-warning-fg">
          {m}
        </li>
      ))}
    </ul>
  );
}

/** Copy / WhatsApp for one person's login details (Add user, and each imported row). */
export function CredentialsPanel({ name, username, email, password, mustChange, phone }: { name: string; username: string | null; email: string | null; password: string | null; mustChange: boolean; phone?: string | null }) {
  const copy = useCopy();
  const message = loginMessage({ name, username, email, password, mustChange });
  return (
    <div className="space-y-3">
      {password ? (
        <p role="note" className="rounded-md border border-warning-border bg-warning-subtle p-3 text-sm text-warning-fg">
          <span className="font-semibold">The password is shown only once.</span> Copy it or share it on WhatsApp now: it can&apos;t be shown again after you close this.
        </p>
      ) : null}
      <dl className="rounded-md bg-surface-sunken px-3">
        {[
          { label: "Username", value: username, mono: true },
          { label: "Email", value: email, mono: false },
          { label: "Temporary password", value: password, mono: true },
        ]
          .filter((x) => x.value)
          .map((x) => (
            <div key={x.label} className="flex items-center justify-between gap-3 border-b border-line py-2 last:border-b-0">
              <div className="min-w-0">
                <dt className="text-xs text-fg-secondary">{x.label}</dt>
                <dd className={x.mono ? "select-all break-all font-mono text-base font-semibold" : "break-all text-sm"}>{x.value}</dd>
              </div>
              <Button size="sm" variant="secondary" aria-label={`Copy ${x.label.toLowerCase()}`} onClick={() => copy(x.value!, x.label)}>
                Copy
              </Button>
            </div>
          ))}
      </dl>
      {password && mustChange ? <p className="text-sm text-fg-secondary">They must choose a new password when they first log in.</p> : null}
      <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
        <Button variant="secondary" onClick={() => copy(message, "Login details")}>
          Copy all
        </Button>
        <a className={buttonClasses({ variant: "primary" })} href={whatsappLink(phone, message)} target="_blank" rel="noreferrer">
          Share on WhatsApp
        </a>
      </div>
    </div>
  );
}

/**
 * Enrol EXISTING accounts (Users list selection, batch page) in a course and/or batch:
 * `POST admin/students/import` with `user_ids` (same API as the import).
 */
export function EnrolDialog({ open, onClose, userIds, defaultBatchId, onDone }: { open: boolean; onClose: () => void; userIds: string[]; defaultBatchId?: string; onDone?: (r: ImportResponse) => void }) {
  const toast = useToast();
  const options = useResource<ImportOptions>(open ? "admin/students/import/options" : null);
  const [course, setCourse] = useState("");
  const [batch, setBatch] = useState(defaultBatchId ?? "");
  const [studentType, setStudentType] = useState("");
  const [reason, setReason] = useState("");
  const n = userIds.length;
  return (
    <ActionDialog<ImportResponse>
      open={open}
      onClose={onClose}
      onOpen={() => {
        setCourse("");
        setBatch(defaultBatchId ?? "");
        setStudentType("");
        setReason("");
      }}
      title={`Enrol ${n} ${n === 1 ? "student" : "students"}`}
      description="Adds them to the batch and gives them the course. Anyone already enrolled is left as is."
      submitLabel="Enrol"
      validate={() => (!n ? "Select at least one student." : n > MAX_ROWS ? `Select at most ${MAX_ROWS} students at a time.` : !course && !batch ? "Choose a course or a batch." : null)}
      onSubmit={async () => {
        // Chunks keep each request well inside the API's 60 s limit; results are merged.
        const parts: ImportResponse[] = [];
        let requestId: string | null = null;
        for (const ids of chunk(userIds, ENROL_CHUNK)) {
          const res = await api.post<ImportResponse>(
            "admin/students/import",
            { user_ids: ids, course: course || null, batch: batch || null, student_type: studentType || null, reason: reason.trim() || null },
            { idempotencyKey: true },
          );
          if (res.kind !== "ok") return toOutcome(res);
          parts.push(res.data);
          requestId = res.requestId;
        }
        return { kind: "ok" as const, data: mergeResponses(parts), status: 200, requestId };
      }}
      onDone={(o) => {
        if (o.kind !== "ok") return;
        const c = o.data.counts;
        const firstError = o.data.rows.find((r) => r.errors.length)?.errors[0];
        toast.show({
          title: `${c.enrolled} enrolled in the course, ${c.added_to_batch} added to the batch.`,
          description: c.errors ? `${c.errors} not enrolled${firstError ? `: ${firstError}` : "."}` : c.existing - c.enrolled > 0 ? "Students already enrolled were left as they were." : undefined,
          tone: c.errors ? "warning" : "success",
        });
        onDone?.(o.data);
      }}
    >
      <InlineProblem error={options.error} />
      <FormField label="Course" hint="Published courses. Leave empty to only add them to the batch.">
        {(f) => <Select {...f} value={course} onChange={(e) => setCourse(e.target.value)} options={courseOptions(options.data)} />}
      </FormField>
      <FormField label="Batch" hint="Optional. When the batch has its own course and no course is chosen, they get that course.">
        {(f) => <Select {...f} value={batch} onChange={(e) => setBatch(e.target.value)} options={batchOptions(options.data)} />}
      </FormField>
      <FormField label="Student type" hint="Optional. Leave unchanged, or record them as course / internship students.">
        {(f) => <Select {...f} value={studentType} onChange={(e) => setStudentType(e.target.value)} options={[{ value: "", label: "Leave unchanged" }, ...TYPE_OPTIONS]} />}
      </FormField>
      <FormField label="Reason" hint="Optional. Kept in the audit log.">
        {(f) => <TextArea {...f} value={reason} onChange={(e) => setReason(e.target.value)} maxLength={500} />}
      </FormField>
    </ActionDialog>
  );
}

type Stage = "upload" | "preview" | "done";

/**
 * Admin › Users › Import students: template → upload (.xlsx / .csv, parsed in the browser) →
 * dry run preview (new / existing / errors) → import → results with the one-time login details.
 */
export function ImportStudents({ initialBatchId = "" }: { initialBatchId?: string }) {
  const toast = useToast();
  const options = useResource<ImportOptions>("admin/students/import/options");
  const o = options.data;
  const fileInput = useRef<HTMLInputElement>(null);
  const [stage, setStage] = useState<Stage>("upload");
  const [fileName, setFileName] = useState("");
  const [rows, setRows] = useState<ImportRow[]>([]);
  const [fileProblem, setFileProblem] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [preview, setPreview] = useState<ImportResponse | null>(null);
  const [result, setResult] = useState<ImportResponse | null>(null);
  const [onlyProblems, setOnlyProblems] = useState(false);
  const [defaults, setDefaults] = useState({ course: "", batch: initialBatchId, student_type: "course" });
  const [confirmAdult, setConfirmAdult] = useState(false);
  const [sendEmail, setSendEmail] = useState(false);
  const [reason, setReason] = useState("");
  const [downloaded, setDownloaded] = useState(false);
  const [sendLogin, setSendLogin] = useState(false);
  const [shareRow, setShareRow] = useState<ImportRowResult | null>(null);
  const [progress, setProgress] = useState<string | null>(null);

  // Leaving with login details that were never downloaded loses the passwords for good.
  const unsaved = !!result && !downloaded && result.rows.some((r) => r.temporary_password);
  useEffect(() => {
    if (!unsaved) return;
    const warn = (e: BeforeUnloadEvent) => {
      e.preventDefault();
      e.returnValue = "";
    };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [unsaved]);

  const body = (dry: boolean) => ({
    rows,
    course: defaults.course || null,
    batch: defaults.batch || null,
    student_type: (defaults.student_type || null) as "course" | "internship" | null,
    must_change_password: true,
    confirm_adult: dry ? false : confirmAdult,
    send_email: !dry && sendEmail && !!o?.email_integrated,
    reason: reason.trim() || null,
  });

  const runDry = async (list: ImportRow[] = rows) => {
    if (!list.length) return;
    setBusy(true);
    setError(null);
    try {
      const res = await api.post<ImportResponse>("admin/students/import", { ...body(true), rows: list }, { query: { dry_run: true } });
      if (res.kind === "ok") {
        setPreview(res.data);
        setStage("preview");
      }
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  };

  const onFile = async (e: ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    setFileProblem(null);
    setError(null);
    setPreview(null);
    setFileName(file.name);
    if (!/\.(xlsx|xls|csv)$/i.test(file.name)) {
      setFileProblem("Choose an Excel (.xlsx) or CSV file.");
      return;
    }
    setBusy(true);
    try {
      const parsed = await parseStudentFile(file);
      if (parsed.missing.length) {
        setFileProblem(`The file has no ${parsed.missing.join(" / ")} column. Use the template's header row.`);
        return;
      }
      if (!parsed.rows.length) {
        setFileProblem("No student rows found under the header row.");
        return;
      }
      if (parsed.rows.length > MAX_ROWS) {
        setFileProblem(`The file has ${parsed.rows.length} rows; import at most ${MAX_ROWS} at a time (split the file).`);
        return;
      }
      setRows(parsed.rows);
      if (parsed.ignored.length) toast.show({ title: "Some columns were ignored", description: parsed.ignored.join(", "), tone: "warning" });
      setBusy(false);
      await runDry(parsed.rows);
    } catch {
      setFileProblem("This file couldn't be read. Save it as .xlsx (or .csv) and try again.");
    } finally {
      setBusy(false);
    }
  };

  /**
   * Only the rows the preview found valid are sent, APPLY_CHUNK at a time (each request is
   * idempotent and well inside the API's 60 s limit). If a request fails part-way, the rows already
   * imported are still shown with their login details; importing the file again links them.
   */
  const apply = async () => {
    if (!preview) return;
    const bad = preview.rows.filter((r) => r.status === "error");
    const okRows = new Set(preview.rows.filter((r) => r.status !== "error").map((r) => r.row));
    const parts = chunk(
      rows.filter((r) => okRows.has(r.row)),
      APPLY_CHUNK,
    );
    const done: ImportResponse[] = [];
    setBusy(true);
    setError(null);
    try {
      for (const [i, part] of parts.entries()) {
        setProgress(`Importing ${i * APPLY_CHUNK + 1}–${i * APPLY_CHUNK + part.length} of ${okRows.size}…`);
        const res = await api.post<ImportResponse>("admin/students/import", { ...body(false), rows: part }, { idempotencyKey: true });
        if (res.kind === "ok") done.push(res.data);
      }
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
      setProgress(null);
    }
    if (!done.length) return;
    const merged = mergeResponses(done, bad);
    setResult(merged);
    setDownloaded(false);
    setStage("done");
    const c = merged.counts;
    toast.show({ title: `${c.created} accounts created, ${c.existing} existing linked.`, description: c.errors ? `${c.errors} rows had errors.` : undefined, tone: c.errors ? "warning" : "success" });
  };

  const reset = () => {
    if (unsaved && !window.confirm("The login details haven't been downloaded. Start a new import anyway? The passwords can't be shown again.")) return;
    setStage("upload");
    setRows([]);
    setPreview(null);
    setResult(null);
    setFileName("");
    setConfirmAdult(false);
    setSendEmail(false);
    setReason("");
    setError(null);
  };

  const download = async (format: "xlsx" | "csv") => {
    if (!result) return;
    await downloadResults(result.rows, format);
    setDownloaded(true);
  };

  const shown = useMemo(() => {
    const list = (stage === "done" ? result : preview)?.rows ?? [];
    return onlyProblems ? list.filter((r) => r.errors.length || r.warnings.length) : list;
  }, [stage, result, preview, onlyProblems]);

  const cols: Column<ImportRowResult>[] = [
    { key: "row", header: "Row", cell: (r) => r.row },
    {
      key: "name",
      header: "Student",
      cell: (r) => (
        <span className="block min-w-0">
          <span className="block font-medium">{r.full_name || "—"}</span>
          <span className="block break-all text-sm text-fg-secondary">{r.email ?? "—"}</span>
        </span>
      ),
    },
    { key: "type", header: "Type", priority: "secondary", cell: (r) => (r.student_type === "internship" ? "Internship" : r.student_type === "course" ? "Course" : "—") },
    { key: "course", header: "Course / batch", cell: (r) => [r.course?.title, r.batch?.name].filter(Boolean).join(" · ") || "—" },
    { key: "status", header: "Status", cell: (r) => <StatusCell r={r} /> },
    ...(stage === "done"
      ? [
          { key: "username", header: "Username", cell: (r: ImportRowResult) => (r.username ? <span className="font-mono">{r.username}</span> : "—") },
          {
            key: "password",
            header: "Temporary password",
            cell: (r: ImportRowResult) => (r.temporary_password ? <span className="select-all font-mono font-semibold">{r.temporary_password}</span> : "—"),
          },
          {
            key: "share",
            header: <span className="sr-only">Share</span>,
            cell: (r: ImportRowResult) =>
              r.username && r.status !== "error" ? (
                <Button size="sm" variant="secondary" aria-label={`Share login details of ${r.full_name}`} onClick={() => setShareRow(r)}>
                  Share
                </Button>
              ) : null,
          },
        ]
      : []),
    { key: "messages", header: "Messages", cell: (r) => <Messages r={r} /> },
  ];

  const counts = (stage === "done" ? result : preview)?.counts;
  const createdIds = (result?.rows ?? []).filter((r) => r.status === "created" && r.user_id).map((r) => r.user_id!);
  const valid = preview ? preview.counts.new + preview.counts.existing : 0;
  const phoneOf = (r: ImportRowResult) => rows.find((x) => x.row === r.row)?.mobile ?? null;

  return (
    <div className="space-y-6">
      <PageHeader
        breadcrumbs={[{ label: "Users", href: "/admin/users" }, { label: "Import students" }]}
        title="Import students"
        description="Create many student accounts from an Excel or CSV file and enrol them in a course or batch. Existing accounts (same email) are linked, never created twice."
        actions={
          <Button variant="secondary" onClick={() => void downloadTemplate(o)}>
            Download template
          </Button>
        }
      />

      {stage === "upload" ? (
        <Card title="Upload the file" description={`Fill in the template (one student per row, at most ${MAX_ROWS}), then choose the file. Nothing is created until you confirm the preview.`}>
          <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
            <FormField label="Course for rows without one" hint="Optional default.">
              {(f) => <Select {...f} value={defaults.course} onChange={(e) => setDefaults((d) => ({ ...d, course: e.target.value }))} options={courseOptions(o)} />}
            </FormField>
            <FormField label="Batch for rows without one" hint="Optional default.">
              {(f) => <Select {...f} value={defaults.batch} onChange={(e) => setDefaults((d) => ({ ...d, batch: e.target.value }))} options={batchOptions(o)} />}
            </FormField>
            <FormField label="Student type for rows without one">
              {(f) => <Select {...f} value={defaults.student_type} onChange={(e) => setDefaults((d) => ({ ...d, student_type: e.target.value }))} options={TYPE_OPTIONS} />}
            </FormField>
          </div>
          <div className="mt-4 flex flex-wrap items-center gap-3">
            <input ref={fileInput} type="file" accept=".xlsx,.xls,.csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,text/csv" className="sr-only" aria-label="Choose the student file" onChange={(e) => void onFile(e)} />
            <Button onClick={() => fileInput.current?.click()} disabled={busy}>
              {busy ? "Checking…" : "Choose file"}
            </Button>
            {fileName ? <span className="text-sm text-fg-secondary">{fileName}</span> : null}
          </div>
          {fileProblem ? (
            <p role="alert" className="mt-3 text-sm font-medium text-danger-fg">
              {fileProblem}
            </p>
          ) : null}
          <InlineProblem error={error ?? options.error} />
        </Card>
      ) : null}

      {counts ? (
        <StatGrid columns={4}>
          <StatTile label="Rows" value={counts.total} />
          <StatTile label={stage === "done" ? "Created" : "New accounts"} value={stage === "done" ? counts.created : counts.new} />
          <StatTile label="Existing accounts" value={counts.existing} />
          <StatTile label="Errors" value={counts.errors} />
        </StatGrid>
      ) : null}

      {stage === "preview" && preview ? (
        <Card title={`Preview of ${fileName}`} description="Rows with errors are skipped. Fix them in the file and choose it again, or import the valid rows now.">
          <div className="space-y-4">
            <Checkbox label="Every student in this file is 18 or older" description="Under-18 learners must sign up themselves so a parent can give consent." checked={confirmAdult} onChange={(e) => setConfirmAdult(e.target.checked)} />
            <Checkbox
              label="Email the login details to each new student"
              description={o?.email_integrated ? "Each new student gets their username and temporary password by email." : "Email isn't connected yet: download the results and share the details yourself (for example on WhatsApp)."}
              checked={sendEmail && !!o?.email_integrated}
              disabled={!o?.email_integrated}
              onChange={(e) => setSendEmail(e.target.checked)}
            />
            <FormField label="Reason" hint="Optional. Kept in the audit log, for example: March internship intake.">
              {(f) => <TextArea {...f} value={reason} onChange={(e) => setReason(e.target.value)} maxLength={500} />}
            </FormField>
            <InlineProblem error={error} />
            <div className="flex flex-wrap gap-2">
              <Button onClick={() => void apply()} disabled={busy || !confirmAdult || valid === 0}>
                {busy ? (progress ?? "Importing…") : `Import ${valid} ${valid === 1 ? "student" : "students"}`}
              </Button>
              <Button variant="secondary" onClick={reset} disabled={busy}>
                Choose another file
              </Button>
            </div>
            {!confirmAdult ? <p className="text-sm text-fg-secondary">Tick the 18+ confirmation to import.</p> : null}
          </div>
        </Card>
      ) : null}

      {stage === "done" && result ? (
        <Card title="Import finished" description={result.credentials_withheld ? "This repeats an earlier import: the temporary passwords were shown only the first time." : undefined}>
          <div className="space-y-4">
            {error ? (
              <div role="alert" className="space-y-1 rounded-md border border-danger-border bg-danger-subtle p-3 text-sm text-danger-fg">
                <p className="font-semibold">The import stopped part-way. The rows below were imported; the others were not.</p>
                <p>Download these login details first, then import the same file again: accounts already created are linked, never duplicated.</p>
                <InlineProblem error={error} />
              </div>
            ) : null}
            {result.rows.some((r) => r.temporary_password) ? (
              <p role="note" className="rounded-md border border-warning-border bg-warning-subtle p-3 text-sm text-warning-fg">
                <span className="font-semibold">Download the login details now.</span> The temporary passwords are shown only on this page and in the download; they are not stored and can&apos;t be shown again.
              </p>
            ) : null}
            <div className="flex flex-wrap gap-2">
              <Button onClick={() => void download("xlsx")}>Download results (.xlsx)</Button>
              <Button variant="secondary" onClick={() => void download("csv")}>
                Download .csv
              </Button>
              <Button variant="secondary" disabled={!o?.email_integrated || !createdIds.length} onClick={() => setSendLogin(true)}>
                Send login details
              </Button>
              <Button variant="ghost" onClick={reset}>
                Import another file
              </Button>
            </div>
            {!o?.email_integrated ? <p className="text-sm text-fg-secondary">Send login details works once email is connected. Until then, share the downloaded details yourself (Share opens WhatsApp).</p> : null}
          </div>
        </Card>
      ) : null}

      {stage !== "upload" ? (
        <Table
          caption={stage === "done" ? "Import results" : "Import preview"}
          columns={cols}
          rows={shown}
          rowKey={(r) => String(r.row)}
          toolbar={<Checkbox label="Only rows with errors or warnings" checked={onlyProblems} onChange={(e) => setOnlyProblems(e.target.checked)} />}
          empty={{ title: onlyProblems ? "No problems" : "No rows", description: onlyProblems ? "Every row is fine." : undefined }}
        />
      ) : null}

      <ActionDialog<{ counts: { total: number; sent: number } }>
        open={sendLogin}
        onClose={() => setSendLogin(false)}
        title="Send login details by email?"
        description={`Each of the ${createdIds.length} new students gets a NEW temporary password by email. The passwords in your download stop working.`}
        submitLabel="Send"
        onSubmit={async () => toOutcome(await api.post<{ counts: { total: number; sent: number } }>("admin/students/send-login", { user_ids: createdIds, must_change_password: true }, { idempotencyKey: true }))}
        onDone={(res) => {
          if (res.kind === "ok") toast.show({ title: `Login details sent to ${res.data.counts.sent} of ${res.data.counts.total} students.`, tone: res.data.counts.sent === res.data.counts.total ? "success" : "warning" });
        }}
      />

      <Dialog open={shareRow !== null} onClose={() => setShareRow(null)} title="Login details" description={shareRow?.full_name} footer={<Button onClick={() => setShareRow(null)}>Done</Button>}>
        {shareRow ? <CredentialsPanel name={shareRow.full_name} username={shareRow.username} email={shareRow.email} password={shareRow.temporary_password} mustChange phone={phoneOf(shareRow)} /> : null}
      </Dialog>
    </div>
  );
}
