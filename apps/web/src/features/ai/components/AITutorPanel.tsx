"use client";

import { useEffect, useId, useRef, useState } from "react";
import { Button, ErrorState } from "@/components/ui";
import { ApiError } from "@/lib/api/errors";
import { cn } from "@/lib/ui/cn";
import type { AITutorMode, AITutorReply } from "../types";
import { AIErrorState, aiProblemCode } from "./AIErrorState";
import { AiNotIntegratedNotice } from "@/features/studio/components/NotIntegrated";

export interface AITutorPanelProps {
  /** Tutor interactions already used for this activity. */
  used: number;
  /** Cap for this activity; null = unlimited. */
  limit: number | null;
  /** Disable asking entirely (e.g. AI off for the org, or the activity is submitted). */
  disabled?: boolean;
  /** Sends ONE question; the server keeps the conversation (SEC-17), so no history is sent. */
  onAsk: (mode: AITutorMode, input: string) => Promise<AITutorReply>;
  /**
   * Loads earlier turns from the server (e.g. `GET me/assignments/{id}/tutor/history?item_id=`).
   * Re-run whenever `historyKey` changes (e.g. the learner moves to another question).
   */
  loadHistory?: () => Promise<TutorHistoryTurn[]>;
  historyKey?: string;
  title?: string;
}

/** One stored turn (`{role, content, created_at}`), oldest first. */
export interface TutorHistoryTurn {
  role: string;
  content: string;
  created_at?: string;
}

interface Exchange {
  id: string;
  /** Unknown for turns loaded from the server. */
  mode: AITutorMode | null;
  question: string;
  reply: string;
}

/** Pure: pair stored learner/tutor turns into exchanges (a learner turn without a reply is skipped). */
export function pairTurns(turns: TutorHistoryTurn[]): Exchange[] {
  const out: Exchange[] = [];
  let question: string | null = null;
  turns.forEach((t, i) => {
    if (t.role === "learner") question = t.content;
    else if (t.role === "tutor") {
      out.push({ id: `h${i}`, mode: null, question: question ?? "", reply: t.content });
      question = null;
    }
  });
  return out;
}

const MODE_LABEL: Record<AITutorMode, string> = { guide: "Guide", explain: "Explain" };

/**
 * Learner-facing AI tutor. Replies are markdown but rendered as pre-wrapped plain text
 * (never dangerouslySetInnerHTML), so model output can't inject markup.
 */
export function AITutorPanel({ used: usedProp, limit: limitProp, disabled = false, onAsk, loadHistory, historyKey, title = "AI tutor" }: AITutorPanelProps) {
  const headingId = useId();
  const inputId = useId();
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState<AITutorMode | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [lastMode, setLastMode] = useState<AITutorMode>("guide");
  const [history, setHistory] = useState<Exchange[]>([]);
  const [historyError, setHistoryError] = useState(false);
  // loadHistory is usually an inline closure; reload only when the conversation (historyKey) changes.
  const loadRef = useRef(loadHistory);
  loadRef.current = loadHistory;

  useEffect(() => {
    setHistory([]);
    setHistoryError(false);
    const load = loadRef.current;
    if (!load) return;
    let live = true;
    load()
      .then((turns) => live && setHistory(pairTurns(turns)))
      .catch(() => live && setHistoryError(true));
    return () => {
      live = false;
    };
  }, [historyKey]);
  // The server's counter wins once we have a reply; until then, trust the props.
  const [server, setServer] = useState<{ used: number; limit: number | null } | null>(null);
  const used = server?.used ?? usedProp;
  const limit = server ? server.limit : limitProp;

  const remaining = limit === null ? null : Math.max(0, limit - used);
  const exhausted = remaining !== null && remaining <= 0;
  const aiCode = aiProblemCode(error);
  const blocked = disabled || exhausted || aiCode === "ai_disabled" || aiCode === "ai_quota_exceeded";
  // 429 rate_limited (SEC-05 per-user rate limit): a short wait, not a dead end.
  const rateLimited = error instanceof ApiError && error.status === 429 && error.code === "rate_limited";

  const ask = async (mode: AITutorMode) => {
    const text = input.trim();
    if (!text || blocked || busy) return;
    setBusy(mode);
    setLastMode(mode);
    setError(null);
    try {
      const res = await onAsk(mode, text);
      setServer({ used: res.used, limit: res.limit });
      setHistory((h) => [...h, { id: `n${h.length + 1}`, mode, question: text, reply: res.reply_md }]);
      setInput("");
    } catch (err) {
      setError(err);
    } finally {
      setBusy(null);
    }
  };

  const label = (mode: AITutorMode) => (remaining === null ? MODE_LABEL[mode] : `${MODE_LABEL[mode]} (${remaining})`);

  return (
    <section aria-labelledby={headingId} className="rounded-xl border border-line bg-surface p-4">
      <header className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 id={headingId} className="font-display text-base font-semibold text-fg">
          {title}
        </h2>
        <p className="text-xs text-fg-muted" aria-live="polite" data-testid="ai-tutor-counter">
          {limit === null ? "Unlimited" : `${Math.min(used, limit)} of ${limit} used`}
        </p>
      </header>
      <AiNotIntegratedNotice className="mt-2" />
      <p className="mt-1 text-sm text-fg-secondary">Stuck? Ask me to guide you or explain a concept — I won&apos;t hand over the full answer.</p>

      {history.length ? (
        <ol className="mt-3 space-y-3" aria-label="Tutor replies">
          {history.map((x) => (
            <li key={x.id} className="rounded-lg border border-line bg-surface-sunken p-3 text-sm">
              <p className="text-xs font-semibold uppercase tracking-wide text-fg-muted">
                {x.mode ? `${MODE_LABEL[x.mode]} · ` : null}
                <span className="normal-case">{x.question.length > 80 ? `${x.question.slice(0, 80)}…` : x.question}</span>
              </p>
              <div className="mt-1 whitespace-pre-wrap break-words text-fg">{x.reply}</div>
            </li>
          ))}
        </ol>
      ) : null}

      <div className="mt-3 space-y-1.5">
        <label htmlFor={inputId} className="block text-sm font-medium text-fg">
          Your question or code
        </label>
        <textarea
          id={inputId}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          disabled={blocked}
          maxLength={8000}
          placeholder="Describe where you're stuck, or paste the relevant code"
          className={cn(
            "block min-h-[6rem] w-full rounded-md border border-line-control bg-surface px-3 py-2 font-mono text-sm text-fg placeholder:font-sans placeholder:text-fg-muted",
            "focus-visible:shadow-focus focus-visible:outline-none disabled:cursor-not-allowed disabled:bg-surface-sunken",
          )}
        />
      </div>

      {exhausted ? (
        <p role="status" className="mt-2 text-sm text-fg-secondary">
          You&apos;ve used all your tutor interactions for this activity. Keep going with run &amp; test.
        </p>
      ) : null}

      {historyError ? (
        <p className="mt-3 text-xs text-fg-muted">Earlier replies couldn&apos;t be loaded. You can keep asking.</p>
      ) : null}

      {error ? (
        <div className="mt-3">
          {rateLimited ? (
            <p role="alert" className="rounded-lg border border-warning-border bg-warning-subtle p-3 text-sm text-fg">
              You&apos;re asking a little fast. {error instanceof ApiError && error.retryAfter ? `Try again in ${error.retryAfter} seconds.` : "Wait a moment, then try again."}
            </p>
          ) : aiCode ? (
            <AIErrorState code={aiCode} detail={error instanceof ApiError ? error.problem?.detail : null} onRetry={() => void ask(lastMode)} />
          ) : (
            <ErrorState error={error} onRetry={() => void ask(lastMode)} />
          )}
        </div>
      ) : null}

      <div className="mt-3 flex flex-wrap gap-2">
        {(["guide", "explain"] as const).map((mode) => (
          <Button key={mode} variant={mode === "guide" ? "primary" : "secondary"} onClick={() => void ask(mode)} disabled={blocked || !input.trim() || busy !== null} loading={busy === mode}>
            {label(mode)}
          </Button>
        ))}
      </div>
    </section>
  );
}
