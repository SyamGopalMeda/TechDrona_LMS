"use client";

import { useEffect, useState } from "react";
import { Button, Checkbox, Dialog, FormField, Input, Select, useToast } from "@/components/ui";
import { api } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import { AIErrorState, aiProblemCode } from "@/features/ai";
import { TextArea, useFailToast } from "@/features/trainer/shared/ui";
import { cn } from "@/lib/ui/cn";
import { KINDS } from "../lib/labels";
import type { GenerateDifficulty, GenerateMode, GenerateResult, ImportKind, ImportResult } from "../lib/types";
import { problemsOf } from "./BulkImportDialog";
import { KindTiles, NEW_BANK, ProblemsPanel, SaveToFields, TagChips, useBankOptions } from "./parts";

export interface GenerateDialogProps {
  open: boolean;
  onClose: () => void;
  defaultBankId?: string | null;
  onSaved: (result: ImportResult) => void;
}

const MODES: { value: GenerateMode; label: string; field: string; placeholder: string; key: "topic" | "company" | "subject" }[] = [
  { value: "topic", label: "On a topic", field: "Topic", placeholder: "Binary search trees", key: "topic" },
  { value: "company", label: "For a company", field: "Company", placeholder: "e.g. Infosys", key: "company" },
  { value: "subject", label: "On a subject", field: "Subject", placeholder: "e.g. Operating systems", key: "subject" },
  { value: "test", label: "Specific test", field: "Test or exam", placeholder: "e.g. TCS NQT aptitude", key: "topic" },
];

const DIFFICULTIES: { value: GenerateDifficulty; label: string }[] = [
  { value: "easy", label: "Easy" },
  { value: "medium", label: "Medium" },
  { value: "hard", label: "Hard" },
  { value: "mixed", label: "Mixed" },
];

/**
 * "Generate with AI": the server drafts questions through the AI service; the author reviews
 * them, picks which to keep and saves them to a bank as drafts (they still go through review).
 */
export function GenerateDialog({ open, onClose, defaultBankId, onSaved }: GenerateDialogProps) {
  const toast = useToast();
  const fail = useFailToast();
  const banks = useBankOptions(open);
  const [mode, setMode] = useState<GenerateMode>("topic");
  const [primary, setPrimary] = useState("");
  const [secondary, setSecondary] = useState("");
  const [instructions, setInstructions] = useState("");
  const [kind, setKind] = useState<ImportKind>("mcq");
  const [count, setCount] = useState("5");
  const [difficulty, setDifficulty] = useState<GenerateDifficulty>("mixed");
  const [saveTo, setSaveTo] = useState(defaultBankId ?? NEW_BANK);
  const [newName, setNewName] = useState("");
  const [busy, setBusy] = useState<"generate" | "save" | null>(null);
  const [aiError, setAiError] = useState<{ code: string; detail: string | null } | null>(null);
  const [result, setResult] = useState<(GenerateResult & { kind: ImportKind }) | null>(null);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [saveProblems, setSaveProblems] = useState<ReturnType<typeof problemsOf>>(null);

  useEffect(() => {
    if (open) {
      setSaveTo(defaultBankId ?? NEW_BANK);
      setResult(null);
      setAiError(null);
      setSaveProblems(null);
    }
  }, [open, defaultBankId]);

  const m = MODES.find((x) => x.value === mode)!;
  const n = Math.min(50, Math.max(1, Math.round(Number(count)) || 5));
  // Secondary (optional) topic for company/subject modes.
  const showSecondary = mode === "company" || mode === "subject";

  const generate = async () => {
    if (!primary.trim()) return;
    setBusy("generate");
    setAiError(null);
    try {
      const body: Record<string, unknown> = { source_mode: mode, question_type: kind, count: n, difficulty, instructions: instructions.trim() || undefined };
      body[m.key] = primary.trim();
      if (showSecondary && secondary.trim()) body.topic = secondary.trim();
      const res = await api.post<GenerateResult>("studio/question-banks/generate", body);
      if (res.kind === "ok") {
        setResult({ ...res.data, kind });
        setSelected(new Set(res.data.drafts.map((_, i) => i)));
        setSaveProblems(null);
      }
    } catch (err) {
      const code = aiProblemCode(err);
      if (code) setAiError({ code, detail: err instanceof ApiError ? err.detail : null });
      else fail(err, "Couldn't generate questions");
    } finally {
      setBusy(null);
    }
  };

  const save = async () => {
    if (!result || !selected.size) return;
    setBusy("save");
    try {
      const items = result.drafts.filter((_, i) => selected.has(i));
      const subject = mode === "subject" ? primary.trim() : undefined;
      const topic = mode === "topic" || mode === "test" ? primary.trim() : secondary.trim() || undefined;
      const res = await api.post<ImportResult>(
        "studio/question-banks/import",
        {
          question_type: result.kind,
          items,
          ...(saveTo === NEW_BANK ? { new_bank_name: newName.trim() || undefined } : { bank_id: saveTo }),
          subject,
          topic,
          source: "ai",
        },
        { idempotencyKey: true },
      );
      if (res.kind === "ok") {
        toast.show({ tone: "success", title: "AI questions saved to your bank.", description: `${res.data.count} drafts added to ${res.data.bank.name}. Review them before use.` });
        onSaved(res.data);
      }
    } catch (err) {
      const p = problemsOf(err);
      if (p) setSaveProblems(p);
      else fail(err, "Couldn't save the questions");
    } finally {
      setBusy(null);
    }
  };

  const toggle = (i: number) =>
    setSelected((s) => {
      const next = new Set(s);
      if (next.has(i)) next.delete(i);
      else next.add(i);
      return next;
    });

  const reviewing = result !== null;
  const kindLabel = KINDS.find((k) => k.value === (result?.kind ?? kind))?.label ?? "";

  return (
    <Dialog
      open={open}
      onClose={onClose}
      dismissible={busy === null}
      className="max-w-3xl"
      title="Generate with AI"
      description="Tech Drona drafts questions for you to review. Saved questions are drafts — they need review before learners see them."
      footer={
        reviewing ? (
          <>
            <Button variant="secondary" onClick={() => setResult(null)} disabled={busy !== null}>
              Back
            </Button>
            <Button onClick={() => void save()} loading={busy === "save"} disabled={!selected.size}>
              Save {selected.size} to bank
            </Button>
          </>
        ) : (
          <>
            <Button variant="secondary" onClick={onClose} disabled={busy !== null}>
              Cancel
            </Button>
            <Button onClick={() => void generate()} loading={busy === "generate"} disabled={!primary.trim()}>
              Generate
            </Button>
          </>
        )
      }
    >
      {reviewing && result ? (
        <div className="max-h-[65vh] space-y-3 overflow-y-auto pr-1">
          <div className="flex flex-wrap items-center gap-3 text-sm">
            <p aria-live="polite" className="font-medium text-fg">
              {result.drafts.length} drafted · {selected.size} selected
            </p>
            <Button size="sm" variant="ghost" onClick={() => setSelected(new Set())} disabled={!selected.size}>
              Clear
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setSelected(new Set(result.drafts.map((_, i) => i)))} disabled={selected.size === result.drafts.length}>
              Select all
            </Button>
          </div>
          {result.problems?.length ? <p className="text-xs text-fg-muted">Some drafts had problems and were left out ({result.problems.length}).</p> : null}
          {saveProblems ? <ProblemsPanel problems={saveProblems.problems} fixPrompt={null} onCopy={() => undefined} /> : null}
          {!result.drafts.length ? <p className="text-sm text-fg-muted">No drafts came back. Go back and adjust the instructions.</p> : null}
          <ul className="space-y-2">
            {result.drafts.map((_, i) => {
              const p = result.previews[i];
              const text = p?.text ?? `Draft ${i + 1}`;
              return (
                <li key={i} className={cn("rounded-lg border p-3", selected.has(i) ? "border-brand" : "border-line")}>
                  <div className="flex items-start gap-3">
                    <span aria-hidden="true" className="mt-0.5 rounded bg-surface-sunken px-1.5 font-mono text-xs">
                      {KINDS.find((k) => k.value === result.kind)?.icon}
                    </span>
                    <div className="min-w-0 flex-1 space-y-1.5">
                      <p className="whitespace-pre-wrap text-sm text-fg">{text}</p>
                      {p?.options?.length ? (
                        <p className="text-xs text-fg-secondary">
                          {p.options.map((o, j) => (
                            <span key={j}>
                              {j > 0 ? " · " : ""}
                              <span className={o.correct ? "font-semibold text-success-fg" : undefined}>
                                {o.text}
                                {o.correct ? " ✓" : ""}
                              </span>
                            </span>
                          ))}
                        </p>
                      ) : null}
                      {p && (p.sample_cases || p.hidden_cases) ? (
                        <p className="text-xs text-fg-muted">
                          {p.sample_cases} sample · {p.hidden_cases} hidden test cases
                        </p>
                      ) : null}
                      <TagChips tags={p?.tags ?? []} />
                    </div>
                    <Checkbox label={<span className="sr-only">Keep draft {i + 1}</span>} checked={selected.has(i)} onChange={() => toggle(i)} />
                  </div>
                </li>
              );
            })}
          </ul>
          <p className="text-xs text-fg-muted">
            {kindLabel} drafts are saved as draft questions. Check each one, add an explanation where needed and submit it for review before using it with learners.
          </p>
        </div>
      ) : (
        <div className="max-h-[65vh] space-y-5 overflow-y-auto pr-1">
          <div role="radiogroup" aria-label="Generate from" className="flex flex-wrap gap-2">
            {MODES.map((x) => (
              <button
                key={x.value}
                type="button"
                role="radio"
                aria-checked={mode === x.value}
                onClick={() => setMode(x.value)}
                className={cn(
                  "rounded-full border px-3 py-1 text-sm focus-visible:shadow-focus focus-visible:outline-none",
                  mode === x.value ? "border-brand bg-brand-subtle font-medium text-brand-on-subtle" : "border-line bg-surface text-fg-secondary hover:bg-surface-hover",
                )}
              >
                {x.label}
              </button>
            ))}
          </div>
          <div className="grid gap-4 sm:grid-cols-2">
            <FormField label={m.field} required>
              {(p) => <Input {...p} value={primary} maxLength={200} placeholder={m.placeholder} onChange={(e) => setPrimary(e.target.value)} />}
            </FormField>
            {showSecondary ? (
              <FormField label="Topic (optional)">{(p) => <Input {...p} value={secondary} maxLength={200} placeholder="e.g. arrays" onChange={(e) => setSecondary(e.target.value)} />}</FormField>
            ) : null}
          </div>
          <FormField label="General instructions">
            {(p) => <TextArea {...p} rows={2} maxLength={2000} value={instructions} placeholder="Difficulty, sub-topics, style…" onChange={(e) => setInstructions(e.target.value)} />}
          </FormField>
          <KindTiles value={kind} onChange={setKind} />
          <div className="grid gap-4 sm:grid-cols-2">
            <FormField label="How many?">{(p) => <Input {...p} type="number" min={1} max={50} value={count} onChange={(e) => setCount(e.target.value)} />}</FormField>
            <FormField label="Difficulty">
              {(p) => <Select {...p} value={difficulty} onChange={(e) => setDifficulty(e.target.value as GenerateDifficulty)} options={DIFFICULTIES} />}
            </FormField>
          </div>
          <SaveToFields banks={banks} value={saveTo} onChange={setSaveTo} newName={newName} onNewName={setNewName} />
          {aiError ? <AIErrorState code={aiError.code} detail={aiError.detail} onRetry={() => void generate()} /> : null}
        </div>
      )}
    </Dialog>
  );
}
