"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { Badge, Button, Checkbox, Dialog, FormField, Input, ProgressBar, Select, Table, Textarea, buttonClasses, useToast, type BadgeTone, type Column } from "@/components/ui";
import { api } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import { useResource } from "@/lib/api/use-resource";
import { InlineProblem, textLink } from "@/features/admin/components/console-ui";
import { isEmail, missingFields, pdfUrlFromBase64, type DocField, type DocTypesResponse, type PreviewResult, type Recipient } from "@/features/certificates/lib/docs";
import type { OutboxStatus } from "@/features/certificates/lib/types";
import { formatDate } from "@/lib/format";
import { uuid7 } from "@/lib/ids/uuid7";
import { whatsappLink } from "../lib/admissions";
import {
  LETTER_TYPES,
  cleanFields,
  issueBody,
  issueLabel,
  issueLettersInBulk,
  letterEmailMode,
  letterLine,
  letterMessage,
  pdfTab,
  runInChunks,
  showPdf,
  switchLetterFields,
  type BulkLetterResult,
  type IssuedLetter,
  type LetterEmailMode,
  type LetterOutcome,
  type LetterStep,
  type LetterSummary,
  type LetterType,
} from "../lib/letters";

/**
 * Admission / offer letter step after "Verify & add to batch" / "Enrol now": the letter is prefilled
 * from the registration (name, email, course, batch dates, fee), previewed as a PDF, edited and
 * issued through the documents register (Certificates & documents), which emails it per the
 * auto-send / approval setting. Without email the admin downloads it or shares the verify link on
 * WhatsApp. A letter in force is shown instead of a second one; corrections supersede it.
 */

const DOCS_HREF = "/admin/certificates";
const EMAIL_TEXT: Record<OutboxStatus, string> = {
  awaiting: "Email waiting for approval (Certificates & documents).",
  pending: "Email is being sent.",
  sent: "Emailed to the student with the PDF attached.",
  failed: "The email failed: download the PDF or share the link instead.",
  cancelled: "The email was cancelled.",
};
const STATUS_TONE: Record<string, BadgeTone> = { valid: "success", revoked: "danger", superseded: "neutral" };

function problemText(e: unknown): string {
  if (e instanceof ApiError) return e.problem?.detail || e.problem?.title || e.message;
  return e instanceof Error ? e.message : "Something went wrong";
}

function revokeLater(url: string) {
  window.setTimeout(() => URL.revokeObjectURL(url), 60_000);
}

/** Draft PDF in a new tab (the documents preview: nothing is stored). */
async function previewPdf(body: { doc_type: string; recipient: Recipient; fields: Record<string, string>; issue_date?: string }): Promise<PreviewResult | null> {
  const tab = pdfTab();
  try {
    const r = await api.post<PreviewResult>("admin/documents/preview", { ...body, fields: cleanFields(body.fields) });
    if (r.kind !== "ok") {
      tab?.close();
      return null;
    }
    const url = pdfUrlFromBase64(r.data.pdf_base64);
    showPdf(tab, url);
    revokeLater(url);
    return r.data;
  } catch (e) {
    tab?.close();
    throw e;
  }
}

/** The issued PDF (short-lived link from the documents register) in a new tab. */
async function downloadPdf(id: string): Promise<void> {
  const tab = pdfTab();
  try {
    const r = await api.get<{ url: string }>(`admin/documents/${encodeURIComponent(id)}/pdf`);
    showPdf(tab, r.url);
  } catch (e) {
    tab?.close();
    throw e;
  }
}

function LetterField({ field, value, onChange }: { field: DocField; value: string; onChange: (v: string) => void }) {
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

/** "Letter issued: TD-AL-… (date)" or "Not issued", for the registrations list and page. */
export function LetterStatus({ letter, enrolled }: { letter: LetterSummary | null | undefined; enrolled: boolean }) {
  if (letter) return <span className="text-sm">{letterLine(letter)}</span>;
  return <span className="text-sm text-fg-secondary">{enrolled ? "Letter not issued" : "After enrolment"}</span>;
}

/** The step in a dialog: one registration's letter (preview, edit, issue & send, download, share, correct). */
export function LetterStepDialog({ registrationId, open, onClose, onChanged }: { registrationId: string | null; open: boolean; onClose: () => void; onChanged?: () => void }) {
  const step = useResource<LetterStep>(open && registrationId ? `admin/admissions/registrations/${registrationId}/letter` : null);
  const s = step.data && step.data.registration_id === registrationId ? step.data : undefined;
  return (
    <Dialog
      open={open}
      onClose={onClose}
      size="lg"
      title="Admission / offer letter"
      description={s ? `${s.name} · ${s.course_title} · ${s.reg_no}` : undefined}
      footer={<Button onClick={onClose}>Done</Button>}
    >
      {step.error && !s ? (
        <InlineProblem error={step.error} />
      ) : !s ? (
        <p className="text-sm text-fg-secondary">Loading the letter…</p>
      ) : (
        <LetterStepBody key={s.registration_id} step={s} reload={step.reload} onChanged={onChanged} />
      )}
    </Dialog>
  );
}

type Mode = "view" | "edit" | "correct";

function LetterStepBody({ step, reload, onChanged }: { step: LetterStep; reload: () => Promise<void>; onChanged?: () => void }) {
  const toast = useToast();
  const types = useResource<DocTypesResponse>("admin/documents/types");
  const letter = step.letter;
  const [mode, setMode] = useState<Mode>(letter ? "view" : "edit");
  const [docType, setDocType] = useState<LetterType>(step.draft?.doc_type ?? "offer_course");
  const [recipient, setRecipient] = useState<Recipient>(step.draft?.recipient ?? { name: step.name, email: "", college: "", reg_no: step.reg_no });
  const [fields, setFields] = useState<Record<string, string>>(step.draft?.fields ?? {});
  const [issueDate, setIssueDate] = useState(step.draft?.issue_date ?? "");
  const [busy, setBusy] = useState<"" | "preview" | "issue" | "pdf">("");
  const [error, setError] = useState<unknown>(null);
  const [check, setCheck] = useState<PreviewResult | null>(null);
  const [autoOpen, setAutoOpen] = useState(step.auto_open);
  const emailMode: LetterEmailMode = letterEmailMode(step.email);
  const def = types.data?.types.find((t) => t.key === docType);
  const missing = missingFields(def, recipient, fields);
  const letterId = letter?.id;

  // A letter issued meanwhile (or just now) is shown instead of the form.
  useEffect(() => {
    if (letterId) setMode("view");
  }, [letterId]);

  const startCorrect = () => {
    if (!letter) return;
    setDocType(letter.doc_type as LetterType);
    setRecipient({ name: letter.recipient.name, email: letter.recipient.email, college: letter.recipient.college ?? "", reg_no: letter.recipient.reg_no ?? step.reg_no });
    setFields({ ...letter.fields });
    setIssueDate(step.draft?.issue_date ?? "");
    setCheck(null);
    setError(null);
    setMode("correct");
  };
  const setR = (k: keyof Recipient) => (e: { target: { value: string } }) => setRecipient((r) => ({ ...r, [k]: e.target.value }));
  const recipientBody = (): Recipient => ({ name: recipient.name.trim(), email: recipient.email.trim(), college: recipient.college?.trim() ?? "", reg_no: recipient.reg_no?.trim() ?? "" });

  async function preview() {
    setBusy("preview");
    setError(null);
    try {
      setCheck(await previewPdf({ doc_type: docType, recipient: recipientBody(), fields, issue_date: issueDate || undefined }));
    } catch (e) {
      setError(e);
    } finally {
      setBusy("");
    }
  }

  async function issue() {
    if (!step.draft) return;
    setBusy("issue");
    setError(null);
    try {
      if (mode === "correct" && letter) {
        const r = await api.post<IssuedLetter>(
          `admin/documents/${encodeURIComponent(letter.id)}/reissue`,
          { recipient: { ...recipientBody(), college: recipient.college?.trim() || null, reg_no: recipient.reg_no?.trim() || null }, fields: cleanFields(fields), issue_date: issueDate || undefined, email: emailMode },
          { idempotencyKey: true },
        );
        toast.show({ tone: "success", title: "Corrected letter issued", description: r.kind === "ok" ? `${r.data.ref_no} replaces ${letter.ref_no}` : undefined });
      } else {
        // Never a second letter: the automatic one (or a colleague's) may have been issued meanwhile.
        const fresh = await api.get<LetterStep>(`admin/admissions/registrations/${step.registration_id}/letter`);
        if (fresh.letter) {
          toast.show({ tone: "warning", title: "A letter was already issued", description: letterLine(fresh.letter) });
          await reload();
          return;
        }
        const r = await api.post<IssuedLetter>("admin/documents", issueBody({ doc_type: docType, recipient: recipientBody(), fields, issue_date: issueDate, draft: step.draft, email: emailMode }), { idempotencyKey: true });
        const d = r.kind === "ok" ? r.data : null;
        toast.show({ tone: "success", title: `${d?.short ?? "Letter"} issued`, description: d ? `${d.ref_no}${emailMode === "none" ? "" : emailMode === "send" ? " · emailed" : " · email waiting for approval"}` : undefined });
      }
      await reload();
      onChanged?.();
    } catch (e) {
      setError(e);
    } finally {
      setBusy("");
    }
  }

  async function download(id: string) {
    setBusy("pdf");
    setError(null);
    try {
      await downloadPdf(id);
    } catch (e) {
      setError(e);
    } finally {
      setBusy("");
    }
  }

  async function saveAutoOpen(on: boolean) {
    setAutoOpen(on);
    try {
      await api.put("admin/admissions/letter-settings", { auto_open: on });
      toast.show({ tone: "success", title: on ? "The letter step opens after each enrolment." : "The letter step no longer opens by itself." });
    } catch (e) {
      setAutoOpen(!on);
      setError(e);
    }
  }

  if (!step.ready) {
    return <p className="text-sm text-fg-secondary">{step.reason}</p>;
  }

  const earlier = step.letters.filter((l) => l.id !== letter?.id);
  return (
    <div className="space-y-4">
      <InlineProblem error={error} />
      {mode === "view" && letter ? (
        <div className="space-y-3">
          <div className="rounded-md border border-success-border bg-success-subtle p-3">
            <p role="status" className="font-semibold text-success-fg">
              {letterLine(letter)}
            </p>
            <p className="mt-1 text-sm">
              {letter.short}
              {letter.origin === "enrolment" ? " · issued automatically on enrolment" : ""} ·{" "}
              <Link className={textLink} href={`/verify/${encodeURIComponent(letter.ref_no)}`} target="_blank">
                verification page
              </Link>
            </p>
            <p className="mt-1 text-sm text-fg-secondary">
              {!step.email.connected ? "Email isn't connected yet — download the PDF or share the link on WhatsApp." : letter.email_status ? EMAIL_TEXT[letter.email_status] : "Not emailed."}
            </p>
          </div>
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
            <Button variant="secondary" loading={busy === "pdf"} onClick={() => void download(letter.id)}>
              Download PDF
            </Button>
            <a className={buttonClasses({ variant: "primary" })} href={whatsappLink(step.phone, letterMessage(step, letter))} target="_blank" rel="noreferrer">
              Share on WhatsApp
            </a>
            <Button variant="secondary" onClick={startCorrect}>
              Re-issue / correct
            </Button>
          </div>
          <p className="text-xs text-fg-muted">Re-issue makes a corrected copy with a new reference; the old one shows as superseded on its verification page.</p>
        </div>
      ) : (
        <div className="space-y-4">
          {mode === "correct" && letter ? (
            <p className="text-sm text-fg-secondary">
              Correcting {letter.ref_no}: the new letter replaces it (it shows as superseded).{" "}
              <button type="button" className={textLink} onClick={() => setMode("view")}>
                Cancel
              </button>
            </p>
          ) : null}
          {step.settings_problem ? (
            <p role="alert" className="rounded-md border border-warning-border bg-warning-subtle p-3 text-sm text-warning-fg">
              Finish the document settings first: {step.settings_problem}{" "}
              <Link className={textLink} href={DOCS_HREF}>
                Certificates &amp; documents
              </Link>
            </p>
          ) : null}
          {types.error && !types.data ? <InlineProblem error={types.error} /> : null}
          <div className="grid gap-4 sm:grid-cols-2">
            <FormField label="Letter">
              {(p) => (
                <Select
                  {...p}
                  value={docType}
                  disabled={mode === "correct"}
                  onChange={(e) => {
                    const to = e.target.value as LetterType;
                    setFields((f) => switchLetterFields(f, to));
                    setDocType(to);
                    setCheck(null);
                  }}
                  options={LETTER_TYPES}
                />
              )}
            </FormField>
            <FormField label="Issue date">{(p) => <Input {...p} type="date" value={issueDate} onChange={(e) => setIssueDate(e.target.value)} />}</FormField>
            <FormField label="Student name" required hint="As it should be printed.">
              {(p) => <Input {...p} value={recipient.name} onChange={setR("name")} autoComplete="off" />}
            </FormField>
            <FormField label="Student email" required error={recipient.email.trim() && !isEmail(recipient.email) ? "Enter a valid email address" : undefined}>
              {(p) => <Input {...p} type="email" value={recipient.email} onChange={setR("email")} autoComplete="off" />}
            </FormField>
            <FormField label="College">{(p) => <Input {...p} value={recipient.college ?? ""} onChange={setR("college")} />}</FormField>
            <FormField label="Registration no.">{(p) => <Input {...p} value={recipient.reg_no ?? ""} onChange={setR("reg_no")} />}</FormField>
            {(def?.fields ?? []).map((f) => (
              <div key={f.key} className={f.kind === "longtext" ? "sm:col-span-2" : undefined}>
                <LetterField field={f} value={fields[f.key] ?? ""} onChange={(v) => setFields((x) => ({ ...x, [f.key]: v }))} />
              </div>
            ))}
          </div>
          {check?.leftovers.length ? (
            <p role="alert" className="text-sm font-medium text-danger-fg">{`Template text is still in the wording: ${check.leftovers.join(", ")}. Fix it in Certificates & documents > Templates.`}</p>
          ) : null}
          <p className="text-sm text-fg-secondary">
            {emailMode === "send"
              ? `Issuing emails the letter to ${recipient.email || "the student"} with the PDF attached.`
              : emailMode === "queue"
                ? "Issuing puts the email in the approval queue (Certificates & documents > Emails)."
                : "Email isn't connected yet: after issuing, download the PDF or share the link on WhatsApp."}
          </p>
          <div className="flex flex-wrap items-center gap-3">
            <Button variant="secondary" loading={busy === "preview"} disabled={!def} onClick={() => void preview()}>
              Preview letter
            </Button>
            <Button loading={busy === "issue"} disabled={!def || missing.length > 0 || Boolean(step.settings_problem)} onClick={() => void issue()}>
              {mode === "correct" ? "Issue corrected letter" : issueLabel(emailMode)}
            </Button>
            {def && missing.length ? <p className="text-sm text-fg-muted">{`Still needed: ${missing.join(", ")}.`}</p> : null}
          </div>
        </div>
      )}
      {earlier.length ? (
        <div>
          <h3 className="mb-1 text-sm font-semibold text-fg-heading">Earlier letters</h3>
          <ul className="space-y-1 text-sm">
            {earlier.map((l) => (
              <li key={l.id} className="flex flex-wrap items-center gap-2">
                <span className="font-mono">{l.ref_no}</span>
                <Badge tone={STATUS_TONE[l.status] ?? "neutral"}>{l.status}</Badge>
                <span className="text-fg-muted">{formatDate(l.issue_date)}</span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      <Checkbox
        label="After enrolling, open the offer-letter step automatically"
        description="For everyone who verifies payments."
        checked={autoOpen}
        onChange={(e) => void saveAutoOpen(e.target.checked)}
      />
    </div>
  );
}

/* ------------------------------------------------------------------ bulk */

interface BulkRow {
  step: LetterStep;
  state: "issued" | "not_enrolled" | "missing" | "ready";
  missing: string[];
  result?: { ref_no?: string; error?: string };
}

/**
 * Registrations > select > "Preview & issue letters": each selected registration's draft, what is
 * missing, a preview per student, then issue the ready ones a few at a time with progress. Students
 * who already have a letter (or aren't enrolled) are skipped.
 */
export function BulkLettersDialog({ ids, open, onClose, onDone }: { ids: string[]; open: boolean; onClose: () => void; onDone?: () => void }) {
  const toast = useToast();
  const types = useResource<DocTypesResponse>(open ? "admin/documents/types" : null);
  const [steps, setSteps] = useState<LetterStep[] | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [progress, setProgress] = useState<{ done: number; total: number } | null>(null);
  const [results, setResults] = useState<Record<string, { ref_no?: string; error?: string }>>({});
  const [busy, setBusy] = useState<string | null>(null);
  const idsKey = ids.join(",");

  useEffect(() => {
    if (!open || !idsKey) return;
    let live = true;
    setSteps(null);
    setError(null);
    setResults({});
    setProgress(null);
    api
      .post<{ data: LetterStep[] }>("admin/admissions/letters/drafts", { registration_ids: idsKey.split(",") })
      .then((r) => {
        if (live && r.kind === "ok") setSteps(r.data.data);
      })
      .catch((e: unknown) => {
        if (live) setError(e);
      });
    return () => {
      live = false;
    };
  }, [open, idsKey]);

  const rows: BulkRow[] = (steps ?? []).map((s) => {
    const def = types.data?.types.find((t) => t.key === s.draft?.doc_type);
    const missing = s.draft ? missingFields(def, s.draft.recipient, s.draft.fields) : [];
    const state: BulkRow["state"] = !s.ready ? "not_enrolled" : s.letter ? "issued" : missing.length ? "missing" : "ready";
    return { step: s, state, missing, result: results[s.registration_id] };
  });
  const ready = rows.filter((r) => r.state === "ready" && !r.result?.ref_no);
  const first = steps?.find((s) => s.ready);
  const mode = first ? letterEmailMode(first.email) : "none";
  const running = progress !== null && progress.done < progress.total;

  async function preview(s: LetterStep) {
    if (!s.draft) return;
    setBusy(s.registration_id);
    try {
      await previewPdf({ doc_type: s.draft.doc_type, recipient: s.draft.recipient, fields: s.draft.fields, issue_date: s.draft.issue_date });
    } catch (e) {
      toast.show({ tone: "danger", title: "Couldn't build the preview", description: problemText(e) });
    } finally {
      setBusy(null);
    }
  }

  async function issueAll() {
    const todo = ready.map((r) => r.step);
    if (!todo.length) return;
    setProgress({ done: 0, total: todo.length });
    const onProgress = (done: number, total: number) => setProgress({ done, total });
    const next: Record<string, { ref_no?: string; error?: string }> = {};
    const got = new Map<number, LetterOutcome>();
    let reached = false;
    try {
      // The documents bulk endpoint (one run id, the email queued per the auto-send setting) ...
      const bulkId = uuid7();
      await issueLettersInBulk(
        todo.map((s) => s.draft!),
        async (docType, chunk) => {
          const r = await api.post<BulkLetterResult>("admin/documents/bulk/issue", { doc_type: docType, bulk_id: bulkId, label: "Admission letters", rows: chunk, email: mode === "none" ? "none" : "outbox" }, { idempotencyKey: true });
          if (r.kind !== "ok") throw new Error("Approval required");
          reached = true;
          return r.data;
        },
        onProgress,
        { into: got },
      );
      got.forEach((o, i) => {
        next[todo[i]!.registration_id] = o;
      });
    } catch (e) {
      // ... or, where it isn't deployed, one letter at a time through POST /admin/documents.
      if (reached || !(e instanceof ApiError && (e.status === 404 || e.status === 405))) {
        got.forEach((o, i) => {
          next[todo[i]!.registration_id] = o;
        });
        setResults((x) => ({ ...x, ...next }));
        setProgress(null);
        toast.show({ tone: "danger", title: "Issuing stopped", description: `${problemText(e)} ${got.size} of ${todo.length} done; issue the rest again.` });
        onDone?.();
        return;
      }
      const out = await runInChunks(
        todo,
        3,
        async (s) => {
          const d = s.draft!;
          const r = await api.post<IssuedLetter>("admin/documents", issueBody({ doc_type: d.doc_type, recipient: d.recipient, fields: d.fields, issue_date: d.issue_date, draft: d, email: letterEmailMode(s.email) }), { idempotencyKey: true });
          return r.kind === "ok" ? r.data.ref_no : "";
        },
        onProgress,
      );
      out.forEach((o, i) => {
        next[todo[i]!.registration_id] = o.ok ? { ref_no: o.value } : { error: problemText(o.error) };
      });
    }
    setResults((x) => ({ ...x, ...next }));
    setProgress({ done: todo.length, total: todo.length });
    const ok = Object.values(next).filter((o) => o.ref_no).length;
    toast.show({ tone: ok === todo.length ? "success" : "warning", title: `${ok} of ${todo.length} letters issued`, description: ok < todo.length ? "See the failed rows." : undefined });
    onDone?.();
  }

  const stateText = (r: BulkRow): string => {
    if (r.result?.ref_no) return `Issued ${r.result.ref_no}`;
    if (r.result?.error) return `Failed: ${r.result.error}`;
    if (r.state === "issued" && r.step.letter) return `Already issued: ${r.step.letter.ref_no}`;
    if (r.state === "not_enrolled") return "Not enrolled: skipped";
    if (r.state === "missing") return `Still needed: ${r.missing.join(", ")}`;
    return "Ready";
  };
  const cols: Column<BulkRow>[] = [
    {
      key: "who",
      header: "Student",
      cell: (r) => (
        <div>
          <div>{r.step.name}</div>
          <div className="text-xs text-fg-secondary">{r.step.reg_no}</div>
        </div>
      ),
    },
    {
      key: "letter",
      header: "Letter",
      cell: (r) =>
        r.step.draft ? (
          <div>
            <div>{LETTER_TYPES.find((t) => t.value === r.step.draft!.doc_type)?.label}</div>
            <div className="text-xs text-fg-secondary">{r.step.draft.fields.program ?? r.step.draft.fields.role ?? r.step.course_title}</div>
          </div>
        ) : (
          "—"
        ),
    },
    { key: "start", header: "Starts", cell: (r) => formatDate(r.step.draft?.fields.batch_start ?? r.step.draft?.fields.start_date ?? null), priority: "secondary" },
    { key: "state", header: "Status", cell: (r) => <span className={r.result?.error ? "text-danger-fg" : undefined}>{stateText(r)}</span> },
    {
      key: "act",
      header: <span className="sr-only">Preview</span>,
      align: "right",
      cell: (r) =>
        r.step.draft && r.state !== "issued" ? (
          <Button size="sm" variant="secondary" loading={busy === r.step.registration_id} onClick={() => void preview(r.step)} aria-label={`Preview letter for ${r.step.name}`}>
            Preview
          </Button>
        ) : null,
    },
  ];

  return (
    <Dialog
      open={open}
      onClose={onClose}
      dismissible={!running}
      size="xl"
      title="Preview & issue letters"
      description={`${ids.length} selected. Students who already have a letter, or aren't enrolled, are skipped.`}
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={running}>
            Close
          </Button>
          <Button onClick={() => void issueAll()} loading={running} disabled={!ready.length || Boolean(first?.settings_problem)}>
            {ready.length ? `${issueLabel(mode)} (${ready.length})` : "Nothing to issue"}
          </Button>
        </>
      }
    >
      <div className="space-y-3">
        <InlineProblem error={error} />
        {first?.settings_problem ? (
          <p role="alert" className="text-sm text-warning-fg">
            Finish the document settings first: {first.settings_problem}
          </p>
        ) : null}
        {progress ? <ProgressBar value={(progress.done / Math.max(progress.total, 1)) * 100} label={`Issued ${progress.done} of ${progress.total}`} /> : null}
        {progress ? <p className="text-sm text-fg-secondary" aria-live="polite">{`${progress.done} of ${progress.total} done`}</p> : null}
        <p className="text-sm text-fg-secondary">
          {mode === "send" ? "Each letter is emailed with the PDF attached." : mode === "queue" ? "The emails go to the approval queue." : "Email isn't connected: download or share each letter from the student's registration."}
        </p>
        <Table caption="Letters to issue" columns={cols} rows={steps ? rows : undefined} rowKey={(r) => r.step.registration_id} loading={!steps && !error} empty={{ title: "Nothing selected" }} />
      </div>
    </Dialog>
  );
}
