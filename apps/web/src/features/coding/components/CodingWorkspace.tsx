"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState, type KeyboardEvent } from "react";
import { Badge, Button, Dialog, ErrorState, Select, Skeleton, Tabs } from "@/components/ui";
import { useActivityTracker, type ActivityTrackerHandle } from "@/lib/analytics/use-activity-tracker";
import { isApiError } from "@/lib/api/errors";
import { uuid7 } from "@/lib/ids/uuid7";
import { codingApi, difficultyLabel, monacoLanguage, pollSubmission, RetryAfterError } from "../lib/api";
import type { Language, ProblemDetail, Submission } from "../lib/types";
import { CodeEditor } from "./CodeEditor";
import { VerdictPanel } from "./VerdictPanel";

const LANG_PREF = "td.coding.lang";
export const CODING_ROUTE = "/app/coding/[slug]";
const FONT_SIZES = [12, 14, 16, 18, 20];
const DEFAULT_SPLIT = 40;
/** COD-04 autosave cadence: at most one save per 5 s of editing (server limit 20/min). */
const DRAFT_DEBOUNCE_MS = 5000;

type DraftState = "idle" | "loading" | "pending" | "saving" | "saved" | "error";

const DRAFT_LABEL: Record<DraftState, string> = {
  idle: "",
  loading: "Loading your saved draft…",
  pending: "Unsaved changes",
  saving: "Saving draft…",
  saved: "Draft saved",
  error: "Draft not saved — we'll retry when you keep typing",
};

function useNow(active: boolean): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!active) return;
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, [active]);
  return now;
}

const mmss = (ms: number) => {
  const s = Math.max(0, Math.ceil(ms / 1000));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
};

export interface CodingWorkspaceProps {
  slug: string;
  /** Inside a timed test (COD-004): submissions count for the attempt. */
  attemptId?: string;
  embedded?: boolean;
  onSubmitted?: (submissionId: string) => void;
  /** Embedded use: the host page's tracker (e.g. the test attempt). Standalone mounts its own. */
  tracker?: ActivityTrackerHandle;
}

/** COD-002 coding workspace (COD-03..08). */
export function CodingWorkspace({ slug, attemptId, embedded = false, onSubmitted, tracker: hostTracker }: CodingWorkspaceProps) {
  const [problem, setProblem] = useState<ProblemDetail | null>(null);
  const [languages, setLanguages] = useState<Language[]>([]);
  const [loadError, setLoadError] = useState<unknown>(null);
  const [lang, setLang] = useState<string | null>(null);
  const [code, setCode] = useState("");
  const [fontSize, setFontSize] = useState(14);
  const [theme, setTheme] = useState<"light" | "dark">("light");
  const [split, setSplit] = useState(DEFAULT_SPLIT);
  const [customInput, setCustomInput] = useState("");
  const [busy, setBusy] = useState<"run" | "submit" | null>(null);
  const [submission, setSubmission] = useState<Submission | null>(null);
  const [startedAt, setStartedAt] = useState<number | null>(null);
  const [actionError, setActionError] = useState<unknown>(null);
  const [blockedUntil, setBlockedUntil] = useState<{ run: number; submit: number }>({ run: 0, submit: 0 });
  const [resultsTab, setResultsTab] = useState("testcases");
  const [resetOpen, setResetOpen] = useState(false);
  // Each language's code this visit (so switching languages keeps it); persisted via COD-04/05.
  const drafts = useRef(new Map<string, string>());
  const dirty = useRef(new Set<string>());
  const saveTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [draftState, setDraftState] = useState<DraftState>("idle");
  const abort = useRef<AbortController | null>(null);
  const now = useNow(blockedUntil.run > Date.now() || blockedUntil.submit > Date.now());

  const load = useCallback(async () => {
    setLoadError(null);
    try {
      const [p, langs] = await Promise.all([codingApi.problem(slug, attemptId), codingApi.languages()]);
      setProblem(p);
      const allowed = langs.filter((l) => p.allowed_languages.includes(l.language_key));
      setLanguages(allowed.length ? allowed : p.languages);
      let pref: string | null = null;
      try {
        pref = window.localStorage.getItem(LANG_PREF);
      } catch {
        pref = null;
      }
      setLang(pref && p.allowed_languages.includes(pref) ? pref : (p.allowed_languages[0] ?? null));
    } catch (e) {
      setLoadError(e);
    }
  }, [slug, attemptId]);

  useEffect(() => {
    void load();
    return () => abort.current?.abort();
  }, [load]);

  const starter = useCallback(
    (l: string) => problem?.languages.find((x) => x.language_key === l)?.starter_template ?? languages.find((x) => x.language_key === l)?.starter_template ?? "",
    [problem, languages],
  );

  const problemId = problem?.problem_id ?? null;

  // FE-07: coding is a learning surface (M5). Embedded in a test, the attempt's tracker is used.
  const ownTracker = useActivityTracker({
    route: CODING_ROUTE,
    surface: "coding",
    entity: { coding_problem_id: problemId ?? undefined },
    enabled: !hostTracker && !embedded && Boolean(problemId),
  });
  const tracker = hostTracker ?? ownTracker;

  /** COD-04: save one language's draft if it changed since the last save. */
  const flushDraft = useCallback(
    async (l: string) => {
      if (!problemId || !dirty.current.has(l)) return;
      const source = drafts.current.get(l);
      if (source === undefined) return;
      dirty.current.delete(l);
      setDraftState("saving");
      try {
        await codingApi.saveDraft(problemId, l, source, attemptId);
        setDraftState(dirty.current.size ? "pending" : "saved");
      } catch {
        dirty.current.add(l);
        setDraftState("error");
      }
    },
    [problemId, attemptId],
  );

  // Restore this visit's code for the language; else the saved draft (COD-05); else the starter.
  useEffect(() => {
    if (!problem || !lang) return;
    const local = drafts.current.get(lang);
    if (local !== undefined) {
      setCode(local);
      return;
    }
    setCode(starter(lang));
    let cancelled = false;
    setDraftState("loading");
    codingApi
      .getDraft(problem.problem_id, lang, attemptId)
      .then((d) => {
        if (cancelled) return;
        // The student may have typed while the draft loaded: their edits win.
        if (d && !drafts.current.has(lang)) {
          drafts.current.set(lang, d.source_code);
          setCode(d.source_code);
          setDraftState("saved");
        } else {
          setDraftState("idle");
        }
      })
      .catch(() => {
        if (!cancelled) setDraftState("idle");
      });
    return () => {
      cancelled = true;
    };
  }, [problem, lang, starter, attemptId]);

  // Debounced autosave; flush pending saves when the language changes or the workspace unmounts.
  useEffect(() => {
    if (!lang) return;
    return () => {
      if (saveTimer.current) clearTimeout(saveTimer.current);
      saveTimer.current = null;
      void flushDraft(lang);
    };
  }, [lang, flushDraft]);

  const onCodeChange = (l: string, v: string) => {
    tracker.editor.edit();
    setCode(v);
    drafts.current.set(l, v);
    dirty.current.add(l);
    setDraftState("pending");
    if (saveTimer.current) clearTimeout(saveTimer.current);
    saveTimer.current = setTimeout(() => {
      saveTimer.current = null;
      void flushDraft(l);
    }, DRAFT_DEBOUNCE_MS);
  };

  const execute = async (mode: "run" | "submit") => {
    if (!problem || !lang || busy) return;
    if (blockedUntil[mode] > Date.now()) return;
    setBusy(mode);
    setActionError(null);
    setResultsTab("results");
    abort.current?.abort();
    const ctrl = new AbortController();
    abort.current = ctrl;
    const key = uuid7();
    try {
      const accepted =
        mode === "run"
          ? await codingApi.run(problem.problem_id, { language_key: lang, source_code: code, custom_input: customInput.trim() ? customInput : null, attempt_id: attemptId ?? null }, key)
          : await codingApi.submit(problem.problem_id, { language_key: lang, source_code: code, attempt_id: attemptId ?? null }, key);
      if (mode === "submit") onSubmitted?.(accepted.submission_id);
      setStartedAt(Date.now());
      setSubmission({ submission_id: accepted.submission_id, mode, status: accepted.status, queue_position: accepted.queue_position });
      await pollSubmission(accepted.submission_id, setSubmission, { signal: ctrl.signal });
    } catch (e) {
      if ((e as Error).name === "AbortError") return;
      if (e instanceof RetryAfterError) {
        setBlockedUntil((b) => ({ ...b, [mode]: Date.now() + e.retryAfterSeconds * 1000 }));
      } else if (isApiError(e) && e.code === "submission_in_flight" && typeof e.problem?.submission_id === "string") {
        setStartedAt(Date.now());
        await pollSubmission(e.problem.submission_id, setSubmission, { signal: ctrl.signal }).catch(() => undefined);
      } else {
        setActionError(e);
      }
    } finally {
      setBusy(null);
    }
  };

  const runRef = useRef(execute);
  runRef.current = execute;
  const editorRun = useCallback(() => void runRef.current("run"), []);
  const editorSubmit = useCallback(() => void runRef.current("submit"), []);

  const onSplitKey = (e: KeyboardEvent<HTMLDivElement>) => {
    if (e.key === "ArrowLeft") setSplit((s) => Math.max(20, s - 5));
    else if (e.key === "ArrowRight") setSplit((s) => Math.min(70, s + 5));
    else if (e.key === "Home") setSplit(DEFAULT_SPLIT);
    else return;
    e.preventDefault();
  };

  const langOptions = useMemo(
    () => languages.map((l) => ({ value: l.language_key, label: "version" in l && l.version ? `${l.display_name} ${l.version}` : l.display_name })),
    [languages],
  );

  if (loadError) {
    if (isApiError(loadError) && loadError.code === "entitlement_required") {
      return (
        <div className="rounded-xl border border-line bg-surface p-6">
          <p className="font-semibold">This problem is part of a paid plan</p>
          <p className="mt-1 text-sm text-fg-muted">{loadError.detail}</p>
          <Link className="mt-3 inline-block text-sm text-fg-link underline" href="/pricing">
            See plans
          </Link>
        </div>
      );
    }
    return <ErrorState error={loadError} onRetry={() => void load()} />;
  }
  if (!problem || !lang)
    return (
      <div aria-busy="true" className="space-y-3">
        <Skeleton className="h-8 w-1/2" />
        <Skeleton className="h-96 w-full" />
      </div>
    );

  const runBlocked = blockedUntil.run > now;
  const submitBlocked = blockedUntil.submit > now;

  const statement = (
    <div className="space-y-4 text-sm leading-relaxed text-fg">
      {/* Problem text is Markdown (statement_md etc.); shown as plain text. */}
      <p className="whitespace-pre-wrap">{problem.statement_md}</p>
      {problem.input_format_md ? (
        <section>
          <h3 className="font-semibold">Input format</h3>
          <p className="whitespace-pre-wrap">{problem.input_format_md}</p>
        </section>
      ) : null}
      {problem.output_format_md ? (
        <section>
          <h3 className="font-semibold">Output format</h3>
          <p className="whitespace-pre-wrap">{problem.output_format_md}</p>
        </section>
      ) : null}
      {problem.constraints_md ? (
        <section>
          <h3 className="font-semibold">Constraints</h3>
          <p className="whitespace-pre-wrap">{problem.constraints_md}</p>
        </section>
      ) : null}
      {problem.samples.map((s) => (
        <section key={s.ordinal}>
          <h3 className="font-semibold">Sample {s.ordinal}</h3>
          <div className="mt-1 grid gap-2 sm:grid-cols-2">
            <pre className="overflow-auto rounded bg-surface-sunken p-2 font-mono text-xs" aria-label={`Sample ${s.ordinal} input`}>
              {s.input}
            </pre>
            <pre className="overflow-auto rounded bg-surface-sunken p-2 font-mono text-xs" aria-label={`Sample ${s.ordinal} output`}>
              {s.expected_output}
            </pre>
          </div>
        </section>
      ))}
      <p className="text-xs text-fg-muted">
        Limits: {problem.limits.time_limit_ms / 1000} s · {Math.round(problem.limits.memory_limit_kb / 1024)} MB
      </p>
      {!embedded ? (
        <Link className="text-xs text-fg-link underline" href={`/app/coding/${encodeURIComponent(problem.slug)}/submissions`}>
          My submissions
        </Link>
      ) : null}
    </div>
  );

  return (
    <div className={embedded ? "" : "-mx-4 lg:-mx-8"}>
      {!embedded ? (
        <header className="flex flex-wrap items-center gap-3 border-b border-line bg-surface px-4 py-2">
          <Link href="/app/coding" className="text-sm text-fg-link underline">
            ← Problems
          </Link>
          <h1 className="font-display text-base font-semibold">{problem.title}</h1>
          <Badge>{difficultyLabel(problem.difficulty)}</Badge>
        </header>
      ) : null}

      {/* < 768 px: readable statement + notice (design-system §5.12) */}
      <div className="p-4 md:hidden">
        <p role="note" className="mb-4 border-l-4 border-info-border bg-info-subtle p-3 text-sm text-info-fg">
          The coding workspace needs a larger screen (tablet or laptop). You can read the problem here.
        </p>
        {statement}
      </div>

      <div className="hidden md:flex md:h-[calc(100dvh-10rem)] md:min-h-[32rem]">
        <section aria-label="Problem statement" className="overflow-y-auto border-r border-line bg-surface p-4" style={{ width: `${split}%` }}>
          {statement}
        </section>
        <div
          role="separator"
          aria-orientation="vertical"
          aria-label="Resize statement and editor (arrow keys; Home resets)"
          aria-valuemin={20}
          aria-valuemax={70}
          aria-valuenow={split}
          tabIndex={0}
          onKeyDown={onSplitKey}
          className="w-2 cursor-col-resize bg-line hover:bg-line-strong focus-visible:shadow-focus focus-visible:outline-none"
        />
        <div className="flex min-w-0 flex-1 flex-col">
          <div className="flex flex-wrap items-center gap-2 border-b border-line bg-surface px-3 py-2">
            <label className="sr-only" htmlFor="lang-select">
              Language
            </label>
            <Select
              id="lang-select"
              className="h-8 w-auto"
              options={langOptions}
              value={lang}
              onChange={(e) => {
                setLang(e.target.value);
                try {
                  window.localStorage.setItem(LANG_PREF, e.target.value);
                } catch {
                  /* ignore */
                }
              }}
            />
            <label className="sr-only" htmlFor="font-size">
              Font size
            </label>
            <Select id="font-size" className="h-8 w-auto" options={FONT_SIZES.map((f) => ({ value: String(f), label: `Aa ${f}` }))} value={String(fontSize)} onChange={(e) => setFontSize(Number(e.target.value))} />
            <Button size="sm" variant="ghost" onClick={() => setTheme((t) => (t === "light" ? "dark" : "light"))} aria-pressed={theme === "dark"}>
              ◐ Dark editor
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setResetOpen(true)}>
              ⟲ Reset
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setSplit(DEFAULT_SPLIT)}>
              Reset layout
            </Button>
            <span className="ml-auto text-xs text-fg-muted" role="status" aria-live="polite">
              {DRAFT_LABEL[draftState]}
            </span>
          </div>
          <div className="min-h-0 flex-1">
            <CodeEditor
              value={code}
              language={monacoLanguage(lang)}
              onChange={(v) => onCodeChange(lang, v)}
              fontSize={fontSize}
              theme={theme}
              ariaLabel={`Code editor, ${lang}`}
              onRun={editorRun}
              onSubmit={editorSubmit}
              onFocus={() => tracker.editor.focus(lang)}
              onBlur={() => tracker.editor.blur(lang)}
            />
          </div>
          <div className="max-h-[45%] overflow-y-auto border-t border-line bg-surface p-3">
            <Tabs
              label="Results panel"
              value={resultsTab}
              onValueChange={setResultsTab}
              items={[
                {
                  id: "testcases",
                  label: "Testcases",
                  content: <p className="text-sm text-fg-secondary">Run uses the {problem.samples.length} sample case{problem.samples.length === 1 ? "" : "s"} shown in the statement, plus your custom input.</p>,
                },
                {
                  id: "custom",
                  label: "Custom input",
                  content: (
                    <textarea
                      aria-label="Custom input"
                      value={customInput}
                      onChange={(e) => setCustomInput(e.target.value)}
                      className="h-24 w-full rounded-md border border-line-control bg-surface-sunken p-2 font-mono text-xs focus-visible:shadow-focus focus-visible:outline-none"
                    />
                  ),
                },
                { id: "results", label: "Results", content: <VerdictPanel submission={submission} startedAt={startedAt} /> },
              ]}
            />
            {actionError ? <div className="mt-2"><ErrorState error={actionError} /></div> : null}
            <div className="mt-3 flex flex-wrap items-center justify-end gap-2">
              {runBlocked ? <span className="text-xs text-fg-secondary" role="status">You can run again in {mmss(blockedUntil.run - now)}</span> : null}
              {submitBlocked ? <span className="text-xs text-fg-secondary" role="status">You can submit again in {mmss(blockedUntil.submit - now)}</span> : null}
              {attemptId ? <span className="text-xs text-fg-muted">Your last submission counts for this test.</span> : null}
              <Button variant="secondary" loading={busy !== null} disabled={runBlocked} onClick={() => void execute("run")} aria-keyshortcuts="Control+Enter">
                Run <span className="text-xs text-fg-muted">Ctrl+Enter</span>
              </Button>
              <Button loading={busy !== null} disabled={submitBlocked || busy !== null} onClick={() => void execute("submit")} aria-keyshortcuts="Control+Shift+Enter">
                Submit <span className="text-xs opacity-80">Ctrl+Shift+Enter</span>
              </Button>
            </div>
          </div>
        </div>
      </div>

      <Dialog
        open={resetOpen}
        onClose={() => setResetOpen(false)}
        title="Reset to the starter code?"
        description={`This replaces your ${lang} code in the editor. Your past submissions are kept.`}
        footer={
          <>
            <Button variant="secondary" onClick={() => setResetOpen(false)}>
              Keep my code
            </Button>
            <Button
              variant="danger"
              onClick={() => {
                onCodeChange(lang, starter(lang));
                setResetOpen(false);
              }}
            >
              Reset code
            </Button>
          </>
        }
      />
    </div>
  );
}
