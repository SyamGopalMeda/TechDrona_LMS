"use client";

/**
 * Create & send > Bulk: many documents of one type from an Excel / CSV upload or from picked
 * students. Steps: choose type + source -> check every row (server) -> preview at least one PDF ->
 * issue in chunks of 25 with progress -> results (this run's register, ZIP of PDFs, results .xlsx
 * with references and verification links). API: `/admin/documents/bulk/*` (doc_admin.py).
 */

import Link from "next/link";
import { useMemo, useRef, useState } from "react";
import { Badge, Button, Card, Checkbox, ConfirmDialog, FormField, Input, ProgressBar, Segmented, Select, Table, useToast } from "@/components/ui";
import { api, type Page } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import { useApi, seg } from "@/features/trainer/shared/use-api";
import { useFailToast } from "@/features/trainer/shared/ui";
import type { Batch } from "@/features/batches/lib/types";
import type { CourseSummary } from "@/features/studio/lib/types";
import { pdfUrlFromBase64, type DocField, type DocTypeDef, type DocTypesResponse, type Prefill, type PreviewResult } from "../lib/docs";
import {
  ISSUE_CHUNK,
  MAX_ROWS,
  PDF_CHUNK,
  XLSX_MIME,
  absoluteUrl,
  buildResults,
  buildTemplate,
  emailText,
  issueInChunks,
  loadXlsx,
  parseFile,
  rowBody,
  saveBytes,
  slug,
  withCommon,
  type BulkEnrolment,
  type BulkIssueResult,
  type BulkIssueRowResult,
  type BulkPdfsResult,
  type BulkRow,
  type BulkRunResponse,
  type BulkValidateResult,
  type IssueProgress,
  type ParsedSheet,
} from "../lib/bulk";
import { base64ToBytes, makeZip } from "../lib/zip";
import { formatDate } from "@/lib/format";

type Source = "file" | "students";
type EmailMode = "outbox" | "none";

function openPdf(b64: string) {
  const url = pdfUrlFromBase64(b64);
  window.open(url, "_blank", "noopener,noreferrer");
  window.setTimeout(() => URL.revokeObjectURL(url), 60_000);
}

/** Network failures and gateway timeouts are worth one retry with the same idempotency key. */
const retryable = (err: unknown) => err instanceof ApiError && (err.status === 0 || err.status === 502 || err.status === 503 || err.status === 504);

function today(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

/** Run `fn` over `items` with at most `n` in flight. */
async function pool<T, R>(items: T[], n: number, fn: (x: T, i: number) => Promise<R>): Promise<R[]> {
  const out: R[] = new Array(items.length);
  let next = 0;
  await Promise.all(
    Array.from({ length: Math.min(n, items.length) }, async () => {
      while (next < items.length) {
        const i = next++;
        out[i] = await fn(items[i]!, i);
      }
    }),
  );
  return out;
}

/** A document field for the "same for every row" card (mirrors AdminDocuments' FieldInput). */
function CommonField({ field, value, onChange }: { field: DocField; value: string; onChange: (v: string) => void }) {
  return (
    <FormField label={field.label} hint={field.hint}>
      {(p) =>
        field.kind === "select" ? (
          <Select {...p} value={value} onChange={(e) => onChange(e.target.value)} options={[{ value: "", label: "From the file" }, ...(field.options ?? []).map((o) => ({ value: o, label: o }))]} />
        ) : (
          <Input {...p} type={field.kind === "date" ? "date" : "text"} value={value} onChange={(e) => onChange(e.target.value)} />
        )
      }
    </FormField>
  );
}

export default function BulkCreate({ onIssued }: { onIssued: () => void }) {
  const catalogue = useApi<DocTypesResponse>("admin/documents/types");
  const [docType, setDocType] = useState("cert_internship");
  const [issueDate, setIssueDate] = useState("");
  const [source, setSource] = useState<Source>("file");
  const [rows, setRows] = useState<BulkRow[]>([]);
  const [sheet, setSheet] = useState<(Omit<ParsedSheet, "rows"> & { name: string }) | null>(null);
  const [common, setCommon] = useState<Record<string, string>>({});
  const [check, setCheck] = useState<BulkValidateResult | null>(null);
  const [previewed, setPreviewed] = useState<Set<number>>(new Set());
  const [email, setEmail] = useState<EmailMode>("none");
  const [busy, setBusy] = useState<"" | "template" | "parse" | "check" | "issue" | `preview:${number}`>("");
  const [confirm, setConfirm] = useState(false);
  const [progress, setProgress] = useState<IssueProgress | null>(null);
  const [run, setRun] = useState<{ bulkId: string; def: DocTypeDef; rows: BulkRow[]; results: BulkIssueRowResult[]; skipped: BulkRow[]; email: EmailMode } | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const fail = useFailToast();
  const toast = useToast();
  const types = catalogue.data?.types;
  const def = types?.find((t) => t.key === docType);
  const effective = useMemo(() => withCommon(rows, common), [rows, common]);
  const checkBy = useMemo(() => new Map((check?.rows ?? []).map((r) => [r.row, r])), [check]);
  const okRows = effective.filter((r) => checkBy.get(r.row)?.ok);
  const badRows = effective.filter((r) => checkBy.has(r.row) && !checkBy.get(r.row)?.ok);
  const settingsProblem = check?.settings_problem ?? catalogue.data?.settings_problem ?? null;

  const typeOptions = useMemo(
    () => [
      ...(types ?? []).filter((t) => t.layout === "certificate").map((t) => ({ value: t.key, label: `Certificate · ${t.label}` })),
      ...(types ?? []).filter((t) => t.layout === "letter").map((t) => ({ value: t.key, label: `Letter · ${t.label}` })),
    ],
    [types],
  );

  /** Anything that changes what would be issued invalidates the check and the previews. */
  function stale() {
    setCheck(null);
    setPreviewed(new Set());
  }

  function reset() {
    setRows([]);
    setSheet(null);
    setCommon({});
    stale();
    setRun(null);
    setProgress(null);
    if (fileInput.current) fileInput.current.value = "";
  }

  async function validate(list: BulkRow[]) {
    if (!list.length) return;
    setBusy("check");
    try {
      const r = await api.post<BulkValidateResult>("admin/documents/bulk/validate", { doc_type: docType, rows: list.map((x) => rowBody(x, docType)), issue_date: issueDate || undefined });
      if (r.kind === "ok") {
        setCheck(r.data);
        setPreviewed(new Set());
        setEmail(r.data.email_ready ? "outbox" : "none");
      }
    } catch (err) {
      fail(err, "Couldn't check the rows");
    } finally {
      setBusy("");
    }
  }

  async function downloadTemplate() {
    if (!def) return;
    setBusy("template");
    try {
      const x = await loadXlsx();
      saveBytes(buildTemplate(x, def), `${slug(def.short)}-bulk-template.xlsx`, XLSX_MIME);
    } catch (err) {
      fail(err, "Couldn't build the template");
    } finally {
      setBusy("");
    }
  }

  async function onFile(file: File | undefined) {
    if (!file || !def) return;
    setBusy("parse");
    setRun(null);
    stale();
    try {
      const parsed = await parseFile(file, def);
      setRows(parsed.rows);
      setSheet({ name: file.name, unknown: parsed.unknown, missingColumns: parsed.missingColumns, truncated: parsed.truncated });
      setBusy("");
      if (!parsed.rows.length) {
        toast.show({ tone: "warning", title: "No rows found", description: parsed.missingColumns.length ? `Missing columns: ${parsed.missingColumns.join(", ")}.` : "The first sheet has no filled rows under the header." });
        return;
      }
      await validate(withCommon(parsed.rows, common));
    } catch (err) {
      setBusy("");
      toast.show({ tone: "danger", title: "Couldn't read the file", description: err instanceof Error ? err.message : "Use the .xlsx template or a .csv file." });
    }
  }

  async function usePicked(picked: BulkRow[]) {
    setRun(null);
    setSheet(null);
    setRows(picked);
    stale();
    await validate(withCommon(picked, common));
  }

  async function preview(r: BulkRow) {
    setBusy(`preview:${r.row}`);
    try {
      const b = rowBody(r, docType);
      const recipient = Object.fromEntries(Object.entries({ name: r.name, email: r.email, college: r.college ?? "", reg_no: r.reg_no ?? "" }).filter(([, v]) => v));
      const res = await api.post<PreviewResult>("admin/documents/preview", { doc_type: docType, recipient, fields: b.fields, issue_date: issueDate || undefined });
      if (res.kind === "ok") {
        openPdf(res.data.pdf_base64);
        setPreviewed((s) => new Set(s).add(r.row));
      }
    } catch (err) {
      fail(err, "Couldn't build the preview");
    } finally {
      setBusy("");
    }
  }

  async function issueAll() {
    if (!def) return;
    const bulkId = crypto.randomUUID();
    const label = sheet?.name ?? "Picked students";
    const sendRows = okRows;
    setBusy("issue");
    setProgress({ done: 0, total: sendRows.length, issued: 0, failed: 0 });
    try {
      const { results, stopped } = await issueInChunks(
        sendRows,
        async (chunk, key) => {
          const r = await api.post<BulkIssueResult>(
            "admin/documents/bulk/issue",
            { doc_type: docType, bulk_id: bulkId, label, rows: chunk.map((x) => rowBody(x, docType)), issue_date: issueDate || undefined, email },
            { idempotencyKey: key },
          );
          if (r.kind !== "ok") throw new Error("Approval required");
          return r.data;
        },
        setProgress,
        { size: ISSUE_CHUNK, retryable },
      );
      if (stopped) fail(stopped, "Issuing stopped");
      setRun({ bulkId, def, rows: effective, results, skipped: badRows, email });
      const issued = results.filter((r) => r.status === "issued").length;
      toast.show({ tone: issued ? "success" : "warning", title: `${issued} of ${sendRows.length} document${sendRows.length === 1 ? "" : "s"} issued`, description: results.length - issued ? `${results.length - issued} could not be issued; see the results.` : undefined });
      if (issued) onIssued();
    } finally {
      setBusy("");
    }
  }

  if (run) return <BulkResults run={run} onDone={reset} />;

  const checking = busy === "check";
  const canIssue = Boolean(check) && okRows.length > 0 && previewed.size > 0 && !settingsProblem && busy === "";

  return (
    <div className="space-y-4">
      {settingsProblem ? <Card title="Finish the document settings first" icon="alert" description={settingsProblem} /> : null}
      <Card title="1. Document and rows" icon="document" description="One document type per upload. Download the template for the type, fill one row per student, then upload it. Or pick students from a batch or course.">
        <div className="grid gap-4 sm:grid-cols-3">
          <FormField label="Type" required>
            {(p) => (
              <Select
                {...p}
                value={docType}
                onChange={(e) => {
                  setDocType(e.target.value);
                  reset();
                }}
                options={typeOptions.length ? typeOptions : [{ value: docType, label: "Loading…" }]}
              />
            )}
          </FormField>
          <FormField label="Issue date" hint="Empty = today (IST).">
            {(p) => (
              <Input
                {...p}
                type="date"
                value={issueDate}
                onChange={(e) => {
                  setIssueDate(e.target.value);
                  stale();
                }}
              />
            )}
          </FormField>
        </div>
        {docType === "cert_completion" ? <p className="mt-3 text-sm text-fg-secondary">For LMS courses, completion certificates are issued from the Due tab. Use this for programmes run outside an LMS enrolment.</p> : null}
        <Segmented<Source>
          className="mt-4"
          legend="Rows from"
          name="bulk-source"
          variant="pills"
          value={source}
          onChange={(v) => setSource(v)}
          options={[
            { value: "file", label: "Excel / CSV file" },
            { value: "students", label: "Pick students" },
          ]}
        />
        {source === "file" ? (
          <div className="mt-4 flex flex-wrap items-end gap-3">
            <Button variant="secondary" loading={busy === "template"} disabled={!def} onClick={() => void downloadTemplate()}>
              Download Excel template
            </Button>
            <FormField label="Upload filled file" hint={`.xlsx or .csv, first sheet, up to ${MAX_ROWS} rows.`}>
              {(p) => <input {...p} ref={fileInput} type="file" accept=".xlsx,.xls,.csv,text/csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" disabled={!def || busy !== ""} onChange={(e) => void onFile(e.target.files?.[0])} className="block text-sm text-fg-secondary file:mr-3 file:rounded-md file:border file:border-line file:bg-surface file:px-3 file:py-2 file:text-sm file:font-medium" />}
            </FormField>
          </div>
        ) : def ? (
          <StudentPicker def={def} onUse={(r) => void usePicked(r)} />
        ) : null}
        {sheet ? (
          <div className="mt-3 space-y-1 text-sm">
            <p className="text-fg-secondary">{`${sheet.name}: ${rows.length} row${rows.length === 1 ? "" : "s"} read.`}</p>
            {sheet.truncated ? <p className="text-warning-fg">{`Only the first ${MAX_ROWS} rows were read; upload the rest separately.`}</p> : null}
            {sheet.missingColumns.length ? <p className="text-danger-fg">{`Missing columns: ${sheet.missingColumns.join(", ")}. Use the template's header row.`}</p> : null}
            {sheet.unknown.length ? <p className="text-fg-muted">{`Ignored columns: ${sheet.unknown.join(", ")}.`}</p> : null}
          </div>
        ) : null}
      </Card>

      {rows.length && def ? (
        <Card title="Same details for every row" icon="pen" description="Optional. Fills a detail wherever the row leaves it empty (a value in the file always wins). Check again after changing it.">
          <div className="grid gap-4 sm:grid-cols-3">
            {def.fields
              .filter((f) => f.kind !== "longtext")
              .map((f) => (
                <CommonField
                  key={f.key}
                  field={f}
                  value={common[f.key] ?? ""}
                  onChange={(v) => {
                    setCommon((c) => ({ ...c, [f.key]: v }));
                    stale();
                  }}
                />
              ))}
          </div>
          <Button className="mt-4" variant="secondary" loading={checking} onClick={() => void validate(effective)}>
            {check ? "Check again" : "Check rows"}
          </Button>
        </Card>
      ) : null}

      {check ? (
        <Card
          title="2. Check and preview"
          icon="check"
          padding="none"
          description={`${check.ok} of ${check.total} rows ready${check.failed ? `; ${check.failed} with problems are skipped (fix them in the file and upload again)` : ""}. Preview at least one document before issuing.`}
        >
          <Table<BulkRow>
            caption="Rows to issue"
            rows={effective}
            rowKey={(r) => String(r.row)}
            columns={[
              { key: "row", header: "Row", cell: (r) => <span className="tabular-nums text-fg-muted">{r.row}</span> },
              {
                key: "who",
                header: "Recipient",
                cell: (r) => (
                  <div className="min-w-0">
                    <p className="font-medium text-fg">{r.name || "—"}</p>
                    <p className="truncate text-xs text-fg-muted">{r.email || "—"}</p>
                  </div>
                ),
              },
              {
                key: "state",
                header: "Check",
                cell: (r) => {
                  const c = checkBy.get(r.row);
                  return c?.ok ? (
                    <Badge tone="success" dot>
                      OK
                    </Badge>
                  ) : (
                    <Badge tone="danger" dot>
                      Error
                    </Badge>
                  );
                },
              },
              {
                key: "problems",
                header: "Problems",
                cell: (r) => {
                  const c = checkBy.get(r.row);
                  const lines = [...(c?.missing.length ? [`Fill in: ${c.missing.join(", ")}.`] : []), ...(c?.errors ?? [])];
                  return (
                    <div className="space-y-0.5 text-sm">
                      {lines.map((l, i) => (
                        <p key={i} className="text-danger-fg">
                          {l}
                        </p>
                      ))}
                      {(c?.warnings ?? []).map((w, i) => (
                        <p key={`w${i}`} className="text-warning-fg">
                          {w}
                        </p>
                      ))}
                      {!lines.length && !c?.warnings.length ? <span className="text-fg-muted">—</span> : null}
                    </div>
                  );
                },
              },
              {
                key: "preview",
                header: <span className="sr-only">Preview</span>,
                align: "right",
                cell: (r) => (
                  <Button size="sm" variant={previewed.has(r.row) ? "ghost" : "secondary"} loading={busy === `preview:${r.row}`} disabled={busy !== "" && busy !== `preview:${r.row}`} onClick={() => void preview(r)} aria-label={`Preview row ${r.row}`}>
                    {previewed.has(r.row) ? "Previewed" : "Preview"}
                  </Button>
                ),
              },
            ]}
          />
        </Card>
      ) : null}

      {check ? (
        <Card title="3. Issue" icon="award" description="Each ready row gets its own reference number, PDF and public verification page.">
          {check.email_ready ? (
            <FormField label="Email">
              {(p) => (
                <Select
                  {...p}
                  value={email}
                  onChange={(e) => setEmail(e.target.value as EmailMode)}
                  options={[
                    { value: "outbox", label: check.auto_send ? "Queue the emails (auto-send is on: sent with the PDF attached)" : "Queue the emails (they wait in the Approval queue)" },
                    { value: "none", label: "Don't email (download the PDFs / share the links)" },
                  ]}
                />
              )}
            </FormField>
          ) : (
            <p role="note" className="rounded-md border border-line bg-surface-sunken p-3 text-sm text-fg-secondary">
              Email isn&apos;t connected yet, so nothing is emailed. The documents are generated; after issuing, download all PDFs as a ZIP or download the results sheet with every verification link to share.
            </p>
          )}
          {progress ? (
            <div className="mt-4 space-y-1">
              <ProgressBar value={progress.total ? (progress.done / progress.total) * 100 : 0} label="Issuing documents" size="md" />
              <p className="text-sm text-fg-secondary" aria-live="polite">{`${progress.done} of ${progress.total} processed · ${progress.issued} issued${progress.failed ? ` · ${progress.failed} failed` : ""}`}</p>
            </div>
          ) : null}
          <div className="mt-4 flex flex-wrap items-center gap-3">
            <Button loading={busy === "issue"} disabled={!canIssue} onClick={() => setConfirm(true)}>
              {`Issue ${okRows.length} document${okRows.length === 1 ? "" : "s"}`}
            </Button>
            {!previewed.size && okRows.length ? <p className="text-sm text-fg-muted">Preview at least one document first.</p> : null}
          </div>
        </Card>
      ) : null}

      <ConfirmDialog
        open={confirm}
        onClose={() => setConfirm(false)}
        title={`Issue ${okRows.length} ${def?.short.toLowerCase() ?? "document"}${okRows.length === 1 ? "" : "s"}?`}
        description={`They are issued in batches of ${ISSUE_CHUNK}; keep this page open until it finishes.${badRows.length ? ` ${badRows.length} row${badRows.length === 1 ? "" : "s"} with problems ${badRows.length === 1 ? "is" : "are"} skipped.` : ""} ${email === "outbox" ? (check?.auto_send ? "Emails are sent automatically." : "Emails wait in the Approval queue.") : "Nothing is emailed."}`}
        confirmLabel="Issue documents"
        onConfirm={() => {
          setConfirm(false);
          void issueAll();
        }}
      />
    </div>
  );
}

/* ------------------------------------------------------------------ pick students */

function StudentPicker({ def, onUse }: { def: DocTypeDef; onUse: (rows: BulkRow[]) => void }) {
  const batches = useApi<{ data: Batch[] }>("batches");
  const courses = useApi<Page<CourseSummary>>("studio/courses", { limit: 100 });
  const [batchId, setBatchId] = useState("");
  const [courseId, setCourseId] = useState("");
  const [list, setList] = useState<BulkEnrolment[] | null>(null);
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState<"" | "load" | "fill">("");
  const fail = useFailToast();
  const keys = new Set(def.fields.map((f) => f.key));

  async function load() {
    setBusy("load");
    try {
      const r = await api.get<{ data: BulkEnrolment[]; truncated: boolean }>("admin/documents/bulk/enrolments", { query: { batch_id: batchId || undefined, course_id: courseId || undefined } });
      setList(r.data);
      setPicked(new Set(r.data.filter((e) => e.status === "active" || e.status === "completed").map((e) => e.enrolment_id)));
    } catch (err) {
      fail(err, "Couldn't load the students");
    } finally {
      setBusy("");
    }
  }

  async function use() {
    if (!list) return;
    setBusy("fill");
    try {
      const chosen = list.filter((e) => picked.has(e.enrolment_id));
      const rows = await pool(chosen, 4, async (e, i): Promise<BulkRow> => {
        let pre: Prefill | null = null;
        try {
          pre = await api.get<Prefill>("admin/documents/prefill", { query: { enrolment_id: e.enrolment_id } });
        } catch {
          pre = null; // the row still has the student's name / email; the check reports what is missing
        }
        const f = { ...(pre?.fields ?? { program: e.course_title }) };
        if (f.batch_start && !f.start_date) f.start_date = f.batch_start;
        return {
          row: i + 1,
          name: pre?.recipient.name || e.name,
          email: pre?.recipient.email || e.email,
          mobile: e.mobile || undefined,
          fields: Object.fromEntries(Object.entries(f).filter(([k, v]) => keys.has(k) && v)),
          user_id: e.user_id,
          enrolment_id: e.enrolment_id,
          batch_id: pre?.batch_id ?? e.batch_id ?? undefined,
          course_id: e.course_id,
        };
      });
      onUse(rows);
    } finally {
      setBusy("");
    }
  }

  const all = list?.length ? list.every((e) => picked.has(e.enrolment_id)) : false;
  return (
    <div className="mt-4 space-y-3">
      <div className="grid gap-4 sm:grid-cols-3">
        <FormField label="Batch" hint={batches.error ? "Batches couldn't be loaded." : undefined}>
          {(p) => <Select {...p} value={batchId} onChange={(e) => setBatchId(e.target.value)} options={[{ value: "", label: "Any batch" }, ...(batches.data?.data ?? []).map((b) => ({ value: b.id, label: `${b.name} (${b.code})` }))]} />}
        </FormField>
        <FormField label="Course" hint={courses.error ? "Courses couldn't be loaded." : undefined}>
          {(p) => <Select {...p} value={courseId} onChange={(e) => setCourseId(e.target.value)} options={[{ value: "", label: "Any course" }, ...(courses.data?.data ?? []).map((c) => ({ value: c.id, label: c.title }))]} />}
        </FormField>
        <div className="flex items-end">
          <Button variant="secondary" loading={busy === "load"} disabled={!batchId && !courseId} onClick={() => void load()}>
            Load students
          </Button>
        </div>
      </div>
      {list ? (
        list.length ? (
          <div className="space-y-2">
            <Checkbox label={`Select all (${list.length})`} checked={all} onChange={(e) => setPicked(e.target.checked ? new Set(list.map((x) => x.enrolment_id)) : new Set())} />
            <ul className="max-h-72 space-y-1 overflow-y-auto rounded-md border border-line p-2">
              {list.map((e) => (
                <li key={e.enrolment_id}>
                  <Checkbox
                    label={`${e.name} · ${e.email || "no email"}`}
                    description={`${e.course_title || "Course"} · ${e.status}`}
                    checked={picked.has(e.enrolment_id)}
                    onChange={(ev) =>
                      setPicked((s) => {
                        const n = new Set(s);
                        if (ev.target.checked) n.add(e.enrolment_id);
                        else n.delete(e.enrolment_id);
                        return n;
                      })
                    }
                  />
                </li>
              ))}
            </ul>
            <Button loading={busy === "fill"} disabled={!picked.size} onClick={() => void use()}>
              {`Use ${picked.size} selected`}
            </Button>
          </div>
        ) : (
          <p className="text-sm text-fg-muted">No students found for this batch / course.</p>
        )
      ) : null}
    </div>
  );
}

/* ------------------------------------------------------------------ results */

function BulkResults({
  run,
  onDone,
}: {
  run: { bulkId: string; def: DocTypeDef; rows: BulkRow[]; results: BulkIssueRowResult[]; skipped: BulkRow[]; email: EmailMode };
  onDone: () => void;
}) {
  const docs = useApi<BulkRunResponse>(`admin/documents/bulk/${seg(run.bulkId)}`, { doc_type: run.def.key });
  const [busy, setBusy] = useState<"" | "zip" | "xlsx" | `pdf:${string}`>("");
  const [zipDone, setZipDone] = useState<number | null>(null);
  const fail = useFailToast();
  const toast = useToast();
  const issued = run.results.filter((r) => r.status === "issued");
  const failed = run.results.filter((r) => r.status !== "issued");
  const rowOf = new Map(run.rows.map((r) => [r.row, r]));
  const sheetResults: BulkIssueRowResult[] = [...run.results, ...run.skipped.map((r) => ({ row: r.row, status: "failed" as const, error: "Skipped: the row had problems when checked." }))];

  async function zip() {
    const ids = issued.map((r) => r.document_id!).filter(Boolean);
    setBusy("zip");
    setZipDone(0);
    try {
      const files: { name: string; data: Uint8Array }[] = [];
      const queue = [...ids];
      let stalls = 0;
      while (queue.length && stalls < 3) {
        const chunk = queue.splice(0, PDF_CHUNK);
        const r = await api.post<BulkPdfsResult>("admin/documents/bulk/pdfs", { document_ids: chunk });
        if (r.kind !== "ok") break;
        for (const f of r.data.files) files.push({ name: f.filename, data: base64ToBytes(f.pdf_base64) });
        const later = r.data.skipped.filter((s) => s.reason === "deferred").map((s) => s.id);
        stalls = later.length === chunk.length ? stalls + 1 : 0;
        queue.unshift(...later);
        setZipDone(files.length);
      }
      if (!files.length) {
        toast.show({ tone: "warning", title: "No PDFs to download" });
        return;
      }
      saveBytes(makeZip(files), `${slug(run.def.short)}-${today()}.zip`, "application/zip");
      if (files.length < ids.length) toast.show({ tone: "warning", title: `${files.length} of ${ids.length} PDFs in the ZIP`, description: "Revoked documents or slow requests were left out; download those from the register." });
    } catch (err) {
      fail(err, "Couldn't build the ZIP");
    } finally {
      setBusy("");
      setZipDone(null);
    }
  }

  async function results() {
    setBusy("xlsx");
    try {
      const x = await loadXlsx();
      const allRows = [...run.rows].sort((a, b) => a.row - b.row);
      saveBytes(buildResults(x, run.def, allRows, sheetResults), `${slug(run.def.short)}-results-${today()}.xlsx`, XLSX_MIME);
    } catch (err) {
      fail(err, "Couldn't build the results sheet");
    } finally {
      setBusy("");
    }
  }

  async function copyLinks() {
    const text = issued.map((r) => `${r.name ?? rowOf.get(r.row)?.name ?? ""}\t${absoluteUrl(r.verify_url ?? "")}`).join("\n");
    try {
      await navigator.clipboard.writeText(text);
      toast.show({ tone: "success", title: "Verification links copied", description: `${issued.length} line${issued.length === 1 ? "" : "s"}: name and link.` });
    } catch {
      toast.show({ tone: "warning", title: "Couldn't copy", description: "Download the results sheet instead." });
    }
  }

  async function pdf(id: string) {
    setBusy(`pdf:${id}`);
    try {
      const r = await api.get<{ url: string }>(`admin/documents/${seg(id)}/pdf`);
      if (r.url) window.open(r.url, "_blank", "noopener,noreferrer");
    } catch (err) {
      fail(err, "Couldn't open the PDF");
    } finally {
      setBusy("");
    }
  }

  return (
    <div className="space-y-4">
      <Card
        title={`${issued.length} ${run.def.short.toLowerCase()}${issued.length === 1 ? "" : "s"} issued`}
        icon="award"
        description={`${failed.length ? `${failed.length} could not be issued. ` : ""}${run.skipped.length ? `${run.skipped.length} skipped (problems in the file). ` : ""}${
          run.email === "outbox" ? "Emails are in the outbox (see the Approval queue)." : "Nothing was emailed: download the PDFs or share the verification links."
        }`}
        actions={
          <Button variant="ghost" onClick={onDone}>
            Start another
          </Button>
        }
      >
        <div className="flex flex-wrap items-center gap-3">
          <Button loading={busy === "zip"} disabled={!issued.length || busy !== ""} onClick={() => void zip()}>
            Download all PDFs (ZIP)
          </Button>
          <Button variant="secondary" loading={busy === "xlsx"} disabled={busy !== ""} onClick={() => void results()}>
            Download results (.xlsx)
          </Button>
          <Button variant="secondary" disabled={!issued.length} onClick={() => void copyLinks()}>
            Copy verification links
          </Button>
          {zipDone !== null ? <span className="text-sm text-fg-muted" aria-live="polite">{`${zipDone} of ${issued.length} PDFs ready…`}</span> : null}
        </div>
      </Card>
      {failed.length || run.skipped.length ? (
        <Card title="Not issued" icon="alert" padding="none" description="Fix these rows in the file and upload them again (only these rows).">
          <Table<BulkIssueRowResult>
            caption="Rows not issued"
            rows={[...failed, ...sheetResults.slice(run.results.length)]}
            rowKey={(r) => String(r.row)}
            columns={[
              { key: "row", header: "Row", cell: (r) => r.row },
              { key: "who", header: "Recipient", cell: (r) => rowOf.get(r.row)?.name || rowOf.get(r.row)?.email || "—" },
              { key: "why", header: "Problem", cell: (r) => [r.error, r.missing?.length ? `Fill in: ${r.missing.join(", ")}.` : ""].filter(Boolean).join(" ") },
            ]}
          />
        </Card>
      ) : null}
      <Card title="This run in the register" icon="list" padding="none">
        <Table<BulkRunResponse["data"][number]>
          caption="Documents of this run"
          rows={docs.data?.data}
          rowKey={(r) => r.id}
          loading={docs.loading}
          error={docs.error}
          onRetry={() => void docs.reload()}
          empty={{ title: "No documents in this run", icon: "document" }}
          columns={[
            { key: "row", header: "Row", cell: (r) => r.bulk_row ?? "—", priority: "secondary" },
            {
              key: "who",
              header: "Recipient",
              cell: (r) => (
                <div className="min-w-0">
                  <p className="font-medium text-fg">{r.recipient.name}</p>
                  <p className="truncate text-xs text-fg-muted">{r.recipient.email}</p>
                </div>
              ),
            },
            { key: "issued", header: "Issued", cell: (r) => formatDate(r.issue_date), priority: "secondary" },
            { key: "email", header: "Email", cell: (r) => emailText(r.email_status), priority: "secondary" },
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
              key: "pdf",
              header: <span className="sr-only">PDF</span>,
              align: "right",
              cell: (r) =>
                r.status === "valid" ? (
                  <Button size="sm" variant="secondary" loading={busy === `pdf:${r.id}`} onClick={() => void pdf(r.id)} aria-label={`Download PDF ${r.ref_no}`}>
                    PDF
                  </Button>
                ) : null,
            },
          ]}
        />
      </Card>
    </div>
  );
}
