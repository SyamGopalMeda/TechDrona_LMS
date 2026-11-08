"use client";

import { useEffect, useMemo, useState } from "react";
import { Badge, Button, Dialog, EmptyState, ErrorState, Input, Select } from "@/components/ui";
import { api } from "@/lib/api/client";
import { LoadingBlock, useFailToast } from "@/features/trainer/shared/ui";
import { seg, useApi } from "@/features/trainer/shared/use-api";
import { useDebounced } from "./lib/hooks";
import { Chip, TagChips } from "./components/parts";
import { GROUPS, plainText, shortDate, typeLabel } from "./lib/labels";
import type { Bank, BankListResponse, BankQuestion, BankQuestionsResponse, PickedQuestion, ResolvedQuestion } from "./lib/types";

export type { PickedQuestion } from "./lib/types";

export interface QuestionBankPickerProps {
  open: boolean;
  onClose: () => void;
  onPick: (questions: PickedQuestion[]) => void | Promise<void>;
  /** Server question_type values; filters banks + questions. */
  allowedTypes?: string[];
  /** Default true: only questions with a published version are selectable. */
  requirePublished?: boolean;
  /** Default "Import questions from a bank". */
  title?: string;
  /** Default "Add questions". */
  confirmLabel?: string;
  /** Max selectable. */
  max?: number;
  /** Already added (shown, but not selectable). */
  excludeQuestionIds?: string[];
  /** Optional: short note shown under the title (e.g. "Questions are copied into this test."). */
  description?: string;
}

const UNCATEGORISED = "__none__";
const SORTS = [
  { value: "newest", label: "Newest first" },
  { value: "updated", label: "Recently updated" },
  { value: "name", label: "Name (A–Z)" },
];

/** Resolved question → the picker's public payload. */
export function toPicked(r: ResolvedQuestion, bankId: string): PickedQuestion {
  const v = r.version;
  return {
    question_id: r.question_id,
    question_version_id: v?.question_version_id ?? null,
    question_type: r.question_type,
    stem_html: v?.stem_html ?? "",
    stem_images: v?.stem_images ?? [],
    options: (v?.options ?? []).map((o) => ({
      option_id: o.option_id,
      label: o.label,
      html: o.html,
      image_url: o.image?.url ?? null,
      ...(o.is_correct !== undefined ? { is_correct: o.is_correct } : {}),
    })),
    settings: (v?.settings ?? {}) as Record<string, unknown>,
    tags: r.tags,
    difficulty: v?.difficulty ?? 3,
    bank_id: bankId,
    keys_visible: r.keys_visible,
  };
}

function typeCountsAllowed(counts: Record<string, number>, allowed?: string[]) {
  if (!allowed?.length) return counts;
  return Object.fromEntries(Object.entries(counts).filter(([t]) => allowed.includes(t)));
}

function groupKey(b: Bank, allowed?: string[]): { key: string; label: string } {
  const counts = typeCountsAllowed(b.type_counts, allowed);
  let best: { key: string; label: string; n: number } | null = null;
  for (const g of GROUPS) {
    const n = g.types.reduce((s, t) => s + (counts[t] ?? 0), 0);
    if (n > 0 && (!best || n > best.n)) best = { key: g.key, label: g.label, n };
  }
  return best ?? { key: "empty", label: "Empty" };
}

/**
 * "Import questions from a bank" picker, shared by assignments, tests and live activities.
 *
 * Browse banks (search, sort, subject chips, banks grouped by their main question type), drill
 * into one, tick questions (or "Select entire bank"), confirm. On confirm the picker calls
 * `POST studio/question-banks/resolve` with `prefer: requirePublished ? "published" : "latest"`
 * and passes the resolved questions to `onPick` as `PickedQuestion[]` (in selection order;
 * questions that resolve to no visible version are dropped when `requirePublished` is true).
 * The dialog stays open while `onPick` runs; the caller closes it via `open`/`onClose`.
 *
 * Props:
 * - `open`, `onClose` — controlled dialog.
 * - `onPick(questions)` — receives the picked questions; may be async.
 * - `allowedTypes` — server `question_type` values (e.g. `["mcq_single","mcq_multi"]`); banks
 *   without those types are hidden and other questions are listed as not selectable.
 * - `requirePublished` (default `true`) — only questions with a published version can be picked.
 * - `title` (default "Import questions from a bank"), `confirmLabel` (default "Add questions").
 * - `max` — maximum number of questions that can be selected.
 * - `excludeQuestionIds` — questions already added; shown as "Already added".
 * - `description` (optional, added) — short note under the title.
 */
export function QuestionBankPicker({
  open,
  onClose,
  onPick,
  allowedTypes,
  requirePublished = true,
  title = "Import questions from a bank",
  confirmLabel = "Add questions",
  max,
  excludeQuestionIds,
  description,
}: QuestionBankPickerProps) {
  const fail = useFailToast();
  const [search, setSearch] = useState("");
  const q = useDebounced(search.trim(), 300);
  const [sort, setSort] = useState("newest");
  const [subject, setSubject] = useState<string | null | undefined>(undefined);
  const [bank, setBank] = useState<Bank | null>(null);
  const [inner, setInner] = useState("");
  const [selected, setSelected] = useState<Map<string, string>>(new Map());
  const [busy, setBusy] = useState(false);
  const allowedKey = allowedTypes?.join(",") || undefined;

  useEffect(() => {
    if (open) {
      setSelected(new Map());
      setBank(null);
      setInner("");
    }
  }, [open]);

  const banks = useApi<BankListResponse>(open ? "studio/question-banks" : null, {
    q: q || undefined,
    sort,
    subject: subject === undefined ? undefined : (subject ?? UNCATEGORISED),
    types: allowedKey,
    limit: 100,
  });
  const questions = useApi<BankQuestionsResponse>(open && bank ? `studio/question-banks/${seg(bank.id)}/questions` : null, { limit: 100 });

  const excluded = useMemo(() => new Set(excludeQuestionIds ?? []), [excludeQuestionIds]);
  const atMax = max !== undefined && selected.size >= max;

  const reason = (x: BankQuestion): string | null => {
    if (excluded.has(x.question_id)) return "Already added";
    if (allowedTypes?.length && !allowedTypes.includes(x.question_type)) return `${typeLabel(x.question_type)} questions can't be used here`;
    if (x.status === "retired") return "Retired";
    if (requirePublished && !x.published_version_id) return "Not published yet";
    return null;
  };

  const term = inner.trim().toLowerCase();
  const rows = (questions.data?.items ?? []).filter(
    (x) => !term || plainText(x.latest_version?.stem_html).toLowerCase().includes(term) || x.tags.some((t) => t.toLowerCase().includes(term)),
  );
  const selectable = rows.filter((x) => !reason(x));

  const toggle = (id: string) =>
    setSelected((s) => {
      const next = new Map(s);
      if (next.has(id)) next.delete(id);
      else if (max === undefined || next.size < max) next.set(id, bank!.id);
      return next;
    });

  const selectAll = () =>
    setSelected((s) => {
      const next = new Map(s);
      for (const x of selectable) {
        if (max !== undefined && next.size >= max) break;
        next.set(x.question_id, bank!.id);
      }
      return next;
    });

  const confirm = async () => {
    if (!selected.size) return;
    setBusy(true);
    try {
      const ids = [...selected.keys()];
      const resolved: ResolvedQuestion[] = [];
      for (let i = 0; i < ids.length; i += 200) {
        const res = await api.post<{ items: ResolvedQuestion[] }>("studio/question-banks/resolve", { question_ids: ids.slice(i, i + 200), prefer: requirePublished ? "published" : "latest" });
        if (res.kind === "ok") resolved.push(...res.data.items);
      }
      const byId = new Map(resolved.map((r) => [r.question_id, r]));
      const picked = ids
        .map((id) => byId.get(id))
        .filter((r): r is ResolvedQuestion => !!r && (!requirePublished || r.version !== null))
        .map((r) => toPicked(r, selected.get(r.question_id)!));
      await onPick(picked);
    } catch (err) {
      fail(err, "Couldn't add the questions");
    } finally {
      setBusy(false);
    }
  };

  const grouped = useMemo(() => {
    const out = new Map<string, { label: string; items: Bank[] }>();
    for (const b of banks.data?.items ?? []) {
      const g = groupKey(b, allowedTypes);
      const entry = out.get(g.key) ?? { label: g.label, items: [] };
      entry.items.push(b);
      out.set(g.key, entry);
    }
    return [...out.entries()];
  }, [banks.data, allowedTypes]);

  const subjects = banks.data?.subjects ?? [];
  const allCount = subjects.reduce((n, s) => n + s.count, 0);

  const bankView = (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-2">
        <div className="min-w-40 flex-1">
          <Input type="search" aria-label="Search banks" placeholder="Search banks…" value={search} onChange={(e) => setSearch(e.target.value)} />
        </div>
        <Select aria-label="Sort banks" className="w-48" value={sort} onChange={(e) => setSort(e.target.value)} options={SORTS} />
      </div>
      {subjects.length ? (
        <div className="flex flex-wrap gap-1.5" role="group" aria-label="Filter by subject">
          <Chip active={subject === undefined} onClick={() => setSubject(undefined)} count={allCount}>
            All subjects
          </Chip>
          {subjects.map((s) => (
            <Chip key={s.subject ?? UNCATEGORISED} active={subject === s.subject} onClick={() => setSubject(s.subject)} count={s.count}>
              {s.subject ?? "Uncategorised"}
            </Chip>
          ))}
        </div>
      ) : null}
      {banks.error ? (
        <ErrorState error={banks.error} onRetry={() => void banks.reload()} />
      ) : banks.loading && !banks.data ? (
        <LoadingBlock rows={4} label="Loading banks" />
      ) : !grouped.length ? (
        <EmptyState title="No banks found" description={q ? "Try a different search." : "Create a question bank first under Question banks."} />
      ) : (
        grouped.map(([key, g]) => (
          <section key={key} aria-label={`${g.label} banks`}>
            <h3 className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-fg-muted">
              {g.label} banks <span className="tabular-nums">{g.items.length}</span>
            </h3>
            <ul className="grid gap-2 sm:grid-cols-2">
              {g.items.map((b) => (
                <li key={b.id}>
                  <button
                    type="button"
                    onClick={() => {
                      setBank(b);
                      setInner("");
                    }}
                    className="w-full rounded-lg border border-line bg-surface p-3 text-left hover:bg-surface-hover focus-visible:shadow-focus focus-visible:outline-none"
                  >
                    <span className="flex items-start justify-between gap-2">
                      <span className="min-w-0">
                        <span className="block truncate font-medium text-fg">{b.name}</span>
                        <span className="block truncate text-xs text-fg-muted">{b.subject || "Uncategorised"}</span>
                      </span>
                      <Badge tone="brand">{b.question_count} Qs</Badge>
                    </span>
                    <span className="mt-1.5 flex flex-wrap gap-1">
                      {Object.entries(typeCountsAllowed(b.type_counts, allowedTypes))
                        .filter(([, n]) => n > 0)
                        .map(([t, n]) => (
                          <Badge key={t}>
                            {n} {typeLabel(t)}
                          </Badge>
                        ))}
                    </span>
                    {b.tags.length ? <span className="mt-1 block truncate text-xs text-fg-secondary">{b.tags.map((t) => `#${t}`).join(" ")}</span> : null}
                    <span className="mt-1 block text-xs text-fg-muted">
                      Created {shortDate(b.created_at)}
                      {b.last_added_at ? ` · Last added ${shortDate(b.last_added_at)}` : ""}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          </section>
        ))
      )}
    </div>
  );

  const questionView = bank ? (
    <div className="space-y-3">
      <Button size="sm" variant="ghost" onClick={() => setBank(null)}>
        ← All banks
      </Button>
      <div>
        <p className="font-display text-base font-semibold text-fg">{bank.name}</p>
        <p className="text-sm text-fg-muted">
          {bank.subject || "Uncategorised"} · {bank.question_count} {bank.question_count === 1 ? "question" : "questions"}
        </p>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <div className="min-w-40 flex-1">
          <Input type="search" aria-label="Search questions in this bank" placeholder="Search questions & tags" value={inner} onChange={(e) => setInner(e.target.value)} />
        </div>
        <Button size="sm" variant="secondary" onClick={selectAll} disabled={!selectable.length || atMax}>
          Select entire bank ({selectable.length})
        </Button>
      </div>
      {questions.error ? (
        <ErrorState error={questions.error} onRetry={() => void questions.reload()} />
      ) : questions.loading && !questions.data ? (
        <LoadingBlock rows={4} label="Loading questions" />
      ) : !rows.length ? (
        <EmptyState title="No questions here" />
      ) : (
        <ul className="divide-y divide-line rounded-lg border border-line" aria-label="Questions">
          {rows.map((x) => {
            const why = reason(x);
            const checked = selected.has(x.question_id);
            const disabled = !!why || (!checked && atMax);
            const v = x.latest_version;
            const id = `qbp-${x.question_id}`;
            return (
              <li key={x.question_id} className="flex items-start gap-3 p-3">
                <input
                  id={id}
                  type="checkbox"
                  checked={checked}
                  disabled={disabled}
                  onChange={() => toggle(x.question_id)}
                  className="mt-1 h-5 w-5 shrink-0 accent-[var(--td-brand)]"
                  aria-describedby={why ? `${id}-why` : undefined}
                />
                <label htmlFor={id} className={disabled && !checked ? "min-w-0 flex-1 opacity-70" : "min-w-0 flex-1"}>
                  <span className="line-clamp-2 text-sm text-fg">{plainText(v?.stem_html) || "Untitled question"}</span>
                  <span className="mt-1 flex flex-wrap items-center gap-1.5 text-xs text-fg-muted">
                    <Badge>{typeLabel(x.question_type)}</Badge>
                    {v && v.option_count > 0 ? <span>{v.option_count} options</span> : null}
                    {why ? <span id={`${id}-why`}>· {why}</span> : null}
                  </span>
                  <span className="mt-1 block">
                    <TagChips tags={x.tags} max={4} />
                  </span>
                </label>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  ) : null;

  return (
    <Dialog
      open={open}
      onClose={onClose}
      dismissible={!busy}
      className="max-w-3xl"
      title={title}
      description={description}
      footer={
        <>
          <span className="mr-auto self-center text-sm text-fg-muted" aria-live="polite">
            {selected.size} selected{max !== undefined ? ` of ${max} max` : ""}
          </span>
          <Button variant="secondary" onClick={onClose} disabled={busy}>
            Cancel
          </Button>
          <Button onClick={() => void confirm()} loading={busy} disabled={!selected.size}>
            {confirmLabel}
          </Button>
        </>
      }
    >
      <div className="max-h-[60vh] overflow-y-auto pr-1">{bank ? questionView : bankView}</div>
    </Dialog>
  );
}
