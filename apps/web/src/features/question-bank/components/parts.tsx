"use client";

import { useId, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import { Badge, Button, FormField, Input, Select } from "@/components/ui";
import { useApi } from "@/features/trainer/shared/use-api";
import { cn } from "@/lib/ui/cn";
import { KINDS } from "../lib/labels";
import { imageProblem, uploadQuestionImage, type UploadPhase } from "../lib/media";
import type { BankListResponse, ImportKind } from "../lib/types";

/** Single-select type tiles (Code, MCQ, Essay, Poll, Survey, Words) as a radio group. */
export function KindTiles({ value, onChange, label = "Question type", kinds = KINDS }: { value: string; onChange: (v: ImportKind) => void; label?: string; kinds?: typeof KINDS }) {
  const id = useId();
  return (
    <fieldset>
      <legend id={id} className="mb-1.5 text-sm font-medium text-fg">
        {label}
      </legend>
      <div role="radiogroup" aria-labelledby={id} className="grid grid-cols-3 gap-2 sm:grid-cols-6">
        {kinds.map((k) => {
          const on = value === k.value;
          return (
            <button
              key={k.value}
              type="button"
              role="radio"
              aria-checked={on}
              title={k.hint}
              onClick={() => onChange(k.value)}
              className={cn(
                "flex flex-col items-center gap-1 rounded-lg border px-2 py-2 text-sm focus-visible:shadow-focus focus-visible:outline-none",
                on ? "border-brand bg-brand-subtle font-semibold text-brand-on-subtle" : "border-line bg-surface text-fg hover:bg-surface-hover",
              )}
            >
              <span aria-hidden="true" className="font-mono text-xs">
                {k.icon}
              </span>
              {k.label}
            </button>
          );
        })}
      </div>
    </fieldset>
  );
}

/** Toggle chip used for filters (type, subject). */
export function Chip({ active, onClick, children, count }: { active: boolean; onClick: () => void; children: ReactNode; count?: number }) {
  return (
    <button
      type="button"
      aria-pressed={active}
      onClick={onClick}
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-sm focus-visible:shadow-focus focus-visible:outline-none",
        active ? "border-brand bg-brand-subtle font-medium text-brand-on-subtle" : "border-line bg-surface text-fg-secondary hover:bg-surface-hover",
      )}
    >
      {children}
      {count !== undefined ? <span className="tabular-nums text-xs opacity-80">{count}</span> : null}
    </button>
  );
}

export function TagChips({ tags, max = 6 }: { tags: string[]; max?: number }) {
  if (!tags.length) return null;
  const shown = tags.slice(0, max);
  return (
    <ul className="flex flex-wrap gap-1" aria-label="Tags">
      {shown.map((t) => (
        <li key={t}>
          <Badge>{t}</Badge>
        </li>
      ))}
      {tags.length > shown.length ? (
        <li>
          <Badge>+{tags.length - shown.length}</Badge>
        </li>
      ) : null}
    </ul>
  );
}

/** Tags input: type and press Enter (or comma) to add; each tag has a remove button. */
export function TagInput({ value, onChange, disabled, hint }: { value: string[]; onChange: (v: string[]) => void; disabled?: boolean; hint?: ReactNode }) {
  const [text, setText] = useState("");
  const add = () => {
    const t = text.trim().toLowerCase().replace(/^#/, "").slice(0, 40);
    if (t && !value.includes(t) && value.length < 20) onChange([...value, t]);
    setText("");
  };
  const onKey = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter" || e.key === ",") {
      e.preventDefault();
      add();
    } else if (e.key === "Backspace" && !text && value.length) onChange(value.slice(0, -1));
  };
  return (
    <FormField label="Tags" hint={hint ?? "Used later for search & filtering. Press Enter to add."}>
      {(p) => (
        <div className="space-y-2">
          {value.length ? (
            <ul className="flex flex-wrap gap-1.5" aria-label="Added tags">
              {value.map((t) => (
                <li key={t} className="inline-flex items-center gap-1 rounded-full border border-line bg-surface-sunken py-0.5 pl-2.5 pr-1 text-xs">
                  {t}
                  {!disabled ? (
                    <button type="button" aria-label={`Remove tag ${t}`} className="rounded-full px-1 hover:bg-surface-hover" onClick={() => onChange(value.filter((x) => x !== t))}>
                      ×
                    </button>
                  ) : null}
                </li>
              ))}
            </ul>
          ) : null}
          {!disabled ? <Input {...p} value={text} placeholder="Add a tag and press Enter" onChange={(e) => setText(e.target.value)} onKeyDown={onKey} onBlur={() => text.trim() && add()} /> : null}
        </div>
      )}
    </FormField>
  );
}

export interface ImageValue {
  media_id: string;
  url: string | null;
  phase: UploadPhase;
}

/** Optional image (question or option) uploaded through the question-media endpoints. */
export function ImageField({
  value,
  onChange,
  label,
  compact = false,
  disabled,
  organizationId,
}: {
  value: ImageValue | null;
  onChange: (v: ImageValue | null) => void;
  label: string;
  compact?: boolean;
  disabled?: boolean;
  organizationId?: string | null;
}) {
  const input = useRef<HTMLInputElement>(null);
  const [phase, setPhase] = useState<UploadPhase | null>(null);
  const [error, setError] = useState<string | null>(null);
  const busy = phase === "uploading" || (phase === "scanning" && !value);

  const pick = async (file: File | undefined) => {
    if (!file) return;
    const problem = imageProblem(file);
    if (problem) {
      setError(problem);
      return;
    }
    setError(null);
    try {
      const res = await uploadQuestionImage(file, { organizationId, onPhase: setPhase });
      onChange({ media_id: res.media_id, url: res.url, phase: res.phase });
      if (res.phase === "failed") setError("The image failed its safety scan or could not be stored. Try another image.");
    } catch {
      setPhase("failed");
      setError("The image couldn't be uploaded. Check your connection and try again.");
    } finally {
      if (input.current) input.current.value = "";
    }
  };

  const status = value?.phase ?? phase;
  return (
    <div className={cn("flex flex-wrap items-center gap-2", compact ? "" : "rounded-lg border border-dashed border-line-strong p-3")}>
      <input ref={input} type="file" accept="image/png,image/jpeg,image/webp,image/gif" className="sr-only" aria-label={label} tabIndex={-1} onChange={(e) => void pick(e.target.files?.[0])} disabled={disabled || busy} />
      {value?.url && value.phase === "ready" ? (
        // eslint-disable-next-line @next/next/no-img-element -- signed, scanned question media via the api redirect
        <img src={value.url} alt="" className={compact ? "h-8 w-8 rounded object-cover" : "h-16 w-auto max-w-[8rem] rounded object-contain"} />
      ) : null}
      <Button size="sm" variant={compact ? "ghost" : "secondary"} disabled={disabled} loading={busy} onClick={() => input.current?.click()} aria-label={value ? `Replace ${label.toLowerCase()}` : label}>
        {compact ? (value ? "Replace image" : "Image") : value ? "Replace image" : label}
      </Button>
      {value && !disabled ? (
        <Button size="sm" variant="ghost" onClick={() => onChange(null)} aria-label={`Remove ${label.toLowerCase()}`}>
          Remove
        </Button>
      ) : null}
      <span aria-live="polite" className="text-xs text-fg-muted">
        {status === "uploading" ? "Uploading…" : status === "scanning" ? "Scanning the image…" : status === "failed" ? "Upload failed" : ""}
      </span>
      {error ? (
        <p role="alert" className="w-full text-xs font-medium text-danger-fg">
          {error}
        </p>
      ) : null}
    </div>
  );
}

export const NEW_BANK = "__new__";

/** Banks for "Save to" selects (loaded only while a dialog is open). */
export function useBankOptions(active: boolean) {
  return useApi<BankListResponse>(active ? "studio/question-banks" : null, { sort: "name", limit: 100 });
}

/** "Save to" bank select plus the "New bank name" field when "+ New bank" is chosen. */
export function SaveToFields({
  banks,
  value,
  onChange,
  newName,
  onNewName,
  nameHint = "Auto-named if left blank",
}: {
  banks: ReturnType<typeof useBankOptions>;
  value: string;
  onChange: (v: string) => void;
  newName: string;
  onNewName: (v: string) => void;
  nameHint?: string;
}) {
  const items = banks.data?.items ?? [];
  return (
    <div className="grid gap-4 sm:grid-cols-2">
      <FormField label="Save to">
        {(p) => (
          <Select
            {...p}
            value={value}
            onChange={(e) => onChange(e.target.value)}
            options={[{ value: NEW_BANK, label: "+ New bank" }, ...items.map((b) => ({ value: b.id, label: b.subject ? `${b.name} (${b.subject})` : b.name }))]}
          />
        )}
      </FormField>
      {value === NEW_BANK ? (
        <FormField label="New bank name">{(p) => <Input {...p} value={newName} maxLength={120} placeholder={nameHint} onChange={(e) => onNewName(e.target.value)} />}</FormField>
      ) : null}
    </div>
  );
}

/** Problems panel shared by bulk import and AI generation. */
export function ProblemsPanel({ problems, fixPrompt, onCopy }: { problems: { index: number | null; field: string; message: string }[]; fixPrompt: string | null; onCopy: () => void }) {
  const n = problems.length;
  return (
    <div role="alert" className="rounded-lg border border-warning-border bg-warning-subtle p-4 text-sm">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="font-semibold text-warning-fg">
          <span aria-hidden="true">⚠ </span>
          {n} {n === 1 ? "problem" : "problems"} found
        </p>
        {fixPrompt ? (
          <Button size="sm" variant="secondary" onClick={onCopy}>
            Copy for the model
          </Button>
        ) : null}
      </div>
      <ul className="mt-2 max-h-48 list-disc space-y-1 overflow-y-auto pl-5 text-fg">
        {problems.map((p, i) => (
          <li key={i}>
            <span className="font-medium">{p.index === null ? "Whole response" : `Item #${p.index + 1}`}</span>
            {p.field ? <span className="text-fg-muted"> · {p.field}</span> : null} · {p.message}
          </li>
        ))}
      </ul>
      {fixPrompt ? <p className="mt-2 text-xs text-fg-muted">Copy these back to the model, ask it to fix them and return corrected JSON, then paste again.</p> : null}
    </div>
  );
}
