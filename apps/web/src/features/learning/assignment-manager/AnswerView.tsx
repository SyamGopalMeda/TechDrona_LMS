"use client";

import type { ReactNode } from "react";
import { RichHtml } from "@/features/assessment/components/RichHtml";
import { VerdictChip } from "@/features/coding/components/VerdictPanel";
import type { ItemCode, ItemOption, ItemResponse } from "./types";

/** Question text: inline prompts are plain text (markdown source); bank stems are sanitised HTML. */
export function QuestionText({ prompt_md, stem_html, className }: { prompt_md: string | null; stem_html: string | null; className?: string }) {
  if (prompt_md) return <p className={`whitespace-pre-wrap break-words text-sm text-fg ${className ?? ""}`}>{prompt_md}</p>;
  return <RichHtml html={stem_html} className={`text-sm text-fg ${className ?? ""}`} />;
}

function str(v: unknown): string | null {
  return typeof v === "string" ? v : null;
}

function arr(v: unknown): string[] {
  return Array.isArray(v) ? v.filter((x): x is string => typeof x === "string") : [];
}

/**
 * A learner's answer for one item, read-only. `code` (staff review) carries the judged source;
 * otherwise the coding response's source is shown. `renderFile` adds a download action per file.
 */
export function AnswerView({
  itemType,
  response,
  options,
  code,
  renderFile,
}: {
  itemType: string;
  response: ItemResponse | null;
  options: ItemOption[];
  code?: ItemCode | null;
  renderFile?: (key: string, index: number) => ReactNode;
}) {
  const r = (response ?? {}) as Record<string, unknown>;
  if (itemType === "coding" || code) {
    const source = code?.source_code ?? str(r.source_code);
    const lang = code?.language_key ?? str(r.language_key);
    if (!source) return <p className="text-sm text-fg-muted">No code submitted.</p>;
    const judge = code?.judge;
    return (
      <div className="space-y-2">
        <div className="flex flex-wrap items-center gap-2 text-xs text-fg-muted">
          {lang ? <span>Language: {lang}</span> : null}
          {judge ? (
            <>
              <VerdictChip verdict={judge.verdict} />
              {judge.passed_cases !== null && judge.total_cases !== null ? (
                <span>
                  {judge.passed_cases}/{judge.total_cases} tests passed
                </span>
              ) : null}
              {judge.status !== "completed" ? <span>Judge: {judge.status}</span> : null}
            </>
          ) : null}
        </div>
        <pre className="max-h-80 overflow-auto rounded-md border border-line bg-surface-sunken p-3 font-mono text-xs text-fg" aria-label="Submitted code">
          <code>{source}</code>
        </pre>
      </div>
    );
  }
  if (itemType === "mcq_single" || itemType === "mcq_multi") {
    const chosen = new Set(arr(r.option_ids));
    if (options.length === 0) return <p className="text-sm text-fg-muted">{chosen.size ? `${chosen.size} option(s) chosen.` : "Not answered."}</p>;
    return (
      <ul className="space-y-1" aria-label="Options">
        {options.map((o) => (
          <li key={o.option_id} className={`flex items-start gap-2 rounded-md border p-2 text-sm ${chosen.has(o.option_id) ? "border-line-strong bg-brand-subtle" : "border-line"}`}>
            <span className="font-semibold">{o.label}.</span>
            <RichHtml html={o.html} as="span" className="flex-1" />
            {chosen.has(o.option_id) ? <span className="text-xs font-medium text-brand-on-subtle">Chosen</span> : null}
          </li>
        ))}
      </ul>
    );
  }
  if (itemType === "file") {
    const keys = arr(r.file_s3_keys);
    if (!keys.length) return <p className="text-sm text-fg-muted">No files uploaded.</p>;
    return (
      <ul className="space-y-1 text-sm" aria-label="Uploaded files">
        {keys.map((k, i) => (
          <li key={k} className="flex items-center justify-between gap-2">
            <span className="truncate text-fg-secondary">{k.split("/").pop() || `File ${i + 1}`}</span>
            {renderFile?.(k, i)}
          </li>
        ))}
      </ul>
    );
  }
  const text = str(r.text) ?? str(r.value);
  if (!text) return <p className="text-sm text-fg-muted">Not answered.</p>;
  return <p className="whitespace-pre-wrap break-words rounded-md border border-line bg-surface-sunken p-3 text-sm text-fg">{text}</p>;
}
