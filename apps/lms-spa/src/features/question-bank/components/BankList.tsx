"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { Badge, Button, EmptyState, ErrorState, Input, LoadingBlock, PageHeader, StatGrid, StatTile } from "@/components/ui";
import { seg, useApi } from "@/features/trainer/shared/use-api";
import { cn } from "@/lib/ui/cn";
import { useDebounced } from "../lib/hooks";
import { dominantGroup, groupCounts, typeIcon } from "../lib/labels";
import type { Bank, BankListResponse } from "../lib/types";
import { BankFormDialog } from "./BankFormDialog";
import { BulkImportDialog } from "./BulkImportDialog";
import { GenerateDialog } from "./GenerateDialog";

export type BankView = "grid" | "list";
export const VIEW_KEY = "td.question-banks.view";

function readView(): BankView {
  try {
    return window.localStorage.getItem(VIEW_KEY) === "list" ? "list" : "grid";
  } catch {
    return "grid";
  }
}

function writeView(v: BankView) {
  try {
    window.localStorage.setItem(VIEW_KEY, v);
  } catch {
    /* storage unavailable: the choice just isn't remembered */
  }
}

const href = (b: Bank) => `/studio/question-banks/${seg(b.id)}`;

/** Question banks list: counters, search, grid/list view, create / bulk import / AI. */
export function BankList() {
  const router = useRouter();
  const [q, setQ] = useState("");
  const query = useDebounced(q.trim(), 300);
  const [view, setView] = useState<BankView>("grid");
  const [dialog, setDialog] = useState<"new" | "bulk" | "ai" | null>(null);
  const list = useApi<BankListResponse>("studio/question-banks", { q: query || undefined, sort: "updated", limit: 100 });

  useEffect(() => setView(readView()), []);
  const choose = (v: BankView) => {
    setView(v);
    writeView(v);
  };

  const data = list.data;
  const items = data?.items ?? [];
  const afterImport = () => {
    setDialog(null);
    void list.reload();
  };

  return (
    <div>
      <PageHeader
        title="Question banks"
        description="Author reusable questions for practice, tests, assignments and live polls."
        actions={
          <>
            <Button variant="secondary" onClick={() => setDialog("bulk")}>
              Bulk import
            </Button>
            <Button variant="secondary" onClick={() => setDialog("ai")}>
              <span aria-hidden="true">✦</span> Generate with AI
            </Button>
            <Button onClick={() => setDialog("new")}>New bank</Button>
          </>
        }
      />
      <StatGrid columns={3} className="mb-6">
        <StatTile label="Banks" value={data ? data.counters.banks : null} />
        <StatTile label="Questions" value={data ? data.counters.questions : null} />
        <StatTile label="Subjects" value={data ? data.counters.subjects : null} />
      </StatGrid>
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <div className="min-w-48 flex-1">
          <Input type="search" aria-label="Search banks" placeholder="Search banks…" value={q} maxLength={200} onChange={(e) => setQ(e.target.value)} />
        </div>
        <span className="text-sm tabular-nums text-fg-muted" aria-live="polite">
          {data ? `${data.total} ${data.total === 1 ? "bank" : "banks"}` : ""}
        </span>
        <div role="group" aria-label="View" className="inline-flex rounded-md border border-line-control">
          {(["grid", "list"] as const).map((v) => (
            <button
              key={v}
              type="button"
              aria-pressed={view === v}
              onClick={() => choose(v)}
              className={cn("h-touch px-3 text-sm md:h-9 focus-visible:shadow-focus focus-visible:outline-none", view === v ? "bg-brand-subtle font-medium text-brand-on-subtle" : "text-fg-secondary hover:bg-surface-hover")}
            >
              {v === "grid" ? "Grid" : "List"}
            </button>
          ))}
        </div>
      </div>

      {list.error ? (
        <ErrorState error={list.error} onRetry={() => void list.reload()} />
      ) : list.loading && !data ? (
        <LoadingBlock rows={4} label="Loading banks" size="row" />
      ) : !items.length ? (
        <EmptyState
          title={query ? "No banks match" : "No question banks yet"}
          description={query ? "Try a different search." : "Create a bank, import questions from a chat model or let AI draft some for you."}
          action={!query ? <Button onClick={() => setDialog("new")}>New bank</Button> : undefined}
        />
      ) : view === "grid" ? (
        <ul aria-label="Question banks" className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {items.map((b) => {
            const dom = dominantGroup(b.type_counts);
            return (
              <li key={b.id} className="flex flex-col rounded-xl border border-line bg-surface p-4 shadow-xs">
                <div className="flex items-start justify-between gap-2">
                  <span aria-hidden="true" className="rounded-md bg-brand-subtle px-2 py-1 font-mono text-xs text-brand-on-subtle">
                    {dom ? typeIcon(dom.key) : "∅"}
                  </span>
                  <Badge tone="brand">
                    {b.question_count} {b.question_count === 1 ? "question" : "questions"}
                  </Badge>
                </div>
                <h2 className="mt-3 font-display text-base font-semibold text-fg">{b.name}</h2>
                <p className="text-sm text-fg-muted">{b.subject || "Uncategorised"}</p>
                <div className="mt-2 flex flex-wrap gap-1">
                  {groupCounts(b.type_counts).map((g) => (
                    <Badge key={g.key}>
                      {g.count} {g.label}
                    </Badge>
                  ))}
                </div>
                <Link href={href(b)} className="mt-auto inline-flex min-h-touch items-end pt-3 text-sm font-medium text-fg-link underline md:min-h-0" aria-label={`Open bank ${b.name}`}>
                  Open bank →
                </Link>
              </li>
            );
          })}
        </ul>
      ) : (
        <ul aria-label="Question banks" className="divide-y divide-line rounded-xl border border-line bg-surface">
          {items.map((b) => (
            <li key={b.id}>
              <Link href={href(b)} className="flex items-center gap-3 px-4 py-3 hover:bg-surface-hover focus-visible:shadow-focus focus-visible:outline-none">
                <span className="min-w-0 flex-1">
                  <span className="block truncate font-medium text-fg">{b.name}</span>
                  <span className="block truncate text-sm text-fg-muted">{b.subject || "Uncategorised"}</span>
                </span>
                <span className="text-sm tabular-nums text-fg-secondary">{b.question_count} Qs</span>
                <span aria-hidden="true">→</span>
              </Link>
            </li>
          ))}
        </ul>
      )}

      <BankFormDialog
        open={dialog === "new"}
        onClose={() => setDialog(null)}
        onSaved={(b) => {
          setDialog(null);
          router.push(href(b));
        }}
      />
      <BulkImportDialog open={dialog === "bulk"} onClose={() => setDialog(null)} onImported={afterImport} />
      <GenerateDialog open={dialog === "ai"} onClose={() => setDialog(null)} onSaved={afterImport} />
    </div>
  );
}
