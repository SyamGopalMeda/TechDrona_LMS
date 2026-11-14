"use client";

import { useEffect, useState } from "react";
import { FormField, Input, Select } from "@/components/ui";
import { useApi } from "@/features/trainer/shared/use-api";
import type { BatchMember, PathsContext } from "../lib/types";

/**
 * Pick learners batch-first: `GET paths/batch-members?batch_id=&q=` lists the active students of
 * one batch the caller may allocate to (WS4 replaced the org-wide member search). The batch list
 * comes from `paths/context`.
 */
export function BatchMemberSearch({
  batches,
  chosen,
  onPick,
  error,
  hint = "Choose a batch, then type at least 2 letters of a name.",
}: {
  batches: PathsContext["batches"];
  chosen: ReadonlySet<string>;
  onPick: (m: BatchMember) => void;
  error?: string;
  hint?: string;
}) {
  const [batchId, setBatchId] = useState("");
  const [q, setQ] = useState("");
  const [query, setQuery] = useState("");
  useEffect(() => {
    const t = setTimeout(() => setQuery(q.trim()), 300);
    return () => clearTimeout(t);
  }, [q]);
  useEffect(() => {
    if (!batchId && batches.length === 1 && batches[0]) setBatchId(batches[0].id);
  }, [batches, batchId]);
  const active = !!batchId && query.length >= 2;
  const res = useApi<{ data: BatchMember[] }>(active ? "paths/batch-members" : null, { batch_id: batchId, q: query });
  return (
    <div className="space-y-2">
      <div className="grid gap-3 sm:grid-cols-2">
        <FormField label="From batch">
          {(p) => (
            <Select
              {...p}
              value={batchId}
              onChange={(e) => setBatchId(e.target.value)}
              placeholder={batches.length ? "Choose a batch…" : "No batches you can allocate to"}
              options={batches.map((b) => ({ value: b.id, label: `${b.name} (${b.code})` }))}
            />
          )}
        </FormField>
        <FormField label="Find learners" hint={hint} error={error}>
          {(p) => <Input {...p} type="search" value={q} disabled={!batchId} onChange={(e) => setQ(e.target.value)} />}
        </FormField>
      </div>
      {active ? (
        <ul className="max-h-40 overflow-y-auto rounded-md border border-line" aria-label="Matching learners">
          {(res.data?.data ?? []).map((m) => (
            <li key={m.user_id}>
              <button
                type="button"
                disabled={chosen.has(m.user_id)}
                onClick={() => onPick(m)}
                className="w-full px-3 py-1.5 text-left text-sm hover:bg-surface-hover disabled:opacity-50"
              >
                {m.full_name || "Learner"}{m.email ? <> <span className="text-fg-muted">{m.email}</span></> : null}
              </button>
            </li>
          ))}
          {res.data && res.data.data.length === 0 ? <li className="px-3 py-1.5 text-sm text-fg-muted">No matches</li> : null}
        </ul>
      ) : null}
    </div>
  );
}
