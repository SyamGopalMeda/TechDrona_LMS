"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { Badge, Button, Checkbox, Dialog, EmptyState, ErrorState, Input, Select, useToast } from "@/components/ui";
import { api } from "@/lib/api/client";
import { LoadingBlock, StatusBadge, useFailToast } from "@/features/trainer/shared/ui";
import { seg, useApi } from "@/features/trainer/shared/use-api";
import { QuestionBankPicker } from "../QuestionBankPicker";
import { useDebounced } from "../lib/hooks";
import { GROUPS, groupCounts, groupOf, plainText, typeIcon, typeLabel } from "../lib/labels";
import type { BankQuestion, BankQuestionsResponse } from "../lib/types";
import { BankFormDialog } from "./BankFormDialog";
import { BulkImportDialog } from "./BulkImportDialog";
import { GenerateDialog } from "./GenerateDialog";
import { QuestionEditorDialog } from "./QuestionEditorDialog";
import { Chip, TagChips } from "./parts";

type DialogKey = "from" | "bulk" | "ai" | "edit-bank" | "delete-bank";

/** One bank: filters, question rows (edit / remove), add from bank / bulk import / AI / new. */
export function BankDetail({ bankId }: { bankId: string }) {
  const router = useRouter();
  const toast = useToast();
  const fail = useFailToast();
  const [group, setGroup] = useState<string>("all");
  const [difficulty, setDifficulty] = useState("");
  const [tag, setTag] = useState("");
  const [search, setSearch] = useState("");
  const q = useDebounced(search.trim(), 300);
  const [dialog, setDialog] = useState<DialogKey | null>(null);
  const [editing, setEditing] = useState<{ id: string | null } | null>(null);
  const [removing, setRemoving] = useState<BankQuestion | null>(null);
  const [purge, setPurge] = useState(false);
  const [busy, setBusy] = useState(false);

  // A group maps to one server type except MCQ (single + multi): filter that one on the client.
  const g = GROUPS.find((x) => x.key === group);
  const state = useApi<BankQuestionsResponse>(`studio/question-banks/${seg(bankId)}/questions`, {
    type: g && g.types.length === 1 ? g.types[0] : undefined,
    difficulty: difficulty || undefined,
    tag: tag || undefined,
    q: q.length >= 2 ? q : undefined,
    limit: 100,
  });
  const data = state.data;
  const bank = data?.bank;
  const items = (data?.items ?? []).filter((x) => group === "all" || groupOf(x.question_type) === group);
  const counts = groupCounts(data?.type_counts ?? bank?.type_counts);
  const totalCount = counts.reduce((n, c) => n + c.count, 0);

  const reload = () => void state.reload();

  const remove = async () => {
    if (!removing) return;
    setBusy(true);
    try {
      const res = await api.delete<{ removed: boolean; purged: boolean }>(`studio/question-banks/${seg(bankId)}/questions/${seg(removing.question_id)}`, { query: { purge: purge && !removing.published_version_id } });
      toast.show({ tone: "success", title: res.kind === "ok" && res.data?.purged ? "Draft question deleted" : "Question removed from this bank" });
      setRemoving(null);
      reload();
    } catch (err) {
      fail(err, "Couldn't remove the question");
    } finally {
      setBusy(false);
    }
  };

  const deleteBank = async () => {
    setBusy(true);
    try {
      await api.delete(`studio/question-banks/${seg(bankId)}`);
      toast.show({ tone: "success", title: "Bank deleted", description: "Its questions are still in the question library." });
      router.push("/studio/question-banks");
    } catch (err) {
      fail(err, "Couldn't delete the bank");
    } finally {
      setBusy(false);
      setDialog(null);
    }
  };

  if (state.error && !data) return <ErrorState error={state.error} onRetry={reload} />;
  if (!data || !bank) return <LoadingBlock rows={5} label="Loading bank" />;

  return (
    <div className="space-y-5">
      <Link href="/studio/question-banks" className="text-sm text-fg-link underline">
        ← All banks
      </Link>
      <header className="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <h1 className="font-display text-2xl font-bold text-fg">{bank.name}</h1>
          <p className="text-sm text-fg-muted">
            {bank.subject || "Uncategorised"} · {bank.question_count} {bank.question_count === 1 ? "question" : "questions"}
          </p>
          {bank.description ? <p className="mt-1 max-w-prose text-sm text-fg-secondary">{bank.description}</p> : null}
          <div className="mt-1 flex gap-3 text-sm">
            <button type="button" className="text-fg-link underline" onClick={() => setDialog("edit-bank")}>
              Edit details
            </button>
            <button type="button" className="text-danger-fg underline" onClick={() => setDialog("delete-bank")}>
              Delete bank
            </button>
          </div>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button variant="secondary" onClick={() => setDialog("from")}>
            From bank
          </Button>
          <Button variant="secondary" onClick={() => setDialog("bulk")}>
            Bulk import
          </Button>
          <Button variant="secondary" onClick={() => setDialog("ai")}>
            <span aria-hidden="true">✦</span> AI
          </Button>
          <Button onClick={() => setEditing({ id: null })}>Add question</Button>
        </div>
      </header>

      <div className="flex flex-wrap gap-1.5" role="group" aria-label="Filter by type">
        <Chip active={group === "all"} onClick={() => setGroup("all")} count={totalCount}>
          All
        </Chip>
        {counts.map((c) => (
          <Chip key={c.key} active={group === c.key} onClick={() => setGroup(String(c.key))} count={c.count}>
            {c.label}
          </Chip>
        ))}
      </div>
      <div className="flex flex-wrap gap-2">
        <div className="min-w-48 flex-1">
          <Input type="search" aria-label="Search questions & tags" placeholder="Search questions & tags" value={search} maxLength={200} onChange={(e) => setSearch(e.target.value)} />
        </div>
        <Select
          aria-label="Filter by tag"
          className="w-44"
          value={tag}
          onChange={(e) => setTag(e.target.value)}
          options={[{ value: "", label: "All tags" }, ...(data.tags ?? []).map((t) => ({ value: t, label: t }))]}
        />
        <Select
          aria-label="Filter by difficulty"
          className="w-40"
          value={difficulty}
          onChange={(e) => setDifficulty(e.target.value)}
          options={[{ value: "", label: "Any difficulty" }, ...[1, 2, 3, 4, 5].map((d) => ({ value: String(d), label: `Difficulty ${d}` }))]}
        />
      </div>

      {state.error ? <ErrorState error={state.error} onRetry={reload} /> : null}
      {!items.length ? (
        <EmptyState
          title={bank.question_count ? "No questions match" : "This bank is empty"}
          description={bank.question_count ? "Try other filters." : "Add a question, import some from a chat model or let AI draft a few."}
          action={!bank.question_count ? <Button onClick={() => setEditing({ id: null })}>Add question</Button> : undefined}
        />
      ) : (
        <ul aria-label="Questions" aria-busy={state.loading} className="divide-y divide-line rounded-xl border border-line bg-surface">
          {items.map((x) => {
            const v = x.latest_version;
            const isMcq = groupOf(x.question_type) === "mcq";
            return (
              <li key={x.question_id} className="flex flex-col gap-2 p-4 sm:flex-row sm:items-start">
                <span aria-hidden="true" className="hidden rounded-md bg-surface-sunken px-2 py-1 font-mono text-xs sm:block">
                  {typeIcon(x.question_type)}
                </span>
                <div className="min-w-0 flex-1 space-y-1.5">
                  <div className="flex flex-wrap items-center gap-1.5">
                    <Badge tone="brand">{typeLabel(x.question_type).toUpperCase()}</Badge>
                    {isMcq && typeof v?.correct_count === "number" ? <span className="text-xs text-fg-muted">{v.correct_count} correct</span> : null}
                    {x.status === "retired" ? <StatusBadge status="retired" /> : v ? <StatusBadge status={v.status} /> : null}
                    {v && !x.published_version_id && v.status !== "published" ? <span className="text-xs text-fg-muted">Needs review before use</span> : null}
                  </div>
                  <p className="line-clamp-2 text-sm text-fg">{plainText(v?.stem_html) || "Untitled question"}</p>
                  <TagChips tags={x.tags} />
                </div>
                <div className="flex shrink-0 gap-1">
                  <Button size="sm" variant="ghost" aria-label={`Edit question: ${plainText(v?.stem_html).slice(0, 60)}`} onClick={() => setEditing({ id: x.question_id })}>
                    Edit
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    aria-label={`Remove question: ${plainText(v?.stem_html).slice(0, 60)}`}
                    onClick={() => {
                      setPurge(false);
                      setRemoving(x);
                    }}
                  >
                    Delete
                  </Button>
                </div>
              </li>
            );
          })}
        </ul>
      )}
      {data.total > data.items.length ? <p className="text-sm text-fg-muted">Showing the first {data.items.length} of {data.total} questions. Use search or filters to narrow the list.</p> : null}

      <QuestionEditorDialog open={editing !== null} onClose={() => setEditing(null)} questionId={editing?.id ?? null} bankId={bankId} organizationId={bank.organization_id} onSaved={reload} />
      <BankFormDialog
        open={dialog === "edit-bank"}
        onClose={() => setDialog(null)}
        bank={bank}
        onSaved={() => {
          setDialog(null);
          reload();
        }}
      />
      <BulkImportDialog
        open={dialog === "bulk"}
        onClose={() => setDialog(null)}
        defaultBankId={bankId}
        onImported={() => {
          setDialog(null);
          reload();
        }}
      />
      <GenerateDialog
        open={dialog === "ai"}
        onClose={() => setDialog(null)}
        defaultBankId={bankId}
        onSaved={() => {
          setDialog(null);
          reload();
        }}
      />
      <QuestionBankPicker
        open={dialog === "from"}
        onClose={() => setDialog(null)}
        requirePublished={false}
        title="Add questions from another bank"
        confirmLabel="Add to this bank"
        description="The questions are shared, not copied: edits show up in every bank that holds them."
        excludeQuestionIds={data.items.map((x) => x.question_id)}
        onPick={async (picked) => {
          const res = await api.post<{ added: number }>(`studio/question-banks/${seg(bankId)}/questions`, { question_ids: picked.map((p) => p.question_id) });
          if (res.kind === "ok") toast.show({ tone: "success", title: `${res.data.added} ${res.data.added === 1 ? "question" : "questions"} added to this bank` });
          setDialog(null);
          reload();
        }}
      />
      <Dialog
        open={removing !== null}
        onClose={() => setRemoving(null)}
        dismissible={!busy}
        title="Remove this question from the bank?"
        description={plainText(removing?.latest_version?.stem_html).slice(0, 160)}
        footer={
          <>
            <Button variant="secondary" onClick={() => setRemoving(null)} disabled={busy}>
              Cancel
            </Button>
            <Button variant="danger" loading={busy} onClick={() => void remove()}>
              {purge ? "Delete question" : "Remove"}
            </Button>
          </>
        }
      >
        {removing && !removing.published_version_id ? (
          <Checkbox label="Also delete the question" description="It has never been published, so nothing else uses it." checked={purge} onChange={(e) => setPurge(e.target.checked)} />
        ) : (
          <p className="text-sm text-fg-muted">The question stays in the question library and in any test that uses it.</p>
        )}
      </Dialog>
      <Dialog
        open={dialog === "delete-bank"}
        onClose={() => setDialog(null)}
        dismissible={!busy}
        title={`Delete “${bank.name}”?`}
        description="The bank is removed. Its questions stay in the question library."
        footer={
          <>
            <Button variant="secondary" onClick={() => setDialog(null)} disabled={busy}>
              Cancel
            </Button>
            <Button variant="danger" loading={busy} onClick={() => void deleteBank()}>
              Delete bank
            </Button>
          </>
        }
      />
    </div>
  );
}
