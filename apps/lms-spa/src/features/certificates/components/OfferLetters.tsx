"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { Badge, Button, Card, Dialog, FormField, Input, Select, Table, Textarea, useToast } from "@/components/ui";
import { loadXlsx, saveBytes, XLSX_MIME } from "../lib/bulk";
import { makeZip } from "../lib/zip";
import {
  MODES,
  buildOffer,
  emailDraft,
  gmailComposeUrl,
  isIsoDate,
  loadSettings,
  longDate,
  nextRef,
  offerErrors,
  offerFileName,
  parseOfferSheet,
  periodOf,
  saveSettings,
  templateWorkbook,
  todayIso,
  type EmailDraft,
  type OfferInput,
  type OfferLetter,
  type OfferSettings,
} from "../lib/offer";
import { LOCAL_SIGNATURE_URL, loadOfferAssets, localSignature, renderOfferPdf } from "../lib/offerpdf";

const MODE_OPTIONS = MODES.map((m) => ({ value: m, label: m[0]!.toUpperCase() + m.slice(1) }));

async function makePdf(l: OfferLetter): Promise<Uint8Array> {
  return renderOfferPdf(l, await loadOfferAssets(l.signature));
}

function openPdf(bytes: Uint8Array): void {
  const url = URL.createObjectURL(new Blob([bytes as BlobPart], { type: "application/pdf" }));
  window.open(url, "_blank", "noopener");
  window.setTimeout(() => URL.revokeObjectURL(url), 120_000);
}

/** The highest ref + 1, when it is beyond the stored next number (keeps numbering moving forward). */
function bumpRef(current: string, used: string[]): string {
  const num = (r: string) => Number(/(\d+)$/.exec(r)?.[1] ?? NaN);
  let next = current;
  for (const r of used) if (num(r) >= num(next) && r.replace(/\d+$/, "") === next.replace(/\d+$/, "")) next = nextRef(r);
  return next;
}

/** Certificates & documents > Offer letters: one letter from a form, or many from an Excel sheet. */
export function OfferLettersTab() {
  const [settings, setSettings] = useState<OfferSettings>(() => loadSettings());
  const update = (s: OfferSettings) => {
    setSettings(s);
    saveSettings(s);
  };
  return (
    <div className="space-y-6">
      <SingleLetter settings={settings} onRefUsed={(r) => update({ ...settings, nextRef: bumpRef(settings.nextRef, [r]) })} />
      <BulkLetters settings={settings} onRefsUsed={(rs) => update({ ...settings, nextRef: bumpRef(settings.nextRef, rs) })} />
      <OfferSettingsCard settings={settings} onSave={update} />
    </div>
  );
}

/* ------------------------------------------------------------------ single */

function SingleLetter({ settings, onRefUsed }: { settings: OfferSettings; onRefUsed: (ref: string) => void }) {
  const toast = useToast();
  const blank = (): OfferInput => ({ name: "", email: "", letterDate: todayIso(), ref: settings.nextRef, role: settings.role, mode: settings.mode, months: settings.months });
  const [f, setF] = useState<OfferInput>(blank);
  const [override, setOverride] = useState(false);
  const [busy, setBusy] = useState("");
  const [draft, setDraft] = useState<{ draft: EmailDraft; letter: OfferLetter } | null>(null);
  const [tried, setTried] = useState(false);
  useEffect(() => setF((x) => ({ ...x, ref: settings.nextRef })), [settings.nextRef]);

  const input: OfferInput = override ? f : { ...f, start: undefined, end: undefined };
  const errors = offerErrors(input);
  const period = isIsoDate(f.letterDate) && f.months >= 1 ? periodOf(f.letterDate, f.months) : null;
  const set = <K extends keyof OfferInput>(k: K, v: OfferInput[K]) => setF((x) => ({ ...x, [k]: v }));

  async function run(kind: "preview" | "download" | "draft") {
    setTried(true);
    if (errors.length) {
      toast.show({ tone: "warning", title: "Fill in the letter details", description: errors.join(". ") + "." });
      return;
    }
    const letter = buildOffer(input, settings);
    if (kind === "draft") {
      setDraft({ draft: emailDraft(letter), letter });
      return;
    }
    setBusy(kind);
    try {
      const bytes = await makePdf(letter);
      if (kind === "preview") openPdf(bytes);
      else {
        saveBytes(bytes, offerFileName(letter), "application/pdf");
        onRefUsed(letter.ref);
        toast.show({ tone: "success", title: `Offer letter ${letter.ref} downloaded` });
      }
    } catch (err) {
      toast.show({ tone: "danger", title: "Couldn't make the PDF", description: err instanceof Error ? err.message : undefined });
    } finally {
      setBusy("");
    }
  }

  return (
    <Card title="Single offer letter" description="Fill in the student's details. The internship starts the day after the letter date.">
      <div className="grid gap-4 sm:grid-cols-2">
        <FormField label="Student's full name" required error={tried && !f.name.trim() ? "Enter the name" : undefined}>
          {(p) => <Input {...p} value={f.name} onChange={(e) => set("name", e.target.value)} placeholder="Perikela Jaya Satya Sai Prakash" />}
        </FormField>
        <FormField label="Email" hint="For the email draft">
          {(p) => <Input {...p} type="email" value={f.email} onChange={(e) => set("email", e.target.value)} placeholder="student@gmail.com" />}
        </FormField>
        <FormField label="Letter date" required hint={period ? `Period: ${longDate(period.start)} – ${longDate(period.end)}` : undefined}>
          {(p) => <Input {...p} type="date" value={f.letterDate} onChange={(e) => set("letterDate", e.target.value)} />}
        </FormField>
        <FormField label="Ref. No. / Intern ID" required>
          {(p) => <Input {...p} value={f.ref} onChange={(e) => set("ref", e.target.value)} />}
        </FormField>
        <FormField label="Role (letter title)" required>
          {(p) => <Input {...p} value={f.role} onChange={(e) => set("role", e.target.value)} />}
        </FormField>
        <div className="grid grid-cols-2 gap-4">
          <FormField label="Mode">{(p) => <Select {...p} options={MODE_OPTIONS} value={f.mode} onChange={(e) => set("mode", e.target.value)} />}</FormField>
          <FormField label="Duration (months)">
            {(p) => <Input {...p} type="number" min={1} max={24} value={String(f.months)} onChange={(e) => set("months", Number(e.target.value))} />}
          </FormField>
        </div>
      </div>
      <label className="mt-4 flex items-center gap-2 text-sm">
        <input type="checkbox" checked={override} onChange={(e) => setOverride(e.target.checked)} /> Set the start and end dates myself
      </label>
      {override ? (
        <div className="mt-3 grid gap-4 sm:grid-cols-2">
          <FormField label="Start date">{(p) => <Input {...p} type="date" value={f.start ?? period?.start ?? ""} onChange={(e) => set("start", e.target.value)} />}</FormField>
          <FormField label="End date">{(p) => <Input {...p} type="date" value={f.end ?? period?.end ?? ""} onChange={(e) => set("end", e.target.value)} />}</FormField>
        </div>
      ) : null}
      <div className="mt-5 flex flex-wrap gap-2">
        <Button onClick={() => void run("download")} loading={busy === "download"}>
          Generate PDF
        </Button>
        <Button variant="secondary" onClick={() => void run("preview")} loading={busy === "preview"}>
          Preview
        </Button>
        <Button variant="secondary" onClick={() => void run("draft")}>
          Generate email draft
        </Button>
        <Button
          variant="ghost"
          onClick={() => {
            setF(blank());
            setTried(false);
            setOverride(false);
          }}
        >
          Clear
        </Button>
      </div>
      <DraftDialog item={draft} onClose={() => setDraft(null)} />
    </Card>
  );
}

/* ------------------------------------------------------------------ bulk */

interface Row {
  key: string;
  input: OfferInput;
  errors: string[];
  letter: OfferLetter | null;
}

function BulkLetters({ settings, onRefsUsed }: { settings: OfferSettings; onRefsUsed: (refs: string[]) => void }) {
  const toast = useToast();
  const fileInput = useRef<HTMLInputElement>(null);
  const [rows, setRows] = useState<Row[] | null>(null);
  const [busy, setBusy] = useState("");
  const [progress, setProgress] = useState("");
  const [draft, setDraft] = useState<{ draft: EmailDraft; letter: OfferLetter } | null>(null);
  const [allDrafts, setAllDrafts] = useState(false);
  const ready = useMemo(() => (rows ?? []).filter((r) => r.letter), [rows]);

  async function downloadTemplate() {
    const x = await loadXlsx();
    saveBytes(templateWorkbook(x, settings), "offer-letters-template.xlsx", XLSX_MIME);
  }

  async function onFile(file: File | undefined) {
    if (!file) return;
    setBusy("read");
    try {
      const x = await loadXlsx();
      const inputs = parseOfferSheet(x, new Uint8Array(await file.arrayBuffer()), settings, settings.nextRef);
      const seen = new Set<string>();
      setRows(
        inputs.map((input, i) => {
          const errors = offerErrors(input);
          if (seen.has(input.ref)) errors.push(`Ref ${input.ref} is used twice`);
          seen.add(input.ref);
          return { key: `${i}-${input.ref}`, input, errors, letter: errors.length ? null : buildOffer(input, settings) };
        }),
      );
      if (!inputs.length) toast.show({ tone: "warning", title: "No rows found", description: "Fill in rows under the header of the first sheet." });
    } catch (err) {
      toast.show({ tone: "danger", title: "Couldn't read the file", description: err instanceof Error ? err.message : "Use the .xlsx template." });
    } finally {
      setBusy("");
      if (fileInput.current) fileInput.current.value = "";
    }
  }

  async function one(l: OfferLetter, kind: "download" | "preview") {
    setBusy(`${kind}:${l.ref}`);
    try {
      const bytes = await makePdf(l);
      if (kind === "preview") openPdf(bytes);
      else saveBytes(bytes, offerFileName(l), "application/pdf");
    } catch (err) {
      toast.show({ tone: "danger", title: "Couldn't make the PDF", description: err instanceof Error ? err.message : undefined });
    } finally {
      setBusy("");
    }
  }

  async function all() {
    if (!ready.length) return;
    setBusy("zip");
    try {
      const assets = await loadOfferAssets(settings.signature);
      const files = [];
      for (const [i, r] of ready.entries()) {
        setProgress(`${i + 1} of ${ready.length}`);
        files.push({ name: offerFileName(r.letter!), data: await renderOfferPdf(r.letter!, assets) });
      }
      saveBytes(makeZip(files), `offer-letters-${todayIso()}.zip`, "application/zip");
      onRefsUsed(ready.map((r) => r.letter!.ref));
      toast.show({ tone: "success", title: `${files.length} offer letter${files.length === 1 ? "" : "s"} generated`, description: rows!.length - ready.length ? `${rows!.length - ready.length} row(s) skipped; fix them in the sheet and upload again.` : undefined });
    } catch (err) {
      toast.show({ tone: "danger", title: "Couldn't make the letters", description: err instanceof Error ? err.message : undefined });
    } finally {
      setBusy("");
      setProgress("");
    }
  }

  return (
    <Card
      title="Bulk offer letters from Excel"
      description="Download the template, fill one row per student, then upload it. Blank Ref No cells are numbered automatically from the next reference number."
      actions={
        <Button variant="secondary" size="sm" onClick={() => void downloadTemplate()}>
          Download Excel template
        </Button>
      }
    >
      <FormField label="Upload the filled template" hint=".xlsx or .csv. Columns: Name, Email, Letter date, Ref No, Role, Mode, Duration (months), Start date, End date">
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
      {rows ? (
        <div className="mt-5 space-y-3">
          <div className="flex flex-wrap items-center gap-2">
            <Button onClick={() => void all()} loading={busy === "zip"} disabled={!ready.length || busy !== ""}>
              {busy === "zip" ? `Generating ${progress}` : `Generate all ${ready.length} (ZIP)`}
            </Button>
            <Button variant="secondary" onClick={() => setAllDrafts(true)} disabled={!ready.length}>
              Email drafts for all
            </Button>
            <span className="text-sm text-fg-secondary">
              {ready.length} ready{rows.length - ready.length ? `, ${rows.length - ready.length} need fixing` : ""}
            </span>
          </div>
          <Table<Row>
            caption="Offer letters from the uploaded sheet"
            rows={rows}
            rowKey={(r) => r.key}
            columns={[
              { key: "ref", header: "Ref. No.", cell: (r) => r.input.ref, priority: "secondary" },
              { key: "name", header: "Name", cell: (r) => <span className="font-medium">{r.input.name}</span>, priority: "primary" },
              { key: "email", header: "Email", cell: (r) => r.input.email || <span className="text-fg-secondary">–</span> },
              { key: "period", header: "Letter date / period", cell: (r) => (r.letter ? <span className="text-sm">{r.letter.date}<br />{r.letter.start} – {r.letter.end}</span> : r.input.letterDate) },
              {
                key: "status",
                header: "Status",
                cell: (r) => (r.errors.length ? <span className="text-sm text-danger">{r.errors.join(". ")}</span> : <Badge tone="success">Ready</Badge>),
              },
              {
                key: "actions",
                header: <span className="sr-only">Actions</span>,
                align: "right",
                cell: (r) =>
                  r.letter ? (
                    <div className="flex flex-wrap justify-end gap-1">
                      <Button size="sm" variant="ghost" loading={busy === `preview:${r.letter.ref}`} onClick={() => void one(r.letter!, "preview")}>Preview</Button>
                      <Button size="sm" variant="ghost" loading={busy === `download:${r.letter.ref}`} onClick={() => void one(r.letter!, "download")}>PDF</Button>
                      <Button size="sm" variant="secondary" onClick={() => setDraft({ draft: emailDraft(r.letter!), letter: r.letter! })}>Generate draft</Button>
                    </div>
                  ) : null,
              },
            ]}
          />
        </div>
      ) : null}
      <DraftDialog item={draft} onClose={() => setDraft(null)} />
      <AllDraftsDialog open={allDrafts} letters={ready.map((r) => r.letter!)} onClose={() => setAllDrafts(false)} />
    </Card>
  );
}

/* ------------------------------------------------------------------ email drafts */

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

function DraftDialog({ item, onClose }: { item: { draft: EmailDraft; letter: OfferLetter } | null; onClose: () => void }) {
  const copy = useCopy();
  const [busy, setBusy] = useState(false);
  const d = item?.draft;
  async function attachment() {
    if (!item) return;
    setBusy(true);
    try {
      saveBytes(await makePdf(item.letter), item.draft.attachment, "application/pdf");
    } finally {
      setBusy(false);
    }
  }
  return (
    <Dialog
      open={item !== null}
      onClose={onClose}
      size="lg"
      title="Email draft"
      description="Send it from the HR mailbox and attach the offer letter PDF."
      footer={
        d ? (
          <div className="flex flex-wrap justify-end gap-2">
            <Button variant="secondary" onClick={() => void copy(`Subject: ${d.subject}\n\n${d.body}`, "Email")}>Copy all</Button>
            <Button variant="secondary" loading={busy} onClick={() => void attachment()}>Download attachment</Button>
            <Button onClick={() => window.open(gmailComposeUrl(d), "_blank", "noopener")} disabled={!d.to}>Open in Gmail</Button>
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
            <Textarea readOnly rows={16} value={d.body} aria-label="Email body" className="font-mono text-xs" />
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

function AllDraftsDialog({ open, letters, onClose }: { open: boolean; letters: OfferLetter[]; onClose: () => void }) {
  const copy = useCopy();
  const text = letters
    .map((l) => {
      const d = emailDraft(l);
      return `To: ${d.to || "(no email)"}\nSubject: ${d.subject}\nAttachment: ${d.attachment}\n\n${d.body}`;
    })
    .join("\n\n" + "=".repeat(60) + "\n\n");
  return (
    <Dialog
      open={open}
      onClose={onClose}
      size="xl"
      title={`Email drafts (${letters.length})`}
      footer={
        <div className="flex flex-wrap justify-end gap-2">
          <Button variant="secondary" onClick={() => saveBytes(new TextEncoder().encode(text), `offer-letter-emails-${todayIso()}.txt`, "text/plain")}>Download .txt</Button>
          <Button onClick={() => void copy(text, "All drafts")}>Copy all</Button>
        </div>
      }
    >
      <ul className="space-y-2">
        {letters.map((l) => {
          const d = emailDraft(l);
          return (
            <li key={l.ref} className="flex flex-wrap items-center gap-2 border-b border-line pb-2 text-sm">
              <span className="min-w-0 flex-1">
                <span className="font-medium">{l.name}</span> <span className="text-fg-secondary">{d.to || "no email"}</span>
              </span>
              <Button size="sm" variant="ghost" onClick={() => void copy(d.body, "Body")}>Copy body</Button>
              <Button size="sm" variant="secondary" disabled={!d.to} onClick={() => window.open(gmailComposeUrl(d), "_blank", "noopener")}>Open in Gmail</Button>
            </li>
          );
        })}
      </ul>
    </Dialog>
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

  const text = (k: "company" | "address" | "website" | "signatory" | "designation" | "role" | "nextRef", label: string, hint?: string) => (
    <FormField label={label} hint={hint}>
      {(p) => <Input {...p} value={s[k]} onChange={(e) => set(k, e.target.value)} />}
    </FormField>
  );

  return (
    <Card title="Offer letter settings" description="Kept in this browser. Used for every new letter and as the defaults for blank Excel cells.">
      <div className="grid gap-4 sm:grid-cols-2">
        {text("company", "Company name")}
        {text("address", "Address (letter header)")}
        {text("website", "Website")}
        {text("nextRef", "Next reference number", "Goes up by one after each generated letter")}
        {text("role", "Default role")}
        <div className="grid grid-cols-2 gap-4">
          <FormField label="Default mode">{(p) => <Select {...p} options={MODE_OPTIONS} value={s.mode} onChange={(e) => set("mode", e.target.value)} />}</FormField>
          <FormField label="Default months">{(p) => <Input {...p} type="number" min={1} max={24} value={String(s.months)} onChange={(e) => set("months", Number(e.target.value) || 1)} />}</FormField>
        </div>
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
