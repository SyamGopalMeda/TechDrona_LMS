"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { Badge, Button, ConfirmDialog, EmptyState, ErrorState, Input, LinkButton, Select, useToast } from "@/components/ui";
import { api } from "@/lib/api/client";
import { seg, useApi } from "@/features/trainer/shared/use-api";
import { ACTIVITY_TYPES, plural, settingsSummary, TYPE_LABEL } from "../lib/labels";
import type { Activity, ActivityList as ActivityListData, ActivitySummary, ActivityType } from "../lib/types";
import { errorText, Loading, StatusBadge } from "./parts";
import { useEngageScope } from "../lib/scope";

function NewMenu() {
  const { base } = useEngageScope();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", onDoc);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDoc);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);
  return (
    <div ref={ref} className="relative">
      <Button aria-haspopup="menu" aria-expanded={open} onClick={() => setOpen((v) => !v)}>
        New <span aria-hidden="true">▾</span>
      </Button>
      {open ? (
        <ul role="menu" aria-label="New activity type" className="absolute right-0 z-dropdown mt-1 w-44 rounded-lg border border-line bg-surface-raised p-1 shadow-lg">
          {ACTIVITY_TYPES.map((t) => (
            <li key={t} role="none">
              <Link role="menuitem" href={`${base}/new?type=${t}`} className="block rounded-md px-3 py-2 text-sm text-fg hover:bg-surface-hover focus-visible:outline-none focus-visible:shadow-focus">
                {TYPE_LABEL[t]}
              </Link>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

export function ActivityCard({
  activity: a,
  onDuplicate,
  onDelete,
  busy,
}: {
  activity: ActivitySummary;
  onDuplicate: () => void;
  onDelete: () => void;
  busy: boolean;
}) {
  const { base } = useEngageScope();
  return (
    <li className="flex flex-col gap-3 rounded-xl border border-line bg-surface p-4 shadow-xs">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="text-xs font-semibold uppercase tracking-wide text-fg-muted">{TYPE_LABEL[a.activity_type]}</p>
          <h2 className="mt-0.5 break-words font-display text-base font-semibold text-fg">
            <Link href={`${base}/${seg(a.id)}`} className="text-fg no-underline hover:text-brand hover:underline focus-visible:shadow-focus focus-visible:outline-none">
              {a.title}
            </Link>
          </h2>
        </div>
        {a.latest_run ? <StatusBadge status={a.latest_run.status} /> : <Badge>Not run yet</Badge>}
      </div>
      <p className="text-sm text-fg-secondary">
        {TYPE_LABEL[a.activity_type]} · {plural(a.question_count, "question")}
      </p>
      <p className="text-xs text-fg-muted">{settingsSummary(a)}</p>
      {/* One primary per view: the header's "New" is the page's primary; card actions are secondary. */}
      <div className="mt-auto flex flex-wrap gap-2">
        <LinkButton size="sm" variant="secondary" href={`${base}/${seg(a.id)}`} aria-label={`Open control room for ${a.title}`}>
          Open control room
        </LinkButton>
        <LinkButton size="sm" variant="ghost" href={`${base}/${seg(a.id)}/edit`} aria-label={`Edit ${a.title}`}>
          Edit
        </LinkButton>
        <Button size="sm" variant="ghost" onClick={onDuplicate} disabled={busy} aria-label={`Duplicate ${a.title}`}>
          Duplicate
        </Button>
        <Button size="sm" variant="danger-secondary" onClick={onDelete} disabled={busy} aria-label={`Delete ${a.title}`}>
          Delete
        </Button>
      </div>
    </li>
  );
}

/** TRN-020 Engage: activity list. */
export function EngageActivities() {
  const { base } = useEngageScope();
  const toast = useToast();
  const [q, setQ] = useState("");
  const [query, setQuery] = useState("");
  const [type, setType] = useState<ActivityType | "">("");
  const [busy, setBusy] = useState<string | null>(null);
  const [confirm, setConfirm] = useState<ActivitySummary | null>(null);
  const list = useApi<ActivityListData>("engage/activities", { q: query || undefined, type: type || undefined });

  useEffect(() => {
    const t = setTimeout(() => setQuery(q.trim()), 300);
    return () => clearTimeout(t);
  }, [q]);

  const duplicate = async (a: ActivitySummary) => {
    setBusy(a.id);
    try {
      const res = await api.post<Activity>(`engage/activities/${seg(a.id)}/duplicate`, undefined, { idempotencyKey: true });
      if (res.kind === "ok") toast.show({ title: `Created "${res.data.title}"`, tone: "success" });
      await list.reload();
    } catch (err) {
      toast.show({ ...errorText(err, "Couldn't duplicate"), tone: "danger" });
    } finally {
      setBusy(null);
    }
  };

  // Errors propagate to ConfirmDialog, which shows them inline and stays open.
  const remove = async (a: ActivitySummary) => {
    setBusy(a.id);
    try {
      await api.delete(`engage/activities/${seg(a.id)}`);
      toast.show({ title: `Deleted "${a.title}"`, tone: "success" });
      await list.reload();
    } finally {
      setBusy(null);
    }
  };

  const rows = list.data?.data ?? [];

  return (
    <div className="space-y-4">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div className="flex flex-1 flex-col gap-2 sm:flex-row">
          <div className="sm:w-72">
            <label htmlFor="engage-search" className="sr-only">
              Search activities
            </label>
            <Input id="engage-search" type="search" placeholder="Search activities…" value={q} maxLength={100} onChange={(e) => setQ(e.target.value)} />
          </div>
          <div className="sm:w-48">
            <label htmlFor="engage-type" className="sr-only">
              Activity type
            </label>
            <Select
              id="engage-type"
              value={type}
              onChange={(e) => setType(e.target.value as ActivityType | "")}
              options={[{ value: "", label: "All types" }, ...ACTIVITY_TYPES.map((t) => ({ value: t, label: TYPE_LABEL[t] }))]}
            />
          </div>
        </div>
        <div className="flex items-center gap-3">
          {list.data ? <span className="text-sm text-fg-muted">{list.data.counts.total} {list.data.counts.total === 1 ? "activity" : "activities"}</span> : null}
          <NewMenu />
        </div>
      </div>

      {list.loading && !list.data ? (
        <Loading label="Loading activities" />
      ) : list.error ? (
        <ErrorState error={list.error} onRetry={() => void list.reload()} />
      ) : rows.length === 0 ? (
        <EmptyState
          title={query || type ? "No activities match" : "No activities yet"}
          description="Create a quiz, poll, word cloud or survey, then launch it live for your batch."
          action={
            <LinkButton variant="secondary" href={`${base}/new?type=poll`}>
              Create a poll
            </LinkButton>
          }
        />
      ) : (
        <ul className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {rows.map((a) => (
            <ActivityCard key={a.id} activity={a} busy={busy === a.id} onDuplicate={() => void duplicate(a)} onDelete={() => setConfirm(a)} />
          ))}
        </ul>
      )}

      <ConfirmDialog
        open={confirm !== null}
        onClose={() => setConfirm(null)}
        title="Delete activity"
        description={confirm ? `Delete "${confirm.title}"? Its past runs and results go too. This cannot be undone.` : undefined}
        confirmLabel="Delete activity"
        danger
        onConfirm={() => (confirm ? remove(confirm) : undefined)}
      />
    </div>
  );
}
