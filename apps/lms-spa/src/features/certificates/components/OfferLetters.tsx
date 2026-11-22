"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { Badge, Button, Card, ConfirmDialog, Dialog, FormField, Input, Segmented, Select, Table, Textarea, useToast } from "@/components/ui";
import { loadXlsx, saveBytes, XLSX_MIME } from "../lib/bulk";
import { makeZip } from "../lib/zip";
import {
  LETTER_KINDS,
  MODES,
  emailDraft,
  gmailComposeUrl,
  isIsoDate,
  kindLabel,
  loadSettings,
  longDate,
  offerFileName,
  periodOf,
  readOfferSheet,
  saveSettings,
  templateWorkbook,
  todayIso,
  addDays,
  type LetterKind,
  type OfferInput,
  type OfferLetter,
  type OfferSettings,
} from "../lib/offer";
import { LOCAL_SIGNATURE_URL, loadOfferAssets, localSignature, renderOfferPdf } from "../lib/offerpdf";
import {
  FOLDER_TO_SEND,
  STATUS_LABEL,
  addEntries,
  counts,
  draftsHtml,
  folderOf,
  generate,
  letterSummary,
  loadRegister,
  markSent,
  newId,
  registerWorkbook,
  removeRecords,
  reopen,
  rowErrors,
  saveRegister,
  undoSent,
  type LetterStatus,
  type OfferRecord,
} from "../lib/register";

const MODE_OPTIONS = MODES.map((m) => ({ value: m, label: m[0]!.toUpperCase() + m.slice(1) }));

async function makePdf(l: OfferLetter, signature: string): Promise<Uint8Array> {
  return renderOfferPdf({ ...l, signature }, await loadOfferAssets(signature));
}

function openPdf(bytes: Uint8Array): void {
  const url = URL.createObjectURL(new Blob([bytes as BlobPart], { type: "application/pdf" }));
  window.open(url, "_blank", "noopener");
  window.setTimeout(() => URL.revokeObjectURL(url), 120_000);
}

const shortDate = (iso: string | undefined) => {
  if (!iso) return "";
  try {
    return longDate(iso);
  } catch {
    return iso;
  }
};

type Filter = "all" | LetterStatus;

/**
 * Certificates & documents > Offer letters. One page, four steps, no AI:
 * 1. add candidates (Excel upload or the form) -> they appear in the list;
 * 2. "Generate … offer letter" -> the letter gets its number and moves to "To send";
 * 3. "Email draft" -> copy To / Subject / Body, download the PDF and send it from the HR mailbox;
 * 4. "Mark as sent" -> the row shows "Sent on <date>".
 * The list is kept in this browser; "Download register (Excel)" is its backup (upload it to restore).
 */
export function OfferLettersTab() {
  const toast = useToast();
  const [settings, setSettings] = useState<OfferSettings>(() => loadSettings());
  const [records, setRecords] = useState<OfferRecord[]>(() => loadRegister());
  const [filter, setFilter] = useState<Filter>("all");
  const [query, setQuery] = useState("");
  const [busy, setBusy] = useState("");
  const [editing, setEditing] = useState<OfferRecord | "new" | null>(null);
  const [draftOf, setDraftOf] = useState<OfferRecord | null>(null);
  const [removing, setRemoving] = useState<OfferRecord | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);

  const saveAll = (r: OfferRecord[], s?: OfferSettings) => {
    setRecords(r);
    if (!saveRegister(r)) toast.show({ tone: "warning", title: "Couldn't save the list in this browser", description: "Download the register (Excel) as a backup." });
    if (s) {
      setSettings(s);
      saveSettings(s);
    }
  };

  const c = counts(records);
  const shown = useMemo(() => {
    const q = query.trim().toLowerCase();
    return records.filter(
      (r) =>
        (filter === "all" || r.status === filter) &&
        (!q || `${r.input.name} ${r.input.email} ${r.letter?.ref ?? r.input.ref}`.toLowerCase().includes(q)),
    );
  }, [records, filter, query]);
  const pending = records.filter((r) => r.status === "new");

  async function downloadTemplate() {
    const x = await loadXlsx();
    saveBytes(templateWorkbook(x, settings), "offer-letters-template.xlsx", XLSX_MIME);
  }

  async function onFile(file: File | undefined) {
    if (!file) return;
    setBusy("upload");
    try {
      const x = await loadXlsx();
      const entries = readOfferSheet(x, new Uint8Array(await file.arrayBuffer()), settings);
      if (!entries.length) {
        toast.show({ tone: "warning", title: "No rows found", description: "Fill in rows under the header of the first sheet." });
        return;
      }
      const res = addEntries(records, entries, settings, todayIso());
      saveAll(res.records);
      setFilter("all");
      toast.show({
        tone: "success",
        title: `${res.added} candidate${res.added === 1 ? "" : "s"} added${res.updated ? `, ${res.updated} updated` : ""}`,
        description: "Click Generate next to a name, or Generate all.",
      });
    } catch (err) {
      toast.show({ tone: "danger", title: "Couldn't read the file", description: err instanceof Error ? err.message : "Use the .xlsx template." });
    } finally {
      setBusy("");
      if (fileInput.current) fileInput.current.value = "";
    }
  }

  function doGenerate(ids: string[]) {
    const res = generate(records, ids, settings, todayIso());
    saveAll(res.records, res.settings);
    if (res.generated.length)
      toast.show({ tone: "success", title: `${res.generated.length} offer letter${res.generated.length === 1 ? "" : "s"} generated`, description: "They are in To send. Open one, or click Email draft." });
    if (res.failed.length)
      toast.show({
        tone: "warning",
        title: `${res.failed.length} not generated`,
        description: res.failed.map((f) => `${f.name}: ${f.errors.join(", ")}`).join(". "),
      });
  }

  async function open(r: OfferRecord) {
    if (!r.letter) return;
    setBusy(`open:${r.id}`);
    try {
      openPdf(await makePdf(r.letter, settings.signature));
    } catch (err) {
      toast.show({ tone: "danger", title: "Couldn't make the PDF", description: err instanceof Error ? err.message : undefined });
    } finally {
      setBusy("");
    }
  }

  async function download(r: OfferRecord) {
    if (!r.letter) return;
    saveBytes(await makePdf(r.letter, settings.signature), offerFileName(r.letter), "application/pdf");
  }

  function sent(ids: string[]) {
    saveAll(markSent(records, ids, todayIso()));
    toast.show({ tone: "success", title: ids.length === 1 ? "Marked as sent" : `${ids.length} marked as sent` });
  }

  async function downloadRegister() {
    const x = await loadXlsx();
    saveBytes(registerWorkbook(x, records), `offer-letters-register-${todayIso()}.xlsx`, XLSX_MIME);
  }

  /** Everything in one ZIP, organised like a shared folder: 1 To Send / 2 Sent, drafts page, register. */
  async function downloadZip() {
    const issued = records.filter((r) => r.letter);
    if (!issued.length) {
      toast.show({ tone: "warning", title: "No letters generated yet" });
      return;
    }
    setBusy("zip");
    try {
      const assets = await loadOfferAssets(settings.signature);
      const files = [];
      for (const r of issued) {
        const l = { ...r.letter!, signature: settings.signature };
        files.push({ name: `${folderOf(r)}/${offerFileName(l)}`, data: await renderOfferPdf(l, assets) });
      }
      const toSend = issued.filter((r) => r.status === "generated").map((r) => ({ letter: r.letter!, folder: FOLDER_TO_SEND }));
      if (toSend.length) files.push({ name: "Email drafts - open this.html", data: new TextEncoder().encode(draftsHtml(toSend)) });
      files.push({ name: "Offer letters register.xlsx", data: registerWorkbook(await loadXlsx(), records) });
      saveBytes(makeZip(files), `offer-letters-${todayIso()}.zip`, "application/zip");
    } catch (err) {
      toast.show({ tone: "danger", title: "Couldn't make the ZIP", description: err instanceof Error ? err.message : undefined });
    } finally {
      setBusy("");
    }
  }

  function downloadDrafts() {
    const toSend = records.filter((r) => r.status === "generated").map((r) => ({ letter: r.letter!, folder: FOLDER_TO_SEND }));
    if (!toSend.length) {
      toast.show({ tone: "warning", title: "No letters waiting to be sent" });
      return;
    }
    saveBytes(new TextEncoder().encode(draftsHtml(toSend)), `offer-letter-email-drafts-${todayIso()}.html`, "text/html");
  }

  const filterOptions: { value: Filter; label: string }[] = [
    { value: "all", label: `All (${c.all})` },
    { value: "new", label: `Not generated (${c.new})` },
    { value: "generated", label: `To send (${c.generated})` },
    { value: "sent", label: `Sent (${c.sent})` },
  ];

  return (
    <div className="space-y-6">
      <Card
        title="Add candidates"
        description="Upload the Excel sheet (or add one person). Every name appears in the list below, ready to generate."
        actions={
          <Button variant="secondary" size="sm" onClick={() => void downloadTemplate()}>
            Download Excel template
          </Button>
        }
      >
        <ol className="mb-4 grid gap-2 text-sm text-fg-secondary sm:grid-cols-4">
          <li><span className="font-semibold text-fg">1. Add</span> – upload Excel or add one</li>
          <li><span className="font-semibold text-fg">2. Generate</span> – one click per person, or all</li>
          <li><span className="font-semibold text-fg">3. Email draft</span> – copy, attach the PDF, send</li>
          <li><span className="font-semibold text-fg">4. Mark as sent</span> – the list shows the date</li>
        </ol>
        <div className="flex flex-wrap items-end gap-3">
          <FormField label="Upload Excel" hint="The template, or a register you downloaded earlier (restores the statuses)">
            {(p) => (
              <input
                {...p}
                ref={fileInput}
                type="file"
                accept=".xlsx,.xls,.csv"
                disabled={busy !== ""}
                onChange={(e) => void onFile(e.target.files?.[0])}
                className="block text-sm text-fg-secondary file:mr-3 file:rounded-md file:border file:border-line file:bg-surface file:px-3 file:py-2 file:text-sm file:font-medium"
              />
            )}
          </FormField>
          <Button variant="secondary" onClick={() => setEditing("new")}>
            Add one candidate
          </Button>
        </div>
      </Card>

      <Card
        title="Candidates and offer letters"
        description="Kept in this browser. Download the register (Excel) now and then as a backup; uploading it restores the list."
      >
        <div className="mb-4 flex flex-wrap items-center gap-2">
          <Button onClick={() => doGenerate(pending.map((r) => r.id))} disabled={!pending.length}>
            Generate all not generated ({pending.length})
          </Button>
          <Button variant="secondary" onClick={downloadDrafts} disabled={!c.generated}>
            Email drafts page ({c.generated})
          </Button>
          <Button variant="secondary" loading={busy === "zip"} onClick={() => void downloadZip()} disabled={!(c.generated + c.sent)}>
            Download all (ZIP)
          </Button>
          <Button variant="ghost" onClick={() => void downloadRegister()} disabled={!records.length}>
            Download register (Excel)
          </Button>
        </div>
        <Table<OfferRecord>
          caption="Candidates and offer letters"
          rows={shown}
          rowKey={(r) => r.id}
          toolbar={
            <div className="flex flex-wrap items-end gap-3">
              <Segmented legend="Show" hideLegend name="offer-filter" variant="pills" value={filter} options={filterOptions} onChange={setFilter} />
              <Input aria-label="Search by name, email or ref" placeholder="Search name, email or ref" value={query} onChange={(e) => setQuery(e.target.value)} className="max-w-xs" />
            </div>
          }
          empty={{
            title: records.length ? "Nothing here" : "No candidates yet",
            description: records.length ? "Try another filter." : "Upload the Excel sheet or add one candidate above.",
          }}
          columns={[
            { key: "ref", header: "Ref. No.", cell: (r) => r.letter?.ref ?? (r.input.ref || <span className="text-fg-secondary">on generate</span>), priority: "secondary" },
            {
              key: "name",
              header: "Name",
              priority: "primary",
              cell: (r) => (
                <span>
                  <span className="font-medium">{r.input.name}</span>
                  <br />
                  <span className="text-sm text-fg-secondary">{r.input.email || "no email"}</span>
                </span>
              ),
            },
            {
              key: "letter",
              header: "Letter",
              cell: (r) => (
                <span className="text-sm">
                  {kindLabel(r.input.kind ?? "internship")}
                  <br />
                  <span className="text-fg-secondary">{letterSummary(r)}</span>
                </span>
              ),
            },
            { key: "status", header: "Status", cell: (r) => <StatusCell r={r} /> },
            {
              key: "actions",
              header: <span className="sr-only">Actions</span>,
              align: "right",
              cell: (r) => (
                <div className="flex flex-wrap justify-end gap-1">
                  {r.status === "new" ? (
                    <>
                      <Button size="sm" onClick={() => doGenerate([r.id])}>
                        Generate {(LETTER_KINDS.find((k) => k.value === (r.input.kind ?? "internship"))?.short ?? "").toLowerCase()} offer letter
                      </Button>
                      <Button size="sm" variant="ghost" onClick={() => setEditing(r)}>Edit</Button>
                      <Button size="sm" variant="ghost" onClick={() => setRemoving(r)}>Remove</Button>
                    </>
                  ) : (
                    <>
                      <Button size="sm" variant="ghost" loading={busy === `open:${r.id}`} onClick={() => void open(r)}>Open</Button>
                      <Button size="sm" variant="ghost" onClick={() => void download(r)}>PDF</Button>
                      <Button size="sm" variant="secondary" onClick={() => setDraftOf(r)}>Email draft</Button>
                      {r.status === "generated" ? (
                        <Button size="sm" onClick={() => sent([r.id])}>Mark as sent</Button>
                      ) : (
                        <Button size="sm" variant="ghost" onClick={() => saveAll(undoSent(records, [r.id]))}>Undo sent</Button>
                      )}
                      {r.status === "generated" ? <Button size="sm" variant="ghost" onClick={() => setEditing(r)}>Edit</Button> : null}
                    </>
                  )}
                </div>
              ),
            },
          ]}
        />
      </Card>

      <OfferSettingsCard
        settings={settings}
        onSave={(s) => {
          setSettings(s);
          saveSettings(s);
        }}
      />

      <CandidateDialog
        open={editing !== null}
        record={editing === "new" ? null : editing}
        settings={settings}
        onClose={() => setEditing(null)}
        onSave={(input) => {
          if (editing === "new" || editing === null) {
            saveAll([...records, { id: newId(), input, status: "new", addedOn: todayIso() }]);
            toast.show({ tone: "success", title: `${input.name} added`, description: "Click Generate next to the name." });
          } else {
            saveAll(reopen(records, editing.id, input));
            toast.show({ tone: "success", title: "Details saved", description: editing.status === "new" ? undefined : "Generate the letter again to update it." });
          }
          setEditing(null);
        }}
      />
      <DraftDialog
        record={draftOf}
        signature={settings.signature}
        onClose={() => setDraftOf(null)}
        onSent={(r) => {
          sent([r.id]);
          setDraftOf(null);
        }}
      />
      <ConfirmDialog
        open={removing !== null}
        onClose={() => setRemoving(null)}
        title={`Remove ${removing?.input.name ?? "this candidate"}?`}
        description="They are removed from this list. Nothing was generated for them yet."
        confirmLabel="Remove"
        danger
        onConfirm={() => {
          if (removing) saveAll(removeRecords(records, [removing.id]));
          setRemoving(null);
        }}
      />
    </div>
  );
}

function StatusCell({ r }: { r: OfferRecord }) {
  if (r.status === "sent") return <Badge tone="success">Sent {shortDate(r.sentOn)}</Badge>;
  if (r.status === "generated") return <Badge tone="warning">{STATUS_LABEL.generated}</Badge>;
  const errs = rowErrors(r);
  return errs.length ? <span className="text-sm text-danger">{errs.join(". ")}</span> : <Badge tone="neutral">{STATUS_LABEL.new}</Badge>;
}

/* ------------------------------------------------------------------ add / edit one candidate */

function blankInput(s: OfferSettings, kind: LetterKind = "internship"): OfferInput {
  return kind === "employment"
    ? { kind, name: "", email: "", letterDate: todayIso(), ref: "", role: s.empRole, mode: "on-site", months: s.months, ctc: s.ctc, probation: s.probation, location: s.location }
    : { kind, name: "", email: "", letterDate: todayIso(), ref: "", role: s.role, mode: s.mode, months: s.months };
}

function CandidateDialog({
  open,
  record,
  settings,
  onClose,
  onSave,
}: {
  open: boolean;
  record: OfferRecord | null;
  settings: OfferSettings;
  onClose: () => void;
  onSave: (input: OfferInput) => void;
}) {
  const [f, setF] = useState<OfferInput>(() => blankInput(settings));
  const [tried, setTried] = useState(false);
  useEffect(() => {
    if (!open) return;
    setF(record ? { ...record.input, ref: record.letter?.ref ?? record.input.ref } : blankInput(settings));
    setTried(false);
  }, [open, record, settings]);
  const set = <K extends keyof OfferInput>(k: K, v: OfferInput[K]) => setF((x) => ({ ...x, [k]: v }));
  const kind = f.kind ?? "internship";
  const emp = kind === "employment";
  const period = !emp && isIsoDate(f.letterDate) && f.months >= 1 ? periodOf(f.letterDate, f.months) : null;
  const joining = emp && isIsoDate(f.letterDate) ? f.start || addDays(f.letterDate, 1) : "";
  const missing = !f.name.trim() ? "Enter the name" : !isIsoDate(f.letterDate) ? "Enter the letter date" : !f.role.trim() ? (emp ? "Enter the position" : "Enter the role") : emp && !(f.ctc ?? "").trim() ? "Enter the annual CTC" : "";

  return (
    <Dialog
      open={open}
      onClose={onClose}
      size="lg"
      title={record ? `Edit ${record.input.name}` : "Add one candidate"}
      footer={
        <div className="flex justify-end gap-2">
          <Button variant="secondary" onClick={onClose}>Cancel</Button>
          <Button
            onClick={() => {
              setTried(true);
              if (!missing) onSave({ ...f, name: f.name.trim(), email: f.email.trim() });
            }}
          >
            {record ? "Save" : "Add to list"}
          </Button>
        </div>
      }
    >
      <div className="space-y-4">
        <Segmented
          legend="Letter template"
          name="offer-kind"
          variant="pills"
          value={kind}
          options={LETTER_KINDS.map((k) => ({ value: k.value, label: k.label }))}
          onChange={(k) => setF((x) => ({ ...blankInput(settings, k), name: x.name, email: x.email, letterDate: x.letterDate, ref: x.ref }))}
        />
        {tried && missing ? <p className="text-sm text-danger">{missing}</p> : null}
        <div className="grid gap-4 sm:grid-cols-2">
          <FormField label="Full name" required>{(p) => <Input {...p} value={f.name} onChange={(e) => set("name", e.target.value)} />}</FormField>
          <FormField label="Email" hint="For the email draft">{(p) => <Input {...p} type="email" value={f.email} onChange={(e) => set("email", e.target.value)} />}</FormField>
          <FormField label="Letter date" required hint={period ? `Period: ${longDate(period.start)} – ${longDate(period.end)}` : joining ? `Joining: ${shortDate(joining)}` : undefined}>
            {(p) => <Input {...p} type="date" value={f.letterDate} onChange={(e) => set("letterDate", e.target.value)} />}
          </FormField>
          <FormField label="Ref. No." hint="Leave blank: the next number is given when you generate">
            {(p) => <Input {...p} value={f.ref} onChange={(e) => set("ref", e.target.value)} />}
          </FormField>
          <FormField label={emp ? "Position" : "Role"} required>{(p) => <Input {...p} value={f.role} onChange={(e) => set("role", e.target.value)} />}</FormField>
          <FormField label="Mode">{(p) => <Select {...p} options={MODE_OPTIONS} value={f.mode} onChange={(e) => set("mode", e.target.value)} />}</FormField>
          {emp ? (
            <>
              <FormField label="Date of joining" hint="Blank = the day after the letter date">
                {(p) => <Input {...p} type="date" value={f.start ?? ""} onChange={(e) => set("start", e.target.value || undefined)} />}
              </FormField>
              <FormField label="Annual CTC" required hint="e.g. 420000 → ₹4,20,000 per annum">
                {(p) => <Input {...p} value={f.ctc ?? ""} onChange={(e) => set("ctc", e.target.value)} />}
              </FormField>
              <FormField label="Probation (months)" hint="0 = no probation">
                {(p) => <Input {...p} type="number" min={0} max={12} value={String(f.probation ?? 0)} onChange={(e) => set("probation", Number(e.target.value))} />}
              </FormField>
              <FormField label="Location">{(p) => <Input {...p} value={f.location ?? ""} onChange={(e) => set("location", e.target.value)} />}</FormField>
            </>
          ) : (
            <FormField label="Duration (months)">
              {(p) => <Input {...p} type="number" min={1} max={24} value={String(f.months)} onChange={(e) => set("months", Number(e.target.value))} />}
            </FormField>
          )}
        </div>
      </div>
    </Dialog>
  );
}

/* ------------------------------------------------------------------ email draft */

function useCopy() {
  const toast = useToast();
  return async (text: string, what: string) => {
    try {
      await navigator.clipboard.writeText(text);
      toast.show({ tone: "success", title: `${what} copied` });
    } catch {
      toast.show({ tone: "warning", title: "Couldn't copy", description: "Select the text and copy it by hand." });
    }
  };
}

function DraftDialog({ record, signature, onClose, onSent }: { record: OfferRecord | null; signature: string; onClose: () => void; onSent: (r: OfferRecord) => void }) {
  const copy = useCopy();
  const [busy, setBusy] = useState(false);
  const d = record?.letter ? emailDraft(record.letter) : null;
  async function attachment() {
    if (!record?.letter) return;
    setBusy(true);
    try {
      saveBytes(await makePdf(record.letter, signature), offerFileName(record.letter), "application/pdf");
    } finally {
      setBusy(false);
    }
  }
  return (
    <Dialog
      open={record !== null}
      onClose={onClose}
      size="lg"
      title={`Email draft – ${record?.input.name ?? ""}`}
      description="Copy each part into a new email from the HR mailbox, attach the PDF, send it, then click Mark as sent."
      footer={
        d && record ? (
          <div className="flex flex-wrap justify-end gap-2">
            <Button variant="secondary" loading={busy} onClick={() => void attachment()}>Download PDF to attach</Button>
            <Button variant="secondary" onClick={() => window.open(gmailComposeUrl(d), "_blank", "noopener")} disabled={!d.to}>Open in Gmail</Button>
            {record.status === "generated" ? <Button onClick={() => onSent(record)}>Mark as sent</Button> : <Badge tone="success">Sent {shortDate(record.sentOn)}</Badge>}
          </div>
        ) : null
      }
    >
      {d ? (
        <div className="space-y-3 text-sm">
          <DraftLine label="To" value={d.to || "(no email in the details)"} onCopy={d.to ? () => void copy(d.to, "Address") : undefined} />
          <DraftLine label="Subject" value={d.subject} onCopy={() => void copy(d.subject, "Subject")} />
          <DraftLine label="Attachment" value={d.attachment} />
          <div>
            <div className="mb-1 flex items-center justify-between">
              <span className="font-medium">Body</span>
              <Button size="sm" variant="ghost" onClick={() => void copy(d.body, "Body")}>Copy</Button>
            </div>
            <Textarea readOnly rows={14} value={d.body} aria-label="Email body" className="font-mono text-xs" />
          </div>
        </div>
      ) : null}
    </Dialog>
  );
}

function DraftLine({ label, value, onCopy }: { label: string; value: string; onCopy?: () => void }) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      <span className="w-24 shrink-0 font-medium">{label}</span>
      <span className="min-w-0 flex-1 break-words">{value}</span>
      {onCopy ? (
        <Button size="sm" variant="ghost" onClick={onCopy}>
          Copy
        </Button>
      ) : null}
    </div>
  );
}

/* ------------------------------------------------------------------ settings */

function OfferSettingsCard({ settings, onSave }: { settings: OfferSettings; onSave: (s: OfferSettings) => void }) {
  const toast = useToast();
  const [s, setS] = useState(settings);
  useEffect(() => setS(settings), [settings]);
  const [localSig, setLocalSig] = useState(false);
  useEffect(() => {
    let live = true;
    void localSignature().then((b) => live && setLocalSig(Boolean(b)));
    return () => {
      live = false;
    };
  }, []);
  const set = <K extends keyof OfferSettings>(k: K, v: OfferSettings[K]) => setS((x) => ({ ...x, [k]: v }));

  function onSignature(file: File | undefined) {
    if (!file) return;
    if (!/^image\/(png|jpe?g)$/.test(file.type)) {
      toast.show({ tone: "warning", title: "Use a PNG or JPEG image" });
      return;
    }
    const r = new FileReader();
    r.onload = () => set("signature", String(r.result));
    r.readAsDataURL(file);
  }

  const text = (k: "company" | "address" | "website" | "signatory" | "designation" | "role" | "nextRef" | "empRole" | "empNextRef" | "ctc" | "location", label: string, hint?: string) => (
    <FormField label={label} hint={hint}>
      {(p) => <Input {...p} value={s[k]} onChange={(e) => set(k, e.target.value)} />}
    </FormField>
  );

  return (
    <Card title="Offer letter settings" description="Kept in this browser. Used for every new letter and as the defaults for blank Excel cells.">
      <h3 className="mb-2 text-sm font-semibold">Company and signatory</h3>
      <div className="grid gap-4 sm:grid-cols-2">
        {text("company", "Company name")}
        {text("address", "Address (letter header)")}
        {text("website", "Website")}
        {text("signatory", "Signatory name")}
        {text("designation", "Signatory designation")}
        <FormField label="Signature image" hint="PNG with a transparent background looks best. Without one, the letter has a blank space to sign.">
          {(p) => (
            <div className="flex flex-wrap items-center gap-3">
              {s.signature ? <img src={s.signature} alt="Current signature" className="h-14 w-auto rounded border border-line bg-white p-1" /> : localSig ? <img src={LOCAL_SIGNATURE_URL} alt="Saved signature on this laptop" className="h-14 w-auto rounded border border-line bg-white p-1" /> : <span className="text-sm text-fg-secondary">No signature</span>}
              <input {...p} type="file" accept="image/png,image/jpeg" onChange={(e) => onSignature(e.target.files?.[0])} className="block text-sm text-fg-secondary file:mr-3 file:rounded-md file:border file:border-line file:bg-surface file:px-3 file:py-2 file:text-sm file:font-medium" />
              {s.signature ? <Button size="sm" variant="ghost" onClick={() => set("signature", "")}>Remove</Button> : null}
            </div>
          )}
        </FormField>
      </div>
      <h3 className="mb-2 mt-6 text-sm font-semibold">Internship offer letter</h3>
      <div className="grid gap-4 sm:grid-cols-2">
        {text("nextRef", "Next reference number", "Goes up by one after each generated letter")}
        {text("role", "Default role")}
        <div className="grid grid-cols-2 gap-4">
          <FormField label="Default mode">{(p) => <Select {...p} options={MODE_OPTIONS} value={s.mode} onChange={(e) => set("mode", e.target.value)} />}</FormField>
          <FormField label="Default months">{(p) => <Input {...p} type="number" min={1} max={24} value={String(s.months)} onChange={(e) => set("months", Number(e.target.value) || 1)} />}</FormField>
        </div>
      </div>
      <h3 className="mb-2 mt-6 text-sm font-semibold">Employment offer letter</h3>
      <div className="grid gap-4 sm:grid-cols-2">
        {text("empNextRef", "Next reference number", "A separate series, e.g. TD-EO-2026-0001")}
        {text("empRole", "Default position")}
        {text("ctc", "Default annual CTC", "Blank = must be given for each person")}
        {text("location", "Default location")}
        <FormField label="Default probation (months)">{(p) => <Input {...p} type="number" min={0} max={12} value={String(s.probation)} onChange={(e) => set("probation", Number(e.target.value) || 0)} />}</FormField>
      </div>
      <div className="mt-5">
        <Button
          onClick={() => {
            onSave(s);
            toast.show({ tone: "success", title: "Offer letter settings saved" });
          }}
        >
          Save settings
        </Button>
      </div>
    </Card>
  );
}

