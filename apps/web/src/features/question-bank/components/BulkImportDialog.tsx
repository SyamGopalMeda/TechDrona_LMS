"use client";

import { useEffect, useRef, useState } from "react";
import { Button, Dialog, FormField, Input, useToast } from "@/components/ui";
import { api } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import { TextArea, useFailToast } from "@/features/trainer/shared/ui";
import { copyText } from "../lib/labels";
import type { ImportKind, ImportProblem, ImportResult, ValidateResult } from "../lib/types";
import { KindTiles, NEW_BANK, ProblemsPanel, SaveToFields, useBankOptions } from "./parts";

export interface BulkImportDialogProps {
  open: boolean;
  onClose: () => void;
  /** Pre-selected "Save to" bank (the bank detail page passes its own id). */
  defaultBankId?: string | null;
  onImported: (result: ImportResult) => void;
  /** Debounce for refreshing the prompt while the inputs change (ms). */
  debounceMs?: number;
}

type Problems = { problems: ImportProblem[]; fix_prompt: string | null };

/** Problems carried by a 400 `validation_failed` from the import endpoint. */
export function problemsOf(err: unknown): Problems | null {
  if (!(err instanceof ApiError) || err.code !== "validation_failed") return null;
  const raw = err.problem?.problems;
  if (!Array.isArray(raw)) return null;
  const fix = err.problem?.fix_prompt;
  return { problems: raw as ImportProblem[], fix_prompt: typeof fix === "string" ? fix : null };
}

/**
 * "Bulk import via prompt": Step 1 builds a prompt for any chat model, Step 2 validates the
 * pasted JSON and imports it (all-or-nothing) as draft questions into a bank.
 */
export function BulkImportDialog({ open, onClose, defaultBankId, onImported, debounceMs = 400 }: BulkImportDialogProps) {
  const toast = useToast();
  const fail = useFailToast();
  const banks = useBankOptions(open);
  const [kind, setKind] = useState<ImportKind>("mcq");
  const [count, setCount] = useState("5");
  const [subject, setSubject] = useState("");
  const [topic, setTopic] = useState("");
  const [instructions, setInstructions] = useState("");
  const [saveTo, setSaveTo] = useState(defaultBankId ?? NEW_BANK);
  const [newName, setNewName] = useState("");
  const [prompt, setPrompt] = useState<string | null>(null);
  const [promptState, setPromptState] = useState<"idle" | "loading" | "error">("idle");
  const [raw, setRaw] = useState("");
  const [result, setResult] = useState<(ValidateResult & { raw: string; kind: ImportKind }) | null>(null);
  const [problems, setProblems] = useState<Problems | null>(null);
  const [busy, setBusy] = useState<"validate" | "import" | null>(null);
  const [announce, setAnnounce] = useState("");
  const seq = useRef(0);

  useEffect(() => {
    if (open) {
      setSaveTo(defaultBankId ?? NEW_BANK);
      setRaw("");
      setResult(null);
      setProblems(null);
      setAnnounce("");
    }
  }, [open, defaultBankId]);

  const n = Math.min(50, Math.max(1, Math.round(Number(count)) || 5));

  // Step 1 prompt: refresh (debounced) whenever the inputs change.
  useEffect(() => {
    if (!open) return;
    const id = ++seq.current;
    setPromptState("loading");
    const t = setTimeout(async () => {
      try {
        const res = await api.post<{ prompt: string }>("studio/question-banks/import/prompt", {
          question_type: kind,
          count: n,
          subject: subject.trim() || undefined,
          topic: topic.trim() || undefined,
          instructions: instructions.trim() || undefined,
        });
        if (id !== seq.current) return;
        if (res.kind === "ok") {
          setPrompt(res.data.prompt);
          setPromptState("idle");
        }
      } catch {
        if (id === seq.current) setPromptState("error");
      }
    }, debounceMs);
    return () => clearTimeout(t);
  }, [open, kind, n, subject, topic, instructions, debounceMs]);

  const copy = async (text: string | null, what: string) => {
    if (!text) return;
    const ok = await copyText(text);
    toast.show({ tone: ok ? "success" : "warning", title: ok ? `${what} copied` : "Couldn't copy — select the text and copy it manually" });
  };

  const validate = async () => {
    setBusy("validate");
    setProblems(null);
    try {
      const res = await api.post<ValidateResult>("studio/question-banks/import/validate", { question_type: kind, raw });
      if (res.kind !== "ok") return;
      setResult({ ...res.data, raw, kind });
      if (!res.data.ok) {
        setProblems({ problems: res.data.problems, fix_prompt: res.data.fix_prompt });
        setAnnounce(`${res.data.problem_count || res.data.problems.length} problems found`);
      } else setAnnounce(`${res.data.count} questions ready to import`);
    } catch (err) {
      fail(err, "Couldn't check the pasted JSON");
    } finally {
      setBusy(null);
    }
  };

  const valid = !!result?.ok && result.raw === raw && result.kind === kind;

  const doImport = async () => {
    if (!valid) return;
    setBusy("import");
    try {
      const res = await api.post<ImportResult>(
        "studio/question-banks/import",
        {
          question_type: kind,
          raw,
          ...(saveTo === NEW_BANK ? { new_bank_name: newName.trim() || undefined } : { bank_id: saveTo }),
          subject: subject.trim() || undefined,
          topic: topic.trim() || undefined,
          source: "bulk",
        },
        { idempotencyKey: true },
      );
      if (res.kind === "ok") {
        toast.show({ tone: "success", title: "Questions imported to your bank.", description: `${res.data.count} draft questions added to ${res.data.bank.name}. Review them before use.` });
        setAnnounce(`${res.data.count} questions imported`);
        onImported(res.data);
      }
    } catch (err) {
      const p = problemsOf(err);
      if (p) {
        setProblems(p);
        setResult(null);
      } else fail(err, "Couldn't import the questions");
    } finally {
      setBusy(null);
    }
  };

  return (
    <Dialog
      open={open}
      onClose={onClose}
      dismissible={busy === null}
      className="max-w-3xl"
      title="Bulk import via prompt"
      description="Generate questions with any chat model, then paste its JSON here. Imported questions are drafts that need review before use."
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={busy !== null}>
            Cancel
          </Button>
          <Button variant="secondary" onClick={() => void validate()} loading={busy === "validate"} disabled={!raw.trim() || busy === "import"}>
            Validate
          </Button>
          <Button onClick={() => void doImport()} loading={busy === "import"} disabled={!valid || busy === "validate"}>
            Import
          </Button>
        </>
      }
    >
      <div className="max-h-[65vh] space-y-5 overflow-y-auto pr-1">
        <KindTiles value={kind} onChange={setKind} />
        <div className="grid gap-4 sm:grid-cols-3">
          <FormField label="How many?">{(p) => <Input {...p} type="number" min={1} max={50} value={count} onChange={(e) => setCount(e.target.value)} />}</FormField>
          <FormField label="Subject (optional)">{(p) => <Input {...p} value={subject} maxLength={120} placeholder="e.g. DBMS" onChange={(e) => setSubject(e.target.value)} />}</FormField>
          <FormField label="Topic (optional)">{(p) => <Input {...p} value={topic} maxLength={200} placeholder="e.g. normalization" onChange={(e) => setTopic(e.target.value)} />}</FormField>
        </div>
        <FormField label="Extra instructions (optional)">
          {(p) => <TextArea {...p} rows={2} maxLength={2000} value={instructions} placeholder="Difficulty, style, constraints…" onChange={(e) => setInstructions(e.target.value)} />}
        </FormField>
        <SaveToFields banks={banks} value={saveTo} onChange={setSaveTo} newName={newName} onNewName={setNewName} nameHint="Auto-named if blank" />

        <section aria-labelledby="qb-step1" className="space-y-2 rounded-lg border border-line p-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h3 id="qb-step1" className="text-sm font-semibold text-fg">
              Step 1 — copy this prompt into any chat model
            </h3>
            <Button size="sm" variant="secondary" disabled={!prompt || promptState !== "idle"} onClick={() => void copy(prompt, "Prompt")}>
              Copy prompt
            </Button>
          </div>
          <p className="text-xs text-fg-muted">Paste it into the chat model you use. Copy the JSON it returns and paste it in Step 2 below.</p>
          {promptState === "error" ? (
            <p role="alert" className="text-sm text-danger-fg">
              Couldn&apos;t build the prompt. Change an input to try again.
            </p>
          ) : (
            <pre aria-label="Generated prompt" aria-busy={promptState === "loading"} tabIndex={0} className="max-h-48 overflow-auto whitespace-pre-wrap rounded-md bg-surface-inverse p-3 font-mono text-xs text-fg-inverse">
              {prompt ?? "Building the prompt…"}
            </pre>
          )}
        </section>

        <section aria-labelledby="qb-step2" className="space-y-2 rounded-lg border border-line p-3">
          <h3 id="qb-step2" className="text-sm font-semibold text-fg">
            Step 2 — paste the model&apos;s JSON response
          </h3>
          <FormField label="Model response (JSON)">
            {(p) => (
              <TextArea
                {...p}
                rows={6}
                className="font-mono text-xs"
                value={raw}
                placeholder='[ { "question": "…", "tags": ["…"] }, … ]'
                onChange={(e) => {
                  setRaw(e.target.value);
                  setProblems(null);
                }}
              />
            )}
          </FormField>
          {problems ? <ProblemsPanel problems={problems.problems} fixPrompt={problems.fix_prompt} onCopy={() => void copy(problems.fix_prompt, "Fix request")} /> : null}
          {valid && result ? (
            <div role="status" className="rounded-lg border border-success-border bg-success-subtle p-3 text-sm text-success-fg">
              <p className="font-medium">{result.count} questions look good and are ready to import.</p>
              <ul className="mt-1 list-disc pl-5 text-fg">
                {result.items.slice(0, 5).map((it) => (
                  <li key={it.index} className="truncate">
                    {it.text}
                  </li>
                ))}
                {result.items.length > 5 ? <li>…and {result.items.length - 5} more</li> : null}
              </ul>
            </div>
          ) : null}
        </section>
        <p aria-live="polite" className="sr-only">
          {announce}
        </p>
      </div>
    </Dialog>
  );
}
