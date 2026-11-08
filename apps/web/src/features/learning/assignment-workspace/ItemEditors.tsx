"use client";

import { useEffect, useId, useRef, useState } from "react";
import { Button, ErrorState, FormField, Input, Select } from "@/components/ui";
import { RichHtml } from "@/features/assessment/components/RichHtml";
import { CodeEditor } from "@/features/coding/components/CodeEditor";
import { VerdictChip } from "@/features/coding/components/VerdictPanel";
import { codingApi, monacoLanguage, pollSubmission, RetryAfterError } from "@/features/coding/lib/api";
import type { ProblemDetail, Submission } from "@/features/coding/lib/types";
import { MAX_ASSIGNMENT_FILE_MB, uploadAssignmentFile } from "../lib/upload";
import type { ItemResponse, WorkspaceItem } from "../assignment-manager/types";

type R = Record<string, unknown>;
const strs = (v: unknown): string[] => (Array.isArray(v) ? v.filter((x): x is string => typeof x === "string") : []);
const str = (v: unknown): string => (typeof v === "string" ? v : "");

export interface ItemEditorProps {
  item: WorkspaceItem;
  response: ItemResponse | null;
  disabled?: boolean;
  onChange: (r: ItemResponse, opts?: { immediate?: boolean }) => void;
}

function ChoiceEditor({ item, response, disabled, onChange }: ItemEditorProps) {
  const name = useId();
  const multi = item.item_type === "mcq_multi";
  const chosen = strs((response as R | null)?.option_ids);
  return (
    <fieldset className="space-y-2" disabled={disabled}>
      <legend className="mb-2 text-sm font-medium text-fg">{multi ? "Choose all that apply" : "Choose one answer"}</legend>
      {item.options.map((o) => {
        const id = `${name}-${o.option_id}`;
        const checked = chosen.includes(o.option_id);
        return (
          <div key={o.option_id} className={`flex items-start gap-3 rounded-md border p-3 ${checked ? "border-line-strong bg-brand-subtle" : "border-line"}`}>
            <input
              id={id}
              type={multi ? "checkbox" : "radio"}
              name={name}
              className="mt-0.5 h-4 w-4 accent-[var(--td-brand)]"
              checked={checked}
              onChange={(e) => {
                const next = multi ? (e.target.checked ? [...chosen, o.option_id] : chosen.filter((x) => x !== o.option_id)) : [o.option_id];
                onChange({ option_ids: next });
              }}
            />
            <label htmlFor={id} className="flex flex-1 gap-2 text-sm text-fg">
              <span className="font-semibold">{o.label}.</span>
              <RichHtml html={o.html} as="span" />
            </label>
          </div>
        );
      })}
    </fieldset>
  );
}

function ValueEditor({ item, response, disabled, onChange }: ItemEditorProps) {
  return (
    <FormField label={item.item_type === "numeric" ? "Your answer (number)" : "Your answer"}>
      {(p) => (
        <Input
          {...p}
          inputMode={item.item_type === "numeric" ? "decimal" : undefined}
          value={str((response as R | null)?.value)}
          disabled={disabled}
          maxLength={500}
          onChange={(e) => onChange({ value: e.target.value })}
        />
      )}
    </FormField>
  );
}

function TextEditor({ item, response, disabled, onChange }: ItemEditorProps) {
  return (
    <FormField label="Your answer">
      {(p) => (
        <textarea
          {...p}
          rows={item.item_type === "essay" ? 14 : 4}
          maxLength={item.item_type === "essay" ? 50000 : 2000}
          disabled={disabled}
          value={str((response as R | null)?.text)}
          onChange={(e) => onChange({ text: e.target.value })}
          className="block w-full rounded-md border border-line-control bg-surface px-3 py-2 text-sm text-fg focus-visible:shadow-focus focus-visible:outline-none disabled:bg-surface-sunken"
        />
      )}
    </FormField>
  );
}

function FileEditor({ response, disabled, onChange }: ItemEditorProps) {
  const inputId = useId();
  const keys = strs((response as R | null)?.file_s3_keys);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const add = async (files: File[]) => {
    setError(null);
    if (keys.length + files.length > 5) return setError("Attach at most 5 files.");
    const big = files.find((f) => f.size > MAX_ASSIGNMENT_FILE_MB * 1024 * 1024);
    if (big) return setError(`${big.name} is larger than ${MAX_ASSIGNMENT_FILE_MB} MB.`);
    setBusy(true);
    try {
      const added: string[] = [];
      for (const f of files) added.push(await uploadAssignmentFile(f));
      onChange({ file_s3_keys: [...keys, ...added] }, { immediate: true });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Upload failed. Try again.");
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="space-y-3">
      <div>
        <label htmlFor={inputId} className="block text-sm font-medium text-fg">
          Upload files
        </label>
        <input
          id={inputId}
          type="file"
          multiple
          disabled={disabled || busy}
          aria-describedby={`${inputId}-hint`}
          onChange={(e) => {
            const list = Array.from(e.target.files ?? []);
            e.target.value = "";
            if (list.length) void add(list);
          }}
          className="mt-1 block text-sm text-fg"
        />
        <p id={`${inputId}-hint`} className="mt-1 text-xs text-fg-muted">
          Up to 5 files, {MAX_ASSIGNMENT_FILE_MB} MB each.{busy ? " Uploading…" : ""}
        </p>
      </div>
      {error ? (
        <p role="alert" className="text-sm text-danger-fg">
          {error}
        </p>
      ) : null}
      {keys.length ? (
        <ul className="space-y-1 text-sm" aria-label="Uploaded files">
          {keys.map((k) => (
            <li key={k} className="flex items-center justify-between gap-2 rounded-md border border-line p-2">
              <span className="truncate text-fg-secondary">{k.split("/").pop()}</span>
              <Button size="sm" variant="ghost" disabled={disabled} onClick={() => onChange({ file_s3_keys: keys.filter((x) => x !== k) }, { immediate: true })} aria-label={`Remove ${k.split("/").pop()}`}>
                Remove
              </Button>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

function fmtMs(ms: number | null | undefined): string | null {
  return typeof ms === "number" ? `${(ms / 1000).toFixed(3)} s` : null;
}
function fmtKb(kb: number | null | undefined): string | null {
  return typeof kb === "number" ? `${Math.round(kb / 1024)} MB` : null;
}

/** Coding item: language, editor, stdin, Run (custom input) and Run tests through the judge. */
function CodingEditor({ item, response, disabled, onChange }: ItemEditorProps) {
  const r = (response ?? {}) as R;
  const [problem, setProblem] = useState<ProblemDetail | null>(null);
  const [loadError, setLoadError] = useState<unknown>(null);
  const [stdin, setStdin] = useState("");
  const [result, setResult] = useState<Submission | null>(null);
  const [running, setRunning] = useState<"run" | "submit" | null>(null);
  const [runError, setRunError] = useState<unknown>(null);
  const abort = useRef<AbortController | null>(null);
  const lang = str(r.language_key) || problem?.languages[0]?.language_key || "";
  const code = typeof r.source_code === "string" ? r.source_code : (problem?.languages.find((l) => l.language_key === lang)?.starter_template ?? "");
  const problemId = item.coding_problem_id;

  useEffect(() => {
    if (!problemId) return;
    let live = true;
    codingApi
      .problem(problemId)
      .then((p) => {
        if (!live) return;
        setProblem(p);
        setStdin(p.samples[0]?.input ?? "");
      })
      .catch((e: unknown) => live && setLoadError(e));
    return () => {
      live = false;
      abort.current?.abort();
    };
  }, [problemId]);

  const emit = (patch: R, immediate = false) =>
    onChange({ language_key: lang, source_code: code, ...(r.submission_id ? { submission_id: r.submission_id as string } : {}), ...patch } as ItemResponse, { immediate });

  const run = async (mode: "run" | "submit") => {
    if (!problemId || !lang) return;
    abort.current?.abort();
    const ctrl = new AbortController();
    abort.current = ctrl;
    setRunning(mode);
    setRunError(null);
    setResult(null);
    try {
      const accepted =
        mode === "run"
          ? await codingApi.run(problemId, { language_key: lang, source_code: code, custom_input: stdin.trim() ? stdin : null })
          : await codingApi.submit(problemId, { language_key: lang, source_code: code });
      if (mode === "submit") emit({ submission_id: accepted.submission_id }, true);
      await pollSubmission(accepted.submission_id, setResult, { signal: ctrl.signal, maxMs: 120000 });
    } catch (e) {
      if ((e as Error).name !== "AbortError") setRunError(e);
    } finally {
      setRunning(null);
    }
  };

  if (!problemId) return <p className="text-sm text-fg-muted">This coding question has no problem attached. Ask your trainer.</p>;
  if (loadError) return <ErrorState error={loadError} />;

  const custom = result?.cases?.find((c) => c.is_custom) ?? result?.cases?.[0];
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-end gap-3">
        <div className="w-48">
          <FormField label="Language">
            {(p) => (
              <Select
                {...p}
                value={lang}
                disabled={disabled || !problem}
                onChange={(e) => {
                  const next = e.target.value;
                  const starter = problem?.languages.find((l) => l.language_key === next)?.starter_template ?? "";
                  const prevStarter = problem?.languages.find((l) => l.language_key === lang)?.starter_template ?? "";
                  onChange({ language_key: next, source_code: !code.trim() || code === prevStarter ? starter : code }, { immediate: true });
                }}
                options={(problem?.languages ?? []).map((l) => ({ value: l.language_key, label: l.display_name }))}
              />
            )}
          </FormField>
        </div>
      </div>
      <div className="h-80 overflow-hidden rounded-md border border-line sm:h-96">
        <CodeEditor value={code} language={monacoLanguage(lang)} onChange={(v) => emit({ source_code: v })} fontSize={14} theme="light" ariaLabel="Code editor" onRun={() => void run("run")} />
      </div>
      <FormField label="Input (stdin)" hint="Starts with the sample input. Programs that read input need it here.">
        {(p) => (
          <textarea
            {...p}
            rows={3}
            value={stdin}
            onChange={(e) => setStdin(e.target.value)}
            className="block w-full rounded-md border border-line-control bg-surface px-3 py-2 font-mono text-xs text-fg focus-visible:shadow-focus focus-visible:outline-none"
          />
        )}
      </FormField>
      <div className="flex flex-wrap gap-2">
        <Button variant="secondary" onClick={() => void run("run")} loading={running === "run"} disabled={disabled || running !== null || !lang}>
          Run
        </Button>
        <Button onClick={() => void run("submit")} loading={running === "submit"} disabled={disabled || running !== null || !lang}>
          Run tests
        </Button>
      </div>
      <section aria-label="Output" aria-live="polite" className="rounded-md border border-line p-3 text-sm">
        {runError ? (
          runError instanceof RetryAfterError ? (
            <p role="alert" className="text-warning-fg">
              The judge is busy. Try again in {runError.retryAfterSeconds} s.
            </p>
          ) : (
            <ErrorState error={runError} />
          )
        ) : running && (!result || result.status === "queued" || result.status === "running") ? (
          <p className="text-fg-secondary">{running === "run" ? "Running your code…" : "Running test cases…"}</p>
        ) : result ? (
          <div className="space-y-2">
            <div className="flex flex-wrap items-center gap-2 text-xs text-fg-muted">
              <VerdictChip verdict={result.verdict} />
              {result.passed_cases !== null && result.passed_cases !== undefined && result.total_cases ? (
                <span>
                  {result.passed_cases}/{result.total_cases} tests passed
                </span>
              ) : null}
              {fmtMs(result.max_time_ms) ? <span>Time {fmtMs(result.max_time_ms)}</span> : null}
              {fmtKb(result.max_memory_kb) ? <span>Memory {fmtKb(result.max_memory_kb)}</span> : null}
            </div>
            {result.compile_output ? <pre className="max-h-40 overflow-auto rounded bg-surface-sunken p-2 font-mono text-xs">{result.compile_output}</pre> : null}
            {result.mode === "run" && custom?.stdout_excerpt !== undefined ? (
              <pre aria-label="Program output" className="max-h-40 overflow-auto rounded bg-surface-sunken p-2 font-mono text-xs">
                {custom.stdout_excerpt ?? ""}
              </pre>
            ) : null}
          </div>
        ) : (
          <p className="text-fg-muted">Run your code with the input above, or run the test cases.</p>
        )}
      </section>
    </div>
  );
}

/** Answer editor for one workspace item, by item type. */
export function ItemEditor(props: ItemEditorProps) {
  switch (props.item.item_type) {
    case "mcq_single":
    case "mcq_multi":
      return <ChoiceEditor {...props} />;
    case "numeric":
    case "fill_blank":
      return <ValueEditor {...props} />;
    case "essay":
    case "short_text":
      return <TextEditor {...props} />;
    case "file":
      return <FileEditor {...props} />;
    case "coding":
      return <CodingEditor {...props} />;
    default:
      return <TextEditor {...props} />;
  }
}
